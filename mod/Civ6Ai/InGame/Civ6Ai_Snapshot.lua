-- Civ6Ai fog snapshot + legal_commands probe (InGame host).
Civ6Ai_Snapshot = Civ6Ai_Snapshot or {}

-- Active build priorities (synced game properties set by Civ6Ai_Orders).
function Civ6Ai_Snapshot._Priorities(playerID)
  local out = Civ6Ai_Util.JsonArrayList()
  for id = 1, 24 do
    local ok, value = pcall(function()
      return Game:GetProperty("CIV6AI_PRIO_" .. tostring(playerID) .. "_" .. tostring(id))
    end)
    local level = ok and tonumber(value) or nil
    if level ~= nil and level >= 1 and level <= 3 then
      out[#out + 1] = { id = id, level = math.floor(level) }
    end
  end
  return out
end

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

-- Civ6 uses -1 for "this layer does not exist" (a city with no walls).
-- Counters the schema requires to be >= 0 must not leave the snapshot as -1.
function Civ6Ai_Snapshot._NonNegative(value)
  local n = tonumber(value)
  if n == nil or n < 0 then
    return 0
  end
  return math.floor(n + 0.5)
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
    if govIndex ~= nil and govIndex < 0 then
      return nil
    end
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
  -- Gathering Storm keeps diplomatic favor on the player (pPlayer:GetFavor());
  -- the diplomacy object has no such call, which left favor at 0.
  if player.GetFavor ~= nil then
    local ok, v = pcall(player.GetFavor, player)
    if ok and v ~= nil then
      return Civ6Ai_Snapshot._Int(v)
    end
  end
  local diplomacy = player:GetDiplomacy()
  if diplomacy ~= nil and diplomacy.GetFavor ~= nil then
    return Civ6Ai_Snapshot._Int(diplomacy:GetFavor())
  end
  return 0
end

function Civ6Ai_Snapshot._FavorPerTurn(playerID)
  local player = Players[playerID]
  if player == nil or player.GetFavorPerTurn == nil then
    return nil
  end
  local ok, v = pcall(player.GetFavorPerTurn, player)
  if ok and v ~= nil then
    return Civ6Ai_Snapshot._Int(v)
  end
  return nil
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

function Civ6Ai_Snapshot._CurrentCivic(playerID)
  local result = {}
  local ok = pcall(function()
    local culture = Players[playerID]:GetCulture()
    local idx = culture:GetProgressingCivic()
    if idx == nil or idx < 0 then return end
    local row = GameInfo.Civics[idx]
    if row == nil then return end
    result.civic_id = row.CivicType
    local progress = culture:GetCulturalProgress(idx) or 0
    local cost = culture:GetCultureCost(idx) or 0
    result.progress = math.floor(progress)
    local rate = Players[playerID]:GetCulture():GetCultureYield() or 0
    local turnsLeft = nil
    if culture.GetTurnsLeft ~= nil then
      local okT, t = pcall(function() return culture:GetTurnsLeft() end)
      if okT and type(t) == "number" and t >= 0 then
        turnsLeft = math.floor(t)
      end
    end
    if turnsLeft == nil and culture.GetTurnsToProgressCivic ~= nil then
      local okT, t = pcall(function() return culture:GetTurnsToProgressCivic(idx) end)
      if okT and type(t) == "number" and t >= 0 then
        turnsLeft = math.floor(t)
      end
    end
    if turnsLeft == nil and rate > 0 and cost > progress then
      turnsLeft = math.ceil((cost - progress) / rate)
    end
    if turnsLeft ~= nil then
      result.turns_left = turnsLeft
    end
  end)
  if not ok then
    return {}
  end
  return result
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

-- Shared per-seat resource visibility: the engine's IsResourceVisible when present,
-- else the row's PrereqTech/PrereqCivic against this player's techs/civics.
function Civ6Ai_Snapshot._ResourceRevealedTo(playerID, row)
  if row == nil then return false end
  local M, p = Civ6Ai_Snapshot._Method, Players ~= nil and Players[playerID] or nil
  if p == nil then return false end
  local res = M(p, "GetResources")
  if res ~= nil and row.Hash ~= nil and res.IsResourceVisible ~= nil then
    local okV, v = pcall(function() return res:IsResourceVisible(row.Hash) end)
    if okV and type(v) == "boolean" then return v end
  end
  if row.PrereqTech ~= nil then
    local t = GameInfo.Technologies[row.PrereqTech]
    if t == nil or M(M(p, "GetTechs"), "HasTech", t.Index) ~= true then return false end
  end
  if row.PrereqCivic ~= nil then
    local c = GameInfo.Civics[row.PrereqCivic]
    if c == nil or M(M(p, "GetCulture"), "HasCivic", c.Index) ~= true then return false end
  end
  return true
end

function Civ6Ai_Snapshot._ResourceTypeName(plot, playerID)
  local idx = plot:GetResourceType()
  if idx == nil or idx < 0 or GameInfo.Resources == nil then
    return nil
  end
  local row = GameInfo.Resources[idx]
  if row == nil then return nil end
  if playerID ~= nil and not Civ6Ai_Snapshot._ResourceRevealedTo(playerID, row) then
    return nil
  end
  return row.ResourceType
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

-- District on this tile. City center is the city marker, not a second icon.
function Civ6Ai_Snapshot._DistrictTypeName(plot)
  if plot == nil or plot.GetDistrictType == nil then
    return nil
  end
  local ok, idx = pcall(function() return plot:GetDistrictType() end)
  if not ok or idx == nil or idx < 0 or GameInfo.Districts == nil then
    return nil
  end
  local row = GameInfo.Districts[idx]
  if row == nil or row.DistrictType == nil or row.DistrictType == "DISTRICT_CITY_CENTER" then
    return nil
  end
  return row.DistrictType
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

-- Civ6 has Map.GetAdjacentPlot (Map.PlotDirection is Civ5-only; the old code always
-- fell back to {dx=0, dy=-1}). dx is normalised across the X-wrap seam.
function Civ6Ai_Snapshot._AdjacentPlot(x, y, direction)
  if Map == nil or direction == nil then
    return nil
  end
  local fn = Map.GetAdjacentPlot or Map.PlotDirection
  if fn == nil then
    return nil
  end
  local ok, neighbor = pcall(function() return fn(x, y, direction) end)
  if ok then
    return neighbor
  end
  return nil
end

function Civ6Ai_Snapshot._RiverEdgeNeighbor(plot, direction, edgeId)
  if plot == nil or direction == nil then
    return nil
  end
  local x = plot:GetX()
  local y = plot:GetY()
  local neighbor = Civ6Ai_Snapshot._AdjacentPlot(x, y, direction)
  if neighbor == nil then
    return nil
  end
  local dx = neighbor:GetX() - x
  if dx > 1 then
    dx = -1
  elseif dx < -1 then
    dx = 1
  end
  return {
    dx = dx,
    dy = neighbor:GetY() - y,
    edge_id = edgeId,
  }
end

function Civ6Ai_Snapshot._RiverEdges(plot)
  local edges = {}
  if plot == nil then
    return edges
  end
  -- IsWOfRiver: river on this tile's EAST edge; IsNWOfRiver: SOUTHEAST edge;
  -- IsNEOfRiver: SOUTHWEST edge. Record the neighbour across that edge.
  local checks = {}
  if DirectionTypes ~= nil then
    if DirectionTypes.DIRECTION_EAST ~= nil and plot.IsWOfRiver ~= nil then
      table.insert(checks, {plot.IsWOfRiver, DirectionTypes.DIRECTION_EAST, "E"})
    end
    if DirectionTypes.DIRECTION_SOUTHEAST ~= nil and plot.IsNWOfRiver ~= nil then
      table.insert(checks, {plot.IsNWOfRiver, DirectionTypes.DIRECTION_SOUTHEAST, "SE"})
    end
    if DirectionTypes.DIRECTION_SOUTHWEST ~= nil and plot.IsNEOfRiver ~= nil then
      table.insert(checks, {plot.IsNEOfRiver, DirectionTypes.DIRECTION_SOUTHWEST, "SW"})
    end
  end
  for _, entry in ipairs(checks) do
    local isRiverFn = entry[1]
    local okRiver, onRiver = pcall(function() return isRiverFn(plot) end)
    if okRiver and onRiver then
      local neighbor = Civ6Ai_Snapshot._RiverEdgeNeighbor(plot, entry[2], entry[3])
      if neighbor ~= nil then
        table.insert(edges, neighbor)
      end
    end
  end
  -- Other three edges are stored on the neighbours (their E/SE/SW), so an empty list
  -- here does not mean "no river"; the renderer unions both sides.
  return edges
end

-- dy of the north-east neighbour of a mid-map plot: +1 means y grows northward.
function Civ6Ai_Snapshot._NorthDy(mapWidth, mapHeight)
  if DirectionTypes == nil or DirectionTypes.DIRECTION_NORTHEAST == nil then
    return 0
  end
  local x = math.floor((mapWidth or 2) / 2)
  local y = math.floor((mapHeight or 2) / 2)
  local neighbor = Civ6Ai_Snapshot._AdjacentPlot(x, y, DirectionTypes.DIRECTION_NORTHEAST)
  if neighbor == nil then
    return 0
  end
  return neighbor:GetY() - y
end

function Civ6Ai_Snapshot._OtherCityPlayerIds(playerID)
  local ids = {}
  for otherID = 0, 63 do
    if otherID ~= playerID and Players[otherID] ~= nil and Players[otherID]:IsAlive() then
      table.insert(ids, otherID)
    end
  end
  return ids
end

-- Foreign cities on tiles this player has revealed (schema known_city fields only).
function Civ6Ai_Snapshot._BuildKnownOtherCities(playerID, turn)
  local out = Civ6Ai_Util.JsonArrayList()
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  if vis == nil then
    return out
  end
  for _, otherID in ipairs(Civ6Ai_Snapshot._OtherCityPlayerIds(playerID)) do
    local ok, cities = pcall(function() return Players[otherID]:GetCities() end)
    if ok and cities ~= nil and cities.Members ~= nil then
      for _, city in cities:Members() do
        local plot = city ~= nil and Map.GetPlot(city:GetX(), city:GetY()) or nil
        if plot ~= nil and vis:IsRevealed(plot:GetIndex()) and #out < 40 then
          local visible = vis:IsVisible(plot:GetIndex())
          local nameOk, name = pcall(function() return Locale.Lookup(city:GetName()) end)
          local population = Civ6Ai_Util.JsonNull()
          if visible and city.GetPopulation ~= nil then
            population = Civ6Ai_Snapshot._Int(city:GetPopulation())
          end
          local isCapital = Civ6Ai_Util.JsonNull()
          if city.IsCapital ~= nil then
            local capOk, cap = pcall(function() return city:IsCapital() end)
            if capOk then isCapital = cap == true end
          end
          local areaId = "AREA_UNKNOWN"
          if plot.GetArea ~= nil then
            local areaOk, area = pcall(function() return plot:GetArea() end)
            if areaOk and area ~= nil and area.GetID ~= nil then
              areaId = "AREA_" .. tostring(area:GetID())
            end
          end
          table.insert(out, {
            city_id = "CITY_" .. tostring(otherID) .. "_" .. tostring(city:GetID()),
            owner_player_id = Civ6Ai_Util.PlayerId(otherID),
            name = (nameOk and name ~= nil and tostring(name) ~= "") and tostring(name) or "City",
            plot_id = "PLOT_" .. tostring(city:GetX()) .. "_" .. tostring(city:GetY()),
            area_id = areaId,
            knowledge = visible and "visible" or "remembered",
            last_seen_turn = visible and Civ6Ai_Snapshot._Int(turn) or 0,
            population = population,
            is_capital = isCapital,
            visible_defense = Civ6Ai_Util.JsonNull(),
          })
        end
      end
    end
  end
  return out
end

-- Foreign units standing on tiles this player can currently see.
function Civ6Ai_Snapshot._BuildVisibleOtherUnits(playerID)
  local out = Civ6Ai_Util.JsonArrayList()
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  if vis == nil then
    return out
  end
  for _, otherID in ipairs(Civ6Ai_Snapshot._OtherCityPlayerIds(playerID)) do
    local ok, units = pcall(function() return Players[otherID]:GetUnits() end)
    if ok and units ~= nil then
      for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(units)) do
        local plot = unit ~= nil and Map.GetPlot(unit:GetX(), unit:GetY()) or nil
        if plot ~= nil and vis:IsVisible(plot:GetIndex()) and #out < 60 then
          local current, maxHp = Civ6Ai_Snapshot._UnitHealth(unit)
          local info = Civ6Ai_Snapshot._UnitInfo(unit)
          local movesOk, moves = pcall(function() return unit:GetMovesRemaining() end)
          local health = math.floor((current * 100) / maxHp)
          if health < 0 then health = 0 elseif health > 100 then health = 100 end
          table.insert(out, {
            unit_id = "UNIT_" .. tostring(otherID) .. "_" .. tostring(unit:GetID()),
            owner_player_id = Civ6Ai_Util.PlayerId(otherID),
            unit_type_id = Civ6Ai_Snapshot._UnitTypeName(unit),
            plot_id = "PLOT_" .. tostring(unit:GetX()) .. "_" .. tostring(unit:GetY()),
            health_percent = health,
            visible_strength = math.max(0, math.floor(tonumber(info.combat) or 0)),
            movement_ready = movesOk and (tonumber(moves) or 0) > 0 or false,
          })
        end
      end
    end
  end
  return out
end

-- Never let a foreign-info helper break the whole snapshot.
function Civ6Ai_Snapshot._SafeList(fn)
  local ok, value = pcall(fn)
  if ok and value ~= nil then
    return value
  end
  if not ok then
    print("[Civ6Ai] snapshot list helper failed: " .. tostring(value))
  end
  return Civ6Ai_Util.JsonArrayList()
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
  local rec = {
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
    district_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._DistrictTypeName(plot)),
    route_id = Civ6Ai_Util.JsonNull(),
    resource_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._ResourceTypeName(plot)),
    yields = {food = 0, production = 0, commerce = 0},
    defense_percent = 0,
    city_id = Civ6Ai_Snapshot._NullableId(Civ6Ai_Snapshot._PlotCityWireId(plot)),
    worked_by_city_id = Civ6Ai_Util.JsonNull(),
    visible_stack_ids = {},
  }
  if plot.IsImprovementPillaged ~= nil then
    local okP, pillaged = pcall(function() return plot:IsImprovementPillaged() end)
    if okP and pillaged == true then
      rec.improvement_pillaged = true
    end
  end
  return rec
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
  local revealedCount = 0
  for y = 0, mapHeight - 1 do
    for x = 0, mapWidth - 1 do
      local plot = Map.GetPlot(x, y)
      if plot ~= nil and vis:IsRevealed(plot:GetIndex()) then
        revealedCount = revealedCount + 1
      end
    end
  end
  local totalPlots = mapWidth * mapHeight
  local exploredPercent = 0
  if totalPlots > 0 then
    exploredPercent = math.floor(100 * revealedCount / totalPlots)
  end
  return {
    format = "plot-grid-v1",
    visibility_mode = "player_visible",
    plots = plots,
    areas = {},
    frontiers = {},
    visible_stacks = {},
    visibility_grid = visibility_grid,
    revealed_count = revealedCount,
    explored_percent = exploredPercent,
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

function Civ6Ai_Snapshot._CityAmenities(city)
  local amenities = {positive = 0, negative = 0, net = 0}
  if city == nil then
    return amenities
  end
  local growth = nil
  if city.GetGrowth ~= nil then
    growth = city:GetGrowth()
  end
  if growth ~= nil then
    local pos = 0
    local neg = 0
    if growth.GetAmenities ~= nil then
      pos = Civ6Ai_Snapshot._Int(growth:GetAmenities())
    end
    if growth.GetAmenitiesNeeded ~= nil then
      neg = Civ6Ai_Snapshot._Int(growth:GetAmenitiesNeeded())
    end
    amenities.positive = pos
    amenities.negative = neg
    amenities.net = pos - neg
  end
  return amenities
end

function Civ6Ai_Snapshot._CityDefense(city)
  local defense = {
    percent = 100, health_percent = 100, bombard_damage = 0,
    wall_hp = 0, wall_max_hp = 0, hp = 200, max_hp = 200,
  }
  if city == nil then
    return defense
  end
  -- City HP is the centre district's garrison, the same pool the city banner
  -- uses. city:GetDamage stays at 0 while that garrison is already gone, which
  -- left every city at 100%. Walls are DISTRICT_OUTER (0 when the city has none).
  local maxHp, damage = nil, 0
  local district = Civ6Ai_Snapshot._CityCenterDistrict(city)
  if district ~= nil and DefenseTypes ~= nil then
    local gMax = Civ6Ai_Snapshot._NonNegative(Civ6Ai_Snapshot._Method(district, "GetMaxDamage", DefenseTypes.DISTRICT_GARRISON))
    local gDmg = Civ6Ai_Snapshot._NonNegative(Civ6Ai_Snapshot._Method(district, "GetDamage", DefenseTypes.DISTRICT_GARRISON))
    local wMax = Civ6Ai_Snapshot._NonNegative(Civ6Ai_Snapshot._Method(district, "GetMaxDamage", DefenseTypes.DISTRICT_OUTER))
    local wDmg = Civ6Ai_Snapshot._NonNegative(Civ6Ai_Snapshot._Method(district, "GetDamage", DefenseTypes.DISTRICT_OUTER))
    defense.wall_max_hp = wMax
    defense.wall_hp = wMax > 0 and math.max(0, wMax - wDmg) or 0
    if gMax > 0 then
      maxHp = gMax
      damage = gDmg
    end
  end
  if maxHp == nil then
    maxHp = 200
    if city.GetMaxHitPoints ~= nil then
      maxHp = city:GetMaxHitPoints() or maxHp
    elseif city.GetMaxDamage ~= nil then
      maxHp = city:GetMaxDamage() or maxHp
    end
    if city.GetDamage ~= nil then
      damage = city:GetDamage() or 0
    end
  end
  damage = Civ6Ai_Snapshot._NonNegative(damage)
  maxHp = math.max(1, Civ6Ai_Snapshot._NonNegative(maxHp))
  local current = math.max(0, maxHp - damage)
  defense.hp = current
  defense.max_hp = maxHp
  defense.percent = math.floor(100 * current / maxHp)
  defense.health_percent = defense.percent
  defense.bombard_damage = damage
  defense.percent = math.max(0, math.min(100, Civ6Ai_Snapshot._NonNegative(defense.percent)))
  defense.health_percent = math.max(0, math.min(100, Civ6Ai_Snapshot._NonNegative(defense.health_percent)))
  defense.hp = math.max(0, Civ6Ai_Snapshot._NonNegative(defense.hp))
  defense.max_hp = math.max(0, Civ6Ai_Snapshot._NonNegative(defense.max_hp))
  return defense
end

function Civ6Ai_Snapshot._GarrisonIds(playerID, x, y)
  local ids = {}
  local plot = Map.GetPlot ~= nil and Map.GetPlot(x, y) or nil
  if plot == nil or Units == nil or Units.GetUnitsInPlot == nil then
    return ids
  end
  local ok, list = pcall(function() return Units.GetUnitsInPlot(plot) end)
  if not ok or list == nil then
    return ids
  end
  for _, unit in ipairs(list) do
    if unit ~= nil and unit.GetOwner ~= nil and unit:GetOwner() == playerID then
      table.insert(ids, Civ6Ai_Snapshot._UnitWireId(unit))
    end
  end
  return ids
end

function Civ6Ai_Snapshot._CityBuildingIds(city)
  local out = Civ6Ai_Util.JsonArrayList()
  local buildings = Civ6Ai_Snapshot._EconCall(city, "GetBuildings")
  if buildings == nil or GameInfo == nil or GameInfo.Buildings == nil then
    return out
  end
  pcall(function()
    for bRow in GameInfo.Buildings() do
      if bRow.IsWonder ~= true and Civ6Ai_Snapshot._EconCall(buildings, "HasBuilding", bRow.Index) == true then
        table.insert(out, bRow.BuildingType)
      end
    end
  end)
  return out
end

function Civ6Ai_Snapshot._WorkedPlotIds(city)
  local out = Civ6Ai_Util.JsonArrayList()
  local citizens = Civ6Ai_Snapshot._EconCall(city, "GetCitizens")
  if citizens == nil or Map == nil or Map.GetPlot == nil then
    return out
  end
  local cx, cy = city:GetX(), city:GetY()
  pcall(function()
    for dy = -3, 3 do
      for dx = -3, 3 do
        local plot = Map.GetPlot(cx + dx, cy + dy)
        local index = plot ~= nil and plot.GetIndex ~= nil and plot:GetIndex() or nil
        if type(index) == "number" and Civ6Ai_Snapshot._EconCall(citizens, "IsPlotWorked", index) == true then
          table.insert(out, Civ6Ai_Util.PlotId(plot:GetX(), plot:GetY()))
        end
      end
    end
  end)
  return out
end

function Civ6Ai_Snapshot._WorldCongress()
  if Game == nil or Game.GetWorldCongress == nil then
    return nil
  end
  local ok, wc = pcall(function() return Game.GetWorldCongress() end)
  if not ok or wc == nil then
    return nil
  end
  local out = {}
  local function take(field, name, ...)
    local okCall, fn = pcall(function() return wc[name] end)
    if not okCall or type(fn) ~= "function" then
      return
    end
    local okV, value = pcall(fn, wc, ...)
    if okV and (type(value) == "number" or type(value) == "string" or type(value) == "boolean") then
      out[field] = value
    end
  end
  take("meeting_status", "GetMeetingStatus")
  take("meeting_turn", "GetMeetingTurn")
  take("in_session", "IsInSession")
  local any = false
  for _, _ in pairs(out) do
    any = true
    break
  end
  if not any then
    return nil
  end
  return out
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
      buildings = Civ6Ai_Snapshot._CityBuildingIds(city),
      garrison_unit_ids = Civ6Ai_Snapshot._GarrisonIds(playerID, x, y),
      worked_plot_ids = Civ6Ai_Snapshot._WorkedPlotIds(city),
      automation = {citizens = false, production = true},
      culture = Civ6Ai_Snapshot._EmptyAmounts(),
      great_people = Civ6Ai_Snapshot._EmptyAmounts(),
      happiness = {positive = 0, negative = 0, net = 0},
      amenities = Civ6Ai_Snapshot._CityAmenities(city),
      health = {positive = 0, negative = 0, net = 0},
      defense = Civ6Ai_Snapshot._CityDefense(city),
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

function Civ6Ai_Snapshot._UnitInfo(unit)
  local info = {combat = 0, ranged = 0, range = 0, formation = nil, domain = nil}
  if unit == nil or GameInfo == nil or GameInfo.Units == nil then
    return info
  end
  local okRow, row = pcall(function() return GameInfo.Units[unit:GetType()] end)
  if okRow and row ~= nil then
    info.combat = math.floor(tonumber(row.Combat) or 0)
    info.ranged = tonumber(row.RangedCombat) or 0
    info.range = tonumber(row.Range) or 0
    info.formation = row.FormationClass
    info.domain = row.Domain
  end
  if unit.GetCombat ~= nil then
    local ok, value = pcall(function() return unit:GetCombat() end)
    if ok and tonumber(value) ~= nil and math.floor(tonumber(value)) ~= info.combat then
      Civ6Ai_Util.Log("snapshot|combat_mismatch|" .. tostring(okRow and row.UnitType) .. "|db=" .. tostring(info.combat) .. "|engine=" .. tostring(value))
      info.combat = math.floor(tonumber(value))
    end
  end
  if unit.GetRangedCombat ~= nil then
    local ok, value = pcall(function() return unit:GetRangedCombat() end)
    if ok and tonumber(value) ~= nil then info.ranged = tonumber(value) end
  end
  if unit.GetRange ~= nil then
    local ok, value = pcall(function() return unit:GetRange() end)
    if ok and tonumber(value) ~= nil then info.range = tonumber(value) end
  end
  return info
end

function Civ6Ai_Snapshot._IsMilitaryInfo(info)
  if info == nil then return false end
  if info.formation == "FORMATION_CLASS_CIVILIAN" or info.formation == "FORMATION_CLASS_SUPPORT" then
    return false
  end
  return (info.combat or 0) > 0 or (info.ranged or 0) > 0
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
    if typeName == "UNIT_BUILDER" then
      counts.workers = counts.workers + 1
    end
    if Civ6Ai_Snapshot._IsMilitaryInfo(Civ6Ai_Snapshot._UnitInfo(unit)) then
      counts.military = counts.military + 1
    end
  end
  return counts
end

function Civ6Ai_Snapshot._ReligionTypeName(index)
  if type(index) ~= "number" or index < 0 or GameInfo == nil or GameInfo.Religions == nil then
    return nil
  end
  local ok, row = pcall(function() return GameInfo.Religions[index] end)
  if not ok or row == nil or type(row.ReligionType) ~= "string" or row.ReligionType == "" then
    return nil
  end
  if row.ReligionType == "RELIGION_PANTHEON" then
    return nil
  end
  return row.ReligionType
end

function Civ6Ai_Snapshot._EmpireReligion(player)
  local rel = {
    state_religion_id = Civ6Ai_Util.JsonNull(),
    convertible_religion_ids = {},
    conversion_timer = 0,
  }
  local obj = Civ6Ai_Snapshot._EconCall(player, "GetReligion")
  local name = Civ6Ai_Snapshot._ReligionTypeName(Civ6Ai_Snapshot._EconCall(obj, "GetReligionType"))
  if name == nil then
    name = Civ6Ai_Snapshot._ReligionTypeName(Civ6Ai_Snapshot._EconCall(obj, "GetReligionInMajorityOfCities"))
  end
  if name ~= nil then
    rel.state_religion_id = name
  end
  local faith = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(obj, "GetFaithBalance"))
  if faith ~= nil then
    rel.faith = faith
  end
  local per = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(obj, "GetFaithYield"))
  if per ~= nil then
    rel.faith_per_turn = per
  end
  return rel
end

function Civ6Ai_Snapshot._CityExtraRow(city)
  local row = {}
  local ident = Civ6Ai_Snapshot._EconCall(city, "GetCulturalIdentity")
  local loyalty = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(ident, "GetLoyalty"))
  if loyalty ~= nil then
    row.loyalty = loyalty
  end
  local per = tonumber(Civ6Ai_Snapshot._EconCall(ident, "GetLoyaltyPerTurn"))
  if per ~= nil then
    row.loyalty_per_turn = math.floor(per * 10 + 0.5) / 10
  end
  local districts = Civ6Ai_Util.JsonArrayList()
  local pDistricts = Civ6Ai_Snapshot._EconCall(city, "GetDistricts")
  if pDistricts ~= nil and pDistricts.Members ~= nil and GameInfo ~= nil and GameInfo.Districts ~= nil then
    pcall(function()
      for _, district in pDistricts:Members() do
        local dRow = GameInfo.Districts[district:GetType()]
        if dRow ~= nil and type(dRow.DistrictType) == "string"
            and dRow.DistrictType ~= "DISTRICT_CITY_CENTER" then
          table.insert(districts, dRow.DistrictType)
        end
      end
    end)
  end
  if #districts > 0 then
    row.districts = districts
  end
  local wonders = Civ6Ai_Util.JsonArrayList()
  local buildings = Civ6Ai_Snapshot._EconCall(city, "GetBuildings")
  if buildings ~= nil and GameInfo ~= nil and GameInfo.Buildings ~= nil then
    pcall(function()
      for bRow in GameInfo.Buildings() do
        if bRow.IsWonder == true and Civ6Ai_Snapshot._EconCall(buildings, "HasBuilding", bRow.Index) == true then
          table.insert(wonders, bRow.BuildingType)
        end
      end
    end)
  end
  if #wonders > 0 then
    row.wonders = wonders
  end
  local cityRel = Civ6Ai_Snapshot._EconCall(city, "GetReligion")
  local majority = Civ6Ai_Snapshot._ReligionTypeName(Civ6Ai_Snapshot._EconCall(cityRel, "GetMajorityReligion"))
  if majority ~= nil then
    row.religion = majority
  end
  return row
end

function Civ6Ai_Snapshot._BuildCityExtra(playerID)
  local out = {}
  local player = Players[playerID]
  local cities = player ~= nil and player.GetCities ~= nil and player:GetCities() or nil
  if cities == nil or cities.Members == nil then
    return out
  end
  for _, city in cities:Members() do
    local facts = Civ6Ai_Snapshot._CityExtraRow(city)
    local has = false
    for _, _ in pairs(facts) do
      has = true
      break
    end
    if has then
      out[Civ6Ai_Production._WireCityId(city)] = facts
    end
  end
  return out
end

-- GetScienceYield and GetCultureYield read 0 on the turn a government
-- changes, and through anarchy, while each city still reports its yield.
-- A positive city sum is the real per-turn number. A true zero stays zero.
function Civ6Ai_Snapshot._YieldOrCities(player, direct, yieldType)
  local n = tonumber(direct)
  if n == nil then
    n = 0
  end
  if n > 0 or yieldType == nil or player == nil or player.GetCities == nil then
    return n
  end
  local cities = player:GetCities()
  local sum = 0
  if cities ~= nil and cities.Members ~= nil then
    pcall(function()
      for _, city in cities:Members() do
        if city.GetYield ~= nil then
          local y = city:GetYield(yieldType)
          if type(y) == "number" and y > 0 then
            sum = sum + y
          end
        end
      end
    end)
  end
  if sum > 0 then
    return sum
  end
  return n
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
    local directScience = 0
    if techs.GetScienceYield ~= nil then
      local okY, y = pcall(function() return techs:GetScienceYield() end)
      if okY and type(y) == "number" then
        directScience = y
      end
    end
    local rawYield = Civ6Ai_Snapshot._YieldOrCities(player, directScience, YieldTypes ~= nil and YieldTypes.SCIENCE or nil)
    research.research_per_turn = Civ6Ai_Snapshot._Int(rawYield)
    if idx ~= nil and idx >= 0 then
      research.progress = Civ6Ai_Snapshot._Int(techs:GetResearchProgress(idx))
      research.cost = Civ6Ai_Snapshot._Int(techs:GetResearchCost(idx))
      local remaining = research.cost - research.progress
      -- The same engine call the tech panel uses. Ceil of the floored
      -- per-turn yield is one turn high whenever the fractional science
      -- would finish sooner (STEEL 7 in one place and 6 in the other).
      local turnsLeft = nil
      if techs.GetTurnsLeft ~= nil then
        local okT, t = pcall(function() return techs:GetTurnsLeft() end)
        if okT and type(t) == "number" and t >= 0 then
          turnsLeft = math.floor(t)
        end
      end
      if turnsLeft == nil and techs.GetTurnsToResearch ~= nil then
        local okT, t = pcall(function() return techs:GetTurnsToResearch(idx) end)
        if okT and type(t) == "number" and t >= 0 then
          turnsLeft = math.floor(t)
        end
      end
      if turnsLeft == nil and rawYield > 0 and remaining > 0 then
        turnsLeft = math.ceil(remaining / rawYield)
      end
      if turnsLeft ~= nil then
        research.estimated_turns_remaining = turnsLeft
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
    local directCulture = 0
    if culture.GetCultureYield ~= nil then
      local okC, c = pcall(function() return culture:GetCultureYield() end)
      if okC and type(c) == "number" then
        directCulture = c
      end
    end
    commerce.culture.rate = Civ6Ai_Snapshot._Int(
      Civ6Ai_Snapshot._YieldOrCities(player, directCulture, YieldTypes ~= nil and YieldTypes.CULTURE or nil))
  end
  local civics = {}
  for row in GameInfo.Technologies() do
    if techs ~= nil and techs:HasTech(row.Index) then table.insert(research.known_tech_ids, row.TechnologyType) end
  end
  for row in GameInfo.Civics() do
    if culture ~= nil and culture:HasCivic(row.Index) then table.insert(civics, {key = "known", id = row.CivicType}) end
  end
  local amenityNet = 0
  local amenityPos = 0
  local amenityNeg = 0
  local cities = Civ6Ai_Snapshot._BuildYourCities(playerID)
  for _, city in ipairs(cities) do
    local amenities = city.amenities
    if amenities ~= nil then
      amenityPos = amenityPos + Civ6Ai_Snapshot._Int(amenities.positive)
      amenityNeg = amenityNeg + Civ6Ai_Snapshot._Int(amenities.negative)
      amenityNet = amenityNet + Civ6Ai_Snapshot._Int(amenities.net)
    end
  end
  local anarchyTurns = 0
  if culture ~= nil and culture.IsInAnarchy ~= nil then
    local okA, inA = pcall(function() return culture:IsInAnarchy() end)
    if okA and inA == true then
      local okE, endTurn = pcall(function() return culture:GetAnarchyEndTurn() end)
      local nowTurn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or 0
      if okE and type(endTurn) == "number" and endTurn > nowTurn then
        anarchyTurns = endTurn - nowTurn
      else
        anarchyTurns = 1
      end
    end
  end
  return {
    team_id = "TEAM_" .. tostring(player:GetTeam()),
    score = Civ6Ai_Snapshot._Int(player:GetScore()),
    gold = gold,
    gold_per_turn = gpt,
    amenities = {positive = amenityPos, negative = amenityNeg, net = amenityNet},
    research = research,
    commerce = commerce,
    unit_counts = Civ6Ai_Snapshot._BuildUnitCounts(playerID),
    anarchy_turns = anarchyTurns,
    golden_age_turns = 0,
    war_weariness = 0,
    civics = civics,
    costs = {
      city_maintenance = Civ6Ai_Snapshot._Int(treasury:GetTotalMaintenance()),
      civic_upkeep = 0,
      inflation = 0,
      unit_cost = 0,
      unit_supply = 0,
    },
    religion = Civ6Ai_Snapshot._EmpireReligion(player),
    resources = {},
    victory_progress = {},
  }
end

-- ===========================================================================
-- civ6.economy (Civ5-parity economy/empire panel). Everything here reads the
-- same engine APIs the base-game UI uses (ToolTipHelper_PlayerYields.lua,
-- CitySupport.lua, ProductionPanel.lua, NotificationPanel.lua) and is pcall'd
-- piecewise: a missing API costs one field, never the snapshot.
-- Fractional values travel as "%.1f" strings (EncodeJsonValue rounds numbers).
-- ===========================================================================
Civ6Ai_Snapshot.ECON_NOTIFICATION_CAP = 15

function Civ6Ai_Snapshot._EconCall(obj, name, ...)
  if obj == nil then return nil end
  local okGet, fn = pcall(function() return obj[name] end)
  if not okGet or type(fn) ~= "function" then return nil end
  local args = {...}
  local unpackFn = table.unpack or unpack
  local ok, value = pcall(function() return fn(obj, unpackFn(args)) end)
  if ok then return value end
  return nil
end

function Civ6Ai_Snapshot._EconNum(value)
  local n = tonumber(value)
  if n == nil then return nil end
  return string.format("%.1f", n)
end

function Civ6Ai_Snapshot._EconInt(value)
  local n = tonumber(value)
  if n == nil then return nil end
  if n >= 0 then return math.floor(n + 0.5) end
  return math.ceil(n - 0.5)
end

function Civ6Ai_Snapshot._EconTreasury(player)
  local out = {}
  local treasury = Civ6Ai_Snapshot._EconCall(player, "GetTreasury")
  if treasury == nil then return out end
  local call = function(name) return Civ6Ai_Snapshot._EconCall(treasury, name) end
  out.treasury = Civ6Ai_Snapshot._EconNum(call("GetGoldBalance"))
  local gross = tonumber(call("GetGoldYield"))
  local total = tonumber(call("GetTotalMaintenance"))
  out.gross_income = Civ6Ai_Snapshot._EconNum(gross)
  out.maintenance_total = Civ6Ai_Snapshot._EconNum(total)
  out.maintenance_buildings = Civ6Ai_Snapshot._EconNum(call("GetBuildingMaintenance"))
  out.maintenance_districts = Civ6Ai_Snapshot._EconNum(call("GetDistrictMaintenance"))
  out.maintenance_units = Civ6Ai_Snapshot._EconNum(call("GetUnitMaintenance"))
  out.maintenance_wmd = Civ6Ai_Snapshot._EconNum(call("GetWMDMaintenance"))
  out.unit_maint_discount = Civ6Ai_Snapshot._EconNum(call("GetMaintDiscountPerUnit"))
  if gross ~= nil and total ~= nil then
    out.net = Civ6Ai_Snapshot._EconNum(gross - total)
  end
  local incomeTip = call("GetGoldYieldToolTip")
  if type(incomeTip) == "string" and incomeTip ~= "" then
    out.income_tooltip = string.sub(incomeTip, 1, 800)
  end
  local expenseTip = call("GetTotalMaintenanceToolTip")
  if type(expenseTip) == "string" and expenseTip ~= "" then
    out.expense_tooltip = string.sub(expenseTip, 1, 800)
  end
  return out
end

function Civ6Ai_Snapshot._EconCity(player, city)
  local row = {
    city_id = Civ6Ai_Production._WireCityId(city),
    name = Locale.Lookup(city:GetName()),
    population = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(city, "GetPopulation")),
  }
  if YieldTypes ~= nil then
    for key, yieldType in pairs({food = YieldTypes.FOOD, production = YieldTypes.PRODUCTION,
        gold = YieldTypes.GOLD, science = YieldTypes.SCIENCE, culture = YieldTypes.CULTURE,
        faith = YieldTypes.FAITH}) do
      if yieldType ~= nil then
        row[key] = Civ6Ai_Snapshot._EconNum(Civ6Ai_Snapshot._EconCall(city, "GetYield", yieldType))
      end
    end
  end
  local growth = Civ6Ai_Snapshot._EconCall(city, "GetGrowth")
  if growth ~= nil then
    local g = function(name) return Civ6Ai_Snapshot._EconCall(growth, name) end
    local turnsGrow = tonumber(g("GetTurnsUntilGrowth"))
    local turnsStarve = tonumber(g("GetTurnsUntilStarvation"))
    if turnsGrow ~= nil and turnsGrow ~= -1 then
      row.turns_to_growth = Civ6Ai_Snapshot._EconInt(turnsGrow)
    elseif turnsStarve ~= nil and turnsStarve ~= -1 then
      row.turns_to_starve = Civ6Ai_Snapshot._EconInt(turnsStarve)
    end
    row.food_surplus = Civ6Ai_Snapshot._EconNum(g("GetFoodSurplus"))
    row.housing = Civ6Ai_Snapshot._EconNum(g("GetHousing"))
    row.housing_growth_mult = Civ6Ai_Snapshot._EconNum(g("GetHousingGrowthModifier"))
    row.amenities = Civ6Ai_Snapshot._EconInt(g("GetAmenities"))
    row.amenities_needed = Civ6Ai_Snapshot._EconInt(g("GetAmenitiesNeeded"))
    row.amenities_lost_bankruptcy = Civ6Ai_Snapshot._EconInt(g("GetAmenitiesLostFromBankruptcy"))
    row.amenities_lost_war_weariness = Civ6Ai_Snapshot._EconInt(g("GetAmenitiesLostFromWarWeariness"))
    row.amenities_from_luxuries = Civ6Ai_Snapshot._EconInt(g("GetAmenitiesFromLuxuries"))
    row.happiness_growth_pct = Civ6Ai_Snapshot._EconInt(g("GetHappinessGrowthModifier"))
    row.happiness_yield_pct = Civ6Ai_Snapshot._EconInt(g("GetHappinessNonFoodYieldModifier"))
    local happiness = g("GetHappiness")
    if happiness ~= nil and GameInfo.Happinesses ~= nil then
      local okH, hRow = pcall(function() return GameInfo.Happinesses[happiness] end)
      if okH and hRow ~= nil then
        row.happiness = hRow.HappinessType
      end
    end
  end
  local okProd, itemId, _, _, _, turns = pcall(Civ6Ai_Production._GetCityProductionState, city)
  if okProd then
    row.production_item = itemId
    row.production_turns = Civ6Ai_Snapshot._EconInt(turns)
  end
  local buildings = Civ6Ai_Util.JsonArrayList()
  local pBuildings = Civ6Ai_Snapshot._EconCall(city, "GetBuildings")
  if pBuildings ~= nil and GameInfo.Buildings ~= nil then
    for bRow in GameInfo.Buildings() do
      if Civ6Ai_Snapshot._EconCall(pBuildings, "HasBuilding", bRow.Index) == true then
        local label = bRow.BuildingType
        if Civ6Ai_Snapshot._EconCall(pBuildings, "IsPillaged", bRow.Index) == true then
          label = label .. " (pillaged)"
        end
        table.insert(buildings, label)
      end
    end
  end
  row.built_buildings = buildings
  local districts = Civ6Ai_Util.JsonArrayList()
  local pDistricts = Civ6Ai_Snapshot._EconCall(city, "GetDistricts")
  if pDistricts ~= nil and GameInfo.Districts ~= nil then
    local okD = pcall(function()
      for _, district in pDistricts:Members() do
        local dRow = GameInfo.Districts[district:GetType()]
        if dRow ~= nil and dRow.DistrictType ~= "DISTRICT_CITY_CENTER" then
          local label = dRow.DistrictType
          if Civ6Ai_Snapshot._EconCall(pDistricts, "HasDistrict", dRow.Index, true) ~= true then
            label = label .. " (under construction)"
          elseif Civ6Ai_Snapshot._EconCall(district, "IsPillaged") == true then
            label = label .. " (pillaged)"
          end
          table.insert(districts, label)
        end
      end
    end)
    if not okD then
      Civ6Ai_Util.Log("snapshot|economy_districts_failed")
    end
  end
  row.built_districts = districts
  return row
end

function Civ6Ai_Snapshot._EconNotifications(playerID)
  local out = Civ6Ai_Util.JsonArrayList()
  if NotificationManager == nil or NotificationManager.GetList == nil then return out end
  local okList, list = pcall(NotificationManager.GetList, playerID)
  if not okList or type(list) ~= "table" then return out end
  local ids = {}
  for _, nid in ipairs(list) do table.insert(ids, nid) end
  table.sort(ids, function(a, b) return (tonumber(a) or 0) > (tonumber(b) or 0) end)
  for _, nid in ipairs(ids) do
    if #out >= Civ6Ai_Snapshot.ECON_NOTIFICATION_CAP then break end
    local okFind, entry = pcall(NotificationManager.Find, playerID, nid)
    if okFind and entry ~= nil and Civ6Ai_Snapshot._EconCall(entry, "IsDismissed") ~= true then
      local message = Civ6Ai_Snapshot._EconCall(entry, "GetMessage")
      local summary = Civ6Ai_Snapshot._EconCall(entry, "GetSummary")
      local okM, m = pcall(function() return message and Locale.Lookup(message) or "" end)
      local okS, s = pcall(function() return summary and Locale.Lookup(summary) or "" end)
      local typeName = Civ6Ai_Snapshot._EconCall(entry, "GetTypeName")
      if typeName == nil then
        typeName = Civ6Ai_Snapshot._NotificationTypeName(entry)
      end
      table.insert(out, {
        id = tonumber(nid) or 0,
        type = tostring(typeName or "NOTIFICATION_UNKNOWN"),
        message = string.sub(okM and tostring(m or "") or "", 1, 160),
        summary = string.sub(okS and tostring(s or "") or "", 1, 240),
        blocking = (tonumber(Civ6Ai_Snapshot._EconCall(entry, "GetEndTurnBlocking")) or 0) ~= 0,
      })
    end
  end
  return out
end

-- Stats for every build id this seat was offered (legal queue_production rows),
-- plus per-city turns. Unit upkeep = UnitManager.GetUnitMaintenance minus the
-- treasury per-unit discount (ReportScreen.lua does the same).
function Civ6Ai_Snapshot._EconCatalog(player, legal)
  local catalog = {}
  local turnsByCity = {}
  local offered = {}
  for _, command in ipairs(legal or {}) do
    if type(command) == "table" and command.kind == "queue_production" then
      local fixed = command.fixed_arguments or {}
      if fixed.city_id ~= nil and fixed.build_id ~= nil then
        offered[fixed.city_id] = offered[fixed.city_id] or {}
        table.insert(offered[fixed.city_id], fixed.build_id)
      end
    end
  end
  local discount = 0
  local treasury = Civ6Ai_Snapshot._EconCall(player, "GetTreasury")
  if treasury ~= nil then
    discount = tonumber(Civ6Ai_Snapshot._EconCall(treasury, "GetMaintDiscountPerUnit")) or 0
  end
  local yieldsByBuilding = nil
  local function buildingYields(buildingType)
    if yieldsByBuilding == nil then
      yieldsByBuilding = {}
      pcall(function()
        for yRow in GameInfo.Building_YieldChanges() do
          local list = yieldsByBuilding[yRow.BuildingType] or {}
          table.insert(list, "+" .. tostring(yRow.YieldChange) .. " "
            .. string.lower(string.gsub(tostring(yRow.YieldType), "^YIELD_", "")))
          yieldsByBuilding[yRow.BuildingType] = list
        end
      end)
    end
    return yieldsByBuilding[buildingType]
  end
  local cities = Civ6Ai_Snapshot._EconCall(player, "GetCities")
  if cities == nil then return catalog, turnsByCity end
  for _, city in cities:Members() do
    local cityId = Civ6Ai_Production._WireCityId(city)
    local builds = offered[cityId]
    if builds ~= nil then
      local bq = Civ6Ai_Snapshot._EconCall(city, "GetBuildQueue")
      local turns = {}
      for _, buildId in ipairs(builds) do
        local uRow = GameInfo.Units ~= nil and GameInfo.Units[buildId] or nil
        local bRow = (uRow == nil and GameInfo.Buildings ~= nil) and GameInfo.Buildings[buildId] or nil
        local pRow = (uRow == nil and bRow == nil and GameInfo.Projects ~= nil) and GameInfo.Projects[buildId] or nil
        local row = uRow or bRow or pRow
        if row ~= nil then
          local t = Civ6Ai_Snapshot._EconCall(bq, "GetTurnsLeft", row.Hash)
          if t == nil or tonumber(t) == nil or tonumber(t) < 0 then
            t = Civ6Ai_Snapshot._EconCall(bq, "GetTurnsLeft", buildId)
          end
          if tonumber(t) ~= nil and tonumber(t) >= 0 then
            turns[buildId] = Civ6Ai_Snapshot._EconInt(t)
          end
          if catalog[buildId] == nil then
            local item = {}
            if uRow ~= nil then
              item.category = "unit"
              item.cost = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(bq, "GetUnitCost", uRow.Index))
              item.combat = tonumber(uRow.Combat) or 0
              item.ranged = tonumber(uRow.RangedCombat) or 0
              item.range = tonumber(uRow.Range) or 0
              item.moves = tonumber(uRow.BaseMoves) or 0
              item.domain = uRow.Domain
              local maint = tonumber(uRow.Maintenance) or 0
              if UnitManager ~= nil and UnitManager.GetUnitMaintenance ~= nil then
                local okM, m = pcall(UnitManager.GetUnitMaintenance, uRow.Hash)
                if okM and tonumber(m) ~= nil then maint = tonumber(m) end
              end
              if maint > 0 then maint = math.max(0, maint - discount) end
              item.upkeep = maint
            elseif bRow ~= nil then
              item.category = "building"
              item.cost = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(bq, "GetBuildingCost", bRow.Index))
              item.maintenance = tonumber(bRow.Maintenance) or 0
              item.housing = tonumber(bRow.Housing) or 0
              item.amenities = tonumber(bRow.Entertainment) or 0
              item.district = bRow.PrereqDistrict
              local ys = buildingYields(bRow.BuildingType)
              if ys ~= nil then item.yields = table.concat(ys, ", ") end
            else
              item.category = "project"
              item.cost = Civ6Ai_Snapshot._EconInt(Civ6Ai_Snapshot._EconCall(bq, "GetProjectCost", pRow.Index))
            end
            catalog[buildId] = item
          end
        end
      end
      turnsByCity[cityId] = turns
    end
  end
  return catalog, turnsByCity
end

function Civ6Ai_Snapshot._BuildEconomy(playerID, legal)
  local player = Players[playerID]
  if player == nil then return nil end
  local economy = {}
  local okT, treasury = pcall(Civ6Ai_Snapshot._EconTreasury, player)
  if okT and type(treasury) == "table" then
    economy.gold = treasury
  else
    Civ6Ai_Util.Log("snapshot|economy_treasury_failed|" .. tostring(treasury))
  end
  local cityRows = Civ6Ai_Util.JsonArrayList()
  local cities = Civ6Ai_Snapshot._EconCall(player, "GetCities")
  if cities ~= nil then
    for _, city in cities:Members() do
      local okC, row = pcall(Civ6Ai_Snapshot._EconCity, player, city)
      if okC and type(row) == "table" then
        table.insert(cityRows, row)
      else
        Civ6Ai_Util.Log("snapshot|economy_city_failed|" .. tostring(row))
      end
    end
  end
  economy.cities = cityRows
  local levels = Civ6Ai_Util.JsonArrayList()
  local okH = pcall(function()
    for hRow in GameInfo.Happinesses() do
      table.insert(levels, {
        type = hRow.HappinessType,
        min_amenity = hRow.MinimumAmenityScore,
        max_amenity = hRow.MaximumAmenityScore,
        growth_pct = hRow.GrowthModifier,
        yield_pct = hRow.NonFoodYieldModifier,
        rebellion = hRow.RebellionPoints,
      })
    end
  end)
  if okH then
    economy.happiness_levels = levels
  end
  local okN, notes = pcall(Civ6Ai_Snapshot._EconNotifications, playerID)
  if okN then
    economy.notifications = notes
  else
    Civ6Ai_Util.Log("snapshot|economy_notifications_failed|" .. tostring(notes))
  end
  local okCat, catalog, turns = pcall(Civ6Ai_Snapshot._EconCatalog, player, legal)
  if okCat then
    economy.build_catalog = catalog
    economy.build_turns = turns
  else
    Civ6Ai_Util.Log("snapshot|economy_catalog_failed|" .. tostring(catalog))
  end
  return economy
end

-- Diplomacy (Civ5-style relations). Every engine call is pcall'd through
-- _Try/_Method: several of these exist only in one Lua context or only in some
-- rulesets, and a missing one must cost a field, never the snapshot.
function Civ6Ai_Snapshot._Try(fn, ...)
  local ok, value = pcall(fn, ...)
  if ok then
    return value
  end
  return nil
end

function Civ6Ai_Snapshot._Method(obj, name, ...)
  if obj == nil then
    return nil
  end
  local okGet, fn = pcall(function() return obj[name] end)
  if not okGet or type(fn) ~= "function" then
    return nil
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local ok, value = pcall(function() return fn(obj, unpackFn(args)) end)
  if ok then
    return value
  end
  return nil
end

-- C-side tables that ClimateScreen.lua calls with a dot (GameClimate.GetTotalCO2Footprint),
-- not a colon. Passing the table as self makes those calls fail.
function Civ6Ai_Snapshot._Static(tbl, name, ...)
  if tbl == nil then
    return nil
  end
  local okGet, fn = pcall(function() return tbl[name] end)
  if not okGet or type(fn) ~= "function" then
    return nil
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local ok, value = pcall(function() return fn(unpackFn(args)) end)
  if ok then
    return value
  end
  return nil
end

function Civ6Ai_Snapshot._Arr()
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.JsonArrayList ~= nil then
    return Civ6Ai_Util.JsonArrayList()
  end
  return {}
end

function Civ6Ai_Snapshot._PlayerLabel(playerID)
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.PlayerId ~= nil then
    return Civ6Ai_Util.PlayerId(playerID)
  end
  return "PLAYER_" .. tostring(playerID)
end

-- "major" | "city_state" | "barbarian" | "free_cities" | nil (dead / absent).
function Civ6Ai_Snapshot._PlayerKind(otherID)
  local other = Players[otherID]
  if other == nil or Civ6Ai_Snapshot._Method(other, "IsAlive") ~= true then
    return nil
  end
  if Civ6Ai_Snapshot._Method(other, "IsBarbarian") == true then
    return "barbarian"
  end
  local leader = tostring(Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._LeaderId, otherID) or "")
  local civ = tostring(Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._CivId, otherID) or "")
  if civ == "CIVILIZATION_FREE_CITIES" or leader == "LEADER_FREE_CITIES" then
    return "free_cities"
  end
  if leader:find("^LEADER_MINOR_CIV_") ~= nil then
    return "city_state"
  end
  local major = Civ6Ai_Snapshot._Method(other, "IsMajor")
  if major == false then
    return "city_state"
  end
  return "major"
end

-- GameInfo.DiplomaticStates StateType of other's stance toward playerID
-- (DIPLO_STATE_ALLIED, _DECLARED_FRIEND, _FRIENDLY, _NEUTRAL, _UNFRIENDLY,
-- _DENOUNCED, _WAR), or nil when the engine will not say (humans, city-states).
function Civ6Ai_Snapshot._DiploState(fromID, towardID)
  local ai = Civ6Ai_Snapshot._Method(Players[fromID], "GetDiplomaticAI")
  local index = Civ6Ai_Snapshot._Method(ai, "GetDiplomaticStateIndex", towardID)
  if type(index) ~= "number" or index < 0 or GameInfo == nil or GameInfo.DiplomaticStates == nil then
    return nil
  end
  local row = Civ6Ai_Snapshot._Try(function() return GameInfo.DiplomaticStates[index] end)
  if row == nil or row.StateType == nil then
    return nil
  end
  return tostring(row.StateType)
end

Civ6Ai_Snapshot.DIPLO_RELATIONSHIP = {
  DIPLO_STATE_ALLIED = "alliance",
  DIPLO_STATE_DECLARED_FRIEND = "declared_friendship",
  DIPLO_STATE_FRIENDLY = "friendly",
  DIPLO_STATE_NEUTRAL = "neutral",
  DIPLO_STATE_UNFRIENDLY = "unfriendly",
  DIPLO_STATE_DENOUNCED = "denounced",
  DIPLO_STATE_WAR = "war",
}

-- Top reasons behind the rival's attitude (the "modifiers" list in the leader
-- screen): { {text, score}, ... } strongest first.
function Civ6Ai_Snapshot._AttitudeReasons(fromID, towardID, limit)
  local out = Civ6Ai_Snapshot._Arr()
  local ai = Civ6Ai_Snapshot._Method(Players[fromID], "GetDiplomaticAI")
  local mods = Civ6Ai_Snapshot._Method(ai, "GetDiplomaticModifiers", towardID)
  if type(mods) ~= "table" then
    return out
  end
  local rows = {}
  for _, mod in pairs(mods) do
    if type(mod) == "table" then
      local text = mod.Text or mod.text
      local score = tonumber(mod.Score or mod.score)
      if type(text) == "string" and text ~= "" and score ~= nil and score ~= 0 then
        if Locale ~= nil and Locale.Lookup ~= nil then
          text = Civ6Ai_Snapshot._Try(Locale.Lookup, text) or text
        end
        text = text:gsub("%[[^%]]*%]", "")
        text = Civ6Ai_Util.CollapseAsciiWS(text)
        if string.find(string.lower(text), "unknown reason", 1, true) == nil then
          table.insert(rows, { text = text:sub(1, 80), score = math.floor(score + 0.5) })
        end
      end
    end
  end
  table.sort(rows, function(a, b) return math.abs(a.score) > math.abs(b.score) end)
  for i = 1, math.min(#rows, limit or 3) do
    table.insert(out, rows[i])
  end
  return out
end

function Civ6Ai_Snapshot._RelationFacts(playerID, otherID)
  local me = Players[playerID]
  local myDiplo = Civ6Ai_Snapshot._Method(me, "GetDiplomacy")
  local theirDiplo = Civ6Ai_Snapshot._Method(Players[otherID], "GetDiplomacy")
  local facts = {}
  facts.at_war = Civ6Ai_Snapshot._Method(myDiplo, "IsAtWarWith", otherID) == true
  facts.state = Civ6Ai_Snapshot._DiploState(otherID, playerID)
  local ai = Civ6Ai_Snapshot._Method(Players[otherID], "GetDiplomaticAI")
  local score = Civ6Ai_Snapshot._Method(ai, "GetDiplomaticScore", playerID)
  facts.score = type(score) == "number" and math.floor(score + 0.5) or nil
  facts.open_borders_to_us = Civ6Ai_Snapshot._Method(theirDiplo, "HasOpenBordersFrom", playerID) == true
    or Civ6Ai_Snapshot._Method(myDiplo, "HasOpenBordersFrom", otherID) == true
  facts.defensive_pact = Civ6Ai_Snapshot._Method(myDiplo, "HasDefensivePact", otherID) == true
  facts.declared_friendship = Civ6Ai_Snapshot._Method(myDiplo, "HasDeclaredFriendship", otherID) == true
    or facts.state == "DIPLO_STATE_DECLARED_FRIEND"
  facts.alliance = Civ6Ai_Snapshot._Method(myDiplo, "HasAllied", otherID) == true
    or facts.state == "DIPLO_STATE_ALLIED"
  local allianceType = Civ6Ai_Snapshot._Method(myDiplo, "GetAllianceType", otherID)
  if type(allianceType) == "number" and allianceType >= 0 and GameInfo ~= nil and GameInfo.Alliances ~= nil then
    local row = Civ6Ai_Snapshot._Try(function() return GameInfo.Alliances[allianceType] end)
    facts.alliance_type = row ~= nil and row.AllianceType or nil
    facts.alliance = facts.alliance or facts.alliance_type ~= nil
  end
  facts.denounced = facts.state == "DIPLO_STATE_DENOUNCED"
  -- CanDeclareWarOn / CanMakePeaceWith are the leader-screen checks (CityStates.lua
  -- in the base game). Snapshot is InGame, so they are present; if a ruleset
  -- omits them, war is legal when not already at war / allied / same team, and
  -- peace is legal when at war.
  local canWar = Civ6Ai_Snapshot._Method(myDiplo, "CanDeclareWarOn", otherID)
  if canWar == true then
    facts.can_declare_war = true
  elseif canWar == false then
    facts.can_declare_war = false
  else
    local meTeam = Civ6Ai_Snapshot._Method(me, "GetTeam")
    local themTeam = Civ6Ai_Snapshot._Method(Players[otherID], "GetTeam")
    facts.can_declare_war = facts.at_war ~= true and facts.alliance ~= true
      and (meTeam == nil or themTeam == nil or meTeam ~= themTeam)
  end
  local canPeace = Civ6Ai_Snapshot._Method(myDiplo, "CanMakePeaceWith", otherID)
  -- Peace is only a legal order while at war. CanMakePeaceWith can return
  -- true in peacetime; offering it then produced a drop every turn.
  if facts.at_war == true and canPeace ~= false then
    facts.can_make_peace = true
  else
    facts.can_make_peace = false
  end
  if facts.at_war then
    facts.relationship = "war"
    local since = Civ6Ai_Snapshot._Method(myDiplo, "GetAtWarTurn", otherID)
    if type(since) ~= "number" then
      since = Civ6Ai_Snapshot._Method(myDiplo, "GetDeclaredWarTurn", otherID)
    end
    if type(since) ~= "number" then
      since = Civ6Ai_Snapshot._Method(myDiplo, "GetWarStartTurn", otherID)
    end
    if type(since) == "number" and since >= 0 then
      facts.war_since_turn = math.floor(since)
    end
  elseif facts.alliance then
    facts.relationship = "alliance"
  elseif facts.state ~= nil then
    facts.relationship = Civ6Ai_Snapshot.DIPLO_RELATIONSHIP[facts.state] or "neutral"
  elseif facts.declared_friendship then
    facts.relationship = "declared_friendship"
  end
  return facts
end

function Civ6Ai_Snapshot._HasMet(playerID, otherID)
  local diplo = Civ6Ai_Snapshot._Method(Players[playerID], "GetDiplomacy")
  return Civ6Ai_Snapshot._Method(diplo, "HasMet", otherID) == true
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
      if Civ6Ai_Snapshot._PlayerKind(otherID) == "major" and Civ6Ai_Snapshot._HasMet(playerID, otherID) then
        local other = Players[otherID]
        local facts = Civ6Ai_Snapshot._RelationFacts(playerID, otherID)
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
            at_war = facts.at_war,
            open_borders = facts.open_borders_to_us,
            defensive_pact = facts.defensive_pact,
            vassal = false,
            -- The rival's diplomatic state toward us (DIPLO_STATE_*), the Civ6
            -- counterpart of Civ5's ATTITUDE_*; value is its diplomatic score.
            attitude_id = facts.state or "ATTITUDE_NEUTRAL",
            attitude_value = facts.score or 0,
          },
        })
      end
    end
  end
  return out
end

Civ6Ai_Snapshot.TRADE_RESOURCE_CAP = 12

-- Luxury / strategic stock of a player: { luxuries = {{resource_id, amount}},
-- strategics = {...}, gold = n, gold_per_turn = n } (nil fields when unknown).
function Civ6Ai_Snapshot._TradeInventory(otherID)
  local other = Players[otherID]
  local inv = { luxuries = Civ6Ai_Snapshot._Arr(), strategics = Civ6Ai_Snapshot._Arr() }
  local resources = Civ6Ai_Snapshot._Method(other, "GetResources")
  if resources ~= nil and GameInfo ~= nil and GameInfo.Resources ~= nil then
    pcall(function()
      for row in GameInfo.Resources() do
        local class = row.ResourceClassType
        if class == "RESOURCECLASS_LUXURY" or class == "RESOURCECLASS_STRATEGIC" then
          local amount = Civ6Ai_Snapshot._Method(resources, "GetResourceAmount", row.Index)
          if type(amount) == "number" and amount > 0 then
            local list = class == "RESOURCECLASS_LUXURY" and inv.luxuries or inv.strategics
            table.insert(list, { resource_id = row.ResourceType, amount = math.floor(amount) })
          end
        end
      end
    end)
  end
  local treasury = Civ6Ai_Snapshot._Method(other, "GetTreasury")
  local gold = Civ6Ai_Snapshot._Method(treasury, "GetGoldBalance")
  if type(gold) == "number" then
    inv.gold = math.floor(gold)
  end
  local yield = Civ6Ai_Snapshot._Method(treasury, "GetGoldYield")
  local upkeep = Civ6Ai_Snapshot._Method(treasury, "GetTotalMaintenance")
  if type(yield) == "number" then
    inv.gold_per_turn = math.floor(yield - (type(upkeep) == "number" and upkeep or 0) + 0.5)
  end
  return inv
end

-- civ6.diplomacy: what the Civ5 prompt showed and Civ6 exposes. Majors met
-- (state toward us, relationship, wars incl. theirs with other majors, trade
-- stock), city-states met (suzerain, our envoys), our own trade stock and wars
-- between majors we know. Optional in the schema; the sidecar copes without it.
function Civ6Ai_Snapshot._BuildDiplomacy(playerID)
  local out = {
    majors = Civ6Ai_Snapshot._Arr(),
    city_states = Civ6Ai_Snapshot._Arr(),
    wars = Civ6Ai_Snapshot._Arr(),
  }
  local metMajors = {}
  for otherID = 0, 63 do
    if otherID ~= playerID then
      local kind = Civ6Ai_Snapshot._PlayerKind(otherID)
      if (kind == "major" or kind == "city_state") and Civ6Ai_Snapshot._HasMet(playerID, otherID) then
        if kind == "major" then
          table.insert(metMajors, otherID)
        else
          local influence = Civ6Ai_Snapshot._Method(Players[otherID], "GetInfluence")
          local suzerain = Civ6Ai_Snapshot._Method(influence, "GetSuzerain")
          local envoys = Civ6Ai_Snapshot._Method(influence, "GetTokensReceived", playerID)
          local leader = tostring(Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._LeaderId, otherID) or "")
          local csFacts = Civ6Ai_Snapshot._RelationFacts(playerID, otherID)
          table.insert(out.city_states, {
            player_id = Civ6Ai_Snapshot._PlayerLabel(otherID),
            name = Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._LeaderName, otherID) or Civ6Ai_Snapshot._PlayerLabel(otherID),
            city_state_type = leader:match("^LEADER_MINOR_CIV_(.+)$"),
            suzerain_id = (type(suzerain) == "number" and suzerain >= 0) and Civ6Ai_Snapshot._PlayerLabel(suzerain) or nil,
            your_envoys = type(envoys) == "number" and math.floor(envoys) or nil,
            suzerain_envoys = (type(suzerain) == "number" and suzerain >= 0) and (function()
              local n = Civ6Ai_Snapshot._Method(influence, "GetTokensReceived", suzerain)
              return type(n) == "number" and math.floor(n) or nil
            end)() or nil,
            at_war = csFacts.at_war == true,
            can_declare_war = csFacts.can_declare_war == true,
            can_make_peace = csFacts.can_make_peace == true,
          })
        end
      end
    end
  end
  for _, otherID in ipairs(metMajors) do
    local facts = Civ6Ai_Snapshot._RelationFacts(playerID, otherID)
    local theirDiplo = Civ6Ai_Snapshot._Method(Players[otherID], "GetDiplomacy")
    local atWarWith = Civ6Ai_Snapshot._Arr()
    if Civ6Ai_Snapshot._Method(theirDiplo, "IsAtWarWith", playerID) == true then
      table.insert(atWarWith, Civ6Ai_Snapshot._PlayerLabel(playerID))
    end
    for _, thirdID in ipairs(metMajors) do
      if thirdID ~= otherID and Civ6Ai_Snapshot._Method(theirDiplo, "IsAtWarWith", thirdID) == true then
        table.insert(atWarWith, Civ6Ai_Snapshot._PlayerLabel(thirdID))
        if otherID < thirdID then
          table.insert(out.wars, { Civ6Ai_Snapshot._PlayerLabel(otherID), Civ6Ai_Snapshot._PlayerLabel(thirdID) })
        end
      end
    end
    local inv = Civ6Ai_Snapshot._TradeInventory(otherID)
    table.insert(out.majors, {
      player_id = Civ6Ai_Snapshot._PlayerLabel(otherID),
      state = facts.state,
      relationship = facts.relationship,
      diplomatic_score = facts.score,
      at_war = facts.at_war,
      war_since_turn = facts.war_since_turn,
      can_declare_war = facts.can_declare_war == true,
      can_make_peace = facts.can_make_peace == true,
      denounced = facts.denounced,
      declared_friendship = facts.declared_friendship,
      alliance = facts.alliance,
      alliance_type = facts.alliance_type,
      open_borders = facts.open_borders_to_us,
      defensive_pact = facts.defensive_pact,
      at_war_with = atWarWith,
      reasons = Civ6Ai_Snapshot._AttitudeReasons(otherID, playerID, 3),
      trade = inv,
    })
  end
  out.your_trade = Civ6Ai_Snapshot._TradeInventory(playerID)
  local myInfluence = Civ6Ai_Snapshot._Method(Players[playerID], "GetInfluence")
  local tokens = Civ6Ai_Snapshot._Method(myInfluence, "GetTokensToGive")
  if type(tokens) == "number" then
    out.envoys_to_give = math.floor(tokens)
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

function Civ6Ai_Snapshot._SafeLookup(fn)
  local ok, value = pcall(fn)
  if ok and type(value) == "string" and value ~= "" then
    return value
  end
  return "UNKNOWN"
end

function Civ6Ai_Snapshot._CurrentEraId()
  return Civ6Ai_Snapshot._SafeLookup(function()
    local idx = Game.GetEras():GetCurrentEra()
    local row = GameInfo.Eras[idx]
    return row and row.EraType
  end)
end

function Civ6Ai_Snapshot._GameSpeedId()
  return Civ6Ai_Snapshot._SafeLookup(function()
    local row = GameInfo.GameSpeeds[GameConfiguration.GetGameSpeedType()]
    return row and row.GameSpeedType
  end)
end

function Civ6Ai_Snapshot._MapSizeId()
  return Civ6Ai_Snapshot._SafeLookup(function()
    local row = GameInfo.Maps[Map.GetMapSize()]
    return row and row.MapSizeType
  end)
end

function Civ6Ai_Snapshot._BuildGameBlock()
  local mapWidth, mapHeight = Map.GetGridSize()
  local wrapX, wrapY = Civ6Ai_Snapshot._MapWrap()
  return {
    map_width = mapWidth,
    map_height = mapHeight,
    wrap_x = wrapX,
    wrap_y = wrapY,
    era_id = Civ6Ai_Snapshot._CurrentEraId(),
    game_speed_id = Civ6Ai_Snapshot._GameSpeedId(),
    difficulty_id = "UNKNOWN",
    world_size_id = Civ6Ai_Snapshot._MapSizeId(),
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
  if string.find(upper, "CITY") or string.find(upper, "LOYALTY") or string.find(upper, "DISTRICT")
      or string.find(upper, "WONDER") then
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
  local player = Players[playerID]
  if player ~= nil then
    for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
      local why = Civ6Ai_Snapshot._FoundBlockReason(unit)
      if why ~= nil then
        local wireId = Civ6Ai_Snapshot._UnitWireId(unit)
        table.insert(summary.city_alerts, Civ6Ai_Snapshot._MakeAlert(
          "city", "critical",
          wireId .. " cannot found a city on its tile (" .. why
            .. "). See that settler's settle.here / settle.sites facts (legal tiles only, unranked).",
          { wireId }))
      end
    end
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

-- A seat other than the local one has its orders played at its next turn
-- start (Civ6Ai_Orders queue), when its units have full movement, so its
-- snapshot plans that turn. The local seat's orders run in this turn.
function Civ6Ai_Snapshot._PlansNextTurn(playerID)
  return Game.GetLocalPlayer() ~= playerID
end

-- No seat is offered queue_production. The local seat is the human. AI seats
-- steer what the engine AI builds with set_build_priority.
function Civ6Ai_Snapshot._CanQueueProduction(playerID)
  return false
end

-- Movement the unit has for the model's orders. Prefers the GameCore view (see
-- Civ6Ai_GameCore.UnitMovesForPlayer): the UI cache reads 0 at turn start.
function Civ6Ai_Snapshot._UnitMoves(unit)
  local owner = unit:GetOwner()
  local planning = Civ6Ai_Snapshot._PlansNextTurn(owner)
  -- Pass 1/0. A boolean across the UI/gameplay boundary can arrive as nil,
  -- and a nil planning flag reads GetMovesRemaining (0 at turn start), which
  -- hid every unit of a non-local seat from the prompt.
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes ~= nil and routes.UnitMovesForPlayer ~= nil then
    local ok, moves = pcall(routes.UnitMovesForPlayer, owner, unit:GetID(), planning and 1 or 0)
    if ok and type(moves) == "number" and moves > 0 then
      return moves
    end
  end
  local remaining = tonumber(Civ6Ai_Snapshot._Method(unit, "GetMovesRemaining")) or 0
  if remaining > 0 then
    return remaining
  end
  local maxMoves = tonumber(Civ6Ai_Snapshot._Method(unit, "GetMaxMoves")) or 0
  if maxMoves <= 0 and GameInfo ~= nil and GameInfo.Units ~= nil then
    local row = GameInfo.Units[unit:GetType()]
    maxMoves = row ~= nil and (tonumber(row.BaseMoves) or tonumber(row.Moves) or 0) or 0
  end
  if planning and maxMoves > 0 then
    return maxMoves
  end
  -- Local seat at turn start: GetMovesRemaining is still 0 while MOVE_TO is
  -- already legal. Using 0 hid almost every unit from the prompt.
  if maxMoves > 0 and UnitManager ~= nil and UnitOperationTypes ~= nil
      and UnitOperationTypes.MOVE_TO ~= nil then
    local okCan, can = pcall(UnitManager.CanStartOperation, unit, UnitOperationTypes.MOVE_TO, nil, true)
    if okCan and can == true then
      return maxMoves
    end
  end
  return remaining
end

-- found_city legality. The UI test (nil plot, test only) does not check the site:
-- it offered P0's new settler "found" on the Paris tile itself. The GameCore check
-- has the site rules, so it decides whenever it is available; the local seat also
-- needs the UI test (its found order goes through the UI operation).
function Civ6Ai_Snapshot._CanFoundCity(unit, foundOp)
  local ui = foundOp ~= nil and UnitManager.CanStartOperation(unit, foundOp.Hash, nil, true)
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes == nil or routes.CanFoundCityForPlayer == nil then
    return ui == true
  end
  local gameCore = Civ6Ai_Snapshot._GameCoreCanFound(unit)
  local isLocal = Game ~= nil and Game.GetLocalPlayer ~= nil and unit:GetOwner() == Game.GetLocalPlayer()
  if isLocal then
    return gameCore and ui == true
  end
  return gameCore
end

-- Gameplay-side founding check (Civ6Ai_GameCore.CanFoundCityForPlayer) for
-- settlers the UI check rejects: non-local seats and units with 0 moves.
function Civ6Ai_Snapshot._GameCoreCanFound(unit)
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes == nil or routes.CanFoundCityForPlayer == nil then
    return false
  end
  local ok, can = pcall(routes.CanFoundCityForPlayer, unit:GetOwner(), unit:GetID())
  return ok and can == true
end

-- Why FoundCity is absent for a settler standing on a bad site. Empty when
-- the unit cannot found at all, or when the current tile is a legal city site.
function Civ6Ai_Snapshot._FoundBlockReason(unit)
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes == nil or routes.CanFoundCityForPlayer == nil or unit == nil then
    return nil
  end
  local ok, can, why = pcall(routes.CanFoundCityForPlayer, unit:GetOwner(), unit:GetID())
  if not ok or can == true or why == nil or why == "" or why == "unit_cannot_found_city" then
    return nil
  end
  return tostring(why)
end

-- The UI MOVE_TO test accepts every neighbour for every seat, the local one
-- included (P0's land scout was offered coast 20,24 and its warrior mountain
-- 14,18; both failed every time), so confirm with
-- Civ6Ai_GameCore.CanMoveUnitToForPlayer for all seats.
function Civ6Ai_Snapshot._GameCoreCanMove(unit, x, y)
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes == nil or routes.CanMoveUnitToForPlayer == nil then
    return true
  end
  local owner = unit:GetOwner()
  local ok, can = pcall(routes.CanMoveUnitToForPlayer, owner, unit:GetID(), x, y, Civ6Ai_Snapshot._PlansNextTurn(owner) and 1 or 0)
  return not ok or can == true
end

-- UI GetBuildCharges lags at turn start for the local seat (reads 0), the same
-- class of bug as GetMovesRemaining. Gameplay BuildChargesForPlayer is authoritative.
function Civ6Ai_Snapshot._BuildCharges(unit)
  local ui = Civ6Ai_Snapshot._Method(unit, "GetBuildCharges")
  local core = nil
  local routes = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if routes ~= nil and routes.BuildChargesForPlayer ~= nil and unit ~= nil and unit.GetOwner ~= nil then
    local ok, n = pcall(routes.BuildChargesForPlayer, unit:GetOwner(), unit:GetID())
    if ok and type(n) == "number" then
      core = n
    end
  end
  local charges = core
  if type(charges) ~= "number" then
    charges = tonumber(ui) or 0
  end
  if type(ui) == "number" and type(core) == "number" and ui ~= core then
    Civ6Ai_Util.Log("snapshot|builder_charges|unit=" .. tostring(unit:GetID()) .. "|ui=" .. tostring(ui) .. "|core=" .. tostring(core))
  end
  return charges, ui, core
end

function Civ6Ai_Snapshot._PlotImpassable(plot)
  if plot == nil then
    return false
  end
  if plot.IsImpassable ~= nil and plot:IsImpassable() == true then
    return true
  end
  if plot.IsMountain ~= nil and plot:IsMountain() == true then
    return true
  end
  return false
end

function Civ6Ai_Snapshot._UnitNeedsOrders(unit)
  if unit == nil or unit:GetX() == -9999 then
    return false
  end
  local goal = Civ6Ai_Snapshot._UnitGoal(unit:GetOwner(), unit:GetID())
  if goal ~= nil then
    local plot = Map ~= nil and Map.GetPlot ~= nil and Map.GetPlot(goal.x, goal.y) or nil
    if not Civ6Ai_Snapshot._PlotImpassable(plot) then
      return false
    end
    -- The standing destination is a mountain. Keep the unit in the prompt so
    -- the seat can pick a different tile; gameplay also drops this goal.
    Civ6Ai_Util.Log("snapshot|goal_impassable|unit=" .. tostring(unit:GetID())
      .. "|xy=" .. tostring(goal.x) .. "," .. tostring(goal.y))
  end
  if Civ6Ai_Snapshot._UnitMoves(unit) <= 0 then
    return false
  end
  -- Builders of AI seats stay with the game's own AI. Taking them after two
  -- idle turns handed the model Improve orders that did not stick, and then
  -- finished the builder's moves so the base AI could not build either.
  -- A human seat has no builder AI, so its builders still need orders.
  local charges = select(1, Civ6Ai_Snapshot._BuildCharges(unit))
  if charges > 0 then
    local owner = Players[unit:GetOwner()]
    if owner ~= nil and owner.IsHuman ~= nil and owner:IsHuman() == true then return true end
    return false
  end
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  local great = row ~= nil and ((row.GreatPersonClassType ~= nil and row.GreatPersonClassType ~= "")
      or (row.UnitType ~= nil and string.find(row.UnitType, "GREAT_", 1, true) ~= nil))
  if great then
    local owner = Players[unit:GetOwner()]
    -- A human seat has no great-person AI. An AI seat's own AI activates them.
    if owner ~= nil and owner.IsHuman ~= nil and owner:IsHuman() == true then return true end
    return false
  end
  return true
end

-- Hex rings around each settler (3–5 is what the map overlay draws; snapshot
-- sends every legal revealed site in this radius, unranked).
Civ6Ai_Snapshot.SETTLE_RADIUS = 5
Civ6Ai_Snapshot.SETTLE_SCAN_CAP = 200
Civ6Ai_Snapshot.SETTLE_SITES_CAP = 200
Civ6Ai_Snapshot.COMMAND_RESULTS_CAP = 12

Civ6Ai_Snapshot.KIND_NAMES = {
  [1] = "move_unit", [2] = "set_research_tech", [3] = "set_research_civic", [4] = "found_city",
  [5] = "unit_skip", [6] = "unit_posture_fortify", [7] = "attack_target", [9] = "set_build_priority",
  [10] = "change_government", [11] = "set_policies", [12] = "found_pantheon", [13] = "found_religion",
  [14] = "recruit_great_person", [15] = "patronize_great_person", [16] = "governor",
  [17] = "send_diplomatic_action", [18] = "propose_peace", [19] = "purchase_item",
  [34] = "send_envoy",
  [20] = "purchase_tile", [21] = "worker_improve", [22] = "pillage_improvement",
  [24] = "trade_route", [25] = "explore", [26] = "activate_great_person",
  [27] = "upgrade_unit", [28] = "promote_unit", [29] = "join_formation", [31] = "city_attack", [32] = "build_fort",
  [35] = "spread_religion",
}

Civ6Ai_Snapshot.INTENT_NAMES = {
  [0] = "move", [1] = "found", [2] = "improve", [3] = "found_religion", [4] = "trade",
}

-- Persistent destination from WP-A: split Game properties
-- CIV6AI_GOAL_<owner>_<unitId>_{X,Y,A,T,I}. A is arrival intent (not N).
function Civ6Ai_Snapshot._UnitGoal(playerID, unitNumericId)
  if Game == nil or Game.GetProperty == nil then
    if Game ~= nil then
      Civ6Ai_Util.Log("snapshot|goal_api_missing|GetProperty")
    end
    return nil
  end
  local prefix = "CIV6AI_GOAL_" .. tostring(playerID) .. "_" .. tostring(unitNumericId) .. "_"
  local function prop(field)
    local ok, raw = pcall(function() return Game:GetProperty(prefix .. field) end)
    if not ok then
      Civ6Ai_Util.Log("snapshot|goal_read_failed|" .. tostring(raw))
      return nil
    end
    return tonumber(raw)
  end
  local x, y = prop("X"), prop("Y")
  if x == nil or y == nil or x < 0 or y < 0 then
    return nil
  end
  local a = prop("A") or 0
  local setTurn = prop("T")
  local eta = nil
  if setTurn ~= nil and Game.GetCurrentGameTurn ~= nil then
    eta = math.max(0, 10 - (Game.GetCurrentGameTurn() - setTurn))
  end
  return {
    x = x, y = y,
    intent = Civ6Ai_Snapshot.INTENT_NAMES[a] or tostring(a),
    A = a,
    eta = eta,
  }
end

function Civ6Ai_Snapshot._PlotFreshWater(plot)
  if plot == nil then
    return false
  end
  local ok, fresh = pcall(function() return plot:IsFreshWater() == true or plot:IsRiver() == true end)
  return ok and fresh == true
end

-- Same site rules as Civ6Ai_GameCore._CitySiteProblem (UI scan; no gameplay mutation).
function Civ6Ai_Snapshot._PlotCitySiteProblem(playerID, x, y)
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return "plot_not_found"
  end
  if (plot.IsWater ~= nil and plot:IsWater()) or (plot.IsImpassable ~= nil and plot:IsImpassable()) then
    return "invalid_city_site"
  end
  if Map.GetPlotDistance == nil then
    return nil
  end
  local tooClose = false
  pcall(function()
    for pid = 0, 63 do
      local other = Players[pid]
      local otherCities = other ~= nil and other:GetCities() or nil
      if otherCities ~= nil and otherCities.Members ~= nil then
        for _, city in otherCities:Members() do
          if Map.GetPlotDistance(x, y, city:GetX(), city:GetY()) < 4 then
            tooClose = true
            return
          end
        end
      end
    end
  end)
  if tooClose then
    return "too_close_to_city"
  end
  local owner = plot.GetOwner ~= nil and plot:GetOwner() or -1
  if owner ~= nil and owner >= 0 and owner ~= playerID then
    return "foreign_territory"
  end
  return nil
end

function Civ6Ai_Snapshot._AddSettleFacts(unit)
  local typeName = nil
  pcall(function() typeName = Civ6Ai_Snapshot._UnitTypeName(unit) end)
  local row = nil
  pcall(function()
    row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  end)
  local canFoundUnit = typeName == "UNIT_SETTLER" or (row ~= nil and (row.FoundCity == true or row.FoundCity == 1))
  if not canFoundUnit then
    return nil
  end
  local x, y = unit:GetX(), unit:GetY()
  local playerID = unit:GetOwner()
  local hereReason = Civ6Ai_Snapshot._FoundBlockReason(unit)
  local hereOk = Civ6Ai_Snapshot._GameCoreCanFound(unit)
  if hereReason == nil and hereOk ~= true then
    hereReason = Civ6Ai_Snapshot._PlotCitySiteProblem(playerID, x, y)
  end
  local herePlot = Map.GetPlot(x, y)
  local sites = {}
  local scanned = 0
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  for dy = -Civ6Ai_Snapshot.SETTLE_RADIUS, Civ6Ai_Snapshot.SETTLE_RADIUS do
    for dx = -Civ6Ai_Snapshot.SETTLE_RADIUS, Civ6Ai_Snapshot.SETTLE_RADIUS do
      if scanned >= Civ6Ai_Snapshot.SETTLE_SCAN_CAP then
        break
      end
      local tx, ty = x + dx, y + dy
      local dist = nil
      if Map.GetPlotDistance ~= nil then
        dist = Map.GetPlotDistance(x, y, tx, ty)
      else
        dist = math.abs(dx) + math.abs(dy)
      end
      if dist ~= nil and dist >= 1 and dist <= Civ6Ai_Snapshot.SETTLE_RADIUS then
        local plot = Map.GetPlot(tx, ty)
        if plot ~= nil then
          scanned = scanned + 1
          local revealed = true
          if vis ~= nil and vis.IsRevealed ~= nil then
            local okRev, isRev = pcall(function() return vis:IsRevealed(plot:GetIndex()) end)
            revealed = (not okRev) or isRev == true
          end
          local okPath, path = pcall(function() return UnitManager.GetMoveToPath(unit, plot:GetIndex()) end)
          if revealed and (not okPath or (type(path) == "table" and #path > 0))
              and Civ6Ai_Snapshot._PlotCitySiteProblem(playerID, tx, ty) == nil then
            table.insert(sites, {
              x = tx, y = ty, dist = dist,
              coastal = Civ6Ai_Snapshot._PlotIsCoastal(tx, ty),
              fresh_water = Civ6Ai_Snapshot._PlotFreshWater(plot),
            })
          end
        end
      end
    end
    if scanned >= Civ6Ai_Snapshot.SETTLE_SCAN_CAP then
      break
    end
  end
  table.sort(sites, function(a, b)
    if a.dist ~= b.dist then
      return a.dist < b.dist
    end
    if a.x ~= b.x then
      return a.x < b.x
    end
    return a.y < b.y
  end)
  local embark = nil
  if #sites == 0 then
    local unitArea = Civ6Ai_Snapshot._AreaId(herePlot)
    local best = nil
    local radius = 12
    for dy = -radius, radius do
      for dx = -radius, radius do
        local tx, ty = x + dx, y + dy
        local dist = Map.GetPlotDistance ~= nil and Map.GetPlotDistance(x, y, tx, ty) or (math.abs(dx) + math.abs(dy))
        if dist >= 1 and dist <= radius and (best == nil or dist < best.dist) then
          local plot = Map.GetPlot(tx, ty)
          if plot ~= nil and Civ6Ai_Snapshot._PlotCitySiteProblem(playerID, tx, ty) == nil then
            local revealed = true
            if vis ~= nil and vis.IsRevealed ~= nil then
              local okRev, isRev = pcall(function() return vis:IsRevealed(plot:GetIndex()) end)
              revealed = (not okRev) or isRev == true
            end
            local plotArea = Civ6Ai_Snapshot._AreaId(plot)
            if revealed and unitArea ~= nil and plotArea ~= nil and plotArea ~= unitArea then
              best = { x = tx, y = ty, dist = dist }
            end
          end
        end
      end
    end
    if best ~= nil then
      local techs = Players[playerID] ~= nil and Players[playerID].GetTechs ~= nil and Players[playerID]:GetTechs() or nil
      local function known(name)
        local row = GameInfo.Technologies ~= nil and GameInfo.Technologies[name] or nil
        return row ~= nil and techs ~= nil and techs.HasTech ~= nil and techs:HasTech(row.Index) == true
      end
      best.can_embark = known("TECH_SHIPBUILDING")
      best.can_ocean = known("TECH_CARTOGRAPHY")
      embark = best
    end
  end
  return {
    here_ok = hereOk == true,
    here_reason = hereReason,
    coastal = Civ6Ai_Snapshot._PlotIsCoastal(x, y),
    fresh_water = Civ6Ai_Snapshot._PlotFreshWater(herePlot),
    sites = sites,
    no_reachable_site = #sites == 0,
    embark_site = embark,
  }
end

function Civ6Ai_Snapshot._NetworkMultiplayer()
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    local ok, mp = pcall(GameConfiguration.IsNetworkMultiplayer, GameConfiguration)
    if ok then
      return mp == true
    end
  end
  if Game ~= nil and Game.IsNetworkMultiplayer ~= nil then
    local ok, mp = pcall(function() return Game.IsNetworkMultiplayer() end)
    if ok then
      return mp == true
    end
  end
  return false
end

function Civ6Ai_Snapshot._AddCommandResults(playerID, turn)
  local out = Civ6Ai_Util.JsonArrayList()
  local shared = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  local rows = shared ~= nil and shared.OrderResults or nil
  if type(rows) ~= "table" then
    return out
  end
  local matched = {}
  local fallback = {}
  for i = 1, #rows do
    local r = rows[i]
    if type(r) == "table" and (r.player == playerID or r.P == playerID) then
      local applyTurn = tonumber(r.apply_turn or r.turn) or turn
      local decisionTurn = tonumber(r.decision_turn)
      if decisionTurn == nil then
        if Civ6Ai_Snapshot._NetworkMultiplayer() then
          decisionTurn = applyTurn - 1
        else
          decisionTurn = applyTurn
        end
      end
      local kindNum = tonumber(r.kind or r.K)
      local kindName = Civ6Ai_Snapshot.KIND_NAMES[kindNum] or tostring(r.kind or "order")
      local ok = r.ok == true
      local reason = tostring(r.reason or "")
      local unit = r.unit
      if type(unit) == "number" then
        unit = "UNIT_" .. tostring(unit)
      elseif unit == nil and r.U ~= nil then
        unit = "UNIT_" .. tostring(r.U)
      end
      local effect = "none"
      if ok and reason ~= "already_there" and reason ~= "plot_unchanged" then
        effect = "applied"
      elseif ok then
        effect = "no_effect"
      else
        effect = "failed"
      end
      local summary = (ok and "ok" or "fail") .. " " .. kindName
      if reason ~= "" then
        summary = summary .. " " .. reason
      end
      if string.len(summary) > 300 then
        summary = string.sub(summary, 1, 300)
      end
      local item = {
        turn = decisionTurn,
        kind = kindName,
        summary = summary,
        affected_ids = unit ~= nil and { tostring(unit) } or {},
        decision_turn = decisionTurn,
        apply_turn = applyTurn,
        unit = unit,
        ok = ok,
        reason = reason,
        effect = effect,
      }
      table.insert(fallback, item)
      if decisionTurn == turn - 1 then
        table.insert(matched, item)
      end
    end
  end
  local picked = #matched > 0 and matched or fallback
  local start = math.max(1, #picked - Civ6Ai_Snapshot.COMMAND_RESULTS_CAP + 1)
  for i = start, #picked do
    table.insert(out, picked[i])
  end
  return out
end

function Civ6Ai_Snapshot._UnitAdjacentToEnemy(playerID, unit)
  local x, y = unit:GetX(), unit:GetY()
  for direction = 0, 5 do
    local adj = Map.GetAdjacentPlot(x, y, direction)
    if adj ~= nil and Civ6Ai_Snapshot._EnemyAtPlot(playerID, adj) ~= nil then
      return true
    end
  end
  return false
end

function Civ6Ai_Snapshot._NearestOwnHolySite(playerID, ux, uy)
  local player = Players[playerID]
  if player == nil or player.GetCities == nil then
    return nil
  end
  local distIdx = GameInfo ~= nil and GameInfo.Districts ~= nil and GameInfo.Districts["DISTRICT_HOLY_SITE"] or nil
  local want = distIdx ~= nil and distIdx.Index or nil
  local best, bestDist = nil, nil
  pcall(function()
    for _, city in player:GetCities():Members() do
      local districts = city.GetDistricts ~= nil and city:GetDistricts() or nil
      if districts ~= nil then
        local d = nil
        if want ~= nil and districts.GetDistrictByType ~= nil then
          d = districts:GetDistrictByType(want)
        end
        if d ~= nil and d.IsComplete ~= nil and d:IsComplete() == true then
          local dx, dy = d:GetX(), d:GetY()
          local dist = Map.GetPlotDistance ~= nil and Map.GetPlotDistance(ux, uy, dx, dy) or 99
          if bestDist == nil or dist < bestDist then
            bestDist = dist
            best = { x = dx, y = dy, dist = dist }
          end
        end
      end
    end
  end)
  return best
end

function Civ6Ai_Snapshot._UnitHealth(unit)
  -- Civ6: damage accumulates toward MaxDamage; remaining HP = max - damage.
  local maxHp = 100
  if unit.GetMaxDamage ~= nil then
    maxHp = unit:GetMaxDamage() or maxHp
  elseif unit.GetMaxHitPoints ~= nil then
    maxHp = unit:GetMaxHitPoints() or maxHp
  end
  local damage = 0
  if unit.GetDamage ~= nil then
    damage = unit:GetDamage() or 0
  end
  local current = maxHp - damage
  if current < 0 then
    current = 0
  end
  if maxHp <= 0 then
    maxHp = 100
    current = 100
  end
  return current, maxHp
end

function Civ6Ai_Snapshot._UnitPromotionReady(unit)
  if unit == nil then
    return false
  end
  -- CanPromote lives on the experience object. The unit itself has neither
  -- IsPromotionReady nor CanPromote, so checking those never offered a promotion.
  local exp = Civ6Ai_Snapshot._Method(unit, "GetExperience")
  if exp ~= nil and exp.CanPromote ~= nil then
    local ok, can = pcall(function() return exp:CanPromote() end)
    if ok then
      return can == true
    end
  end
  if exp ~= nil and exp.GetExperiencePoints ~= nil and exp.GetExperienceForNextLevel ~= nil then
    local okPts, pts = pcall(function() return exp:GetExperiencePoints() end)
    local okNeed, need = pcall(function() return exp:GetExperienceForNextLevel() end)
    if okPts and okNeed and type(pts) == "number" and type(need) == "number" and need > 0 and pts >= need then
      return true
    end
  end
  if unit.IsPromotionReady ~= nil then
    return unit:IsPromotionReady() == true
  end
  if unit.CanPromote ~= nil then
    return unit:CanPromote() == true
  end
  return false
end

function Civ6Ai_Snapshot._HeldPromotions(unit)
  local exp, out = Civ6Ai_Snapshot._Method(unit, "GetExperience"), {}
  if exp == nil or exp.HasPromotion == nil then return out end
  for promo in GameInfo.UnitPromotions() do
    if exp:HasPromotion(promo.Index) == true then out[#out + 1] = promo.UnitPromotionType end
  end
  return out
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
    local moves = Civ6Ai_Snapshot._UnitMoves(unit)
    local maxMoves = unit:GetMaxMoves()
    local needsOrders = Civ6Ai_Snapshot._UnitNeedsOrders(unit)
    local curHp, maxHp = Civ6Ai_Snapshot._UnitHealth(unit)
    local promoReady = Civ6Ai_Snapshot._UnitPromotionReady(unit)
    local info = Civ6Ai_Snapshot._UnitInfo(unit)
    local rec = {
      unit_id = Civ6Ai_Snapshot._UnitWireId(unit),
      unit_type_id = Civ6Ai_Snapshot._UnitTypeName(unit),
      unit_class_id = info.formation or "UNITCLASS_UNKNOWN",
      domain_id = info.domain or "DOMAIN_LAND",
      plot_id = Civ6Ai_Util.PlotId(x, y),
      health = {current = curHp, maximum = maxHp, change_per_turn = 0},
      health_percent = maxHp > 0 and math.floor(100 * curHp / maxHp) or 100,
      strength = {current = info.combat, maximum = info.combat, change_per_turn = 0},
      movement = {current = moves, maximum = maxMoves, change_per_turn = 0},
      level = Civ6Ai_Snapshot._Method(Civ6Ai_Snapshot._Method(unit, "GetExperience"), "GetLevel") or 1,
      experience = Civ6Ai_Snapshot._Method(Civ6Ai_Snapshot._Method(unit, "GetExperience"), "GetExperiencePoints") or 0,
      promotion_ids = Civ6Ai_Snapshot._HeldPromotions(unit),
      promotion_ready = promoReady,
      activity_id = "ACTIVITY_UNKNOWN",
      mission_queue = {},
      unit_ai_role = "UNITAI_UNKNOWN",
      cargo_unit_ids = {},
      can_act = needsOrders,
      needs_orders = needsOrders,
      upgrade_options = Civ6Ai_Snapshot._UpgradeOptions(playerID, unit),
    }
    local charges = select(1, Civ6Ai_Snapshot._BuildCharges(unit))
    if charges > 0 then
      rec.build_charges = charges
    end
    local goal = Civ6Ai_Snapshot._UnitGoal(playerID, unit:GetID())
    if goal ~= nil then
      rec.goal = goal
    end
    local okSettle, settleVal = pcall(Civ6Ai_Snapshot._AddSettleFacts, unit)
    if okSettle and settleVal ~= nil then
      rec.settle = settleVal
    elseif not okSettle then
      Civ6Ai_Util.Log("snapshot|settle_facts_failed|" .. tostring(settleVal))
    end
    table.insert(units, rec)
  end
  return units
end

-- Plots the engine says the unit can reach this turn (UI-side
-- UnitManager.GetReachableMovement, a list of plot indices). nil when the API is
-- missing or has nothing to say: a seat planning its next turn has spent its
-- moves this turn, so its targets rest on the GameCore step-cost check alone.
function Civ6Ai_Snapshot._ReachablePlotSet(unit)
  if UnitManager == nil or UnitManager.GetReachableMovement == nil then
    return nil
  end
  local okMoves, moves = pcall(function() return unit:GetMovesRemaining() end)
  if not okMoves or type(moves) ~= "number" or moves <= 0 then
    return nil
  end
  local ok, list = pcall(UnitManager.GetReachableMovement, unit)
  if not ok or type(list) ~= "table" then
    return nil
  end
  local set = {}
  local any = false
  for _, plotIndex in pairs(list) do
    if type(plotIndex) == "number" then
      set[plotIndex] = true
      any = true
    end
  end
  if not any then
    return nil
  end
  return set
end

function Civ6Ai_Snapshot._PlotIndex(plot)
  if plot == nil or plot.GetIndex == nil then
    return nil
  end
  local ok, index = pcall(function() return plot:GetIndex() end)
  if ok and type(index) == "number" then
    return index
  end
  return nil
end

-- Neighbour steps for combat units standing next to a visible enemy. Open
-- moveTo=(x,y) covers every other destination; listing six neighbours for every
-- unit bloated the prompt and invited illegal water/mountain steps.
function Civ6Ai_Snapshot._AddAdjacentMoveCommands(commands, unit, unitId)
  local info = Civ6Ai_Snapshot._UnitInfo(unit)
  if not Civ6Ai_Snapshot._IsMilitaryInfo(info) then
    return
  end
  if not Civ6Ai_Snapshot._UnitAdjacentToEnemy(unit:GetOwner(), unit) then
    return
  end
  local x = unit:GetX()
  local y = unit:GetY()
  local reachable = Civ6Ai_Snapshot._ReachablePlotSet(unit)
  for direction = 0, 5 do
    local adjPlot = Map.GetAdjacentPlot(x, y, direction)
    if adjPlot ~= nil then
      local ax = adjPlot:GetX()
      local ay = adjPlot:GetY()
      local index = reachable ~= nil and Civ6Ai_Snapshot._PlotIndex(adjPlot) or nil
      local engineOk = reachable == nil or index == nil or reachable[index] == true
      if not engineOk and Civ6Ai_Snapshot._GameCoreCanMove(unit, ax, ay) then
        -- Evidence for the first-step rule: the step check allows it, the
        -- engine's reachable list does not.
        Civ6Ai_Util.Log("snapshot|reach_excludes|player=" .. tostring(unit:GetOwner()) .. "|unit=" .. tostring(unit:GetID())
          .. "|plot=" .. tostring(ax) .. "," .. tostring(ay))
      end
      if engineOk
          and UnitManager.CanStartOperation(unit, UnitOperationTypes.MOVE_TO, adjPlot, true)
          and Civ6Ai_Snapshot._GameCoreCanMove(unit, ax, ay) then
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
end

Civ6Ai_Snapshot.PURCHASE_UNAVAILABLE = 1000000000
Civ6Ai_Snapshot.PURCHASE_PER_CITY_CAP = 12
Civ6Ai_Snapshot.TILE_PURCHASE_CAP = 8
Civ6Ai_Snapshot.TILE_PURCHASE_RANGE = 3

function Civ6Ai_Snapshot._YieldIndex(yieldType)
  if GameInfo == nil or GameInfo.Yields == nil then
    return nil
  end
  local row = GameInfo.Yields[yieldType]
  return row ~= nil and row.Index or nil
end

-- Gold/faith price the city gold object reports, or nil when that item cannot
-- be bought (0 or the engine's INT_MAX "unavailable" sentinel).
function Civ6Ai_Snapshot._PurchaseCost(city, yieldType, hash, formation)
  local gold = Civ6Ai_Snapshot._Method(city, "GetGold")
  local y = Civ6Ai_Snapshot._YieldIndex(yieldType)
  if y == nil then
    y = yieldType == "YIELD_FAITH" and 5 or 0
  end
  if gold == nil or hash == nil then
    return nil
  end
  local cost
  if formation ~= nil then
    cost = Civ6Ai_Snapshot._Method(gold, "GetPurchaseCost", y, hash, formation)
  else
    cost = Civ6Ai_Snapshot._Method(gold, "GetPurchaseCost", y, hash)
  end
  local bq = Civ6Ai_Snapshot._Method(city, "GetBuildQueue")
  local canProduce = false
  if bq ~= nil and bq.CanProduce ~= nil then
    local okCan, produced = pcall(bq.CanProduce, bq, hash, true)
    canProduce = okCan and produced == true
  end
  if not canProduce or type(cost) ~= "number" or cost <= 0 or cost >= Civ6Ai_Snapshot.PURCHASE_UNAVAILABLE then
    return nil
  end
  return math.floor(cost)
end

function Civ6Ai_Snapshot._CanStartPurchase(city, params)
  if CityManager == nil or CityManager.CanStartCommand == nil
      or CityCommandTypes == nil or CityCommandTypes.PURCHASE == nil then
    return nil
  end
  local ok, can = pcall(function()
    return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, true, params, false)
  end)
  if not ok then
    return nil
  end
  return can == true
end

function Civ6Ai_Snapshot._GoldBalance(playerID)
  local treasury = Civ6Ai_Snapshot._Method(Players[playerID], "GetTreasury")
  local gold = Civ6Ai_Snapshot._Method(treasury, "GetGoldBalance")
  return type(gold) == "number" and gold or 0
end

function Civ6Ai_Snapshot._FaithBalance(playerID)
  local rel = Civ6Ai_Snapshot._Method(Players[playerID], "GetReligion")
  local faith = Civ6Ai_Snapshot._Method(rel, "GetFaithBalance")
  return type(faith) == "number" and faith or 0
end

-- Gold/faith unit and building buys, plus tiles the city gold object prices.
-- CityManager.CanStartCommand(PURCHASE) is the production-screen check and is
-- only reliable for the local city; other seats use GetPurchaseCost (the same
-- CityGold object PlotInfo.lua / ProductionPanel.lua read).
function Civ6Ai_Snapshot._AddPurchaseCommands(commands, playerID)
  local player = Players[playerID]
  if player == nil or GameInfo == nil or Civ6Ai_Production == nil then
    return
  end
  local cities = player.GetCities ~= nil and player:GetCities() or nil
  if cities == nil then
    return
  end
  local goldBal = Civ6Ai_Snapshot._GoldBalance(playerID)
  local faithBal = Civ6Ai_Snapshot._FaithBalance(playerID)
  local formation = MilitaryFormationTypes ~= nil and MilitaryFormationTypes.STANDARD_MILITARY_FORMATION or nil
  local goldYield = "YIELD_GOLD"
  local faithYield = "YIELD_FAITH"
  for _, city in cities:Members() do
    local cityId = Civ6Ai_Production._WireCityId(city)
    local added = 0
    local function offer(kind, fixed, suffix)
      table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
        command_id = "CMD_" .. suffix .. "_" .. cityId,
        kind = kind,
        fixed_arguments = fixed,
      }))
      added = added + 1
    end
    local function tryItem(itemId, hash, isUnit)
      if added >= Civ6Ai_Snapshot.PURCHASE_PER_CITY_CAP then
        return
      end
      for _, pair in ipairs({ { goldYield, goldBal, "gold" }, { faithYield, faithBal, "faith" } }) do
        local yieldType, bal, yieldName = pair[1], pair[2], pair[3]
        local cost = isUnit
          and Civ6Ai_Snapshot._PurchaseCost(city, yieldType, hash, formation)
          or Civ6Ai_Snapshot._PurchaseCost(city, yieldType, hash)
        if cost ~= nil and cost <= bal then
          do
            local fixed = { city_id = cityId, item_id = itemId, cost = cost }
            if yieldName == "faith" then
              fixed["yield"] = "faith"
            end
            offer("purchase_item", fixed, "buy_" .. itemId .. "_" .. yieldName)
            break
          end
        end
      end
    end
    if GameInfo.Units ~= nil then
      for row in GameInfo.Units() do
        if added >= Civ6Ai_Snapshot.PURCHASE_PER_CITY_CAP then break end
        tryItem(row.UnitType, row.Hash, true)
      end
    end
    if GameInfo.Buildings ~= nil then
      for row in GameInfo.Buildings() do
        if added >= Civ6Ai_Snapshot.PURCHASE_PER_CITY_CAP then break end
        if not row.IsWonder then
          local buildings = Civ6Ai_Snapshot._Method(city, "GetBuildings")
          if Civ6Ai_Snapshot._Method(buildings, "HasBuilding", row.Index) ~= true then
            tryItem(row.BuildingType, row.Hash, false)
          end
        end
      end
    end
    local tileAdded = 0
    local cx, cy = city:GetX(), city:GetY()
    local cityGold = Civ6Ai_Snapshot._Method(city, "GetGold")
    local range = Civ6Ai_Snapshot.TILE_PURCHASE_RANGE
    for dy = -range, range do
      for dx = -range, range do
        if tileAdded >= Civ6Ai_Snapshot.TILE_PURCHASE_CAP then break end
        local plot = Map.GetPlot(cx + dx, cy + dy)
        if plot ~= nil then
          local dist = Map.GetPlotDistance(cx, cy, plot:GetX(), plot:GetY())
          local owner = Civ6Ai_Snapshot._Method(plot, "GetOwner")
          local unowned = owner == nil or owner < 0
          if dist >= 1 and dist <= range and unowned then
            local index = Civ6Ai_Snapshot._Method(plot, "GetIndex")
            local cost = type(index) == "number" and Civ6Ai_Snapshot._Method(cityGold, "GetPlotPurchaseCost", index) or nil
            if type(cost) == "number" and cost > 0 and cost < Civ6Ai_Snapshot.PURCHASE_UNAVAILABLE and cost <= goldBal then
              local params = {}
              if CityCommandTypes ~= nil then
                if CityCommandTypes.PARAM_X ~= nil then
                  params[CityCommandTypes.PARAM_X] = plot:GetX()
                  params[CityCommandTypes.PARAM_Y] = plot:GetY()
                end
                if Civ6Ai_Snapshot._YieldIndex(goldYield) ~= nil then
                  params[CityCommandTypes.PARAM_YIELD_TYPE] = Civ6Ai_Snapshot._YieldIndex(goldYield)
                end
              end
              local can = Civ6Ai_Snapshot._CanStartPurchase(city, params)
              if can ~= false then
                offer("purchase_tile", {
                  city_id = cityId,
                  target_x = plot:GetX(),
                  target_y = plot:GetY(),
                }, "tile_" .. tostring(plot:GetX()) .. "_" .. tostring(plot:GetY()))
                tileAdded = tileAdded + 1
              end
            end
          end
        end
      end
    end
  end
end

function Civ6Ai_Snapshot._IsEnemyOwner(playerID, ownerID)
  if ownerID == nil or ownerID < 0 or ownerID == playerID then
    return false
  end
  local owner = Players[ownerID]
  if owner == nil then
    return false
  end
  if owner.IsBarbarian ~= nil and owner:IsBarbarian() then
    return true
  end
  local ok, atWar = pcall(function()
    return Players[playerID]:GetDiplomacy():IsAtWarWith(ownerID)
  end)
  return ok and atWar == true
end

function Civ6Ai_Snapshot._PlotVisible(playerID, x, y)
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  if vis == nil or vis.IsVisible == nil then
    return true
  end
  local plot = Map.GetPlot ~= nil and Map.GetPlot(x, y) or nil
  if plot ~= nil and plot.GetIndex ~= nil then
    local ok, visible = pcall(function() return vis:IsVisible(plot:GetIndex()) end)
    if ok then
      return visible == true
    end
  end
  local ok2, visible2 = pcall(function() return vis:IsVisible(x, y) end)
  if ok2 and visible2 == false then
    return false
  end
  return true
end

function Civ6Ai_Snapshot._EnemyAtPlot(playerID, plot)
  if plot == nil then
    return nil
  end
  local x, y = plot:GetX(), plot:GetY()
  if not Civ6Ai_Snapshot._PlotVisible(playerID, x, y) then
    return nil
  end
  local cityOk, city = pcall(function() return Cities.GetCityInPlot(x, y) end)
  if cityOk and city ~= nil and Civ6Ai_Snapshot._IsEnemyOwner(playerID, city:GetOwner()) then
    return "city"
  end
  local unitsOk, units = pcall(function() return Units.GetUnitsInPlot(plot) end)
  if unitsOk and units ~= nil then
    for _, other in ipairs(units) do
      if other ~= nil and Civ6Ai_Snapshot._IsEnemyOwner(playerID, other:GetOwner()) then
        return "unit"
      end
    end
  end
  return nil
end

function Civ6Ai_Snapshot._HostileTargets(playerID)
  if Civ6Ai_Snapshot._hostileCachePlayer == playerID and Civ6Ai_Snapshot._hostileCache ~= nil then
    return Civ6Ai_Snapshot._hostileCache
  end
  local hostiles, cities = Civ6Ai_Snapshot._VisibleHostiles(playerID)
  local targets = {}
  for _, h in ipairs(hostiles) do
    table.insert(targets, {x = h.x, y = h.y, who = "unit"})
  end
  for _, c in ipairs(cities) do
    table.insert(targets, {x = c.x, y = c.y, who = "city"})
  end
  Civ6Ai_Snapshot._hostileCachePlayer = playerID
  Civ6Ai_Snapshot._hostileCache = targets
  return targets
end

-- AI seats and the single-player local seat execute attacks with the gameplay
-- resolver, which matches these distance offers. A network game's local seat
-- uses the UI operation instead, so only list a strike that operation can start.
function Civ6Ai_Snapshot._AttackCanExecute(playerID, unit, x, y)
  local mp = GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil
    and GameConfiguration.IsNetworkMultiplayer()
  if not mp or Game == nil or Game.GetLocalPlayer == nil or Game.GetLocalPlayer() ~= playerID then
    return true
  end
  if Civ6Ai_Apply == nil or Civ6Ai_Apply._AttackPlan == nil then
    return true
  end
  return Civ6Ai_Apply._AttackPlan(unit, x, y) ~= nil
end

function Civ6Ai_Snapshot._OfferAttack(commands, seen, unitId, tx, ty, kind, ranged)
  local key = tostring(tx) .. "," .. tostring(ty)
  if seen[key] then
    return
  end
  seen[key] = true
  table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
    command_id = "CMD_attack_" .. unitId .. "_" .. tostring(tx) .. "_" .. tostring(ty),
    kind = "attack_target",
    fixed_arguments = {
      unit_id = unitId, target_x = tx, target_y = ty,
      target_kind = kind, ranged = ranged,
    },
  }))
end

function Civ6Ai_Snapshot._AddAttackCommands(commands, playerID, unit, unitId)
  local info = Civ6Ai_Snapshot._UnitInfo(unit)
  if not Civ6Ai_Snapshot._IsMilitaryInfo(info) then
    return
  end
  local x, y = unit:GetX(), unit:GetY()
  local ranged = (info.ranged or 0) > 0 and (info.range or 0) > 0
  local reach = ranged and (tonumber(info.range) or 0) or 1
  local seen = {}
  for _, target in ipairs(Civ6Ai_Snapshot._HostileTargets(playerID)) do
    local dist = Civ6Ai_Snapshot._Dist(x, y, target.x, target.y)
    if dist >= 1 and dist <= reach
        and Civ6Ai_Snapshot._AttackCanExecute(playerID, unit, target.x, target.y) then
      Civ6Ai_Snapshot._OfferAttack(commands, seen, unitId, target.x, target.y, target.who, ranged)
    end
  end
  local plots = {}
  if ranged and Map.GetNeighborPlots ~= nil then
    local ok, list = pcall(function() return Map.GetNeighborPlots(x, y, info.range) end)
    if ok and list ~= nil then plots = list end
  else
    for direction = 0, 5 do
      local adj = Map.GetAdjacentPlot(x, y, direction)
      if adj ~= nil then table.insert(plots, adj) end
    end
  end
  for _, plot in ipairs(plots) do
    local tx, ty = plot:GetX(), plot:GetY()
    if not (tx == x and ty == y) and Civ6Ai_Snapshot._EnemyAtPlot(playerID, plot) ~= nil
        and Civ6Ai_Snapshot._AttackCanExecute(playerID, unit, tx, ty) then
      Civ6Ai_Snapshot._OfferAttack(commands, seen, unitId, tx, ty, Civ6Ai_Snapshot._EnemyAtPlot(playerID, plot), ranged)
    end
  end
end

-- Pillage the improvement the unit is standing on. Legality is the plot state
-- (PlotToolTip's IsImprovementPillaged), not CanStartOperation, which is a
-- local-player UI check and is empty for an AI seat.
function Civ6Ai_Snapshot._AddPillageCommand(commands, unit, unitId)
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  if row == nil or (tonumber(row.Combat) or 0) <= 0 then
    return
  end
  local plot = Map.GetPlot(unit:GetX(), unit:GetY())
  if plot == nil or plot.IsImprovementPillaged == nil or plot.GetImprovementType == nil then
    return
  end
  local imp = plot:GetImprovementType()
  if type(imp) ~= "number" or imp < 0 or plot:IsImprovementPillaged() == true then
    return
  end
  local irow = GameInfo.Improvements ~= nil and GameInfo.Improvements[imp] or nil
  table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
    command_id = "CMD_pillage_" .. unitId,
    kind = "pillage_improvement",
    fixed_arguments = {
      unit_id = unitId,
      improvement_id = irow ~= nil and irow.ImprovementType or nil,
      target_x = plot:GetX(),
      target_y = plot:GetY(),
    },
  }))
end

function Civ6Ai_Snapshot._AddTradeRouteCommands(commands, playerID, unit, unitId)
  -- Creating a route is a UI operation, and a host UI request does not sync
  -- for an AI seat (Gov.MakeTradeRoute). Offering it failed on every send.
  -- Traders stay with the game's own AI.
end

-- Schema upgrade list: {} or {{unit_type_id, gold_cost}}.
function Civ6Ai_Snapshot._UpgradeOptions(playerID, unit)
  local up, cost = Civ6Ai_Snapshot._UpgradeTarget(playerID, unit)
  if up == nil then return {} end
  return {{unit_type_id = up, gold_cost = cost}}
end

-- Upgrade target the seat can afford now (tech, gold, own territory), or nil.
function Civ6Ai_Snapshot._UpgradeTarget(playerID, unit)
  local M, p = Civ6Ai_Snapshot._Method, Players[playerID]
  local up = GameInfo.UnitUpgrades ~= nil and GameInfo.UnitUpgrades[GameInfo.Units[unit:GetType()].UnitType] or nil
  local row = up ~= nil and GameInfo.Units[up.UpgradeUnit] or nil
  if row == nil then return nil end
  local cfg = PlayerConfigurations ~= nil and PlayerConfigurations[playerID] or nil
  local mine = {}
  for _, t in ipairs({"CivilizationTraits", "LeaderTraits"}) do
    for r in GameInfo[t]() do
      if r.CivilizationType == M(cfg, "GetCivilizationTypeName") or r.LeaderType == M(cfg, "GetLeaderTypeName") then mine[r.TraitType] = true end
    end
  end
  for r in GameInfo.UnitReplaces() do
    local u = r.ReplacesUnitType == row.UnitType and GameInfo.Units[r.CivUniqueUnitType] or nil
    if u ~= nil and mine[u.TraitType] then row = u end
  end
  local res = row.StrategicResource ~= nil and GameInfo.Resources[row.StrategicResource] or nil
  local xp2 = GameInfo.Units_XP2 ~= nil and GameInfo.Units_XP2[row.UnitType] or nil
  if res ~= nil and (M(M(p, "GetResources"), "GetResourceAmount", res.Index) or 0) < math.max(1, xp2 ~= nil and tonumber(xp2.ResourceCost) or 1) then
    return nil
  end
  local tech = row.PrereqTech ~= nil and GameInfo.Technologies[row.PrereqTech] or nil
  local civic = row.PrereqCivic ~= nil and GameInfo.Civics[row.PrereqCivic] or nil
  local cost = M(unit, "GetUpgradeCost") or 0
  local plot = Map.GetPlot(unit:GetX(), unit:GetY())
  if (tech ~= nil and M(M(p, "GetTechs"), "HasTech", tech.Index) ~= true)
      or (civic ~= nil and M(M(p, "GetCulture"), "HasCivic", civic.Index) ~= true)
      or cost <= 0 then
    return nil
  end
  local gold = M(M(p, "GetTreasury"), "GetGoldBalance") or 0
  local affordable = gold >= cost and M(plot, "GetOwner") == playerID
  return row.UnitType, cost, affordable
end

-- Promotions the unit may take now: its class, not held, any prereq held.
function Civ6Ai_Snapshot._LegalPromotions(unit)
  local exp, out = Civ6Ai_Snapshot._Method(unit, "GetExperience"), {}
  local cls = GameInfo.Units[unit:GetType()].PromotionClass
  if exp == nil or cls == nil or Civ6Ai_Snapshot._UnitPromotionReady(unit) ~= true then return out end
  for promo in GameInfo.UnitPromotions() do
    if promo.PromotionClass == cls and exp:HasPromotion(promo.Index) ~= true then
      local need, ok = false, false
      for pre in GameInfo.UnitPromotionPrereqs() do
        if pre.UnitPromotion == promo.UnitPromotionType then
          need = true
          ok = ok or exp:HasPromotion(GameInfo.UnitPromotions[pre.PrereqUnitPromotion].Index) == true
        end
      end
      if ok or not need then out[#out + 1] = promo.UnitPromotionType end
    end
  end
  return out
end

-- Upgrade, promote, corps/army, fort: the later-era unit orders.
function Civ6Ai_Snapshot._AddProgressionCommands(commands, playerID, unit, unitId)
  local add = function(kind, tag, args)
    args.unit_id = unitId
    table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({command_id = "CMD_" .. kind .. "_" .. unitId .. "_" .. tag, kind = kind, fixed_arguments = args}))
  end
  local up, cost, canAfford = Civ6Ai_Snapshot._UpgradeTarget(playerID, unit)
  if up ~= nil and canAfford == true then add("upgrade_unit", up, {unit_type_id = up, cost = cost}) end
  for _, promo in ipairs(Civ6Ai_Snapshot._LegalPromotions(unit)) do
    add("promote_unit", promo, {promotion_id = promo})
  end
  local row, M, p = GameInfo.Units[unit:GetType()], Civ6Ai_Snapshot._Method, Players[playerID]
  local F = MilitaryFormationTypes
  local function civic(name) local c = GameInfo.Civics[name]; return c ~= nil and M(M(p, "GetCulture"), "HasCivic", c.Index) == true end
  local form = F ~= nil and M(unit, "GetMilitaryFormation") or nil
  local sea = row.Domain == "DOMAIN_SEA"
  -- Indexing F when the formation table is missing throws and drops the fort
  -- offer that follows, even though the promotion was already inserted.
  local can = false
  if F ~= nil then
    can = (form == F.STANDARD_MILITARY_FORMATION and civic(sea and "CIVIC_MERCANTILISM" or "CIVIC_NATIONALISM"))
      or (form == F.CORPS_MILITARY_FORMATION and civic(sea and "CIVIC_NATIONALISM" or "CIVIC_MOBILIZATION"))
  end
  -- SetMilitaryFormation does not stick from a gameplay script, and a host
  -- UI form-corps request does not sync for an AI seat (Gov.MakeTradeRoute).
  -- Offering the order failed every time and removed nothing. Leave both units.
  can = false
  if can and row.FormationClass ~= "FORMATION_CLASS_CIVILIAN" and row.FormationClass ~= "FORMATION_CLASS_SUPPORT" then
    for _, other in ipairs(Civ6Ai_Snapshot._IterateUnits(p:GetUnits())) do
      if other:GetID() ~= unit:GetID() and other:GetType() == unit:GetType()
          and M(other, "GetMilitaryFormation") == F.STANDARD_MILITARY_FORMATION
          and Map.GetPlotDistance(unit:GetX(), unit:GetY(), other:GetX(), other:GetY()) <= 1 then
        local oid = Civ6Ai_Snapshot._UnitWireId(other)
        add("join_formation", oid, {other_unit_id = oid})
        break
      end
    end
  end
  local fort = ({UNIT_MILITARY_ENGINEER = "IMPROVEMENT_FORT", UNIT_ROMAN_LEGION = "IMPROVEMENT_ROMAN_FORT"})[row.UnitType]
  local plot = Map.GetPlot(unit:GetX(), unit:GetY())
  local charges = select(1, Civ6Ai_Snapshot._BuildCharges(unit))
  if fort ~= nil and GameInfo.Improvements[fort] ~= nil and charges > 0
      and M(plot, "GetOwner") == playerID and (M(plot, "GetImprovementType") or -1) < 0 and not M(plot, "IsCity") then
    add("build_fort", fort, {improvement_id = fort})
  end
  -- Builder: every improvement the game allows on its own tile right now.
  local U = UnitOperationTypes
  if fort == nil and charges > 0 and U ~= nil and U.BUILD_IMPROVEMENT ~= nil
      and M(plot, "GetOwner") == playerID and not M(plot, "IsCity") then
    for imp in GameInfo.Improvements() do
      local t = { [U.PARAM_X] = unit:GetX(), [U.PARAM_Y] = unit:GetY(), [U.PARAM_IMPROVEMENT_TYPE] = imp.Hash }
      local ok, can = pcall(UnitManager.CanStartOperation, unit, U.BUILD_IMPROVEMENT, nil, t)
      if ok and can then
        add("worker_improve", imp.ImprovementType, {improvement_id = imp.ImprovementType, target_x = unit:GetX(), target_y = unit:GetY()})
      end
    end
  end
end

-- Builder Improve(x,y,IMP): this builder's nearest owned, unimproved, same-landmass
-- tiles within 8, and the improvements the DB allows there (terrain/feature/resource,
-- tech/civic). A removable feature (woods, rainforest, marsh) does not hide an
-- improvement the terrain allows. Sites are this unit's, nearest first: a shared
-- luxury across the city must not be the only offer for every builder. A MOVE goal
-- with intent improve: gameplay walks there and builds on arrival.
Civ6Ai_Snapshot.IMPROVE_SITES_CAP = 6
function Civ6Ai_Snapshot._ImproveRules()
  if Civ6Ai_Snapshot._impRules ~= nil then return Civ6Ai_Snapshot._impRules end
  local r = {terrain = {}, feature = {}, resource = {}, units = {}}
  local function put(t, a, b) t[a] = t[a] or {}; t[a][b] = true end
  for row in GameInfo.Improvement_ValidTerrains() do put(r.terrain, row.ImprovementType, row.TerrainType) end
  for row in GameInfo.Improvement_ValidFeatures() do put(r.feature, row.ImprovementType, row.FeatureType) end
  for row in GameInfo.Improvement_ValidResources() do put(r.resource, row.ImprovementType, row.ResourceType) end
  for row in GameInfo.Improvement_ValidBuildUnits() do put(r.units, row.ImprovementType, row.UnitType) end
  Civ6Ai_Snapshot._impRules = r
  return r
end

function Civ6Ai_Snapshot._AreaId(plot)
  local ok, a = pcall(function() return plot:GetArea():GetID() end)
  return ok and a or nil
end

function Civ6Ai_Snapshot._LegalImprovementsAt(playerID, unitType, plot)
  local M, p, r = Civ6Ai_Snapshot._Method, Players[playerID], Civ6Ai_Snapshot._ImproveRules()
  local techs, culture = M(p, "GetTechs"), M(p, "GetCulture")
  local function known(t, c)
    if t ~= nil then local row = GameInfo.Technologies[t]; if row == nil or M(techs, "HasTech", row.Index) ~= true then return false end end
    if c ~= nil then local row = GameInfo.Civics[c]; if row == nil or M(culture, "HasCivic", row.Index) ~= true then return false end end
    return true
  end
  local terrain = GameInfo.Terrains[M(plot, "GetTerrainType") or -1]
  local feature = GameInfo.Features[M(plot, "GetFeatureType") or -1]
  local resource = GameInfo.Resources[M(plot, "GetResourceType") or -1]
  if resource ~= nil and not Civ6Ai_Snapshot._ResourceRevealedTo(playerID, resource) then resource = nil end
  -- DB booleans are true or nil. 0 is truthy in Lua, so `not RequiresRiver` would
  -- reject every non-river tile when the column is stored as 0.
  local function flagged(v)
    return v == true or v == 1
  end
  local removable = feature ~= nil and flagged(feature.Removable)
  local ranked = {}
  for imp in GameInfo.Improvements() do
    local t = imp.ImprovementType
    local needsRiver = flagged(imp.RequiresRiver)
    if imp.Buildable ~= false and imp.Buildable ~= 0 and imp.TraitType == nil and (r.units[t] or {})[unitType]
        and known(imp.PrereqTech, imp.PrereqCivic) and (not needsRiver or M(plot, "IsRiver") == true) then
      local onResource = resource ~= nil and (r.resource[t] or {})[resource.ResourceType] == true
      local onFeature = feature ~= nil and (r.feature[t] or {})[feature.FeatureType] == true
      local onTerrain = terrain ~= nil and (r.terrain[t] or {})[terrain.TerrainType] == true
      local ok = false
      if resource ~= nil then
        ok = onResource
      elseif onFeature then
        ok = true
      elseif onTerrain and (feature == nil or removable) then
        ok = true
      end
      if ok then
        local rank = 1
        if onResource or onFeature then rank = 0 end
        ranked[#ranked + 1] = { t = t, rank = rank }
      end
    end
  end
  table.sort(ranked, function(a, b)
    if a.rank ~= b.rank then return a.rank < b.rank end
    return a.t < b.t
  end)
  local out = {}
  for i = 1, #ranked do out[i] = ranked[i].t end
  return out, resource ~= nil
end

function Civ6Ai_Snapshot._AddBuilderImproveCommands(commands, playerID, unit, unitId)
  local M = Civ6Ai_Snapshot._Method
  local charges, ui, core = Civ6Ai_Snapshot._BuildCharges(unit)
  local before = #commands
  if charges <= 0 then
    Civ6Ai_Util.Log("snapshot|improve|unit=" .. tostring(unitId)
      .. "|charges=" .. tostring(charges) .. "|ui=" .. tostring(ui) .. "|core=" .. tostring(core)
      .. "|sites=0|commands=0|dropped_area=0")
    return
  end
  local urow = GameInfo.Units[unit:GetType()]
  local ux, uy = unit:GetX(), unit:GetY()
  local area = Civ6Ai_Snapshot._AreaId(Map.GetPlot(ux, uy))
  local sites, droppedArea = {}, 0
  for dx = -8, 8 do
    for dy = -8, 8 do
      local plot = Map.GetPlot(ux + dx, uy + dy)
      if plot ~= nil and M(plot, "GetOwner") == playerID and not M(plot, "IsCity") and not M(plot, "IsWater")
          and not M(plot, "IsMountain") and (M(plot, "GetImprovementType") or -1) < 0
          and (M(plot, "GetDistrictType") or -1) < 0 then
        local d = Map.GetPlotDistance(ux, uy, plot:GetX(), plot:GetY())
        if d <= 8 then
          -- Snapshot plot records hardcode AREA_0. A nil GetArea on one side is
          -- unknown, not a different landmass; only two known differing ids exclude.
          local plotArea = Civ6Ai_Snapshot._AreaId(plot)
          if area ~= nil and plotArea ~= nil and plotArea ~= area then
            droppedArea = droppedArea + 1
          else
            local imps, res = Civ6Ai_Snapshot._LegalImprovementsAt(playerID, urow.UnitType, plot)
            if #imps > 0 then
              table.insert(sites, {x = plot:GetX(), y = plot:GetY(), d = d, res = res, imps = imps})
            end
          end
        end
      end
    end
  end
  table.sort(sites, function(a, b)
    if a.d ~= b.d then return a.d < b.d end
    if a.res ~= b.res then return a.res end
    if a.x ~= b.x then return a.x < b.x end
    return a.y < b.y
  end)
  for i = 1, math.min(#sites, Civ6Ai_Snapshot.IMPROVE_SITES_CAP) do
    local s = sites[i]
    for j = 1, math.min(#s.imps, 2) do
      local imp = s.imps[j]
      table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
        command_id = "CMD_" .. unitId .. "_" .. imp .. "_improve_" .. s.x .. "_" .. s.y,
        kind = "move_unit",
        fixed_arguments = {unit_id = unitId, target_x = s.x, target_y = s.y, improvement_id = imp,
          intent = "improve", A = 2, G = 1, goal = 1},
      }))
    end
  end
  Civ6Ai_Util.Log("snapshot|improve|unit=" .. tostring(unitId)
    .. "|charges=" .. tostring(charges) .. "|ui=" .. tostring(ui) .. "|core=" .. tostring(core)
    .. "|sites=" .. tostring(#sites) .. "|commands=" .. tostring(#commands - before)
    .. "|dropped_area=" .. tostring(droppedArea))
end

function Civ6Ai_Snapshot._CityStrikeCommand()
  if CityCommandTypes ~= nil and CityCommandTypes.RANGE_ATTACK ~= nil then
    return CityCommandTypes.RANGE_ATTACK
  end
  local row = GameInfo ~= nil and GameInfo.CityCommands ~= nil
    and (GameInfo.CityCommands["CITYCOMMAND_RANGE_ATTACK"] or GameInfo.CityCommands.CITYCOMMAND_RANGE_ATTACK)
    or nil
  if row ~= nil then
    return row.Hash or row.Index
  end
  return nil
end

function Civ6Ai_Snapshot._CityStrikeParams(x, y)
  local params = {}
  local function put(axis, value)
    if CityCommandTypes ~= nil then
      local key = axis == "x" and CityCommandTypes.PARAM_X or CityCommandTypes.PARAM_Y
      if key ~= nil then params[key] = value end
    end
    if UnitOperationTypes ~= nil then
      local key = axis == "x" and UnitOperationTypes.PARAM_X or UnitOperationTypes.PARAM_Y
      if key ~= nil then params[key] = value end
    end
    params[axis == "x" and "PARAM_X" or "PARAM_Y"] = value
    params[string.upper(axis)] = value
  end
  put("x", x)
  put("y", y)
  return params
end

function Civ6Ai_Snapshot._CityStrikeCan(city, x, y)
  local cmd = Civ6Ai_Snapshot._CityStrikeCommand()
  if CityManager == nil or CityManager.CanStartCommand == nil or cmd == nil then
    return nil
  end
  local params = Civ6Ai_Snapshot._CityStrikeParams(x, y)
  local ok, can = pcall(CityManager.CanStartCommand, city, cmd, params)
  if ok and can == true then
    return true
  end
  ok, can = pcall(CityManager.CanStartCommand, city, cmd, true, params, false)
  if ok and can == true then
    return true
  end
  if ok and can == false then
    return false
  end
  ok, can = pcall(CityManager.CanStartCommand, city, cmd)
  if ok and can == true then
    return true
  end
  if ok and can == false then
    return false
  end
  return nil
end

-- City ranged strike: an enemy unit within 2 tiles. Walls are not required to
-- offer the order; the strike is the city's own ranged attack.
function Civ6Ai_Snapshot._CityStrikeAvailableFlag()
  local shared = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if shared ~= nil and shared.CityStrikeAvailable ~= nil then
    local okAvail, avail = pcall(shared.CityStrikeAvailable)
    if okAvail then
      return avail == true
    end
  end
  if Game ~= nil and Game.GetProperty ~= nil then
    local ok, value = pcall(function() return Game:GetProperty("CIV6AI_CITY_STRIKE") end)
    if ok and tonumber(value) == 0 then
      return false
    end
    if ok and tonumber(value) == 1 then
      return true
    end
  end
  return CityManager ~= nil and CityManager.CanStartCommand ~= nil
    and Civ6Ai_Snapshot._CityStrikeCommand() ~= nil
end

function Civ6Ai_Snapshot._AddCityStrikeCommands(commands, playerID)
  local seen = {}
  local function offer(city, tx, ty)
    local dist = Civ6Ai_Snapshot._Dist(city:GetX(), city:GetY(), tx, ty)
    if dist < 1 or dist > Civ6Ai_Snapshot.CITY_STRIKE_RANGE then
      return
    end
    local key = tostring(city:GetID()) .. ":" .. tostring(tx) .. "," .. tostring(ty)
    if seen[key] then
      return
    end
    if not Civ6Ai_Snapshot._CityStrikeAvailableFlag() then
      return
    end
    local can = nil
    if shared ~= nil and shared.CityStrikeCan ~= nil then
      local okCan, result = pcall(shared.CityStrikeCan, city, tx, ty)
      if okCan then
        can = result
      end
    end
    if can == nil then
      can = Civ6Ai_Snapshot._CityStrikeCan(city, tx, ty)
    end
    if can ~= true then
      return
    end
    seen[key] = true
    table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
      command_id = "CMD_citystrike_" .. tostring(city:GetID()) .. "_" .. tostring(tx) .. "_" .. tostring(ty),
      kind = "city_attack",
      fixed_arguments = {city_id = Civ6Ai_Production._WireCityId(city), target_x = tx, target_y = ty},
    }))
  end
  for _, city in Players[playerID]:GetCities():Members() do
    for _, target in ipairs(Civ6Ai_Snapshot._HostileTargets(playerID)) do
      if target.who == "unit" then
        offer(city, target.x, target.y)
      end
    end
    if Map.GetNeighborPlots ~= nil then
      for _, plot in ipairs(Map.GetNeighborPlots(city:GetX(), city:GetY(), Civ6Ai_Snapshot.CITY_STRIKE_RANGE) or {}) do
        if Civ6Ai_Snapshot._EnemyAtPlot(playerID, plot) == "unit" then
          offer(city, plot:GetX(), plot:GetY())
        end
      end
    end
  end
end

-- Missionary and apostle: SpreadReligion on an adjacent city when the unit
-- still has charges and a religious strength. Guru: HealReligious on an
-- adjacent friendly unit when the database publishes a heal amount.
-- CanStartOperation is a local-player check and is not used.
function Civ6Ai_Snapshot._ReligiousHealAmount(row)
  local amount = tonumber(row and row.ReligiousStrength) or 0
  if amount > 0 then
    return amount
  end
  if GameInfo == nil or GameInfo.GlobalParameters == nil then
    return 0
  end
  local found = 0
  pcall(function()
    for param in GameInfo.GlobalParameters() do
      local name = tostring(param.Name or "")
      if string.find(name, "HEAL", 1, true) and string.find(name, "RELIG", 1, true) then
        local n = tonumber(param.Value) or 0
        if n > 0 then
          found = n
          return
        end
      end
    end
  end)
  return found
end

function Civ6Ai_Snapshot._AddReligionCommands(commands, playerID, unit, unitId)
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  if row == nil or row.UnitType == nil then
    return
  end
  local rel = Civ6Ai_Snapshot._Method(unit, "GetReligion")
  local charges = Civ6Ai_Snapshot._Method(rel, "GetSpreadCharges")
  if type(charges) ~= "number" or charges <= 0 then
    return
  end
  local ux, uy = unit:GetX(), unit:GetY()
  local added = 0
  if row.UnitType == "UNIT_MISSIONARY" or row.UnitType == "UNIT_APOSTLE" then
    local religion = Civ6Ai_Snapshot._Method(rel, "GetReligionType")
    local pressure = tonumber(row.ReligiousStrength) or 0
    if type(religion) ~= "number" or religion < 0 or pressure <= 0 then
      return
    end
    for pid = 0, 63 do
      if added >= 6 then break end
      local other = Players[pid]
      local cities = other ~= nil and other.GetCities ~= nil and other:GetCities() or nil
      if cities ~= nil and cities.Members ~= nil then
        for _, city in cities:Members() do
          if added >= 6 then break end
          local dist = Map.GetPlotDistance ~= nil and Map.GetPlotDistance(ux, uy, city:GetX(), city:GetY()) or 99
          if dist <= 1 then
            table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
              command_id = "CMD_spread_" .. unitId .. "_" .. tostring(city:GetOwner()) .. "_" .. tostring(city:GetID()),
              kind = "spread_religion",
              fixed_arguments = {
                unit_id = unitId, target_x = city:GetX(), target_y = city:GetY(), action = "spread",
              },
            }))
            added = added + 1
          end
        end
      end
    end
    return
  end
  if row.UnitType ~= "UNIT_GURU" or Civ6Ai_Snapshot._ReligiousHealAmount(row) <= 0 then
    return
  end
  if Units == nil or Units.GetUnitsInPlot == nil or Map.GetNeighborPlots == nil then
    return
  end
  local plots = { Map.GetPlot(ux, uy) }
  for _, plot in ipairs(Map.GetNeighborPlots(ux, uy, 1) or {}) do
    plots[#plots + 1] = plot
  end
  for _, plot in ipairs(plots) do
    if added >= 4 then break end
    local okL, list = pcall(function() return Units.GetUnitsInPlot(plot) end)
    if okL and list ~= nil then
      for _, other in ipairs(list) do
        if other ~= nil and other.GetOwner ~= nil and other:GetOwner() == playerID and other:GetID() ~= unit:GetID() then
          table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
            command_id = "CMD_healrel_" .. unitId .. "_" .. tostring(plot:GetX()) .. "_" .. tostring(plot:GetY()),
            kind = "spread_religion",
            fixed_arguments = {
              unit_id = unitId, target_x = plot:GetX(), target_y = plot:GetY(), action = "heal",
            },
          }))
          added = added + 1
          break
        end
      end
    end
  end
end

function Civ6Ai_Snapshot._AddExploreCommand(commands, unit, unitId)
  local row = GameInfo.Units[unit:GetType()]
  if row ~= nil and row.FormationClass ~= "FORMATION_CLASS_CIVILIAN" and Civ6Ai_Snapshot._UnitMoves(unit) > 0 then
    table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({command_id = "CMD_explore_" .. unitId, kind = "explore", fixed_arguments = {unit_id = unitId}}))
  end
end

-- Great person activation is legal on the district that class uses, not via
-- UnitManager.CanStartCommand (that check is false for every AI seat).
Civ6Ai_Snapshot.GP_DISTRICT = {
  GREAT_PERSON_CLASS_SCIENTIST = { "DISTRICT_CAMPUS" },
  GREAT_PERSON_CLASS_WRITER = { "DISTRICT_THEATER" },
  GREAT_PERSON_CLASS_ARTIST = { "DISTRICT_THEATER" },
  GREAT_PERSON_CLASS_MUSICIAN = { "DISTRICT_THEATER" },
  GREAT_PERSON_CLASS_MERCHANT = { "DISTRICT_COMMERCIAL_HUB", "DISTRICT_HARBOR" },
  GREAT_PERSON_CLASS_ENGINEER = { "DISTRICT_INDUSTRIAL_ZONE" },
  GREAT_PERSON_CLASS_PROPHET = { "DISTRICT_HOLY_SITE" },
}

function Civ6Ai_Snapshot._AddActivateCommand(commands, playerID, unit, unitId)
  -- Activation and retire are not offered. The action is UI-only, a host UI
  -- request does not sync for an AI seat (Gov.MakeTradeRoute), and every
  -- live order failed. A Great Prophet still gets a move onto the Holy Site,
  -- which founds the religion through the gameplay route on arrival.
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  if row == nil then
    return
  end
  local isProphet = row.UnitType == "UNIT_GREAT_PROPHET"
    or (row.GreatPersonClassType == "GREAT_PERSON_CLASS_PROPHET")
  if not isProphet then
    return
  end
  local site = Civ6Ai_Snapshot._NearestOwnHolySite(playerID, unit:GetX(), unit:GetY())
  if site == nil then
    return
  end
  table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
    command_id = "CMD_foundrel_move_" .. unitId .. "_" .. tostring(site.x) .. "_" .. tostring(site.y),
    kind = "move_unit",
    fixed_arguments = {
      unit_id = unitId,
      target_x = site.x,
      target_y = site.y,
      G = 1,
      A = 3,
      intent = "found_religion",
    },
  }))
end

-- ---------------------------------------------------------------------------
-- Combat awareness (civ6.combat): own unit strengths, attack previews and
-- threats, all from the engine's own CombatManager simulation (the numbers the
-- unit panel shows on hover). Every engine call is pcall'd: a failure here
-- costs the combat block, never the snapshot.
-- ---------------------------------------------------------------------------
Civ6Ai_Snapshot.COMBAT_PREVIEW_CAP = 40
Civ6Ai_Snapshot.COMBAT_THREAT_CAP = 40
Civ6Ai_Snapshot.CITY_STRIKE_RANGE = 2

function Civ6Ai_Snapshot._CombatNum(v)
  local n = tonumber(v)
  if n == nil then return nil end
  return math.floor(n + 0.5)
end

function Civ6Ai_Snapshot._UnitDisplayName(unit)
  local ok, name = pcall(function()
    local row = GameInfo.Units[unit:GetType()]
    return Locale.Lookup(row.Name)
  end)
  if ok and type(name) == "string" and name ~= "" then return name end
  return Civ6Ai_Snapshot._UnitTypeName(unit)
end

function Civ6Ai_Snapshot._CombatUnitStats(unit)
  local info = Civ6Ai_Snapshot._UnitInfo(unit)
  local cur, maxHp = Civ6Ai_Snapshot._UnitHealth(unit)
  local bombard = Civ6Ai_Snapshot._Method(unit, "GetBombardCombat") or 0
  local maxMoves = tonumber(Civ6Ai_Snapshot._Method(unit, "GetMaxMoves")) or 0
  if maxMoves <= 0 then
    local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
    maxMoves = row ~= nil and (tonumber(row.BaseMoves) or tonumber(row.Moves)) or 2
    if maxMoves == nil or maxMoves <= 0 then
      maxMoves = 2
    end
  end
  local ranged = math.max(tonumber(info.ranged) or 0, tonumber(bombard) or 0)
  return {
    strength = Civ6Ai_Snapshot._CombatNum(info.combat) or 0,
    ranged_strength = Civ6Ai_Snapshot._CombatNum(ranged) or 0,
    bombard = (tonumber(bombard) or 0) > (tonumber(info.ranged) or 0),
    range = Civ6Ai_Snapshot._CombatNum(info.range) or 0,
    hp = Civ6Ai_Snapshot._CombatNum(cur) or 0,
    max_hp = Civ6Ai_Snapshot._CombatNum(maxHp) or 100,
    max_moves = Civ6Ai_Snapshot._CombatNum(maxMoves) or 0,
    military = Civ6Ai_Snapshot._IsMilitaryInfo(info),
    is_ranged = ranged > 0 and (tonumber(info.range) or 0) > 0,
  }
end

function Civ6Ai_Snapshot._CombatTypeFor(stats)
  if CombatTypes == nil or not stats.is_ranged then
    return nil
  end
  if stats.bombard and CombatTypes.BOMBARD ~= nil then
    return CombatTypes.BOMBARD
  end
  return CombatTypes.RANGED
end

-- Outcome label, same thresholds as the base game's UnitPanel.lua combat preview.
function Civ6Ai_Snapshot._CombatPrediction(att, def, ranged)
  local P = CombatResultParameters
  local dmgDef = tonumber(def[P.DAMAGE_TO]) or 0
  local defMax = tonumber(def[P.MAX_HIT_POINTS]) or 100
  local dmgAtt = tonumber(att[P.DAMAGE_TO]) or 0
  local attMax = tonumber(att[P.MAX_HIT_POINTS]) or 100
  local defWallMax = tonumber(def[P.MAX_DEFENSE_HIT_POINTS]) or 0
  local defWallDmg = tonumber(def[P.DEFENSE_DAMAGE_TO]) or 0
  local defStrength = (tonumber(def[P.COMBAT_STRENGTH]) or 0) + (tonumber(def[P.STRENGTH_MODIFIER]) or 0)
  if not ranged and (tonumber(att[P.FINAL_DAMAGE_TO]) or 0) >= attMax then
    return "DECISIVE_DEFEAT"
  end
  if dmgDef <= 0 and defWallDmg <= 0 then
    return defStrength > 0 and "INEFFECTIVE" or "DECISIVE_VICTORY"
  end
  if ranged then
    if defWallMax > 0 and defWallDmg >= dmgDef then
      if (tonumber(def[P.FINAL_DEFENSE_DAMAGE_TO]) or 0) >= defWallMax then return "TOTAL_WALL_DAMAGE" end
      return (defWallDmg * 100 / defWallMax) < 25 and "MINOR_WALL_DAMAGE" or "MAJOR_WALL_DAMAGE"
    end
    if defWallMax > 0 then
      if (tonumber(def[P.FINAL_DAMAGE_TO]) or 0) >= defMax then return "TOTAL_CITY_DAMAGE" end
      return (dmgDef * 100 / defMax) < 25 and "MINOR_CITY_DAMAGE" or "MAJOR_CITY_DAMAGE"
    end
    if dmgDef >= defMax or (tonumber(def[P.FINAL_DAMAGE_TO]) or 0) >= defMax then return "DECISIVE_VICTORY" end
    return (dmgDef * 100 / defMax) < 25 and "MINOR_VICTORY" or "MAJOR_VICTORY"
  end
  if dmgDef >= defMax or (defWallMax == 0 and (tonumber(def[P.FINAL_DAMAGE_TO]) or 0) >= defMax) then
    return "DECISIVE_VICTORY"
  end
  local attacking = dmgDef
  if defWallMax > 0 then attacking = math.max(dmgDef, defWallDmg) end
  local diff = attacking - dmgAtt
  if diff > 0 then
    if diff < 3 then return "STALEMATE" end
    if diff < 10 then return "MINOR_VICTORY" end
    return "MAJOR_VICTORY"
  end
  if diff > -3 then return "STALEMATE" end
  if diff > -10 then return "MINOR_DEFEAT" end
  return "MAJOR_DEFEAT"
end

-- Flatten a CombatManager result into plain numbers (+ label). nil when the
-- engine has nothing to say.
function Civ6Ai_Snapshot._CombatResultRow(res, ranged)
  if type(res) ~= "table" or CombatResultParameters == nil then
    return nil
  end
  local P = CombatResultParameters
  local att = res[P.ATTACKER]
  local def = res[P.DEFENDER]
  if type(att) ~= "table" or type(def) ~= "table" then
    return nil
  end
  local function hpLeft(side)
    local maxHp = tonumber(side[P.MAX_HIT_POINTS]) or 0
    local final = tonumber(side[P.FINAL_DAMAGE_TO]) or 0
    local dmg = tonumber(side[P.DAMAGE_TO]) or 0
    return math.max(0, maxHp - (final - dmg)), maxHp
  end
  local defHp, defMax = hpLeft(def)
  local attHp, attMax = hpLeft(att)
  local row = {
    attacker_strength = Civ6Ai_Snapshot._CombatNum((tonumber(att[P.COMBAT_STRENGTH]) or 0) + (tonumber(att[P.STRENGTH_MODIFIER]) or 0)),
    defender_strength = Civ6Ai_Snapshot._CombatNum((tonumber(def[P.COMBAT_STRENGTH]) or 0) + (tonumber(def[P.STRENGTH_MODIFIER]) or 0)),
    damage_to_defender = Civ6Ai_Snapshot._CombatNum(def[P.DAMAGE_TO]) or 0,
    damage_to_attacker = ranged and 0 or (Civ6Ai_Snapshot._CombatNum(att[P.DAMAGE_TO]) or 0),
    defender_hp = Civ6Ai_Snapshot._CombatNum(defHp),
    defender_max_hp = Civ6Ai_Snapshot._CombatNum(defMax),
    attacker_hp = Civ6Ai_Snapshot._CombatNum(attHp),
    attacker_max_hp = Civ6Ai_Snapshot._CombatNum(attMax),
    prediction = Civ6Ai_Snapshot._CombatPrediction(att, def, ranged),
  }
  local wallMax = tonumber(def[P.MAX_DEFENSE_HIT_POINTS]) or 0
  if wallMax > 0 then
    local wallFinal = tonumber(def[P.FINAL_DEFENSE_DAMAGE_TO]) or 0
    local wallDmg = tonumber(def[P.DEFENSE_DAMAGE_TO]) or 0
    row.defender_wall_hp = Civ6Ai_Snapshot._CombatNum(math.max(0, wallMax - (wallFinal - wallDmg)))
    row.defender_wall_max_hp = Civ6Ai_Snapshot._CombatNum(wallMax)
    row.damage_to_walls = Civ6Ai_Snapshot._CombatNum(wallDmg)
  end
  return row
end

function Civ6Ai_Snapshot._SimulateVersus(attackerCid, defenderCid, combatType)
  if CombatManager == nil or CombatManager.SimulateAttackVersus == nil then return nil end
  local ok, res = pcall(CombatManager.SimulateAttackVersus, attackerCid, defenderCid, combatType)
  if ok then return res end
  return nil
end

function Civ6Ai_Snapshot._SimulateInto(attackerCid, combatType, x, y)
  if CombatManager == nil or CombatManager.SimulateAttackInto == nil then return nil end
  local ok, res = pcall(CombatManager.SimulateAttackInto, attackerCid, combatType, x, y)
  if ok then return res end
  return nil
end

-- City centre. GetDistrictID exists on some UI city objects and is missing on
-- the gameplay city (calling it throws). Try the city plot, then that method
-- through _Method, then the city's and the player's district lists.
function Civ6Ai_Snapshot._DistrictById(owner, city, id)
  local n = tonumber(id)
  if n == nil or n < 0 then return nil end
  local lists = {}
  if owner ~= nil and Players ~= nil and Players[owner] ~= nil then
    table.insert(lists, Civ6Ai_Snapshot._Method(Players[owner], "GetDistricts"))
  end
  if city ~= nil then
    table.insert(lists, Civ6Ai_Snapshot._Method(city, "GetDistricts"))
  end
  for _, list in ipairs(lists) do
    local found = Civ6Ai_Snapshot._Method(list, "FindID", n) or Civ6Ai_Snapshot._Method(list, "GetDistrict", n)
    if found ~= nil then return found end
  end
  return nil
end

function Civ6Ai_Snapshot._ScanCityCenter(list, x, y)
  if list == nil or list.Members == nil then return nil end
  local found = nil
  pcall(function()
    for _, d in list:Members() do
      local dx, dy = Civ6Ai_Snapshot._Method(d, "GetX"), Civ6Ai_Snapshot._Method(d, "GetY")
      local typ = Civ6Ai_Snapshot._Method(d, "GetType")
      local row = GameInfo ~= nil and GameInfo.Districts ~= nil and GameInfo.Districts[typ] or nil
      if (x ~= nil and dx == x and dy == y) or (row ~= nil and row.DistrictType == "DISTRICT_CITY_CENTER") then
        found = d
        return
      end
    end
  end)
  return found
end

function Civ6Ai_Snapshot._CityCenterDistrict(city)
  if city == nil then return nil end
  local owner = Civ6Ai_Snapshot._Method(city, "GetOwner")
  local x, y = Civ6Ai_Snapshot._Method(city, "GetX"), Civ6Ai_Snapshot._Method(city, "GetY")
  local plot = nil
  if x ~= nil and y ~= nil and Map ~= nil and Map.GetPlot ~= nil then
    plot = Civ6Ai_Snapshot._Try(Map.GetPlot, x, y)
  end
  local district = Civ6Ai_Snapshot._DistrictById(owner, city, Civ6Ai_Snapshot._Method(plot, "GetDistrictID"))
  if district ~= nil then return district end
  district = Civ6Ai_Snapshot._DistrictById(owner, city, Civ6Ai_Snapshot._Method(city, "GetDistrictID"))
  if district ~= nil then return district end
  district = Civ6Ai_Snapshot._ScanCityCenter(Civ6Ai_Snapshot._Method(city, "GetDistricts"), x, y)
  if district ~= nil then return district end
  local playerDistricts = owner ~= nil and Players ~= nil and Players[owner] ~= nil
    and Civ6Ai_Snapshot._Method(Players[owner], "GetDistricts") or nil
  return Civ6Ai_Snapshot._ScanCityCenter(playerDistricts, x, y)
end

-- Visible hostile units and cities (at war or barbarian) for this player.
function Civ6Ai_Snapshot._VisibleHostiles(playerID)
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  local units, cities = {}, {}
  if vis == nil then return units, cities end
  for _, otherID in ipairs(Civ6Ai_Snapshot._OtherCityPlayerIds(playerID)) do
    if Civ6Ai_Snapshot._IsEnemyOwner(playerID, otherID) then
      local owner = Civ6Ai_Util.PlayerId(otherID)
      local okU, list = pcall(function() return Players[otherID]:GetUnits() end)
      if okU and list ~= nil then
        for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(list)) do
          local okV, visible = pcall(function()
            return unit:GetX() >= 0 and vis:IsVisible(Map.GetPlot(unit:GetX(), unit:GetY()):GetIndex())
          end)
          if okV and visible then
            local stats = Civ6Ai_Snapshot._CombatUnitStats(unit)
            stats.unit = unit
            stats.unit_id = "UNIT_" .. tostring(otherID) .. "_" .. tostring(unit:GetID())
            stats.owner = owner
            stats.name = Civ6Ai_Snapshot._UnitDisplayName(unit)
            stats.unit_type_id = Civ6Ai_Snapshot._UnitTypeName(unit)
            stats.x, stats.y = unit:GetX(), unit:GetY()
            table.insert(units, stats)
          end
        end
      end
      local okC, clist = pcall(function() return Players[otherID]:GetCities() end)
      if okC and clist ~= nil and clist.Members ~= nil then
        for _, city in clist:Members() do
          local okV, visible = pcall(function()
            return vis:IsVisible(Map.GetPlot(city:GetX(), city:GetY()):GetIndex())
          end)
          if okV and visible then
            local district = Civ6Ai_Snapshot._CityCenterDistrict(city)
            local row = {
              city = city, district = district, owner = owner,
              x = city:GetX(), y = city:GetY(),
              name = tostring(Civ6Ai_Snapshot._Try(function() return Locale.Lookup(city:GetName()) end) or "City"),
              strength = Civ6Ai_Snapshot._CombatNum(Civ6Ai_Snapshot._Method(city, "GetStrength")),
            }
            local defense = Civ6Ai_Snapshot._CityDefense(city)
            row.hp, row.max_hp = defense.hp, defense.max_hp
            row.wall_hp, row.wall_max_hp = defense.wall_hp, defense.wall_max_hp
            if district ~= nil and DefenseTypes ~= nil then
              row.strength = row.strength or Civ6Ai_Snapshot._CombatNum(Civ6Ai_Snapshot._Method(district, "GetDefenseStrength"))
            end
            table.insert(cities, row)
          end
        end
      end
    end
  end
  return units, cities
end

function Civ6Ai_Snapshot._Dist(ax, ay, bx, by)
  local ok, d = pcall(Map.GetPlotDistance, ax, ay, bx, by)
  if ok and type(d) == "number" then return d end
  return 999
end

-- Real garrison and wall HP for every city this seat can see, including its own.
-- Fogged cities are left out: last-seen banners are not the engine's current HP.
function Civ6Ai_Snapshot._FillCityDefenses(playerID, out)
  out.city_defenses = Civ6Ai_Util.JsonArrayList()
  local function add(city, ownerID)
    if city == nil or city.GetX == nil or #out.city_defenses >= 80 then
      return
    end
    local defense = Civ6Ai_Snapshot._CityDefense(city)
    local name = tostring(Civ6Ai_Snapshot._Try(function() return Locale.Lookup(city:GetName()) end) or "City")
    table.insert(out.city_defenses, {
      name = name,
      owner_player_id = Civ6Ai_Util.PlayerId(ownerID),
      x = city:GetX(),
      y = city:GetY(),
      hp = defense.hp,
      max_hp = defense.max_hp,
      health_percent = defense.health_percent,
      wall_hp = defense.wall_hp,
      wall_max_hp = defense.wall_max_hp,
      visible = true,
    })
  end
  local player = Players ~= nil and Players[playerID] or nil
  if player ~= nil then
    local ok, cities = pcall(function() return player:GetCities() end)
    if ok and cities ~= nil and cities.Members ~= nil then
      for _, city in cities:Members() do
        add(city, playerID)
      end
    end
  end
  local vis = PlayersVisibility ~= nil and PlayersVisibility[playerID] or nil
  if vis == nil or vis.IsVisible == nil then
    return
  end
  for _, otherID in ipairs(Civ6Ai_Snapshot._OtherCityPlayerIds(playerID)) do
    local ok, cities = pcall(function() return Players[otherID]:GetCities() end)
    if ok and cities ~= nil and cities.Members ~= nil then
      for _, city in cities:Members() do
        local plot = city ~= nil and Map ~= nil and Map.GetPlot ~= nil and Map.GetPlot(city:GetX(), city:GetY()) or nil
        local seen = false
        if plot ~= nil and plot.GetIndex ~= nil then
          local okV, visible = pcall(function() return vis:IsVisible(plot:GetIndex()) end)
          seen = okV and visible == true
        end
        if seen then
          add(city, otherID)
        end
      end
    end
  end
end

function Civ6Ai_Snapshot._BuildCombat(playerID)
  local player = Players[playerID]
  local out = {
    units = Civ6Ai_Util.JsonArrayList(),
    hostiles = Civ6Ai_Util.JsonArrayList(),
    hostile_cities = Civ6Ai_Util.JsonArrayList(),
    previews = Civ6Ai_Util.JsonArrayList(),
    threats = Civ6Ai_Util.JsonArrayList(),
    city_strike_available = Civ6Ai_Snapshot._CityStrikeAvailableFlag(),
  }
  if player == nil then return out end
  local own = {}
  for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
    if unit:GetX() >= 0 then
      local stats = Civ6Ai_Snapshot._CombatUnitStats(unit)
      stats.unit = unit
      stats.unit_id = Civ6Ai_Snapshot._UnitWireId(unit)
      stats.x, stats.y = unit:GetX(), unit:GetY()
      table.insert(own, stats)
      table.insert(out.units, {
        unit_id = stats.unit_id, strength = stats.strength, ranged_strength = stats.ranged_strength,
        range = stats.range, hp = stats.hp, max_hp = stats.max_hp, max_moves = stats.max_moves,
        military = stats.military,
      })
    end
  end
  local hostiles, cities = Civ6Ai_Snapshot._VisibleHostiles(playerID)
  for _, h in ipairs(hostiles) do
    table.insert(out.hostiles, {
      unit_id = h.unit_id, owner_player_id = h.owner, name = h.name, unit_type_id = h.unit_type_id,
      x = h.x, y = h.y, strength = h.strength, ranged_strength = h.ranged_strength, range = h.range,
      hp = h.hp, max_hp = h.max_hp, max_moves = h.max_moves,
    })
  end
  for _, c in ipairs(cities) do
    table.insert(out.hostile_cities, {
      name = c.name, owner_player_id = c.owner, x = c.x, y = c.y, strength = c.strength,
      hp = c.hp, max_hp = c.max_hp, wall_hp = c.wall_hp, wall_max_hp = c.wall_max_hp,
    })
  end
  Civ6Ai_Snapshot._FillCityDefenses(playerID, out)
  if #hostiles == 0 and #cities == 0 then
    return out
  end
  -- Attack previews: every own military unit vs every visible hostile it could
  -- hit this turn (now, or after moving). Held AI-seat units read 0 moves, so
  -- this is distance based, not CanStartOperation based.
  local function addPreview(u, target, kind)
    if #out.previews >= Civ6Ai_Snapshot.COMBAT_PREVIEW_CAP then return end
    local dist = Civ6Ai_Snapshot._Dist(u.x, u.y, target.x, target.y)
    local ranged = u.is_ranged
    local reachNow = ranged and u.range or 1
    local reachMove = ranged and (u.range + math.max(0, u.max_moves - 1)) or math.max(1, u.max_moves)
    if dist < 1 or dist > reachMove then return end
    local combatType = Civ6Ai_Snapshot._CombatTypeFor(u)
    local cid = u.unit:GetComponentID()
    local res
    local tcid = kind == "unit" and target.unit:GetComponentID()
      or (target.district ~= nil and target.district:GetComponentID()) or nil
    if tcid ~= nil then
      res = Civ6Ai_Snapshot._SimulateVersus(cid, tcid, combatType)
        or (ranged and Civ6Ai_Snapshot._SimulateVersus(cid, tcid, CombatTypes.RANGED)) or nil
    end
    if res == nil then
      res = Civ6Ai_Snapshot._SimulateInto(cid, combatType, target.x, target.y)
    end
    local row = Civ6Ai_Snapshot._CombatResultRow(res, ranged) or {}
    row.unit_id = u.unit_id
    row.target_x, row.target_y = target.x, target.y
    row.target_kind = kind
    row.target_name = target.name
    row.target_owner = target.owner
    -- A unit standing on an enemy city is that city's defender. Name the city.
    if kind == "unit" then
      for _, c in ipairs(cities) do
        if c.x == target.x and c.y == target.y and c.name ~= nil then
          row.target_name = c.name
          row.target_kind = "city"
          row.target_owner = c.owner or row.target_owner
          break
        end
      end
    end
    row.ranged = ranged
    row.distance = dist
    row.needs_move = dist > reachNow
    if row.attacker_strength == nil then row.attacker_strength = ranged and u.ranged_strength or u.strength end
    if row.defender_strength == nil then row.defender_strength = target.strength end
    if row.attacker_hp == nil then row.attacker_hp, row.attacker_max_hp = u.hp, u.max_hp end
    if row.defender_hp == nil then row.defender_hp, row.defender_max_hp = target.hp, target.max_hp end
    row.simulated = res ~= nil and row.prediction ~= nil
    table.insert(out.previews, row)
  end
  for _, u in ipairs(own) do
    if u.military and (u.strength > 0 or u.ranged_strength > 0) then
      for _, h in ipairs(hostiles) do
        local ok, err = pcall(addPreview, u, h, "unit")
        if not ok then Civ6Ai_Util.Log("snapshot|combat_preview_failed|" .. tostring(err)) end
      end
      for _, c in ipairs(cities) do
        local ok, err = pcall(addPreview, u, c, "city")
        if not ok then Civ6Ai_Util.Log("snapshot|combat_preview_failed|" .. tostring(err)) end
      end
    end
  end
  -- City ranged strike forecast (the city's own centre vs a hostile unit in
  -- range). These rows carry city_id so the prompt can put the numbers on the
  -- city's rangeStrike option.
  local function addCityStrike(city, h)
    if #out.previews >= Civ6Ai_Snapshot.COMBAT_PREVIEW_CAP then return end
    if city == nil or h == nil or h.unit == nil then return end
    local dist = Civ6Ai_Snapshot._Dist(city:GetX(), city:GetY(), h.x, h.y)
    if dist < 1 or dist > Civ6Ai_Snapshot.CITY_STRIKE_RANGE then return end
    local district = Civ6Ai_Snapshot._CityCenterDistrict(city)
    local dcid = Civ6Ai_Snapshot._Method(district, "GetComponentID")
    local ucid = Civ6Ai_Snapshot._Method(h.unit, "GetComponentID")
    if dcid == nil or ucid == nil then return end
    local rangedType = CombatTypes ~= nil and CombatTypes.RANGED or nil
    local res = Civ6Ai_Snapshot._SimulateVersus(dcid, ucid, rangedType)
    local row = Civ6Ai_Snapshot._CombatResultRow(res, true)
    if row == nil then return end
    row.city_id = "CITY_" .. tostring(city:GetID())
    row.target_x, row.target_y = h.x, h.y
    local strikeTarget = "unit"
    row.target_kind = strikeTarget
    row.target_name = h.name
    row.target_owner = h.owner
    row.ranged = true
    row.distance = dist
    row.needs_move = false
    row.source = "city"
    row.simulated = row.prediction ~= nil
    table.insert(out.previews, row)
  end
  local okCities, clist = pcall(function() return player:GetCities() end)
  if okCities and clist ~= nil and clist.Members ~= nil then
    for _, city in clist:Members() do
      for _, h in ipairs(hostiles) do
        local ok, err = pcall(addCityStrike, city, h)
        if not ok then Civ6Ai_Util.Log("snapshot|city_strike_preview_failed|" .. tostring(err)) end
      end
    end
  end
  -- Threats: own units a visible hostile can hit on its next turn, and units
  -- inside a walled hostile city's strike range. Damage from the engine
  -- simulating the enemy attacking us.
  local function addThreats(u)
    for _, h in ipairs(hostiles) do
      if #out.threats >= Civ6Ai_Snapshot.COMBAT_THREAT_CAP then break end
      if h.strength > 0 or h.ranged_strength > 0 then
        local dist = Civ6Ai_Snapshot._Dist(u.x, u.y, h.x, h.y)
        local reach = h.is_ranged and (h.range + math.max(0, h.max_moves - 1)) or math.max(1, h.max_moves)
        if dist >= 1 and dist <= reach then
          local row = {}
          if u.military then
            local res = Civ6Ai_Snapshot._SimulateVersus(h.unit:GetComponentID(), u.unit:GetComponentID(),
              Civ6Ai_Snapshot._CombatTypeFor(h))
            row = Civ6Ai_Snapshot._CombatResultRow(res, h.is_ranged) or {}
          end
          row.unit_id = u.unit_id
          row.source_type = "unit"
          row.source_name = h.name
          row.source_owner = h.owner
          row.source_x, row.source_y = h.x, h.y
          row.distance = dist
          row.reach = reach
          row.ranged = h.is_ranged
          row.civilian = not u.military
          row.enemy_strength = h.is_ranged and h.ranged_strength or h.strength
          row.own_strength = u.strength
          row.own_hp, row.own_max_hp = u.hp, u.max_hp
          table.insert(out.threats, row)
        end
      end
    end
    for _, c in ipairs(cities) do
      if #out.threats >= Civ6Ai_Snapshot.COMBAT_THREAT_CAP then break end
      local dist = Civ6Ai_Snapshot._Dist(u.x, u.y, c.x, c.y)
      if dist >= 1 and dist <= Civ6Ai_Snapshot.CITY_STRIKE_RANGE then
        local row = {}
        local canStrike = (c.wall_max_hp or 0) > 0
        if canStrike and u.military and c.district ~= nil then
          local res = Civ6Ai_Snapshot._SimulateVersus(c.district:GetComponentID(), u.unit:GetComponentID(), nil)
          row = Civ6Ai_Snapshot._CombatResultRow(res, true) or {}
        end
        row.unit_id = u.unit_id
        row.source_type = "city"
        row.source_name = c.name
        row.source_owner = c.owner
        row.source_x, row.source_y = c.x, c.y
        row.distance = dist
        row.reach = Civ6Ai_Snapshot.CITY_STRIKE_RANGE
        row.ranged = true
        row.can_strike = canStrike
        row.civilian = not u.military
        row.enemy_strength = c.strength
        row.own_strength = u.strength
        row.own_hp, row.own_max_hp = u.hp, u.max_hp
        table.insert(out.threats, row)
      end
    end
  end
  for _, u in ipairs(own) do
    local ok, err = pcall(addThreats, u)
    if not ok then Civ6Ai_Util.Log("snapshot|combat_threat_failed|" .. tostring(err)) end
  end
  return out
end

Civ6Ai_Snapshot.LEGAL_COMMAND_CAP = 500

-- One envoy per met city-state when this seat still has tokens to give.
-- Gameplay applies it (Gov.SendEnvoy); the UI influence-token request is not used.
function Civ6Ai_Snapshot._AddEnvoyCommands(commands, playerID)
  -- The influence-token setters are not available in a gameplay script, and a
  -- host UI write does not sync for an AI seat (Gov.MakeTradeRoute). Every
  -- live envoy order failed. The game's own AI sends them.
end

function Civ6Ai_Snapshot._BuildLegalCommands(playerID, playerLabel)
  -- Priority order under the sidecar schema cap (512): unit orders, then research/civics.
  -- City item orders are not offered; AI seats use set_build_priority.
  Civ6Ai_Snapshot._hostileCache = nil
  Civ6Ai_Snapshot._hostileCachePlayer = nil
  local commands = {}
  local prodCommands = {}
  Civ6Ai_Snapshot._AddProductionCommands(prodCommands, playerID)
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
        -- CanStartOperation(FORTIFY) is a local-player UI check and is false for
        -- an AI seat, so the token never reached the option list. A military
        -- unit with movement left can fortify; gameplay applies FinishMoves.
        local info = Civ6Ai_Snapshot._UnitInfo(unit)
        if Civ6Ai_Snapshot._IsMilitaryInfo(info) and Civ6Ai_Snapshot._UnitMoves(unit) > 0 then
          table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
            command_id = "CMD_fortify_" .. unitId,
            kind = "unit_posture_fortify",
            fixed_arguments = {unit_id = unitId},
          }))
        end
        if GameInfo ~= nil and GameInfo.UnitOperations ~= nil then
          local foundOp = GameInfo.UnitOperations["UNITOPERATION_FOUND_CITY"]
          local canFound = Civ6Ai_Snapshot._CanFoundCity(unit, foundOp)
          if canFound then
            table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
              command_id = "CMD_found_" .. unitId,
              kind = "found_city",
              fixed_arguments = {unit_id = unitId},
            }))
          end
        end
        Civ6Ai_Snapshot._AddAttackCommands(commands, playerID, unit, unitId)
        Civ6Ai_Snapshot._AddPillageCommand(commands, unit, unitId)
        Civ6Ai_Snapshot._AddAdjacentMoveCommands(commands, unit, unitId)
        pcall(Civ6Ai_Snapshot._AddTradeRouteCommands, commands, playerID, unit, unitId)
        pcall(Civ6Ai_Snapshot._AddExploreCommand, commands, unit, unitId)
        local okB, whyB = pcall(Civ6Ai_Snapshot._AddBuilderImproveCommands, commands, playerID, unit, unitId)
        if not okB then Civ6Ai_Util.Log("snapshot|improve_error|" .. tostring(whyB)) end
        pcall(Civ6Ai_Snapshot._AddActivateCommand, commands, playerID, unit, unitId)
        pcall(Civ6Ai_Snapshot._AddReligionCommands, commands, playerID, unit, unitId)
        local okP, whyP = pcall(Civ6Ai_Snapshot._AddProgressionCommands, commands, playerID, unit, unitId)
        if not okP then Civ6Ai_Util.Log("snapshot|progression_error|" .. tostring(whyP)) end
      end
    end
  end
  if player ~= nil then
    -- Unit move and improve offers fill the legal-command cap and used to
    -- drop every city strike. Strikes are few and go in front.
    local strikes = {}
    local okS, whyS = pcall(Civ6Ai_Snapshot._AddCityStrikeCommands, strikes, playerID)
    if not okS then
      Civ6Ai_Util.Log("snapshot|city_strike_error|" .. tostring(whyS))
    else
      for i = #strikes, 1, -1 do
        table.insert(commands, 1, strikes[i])
      end
    end
  end
  local techs = player and player:GetTechs()
  local rt = techs ~= nil and techs:GetResearchingTech() or -1
  if techs ~= nil and (rt < 0 or techs:GetResearchProgress(rt) + techs:GetScienceYield() >= techs:GetResearchCost(rt)) then
    for row in GameInfo.Technologies() do
      -- Require HasTech == false (not mere ~= true): nil from HasTech must not pass.
      if techs:CanResearch(row.Index) and techs:HasTech(row.Index) == false then
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_research_" .. row.TechnologyType,
          kind = "set_research_tech",
          fixed_arguments = {tech_id = row.TechnologyType},
        }))
      end
    end
  end
  local culture = player and player.GetCulture ~= nil and player:GetCulture() or nil
  local rc = culture ~= nil and culture:GetProgressingCivic() or -1
  if culture ~= nil and GameInfo.Civics ~= nil and culture.CanProgress ~= nil
      and (rc < 0 or culture:GetCulturalProgress(rc) + culture:GetCultureYield() >= culture:GetCultureCost(rc)) then
    for row in GameInfo.Civics() do
      local ok, can = pcall(function()
        -- Require HasCivic == false so nil does not look researchable.
        return culture:CanProgress(row.Index) == true and culture:HasCivic(row.Index) == false
      end)
      if ok and can then
        table.insert(commands, Civ6Ai_Snapshot._EnrichLegalCommand({
          command_id = "CMD_civic_" .. row.CivicType,
          kind = "set_research_civic",
          fixed_arguments = {civic_id = row.CivicType},
        }))
      end
    end
  end
  for _, command in ipairs(prodCommands) do
    table.insert(commands, command)
  end
  Civ6Ai_Snapshot._AddPurchaseCommands(commands, playerID)
  pcall(Civ6Ai_Snapshot._AddEnvoyCommands, commands, playerID)
  local capped = {}
  for index, command in ipairs(commands) do
    if index > Civ6Ai_Snapshot.LEGAL_COMMAND_CAP then
      Civ6Ai_Util.Log("snapshot|legal_cap|dropped=" .. tostring(#commands - Civ6Ai_Snapshot.LEGAL_COMMAND_CAP))
      break
    end
    table.insert(capped, command)
  end
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
    local offeredUnit, offeredCity = 0, 0
    for _, command in ipairs(capped) do
      if command.kind == "attack_target" or command.kind == "range_attack" or command.kind == "melee_attack" then
        offeredUnit = offeredUnit + 1
      elseif command.kind == "city_attack" then
        offeredCity = offeredCity + 1
      end
    end
    local turn = -1
    if Game ~= nil and Game.GetCurrentGameTurn ~= nil then
      local okTurn, got = pcall(Game.GetCurrentGameTurn)
      if okTurn and got ~= nil then
        turn = got
      end
    end
    Civ6Ai_Util.Log("attacks|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn)
      .. "|offered=" .. tostring(offeredUnit + offeredCity)
      .. "|unit=" .. tostring(offeredUnit) .. "|city=" .. tostring(offeredCity))
  end
  return capped
end

-- ---------------------------------------------------------------------------
-- civ6.governance: government, policy slots, civics, religion, governors,
-- great people and great works, read from the engine (interface context, so
-- the government/governor screens' own calls are available). Options listed
-- here are what the commands in Civ6Ai_Apply can do; the sidecar turns them
-- into legal commands and the prompt's GOVERNMENT & CULTURE section.
-- ---------------------------------------------------------------------------
Civ6Ai_Snapshot.GOV_TEXT_MAX = 200
-- Effect text lengths: long enough for a whole card/belief description, cut
-- at a word boundary beyond that (prompt size).
Civ6Ai_Snapshot.EFFECT_MAX = 240

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

-- Index first, then hash: the engine takes either depending on the call.
local function gtrue(obj, name, row)
  if gcall(obj, name, row.Index) == true then
    return true
  end
  return row.Hash ~= nil and gcall(obj, name, row.Hash) == true
end

function Civ6Ai_Snapshot._GovText(key, maxLen)
  if key == nil or key == "" then
    return nil
  end
  local ok, text = pcall(function() return Locale.Lookup(key) end)
  if not ok or type(text) ~= "string" or text == "" then
    return nil
  end
  -- Some engine fields (great people timeline effect text) are already
  -- localized; only an unresolved LOC_ key counts as missing.
  if text == key and string.find(key, "^LOC_") ~= nil then
    return nil
  end
  -- Icons become a word only when the text does not already name the yield
  -- right after the icon ("[ICON_Faith] Faith" -> "Faith").
  local map = { Gold = "gold", Faith = "faith", Culture = "culture", Science = "science", Production = "production",
    Food = "food", Housing = "housing", Amenities = "amenities", GreatPerson = "great person points",
    Envoy = "envoy", Influence = "influence", Governor = "governor title" }
  text = string.gsub(text, "%[ICON_(%w+)%]( ?)(%a*)", function(icon, sp, word)
    local w = map[icon]
    if w == nil or (word ~= "" and string.sub(string.lower(word), 1, 4) == string.sub(w, 1, 4)) then
      return word
    end
    return w .. (word ~= "" and " " or sp) .. word
  end)
  text = string.gsub(text, "%[NEWLINE%]", " ")
  text = string.gsub(text, "%[[^%]]*%]", "")
  text = Civ6Ai_Util.CollapseAsciiWS(text)
  text = string.gsub(text, "%( ", "(")
  text = string.gsub(text, " ([%),%.;:])", "%1")
  text = Civ6Ai_Util.TrimAsciiWSLeft(text)
  maxLen = maxLen or Civ6Ai_Snapshot.GOV_TEXT_MAX
  text = Civ6Ai_Util.TrimAsciiWSRight(text)
  if string.len(text) > maxLen then
    local cut = string.sub(text, 1, maxLen - 3)
    local space = string.find(cut, " [^ ]*$")
    if space ~= nil and space > maxLen * 0.6 then
      cut = string.sub(cut, 1, space - 1)
    end
    text = cut .. "..."
  end
  return text
end

local function slotShort(slotType)
  return (string.gsub(tostring(slotType or ""), "^SLOT_", ""))
end

-- Legacy (accumulated) bonus text; skipped when it only repeats "no bonus".
function Civ6Ai_Snapshot._GovLegacy(row)
  local text = Civ6Ai_Snapshot._GovText(row.AccumulatedBonusDesc, Civ6Ai_Snapshot.EFFECT_MAX)
    or Civ6Ai_Snapshot._GovText(row.AccumulatedBonusShortDesc, Civ6Ai_Snapshot.EFFECT_MAX)
  local inherent = Civ6Ai_Snapshot._GovText(row.InherentBonusDesc, Civ6Ai_Snapshot.EFFECT_MAX)
  if text == nil or text == inherent then
    return nil
  end
  return text
end

function Civ6Ai_Snapshot._GovGovernment(culture)
  local out = { available = Civ6Ai_Util.JsonArrayList() }
  local current = gcall(culture, "GetCurrentGovernment")
  local row = current ~= nil and current >= 0 and GameInfo.Governments[current] or nil
  out.current = row ~= nil and row.GovernmentType or nil
  local canAtAll = gcall(culture, "CanChangeGovernmentAtAll")
  local made = gcall(culture, "GovernmentChangeMade")
  local fresh = row == nil or gcall(culture, "CivicCompletedThisTurn") == true
  local inAnarchy = gcall(culture, "IsInAnarchy") == true
  local endTurn = gcall(culture, "GetAnarchyEndTurn")
  local nowTurn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or 0
  local anarchyLeft = 0
  if inAnarchy or (current ~= nil and current < 0) then
    if type(endTurn) == "number" and endTurn > nowTurn then
      anarchyLeft = endTurn - nowTurn
    else
      anarchyLeft = 1
    end
    out.in_anarchy = true
    out.anarchy_turns_left = anarchyLeft
  end
  out.change_allowed = canAtAll ~= false and made ~= true and fresh and not out.in_anarchy
  out.change_rule = "a government can be changed only on a turn when a civic completed"
  local slotsByGov = {}
  if GameInfo.Government_SlotCounts ~= nil then
    for s in GameInfo.Government_SlotCounts() do
      local list = slotsByGov[s.GovernmentType] or {}
      list[#list + 1] = slotShort(s.GovernmentSlotType) .. "x" .. tostring(s.NumSlots)
      slotsByGov[s.GovernmentType] = list
    end
  end
  if row ~= nil then
    out.current_slots = table.concat(slotsByGov[row.GovernmentType] or {}, " ")
    out.current_bonus = Civ6Ai_Snapshot._GovText(row.InherentBonusDesc, Civ6Ai_Snapshot.EFFECT_MAX)
    out.current_legacy = Civ6Ai_Snapshot._GovLegacy(row)
  end
  for g in GameInfo.Governments() do
    if (row == nil or g.Index ~= row.Index) and gtrue(culture, "IsGovernmentUnlocked", g) then
      out.available[#out.available + 1] = {
        id = g.GovernmentType,
        slots = table.concat(slotsByGov[g.GovernmentType] or {}, " "),
        bonus = Civ6Ai_Snapshot._GovText(g.InherentBonusDesc, Civ6Ai_Snapshot.EFFECT_MAX),
        legacy = Civ6Ai_Snapshot._GovLegacy(g),
        anarchy_turns = gcall(culture, "GetAnarchyTurns", g.Index) or 0,
      }
    end
  end
  return out
end

function Civ6Ai_Snapshot._GovPolicies(culture)
  local out = { slots = Civ6Ai_Util.JsonArrayList(), available = Civ6Ai_Util.JsonArrayList() }
  local n = gcall(culture, "GetNumPolicySlots") or 0
  local active = {}
  local empty = 0
  for i = 0, n - 1 do
    local st = gcall(culture, "GetSlotType", i)
    local srow = st ~= nil and GameInfo.GovernmentSlots[st] or nil
    local pid = gcall(culture, "GetSlotPolicy", i)
    local prow = pid ~= nil and pid >= 0 and GameInfo.Policies[pid] or nil
    if prow ~= nil then
      active[prow.PolicyType] = true
    else
      empty = empty + 1
    end
    out.slots[#out.slots + 1] = {
      index = i,
      slot_type = srow ~= nil and srow.GovernmentSlotType or "SLOT_UNKNOWN",
      policy = prow ~= nil and prow.PolicyType or nil,
    }
  end
  out.empty_slots = empty
  local civicDone = gcall(culture, "CivicCompletedThisTurn") == true
  local open = gcall(culture, "GetNumPolicySlotsOpen") or 0
  out.change_allowed = (civicDone or open > 0) and gcall(culture, "PolicyChangeMade") ~= true
  out.change_rule = "policy cards can be changed on a turn when a civic completed (or while a slot is newly open)"
  for p in GameInfo.Policies() do
    if gtrue(culture, "IsPolicyUnlocked", p) and not gtrue(culture, "IsPolicyObsolete", p) then
      out.available[#out.available + 1] = {
        id = p.PolicyType,
        slot_type = p.GovernmentSlotType,
        active = active[p.PolicyType] == true,
        effect = Civ6Ai_Snapshot._GovText(p.Description, Civ6Ai_Snapshot.EFFECT_MAX),
      }
    end
  end
  return out
end

-- What each tech/civic unlocks (same tables the tech/civic tree tooltips
-- read: TechAndCivicSupport GetUnlockablesForTech/Civic), built once per load.
Civ6Ai_Snapshot.UNLOCK_TEXT_MAX = 220
function Civ6Ai_Snapshot._UnlockIndex()
  if Civ6Ai_Snapshot._unlockIndex ~= nil then
    return Civ6Ai_Snapshot._unlockIndex
  end
  local index = {}
  local function add(prereq, group, row)
    if prereq == nil or prereq == "" then
      return
    end
    local entry = index[prereq] or { order = {}, groups = {} }
    index[prereq] = entry
    if entry.groups[group] == nil then
      entry.groups[group] = {}
      entry.order[#entry.order + 1] = group
    end
    local name = row.Name ~= nil and Civ6Ai_Snapshot._GovText(row.Name, 40) or nil
    table.insert(entry.groups[group], name or tostring(row.Type or "?"))
  end
  local function scan(tableName, groupFn)
    local t = GameInfo[tableName]
    if t == nil then
      return
    end
    pcall(function()
      for row in t() do
        local group = groupFn(row)
        if group ~= nil then
          add(row.PrereqTech, group, row)
          add(row.PrereqCivic, group, row)
        end
      end
    end)
  end
  local function traitFree(row)
    return row.TraitType == nil or row.TraitType == ""
  end
  scan("Units", function(r) return traitFree(r) and "units" or nil end)
  scan("Buildings", function(r)
    if not traitFree(r) or r.InternalOnly == true then return nil end
    return r.IsWonder == true and "wonders" or "buildings"
  end)
  scan("Districts", function(r) return traitFree(r) and r.InternalOnly ~= true and "districts" or nil end)
  scan("Improvements", function(r) return traitFree(r) and "improvements" or nil end)
  scan("Policies", function(r) return "policies" end)
  scan("Governments", function(r) return "governments" end)
  scan("Projects", function(r) return "projects" end)
  Civ6Ai_Snapshot._unlockIndex = index
  return index
end

function Civ6Ai_Snapshot._UnlockText(typeId)
  local entry = Civ6Ai_Snapshot._UnlockIndex()[typeId]
  if entry == nil then
    return nil
  end
  local parts = {}
  for _, group in ipairs(entry.order) do
    parts[#parts + 1] = group .. " " .. table.concat(entry.groups[group], ", ")
  end
  local text = table.concat(parts, "; ")
  local maxLen = Civ6Ai_Snapshot.UNLOCK_TEXT_MAX
  if string.len(text) > maxLen then
    text = string.sub(text, 1, maxLen - 3) .. "..."
  end
  return text
end

-- Eureka/inspiration condition for a tech or civic (Boosts.TriggerDescription).
function Civ6Ai_Snapshot._BoostText(typeId)
  if Civ6Ai_Snapshot._boostIndex == nil then
    local idx = {}
    if GameInfo.Boosts ~= nil then
      pcall(function()
        for b in GameInfo.Boosts() do
          local key = b.TechnologyType or b.CivicType
          if key ~= nil and idx[key] == nil then
            idx[key] = Civ6Ai_Snapshot._GovText(b.TriggerDescription, 140)
          end
        end
      end)
    end
    Civ6Ai_Snapshot._boostIndex = idx
  end
  return Civ6Ai_Snapshot._boostIndex[typeId]
end

function Civ6Ai_Snapshot._GovCivics(culture, player)
  local out = { options = Civ6Ai_Util.JsonArrayList() }
  local cur = gcall(culture, "GetProgressingCivic")
  local crow = cur ~= nil and cur >= 0 and GameInfo.Civics[cur] or nil
  out.current = crow ~= nil and crow.CivicType or nil
  if crow ~= nil then
    out.turns_left = gcall(culture, "GetTurnsLeft") or gcall(culture, "GetTurnsToProgressCivic", crow.Index)
    out.current_unlocks = Civ6Ai_Snapshot._UnlockText(crow.CivicType)
    out.current_boosted = gcall(culture, "HasBoostBeenTriggered", crow.Index) == true
    out.current_boost = Civ6Ai_Snapshot._BoostText(crow.CivicType)
  end
  out.culture_per_turn = Civ6Ai_Snapshot._YieldOrCities(player, gcall(culture, "GetCultureYield"), YieldTypes ~= nil and YieldTypes.CULTURE or nil)
  for c in GameInfo.Civics() do
    if gcall(culture, "CanProgress", c.Index) == true and gcall(culture, "HasCivic", c.Index) == false then
      local unlocks = {}
      if GameInfo.Governments ~= nil then
        for g in GameInfo.Governments() do
          if g.PrereqCivic == c.CivicType then
            unlocks[#unlocks + 1] = g.GovernmentType
          end
        end
      end
      out.options[#out.options + 1] = {
        id = c.CivicType,
        turns = gcall(culture, "GetTurnsToProgressCivic", c.Index),
        cost = gcall(culture, "GetCultureCost", c.Index),
        boosted = gcall(culture, "HasBoostBeenTriggered", c.Index) == true,
        unlocks_government = #unlocks > 0 and table.concat(unlocks, "/") or nil,
        unlocks = Civ6Ai_Snapshot._UnlockText(c.CivicType),
        boost = Civ6Ai_Snapshot._BoostText(c.CivicType),
      }
    end
  end
  return out
end

function Civ6Ai_Snapshot._GovTechs(player)
  local techs = player.GetTechs ~= nil and player:GetTechs() or nil
  local out = { options = Civ6Ai_Util.JsonArrayList() }
  if techs == nil then
    return out
  end
  local cur = gcall(techs, "GetResearchingTech")
  local trow = cur ~= nil and cur >= 0 and GameInfo.Technologies[cur] or nil
  out.current = trow ~= nil and trow.TechnologyType or nil
  if trow ~= nil then
    out.turns_left = gcall(techs, "GetTurnsLeft") or gcall(techs, "GetTurnsToResearch", trow.Index)
    out.current_unlocks = Civ6Ai_Snapshot._UnlockText(trow.TechnologyType)
    out.current_boosted = gcall(techs, "HasBoostBeenTriggered", trow.Index) == true
    out.current_boost = Civ6Ai_Snapshot._BoostText(trow.TechnologyType)
  end
  out.science_per_turn = Civ6Ai_Snapshot._YieldOrCities(player, gcall(techs, "GetScienceYield"), YieldTypes ~= nil and YieldTypes.SCIENCE or nil)
  for t in GameInfo.Technologies() do
    if gcall(techs, "CanResearch", t.Index) == true and gcall(techs, "HasTech", t.Index) == false then
      out.options[#out.options + 1] = {
        id = t.TechnologyType,
        turns = gcall(techs, "GetTurnsToResearch", t.Index),
        boosted = gcall(techs, "HasBoostBeenTriggered", t.Index) == true,
        unlocks = Civ6Ai_Snapshot._UnlockText(t.TechnologyType),
        boost = Civ6Ai_Snapshot._BoostText(t.TechnologyType),
      }
    end
  end
  return out
end

local function isHolySite(plot, owner)
  if plot == nil or gcall(plot, "GetOwner") ~= owner then
    return false
  end
  local d = gcall(plot, "GetDistrictType")
  local row = d ~= nil and d >= 0 and GameInfo.Districts[d] or nil
  if row == nil then
    return false
  end
  if row.DistrictType == "DISTRICT_HOLY_SITE" then
    return true
  end
  if GameInfo.DistrictReplaces ~= nil then
    for r in GameInfo.DistrictReplaces() do
      if r.CivUniqueDistrictType == row.DistrictType and r.ReplacesDistrictType == "DISTRICT_HOLY_SITE" then
        return true
      end
    end
  end
  return false
end

function Civ6Ai_Snapshot._GovReligion(playerID, player)
  local rel = player:GetReligion()
  local game = Game.GetReligion ~= nil and Game.GetReligion() or nil
  local out = {
    faith = math.floor(gcall(rel, "GetFaithBalance") or 0),
    faith_per_turn = gcall(rel, "GetFaithYield") or 0,
    pantheon_beliefs = Civ6Ai_Util.JsonArrayList(),
    religion_options = Civ6Ai_Util.JsonArrayList(),
    founder_beliefs = Civ6Ai_Util.JsonArrayList(),
    follower_beliefs = Civ6Ai_Util.JsonArrayList(),
    worship_beliefs = Civ6Ai_Util.JsonArrayList(),
    enhancer_beliefs = Civ6Ai_Util.JsonArrayList(),
    prophets = Civ6Ai_Util.JsonArrayList(),
    religious_units = {},
  }
  local pan = gcall(rel, "GetPantheon")
  local prow = pan ~= nil and pan >= 0 and GameInfo.Beliefs[pan] or nil
  out.pantheon = prow ~= nil and prow.BeliefType or nil
  out.pantheon_cost = gcall(game, "GetMinimumFaithNextPantheon")
  if out.pantheon_cost == nil then
    local gp = GameInfo.GlobalParameters ~= nil and GameInfo.GlobalParameters["RELIGION_PANTHEON_MIN_FAITH"] or nil
    out.pantheon_cost = tonumber(gp and gp.Value) or 25
  end
  out.can_found_pantheon = prow == nil and gcall(rel, "CanCreatePantheon") ~= false and out.faith >= out.pantheon_cost
  local made = gcall(rel, "GetReligionTypeCreated")
  local rrow = made ~= nil and made >= 0 and GameInfo.Religions[made] or nil
  out.religion = rrow ~= nil and rrow.ReligionType or nil
  -- Pantheon choices are listed from a few turns before the faith is there.
  local soon = out.faith_per_turn > 0 and (out.pantheon_cost - out.faith) / out.faith_per_turn <= 6
  if prow == nil and (out.can_found_pantheon or soon) then
    for b in GameInfo.Beliefs() do
      if b.BeliefClassType == "BELIEF_CLASS_PANTHEON" and not gtrue(game, "IsInSomePantheon", b) then
        out.pantheon_beliefs[#out.pantheon_beliefs + 1] = { id = b.BeliefType, effect = Civ6Ai_Snapshot._GovText(b.Description, Civ6Ai_Snapshot.EFFECT_MAX) }
      end
    end
  end
  for _, unit in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetUnits())) do
    local urow = GameInfo.Units[unit:GetType()]
    local t = urow ~= nil and urow.UnitType or ""
    if t == "UNIT_GREAT_PROPHET" then
      out.prophets[#out.prophets + 1] = {
        unit_id = Civ6Ai_Snapshot._UnitWireId(unit), x = unit:GetX(), y = unit:GetY(),
        on_holy_site = isHolySite(Map.GetPlot(unit:GetX(), unit:GetY()), playerID),
      }
    elseif t == "UNIT_MISSIONARY" or t == "UNIT_APOSTLE" or t == "UNIT_INQUISITOR" or t == "UNIT_GURU" then
      out.religious_units[t] = (out.religious_units[t] or 0) + 1
    end
  end
  if rrow == nil and #out.prophets > 0 then
    for r in GameInfo.Religions() do
      if r.Pantheon ~= true and gcall(game, "HasBeenFounded", r.Index) ~= true then
        out.religion_options[#out.religion_options + 1] = r.ReligionType
      end
    end
    for b in GameInfo.Beliefs() do
      if not gtrue(game, "IsInSomeReligion", b) then
        local entry = { id = b.BeliefType, effect = Civ6Ai_Snapshot._GovText(b.Description, Civ6Ai_Snapshot.EFFECT_MAX) }
        if b.BeliefClassType == "BELIEF_CLASS_FOUNDER" then
          out.founder_beliefs[#out.founder_beliefs + 1] = entry
        elseif b.BeliefClassType == "BELIEF_CLASS_FOLLOWER" then
          out.follower_beliefs[#out.follower_beliefs + 1] = entry
        elseif b.BeliefClassType == "BELIEF_CLASS_WORSHIP" then
          out.worship_beliefs[#out.worship_beliefs + 1] = entry
        elseif b.BeliefClassType == "BELIEF_CLASS_ENHANCER" then
          out.enhancer_beliefs[#out.enhancer_beliefs + 1] = entry
        end
      end
    end
  end
  return out
end

function Civ6Ai_Snapshot._GovGovernors(playerID, player)
  local govs = player.GetGovernors ~= nil and player:GetGovernors() or nil
  local out = { appointed = Civ6Ai_Util.JsonArrayList(), candidates = Civ6Ai_Util.JsonArrayList(), cities = Civ6Ai_Util.JsonArrayList() }
  if govs == nil or GameInfo.Governors == nil then
    out.supported = false
    return out
  end
  out.supported = true
  out.points = gcall(govs, "GetGovernorPoints") or 0
  out.spent = gcall(govs, "GetGovernorPointsSpent") or 0
  out.can_appoint = gcall(govs, "CanAppoint") == true
  local has = {}
  local okList, a, b = pcall(govs.GetGovernorList, govs)
  local list = okList and (type(b) == "table" and b or (type(a) == "table" and a or nil)) or nil
  local promosBy = {}
  if GameInfo.GovernorPromotionSets ~= nil then
    for s in GameInfo.GovernorPromotionSets() do
      local l = promosBy[s.GovernorType] or {}
      l[#l + 1] = s.GovernorPromotion
      promosBy[s.GovernorType] = l
    end
  end
  local prereqs = {}
  if GameInfo.GovernorPromotionPrereqs ~= nil then
    for r in GameInfo.GovernorPromotionPrereqs() do
      local l = prereqs[r.GovernorPromotionType] or {}
      l[#l + 1] = r.PrereqGovernorPromotion
      prereqs[r.GovernorPromotionType] = l
    end
  end
  for _, g in ipairs(list or {}) do
    local grow = GameInfo.Governors[gcall(g, "GetType")]
    if grow ~= nil then
      has[grow.GovernorType] = true
      local city = gcall(g, "GetAssignedCity")
      local owned, options = {}, Civ6Ai_Util.JsonArrayList()
      for _, promo in ipairs(promosBy[grow.GovernorType] or {}) do
        local hash = DB ~= nil and DB.MakeHash ~= nil and DB.MakeHash(promo) or nil
        if hash ~= nil and gcall(g, "HasPromotion", hash) == true then
          owned[promo] = true
        end
      end
      local ownedList = {}
      local ownedEffects = Civ6Ai_Util.JsonArrayList()
      for _, promo in ipairs(promosBy[grow.GovernorType] or {}) do
        if owned[promo] then
          ownedList[#ownedList + 1] = promo
          local orow = GameInfo.GovernorPromotions ~= nil and GameInfo.GovernorPromotions[promo] or nil
          ownedEffects[#ownedEffects + 1] = { id = promo,
            effect = Civ6Ai_Snapshot._GovText(orow and orow.Description, Civ6Ai_Snapshot.EFFECT_MAX) }
        else
          local ready = true
          local reqs = prereqs[promo] or {}
          if #reqs > 0 then
            ready = false
            for _, req in ipairs(reqs) do
              if owned[req] then
                ready = true
              end
            end
          end
          if ready then
            local prow = GameInfo.GovernorPromotions ~= nil and GameInfo.GovernorPromotions[promo] or nil
            options[#options + 1] = { id = promo, effect = Civ6Ai_Snapshot._GovText(prow and prow.Description, Civ6Ai_Snapshot.EFFECT_MAX) }
          end
        end
      end
      out.appointed[#out.appointed + 1] = {
        id = grow.GovernorType,
        city = city ~= nil and Locale.Lookup(city:GetName()) or nil,
        city_id = city ~= nil and ("CITY_" .. tostring(city:GetID())) or nil,
        established = gcall(g, "IsEstablished") == true,
        turns_to_establish = gcall(g, "GetTurnsToEstablish"),
        neutralized_turns = gcall(g, "GetNeutralizedTurns") or 0,
        can_promote = gcall(govs, "CanPromoteGovernor", grow.Hash) == true,
        promotions = table.concat(ownedList, "/"),
        promotion_effects = ownedEffects,
        promotion_options = options,
        title = Civ6Ai_Snapshot._GovText(grow.Title, 50),
      }
    end
  end
  for grow in GameInfo.Governors() do
    if not has[grow.GovernorType] and gcall(govs, "CanEverAppointGovernor", grow.Hash) ~= false
        and (grow.TraitType == nil or gcall(govs, "CanEverAppointGovernor", grow.Hash) == true) then
      out.candidates[#out.candidates + 1] = {
        id = grow.GovernorType,
        title = Civ6Ai_Snapshot._GovText(grow.Title, 50),
        effect = Civ6Ai_Snapshot._GovText(grow.Description, Civ6Ai_Snapshot.EFFECT_MAX),
      }
    end
  end
  for _, city in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetCities())) do
    out.cities[#out.cities + 1] = { city_id = "CITY_" .. tostring(city:GetID()), name = Locale.Lookup(city:GetName()) }
  end
  return out
end

function Civ6Ai_Snapshot._GovGreatPeople(playerID, player)
  local out = { points = Civ6Ai_Util.JsonArrayList(), available = Civ6Ai_Util.JsonArrayList() }
  local gpp = player.GetGreatPeoplePoints ~= nil and player:GetGreatPeoplePoints() or nil
  local gp = Game.GetGreatPeople ~= nil and Game.GetGreatPeople() or nil
  local byClass = {}
  if GameInfo.GreatPersonClasses ~= nil then
    for c in GameInfo.GreatPersonClasses() do
      local total = gcall(gpp, "GetPointsTotal", c.Index) or 0
      local rate = gcall(gpp, "GetPointsPerTurn", c.Index) or 0
      byClass[c.Index] = c.GreatPersonClassType
      if total > 0 or rate > 0 then
        out.points[#out.points + 1] = { class = c.GreatPersonClassType, points = math.floor(total), per_turn = rate }
      end
    end
  end
  local okT, timeline = pcall(function() return gp:GetTimeline() end)
  if okT and type(timeline) == "table" then
    local gold = GameInfo.Yields["YIELD_GOLD"]
    local faith = GameInfo.Yields["YIELD_FAITH"]
    for _, e in ipairs(timeline) do
      if e.Individual ~= nil and e.Claimant == nil then
        local irow = GameInfo.GreatPersonIndividuals[e.Individual]
        if irow ~= nil then
          out.available[#out.available + 1] = {
            id = irow.GreatPersonIndividualType,
            class = byClass[e.Class] or tostring(e.Class),
            cost = e.Cost,
            can_recruit = gcall(gp, "CanRecruitPerson", playerID, e.Individual) == true,
            gold_cost = gold and gcall(gp, "GetPatronizeCost", playerID, e.Individual, gold.Index) or nil,
            faith_cost = faith and gcall(gp, "GetPatronizeCost", playerID, e.Individual, faith.Index) or nil,
            can_patronize_gold = gold ~= nil and gcall(gp, "CanPatronizePerson", playerID, e.Individual, gold.Index) == true,
            can_patronize_faith = faith ~= nil and gcall(gp, "CanPatronizePerson", playerID, e.Individual, faith.Index) == true,
            effect = Civ6Ai_Snapshot._GovText(e.ActionEffectText, Civ6Ai_Snapshot.EFFECT_MAX)
              or Civ6Ai_Snapshot._GovText(irow.ActionEffectTextOverride, Civ6Ai_Snapshot.EFFECT_MAX)
              or Civ6Ai_Snapshot._GovText(e.PassiveEffectText, Civ6Ai_Snapshot.EFFECT_MAX),
          }
        end
      end
    end
  end
  return out
end

function Civ6Ai_Snapshot._GovGreatWorks(player)
  local works = Civ6Ai_Util.JsonArrayList()
  local emptySlots = {}
  for _, city in ipairs(Civ6Ai_Snapshot._IterateUnits(player:GetCities())) do
    local b = city:GetBuildings()
    for row in GameInfo.Buildings() do
      local n = b ~= nil and gcall(b, "HasBuilding", row.Index) == true and (gcall(b, "GetNumGreatWorkSlots", row.Index) or 0) or 0
      for i = 0, n - 1 do
        local gw = gcall(b, "GetGreatWorkInSlot", row.Index, i)
        if gw ~= nil and gw >= 0 then
          local t = gcall(b, "GetGreatWorkTypeFromIndex", gw)
          local wrow = t ~= nil and GameInfo.GreatWorks[t] or nil
          works[#works + 1] = {
            city = Locale.Lookup(city:GetName()), building = row.BuildingType,
            work = wrow ~= nil and wrow.GreatWorkType or tostring(t),
            kind = wrow ~= nil and wrow.GreatWorkObjectType or nil,
          }
        else
          local st = gcall(b, "GetGreatWorkSlotType", row.Index, i)
          local srow = st ~= nil and GameInfo.GreatWorkSlotTypes ~= nil and GameInfo.GreatWorkSlotTypes[st] or nil
          local key = srow ~= nil and srow.GreatWorkSlotType or "GREATWORKSLOT_ANY"
          emptySlots[key] = (emptySlots[key] or 0) + 1
        end
      end
    end
  end
  return works, emptySlots
end

function Civ6Ai_Snapshot._BuildGovernance(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local culture = player:GetCulture()
  local out = {}
  local parts = {
    { "government", function() return Civ6Ai_Snapshot._GovGovernment(culture) end },
    { "policies", function() return Civ6Ai_Snapshot._GovPolicies(culture) end },
    { "civics", function() return Civ6Ai_Snapshot._GovCivics(culture, player) end },
    { "techs", function() return Civ6Ai_Snapshot._GovTechs(player) end },
    { "religion", function() return Civ6Ai_Snapshot._GovReligion(playerID, player) end },
    { "governors", function() return Civ6Ai_Snapshot._GovGovernors(playerID, player) end },
    { "great_people", function() return Civ6Ai_Snapshot._GovGreatPeople(playerID, player) end },
    { "world_congress", function() return Civ6Ai_Snapshot._WorldCongress() end },
  }
  for _, part in ipairs(parts) do
    local ok, value = pcall(part[2])
    if ok and type(value) == "table" then
      out[part[1]] = value
    else
      Civ6Ai_Util.Log("snapshot|governance_failed|" .. part[1] .. "|" .. tostring(value))
    end
  end
  local okW, works, empty = pcall(Civ6Ai_Snapshot._GovGreatWorks, player)
  if okW then
    out.great_works = works
    out.great_work_empty_slots = empty
  end
  -- Which commands this seat's route can carry (interface requests exist only
  -- for the local player; a game script cannot slot cards or run governors).
  out.routes = Civ6Ai_Snapshot._GovRoutes(playerID)
  if player.GetFavor ~= nil then
    out.favor = Civ6Ai_Snapshot._Favor(playerID)
    out.favor_per_turn = Civ6Ai_Snapshot._FavorPerTurn(playerID)
  end
  return out
end

function Civ6Ai_Snapshot._GovRoutes(playerID)
  local isLocal = Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() == playerID
  return {
    government = true, pantheon = true, religion = true, great_people = true, civic = true,
    policies = isLocal,
    governors = isLocal,
    mode = isLocal and "local_player" or "synced_order",
  }
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
  local northDy = Civ6Ai_Snapshot._NorthDy(mapWidth, mapHeight)
  local techId = Civ6Ai_Snapshot._CurrentTech(playerID)
  local sessionId = Civ6Ai_Bridge.SessionId()
  local yourEmpire = Civ6Ai_Snapshot._BuildYourEmpire(playerID, player)
  local okExtra, cityExtra = pcall(Civ6Ai_Snapshot._BuildCityExtra, playerID)
  local civ6Block = {
    session_id = sessionId,
    research_tech = Civ6Ai_Snapshot._NullableId(techId),
    research_civic = Civ6Ai_Snapshot._CurrentCivic(playerID),
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
      -- civ6.map is additionalProperties:false in the schema, so the measured axis and
      -- river-edge format ride in coords_note (sidecar parses "measured north_dy=N").
      coords_note = "grid x,y; " .. (northDy > 0 and "Y increases north"
        or (northDy < 0 and "Y increases south" or "Y direction unknown"))
        .. " (measured north_dy=" .. tostring(northDy) .. "); river_edges across-v2",
    },
  }
  if okExtra and type(cityExtra) == "table" then
    civ6Block.city_extra = cityExtra
  end
  local okEconomy, economy = pcall(Civ6Ai_Snapshot._BuildEconomy, playerID, legal)
  if okEconomy and type(economy) == "table" then
    civ6Block.economy = economy
  else
    Civ6Ai_Util.Log("snapshot|economy_failed|" .. tostring(economy))
  end
  -- Build priorities travel on the synced order channel for every seat; the
  -- sidecar offers the priorities command when this list is present. The local
  -- seat's empty queues are filled from them (FillEmptyQueuesWeighted).
  civ6Block.priorities = Civ6Ai_Snapshot._Priorities(playerID)
  local okDiplo, civ6Diplomacy = pcall(Civ6Ai_Snapshot._BuildDiplomacy, playerID)
  if okDiplo and type(civ6Diplomacy) == "table" then
    civ6Block.diplomacy = civ6Diplomacy
  else
    Civ6Ai_Util.Log("snapshot|diplomacy_failed|" .. tostring(civ6Diplomacy))
  end
  local okCombat, combat = pcall(Civ6Ai_Snapshot._BuildCombat, playerID)
  if okCombat and type(combat) == "table" then
    civ6Block.combat = combat
  else
    Civ6Ai_Util.Log("snapshot|combat_failed|" .. tostring(combat))
  end
  local okRankings, rankings = pcall(Civ6Ai_Snapshot._BuildRankings, playerID)
  if okRankings and type(rankings) == "table" then
    civ6Block.rankings = rankings
  else
    Civ6Ai_Util.Log("snapshot|rankings_failed|" .. tostring(rankings))
  end
  local okClimate, climate = pcall(Civ6Ai_Snapshot._BuildClimate, playerID)
  if okClimate and type(climate) == "table" then
    civ6Block.climate = climate
  elseif not okClimate then
    Civ6Ai_Util.Log("snapshot|climate_failed|" .. tostring(climate))
  end
  local okPower, power = pcall(Civ6Ai_Snapshot._BuildPower, playerID)
  if okPower and type(power) == "table" then
    civ6Block.power = power
  elseif not okPower then
    Civ6Ai_Util.Log("snapshot|power_failed|" .. tostring(power))
  end
  local okStock, stockpiles = pcall(Civ6Ai_Snapshot._BuildStockpiles, playerID)
  if okStock and type(stockpiles) == "table" then
    civ6Block.stockpiles = stockpiles
  elseif not okStock then
    Civ6Ai_Util.Log("snapshot|stockpiles_failed|" .. tostring(stockpiles))
  end
  local okGov, governance = pcall(Civ6Ai_Snapshot._BuildGovernance, playerID)
  if okGov and type(governance) == "table" then
    civ6Block.governance = governance
  else
    Civ6Ai_Util.Log("snapshot|governance_failed|" .. tostring(governance))
  end
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
    for _, event in ipairs(Civ6Ai_Chat.GetPublicEvents(playerID)) do
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
    known_other_cities = Civ6Ai_Snapshot._SafeList(function()
      return Civ6Ai_Snapshot._BuildKnownOtherCities(playerID, turn)
    end),
    visible_other_units = Civ6Ai_Snapshot._SafeList(function()
      return Civ6Ai_Snapshot._BuildVisibleOtherUnits(playerID)
    end),
    diplomacy = diplomacyBlock,
    strategic_summary = strategicSummary,
    history = {
      accepted_decisions = Civ6Ai_Util.JsonArrayList(),
      command_results = Civ6Ai_Snapshot._AddCommandResults(playerID, turn),
      public_events = publicEvents,
      diplomacy_events = Civ6Ai_Util.JsonArrayList(),
    },
    advciv = {
      default_unit_controller = "native",
      fallback_policy = "The host fallback (Civ6Ai_Orders) handles units the model did not order; it never overrides a model order.",
      recommendations = Civ6Ai_Util.JsonArrayList(),
    },
    legal_commands = legal,
    civ6 = civ6Block,
  }
  return Civ6Ai_Util.EncodeJsonObject(payload), legal
end

-- ---------------------------------------------------------------------------
-- civ6.rankings: the in-game World Rankings screen as data. Same engine calls
-- as Base/Assets/UI/PartialScreens/WorldRankings.lua (+ Expansion2's
-- WorldRankings_Expansion2.lua): Game.GetVictoryProgressForTeam for the
-- overview order, then the screen's tiebreakers (techs/science, tourism/culture,
-- cities following/faith, military strength, diplomatic victory points).
-- Every alive major is listed like the screen does; unmet players carry
-- met=false and no leader/civ identity (the sidecar prints "Unmet Civilization").
-- Every engine call is pcall-guarded; a missing method just omits that field.
-- ---------------------------------------------------------------------------
Civ6Ai_Snapshot.RANKING_VICTORIES = {
  "VICTORY_TECHNOLOGY", "VICTORY_CULTURE", "VICTORY_CONQUEST",
  "VICTORY_RELIGIOUS", "VICTORY_DIPLOMATIC", "VICTORY_SCORE",
}
Civ6Ai_Snapshot.RANKING_SPACE_PROJECTS = {
  "PROJECT_LAUNCH_EARTH_SATELLITE", "PROJECT_LAUNCH_MOON_LANDING",
  "PROJECT_LAUNCH_MARS_BASE", "PROJECT_LAUNCH_MARS_REACTOR",
  "PROJECT_LAUNCH_MARS_HABITATION", "PROJECT_LAUNCH_MARS_HYDROPONICS",
  "PROJECT_LAUNCH_EXOPLANET_EXPEDITION",
}

function Civ6Ai_Snapshot._RankNum(value)
  if type(value) ~= "number" or value ~= value then
    return nil
  end
  if value == math.floor(value) then
    return value
  end
  return math.floor(value * 10 + 0.5) / 10
end

function Civ6Ai_Snapshot._RankGameInfoRow(tableName, key)
  return Civ6Ai_Snapshot._Try(function()
    local t = GameInfo[tableName]
    if t == nil then return nil end
    return t[key]
  end)
end

function Civ6Ai_Snapshot._RankRuleset()
  if Civ6Ai_Snapshot._RankGameInfoRow("Victories", "VICTORY_DIPLOMATIC") ~= nil then
    return "EXPANSION2"
  end
  local hasGovernors = Civ6Ai_Snapshot._Try(function()
    return GameInfo.Governors ~= nil and GameInfo.Governors["GOVERNOR_THE_EDUCATOR"] ~= nil
  end)
  if hasGovernors then
    return "EXPANSION1"
  end
  return "BASE"
end

function Civ6Ai_Snapshot._RankAliveMajorIDs()
  local ids = {}
  local fromManager = Civ6Ai_Snapshot._Try(function()
    local list = {}
    for _, p in ipairs(PlayerManager.GetAliveMajors()) do
      table.insert(list, p:GetID())
    end
    return list
  end)
  if type(fromManager) == "table" and #fromManager > 0 then
    ids = fromManager
  else
    for otherID = 0, 63 do
      if Civ6Ai_Snapshot._PlayerKind(otherID) == "major" then
        table.insert(ids, otherID)
      end
    end
  end
  table.sort(ids)
  return ids
end

function Civ6Ai_Snapshot._RankReligionInfo(religionType)
  if type(religionType) ~= "number" or religionType < 0 then
    return nil
  end
  local row = Civ6Ai_Snapshot._Try(function() return GameInfo.Religions[religionType] end)
  local name = Civ6Ai_Snapshot._Try(function() return Game.GetReligion():GetName(religionType) end)
  if (name == nil or name == "") and row ~= nil and row.Name ~= nil then
    name = Civ6Ai_Snapshot._Try(Locale.Lookup, row.Name)
  end
  return {
    id = row ~= nil and row.ReligionType or tostring(religionType),
    name = name ~= nil and tostring(name) or Civ6Ai_Util.JsonNull(),
  }
end

function Civ6Ai_Snapshot._RankSpaceProgress(player)
  local stats = Civ6Ai_Snapshot._Method(player, "GetStats")
  local done, total = 0, 0
  for _, projectType in ipairs(Civ6Ai_Snapshot.RANKING_SPACE_PROJECTS) do
    local info = Civ6Ai_Snapshot._RankGameInfoRow("Projects", projectType)
    if info ~= nil then
      total = total + 1
      local n = Civ6Ai_Snapshot._Method(stats, "GetNumProjectsAdvanced", info.Index)
      if type(n) == "number" and n > 0 then
        done = done + 1
      end
    end
  end
  local hasSpaceport = false
  local spaceport = Civ6Ai_Snapshot._RankGameInfoRow("Districts", "DISTRICT_SPACEPORT")
  if spaceport ~= nil then
    Civ6Ai_Snapshot._Try(function()
      for _, district in player:GetDistricts():Members() do
        if district ~= nil and district:IsComplete() and district:GetType() == spaceport.Index then
          hasSpaceport = true
          break
        end
      end
    end)
  end
  return done, total, hasSpaceport
end

function Civ6Ai_Snapshot._RankCapitals(player, playerID)
  local hasOriginal, captured, hasCapital = false, Civ6Ai_Snapshot._Arr(), false
  Civ6Ai_Snapshot._Try(function()
    local cities = player:GetCities()
    hasCapital = cities:GetCapitalCity() ~= nil
    for _, city in cities:Members() do
      if city:IsOriginalCapital() then
        local ownerID = city:GetOriginalOwner()
        local owner = Players[ownerID]
        if owner ~= nil and owner:IsMajor() then
          if ownerID == playerID then
            hasOriginal = true
          else
            table.insert(captured, Civ6Ai_Snapshot._PlayerLabel(ownerID))
          end
        end
      end
    end
  end)
  return hasOriginal, captured, hasCapital
end

function Civ6Ai_Snapshot._RankPlayerRow(viewerID, otherID, majorIDs, dipNeeded)
  local p = Players[otherID]
  local stats = Civ6Ai_Snapshot._Method(p, "GetStats")
  local culture = Civ6Ai_Snapshot._Method(p, "GetCulture")
  local techs = Civ6Ai_Snapshot._Method(p, "GetTechs")
  local religion = Civ6Ai_Snapshot._Method(p, "GetReligion")
  local diplomacy = Civ6Ai_Snapshot._Method(p, "GetDiplomacy")
  local N = Civ6Ai_Snapshot._RankNum
  local met = otherID == viewerID or Civ6Ai_Snapshot._HasMet(viewerID, otherID)
  local row = {
    player_id = Civ6Ai_Snapshot._PlayerLabel(otherID),
    is_you = otherID == viewerID,
    met = met,
    team_id = Civ6Ai_Snapshot._Method(p, "GetTeam"),
    score = N(Civ6Ai_Snapshot._Method(p, "GetScore")),
    -- science
    science_yield = N(Civ6Ai_Snapshot._YieldOrCities(p, Civ6Ai_Snapshot._Method(techs, "GetScienceYield"), YieldTypes ~= nil and YieldTypes.SCIENCE or nil)),
    techs_researched = N(Civ6Ai_Snapshot._Method(stats, "GetNumTechsResearched")),
    science_vp = N(Civ6Ai_Snapshot._Method(stats, "GetScienceVictoryPoints")),
    science_vp_needed = N(Civ6Ai_Snapshot._Method(stats, "GetScienceVictoryPointsTotalNeeded")),
    -- culture
    culture_yield = N(Civ6Ai_Snapshot._YieldOrCities(p, Civ6Ai_Snapshot._Method(culture, "GetCultureYield"), YieldTypes ~= nil and YieldTypes.CULTURE or nil)),
    tourism = N(Civ6Ai_Snapshot._Method(stats, "GetTourism") or Civ6Ai_Snapshot._Method(culture, "GetTourism")),
    domestic_tourists = N(Civ6Ai_Snapshot._Method(culture, "GetStaycationers")),
    foreign_tourists = N(Civ6Ai_Snapshot._Method(culture, "GetTouristsTo")),
    -- domination
    military_strength = N(Civ6Ai_Snapshot._Method(stats, "GetMilitaryStrengthWithoutTreasury")
      or Civ6Ai_Snapshot._Method(stats, "GetMilitaryStrength")),
    -- religion
    faith_yield = N(Civ6Ai_Snapshot._Method(religion, "GetFaithYield")),
    cities_following_religion = N(Civ6Ai_Snapshot._Method(stats, "GetNumCitiesFollowingReligion")),
    -- diplomacy
    diplomatic_vp = N(Civ6Ai_Snapshot._Method(stats, "GetDiplomaticVictoryPoints")),
    -- Gathering Storm exposes favor on the player (pPlayer:GetFavor()); keep the
    -- diplomacy fallback for other rulesets / builds.
    favor = N(Civ6Ai_Snapshot._Method(p, "GetFavor") or Civ6Ai_Snapshot._Method(diplomacy, "GetFavor")),
    favor_per_turn = N(Civ6Ai_Snapshot._Method(p, "GetFavorPerTurn")),
  }
  if met and otherID ~= viewerID then
    row.leader_name = Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._LeaderName, otherID)
    row.civilization_id = Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._CivId, otherID)
  elseif otherID == viewerID then
    row.leader_name = Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._LeaderName, otherID)
    row.civilization_id = Civ6Ai_Snapshot._Try(Civ6Ai_Snapshot._CivId, otherID)
  end
  -- Culture victory: foreign tourists must exceed every other civ's domestic tourists.
  local needed = 0
  for _, id in ipairs(majorIDs) do
    if id ~= otherID then
      local other = Players[id]
      if Civ6Ai_Snapshot._Method(other, "GetTeam") ~= row.team_id then
        local stay = Civ6Ai_Snapshot._Method(Civ6Ai_Snapshot._Method(other, "GetCulture"), "GetStaycationers")
        if type(stay) == "number" and stay >= needed then
          needed = stay + 1
        end
      end
    end
  end
  row.tourists_needed = needed
  if otherID ~= viewerID then
    local viewerCulture = Civ6Ai_Snapshot._Method(Players[viewerID], "GetCulture")
    row.their_tourists_visiting_you = N(Civ6Ai_Snapshot._Method(viewerCulture, "GetTouristsFrom", otherID))
    row.your_tourists_visiting_them = N(Civ6Ai_Snapshot._Method(culture, "GetTouristsFrom", viewerID))
    row.you_culturally_dominant = Civ6Ai_Snapshot._Method(viewerCulture, "IsDominantOver", otherID)
    row.they_culturally_dominant = Civ6Ai_Snapshot._Method(culture, "IsDominantOver", viewerID)
  end
  local turnsCV = Civ6Ai_Snapshot._Method(culture, "GetTurnsUntilVictory")
  if type(turnsCV) == "number" and turnsCV >= 0 then
    row.turns_until_culture_victory = turnsCV
  end
  local spaceDone, spaceTotal, spaceport = Civ6Ai_Snapshot._RankSpaceProgress(p)
  row.space_projects_done = spaceDone
  row.space_projects_total = spaceTotal
  row.has_spaceport = spaceport
  local hasOriginal, captured, hasCapital = Civ6Ai_Snapshot._RankCapitals(p, otherID)
  row.has_original_capital = hasOriginal
  row.has_capital = hasCapital
  row.captured_capitals = captured
  -- Religion: founded religion, majority religion, civs converted to theirs.
  local founded = Civ6Ai_Snapshot._Method(religion, "GetReligionTypeCreated")
  local foundedInfo = Civ6Ai_Snapshot._RankReligionInfo(founded)
  if foundedInfo ~= nil then
    row.religion_founded = foundedInfo
    local converted = Civ6Ai_Snapshot._Arr()
    for _, id in ipairs(majorIDs) do
      local maj = Civ6Ai_Snapshot._Method(Civ6Ai_Snapshot._Method(Players[id], "GetReligion"), "GetReligionInMajorityOfCities")
      if maj == founded then
        table.insert(converted, Civ6Ai_Snapshot._PlayerLabel(id))
      end
    end
    row.civs_converted = converted
  end
  local majority = Civ6Ai_Snapshot._RankReligionInfo(Civ6Ai_Snapshot._Method(religion, "GetReligionInMajorityOfCities"))
  if majority ~= nil then
    row.majority_religion = majority
  end
  local function relLabel(info)
    if info == nil then
      return nil
    end
    if type(info.name) == "string" and info.name ~= "" and info.name ~= "NULL" then
      return info.name
    end
    if type(info.id) == "string" and info.id ~= "" then
      return info.id
    end
    return nil
  end
  local religionName = relLabel(foundedInfo) or relLabel(majority)
  if religionName ~= nil then
    row.religion = religionName
  end
  -- The game era is global. Era score, wonders, and city count are per player.
  -- Each read is optional; a ruleset without the method simply omits the field.
  local era = Civ6Ai_Snapshot._CurrentEraId()
  if type(era) == "string" and era ~= "" and era ~= "UNKNOWN" then
    row.era = era
  end
  local eraScore = nil
  local eras = Civ6Ai_Snapshot._Try(function() return Game.GetEras() end)
  if eras ~= nil then
    eraScore = Civ6Ai_Snapshot._Method(eras, "GetPlayerCurrentScore", otherID)
  end
  if type(eraScore) ~= "number" then
    local playerEra = Civ6Ai_Snapshot._Method(p, "GetEra")
    eraScore = Civ6Ai_Snapshot._Method(playerEra, "GetPlayerEraScore")
      or Civ6Ai_Snapshot._Method(playerEra, "GetCurrentEraScore")
  end
  if type(eraScore) == "number" then
    row.era_score = math.floor(eraScore)
  end
  local wonders = Civ6Ai_Snapshot._Method(stats, "GetNumWondersBuilt")
    or Civ6Ai_Snapshot._Method(stats, "GetNumWondersConstructed")
  if type(wonders) == "number" then
    row.wonders = math.floor(wonders)
  end
  local cityCount = Civ6Ai_Snapshot._Method(Civ6Ai_Snapshot._Method(p, "GetCities"), "GetCount")
  if type(cityCount) ~= "number" then
    local counted, total = false, 0
    Civ6Ai_Snapshot._Try(function()
      for _ in p:GetCities():Members() do
        total = total + 1
        counted = true
      end
    end)
    if counted then
      cityCount = total
    end
  end
  if type(cityCount) == "number" then
    row.cities = math.floor(cityCount)
  end
  -- Overview order key: Game.GetVictoryProgressForTeam per enabled victory.
  local progress = {}
  if type(row.team_id) == "number" then
    for _, victoryType in ipairs(Civ6Ai_Snapshot.RANKING_VICTORIES) do
      local v = Civ6Ai_Snapshot._Try(function() return Game.GetVictoryProgressForTeam(victoryType, row.team_id) end)
      if type(v) == "number" then
        progress[victoryType] = N(v)
      end
    end
  end
  row.victory_progress = progress
  return row
end

function Civ6Ai_Snapshot._BuildRankings(playerID)
  local majorIDs = Civ6Ai_Snapshot._RankAliveMajorIDs()
  local enabled = {}
  for _, victoryType in ipairs(Civ6Ai_Snapshot.RANKING_VICTORIES) do
    local on = Civ6Ai_Snapshot._Try(function() return Game.IsVictoryEnabled(victoryType) end)
    if type(on) == "boolean" then
      enabled[victoryType] = on
    end
  end
  local dipNeeded = Civ6Ai_Snapshot._Try(function()
    return GlobalParameters ~= nil and GlobalParameters.DIPLOMATIC_VICTORY_POINTS_REQUIRED or nil
  end)
  local players = Civ6Ai_Snapshot._Arr()
  local seenYou = false
  for _, id in ipairs(majorIDs) do
    if id == playerID then seenYou = true end
    local ok, row = pcall(Civ6Ai_Snapshot._RankPlayerRow, playerID, id, majorIDs, dipNeeded)
    if ok and type(row) == "table" then
      table.insert(players, row)
    else
      Civ6Ai_Util.Log("snapshot|rankings_row_failed|" .. tostring(id) .. "|" .. tostring(row))
    end
  end
  if not seenYou and Players[playerID] ~= nil then
    local ok, row = pcall(Civ6Ai_Snapshot._RankPlayerRow, playerID, playerID, majorIDs, dipNeeded)
    if ok and type(row) == "table" then table.insert(players, row) end
  end
  return {
    source = "WorldRankings.lua engine calls",
    ruleset = Civ6Ai_Snapshot._RankRuleset(),
    victories_enabled = enabled,
    diplomatic_vp_needed = Civ6Ai_Snapshot._RankNum(dipNeeded),
    you = Civ6Ai_Snapshot._PlayerLabel(playerID),
    players = players,
  }
end

-- Gathering Storm climate / city power / strategic stockpiles. APIs are the ones
-- ClimateScreen.lua, CityBannerManager.lua, CityPanelPower.lua, and
-- TopPanel_Expansion2.lua already call. Each builder returns nil until the
-- system is relevant (CO2/temperature/level underway; a city that needs or
-- produces power; a strategic with stock, income, or demand) so early ages
-- stay quiet.

function Civ6Ai_Snapshot._ClimateNum(name, ...)
  local value = Civ6Ai_Snapshot._Static(GameClimate, name, ...)
  if type(value) == "number" then
    return value
  end
  return nil
end

function Civ6Ai_Snapshot._BuildClimate(playerID)
  if GameClimate == nil then
    return nil
  end
  local co2World = Civ6Ai_Snapshot._ClimateNum("GetTotalCO2Footprint") or 0
  local co2You = Civ6Ai_Snapshot._ClimateNum("GetPlayerCO2Footprint", playerID, false) or 0
  local level = Civ6Ai_Snapshot._ClimateNum("GetClimateChangeLevel") or 0
  local temp = Civ6Ai_Snapshot._ClimateNum("GetTemperatureChange") or 0
  if co2World <= 0 and co2You <= 0 and level <= 0 and temp <= 0 then
    return nil
  end
  local out = {
    source = "ClimateScreen.lua GameClimate",
    co2_world = math.floor(co2World),
    co2_you = math.floor(co2You),
    level = math.floor(level),
    temperature_c_tenths = math.floor(temp * 10 + (temp >= 0 and 0.5 or -0.5)),
  }
  local seaTurns = Civ6Ai_Snapshot._ClimateNum("GetNextSeaLevelRiseTurns")
  if type(seaTurns) == "number" then
    out.sea_rise_turns = math.floor(seaTurns)
  end
  local flooded = Civ6Ai_Snapshot._ClimateNum("GetTilesFlooded")
  if type(flooded) == "number" then
    out.tiles_flooded = math.floor(flooded)
  end
  local submerged = Civ6Ai_Snapshot._ClimateNum("GetTilesSubmerged")
  if type(submerged) == "number" then
    out.tiles_submerged = math.floor(submerged)
  end
  local storm = Civ6Ai_Snapshot._ClimateNum("GetStormPercentChance")
  if type(storm) == "number" then
    out.storm_pct = math.floor(storm)
  end
  local flood = Civ6Ai_Snapshot._ClimateNum("GetFloodPercentChance")
  if type(flood) == "number" then
    out.flood_pct = math.floor(flood)
  end
  local drought = Civ6Ai_Snapshot._ClimateNum("GetDroughtPercentChance")
  if type(drought) == "number" then
    out.drought_pct = math.floor(drought)
  end
  return out
end

function Civ6Ai_Snapshot._PowerCityId(city)
  if Civ6Ai_Production ~= nil and Civ6Ai_Production._WireCityId ~= nil then
    return Civ6Ai_Production._WireCityId(city)
  end
  return "CITY_" .. tostring(Civ6Ai_Snapshot._Method(city, "GetID") or 0)
end

function Civ6Ai_Snapshot._BuildPower(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local cities = Civ6Ai_Snapshot._Method(player, "GetCities")
  if cities == nil then
    return nil
  end
  local rows = Civ6Ai_Snapshot._Arr()
  local seen = false
  local anyApi = false
  local powered = 0
  local needing = 0
  for _, city in cities:Members() do
    local pwr = Civ6Ai_Snapshot._Method(city, "GetPower")
    if pwr ~= nil then
      anyApi = true
      local free = Civ6Ai_Snapshot._Method(pwr, "GetFreePower")
      local temp = Civ6Ai_Snapshot._Method(pwr, "GetTemporaryPower")
      local req = Civ6Ai_Snapshot._Method(pwr, "GetRequiredPower")
      if type(free) ~= "number" then free = 0 end
      if type(temp) ~= "number" then temp = 0 end
      if type(req) ~= "number" then req = 0 end
      -- CityBannerManager.lua only shows the icon when any of these is > 0.
      if free > 0 or temp > 0 or req > 0 then
        seen = true
        needing = needing + 1
        local fully = Civ6Ai_Snapshot._Method(pwr, "IsFullyPowered") == true
        if fully then
          powered = powered + 1
        end
        table.insert(rows, {
          city_id = Civ6Ai_Snapshot._PowerCityId(city),
          name = Locale.Lookup(Civ6Ai_Snapshot._Method(city, "GetName") or ""),
          required = req,
          free = free,
          temporary = temp,
          powered = fully,
          powered_by_project = Civ6Ai_Snapshot._Method(pwr, "IsFullyPoweredByActiveProject") == true,
        })
      end
    end
  end
  if not anyApi or not seen then
    return nil
  end
  return {
    source = "CityBannerManager.lua city:GetPower",
    cities_powered = powered,
    cities_needing = needing,
    cities = rows,
  }
end

Civ6Ai_Snapshot.STOCKPILE_CAP = 12

function Civ6Ai_Snapshot._ResourceNum(resources, method, row)
  local byType = Civ6Ai_Snapshot._Method(resources, method, row.ResourceType)
  if type(byType) == "number" then
    return byType
  end
  local byIndex = Civ6Ai_Snapshot._Method(resources, method, row.Index)
  if type(byIndex) == "number" then
    return byIndex
  end
  return 0
end

function Civ6Ai_Snapshot._BuildStockpiles(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  local resources = Civ6Ai_Snapshot._Method(player, "GetResources")
  if resources == nil then
    return nil
  end
  local okCap, capFn = pcall(function() return resources.GetResourceStockpileCap end)
  if not okCap or type(capFn) ~= "function" then
    return nil
  end
  if GameInfo == nil or GameInfo.Resources == nil then
    return nil
  end
  local rows = Civ6Ai_Snapshot._Arr()
  pcall(function()
    for row in GameInfo.Resources() do
      if row.ResourceClassType == "RESOURCECLASS_STRATEGIC" and #rows < Civ6Ai_Snapshot.STOCKPILE_CAP then
        local amount = Civ6Ai_Snapshot._ResourceNum(resources, "GetResourceAmount", row)
        local cap = Civ6Ai_Snapshot._ResourceNum(resources, "GetResourceStockpileCap", row)
        local reserved = Civ6Ai_Snapshot._ResourceNum(resources, "GetReservedResourceAmount", row)
        local acc = Civ6Ai_Snapshot._ResourceNum(resources, "GetResourceAccumulationPerTurn", row)
        local imported = Civ6Ai_Snapshot._ResourceNum(resources, "GetResourceImportPerTurn", row)
        local bonus = Civ6Ai_Snapshot._ResourceNum(resources, "GetBonusResourcePerTurn", row)
        local unitDemand = Civ6Ai_Snapshot._ResourceNum(resources, "GetUnitResourceDemandPerTurn", row)
        local powerDemand = Civ6Ai_Snapshot._ResourceNum(resources, "GetPowerResourceDemandPerTurn", row)
        if amount > 0 or reserved > 0 or acc > 0 or imported > 0 or bonus > 0
            or unitDemand > 0 or powerDemand > 0 then
          table.insert(rows, {
            resource_id = row.ResourceType,
            amount = math.floor(amount),
            cap = math.floor(cap),
            reserved = math.floor(reserved),
            per_turn = math.floor(acc + imported + bonus + 0.5),
            from_improvements = math.floor(acc),
            import = math.floor(imported),
            bonus = math.floor(bonus),
            unit_demand = math.floor(unitDemand),
            power_demand = math.floor(powerDemand),
          })
        end
      end
    end
  end)
  if #rows == 0 then
    return nil
  end
  return {
    source = "TopPanel_Expansion2.lua GetResources stockpile",
    strategics = rows,
  }
end
