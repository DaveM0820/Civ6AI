-- Civ6Ai GameCore — unit FinishMoves + file I/O + expose to InGame via ExposedMembers.
Civ6Ai_GameCore = Civ6Ai_GameCore or {}
print("CIV6AI|gamecore|load")

function Civ6Ai_GameCore._IterateUnits(playerUnits)
  local list = {}
  if playerUnits == nil then
    return list
  end
  if playerUnits.Members ~= nil then
    for _, unit in playerUnits:Members() do
      table.insert(list, unit)
    end
    return list
  end
  for i = 0, playerUnits:GetCount() - 1 do
    local unit = playerUnits:Get(i)
    if unit ~= nil then
      table.insert(list, unit)
    end
  end
  return list
end

function Civ6Ai_GameCore._EnsureParentDirs(path)
  if path == nil or path == "" then
    return false
  end
  local dir = path:gsub("\\", "/"):match("^(.*)/[^/]+$")
  if dir == nil or dir == "" then
    return true
  end
  if os == nil or os.execute == nil then
    return false
  end
  local winPath = dir:gsub("/", "\\")
  os.execute('cmd /c mkdir "' .. winPath .. '"')
  return true
end

function Civ6Ai_GameCore._Open(path, mode)
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

function Civ6Ai_GameCore.WriteFile(path, content)
  if path == nil or content == nil then
    return false
  end
  Civ6Ai_GameCore._EnsureParentDirs(path)
  local file = Civ6Ai_GameCore._Open(path, "w")
  if file == nil then
    return false
  end
  file:write(content)
  file:close()
  return true
end

function Civ6Ai_GameCore.ReadFile(path)
  if path == nil or path == "" then
    return nil
  end
  local file = Civ6Ai_GameCore._Open(path, "r")
  if file == nil then
    return nil
  end
  local text = file:read("*a")
  file:close()
  return text
end

function Civ6Ai_GameCore.AppendFile(path, line)
  if path == nil or line == nil then
    return false
  end
  Civ6Ai_GameCore._EnsureParentDirs(path)
  local file = Civ6Ai_GameCore._Open(path, "a")
  if file == nil then
    return false
  end
  file:write(line .. "\n")
  file:close()
  return true
end

function Civ6Ai_GameCore.ResolvePlayerUnits(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local units = player:GetUnits()
  if units == nil then
    return 0
  end
  local resolved = 0
  for _, unit in ipairs(Civ6Ai_GameCore._IterateUnits(units)) do
    if unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0 then
      UnitManager.FinishMoves(unit)
      resolved = resolved + 1
    end
  end
  return resolved
end

function Civ6Ai_GameCore.FoundCityForPlayer(playerID, unitNumericId)
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local units = player:GetUnits()
  if units == nil then
    return false
  end
  local unit = units:FindID(unitNumericId)
  if unit == nil then
    return false
  end
  local op = nil
  if UnitOperationTypes ~= nil and UnitOperationTypes.FOUND_CITY ~= nil then
    op = UnitOperationTypes.FOUND_CITY
  elseif GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
    local row = GameInfo.UnitOperations["UNITOPERATION_FOUND_CITY"]
    if row ~= nil then
      op = row.Hash
    end
  end
  if op == nil then
    return false
  end
  local params = {}
  if UnitManager.CanStartOperation ~= nil then
    local can = UnitManager.CanStartOperation(unit, op, nil, true)
    if not can then
      can = UnitManager.CanStartOperation(unit, op, nil, params, true)
    end
    if not can then
      return false
    end
  end
  if UnitManager.RequestOperation ~= nil then
    if UnitManager.RequestOperation(unit, op, params) then
      return true
    end
    if UnitManager.RequestOperation(unit, op) then
      return true
    end
  end
  local plot = Map.GetPlot(unit:GetX(), unit:GetY())
  local cities = player:GetCities()
  if cities ~= nil and cities.Create ~= nil and plot ~= nil then
    local created = cities:Create(plot:GetIndex())
    if created ~= nil then
      if UnitManager.Kill ~= nil then
        UnitManager.Kill(unit)
      end
      return true
    end
  end
  return false
end

function Civ6Ai_GameCore.MoveUnitForPlayer(playerID, unitNumericId, x, y)
  local player = Players[playerID]
  if player == nil then
    return false, "no_player"
  end
  local units = player:GetUnits()
  if units == nil then
    return false, "no_units"
  end
  local unit = units:FindID(unitNumericId)
  if unit == nil then
    return false, "unit_not_found"
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "plot_not_found"
  end
  local params = {}
  if UnitOperationTypes ~= nil and UnitOperationTypes.PARAM_X ~= nil then
    params[UnitOperationTypes.PARAM_X] = x
    params[UnitOperationTypes.PARAM_Y] = y
  end
  local moveOp = UnitOperationTypes ~= nil and UnitOperationTypes.MOVE_TO or nil
  if moveOp ~= nil and UnitManager.CanStartOperation ~= nil then
    if UnitManager.CanStartOperation(unit, moveOp, plot, true) then
      if UnitManager.RequestOperation ~= nil then
        if UnitManager.RequestOperation(unit, moveOp, plot) then
          return true, ""
        end
        if UnitManager.RequestOperation(unit, moveOp, params) then
          return true, ""
        end
      end
    end
  end
  if UnitManager.MoveUnit ~= nil and UnitManager.MoveUnit(unit, plot) then
    return true, ""
  end
  return false, "script_move_rejected"
end

function Civ6Ai_GameCore.SetResearchForPlayer(playerID, techIndex)
  local player = Players[playerID]
  if player == nil or player.GetTechs == nil then
    return false
  end
  local techs = player:GetTechs()
  if techs == nil or techs.SetResearchingTech == nil then
    return false
  end
  techs:SetResearchingTech(techIndex)
  return true
end

function Civ6Ai_OnPlayerTurnStartComplete(playerID)
  print("CIV6AI|gamecore|turn_start_complete|player=" .. tostring(playerID))
  if LuaEvents ~= nil and LuaEvents.Civ6Ai_PlayerTurnStartComplete ~= nil then
    LuaEvents.Civ6Ai_PlayerTurnStartComplete(playerID)
  end
end

function Civ6Ai_InitializeGameCore()
  Civ6Ai_GameCore = Civ6Ai_GameCore or {}
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  ExposedMembers.Civ6Ai.ResolvePlayerUnits = Civ6Ai_GameCore.ResolvePlayerUnits
  ExposedMembers.Civ6Ai.FoundCityForPlayer = Civ6Ai_GameCore.FoundCityForPlayer
  ExposedMembers.Civ6Ai.MoveUnitForPlayer = Civ6Ai_GameCore.MoveUnitForPlayer
  ExposedMembers.Civ6Ai.SetResearchForPlayer = Civ6Ai_GameCore.SetResearchForPlayer
  ExposedMembers.Civ6Ai.WriteFile = Civ6Ai_GameCore.WriteFile
  ExposedMembers.Civ6Ai.ReadFile = Civ6Ai_GameCore.ReadFile
  ExposedMembers.Civ6Ai.AppendFile = Civ6Ai_GameCore.AppendFile
  if Civ6Ai_Runtime ~= nil then
    ExposedMembers.Civ6Ai.Runtime = Civ6Ai_Runtime
  end
  local hasIo = io ~= nil and io.open ~= nil
  local hasExec = os ~= nil and os.execute ~= nil
  local hasGetenv = os ~= nil and os.getenv ~= nil
  ExposedMembers.Civ6Ai.Runtime = ExposedMembers.Civ6Ai.Runtime or {}
  ExposedMembers.Civ6Ai.Runtime.GameCoreIo = hasIo
  GameEvents.PlayerTurnStartComplete.Add(Civ6Ai_OnPlayerTurnStartComplete)
  print("CIV6AI|gamecore|ready|io=" .. tostring(hasIo) .. "|os_exec=" .. tostring(hasExec) .. "|getenv=" .. tostring(hasGetenv))
end

Civ6Ai_InitializeGameCore()
