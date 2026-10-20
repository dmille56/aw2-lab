-- mGBA Lua bridge, protocol v1. Messages are newline-delimited JSON objects.
-- The script binds only to loopback. Socket event delivery is frame-polled by
-- mGBA, so this transport still needs validation while the emulator is paused.
-- luacheck: globals emu socket callbacks

local bridge = {
    protocol_version = 1,
    capabilities = {"connect", "set_keys", "advance_frames", "read_memory"},
    max_message_bytes = 65536,
    port = 43128,
}

-- Small JSON decoder so the bridge does not depend on an optional Lua module.
local json = {}
function json.decode(input)
    local index = 1
    local function whitespace()
        while input:sub(index, index):match("%s") do index = index + 1 end
    end
    local parse_value
    local function parse_string()
        index = index + 1
        local parts = {}
        while index <= #input do
            local char = input:sub(index, index)
            if char == '"' then index = index + 1; return table.concat(parts) end
            if char == "\\" then
                index = index + 1
                local escaped = input:sub(index, index)
                local replacements = {['"'] = '"', ['\\'] = '\\', ['/'] = '/',
                    b = "\b", f = "\f", n = "\n", r = "\r", t = "\t"}
                if escaped == "u" then
                    local code = tonumber(input:sub(index + 1, index + 4), 16)
                    if not code then error("invalid unicode escape") end
                    parts[#parts + 1] = code < 128 and string.char(code) or "?"
                    index = index + 4
                else
                    parts[#parts + 1] = replacements[escaped] or error("invalid escape")
                end
            else
                parts[#parts + 1] = char
            end
            index = index + 1
        end
        error("unterminated string")
    end
    local function parse_object()
        index = index + 1
        local result = {}
        whitespace()
        if input:sub(index, index) == "}" then index = index + 1; return result end
        while true do
            whitespace()
            if input:sub(index, index) ~= '"' then error("expected object key") end
            local key = parse_string()
            whitespace()
            if input:sub(index, index) ~= ":" then error("expected colon") end
            index = index + 1
            result[key] = parse_value()
            whitespace()
            local delimiter = input:sub(index, index)
            index = index + 1
            if delimiter == "}" then return result end
            if delimiter ~= "," then error("expected comma") end
        end
    end
    local function parse_array()
        index = index + 1
        local result = {}
        whitespace()
        if input:sub(index, index) == "]" then index = index + 1; return result end
        while true do
            result[#result + 1] = parse_value()
            whitespace()
            local delimiter = input:sub(index, index)
            index = index + 1
            if delimiter == "]" then return result end
            if delimiter ~= "," then error("expected comma") end
        end
    end
    parse_value = function()
        whitespace()
        local char = input:sub(index, index)
        if char == '"' then return parse_string() end
        if char == "{" then return parse_object() end
        if char == "[" then return parse_array() end
        for word, value in pairs({["true"] = true, ["false"] = false, ["null"] = nil}) do
            if input:sub(index, index + #word - 1) == word then
                index = index + #word
                return value
            end
        end
        local number = input:sub(index):match("^-?%d+%.?%d*[eE]?[+-]?%d*")
        if number and #number > 0 then index = index + #number; return tonumber(number) end
        error("invalid JSON value")
    end
    local value = parse_value()
    whitespace()
    if index <= #input then error("trailing JSON data") end
    return value
end

local function json_quote(value)
    return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
        local escapes = {['\\'] = '\\\\', ['"'] = '\\"', ['\n'] = '\\n',
            ['\r'] = '\\r', ['\t'] = '\\t'}
        return escapes[char] or string.format('\\u%04x', string.byte(char))
    end) .. '"'
end

local function json_encode(value)
    local kind = type(value)
    if value == nil then return "null" end
    if kind == "boolean" or kind == "number" then return tostring(value) end
    if kind == "string" then return json_quote(value) end
    if kind ~= "table" then error("unsupported JSON value") end
    local is_array = #value > 0
    local parts = {}
    if is_array then
        for _, item in ipairs(value) do parts[#parts + 1] = json_encode(item) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    for key, item in pairs(value) do
        parts[#parts + 1] = json_quote(tostring(key)) .. ":" .. json_encode(item)
    end
    return "{" .. table.concat(parts, ",") .. "}"
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
        if type(request.keys) ~= "number" or request.keys < 0 or request.keys > 1023 then
            return error_response(request_id, "invalid_request", "keys must be a 10-bit mask")
        end
        emu:setKeys(request.keys)
        return {id = request_id, ok = true, result = {keys = emu:getKeys()}}
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
        for _ = 1, frames do emu:runFrame() end
        return {id = request_id, ok = true, result = {frame = emu:currentFrame()}}
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

    return error_response(request_id, "unsupported_operation", "Operation is not implemented")
end

local function handle_line(client, line)
    local ok, request = pcall(json.decode, line)
    local response
    if ok then
        local handled, result = pcall(bridge.handle_request, request)
        response = handled and result or error_response(type(request) == "table" and request.id,
            "internal_error", tostring(result))
    else
        response = error_response(nil, "invalid_json", tostring(request))
    end
    local encoded_ok, encoded = pcall(json_encode, response)
    if encoded_ok then
        local message = encoded .. "\n"
        local offset = 1
        while offset <= #message do
            local sent = client:send(message, offset)
            if not sent or sent < offset then return false end
            offset = sent + 1
        end
        return true
    end
    return false
end

local listener = socket.bind("127.0.0.1", bridge.port)
if not listener or not listener:listen(1) then
    error("Could not bind AW2 Lua bridge to 127.0.0.1:" .. bridge.port)
end

-- mGBA socket events are polled once per frame. Process at most one bounded
-- request per frame callback so gameplay and UI callbacks remain schedulable.
local client, buffer
callbacks:add("frame", function()
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
        if not handle_line(client, buffer:sub(1, newline - 1)) then client = nil end
        buffer = ""
    end
end)

-- mGBA's scripting loader can use this global for interactive inspection.
AW2Bridge = bridge

