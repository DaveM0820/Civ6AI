-- Civ6Ai autotest: auto end-turn, session lifecycle, autotest.log.
Civ6Ai_Autotest = Civ6Ai_Autotest or {}

Civ6Ai_Autotest._stopped = false

function Civ6Ai_Autotest.Initialize()
  Civ6Ai_Autotest.StartStallWatchdog()
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._EnsureSessionId()
  Civ6Ai_Util.Log("autotest|enabled|stop_turn=" .. tostring(Civ6Ai_Autotest.StopTurn()))
  if Events ~= nil then
    if Events.TechBoostTriggered ~= nil then
      Events.TechBoostTriggered.Add(Civ6Ai_Autotest._OnBoostTriggered)
    end
    if Events.CivicBoostTriggered ~= nil then
      Events.CivicBoostTriggered.Add(Civ6Ai_Autotest._OnBoostTriggered)
    end
    if Events.CityAddedToMap ~= nil then
      Events.CityAddedToMap.Add(Civ6Ai_Autotest._OnCityAddedToMap)
    end
    if Events.LoadScreenClose ~= nil then
      Events.LoadScreenClose.Add(Civ6Ai_Autotest._DisableBoostPopups)
    end
    if Events.DiplomacyStatement ~= nil then
      Events.DiplomacyStatement.Add(Civ6Ai_Autotest._OnDiplomacyStatement)
    end
    for _, ev in ipairs({ Events.WorldCongressStage1, Events.WorldCongressStage2 }) do
      ev.Add(Civ6Ai_Autotest._OnWorldCongress)
    end
  end
  Civ6Ai_Autotest._DisableBoostPopups()
end

function Civ6Ai_Autotest._AutotestDir()
  local root = Civ6Ai_Config.RootDir()
  if root ~= nil and root ~= "" then
    return Civ6Ai_Util.JoinPath(root, "autotest")
  end
  local logDir = Civ6Ai_Util.LogDir()
  if logDir ~= nil and logDir ~= "" then
    return Civ6Ai_Util.JoinPath(logDir, "civ6ai/autotest")
  end
  return "autotest"
end

function Civ6Ai_Autotest._LogLine(text)
  Civ6Ai_Util.Log("autotest|" .. text)
end

function Civ6Ai_Autotest._EnsureSessionId()
  local configured = ""
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.SessionId ~= nil then
    configured = Civ6Ai_Config.SessionId()
  end
  if configured ~= nil and configured ~= "" then
    Civ6Ai_Bridge.SetSessionId(configured)
    Civ6Ai_Util.Log("autotest|session_id=" .. configured)
    Civ6Ai_Autotest._LogLine("session_id=" .. configured)
    return
  end
  local sid = Civ6Ai_Bridge.SessionId()
  if sid == nil or sid == "" or sid == "default" then
    local newId = "autotest"
    if os and os.time then
      newId = "autotest-" .. tostring(os.time())
    end
    Civ6Ai_Bridge.SetSessionId(newId)
    Civ6Ai_Autotest._LogLine("session_id=" .. newId)
  end
end

function Civ6Ai_Autotest.StopTurn()
  return Civ6Ai_Config.AutotestStopTurn()
end

function Civ6Ai_Autotest.AfterPulse(playerID)
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  if Civ6Ai_Autotest._stopped then
    -- Resume when AutotestStopTurn was raised after a prior stop (no full restart).
    if Game.GetCurrentGameTurn() < Civ6Ai_Autotest.StopTurn() then
      Civ6Ai_Autotest._stopped = false
      Civ6Ai_Util.Log("autotest|resume|turn=" .. tostring(Game.GetCurrentGameTurn())
        .. "|stop_turn=" .. tostring(Civ6Ai_Autotest.StopTurn()))
    else
      -- Still clear research/civic (and other) blockers so CHOOSE CIVIC/RESEARCH
      -- cannot soft-lock the host after stop_turn.
      Civ6Ai_Autotest._CloseQueuedPopups()
      Civ6Ai_Autotest._DismissBlockers(playerID)
      return
    end
  end
  local turn = Game.GetCurrentGameTurn()
  Civ6Ai_Autotest._LogLine("pulse|turn=" .. tostring(turn) .. "|player=" .. tostring(playerID))
  -- Blocker clearing is best effort: an error in it must not skip the seat
  -- snapshots and the end turn below (that stalled the host on turn 1).
  local okBlockers, blockersErr = pcall(function()
    Civ6Ai_Autotest._DisableBoostPopups()
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
  end)
  if not okBlockers then
    Civ6Ai_Util.Log("autotest|dismiss_blockers_error|player=" .. tostring(playerID)
      .. "|turn=" .. tostring(turn) .. "|err=" .. tostring(blockersErr))
  end
  -- Ending the turn is what the diplomacy ribbon uses to drop a portrait
  -- (RemotePlayerTurnEnd / IsTurnActive). Humans wait until every AI seat's
  -- answer is in. AI seats end once their pulse is done (old timing) or once
  -- their queue ran at their turn start (same-turn timing), the same request
  -- the human uses, so their portrait shows completed.
  local p = Players[playerID]
  if p ~= nil and p:IsHuman() then
    -- host_end: the host's own orders are applied now, so snapshot every
    -- managed AI seat from this state before the barrier waits for them.
    Civ6Ai_Bridge.PrepulseSeats("host_end")
    Civ6Ai_Autotest._EndTurnAfterSeats(playerID)
  elseif p ~= nil and not (Civ6Ai_Apply._IsNetworkMultiplayer ~= nil and Civ6Ai_Apply._IsNetworkMultiplayer()) then
    Civ6Ai_Autotest._EndManagedTurn(playerID)
  end
  if turn >= Civ6Ai_Autotest.StopTurn() then
    Civ6Ai_Autotest._WriteSessionSummary()
    Civ6Ai_Autotest._stopped = true
    Civ6Ai_Autotest._LogLine("stop|turn=" .. tostring(turn))
  end
end

-- Seat-timing barrier (docs/REAL_TEST.md "Seat timing").
-- Same-turn timing (autotest default, seat_snapshot_at host_end/turn_start):
-- every managed AI seat is snapshotted during the local seat's turn N
-- (Civ6Ai_Bridge.PrepulseSeats) and its answer is sent for the seat's next turn
-- start (single player: its turn N, which starts after the local seat ends N;
-- LAN: N+1). The local seat holds its end-turn until every AI seat's turn N
-- answer has been sent (or given up on); otherwise the seat's turn would start
-- without it and the native AI would play the seat. Bounded by a wall-clock
-- deadline of sidecar timeout x (pending seats + 1).
-- Old sequential SP timing (no same-turn): hold until every AI seat's turn N-1
-- snapshot has an answer (Civ6Ai_Bridge.HostWaitSnapshotTurn).
function Civ6Ai_Autotest._PendingSeats(localPlayer)
  local pending = {}
  local snapshotTurn = Civ6Ai_Bridge.HostWaitSnapshotTurn()
  if snapshotTurn < 1 then
    return pending
  end
  for _, seat in ipairs(Civ6Ai_Config.ManagedSeatsList()) do
    if seat ~= localPlayer and Civ6Ai_Config.ShouldRunBridge(seat)
        and Civ6Ai_Bridge.SeatAnswerOutstanding(seat, snapshotTurn) then
      table.insert(pending, seat)
    end
  end
  return pending
end

function Civ6Ai_Autotest._EndTurnAfterSeats(playerID)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(playerID) .. "|" .. tostring(turn)
  Civ6Ai_Autotest._barrierKeys = Civ6Ai_Autotest._barrierKeys or {}
  if Civ6Ai_Autotest._barrierKeys[key] then
    return
  end
  Civ6Ai_Autotest._barrierKeys[key] = true
  local pending = Civ6Ai_Autotest._PendingSeats(playerID)
  if #pending == 0 then
    Civ6Ai_Autotest._EndManagedTurn(playerID)
    return
  end
  local started = Civ6Ai_Bridge._WallClock()
  local waitSeconds = Civ6Ai_Config.SidecarTimeout() * (#pending + 1)
  local deadline = started ~= nil and (started + waitSeconds) or nil
  local line = "seat_barrier_wait|turn=" .. tostring(turn) .. "|player=" .. tostring(playerID)
    .. "|pending=" .. table.concat(pending, ",") .. "|max_wait=" .. tostring(waitSeconds)
  Civ6Ai_Util.Log("autotest|" .. line)
  Civ6Ai_Autotest._LogLine(line)
  local attempts = 0
  local lastCheck = nil
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Game.GetCurrentGameTurn() ~= turn then
      Civ6Ai_Util.Log("autotest|seat_barrier_abandoned|turn=" .. tostring(turn) .. "|reason=turn_advanced")
      return false
    end
    local now = Civ6Ai_Bridge._WallClock()
    if now ~= nil then
      if now == lastCheck then
        return true
      end
      lastCheck = now
    elseif attempts % 30 ~= 0 then
      return true
    end
    local still = Civ6Ai_Autotest._PendingSeats(playerID)
    local expired = (deadline ~= nil and now ~= nil and now >= deadline) or (deadline == nil and attempts >= 60000)
    if #still == 0 or expired then
      local done = "seat_barrier_done|turn=" .. tostring(turn)
        .. "|waited=" .. tostring((now ~= nil and started ~= nil) and (now - started) or attempts)
        .. "|timed_out=" .. tostring(#still > 0) .. "|pending=" .. table.concat(still, ",")
      Civ6Ai_Util.Log("autotest|" .. done)
      Civ6Ai_Autotest._LogLine(done)
      Civ6Ai_Autotest._EndManagedTurn(playerID)
      return false
    end
    return true
  end)
end

-- World Congress: close its screens and submit the local seat's turn as the
-- native popup does when it has no choices (synced player operation; the
-- seat casts no votes). AI seats vote natively.
function Civ6Ai_Autotest._OnWorldCongress()
  local ticks = 0
  Civ6Ai_Util.ScheduleTick(function()
    ticks = ticks + 1
    if ticks < 30 then
      return true
    end
    Civ6Ai_Autotest._CloseQueuedPopups()
    local me = Game.GetLocalPlayer()
    local ok = pcall(UI.RequestPlayerOperation, me, PlayerOperations.WORLD_CONGRESS_SUBMIT_TURN, {})
    Civ6Ai_Util.Log("autotest|world_congress_submit|player=" .. tostring(me) .. "|ok=" .. tostring(ok))
    return false
  end)
end

function Civ6Ai_Autotest._DisableBoostPopups()
  if LuaEvents ~= nil and LuaEvents.TutorialUIRoot_DisableTechAndCivicPopups ~= nil then
    LuaEvents.TutorialUIRoot_DisableTechAndCivicPopups()
  end
end

function Civ6Ai_Autotest._CloseQueuedPopups()
  if ContextPtr == nil or UIManager == nil or UIManager.DequeuePopup == nil then
    return
  end
  local names = {
    "BoostUnlockedPopup",
    "TechCivicCompletedPopup",
    "CityNamePopup",
    "ChooseCityNamePopup",
    "CityRenamePopup",
    "InGamePopup",
    "GenericPopup",
    "PopupDialog",
    -- Expansion popups; HistoricMoments held P0's end turn for 25+ min on turn 10.
    -- Engine-locking popups (ExclusivePopupManager: NaturalDisaster, NaturalWonder,
    -- WonderBuilt, ProjectBuilt, EraComplete, CreateCorporation) are NOT listed:
    -- dequeuing them hides the screen but keeps the engine event lock and the
    -- BulkHide, which froze T28. Civ6Ai_ExclusivePopup closes them natively.
    "HistoricMoments",
    "EraReviewPopup",
    "DedicationPopup",
    "WorldCrisisPopup",
    "WorldCongressIntro",
    "WorldCongressPopup",
    "WorldCongressBetweenTurns",
    -- Research/civic chooser panels (CHOOSE RESEARCH / CHOOSE CIVIC).
    "ResearchChooser",
    "CivicsChooser",
    "ProductionPanel",
    -- Government / Change Policies (FILL_CIVIC_SLOT / CONSIDER_GOVERNMENT_CHANGE).
    "GovernmentScreen",
  }
  local closed = 0
  for _, name in ipairs(names) do
    local control = ContextPtr:LookUpControl("/InGame/" .. name)
    if control ~= nil then
      local hidden = true
      if control.IsHidden ~= nil then
        hidden = control:IsHidden()
      end
      if not hidden then
        pcall(function() UIManager:DequeuePopup(control) end)
        closed = closed + 1
      end
    end
  end
  if LuaEvents ~= nil and LuaEvents.TechCivicCompletedPopup_Closed ~= nil then
    pcall(function() LuaEvents.TechCivicCompletedPopup_Closed() end)
  end
  if closed > 0 then
    Civ6Ai_Autotest._LogLine("popups_closed|count=" .. tostring(closed))
    Civ6Ai_Util.Log("autotest|popups_closed|count=" .. tostring(closed))
  end
end

-- Leader screens (first meeting, greetings, warnings, denouncements, war
-- declarations) wait for a click and ignore posted Enter keys, so autotest
-- answers them through DiplomacyManager, the same calls the screen's buttons
-- make. Deal proposals are left to the deal flow.
Civ6Ai_Autotest.DIPLO_KEEP = { MAKE_DEAL = true }

function Civ6Ai_Autotest._OnDiplomacyStatement(fromPlayer, toPlayer, kVariants)
  if not Civ6Ai_Config.IsAutotest() or DiplomacyManager == nil or kVariants == nil then
    return
  end
  local localPlayer = Game.GetLocalPlayer()
  if toPlayer ~= localPlayer or fromPlayer == localPlayer then
    return
  end
  local sessionID = kVariants.SessionID
  local typeName = ""
  pcall(function() typeName = DiplomacyManager.GetKeyName(kVariants.StatementType) or "" end)
  if Civ6Ai_Autotest.DIPLO_KEEP[typeName] then
    Civ6Ai_Util.Log("autotest|diplo_left_open|type=" .. tostring(typeName) .. "|from=" .. tostring(fromPlayer))
    return
  end
  local ticks = 0
  Civ6Ai_Util.ScheduleTick(function()
    ticks = ticks + 1
    -- Let the leader screen open first so it sees the close and tears down cleanly.
    if ticks < 15 then
      return true
    end
    local okResp = pcall(function() DiplomacyManager.AddResponse(sessionID, localPlayer, "POSITIVE") end)
    local stillOpen = true
    if DiplomacyManager.FindOpenSessionID ~= nil then
      pcall(function() stillOpen = DiplomacyManager.FindOpenSessionID(fromPlayer, localPlayer) == sessionID end)
    end
    if stillOpen then
      pcall(function() DiplomacyManager.CloseSession(sessionID) end)
    end
    Civ6Ai_Util.Log("autotest|diplo_auto_answer|type=" .. tostring(typeName) .. "|from=" .. tostring(fromPlayer)
      .. "|response=" .. tostring(okResp) .. "|closed=" .. tostring(stillOpen))
    return false
  end)
end

function Civ6Ai_Autotest._OnBoostTriggered()
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._DisableBoostPopups()
  Civ6Ai_Util.ScheduleTick(function()
    Civ6Ai_Autotest._CloseQueuedPopups()
    return false
  end)
end

function Civ6Ai_Autotest._DismissCityNamePopups()
  if ContextPtr == nil then
    return 0
  end
  local names = {
    "CityNamePopup",
    "ChooseCityNamePopup",
    "CityRenamePopup",
    "NewCityPopup",
    "PopupDialog",
    "GenericPopup",
  }
  local prefixes = {
    "/InGame/",
    "/InGame/Popups/",
    "/InGame/WorldView/",
  }
  local closed = 0
  for _, prefix in ipairs(prefixes) do
    for _, name in ipairs(names) do
      local control = ContextPtr:LookUpControl(prefix .. name)
      if control ~= nil then
        local hidden = true
        if control.IsHidden ~= nil then
          hidden = control:IsHidden()
        end
        if not hidden then
          if UIManager ~= nil and UIManager.DequeuePopup ~= nil then
            pcall(function() UIManager:DequeuePopup(control) end)
          end
          if control.SetHide ~= nil then
            pcall(function() control:SetHide(true) end)
          end
          closed = closed + 1
        end
      end
    end
  end
  if closed > 0 then
    Civ6Ai_Autotest._LogLine("city_name_popups_closed|count=" .. tostring(closed))
    Civ6Ai_Util.Log("autotest|city_name_popups_closed|count=" .. tostring(closed))
  end
  return closed
end

function Civ6Ai_Autotest._OnCityAddedToMap(playerID, cityID, x, y)
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._OnBoostTriggered()
  Civ6Ai_Util.ScheduleTick(function()
    Civ6Ai_Autotest._DismissCityNamePopups()
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._NudgeEnter(playerID or Game.GetLocalPlayer())
    return false
  end)
end

-- Auto-pick a researchable tech when ENDTURN_BLOCKING_RESEARCH would show
-- CHOOSE RESEARCH (same idea as dismissing other autotest popups).
function Civ6Ai_Autotest._PickFallbackTech(playerID)
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetTechs == nil or GameInfo == nil or GameInfo.Technologies == nil then
    return nil
  end
  local techs = player:GetTechs()
  if techs == nil then
    return nil
  end
  local cur = nil
  pcall(function() cur = techs:GetResearchingTech() end)
  if cur ~= nil and cur >= 0 then
    return nil
  end
  for row in GameInfo.Technologies() do
    local ok, can = pcall(function()
      return techs:CanResearch(row.Index) and not techs:HasTech(row.Index)
    end)
    if ok and can then
      return row.TechnologyType
    end
  end
  return nil
end

-- Auto-pick a progressable civic when ENDTURN_BLOCKING_CIVIC would show CHOOSE CIVIC.
function Civ6Ai_Autotest._PickFallbackCivic(playerID)
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetCulture == nil or GameInfo == nil or GameInfo.Civics == nil then
    return nil
  end
  local culture = player:GetCulture()
  if culture == nil then
    return nil
  end
  local cur = nil
  pcall(function() cur = culture:GetProgressingCivic() end)
  if cur ~= nil and cur >= 0 then
    local done = false
    pcall(function()
      done = culture.CivicCompletedThisTurn ~= nil and culture:CivicCompletedThisTurn() == true
    end)
    if not done then
      return nil
    end
  end
  for row in GameInfo.Civics() do
    local ok, can = pcall(function()
      return culture:CanProgress(row.Index) and not culture:HasCivic(row.Index)
    end)
    if ok and can then
      return row.CivicType
    end
  end
  return nil
end

-- The local seat's UI research call does nothing in network games (logged
-- research_rejected every time); send the fallback pick on the synced channel, once per turn.
Civ6Ai_Autotest._autoSent = Civ6Ai_Autotest._autoSent or {}
function Civ6Ai_Autotest._SetFallback(playerID, kind, args, direct)
  local local_ = Game ~= nil and Game.GetLocalPlayer ~= nil and playerID == Game.GetLocalPlayer()
  if local_ and Civ6Ai_OrderChannel ~= nil and Civ6Ai_OrderChannel.SendDecision ~= nil
      and Civ6Ai_Apply._IsNetworkMultiplayer ~= nil and Civ6Ai_Apply._IsNetworkMultiplayer() then
    local turn = Game.GetCurrentGameTurn()
    local id = tostring(args.tech_id or args.civic_id)
    local key = tostring(playerID) .. "|" .. kind .. "|" .. id .. "|" .. tostring(turn)
    if Civ6Ai_Autotest._autoSent[key] then
      return true, "already_sent"
    end
    Civ6Ai_Autotest._autoSent[key] = true
    local n = Civ6Ai_OrderChannel.SendDecision(playerID, { commands = { {
      kind = kind, command_id = "CMD_auto_" .. id, arguments = args } } }, turn, turn)
    return n > 0, n > 0 and "sent_synced" or "send_failed"
  end
  return direct(playerID, args)
end

function Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)
  if Civ6Ai_Apply == nil then
    return
  end
  local techId = Civ6Ai_Autotest._PickFallbackTech(playerID)
  if techId ~= nil and Civ6Ai_Apply._SetResearchTech ~= nil then
    local ok, reason = Civ6Ai_Autotest._SetFallback(playerID, "set_research_tech", { tech_id = techId }, Civ6Ai_Apply._SetResearchTech)
    Civ6Ai_Autotest._LogLine(
      "auto_research|player=" .. tostring(playerID)
      .. "|tech=" .. tostring(techId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_research|player=" .. tostring(playerID)
      .. "|tech=" .. tostring(techId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
  end
  local civicId = Civ6Ai_Autotest._PickFallbackCivic(playerID)
  if civicId ~= nil and Civ6Ai_Apply._SetResearchCivic ~= nil then
    local ok, reason = Civ6Ai_Autotest._SetFallback(playerID, "set_research_civic", { civic_id = civicId }, Civ6Ai_Apply._SetResearchCivic)
    Civ6Ai_Autotest._LogLine(
      "auto_civic|player=" .. tostring(playerID)
      .. "|civic=" .. tostring(civicId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_civic|player=" .. tostring(playerID)
      .. "|civic=" .. tostring(civicId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
  end
end

function Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  -- Empty queues only (never a model or human choice), once per city per turn.
  if Civ6Ai_Production ~= nil and Civ6Ai_Production.FillEmptyQueuesWeighted ~= nil then
    pcall(Civ6Ai_Production.FillEmptyQueuesWeighted, playerID)
  end
end

-- Auto-fill empty policy slots when FILL_CIVIC_SLOT would leave Change Policies up.
-- Bare notification dismiss does not Confirm policies, so NEXT TURN stays blocked.
-- Government is never chosen here. A negative current government (anarchy, or the
-- chooser opening when anarchy ends) is not "no government": confirming one for it
-- starts another anarchy and yields stay at 0.
local function _policySlotFits(slotType, policyRow)
  local cardType = policyRow ~= nil and policyRow.GovernmentSlotType or nil
  if slotType == cardType or slotType == "SLOT_WILDCARD" then
    return true
  end
  return false
end

function Civ6Ai_Autotest._BuildFallbackPolicySlots(playerID)
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetCulture == nil or GameInfo == nil or GameInfo.Policies == nil then
    return nil, "no_culture"
  end
  local culture = player:GetCulture()
  if culture == nil then
    return nil, "no_culture"
  end
  local made = false
  pcall(function() made = culture:PolicyChangeMade() == true end)
  if made then
    return nil, "already_changed"
  end
  local civicDone, openSlots = false, 0
  pcall(function() civicDone = culture:CivicCompletedThisTurn() == true end)
  pcall(function() openSlots = culture:GetNumPolicySlotsOpen() or 0 end)
  if not civicDone and openSlots <= 0 then
    return nil, "change_not_allowed"
  end
  local n = 0
  pcall(function() n = culture:GetNumPolicySlots() or 0 end)
  if n <= 0 then
    return nil, "no_slots"
  end
  local used = {}
  local parts = {}
  local filledEmpty = 0
  for i = 0, n - 1 do
    local st, pid = nil, nil
    pcall(function() st = culture:GetSlotType(i) end)
    pcall(function() pid = culture:GetSlotPolicy(i) end)
    local srow = st ~= nil and GameInfo.GovernmentSlots ~= nil and GameInfo.GovernmentSlots[st] or nil
    local slotType = srow ~= nil and srow.GovernmentSlotType or "SLOT_UNKNOWN"
    local policyId = nil
    if pid ~= nil and pid >= 0 and GameInfo.Policies[pid] ~= nil then
      policyId = GameInfo.Policies[pid].PolicyType
      used[policyId] = true
    else
      for row in GameInfo.Policies() do
        local ok, avail = pcall(function()
          local unlocked = culture:IsPolicyUnlocked(row.Hash) == true
            or culture:IsPolicyUnlocked(row.Index) == true
          local obsolete = culture.IsPolicyObsolete ~= nil and culture:IsPolicyObsolete(row.Hash) == true
          return unlocked and not obsolete and _policySlotFits(slotType, row)
            and used[row.PolicyType] ~= true
        end)
        if ok and avail then
          policyId = row.PolicyType
          used[policyId] = true
          filledEmpty = filledEmpty + 1
          break
        end
      end
      if policyId == nil then
        policyId = "NONE"
      end
    end
    parts[#parts + 1] = tostring(i) .. "=" .. tostring(policyId)
  end
  -- GovernmentScreen Confirm stays disabled while any slot is free; do not
  -- submit a plan that still has NONE in an open slot.
  for _, part in ipairs(parts) do
    if string.match(part, "=%s*NONE%s*$") and openSlots > 0 then
      return nil, "unfilled_slots"
    end
  end
  return table.concat(parts, ";"), nil
end

function Civ6Ai_Autotest._ClearPolicyGovernmentBlockers(playerID)
  local localPlayer = Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() or nil
  -- GovernmentScreen / RequestPolicyChanges are local-seat UI routes (same as production).
  if localPlayer == nil or playerID ~= localPlayer then
    return
  end
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetCulture == nil then
    return
  end
  local culture = player:GetCulture()
  if culture == nil then
    return
  end
  local slots, why = Civ6Ai_Autotest._BuildFallbackPolicySlots(playerID)
  if slots == nil then
    if why ~= nil and why ~= "already_changed" and why ~= "change_not_allowed" then
      Civ6Ai_Autotest._LogLine(
        "auto_policies|player=" .. tostring(playerID) .. "|skip=" .. tostring(why))
    end
    return
  end
  local ok, reason = false, "no_apply"
  if Civ6Ai_Apply ~= nil and Civ6Ai_Apply._SetPolicies ~= nil then
    ok, reason = Civ6Ai_Apply._SetPolicies(
      playerID,
      { kind = "set_policies", id = "autotest_fallback" },
      { slots = slots })
    if ok == Civ6Ai_Apply.DEFERRED then
      ok = true
      reason = reason or "deferred"
    end
  else
    -- Direct fallback mirroring GovernmentScreen ConfirmPolicies.
    local plan = {}
    for part in string.gmatch(slots, "[^;]+") do
      local slot, policy = string.match(part, "^(%d+)=([%w_]+)$")
      if slot ~= nil then
        plan[#plan + 1] = { slot = tonumber(slot), policy = policy }
      end
    end
    local clearList, addList = {}, {}
    for _, e in ipairs(plan) do
      table.insert(clearList, e.slot)
      if string.upper(e.policy) ~= "NONE" then
        local prow = GameInfo.Policies[e.policy]
        if prow ~= nil and Civ6Ai_Apply ~= nil and Civ6Ai_Apply._PolicyTypeHash ~= nil then
          addList[e.slot] = Civ6Ai_Apply._PolicyTypeHash(prow)
        elseif prow ~= nil then
          addList[e.slot] = prow.Hash
        end
      end
    end
    local okCall, okReq = pcall(function()
      return culture:RequestPolicyChanges(clearList, addList)
    end)
    ok = okCall and okReq ~= false
    reason = ok and "" or tostring(okReq)
  end
  Civ6Ai_Autotest._LogLine(
    "auto_policies|player=" .. tostring(playerID)
    .. "|slots=" .. tostring(slots) .. "|ok=" .. tostring(ok)
    .. "|reason=" .. tostring(reason or ""))
  Civ6Ai_Util.Log(
    "autotest|auto_policies|player=" .. tostring(playerID)
    .. "|slots=" .. tostring(slots) .. "|ok=" .. tostring(ok)
    .. "|reason=" .. tostring(reason or ""))
end


-- Names used by the dispatch table. Keys are suffixes of EndTurnBlockingTypes
-- (ENDTURN_BLOCKING_<NAME>) from base ActionPanel.lua. Looked up at runtime;
-- missing types log blocker_unhandled and get one Activate/Dismiss.
Civ6Ai_Autotest.BLOCKER_HANDLERS = {
  RESEARCH = function(playerID)
    Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)
  end,
  CIVIC = function(playerID)
    Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)
  end,
  PRODUCTION = function(playerID)
    Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  end,
  CITIES = function(playerID)
    Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  end,
  FILL_CIVIC_SLOT = function(playerID)
    Civ6Ai_Autotest._ClearPolicyGovernmentBlockers(playerID)
  end,
  -- Close the chooser. Do not confirm a government; that restarts anarchy.
  CONSIDER_GOVERNMENT_CHANGE = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  UNITS = function(playerID)
    Civ6Ai_Autotest._SkipUnitMovesEscalating(playerID)
  end,
  UNIT_NEEDS_ORDERS = function(playerID)
    Civ6Ai_Autotest._SkipUnitMovesEscalating(playerID)
  end,
  STACKED_UNITS = function(playerID)
    Civ6Ai_Autotest._SkipUnitMovesEscalating(playerID)
  end,
  PANTHEON = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  FOUND_PANTHEON = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  RELIGION = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  BELIEFS = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  FOUND_RELIGION = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  CHOOSE_RELIGION = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  GOVERNOR = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  PROMOTION = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  ENVOYS = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  GIVE_INFLUENCE_TOKEN = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  GREAT_PERSON = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  SPIES = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
  CONSIDER_GOLDEN_AGE_DEDICATION = function()
    Civ6Ai_Autotest._CloseQueuedPopups()
  end,
}

function Civ6Ai_Autotest._BlockingTypeName(blocking)
  if blocking == nil or blocking == 0 then
    return "NONE"
  end
  local t = EndTurnBlockingTypes
  if type(t) == "table" then
    for key, value in pairs(t) do
      if value == blocking then
        local name = string.match(tostring(key), "ENDTURN_BLOCKING_(.+)$")
        return name or tostring(key)
      end
    end
  end
  return "unknown:" .. tostring(blocking)
end

function Civ6Ai_Autotest._FirstBlockingType(playerID)
  if UI ~= nil and UI.GetEndTurnBlockingType ~= nil then
    local ok, value = pcall(function() return UI.GetEndTurnBlockingType() end)
    if ok and value ~= nil and value ~= 0 then
      return value
    end
  end
  if NotificationManager == nil or NotificationManager.GetList == nil then
    return 0
  end
  local list = NotificationManager.GetList(playerID)
  if list == nil then
    return 0
  end
  for _, nid in ipairs(list) do
    local entry = NotificationManager.Find(playerID, nid)
    if entry ~= nil then
      local dismissed = false
      pcall(function() dismissed = entry:IsDismissed() == true end)
      if not dismissed and entry.GetEndTurnBlocking ~= nil then
        local blocking = nil
        pcall(function() blocking = entry:GetEndTurnBlocking() end)
        if blocking ~= nil and blocking ~= 0 then
          return blocking
        end
      end
    end
  end
  return 0
end

function Civ6Ai_Autotest._HandlerForBlocking(blocking)
  local name = Civ6Ai_Autotest._BlockingTypeName(blocking)
  return Civ6Ai_Autotest.BLOCKER_HANDLERS[name], name
end

function Civ6Ai_Autotest._SweepCommonBlockers(playerID)
  Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)
  Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  Civ6Ai_Autotest._ClearPolicyGovernmentBlockers(playerID)
end

function Civ6Ai_Autotest._ResolveEndTurnBlocking(playerID)
  local blocking = Civ6Ai_Autotest._FirstBlockingType(playerID)
  local handler, name = Civ6Ai_Autotest._HandlerForBlocking(blocking)
  if blocking == nil or blocking == 0 then
    Civ6Ai_Autotest._SweepCommonBlockers(playerID)
    return "NONE", true
  end
  if handler == nil then
    Civ6Ai_Util.Log("autotest|blocker_unhandled|type=" .. tostring(name)
      .. "|player=" .. tostring(playerID))
    Civ6Ai_Autotest._LogLine("blocker_unhandled|type=" .. tostring(name))
    Civ6Ai_Autotest._SweepCommonBlockers(playerID)
    return name, false
  end
  local ok, err = pcall(handler, playerID, blocking)
  if not ok then
    Civ6Ai_Util.Log("autotest|blocker_handler_error|type=" .. tostring(name)
      .. "|err=" .. tostring(err))
    return name, false
  end
  Civ6Ai_Util.Log("autotest|blocker_handled|type=" .. tostring(name)
    .. "|player=" .. tostring(playerID))
  return name, true
end

function Civ6Ai_Autotest._DismissBlockingNotifications(playerID)
  if NotificationManager == nil or NotificationManager.GetList == nil then
    return 0
  end
  local list = NotificationManager.GetList(playerID)
  if list == nil then
    return 0
  end
  local count = 0
  for _, nid in ipairs(list) do
    local entry = NotificationManager.Find(playerID, nid)
    if entry ~= nil then
      local dismissed = false
      pcall(function() dismissed = entry:IsDismissed() == true end)
      if not dismissed then
        local blocking = 0
        pcall(function() blocking = entry:GetEndTurnBlocking() end)
        if blocking ~= nil and blocking ~= 0 then
          pcall(function() NotificationManager.SendActivated(playerID, nid) end)
          pcall(function() NotificationManager.Dismiss(playerID, nid) end)
          count = count + 1
        end
      end
    end
  end
  return count
end

function Civ6Ai_Autotest._DismissBlockers(playerID)
  local ok, nameOrErr, handled = pcall(function()
    return Civ6Ai_Autotest._ResolveEndTurnBlocking(playerID)
  end)
  if not ok then
    Civ6Ai_Util.Log("autotest|resolve_blockers_error|player=" .. tostring(playerID)
      .. "|err=" .. tostring(nameOrErr))
  end
  local count = 0
  pcall(function() count = Civ6Ai_Autotest._DismissBlockingNotifications(playerID) end)
  if count > 0 then
    Civ6Ai_Autotest._LogLine("blockers|player=" .. tostring(playerID) .. "|count=" .. tostring(count)
      .. "|type=" .. tostring(ok and nameOrErr or ""))
  end
end

-- If the local turn has not advanced for STALL_SECONDS, clear blockers and
-- retry end turn. After STALL_MAX_ATTEMPTS, log stall| so the bridge can raise it.
Civ6Ai_Autotest.STALL_SECONDS = 240
Civ6Ai_Autotest.STALL_MAX_ATTEMPTS = 3

-- True while the same-turn barrier still needs AI answers. Ending the host
-- turn here would let the native AI play those seats before their queues land.
function Civ6Ai_Autotest._SameTurnWaitActive()
  if Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge.HostEndTurnWaiting ~= nil
      and Civ6Ai_Bridge.HostEndTurnWaiting() == true then
    return true
  end
  local playerID = Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() or nil
  if playerID ~= nil and Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge.LocalInboxWaiting ~= nil
      and Civ6Ai_Bridge.LocalInboxWaiting(playerID) then
    return true
  end
  if playerID == nil or Civ6Ai_Autotest._PendingSeats == nil then
    return false
  end
  if Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge.HostWaitSnapshotTurn == nil then
    return false
  end
  local pending = Civ6Ai_Autotest._PendingSeats(playerID)
  return type(pending) == "table" and #pending > 0
end

function Civ6Ai_Autotest.StartStallWatchdog()
  if Civ6Ai_Autotest._stallWatching then
    return
  end
  Civ6Ai_Autotest._stallWatching = true
  Civ6Ai_Autotest._stallTurn = nil
  Civ6Ai_Autotest._stallSince = nil
  Civ6Ai_Autotest._stallAttempts = 0
  local lastTickClock = nil
  Civ6Ai_Util.ScheduleTick(function()
    if Game == nil or Game.GetCurrentGameTurn == nil then
      return true
    end
    local turn = Game.GetCurrentGameTurn()
    local now = Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge._WallClock ~= nil and Civ6Ai_Bridge._WallClock() or nil
    if Civ6Ai_Autotest._stallTurn ~= turn then
      Civ6Ai_Autotest._stallTurn = turn
      Civ6Ai_Autotest._stallSince = now
      Civ6Ai_Autotest._stallAttempts = 0
      lastTickClock = now
      return true
    end
    if now == nil then
      return true
    end
    if lastTickClock == now then
      return true
    end
    lastTickClock = now
    local since = Civ6Ai_Autotest._stallSince
    if since == nil then
      Civ6Ai_Autotest._stallSince = now
      return true
    end
    if (now - since) < Civ6Ai_Autotest.STALL_SECONDS then
      return true
    end
    local playerID = Game.GetLocalPlayer and Game.GetLocalPlayer() or 0
    local waitingSeats = Civ6Ai_Autotest._SameTurnWaitActive()
    Civ6Ai_Autotest._stallAttempts = (Civ6Ai_Autotest._stallAttempts or 0) + 1
    Civ6Ai_Util.Log("autotest|stall_watch|turn=" .. tostring(turn)
      .. "|seconds=" .. tostring(now - since)
      .. "|attempt=" .. tostring(Civ6Ai_Autotest._stallAttempts)
      .. "|same_turn_wait=" .. tostring(waitingSeats))
    pcall(function()
      Civ6Ai_Autotest._CloseQueuedPopups()
      Civ6Ai_Autotest._DismissBlockers(playerID)
      if waitingSeats then
        return
      end
      if Civ6Ai_Apply ~= nil and Civ6Ai_Apply.ResolveAllUnitOrders ~= nil then
        Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
      end
      -- Human End Turn is gated by ActionPanel; RequestAction would bypass it.
      if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsAutotest ~= nil and not Civ6Ai_Config.IsAutotest() then
        return
      end
      if Civ6Ai_Autotest._TryEndTurnNow ~= nil then
        Civ6Ai_Autotest._TryEndTurnNow(playerID)
      end
    end)
    if Civ6Ai_Autotest._stallAttempts >= Civ6Ai_Autotest.STALL_MAX_ATTEMPTS then
      local line = "stall|turn=" .. tostring(turn) .. "|seconds=" .. tostring(now - since)
        .. "|attempts=" .. tostring(Civ6Ai_Autotest._stallAttempts)
      Civ6Ai_Util.Log("autotest|" .. line)
      Civ6Ai_Autotest._LogLine(line)
      if Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge.SessionId ~= nil then
        local root = Civ6Ai_Config ~= nil and Civ6Ai_Config.RootDir() or "civ6ai"
        local sid = Civ6Ai_Bridge.SessionId()
        local journal = Civ6Ai_Util.JoinPath(root, "sessions", sid, "stall.txt")
        pcall(function() Civ6Ai_Util.WriteTextFile(journal, line .. "\n") end)
      end
      Civ6Ai_Autotest._stallSince = now
      Civ6Ai_Autotest._stallAttempts = 0
    else
      Civ6Ai_Autotest._stallSince = now
    end
    return true
  end)
end

-- A unit-blocker that survives repeated skips is a unit we ordered that still has
-- moves (partial path, dropped goal, failed fallback). After a few tries in the same
-- turn, finish ordered units too so the turn can never stall on one unit.
Civ6Ai_Autotest.UNIT_BLOCK_FORCE_AFTER = 3
Civ6Ai_Autotest._unitBlockTries = { turn = -1, n = 0 }
function Civ6Ai_Autotest._SkipUnitMovesEscalating(playerID)
  local turn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or -1
  local t = Civ6Ai_Autotest._unitBlockTries
  if t.turn ~= turn or t.player ~= playerID then t.turn, t.player, t.n = turn, playerID, 0 end
  t.n = t.n + 1
  local force = t.n > Civ6Ai_Autotest.UNIT_BLOCK_FORCE_AFTER
  if force then
    Civ6Ai_Util.Log("autotest|unit_block_force|player=" .. tostring(playerID) .. "|tries=" .. tostring(t.n))
  end
  Civ6Ai_Autotest._SkipUnitMoves(playerID, force)
end

-- One military unit per tile. A unit the city finished while its center was
-- already held stays stacked there until it moves; the engine asks for that
-- move, and finishing its moves instead (the skip below) left it stacked for
-- good (live T36: P0 had five land military units in its capital). Before a
-- stacked land military unit is finished, step it to an adjacent tile with no
-- foreign unit and no land military unit of ours, through the normal MOVE_TO
-- request. True when a move was requested.
function Civ6Ai_Autotest._LandMilitary(unit)
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  return row ~= nil and row.FormationClass == "FORMATION_CLASS_LAND_COMBAT"
end

Civ6Ai_Autotest.UNSTACK_STEPS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 }, { 1, -1 }, { -1, 1 }, { 1, 1 }, { -1, -1 } }

function Civ6Ai_Autotest._Unstack(playerID, unit)
  local ok, moved = pcall(function()
    if Units == nil or Units.GetUnitsInPlot == nil or Map == nil or Map.GetPlot == nil
        or UnitManager == nil or UnitManager.RequestOperation == nil or UnitOperationTypes == nil then
      return false
    end
    if not Civ6Ai_Autotest._LandMilitary(unit) then
      return false
    end
    local x, y = unit:GetX(), unit:GetY()
    local function blocked(px, py, selfId)
      local plot = Map.GetPlot(px, py)
      if plot == nil then return true end
      for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
        if other:GetOwner() ~= playerID then
          return true
        end
        if other:GetID() ~= selfId and Civ6Ai_Autotest._LandMilitary(other) then
          return true
        end
      end
      return false
    end
    if not blocked(x, y, unit:GetID()) then
      return false
    end
    local moveOp = UnitOperationTypes.MOVE_TO
    for _, d in ipairs(Civ6Ai_Autotest.UNSTACK_STEPS) do
      local px, py = x + d[1], y + d[2]
      local plot = Map.GetPlot(px, py)
      if plot ~= nil and (Map.GetPlotDistance == nil or Map.GetPlotDistance(x, y, px, py) == 1)
          and not blocked(px, py, nil) then
        local params = {}
        params[UnitOperationTypes.PARAM_X] = px
        params[UnitOperationTypes.PARAM_Y] = py
        if UnitManager.CanStartOperation == nil or UnitManager.CanStartOperation(unit, moveOp, nil, params) then
          UnitManager.RequestOperation(unit, moveOp, params)
          Civ6Ai_Util.Log("autotest|unstack|player=" .. tostring(playerID) .. "|unit=" .. tostring(unit:GetID())
            .. "|from=" .. x .. "," .. y .. "|to=" .. px .. "," .. py)
          return true
        end
      end
    end
    Civ6Ai_Util.Log("autotest|unstack|player=" .. tostring(playerID) .. "|unit=" .. tostring(unit:GetID())
      .. "|from=" .. x .. "," .. y .. "|to=none")
    return false
  end)
  return ok and moved == true
end

function Civ6Ai_Autotest._SkipUnitMoves(playerID, force)
  pcall(function()
    local player = Players[playerID]
    if player == nil then
      return
    end
    local units = player:GetUnits()
    if units == nil then
      return
    end
    if units.Members ~= nil then
      for _, unit in units:Members() do
        if unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0
            and (force or not Civ6Ai_Apply._UnitWasOrdered(playerID, unit))
            and not Civ6Ai_Autotest._Unstack(playerID, unit) then
          UnitManager.FinishMoves(unit)
        end
      end
    else
      for i = 0, units:GetCount() - 1 do
        local unit = units:Get(i)
        if unit ~= nil and unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0
            and (force or not Civ6Ai_Apply._UnitWasOrdered(playerID, unit))
            and not Civ6Ai_Autotest._Unstack(playerID, unit) then
          UnitManager.FinishMoves(unit)
        end
      end
    end
  end)
end

function Civ6Ai_Autotest._RequestEndTurn()
  if UI == nil or UI.RequestAction == nil then
    return false, "no_ui_request_action"
  end
  local action = nil
  if ActionTypes ~= nil and ActionTypes.ACTION_ENDTURN ~= nil then
    action = ActionTypes.ACTION_ENDTURN
  elseif GameInfo ~= nil and GameInfo.Types ~= nil and GameInfo.Types.ACTION_ENDTURN ~= nil then
    action = GameInfo.Types.ACTION_ENDTURN.Hash
  end
  if action == nil then
    return false, "no_end_turn_action"
  end
  UI.RequestAction(action)
  return true, ""
end

-- True while playerID still has its turn. After an accepted end turn this goes
-- false; an Enter tap sent then lands in the next turn, where Enter is the
-- Next Turn hotkey and ends that turn before the model has answered.
function Civ6Ai_Autotest._TurnStillActive(playerID)
  local p = Players ~= nil and Players[playerID] or nil
  if p == nil or p.IsTurnActive == nil then
    return true
  end
  local ok, active = pcall(function() return p:IsTurnActive() end)
  return not ok or active == true
end

function Civ6Ai_Autotest._NudgeEnter(playerID)
  if playerID ~= Game.GetLocalPlayer() or not Civ6Ai_Autotest._TurnStillActive(playerID) then
    return
  end
  local text = "nudge_enter|player=" .. tostring(playerID)
  Civ6Ai_Util.Log("autotest|" .. text)
  Civ6Ai_Autotest._LogLine(text)
end

function Civ6Ai_Autotest._TryEndTurnNow(playerID)
  for attempt = 1, 6 do
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      break
    end
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
  end
  if UI.CanEndTurn ~= nil and not UI.CanEndTurn() then
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    return false, "end_turn_blocked"
  end
  local endOk, endReason = Civ6Ai_Autotest._RequestEndTurn()
  if not endOk then
    return false, endReason
  end
  return true, ""
end

function Civ6Ai_Autotest._ScheduleEndTurnRetry(playerID, origPlayer, maxAttempts)
  local attempts = 0
  Civ6Ai_Autotest._NudgeEnter(playerID)
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      local endOk, endReason = Civ6Ai_Autotest._RequestEndTurn()
      pcall(function()
        if origPlayer ~= nil and origPlayer ~= playerID and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
          PlayerManager.SetLocalPlayerAndObserver(origPlayer)
        end
      end)
      if endOk then
        Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
      else
        Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(endReason))
      end
      return false
    end
    if attempts == 1 or attempts % 3 == 0 then
      Civ6Ai_Autotest._NudgeEnter(playerID)
    end
    if attempts >= maxAttempts then
      pcall(function()
        if origPlayer ~= nil and origPlayer ~= playerID and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
          PlayerManager.SetLocalPlayerAndObserver(origPlayer)
        end
      end)
      Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|blocked_after_nudge")
      return false
    end
    return true
  end)
end

function Civ6Ai_Autotest._SchedulePopupDrain(playerID)
  if Civ6Ai_Autotest._draining then
    return
  end
  Civ6Ai_Autotest._draining = true
  local attempts = 0
  local startTurn = Game.GetCurrentGameTurn()
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    if Game.GetCurrentGameTurn() ~= startTurn or not Civ6Ai_Autotest._TurnStillActive(playerID) then
      Civ6Ai_Autotest._draining = false
      return false
    end
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      Civ6Ai_Autotest._RequestEndTurn()
    elseif attempts == 1 or attempts % 3 == 0 then
      Civ6Ai_Autotest._NudgeEnter(playerID)
    end
    if attempts >= 16 then
      Civ6Ai_Autotest._draining = false
      Civ6Ai_Autotest._NudgeEnter(playerID)
      return false
    end
    return true
  end)
end

function Civ6Ai_Autotest._EndManagedTurn(playerID)
  Civ6Ai_Autotest._CloseQueuedPopups()
  Civ6Ai_Autotest._DismissBlockers(playerID)
  Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
  local origPlayer = Game.GetLocalPlayer()
  if PlayerManager == nil or PlayerManager.SetLocalPlayerAndObserver == nil then
    if Game.GetLocalPlayer() == playerID then
      local endOk, endReason = Civ6Ai_Autotest._TryEndTurnNow(playerID)
      if endOk then
        Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
        Civ6Ai_Autotest._SchedulePopupDrain(playerID)
      else
        Civ6Ai_Autotest._NudgeEnter(playerID)
        Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(endReason))
        Civ6Ai_Autotest._SchedulePopupDrain(playerID)
      end
    else
      Civ6Ai_Autotest._LogLine("end_turn_skipped|player=" .. tostring(playerID) .. "|no_player_manager")
    end
    return
  end
  local ok, err = pcall(function()
    -- Never re-set the local seat onto itself: SetLocalPlayerAndObserver also makes
    -- it an observer, and the game then drops its UI city/player operations.
    if origPlayer ~= playerID then
      PlayerManager.SetLocalPlayerAndObserver(playerID)
    end
    local endOk, endReason = Civ6Ai_Autotest._TryEndTurnNow(playerID)
    if endOk then
      return
    end
    Civ6Ai_Autotest._ScheduleEndTurnRetry(playerID, origPlayer, 12)
    error("end_turn_pending_nudge")
  end)
  if ok then
    pcall(function()
      if origPlayer ~= nil and origPlayer ~= playerID then
        PlayerManager.SetLocalPlayerAndObserver(origPlayer)
      end
    end)
    Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
    Civ6Ai_Autotest._SchedulePopupDrain(playerID)
  elseif err == "end_turn_pending_nudge" then
    Civ6Ai_Autotest._LogLine("end_turn_blocked|player=" .. tostring(playerID))
  else
    pcall(function()
      if origPlayer ~= nil then
        PlayerManager.SetLocalPlayerAndObserver(origPlayer)
      end
    end)
    Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(err))
  end
end

function Civ6Ai_Autotest._WriteSessionSummary()
  local root = Civ6Ai_Config.RootDir()
  local sessionId = Civ6Ai_Bridge.SessionId()
  local summary = {
    event = "session_summary",
    session_id = sessionId,
    stop_turn = Civ6Ai_Autotest.StopTurn(),
    final_turn = Game.GetCurrentGameTurn(),
    stopped = true,
  }
  local path = Civ6Ai_Util.JoinPath(Civ6Ai_Autotest._AutotestDir(), "session_summary.json")
  Civ6Ai_Util.WriteTextFile(path, Civ6Ai_Util.EncodeJsonObject(summary) .. "\n")
  Civ6Ai_Autotest._LogLine("session_summary_written")
end
