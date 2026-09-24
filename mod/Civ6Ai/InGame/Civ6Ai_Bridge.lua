-- Civ6Ai file bridge: snapshot -> sidecar -> decision -> apply.
Civ6Ai_Bridge = Civ6Ai_Bridge or {}

Civ6Ai_Bridge._sessionId = nil
Civ6Ai_Bridge._pulseKeys = {}
Civ6Ai_Bridge._appliedKeys = {}
Civ6Ai_Bridge._chatPulseKeys = {}
Civ6Ai_Bridge._chatAppliedKeys = {}
Civ6Ai_Bridge._activeChatPulseKey = {}
Civ6Ai_Bridge._chatPulseQueue = {}
Civ6Ai_Bridge._chatPulseSeq = 0

function Civ6Ai_Bridge._MarkPulse(playerID)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(playerID) .. "|" .. tostring(turn)
  Civ6Ai_Bridge._pulseKeys[key] = true
end

function Civ6Ai_Bridge._ClearPulse(playerID)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(playerID) .. "|" .. tostring(turn)
  Civ6Ai_Bridge._pulseKeys[key] = nil
  Civ6Ai_Bridge._appliedKeys[key] = nil
  if Civ6Ai_Bridge._finishedKeys ~= nil then
    Civ6Ai_Bridge._finishedKeys[key] = nil
  end
  if Civ6Ai_Bridge._retryKeys ~= nil then
    Civ6Ai_Bridge._retryKeys[key] = nil
  end
end

function Civ6Ai_Bridge._IsGameplayReady(playerID)
  return Players ~= nil and Players[playerID] ~= nil
end

function Civ6Ai_Bridge._HasActablePieces(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local units = player:GetUnits()
  if units ~= nil and units:GetCount() ~= nil and units:GetCount() > 0 then
    return true
  end
  local cities = player:GetCities()
  if cities ~= nil and cities:GetCount() ~= nil and cities:GetCount() > 0 then
    return true
  end
  return false
end

function Civ6Ai_Bridge._CanApplyInGame(playerID)
  if Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() == playerID then
    return true
  end
  return PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil
end

function Civ6Ai_Bridge._PollMaxAttempts(waitSeconds)
  return math.max(30, tonumber(waitSeconds) or Civ6Ai_Config.SidecarTimeout()) * 10
end

function Civ6Ai_Bridge.MarkLoadScreenClosed()
  Civ6Ai_Bridge._loadScreenClosed = true
end

function Civ6Ai_Bridge.IsLoadScreenClosed()
  return Civ6Ai_Bridge._loadScreenClosed == true
end

function Civ6Ai_Bridge._CanStartAutotestPulse(playerID)
  -- STABLE: first-turn pulse gating — see .cursor/rules/civ6-stable-runtime.mdc
  if not Civ6Ai_Config.IsAutotest() then
    return true
  end
  if not Civ6Ai_Bridge.IsLoadScreenClosed() then
    return false
  end
  return Civ6Ai_Bridge._HasActablePieces(playerID)
end

function Civ6Ai_Bridge._AlreadyPulsed(playerID)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(playerID) .. "|" .. tostring(turn)
  return Civ6Ai_Bridge._pulseKeys[key] == true
end

function Civ6Ai_Bridge.SetSessionId(sessionId)
  if sessionId ~= nil and sessionId ~= "" then
    Civ6Ai_Bridge._sessionId = sessionId
  end
end

function Civ6Ai_Bridge.SessionId()
  if Civ6Ai_Bridge._sessionId ~= nil and Civ6Ai_Bridge._sessionId ~= "" then
    return Civ6Ai_Bridge._sessionId
  end
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.SessionId ~= nil then
    local fromConfig = Civ6Ai_Config.SessionId()
    if fromConfig ~= nil and fromConfig ~= "" then
      Civ6Ai_Bridge._sessionId = fromConfig
      return fromConfig
    end
  end
  if Game ~= nil and Game.GetProperty ~= nil then
    local prop = Game.GetProperty("CIV6AI_SESSION_ID")
    if prop ~= nil and prop ~= "" then
      Civ6Ai_Bridge._sessionId = prop
      return prop
    end
  end
  Civ6Ai_Bridge._sessionId = "default"
  return Civ6Ai_Bridge._sessionId
end

function Civ6Ai_Bridge._SessionDir()
  return Civ6Ai_Util.JoinPath(Civ6Ai_Config.RootDir(), "sessions", Civ6Ai_Bridge.SessionId())
end

function Civ6Ai_Bridge._PlayerDir(playerID)
  return Civ6Ai_Util.JoinPath(Civ6Ai_Bridge._SessionDir(), "PLAYER_" .. tostring(playerID))
end

function Civ6Ai_Bridge._CircuitBreakerPath()
  return Civ6Ai_Util.JoinPath(Civ6Ai_Bridge._SessionDir(), "circuit_breaker.json")
end

function Civ6Ai_Bridge._ReadCircuitBreaker(playerID)
  local path = Civ6Ai_Bridge._CircuitBreakerPath()
  local text = Civ6Ai_Util.ReadTextFile(path)
  if text == nil or text == "" then
    return nil
  end
  local label = "PLAYER_" .. tostring(playerID)
  for line in string.gmatch(text, "[^\r\n]+") do
    if string.find(line, label, 1, true) then
      if string.find(line, '"open"', 1, true) or string.find(line, "open", 1, true) then
        return "open"
      end
    end
  end
  return nil
end

function Civ6Ai_Bridge._PreviousJournalResponseId(playerID)
  local journal = Civ6Ai_Util.JoinPath(Civ6Ai_Bridge._PlayerDir(playerID), "journal.jsonl")
  local text = Civ6Ai_Util.ReadTextFile(journal)
  if text == nil or text == "" then
    return ""
  end
  local lastLine = nil
  for line in string.gmatch(text, "[^\r\n]+") do
    lastLine = line
  end
  if lastLine == nil then
    return ""
  end
  local id = string.match(lastLine, '"response_id"%s*:%s*"([^"]+)"')
  return id or ""
end

function Civ6Ai_Bridge._SchedulePulseRetry(playerID)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(playerID) .. "|" .. tostring(turn)
  if Civ6Ai_Bridge._retryKeys ~= nil and Civ6Ai_Bridge._retryKeys[key] then
    return
  end
  Civ6Ai_Bridge._retryKeys = Civ6Ai_Bridge._retryKeys or {}
  Civ6Ai_Bridge._retryKeys[key] = true
  local attempts = 0
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ6Ai_Bridge._IsGameplayReady(playerID)
        and Civ6Ai_Bridge._CanStartAutotestPulse(playerID)
        and not Civ6Ai_Bridge._AlreadyPulsed(playerID) then
      Civ6Ai_Bridge._retryKeys[key] = nil
      Civ6Ai_Util.Log("bridge|retry_pulse|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      Civ6Ai_Bridge.RunTurnPulse(playerID)
      return false
    end
    if attempts == 1 or attempts % 50 == 0 then
      Civ6Ai_Util.Log(
        "bridge|retry_wait|player="
          .. tostring(playerID)
          .. "|attempts="
          .. tostring(attempts)
          .. "|pieces="
          .. tostring(Civ6Ai_Bridge._HasActablePieces(playerID))
      )
    end
    if attempts >= 600 then
      Civ6Ai_Bridge._retryKeys[key] = nil
      Civ6Ai_Util.Log("bridge|retry_timeout|player=" .. tostring(playerID))
      return false
    end
    return true
  end)
end

function Civ6Ai_Bridge._FinishTurnPulse(playerID)
  local key = Civ6Ai_Bridge._PulseKey(playerID)
  Civ6Ai_Bridge._finishedKeys = Civ6Ai_Bridge._finishedKeys or {}
  if Civ6Ai_Bridge._finishedKeys[key] then
    return
  end
  Civ6Ai_Bridge._finishedKeys[key] = true
  Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
  if Civ6Ai_Autotest ~= nil then
    Civ6Ai_Autotest.AfterPulse(playerID)
  end
end

function Civ6Ai_Bridge._FinishChatPulse(playerID)
  local key = Civ6Ai_Bridge._activeChatPulseKey[playerID]
  if key ~= nil then
    Civ6Ai_Bridge._chatPulseKeys[key] = nil
    Civ6Ai_Bridge._activeChatPulseKey[playerID] = nil
  end
  Civ6Ai_Util.Log("bridge|chat_pulse_done|player=" .. tostring(playerID))
  Civ6Ai_Bridge._DrainChatPulseQueue(playerID)
end

function Civ6Ai_Bridge._DrainChatPulseQueue(playerID)
  local queue = Civ6Ai_Bridge._chatPulseQueue[playerID]
  if queue == nil or #queue == 0 then
    Civ6Ai_Bridge._chatPulseQueue[playerID] = nil
    return
  end
  table.remove(queue, 1)
  if #queue == 0 then
    Civ6Ai_Bridge._chatPulseQueue[playerID] = nil
  end
  Civ6Ai_Bridge._RunChatPulseBody(playerID)
end

function Civ6Ai_Bridge._PulseKey(playerID)
  return tostring(playerID) .. "|" .. tostring(Game.GetCurrentGameTurn())
end

function Civ6Ai_Bridge._ChatPulseKey(playerID, seq)
  return tostring(playerID) .. "|" .. tostring(Game.GetCurrentGameTurn()) .. "|chat|" .. tostring(seq)
end

function Civ6Ai_Bridge._NextChatPulseSeq()
  Civ6Ai_Bridge._chatPulseSeq = (Civ6Ai_Bridge._chatPulseSeq or 0) + 1
  return Civ6Ai_Bridge._chatPulseSeq
end

function Civ6Ai_Bridge._MarkApplied(playerID)
  Civ6Ai_Bridge._appliedKeys[Civ6Ai_Bridge._PulseKey(playerID)] = true
end

function Civ6Ai_Bridge._MarkChatApplied(playerID)
  local key = Civ6Ai_Bridge._activeChatPulseKey[playerID]
  if key ~= nil then
    Civ6Ai_Bridge._chatAppliedKeys[key] = true
  end
end

function Civ6Ai_Bridge._WasAppliedThisPulse(playerID)
  return Civ6Ai_Bridge._appliedKeys[Civ6Ai_Bridge._PulseKey(playerID)] == true
end

function Civ6Ai_Bridge._WasAppliedThisChatPulse(playerID)
  local key = Civ6Ai_Bridge._activeChatPulseKey[playerID]
  if key == nil then
    return false
  end
  return Civ6Ai_Bridge._chatAppliedKeys[key] == true
end

function Civ6Ai_Bridge._ApplyDecisionFiles(playerID, decisionPath, playerDir)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  local applyPath = Civ6Ai_Util.JoinPath(playerDir, "apply_commands.json")
  local applyText = Civ6Ai_Util.ReadTextFile(applyPath)
  local decisionText = Civ6Ai_Util.ReadTextFile(decisionPath)
  if (applyText == nil or applyText == "") and (decisionText == nil or decisionText == "") then
    return false
  end
  Civ6Ai_Bridge.ApplyPayload(playerID, applyText or decisionText)
  return true
end

function Civ6Ai_Bridge._ApplyChatDecisionFiles(playerID, decisionPath)
  if Civ6Ai_Bridge._WasAppliedThisChatPulse(playerID) then
    return true
  end
  local decisionText = Civ6Ai_Util.ReadTextFile(decisionPath)
  if decisionText == nil or decisionText == "" then
    return false
  end
  return Civ6Ai_Bridge.ApplyPayload(playerID, decisionText, { chatOnly = true })
end

function Civ6Ai_Bridge._ScheduleApplyRetry(playerID, decisionPath, playerDir, deadline, mode)
  mode = mode or "turn"
  local finishPulse = Civ6Ai_Bridge._FinishTurnPulse
  local applyFn = Civ6Ai_Bridge._ApplyDecisionFiles
  local clearPulse = function()
    Civ6Ai_Bridge._ClearPulse(playerID)
  end
  if mode == "chat" then
    finishPulse = Civ6Ai_Bridge._FinishChatPulse
    applyFn = function(pid, path, _)
      return Civ6Ai_Bridge._ApplyChatDecisionFiles(pid, path)
    end
    clearPulse = function()
    end
  end
  local attempts = 0
  local maxAttempts = Civ6Ai_Bridge._PollMaxAttempts(Civ6Ai_Config.SidecarTimeout())
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ6Ai_Bridge._CanApplyInGame(playerID) then
      if applyFn(playerID, decisionPath, playerDir) then
        finishPulse(playerID)
        return false
      end
    end
    if attempts >= maxAttempts then
      Civ6Ai_Util.Log("bridge|apply_timeout|player=" .. tostring(playerID) .. "|mode=" .. mode)
      clearPulse()
      finishPulse(playerID)
      return false
    end
    return true
  end)
  return true
end

function Civ6Ai_Bridge._WasPulseFinished(playerID)
  local key = Civ6Ai_Bridge._PulseKey(playerID)
  return Civ6Ai_Bridge._finishedKeys ~= nil and Civ6Ai_Bridge._finishedKeys[key] == true
end

function Civ6Ai_Bridge._ClearPendingApplyMod()
  Civ6Ai_PendingApplyJson = ""
  Civ6Ai_PendingApplyMeta = nil
end

function Civ6Ai_Bridge._ReloadPendingApplyMod()
  if include == nil then
    return
  end
  local ok, err = pcall(function()
    include("Civ6Ai_PendingApply.lua")
  end)
  if not ok then
    Civ6Ai_Util.Log("bridge|pending_apply_reload_failed|" .. tostring(err))
  end
end

function Civ6Ai_Bridge._PendingApplyIsCurrent(playerID)
  if Civ6Ai_PendingApplyJson == nil or Civ6Ai_PendingApplyJson == "" then
    return false
  end
  local meta = Civ6Ai_PendingApplyMeta
  if meta == nil then
    Civ6Ai_Util.Log("bridge|pending_apply_missing_meta")
    return false
  end
  local sessionId = Civ6Ai_Bridge.SessionId()
  if meta.session_id ~= nil and meta.session_id ~= sessionId then
    Civ6Ai_Util.Log(
      "bridge|pending_apply_stale_session|expected="
        .. tostring(sessionId)
        .. "|got="
        .. tostring(meta.session_id)
    )
    return false
  end
  return true
end

function Civ6Ai_Bridge._TryPendingApplyFromMod(playerID)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  Civ6Ai_Bridge._ReloadPendingApplyMod()
  if not Civ6Ai_Bridge._PendingApplyIsCurrent(playerID) then
    return false
  end
  if not Civ6Ai_Bridge._CanApplyInGame(playerID) then
    Civ6Ai_Util.Log("bridge|pending_apply_deferred|player=" .. tostring(playerID))
    return false
  end
  local jsonText = Civ6Ai_PendingApplyJson
  Civ6Ai_Util.Log(
    "bridge|pending_apply|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(Game.GetCurrentGameTurn())
      .. "|len="
      .. tostring(string.len(jsonText or ""))
  )
  if Civ6Ai_Bridge.ApplyPayload(playerID, jsonText) then
    Civ6Ai_Util.Log("bridge|pending_apply_ok|player=" .. tostring(playerID))
    Civ6Ai_Bridge._ClearPendingApplyMod()
    return true
  end
  return false
end


function Civ6Ai_Bridge._TryInboxApply(playerID)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  if Civ6Ai_HostChannel ~= nil and Civ6Ai_HostChannel.Poll ~= nil then
    Civ6Ai_HostChannel.Poll()
  end
  return Civ6Ai_Bridge._WasAppliedThisPulse(playerID)
end

function Civ6Ai_Bridge._ScheduleInboxApplyWait(playerID)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    if not Civ6Ai_Bridge._WasPulseFinished(playerID) then
      Civ6Ai_Bridge._FinishTurnPulse(playerID)
    end
    return
  end
  if Civ6Ai_HostChannel ~= nil and Civ6Ai_HostChannel.Arm ~= nil then
    Civ6Ai_HostChannel.Arm(Civ6Ai_Config.SidecarTimeout())
  end
  local maxAttempts = Civ6Ai_Bridge._PollMaxAttempts(Civ6Ai_Config.SidecarTimeout())
  local playerDir = Civ6Ai_Bridge._PlayerDir(playerID)
  local decisionPath = Civ6Ai_Util.JoinPath(playerDir, "decision.json")
  local attempts = 0
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    Civ6Ai_Bridge._TryPendingApplyFromMod(playerID)
    Civ6Ai_Bridge._TryInboxApply(playerID)
    if Civ6Ai_Bridge._CanApplyInGame(playerID) then
      Civ6Ai_Bridge._ApplyDecisionFiles(playerID, decisionPath, playerDir)
    end
    if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
      Civ6Ai_Util.Log("bridge|inbox_apply_done|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      if not Civ6Ai_Bridge._WasPulseFinished(playerID) then
        Civ6Ai_Bridge._FinishTurnPulse(playerID)
      end
      return false
    end
    if attempts == 1 or attempts % 50 == 0 then
      Civ6Ai_Util.Log("bridge|inbox_wait|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
    end
    if attempts >= maxAttempts then
      Civ6Ai_Util.Log("bridge|inbox_apply_timeout|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      if not Civ6Ai_Bridge._WasPulseFinished(playerID) then
        Civ6Ai_Bridge._FinishTurnPulse(playerID)
      end
      return false
    end
    return true
  end)
end

function Civ6Ai_Bridge._WaitForInboxApply(playerID)
  Civ6Ai_Bridge._ScheduleInboxApplyWait(playerID)
end

function Civ6Ai_Bridge.ResumeAutotestTurnIfStalled()
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  for _, playerID in ipairs(Civ6Ai_Config.ManagedSeatsList()) do
    local key = Civ6Ai_Bridge._PulseKey(playerID)
    if Civ6Ai_Bridge._pulseKeys[key] and not Civ6Ai_Bridge._WasPulseFinished(playerID) then
      Civ6Ai_Util.Log("bridge|resume_stalled_pulse|player=" .. tostring(playerID))
      if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
        Civ6Ai_Bridge._FinishTurnPulse(playerID)
      else
        Civ6Ai_Bridge._ScheduleInboxApplyWait(playerID)
      end
    elseif not Civ6Ai_Bridge._AlreadyPulsed(playerID) and Civ6Ai_Bridge._IsGameplayReady(playerID) then
      Civ6Ai_Bridge._SchedulePulseRetry(playerID)
    end
  end
end

function Civ6Ai_Bridge._CompleteTurnAfterApply(playerID, chatOnly)
  if chatOnly then
    return
  end
  if Civ6Ai_Bridge._pulseKeys[Civ6Ai_Bridge._PulseKey(playerID)] == true then
    Civ6Ai_Bridge._FinishTurnPulse(playerID)
    return
  end
  if Civ6Ai_Config.IsAutotest() and Civ6Ai_Config.IsManagedSeat(playerID) then
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    if Civ6Ai_Autotest ~= nil then
      Civ6Ai_Autotest.AfterPulse(playerID)
    end
  end
end

function Civ6Ai_Bridge._ScheduleSidecarPoll(playerID, decisionPath, playerDir, deadline, mode)
  mode = mode or "turn"
  local finishPulse = Civ6Ai_Bridge._FinishTurnPulse
  local wasApplied = Civ6Ai_Bridge._WasAppliedThisPulse
  local applyFn = Civ6Ai_Bridge._ApplyDecisionFiles
  local clearPulse = function()
    Civ6Ai_Bridge._ClearPulse(playerID)
  end
  if mode == "chat" then
    finishPulse = Civ6Ai_Bridge._FinishChatPulse
    wasApplied = Civ6Ai_Bridge._WasAppliedThisChatPulse
    applyFn = function(pid, path, _)
      return Civ6Ai_Bridge._ApplyChatDecisionFiles(pid, path)
    end
    clearPulse = function()
    end
  end
  if ContextPtr == nil then
    local decisionText = Civ6Ai_Bridge._WaitForFile(decisionPath, Civ6Ai_Config.SidecarTimeout())
    if decisionText == nil then
      Civ6Ai_Util.Log("bridge|decision_timeout|player=" .. tostring(playerID) .. "|mode=" .. mode)
      clearPulse()
      finishPulse(playerID)
      return
    end
    if Civ6Ai_Bridge._CanApplyInGame(playerID) then
      applyFn(playerID, decisionPath, playerDir)
    end
    finishPulse(playerID)
    return
  end
  local attempts = 0
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    local decisionText = Civ6Ai_Util.ReadTextFile(decisionPath)
    if wasApplied(playerID) then
      finishPulse(playerID)
      return false
    end
    if decisionText ~= nil and decisionText ~= "" then
      if Civ6Ai_Bridge._CanApplyInGame(playerID) then
        applyFn(playerID, decisionPath, playerDir)
        finishPulse(playerID)
      else
        Civ6Ai_Bridge._ScheduleApplyRetry(playerID, decisionPath, playerDir, deadline, mode)
      end
      return false
    end
    if deadline ~= nil and os and os.time and os.time() >= deadline then
      Civ6Ai_Util.Log("bridge|decision_timeout|player=" .. tostring(playerID) .. "|mode=" .. mode)
      clearPulse()
      finishPulse(playerID)
      return false
    end
    return true
  end)
end

function Civ6Ai_Bridge.RunTurnPulse(playerID)
  -- STABLE through snapshot dump + sidecar queue — apply fixes go in HostChannel/Apply, not here.
  if not Civ6Ai_Bridge._IsGameplayReady(playerID) then
    Civ6Ai_Util.Log("bridge|not_ready|player=" .. tostring(playerID))
    Civ6Ai_Bridge._SchedulePulseRetry(playerID)
    return
  end
  if not Civ6Ai_Bridge._CanStartAutotestPulse(playerID) then
    Civ6Ai_Util.Log(
      "bridge|waiting_load|player="
        .. tostring(playerID)
        .. "|load="
        .. tostring(Civ6Ai_Bridge.IsLoadScreenClosed())
        .. "|pieces="
        .. tostring(Civ6Ai_Bridge._HasActablePieces(playerID))
    )
    Civ6Ai_Bridge._SchedulePulseRetry(playerID)
    return
  end
  if Civ6Ai_Bridge._AlreadyPulsed(playerID) then
    Civ6Ai_Util.Log("bridge|already_pulsed|player=" .. tostring(playerID))
    return
  end
  if Civ6Ai_Config.IsAutotest() and Civ6Ai_Config.IsFastEndTurn() then
    Civ6Ai_Util.Log("bridge|fast_end_turn_skip|player=" .. tostring(playerID))
    if Civ6Ai_Config.IsManagedSeat(playerID) and Civ6Ai_Autotest ~= nil then
      Civ6Ai_Autotest.AfterPulse(playerID)
    end
    return
  end
  if not Civ6Ai_Config.ShouldRunBridge(playerID) then
    return
  end
  Civ6Ai_Bridge._MarkPulse(playerID)
  Civ6Ai_Util.Log("bridge|pulse|player=" .. tostring(playerID))
  local breaker = Civ6Ai_Bridge._ReadCircuitBreaker(playerID)
  if breaker == "open" then
    Civ6Ai_Util.Log("bridge|circuit_breaker_open|player=" .. tostring(playerID))
    if Civ6Ai_Autotest ~= nil then
      Civ6Ai_Autotest.AfterPulse(playerID)
    end
    return
  end
  local snapshotJson, legal = Civ6Ai_Snapshot.Build(playerID)
  if snapshotJson == nil then
    Civ6Ai_Util.Log("bridge|snapshot_failed|player=" .. tostring(playerID))
    Civ6Ai_Bridge._FinishTurnPulse(playerID)
    return
  end
  local playerDir = Civ6Ai_Bridge._PlayerDir(playerID)
  local snapshotPath = Civ6Ai_Util.JoinPath(playerDir, "snapshot.json")
  local dumped = false
  if not Civ6Ai_Util.WriteTextFile(snapshotPath, snapshotJson) then
    dumped = Civ6Ai_Util.DumpBlob("snapshot", {
      session = Civ6Ai_Bridge.SessionId(),
      player = playerID,
      turn = Game.GetCurrentGameTurn(),
      live = Civ6Ai_Config.IsSidecarLive() and 1 or 0,
    }, snapshotJson)
    if dumped then
      Civ6Ai_Util.Log("bridge|snapshot_dumped|player=" .. tostring(playerID))
    else
      Civ6Ai_Util.Log("bridge|snapshot_write_failed|player=" .. tostring(playerID))
      Civ6Ai_Bridge._ClearPulse(playerID)
      Civ6Ai_Bridge._SchedulePulseRetry(playerID)
      return
    end
  end
  local decisionPath = Civ6Ai_Util.JoinPath(playerDir, "decision.json")
  local journalPath = Civ6Ai_Util.JoinPath(playerDir, "journal.jsonl")
  local args = {
    "--from-game",
    "--session-dir", playerDir,
    "--state", snapshotPath,
    "--output", decisionPath,
    "--journal", journalPath,
    "--session-id", Civ6Ai_Bridge.SessionId(),
  }
  if Civ6Ai_Config.IsSidecarLive() then
    table.insert(args, "--live")
  end
  local personality = Civ6Ai_Config.PersonalityPath(playerID)
  if personality ~= "" then
    table.insert(args, "--personality")
    table.insert(args, personality)
  end
  local prevId = Civ6Ai_Bridge._PreviousJournalResponseId(playerID)
  if prevId ~= "" then
    table.insert(args, "--previous-response-id")
    table.insert(args, prevId)
  end
  local ok, err
  if dumped then
    Civ6Ai_Util.Log("bridge|sidecar_via_log|player=" .. tostring(playerID))
    ok = true
  else
    ok, err = Civ6Ai_Bridge._SpawnSidecar(playerDir, args)
    if not ok then
      Civ6Ai_Util.Log("bridge|sidecar_spawn_failed|" .. tostring(err))
      Civ6Ai_Bridge._ClearPulse(playerID)
      Civ6Ai_Bridge._FinishTurnPulse(playerID)
      return
    end
  end
  local deadline = nil
  if os and os.time then
    deadline = os.time() + Civ6Ai_Config.SidecarTimeout()
  end
  if Civ6Ai_Util.CanReadHostFiles() then
    Civ6Ai_Bridge._ScheduleSidecarPoll(playerID, decisionPath, playerDir, deadline)
    return
  end
  Civ6Ai_Bridge._ScheduleInboxApplyWait(playerID)
end

function Civ6Ai_Bridge.RunChatPulse(playerID)
  if not Civ6Ai_Bridge._IsGameplayReady(playerID) then
    Civ6Ai_Util.Log("bridge|chat_not_ready|player=" .. tostring(playerID))
    return
  end
  if Civ6Ai_Config.IsAutotest() and Civ6Ai_Config.IsFastEndTurn() then
    return
  end
  if not Civ6Ai_Config.ShouldRunBridge(playerID) then
    return
  end
  if Civ6Ai_Bridge._activeChatPulseKey[playerID] ~= nil then
    Civ6Ai_Bridge._chatPulseQueue[playerID] = Civ6Ai_Bridge._chatPulseQueue[playerID] or {}
    table.insert(Civ6Ai_Bridge._chatPulseQueue[playerID], true)
    return
  end
  Civ6Ai_Bridge._RunChatPulseBody(playerID)
end

function Civ6Ai_Bridge._RunChatPulseBody(playerID)
  local seq = Civ6Ai_Bridge._NextChatPulseSeq()
  local pulseKey = Civ6Ai_Bridge._ChatPulseKey(playerID, seq)
  Civ6Ai_Bridge._chatPulseKeys[pulseKey] = true
  Civ6Ai_Bridge._activeChatPulseKey[playerID] = pulseKey
  Civ6Ai_Util.Log("bridge|chat_pulse|player=" .. tostring(playerID) .. "|seq=" .. tostring(seq))
  local breaker = Civ6Ai_Bridge._ReadCircuitBreaker(playerID)
  if breaker == "open" then
    Civ6Ai_Util.Log("bridge|chat_circuit_breaker_open|player=" .. tostring(playerID))
    Civ6Ai_Bridge._FinishChatPulse(playerID)
    return
  end
  local snapshotJson = Civ6Ai_Snapshot.Build(playerID, { reason = "human_chat" })
  if snapshotJson == nil then
    Civ6Ai_Util.Log("bridge|chat_snapshot_failed|player=" .. tostring(playerID))
    Civ6Ai_Bridge._FinishChatPulse(playerID)
    return
  end
  local playerDir = Civ6Ai_Bridge._PlayerDir(playerID)
  local snapshotPath = Civ6Ai_Util.JoinPath(playerDir, "snapshot_chat.json")
  local dumped = false
  if not Civ6Ai_Util.WriteTextFile(snapshotPath, snapshotJson) then
    dumped = Civ6Ai_Util.DumpBlob("snapshot_chat", {
      session = Civ6Ai_Bridge.SessionId(),
      player = playerID,
      turn = Game.GetCurrentGameTurn(),
      live = Civ6Ai_Config.IsSidecarLive() and 1 or 0,
      seq = seq,
    }, snapshotJson)
    if not dumped then
      Civ6Ai_Util.Log("bridge|chat_snapshot_write_failed|player=" .. tostring(playerID))
      Civ6Ai_Bridge._FinishChatPulse(playerID)
      return
    end
    Civ6Ai_Util.Log("bridge|chat_snapshot_dumped|player=" .. tostring(playerID))
  end
  local decisionPath = Civ6Ai_Util.JoinPath(playerDir, "decision_chat.json")
  local journalPath = Civ6Ai_Util.JoinPath(playerDir, "journal.jsonl")
  local args = {
    "--from-game",
    "--session-dir", playerDir,
    "--state", snapshotPath,
    "--output", decisionPath,
    "--journal", journalPath,
    "--session-id", Civ6Ai_Bridge.SessionId(),
    "--live",
  }
  local personality = Civ6Ai_Config.PersonalityPath(playerID)
  if personality ~= "" then
    table.insert(args, "--personality")
    table.insert(args, personality)
  end
  local prevId = Civ6Ai_Bridge._PreviousJournalResponseId(playerID)
  if prevId ~= "" then
    table.insert(args, "--previous-response-id")
    table.insert(args, prevId)
  end
  local ok, err = Civ6Ai_Bridge._SpawnSidecar(playerDir, args)
  if not ok then
    if dumped then
      Civ6Ai_Util.Log("bridge|chat_sidecar_via_log|" .. tostring(err))
    else
      Civ6Ai_Util.Log("bridge|chat_sidecar_spawn_failed|" .. tostring(err))
      Civ6Ai_Bridge._FinishChatPulse(playerID)
      return
    end
  end
  local deadline = nil
  if os and os.time then
    deadline = os.time() + Civ6Ai_Config.SidecarTimeout()
  end
  Civ6Ai_Bridge._ScheduleSidecarPoll(playerID, decisionPath, playerDir, deadline, "chat")
end

function Civ6Ai_Bridge._SpawnSidecar(playerDir, args)
  local repo = Civ6Ai_Config.RepoRoot()
  local script = Civ6Ai_Config.SidecarScript()
  if repo == "" then
    return false, "no_repo_root"
  end
  local py = Civ6Ai_Config.PythonExe()
  local job = {
    python = py,
    repo = repo,
    script = script,
    args = args,
    timeout_seconds = Civ6Ai_Config.SidecarTimeout(),
  }
  local jobPath = Civ6Ai_Util.JoinPath(playerDir, "sidecar_job.json")
  if not Civ6Ai_Util.WriteTextFile(jobPath, Civ6Ai_Util.EncodeJsonValue(job)) then
    return false, "job_write_failed"
  end
  if os and os.execute then
    local cmd = '"' .. py .. '" "' .. Civ6Ai_Util.JoinPath(repo, script) .. '"'
    for _, arg in ipairs(args) do
      local escaped = string.gsub(arg, '"', '\\"')
      cmd = cmd .. ' "' .. escaped .. '"'
    end
    local ok = os.execute(cmd)
    if ok == true or ok == 0 then
      return true, nil
    end
  end
  Civ6Ai_Util.Log("bridge|sidecar_job_queued|" .. jobPath)
  return true, "job_queued"
end

function Civ6Ai_Bridge.ApplyJson(playerID, jsonText)
  if jsonText == nil or jsonText == "" then
    return "empty"
  end
  Civ6Ai_Bridge.ApplyPayload(playerID, jsonText)
  Civ6Ai_Util.Log("bridge|apply_json|player=" .. tostring(playerID))
  return "ok"
end

function Civ6Ai_Bridge.ApplyPayload(playerID, jsonText, options)
  options = options or {}
  if jsonText == nil or jsonText == "" then
    return false
  end
  local chatOnly = options.chatOnly == true or Civ6Ai_Bridge._activeChatPulseKey[playerID] ~= nil
  if chatOnly then
    if Civ6Ai_Bridge._WasAppliedThisChatPulse(playerID) then
      Civ6Ai_Util.Log("bridge|chat_apply_skip_duplicate|player=" .. tostring(playerID))
      return true
    end
  elseif Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    Civ6Ai_Util.Log("bridge|apply_skip_duplicate|player=" .. tostring(playerID))
    return true
  end
  local decision = Civ6Ai_Bridge._ParseDecision(jsonText)
  local chats = Civ6Ai_Bridge._ParseChatMessages(jsonText)
  local turnPulseActive = Civ6Ai_Bridge._pulseKeys[Civ6Ai_Bridge._PulseKey(playerID)] == true
  if not chatOnly and not turnPulseActive and #decision.commands == 0 and #chats > 0 then
    chatOnly = true
  end
  if chatOnly and #chats == 0 then
    Civ6Ai_Util.Log("bridge|chat_apply_empty|player=" .. tostring(playerID))
    Civ6Ai_Bridge._FinishChatPulse(playerID)
    return false
  end
  if not chatOnly and #decision.commands == 0 and #chats == 0 then
    Civ6Ai_Util.Log("bridge|apply_empty|player=" .. tostring(playerID))
    return false
  end
  if Civ6Ai_Bridge._IsGameplayReady(playerID) then
    if not chatOnly then
      Civ6Ai_Apply.ApplyDecision(playerID, decision)
    end
    if Civ6Ai_Chat ~= nil and chats ~= nil and #chats > 0 then
      Civ6Ai_Chat.SendMessages(playerID, chats)
    end
    if chatOnly then
      Civ6Ai_Bridge._MarkChatApplied(playerID)
      Civ6Ai_Util.Log("bridge|chat_apply_payload|player=" .. tostring(playerID) .. "|chats=" .. tostring(#chats))
      Civ6Ai_Bridge._FinishChatPulse(playerID)
    else
      Civ6Ai_Bridge._MarkApplied(playerID)
      Civ6Ai_Util.Log(
        "bridge|apply_payload|player="
          .. tostring(playerID)
          .. "|turn="
          .. tostring(Game.GetCurrentGameTurn())
          .. "|commands="
          .. tostring(#decision.commands)
      )
      Civ6Ai_Bridge._CompleteTurnAfterApply(playerID, false)
    end
    return true
  end
  Civ6Ai_Util.Log("bridge|apply_deferred|player=" .. tostring(playerID))
  return false
end

function Civ6Ai_Bridge._WaitForFile(path, timeoutSec)
  local deadline = (os and os.time and os.time() + timeoutSec) or nil
  while true do
    local text = Civ6Ai_Util.ReadTextFile(path)
    if text ~= nil and text ~= "" then
      return text
    end
    if deadline ~= nil and os.time() >= deadline then
      return nil
    end
    Civ6Ai_Util.SleepSeconds(0.25)
  end
end

function Civ6Ai_Bridge._ExtractJsonObject(text, innerPos)
  local depth = 0
  local start = 1
  for i = innerPos, 1, -1 do
    local ch = string.sub(text, i, i)
    if ch == "}" then
      depth = depth + 1
    elseif ch == "{" then
      if depth == 0 then
        start = i
        break
      end
      depth = depth - 1
    end
  end
  depth = 0
  local last = string.len(text)
  for i = start, last do
    local ch = string.sub(text, i, i)
    if ch == "{" then
      depth = depth + 1
    elseif ch == "}" then
      depth = depth - 1
      if depth == 0 then
        return string.sub(text, start, i), i
      end
    end
  end
  return string.sub(text, start, last), last
end

function Civ6Ai_Bridge._ParseDecision(text)
  local commands = {}
  local pos = 1
  while true do
    local kindStart, kindEnd, kind = string.find(text, '"kind"%s*:%s*"([^"]+)"', pos)
    if kindStart == nil then
      break
    end
    local slice, objEnd = Civ6Ai_Bridge._ExtractJsonObject(text, kindStart)
    local commandId = string.match(slice, '"command_id"%s*:%s*"([^"]+)"')
    local arguments = {}
    local techId = string.match(slice, '"tech_id"%s*:%s*"([^"]+)"')
    if techId ~= nil then
      arguments.tech_id = techId
    end
    local civicId = string.match(slice, '"civic_id"%s*:%s*"([^"]+)"')
    if civicId ~= nil then
      arguments.civic_id = civicId
    end
    local unitId = string.match(slice, '"unit_id"%s*:%s*"([^"]+)"')
    if unitId ~= nil then
      arguments.unit_id = unitId
    end
    local plotId = string.match(slice, '"plot_id"%s*:%s*"([^"]+)"')
    if plotId ~= nil then
      arguments.plot_id = plotId
    end
    local cityId = string.match(slice, '"city_id"%s*:%s*"([^"]+)"')
    if cityId ~= nil then
      arguments.city_id = cityId
    end
    local buildId = string.match(slice, '"build_id"%s*:%s*"([^"]+)"')
    if buildId ~= nil then
      arguments.build_id = buildId
    end
    local targetX = string.match(slice, '"target_x"%s*:%s*(%-?%d+)')
    if targetX ~= nil then
      arguments.target_x = tonumber(targetX)
    end
    local targetY = string.match(slice, '"target_y"%s*:%s*(%-?%d+)')
    if targetY ~= nil then
      arguments.target_y = tonumber(targetY)
    end
    if kind ~= nil then
      table.insert(commands, {
        kind = kind,
        command_id = commandId or "",
        arguments = arguments,
      })
    end
    pos = (objEnd or kindEnd) + 1
  end
  return { commands = commands }
end

function Civ6Ai_Bridge._ParseChatMessages(text)
  local start = string.find(text, '"chat_messages"', 1, true)
  if start == nil then
    return {}
  end
  local block = string.sub(text, start, start + 4000)
  local messages = {}
  local pos = 1
  while true do
    local targetStart = string.find(block, '"target":"', pos, true)
    if targetStart == nil then
      break
    end
    local slice = string.sub(block, targetStart, targetStart + 400)
    local target = string.match(slice, '"target":"([^"]+)"')
    local body = string.match(slice, '"text":"([^"]*)"')
    local targetPlayerId = string.match(slice, '"target_player_id":"([^"]+)"')
    if body ~= nil then
      table.insert(messages, {
        target = target or "all",
        text = body,
        target_player_id = targetPlayerId,
      })
    end
    pos = targetStart + 1
  end
  return messages
end
