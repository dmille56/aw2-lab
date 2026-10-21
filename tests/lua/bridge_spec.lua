-- Busted specs for the Lua bridge. Run with `busted tests/lua` from the repo root.
-- luacheck: globals describe it before_each socket callbacks emu
local pending_chunks = {}
local sent_data = ""
local active_client
local frame_callback
local complete_callback
local queued_request
local reject_queue = false
local frame = 100
local keys = 0
local frames_run = 0
local input_samples = {}
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
    active_client = nil
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
    if name == "bridgePoll" then
        frame_callback = callback
    elseif name == "bridgeComplete" then
        complete_callback = callback
    else
        error("unexpected callback " .. name)
    end
end

_G.emu = {}
function _G.emu.setKeys(_self, value)
    keys = value
end
function _G.emu.getKeys(_self)
    return keys
end
function _G.emu.runFrame(_self)
    input_samples[#input_samples + 1] = keys
    frame = (frame + 1) % 4294967296
    frames_run = frames_run + 1
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

function _G.emu.requestFrames(_self, count, mask, release)
    if reject_queue then return false end
    queued_request = {frames = count, keys = mask, release = release}
    return true
end

-- Model the native frontend: Lua has returned before any frames execute.
local function finish_native_request(actual_frames)
    local request = assert(queued_request)
    queued_request = nil
    keys = request.keys
    for _ = 1, actual_frames or request.frames do
        emu:runFrame()
    end
    if request.release then keys = 0 end
    complete_callback()
end

describe("mGBA Lua bridge", function()
    before_each(function()
        pending_chunks = {}
        sent_data = ""
        active_client = nil
        frame = 100
        keys = 0
        frames_run = 0
        input_samples = {}
        screenshot_path = nil
        queued_request = nil
        reject_queue = false
        dofile("lua/bridge.lua")
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

        local fractional = _G.AW2Bridge.handle_request({
            id = 10, version = 1, operation = "set_keys", keys = 1.5,
        })
        assert.is_false(fractional.ok)
    end)

    it("holds the requested mask for exact native frames and then releases it", function()
        pending_chunks = {
            '{"id":11,"version":1,"operation":"press_keys","keys":1,"frames":4}\n',
        }
        frame_callback() -- Handle the request from the frontend's paused poll loop.

        assert.are.equal(100, frame)
        assert.are.equal("", sent_data)
        assert.are.same({frames = 4, keys = 1, release = true}, queued_request)
        frame_callback() -- Another poll cannot process a second request mid-budget.
        finish_native_request()
        assert.are.equal(104, frame)
        assert.are.equal(4, #input_samples)
        assert.are.same({1, 1, 1, 1}, input_samples)
        assert.are.equal(0, keys)
        assert.is_truthy(sent_data:match('"frames_advanced":4'))
        assert.is_truthy(sent_data:match('"released":true'))
    end)

    it("keeps idle polling responsive without advancing and advances only on request", function()
        frame_callback()
        assert.are.equal(100, frame)

        pending_chunks = {
            '{"id":15,"version":1,"operation":"advance_frames","frames":3}\n',
        }
        frame_callback()
        assert.are.equal(100, frame)
        assert.are.equal("", sent_data)
        finish_native_request()
        assert.are.equal(103, frame)
        assert.are.equal(3, frames_run)
        assert.is_truthy(sent_data:match('"frames_advanced":3'))
    end)

    it("rejects invalid exact key presses without advancing frames", function()
        pending_chunks = {
            '{"id":12,"version":1,"operation":"press_keys","keys":1024,"frames":1}\n',
        }
        frame_callback()
        assert.is_truthy(sent_data:match('"code":"invalid_request"'))
        assert.are.equal(0, frames_run)
        assert.are.equal(0, keys)
    end)

    it("queries the frame without queuing execution or changing held keys", function()
        keys = 513
        local response = _G.AW2Bridge.handle_request({
            id = 4, version = 1, operation = "advance_frames", frames = 0,
        })
        assert.is_true(response.ok)
        assert.are.equal(100, response.result.frame)
        assert.are.equal(0, response.result.frames_advanced)
        assert.are.equal(513, keys)
        assert.is_nil(queued_request)
    end)

    it("preserves held keys during advance and after it finishes", function()
        keys = 513
        pending_chunks = {
            '{"id":16,"version":1,"operation":"advance_frames","frames":2}\n',
        }
        frame_callback()
        finish_native_request()
        assert.are.same({513, 513}, input_samples)
        assert.are.equal(513, keys)
        assert.is_truthy(sent_data:match('"frames_advanced":2'))
    end)

    it("reports native frame mismatches and accepts the next command", function()
        pending_chunks = {
            '{"id":17,"version":1,"operation":"advance_frames","frames":3}\n',
        }
        frame_callback()
        finish_native_request(2)
        assert.is_truthy(sent_data:match('"code":"frame_count_mismatch"'))
        pending_chunks = {'{"id":18,"version":1,"operation":"connect"}\n'}
        frame_callback()
        assert.is_truthy(sent_data:match('"id":18'))
    end)

    it("checks exact counts across frame counter wraparound", function()
        frame = 4294967295
        pending_chunks = {
            '{"id":19,"version":1,"operation":"advance_frames","frames":2}\n',
        }
        frame_callback()
        finish_native_request()
        assert.are.equal(1, frame)
        assert.is_truthy(sent_data:match('"frames_advanced":2'))
    end)

    it("rejects unavailable frame gating without leaving a pending action", function()
        reject_queue = true
        pending_chunks = {
            '{"id":20,"version":1,"operation":"advance_frames","frames":1}\n',
        }
        frame_callback()
        assert.is_truthy(sent_data:match('"code":"frame_gate_unavailable"'))
        reject_queue = false
        pending_chunks = {
            '{"id":21,"version":1,"operation":"advance_frames","frames":1}\n',
        }
        frame_callback()
        finish_native_request()
        assert.is_truthy(sent_data:match('"id":21'))
        assert.are.equal(101, frame)
    end)

    it("rejects invalid frame budgets before queuing native work", function()
        for _, count in ipairs({-1, 601, 1.5, "3"}) do
            local response = _G.AW2Bridge.handle_request({
                id = 22, version = 1, operation = "advance_frames", frames = count,
            })
            assert.is_false(response.ok)
            assert.are.equal("invalid_request", response.error.code)
        end
        local response = _G.AW2Bridge.handle_request({
            id = 23, version = 1, operation = "press_keys", keys = 1, frames = 0,
        })
        assert.is_false(response.ok)
        assert.is_nil(queued_request)
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

    it("accepts another connection after replying to the prior request", function()
        pending_chunks = {
            '{"id":13,"version":1,"operation":"connect"}\n',
            '{"id":14,"version":1,"operation":"connect"}\n',
        }
        frame_callback()
        frame_callback()
        frame_callback()
        frame_callback()
        assert.is_truthy(sent_data:match('"id":13'))
        assert.is_truthy(sent_data:match('"id":14'))
    end)
end)
