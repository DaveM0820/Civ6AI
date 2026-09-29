-- Civ6Ai utilities: logging, JSON, file bridge helpers.
Civ6Ai_Util = Civ6Ai_Util or {}

function Civ6Ai_Util.Log(message)
  print("CIV6AI|" .. tostring(message))
end

function Civ6Ai_Util.EscapeJson(value)
  if value == nil then
    return "null"
  end
  if type(value) == "boolean" then
    return value and "true" or "false"
  end
  if type(value) == "number" then
    return tostring(value)
  end
  local text = tostring(value)
  text = text:gsub("\\", "\\\\")
  text = text:gsub('"', '\\"')
  text = text:gsub("\n", "\\n")
  text = text:gsub("\r", "")
  return '"' .. text .. '"'
end

function Civ6Ai_Util.JsonArray(items)
  local parts = {}
  for _, item in ipairs(items) do
    table.insert(parts, Civ6Ai_Util.EscapeJson(item))
  end
  return "[" .. table.concat(parts, ",") .. "]"
end

function Civ6Ai_Util.HasIo()
  return io ~= nil and io.open ~= nil
end

function Civ6Ai_Util._GameCoreIo()
  return ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil
end

function Civ6Ai_Util.LogDir()
  if Civ6Ai_Paths and Civ6Ai_Paths.LogDir and Civ6Ai_Paths.LogDir ~= "" then
    return Civ6Ai_Paths.LogDir:gsub("\\", "/")
  end
  if Civ6Ai_Runtime and Civ6Ai_Runtime.LogDir and Civ6Ai_Runtime.LogDir ~= "" then
    return Civ6Ai_Runtime.LogDir:gsub("\\", "/")
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil and ExposedMembers.Civ6Ai.Runtime ~= nil then
    local runtime = ExposedMembers.Civ6Ai.Runtime
    if runtime.LogDir and runtime.LogDir ~= "" then
      return runtime.LogDir:gsub("\\", "/")
    end
  end
  if os and os.getenv then
    local localApp = os.getenv("LOCALAPPDATA")
    if localApp ~= nil and localApp ~= "" then
      return localApp:gsub("\\", "/") .. "/Firaxis Games/Sid Meier's Civilization VI/Logs"
    end
  end
  return nil
end

function Civ6Ai_Util._LogMirrorPath(path)
  local logDir = Civ6Ai_Util.LogDir()
  if logDir == nil or path == nil or path == "" then
    return nil
  end
  local rel = string.match(path, "/civ6ai/(.+)$")
  if rel == nil then
    rel = string.match(path, "civ6ai/(.+)$")
  end
  if rel == nil then
    rel = string.match(path, "([^/]+)$")
  end
  if rel == nil or rel == "" then
    return nil
  end
  return logDir .. "/civ6ai/" .. rel
end

function Civ6Ai_Util._CandidatePaths(path)
  local paths = {}
  if path ~= nil and path ~= "" then
    table.insert(paths, path)
  end
  local mirror = Civ6Ai_Util._LogMirrorPath(path)
  if mirror ~= nil and mirror ~= path then
    table.insert(paths, mirror)
  end
  return paths
end

function Civ6Ai_Util._TryInGameOpen(path, mode)
  if io == nil or io.open == nil or path == nil then
    return nil
  end
  local file = io.open(path, mode)
  if file ~= nil then
    return file
  end
  local alt = path:gsub("/", "\\")
  if alt ~= path then
    return io.open(alt, mode)
  end
  return nil
end

function Civ6Ai_Util._OpenWrite(path, content)
  local file = Civ6Ai_Util._TryInGameOpen(path, "w")
  if file ~= nil then
    file:write(content)
    file:close()
    return true
  end
  if Civ6Ai_Util._GameCoreIo() and ExposedMembers.Civ6Ai.WriteFile ~= nil then
    if ExposedMembers.Civ6Ai.WriteFile(path, content) then
      return true
    end
  end
  return false
end

function Civ6Ai_Util.WriteTextFile(path, content)
  for _, candidate in ipairs(Civ6Ai_Util._CandidatePaths(path)) do
    if Civ6Ai_Util._OpenWrite(candidate, content) then
      if candidate ~= path then
        Civ6Ai_Util.Log("io|wrote_mirror|" .. tostring(candidate))
      end
      return true
    end
  end
  Civ6Ai_Util.Log("io|write_failed|" .. tostring(path))
  return false
end

function Civ6Ai_Util.ReadTextFile(path)
  for _, candidate in ipairs(Civ6Ai_Util._CandidatePaths(path)) do
    local file = Civ6Ai_Util._TryInGameOpen(candidate, "r")
    if file ~= nil then
      local content = file:read("*a")
      file:close()
      return content
    end
    if Civ6Ai_Util._GameCoreIo() and ExposedMembers.Civ6Ai.ReadFile ~= nil then
      local text = ExposedMembers.Civ6Ai.ReadFile(candidate)
      if text ~= nil then
        return text
      end
    end
  end
  return nil
end

function Civ6Ai_Util.FileExists(path)
  local text = Civ6Ai_Util.ReadTextFile(path)
  return text ~= nil
end

function Civ6Ai_Util.AppendTextLine(path, line)
  for _, candidate in ipairs(Civ6Ai_Util._CandidatePaths(path)) do
    local file = Civ6Ai_Util._TryInGameOpen(candidate, "a")
    if file ~= nil then
      file:write(line .. "\n")
      file:close()
      return true
    end
    if Civ6Ai_Util._GameCoreIo() and ExposedMembers.Civ6Ai.AppendFile ~= nil then
      if ExposedMembers.Civ6Ai.AppendFile(candidate, line) then
        return true
      end
    end
  end
  Civ6Ai_Util.Log("io|append_failed|" .. tostring(path) .. "|" .. tostring(line))
  return false
end

-- Base64 via 3-byte arithmetic and table.concat. The old bit-string version
-- concatenated one growing string per byte (O(n^2)); a 27 KB snapshot made
-- gigabytes of garbage per seat and froze Civ6 at 30 GB by turn 3.
local _B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local _B64Chars = {}
local _B64Lookup = {}
for i = 1, 64 do
  local ch = string.sub(_B64, i, i)
  _B64Chars[i - 1] = ch
  _B64Lookup[ch] = i - 1
end

function Civ6Ai_Util.Base64Encode(data)
  if data == nil then
    return ""
  end
  local out = {}
  local n = #data
  local i = 1
  while i <= n do
    local b1 = string.byte(data, i)
    local b2 = (i + 1 <= n) and string.byte(data, i + 1) or 0
    local b3 = (i + 2 <= n) and string.byte(data, i + 2) or 0
    local v = b1 * 65536 + b2 * 256 + b3
    local c1 = math.floor(v / 262144) % 64
    local c2 = math.floor(v / 4096) % 64
    local c3 = math.floor(v / 64) % 64
    local c4 = v % 64
    out[#out + 1] = _B64Chars[c1] .. _B64Chars[c2]
      .. ((i + 1 <= n) and _B64Chars[c3] or "=")
      .. ((i + 2 <= n) and _B64Chars[c4] or "=")
    i = i + 3
  end
  return table.concat(out)
end

function Civ6Ai_Util.Base64Decode(encoded)
  if encoded == nil or encoded == "" then
    return nil
  end
  local out = {}
  local vals = {}
  for i = 1, #encoded do
    local ch = string.sub(encoded, i, i)
    if ch == "=" then
      break
    end
    local value = _B64Lookup[ch]
    if value == nil then
      return nil
    end
    vals[#vals + 1] = value
    if #vals == 4 then
      local v = vals[1] * 262144 + vals[2] * 4096 + vals[3] * 64 + vals[4]
      out[#out + 1] = string.char(math.floor(v / 65536) % 256, math.floor(v / 256) % 256, v % 256)
      vals = {}
    end
  end
  if #vals == 2 then
    local v = vals[1] * 262144 + vals[2] * 4096
    out[#out + 1] = string.char(math.floor(v / 65536) % 256)
  elseif #vals == 3 then
    local v = vals[1] * 262144 + vals[2] * 4096 + vals[3] * 64
    out[#out + 1] = string.char(math.floor(v / 65536) % 256, math.floor(v / 256) % 256)
  end
  return table.concat(out)
end

function Civ6Ai_Util.DumpBlob(kind, meta, content)
  if content == nil or content == "" then
    return false
  end
  local encoded = Civ6Ai_Util.Base64Encode(content)
  local chunkSize = 180
  local chunks = math.ceil(#encoded / chunkSize)
  if chunks < 1 then
    chunks = 1
  end
  local session = tostring(meta.session or "")
  local player = tostring(meta.player or 0)
  local turn = tostring(meta.turn or 0)
  local live = tostring(meta.live or 0)
  local id = session .. "_" .. player .. "_" .. turn .. "_" .. tostring(kind)
  Civ6Ai_Util.Log(
    "blob|begin|"
      .. tostring(kind)
      .. "|"
      .. id
      .. "|"
      .. tostring(chunks)
      .. "|"
      .. live
      .. "|"
      .. player
      .. "|"
      .. turn
      .. "|"
      .. session
  )
  local index = 0
  local pos = 1
  while pos <= #encoded do
    local chunk = string.sub(encoded, pos, pos + chunkSize - 1)
    Civ6Ai_Util.Log("blob|c|" .. id .. "|" .. tostring(index) .. "|" .. chunk)
    index = index + 1
    pos = pos + chunkSize
  end
  Civ6Ai_Util.Log("blob|end|" .. id)
  return true
end

function Civ6Ai_Util.ProbeIo()
  local logDir = Civ6Ai_Util.LogDir()
  Civ6Ai_Util.Log(
    "io|probe|ingame="
      .. tostring(Civ6Ai_Util.HasIo())
      .. "|logdir="
      .. tostring(logDir)
  )
  if logDir == nil then
    Civ6Ai_Util._fileIoOk = false
    return false
  end
  local probePath = logDir .. "/civ6ai/io_probe.txt"
  if Civ6Ai_Util.WriteTextFile(probePath, "ok\n") then
    Civ6Ai_Util._fileIoOk = true
    Civ6Ai_Util.Log("io|probe_ok|" .. probePath)
    return true
  end
  Civ6Ai_Util._fileIoOk = false
  Civ6Ai_Util.Log("io|probe_failed|" .. probePath)
  return false
end

function Civ6Ai_Util.FileIoOk()
  return Civ6Ai_Util._fileIoOk == true
end

function Civ6Ai_Util.CanReadHostFiles()
  if Civ6Ai_Util.FileIoOk() then
    return true
  end
  if Civ6Ai_Util._GameCoreIo() and ExposedMembers.Civ6Ai.ReadFile ~= nil then
    local runtime = ExposedMembers.Civ6Ai.Runtime
    if runtime ~= nil and runtime.GameCoreIo == true then
      return true
    end
  end
  return false
end

Civ6Ai_Util._ticks = Civ6Ai_Util._ticks or {}
Civ6Ai_Util._pumping = false
Civ6Ai_Util._tickUpdateContext = nil

function Civ6Ai_Util._GetTickUpdateContext()
  if ContextPtr ~= nil and ContextPtr.SetUpdate ~= nil then
    return ContextPtr
  end
  return nil
end

function Civ6Ai_Util._PumpTicks()
  if #Civ6Ai_Util._ticks == 0 then
    return 0
  end
  local remaining = {}
  for _, tick in ipairs(Civ6Ai_Util._ticks) do
    local keep = false
    local ok, result = pcall(tick)
    if ok then
      keep = result == true
    else
      Civ6Ai_Util.Log("tick|error|" .. tostring(result))
    end
    if keep then
      table.insert(remaining, tick)
    end
  end
  Civ6Ai_Util._ticks = remaining
  return #remaining
end

function Civ6Ai_Util._ClearTickUpdate()
  local ctx = Civ6Ai_Util._tickUpdateContext
  if ctx ~= nil and ctx.ClearUpdate ~= nil then
    ctx:ClearUpdate()
  end
  Civ6Ai_Util._tickUpdateContext = nil
  Civ6Ai_Util._pumping = false
  Civ6Ai_Util._framePumpActive = false
end

function Civ6Ai_Util._StartFramePump()
  if Civ6Ai_Util._framePumpActive then
    return
  end
  local ctx = Civ6Ai_Util._GetTickUpdateContext()
  if ctx == nil or ctx.SetUpdate == nil then
    return
  end
  Civ6Ai_Util._framePumpActive = true
  Civ6Ai_Util._tickUpdateContext = ctx
  ctx:SetUpdate(function()
    if #Civ6Ai_Util._ticks == 0 then
      Civ6Ai_Util._ClearTickUpdate()
      Civ6Ai_Util._framePumpActive = false
      return
    end
    Civ6Ai_Util._OnSystemUpdate()
  end)
end

function Civ6Ai_Util._EnsureTickPump()
  if ContextPtr == nil then
    return
  end
  local count = Civ6Ai_Util._PumpTicks()
  if count == 0 then
    Civ6Ai_Util._ClearTickUpdate()
    Civ6Ai_Util._framePumpActive = false
    return
  end
  Civ6Ai_Util._StartFramePump()
end

function Civ6Ai_Util._OnSystemUpdate()
  -- Civ6 hot-reloads a changed InGame Lua file; the old context's event handler
  -- keeps firing with its globals gone (Civ6Ai_Util nil): 10k+ errors, one per
  -- frame, until the game was reloaded. Bail quietly instead.
  if Civ6Ai_Util == nil or Civ6Ai_Util._ticks == nil then
    return
  end
  if #Civ6Ai_Util._ticks == 0 then
    return
  end
  local remaining = Civ6Ai_Util._PumpTicks()
  if remaining > 0 then
    Civ6Ai_Util._EnsureTickPump()
  else
    Civ6Ai_Util._ClearTickUpdate()
  end
end

function Civ6Ai_Util.InitializeTickPump()
  if Civ6Ai_Util._tickPumpHooks then
    return
  end
  Civ6Ai_Util._tickPumpHooks = true
  if Events ~= nil and Events.SystemUpdateUI ~= nil then
    Events.SystemUpdateUI.Add(Civ6Ai_Util._OnSystemUpdate)
  end
  if Events ~= nil and Events.GameCoreEventPublishComplete ~= nil then
    Events.GameCoreEventPublishComplete.Add(Civ6Ai_Util._OnSystemUpdate)
  end
  if Events ~= nil and Events.LocalPlayerTurnBegin ~= nil then
    Events.LocalPlayerTurnBegin.Add(function()
      Civ6Ai_Util._framePumpActive = false
      Civ6Ai_Util._EnsureTickPump()
    end)
  end
end

function Civ6Ai_Util.ScheduleTick(fn)
  if fn == nil then
    return
  end
  table.insert(Civ6Ai_Util._ticks, fn)
  Civ6Ai_Util._EnsureTickPump()
end

function Civ6Ai_Util.JoinPath(...)
  local parts = {...}
  local path = parts[1] or ""
  for i = 2, #parts do
    local segment = parts[i]
    if segment ~= nil and segment ~= "" then
      if path:sub(-1) ~= "/" and path:sub(-1) ~= "\\" then
        path = path .. "/"
      end
      path = path .. segment
    end
  end
  return path:gsub("\\", "/")
end

function Civ6Ai_Util.SleepSeconds(seconds)
  local deadline = (os and os.clock and os.clock()) and (os.clock() + seconds) or 0
  while os and os.clock and os.clock() < deadline do
    -- tight poll; Gate 0 only
  end
end

function Civ6Ai_Util.PlayerId(playerID)
  return "PLAYER_" .. tostring(playerID)
end

function Civ6Ai_Util.PlotId(x, y)
  return "PLOT_" .. tostring(x) .. "_" .. tostring(y)
end

function Civ6Ai_Util.ParsePlotId(plotId)
  if plotId == nil or type(plotId) ~= "string" then
    return nil
  end
  local x, y = string.match(plotId, "^PLOT_(%d+)_(%d+)$")
  if x == nil or y == nil then
    return nil
  end
  return {x = tonumber(x), y = tonumber(y)}
end

function Civ6Ai_Util.JsonArrayList()
  return setmetatable({}, { __json_array = true })
end

function Civ6Ai_Util.JsonNull()
  return setmetatable({}, { __json_null = true })
end

function Civ6Ai_Util._IsJsonNull(value)
  if type(value) ~= "table" then
    return false
  end
  local meta = getmetatable(value)
  return meta ~= nil and meta.__json_null == true
end

function Civ6Ai_Util._IsJsonArray(value)
  if type(value) ~= "table" then
    return false
  end
  local meta = getmetatable(value)
  if meta ~= nil and meta.__json_array then
    return true
  end
  return #value > 0
end

function Civ6Ai_Util.EncodeJsonValue(value)
  if Civ6Ai_Util._IsJsonNull(value) or value == nil then
    return "null"
  end
  if type(value) == "table" then
    if Civ6Ai_Util._IsJsonArray(value) then
      local items = {}
      for _, item in ipairs(value) do
        table.insert(items, Civ6Ai_Util.EncodeJsonValue(item))
      end
      return "[" .. table.concat(items, ",") .. "]"
    end
    local parts = {}
    for key, child in pairs(value) do
      table.insert(parts, Civ6Ai_Util.EscapeJson(key) .. ":" .. Civ6Ai_Util.EncodeJsonValue(child))
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  if type(value) == "boolean" then
    return value and "true" or "false"
  end
  if type(value) == "number" then
    local rounded = value >= 0 and math.floor(value + 0.5) or math.ceil(value - 0.5)
    return tostring(rounded)
  end
  return Civ6Ai_Util.EscapeJson(value)
end

function Civ6Ai_Util.EncodeJsonObject(payload)
  local parts = {}
  for key, value in pairs(payload) do
    table.insert(parts, Civ6Ai_Util.EscapeJson(key) .. ":" .. Civ6Ai_Util.EncodeJsonValue(value))
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

function Civ6Ai_Util.AppendJsonLine(path, payload)
  local line = Civ6Ai_Util.EncodeJsonObject(payload)
  if Civ6Ai_Util.AppendTextLine(path, line) then
    return true
  end
  Civ6Ai_Util.Log("jsonl|" .. line)
  return false
end
