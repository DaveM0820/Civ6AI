-- Civ6Ai city production read/write (InGame).
Civ6Ai_Production = Civ6Ai_Production or {}

function Civ6Ai_Production._HashToTypeName(hash)
  if hash == nil or hash == 0 then
    return nil
  end
  for row in GameInfo.Units() do
    if row.Hash == hash then
      return row.UnitType
    end
  end
  for row in GameInfo.Buildings() do
    if row.Hash == hash then
      return row.BuildingType
    end
  end
  for row in GameInfo.Districts() do
    if row.Hash == hash then
      return row.DistrictType
    end
  end
  for row in GameInfo.Projects() do
    if row.Hash == hash then
      return row.ProjectType
    end
  end
  return "UNKNOWN_" .. tostring(hash)
end

function Civ6Ai_Production._WireCityId(city)
  return "CITY_" .. tostring(city:GetID())
end

function Civ6Ai_Production._GetCity(playerID, cityWireId)
  local numericId = tonumber((cityWireId or ""):match("CITY_(%d+)"))
  if numericId == nil then
    return nil
  end
  return CityManager.GetCity(playerID, numericId % 65536)
end

function Civ6Ai_Production._ResolveBuildItem(buildId)
  for row in GameInfo.Units() do
    if row.UnitType == buildId then
      return row, CityOperationTypes.PARAM_UNIT_TYPE
    end
  end
  for row in GameInfo.Buildings() do
    if row.BuildingType == buildId then
      return row, CityOperationTypes.PARAM_BUILDING_TYPE
    end
  end
  for row in GameInfo.Districts() do
    if row.DistrictType == buildId then
      return row, CityOperationTypes.PARAM_DISTRICT_TYPE
    end
  end
  for row in GameInfo.Projects() do
    if row.ProjectType == buildId then
      return row, CityOperationTypes.PARAM_PROJECT_TYPE
    end
  end
  return nil, nil
end

function Civ6Ai_Production._GetCityProduction(city)
  if city == nil then
    return nil
  end
  local bq = city:GetBuildQueue()
  if bq == nil or bq:GetSize() <= 0 then
    return nil
  end
  local hash = bq:GetCurrentProductionTypeHash()
  if hash == nil or hash == 0 then
    return nil
  end
  return Civ6Ai_Production._HashToTypeName(hash)
end

function Civ6Ai_Production._GetCityProductionState(city)
  local itemId = Civ6Ai_Production._GetCityProduction(city)
  local progress = 0
  local cost = 0
  local productionPerTurn = 0
  local turnsRemaining = nil
  if city == nil then
    return itemId, progress, cost, productionPerTurn, turnsRemaining
  end
  if city.GetYield ~= nil and YieldTypes ~= nil and YieldTypes.PRODUCTION ~= nil then
    productionPerTurn = city:GetYield(YieldTypes.PRODUCTION)
  end
  local bq = city:GetBuildQueue()
  if bq ~= nil then
    if bq.GetProgress ~= nil then
      progress = bq:GetProgress()
    elseif city.GetProductionProgress ~= nil then
      progress = city:GetProductionProgress()
    end
    if bq.GetCost ~= nil then
      cost = bq:GetCost()
    elseif city.GetProductionCost ~= nil then
      cost = city:GetProductionCost()
    end
    if bq.GetTurnsLeft ~= nil then
      local turns = bq:GetTurnsLeft()
      if turns ~= nil and turns >= 0 then
        turnsRemaining = turns
      end
    end
  end
  return itemId, progress, cost, productionPerTurn, turnsRemaining
end

function Civ6Ai_Production.CollectProductionMap(playerID)
  local map = {}
  local cities = Players[playerID]:GetCities()
  if cities == nil then
    return map
  end
  for _, city in cities:Members() do
    map[Civ6Ai_Production._WireCityId(city)] = Civ6Ai_Production._GetCityProduction(city)
  end
  return map
end

function Civ6Ai_Production.CountUnitsWithMoves(playerID)
  local count = 0
  local units = Players[playerID]:GetUnits()
  if units == nil then
    return 0
  end
  for unit in units:Members() do
    if unit:GetMovesRemaining() > 0 then
      count = count + 1
    end
  end
  return count
end

function Civ6Ai_Production._CanQueueBuild(city, buildId)
  if city == nil or buildId == nil or buildId == "" then
    return false
  end
  local item, paramKey = Civ6Ai_Production._ResolveBuildItem(buildId)
  if item == nil or paramKey == nil then
    return false
  end
  local bq = city:GetBuildQueue()
  if bq == nil or not bq:CanProduce(item.Hash, true) then
    return false
  end
  local tCheck = {}
  tCheck[paramKey] = item.Hash
  return CityManager.CanStartOperation(city, CityOperationTypes.BUILD, tCheck, true)
end

function Civ6Ai_Production.FindExperimentTarget(playerID)
  local cities = Players[playerID]:GetCities()
  if cities == nil then
    return nil, nil
  end
  local capital = nil
  for _, city in cities:Members() do
    if city:IsCapital() then
      capital = city
      break
    end
  end
  if capital == nil then
    for _, city in cities:Members() do
      capital = city
      break
    end
  end
  if capital == nil then
    return nil, nil
  end
  local cityWireId = Civ6Ai_Production._WireCityId(capital)
  local candidates = {
    "BUILDING_MONUMENT",
    "BUILDING_GRANARY",
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "UNIT_WARRIOR",
  }
  for _, buildId in ipairs(candidates) do
    if Civ6Ai_Production._CanQueueBuild(capital, buildId) then
      return cityWireId, buildId
    end
  end
  return cityWireId, nil
end

function Civ6Ai_Production.QueueProduction(playerID, args)
  args = args or {}
  return Civ6Ai_Production.QueueBuild(playerID, args.city_id, args.build_id)
end

function Civ6Ai_Production.QueueBuild(playerID, cityWireId, buildId)
  if buildId == nil or buildId == "" then
    return false, "missing_build_id"
  end
  local city = Civ6Ai_Production._GetCity(playerID, cityWireId)
  if city == nil then
    return false, "city_not_found"
  end
  local item, paramKey = Civ6Ai_Production._ResolveBuildItem(buildId)
  if item == nil or paramKey == nil then
    return false, "build_not_found"
  end
  local bq = city:GetBuildQueue()
  if bq == nil or not bq:CanProduce(item.Hash, true) then
    return false, "cannot_produce"
  end
  local tCheck = {}
  tCheck[paramKey] = item.Hash
  if not CityManager.CanStartOperation(city, CityOperationTypes.BUILD, tCheck, true) then
    return false, "cannot_start"
  end
  local tParams = {}
  tParams[paramKey] = item.Hash
  tParams[CityOperationTypes.PARAM_INSERT_MODE] = CityOperationTypes.VALUE_EXCLUSIVE
  CityManager.RequestOperation(city, CityOperationTypes.BUILD, tParams)
  return true, "queued"
end
