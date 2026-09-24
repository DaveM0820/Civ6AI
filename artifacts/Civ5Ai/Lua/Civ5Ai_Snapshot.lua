-- Civ5Ai snapshot builder (minimal vertical slice).
Civ5Ai_Snapshot = Civ5Ai_Snapshot or {}

Civ5Ai_Snapshot.MAP_EXPORT_RADIUS = 12
Civ5Ai_Snapshot.MAX_MAP_PLOTS = 700
Civ5Ai_Snapshot.SETTLE_SCAN_RADIUS = 3
Civ5Ai_Snapshot.SETTLE_CITY_RADIUS = 3
Civ5Ai_Snapshot.SETTLE_MAX_LOOK = 6
Civ5Ai_Snapshot.SETTLE_MAX_SITES = 3
Civ5Ai_Snapshot.NATIVE_PRODUCTION_MIN_CITIES = 15

function Civ5Ai_Snapshot._CityStrengthDisplay(city)
  if city == nil or city.GetStrengthValue == nil then
    return 0
  end
  local raw = city:GetStrengthValue() or 0
  if raw > 100 then
    return math.floor(raw / 100)
  end
  return raw
end

function Civ5Ai_Snapshot._GameTurn()
  if Game.GetGameTurn then
    return Game.GetGameTurn()
  end
  return 0
end

function Civ5Ai_Snapshot._GameYear()
  local turn = Civ5Ai_Snapshot._GameTurn()
  if Game.GetTurnYear then
    return Game.GetTurnYear(turn)
  end
  if Game.GetGameTurnYear then
    return Game.GetGameTurnYear()
  end
  return 0
end

function Civ5Ai_Snapshot._ClipText(text, maxLen)
  if text == nil then
    return ""
  end
  local value = tostring(text)
  if maxLen == nil or #value <= maxLen then
    return value
  end
  return string.sub(value, 1, maxLen)
end

function Civ5Ai_Snapshot._InfoRows(tableName)
  Civ5Ai_Snapshot._infoCache = Civ5Ai_Snapshot._infoCache or {}
  if Civ5Ai_Snapshot._infoCache[tableName] ~= nil then
    return Civ5Ai_Snapshot._infoCache[tableName]
  end
  local rows = {}
  local info = GameInfo[tableName]
  if info ~= nil then
    for row in info() do
      table.insert(rows, row)
    end
  end
  Civ5Ai_Snapshot._infoCache[tableName] = rows
  return rows
end

function Civ5Ai_Snapshot._MovePointsToTiles(points)
  local denom = 60
  if GameDefines ~= nil and GameDefines.MOVE_DENOMINATOR ~= nil and GameDefines.MOVE_DENOMINATOR > 0 then
    denom = GameDefines.MOVE_DENOMINATOR
  end
  return math.floor((tonumber(points) or 0) / denom)
end

function Civ5Ai_Snapshot._GameInfoTypeName(tableName, index)
  if index == nil or index < 0 then
    return Civ5Ai_Util.JsonNull()
  end
  local info = GameInfo[tableName]
  if info == nil then
    return Civ5Ai_Util.JsonNull()
  end
  local row = info[index]
  if row == nil or row.Type == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return row.Type
end

function Civ5Ai_Snapshot._IsIdeologyBranch(row)
  if row == nil then
    return false
  end
  if row.PurchaseByLevel then
    return true
  end
  return Civ5Ai_Snapshot._IsIdeologyBranchType(row.Type)
end

function Civ5Ai_Snapshot._PlayerHasIdeology(player)
  if player == nil then
    return true
  end
  if player.GetLateGamePolicyTree ~= nil then
    local tree = player:GetLateGamePolicyTree()
    if tree ~= nil and tree ~= -1 then
      return true
    end
  end
  return false
end

function Civ5Ai_Snapshot._PlayerCanChooseIdeology(player)
  if player == nil or player:IsMinorCiv() or player:IsBarbarian() then
    return false
  end
  if Civ5Ai_Snapshot._PlayerHasIdeology(player) then
    return false
  end
  if player.IsTimeToChooseIdeology ~= nil then
    return player:IsTimeToChooseIdeology() == true
  end
  local era = player:GetCurrentEra() or 0
  local prereqEra = -1
  local startEra = 4
  local policiesNeeded = -1
  local branchesNeeded = -1
  if GameDefines ~= nil then
    if GameDefines.IDEOLOGY_PREREQ_ERA ~= nil then
      prereqEra = GameDefines.IDEOLOGY_PREREQ_ERA
    end
    if GameDefines.IDEOLOGY_START_ERA ~= nil then
      startEra = GameDefines.IDEOLOGY_START_ERA
    end
    if GameDefines.IDEOLOGY_UNLOCK_NUM_POLICIES_NEEDED ~= nil then
      policiesNeeded = GameDefines.IDEOLOGY_UNLOCK_NUM_POLICIES_NEEDED
    end
    if GameDefines.IDEOLOGY_UNLOCK_NUM_POLICY_BRANCHES_NEEDED ~= nil then
      branchesNeeded = GameDefines.IDEOLOGY_UNLOCK_NUM_POLICY_BRANCHES_NEEDED
    end
  end
  if prereqEra > -1 and era >= prereqEra then
    if policiesNeeded > -1 and player.GetNumPolicies ~= nil and player:GetNumPolicies(true, true) >= policiesNeeded then
      return true
    end
  end
  if era > startEra then
    return true
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
    local trigger = row.XBuiltTriggersIdeologyChoice
    if trigger ~= nil and trigger > 0 then
      local classId = GameInfoTypes[row.BuildingClass]
      if classId ~= nil and player.GetBuildingClassCount ~= nil and player:GetBuildingClassCount(classId) >= trigger then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Snapshot._UnitWireId(unit)
  if unit == nil then
    return "UNIT_UNKNOWN"
  end
  if type(unit) == "string" then
    return unit
  end
  return "UNIT_" .. tostring(unit:GetID())
end

function Civ5Ai_Snapshot._TryUnit(unit, fn)
  if unit == nil or fn == nil then
    return false, nil
  end
  local ok, result = pcall(fn, unit)
  if not ok then
    return false, nil
  end
  return true, result
end

function Civ5Ai_Snapshot._LiveUnit(playerID, unitId)
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._FindUnit ~= nil then
    return Civ5Ai_Apply._FindUnit(playerID, unitId)
  end
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  for unit in player:Units() do
    if Civ5Ai_Snapshot._UnitWireId(unit) == unitId then
      local ok, alive = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return not u:IsDead()
      end)
      if ok and alive then
        return unit
      end
    end
  end
  return nil
end

function Civ5Ai_Snapshot._CityWireId(city)
  if city == nil then
    return "CITY_UNKNOWN"
  end
  local name = city:GetName()
  if name ~= nil and name ~= "" then
    local slug = string.upper(string.gsub(name, "%s+", "_"))
    slug = string.gsub(slug, "[^A-Z0-9_]", "")
    if slug ~= "" then
      return "CITY_" .. slug
    end
  end
  return "CITY_" .. tostring(city:GetID())
end

function Civ5Ai_Snapshot._TechWireId(techIndex)
  if techIndex == nil or techIndex < 0 then
    return Civ5Ai_Util.JsonNull()
  end
  local row = GameInfo.Technologies[techIndex]
  if row == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return row.Type
end

function Civ5Ai_Snapshot._BuildKnownTechIds(player)
  local ids = {}
  local team = Teams[player:GetTeam()]
  if team == nil then
    return ids
  end
  for row in GameInfo.Technologies() do
    if team:IsHasTech(row.ID) then
      table.insert(ids, row.Type)
    end
  end
  return ids
end

function Civ5Ai_Snapshot._BuildAdoptedPolicies(player)
  local policies = Civ5Ai_Util.JsonArrayList()
  for row in GameInfo.Policies() do
    if player:HasPolicy(row.ID) then
      table.insert(policies, { key = "POLICY", id = row.Type })
    end
  end
  return policies
end

function Civ5Ai_Snapshot._FaithBalance(player)
  if player.GetFaithTimes100 ~= nil then
    return (player:GetFaithTimes100() or 0) / 100
  end
  if player.GetFaith ~= nil then
    return player:GetFaith() or 0
  end
  return 0
end

function Civ5Ai_Snapshot._FaithPerTurn(player)
  if player.GetTotalFaithPerTurnTimes100 ~= nil then
    return math.floor((player:GetTotalFaithPerTurnTimes100() or 0) / 100)
  end
  if player.GetFaithPerTurn ~= nil then
    return player:GetFaithPerTurn() or 0
  end
  return 0
end

function Civ5Ai_Snapshot._ReligionWireId(player)
  if player.GetReligionCreatedByPlayer == nil then
    return Civ5Ai_Util.JsonNull()
  end
  local religionId = player:GetReligionCreatedByPlayer()
  if religionId == nil or religionId < 0 then
    return Civ5Ai_Util.JsonNull()
  end
  local row = GameInfo.Religions[religionId]
  if row == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return row.Type
end

function Civ5Ai_Snapshot._NotificationCategory(summary, detail)
  local text = string.lower(tostring(summary or "") .. " " .. tostring(detail or ""))
  if string.find(text, "nuke", 1, true) or string.find(text, "nuclear", 1, true) then
    return "nuke", "critical"
  end
  if string.find(text, "culture victory", 1, true)
      or string.find(text, "influential on", 1, true)
      or string.find(text, "tourism victory", 1, true) then
    return "culture_victory", "critical"
  end
  if string.find(text, "science victory", 1, true)
      or string.find(text, "spaceship", 1, true)
      or string.find(text, "ss part", 1, true) then
    return "science_victory", "critical"
  end
  if string.find(text, "world leader", 1, true)
      or string.find(text, "diplomatic victory", 1, true) then
    return "diplomatic_victory", "critical"
  end
  if string.find(text, "world congress", 1, true)
      or string.find(text, "league of nations", 1, true) then
    return "world_congress", "warning"
  end
  return "general", "info"
end

function Civ5Ai_Snapshot._BuildNotifications(player)
  local out = Civ5Ai_Util.JsonArrayList()
  if player == nil or player.GetNumNotifications == nil then
    return out
  end
  local count = player:GetNumNotifications()
  if count == nil or count <= 0 then
    return out
  end
  for i = 0, count - 1 do
    if player.GetNotificationDismissed ~= nil and player:GetNotificationDismissed(i) then
      -- skip dismissed log entries
    else
      local summary = nil
      if player.GetNotificationSummaryStr ~= nil then
        summary = player:GetNotificationSummaryStr(i)
      end
      local detail = nil
      if player.GetNotificationStr ~= nil then
        detail = player:GetNotificationStr(i)
      end
      local turn = nil
      if player.GetNotificationTurn ~= nil then
        turn = player:GetNotificationTurn(i)
      end
      if summary ~= nil and summary ~= "" then
        local category, severity = Civ5Ai_Snapshot._NotificationCategory(summary, detail)
        table.insert(out, {
          summary = summary,
          detail = detail or summary,
          turn = turn,
          category = category,
          severity = severity,
        })
      elseif detail ~= nil and detail ~= "" then
        local category, severity = Civ5Ai_Snapshot._NotificationCategory(detail, detail)
        table.insert(out, {
          summary = detail,
          detail = detail,
          turn = turn,
          category = category,
          severity = severity,
        })
      end
    end
  end
  local seen = {}
  local deduped = Civ5Ai_Util.JsonArrayList()
  for _, row in ipairs(out) do
    local key = tostring(row.summary or "") .. "\0" .. tostring(row.detail or "")
    if not seen[key] then
      seen[key] = true
      table.insert(deduped, row)
    end
  end
  local maxNotifications = 32
  while #deduped > maxNotifications do
    table.remove(deduped, 1)
  end
  return deduped
end

function Civ5Ai_Snapshot._BuildReligionState(player, playerID)
  local convertible = Civ5Ai_Util.JsonArrayList()
  if player.GetConvertibleReligions ~= nil then
    local count = player:GetConvertibleReligions()
    for index = 0, count - 1 do
      local religionId = player:GetConvertibleReligion(index)
      if religionId ~= nil and religionId >= 0 then
        local row = GameInfo.Religions[religionId]
        if row ~= nil then
          table.insert(convertible, row.Type)
        end
      end
    end
  end
  local hasPantheon = player.HasCreatedPantheon ~= nil and player:HasCreatedPantheon() == true
  if not hasPantheon
    and playerID ~= nil
    and Civ5Ai_Apply ~= nil
    and Civ5Ai_Apply._pantheonSent ~= nil
    and Civ5Ai_Apply._pantheonSent[playerID] then
    hasPantheon = true
  end
  return {
    state_religion_id = Civ5Ai_Snapshot._ReligionWireId(player),
    conversion_timer = 0,
    convertible_religion_ids = convertible,
    faith = Civ5Ai_Snapshot._FaithBalance(player),
    faith_per_turn = Civ5Ai_Snapshot._FaithPerTurn(player),
    has_pantheon = hasPantheon,
    has_religion = player.HasCreatedReligion ~= nil and player:HasCreatedReligion() == true,
  }
end

function Civ5Ai_Snapshot._BuildUnitCounts(yourUnits)
  local counts = {
    total = 0,
    military = 0,
    settlers = 0,
    workers = 0,
    missionaries = 0,
    spies = 0,
    great_people = 0,
    idle = 0,
    upgradeable = 0,
    naval = 0,
    embarked = 0,
  }
  for _, unit in ipairs(yourUnits) do
    counts.total = counts.total + 1
    if unit.needs_orders == true then
      counts.idle = counts.idle + 1
    end
    if unit.domain_id == "DOMAIN_SEA" then
      counts.naval = counts.naval + 1
    end
    if unit.embarked == true then
      counts.embarked = counts.embarked + 1
    end
    local typeId = unit.unit_type_id or ""
    if string.find(typeId, "SETTLER", 1, true) ~= nil then
      counts.settlers = counts.settlers + 1
    elseif string.find(typeId, "WORKER", 1, true) ~= nil then
      counts.workers = counts.workers + 1
    elseif string.find(typeId, "MISSIONARY", 1, true) ~= nil then
      counts.missionaries = counts.missionaries + 1
    elseif string.find(typeId, "SPY", 1, true) ~= nil then
      counts.spies = counts.spies + 1
    elseif string.find(typeId, "GREAT_", 1, true) ~= nil then
      counts.great_people = counts.great_people + 1
    elseif unit.is_trade_unit == true
        or string.find(typeId, "CARAVAN", 1, true) ~= nil
        or string.find(typeId, "CARGO", 1, true) ~= nil then
      -- trade units are not military
    else
      counts.military = counts.military + 1
    end
  end
  return counts
end

function Civ5Ai_Snapshot._SciencePerTurn(player)
  if player == nil then
    return 0
  end
  if player.GetScienceTimes100 ~= nil then
    return math.floor((player:GetScienceTimes100() or 0) / 100)
  end
  if player.GetYieldRateTimes100 ~= nil and YieldTypes ~= nil then
    return math.floor((player:GetYieldRateTimes100(YieldTypes.YIELD_SCIENCE) or 0) / 100)
  end
  return 0
end

function Civ5Ai_Snapshot._CulturePerTurn(player)
  if player == nil then
    return 0
  end
  if player.GetTotalJONSCulturePerTurnTimes100 ~= nil then
    return math.floor((player:GetTotalJONSCulturePerTurnTimes100() or 0) / 100)
  end
  if player.GetJONCulturePerTurn ~= nil then
    return math.floor(player:GetJONCulturePerTurn() or 0)
  end
  if player.GetCulturePerTurn ~= nil then
    return math.floor(player:GetCulturePerTurn() or 0)
  end
  return 0
end

function Civ5Ai_Snapshot._CultureStored(player)
  if player == nil or player.GetJONSCultureTimes100 == nil then
    return 0
  end
  return math.floor((player:GetJONSCultureTimes100() or 0) / 100)
end

function Civ5Ai_Snapshot._NextPolicyCost(player)
  if player == nil or player.GetNextPolicyCost == nil then
    return 0
  end
  return player:GetNextPolicyCost() or 0
end

function Civ5Ai_Snapshot._FreePolicies(player)
  if player == nil or player.GetNumFreePolicies == nil then
    return 0
  end
  return player:GetNumFreePolicies() or 0
end

function Civ5Ai_Snapshot._UnitActivityId(unit)
  if unit == nil or unit.GetActivityType == nil then
    return "ACTIVITY_AWAKE"
  end
  local actType = unit:GetActivityType()
  if ActivityTypes ~= nil then
    for name, id in pairs(ActivityTypes) do
      if id == actType then
        return name
      end
    end
  end
  return "ACTIVITY_UNKNOWN"
end

function Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
  if unit == nil or unit.MovesLeft == nil then
    return false
  end
  return (unit:MovesLeft() or 0) > 0
end

function Civ5Ai_Snapshot._UnitIsPromotionReady(unit)
  if unit == nil or unit.IsPromotionReady == nil then
    return false
  end
  return unit:IsPromotionReady() == true
end

function Civ5Ai_Snapshot._UnitMissionQueueEmpty(unit)
  if unit == nil then
    return true
  end
  if unit.GetMissionCount ~= nil then
    return (unit:GetMissionCount() or 0) <= 0
  end
  if unit.GetHeadMissionData ~= nil then
    local ok, data = pcall(function() return unit:GetHeadMissionData() end)
    if ok and data ~= nil then
      return false
    end
  end
  return true
end

-- UI-idle: HOLD/AWAKE + moves left + empty mission queue, even if automated/explore flags set.
function Civ5Ai_Snapshot._UnitLooksIdleWithMoves(unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  if not Civ5Ai_Snapshot._UnitHasMovesLeft(unit) then
    return false
  end
  local activity = Civ5Ai_Snapshot._UnitActivityId(unit)
  if activity ~= "ACTIVITY_HOLD" and activity ~= "ACTIVITY_AWAKE" then
    return false
  end
  return Civ5Ai_Snapshot._UnitMissionQueueEmpty(unit)
end

function Civ5Ai_Snapshot._UnitNeedsOrders(unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  -- Workers/warriors (any orderable unit) stuck on HOLD/AWAKE with moves must surface as needing orders
  -- even when automated=true (explore/build flag stale while UI shows unordered).
  if Civ5Ai_Snapshot._UnitLooksIdleWithMoves(unit) then
    return true
  end
  if Civ5Ai_Snapshot._IsTradeUnit(unit) then
    local plot = Map.GetPlot(unit:GetX(), unit:GetY())
    if plot ~= nil then
      local okCan, canRoute = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return u.CanMakeTradeRoute ~= nil and u:CanMakeTradeRoute(plot) == true
      end)
      if okCan and canRoute and Civ5Ai_Snapshot._UnitHasMovesLeft(unit) then
        return true
      end
    end
  end
  if unit.IsAutomated ~= nil and unit:IsAutomated() then
    return false
  end
  if unit:IsReadyToMove() == true then
    return true
  end
  if Civ5Ai_Snapshot._UnitIsPromotionReady(unit) then
    return true
  end
  return Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
end

function Civ5Ai_Snapshot._UnitNeedsLegalCommands(unit)
  if unit == nil or unit:IsDead() then
    return false
  end
  if Civ5Ai_Snapshot._UnitLooksIdleWithMoves(unit) then
    return true
  end
  if unit.IsAutomated ~= nil and unit:IsAutomated() then
    return false
  end
  return Civ5Ai_Snapshot._UnitNeedsOrders(unit) and Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
end

function Civ5Ai_Snapshot._BuildUnitPromotionIds(unit)
  local promotions = Civ5Ai_Util.JsonArrayList()
  if unit == nil or unit.HasPromotion == nil then
    return promotions
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("UnitPromotions")) do
    if unit:HasPromotion(row.ID) then
      table.insert(promotions, row.Type)
    end
  end
  return promotions
end

function Civ5Ai_Snapshot._BuildYourUnits(playerID)
  local player = Players[playerID]
  local units = {}
  if player == nil then
    return units
  end
  for unit in player:Units() do
  if unit ~= nil and not unit:IsDead() then
    local unitType = GameInfo.Units[unit:GetUnitType()]
    local typeId = unitType and unitType.Type or "UNIT_UNKNOWN"
    local plot = Map.GetPlot(unit:GetX(), unit:GetY())
    local plotId = Civ5Ai_Util.PlotId(unit:GetX(), unit:GetY())
    local movesLeft = Civ5Ai_Snapshot._MovePointsToTiles(unit:MovesLeft() or 0)
    local maxMoves = Civ5Ai_Snapshot._MovePointsToTiles(unit:MaxMoves() or 0)
    local classRow = unit.GetUnitClassType ~= nil and GameInfo.UnitClasses[unit:GetUnitClassType()] or nil
    local domainRow = unit.GetDomainType ~= nil and GameInfo.Domains[unit:GetDomainType()] or nil
    local combat = 0
    if unit.GetBaseCombatStrength ~= nil then
      combat = unit:GetBaseCombatStrength() or 0
    end
    local maintenance = 0
    if unit.GetGoldMaintenance ~= nil then
      maintenance = unit:GetGoldMaintenance() or 0
    elseif unit.GetMaintenance ~= nil then
      maintenance = unit:GetMaintenance() or 0
    elseif unitType ~= nil then
      maintenance = unitType.ExtraMaintenanceCost or unitType.GoldMaintenance or 0
    end
    local needsOrders = Civ5Ai_Snapshot._UnitNeedsOrders(unit)
    local strikeRange = 0
    Civ5Ai_Snapshot._TryUnit(unit, function(u)
      if u.Range ~= nil then
        strikeRange = u:Range() or 0
      end
    end)
    local maxHp = unit:GetMaxHitPoints() or 100
    local curHp = unit:GetCurrHitPoints() or maxHp
    local tradeState = Civ5Ai_Snapshot._TradeUnitState(unit)
    table.insert(units, {
      unit_id = Civ5Ai_Snapshot._UnitWireId(unit),
      unit_type_id = typeId,
      plot_id = plotId,
      can_act = unit:IsReadyToMove() == true,
      needs_orders = needsOrders,
      automated = unit.IsAutomated ~= nil and unit:IsAutomated() == true,
      promotion_ready = Civ5Ai_Snapshot._UnitIsPromotionReady(unit),
      range = strikeRange,
      movement = {
        current = movesLeft,
        maximum = maxMoves,
        change_per_turn = 0,
      },
      health = {
        current = curHp,
        maximum = maxHp,
        change_per_turn = 0,
      },
      health_percent = maxHp > 0 and math.floor(100 * curHp / maxHp) or 100,
      embarked = unit.IsEmbarked ~= nil and unit:IsEmbarked() == true,
      mission_queue = Civ5Ai_Util.JsonArrayList(),
      promotion_ids = Civ5Ai_Snapshot._BuildUnitPromotionIds(unit),
      cargo_unit_ids = Civ5Ai_Util.JsonArrayList(),
      upgrade_options = Civ5Ai_Snapshot._BuildUpgradeOptions(unit),
      activity_id = Civ5Ai_Snapshot._UnitActivityId(unit),
      domain_id = domainRow and domainRow.Type or "DOMAIN_LAND",
      experience = unit:GetExperience() or 0,
      level = unit.GetLevel ~= nil and (unit:GetLevel() or 1) or 1,
      strength = { current = combat, maximum = combat, change_per_turn = 0 },
      maintenance = maintenance,
      unit_class_id = classRow and classRow.Type or "UNITCLASS_UNKNOWN",
      unit_ai_role = "UNITAI_UNKNOWN",
      is_trade_unit = tradeState.is_trade_unit,
      trade_route_index = tradeState.trade_route_index,
      trade_needs_route = tradeState.trade_needs_route,
      trade_recalled = tradeState.trade_recalled,
      trade_origin_city_name = tradeState.trade_origin_city_name,
    })
  end
  end
  return units
end

function Civ5Ai_Snapshot._CityProductionItemId(city)
  if city == nil then
    return Civ5Ai_Util.JsonNull()
  end
  local unitId = city.GetProductionUnit and city:GetProductionUnit()
  if unitId ~= nil and unitId >= 0 then
    local row = GameInfo.Units[unitId]
    if row ~= nil then
      return row.Type
    end
  end
  local buildingId = city.GetProductionBuilding and city:GetProductionBuilding()
  if buildingId ~= nil and buildingId >= 0 then
    local row = GameInfo.Buildings[buildingId]
    if row ~= nil then
      return row.Type
    end
  end
  local projectId = city.GetProductionProject and city:GetProductionProject()
  if projectId ~= nil and projectId >= 0 then
    local row = GameInfo.Projects[projectId]
    if row ~= nil then
      return row.Type
    end
  end
  local processId = city.GetProductionProcess and city:GetProductionProcess()
  if processId ~= nil and processId >= 0 then
    local row = GameInfo.Processes[processId]
    if row ~= nil then
      return row.Type
    end
  end
  return Civ5Ai_Util.JsonNull()
end

function Civ5Ai_Snapshot._CityProductionPerTurn(city)
  if city == nil or YieldTypes == nil or city.GetYieldRateTimes100 == nil then
    return 0
  end
  return math.floor((city:GetYieldRateTimes100(YieldTypes.YIELD_PRODUCTION) or 0) / 100)
end

function Civ5Ai_Snapshot._CityBuildings(city)
  local buildings = Civ5Ai_Util.JsonArrayList()
  if city == nil then
    return buildings
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
    local hasBuilding = false
    if city.IsHasBuilding ~= nil then
      hasBuilding = city:IsHasBuilding(row.ID) == true
    elseif city.GetNumBuilding ~= nil then
      hasBuilding = (city:GetNumBuilding(row.ID) or 0) > 0
    end
    if hasBuilding then
      table.insert(buildings, row.Type)
    end
  end
  return buildings
end

function Civ5Ai_Snapshot._CitySpecialists(city)
  local specialists = Civ5Ai_Util.JsonArrayList()
  if city == nil then
    return specialists
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Specialists")) do
    local assigned = 0
    if city.GetSpecialistCount ~= nil then
      assigned = city:GetSpecialistCount(row.ID) or 0
    end
    if assigned > 0 then
      table.insert(specialists, {
        specialist_id = row.Type,
        assigned = assigned,
        free = 0,
        joined = 0,
      })
    end
  end
  return specialists
end

function Civ5Ai_Snapshot._YieldInt(city, yieldType)
  if city == nil or yieldType == nil or city.GetYieldRateTimes100 == nil then
    return 0
  end
  return math.floor((city:GetYieldRateTimes100(yieldType) or 0) / 100)
end

function Civ5Ai_Snapshot._CityReligions(city)
  local religions = Civ5Ai_Util.JsonArrayList()
  if city == nil or city.GetNumFollowers == nil then
    return religions
  end
  local majorityId = city.GetReligiousMajority ~= nil and city:GetReligiousMajority() or -1
  local maxReligions = 8
  if GameDefines ~= nil and GameDefines.MAX_RELIGIONS ~= nil then
    maxReligions = GameDefines.MAX_RELIGIONS
  end
  for religionIndex = 0, maxReligions - 1 do
    local followers = city:GetNumFollowers(religionIndex) or 0
    if followers > 0 then
      local row = GameInfo.Religions ~= nil and GameInfo.Religions[religionIndex] or nil
      table.insert(religions, {
        religion_id = row and row.Type or ("RELIGION_" .. tostring(religionIndex)),
        followers = followers,
        majority = religionIndex == majorityId,
      })
    end
  end
  return religions
end

function Civ5Ai_Snapshot._ScienceVictoryParts(team)
  local built = 0
  local total = 0
  if team == nil or team.GetProjectCount == nil or GameInfo.Projects == nil then
    return built, total
  end
  for row in GameInfo.Projects() do
    if row.Type ~= nil and string.find(row.Type, "PROJECT_SS_", 1, true) == 1 then
      total = total + 1
      if team:GetProjectCount(row.ID) > 0 then
        built = built + 1
      end
    end
  end
  return built, total
end

function Civ5Ai_Snapshot._BuildVictoryAlerts(playerID)
  local alerts = Civ5Ai_Util.JsonArrayList()
  local player = Players[playerID]
  if player == nil then
    return alerts
  end
  local activeTeam = Teams[player:GetTeam()]
  if activeTeam == nil then
    return alerts
  end
  for otherID = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local other = Players[otherID]
    if other ~= nil and other:IsAlive() and not other:IsMinorCiv() and otherID ~= playerID then
      if activeTeam:IsHasMet(other:GetTeam()) then
        local playerWireId = Civ5Ai_Util.PlayerId(otherID)
        local leaderName = Civ5Ai_Snapshot._LeaderDisplayName(
          other,
          GameInfo.Leaders[other:GetLeaderType()]
        )
        if other.GetNumCivsInfluentialOn ~= nil and other.GetNumCivsToBeInfluentialOn ~= nil then
          local influential = other:GetNumCivsInfluentialOn() or 0
          local needed = other:GetNumCivsToBeInfluentialOn() or 0
          if needed > 0 and influential >= math.max(1, needed - 1) then
            table.insert(alerts, {
              kind = "VICTORY_CULTURE",
              severity = influential >= needed and "critical" or "warning",
              affected_ids = { playerWireId },
              text = leaderName
                .. " is "
                .. tostring(influential)
                .. "/"
                .. tostring(needed)
                .. " toward cultural victory",
            })
          end
        end
        local otherTeam = Teams[other:GetTeam()]
        local built, total = Civ5Ai_Snapshot._ScienceVictoryParts(otherTeam)
        if total > 0 and built >= math.max(2, total - 1) then
          table.insert(alerts, {
            kind = "VICTORY_SCIENCE",
            severity = built >= total and "critical" or "warning",
            affected_ids = { playerWireId },
            text = leaderName
              .. " has built "
              .. tostring(built)
              .. "/"
              .. tostring(total)
              .. " spaceship parts",
          })
        end
      end
    end
  end
  -- GetVotesNeededForDiploVictory() returns the win threshold even before the World
  -- Congress exists; only surface this alert once the UN is actually active.
  if Game.GetVotesNeededForDiploVictory ~= nil
      and Game.IsUnitedNationsActive ~= nil
      and Game.IsUnitedNationsActive() then
    local votesNeeded = Game.GetVotesNeededForDiploVictory()
    if votesNeeded ~= nil and votesNeeded > 0 and votesNeeded <= 30 then
      table.insert(alerts, {
        kind = "VICTORY_DIPLOMATIC",
        severity = votesNeeded <= 10 and "critical" or "warning",
        affected_ids = Civ5Ai_Util.JsonArrayList(),
        text = "Diplomatic victory may be decided soon ("
          .. tostring(votesNeeded)
          .. " votes needed for World Leader)",
      })
    end
  end
  return alerts
end

function Civ5Ai_Snapshot._BuildWorldCongress(playerID)
  if Civ5Ai_Congress ~= nil and Civ5Ai_Congress.BuildBlock ~= nil then
    return Civ5Ai_Congress.BuildBlock(playerID)
  end
  return { available = false }
end


function Civ5Ai_Snapshot._ResourceIsLuxOrStrategic(resourceId)
  if resourceId == nil or resourceId == "" then
    return false
  end
  local info = GameInfo.Resources
  if info == nil then
    return false
  end
  local row = info[resourceId]
  if row == nil then
    return false
  end
  local usage = row.ResourceUsage
  if usage == 1 or usage == 2 then
    return true
  end
  local class = row.ResourceClassType
  if class == "RESOURCECLASS_LUXURY" then
    return true
  end
  if class == "RESOURCECLASS_RUSH" or class == "RESOURCECLASS_MODERN" then
    return true
  end
  return false
end

function Civ5Ai_Snapshot._CityTileImprovementStats(city, playerID)
  local improved = 0
  local improvable = 0
  local unimproved = Civ5Ai_Util.JsonArrayList()
  if city == nil or playerID == nil then
    return { improved = 0, improvable = 0, unimproved_lux_strat = unimproved }
  end
  if city.GetNumCityPlots == nil or city.GetCityIndexPlot == nil then
    return { improved = 0, improvable = 0, unimproved_lux_strat = unimproved }
  end
  local n = city:GetNumCityPlots() or 0
  for i = 0, n - 1 do
    local plot = city:GetCityIndexPlot(i)
    if plot ~= nil then
      local isCity = plot.IsCity ~= nil and plot:IsCity() == true
      if not isCity then
        local owner = plot.GetOwner ~= nil and plot:GetOwner() or -1
        if owner == playerID then
          local peak = (plot.IsMountain ~= nil and plot:IsMountain() == true)
            or (plot.IsImpassable ~= nil and plot:IsImpassable() == true)
          local ocean = false
          if plot.IsWater ~= nil and plot:IsWater() == true then
            local terrain = Civ5Ai_Snapshot._TerrainTypeName(plot)
            if terrain == "TERRAIN_OCEAN" then
              ocean = true
            end
          end
          local resourceId = Civ5Ai_Snapshot._ResourceTypeName(plot)
          local hasResource = type(resourceId) == "string" and resourceId ~= ""
          if not peak and (not ocean or hasResource) then
            improvable = improvable + 1
            local impName = Civ5Ai_Snapshot._ImprovementTypeName(plot)
            local hasImp = type(impName) == "string"
              and impName ~= ""
              and impName ~= "IMPROVEMENT_GOODY_HUT"
            if hasImp then
              improved = improved + 1
            elseif hasResource and Civ5Ai_Snapshot._ResourceIsLuxOrStrategic(resourceId) then
              table.insert(unimproved, {
                resource_id = resourceId,
                plot_id = Civ5Ai_Util.PlotId(plot:GetX(), plot:GetY()),
                x = plot:GetX(),
                y = plot:GetY(),
              })
            end
          end
        end
      end
    end
  end
  return {
    improved = improved,
    improvable = improvable,
    unimproved_lux_strat = unimproved,
  }
end

function Civ5Ai_Snapshot._ItemProductionCost(city, buildId)
  if city == nil or buildId == nil or buildId == "" then
    return 0
  end
  if GameInfo == nil then
    return 0
  end
  local unitRow = GameInfo.Units ~= nil and GameInfo.Units[buildId] or nil
  if unitRow ~= nil and unitRow.ID ~= nil then
    if city.GetUnitProductionNeeded ~= nil then
      return city:GetUnitProductionNeeded(unitRow.ID) or 0
    end
    return unitRow.Cost or 0
  end
  local buildingRow = GameInfo.Buildings ~= nil and GameInfo.Buildings[buildId] or nil
  if buildingRow ~= nil and buildingRow.ID ~= nil then
    if city.GetBuildingProductionNeeded ~= nil then
      return city:GetBuildingProductionNeeded(buildingRow.ID) or 0
    end
    return buildingRow.Cost or 0
  end
  local projectRow = GameInfo.Projects ~= nil and GameInfo.Projects[buildId] or nil
  if projectRow ~= nil then
    return projectRow.Cost or 0
  end
  return 0
end

function Civ5Ai_Snapshot._BuildYourCities(playerID)
  local player = Players[playerID]
  local cities = {}
  if player == nil then
    return cities
  end
  for city in player:Cities() do
    if city ~= nil then
      local cityId = Civ5Ai_Snapshot._CityWireId(city)
      local productionItem = Civ5Ai_Snapshot._CityProductionItemId(city)
      local foodNow = city.GetFood ~= nil and (city:GetFood() or 0) or 0
      local foodMax = city.GrowthThreshold ~= nil and (city:GrowthThreshold() or 0) or 0
      local cultureNow = 0
      if city.GetJONSCultureStored ~= nil then
        cultureNow = city:GetJONSCultureStored() or 0
      end
      local bombardDamage = 0
      if city.GetDamage ~= nil then
        bombardDamage = city:GetDamage() or 0
      end
      table.insert(cities, {
        city_id = cityId,
        name = city:GetName() or cityId,
        plot_id = Civ5Ai_Util.PlotId(city:GetX(), city:GetY()),
        population = city:GetPopulation() or 1,
        is_capital = city:IsCapital() == true,
        is_coastal = city:IsCoastal(25) == true,
        area_id = "AREA_" .. tostring(city.GetArea ~= nil and city:GetArea() or 0),
        automation = { citizens = false, production = true },
        buildings = Civ5Ai_Snapshot._CityBuildings(city),
        commerce = {
          culture = { percent = 0, rate = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_CULTURE) },
          espionage = { percent = 0, rate = 0 },
          gold = { percent = 0, rate = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_GOLD) },
          research = { percent = 0, rate = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_SCIENCE) },
        },
        corporations = Civ5Ai_Util.JsonArrayList(),
        culture = { current = cultureNow, maximum = 0, change_per_turn = 0 },
        defense = { bombard_damage = bombardDamage, percent = Civ5Ai_Snapshot._CityStrengthDisplay(city) },
        -- BNW city max HP is 200; expose percent so wire can mirror unit .hp rules.
        health_percent = math.floor(100 * math.max(0, 200 - bombardDamage) / 200),
        food = { current = foodNow, maximum = foodMax, change_per_turn = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_FOOD) },
        garrison_unit_ids = Civ5Ai_Util.JsonArrayList(),
        great_people = { current = 0, maximum = 0, change_per_turn = 0 },
        happiness = { negative = 0, net = 0, positive = 0 },
        health = { negative = 0, net = 0, positive = 0 },
        maintenance = city.GetMaintenance ~= nil and (city:GetMaintenance() or 0) or 0,
        occupation_turns = city.GetOccupationTimer ~= nil and (city:GetOccupationTimer() or 0) or 0,
        is_puppet = city.IsPuppet ~= nil and city:IsPuppet() == true,
        needs_capture_choice = Civ5Ai_Snapshot._CityNeedsCaptureChoice(playerID, city),
        production = {
          item_id = productionItem,
          progress = city:GetProduction() or 0,
          cost = city:GetProductionNeeded() or 0,
          production_per_turn = Civ5Ai_Snapshot._CityProductionPerTurn(city),
          estimated_turns_remaining = Civ5Ai_Util.JsonNull(),
        },
        production_queue = Civ5Ai_Util.JsonArrayList(),
        religions = Civ5Ai_Snapshot._CityReligions(city),
        specialists = Civ5Ai_Snapshot._CitySpecialists(city),
        trade_routes = Civ5Ai_Util.JsonArrayList(),
        worked_plot_ids = Civ5Ai_Util.JsonArrayList(),
        yields = {
          commerce = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_GOLD),
          food = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_FOOD),
          production = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_PRODUCTION),
          science = Civ5Ai_Snapshot._YieldInt(city, YieldTypes and YieldTypes.YIELD_SCIENCE),
        },
        connected = (city:IsCapital() == true)
          or (city.IsRouteToCapitalConnected ~= nil and city:IsRouteToCapitalConnected() == true)
          or (city.IsConnectedToCapital ~= nil and city:IsConnectedToCapital() == true),
        tile_improvements = Civ5Ai_Snapshot._CityTileImprovementStats(city, playerID),
      })
    end
  end
  return cities
end

function Civ5Ai_Snapshot._BuildEmpireResources(player)
  local resources = Civ5Ai_Util.JsonArrayList()
  if player == nil or player.GetNumResourceTotal == nil then
    return resources
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Resources")) do
    local total = player:GetNumResourceTotal(row.ID, false) or 0
    if total ~= 0 then
      table.insert(resources, {
        resource_id = row.Type,
        available = math.max(0, total),
        surplus = total,
        imported = 0,
        exported = 0,
      })
    end
  end
  return resources
end

function Civ5Ai_Snapshot._PlayerGoldTimes100(player, methodName)
  if player == nil or player[methodName] == nil then
    return 0
  end
  local value = player[methodName](player)
  if value == nil then
    return 0
  end
  return math.floor(value / 100)
end

function Civ5Ai_Snapshot._PlayerGoldRate(player, methodName)
  if player == nil or player[methodName] == nil then
    return 0
  end
  local value = player[methodName](player)
  if value == nil then
    return 0
  end
  return math.floor(value)
end

function Civ5Ai_Snapshot._UnhappinessInt(player, methodName)
  if player == nil or player[methodName] == nil then
    return 0
  end
  return math.floor((player[methodName](player) or 0) / 100)
end

function Civ5Ai_Snapshot._BuildEmpireCosts(player)
  local unitCost = 0
  if player.CalculateUnitCost ~= nil then
    unitCost = player:CalculateUnitCost() or 0
  end
  local buildingMaint = 0
  if player.GetBuildingGoldMaintenance ~= nil then
    buildingMaint = player:GetBuildingGoldMaintenance() or 0
  end
  local improvementMaint = 0
  if player.GetImprovementGoldMaintenance ~= nil then
    improvementMaint = player:GetImprovementGoldMaintenance() or 0
  end
  local civicUpkeep = 0
  if player.GetPolicyCostPerTurn ~= nil then
    civicUpkeep = player:GetPolicyCostPerTurn() or 0
  end
  local cityMaintenance = buildingMaint + improvementMaint
  local inflation = 0
  if player.CalculateInflatedCosts ~= nil then
    local total = player:CalculateInflatedCosts() or 0
    inflation = math.max(0, total - unitCost - cityMaintenance - civicUpkeep)
  end
  return {
    unit_cost = unitCost,
    city_maintenance = cityMaintenance,
    civic_upkeep = civicUpkeep,
    inflation = inflation,
    unit_supply = 0,
  }
end

function Civ5Ai_Snapshot._BuildGoldRevenue(player)
  local cities = Civ5Ai_Snapshot._PlayerGoldTimes100(player, "GetGoldFromCitiesMinusTradeRoutesTimes100")
  local cityGoldTotal = Civ5Ai_Snapshot._PlayerGoldTimes100(player, "GetGoldFromCitiesTimes100")
  local tradeRoutes = math.max(0, cityGoldTotal - cities)
  local connections = Civ5Ai_Snapshot._PlayerGoldTimes100(player, "GetCityConnectionGoldTimes100")
  local diplomacy = Civ5Ai_Snapshot._PlayerGoldRate(player, "GetGoldPerTurnFromDiplomacy")
  if diplomacy < 0 then
    diplomacy = 0
  end
  return {
    cities = cities,
    trade = connections + tradeRoutes,
    diplomacy = diplomacy,
    religion = Civ5Ai_Snapshot._PlayerGoldRate(player, "GetGoldPerTurnFromReligion"),
    traits = Civ5Ai_Snapshot._PlayerGoldRate(player, "GetGoldPerTurnFromTraits"),
  }
end

function Civ5Ai_Snapshot._BuildHappinessDetail(player)
  -- UI net excess = GetExcessHappiness() = GetHappiness() - GetUnhappiness().
  -- Store both totals so Python can recover excess from pre-reload snapshots.
  local happyTotal = 0
  if player.GetHappiness ~= nil then
    happyTotal = player:GetHappiness() or 0
  end
  local unhappyTotal = 0
  if player.GetUnhappiness ~= nil then
    unhappyTotal = player:GetUnhappiness() or 0
  end
  local net = happyTotal - unhappyTotal
  if player.GetExcessHappiness ~= nil then
    net = player:GetExcessHappiness() or net
  end
  local unhappyBuildings = Civ5Ai_Snapshot._UnhappinessInt(player, "GetUnhappinessFromCityBuildings")
  if unhappyBuildings == 0 and player.GetUnhappinessFromBuildings ~= nil then
    unhappyBuildings = player:GetUnhappinessFromBuildings() or 0
  end
  local otherHappy = 0
  if player.GetHappinessFromNaturalWonders ~= nil then
    otherHappy = otherHappy + (player:GetHappinessFromNaturalWonders() or 0)
  end
  if player.GetHappinessFromTradeRoutes ~= nil then
    otherHappy = otherHappy + (player:GetHappinessFromTradeRoutes() or 0)
  end
  if player.GetHappinessFromMinorCivs ~= nil then
    otherHappy = otherHappy + (player:GetHappinessFromMinorCivs() or 0)
  end
  if player.GetHappinessFromLeagues ~= nil then
    otherHappy = otherHappy + (player:GetHappinessFromLeagues() or 0)
  end
  return {
    net = net,
    happy_total = happyTotal,
    unhappy_total = unhappyTotal,
    unhappy = {
      units = Civ5Ai_Snapshot._UnhappinessInt(player, "GetUnhappinessFromUnits"),
      cities = Civ5Ai_Snapshot._UnhappinessInt(player, "GetUnhappinessFromCityCount"),
      population = Civ5Ai_Snapshot._UnhappinessInt(player, "GetUnhappinessFromCityPopulation"),
      occupied = Civ5Ai_Snapshot._UnhappinessInt(player, "GetUnhappinessFromOccupiedCities"),
      buildings = unhappyBuildings,
    },
    happy = {
      luxuries = player.GetHappinessFromResources ~= nil and (player:GetHappinessFromResources() or 0) or 0,
      buildings = player.GetHappinessFromBuildings ~= nil and (player:GetHappinessFromBuildings() or 0) or 0,
      cities = player.GetHappinessFromCities ~= nil and (player:GetHappinessFromCities() or 0) or 0,
      policies = player.GetHappinessFromPolicies ~= nil and (player:GetHappinessFromPolicies() or 0) or 0,
      religion = player.GetHappinessFromReligion ~= nil and (player:GetHappinessFromReligion() or 0) or 0,
      other = otherHappy,
    },
  }
end

function Civ5Ai_Snapshot._AtWarWithOtherMajor(playerID, otherID)
  local other = Players[otherID]
  if other == nil or not other:IsAlive() then
    return false
  end
  local theirTeam = other:GetTeam()
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for rivalID = 0, lastMajor do
    if rivalID ~= playerID and rivalID ~= otherID then
      local rival = Players[rivalID]
      if rival ~= nil and rival:IsAlive() and not rival:IsMinorCiv() and not rival:IsBarbarian() then
        if Teams[theirTeam] ~= nil and Teams[theirTeam]:IsAtWar(rival:GetTeam()) then
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_Snapshot._BuildYourEmpire(playerID, player, yourUnits)
  local techId = Civ5Ai_Snapshot._TechWireId(player:GetCurrentResearch())
  local knownTechIds = Civ5Ai_Snapshot._BuildKnownTechIds(player)
  local adoptedPolicies = Civ5Ai_Snapshot._BuildAdoptedPolicies(player)
  local religion = Civ5Ai_Snapshot._BuildReligionState(player, playerID)
  local researchProgress = 0
  local researchCost = 0
  local researchPerTurn = Civ5Ai_Snapshot._SciencePerTurn(player)
  local cultureRate = Civ5Ai_Snapshot._CulturePerTurn(player)
  local cultureStored = Civ5Ai_Snapshot._CultureStored(player)
  local nextPolicyCost = Civ5Ai_Snapshot._NextPolicyCost(player)
  local freePolicies = Civ5Ai_Snapshot._FreePolicies(player)
  local currentTech = player:GetCurrentResearch()
  if currentTech ~= nil and currentTech >= 0 then
    researchProgress = player:GetResearchProgress(currentTech) or 0
    researchCost = player:GetResearchCost(currentTech) or 0
  end
  return {
    gold = player:GetGold() or 0,
    gold_per_turn = player:CalculateGoldRate() or 0,
    anarchy_turns = player.GetAnarchyNumTurns ~= nil and (player:GetAnarchyNumTurns() or 0) or 0,
    golden_age_turns = player.GetGoldenAgeTurns ~= nil and (player:GetGoldenAgeTurns() or 0) or 0,
    war_weariness = 0,
    score = player:GetScore() or 0,
    team_id = "TEAM_" .. tostring(player:GetTeam()),
    civics = adoptedPolicies,
    resources = Civ5Ai_Snapshot._BuildEmpireResources(player),
    victory_progress = Civ5Ai_Util.JsonArrayList(),
    commerce = {
      culture = {
        percent = 0,
        rate = cultureRate,
        stored = cultureStored,
        next_policy_cost = nextPolicyCost,
        free_policies = freePolicies,
      },
      espionage = { percent = 0, rate = 0 },
      gold = { percent = 0, rate = player:CalculateGoldRate() or 0 },
      research = { percent = 100, rate = researchPerTurn },
    },
    costs = Civ5Ai_Snapshot._BuildEmpireCosts(player),
    gold_revenue = Civ5Ai_Snapshot._BuildGoldRevenue(player),
    happiness_detail = Civ5Ai_Snapshot._BuildHappinessDetail(player),
    religion = religion,
    research = {
      tech_id = techId,
      progress = researchProgress,
      cost = researchCost,
      research_per_turn = researchPerTurn,
      estimated_turns_remaining = Civ5Ai_Util.JsonNull(),
      queue = Civ5Ai_Util.JsonArrayList(),
      known_tech_ids = knownTechIds,
    },
    unit_counts = Civ5Ai_Snapshot._BuildUnitCounts(yourUnits or {}),
    can_train_settlers = Civ5Ai_Snapshot._PlayerCanTrainSettler(player),
  }
end

function Civ5Ai_Snapshot._PlayerCanTrainSettler(player)
  if player == nil or GameInfo == nil or GameInfo.Units == nil then
    return true
  end
  local row = GameInfo.Units["UNIT_SETTLER"]
  if row == nil or row.ID == nil or player.CanTrain == nil then
    return true
  end
  -- Player-level CanTrain is the civ/UA gate (Venice). City CanTrain also
  -- fails for pop-1 capitals and is not a civilization lock.
  return player:CanTrain(row.ID, false, true, true, false) == true
end

function Civ5Ai_Snapshot._ResearchChoiceDue(player)
  if player == nil or player.GetCurrentResearch == nil then
    return true
  end
  local current = player:GetCurrentResearch()
  if current == nil or current < 0 then
    return true
  end
  local progress = 0
  local cost = 0
  if player.GetResearchProgress ~= nil then
    progress = player:GetResearchProgress(current) or 0
  end
  if player.GetResearchCost ~= nil then
    cost = player:GetResearchCost(current) or 0
  end
  if cost > 0 and progress >= cost then
    return true
  end
  return false
end

function Civ5Ai_Snapshot._PolicyChoiceDue(player)
  if player == nil then
    return false
  end
  if Civ5Ai_Snapshot._FreePolicies(player) > 0 then
    return true
  end
  local stored = Civ5Ai_Snapshot._CultureStored(player)
  local cost = Civ5Ai_Snapshot._NextPolicyCost(player)
  if cost > 0 and stored >= cost then
    return true
  end
  return false
end

function Civ5Ai_Snapshot._BuildLegalResearch(playerID, player)
  local commands = {}
  if not Civ5Ai_Snapshot._ResearchChoiceDue(player) then
    return commands
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Technologies")) do
    if player:CanResearch(row.ID) then
      local techId = row.Type
      table.insert(commands, {
        kind = "set_research_tech",
        command_id = "CMD_research_" .. techId,
        description = "Research " .. techId,
        fixed_arguments = { tech_id = techId },
        affected_ids = { techId },
        parameter_domains = {},
        runtime_status = "tested",
      })
    end
  end
  return commands
end

function Civ5Ai_Snapshot._AppendQueueProduction(commands, cityId, buildId, productionCost)
  table.insert(commands, {
    kind = "queue_production",
    command_id = "CMD_prod_" .. cityId .. "_" .. buildId,
    description = "Queue " .. buildId .. " in " .. cityId,
    fixed_arguments = {
      city_id = cityId,
      build_id = buildId,
      production_cost = productionCost or 0,
    },
    affected_ids = { cityId },
    parameter_domains = {},
    runtime_status = "tested",
  })
end

-- Same catalog the production popup builds: CanConstruct / CanTrain / CanCreate / CanMaintain.
function Civ5Ai_Snapshot._AppendCityProductionCatalog(commands, city, cityId)
  if city == nil then
    return
  end
  if city.CanConstruct ~= nil then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
      if row ~= nil and row.Type ~= nil and row.ID ~= nil and city:CanConstruct(row.ID, 0, 0) then
        Civ5Ai_Snapshot._AppendQueueProduction(
          commands, cityId, row.Type, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
      end
    end
  end
  if city.CanTrain ~= nil then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Units")) do
      if row ~= nil and row.Type ~= nil and row.ID ~= nil and city:CanTrain(row.ID, 0, 0) then
        Civ5Ai_Snapshot._AppendQueueProduction(
          commands, cityId, row.Type, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
      end
    end
  end
  if city.CanCreate ~= nil then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Projects")) do
      if row ~= nil and row.Type ~= nil and row.ID ~= nil and city:CanCreate(row.ID, 0, 0) then
        Civ5Ai_Snapshot._AppendQueueProduction(
          commands, cityId, row.Type, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
      end
    end
  end
  if city.CanMaintain ~= nil then
    for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Processes")) do
      if row ~= nil and row.Type ~= nil and row.ID ~= nil and city:CanMaintain(row.ID) then
        Civ5Ai_Snapshot._AppendQueueProduction(commands, cityId, row.Type, 0)
      end
    end
  end
end

function Civ5Ai_Snapshot._UnitLeftoverController(playerID)
  if Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._IsLocalHumanSeat ~= nil
      and Civ5Ai_Apply._IsLocalHumanSeat(playerID) then
    return "skip_leftover"
  end
  return "native"
end

function Civ5Ai_Snapshot._FallbackPolicy(playerID, player)
  if Civ5Ai_Snapshot._UnitLeftoverController(playerID) == "skip_leftover" then
    return "After apply, leftover units waiting for orders are skipped so the turn can end. Empty-city production stays empty until you set it."
  end
  if Civ5Ai_Seats == nil or not Civ5Ai_Seats.UsesCpLimitedFallback(playerID) then
    return "Community Patch AI moves unmoved units after LLM apply."
  end
  local n = 0
  if player ~= nil and player.GetNumCities ~= nil then
    n = player:GetNumCities() or 0
  end
  if n >= Civ5Ai_Snapshot.NATIVE_PRODUCTION_MIN_CITIES then
    return "Community Patch moves unordered units and fills empty-city production after LLM apply; research, policies, and other strategy stay LLM-only."
  end
  return "Community Patch moves unordered units after LLM apply; empty-city production stays empty until you set it. Research, policies, and other strategy stay LLM-only."
end

function Civ5Ai_Snapshot._AppendFaithPurchase(commands, cityId, buildId, faithCost, productionCost)
  table.insert(commands, {
    kind = "buy_with_faith",
    command_id = "CMD_buy_faith_" .. cityId .. "_" .. buildId,
    description = "Buy " .. buildId .. " in " .. cityId .. " for " .. tostring(faithCost) .. " faith",
    fixed_arguments = {
      city_id = cityId,
      build_id = buildId,
      faith_cost = faithCost,
      production_cost = productionCost or 0,
    },
    affected_ids = { cityId },
    parameter_domains = {},
    runtime_status = "tested",
  })
end

function Civ5Ai_Snapshot._FaithPurchaseCost(city, row, isUnit)
  if city == nil or row == nil then
    return 0
  end
  if isUnit and city.GetUnitFaithPurchaseCost ~= nil then
    return city:GetUnitFaithPurchaseCost(row.ID) or 0
  end
  if not isUnit and city.GetBuildingFaithPurchaseCost ~= nil then
    return city:GetBuildingFaithPurchaseCost(row.ID) or 0
  end
  if city.GetFaithPurchaseCost ~= nil then
    return city:GetFaithPurchaseCost(row.ID, isUnit and -1 or row.ID) or 0
  end
  return 0
end

function Civ5Ai_Snapshot._BuildLegalFaithPurchases(playerID, player)
  local commands = {}
  if player == nil or player.Cities == nil or YieldTypes == nil then
    return commands
  end
  local faithUnits = {
    "UNIT_MISSIONARY", "UNIT_INQUISITOR", "UNIT_GREAT_PROPHET",
    "UNIT_GREAT_GENERAL", "UNIT_GREAT_ADMIRAL", "UNIT_SCIENTIST",
    "UNIT_ENGINEER", "UNIT_MERCHANT", "UNIT_ARTIST", "UNIT_WRITER",
    "UNIT_MUSICIAN",
  }
  local maxPerCity = 12
  for city in player:Cities() do
    if city ~= nil then
      local cityId = Civ5Ai_Snapshot._CityWireId(city)
      local count = 0
      for _, unitType in ipairs(faithUnits) do
        if count >= maxPerCity then
          break
        end
        local row = GameInfo.Units ~= nil and GameInfo.Units[unitType] or nil
        if row ~= nil
            and city.IsCanPurchase ~= nil
            and city:IsCanPurchase(false, false, row.ID, -1, -1, YieldTypes.YIELD_FAITH) then
          local cost = Civ5Ai_Snapshot._FaithPurchaseCost(city, row, true)
          if cost > 0 then
            Civ5Ai_Snapshot._AppendFaithPurchase(
              commands, cityId, row.Type, cost, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
            count = count + 1
          end
        end
      end
      for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
        if count >= maxPerCity then
          break
        end
        if row ~= nil and row.Type ~= nil and row.ID ~= nil
            and city.IsCanPurchase ~= nil
            and city:IsCanPurchase(false, false, -1, row.ID, -1, YieldTypes.YIELD_FAITH) then
          local cost = Civ5Ai_Snapshot._FaithPurchaseCost(city, row, false)
          if cost > 0 then
            Civ5Ai_Snapshot._AppendFaithPurchase(
              commands, cityId, row.Type, cost, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
            count = count + 1
          end
        end
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalFreeGreatPerson(playerID, player)
  local commands = {}
  if player == nil or player.GetNumFreeGreatPeople == nil or (player:GetNumFreeGreatPeople() or 0) <= 0 then
    return commands
  end
  for row in GameInfo.Units() do
    if row.Special == "SPECIALUNIT_PEOPLE" then
      if player.CanTrain ~= nil and player:CanTrain(row.ID, true, true, true, false) then
        local unitTypeId = row.Type
        table.insert(commands, {
          kind = "choose_free_great_person",
          command_id = "CMD_freegp_" .. unitTypeId,
          description = "Free Great Person " .. unitTypeId,
          fixed_arguments = { unit_type_id = unitTypeId },
          affected_ids = { unitTypeId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._AppendGoldPurchase(commands, cityId, buildId, goldCost, productionCost)
  table.insert(commands, {
    kind = "buy_with_gold",
    command_id = "CMD_buy_gold_" .. cityId .. "_" .. buildId,
    description = "Buy " .. buildId .. " in " .. cityId .. " for " .. tostring(goldCost) .. " gold",
    fixed_arguments = {
      city_id = cityId,
      build_id = buildId,
      gold_cost = goldCost,
      production_cost = productionCost or 0,
    },
    affected_ids = { cityId },
    parameter_domains = {},
    runtime_status = "tested",
  })
end

function Civ5Ai_Snapshot._PlayerAtWar(playerID)
  if playerID == nil or Teams == nil or Players == nil then
    return false
  end
  local player = Players[playerID]
  if player == nil then
    return false
  end
  local team = Teams[player:GetTeam()]
  if team == nil then
    return false
  end
  for otherID = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    if otherID ~= playerID and Civ5Ai_Snapshot._PlayerAtWarWith(playerID, otherID) then
      return true
    end
  end
  return false
end

function Civ5Ai_Snapshot._BuildLegalGoldPurchases(playerID, player)
  local commands = {}
  if player == nil or player.Cities == nil or YieldTypes == nil then
    return commands
  end
  local atWar = Civ5Ai_Snapshot._PlayerAtWar(playerID)
  local shortUnits = atWar
    and { "UNIT_WARRIOR", "UNIT_ARCHER", "UNIT_SPEARMAN", "UNIT_HORSEMAN", "UNIT_CATAPULT", "UNIT_SWORDSMAN" }
    or { "UNIT_WORKER", "UNIT_SETTLER", "UNIT_WARRIOR", "UNIT_ARCHER", "UNIT_SCOUT" }
  local maxPerCity = 10
  for city in player:Cities() do
    if city ~= nil then
      local cityId = Civ5Ai_Snapshot._CityWireId(city)
      local count = 0
      for _, unitType in ipairs(shortUnits) do
        if count >= maxPerCity then
          break
        end
        local row = GameInfo.Units ~= nil and GameInfo.Units[unitType] or nil
        if row ~= nil
            and city.IsCanPurchase ~= nil
            and city:IsCanPurchase(false, false, row.ID, -1, -1, YieldTypes.YIELD_GOLD) then
          local cost = city.GetUnitPurchaseCost ~= nil and (city:GetUnitPurchaseCost(row.ID) or 0) or 0
          if cost > 0 then
            Civ5Ai_Snapshot._AppendGoldPurchase(
              commands, cityId, row.Type, cost, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
            count = count + 1
          end
        end
      end
      for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Buildings")) do
        if count >= maxPerCity then
          break
        end
        if row ~= nil and row.Type ~= nil and row.ID ~= nil
            and city.IsCanPurchase ~= nil
            and city:IsCanPurchase(false, false, -1, row.ID, -1, YieldTypes.YIELD_GOLD) then
          if atWar or row.Cost == nil or (row.Cost or 0) <= 200 then
            local cost = city.GetBuildingPurchaseCost ~= nil and (city:GetBuildingPurchaseCost(row.ID) or 0) or 0
            if cost > 0 then
              Civ5Ai_Snapshot._AppendGoldPurchase(
                commands, cityId, row.Type, cost, Civ5Ai_Snapshot._ItemProductionCost(city, row.Type))
              count = count + 1
            end
          end
        end
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalProduction(playerID, player)
  -- Empty-queue cities only. Same tables and Can* checks as ProductionPopup.lua.
  local commands = {}
  if player == nil or player.Cities == nil then
    return commands
  end
  for city in player:Cities() do
    if city ~= nil then
      local item = Civ5Ai_Snapshot._CityProductionItemId(city)
      local hasItem = type(item) == "string" and item ~= ""
      if not hasItem then
        Civ5Ai_Snapshot._AppendCityProductionCatalog(commands, city, Civ5Ai_Snapshot._CityWireId(city))
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._IsIdeologyBranchType(branchType)
  return branchType == "POLICY_BRANCH_FREEDOM"
    or branchType == "POLICY_BRANCH_ORDER"
    or branchType == "POLICY_BRANCH_AUTOCRACY"
end

function Civ5Ai_Snapshot._BuildLegalPolicyBranches(playerID, player)
  local commands = {}
  local canChooseIdeology = Civ5Ai_Snapshot._PlayerCanChooseIdeology(player)
  local policyDue = Civ5Ai_Snapshot._PolicyChoiceDue(player)
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("PolicyBranchTypes")) do
    local branchId = row.Type
    if Civ5Ai_Snapshot._IsIdeologyBranch(row) then
      if canChooseIdeology then
        table.insert(commands, {
          kind = "adopt_ideology",
          command_id = "CMD_ideology_" .. branchId,
          description = "Adopt ideology " .. branchId,
          fixed_arguments = { policy_branch_id = branchId },
          affected_ids = { branchId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    elseif policyDue and player.CanUnlockPolicyBranch ~= nil and player:CanUnlockPolicyBranch(row.ID) then
      if player.IsPolicyBranchUnlocked == nil or not player:IsPolicyBranchUnlocked(row.ID) then
        table.insert(commands, {
          kind = "unlock_policy_branch",
          command_id = "CMD_branch_" .. branchId,
          description = "Unlock " .. branchId,
          fixed_arguments = { policy_branch_id = branchId },
          affected_ids = { branchId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalPolicies(playerID, player)
  local commands = {}
  local seen = {}
  if not Civ5Ai_Snapshot._PolicyChoiceDue(player) then
    return commands
  end
  for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Policies")) do
    local policyId = row.Type
    local canList = player.CanAdoptPolicy ~= nil and player:CanAdoptPolicy(row.ID)
    if canList and row.PolicyBranchType ~= nil and GameInfo.PolicyBranchTypes ~= nil then
      local branchRow = GameInfo.PolicyBranchTypes[row.PolicyBranchType]
      if branchRow ~= nil and player.IsPolicyBranchUnlocked ~= nil and not player:IsPolicyBranchUnlocked(branchRow.ID) then
        canList = false
      end
    end
    if canList and player.HasPolicy ~= nil and player:HasPolicy(row.ID) then
      canList = false
    end
    if canList and seen[policyId] ~= true then
      seen[policyId] = true
      table.insert(commands, {
        kind = "adopt_social_policy",
        command_id = "CMD_policy_" .. policyId,
        description = "Adopt " .. policyId,
        fixed_arguments = { policy_id = policyId },
        affected_ids = { policyId },
        parameter_domains = {},
        runtime_status = "tested",
      })
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalPromotions(playerID, player)
  local commands = {}
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and Civ5Ai_Snapshot._UnitIsPromotionReady(unit) then
      local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
      for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("UnitPromotions")) do
        local okPromo, canPromote = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          return u.CanPromote ~= nil and u:CanPromote(row.ID, -1)
        end)
        if okPromo and canPromote then
          local promoId = row.Type
          table.insert(commands, {
            kind = "promote_unit",
            command_id = "CMD_promote_" .. unitId .. "_" .. promoId,
            description = "Promote " .. unitId .. " with " .. promoId,
            fixed_arguments = { unit_id = unitId, promotion_id = promoId },
            affected_ids = { unitId, promoId },
            parameter_domains = {},
            runtime_status = "tested",
          })
        end
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalMayaBonus(playerID, player)
  local commands = {}
  if player.GetNumMayaBoosts == nil or (player:GetNumMayaBoosts() or 0) <= 0 then
    return commands
  end
  for row in GameInfo.Units() do
    if row.Special == "SPECIALUNIT_PEOPLE" then
      if player.CanTrain ~= nil and player:CanTrain(row.ID, true, true, true, false) then
        local unitTypeId = row.Type
        table.insert(commands, {
          kind = "choose_maya_bonus",
          command_id = "CMD_maya_" .. unitTypeId,
          description = "Maya Long Count " .. unitTypeId,
          fixed_arguments = { unit_type_id = unitTypeId },
          affected_ids = { unitTypeId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._CollectLegalUnitIds(playerID, player)
  local unitIds = {}
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and Civ5Ai_Snapshot._UnitNeedsLegalCommands(unit) then
      table.insert(unitIds, Civ5Ai_Snapshot._UnitWireId(unit))
    end
  end
  return unitIds
end

function Civ5Ai_Snapshot._AppendUnitMissionCommand(commands, unitId, kind, commandId, fixedArgs, description)
  table.insert(commands, {
    kind = kind,
    command_id = commandId,
    description = description,
    fixed_arguments = fixedArgs,
    affected_ids = { unitId },
    parameter_domains = {},
    runtime_status = "tested",
  })
end


function Civ5Ai_Snapshot._PlotStrikeNote(playerID, plot)
  if plot == nil then
    return nil
  end
  local n = 0
  if plot.GetNumUnits ~= nil then
    n = plot:GetNumUnits() or 0
  end
  for i = 0, n - 1 do
    local unit = plot.GetUnit ~= nil and plot:GetUnit(i) or nil
    if unit ~= nil and (unit.IsDead == nil or not unit:IsDead()) and unit:GetOwner() ~= playerID then
      local ut = "unit"
      if unit.GetUnitType ~= nil and GameInfo ~= nil and GameInfo.Units ~= nil then
        local row = GameInfo.Units[unit:GetUnitType()]
        if row ~= nil and row.Type ~= nil then
          ut = row.Type
        end
      end
      return ut .. " at (" .. tostring(plot:GetX()) .. "," .. tostring(plot:GetY()) .. ")"
    end
  end
  local city = plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
  if city ~= nil and city:GetOwner() ~= playerID then
    return (city:GetName() or "City") .. " at (" .. tostring(plot:GetX()) .. "," .. tostring(plot:GetY()) .. ")"
  end
  return nil
end

function Civ5Ai_Snapshot._CombatPredictionLabel(prediction)
  if prediction == nil or CombatPredictionTypes == nil then
    return "unknown"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_TOTAL_VICTORY then
    return "total_victory"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_MAJOR_VICTORY then
    return "major_victory"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_SMALL_VICTORY then
    return "small_victory"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_STALEMATE then
    return "stalemate"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_SMALL_DEFEAT then
    return "small_defeat"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_MAJOR_DEFEAT then
    return "major_defeat"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_TOTAL_DEFEAT then
    return "total_defeat"
  end
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_RANGED then
    return "ranged"
  end
  return "unknown"
end

function Civ5Ai_Snapshot._CombatPreviewRisky(prediction, myDamage, theirDamage, myMaxHP, myCurrentDamage)
  if prediction == CombatPredictionTypes.COMBAT_PREDICTION_SMALL_DEFEAT
      or prediction == CombatPredictionTypes.COMBAT_PREDICTION_MAJOR_DEFEAT
      or prediction == CombatPredictionTypes.COMBAT_PREDICTION_TOTAL_DEFEAT then
    return true
  end
  if theirDamage ~= nil and myDamage ~= nil and theirDamage >= myDamage and theirDamage > 0 then
    return true
  end
  if myMaxHP ~= nil and myCurrentDamage ~= nil and theirDamage ~= nil and theirDamage > 0 then
    if (myMaxHP - myCurrentDamage) <= (myMaxHP / 2) then
      return true
    end
  end
  return false
end

function Civ5Ai_Snapshot._EnemyOnPlot(playerID, plot)
  if plot == nil then
    return nil, nil
  end
  local n = 0
  if plot.GetNumUnits ~= nil then
    n = plot:GetNumUnits() or 0
  end
  for i = 0, n - 1 do
    local unit = plot.GetUnit ~= nil and plot:GetUnit(i) or nil
    if unit ~= nil
        and (unit.IsDead == nil or not unit:IsDead())
        and unit:GetOwner() ~= playerID
        and Civ5Ai_Snapshot._PlayerAtWarWith(playerID, unit:GetOwner()) then
      return unit, nil
    end
  end
  local city = plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
  if city ~= nil
      and city:GetOwner() ~= playerID
      and Civ5Ai_Snapshot._PlayerAtWarWith(playerID, city:GetOwner()) then
    return nil, city
  end
  return nil, nil
end

function Civ5Ai_Snapshot._PlayerAtWarWith(playerID, otherPlayerID)
  if playerID == nil or otherPlayerID == nil or Players == nil or Teams == nil then
    return false
  end
  local player = Players[playerID]
  local other = Players[otherPlayerID]
  if player == nil or other == nil then
    return false
  end
  local team = Teams[player:GetTeam()]
  if team == nil then
    return false
  end
  return team:IsAtWar(other:GetTeam())
end

function Civ5Ai_Snapshot._EstimateCombatPreview(attacker, defenderUnit, defenderCity, targetPlot)
  if attacker == nil or targetPlot == nil then
    return nil
  end
  local myMaxHP = attacker.GetMaxHitPoints ~= nil and (attacker:GetMaxHitPoints() or 0) or 0
  local myDamage = attacker.GetDamage ~= nil and (attacker:GetDamage() or 0) or 0
  local myDamageInflicted = 0
  local theirDamageInflicted = 0
  local prediction = "unknown"
  local ranged = false
  local pFromPlot = attacker:GetPlot()
  local pToPlot = targetPlot

  if defenderUnit ~= nil then
    if attacker.IsCanAttackRanged ~= nil and attacker:IsCanAttackRanged() then
      ranged = true
      myDamageInflicted = attacker.GetRangeCombatDamage ~= nil
        and (attacker:GetRangeCombatDamage(defenderUnit, nil, false) or 0)
        or 0
      if Game ~= nil and Game.GetCombatPrediction ~= nil then
        if defenderUnit.IsEmbarked ~= nil and defenderUnit:IsEmbarked() then
          prediction = Civ5Ai_Snapshot._CombatPredictionLabel(CombatPredictionTypes.COMBAT_PREDICTION_TOTAL_VICTORY)
        else
          prediction = Civ5Ai_Snapshot._CombatPredictionLabel(Game.GetCombatPrediction(attacker, defenderUnit))
        end
      end
    else
      pFromPlot = attacker.GetMeleeAttackFromPlot ~= nil and attacker:GetMeleeAttackFromPlot(pToPlot) or pFromPlot
      local iMyStrength = attacker.GetMaxAttackStrength ~= nil
        and (attacker:GetMaxAttackStrength(pFromPlot, pToPlot, defenderUnit) or 0)
        or 0
      local iTheirStrength = defenderUnit.GetMaxDefenseStrength ~= nil
        and (defenderUnit:GetMaxDefenseStrength(pToPlot, attacker, pFromPlot, false, 0) or 0)
        or 0
      if attacker.GetMeleeCombatDamage ~= nil and iMyStrength > 0 then
        myDamageInflicted, theirDamageInflicted = attacker:GetMeleeCombatDamage(
          iMyStrength,
          iTheirStrength,
          false,
          defenderUnit,
          0
        )
      end
      if Game ~= nil and Game.GetCombatPrediction ~= nil then
        if defenderUnit.IsEmbarked ~= nil and defenderUnit:IsEmbarked() then
          prediction = Civ5Ai_Snapshot._CombatPredictionLabel(CombatPredictionTypes.COMBAT_PREDICTION_TOTAL_VICTORY)
        else
          prediction = Civ5Ai_Snapshot._CombatPredictionLabel(Game.GetCombatPrediction(attacker, defenderUnit))
        end
      end
    end
  elseif defenderCity ~= nil then
    if attacker.IsCanAttackRanged ~= nil and attacker:IsCanAttackRanged() then
      -- Ranged vs city: use range combat damage (not melee city APIs).
      ranged = true
      myDamageInflicted = attacker.GetRangeCombatDamage ~= nil
        and (attacker:GetRangeCombatDamage(nil, defenderCity, false) or 0)
        or 0
      theirDamageInflicted = 0
      if myDamageInflicted >= 60 then
        prediction = "total_victory"
      elseif myDamageInflicted >= 35 then
        prediction = "major_victory"
      elseif myDamageInflicted >= 15 then
        prediction = "small_victory"
      else
        prediction = "stalemate"
      end
    else
      local iMyStrength = attacker.GetMaxAttackStrength ~= nil
        and (attacker:GetMaxAttackStrength(pFromPlot, pToPlot, nil) or 0)
        or 0
      if attacker.GetMeleeCombatDamageCity ~= nil and iMyStrength > 0 then
        myDamageInflicted, theirDamageInflicted = attacker:GetMeleeCombatDamageCity(iMyStrength, defenderCity, false)
      end
      if myDamage > (myMaxHP / 2) and theirDamageInflicted > 0 then
        prediction = "risky"
      elseif theirDamageInflicted >= myDamageInflicted then
        prediction = "risky"
      else
        prediction = "favorable"
      end
    end
  else
    return nil
  end

  local risky = Civ5Ai_Snapshot._CombatPreviewRisky(
    nil,
    myDamageInflicted,
    theirDamageInflicted,
    myMaxHP,
    myDamage
  )
  if prediction == "small_defeat" or prediction == "major_defeat" or prediction == "total_defeat" or prediction == "risky" then
    risky = true
  end

  return {
    damage_to_enemy = myDamageInflicted,
    damage_to_self = theirDamageInflicted,
    prediction = prediction,
    risky = risky,
    ranged = ranged,
  }
end

function Civ5Ai_Snapshot._BuildCombatPreviews(playerID, player)
  local previews = Civ5Ai_Util.JsonArrayList()
  if player == nil or player:IsAlive() ~= true then
    return previews
  end
  local atWar = false
  for otherID = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    if Civ5Ai_Snapshot._PlayerAtWarWith(playerID, otherID) then
      atWar = true
      break
    end
  end
  if not atWar then
    return previews
  end

  for unit in player:Units() do
    if unit == nil or (unit.IsDead ~= nil and unit:IsDead()) then
      -- skip
    else
      local okCombat, isCombat = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return u.IsCombatUnit ~= nil and u:IsCombatUnit()
      end)
      if okCombat and isCombat then
        local moves = unit.MovesLeft ~= nil and (unit:MovesLeft() or 0) or 0
        if moves > 0 then
          local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
          local ux = unit:GetX()
          local uy = unit:GetY()
          local reach = 1
          local okRange, canRange = Civ5Ai_Snapshot._TryUnit(unit, function(u)
            return u.IsCanAttackRanged ~= nil and u:IsCanAttackRanged()
          end)
          local isRanged = okRange and canRange
          if isRanged and unit.GetRangeCombatRange ~= nil then
            reach = unit:GetRangeCombatRange() or 1
          end
          for dy = -reach, reach do
            for dx = -reach, reach do
              local plot = Map.GetPlot(ux + dx, uy + dy)
              if plot ~= nil then
                local px = plot:GetX()
                local py = plot:GetY()
                local dist = Civ5Ai_Snapshot._PlotDistance(ux, uy, px, py)
                if dist >= 1 and dist <= reach then
                  local defenderUnit, defenderCity = Civ5Ai_Snapshot._EnemyOnPlot(playerID, plot)
                  if defenderUnit ~= nil or defenderCity ~= nil then
                    local canStrike = false
                    if isRanged then
                      canStrike = unit.CanRangeStrikeAt ~= nil and unit:CanRangeStrikeAt(px, py)
                    else
                      canStrike = unit.CanMoveInto ~= nil and unit:CanMoveInto(plot, true)
                    end
                    if canStrike then
                      local estimate = Civ5Ai_Snapshot._EstimateCombatPreview(unit, defenderUnit, defenderCity, plot)
                      if estimate ~= nil then
                        local targetLabel = "plot"
                        if defenderUnit ~= nil then
                          local ut = "UNIT"
                          if defenderUnit.GetUnitType ~= nil and GameInfo ~= nil and GameInfo.Units ~= nil then
                            local row = GameInfo.Units[defenderUnit:GetUnitType()]
                            if row ~= nil and row.Type ~= nil then
                              ut = row.Type
                            end
                          end
                          targetLabel = ut
                        elseif defenderCity ~= nil then
                          targetLabel = defenderCity:GetName() or "city"
                        end
                        table.insert(previews, {
                          attacker_unit_id = unitId,
                          target_x = px,
                          target_y = py,
                          target_label = targetLabel,
                          damage_to_enemy = estimate.damage_to_enemy,
                          damage_to_self = estimate.damage_to_self,
                          prediction = estimate.prediction,
                          risky = estimate.risky,
                          ranged = estimate.ranged,
                        })
                      end
                    end
                  end
                end
              end
            end
          end
        end
      end
    end
  end
  return previews
end

function Civ5Ai_Snapshot._BuildLegalCityRangeStrike(playerID, player)
  local commands = {}
  if player == nil or player.Cities == nil then
    return commands
  end
  for city in player:Cities() do
    if city ~= nil and city.CanRangeStrike ~= nil and city:CanRangeStrike() then
      local cityId = Civ5Ai_Snapshot._CityWireId(city)
      local range = 2
      if city.GetBombardRange ~= nil then
        range = city:GetBombardRange() or 2
      end
      local cx = city:GetX()
      local cy = city:GetY()
      local notes = {}
      for dy = -range, range do
        for dx = -range, range do
          local plot = Map.GetPlot(cx + dx, cy + dy)
          if plot ~= nil then
            local px = plot:GetX()
            local py = plot:GetY()
            if Civ5Ai_Snapshot._PlotDistance(cx, cy, px, py) <= range
              and city.CanRangeStrikeAt ~= nil
              and city:CanRangeStrikeAt(px, py) then
              local note = Civ5Ai_Snapshot._PlotStrikeNote(playerID, plot)
              if note ~= nil then
                table.insert(notes, note)
              end
            end
          end
        end
      end
      -- Only offer rangeStrike when at least one concrete enemy/plot is legal.
      if #notes == 0 then
        -- CanRangeStrike alone is not enough; avoid dual-log cannot_range_strike_at noise.
      else
        local desc = cityId .. " can bombard " .. table.concat(notes, "; ")
        table.insert(commands, {
          kind = "city_range_strike",
          command_id = "CMD_city_range_" .. cityId,
          description = desc,
          fixed_arguments = { city_id = cityId },
          affected_ids = { cityId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._CityNeedsCaptureChoice(playerID, city)
  if city == nil then
    return false
  end
  if city.IsPuppet ~= nil and city:IsPuppet() == true then
    return false
  end
  if city.IsOccupied ~= nil and city:IsOccupied() == true then
    return false
  end
  if city.IsRazing ~= nil and city:IsRazing() == true then
    return false
  end
  local prev = -1
  if city.GetPreviousOwner ~= nil then
    prev = city:GetPreviousOwner() or -1
  end
  return prev >= 0 and prev ~= playerID
end

function Civ5Ai_Snapshot._BuildLegalCityStatus(playerID, player)
  local commands = {}
  if player == nil or player.Cities == nil then
    return commands
  end
  local mayNotAnnex = player.MayNotAnnex ~= nil and player:MayNotAnnex() == true
  for city in player:Cities() do
    if city ~= nil and Civ5Ai_Snapshot._CityNeedsCaptureChoice(playerID, city) then
        local cityId = Civ5Ai_Snapshot._CityWireId(city)
        local statuses = { "puppet" }
        if not mayNotAnnex then
          table.insert(statuses, "annex")
        end
        if city.CanRaze ~= nil and city:CanRaze() then
          table.insert(statuses, "raze")
        end
        for _, status in ipairs(statuses) do
          table.insert(commands, {
            kind = "set_city_status",
            command_id = "CMD_capture_" .. cityId .. "_" .. status,
            description = "Set captured city status",
            fixed_arguments = { city_id = cityId, status = status },
            affected_ids = { cityId },
            parameter_domains = {},
            runtime_status = "tested",
          })
        end
    end
  end
  return commands
end


function Civ5Ai_Snapshot._IsWorkerUnit(unit)
  if unit == nil then
    return false
  end
  local unitType = GameInfo.Units[unit:GetUnitType()]
  local typeId = unitType and unitType.Type or ""
  local classRow = unit.GetUnitClassType ~= nil and GameInfo.UnitClasses[unit:GetUnitClassType()] or nil
  local classId = classRow and classRow.Type or ""
  if classId == "UNITCLASS_WORKER" or typeId == "UNIT_WORKER" then
    return true
  end
  if string.find(string.upper(typeId), "WORKER", 1, true) and not string.find(string.upper(typeId), "BOAT", 1, true) then
    return true
  end
  return false
end

function Civ5Ai_Snapshot._PlayerWorkerAndCityCount(player)
  local workers = 0
  local cities = 0
  if player == nil then
    return 0, 0
  end
  if player.GetNumCities ~= nil then
    cities = player:GetNumCities() or 0
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and Civ5Ai_Snapshot._IsWorkerUnit(unit) then
      workers = workers + 1
    end
  end
  return workers, cities
end

function Civ5Ai_Snapshot._PlayerGoldPerTurn(player)
  if player == nil then
    return 0
  end
  if player.CalculateGoldRate ~= nil then
    return player:CalculateGoldRate() or 0
  end
  return 0
end

function Civ5Ai_Snapshot._BuildLegalDisband(playerID, player)
  local commands = {}
  if player == nil then
    return commands
  end
  local gpt = Civ5Ai_Snapshot._PlayerGoldPerTurn(player)
  local workers, cities = Civ5Ai_Snapshot._PlayerWorkerAndCityCount(player)
  local offerAll = gpt < 0 or (cities > 0 and workers > cities)
  local deleteCmd = CommandTypes ~= nil and CommandTypes.COMMAND_DELETE or nil
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local isWorker = Civ5Ai_Snapshot._IsWorkerUnit(unit)
      if isWorker or offerAll then
        local canDelete = true
        if deleteCmd ~= nil and unit.CanDoCommand ~= nil then
          -- CP/VP: 4th arg is iData3 (number), not bTestVisible.
          local ok, result = pcall(function()
            return unit:CanDoCommand(deleteCmd, -1, -1, 0, false)
          end)
          if not ok then
            ok, result = pcall(function()
              return unit:CanDoCommand(deleteCmd, -1, -1)
            end)
          end
          if ok then
            canDelete = result == true
          else
            canDelete = true
          end
        end
        if canDelete then
          local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
          table.insert(commands, {
            kind = "disband_unit",
            command_id = "CMD_disband_" .. unitId,
            description = "Disband " .. unitId,
            fixed_arguments = { unit_id = unitId },
          })
        end
      end
    end
  end
  return commands
end


function Civ5Ai_Snapshot._BeliefKeysFromGetter(getter)
  if getter == nil then
    return {}
  end
  local keys = getter()
  if keys == nil then
    return {}
  end
  local out = {}
  for _, beliefKey in ipairs(keys) do
    local belief = GameInfo.Beliefs ~= nil and GameInfo.Beliefs[beliefKey] or nil
    if belief ~= nil and belief.Type ~= nil then
      table.insert(out, belief.Type)
    elseif type(beliefKey) == "string" then
      table.insert(out, beliefKey)
    end
  end
  return out
end

function Civ5Ai_Snapshot._PlayerHasFoundingProphet(player)
  if player == nil then
    return false
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._UnitCanFoundReligion ~= nil then
        if Civ5Ai_Apply._UnitCanFoundReligion(unit) then
          return true
        end
      else
        local row = GameInfo.Units ~= nil and GameInfo.Units[unit:GetUnitType()] or nil
        if row ~= nil and (row.FoundReligion == true or row.Special == "SPECIALUNIT_PROPHET") then
          return true
        end
      end
    end
  end
  return false
end

function Civ5Ai_Snapshot._AppendBeliefCommands(commands, kind, prefix, descriptionPrefix, beliefTypes)
  for _, beliefType in ipairs(beliefTypes) do
    table.insert(commands, {
      kind = kind,
      command_id = prefix .. beliefType,
      description = descriptionPrefix .. " " .. beliefType,
      fixed_arguments = { belief_id = beliefType },
      affected_ids = { beliefType },
      parameter_domains = {},
      runtime_status = "tested",
    })
  end
end

function Civ5Ai_Snapshot._BuildLegalReligion(playerID, player)
  local commands = {}
  if player == nil or Game == nil then
    return commands
  end
  -- Pantheon: faith threshold / CanCreatePantheon.
  if player.CanCreatePantheon ~= nil and player:CanCreatePantheon(false)
    and (player.HasCreatedPantheon == nil or not player:HasCreatedPantheon()) then
    local beliefs = Civ5Ai_Snapshot._BeliefKeysFromGetter(Game.GetAvailablePantheonBeliefs)
    Civ5Ai_Snapshot._AppendBeliefCommands(
      commands,
      "found_pantheon",
      "CMD_pantheon_",
      "Found pantheon with",
      beliefs
    )
  end
  -- Found religion: Great Prophet present and no founded religion yet.
  local hasReligion = player.HasCreatedReligion ~= nil and player:HasCreatedReligion() == true
  if not hasReligion and Civ5Ai_Snapshot._PlayerHasFoundingProphet(player) then
    local founders = Civ5Ai_Snapshot._BeliefKeysFromGetter(Game.GetAvailableFounderBeliefs)
    Civ5Ai_Snapshot._AppendBeliefCommands(
      commands,
      "found_religion",
      "CMD_founder_",
      "Found religion with founder",
      founders
    )
  end
  -- Enhance religion: own a religion, prophet available, enhancer beliefs remain.
  local owns = player.OwnsReligion ~= nil and player:OwnsReligion() == true
  if owns and Civ5Ai_Snapshot._PlayerHasFoundingProphet(player) then
    local alreadyEnhanced = false
    if player.HasEnhancedReligion ~= nil then
      alreadyEnhanced = player:HasEnhancedReligion() == true
    end
    if not alreadyEnhanced then
      local enhancers = Civ5Ai_Snapshot._BeliefKeysFromGetter(Game.GetAvailableEnhancerBeliefs)
      Civ5Ai_Snapshot._AppendBeliefCommands(
        commands,
        "enhance_religion",
        "CMD_enhancer_",
        "Enhance religion with",
        enhancers
      )
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalUnitMissions(playerID, player)
  local commands = {}
  local unitIds = Civ5Ai_Snapshot._CollectLegalUnitIds(playerID, player)
  for _, unitId in ipairs(unitIds) do
    local unit = Civ5Ai_Snapshot._LiveUnit(playerID, unitId)
    if unit == nil then
    else
      local plot = nil
      Civ5Ai_Snapshot._TryUnit(unit, function(u)
        plot = Map.GetPlot(u:GetX(), u:GetY())
      end)
      if plot ~= nil then
        for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Builds")) do
          local okBuild, canBuild = Civ5Ai_Snapshot._TryUnit(unit, function(u)
            if u.CanBuild == nil then
              return false
            end
            return u:CanBuild(plot, row.ID)
          end)
          if okBuild and canBuild then
            local buildId = row.Type
            Civ5Ai_Snapshot._AppendUnitMissionCommand(
              commands,
              unitId,
              "improve_tile",
              "CMD_improve_" .. unitId .. "_" .. buildId,
              { unit_id = unitId, build_id = buildId },
              "Build " .. buildId .. " with " .. unitId
            )
          end
        end
      end
      unit = Civ5Ai_Snapshot._LiveUnit(playerID, unitId)
      if unit ~= nil then
        local okDiscover, canDiscover = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          if u.CanDiscover == nil or plot == nil then
            return false
          end
          return u:CanDiscover(plot)
        end)
        if okDiscover and canDiscover then
          Civ5Ai_Snapshot._AppendUnitMissionCommand(
            commands,
            unitId,
            "discover_tech",
            "CMD_discover_" .. unitId,
            { unit_id = unitId },
            "Discover tech with " .. unitId
          )
        end
        local okHurry, hurryAmount = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          if u.GetHurryProduction == nil then
            return 0
          end
          return u:GetHurryProduction() or 0
        end)
        if okHurry and hurryAmount > 0 then
          Civ5Ai_Snapshot._AppendUnitMissionCommand(
            commands,
            unitId,
            "hurry_production",
            "CMD_hurry_" .. unitId,
            { unit_id = unitId },
            "Hurry production with " .. unitId
          )
        end
        local okTrade, canTrade = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          if u.CanTrade == nil or plot == nil then
            return false
          end
          return u:CanTrade(plot)
        end)
        if okTrade and canTrade then
          Civ5Ai_Snapshot._AppendUnitMissionCommand(
            commands,
            unitId,
            "trade_mission",
            "CMD_trade_" .. unitId,
            { unit_id = unitId },
            "Trade mission with " .. unitId
          )
        end
        local okGolden, canGolden = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          if u.CanGoldenAge == nil or plot == nil then
            return false
          end
          return u:CanGoldenAge(plot)
        end)
        if okGolden and canGolden then
          Civ5Ai_Snapshot._AppendUnitMissionCommand(
            commands,
            unitId,
            "start_golden_age",
            "CMD_golden_" .. unitId,
            { unit_id = unitId },
            "Golden age with " .. unitId
          )
        end
        unit = Civ5Ai_Snapshot._LiveUnit(playerID, unitId)
        if unit ~= nil and plot ~= nil then
          local okWork, canWork = Civ5Ai_Snapshot._TryUnit(unit, function(u)
            if u.CanCreateGreatWork == nil then
              return false
            end
            return u:CanCreateGreatWork(plot)
          end)
          if okWork and canWork then
            Civ5Ai_Snapshot._AppendUnitMissionCommand(
              commands,
              unitId,
              "create_great_work",
              "CMD_greatwork_" .. unitId,
              { unit_id = unitId },
              "Create great work with " .. unitId
            )
          end
        end
        unit = Civ5Ai_Snapshot._LiveUnit(playerID, unitId)
        if unit ~= nil and plot ~= nil then
          Civ5Ai_Snapshot._AppendSpecialPlotMissions(commands, unit, unitId, plot)
        end
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._BuildLegalUnitPostures(playerID, player)
  local commands = {}
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and Civ5Ai_Snapshot._UnitNeedsLegalCommands(unit) then
      local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
      local plot = Map.GetPlot(unit:GetX(), unit:GetY())
      local okFortify, canFortify = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return plot ~= nil and u.CanFortify ~= nil and u:CanFortify(plot)
      end)
      local alreadyFortified = false
      Civ5Ai_Snapshot._TryUnit(unit, function(u)
        if u.IsFortified ~= nil then
          alreadyFortified = u:IsFortified() == true
        end
      end)
      if okFortify and canFortify and not alreadyFortified then
        table.insert(commands, {
          kind = "unit_posture_fortify",
          command_id = "CMD_fortify_" .. unitId,
          description = "Fortify " .. unitId,
          fixed_arguments = { unit_id = unitId },
          affected_ids = { unitId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
      local okSleep, canSleep = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return plot ~= nil and u.CanSleep ~= nil and u:CanSleep(plot)
      end)
      if okSleep and canSleep then
        table.insert(commands, {
          kind = "unit_posture_sleep",
          command_id = "CMD_sleep_" .. unitId,
          description = "Sleep " .. unitId,
          fixed_arguments = { unit_id = unitId },
          affected_ids = { unitId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
      local okHeal, canHeal = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return plot ~= nil and u.CanHeal ~= nil and u:CanHeal(plot)
      end)
      if okHeal and canHeal then
        table.insert(commands, {
          kind = "unit_posture_heal",
          command_id = "CMD_heal_" .. unitId,
          description = "Heal " .. unitId,
          fixed_arguments = { unit_id = unitId },
          affected_ids = { unitId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
      table.insert(commands, {
        kind = "unit_skip",
        command_id = "CMD_skip_" .. unitId,
        description = "Skip " .. unitId,
        fixed_arguments = { unit_id = unitId },
        affected_ids = { unitId },
        parameter_domains = {},
        runtime_status = "tested",
      })
      local isAir = Civ5Ai_Snapshot._UnitIsAir(unit)
      if isAir then
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "rebase",
          "CMD_rebase_" .. unitId,
          { unit_id = unitId },
          "Rebase " .. unitId
        )
      else
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "move_unit",
          "CMD_move_" .. unitId,
          { unit_id = unitId },
          "Move " .. unitId
        )
        local okCombat, isCombat = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          return u.IsCombatUnit ~= nil and u:IsCombatUnit()
        end)
        if okCombat and isCombat then
          Civ5Ai_Snapshot._AppendUnitMissionCommand(
            commands,
            unitId,
            "attack_target",
            "CMD_attack_" .. unitId,
            { unit_id = unitId },
            "Attack with " .. unitId
          )
        end
      end
      local okRange, canRange = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return u.CanRangeStrike ~= nil and u:CanRangeStrike()
      end)
      if okRange and canRange then
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "range_attack",
          "CMD_range_" .. unitId,
          { unit_id = unitId },
          "Range attack with " .. unitId
        )
      end
      local okPara, canPara = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return plot ~= nil and u.CanParadrop ~= nil and u:CanParadrop(plot, false)
      end)
      if okPara and canPara then
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "paradrop",
          "CMD_paradrop_" .. unitId,
          { unit_id = unitId },
          "Paradrop " .. unitId
        )
      end
      local okNuke, canNuke = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return u.CanNuke ~= nil and u:CanNuke()
      end)
      if okNuke and canNuke then
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "nuke",
          "CMD_nuke_" .. unitId,
          { unit_id = unitId },
          "Nuke with " .. unitId
        )
      end
      local okPatrol, canPatrol = Civ5Ai_Snapshot._TryUnit(unit, function(u)
        return plot ~= nil and u.CanAirPatrol ~= nil and u:CanAirPatrol(plot)
      end)
      if okPatrol and canPatrol then
        Civ5Ai_Snapshot._AppendUnitMissionCommand(
          commands,
          unitId,
          "air_patrol",
          "CMD_intercept_" .. unitId,
          { unit_id = unitId },
          "Intercept with " .. unitId
        )
      end
      if Civ5Ai_Snapshot._UnitCanFound(playerID, unit) then
        table.insert(commands, {
          kind = "found_city",
          command_id = "CMD_found_" .. unitId,
          description = "Found city with " .. unitId,
          fixed_arguments = { unit_id = unitId },
          affected_ids = { unitId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
      local alreadyAuto = unit.IsAutomated ~= nil and unit:IsAutomated() == true
      if not alreadyAuto then
        for _, row in ipairs(Civ5Ai_Snapshot._InfoRows("Automates")) do
          if Civ5Ai_Snapshot._UnitCanAutomate(unit, row) then
            Civ5Ai_Snapshot._AppendUnitMissionCommand(
              commands,
              unitId,
              "automate_unit",
              "CMD_automate_" .. unitId .. "_" .. row.Type,
              { unit_id = unitId, automate_id = row.Type },
              "Automate " .. row.Type .. " with " .. unitId
            )
          end
        end
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot._UnitIsAir(unit)
  if unit == nil then
    return false
  end
  local domain = nil
  Civ5Ai_Snapshot._TryUnit(unit, function(u)
    if u.GetDomainType ~= nil then
      domain = u:GetDomainType()
    end
  end)
  if DomainTypes ~= nil and DomainTypes.DOMAIN_AIR ~= nil and domain ~= nil then
    return domain == DomainTypes.DOMAIN_AIR
  end
  local row = domain ~= nil and GameInfo.Domains ~= nil and GameInfo.Domains[domain] or nil
  return row ~= nil and row.Type == "DOMAIN_AIR"
end

function Civ5Ai_Snapshot._UnitTypeRow(unit)
  local row = nil
  Civ5Ai_Snapshot._TryUnit(unit, function(u)
    row = GameInfo.Units[u:GetUnitType()]
  end)
  return row
end

function Civ5Ai_Snapshot._AppendSpecialPlotMissions(commands, unit, unitId, plot)
  if unit == nil or unitId == nil or plot == nil then
    return
  end
  local typeRow = Civ5Ai_Snapshot._UnitTypeRow(unit)
  local city = plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
  if typeRow ~= nil and typeRow.SpreadReligion and city ~= nil then
    local okSpreads, spreadsLeft = Civ5Ai_Snapshot._TryUnit(unit, function(u)
      if u.GetSpreadsLeft == nil then
        return 1
      end
      return u:GetSpreadsLeft() or 0
    end)
    if okSpreads and spreadsLeft > 0 then
      Civ5Ai_Snapshot._AppendUnitMissionCommand(
        commands,
        unitId,
        "spread_religion",
        "CMD_spread_" .. unitId,
        { unit_id = unitId },
        "Spread religion with " .. unitId
      )
    end
  end
  if typeRow ~= nil and typeRow.RemoveHeresy and city ~= nil then
    Civ5Ai_Snapshot._AppendUnitMissionCommand(
      commands,
      unitId,
      "remove_heresy",
      "CMD_heresy_" .. unitId,
      { unit_id = unitId },
      "Remove heresy with " .. unitId
    )
  end
  local okPillage, canPillage = Civ5Ai_Snapshot._TryUnit(unit, function(u)
    return u.CanPillage ~= nil and u:CanPillage(plot)
  end)
  if okPillage and canPillage then
    Civ5Ai_Snapshot._AppendUnitMissionCommand(
      commands,
      unitId,
      "pillage",
      "CMD_pillage_" .. unitId,
      { unit_id = unitId },
      "Pillage with " .. unitId
    )
  end
  local upgradeTypeId, upgradeGold = Civ5Ai_Snapshot._UnitUpgradeOffer(unit)
  if upgradeTypeId ~= nil then
    Civ5Ai_Snapshot._AppendUnitMissionCommand(
      commands,
      unitId,
      "upgrade_unit",
      "CMD_upgrade_" .. unitId .. "_" .. upgradeTypeId,
      { unit_id = unitId, unit_type_id = upgradeTypeId },
      "Upgrade " .. unitId .. " to " .. upgradeTypeId
    )
  end
end

function Civ5Ai_Snapshot._UnitUpgradeOffer(unit)
  local typeId = nil
  local gold = 0
  local ok, can = Civ5Ai_Snapshot._TryUnit(unit, function(u)
    if CommandTypes ~= nil and CommandTypes.COMMAND_UPGRADE ~= nil and u.CanDoCommand ~= nil then
      if u:CanDoCommand(CommandTypes.COMMAND_UPGRADE) ~= true then
        return false
      end
    elseif u.CanUpgradeRightNow ~= nil then
      if u:CanUpgradeRightNow(false) ~= true then
        return false
      end
    else
      return false
    end
    if u.GetUpgradeUnitType == nil then
      return false
    end
    local upgradeType = u:GetUpgradeUnitType()
    if upgradeType == nil or upgradeType < 0 then
      return false
    end
    local row = GameInfo.Units[upgradeType]
    if row == nil or row.Type == nil then
      return false
    end
    typeId = row.Type
    if u.UpgradePrice ~= nil then
      gold = u:UpgradePrice(upgradeType) or 0
    end
    return true
  end)
  if ok and can and typeId ~= nil then
    return typeId, gold
  end
  return nil, 0
end

function Civ5Ai_Snapshot._BuildUpgradeOptions(unit)
  local options = Civ5Ai_Util.JsonArrayList()
  local typeId, gold = Civ5Ai_Snapshot._UnitUpgradeOffer(unit)
  if typeId ~= nil then
    table.insert(options, {
      unit_type_id = typeId,
      gold_cost = gold,
    })
  end
  return options
end

function Civ5Ai_Snapshot._UnitCanAutomate(unit, row)
  if unit == nil or row == nil then
    return false
  end
  if CommandTypes ~= nil and CommandTypes.COMMAND_AUTOMATE ~= nil then
    local ok, can = Civ5Ai_Snapshot._TryUnit(unit, function(u)
      if u.CanDoCommand == nil then
        return nil
      end
      return u:CanDoCommand(CommandTypes.COMMAND_AUTOMATE, row.ID) == true
    end)
    if ok and can ~= nil then
      return can == true
    end
  end
  local typeRow = nil
  Civ5Ai_Snapshot._TryUnit(unit, function(u)
    typeRow = GameInfo.Units[u:GetUnitType()]
  end)
  if typeRow == nil then
    return false
  end
  if row.Type == "AUTOMATE_BUILD" then
    return (typeRow.WorkRate or 0) > 0
  end
  if row.Type == "AUTOMATE_EXPLORE" then
    return typeRow.DefaultUnitAI == "UNITAI_EXPLORE" or typeRow.CombatClass == "UNITCOMBAT_RECON"
  end
  return false
end

function Civ5Ai_Snapshot._UnitCanFound(playerID, unit)
  if unit == nil then
    return false
  end
  if unit.IsFound ~= nil and not unit:IsFound() then
    return false
  end
  local player = Players[playerID]
  if player ~= nil and player.CanFound ~= nil then
    return player:CanFound(unit:GetX(), unit:GetY()) == true
  end
  return unit.IsFound ~= nil and unit:IsFound()
end

function Civ5Ai_Snapshot._PlotDistance(x1, y1, x2, y2)
  if Map ~= nil and Map.PlotDistance ~= nil then
    return Map.PlotDistance(x1, y1, x2, y2)
  end
  return math.abs(x1 - x2) + math.abs(y1 - y2)
end

function Civ5Ai_Snapshot._PlotYields(plot)
  local yields = { food = 0, production = 0, commerce = 0 }
  if plot == nil or plot.CalculateYield == nil or YieldTypes == nil then
    return yields
  end
  if YieldTypes.YIELD_FOOD ~= nil then
    yields.food = plot:CalculateYield(YieldTypes.YIELD_FOOD, true) or 0
  end
  if YieldTypes.YIELD_PRODUCTION ~= nil then
    yields.production = plot:CalculateYield(YieldTypes.YIELD_PRODUCTION, true) or 0
  end
  if YieldTypes.YIELD_GOLD ~= nil then
    yields.commerce = plot:CalculateYield(YieldTypes.YIELD_GOLD, true) or 0
  end
  return yields
end

function Civ5Ai_Snapshot._DirectionList()
  local dirs = {}
  if DirectionTypes == nil then
    return dirs
  end
  local names = {
    "DIRECTION_NORTHEAST",
    "DIRECTION_EAST",
    "DIRECTION_SOUTHEAST",
    "DIRECTION_SOUTHWEST",
    "DIRECTION_WEST",
    "DIRECTION_NORTHWEST",
  }
  for _, name in ipairs(names) do
    if DirectionTypes[name] ~= nil then
      table.insert(dirs, DirectionTypes[name])
    end
  end
  return dirs
end

function Civ5Ai_Snapshot._CoastKind(plot)
  if plot == nil or plot.IsCoastalLand == nil or not plot:IsCoastalLand() then
    return false, false
  end
  local ocean = false
  local lake = false
  if Map == nil or Map.PlotDirection == nil then
    return true, false
  end
  for _, dir in ipairs(Civ5Ai_Snapshot._DirectionList()) do
    local neighbor = Map.PlotDirection(plot:GetX(), plot:GetY(), dir)
    if neighbor ~= nil and neighbor.IsWater ~= nil and neighbor:IsWater() then
      if neighbor.IsLake ~= nil and neighbor:IsLake() then
        lake = true
      else
        ocean = true
      end
    end
  end
  if not ocean and not lake then
    ocean = true
  end
  return ocean, lake
end

function Civ5Ai_Snapshot._ResourceScore(resourceId)
  if resourceId == nil or resourceId == "" then
    return 0
  end
  local info = GameInfo.Resources
  if info == nil then
    return 1
  end
  local row = info[resourceId]
  if row == nil then
    return 1
  end
  local class = row.ResourceClassType
  if class == "RESOURCECLASS_LUXURY" then
    return 2
  end
  if class == "RESOURCECLASS_RUSH" or class == "RESOURCECLASS_MODERN" then
    return 2
  end
  return 1
end

function Civ5Ai_Snapshot._NearbyResourceIds(center, team, radius)
  local ids = Civ5Ai_Util.JsonArrayList()
  if center == nil then
    return ids
  end
  local cx = center:GetX()
  local cy = center:GetY()
  local seen = {}
  for ny = cy - radius, cy + radius do
    for nx = cx - radius, cx + radius do
      local plot = Map.GetPlot(nx, ny)
      if plot ~= nil then
        local px = plot:GetX()
        local py = plot:GetY()
        if Civ5Ai_Snapshot._PlotDistance(cx, cy, px, py) <= radius then
          if team == nil or plot.IsRevealed == nil or plot:IsRevealed(team, false) then
            local resourceId = Civ5Ai_Snapshot._ResourceTypeName(plot)
            if type(resourceId) == "string" and resourceId ~= "" and not seen[resourceId] then
              seen[resourceId] = true
              table.insert(ids, resourceId)
            end
          end
        end
      end
    end
  end
  table.sort(ids)
  return ids
end

function Civ5Ai_Snapshot._MinimumCityRange()
  if GameDefines ~= nil and GameDefines.MIN_CITY_RANGE ~= nil then
    return GameDefines.MIN_CITY_RANGE
  end
  return 3
end

function Civ5Ai_Snapshot._NearestCityToPlot(x, y)
  local nearestName = nil
  local nearestDist = nil
  local lastPlayer = 63
  if GameDefines ~= nil and GameDefines.MAX_CIV_PLAYERS ~= nil then
    lastPlayer = GameDefines.MAX_CIV_PLAYERS - 1
  end
  for playerID = 0, lastPlayer do
    local owner = Players[playerID]
    if owner ~= nil and owner:IsAlive() then
      for city in owner:Cities() do
        if city ~= nil then
          local dist = Civ5Ai_Snapshot._PlotDistance(x, y, city:GetX(), city:GetY())
          if nearestDist == nil or dist < nearestDist then
            nearestDist = dist
            nearestName = city:GetName() or "City"
          end
        end
      end
    end
  end
  return nearestDist, nearestName
end

function Civ5Ai_Snapshot._DescribeCannotFoundReason(player, plot)
  if plot == nil then
    return "invalid plot"
  end
  if plot.IsWater ~= nil and plot:IsWater() then
    return "water tile; embark first / found on land"
  end
  if plot.IsMountain ~= nil and plot:IsMountain() then
    return "mountain tile"
  end
  if plot.IsNaturalWonder ~= nil and plot:IsNaturalWonder(false) then
    return "natural wonder"
  end
  local city = plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
  if city ~= nil then
    return "city already here (" .. (city:GetName() or "City") .. ")"
  end
  local minRange = Civ5Ai_Snapshot._MinimumCityRange()
  local nearestDist, nearestName = Civ5Ai_Snapshot._NearestCityToPlot(plot:GetX(), plot:GetY())
  if nearestDist ~= nil and nearestName ~= nil and nearestDist <= minRange then
    return "too close to "
      .. nearestName
      .. " ("
      .. tostring(nearestDist)
      .. " hexes; need "
      .. tostring(minRange + 1)
      .. "+) at ("
      .. tostring(plot:GetX())
      .. ","
      .. tostring(plot:GetY())
      .. ")"
  end
  if player ~= nil and player.CanFound ~= nil and not player:CanFound(plot:GetX(), plot:GetY()) then
    return "cannot found here"
  end
  return "unknown"
end

function Civ5Ai_Snapshot._SettleTileRecord(player, plot, fromX, fromY, team, distance)
  local ocean, lake = Civ5Ai_Snapshot._CoastKind(plot)
  local river = false
  if plot.IsFreshWater ~= nil and plot:IsFreshWater() then
    river = true
  elseif plot.IsRiver ~= nil and plot:IsRiver() then
    river = true
  end
  local hills = plot.IsHills ~= nil and plot:IsHills() == true
  local ruins = false
  if plot.IsGoody ~= nil and plot:IsGoody() then
    ruins = true
  else
    local improvementId = Civ5Ai_Snapshot._ImprovementTypeName(plot)
    ruins = improvementId == "IMPROVEMENT_GOODY_HUT"
  end
  local canFound = false
  if player ~= nil and player.CanFound ~= nil then
    canFound = player:CanFound(plot:GetX(), plot:GetY()) == true
  end
  local cannotFoundReason = nil
  if not canFound then
    cannotFoundReason = Civ5Ai_Snapshot._DescribeCannotFoundReason(player, plot)
  end
  local resources = Civ5Ai_Snapshot._NearbyResourceIds(plot, team, Civ5Ai_Snapshot.SETTLE_CITY_RADIUS)
  local score = 0
  if ocean then
    score = score + 4
  elseif lake then
    score = score + 1
  end
  if river then
    score = score + 3
  end
  if hills then
    score = score + 1
  end
  for _, resourceId in ipairs(resources) do
    score = score + Civ5Ai_Snapshot._ResourceScore(resourceId)
  end
  score = score - distance
  local plotYields = Civ5Ai_Snapshot._PlotYields(plot)
  local featureId = Civ5Ai_Snapshot._FeatureTypeName(plot)
  local forest = featureId == "FEATURE_FOREST"
  local jungle = featureId == "FEATURE_JUNGLE"
  return {
    x = plot:GetX(),
    y = plot:GetY(),
    distance = distance,
    coast = ocean,
    lake = lake,
    river = river,
    hills = hills,
    forest = forest,
    jungle = jungle,
    ruins = ruins,
    can_found = canFound,
    cannot_found_reason = (cannotFoundReason ~= nil and string.find(string.lower(tostring(cannotFoundReason)), "water", 1, true) and (tostring(cannotFoundReason) .. "; embark first / found on land")) or cannotFoundReason,
    resources = resources,
    score = score,
    yields = {
      food = plotYields.food,
      production = plotYields.production,
      gold = plotYields.commerce,
    },
  }
end

function Civ5Ai_Snapshot._SettleSitePriority(site)
  if site == nil or site.here == nil then
    return 0
  end
  local here = site.here
  local score = 0
  if here.can_found == true then
    score = score + 10000 + (here.score or 0)
  elseif site.look ~= nil and #site.look > 0 then
    score = score + 5000 + (site.look[1].score or 0)
  else
    score = score + 1000
  end
  if site.can_act == true then
    score = score + 100
  end
  return score
end

function Civ5Ai_Snapshot._BuildSettleSites(playerID)
  local buffer = {}
  local player = Players[playerID]
  if player == nil then
    return Civ5Ai_Util.JsonArrayList()
  end
  local team = player:GetTeam()
  local radius = Civ5Ai_Snapshot.SETTLE_SCAN_RADIUS
  local maxLook = Civ5Ai_Snapshot.SETTLE_MAX_LOOK
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and unit.IsFound ~= nil and unit:IsFound() then
      local ux = unit:GetX()
      local uy = unit:GetY()
      local herePlot = Map.GetPlot(ux, uy)
      if herePlot ~= nil then
        local here = Civ5Ai_Snapshot._SettleTileRecord(player, herePlot, ux, uy, team, 0)
        local look = {}
        local nearby = {}
        local seen = {}
        seen[ux .. "_" .. uy] = true
        for ny = uy - radius, uy + radius do
          for nx = ux - radius, ux + radius do
            local plot = Map.GetPlot(nx, ny)
            if plot ~= nil then
              local px = plot:GetX()
              local py = plot:GetY()
              local key = px .. "_" .. py
              if not seen[key] then
                seen[key] = true
                local dist = Civ5Ai_Snapshot._PlotDistance(ux, uy, px, py)
                if dist <= radius then
                  local revealed = team == nil or plot.IsRevealed == nil or plot:IsRevealed(team, false)
                  if revealed then
                    local tile = Civ5Ai_Snapshot._SettleTileRecord(player, plot, ux, uy, team, dist)
                    table.insert(nearby, tile)
                    if dist > 0
                      and tile.can_found
                      and (not here.can_found or tile.score > here.score) then
                      table.insert(look, tile)
                    end
                  end
                end
              end
            end
          end
        end
        table.sort(nearby, function(a, b)
          if a.distance ~= b.distance then
            return a.distance < b.distance
          end
          if a.y ~= b.y then
            return a.y < b.y
          end
          return a.x < b.x
        end)
        table.sort(look, function(a, b)
          if a.score ~= b.score then
            return a.score > b.score
          end
          return a.distance < b.distance
        end)
        local clipped = Civ5Ai_Util.JsonArrayList()
        for i = 1, math.min(maxLook, #look) do
          table.insert(clipped, look[i])
        end
        local nearbyOut = Civ5Ai_Util.JsonArrayList()
        for i = 1, #nearby do
          table.insert(nearbyOut, nearby[i])
        end
        table.insert(buffer, {
          unit_id = Civ5Ai_Snapshot._UnitWireId(unit),
          here = here,
          look = clipped,
          nearby = nearbyOut,
          can_act = unit.IsReadyToMove ~= nil and unit:IsReadyToMove() == true,
        })
      end
    end
  end
  table.sort(buffer, function(a, b)
    return Civ5Ai_Snapshot._SettleSitePriority(a) > Civ5Ai_Snapshot._SettleSitePriority(b)
  end)
  local sites = Civ5Ai_Util.JsonArrayList()
  local maxSites = Civ5Ai_Snapshot.SETTLE_MAX_SITES
  for i = 1, math.min(maxSites, #buffer) do
    local entry = buffer[i]
    table.insert(sites, {
      unit_id = entry.unit_id,
      here = entry.here,
      look = entry.look,
      nearby = entry.nearby,
    })
  end
  return sites
end

function Civ5Ai_Snapshot._NullableId(value)
  if value == nil or value == "" then
    return Civ5Ai_Util.JsonNull()
  end
  return value
end

function Civ5Ai_Snapshot._GameInfoType(tableName, index)
  if index == nil or index < 0 then
    return Civ5Ai_Util.JsonNull()
  end
  local info = GameInfo[tableName]
  if info == nil then
    return Civ5Ai_Util.JsonNull()
  end
  local row = info[index]
  if row == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return row.Type
end

function Civ5Ai_Snapshot._TerrainTypeName(plot)
  if plot == nil or plot.GetTerrainType == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return Civ5Ai_Snapshot._GameInfoType("Terrains", plot:GetTerrainType())
end

function Civ5Ai_Snapshot._FeatureTypeName(plot)
  if plot == nil or plot.GetFeatureType == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return Civ5Ai_Snapshot._GameInfoType("Features", plot:GetFeatureType())
end

function Civ5Ai_Snapshot._ResourceTypeName(plot)
  if plot == nil or plot.GetResourceType == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return Civ5Ai_Snapshot._GameInfoType("Resources", plot:GetResourceType())
end

function Civ5Ai_Snapshot._ImprovementTypeName(plot)
  if plot == nil then
    return Civ5Ai_Util.JsonNull()
  end
  if plot.IsGoody ~= nil and plot:IsGoody() then
    return "IMPROVEMENT_GOODY_HUT"
  end
  if plot.GetImprovementType == nil then
    return Civ5Ai_Util.JsonNull()
  end
  return Civ5Ai_Snapshot._GameInfoType("Improvements", plot:GetImprovementType())
end

function Civ5Ai_Snapshot._VisibilityChar(plot)
  if plot == nil then
    return "?"
  end
  if plot.IsMountain ~= nil and plot:IsMountain() then
    return "^"
  end
  if plot.IsNaturalWonder ~= nil and plot:IsNaturalWonder(false) then
    return "^"
  end
  if plot.IsHills ~= nil and plot:IsHills() then
    return "#"
  end
  if plot.IsWater ~= nil and plot:IsWater() then
    local terrain = Civ5Ai_Snapshot._TerrainTypeName(plot)
    if terrain == "TERRAIN_OCEAN" then
      return "o"
    end
    return "~"
  end
  return "."
end

function Civ5Ai_Snapshot._PlotOwnerPlayerId(plot)
  if plot == nil or plot.GetOwner == nil then
    return nil
  end
  local owner = plot:GetOwner()
  if owner == nil or owner < 0 then
    return nil
  end
  return Civ5Ai_Util.PlayerId(owner)
end

function Civ5Ai_Snapshot._PlotIsVisibleToTeam(plot, team)
  if plot == nil or team == nil or plot.IsVisible == nil then
    return false
  end
  local ok, visible = pcall(plot.IsVisible, plot, team)
  return ok and visible == true
end

function Civ5Ai_Snapshot._PlotIsRevealedToTeam(plot, team)
  if plot == nil or team == nil or plot.IsRevealed == nil then
    return false
  end
  local ok, revealed = pcall(plot.IsRevealed, plot, team, false)
  if ok and revealed == true then
    return true
  end
  ok, revealed = pcall(plot.IsRevealed, plot, team)
  return ok and revealed == true
end

function Civ5Ai_Snapshot._UnitSightRange(unit)
  local range = 2
  if unit == nil then
    return range
  end
  if unit.VisibilityRange ~= nil then
    local ok, value = pcall(unit.VisibilityRange, unit)
    if ok and type(value) == "number" and value > 0 then
      return value
    end
  end
  if unit.GetVisibilityRange ~= nil then
    local ok, value = pcall(unit.GetVisibilityRange, unit)
    if ok and type(value) == "number" and value > 0 then
      return value
    end
  end
  return range
end

function Civ5Ai_Snapshot._HexDistance(x0, y0, x1, y1)
  if Map ~= nil and Map.PlotDistance ~= nil then
    local ok, dist = pcall(Map.PlotDistance, x0, y0, x1, y1)
    if ok and type(dist) == "number" then
      return dist
    end
  end
  return math.max(math.abs((x1 or 0) - (x0 or 0)), math.abs((y1 or 0) - (y0 or 0)))
end

function Civ5Ai_Snapshot._CollectMapAnchors(playerID, yourUnits, yourCities)
  local anchors = {}
  local function addAnchor(x, y)
    if x == nil or y == nil or x < 0 or y < 0 then
      return
    end
    table.insert(anchors, { x = x, y = y })
  end
  for _, unit in ipairs(yourUnits or {}) do
    local plotId = unit.plot_id
    if plotId ~= nil then
      local x, y = Civ5Ai_Util.ParsePlotId(plotId)
      if x ~= nil and y ~= nil then
        addAnchor(x, y)
      end
    end
  end
  for _, city in ipairs(yourCities or {}) do
    local plotId = city.plot_id
    if plotId ~= nil then
      local x, y = Civ5Ai_Util.ParsePlotId(plotId)
      if x ~= nil and y ~= nil then
        addAnchor(x, y)
      end
    end
  end
  -- Live units/cities so t0 (no capital) still anchors on settler/warrior vision.
  local player = Players[playerID]
  if player ~= nil then
    if player.Units ~= nil then
      for unit in player:Units() do
        if unit ~= nil and not unit:IsDead() then
          addAnchor(unit:GetX(), unit:GetY())
        end
      end
    end
    if player.Cities ~= nil then
      for city in player:Cities() do
        if city ~= nil then
          addAnchor(city:GetX(), city:GetY())
        end
      end
    end
    if #anchors == 0 and player.GetCapitalCity ~= nil then
      local capital = player:GetCapitalCity()
      if capital ~= nil then
        addAnchor(capital:GetX(), capital:GetY())
      end
    end
  end
  return anchors
end

function Civ5Ai_Snapshot._RiverEdgeNeighbor(plot, direction)
  if plot == nil or direction == nil or Map == nil or Map.PlotDirection == nil then
    return nil
  end
  local x = plot:GetX()
  local y = plot:GetY()
  local neighbor = Map.PlotDirection(x, y, direction)
  if neighbor == nil then
    return nil
  end
  return {
    dx = neighbor:GetX() - x,
    dy = neighbor:GetY() - y,
  }
end

function Civ5Ai_Snapshot._RiverEdgeIdForDirection(direction)
  if DirectionTypes == nil or direction == nil then
    return nil
  end
  if direction == DirectionTypes.DIRECTION_WEST then
    return "E"
  end
  if direction == DirectionTypes.DIRECTION_NORTHWEST then
    return "SE"
  end
  if direction == DirectionTypes.DIRECTION_NORTHEAST then
    return "SW"
  end
  return nil
end

function Civ5Ai_Snapshot._RiverEdges(plot)
  local edges = {}
  if plot == nil then
    return edges
  end
  local checks = {}
  if DirectionTypes ~= nil then
    if DirectionTypes.DIRECTION_NORTHEAST ~= nil and plot.IsNEOfRiver ~= nil then
      table.insert(checks, { plot.IsNEOfRiver, DirectionTypes.DIRECTION_NORTHEAST })
    end
    if DirectionTypes.DIRECTION_WEST ~= nil and plot.IsWOfRiver ~= nil then
      table.insert(checks, { plot.IsWOfRiver, DirectionTypes.DIRECTION_WEST })
    end
    if DirectionTypes.DIRECTION_NORTHWEST ~= nil and plot.IsNWOfRiver ~= nil then
      table.insert(checks, { plot.IsNWOfRiver, DirectionTypes.DIRECTION_NORTHWEST })
    end
  end
  for _, entry in ipairs(checks) do
    local isRiverFn = entry[1]
    local direction = entry[2]
    if isRiverFn ~= nil and direction ~= nil and isRiverFn(plot) then
      local neighbor = Civ5Ai_Snapshot._RiverEdgeNeighbor(plot, direction)
      local edgeId = Civ5Ai_Snapshot._RiverEdgeIdForDirection(direction)
      if neighbor ~= nil and edgeId ~= nil then
        table.insert(edges, {
          edge_id = edgeId,
          dx = neighbor.dx,
          dy = neighbor.dy,
        })
      end
    end
  end
  if #edges == 0 and plot.IsRiver ~= nil and plot:IsRiver() then
    table.insert(edges, { edge_id = "SE", dx = 0, dy = -1 })
  end
  return edges
end

function Civ5Ai_Snapshot._BuildPlotRecord(plot, playerID, turn, team)
  local x = plot:GetX()
  local y = plot:GetY()
  local visible = false
  if plot.IsVisible ~= nil then
    visible = plot:IsVisible(team) == true
  elseif plot.IsRevealed ~= nil then
    visible = plot:IsRevealed(team, false) == true
  end
  local knowledge = visible and "visible" or "remembered"
  local water = plot.IsWater ~= nil and plot:IsWater() == true
  local fresh_water = false
  if plot.IsFreshWater ~= nil and plot:IsFreshWater() then
    fresh_water = true
  elseif plot.IsRiver ~= nil and plot:IsRiver() then
    fresh_water = true
  elseif plot.IsRiverSide ~= nil and plot:IsRiverSide() then
    fresh_water = true
  end
  return {
    plot_id = Civ5Ai_Util.PlotId(x, y),
    x = x,
    y = y,
    knowledge = knowledge,
    last_seen_turn = visible and turn or Civ5Ai_Util.JsonNull(),
    area_id = "AREA_0",
    terrain_id = Civ5Ai_Snapshot._TerrainTypeName(plot),
    water = water,
    hills = plot.IsHills ~= nil and plot:IsHills() == true,
    peak = (plot.IsMountain ~= nil and plot:IsMountain())
      or (plot.IsNaturalWonder ~= nil and plot:IsNaturalWonder(false)),
    fresh_water = fresh_water,
    river_edges = Civ5Ai_Snapshot._RiverEdges(plot),
    revealed_owner_id = Civ5Ai_Snapshot._NullableId(Civ5Ai_Snapshot._PlotOwnerPlayerId(plot)),
    feature_id = Civ5Ai_Snapshot._NullableId(Civ5Ai_Snapshot._FeatureTypeName(plot)),
    improvement_id = Civ5Ai_Snapshot._NullableId(Civ5Ai_Snapshot._ImprovementTypeName(plot)),
    route_id = Civ5Ai_Util.JsonNull(),
    resource_id = Civ5Ai_Snapshot._NullableId(Civ5Ai_Snapshot._ResourceTypeName(plot)),
    yields = Civ5Ai_Snapshot._PlotYields(plot),
    defense_percent = 0,
    city_id = Civ5Ai_Util.JsonNull(),
    worked_by_city_id = Civ5Ai_Util.JsonNull(),
    visible_stack_ids = Civ5Ai_Util.JsonArrayList(),
  }
end

function Civ5Ai_Snapshot._BuildKnownMap(playerID, turn, yourUnits, yourCities)
  local player = Players[playerID]
  local mapWidth, mapHeight = Map.GetGridSize()
  local plots = Civ5Ai_Util.JsonArrayList()
  local empty_image = {
    attached = false,
    format = "png-grid-v1",
    width = mapWidth,
    height = mapHeight,
    legend = Civ5Ai_Util.JsonArrayList(),
    label_ids = Civ5Ai_Util.JsonArrayList(),
  }
  if player == nil then
    return {
      format = "plot-grid-v1",
      visibility_mode = "player_visible",
      plots = plots,
      areas = Civ5Ai_Util.JsonArrayList(),
      frontiers = Civ5Ai_Util.JsonArrayList(),
      visible_stacks = Civ5Ai_Util.JsonArrayList(),
      image = empty_image,
    }
  end
  local team = player:GetTeam()
  local seen = {}
  local function addPlot(plot, forceVisible)
    if plot == nil or #plots >= Civ5Ai_Snapshot.MAX_MAP_PLOTS then
      return
    end
    local plotId = Civ5Ai_Util.PlotId(plot:GetX(), plot:GetY())
    if seen[plotId] then
      return
    end
    seen[plotId] = true
    local rec = Civ5Ai_Snapshot._BuildPlotRecord(plot, playerID, turn, team)
    if forceVisible then
      rec.knowledge = "visible"
      rec.last_seen_turn = turn
    end
    table.insert(plots, rec)
  end
  local anchors = Civ5Ai_Snapshot._CollectMapAnchors(playerID, yourUnits, yourCities)
  local minX, minY = mapWidth, mapHeight
  local maxX, maxY = 0, 0
  for _, anchor in ipairs(anchors) do
    minX = math.min(minX, anchor.x - Civ5Ai_Snapshot.MAP_EXPORT_RADIUS)
    minY = math.min(minY, anchor.y - Civ5Ai_Snapshot.MAP_EXPORT_RADIUS)
    maxX = math.max(maxX, anchor.x + Civ5Ai_Snapshot.MAP_EXPORT_RADIUS)
    maxY = math.max(maxY, anchor.y + Civ5Ai_Snapshot.MAP_EXPORT_RADIUS)
  end
  if #anchors == 0 then
    minX = 0
    minY = 0
    maxX = math.min(mapWidth - 1, Civ5Ai_Snapshot.MAP_EXPORT_RADIUS * 2)
    maxY = math.min(mapHeight - 1, Civ5Ai_Snapshot.MAP_EXPORT_RADIUS * 2)
  end
  minX = math.max(0, minX)
  minY = math.max(0, minY)
  maxX = math.min(mapWidth - 1, maxX)
  maxY = math.min(mapHeight - 1, maxY)
  for y = minY, maxY do
    for x = minX, maxX do
      local plot = Map.GetPlot(x, y)
      if plot ~= nil then
        local visible = Civ5Ai_Snapshot._PlotIsVisibleToTeam(plot, team)
        local revealed = Civ5Ai_Snapshot._PlotIsRevealedToTeam(plot, team)
        if visible or revealed then
          addPlot(plot)
        end
      end
    end
  end
  -- Unit vision, including t0 FOW lag (starting units exist but IsRevealed is still false).
  if player.Units ~= nil then
    for unit in player:Units() do
      if unit ~= nil and not unit:IsDead() then
        local ux, uy = unit:GetX(), unit:GetY()
        local range = Civ5Ai_Snapshot._UnitSightRange(unit)
        local unitPlot = Map.GetPlot(ux, uy)
        local fowLag = unitPlot ~= nil
          and (not Civ5Ai_Snapshot._PlotIsVisibleToTeam(unitPlot, team))
          and (not Civ5Ai_Snapshot._PlotIsRevealedToTeam(unitPlot, team))
        for y = uy - range, uy + range do
          for x = ux - range, ux + range do
            if x >= 0 and y >= 0 and x < mapWidth and y < mapHeight then
              if Civ5Ai_Snapshot._HexDistance(ux, uy, x, y) <= range then
                local plot = Map.GetPlot(x, y)
                if plot ~= nil then
                  local visible = Civ5Ai_Snapshot._PlotIsVisibleToTeam(plot, team)
                  local revealed = Civ5Ai_Snapshot._PlotIsRevealedToTeam(plot, team)
                  if visible or revealed then
                    addPlot(plot)
                  elseif fowLag then
                    addPlot(plot, true)
                  end
                end
              end
            end
          end
        end
      end
    end
  end
  local viewport = {
    x0 = minX,
    y0 = minY,
    width = maxX - minX + 1,
    height = maxY - minY + 1,
  }
  return {
    format = "plot-grid-v1",
    visibility_mode = "player_visible",
    plots = plots,
    areas = Civ5Ai_Util.JsonArrayList(),
    frontiers = Civ5Ai_Util.JsonArrayList(),
    visible_stacks = Civ5Ai_Util.JsonArrayList(),
    viewport = viewport,
    image = {
      attached = false,
      format = "png-grid-v1",
      width = mapWidth,
      height = mapHeight,
      legend = Civ5Ai_Util.JsonArrayList(),
      label_ids = Civ5Ai_Util.JsonArrayList(),
    },
  }
end

function Civ5Ai_Snapshot._MilitaryPower(other)
  if other == nil then
    return Civ5Ai_Util.JsonNull()
  end
  if other.GetMilitaryMight ~= nil then
    return other:GetMilitaryMight() or 0
  end
  if other.GetPower ~= nil then
    return other:GetPower() or 0
  end
  return Civ5Ai_Util.JsonNull()
end

function Civ5Ai_Snapshot._LeaderDisplayName(player, leaderType)
  if player ~= nil and player.GetName ~= nil then
    local name = player:GetName()
    if name ~= nil and name ~= "" then
      return name
    end
  end
  local key = leaderType and leaderType.Description or nil
  if key ~= nil and key ~= "" then
    if Locale ~= nil and Locale.ConvertTextKey ~= nil then
      return Locale.ConvertTextKey(key)
    end
    return key
  end
  return "Unknown"
end

function Civ5Ai_Snapshot._BuildKnownPlayers(playerID)
  local known = Civ5Ai_Util.JsonArrayList()
  local us = Players[playerID]
  if us == nil then
    return known
  end
  local ourTeam = Teams[us:GetTeam()]
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for otherID = 0, lastMajor do
    if otherID ~= playerID then
      local other = Players[otherID]
      if other ~= nil and other:IsAlive() and not other:IsMinorCiv() and not other:IsBarbarian() then
        if ourTeam:IsHasMet(other:GetTeam()) then
          local civType = GameInfo.Civilizations[other:GetCivilizationType()]
          local leaderType = GameInfo.Leaders[other:GetLeaderType()]
          local capital = other.GetCapitalCity ~= nil and other:GetCapitalCity() or nil
          local capitalId = Civ5Ai_Util.JsonNull()
          if capital ~= nil then
            capitalId = Civ5Ai_Snapshot._CityWireId(capital)
          end
          local ideology = Civ5Ai_Util.JsonArrayList()
          if other.GetLateGamePolicyTree ~= nil then
            local tree = other:GetLateGamePolicyTree()
            local branch = tree ~= nil and tree ~= -1 and GameInfo.PolicyBranchTypes[tree] or nil
            if branch ~= nil then
              table.insert(ideology, branch.Type)
            end
          end
          table.insert(known, {
            player_id = Civ5Ai_Util.PlayerId(otherID),
            team_id = "TEAM_" .. tostring(other:GetTeam()),
            leader_id = leaderType and leaderType.Type or "LEADER_UNKNOWN",
            leader_name = Civ5Ai_Snapshot._LeaderDisplayName(other, leaderType),
            civilization_id = civType and civType.Type or "CIVILIZATION_UNKNOWN",
            score = other:GetScore() or 0,
            population = other.GetTotalPopulation ~= nil and (other:GetTotalPopulation() or 0) or Civ5Ai_Util.JsonNull(),
            land = other.GetNumPlots ~= nil and (other:GetNumPlots() or 0) or Civ5Ai_Util.JsonNull(),
            power = Civ5Ai_Snapshot._MilitaryPower(other),
            known_capital_city_id = capitalId,
            known_religion_id = Civ5Ai_Snapshot._ReligionWireId(other),
            known_civic_ids = ideology,
            known_tech_ids = Civ5Ai_Util.JsonArrayList(),
            relation = Civ5Ai_Diplo.RelationBetween(playerID, otherID),
            at_war_elsewhere = Civ5Ai_Snapshot._AtWarWithOtherMajor(playerID, otherID),
          })
        end
      end
    end
  end
  return known
end

function Civ5Ai_Snapshot._BuildKnownOtherCities(playerID)
  local cities = Civ5Ai_Util.JsonArrayList()
  local us = Players[playerID]
  if us == nil then
    return cities
  end
  local teamID = us:GetTeam()
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  local turn = Civ5Ai_Snapshot._GameTurn()
  for otherID = 0, lastMajor do
    if otherID ~= playerID and #cities < 24 then
      local other = Players[otherID]
      if other ~= nil and other:IsAlive() and not other:IsMinorCiv() then
        for city in other:Cities() do
          local plot = Map.GetPlot(city:GetX(), city:GetY())
          if plot ~= nil and plot.IsRevealed ~= nil and plot:IsRevealed(teamID) then
            local visible = plot.IsVisible ~= nil and plot:IsVisible(teamID)
            local bombardDamage = 0
        if city.GetDamage ~= nil then
          bombardDamage = city:GetDamage() or 0
        end
        table.insert(cities, {
              city_id = Civ5Ai_Snapshot._CityWireId(city),
              owner_player_id = Civ5Ai_Util.PlayerId(otherID),
              name = city:GetName() or "City",
              plot_id = Civ5Ai_Util.PlotId(city:GetX(), city:GetY()),
              area_id = "AREA_" .. tostring(city.GetArea ~= nil and city:GetArea() or 0),
              knowledge = visible and "visible" or "remembered",
              last_seen_turn = turn,
              population = city:GetPopulation() or 1,
              is_capital = city:IsCapital() == true,
              visible_defense = Civ5Ai_Snapshot._CityStrengthDisplay(city),
              bombard_damage = bombardDamage,
              health_percent = math.floor(100 * math.max(0, 200 - bombardDamage) / 200),
            })
            if #cities >= 24 then
              break
            end
          end
        end
      end
    end
  end
  return cities
end

function Civ5Ai_Snapshot._BuildVisibleOtherUnits(playerID)
  local units = Civ5Ai_Util.JsonArrayList()
  local us = Players[playerID]
  if us == nil then
    return units
  end
  local teamID = us:GetTeam()
  local lastPlayer = 63
  if GameDefines ~= nil and GameDefines.MAX_CIV_PLAYERS ~= nil then
    lastPlayer = GameDefines.MAX_CIV_PLAYERS - 1
  end
  for otherID = 0, lastPlayer do
    if otherID ~= playerID and #units < 40 then
      local other = Players[otherID]
      if other ~= nil and other:IsAlive() then
        for unit in other:Units() do
          if unit ~= nil and not unit:IsDead() then
            local plot = Map.GetPlot(unit:GetX(), unit:GetY())
            if plot ~= nil and plot.IsVisible ~= nil and plot:IsVisible(teamID) then
              local unitType = GameInfo.Units[unit:GetUnitType()]
              local hp = unit:GetCurrHitPoints() or 100
              local maxHp = unit:GetMaxHitPoints() or 100
              local strength = 0
              if unit.GetBaseCombatStrength ~= nil then
                strength = unit:GetBaseCombatStrength() or 0
              end
              table.insert(units, {
                unit_id = "UNIT_" .. tostring(otherID) .. "_" .. tostring(unit:GetID()),
                owner_player_id = Civ5Ai_Util.PlayerId(otherID),
                unit_type_id = unitType and unitType.Type or "UNIT_UNKNOWN",
                plot_id = Civ5Ai_Util.PlotId(unit:GetX(), unit:GetY()),
                health_percent = maxHp > 0 and math.floor(100 * hp / maxHp) or 100,
                visible_strength = strength,
                movement_ready = unit:IsReadyToMove() == true,
              })
              if #units >= 40 then
                break
              end
            end
          end
        end
      end
    end
  end
  return units
end

function Civ5Ai_Snapshot._PreGameType(tableName, methodName, fallback)
  if PreGame == nil or PreGame[methodName] == nil then
    return fallback
  end
  local ok, index = pcall(PreGame[methodName])
  if not ok then
    return fallback
  end
  local typed = Civ5Ai_Snapshot._GameInfoTypeName(tableName, index)
  if typed == nil or Civ5Ai_Util._IsJsonNull(typed) then
    return fallback
  end
  return typed
end

function Civ5Ai_Snapshot._BuildGameBlock(player, mapWidth, mapHeight)
  local era = "ERA_UNKNOWN"
  if player ~= nil and player.GetCurrentEra ~= nil then
    era = Civ5Ai_Snapshot._GameInfoTypeName("Eras", player:GetCurrentEra())
    if Civ5Ai_Util._IsJsonNull(era) then
      era = "ERA_UNKNOWN"
    end
  end
  local speed = "GAMESPEED_UNKNOWN"
  if Game.GetGameSpeedType ~= nil then
    speed = Civ5Ai_Snapshot._GameInfoTypeName("GameSpeeds", Game.GetGameSpeedType())
    if Civ5Ai_Util._IsJsonNull(speed) then
      speed = "GAMESPEED_UNKNOWN"
    end
  end
  local handicap = "HANDICAP_UNKNOWN"
  if Game.GetHandicapType ~= nil then
    handicap = Civ5Ai_Snapshot._GameInfoTypeName("HandicapInfos", Game.GetHandicapType())
    if Civ5Ai_Util._IsJsonNull(handicap) then
      handicap = "HANDICAP_UNKNOWN"
    end
  end
  local world = "WORLDSIZE_UNKNOWN"
  if Map.GetWorldSize ~= nil then
    world = Civ5Ai_Snapshot._GameInfoTypeName("Worlds", Map.GetWorldSize())
    if Civ5Ai_Util._IsJsonNull(world) then
      world = "WORLDSIZE_UNKNOWN"
    end
  end
  local mapScript = "Unknown"
  if PreGame ~= nil and PreGame.GetMapScript ~= nil then
    local ok, script = pcall(function()
      return PreGame.GetMapScript()
    end)
    if ok and script ~= nil and script ~= "" then
      mapScript = Civ5Ai_Snapshot._ClipText(script, 160)
    end
  end
  local startEra = era
  if Game.GetStartEra ~= nil then
    local typed = Civ5Ai_Snapshot._GameInfoTypeName("Eras", Game.GetStartEra())
    if not Civ5Ai_Util._IsJsonNull(typed) then
      startEra = typed
    end
  end
  return {
    map_width = mapWidth,
    map_height = mapHeight,
    map_script = mapScript,
    world_size_id = world,
    game_speed_id = speed,
    difficulty_id = handicap,
    era_id = era,
    start_era_id = startEra,
    climate_id = Civ5Ai_Snapshot._PreGameType("Climates", "GetClimate", "CLIMATE_UNKNOWN"),
    sea_level_id = Civ5Ai_Snapshot._PreGameType("SeaLevels", "GetSeaLevel", "SEALEVEL_UNKNOWN"),
    calendar_id = "CALENDAR_DEFAULT",
    network_multiplayer = Game.IsNetworkMultiPlayer and Game.IsNetworkMultiPlayer() or false,
    wrap_x = false,
    wrap_y = false,
    max_turns = Civ5Ai_Util.JsonNull(),
    options = Civ5Ai_Util.JsonArrayList(),
    victory_ids = Civ5Ai_Util.JsonArrayList(),
  }
end


-- CIV5AI_TRADE_UNIT_COMMANDS_V1 helpers
function Civ5Ai_Snapshot._IsTradeUnit(unit)
  if unit == nil then
    return false
  end
  local ok, isTrade = Civ5Ai_Snapshot._TryUnit(unit, function(u)
    if u.IsTrade ~= nil then
      return u:IsTrade() == true
    end
    return false
  end)
  if ok and isTrade then
    return true
  end
  local unitType = nil
  Civ5Ai_Snapshot._TryUnit(unit, function(u)
    unitType = GameInfo.Units[u:GetUnitType()]
  end)
  local typeId = unitType and unitType.Type or ""
  if string.find(typeId, "CARAVAN", 1, true) ~= nil then
    return true
  end
  if string.find(typeId, "CARGO_SHIP", 1, true) ~= nil then
    return true
  end
  if string.find(typeId, "CARGO", 1, true) ~= nil and string.find(typeId, "SHIP", 1, true) ~= nil then
    return true
  end
  return false
end

function Civ5Ai_Snapshot._TradeConnectionTypeId(typeNum)
  if typeNum == nil then
    return "TRADE_CONNECTION_INTERNATIONAL"
  end
  if TradeConnectionTypes ~= nil then
    for name, id in pairs(TradeConnectionTypes) do
      if id == typeNum and type(name) == "string" and name ~= "NUM_TRADE_CONNECTION_TYPES" then
        return name
      end
    end
  end
  local names = {
    [0] = "TRADE_CONNECTION_INTERNATIONAL",
    [1] = "TRADE_CONNECTION_FOOD",
    [2] = "TRADE_CONNECTION_PRODUCTION",
    [3] = "TRADE_CONNECTION_WONDER_RESOURCE",
    [4] = "TRADE_CONNECTION_GOLD_INTERNAL",
  }
  return names[typeNum] or ("TRADE_CONNECTION_" .. tostring(typeNum))
end

function Civ5Ai_Snapshot._TradeConnectionTypeNum(typeId)
  if type(typeId) == "number" then
    return typeId
  end
  if typeId == nil or typeId == "" then
    return 0
  end
  if TradeConnectionTypes ~= nil and TradeConnectionTypes[typeId] ~= nil then
    return TradeConnectionTypes[typeId]
  end
  local names = {
    TRADE_CONNECTION_INTERNATIONAL = 0,
    TRADE_CONNECTION_FOOD = 1,
    TRADE_CONNECTION_PRODUCTION = 2,
    TRADE_CONNECTION_WONDER_RESOURCE = 3,
    TRADE_CONNECTION_GOLD_INTERNAL = 4,
  }
  return names[typeId] or tonumber(typeId) or 0
end

function Civ5Ai_Snapshot._CityPromptLabel(city)
  if city == nil then
    return "UnknownCity"
  end
  local name = city.GetName ~= nil and (city:GetName() or "City") or "City"
  name = string.gsub(name, "%s+", "")
  return name
end

function Civ5Ai_Snapshot._TradeCityOwnerLabel(city)
  if city == nil then
    return "Unknown"
  end
  local owner = Players[city:GetOwner()]
  if owner == nil then
    return "Unknown"
  end
  if owner.GetCivilizationShortDescription ~= nil then
    local label = owner:GetCivilizationShortDescription()
    if label ~= nil and label ~= "" then
      return string.gsub(tostring(label), "%s+", " ")
    end
  end
  local civ = GameInfo.Civilizations[owner:GetCivilizationType()]
  if civ ~= nil and civ.ShortDescription ~= nil and Locale ~= nil and Locale.ConvertTextKey ~= nil then
    return Locale.ConvertTextKey(civ.ShortDescription)
  end
  return "Civ" .. tostring(city:GetOwner())
end

function Civ5Ai_Snapshot._TradeUnitState(unit)
  local state = {
    is_trade_unit = false,
    trade_route_index = -1,
    trade_needs_route = false,
    trade_recalled = false,
    trade_origin_city_name = Civ5Ai_Util.JsonNull(),
    trade_can_change_home = false,
  }
  if unit == nil or not Civ5Ai_Snapshot._IsTradeUnit(unit) then
    return state
  end
  state.is_trade_unit = true
  local plot = nil
  Civ5Ai_Snapshot._TryUnit(unit, function(u)
    plot = Map.GetPlot(u:GetX(), u:GetY())
    if u.GetTradeRouteIndex ~= nil then
      state.trade_route_index = u:GetTradeRouteIndex() or -1
    end
    if u.IsRecalledTrader ~= nil then
      state.trade_recalled = u:IsRecalledTrader() == true
    end
  end)
  if plot ~= nil then
    local originCity = plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
    if originCity ~= nil then
      state.trade_origin_city_name = Civ5Ai_Snapshot._CityPromptLabel(originCity)
    end
    local okCan, canRoute = Civ5Ai_Snapshot._TryUnit(unit, function(u)
      return u.CanMakeTradeRoute ~= nil and u:CanMakeTradeRoute(plot) == true
    end)
    if okCan and canRoute then
      state.trade_needs_route = true
    end
  end
  return state
end

function Civ5Ai_Snapshot._BuildLegalTradeUnits(playerID, player)
  local commands = {}
  if player == nil or player.GetPotentialInternationalTradeRouteDestinations == nil then
    return commands
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() and Civ5Ai_Snapshot._IsTradeUnit(unit) then
      local unitId = Civ5Ai_Snapshot._UnitWireId(unit)
      local plot = Map.GetPlot(unit:GetX(), unit:GetY())
      local originCity = plot ~= nil and plot.GetPlotCity ~= nil and plot:GetPlotCity() or nil
      local originName = originCity ~= nil and Civ5Ai_Snapshot._CityPromptLabel(originCity) or "NoHomeCity"
      local hasMoves = Civ5Ai_Snapshot._UnitHasMovesLeft(unit)
      local routeIndex = -1
      local recalled = false
      Civ5Ai_Snapshot._TryUnit(unit, function(u)
        if u.GetTradeRouteIndex ~= nil then
          routeIndex = u:GetTradeRouteIndex() or -1
        end
        if u.IsRecalledTrader ~= nil then
          recalled = u:IsRecalledTrader() == true
        end
      end)

      local canMake = false
      if plot ~= nil then
        local okCan, canRoute = Civ5Ai_Snapshot._TryUnit(unit, function(u)
          return u.CanMakeTradeRoute ~= nil and u:CanMakeTradeRoute(plot) == true
        end)
        canMake = okCan and canRoute
      end

      if canMake and hasMoves then
        local destinations = player:GetPotentialInternationalTradeRouteDestinations(unit) or {}
        for _, dest in ipairs(destinations) do
          local destX = dest.X
          local destY = dest.Y
          local connType = dest.TradeConnectionType or 0
          local connId = Civ5Ai_Snapshot._TradeConnectionTypeId(connType)
          local destPlot = Map.GetPlot(destX, destY)
          local destCity = destPlot ~= nil and destPlot.GetPlotCity ~= nil and destPlot:GetPlotCity() or nil
          local destName = destCity ~= nil and Civ5Ai_Snapshot._CityPromptLabel(destCity) or ("Plot" .. tostring(destX) .. "_" .. tostring(destY))
          local ownerLabel = destCity ~= nil and Civ5Ai_Snapshot._TradeCityOwnerLabel(destCity) or "Unknown"
          local cmdId = "CMD_route_" .. unitId .. "_" .. tostring(destX) .. "_" .. tostring(destY) .. "_" .. connId
          table.insert(commands, {
            kind = "establish_trade_route",
            command_id = cmdId,
            description = "Establish trade route from "
              .. originName
              .. " to "
              .. destName
              .. " ("
              .. ownerLabel
              .. ") as "
              .. connId
              .. " with "
              .. unitId,
            fixed_arguments = {
              unit_id = unitId,
              origin_city_name = originName,
              destination_city_name = destName,
              destination_owner = ownerLabel,
              target_x = destX,
              target_y = destY,
              trade_connection_type = connId,
            },
            affected_ids = { unitId },
            parameter_domains = {},
            runtime_status = "tested",
          })
        end
      end

      if player.GetPotentialTradeUnitNewHomeCity ~= nil and hasMoves then
        local homes = player:GetPotentialTradeUnitNewHomeCity(unit) or {}
        for _, home in ipairs(homes) do
          local homeX = home.X
          local homeY = home.Y
          local homePlot = Map.GetPlot(homeX, homeY)
          local homeCity = homePlot ~= nil and homePlot.GetPlotCity ~= nil and homePlot:GetPlotCity() or nil
          local homeName = homeCity ~= nil and Civ5Ai_Snapshot._CityPromptLabel(homeCity) or ("Plot" .. tostring(homeX) .. "_" .. tostring(homeY))
          local cmdId = "CMD_tradehome_" .. unitId .. "_" .. tostring(homeX) .. "_" .. tostring(homeY)
          table.insert(commands, {
            kind = "change_trade_home_city",
            command_id = cmdId,
            description = "Change trade unit home city of "
              .. unitId
              .. " to "
              .. homeName
              .. " (moves the caravan or cargo ship to that city as its new origin)",
            fixed_arguments = {
              unit_id = unitId,
              home_city_name = homeName,
              target_x = homeX,
              target_y = homeY,
            },
            affected_ids = { unitId },
            parameter_domains = {},
            runtime_status = "tested",
          })
        end
      end

      if routeIndex ~= nil and routeIndex >= 0 and not recalled then
        table.insert(commands, {
          kind = "recall_trader",
          command_id = "CMD_recalltrade_" .. unitId,
          description = "Recall trade unit "
            .. unitId
            .. " from its active trade route back toward home (does not clear the route instantly unless radio tech allows immediate recall)",
          fixed_arguments = { unit_id = unitId, immediate = false },
          affected_ids = { unitId },
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end
  return commands
end

function Civ5Ai_Snapshot.Build(playerID, options)
  options = options or {}
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local turn = Civ5Ai_Snapshot._GameTurn()
  local year = Civ5Ai_Snapshot._GameYear()
  local reason = options.reason or "turn_start"
  local mapWidth, mapHeight = Map.GetGridSize()
  local yourUnits = Civ5Ai_Snapshot._BuildYourUnits(playerID)
  local yourCities = Civ5Ai_Snapshot._BuildYourCities(playerID)
  local knownMap = Civ5Ai_Snapshot._BuildKnownMap(playerID, turn, yourUnits, yourCities)
  local yourEmpire = Civ5Ai_Snapshot._BuildYourEmpire(playerID, player, yourUnits)
  local legal = {}
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalResearch(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalProduction(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalGoldPurchases(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalFaithPurchases(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalFreeGreatPerson(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalPolicyBranches(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalPolicies(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalPromotions(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalMayaBonus(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalReligion(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalUnitPostures(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalUnitMissions(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalTradeUnits(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalCityRangeStrike(playerID, player)) do
    table.insert(legal, cmd)
  end
  for _, cmd in ipairs(Civ5Ai_Snapshot._BuildLegalCityStatus(playerID, player)) do
    table.insert(legal, cmd)
  end
  local diplomacySection = {
    relations = Civ5Ai_Diplo.BuildRelations(playerID),
    active_deals = Civ5Ai_Diplo.BuildActiveDeals(playerID),
    available_proposals = Civ5Ai_Diplo.BuildAvailableProposals(playerID),
    legal_trade_inventory = Civ5Ai_Diplo.BuildLegalTradeInventory(playerID),  -- DEAL_WIRE_CLEAR_V1
    pending_requests = Civ5Ai_Diplo.BuildPendingRequests(playerID),
    private_inbox = Civ5Ai_Chat.PrivateInbox(playerID),
  }
  for _, cmd in ipairs(Civ5Ai_Diplo.BuildLegalCommands(playerID, diplomacySection)) do
    table.insert(legal, cmd)
  end
  if Civ5Ai_Congress ~= nil and Civ5Ai_Congress.BuildLegalCommands ~= nil then
    for _, cmd in ipairs(Civ5Ai_Congress.BuildLegalCommands(playerID)) do
      table.insert(legal, cmd)
    end
  end
  local decisionReason = reason
  if #diplomacySection.pending_requests > 0 then
    decisionReason = "diplomacy_request"
  end
  local civType = GameInfo.Civilizations[player:GetCivilizationType()]
  local leaderType = GameInfo.Leaders[player:GetLeaderType()]
  local commandResults = Civ5Ai_Util.JsonArrayList()
  local diplomacyAlerts = Civ5Ai_Util.JsonArrayList()
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.TakePendingNotes ~= nil then
    for _, note in ipairs(Civ5Ai_Apply.TakePendingNotes(playerID) or {}) do
      local noteIds = note.affected_ids
      if noteIds == nil or (type(noteIds) == "table" and #noteIds == 0) then
        noteIds = Civ5Ai_Util.JsonArrayList()
      end
      table.insert(commandResults, {
        turn = note.turn or turn,
        kind = note.kind or "WAR_MOVE_BLOCKED",
        summary = note.summary or "",
        affected_ids = noteIds,
        actor_player_id = note.actor_player_id,
      })
      table.insert(diplomacyAlerts, {
        kind = note.kind or "WAR_MOVE_BLOCKED",
        severity = "warning",
        affected_ids = noteIds,
        text = note.summary or "",
        actor_player_id = note.actor_player_id,
      })
    end
  end
  for _, alert in ipairs(Civ5Ai_Snapshot._BuildVictoryAlerts(playerID)) do
    table.insert(diplomacyAlerts, alert)
  end
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.TakePendingCommandResults ~= nil then
    for _, result in ipairs(Civ5Ai_Apply.TakePendingCommandResults(playerID) or {}) do
      table.insert(commandResults, result)
    end
  end
  local combatPreviews = Civ5Ai_Snapshot._BuildCombatPreviews(playerID, player)
  local payload = {
    schema_version = "civ5ai-input/1",
    decision = {
      phase = "strategic_decision",
      player_id = Civ5Ai_Util.PlayerId(playerID),
      reason = decisionReason,
      turn = turn,
      year = year,
    },
    civ5 = {
      research_tech = yourEmpire.research.tech_id,
      yields = {
        science = yourEmpire.commerce.research.rate,
        culture = yourEmpire.commerce.culture.rate,
        faith = (yourEmpire.religion and yourEmpire.religion.faith) or 0,
        gold = yourEmpire.gold,
        -- UI-correct excess (GetExcessHappiness); not gross GetHappiness.
        happiness = (player.GetExcessHappiness ~= nil and (player:GetExcessHappiness() or 0))
          or ((player.GetHappiness and (player:GetHappiness() or 0) or 0)
            - (player.GetUnhappiness and (player:GetUnhappiness() or 0) or 0)),
      },
      map = {
        width = mapWidth,
        height = mapHeight,
        hex_layout = "odd-r",
        coords_note = "grid x,y; Y increases south",
      },
      settle_sites = Civ5Ai_Snapshot._BuildSettleSites(playerID),
      world_congress = Civ5Ai_Snapshot._BuildWorldCongress(playerID),
    },
    advciv = {
      default_unit_controller = Civ5Ai_Snapshot._UnitLeftoverController(playerID),
      fallback_policy = Civ5Ai_Snapshot._FallbackPolicy(playerID, player),
      recommendations = Civ5Ai_Util.JsonArrayList(),
    },
    personality = {
      civilization_id = civType and civType.Type or "CIVILIZATION_UNKNOWN",
      leader_id = leaderType and leaderType.Type or "LEADER_UNKNOWN",
      leader_name = Civ5Ai_Snapshot._LeaderDisplayName(player, leaderType),
      identity = Civ5Ai_Snapshot._LeaderDisplayName(player, leaderType),
    },
    game = Civ5Ai_Snapshot._BuildGameBlock(player, mapWidth, mapHeight),
    diplomacy = diplomacySection,
    history = {
      memory_summary = "",
      accepted_decisions = Civ5Ai_Util.JsonArrayList(),
      command_results = commandResults,
      diplomacy_events = Civ5Ai_Util.JsonArrayList(),
      public_events = Civ5Ai_Chat.VisibleEvents(playerID),
    },
    strategic_summary = {
      city_alerts = Civ5Ai_Util.JsonArrayList(),
      diplomacy_alerts = diplomacyAlerts,
      economy_alerts = Civ5Ai_Util.JsonArrayList(),
      military_alerts = Civ5Ai_Util.JsonArrayList(),
      resource_alerts = Civ5Ai_Util.JsonArrayList(),
      ratios = Civ5Ai_Util.JsonArrayList(),
      combat_previews = combatPreviews,
    },
    known_map = knownMap,
    known_other_cities = Civ5Ai_Snapshot._BuildKnownOtherCities(playerID),
    known_players = Civ5Ai_Snapshot._BuildKnownPlayers(playerID),
    visible_other_units = Civ5Ai_Snapshot._BuildVisibleOtherUnits(playerID),
    your_units = yourUnits,
    your_cities = yourCities,
    your_empire = yourEmpire,
    legal_commands = legal,
    notifications = Civ5Ai_Snapshot._BuildNotifications(player),
  }
  return Civ5Ai_Util.EncodeJsonObject(payload)
end
