-- Civ5Ai apply: research, production, movement, policies, workers, great people, special unit missions.
Civ5Ai_Apply = Civ5Ai_Apply or {}

Civ5Ai_Apply._orderedUnits = {}
Civ5Ai_Apply._failedUnits = {}
Civ5Ai_Apply._orderOrigin = {}
Civ5Ai_Apply._productionSatisfied = {}
Civ5Ai_Apply._pendingSkipRemaining = {}
Civ5Ai_Apply._turnAutomatedUnits = {}
Civ5Ai_Apply._zeroedEndTurn = Civ5Ai_Apply._zeroedEndTurn or {}
Civ5Ai_Apply._restoredTurn = Civ5Ai_Apply._restoredTurn or {}
Civ5Ai_Apply._PendingNotes = Civ5Ai_Apply._PendingNotes or {}
Civ5Ai_Apply._PendingCommandResults = Civ5Ai_Apply._PendingCommandResults or {}

Civ5Ai_Apply._MP_KINDS = Civ5Ai_Commands.MpKindSet()

-- Read-only informational popups (progress rankings, wonder splash, etc.) that
-- block turns but need no player choice during managed/autotest play.
Civ5Ai_Apply._INFO_POPUP_SPECS = {
  { path = "/InGame/WhosWinningPopup", popup = "BUTTONPOPUP_WHOS_WINNING" },
  { path = "/InGame/WonderPopup", popup = "BUTTONPOPUP_WONDER_COMPLETED_ACTIVE_PLAYER" },
  { path = "/InGame/TextPopup", popup = "BUTTONPOPUP_TEXT" },
  { path = "/InGame/VoteResultsPopup", popup = "BUTTONPOPUP_VOTE_RESULTS" },
  { path = "/InGame/AdvisorCounselPopup", popup = "BUTTONPOPUP_ADVISOR_COUNSEL" },
  { path = "/InGame/AdvisorModal", popup = "BUTTONPOPUP_ADVISOR_MODAL" },
}

function Civ5Ai_Apply._HasMethod(obj, methodName)
  return obj ~= nil and obj[methodName] ~= nil
end

function Civ5Ai_Apply._Mission(name)
  if MissionTypes ~= nil and MissionTypes[name] ~= nil then
    return MissionTypes[name]
  end
  if GameInfoTypes ~= nil and GameInfoTypes[name] ~= nil then
    return GameInfoTypes[name]
  end
  return nil
end

function Civ5Ai_Apply._NetEncodingRequired()
  return Game ~= nil and Game.SendCiv5AiCommands ~= nil
end

function Civ5Ai_Apply._NetKindSupported(kind)
  return kind ~= nil and Civ5Ai_Apply._MP_KINDS[kind] == true
end

function Civ5Ai_Apply._CommandSortKey(kind)
  local order = {
    unlock_policy_branch = 10,
    adopt_ideology = 11,
    adopt_social_policy = 12,
    found_pantheon = 13,
    found_religion = 14,
    enhance_religion = 15,
    choose_maya_bonus = 20,
    choose_free_great_person = 19,
    promote_unit = 21,
    set_research_tech = 85,
    queue_production = 31,
    buy_with_gold = 32,
    buy_with_faith = 33,
    disband_unit = 25,
    sell_building = 26,
    set_city_status = 27,
    improve_tile = 41,
    automate_unit = 76,
    discover_tech = 43,
    hurry_production = 43,
    trade_mission = 44,
    establish_trade_route = 42,
    change_trade_home_city = 42,
    recall_trader = 42,
    start_golden_age = 45,
    create_great_work = 46,
    spread_religion = 47,
    remove_heresy = 47,
    pillage = 48,
    upgrade_unit = 49,
    propose_deal = 50,
    respond_to_deal = 51,
    cancel_deal = 52,
    declare_war = 53,
    move_unit = 60,
    found_city = 61,
    attack_target = 62,
    range_attack = 63,
    rebase = 64,
    paradrop = 65,
    nuke = 66,
    unit_posture_fortify = 70,
    unit_posture_alert = 71,
    unit_posture_heal = 72,
    unit_posture_sleep = 73,
    air_patrol = 74,
    unit_skip = 80,
  }
  return order[kind] or 90
end

function Civ5Ai_Apply._SortCommands(commands)
  if commands == nil then
    return
  end
  table.sort(commands, function(a, b)
    local ak = Civ5Ai_Apply._CommandSortKey(a.kind)
    local bk = Civ5Ai_Apply._CommandSortKey(b.kind)
    if ak ~= bk then
      return ak < bk
    end
    local aId = a.command_id or ""
    local bId = b.command_id or ""
    return aId < bId
  end)
end

function Civ5Ai_Apply.BeginPulse(playerID)
  Civ5Ai_Apply._applySeat = playerID
  Civ5Ai_Apply._orderedUnits[playerID] = {}
  Civ5Ai_Apply._failedUnits[playerID] = {}
  Civ5Ai_Apply._orderOrigin[playerID] = {}
  Civ5Ai_Apply._pendingSkipRemaining[playerID] = {}
  Civ5Ai_Apply._productionSatisfied[playerID] = {}
  Civ5Ai_Apply._turnAutomatedUnits[playerID] = {}
end

-- Do not SetActivePlayer here. That call updates fog/minimap to the
-- target seat, which leaks other civs on the local minimap during
-- simultaneous LLM pulses. Player-object APIs take playerID directly;
-- CityPushOrder uses city:PushOrder without a local-active switch.
function Civ5Ai_Apply._WithActivePlayer(playerID, fn)
  if fn == nil then
    return nil
  end
  return fn()
end

-- Local human production must run under Game.GetActivePlayer() == seat or
-- CityPushOrder leaves ENDTURN_BLOCKING_PRODUCTION set while cities look queued.
function Civ5Ai_Apply._WithLocalHumanActivePlayer(playerID, fn)
  if fn == nil then
    return nil
  end
  local needsSwitch = Civ5Ai_Seats ~= nil
    and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil
    and Civ5Ai_Seats.IsActiveLocalPlayer(playerID) == true
    and Game ~= nil
    and Game.GetActivePlayer ~= nil
    and Game.SetActivePlayer ~= nil
  local restore = nil
  if needsSwitch then
    restore = Game.GetActivePlayer()
    needsSwitch = restore ~= playerID
  end
  if needsSwitch then
    Game.SetActivePlayer(playerID)
  end
  local ok, result = pcall(fn)
  if needsSwitch and restore ~= nil then
    Game.SetActivePlayer(restore)
  end
  if ok then
    return result
  end
  Civ5Ai_Util.Log(
    "apply|local_active_player|player="
      .. tostring(playerID)
      .. "|"
      .. tostring(result)
  )
  return nil
end

function Civ5Ai_Apply._AllCitiesHaveProductionQueued(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local cityCount = 0
  for city in player:Cities() do
    if city ~= nil then
      cityCount = cityCount + 1
      if not Civ5Ai_Apply._CityHasProductionQueued(city) then
        return false
      end
    end
  end
  return cityCount > 0
end

function Civ5Ai_Apply._ResyncLocalHumanProduction(playerID)
  if not Civ5Ai_Apply._AllCitiesHaveProductionQueued(playerID) then
    return false
  end
  local player = Players[playerID]
  if player == nil then
    return false
  end
  return Civ5Ai_Apply._WithLocalHumanActivePlayer(playerID, function()
    local touched = false
    for city in player:Cities() do
      if city ~= nil and Civ5Ai_Apply._CityHasProductionQueued(city) then
        local unitId = city.GetProductionUnit ~= nil and (city:GetProductionUnit() or -1) or -1
        local buildingId = city.GetProductionBuilding ~= nil and (city:GetProductionBuilding() or -1) or -1
        local projectId = city.GetProductionProject ~= nil and (city:GetProductionProject() or -1) or -1
        local processId = city.GetProductionProcess ~= nil and (city:GetProductionProcess() or -1) or -1
        if unitId >= 0 and OrderTypes ~= nil and Game ~= nil and Game.CityPushOrder ~= nil then
          Game.CityPushOrder(city, OrderTypes.ORDER_TRAIN, unitId, false, false, true)
          touched = true
        elseif buildingId >= 0 and OrderTypes ~= nil and Game ~= nil and Game.CityPushOrder ~= nil then
          Game.CityPushOrder(city, OrderTypes.ORDER_CONSTRUCT, buildingId, false, false, true)
          touched = true
        elseif projectId >= 0 and OrderTypes ~= nil and Game ~= nil and Game.CityPushOrder ~= nil then
          Game.CityPushOrder(city, OrderTypes.ORDER_CREATE, projectId, false, false, true)
          touched = true
        elseif processId >= 0 and OrderTypes ~= nil and Game ~= nil and Game.CityPushOrder ~= nil then
          Game.CityPushOrder(city, OrderTypes.ORDER_MAINTAIN, processId, false, false, true)
          touched = true
        end
        if Events ~= nil and Events.SpecificCityInfoDirty ~= nil and CityUpdateTypes ~= nil then
          Events.SpecificCityInfoDirty(playerID, city:GetID(), CityUpdateTypes.CITY_UPDATE_TYPE_PRODUCTION)
        end
      end
    end
    if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
      Events.SerialEventEndTurnDirty()
    end
    if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
      Events.SerialEventGameDataDirty()
    end
    return touched
  end) == true
end

function Civ5Ai_Apply._PlayerCityCount(playerID)
  local player = Players[playerID]
  if player == nil or player.GetNumCities == nil then
    return 0
  end
  return player:GetNumCities() or 0
end

function Civ5Ai_Apply._AllowsNativeProductionFill(playerID)
  local minCities = 15
  if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot.NATIVE_PRODUCTION_MIN_CITIES ~= nil then
    minCities = Civ5Ai_Snapshot.NATIVE_PRODUCTION_MIN_CITIES
  end
  return Civ5Ai_Apply._PlayerCityCount(playerID) >= minCities
end

function Civ5Ai_Apply._UsesUiApply()
  return Civ5Ai_Seats ~= nil
    and Civ5Ai_Apply._applySeat ~= nil
    and Civ5Ai_Seats.UsesUiApply(Civ5Ai_Apply._applySeat)
end

function Civ5Ai_Apply.ApplyDecision(playerID, decision)
  return Civ5Ai_Apply._WithActivePlayer(playerID, function()
    return Civ5Ai_Apply._ApplyDecisionImpl(playerID, decision)
  end)
end

function Civ5Ai_Apply._CommandUnitId(command)
  if command == nil then
    return nil
  end
  if command.arguments ~= nil and command.arguments.unit_id ~= nil then
    return command.arguments.unit_id
  end
  local cmdId = tostring(command.command_id or "")
  local unitId = string.match(cmdId, "(UNIT_%d+)")
  return unitId
end

function Civ5Ai_Apply._CommandCityId(command)
  if command == nil then
    return nil
  end
  if command.arguments ~= nil and command.arguments.city_id ~= nil then
    return command.arguments.city_id
  end
  local cmdId = tostring(command.command_id or "")
  local cityId = string.match(cmdId, "(CITY_[%w_]+)")
  return cityId
end

function Civ5Ai_Apply._FilterLiveCommands(playerID, commands)
  -- Drop orders for units/cities that are not alive this pulse (stale mailbox replay).
  local kept = {}
  if commands == nil then
    return kept
  end
  for _, command in ipairs(commands) do
    local unitId = Civ5Ai_Apply._CommandUnitId(command)
    local cityId = Civ5Ai_Apply._CommandCityId(command)
    local drop = false
    local reason = nil
    if unitId ~= nil then
      local unit = Civ5Ai_Apply._FindUnit(playerID, unitId)
      if unit == nil then
        drop = true
        reason = "stale_unit_id"
      end
    end
    if (not drop) and cityId ~= nil and Civ5Ai_Apply._FindCity ~= nil then
      local city = Civ5Ai_Apply._FindCity(playerID, cityId)
      if city == nil then
        drop = true
        reason = "stale_city_id"
      end
    end
    if drop then
      local kind = tostring(command.kind or "command")
      local line = "apply|skip|" .. kind .. "|" .. tostring(reason) .. "|" .. tostring(command.command_id or unitId or cityId)
      Civ5Ai_Util.Log(line)
    else
      table.insert(kept, command)
    end
  end
  return kept
end

function Civ5Ai_Apply._IsPlotOccupiedRetryableKind(kind)
  -- Friendly combat stacking blocks move / melee-as-move (attack_target).
  return kind == "move_unit" or kind == "attack_target"
end

function Civ5Ai_Apply._CountPlotOccupiedRetryable(commands)
  local n = 0
  if commands == nil then
    return 0
  end
  for _, command in ipairs(commands) do
    if command ~= nil and Civ5Ai_Apply._IsPlotOccupiedRetryableKind(command.kind) then
      n = n + 1
    end
  end
  return n
end

function Civ5Ai_Apply._CommandUnitIdForLog(command)
  if command == nil then
    return ""
  end
  if command.arguments ~= nil and command.arguments.unit_id ~= nil then
    return tostring(command.arguments.unit_id)
  end
  return tostring(command.command_id or "")
end

function Civ5Ai_Apply._MoveRetryMaxPasses(commands)
  local moveLike = Civ5Ai_Apply._CountPlotOccupiedRetryable(commands)
  local maxPasses = moveLike
  if maxPasses < 1 then
    maxPasses = 1
  end
  if maxPasses > 32 then
    maxPasses = 32
  end
  return maxPasses, moveLike
end

function Civ5Ai_Apply._ApplyDecisionImpl(playerID, decision)
  local lines = {}
  if decision == nil or decision.commands == nil then
    Civ5Ai_Util.Log("apply|no_commands|player=" .. tostring(playerID))
    table.insert(lines, "apply|no_commands|player=" .. tostring(playerID))
    return lines
  end
  Civ5Ai_Apply.BeginPulse(playerID)
  if Civ5Ai_Apply._UsesUiApply() and Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
    Civ5Ai_Autotest._ReleaseUiFocus()
  end
  Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  Civ5Ai_Apply._AcknowledgeGoodyHutAnnounce(playerID)
  decision.commands = Civ5Ai_Apply._FilterLiveCommands(playerID, decision.commands)
  Civ5Ai_Apply._SortCommands(decision.commands)
  local pending = {}
  for _, command in ipairs(decision.commands) do
    table.insert(pending, command)
  end
  -- After the first pass, retry plot_occupied move-like commands until a
  -- full retry pass has zero successes (rear units unblock when front moves).
  -- Cap iterations by move-like count (ceiling 32) to avoid infinite loops.
  local maxPasses, moveLike = Civ5Ai_Apply._MoveRetryMaxPasses(decision.commands)
  local budgetLine = "apply|move_retry_budget|move_like="
    .. tostring(moveLike)
    .. "|max_passes="
    .. tostring(maxPasses)
  table.insert(lines, budgetLine)
  Civ5Ai_Util.Log(budgetLine)
  for pass = 1, maxPasses do
    local retry = {}
    local passSuccesses = 0
    local passTried = 0
    for _, command in ipairs(pending) do
      passTried = passTried + 1
      local kind = command.kind
      local line = nil
      local deferOccupied = false
      local unitLog = Civ5Ai_Apply._CommandUnitIdForLog(command)
      if Civ5Ai_Apply._NetEncodingRequired() and not Civ5Ai_Apply._NetKindSupported(kind) then
        line = "apply|fail|" .. tostring(kind) .. "|mp_encode_missing"
        Civ5Ai_Apply._RecordCommandFailure(playerID, command, "mp_encode_missing")
      else
        local ok, success, reason = pcall(Civ5Ai_Apply._ApplyCommand, playerID, command)
        if not ok then
          line = "apply|fail|" .. tostring(kind) .. "|lua_error|" .. tostring(success)
          Civ5Ai_Apply._RecordCommandFailure(playerID, command, "lua_error")
        elseif success then
          local unitId = command.arguments and command.arguments.unit_id
          local softSkip = (reason == "automation_soft_skip_no_moves")
            or (reason == "found_soft_skip_city_already_here")
          if unitId ~= nil and not softSkip then
            Civ5Ai_Apply._orderedUnits[playerID][unitId] = true
            Civ5Ai_Apply._RecordOrderOrigin(playerID, unitId, kind, command.arguments)
            if kind == "automate_unit" then
              Civ5Ai_Apply._MarkTurnAutomated(playerID, unitId)
            end
          end
          if (not softSkip) and (kind == "attack_target" or kind == "range_attack" or kind == "city_range_strike") then
            Civ5Ai_Apply._RecordCombatSuccess(playerID, command)
          end
          if softSkip then
            line = "apply|skip|" .. tostring(kind) .. "|" .. tostring(reason) .. "|" .. tostring(command.command_id)
          else
            passSuccesses = passSuccesses + 1
            line = "apply|ok|" .. tostring(kind) .. "|" .. tostring(command.command_id)
            if pass > 1 then
              line = line
                .. "|pass="
                .. tostring(pass)
                .. "|unit="
                .. unitLog
                .. "|retry"
            end
          end
        elseif reason == "plot_occupied"
            and Civ5Ai_Apply._IsPlotOccupiedRetryableKind(kind) then
          deferOccupied = true
          table.insert(retry, command)
          line = "apply|defer|"
            .. tostring(kind)
            .. "|plot_occupied|pass="
            .. tostring(pass)
            .. "|unit="
            .. unitLog
          if command ~= nil and command.command_id ~= nil then
            line = line .. "|" .. tostring(command.command_id)
          end
        else
          line = "apply|fail|" .. tostring(kind) .. "|" .. tostring(reason)
          if command ~= nil and command.command_id ~= nil then
            line = line .. "|" .. tostring(command.command_id)
          end
          Civ5Ai_Apply._RecordApplyFailEcho(playerID, kind, reason, command)
          Civ5Ai_Apply._RecordCommandFailure(playerID, command, reason)
        end
      end
      if not deferOccupied then
        table.insert(lines, line)
        Civ5Ai_Util.Log(line)
      else
        -- Keep defer lines in apply output so retries are visible.
        table.insert(lines, line)
        Civ5Ai_Util.Log(line)
      end
    end
    if pass > 1 or #retry > 0 then
      local summary = "apply|retry_pass|pass="
        .. tostring(pass)
        .. "|tried="
        .. tostring(passTried)
        .. "|ok="
        .. tostring(passSuccesses)
        .. "|still_deferred="
        .. tostring(#retry)
      table.insert(lines, summary)
      Civ5Ai_Util.Log(summary)
    end
    pending = retry
    if #pending == 0 then
      break
    end
    if pass == maxPasses then
      break
    end
    -- After the first pass, stop when a full retry pass had zero successes.
    if pass > 1 and passSuccesses == 0 then
      break
    end
  end
  for _, command in ipairs(pending) do
    local kind = command.kind
    local unitLog = Civ5Ai_Apply._CommandUnitIdForLog(command)
    local line = "apply|fail|"
      .. tostring(kind)
      .. "|plot_occupied|unit="
      .. unitLog
    if command ~= nil and command.command_id ~= nil then
      line = line .. "|" .. tostring(command.command_id)
    end
    Civ5Ai_Apply._RecordCommandFailure(playerID, command, "plot_occupied")
    table.insert(lines, line)
    Civ5Ai_Util.Log(line)
  end
  Civ5Ai_Apply._ResolvePostCommandBlockers(playerID, decision)
  return lines
end

function Civ5Ai_Apply._ResolvePostCommandBlockers(playerID, decision)
  local founded = false
  if decision ~= nil and decision.commands ~= nil then
    for _, command in ipairs(decision.commands) do
      if command ~= nil and command.kind == "found_city" then
        founded = true
        break
      end
    end
  end
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local t = EndTurnBlockingTypes
  local needsResearch = t == nil
    or blocking == t.ENDTURN_BLOCKING_RESEARCH
    or blocking == t.ENDTURN_BLOCKING_FREE_TECH
    or blocking == t.ENDTURN_BLOCKING_STEAL_TECH
  if founded then
    Civ5Ai_Apply.ResolveCityProduction(playerID)
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION then
    Civ5Ai_Apply.ResolveCityProduction(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  end
  if founded or needsResearch then
    -- Always pick research after founding. Waiting for PRODUCTION to clear
    -- left seat 0 with can=false / blocking=-1 (CHOOSE RESEARCH) forever.
    Civ5Ai_Apply.ResolveResearch(playerID)
  end
end

function Civ5Ai_Apply._FindCity(playerID, cityId)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  for city in player:Cities() do
    if Civ5Ai_Snapshot._CityWireId(city) == cityId then
      return city
    end
  end
  return nil
end

function Civ5Ai_Apply._FindUnit(playerID, unitId)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local numeric = string.match(tostring(unitId), "^UNIT_(%d+)$")
  if numeric ~= nil then
    local unit = player:GetUnitByID(tonumber(numeric))
    if unit ~= nil and not unit:IsDead() then
      return unit
    end
  end
  for unit in player:Units() do
    if Civ5Ai_Snapshot._UnitWireId(unit) == unitId then
      return unit
    end
  end
  return nil
end

function Civ5Ai_Apply._UnitWasOrdered(playerID, unitId)
  local bucket = Civ5Ai_Apply._orderedUnits[playerID]
  if bucket == nil then
    return false
  end
  local wireId = Civ5Ai_Snapshot._UnitWireId(unitId)
  return bucket[wireId] == true or bucket[unitId] == true
end

function Civ5Ai_Apply._MarkTurnAutomated(playerID, unitId)
  Civ5Ai_Apply._turnAutomatedUnits[playerID] = Civ5Ai_Apply._turnAutomatedUnits[playerID] or {}
  Civ5Ai_Apply._turnAutomatedUnits[playerID][Civ5Ai_Snapshot._UnitWireId(unitId)] = true
end

function Civ5Ai_Apply._UnitWasAutomatedThisTurn(playerID, unit)
  local bucket = Civ5Ai_Apply._turnAutomatedUnits[playerID]
  if bucket == nil or unit == nil then
    return false
  end
  return bucket[Civ5Ai_Snapshot._UnitWireId(unit)] == true
end

function Civ5Ai_Apply._UnitSkipRemainingQueued(playerID, unitId)
  local bucket = Civ5Ai_Apply._pendingSkipRemaining[playerID]
  if bucket == nil or unitId == nil then
    return false
  end
  if bucket[unitId] == true then
    return true
  end
  -- Match either raw id or wire id (same as _UnitWasOrdered).
  if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._UnitWireId ~= nil then
    local wireId = Civ5Ai_Snapshot._UnitWireId(unitId)
    if wireId ~= nil and bucket[wireId] == true then
      return true
    end
  end
  return false
end

function Civ5Ai_Apply._QueueSkipIfShortMove(playerID, unit, destX, destY)
  if Civ5Ai_Seats == nil then
    return
  end
  if not Civ5Ai_Seats.UsesFullLlmControl(playerID) then
    return
  end
  if unit == nil or destX == nil or destY == nil then
    return
  end
  local dist = Civ5Ai_Snapshot._PlotDistance(unit:GetX(), unit:GetY(), destX, destY)
  local moves = Civ5Ai_Snapshot._MovePointsToTiles(unit:MovesLeft() or 0)
  if dist >= moves then
    return
  end
  local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
  Civ5Ai_Apply._QueueLeftoverSkip(playerID, unitId)
  Civ5Ai_Util.Log(
    "apply|queue_skip|unit="
      .. tostring(unitId)
      .. "|dist="
      .. tostring(dist)
      .. "|moves="
      .. tostring(moves)
  )
end

function Civ5Ai_Apply._UnitIsBusyMoving(unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  -- Automated units keep MovesLeft with IsReadyToMove=false. Treating them as
  -- busy livelocks endturn_wait_ordered forever (A/B drain + zero_auto never run).
  if unit.IsAutomated ~= nil and unit:IsAutomated() == true then
    return false
  end
  -- Only ACTIVITY_MISSION (pathing / executing) is in-flight. HOLD/SLEEP with
  -- MovesLeft and ReadyToMove=false is NOT busy — live t43 UNIT_1035 sat at
  -- moves=120/act=HOLD/ready=false and was misclassified as busy, so net SKIP
  -- never ran and end-turn stayed blocked.
  if unit.GetActivityType ~= nil and ActivityTypes ~= nil then
    local act = unit:GetActivityType()
    if ActivityTypes.ACTIVITY_MISSION ~= nil and act == ActivityTypes.ACTIVITY_MISSION then
      return Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
    end
    if ActivityTypes.ACTIVITY_HOLD ~= nil and act == ActivityTypes.ACTIVITY_HOLD then
      return false
    end
    if ActivityTypes.ACTIVITY_SLEEP ~= nil and act == ActivityTypes.ACTIVITY_SLEEP then
      return false
    end
    if ActivityTypes.ACTIVITY_HEAL ~= nil and act == ActivityTypes.ACTIVITY_HEAL then
      return false
    end
  end
  if unit.IsBusy ~= nil and unit:IsBusy() == true then
    return Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
  end
  return false
end

function Civ5Ai_Apply._UnitOrderedId(playerID, unit)
  if unit == nil then
    return nil
  end
  return Civ5Ai_Snapshot._UnitWireId(unit)
end

function Civ5Ai_Apply._IsUnorderedBlockingUnit(playerID, unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  if unit.IsAutomated ~= nil and unit:IsAutomated() then
    return false
  end
  if unit.GetActivityType ~= nil and ActivityTypes ~= nil
      and ActivityTypes.ACTIVITY_INTERCEPT ~= nil
      and unit:GetActivityType() == ActivityTypes.ACTIVITY_INTERCEPT then
    return false
  end
  if Civ5Ai_Apply._UnitIsBusyMoving(unit) then
    return false
  end
  if Civ5Ai_Apply._UnitWasAutomatedThisTurn(playerID, unit) then
    return false
  end
  -- End turn must not wait on units the model did not finish ordering.
  -- Skip any idle unit that still needs orders; in-flight moves stay protected above.
  return Civ5Ai_Snapshot._UnitNeedsOrders(unit) == true
end

function Civ5Ai_Apply._StopUnitAutomation(unit)
  -- Explicit LLM orders cancel AUTOMATE_EXPLORE/BUILD before move/found/attack.
  -- Lua apply is untested in pytest; keep this in sync with live MODS + Expansion2 InGame copies.
  if unit == nil then
    return false
  end
  local was = false
  if unit.IsAutomated ~= nil and unit:IsAutomated() then
    was = true
  elseif unit.GetAutomateType ~= nil then
    local autoType = unit:GetAutomateType()
    if type(autoType) == "number" and autoType ~= 0 then
      was = true
    end
  end
  if not was then
    return false
  end
  if CommandTypes ~= nil and CommandTypes.COMMAND_STOP_AUTOMATION ~= nil and unit.DoCommand ~= nil then
    unit:DoCommand(CommandTypes.COMMAND_STOP_AUTOMATION)
  end
  if unit.SetAutomateType ~= nil then
    local none = 0
    if AutomateTypes ~= nil and AutomateTypes.NO_AUTOMATE ~= nil then
      none = AutomateTypes.NO_AUTOMATE
    elseif AutomateTypes ~= nil and AutomateTypes.AUTOMATE_NONE ~= nil then
      none = AutomateTypes.AUTOMATE_NONE
    end
    unit:SetAutomateType(none)
  elseif unit.SetAutomated ~= nil then
    unit:SetAutomated(false)
  end
  if unit.Wake ~= nil then
    unit:Wake()
  elseif ActivityTypes ~= nil and ActivityTypes.ACTIVITY_AWAKE ~= nil and unit.SetActivityType ~= nil then
    unit:SetActivityType(ActivityTypes.ACTIVITY_AWAKE)
  end
  return true
end

function Civ5Ai_Apply._FinishUnitMoves(unit)
  if unit == nil then
    return false
  end
  local owner = nil
  if unit.GetOwner ~= nil then
    owner = unit:GetOwner()
  end
  local localHuman = owner ~= nil and Civ5Ai_Apply._IsLocalHumanSeat(owner)
  local prevSeat = Civ5Ai_Apply._applySeat
  if localHuman then
    Civ5Ai_Apply._applySeat = owner
  end
  local skip = Civ5Ai_Apply._Mission("MISSION_SKIP")
  if skip ~= nil then
    -- PushMission updates the DLL ReadyToMove/activity. Avoid SetMoves/
    -- SetActivityType alone (Lua/DLL desync). For local human also net SKIP
    -- via _PushSelectedMission so UI/selection stays consistent.
    Civ5Ai_Apply._PushSelectedMission(unit, skip, 0, 0, "MISSION_SKIP")
  end
  if not localHuman then
    if unit.FinishMoves ~= nil then
      unit:FinishMoves()
    end
    if unit.SetMoves ~= nil then
      unit:SetMoves(0)
    end
    if ActivityTypes ~= nil and unit.SetActivityType ~= nil then
      unit:SetActivityType(ActivityTypes.ACTIVITY_HOLD)
    end
  else
    -- Local human: after select+PushMission+net, also HOLD/zero so DLL
    -- ReadyToMove clears even if net SKIP lags one tick.
    if ActivityTypes ~= nil and unit.SetActivityType ~= nil then
      unit:SetActivityType(ActivityTypes.ACTIVITY_HOLD)
    end
    if unit.SetMoves ~= nil then
      unit:SetMoves(0)
    end
  end
  local movesFinal = 0
  if unit.MovesLeft ~= nil then
    movesFinal = unit:MovesLeft() or 0
  end
  local readyFinal = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true
  Civ5Ai_Apply._NoteZeroedForEndTurn(unit)
  if prevSeat ~= nil then
    Civ5Ai_Apply._applySeat = prevSeat
  end
  return movesFinal <= 0 and not readyFinal
end

function Civ5Ai_Apply._IsLocalHumanSeat(playerID)
  return Civ5Ai_Seats ~= nil
    and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil
    and Civ5Ai_Seats.IsActiveLocalPlayer(playerID) == true
end

function Civ5Ai_Apply._NoteZeroedForEndTurn(unit)
  if unit == nil or unit.GetOwner == nil then
    return
  end
  local owner = unit:GetOwner()
  if not Civ5Ai_Apply._IsLocalHumanSeat(owner) then
    return
  end
  local id = Civ5Ai_Snapshot._UnitWireId(unit)
  Civ5Ai_Apply._zeroedEndTurn[owner] = Civ5Ai_Apply._zeroedEndTurn[owner] or {}
  Civ5Ai_Apply._zeroedEndTurn[owner][id] = true
end

-- Undo SKIP/SetMoves(0)/HOLD from the previous local-human end-turn.
-- If vanilla already restored MovesLeft, only wake HOLD. Do not add a second budget.
function Civ5Ai_Apply._RestoreLocalHumanUnitsAfterTurnAdvance(playerID)
  if playerID == nil or not Civ5Ai_Apply._IsLocalHumanSeat(playerID) then
    if playerID ~= nil then
      Civ5Ai_Apply._zeroedEndTurn[playerID] = nil
    end
    return
  end
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn() or 0
  end
  if Civ5Ai_Apply._restoredTurn[playerID] == turn then
    return
  end
  Civ5Ai_Apply._restoredTurn[playerID] = turn
  local player = Players[playerID]
  if player == nil then
    Civ5Ai_Apply._zeroedEndTurn[playerID] = nil
    return
  end
  local tracked = Civ5Ai_Apply._zeroedEndTurn[playerID] or {}
  local woken = 0
  local restored = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local id = Civ5Ai_Snapshot._UnitWireId(unit)
      local weZeroed = tracked[id] == true
      local hold = ActivityTypes ~= nil
        and unit.GetActivityType ~= nil
        and unit:GetActivityType() == ActivityTypes.ACTIVITY_HOLD
      if weZeroed or hold then
        if hold and unit.SetActivityType ~= nil and ActivityTypes.ACTIVITY_AWAKE ~= nil then
          unit:SetActivityType(ActivityTypes.ACTIVITY_AWAKE)
          woken = woken + 1
        end
        local moves = 0
        if unit.MovesLeft ~= nil then
          moves = unit:MovesLeft() or 0
        end
        if weZeroed and moves <= 0 and unit.SetMoves ~= nil and unit.MaxMoves ~= nil then
          unit:SetMoves(unit:MaxMoves())
          restored = restored + 1
        end
      end
    end
  end
  Civ5Ai_Apply._zeroedEndTurn[playerID] = nil
  if woken > 0 or restored > 0 then
    Civ5Ai_Util.Log(
      "apply|restore_local_human_units|player="
        .. tostring(playerID)
        .. "|turn="
        .. tostring(turn)
        .. "|woken="
        .. tostring(woken)
        .. "|moves="
        .. tostring(restored)
    )
  end
end

function Civ5Ai_Apply._IsManagedPlayer(playerID)
  return Civ5Ai_Config ~= nil and Civ5Ai_Config.IsManagedSeat(playerID)
end



function Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
  if playerID == nil or Game == nil then
    return false
  end
  if Game.Civ5AiClearUnitsEndTurnBlock == nil then
    return false
  end
  Game.Civ5AiClearUnitsEndTurnBlock(playerID)
  Civ5Ai_Util.Log(
    "apply|dll_clear_units_endturn|player="
      .. tostring(playerID)
      .. "|blocking="
      .. tostring(Civ5Ai_Apply._PlayerEndTurnBlocking(playerID))
  )
  return true
end

function Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  -- SP local human: raw unit:PushMission alone can leave DLL ReadyToMove set.
  -- Use _PushSelectedMission (select + PushMission + net SKIP). Do NOT call
  -- _FinishUnitMoves here — it calls this helper (recursion).
  local skip = Civ5Ai_Apply._Mission("MISSION_SKIP")
  local n = 0
  local forced = 0
  local localHuman = Civ5Ai_Apply._IsLocalHumanSeat(playerID)
  local prevSeat = Civ5Ai_Apply._applySeat
  if localHuman then
    Civ5Ai_Apply._applySeat = playerID
  end
  local function finishOne(unit)
    if unit == nil or skip == nil then
      return false
    end
    if Civ5Ai_Apply._PushSelectedMission ~= nil then
      Civ5Ai_Apply._PushSelectedMission(unit, skip, 0, 0, "MISSION_SKIP")
      return true
    end
    if unit.PushMission ~= nil then
      -- bManual=true (7th arg) for human seat reliability.
      unit:PushMission(skip, -1, -1, 0, 0, 1)
      return true
    end
    return false
  end
  if skip ~= nil then
    for unit in player:Units() do
      if unit ~= nil and not unit:IsDead() then
        local ready = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true
        local moves = 0
        if unit.MovesLeft ~= nil then
          moves = unit:MovesLeft() or 0
        end
        local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
        local busy = Civ5Ai_Apply._UnitIsBusyMoving(unit)
        if (ready or moves > 0) and not auto and not busy then
          if finishOne(unit) then
            n = n + 1
          end
        end
      end
    end
  end
  if player.EndTurnsForReadyUnits ~= nil then
    player:EndTurnsForReadyUnits(false)
  end
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._UnitsStillBlocking(blocking) then
    for unit in player:Units() do
      if unit ~= nil and not unit:IsDead() then
        local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
        local busy = Civ5Ai_Apply._UnitIsBusyMoving(unit)
        if not auto and not busy then
          if finishOne(unit) then
            forced = forced + 1
          end
        end
      end
    end
    if player.EndTurnsForReadyUnits ~= nil then
      player:EndTurnsForReadyUnits(false)
    end
  end
  -- After select+PushMission+net, also force activity HOLD / moves 0 on the
  -- DLL for local human leftovers that still look ready (net may lag a tick).
  if localHuman and Civ5Ai_Apply._UnitsStillBlocking(Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)) then
    for unit in player:Units() do
      if unit ~= nil and not unit:IsDead() then
        local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
        local busy = Civ5Ai_Apply._UnitIsBusyMoving(unit)
        if not auto and not busy then
          if ActivityTypes ~= nil and unit.SetActivityType ~= nil then
            unit:SetActivityType(ActivityTypes.ACTIVITY_HOLD)
          end
          if unit.SetMoves ~= nil then
            unit:SetMoves(0)
          end
        end
      end
    end
    if player.EndTurnsForReadyUnits ~= nil then
      player:EndTurnsForReadyUnits(false)
    end
  end
  if prevSeat ~= nil then
    Civ5Ai_Apply._applySeat = prevSeat
  elseif localHuman then
    Civ5Ai_Apply._applySeat = nil
  end
  if Civ5Ai_Apply._UnitsStillBlocking(Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)) then
    Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
  end
  Civ5Ai_Util.Log(
    "apply|endturns_for_ready|player="
      .. tostring(playerID)
      .. "|linked_only=false|push_skip="
      .. tostring(n)
      .. "|force_skip="
      .. tostring(forced)
      .. "|local_human="
      .. tostring(localHuman)
      .. "|blocking_after="
      .. tostring(Civ5Ai_Apply._PlayerEndTurnBlocking(playerID))
  )
  return true
end

function Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local any = false
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      any = true
      local moves = 0
      if unit.MovesLeft ~= nil then
        moves = unit:MovesLeft() or 0
      end
      if moves > 0 then
        return false
      end
      if unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true then
        return false
      end
      if Civ5Ai_Apply._UnitIsBusyMoving(unit) then
        return false
      end
    end
  end
  return any
end


function Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking(playerID)
  -- When every unit looks finished but GetEndTurnBlockingType stays UNITS,
  -- remove the blocking notification once and dirty end-turn state (same
  -- pattern as production ack). Do not StopUnitAutomation (re-opens UNITS).
  if playerID == nil then
    return false
  end
  if not Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) then
    return false
  end
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if not Civ5Ai_Apply._UnitsStillBlocking(blocking) then
    return true
  end
  local prevSeat = Civ5Ai_Apply._applySeat
  if Civ5Ai_Apply._IsLocalHumanSeat(playerID) then
    Civ5Ai_Apply._applySeat = playerID
  end
  local skip = Civ5Ai_Apply._Mission("MISSION_SKIP")
  local nHold = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
      local busy = Civ5Ai_Apply._UnitIsBusyMoving(unit)
      if not auto and not busy then
        if skip ~= nil and Civ5Ai_Apply._PushSelectedMission ~= nil then
          Civ5Ai_Apply._PushSelectedMission(unit, skip, 0, 0, "MISSION_SKIP")
        end
        if ActivityTypes ~= nil and unit.SetActivityType ~= nil then
          unit:SetActivityType(ActivityTypes.ACTIVITY_HOLD)
        end
        if unit.SetMoves ~= nil then
          unit:SetMoves(0)
        end
        nHold = nHold + 1
      end
    end
  end
  Civ5Ai_Util.Log(
    "apply|ack_phantom_hold_zero|player="
      .. tostring(playerID)
      .. "|n="
      .. tostring(nHold)
  )
  if Civ5Ai_Apply._EndTurnsForReadyUnits ~= nil then
    Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
  elseif player.EndTurnsForReadyUnits ~= nil then
    player:EndTurnsForReadyUnits(false)
  end
  if prevSeat ~= nil then
    Civ5Ai_Apply._applySeat = prevSeat
  end
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn() or 0
  end
  Civ5Ai_Apply._unitsNotifyRemoved = Civ5Ai_Apply._unitsNotifyRemoved or {}
  local notifyKey = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._unitsNotifyRemoved[notifyKey] ~= true
      and player.GetEndTurnBlockingNotificationIndex ~= nil
      and UI ~= nil
      and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
      Civ5Ai_Apply._unitsNotifyRemoved[notifyKey] = true
      Civ5Ai_Util.Log(
        "apply|ack_phantom_units|player="
          .. tostring(playerID)
          .. "|removed_notification="
          .. tostring(idx)
      )
    end
  end
  if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
    Events.SerialEventEndTurnDirty()
  end
  if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
    Events.SerialEventGameDataDirty()
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local cleared = Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
  Civ5Ai_Util.Log(
    "apply|ack_phantom_units|player="
      .. tostring(playerID)
      .. "|blocking="
      .. tostring(blocking)
      .. "|cleared="
      .. tostring(cleared)
  )
  return cleared
end

function Civ5Ai_Apply._UnitsStillBlocking(blocking)
  local t = EndTurnBlockingTypes
  if t == nil then
    return false
  end
  return blocking == t.ENDTURN_BLOCKING_UNITS
    or blocking == t.ENDTURN_BLOCKING_STACKED_UNITS
    or blocking == t.ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS
end

function Civ5Ai_Apply._IsEndTurnClear(blocking)
  local t = EndTurnBlockingTypes
  if t == nil then
    return blocking == 0 or blocking == nil
  end
  return blocking == t.NO_ENDTURN_BLOCKING_TYPE
end

function Civ5Ai_Apply.ResolveEndTurnBlocking(playerID, blocking)
  if playerID == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  if t == nil then
    Civ5Ai_Apply.ResolveCityProduction(playerID)
    Civ5Ai_Apply.ResolveResearch(playerID)
    return true
  end
  if blocking == t.ENDTURN_BLOCKING_PRODUCTION then
    Civ5Ai_Apply.ResolveCityProduction(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_RESEARCH
    or blocking == t.ENDTURN_BLOCKING_FREE_TECH
    or blocking == t.ENDTURN_BLOCKING_STEAL_TECH then
    Civ5Ai_Apply.ResolveResearch(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_POLICY
    or blocking == t.ENDTURN_BLOCKING_FREE_POLICY then
    Civ5Ai_Apply.ResolvePolicies(playerID)
    if Civ5Ai_Apply._AcknowledgePolicyBlocking ~= nil then
      Civ5Ai_Apply._AcknowledgePolicyBlocking(playerID)
    end
  elseif blocking == t.ENDTURN_BLOCKING_FOUND_PANTHEON then
    Civ5Ai_Apply.ResolvePantheon(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_FOUND_RELIGION then
    Civ5Ai_Apply.ResolveFoundReligion(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_ENHANCE_RELIGION then
    Civ5Ai_Apply.ResolveEnhanceReligion(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF then
    Civ5Ai_Apply.ResolveReformationBelief(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_FREE_ITEMS
    or blocking == t.ENDTURN_BLOCKING_FAITH_GREAT_PERSON then
    Civ5Ai_Apply.ResolveFreeGreatPerson(playerID)
  elseif blocking == t.ENDTURN_BLOCKING_UNIT_PROMOTION then
    -- Live t44: promote_unit applied OK but ENDTURN_BLOCKING_UNIT_PROMOTION
    -- (blocking=9) stayed asserted with zero IsPromotionReady units (phantom).
    Civ5Ai_Apply.ResolvePromotions(playerID)
    Civ5Ai_Apply._AcknowledgePromotionBlocking(playerID)
  elseif Civ5Ai_Apply._UnitsStillBlocking(blocking) then
    local localHuman = Civ5Ai_Seats ~= nil
      and Civ5Ai_Seats.IsActiveLocalPlayer ~= nil
      and Civ5Ai_Seats.IsActiveLocalPlayer(playerID) == true
    Civ5Ai_Apply.ResolvePolicies(playerID)
    if localHuman and Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil then
      Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, true)
    elseif Civ5Ai_Seats ~= nil and Civ5Ai_Seats.UsesCpLimitedFallback(playerID) then
      Civ5Ai_Apply.ResolveCpLimitedFallback(playerID)
    else
      Civ5Ai_Apply.ResolveRemainingOrders(playerID)
    end
  else
    Civ5Ai_Apply.ResolveRemainingOrders(playerID)
  end
  return true
end

function Civ5Ai_Apply._LogUnitEndTurnBlockDiagOnce(playerID)
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn() or 0
  end
  Civ5Ai_Apply._unitBlockDiagLogged = Civ5Ai_Apply._unitBlockDiagLogged or {}
  local key = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._unitBlockDiagLogged[key] then
    return
  end
  Civ5Ai_Apply._unitBlockDiagLogged[key] = true
  local player = Players[playerID]
  if player == nil then
    return
  end
  local parts = {}
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local moves = 0
      if unit.MovesLeft ~= nil then
        moves = unit:MovesLeft() or 0
      end
      local ready = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true
      local act = nil
      if unit.GetActivityType ~= nil then
        act = unit:GetActivityType()
      end
      local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
      local uid = Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._UnitWireId ~= nil
        and Civ5Ai_Snapshot._UnitWireId(unit)
        or tostring(unit:GetID())
      table.insert(
        parts,
        tostring(uid)
          .. ":moves="
          .. tostring(moves)
          .. ":ready="
          .. tostring(ready)
          .. ":act="
          .. tostring(act)
          .. ":auto="
          .. tostring(auto)
      )
    end
  end
  local body = "none"
  if #parts > 0 then
    body = table.concat(parts, ",")
  end
  Civ5Ai_Util.Log(
    "apply|unit_endturn_block_diag|player="
      .. tostring(playerID)
      .. "|turn="
      .. tostring(turn)
      .. "|units="
      .. body
  )
end

function Civ5Ai_Apply._SkipIdleUnitsForEngineBlock(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local prevSeat = Civ5Ai_Apply._applySeat
  if Civ5Ai_Apply._IsLocalHumanSeat(playerID) then
    Civ5Ai_Apply._applySeat = playerID
  end
  local n = 0
  local cleared = 0
  local targeted = 0
  local function _StuckAutoNeedsFinish(unit)
    if unit == nil or unit.IsAutomated == nil or unit:IsAutomated() ~= true then
      return false
    end
    -- Do not cancel non-auto in-flight LLM missions; only stuck automation.
    local act = nil
    if unit.GetActivityType ~= nil then
      act = unit:GetActivityType()
    end
    if ActivityTypes == nil then
      return false
    end
    if ActivityTypes.ACTIVITY_MISSION ~= nil and act == ActivityTypes.ACTIVITY_MISSION then
      return true
    end
    if ActivityTypes.ACTIVITY_AWAKE ~= nil and act == ActivityTypes.ACTIVITY_AWAKE then
      return true
    end
    return false
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local automated = unit.IsAutomated ~= nil and unit:IsAutomated()
      if automated and not _StuckAutoNeedsFinish(unit) then
        -- Sleep/heal/sentry auto: leave alone.
      elseif not Civ5Ai_Apply._UnitIsBusyMoving(unit) then
        local moves = 0
        if unit.MovesLeft ~= nil then
          moves = unit:MovesLeft() or 0
        end
        local ready = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true
        local needs = Civ5Ai_Snapshot ~= nil
          and Civ5Ai_Snapshot._UnitNeedsOrders ~= nil
          and Civ5Ai_Snapshot._UnitNeedsOrders(unit) == true
        local stuckAuto = _StuckAutoNeedsFinish(unit)
        -- Prefer units that still show moves/ready/needs, plus stuck auto.
        if moves > 0 or ready or needs or stuckAuto then
          targeted = targeted + 1
          local ok = Civ5Ai_Apply._FinishUnitMoves(unit)
          n = n + 1
          if ok then
            cleared = cleared + 1
          end
        end
      end
    end
  end
  -- Phantom engine block: MovesLeft/Ready all clear but ENDTURN_BLOCKING_UNITS
  -- still set. Finish every non-busy idle unit once (incl. stuck auto).
  if targeted == 0 then
    if Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
      Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
    end
    for unit in player:Units() do
      if unit ~= nil and not unit:IsDead() then
        local automated = unit.IsAutomated ~= nil and unit:IsAutomated()
        if automated and not _StuckAutoNeedsFinish(unit) then
        elseif not Civ5Ai_Apply._UnitIsBusyMoving(unit) then
          local ok = Civ5Ai_Apply._FinishUnitMoves(unit)
          n = n + 1
          if ok then
            cleared = cleared + 1
          end
        end
      end
    end
  end
  local now = (os and os.clock and os.clock()) or 0
  Civ5Ai_Apply._skipIdleLogAt = Civ5Ai_Apply._skipIdleLogAt or {}
  local last = Civ5Ai_Apply._skipIdleLogAt[playerID]
  if n > 0 and (last == nil or (now - last) >= 2.0) then
    Civ5Ai_Apply._skipIdleLogAt[playerID] = now
    Civ5Ai_Util.Log(
      "apply|skip_idle_engine_block|player="
        .. tostring(playerID)
        .. "|finished="
        .. tostring(n)
        .. "|cleared="
        .. tostring(cleared)
        .. "|targeted="
        .. tostring(targeted)
    )
  end
  local playerObj = Players[playerID]
  Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._UnitsStillBlocking(blocking) then
    Civ5Ai_Apply._LogUnitEndTurnBlockDiagOnce(playerID)
    if Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking ~= nil then
      Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking(playerID)
      blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    end
  end
  if prevSeat ~= nil then
    Civ5Ai_Apply._applySeat = prevSeat
  end
  return n
end

function Civ5Ai_Apply.SkipUnorderedUnits(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local finished = 0
  for unit in player:Units() do
    if Civ5Ai_Apply._IsUnorderedBlockingUnit(playerID, unit) then
      Civ5Ai_Apply._FinishUnitMoves(unit)
      finished = finished + 1
    end
  end
  if finished > 0 then
    Civ5Ai_Util.Log(
      "apply|skip_unordered|player="
        .. tostring(playerID)
        .. "|finished="
        .. tostring(finished)
    )
  end
  return true
end

-- Drain short-move leftover MovesLeft from _pendingSkipRemaining.
-- SkipUnorderedUnits alone missed ordered leftovers because _UnitWasOrdered
-- excluded them; call this after moves settle and before CONTROL_ENDTURN.
function Civ5Ai_Apply.SkipPendingRemainingMoves(playerID)
  local bucket = Civ5Ai_Apply._pendingSkipRemaining[playerID]
  if bucket == nil then
    return 0
  end
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local finished = 0
  local clearIds = {}
  for unitId, queued in pairs(bucket) do
    if queued == true then
      local unit = Civ5Ai_Apply._FindUnit(playerID, unitId)
      if unit == nil or unit:IsDead() then
        table.insert(clearIds, unitId)
      elseif Civ5Ai_Apply._UnitIsBusyMoving(unit) then
        -- Wait until the short move settles before skipping leftovers.
      elseif Civ5Ai_Apply._UnitSkipRemainingQueued(playerID, unitId) then
        local movesBefore = 0
        if unit.MovesLeft ~= nil then
          movesBefore = unit:MovesLeft() or 0
        end
        Civ5Ai_Apply._FinishUnitMoves(unit)
        local movesAfter = 0
        if unit.MovesLeft ~= nil then
          movesAfter = unit:MovesLeft() or 0
        end
        Civ5Ai_Util.Log(
          "apply|skip_remaining|unit="
            .. tostring(unitId)
            .. "|moves_before="
            .. tostring(movesBefore)
            .. "|moves_after="
            .. tostring(movesAfter)
        )
        finished = finished + 1
        table.insert(clearIds, unitId)
      end
    end
  end
  for _, unitId in ipairs(clearIds) do
    bucket[unitId] = nil
  end
  return finished
end


-- Called only after end-turn failed because units still need orders.
function Civ5Ai_Apply._FinishAllReadyUnits(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  -- DLL helper the AI uses to flush ReadyToMove units for end-turn.
  -- Lua EndTurnsForReadyUnits(bLinkedOnly): ALWAYS nets SKIP. Arg true =
  -- linked-followers only (skips normal ready units). Must pass false/nil.
  Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
  Civ5Ai_Apply.SkipUnorderedUnits(playerID)
  if Civ5Ai_Apply._FinishAllUnitsWithMoves ~= nil then
    Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
  end
  Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
  return true
end

function Civ5Ai_Apply.ClearManagedSeatEndTurnBlocking(playerID)
  if playerID == nil then
    return false
  end
  return Civ5Ai_Apply._WithActivePlayer(playerID, function()
    Civ5Ai_Apply._applySeat = playerID
    if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
      Civ5Ai_Autotest._ReleaseUiFocus()
    end
    Civ5Ai_Apply._DismissBlockingPopups(true)
    for _ = 1, 8 do
      local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
      if Civ5Ai_Apply._IsEndTurnClear(blocking) then
        break
      end
      if blocking == -1 then
        Civ5Ai_Apply.ResolveRemainingOrders(playerID)
        Civ5Ai_Apply._DismissBlockingPopups(true)
        if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
          Civ5Ai_Autotest._ReleaseUiFocus()
        end
        break
      end
      Civ5Ai_Apply.ResolveEndTurnBlocking(playerID, blocking)
    end
    Civ5Ai_Apply._DismissBlockingPopups(true)
    local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    if not Civ5Ai_Apply._IsEndTurnClear(blocking) then
      Civ5Ai_Apply.ResolveEndTurnBlocking(playerID, blocking)
      blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    end
    local cityCount = Civ5Ai_Apply._PlayerCityCount(playerID)
    Civ5Ai_Apply._PrepareSeatForNativeFinish(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    -- Engine can report ENDTURN_BLOCKING_UNITS with zero ReadyToMove/MovesLeft
    -- (live P0 t23: units=none, blocking=3). Our needs-orders heuristic then
    -- skips nobody and CONTROL_ENDTURN never succeeds. Skip every idle unit.
    if Civ5Ai_Apply._UnitsStillBlocking(blocking) then
      Civ5Ai_Apply._SkipIdleUnitsForEngineBlock(playerID)
      blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    end
    local nowClear = (os and os.clock and os.clock()) or 0
    Civ5Ai_Apply._clearSeatLogAt = Civ5Ai_Apply._clearSeatLogAt or {}
    local lastClear = Civ5Ai_Apply._clearSeatLogAt[playerID]
    if lastClear == nil or (nowClear - lastClear) >= 2.0 then
      Civ5Ai_Apply._clearSeatLogAt[playerID] = nowClear
      Civ5Ai_Util.Log(
        "apply|clear_seat_blocking|player="
          .. tostring(playerID)
          .. "|blocking="
          .. tostring(blocking)
          .. "|cities="
          .. tostring(cityCount)
      )
    end
    return Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
  end)
end

function Civ5Ai_Apply._PrepareSeatForNativeFinish(playerID)
  Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  Civ5Ai_Apply._AcknowledgeGoodyHutAnnounce(playerID)
  Civ5Ai_Apply.ResolveResearch(playerID)
  Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
  -- Do not StopUnitAutomation: COMMAND_STOP_AUTOMATION re-opens
  -- ENDTURN_BLOCKING_UNITS and CONTROL_ENDTURN never succeeds.
end

function Civ5Ai_Apply.ResolveRemainingOrders(playerID)
  if Civ5Ai_Seats == nil or not Civ5Ai_Seats.UsesFullLlmControl(playerID) then
    return false
  end
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
    Civ5Ai_Autotest._ReleaseUiFocus()
  end
  -- Goody announce / tech / production popups steal UI focus. CONTROL_ENDTURN
  -- then returns true with blocking -1 and the turn never actually ends.
  Civ5Ai_Apply._DismissBlockingPopups()
  Civ5Ai_Apply.ResolvePromotions(playerID)
  Civ5Ai_Apply.ResolveMayaBonus(playerID)
  Civ5Ai_Apply.ResolveFreeGreatPerson(playerID)
  Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  Civ5Ai_Apply.ResolvePolicies(playerID)
  Civ5Ai_Apply.ResolveFaithBlockers(playerID)
  Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  Civ5Ai_Apply.ResolveCityProduction(playerID)
  Civ5Ai_Apply.ResolveResearch(playerID)
  Civ5Ai_Apply.SkipUnorderedUnits(playerID)
  Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
  return true
end

-- CP limited fallback: unordered units (via native release). Empty-city
-- production only when the empire has 15+ cities. No research, policy, or faith autofill.
function Civ5Ai_Apply.ResolveCpLimitedFallback(playerID)
  if Civ5Ai_Seats == nil or not Civ5Ai_Seats.UsesCpLimitedFallback(playerID) then
    return false
  end
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
    Civ5Ai_Autotest._ReleaseUiFocus()
  end
  Civ5Ai_Apply._DismissBlockingPopups()
  Civ5Ai_Apply.ResolvePromotions(playerID)
  Civ5Ai_Apply.ResolveMayaBonus(playerID)
  Civ5Ai_Apply.ResolveFreeGreatPerson(playerID)
  Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  Civ5Ai_Apply.ResolveCityProduction(playerID)
  Civ5Ai_Apply.SkipUnorderedUnits(playerID)
  Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
  return true
end

function Civ5Ai_Apply._LookupControl(path)
  if path == nil then
    return nil
  end
  -- Absolute paths: global LookUpControl, same as EUI NotificationPanel.
  -- ContextPtr:LookUpControl("/LeaderHeadRoot") from InGame can miss the
  -- EUI root or hit a hidden InGame child and never fall through.
  if string.sub(path, 1, 1) == "/" and LookUpControl ~= nil then
    local ctx = LookUpControl(path)
    if ctx ~= nil then
      return ctx
    end
  end
  if ContextPtr ~= nil and ContextPtr.LookUpControl ~= nil then
    local ctx = ContextPtr:LookUpControl(path)
    if ctx ~= nil then
      return ctx
    end
  end
  if LookUpControl ~= nil then
    return LookUpControl(path)
  end
  return nil
end

function Civ5Ai_Apply._ControlVisible(path)
  local ctx = Civ5Ai_Apply._LookupControl(path)
  return ctx ~= nil and ctx.IsHidden ~= nil and not ctx:IsHidden()
end

Civ5Ai_Apply._LEADER_HEAD_PATHS = {
  "/LeaderHeadRoot",
  "/InGame/LeaderHeadRoot",
}

function Civ5Ai_Apply._LeaderHeadContext()
  -- DiplomacyUIAddin lives under the queued LeaderHead. That ContextPtr is
  -- the one Goodbye dequeues; LookUpControl from InGame can miss it.
  local host = ExposedMembers ~= nil and ExposedMembers.Civ5Ai or nil
  if host ~= nil and host.LeaderHeadRoot ~= nil then
    local ctx = host.LeaderHeadRoot
    if ctx.IsHidden ~= nil and not ctx:IsHidden() then
      return ctx, "addin"
    end
  end
  -- Only the root context. Goodbye/BackButton stay unhidden in XML even
  -- when LeaderHead is not queued, so child IsHidden is not a show signal.
  for _, path in ipairs(Civ5Ai_Apply._LEADER_HEAD_PATHS) do
    if Civ5Ai_Apply._ControlVisible(path) then
      return Civ5Ai_Apply._LookupControl(path), path
    end
  end
  return nil, nil
end

function Civ5Ai_Apply._LeaderHeadShowing()
  if UI ~= nil and UI.GetLeaderHeadRootUp ~= nil and UI.GetLeaderHeadRootUp() then
    return true
  end
  local _, path = Civ5Ai_Apply._LeaderHeadContext()
  return path ~= nil
end

function Civ5Ai_Apply._DismissPopupType(popupType, choice)
  if Events == nil
    or Events.SerialEventGameMessagePopupProcessed == nil
    or popupType == nil then
    return
  end
  Events.SerialEventGameMessagePopupProcessed.CallImmediate(popupType, choice or 0)
end

function Civ5Ai_Apply._InfoPopupType(popupName)
  if ButtonPopupTypes == nil or popupName == nil then
    return nil
  end
  return ButtonPopupTypes[popupName]
end

function Civ5Ai_Apply._ShouldAutoDismissInfoPopups()
  if Civ5Ai_Config == nil or Game == nil then
    return false
  end
  return Civ5Ai_Config.IsManagedSeat(Game.GetActivePlayer())
end

function Civ5Ai_Apply._DismissInfoPopup(path, popupType, reason, choice)
  Civ5Ai_Apply._DequeuePopupPath(path)
  Civ5Ai_Apply._DismissPopupType(popupType, choice)
  if reason ~= nil then
    Civ5Ai_Util.Log("apply|dismiss_info_popup|" .. tostring(reason))
  end
end

function Civ5Ai_Apply._OnAdvisorCombatPopup(popupInfo)
  if popupInfo == nil or ButtonPopupTypes == nil then
    return false
  end
  local popupType = ButtonPopupTypes.BUTTONPOPUP_ADVISOR_INFO
  if popupType == nil or popupInfo.Type ~= popupType then
    return false
  end
  if not Civ5Ai_Apply._ShouldAutoDismissInfoPopups() then
    return false
  end
  local choice = 0
  local reason = "advisor_reconsider"
  if Civ5Ai_Apply._applySeat ~= nil then
    choice = 1
    reason = "advisor_attack_anyway"
  end
  Civ5Ai_Apply._DismissInfoPopup("/InGame/AdvisorInfoPopup", popupType, reason, choice)
  return true
end

function Civ5Ai_Apply._OnInfoPopupShown(popupInfo)
  if popupInfo == nil or not Civ5Ai_Apply._ShouldAutoDismissInfoPopups() then
    return
  end
  if Civ5Ai_Apply._OnAdvisorCombatPopup(popupInfo) then
    return
  end
  for _, spec in ipairs(Civ5Ai_Apply._INFO_POPUP_SPECS) do
    local popupType = Civ5Ai_Apply._InfoPopupType(spec.popup)
    if popupType ~= nil and popupInfo.Type == popupType then
      Civ5Ai_Apply._DismissInfoPopup(spec.path, popupType, spec.popup)
      return
    end
  end
end

function Civ5Ai_Apply._DequeuePopupPath(path)
  if UIManager == nil then
    return
  end
  local ctx = Civ5Ai_Apply._LookupControl(path)
  if ctx == nil then
    return
  end
  if ctx.IsHidden ~= nil and not ctx:IsHidden() then
    Civ5Ai_Util.Log("apply|dequeue_popup|" .. tostring(path))
  end
  UIManager:DequeuePopup(ctx)
end

function Civ5Ai_Apply._DismissLeaderHead()
  -- Same close as EUI Goodbye / ForceLeaveLeader: dequeue the queued context,
  -- clear LeaderHeadRootUp, then RequestLeaveLeader. The DiplomacyUIAddin
  -- supplies that context; LeavingLeaderViewMode runs DoLeaveLeader there.
  local ctx, path = Civ5Ai_Apply._LeaderHeadContext()
  local leaderUp = UI ~= nil and UI.GetLeaderHeadRootUp ~= nil and UI.GetLeaderHeadRootUp()
  if ctx == nil and path == nil and not leaderUp then
    return
  end
  Civ5Ai_Util.Log("apply|dismiss_leader|" .. tostring(path or "root_up"))
  -- Same order as EUI Goodbye / ForceLeaveLeader.
  if ctx ~= nil and UIManager ~= nil then
    UIManager:DequeuePopup(ctx)
  end
  if UI ~= nil then
    if UI.SetLeaderHeadRootUp ~= nil then
      UI.SetLeaderHeadRootUp(false)
    end
    if UI.RequestLeaveLeader ~= nil then
      UI.RequestLeaveLeader()
    end
  end
  -- Runs LeaderHeadRoot's DoLeaveLeader in that Lua state (correct ContextPtr).
  if Events ~= nil and Events.LeavingLeaderViewMode ~= nil then
    Events.LeavingLeaderViewMode()
  end
end

function Civ5Ai_Apply._GoodyHutChoicePopup()
  return Civ5Ai_Apply._LookupControl("/InGame/ChooseGoodyHutRewardPopup")
end

function Civ5Ai_Apply._GoodyHutChoicePopupOpen()
  local ctx = Civ5Ai_Apply._GoodyHutChoicePopup()
  return ctx ~= nil and ctx.IsHidden ~= nil and not ctx:IsHidden()
end

function Civ5Ai_Apply._HideGoodyHutChoicePopup()
  local ctx = Civ5Ai_Apply._GoodyHutChoicePopup()
  if ctx ~= nil and ctx.SetHide ~= nil then
    ctx:SetHide(true)
  end
end

function Civ5Ai_Apply._FindGoodyChoiceUnit(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local promo = nil
  if GameInfo ~= nil and GameInfo.UnitPromotions ~= nil then
    promo = GameInfo.UnitPromotions["PROMOTION_GOODY_HUT_PICKER"]
  end
  if UI ~= nil and UI.GetHeadSelectedUnit ~= nil then
    local selected = UI.GetHeadSelectedUnit()
    if selected ~= nil and selected.GetOwner ~= nil and selected:GetOwner() == playerID then
      if promo == nil or (selected.IsHasPromotion ~= nil and selected:IsHasPromotion(promo.ID)) then
        return selected
      end
    end
  end
  if promo == nil then
    return nil
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and unit.IsHasPromotion ~= nil and unit:IsHasPromotion(promo.ID) then
      return unit
    end
  end
  return nil
end

function Civ5Ai_Apply.ResolveGoodyHutBonus(playerID)
  if not Civ5Ai_Apply._GoodyHutChoicePopupOpen() then
    return false
  end
  if Network == nil or Network.SendGoodyChoice == nil then
    return false
  end
  local player = Players[playerID]
  if player == nil or player.CanGetGoody == nil then
    return false
  end
  local unit = Civ5Ai_Apply._FindGoodyChoiceUnit(playerID)
  if unit == nil or unit.GetPlot == nil then
    return false
  end
  local plot = unit:GetPlot()
  if plot == nil then
    return false
  end
  for row in GameInfo.GoodyHuts() do
    if player:CanGetGoody(plot, row.ID, unit) then
      Network.SendGoodyChoice(playerID, plot:GetX(), plot:GetY(), row.ID, unit:GetID())
      -- Same close as ChooseGoodyHutReward ConfirmButton. DequeuePopup does
      -- not hide this screen; leaving it up makes CanGetGoody keep paying.
      Civ5Ai_Apply._HideGoodyHutChoicePopup()
      Civ5Ai_Util.Log(
        "apply|goody_choice|player="
          .. tostring(playerID)
          .. "|unit="
          .. tostring(unit:GetID())
          .. "|goody="
          .. tostring(row.Type)
      )
      return true
    end
  end
  return false
end

function Civ5Ai_Apply._AcknowledgeGoodyHutAnnounce(playerID)
  if not Civ5Ai_Apply._ControlVisible("/InGame/GoodyHutPopup") then
    return false
  end
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_GOODY_HUT_REWARD)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/GoodyHutPopup")
  Civ5Ai_Util.Log("apply|goody_announce|player=" .. tostring(playerID))
  return true
end

function Civ5Ai_Apply._DismissBlockingPopups(force)
  local now = (os and os.clock and os.clock()) or 0
  local leaderUp = Civ5Ai_Apply._LeaderHeadShowing()
  if (leaderUp or Civ5Ai_Diplo._TradeUiShowing())
    and Civ5Ai_Diplo ~= nil
    and Civ5Ai_Diplo.HandleLeaderTradeBlocker ~= nil then
    Civ5Ai_Diplo.HandleLeaderTradeBlocker(Game.GetActivePlayer())
  end
  -- First-meet queues LeaderHead after apply/end-turn already dismissed.
  -- Do not let the 0.4s coalescer skip that close.
  if not force and Civ5Ai_Apply._lastDismissAt ~= nil and (now - Civ5Ai_Apply._lastDismissAt) < 0.4 then
    return
  end
  Civ5Ai_Apply._lastDismissAt = now
  -- Dequeue first. GoodyHutPopup's hide handler fires Processed; calling
  -- Processed while the panel is still up leaves the UI on screen and
  -- CONTROL_ENDTURN no-ops with blocking -1.
  -- Do not SendGoodyChoice here: that grants a bonus. The Shoshone picker
  -- stays legal after one pick, so a dismiss pump would farm gold.
  -- ChooseGoodyHutReward is closed by ResolveGoodyHutBonus (SetHide), not dequeue.
  local paths = {
    "/InGame/GoodyHutPopup",
    "/InGame/TechAwardPopup",
    "/InGame/TechPopup",
    "/InGame/TechTree",
    "/InGame/NewEraPopup",
    "/InGame/ProductionPopup",
    "/InGame/ChooseProductionPopup",
    "/InGame/ResearchChooserPopup",
    "/InGame/ChooseTechPopup",
    "/InGame/CityStateDiploPopup",
    "/InGame/CityStateGreetingPopup",
    "/InGame/NaturalWonderPopup",
    "/InGame/BarbarianCampPopup",
    "/InGame/GoldenAgePopup",
    "/InGame/GreatPersonRewardPopup",
    "/InGame/WhosWinningPopup",
    "/InGame/WonderPopup",
    "/InGame/TextPopup",
    "/InGame/VoteResultsPopup",
    "/InGame/AdvisorCounselPopup",
    "/InGame/AdvisorModal",
    "/InGame/GenericPopup",
    "/InGame/DeclareWarPopup",
    "/InGame/SocialPolicyPopup",
    "/InGame/ChoosePantheonPopup",
    "/InGame/ChooseReligionPopup",
    "/LeaderHeadRoot",
    "/LeaderHeadRoot/DiploTrade",
    "/LeaderHeadRoot/DiscussionDialog",
    "/InGame/LeaderHeadRoot",
    "/InGame/DiploCorner/SimpleDiplo",
    "/InGame/WorldView/SimpleDiploTrade",
  }
  for _, path in ipairs(paths) do
    Civ5Ai_Apply._DequeuePopupPath(path)
  end
  Civ5Ai_Apply._DismissLeaderHead()
  if ButtonPopupTypes ~= nil then
    if Civ5Ai_Apply._applySeat == nil and ButtonPopupTypes.BUTTONPOPUP_ADVISOR_INFO ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_ADVISOR_INFO, 0)
    end
    local types = {
      ButtonPopupTypes.BUTTONPOPUP_CHOOSETECH,
      ButtonPopupTypes.BUTTONPOPUP_CHOOSE_TECH_TO_STEAL,
      ButtonPopupTypes.BUTTONPOPUP_TECH_AWARD,
      ButtonPopupTypes.BUTTONPOPUP_TECH_TREE,
      ButtonPopupTypes.BUTTONPOPUP_NEW_ERA,
      ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION,
      ButtonPopupTypes.BUTTONPOPUP_CHOOSEPOLICY,
      ButtonPopupTypes.BUTTONPOPUP_FOUND_PANTHEON,
      ButtonPopupTypes.BUTTONPOPUP_FOUND_RELIGION,
      ButtonPopupTypes.BUTTONPOPUP_DIPLOMACY,
      ButtonPopupTypes.BUTTONPOPUP_DIPLOMATIC_OVERVIEW,
      ButtonPopupTypes.BUTTONPOPUP_CITY_STATE_GREETING,
      ButtonPopupTypes.BUTTONPOPUP_MINOR_CIV_GREETING_AND_WAR,
      ButtonPopupTypes.BUTTONPOPUP_DECLAREWARMOVE,
      ButtonPopupTypes.BUTTONPOPUP_DECLAREWARRANGESTRIKE,
      ButtonPopupTypes.BUTTONPOPUP_GOODY_HUT_REWARD,
      ButtonPopupTypes.BUTTONPOPUP_NATURAL_WONDER_REWARD,
      ButtonPopupTypes.BUTTONPOPUP_BARBARIAN_CAMP_REWARD,
      ButtonPopupTypes.BUTTONPOPUP_GOLDEN_AGE_REWARD,
      ButtonPopupTypes.BUTTONPOPUP_GREAT_PERSON_REWARD,
    }
    for _, popupType in ipairs(types) do
      Civ5Ai_Apply._DismissPopupType(popupType)
    end
    for _, spec in ipairs(Civ5Ai_Apply._INFO_POPUP_SPECS) do
      local popupType = Civ5Ai_Apply._InfoPopupType(spec.popup)
      if popupType ~= nil then
        Civ5Ai_Apply._DismissPopupType(popupType)
      end
    end
  end
end

function Civ5Ai_Apply._DismissPolicyPopup()
  Civ5Ai_Apply._DismissBlockingPopups()
end

function Civ5Ai_Apply._PrepareUnitSelection(unit)
  if not Civ5Ai_Apply._UsesUiApply() then
    return
  end
  if UI ~= nil then
    if UI.IsCityScreenUp ~= nil and UI.IsCityScreenUp() then
      if UI.SetCityScreenUp ~= nil then
        UI.SetCityScreenUp(false)
      end
    end
    if UI.ClearSelectedCities ~= nil then
      UI.ClearSelectedCities()
    end
    if Events ~= nil and Events.SerialEventExitCityScreen ~= nil then
      Events.SerialEventExitCityScreen()
    end
    if UI.SetInterfaceMode ~= nil and InterfaceModeTypes ~= nil then
      UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION)
    end
    if UI.SelectUnit ~= nil then
      UI.SelectUnit(unit)
    end
  end
end

function Civ5Ai_Apply._HandleActionByType(unit, typeName)
  if not Civ5Ai_Apply._UsesUiApply() then
    return false
  end
  if unit == nil or typeName == nil or Game == nil or Game.HandleAction == nil then
    return false
  end
  Civ5Ai_Apply._PrepareUnitSelection(unit)
  local plot = Civ5Ai_Apply._UnitPlot(unit)
  -- Unit panel clicks GameInfoActions[actionID], not GameInfo.Actions().
  -- Automate / skip live there; GameInfo.Actions() often has no such rows.
  if GameInfoActions ~= nil then
    for actionID = 0, #GameInfoActions do
      local action = GameInfoActions[actionID]
      if action ~= nil and action.Type == typeName then
        if Game.CanHandleAction == nil or Game.CanHandleAction(actionID, plot, true) then
          Game.HandleAction(actionID)
          return true
        end
      end
    end
  end
  if GameInfo == nil or GameInfo.Actions == nil then
    return false
  end
  for row in GameInfo.Actions() do
    if row ~= nil and row.Type == typeName and row.ID ~= nil then
      if Game.CanHandleAction == nil or Game.CanHandleAction(row.ID, plot, false) then
        Game.HandleAction(row.ID)
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Apply._PushSelectedMission(unit, mission, x, y, actionType)
  if unit == nil or mission == nil then
    return false
  end
  if Civ5Ai_Apply._UsesUiApply() then
    if actionType ~= nil then
      Civ5Ai_Apply._HandleActionByType(unit, actionType)
    end
    Civ5Ai_Apply._PrepareUnitSelection(unit)
  end
  if unit.PushMission ~= nil then
    unit:PushMission(mission, x or 0, y or 0, 0, 0, 0)
  end
  if Civ5Ai_Apply._UsesUiApply()
      and Game ~= nil
      and Game.SelectionListGameNetMessage ~= nil
      and GameMessageTypes ~= nil then
    Game.SelectionListGameNetMessage(
      GameMessageTypes.GAMEMESSAGE_PUSH_MISSION,
      mission,
      x or 0,
      y or 0,
      0,
      false,
      false
    )
  end
  return true
end

function Civ5Ai_Apply.ResolveAllUnitOrders(playerID, includeOrdered)
  return Civ5Ai_Apply.SkipUnorderedUnits(playerID)
end

function Civ5Ai_Apply._PlayerHasResearchQueued(player)
  if player == nil or player.GetCurrentResearch == nil then
    return false
  end
  local current = player:GetCurrentResearch()
  if current == nil or current < 0 then
    return false
  end
  if player.IsHasTech ~= nil and player:IsHasTech(current) then
    return false
  end
  return true
end

function Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local isResearchBlock = t == nil
    or blocking == t.ENDTURN_BLOCKING_RESEARCH
    or blocking == t.ENDTURN_BLOCKING_FREE_TECH
    or blocking == t.ENDTURN_BLOCKING_STEAL_TECH
  if not isResearchBlock then
    return false
  end
  local satisfied = Civ5Ai_Apply._PlayerHasResearchQueued(player)
  if not satisfied and t ~= nil and blocking == t.ENDTURN_BLOCKING_FREE_TECH then
    satisfied = player.GetNumFreeTechs ~= nil and (player:GetNumFreeTechs() or 0) == 0
  end
  if not satisfied then
    return false
  end
  Civ5Ai_Apply._DismissBlockingPopups(true)
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSETECH)
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSE_TECH_TO_STEAL)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseTechPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ResearchChooserPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/TechPopup")
  if player.GetEndTurnBlockingNotificationIndex ~= nil
    and UI ~= nil
    and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
    end
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
    Civ5Ai_Util.Log(
      "apply|resolve_research|player=" .. tostring(playerID) .. "|acknowledged=1"
    )
    return true
  end
  -- Live t46: notification-remove left RESEARCH blocking=1 with research queued
  -- (current>=0, not HasTech). Mirror promo phantom clear via DLL.
  if Civ5Ai_Apply._PlayerHasResearchQueued(player) then
    local t2 = EndTurnBlockingTypes
    if t2 ~= nil and (
      blocking == t2.ENDTURN_BLOCKING_RESEARCH
      or blocking == t2.ENDTURN_BLOCKING_FREE_TECH
    ) then
      Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
      blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
      Civ5Ai_Util.Log(
        "apply|resolve_research|player="
          .. tostring(playerID)
          .. "|dll_clear_after_phantom|blocking="
          .. tostring(blocking)
      )
      if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Apply._SendResearchChoice(playerID, row)
  local player = Players[playerID]
  if player == nil or row == nil or row.ID == nil then
    return false
  end
  local queue = 0
  if player.GetNumFreeTechs ~= nil then
    local free = player:GetNumFreeTechs()
    if free ~= nil and free > 0 then
      queue = free
    end
  end
  -- Pottery-complete leaves GetCurrentResearch on a known tech, so the
  -- next SendResearch no-ops and CHOOSE RESEARCH stays up. Clear first.
  if player.GetCurrentResearch ~= nil then
    local current = player:GetCurrentResearch()
    if current ~= nil and current >= 0
      and player.IsHasTech ~= nil and player:IsHasTech(current) then
      if player.ClearResearchQueue ~= nil then
        player:ClearResearchQueue()
      end
    end
  end
  if player.PushResearch ~= nil then
    player:PushResearch(row.ID, true)
  end
  if player.SetResearchingTech ~= nil then
    player:SetResearchingTech(row.ID, true)
  end
  if Network ~= nil and Network.SendResearch ~= nil then
    Network.SendResearch(row.ID, queue, -1, false)
  end
  if Events ~= nil and Events.SerialEventResearchDirty ~= nil then
    Events.SerialEventResearchDirty()
  end
  -- Send first, then close the chooser. Dequeue-before-send cancelled the pick.
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSETECH)
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSE_TECH_TO_STEAL)
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_TECH_AWARD)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseTechPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ResearchChooserPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/TechAwardPopup")
  Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
    return true
  end
  if Civ5Ai_Apply._PlayerHasResearchQueued(player) then
    Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    return Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
  end
  local t = EndTurnBlockingTypes
  if t ~= nil and blocking == t.ENDTURN_BLOCKING_RESEARCH then
    return false
  end
  return true
end

function Civ5Ai_Apply.ResolveResearch(playerID)
  return Civ5Ai_Apply._WithActivePlayer(playerID, function()
    return Civ5Ai_Apply._ResolveResearchImpl(playerID)
  end)
end

function Civ5Ai_Apply._ResolveResearchImpl(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  -- Close the award toast only. Dequeuing ChooseTech/TechTree before the
  -- pick makes Network.SendResearch no-op on the local human seat.
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_TECH_AWARD)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/TechAwardPopup")
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local t = EndTurnBlockingTypes
  local needsPick = t == nil
    or blocking == t.ENDTURN_BLOCKING_RESEARCH
    or blocking == t.ENDTURN_BLOCKING_FREE_TECH
    or blocking == t.ENDTURN_BLOCKING_STEAL_TECH
  local current = player:GetCurrentResearch()
  -- Agriculture leftover: GetCurrentResearch stays on a known tech while
  -- blocking==-1, so needsPick is false and we returned without picking.
  if current ~= nil and current >= 0
    and player.IsHasTech ~= nil and player:IsHasTech(current) then
    if player.ClearResearchQueue ~= nil then
      player:ClearResearchQueue()
    end
    current = -1
  end
  if current ~= nil and current >= 0 then
    if needsPick then
      local activeRow = GameInfo.Technologies[current]
      if activeRow ~= nil and player.IsHasTech ~= nil and not player:IsHasTech(current) then
        Civ5Ai_Apply._DismissBlockingPopups(true)
        if ButtonPopupTypes ~= nil then
          Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSETECH)
          Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSE_TECH_TO_STEAL)
        end
        Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
        blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
        if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
          Civ5Ai_Util.Log(
            "apply|resolve_research|player="
              .. tostring(playerID)
              .. "|tech="
              .. tostring(activeRow.Type)
              .. "|already=1"
          )
          return true
        end
      end
    elseif player.IsHasTech == nil or not player:IsHasTech(current) then
      -- Queued research with blocking==-1 still leaves CHOOSE RESEARCH up
      -- for the local human, which makes CanDoControl false.
      Civ5Ai_Apply._DismissBlockingPopups(true)
      Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
      Civ5Ai_Apply._researchQueuedLogged = Civ5Ai_Apply._researchQueuedLogged or {}
      if Civ5Ai_Apply._researchQueuedLogged[playerID] ~= current then
        Civ5Ai_Apply._researchQueuedLogged[playerID] = current
        Civ5Ai_Util.Log(
          "apply|resolve_research|player="
            .. tostring(playerID)
            .. "|tech_queued="
            .. tostring(current)
        )
      end
      return true
    end
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Technologies")) do
    if row ~= nil and player.CanResearch ~= nil and player:CanResearch(row.ID) then
      if Civ5Ai_Apply._SendResearchChoice(playerID, row) then
        Civ5Ai_Util.Log(
          "apply|resolve_research|player=" .. tostring(playerID) .. "|tech=" .. tostring(row.Type)
        )
        return true
      end
    end
  end
  if needsPick then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Technologies")) do
      if Civ5Ai_Apply._SendResearchChoice(playerID, row) then
        Civ5Ai_Util.Log(
          "apply|resolve_research|player="
            .. tostring(playerID)
            .. "|tech="
            .. tostring(row.Type)
            .. "|send=1"
        )
        return true
      end
    end
  end
  Civ5Ai_Apply._AcknowledgeResearchBlocking(playerID)
  if Civ5Ai_Apply._PlayerHasResearchQueued(player) then
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
      Civ5Ai_Util.Log(
        "apply|resolve_research|player=" .. tostring(playerID) .. "|queued=1"
      )
      return true
    end
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
    Civ5Ai_Util.Log(
      "apply|resolve_research|player=" .. tostring(playerID) .. "|cleared=1"
    )
    return true
  end
  local currentNow = player.GetCurrentResearch ~= nil and player:GetCurrentResearch() or nil
  if Civ5Ai_Apply._PlayerHasResearchQueued(player) then
    Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
      Civ5Ai_Util.Log(
        "apply|resolve_research|player="
          .. tostring(playerID)
          .. "|dll_clear_failpath|current="
          .. tostring(currentNow)
      )
      return true
    end
  end
  Civ5Ai_Util.Log(
    "apply|resolve_research|player="
      .. tostring(playerID)
      .. "|failed|blocking="
      .. tostring(blocking)
      .. "|current="
      .. tostring(currentNow)
  )
  return false
end


function Civ5Ai_Apply.EnsureFirstCity(playerID)
  -- Disabled: first city must come from the model (foundCity), not a host inject.
  if playerID == nil then
    return false
  end
  local hasCity = Civ5Ai_Apply._PlayerCityCount(playerID) > 0
  if not hasCity then
    Civ5Ai_Util.Log("apply|ensure_first_city|player=" .. tostring(playerID) .. "|disabled|no_city")
  end
  return hasCity
end
function Civ5Ai_Apply._PlayerHasSettlerInField(player)
  if player == nil then
    return false
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local typeRow = GameInfo.Units[unit:GetUnitType()]
      if typeRow ~= nil and string.find(typeRow.Type, "SETTLER", 1, true) ~= nil then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Apply._CityHasProductionQueued(city)
  if city == nil then
    return false
  end
  if city.GetProductionUnit ~= nil and (city:GetProductionUnit() or -1) >= 0 then
    return true
  end
  if city.GetProductionBuilding ~= nil and (city:GetProductionBuilding() or -1) >= 0 then
    return true
  end
  if city.GetProductionProject ~= nil and (city:GetProductionProject() or -1) >= 0 then
    return true
  end
  if city.GetProductionProcess ~= nil and (city:GetProductionProcess() or -1) >= 0 then
    return true
  end
  return false
end

function Civ5Ai_Apply._MarkCityProductionSatisfied(playerID, city)
  if city == nil then
    return
  end
  Civ5Ai_Apply._productionSatisfied[playerID] = Civ5Ai_Apply._productionSatisfied[playerID] or {}
  Civ5Ai_Apply._productionSatisfied[playerID][Civ5Ai_Snapshot._CityWireId(city)] = true
end

function Civ5Ai_Apply._CityProductionSatisfied(playerID, city)
  -- Bucket marks are not engine state. Treating them as queued left
  -- ENDTURN_BLOCKING_PRODUCTION stuck after a no-op CityPushOrder.
  return Civ5Ai_Apply._CityHasProductionQueued(city)
end

function Civ5Ai_Apply._AcknowledgeProductionBlocking(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  -- FPS / DX9: ack_stuck + SerialEventGameDataDirty every finish retry
  -- can storm the UI during a minimize/maximize device reset.
  local now = (os and os.clock and os.clock()) or 0
  Civ5Ai_Apply._ackProdAt = Civ5Ai_Apply._ackProdAt or {}
  local lastAck = Civ5Ai_Apply._ackProdAt[playerID]
  if lastAck ~= nil and (now - lastAck) < 2.0 then
    return false
  end
  Civ5Ai_Apply._ackProdAt[playerID] = now
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t == nil or blocking ~= t.ENDTURN_BLOCKING_PRODUCTION then
    return false
  end
  local cityCount = 0
  local unsatisfied = false
  for city in player:Cities() do
    cityCount = cityCount + 1
    if not Civ5Ai_Apply._CityProductionSatisfied(playerID, city) then
      unsatisfied = true
    end
  end
  if cityCount == 0 then
    return false
  end
  if not unsatisfied then
    Civ5Ai_Apply._ResyncLocalHumanProduction(playerID)
  end
  if unsatisfied then
    -- Force one fill pass (below native-fill city gate) without re-entering
    -- Acknowledge via ResolveCityProductionImpl's trailing call.
    if Civ5Ai_Apply._ackProductionFilling then
      return false
    end
    Civ5Ai_Apply._ackProductionFilling = true
    Civ5Ai_Apply._forceProductionFill = true
    local okFill, errFill
    if Civ5Ai_Apply._WithLocalHumanActivePlayer ~= nil then
      okFill, errFill = pcall(function()
        return Civ5Ai_Apply._WithLocalHumanActivePlayer(playerID, function()
          return Civ5Ai_Apply._ResolveCityProductionImpl(playerID)
        end)
      end)
    else
      okFill, errFill = pcall(Civ5Ai_Apply._ResolveCityProductionImpl, playerID)
    end
    Civ5Ai_Apply._forceProductionFill = nil
    Civ5Ai_Apply._ackProductionFilling = nil
    if not okFill then
      Civ5Ai_Util.Log(
        "apply|resolve_cities|force_fill_error|player="
          .. tostring(playerID)
          .. "|"
          .. tostring(errFill)
      )
      return false
    end
    unsatisfied = false
    for city in player:Cities() do
      if not Civ5Ai_Apply._CityProductionSatisfied(playerID, city) then
        unsatisfied = true
        break
      end
    end
    if unsatisfied then
      return false
    end
  end
  Civ5Ai_Apply._DismissBlockingPopups(true)
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION)
    if ButtonPopupTypes.BUTTONPOPUP_PRODUCTION_POPUP ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_PRODUCTION_POPUP)
    end
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseProductionPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ProductionPopup")
  Civ5Ai_Apply._DismissCityScreen()
  -- Removing the blocking notification every finish retry prevented the engine
  -- from clearing PRODUCTION blocking after CityPushOrder on the local human.
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn()
  end
  Civ5Ai_Apply._productionNotifyRemoved = Civ5Ai_Apply._productionNotifyRemoved or {}
  local notifyKey = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._productionNotifyRemoved[notifyKey] ~= true
      and player.GetEndTurnBlockingNotificationIndex ~= nil
      and UI ~= nil
      and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
      Civ5Ai_Apply._productionNotifyRemoved[notifyKey] = true
      Civ5Ai_Util.Log(
        "apply|resolve_cities|player="
          .. tostring(playerID)
          .. "|removed_notification="
          .. tostring(idx)
      )
    end
  end
  if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
    Events.SerialEventEndTurnDirty()
  end
  if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
    Events.SerialEventGameDataDirty()
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
    Civ5Ai_Util.Log(
      "apply|resolve_cities|player=" .. tostring(playerID) .. "|acknowledged=1"
    )
    return true
  end
  -- Cities satisfied but PRODUCTION still asserted: log and keep dismissing.
  Civ5Ai_Util.Log(
    "apply|resolve_cities|player="
      .. tostring(playerID)
      .. "|ack_stuck|blocking="
      .. tostring(blocking)
      .. "|cities_ok=1"
  )
  -- One extra resync+dismiss wave per turn after ack_stuck. CityPushOrder can
  -- leave ENDTURN_BLOCKING_PRODUCTION while queues look filled.
  Civ5Ai_Apply._ackStuckExtra = Civ5Ai_Apply._ackStuckExtra or {}
  local stuckKey = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._ackStuckExtra[stuckKey] ~= true then
    Civ5Ai_Apply._ackStuckExtra[stuckKey] = true
    Civ5Ai_Apply._productionNotifyRemoved[notifyKey] = nil
    Civ5Ai_Apply._ResyncLocalHumanProduction(playerID)
    Civ5Ai_Apply._DismissBlockingPopups(true)
    if ButtonPopupTypes ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION)
    end
    Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseProductionPopup")
    Civ5Ai_Apply._DequeuePopupPath("/InGame/ProductionPopup")
    Civ5Ai_Apply._DismissCityScreen()
    if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
      Events.SerialEventEndTurnDirty()
    end
    if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
      Events.SerialEventGameDataDirty()
    end
    Civ5Ai_Util.Log(
      "apply|resolve_cities|player=" .. tostring(playerID) .. "|ack_stuck_extra_resync=1"
    )
    -- Second CityPushOrder wave under explicit local-active (Resync already does);
    -- re-check blocking after the wave.
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    if Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1 then
      Civ5Ai_Util.Log(
        "apply|resolve_cities|player=" .. tostring(playerID) .. "|acknowledged=1|after_extra_resync"
      )
      return true
    end
  end
  return false
end

function Civ5Ai_Apply._TryQueueCityProduction(playerID, city, buildId)
  if city == nil or buildId == nil or buildId == "" then
    return false
  end
  if Civ5Ai_Apply._CityProductionSatisfied(playerID, city) then
    return true
  end
  local ok = Civ5Ai_Apply._QueueProduction(playerID, {
    city_id = Civ5Ai_Snapshot._CityWireId(city),
    build_id = buildId,
  })
  if ok then
    Civ5Ai_Util.Log(
      "apply|resolve_cities|player="
        .. tostring(playerID)
        .. "|build="
        .. tostring(buildId)
    )
  end
  return ok
end

function Civ5Ai_Apply.ResolveCityProduction(playerID)
  -- Local-human CityPushOrder must run with GetActivePlayer()==seat or the
  -- engine leaves ENDTURN_BLOCKING_PRODUCTION while queues look filled
  -- (live-1789249180 t59 P0: resolve_cities failed blocking=2 queued=3).
  if Civ5Ai_Apply._WithLocalHumanActivePlayer ~= nil then
    return Civ5Ai_Apply._WithLocalHumanActivePlayer(playerID, function()
      return Civ5Ai_Apply._ResolveCityProductionImpl(playerID)
    end) == true
  end
  return Civ5Ai_Apply._WithActivePlayer(playerID, function()
    return Civ5Ai_Apply._ResolveCityProductionImpl(playerID)
  end)
end


function Civ5Ai_Apply._PlayerCombatUnitCount(player)
  local n = 0
  if player == nil then
    return 0
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local row = GameInfo.Units[unit:GetUnitType()]
      if row ~= nil and (row.Combat or 0) > 0 then
        n = n + 1
      end
    end
  end
  return n
end

function Civ5Ai_Apply._ResolveCityProductionImpl(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local forceAll = t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION
  local hasSettler = Civ5Ai_Apply._PlayerHasSettlerInField(player)
  local count = 0
  -- Warrior-first fallback loops Aztec jaguars / extra scouts while the
  -- starting UU sits idle. If we already have troops, try a worker instead.
  local gpt = 0
  if player.CalculateGoldRate ~= nil then
    gpt = player:CalculateGoldRate() or 0
  end
  local gold = 0
  if player.GetGold ~= nil then
    gold = player:GetGold() or 0
  end
  local cityCount = 0
  if player.GetNumCities ~= nil then
    cityCount = player:GetNumCities() or 0
  end
  local allowFill = Civ5Ai_Apply._AllowsNativeProductionFill(playerID)
  -- End-turn PRODUCTION block / forced clear must fill even below the
  -- native-fill city threshold (t21 CHOOSE PRODUCTION stall with 2 cities).
  if forceAll or Civ5Ai_Apply._forceProductionFill then
    allowFill = true
  end
  if not allowFill then
    Civ5Ai_Util.Log(
      "apply|resolve_cities|skip_native_fill|player="
        .. tostring(playerID)
        .. "|cities="
        .. tostring(cityCount)
    )
  end
  local workerCount = 0
  for u in player:Units() do
    if u ~= nil and not u:IsDead() then
      local row = GameInfo.Units[u:GetUnitType()]
      local typeId = row and row.Type or ""
      if typeId == "UNIT_WORKER" or (string.find(string.upper(typeId), "WORKER", 1, true) and not string.find(string.upper(typeId), "BOAT", 1, true)) then
        workerCount = workerCount + 1
      end
    end
  end
  local bankrupt = gpt < 0 or gold < 0
  local skipWorker = bankrupt or (cityCount > 0 and workerCount >= cityCount)
  -- Never worker-first while bankrupt or worker-saturated.
  local preferredUnits = { "UNIT_WARRIOR", "UNIT_SCOUT" }
  if not skipWorker then
    if Civ5Ai_Apply._PlayerCombatUnitCount(player) >= 2 then
      preferredUnits = { "UNIT_WORKER", "UNIT_WARRIOR", "UNIT_SCOUT" }
    else
      preferredUnits = { "UNIT_WARRIOR", "UNIT_SCOUT", "UNIT_WORKER", "UNIT_SETTLER" }
    end
  end
  local preferredBuildings = { "BUILDING_MONUMENT", "BUILDING_SHRINE" }
  for city in player:Cities() do
    if city ~= nil then
      if Civ5Ai_Apply._CityProductionSatisfied(playerID, city) then
        count = count + 1
      else
      local item = Civ5Ai_Snapshot._CityProductionItemId(city)
      local hasItem = type(item) == "string" and item ~= ""
      local queued = false
      -- Fall through when current-item requeue fails (e.g. cannot_construct).
      if hasItem then
        queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, item)
      end
      if not queued and allowFill then
        if not hasSettler and city.GetPopulation ~= nil and city:GetPopulation() >= 2 then
          queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, "UNIT_SETTLER")
        end
        if not queued and skipWorker then
          local wealth = GameInfo.Processes ~= nil and GameInfo.Processes["PROCESS_WEALTH"] or nil
          if wealth ~= nil and city.CanDo ~= nil then
            local canWealth = true
            if city.CanDo ~= nil and GameInfoTypes ~= nil then
              -- PROCESS_WEALTH via CanQueue / TryQueue
            end
            queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, wealth.Type)
          elseif wealth ~= nil then
            queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, wealth.Type)
          end
          if not queued then
            for _, btype in ipairs(preferredBuildings) do
              local brow = GameInfo.Buildings ~= nil and GameInfo.Buildings[btype] or nil
              if brow ~= nil and city.CanConstruct ~= nil and city:CanConstruct(brow.ID, 0, 0) then
                queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, brow.Type)
                if queued then
                  break
                end
              end
            end
          end
          -- Prefer leaving the queue empty over a worker while bankrupt.
        end
        if not queued then
          for _, unitType in ipairs(preferredUnits) do
            local row = GameInfo.Units[unitType]
            if row ~= nil and city.CanTrain ~= nil and city:CanTrain(row.ID, 0, 0) then
              queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, row.Type)
              if queued then
                break
              end
            end
          end
        end
        if not queued then
          for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Units")) do
            if row ~= nil and city.CanTrain ~= nil and city:CanTrain(row.ID, 0, 0) then
              local typeId = row.Type or ""
              local isWorker = typeId == "UNIT_WORKER" or (string.find(string.upper(typeId), "WORKER", 1, true) and not string.find(string.upper(typeId), "BOAT", 1, true))
              if not (skipWorker and isWorker) then
                queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, row.Type)
                if queued then
                  break
                end
              end
            end
          end
        end
        if not queued then
          for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
            if city.CanConstruct ~= nil and city:CanConstruct(row.ID, 0, 0) then
              if Civ5Ai_Apply._TryQueueCityProduction(playerID, city, row.Type) then
                queued = true
                break
              end
            end
          end
        end
        if not queued then
          local wealth = GameInfo.Processes ~= nil and GameInfo.Processes["PROCESS_WEALTH"] or nil
          if wealth ~= nil then
            queued = Civ5Ai_Apply._TryQueueCityProduction(playerID, city, wealth.Type)
          end
        end
      end
      if queued then
        count = count + 1
      end
      end
    end
  end
  Civ5Ai_Apply._DismissBlockingPopups(true)
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseProductionPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ProductionPopup")
  if not Civ5Ai_Apply._ackProductionFilling then
    Civ5Ai_Apply._AcknowledgeProductionBlocking(playerID)
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION then
    Civ5Ai_Util.Log(
      "apply|resolve_cities|player="
        .. tostring(playerID)
        .. "|failed|blocking="
        .. tostring(blocking)
        .. "|queued="
        .. tostring(count)
    )
  end
  return count > 0
end


function Civ5Ai_Apply._AcknowledgePolicyBlocking(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t == nil then
    return false
  end
  if blocking ~= t.ENDTURN_BLOCKING_POLICY
      and blocking ~= t.ENDTURN_BLOCKING_FREE_POLICY then
    return false
  end
  local freePolicies = 0
  if player.GetNumFreePolicies ~= nil then
    freePolicies = player:GetNumFreePolicies() or 0
  end
  local cultureStored = 0
  local nextCost = 0
  if Civ5Ai_Snapshot ~= nil then
    if Civ5Ai_Snapshot._CultureStored ~= nil then
      cultureStored = Civ5Ai_Snapshot._CultureStored(player) or 0
    end
    if Civ5Ai_Snapshot._NextPolicyCost ~= nil then
      nextCost = Civ5Ai_Snapshot._NextPolicyCost(player) or 0
    end
  end
  local canAny = false
  if player.CanAdoptPolicy ~= nil then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Policies")) do
      if Civ5Ai_Apply._PolicyBranchUnlocked(player, row)
          and not (player.HasPolicy ~= nil and player:HasPolicy(row.ID))
          and player:CanAdoptPolicy(row.ID) then
        canAny = true
        break
      end
    end
  end
  -- Still adoptable: leave blocker for ResolvePolicies / LLM.
  if canAny or freePolicies > 0 or (nextCost > 0 and cultureStored >= nextCost) then
    Civ5Ai_Util.Log(
      "apply|ack_policy|player="
        .. tostring(playerID)
        .. "|still_needed|free="
        .. tostring(freePolicies)
        .. "|culture="
        .. tostring(cultureStored)
        .. "|cost="
        .. tostring(nextCost)
        .. "|can="
        .. tostring(canAny)
    )
    return false
  end
  Civ5Ai_Apply._DismissPolicyPopup()
  if ButtonPopupTypes ~= nil and ButtonPopupTypes.BUTTONPOPUP_CHOOSEPOLICY ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPOLICY)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/SocialPolicyPopup")
  if player.GetEndTurnBlockingNotificationIndex ~= nil
      and UI ~= nil
      and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
      Civ5Ai_Util.Log(
        "apply|ack_policy|player="
          .. tostring(playerID)
          .. "|removed_notification="
          .. tostring(idx)
      )
    end
  end
  if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
    Events.SerialEventEndTurnDirty()
  end
  if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
    Events.SerialEventGameDataDirty()
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if blocking == t.ENDTURN_BLOCKING_POLICY
      or blocking == t.ENDTURN_BLOCKING_FREE_POLICY then
    -- Mirror research/promo phantom clear (DLL clears known phantoms; POLICY
    -- not yet listed there, but EndTurns refresh + notification remove often
    -- clears after culture is spent).
    Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  end
  local cleared = Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
  Civ5Ai_Util.Log(
    "apply|ack_policy|player="
      .. tostring(playerID)
      .. "|blocking="
      .. tostring(blocking)
      .. "|cleared="
      .. tostring(cleared)
  )
  return cleared
end

function Civ5Ai_Apply.ResolvePolicies(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local adopted = 0
  -- Hard cap + attempt de-dupe: Network.SendUpdatePolicies can return ok while
  -- culture/freePolicies stay unchanged (phantom POLICY block), which previously
  -- spun this while-true forever and crashed the host (live-1789449034 t4).
  local attempted = {}
  local maxAdopt = 8
  while adopted < maxAdopt do
    local freePolicies = 0
    if player.GetNumFreePolicies ~= nil then
      freePolicies = player:GetNumFreePolicies() or 0
    end
    local cultureStored = Civ5Ai_Snapshot._CultureStored(player)
    local nextCost = Civ5Ai_Snapshot._NextPolicyCost(player)
    if freePolicies <= 0 and cultureStored < nextCost then
      break
    end
    local cultureBefore = cultureStored
    local freeBefore = freePolicies
    local didOne = false
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("PolicyBranchTypes")) do
      if not Civ5Ai_Snapshot._IsIdeologyBranch(row) then
        local key = "branch:" .. tostring(row.Type)
        if attempted[key] then
          -- already tried this branch unlock this call
        else
          attempted[key] = true
          local ok = Civ5Ai_Apply._UnlockPolicyBranch(playerID, { policy_branch_id = row.Type })
          if ok then
            adopted = adopted + 1
            didOne = true
            Civ5Ai_Util.Log(
              "apply|resolve_policy_branch|player="
                .. tostring(playerID)
                .. "|branch="
                .. tostring(row.Type)
            )
            break
          end
        end
      end
    end
    if not didOne and player.CanAdoptPolicy ~= nil then
      for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Policies")) do
        local key = "policy:" .. tostring(row.Type)
        if not Civ5Ai_Apply._PolicyBranchUnlocked(player, row) then
          -- Match snapshot allowlist: branch policies require unlock first.
        elseif player.HasPolicy ~= nil and player:HasPolicy(row.ID) then
          -- already owned
        elseif attempted[key] then
          -- skip retry of same policy this call
        else
          attempted[key] = true
          local ok = Civ5Ai_Apply._AdoptSocialPolicy(playerID, { policy_id = row.Type })
          if ok then
            adopted = adopted + 1
            didOne = true
            Civ5Ai_Util.Log(
              "apply|resolve_policy|player=" .. tostring(playerID) .. "|policy=" .. tostring(row.Type)
            )
            break
          end
        end
      end
    end
    if not didOne then
      break
    end
    -- Phantom adopt: API said ok but culture/free unchanged -> stop to avoid freeze.
    local freeAfter = 0
    if player.GetNumFreePolicies ~= nil then
      freeAfter = player:GetNumFreePolicies() or 0
    end
    local cultureAfter = Civ5Ai_Snapshot._CultureStored(player)
    if freeAfter == freeBefore and cultureAfter == cultureBefore then
      Civ5Ai_Util.Log(
        "apply|resolve_policy_abort_phantom|player="
          .. tostring(playerID)
          .. "|adopted="
          .. tostring(adopted)
          .. "|culture="
          .. tostring(cultureAfter)
          .. "|free="
          .. tostring(freeAfter)
      )
      Civ5Ai_Apply._AcknowledgePolicyBlocking(playerID)
      break
    end
  end
  if adopted >= maxAdopt then
    Civ5Ai_Util.Log(
      "apply|resolve_policy_cap|player=" .. tostring(playerID) .. "|adopted=" .. tostring(adopted)
    )
  end
  return adopted > 0
end

function Civ5Ai_Apply._NoBelief()
  if BeliefTypes ~= nil and BeliefTypes.NO_BELIEF ~= nil then
    return BeliefTypes.NO_BELIEF
  end
  return -1
end

function Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local player = Players[playerID]
  if player == nil or player.GetEndTurnBlockingType == nil then
    return nil
  end
  return player:GetEndTurnBlockingType()
end

function Civ5Ai_Apply._PickBestBelief(playerID, beliefKeys)
  if beliefKeys == nil then
    return nil
  end
  local bestId = nil
  local bestScore = nil
  for _, beliefKey in ipairs(beliefKeys) do
    local belief = GameInfo.Beliefs[beliefKey]
    if belief ~= nil then
      local score = nil
      if Game.ScoreBelief ~= nil then
        score = Game.ScoreBelief(playerID, belief.ID)
      end
      if bestId == nil
        or (type(score) == "number" and (bestScore == nil or score > bestScore)) then
        bestId = belief.ID
        bestScore = score
      end
    end
  end
  return bestId
end

function Civ5Ai_Apply._BeliefKeys(getter, exclude)
  if getter == nil then
    return {}
  end
  local keys = getter()
  if keys == nil then
    return {}
  end
  local excluded = {}
  if exclude ~= nil then
    for _, beliefId in ipairs(exclude) do
      if beliefId ~= nil and beliefId >= 0 then
        excluded[beliefId] = true
      end
    end
  end
  local out = {}
  for _, beliefKey in ipairs(keys) do
    local belief = GameInfo.Beliefs[beliefKey]
    local beliefId = belief and belief.ID or beliefKey
    if not excluded[beliefId] then
      table.insert(out, beliefKey)
    end
  end
  return out
end

function Civ5Ai_Apply._PickPantheonBelief(playerID)
  if Game == nil or Game.GetAvailablePantheonBeliefs == nil then
    return nil
  end
  return Civ5Ai_Apply._PickBestBelief(playerID, Game.GetAvailablePantheonBeliefs())
end

function Civ5Ai_Apply._PickBeliefFromGetter(playerID, getter, exclude)
  return Civ5Ai_Apply._PickBestBelief(playerID, Civ5Ai_Apply._BeliefKeys(getter, exclude))
end

function Civ5Ai_Apply._ReligionIsTaken(religionId)
  if religionId == nil or religionId < 0 then
    return true
  end
  local lastPlayer = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastPlayer = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for otherID = 0, lastPlayer do
    local other = Players[otherID]
    if other ~= nil and other.IsEverAlive ~= nil and other:IsEverAlive()
      and other.OwnsReligion ~= nil and other:OwnsReligion() then
      if other:GetOwnedReligion() == religionId then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Apply._PickAvailableReligionId(playerID)
  local player = Players[playerID]
  if player ~= nil and player.OwnsReligion ~= nil and player:OwnsReligion() then
    return player:GetOwnedReligion()
  end
  if GameInfo == nil or GameInfo.Religions == nil then
    return nil
  end
  for row in GameInfo.Religions() do
    if row.Type ~= "RELIGION_PANTHEON" and not Civ5Ai_Apply._ReligionIsTaken(row.ID) then
      return row.ID
    end
  end
  return nil
end

function Civ5Ai_Apply._UnitCanFoundReligion(unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  local row = GameInfo.Units[unit:GetUnitType()]
  if row == nil then
    return false
  end
  if row.FoundReligion == true then
    return true
  end
  return row.Special == "SPECIALUNIT_PROPHET"
end

function Civ5Ai_Apply._FindProphetUnit(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  for unit in player:Units() do
    if Civ5Ai_Apply._UnitCanFoundReligion(unit) then
      return unit
    end
  end
  return nil
end

function Civ5Ai_Apply._ReligionPopupCoords(playerID)
  local unit = Civ5Ai_Apply._FindProphetUnit(playerID)
  if unit ~= nil then
    return unit:GetX(), unit:GetY()
  end
  local player = Players[playerID]
  if player ~= nil then
    local capital = player.GetCapitalCity ~= nil and player:GetCapitalCity() or nil
    if capital ~= nil then
      return capital:GetX(), capital:GetY()
    end
    for city in player:Cities() do
      if city ~= nil then
        return city:GetX(), city:GetY()
      end
    end
  end
  return 0, 0
end

function Civ5Ai_Apply._DismissReligionPopups()
  if ButtonPopupTypes ~= nil then
    if ButtonPopupTypes.BUTTONPOPUP_FOUND_RELIGION ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_FOUND_RELIGION)
    end
    if ButtonPopupTypes.BUTTONPOPUP_FOUND_PANTHEON ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_FOUND_PANTHEON)
    end
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseReligionPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChoosePantheonPopup")
end

function Civ5Ai_Apply.ResolveFoundReligion(playerID)
  local player = Players[playerID]
  if player == nil or Network == nil or Network.SendFoundReligion == nil then
    return false
  end
  if EndTurnBlockingTypes ~= nil then
    if Civ5Ai_Apply._PlayerEndTurnBlocking(playerID) ~= EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_RELIGION then
      return false
    end
  elseif player.HasCreatedReligion ~= nil and player:HasCreatedReligion() then
    return false
  end
  local religionId = Civ5Ai_Apply._PickAvailableReligionId(playerID)
  if religionId == nil then
    Civ5Ai_Util.Log("apply|resolve_religion|player=" .. tostring(playerID) .. "|no_religion")
    return false
  end
  local exclude = {}
  local founder = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableFounderBeliefs, exclude)
  if founder == nil then
    Civ5Ai_Util.Log("apply|resolve_religion|player=" .. tostring(playerID) .. "|no_founder")
    return false
  end
  table.insert(exclude, founder)
  local follower = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableFollowerBeliefs, exclude)
  if follower == nil then
    Civ5Ai_Util.Log("apply|resolve_religion|player=" .. tostring(playerID) .. "|no_follower")
    return false
  end
  table.insert(exclude, follower)
  local pantheonBelief = Civ5Ai_Apply._NoBelief()
  if player.HasCreatedPantheon ~= nil and not player:HasCreatedPantheon() then
    pantheonBelief = Civ5Ai_Apply._PickPantheonBelief(playerID) or pantheonBelief
  elseif player.GetBeliefInPantheon ~= nil then
    pantheonBelief = player:GetBeliefInPantheon()
  end
  local bonusBelief = Civ5Ai_Apply._NoBelief()
  if player.IsTraitBonusReligiousBelief ~= nil and player:IsTraitBonusReligiousBelief() then
    bonusBelief = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableBonusBeliefs, exclude)
      or bonusBelief
  end
  local dataX, dataY = Civ5Ai_Apply._ReligionPopupCoords(playerID)
  Network.SendFoundReligion(
    playerID,
    religionId,
    nil,
    founder,
    follower,
    pantheonBelief,
    bonusBelief,
    dataX,
    dataY
  )
  local religion = GameInfo.Religions[religionId]
  Civ5Ai_Util.Log(
    "apply|resolve_religion|player="
      .. tostring(playerID)
      .. "|religion="
      .. tostring(religion and religion.Type or religionId)
  )
  Civ5Ai_Apply._DismissReligionPopups()
  return true
end

function Civ5Ai_Apply.ResolveEnhanceReligion(playerID)
  local player = Players[playerID]
  if player == nil or Network == nil or Network.SendEnhanceReligion == nil then
    return false
  end
  if EndTurnBlockingTypes ~= nil then
    if Civ5Ai_Apply._PlayerEndTurnBlocking(playerID) ~= EndTurnBlockingTypes.ENDTURN_BLOCKING_ENHANCE_RELIGION then
      return false
    end
  elseif player.OwnsReligion == nil or not player:OwnsReligion() then
    return false
  end
  local religionId = player:GetOwnedReligion()
  if religionId == nil or religionId < 0 then
    return false
  end
  local exclude = {}
  if Game.GetBeliefsInReligion ~= nil then
    for _, beliefId in ipairs(Game.GetBeliefsInReligion(religionId)) do
      table.insert(exclude, beliefId)
    end
  end
  local follower2 = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableFollowerBeliefs, exclude)
  if follower2 == nil then
    Civ5Ai_Util.Log("apply|resolve_enhance_religion|player=" .. tostring(playerID) .. "|no_follower2")
    return false
  end
  table.insert(exclude, follower2)
  local enhancer = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableEnhancerBeliefs, exclude)
  if enhancer == nil then
    Civ5Ai_Util.Log("apply|resolve_enhance_religion|player=" .. tostring(playerID) .. "|no_enhancer")
    return false
  end
  local dataX, dataY = Civ5Ai_Apply._ReligionPopupCoords(playerID)
  Network.SendEnhanceReligion(playerID, religionId, nil, follower2, enhancer, dataX, dataY)
  local religion = GameInfo.Religions[religionId]
  Civ5Ai_Util.Log(
    "apply|resolve_enhance_religion|player="
      .. tostring(playerID)
      .. "|religion="
      .. tostring(religion and religion.Type or religionId)
  )
  Civ5Ai_Apply._DismissReligionPopups()
  return true
end

function Civ5Ai_Apply.ResolveReformationBelief(playerID)
  if Network == nil or Network.SendFoundPantheon == nil then
    return false
  end
  if EndTurnBlockingTypes ~= nil then
    if Civ5Ai_Apply._PlayerEndTurnBlocking(playerID) ~= EndTurnBlockingTypes.ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF then
      return false
    end
  elseif Game.GetAvailableReformationBeliefs == nil then
    return false
  end
  local beliefId = Civ5Ai_Apply._PickBestBelief(playerID, Game.GetAvailableReformationBeliefs())
  if beliefId == nil then
    Civ5Ai_Util.Log("apply|resolve_reformation|player=" .. tostring(playerID) .. "|no_beliefs")
    return false
  end
  Network.SendFoundPantheon(playerID, beliefId)
  local belief = GameInfo.Beliefs[beliefId]
  Civ5Ai_Util.Log(
    "apply|resolve_reformation|player="
      .. tostring(playerID)
      .. "|belief="
      .. tostring(belief and belief.Type or beliefId)
  )
  Civ5Ai_Apply._DismissReligionPopups()
  return true
end

function Civ5Ai_Apply.ResolveReligionChoices(playerID)
  if Civ5Ai_Apply.ResolveEnhanceReligion(playerID) then
    return true
  end
  if Civ5Ai_Apply.ResolveFoundReligion(playerID) then
    return true
  end
  return false
end

function Civ5Ai_Apply.ResolvePantheon(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  if player.HasCreatedPantheon ~= nil and player:HasCreatedPantheon() then
    Civ5Ai_Apply._pantheonSent = Civ5Ai_Apply._pantheonSent or {}
    Civ5Ai_Apply._pantheonSent[playerID] = nil
    -- Live t66 P0: FOUND_PANTHEON (13) can stay asserted after pantheon exists.
    local t = EndTurnBlockingTypes
    local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    if t ~= nil and blocking == t.ENDTURN_BLOCKING_FOUND_PANTHEON then
      Civ5Ai_Apply._DismissReligionPopups()
      if player.GetEndTurnBlockingNotificationIndex ~= nil
        and UI ~= nil and UI.RemoveNotification ~= nil then
        local idx = player:GetEndTurnBlockingNotificationIndex()
        if idx ~= nil and idx >= 0 then
          UI.RemoveNotification(idx)
        end
      end
      Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
      blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
      Civ5Ai_Util.Log(
        "apply|ack_phantom_pantheon|player="
          .. tostring(playerID)
          .. "|blocking="
          .. tostring(blocking)
      )
      return Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
    end
    return false
  end
  Civ5Ai_Apply._pantheonSent = Civ5Ai_Apply._pantheonSent or {}
  if Civ5Ai_Apply._pantheonSent[playerID] then
    if EndTurnBlockingTypes ~= nil
      and Civ5Ai_Apply._PlayerEndTurnBlocking(playerID) == EndTurnBlockingTypes.ENDTURN_BLOCKING_FOUND_PANTHEON then
      Civ5Ai_Apply._pantheonSent[playerID] = nil
    else
      return false
    end
  end
  if player.CanCreatePantheon == nil or not player:CanCreatePantheon(false) then
    return false
  end
  local beliefId = Civ5Ai_Apply._PickPantheonBelief(playerID)
  if beliefId == nil then
    Civ5Ai_Util.Log("apply|resolve_pantheon|player=" .. tostring(playerID) .. "|no_beliefs")
    return false
  end
  if Network == nil or Network.SendFoundPantheon == nil then
    return false
  end
  Network.SendFoundPantheon(playerID, beliefId)
  Civ5Ai_Apply._pantheonSent[playerID] = true
  local belief = GameInfo.Beliefs[beliefId]
  local beliefType = belief and belief.Type or tostring(beliefId)
  Civ5Ai_Util.Log(
    "apply|resolve_pantheon|player=" .. tostring(playerID) .. "|belief=" .. tostring(beliefType)
  )
  if ButtonPopupTypes ~= nil and ButtonPopupTypes.BUTTONPOPUP_FOUND_PANTHEON ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_FOUND_PANTHEON)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/ChoosePantheonPopup")
  return true
end


function Civ5Ai_Apply._BeliefRow(beliefId)
  if beliefId == nil or beliefId == "" or GameInfo == nil or GameInfo.Beliefs == nil then
    return nil
  end
  return GameInfo.Beliefs[beliefId]
end

function Civ5Ai_Apply._FoundPantheon(playerID, args)
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if player.HasCreatedPantheon ~= nil and player:HasCreatedPantheon() then
    return false, "pantheon_already_founded"
  end
  if player.CanCreatePantheon ~= nil and not player:CanCreatePantheon(false) then
    return false, "cannot_create_pantheon"
  end
  local row = Civ5Ai_Apply._BeliefRow(args and args.belief_id)
  if row == nil then
    return false, "invalid_belief"
  end
  if Network == nil or Network.SendFoundPantheon == nil then
    return false, "send_missing"
  end
  Network.SendFoundPantheon(playerID, row.ID)
  Civ5Ai_Apply._pantheonSent = Civ5Ai_Apply._pantheonSent or {}
  Civ5Ai_Apply._pantheonSent[playerID] = true
  Civ5Ai_Apply._DismissReligionPopups()
  Civ5Ai_Util.Log(
    "apply|found_pantheon|player=" .. tostring(playerID) .. "|belief=" .. tostring(row.Type)
  )
  return true, ""
end

function Civ5Ai_Apply._FoundReligion(playerID, args)
  local player = Players[playerID]
  if player == nil or Network == nil or Network.SendFoundReligion == nil then
    return false, "send_missing"
  end
  if player.HasCreatedReligion ~= nil and player:HasCreatedReligion() then
    return false, "religion_already_founded"
  end
  if Civ5Ai_Apply._FindProphetUnit(playerID) == nil then
    return false, "no_prophet"
  end
  local founderRow = Civ5Ai_Apply._BeliefRow(args and args.belief_id)
  if founderRow == nil then
    return false, "invalid_belief"
  end
  local religionId = Civ5Ai_Apply._PickAvailableReligionId(playerID)
  if religionId == nil then
    return false, "no_religion_slot"
  end
  local exclude = { founderRow.ID }
  local follower = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableFollowerBeliefs, exclude)
  if follower == nil then
    return false, "no_follower"
  end
  table.insert(exclude, follower)
  local pantheonBelief = Civ5Ai_Apply._NoBelief()
  if player.HasCreatedPantheon ~= nil and not player:HasCreatedPantheon() then
    pantheonBelief = Civ5Ai_Apply._PickPantheonBelief(playerID) or pantheonBelief
  elseif player.GetBeliefInPantheon ~= nil then
    pantheonBelief = player:GetBeliefInPantheon()
  end
  local bonusBelief = Civ5Ai_Apply._NoBelief()
  if player.IsTraitBonusReligiousBelief ~= nil and player:IsTraitBonusReligiousBelief() then
    bonusBelief = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableBonusBeliefs, exclude)
      or bonusBelief
  end
  local dataX, dataY = Civ5Ai_Apply._ReligionPopupCoords(playerID)
  Network.SendFoundReligion(
    playerID,
    religionId,
    nil,
    founderRow.ID,
    follower,
    pantheonBelief,
    bonusBelief,
    dataX,
    dataY
  )
  Civ5Ai_Apply._DismissReligionPopups()
  local religion = GameInfo.Religions[religionId]
  Civ5Ai_Util.Log(
    "apply|found_religion|player="
      .. tostring(playerID)
      .. "|religion="
      .. tostring(religion and religion.Type or religionId)
      .. "|founder="
      .. tostring(founderRow.Type)
  )
  return true, ""
end

function Civ5Ai_Apply._EnhanceReligion(playerID, args)
  local player = Players[playerID]
  if player == nil or Network == nil or Network.SendEnhanceReligion == nil then
    return false, "send_missing"
  end
  if player.OwnsReligion == nil or not player:OwnsReligion() then
    return false, "no_religion"
  end
  if Civ5Ai_Apply._FindProphetUnit(playerID) == nil then
    return false, "no_prophet"
  end
  local enhancerRow = Civ5Ai_Apply._BeliefRow(args and args.belief_id)
  if enhancerRow == nil then
    return false, "invalid_belief"
  end
  local religionId = player:GetOwnedReligion()
  if religionId == nil or religionId < 0 then
    return false, "no_religion"
  end
  local exclude = {}
  if Game.GetBeliefsInReligion ~= nil then
    for _, beliefId in ipairs(Game.GetBeliefsInReligion(religionId)) do
      table.insert(exclude, beliefId)
    end
  end
  table.insert(exclude, enhancerRow.ID)
  local follower2 = Civ5Ai_Apply._PickBeliefFromGetter(playerID, Game.GetAvailableFollowerBeliefs, exclude)
  if follower2 == nil then
    return false, "no_follower2"
  end
  local dataX, dataY = Civ5Ai_Apply._ReligionPopupCoords(playerID)
  Network.SendEnhanceReligion(playerID, religionId, nil, follower2, enhancerRow.ID, dataX, dataY)
  Civ5Ai_Apply._DismissReligionPopups()
  local religion = GameInfo.Religions[religionId]
  Civ5Ai_Util.Log(
    "apply|enhance_religion|player="
      .. tostring(playerID)
      .. "|religion="
      .. tostring(religion and religion.Type or religionId)
      .. "|enhancer="
      .. tostring(enhancerRow.Type)
  )
  return true, ""
end

function Civ5Ai_Apply.ResolveFaithBlockers(playerID)
  if Civ5Ai_Apply.ResolvePantheon(playerID) then
    return true
  end
  if Civ5Ai_Apply.ResolveReligionChoices(playerID) then
    return true
  end
  if Civ5Ai_Apply.ResolveReformationBelief(playerID) then
    return true
  end
  return false
end

function Civ5Ai_Apply.ResolvePromotions(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local count = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and unit.IsPromotionReady ~= nil and unit:IsPromotionReady() then
      for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("UnitPromotions")) do
        if unit.CanPromote ~= nil and unit:CanPromote(row.ID, -1) then
          if Civ5Ai_Apply._UsesUiApply() and UI ~= nil and UI.SelectUnit ~= nil then
            UI.SelectUnit(unit)
          end
          unit:Promote(row.ID, -1)
          count = count + 1
          Civ5Ai_Util.Log(
            "apply|resolve_promotion|player="
              .. tostring(playerID)
              .. "|unit="
              .. Civ5Ai_Snapshot._UnitWireId(unit)
              .. "|promotion="
              .. tostring(row.Type)
          )
          break
        end
      end
    end
  end
  -- Always try ack: Promote can succeed while blocking=9 notification sticks.
  Civ5Ai_Apply._AcknowledgePromotionBlocking(playerID)
  return count > 0
end

function Civ5Ai_Apply._PromotionReadyCount(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local n = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead()
      and unit.IsPromotionReady ~= nil and unit:IsPromotionReady() then
      n = n + 1
    end
  end
  return n
end

function Civ5Ai_Apply._AcknowledgePromotionBlocking(playerID)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local t = EndTurnBlockingTypes
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  if t == nil or blocking ~= t.ENDTURN_BLOCKING_UNIT_PROMOTION then
    return false
  end
  local ready = Civ5Ai_Apply._PromotionReadyCount(playerID)
  if ready > 0 then
    Civ5Ai_Util.Log(
      "apply|ack_promotion|player="
        .. tostring(playerID)
        .. "|still_ready="
        .. tostring(ready)
    )
    return false
  end
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
    Civ5Ai_Autotest._ReleaseUiFocus()
  end
  if Civ5Ai_Apply._ClearChatEntryFocus ~= nil then
    Civ5Ai_Apply._ClearChatEntryFocus()
  end
  Civ5Ai_Apply._DismissBlockingPopups(true)
  -- Unit promotion uses the unit panel, not a dedicated BUTTONPOPUP in BNW.
  Civ5Ai_Apply._DequeuePopupPath("/InGame/WorldView/UnitPanel")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/UnitPanel")
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn() or 0
  end
  Civ5Ai_Apply._promotionNotifyRemoved = Civ5Ai_Apply._promotionNotifyRemoved or {}
  local notifyKey = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._promotionNotifyRemoved[notifyKey] ~= true
      and player.GetEndTurnBlockingNotificationIndex ~= nil
      and UI ~= nil
      and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
      Civ5Ai_Apply._promotionNotifyRemoved[notifyKey] = true
      Civ5Ai_Util.Log(
        "apply|ack_promotion|player="
          .. tostring(playerID)
          .. "|removed_notification="
          .. tostring(idx)
      )
    end
  end
  if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
    Events.SerialEventEndTurnDirty()
  end
  if Events ~= nil and Events.SerialEventGameDataDirty ~= nil then
    Events.SerialEventGameDataDirty()
  end
  blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  -- Live t45: notification-remove-only left blocking=9 with ready==0 (phantom).
  -- Force DLL clear via Civ5Ai_ClearUnitsEndTurnBlock when still stuck.
  if blocking == t.ENDTURN_BLOCKING_UNIT_PROMOTION
      and Civ5Ai_Apply._PromotionReadyCount(playerID) == 0 then
    Civ5Ai_Apply._DllClearUnitsEndTurnBlock(playerID)
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    Civ5Ai_Util.Log(
      "apply|ack_promotion|player="
        .. tostring(playerID)
        .. "|dll_clear_after_phantom|blocking="
        .. tostring(blocking)
    )
  end
  local cleared = Civ5Ai_Apply._IsEndTurnClear(blocking) or blocking == -1
  Civ5Ai_Util.Log(
    "apply|ack_promotion|player="
      .. tostring(playerID)
      .. "|blocking="
      .. tostring(blocking)
      .. "|cleared="
      .. tostring(cleared)
      .. "|ready=0"
  )
  return cleared
end

function Civ5Ai_Apply.ResolveMayaBonus(playerID)
  local player = Players[playerID]
  if player == nil or player.GetNumMayaBoosts == nil or (player:GetNumMayaBoosts() or 0) <= 0 then
    return false
  end
  for row in GameInfo.Units() do
    if row.Special == "SPECIALUNIT_PEOPLE" then
      if player.CanTrain ~= nil and player:CanTrain(row.ID, true, true, true, false) then
        local ok = Civ5Ai_Apply._ChooseMayaBonus(playerID, { unit_type_id = row.Type })
        if ok then
          Civ5Ai_Util.Log(
            "apply|resolve_maya|player=" .. tostring(playerID) .. "|unit=" .. tostring(row.Type)
          )
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_Apply._ApplyCommand(playerID, command)
  return Civ5Ai_Commands.Apply(playerID, command)
end

function Civ5Ai_Apply._SetResearchTech(playerID, args)
  local techId = args.tech_id
  if techId == nil or techId == "" then
    return false, "missing_tech_id"
  end
  local row = GameInfo.Technologies[techId]
  if row == nil then
    return false, "invalid_tech"
  end
  local player = Players[playerID]
  if player == nil or not player:CanResearch(row.ID) then
    return false, "cannot_research"
  end
  if Civ5Ai_Apply._SendResearchChoice(playerID, row) then
    return true, ""
  end
  return false, "send_failed"
end


function Civ5Ai_Apply._RecordApplyFailEcho(playerID, kind, reason, command)
  if reason ~= "cannot_maintain" and reason ~= "would_declare_war" then
    return
  end
  local cmdId = command and command.command_id or ""
  local summary = tostring(reason) .. " kind=" .. tostring(kind) .. " " .. tostring(cmdId)
  table.insert(Civ5Ai_Apply._PendingCommandResults, {
    kind = reason,
    summary = summary,
    text = summary,
    turn = Game and Game.GetGameTurn and Game.GetGameTurn() or 0,
    actor_player_id = "PLAYER_" .. tostring(playerID),
    affected_ids = { cmdId },
  })
end
function Civ5Ai_Apply._CanDoCommandSafe(unit, command, iData1, iData2)
  -- Community Patch / VP: CanDoCommand(eCommand, iData1, iData2, iData3[, bTestVisible[, bTestBusy]])
  -- Vanilla used bool as 4th (bTestVisible). Passing false as 4th on CP throws:
  -- "bad arg #4 (number expected, got boolean)" and aborts the whole apply via pcall.
  if unit == nil or command == nil or unit.CanDoCommand == nil then
    return true, nil
  end
  iData1 = iData1 or -1
  iData2 = iData2 or -1
  local attempts = {
    function() return unit:CanDoCommand(command, iData1, iData2, 0, false) end,
    function() return unit:CanDoCommand(command, iData1, iData2, 0) end,
    function() return unit:CanDoCommand(command, iData1, iData2) end,
    function() return unit:CanDoCommand(command) end,
  }
  local lastErr = nil
  for _, fn in ipairs(attempts) do
    local ok, result = pcall(fn)
    if ok then
      return result == true, nil
    end
    lastErr = result
  end
  return true, lastErr
end

function Civ5Ai_Apply._DisbandUnit(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local deleteCmd = CommandTypes ~= nil and CommandTypes.COMMAND_DELETE or nil
  if deleteCmd ~= nil then
    local canDelete, canErr = Civ5Ai_Apply._CanDoCommandSafe(unit, deleteCmd, -1, -1)
    if canErr ~= nil then
      Civ5Ai_Util.Log(
        "apply|disband_can_err|unit="
          .. tostring(args.unit_id)
          .. "|"
          .. tostring(canErr)
      )
    end
    if canDelete and unit.DoCommand ~= nil then
      pcall(function()
        unit:DoCommand(deleteCmd)
      end)
    end
  end
  unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit ~= nil then
    local mission = Civ5Ai_Apply._Mission("MISSION_DELETE")
    if mission ~= nil and unit.PushMission ~= nil then
      pcall(function()
        unit:PushMission(mission, 0, 0, 0, 0, 0)
      end)
    end
  end
  unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit ~= nil and unit.Kill ~= nil and (unit.IsDead == nil or not unit:IsDead()) then
    pcall(function()
      unit:Kill()
    end)
  end
  unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit ~= nil and (unit.IsDead == nil or not unit:IsDead()) then
    -- Ensure leftover drain (B) can clear MovesLeft after wait.
    Civ5Ai_Apply._failedUnits[playerID] = Civ5Ai_Apply._failedUnits[playerID] or {}
    Civ5Ai_Apply._failedUnits[playerID][tostring(args.unit_id)] = true
    if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._UnitWireId ~= nil then
      local wire = Civ5Ai_Snapshot._UnitWireId(args.unit_id)
      if wire ~= nil then
        Civ5Ai_Apply._failedUnits[playerID][tostring(wire)] = true
      end
    end
    return false, "disband_failed"
  end
  Civ5Ai_Util.Log("apply|ok|disband|unit=" .. tostring(args.unit_id))
  return true, ""
end

function Civ5Ai_Apply._SellBuilding(playerID, args)
  local cityId = args.city_id
  local buildId = args.build_id or args.building_id
  if cityId == nil or buildId == nil then
    return false, "missing_city_or_building"
  end
  local city = Civ5Ai_Apply._FindCity(playerID, cityId)
  if city == nil then
    return false, "city_not_found"
  end
  local row = GameInfo.Buildings ~= nil and GameInfo.Buildings[buildId] or nil
  if row == nil then
    return false, "invalid_building"
  end
  if city.CanSellBuilding ~= nil and not city:CanSellBuilding(row.ID) then
    return false, "cannot_sell"
  end
  local refund = 0
  if city.GetSellBuildingRefund ~= nil then
    refund = city:GetSellBuildingRefund(row.ID) or 0
  end
  if Network ~= nil and Network.SendSellBuilding ~= nil then
    Network.SendSellBuilding(city:GetID(), row.ID)
  end
  local stillHas = false
  if city.IsHasBuilding ~= nil then
    stillHas = city:IsHasBuilding(row.ID) == true
  elseif city.GetNumBuilding ~= nil then
    stillHas = (city:GetNumBuilding(row.ID) or 0) > 0
  end
  if stillHas and city.SetNumRealBuilding ~= nil then
    city:SetNumRealBuilding(row.ID, 0)
    local player = Players[playerID]
    if refund > 0 and player ~= nil and player.ChangeGold ~= nil then
      player:ChangeGold(refund)
    end
  end
  return true, ""
end

function Civ5Ai_Apply._SetCityStatus(playerID, args)
  local cityId = args.city_id
  local status = string.lower(tostring(args.status or ""))
  if cityId == nil or status == "" then
    return false, "missing_city_or_status"
  end
  if status ~= "puppet" and status ~= "annex" and status ~= "raze" then
    return false, "invalid_status"
  end
  local city = Civ5Ai_Apply._FindCity(playerID, cityId)
  if city == nil then
    return false, "city_not_found"
  end
  local player = Players[playerID]
  if status == "annex" and player ~= nil and player.MayNotAnnex ~= nil and player:MayNotAnnex() then
    return false, "may_not_annex"
  end
  local cityNumericId = city.GetID ~= nil and city:GetID() or nil
  if cityNumericId == nil then
    return false, "city_id_missing"
  end
  local task = nil
  if status == "puppet" and TaskTypes ~= nil then
    task = TaskTypes.TASK_CREATE_PUPPET
  elseif status == "annex" and TaskTypes ~= nil then
    task = TaskTypes.TASK_ANNEX_PUPPET
  elseif status == "raze" and TaskTypes ~= nil then
    if city.CanRaze ~= nil and not city:CanRaze() then
      return false, "cannot_raze"
    end
    task = TaskTypes.TASK_RAZE
  end
  if task == nil then
    return false, "task_missing"
  end
  if Network ~= nil and Network.SendDoTask ~= nil then
    Network.SendDoTask(cityNumericId, task, -1, -1, false, false, false, false)
  elseif city.DoTask ~= nil then
    city:DoTask(task)
  else
    return false, "do_task_missing"
  end
  if ButtonPopupTypes ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CITY_CAPTURED)
  end
  return true, ""
end

function Civ5Ai_Apply._QueueProduction(playerID, args)
  local cityId = args.city_id
  local buildId = args.build_id
  if cityId == nil or buildId == nil then
    return false, "missing_city_or_build"
  end
  local city = Civ5Ai_Apply._FindCity(playerID, cityId)
  if city == nil then
    return false, "city_not_found"
  end
  local function pushOrder(orderType, itemId)
    local okPush = Civ5Ai_Apply._WithLocalHumanActivePlayer(playerID, function()
      if Game ~= nil and Game.CityPushOrder ~= nil then
        Game.CityPushOrder(city, orderType, itemId, false, false, true)
      end
      if not Civ5Ai_Apply._CityHasProductionQueued(city) and city.PushOrder ~= nil then
        city:PushOrder(orderType, itemId, -1, 0, 0, 1, 0)
      end
      return Civ5Ai_Apply._CityHasProductionQueued(city)
    end)
    if okPush ~= true then
      if Game == nil or (Game.CityPushOrder == nil and city.PushOrder == nil) then
        return false, "push_order_missing"
      end
      return false, "push_order_failed"
    end
    Civ5Ai_Apply._MarkCityProductionSatisfied(playerID, city)
    if ButtonPopupTypes ~= nil then
      Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION)
    end
    Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseProductionPopup")
    Civ5Ai_Apply._DequeuePopupPath("/InGame/ProductionPopup")
    if Events ~= nil and Events.SpecificCityInfoDirty ~= nil then
      Events.SpecificCityInfoDirty(playerID, city:GetID(), CityUpdateTypes.CITY_UPDATE_TYPE_PRODUCTION)
    end
    Civ5Ai_Apply._AcknowledgeProductionBlocking(playerID)
    return true, ""
  end
  local unitRow = GameInfo.Units[buildId]
  if unitRow ~= nil then
    if not city:CanTrain(unitRow.ID, 0, 0) then
      return false, "cannot_train"
    end
    return pushOrder(OrderTypes.ORDER_TRAIN, unitRow.ID)
  end
  local buildingRow = GameInfo.Buildings[buildId]
  if buildingRow ~= nil then
    if not city:CanConstruct(buildingRow.ID, 0, 0) then
      return false, "cannot_construct"
    end
    return pushOrder(OrderTypes.ORDER_CONSTRUCT, buildingRow.ID)
  end
  local projectRow = GameInfo.Projects[buildId]
  if projectRow ~= nil then
    if not Civ5Ai_Apply._HasMethod(city, "CanCreate") or not city:CanCreate(projectRow.ID) then
      return false, "cannot_create"
    end
    return pushOrder(OrderTypes.ORDER_CREATE, projectRow.ID)
  end
  local processRow = GameInfo.Processes[buildId]
  if processRow ~= nil then
    if not Civ5Ai_Apply._HasMethod(city, "CanMaintain") or not city:CanMaintain(processRow.ID) then
      return false, "cannot_maintain"
    end
    return pushOrder(OrderTypes.ORDER_MAINTAIN, processRow.ID)
  end
  return false, "invalid_build_id"
end

function Civ5Ai_Apply._BuyWithFaith(playerID, args)
  local cityId = args.city_id
  local buildId = args.build_id
  if cityId == nil or buildId == nil then
    return false, "missing_city_or_build"
  end
  local city = Civ5Ai_Apply._FindCity(playerID, cityId)
  if city == nil then
    return false, "city_not_found"
  end
  if YieldTypes == nil then
    return false, "yield_types_missing"
  end
  local unitRow = GameInfo.Units ~= nil and GameInfo.Units[buildId] or nil
  if unitRow ~= nil then
    if city.IsCanPurchase == nil or not city:IsCanPurchase(false, false, unitRow.ID, -1, -1, YieldTypes.YIELD_FAITH) then
      return false, "cannot_purchase"
    end
    if Game ~= nil and Game.CityPurchaseUnit ~= nil then
      Game.CityPurchaseUnit(city, unitRow.ID, YieldTypes.YIELD_FAITH)
      return true, ""
    end
    return false, "purchase_api_missing"
  end
  local buildingRow = GameInfo.Buildings ~= nil and GameInfo.Buildings[buildId] or nil
  if buildingRow ~= nil then
    if city.IsCanPurchase == nil or not city:IsCanPurchase(false, false, -1, buildingRow.ID, -1, YieldTypes.YIELD_FAITH) then
      return false, "cannot_purchase"
    end
    if Game ~= nil and Game.CityPurchaseBuilding ~= nil then
      Game.CityPurchaseBuilding(city, buildingRow.ID, YieldTypes.YIELD_FAITH)
      return true, ""
    end
    return false, "purchase_api_missing"
  end
  return false, "invalid_build_id"
end

function Civ5Ai_Apply._BuyWithGold(playerID, args)
  local cityId = args.city_id
  local buildId = args.build_id
  if cityId == nil or buildId == nil then
    return false, "missing_city_or_build"
  end
  local city = Civ5Ai_Apply._FindCity(playerID, cityId)
  if city == nil then
    return false, "city_not_found"
  end
  if YieldTypes == nil then
    return false, "yield_types_missing"
  end
  local unitRow = GameInfo.Units ~= nil and GameInfo.Units[buildId] or nil
  if unitRow ~= nil then
    if city.IsCanPurchase == nil or not city:IsCanPurchase(false, false, unitRow.ID, -1, -1, YieldTypes.YIELD_GOLD) then
      return false, "cannot_purchase"
    end
    if Game ~= nil and Game.CityPurchaseUnit ~= nil then
      Game.CityPurchaseUnit(city, unitRow.ID, YieldTypes.YIELD_GOLD)
      return true, ""
    end
    return false, "purchase_api_missing"
  end
  local buildingRow = GameInfo.Buildings ~= nil and GameInfo.Buildings[buildId] or nil
  if buildingRow ~= nil then
    if city.IsCanPurchase == nil or not city:IsCanPurchase(false, false, -1, buildingRow.ID, -1, YieldTypes.YIELD_GOLD) then
      return false, "cannot_purchase"
    end
    if Game ~= nil and Game.CityPurchaseBuilding ~= nil then
      Game.CityPurchaseBuilding(city, buildingRow.ID, YieldTypes.YIELD_GOLD)
      return true, ""
    end
    return false, "purchase_api_missing"
  end
  return false, "invalid_build_id"
end

function Civ5Ai_Apply._UnlockPolicyBranch(playerID, args)
  local branchId = args.policy_branch_id
  if branchId == nil or branchId == "" then
    return false, "missing_policy_branch_id"
  end
  local row = GameInfo.PolicyBranchTypes[branchId]
  if row == nil then
    return false, "invalid_policy_branch"
  end
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if not player:CanUnlockPolicyBranch(row.ID) then
    return false, "cannot_unlock_branch"
  end
  if player.IsPolicyBranchUnlocked ~= nil and player:IsPolicyBranchUnlocked(row.ID) then
    return false, "branch_already_unlocked"
  end
  if not Civ5Ai_Apply._HasMethod(player, "SetPolicyBranchUnlocked") then
    return false, "set_policy_branch_missing"
  end
  player:SetPolicyBranchUnlocked(row.ID, true, false)
  Civ5Ai_Apply._DismissPolicyPopup()
  return true, ""
end

function Civ5Ai_Apply._PromoteUnit(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local promotionId = args.promotion_id
  if promotionId == nil or promotionId == "" then
    return false, "missing_promotion_id"
  end
  local row = GameInfo.UnitPromotions[promotionId]
  if row == nil then
    return false, "invalid_promotion"
  end
  if unit.CanPromote == nil or not unit:CanPromote(row.ID, -1) then
    return false, "cannot_promote"
  end
  if Civ5Ai_Apply._UsesUiApply() and UI ~= nil and UI.SelectUnit ~= nil then
    UI.SelectUnit(unit)
  end
  unit:Promote(row.ID, -1)
  -- Promote alone can leave ENDTURN_BLOCKING_UNIT_PROMOTION asserted.
  Civ5Ai_Apply._AcknowledgePromotionBlocking(playerID)
  return true, ""
end

function Civ5Ai_Apply._ChooseFreeGreatPerson(playerID, args)
  local unitTypeId = args.unit_type_id
  if unitTypeId == nil or unitTypeId == "" then
    return false, "missing_unit_type_id"
  end
  local row = GameInfo.Units[unitTypeId]
  if row == nil then
    return false, "invalid_unit_type"
  end
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if player.GetNumFreeGreatPeople == nil or (player:GetNumFreeGreatPeople() or 0) <= 0 then
    return false, "no_free_gp"
  end
  if player.CanTrain == nil or not player:CanTrain(row.ID, true, true, true, false) then
    return false, "cannot_train"
  end
  if Network ~= nil and Network.SendGreatPersonChoice ~= nil then
    Network.SendGreatPersonChoice(playerID, row.ID)
    return true, ""
  end
  if Network ~= nil and Network.SendFaithGreatPersonChoice ~= nil then
    Network.SendFaithGreatPersonChoice(playerID, row.ID)
    return true, ""
  end
  return false, "send_gp_missing"
end

function Civ5Ai_Apply.ResolveFreeGreatPerson(playerID)
  local player = Players[playerID]
  if player == nil or player.GetNumFreeGreatPeople == nil or (player:GetNumFreeGreatPeople() or 0) <= 0 then
    return false
  end
  local preferred = {
    "UNIT_SCIENTIST", "UNIT_ENGINEER", "UNIT_MERCHANT", "UNIT_ARTIST",
    "UNIT_WRITER", "UNIT_MUSICIAN", "UNIT_GREAT_GENERAL", "UNIT_GREAT_ADMIRAL",
  }
  for _, unitType in ipairs(preferred) do
    local row = GameInfo.Units[unitType]
    if row ~= nil and player.CanTrain ~= nil and player:CanTrain(row.ID, true, true, true, false) then
      local ok = Civ5Ai_Apply._ChooseFreeGreatPerson(playerID, { unit_type_id = unitType })
      if ok then
        Civ5Ai_Util.Log(
          "apply|resolve_free_gp|player=" .. tostring(playerID) .. "|unit=" .. tostring(unitType)
        )
        return true
      end
    end
  end
  for row in GameInfo.Units() do
    if row.Special == "SPECIALUNIT_PEOPLE" then
      if player.CanTrain ~= nil and player:CanTrain(row.ID, true, true, true, false) then
        local ok = Civ5Ai_Apply._ChooseFreeGreatPerson(playerID, { unit_type_id = row.Type })
        if ok then
          Civ5Ai_Util.Log(
            "apply|resolve_free_gp|player=" .. tostring(playerID) .. "|unit=" .. tostring(row.Type)
          )
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_Apply._ChooseMayaBonus(playerID, args)
  local unitTypeId = args.unit_type_id
  if unitTypeId == nil or unitTypeId == "" then
    return false, "missing_unit_type_id"
  end
  local row = GameInfo.Units[unitTypeId]
  if row == nil then
    return false, "invalid_unit_type"
  end
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if player.GetNumMayaBoosts == nil or (player:GetNumMayaBoosts() or 0) <= 0 then
    return false, "no_maya_boosts"
  end
  if player.CanTrain == nil or not player:CanTrain(row.ID, true, true, true, false) then
    return false, "cannot_train"
  end
  if Network == nil or Network.SendMayaBonusChoice == nil then
    return false, "send_maya_missing"
  end
  Network.SendMayaBonusChoice(playerID, row.ID)
  return true, ""
end

function Civ5Ai_Apply._AdoptIdeology(playerID, args)
  local branchId = args.policy_branch_id
  if branchId == nil or branchId == "" then
    return false, "missing_policy_branch_id"
  end
  local row = GameInfo.PolicyBranchTypes[branchId]
  if row == nil then
    return false, "invalid_policy_branch"
  end
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if not Civ5Ai_Snapshot._IsIdeologyBranch(row) then
    return false, "not_ideology_branch"
  end
  if not Civ5Ai_Snapshot._PlayerCanChooseIdeology(player) then
    return false, "cannot_adopt_ideology"
  end
  if not Civ5Ai_Apply._HasMethod(player, "SetPolicyBranchUnlocked") then
    return false, "set_policy_branch_missing"
  end
  player:SetPolicyBranchUnlocked(row.ID, true, false)
  Civ5Ai_Apply._DismissPolicyPopup()
  return true, ""
end

function Civ5Ai_Apply._UnitPlot(unit)
  if unit == nil then
    return nil
  end
  return Map.GetPlot(unit:GetX(), unit:GetY())
end

function Civ5Ai_Apply._QueueLeftoverSkip(playerID, unitId)
  if unitId == nil then
    return
  end
  local bucket = Civ5Ai_Apply._pendingSkipRemaining[playerID]
  if bucket == nil then
    bucket = {}
    Civ5Ai_Apply._pendingSkipRemaining[playerID] = bucket
  end
  bucket[unitId] = true
end

function Civ5Ai_Apply._UnitMission(playerID, args, missionName, gateFn)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  -- SKIP/FORTIFY/SLEEP in the same pulse replace MOVE_TO before the path runs.
  if Civ5Ai_Apply._UnitWasOrdered(playerID, args.unit_id) then
    Civ5Ai_Apply._QueueLeftoverSkip(playerID, args.unit_id)
    Civ5Ai_Util.Log(
      "apply|defer_post_move|unit="
        .. tostring(args.unit_id)
        .. "|mission="
        .. tostring(missionName)
    )
    return true, ""
  end
  if gateFn ~= nil and not gateFn(unit) then
    return false, "cannot_execute"
  end
  local mission = Civ5Ai_Apply._Mission(missionName)
  if mission == nil then
    return false, "mission_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, 0, 0, missionName)
  return true, ""
end

function Civ5Ai_Apply._FoundCitySettled(playerID, beforeCities, unit)
  if Civ5Ai_Apply._PlayerCityCount(playerID) > beforeCities then
    return true
  end
  if unit ~= nil and unit.IsDelayedDeath ~= nil and unit:IsDelayedDeath() then
    return true
  end
  return false
end

function Civ5Ai_Apply._DismissCityScreen()
  if UI ~= nil and UI.SetCityScreenUp ~= nil then
    UI.SetCityScreenUp(false)
  end
  if Events ~= nil and Events.SerialEventExitCityScreen ~= nil then
    Events.SerialEventExitCityScreen()
  end
  if UI ~= nil and UI.ClearSelectedCities ~= nil then
    UI.ClearSelectedCities()
  end
end

function Civ5Ai_Apply._ChatPanelHidden()
  if ContextPtr == nil or ContextPtr.LookUpControl == nil then
    return "no_ctx"
  end
  local paths = {
    "/InGame/WorldView/DiploCorner/ChatPanel",
    "/InGame/DiploCorner/ChatPanel",
  }
  for _, path in ipairs(paths) do
    local c = ContextPtr:LookUpControl(path)
    if c ~= nil and c.IsHidden ~= nil then
      return tostring(c:IsHidden() == true) .. "|" .. path
    end
  end
  return "missing"
end

function Civ5Ai_Apply._ClearChatEntryFocus()
  -- Clear ChatEntry focus only. Do not hide the chat panel or edit box:
  -- end-turn dismiss used to do that every tick and the WorldView restore
  -- never survived past the first local-human end-turn.
  if LuaEvents ~= nil then
    LuaEvents.Civ5AiClearChatFocus()
  end
  if ContextPtr == nil or ContextPtr.LookUpControl == nil then
    return
  end
  local paths = {
    "/InGame/WorldView/DiploCorner/ChatEntry",
    "/InGame/DiploCorner/ChatEntry",
  }
  for _, path in ipairs(paths) do
    local c = ContextPtr:LookUpControl(path)
    if c ~= nil and c.ClearFocus ~= nil then
      c:ClearFocus()
    end
  end
end

function Civ5Ai_Apply._CityProductionDiag(playerID)
  local player = Players[playerID]
  if player == nil then
    return "no_player"
  end
  local parts = {}
  for city in player:Cities() do
    if city ~= nil then
      local item = ""
      if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._CityProductionItemId ~= nil then
        item = tostring(Civ5Ai_Snapshot._CityProductionItemId(city) or "")
      end
      local name = tostring(city:GetID())
      if city.GetName ~= nil then
        name = tostring(city:GetName() or name)
      end
      table.insert(parts, name .. "=" .. item)
    end
  end
  if #parts == 0 then
    return "none"
  end
  return table.concat(parts, ",")
end

function Civ5Ai_Apply._UnitsNeedingOrdersCount(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local n = 0
  for unit in player:Units() do
    if Civ5Ai_Apply._IsUnorderedBlockingUnit(playerID, unit) then
      n = n + 1
    end
  end
  return n
end

function Civ5Ai_Apply._UnitsMovesDiag(playerID)
  local player = Players[playerID]
  if player == nil then
    return "no_player", 0
  end
  local parts = {}
  local busyN = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local moves = 0
      if unit.MovesLeft ~= nil then
        moves = unit:MovesLeft() or 0
      end
      local ready = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true
      local isBusy = false
      if unit.IsBusy ~= nil then
        isBusy = unit:IsBusy() == true
      elseif Civ5Ai_Apply._UnitIsBusyMoving ~= nil then
        isBusy = Civ5Ai_Apply._UnitIsBusyMoving(unit) == true
      end
      if isBusy then
        busyN = busyN + 1
      end
      if ready or isBusy or moves > 0 then
        table.insert(
          parts,
          tostring(unit:GetID())
            .. ":m="
            .. tostring(moves)
            .. ":r="
            .. tostring(ready)
            .. ":b="
            .. tostring(isBusy)
        )
      end
    end
  end
  local body = "none"
  if #parts > 0 then
    body = table.concat(parts, ",")
  end
  return body, busyN
end

function Civ5Ai_Apply._UiTry(name, ...)
  if UI == nil then
    return nil
  end
  local fn = UI[name]
  if type(fn) ~= "function" then
    return nil
  end
  local ok, val = pcall(fn, UI, ...)
  if not ok then
    return nil
  end
  return val
end

function Civ5Ai_Apply._LocalHumanMovesRemaining(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local n = 0
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local moves = 0
      if unit.MovesLeft ~= nil then
        moves = unit:MovesLeft() or 0
      end
      if moves <= 0 then
      elseif Civ5Ai_Apply._UnitWasAutomatedThisTurn(playerID, unit) then
      elseif unit.IsAutomated ~= nil and unit:IsAutomated() == true then
      elseif Civ5Ai_Apply._UnitIsBusyMoving ~= nil and Civ5Ai_Apply._UnitIsBusyMoving(unit) then
      else
        n = n + 1
      end
    end
  end
  return n
end

function Civ5Ai_Apply._PrepLocalHumanSeatEndTurn(playerID, forceLeftovers)
  if playerID == nil or Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers == nil then
    return
  end
  Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, forceLeftovers == true)
  if Civ5Ai_Apply._AnyOrderedUnitBusyMoving ~= nil
      and Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID) then
    return
  end
  if Civ5Ai_Apply.SkipPendingRemainingMoves ~= nil then
    Civ5Ai_Apply.SkipPendingRemainingMoves(playerID)
  end
  if Civ5Ai_Apply.SkipUnorderedUnits ~= nil then
    Civ5Ai_Apply.SkipUnorderedUnits(playerID)
  end
  if forceLeftovers and Civ5Ai_Apply._FinishAllUnitsWithMoves ~= nil then
    Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
  end
  if Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
    Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
  end
end

function Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
  Civ5Ai_Apply._DismissCityScreen()
  Civ5Ai_Apply._ClearChatEntryFocus()
  if Civ5Ai_HostChannel ~= nil and Civ5Ai_HostChannel.ReleaseUiFocus ~= nil then
    Civ5Ai_HostChannel.ReleaseUiFocus()
  end
  if UI ~= nil and UI.SetInterfaceMode ~= nil and InterfaceModeTypes ~= nil then
    UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION)
  end
  Civ5Ai_Apply._DismissBlockingPopups(true)
  -- C++ canDoControl(CONTROL_ENDTURN) is canEndTurn() && !isFocused().
  -- MP auto-end skips isFocused and calls sendTurnComplete itself.
  Civ5Ai_Apply._UiTry("ClearFocus")
  -- Never force SetCanEndTurn(true) while units still have MovesLeft: that makes
  -- Game.CanDoControl lie (can=true) while CONTROL_ENDTURN silently no-ops and
  -- the finish_seat retry spins forever (t29 P0 stall).
  local movesLeft = 0
  if playerID ~= nil then
    movesLeft = Civ5Ai_Apply._LocalHumanMovesRemaining(playerID)
  end
  local blocking = nil
  if playerID ~= nil then
    blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  end
  local unitsBlock = Civ5Ai_Apply._UnitsStillBlocking(blocking)
  if movesLeft <= 0 and not unitsBlock then
    Civ5Ai_Apply._UiTry("SetCanEndTurn", true)
    Civ5Ai_Apply._UiTry("SetMPAutoEndTurnEnabled", true)
  else
    Civ5Ai_Util.Log(
      "apply|defer_set_can_end_turn|player="
        .. tostring(playerID)
        .. "|units_with_moves="
        .. tostring(movesLeft)
        .. "|blocking="
        .. tostring(blocking)
    )
  end
end

function Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
  -- Local-human CONTROL_ENDTURN stays locked while any unit has MovesLeft,
  -- including AUTOMATE_EXPLORE (ReadyToMove is false so finish_ready skipped it).
  -- Also clear automated AWAKE / ACTIVITY_MISSION leftovers with 0 MovesLeft:
  -- live t43 diag showed auto act=6/0 keeping ENDTURN_BLOCKING_UNITS after
  -- SkipIdle only finished the four non-auto HOLD units.
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local n = 0
  local skipped = 0
  local localHuman = Civ5Ai_Apply._IsLocalHumanSeat(playerID)
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local auto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
      local was = Civ5Ai_Apply._UnitWasAutomatedThisTurn(playerID, unit)
      if auto or was then
        local moves = 0
        if unit.MovesLeft ~= nil then
          moves = unit:MovesLeft() or 0
        end
        local act = nil
        if unit.GetActivityType ~= nil then
          act = unit:GetActivityType()
        end
        local awake = ActivityTypes ~= nil
          and ActivityTypes.ACTIVITY_AWAKE ~= nil
          and act == ActivityTypes.ACTIVITY_AWAKE
        local mission = ActivityTypes ~= nil
          and ActivityTypes.ACTIVITY_MISSION ~= nil
          and act == ActivityTypes.ACTIVITY_MISSION
        if moves > 0 or awake or mission then
          if localHuman then
            Civ5Ai_Apply._FinishUnitMoves(unit)
            if awake or mission then
              skipped = skipped + 1
            end
          elseif unit.SetMoves ~= nil and moves > 0 and not awake and not mission then
            unit:SetMoves(0)
            Civ5Ai_Apply._NoteZeroedForEndTurn(unit)
          else
            Civ5Ai_Apply._FinishUnitMoves(unit)
            if awake or mission then
              skipped = skipped + 1
            end
          end
          n = n + 1
        end
      end
    end
  end
  if n > 0 then
    Civ5Ai_Util.Log(
      "apply|zero_auto_moves|player="
        .. tostring(playerID)
        .. "|n="
        .. tostring(n)
        .. "|stuck_skip="
        .. tostring(skipped)
    )
  end
  return n
end

function Civ5Ai_Apply._RecordOrderOrigin(playerID, unitId, kind, args)
  if playerID == nil or unitId == nil then
    return
  end
  local unit = Civ5Ai_Apply._FindUnit(playerID, unitId)
  local ox, oy = nil, nil
  if unit ~= nil then
    ox = unit:GetX()
    oy = unit:GetY()
  end
  local tx, ty = nil, nil
  if args ~= nil then
    tx = tonumber(args.target_x or args.x)
    ty = tonumber(args.target_y or args.y)
  end
  Civ5Ai_Apply._orderOrigin[playerID] = Civ5Ai_Apply._orderOrigin[playerID] or {}
  Civ5Ai_Apply._orderOrigin[playerID][tostring(unitId)] = {
    kind = tostring(kind or ""),
    x = ox,
    y = oy,
    tx = tx,
    ty = ty,
  }
end

function Civ5Ai_Apply._UnitApplyFailed(playerID, unitId)
  if unitId == nil then
    return false
  end
  local bucket = Civ5Ai_Apply._failedUnits[playerID]
  return bucket ~= nil and bucket[tostring(unitId)] == true
end

function Civ5Ai_Apply._UnitOrderVerifiedFailed(playerID, unit)
  -- (B) Verified failure: apply fail mark, or move/attack that never left
  -- its origin plot after the mission settled (plot unchanged).
  if unit == nil or unit:IsDead() then
    return false
  end
  local unitId = Civ5Ai_Apply._UnitOrderedId(playerID, unit)
  if unitId == nil then
    return false
  end
  if Civ5Ai_Apply._UnitApplyFailed(playerID, unitId) then
    return true
  end
  if Civ5Ai_Apply._UnitIsBusyMoving(unit) then
    return false
  end
  local originBucket = Civ5Ai_Apply._orderOrigin[playerID]
  local origin = originBucket ~= nil and originBucket[tostring(unitId)] or nil
  if origin == nil then
    return false
  end
  local kind = origin.kind or ""
  if kind ~= "move_unit" and kind ~= "attack_target" then
    return false
  end
  if origin.x == nil or origin.y == nil then
    return false
  end
  local tx, ty = origin.tx, origin.ty
  if tx == nil or ty == nil then
    return false
  end
  -- Target was a different tile but unit never moved.
  if tx == origin.x and ty == origin.y then
    return false
  end
  local x = unit:GetX()
  local y = unit:GetY()
  return x == origin.x and y == origin.y
end

function Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID)
  -- True while an LLM-ordered unit is still executing its mission/path.
  -- Leftover drain must WAIT before evaluating (A)/(B).
  local player = Players[playerID]
  if player == nil then
    return false
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local unitId = Civ5Ai_Apply._UnitOrderedId(playerID, unit)
      if unitId ~= nil and Civ5Ai_Apply._UnitWasOrdered(playerID, unitId) then
        if not Civ5Ai_Apply._UnitApplyFailed(playerID, unitId)
            and Civ5Ai_Apply._UnitIsBusyMoving(unit) then
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_Apply._UnitEligibleForLeftoverDrain(playerID, unit, forceBusy)
  -- Drain ONLY if:
  -- (A) LLM did not give a full-move / real order this turn, OR
  -- (B) command verified failed AND unit still has MovesLeft.
  -- Plus intentional short-move leftover queue. Never drain successful
  -- in-flight or completed orders that still hold MovesLeft legitimately.
  if unit == nil or unit:IsDead() then
    return false
  end
  local moves = 0
  if unit.MovesLeft ~= nil then
    moves = unit:MovesLeft() or 0
  end
  if moves <= 0 then
    return false
  end
  if Civ5Ai_Apply._UnitWasAutomatedThisTurn(playerID, unit) then
    return false
  end
  local busy = Civ5Ai_Apply._UnitIsBusyMoving(unit)
  if busy and not forceBusy then
    return false
  end
  local unitId = Civ5Ai_Apply._UnitOrderedId(playerID, unit)
  local ordered = unitId ~= nil and Civ5Ai_Apply._UnitWasOrdered(playerID, unitId)
  local leftover = unitId ~= nil and Civ5Ai_Apply._UnitSkipRemainingQueued(playerID, unitId)
  if leftover then
    return not busy or forceBusy == true
  end
  -- (B) verified failed (disband/lua_error/etc.) even if never marked ordered.
  if unitId ~= nil and Civ5Ai_Apply._UnitApplyFailed(playerID, unitId) then
    return not busy or forceBusy == true
  end
  if not ordered then
    -- (A) no real LLM order this pulse.
    return not busy or forceBusy == true
  end
  -- (B) ordered but verified failed (plot-unchanged move/attack), still MovesLeft.
  if Civ5Ai_Apply._UnitOrderVerifiedFailed(playerID, unit) then
    return true
  end
  -- (C) Ordered unit settled and ReadyToMove with MovesLeft = short-move
  -- leftover after a successful mission. Not cancelling an in-flight order.
  if unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true then
    return true
  end
  return false
end

function Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, forceBusy)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local waitingOrdered = Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID)
  if waitingOrdered then
    Civ5Ai_Util.Log(
      "apply|finish_moves_wait_ordered|player="
        .. tostring(playerID)
    )
    -- Do NOT abort drain. Successful in-flight orders stay protected by
    -- _UnitEligibleForLeftoverDrain; (A) unordered and (B) verified-failed
    -- leftovers (e.g. failed disbands) must still clear MovesLeft.
  end
  local n = 0
  for unit in player:Units() do
    if Civ5Ai_Apply._UnitEligibleForLeftoverDrain(playerID, unit, forceBusy) then
      Civ5Ai_Apply._FinishUnitMoves(unit)
      n = n + 1
    end
  end
  if n > 0 then
    Civ5Ai_Util.Log(
      "apply|finish_eligible_moves|player="
        .. tostring(playerID)
        .. "|n="
        .. tostring(n)
        .. "|force="
        .. tostring(forceBusy == true)
        .. "|waiting_ordered="
        .. tostring(waitingOrdered == true)
    )
  end
  return n
end

function Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, forceBusy)
  if playerID ~= nil then
    Civ5Ai_Apply.ResolvePolicies(playerID)
    local waitingOrders = Civ5Ai_Apply._AnyOrderedUnitBusyMoving(playerID)
    Civ5Ai_Apply._endturnWaitOrderedCount = Civ5Ai_Apply._endturnWaitOrderedCount or {}
    local waitN = Civ5Ai_Apply._endturnWaitOrderedCount[playerID] or 0
    if waitingOrders and forceBusy ~= true then
      waitN = waitN + 1
      Civ5Ai_Apply._endturnWaitOrderedCount[playerID] = waitN
      Civ5Ai_Util.Log(
        "apply|endturn_wait_ordered|player="
          .. tostring(playerID)
          .. "|n="
          .. tostring(waitN)
      )
      -- Cap: after ~8 waits (~4s at 0.5s bridge ticks) force settle path.
      if waitN >= 8 then
        Civ5Ai_Util.Log(
          "apply|endturn_wait_ordered_cap|player="
            .. tostring(playerID)
            .. "|n="
            .. tostring(waitN)
        )
        forceBusy = true
      end
    elseif not waitingOrders then
      Civ5Ai_Apply._endturnWaitOrderedCount[playerID] = 0
    end
    -- Always drain (A)/(B)/(C) eligible leftovers — including while other
    -- ordered missions are in flight. Previously gated on not waitingOrders,
    -- which left failed-disband MovesLeft stuck forever (livelock).
    Civ5Ai_Apply.SkipPendingRemainingMoves(playerID)
    if Civ5Ai_Apply.SkipUnorderedUnits ~= nil then
      Civ5Ai_Apply.SkipUnorderedUnits(playerID)
    end
    Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, forceBusy == true)
    if Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
      Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
    end
  end
  if playerID ~= nil and Civ5Ai_Apply._PlayerCityCount(playerID) > 0 then
    -- Force production chooser clear even below native-fill city threshold.
    local t = EndTurnBlockingTypes
    local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
    -- Do NOT ResolveCityProduction on every finish tick while UNITS block:
    -- that floods skip_native_fill + SerialEventGameDataDirty (DX/FPS storm).
    if Civ5Ai_Apply._UnitsStillBlocking(blocking) then
      -- Unit path only: skip production resolve this tick.
    else
      local nowProd = (os and os.clock and os.clock()) or 0
      Civ5Ai_Apply._clearLocalProdAt = Civ5Ai_Apply._clearLocalProdAt or {}
      local lastProd = Civ5Ai_Apply._clearLocalProdAt[playerID]
      local allowProd = lastProd == nil or (nowProd - lastProd) >= 2.0
      if allowProd then
        Civ5Ai_Apply._clearLocalProdAt[playerID] = nowProd
        if t ~= nil and blocking == t.ENDTURN_BLOCKING_PRODUCTION then
          Civ5Ai_Apply.ResolveCityProduction(playerID)
        else
          -- Still attempt resolve; impl force-fills when PRODUCTION blocking.
          Civ5Ai_Apply.ResolveCityProduction(playerID)
        end
      end
      if ButtonPopupTypes ~= nil then
        Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPRODUCTION)
      end
      Civ5Ai_Apply._DequeuePopupPath("/InGame/ChooseProductionPopup")
      Civ5Ai_Apply._DequeuePopupPath("/InGame/ProductionPopup")
      Civ5Ai_Apply.ResolveResearch(playerID)
    end
  end
  -- UI canEndTurn only after moves are actually gone / orders finishing.
  Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
end

function Civ5Ai_Apply._LogCanDoControlDiag(playerID, can)
  Civ5Ai_Apply._canDiagLogged = Civ5Ai_Apply._canDiagLogged or {}
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn()
  end
  local key = tostring(playerID) .. "|" .. tostring(turn)
  if Civ5Ai_Apply._canDiagLogged[key] then
    return
  end
  Civ5Ai_Apply._canDiagLogged[key] = true
  local cityUp = false
  if UI ~= nil and UI.IsCityScreenUp ~= nil then
    cityUp = UI.IsCityScreenUp() == true
  end
  local mode = nil
  if UI ~= nil and UI.GetInterfaceMode ~= nil then
    mode = UI.GetInterfaceMode()
  end
  local gameBusy = false
  if Game ~= nil and Game.IsBusy ~= nil then
    gameBusy = Game.IsBusy() == true
  end
  local units, busyN = Civ5Ai_Apply._UnitsMovesDiag(playerID)
  local prod = Civ5Ai_Apply._CityProductionDiag(playerID)
  local research = nil
  local player = Players[playerID]
  if player ~= nil and player.GetCurrentResearch ~= nil then
    research = player:GetCurrentResearch()
  end
  local blocking = Civ5Ai_Apply._PlayerEndTurnBlocking(playerID)
  local chatFocus = false
  if ContextPtr ~= nil and ContextPtr.LookUpControl ~= nil then
    local chat = ContextPtr:LookUpControl("/InGame/DiploCorner/ChatEntry")
    if chat == nil then
      chat = ContextPtr:LookUpControl("/InGame/WorldView/DiploCorner/ChatEntry")
    end
    if chat ~= nil and chat.HasFocus ~= nil then
      chatFocus = chat:HasFocus() == true
    end
  end
  local processing = false
  if Game ~= nil and Game.IsProcessingMessages ~= nil then
    processing = Game.IsProcessingMessages() == true
  end
  local uiFocused = Civ5Ai_Apply._UiTry("IsFocused")
  local uiWidget = Civ5Ai_Apply._UiTry("IsFocusedWidget")
  local uiPopup = Civ5Ai_Apply._UiTry("IsPopupUp")
  local uiCanEnd = Civ5Ai_Apply._UiTry("CanEndTurn")
  Civ5Ai_Util.Log(
    "apply|can_false_diag|player="
      .. tostring(playerID)
      .. "|can="
      .. tostring(can)
      .. "|blocking="
      .. tostring(blocking)
      .. "|city_screen="
      .. tostring(cityUp)
      .. "|iface="
      .. tostring(mode)
      .. "|game_busy="
      .. tostring(gameBusy)
      .. "|busy_units="
      .. tostring(busyN)
      .. "|units="
      .. tostring(units)
      .. "|prod="
      .. tostring(prod)
      .. "|research="
      .. tostring(research)
      .. "|chat_focus="
      .. tostring(chatFocus)
      .. "|processing="
      .. tostring(processing)
      .. "|chat_panel="
      .. tostring(Civ5Ai_Apply._ChatPanelHidden())
      .. "|ui_focused="
      .. tostring(uiFocused)
      .. "|ui_widget="
      .. tostring(uiWidget)
      .. "|ui_popup="
      .. tostring(uiPopup)
      .. "|ui_can_end="
      .. tostring(uiCanEnd)
  )
end

function Civ5Ai_Apply._FoundCity(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x = unit:GetX()
  local y = unit:GetY()
  local player = Players[playerID]
  if player ~= nil and player.CanFound ~= nil and not player:CanFound(x, y) then
    local plot = Map.GetPlot(x, y)
    local reason = "cannot_found"
    if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._DescribeCannotFoundReason ~= nil then
      reason = Civ5Ai_Snapshot._DescribeCannotFoundReason(player, plot)
    end
    -- Soft-skip replay of foundCity on a tile that already has a city (Nuku Hiva loop).
    local reasonText = string.lower(tostring(reason or ""))
    if string.find(reasonText, "city already here", 1, true) ~= nil then
      return true, "found_soft_skip_city_already_here"
    end
    return false, reason
  end
  local before = Civ5Ai_Apply._PlayerCityCount(playerID)
  local localSeat = Civ5Ai_Seats ~= nil and Civ5Ai_Seats.IsActiveLocalPlayer(playerID)
  local mission = Civ5Ai_Apply._Mission("MISSION_FOUND")
  if localSeat and mission ~= nil then
    -- UI found only for the locally selected seat. HandleAction on seats 1-3
    -- hits seat 0's selection and still returns ok.
    Civ5Ai_Apply._PushSelectedMission(unit, mission, 0, 0, "MISSION_FOUND")
  elseif unit.PushMission ~= nil and mission ~= nil then
    unit:PushMission(mission, 0, 0, 0, 0, 0)
  end
  unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if not Civ5Ai_Apply._FoundCitySettled(playerID, before, unit) then
    if player ~= nil and player.InitCity ~= nil then
      player:InitCity(x, y)
    end
    if Civ5Ai_Apply._PlayerCityCount(playerID) > before then
      unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
      if unit ~= nil and unit.Kill ~= nil and (unit.IsDead == nil or not unit:IsDead()) then
        unit:Kill()
      end
      Civ5Ai_Util.Log(
        "apply|found_city|via=init_city|player="
          .. tostring(playerID)
          .. "|plot="
          .. tostring(x)
          .. ","
          .. tostring(y)
      )
    end
  end
  -- UI MISSION_FOUND opens the city screen on the local human; that
  -- leaves CanDoControl(CONTROL_ENDTURN) false with blocking==-1.
  Civ5Ai_Apply._DismissCityScreen()
  Civ5Ai_Apply._ClearChatEntryFocus()
  Civ5Ai_Apply._DismissBlockingPopups(true)
  unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if not Civ5Ai_Apply._FoundCitySettled(playerID, before, unit) then
    return false, "found_no_city"
  end
  return true, ""
end

function Civ5Ai_Apply._ResolveTargetPlot(args)
  if args.target_unit_id ~= nil and args.target_unit_id ~= "" then
    local ownerIndex, gameUnitId = string.match(tostring(args.target_unit_id), "^UNIT_(%d+)_(%d+)$")
    if ownerIndex ~= nil and gameUnitId ~= nil then
      local other = Players[tonumber(ownerIndex)]
      if other ~= nil and other.GetUnitByID ~= nil then
        local targetUnit = other:GetUnitByID(tonumber(gameUnitId))
        if targetUnit ~= nil and not targetUnit:IsDead() then
          return targetUnit:GetX(), targetUnit:GetY()
        end
      end
    end
  end
  local x = tonumber(args.target_x)
  local y = tonumber(args.target_y)
  if (x == nil or y == nil) and args.plot_id ~= nil then
    x, y = Civ5Ai_Util.ParsePlotId(args.plot_id)
  end
  if (x == nil or y == nil) then
    local name = args.target_name or args.name
    if name ~= nil and tostring(name) ~= "" then
      x, y = Civ5Ai_Apply._ResolveNamedPlot(tostring(name))
    end
  end
  return x, y
end

function Civ5Ai_Apply._ResolveNamedPlot(name)
  local want = string.lower(tostring(name or ""))
  if want == "" or Players == nil then
    return nil, nil
  end
  local maxP = (GameDefines ~= nil and GameDefines.MAX_CIV_PLAYERS) or 22
  for i = 0, maxP - 1 do
    local p = Players[i]
    if p ~= nil and (p.IsAlive == nil or p:IsAlive()) then
      if p.Cities ~= nil then
        for city in p:Cities() do
          if city ~= nil and city.GetName ~= nil then
            local cname = string.lower(tostring(city:GetName() or ""))
            if cname == want then
              return city:GetX(), city:GetY()
            end
          end
        end
      end
      if p.Units ~= nil then
        for unit in p:Units() do
          if unit ~= nil and not unit:IsDead() then
            local uid = ""
            if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._UnitWireId ~= nil then
              uid = string.lower(tostring(Civ5Ai_Snapshot._UnitWireId(unit) or ""))
            end
            local uname = ""
            if unit.GetName ~= nil then
              uname = string.lower(tostring(unit:GetName() or ""))
            end
            if uid == want or uname == want then
              return unit:GetX(), unit:GetY()
            end
          end
        end
      end
    end
  end
  return nil, nil
end


function Civ5Ai_Apply._PlotHasFriendlyCombat(playerID, plot, exceptUnit)
  if plot == nil or plot.GetNumUnits == nil then
    return false
  end
  local n = plot:GetNumUnits() or 0
  for i = 0, n - 1 do
    local other = plot.GetUnit ~= nil and plot:GetUnit(i) or nil
    if other ~= nil and (exceptUnit == nil or other ~= exceptUnit) then
      if other.IsDead == nil or other:IsDead() ~= true then
        if other.GetOwner ~= nil and other:GetOwner() == playerID then
          local combat = 0
          if other.GetBaseCombatStrength ~= nil then
            combat = other:GetBaseCombatStrength() or 0
          end
          local ranged = 0
          if other.GetBaseRangedCombatStrength ~= nil then
            ranged = other:GetBaseRangedCombatStrength() or 0
          end
          if combat > 0 or ranged > 0 then
            return true
          end
        end
      end
    end
  end
  return false
end

function Civ5Ai_Apply._CanEnterPlot(unit, plot)
  if plot == nil then
    return false
  end
  if unit.CanMoveOrAttackInto ~= nil then
    return unit:CanMoveOrAttackInto(plot, 0, 1) == true
  end
  return true
end

function Civ5Ai_Apply._IsTeamId(teamID)
  return teamID ~= nil and type(teamID) == "number" and teamID >= 0
end

function Civ5Ai_Apply._PlayerLeaderName(playerID)
  local player = Players[playerID]
  if player == nil then
    return "a rival"
  end
  local leaderType = nil
  if GameInfo ~= nil and GameInfo.Leaders ~= nil and player.GetLeaderType ~= nil then
    leaderType = GameInfo.Leaders[player:GetLeaderType()]
  end
  if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._LeaderDisplayName ~= nil then
    return Civ5Ai_Snapshot._LeaderDisplayName(player, leaderType)
  end
  if player.GetName ~= nil then
    local name = player:GetName()
    if name ~= nil and name ~= "" then
      return name
    end
  end
  return "a rival"
end

function Civ5Ai_Apply._TeamLeaderPlayer(teamID)
  if not Civ5Ai_Apply._IsTeamId(teamID) or Teams == nil then
    return nil
  end
  local team = Teams[teamID]
  if team == nil or team.GetLeaderID == nil then
    return nil
  end
  return team:GetLeaderID()
end

function Civ5Ai_Apply._CanDeclareWarOnTeam(ourTeam, theirTeam)
  if ourTeam == nil or ourTeam.CanDeclareWar == nil or not Civ5Ai_Apply._IsTeamId(theirTeam) then
    return false
  end
  return ourTeam:CanDeclareWar(theirTeam) == true
end

function Civ5Ai_Apply._PlotCombatRivalTeam(plot, ourTeamID)
  if plot == nil then
    return nil
  end
  if plot.IsCity ~= nil and plot:IsCity() then
    local cityTeam = plot:GetTeam()
    if Civ5Ai_Apply._IsTeamId(cityTeam) and cityTeam ~= ourTeamID then
      return cityTeam
    end
  end
  local count = 0
  if plot.GetNumUnits ~= nil then
    count = plot:GetNumUnits() or 0
  end
  for i = 0, count - 1 do
    local other = nil
    if plot.GetUnit ~= nil then
      other = plot:GetUnit(i)
    end
    if other ~= nil and not other:IsDead() then
      local otherTeam = other:GetTeam()
      if Civ5Ai_Apply._IsTeamId(otherTeam) and otherTeam ~= ourTeamID then
        return otherTeam
      end
    end
  end
  return nil
end

function Civ5Ai_Apply._WarMoveTeam(unit, plot, ranged)
  if unit == nil or plot == nil then
    return nil
  end
  local ourTeamID = unit:GetTeam()
  local ourTeam = Teams[ourTeamID]
  if ranged == true and unit.GetDeclareWarRangeStrike ~= nil then
    local teamID = unit:GetDeclareWarRangeStrike(plot)
    if Civ5Ai_Apply._IsTeamId(teamID) and Civ5Ai_Apply._CanDeclareWarOnTeam(ourTeam, teamID) then
      return teamID
    end
    return nil
  end
  local revealed = nil
  if plot.GetRevealedTeam ~= nil then
    revealed = plot:GetRevealedTeam(ourTeamID)
  end
  if not Civ5Ai_Apply._IsTeamId(revealed) and plot.GetTeam ~= nil then
    revealed = plot:GetTeam()
  end
  if Civ5Ai_Apply._IsTeamId(revealed) and revealed ~= ourTeamID then
    local canEnter = true
    if unit.CanEnterTerritory ~= nil then
      canEnter = unit:CanEnterTerritory(revealed) == true
    end
    if not canEnter then
      local plotTeam = plot:GetTeam()
      if not Civ5Ai_Apply._IsTeamId(plotTeam) then
        plotTeam = revealed
      end
      if Civ5Ai_Apply._CanDeclareWarOnTeam(ourTeam, plotTeam) then
        return revealed
      end
    end
  end
  local attackTeam = Civ5Ai_Apply._PlotCombatRivalTeam(plot, ourTeamID)
  if attackTeam ~= nil and Civ5Ai_Apply._CanDeclareWarOnTeam(ourTeam, attackTeam) then
    return attackTeam
  end
  return nil
end

function Civ5Ai_Apply._NoteWarMoveBlocked(playerID, unit, rivalTeam)
  local leaderID = Civ5Ai_Apply._TeamLeaderPlayer(rivalTeam)
  local leaderName = "a rival"
  local playerToken = ""
  local cmdHint = "diplomacy.declareWar.LeaderName = apply"
  if leaderID ~= nil then
    leaderName = Civ5Ai_Apply._PlayerLeaderName(leaderID)
    playerToken = Civ5Ai_Util.PlayerId(leaderID)
    cmdHint = "diplomacy.declareWar." .. leaderName .. " = apply"
  end
  local unitId = "a unit"
  if unit ~= nil and Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._UnitWireId ~= nil then
    unitId = Civ5Ai_Snapshot._UnitWireId(unit)
  end
  local text = (
    "You tried to move "
    .. tostring(unitId)
    .. " into "
    .. leaderName
    .. "'s empire. If you wish to declare war, "
    .. cmdHint
    .. " this turn."
  )
  if #text > 200 then
    text = string.sub(text, 1, 200)
  end
  local affected = {}
  if unitId ~= "a unit" then
    table.insert(affected, unitId)
  end
  if playerToken ~= "" then
    table.insert(affected, playerToken)
  end
  local turn = 0
  if Game ~= nil and Game.GetGameTurn ~= nil then
    turn = Game.GetGameTurn() or 0
  end
  table.insert(Civ5Ai_Apply._PendingNotes, {
    turn = turn,
    kind = "WAR_MOVE_BLOCKED",
    summary = text,
    affected_ids = affected,
    player_id = playerID,
    actor_player_id = Civ5Ai_Util.PlayerId(playerID),
  })
  Civ5Ai_Util.Log(
    "apply|war_move_blocked|player="
      .. tostring(playerID)
      .. "|unit="
      .. tostring(unitId)
      .. "|rival="
      .. tostring(playerToken)
  )
end

function Civ5Ai_Apply.TakePendingNotes(playerID)
  local taken = {}
  local kept = {}
  for _, note in ipairs(Civ5Ai_Apply._PendingNotes) do
    if playerID == nil then
      table.insert(taken, note)
    elseif note.player_id == playerID then
      table.insert(taken, note)
    else
      table.insert(kept, note)
    end
  end
  Civ5Ai_Apply._PendingNotes = kept
  return taken
end


function Civ5Ai_Apply._UnitOutcomeBits(playerID, args)
  local bits = {
    unit_id = nil,
    from_x = nil,
    from_y = nil,
    hp_before = nil,
    to_x = nil,
    to_y = nil,
  }
  if args == nil then
    return bits
  end
  bits.unit_id = args.unit_id
  bits.to_x = args.target_x
  bits.to_y = args.target_y
  if bits.to_x == nil and args.x ~= nil then
    bits.to_x = args.x
    bits.to_y = args.y
  end
  local unit = nil
  if bits.unit_id ~= nil then
    unit = Civ5Ai_Apply._FindUnit(playerID, bits.unit_id)
  end
  if unit ~= nil then
    if unit.GetX ~= nil and unit.GetY ~= nil then
      bits.from_x = unit:GetX()
      bits.from_y = unit:GetY()
    end
    -- Civ5 damage is 0..max; health percent ~= 100 - damage%
    local damage = 0
    local maxHp = 100
    if unit.GetDamage ~= nil then
      damage = unit:GetDamage() or 0
    end
    if unit.GetMaxHitPoints ~= nil then
      maxHp = unit:GetMaxHitPoints() or 100
    end
    if maxHp > 0 then
      bits.hp_before = math.floor(100 * (maxHp - damage) / maxHp)
    end
  end
  return bits
end

function Civ5Ai_Apply._RecordCombatSuccess(playerID, command)
  local turn = Game ~= nil and Game.GetGameTurn ~= nil and (Game.GetGameTurn() or 0) or 0
  local kind = command ~= nil and command.kind or "combat"
  local args = command ~= nil and command.arguments or {}
  local bits = Civ5Ai_Apply._UnitOutcomeBits(playerID, args)
  local summary = tostring(kind)
  if bits.unit_id ~= nil then
    summary = summary .. " " .. tostring(bits.unit_id)
  end
  if bits.from_x ~= nil and bits.from_y ~= nil then
    summary = summary .. " from (" .. tostring(bits.from_x) .. "," .. tostring(bits.from_y) .. ")"
  end
  if bits.to_x ~= nil and bits.to_y ~= nil then
    summary = summary .. " -> (" .. tostring(bits.to_x) .. "," .. tostring(bits.to_y) .. ")"
  elseif args.target_x ~= nil and args.target_y ~= nil then
    summary = summary .. ": strike (" .. tostring(args.target_x) .. "," .. tostring(args.target_y) .. ")"
  end
  if bits.hp_before ~= nil then
    summary = summary .. " hp_before=" .. tostring(bits.hp_before) .. "%"
  end
  if args.city_id ~= nil and kind == "city_range_strike" then
    summary = summary .. " fromCity " .. tostring(args.city_id)
  end
  if #summary > 300 then
    summary = string.sub(summary, 1, 300)
  end
  local affected = Civ5Ai_Util.JsonArrayList()
  if command ~= nil then
    if command.command_id ~= nil then
      table.insert(affected, command.command_id)
    end
    if args ~= nil then
      for _, key in ipairs({ "unit_id", "city_id", "target_x", "target_y" }) do
        if args[key] ~= nil then
          table.insert(affected, tostring(args[key]))
        end
      end
    end
  end
  table.insert(Civ5Ai_Apply._PendingCommandResults, {
    turn = turn,
    kind = "combat_success",
    summary = summary,
    affected_ids = affected,
    player_id = playerID,
    actor_player_id = Civ5Ai_Util.PlayerId(playerID),
  })
end

function Civ5Ai_Apply._RecordCommandFailure(playerID, command, reason)
  local turn = Game ~= nil and Game.GetGameTurn ~= nil and (Game.GetGameTurn() or 0) or 0
  local kind = command ~= nil and command.kind or "APPLY_FAILED"
  local args = command ~= nil and command.arguments or {}
  if args ~= nil and args.unit_id ~= nil then
    Civ5Ai_Apply._failedUnits[playerID] = Civ5Ai_Apply._failedUnits[playerID] or {}
    Civ5Ai_Apply._failedUnits[playerID][tostring(args.unit_id)] = true
  end
  local bits = Civ5Ai_Apply._UnitOutcomeBits(playerID, args)
  local summary = tostring(kind) .. ": " .. tostring(reason)
  if bits.unit_id ~= nil then
    summary = summary .. " " .. tostring(bits.unit_id)
  end
  if bits.from_x ~= nil and bits.from_y ~= nil then
    summary = summary .. " from (" .. tostring(bits.from_x) .. "," .. tostring(bits.from_y) .. ")"
  end
  if bits.to_x ~= nil and bits.to_y ~= nil then
    summary = summary .. " -> (" .. tostring(bits.to_x) .. "," .. tostring(bits.to_y) .. ")"
  end
  if bits.hp_before ~= nil then
    summary = summary .. " hp_before=" .. tostring(bits.hp_before) .. "%"
  end
  if #summary > 300 then
    summary = string.sub(summary, 1, 300)
  end
  local affected = Civ5Ai_Util.JsonArrayList()
  if command ~= nil then
    if command.command_id ~= nil then
      table.insert(affected, command.command_id)
    end
    local args = command.arguments
    if args ~= nil then
      for _, key in ipairs({ "unit_id", "city_id", "build_id", "request_id" }) do
        if args[key] ~= nil then
          table.insert(affected, tostring(args[key]))
        end
      end
    end
  end
  table.insert(Civ5Ai_Apply._PendingCommandResults, {
    turn = turn,
    kind = tostring(kind),
    summary = summary,
    affected_ids = affected,
    player_id = playerID,
    actor_player_id = Civ5Ai_Util.PlayerId(playerID),
  })
end

function Civ5Ai_Apply.TakePendingCommandResults(playerID)
  local taken = {}
  local kept = {}
  for _, result in ipairs(Civ5Ai_Apply._PendingCommandResults) do
    if playerID == nil then
      table.insert(taken, result)
    elseif result.player_id == playerID then
      table.insert(taken, result)
    else
      table.insert(kept, result)
    end
  end
  Civ5Ai_Apply._PendingCommandResults = kept
  return taken
end

function Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, plot, ranged)
  local rivalTeam = Civ5Ai_Apply._WarMoveTeam(unit, plot, ranged)
  if rivalTeam == nil then
    return false
  end
  Civ5Ai_Apply._NoteWarMoveBlocked(playerID, unit, rivalTeam)
  return true
end

function Civ5Ai_Apply._OnWarMovePopup(popupInfo)
  if popupInfo == nil or ButtonPopupTypes == nil then
    return
  end
  local popupType = popupInfo.Type
  if popupType ~= ButtonPopupTypes.BUTTONPOPUP_DECLAREWARMOVE
    and popupType ~= ButtonPopupTypes.BUTTONPOPUP_DECLAREWARRANGESTRIKE then
    return
  end
  local active = Game.GetActivePlayer()
  if Civ5Ai_Config == nil or not Civ5Ai_Config.IsManagedSeat(active) then
    return
  end
  local unit = nil
  if UI ~= nil and UI.GetHeadSelectedUnit ~= nil then
    unit = UI.GetHeadSelectedUnit()
  end
  Civ5Ai_Apply._NoteWarMoveBlocked(active, unit, popupInfo.Data1)
  Civ5Ai_Apply._DismissPopupType(popupType)
  Civ5Ai_Apply._DequeuePopupPath("/InGame/GenericPopup")
  Civ5Ai_Util.Log("apply|war_move_popup|no|team=" .. tostring(popupInfo.Data1))
end

function Civ5Ai_Apply.Initialize()
  if Civ5Ai_Apply._warMoveArmed then
    return
  end
  Civ5Ai_Apply._warMoveArmed = true
  if Events ~= nil and Events.SerialEventGameMessagePopup ~= nil then
    Events.SerialEventGameMessagePopup.Add(Civ5Ai_Apply._OnWarMovePopup)
  end
  if Events ~= nil and Events.SerialEventGameMessagePopupShown ~= nil then
    Events.SerialEventGameMessagePopupShown.Add(Civ5Ai_Apply._OnInfoPopupShown)
  end
end

function Civ5Ai_Apply._MoveUnit(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local cancelledAuto = Civ5Ai_Apply._StopUnitAutomation(unit)
  local moves = 0
  if unit.MovesLeft ~= nil then
    moves = unit:MovesLeft() or 0
  end
  if moves <= 0 then
    if cancelledAuto then
      -- Soft-skip: cancel-auto does not refund moves; do not treat as a hard fail.
      return true, "automation_soft_skip_no_moves"
    end
    return false, "no_moves"
  end
  if unit.CanMove ~= nil and unit:CanMove() ~= true then
    return false, "cannot_move"
  end
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "invalid_plot"
  end
  if Civ5Ai_Apply._PlotHasFriendlyCombat(playerID, plot, unit) then
    return false, "plot_occupied"
  end
  if Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, plot, false) then
    return false, "would_declare_war"
  end
  Civ5Ai_Apply._QueueSkipIfShortMove(playerID, unit, x, y)
  local mission = Civ5Ai_Apply._Mission("MISSION_MOVE_TO")
  if Civ5Ai_Apply._UsesUiApply() then
    Civ5Ai_Apply._PrepareUnitSelection(unit)
    if Game ~= nil and Game.SelectionListMove ~= nil then
      Game.SelectionListMove(plot, false, false, false)
    end
  end
  if mission ~= nil then
    if unit.PushMission ~= nil then
      unit:PushMission(mission, x, y, 0, 0, 0)
    end
    if Civ5Ai_Apply._UsesUiApply()
        and Game ~= nil
        and Game.SelectionListGameNetMessage ~= nil
        and GameMessageTypes ~= nil then
      Game.SelectionListGameNetMessage(
        GameMessageTypes.GAMEMESSAGE_PUSH_MISSION,
        mission,
        x,
        y,
        0,
        false,
        false
      )
    end
  end
  return true, ""
end

function Civ5Ai_Apply._AttackTarget(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local cancelledAuto = Civ5Ai_Apply._StopUnitAutomation(unit)
  local moves = 0
  if unit.MovesLeft ~= nil then
    moves = unit:MovesLeft() or 0
  end
  if moves <= 0 then
    if cancelledAuto then
      return true, "automation_soft_skip_no_moves"
    end
    return false, "no_moves"
  end
  if unit.CanMove ~= nil and unit:CanMove() ~= true then
    return false, "cannot_move"
  end
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "invalid_plot"
  end
  local teamID = Players[playerID]:GetTeam()
  if plot.IsVisible ~= nil and not plot:IsVisible(teamID) then
    return false, "plot_not_visible"
  end
  if Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, plot, false) then
    return false, "would_declare_war"
  end
  local ourTeamID = unit:GetTeam()
  local rivalTeam = Civ5Ai_Apply._PlotCombatRivalTeam(plot, ourTeamID)
  local enemyCity = plot.IsEnemyCity ~= nil and plot:IsEnemyCity(unit) == true
  if rivalTeam == nil and not enemyCity then
    return false, "no_attack_target"
  end
  if unit.CanMoveInto ~= nil and unit:CanMoveInto(plot, true) ~= true then
    return false, "cannot_attack"
  end
  -- Civ5 has no MISSION_ATTACK; melee combat is a move into the enemy plot.
  Civ5Ai_Apply._QueueSkipIfShortMove(playerID, unit, x, y)
  local mission = Civ5Ai_Apply._Mission("MISSION_MOVE_TO")
  if Civ5Ai_Apply._UsesUiApply() then
    Civ5Ai_Apply._PrepareUnitSelection(unit)
    if Game ~= nil and Game.SelectionListMove ~= nil then
      Game.SelectionListMove(plot, false, false, false)
    end
  end
  if mission ~= nil then
    if unit.PushMission ~= nil then
      unit:PushMission(mission, x, y, 0, 0, 0)
    end
    if Civ5Ai_Apply._UsesUiApply()
        and Game ~= nil
        and Game.SelectionListGameNetMessage ~= nil
        and GameMessageTypes ~= nil then
      Game.SelectionListGameNetMessage(
        GameMessageTypes.GAMEMESSAGE_PUSH_MISSION,
        mission,
        x,
        y,
        0,
        false,
        false
      )
    end
  end
  return true, ""
end


function Civ5Ai_Apply._CityRangeStrike(playerID, args)
  local city = Civ5Ai_Apply._FindCity(playerID, args.city_id)
  if city == nil then
    return false, "city_not_found"
  end
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  if city.CanRangeStrike ~= nil and not city:CanRangeStrike() then
    return false, "cannot_range_strike"
  end
  if city.CanRangeStrikeAt ~= nil and not city:CanRangeStrikeAt(x, y) then
    return false, "cannot_range_strike_at"
  end
  if city.RangeStrike ~= nil then
    city:RangeStrike(x, y)
    return true, ""
  end
  if Game ~= nil and Game.SelectedCitiesGameNetMessage ~= nil
      and GameMessageTypes ~= nil and TaskTypes ~= nil then
    local plot = Map.GetPlot(city:GetX(), city:GetY())
    if UI ~= nil and plot ~= nil and UI.DoSelectCityAtPlot ~= nil then
      UI.DoSelectCityAtPlot(plot)
    end
    Game.SelectedCitiesGameNetMessage(
      GameMessageTypes.GAMEMESSAGE_DO_TASK,
      TaskTypes.TASK_RANGED_ATTACK,
      x,
      y
    )
    if UI ~= nil and UI.ClearSelectedCities ~= nil then
      UI.ClearSelectedCities()
    end
    return true, ""
  end
  return false, "range_strike_unavailable"
end

function Civ5Ai_Apply._RangeAttack(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "invalid_plot"
  end
  if Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, plot, true) then
    return false, "would_declare_war"
  end
  if unit.CanRangeStrikeAt ~= nil and not unit:CanRangeStrikeAt(x, y) then
    return false, "cannot_range_strike"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_RANGE_ATTACK")
  if mission == nil then
    return false, "mission_range_attack_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, x, y, "MISSION_RANGE_ATTACK")
  return true, ""
end

function Civ5Ai_Apply._Rebase(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  if unit.CanRebaseAt ~= nil and not unit:CanRebaseAt(0, x, y) then
    return false, "cannot_rebase"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_REBASE")
  if mission == nil then
    return false, "mission_rebase_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, x, y, "MISSION_REBASE")
  return true, ""
end

function Civ5Ai_Apply._Paradrop(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  local dest = Map.GetPlot(x, y)
  if dest ~= nil and Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, dest, false) then
    return false, "would_declare_war"
  end
  local plot = Civ5Ai_Apply._UnitPlot(unit)
  if unit.CanParadropAt ~= nil and plot ~= nil and not unit:CanParadropAt(plot, x, y) then
    return false, "cannot_paradrop"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_PARADROP")
  if mission == nil then
    return false, "mission_paradrop_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, x, y, "MISSION_PARADROP")
  return true, ""
end

function Civ5Ai_Apply._Nuke(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x, y = Civ5Ai_Apply._ResolveTargetPlot(args)
  if x == nil or y == nil then
    return false, "missing_target"
  end
  local plot = Map.GetPlot(x, y)
  if plot ~= nil and Civ5Ai_Apply._RefuseIfWarMove(playerID, unit, plot, true) then
    return false, "would_declare_war"
  end
  if unit.CanNukeAt ~= nil and not unit:CanNukeAt(x, y) then
    return false, "cannot_nuke"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_NUKE")
  if mission == nil then
    return false, "mission_nuke_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, x, y, "MISSION_NUKE")
  return true, ""
end

function Civ5Ai_Apply._AirPatrol(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_AIRPATROL", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanAirPatrol ~= nil and unit:CanAirPatrol(plot)
  end)
end

function Civ5Ai_Apply._SpreadReligion(playerID, args)
  return Civ5Ai_Apply._CurrentPlotMission(playerID, args, "MISSION_SPREAD_RELIGION")
end

function Civ5Ai_Apply._RemoveHeresy(playerID, args)
  return Civ5Ai_Apply._CurrentPlotMission(playerID, args, "MISSION_REMOVE_HERESY")
end

function Civ5Ai_Apply._Pillage(playerID, args)
  return Civ5Ai_Apply._CurrentPlotMission(playerID, args, "MISSION_PILLAGE", function(unit, plot)
    return unit.CanPillage ~= nil and unit:CanPillage(plot)
  end)
end

function Civ5Ai_Apply._CurrentPlotMission(playerID, args, missionName, gateFn)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local plot = Civ5Ai_Apply._UnitPlot(unit)
  if plot == nil then
    return false, "plot_missing"
  end
  if gateFn ~= nil and not gateFn(unit, plot) then
    return false, "cannot_execute"
  end
  local mission = Civ5Ai_Apply._Mission(missionName)
  if mission == nil then
    return false, "mission_missing"
  end
  Civ5Ai_Apply._PushSelectedMission(unit, mission, unit:GetX(), unit:GetY(), missionName)
  return true, ""
end

function Civ5Ai_Apply._UpgradeUnit(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local requested = args.unit_type_id
  if requested ~= nil and requested ~= "" and unit.GetUpgradeUnitType ~= nil then
    local row = GameInfo.Units[unit:GetUpgradeUnitType()]
    local actual = row and row.Type or nil
    if actual ~= nil and actual ~= requested then
      return false, "upgrade_type_mismatch"
    end
  end
  if CommandTypes == nil or CommandTypes.COMMAND_UPGRADE == nil then
    return false, "command_upgrade_missing"
  end
  if unit.DoCommand == nil then
    return false, "do_command_missing"
  end
  unit:DoCommand(CommandTypes.COMMAND_UPGRADE)
  return true, ""
end

function Civ5Ai_Apply._UnitSkip(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_SKIP")
end

function Civ5Ai_Apply._UnitFortify(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_FORTIFY", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanFortify ~= nil and unit:CanFortify(plot)
  end)
end

function Civ5Ai_Apply._UnitSleep(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_SLEEP", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanSleep ~= nil and unit:CanSleep(plot)
  end)
end

function Civ5Ai_Apply._UnitAlert(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_ALERT", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanSentry ~= nil and unit:CanSentry(plot)
  end)
end

function Civ5Ai_Apply._UnitHeal(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_HEAL", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanHeal ~= nil and unit:CanHeal(plot)
  end)
end

function Civ5Ai_Apply._ImproveTile(playerID, args)
  local buildId = args.build_id
  if buildId == nil or buildId == "" then
    return false, "missing_build_id"
  end
  local buildRow = GameInfo.Builds[buildId]
  if buildRow == nil then
    return false, "invalid_build_id"
  end
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local plot = Map.GetPlot(unit:GetX(), unit:GetY())
  if plot == nil then
    return false, "plot_missing"
  end
  if not Civ5Ai_Apply._HasMethod(unit, "CanBuild") or not unit:CanBuild(plot, buildRow.ID) then
    return false, "cannot_build"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_BUILD")
  if mission == nil then
    return false, "mission_build_missing"
  end
  unit:PushMission(mission, buildRow.ID)
  return true, ""
end

function Civ5Ai_Apply._ResolveAutomateId(raw)
  if raw == nil then
    return nil
  end
  if type(raw) == "number" then
    return raw
  end
  local text = tostring(raw)
  local intPart = string.match(text, "^INT_(%d+)$")
  if intPart ~= nil then
    return tonumber(intPart)
  end
  local mapped = ({
    build = "AUTOMATE_BUILD",
    explore = "AUTOMATE_EXPLORE",
  })[string.lower(text)]
  if mapped ~= nil then
    text = mapped
  end
  -- AUTOMATE_EXPLORE has no explicit <ID> in XML (autoincrement after BUILD=0).
  -- GameInfoTypes and row.ID are often nil for that row; CIV5Automates.xml is 0/1.
  if GameInfoTypes ~= nil and GameInfoTypes[text] ~= nil then
    return GameInfoTypes[text]
  end
  if GameInfo ~= nil and GameInfo.Automates ~= nil then
    local keyed = GameInfo.Automates[text]
    if keyed ~= nil and keyed.ID ~= nil then
      return keyed.ID
    end
    for row in GameInfo.Automates() do
      if row ~= nil and row.Type == text and row.ID ~= nil then
        return row.ID
      end
    end
  end
  if text == "AUTOMATE_BUILD" then
    return 0
  end
  if text == "AUTOMATE_EXPLORE" then
    return 1
  end
  return nil
end

function Civ5Ai_Apply._AutomateUnit(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local automateType = args.automate_id or args.data1_id
  Civ5Ai_Apply._PrepareUnitSelection(unit)
  -- Unit panel Explore/Build is HandleAction on GameInfoActions, not Automates.ID.
  local clicked = false
  if type(automateType) == "string" then
    clicked = Civ5Ai_Apply._HandleActionByType(unit, automateType)
  end
  local automateId = Civ5Ai_Apply._ResolveAutomateId(automateType)
  if automateId ~= nil and CommandTypes ~= nil and CommandTypes.COMMAND_AUTOMATE ~= nil then
    if unit.DoCommand ~= nil then
      unit:DoCommand(CommandTypes.COMMAND_AUTOMATE, automateId)
    end
    if Game ~= nil and Game.SelectionListGameNetMessage ~= nil
        and GameMessageTypes ~= nil and GameMessageTypes.GAMEMESSAGE_DO_COMMAND ~= nil then
      Game.SelectionListGameNetMessage(
        GameMessageTypes.GAMEMESSAGE_DO_COMMAND,
        CommandTypes.COMMAND_AUTOMATE,
        automateId,
        -1,
        0,
        false
      )
    end
  end
  if unit.IsAutomated ~= nil and unit:IsAutomated() then
    return true, ""
  end
  if automateId == nil then
    return false, "invalid_automate"
  end
  return false, "automate_not_applied"
end

function Civ5Ai_Apply._DiscoverTech(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_DISCOVER", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanDiscover ~= nil and unit:CanDiscover(plot)
  end)
end

function Civ5Ai_Apply._HurryProduction(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_HURRY", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    if plot == nil or plot.GetPlotCity == nil or plot:GetPlotCity() == nil then
      return false
    end
    return unit.GetHurryProduction ~= nil and (unit:GetHurryProduction() or 0) > 0
  end)
end

function Civ5Ai_Apply._TradeMission(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_TRADE", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanTrade ~= nil and unit:CanTrade(plot)
  end)
end

-- CIV5AI_TRADE_UNIT_COMMANDS_V1
function Civ5Ai_Apply._TradeConnectionTypeNum(typeId)
  if Civ5Ai_Snapshot ~= nil and Civ5Ai_Snapshot._TradeConnectionTypeNum ~= nil then
    return Civ5Ai_Snapshot._TradeConnectionTypeNum(typeId)
  end
  if type(typeId) == "number" then
    return typeId
  end
  if TradeConnectionTypes ~= nil and typeId ~= nil and TradeConnectionTypes[typeId] ~= nil then
    return TradeConnectionTypes[typeId]
  end
  return tonumber(typeId) or 0
end

function Civ5Ai_Apply._PushTradeMission(unit, mission, data1, data2, actionType)
  if unit == nil or mission == nil then
    return false
  end
  if Civ5Ai_Apply._UsesUiApply() then
    if actionType ~= nil then
      Civ5Ai_Apply._HandleActionByType(unit, actionType)
    end
    Civ5Ai_Apply._PrepareUnitSelection(unit)
  end
  if unit.PushMission ~= nil then
    unit:PushMission(mission, data1 or 0, data2 or 0, 0, 0, 0)
  end
  if Civ5Ai_Apply._UsesUiApply()
      and Game ~= nil
      and Game.SelectionListGameNetMessage ~= nil
      and GameMessageTypes ~= nil then
    Game.SelectionListGameNetMessage(
      GameMessageTypes.GAMEMESSAGE_PUSH_MISSION,
      mission,
      data1 or 0,
      data2 or 0,
      0,
      false,
      false
    )
  end
  return true
end

function Civ5Ai_Apply._EstablishTradeRoute(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x = tonumber(args.target_x or args.dest_x or args.plot_x)
  local y = tonumber(args.target_y or args.dest_y or args.plot_y)
  if x == nil or y == nil then
    return false, "destination_missing"
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "destination_plot_missing"
  end
  local plotIndex = plot.GetPlotIndex ~= nil and plot:GetPlotIndex() or nil
  if plotIndex == nil then
    return false, "destination_plot_index_missing"
  end
  local connType = Civ5Ai_Apply._TradeConnectionTypeNum(args.trade_connection_type)
  local unitPlot = Map.GetPlot(unit:GetX(), unit:GetY())
  if unit.CanMakeTradeRouteAt ~= nil and unitPlot ~= nil then
    if not unit:CanMakeTradeRouteAt(unitPlot, x, y, connType) then
      return false, "cannot_establish_trade_route"
    end
  elseif unit.CanMakeTradeRoute ~= nil and unitPlot ~= nil then
    if not unit:CanMakeTradeRoute(unitPlot) then
      return false, "cannot_make_trade_route"
    end
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_ESTABLISH_TRADE_ROUTE")
  if mission == nil then
    return false, "mission_missing"
  end
  Civ5Ai_Apply._PushTradeMission(unit, mission, plotIndex, connType, "MISSION_ESTABLISH_TRADE_ROUTE")
  return true, ""
end

function Civ5Ai_Apply._ChangeTradeHomeCity(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  Civ5Ai_Apply._StopUnitAutomation(unit)
  local x = tonumber(args.target_x or args.home_x or args.plot_x)
  local y = tonumber(args.target_y or args.home_y or args.plot_y)
  if x == nil or y == nil then
    return false, "home_city_missing"
  end
  local mission = Civ5Ai_Apply._Mission("MISSION_CHANGE_TRADE_UNIT_HOME_CITY")
  if mission == nil then
    return false, "mission_missing"
  end
  -- UI uses plot X/Y (not plot index) for change-home.
  Civ5Ai_Apply._PushTradeMission(unit, mission, x, y, "MISSION_CHANGE_TRADE_UNIT_HOME_CITY")
  return true, ""
end

function Civ5Ai_Apply._RecallTrader(playerID, args)
  local unit = Civ5Ai_Apply._FindUnit(playerID, args.unit_id)
  if unit == nil then
    return false, "unit_not_found"
  end
  local immediate = args.immediate == true
  if unit.RecallTrader ~= nil then
    unit:RecallTrader(immediate)
    return true, ""
  end
  return false, "recall_trader_unavailable"
end

function Civ5Ai_Apply._StartGoldenAge(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_GOLDEN_AGE", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanGoldenAge ~= nil and unit:CanGoldenAge(plot)
  end)
end

function Civ5Ai_Apply._CreateGreatWork(playerID, args)
  return Civ5Ai_Apply._UnitMission(playerID, args, "MISSION_CREATE_GREAT_WORK", function(unit)
    local plot = Civ5Ai_Apply._UnitPlot(unit)
    return plot ~= nil and unit.CanCreateGreatWork ~= nil and unit:CanCreateGreatWork(plot)
  end)
end

function Civ5Ai_Apply._PolicyBranchUnlocked(player, policyRow)
  if player == nil or policyRow == nil then
    return false
  end
  if policyRow.PolicyBranchType == nil or GameInfo.PolicyBranchTypes == nil then
    return true
  end
  local branchRow = GameInfo.PolicyBranchTypes[policyRow.PolicyBranchType]
  if branchRow == nil or player.IsPolicyBranchUnlocked == nil then
    return true
  end
  return player:IsPolicyBranchUnlocked(branchRow.ID) == true
end

function Civ5Ai_Apply._AdoptSocialPolicy(playerID, args)
  local policyId = args.policy_id
  if policyId == nil or policyId == "" then
    return false, "missing_policy_id"
  end
  local row = GameInfo.Policies[policyId]
  if row == nil then
    return false, "invalid_policy"
  end
  local player = Players[playerID]
  if player == nil then
    return false, "player_missing"
  end
  if not Civ5Ai_Apply._PolicyBranchUnlocked(player, row) then
    return false, "branch_not_unlocked"
  end
  if not player:CanAdoptPolicy(row.ID) then
    return false, "cannot_adopt_policy"
  end
  -- Live t76 P0: DoAdoptPolicy logged ok but culture/blocking=0 (POLICY) stayed.
  -- Stock SocialPolicyPopup uses Network.SendUpdatePolicies for local human.
  local usedNet = false
  if Network ~= nil and Network.SendUpdatePolicies ~= nil then
    Network.SendUpdatePolicies(row.ID, true, true)
    usedNet = true
  elseif player.DoAdoptPolicy ~= nil then
    player:DoAdoptPolicy(row.ID)
  else
    return false, "do_adopt_policy_missing"
  end
  Civ5Ai_Apply._DismissPolicyPopup()
  if ButtonPopupTypes ~= nil and ButtonPopupTypes.BUTTONPOPUP_CHOOSEPOLICY ~= nil then
    Civ5Ai_Apply._DismissPopupType(ButtonPopupTypes.BUTTONPOPUP_CHOOSEPOLICY)
  end
  Civ5Ai_Apply._DequeuePopupPath("/InGame/SocialPolicyPopup")
  Civ5Ai_Apply._DequeuePopupPath("/InGame/Popups/SocialPolicyPopup")
  if player.GetEndTurnBlockingNotificationIndex ~= nil
      and UI ~= nil
      and UI.RemoveNotification ~= nil then
    local idx = player:GetEndTurnBlockingNotificationIndex()
    if idx ~= nil and idx >= 0 then
      UI.RemoveNotification(idx)
    end
  end
  if Events ~= nil and Events.SerialEventEndTurnDirty ~= nil then
    Events.SerialEventEndTurnDirty()
  end
  Civ5Ai_Util.Log(
    "apply|adopt_policy|player="
      .. tostring(playerID)
      .. "|policy="
      .. tostring(policyId)
      .. "|net="
      .. tostring(usedNet)
  )
  return true, ""
end
