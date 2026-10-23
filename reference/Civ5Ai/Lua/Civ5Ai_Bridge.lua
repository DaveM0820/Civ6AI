-- Civ5Ai file bridge: snapshot -> sidecar -> decision -> apply.
Civ5Ai_Bridge = Civ5Ai_Bridge or {}

Civ5Ai_Bridge._sessionId = nil
Civ5Ai_Bridge._pulseKeys = {}
Civ5Ai_Bridge._appliedKeys = {}
Civ5Ai_Bridge._finishedKeys = {}
Civ5Ai_Bridge._retryKeys = {}
Civ5Ai_Bridge._loadScreenClosed = false
Civ5Ai_Bridge._inboxWaitGen = {}
Civ5Ai_Bridge._seatQueue = {}
Civ5Ai_Bridge._pulseBusy = false
Civ5Ai_Bridge._pulseBusyBySeat = {}
Civ5Ai_Bridge._pulseSeat = nil
Civ5Ai_Bridge._appliedPendingKeys = {}
Civ5Ai_Bridge._pendingRejectSig = nil
Civ5Ai_Bridge._staleSessionSig = nil
Civ5Ai_Bridge._holdNative = {}
Civ5Ai_Bridge._seatTurnTimeoutGen = {}
Civ5Ai_Bridge._seatTurnStartedAt = {}

function Civ5Ai_Bridge._HostChannel()
  if Civ5Ai_HostChannel ~= nil then
    return Civ5Ai_HostChannel
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ5Ai ~= nil then
    return {
      Arm = ExposedMembers.Civ5Ai.ArmHostInbox,
      Poll = ExposedMembers.Civ5Ai.PollHostInbox,
    }
  end
  return nil
end

function Civ5Ai_Bridge._GameTurn()
  if Game.GetGameTurn then
    return Game.GetGameTurn()
  end
  return 0
end

function Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
  return tostring(playerID) .. "|" .. tostring(turn ~= nil and turn or Civ5Ai_Bridge._GameTurn())
end

-- In-flight apply/mailbox key (may lag game turn during async LLM).
function Civ5Ai_Bridge._PulseKey(playerID)
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    local dumpTurn = Civ5Ai_Bridge._dumpTurn[playerID]
    if dumpTurn ~= nil then
      return Civ5Ai_Bridge._TurnPulseKey(playerID, dumpTurn)
    end
  end
  return Civ5Ai_Bridge._TurnPulseKey(playerID, Civ5Ai_Bridge._GameTurn())
end

function Civ5Ai_Bridge._MarkPulse(playerID)
  if not Civ5Ai_Bridge._TryClaimPulseFile(playerID) then
    return false
  end
  local turn = Civ5Ai_Bridge._GameTurn()
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
  Civ5Ai_Bridge._pulseKeys[key] = true
  Civ5Ai_Bridge._dumpTurn = Civ5Ai_Bridge._dumpTurn or {}
  Civ5Ai_Bridge._dumpTurn[playerID] = turn
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.BeginPulse ~= nil then
    Civ5Ai_Apply.BeginPulse(playerID)
  end
  if Civ5Ai_Bridge._endTurnTried ~= nil then
    Civ5Ai_Bridge._endTurnTried[playerID] = nil
  end
  -- Pulse/gather start of a new GameTurn: undo last-turn HOLD/zero so the LLM can move.
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance ~= nil then
    Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance(playerID)
  end
  return true
end

function Civ5Ai_Bridge._ClearPulse(playerID)
  local key = Civ5Ai_Bridge._PulseKey(playerID)
  Civ5Ai_Bridge._pulseKeys[key] = nil
  Civ5Ai_Bridge._appliedKeys[key] = nil
  Civ5Ai_Bridge._finishedKeys[key] = nil
  Civ5Ai_Bridge._retryKeys[key] = nil
  if Civ5Ai_Bridge._humanPulseCompleted ~= nil then
    Civ5Ai_Bridge._humanPulseCompleted[key] = nil
  end
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    Civ5Ai_Bridge._dumpTurn[playerID] = nil
  end
end

function Civ5Ai_Bridge._IsGameplayReady(playerID)
  return Players ~= nil and Players[playerID] ~= nil
end

function Civ5Ai_Bridge._HasActablePieces(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  for _ in player:Cities() do
    return true
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      return true
    end
  end
  return false
end

function Civ5Ai_Bridge._PulseClaimPath(playerID)
  local playerDir = Civ5Ai_Bridge._PlayerDir(playerID)
  return Civ5Ai_Util.JoinPath(playerDir, "pulse_turn.txt")
end

function Civ5Ai_Bridge._FileAlreadyPulsed(playerID)
  local lock = Civ5Ai_Util.ReadTextFile(Civ5Ai_Bridge._PulseLockPath(playerID))
  if lock ~= nil and lock ~= "" then
    return true
  end
  local path = Civ5Ai_Bridge._PulseClaimPath(playerID)
  local text = Civ5Ai_Util.ReadTextFile(path)
  if text == nil or text == "" then
    return false
  end
  local claimed = tonumber(string.match(text, "%-?%d+"))
  return claimed ~= nil and claimed == Civ5Ai_Bridge._GameTurn()
end

function Civ5Ai_Bridge._WritePulseClaim(playerID)
  local turn = Civ5Ai_Bridge._GameTurn()
  Civ5Ai_Util.WriteTextFile(Civ5Ai_Bridge._PulseClaimPath(playerID), tostring(turn) .. "\n")
end

function Civ5Ai_Bridge._PulseLockPath(playerID)
  local turn = Civ5Ai_Bridge._GameTurn()
  return Civ5Ai_Util.JoinPath(Civ5Ai_Bridge._PlayerDir(playerID), "pulse_t" .. tostring(turn) .. ".lock")
end

function Civ5Ai_Bridge._TryClaimPulseFile(playerID)
  local dest = Civ5Ai_Bridge._PulseLockPath(playerID)
  local existing = Civ5Ai_Util.ReadTextFile(dest)
  if existing ~= nil and existing ~= "" then
    return false
  end
  local token = tostring((os and os.clock and os.clock()) or playerID)
  local tmp = dest .. ".tmp"
  Civ5Ai_Util.WriteTextFile(tmp, token .. "\n")
  if os ~= nil and os.rename ~= nil then
    local ok = os.rename(tmp, dest)
    if not ok then
      return false
    end
  else
    Civ5Ai_Util.WriteTextFile(dest, token .. "\n")
  end
  Civ5Ai_Bridge._WritePulseClaim(playerID)
  return true
end

function Civ5Ai_Bridge._AlreadyPulsed(playerID)
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, Civ5Ai_Bridge._GameTurn())
  if Civ5Ai_Bridge._finishedKeys[key] == true then
    return true
  end
  if Civ5Ai_Bridge._pulseKeys[key] == true then
    return true
  end
  return Civ5Ai_Bridge._FileAlreadyPulsed(playerID)
end

function Civ5Ai_Bridge.MarkLoadScreenClosed()
  Civ5Ai_Bridge._loadScreenClosed = true
end

function Civ5Ai_Bridge.IsLoadScreenClosed()
  return Civ5Ai_Bridge._loadScreenClosed == true
end

function Civ5Ai_Bridge._CanStartAutotestPulse(playerID)
  if not Civ5Ai_Config.IsAutotest() then
    return true
  end
  if not Civ5Ai_Bridge.IsLoadScreenClosed() then
    return false
  end
  return Civ5Ai_Bridge._HasActablePieces(playerID)
end

function Civ5Ai_Bridge.SetSessionId(sessionId)
  if sessionId ~= nil and sessionId ~= "" then
    Civ5Ai_Bridge._sessionId = sessionId
  end
end

function Civ5Ai_Bridge.SessionId()
  if Civ5Ai_Bridge._sessionId ~= nil and Civ5Ai_Bridge._sessionId ~= "" then
    return Civ5Ai_Bridge._sessionId
  end
  if Civ5Ai_Config ~= nil and Civ5Ai_Config.SessionId ~= nil then
    local fromConfig = Civ5Ai_Config.SessionId()
    if fromConfig ~= nil and fromConfig ~= "" then
      Civ5Ai_Bridge._sessionId = fromConfig
      return fromConfig
    end
  end
  Civ5Ai_Bridge._sessionId = "default"
  return Civ5Ai_Bridge._sessionId
end

function Civ5Ai_Bridge._SessionDir()
  return Civ5Ai_Util.JoinPath(Civ5Ai_Config.RootDir(), "sessions", Civ5Ai_Bridge.SessionId())
end

function Civ5Ai_Bridge._PlayerDir(playerID)
  return Civ5Ai_Util.JoinPath(Civ5Ai_Bridge._SessionDir(), "PLAYER_" .. tostring(playerID))
end

function Civ5Ai_Bridge._SafeGameId()
  local id = Civ5Ai_Bridge.SessionId()
  if id == nil or id == "" then
    id = "game"
  end
  return string.gsub(tostring(id), "[^%w._%-]", "_")
end

function Civ5Ai_Bridge._ApplyMailboxName(playerID, turn)
  return Civ5Ai_Bridge._SafeGameId()
    .. "_"
    .. tostring(playerID)
    .. "_"
    .. tostring(turn)
    .. ".json"
end

function Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    local dumpTurn = tonumber(Civ5Ai_Bridge._dumpTurn[playerID])
    if dumpTurn ~= nil then
      return dumpTurn
    end
  end
  return tonumber(Civ5Ai_Bridge._GameTurn())
end

function Civ5Ai_Bridge._ApplyMailboxPaths(playerID)
  local dumpTurn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
  local name = Civ5Ai_Bridge._ApplyMailboxName(playerID, dumpTurn)
  return {
    Civ5Ai_Util.JoinPath(Civ5Ai_Config.RootDir(), name),
    Civ5Ai_Util.JoinPath(Civ5Ai_Bridge._PlayerDir(playerID), name),
  }
end

function Civ5Ai_Bridge._DeleteApplyMailbox(playerID)
  for _, path in ipairs(Civ5Ai_Bridge._ApplyMailboxPaths(playerID)) do
    Civ5Ai_Util.DeleteFile(path)
  end
end


function Civ5Ai_Bridge._RequestSidecarRepulse(playerID, reason)
  local root = Civ5Ai_Config ~= nil and Civ5Ai_Config.RootDir() or nil
  if root == nil then
    return
  end
  local path = Civ5Ai_Util.JoinPath(root, "autotest")
  path = Civ5Ai_Util.JoinPath(path, "need_sidecar_repulse.txt")
  local turn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID) or Civ5Ai_Bridge._GameTurn()
  local body = "player=" .. tostring(playerID) .. "|turn=" .. tostring(turn) .. "|reason=" .. tostring(reason or "") .. "|t=" .. tostring(os.clock())
  Civ5Ai_Util.WriteTextFile(path, body)
  Civ5Ai_Util.Log("bridge|need_sidecar_repulse|player=" .. tostring(playerID) .. "|reason=" .. tostring(reason or ""))
end

function Civ5Ai_Bridge._MarkEmptyApplied(playerID)
  Civ5Ai_Bridge._emptyAppliedKeys = Civ5Ai_Bridge._emptyAppliedKeys or {}
  Civ5Ai_Bridge._emptyAppliedKeys[Civ5Ai_Bridge._PulseKey(playerID)] = true
end

function Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID)
  Civ5Ai_Bridge._emptyAppliedKeys = Civ5Ai_Bridge._emptyAppliedKeys or {}
  return Civ5Ai_Bridge._emptyAppliedKeys[Civ5Ai_Bridge._PulseKey(playerID)] == true
end

function Civ5Ai_Bridge._MarkApplied(playerID)
  Civ5Ai_Bridge._appliedKeys[Civ5Ai_Bridge._PulseKey(playerID)] = true
  Civ5Ai_Bridge._DeleteApplyMailbox(playerID)
  local turn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID) or Civ5Ai_Bridge._GameTurn()
  local path = Civ5Ai_Util.JoinPath(
    Civ5Ai_Bridge._PlayerDir(playerID),
    "t" .. tostring(turn) .. "_seat_applied.txt"
  )
  Civ5Ai_Util.WriteTextFile(
    path,
    "apply_payload|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn) .. "\n"
  )
end

function Civ5Ai_Bridge._WasAppliedThisPulse(playerID)
  return Civ5Ai_Bridge._appliedKeys[Civ5Ai_Bridge._PulseKey(playerID)] == true
end

function Civ5Ai_Bridge._WasPulseFinished(playerID)
  return Civ5Ai_Bridge._finishedKeys[Civ5Ai_Bridge._PulseKey(playerID)] == true
end

function Civ5Ai_Bridge._SeatTurnIsActive(playerID)
  local player = Players[playerID]
  return player ~= nil and player.IsTurnActive ~= nil and player:IsTurnActive() == true
end

function Civ5Ai_Bridge._IsQueued(playerID)
  for i = 1, #Civ5Ai_Bridge._seatQueue do
    if Civ5Ai_Bridge._seatQueue[i] == playerID then
      return true
    end
  end
  return false
end

function Civ5Ai_Bridge._AutoplayRunning()
  return Game ~= nil and Game.GetAIAutoPlay ~= nil and Game.GetAIAutoPlay() > 0
end

function Civ5Ai_Bridge._HoldNativeAi(playerID)
  Civ5Ai_Bridge._holdNative[playerID] = true
  if Game ~= nil and Game.Civ5AiHoldSeat ~= nil then
    Game.Civ5AiHoldSeat(playerID)
  end
end

function Civ5Ai_Bridge._ReleaseNativeAi(playerID)
  Civ5Ai_Bridge._holdNative[playerID] = nil
end

function Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
  if Civ5Ai_Bridge._SeatTurnIsActive(playerID) then
    Civ5Ai_Util.Log(
      "bridge|finish_refused_still_active|player="
        .. tostring(playerID)
        .. "|reason="
        .. tostring(reason or "")
    )
    return
  end
  if Civ5Ai_Bridge._finishCleared ~= nil then
    Civ5Ai_Bridge._finishCleared[playerID] = nil
  end
  local turn = Civ5Ai_Bridge._GameTurn()
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
  Civ5Ai_Bridge._finishedKeys[key] = true
  Civ5Ai_Bridge._pulseKeys[key] = nil
  Civ5Ai_Bridge._SetPulseStep(playerID, 6)
  Civ5Ai_Bridge._DeleteApplyMailbox(playerID)
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    Civ5Ai_Bridge._dumpTurn[playerID] = nil
  end
  if reason ~= nil and reason ~= "" then
    Civ5Ai_Bridge._LogStep(playerID, "6_end_turn", "out", tostring(reason))
  end
  if Civ5Ai_Seats ~= nil then
    Civ5Ai_Seats.MarkDone(playerID)
  end
  if Civ5Ai_Autotest ~= nil then
    Civ5Ai_Autotest.AfterPulse(playerID)
  end
  Civ5Ai_Bridge._ReleasePulseSlot(playerID)
  if not Civ5Ai_Bridge._AnyManagedSeatTurnActive() then
    Civ5Ai_Util.Log("bridge|co_active_turn_closed|turn=" .. tostring(turn))
  end
end

function Civ5Ai_Bridge._StopFinishRetriesForNewTurn(turn)
  Civ5Ai_Bridge._finishRetryGen = Civ5Ai_Bridge._finishRetryGen or {}
  Civ5Ai_Bridge._finishRetryPending = Civ5Ai_Bridge._finishRetryPending or {}
  for pid, pending in pairs(Civ5Ai_Bridge._finishRetryPending) do
    if pending then
      Civ5Ai_Bridge._finishRetryGen[pid] = (Civ5Ai_Bridge._finishRetryGen[pid] or 0) + 1
      Civ5Ai_Bridge._finishRetryPending[pid] = nil
      Civ5Ai_Util.Log(
        "bridge|dll_finish_retry_stop_turn|player="
          .. tostring(pid)
          .. "|turn="
          .. tostring(turn)
      )
    end
  end
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance ~= nil then
    if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil then
      for seat = 0, 63 do
        if Civ5Ai_Seats.IsActiveLocalPlayer(seat) then
          Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance(seat)
        end
      end
    end
  end
end

function Civ5Ai_Bridge._FinishSeatShared()
  -- HostInbox and InGame are separate Lua VMs. Queue must live on ExposedMembers.
  ExposedMembers = ExposedMembers or {}
  ExposedMembers.Civ5Ai = ExposedMembers.Civ5Ai or {}
  return ExposedMembers.Civ5Ai
end

function Civ5Ai_Bridge._QueueFinishSeat(playerID)
  -- Do not call Game.Civ5AiFinishSeat from HostInbox/DiploCorner SetUpdate.
  -- Hold-release stays immediate in _DllFinishManagedSeat. Never SetActivePlayer.
  local active = nil
  if Game ~= nil and Game.GetActivePlayer ~= nil then
    active = Game.GetActivePlayer()
  end
  if playerID == active then
    Civ5Ai_Util.Log("bridge|finish_seat_skip_active|player=" .. tostring(playerID))
    return
  end
  local shared = Civ5Ai_Bridge._FinishSeatShared()
  shared._finishSeatQueue = shared._finishSeatQueue or {}
  shared._finishSeatQueue[playerID] = true
end

function Civ5Ai_Bridge._FlushFinishSeatQueue()
  local shared = Civ5Ai_Bridge._FinishSeatShared()
  local queue = shared._finishSeatQueue
  if queue == nil then
    return
  end
  shared._finishSeatQueue = {}
  local active = nil
  if Game ~= nil and Game.GetActivePlayer ~= nil then
    active = Game.GetActivePlayer()
  end
  for pid, _ in pairs(queue) do
    if pid == active then
      Civ5Ai_Util.Log("bridge|finish_seat_flush_skip_active|player=" .. tostring(pid))
    elseif Game ~= nil and Game.Civ5AiFinishSeat ~= nil then
      Game.Civ5AiFinishSeat(pid)
    end
  end
end

function Civ5Ai_Bridge._BindGameCoreUpdateEnd()
  if Civ5Ai_Bridge._gameCoreUpdateEndBound then
    return
  end
  local hook = nil
  local via = nil
  -- CP DLL CallHook is GameEvents.GameCoreUpdateEnd (CvGame.cpp), not Events.
  if GameEvents ~= nil and GameEvents.GameCoreUpdateEnd ~= nil then
    hook = GameEvents.GameCoreUpdateEnd
    via = "GameEvents"
  elseif Events ~= nil and Events.GameCoreUpdateEnd ~= nil then
    hook = Events.GameCoreUpdateEnd
    via = "Events"
  end
  if hook == nil then
    Civ5Ai_Util.Log("bridge|game_core_update_end_unavailable")
    return
  end
  Civ5Ai_Bridge._gameCoreUpdateEndBound = true
  hook.Add(function()
    Civ5Ai_Bridge._FlushFinishSeatQueue()
  end)
  Civ5Ai_Util.Log("bridge|game_core_update_end_bound|via=" .. tostring(via))
end

function Civ5Ai_Bridge._ScheduleManagedSeatFinishRetry(playerID, reason)
  Civ5Ai_Bridge._finishRetryGen = Civ5Ai_Bridge._finishRetryGen or {}
  Civ5Ai_Bridge._finishRetryPending = Civ5Ai_Bridge._finishRetryPending or {}
  if Civ5Ai_Bridge._finishRetryPending[playerID] then
    return
  end
  Civ5Ai_Bridge._finishRetryPending[playerID] = true
  Civ5Ai_Bridge._finishRetryGen[playerID] = (Civ5Ai_Bridge._finishRetryGen[playerID] or 0) + 1
  local gen = Civ5Ai_Bridge._finishRetryGen[playerID]
  local scheduledTurn = Civ5Ai_Bridge._GameTurn()
  local attempt = 0
  local nextAt = (os and os.clock and os.clock()) or 0
  local pressAt = nextAt
  Civ5Ai_Util.Log(
    "bridge|dll_finish_retry|player="
      .. tostring(playerID)
      .. "|reason="
      .. tostring(reason or "")
  )
  Civ5Ai_Util.ScheduleTick(function()
    if Civ5Ai_Bridge._finishRetryGen[playerID] ~= gen then
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      return false
    end
    if os and os.clock then
      local now = os.clock()
      if now < nextAt then
        return true
      end
      nextAt = now + 0.5
    end
    attempt = attempt + 1
    local turn = Civ5Ai_Bridge._GameTurn()
    if turn ~= scheduledTurn then
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance ~= nil then
        Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance(playerID)
      end
      Civ5Ai_Util.Log(
        "bridge|dll_finish_retry_stop_turn|player="
          .. tostring(playerID)
          .. "|from="
          .. tostring(scheduledTurn)
          .. "|to="
          .. tostring(turn)
      )
      return false
    end
    local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
    if Civ5Ai_Bridge._finishedKeys[key] then
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      return false
    end
    if not Civ5Ai_Bridge._SeatTurnIsActive(playerID) then
      Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      return false
    end
    -- Local human CONTROL_ENDTURN waits for managed peers (CP numActive).
    -- Non-local seats must deactivate first or everyone waits forever.
    local localHuman = Civ5Ai_Seats ~= nil
      and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil
      and Civ5Ai_Seats.IsActiveLocalPlayer(playerID) == true
    local waitingPeers = localHuman
      and Civ5Ai_Autotest ~= nil
      and Civ5Ai_Autotest._OtherSeatTurnActive ~= nil
      and Civ5Ai_Autotest._OtherSeatTurnActive(playerID)
    if waitingPeers then
      if attempt == 1 then
        Civ5Ai_Util.Log(
          "bridge|dll_finish_wait_peers|player="
            .. tostring(playerID)
            .. "|reason="
            .. tostring(reason or "")
        )
      end
      if os and os.clock then
        nextAt = os.clock() + 2.0
      end
      return true
    end
    -- Rapidly clear city screen / research / production / units every 0.5s.
    -- Do not press CONTROL_ENDTURN while CanDoControl is false: that no-op
    -- keeps the engine busy so can stays false (t0 2s storm).
    if localHuman and Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil then
      -- attempt>=2 only forces unordered leftovers; ordered missions still wait.
      Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, attempt >= 2)
    end
    if localHuman and Civ5Ai_Apply ~= nil then
      -- Wait for LLM-ordered paths to finish before leftover drain / end-turn.
      -- Cap attempts so automate/stuck missions cannot livelock finish_seat.
      local orderedBusy = Civ5Ai_Apply._AnyOrderedUnitBusyMoving ~= nil
        and Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID)
      if orderedBusy and attempt < 12 then
        if attempt == 1 or (attempt % 8) == 0 then
          Civ5Ai_Util.Log(
            "bridge|dll_finish_wait_ordered|player="
              .. tostring(playerID)
              .. "|attempt="
              .. tostring(attempt)
          )
        end
        return true
      end
      if orderedBusy and attempt >= 12 then
        Civ5Ai_Util.Log(
          "bridge|dll_finish_wait_ordered_cap|player="
            .. tostring(playerID)
            .. "|attempt="
            .. tostring(attempt)
        )
      end
      if Civ5Ai_Apply.SkipPendingRemainingMoves ~= nil then
        Civ5Ai_Apply.SkipPendingRemainingMoves(playerID)
      end
      if Civ5Ai_Apply._UnitsNeedingOrdersCount ~= nil
          and Civ5Ai_Apply._UnitsNeedingOrdersCount(playerID) > 0
          and Civ5Ai_Apply.SkipUnorderedUnits ~= nil then
        Civ5Ai_Apply.SkipUnorderedUnits(playerID)
      end
      -- Order-aware only (never cancels in-flight LLM missions).
      if attempt >= 2 and Civ5Ai_Apply._FinishAllUnitsWithMoves ~= nil then
        Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
      end
      if Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
        Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
      end
      if attempt == 3 and Civ5Ai_Apply._LogCanDoControlDiag ~= nil then
        Civ5Ai_Apply._LogCanDoControlDiag(playerID, false)
      end
    end
    local movesLeft = 0
    if localHuman and Civ5Ai_Apply ~= nil and Civ5Ai_Apply._LocalHumanMovesRemaining ~= nil then
      movesLeft = Civ5Ai_Apply._LocalHumanMovesRemaining(playerID) or 0
    end
    local canNow = true
    if Game ~= nil and Game.CanDoControl ~= nil and GameInfoTypes ~= nil then
      canNow = Game.CanDoControl(GameInfoTypes.CONTROL_ENDTURN) == true
    end
    -- Do not spam CONTROL_ENDTURN while units still have MovesLeft: the UI may
    -- already report can=true from a prior SetCanEndTurn, but the engine will
    -- not deactivate the seat (t29 P0 dll_finish_stalled forever).
    -- Cap wait_moves: after settle + A/B/C drain + zero_auto, force progress.
    if localHuman and movesLeft > 0 then
      if attempt == 1 or (attempt % 8) == 0 then
        Civ5Ai_Util.Log(
          "bridge|dll_finish_wait_moves|player="
            .. tostring(playerID)
            .. "|units_with_moves="
            .. tostring(movesLeft)
            .. "|attempt="
            .. tostring(attempt)
        )
      end
      if attempt < 20 then
        return true
      end
      Civ5Ai_Util.Log(
        "bridge|dll_finish_wait_moves_cap|player="
          .. tostring(playerID)
          .. "|units_with_moves="
          .. tostring(movesLeft)
          .. "|attempt="
          .. tostring(attempt)
      )
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._FinishAllUnitsWithMoves ~= nil then
        Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
      end
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
        Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
      end
      movesLeft = Civ5Ai_Apply._LocalHumanMovesRemaining(playerID) or 0
      if movesLeft > 0 then
        -- Still blocked only while successful in-flight orders hold MovesLeft.
        -- Failed/unordered leftovers should already be drained above; keep
        -- waiting for in-flight, but after a hard cap fall through so give_up
        -- / end-turn press can run (previously returned true forever → 1300+).
        local orderedBusy = Civ5Ai_Apply._AnyOrderedUnitBusyMoving ~= nil
          and Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID)
        if orderedBusy and attempt < 48 then
          return true
        end
        if attempt < 36 then
          return true
        end
        Civ5Ai_Util.Log(
          "bridge|dll_finish_wait_moves_hard_cap|player="
            .. tostring(playerID)
            .. "|units_with_moves="
            .. tostring(movesLeft)
            .. "|attempt="
            .. tostring(attempt)
        )
      end
    end
    local now = (os and os.clock and os.clock()) or 0
    local pressDue = now >= pressAt
    local press = canNow or pressDue
    if press then
      if Civ5Ai_Bridge._DllFinishManagedSeat(playerID, reason) then
        Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
        Civ5Ai_Bridge._finishRetryPending[playerID] = nil
        return false
      end
      if not canNow then
        local backoff = 4.0
        if attempt >= 8 then
          backoff = 16.0
        elseif attempt >= 4 then
          backoff = 8.0
        end
        pressAt = now + backoff
      else
        pressAt = now + 0.5
      end
    elseif not Civ5Ai_Bridge._SeatTurnIsActive(playerID) then
      Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      return false
    end
    if attempt == 60 then
      Civ5Ai_Util.Log(
        "bridge|dll_finish_give_up|player="
          .. tostring(playerID)
          .. "|still_active=true"
      )
      if localHuman and Civ5Ai_Apply ~= nil then
        if Civ5Ai_Apply.ResolveCityProduction ~= nil then
          Civ5Ai_Apply.ResolveCityProduction(playerID)
        end
        if Civ5Ai_Apply._AcknowledgeProductionBlocking ~= nil then
          Civ5Ai_Apply._AcknowledgeProductionBlocking(playerID)
        end
        if Civ5Ai_Apply._PrepLocalHumanSeatEndTurn ~= nil then
          Civ5Ai_Apply._PrepLocalHumanSeatEndTurn(playerID, true)
        end
        if Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
          Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
        end
      end
    end
    if attempt >= 120 and localHuman then
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._PrepLocalHumanSeatEndTurn ~= nil then
        Civ5Ai_Apply._PrepLocalHumanSeatEndTurn(playerID, true)
      end
      if Civ5Ai_Bridge._DllFinishManagedSeat(playerID, reason) then
        Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
        Civ5Ai_Bridge._finishRetryPending[playerID] = nil
        return false
      end
      Civ5Ai_Util.Log(
        "bridge|dll_finish_abort|player="
          .. tostring(playerID)
          .. "|attempt="
          .. tostring(attempt)
      )
      Civ5Ai_Bridge._finishRetryPending[playerID] = nil
      return false
    end
    return true
  end)
end

-- Single entry for managed-seat DLL release (SP co-active + LAN host).
function Civ5Ai_Bridge._DllFinishManagedSeat(playerID, reason)
  -- Hold must be off before blocking clear: CvGame skips EndTurnsForReadyUnits
  -- while Civ5Ai_ShouldHoldTurn is true.
  if Game ~= nil and Game.Civ5AiReleaseSeatHold ~= nil then
    Game.Civ5AiReleaseSeatHold(playerID)
  end
  local player = Players[playerID]
  local engineHuman = player ~= nil and player.IsHuman ~= nil and player:IsHuman() == true
  -- CONTROL_ENDTURN is the local-client UI control only. Fair-handicap
  -- autoplay marks seats 1-3 SS_TAKEN so IsHuman() is true for handicap
  -- parity; those are not the local client. Using IsHuman() here sent
  -- CONTROL_ENDTURN for 1-3 and never called Civ5AiFinishSeat.
  -- SP autoplay: seat 0 only. Hotseat/LAN: IsActiveLocalPlayer.
  local localHumanEnd = false
  if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil then
    localHumanEnd = Civ5Ai_Seats.IsActiveLocalPlayer(playerID) == true
  elseif engineHuman then
    local active = 0
    if Game ~= nil and Game.GetActivePlayer ~= nil then
      active = Game.GetActivePlayer()
    end
    localHumanEnd = playerID == active
  end
  local blocking = nil
  if player ~= nil and player.GetEndTurnBlockingType ~= nil then
    blocking = player:GetEndTurnBlockingType()
  end
  local cleared = blocking == -1
    or (Civ5Ai_Apply ~= nil and Civ5Ai_Apply._IsEndTurnClear ~= nil and Civ5Ai_Apply._IsEndTurnClear(blocking))
  Civ5Ai_Bridge._finishCleared = Civ5Ai_Bridge._finishCleared or {}
  -- Skip the heavy clear on later retries once a seat is idle (blocking==-1).
  -- Re-running popup/unit sweeps every 2s kept CanDoControl false.
  if Civ5Ai_Bridge._finishCleared[playerID] == true and cleared then
    -- Still drain leftover MovesLeft on every retry. Only clearing UI left
    -- ordered/busy units untouched while SetCanEndTurn(true) lied.
    if localHumanEnd and Civ5Ai_Apply ~= nil then
      if Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil then
        local force = Civ5Ai_Bridge._endTurnTried ~= nil
          and Civ5Ai_Bridge._endTurnTried[playerID] == true
        Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, force)
      elseif Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
        Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
      end
    end
  else
    Civ5Ai_Bridge._TryApplyProductionMailboxDuringFinish(playerID)
    -- Live t66: finish retries only polled production mailboxes, so a late
    -- found_pantheon replace-empty payload was ignored while blocking=13.
    if Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
      Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
    end
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ClearManagedSeatEndTurnBlocking ~= nil then
      cleared = Civ5Ai_Apply.ClearManagedSeatEndTurnBlocking(playerID) == true
    end
    if player ~= nil and player.GetEndTurnBlockingType ~= nil then
      blocking = player:GetEndTurnBlockingType()
    end
    if not cleared and localHumanEnd and Civ5Ai_Apply ~= nil
        and Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil
        and Civ5Ai_Apply._UnitsStillBlocking ~= nil
        and Civ5Ai_Apply._UnitsStillBlocking(blocking) then
      Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, true)
      if player ~= nil and player.GetEndTurnBlockingType ~= nil then
        blocking = player:GetEndTurnBlockingType()
      end
      cleared = blocking == -1
        or (Civ5Ai_Apply._IsEndTurnClear ~= nil
            and Civ5Ai_Apply._IsEndTurnClear(blocking))
    end
    if cleared then
      Civ5Ai_Bridge._finishCleared[playerID] = true
    end
  end
  local called = "none"
  if localHumanEnd then
    -- CONTROL_ENDTURN is the only legal local-human end. FinishSeat /
    -- setTurnActive on the true local human (seat 0) crashed CP.
    -- Never SetActivePlayer to another seat: that copies their FoW onto
    -- the local minimap and desyncs CP numActive == getNumGameTurnActive.
    if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._OtherSeatTurnActive ~= nil
        and Civ5Ai_Autotest._OtherSeatTurnActive(playerID) then
      called = "wait_peers"
    else
      local activeSeat = nil
      if Game ~= nil and Game.GetActivePlayer ~= nil then
        activeSeat = Game.GetActivePlayer()
      end
      if activeSeat ~= nil and activeSeat ~= playerID then
        called = "defer_wrong_active"
      else
        if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._PrepLocalHumanSeatEndTurn ~= nil then
          Civ5Ai_Apply._PrepLocalHumanSeatEndTurn(playerID, true)
        end
        if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._TryEndTurnNow ~= nil then
          Civ5Ai_Autotest._TryEndTurnNow(playerID)
        end
        called = "CONTROL_ENDTURN"
      end
    end
  elseif Game ~= nil and Game.Civ5AiFinishSeat ~= nil then
    -- Do not SetActivePlayer around FinishSeat: the DLL skips
    -- setTurnActive when isHuman() and ePlayer == getActivePlayer().
    -- Switching would make managed SS_TAKEN seats look local and no-op.
    -- Queue; flush on GameCoreUpdateEnd (after UpdatePlayers + CheckPlayerTurnDeactivate).
    Civ5Ai_Bridge._QueueFinishSeat(playerID)
    called = "Civ5AiFinishSeat_queued"
  end
  if player ~= nil and player.GetEndTurnBlockingType ~= nil then
    blocking = player:GetEndTurnBlockingType()
  end
  if Civ5Ai_Bridge._SeatTurnIsActive(playerID) then
    Civ5Ai_Bridge._endTurnTried = Civ5Ai_Bridge._endTurnTried or {}
    if Civ5Ai_Bridge._endTurnTried[playerID]
        and Civ5Ai_Apply ~= nil
        and Civ5Ai_Apply.SkipUnorderedUnits ~= nil
        and Civ5Ai_Apply._UnitsStillBlocking ~= nil
        and Civ5Ai_Apply._UnitsStillBlocking(blocking) then
      Civ5Ai_Apply.SkipUnorderedUnits(playerID)
      if localHumanEnd and Civ5Ai_Apply.SkipPendingRemainingMoves ~= nil then
        Civ5Ai_Apply.SkipPendingRemainingMoves(playerID)
      end
      if localHumanEnd and Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
        Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
      end
      if player ~= nil and player.GetEndTurnBlockingType ~= nil then
        blocking = player:GetEndTurnBlockingType()
      end
    end
    Civ5Ai_Bridge._endTurnTried[playerID] = true
    -- Keep finishCleared when idle so the 2s retry does not re-run the
    -- heavy ClearManagedSeatEndTurnBlocking sweep. Re-clear only if a
    -- real end-turn blocker comes back (units/prod/research).
    local idleNow = blocking == -1
      or (Civ5Ai_Apply ~= nil and Civ5Ai_Apply._IsEndTurnClear ~= nil
          and Civ5Ai_Apply._IsEndTurnClear(blocking))
    if not idleNow then
      Civ5Ai_Bridge._finishCleared[playerID] = nil
    end
    -- Rate-limit stalled logs. wait_peers is handled in the retry scheduler
    -- without calling this function; remaining CONTROL_ENDTURN waits can
    -- still log, but not every 0.5s.
    Civ5Ai_Bridge._stalledLogAt = Civ5Ai_Bridge._stalledLogAt or {}
    local now = (os and os.clock and os.clock()) or 0
    local last = Civ5Ai_Bridge._stalledLogAt[playerID]
    if last == nil or (now - last) >= 2.0 then
      Civ5Ai_Bridge._stalledLogAt[playerID] = now
      Civ5Ai_Util.Log(
        "bridge|dll_finish_stalled|player="
          .. tostring(playerID)
          .. "|reason="
          .. tostring(reason or "")
          .. "|cleared="
          .. tostring(cleared)
          .. "|blocking="
          .. tostring(blocking)
          .. "|human="
          .. tostring(engineHuman)
          .. "|local="
          .. tostring(localHumanEnd)
          .. "|called="
          .. called
      )
    end
    return false
  end
  Civ5Ai_Bridge._finishCleared[playerID] = nil
  if Civ5Ai_Bridge._endTurnTried ~= nil then
    Civ5Ai_Bridge._endTurnTried[playerID] = nil
  end
  Civ5Ai_Util.Log(
    "bridge|dll_finish_ok|dll_finish_seat|player="
      .. tostring(playerID)
      .. "|reason="
      .. tostring(reason or "")
      .. "|called="
      .. called
  )
  return true
end

function Civ5Ai_Bridge._UsesUnifiedSeatFinish(playerID)
  return Civ5Ai_Config ~= nil
    and Civ5Ai_Config.IsCoActiveMode()
    and Civ5Ai_Config.IsManagedSeat(playerID)
end

-- Co-active turn flow: timer or LLM apply -> CP cleanup -> dll finish -> next seat.
function Civ5Ai_Bridge._FinishManagedSeat(playerID, reason)
  local turn = Civ5Ai_Bridge._GameTurn()
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
  if Civ5Ai_Bridge._finishedKeys[key] then
    return
  end
  Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._BumpHumanEndTurnGen ~= nil then
    Civ5Ai_Autotest._BumpHumanEndTurnGen(playerID)
  end
  Civ5Ai_Bridge._BumpInboxWaitGen(playerID)
  if Civ5Ai_Bridge._inboxWaitActive ~= nil then
    Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
  end
  if not Civ5Ai_Bridge._WasAppliedThisPulse(playerID)
      or Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
    Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
  end
  if not Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
    Civ5Ai_Bridge.ApplyPayload(playerID, Civ5Ai_Bridge._EmptyDecisionJson(playerID), true)
  end
  Civ5Ai_Bridge._ReleaseNativeAi(playerID)
  if Civ5Ai_Bridge._DllFinishManagedSeat(playerID, reason) then
    Civ5Ai_Bridge._CompleteManagedSeatFinish(playerID, reason)
  else
    Civ5Ai_Bridge._ScheduleManagedSeatFinishRetry(playerID, reason)
  end
end

function Civ5Ai_Bridge._ApplyCpLimitedFallback(playerID)
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ResolveCpLimitedFallback ~= nil then
    Civ5Ai_Apply.ResolveCpLimitedFallback(playerID)
  end
  Civ5Ai_Bridge._ReleaseNativeAi(playerID)
end

function Civ5Ai_Bridge.ShouldSkipNativeUnitAi(playerID)
  if Civ5Ai_Config == nil or not Civ5Ai_Config.ShouldRunBridge(playerID) then
    return false
  end
  if Civ5Ai_Bridge._AutoplayRunning() then
    return false
  end
  return Civ5Ai_Bridge._holdNative[playerID] == true
end

function Civ5Ai_Bridge._LogStep(playerID, step, direction, body)
  Civ5Ai_Util.LogStep(
    Civ5Ai_Bridge._PlayerDir(playerID),
    playerID,
    Civ5Ai_Bridge._GameTurn(),
    step,
    direction,
    body
  )
end

function Civ5Ai_Bridge._UsesParallelPulses()
  return Civ5Ai_Config ~= nil and Civ5Ai_Config.IsParallelPulses()
end

function Civ5Ai_Bridge._IsSeatPulseBusy(playerID)
  if Civ5Ai_Bridge._UsesParallelPulses() then
    return Civ5Ai_Bridge._pulseBusyBySeat[playerID] == true
  end
  return Civ5Ai_Bridge._pulseBusy == true and Civ5Ai_Bridge._pulseSeat == playerID
end

function Civ5Ai_Bridge._ClaimPulseSlot(playerID)
  if Civ5Ai_Bridge._UsesParallelPulses() then
    Civ5Ai_Bridge._pulseBusyBySeat[playerID] = true
    return
  end
  Civ5Ai_Bridge._pulseBusy = true
  Civ5Ai_Bridge._pulseSeat = playerID
end

function Civ5Ai_Bridge._CountTurnActiveManaged()
  local count = 0
  if Civ5Ai_Config == nil or not Civ5Ai_Config.IsCoActiveMode() then
    return count
  end
  for seat = 0, 63 do
    if Civ5Ai_Config.IsManagedSeat(seat) and Civ5Ai_Bridge._SeatTurnIsActive(seat) then
      count = count + 1
    end
  end
  return count
end

function Civ5Ai_Bridge._HasPendingDiplomacy(playerID)
  if Civ5Ai_Diplo == nil or Civ5Ai_Diplo.BuildPendingRequests == nil then
    return false
  end
  local pending = Civ5Ai_Diplo.BuildPendingRequests(playerID)
  return pending ~= nil and #pending > 0
end

function Civ5Ai_Bridge._BumpSeatTurnTimeoutGen(playerID)
  Civ5Ai_Bridge._seatTurnTimeoutGen[playerID] = (Civ5Ai_Bridge._seatTurnTimeoutGen[playerID] or 0) + 1
  return Civ5Ai_Bridge._seatTurnTimeoutGen[playerID]
end

function Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
  Civ5Ai_Bridge._BumpSeatTurnTimeoutGen(playerID)
  Civ5Ai_Bridge._seatTurnStartedAt[playerID] = nil
end

function Civ5Ai_Bridge._ArmSeatTurnTimeout(playerID)
  local cap = Civ5Ai_Config ~= nil and Civ5Ai_Config.SeatTurnCapSeconds() or nil
  if cap == nil or cap <= 0 or not os or not os.clock then
    return
  end
  local gen = Civ5Ai_Bridge._BumpSeatTurnTimeoutGen(playerID)
  Civ5Ai_Bridge._seatCapExtends = Civ5Ai_Bridge._seatCapExtends or {}
  Civ5Ai_Bridge._seatCapExtends[playerID] = 0
  Civ5Ai_Bridge._seatTurnStartedAt[playerID] = os.clock()
  Civ5Ai_Util.Log(
    "bridge|seat_turn_cap_armed|player="
      .. tostring(playerID)
      .. "|seconds="
      .. tostring(cap)
  )
  Civ5Ai_Util.ScheduleTick(function()
    if Civ5Ai_Bridge._seatTurnTimeoutGen[playerID] ~= gen then
      return false
    end
    local started = Civ5Ai_Bridge._seatTurnStartedAt[playerID]
    if started == nil then
      return false
    end
    if (os.clock() - started) < cap then
      return true
    end
    local turn = Civ5Ai_Bridge._GameTurn()
    local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
    if Civ5Ai_Bridge._finishedKeys[key] == true then
      Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
      return false
    end
    Civ5Ai_Util.Log(
      "bridge|seat_turn_cap|player="
        .. tostring(playerID)
        .. "|turn="
        .. tostring(turn)
        .. "|elapsed="
        .. tostring(math.floor(os.clock() - started))
    )
    Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
    -- One timeout, then native AI finishes the seat. Missing/failed LLM
    -- orders must not hold the turn open.
    if Civ5Ai_Bridge._inboxWaitActive ~= nil then
      Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
    end
    Civ5Ai_Bridge._ForceReleaseManagedSeat(playerID, "seat_turn_cap")
    Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
    return false
  end)
end

function Civ5Ai_Bridge._OnCoActiveTurnBegin(turn)
  if Civ5Ai_Bridge._coActivePulseTurn == turn then
    return
  end
  Civ5Ai_Bridge._coActivePulseTurn = turn
  Civ5Ai_Bridge._seatCapExtends = {}
  Civ5Ai_Bridge._StopFinishRetriesForNewTurn(turn)
  for seat = 0, 63 do
    if Civ5Ai_Config ~= nil and Civ5Ai_Config.IsManagedSeat(seat) then
      -- A new game turn is a new pulse. Stale inbox waits (a seat that never
      -- applied last turn) must not block this turn's dump.
      Civ5Ai_Bridge._BumpInboxWaitGen(seat)
      if Civ5Ai_Bridge._pulseBusyBySeat ~= nil then
        Civ5Ai_Bridge._pulseBusyBySeat[seat] = nil
      end
      if Civ5Ai_Bridge._inboxWaitActive ~= nil then
        Civ5Ai_Bridge._inboxWaitActive[seat] = nil
      end
      if Civ5Ai_Bridge._emptyApplyAt ~= nil then
        Civ5Ai_Bridge._emptyApplyAt[seat] = nil
      end
    end
  end
end

function Civ5Ai_Bridge._RequestCoActiveManagedTurnPulses()
  if Civ5Ai_Config == nil or not Civ5Ai_Config.IsCoActiveMode() then
    local active = Game.GetActivePlayer()
    if Civ5Ai_Config ~= nil and Civ5Ai_Config.ShouldRunBridge(active) then
      Civ5Ai_Bridge.RequestTurnPulse(active)
    end
    return
  end
  local turn = Civ5Ai_Bridge._GameTurn()
  Civ5Ai_Bridge._OnCoActiveTurnBegin(turn)
  local seats = {}
  for seat = 0, 63 do
    if Civ5Ai_Config.IsManagedSeat(seat) and Civ5Ai_Config.ShouldRunBridge(seat) then
      Civ5Ai_Bridge.RequestTurnPulse(seat)
      table.insert(seats, tostring(seat))
    end
  end
  if #seats > 0 then
    Civ5Ai_Util.Log(
      "bridge|co_active_request_pulses|turn="
        .. tostring(turn)
        .. "|seats="
        .. table.concat(seats, ",")
    )
  end
end

function Civ5Ai_Bridge.RequestTurnPulse(playerID)
  local gameTurn = Civ5Ai_Bridge._GameTurn()
  local dumpTurn = nil
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    dumpTurn = tonumber(Civ5Ai_Bridge._dumpTurn[playerID])
  end
  if Civ5Ai_Bridge._inboxWaitActive ~= nil and Civ5Ai_Bridge._inboxWaitActive[playerID] then
    if dumpTurn ~= nil and dumpTurn == tonumber(gameTurn) then
      return
    end
    Civ5Ai_Bridge._BumpInboxWaitGen(playerID)
    Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
  end
  local pendingDiplo = Civ5Ai_Bridge._HasPendingDiplomacy(playerID)
  if Civ5Ai_Bridge._AlreadyPulsed(playerID) then
    if not pendingDiplo then
      return
    end
    Civ5Ai_Bridge._ClearPulse(playerID)
    Civ5Ai_Util.Log("bridge|diplomacy_repulse|player=" .. tostring(playerID))
  end
  if Civ5Ai_Bridge._IsQueued(playerID) then
    return
  end
  if Civ5Ai_Bridge._IsSeatPulseBusy(playerID) then
    return
  end
  Civ5Ai_Bridge._HoldNativeAi(playerID)
  Civ5Ai_Bridge._ArmSeatTurnTimeout(playerID)
  table.insert(Civ5Ai_Bridge._seatQueue, playerID)
  Civ5Ai_Util.Log(
    "bridge|queue_seat|player="
      .. tostring(playerID)
      .. "|queued="
      .. tostring(#Civ5Ai_Bridge._seatQueue)
      .. "|co_active_turn_active="
      .. tostring(Civ5Ai_Bridge._CountTurnActiveManaged())
  )
  -- Next UI frame, not inside PlayerDoTurn: Snapshot.Build on the cascade stack CTDs lua51.
  Civ5Ai_Util.ScheduleTick(function()
    Civ5Ai_Bridge._KickPulseQueue()
    return false
  end)
end

function Civ5Ai_Bridge._TakeNextSeat()
  -- FIFO: PlayerDoTurn enqueues in engine order; one seat runs steps 1-6 at a time.
  local queue = Civ5Ai_Bridge._seatQueue
  if #queue == 0 then
    return nil
  end
  return table.remove(queue, 1)
end

function Civ5Ai_Bridge._StartPulseForSeat(playerID)
  Civ5Ai_Bridge._ClaimPulseSlot(playerID)
  Civ5Ai_Util.Log(
    "bridge|kick_seat|player="
      .. tostring(playerID)
      .. "|active="
      .. tostring(Game.GetActivePlayer())
      .. "|queued="
      .. tostring(#Civ5Ai_Bridge._seatQueue)
      .. "|parallel="
      .. tostring(Civ5Ai_Bridge._UsesParallelPulses() and 1 or 0)
  )
  Civ5Ai_Util.ScheduleTick(function()
    local ok, err = pcall(function()
      Civ5Ai_Bridge.RunTurnPulse(playerID)
    end)
    if not ok then
      Civ5Ai_Util.Log(
        "bridge|pulse_error|player=" .. tostring(playerID) .. "|" .. tostring(err)
      )
      Civ5Ai_Bridge._ClearPulse(playerID)
      Civ5Ai_Bridge.FinishSeat(playerID)
    end
    return false
  end)
end

function Civ5Ai_Bridge._KickPulseQueue()
  if Civ5Ai_Bridge._UsesParallelPulses() then
    if #Civ5Ai_Bridge._seatQueue == 0 then
      return
    end
    local seat = Civ5Ai_Bridge._TakeNextSeat()
    if seat == nil then
      return
    end
    if Civ5Ai_Bridge._pulseBusyBySeat[seat] then
      table.insert(Civ5Ai_Bridge._seatQueue, seat)
      return
    end
    Civ5Ai_Bridge._StartPulseForSeat(seat)
    if #Civ5Ai_Bridge._seatQueue > 0 then
      Civ5Ai_Util.ScheduleTick(function()
        Civ5Ai_Bridge._KickPulseQueue()
        return false
      end)
    end
    return
  end
  if Civ5Ai_Bridge._pulseBusy then
    return
  end
  local seat = Civ5Ai_Bridge._TakeNextSeat()
  if seat == nil then
    return
  end
  Civ5Ai_Bridge._StartPulseForSeat(seat)
end

function Civ5Ai_Bridge._ReleasePulseSlot(playerID)
  if Civ5Ai_Bridge._UsesParallelPulses() then
    if playerID ~= nil then
      Civ5Ai_Bridge._pulseBusyBySeat[playerID] = nil
    end
  else
    Civ5Ai_Bridge._pulseBusy = false
    Civ5Ai_Bridge._pulseSeat = nil
  end
  Civ5Ai_Bridge._KickPulseQueue()
end

function Civ5Ai_Bridge._AllManagedPulsesFinished(turn)
  for seat = 0, 63 do
    if Civ5Ai_Config.IsManagedSeat(seat) then
      local key = tostring(seat) .. "|" .. tostring(turn)
      if Civ5Ai_Bridge._finishedKeys[key] ~= true then
        return false
      end
    end
  end
  return true
end

function Civ5Ai_Bridge._AnyManagedSeatTurnActive()
  for seat = 0, 63 do
    if Civ5Ai_Config.IsManagedSeat(seat) and Civ5Ai_Bridge._SeatTurnIsActive(seat) then
      return true
    end
  end
  return false
end

function Civ5Ai_Bridge._ForceReleaseManagedSeat(playerID, reason)
  if Civ5Ai_Bridge._UsesUnifiedSeatFinish(playerID) then
    Civ5Ai_Bridge._FinishManagedSeat(playerID, reason)
    return
  end
  Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._BumpHumanEndTurnGen ~= nil then
    Civ5Ai_Autotest._BumpHumanEndTurnGen(playerID)
  end
  Civ5Ai_Bridge._BumpInboxWaitGen(playerID)
  if Civ5Ai_Bridge._inboxWaitActive ~= nil then
    Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
  end
  if not Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
    Civ5Ai_Bridge.ApplyPayload(playerID, Civ5Ai_Bridge._EmptyDecisionJson(playerID), true)
  end
  Civ5Ai_Bridge._PrepareManagedSeatFinish(playerID)
  Civ5Ai_Bridge._ReleaseNativeAi(playerID)
  local turn = Civ5Ai_Bridge._GameTurn()
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, turn)
  if Civ5Ai_Bridge._finishedKeys[key] then
    return
  end
  Civ5Ai_Bridge._finishedKeys[key] = true
  Civ5Ai_Bridge._pulseKeys[key] = nil
  Civ5Ai_Bridge._SetPulseStep(playerID, 6)
  if Civ5Ai_Seats ~= nil then
    Civ5Ai_Seats.MarkDone(playerID)
  end
  if Civ5Ai_Autotest ~= nil then
    Civ5Ai_Autotest.AfterPulse(playerID)
  end
  if Civ5Ai_Seats ~= nil
    and Civ5Ai_Seats.IsLlmHuman(playerID)
    and Civ5Ai_Seats.IsActiveLocalPlayer(playerID)
    and Civ5Ai_Autotest ~= nil
    and Civ5Ai_Autotest.EndHumanTurn ~= nil then
    Civ5Ai_Autotest.EndHumanTurn(playerID)
    return
  end
  Civ5Ai_Bridge._DllFinishManagedSeat(playerID, reason)
  Civ5Ai_Bridge._ReleasePulseSlot(playerID)
end

function Civ5Ai_Bridge._PrepareManagedSeatFinish(playerID)
  if Civ5Ai_Apply == nil then
    return
  end
  if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.UsesCpLimitedFallback(playerID) then
    Civ5Ai_Bridge._ApplyCpLimitedFallback(playerID)
    return
  end
  if Civ5Ai_Apply._WithActivePlayer ~= nil then
    Civ5Ai_Apply._WithActivePlayer(playerID, function()
      if Civ5Ai_Apply.ResolveCityProduction ~= nil then
        Civ5Ai_Apply.ResolveCityProduction(playerID)
      end
      if Civ5Ai_Apply.ResolveResearch ~= nil then
        local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
        local t = EndTurnBlockingTypes
        if not (t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION) then
          Civ5Ai_Apply.ResolveResearch(playerID)
        end
      end
      if Civ5Ai_Apply.ResolvePolicies ~= nil then
        Civ5Ai_Apply.ResolvePolicies(playerID)
      end
      if Civ5Ai_Apply.ResolveFaithBlockers ~= nil then
        Civ5Ai_Apply.ResolveFaithBlockers(playerID)
      end
      if Civ5Ai_Apply._DismissBlockingPopups ~= nil then
        Civ5Ai_Apply._DismissBlockingPopups()
      end
    end)
    return
  end
  if Civ5Ai_Apply.ResolveCityProduction ~= nil then
    Civ5Ai_Apply.ResolveCityProduction(playerID)
  end
  if Civ5Ai_Apply.ResolveResearch ~= nil then
    local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    local t = EndTurnBlockingTypes
    if not (t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION) then
      Civ5Ai_Apply.ResolveResearch(playerID)
    end
  end
  if Civ5Ai_Apply.ResolvePolicies ~= nil then
    Civ5Ai_Apply.ResolvePolicies(playerID)
  end
  if Civ5Ai_Apply.ResolveFaithBlockers ~= nil then
    Civ5Ai_Apply.ResolveFaithBlockers(playerID)
  end
  if Civ5Ai_Apply._DismissBlockingPopups ~= nil then
    Civ5Ai_Apply._DismissBlockingPopups()
  end
end

function Civ5Ai_Bridge._PrepareComputerSeatFinish(playerID)
  Civ5Ai_Bridge._PrepareManagedSeatFinish(playerID)
end

function Civ5Ai_Bridge._SetPulseStep(playerID, step)
  if Civ5Ai_Seats ~= nil then
    Civ5Ai_Seats.SetStep(playerID, step)
  end
end

function Civ5Ai_Bridge.EnsureFinishSeat(playerID)
  if Civ5Ai_Bridge._WasPulseFinished(playerID) then
    return
  end
  if not Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
    return
  end
  Civ5Ai_Bridge._finishRetryPending = Civ5Ai_Bridge._finishRetryPending or {}
  if Civ5Ai_Bridge._finishRetryPending[playerID] then
    return
  end
  -- FPS: HostInbox/LeaderHead may call often while blocked on production/units.
  -- A retry tick already owns progress; do not re-enter FinishSeat <250ms.
  Civ5Ai_Bridge._ensureFinishAt = Civ5Ai_Bridge._ensureFinishAt or {}
  local now = (os and os.clock and os.clock()) or 0
  local last = Civ5Ai_Bridge._ensureFinishAt[playerID]
  local minInterval = 0.25
  local blocking = nil
  local p = Players ~= nil and Players[playerID] or nil
  if p ~= nil and p.GetEndTurnBlockingType ~= nil then
    blocking = p:GetEndTurnBlockingType()
  end
  if blocking == 2 then
    minInterval = 2.0
  end
  if last ~= nil and (now - last) < minInterval then
    return
  end
  Civ5Ai_Bridge._ensureFinishAt[playerID] = now
  Civ5Ai_Bridge.FinishSeat(playerID)
end

function Civ5Ai_Bridge.FinishSeat(playerID)
  if Civ5Ai_Bridge._WasPulseFinished(playerID) then
    return
  end
  local active = Game.GetActivePlayer()
  Civ5Ai_Bridge._LogStep(
    playerID,
    "6_end_turn",
    "in",
    "player="
      .. tostring(playerID)
      .. "\nlocal_active="
      .. tostring(active)
      .. "\nturn_active="
      .. tostring(Civ5Ai_Bridge._SeatTurnIsActive(playerID))
      .. "\napplied="
      .. tostring(Civ5Ai_Bridge._WasAppliedThisPulse(playerID))
  )
  if Civ5Ai_Bridge._UsesUnifiedSeatFinish(playerID) then
    Civ5Ai_Bridge._FinishManagedSeat(playerID, "finish_seat")
    return
  end
  Civ5Ai_Bridge._DisarmSeatTurnTimeout(playerID)
  local key = Civ5Ai_Bridge._PulseKey(playerID)
  Civ5Ai_Bridge._finishedKeys[key] = true
  Civ5Ai_Bridge._pulseKeys[key] = nil
  Civ5Ai_Bridge._SetPulseStep(playerID, 6)
  Civ5Ai_Bridge._DeleteApplyMailbox(playerID)
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    Civ5Ai_Bridge._dumpTurn[playerID] = nil
  end
  local lines = {}
  local humanPending = false
  if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.UsesFullLlmControl(playerID) then
    Civ5Ai_Bridge._ApplyCpLimitedFallback(playerID)
    table.insert(lines, "cp_fallback|units+production|player=" .. tostring(playerID))
    if Civ5Ai_Seats.IsActiveLocalPlayer(playerID) then
      humanPending = true
      if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest.EndHumanTurn ~= nil then
        Civ5Ai_Autotest.EndHumanTurn(playerID)
      end
    else
      Civ5Ai_Bridge._DllFinishManagedSeat(playerID, "finish_seat")
      table.insert(lines, "dll_finish_seat|player=" .. tostring(playerID))
    end
  else
    Civ5Ai_Bridge._ReleaseNativeAi(playerID)
    table.insert(lines, "native_release|player=" .. tostring(playerID))
    Civ5Ai_Util.Log("finish_seat|native_release|player=" .. tostring(playerID))
    Civ5Ai_Bridge._PrepareComputerSeatFinish(playerID)
    table.insert(lines, "computer_prepare|player=" .. tostring(playerID))
    Civ5Ai_Bridge._DllFinishManagedSeat(playerID, "finish_seat_computer")
    table.insert(lines, "dll_finish_seat|player=" .. tostring(playerID))
  end
  local player = Players[playerID]
  if player ~= nil and player.GetEndTurnBlockingType ~= nil then
    table.insert(lines, "blocking=" .. tostring(player:GetEndTurnBlockingType()))
  end
  table.insert(lines, "turn_active=" .. tostring(Civ5Ai_Bridge._SeatTurnIsActive(playerID)))
  table.insert(lines, "local_active=" .. tostring(active))
  if humanPending then
    table.insert(lines, "human_end_turn_pending=1")
  end
  Civ5Ai_Bridge._LogStep(playerID, "6_end_turn", "out", table.concat(lines, "\n"))
  if humanPending then
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  if Civ5Ai_Seats ~= nil then
    Civ5Ai_Seats.MarkDone(playerID)
  end
  if Civ5Ai_Autotest ~= nil then
    Civ5Ai_Autotest.AfterPulse(playerID)
  end
  Civ5Ai_Bridge._ReleasePulseSlot(playerID)
end

function Civ5Ai_Bridge._SchedulePulseRetry(playerID)
  local key = Civ5Ai_Bridge._TurnPulseKey(playerID, Civ5Ai_Bridge._GameTurn())
  if Civ5Ai_Bridge._retryKeys[key] then
    return
  end
  Civ5Ai_Bridge._retryKeys[key] = true
  local attempts = 0
  Civ5Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ5Ai_Bridge._IsGameplayReady(playerID)
        and Civ5Ai_Bridge._CanStartAutotestPulse(playerID)
        and not Civ5Ai_Bridge._AlreadyPulsed(playerID) then
      Civ5Ai_Bridge._retryKeys[key] = nil
      Civ5Ai_Util.Log("bridge|retry_pulse|player=" .. tostring(playerID) .. "|attempts=" .. tostring(attempts))
      Civ5Ai_Bridge.RequestTurnPulse(playerID)
      Civ5Ai_Bridge._KickPulseQueue()
      return false
    end
    if attempts >= 600 then
      Civ5Ai_Bridge._retryKeys[key] = nil
      Civ5Ai_Util.Log("bridge|retry_timeout|player=" .. tostring(playerID))
      Civ5Ai_Bridge._ReleaseNativeAi(playerID)
      return false
    end
    return true
  end)
end

function Civ5Ai_Bridge._EmptyDecisionJson(playerID)
  local turn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID) or Civ5Ai_Bridge._GameTurn()
  return '{"commands":[],"chat_messages":[],"complete":true,"turn":' .. tostring(turn) .. "}"
end

function Civ5Ai_Bridge._ApplyEmptyThenFinish(playerID, reason)
  Civ5Ai_Util.Log("bridge|" .. tostring(reason) .. "|player=" .. tostring(playerID))
  Civ5Ai_Bridge.ApplyPayload(playerID, Civ5Ai_Bridge._EmptyDecisionJson(playerID), true)
  if not Civ5Ai_Bridge._WasPulseFinished(playerID) then
    Civ5Ai_Bridge.FinishSeat(playerID)
  end
end

function Civ5Ai_Bridge._ExtractJsonBalanced(text, startPos, openCh, closeCh)
  local open = string.find(text, openCh, startPos, true)
  if open == nil then
    return nil, startPos
  end
  local depth = 0
  local inString = false
  local escape = false
  for i = open, #text do
    local ch = string.sub(text, i, i)
    if inString then
      if escape then
        escape = false
      elseif ch == "\\" then
        escape = true
      elseif ch == '"' then
        inString = false
      end
    else
      if ch == '"' then
        inString = true
      elseif ch == openCh then
        depth = depth + 1
      elseif ch == closeCh then
        depth = depth - 1
        if depth == 0 then
          return string.sub(text, open, i), i
        end
      end
    end
  end
  return nil, startPos
end

function Civ5Ai_Bridge._ExtractJsonObject(text, startPos)
  return Civ5Ai_Bridge._ExtractJsonBalanced(text, startPos, "{", "}")
end

function Civ5Ai_Bridge._ParseChatMessages(text)
  local found = string.find(text, '"chat_messages"%s*:%s*%[')
  if found == nil then
    return {}
  end
  local bracket = string.find(text, "[", found, true)
  local arrayText = Civ5Ai_Bridge._ExtractJsonBalanced(text, bracket, "[", "]")
  if arrayText == nil then
    return {}
  end
  local chats = {}
  local pos = 2
  while pos < #arrayText do
    local obj, objEnd = Civ5Ai_Bridge._ExtractJsonBalanced(arrayText, pos, "{", "}")
    if obj == nil then
      break
    end
    local target = Civ5Ai_Util.ReadJsonStringField(obj, "target") or "all"
    local body = Civ5Ai_Util.ReadJsonStringField(obj, "text")
    local dest = Civ5Ai_Util.ReadJsonStringField(obj, "target_player_id")
    if body ~= nil and body ~= "" then
      table.insert(chats, {
        target = target,
        text = body,
        target_player_id = dest,
      })
    end
    pos = objEnd + 1
  end
  return chats
end

function Civ5Ai_Bridge._ReadJsonIntField(objectText, key)
  local value = string.match(objectText or "", '"' .. key .. '"%s*:%s*(%-?%d+)')
  if value ~= nil then
    return tonumber(value)
  end
  return nil
end

function Civ5Ai_Bridge._ParseCommandArguments(objectText)
  local arguments = {}
  local argsKey = string.find(objectText or "", '"arguments"%s*:%s*{')
  if argsKey == nil then
    return arguments
  end
  local brace = string.find(objectText, "{", argsKey, true)
  local argsSlice = Civ5Ai_Bridge._ExtractJsonBalanced(objectText, brace, "{", "}")
  if argsSlice == nil then
    return arguments
  end
  local techId = string.match(argsSlice, '"tech_id"%s*:%s*"([^"]+)"')
  if techId ~= nil then
    arguments.tech_id = techId
  end
  local unitId = string.match(argsSlice, '"unit_id"%s*:%s*"([^"]+)"')
  if unitId ~= nil then
    arguments.unit_id = unitId
  end
  local cityId = string.match(argsSlice, '"city_id"%s*:%s*"([^"]+)"')
  if cityId ~= nil then
    arguments.city_id = cityId
  end
  local status = string.match(argsSlice, '"status"%s*:%s*"([^"]+)"')
  if status ~= nil then
    arguments.status = status
  end
  local buildId = string.match(argsSlice, '"build_id"%s*:%s*"([^"]+)"')
  if buildId ~= nil then
    arguments.build_id = buildId
  end
  local policyId = string.match(argsSlice, '"policy_id"%s*:%s*"([^"]+)"')
  if policyId ~= nil then
    arguments.policy_id = policyId
  end
  local branchId = string.match(argsSlice, '"policy_branch_id"%s*:%s*"([^"]+)"')
  if branchId ~= nil then
    arguments.policy_branch_id = branchId
  end
  local targetX = Civ5Ai_Bridge._ReadJsonIntField(argsSlice, "target_x")
  if targetX ~= nil then
    arguments.target_x = targetX
  end
  local targetY = Civ5Ai_Bridge._ReadJsonIntField(argsSlice, "target_y")
  if targetY ~= nil then
    arguments.target_y = targetY
  end
  return arguments
end

function Civ5Ai_Bridge._HydrateCommandArguments(commandId, arguments)
  arguments = arguments or {}
  if commandId == nil or commandId == "" then
    return arguments
  end
  if arguments.tech_id == nil then
    local techId = string.match(commandId, "^CMD_research_(.+)$")
    if techId ~= nil then
      arguments.tech_id = techId
    end
  end
  if arguments.policy_id == nil then
    local policyId = string.match(commandId, "^CMD_policy_(.+)$")
    if policyId ~= nil then
      arguments.policy_id = policyId
    end
  end
  if arguments.policy_branch_id == nil then
    local branchId = string.match(commandId, "^CMD_(?:branch|ideology)_(.+)$")
    if branchId ~= nil then
      arguments.policy_branch_id = branchId
    end
  end
  if arguments.city_id == nil or arguments.build_id == nil then
    local cityId, buildId = string.match(
      commandId,
      "^CMD_prod_(.+)_((?:UNIT_|BUILDING_|PROJECT_|PROCESS_).+)$"
    )
    if cityId ~= nil and buildId ~= nil then
      if arguments.city_id == nil then
        arguments.city_id = cityId
      end
      if arguments.build_id == nil then
        arguments.build_id = buildId
      end
    end
  end
  if arguments.city_id == nil or arguments.build_id == nil then
    local cityId, buildId = string.match(
      commandId,
      "^CMD_buy_gold_(.+)_((?:UNIT_|BUILDING_|PROJECT_|PROCESS_).+)$"
    )
    if cityId ~= nil and buildId ~= nil then
      if arguments.city_id == nil then
        arguments.city_id = cityId
      end
      if arguments.build_id == nil then
        arguments.build_id = buildId
      end
    end
  end
  if arguments.city_id == nil or arguments.status == nil then
    local cityId, status = string.match(commandId, "^CMD_capture_(.+)_((?:puppet|annex|raze))$")
    if cityId ~= nil and status ~= nil then
      if arguments.city_id == nil then
        arguments.city_id = cityId
      end
      if arguments.status == nil then
        arguments.status = status
      end
    end
  end
  if arguments.unit_id == nil or arguments.target_x == nil or arguments.target_y == nil then
    local unitId, targetX, targetY = string.match(
      commandId,
      "^CMD_(?:move|attack|range|rebase|paradrop|nuke)_(UNIT_%d+)_(-?%d+)_(-?%d+)$"
    )
    if unitId ~= nil then
      if arguments.unit_id == nil then
        arguments.unit_id = unitId
      end
      if arguments.target_x == nil then
        arguments.target_x = tonumber(targetX)
      end
      if arguments.target_y == nil then
        arguments.target_y = tonumber(targetY)
      end
    end
  end
  if arguments.unit_id == nil then
    local unitId = string.match(commandId, "^CMD_(?:fortify|skip|found|sleep|alert|heal|discover|hurry|trade|golden|greatwork|spread|heresy|pillage|intercept)_(.+)$")
    if unitId ~= nil then
      arguments.unit_id = unitId
    end
  end
  if arguments.build_id == nil then
    local unitId, buildId = string.match(commandId, "^CMD_improve_(.+)_((?:BUILD_|IMPROVEMENT_).+)$")
    if unitId ~= nil and buildId ~= nil then
      if arguments.unit_id == nil then
        arguments.unit_id = unitId
      end
      arguments.build_id = buildId
    end
  end
  if arguments.unit_type_id == nil then
    local unitId, typeId = string.match(commandId, "^CMD_upgrade_(UNIT_%d+)_(UNIT_.+)$")
    if unitId ~= nil and typeId ~= nil then
      if arguments.unit_id == nil then
        arguments.unit_id = unitId
      end
      arguments.unit_type_id = typeId
    end
  end
  if arguments.automate_id == nil then
    local unitId, automateId = string.match(commandId, "^CMD_automate_(.+)_((?:AUTOMATE_).+)$")
    if unitId ~= nil and automateId ~= nil then
      if arguments.unit_id == nil then
        arguments.unit_id = unitId
      end
      arguments.automate_id = automateId
    end
  end
  if arguments.target_player_id == nil then
    local targetId = string.match(commandId, "^CMD_declare_war_(PLAYER_%d+)$")
    if targetId ~= nil then
      arguments.target_player_id = targetId
    end
  end
  return arguments
end

function Civ5Ai_Bridge._KindFromCommandId(commandId)
  return Civ5Ai_Commands.KindFromCommandId(commandId)
end

function Civ5Ai_Bridge._ParseOneCommandObject(obj)
  if obj == nil or obj == "" then
    return nil
  end
  local commandId = string.match(obj, '"command_id"%s*:%s*"([^"]+)"')
  local kind = string.match(obj, '"kind"%s*:%s*"([^"]+)"')
  if kind == nil then
    kind = Civ5Ai_Bridge._KindFromCommandId(commandId)
  end
  if kind == nil then
    return nil
  end
  local arguments = Civ5Ai_Bridge._HydrateCommandArguments(
    commandId,
    Civ5Ai_Bridge._ParseCommandArguments(obj)
  )
  return {
    kind = kind,
    command_id = commandId or "",
    arguments = arguments,
  }
end

function Civ5Ai_Bridge._CommandFromTable(obj)
  if type(obj) ~= "table" then
    return nil
  end
  local commandId = obj.command_id
  local kind = obj.kind
  if kind == nil then
    kind = Civ5Ai_Bridge._KindFromCommandId(commandId)
  end
  if kind == nil then
    return nil
  end
  local arguments = Civ5Ai_Bridge._HydrateCommandArguments(commandId, obj.arguments or {})
  return {
    kind = kind,
    command_id = commandId or "",
    arguments = arguments,
  }
end

function Civ5Ai_Bridge._ParseDecision(text)
  local decoded = Civ5Ai_Util.DecodeJson(text)
  if type(decoded) == "table" then
    local commands = {}
    if type(decoded.commands) == "table" then
      for _, obj in ipairs(decoded.commands) do
        local ok, command = pcall(Civ5Ai_Bridge._CommandFromTable, obj)
        if ok and command ~= nil then
          table.insert(commands, command)
        else
          Civ5Ai_Util.Log("bridge|command_parse_skip|json")
        end
      end
    end
    local chats = decoded.chat_messages
    if type(chats) ~= "table" then
      chats = {}
    end
    return {
      commands = commands,
      chat_messages = chats,
      turn = tonumber(decoded.turn),
      complete = decoded.complete == true,
    }
  end
  local commands = {}
  local found = string.find(text, '"commands"%s*:%s*%[')
  if found ~= nil then
    local bracket = string.find(text, "[", found, true)
    local arrayText = Civ5Ai_Bridge._ExtractJsonBalanced(text, bracket, "[", "]")
    if arrayText == nil then
      arrayText = string.sub(text, bracket or found)
    end
    local pos = 2
    while pos < #arrayText do
      local obj, objEnd = Civ5Ai_Bridge._ExtractJsonBalanced(arrayText, pos, "{", "}")
      if obj == nil then
        local nextOpen = string.find(arrayText, "{", pos + 1, true)
        if nextOpen == nil then
          break
        end
        pos = nextOpen
      else
        local ok, command = pcall(Civ5Ai_Bridge._ParseOneCommandObject, obj)
        if ok and command ~= nil then
          table.insert(commands, command)
        else
          Civ5Ai_Util.Log("bridge|command_parse_skip|pos=" .. tostring(pos))
        end
        pos = objEnd + 1
      end
    end
  end
  return {
    commands = commands,
    chat_messages = Civ5Ai_Bridge._ParseChatMessages(text),
    turn = tonumber(string.match(text, '"turn"%s*:%s*(%-?%d+)')),
    complete = string.find(text, '"complete"%s*:%s*true', 1, false) ~= nil,
  }
end

function Civ5Ai_Bridge._ApplyChat(playerID, messages)
  if messages == nil or #messages == 0 then
    return 0
  end
  -- Civ4: chat is social-only. A display miss must not cancel commands.
  local ok, result = pcall(Civ5Ai_Chat.ApplyMessages, playerID, messages)
  if not ok then
    Civ5Ai_Util.Log("bridge|chat_failed|" .. tostring(result))
    return 0
  end
  Civ5Ai_Util.Log(
    "bridge|chat_sent|player=" .. tostring(playerID) .. "|n=" .. tostring(result)
  )
  return result
end

function Civ5Ai_Bridge._CommandListText(decision)
  local parts = {}
  if decision == nil or decision.commands == nil then
    return ""
  end
  for _, command in ipairs(decision.commands) do
    table.insert(
      parts,
      tostring(command.kind)
        .. " "
        .. tostring(command.command_id)
        .. " "
        .. tostring(command.arguments and command.arguments.unit_id or "")
    )
  end
  return table.concat(parts, "\n")
end

function Civ5Ai_Bridge._ShouldApplyViaNet()
  if Civ5Ai_Config == nil or not Civ5Ai_Config.IsNetApply() then
    return false
  end
  if Civ5Ai_Net == nil or Civ5Ai_Net._IsHost == nil or not Civ5Ai_Net._IsHost() then
    return false
  end
  return Game ~= nil and Game.SendCiv5AiCommands ~= nil
end

function Civ5Ai_Bridge.ApplyPayload(playerID, jsonText, forceEmpty)
  if jsonText == nil or jsonText == "" then
    return false
  end
  -- HostInbox (and any VM without Civ5Ai_Apply) must not parse/apply: doing so
  -- logs no_SendCiv5AiCommands then errors before MarkApplied and poisons
  -- mailboxes into an infinite re-parse loop beside CONTROL_ENDTURN.
  if Civ5Ai_Apply == nil or Civ5Ai_Apply.ApplyDecision == nil then
    Civ5Ai_Util.Log(
      "bridge|apply_abort_no_apply_module|player="
        .. tostring(playerID)
    )
    return false
  end
  local ok, decision = pcall(Civ5Ai_Bridge._ParseDecision, jsonText)
  if not ok or type(decision) ~= "table" then
    Civ5Ai_Util.Log("bridge|parse_failed|player=" .. tostring(playerID) .. "|" .. tostring(decision))
    decision = { commands = {}, chat_messages = {} }
  end
  local parsedText = Civ5Ai_Bridge._CommandListText(decision)
  local nCommands = #(decision.commands or {})
  local nChat = #(decision.chat_messages or {})
  local payloadTurn = tonumber(decision.turn)
  local expectedTurn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
  if payloadTurn ~= nil and expectedTurn ~= nil and payloadTurn ~= expectedTurn then
    Civ5Ai_Util.Log(
      "bridge|apply_stale_turn|player="
        .. tostring(playerID)
        .. "|expected="
        .. tostring(expectedTurn)
        .. "|got="
        .. tostring(payloadTurn)
    )
    Civ5Ai_Bridge._LogStep(playerID, "5_apply", "out", "apply_stale_turn")
    return false
  end
  -- If this pulse already applied non-empty commands, ignore a later mailbox
  -- without rewriting 4_parse/5_apply_in. Rewriting those steps made apply_in
  -- look like it matched a newer parse_out even though the earlier commands ran.
  if Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
    if Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) and nCommands > 0 then
      Civ5Ai_Util.Log("bridge|apply_replace_empty|player=" .. tostring(playerID))
      local appliedKey = Civ5Ai_Bridge._PulseKey(playerID)
      Civ5Ai_Bridge._appliedKeys[appliedKey] = nil
      Civ5Ai_Bridge._emptyAppliedKeys = Civ5Ai_Bridge._emptyAppliedKeys or {}
      Civ5Ai_Bridge._emptyAppliedKeys[appliedKey] = nil
      if Civ5Ai_Bridge._emptyApplyAt ~= nil then
        Civ5Ai_Bridge._emptyApplyAt[playerID] = nil
      end
    else
      Civ5Ai_Util.Log("bridge|apply_skip_duplicate|player=" .. tostring(playerID))
      if nCommands > 0 then
        Civ5Ai_Util.Log(
          "bridge|apply_mailbox_ignored_after_apply|player="
            .. tostring(playerID)
            .. "|new_commands="
            .. tostring(nCommands)
        )
      end
      Civ5Ai_Bridge._LogStep(playerID, "5_apply", "out", "apply_skip_duplicate")
      return true
    end
  end
  Civ5Ai_Bridge._SetPulseStep(playerID, 4)
  Civ5Ai_Bridge._LogStep(playerID, "4_parse", "in", jsonText)
  Civ5Ai_Bridge._LogStep(playerID, "4_parse", "out", parsedText)
  Civ5Ai_Bridge._SetPulseStep(playerID, 5)
  Civ5Ai_Bridge._LogStep(playerID, "5_apply", "in", parsedText)
  local applyLines = {}
  local complete = decision.complete == true
  if nCommands == 0 and nChat == 0 then
    -- Empty payload (complete or not) ends the seat. Native AI handles leftovers.
    Civ5Ai_Util.Log(
      "bridge|apply_empty|player="
        .. tostring(playerID)
        .. "|complete="
        .. tostring(complete)
        .. "|force="
        .. tostring(forceEmpty == true)
    )
    table.insert(applyLines, "apply_empty")
    Civ5Ai_Bridge._MarkApplied(playerID)
    Civ5Ai_Bridge._MarkEmptyApplied(playerID)
    Civ5Ai_Bridge._LogStep(playerID, "5_apply", "out", table.concat(applyLines, "\n"))
    return true
  end
  -- Net broadcast when the overlay method exists. Otherwise ApplyDecision
  -- below is the one apply engine (SP autoplay). Do not spin forever.
  if Civ5Ai_Config ~= nil and Civ5Ai_Config.IsNetApply()
    and Game ~= nil and Game.SendCiv5AiCommands ~= nil
    and Civ5Ai_Net ~= nil and Civ5Ai_Net.BroadcastDecision ~= nil
    and Civ5Ai_Net._IsHost() then
    if Civ5Ai_Net.BroadcastDecision(playerID, decision) then
      if Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
        table.insert(applyLines, "apply_via_net")
        table.insert(
          applyLines,
          "apply_payload|player="
            .. tostring(playerID)
            .. "|turn="
            .. tostring(Civ5Ai_Bridge._GameTurn())
            .. "|commands="
            .. tostring(nCommands)
            .. "|chat="
            .. tostring(nChat)
        )
        Civ5Ai_Util.Log(
          "bridge|apply_via_net|player="
            .. tostring(playerID)
            .. "|commands="
            .. tostring(nCommands)
            .. "|chat="
            .. tostring(nChat)
        )
        Civ5Ai_Bridge._LogStep(playerID, "5_apply", "out", table.concat(applyLines, "\n"))
        return true
      end
    end
  elseif Civ5Ai_Config ~= nil and Civ5Ai_Config.IsNetApply() then
    Civ5Ai_Util.Log("bridge|apply_local|no_SendCiv5AiCommands|player=" .. tostring(playerID))
  end
  if nCommands > 0 then
    local lines = Civ5Ai_Apply.ApplyDecision(playerID, decision)
    if type(lines) == "table" then
      for _, line in ipairs(lines) do
        table.insert(applyLines, line)
      end
    end
  else
    table.insert(applyLines, "chat_only")
  end
  Civ5Ai_Bridge._ApplyChat(playerID, decision.chat_messages)
  Civ5Ai_Bridge._MarkApplied(playerID)
  table.insert(
    applyLines,
    "apply_payload|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(Civ5Ai_Bridge._GameTurn())
      .. "|commands="
      .. tostring(nCommands)
      .. "|chat="
      .. tostring(nChat)
  )
  Civ5Ai_Util.Log(applyLines[#applyLines])
  Civ5Ai_Bridge._LogStep(playerID, "5_apply", "out", table.concat(applyLines, "\n"))
  return true
end

function Civ5Ai_Bridge._ApplyDecisionFiles(playerID, decisionPath)
  if Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
    return true
  end
  local decisionText = Civ5Ai_Util.ReadTextFile(decisionPath)
  if decisionText == nil or decisionText == "" then
    return false
  end
  Civ5Ai_Bridge.ApplyPayload(playerID, decisionText)
  return true
end

function Civ5Ai_Bridge._CanApplyInGame(playerID)
  if Players == nil or Players[playerID] == nil then
    return false
  end
  -- Single-player: GetActivePlayer stays the human while AI seats dump.
  -- Blocking apply on that check meant LLM commands never ran.
  return true
end

function Civ5Ai_Bridge._EnsureApplyPoller()
end

function Civ5Ai_Bridge._EraseApplyPendingOnDisk(playerID)
  Civ5Ai_Bridge._pendingEraseFailed = Civ5Ai_Bridge._pendingEraseFailed or {}
  local stub = "-- cleared by Civ5Ai after apply\nCiv5Ai_ApplyPendingMeta = nil\nCiv5Ai_ApplyPendingJson = \"\"\nCiv5Ai_ApplyPendingB64 = \"\"\n"
  local paths = {}
  if playerID ~= nil and Civ5Ai_Util ~= nil and Civ5Ai_Util.ApplyPendingCandidatePaths ~= nil then
    paths = Civ5Ai_Util.ApplyPendingCandidatePaths(playerID)
  elseif Civ5Ai_Util ~= nil and Civ5Ai_Util.AllApplyPendingDiskPaths ~= nil then
    paths = Civ5Ai_Util.AllApplyPendingDiskPaths()
  elseif Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ApplyPendingPaths ~= nil then
    paths = Civ5Ai_Paths.ApplyPendingPaths
  else
    return
  end
  for _, path in ipairs(paths) do
    if Civ5Ai_Bridge._pendingEraseFailed[path] then
    elseif Civ5Ai_Util.WriteTextFile(path, stub) then
      Civ5Ai_Bridge._pendingEraseFailed[path] = nil
    else
      Civ5Ai_Bridge._pendingEraseFailed[path] = true
    end
  end
end

function Civ5Ai_Bridge._ClearPendingApplyMod()
  local playerID = nil
  if Civ5Ai_ApplyPendingMeta ~= nil then
    playerID = Civ5Ai_ApplyPendingMeta.player
  end
  Civ5Ai_ApplyPendingJson = ""
  Civ5Ai_ApplyPendingB64 = ""
  Civ5Ai_ApplyPendingMeta = nil
  Civ5Ai_Bridge._EraseApplyPendingOnDisk(playerID)
end

function Civ5Ai_Bridge._PendingApplyKey(meta)
  if meta == nil then
    return nil
  end
  return tostring(meta.session_id) .. "|" .. tostring(meta.player) .. "|" .. tostring(meta.turn)
end

function Civ5Ai_Bridge._WasPendingApplied(meta)
  local key = Civ5Ai_Bridge._PendingApplyKey(meta)
  return key ~= nil and Civ5Ai_Bridge._appliedPendingKeys[key] == true
end

function Civ5Ai_Bridge._MarkPendingApplied(meta)
  local key = Civ5Ai_Bridge._PendingApplyKey(meta)
  if key ~= nil then
    Civ5Ai_Bridge._appliedPendingKeys[key] = true
  end
end

function Civ5Ai_Bridge._LogPendingRejectOnce(code, detail)
  local sig = tostring(code) .. "|" .. tostring(detail)
  if Civ5Ai_Bridge._pendingRejectSig == sig then
    return
  end
  Civ5Ai_Bridge._pendingRejectSig = sig
  Civ5Ai_Util.Log("bridge|" .. tostring(code) .. "|" .. tostring(detail))
end

function Civ5Ai_Bridge._BumpInboxWaitGen(playerID)
  Civ5Ai_Bridge._inboxWaitGen[playerID] = (Civ5Ai_Bridge._inboxWaitGen[playerID] or 0) + 1
end

function Civ5Ai_Bridge._InboxWaitStale(playerID, gen)
  return Civ5Ai_Bridge._inboxWaitGen[playerID] ~= gen
end

function Civ5Ai_Bridge._ShortLuaError(err)
  local text = tostring(err or "")
  local firstLine = string.match(text, "^(.-)\n") or text
  if string.len(firstLine) > 160 then
    return string.sub(firstLine, 1, 160) .. "..."
  end
  return firstLine
end

function Civ5Ai_Bridge._NormalizeApplyPendingGlobals()
  if Civ5Ai_ApplyPendingB64 ~= nil and Civ5Ai_ApplyPendingB64 ~= "" then
    local decoded = Civ5Ai_Util.Base64Decode(Civ5Ai_ApplyPendingB64)
    if decoded ~= nil and decoded ~= "" then
      Civ5Ai_ApplyPendingJson = decoded
    end
  end
end

function Civ5Ai_Bridge._ClearApplyPendingGlobals()
  Civ5Ai_ApplyPendingJson = ""
  Civ5Ai_ApplyPendingB64 = ""
  Civ5Ai_ApplyPendingMeta = nil
end

function Civ5Ai_Bridge._RunApplyPendingChunk(chunk)
  if chunk == nil then
    return false
  end
  Civ5Ai_Bridge._ClearApplyPendingGlobals()
  local ok, err = pcall(chunk)
  if not ok then
    Civ5Ai_Util.Log("bridge|apply_pending_chunk_failed|" .. Civ5Ai_Bridge._ShortLuaError(err))
    return false
  end
  Civ5Ai_Bridge._NormalizeApplyPendingGlobals()
  return Civ5Ai_ApplyPendingJson ~= nil and Civ5Ai_ApplyPendingJson ~= ""
end

function Civ5Ai_Bridge._LoadApplyPendingText(path)
  if path == nil or path == "" then
    return nil
  end
  return Civ5Ai_Util.ReadTextFile(path)
end

function Civ5Ai_Bridge._RunApplyPendingPath(path)
  if path == nil or path == "" then
    return false
  end
  local text = Civ5Ai_Bridge._LoadApplyPendingText(path)
  if text ~= nil and text ~= "" then
    Civ5Ai_Bridge._ClearApplyPendingGlobals()
    local chunk, err = loadstring(text)
    if chunk ~= nil then
      if Civ5Ai_Bridge._RunApplyPendingChunk(chunk) then
        return true
      end
    else
      Civ5Ai_Util.Log("bridge|apply_pending_loadstring_failed|" .. Civ5Ai_Bridge._ShortLuaError(err))
    end
  end
  if dofile ~= nil then
    local ok, err = pcall(function()
      Civ5Ai_Bridge._ClearApplyPendingGlobals()
      dofile(path)
    end)
    if ok and Civ5Ai_ApplyPendingJson ~= nil and Civ5Ai_ApplyPendingJson ~= "" then
      return true
    end
    if ok then
      Civ5Ai_Bridge._NormalizeApplyPendingGlobals()
      if Civ5Ai_ApplyPendingJson ~= nil and Civ5Ai_ApplyPendingJson ~= "" then
        return true
      end
    end
    if not ok then
      Civ5Ai_Util.Log("bridge|apply_pending_dofile_failed|" .. Civ5Ai_Bridge._ShortLuaError(err))
    end
  end
  if loadfile ~= nil then
    local chunk = loadfile(path)
    if Civ5Ai_Bridge._RunApplyPendingChunk(chunk) then
      return true
    end
    local alt = path:gsub("/", "\\")
    if alt ~= path then
      chunk = loadfile(alt)
      if Civ5Ai_Bridge._RunApplyPendingChunk(chunk) then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Bridge._PendingApplyFilename(playerID)
  return "apply_pending_p" .. tostring(playerID) .. ".lua"
end

function Civ5Ai_Bridge._ReloadPendingApplyMod(playerID)
  if package ~= nil and package.loaded ~= nil then
    for key, _ in pairs(package.loaded) do
      if type(key) == "string" and string.find(key, "ApplyPending", 1, true) then
        package.loaded[key] = nil
      end
    end
  end
  Civ5Ai_Bridge._ClearApplyPendingGlobals()
  local loaded = false
  local paths = {}
  if Civ5Ai_Util ~= nil and Civ5Ai_Util.ApplyPendingCandidatePaths ~= nil then
    paths = Civ5Ai_Util.ApplyPendingCandidatePaths(playerID)
  elseif playerID ~= nil then
    table.insert(paths, Civ5Ai_Bridge._PendingApplyFilename(playerID))
    table.insert(paths, "apply_pending.lua")
    if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ApplyPendingPaths ~= nil then
      for _, path in ipairs(Civ5Ai_Paths.ApplyPendingPaths) do
        table.insert(paths, path)
      end
    end
  end
  for _, path in ipairs(paths) do
    if Civ5Ai_Bridge._RunApplyPendingPath(path) then
      loaded = true
      break
    end
  end
  if loaded then
    local meta = Civ5Ai_ApplyPendingMeta or {}
    local sig =
      tostring(meta.session_id)
      .. "|"
      .. tostring(meta.player)
      .. "|"
      .. tostring(meta.turn)
      .. "|"
      .. tostring(string.len(Civ5Ai_ApplyPendingJson or ""))
    if sig ~= Civ5Ai_Bridge._pendingLoadSig then
      Civ5Ai_Bridge._pendingLoadSig = sig
      Civ5Ai_Util.Log(
        "bridge|apply_pending_loaded|session="
          .. tostring(meta.session_id)
          .. "|player="
          .. tostring(meta.player)
          .. "|turn="
          .. tostring(meta.turn)
          .. "|len="
          .. tostring(string.len(Civ5Ai_ApplyPendingJson or ""))
      )
    end
    Civ5Ai_Bridge._pendingMissLogged = false
  else
    Civ5Ai_Bridge._ClearApplyPendingGlobals()
    if not Civ5Ai_Bridge._pendingMissLogged then
      Civ5Ai_Bridge._pendingMissLogged = true
      local first = nil
      if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ApplyPendingPaths ~= nil then
        first = Civ5Ai_Paths.ApplyPendingPaths[1]
      end
      Civ5Ai_Util.Log("bridge|apply_pending_miss|path=" .. tostring(first))
    end
  end
end

function Civ5Ai_Bridge._PendingApplyIsCurrent(playerID)
  if Civ5Ai_ApplyPendingJson == nil or Civ5Ai_ApplyPendingJson == "" then
    return false
  end
  local meta = Civ5Ai_ApplyPendingMeta
  if meta == nil then
    Civ5Ai_Util.Log("bridge|pending_apply_missing_meta")
    return false
  end
  local sessionId = Civ5Ai_Bridge.SessionId()
  if meta.session_id ~= nil and meta.session_id ~= sessionId then
    Civ5Ai_Bridge._LogPendingRejectOnce(
      "pending_apply_stale_session",
      "expected=" .. tostring(sessionId) .. "|got=" .. tostring(meta.session_id)
    )
    Civ5Ai_Bridge._ClearPendingApplyMod()
    return false
  end
  if meta.player ~= nil and tonumber(meta.player) ~= tonumber(playerID) then
    return false
  end
  if Civ5Ai_Bridge._WasPendingApplied(meta) then
    return false
  end
  local gameTurn = tonumber(Civ5Ai_Bridge._GameTurn()) or 0
  local pendingTurn = tonumber(meta.turn) or 0
  local dumpTurn = nil
  if Civ5Ai_Bridge._dumpTurn ~= nil then
    dumpTurn = tonumber(Civ5Ai_Bridge._dumpTurn[playerID])
  end
  if pendingTurn > gameTurn and (dumpTurn == nil or pendingTurn ~= dumpTurn) then
    Civ5Ai_Bridge._LogPendingRejectOnce(
      "pending_apply_future_turn",
      "player=" .. tostring(playerID) .. "|expected<=" .. tostring(gameTurn) .. "|got=" .. tostring(pendingTurn)
    )
    return false
  end
  if pendingTurn < gameTurn then
    if dumpTurn ~= nil and pendingTurn == dumpTurn then
      return true
    end
    Civ5Ai_Bridge._LogPendingRejectOnce(
      "pending_apply_late",
      "player=" .. tostring(playerID) .. "|game_turn=" .. tostring(gameTurn) .. "|got=" .. tostring(pendingTurn)
    )
    Civ5Ai_Bridge._ClearPendingApplyMod()
    return false
  end
  return true
end

function Civ5Ai_Bridge._TryPendingApplyFromMod(playerID, reload)
  if reload then
    Civ5Ai_Bridge._ReloadPendingApplyMod(playerID)
  end
  if not Civ5Ai_Bridge._PendingApplyIsCurrent(playerID) then
    return false
  end
  if Civ5Ai_Bridge._WasAppliedThisPulse(playerID)
      and not Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
    if Civ5Ai_ApplyPendingMeta ~= nil then
      Civ5Ai_Bridge._MarkPendingApplied(Civ5Ai_ApplyPendingMeta)
      Civ5Ai_Bridge._ClearPendingApplyMod()
      Civ5Ai_Util.Log("bridge|pending_apply_already|player=" .. tostring(playerID))
    end
    return true
  end
  if not Civ5Ai_Bridge._CanApplyInGame(playerID) then
    Civ5Ai_Util.Log("bridge|pending_apply_deferred|player=" .. tostring(playerID))
    return false
  end
  local jsonText = Civ5Ai_ApplyPendingJson
  Civ5Ai_Util.Log(
    "bridge|pending_apply|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(Civ5Ai_Bridge._GameTurn())
      .. "|len="
      .. tostring(string.len(jsonText or ""))
  )
  if Civ5Ai_Bridge.ApplyPayload(playerID, jsonText) then
    Civ5Ai_Util.Log("bridge|pending_apply_ok|player=" .. tostring(playerID))
    Civ5Ai_Bridge._MarkPendingApplied(Civ5Ai_ApplyPendingMeta)
    Civ5Ai_Bridge._ClearPendingApplyMod()
    return true
  end
  return false
end

function Civ5Ai_Bridge._ApplyPulseMailbox(playerID, jsonText)
  if jsonText == nil or jsonText == "" then
    return false
  end
  local applyTurn = tonumber(string.match(jsonText, '"turn"%s*:%s*(%-?%d+)'))
  local dumpTurn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
  if applyTurn ~= dumpTurn then
    return false
  end
  return Civ5Ai_Bridge.ApplyPayload(playerID, jsonText)
end

function Civ5Ai_Bridge._TryApplyProductionMailboxDuringFinish(playerID)
  if Civ5Ai_Apply == nil or Civ5Ai_Apply.ApplyDecision == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t == nil or blocking ~= t.ENDTURN_BLOCKING_PRODUCTION then
    return false
  end
  for _, path in ipairs(Civ5Ai_Bridge._ApplyMailboxPaths(playerID)) do
    local jsonText = Civ5Ai_Util.ReadTextFile(path)
    if jsonText ~= nil and jsonText ~= "" then
      local applyTurn = tonumber(string.match(jsonText, '"turn"%s*:%s*(%-?%d+)'))
      local dumpTurn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
      if applyTurn == dumpTurn then
        local ok, decision = pcall(Civ5Ai_Bridge._ParseDecision, jsonText)
        if ok and type(decision) == "table" then
          local prod = {}
          for _, cmd in ipairs(decision.commands or {}) do
            if cmd ~= nil and cmd.kind == "queue_production" then
              table.insert(prod, cmd)
            end
          end
          if #prod > 0 then
            Civ5Ai_Util.Log(
              "bridge|finish_apply_production|player="
                .. tostring(playerID)
                .. "|commands="
                .. tostring(#prod)
            )
            Civ5Ai_Apply.ApplyDecision(playerID, {
              commands = prod,
              chat_messages = {},
              complete = true,
              turn = applyTurn,
            })
            return true
          end
        end
      end
    end
  end
  return false
end

function Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
  if Civ5Ai_Bridge._WasAppliedThisPulse(playerID)
      and not Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
    return true
  end
  if not Civ5Ai_Bridge._CanApplyInGame(playerID) then
    return false
  end
  -- FPS: responsive_wait / finish retries poll mailboxes often. Skip disk reads
  -- for 500ms after an empty miss (sidecar writes are not per-frame).
  Civ5Ai_Bridge._mailboxMissUntil = Civ5Ai_Bridge._mailboxMissUntil or {}
  local now = (os and os.clock and os.clock()) or 0
  local missUntil = Civ5Ai_Bridge._mailboxMissUntil[playerID]
  if missUntil ~= nil and now < missUntil then
    return false
  end
  local sawAny = false
  for _, path in ipairs(Civ5Ai_Bridge._ApplyMailboxPaths(playerID)) do
    local jsonText = Civ5Ai_Util.ReadTextFile(path)
    if jsonText ~= nil and jsonText ~= "" then
      sawAny = true
      local applyTurn = tonumber(string.match(jsonText, '"turn"%s*:%s*(%-?%d+)'))
      local dumpTurn = Civ5Ai_Bridge._ExpectedApplyTurn(playerID)
      if applyTurn == dumpTurn then
        Civ5Ai_Bridge._mailboxMissUntil[playerID] = nil
        return Civ5Ai_Bridge.ApplyPayload(playerID, jsonText)
      end
    end
  end
  if not sawAny then
    Civ5Ai_Bridge._mailboxMissUntil[playerID] = now + 0.5
  end
  return false
end

function Civ5Ai_Bridge._ScheduleInboxApplyWait(playerID)
  -- Wait for a mailbox, then finish. SeatTurnCap always ends the seat.
  -- Empty apply must NOT finish immediately: a duplicate skip_duplicate worker
  -- used to publish empty complete while the claim holder was still thinking
  -- (live t73/t79/t80/t81). Keep waiting for apply_replace_empty until grace
  -- expires or seat_turn_cap force-releases.
  if Civ5Ai_Bridge._WasAppliedThisPulse(playerID)
      and not Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
    if not Civ5Ai_Bridge._WasPulseFinished(playerID) then
      Civ5Ai_Bridge.FinishSeat(playerID)
    end
    return
  end
  local responsive = Civ5Ai_Config ~= nil and Civ5Ai_Config.IsResponsiveWait()
  Civ5Ai_Bridge._inboxWaitActive = Civ5Ai_Bridge._inboxWaitActive or {}
  Civ5Ai_Bridge._inboxWaitActive[playerID] = true
  if responsive then
    -- Keep the seat turn open and native AI held, but release bridge bookkeeping
    -- and UI focus so the map stays interactive while the sidecar runs.
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    local host = Civ5Ai_Bridge._HostChannel()
    if host ~= nil and host.ReleaseUiFocus ~= nil then
      host.ReleaseUiFocus()
    end
    Civ5Ai_Util.Log(
      "bridge|responsive_wait|player="
        .. tostring(playerID)
        .. "|turn="
        .. tostring(Civ5Ai_Bridge._ExpectedApplyTurn(playerID))
    )
  else
    local host = Civ5Ai_Bridge._HostChannel()
    local waitSeconds = Civ5Ai_Config.SeatTurnCapSeconds()
    if host ~= nil and host.Arm ~= nil then
      host.Arm(waitSeconds)
    end
  end
  local waitGen = Civ5Ai_Bridge._inboxWaitGen[playerID] or 0
  local lastLog = nil
  local lastPoll = nil
  local started = nil
  if os and os.clock then
    started = os.clock()
  end
  -- Sidecar writes the session JSON mailbox. ApplyPayload sends it on the net.
  -- Seat turn cap is the only timeout. Responsive wait polls disk sparingly.
  Civ5Ai_Util.ScheduleTick(function()
    if Civ5Ai_Bridge._InboxWaitStale(playerID, waitGen) then
      return false
    end
    local gameTurn = tonumber(Civ5Ai_Bridge._GameTurn())
    local dumpTurn = tonumber(Civ5Ai_Bridge._ExpectedApplyTurn(playerID))
    if dumpTurn ~= nil and gameTurn ~= nil and dumpTurn ~= gameTurn then
      Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
      Civ5Ai_Util.Log(
        "bridge|stale_wait_new_turn|player="
          .. tostring(playerID)
          .. "|dump="
          .. tostring(dumpTurn)
          .. "|game="
          .. tostring(gameTurn)
      )
      Civ5Ai_Bridge.RequestTurnPulse(playerID)
      return false
    end
    if os and os.clock then
      local now = os.clock()
      -- FPS: while waiting on sidecar, do not ReadTextFile mailboxes every pump.
      local interval = responsive and 1.0 or 0.5
      if lastPoll == nil or (now - lastPoll) >= interval then
        lastPoll = now
        Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
      end
    else
      Civ5Ai_Bridge._TryApplyFromMailbox(playerID)
    end
    if Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
      if Civ5Ai_Bridge._WasEmptyAppliedThisPulse(playerID) then
        -- Grace: allow a late non-empty mailbox to replace empty before finish.
        Civ5Ai_Bridge._emptyApplyAt = Civ5Ai_Bridge._emptyApplyAt or {}
        if Civ5Ai_Bridge._emptyApplyAt[playerID] == nil and os and os.clock then
          Civ5Ai_Bridge._emptyApplyAt[playerID] = os.clock()
          Civ5Ai_Util.Log(
            "bridge|empty_apply_grace|player="
              .. tostring(playerID)
              .. "|seconds=45"
          )
        end
        local emptyAt = Civ5Ai_Bridge._emptyApplyAt[playerID]
        local grace = 45
        if emptyAt ~= nil and os and os.clock and (os.clock() - emptyAt) < grace then
          return true
        end
        Civ5Ai_Bridge._emptyApplyAt[playerID] = nil
        Civ5Ai_Util.Log("bridge|empty_apply_grace_done|player=" .. tostring(playerID))
      end
      Civ5Ai_Bridge._inboxWaitActive[playerID] = nil
      Civ5Ai_Util.Log("bridge|inbox_apply_done|player=" .. tostring(playerID))
      if not Civ5Ai_Bridge._WasPulseFinished(playerID) then
        Civ5Ai_Bridge.FinishSeat(playerID)
      end
      return false
    end
    if started ~= nil and os and os.clock then
      local elapsed = os.clock() - started
      if lastLog == nil or (elapsed - lastLog) >= 5 then
        lastLog = elapsed
        local tag = responsive and "responsive_wait" or "inbox_wait"
        Civ5Ai_Util.Log(
          "bridge|" .. tag .. "|player=" .. tostring(playerID) .. "|elapsed=" .. tostring(math.floor(elapsed))
        )
      end
    end
    return true
  end)
end

function Civ5Ai_Bridge.RunTurnPulse(playerID)
  if not Civ5Ai_Bridge._IsGameplayReady(playerID) then
    Civ5Ai_Util.Log("bridge|not_ready|player=" .. tostring(playerID))
    Civ5Ai_Bridge._SchedulePulseRetry(playerID)
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  if not Civ5Ai_Bridge._CanStartAutotestPulse(playerID) then
    Civ5Ai_Bridge._SchedulePulseRetry(playerID)
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  -- Durable gate: if this turn already applied on disk, never re-dump snapshot /
  -- re-wait LLM while EnsureFinishSeat is blocked (e.g. PRODUCTION chooser).
  do
    local turn = Civ5Ai_Bridge._GameTurn()
    local appliedPath = Civ5Ai_Util.JoinPath(
      Civ5Ai_Bridge._PlayerDir(playerID),
      "t" .. tostring(turn) .. "_seat_applied.txt"
    )
    local appliedText = Civ5Ai_Util.ReadTextFile(appliedPath)
    if appliedText ~= nil and appliedText ~= "" then
      Civ5Ai_Util.Log(
        "bridge|skip_redump_already_applied|player="
          .. tostring(playerID)
          .. "|turn="
          .. tostring(turn)
      )
      if not Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
        Civ5Ai_Bridge._MarkApplied(playerID)
      end
      Civ5Ai_Bridge.EnsureFinishSeat(playerID)
      Civ5Ai_Bridge._ReleasePulseSlot(playerID)
      return
    end
  end
  if Civ5Ai_Bridge._AlreadyPulsed(playerID) then
    if Civ5Ai_Bridge._HasPendingDiplomacy(playerID) then
      Civ5Ai_Bridge._ClearPulse(playerID)
      Civ5Ai_Util.Log("bridge|diplomacy_repulse|player=" .. tostring(playerID))
    else
      Civ5Ai_Bridge._ReleasePulseSlot(playerID)
      return
    end
  end
  if Civ5Ai_Config.IsAutotest() and Civ5Ai_Config.IsFastEndTurn() then
    if not Civ5Ai_Bridge._MarkPulse(playerID) then
      Civ5Ai_Util.Log("bridge|skip_duplicate_pulse|player=" .. tostring(playerID))
      Civ5Ai_Bridge._ReleasePulseSlot(playerID)
      return
    end
    Civ5Ai_Util.Log("bridge|fast_end_turn_skip|player=" .. tostring(playerID))
    Civ5Ai_Bridge.FinishSeat(playerID)
    return
  end
  if not Civ5Ai_Config.ShouldRunBridge(playerID) then
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  Civ5Ai_Bridge._BumpInboxWaitGen(playerID)
  if not Civ5Ai_Bridge._MarkPulse(playerID) then
    Civ5Ai_Util.Log("bridge|skip_duplicate_pulse|player=" .. tostring(playerID))
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  Civ5Ai_Bridge._HoldNativeAi(playerID)
  Civ5Ai_Bridge._SetPulseStep(playerID, 1)
  Civ5Ai_Bridge._LogStep(
    playerID,
    "1_gather",
    "in",
    "player="
      .. tostring(playerID)
      .. "\nreason="
      .. (Civ5Ai_Bridge._HasPendingDiplomacy(playerID) and "diplomacy_request" or "turn_start")
      .. "\nsession="
      .. tostring(Civ5Ai_Bridge.SessionId())
  )
  local snapshotJson = nil
  local pulseReason = Civ5Ai_Bridge._HasPendingDiplomacy(playerID) and "diplomacy_request" or "turn_start"
  local buildOk, buildErr = pcall(function()
    snapshotJson = Civ5Ai_Snapshot.Build(playerID, { reason = pulseReason })
  end)
  if not buildOk then
    Civ5Ai_Bridge._LogStep(playerID, "1_gather", "out", "snapshot_error|" .. tostring(buildErr))
    Civ5Ai_Bridge._ApplyEmptyThenFinish(playerID, "snapshot_error")
    return
  end
  if snapshotJson == nil then
    Civ5Ai_Bridge._LogStep(playerID, "1_gather", "out", "snapshot_failed")
    Civ5Ai_Bridge._ApplyEmptyThenFinish(playerID, "snapshot_failed")
    return
  end
  Civ5Ai_Bridge._LogStep(playerID, "1_gather", "out", snapshotJson)
  local playerDir = Civ5Ai_Bridge._PlayerDir(playerID)
  local snapshotPath = Civ5Ai_Util.JoinPath(playerDir, "snapshot.json")
  Civ5Ai_Bridge._SetPulseStep(playerID, 2)
  local wroteFile = false
  local writeOk, writeErr = pcall(function()
    wroteFile = Civ5Ai_Util.WriteTextFile(snapshotPath, snapshotJson)
  end)
  if not writeOk then
    Civ5Ai_Bridge._LogStep(playerID, "2_prompt", "out", "snapshot_write_error|" .. tostring(writeErr))
    wroteFile = false
  end
  if wroteFile then
    Civ5Ai_Bridge._LogStep(
      playerID,
      "2_prompt",
      "in",
      "snapshot_path=" .. tostring(snapshotPath)
    )
    Civ5Ai_Bridge._SetPulseStep(playerID, 3)
    Civ5Ai_Bridge._LogStep(
      playerID,
      "3_llm",
      "in",
      "waiting_host_sidecar\nsnapshot=" .. tostring(snapshotPath)
    )
    Civ5Ai_Util.Log("bridge|dump_wait_apply|player=" .. tostring(playerID) .. "|file")
    Civ5Ai_Bridge._ScheduleInboxApplyWait(playerID)
    return
  end
  Civ5Ai_Util.Log("bridge|snapshot_write_failed|player=" .. tostring(playerID))
  Civ5Ai_Bridge._ApplyEmptyThenFinish(playerID, "snapshot_write_failed")
end


-- Bind in whatever VM included this file (InGame and HostInbox).
Civ5Ai_Bridge._BindGameCoreUpdateEnd()
