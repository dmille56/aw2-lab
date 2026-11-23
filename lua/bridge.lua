-- mGBA Lua bridge, protocol v1. Messages are newline-delimited JSON objects.
-- The script binds only to loopback. The patched frontends call bridgePoll while
-- the core is paused, so requests do not depend on gameplay frames advancing.
-- luacheck: globals emu socket callbacks C

local bridge = {
    protocol_version = 1,
    capabilities = {
        "connect", "set_keys", "press_keys", "advance_frames", "read_memory",
        "write_memory", "read_memory_batch", "screenshot", "reset", "save_state", "load_state",
        "save_state_buffer", "load_state_buffer", "move_map_cursor_batch", "read_battle_ram",
        "verify_map_cursor",
    },
    max_message_bytes = 4718592,
    max_state_bytes = 3145728,
    max_screenshot_bytes = 3145728,
    port = rawget(_G, "AW2_BRIDGE_PORT") or 43128,
}

-- The launcher exports AW2_BRIDGE_INSTANCE for the emulator process it started, so
-- a handshake that does not carry this nonce belongs to a different emulator that
-- happens to be listening on the same bridge port.
bridge.instance = _G.AW2_BRIDGE_INSTANCE or os.getenv("AW2_BRIDGE_INSTANCE")

-- Load the vendored pure-Lua library beside this script; mGBA embeds Lua and
-- does not necessarily use the host's Lua module search path.
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_directory = script_path:match("^(.*[/\\])") or ""
local json = dofile(script_directory .. "dkjson.lua")
local base64 = dofile(script_directory .. "base64.lua")
local pending_action
local cursor_batch

local function decode_json(input)
    local value, position, err = json.decode(input)
    if err then error(err) end
    if input:sub(position):match("%S") then error("trailing JSON data") end
    return value
end

local function error_response(request_id, code, message)
    return {
        id = request_id,
        ok = false,
        error = {
            code = code,
            message = message,
        },
    }
end

-- AW2 US revision 0. Match the free map-input checks in lifecycle.py and
-- ui_state.py. Python validates the full battle snapshot at both ends.
local cursor_directions = {
    [16] = {1, 0}, [32] = {-1, 0}, [64] = {0, -1}, [128] = {0, 1},
}
local function cursor_batch_guard(batch)
    if emu:read32(0x030040D0) ~= 0x08036945 or emu:read32(0x030040EC) ~= 0x080369BD
        or emu:read32(0x03003F3C) ~= 1 or emu:read16(0x030032D8) ~= 13
        or emu:read8(0x030030F0) ~= 0 or emu:read16(0x030040E4) ~= 0
        or emu:read16(0x03003334) ~= 0 or emu:read16(0x030033EC) ~= batch.player
        or emu:read16(0x0201E450) ~= batch.width or emu:read16(0x0201E452) ~= batch.height
        or (batch.map_id ~= nil and emu:read8(0x03003FC2) ~= batch.map_id)
        or emu:read16(0x03004080) ~= batch.day then
        return "phase"
    end
    for index = 0, 31 do
        if emu:read32(0x0200D610 + index * 0x6C) ~= 0 then return "phase" end
    end
    if emu:read16(0x030033E4) ~= batch.x or emu:read16(0x030033E6) ~= batch.y
        or emu:read8(0x03003140) ~= batch.x or emu:read8(0x03003141) ~= batch.y then
        return "cursor"
    end
end

local function integer_in_range(value, lower, upper)
    return type(value) == "number" and value >= lower and value <= upper and value % 1 == 0
end

function bridge.handle_request(request)
    if type(request) ~= "table" then
        return error_response(nil, "invalid_request", "Request must be a table")
    end

    local request_id = request.id
    if request_id == nil then
        return error_response(nil, "invalid_request", "Request is missing id")
    end

    if request.version ~= bridge.protocol_version then
        return error_response(request_id, "unsupported_version", "Unsupported protocol version")
    end

    if type(request.operation) ~= "string" then
        return error_response(request_id, "invalid_request", "Request is missing operation")
    end

    if request.expected_instance ~= nil and request.expected_instance ~= bridge.instance then
        return error_response(request_id, "instance_mismatch", "The emulator instance changed")
    end

    if request.operation == "connect" then
        return {
            id = request_id,
            ok = true,
            result = {
                protocol_version = bridge.protocol_version,
                capabilities = bridge.capabilities,
                -- The launcher exports a per-process nonce, so a handshake that
                -- does not carry it belongs to some other emulator that happens to
                -- answer on the same port.
                instance = bridge.instance,
                instance_guard = request.guard_next == true and bridge.instance ~= nil
                    and request.expected_instance == bridge.instance or nil,
            },
        }
    end

    if request.operation == "set_keys" then
        if type(request.keys) ~= "number" or request.keys < 0 or request.keys > 1023
            or request.keys % 1 ~= 0 then
            return error_response(request_id, "invalid_request", "keys must be a 10-bit mask")
        end
        emu:setKeys(request.keys)
        return {id = request_id, ok = true, result = {keys = emu:getKeys()}}
    end

    if request.operation == "verify_map_cursor" then
        local frame = emu:currentFrame()
        if not integer_in_range(request.width, 1, 48)
            or not integer_in_range(request.height, 1, 39)
            or not integer_in_range(request.x, 0, request.width - 1)
            or not integer_in_range(request.y, 0, request.height - 1)
            or not integer_in_range(request.player, 1, 4)
            or not integer_in_range(request.day, 0, 65535) then
            return error_response(request_id, "invalid_request", "invalid map cursor probe")
        end
        return {
            id = request_id, ok = true,
            result = {frame = frame, matches = cursor_batch_guard(request) == nil},
        }
    end

    if request.operation == "move_map_cursor_batch" then
        local direction = cursor_directions[request.keys]
        local gap, steps = request.gap, request.steps
        local x, y, start_frame = request.x, request.y, request.start_frame
        if not direction or not integer_in_range(gap, 8, 60)
            or not integer_in_range(steps, 2, 8) or not integer_in_range(x, 0, 47)
            or not integer_in_range(y, 0, 38)
            or not integer_in_range(start_frame, 0, 4294967295) then
            return error_response(request_id, "invalid_request", "invalid map cursor batch")
        end
        if pending_action or cursor_batch then
            return error_response(request_id, "busy", "a frame request is already pending")
        end
        if emu:currentFrame() ~= start_frame then
            return error_response(
                request_id, "frame_count_mismatch", "map cursor start frame changed"
            )
        end
        local width, height = emu:read16(0x0201E450), emu:read16(0x0201E452)
        local player = emu:read16(0x030033EC)
        if width > 48 or height > 39 or not integer_in_range(player, 1, 4)
            or not integer_in_range(x, 0, width - 1) or not integer_in_range(y, 0, height - 1)
            or not integer_in_range(x + direction[1] * steps, 0, width - 1)
            or not integer_in_range(y + direction[2] * steps, 0, height - 1) then
            return error_response(
                request_id, "invalid_request", "map cursor batch exceeds map bounds"
            )
        end
        cursor_batch = {
            id = request_id, start_frame = start_frame, x = x, y = y, keys = request.keys,
            direction = direction, gap = gap, steps = steps, taps = 0, press = false,
            width = width, height = height, player = player, map_id = emu:read8(0x03003FC2),
            day = emu:read16(0x03004080),
        }
        return {id = request_id, ok = true, result = {deferred = true}}
    end

    if request.operation == "press_keys" or request.operation == "advance_frames" then
        local frames = request.frames
        if type(frames) ~= "number" or frames < 0 or frames > 600 or frames % 1 ~= 0
            or (request.operation == "press_keys" and frames == 0) then
            return error_response(request_id, "invalid_request", "invalid frame count")
        end
        local keys = request.keys
        if request.operation == "press_keys"
            and (type(keys) ~= "number" or keys < 0 or keys > 1023 or keys % 1 ~= 0) then
            return error_response(request_id, "invalid_request", "keys must be a 10-bit mask")
        end
        if request.operation == "advance_frames" then
            keys = emu:getKeys()
        end
        if frames == 0 then
            local frame = emu:currentFrame()
            return {
                id = request_id,
                ok = true,
                result = {start_frame = frame, frame = frame, frames_advanced = 0},
            }
        end
        if pending_action then
            return error_response(request_id, "busy", "a frame request is already pending")
        end
        local start_frame = emu:currentFrame()
        local release_keys = request.operation == "press_keys"
        local queued, accepted = pcall(function()
            return emu:requestFrames(frames, keys, release_keys)
        end)
        if not queued or not accepted then
            return error_response(
                request_id, "frame_gate_unavailable", "frame gate rejected request"
            )
        end
        pending_action = {
            id = request_id,
            operation = request.operation,
            frames = frames,
            keys = keys,
            start_frame = start_frame,
        }
        return {
            id = request_id,
            ok = true,
            result = {deferred = true},
        }
    end

    if request.operation == "write_memory" then
        local address, bytes = request.address, request.bytes
        if type(address) ~= "number" or address % 1 ~= 0
            or type(bytes) ~= "table" or #bytes < 1 or #bytes > 256 then
            return error_response(request_id, "invalid_request", "invalid memory write")
        end
        local last = address + #bytes
        if not ((address >= 0x02000000 and last <= 0x02040000)
            or (address >= 0x03000000 and last <= 0x03008000)) then
            return error_response(request_id, "invalid_request", "write requires work RAM")
        end
        for _, value in ipairs(bytes) do
            if type(value) ~= "number" or value % 1 ~= 0 or value < 0 or value > 255 then
                return error_response(request_id, "invalid_request", "invalid byte")
            end
        end
        for index, value in ipairs(bytes) do emu:write8(address + index - 1, value) end
        return {id = request_id, ok = true, result = {written = #bytes}}
    end

    if request.operation == "read_memory" then
        local address, length = request.address, request.length
        if type(address) ~= "number" or address < 0 or address % 1 ~= 0
            or type(length) ~= "number" or length < 0 or length > 4096 or length % 1 ~= 0 then
            return error_response(request_id, "invalid_request", "invalid address or length")
        end
        local bytes = {string.byte(emu:readRange(address, length), 1, length)}
        return {id = request_id, ok = true, result = {address = address, bytes = bytes}}
    end

    if request.operation == "read_battle_ram" then
        local frame = emu:currentFrame()
        local ewram = emu:readRange(0x02000000, 0x40000)
        local iwram = emu:readRange(0x03000000, 0x8000)
        if emu:currentFrame() ~= frame then
            return error_response(request_id, "frame_count_mismatch", "battle RAM frame changed")
        end
        if type(ewram) ~= "string" or #ewram ~= 0x40000
            or type(iwram) ~= "string" or #iwram ~= 0x8000 then
            return error_response(request_id, "incomplete_memory_read", "incomplete battle RAM")
        end
        return {
            id = request_id, ok = true,
            result = {
                frame = frame,
                ewram_base64 = base64.encode(ewram),
                iwram_base64 = base64.encode(iwram),
            },
        }
    end

    if request.operation == "read_memory_batch" then
        local ranges = request.ranges
        if type(ranges) ~= "table" or #ranges < 1 or #ranges > 64 then
            return error_response(
                request_id, "invalid_request", "ranges must contain 1 to 64 entries"
            )
        end
        local total = 0
        local results = {}
        for index, range in ipairs(ranges) do
            local address, length = range.address, range.length
            if type(address) ~= "number" or address < 0 or address > 4294967295
                or address % 1 ~= 0 or type(length) ~= "number" or length < 0
                or length > 4096 or length % 1 ~= 0 or address + length > 4294967296 then
                return error_response(request_id, "invalid_request", "invalid memory range")
            end
            total = total + length
            if total > 4096 then
                return error_response(
                    request_id, "invalid_request", "combined read exceeds 4096 bytes"
                )
            end
            results[index] = {
                address = address,
                bytes = {string.byte(emu:readRange(address, length), 1, length)},
            }
        end
        return {
            id = request_id, ok = true,
            result = {frame = emu:currentFrame(), ranges = results},
        }
    end

    if request.operation == "reset" then
        emu:setKeys(0)
        emu:reset()
        return {id = request_id, ok = true, result = {frame = emu:currentFrame()}}
    end

    if request.operation == "save_state_buffer" then
        local ok, state = pcall(function() return emu:saveStateBuffer(C.SAVESTATE.ALL) end)
        if not ok or type(state) ~= "string" or #state == 0 then
            return error_response(request_id, "state_operation_failed", tostring(state))
        end
        if #state > bridge.max_state_bytes then
            return error_response(request_id, "state_too_large", "State buffer exceeds 3 MiB")
        end
        return {
            id = request_id,
            ok = true,
            result = {state_base64 = base64.encode(state), frame = emu:currentFrame()},
        }
    end

    if request.operation == "load_state_buffer" then
        local encoded = request.state_base64
        if type(encoded) ~= "string" or #encoded == 0
            or #encoded > math.ceil(bridge.max_state_bytes / 3) * 4 then
            return error_response(request_id, "invalid_request", "invalid state buffer")
        end
        local state = base64.decode(encoded)
        if #state == 0 or #state > bridge.max_state_bytes or base64.encode(state) ~= encoded then
            return error_response(request_id, "invalid_request", "invalid state buffer encoding")
        end
        local ok, loaded = pcall(function()
            return emu:loadStateBuffer(state, C.SAVESTATE.ALL)
        end)
        if not ok or not loaded then
            return error_response(request_id, "state_operation_failed", tostring(loaded))
        end
        return {id = request_id, ok = true, result = {frame = emu:currentFrame()}}
    end

    if request.operation == "save_state" or request.operation == "load_state" then
        local filename = request.filename
        if type(filename) ~= "string" or #filename == 0 or #filename > 4096 then
            return error_response(
                request_id, "invalid_request", "filename must be a non-empty path"
            )
        end
        local ok, success = pcall(function()
            if request.operation == "save_state" then
                local state = emu:saveStateBuffer(C.SAVESTATE.ALL)
                if type(state) ~= "string" or #state == 0 then
                    return false
                end
                local file, open_error = io.open(filename, "wb")
                if not file then error(open_error) end
                local write_ok, write_error = file:write(state)
                local close_ok, close_error = file:close()
                if not write_ok then error(write_error) end
                if not close_ok then error(close_error) end
                return true
            end
            local file, open_error = io.open(filename, "rb")
            if not file then error(open_error) end
            local state = file:read("*a")
            local close_ok, close_error = file:close()
            if not close_ok then error(close_error) end
            if type(state) ~= "string" or #state == 0 then return false end
            return emu:loadStateBuffer(state, C.SAVESTATE.ALL)
        end)
        if not ok or not success then
            return error_response(request_id, "state_operation_failed", tostring(success))
        end
        return {
            id = request_id,
            ok = true,
            result = {frame = emu:currentFrame()},
        }
    end

    if request.operation == "screenshot" then
        local filename = request.filename
        if type(filename) ~= "string" or #filename == 0 or #filename > 4096 then
            return error_response(
                request_id,
                "invalid_request",
                "filename must be a non-empty path"
            )
        end
        local capture_ok, image = pcall(function() return emu:screenshotToImage() end)
        if not capture_ok then
            return error_response(request_id, "screenshot_failed", tostring(image))
        end
        if not image then
            return error_response(request_id, "screenshot_failed", "No video frame is available")
        end
        local save_ok, saved, save_error = pcall(function() return image:save(filename, "PNG") end)
        if not save_ok or not saved then
            return error_response(
                request_id,
                "screenshot_failed",
                tostring(save_ok and (save_error or "Could not save PNG image") or saved)
            )
        end
        local file, open_error = io.open(filename, "rb")
        if not file then
            return error_response(request_id, "screenshot_failed", tostring(open_error))
        end
        local png = file:read("*a")
        file:close()
        if #png > bridge.max_screenshot_bytes then
            return error_response(
                request_id,
                "screenshot_too_large",
                "Screenshot exceeds the size limit"
            )
        end
        return {id = request_id, ok = true, result = {png_base64 = base64.encode(png)}}
    end

    return error_response(request_id, "unsupported_operation", "Operation is not implemented")
end

local function send_response(client, response)
    local encoded_ok, encoded = pcall(json.encode, response)
    if not encoded_ok then return false end
    local message = encoded .. "\n"
    local offset = 1
    while offset <= #message do
        local sent, _, partial = client:send(message, offset, #message)
        if sent and sent >= offset then
            offset = sent + 1
        elseif partial and partial >= offset then
            offset = partial + 1
        else
            return false
        end
    end
    return true
end

local function close_client(client)
    if client then pcall(function() client:close() end) end
end

local function handle_line(client, line)
    local ok, request = pcall(decode_json, line)
    local response
    if ok then
        local handled, result = pcall(bridge.handle_request, request)
        response = handled and result or error_response(type(request) == "table" and request.id,
            "internal_error", tostring(result))
    else
        response = error_response(nil, "invalid_json", tostring(request))
    end
    if response.ok and response.result and response.result.deferred then
        return true
    end
    send_response(client, response)
    local keep_open = response.ok and response.result and response.result.instance_guard
    return false, keep_open
end

local listener = socket.bind("127.0.0.1", bridge.port)
if not listener or not listener:listen(1) then
    error("Could not bind AW2 Lua bridge to 127.0.0.1:" .. bridge.port)
end

-- The pinned headless and Qt frontends invoke bridgePoll from an idle loop while
-- the core is paused. Gameplay runs only inside explicit advance/input commands.
local client, buffer

local function finish_request(response)
    send_response(client, response)
    close_client(client)
    client = nil
    buffer = nil
end

local function finish_cursor_batch(batch, reason)
    emu:setKeys(0)
    cursor_batch = nil
    local frame = emu:currentFrame()
    finish_request({
        id = batch.id, ok = true, result = {
            frame = frame,
            taps = batch.taps,
            stop = reason,
            released = emu:getKeys() == 0,
        },
    })
end

local function poll_cursor_batch(batch)
    local stop = cursor_batch_guard(batch)
    if stop then
        finish_cursor_batch(batch, stop)
        return
    end
    local frames, keys = batch.gap, 0
    if batch.press then frames, keys = 1, batch.keys end
    local queued, accepted = pcall(function() return emu:requestFrames(frames, keys, true) end)
    if not queued or not accepted then
        emu:setKeys(0)
        cursor_batch = nil
        finish_request(error_response(
            batch.id, "frame_gate_unavailable", "frame gate rejected batch"
        ))
    end
end

function bridge.poll()
    if cursor_batch then
        poll_cursor_batch(cursor_batch)
        return
    end
    if pending_action then return end
    if not client then
        client = listener:accept()
        buffer = ""
        if not client then return end
    end
    if not client:hasdata() then return end
    local chunk, receive_error, partial = client:receive(4096)
    chunk = chunk or partial
    if not chunk then
        if receive_error then
            close_client(client)
            client = nil
            buffer = nil
        end
        return
    end
    buffer = buffer .. chunk
    if #buffer > bridge.max_message_bytes then
        send_response(
            client, error_response(nil, "message_too_large", "Request exceeds the size limit")
        )
        close_client(client)
        client = nil
        buffer = nil
        return
    end
    local newline = buffer:find("\n", 1, true)
    if newline then
        local deferred, keep_open = handle_line(client, buffer:sub(1, newline - 1))
        if deferred then return end
        if keep_open then
            buffer = ""
            return
        end
        close_client(client)
        client = nil
        buffer = nil
    elseif receive_error and receive_error ~= "timeout" then
        close_client(client)
        client = nil
        buffer = nil
    end
end

local function complete_cursor_batch(batch)
    if batch.press then
        batch.taps = batch.taps + 1
        batch.x = batch.x + batch.direction[1]
        batch.y = batch.y + batch.direction[2]
    end
    local advanced = batch.taps * (batch.gap + 1) + (batch.press and 0 or batch.gap)
    if emu:currentFrame() ~= (batch.start_frame + advanced) % 4294967296 then
        emu:setKeys(0)
        cursor_batch = nil
        finish_request(error_response(
            batch.id, "frame_count_mismatch", "map cursor batch frame drift"
        ))
        return
    end
    local stop = cursor_batch_guard(batch)
    if stop or batch.taps == batch.steps then
        finish_cursor_batch(batch, stop or "complete")
        return
    end
    batch.press = not batch.press
end

function bridge.complete()
    if cursor_batch then
        complete_cursor_batch(cursor_batch)
        return
    end
    if not pending_action then return end
    local action = pending_action
    pending_action = nil
    local frame = emu:currentFrame()
    local frames_advanced = (frame - action.start_frame) % 4294967296
    local response
    if frames_advanced ~= action.frames then
        response = error_response(
            action.id,
            "frame_count_mismatch",
            "emulator advanced " .. frames_advanced .. " frames instead of " .. action.frames
        )
    else
        local result = {
            start_frame = action.start_frame,
            frame = frame,
            frames_advanced = frames_advanced,
        }
        if action.operation == "press_keys" then
            result.keys = action.keys
            result.frames = action.frames
            result.released = emu:getKeys() == 0
        end
        response = {
            id = action.id,
            ok = true,
            result = result,
        }
    end
    finish_request(response)
end

callbacks:add("bridgePoll", bridge.poll)
callbacks:add("bridgeComplete", bridge.complete)

-- mGBA's scripting loader can use this global for interactive inspection.
AW2Bridge = bridge

