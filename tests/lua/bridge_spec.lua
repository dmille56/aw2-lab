-- Busted specs for the Lua bridge. Run with `busted tests/lua` from the repo root.
-- luacheck: globals describe it before_each socket callbacks emu
local pending_chunks = {}
local sent_data = ""
local active_client
local frame_callback
local frame = 100
local keys = 0
local screenshot_path

local client = {}
function client.hasdata(_self)
    return #pending_chunks > 0
end
function client.receive(_self)
    return table.remove(pending_chunks, 1)
end
function client.send(_self, data, first)
    sent_data = sent_data .. data:sub(first or 1)
    return #data
end

local listener = {}
function listener.listen(_self, backlog)
    assert(backlog == 1)
    return 1
end
function listener.accept(_self)
    if active_client then return nil end
    active_client = client
    return client
end

_G.socket = {}
function _G.socket.bind(host, port)
    assert(host == "127.0.0.1")
    assert(port == 43128)
    return listener
end

_G.callbacks = {}
function _G.callbacks.add(_self, name, callback)
    assert(name == "frame")
    frame_callback = callback
end

_G.emu = {}
function _G.emu.setKeys(_self, value)
    keys = value
end
function _G.emu.getKeys(_self)
    return keys
end
function _G.emu.runFrame(_self)
    frame = frame + 1
end
function _G.emu.currentFrame(_self)
    return frame
end
function _G.emu.readRange(_self, address, length)
    return string.rep(string.char(address % 256), length)
end
function _G.emu.screenshot(_self, filename)
    screenshot_path = filename
    local file = assert(io.open(filename, "wb"))
    file:write("png?")
    file:close()
end

dofile("lua/bridge.lua")

describe("mGBA Lua bridge", function()
    before_each(function()
        pending_chunks = {}
        sent_data = ""
        active_client = nil
        frame = 100
        keys = 0
        screenshot_path = nil
    end)

    it("encodes base64 values with and without padding", function()
        local base64 = dofile("lua/base64.lua")
        assert.are.equal("", base64.encode(""))
        assert.are.equal("Zg==", base64.encode("f"))
        assert.are.equal("Zm8=", base64.encode("fo"))
        assert.are.equal("Zm9v", base64.encode("foo"))
        assert.are.equal("Zm9vYg==", base64.encode("foob"))
        assert.are.equal("Zm9vYmE=", base64.encode("fooba"))
        assert.are.equal("Zm9vYmFy", base64.encode("foobar"))
    end)

    it("reports protocol version and capabilities", function()
        local response = _G.AW2Bridge.handle_request({id = 1, version = 1, operation = "connect"})
        assert.is_true(response.ok)
        assert.are.equal(1, response.result.protocol_version)
        assert.are.equal("connect", response.result.capabilities[1])
    end)

    it("accepts valid key masks and rejects masks outside 10 bits", function()
        local response = _G.AW2Bridge.handle_request({
            id = 2, version = 1, operation = "set_keys", keys = 513,
        })
        assert.is_true(response.ok)
        assert.are.equal(513, response.result.keys)

        local invalid = _G.AW2Bridge.handle_request({
            id = 3, version = 1, operation = "set_keys", keys = 1024,
        })
        assert.is_false(invalid.ok)
        assert.are.equal("invalid_request", invalid.error.code)
    end)

    it("advances the requested number of frames", function()
        local response = _G.AW2Bridge.handle_request({
            id = 4, version = 1, operation = "advance_frames", frames = 3,
        })
        assert.is_true(response.ok)
        assert.are.equal(103, response.result.frame)
    end)

    it("reads the requested memory range", function()
        local response = _G.AW2Bridge.handle_request({
            id = 5, version = 1, operation = "read_memory", address = 0x02000000, length = 3,
        })
        assert.is_true(response.ok)
        assert.are.equal(0x02000000, response.result.address)
        assert.are.equal(3, #response.result.bytes)
        assert.are.equal(0, response.result.bytes[1])
    end)

    it("captures a screenshot to the requested file", function()
        local filename = os.tmpname()
        local response = _G.AW2Bridge.handle_request({
            id = 9, version = 1, operation = "screenshot", filename = filename,
        })
        assert.is_true(response.ok)
        assert.are.equal(filename, screenshot_path)
        assert.are.equal("cG5nPw==", response.result.png_base64)
        os.remove(filename)
    end)

    it("returns structured errors for invalid versions and operations", function()
        local bad_version = _G.AW2Bridge.handle_request({
            id = 6, version = 2, operation = "connect",
        })
        assert.is_false(bad_version.ok)
        assert.are.equal("unsupported_version", bad_version.error.code)

        local unsupported = _G.AW2Bridge.handle_request({
            id = 7, version = 1, operation = "unknown",
        })
        assert.is_false(unsupported.ok)
        assert.are.equal("unsupported_operation", unsupported.error.code)
    end)

    it("handles fragmented JSON requests over the socket", function()
        pending_chunks = {
            '{"id":8,"version":1,"operation":"connect"',
            "}\n",
        }
        frame_callback()
        assert.are.equal("", sent_data)
        frame_callback()
        assert.is_truthy(sent_data:match("\n$"))
        assert.is_truthy(sent_data:match('"id":8'))
        assert.is_truthy(sent_data:match('"ok":true'))
    end)
end)
