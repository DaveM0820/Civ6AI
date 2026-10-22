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
  -- CityManager.GetCity takes the per-player city index (low 16 bits of GetID).
  -- Gameplay cityById compares full GetID(); do not modulo on that path.
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

-- Autotest only. A real human game never queues for the local seat.
-- Highest weight the city can produce, ties broken by list order. No randomness.
Civ6Ai_Production.PEACE_PROFILE = {
  {"BUILDING_MONUMENT", 5},
  {"BUILDING_GRANARY", 4},
  {"UNIT_BUILDER", 3},
  {"UNIT_SETTLER", 3},
  {"UNIT_WARRIOR", 2},
  {"UNIT_SCOUT", 1},
}
Civ6Ai_Production.WAR_PROFILE = {
  {"UNIT_WARRIOR", 5},
  {"UNIT_ARCHER", 5},
  {"UNIT_CATAPULT", 4},
  {"BUILDING_WALLS", 4},
  {"UNIT_SPEARMAN", 3},
  {"BUILDING_MONUMENT", 1},
}

function Civ6Ai_Production._SeatAtWar(playerID)
  local player = Players[playerID]
  local diplo = player ~= nil and player.GetDiplomacy ~= nil and player:GetDiplomacy() or nil
  if diplo == nil or diplo.IsAtWarWith == nil then
    return false
  end
  for other = 0, 63 do
    if other ~= playerID and Players[other] ~= nil then
      local ok, atWar = pcall(diplo.IsAtWarWith, diplo, other)
      if ok and atWar == true then
        return true
      end
    end
  end
  return false
end

function Civ6Ai_Production._PickProfileItem(city, profile)
  local bestId, bestWeight = nil, -1
  for _, row in ipairs(profile) do
    local buildId, weight = row[1], row[2]
    if weight > bestWeight and Civ6Ai_Production._CanQueueBuild(city, buildId) then
      bestId, bestWeight = buildId, weight
    end
  end
  return bestId
end

function Civ6Ai_Production._QueueLocalBuild(city, buildId)
  local item, paramKey = Civ6Ai_Production._ResolveBuildItem(buildId)
  if item == nil or paramKey == nil or CityManager == nil or CityOperationTypes == nil then
    return false
  end
  local params = {}
  params[paramKey] = item.Hash
  params[CityOperationTypes.PARAM_INSERT_MODE] = CityOperationTypes.VALUE_EXCLUSIVE
  local ok, result = pcall(CityManager.RequestOperation, city, CityOperationTypes.BUILD, params)
  return ok and result ~= false
end

function Civ6Ai_Production.AutoqueueEmptyCities(playerID)
  if Civ6Ai_Config == nil or Civ6Ai_Config.IsAutotest == nil or not Civ6Ai_Config.IsAutotest() then
    return 0
  end
  if Game == nil or Game.GetLocalPlayer == nil or Game.GetLocalPlayer() ~= playerID then
    return 0
  end
  local player = Players[playerID]
  local cities = player ~= nil and player.GetCities ~= nil and player:GetCities() or nil
  if cities == nil or cities.Members == nil then
    return 0
  end
  local profile = Civ6Ai_Production._SeatAtWar(playerID) and Civ6Ai_Production.WAR_PROFILE
    or Civ6Ai_Production.PEACE_PROFILE
  local queued = 0
  for _, city in cities:Members() do
    local current = Civ6Ai_Production._GetCityProduction(city)
    if current == nil then
      local buildId = Civ6Ai_Production._PickProfileItem(city, profile)
      if buildId ~= nil and Civ6Ai_Production._QueueLocalBuild(city, buildId) then
        queued = queued + 1
        if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
          Civ6Ai_Util.Log("production|autoqueue|player=" .. tostring(playerID)
            .. "|city=" .. tostring(city:GetID()) .. "|build=" .. buildId)
        end
      end
    end
  end
  return queued
end

function Civ6Ai_Production.QueueProduction(playerID, args)
  return false, "production_requires_local_player"
end

function Civ6Ai_Production.QueueBuild(playerID, cityWireId, buildId, x, y)
  return false, "production_requires_local_player"
end
