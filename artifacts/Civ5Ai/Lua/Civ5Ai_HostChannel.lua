-- Civ5Ai hidden inbox: receive apply payloads from the Python sidecar (retail io=false).
Civ5Ai_HostChannel = Civ5Ai_HostChannel or {}

Civ5Ai_HostChannel._applyPending = {}
Civ5Ai_HostChannel._armedUntil = 0
Civ5Ai_HostChannel._consumedPendingDisk = {}

function Civ5Ai_HostChannel._Bridge()
  if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil then
    return ExposedMembers.Civ5Ai
  end
  return nil
end

function Civ5Ai_HostChannel._PulseDumpTurn(playerID)
  local bridge = Civ5Ai_HostChannel._Bridge()
  if bridge == nil then
    return nil
  end
  if bridge.ExpectedApplyTurn ~= nil then
    return tonumber(bridge.ExpectedApplyTurn(playerID))
  end
  if bridge._ExpectedApplyTurn ~= nil then
    return tonumber(bridge._ExpectedApplyTurn(playerID))
  end
  return nil
end

-- Accept apply when wire turn matches game turn or the active pulse dump turn.
function Civ5Ai_HostChannel._AcceptApplyTurn(playerID, wireTurn)
  if wireTurn == nil then
    return true
  end
  local pendingTurn = tonumber(wireTurn)
  local gameTurn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    gameTurn = tonumber(Game.GetGameTurn()) or 0
  end
  if pendingTurn == gameTurn then
    return true
  end
  local dumpTurn = Civ5Ai_HostChannel._PulseDumpTurn(playerID)
  return dumpTurn ~= nil and pendingTurn == dumpTurn
end

function Civ5Ai_HostChannel._SessionId()
  local bridge = Civ5Ai_HostChannel._Bridge()
  if bridge ~= nil and bridge.SessionId ~= nil then
    return bridge.SessionId()
  end
  if Civ5Ai_Config ~= nil and Civ5Ai_Config.SessionId ~= nil then
    return Civ5Ai_Config.SessionId()
  end
  return "default"
end

function Civ5Ai_HostChannel._ConsumePendingFile()
  local bridge = Civ5Ai_HostChannel._Bridge()
  if bridge ~= nil and bridge.ClearPendingApply ~= nil then
    bridge.ClearPendingApply()
    return
  end
  if Civ5Ai_Paths == nil or Civ5Ai_Paths.ApplyPendingPaths == nil then
    return
  end
  local stub =
    "-- cleared by Civ5Ai after apply\nCiv5Ai_ApplyPendingMeta = nil\nCiv5Ai_ApplyPendingJson = \"\"\nCiv5Ai_ApplyPendingB64 = \"\"\n"
  for _, path in ipairs(Civ5Ai_Paths.ApplyPendingPaths) do
    Civ5Ai_Util.WriteTextFile(path, stub)
  end
end

function Civ5Ai_HostChannel._ApplyPayload(playerID, decoded)
  local bridge = Civ5Ai_HostChannel._Bridge()
  if bridge == nil or bridge.ApplyPayload == nil then
    Civ5Ai_Util.Log("inbox|apply_no_bridge|player=" .. tostring(playerID))
    return
  end
  local ok = bridge.ApplyPayload(playerID, decoded)
  Civ5Ai_HostChannel._ConsumePendingFile()
  -- Disk/host apply bypasses inbox-wait ScheduleTick. Always progress to
  -- end-turn after a successful apply so HostInbox cannot go silent with
  -- seats marked applied but never finished (t21 stall).
  if ok ~= false then
    local finished = false
    if bridge.WasPulseFinished ~= nil then
      finished = bridge.WasPulseFinished(playerID) == true
    end
    if not finished then
      Civ5Ai_Util.Log(
        "hostchannel|finish_after_apply|player="
          .. tostring(playerID)
      )
      if bridge.EnsureFinishSeat ~= nil then
        pcall(function()
          bridge.EnsureFinishSeat(playerID)
        end)
      elseif bridge.FinishSeat ~= nil then
        pcall(function()
          bridge.FinishSeat(playerID)
        end)
      end
    end
  end
end

function Civ5Ai_HostChannel._Now()
  if os and os.time then
    return os.time()
  end
  return 0
end

function Civ5Ai_HostChannel._IsArmed()
  return Civ5Ai_HostChannel._Now() <= Civ5Ai_HostChannel._armedUntil
end

function Civ5Ai_HostChannel._SetInboxHidden(hidden)
  if Controls ~= nil and Controls.HostInboxBox ~= nil and Controls.HostInboxBox.SetHide ~= nil then
    Controls.HostInboxBox:SetHide(hidden and true or false)
  end
  if Controls ~= nil and Controls.HostChannelInput ~= nil and Controls.HostChannelInput.SetHide ~= nil then
    Controls.HostChannelInput:SetHide(hidden and true or false)
  end
end

function Civ5Ai_HostChannel.Arm(seconds)
  local duration = tonumber(seconds) or 45
  if duration < 5 then
    duration = 5
  end
  Civ5Ai_HostChannel._armedUntil = Civ5Ai_HostChannel._Now() + duration
  Civ5Ai_Util.Log("inbox|armed|" .. tostring(duration))
  -- Sidecar live apply is the JSON mailbox. Unhiding + TakeKeyboardFocus
  -- blocks CONTROL_ENDTURN and used to force a Python map-click unstick.
  if Civ5Ai_Config ~= nil and Civ5Ai_Config.IsSidecarLive ~= nil and Civ5Ai_Config.IsSidecarLive() then
    Civ5Ai_HostChannel._SetInboxHidden(true)
    return
  end
  -- Host paste targets HostChannelInput. A hidden EditBox does not receive
  -- clipboard input on Windows, so unhide for the arm window only.
  Civ5Ai_HostChannel._SetInboxHidden(false)
  Civ5Ai_HostChannel._FocusInbox()
end

function Civ5Ai_HostChannel._FocusInbox()
  if Controls == nil or Controls.HostChannelInput == nil then
    return false
  end
  if Controls.HostChannelInput.TakeKeyboardFocus ~= nil then
    Controls.HostChannelInput:TakeKeyboardFocus()
    return true
  end
  if Controls.HostChannelInput.SetFocus ~= nil then
    Controls.HostChannelInput:SetFocus()
    return true
  end
  return false
end

function Civ5Ai_HostChannel.ReleaseUiFocus()
  Civ5Ai_HostChannel._SetInboxHidden(true)
  if Controls ~= nil and Controls.HostChannelInput ~= nil then
    if Controls.HostChannelInput.SetText ~= nil then
      Controls.HostChannelInput:SetText("")
    end
    if Controls.HostChannelInput.ClearFocus ~= nil then
      Controls.HostChannelInput:ClearFocus()
    end
  end
  if UI ~= nil and UI.ClearFocus ~= nil then
    UI.ClearFocus()
  end
end

function Civ5Ai_HostChannel._ClearInbox()
  Civ5Ai_HostChannel.ReleaseUiFocus()
end

function Civ5Ai_HostChannel._ReadInboxText()
  if Controls == nil or Controls.HostChannelInput == nil then
    return nil
  end
  local text = Controls.HostChannelInput:GetText()
  if text == nil or text == "" then
    return nil
  end
  return text
end

function Civ5Ai_HostChannel._ConsumeInboxText()
  local text = Civ5Ai_HostChannel._ReadInboxText()
  if text == nil or text == "" then
    return nil
  end
  Civ5Ai_HostChannel._ClearInbox()
  return text
end

function Civ5Ai_HostChannel._SplitLines(text)
  return Civ5Ai_HostChannel._SplitWireLines(text)
end

function Civ5Ai_HostChannel._SplitWireLines(text)
  local lines = {}
  if text == nil or text == "" then
    return lines
  end
  for chunk in string.gmatch(text, "[^\r\n]+") do
    local pos = 1
    while pos <= #chunk do
      local start = string.find(chunk, "CIV5AI|", pos, true)
      if start == nil then
        break
      end
      local nextStart = string.find(chunk, "CIV5AI|", start + 7, true)
      local piece = nextStart and string.sub(chunk, start, nextStart - 1) or string.sub(chunk, start)
      piece = string.match(piece, "^%s*(.-)%s*$") or piece
      if piece ~= "" then
        table.insert(lines, piece)
      end
      pos = nextStart or (#chunk + 1)
    end
  end
  return lines
end

function Civ5Ai_HostChannel._CommitWireLines(text)
  if text == nil or text == "" then
    return false
  end
  local processed = false
  for _, line in ipairs(Civ5Ai_HostChannel._SplitWireLines(text)) do
    if Civ5Ai_HostChannel._IsCompleteWireLine(line) then
      Civ5Ai_HostChannel.OnLine(line)
      processed = true
    end
  end
  return processed
end

function Civ5Ai_HostChannel._DecodeAndApply(playerID, session, encoded, wireTurn)
  local sessionId = Civ5Ai_HostChannel._SessionId()
  if session ~= nil and session ~= "" and session ~= sessionId then
    Civ5Ai_Util.Log(
      "inbox|apply_stale_session|expected="
        .. tostring(sessionId)
        .. "|got="
        .. tostring(session)
    )
    return
  end
  local gameTurn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    gameTurn = Game.GetGameTurn()
  end
  if not Civ5Ai_HostChannel._AcceptApplyTurn(playerID, wireTurn) then
    Civ5Ai_Util.Log(
      "inbox|apply_stale_turn|player="
        .. tostring(playerID)
        .. "|game_turn="
        .. tostring(gameTurn)
        .. "|pulse_turn="
        .. tostring(Civ5Ai_HostChannel._PulseDumpTurn(playerID))
        .. "|got="
        .. tostring(wireTurn)
    )
    return
  end
  local decoded = Civ5Ai_Util.Base64Decode(encoded)
  if decoded == nil or decoded == "" then
    Civ5Ai_Util.Log("inbox|apply_decode_failed|player=" .. tostring(playerID))
    return
  end
  Civ5Ai_Util.Log(
    "inbox|apply_ready|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(gameTurn)
      .. "|len="
      .. tostring(string.len(decoded))
  )
  Civ5Ai_HostChannel._ApplyPayload(playerID, decoded)
end

function Civ5Ai_HostChannel.OnLine(line)
  if line == nil or line == "" then
    return
  end
  if string.find(line, "CIV5AI|host|arm", 1, true) == 1 then
    local seconds = string.match(line, "CIV5AI|host|arm|(%d+)")
    Civ5Ai_HostChannel.Arm(seconds)
    return
  end
  if string.find(line, "CIV5AI|apply|full|", 1, true) == 1 then
    local player, turn, session, encoded = string.match(
      line,
      "^CIV5AI|apply|full|(%d+)|(-?%d+)|([^|]*)|(.*)$"
    )
    if player ~= nil and encoded ~= nil then
      Civ5Ai_Util.Log("inbox|apply_full|player=" .. tostring(player) .. "|turn=" .. tostring(turn))
      Civ5Ai_HostChannel._DecodeAndApply(tonumber(player) or 0, session or "", encoded, tonumber(turn))
    end
    return
  end
  if string.find(line, "CIV5AI|apply|begin|", 1, true) == 1 then
    local id, chunks, player, turn, session = string.match(
      line,
      "^CIV5AI|apply|begin|([^|]+)|(%d+)|(%d+)|(-?%d+)|(.*)$"
    )
    if id ~= nil then
      Civ5Ai_HostChannel._applyPending[id] = {
        id = id,
        chunks = tonumber(chunks) or 1,
        player = tonumber(player) or 0,
        turn = tonumber(turn) or 0,
        session = session or "",
        parts = {},
      }
      Civ5Ai_Util.Log("inbox|apply_begin|" .. id .. "|player=" .. tostring(player))
    end
    return
  end
  if string.find(line, "CIV5AI|apply|c|", 1, true) == 1 then
    local id, index, data = string.match(line, "^CIV5AI|apply|c|([^|]+)|(%d+)|(.*)$")
    local blob = Civ5Ai_HostChannel._applyPending[id]
    if blob ~= nil and index ~= nil then
      blob.parts[tonumber(index) or 0] = data or ""
    end
    return
  end
  if string.find(line, "CIV5AI|apply|end|", 1, true) == 1 then
    local id = string.match(line, "^CIV5AI|apply|end|([^|]+)$")
    local blob = Civ5Ai_HostChannel._applyPending[id]
    Civ5Ai_HostChannel._applyPending[id] = nil
    if blob == nil then
      Civ5Ai_Util.Log("inbox|apply_end_missing|" .. tostring(id))
      return
    end
    local pieces = {}
    for i = 0, blob.chunks - 1 do
      table.insert(pieces, blob.parts[i] or "")
    end
    Civ5Ai_HostChannel._DecodeAndApply(blob.player, blob.session or "", table.concat(pieces, ""), blob.turn)
    return
  end
end

function Civ5Ai_HostChannel._IsCompleteWireLine(text)
  if text == nil or text == "" then
    return false
  end
  if string.find(text, "\r", 1, true) or string.find(text, "\n", 1, true) then
    return false
  end
  if string.find(text, "CIV5AI|host|arm|", 1, true) == 1 then
    return string.match(text, "^CIV5AI|host|arm|(%d+)$") ~= nil
  end
  if string.find(text, "CIV5AI|apply|full|", 1, true) == 1 then
    return string.match(text, "^CIV5AI|apply|full|(%d+)|(-?%d+)|([^|]*)|(.*)$") ~= nil
  end
  if string.find(text, "CIV5AI|apply|begin|", 1, true) == 1 then
    return string.match(text, "^CIV5AI|apply|begin|([^|]+)|(%d+)|(%d+)|(-?%d+)|(.*)$") ~= nil
  end
  if string.find(text, "CIV5AI|apply|c|", 1, true) == 1 then
    return string.match(text, "^CIV5AI|apply|c|([^|]+)|(%d+)|(.*)$") ~= nil
  end
  if string.find(text, "CIV5AI|apply|end|", 1, true) == 1 then
    return string.match(text, "^CIV5AI|apply|end|([^|]+)$") ~= nil
  end
  return false
end

function Civ5Ai_HostChannel._DeliverInboxText(text)
  if text == nil or text == "" then
    return false
  end
  Civ5Ai_HostChannel._OnInboxText(text)
  Civ5Ai_HostChannel._ClearInbox()
  return true
end

function Civ5Ai_HostChannel.DeliverLine(line)
  if line == nil or line == "" then
    return false
  end
  if Controls ~= nil and Controls.HostChannelInput ~= nil and Controls.HostChannelInput.SetText ~= nil then
    Controls.HostChannelInput:SetText(line)
  end
  Civ5Ai_HostChannel._OnHostChannelCommit(line)
  return true
end

function Civ5Ai_HostChannel.CommitLine(line)
  if line == nil or line == "" then
    return false
  end
  Civ5Ai_HostChannel.OnLine(line)
  return true
end

function Civ5Ai_HostChannel._OnInboxText(text)
  if text == nil or text == "" then
    return
  end
  if string.find(text, "CIV5AI|", 1, true) == nil then
    return
  end
  Civ5Ai_Util.Log("inbox|text|len=" .. tostring(string.len(text)))
  Civ5Ai_HostChannel._CommitWireLines(text)
end

function Civ5Ai_HostChannel._OnHostChannelCommit(text)
  -- Chat EditBox RegisterCallback(fn) passes the string on Enter (see DiploCorner SendChat).
  -- Host paste is Ctrl+V then Enter. Do not GetText from a per-frame tick.
  if text == nil or text == "" then
    return
  end
  Civ5Ai_HostChannel._OnInboxText(text)
  if Controls ~= nil and Controls.HostChannelInput ~= nil and Controls.HostChannelInput.ClearString ~= nil then
    Controls.HostChannelInput:ClearString()
  else
    Civ5Ai_HostChannel._ClearInbox()
  end
end

function Civ5Ai_HostChannel._UnescapeLuaQuotedString(text)
  if text == nil then
    return nil
  end
  return (text:gsub("\\n", "\n"):gsub("\\\"", "\""):gsub("\\\\", "\\"))
end

function Civ5Ai_HostChannel._ParseApplyPendingLua(text)
  if text == nil or text == "" then
    return nil
  end
  local session = string.match(text, 'session_id%s*=%s*"([^"]*)"')
  local player = tonumber(string.match(text, "player%s*=%s*(%d+)"))
  local turn = tonumber(string.match(text, "turn%s*=%s*(%d+)"))
  local b64 = string.match(text, 'Civ5Ai_ApplyPendingB64%s*=%s*"([^"]*)"')
  if b64 ~= nil and b64 ~= "" then
    local json = Civ5Ai_Util.Base64Decode(b64)
    if json ~= nil and json ~= "" then
      return {
        session_id = session,
        player = player,
        turn = turn,
        json = json,
      }
    end
  end
  local jsonEscaped = string.match(text, 'Civ5Ai_ApplyPendingJson%s*=%s*"(.*)"%s*$')
  if jsonEscaped == nil then
    jsonEscaped = string.match(text, 'Civ5Ai_ApplyPendingJson%s*=%s*"(.*)"')
  end
  if jsonEscaped == nil or jsonEscaped == "" then
    return nil
  end
  local json = Civ5Ai_HostChannel._UnescapeLuaQuotedString(jsonEscaped)
  if json == nil or json == "" then
    return nil
  end
  return {
    session_id = session,
    player = player,
    turn = turn,
    json = json,
  }
end

function Civ5Ai_HostChannel._ApplyPendingPayload(playerID, session, turn, json)
  if json == nil or json == "" or playerID == nil then
    return false
  end
  local sessionId = Civ5Ai_HostChannel._SessionId()
  if session ~= nil and session ~= "" and session ~= sessionId then
    return false
  end
  local gameTurn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    gameTurn = Game.GetGameTurn()
  end
  if not Civ5Ai_HostChannel._AcceptApplyTurn(playerID, turn) then
    return false
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil then
    Civ5Ai_Util.Log("hostchannel|apply_pending|player=" .. tostring(playerID))
    Civ5Ai_HostChannel._ApplyPayload(playerID, json)
    return true
  end
  local encoded = Civ5Ai_Util.Base64Encode(json)
  if encoded == nil or encoded == "" then
    return false
  end
  local line =
    "CIV5AI|apply|full|"
      .. tostring(playerID)
      .. "|"
      .. tostring(turn or gameTurn)
      .. "|"
      .. sessionId
      .. "|"
      .. encoded
  return Civ5Ai_HostChannel.DeliverLine(line)
end

function Civ5Ai_HostChannel._PendingDiskDigest(path, text)
  if path == nil or text == nil or text == "" then
    return nil
  end
  return tostring(path) .. "|" .. tostring(#text) .. "|" .. string.sub(text, 1, 96)
end

function Civ5Ai_HostChannel._TryApplyPendingFromDisk()
  if Civ5Ai_Paths == nil or Civ5Ai_Paths.ApplyPendingPaths == nil then
    return false
  end
  local bridge = Civ5Ai_HostChannel._Bridge()
  local paths = { "apply_pending.lua" }
  for _, path in ipairs(Civ5Ai_Paths.ApplyPendingPaths) do
    table.insert(paths, path)
  end
  for _, path in ipairs(paths) do
    local text = Civ5Ai_Util.ReadTextFile(path)
    if text ~= nil and text ~= "" then
      local digest = Civ5Ai_HostChannel._PendingDiskDigest(path, text)
      if digest ~= nil and Civ5Ai_HostChannel._consumedPendingDisk[digest] then
        return false
      end
      local parsed = Civ5Ai_HostChannel._ParseApplyPendingLua(text)
      if parsed ~= nil and parsed.player ~= nil then
        if bridge ~= nil and bridge.WasAppliedThisPulse ~= nil and bridge.WasAppliedThisPulse(parsed.player) then
          local empty = bridge.WasEmptyAppliedThisPulse ~= nil
            and bridge.WasEmptyAppliedThisPulse(parsed.player) == true
          if not empty then
            if digest ~= nil then
              Civ5Ai_HostChannel._consumedPendingDisk[digest] = true
            end
            Civ5Ai_HostChannel._ConsumePendingFile()
            return false
          end
        end
        if Civ5Ai_HostChannel._ApplyPendingPayload(parsed.player, parsed.session_id, parsed.turn, parsed.json) then
          if digest ~= nil then
            Civ5Ai_HostChannel._consumedPendingDisk[digest] = true
          end
          Civ5Ai_HostChannel._ConsumePendingFile()
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_HostChannel._ShouldPollDisk()
  if os == nil or os.clock == nil then
    return true
  end
  local now = os.clock()
  local last = Civ5Ai_HostChannel._lastDiskPoll
  if last ~= nil and (now - last) < 0.5 then
    return false
  end
  Civ5Ai_HostChannel._lastDiskPoll = now
  return true
end

function Civ5Ai_HostChannel.Poll()
  Civ5Ai_HostChannel._EnsureFrequentAutosaves()
  Civ5Ai_HostChannel._WireInbox()
  -- GetText is cheap. Commit as soon as a complete paste is sitting in the box.
  -- Do not send Enter from the host: a missed click plus Return ends the turn.
  local text = Civ5Ai_HostChannel._ReadInboxText()
  if text ~= nil and text ~= "" then
    if Civ5Ai_HostChannel._CommitWireLines(text) then
      Civ5Ai_HostChannel._ClearInbox()
      return
    end
    return
  end
  -- ReadTextFile every frame leaks on lua51. Twice a second is enough for apply_pending.lua.
  if Civ5Ai_HostChannel._ShouldPollDisk() then
    Civ5Ai_HostChannel._TryApplyPendingFromDisk()
  end
end

function Civ5Ai_HostChannel._WireInbox()
  if Civ5Ai_HostChannel._inboxWired then
    return true
  end
  if Controls == nil or Controls.HostChannelInput == nil then
    return false
  end
  Controls.HostChannelInput:RegisterCallback(Civ5Ai_HostChannel._OnHostChannelCommit)
  Civ5Ai_HostChannel._inboxWired = true
  Civ5Ai_Util.Log("inbox|editbox|ready")
  return true
end


-- Tighten modded/single autosaves so mid-run crashes can continue from a recent turn.
-- OptionsManager is in-memory; UserSettings.ini alone does not affect a running session.
function Civ5Ai_HostChannel._EnsureFrequentAutosaves()
  if Civ5Ai_HostChannel._autosaveTightened then
    return
  end
  if OptionsManager == nil then
    return
  end
  local turns = 1
  local kept = 15
  local beforeTurns = nil
  local beforeKept = nil
  if OptionsManager.GetTurnsBetweenAutosave_Cached ~= nil then
    beforeTurns = OptionsManager.GetTurnsBetweenAutosave_Cached()
  elseif OptionsManager.GetTurnsBetweenAutosave ~= nil then
    beforeTurns = OptionsManager.GetTurnsBetweenAutosave()
  end
  if OptionsManager.GetNumAutosavesKept_Cached ~= nil then
    beforeKept = OptionsManager.GetNumAutosavesKept_Cached()
  elseif OptionsManager.GetNumAutosavesKept ~= nil then
    beforeKept = OptionsManager.GetNumAutosavesKept()
  end
  if OptionsManager.SetTurnsBetweenAutosave_Cached ~= nil then
    OptionsManager.SetTurnsBetweenAutosave_Cached(turns)
  end
  if OptionsManager.SetNumAutosavesKept_Cached ~= nil then
    OptionsManager.SetNumAutosavesKept_Cached(kept)
  end
  if OptionsManager.CommitGameOptions ~= nil then
    OptionsManager.CommitGameOptions()
  end
  Civ5Ai_HostChannel._autosaveTightened = true
  if Civ5Ai_Util ~= nil and Civ5Ai_Util.Log ~= nil then
    Civ5Ai_Util.Log(
      "autosave|tighten|turns="
        .. tostring(turns)
        .. "|kept="
        .. tostring(kept)
        .. "|before_turns="
        .. tostring(beforeTurns)
        .. "|before_kept="
        .. tostring(beforeKept)
    )
  end
end

function Civ5Ai_HostChannel.Initialize()
  if Civ5Ai_HostChannel._initialized then
    return
  end
  Civ5Ai_HostChannel._initialized = true
  Civ5Ai_HostChannel._EnsureFrequentAutosaves()
  ExposedMembers = ExposedMembers or {}
  ExposedMembers.Civ5Ai = ExposedMembers.Civ5Ai or {}
  ExposedMembers.Civ5Ai.ReceiveHostLine = Civ5Ai_HostChannel.OnLine
  ExposedMembers.Civ5Ai.CommitHostLine = Civ5Ai_HostChannel.CommitLine
  ExposedMembers.Civ5Ai.DeliverHostLine = Civ5Ai_HostChannel.DeliverLine
  ExposedMembers.Civ5Ai.ArmHostInbox = Civ5Ai_HostChannel.Arm
  ExposedMembers.Civ5Ai.PollHostInbox = Civ5Ai_HostChannel.Poll
  ExposedMembers.Civ5Ai.FocusHostInbox = Civ5Ai_HostChannel._FocusInbox
  ExposedMembers.Civ5Ai.ReleaseUiFocus = Civ5Ai_HostChannel.ReleaseUiFocus
  if not Civ5Ai_HostChannel._WireInbox() then
    if Events ~= nil and Events.LoadGameViewStateDone ~= nil then
      Events.LoadGameViewStateDone.Add(Civ5Ai_HostChannel._WireInbox)
    end
  end
  Civ5Ai_Util.Log("inbox|ready")
end

