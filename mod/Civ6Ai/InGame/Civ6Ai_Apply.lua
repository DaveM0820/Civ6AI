-- Civ6Ai apply: execute validated decision commands and emit apply-results.jsonl.
Civ6Ai_Apply = Civ6Ai_Apply or {}

function Civ6Ai_Apply._IsNetworkMultiplayer()
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    return GameConfiguration.IsNetworkMultiplayer()
  end
  return false
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

function Civ6Ai_Apply.ApplyDecision(playerID, decision)
  if decision == nil or decision.commands == nil then
    Civ6Ai_Util.Log("apply|no_commands|player=" .. tostring(playerID))
    return
  end
  Civ6Ai_Apply._orderedUnits = Civ6Ai_Apply._orderedUnits or {}
  Civ6Ai_Apply._orderedUnits[playerID] = {}
  local commands = decision.commands
  local maxPasses = 4
  local pending = {}
  for _, command in ipairs(commands) do
    table.insert(pending, command)
  end
  for passIndex = 1, maxPasses do
    if #pending == 0 then
      break
    end
    local nextPending = {}
    local progress = false
    for _, command in ipairs(pending) do
      local ok, reason, fixedArgs = Civ6Ai_Apply._ApplyCommand(playerID, command)
      Civ6Ai_Apply._RecordResult(playerID, command, ok, reason, fixedArgs)
      if ok then
        progress = true
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
          Civ6Ai_Util.Log("apply|fail|" .. tostring(command.kind) .. "|" .. tostring(reason))
        end
      end
    end
    if not progress then
      for _, command in ipairs(nextPending) do
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
end

function Civ6Ai_Apply._IsPlotOccupiedRetryable(kind, reason)
  if kind ~= "move_unit" and kind ~= "attack_target" then
    return false
  end
  local text = tostring(reason or "")
  return text == "plot_occupied"
    or text == "operation_illegal"
    or text == "operation_rejected"
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
  if UnitManager ~= nil and UnitManager.FinishMoves ~= nil then
    UnitManager.FinishMoves(unit)
    return true
  end
  return false
end

function Civ6Ai_Apply._WithLocalPlayer(playerID, fn)
  if Civ6Ai_Apply._IsNetworkMultiplayer() then
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
  if ExposedMembers == nil or ExposedMembers.Civ6Ai == nil or ExposedMembers.Civ6Ai.MoveUnitForPlayer == nil then
    return false, "gamecore_unavailable"
  end
  local ok, reason = ExposedMembers.Civ6Ai.MoveUnitForPlayer(playerID, unitNumericId, x, y)
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
    )
    return true, ""
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
  if not Civ6Ai_Apply._IsNetworkMultiplayer()
      and (Game.GetLocalPlayer() == playerID
        or (PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil)) then
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
  return false, "unsupported_kind", args
end

function Civ6Ai_Apply._RequestPlayerOperation(playerID, opType, params)
  if UI == nil or UI.RequestPlayerOperation == nil then
    return false, "ui_unavailable"
  end
  if UI.RequestPlayerOperation(playerID, opType, params or {}) then
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
  local params = {}
  if PlayerOperationTypes ~= nil then
    params[PlayerOperationTypes.PARAM_TECH_TYPE] = hash.Index
    local ok, reason = Civ6Ai_Apply._RequestPlayerOperation(playerID, PlayerOperationTypes.RESEARCH, params)
    if ok then
      return true, "", args
    end
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil and ExposedMembers.Civ6Ai.SetResearchForPlayer ~= nil then
    if ExposedMembers.Civ6Ai.SetResearchForPlayer(playerID, hash.Index) then
      Civ6Ai_Util.Log("apply|research|gamecore|player=" .. tostring(playerID) .. "|tech=" .. tostring(techId))
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
  local params = {}
  if PlayerOperationTypes ~= nil then
    params[PlayerOperationTypes.PARAM_CIVIC_TYPE] = hash.Index
    local ok, reason = Civ6Ai_Apply._RequestPlayerOperation(playerID, PlayerOperationTypes.PROGRESS_CIVIC, params)
    if ok then
      return true, "", args
    end
    return false, reason or "civic_rejected", args
  end
  return false, "player_ops_unavailable", args
end

function Civ6Ai_Apply._ResolveTargetCoords(args)
  local x = args.target_x
  local y = args.target_y
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
    if UnitManager.CanStartOperation(unit, op, nil, params, false) then
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
  if UnitManager.RequestOperation ~= nil then
    if plot ~= nil and UnitManager.RequestOperation(unit, op, plot) then
      if probeLabel ~= nil then
        Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|ok")
      end
      return true, ""
    end
    if UnitManager.RequestOperation(unit, op, params) then
      if probeLabel ~= nil then
        Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|ok")
      end
      return true, ""
    end
    if UnitManager.RequestOperation(unit, op) then
      if probeLabel ~= nil then
        Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|ok")
      end
      return true, ""
    end
  end
  if probeLabel ~= nil then
    Civ6Ai_Util.Log("apply|probe|" .. probeLabel .. "|fail|rejected")
  end
  return false, "operation_rejected"
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
  -- M2 MP path: all-client GameCore move via chat broadcast (flagged). SP ladder unchanged.
  if Civ6Ai_MpSync ~= nil and Civ6Ai_MpSync.IsActive ~= nil and Civ6Ai_MpSync.IsActive() then
    if numericId == nil then
      return false, "missing_unit_numeric_id", args
    end
    local syncOk, syncReason = Civ6Ai_MpSync.BroadcastMove(playerID, numericId, x, y)
    if syncOk then
      Civ6Ai_Util.Log(
        "apply|mp_sync|ok|player="
          .. tostring(playerID)
          .. "|unit="
          .. tostring(numericId)
          .. "|plot="
          .. tostring(x)
          .. ","
          .. tostring(y)
      )
      return true, "", args
    end
    return false, syncReason or "mp_sync_rejected", args
  end
  local params = {}
  if UnitOperationTypes ~= nil then
    params[UnitOperationTypes.PARAM_X] = x
    params[UnitOperationTypes.PARAM_Y] = y
  end
  local moveOp = UnitOperationTypes ~= nil and UnitOperationTypes.MOVE_TO or nil
  local plot = nil
  if Map ~= nil and Map.GetPlot ~= nil then
    plot = Map.GetPlot(x, y)
  end
  local ok, reason = Civ6Ai_Apply._RequestUnitOperation(unit, moveOp, params, "move", plot)
  if ok then
    return true, "", args
  end
  if numericId ~= nil then
    local scriptOk, scriptReason = Civ6Ai_Apply._MoveUnitGameCore(playerID, numericId, x, y)
    if scriptOk then
      return true, "", args
    end
    reason = scriptReason or reason
  end
  if not Civ6Ai_Apply._IsNetworkMultiplayer() then
    local fallbackOk, fallbackReason = Civ6Ai_Apply._WithLocalPlayer(playerID, function()
      local localUnit = Civ6Ai_Apply._FindUnit(playerID, unitId)
      if localUnit == nil then
        return false, "unit_not_found"
      end
      return Civ6Ai_Apply._RequestUnitOperation(localUnit, moveOp, params, nil, plot)
    end)
    if fallbackOk then
      Civ6Ai_Util.Log("apply|move|sp_local_player_fallback|player=" .. tostring(playerID))
      return true, "", args
    end
    reason = fallbackReason or reason
  end
  return false, reason or "move_rejected", args
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
  local numericId = Civ6Ai_Apply._ParseUnitNumericId(unitId)
  if numericId ~= nil and ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil and ExposedMembers.Civ6Ai.FoundCityForPlayer ~= nil then
    if ExposedMembers.Civ6Ai.FoundCityForPlayer(playerID, numericId) then
      Civ6Ai_Apply._ScheduleFoundCityFollowup(playerID)
      Civ6Ai_Util.Log("apply|found_city|gamecore|player=" .. tostring(playerID))
      return true, "", args
    end
  end
  return false, reason or "found_city_rejected", args
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
  local params = {}
  if UnitOperationTypes ~= nil then
    params[UnitOperationTypes.PARAM_X] = x
    params[UnitOperationTypes.PARAM_Y] = y
  end
  local attackOp = nil
  if UnitOperationTypes ~= nil then
    attackOp = UnitOperationTypes.RANGE_ATTACK or UnitOperationTypes.ATTACK
  end
  if attackOp == nil and GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
    local row = GameInfo.UnitOperations["UNITOPERATION_RANGE_ATTACK"]
    if row ~= nil then
      attackOp = row.Hash
    end
  end
  if attackOp == nil then
    return false, "attack_op_missing", args
  end
  local ok, reason = Civ6Ai_Apply._RequestUnitOperation(unit, attackOp, params, "attack")
  if ok then
    return true, "", args
  end
  if not Civ6Ai_Apply._IsNetworkMultiplayer() then
    local fallbackOk, fallbackReason = Civ6Ai_Apply._WithLocalPlayer(playerID, function()
      local localUnit = Civ6Ai_Apply._FindUnit(playerID, unitId)
      if localUnit == nil then
        return false, "unit_not_found"
      end
      return Civ6Ai_Apply._RequestUnitOperation(localUnit, attackOp, params, nil)
    end)
    if fallbackOk then
      return true, "", args
    end
    reason = fallbackReason or reason
  end
  return false, reason or "attack_rejected", args
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
  if UnitOperationTypes ~= nil and UnitOperationTypes.FORTIFY ~= nil then
    if UnitManager.RequestOperation(unit, UnitOperationTypes.FORTIFY) then
      return true, "", args
    end
  end
  UnitManager.FinishMoves(unit)
  return true, "finish_moves_fallback", args
end

function Civ6Ai_Apply._QueueProduction(playerID, args)
  if Civ6Ai_Production == nil then
    return false, "production_module_missing", args
  end
  local ok, reason = Civ6Ai_Production.QueueProduction(playerID, args)
  return ok, reason or "", args
end

function Civ6Ai_Apply._ParsePlotId(plotId)
  local text = tostring(plotId or "")
  local x, y = string.match(text, "PLOT_(%d+)_(%d+)")
  if x == nil then
    return nil, nil
  end
  return tonumber(x), tonumber(y)
end
