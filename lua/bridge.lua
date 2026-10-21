-- mGBA Lua bridge, protocol v1. Messages are newline-delimited JSON objects.
-- The script binds only to loopback. Socket event delivery is frame-polled by
-- mGBA, so this transport still needs validation while the emulator is paused.
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

    if request.operation == "press_keys" then
        local keys, frames = request.keys, request.frames
        if type(keys) ~= "number" or keys < 0 or keys > 1023 or keys % 1 ~= 0 then
            return error_response(request_id, "invalid_request", "keys must be a 10-bit mask")
        end
        if type(frames) ~= "number" or frames < 1 or frames > 600 or frames % 1 ~= 0 then
            return error_response(
                request_id,
                "invalid_request",
                "frames must be an integer from 1 to 600"
            )
        end
        emu:setKeys(keys)
        return {
            id = request_id,
            ok = true,
            result = {
                keys = keys,
                frames = frames,
                start_frame = emu:currentFrame(),
                deferred = true,
            },
        }
    end

    if request.operation == "advance_frames" then
        local frames = request.frames
        if type(frames) ~= "number" or frames < 0 or frames > 600 or frames % 1 ~= 0 then
            return error_response(
                request_id,
                "invalid_request",
                "frames must be an integer from 0 to 600"
            )
        end
        local start_frame = emu:currentFrame()
        for _ = 1, frames do emu:runFrame() end
        return {
            id = request_id,
            ok = true,
            result = {
                start_frame = start_frame,
                frame = emu:currentFrame(),
                frames_advanced = frames,
            },
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

local pending_press

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
        pending_press = {
            client = client,
            id = response.id,
            keys = response.result.keys,
            frames = response.result.frames,
            start_frame = response.result.start_frame,
            advanced = 0,
        }
        return true, true
    end
    local encoded_ok, encoded = pcall(json.encode, response)
    if encoded_ok then
        local message = encoded .. "\n"
        local offset = 1
        while offset <= #message do
            local sent = client:send(message, offset)
            if not sent or sent < offset then return false end
            offset = sent + 1
        end
        return true, false
    end
    return false, false
end

local listener = socket.bind("127.0.0.1", bridge.port)
if not listener or not listener:listen(1) then
    error("Could not bind AW2 Lua bridge to 127.0.0.1:" .. bridge.port)
end

-- mGBA socket events are polled once per frame. Process at most one bounded
-- request per frame callback so gameplay and UI callbacks remain schedulable.
local client, buffer
callbacks:add("frame", function()
    if pending_press then
        pending_press.advanced = pending_press.advanced + 1
        if pending_press.advanced >= pending_press.frames then
            emu:setKeys(0)
            local completed = pending_press
            pending_press = nil
            local response = {
                id = completed.id,
                ok = true,
                result = {
                    keys = completed.keys,
                    frames = completed.frames,
                    start_frame = completed.start_frame,
                    frame = emu:currentFrame(),
                    frames_advanced = completed.advanced,
                    released = emu:getKeys() == 0,
                },
            }
            local encoded_ok, encoded = pcall(json.encode, response)
            if encoded_ok then
                local message = encoded .. "\n"
                local offset = 1
                while offset <= #message do
                    local sent = completed.client:send(message, offset)
                    if not sent or sent < offset then break end
                    offset = sent + 1
                end
            end
            client = nil
            buffer = nil
        end
        return
    end
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
        local replied, deferred = handle_line(client, buffer:sub(1, newline - 1))
        if deferred then return end
        -- The Python client uses one request per connection. Drop the accepted
        -- socket after replying so the next request can be accepted promptly.
        client = nil
        buffer = ""
        if not replied then buffer = nil end
    end
end)

-- mGBA's scripting loader can use this global for interactive inspection.
AW2Bridge = bridge

