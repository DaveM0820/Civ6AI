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
  if bq == nil then
    return nil
  end
  -- Read the hash first, as CityBannerManager does. GetSize() reads 0 in the
  -- InGame context for a local seat even while the banner shows a build.
  local okHash, hash = pcall(function() return bq:GetCurrentProductionTypeHash() end)
  if okHash and hash ~= nil and hash ~= 0 then
    return Civ6Ai_Production._HashToTypeName(hash)
  end
  local okType, typeName = pcall(function() return bq:CurrentlyBuilding() end)
  if okType and type(typeName) == "string" and typeName ~= "" and typeName ~= "NONE" then
    return typeName
  end
  return nil
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

-- The build lists in Data/Civ6Ai_Priorities.sql are AiFavoredItems (yields,
-- pseudoyields, promotion classes, districts) generated from
-- sidecar/civ6_priorities.py. They reweight the engine AI, which never queues
-- this local autotest seat, and they are not an ordered UNIT_/BUILDING_ list.
-- The old autofill therefore used two hardcoded peace/war profiles. Scoring
-- below turns those same weights into a CanProduce pick and layers war,
-- threat, a warlike leader, expansion, builders and variety on top.
-- BEGIN GENERATED PRIORITY_WEIGHTS (scripts/gen_priorities.py)
-- Level-1 item weights from sidecar/civ6_priorities.py CATEGORIES.
-- ScoreBuild multiplies level 2 by 2 and level 3 by 4, then clamps each
-- component at -100. Do not edit by hand.
Civ6Ai_Production.PRIORITY_WEIGHTS = {
  [1] = { YIELD_FOOD = 10, YIELD_CULTURE = 5, YIELD_FAITH = 5, PSEUDOYIELD_DISTRICT = 20, PSEUDOYIELD_IMPROVEMENT = 15, PSEUDOYIELD_WONDER = 15, PSEUDOYIELD_UNIT_SETTLER = 15, PSEUDOYIELD_STANDING_ARMY_NUMBER = -15, PSEUDOYIELD_STANDING_ARMY_VALUE = -15, PSEUDOYIELD_UNIT_COMBAT = -20, PSEUDOYIELD_UNIT_NAVAL_COMBAT = -20 }, -- peace
  [2] = { YIELD_PRODUCTION = 15, YIELD_GOLD = 10, YIELD_CULTURE = -10, YIELD_FAITH = -10, PSEUDOYIELD_UNIT_COMBAT = 50, PSEUDOYIELD_STANDING_ARMY_NUMBER = 20, PSEUDOYIELD_STANDING_ARMY_VALUE = 20, PSEUDOYIELD_GPP_GENERAL = 25, PSEUDOYIELD_DISTRICT = -25, PSEUDOYIELD_WONDER = -30, PSEUDOYIELD_IMPROVEMENT = -15, PSEUDOYIELD_UNIT_SETTLER = -20, PSEUDOYIELD_UNIT_ARCHAEOLOGIST = -50, PSEUDOYIELD_TOURISM = -30, PROMOTION_CLASS_SIEGE = 15, DISTRICT_ENCAMPMENT = 50 }, -- war
  [3] = { YIELD_PRODUCTION = 30, YIELD_GOLD = 20, YIELD_SCIENCE = -20, YIELD_CULTURE = -30, YIELD_FAITH = -30, PSEUDOYIELD_UNIT_COMBAT = 200, PSEUDOYIELD_STANDING_ARMY_NUMBER = 50, PSEUDOYIELD_STANDING_ARMY_VALUE = 50, PSEUDOYIELD_GPP_GENERAL = 50, PSEUDOYIELD_DISTRICT = -90, PSEUDOYIELD_WONDER = -100, PSEUDOYIELD_IMPROVEMENT = -60, PSEUDOYIELD_UNIT_SETTLER = -80, PSEUDOYIELD_UNIT_ARCHAEOLOGIST = -100, PSEUDOYIELD_UNIT_RELIGIOUS = -80, PSEUDOYIELD_UNIT_TRADE = -60, PSEUDOYIELD_TOURISM = -100, PSEUDOYIELD_SPACE_RACE = -80, PSEUDOYIELD_HAPPINESS = -50, PSEUDOYIELD_UNIT_NAVAL_COMBAT = -25, PROMOTION_CLASS_SIEGE = 25, DISTRICT_ENCAMPMENT = 100 }, -- total_war
  [4] = { YIELD_PRODUCTION = 15, YIELD_GOLD = 10, YIELD_CULTURE = -10, YIELD_FAITH = -10, PSEUDOYIELD_UNIT_NAVAL_COMBAT = 60, PSEUDOYIELD_STANDING_ARMY_NUMBER = 20, PSEUDOYIELD_STANDING_ARMY_VALUE = 20, PSEUDOYIELD_GPP_ADMIRAL = 30, PSEUDOYIELD_DISTRICT = -25, PSEUDOYIELD_WONDER = -30, PSEUDOYIELD_IMPROVEMENT = -15, PSEUDOYIELD_UNIT_SETTLER = -20, PSEUDOYIELD_UNIT_ARCHAEOLOGIST = -50, PSEUDOYIELD_TOURISM = -30, PROMOTION_CLASS_NAVAL_MELEE = 15, PROMOTION_CLASS_NAVAL_RANGED = 15, PROMOTION_CLASS_NAVAL_RAIDER = 10, DISTRICT_HARBOR = 60 }, -- naval_war
  [5] = { YIELD_PRODUCTION = 30, YIELD_GOLD = 20, YIELD_SCIENCE = -20, YIELD_CULTURE = -30, YIELD_FAITH = -30, PSEUDOYIELD_UNIT_NAVAL_COMBAT = 220, PSEUDOYIELD_STANDING_ARMY_NUMBER = 50, PSEUDOYIELD_STANDING_ARMY_VALUE = 50, PSEUDOYIELD_GPP_ADMIRAL = 50, PSEUDOYIELD_UNIT_COMBAT = -40, PSEUDOYIELD_DISTRICT = -90, PSEUDOYIELD_WONDER = -100, PSEUDOYIELD_IMPROVEMENT = -60, PSEUDOYIELD_UNIT_SETTLER = -80, PSEUDOYIELD_UNIT_ARCHAEOLOGIST = -100, PSEUDOYIELD_UNIT_RELIGIOUS = -80, PSEUDOYIELD_UNIT_TRADE = -60, PSEUDOYIELD_TOURISM = -100, PSEUDOYIELD_SPACE_RACE = -80, PSEUDOYIELD_HAPPINESS = -50, PROMOTION_CLASS_NAVAL_MELEE = 25, PROMOTION_CLASS_NAVAL_RANGED = 25, PROMOTION_CLASS_NAVAL_RAIDER = 20, PROMOTION_CLASS_NAVAL_CARRIER = 15, DISTRICT_HARBOR = 120 }, -- naval_total_war
  [6] = { YIELD_PRODUCTION = 15, YIELD_GOLD = 10, PSEUDOYIELD_CITY_DEFENSES = 100, PSEUDOYIELD_CITY_DEFENDING_UNITS = 50, PSEUDOYIELD_UNIT_COMBAT = 30, PSEUDOYIELD_CITY_BASE = -50, PSEUDOYIELD_WONDER = -30, PSEUDOYIELD_UNIT_SETTLER = -30, PROMOTION_CLASS_RANGED = 15, PROMOTION_CLASS_ANTI_CAVALRY = 15, PROMOTION_CLASS_SIEGE = -50, DISTRICT_ENCAMPMENT = 40 }, -- defense
  [7] = { PSEUDOYIELD_UNIT_AIR_COMBAT = 100, PSEUDOYIELD_STANDING_ARMY_VALUE = 15, PROMOTION_CLASS_AIR_FIGHTER = 20, PROMOTION_CLASS_AIR_BOMBER = 20, DISTRICT_AERODROME = 80 }, -- air_power
  [8] = { YIELD_SCIENCE = 40, PSEUDOYIELD_TECHNOLOGY = 25, PSEUDOYIELD_GPP_SCIENTIST = 40, PSEUDOYIELD_SPACE_RACE = 50, DISTRICT_CAMPUS = 60, DISTRICT_SPACEPORT = 60 }, -- science_victory
  [9] = { YIELD_CULTURE = 40, PSEUDOYIELD_CIVIC = 25, PSEUDOYIELD_TOURISM = 60, PSEUDOYIELD_GPP_ARTIST = 30, PSEUDOYIELD_GPP_MUSICIAN = 30, PSEUDOYIELD_GPP_WRITER = 30, PSEUDOYIELD_GREATWORK_WRITING = 20, PSEUDOYIELD_GREATWORK_PORTRAIT = 20, PSEUDOYIELD_GREATWORK_LANDSCAPE = 20, PSEUDOYIELD_GREATWORK_SCULPTURE = 20, PSEUDOYIELD_GREATWORK_MUSIC = 20, PSEUDOYIELD_GREATWORK_ARTIFACT = 20, PSEUDOYIELD_UNIT_ARCHAEOLOGIST = 40, PSEUDOYIELD_WONDER = 25, PROMOTION_CLASS_ROCK_BAND = 20, DISTRICT_THEATER = 60 }, -- culture_victory
  [10] = { YIELD_FAITH = 50, PSEUDOYIELD_UNIT_RELIGIOUS = 80, PSEUDOYIELD_GPP_PROPHET = 60, PSEUDOYIELD_RELIGIOUS_CONVERT_EMPIRE = 50, PSEUDOYIELD_GREATWORK_RELIC = 20, PSEUDOYIELD_GREATWORK_RELIGIOUS = 20, PROMOTION_CLASS_APOSTLE = 20, DISTRICT_HOLY_SITE = 60 }, -- religious_victory
  [11] = { YIELD_GOLD = 15, PSEUDOYIELD_DIPLOMATIC_FAVOR = 50, PSEUDOYIELD_DIPLOMATIC_VICTORY_POINT = 50, PSEUDOYIELD_INFLUENCE = 50, PSEUDOYIELD_DIPLOMATIC_BONUS = 50, PSEUDOYIELD_DIPLOMATIC_GRIEVANCE = 30, DISTRICT_GOVERNMENT = 40, DISTRICT_DIPLOMATIC_QUARTER = 60 }, -- diplomatic_victory
  [12] = { YIELD_PRODUCTION = 15, PSEUDOYIELD_CITY_BASE = 50, PSEUDOYIELD_CITY_ORIGINAL_CAPITAL = 50, PSEUDOYIELD_UNIT_COMBAT = 60, PSEUDOYIELD_STANDING_ARMY_VALUE = 30, PSEUDOYIELD_GPP_GENERAL = 40, PSEUDOYIELD_TOURISM = -50, PROMOTION_CLASS_SIEGE = 20, DISTRICT_ENCAMPMENT = 60 }, -- domination_victory
  [13] = { YIELD_GOLD = 100, PSEUDOYIELD_STANDING_ARMY_NUMBER = -60, PSEUDOYIELD_STANDING_ARMY_VALUE = -60, PSEUDOYIELD_UNIT_COMBAT = -60, PSEUDOYIELD_UNIT_NAVAL_COMBAT = -60, PSEUDOYIELD_UNIT_AIR_COMBAT = -60, PSEUDOYIELD_DISTRICT = -30, PSEUDOYIELD_WONDER = -30, PSEUDOYIELD_UNIT_TRADE = 50, PSEUDOYIELD_GPP_MERCHANT = 30, DISTRICT_COMMERCIAL_HUB = 80, DISTRICT_HARBOR = 40 }, -- fix_bankruptcy
  [14] = { YIELD_GOLD = 40, PSEUDOYIELD_GPP_MERCHANT = 30, PSEUDOYIELD_UNIT_TRADE = 30, DISTRICT_COMMERCIAL_HUB = 60, DISTRICT_HARBOR = 30 }, -- gold
  [15] = { YIELD_GOLD = 15, PSEUDOYIELD_UNIT_TRADE = 100, DISTRICT_COMMERCIAL_HUB = 50, DISTRICT_HARBOR = 40 }, -- trade
  [16] = { PSEUDOYIELD_HAPPINESS = 100, PSEUDOYIELD_RESOURCE_LUXURY = 80, DISTRICT_ENTERTAINMENT_COMPLEX = 80, DISTRICT_WATER_ENTERTAINMENT_COMPLEX = 60 }, -- amenities
  [17] = { YIELD_FOOD = 50, PSEUDOYIELD_CITY_POPULATION = 50, PSEUDOYIELD_IMPROVEMENT = 15, DISTRICT_AQUEDUCT = 60, DISTRICT_NEIGHBORHOOD = 60 }, -- growth
  [18] = { YIELD_PRODUCTION = 50, PSEUDOYIELD_GPP_ENGINEER = 30, PSEUDOYIELD_IMPROVEMENT = 15, DISTRICT_INDUSTRIAL_ZONE = 70 }, -- production
  [19] = { PSEUDOYIELD_UNIT_SETTLER = 100, PSEUDOYIELD_UNIT_EXPLORER = 20, PSEUDOYIELD_WONDER = -20 }, -- expansion
  [20] = { YIELD_FOOD = 10, YIELD_PRODUCTION = 10, PSEUDOYIELD_IMPROVEMENT = 80 }, -- improvements
  [21] = { YIELD_PRODUCTION = 15, PSEUDOYIELD_WONDER = 100, PSEUDOYIELD_GPP_ENGINEER = 30 }, -- wonders
  [22] = { PSEUDOYIELD_GPP_ADMIRAL = 50, PSEUDOYIELD_GPP_ARTIST = 50, PSEUDOYIELD_GPP_ENGINEER = 50, PSEUDOYIELD_GPP_GENERAL = 50, PSEUDOYIELD_GPP_MERCHANT = 50, PSEUDOYIELD_GPP_MUSICIAN = 50, PSEUDOYIELD_GPP_PROPHET = 50, PSEUDOYIELD_GPP_SCIENTIST = 50, PSEUDOYIELD_GPP_WRITER = 50, PSEUDOYIELD_DISTRICT = 15 }, -- great_people
  [23] = { YIELD_FAITH = 50, PSEUDOYIELD_GPP_PROPHET = 20, DISTRICT_HOLY_SITE = 50 }, -- faith
  [24] = { PSEUDOYIELD_UNIT_EXPLORER = 100, PROMOTION_CLASS_RECON = 30 }, -- exploration
}
Civ6Ai_Production.PRIORITY_GROUP = {
  [1] = "posture",
  [2] = "posture",
  [3] = "posture",
  [4] = "posture",
  [5] = "posture",
  [6] = "posture",
  [7] = "posture",
  [8] = "focus",
  [9] = "focus",
  [10] = "focus",
  [11] = "focus",
  [12] = "focus",
  [13] = "focus",
  [14] = "focus",
  [15] = "focus",
  [16] = "focus",
  [17] = "focus",
  [18] = "focus",
  [19] = "focus",
  [20] = "focus",
  [21] = "focus",
  [22] = "focus",
  [23] = "focus",
  [24] = "focus",
}
Civ6Ai_Production.PRIORITY_KEY_ID = {
  peace = 1,
  war = 2,
  total_war = 3,
  naval_war = 4,
  naval_total_war = 5,
  defense = 6,
  air_power = 7,
  science_victory = 8,
  culture_victory = 9,
  religious_victory = 10,
  diplomatic_victory = 11,
  domination_victory = 12,
  fix_bankruptcy = 13,
  gold = 14,
  trade = 15,
  amenities = 16,
  growth = 17,
  production = 18,
  expansion = 19,
  improvements = 20,
  wonders = 21,
  great_people = 22,
  faith = 23,
  exploration = 24,
}
-- END GENERATED PRIORITY_WEIGHTS

local function call(obj, method, ...)
  if obj == nil or obj[method] == nil then
    return nil
  end
  local ok, value = pcall(obj[method], obj, ...)
  if ok then
    return value
  end
  return nil
end

local function eachRow(tableName, fn)
  if GameInfo == nil or GameInfo[tableName] == nil then
    return
  end
  pcall(function()
    for row in GameInfo[tableName]() do
      fn(row)
    end
  end)
end

local function findRow(tableName, field, value)
  local found = nil
  eachRow(tableName, function(row)
    if found == nil and row[field] == value then
      found = row
    end
  end)
  return found
end

local function eachMember(collection, fn)
  if collection == nil or collection.Members == nil then
    return false
  end
  local ok = pcall(function()
    for a, b in collection:Members() do
      local item = b
      if item == nil then
        item = a
      end
      if item ~= nil and type(item) ~= "number" then
        fn(item)
      end
    end
  end)
  return ok
end

local function positive(value)
  local n = tonumber(value)
  return n ~= nil and n > 0
end

function Civ6Ai_Production.WeightVector(levels, halfWar)
  local acc = {}
  local mult = { [1] = 1, [2] = 2, [3] = 4 }
  if levels ~= nil then
    for id, level in pairs(levels) do
      local weights = Civ6Ai_Production.PRIORITY_WEIGHTS[id]
      local m = mult[level]
      if weights ~= nil and m ~= nil then
        for item, value in pairs(weights) do
          local v = value * m
          if v < -100 then
            v = -100
          end
          acc[item] = (acc[item] or 0) + v
        end
      end
    end
  end
  local warId = Civ6Ai_Production.PRIORITY_KEY_ID ~= nil and Civ6Ai_Production.PRIORITY_KEY_ID.war or nil
  if halfWar and warId ~= nil then
    local weights = Civ6Ai_Production.PRIORITY_WEIGHTS[warId]
    if weights ~= nil then
      for item, value in pairs(weights) do
        local v = value
        if v < -100 then
          v = -100
        end
        acc[item] = (acc[item] or 0) + math.floor(v / 2)
      end
    end
  end
  return acc
end

function Civ6Ai_Production.ComposeSituation(raw)
  raw = raw or {}
  local levels = {}
  local posture = false
  local militaryOn = false
  local military = {}
  local keys = Civ6Ai_Production.PRIORITY_KEY_ID or {}
  for _, key in ipairs({ "war", "total_war", "naval_war", "naval_total_war", "domination_victory" }) do
    if keys[key] ~= nil then
      military[keys[key]] = true
    end
  end
  if raw.saved ~= nil then
    for rawId, rawLevel in pairs(raw.saved) do
      local id = tonumber(rawId)
      local level = tonumber(rawLevel)
      if id ~= nil and level ~= nil and level >= 1 and level <= 3
          and Civ6Ai_Production.PRIORITY_WEIGHTS[id] ~= nil then
        levels[id] = level
        if Civ6Ai_Production.PRIORITY_GROUP[id] == "posture" then
          posture = true
        end
        if military[id] then
          militaryOn = true
        end
      end
    end
  end
  if not posture and keys.peace ~= nil then
    levels[keys.peace] = 1
  end
  local wars = tonumber(raw.major_wars) or 0
  if wars > 0 and not militaryOn and keys.war ~= nil and (levels[keys.war] or 0) < 1 then
    levels[keys.war] = 1
  end
  local cities = tonumber(raw.cities) or 1
  local pop = tonumber(raw.pop) or 1
  local land = raw.land ~= false
  local turn = tonumber(raw.turn) or 0
  local era = tonumber(raw.era) or 0
  if era < 0 then
    era = 0
  end
  local builders = tonumber(raw.builders) or 0
  local army = tonumber(raw.military) or 0
  local threatened = raw.threatened == true
  local warlike = raw.warlike == true
  -- Online T70 aims at 6 cities, or 8 while land is free. speed_num is the
  -- game-speed percent (Online 200). Missing means Online. Keep this in step
  -- with sidecar/civ6_priorities.py city_count_target.
  local speedNum = tonumber(raw.speed_num) or 200
  if speedNum <= 0 then
    speedNum = 200
  end
  local online = math.floor(turn * speedNum / 200)
  if online > 70 then
    online = 70
  end
  if online < 0 then
    online = 0
  end
  local span = land == false and 4 or 6
  local target = 2 + math.floor(span * online / 70)
  local belowTarget = cities < target and turn <= 100 and pop >= 2 and land == true
  local needExpansion = belowTarget and wars <= 0
  local needBuilders = builders < cities
  local needed = cities
  if wars > 0 then
    needed = needed + cities
  end
  if threatened then
    needed = needed + 1
  end
  if warlike then
    needed = needed + 1
  end
  if (threatened or army < needed) and keys.defense ~= nil and (levels[keys.defense] or 0) < 1 then
    levels[keys.defense] = 1
  end
  if needExpansion and wars <= 0 and keys.expansion ~= nil then
    local want = (cities + 2 < target) and 2 or 1
    if (levels[keys.expansion] or 0) < want then
      levels[keys.expansion] = want
    end
  end
  if needBuilders and keys.improvements ~= nil and (levels[keys.improvements] or 0) < 1 then
    levels[keys.improvements] = 1
  end
  local counts = {}
  if raw.unit_counts ~= nil then
    for key, value in pairs(raw.unit_counts) do
      counts[key] = tonumber(value) or 0
    end
  end
  return {
    levels = levels,
    half_war = warlike and (levels[keys.war] or 0) == 0,
    military_over = army >= needed + 2,
    army_heavy = wars <= 0 and army > cities * 2,
    at_war = wars > 0,
    missing_monument = raw.missing_monument == true,
    missing_granary = raw.missing_granary == true,
    missing_district = raw.missing_district == true,
    pop = pop,
    land = land,
    need_expansion = needExpansion,
    threatened = threatened,
    last = raw.last,
    unit_counts = counts,
  }
end

function Civ6Ai_Production.ScoreBuild(buildId, tags, situation, kind)
  situation = situation or {}
  local weights = Civ6Ai_Production.WeightVector(situation.levels, situation.half_war == true)
  local seen = {}
  local score = 0
  if tags ~= nil then
    for _, tag in ipairs(tags) do
      if not seen[tag] then
        seen[tag] = true
        score = score + (weights[tag] or 0)
      end
    end
  end
  if seen["PSEUDOYIELD_UNIT_COMBAT"] then
    if situation.army_heavy == true then
      score = score - 80
    elseif situation.military_over == true then
      score = score - 40
    end
  end
  if situation.missing_monument == true and buildId == "BUILDING_MONUMENT" then
    score = score + 15
  end
  if situation.missing_granary == true and buildId == "BUILDING_GRANARY" then
    score = score + 15
  end
  if situation.missing_district == true and kind == "district"
      and buildId ~= "DISTRICT_CITY_CENTER"
      and string.find(tostring(buildId), "WONDER", 1, true) == nil then
    score = score + 10
  end
  -- Walls come from the defense list. At peace, with no enemy nearby, they
  -- lose to a settler. A war or a threatened city keeps the defense weight.
  if seen["PSEUDOYIELD_CITY_DEFENSES"] and situation.threatened ~= true and situation.at_war ~= true then
    score = score - 120
  end
  if seen["PSEUDOYIELD_UNIT_SETTLER"] or buildId == "UNIT_SETTLER" then
    if (tonumber(situation.pop) or 1) < 2 or situation.land == false then
      score = score - 200
    end
    if situation.need_expansion ~= true then
      score = score - 40
    end
  end
  if situation.last == buildId then
    score = score - 50
  end
  if kind == "unit" or string.sub(tostring(buildId or ""), 1, 5) == "UNIT_" then
    local n = tonumber((situation.unit_counts or {})[buildId]) or 0
    if n > 2 then
      score = score - 25 * (n - 2)
    end
  end
  return score
end

function Civ6Ai_Production.PickBuild(candidates, situation)
  local bestId, bestScore = nil, nil
  for _, cand in ipairs(candidates or {}) do
    local id = cand.id
    local tags = cand.tags
    local kind = cand.kind or ""
    if tags == nil and id ~= nil then
      tags, kind = Civ6Ai_Production._TagsFor(id)
    end
    local score = Civ6Ai_Production.ScoreBuild(id, tags, situation, kind)
    if bestScore == nil or score > bestScore or (score == bestScore and id < bestId) then
      bestId, bestScore = id, score
    end
  end
  return bestId, bestScore
end

-- Every candidate, best first (same score and tie order as PickBuild).
function Civ6Ai_Production.RankBuilds(candidates, situation)
  local scored = {}
  for _, cand in ipairs(candidates or {}) do
    local tags, kind = cand.tags, cand.kind or ""
    if tags == nil and cand.id ~= nil then
      tags, kind = Civ6Ai_Production._TagsFor(cand.id)
    end
    if cand.id ~= nil then
      table.insert(scored, { id = cand.id, score = Civ6Ai_Production.ScoreBuild(cand.id, tags, situation, kind) })
    end
  end
  table.sort(scored, function(a, b)
    if a.score ~= b.score then
      return a.score > b.score
    end
    return a.id < b.id
  end)
  local out = {}
  for _, row in ipairs(scored) do
    table.insert(out, row.id)
  end
  return out
end

function Civ6Ai_Production._TagsFor(buildId)
  local tags = {}
  local seen = {}
  local function add(tag)
    if tag ~= nil and tag ~= "" and not seen[tag] then
      seen[tag] = true
      table.insert(tags, tag)
    end
  end
  local id = tostring(buildId or "")
  if string.sub(id, 1, 5) == "UNIT_" then
    local row = findRow("Units", "UnitType", id) or {}
    local promo = row.PromotionClass or ""
    local formation = row.FormationClass or ""
    local naval = {
      PROMOTION_CLASS_NAVAL_MELEE = true,
      PROMOTION_CLASS_NAVAL_RANGED = true,
      PROMOTION_CLASS_NAVAL_RAIDER = true,
      PROMOTION_CLASS_NAVAL_CARRIER = true,
    }
    local air = { PROMOTION_CLASS_AIR_FIGHTER = true, PROMOTION_CLASS_AIR_BOMBER = true }
    local religious = {
      PROMOTION_CLASS_APOSTLE = true,
      PROMOTION_CLASS_MISSIONARY = true,
      PROMOTION_CLASS_INQUISITOR = true,
      PROMOTION_CLASS_WARRIOR_MONK = true,
      PROMOTION_CLASS_GURU = true,
    }
    if row.FoundCity == true or row.FoundCity == 1 or id == "UNIT_SETTLER" then
      add("PSEUDOYIELD_UNIT_SETTLER")
    elseif positive(row.BuildCharges) or id == "UNIT_BUILDER" then
      add("PSEUDOYIELD_IMPROVEMENT")
    elseif promo == "PROMOTION_CLASS_RECON" or string.find(id, "SCOUT", 1, true) ~= nil then
      add("PSEUDOYIELD_UNIT_EXPLORER")
      add(promo ~= "" and promo or "PROMOTION_CLASS_RECON")
    elseif naval[promo] or formation == "FORMATION_CLASS_NAVAL" then
      add("PSEUDOYIELD_UNIT_NAVAL_COMBAT")
      add(promo)
    elseif air[promo] or formation == "FORMATION_CLASS_AIR" then
      add("PSEUDOYIELD_UNIT_AIR_COMBAT")
      add(promo)
    elseif positive(row.ReligiousStrength) or religious[promo] then
      add("PSEUDOYIELD_UNIT_RELIGIOUS")
      add(promo)
    elseif id == "UNIT_TRADER" or promo == "PROMOTION_CLASS_TRADER" then
      add("PSEUDOYIELD_UNIT_TRADE")
    elseif positive(row.Combat) or positive(row.RangedCombat) or string.sub(promo, 1, 16) == "PROMOTION_CLASS_" then
      add("PSEUDOYIELD_UNIT_COMBAT")
      if promo ~= "" then
        add(promo)
      elseif positive(row.RangedCombat) then
        add("PROMOTION_CLASS_RANGED")
      else
        add("PROMOTION_CLASS_MELEE")
      end
    end
    return tags, "unit"
  end
  if string.sub(id, 1, 9) == "DISTRICT_" then
    add(id)
    add("PSEUDOYIELD_DISTRICT")
    eachRow("DistrictReplaces", function(row)
      if row.CivUniqueDistrictType == id then
        add(row.ReplacesDistrictType)
      end
    end)
    local row = findRow("Districts", "DistrictType", id) or {}
    if row.IsWonder == true or string.find(id, "WONDER", 1, true) ~= nil then
      add("PSEUDOYIELD_WONDER")
    end
    return tags, "district"
  end
  local kind = "project"
  if string.sub(id, 1, 9) == "BUILDING_" then
    kind = "building"
    if string.find(id, "WALL", 1, true) or string.find(id, "CASTLE", 1, true)
        or string.find(id, "STAR_FORT", 1, true) then
      add("PSEUDOYIELD_CITY_DEFENSES")
    end
    local row = findRow("Buildings", "BuildingType", id) or {}
    if row.IsWonder == true or row.IsWonder == 1 then
      add("PSEUDOYIELD_WONDER")
    end
    if row.PrereqDistrict ~= nil and row.PrereqDistrict ~= "" then
      add(row.PrereqDistrict)
    end
    local added = false
    local sawYield = false
    eachRow("Building_YieldChanges", function(y)
      if y.BuildingType == id then
        sawYield = true
        if positive(y.YieldChange) then
          add(y.YieldType)
          added = true
        end
      end
    end)
    if not added and positive(row.Housing) then
      add("YIELD_FOOD")
      added = true
    end
    if not added and not sawYield and row.Housing == nil then
      if string.find(id, "MONUMENT", 1, true) then
        add("YIELD_CULTURE")
      elseif string.find(id, "GRANARY", 1, true) then
        add("YIELD_FOOD")
      end
    end
  end
  return tags, kind
end

function Civ6Ai_Production._CanProduce(city, buildId)
  if city == nil or buildId == nil or buildId == "" then
    return false
  end
  local item = Civ6Ai_Production._ResolveBuildItem(buildId)
  if item == nil then
    return false
  end
  local bq = call(city, "GetBuildQueue")
  if bq == nil or bq.CanProduce == nil then
    return false
  end
  local ok, can = pcall(bq.CanProduce, bq, item.Hash, true)
  if not (ok and can == true) then
    return false
  end
  -- CanProduce ignores PopulationCost. A settler the city is too small to
  -- train is accepted, then never sticks, and the next ranked item (walls) does.
  return not Civ6Ai_Production._PopulationBlocked(city, buildId)
end

function Civ6Ai_Production._PopulationBlocked(city, buildId)
  local id = tostring(buildId or "")
  if string.sub(id, 1, 5) ~= "UNIT_" then
    return false
  end
  local row = findRow("Units", "UnitType", id)
  local cost = row ~= nil and tonumber(row.PopulationCost) or nil
  local found = id == "UNIT_SETTLER" or (row ~= nil and (row.FoundCity == true or row.FoundCity == 1))
  if (cost == nil or cost <= 0) and found then
    cost = 1
  end
  if cost == nil or cost <= 0 then
    return false
  end
  local pop = tonumber(call(city, "GetPopulation")) or 1
  return pop <= cost
end

function Civ6Ai_Production._Candidates(city)
  local out = {}
  local function consider(tableName, field)
    eachRow(tableName, function(row)
      local id = row[field]
      if id ~= nil and Civ6Ai_Production._CanProduce(city, id) then
        local tags, kind = Civ6Ai_Production._TagsFor(id)
        table.insert(out, { id = id, tags = tags, kind = kind })
      end
    end)
  end
  consider("Units", "UnitType")
  consider("Buildings", "BuildingType")
  consider("Districts", "DistrictType")
  consider("Projects", "ProjectType")
  return out
end

function Civ6Ai_Production._SavedLevels(playerID)
  local levels = {}
  if Game == nil or Game.GetProperty == nil then
    return levels
  end
  for id, _group in pairs(Civ6Ai_Production.PRIORITY_GROUP or {}) do
    local ok, value = pcall(function()
      return Game:GetProperty("CIV6AI_PRIO_" .. tostring(playerID) .. "_" .. tostring(id))
    end)
    if ok and type(value) == "number" and value >= 1 and value <= 3 then
      levels[id] = value
    end
  end
  return levels
end

-- Only wars with major civs turn on the war list. Barbarians are always at
-- war with everyone, and counting them made the old profile build warriors
-- forever. A barbarian unit next to a city is a threat and uses the defense list.
function Civ6Ai_Production._MajorWars(playerID)
  local diplo = call(Players ~= nil and Players[playerID] or nil, "GetDiplomacy")
  if diplo == nil or diplo.IsAtWarWith == nil or Players == nil then
    return 0
  end
  local n = 0
  for other = 0, 63 do
    if other ~= playerID and Players[other] ~= nil
        and call(Players[other], "IsAlive") == true
        and call(Players[other], "IsMajor") == true
        and call(diplo, "IsAtWarWith", other) == true then
      n = n + 1
    end
  end
  return n
end

function Civ6Ai_Production._CityThreatened(playerID, city)
  if city == nil or Map == nil or Map.GetPlotDistance == nil or Players == nil then
    return false
  end
  local cx, cy = call(city, "GetX"), call(city, "GetY")
  if cx == nil or cy == nil then
    return false
  end
  local diplo = call(Players[playerID], "GetDiplomacy")
  for other = 0, 63 do
    if other ~= playerID and Players[other] ~= nil then
      local hostile = call(Players[other], "IsBarbarian") == true
          or (diplo ~= nil and call(diplo, "IsAtWarWith", other) == true)
      if hostile then
        local hit = false
        eachMember(call(Players[other], "GetUnits"), function(unit)
          if hit or GameInfo == nil or GameInfo.Units == nil or unit.GetType == nil then
            return
          end
          local ok, info = pcall(function() return GameInfo.Units[unit:GetType()] end)
          local combat = ok and info ~= nil and (tonumber(info.Combat) or 0) or 0
          local ranged = ok and info ~= nil and (tonumber(info.RangedCombat) or 0) or 0
          if combat > 0 or ranged > 0 then
            local ux, uy = call(unit, "GetX"), call(unit, "GetY")
            local dist = ux ~= nil and uy ~= nil and Map.GetPlotDistance(cx, cy, ux, uy) or nil
            if dist ~= nil and dist > 0 and dist <= 4 then
              hit = true
            end
          end
        end)
        if hit then
          return true
        end
      end
    end
  end
  return false
end

function Civ6Ai_Production._OpenLand(city)
  if Map == nil or Map.GetPlotCount == nil or Map.GetPlotByIndex == nil or Map.GetPlotDistance == nil then
    return true
  end
  local cx, cy = call(city, "GetX"), call(city, "GetY")
  if cx == nil or cy == nil then
    return true
  end
  local count = Map.GetPlotCount()
  if type(count) ~= "number" then
    return true
  end
  for i = 0, count - 1 do
    local plot = Map.GetPlotByIndex(i)
    if plot ~= nil then
      local px, py = call(plot, "GetX"), call(plot, "GetY")
      local dist = px ~= nil and py ~= nil and Map.GetPlotDistance(cx, cy, px, py) or nil
      if dist ~= nil and dist > 0 and dist <= 6 then
        local owner = call(plot, "GetOwner")
        local impassable = call(plot, "IsImpassable") == true
        local water = call(plot, "IsWater") == true
        if not impassable and not water and (type(owner) ~= "number" or owner < 0) then
          return true
        end
      end
    end
  end
  return false
end

Civ6Ai_Production._warlikeCache = Civ6Ai_Production._warlikeCache or {}

function Civ6Ai_Production._Warlike(playerID)
  local turn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or 0
  local key = tostring(playerID) .. ":" .. tostring(turn)
  if Civ6Ai_Production._warlikeCache[key] ~= nil then
    return Civ6Ai_Production._warlikeCache[key]
  end
  local bias = 0
  local cfg = PlayerConfigurations ~= nil and PlayerConfigurations[playerID] or nil
  local civ = call(cfg, "GetCivilizationTypeName")
  local leader = call(cfg, "GetLeaderTypeName")
  local traits = {}
  for _, tableName in ipairs({ "CivilizationTraits", "LeaderTraits" }) do
    eachRow(tableName, function(row)
      if (civ ~= nil and row.CivilizationType == civ) or (leader ~= nil and row.LeaderType == leader) then
        if row.TraitType ~= nil then
          traits[row.TraitType] = true
        end
      end
    end)
  end
  eachRow("Units", function(row)
    if bias < 20 and row.TraitType ~= nil and traits[row.TraitType] and (tonumber(row.Combat) or 0) > 0 then
      bias = bias + 20
    end
  end)
  local lists = {}
  eachRow("AiLists", function(row)
    if row.ListType ~= nil and ((leader ~= nil and row.LeaderType == leader) or (civ ~= nil and row.LeaderType == civ)) then
      lists[row.ListType] = true
    end
  end)
  local watch = {
    PSEUDOYIELD_UNIT_COMBAT = true,
    PSEUDOYIELD_STANDING_ARMY_NUMBER = true,
    PSEUDOYIELD_STANDING_ARMY_VALUE = true,
  }
  eachRow("AiFavoredItems", function(row)
    local value = tonumber(row.Value) or 0
    if lists[row.ListType] and watch[row.Item] and value > 0 then
      bias = bias + value
    end
  end)
  local warlike = bias > 0
  Civ6Ai_Production._warlikeCache[key] = warlike
  return warlike
end

function Civ6Ai_Production._ArmyCounts(playerID)
  local builders, military = 0, 0
  eachMember(call(Players ~= nil and Players[playerID] or nil, "GetUnits"), function(unit)
    local info = nil
    if GameInfo ~= nil and GameInfo.Units ~= nil and unit.GetType ~= nil then
      local ok, row = pcall(function() return GameInfo.Units[unit:GetType()] end)
      if ok then
        info = row
      end
    end
    if info ~= nil then
      if (tonumber(info.BuildCharges) or 0) > 0 or info.UnitType == "UNIT_BUILDER" then
        builders = builders + 1
      end
      if (tonumber(info.Combat) or 0) > 0 or (tonumber(info.RangedCombat) or 0) > 0 then
        military = military + 1
      end
    end
  end)
  return builders, military
end

function Civ6Ai_Production._HasBuilding(city, typeName)
  local buildings = call(city, "GetBuildings")
  if buildings == nil or buildings.HasBuilding == nil then
    return nil
  end
  local row = findRow("Buildings", "BuildingType", typeName)
  if (row == nil or row.Index == nil) and GameInfo ~= nil and GameInfo.Buildings ~= nil then
    local ok, indexed = pcall(function() return GameInfo.Buildings[typeName] end)
    if ok then
      row = indexed
    end
  end
  if row == nil or row.Index == nil then
    return nil
  end
  local has = call(buildings, "HasBuilding", row.Index)
  if has == nil then
    return nil
  end
  return has == true
end

function Civ6Ai_Production._MissingDistrict(city)
  local districts = call(city, "GetDistricts")
  if districts == nil or districts.Members == nil then
    return false
  end
  local saw, any = false, false
  eachMember(districts, function(district)
    saw = true
    local info = nil
    if GameInfo ~= nil and GameInfo.Districts ~= nil and district.GetType ~= nil then
      local ok, row = pcall(function() return GameInfo.Districts[district:GetType()] end)
      if ok then
        info = row
      end
    end
    local id = info ~= nil and info.DistrictType or ""
    local wonder = (info ~= nil and info.IsWonder == true) or string.find(id, "WONDER", 1, true) ~= nil
    if id ~= "" and id ~= "DISTRICT_CITY_CENTER" and not wonder then
      any = true
    end
  end)
  if not saw then
    return false
  end
  return not any
end

local function currentEra()
  local eras = call(Game, "GetEras")
  local era = call(eras, "GetCurrentEra")
  if type(era) ~= "number" then
    return 0
  end
  return era
end

function Civ6Ai_Production._QueueLocalBuild(city, buildId)
  local item, paramKey = Civ6Ai_Production._ResolveBuildItem(buildId)
  if item == nil or paramKey == nil or CityManager == nil or CityOperationTypes == nil then
    return false
  end
  local params = {}
  params[paramKey] = item.Hash
  -- Same form ProductionPanel uses with the panel closed: replace queue slot 0.
  params[CityOperationTypes.PARAM_INSERT_MODE] = CityOperationTypes.VALUE_REPLACE_AT or CityOperationTypes.VALUE_EXCLUSIVE
  if CityOperationTypes.VALUE_REPLACE_AT ~= nil and CityOperationTypes.PARAM_QUEUE_DESTINATION_LOCATION ~= nil then
    params[CityOperationTypes.PARAM_QUEUE_DESTINATION_LOCATION] = 0
  end
  local okField, canStart = pcall(function() return CityManager.CanStartOperation end)
  if okField and type(canStart) == "function" then
    local okCan, can = pcall(canStart, city, CityOperationTypes.BUILD, params)
    if not okCan or can == false then
      return false
    end
  end
  local ok, result = pcall(CityManager.RequestOperation, city, CityOperationTypes.BUILD, params)
  if not ok or result == false then
    return false
  end
  local now = Civ6Ai_Production._GetCityProduction(city)
  if now == buildId then
    return true
  end
  -- Nil (or any non-false) means the request was accepted. The queue updates
  -- on a later tick, so this frame must not log not_stuck or request again.
  return false, "pending", result
end

Civ6Ai_Production._autoTries = Civ6Ai_Production._autoTries or {}
-- Per city: how many picks failed to stick. Each miss moves to the next ranked item.
Civ6Ai_Production._autoMiss = Civ6Ai_Production._autoMiss or {}
Civ6Ai_Production._lastQueued = Civ6Ai_Production._lastQueued or {}
Civ6Ai_Production._pendingQueue = Civ6Ai_Production._pendingQueue or {}
Civ6Ai_Production._queuePass = Civ6Ai_Production._queuePass or 0
Civ6Ai_Production._turnTries = Civ6Ai_Production._turnTries or {}
Civ6Ai_Production._lastReqPass = Civ6Ai_Production._lastReqPass or {}
Civ6Ai_Production._gaveUp = Civ6Ai_Production._gaveUp or {}
Civ6Ai_Production.AUTO_GAP = 1
Civ6Ai_Production.AUTO_TURN_CAP = 6
Civ6Ai_Production._queuePassDepth = Civ6Ai_Production._queuePassDepth or 0

function Civ6Ai_Production.BeginQueuePass()
  -- One pass per watch tick. A pulse inside that watch shares it, so the
  -- same-frame second call does not re-request before the queue can update.
  if (Civ6Ai_Production._queuePassDepth or 0) == 0 then
    Civ6Ai_Production._queuePass = (Civ6Ai_Production._queuePass or 0) + 1
  end
  Civ6Ai_Production._queuePassDepth = (Civ6Ai_Production._queuePassDepth or 0) + 1
end

function Civ6Ai_Production.EndQueuePass()
  local depth = (Civ6Ai_Production._queuePassDepth or 1) - 1
  if depth < 0 then
    depth = 0
  end
  Civ6Ai_Production._queuePassDepth = depth
end

local function _logProduction(line)
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
    Civ6Ai_Util.Log(line)
  end
end

function Civ6Ai_Production.AutoqueueEmptyCities(playerID)
  local ownPass = (Civ6Ai_Production._queuePassDepth or 0) == 0
  if ownPass then
    Civ6Ai_Production.BeginQueuePass()
  end
  local ok, queued = pcall(Civ6Ai_Production._AutoqueuePass, playerID)
  if ownPass then
    Civ6Ai_Production.EndQueuePass()
  end
  if not ok then
    error(queued)
  end
  return queued or 0
end

function Civ6Ai_Production._AutoqueuePass(playerID)
  if Civ6Ai_Config == nil or Civ6Ai_Config.IsAutotest == nil or not Civ6Ai_Config.IsAutotest() then
    return 0
  end
  if Game == nil or Game.GetLocalPlayer == nil or Game.GetLocalPlayer() ~= playerID then
    return 0
  end
  local player = Players[playerID]
  -- Requests sent before the seat's turn is active (turn processing, load) are dropped.
  if player ~= nil and player.IsTurnActive ~= nil then
    local okActive, active = pcall(function() return player:IsTurnActive() end)
    if okActive and active == false then
      return 0
    end
  end
  local cities = player ~= nil and player.GetCities ~= nil and player:GetCities() or nil
  if cities == nil or cities.Members == nil then
    return 0
  end
  local list = {}
  eachMember(cities, function(city)
    table.insert(list, city)
  end)
  table.sort(list, function(a, b)
    return (call(a, "GetID") or 0) < (call(b, "GetID") or 0)
  end)
  local turn = Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or 0
  local builders, military = Civ6Ai_Production._ArmyCounts(playerID)
  local saved = Civ6Ai_Production._SavedLevels(playerID)
  local wars = Civ6Ai_Production._MajorWars(playerID)
  local warlike = Civ6Ai_Production._Warlike(playerID)
  local era = currentEra()
  local unitCounts = {}
  local queued = 0
  local pass = Civ6Ai_Production._queuePass or 0
  local function confirm(cityId, buildId, key)
    Civ6Ai_Production._autoTries[key] = 3
    Civ6Ai_Production._lastQueued[cityId] = buildId
    Civ6Ai_Production._pendingQueue[key] = nil
    if type(buildId) == "string" and string.sub(buildId, 1, 5) == "UNIT_" then
      unitCounts[buildId] = (unitCounts[buildId] or 0) + 1
    end
    _logProduction("production|autoqueue|player=" .. tostring(playerID)
      .. "|city=" .. tostring(cityId) .. "|build=" .. buildId
      .. "|turn=" .. tostring(turn))
  end
  for _, city in ipairs(list) do
    local cityId = call(city, "GetID")
    local key = tostring(playerID) .. ":" .. tostring(cityId) .. ":" .. tostring(turn)
    local current = Civ6Ai_Production._GetCityProduction(city)
    local pending = Civ6Ai_Production._pendingQueue[key]
    if pending ~= nil and pending.pass ~= pass then
      if current == pending.build then
        Civ6Ai_Production._autoMiss[cityId] = 0
        confirm(cityId, pending.build, key)
        queued = queued + 1
      else
        _logProduction("production|autoqueue|not_stuck|city=" .. tostring(city:GetID())
          .. "|wanted=" .. tostring(pending.build) .. "|current=" .. tostring(current)
          .. "|result=" .. tostring(pending.result))
        Civ6Ai_Production._pendingQueue[key] = nil
        Civ6Ai_Production._autoMiss[cityId] = (Civ6Ai_Production._autoMiss[cityId] or 0) + 1
      end
    end
    -- Throttle: at most one request per city per pass, and AUTO_TURN_CAP
    -- requests per city per turn. Per-tick retries flooded the UI and hung the game.
    local tries = Civ6Ai_Production._turnTries[key] or 0
    local lastPass = Civ6Ai_Production._lastReqPass[key]
    local throttled = (lastPass ~= nil and pass - lastPass < Civ6Ai_Production.AUTO_GAP)
      or tries >= Civ6Ai_Production.AUTO_TURN_CAP
    if tries >= Civ6Ai_Production.AUTO_TURN_CAP and not Civ6Ai_Production._gaveUp[key]
        and Civ6Ai_Production._GetCityProduction(city) == nil then
      Civ6Ai_Production._gaveUp[key] = true
      _logProduction("production|autoqueue|gave_up|city=" .. tostring(cityId) .. "|tries=" .. tostring(tries) .. "|turn=" .. tostring(turn))
    end
    if not throttled and Civ6Ai_Production._GetCityProduction(city) == nil and Civ6Ai_Production._pendingQueue[key] == nil then
      Civ6Ai_Production._lastReqPass[key] = pass
      Civ6Ai_Production._turnTries[key] = tries + 1
      -- Hard guarantee: an empty queue is retried on every pass until it sticks.
      -- A pick that did not stick moves to the next ranked item, wrapping round.
      do
        local hasMonument = Civ6Ai_Production._HasBuilding(city, "BUILDING_MONUMENT")
        local hasGranary = Civ6Ai_Production._HasBuilding(city, "BUILDING_GRANARY")
        local speedNum = 200
        pcall(function()
          local row = GameInfo.GameSpeeds[GameConfiguration.GetGameSpeedType()]
          local known = {
            GAMESPEED_ONLINE = 200, GAMESPEED_QUICK = 150, GAMESPEED_STANDARD = 100,
            GAMESPEED_EPIC = 67, GAMESPEED_MARATHON = 33,
          }
          if row ~= nil and known[row.GameSpeedType] ~= nil then
            speedNum = known[row.GameSpeedType]
          end
        end)
        local situation = Civ6Ai_Production.ComposeSituation({
          saved = saved,
          major_wars = wars,
          speed_num = speedNum,
          threatened = Civ6Ai_Production._CityThreatened(playerID, city),
          warlike = warlike,
          cities = #list,
          pop = tonumber(call(city, "GetPopulation")) or 1,
          land = Civ6Ai_Production._OpenLand(city),
          turn = turn,
          era = era,
          builders = builders,
          military = military,
          missing_monument = hasMonument == false,
          missing_granary = hasGranary == false,
          missing_district = Civ6Ai_Production._MissingDistrict(city) == true,
          last = Civ6Ai_Production._lastQueued[cityId],
          unit_counts = unitCounts,
        })
        local ranked = Civ6Ai_Production.RankBuilds(Civ6Ai_Production._Candidates(city), situation)
        if #ranked == 0 then
          _logProduction("production|autoqueue|no_candidates|city=" .. tostring(cityId) .. "|turn=" .. tostring(turn))
        end
        local miss = Civ6Ai_Production._autoMiss[cityId] or 0
        local function skipWalls(buildId)
          if situation.need_expansion ~= true or situation.threatened == true or situation.at_war == true then
            return false
          end
          local name = tostring(buildId or "")
          return string.find(name, "WALL", 1, true) ~= nil
            or string.find(name, "CASTLE", 1, true) ~= nil
            or string.find(name, "STAR_FORT", 1, true) ~= nil
        end
        for step = 0, #ranked - 1 do
          local buildId = ranked[((miss + step) % #ranked) + 1]
          if skipWalls(buildId) then
            buildId = nil
          end
          local stuck, status, result
          if buildId ~= nil then
            stuck, status, result = Civ6Ai_Production._QueueLocalBuild(city, buildId)
          end
          if miss + step > 0 then
            _logProduction("production|autoqueue|retry|city=" .. tostring(cityId) .. "|attempt=" .. tostring(miss + step)
              .. "|build=" .. tostring(buildId) .. "|status=" .. tostring(stuck and "stuck" or status) .. "|turn=" .. tostring(turn))
          end
          if stuck then
            Civ6Ai_Production._autoMiss[cityId] = 0
            confirm(cityId, buildId, key)
            queued = queued + 1
            break
          elseif status == "pending" then
            Civ6Ai_Production._autoMiss[cityId] = miss + step
            local record = { build = buildId, pass = pass }
            if result ~= nil then
              record.result = result
            end
            Civ6Ai_Production._pendingQueue[key] = record
            break
          end
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
