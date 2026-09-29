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
Civ6Ai_Bridge._logOnceKeys = {}
Civ6Ai_Bridge._consumedApplyIds = {}
Civ6Ai_Bridge._dumpedKeys = {}
Civ6Ai_Bridge._delivered = {}

-- Log a line only the first time `key` is seen. Wait loops run every frame, so
-- any status line inside them must go through here (or a wall-clock throttle).
function Civ6Ai_Bridge._LogOnce(key, message)
  if Civ6Ai_Bridge._logOnceKeys[key] then
    return false
  end
  Civ6Ai_Bridge._logOnceKeys[key] = true
  Civ6Ai_Util.Log(message)
  return true
end

function Civ6Ai_Bridge._WallClock()
  if os ~= nil and os.time ~= nil then
    return os.time()
  end
  return nil
end

-- Seats this bridge drives. Players that are not managed (barbarians, city-states,
-- the human seat outside autotest) never pulse, retry or log. A configured seat
-- whose Players entry does not exist yet still counts so the readiness retry runs.
function Civ6Ai_Bridge._IsBridgeSeat(playerID)
  if Civ6Ai_Config.ShouldRunBridge(playerID) then
    return true
  end
  if Players ~= nil and Players[playerID] == nil and Civ6Ai_Config._managedSeats ~= nil then
    return Civ6Ai_Config._managedSeats[playerID] == true
  end
  return false
end

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

function Civ6Ai_Bridge._IsLocalSeat(playerID)
  return Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() == playerID
end

-- Whether a payload for playerID can be applied from this InGame context. The
-- local seat uses UI operations; any other seat the synced order channel
-- (Civ6Ai_Apply.ApplyDecision), which needs the seat to exist.
function Civ6Ai_Bridge._CanApplyInGame(playerID)
  return Civ6Ai_Bridge._IsLocalSeat(playerID) or Civ6Ai_Bridge._IsGameplayReady(playerID)
end

function Civ6Ai_Bridge._PollMaxAttempts(waitSeconds)
  return math.max(30, tonumber(waitSeconds) or Civ6Ai_Config.SidecarTimeout()) * 10
end

-- Wall-clock deadline for decision waits. Tick count alone is frame-rate
-- dependent (a fast PC pumps ~60+ ticks/s), which timed out 600s waits in ~100s.
function Civ6Ai_Bridge._WaitDeadline(waitSeconds)
  if os and os.time then
    return os.time() + math.max(30, tonumber(waitSeconds) or Civ6Ai_Config.SidecarTimeout())
  end
  return nil
end

function Civ6Ai_Bridge._WaitExpired(deadline, attempts, maxAttempts)
  if deadline ~= nil then
    return os.time() >= deadline
  end
  return attempts >= maxAttempts
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
  if not Civ6Ai_Bridge._IsBridgeSeat(playerID) then
    return
  end
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
  -- Only the local seat has to clear its units before it can end the turn. AI
  -- seats end their own turns; units the model did not order are left to the
  -- native AI (the documented fallback) instead of being force-finished.
  if Civ6Ai_Bridge._IsLocalSeat(playerID) then
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
  end
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

-- A sidecar timeout or pipeline error writes status=fallback with no orders.
-- Applying that file ends the pulse, so a later approved reply (the model takes
-- ~90s; a 45s wait used to lose T17/T21/T26) never runs. Last turn's approved
-- file is also still on disk at the next pulse. Only apply this turn's approved
-- decision.
function Civ6Ai_Bridge._DecisionStatus(text)
  if text == nil or text == "" then
    return nil
  end
  if string.find(text, '"status"%s*:%s*"approved"') then
    return "approved"
  end
  if string.find(text, '"status"%s*:%s*"fallback"') then
    return "fallback"
  end
  return "unknown"
end

function Civ6Ai_Bridge._DecisionTurn(text)
  if text == nil then
    return nil
  end
  return tonumber(string.match(text, '"turn"%s*:%s*(%d+)'))
end

function Civ6Ai_Bridge._IsReadyDecision(text, turn, mode)
  if mode == "chat" then
    return text ~= nil and text ~= ""
  end
  if Civ6Ai_Bridge._DecisionStatus(text) ~= "approved" then
    return false
  end
  local decisionTurn = Civ6Ai_Bridge._DecisionTurn(text)
  if turn ~= nil and decisionTurn ~= nil and decisionTurn ~= turn then
    return false
  end
  return true
end

function Civ6Ai_Bridge._ApplyDecisionFiles(playerID, decisionPath, playerDir)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  local applyPath = Civ6Ai_Util.JoinPath(playerDir, "apply_commands.json")
  local applyText = Civ6Ai_Util.ReadTextFile(applyPath)
  local decisionText = Civ6Ai_Util.ReadTextFile(decisionPath)
  local turn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or nil
  if not Civ6Ai_Bridge._IsReadyDecision(decisionText, turn) then
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
  local waitDeadline = Civ6Ai_Bridge._WaitDeadline(Civ6Ai_Config.SidecarTimeout())
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ6Ai_Bridge._CanApplyInGame(playerID) then
      if applyFn(playerID, decisionPath, playerDir) then
        finishPulse(playerID)
        return false
      end
    end
    if Civ6Ai_Bridge._WaitExpired(waitDeadline, attempts, maxAttempts) then
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
  Civ6Ai_PendingApplyQueue = nil
end

-- Re-run the host-written Civ6Ai_PendingApply.lua (the only host->game channel
-- retail InGame can read). Every waiting seat calls this every frame, so the disk
-- reload is throttled to once per wall-clock second (or every 30th call without os).
function Civ6Ai_Bridge._ReloadPendingApplyMod(force)
  if include == nil then
    return
  end
  local now = Civ6Ai_Bridge._WallClock()
  if not force then
    if now ~= nil then
      if Civ6Ai_Bridge._lastPendingReload == now then
        return
      end
    else
      Civ6Ai_Bridge._pendingReloadCalls = (Civ6Ai_Bridge._pendingReloadCalls or 0) + 1
      if Civ6Ai_Bridge._pendingReloadCalls % 30 ~= 1 then
        return
      end
    end
  end
  Civ6Ai_Bridge._lastPendingReload = now
  local ok, err = pcall(function()
    include("Civ6Ai_PendingApply.lua")
  end)
  if not ok then
    Civ6Ai_Bridge._LogOnce("reload_failed|" .. tostring(err), "bridge|pending_apply_reload_failed|" .. tostring(err))
  end
end

-- Host entry for (playerID, kind). The host writes one module holding a queue
-- keyed "<player>:<kind>" (kind = turn | chat), each entry carrying session_id,
-- player, turn and a content-derived apply_id. A legacy single-payload module is
-- only honoured when its meta names this player.
function Civ6Ai_Bridge._PendingApplyEntry(playerID, kind)
  kind = kind or "turn"
  local queue = Civ6Ai_PendingApplyQueue
  if type(queue) == "table" then
    local entry = queue[tostring(playerID) .. ":" .. kind]
    if type(entry) == "table" then
      return entry
    end
  end
  local meta = Civ6Ai_PendingApplyMeta
  if kind == "turn" and type(meta) == "table" and Civ6Ai_PendingApplyJson ~= nil and Civ6Ai_PendingApplyJson ~= "" then
    if tonumber(meta.player) == playerID and (meta.kind == nil or meta.kind == "turn") then
      return {
        session_id = meta.session_id,
        player = tonumber(meta.player),
        turn = meta.turn,
        kind = "turn",
        apply_id = meta.apply_id,
        json = Civ6Ai_PendingApplyJson,
      }
    end
  end
  return nil
end

-- Turn rule (docs/REAL_TEST.md "Seat timing"). Single player runs the local seat's
-- turn N first; the AI seats play turn N after it ends (same game turn number).
--   local seat: payload turn must equal the current game turn (applied in its turn).
--   AI seats:   the answer to the seat's turn N snapshot is sent as soon as it
--               lands and played at the seat's turn N+1 start, so the caller
--               passes expectedTurn = the snapshot turn.
-- Anything else is a replay and is dropped (logged once). Chat replies may land
-- one turn late. Each apply_id is consumed once, so re-including the same module
-- never re-applies a payload.
function Civ6Ai_Bridge._PendingApplyIsCurrent(playerID, entry, kind, expectedTurn)
  if entry == nil or entry.json == nil or entry.json == "" then
    return false
  end
  kind = kind or "turn"
  local applyId = tostring(entry.apply_id or "")
  if applyId ~= "" and Civ6Ai_Bridge._consumedApplyIds[applyId] then
    return false
  end
  local tag = tostring(playerID) .. "|" .. kind .. "|" .. applyId
  local sessionId = Civ6Ai_Bridge.SessionId()
  if entry.session_id ~= sessionId then
    Civ6Ai_Bridge._LogOnce(
      "stale_session|" .. tag,
      "bridge|pending_apply_stale_session|player=" .. tostring(playerID)
        .. "|expected=" .. tostring(sessionId) .. "|got=" .. tostring(entry.session_id)
    )
    return false
  end
  if tonumber(entry.player) ~= playerID then
    Civ6Ai_Bridge._LogOnce(
      "player_mismatch|" .. tag,
      "bridge|pending_apply_player_mismatch|player=" .. tostring(playerID) .. "|got=" .. tostring(entry.player)
    )
    return false
  end
  local payloadTurn = tonumber(entry.turn)
  local current = Game.GetCurrentGameTurn()
  local fresh = false
  if payloadTurn ~= nil then
    if kind == "chat" then
      fresh = payloadTurn <= current and payloadTurn >= current - 1
    else
      fresh = payloadTurn == (expectedTurn or current)
    end
  end
  if not fresh then
    Civ6Ai_Bridge._LogOnce(
      "stale_turn|" .. tag .. "|" .. tostring(current),
      "bridge|pending_apply_stale_turn|player=" .. tostring(playerID) .. "|kind=" .. kind
        .. "|payload_turn=" .. tostring(entry.turn) .. "|game_turn=" .. tostring(current) .. "|id=" .. applyId
    )
    return false
  end
  return true
end

function Civ6Ai_Bridge._ConsumeApplyId(entry)
  local applyId = tostring(entry and entry.apply_id or "")
  if applyId ~= "" then
    Civ6Ai_Bridge._consumedApplyIds[applyId] = true
  end
  return applyId
end

function Civ6Ai_Bridge._TryPendingApplyFromMod(playerID)
  if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  Civ6Ai_Bridge._ReloadPendingApplyMod()
  local entry = Civ6Ai_Bridge._PendingApplyEntry(playerID, "turn")
  if not Civ6Ai_Bridge._PendingApplyIsCurrent(playerID, entry, "turn") then
    return false
  end
  local turn = Game.GetCurrentGameTurn()
  if not Civ6Ai_Bridge._CanApplyInGame(playerID) then
    Civ6Ai_Bridge._LogOnce(
      "deferred|" .. tostring(playerID) .. "|" .. tostring(turn),
      "bridge|pending_apply_deferred|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn) .. "|reason=no_apply_route"
    )
    return false
  end
  local jsonText = entry.json
  local applyId = Civ6Ai_Bridge._ConsumeApplyId(entry)
  Civ6Ai_Util.Log(
    "bridge|pending_apply|player=" .. tostring(playerID)
      .. "|turn=" .. tostring(turn)
      .. "|local=" .. tostring(Civ6Ai_Bridge._IsLocalSeat(playerID))
      .. "|id=" .. applyId
      .. "|len=" .. tostring(string.len(jsonText or ""))
  )
  if Civ6Ai_Bridge.ApplyPayload(playerID, jsonText, { turn = true, snapshotTurn = tonumber(entry.turn) }) then
    Civ6Ai_Util.Log(
      "bridge|pending_apply_ok|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn) .. "|kind=turn|id=" .. applyId
    )
    return true
  end
  -- Empty or unusable payload: the model answered, there is just nothing to run.
  -- Finish the pulse so the seat does not wait out the full timeout.
  Civ6Ai_Util.Log(
    "bridge|pending_apply_empty|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn) .. "|kind=turn|id=" .. applyId
  )
  Civ6Ai_Bridge._MarkApplied(playerID)
  Civ6Ai_Bridge._CompleteTurnAfterApply(playerID, false)
  return true
end

-- A seat other than the local one: send the model's answer to the seat's
-- snapshot of snapshotTurn as soon as the host writes it. The orders go out on
-- the synced channel for the seat's next turn (Civ6Ai_Apply.ApplyDecision) and
-- its chat right away. Returns true once sent.
function Civ6Ai_Bridge._DeliverSeatDecision(playerID, snapshotTurn)
  Civ6Ai_Bridge._ReloadPendingApplyMod()
  local entry = Civ6Ai_Bridge._PendingApplyEntry(playerID, "turn")
  if not Civ6Ai_Bridge._PendingApplyIsCurrent(playerID, entry, "turn", snapshotTurn) then
    return false
  end
  local applyId = Civ6Ai_Bridge._ConsumeApplyId(entry)
  local decision = Civ6Ai_Bridge._ParseDecision(entry.json)
  local chats = Civ6Ai_Bridge._ParseChatMessages(entry.json)
  if #decision.commands > 0 then
    Civ6Ai_Apply.ApplyDecision(playerID, decision, snapshotTurn)
  end
  if Civ6Ai_Chat ~= nil and #chats > 0 then
    Civ6Ai_Chat.SendMessages(playerID, chats)
  end
  Civ6Ai_Util.Log(
    "bridge|seat_decision_sent|player=" .. tostring(playerID) .. "|snapshot_turn=" .. tostring(snapshotTurn)
      .. "|game_turn=" .. tostring(Game.GetCurrentGameTurn()) .. "|commands=" .. tostring(#decision.commands)
      .. "|chats=" .. tostring(#chats) .. "|id=" .. applyId
  )
  Civ6Ai_Bridge._SettleSeat(playerID, snapshotTurn, true)
  return true
end

-- Note that a seat's answer to its snapshot was sent (or given up on), and
-- tell the host's player once every AI seat's answer is settled: ending the
-- turn before that leaves the unanswered seats to the game's own AI.
function Civ6Ai_Bridge._SettleSeat(playerID, snapshotTurn, sent)
  Civ6Ai_Bridge._delivered[tostring(playerID) .. "|" .. tostring(snapshotTurn)] = sent
  local missing = 0
  for _, seat in ipairs(Civ6Ai_Config.ManagedSeatsList()) do
    if not Civ6Ai_Bridge._IsLocalSeat(seat) then
      if not Civ6Ai_Bridge.SeatDecisionSettled(seat, snapshotTurn) then
        return
      end
      if Civ6Ai_Bridge._delivered[tostring(seat) .. "|" .. tostring(snapshotTurn)] == false then
        missing = missing + 1
      end
    end
  end
  local line = "All AI orders are in. You can end your turn."
  if missing > 0 then
    line = "AI orders are in; " .. missing .. " AI player(s) had no answer and play on the game's own AI this turn."
  end
  Civ6Ai_Chat.PanelAdd("T" .. tostring(Game.GetCurrentGameTurn()) .. "  " .. line)
end

-- Watch for the answer to a seat's snapshot until it is sent, the turn it was
-- for is over, or the host's wait for all seats runs out.
function Civ6Ai_Bridge._ScheduleSeatDelivery(playerID, snapshotTurn)
  local waitSeconds = Civ6Ai_Bridge._InboxWaitSeconds()
  local deadline = Civ6Ai_Bridge._WaitDeadline(waitSeconds)
  local maxAttempts = Civ6Ai_Bridge._PollMaxAttempts(waitSeconds)
  local attempts = 0
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ6Ai_Bridge._DeliverSeatDecision(playerID, snapshotTurn) then
      return false
    end
    if Game.GetCurrentGameTurn() > snapshotTurn + 1 or Civ6Ai_Bridge._WaitExpired(deadline, attempts, maxAttempts) then
      Civ6Ai_Util.Log("bridge|seat_decision_missing|player=" .. tostring(playerID) .. "|snapshot_turn="
        .. tostring(snapshotTurn) .. "|game_turn=" .. tostring(Game.GetCurrentGameTurn()))
      Civ6Ai_Bridge._SettleSeat(playerID, snapshotTurn, false)
      return false
    end
    return true
  end)
end

-- True when the model's answer to the seat's snapshot of `turn` has been sent
-- or given up on, or when no snapshot of that turn was dumped (nothing to wait
-- for). Used by the autotest seat barrier and the host's status line.
function Civ6Ai_Bridge.SeatDecisionSettled(playerID, turn)
  local key = tostring(playerID) .. "|" .. tostring(turn)
  return not Civ6Ai_Bridge._dumpedKeys[key] or Civ6Ai_Bridge._delivered[key] ~= nil
end

function Civ6Ai_Bridge._TryPendingChatFromMod(playerID)
  if Civ6Ai_Bridge._WasAppliedThisChatPulse(playerID) then
    return true
  end
  Civ6Ai_Bridge._ReloadPendingApplyMod()
  local entry = Civ6Ai_Bridge._PendingApplyEntry(playerID, "chat")
  if not Civ6Ai_Bridge._PendingApplyIsCurrent(playerID, entry, "chat") then
    return false
  end
  local applyId = Civ6Ai_Bridge._ConsumeApplyId(entry)
  Civ6Ai_Util.Log(
    "bridge|pending_apply_ok|player=" .. tostring(playerID) .. "|turn=" .. tostring(entry.turn) .. "|kind=chat|id=" .. applyId
  )
  Civ6Ai_Bridge.ApplyPayload(playerID, entry.json, { chatOnly = true })
  return true
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
  local waitSeconds = Civ6Ai_Bridge._InboxWaitSeconds()
  if Civ6Ai_HostChannel ~= nil and Civ6Ai_HostChannel.Arm ~= nil then
    Civ6Ai_HostChannel.Arm(waitSeconds)
  end
  local maxAttempts = Civ6Ai_Bridge._PollMaxAttempts(waitSeconds)
  local waitDeadline = Civ6Ai_Bridge._WaitDeadline(waitSeconds)
  local playerDir = Civ6Ai_Bridge._PlayerDir(playerID)
  local decisionPath = Civ6Ai_Util.JoinPath(playerDir, "decision.json")
  local canReadFiles = Civ6Ai_Util.CanReadHostFiles()
  local waitTurn = Game.GetCurrentGameTurn()
  local attempts = 0
  local lastWaitLog = nil
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Game.GetCurrentGameTurn() ~= waitTurn then
      Civ6Ai_Util.Log("bridge|inbox_wait_abandoned|player=" .. tostring(playerID) .. "|turn=" .. tostring(waitTurn))
      return false
    end
    Civ6Ai_Bridge._TryPendingApplyFromMod(playerID)
    Civ6Ai_Bridge._TryInboxApply(playerID)
    if canReadFiles and Civ6Ai_Bridge._CanApplyInGame(playerID) then
      Civ6Ai_Bridge._ApplyDecisionFiles(playerID, decisionPath, playerDir)
    end
    if Civ6Ai_Bridge._WasAppliedThisPulse(playerID) then
      Civ6Ai_Util.Log("bridge|inbox_apply_done|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      if not Civ6Ai_Bridge._WasPulseFinished(playerID) then
        Civ6Ai_Bridge._FinishTurnPulse(playerID)
      end
      return false
    end
    local now = Civ6Ai_Bridge._WallClock()
    if attempts == 1 or (now ~= nil and lastWaitLog ~= nil and now - lastWaitLog >= 120) then
      lastWaitLog = now
      Civ6Ai_Util.Log(
        "bridge|inbox_wait|player=" .. tostring(playerID) .. "|turn=" .. tostring(waitTurn)
          .. "|attempts=" .. tostring(attempts) .. "|max_wait=" .. tostring(waitSeconds)
      )
    end
    if Civ6Ai_Bridge._WaitExpired(waitDeadline, attempts, maxAttempts) then
      Civ6Ai_Util.Log("bridge|inbox_apply_timeout|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      if not Civ6Ai_Bridge._WasPulseFinished(playerID) then
        Civ6Ai_Bridge._FinishTurnPulse(playerID)
      end
      return false
    end
    return true
  end)
end

-- The host asks the model for one seat at a time, so the last managed seat's
-- answer can arrive up to (managed seats x sidecar timeout) after its pulse.
function Civ6Ai_Bridge._InboxWaitSeconds()
  local seats = 1
  if Civ6Ai_Config.ManagedSeatsList ~= nil then
    seats = math.max(1, #Civ6Ai_Config.ManagedSeatsList())
  end
  return Civ6Ai_Config.SidecarTimeout() * seats
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
  if Civ6Ai_Config.IsAutotest() and Civ6Ai_Bridge._IsLocalSeat(playerID) then
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
    local waitTurn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or nil
    local decisionText = Civ6Ai_Bridge._WaitForApprovedDecision(decisionPath, Civ6Ai_Config.SidecarTimeout(), waitTurn, mode)
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
  local chatKey = Civ6Ai_Bridge._activeChatPulseKey[playerID]
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if mode == "chat" then
      if Civ6Ai_Bridge._activeChatPulseKey[playerID] ~= chatKey then
        return false
      end
      if Civ6Ai_Bridge._TryPendingChatFromMod(playerID) then
        return false
      end
    end
    local decisionText = Civ6Ai_Util.ReadTextFile(decisionPath)
    if wasApplied(playerID) then
      finishPulse(playerID)
      return false
    end
    local waitTurn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or nil
    if Civ6Ai_Bridge._IsReadyDecision(decisionText, waitTurn, mode) then
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
  if not Civ6Ai_Bridge._IsBridgeSeat(playerID) then
    return
  end
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
    local key = Civ6Ai_Bridge._PulseKey(playerID)
    Civ6Ai_Bridge._LogOnce("already_pulsed|" .. key, "bridge|already_pulsed|player=" .. tostring(playerID) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
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
    Civ6Ai_Bridge._FinishTurnPulse(playerID)
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
      Civ6Ai_Bridge._dumpedKeys[Civ6Ai_Bridge._PulseKey(playerID)] = true
      Civ6Ai_Util.Log("bridge|snapshot_dumped|player=" .. tostring(playerID) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
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
  if not Civ6Ai_Bridge._IsLocalSeat(playerID) then
    -- The answer is sent when the host writes it and played at this seat's
    -- next turn start; this turn's pulse is done.
    Civ6Ai_Util.Log("bridge|seat_async|player=" .. tostring(playerID) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
    Civ6Ai_Bridge._ScheduleSeatDelivery(playerID, Game.GetCurrentGameTurn())
    Civ6Ai_Bridge._FinishTurnPulse(playerID)
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
  local chatOnly = options.chatOnly == true
    or (options.turn ~= true and Civ6Ai_Bridge._activeChatPulseKey[playerID] ~= nil)
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
      Civ6Ai_Apply.ApplyDecision(playerID, decision, options.snapshotTurn)
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
  return Civ6Ai_Bridge._WaitForApprovedDecision(path, timeoutSec, nil, "chat")
end

function Civ6Ai_Bridge._WaitForApprovedDecision(path, timeoutSec, turn, mode)
  local deadline = (os and os.time and os.time() + timeoutSec) or nil
  while true do
    local text = Civ6Ai_Util.ReadTextFile(path)
    if Civ6Ai_Bridge._IsReadyDecision(text, turn, mode) then
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

Civ6Ai_Bridge.GOV_ARG_KEYS = {
  "government_id", "slots", "belief_id", "belief_ids", "religion_id", "individual_id", "yield",
  "governor_id", "promotion_id",
}

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
    local prioId = string.match(slice, '"priority_id"%s*:%s*(%d+)')
    if prioId ~= nil then
      arguments.priority_id = tonumber(prioId)
    end
    local prioLevel = string.match(slice, '"priority_level"%s*:%s*(%d+)')
    if prioLevel ~= nil then
      arguments.priority_level = tonumber(prioLevel)
    end
    -- Government & culture commands (Civ6Ai_Apply._Governance): string ids.
    for _, key in ipairs(Civ6Ai_Bridge.GOV_ARG_KEYS) do
      local value = string.match(slice, '"' .. key .. '"%s*:%s*"([^"]*)"')
      if value ~= nil then
        arguments[key] = value
      end
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
    -- Always advance past this "kind" match. Braces inside model text (thought,
    -- chat) can make _ExtractJsonObject close before kindStart; resetting pos
    -- backwards looped forever and grew commands until Civ6 ran out of memory.
    pos = math.max(objEnd or 0, kindEnd) + 1
    if #commands >= 400 then
      Civ6Ai_Util.Log("bridge|parse_decision_cap|commands=" .. tostring(#commands))
      break
    end
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
