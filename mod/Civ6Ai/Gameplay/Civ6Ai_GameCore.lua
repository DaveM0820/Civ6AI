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

-- GameCore (gameplay script) routes used by InGame for seats other than the local
-- player. UnitManager.RequestOperation / CanStartOperation are UI-only; the
-- script-side calls here are UnitManager.MoveUnit(unit, x, y), UnitManager.FinishMoves,
-- Cities:Create(x, y), Techs:SetResearchingTech and Culture:SetProgressingCivic.
-- Every route returns ok(bool), reason(string) and never raises.

function Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  local player = Players[playerID]
  if player == nil then
    return nil, nil, "no_player"
  end
  local units = player:GetUnits()
  if units == nil then
    return player, nil, "no_units"
  end
  local unit = units:FindID(unitNumericId)
  if unit == nil then
    return player, nil, "unit_not_found"
  end
  return player, unit, ""
end

-- Cities:Create skips the engine's founding rules, so enforce the basic ones.
function Civ6Ai_GameCore._CitySiteProblem(x, y)
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
  return nil
end

-- Founding legality from the gameplay side. The UI-side
-- UnitManager.CanStartOperation is false for a non-local seat's settler (and for
-- one with 0 moves), which kept found_city out of seats 1-4's legal commands.
-- Founding through Cities:Create needs no movement.
function Civ6Ai_GameCore.CanFoundCityForPlayer(playerID, unitNumericId)
  local player, unit, reason = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return false, reason
  end
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  if row == nil or not (row.FoundCity == true or row.FoundCity == 1) then
    return false, "unit_cannot_found_city"
  end
  local x, y = unit:GetX(), unit:GetY()
  local siteReason = Civ6Ai_GameCore._CitySiteProblem(x, y)
  if siteReason ~= nil then
    return false, siteReason
  end
  local plot = Map.GetPlot(x, y)
  local owner = plot ~= nil and plot.GetOwner ~= nil and plot:GetOwner() or -1
  if owner ~= nil and owner >= 0 and owner ~= playerID then
    return false, "foreign_territory"
  end
  return true, ""
end

function Civ6Ai_GameCore.FoundCityForPlayer(playerID, unitNumericId)
  local canFound, whyNot = Civ6Ai_GameCore.CanFoundCityForPlayer(playerID, unitNumericId)
  if not canFound then
    return false, whyNot
  end
  local player, unit = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  local x, y = unit:GetX(), unit:GetY()
  local cities = player:GetCities()
  if cities == nil or cities.Create == nil then
    return false, "city_create_unavailable"
  end
  local okCreate, created = pcall(function()
    return cities:Create(x, y)
  end)
  if not okCreate or created == nil then
    return false, "found_city_rejected"
  end
  if UnitManager.Kill ~= nil then
    pcall(function()
      UnitManager.Kill(unit, false)
    end)
  end
  return true, ""
end

-- Movement cost of one step, the Civ6 rules: a unit needs the full cost of the
-- tile it enters (no spending the last 1 MP on a 3-MP tile). Terrain
-- MovementCost (hills 2) + feature MovementChange (woods/rainforest/marsh +1),
-- +2 to cross a river (no bridge), a road on both plots makes the step cost the
-- road's cost. Embarking/disembarking costs 3 MP or all MP when the unit has less.
Civ6Ai_GameCore.RIVER_CROSSING_COST = 2
Civ6Ai_GameCore.EMBARK_COST = 3
-- Civ6 rule (Civilopedia / Movement): a unit with full movement can always move
-- one tile regardless of terrain, spending all of it; a unit that has already
-- moved needs the full cost. So a step that costs more than the unit's moves is
-- legal when it is at full movement and not embarking (a "first step").
-- It is issued through the engine's own mover (UnitManager.MoveUnit). If the
-- engine refuses it anyway (seen 2026-09-25 for held AI-seat units, which were
-- FinishMoves'd at turn start and given RestoreMovement), FIRST_STEP_TOPUP lets
-- MoveUnit take the step with its movement topped up to the step cost via
-- UnitManager.ChangeMovesRemaining, then ends the unit's moves (FinishMoves),
-- so the result is the rule's: one tile entered, 0 moves left. Each route used is
-- logged (CIV6AI|gamecore|first_step|...). Live session live-20260927-171854:
-- P0's scout (3 MP, cost 4) and warrior (2 MP, cost 3) took the step through
-- MoveUnit alone (T22/T23); P1's held warrior (2/2 MP after RestoreMovement,
-- cost 3) was refused by MoveUnit and moved through the top-up (T24). Holding
-- by zeroing moves instead of FinishMoves (HOLD_MODE) did not bring it back:
-- T31 P1's warrior, held with ChangeMovesRemaining and given 2/2 back, was
-- refused forest-hills 6,13>7,13 (cost 3) although GetMoveToPath planned it,
-- then moved through the top-up. Any hold of a unit costs it the engine's
-- exception. AI-seat orders now run at turn start on untouched movement (no
-- hold); FIRST_STEP_TOPUP stays on until a live log shows AI seats taking the
-- step through first_step:move_unit.
Civ6Ai_GameCore.ALLOW_FIRST_STEP_EXCEPTION = true
Civ6Ai_GameCore.FIRST_STEP_TOPUP = true

function Civ6Ai_GameCore._Call(obj, name, ...)
  if obj == nil then
    return nil
  end
  local fn = obj[name]
  if fn == nil then
    return nil
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local ok, value = pcall(function()
    return fn(obj, unpackFn(args))
  end)
  if ok then
    return value
  end
  return nil
end

function Civ6Ai_GameCore._Row(tableName, key)
  if GameInfo == nil or GameInfo[tableName] == nil or key == nil or key == -1 then
    return nil
  end
  local ok, row = pcall(function()
    return GameInfo[tableName][key]
  end)
  if ok then
    return row
  end
  return nil
end

-- true / false when the engine can tell, nil when it cannot (tests, missing API).
function Civ6Ai_GameCore._IsAdjacent(fromX, fromY, toX, toY)
  if Map == nil then
    return nil
  end
  if Map.GetPlotDistance ~= nil then
    local ok, d = pcall(Map.GetPlotDistance, fromX, fromY, toX, toY)
    if ok and type(d) == "number" then
      return d == 1
    end
  end
  if Map.GetAdjacentPlot ~= nil then
    local found = false
    local ok = pcall(function()
      for direction = 0, 5 do
        local adj = Map.GetAdjacentPlot(fromX, fromY, direction)
        if adj ~= nil and adj:GetX() == toX and adj:GetY() == toY then
          found = true
          return
        end
      end
    end)
    if ok then
      return found
    end
  end
  return nil
end

function Civ6Ai_GameCore._PlotEnterCost(plot)
  local cost = 1
  local terrain = Civ6Ai_GameCore._Row("Terrains", Civ6Ai_GameCore._Call(plot, "GetTerrainType"))
  if terrain ~= nil and tonumber(terrain.MovementCost) ~= nil then
    cost = tonumber(terrain.MovementCost)
  elseif Civ6Ai_GameCore._Call(plot, "IsHills") == true then
    cost = 2
  end
  local feature = Civ6Ai_GameCore._Row("Features", Civ6Ai_GameCore._Call(plot, "GetFeatureType"))
  if feature ~= nil and tonumber(feature.MovementChange) ~= nil then
    cost = cost + tonumber(feature.MovementChange)
  end
  return cost
end

function Civ6Ai_GameCore._RiverBetween(fromPlot, toPlot)
  local crossing = Civ6Ai_GameCore._Call(fromPlot, "IsRiverCrossingToPlot", toPlot)
  return crossing == true
end

-- Road step cost when both plots carry a road; nil otherwise. bridges: the road
-- also removes the river penalty.
function Civ6Ai_GameCore._RoadStep(fromPlot, toPlot)
  local a = Civ6Ai_GameCore._Call(fromPlot, "GetRouteType")
  local b = Civ6Ai_GameCore._Call(toPlot, "GetRouteType")
  if a == nil or b == nil or a == -1 or b == -1 then
    return nil, false
  end
  if Civ6Ai_GameCore._Call(fromPlot, "IsRoutePillaged") == true or Civ6Ai_GameCore._Call(toPlot, "IsRoutePillaged") == true then
    return nil, false
  end
  local ra = Civ6Ai_GameCore._Row("Routes", a)
  local rb = Civ6Ai_GameCore._Row("Routes", b)
  local cost = math.max(tonumber(ra and ra.MovementCost) or 1, tonumber(rb and rb.MovementCost) or 1)
  local bridges = ra ~= nil and rb ~= nil and (ra.SupportsBridges == true or ra.SupportsBridges == 1)
    and (rb.SupportsBridges == true or rb.SupportsBridges == 1)
  return cost, bridges
end

function Civ6Ai_GameCore._HasTech(player, techType)
  local row = Civ6Ai_GameCore._Row("Technologies", techType)
  if row == nil or player == nil then
    return false
  end
  local techs = Civ6Ai_GameCore._Call(player, "GetTechs")
  return Civ6Ai_GameCore._Call(techs, "HasTech", row.Index) == true
end

-- Land unit onto water: needs Shipbuilding (coast/lake) or Cartography (ocean).
function Civ6Ai_GameCore._EmbarkProblem(playerID, plot)
  local player = Players ~= nil and Players[playerID] or nil
  local shallow = Civ6Ai_GameCore._Call(plot, "IsShallowWater")
  if shallow == false then
    if not Civ6Ai_GameCore._HasTech(player, "TECH_CARTOGRAPHY") then
      return "water_no_ocean_embark"
    end
    return nil
  end
  if not Civ6Ai_GameCore._HasTech(player, "TECH_SHIPBUILDING") then
    return "water"
  end
  return nil
end

-- Moves the unit has for an order: its real movement, or, when planning a
-- seat's next turn (its orders run at that turn's start, Civ6Ai_Orders queue),
-- its full movement. Returns moves, maxMoves.
function Civ6Ai_GameCore._AvailableMoves(unit, planning)
  local maxMoves = Civ6Ai_GameCore._Call(unit, "GetMaxMoves") or 0
  if planning then
    return maxMoves, maxMoves
  end
  return Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0, maxMoves
end

-- Cost of the step and its kind ("land", "sea", "embark", "disembark").
function Civ6Ai_GameCore.StepCost(unit, domain, fromPlot, toPlot, maxMoves)
  local toWater = Civ6Ai_GameCore._Call(toPlot, "IsWater") == true
  local embarked = Civ6Ai_GameCore._Call(unit, "IsEmbarked") == true
  if domain == "DOMAIN_LAND" and toWater and not embarked then
    return math.min(Civ6Ai_GameCore.EMBARK_COST, math.max(maxMoves or 0, 1)), "embark"
  end
  if domain == "DOMAIN_LAND" and embarked and not toWater then
    return math.min(Civ6Ai_GameCore.EMBARK_COST, math.max(maxMoves or 0, 1)), "disembark"
  end
  if toWater then
    return 1, "sea"
  end
  local cost = Civ6Ai_GameCore._PlotEnterCost(toPlot)
  local river = Civ6Ai_GameCore._RiverBetween(fromPlot, toPlot)
  local roadCost, bridges = Civ6Ai_GameCore._RoadStep(fromPlot, toPlot)
  if roadCost ~= nil and (bridges or not river) then
    return math.min(cost, roadCost), "land"
  end
  if river then
    cost = cost + Civ6Ai_GameCore.RIVER_CROSSING_COST
  end
  return cost, "land"
end

-- Adjacent-move legality from the gameplay side, used for every seat's
-- legal_commands and before every move is issued. The UI-side
-- CanStartOperation(MOVE_TO) accepts every neighbour (water included) and the
-- script mover gives up on steps the unit cannot pay for this turn, so check
-- domain, embark rules, impassable terrain, stacking and the step cost.
-- planning: judge the step for the seat's next turn (full movement).
function Civ6Ai_GameCore.CanMoveUnitToForPlayer(playerID, unitNumericId, x, y, planning)
  local _, unit, reason = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return false, reason
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "plot_not_found"
  end
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
  local domain = row ~= nil and row.Domain or "DOMAIN_LAND"
  local water = plot.IsWater ~= nil and plot:IsWater()
  local embark = false
  if domain == "DOMAIN_LAND" and water and Civ6Ai_GameCore._Call(unit, "IsEmbarked") ~= true then
    local why = Civ6Ai_GameCore._EmbarkProblem(playerID, plot)
    if why ~= nil then
      return false, why
    end
    embark = true
  end
  if domain == "DOMAIN_SEA" and not water and not (plot.IsCity ~= nil and plot:IsCity()) then
    return false, "land"
  end
  if (plot.IsImpassable ~= nil and plot:IsImpassable()) or (plot.IsMountain ~= nil and plot:IsMountain()) then
    return false, "impassable"
  end
  local ok, blocked = pcall(function()
    if Units == nil or Units.GetUnitsInPlot == nil then
      return nil
    end
    for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
      if other:GetOwner() ~= playerID then
        return "occupied_foreign"
      end
      local otherRow = GameInfo.Units[other:GetType()]
      if row ~= nil and otherRow ~= nil and otherRow.FormationClass == row.FormationClass then
        return "stack_limit"
      end
    end
    return nil
  end)
  if ok and blocked ~= nil then
    return false, blocked
  end
  local fromX, fromY = unit:GetX(), unit:GetY()
  local adjacent = Civ6Ai_GameCore._IsAdjacent(fromX, fromY, x, y)
  if adjacent == false then
    -- legal_commands only offer neighbours; the engine paths longer orders over
    -- several turns and ends the unit's turn, which is what burned moves.
    return false, "not_adjacent"
  end
  local moves, maxMoves = Civ6Ai_GameCore._AvailableMoves(unit, planning)
  if moves <= 0 then
    return false, "no_moves_left"
  end
  if adjacent == nil then
    return true, ""
  end
  local fromPlot = Map.GetPlot(fromX, fromY)
  local cost, kind = Civ6Ai_GameCore.StepCost(unit, domain, fromPlot, plot, maxMoves)
  if kind == "embark" or kind == "disembark" then
    embark = true
  end
  local full = maxMoves > 0 and moves >= maxMoves
  if cost > moves then
    if Civ6Ai_GameCore.ALLOW_FIRST_STEP_EXCEPTION and full and not embark then
      return true, "first_step:" .. tostring(cost) .. ">" .. tostring(moves)
    end
    return false, "insufficient_moves:" .. tostring(cost) .. ">" .. tostring(moves)
  end
  return true, ""
end

-- Give back movement a failed order took. UnitManager.MoveUnit to a step the
-- unit cannot finish this turn left it in place with 0 moves (P0 T25: the scout
-- and warrior then failed their retries with no_moves_left).
function Civ6Ai_GameCore._RestoreMoves(unit, before)
  local after = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
  if before == nil or after >= before then
    return false
  end
  if UnitManager.ChangeMovesRemaining ~= nil then
    pcall(function() UnitManager.ChangeMovesRemaining(unit, before - after) end)
  end
  local now = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
  if now < before and UnitManager.RestoreMovement ~= nil then
    pcall(function() UnitManager.RestoreMovement(unit) end)
    now = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
    local maxMoves = Civ6Ai_GameCore._Call(unit, "GetMaxMoves") or now
    if now > before and before < maxMoves and UnitManager.ChangeMovesRemaining ~= nil then
      pcall(function() UnitManager.ChangeMovesRemaining(unit, before - now) end)
      now = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or now
    end
  end
  print("CIV6AI|gamecore|restore_moves|unit=" .. tostring(unit:GetID()) .. "|before=" .. tostring(before)
    .. "|after=" .. tostring(after) .. "|now=" .. tostring(now))
  return now >= before
end

-- UnitManager.MoveUnit is reliable for short hops and pathfinds (sometimes) for
-- longer ones; success is judged by whether the unit actually changed plot. The
-- step is checked first (CanMoveUnitToForPlayer) so a move the engine would
-- refuse is never issued, and a move that still makes no progress gets its
-- movement back, so the unit can take its next order or be skipped/fortified.
function Civ6Ai_GameCore.MoveUnitForPlayer(playerID, unitNumericId, x, y)
  local _, unit, reason = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return false, reason
  end
  if Map.GetPlot(x, y) == nil then
    return false, "plot_not_found"
  end
  local fromX, fromY = unit:GetX(), unit:GetY()
  if fromX == x and fromY == y then
    return true, "already_there"
  end
  local canMove, whyNot = Civ6Ai_GameCore.CanMoveUnitToForPlayer(playerID, unitNumericId, x, y)
  if not canMove then
    return false, "illegal_move:" .. tostring(whyNot)
  end
  if UnitManager.MoveUnit == nil then
    return false, "move_unit_unavailable"
  end
  local firstCost = Civ6Ai_GameCore._FirstStepCost(whyNot)
  if firstCost ~= nil then
    return Civ6Ai_GameCore._FirstStep(playerID, unit, x, y, firstCost)
  end
  local before = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining")
  local okMove, err = pcall(function()
    UnitManager.MoveUnit(unit, x, y)
  end)
  local toX, toY = unit:GetX(), unit:GetY()
  if not okMove then
    if toX == fromX and toY == fromY then
      Civ6Ai_GameCore._RestoreMoves(unit, before)
    end
    return false, "move_unit_error:" .. tostring(err)
  end
  if toX == x and toY == y then
    return true, ""
  end
  if toX ~= fromX or toY ~= fromY then
    return true, "partial_move_to_" .. tostring(toX) .. "_" .. tostring(toY)
  end
  Civ6Ai_GameCore._RestoreMoves(unit, before)
  Civ6Ai_GameCore._LogStepRefusal(playerID, unit, x, y, before, "script_move_no_progress")
  return false, "script_move_no_progress"
end

-- Why did the engine refuse a step our check allowed? Logs our price of the
-- step with its parts, the unit's movement, and the engine's
-- own route to the plot (UnitManager.GetMoveToPath: length, and whether its
-- first step is the target).
function Civ6Ai_GameCore._LogStepRefusal(playerID, unit, x, y, before, tag)
  pcall(function()
    local fromPlot = Map.GetPlot(unit:GetX(), unit:GetY())
    local toPlot = Map.GetPlot(x, y)
    local maxMoves = Civ6Ai_GameCore._Call(unit, "GetMaxMoves") or 0
    local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[unit:GetType()] or nil
    local cost, kind = Civ6Ai_GameCore.StepCost(unit, row ~= nil and row.Domain or "DOMAIN_LAND", fromPlot, toPlot, maxMoves)
    local enginePath = "none"
    if UnitManager.GetMoveToPath ~= nil and toPlot ~= nil then
      local okPath, path = pcall(function() return UnitManager.GetMoveToPath(unit, toPlot:GetIndex()) end)
      if okPath and type(path) == "table" then
        local parts = {}
        for i, index in ipairs(path) do
          if i > 4 then break end
          local p = Map.GetPlotByIndex(index)
          parts[#parts + 1] = p ~= nil and (p:GetX() .. "," .. p:GetY()) or tostring(index)
        end
        enginePath = tostring(#path) .. ":" .. table.concat(parts, ";")
      elseif not okPath then
        enginePath = "error"
      end
    end
    print("CIV6AI|gamecore|step_refused|" .. tostring(tag) .. "|player=" .. tostring(playerID) .. "|unit=" .. tostring(unit:GetID())
      .. "|type=" .. tostring(row ~= nil and row.UnitType or unit:GetType())
      .. "|from=" .. unit:GetX() .. "," .. unit:GetY() .. "|to=" .. tostring(x) .. "," .. tostring(y)
      .. "|our_cost=" .. tostring(cost) .. "|kind=" .. tostring(kind)
      .. "|terrain=" .. tostring(Civ6Ai_GameCore._Call(toPlot, "GetTerrainType"))
      .. "|feature=" .. tostring(Civ6Ai_GameCore._Call(toPlot, "GetFeatureType"))
      .. "|hills=" .. tostring(Civ6Ai_GameCore._Call(toPlot, "IsHills"))
      .. "|river=" .. tostring(Civ6Ai_GameCore._RiverBetween(fromPlot, toPlot))
      .. "|route=" .. tostring(Civ6Ai_GameCore._Call(fromPlot, "GetRouteType")) .. ">" .. tostring(Civ6Ai_GameCore._Call(toPlot, "GetRouteType"))
      .. "|cliff=" .. tostring(Civ6Ai_GameCore._Call(fromPlot, "IsCliffCrossingToPlot", toPlot))
      .. "|owner=" .. tostring(Civ6Ai_GameCore._Call(toPlot, "GetOwner"))
      .. "|moves=" .. tostring(before) .. ">" .. tostring(Civ6Ai_GameCore._Call(unit, "GetMovesRemaining")) .. "/" .. tostring(maxMoves)
      .. "|engine_path=" .. enginePath)
  end)
end

-- Step cost from a CanMoveUnitToForPlayer "first_step:<cost>><moves>" reason.
function Civ6Ai_GameCore._FirstStepCost(reason)
  local cost = string.match(tostring(reason or ""), "^first_step:([%d%.]+)>")
  return tonumber(cost)
end

-- A full-movement unit entering a neighbour that costs more than its moves
-- (see ALLOW_FIRST_STEP_EXCEPTION). Route 1: the engine's mover as is.
-- Route 2 (FIRST_STEP_TOPUP): the same mover with the unit's movement raised
-- to the step cost for the call, then the unit's moves are ended. A refused
-- step gets its movement back. Returns ok, reason ("first_step:<route>").
function Civ6Ai_GameCore._FirstStep(playerID, unit, x, y, cost)
  local fromX, fromY = unit:GetX(), unit:GetY()
  local before = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
  local maxMoves = Civ6Ai_GameCore._Call(unit, "GetMaxMoves") or 0
  local function moved()
    return unit:GetX() ~= fromX or unit:GetY() ~= fromY
  end
  local function log(route, result)
    print("CIV6AI|gamecore|first_step|player=" .. tostring(playerID) .. "|unit=" .. tostring(unit:GetID())
      .. "|from=" .. fromX .. "," .. fromY .. "|to=" .. tostring(x) .. "," .. tostring(y) .. "|cost=" .. tostring(cost)
      .. "|moves=" .. tostring(before) .. "/" .. tostring(maxMoves) .. "|route=" .. route .. "|result=" .. result
      .. "|at=" .. unit:GetX() .. "," .. unit:GetY() .. "|left=" .. tostring(Civ6Ai_GameCore._Call(unit, "GetMovesRemaining")))
  end
  local okMove, err = pcall(function() UnitManager.MoveUnit(unit, x, y) end)
  if moved() then
    log("move_unit", "moved")
    if (Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0) > 0 then
      pcall(function() UnitManager.FinishMoves(unit) end)
    end
    return true, "first_step:move_unit"
  end
  log("move_unit", okMove and "refused" or ("error:" .. tostring(err)))
  Civ6Ai_GameCore._RestoreMoves(unit, before)
  Civ6Ai_GameCore._LogStepRefusal(playerID, unit, x, y, before, "first_step")
  if not Civ6Ai_GameCore.FIRST_STEP_TOPUP or UnitManager.ChangeMovesRemaining == nil then
    return false, "first_step_refused"
  end
  local now = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
  pcall(function() UnitManager.ChangeMovesRemaining(unit, cost - now) end)
  okMove, err = pcall(function() UnitManager.MoveUnit(unit, x, y) end)
  if moved() then
    pcall(function() UnitManager.FinishMoves(unit) end)
    log("topup", "moved")
    return true, "first_step:topup"
  end
  log("topup", okMove and "refused" or ("error:" .. tostring(err)))
  local after = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining") or 0
  if after ~= before then
    pcall(function() UnitManager.ChangeMovesRemaining(unit, before - after) end)
  end
  return false, "first_step_refused"
end

-- A move to a plot more than one tile away. UnitManager.MoveUnit only moves a
-- unit when it can reach the target this turn; a farther target spends the
-- unit's moves and leaves it in place (MP test T2: 36,9 to 33,9 with 2 moves).
-- So ask the engine for its own route (UnitManager.GetMoveToPath, as the
-- Pirates scenario does) and walk it one neighbour at a time, each step checked
-- like a normal move, stopping when the next step cannot be paid this turn.
function Civ6Ai_GameCore.MoveUnitAlongPathForPlayer(playerID, unitNumericId, x, y)
  local _, unit, reason = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return false, reason
  end
  local target = Map.GetPlot(x, y)
  if target == nil then
    return false, "plot_not_found"
  end
  local fromX, fromY = unit:GetX(), unit:GetY()
  if fromX == x and fromY == y then
    return true, "already_there"
  end
  if UnitManager.GetMoveToPath == nil then
    return false, "path_unavailable"
  end
  if unit:GetMovesRemaining() <= 0 then
    return false, "no_moves_left"
  end
  local okPath, path = pcall(function() return UnitManager.GetMoveToPath(unit, target:GetIndex()) end)
  if not okPath or type(path) ~= "table" or #path == 0 then
    return false, "no_path"
  end
  local steps, stop = 0, "arrived"
  for _, index in ipairs(path) do
    local plot = Map.GetPlotByIndex(index)
    if plot == nil then
      stop = "bad_path_plot"
      break
    end
    local px, py = plot:GetX(), plot:GetY()
    if px ~= unit:GetX() or py ~= unit:GetY() then
      local canMove, whyNot = Civ6Ai_GameCore.CanMoveUnitToForPlayer(playerID, unitNumericId, px, py)
      if not canMove then
        stop = tostring(whyNot)
        break
      end
      local firstCost = Civ6Ai_GameCore._FirstStepCost(whyNot)
      if firstCost ~= nil then
        local okFirst, why = Civ6Ai_GameCore._FirstStep(playerID, unit, px, py, firstCost)
        if not okFirst then
          stop = tostring(why)
          break
        end
        steps = steps + 1
      else
        local before = Civ6Ai_GameCore._Call(unit, "GetMovesRemaining")
        local bx, by = unit:GetX(), unit:GetY()
        pcall(function() UnitManager.MoveUnit(unit, px, py) end)
        if unit:GetX() == bx and unit:GetY() == by then
          Civ6Ai_GameCore._RestoreMoves(unit, before)
          Civ6Ai_GameCore._LogStepRefusal(playerID, unit, px, py, before, "path_step")
          stop = "step_refused"
          break
        end
        steps = steps + 1
      end
    end
  end
  local note = "path:" .. fromX .. "," .. fromY .. ">" .. unit:GetX() .. "," .. unit:GetY()
    .. ":steps=" .. steps .. ":len=" .. #path .. ":stop=" .. stop
  if unit:GetX() == x and unit:GetY() == y then
    return true, note
  end
  if steps > 0 then
    return true, "partial_" .. note
  end
  return false, note
end

function Civ6Ai_GameCore.FinishMovesForPlayer(playerID, unitNumericId)
  local _, unit, reason = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return false, reason
  end
  local ok = pcall(function()
    UnitManager.FinishMoves(unit)
  end)
  if not ok then
    return false, "finish_moves_error"
  end
  return true, ""
end

function Civ6Ai_GameCore.SetResearchForPlayer(playerID, techIndex)
  local player = Players[playerID]
  if player == nil or player.GetTechs == nil then
    return false, "no_player"
  end
  local techs = player:GetTechs()
  if techs == nil or techs.SetResearchingTech == nil then
    return false, "set_research_unavailable"
  end
  if techs.HasTech ~= nil and techs:HasTech(techIndex) then
    -- Idempotent: already researched is not a failure for queued orders.
    return true, "tech_already_known"
  end
  local ok = pcall(function()
    techs:SetResearchingTech(techIndex)
  end)
  if not ok then
    return false, "set_research_error"
  end
  return true, ""
end

function Civ6Ai_GameCore.SetCivicForPlayer(playerID, civicIndex)
  local player = Players[playerID]
  if player == nil or player.GetCulture == nil then
    return false, "no_player"
  end
  local culture = player:GetCulture()
  if culture == nil or culture.SetProgressingCivic == nil then
    return false, "set_civic_unavailable"
  end
  if culture.HasCivic ~= nil and culture:HasCivic(civicIndex) then
    return true, "civic_already_known"
  end
  local ok = pcall(function()
    culture:SetProgressingCivic(civicIndex)
  end)
  if not ok then
    return false, "set_civic_error"
  end
  return true, ""
end

-- Movement for snapshots. The interface's unit cache lags at turn start (the
-- local seat reads 0 moves at LocalPlayerTurnBegin). planning: the seat's
-- orders run at its next turn start (Civ6Ai_Orders queue), with full movement.
function Civ6Ai_GameCore.UnitMovesForPlayer(playerID, unitNumericId, planning)
  local _, unit = Civ6Ai_GameCore._FindUnit(playerID, unitNumericId)
  if unit == nil then
    return nil
  end
  return (Civ6Ai_GameCore._AvailableMoves(unit, planning))
end

function Civ6Ai_InitializeGameCore()
  Civ6Ai_GameCore = Civ6Ai_GameCore or {}
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  ExposedMembers.Civ6Ai.ResolvePlayerUnits = Civ6Ai_GameCore.ResolvePlayerUnits
  ExposedMembers.Civ6Ai.FoundCityForPlayer = Civ6Ai_GameCore.FoundCityForPlayer
  ExposedMembers.Civ6Ai.CanFoundCityForPlayer = Civ6Ai_GameCore.CanFoundCityForPlayer
  ExposedMembers.Civ6Ai.CanMoveUnitToForPlayer = Civ6Ai_GameCore.CanMoveUnitToForPlayer
  ExposedMembers.Civ6Ai.MoveUnitForPlayer = Civ6Ai_GameCore.MoveUnitForPlayer
  ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = Civ6Ai_GameCore.MoveUnitAlongPathForPlayer
  ExposedMembers.Civ6Ai.SetResearchForPlayer = Civ6Ai_GameCore.SetResearchForPlayer
  ExposedMembers.Civ6Ai.SetCivicForPlayer = Civ6Ai_GameCore.SetCivicForPlayer
  ExposedMembers.Civ6Ai.FinishMovesForPlayer = Civ6Ai_GameCore.FinishMovesForPlayer
  ExposedMembers.Civ6Ai.UnitMovesForPlayer = Civ6Ai_GameCore.UnitMovesForPlayer
  ExposedMembers.Civ6Ai.WriteFile = Civ6Ai_GameCore.WriteFile
  ExposedMembers.Civ6Ai.ReadFile = Civ6Ai_GameCore.ReadFile
  ExposedMembers.Civ6Ai.AppendFile = Civ6Ai_GameCore.AppendFile
  local hasIo = io ~= nil and io.open ~= nil
  local hasExec = os ~= nil and os.execute ~= nil
  local hasGetenv = os ~= nil and os.getenv ~= nil
  ExposedMembers.Civ6Ai.GameCoreIo = hasIo
  print("CIV6AI|gamecore|ready|io=" .. tostring(hasIo) .. "|os_exec=" .. tostring(hasExec) .. "|getenv=" .. tostring(hasGetenv))
end

Civ6Ai_InitializeGameCore()
