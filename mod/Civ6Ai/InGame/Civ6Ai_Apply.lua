-- Civ6Ai apply: execute validated decision commands and emit apply-results.jsonl.
Civ6Ai_Apply = Civ6Ai_Apply or {}

function Civ6Ai_Apply._IsNetworkMultiplayer()
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    return GameConfiguration.IsNetworkMultiplayer()
  end
  return false
end

-- Non-local seats in single player: UI operations (UnitManager/CityManager/
-- UI.RequestPlayerOperation) are only honoured for the local player, so these
-- seats use the GameCore routes exposed as ExposedMembers.Civ6Ai.*ForPlayer.
-- Commands without a GameCore route fail individually with a *_requires_local_player reason.
function Civ6Ai_Apply._UseGameCoreRoute(playerID)
  if Civ6Ai_Apply._IsNetworkMultiplayer() then
    return false
  end
  return Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() ~= playerID
end

-- pcall an ExposedMembers.Civ6Ai GameCore route. Returns ok(bool), reason(string).
function Civ6Ai_Apply._GameCore(name, ...)
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  local fn = routes ~= nil and routes[name] or nil
  if fn == nil then
    return false, "gamecore_unavailable:" .. tostring(name)
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local okCall, ok, reason = pcall(function()
    return fn(unpackFn(args))
  end)
  if not okCall then
    return false, "gamecore_error:" .. tostring(ok)
  end
  if ok then
    return true, reason or ""
  end
  return false, reason or (tostring(name) .. "_rejected")
end

function Civ6Ai_Apply._ApplyResultsPath(playerID)
  local sessionId = Civ6Ai_Bridge.SessionId()
  local root = Civ6Ai_Config.RootDir()
  local playerLabel = "PLAYER_" .. tostring(playerID)
  return Civ6Ai_Util.JoinPath(root, "sessions", sessionId, playerLabel, "apply-results.jsonl")
end

function Civ6Ai_Apply._RecordResult(playerID, command, ok, reason, fixedArgs)
  local turn = Game.GetCurrentGameTurn()
  local payload = {
    event = "apply_result",
    turn = turn,
    player_id = "PLAYER_" .. tostring(playerID),
    command_id = command and command.command_id or "",
    kind = command and command.kind or "",
    ok = ok,
    reason = reason or "",
    fixed_arguments = fixedArgs or {},
    empire = Civ6Ai_Snapshot.EmpireTelemetry(playerID),
  }
  Civ6Ai_Util.AppendJsonLine(Civ6Ai_Apply._ApplyResultsPath(playerID), payload)
end

-- snapshotTurn: the turn of the snapshot the decision answers (default: now).
-- A seat other than the local one plays it at its next turn start: the orders
-- go out on the synced channel (every PC makes the same change) for turn
-- forTurn, and results are recorded when they come back. forTurn defaults to
-- Civ6Ai_Bridge.SeatForTurn: snapshotTurn in single player when the seat's
-- turn snapshotTurn has not started yet (same-turn timing), else snapshotTurn + 1.

-- Unit attacks and city strikes before moves, same rule as the synced
-- gameplay queue. Stable: attacks keep their order, then everything else.
function Civ6Ai_Apply._AttacksBeforeMoves(commands)
  local attacks, rest = {}, {}
  for _, command in ipairs(commands or {}) do
    local kind = command.kind
    if kind == "attack_target" or kind == "city_attack" or kind == "range_attack" or kind == "melee_attack" then
      attacks[#attacks + 1] = command
    else
      rest[#rest + 1] = command
    end
  end
  for _, command in ipairs(rest) do
    attacks[#attacks + 1] = command
  end
  return attacks
end

function Civ6Ai_Apply._CountAttacks(commands)
  local unit, city = 0, 0
  for _, command in ipairs(commands or {}) do
    local kind = command.kind
    if kind == "attack_target" or kind == "range_attack" or kind == "melee_attack" then
      unit = unit + 1
    elseif kind == "city_attack" then
      city = city + 1
    end
  end
  return unit, city
end

function Civ6Ai_Apply._LogAttacks(playerID, turn, field, unit, city, failed)
  local message = "attacks|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn)
    .. "|" .. field .. "=" .. tostring(unit + city)
    .. "|unit=" .. tostring(unit) .. "|city=" .. tostring(city)
  if failed ~= nil then
    message = message .. "|failed=" .. tostring(failed)
  end
  Civ6Ai_Util.Log(message)
end

function Civ6Ai_Apply.ApplyDecision(playerID, decision, snapshotTurn, forTurn)
  if decision == nil or decision.commands == nil then
    Civ6Ai_Util.Log("apply|no_commands|player=" .. tostring(playerID))
    return
  end
  decision.commands = Civ6Ai_Apply._AttacksBeforeMoves(decision.commands)
  local orderedUnit, orderedCity = Civ6Ai_Apply._CountAttacks(decision.commands)
  local rest = decision.commands
  if playerID ~= Game.GetLocalPlayer() then
    if forTurn == nil then
      if Civ6Ai_Bridge ~= nil and Civ6Ai_Bridge.SeatForTurn ~= nil then
        forTurn = Civ6Ai_Bridge.SeatForTurn(playerID, snapshotTurn)
      else
        forTurn = (snapshotTurn or Game.GetCurrentGameTurn()) + 1
      end
    end
    local sent = Civ6Ai_OrderChannel.SendDecision(playerID, decision, forTurn, snapshotTurn)
    Civ6Ai_Util.Log("apply|order_channel|player=" .. tostring(playerID) .. "|for_turn=" .. tostring(forTurn)
      .. "|sent=" .. tostring(sent))
    Civ6Ai_Apply._LogAttacks(playerID, forTurn, "ordered", orderedUnit, orderedCity)
    return
  end
  if Civ6Ai_Apply._IsNetworkMultiplayer() then
    local synced, here = {}, {}
    for _, c in ipairs(rest) do
      table.insert(Civ6Ai_Apply.SYNCED_KINDS[c.kind] and synced or here, c)
    end
    if #synced > 0 then
      Civ6Ai_OrderChannel.SendDecision(playerID, { commands = synced }, Game.GetCurrentGameTurn(), snapshotTurn)
    end
    decision = { commands = here }
  end
  Civ6Ai_Apply._orderedUnits = Civ6Ai_Apply._orderedUnits or {}
  Civ6Ai_Apply._orderedUnits[playerID] = {}
  local commands = decision.commands
  Civ6Ai_Apply._LogAttacks(playerID, forTurn or snapshotTurn or Game.GetCurrentGameTurn(), "ordered", orderedUnit, orderedCity)
  local maxPasses = 4
  local pending = {}
  for _, command in ipairs(commands) do
    table.insert(pending, command)
  end
  local executedUnit, executedCity, failedAttacks = 0, 0, 0
  local function noteLocal(command, ok)
    local kind = command.kind
    local attack = kind == "attack_target" or kind == "city_attack" or kind == "range_attack" or kind == "melee_attack"
    if not attack then
      return
    end
    if ok then
      if kind == "city_attack" then
        executedCity = executedCity + 1
      else
        executedUnit = executedUnit + 1
      end
    else
      failedAttacks = failedAttacks + 1
    end
  end
  for passIndex = 1, maxPasses do
    if #pending == 0 then
      break
    end
    local nextPending = {}
    local progress = false
    for _, command in ipairs(pending) do
      local ok, reason, fixedArgs = Civ6Ai_Apply._ApplyCommand(playerID, command)
      local deferred = reason == Civ6Ai_Apply.DEFERRED
      if not deferred then
        Civ6Ai_Apply._RecordResult(playerID, command, ok, reason, fixedArgs)
      end
      if deferred then
        progress = true
        Civ6Ai_Util.Log("apply|deferred|" .. tostring(command.kind) .. "|" .. tostring(command.command_id))
      elseif ok then
        progress = true
        noteLocal(command, true)
        local unitId = (command.arguments and command.arguments.unit_id) or (fixedArgs and fixedArgs.unit_id)
        if unitId ~= nil then
          local numeric = Civ6Ai_Apply._ParseUnitNumericId(unitId)
          if numeric ~= nil then
            Civ6Ai_Apply._orderedUnits[playerID][numeric] = true
          end
        end
        Civ6Ai_Util.Log("apply|ok|" .. tostring(command.kind) .. "|" .. tostring(command.command_id))
      else
        local retryable = Civ6Ai_Apply._IsPlotOccupiedRetryable(command.kind, reason)
        if retryable and passIndex < maxPasses then
          table.insert(nextPending, command)
          Civ6Ai_Util.Log(
            "apply|retry_plot_occupied|pass="
              .. tostring(passIndex)
              .. "|"
              .. tostring(command.kind)
              .. "|"
              .. tostring(command.command_id)
          )
        else
          noteLocal(command, false)
          Civ6Ai_Util.Log("apply|fail|" .. tostring(command.kind) .. "|" .. tostring(reason))
        end
      end
    end
    if not progress then
      for _, command in ipairs(nextPending) do
        noteLocal(command, false)
        Civ6Ai_Util.Log(
          "apply|fail|"
            .. tostring(command.kind)
            .. "|plot_occupied_exhausted|"
            .. tostring(command.command_id)
        )
      end
      break
    end
    pending = nextPending
  end
  Civ6Ai_Apply._LogAttacks(
    playerID, forTurn or snapshotTurn or Game.GetCurrentGameTurn(),
    "executed", executedUnit, executedCity, failedAttacks)
end

-- Retry a move/attack in a later pass only when another unit was in the way (it
-- may move off during this apply). Rejected or impossible orders are not retried:
-- re-issuing them is what spent P0's movement on turn 25 (operation_rejected ->
-- retry -> no_moves_left -> plot_occupied_exhausted).
function Civ6Ai_Apply._IsPlotOccupiedRetryable(kind, reason)
  if kind ~= "move_unit" and kind ~= "attack_target" then
    return false
  end
  local text = tostring(reason or "")
  return text == "plot_occupied"
    or string.find(text, "stack_limit", 1, true) ~= nil
    or string.find(text, "occupied", 1, true) ~= nil
end

function Civ6Ai_Apply._TrySkipUnit(unit)
  if unit == nil then
    return false
  end
  if GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
    local skipOp = GameInfo.UnitOperations["UNITOPERATION_SKIP_TURN"]
    if skipOp ~= nil and UnitManager.RequestOperation(unit, skipOp.Hash) then
      return true
    end
  end
  if UnitOperationTypes ~= nil and UnitOperationTypes.SKIP_TURN ~= nil then
    if UnitManager.RequestOperation(unit, UnitOperationTypes.SKIP_TURN) then
      return true
    end
  end
  -- A direct FinishMoves from the interface changes this PC only; in a
  -- network game that would desync, so only the synced operations count there.
  if UnitManager ~= nil and UnitManager.FinishMoves ~= nil and not Civ6Ai_Apply._IsNetworkMultiplayer() then
    UnitManager.FinishMoves(unit)
    return true
  end
  return false
end

function Civ6Ai_Apply._WithLocalPlayer(playerID, fn)
  if Civ6Ai_Apply._IsNetworkMultiplayer() and Game.GetLocalPlayer() ~= playerID then
    return false, "local_player_swap_blocked_mp"
  end
  local origPlayer = Game.GetLocalPlayer()
  local results = {false, "no_result"}
  local ok, err = pcall(function()
    if origPlayer ~= playerID then
      if PlayerManager == nil or PlayerManager.SetLocalPlayerAndObserver == nil then
        error("player_manager_unavailable")
      end
      PlayerManager.SetLocalPlayerAndObserver(playerID)
    end
    results[1], results[2] = fn()
  end)
  pcall(function()
    if origPlayer ~= nil and origPlayer ~= playerID
        and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
      PlayerManager.SetLocalPlayerAndObserver(origPlayer)
    end
  end)
  if not ok then
    return false, tostring(err)
  end
  return results[1], results[2]
end

function Civ6Ai_Apply._UnitWasOrdered(playerID, unit)
  if unit == nil then
    return false
  end
  local ordered = Civ6Ai_Apply._orderedUnits and Civ6Ai_Apply._orderedUnits[playerID]
  if ordered == nil then
    return false
  end
  return ordered[unit:GetID()] == true
end

function Civ6Ai_Apply._ParseUnitNumericId(unitId)
  local text = tostring(unitId or "")
  local fromPrefix = string.match(text, "^UNIT_(%d+)$")
  if fromPrefix ~= nil then
    return tonumber(fromPrefix)
  end
  -- The owner-qualified form other players' units use (UNIT_<owner>_<id>).
  local qualified = string.match(text, "^UNIT_%d+_(%d+)$")
  if qualified ~= nil then
    return tonumber(qualified)
  end
  return tonumber(text)
end

function Civ6Ai_Apply._FindUnit(playerID, unitId)
  local numericId = Civ6Ai_Apply._ParseUnitNumericId(unitId)
  if numericId == nil then
    return nil
  end
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  return player:GetUnits():FindID(numericId)
end

function Civ6Ai_Apply._MoveUnitGameCore(playerID, unitNumericId, x, y)
  -- A far destination walks the engine's own route (UnitManager.GetMoveToPath)
  -- until the unit's moves run out; an adjacent one is a single checked step.
  local route = "MoveUnitForPlayer"
  local unit = Civ6Ai_Apply._FindUnit(playerID, "UNIT_" .. tostring(unitNumericId))
  if unit ~= nil and Map ~= nil and Map.GetPlotDistance ~= nil then
    local okDist, dist = pcall(Map.GetPlotDistance, unit:GetX(), unit:GetY(), x, y)
    if okDist and type(dist) == "number" and dist > 1 then
      route = "MoveUnitAlongPathForPlayer"
    end
  end
  local ok, reason = Civ6Ai_Apply._GameCore(route, playerID, unitNumericId, x, y)
  if ok then
    Civ6Ai_Util.Log(
      "apply|script_move|ok|player="
        .. tostring(playerID)
        .. "|unit="
        .. tostring(unitNumericId)
        .. "|plot="
        .. tostring(x)
        .. ","
        .. tostring(y)
        .. "|note="
        .. tostring(reason or "")
    )
    return true, reason or ""
  end
  Civ6Ai_Util.Log(
    "apply|script_move|fail|player="
      .. tostring(playerID)
      .. "|reason="
      .. tostring(reason or "rejected")
  )
  return false, reason or "script_move_rejected"
end

function Civ6Ai_Apply._ResolveUnitsGameCore(playerID)
  if ExposedMembers == nil or ExposedMembers.Civ6Ai == nil or ExposedMembers.Civ6Ai.ResolvePlayerUnits == nil then
    return false, 0
  end
  local count = ExposedMembers.Civ6Ai.ResolvePlayerUnits(playerID)
  return true, count
end

function Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
  local player = Players[playerID]
  if player == nil then
    Civ6Ai_Util.Log("apply|resolve_units|player=" .. tostring(playerID) .. "|ok=false|no_player")
    return false
  end
  if Game.GetLocalPlayer() == playerID
      or (not Civ6Ai_Apply._IsNetworkMultiplayer()
        and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil) then
    local ok, reason = Civ6Ai_Apply._WithLocalPlayer(playerID, function()
      local units = player:GetUnits()
      if units == nil then
        return true, 0
      end
      local count = 0
      for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(units)) do
        if Civ6Ai_Snapshot._UnitNeedsOrders(unit) and not Civ6Ai_Apply._UnitWasOrdered(playerID, unit) then
          Civ6Ai_Apply._TrySkipUnit(unit)
          count = count + 1
        end
      end
      return true, count
    end)
    if ok then
      if tonumber(reason) and tonumber(reason) > 0 then
        Civ6Ai_Util.Log(
          "apply|resolve_units|player=" .. tostring(playerID) .. "|ok=true|resolved=" .. tostring(reason)
        )
      end
      return true
    end
  end
  if Civ6Ai_Apply._IsNetworkMultiplayer() then
    Civ6Ai_Util.Log("apply|resolve_units|player=" .. tostring(playerID) .. "|ok=false|mp_local_skip_failed")
    return false
  end
  local gcOk, gcCount = Civ6Ai_Apply._ResolveUnitsGameCore(playerID)
  if gcOk and gcCount > 0 then
    Civ6Ai_Util.Log(
      "apply|resolve_units|player=" .. tostring(playerID) .. "|ok=true|gamecore_resolved=" .. tostring(gcCount)
    )
    return true
  end
  Civ6Ai_Util.Log("apply|resolve_units|player=" .. tostring(playerID) .. "|ok=false|no_units_cleared")
  return false
end

function Civ6Ai_Apply._ApplyCommand(playerID, command)
  if command == nil or command.kind == nil then
    return false, "missing_kind", {}
  end
  local args = command.arguments or {}
  if command.kind == "set_research_tech" then
    return Civ6Ai_Apply._SetResearchTech(playerID, args)
  end
  if command.kind == "set_research_civic" then
    return Civ6Ai_Apply._SetResearchCivic(playerID, args)
  end
  if command.kind == "move_unit" then
    return Civ6Ai_Apply._MoveUnit(playerID, args)
  end
  if command.kind == "queue_production" then
    return Civ6Ai_Apply._QueueProduction(playerID, args)
  end
  if command.kind == "unit_skip" then
    return Civ6Ai_Apply._UnitSkip(playerID, args)
  end
  if command.kind == "unit_posture_fortify" then
    return Civ6Ai_Apply._UnitFortify(playerID, args)
  end
  if command.kind == "found_city" then
    return Civ6Ai_Apply._FoundCity(playerID, args)
  end
  if command.kind == "attack_target" then
    return Civ6Ai_Apply._AttackTarget(playerID, args)
  end
  if command.kind == "send_diplomatic_action" or command.kind == "execute_deal"
      or command.kind == "send_envoy"
      or command.kind == "purchase_item" or command.kind == "purchase_tile" then
    return Civ6Ai_Apply._Deal(playerID, command, args)
  end
  if command.kind == "explore" then
    return Civ6Ai_Apply._Work(playerID, command, args)
  end
  if command.kind == "trade_route" then
    local f, why = Civ6Ai_OrderChannel._Fields(playerID, command)
    if f == nil then
      return false, why, args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("MakeTradeRoute", playerID, f.U, f.I)
    return ok, reason, args
  end
  if command.kind == "activate_great_person" or command.kind == "upgrade_unit" or command.kind == "promote_unit"
      or command.kind == "join_formation" or command.kind == "city_attack" or command.kind == "build_fort"
      or command.kind == "worker_improve" or command.kind == "spread_religion" then
    local f, why = Civ6Ai_OrderChannel._Fields(playerID, command)
    if f == nil then
      return false, why, args
    end
    local route = ({ [26] = { "ActivateGreatPerson", f.U, f.V }, [27] = { "UpgradeUnit", f.U, f.I, f.V },
      [28] = { "PromoteUnit", f.U, f.I }, [29] = { "JoinFormation", f.U, f.I },
      [31] = { "CityStrike", f.I, f.X, f.Y }, [32] = { "BuildFort", f.U, f.I }, [21] = { "BuildImprovement", f.U, f.I },
      [35] = { "SpreadReligion", f.U, f.X, f.Y, f.A } })[f.K]
    local ok, reason = Civ6Ai_Apply._GovRoute(route[1], playerID, route[2], route[3], route[4])
    return ok, reason, args
  end
  if command.kind == "pillage_improvement" then
    return Civ6Ai_Apply._Work(playerID, command, args)
  end
  if Civ6Ai_Apply.GOV_KINDS ~= nil and Civ6Ai_Apply.GOV_KINDS[command.kind] then
    return Civ6Ai_Apply._Governance(playerID, command, args)
  end
  return false, "unsupported_kind", args
end

function Civ6Ai_Apply._RequestPlayerOperation(playerID, opType, params)
  if UI == nil or UI.RequestPlayerOperation == nil then
    return false, "ui_unavailable"
  end
  -- UI.RequestPlayerOperation returns no value; only an error means it failed.
  local ok = pcall(UI.RequestPlayerOperation, playerID, opType, params or {})
  if ok then
    return true, ""
  end
  return false, "request_rejected"
end

function Civ6Ai_Apply._SetResearchTech(playerID, args)
  local techId = args.tech_id
  if techId == nil or techId == "" then
    return false, "missing_tech_id", args
  end
  local hash = GameInfo.Technologies[techId]
  if hash == nil then
    return false, "invalid_tech", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    local gcOk, gcReason = Civ6Ai_Apply._GameCore("SetResearchForPlayer", playerID, hash.Index)
    if gcOk then
      Civ6Ai_Util.Log("apply|research|gamecore|player=" .. tostring(playerID) .. "|tech=" .. tostring(techId))
      return true, "", args
    end
    return false, gcReason or "research_rejected", args
  end
  local params = {}
  if PlayerOperationTypes ~= nil then
    -- Firaxis TechTree passes the tech Hash (not Index) and an insert mode.
    params[PlayerOperationTypes.PARAM_TECH_TYPE] = hash.Hash
    params[PlayerOperationTypes.PARAM_INSERT_MODE] = PlayerOperationTypes.VALUE_EXCLUSIVE
    local ok, reason = Civ6Ai_Apply._RequestPlayerOperation(playerID, PlayerOperationTypes.RESEARCH, params)
    if ok then
      return true, "", args
    end
  end
  return false, "research_rejected", args
end

function Civ6Ai_Apply._SetResearchCivic(playerID, args)
  local civicId = args.civic_id or args.tech_id
  if civicId == nil or civicId == "" then
    return false, "missing_civic_id", args
  end
  local hash = GameInfo.Civics[civicId]
  if hash == nil then
    return false, "invalid_civic", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    local gcOk, gcReason = Civ6Ai_Apply._GameCore("SetCivicForPlayer", playerID, hash.Index)
    if gcOk then
      Civ6Ai_Util.Log("apply|civic|gamecore|player=" .. tostring(playerID) .. "|civic=" .. tostring(civicId))
      return true, "", args
    end
    return false, gcReason or "civic_rejected", args
  end
  local params = {}
  if PlayerOperationTypes ~= nil then
    params[PlayerOperationTypes.PARAM_CIVIC_TYPE] = hash.Hash
    params[PlayerOperationTypes.PARAM_INSERT_MODE] = PlayerOperationTypes.VALUE_EXCLUSIVE
    local ok = Civ6Ai_Apply._RequestPlayerOperation(playerID, PlayerOperationTypes.PROGRESS_CIVIC, params)
    if ok then
      return true, "", args
    end
  end
  -- The local seat has no PlayerOperationTypes in this UI context
  -- (player_ops_unavailable); set the civic through GameCore like research does.
  local gcOk, gcReason = Civ6Ai_Apply._GameCore("SetCivicForPlayer", playerID, hash.Index)
  if gcOk then
    Civ6Ai_Util.Log("apply|civic|gamecore|player=" .. tostring(playerID) .. "|civic=" .. tostring(civicId))
    return true, "", args
  end
  return false, gcReason or "civic_rejected", args
end

function Civ6Ai_Apply._ResolveTargetCoords(args)
  local x = args.target_x
  local y = args.target_y
  if x == nil or y == nil then
    x, y = args.x, args.y
  end
  if x ~= nil and y ~= nil then
    return tonumber(x), tonumber(y)
  end
  local plotId = args.plot_id
  if plotId ~= nil then
    return Civ6Ai_Apply._ParsePlotId(plotId)
  end
  return nil, nil
end

function Civ6Ai_Apply._CanStartUnitOperation(unit, op, plot, params)
  if UnitManager.CanStartOperation == nil then
    return true
  end
  if plot ~= nil then
    if UnitManager.CanStartOperation(unit, op, plot, true) then
      return true
    end
  end
  if params ~= nil then
    -- Firaxis UI (WorldInput, Civ6Common) uses four arguments. A fifth false is
    -- not that check: UnitPanel's fifth argument asks for a results table, and
    -- false here rejects a legal targeted operation.
    if UnitManager.CanStartOperation(unit, op, nil, params) then
      return true
    end
  end
  return UnitManager.CanStartOperation(unit, op, nil, true)
end

function Civ6Ai_Apply._RequestUnitOperation(unit, op, params, probeLabel, plot)
  if unit == nil or op == nil then
    return false, "missing_unit_or_op"
  end
  params = params or {}
  if not Civ6Ai_Apply._CanStartUnitOperation(unit, op, plot, params) then
    if probeLabel ~= nil then
      Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|fail|illegal")
    end
    return false, "operation_illegal"
  end
  if UnitManager.RequestOperation == nil then
    return false, "operation_rejected"
  end
  UnitManager.RequestOperation(unit, op, params)
  if probeLabel ~= nil then
    Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|ok")
  end
  return true, ""
end

function Civ6Ai_Apply._MoveUnit(playerID, args)
  local unitId = args.unit_id
  local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
  if unitId == nil or x == nil or y == nil then
    return false, "missing_unit_or_target", args
  end
  local numericId = Civ6Ai_Apply._ParseUnitNumericId(unitId)
  local unit = Civ6Ai_Apply._FindUnit(playerID, unitId)
  if unit == nil then
    return false, "unit_not_found", args
  end
  if args.improvement_id ~= nil and (unit:GetX() ~= x or unit:GetY() ~= y)
      and Civ6Ai_OrderChannel ~= nil and Civ6Ai_OrderChannel.SendDecision ~= nil then
    -- Improve(x,y) away from the tile: a synced goal move, so gameplay keeps walking
    -- the builder there on later turns and builds on arrival (a local move would not).
    local a2 = {}
    for k, v in pairs(args) do a2[k] = v end
    a2.intent, a2.goal = "improve", 1
    local n = Civ6Ai_OrderChannel.SendDecision(playerID, {commands = {{kind = "move_unit", arguments = a2,
      command_id = "CMD_" .. tostring(args.unit_id) .. "_improve_goal"}}}, Game.GetCurrentGameTurn())
    return (n or 0) > 0, "sent_synced_goal", args
  end
  if unit:GetX() == x and unit:GetY() == y and args.improvement_id ~= nil then
    -- Improve(x,y) on the builder's own tile: build now instead of "already_there".
    local f, why = Civ6Ai_OrderChannel._Fields(playerID, {kind = "worker_improve", arguments = args})
    if f == nil then
      return false, why, args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("BuildImprovement", playerID, f.U, f.I)
    return ok, reason, args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    if numericId == nil then
      return false, "missing_unit_numeric_id", args
    end
    local gcOk, gcReason = Civ6Ai_Apply._MoveUnitGameCore(playerID, numericId, x, y)
    if gcOk then
      return true, gcReason or "", args
    end
    return false, gcReason or "script_move_rejected", args
  end
  -- Local seat. One route per order: the GameCore script move is synchronous and
  -- its result is checked (plot changed, movement restored on failure). The old
  -- ladder fired UnitManager.RequestOperation(MOVE_TO) three times (it returns
  -- nothing, which read as "rejected"), then the script move, then the UI order
  -- again: several competing orders for one unit, and a step it could not take
  -- this turn left it in place with 0 moves.
  if numericId ~= nil then
    local scriptOk, scriptReason = Civ6Ai_Apply._MoveUnitGameCore(playerID, numericId, x, y)
    if scriptOk then
      return true, scriptReason or "", args
    end
    if string.find(tostring(scriptReason or ""), "gamecore_unavailable", 1, true) == nil then
      return false, scriptReason or "script_move_rejected", args
    end
  end
  return Civ6Ai_Apply._RequestMoveUi(unit, x, y, args)
end

-- UI MOVE_TO for the local seat when the GameCore route is missing. Issued once.
-- UnitManager.RequestOperation returns nothing and runs asynchronously, so the
-- result is "ui_move_requested" unless the unit is already on the target.
function Civ6Ai_Apply._RequestMoveUi(unit, x, y, args)
  if UnitManager == nil or UnitManager.RequestOperation == nil or UnitOperationTypes == nil then
    return false, "move_unavailable", args
  end
  local params = {}
  params[UnitOperationTypes.PARAM_X] = x
  params[UnitOperationTypes.PARAM_Y] = y
  local moveOp = UnitOperationTypes.MOVE_TO
  if UnitManager.CanStartOperation ~= nil and not UnitManager.CanStartOperation(unit, moveOp, nil, params) then
    Civ6Ai_Util.Log("apply|probe|move|fail|illegal")
    return false, "operation_illegal", args
  end
  local ok, result = pcall(UnitManager.RequestOperation, unit, moveOp, params)
  if not ok or result == false then
    Civ6Ai_Util.Log("apply|probe|move|fail|rejected")
    return false, "operation_rejected", args
  end
  if unit:GetX() == x and unit:GetY() == y then
    return true, "", args
  end
  Civ6Ai_Util.Log("apply|probe|move|requested")
  return true, "ui_move_requested", args
end

function Civ6Ai_Apply._UnitSkip(playerID, args)
  local unitId = args.unit_id
  if unitId == nil then
    return false, "missing_unit_id", args
  end
  local unit = Civ6Ai_Apply._FindUnit(playerID, unitId)
  if unit == nil then
    return false, "unit_not_found", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    local gcOk, gcReason = Civ6Ai_Apply._GameCore("FinishMovesForPlayer", playerID, unit:GetID())
    return gcOk, gcReason or "", args
  end
  Civ6Ai_Apply._TrySkipUnit(unit)
  return true, "", args
end

function Civ6Ai_Apply._FoundCityOperation(unit)
  if unit == nil then
    return nil
  end
  if UnitOperationTypes ~= nil and UnitOperationTypes.FOUND_CITY ~= nil then
    return UnitOperationTypes.FOUND_CITY
  end
  if GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
    local row = GameInfo.UnitOperations["UNITOPERATION_FOUND_CITY"]
    if row ~= nil then
      return row.Hash
    end
  end
  return nil
end

function Civ6Ai_Apply._ScheduleFoundCityFollowup(playerID)
  if Civ6Ai_Autotest == nil or not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Util.ScheduleTick(function()
    Civ6Ai_Autotest._DismissCityNamePopups()
    Civ6Ai_Autotest._CloseQueuedPopups()
    return false
  end)
end

function Civ6Ai_Apply._FoundCity(playerID, args)
  local unitId = args.unit_id
  if unitId == nil then
    return false, "missing_unit_id", args
  end
  local unit = Civ6Ai_Apply._FindUnit(playerID, unitId)
  if unit == nil then
    return false, "unit_not_found", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    local gcOk, gcReason = Civ6Ai_Apply._GameCore("FoundCityForPlayer", playerID, unit:GetID())
    if gcOk then
      Civ6Ai_Apply._ScheduleFoundCityFollowup(playerID)
      Civ6Ai_Util.Log("apply|found_city|gamecore|player=" .. tostring(playerID))
      return true, "", args
    end
    return false, gcReason or "found_city_rejected", args
  end
  local op = Civ6Ai_Apply._FoundCityOperation(unit)
  if op == nil then
    return false, "found_city_op_missing", args
  end
  local ok, reason = Civ6Ai_Apply._RequestUnitOperation(unit, op, {}, "found_city")
  if ok then
    Civ6Ai_Apply._ScheduleFoundCityFollowup(playerID)
    return true, "", args
  end
  if not Civ6Ai_Apply._IsNetworkMultiplayer() then
    local fallbackOk, fallbackReason = Civ6Ai_Apply._WithLocalPlayer(playerID, function()
      local localUnit = Civ6Ai_Apply._FindUnit(playerID, unitId)
      if localUnit == nil then
        return false, "unit_not_found"
      end
      if UI ~= nil and UI.SelectUnit ~= nil then
        UI.SelectUnit(localUnit)
      end
      return Civ6Ai_Apply._RequestUnitOperation(localUnit, op, {}, nil)
    end)
    if fallbackOk then
      Civ6Ai_Apply._ScheduleFoundCityFollowup(playerID)
      Civ6Ai_Util.Log("apply|found_city|sp_local_player_fallback|player=" .. tostring(playerID))
      return true, "", args
    end
    reason = fallbackReason or reason
  end
  return false, reason or "found_city_rejected", args
end

-- The operation Civ6Common.RequestMoveOperation would issue for a strike on
-- x,y. CanStartOperation is the four-argument form (unit, op, nil, params).
-- Returns op, params, or nil when none of those operations can start.
function Civ6Ai_Apply._AttackParams(x, y, modifiers)
  local params = {}
  if UnitOperationTypes == nil then
    return params
  end
  params[UnitOperationTypes.PARAM_X] = x
  params[UnitOperationTypes.PARAM_Y] = y
  if modifiers ~= nil and UnitOperationTypes.PARAM_MODIFIERS ~= nil then
    params[UnitOperationTypes.PARAM_MODIFIERS] = modifiers
  end
  return params
end

function Civ6Ai_Apply._CanStartParams(unit, op, params)
  if unit == nil or op == nil then
    return false
  end
  if UnitManager == nil or UnitManager.CanStartOperation == nil then
    return true
  end
  local ok, can = pcall(UnitManager.CanStartOperation, unit, op, nil, params)
  return ok and can == true
end

function Civ6Ai_Apply._AttackPlan(unit, x, y)
  if unit == nil or x == nil or y == nil or UnitOperationTypes == nil then
    return nil, nil
  end
  local moveMods = UnitOperationMoveModifiers
  local function tryOp(op, modifiers)
    if op == nil then
      return nil, nil
    end
    local params = Civ6Ai_Apply._AttackParams(x, y, modifiers)
    if Civ6Ai_Apply._CanStartParams(unit, op, params) then
      return op, params
    end
    return nil, nil
  end
  local domain = nil
  if GameInfo ~= nil and GameInfo.Units ~= nil and unit.GetType ~= nil then
    local okRow, row = pcall(function() return GameInfo.Units[unit:GetType()] end)
    if okRow and row ~= nil then
      domain = row.Domain
    end
  end
  local attackMods = nil
  if moveMods ~= nil then
    attackMods = (moveMods.ATTACK or 0) + (moveMods.MOVE_IGNORE_UNEXPLORED_DESTINATION or 0)
  end
  if domain == "DOMAIN_AIR" then
    return tryOp(UnitOperationTypes.AIR_ATTACK, moveMods ~= nil and moveMods.ATTACK or nil)
  end
  local op, params = tryOp(UnitOperationTypes.RANGE_ATTACK, moveMods ~= nil and moveMods.NONE or nil)
  if op ~= nil then
    return op, params
  end
  op, params = tryOp(UnitOperationTypes.COASTAL_RAID, attackMods)
  if op ~= nil then
    return op, params
  end
  -- Melee is MOVE_TO with the attack modifier. Offer it only when that same
  -- check passes, so a listed attack is one RequestOperation can start.
  return tryOp(UnitOperationTypes.MOVE_TO, attackMods)
end

function Civ6Ai_Apply._AttackTarget(playerID, args)
  local unitId = args.unit_id
  local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
  if unitId == nil or x == nil or y == nil then
    return false, "missing_unit_or_target", args
  end
  local unit = Civ6Ai_Apply._FindUnit(playerID, unitId)
  if unit == nil then
    return false, "unit_not_found", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    -- AI seats attack through the synced order channel, not this function.
    return false, "attack_requires_local_player", args
  end
  -- Single player: the local seat's offers are the same distance list the AI
  -- seats execute with Civ6Ai_Orders._ResolveAttack. The UI CanStart check
  -- rejected every one of those as operation_illegal. Use that resolver here
  -- so an offered attack is the attack that runs.
  if not Civ6Ai_Apply._IsNetworkMultiplayer() then
    local ok, reason = Civ6Ai_Apply._GovRoute("AttackUnit", playerID, unit:GetID(), x, y)
    local missing = reason ~= nil and string.find(tostring(reason), "is not loaded", 1, true) ~= nil
    if not missing then
      if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
        Civ6Ai_Util.Log("apply|attack|gameplay|player=" .. tostring(playerID)
          .. "|ok=" .. tostring(ok) .. "|" .. tostring(reason or ""))
      end
      return ok, reason or "", args
    end
  end
  if UI ~= nil and UI.SelectUnit ~= nil then
    pcall(UI.SelectUnit, unit)
  end
  local op, params = Civ6Ai_Apply._AttackPlan(unit, x, y)
  if op == nil or UnitManager == nil or UnitManager.RequestOperation == nil then
    return false, "operation_illegal", args
  end
  local requested, err = pcall(UnitManager.RequestOperation, unit, op, params)
  if not requested or err == false then
    return false, "operation_rejected", args
  end
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
    Civ6Ai_Util.Log("apply|attack|ui|player=" .. tostring(playerID) .. "|op=" .. tostring(op))
  end
  return true, "ui_attack_requested", args
end

function Civ6Ai_Apply._UnitFortify(playerID, args)
  local unitId = args.unit_id
  if unitId == nil then
    return false, "missing_unit_id", args
  end
  local unit = Civ6Ai_Apply._FindUnit(playerID, unitId)
  if unit == nil then
    return false, "unit_not_found", args
  end
  if Civ6Ai_Apply._UseGameCoreRoute(playerID) then
    local gcOk, gcReason = Civ6Ai_Apply._GameCore("FinishMovesForPlayer", playerID, unit:GetID())
    if gcOk then
      return true, "finish_moves_gamecore", args
    end
    return false, gcReason or "fortify_rejected", args
  end
  if UnitOperationTypes ~= nil and UnitOperationTypes.FORTIFY ~= nil
      and UnitManager ~= nil and UnitManager.RequestOperation ~= nil then
    if pcall(UnitManager.RequestOperation, unit, UnitOperationTypes.FORTIFY) then
      return true, "", args
    end
  end
  if UnitManager ~= nil and UnitManager.FinishMoves ~= nil then
    local okFin = pcall(function()
      UnitManager.FinishMoves(unit)
    end)
    if okFin then
      return true, "finish_moves_fallback", args
    end
  end
  return false, "fortify_unavailable", args
end

function Civ6Ai_Apply._QueueProduction(playerID, args)
  -- The local seat is the human. AI seats use set_build_priority. A stale
  -- queue_production command is refused and does not touch the city.
  return false, "production_requires_local_player", args
end

function Civ6Ai_Apply._ParsePlotId(plotId)
  local text = tostring(plotId or "")
  local x, y = string.match(text, "PLOT_(%d+)_(%d+)")
  if x == nil then
    return nil, nil
  end
  return tonumber(x), tonumber(y)
end

-- ---------------------------------------------------------------------------
-- Governance commands: government, policy cards, pantheon, religion, great
-- people, governors. The local seat uses the game's own screen requests
-- (UI.RequestPlayerOperation / PlayerCulture:Request*), checked a moment later
-- because the engine applies them on a later frame; other seats in a single
-- player game use the gameplay routes in Civ6Ai_Orders.Gov (and, for policy
-- cards and governors, which no gameplay script can set, the screen request
-- made as that seat). A network game sends them on the synced order channel
-- (Civ6Ai_OrderChannel) before reaching this code.
-- ---------------------------------------------------------------------------
Civ6Ai_Apply.DEFERRED = "__deferred__"
Civ6Ai_Apply.GOV_KINDS = {
  change_government = true, set_policies = true, found_pantheon = true, found_religion = true,
  recruit_great_person = true, patronize_great_person = true,
  appoint_governor = true, assign_governor = true, promote_governor = true,
}
Civ6Ai_Apply.VERIFY_TICKS = 90
Civ6Ai_Apply.SYNCED_KINDS = {
  change_government = true, found_pantheon = true, found_religion = true, recruit_great_person = true,
  patronize_great_person = true, send_diplomatic_action = true, propose_peace = true, send_envoy = true, purchase_item = true,
  purchase_tile = true, pillage_improvement = true, worker_improve = true, build_fort = true,
  -- The local seat's UI research request returns nothing (not true), so every
  -- P0 research order was logged research_rejected. Use the synced channel.
  set_research_tech = true, set_research_civic = true,
}

local function gcall(obj, name, ...)
  if obj == nil or obj[name] == nil then
    return nil
  end
  local ok, v, w = pcall(obj[name], obj, ...)
  if ok then
    return v, w
  end
  return nil
end

function Civ6Ai_Apply._GovRoute(name, ...)
  local gov = ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil and ExposedMembers.Civ6Ai.Gov or nil
  local fn = gov ~= nil and gov[name] or nil
  if fn == nil then
    return false, "the gameplay route " .. tostring(name) .. " is not loaded (reload the game)"
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local okCall, ok, reason = pcall(function() return fn(unpackFn(args)) end)
  if not okCall then
    return false, "gameplay error: " .. tostring(ok)
  end
  return ok == true, reason or ""
end

-- Record the result once check() passes, or a failure after VERIFY_TICKS.
-- retry(), when given, is sent once halfway (e.g. the other id form).
function Civ6Ai_Apply._Defer(playerID, command, args, label, check, retry)
  local ticks, retried = 0, false
  Civ6Ai_Util.ScheduleTick(function()
    ticks = ticks + 1
    local okC, ok, reason = pcall(check)
    if okC and ok then
      Civ6Ai_Apply._RecordResult(playerID, command, true, reason or "", args)
      Civ6Ai_Util.Log("apply|gov_verified|player=" .. tostring(playerID) .. "|" .. label .. "|" .. tostring(reason))
      return false
    end
    if retry ~= nil and not retried and ticks >= Civ6Ai_Apply.VERIFY_TICKS / 2 then
      retried = true
      pcall(retry)
    end
    if ticks >= Civ6Ai_Apply.VERIFY_TICKS then
      local why = okC and tostring(reason or "no change seen") or ("check error: " .. tostring(ok))
      Civ6Ai_Apply._RecordResult(playerID, command, false, "the game did not apply it: " .. why, args)
      Civ6Ai_Util.Log("apply|gov_not_applied|player=" .. tostring(playerID) .. "|" .. label .. "|" .. why)
      return false
    end
    return true
  end)
  return false, Civ6Ai_Apply.DEFERRED, args
end

-- Run a screen request as playerID (swapping the local player in single
-- player when it is another seat).
function Civ6Ai_Apply._AsSeat(playerID, fn)
  if Game.GetLocalPlayer() == playerID then
    local ok, a, b = pcall(fn)
    if not ok then
      return false, tostring(a)
    end
    return a ~= false, b
  end
  return Civ6Ai_Apply._WithLocalPlayer(playerID, fn)
end

function Civ6Ai_Apply._PlayerOp(playerID, opName, params)
  if PlayerOperations == nil or PlayerOperations[opName] == nil then
    return false, "this screen request is not available (" .. tostring(opName) .. ")"
  end
  local ok, err = pcall(UI.RequestPlayerOperation, playerID, PlayerOperations[opName], params)
  if not ok then
    return false, tostring(err)
  end
  return true, ""
end

local function isLocal(playerID)
  return Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() == playerID
end

-- --- Government ---------------------------------------------------------
function Civ6Ai_Apply._ChangeGovernment(playerID, command, args)
  local row = args.government_id ~= nil and GameInfo.Governments[args.government_id] or nil
  if row == nil then
    return false, "unknown government " .. tostring(args.government_id), args
  end
  if not isLocal(playerID) then
    local ok, reason = Civ6Ai_Apply._GovRoute("ChangeGovernment", playerID, row.Index)
    return ok, reason, args
  end
  local culture = Players[playerID]:GetCulture()
  local current = gcall(culture, "GetCurrentGovernment")
  if gcall(culture, "IsInAnarchy") == true or (type(current) == "number" and current < 0) then
    return false, "you are in anarchy; wait until it ends before changing government", args
  end
  if current == row.Index then
    return false, "you already have " .. row.GovernmentType, args
  end
  if gcall(culture, "IsGovernmentUnlocked", row.Hash) ~= true and gcall(culture, "IsGovernmentUnlocked", row.Index) ~= true then
    return false, row.GovernmentType .. " is not unlocked yet (research the civic that unlocks it first)", args
  end
  if gcall(culture, "GovernmentChangeMade") == true then
    return false, "government was already changed this turn", args
  end
  if gcall(culture, "CivicCompletedThisTurn") ~= true then
    return false, "a government can only be changed on a turn when a civic completed", args
  end
  local okR = gcall(culture, "RequestChangeGovernment", row.Hash)
  if okR == false then
    return false, "the game refused the government change", args
  end
  return Civ6Ai_Apply._Defer(playerID, command, args, "government=" .. row.GovernmentType, function()
    local now = gcall(culture, "GetCurrentGovernment")
    if gcall(culture, "IsInAnarchy") == true then
      if now == row.Index then
        return true, "government=" .. row.GovernmentType .. " (anarchy started)"
      end
      return false, "you are in anarchy; wait until it ends before changing government"
    end
    if now == row.Index then
      return true, "government=" .. row.GovernmentType
    end
    return false, "government is still " .. tostring(now and GameInfo.Governments[now] and GameInfo.Governments[now].GovernmentType)
  end)
end

-- --- Policy cards -------------------------------------------------------
-- args.slots = "0=POLICY_A;1=POLICY_B;2=NONE" (slot index = policy or NONE).
function Civ6Ai_Apply._ParsePolicySlots(text)
  local out = {}
  for part in string.gmatch(tostring(text or ""), "[^;,]+") do
    local slot, policy = string.match(part, "^%s*(%d+)%s*[=:]%s*([%w_]+)%s*$")
    if slot == nil then
      return nil, "could not read policy slot entry '" .. part .. "'"
    end
    out[#out + 1] = { slot = tonumber(slot), policy = policy }
  end
  if #out == 0 then
    return nil, "no policy slots given"
  end
  return out
end

local function slotFits(slotType, policyRow)
  local cardType = policyRow.GovernmentSlotType
  if slotType == cardType or slotType == "SLOT_WILDCARD" then
    return true
  end
  return false
end

-- GovernmentScreen confirms with GameInfo.Types[PolicyType].Hash.
-- RequestPolicyChanges ignores a different hash and the slot stays empty
-- ("slot N still holds nothing").
function Civ6Ai_Apply._PolicyTypeHash(prow)
  if prow == nil then
    return nil
  end
  local typeName = prow.PolicyType
  local types = GameInfo ~= nil and GameInfo.Types or nil
  local typeRow = types ~= nil and typeName ~= nil and types[typeName] or nil
  if typeRow ~= nil and typeRow.Hash ~= nil then
    return typeRow.Hash
  end
  return prow.Hash
end

function Civ6Ai_Apply._SetPolicies(playerID, command, args)
  local plan, why = Civ6Ai_Apply._ParsePolicySlots(args.slots)
  if plan == nil then
    return false, why, args
  end
  local culture = Players[playerID]:GetCulture()
  local n = gcall(culture, "GetNumPolicySlots") or 0
  if gcall(culture, "PolicyChangeMade") == true then
    return false, "policy cards were already changed this turn", args
  end
  if gcall(culture, "CivicCompletedThisTurn") ~= true and (gcall(culture, "GetNumPolicySlotsOpen") or 0) <= 0 then
    return false, "policy cards can only be changed on a turn when a civic completed", args
  end
  -- Start from the cards already slotted, then overlay the plan. NONE leaves
  -- a slot alone (models wrote all-NONE and emptied every card). A card named
  -- for a new slot is lifted out of its old one: the engine denies the add
  -- while that card is still active, and the destination stays empty.
  local desired = {}
  for i = 0, n - 1 do
    local cur = gcall(culture, "GetSlotPolicy", i)
    local crow = cur ~= nil and cur >= 0 and GameInfo.Policies[cur] or nil
    if crow ~= nil then
      desired[i] = crow
    end
  end
  local want, used = {}, {}
  for _, e in ipairs(plan) do
    if e.slot < 0 or e.slot >= n then
      return false, "there is no policy slot " .. e.slot .. " (you have " .. n .. ")", args
    end
    local st = gcall(culture, "GetSlotType", e.slot)
    local srow = st ~= nil and GameInfo.GovernmentSlots[st] or nil
    local slotType = srow ~= nil and srow.GovernmentSlotType or "?"
    if string.upper(e.policy) ~= "NONE" then
      local prow = GameInfo.Policies[e.policy] or GameInfo.Policies["POLICY_" .. e.policy]
      if prow == nil then
        return false, "unknown policy card " .. e.policy, args
      end
      local typeHash = Civ6Ai_Apply._PolicyTypeHash(prow)
      if gcall(culture, "IsPolicyUnlocked", typeHash) ~= true
          and gcall(culture, "IsPolicyUnlocked", prow.Hash) ~= true
          and gcall(culture, "IsPolicyUnlocked", prow.Index) ~= true then
        return false, e.policy .. " is not unlocked yet", args
      end
      if not slotFits(slotType, prow) then
        return false, e.policy .. " is a " .. tostring(prow.GovernmentSlotType) .. " card and slot " .. e.slot
          .. " is " .. slotType, args
      end
      if used[prow.PolicyType] then
        return false, e.policy .. " can only be slotted once", args
      end
      used[prow.PolicyType] = true
      for i = 0, n - 1 do
        if i ~= e.slot and desired[i] ~= nil and desired[i].PolicyType == prow.PolicyType then
          desired[i] = nil
        end
      end
      desired[e.slot] = prow
      want[e.slot] = prow.Index
    end
  end
  if next(want) == nil then
    return false, "no policy card named (NONE leaves a slot unchanged)", args
  end
  if Game ~= nil and Game.IsAllowStrategicCommands ~= nil and Game.IsAllowStrategicCommands(playerID) == false then
    return false, "policy cards cannot be changed until this seat's turn is active", args
  end
  local changed = false
  for i = 0, n - 1 do
    local cur = gcall(culture, "GetSlotPolicy", i)
    local crow = cur ~= nil and cur >= 0 and GameInfo.Policies[cur] or nil
    local nextRow = desired[i]
    local same = (crow == nil and nextRow == nil)
      or (crow ~= nil and nextRow ~= nil and crow.PolicyType == nextRow.PolicyType)
    if not same then
      changed = true
    end
  end
  if not changed then
    local parts = {}
    for slot, idx in pairs(want) do
      parts[#parts + 1] = slot .. "=" .. (GameInfo.Policies[idx] and GameInfo.Policies[idx].PolicyType or "?")
    end
    table.sort(parts)
    return true, "policies=" .. table.concat(parts, ";") .. ":already", args
  end
  -- GovernmentScreen leaves Confirm disabled while any slot is empty, and
  -- RequestPolicyChanges then does nothing: the slot we named stays empty
  -- ("slot N still holds nothing") on every later turn.
  local empty = {}
  for i = 0, n - 1 do
    if desired[i] == nil then
      empty[#empty + 1] = tostring(i)
    end
    local typeHash = desired[i] ~= nil and Civ6Ai_Apply._PolicyTypeHash(desired[i]) or nil
    if desired[i] ~= nil and typeHash == nil then
      return false, desired[i].PolicyType .. " has no type hash", args
    end
  end
  if #empty > 0 then
    return false, "the game will not apply a policy change while slot " .. table.concat(empty, ", ")
      .. " still holds nothing (every slot has to hold a card)", args
  end
  -- Confirm is hidden until GetCostToUnlockPolicies() is 0. On a turn a civic
  -- did not complete, that cost stays above 0 and RequestPolicyChanges is
  -- ignored, so the empty slot never fills. Unlock (the government screen's
  -- gold/faith button) first, then send every slot the way OnConfirmPolicies does.
  local cost = Civ6Ai_Apply._PolicyUnlockCost(culture)
  local justUnlocked = false
  if cost > 0 then
    local currency, balance = Civ6Ai_Apply._PolicyUnlockCurrency(playerID)
    if balance < cost then
      return false, "changing policy cards costs " .. tostring(cost) .. " " .. currency
        .. " and this seat has " .. tostring(balance), args
    end
    local okU, whyU = Civ6Ai_Apply._AsSeat(playerID, function()
      return Civ6Ai_Apply._PlayerOp(playerID, "UNLOCK_POLICIES", {})
    end)
    if okU == false then
      return false, "the game refused to unlock policy changes"
        .. ((whyU ~= nil and whyU ~= "") and (": " .. tostring(whyU)) or ""), args
    end
    -- The unlock is a separate operation. Confirm on a later frame, once the
    -- cost has dropped, the way the government screen does.
    justUnlocked = true
  end
  local submitted, fatal = false, nil
  local function submitOnce()
    if fatal ~= nil then
      return false, fatal
    end
    if submitted then
      return true, ""
    end
    if justUnlocked then
      justUnlocked = false
      return false, "waiting for the policy change to unlock"
    end
    if Civ6Ai_Apply._PolicyUnlockCost(culture) > 0 then
      return false, "policy changes stay locked (the unlock did not apply)"
    end
    local okReq, why = Civ6Ai_Apply._SubmitPolicyChanges(playerID, culture, n, desired)
    if okReq == false then
      fatal = "the game refused the policy change"
        .. ((why ~= nil and why ~= "") and (": " .. tostring(why)) or "")
      return false, fatal
    end
    submitted = true
    return true, ""
  end
  local okNow, whyNow = submitOnce()
  if fatal ~= nil then
    return false, whyNow, args
  end
  local label = tostring(args.slots)
  return Civ6Ai_Apply._Defer(playerID, command, args, "policies=" .. label, function()
    if not submitted then
      local okReq, why = submitOnce()
      if not okReq then
        return false, why or "policy changes stay locked (the unlock did not apply)"
      end
    end
    local parts, missing = {}, {}
    for slot, idx in pairs(want) do
      local now = gcall(culture, "GetSlotPolicy", slot)
      local row = now ~= nil and now >= 0 and GameInfo.Policies[now] or nil
      local wantRow = idx ~= nil and GameInfo.Policies[idx] or nil
      if row ~= nil and wantRow ~= nil and row.PolicyType == wantRow.PolicyType then
        parts[#parts + 1] = slot .. "=" .. row.PolicyType
      else
        missing[#missing + 1] = "slot " .. slot .. " still holds "
          .. tostring(row ~= nil and row.PolicyType or "nothing")
      end
    end
    if #missing == 0 then
      table.sort(parts)
      return true, "policies=" .. table.concat(parts, ";")
    end
    local seatNote = isLocal(playerID) and "" or " (policy cards for a seat that is not the local player can only be "
      .. "set through the game's screen, which ignored the request; the game's own AI keeps choosing this seat's cards)"
    return false, table.concat(missing, ", ") .. seatNote
  end, function()
    if Civ6Ai_Apply._PolicyUnlockCost(culture) > 0 then
      Civ6Ai_Apply._AsSeat(playerID, function()
        return Civ6Ai_Apply._PlayerOp(playerID, "UNLOCK_POLICIES", {})
      end)
    end
  end)
end

function Civ6Ai_Apply._PolicyUnlockCost(culture)
  local cost = gcall(culture, "GetCostToUnlockPolicies")
  if type(cost) ~= "number" or cost < 0 then
    return 0
  end
  return cost
end

-- Gold, unless GOVERNMENT_UNLOCK_WITH_FAITH is set (GovernmentScreen).
function Civ6Ai_Apply._PolicyUnlockCurrency(playerID)
  local gp = GameInfo ~= nil and GameInfo.GlobalParameters ~= nil
    and GameInfo.GlobalParameters["GOVERNMENT_UNLOCK_WITH_FAITH"] or nil
  local value = gp ~= nil and gp.Value or 0
  local faith = value == true or (tonumber(value) ~= nil and tonumber(value) ~= 0)
  if faith then
    local rel = gcall(Players[playerID], "GetReligion")
    return "faith", tonumber(gcall(rel, "GetFaithBalance")) or 0
  end
  local treasury = gcall(Players[playerID], "GetTreasury")
  return "gold", tonumber(gcall(treasury, "GetGoldBalance")) or 0
end

-- OnConfirmPolicies: clear every slot, then slot index -> Types[PolicyType].Hash
-- for each card that should be there. Removals are applied first, so a card
-- moving between slots is not still "active" when it is added.
function Civ6Ai_Apply._SubmitPolicyChanges(playerID, culture, n, desired)
  local clearList, addList = {}, {}
  for i = 0, n - 1 do
    table.insert(clearList, i)
    local row = desired[i]
    if row ~= nil then
      addList[i] = Civ6Ai_Apply._PolicyTypeHash(row)
    end
  end
  return Civ6Ai_Apply._AsSeat(playerID, function()
    return culture:RequestPolicyChanges(clearList, addList)
  end)
end

-- --- Religion -----------------------------------------------------------
function Civ6Ai_Apply._FoundPantheon(playerID, command, args)
  local row = args.belief_id ~= nil and GameInfo.Beliefs[args.belief_id] or nil
  if row == nil then
    return false, "unknown belief " .. tostring(args.belief_id), args
  end
  if not isLocal(playerID) then
    local ok, reason = Civ6Ai_Apply._GovRoute("FoundPantheon", playerID, row.Index)
    return ok, reason, args
  end
  local rel = Players[playerID]:GetReligion()
  local have = gcall(rel, "GetPantheon")
  if have ~= nil and have >= 0 then
    return false, "you already have a pantheon", args
  end
  if row.BeliefClassType ~= "BELIEF_CLASS_PANTHEON" then
    return false, row.BeliefType .. " is not a pantheon belief", args
  end
  if gcall(rel, "CanCreatePantheon") == false then
    return false, "not enough faith for a pantheon yet", args
  end
  local params = {}
  params[PlayerOperations.PARAM_BELIEF_TYPE] = row.Hash
  params[PlayerOperations.PARAM_INSERT_MODE] = PlayerOperations.VALUE_EXCLUSIVE
  local okOp, opWhy = Civ6Ai_Apply._PlayerOp(playerID, "FOUND_PANTHEON", params)
  if not okOp then
    return false, opWhy, args
  end
  return Civ6Ai_Apply._Defer(playerID, command, args, "pantheon=" .. row.BeliefType, function()
    local now = gcall(rel, "GetPantheon")
    if now == row.Index then
      return true, "pantheon=" .. row.BeliefType .. ":faith_left=" .. tostring(math.floor(gcall(rel, "GetFaithBalance") or 0))
    end
    return false, "no pantheon yet"
  end)
end

function Civ6Ai_Apply._FoundReligion(playerID, command, args)
  local row = args.religion_id ~= nil and GameInfo.Religions[args.religion_id] or nil
  if row == nil then
    return false, "unknown religion " .. tostring(args.religion_id), args
  end
  local unitNum = Civ6Ai_Apply._ParseUnitNumericId(args.unit_id)
  local beliefs = {}
  for b in string.gmatch(tostring(args.belief_ids or ""), "[%w_]+") do
    local brow = GameInfo.Beliefs[b]
    if brow == nil then
      return false, "unknown belief " .. b, args
    end
    beliefs[#beliefs + 1] = brow.Index
  end
  local ok, reason = Civ6Ai_Apply._GovRoute(
    "FoundReligion", playerID, row.Index, unitNum or -1,
    beliefs[1] or -1, beliefs[2] or -1, beliefs[3] or -1, beliefs[4] or -1)
  return ok, reason, args
end

-- --- Great people -------------------------------------------------------
local function unclaimed(individual)
  local gp = Game.GetGreatPeople()
  local okT, list = pcall(function() return gp:GetTimeline() end)
  if okT and type(list) == "table" then
    for _, e in ipairs(list) do
      if e.Individual == individual then
        return e
      end
    end
  end
  return nil
end

function Civ6Ai_Apply._GreatPerson(playerID, command, args, patronize)
  local row = args.individual_id ~= nil and GameInfo.GreatPersonIndividuals[args.individual_id] or nil
  if row == nil then
    return false, "unknown great person " .. tostring(args.individual_id), args
  end
  local useFaith = string.lower(tostring(args.yield or "gold")) == "faith"
  if not isLocal(playerID) then
    local ok, reason
    if patronize then
      ok, reason = Civ6Ai_Apply._GovRoute("PatronizeGreatPerson", playerID, row.Index, useFaith)
    else
      ok, reason = Civ6Ai_Apply._GovRoute("RecruitGreatPerson", playerID, row.Index)
    end
    return ok, reason, args
  end
  local gp = Game.GetGreatPeople()
  local entry = unclaimed(row.Index)
  if entry == nil or entry.Claimant ~= nil then
    return false, row.GreatPersonIndividualType .. " is not available right now", args
  end
  local params = {}
  params[PlayerOperations.PARAM_GREAT_PERSON_INDIVIDUAL_TYPE] = row.Index
  local op = "RECRUIT_GREAT_PERSON"
  if patronize then
    local y = GameInfo.Yields[useFaith and "YIELD_FAITH" or "YIELD_GOLD"].Index
    if gcall(gp, "CanPatronizePerson", playerID, row.Index, y) ~= true then
      return false, "cannot patronize " .. row.GreatPersonIndividualType .. " with " .. (useFaith and "faith" or "gold")
        .. " (costs " .. tostring(gcall(gp, "GetPatronizeCost", playerID, row.Index, y)) .. ")", args
    end
    params[PlayerOperations.PARAM_YIELD_TYPE] = y
    op = "PATRONIZE_GREAT_PERSON"
  elseif gcall(gp, "CanRecruitPerson", playerID, row.Index) ~= true then
    return false, "not enough great person points to recruit " .. row.GreatPersonIndividualType
      .. " (needs " .. tostring(entry.Cost) .. ")", args
  end
  local okOp, opWhy = Civ6Ai_Apply._PlayerOp(playerID, op, params)
  if not okOp then
    return false, opWhy, args
  end
  return Civ6Ai_Apply._Defer(playerID, command, args, string.lower(op) .. "=" .. row.GreatPersonIndividualType, function()
    local e = unclaimed(row.Index)
    if e == nil or e.Claimant == playerID then
      return true, (patronize and "patronized=" or "recruited=") .. row.GreatPersonIndividualType
    end
    return false, "still unclaimed"
  end)
end

-- --- Governors ----------------------------------------------------------
local function governorObj(playerID, grow)
  local govs = Players[playerID]:GetGovernors()
  return govs, gcall(govs, "GetGovernor", grow.Hash)
end

function Civ6Ai_Apply._Governor(playerID, command, args)
  if GameInfo.Governors == nil then
    return false, "this game has no governors (Rise and Fall rules are off)", args
  end
  local grow = args.governor_id ~= nil and GameInfo.Governors[args.governor_id] or nil
  if grow == nil then
    return false, "unknown governor " .. tostring(args.governor_id), args
  end
  local govs, g = governorObj(playerID, grow)
  if govs == nil then
    return false, "no governor data for this player", args
  end
  local kind = command.kind
  local params = {}
  local check, label, retryParams
  if kind == "appoint_governor" then
    if g ~= nil then
      return false, grow.GovernorType .. " is already appointed", args
    end
    if gcall(govs, "CanAppoint") ~= true then
      return false, "no governor title available to appoint a new governor", args
    end
    params[PlayerOperations.PARAM_GOVERNOR_TYPE] = grow.Index
    label = "appoint=" .. grow.GovernorType
    check = function()
      local _, now = governorObj(playerID, grow)
      return now ~= nil, now ~= nil and ("appointed=" .. grow.GovernorType) or "not appointed"
    end
  elseif kind == "assign_governor" then
    if g == nil then
      return false, grow.GovernorType .. " is not appointed yet (appoint first)", args
    end
    if (gcall(g, "GetNeutralizedTurns") or 0) > 0 then
      return false, grow.GovernorType .. " is neutralized for now", args
    end
    local cityNum = tonumber(string.match(tostring(args.city_id or ""), "(%d+)$"))
    local city = cityNum ~= nil and CityManager ~= nil and CityManager.GetCity(playerID, cityNum) or nil
    if city == nil then
      local cities = Players[playerID]:GetCities()
      city = cityNum ~= nil and cities ~= nil and gcall(cities, "FindID", cityNum) or nil
    end
    if city == nil then
      return false, "you have no city " .. tostring(args.city_id), args
    end
    if gcall(govs, "CanAssignGovernor", grow.Hash, city) == false then
      return false, "the game does not allow " .. grow.GovernorType .. " in " .. Locale.Lookup(city:GetName()) .. " now", args
    end
    params[PlayerOperations.PARAM_GOVERNOR_TYPE] = grow.Index
    params[PlayerOperations.PARAM_PLAYER_ONE] = playerID
    params[PlayerOperations.PARAM_CITY_DEST] = cityNum
    label = "assign=" .. grow.GovernorType .. "@" .. tostring(cityNum)
    check = function()
      local _, now = governorObj(playerID, grow)
      local c = now ~= nil and gcall(now, "GetAssignedCity") or nil
      if c ~= nil and c:GetID() == cityNum then
        return true, "assigned=" .. grow.GovernorType .. ":city=" .. Locale.Lookup(c:GetName())
      end
      return false, "not assigned there"
    end
  else
    if g == nil then
      return false, grow.GovernorType .. " is not appointed yet (appoint first)", args
    end
    local prow = args.promotion_id ~= nil and GameInfo.GovernorPromotions ~= nil
      and GameInfo.GovernorPromotions[args.promotion_id] or nil
    if prow == nil then
      return false, "unknown governor promotion " .. tostring(args.promotion_id), args
    end
    if gcall(g, "HasPromotion", prow.Hash) == true then
      return false, grow.GovernorType .. " already has " .. prow.GovernorPromotionType, args
    end
    if gcall(govs, "CanPromoteGovernor", grow.Hash) == false then
      return false, "no governor title available to promote " .. grow.GovernorType, args
    end
    params[PlayerOperations.PARAM_GOVERNOR_TYPE] = grow.Index
    params[PlayerOperations.PARAM_GOVERNOR_PROMOTION_TYPE] = prow.Index
    retryParams = {}
    retryParams[PlayerOperations.PARAM_GOVERNOR_TYPE] = grow.Hash
    retryParams[PlayerOperations.PARAM_GOVERNOR_PROMOTION_TYPE] = prow.Hash
    label = "promote=" .. grow.GovernorType .. ":" .. prow.GovernorPromotionType
    check = function()
      local _, now = governorObj(playerID, grow)
      if now ~= nil and gcall(now, "HasPromotion", prow.Hash) == true then
        return true, "promoted=" .. grow.GovernorType .. ":" .. prow.GovernorPromotionType
      end
      return false, "promotion not applied"
    end
  end
  if retryParams == nil then
    retryParams = {}
    for k, v in pairs(params) do
      retryParams[k] = v
    end
    retryParams[PlayerOperations.PARAM_GOVERNOR_TYPE] = grow.Hash
  end
  local opName = kind == "appoint_governor" and "APPOINT_GOVERNOR" or (kind == "assign_governor" and "ASSIGN_GOVERNOR" or "PROMOTE_GOVERNOR")
  local okOp, opWhy = Civ6Ai_Apply._AsSeat(playerID, function()
    return Civ6Ai_Apply._PlayerOp(playerID, opName, params)
  end)
  if not okOp then
    return false, tostring(opWhy), args
  end
  local wrapped = function()
    local ok, reason = check()
    if not ok and not isLocal(playerID) then
      reason = tostring(reason) .. " (governors for a seat that is not the local player can only be set through the "
        .. "game's screen, which ignored the request; the game's own AI manages this seat's governors)"
    end
    return ok, reason
  end
  return Civ6Ai_Apply._Defer(playerID, command, args, label, wrapped, function()
    Civ6Ai_Apply._AsSeat(playerID, function() return Civ6Ai_Apply._PlayerOp(playerID, opName, retryParams) end)
  end)
end

function Civ6Ai_Apply._PlayerNum(id)
  local n = tonumber(string.match(tostring(id or ""), "(%d+)$"))
  return n
end

function Civ6Ai_Apply._CityNum(id)
  local n = tonumber(string.match(tostring(id or ""), "CITY_(%d+)"))
  if n ~= nil then
    -- Full city id for gameplay Gov.Purchase* (cityById uses c:GetID()).
    -- UI CityManager.GetCity still takes the low 16 bits; see Production.lua.
    return n
  end
  return tonumber(id)
end

-- War, peace, gold/faith purchase, tile purchase: the gameplay Gov functions
-- (DeclareWarOn / MakePeaceWith / InitUnit / SetOwner). Local seat in single
-- player calls them through ExposedMembers; queued seats go through the order
-- channel before this file.
function Civ6Ai_Apply._Deal(playerID, command, args)
  local kind = command.kind
  if kind == "send_diplomatic_action" then
    local other = Civ6Ai_Apply._PlayerNum(args.target_player_id)
    if other == nil then
      return false, "missing_target_player", args
    end
    local action = string.upper(tostring(args.action_id or ""))
    if string.find(action, "WAR", 1, true) == nil then
      return false, "only DECLARE_WAR can be applied", args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("DeclareWar", playerID, other, string.find(action, "SURPRISE", 1, true) ~= nil)
    return ok, reason, args
  end
  if kind == "send_envoy" then
    local other = Civ6Ai_Apply._PlayerNum(args.target_player_id or args.city_state_id)
    if other == nil then
      return false, "missing_target_player", args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("SendEnvoy", playerID, other)
    return ok, reason, args
  end
  if kind == "execute_deal" then
    local f, why = Civ6Ai_OrderChannel._Fields(playerID, command)
    if f == nil then
      return false, why, args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("Deal", playerID, f.I, f.W, f.X, f.Y, f.I2, f.I3, f.A)
    return ok, reason, args
  end
  if kind == "purchase_item" then
    local cityNum = Civ6Ai_Apply._CityNum(args.city_id)
    local item = args.item_id
    local unitRow = item ~= nil and GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[item] or nil
    local bldRow = item ~= nil and GameInfo ~= nil and GameInfo.Buildings ~= nil and GameInfo.Buildings[item] or nil
    if cityNum == nil or (unitRow == nil and bldRow == nil) then
      return false, "missing_city_or_item", args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute(
      "PurchaseItem", playerID, cityNum, (unitRow or bldRow).Index, bldRow ~= nil,
      string.lower(tostring(args.yield or "gold")) == "faith")
    return ok, reason, args
  end
  if kind == "purchase_tile" then
    local cityNum = Civ6Ai_Apply._CityNum(args.city_id)
    local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
    if cityNum == nil or x == nil or y == nil then
      return false, "missing_city_or_tile", args
    end
    local ok, reason = Civ6Ai_Apply._GovRoute("PurchaseTile", playerID, cityNum, x, y)
    return ok, reason, args
  end
  return false, "unsupported_kind", args
end

function Civ6Ai_Apply._Work(playerID, command, args)
  local unitNum = Civ6Ai_Apply._ParseUnitNumericId(args.unit_id)
  local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
  if unitNum == nil then
    return false, "missing_unit_id", args
  end
  -- Local seat: the game's own auto-explore (a synced unit operation that keeps going).
  -- UnitOperationTypes has no AUTOMATE_EXPLORE entry in the UI context; the UnitPanel
  -- passes the UnitOperations row Hash, so do the same.
  local auto = UnitOperationTypes ~= nil and UnitOperationTypes.AUTOMATE_EXPLORE or nil
  if auto == nil and GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
    local row = GameInfo.UnitOperations["UNITOPERATION_AUTOMATE_EXPLORE"]
    auto = row ~= nil and row.Hash or nil
  end
  if command.kind == "explore" and auto ~= nil and playerID == Game.GetLocalPlayer() then
    local unit = UnitManager.GetUnit(playerID, unitNum)
    local can = false
    if unit ~= nil then
      local okc, res = pcall(UnitManager.CanStartOperation, unit, auto, nil, true)
      can = okc and res == true
    end
    if can then
      UnitManager.RequestOperation(unit, auto)
      return true, "auto_explore", args
    end
    Civ6Ai_Util.Log("apply|auto_explore_unavailable|player=" .. tostring(playerID) .. "|unit=" .. tostring(unitNum))
  end
  local ok, reason = Civ6Ai_Apply._GovRoute(command.kind == "explore" and "Explore" or "PillageImprovement", playerID, unitNum, x, y)
  return ok, reason, args
end

function Civ6Ai_Apply._Governance(playerID, command, args)
  local kind = command.kind
  if kind == "change_government" then
    return Civ6Ai_Apply._ChangeGovernment(playerID, command, args)
  elseif kind == "set_policies" then
    return Civ6Ai_Apply._SetPolicies(playerID, command, args)
  elseif kind == "found_pantheon" then
    return Civ6Ai_Apply._FoundPantheon(playerID, command, args)
  elseif kind == "found_religion" then
    return Civ6Ai_Apply._FoundReligion(playerID, command, args)
  elseif kind == "recruit_great_person" then
    return Civ6Ai_Apply._GreatPerson(playerID, command, args, false)
  elseif kind == "patronize_great_person" then
    return Civ6Ai_Apply._GreatPerson(playerID, command, args, true)
  end
  return Civ6Ai_Apply._Governor(playerID, command, args)
end
