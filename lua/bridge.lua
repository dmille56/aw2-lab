-- mGBA Lua bridge, protocol v1. Messages are newline-delimited JSON objects.
-- The script binds only to loopback. The patched frontends call bridgePoll while
-- the core is paused, so requests do not depend on gameplay frames advancing.
-- luacheck: globals emu socket callbacks

local bridge = {
    protocol_version = 1,
    capabilities = {
        "connect", "set_keys", "press_keys", "advance_frames", "read_memory", "screenshot",
    },
    max_message_bytes = 4718592,
    max_screenshot_bytes = 3145728,
    port = 43128,
}

-- Load the vendored pure-Lua library beside this script; mGBA embeds Lua and
-- does not necessarily use the host's Lua module search path.
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_directory = script_path:match("^(.*[/\\])") or ""
local json = dofile(script_directory .. "dkjson.lua")
local base64 = dofile(script_directory .. "base64.lua")
local pending_action

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

    if request.operation == "connect" then
        return {
            id = request_id,
            ok = true,
            result = {
                protocol_version = bridge.protocol_version,
                capabilities = bridge.capabilities,
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

    if request.operation == "read_memory" then
        local address, length = request.address, request.length
        if type(address) ~= "number" or address < 0 or address % 1 ~= 0
            or type(length) ~= "number" or length < 0 or length > 4096 or length % 1 ~= 0 then
            return error_response(request_id, "invalid_request", "invalid address or length")
        end
        local bytes = {string.byte(emu:readRange(address, length), 1, length)}
        return {id = request_id, ok = true, result = {address = address, bytes = bytes}}
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
        local ok, err = pcall(function() emu:screenshot(filename) end)
        if not ok then
            return error_response(request_id, "screenshot_failed", tostring(err))
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
        local sent = client:send(message, offset)
        if not sent or sent < offset then return false end
        offset = sent + 1
    end
    return true
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
    return false
end

local listener = socket.bind("127.0.0.1", bridge.port)
if not listener or not listener:listen(1) then
    error("Could not bind AW2 Lua bridge to 127.0.0.1:" .. bridge.port)
end

-- The pinned headless and Qt frontends invoke bridgePoll from an idle loop while
-- the core is paused. Gameplay runs only inside explicit advance/input commands.
local client, buffer
function bridge.poll()
    if pending_action then return end
    if not client then
        client = listener:accept()
        buffer = ""
        if not client then return end
    end
    if not client:hasdata() then return end
    local chunk = client:receive(4096)
    if not chunk then
        client = nil
        buffer = nil
        return
    end
    buffer = buffer .. chunk
    if #buffer > bridge.max_message_bytes then
        client = nil
        buffer = nil
        return
    end
    local newline = buffer:find("\n", 1, true)
    if newline then
        local deferred = handle_line(client, buffer:sub(1, newline - 1))
        if deferred then return end
        -- The Python client uses one request per connection.
        client = nil
        buffer = nil
    end
end

function bridge.complete()
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
    send_response(client, response)
    client = nil
    buffer = nil
end

callbacks:add("bridgePoll", bridge.poll)
callbacks:add("bridgeComplete", bridge.complete)

-- mGBA's scripting loader can use this global for interactive inspection.
AW2Bridge = bridge

