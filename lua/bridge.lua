-- Minimal mGBA Lua bridge scaffold.
--
-- This file deliberately contains no socket or frame-loop code yet. The first
-- emulator spike must confirm which APIs are available in the pinned mGBA
-- build before a transport adapter is added.

local bridge = {
    protocol_version = 1,
    capabilities = {},
}

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

    return error_response(request_id, "unsupported_operation", "Operation is not implemented")
end

-- mGBA's scripting loader can use this global for interactive inspection.
AW2Bridge = bridge

