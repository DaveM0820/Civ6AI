-- Civ6Ai fog snapshot + legal_commands probe (InGame host).
Civ6Ai_Snapshot = Civ6Ai_Snapshot or {}

function Civ6Ai_Snapshot._Int(value)
  local n = tonumber(value)
  if n == nil then
    return 0
  end
  if n >= 0 then
    return math.floor(n + 0.5)
  end
  return math.ceil(n - 0.5)
end

function Civ6Ai_Snapshot._NullableInt(value)
  if value == nil then
    return Civ6Ai_Util.JsonNull()
  end
  return Civ6Ai_Snapshot._Int(value)
end

function Civ6Ai_Snapshot._NullableId(value)
  if value == nil or value == "" then
    return Civ6Ai_Util.JsonNull()
  end
  return value
end

function Civ6Ai_Snapshot._LeaderName(playerID)
  local config = PlayerConfigurations[playerID]
  if config == nil then
    return "Leader"
  end
  local name = config:GetLeaderName()
  if name ~= nil and name ~= "" then
    return Locale.Lookup(name)
  end
  return "Leader"
end

function Civ6Ai_Snapshot._CivId(playerID)
  local config = PlayerConfigurations[playerID]
  if config == nil then
    return "CIVILIZATION_UNKNOWN"
  end
  return config:GetCivilizationTypeName()
end

function Civ6Ai_Snapshot._LeaderId(playerID)
  local config = PlayerConfigurations[playerID]
  if config == nil then
    return "LEADER_UNKNOWN"
  end
  return config:GetLeaderTypeName()
end

function Civ6Ai_Snapshot._GovernmentId(playerID)
  local player = Players[playerID]
  if player == nil then
    return "GOVERNMENT_CHIEFDOM"
  end
  local culture = player:GetCulture()
  if culture ~= nil and culture.GetCurrentGovernment ~= nil then
    local govIndex = culture:GetCurrentGovernment()
    if govIndex ~= nil and govIndex >= 0 and GameInfo ~= nil and GameInfo.Governments ~= nil then
      for row in GameInfo.Governments() do
        if row.Index == govIndex then
          return row.GovernmentType
        end
      end
    end
  end
  return "GOVERNMENT_CHIEFDOM"
end

function Civ6Ai_Snapshot._FaithYield(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local religion = player:GetReligion()
  if religion ~= nil and religion.GetFaithYield ~= nil then
    return Civ6Ai_Snapshot._Int(religion:GetFaithYield())
  end
  return 0
end

function Civ6Ai_Snapshot._Favor(playerID)
  local player = Players[playerID]
  if player == nil then
    return 0
  end
  local diplomacy = player:GetDiplomacy()
  if diplomacy ~= nil and diplomacy.GetFavor ~= nil then
    return Civ6Ai_Snapshot._Int(diplomacy:GetFavor())
  end
  return 0
end

function Civ6Ai_Snapshot._CurrentTech(playerID)
  local techs = Players[playerID]:GetTechs()
  if techs == nil then
    return nil
  end
  local idx = techs:GetResearchingTech()
  if idx == nil or idx < 0 then
    return nil
  end
  for row in GameInfo.Technologies() do
    if row.Index == idx then
      return row.TechnologyType
    end
  end
  return nil
end

function Civ6Ai_Snapshot._UnitTypeName(unit)
  local info = GameInfo.Units[unit:GetType()]
  if info == nil then
    return "UNIT_UNKNOWN"
  end
  return info.UnitType
end

function Civ6Ai_Snapshot._UnitWireId(unit)
  return "UNIT_" .. tostring(unit:GetID())
end

Civ6Ai_Snapshot.MAP_EXPORT_RADIUS = 12
Civ6Ai_Snapshot.MAX_MAP_PLOTS = 700

function Civ6Ai_Snapshot._GameYear()
  if Game ~= nil and Game.GetCalendar ~= nil then
    local cal = Game.GetCalendar()
    if cal ~= nil and cal.GetYear ~= nil then
      return cal:GetYear()
    end
  end
  return Game.GetCurrentGameTurn()
end

function Civ6Ai_Snapshot._TerrainTypeName(plot)
  local idx = plot:GetTerrainType()
  if GameInfo.Terrains ~= nil then
    for row in GameInfo.Terrains() do
      if row.Index == idx then
        return row.TerrainType
      end
    end
  end
  return "TERRAIN_UNKNOWN"
end

function Civ6Ai_Snapshot._FeatureTypeName(plot)
  local idx = plot:GetFeatureType()
  if idx == nil or idx < 0 then
    return nil
  end
  if GameInfo.Features ~= nil then
    for row in GameInfo.Features() do
      if row.Index == idx then
        return row.FeatureType
      end
    end
  end
  return nil
end

function Civ6Ai_Snapshot._ResourceTypeName(plot)
  local idx = plot:GetResourceType()
  if idx == nil or idx < 0 then
    return nil
  end
  if GameInfo.Resources ~= nil then
    for row in GameInfo.Resources() do
      if row.Index == idx then
        return row.ResourceType
      end
    end
  end
  return nil
end

function Civ6Ai_Snapshot._ImprovementTypeName(plot)
  local idx = plot:GetImprovementType()
  if idx == nil or idx < 0 then
    return nil
  end
  if GameInfo.Improvements ~= nil then
    for row in GameInfo.Improvements() do
      if row.Index == idx then
        return row.ImprovementType
      end
    end
  end
  return nil
end

function Civ6Ai_Snapshot._VisibilityChar(plot)
  if plot:IsMountain() or plot:IsNaturalWonder() then
    return "^"
  end
  if plot:IsHills() then
    return "#"
  end
  if plot:IsWater() then
    local terrain = Civ6Ai_Snapshot._TerrainTypeName(plot)
    if terrain == "TERRAIN_OCEAN" then
      return "o"
    end
    return "~"
  end
  return "."
end

function Civ6Ai_Snapshot._PlotOwnerPlayerId(plot)
  local owner = plot:GetOwner()
  if owner == nil or owner < 0 then
    return nil
  end
  return Civ6Ai_Util.PlayerId(owner)
end

function Civ6Ai_Snapshot._PlotCityWireId(plot)
  if Cities == nil or Cities.GetCityInPlot == nil then
    return nil
  end
  local city = Cities.GetCityInPlot(plot:GetX(), plot:GetY())
  if city == nil then
    return nil
  end
  return Civ6Ai_Production._WireCityId(city)
end

function Civ6Ai_Snapshot._CollectMapAnchors(playerID, yourUnits, yourCities)
  local anchors = {}
  local function addAnchor(x, y)
    if x == nil or y == nil or x < 0 or y < 0 then
      return
    end
    table.insert(anchors, {x = x, y = y})
  end
  for _, unit in ipairs(yourUnits) do
    local coords = Civ6Ai_Util.ParsePlotId(unit.plot_id)
    if coords ~= nil then
      addAnchor(coords.x, coords.y)
    end
  end
  for _, city in ipairs(yourCities) do
    local coords = Civ6Ai_Util.ParsePlotId(city.plot_id)
    if coords ~= nil then
      addAnchor(coords.x, coords.y)
    end
  end
  if #anchors == 0 then
    local player = Players[playerID]
    if player ~= nil and player:GetCities() ~= nil then
      local capital = player:GetCities():GetCapitalCity()
      if capital ~= nil then
        addAnchor(capital:GetX(), capital:GetY())
      end
    end
  end
  return anchors
end

function Civ6Ai_Snapshot._RiverEdgeNeighbor(plot, direction)
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

function Civ6Ai_Snapshot._RiverEdges(plot)
  local edges = {}
  if plot == nil then
    return edges
  end
  local checks = {}
  if DirectionTypes ~= nil then
  if DirectionTypes.DIRECTION_NORTHEAST ~= nil and plot.IsNEOfRiver ~= nil then
    table.insert(checks, {plot.IsNEOfRiver, DirectionTypes.DIRECTION_NORTHEAST})
  end
  if DirectionTypes.DIRECTION_WEST ~= nil and plot.IsWOfRiver ~= nil then
    table.insert(checks, {plot.IsWOfRiver, DirectionTypes.DIRECTION_WEST})
  end
  if DirectionTypes.DIRECTION_NORTHWEST ~= nil and plot.IsNWOfRiver ~= nil then
    table.insert(checks, {plot.IsNWOfRiver, DirectionTypes.DIRECTION_NORTHWEST})
  end
  end
  for _, entry in ipairs(checks) do
    local isRiverFn = entry[1]
    local direction = entry[2]
    if isRiverFn ~= nil and direction ~= nil and isRiverFn(plot) then
      local neighbor = Civ6Ai_Snapshot._RiverEdgeNeighbor(plot, direction)
      if neighbor ~= nil then
        table.insert(edges, neighbor)
      end
    end
  end
  if #edges == 0 and plot.IsRiver ~= nil and plot:IsRiver() then
    table.insert(edges, {dx = 0, dy = -1})
  end
  return edges
end

function Civ6Ai_Snapshot._BuildPlotRecord(plot, playerID, turn, vis)
  local x = plot:GetX()
  local y = plot:GetY()
  local index = plot:GetIndex()
  local visible = vis:IsVisible(index)
  local knowledge = visible and "visible" or "remembered"
  local water = plot:IsWater()
  local terrain_id = Civ6Ai_Snapshot._TerrainTypeName(plot)
  local fresh_water = plot:IsFreshWater() or plot:IsRiver()
  local river_edges = Civ6Ai_Snapshot._RiverEdges(plot)
  return {
    plot_id = Civ6Ai_Util.PlotId(x, y),
    x = x,
    y = y,
    knowledge = knowledge,
    last_seen_turn = visible and turn or Civ6Ai_Util.JsonNull(),
    area_id = "AREA_0",
    terrain_id = terrain_id,
    water = water,
    hills = plot:IsHills(),
    peak = plot:IsMountain() or plot:IsNaturalWonder(),
    fresh_water = fresh_water,
    river_edges = river_edges,
    revealed_owner_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._PlotOwnerPlayerId(plot)),
    feature_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._FeatureTypeName(plot)),
    improvement_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._ImprovementTypeName(plot)),
    route_id = Civ6Ai_Util.JsonNull(),
    resource_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._ResourceTypeName(plot)),
    yields = {food = 0, production = 0, commerce = 0},
    defense_percent = 0,
    city_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._PlotCityWireId(plot)),
    worked_by_city_id = Civ6Ai_Util.JsonNull(),
    visible_stack_ids = {},
  }
end

function Civ6Ai_Snapshot._BuildKnownMap(playerID, turn, yourUnits, yourCities)
  local vis = PlayersVisibility[playerID]
  local mapWidth, mapHeight = Map.GetGridSize()
  local plots = {}
  local visibility_grid = {}
  if vis == nil then
    return {
      format = "plot-grid-v1",
      visibility_mode = "player_visible",
      plots = plots,
      areas = {},
      frontiers = {},
      visible_stacks = {},
      visibility_grid = visibility_grid,
      image = {
        attached = false,
        format = "png-grid-v1",
        width = mapWidth,
        height = mapHeight,
        legend = {},
        label_ids = {},
      },
    }
  end
  local anchors = Civ6Ai_Snapshot._CollectMapAnchors(playerID, yourUnits, yourCities)
  local minX, minY = mapWidth, mapHeight
  local maxX, maxY = 0, 0
  for _, anchor in ipairs(anchors) do
    minX = math.min(minX, anchor.x - Civ6Ai_Snapshot.MAP_EXPORT_RADIUS)
    minY = math.min(minY, anchor.y - Civ6Ai_Snapshot.MAP_EXPORT_RADIUS)
    maxX = math.max(maxX, anchor.x + Civ6Ai_Snapshot.MAP_EXPORT_RADIUS)
    maxY = math.max(maxY, anchor.y + Civ6Ai_Snapshot.MAP_EXPORT_RADIUS)
  end
  if #anchors == 0 then
    minX = 0
    minY = 0
    maxX = math.min(mapWidth - 1, Civ6Ai_Snapshot.MAP_EXPORT_RADIUS * 2)
    maxY = math.min(mapHeight - 1, Civ6Ai_Snapshot.MAP_EXPORT_RADIUS * 2)
  end
  minX = math.max(0, minX)
  minY = math.max(0, minY)
  maxX = math.min(mapWidth - 1, maxX)
  maxY = math.min(mapHeight - 1, maxY)
  for y = minY, maxY do
    local row = ""
    for x = minX, maxX do
      local plot = Map.GetPlot(x, y)
      if plot ~= nil and vis:IsRevealed(plot:GetIndex()) then
        if #plots < Civ6Ai_Snapshot.MAX_MAP_PLOTS then
          table.insert(plots, Civ6Ai_Snapshot._BuildPlotRecord(plot, playerID, turn, vis))
        end
        row = row .. Civ6Ai_Snapshot._VisibilityChar(plot)
      else
        row = row .. "?"
      end
    end
    table.insert(visibility_grid, row)
  end
  return {
    format = "plot-grid-v1",
    visibility_mode = "player_visible",
    plots = plots,
    areas = {},
    frontiers = {},
    visible_stacks = {},
    visibility_grid = visibility_grid,
    viewport = {
      x0 = minX,
      y0 = minY,
      width = maxX - minX + 1,
      height = maxY - minY + 1,
    },
    image = {
      attached = false,
      format = "png-grid-v1",
      width = mapWidth,
      height = mapHeight,
      legend = {},
      label_ids = {},
      viewport = {
        x0 = minX,
        y0 = minY,
        width = maxX - minX + 1,
        height = maxY - minY + 1,
      },
    },
  }
end

function Civ6Ai_Snapshot._EmptyAmounts()
  return {current = 0, maximum = 0, change_per_turn = 0}
end

function Civ6Ai_Snapshot._EmptyCommerceItem()
  return {percent = 0, rate = 0}
end

function Civ6Ai_Snapshot._PlotIsCoastal(x, y)
  if Map == nil or Map.GetPlot == nil then
    return false
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil or plot.IsCoastalLand == nil then
    return false
  end
  return plot:IsCoastalLand() == true
end

function Civ6Ai_Snapshot._BuildYourCities(playerID)
  local player = Players[playerID]
  if player == nil then
    return {}
  end
  local cities = player:GetCities()
  if cities == nil then
    return {}
  end
  local out = {}
  for _, city in cities:Members() do
    local x = city:GetX()
    local y = city:GetY()
    local name = Locale.Lookup(city:GetName())
    local productionId, productionProgress, productionCost, productionPerTurn, productionTurns =
      Civ6Ai_Production._GetCityProductionState(city)
    table.insert(out, {
      city_id = Civ6Ai_Production._WireCityId(city),
      name = name,
      plot_id = Civ6Ai_Util.PlotId(x, y),
      area_id = "AREA_0",
      is_capital = city.IsCapital ~= nil and city:IsCapital() or false,
      is_coastal = Civ6Ai_Snapshot._PlotIsCoastal(x, y),
      population = Civ6Ai_Snapshot._Int(city:GetPopulation()),
      food = Civ6Ai_Snapshot._EmptyAmounts(),
      production = {
        item_id = Civ6Ai_Snapshot._NullableId(productionId),
        progress = Civ6Ai_Snapshot._Int(productionProgress),
        cost = Civ6Ai_Snapshot._Int(productionCost),
        production_per_turn = Civ6Ai_Snapshot._Int(productionPerTurn),
        estimated_turns_remaining = Civ6Ai_Snapshot._NullableInt(productionTurns),
      },
      production_queue = {},
      yields = {food = 0, production = 0, commerce = 0},
      commerce = {
        gold = Civ6Ai_Snapshot._EmptyCommerceItem(),
        research = Civ6Ai_Snapshot._EmptyCommerceItem(),
        culture = Civ6Ai_Snapshot._EmptyCommerceItem(),
        espionage = Civ6Ai_Snapshot._EmptyCommerceItem(),
      },
      buildings = {},
      garrison_unit_ids = {},
      worked_plot_ids = {},
      automation = {citizens = false, production = true},
      culture = Civ6Ai_Snapshot._EmptyAmounts(),
      great_people = Civ6Ai_Snapshot._EmptyAmounts(),
      happiness = {positive = 0, negative = 0, net = 0},
      health = {positive = 0, negative = 0, net = 0},
      defense = {percent = 0, bombard_damage = 0},
      maintenance = 0,
      occupation_turns = 0,
      religions = {},
      specialists = {},
      trade_routes = {},
      corporations = {},
    })
  end
  return out
end

function Civ6Ai_Snapshot._BuildUnitCounts(playerID)
  local player = Players[playerID]
  local counts = {
    total = 0,
    military = 0,
    settlers = 0,
    idle = 0,
    workers = 0,
    missionaries = 0,
    spies = 0,
    great_people = 0,
    upgradeable = 0,
  }
  if player == nil then
    return counts
  end
  for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
    counts.total = counts.total + 1
    if Civ6Ai_Snapshot._UnitNeedsOrders(unit) then
      counts.idle = counts.idle + 1
    end
    local typeName = Civ6Ai_Snapshot._UnitTypeName(unit)
    if typeName == "UNIT_SETTLER" then
      counts.settlers = counts.settlers + 1
    end
    if typeName ~= nil and (
      string.find(typeName, "WARRIOR") ~= nil
      or string.find(typeName, "SPEARMAN") ~= nil
      or string.find(typeName, "ARCHER") ~= nil
      or string.find(typeName, "HORSEMAN") ~= nil
    ) then
      counts.military = counts.military + 1
    end
  end
  return counts
end

function Civ6Ai_Snapshot._BuildYourEmpire(playerID, player)
  local treasury = player:GetTreasury()
  local techs = player:GetTechs()
  local culture = player:GetCulture()
  local gold = Civ6Ai_Snapshot._Int(treasury:GetGoldBalance())
  local gpt = Civ6Ai_Snapshot._Int(treasury:GetGoldYield() - treasury:GetTotalMaintenance())
  local research = {
    tech_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._CurrentTech(playerID)),
    progress = 0,
    cost = 0,
    research_per_turn = 0,
    estimated_turns_remaining = Civ6Ai_Util.JsonNull(),
    queue = {},
    known_tech_ids = {},
  }
  if techs ~= nil then
    local idx = techs:GetResearchingTech()
    research.research_per_turn = Civ6Ai_Snapshot._Int(techs:GetScienceYield())
    if idx ~= nil and idx >= 0 then
      research.progress = Civ6Ai_Snapshot._Int(techs:GetResearchProgress(idx))
      research.cost = Civ6Ai_Snapshot._Int(techs:GetResearchCost(idx))
      local remaining = research.cost - research.progress
      if research.research_per_turn > 0 and remaining > 0 then
        research.estimated_turns_remaining = math.ceil(remaining / research.research_per_turn)
      end
    end
  end
  local commerce = {
    gold = {percent = 0, rate = Civ6Ai_Snapshot._Int(treasury:GetGoldYield())},
    research = {percent = 100, rate = research.research_per_turn},
    culture = {percent = 0, rate = 0},
    espionage = {percent = 0, rate = 0},
  }
  if culture ~= nil then
    commerce.culture.rate = Civ6Ai_Snapshot._Int(culture:GetCultureYield())
  end
  return {
    team_id = "TEAM_" .. tostring(player:GetTeam()),
    score = Civ6Ai_Snapshot._Int(player:GetScore()),
    gold = gold,
    gold_per_turn = gpt,
    research = research,
    commerce = commerce,
    unit_counts = Civ6Ai_Snapshot._BuildUnitCounts(playerID),
    anarchy_turns = 0,
    golden_age_turns = 0,
    war_weariness = 0,
    civics = {},
    costs = {
      city_maintenance = Civ6Ai_Snapshot._Int(treasury:GetTotalMaintenance()),
      civic_upkeep = 0,
      inflation = 0,
      unit_cost = 0,
      unit_supply = 0,
    },
    religion = {
      state_religion_id = Civ6Ai_Util.JsonNull(),
      convertible_religion_ids = {},
      conversion_timer = 0,
    },
    resources = {},
    victory_progress = {},
  }
end

function Civ6Ai_Snapshot._BuildKnownPlayers(playerID)
  local player = Players[playerID]
  if player == nil then
    return {}
  end
  local diplomacy = player:GetDiplomacy()
  if diplomacy == nil then
    return {}
  end
  local out = {}
  for otherID = 0, 63 do
    if otherID ~= playerID and Players[otherID] ~= nil and Players[otherID]:IsAlive() then
      if diplomacy.HasMet ~= nil and diplomacy:HasMet(otherID) then
        local other = Players[otherID]
        local attitude = "ATTITUDE_NEUTRAL"
        if diplomacy.GetAttitude ~= nil then
          local raw = diplomacy:GetAttitude(otherID)
          if raw ~= nil then
            attitude = "ATTITUDE_" .. tostring(raw)
          end
        end
        table.insert(out, {
          player_id = Civ6Ai_Util.PlayerId(otherID),
          leader_id = Civ6Ai_Snapshot._LeaderId(otherID),
          leader_name = Civ6Ai_Snapshot._LeaderName(otherID),
          civilization_id = Civ6Ai_Snapshot._CivId(otherID),
          team_id = "TEAM_" .. tostring(other:GetTeam()),
          score = Civ6Ai_Snapshot._Int(other:GetScore()),
          known_capital_city_id = Civ6Ai_Util.JsonNull(),
          known_tech_ids = {},
          known_civic_ids = {},
          known_religion_id = Civ6Ai_Util.JsonNull(),
          land = Civ6Ai_Util.JsonNull(),
          population = Civ6Ai_Util.JsonNull(),
          power = Civ6Ai_Util.JsonNull(),
          relation = {
            met = true,
            at_war = diplomacy:IsAtWarWith(otherID),
            open_borders = false,
            defensive_pact = false,
            vassal = false,
            attitude_id = attitude,
            attitude_value = 0,
          },
        })
      end
    end
  end
  return out
end

function Civ6Ai_Snapshot._MapWrap()
  if Map.IsWrapX ~= nil and Map.IsWrapY ~= nil then
    return Map.IsWrapX(), Map.IsWrapY()
  end
  return false, false
end

function Civ6Ai_Snapshot._IsNetworkMultiplayer()
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    return GameConfiguration.IsNetworkMultiplayer()
  end
  return false
end

function Civ6Ai_Snapshot._BuildGameBlock()
  local mapWidth, mapHeight = Map.GetGridSize()
  local wrapX, wrapY = Civ6Ai_Snapshot._MapWrap()
  return {
    map_width = mapWidth,
    map_height = mapHeight,
    wrap_x = wrapX,
    wrap_y = wrapY,
    era_id = "ERA_UNKNOWN",
    game_speed_id = "GAMESPEED_STANDARD",
    difficulty_id = "HANDICAP_STANDARD",
    world_size_id = "WORLDSIZE_STANDARD",
    calendar_id = "CALENDAR_DEFAULT",
    climate_id = "CLIMATE_TEMPERATE",
    sea_level_id = "SEALEVEL_MEDIUM",
    start_era_id = "ERA_UNKNOWN",
    map_script = "Unknown",
    max_turns = Civ6Ai_Util.JsonNull(),
    network_multiplayer = Civ6Ai_Snapshot._IsNetworkMultiplayer(),
    options = {},
    victory_ids = {},
  }
end

function Civ6Ai_Snapshot._EmptyStrategicSummary()
  return {
    city_alerts = Civ6Ai_Util.JsonArrayList(),
    economy_alerts = Civ6Ai_Util.JsonArrayList(),
    military_alerts = Civ6Ai_Util.JsonArrayList(),
    diplomacy_alerts = Civ6Ai_Util.JsonArrayList(),
    resource_alerts = Civ6Ai_Util.JsonArrayList(),
    ratios = Civ6Ai_Util.JsonArrayList(),
  }
end

function Civ6Ai_Snapshot._MakeAlert(section, severity, text, affectedIds)
  return {
    kind = "ALERT_" .. string.upper(section),
    severity = severity,
    affected_ids = affectedIds or {},
    text = string.sub(text, 1, 200),
  }
end

function Civ6Ai_Snapshot._NotificationSection(typeName)
  local upper = string.upper(tostring(typeName or ""))
  if string.find(upper, "DIPLO") or string.find(upper, "DEAL") or string.find(upper, "GOSSIP") then
    return "diplomacy"
  end
  if string.find(upper, "CITY") or string.find(upper, "LOYALTY") or string.find(upper, "DISTRICT") then
    return "city"
  end
  if string.find(upper, "GOLD") or string.find(upper, "TRADE") or string.find(upper, "BANKRUPT") then
    return "economy"
  end
  if string.find(upper, "RESOURCE") or string.find(upper, "LUXURY") or string.find(upper, "STRATEGIC") then
    return "resource"
  end
  return "military"
end

function Civ6Ai_Snapshot._AlertBucket(section)
  if section == "city" then
    return "city_alerts"
  end
  if section == "economy" then
    return "economy_alerts"
  end
  if section == "diplomacy" then
    return "diplomacy_alerts"
  end
  if section == "resource" then
    return "resource_alerts"
  end
  return "military_alerts"
end

function Civ6Ai_Snapshot._NotificationText(entry)
  if entry == nil then
    return ""
  end
  local methods = {"GetText", "GetSummary", "GetBriefText"}
  for _, method in ipairs(methods) do
    if entry[method] ~= nil then
      local ok, value = pcall(function()
        return entry[method](entry)
      end)
      if ok and value ~= nil and value ~= "" then
        return Locale.Lookup(value)
      end
    end
  end
  return ""
end

function Civ6Ai_Snapshot._NotificationTypeName(entry)
  if entry == nil or entry.GetType == nil then
    return "NOTIFICATION_UNKNOWN"
  end
  local ok, typeIdx = pcall(function()
    return entry:GetType()
  end)
  if not ok or typeIdx == nil then
    return "NOTIFICATION_UNKNOWN"
  end
  if GameInfo.Notifications ~= nil then
    for row in GameInfo.Notifications() do
      if row.Index == typeIdx or row.Hash == typeIdx then
        if row.NotificationType ~= nil then
          return row.NotificationType
        end
        if row.Type ~= nil then
          return row.Type
        end
      end
    end
  end
  return tostring(typeIdx)
end

function Civ6Ai_Snapshot._MergeNotificationAlerts(playerID, summary)
  if NotificationManager == nil then
    return summary
  end
  local list = NotificationManager.GetList(playerID)
  if list == nil then
    return summary
  end
  local seen = {}
  for _, nid in ipairs(list) do
    local entry = NotificationManager.Find(playerID, nid)
    if entry ~= nil and entry.IsDismissed ~= nil and not entry:IsDismissed() then
      local text = Civ6Ai_Snapshot._NotificationText(entry)
      if text ~= "" and seen[text] == nil then
        seen[text] = true
        local typeName = Civ6Ai_Snapshot._NotificationTypeName(entry)
        local section = Civ6Ai_Snapshot._NotificationSection(typeName)
        local bucket = Civ6Ai_Snapshot._AlertBucket(section)
        local severity = "info"
        if entry.GetEndTurnBlocking ~= nil then
          local ok, blocking = pcall(function()
            return entry:GetEndTurnBlocking()
          end)
          if ok and blocking ~= nil and blocking ~= 0 then
            severity = "critical"
          end
        end
        table.insert(summary[bucket], Civ6Ai_Snapshot._MakeAlert(section, severity, text, {}))
      end
    end
  end
  return summary
end

function Civ6Ai_Snapshot._DeriveStrategicSummary(playerID, yourCities, yourUnits, empire, diplomacy)
  local summary = Civ6Ai_Snapshot._EmptyStrategicSummary()
  local unitCounts = empire.unit_counts or {}
  local idle = tonumber(unitCounts.idle) or 0
  if idle > 0 then
    table.insert(summary.military_alerts, Civ6Ai_Snapshot._MakeAlert(
      "military", "warning", tostring(idle) .. " owned units need orders", {}))
  end
  local gold = tonumber(empire.gold) or 0
  local gpt = tonumber(empire.gold_per_turn) or 0
  if gold < 0 then
    table.insert(summary.economy_alerts, Civ6Ai_Snapshot._MakeAlert(
      "economy", "critical", "Treasury is negative", {}))
  elseif gpt < 0 then
    table.insert(summary.economy_alerts, Civ6Ai_Snapshot._MakeAlert(
      "economy", "warning", "Net income is negative", {}))
  end
  local military = tonumber(unitCounts.military) or 0
  if military > 0 and yourCities ~= nil then
    table.insert(summary.ratios, {
      kind = "MILITARY_PER_CITY",
      numerator = military,
      denominator = math.max(1, #yourCities),
      basis = "military units per owned city",
    })
  end
  if yourUnits ~= nil and #yourUnits > 0 then
    local needing = 0
    for _, unit in ipairs(yourUnits) do
      if unit.needs_orders then
        needing = needing + 1
      end
    end
    table.insert(summary.ratios, {
      kind = "UNITS_NEEDING_ORDERS",
      numerator = needing,
      denominator = #yourUnits,
      basis = "owned units needing orders",
    })
  end
  if diplomacy ~= nil and diplomacy.pending_requests ~= nil and #diplomacy.pending_requests > 0 then
    table.insert(summary.diplomacy_alerts, Civ6Ai_Snapshot._MakeAlert(
      "diplomacy", "critical", "Pending diplomacy requests require a response", {}))
  end
  return Civ6Ai_Snapshot._MergeNotificationAlerts(playerID, summary)
end

function Civ6Ai_Snapshot._BuildStrategicSummary(playerID, yourCities, yourUnits, empire, diplomacy)
  return Civ6Ai_Snapshot._DeriveStrategicSummary(playerID, yourCities, yourUnits, empire, diplomacy)
end

function Civ6Ai_Snapshot._EnrichLegalCommand(command)
  command.fixed_arguments = command.fixed_arguments or {}
  command.parameter_domains = command.parameter_domains or {}
  if command.affected_ids == nil then
    local affected = {}
    local fixed = command.fixed_arguments
    if fixed.unit_id ~= nil then
      table.insert(affected, fixed.unit_id)
    end
    if fixed.city_id ~= nil then
      table.insert(affected, fixed.city_id)
    end
    command.affected_ids = affected
  end
  if command.runtime_status == nil then
    command.runtime_status = "implemented_untested"
  end
  return command
end

function Civ6Ai_Snapshot._IterateUnits(playerUnits)
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
  if playerUnits.Units ~= nil then
    for unit in playerUnits:Units() do
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

function Civ6Ai_Snapshot._UnitNeedsOrders(unit)
  if unit == nil or unit:GetX() == -9999 then
    return false
  end
  return unit:GetMovesRemaining() > 0
end

function Civ6Ai_Snapshot._BuildYourUnits(playerID)
  local player = Players[playerID]
  if player == nil then
    return {}
  end
  local units = {}
  for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
    local x = unit:GetX()
    local y = unit:GetY()
    local moves = unit:GetMovesRemaining()
    local maxMoves = unit:GetMaxMoves()
    local needsOrders = Civ6Ai_Snapshot._UnitNeedsOrders(unit)
    table.insert(units, {
      unit_id = Civ6Ai_Snapshot._UnitWireId(unit),
      unit_type_id = Civ6Ai_Snapshot._UnitTypeName(unit),
      unit_class_id = "UNITCLASS_UNKNOWN",
      domain_id = "DOMAIN_LAND",
      plot_id = Civ6Ai_Util.PlotId(x, y),
      health = {current = 100, maximum = 100, change_per_turn = 0},
      strength = {current = 0, maximum = 0, change_per_turn = 0},
      movement = {current = moves, maximum = maxMoves, change_per_turn = 0},
      level = 1,
      experience = 0,
      promotion_ids = {},
      activity_id = "ACTIVITY_UNKNOWN",
      mission_queue = {},
      unit_ai_role = "UNITAI_UNKNOWN",
      cargo_unit_ids = {},
      can_act = needsOrders,
      needs_orders = needsOrders,
      upgrade_options = {},
    })
  end
  return units
end

function Civ6Ai_Snapshot._AddAdjacentMoveCommands(commands, unit, unitId)
  local x = unit:GetX()
  local y = unit:GetY()
  for direction = 0, 5 do
    local adjPlot = Map.GetAdjacentPlot(x, y, direction)
    if adjPlot ~= nil then
      local ax = adjPlot:GetX()
      local ay = adjPlot:GetY()
      if UnitManager.CanStartOperation(unit, UnitOperationTypes.MOVE_TO, adjPlot, true) then
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_move_" .. unitId .. "_" .. tostring(ax) .. "_" .. tostring(ay),
          kind = "move_unit",
          fixed_arguments = {unit_id = unitId, target_x = ax, target_y = ay},
        }))
      end
    end
  end
end

function Civ6Ai_Snapshot._AddProductionCommands(commands, playerID)
  if Civ6Ai_Production == nil or Players[playerID] == nil then
    return
  end
  local cities = Players[playerID]:GetCities()
  if cities == nil then
    return
  end
  local candidates = {
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "UNIT_SCOUT",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "BUILDING_MONUMENT",
    "BUILDING_GRANARY",
  }
  for _, city in cities:Members() do
    local cityId = Civ6Ai_Production._WireCityId(city)
    for _, buildId in ipairs(candidates) do
      if Civ6Ai_Production._CanQueueBuild(city, buildId) then
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_prod_" .. buildId .. "_" .. cityId,
          kind = "queue_production",
          fixed_arguments = {city_id = cityId, build_id = buildId},
        }))
      end
      if #commands >= 80 then
        return
      end
    end
  end
end

function Civ6Ai_Snapshot._BuildLegalCommands(playerID, playerLabel)
  local commands = {}
  Civ6Ai_Snapshot._AddProductionCommands(commands, playerID)
  if Civ6Ai_Config.IsSeatExperiment() then
    local cityId, buildId = Civ6Ai_Production.FindExperimentTarget(playerID)
    if buildId ~= nil and cityId ~= nil then
      table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
        command_id = "CMD_exp_prod_" .. buildId .. "_" .. cityId,
        kind = "queue_production",
        fixed_arguments = {city_id = cityId, build_id = buildId},
      }))
    end
  end
  local player = Players[playerID]
  if player ~= nil then
    for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
      if Civ6Ai_Snapshot._UnitNeedsOrders(unit) then
        local unitId = Civ6Ai_Snapshot._UnitWireId(unit)
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_skip_" .. unitId,
          kind = "unit_skip",
          fixed_arguments = {unit_id = unitId},
        }))
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_fortify_" .. unitId,
          kind = "unit_posture_fortify",
          fixed_arguments = {unit_id = unitId},
        }))
        if GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
          local foundOp = GameInfo.UnitOperations["UNITOPERATION_FOUND_CITY"]
          if foundOp ~= nil and UnitManager.CanStartOperation(unit, foundOp.Hash, nil, true) then
            table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
              command_id = "CMD_found_" .. unitId,
              kind = "found_city",
              fixed_arguments = {unit_id = unitId},
            }))
          end
        end
        Civ6Ai_Snapshot._AddAdjacentMoveCommands(commands, unit, unitId)
        if #commands >= 48 then
          break
        end
      end
    end
  end
  local techs = player and player:GetTechs()
  if techs ~= nil then
    for row in GameInfo.Technologies() do
      if techs:CanResearch(row.Index) and not techs:HasTech(row.Index) then
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_research_" .. row.TechnologyType,
          kind = "set_research_tech",
          fixed_arguments = {tech_id = row.TechnologyType},
        }))
        if #commands >= 56 then
          break
        end
      end
    end
  end
  return commands
end

function Civ6Ai_Snapshot.Build(playerID, options)
  options = options or {}
  local player = Players[playerID]
  local playerLabel = Civ6Ai_Util.PlayerId(playerID)
  local turn = Game.GetCurrentGameTurn()
  local year = Civ6Ai_Snapshot._GameYear()
  local reason = "turn_start"
  if options.reason ~= nil and options.reason ~= "" then
    reason = tostring(options.reason)
  end
  local yourUnits = Civ6Ai_Snapshot._BuildYourUnits(playerID)
  local yourCities = Civ6Ai_Snapshot._BuildYourCities(playerID)
  local legal = Civ6Ai_Snapshot._BuildLegalCommands(playerID, playerLabel)
  local mapWidth, mapHeight = Map.GetGridSize()
  local techId = Civ6Ai_Snapshot._CurrentTech(playerID)
  local sessionId = Civ6Ai_Bridge.SessionId()
  local yourEmpire = Civ6Ai_Snapshot._BuildYourEmpire(playerID, player)
  local civ6Block = {
    session_id = sessionId,
    research_tech = Civ6Ai_Snapshot._NullableId(techId),
    government_id = Civ6Ai_Snapshot._GovernmentId(playerID),
    yields = {
      science = yourEmpire.commerce.research.rate,
      culture = yourEmpire.commerce.culture.rate,
      faith = Civ6Ai_Snapshot._FaithYield(playerID),
      favor = Civ6Ai_Snapshot._Favor(playerID),
    },
    map = {
      width = mapWidth,
      height = mapHeight,
      hex_layout = "odd-r",
      coords_note = "grid x,y; Y increases south",
    },
  }
  if Civ6Ai_Config.IsSeatExperiment() then
    local experimentCityId, experimentBuildId = Civ6Ai_Production.FindExperimentTarget(playerID)
    civ6Block.experiment_city_id = Civ6Ai_Snapshot._NullableId(experimentCityId)
    civ6Block.experiment_build_id = Civ6Ai_Snapshot._NullableId(experimentBuildId)
  end
  local privateInbox = Civ6Ai_Util.JsonArrayList()
  if Civ6Ai_Chat ~= nil and Civ6Ai_Chat.GetPrivateInbox ~= nil then
    for _, message in ipairs(Civ6Ai_Chat.GetPrivateInbox(playerID)) do
      table.insert(privateInbox, message)
    end
  end
  local publicEvents = Civ6Ai_Util.JsonArrayList()
  if Civ6Ai_Chat ~= nil and Civ6Ai_Chat.GetPublicEvents ~= nil then
    for _, event in ipairs(Civ6Ai_Chat.GetPublicEvents()) do
      table.insert(publicEvents, event)
    end
  end
  local diplomacyBlock = {
    relations = Civ6Ai_Util.JsonArrayList(),
    active_deals = Civ6Ai_Util.JsonArrayList(),
    pending_requests = Civ6Ai_Util.JsonArrayList(),
    available_proposals = Civ6Ai_Util.JsonArrayList(),
    legal_trade_inventory = Civ6Ai_Util.JsonArrayList(),
    private_inbox = privateInbox,
  }
  local strategicSummary = Civ6Ai_Snapshot._BuildStrategicSummary(
    playerID, yourCities, yourUnits, yourEmpire, diplomacyBlock)
  local payload = {
    schema_version = "civ6ai-input/1",
    decision = {
      turn = turn,
      year = year,
      phase = "strategic_decision",
      player_id = playerLabel,
      reason = reason,
    },
    personality = {
      identity = Civ6Ai_Snapshot._LeaderName(playerID),
      leader_id = Civ6Ai_Snapshot._LeaderId(playerID),
      leader_name = Civ6Ai_Snapshot._LeaderName(playerID),
      civilization_id = Civ6Ai_Snapshot._CivId(playerID),
    },
    game = Civ6Ai_Snapshot._BuildGameBlock(),
    your_empire = yourEmpire,
    your_cities = yourCities,
    your_units = yourUnits,
    known_map = Civ6Ai_Snapshot._BuildKnownMap(playerID, turn, yourUnits, yourCities),
    known_players = Civ6Ai_Snapshot._BuildKnownPlayers(playerID),
    known_other_cities = Civ6Ai_Util.JsonArrayList(),
    visible_other_units = Civ6Ai_Util.JsonArrayList(),
    diplomacy = diplomacyBlock,
    strategic_summary = strategicSummary,
    history = {
      accepted_decisions = Civ6Ai_Util.JsonArrayList(),
      command_results = Civ6Ai_Util.JsonArrayList(),
      public_events = publicEvents,
      diplomacy_events = Civ6Ai_Util.JsonArrayList(),
    },
    advciv = {
      default_unit_controller = "native",
      fallback_policy = "Firaxis native AI handles unmoved units after LLM apply.",
      recommendations = Civ6Ai_Util.JsonArrayList(),
    },
    legal_commands = legal,
    civ6 = civ6Block,
  }
  return Civ6Ai_Util.EncodeJsonObject(payload), legal
end

function Civ6Ai_Snapshot.EmpireTelemetry(playerID)
  local player = Players[playerID]
  if player == nil then
    return {}
  end
  local gold = 0
  local gpt = 0
  local science = 0
  local cities = 0
  local unitsWithMoves = 0
  if player:GetTreasury() ~= nil then
    gold = player:GetTreasury():GetGoldBalance()
    gpt = player:GetTreasury():GetGoldYield()
  end
  if player:GetTechs() ~= nil then
    science = player:GetTechs():GetScienceYield()
  end
  local citiesTable = player:GetCities()
  if citiesTable ~= nil then
    cities = citiesTable:GetCount()
  end
  local units = player:GetUnits()
  if units ~= nil then
    for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(units)) do
      if Civ6Ai_Snapshot._UnitNeedsOrders(unit) then
        unitsWithMoves = unitsWithMoves + 1
      end
    end
  end
  return {
    gold = gold,
    gold_per_turn = gpt,
    science = science,
    cities = cities,
    units_with_moves = unitsWithMoves,
  }
end
