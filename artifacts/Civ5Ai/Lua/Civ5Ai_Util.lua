-- Civ6Ai utilities: logging, JSON, file bridge helpers.
Civ5Ai_Util = Civ5Ai_Util or {}

function Civ5Ai_Util.Log(message)
  print("CIV5AI|" .. tostring(message))
end

-- Full step I/O for one managed seat. Files hold the entire payload; Lua.log
-- gets a size line plus the body when it is short enough not to CTD lua51.
function Civ5Ai_Util.LogStep(playerDir, playerID, turn, step, direction, body)
  local text = body == nil and "" or tostring(body)
  local name = "t" .. tostring(turn) .. "_" .. tostring(step) .. "_" .. tostring(direction) .. ".txt"
  local path = nil
  if playerDir ~= nil and playerDir ~= "" then
    path = Civ5Ai_Util.JoinPath(playerDir, name)
    Civ5Ai_Util.WriteTextFile(path, text)
  end
  Civ5Ai_Util.Log(
    "bridge|step|"
      .. tostring(step)
      .. "|"
      .. tostring(direction)
      .. "|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(turn)
      .. "|bytes="
      .. tostring(#text)
      .. "|path="
      .. tostring(path or "")
  )
  if #text > 0 and #text <= 3500 then
    Civ5Ai_Util.Log(
      "bridge|step|"
        .. tostring(step)
        .. "|"
        .. tostring(direction)
        .. "|body|"
        .. text
    )
  end
  return path
end

function Civ5Ai_Util.EscapeJson(value)
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

function Civ5Ai_Util.ParseJsonQuotedString(text, quoteIndex)
  if text == nil or quoteIndex == nil then
    return nil, quoteIndex
  end
  local i = quoteIndex + 1
  local out = {}
  while i <= #text do
    local ch = string.sub(text, i, i)
    if ch == '"' then
      return table.concat(out), i + 1
    end
    if ch == "\\" then
      local nxt = string.sub(text, i + 1, i + 1)
      if nxt == "n" then
        table.insert(out, "\n")
      elseif nxt == "t" then
        table.insert(out, "\t")
      elseif nxt == '"' then
        table.insert(out, '"')
      elseif nxt == "\\" then
        table.insert(out, "\\")
      else
        table.insert(out, nxt)
      end
      i = i + 2
    else
      table.insert(out, ch)
      i = i + 1
    end
  end
  return table.concat(out), i
end

function Civ5Ai_Util.ReadJsonStringField(objectText, key)
  if objectText == nil or key == nil then
    return nil
  end
  local pattern = '"' .. key .. '"%s*:%s*"'
  local _, stop = string.find(objectText, pattern)
  if stop == nil then
    return nil
  end
  local value = Civ5Ai_Util.ParseJsonQuotedString(objectText, stop)
  return value
end

function Civ5Ai_Util.JsonArray(items)
  local parts = {}
  for _, item in ipairs(items) do
    table.insert(parts, Civ5Ai_Util.EscapeJson(item))
  end
  return "[" .. table.concat(parts, ",") .. "]"
end

function Civ5Ai_Util.HasIo()
  return io ~= nil and io.open ~= nil
end

function Civ5Ai_Util._GameCoreIo()
  return ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil
end

function Civ5Ai_Util.LogDir()
  if Civ5Ai_Paths and Civ5Ai_Paths.LogDir and Civ5Ai_Paths.LogDir ~= "" then
    return (Civ5Ai_Paths.LogDir:gsub("\\", "/"))
  end
  if Civ5Ai_Runtime and Civ5Ai_Runtime.LogDir and Civ5Ai_Runtime.LogDir ~= "" then
    return (Civ5Ai_Runtime.LogDir:gsub("\\", "/"))
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil and ExposedMembers.Civ5Ai.Runtime ~= nil then
    local runtime = ExposedMembers.Civ5Ai.Runtime
    if runtime.LogDir and runtime.LogDir ~= "" then
      return (runtime.LogDir:gsub("\\", "/"))
    end
  end
  if Civ5Ai_Paths and Civ5Ai_Paths.Civ5AiRoot and Civ5Ai_Paths.Civ5AiRoot ~= "" and Civ5Ai_Paths.Civ5AiRoot ~= "civ5ai" then
    local root = Civ5Ai_Paths.Civ5AiRoot:gsub("\\", "/")
    local parent = string.match(root, "^(.*)/civ5ai$")
    if parent ~= nil and parent ~= "" then
      return parent .. "/Logs"
    end
  end
  if os and os.getenv then
    local home = os.getenv("USERPROFILE") or os.getenv("HOME")
    if home ~= nil and home ~= "" then
      local docs = home:gsub("\\", "/") .. "/Documents/My Games/Sid Meier's Civilization V/Logs"
      return docs
    end
  end
  if os and os.getenv then
    local localApp = os.getenv("LOCALAPPDATA")
    if localApp ~= nil and localApp ~= "" then
      return localApp:gsub("\\", "/") .. "/Firaxis Games/Sid Meier's Civilization V/Logs"
    end
  end
  return nil
end

function Civ5Ai_Util._ManagedSeatIds()
  local seats = {}
  if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ManagedSeats ~= nil and Civ5Ai_Paths.ManagedSeats ~= "" then
    for seat in string.gmatch(tostring(Civ5Ai_Paths.ManagedSeats), "%d+") do
      table.insert(seats, tonumber(seat))
    end
  end
  if #seats == 0 then
    for seat = 0, 7 do
      table.insert(seats, seat)
    end
  end
  return seats
end

function Civ5Ai_Util.ApplyPendingFilename(playerID)
  if playerID == nil then
    return "apply_pending.lua"
  end
  return "apply_pending_p" .. tostring(playerID) .. ".lua"
end

function Civ5Ai_Util.ApplyPendingCandidatePaths(playerID)
  local paths = {}
  local seen = {}
  local function add(path)
    if path == nil or path == "" or seen[path] then
      return
    end
    seen[path] = true
    table.insert(paths, path)
  end
  if playerID ~= nil then
    local filename = Civ5Ai_Util.ApplyPendingFilename(playerID)
    local logDir = Civ5Ai_Util.LogDir()
    if logDir ~= nil and logDir ~= "" then
      add(logDir .. "/civ5ai/" .. filename)
    end
    if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.Civ5AiRoot ~= nil and Civ5Ai_Paths.Civ5AiRoot ~= "" then
      add((tostring(Civ5Ai_Paths.Civ5AiRoot):gsub("\\", "/")) .. "/" .. filename)
    end
    add(filename)
    add("apply_pending.lua")
  end
  if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ApplyPendingPaths ~= nil then
    for _, path in ipairs(Civ5Ai_Paths.ApplyPendingPaths) do
      add(path)
    end
  end
  return paths
end

function Civ5Ai_Util.AllApplyPendingDiskPaths()
  local paths = {}
  local seen = {}
  local function add(path)
    if path == nil or path == "" or seen[path] then
      return
    end
    seen[path] = true
    table.insert(paths, path)
  end
  for _, seat in ipairs(Civ5Ai_Util._ManagedSeatIds()) do
    for _, path in ipairs(Civ5Ai_Util.ApplyPendingCandidatePaths(seat)) do
      add(path)
    end
  end
  return paths
end

function Civ5Ai_Util._LogMirrorPath(path)
  local logDir = Civ5Ai_Util.LogDir()
  if logDir == nil or path == nil or path == "" then
    return nil
  end
  local rel = string.match(path, "/[Cc]iv5[Aa]i/runtime/(.+)$")
  if rel == nil then
    rel = string.match(path, "/civ5ai/(.+)$")
  end
  if rel == nil then
    rel = string.match(path, "civ5ai/(.+)$")
  end
  if rel == nil then
    rel = string.match(path, "([^/]+)$")
  end
  if rel == nil or rel == "" then
    return nil
  end
  return logDir .. "/civ5ai/" .. rel
end

function Civ5Ai_Util._CandidatePaths(path)
  local paths = {}
  if path ~= nil and path ~= "" then
    table.insert(paths, path)
  end
  local mirror = Civ5Ai_Util._LogMirrorPath(path)
  if mirror ~= nil and mirror ~= path then
    table.insert(paths, mirror)
  end
  return paths
end

function Civ5Ai_Util._TryInGameOpen(path, mode)
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

function Civ5Ai_Util._OpenWrite(path, content)
  if Game ~= nil and Game.WriteTextFile ~= nil then
    if Game.WriteTextFile(path, content) then
      return true
    end
    local alt = path:gsub("/", "\\")
    if alt ~= path and Game.WriteTextFile(alt, content) then
      return true
    end
  end
  local file = Civ5Ai_Util._TryInGameOpen(path, "w")
  if file ~= nil then
    file:write(content)
    file:close()
    return true
  end
  if Civ5Ai_Util._GameCoreIo() and ExposedMembers.Civ5Ai.WriteFile ~= nil then
    if ExposedMembers.Civ5Ai.WriteFile(path, content) then
      return true
    end
  end
  return false
end

function Civ5Ai_Util.WriteTextFile(path, content)
  Civ5Ai_Util._writeFailedLogged = Civ5Ai_Util._writeFailedLogged or {}
  for _, candidate in ipairs(Civ5Ai_Util._CandidatePaths(path)) do
    if Civ5Ai_Util._OpenWrite(candidate, content) then
      if candidate ~= path then
        Civ5Ai_Util.Log("io|wrote_mirror|" .. tostring(candidate))
      end
      Civ5Ai_Util._writeFailedLogged[path] = nil
      return true
    end
  end
  if not Civ5Ai_Util._writeFailedLogged[path] then
    Civ5Ai_Util._writeFailedLogged[path] = true
    Civ5Ai_Util.Log("io|write_failed|" .. tostring(path))
  end
  return false
end

function Civ5Ai_Util.ReadTextFile(path)
  if path == nil or path == "" then
    return nil
  end
  -- Host-written files (apply JSON, apply_pending.lua) live on disk and update
  -- every turn. Prefer Game.ReadTextFile: in-game io.open is blocked on many
  -- My Games / OneDrive paths unless the patched DLL exposes GameCoreIo.
  for _, candidate in ipairs(Civ5Ai_Util._CandidatePaths(path)) do
    if Game ~= nil and Game.ReadTextFile ~= nil then
      local text = Game.ReadTextFile(candidate)
      if (text == nil or text == "") then
        local alt = candidate:gsub("/", "\\")
        if alt ~= candidate then
          text = Game.ReadTextFile(alt)
        end
      end
      if text ~= nil and text ~= "" then
        return text
      end
    end
    local file = Civ5Ai_Util._TryInGameOpen(candidate, "r")
    if file ~= nil then
      local content = file:read("*a")
      file:close()
      if content ~= nil and content ~= "" then
        return content
      end
    end
    if Civ5Ai_Util._GameCoreIo() and ExposedMembers.Civ5Ai.ReadFile ~= nil then
      local text = ExposedMembers.Civ5Ai.ReadFile(candidate)
      if text ~= nil and text ~= "" then
        return text
      end
    end
  end
  return nil
end

function Civ5Ai_Util.DeleteFile(path)
  if path == nil or path == "" then
    return
  end
  for _, candidate in ipairs(Civ5Ai_Util._CandidatePaths(path)) do
    if os ~= nil and os.remove ~= nil then
      pcall(os.remove, candidate)
      local alt = candidate:gsub("/", "\\")
      if alt ~= candidate then
        pcall(os.remove, alt)
      end
    end
    -- Retail Civ5 Lua often cannot os.remove under Documents. Empty the
    -- mailbox so HostInbox recovery cannot re-parse a stale apply forever.
    if Civ5Ai_Util.WriteTextFile ~= nil then
      pcall(Civ5Ai_Util.WriteTextFile, candidate, "")
      local alt = candidate:gsub("/", "\\")
      if alt ~= candidate then
        pcall(Civ5Ai_Util.WriteTextFile, alt, "")
      end
    end
  end
end

function Civ5Ai_Util.FileExists(path)
  local text = Civ5Ai_Util.ReadTextFile(path)
  return text ~= nil
end

function Civ5Ai_Util.AppendTextLine(path, line)
  for _, candidate in ipairs(Civ5Ai_Util._CandidatePaths(path)) do
    local file = Civ5Ai_Util._TryInGameOpen(candidate, "a")
    if file ~= nil then
      file:write(line .. "\n")
      file:close()
      return true
    end
    if Civ5Ai_Util._GameCoreIo() and ExposedMembers.Civ5Ai.AppendFile ~= nil then
      if ExposedMembers.Civ5Ai.AppendFile(candidate, line) then
        return true
      end
    end
  end
  Civ5Ai_Util.Log("io|append_failed|" .. tostring(path) .. "|" .. tostring(line))
  return false
end

function Civ5Ai_Util.Base64Encode(data)
  if data == nil or data == "" then
    return ""
  end
  local alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  local out = {}
  local n = #data
  local i = 1
  while i <= n do
    local a = string.byte(data, i)
    local b = string.byte(data, i + 1)
    local c = string.byte(data, i + 2)
    local n24 = a * 65536
    if b ~= nil then
      n24 = n24 + b * 256
    end
    if c ~= nil then
      n24 = n24 + c
    end
    local i1 = math.floor(n24 / 262144) + 1
    local i2 = math.floor(n24 / 4096) % 64 + 1
    local i3 = math.floor(n24 / 64) % 64 + 1
    local i4 = n24 % 64 + 1
    out[#out + 1] = string.sub(alphabet, i1, i1)
    out[#out + 1] = string.sub(alphabet, i2, i2)
    if b ~= nil then
      out[#out + 1] = string.sub(alphabet, i3, i3)
    else
      out[#out + 1] = "="
    end
    if c ~= nil then
      out[#out + 1] = string.sub(alphabet, i4, i4)
    else
      out[#out + 1] = "="
    end
    i = i + 3
  end
  return table.concat(out)
end

function Civ5Ai_Util.Base64Decode(encoded)
  if encoded == nil or encoded == "" then
    return nil
  end
  local alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  local lookup = {}
  for i = 1, #alphabet do
    lookup[string.byte(alphabet, i)] = i - 1
  end
  local out = {}
  local acc = 0
  local bits = 0
  for i = 1, #encoded do
    local b = string.byte(encoded, i)
    if b == 61 then
      break
    end
    local value = lookup[b]
    if value == nil then
      return nil
    end
    acc = acc * 64 + value
    bits = bits + 6
    if bits >= 8 then
      bits = bits - 8
      local shift = 2 ^ bits
      out[#out + 1] = string.char(math.floor(acc / shift) % 256)
      acc = acc % shift
    end
  end
  return table.concat(out)
end

function Civ5Ai_Util.ProbeIo()
  local logDir = Civ5Ai_Util.LogDir()
  Civ5Ai_Util.Log(
    "io|probe|ingame="
      .. tostring(Civ5Ai_Util.HasIo())
      .. "|logdir="
      .. tostring(logDir)
  )
  if logDir == nil then
    Civ5Ai_Util._fileIoOk = false
    return false
  end
  local probePath = logDir .. "/civ5ai/io_probe.txt"
  if Civ5Ai_Util.WriteTextFile(probePath, "ok\n") then
    Civ5Ai_Util._fileIoOk = true
    Civ5Ai_Util.Log("io|probe_ok|" .. probePath)
    return true
  end
  Civ5Ai_Util._fileIoOk = false
  Civ5Ai_Util.Log("io|probe_failed|" .. probePath)
  return false
end

function Civ5Ai_Util.FileIoOk()
  return Civ5Ai_Util._fileIoOk == true
end

function Civ5Ai_Util.CpOverlayOk()
  return Game ~= nil
    and Game.WriteTextFile ~= nil
    and Game.Civ5AiFinishSeat ~= nil
    and Game.Civ5AiHoldSeat ~= nil
end

function Civ5Ai_Util.RequireCpOverlay()
  if Civ5Ai_Util.CpOverlayOk() then
    Civ5Ai_Util.Log("config|cp_overlay_ok")
    return true
  end
  Civ5Ai_Util.Log(
    "config|cp_overlay_missing|write_text_file="
      .. tostring(Game ~= nil and Game.WriteTextFile ~= nil)
      .. "|finish_seat="
      .. tostring(Game ~= nil and Game.Civ5AiFinishSeat ~= nil)
      .. "|hold_seat="
      .. tostring(Game ~= nil and Game.Civ5AiHoldSeat ~= nil)
      .. "|hint=close Civ5 and run Invoke-Install-Civ5CommunityPatch.ps1"
  )
  return false
end

function Civ5Ai_Util.CanReadHostFiles()
  if Game ~= nil and Game.ReadTextFile ~= nil then
    return true
  end
  if Civ5Ai_Util.FileIoOk() then
    return true
  end
  if Civ5Ai_Util._GameCoreIo() and ExposedMembers.Civ5Ai.ReadFile ~= nil then
    local runtime = ExposedMembers.Civ5Ai.Runtime
    if runtime ~= nil and runtime.GameCoreIo == true then
      return true
    end
  end
  return false
end

Civ5Ai_Util._ticks = Civ5Ai_Util._ticks or {}
Civ5Ai_Util._ticksDuringPump = nil
Civ5Ai_Util._framePumpActive = false
Civ5Ai_Util._tickUpdateContext = nil
Civ5Ai_Util._pumpingTicks = false

function Civ5Ai_Util._GetTickUpdateContext()
  if ContextPtr ~= nil and ContextPtr.SetUpdate ~= nil then
    return ContextPtr
  end
  return nil
end

function Civ5Ai_Util._PumpTicks()
  if Civ5Ai_Util._pumpingTicks then
    return #Civ5Ai_Util._ticks
  end
  if #Civ5Ai_Util._ticks == 0 then
    return 0
  end
  Civ5Ai_Util._pumpingTicks = true
  Civ5Ai_Util._ticksDuringPump = {}
  local work = Civ5Ai_Util._ticks
  Civ5Ai_Util._ticks = {}
  local remaining = {}
  for _, tick in ipairs(work) do
    local keep = false
    local ok, result = pcall(tick)
    if ok then
      keep = result == true
    else
      Civ5Ai_Util.Log("tick|error|" .. tostring(result))
    end
    if keep then
      table.insert(remaining, tick)
    end
  end
  local scheduled = Civ5Ai_Util._ticksDuringPump
  Civ5Ai_Util._ticksDuringPump = nil
  Civ5Ai_Util._pumpingTicks = false
  for _, tick in ipairs(remaining) do
    table.insert(scheduled, tick)
  end
  Civ5Ai_Util._ticks = scheduled
  return #Civ5Ai_Util._ticks
end

function Civ5Ai_Util._ClearTickUpdate()
  local ctx = Civ5Ai_Util._tickUpdateContext
  if ctx ~= nil and ctx.ClearUpdate ~= nil then
    ctx:ClearUpdate()
  end
  Civ5Ai_Util._tickUpdateContext = nil
  Civ5Ai_Util._framePumpActive = false
end

function Civ5Ai_Util._StartFramePump()
  if Civ5Ai_Util._framePumpActive then
    return
  end
  local ctx = Civ5Ai_Util._GetTickUpdateContext()
  if ctx == nil or ctx.SetUpdate == nil then
    return
  end
  Civ5Ai_Util._framePumpActive = true
  Civ5Ai_Util._tickUpdateContext = ctx
  ctx:SetUpdate(function()
    if #Civ5Ai_Util._ticks == 0 then
      Civ5Ai_Util._ClearTickUpdate()
      return
    end
    Civ5Ai_Util._OnSystemUpdate()
  end)
  Civ5Ai_Util.Log("tick|frame_pump")
end

function Civ5Ai_Util._EnsureTickPump()
  -- HostInbox and DiploCorner SetUpdate call PumpTicks. Do not bind InGame
  -- ContextPtr or SystemUpdateUI â€” nested pumps overflow lua51.
end

function Civ5Ai_Util._OnSystemUpdate()
  if #Civ5Ai_Util._ticks == 0 then
    return
  end
  local remaining = Civ5Ai_Util._PumpTicks()
  if remaining > 0 then
    Civ5Ai_Util._EnsureTickPump()
  else
    Civ5Ai_Util._ClearTickUpdate()
  end
end

-- HostInbox/DiploCorner are other Lua states; they call ExposedMembers.Civ5Ai.PumpTicks.
function Civ5Ai_Util.BindTickPumpContext(ctx)
  if ctx == nil or ctx.SetUpdate == nil then
    return
  end
  -- FPS: permanent SetUpdate must not PumpTicks every frame when the queue is empty.
  local minInterval = 0.25
  local last = 0
  ctx:SetUpdate(function()
    if Civ5Ai_Util._ticks == nil or #Civ5Ai_Util._ticks == 0 then
      return
    end
    local now = (os and os.clock and os.clock()) or 0
    if (now - last) < minInterval then
      return
    end
    last = now
    if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil and ExposedMembers.Civ5Ai.PumpTicks ~= nil then
      ExposedMembers.Civ5Ai.PumpTicks()
    end
  end)
  Civ5Ai_Util.Log("tick|pump_context")
end

function Civ5Ai_Util.InitializeTickPump()
  if Civ5Ai_Util._tickPumpHooks then
    return
  end
  Civ5Ai_Util._tickPumpHooks = true
  Civ5Ai_Util.Log("tick|pump_ui_contexts")
end

function Civ5Ai_Util.ScheduleTick(fn)
  if fn == nil then
    return
  end
  if Civ5Ai_Util._ticksDuringPump ~= nil then
    table.insert(Civ5Ai_Util._ticksDuringPump, fn)
  else
    table.insert(Civ5Ai_Util._ticks, fn)
  end
  Civ5Ai_Util._EnsureTickPump()
end

function Civ5Ai_Util.JoinPath(...)
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
  -- Parentheses drop gsub's replacement count. Without that, a table whose last
  -- field is JoinPath(...) also stores a number, and ReadTextFile then dies.
  return (path:gsub("\\", "/"))
end

function Civ5Ai_Util.SleepSeconds(seconds)
  local deadline = (os and os.clock and os.clock()) and (os.clock() + seconds) or 0
  while os and os.clock and os.clock() < deadline do
    -- tight poll; Gate 0 only
  end
end

function Civ5Ai_Util.PlayerId(playerID)
  return "PLAYER_" .. tostring(playerID)
end

function Civ5Ai_Util.PlotId(x, y)
  return "PLOT_" .. tostring(x) .. "_" .. tostring(y)
end

function Civ5Ai_Util.ParsePlotId(plotId)
  -- Two return values so `local x, y = ParsePlotId(...)` works.
  -- A table return left y nil, so t0 map anchors never included unit tiles.
  if plotId == nil or type(plotId) ~= "string" then
    return nil
  end
  local x, y = string.match(plotId, "^PLOT_(%d+)_(%d+)$")
  if x == nil or y == nil then
    return nil
  end
  return tonumber(x), tonumber(y)
end

function Civ5Ai_Util.JsonArrayList()
  return setmetatable({}, { __json_array = true })
end

function Civ5Ai_Util.JsonNull()
  return setmetatable({}, { __json_null = true })
end

function Civ5Ai_Util._IsJsonNull(value)
  if type(value) ~= "table" then
    return false
  end
  local meta = getmetatable(value)
  return meta ~= nil and meta.__json_null == true
end

function Civ5Ai_Util._IsJsonArray(value)
  if type(value) ~= "table" then
    return false
  end
  local meta = getmetatable(value)
  if meta ~= nil and meta.__json_array then
    return true
  end
  return #value > 0
end

function Civ5Ai_Util.EncodeJsonValue(value)
  if Civ5Ai_Util._IsJsonNull(value) or value == nil then
    return "null"
  end
  if type(value) == "table" then
    if Civ5Ai_Util._IsJsonArray(value) then
      local items = {}
      for _, item in ipairs(value) do
        table.insert(items, Civ5Ai_Util.EncodeJsonValue(item))
      end
      return "[" .. table.concat(items, ",") .. "]"
    end
    local parts = {}
    for key, child in pairs(value) do
      table.insert(parts, Civ5Ai_Util.EscapeJson(key) .. ":" .. Civ5Ai_Util.EncodeJsonValue(child))
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
  return Civ5Ai_Util.EscapeJson(value)
end

function Civ5Ai_Util.EncodeJsonObject(payload)
  local parts = {}
  for key, value in pairs(payload) do
    table.insert(parts, Civ5Ai_Util.EscapeJson(key) .. ":" .. Civ5Ai_Util.EncodeJsonValue(value))
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

function Civ5Ai_Util._SkipJsonWs(text, i)
  while i <= #text do
    local ch = string.sub(text, i, i)
    if ch ~= " " and ch ~= "\t" and ch ~= "\n" and ch ~= "\r" then
      return i
    end
    i = i + 1
  end
  return i
end

function Civ5Ai_Util._DecodeJsonValue(text, i)
  i = Civ5Ai_Util._SkipJsonWs(text, i)
  local ch = string.sub(text, i, i)
  if ch == '"' then
    local value, nextI = Civ5Ai_Util.ParseJsonQuotedString(text, i)
    return value, nextI
  end
  if ch == "{" then
    local obj = {}
    i = Civ5Ai_Util._SkipJsonWs(text, i + 1)
    if string.sub(text, i, i) == "}" then
      return obj, i + 1
    end
    while i <= #text do
      i = Civ5Ai_Util._SkipJsonWs(text, i)
      if string.sub(text, i, i) ~= '"' then
        return nil, i
      end
      local key, afterKey = Civ5Ai_Util.ParseJsonQuotedString(text, i)
      i = Civ5Ai_Util._SkipJsonWs(text, afterKey)
      if string.sub(text, i, i) ~= ":" then
        return nil, i
      end
      local value, afterValue = Civ5Ai_Util._DecodeJsonValue(text, i + 1)
      if afterValue == nil then
        return nil, i
      end
      obj[key] = value
      i = Civ5Ai_Util._SkipJsonWs(text, afterValue)
      local sep = string.sub(text, i, i)
      if sep == "}" then
        return obj, i + 1
      end
      if sep ~= "," then
        return nil, i
      end
      i = i + 1
    end
    return nil, i
  end
  if ch == "[" then
    local arr = Civ5Ai_Util.JsonArrayList()
    i = Civ5Ai_Util._SkipJsonWs(text, i + 1)
    if string.sub(text, i, i) == "]" then
      return arr, i + 1
    end
    while i <= #text do
      local value, afterValue = Civ5Ai_Util._DecodeJsonValue(text, i)
      if afterValue == nil then
        return nil, i
      end
      table.insert(arr, value)
      i = Civ5Ai_Util._SkipJsonWs(text, afterValue)
      local sep = string.sub(text, i, i)
      if sep == "]" then
        return arr, i + 1
      end
      if sep ~= "," then
        return nil, i
      end
      i = i + 1
    end
    return nil, i
  end
  if string.sub(text, i, i + 3) == "true" then
    return true, i + 4
  end
  if string.sub(text, i, i + 4) == "false" then
    return false, i + 5
  end
  if string.sub(text, i, i + 3) == "null" then
    return Civ5Ai_Util.JsonNull(), i + 4
  end
  local num, nextI = string.match(text, "^(%-?%d+%.?%d*[eE]?[%+%-]?%d*)()", i)
  if num ~= nil then
    return tonumber(num), nextI
  end
  return nil, i
end

function Civ5Ai_Util.DecodeJson(text)
  if text == nil or text == "" then
    return nil
  end
  local value, nextI = Civ5Ai_Util._DecodeJsonValue(tostring(text), 1)
  if value == nil then
    return nil
  end
  return value, nextI
end

function Civ5Ai_Util.AppendJsonLine(path, payload)
  local line = Civ5Ai_Util.EncodeJsonObject(payload)
  if Civ5Ai_Util.AppendTextLine(path, line) then
    return true
  end
  Civ5Ai_Util.Log("jsonl|" .. line)
  return false
end
