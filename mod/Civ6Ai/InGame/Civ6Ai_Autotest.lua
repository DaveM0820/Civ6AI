-- Civ6Ai autotest: auto end-turn, session lifecycle, autotest.log.
Civ6Ai_Autotest = Civ6Ai_Autotest or {}

Civ6Ai_Autotest._stopped = false

function Civ6Ai_Autotest.Initialize()
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
  local path = Civ6Ai_Util.JoinPath(Civ6Ai_Autotest._AutotestDir(), "autotest.log")
  if Civ6Ai_Util.AppendTextLine(path, text) then
    return
  end
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

function Civ6Ai_Autotest.IsStopped()
  return Civ6Ai_Autotest._stopped
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
  Civ6Ai_Autotest._DisableBoostPopups()
  Civ6Ai_Autotest._CloseQueuedPopups()
  Civ6Ai_Autotest._DismissBlockers(playerID)
  -- Ending the turn is what the diplomacy ribbon uses to drop a portrait
  -- (RemotePlayerTurnEnd / IsTurnActive). Humans wait until every AI seat's
  -- answer is in. AI seats end as soon as this pulse is done, the same request
  -- the human uses, so their portrait shows completed.
  local p = Players[playerID]
  if p ~= nil and p:IsHuman() then
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
-- Single player plays the local seat's turn N first; the AI seats play their turn
-- N after it ends (same game turn number) and each dumps a snapshot then. The host
-- asks the model for one seat at a time, so the AI answers for turn N arrive while
-- the local seat plays turn N+1; each is sent on the order channel as it lands and
-- played at that seat's turn N+1 start (Civ6Ai_Bridge._DeliverSeatDecision). The
-- local seat therefore holds its end-turn until every AI seat that dumped a turn N
-- snapshot has had its answer sent (or given up on); otherwise the AI turn N+1 would start without
-- it and the native AI would play the seat. Bounded by a wall-clock deadline of
-- sidecar timeout x (pending seats + 1).
-- Sequential SP: hold end-turn until every AI seat's turn N-1 snapshot has an
-- answer (those answers play at turn N). Simultaneous LAN: hold until this
-- turn's dumps are sent, otherwise the year rolls and Firaxis plays the seats.
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
    "HistoricMoments",
    "EraReviewPopup",
    "EraCompletePopup",
    "DedicationPopup",
    "WorldCrisisPopup",
    "NaturalWonderPopup",
    "WonderBuiltPopup",
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

function Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)
  if Civ6Ai_Apply == nil then
    return
  end
  local techId = Civ6Ai_Autotest._PickFallbackTech(playerID)
  if techId ~= nil and Civ6Ai_Apply._SetResearchTech ~= nil then
    local ok, reason = Civ6Ai_Apply._SetResearchTech(playerID, { tech_id = techId })
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
    local ok, reason = Civ6Ai_Apply._SetResearchCivic(playerID, { civic_id = civicId })
    Civ6Ai_Autotest._LogLine(
      "auto_civic|player=" .. tostring(playerID)
      .. "|civic=" .. tostring(civicId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_civic|player=" .. tostring(playerID)
      .. "|civic=" .. tostring(civicId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
  end
  -- CHOOSE PRODUCTION: queue a safe default in any city with an empty build queue.
  Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  -- FILL_CIVIC_SLOT / CONSIDER_GOVERNMENT_CHANGE: slot cards + pick a government.
  Civ6Ai_Autotest._ClearPolicyGovernmentBlockers(playerID)
end

function Civ6Ai_Autotest._CityNeedsProduction(city)
  if city == nil or Civ6Ai_Production == nil then
    return false
  end
  local state = nil
  pcall(function() state = Civ6Ai_Production._GetCityProductionState(city) end)
  if type(state) ~= "table" then
    return true
  end
  local item = state.item_id or state.current or state.build_id
  return item == nil or item == "" or item == "NONE"
end

function Civ6Ai_Autotest._ClearProductionBlockers(playerID)
  if Civ6Ai_Production == nil or Civ6Ai_Production.FindExperimentTarget == nil then
    return
  end
  -- Local-seat UI RequestOperation only; matches Apply._QueueProduction constraints.
  local localPlayer = Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() or nil
  if localPlayer == nil or playerID ~= localPlayer then
    return
  end
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetCities == nil then
    return
  end
  local cities = player:GetCities()
  if cities == nil then
    return
  end
  local members = nil
  pcall(function()
    if cities.Members ~= nil then
      members = cities:Members()
    end
  end)
  local function consider(city)
    if city == nil or not Civ6Ai_Autotest._CityNeedsProduction(city) then
      return false
    end
    local cityWireId, buildId = Civ6Ai_Production.FindExperimentTarget(playerID)
    -- Prefer this city's wire id when FindExperimentTarget returned capital.
    if buildId == nil then
      return false
    end
    local wire = cityWireId
    pcall(function() wire = Civ6Ai_Production._WireCityId(city) or cityWireId end)
    local ok, reason = Civ6Ai_Production.QueueBuild(playerID, wire, buildId)
    Civ6Ai_Autotest._LogLine(
      "auto_production|player=" .. tostring(playerID)
      .. "|city=" .. tostring(wire) .. "|build=" .. tostring(buildId)
      .. "|ok=" .. tostring(ok) .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_production|player=" .. tostring(playerID)
      .. "|city=" .. tostring(wire) .. "|build=" .. tostring(buildId)
      .. "|ok=" .. tostring(ok) .. "|reason=" .. tostring(reason or ""))
    return ok == true
  end
  if members ~= nil then
    for _, city in members do
      if consider(city) then
        return
      end
    end
  end
  -- Fallback: experiment target alone.
  local cityWireId, buildId = Civ6Ai_Production.FindExperimentTarget(playerID)
  if cityWireId ~= nil and buildId ~= nil then
    local ok, reason = Civ6Ai_Production.QueueBuild(playerID, cityWireId, buildId)
    Civ6Ai_Autotest._LogLine(
      "auto_production|player=" .. tostring(playerID)
      .. "|city=" .. tostring(cityWireId) .. "|build=" .. tostring(buildId)
      .. "|ok=" .. tostring(ok) .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_production|player=" .. tostring(playerID)
      .. "|city=" .. tostring(cityWireId) .. "|build=" .. tostring(buildId)
      .. "|ok=" .. tostring(ok) .. "|reason=" .. tostring(reason or ""))
  end
end

-- Auto-fill empty policy slots / pick a government when FILL_CIVIC_SLOT or
-- CONSIDER_GOVERNMENT_CHANGE would leave GovernmentScreen (Change Policies) up.
-- Bare notification dismiss does not Confirm policies, so NEXT TURN stays blocked.
local function _policySlotFits(slotType, policyRow)
  local cardType = policyRow ~= nil and policyRow.GovernmentSlotType or nil
  if slotType == cardType or slotType == "SLOT_WILDCARD" then
    return true
  end
  return false
end

function Civ6Ai_Autotest._PickFallbackGovernment(playerID)
  local player = Players ~= nil and Players[playerID] or nil
  if player == nil or player.GetCulture == nil or GameInfo == nil or GameInfo.Governments == nil then
    return nil
  end
  local culture = player:GetCulture()
  if culture == nil then
    return nil
  end
  local cur = nil
  pcall(function() cur = culture:GetCurrentGovernment() end)
  if cur ~= nil and cur >= 0 then
    return nil
  end
  local can = nil
  pcall(function() can = culture:CanChangeGovernmentAtAll() end)
  if can ~= true then
    return nil
  end
  local made = false
  pcall(function() made = culture:GovernmentChangeMade() == true end)
  if made then
    return nil
  end
  -- Prefer Chiefdom when unlocked; else first unlocked government.
  local prefer = GameInfo.Governments["GOVERNMENT_CHIEFDOM"]
  if prefer ~= nil then
    local ok, unlocked = pcall(function()
      return culture:IsGovernmentUnlocked(prefer.Hash) == true
        or culture:IsGovernmentUnlocked(prefer.Index) == true
    end)
    if ok and unlocked then
      return prefer.GovernmentType
    end
  end
  for row in GameInfo.Governments() do
    local ok, unlocked = pcall(function()
      return culture:IsGovernmentUnlocked(row.Hash) == true
        or culture:IsGovernmentUnlocked(row.Index) == true
    end)
    if ok and unlocked then
      return row.GovernmentType
    end
  end
  return nil
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

  local govId = Civ6Ai_Autotest._PickFallbackGovernment(playerID)
  if govId ~= nil then
    local ok, reason = false, "no_apply"
    if Civ6Ai_Apply ~= nil and Civ6Ai_Apply._ChangeGovernment ~= nil then
      ok, reason = Civ6Ai_Apply._ChangeGovernment(
        playerID,
        { kind = "change_government", id = "autotest_fallback" },
        { government_id = govId })
      if ok == Civ6Ai_Apply.DEFERRED then
        ok = true
        reason = reason or "deferred"
      end
    else
      local row = GameInfo.Governments[govId]
      if row ~= nil then
        local okCall, okReq = pcall(function()
          return culture:RequestChangeGovernment(row.Hash)
        end)
        ok = okCall and okReq == true
        reason = ok and "" or tostring(okReq)
      end
    end
    Civ6Ai_Autotest._LogLine(
      "auto_government|player=" .. tostring(playerID)
      .. "|government=" .. tostring(govId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
    Civ6Ai_Util.Log(
      "autotest|auto_government|player=" .. tostring(playerID)
      .. "|government=" .. tostring(govId) .. "|ok=" .. tostring(ok)
      .. "|reason=" .. tostring(reason or ""))
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
        if prow ~= nil then
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


function Civ6Ai_Autotest._DismissBlockers(playerID)
  -- Choose research/civic before dismissing notifications: bare Dismiss does not
  -- select a civic, so CHOOSE CIVIC stays up and blocks NEXT TURN.
  Civ6Ai_Autotest._ClearResearchCivicBlockers(playerID)

  local list = NotificationManager.GetList(playerID)
  if list == nil then
    return
  end
  local count = 0
  for _, nid in ipairs(list) do
    local entry = NotificationManager.Find(playerID, nid)
    if entry ~= nil and not entry:IsDismissed() then
      local blocking = entry:GetEndTurnBlocking()
      if blocking ~= nil and blocking ~= 0 then
        pcall(function() NotificationManager.SendActivated(playerID, nid) end)
        pcall(function() NotificationManager.Dismiss(playerID, nid) end)
        count = count + 1
      end
    end
  end
  if count > 0 then
    Civ6Ai_Autotest._LogLine("blockers|player=" .. tostring(playerID) .. "|count=" .. tostring(count))
  end
end

function Civ6Ai_Autotest._SkipUnitMoves(playerID)
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
            and not Civ6Ai_Apply._UnitWasOrdered(playerID, unit) then
          UnitManager.FinishMoves(unit)
        end
      end
    else
      for i = 0, units:GetCount() - 1 do
        local unit = units:Get(i)
        if unit ~= nil and unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0
            and not Civ6Ai_Apply._UnitWasOrdered(playerID, unit) then
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
        if origPlayer ~= nil and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
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
        if origPlayer ~= nil and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
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
    PlayerManager.SetLocalPlayerAndObserver(playerID)
    local endOk, endReason = Civ6Ai_Autotest._TryEndTurnNow(playerID)
    if endOk then
      return
    end
    Civ6Ai_Autotest._ScheduleEndTurnRetry(playerID, origPlayer, 12)
    error("end_turn_pending_nudge")
  end)
  if ok then
    pcall(function()
      if origPlayer ~= nil then
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
