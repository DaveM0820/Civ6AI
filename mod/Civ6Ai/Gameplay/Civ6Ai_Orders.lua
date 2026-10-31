-- Civ6Ai synced order channel (gameplay side). Runs on every PC in lockstep.
--
-- In a network game the host's model orders for AI seats must change the game
-- on every PC, or the game desyncs. The host's interface script sends each
-- order with
--   UI.RequestPlayerOperation(localPlayer, PlayerOperations.EXECUTE_SCRIPT,
--                             { OnStart = "Civ6AiOrder", K = kind, ... })
-- and the engine raises GameEvents.Civ6AiOrder(sender, params) at the same
-- simulation point on every PC. Everything below is deterministic: no
-- Game.GetLocalPlayer, no UI, no files, no clocks, no randomness. Params are
-- integers only.
--
-- A model decision for an AI seat arrives as one batch (B = batch id, J =
-- index, N = count, T = the turn the orders are for). The complete batch is
-- the seat's order queue for turn T, kept in synced game properties (saved
-- with the game). When the seat's turn T starts, every PC plays the queue
-- with the seat's full movement, with retry passes (a move blocked by another
-- of the seat's own units is retried after the others moved), then ends the
-- turn of the seat's units the model left in place. A seat with no queue is
-- played by the game's own AI. The same path runs in single player.
--
-- Local-only bookkeeping (results for the host's apply log, checksums for the
-- sync reports) goes into ExposedMembers.Civ6Ai, which each PC keeps for itself
-- and never feeds back into game state.
Civ6Ai_Orders = Civ6Ai_Orders or {}
Civ6Ai_Orders.VERSION = 2
Civ6Ai_Orders.TAG = "CIV6AI|orders|"

-- Order kinds (param K).
Civ6Ai_Orders.K = {
  MOVE = 1,
  RESEARCH = 2,
  CIVIC = 3,
  FOUND = 4,
  SKIP = 5,
  FORTIFY = 6,
  ATTACK = 7,
  PRIORITY = 9,
  GOVERNMENT = 10,
  POLICY = 11,
  PANTHEON = 12,
  RELIGION = 13,
  GP_RECRUIT = 14,
  GP_PATRONIZE = 15,
  GOVERNOR = 16,
  WAR = 17,
  DEAL = 33,
  ENVOY = 34,
  BUY = 19,
  BUY_TILE = 20,
  IMPROVE = 21,
  PILLAGE = 22,
  FINISH_SEAT = 23,
  TRADE = 24,
  EXPLORE = 25,
  ACTIVATE_GP = 26,
  UPGRADE = 27,
  PROMOTE = 28,
  FORMATION = 29,
  REPORT = 30,
  CITY_STRIKE = 31,
  FORT = 32,
  SPREAD = 35,
  PING = 40,
  TEST_MODE = 49,
  TEST_INTROSPECT = 50,
  TEST_SPAWN_ENEMY = 51,
  TEST_MELEE_MOVE = 52,
  TEST_SCRIPTED_COMBAT = 53,
  TEST_SCRIPTED_PRODUCTION = 54,
  TEST_IMPROVEMENT = 55,
  TEST_EXPERIENCE = 56,
  TEST_FAR_MOVE = 57,
  TEST_COMBAT_PROBE = 58,
  TEST_DAMAGE_CHECK = 59,
  TEST_RESOLVED_ATTACK = 60,
  TEST_API_SURVEY = 61,
  TEST_PRODUCTION_STEER = 62,
  TEST_FORCE_BUILD = 63,
  TEST_PRIORITY = 64,
  HINT = 36,
}
-- Kinds a model decision is made of (unit, research, priority, governance).
Civ6Ai_Orders.DECISION_KINDS = {
  [1] = true, [2] = true, [3] = true, [4] = true, [5] = true, [6] = true, [7] = true, [9] = true,
  [10] = true, [11] = true, [12] = true, [13] = true, [14] = true, [15] = true, [16] = true,
  [17] = true, [18] = true, [19] = true, [20] = true, [21] = true, [22] = true,
  [24] = true, [25] = true, [26] = true, [27] = true, [28] = true, [29] = true, [31] = true, [32] = true, [33] = true, [34] = true,
  [35] = true, [36] = true,
}
-- Intent on a MOVE (param A). N is the batch count on the wire, so intent is A.
Civ6Ai_Orders.INTENT = { MOVE = 0, FOUND = 1, IMPROVE = 2, RELIGION = 3, TRADE = 4 }
Civ6Ai_Orders.GOAL_MAX_AGE = 10
-- Order fields kept in the queue (P is the seat itself). A missing field is
-- stored as -1, which every kind that reads the field treats as "none".
-- G = persistent goal, A = arrival intent, I2/I3 = research/civic fallbacks,
-- D = snapshot/decision turn.
Civ6Ai_Orders.QUEUE_FIELDS = { "K", "U", "X", "Y", "I", "V", "W", "S", "G", "A", "I2", "I3", "D" }
Civ6Ai_Orders.MAX_PASSES = 4
Civ6Ai_Orders._batches = Civ6Ai_Orders._batches or {}

local function log(s)
  print(Civ6Ai_Orders.TAG .. s)
end

-- Civ6 userdata __index throws "function expected instead of nil" for a method
-- the object does not have. The lookup itself has to be inside pcall; a bare
-- obj[name] aborts the turn before the nil check can run.
local function call(obj, name, ...)
  if obj == nil then
    return nil
  end
  local okGet, fn = pcall(function() return obj[name] end)
  if not okGet or type(fn) ~= "function" then
    return nil
  end
  local ok, v = pcall(fn, obj, ...)
  if ok then
    return v
  end
  return nil
end

local function num(v)
  return tonumber(v)
end

-- Keys of a table in a fixed order (numbers, then strings), so synced code
-- never depends on pairs() order, which can differ between machines.
local function sortedKeys(t)
  local keys = {}
  for k in pairs(t or {}) do
    keys[#keys + 1] = k
  end
  table.sort(keys, function(a, b)
    local ta, tb = type(a), type(b)
    if ta ~= tb then
      return ta < tb
    end
    if ta == "number" or ta == "string" then
      return a < b
    end
    return tostring(a) < tostring(b)
  end)
  return keys
end
Civ6Ai_Orders._SortedKeys = sortedKeys

local function sortedMembers(coll)
  local list = {}
  if coll ~= nil and coll.Members ~= nil then
    for _, v in coll:Members() do
      list[#list + 1] = v
    end
  end
  table.sort(list, function(a, b) return a:GetID() < b:GetID() end)
  return list
end

local function trimErr(err)
  local text = tostring(err or "")
  if #text > 240 then
    text = string.sub(text, 1, 240)
  end
  return text
end

-- City centre district. Gameplay cities have no GetDistrictID (indexing it throws
-- "function expected instead of nil"). call() swallows that lookup.
-- The centre is the district on the city plot, else a CITY_CENTER in the city's
-- or the player's district list. Every lookup goes through call/pcall.
function Civ6Ai_Orders._DistrictById(owner, city, id)
  id = num(id)
  if id == nil or id < 0 then
    return nil
  end
  local lists = { call(Players ~= nil and Players[owner] or nil, "GetDistricts"), call(city, "GetDistricts") }
  for _, list in ipairs(lists) do
    local found = call(list, "FindID", id) or call(list, "GetDistrict", id)
    if found ~= nil then
      return found
    end
  end
  return nil
end

function Civ6Ai_Orders._MatchCityCenter(list, x, y)
  local ok, found = pcall(function()
    for _, d in ipairs(sortedMembers(list)) do
      if call(d, "GetX") == x and call(d, "GetY") == y then
        return d
      end
      local row = GameInfo ~= nil and GameInfo.Districts ~= nil and GameInfo.Districts[call(d, "GetType")] or nil
      if row ~= nil and row.DistrictType == "DISTRICT_CITY_CENTER" then
        return d
      end
    end
    return nil
  end)
  if ok then
    return found
  end
  return nil
end

function Civ6Ai_Orders._CityCenterDistrict(city)
  if city == nil then
    return nil
  end
  local owner = call(city, "GetOwner")
  local x, y = call(city, "GetX"), call(city, "GetY")
  local plot = nil
  if x ~= nil and y ~= nil and Map ~= nil and Map.GetPlot ~= nil then
    local okPlot, p = pcall(Map.GetPlot, x, y)
    if okPlot then
      plot = p
    end
  end
  local district = Civ6Ai_Orders._DistrictById(owner, city, call(plot, "GetDistrictID"))
  if district ~= nil then
    return district
  end
  district = Civ6Ai_Orders._DistrictById(owner, city, call(city, "GetDistrictID"))
  if district ~= nil then
    return district
  end
  district = Civ6Ai_Orders._MatchCityCenter(call(city, "GetDistricts"), x, y)
  if district ~= nil then
    return district
  end
  return Civ6Ai_Orders._MatchCityCenter(call(Players ~= nil and Players[owner] or nil, "GetDistricts"), x, y)
end

function Civ6Ai_Orders._Shared()
  if ExposedMembers == nil then
    return {}
  end
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  return ExposedMembers.Civ6Ai
end

-- A GameCore route, looked up when called (the GameCore script may load after
-- this one). Returns ok, reason.
function Civ6Ai_Orders._Route(name, ...)
  local fn = Civ6Ai_Orders._Shared()[name]
  if fn == nil then
    return false, "gamecore_unavailable:" .. tostring(name)
  end
  local args = { ... }
  local unpackFn = unpack or table.unpack
  local okCall, ok, reason = pcall(function()
    return fn(unpackFn(args))
  end)
  if not okCall then
    return false, "gamecore_error"
  end
  return ok == true, reason or ""
end

-- ---------------------------------------------------------------------------
-- Sender rules
-- ---------------------------------------------------------------------------
-- Only humans send. A human may order only their own units; AI seats may be
-- ordered only by the controller, the human whose order first reached an AI
-- seat (the host, the only PC that runs the model). The claim is a synced game
-- property, so every PC accepts and refuses the same orders. Returns nil when
-- the order is allowed, else the reason.
function Civ6Ai_Orders._Controller()
  return num(Game:GetProperty("CIV6AI_CONTROLLER"))
end

function Civ6Ai_Orders._Authorize(sender, owner)
  local s = Players[sender]
  if s == nil or not call(s, "IsHuman") then
    return "sender_not_human"
  end
  local p = Players[owner]
  if p == nil then
    return "no_player"
  end
  if call(p, "IsHuman") then
    if owner ~= sender then
      return "not_owner"
    end
    return nil
  end
  local controller = Civ6Ai_Orders._Controller()
  if controller == nil then
    Game:SetProperty("CIV6AI_CONTROLLER", sender)
  elseif controller ~= sender then
    return "not_controller"
  end
  return nil
end

-- ---------------------------------------------------------------------------
-- Commands
-- ---------------------------------------------------------------------------
function Civ6Ai_Orders._Unit(owner, unitId)
  local p = Players[owner]
  local units = p ~= nil and call(p, "GetUnits") or nil
  if units == nil then
    return nil
  end
  return call(units, "FindID", unitId)
end

function Civ6Ai_Orders._GoalKey(owner, unitId, field)
  return "CIV6AI_GOAL_" .. tostring(owner) .. "_" .. tostring(unitId) .. "_" .. field
end

function Civ6Ai_Orders._HoldKey(owner, unitId)
  return "CIV6AI_HOLD_" .. tostring(owner) .. "_" .. tostring(unitId)
end

function Civ6Ai_Orders.ClearHold(owner, unitId)
  if owner ~= nil and unitId ~= nil and num(Game:GetProperty(Civ6Ai_Orders._HoldKey(owner, unitId))) ~= nil then
    Game:SetProperty(Civ6Ai_Orders._HoldKey(owner, unitId), nil)
  end
end

-- An enemy (at war) or barbarian unit on a neighbouring tile wakes a fortified unit.
function Civ6Ai_Orders._EnemyAdjacent(owner, unit)
  if Map == nil or Map.GetAdjacentPlot == nil or DirectionTypes == nil or Units == nil then
    return false
  end
  for d = 0, (DirectionTypes.NUM_DIRECTION_TYPES or 6) - 1 do
    local plot = Map.GetAdjacentPlot(unit:GetX(), unit:GetY(), d)
    if plot ~= nil then
      for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
        local o = other:GetOwner()
        if o ~= owner and (Civ6Ai_Orders._AtWar(owner, o) or call(Players[o], "IsBarbarian") == true) then
          return true
        end
      end
    end
  end
  return false
end

-- Turn start: fortified units of this seat stay put (moves finished) unless an
-- enemy is adjacent, which wakes them so the seat sees them again.
function Civ6Ai_Orders.HoldFortified(owner)
  local p = Players[owner]
  if p == nil then
    return 0
  end
  local held = 0
  for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
    local key = Civ6Ai_Orders._HoldKey(owner, u:GetID())
    if num(Game:GetProperty(key)) ~= nil then
      if Civ6Ai_Orders._EnemyAdjacent(owner, u) then
        Game:SetProperty(key, nil)
        log("hold_wake|player=" .. tostring(owner) .. "|unit=" .. tostring(u:GetID()))
      elseif (call(u, "GetMovesRemaining") or 0) > 0 then
        pcall(UnitManager.FinishMoves, u)
        held = held + 1
      end
    end
  end
  if held > 0 then
    log("hold_fortified|player=" .. tostring(owner) .. "|units=" .. held)
  end
  return held
end

function Civ6Ai_Orders._ClearGoal(owner, unitId)
  if owner == nil or unitId == nil then
    return
  end
  for _, f in ipairs({ "X", "Y", "A", "T", "I", "V", "W" }) do
    Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, f), -1)
  end
end

function Civ6Ai_Orders._ReadGoal(owner, unitId)
  local x = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "X")))
  if x == nil or x < 0 then
    return nil
  end
  local y = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "Y")))
  if y == nil or y < 0 then
    return nil
  end
  return {
    x = x,
    y = y,
    intent = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "A"))) or 0,
    setTurn = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "T"))) or 0,
    I = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "I"))),
    V = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "V"))),
    W = num(Game:GetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "W"))),
  }
end

function Civ6Ai_Orders._StoreGoal(owner, unitId, x, y, intent, extra)
  extra = extra or {}
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "X"), x)
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "Y"), y)
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "A"), intent or 0)
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "T"), Game.GetCurrentGameTurn())
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "I"), extra.I or -1)
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "V"), extra.V or -1)
  Game:SetProperty(Civ6Ai_Orders._GoalKey(owner, unitId, "W"), extra.W or -1)
  log("goal_set|player=" .. tostring(owner) .. "|unit=" .. tostring(unitId)
    .. "|xy=" .. tostring(x) .. "," .. tostring(y) .. "|intent=" .. tostring(intent or 0))
end

function Civ6Ai_Orders._IsSettler(unit)
  local row = GameInfo.Units[unit:GetType()]
  return row ~= nil and (row.FoundCity == true or row.FoundCity == 1)
end

function Civ6Ai_Orders._PlotEnterOk(owner, unit, x, y)
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false, "plot_not_found"
  end
  -- A mountain destination must say impassable, not the vaguer no_path that
  -- pathfinding returns when it refuses to route onto the peak.
  if (plot.IsImpassable ~= nil and plot:IsImpassable() == true)
      or (plot.IsMountain ~= nil and plot:IsMountain() == true) then
    return false, "impassable"
  end
  return true, ""
end

-- Builders improve owned land. A destination outside this seat's borders
-- (including unowned tiles) is refused before pathing, with a plain reason.
function Civ6Ai_Orders._BuilderOutsideBorders(unit, x, y)
  local info = GameInfo.Units[unit:GetType()]
  if info == nil or (num(info.BuildCharges) or 0) <= 0 then
    return false
  end
  local plot = Map.GetPlot(x, y)
  if plot == nil then
    return false
  end
  local tileOwner = call(plot, "GetOwner")
  if tileOwner == nil then
    return false
  end
  return tileOwner ~= unit:GetOwner()
end

function Civ6Ai_Orders._SameDomain(unit, plot)
  local row = GameInfo.Units[unit:GetType()]
  local domain = row ~= nil and row.Domain or "DOMAIN_LAND"
  local water = call(plot, "IsWater") == true
  if domain == "DOMAIN_SEA" then
    return water or call(plot, "IsCity") == true
  end
  return not water
end

function Civ6Ai_Orders._SameLandmass(a, b)
  if a == nil or b == nil then
    return false
  end
  local aid = call(a, "GetAreaID") or call(a, "GetContinentType")
  local bid = call(b, "GetAreaID") or call(b, "GetContinentType")
  if aid == nil or bid == nil then
    return true
  end
  return aid == bid
end

-- Neighbours in a stable (x,y) order. Uses GetPlotDistance so odd-r hexes work.
function Civ6Ai_Orders._Ring1(x, y)
  local list = {}
  for dx = -1, 1 do
    for dy = -1, 1 do
      if not (dx == 0 and dy == 0) then
        local px, py = x + dx, y + dy
        local d = Map.GetPlotDistance(x, y, px, py)
        if d == 1 then
          list[#list + 1] = { x = px, y = py }
        end
      end
    end
  end
  table.sort(list, function(a, b)
    if a.x ~= b.x then
      return a.x < b.x
    end
    return a.y < b.y
  end)
  return list
end

function Civ6Ai_Orders._OccupiedReason(reason)
  local text = tostring(reason or "")
  return string.find(text, "occupied", 1, true) ~= nil or string.find(text, "stack_limit", 1, true) ~= nil
end

function Civ6Ai_Orders._RetargetPlot(owner, unit, x, y)
  local origin = Map.GetPlot(unit:GetX(), unit:GetY())
  local candidates = Civ6Ai_Orders._Ring1(x, y)
  for _, c in ipairs(candidates) do
    local plot = Map.GetPlot(c.x, c.y)
    if plot ~= nil and not (c.x == unit:GetX() and c.y == unit:GetY())
        and Civ6Ai_Orders._SameDomain(unit, plot)
        and Civ6Ai_Orders._SameLandmass(origin, plot) then
      local okEnter, whyEnter = Civ6Ai_Orders._PlotEnterOk(owner, unit, c.x, c.y)
      if okEnter then
        local skip = false
        local can, why = Civ6Ai_Orders._Route("CanMoveUnitToForPlayer", owner, unit:GetID(), c.x, c.y)
        if not can then
          local w = tostring(why)
          if w == "impassable" or w == "land" or w == "occupied_foreign" or w == "stack_limit"
              or string.find(w, "illegal", 1, true) then
            skip = true
          end
        end
        if not skip then
          local occupied = false
          if Units ~= nil and Units.GetUnitsInPlot ~= nil then
            for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
              if other:GetID() ~= unit:GetID() then
                occupied = true
                break
              end
            end
          end
          if not occupied then
            return c.x, c.y
          end
        end
      end
    end
  end
  return nil
end

function Civ6Ai_Orders._MoveOnce(owner, unitId, x, y)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "stale_unit_id"
  end
  local fromX, fromY = unit:GetX(), unit:GetY()
  local dist = Map.GetPlotDistance(fromX, fromY, x, y)
  local ok, reason
  if dist > 1 then
    ok, reason = Civ6Ai_Orders._Route("MoveUnitAlongPathForPlayer", owner, unitId, x, y)
  else
    ok, reason = Civ6Ai_Orders._Route("MoveUnitForPlayer", owner, unitId, x, y)
  end
  local now = Civ6Ai_Orders._Unit(owner, unitId)
  if ok and now ~= nil then
    local ax, ay = now:GetX(), now:GetY()
    -- A reported success that leaves the unit put is not a move. already_there
    -- (start equals the target) stays a success.
    if ax == fromX and ay == fromY and (fromX ~= x or fromY ~= y) then
      return false, "move_not_applied:" .. tostring(fromX) .. "," .. tostring(fromY) .. ">" .. tostring(ax) .. "," .. tostring(ay)
    end
    if reason == nil or reason == "" then
      reason = "moved:" .. tostring(ax) .. "," .. tostring(ay)
    end
  end
  return ok, reason
end

-- One passable step from the unit toward x,y. Used when the destination
-- itself is a mountain, water, or has no route. Does not list tiles.
function Civ6Ai_Orders._StepToward(owner, unit, x, y)
  if unit == nil or Map == nil or Map.GetPlotDistance == nil then
    return nil
  end
  local ux, uy = unit:GetX(), unit:GetY()
  local here = Map.GetPlotDistance(ux, uy, x, y)
  if here == nil or here <= 0 then
    return nil
  end
  local bestX, bestY, bestD, bestCross = nil, nil, here, nil
  local function cross(px, py)
    return math.abs((px - ux) * (y - uy) - (py - uy) * (x - ux))
  end
  for _, step in ipairs(Civ6Ai_Orders._Ring1(ux, uy)) do
    local plot = Map.GetPlot(step.x, step.y)
    if plot ~= nil and Civ6Ai_Orders._SameDomain(unit, plot) then
      local okEnter = Civ6Ai_Orders._PlotEnterOk(owner, unit, step.x, step.y)
      if okEnter then
        local dist = Map.GetPlotDistance(step.x, step.y, x, y)
        local stepCross = cross(step.x, step.y)
        local closer = dist ~= nil and dist < bestD
        local straighter = bestX ~= nil and dist ~= nil and dist == bestD and stepCross < bestCross
        if closer or straighter then
          local can = true
          local checked, why = Civ6Ai_Orders._Route("CanMoveUnitToForPlayer", owner, unit:GetID(), step.x, step.y)
          if checked == false then
            local w = tostring(why or "")
            if w == "impassable" or w == "land" or w == "water" or w == "occupied_foreign"
                or w == "stack_limit" or string.find(w, "illegal", 1, true) then
              can = false
            end
          end
          if can then
            bestX, bestY, bestD, bestCross = step.x, step.y, dist, stepCross
          end
        end
      end
    end
  end
  return bestX, bestY
end

function Civ6Ai_Orders._MoveWithRetarget(owner, unit, x, y)
  local okEnter, whyEnter = Civ6Ai_Orders._PlotEnterOk(owner, unit, x, y)
  if not okEnter then
    return false, whyEnter
  end
  return Civ6Ai_Orders._MoveOnce(owner, unit:GetID(), x, y)
end

function Civ6Ai_Orders._ArrivalAction(owner, unit, intent, extra, sender)
  extra = extra or {}
  if intent == Civ6Ai_Orders.INTENT.FOUND then
    -- No found-on-arrival: the settler arrives; FoundCity is its own order.
    return true, "arrived"
  elseif intent == Civ6Ai_Orders.INTENT.RELIGION then
    -- Belief indices live in I/V/W. X/Y on a MOVE are the plot, never beliefs.
    return Civ6Ai_Orders.Gov.FoundReligion(owner, extra.I, unit:GetID(), extra.V, extra.W)
  elseif intent == Civ6Ai_Orders.INTENT.TRADE then
    return Civ6Ai_Orders.Gov.MakeTradeRoute(owner, unit:GetID(), extra.I)
  elseif intent == Civ6Ai_Orders.INTENT.IMPROVE and extra.I ~= nil and extra.I >= 0 then
    return Civ6Ai_Orders.Gov.BuildImprovement(owner, unit:GetID(), extra.I)
  end
  return true, "arrived"
end

-- A foreign unit or city on the destination. War is checked by the attack.
function Civ6Ai_Orders._EnemyOnPlot(owner, x, y)
  local city = Cities ~= nil and Cities.GetCityInPlot ~= nil and Cities.GetCityInPlot(x, y) or nil
  if city ~= nil and city:GetOwner() ~= owner then
    return "city"
  end
  if Civ6Ai_Orders._Defender(x, y, owner) ~= nil then
    return "unit"
  end
  return nil
end

-- Melee and anti-cavalry have Combat. Ranged, siege, and naval ranged have a range.
function Civ6Ai_Orders._CanFight(unit)
  if Civ6Ai_Orders._IsRanged(unit) then
    return true
  end
  local row = GameInfo ~= nil and GameInfo.Units[unit:GetType()] or nil
  return row ~= nil and (num(row.Combat) or 0) > 0
end

function Civ6Ai_Orders._AttackReach(unit)
  if Civ6Ai_Orders._IsRanged(unit) then
    return call(unit, "GetRange") or num(GameInfo.Units[unit:GetType()].Range) or 1
  end
  return 1
end

function Civ6Ai_Orders._InAttackRange(unit, x, y)
  if unit == nil or x == nil or y == nil or Map == nil or Map.GetPlotDistance == nil then
    return false
  end
  local dist = Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y)
  if Civ6Ai_Orders._IsRanged(unit) then
    return dist >= 1 and dist <= Civ6Ai_Orders._AttackReach(unit)
  end
  return dist == 1
end

-- The enterable tile in attack range of tx,ty that is closest to the unit.
-- The enemy tile itself is the attack, not a step of the path.
function Civ6Ai_Orders._ApproachTile(unit, tx, ty)
  local reach = Civ6Ai_Orders._AttackReach(unit)
  local ranged = Civ6Ai_Orders._IsRanged(unit)
  local owner = unit:GetOwner()
  local ux, uy = unit:GetX(), unit:GetY()
  local best, bestD = nil, nil
  for dx = -reach, reach do
    for dy = -reach, reach do
      local x, y = tx + dx, ty + dy
      if not (x == tx and y == ty) then
        local dist = Map.GetPlotDistance(tx, ty, x, y)
        local inReach = (ranged and dist >= 1 and dist <= reach) or ((not ranged) and dist == 1)
        if inReach then
          local plot = Map.GetPlot(x, y)
          if plot ~= nil and Civ6Ai_Orders._SameDomain(unit, plot) then
            local okEnter = Civ6Ai_Orders._PlotEnterOk(owner, unit, x, y)
            if okEnter and Civ6Ai_Orders._EnemyOnPlot(owner, x, y) == nil then
              local occupied = false
              if Units ~= nil and Units.GetUnitsInPlot ~= nil then
                for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
                  if other:GetID() ~= unit:GetID() then
                    occupied = true
                    break
                  end
                end
              end
              if not occupied then
                local d = Map.GetPlotDistance(ux, uy, x, y)
                if best == nil or d < bestD or (d == bestD and (x < best.x or (x == best.x and y < best.y))) then
                  best, bestD = { x = x, y = y }, d
                end
              end
            end
          end
        end
      end
    end
  end
  return best
end

-- MoveTo onto an enemy tile attacks when this unit can fight it this turn.
-- Already in reach: attack from here. Out of reach: path to the nearest tile
-- in reach, then attack if a move is left. nil means the tile has no enemy.
function Civ6Ai_Orders._MoveAsAttack(unit, x, y)
  if Civ6Ai_Orders._EnemyOnPlot(unit:GetOwner(), x, y) == nil then
    return nil
  end
  if not Civ6Ai_Orders._CanFight(unit) then
    return false, "enemy_on_tile: this unit cannot attack; pick a different tile"
  end
  if Civ6Ai_Orders._InAttackRange(unit, x, y) then
    local ok, why = Civ6Ai_Orders._ResolveAttack(unit, x, y)
    if ok then
      return true, "attack_instead:" .. tostring(why)
    end
    return false, "enemy_on_tile:" .. tostring(why)
  end
  local tile = Civ6Ai_Orders._ApproachTile(unit, x, y)
  if tile == nil then
    return false, "enemy_on_tile:no_approach"
  end
  local owner = unit:GetOwner()
  local startX, startY = unit:GetX(), unit:GetY()
  if tile.x == startX and tile.y == startY then
    return false, "enemy_on_tile:out_of_range:" .. tostring(Map.GetPlotDistance(startX, startY, x, y))
  end
  local okMove, whyMove = Civ6Ai_Orders._MoveOnce(owner, unit:GetID(), tile.x, tile.y)
  local movedUnit = Civ6Ai_Orders._Unit(owner, unit:GetID())
  if movedUnit ~= nil then
    unit = movedUnit
  end
  local moved = unit:GetX() ~= startX or unit:GetY() ~= startY
  local here = tostring(unit:GetX()) .. "," .. tostring(unit:GetY())
  local attacksLeft = call(unit, "GetAttacksRemaining")
  if moved and Civ6Ai_Orders._InAttackRange(unit, x, y) and (call(unit, "GetMovesRemaining") or 0) > 0
      and (attacksLeft == nil or attacksLeft > 0) then
    local ok, why = Civ6Ai_Orders._ResolveAttack(unit, x, y)
    if ok then
      return true, "approached:" .. here .. ":attack_instead:" .. tostring(why)
    end
    return true, "approached:" .. here .. ":attack_failed:" .. tostring(why)
  end
  if okMove or moved then
    return true, "approached:" .. here .. ":" .. tostring(whyMove or "moved")
  end
  return false, "enemy_on_tile:" .. tostring(whyMove)
end

function Civ6Ai_Orders._DoMove(sender, o)
  local owner = o.P
  local unit = Civ6Ai_Orders._Unit(owner, o.U)
  if unit == nil then
    return false, "stale_unit_id"
  end
  local intent = o.A or Civ6Ai_Orders.INTENT.MOVE
  if intent < 0 then
    intent = Civ6Ai_Orders.INTENT.MOVE
  end
  local x, y = o.X, o.Y
  if x == nil or y == nil or x < 0 or y < 0 then
    return false, "missing_target"
  end
  if intent == Civ6Ai_Orders.INTENT.TRADE and o.I ~= nil then
    -- The offer was checked from the trader's current city and the engine paths the
    -- route itself (sea included), so start it here instead of walking to the target.
    Civ6Ai_Orders._ClearGoal(owner, o.U)
    return Civ6Ai_Orders.Gov.MakeTradeRoute(owner, o.U, o.I)
  end
  -- Builders walk anywhere like any civilian; Improve offers stay on owned
  -- tiles. (_BuilderOutsideBorders is kept for callers that ask about it.)
  local attacked, attackWhy = Civ6Ai_Orders._MoveAsAttack(unit, x, y)
  if attacked ~= nil then
    if attacked then
      Civ6Ai_Orders._ClearGoal(owner, o.U)
    end
    return attacked, attackWhy
  end
  if unit:GetX() == x and unit:GetY() == y then
    Civ6Ai_Orders._ClearGoal(owner, o.U)
    if intent == Civ6Ai_Orders.INTENT.FOUND or Civ6Ai_Orders._IsSettler(unit) then
      local can, why = Civ6Ai_Orders._Route("CanFoundCityForPlayer", owner, o.U)
      if can then
        return Civ6Ai_Orders._Route("FoundCityForPlayer", owner, o.U)
      end
      if intent == Civ6Ai_Orders.INTENT.FOUND then
        return false, "site_no_longer_legal:" .. tostring(why)
      end
    end
    if intent == Civ6Ai_Orders.INTENT.RELIGION then
      return Civ6Ai_Orders.Gov.FoundReligion(owner, o.I, o.U, o.V, o.W)
    end
    if intent == Civ6Ai_Orders.INTENT.TRADE then
      return Civ6Ai_Orders.Gov.MakeTradeRoute(owner, o.U, o.I)
    end
    if intent == Civ6Ai_Orders.INTENT.IMPROVE and o.I ~= nil and o.I >= 0 then
      return Civ6Ai_Orders.Gov.BuildImprovement(owner, o.U, o.I)
    end
    local ok, reason = Civ6Ai_Orders._Route("FinishMovesForPlayer", owner, o.U)
    return ok, "self_target_hold:" .. tostring(reason)
  end
  local persist = o.G == 1 or intent ~= Civ6Ai_Orders.INTENT.MOVE
    or Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y) > 1
  local ok, reason = Civ6Ai_Orders._MoveWithRetarget(owner, unit, x, y)
  unit = Civ6Ai_Orders._Unit(owner, o.U)
  if not ok then
    local text = tostring(reason or "")
    -- Mountains, water, and a missing route all take one closer step.
    local blocked = text == "impassable" or text == "no_path" or text == "water"
        or text == "water_no_ocean_embark" or text == "land"
        or string.find(text, "no_path", 1, true) ~= nil
        or string.find(text, "impassable", 1, true) ~= nil
    if blocked and unit ~= nil then
      local sx, sy = Civ6Ai_Orders._StepToward(owner, unit, x, y)
      if sx ~= nil then
        local sok, swhy = Civ6Ai_Orders._MoveOnce(owner, unit:GetID(), sx, sy)
        if sok then
          if persist then
            Civ6Ai_Orders._StoreGoal(owner, o.U, x, y, intent, o)
          end
          return true, "step_toward:" .. tostring(x) .. "," .. tostring(y)
            .. ">" .. tostring(sx) .. "," .. tostring(sy) .. ":" .. tostring(swhy)
        end
      end
    end
  end
  if unit ~= nil and unit:GetX() == x and unit:GetY() == y then
    Civ6Ai_Orders._ClearGoal(owner, o.U)
    if intent ~= Civ6Ai_Orders.INTENT.MOVE then
      local aok, awhy = Civ6Ai_Orders._ArrivalAction(owner, unit, intent, o, sender)
      return aok, tostring(reason) .. ":" .. tostring(awhy)
    end
    return ok, reason
  end
  if persist and ok and unit ~= nil then
    Civ6Ai_Orders._StoreGoal(owner, o.U, x, y, intent, o)
  else
    Civ6Ai_Orders._ClearGoal(owner, o.U)
  end
  return ok, reason
end

function Civ6Ai_Orders._TechKnown(owner, idx)
  local techs = call(Players[owner], "GetTechs")
  return techs ~= nil and call(techs, "HasTech", idx) == true
end

function Civ6Ai_Orders._CivicKnown(owner, idx)
  local culture = call(Players[owner], "GetCulture")
  return culture ~= nil and call(culture, "HasCivic", idx) == true
end

function Civ6Ai_Orders._CurrentTech(owner)
  local techs = call(Players[owner], "GetTechs")
  return techs ~= nil and call(techs, "GetResearchingTech") or nil
end

function Civ6Ai_Orders._CurrentCivic(owner)
  local culture = call(Players[owner], "GetCulture")
  return culture ~= nil and call(culture, "GetProgressingCivic") or nil
end

function Civ6Ai_Orders._PickFallback(owner, primary, a, b, knownFn, currentFn)
  local list = { primary, a, b }
  local current = currentFn(owner)
  for _, idx in ipairs(list) do
    if idx ~= nil and idx >= 0 then
      if current ~= nil and current == idx then
        return idx, idx == primary and "already_researching" or "ok_superseded"
      end
      if not knownFn(owner, idx) then
        if idx == primary then
          return idx, "primary"
        end
        return idx, "ok_superseded"
      end
    end
  end
  return nil, "already_known"
end

function Civ6Ai_Orders._DoResearch(owner, o)
  local idx, tag = Civ6Ai_Orders._PickFallback(
    owner, o.I, o.I2, o.I3, Civ6Ai_Orders._TechKnown, Civ6Ai_Orders._CurrentTech)
  if idx == nil then
    return true, "tech_already_known"
  end
  if tag == "already_researching" then
    return true, "ok_already_researching:" .. tostring(idx)
  end
  local ok, reason = Civ6Ai_Orders._Route("SetResearchForPlayer", owner, idx)
  if ok and tag == "ok_superseded" then
    return true, "ok_superseded:" .. tostring(o.I) .. ">" .. tostring(idx) .. ":" .. tostring(reason)
  end
  return ok, reason
end

function Civ6Ai_Orders._DoCivic(owner, o)
  local idx, tag = Civ6Ai_Orders._PickFallback(
    owner, o.I, o.I2, o.I3, Civ6Ai_Orders._CivicKnown, Civ6Ai_Orders._CurrentCivic)
  if idx == nil then
    return true, "civic_already_known"
  end
  if tag == "already_researching" then
    return true, "ok_already_researching:" .. tostring(idx)
  end
  local ok, reason = Civ6Ai_Orders._Route("SetCivicForPlayer", owner, idx)
  if ok and tag == "ok_superseded" then
    return true, "ok_superseded:" .. tostring(o.I) .. ">" .. tostring(idx) .. ":" .. tostring(reason)
  end
  return ok, reason
end

function Civ6Ai_Orders._DoCommand(sender, o)
  local k = o.K
  local owner = o.P
  local why = Civ6Ai_Orders._Authorize(sender, owner)
  if why ~= nil then
    return false, why
  end
  -- Any other order for a fortified unit wakes it (vanilla: a new order cancels fortify).
  if o.U ~= nil and o.U >= 0 and k ~= Civ6Ai_Orders.K.FORTIFY and k ~= Civ6Ai_Orders.K.RESEARCH
      and k ~= Civ6Ai_Orders.K.CIVIC then
    Civ6Ai_Orders.ClearHold(owner, o.U)
  end
  if k == Civ6Ai_Orders.K.MOVE then
    return Civ6Ai_Orders._DoMove(sender, o)
  elseif k == Civ6Ai_Orders.K.RESEARCH then
    return Civ6Ai_Orders._DoResearch(owner, o)
  elseif k == Civ6Ai_Orders.K.CIVIC then
    return Civ6Ai_Orders._DoCivic(owner, o)
  elseif k == Civ6Ai_Orders.K.FOUND then
    local unit = Civ6Ai_Orders._Unit(owner, o.U)
    if unit == nil then
      return false, "stale_unit_id"
    end
    return Civ6Ai_Orders._Route("FoundCityForPlayer", owner, o.U)
  elseif k == Civ6Ai_Orders.K.SKIP or k == Civ6Ai_Orders.K.FORTIFY then
    Civ6Ai_Orders._ClearGoal(owner, o.U)
    local unit = Civ6Ai_Orders._Unit(owner, o.U)
    if unit == nil then
      return false, "stale_unit_id"
    end
    if k == Civ6Ai_Orders.K.FORTIFY then
      -- Fortify holds until another order or an adjacent enemy (vanilla
      -- fortify). The UI fortify operation does not sync for an AI seat, so
      -- the hold is a synced Game property and the unit's moves are finished
      -- at each of its turn starts (HoldFortified).
      Game:SetProperty(Civ6Ai_Orders._HoldKey(owner, o.U), Game.GetCurrentGameTurn())
    end
    return Civ6Ai_Orders._Route("FinishMovesForPlayer", owner, o.U)
  elseif k == Civ6Ai_Orders.K.ATTACK then
    local unit = Civ6Ai_Orders._Unit(owner, o.U)
    if unit == nil then
      return false, "stale_unit_id"
    end
    return Civ6Ai_Orders._Attack(owner, o)
  elseif k == Civ6Ai_Orders.K.TRADE then
    return Civ6Ai_Orders.Gov.MakeTradeRoute(owner, o.U, o.I)
  elseif k == Civ6Ai_Orders.K.EXPLORE then
    return false, "explore_removed"
  elseif k == Civ6Ai_Orders.K.ACTIVATE_GP then
    return Civ6Ai_Orders.Gov.ActivateGreatPerson(owner, o.U, o.V)
  elseif k == Civ6Ai_Orders.K.SPREAD then
    return Civ6Ai_Orders.Gov.SpreadReligion(owner, o.U, o.X, o.Y, o.A)
  elseif k == Civ6Ai_Orders.K.UPGRADE then
    return Civ6Ai_Orders.Gov.UpgradeUnit(owner, o.U, o.I, o.V)
  elseif k == Civ6Ai_Orders.K.PROMOTE then
    return Civ6Ai_Orders.Gov.PromoteUnit(owner, o.U, o.I)
  elseif k == Civ6Ai_Orders.K.FORMATION then
    return Civ6Ai_Orders.Gov.JoinFormation(owner, o.U, o.I)
  elseif k == Civ6Ai_Orders.K.CITY_STRIKE then
    return Civ6Ai_Orders.Gov.CityStrike(owner, o.I, o.X, o.Y)
  elseif k == Civ6Ai_Orders.K.FORT or k == Civ6Ai_Orders.K.IMPROVE then
    return Civ6Ai_Orders.Gov.BuildImprovement(owner, o.U, o.I)
  end
  return false, "unknown_kind"
end

-- An AI seat's attack, melee or ranged. Unit fights use the gameplay forecast
-- and apply that damage here. The unit operation request is UI-only and is
-- nil in this script, so it cannot be the attack. A melee hit that finds a
-- city already at 0 HP, or leaves it there, captures through the gameplay
-- transfer. City ranged strikes stay on CityManager.RequestCommand.
function Civ6Ai_Orders._Attack(owner, o)
  local unit = Civ6Ai_Orders._Unit(owner, o.U)
  if unit == nil then
    return false, "unit_not_found"
  end
  local tx, ty = o.X, o.Y
  local city = Cities ~= nil and Cities.GetCityInPlot ~= nil and Cities.GetCityInPlot(tx, ty) or nil
  if Civ6Ai_Orders._Defender(tx, ty, owner) == nil and (city == nil or city:GetOwner() == owner) then
    -- The target moved off the tile: retarget to an at-war enemy next to it
    -- that this unit can still hit this turn (fixed direction order).
    local nx, ny = Civ6Ai_Orders._RetargetAdjacent(unit, tx, ty)
    if nx ~= nil then
      log("attack_retarget|player=" .. tostring(owner) .. "|unit=" .. tostring(o.U) .. "|from=" .. tostring(tx)
        .. "," .. tostring(ty) .. "|to=" .. tostring(nx) .. "," .. tostring(ny))
      local ok, why = Civ6Ai_Orders._ResolveAttack(unit, nx, ny)
      return ok, "retarget:" .. tostring(nx) .. "," .. tostring(ny) .. ":" .. tostring(why)
    end
  end
  return Civ6Ai_Orders._ResolveAttack(unit, tx, ty)
end

function Civ6Ai_Orders._RetargetAdjacent(unit, x, y)
  if Map == nil or Map.GetAdjacentPlot == nil then
    return nil
  end
  local owner = unit:GetOwner()
  local ranged = Civ6Ai_Orders._IsRanged(unit)
  local reach = ranged and (call(unit, "GetRange") or num(GameInfo.Units[unit:GetType()].Range) or 1) or 1
  for dir = 0, 5 do
    local ok, plot = pcall(Map.GetAdjacentPlot, x, y, dir)
    if ok and plot ~= nil then
      local px, py = plot:GetX(), plot:GetY()
      local d = Map.GetPlotDistance(unit:GetX(), unit:GetY(), px, py)
      local defender = Civ6Ai_Orders._Defender(px, py, owner)
      if d >= 1 and d <= reach and defender ~= nil and Civ6Ai_Orders._AtWar(owner, defender:GetOwner()) then
        return px, py
      end
    end
  end
  return nil
end

function Civ6Ai_Orders._IsRanged(unit)
  local row = GameInfo ~= nil and GameInfo.Units[unit:GetType()] or nil
  if row == nil then
    return false
  end
  local range = num(row.Range) or 0
  if range <= 0 then
    return false
  end
  -- Archers, siege (Bombard), and naval ranged. Melee and land melee have no range.
  return (num(row.RangedCombat) or 0) > 0 or (num(row.Bombard) or 0) > 0
end

function Civ6Ai_Orders._CombatType(unit)
  if CombatTypes == nil then
    return nil
  end
  if not Civ6Ai_Orders._IsRanged(unit) then
    return CombatTypes.MELEE
  end
  local row = GameInfo ~= nil and GameInfo.Units[unit:GetType()] or nil
  local bombard = call(unit, "GetBombardCombat") or (row ~= nil and num(row.Bombard)) or 0
  local ranged = call(unit, "GetRangedCombat") or (row ~= nil and num(row.RangedCombat)) or 0
  if bombard > ranged and CombatTypes.BOMBARD ~= nil then
    return CombatTypes.BOMBARD
  end
  return CombatTypes.RANGED
end

-- The foreign unit on X,Y that defends: the one with the highest strength.
function Civ6Ai_Orders._Defender(x, y, owner)
  local plot = Map.GetPlot(x, y)
  local best, bestStrength = nil, -1
  if plot == nil or Units == nil or Units.GetUnitsInPlot == nil then
    return nil
  end
  for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
    if other:GetOwner() ~= owner and Civ6Ai_Orders._RemoveDead(other) then
      -- a 0 HP unit left over from an earlier scripted hit; it is gone now
    elseif other:GetOwner() ~= owner then
      local row = GameInfo.Units[other:GetType()]
      local strength = row ~= nil and (num(row.Combat) or 0) or 0
      if strength > bestStrength then
        best, bestStrength = other, strength
      end
    end
  end
  return best
end

function Civ6Ai_Orders._DefenderDamage(x, y, owner)
  local plot = Map.GetPlot(x, y)
  local total, count = 0, 0
  if plot == nil or Units == nil or Units.GetUnitsInPlot == nil then
    return 0, 0
  end
  for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
    if other:GetOwner() ~= owner and Civ6Ai_Orders._RemoveDead(other) then
      -- removed: a dead unit does not defend
    elseif other:GetOwner() ~= owner then
      total = total + (call(other, "GetDamage") or 0)
      count = count + 1
    end
  end
  return total, count
end

function Civ6Ai_Orders._AtWar(owner, other)
  local them = Players[other]
  if call(them, "IsBarbarian") == true then
    return true
  end
  local diplo = call(Players[owner], "GetDiplomacy")
  local atWar = call(diplo, "IsAtWarWith", other)
  return atWar == true
end

-- Damage each side takes, from the engine's forecast. Returns
-- attackerDamage, defenderDamage, or nil, reason.
function Civ6Ai_Orders._ReadForecast(res)
  if type(res) ~= "table" or CombatResultParameters == nil then
    return nil
  end
  local P = CombatResultParameters
  local a = res[P.ATTACKER]
  local d = res[P.DEFENDER]
  if type(a) ~= "table" or type(d) ~= "table" then
    return nil
  end
  local toDef = num(d[P.DAMAGE_TO]) or 0
  local wall = P.DEFENSE_DAMAGE_TO ~= nil and (num(d[P.DEFENSE_DAMAGE_TO]) or 0) or 0
  return num(a[P.DAMAGE_TO]) or 0, math.max(toDef, wall)
end

function Civ6Ai_Orders._ForecastOnce(unit, defender, combatType)
  -- Arguments to pcall are evaluated first. A city district with no
  -- GetComponentID throws "function expected instead of nil" on that lookup
  -- and never enters pcall, which aborted the seat's turn on a city attack.
  local attackerId = call(unit, "GetComponentID")
  local defenderId = call(defender, "GetComponentID")
  if attackerId == nil or CombatManager == nil then
    return nil, "no_component_id"
  end
  local okFn, simulate = pcall(function() return CombatManager.SimulateAttackVersus end)
  if defenderId ~= nil and okFn and type(simulate) == "function" then
    local ok, res = pcall(simulate, attackerId, defenderId, combatType)
    if ok then
      local toA, toD = Civ6Ai_Orders._ReadForecast(res)
      if toA ~= nil then
        return toA, toD
      end
    end
  end
  -- A district often has no component id. SimulateAttackInto only needs the attacker.
  local x, y = call(defender, "GetX"), call(defender, "GetY")
  local okInto, into = pcall(function() return CombatManager.SimulateAttackInto end)
  if x ~= nil and y ~= nil and okInto and type(into) == "function" then
    local ok, res = pcall(into, attackerId, combatType, x, y)
    if ok then
      local toA, toD = Civ6Ai_Orders._ReadForecast(res)
      if toA ~= nil then
        return toA, toD
      end
    end
  end
  if defenderId == nil then
    return nil, "no_component_id"
  end
  if not okFn or type(simulate) ~= "function" then
    return nil, "no_simulate"
  end
  return nil, "bad_result"
end

-- The unit panel's hover preview passes nil for melee. A MELEE type that
-- forecasts 0 is retried with nil before the attack is refused.
function Civ6Ai_Orders._Forecast(unit, defender, combatType)
  local simulate = nil
  if CombatManager ~= nil then
    local okFn, fn = pcall(function() return CombatManager.SimulateAttackVersus end)
    if okFn and type(fn) == "function" then
      simulate = fn
    end
  end
  if simulate == nil or CombatResultParameters == nil then
    return nil, "no_combat_forecast"
  end
  local function usable(a, d)
    return a ~= nil and type(d) == "number"
  end
  local toA, toD = Civ6Ai_Orders._ForecastOnce(unit, defender, combatType)
  local why = type(toD) == "string" and toD or nil
  if not usable(toA, toD) or toD <= 0 then
    local a2, d2 = Civ6Ai_Orders._ForecastOnce(unit, defender, nil)
    local soFar = usable(toA, toD) and toD or 0
    if usable(a2, d2) and d2 > soFar then
      toA, toD = a2, d2
      why = nil
    elseif type(d2) == "string" then
      why = d2
    end
  end
  if not usable(toA, toD) then
    return nil, "forecast_failed:" .. tostring(why or "no_result")
  end
  return toA, toD
end

function Civ6Ai_Orders._ChangeDamage(target, amount)
  if amount <= 0 then
    return
  end
  local before = call(target, "GetDamage") or 0
  if target.ChangeDamage ~= nil then
    pcall(target.ChangeDamage, target, amount)
  end
  if (call(target, "GetDamage") or 0) == before and target.SetDamage ~= nil then
    pcall(target.SetDamage, target, before + amount)
  end
end

function Civ6Ai_Orders._IsDead(target)
  local max = call(target, "GetMaxDamage") or 100
  return call(target, "IsDead") == true or (call(target, "GetDamage") or 0) >= max
end

-- A unit at 0 HP leaves the map, as in real combat. Damage set by script does
-- not run the engine's death clean-up, and IsDead() is already true at max
-- damage, so the kill is never gated on IsDead. Kill(unit, false) = no delay.
function Civ6Ai_Orders._RemoveDead(target)
  if target == nil or UnitManager == nil or UnitManager.Kill == nil then
    return false
  end
  if not Civ6Ai_Orders._IsDead(target) then
    return false
  end
  local ok = pcall(UnitManager.Kill, target, false)
  log("combat|remove_dead|owner=" .. tostring(call(target, "GetOwner")) .. "|unit=" .. tostring(call(target, "GetID"))
    .. "|ok=" .. tostring(ok))
  return ok
end

Civ6Ai_Orders.ATTACK_XP = { melee = 3, ranged = 2, kill_bonus = 2 }

-- Hit points left on one district defense layer. Damage at or past the max is 0.
function Civ6Ai_Orders._DistrictHp(district, defenseType)
  local maxHp = call(district, "GetMaxDamage", defenseType) or 0
  local dmg = call(district, "GetDamage", defenseType) or 0
  if dmg >= maxHp then
    return 0
  end
  return maxHp - dmg
end

function Civ6Ai_Orders._CityHitPoints(district)
  if district == nil or DefenseTypes == nil then
    return 0
  end
  return Civ6Ai_Orders._DistrictHp(district, DefenseTypes.DISTRICT_OUTER)
    + Civ6Ai_Orders._DistrictHp(district, DefenseTypes.DISTRICT_GARRISON)
end

-- Kill defenders on the tile, hand the city to owner, then step the attacker on.
-- TransferCity is the gameplay call. AcquireCity is the fallback when that
-- function is absent. Owner is checked after the call: a missing method is not a capture.
function Civ6Ai_Orders._TakeCity(unit, city, x, y)
  local owner = unit:GetOwner()
  if Map ~= nil and Map.GetPlot ~= nil and Units ~= nil and Units.GetUnitsInPlot ~= nil
      and UnitManager ~= nil and UnitManager.Kill ~= nil then
    local plot = Map.GetPlot(x, y)
    for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
      if other:GetOwner() ~= owner then
        pcall(UnitManager.Kill, other)
      end
    end
  end
  local function owned()
    return call(city, "GetOwner") == owner
  end
  if CityManager ~= nil and CityManager.TransferCity ~= nil then
    pcall(CityManager.TransferCity, city, owner)
  end
  if not owned() and Cities ~= nil then
    local okGet, transfer = pcall(function() return Cities.TransferCity end)
    if okGet and type(transfer) == "function" then
      pcall(transfer, city, owner)
    end
  end
  if not owned() and Players ~= nil and Players[owner] ~= nil then
    local okGet, acquire = pcall(function() return Players[owner].AcquireCity end)
    if okGet and type(acquire) == "function" then
      pcall(acquire, Players[owner], city, true, false)
    end
  end
  if not owned() then
    return false
  end
  if UnitManager ~= nil and UnitManager.MoveUnit ~= nil then
    pcall(UnitManager.MoveUnit, unit, x, y)
  elseif UnitManager ~= nil and UnitManager.PlaceUnit ~= nil then
    pcall(UnitManager.PlaceUnit, unit, x, y)
  end
  return true
end

function Civ6Ai_Orders._ResolveAttack(unit, x, y)
  local owner = unit:GetOwner()
  local ranged = Civ6Ai_Orders._IsRanged(unit)
  local dist = Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y)
  if not ranged and dist ~= 1 then
    return false, "not_adjacent"
  end
  if ranged and (dist < 1 or dist > (call(unit, "GetRange") or num(GameInfo.Units[unit:GetType()].Range) or 1)) then
    return false, "out_of_range:" .. tostring(dist)
  end
  local city = Cities ~= nil and Cities.GetCityInPlot ~= nil and Cities.GetCityInPlot(x, y) or nil
  local defender = Civ6Ai_Orders._Defender(x, y, owner)
  if defender == nil or (city ~= nil and city:GetOwner() ~= owner) then
    return Civ6Ai_Orders._AttackCity(unit, x, y, ranged)
  end
  if not Civ6Ai_Orders._AtWar(owner, defender:GetOwner()) then
    return false, "not_at_war"
  end
  if (call(unit, "GetMovesRemaining") or 0) <= 0 then
    return false, "no_moves_left"
  end
  local attacks = call(unit, "GetAttacksRemaining")
  if attacks ~= nil and attacks <= 0 then
    return false, "no_attacks_left"
  end
  local combatType = Civ6Ai_Orders._CombatType(unit)
  local toAttacker, toDefender = Civ6Ai_Orders._Forecast(unit, defender, combatType)
  if toAttacker == nil then
    return false, toDefender
  end
  if ranged then
    toAttacker = 0
  end
  if toDefender <= 0 and toAttacker <= 0 then
    return false, "no_effect:zero_damage"
  end
  local defBefore = call(defender, "GetDamage") or 0
  local attBefore = call(unit, "GetDamage") or 0
  Civ6Ai_Orders._ChangeDamage(defender, toDefender)
  Civ6Ai_Orders._ChangeDamage(unit, toAttacker)
  local killed = Civ6Ai_Orders._IsDead(defender)
  local lost = Civ6Ai_Orders._IsDead(unit)
  local defAfter = call(defender, "GetDamage") or 0
  if not killed and toDefender > 0 and defAfter == defBefore then
    return false, "no_effect:damage_not_applied:forecast=" .. tostring(toDefender)
  end
  if killed then
    Civ6Ai_Orders._RemoveDead(defender)
  end
  if lost then
    Civ6Ai_Orders._RemoveDead(unit)
  else
    local exp = call(unit, "GetExperience")
    local xp = (ranged and Civ6Ai_Orders.ATTACK_XP.ranged or Civ6Ai_Orders.ATTACK_XP.melee)
      + (killed and Civ6Ai_Orders.ATTACK_XP.kill_bonus or 0)
    if exp ~= nil and exp.ChangeExperience ~= nil then
      pcall(exp.ChangeExperience, exp, xp)
    end
    local _, left = Civ6Ai_Orders._DefenderDamage(x, y, owner)
    if killed and not ranged and left == 0 then
      pcall(UnitManager.MoveUnit, unit, x, y)
    end
    pcall(UnitManager.FinishMoves, unit)
  end
  return true, (ranged and "ranged" or "melee") .. ":def_dmg=" .. defBefore .. ">" .. defAfter
    .. ":att_dmg=" .. attBefore .. ">" .. (lost and "dead" or tostring(call(unit, "GetDamage") or 0))
    .. ":killed=" .. tostring(killed)
end

-- Fight the enemy city on X,Y (centre district, walls first) from the forecast.
-- Melee captures when the city is already at 0 HP, or when this hit leaves it there.
-- A city that still has HP and does not take the forecast damage is still a refusal.
function Civ6Ai_Orders._AttackCity(unit, x, y, ranged)
  local owner = unit:GetOwner()
  local city = Cities ~= nil and Cities.GetCityInPlot ~= nil and Cities.GetCityInPlot(x, y) or nil
  if city == nil or city:GetOwner() == owner then
    return false, "no_enemy_on_plot"
  end
  if not Civ6Ai_Orders._AtWar(owner, city:GetOwner()) then
    return false, "not_at_war"
  end
  if (call(unit, "GetMovesRemaining") or 0) <= 0 or (call(unit, "GetAttacksRemaining") or 1) <= 0 then
    return false, "no_moves_left"
  end
  local district = Civ6Ai_Orders._CityCenterDistrict(city)
  if district == nil or DefenseTypes == nil then
    return false, "no_city_district"
  end
  local before = Civ6Ai_Orders._CityHitPoints(district)
  if not ranged and before <= 0 and not Civ6Ai_Orders._IsDead(unit) then
    local captured = Civ6Ai_Orders._TakeCity(unit, city, x, y)
    pcall(UnitManager.FinishMoves, unit)
    if not captured then
      return false, "capture_unavailable"
    end
    return true, "melee:city_hp=" .. tostring(before) .. ">0:captured=true"
  end
  local toAttacker, toCity = Civ6Ai_Orders._Forecast(unit, district, Civ6Ai_Orders._CombatType(unit))
  if toAttacker == nil then
    return false, toCity
  end
  if toCity <= 0 then
    return false, "no_effect:zero_damage"
  end
  local walls, garrison = DefenseTypes.DISTRICT_OUTER, DefenseTypes.DISTRICT_GARRISON
  local w = math.min(toCity, Civ6Ai_Orders._DistrictHp(district, walls))
  call(district, "ChangeDamage", walls, w)
  call(district, "ChangeDamage", garrison, toCity - w)
  if not ranged then
    Civ6Ai_Orders._ChangeDamage(unit, toAttacker)
    Civ6Ai_Orders._RemoveDead(unit)
  end
  local after = Civ6Ai_Orders._CityHitPoints(district)
  if after >= before then
    return false, "no_effect:damage_not_applied:forecast=" .. tostring(toCity)
  end
  local captured = false
  if not ranged and after <= 0 and not Civ6Ai_Orders._IsDead(unit) then
    captured = Civ6Ai_Orders._TakeCity(unit, city, x, y)
  end
  pcall(UnitManager.FinishMoves, unit)
  return true, (ranged and "ranged" or "melee") .. ":city_hp=" .. tostring(before) .. ">"
    .. tostring(after) .. ":captured=" .. tostring(captured)
end

function Civ6Ai_Orders._MeleeStep(unit, x, y)
  if Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y) ~= 1 then
    return false, "not_adjacent"
  end
  local owner = unit:GetOwner()
  local dmgBefore, defenders = Civ6Ai_Orders._DefenderDamage(x, y, owner)
  if defenders == 0 then
    return false, "no_enemy_on_plot"
  end
  local fromX, fromY = unit:GetX(), unit:GetY()
  local hpBefore = call(unit, "GetDamage") or 0
  local ok = pcall(UnitManager.MoveUnit, unit, x, y)
  if not ok then
    return false, "melee_move_error"
  end
  local dmgAfter = Civ6Ai_Orders._DefenderDamage(x, y, owner)
  local moved = unit:GetX() ~= fromX or unit:GetY() ~= fromY
  local hpAfter = call(unit, "GetDamage") or 0
  if dmgAfter ~= dmgBefore or moved or hpAfter ~= hpBefore then
    return true, "melee:def_dmg=" .. dmgBefore .. ">" .. dmgAfter .. ":att_dmg=" .. hpBefore .. ">" .. hpAfter
      .. ":moved=" .. tostring(moved)
  end
  return false, "melee_no_effect"
end

local function retryable(k, reason)
  if k ~= Civ6Ai_Orders.K.MOVE and k ~= Civ6Ai_Orders.K.ATTACK then
    return false
  end
  local text = tostring(reason or "")
  return string.find(text, "occupied", 1, true) ~= nil or string.find(text, "stack_limit", 1, true) ~= nil
end

-- One decision order. Returns ok, reason.
function Civ6Ai_Orders._Execute(sender, o)
  local k = o.K
  if k == Civ6Ai_Orders.K.PRIORITY then
    return Civ6Ai_Orders._SetPriority(sender, o)
  end
  if k ~= nil and k >= Civ6Ai_Orders.K.GOVERNMENT and k <= Civ6Ai_Orders.K.GOVERNOR then
    return Civ6Ai_Orders._DoGovernance(sender, o)
  end
  if k == Civ6Ai_Orders.K.WAR or k == Civ6Ai_Orders.K.DEAL or k == Civ6Ai_Orders.K.ENVOY
      or k == Civ6Ai_Orders.K.BUY or k == Civ6Ai_Orders.K.BUY_TILE then
    return Civ6Ai_Orders._DoDeal(sender, o)
  end
  if k == Civ6Ai_Orders.K.PILLAGE then
    return Civ6Ai_Orders._DoWork(sender, o)
  end
  return Civ6Ai_Orders._DoCommand(sender, o)
end

-- Unit attacks and city strikes before every other order. A move that fails
-- or spends the unit must not run first and make a listed attack illegal.
-- Stable: attacks keep their relative order, and so does everything else.
function Civ6Ai_Orders._AttacksBeforeMoves(orders)
  local attacks, rest = {}, {}
  for _, o in ipairs(orders or {}) do
    if o.K == Civ6Ai_Orders.K.ATTACK or o.K == Civ6Ai_Orders.K.CITY_STRIKE then
      attacks[#attacks + 1] = o
    else
      rest[#rest + 1] = o
    end
  end
  for _, o in ipairs(rest) do
    attacks[#attacks + 1] = o
  end
  return attacks
end

-- A move that sets up an attack this unit cannot reach yet runs first.
-- An attack already in range stays ahead of that unit's move: the move would
-- spend the unit and the attack would never fire.
function Civ6Ai_Orders._SetupMovesFirst(orders)
  local info = {}
  for _, o in ipairs(orders or {}) do
    if o.U ~= nil and (o.K == Civ6Ai_Orders.K.ATTACK or o.K == Civ6Ai_Orders.K.MOVE) then
      local row = info[o.U]
      if row == nil then
        row = { attack = false, move = false, attackInRange = false }
        info[o.U] = row
      end
      if o.K == Civ6Ai_Orders.K.ATTACK then
        row.attack = true
        local unit = Civ6Ai_Orders._Unit(o.P, o.U)
        if unit ~= nil and Civ6Ai_Orders._InAttackRange(unit, o.X, o.Y) then
          row.attackInRange = true
        end
      else
        row.move = true
      end
    end
  end
  local function setsUp(o)
    local row = o.U ~= nil and info[o.U] or nil
    return row ~= nil and row.attack and row.move and not row.attackInRange and o.K == Civ6Ai_Orders.K.MOVE
  end
  local first, rest = {}, {}
  for _, o in ipairs(orders or {}) do
    if setsUp(o) then
      first[#first + 1] = o
    else
      rest[#rest + 1] = o
    end
  end
  for _, o in ipairs(rest) do
    first[#first + 1] = o
  end
  return first
end

local function noteAttack(counts, o, ok)
  local which = nil
  if o.K == Civ6Ai_Orders.K.ATTACK then
    which = "unit"
  elseif o.K == Civ6Ai_Orders.K.CITY_STRIKE then
    which = "city"
  end
  if which == nil then
    return
  end
  local bucket = ok and counts.ok or counts.fail
  bucket[which] = bucket[which] + 1
end

-- Remaining hit points. A missing max is treated as the usual 100.
function Civ6Ai_Orders._HpLeft(target)
  local maxHp = call(target, "GetMaxDamage") or 100
  local dmg = call(target, "GetDamage") or 0
  if maxHp < dmg then
    return 0
  end
  return maxHp - dmg
end

function Civ6Ai_Orders._WouldDie(target, damage)
  return type(damage) == "number" and damage > 0 and damage >= Civ6Ai_Orders._HpLeft(target)
end

-- auto: 0 off, 2 include a human seat, anything else is AI seats only.
-- A nil mode is the default: not IsHuman(). The local human (P0 in a real
-- game) is IsHuman and is never auto-fired unless the host sent mode 2.
function Civ6Ai_Orders._AutoRangedEnabled(owner, mode)
  if mode == 0 then
    return false
  end
  if call(Players[owner], "IsHuman") and mode ~= 2 then
    return false
  end
  return true
end

-- After apply, one handled set: units, cities, city-strike opportunities.
-- A fallback may act only when that entity is not in the set. Failed
-- validation or dispatch leaves the entity unhandled.
function Civ6Ai_Orders._NewHandled()
  return { unit = {}, city = {}, strike = {}, empire = {} }
end

-- value: the model order kind (K), "fallback" or "goal". Any value means handled.
function Civ6Ai_Orders._MarkHandled(handled, class, id, value)
  if handled == nil or class == nil or id == nil then
    return
  end
  handled[class] = handled[class] or {}
  handled[class][id] = value or true
end

function Civ6Ai_Orders._WasHandled(handled, class, id)
  return handled ~= nil and handled[class] ~= nil and handled[class][id] ~= nil and handled[class][id] ~= false
end

function Civ6Ai_Orders._HandledProp(owner, class, id)
  return "CIV6AI_H_" .. tostring(owner) .. "_" .. tostring(class) .. "_" .. tostring(id)
end

function Civ6Ai_Orders._PersistHandled(owner, handled)
  if Game == nil or Game.SetProperty == nil or handled == nil then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  for _, class in ipairs({ "unit", "city", "strike" }) do
    local set = handled[class] or {}
    for _, id in ipairs(sortedKeys(set)) do
      if set[id] then
        pcall(function()
          Game:SetProperty(Civ6Ai_Orders._HandledProp(owner, class, id), turn)
        end)
      end
    end
  end
end

function Civ6Ai_Orders.WasHandled(owner, class, id)
  if Game == nil or Game.GetProperty == nil then
    return false
  end
  local turn = Game.GetCurrentGameTurn()
  local ok, value = pcall(function()
    return Game:GetProperty(Civ6Ai_Orders._HandledProp(owner, class, id))
  end)
  return ok and num(value) == turn
end

function Civ6Ai_Orders.MarkHandled(owner, class, id)
  if class == nil or id == nil then
    return
  end
  if Game == nil or Game.SetProperty == nil then
    return
  end
  pcall(function()
    Game:SetProperty(Civ6Ai_Orders._HandledProp(owner, class, id), Game.GetCurrentGameTurn())
  end)
end

function Civ6Ai_Orders._OrderEntity(o)
  if o == nil then
    return nil
  end
  local k = o.K
  if k == Civ6Ai_Orders.K.CITY_STRIKE and o.I ~= nil then
    return "strike", o.I
  end
  if k == Civ6Ai_Orders.K.PRIORITY then
    return "empire", "priority"
  end
  if (k == Civ6Ai_Orders.K.BUY or k == Civ6Ai_Orders.K.BUY_TILE) and o.I ~= nil then
    return "city", o.I
  end
  if o.U ~= nil and o.U >= 0 then
    return "unit", o.U
  end
  return nil
end

function Civ6Ai_Orders._LogOrderSource(owner, source, kind, class, id, reason)
  log("orders|source=" .. tostring(source)
    .. "|player=" .. tostring(owner)
    .. "|turn=" .. tostring(Game.GetCurrentGameTurn())
    .. "|kind=" .. tostring(kind)
    .. "|entity=" .. tostring(class) .. ":" .. tostring(id)
    .. "|reason=" .. tostring(reason or ""))
end

function Civ6Ai_Orders._IsExplorer(unit)
  local row = GameInfo ~= nil and GameInfo.Units ~= nil and GameInfo.Units[call(unit, "GetType")] or nil
  if row == nil then
    return false
  end
  local typ = tostring(row.UnitType or "")
  if string.find(typ, "SETTLER", 1, true) or string.find(typ, "BUILDER", 1, true) then
    return false
  end
  if string.find(typ, "SCOUT", 1, true) or string.find(typ, "RANGER", 1, true)
      or string.find(typ, "RECON", 1, true) then
    return true
  end
  if row.MakeTradeRoute == true then
    return false
  end
  if (num(row.BuildCharges) or 0) > 0 then
    return false
  end
  -- A civilian with no combat, or a ship, can take the explore fallback.
  if (num(row.Combat) or 0) == 0 and (num(row.RangedCombat) or 0) == 0 then
    return true
  end
  return row.Domain == "DOMAIN_SEA"
end

-- Hint roles (param A on a K.HINT order). The sidecar proposes a target from
-- the seat's snapshot, in the same synced batch; this pass decides.
Civ6Ai_Orders.HINT_ROLE = { EXPLORE = 1, IMPROVE = 2, DEFEND = 3, SETTLE = 4, PRIORITY = 9 }

-- The one host fallback pass, in this order. A row acts only on an entity the
-- handled set does not hold (a successful model order, or an earlier row), and
-- marks what it ran. gated rows need the seat's auto mode (_AutoRangedEnabled).
Civ6Ai_Orders.FALLBACKS = {
  { name = "combat", seat = "_AutoRanged", gated = true },
  { name = "goal", unit = "_FbGoal" },
  { name = "settle", unit = "_FbSettle" },
  { name = "improve", unit = "_FbImprove" },
  { name = "defend", unit = "_FbDefend" },
  { name = "priority", seat = "_FbPriority" },
}

-- Hints out of a batch: units by id, empire-level rows in order. Each hint
-- gets its result row now (it is not an order).
function Civ6Ai_Orders._SplitHints(sender, orders)
  local hints, rest = { unit = {}, empire = {} }, {}
  for _, o in ipairs(orders or {}) do
    if o.K == Civ6Ai_Orders.K.HINT then
      if o.A == Civ6Ai_Orders.HINT_ROLE.PRIORITY then
        hints.empire[#hints.empire + 1] = o
      elseif o.U ~= nil and o.U >= 0 then
        hints.unit[o.U] = o
      end
      Civ6Ai_Orders._Record(sender, o, true, "hint", "hint")
    else
      rest[#rest + 1] = o
    end
  end
  return hints, rest
end

function Civ6Ai_Orders._FbRun(sender, owner, unit, o, kind)
  o.S, o.P, o.U, o.D = -1, owner, unit:GetID(), Game.GetCurrentGameTurn()
  local ok, why = Civ6Ai_Orders._Execute(sender, o)
  if ok then
    local reason = "fallback:" .. kind .. ":" .. tostring(why or "")
    Civ6Ai_Orders._Record(sender, o, true, reason, "fallback")
    Civ6Ai_Orders._AutoJson(owner, kind, reason, "AUTO_FB_" .. kind .. "_" .. tostring(o.U),
      { unit = o.U, x = o.X ~= nil and o.X >= 0 and o.X or nil, y = o.Y ~= nil and o.Y >= 0 and o.Y or nil })
  end
  return ok, kind, why
end

local function hinted(hint, role)
  return hint ~= nil and hint.A == role
end

local function hasTarget(hint)
  return hint.X ~= nil and hint.X >= 0 and hint.Y ~= nil and hint.Y >= 0
end

function Civ6Ai_Orders._FbGoal(sender, owner, unit)
  local ok = Civ6Ai_Orders._ContinueGoal(owner, unit)
  return ok, "goal", nil, "goal"
end

function Civ6Ai_Orders._FbExplore(sender, owner, unit, hint, enabled)
  if (call(unit, "GetMovesRemaining") or 0) <= 0 then
    return false
  end
  if hinted(hint, Civ6Ai_Orders.HINT_ROLE.EXPLORE) and hasTarget(hint) then
    return Civ6Ai_Orders._FbRun(sender, owner, unit, { K = Civ6Ai_Orders.K.MOVE, X = hint.X, Y = hint.Y }, "move_unit")
  end
  if not hinted(hint, Civ6Ai_Orders.HINT_ROLE.EXPLORE)
      and not (hint == nil and enabled and Civ6Ai_Orders._IsExplorer(unit)) then
    return false
  end
  local uid = unit:GetID()
  local ok, why = Civ6Ai_Orders.Gov.Explore(owner, uid)
  if ok then
    Civ6Ai_Orders._Record(sender, {
      S = -1, K = Civ6Ai_Orders.K.EXPLORE, P = owner, U = uid, D = Game.GetCurrentGameTurn(),
    }, true, "auto:" .. tostring(why or "explore"), "fallback")
    Civ6Ai_Orders._AutoJson(owner, "explore", "auto:" .. tostring(why or "explore"),
      "AUTO_E_" .. tostring(uid), { unit = uid })
  end
  return ok, "explore", why
end

-- Found on a listed site, otherwise walk to it (found on arrival).
function Civ6Ai_Orders._FbSettle(sender, owner, unit, hint)
  if not hinted(hint, Civ6Ai_Orders.HINT_ROLE.SETTLE) or not hasTarget(hint) then
    return false
  end
  if unit:GetX() == hint.X and unit:GetY() == hint.Y then
    return Civ6Ai_Orders._FbRun(sender, owner, unit, { K = Civ6Ai_Orders.K.FOUND }, "found_city")
  end
  return Civ6Ai_Orders._FbRun(sender, owner, unit, {
    K = Civ6Ai_Orders.K.MOVE, X = hint.X, Y = hint.Y, G = 1, A = Civ6Ai_Orders.INTENT.FOUND,
  }, "move_unit")
end

function Civ6Ai_Orders._FbImprove(sender, owner, unit, hint)
  if not hinted(hint, Civ6Ai_Orders.HINT_ROLE.IMPROVE) or not hasTarget(hint) then
    return false
  end
  return Civ6Ai_Orders._FbRun(sender, owner, unit, { K = Civ6Ai_Orders.K.MOVE, X = hint.X, Y = hint.Y }, "move_unit")
end

-- Move to the threatened city the hint names, otherwise fortify.
function Civ6Ai_Orders._FbDefend(sender, owner, unit, hint)
  if not hinted(hint, Civ6Ai_Orders.HINT_ROLE.DEFEND) then
    return false
  end
  if hasTarget(hint) then
    local ok, kind, why = Civ6Ai_Orders._FbRun(
      sender, owner, unit, { K = Civ6Ai_Orders.K.MOVE, X = hint.X, Y = hint.Y }, "move_unit")
    if ok then
      return ok, kind, why
    end
  end
  return Civ6Ai_Orders._FbRun(sender, owner, unit, { K = Civ6Ai_Orders.K.FORTIFY }, "unit_posture_fortify")
end

-- Empty production: the sidecar's priority packets, unless the model set priorities.
function Civ6Ai_Orders._FbPriority(sender, owner, handled, mode, hints)
  log("fb_priority|player=" .. tostring(owner) .. "|hints=" .. tostring(#(hints.empire or {}))
    .. "|handled=" .. tostring(Civ6Ai_Orders._WasHandled(handled, "empire", "priority")))
  if Civ6Ai_Orders._WasHandled(handled, "empire", "priority") then
    return
  end
  for _, h in ipairs(hints.empire) do
    local o = { S = -1, K = Civ6Ai_Orders.K.PRIORITY, P = owner, I = h.I, X = h.X, D = Game.GetCurrentGameTurn() }
    local ok, why = Civ6Ai_Orders._Execute(sender, o)
    Civ6Ai_Orders._Record(sender, o, ok, "fallback:priority:" .. tostring(why or ""), "fallback")
    if ok then
      Civ6Ai_Orders._MarkHandled(handled, "empire", "priority", "fallback")
      Civ6Ai_Orders._LogOrderSource(owner, "fallback", "set_build_priority", "empire", "priority", why)
    end
  end
end

function Civ6Ai_Orders._RunHostFallbacks(sender, owner, handled, mode, hints)
  handled = handled or Civ6Ai_Orders._NewHandled()
  hints = hints or { unit = {}, empire = {} }
  Civ6Ai_Orders._PersistHandled(owner, handled)
  local enabled = Civ6Ai_Orders._AutoRangedEnabled(owner, mode)
  local p = Players[owner]
  for _, row in ipairs(Civ6Ai_Orders.FALLBACKS) do
    if row.seat ~= nil and (enabled or not row.gated) then
      local ran, err = pcall(Civ6Ai_Orders[row.seat], sender, owner, handled, mode, hints)
      if not ran then
        log("fallback_error|row=" .. row.name .. "|player=" .. tostring(owner) .. "|" .. trimErr(err))
      end
    elseif row.unit ~= nil and p ~= nil then
      for _, unit in ipairs(sortedMembers(call(p, "GetUnits"))) do
        local uid = unit:GetID()
        if not Civ6Ai_Orders._WasHandled(handled, "unit", uid) then
          local ran, ok, kind, why, mark = pcall(
            Civ6Ai_Orders[row.unit], sender, owner, unit, hints.unit[uid], enabled)
          if not ran then
            log("fallback_error|row=" .. row.name .. "|unit=" .. tostring(uid) .. "|" .. trimErr(ok))
          elseif ok then
            Civ6Ai_Orders._MarkHandled(handled, "unit", uid, mark or "fallback")
            Civ6Ai_Orders._LogOrderSource(owner, mark == "goal" and "goal" or "fallback", kind, "unit", uid, why)
          end
        end
      end
    end
  end
  return handled
end

function Civ6Ai_Orders._AutoJson(owner, kind, reason, commandId, fixed, source)
  local function esc(text)
    text = tostring(text or "")
    text = string.gsub(text, "\\", "\\\\")
    text = string.gsub(text, '"', '\\"')
    return text
  end
  local extra = ""
  if type(fixed) == "table" then
    local bits = {}
    if fixed.unit ~= nil then
      bits[#bits + 1] = '"unit_id":"' .. esc(fixed.unit) .. '"'
    end
    if fixed.city ~= nil then
      bits[#bits + 1] = '"city_id":"' .. esc(fixed.city) .. '"'
    end
    if fixed.x ~= nil then
      bits[#bits + 1] = '"target_x":' .. tostring(fixed.x)
    end
    if fixed.y ~= nil then
      bits[#bits + 1] = '"target_y":' .. tostring(fixed.y)
    end
    if #bits > 0 then
      extra = ',"fixed_arguments":{' .. table.concat(bits, ",") .. "}"
    end
  end
  print("CIV6AI|jsonl|{\"event\":\"apply_result\",\"turn\":" .. tostring(Game.GetCurrentGameTurn())
    .. ",\"player_id\":\"PLAYER_" .. tostring(owner)
    .. "\",\"command_id\":\"" .. esc(commandId)
    .. "\",\"kind\":\"" .. esc(kind)
    .. "\",\"ok\":true,\"reason\":\"" .. esc(reason)
    .. "\",\"source\":\"" .. esc(source or "fallback") .. "\"" .. extra .. "}")
end

function Civ6Ai_Orders._AutoRank(kind, killable)
  if kind == "unit" and killable then
    return 1
  end
  if kind == "unit" then
    return 2
  end
  if killable then
    return 3
  end
  return 4
end

-- One ranged shot, or nil when the forecast is unusable or would kill the shooter.
function Civ6Ai_Orders._AutoPreview(attacker, defender, combatType)
  local toA, toD = Civ6Ai_Orders._Forecast(attacker, defender, combatType)
  if type(toA) ~= "number" or type(toD) ~= "number" or toD <= 0 then
    return nil
  end
  if Civ6Ai_Orders._WouldDie(attacker, toA) then
    return nil, "attacker_would_die"
  end
  return toA, toD
end

function Civ6Ai_Orders._AutoCandidates(owner, x, y, reach)
  local out = {}
  for pid = 0, 63 do
    if pid ~= owner and Civ6Ai_Orders._AtWar(owner, pid) then
      local them = Players[pid]
      for _, unit in ipairs(sortedMembers(call(them, "GetUnits"))) do
        local dist = Map.GetPlotDistance(x, y, unit:GetX(), unit:GetY())
        if dist >= 1 and dist <= reach and call(unit, "IsDead") ~= true then
          out[#out + 1] = { kind = "unit", obj = unit, x = unit:GetX(), y = unit:GetY(), id = unit:GetID() }
        end
      end
      for _, city in ipairs(sortedMembers(call(them, "GetCities"))) do
        local dist = Map.GetPlotDistance(x, y, city:GetX(), city:GetY())
        if dist >= 1 and dist <= reach then
          out[#out + 1] = { kind = "city", obj = city, x = city:GetX(), y = city:GetY(), id = city:GetID() }
        end
      end
    end
  end
  return out
end

function Civ6Ai_Orders._PickAutoTarget(attacker, owner, x, y, reach, combatType)
  local best = nil
  local sawDie = false
  for _, cand in ipairs(Civ6Ai_Orders._AutoCandidates(owner, x, y, reach)) do
    local defender = cand.obj
    if cand.kind == "city" then
      defender = Civ6Ai_Orders._CityCenterDistrict(cand.obj) or cand.obj
    end
    local toA, toD = Civ6Ai_Orders._AutoPreview(attacker, defender, combatType)
    if toA == nil and toD == "attacker_would_die" then
      sawDie = true
    elseif type(toD) == "number" then
      local hp = Civ6Ai_Orders._HpLeft(cand.kind == "unit" and cand.obj or defender)
      local row = {
        cand = cand, dmg = toD, hp = hp,
        rank = Civ6Ai_Orders._AutoRank(cand.kind, toD >= hp),
      }
      if best == nil or row.rank < best.rank or (row.rank == best.rank and row.hp < best.hp)
          or (row.rank == best.rank and row.hp == best.hp and row.dmg > best.dmg)
          or (row.rank == best.rank and row.hp == best.hp and row.dmg == best.dmg and row.cand.x < best.cand.x)
          or (row.rank == best.rank and row.hp == best.hp and row.dmg == best.dmg
              and row.cand.x == best.cand.x and row.cand.y < best.cand.y) then
        best = row
      end
    end
  end
  return best, sawDie
end

-- After the model's orders: unused ranged, siege, and naval ranged units, plus
-- city and encampment strikes. Melee is left alone. Runs inside _ApplyOrders,
-- so every PC plays the same shots. The host chooses the mode on the batch.
Civ6Ai_Orders._autoDone = Civ6Ai_Orders._autoDone or {}

function Civ6Ai_Orders._AutoRanged(sender, owner, handled, mode)
  if not Civ6Ai_Orders._AutoRangedEnabled(owner, mode) then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  local doneKey = tostring(owner) .. ":" .. tostring(turn)
  if Civ6Ai_Orders._autoDone[doneKey] then
    return
  end
  Civ6Ai_Orders._autoDone[doneKey] = true
  handled = handled or Civ6Ai_Orders._NewHandled()
  local unitOk, cityOk, skipped = 0, 0, 0
  local function note(kind, reason, commandId, order, fixed)
    Civ6Ai_Orders._Record(sender, order, true, reason, "fallback")
    Civ6Ai_Orders._AutoJson(owner, kind, reason, commandId, fixed, "fallback")
    local class, id = "unit", order.U
    if kind == "city_attack" then
      class, id = "strike", order.I
    end
    Civ6Ai_Orders._MarkHandled(handled, class, id, "fallback")
    Civ6Ai_Orders._LogOrderSource(owner, "fallback", kind, class, id, reason)
  end
  local p = Players[owner]
  for _, unit in ipairs(sortedMembers(call(p, "GetUnits"))) do
    local uid = unit:GetID()
    -- A successful model order (any kind) owns this unit. Failed validation
    -- or dispatch leaves it unhandled, so the fallback may still shoot.
    local eligible = not Civ6Ai_Orders._WasHandled(handled, "unit", uid)
    if Civ6Ai_Orders._IsRanged(unit) and eligible
        and (call(unit, "GetMovesRemaining") or 0) > 0
        and (call(unit, "GetAttacksRemaining") == nil or (call(unit, "GetAttacksRemaining") or 0) > 0) then
      local row = GameInfo.Units[unit:GetType()]
      local reach = num(row and row.Range) or 1
      local best, sawDie = Civ6Ai_Orders._PickAutoTarget(
        unit, owner, unit:GetX(), unit:GetY(), reach, Civ6Ai_Orders._CombatType(unit))
      if best == nil then
        if sawDie then
          skipped = skipped + 1
        end
      else
        local ok, why = Civ6Ai_Orders._ResolveAttack(unit, best.cand.x, best.cand.y)
        local reason = "auto:" .. tostring(why or "")
        if ok then
          unitOk = unitOk + 1
          note("attack_target", reason, "AUTO_U_" .. tostring(uid) .. "_" .. best.cand.x .. "_" .. best.cand.y, {
            S = -1, K = Civ6Ai_Orders.K.ATTACK, P = owner, U = uid,
            X = best.cand.x, Y = best.cand.y, D = turn,
          }, { unit = uid, x = best.cand.x, y = best.cand.y })
        else
          skipped = skipped + 1
        end
      end
    end
  end
  -- Same command as an ordered strike. No forecast, and no damage applied here.
  -- The first refusal stops the rest, matching the ordered batch.
  -- nil means the gameplay command API is missing (the strike itself reports that).
  -- false means CanStartCommand refused this plot, so another target can be tried.
  local function strikeReady(city, x, y)
    return Civ6Ai_Orders._CityStrikeCan(city, x, y)
  end
  local function bestStrike(city, x, y)
    local best = nil
    local blocked = false
    for _, cand in ipairs(Civ6Ai_Orders._AutoCandidates(owner, x, y, 2)) do
      local ready = strikeReady(city, cand.x, cand.y)
      if ready == false then
        blocked = true
      else
        local hp = Civ6Ai_Orders._HpLeft(cand.obj)
        local rank = cand.kind == "unit" and 1 or 2
        if best == nil or rank < best.rank or (rank == best.rank and hp < best.hp)
            or (rank == best.rank and hp == best.hp and cand.x < best.cand.x)
            or (rank == best.rank and hp == best.hp and cand.x == best.cand.x and cand.y < best.cand.y) then
          best = { cand = cand, hp = hp, rank = rank }
        end
      end
    end
    return best, blocked
  end
  local function cityOf(district)
    local found = call(district, "GetCity")
    if found ~= nil and found.GetID ~= nil then
      return found
    end
    local cid = call(district, "GetCityID")
    if cid == nil then
      return nil
    end
    for _, city in ipairs(sortedMembers(call(p, "GetCities"))) do
      if city:GetID() == cid then
        return city
      end
    end
    return nil
  end
  local stopped = false
  local skipWhy = nil
  if not Civ6Ai_Orders.CityStrikeAvailable() then
    stopped = true
    skipWhy = "city_strike_unavailable"
  end
  local function fire(city, fromX, fromY, commandId)
    if stopped or city == nil then
      return
    end
    local cityId = city:GetID()
    if Civ6Ai_Orders._WasHandled(handled, "strike", cityId) then
      return
    end
    local key = "CIV6AI_STRIKE_" .. tostring(owner) .. "_" .. tostring(cityId)
    if num(Game:GetProperty(key)) == turn then
      return
    end
    local best, blocked = bestStrike(city, fromX, fromY)
    if best == nil then
      if blocked then
        skipped = skipped + 1
        skipWhy = skipWhy or "city_strike_refused"
      end
      return
    end
    local tx, ty = best.cand.x, best.cand.y
    local ok, why
    if fromX == city:GetX() and fromY == city:GetY() then
      ok, why = Civ6Ai_Orders.Gov.CityStrike(owner, cityId, tx, ty)
    else
      local defenderId = Civ6Ai_Orders._LiveStrikeTarget(owner, tx, ty)
      if defenderId == nil then
        ok, why = false, "no_enemy_on_plot"
      else
        log("city_strike|city=" .. tostring(cityId) .. "|x=" .. tostring(tx) .. "|y=" .. tostring(ty)
          .. "|defender=" .. tostring(defenderId))
        ok, why = Civ6Ai_Orders._CityRangeAttack(city, tx, ty)
        if ok then
          Game:SetProperty(key, turn)
        end
      end
    end
    if ok then
      cityOk = cityOk + 1
      note("city_attack", "auto:" .. tostring(why or ""), commandId .. "_" .. tx .. "_" .. ty, {
        S = -1, K = Civ6Ai_Orders.K.CITY_STRIKE, P = owner, I = cityId,
        X = tx, Y = ty, D = turn,
      }, { city = cityId, x = tx, y = ty })
    else
      stopped = true
      skipped = skipped + 1
      skipWhy = skipWhy or why or "city_strike_refused"
    end
  end
  for _, city in ipairs(sortedMembers(call(p, "GetCities"))) do
    fire(city, city:GetX(), city:GetY(), "AUTO_C_" .. tostring(city:GetID()))
  end
  for _, district in ipairs(sortedMembers(call(p, "GetDistricts"))) do
    local row = GameInfo ~= nil and GameInfo.Districts ~= nil and GameInfo.Districts[call(district, "GetType")] or nil
    if row ~= nil and row.DistrictType == "DISTRICT_ENCAMPMENT" then
      local city = cityOf(district)
      fire(city, call(district, "GetX"), call(district, "GetY"), "AUTO_E_" .. tostring(call(district, "GetID") or 0))
    end
  end
  if unitOk + cityOk + skipped > 0 then
    local line = "CIV6AI|attacks|auto|player=" .. tostring(owner) .. "|turn=" .. tostring(turn)
      .. "|unit=" .. tostring(unitOk) .. "|city=" .. tostring(cityOk) .. "|skipped=" .. tostring(skipped)
    if skipWhy ~= nil and tostring(skipWhy) ~= "" then
      line = line .. "|why=" .. tostring(skipWhy)
    end
    print(line)
  end
end

-- Play one seat's orders with retry passes and record each result, then end
-- the turn of the seat's units the model left in place.
function Civ6Ai_Orders._ApplyOrders(sender, owner, orders, autoMode)
  if Game.GetCurrentGameTurn() == 1 then
    for _, o in ipairs(orders) do
      local unit = o.U ~= nil and Civ6Ai_Orders._Unit(owner, o.U) or nil
      if unit ~= nil and (call(unit, "GetMovesRemaining") or 0) <= 0 and UnitManager.RestoreMovement ~= nil then
        pcall(UnitManager.RestoreMovement, unit)
      end
    end
  end
  local hints
  hints, orders = Civ6Ai_Orders._SplitHints(sender, orders)
  orders = Civ6Ai_Orders._SetupMovesFirst(Civ6Ai_Orders._AttacksBeforeMoves(orders))
  -- The one record of what the model ran: written only on a successful dispatch.
  local handled = Civ6Ai_Orders._NewHandled()
  local function markModel(o, reason)
    local class, id = Civ6Ai_Orders._OrderEntity(o)
    if class == nil then
      return
    end
    Civ6Ai_Orders._MarkHandled(handled, class, id, o.K)
    Civ6Ai_Orders._LogOrderSource(owner, "model", o.K, class, id, reason)
  end
  for _, o in ipairs(orders) do
    if o.U ~= nil and o.U >= 0 then
      Civ6Ai_Orders._ClearGoal(owner, o.U)
    end
  end
  local pending = orders
  local cityStrikeFailed = false
  local attackOk, attackFailed = {}, {}
  local moveOk, moveFailed = {}, {}
  local function markMove(o, succeeded)
    if o.U == nil or o.K ~= Civ6Ai_Orders.K.MOVE then
      return
    end
    if succeeded then
      moveOk[o.U] = true
      moveFailed[o.U] = nil
    elseif not moveOk[o.U] then
      moveFailed[o.U] = true
    end
  end
  local function markAttack(o, succeeded, reason)
    if o.U == nil then
      return
    end
    local text = tostring(reason or "")
    local attackish = o.K == Civ6Ai_Orders.K.ATTACK
    if o.K == Civ6Ai_Orders.K.MOVE
        and (string.find(text, "attack_instead:", 1, true) or string.find(text, "enemy_on_tile:", 1, true)) then
      attackish = true
    end
    if not attackish then
      return
    end
    if succeeded then
      attackOk[o.U] = true
      attackFailed[o.U] = nil
    elseif not attackOk[o.U] then
      attackFailed[o.U] = true
    end
  end
  local counts = { ok = { unit = 0, city = 0 }, fail = { unit = 0, city = 0 } }
  for pass = 1, Civ6Ai_Orders.MAX_PASSES do
    if #pending == 0 then
      break
    end
    local nextPending, progress = {}, false
    for _, o in ipairs(pending) do
      -- A city strike that fails is not followed by the rest of the strike
      -- list. The first refusal is the result; later strikes are not sent.
      if o.K == Civ6Ai_Orders.K.CITY_STRIKE and cityStrikeFailed then
        Civ6Ai_Orders._Record(sender, o, false, "city_strike_stopped")
        noteAttack(counts, o, false)
      else
      -- One order's script error is that order's result. It must not abort the
      -- rest of the turn (a thrown city:GetDistrictID used to do that).
      local ran, ok, reason = pcall(Civ6Ai_Orders._Execute, sender, o)
      if not ran then
        ok, reason = false, "order_error:" .. trimErr(ok)
      end
      if o.K == Civ6Ai_Orders.K.CITY_STRIKE and not ok then
        cityStrikeFailed = true
      end
      if ok then
        progress = true
        markMove(o, true)
        markAttack(o, true, reason)
        markModel(o, reason)
        Civ6Ai_Orders._Record(sender, o, true, reason, "model")
        noteAttack(counts, o, true)
      elseif retryable(o.K, reason) and pass < Civ6Ai_Orders.MAX_PASSES then
        nextPending[#nextPending + 1] = o
      else
        markMove(o, false)
        markAttack(o, false, reason)
        Civ6Ai_Orders._Record(sender, o, false, reason)
        noteAttack(counts, o, false)
      end
      end
    end
    if not progress then
      for _, o in ipairs(nextPending) do
        local unit = Civ6Ai_Orders._Unit(owner, o.U)
        local moveSucceeded = false
        if o.K == Civ6Ai_Orders.K.MOVE and unit ~= nil then
          local nx, ny = Civ6Ai_Orders._RetargetPlot(owner, unit, o.X, o.Y)
          local recorded = false
          local lastWhy = nil
          if nx ~= nil then
            local ran, rok, rreason = pcall(Civ6Ai_Orders._MoveOnce, owner, o.U, nx, ny)
            if not ran then
              Civ6Ai_Orders._Record(sender, o, false, "order_error:" .. trimErr(rok))
              recorded = true
            elseif rok == true then
              moveSucceeded = true
              recorded = true
              markModel(o, rreason)
              Civ6Ai_Orders._Record(sender, o, true, "retargeted:"
                .. tostring(o.X) .. "," .. tostring(o.Y) .. ">" .. tostring(nx) .. "," .. tostring(ny)
                .. ":" .. tostring(rreason), "model")
            else
              lastWhy = rreason
            end
          end
          -- The destination's ring is full (stack_limit). Step toward a free tile.
          if not recorded then
            unit = Civ6Ai_Orders._Unit(owner, o.U)
            local sx, sy = unit ~= nil and Civ6Ai_Orders._StepToward(owner, unit, o.X, o.Y) or nil
            if sx ~= nil and not (sx == nx and sy == ny) then
              local ran, rok, rreason = pcall(Civ6Ai_Orders._MoveOnce, owner, o.U, sx, sy)
              if not ran then
                Civ6Ai_Orders._Record(sender, o, false, "order_error:" .. trimErr(rok))
                recorded = true
              elseif rok == true then
                moveSucceeded = true
                recorded = true
                markModel(o, rreason)
                Civ6Ai_Orders._Record(sender, o, true, "step_toward:" .. tostring(o.X) .. "," .. tostring(o.Y)
                  .. ">" .. tostring(sx) .. "," .. tostring(sy) .. ":" .. tostring(rreason), "model")
              else
                lastWhy = rreason
              end
            end
          end
          if not recorded then
            local why = "plot_occupied_exhausted"
            if nx ~= nil then
              why = why .. ":" .. tostring(o.X) .. "," .. tostring(o.Y) .. ">" .. tostring(nx) .. "," .. tostring(ny)
                .. ":" .. tostring(lastWhy)
            end
            Civ6Ai_Orders._Record(sender, o, false, why)
          end
        else
          Civ6Ai_Orders._Record(sender, o, false, "plot_occupied_exhausted")
        end
        markMove(o, moveSucceeded)
        markAttack(o, false)
        noteAttack(counts, o, false)
      end
      break
    end
    pending = nextPending
  end
  local executed = counts.ok.unit + counts.ok.city
  local failed = counts.fail.unit + counts.fail.city
  Civ6Ai_Orders._LogAttackBatch(
    owner, Game.GetCurrentGameTurn(), executed, failed, nil, counts.ok.unit, counts.ok.city)
  -- After the model's orders, then finish-moves. Empty queues never reach
  -- here, so a seat the model did not answer stays with the game's AI.
  local ranAuto, autoErr = pcall(
    Civ6Ai_Orders._RunHostFallbacks, sender, owner, handled, autoMode, hints)
  if not ranAuto then
    log("auto_error|player=" .. tostring(owner) .. "|" .. trimErr(autoErr))
  end
  Civ6Ai_Orders._FinishIdleUnits(owner, handled)
end

-- Units the model commands. Traders and religious units stay with the game's
-- AI until this file applies an order (or a standing goal) for them. Builders
-- stay with it unless this file applies an improve order.
function Civ6Ai_Orders._ModelCommandsUnit(unit, ordered)
  local info = GameInfo.Units[unit:GetType()]
  if info == nil then
    return false
  end
  local builder = (num(info.BuildCharges) or 0) > 0
  local trader = info.MakeTradeRoute == true
  local religious = (num(info.ReligiousStrength) or 0) > 0
  -- Great people stay with the game's own AI. Activate is a UI action and
  -- does not exist in this script, so finishing their moves would idle them.
  local great = (info.GreatPersonClassType ~= nil and info.GreatPersonClassType ~= "")
    or (info.UnitType ~= nil and string.find(info.UnitType, "GREAT_", 1, true) ~= nil)
  if builder or trader or religious or great then
    if ordered ~= nil and ordered[unit:GetID()] then
      return true
    end
    return Civ6Ai_Orders._ReadGoal(unit:GetOwner(), unit:GetID()) ~= nil
  end
  return true
end

-- An AI seat's model-commanded units end their turn after its orders, so the
-- game's AI cannot override a unit the model (or a host fallback / standing
-- goal) handled successfully. A unit still without a successful order after
-- the reply and the sidecar's coverage repair goes to the game's own AI the
-- same turn (as Civ 5 leaves leftovers to the Community Patch AI); it used to
-- be held for two idle turns, which piled new units up in the capital.
-- handled == nil (T1 dump, no orders yet): every unit ends its moves, as before.
-- A human seat finishes its own units.
function Civ6Ai_Orders._FinishIdleUnits(owner, handled)
  local p = Players[owner]
  if p == nil or call(p, "IsHuman") then
    return 0
  end
  local ran = handled ~= nil and handled.unit or nil
  local count, native = 0, 0
  for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
    if (call(u, "GetMovesRemaining") or 0) > 0 and Civ6Ai_Orders._ModelCommandsUnit(u, ran) then
      local done = ran ~= nil and ran[u:GetID()] or nil
      local held = ran == nil or (done ~= nil and done ~= false)
        or Civ6Ai_Orders._ReadGoal(owner, u:GetID()) ~= nil
      if not held then
        native = native + 1
      elseif pcall(UnitManager.FinishMoves, u) then
        count = count + 1
      end
    end
  end
  log("finish_idle|player=" .. tostring(owner) .. "|units=" .. count .. "|native=" .. native)
  return count
end

-- A standing goal for units no order handled (turn-start paths with no queue).
function Civ6Ai_Orders._ContinueGoals(owner, handled)
  local p = Players[owner]
  if p == nil then
    return 0
  end
  local n = 0
  for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
    if not Civ6Ai_Orders._WasHandled(handled, "unit", u:GetID())
        and Civ6Ai_Orders._ReadGoal(owner, u:GetID()) ~= nil then
      n = n + 1
      Civ6Ai_Orders._ContinueGoal(owner, u)
    end
  end
  if n > 0 then
    log("goals_continue|player=" .. tostring(owner) .. "|units=" .. n)
  end
  return n
end

-- One unit's standing goal: step toward it, act on arrival. True when the move ran.
function Civ6Ai_Orders._ContinueGoal(owner, u)
  local turn = Game.GetCurrentGameTurn()
  local uid = u:GetID()
  local goal = Civ6Ai_Orders._ReadGoal(owner, uid)
  if goal == nil then
    return false
  end
  if turn - (goal.setTurn or 0) >= Civ6Ai_Orders.GOAL_MAX_AGE then
    Civ6Ai_Orders._ClearGoal(owner, uid)
    log("goal_expired|player=" .. tostring(owner) .. "|unit=" .. tostring(uid))
    return false
  end
  local ran, ok, reason = pcall(Civ6Ai_Orders._MoveWithRetarget, owner, u, goal.x, goal.y)
  if not ran then
    log("goal_error|player=" .. tostring(owner) .. "|unit=" .. tostring(uid) .. "|" .. trimErr(ok))
    Civ6Ai_Orders._ClearGoal(owner, uid)
    return false
  end
  u = Civ6Ai_Orders._Unit(owner, uid)
  if u == nil then
    Civ6Ai_Orders._ClearGoal(owner, uid)
  elseif u:GetX() == goal.x and u:GetY() == goal.y then
    local aRan, aok, awhy = pcall(Civ6Ai_Orders._ArrivalAction, owner, u, goal.intent, goal)
    if not aRan then
      aok, awhy = false, "order_error:" .. trimErr(aok)
    end
    log("goal_arrive|player=" .. tostring(owner) .. "|unit=" .. tostring(uid)
      .. "|ok=" .. tostring(aok) .. "|reason=" .. tostring(awhy))
    Civ6Ai_Orders._ClearGoal(owner, uid)
    local shared = Civ6Ai_Orders._Shared()
    shared.OrderResults = shared.OrderResults or {}
    table.insert(shared.OrderResults, {
      sender = -1, seq = -1, kind = Civ6Ai_Orders.K.MOVE, player = owner, unit = uid,
      turn = turn, decision_turn = goal.setTurn, apply_turn = turn,
      ok = aok, reason = "goal_arrive:" .. tostring(awhy),
    })
  elseif not ok and not Civ6Ai_Orders._OccupiedReason(reason) then
    log("goal_drop|player=" .. tostring(owner) .. "|unit=" .. tostring(uid)
      .. "|reason=" .. tostring(reason))
    Civ6Ai_Orders._ClearGoal(owner, uid)
  end
  return ok == true
end

-- Every unit with movement left. Used when a managed AI seat has dumped its
-- snapshot: the model's orders play next turn, and this turn must actually
-- end. In a network game the local-player swap that requests ENDTURN is not
-- used, so leftover movement (a settler still "needs orders") is what keeps
-- the seat's portrait up and blocks every other player on simultaneous T1.
function Civ6Ai_Orders._FinishAllMoves(owner)
  local p = Players[owner]
  if p == nil then
    return 0
  end
  local count = 0
  for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
    if (call(u, "GetMovesRemaining") or 0) > 0 and pcall(UnitManager.FinishMoves, u) then
      count = count + 1
    end
  end
  log("finish_all|player=" .. tostring(owner) .. "|units=" .. count)
  return count
end

-- ---------------------------------------------------------------------------
-- Order queue: one seat's orders for one turn, in synced game properties
-- ---------------------------------------------------------------------------
local function qkey(owner, name)
  return "CIV6AI_Q_" .. tostring(owner) .. "_" .. name
end

function Civ6Ai_Orders._StartedTurn(owner)
  return num(Game:GetProperty("CIV6AI_STARTED_" .. tostring(owner))) or -1
end

function Civ6Ai_Orders._LogAttackBatch(owner, turn, executed, failed, reason, unitOk, cityOk)
  if (executed or 0) + (failed or 0) <= 0 then
    return
  end
  local line = "CIV6AI|attacks|player=" .. tostring(owner) .. "|turn=" .. tostring(turn)
    .. "|executed=" .. tostring(executed or 0) .. "|failed=" .. tostring(failed or 0)
  if unitOk ~= nil then
    line = line .. "|unit=" .. tostring(unitOk) .. "|city=" .. tostring(cityOk or 0)
  end
  if reason ~= nil and reason ~= "" then
    line = line .. "|reason=" .. tostring(reason)
  end
  print(line)
end

-- A second batch for this seat replaces a queue that has not run yet. Record
-- the replaced orders, or an attack in the old batch vanishes with no result.
function Civ6Ai_Orders._DropUnplayedQueue(owner)
  local oldT = num(Game:GetProperty(qkey(owner, "T")))
  if oldT == nil or oldT < 0 then
    return
  end
  local sender = num(Game:GetProperty(qkey(owner, "FROM"))) or -1
  local n = num(Game:GetProperty(qkey(owner, "N"))) or 0
  local attacks = 0
  for j = 1, n do
    local o = { P = owner }
    for _, f in ipairs(Civ6Ai_Orders.QUEUE_FIELDS) do
      o[f] = num(Game:GetProperty(qkey(owner, j .. "_" .. f)))
    end
    if o.K == Civ6Ai_Orders.K.ATTACK or o.K == Civ6Ai_Orders.K.CITY_STRIKE then
      attacks = attacks + 1
    end
    Civ6Ai_Orders._Record(sender, o, false, "queue_replaced:" .. tostring(oldT))
  end
  Civ6Ai_Orders._LogAttackBatch(owner, oldT, 0, attacks, "queue_replaced")
  log("queue_replaced|player=" .. tostring(owner) .. "|old_turn=" .. tostring(oldT) .. "|orders=" .. tostring(n)
    .. "|started=" .. tostring(Civ6Ai_Orders._StartedTurn(owner)) .. "|game_turn=" .. tostring(Game.GetCurrentGameTurn())
    .. "|active=" .. tostring(call(Players[owner], "IsTurnActive")))
end

-- Order identity inside one seat-turn queue: a later order for the same unit
-- and kind (or the same empire-level kind and target) supersedes the earlier one.
local function orderKey(o)
  if o.U ~= nil and o.U >= 0 then
    return "U" .. tostring(o.U) .. ":" .. tostring(o.K) .. ":" .. tostring(o.A or -1)
  end
  return "K" .. tostring(o.K) .. ":" .. tostring(o.I or -1) .. ":" .. tostring(o.A or -1)
end
Civ6Ai_Orders._OrderKey = orderKey

-- One queue per seat per turn. A second batch for the same turn merges into
-- the queued one (same unit and kind: the newer order wins), so nothing is
-- dropped and the seat's turn still plays exactly one batch.
function Civ6Ai_Orders._MergeQueued(owner, turn, orders)
  local oldT = num(Game:GetProperty(qkey(owner, "T")))
  if oldT == nil or oldT ~= turn then
    return orders, false
  end
  local merged, at = {}, {}
  for j = 1, num(Game:GetProperty(qkey(owner, "N"))) or 0 do
    local o = { P = owner }
    for _, f in ipairs(Civ6Ai_Orders.QUEUE_FIELDS) do
      o[f] = num(Game:GetProperty(qkey(owner, j .. "_" .. f)))
    end
    merged[#merged + 1] = o
    at[orderKey(o)] = #merged
  end
  for _, o in ipairs(orders) do
    local k = orderKey(o)
    if at[k] ~= nil then
      merged[at[k]] = o
    else
      merged[#merged + 1] = o
      at[k] = #merged
    end
  end
  log("queue_merged|player=" .. tostring(owner) .. "|turn=" .. tostring(turn) .. "|orders=" .. #merged)
  return merged, true
end

function Civ6Ai_Orders._Store(sender, owner, turn, orders, autoMode)
  local mergedOrders, merged = Civ6Ai_Orders._MergeQueued(owner, turn, orders)
  if merged then
    orders = mergedOrders
  else
    Civ6Ai_Orders._DropUnplayedQueue(owner)
  end
  for j, o in ipairs(orders) do
    for _, f in ipairs(Civ6Ai_Orders.QUEUE_FIELDS) do
      Game:SetProperty(qkey(owner, j .. "_" .. f), o[f] or -1)
    end
  end
  Game:SetProperty(qkey(owner, "N"), #orders)
  Game:SetProperty(qkey(owner, "FROM"), sender)
  Game:SetProperty(qkey(owner, "T"), turn)
  -- -1 means the host did not send a mode (AI seats only). 0 is off. 2 includes humans.
  Game:SetProperty(qkey(owner, "AR"), autoMode == nil and -1 or autoMode)
  log("queued|player=" .. tostring(owner) .. "|for_turn=" .. tostring(turn) .. "|orders=" .. #orders
    .. "|from=" .. tostring(sender))
end

-- Remove and return the seat's queue: turn, sender, orders (nil when empty).
function Civ6Ai_Orders._Take(owner)
  local turn = num(Game:GetProperty(qkey(owner, "T")))
  if turn == nil or turn < 0 then
    return nil
  end
  local orders = {}
  for j = 1, num(Game:GetProperty(qkey(owner, "N"))) or 0 do
    local o = { P = owner }
    for _, f in ipairs(Civ6Ai_Orders.QUEUE_FIELDS) do
      o[f] = num(Game:GetProperty(qkey(owner, j .. "_" .. f)))
    end
    orders[j] = o
  end
  local autoMode = num(Game:GetProperty(qkey(owner, "AR")))
  if autoMode ~= nil and autoMode < 0 then
    autoMode = nil
  end
  Game:SetProperty(qkey(owner, "T"), -1)
  Game:SetProperty(qkey(owner, "AR"), -1)
  return turn, num(Game:GetProperty(qkey(owner, "FROM"))), orders, autoMode
end

-- A complete batch: the sender's orders for one seat's turn T. Queued until
-- the seat's turn T starts. When that turn has already started, the orders run
-- at once while the seat still has its turn, and are dropped otherwise.
function Civ6Ai_Orders._Deliver(sender, batch)
  local orders = {}
  for j = 1, batch.n do
    if batch.orders[j] ~= nil then
      orders[#orders + 1] = batch.orders[j]
    else
      Civ6Ai_Orders._Record(sender, { S = -1, K = 0, P = batch.p }, false, "batch_order_missing:" .. j)
    end
  end
  local owner, t, turn = batch.p, batch.t, Game.GetCurrentGameTurn()
  local started = t ~= nil and Civ6Ai_Orders._StartedTurn(owner) >= t
  local why = Civ6Ai_Orders._Authorize(sender, owner)
  if why == nil and (t == nil or t < turn or t > turn + 1) then
    why = "stale_turn:" .. tostring(t)
  elseif why == nil and started and t ~= turn
      and call(Players[owner], "IsTurnActive") ~= true then
    why = "seat_turn_over:" .. tostring(t)
  end
  if why ~= nil then
    local attacks = 0
    for _, o in ipairs(orders) do
      Civ6Ai_Orders._Record(sender, o, false, why)
      if o.K == Civ6Ai_Orders.K.ATTACK or o.K == Civ6Ai_Orders.K.CITY_STRIKE then
        attacks = attacks + 1
      end
    end
    -- Refused before _ApplyOrders, so the executed summary would otherwise be missing.
    Civ6Ai_Orders._LogAttackBatch(owner, t or turn, 0, attacks, why)
    return
  end
  if started then
    log("late_batch|player=" .. tostring(owner) .. "|turn=" .. tostring(t))
    Civ6Ai_Orders._ApplyOrders(sender, owner, orders, batch.auto)
    return
  end
  Civ6Ai_Orders._Store(sender, owner, t, orders, batch.auto)
end

-- A seat's turn start, on every PC: note it, then play the seat's queue for
-- this turn (none: the game's own AI plays the seat). Movement is restored by
-- now and the game's AI has not moved yet.
function Civ6Ai_Orders.OnPlayerTurnStartComplete(owner)
  local turn = Game.GetCurrentGameTurn()
  log("turn_start|player=" .. tostring(owner) .. "|turn=" .. tostring(turn))
  Game:SetProperty("CIV6AI_STARTED_" .. tostring(owner), turn)
  pcall(Civ6Ai_Orders.ApplyEarlyLock, owner)
  local t, sender, orders, autoMode = Civ6Ai_Orders._Take(owner)
  if t == turn then
    log("queue_apply|player=" .. tostring(owner) .. "|turn=" .. turn .. "|orders=" .. #orders)
    Civ6Ai_Orders._LogQueueUnits(owner, turn)
    Civ6Ai_Orders._ApplyOrders(sender, owner, orders, autoMode)
  elseif t ~= nil then
    local attacks = 0
    local why = "stale_turn:" .. tostring(t)
    for _, o in ipairs(orders) do
      Civ6Ai_Orders._Record(sender, o, false, why)
      if o.K == Civ6Ai_Orders.K.ATTACK or o.K == Civ6Ai_Orders.K.CITY_STRIKE then
        attacks = attacks + 1
      end
    end
    Civ6Ai_Orders._LogAttackBatch(owner, t, 0, attacks, why)
    Civ6Ai_Orders._ContinueGoals(owner, nil)
  elseif turn == 1 and not call(Players[owner], "IsHuman") then
    Civ6Ai_Orders._FinishIdleUnits(owner, nil)
  else
    Civ6Ai_Orders._ContinueGoals(owner, nil)
  end
  pcall(Civ6Ai_Orders.HoldFortified, owner)
end

-- Log-only (no game state): the seat's model-commanded units as the queue is
-- about to run, so the log shows whether the game's AI moved any of them first
-- (moves below full) and where they stand compared with the seat's snapshot.
function Civ6Ai_Orders._LogQueueUnits(owner, turn)
  local p = Players[owner]
  if p == nil then
    return
  end
  local total, partial, parts = 0, 0, {}
  for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
    if Civ6Ai_Orders._ModelCommandsUnit(u) then
      local moves = call(u, "GetMovesRemaining") or 0
      local maxMoves = call(u, "GetMaxMoves") or 0
      total = total + 1
      if moves < maxMoves then
        partial = partial + 1
      end
      parts[#parts + 1] = tostring(u:GetID()) .. "@" .. tostring(u:GetX()) .. "," .. tostring(u:GetY())
        .. ":" .. tostring(moves) .. "/" .. tostring(maxMoves)
    end
  end
  log("queue_units|player=" .. tostring(owner) .. "|turn=" .. tostring(turn) .. "|units=" .. total
    .. "|below_full=" .. partial .. "|list=" .. table.concat(parts, ";"))
end

-- Tell the interface the seat's turn has started (after its queue ran, so the
-- snapshot sees the result). The local seat's LocalPlayerTurnBegin fires
-- earlier, so its pulse waits for the TurnStartComplete mark (Civ6Ai_InGame).
-- A turn-start script error, kept by turn so a later timeout can tell the model
-- the real message. Local bookkeeping on ExposedMembers, same path as OrderResults.
function Civ6Ai_Orders._NoteTurnStartError(owner, err)
  local shared = Civ6Ai_Orders._Shared()
  shared.TurnStartErrors = shared.TurnStartErrors or {}
  local byTurn = shared.TurnStartErrors[owner]
  if type(byTurn) ~= "table" then
    byTurn = {}
    shared.TurnStartErrors[owner] = byTurn
  end
  local turn = Game.GetCurrentGameTurn()
  byTurn[turn] = trimErr(err)
  for _, t in ipairs(sortedKeys(byTurn)) do
    if type(t) == "number" and t < turn - 3 then
      byTurn[t] = nil
    end
  end
end

function Civ6Ai_Orders._PublishTurnStart(owner)
  local shared = Civ6Ai_Orders._Shared()
  shared.TurnStartComplete = shared.TurnStartComplete or {}
  shared.TurnStartComplete[owner] = Game.GetCurrentGameTurn()
  if LuaEvents ~= nil and LuaEvents.Civ6Ai_PlayerTurnStartComplete ~= nil then
    LuaEvents.Civ6Ai_PlayerTurnStartComplete(owner)
  end
end

-- ---------------------------------------------------------------------------
-- Results and running hash (local bookkeeping)
-- ---------------------------------------------------------------------------
local function mixString(h, s)
  s = tostring(s)
  for i = 1, #s do
    h = (h * 31 + string.byte(s, i)) % 2147483629
  end
  return h
end

-- Unread results stay until the UI drain marks them. Only a very long unread
-- backlog drops the oldest, and that drop is logged.
Civ6Ai_Orders.RESULT_CAP = 2048

function Civ6Ai_Orders._TrimResults(shared)
  local results = shared.OrderResults or {}
  local unread = {}
  for _, r in ipairs(results) do
    if not r._taken then
      unread[#unread + 1] = r
    end
  end
  local drop = #unread - Civ6Ai_Orders.RESULT_CAP
  if drop < 0 then
    drop = 0
  end
  local kept = {}
  for i, r in ipairs(unread) do
    if i <= drop then
      log("result_evicted|seq=" .. tostring(r.seq) .. "|kind=" .. tostring(r.kind)
        .. "|player=" .. tostring(r.player) .. "|turn=" .. tostring(r.turn))
    else
      kept[#kept + 1] = r
    end
  end
  shared.OrderResults = kept
end

function Civ6Ai_Orders._Record(sender, o, ok, reason, source)
  source = source or "model"
  local shared = Civ6Ai_Orders._Shared()
  local turn = Game.GetCurrentGameTurn()
  shared.OrderHash = mixString(shared.OrderHash or 7, table.concat({
    tostring(turn), tostring(sender), tostring(o.S), tostring(o.K), tostring(ok), tostring(reason or "") }, "|"))
  shared.OrderCount = (shared.OrderCount or 0) + 1
  shared.OrderResults = shared.OrderResults or {}
  table.insert(shared.OrderResults, {
    sender = sender, seq = o.S, kind = o.K, player = o.P, unit = o.U, turn = turn,
    apply_turn = turn, decision_turn = o.D ~= nil and o.D >= 0 and o.D or turn,
    ok = ok, reason = tostring(reason or ""), source = source,
  })
  -- Moves are recorded before later attacks. Dropping the oldest unread row
  -- made those moves time out as no_result_from_gameplay. Taken rows go first.
  Civ6Ai_Orders._TrimResults(shared)
  log("result|turn=" .. turn .. "|from=" .. tostring(sender) .. "|seq=" .. tostring(o.S) .. "|kind=" .. tostring(o.K)
    .. "|player=" .. tostring(o.P) .. "|unit=" .. tostring(o.U) .. "|ok=" .. tostring(ok)
    .. "|source=" .. tostring(source)
    .. "|reason=" .. tostring(reason or "") .. "|hash=" .. tostring(shared.OrderHash))
end

-- ---------------------------------------------------------------------------
-- Checksum of synced state
-- ---------------------------------------------------------------------------
-- Every living player's gold, research and civic (with progress), every
-- unit's position, moves, damage and experience, every city's size, current
-- production and its progress, and every owned plot's owner and improvement.
function Civ6Ai_Orders.Checksum()
  local h = 7
  local units = 0
  local function mix(v)
    if type(v) == "string" then
      h = mixString(h, v)
      return
    end
    local n = math.floor((tonumber(v) or 0) * 100 + 0.5)
    h = (h * 31 + n) % 2147483629
  end
  for id = 0, 63 do
    local p = Players[id]
    if p ~= nil and call(p, "IsAlive") then
      mix(id)
      mix(call(call(p, "GetTreasury"), "GetGoldBalance"))
      local techs = call(p, "GetTechs")
      local tech = call(techs, "GetResearchingTech")
      mix(tech)
      if tech ~= nil and tech >= 0 then
        mix(call(techs, "GetResearchProgress", tech))
      end
      local culture = call(p, "GetCulture")
      local civic = call(culture, "GetProgressingCivic")
      mix(civic)
      if civic ~= nil and civic >= 0 then
        mix(call(culture, "GetCulturalProgress", civic))
      end
      for _, u in ipairs(sortedMembers(call(p, "GetUnits"))) do
        mix(u:GetID())
        mix(u:GetX())
        mix(u:GetY())
        mix(call(u, "GetMovesRemaining"))
        mix(call(u, "GetDamage"))
        mix(call(call(u, "GetExperience"), "GetExperiencePoints"))
        units = units + 1
      end
      for _, c in ipairs(sortedMembers(call(p, "GetCities"))) do
        mix(c:GetID())
        mix(call(c, "GetPopulation"))
        local q = call(c, "GetBuildQueue")
        mix(tostring(call(q, "CurrentlyBuilding")))
        mix(call(q, "GetProductionProgress"))
      end
    end
  end
  if Map ~= nil and Map.GetPlotCount ~= nil and Map.GetPlotByIndex ~= nil then
    local count = Map.GetPlotCount() or 0
    for i = 0, count - 1 do
      local plot = Map.GetPlotByIndex(i)
      local owner = call(plot, "GetOwner") or -1
      local imp = call(plot, "GetImprovementType") or -1
      if owner >= 0 or imp >= 0 then
        mix(i)
        mix(owner)
        mix(imp)
      end
    end
  end
  return h, units
end

function Civ6Ai_Orders._FlushOpenBatches(turn)
  -- An order whose batch never closed (the last send never arrived) has no
  -- gameplay result, so the UI reports no_result_from_gameplay. Deliver it
  -- once its turn has passed: received orders get a real result.
  local senders = {}
  for sender, cur in pairs(Civ6Ai_Orders._batches) do
    if cur ~= nil and cur.t ~= nil and cur.t < turn then
      senders[#senders + 1] = sender
    end
  end
  table.sort(senders)
  for _, sender in ipairs(senders) do
    local cur = Civ6Ai_Orders._batches[sender]
    if cur ~= nil then
      Civ6Ai_Orders._batches[sender] = nil
      log("batch_flush|from=" .. tostring(sender) .. "|batch=" .. tostring(cur.id)
        .. "|for_turn=" .. tostring(cur.t))
      Civ6Ai_Orders._Deliver(sender, cur)
    end
  end
end

function Civ6Ai_Orders.OnGameTurnStarted(turn)
  Civ6Ai_Orders._FlushOpenBatches(turn)
  local h, n = Civ6Ai_Orders.Checksum()
  local shared = Civ6Ai_Orders._Shared()
  shared.Checksums = shared.Checksums or {}
  shared.Checksums[turn] = { sum = h, orders = shared.OrderHash or 7, count = shared.OrderCount or 0 }
  shared.Checksums[turn - 20] = nil
  log("turn|turn=" .. tostring(turn) .. "|sum=" .. tostring(h) .. "|units=" .. tostring(n)
    .. "|order_hash=" .. tostring(shared.OrderHash or 7) .. "|order_count=" .. tostring(shared.OrderCount or 0))
end

-- A PC's report of its own checksum for turn T. Every PC compares it with its
-- own value and logs the verdict, so the host's log alone shows whether the
-- friend's game still matches. The verdict is never written to game state.
function Civ6Ai_Orders._Report(sender, params)
  local t = num(params.T)
  local shared = Civ6Ai_Orders._Shared()
  local mine = shared.Checksums ~= nil and shared.Checksums[t] or nil
  local verdict
  if mine == nil then
    verdict = "no_local_value"
  else
    local sumOk = mine.sum == num(params.H)
    local ordersOk = mine.orders == num(params.R) and mine.count == num(params.Q)
    verdict = (sumOk and ordersOk) and "match" or ("MISMATCH:sum=" .. tostring(sumOk) .. ":orders=" .. tostring(ordersOk))
  end
  shared.SyncReports = shared.SyncReports or {}
  shared.SyncReports[sender] = { turn = t, verdict = verdict }
  log("sync|turn=" .. tostring(t) .. "|from=" .. tostring(sender) .. "|their_sum=" .. tostring(params.H)
    .. "|my_sum=" .. tostring(mine and mine.sum) .. "|their_orders=" .. tostring(params.R) .. "/" .. tostring(params.Q)
    .. "|my_orders=" .. tostring(mine and mine.orders) .. "/" .. tostring(mine and mine.count) .. "|verdict=" .. verdict)
end

-- ---------------------------------------------------------------------------
-- Entry point
-- ---------------------------------------------------------------------------
local function readOrder(params)
  return {
    K = num(params.K), P = num(params.P), U = num(params.U), X = num(params.X), Y = num(params.Y),
    I = num(params.I), V = num(params.V), W = num(params.W), S = num(params.S) or -1,
    G = num(params.G), A = num(params.A), I2 = num(params.I2), I3 = num(params.I3),
    D = num(params.D),
  }
end

function Civ6Ai_Orders.OnOrder(sender, params)
  params = params or {}
  local turn = Game.GetCurrentGameTurn()
  local o = readOrder(params)
  local k = o.K
  if k == Civ6Ai_Orders.K.REPORT then
    Civ6Ai_Orders._Report(sender, params)
    return
  end
  if k == Civ6Ai_Orders.K.FINISH_SEAT then
    local why = Civ6Ai_Orders._Authorize(sender, o.P)
    if why ~= nil then
      Civ6Ai_Orders._Record(sender, o, false, why)
      return
    end
    local n = Civ6Ai_Orders._FinishAllMoves(o.P)
    Civ6Ai_Orders._Record(sender, o, true, "finish_seat=" .. n)
    return
  end
  if params.B ~= nil and Civ6Ai_Orders.DECISION_KINDS[k] then
    Civ6Ai_Orders._Batch(sender, o, params)
  elseif num(params.T) ~= turn then
    local why = "stale_turn:" .. tostring(params.T)
    Civ6Ai_Orders._Record(sender, o, false, why)
    if k == Civ6Ai_Orders.K.ATTACK or k == Civ6Ai_Orders.K.CITY_STRIKE then
      Civ6Ai_Orders._LogAttackBatch(o.P, params.T or turn, 0, 1, why)
    end
  elseif Civ6Ai_Orders.DECISION_KINDS[k] then
    local ok, reason = Civ6Ai_Orders._Execute(sender, o)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  elseif k == Civ6Ai_Orders.K.PING then
    local n = (num(Game:GetProperty("CIV6AI_PINGS")) or 0) + 1
    Game:SetProperty("CIV6AI_PINGS", n)
    Civ6Ai_Orders._Record(sender, o, true, "pings=" .. n)
  elseif k ~= nil and k >= Civ6Ai_Orders.K.TEST_MODE then
    local ok, reason = Civ6Ai_Orders.RunTest(sender, o, params)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  else
    Civ6Ai_Orders._Record(sender, o, false, "unknown_kind")
  end
  Game:SetProperty("CIV6AI_LAST_SEQ_" .. tostring(sender), o.S)
end

-- Collect one batch per sender (orders arrive one operation each) and deliver
-- it when its last order arrives. A new batch id before the old one completed
-- delivers the old one as it is.
function Civ6Ai_Orders._Batch(sender, o, params)
  local b, j, n, t = num(params.B), num(params.J), num(params.N), num(params.T)
  if j == nil or n == nil or n < 1 or j < 1 or j > n then
    j, n = 1, 1
  end
  local cur = Civ6Ai_Orders._batches[sender]
  if cur ~= nil and cur.id ~= b then
    log("batch_abandoned|from=" .. tostring(sender) .. "|batch=" .. tostring(cur.id))
    Civ6Ai_Orders._batches[sender] = nil
    Civ6Ai_Orders._Deliver(sender, cur)
    cur = nil
  end
  if cur == nil then
    cur = { id = b, n = n, p = o.P, t = t, orders = {}, auto = num(params.AR) }
    Civ6Ai_Orders._batches[sender] = cur
  elseif cur.auto == nil then
    cur.auto = num(params.AR)
  end
  cur.orders[j] = o
  if j == n then
    Civ6Ai_Orders._batches[sender] = nil
    Civ6Ai_Orders._Deliver(sender, cur)
  end
end

-- ---------------------------------------------------------------------------
-- Governance orders: government, policy slots, pantheon, religion, great
-- people. One gameplay function per command; the host's direct route (single
-- player) calls them through ExposedMembers.Civ6Ai.Gov, the synced channel
-- (network game) through OnOrder. Each returns ok, reason; a failure reason is
-- plain language because it goes straight back to the model.
--
-- Gameplay-script API used (Firaxis scenario scripts and the gameplay API
-- survey): PlayerCulture:IsGovernmentUnlocked/SetCurrentGovernment/
-- CivicCompletedThisTurn/GetNumPolicySlots/GetSlotPolicy/ClearPolicySlot/
-- IsPolicyUnlocked/IsPolicyActive, Game.GetReligion():FoundPantheon/
-- FoundReligion/AddBelief/IsInSomePantheon/IsInSomeReligion,
-- PlayerReligion:CanCreatePantheon/GetPantheon/GetReligionTypeCreated/
-- GetFaithBalance/ChangeFaithBalance, Game.GetGreatPeople():GetTimeline/
-- CanRecruitPerson/RecruitPerson/CanPatronizePerson/GetPatronizeCost/
-- GrantPerson. Gameplay scripts have no call that puts a card in a policy slot
-- or appoints/assigns/promotes a governor (those exist only as UI requests
-- for the local player), so those orders report that plainly.
-- ---------------------------------------------------------------------------
Civ6Ai_Orders.Gov = Civ6Ai_Orders.Gov or {}
local Gov = Civ6Ai_Orders.Gov

local function rowName(row, key)
  if row == nil then
    return "?"
  end
  return tostring(row[key] or row.Name or "?")
end

local function govProp(owner, what)
  return "CIV6AI_GOV_" .. what .. "_" .. tostring(owner)
end

-- A government change: only right after a civic completed (the same rule as
-- the government screen), once per turn, and only to an unlocked government.
function Gov.ChangeGovernment(owner, govIndex)
  local p = Players[owner]
  local culture = call(p, "GetCulture")
  if culture == nil then
    return false, "no culture object for this player"
  end
  local row = govIndex ~= nil and GameInfo.Governments[govIndex] or nil
  if row == nil then
    return false, "unknown government"
  end
  local name = rowName(row, "GovernmentType")
  if call(culture, "IsGovernmentUnlocked", row.Index) ~= true and call(culture, "IsGovernmentUnlocked", row.Hash) ~= true then
    return false, name .. " is not unlocked yet (research the civic that unlocks it first)"
  end
  local current = call(culture, "GetCurrentGovernment")
  if call(culture, "IsInAnarchy") == true or (current ~= nil and current < 0) then
    return false, "you are in anarchy; wait until it ends before changing government"
  end
  if current ~= nil and current == row.Index then
    return false, "you already have " .. name
  end
  local turn = Game.GetCurrentGameTurn()
  if num(Game:GetProperty(govProp(owner, "CHANGED"))) == turn then
    return false, "government was already changed this turn"
  end
  -- A negative current government is anarchy, not "no government yet".
  local fresh = call(culture, "CivicCompletedThisTurn") == true
    or call(culture, "GetCivicCompletedThisTurn") == true
  if not fresh then
    return false, "a government can only be changed on a turn when a civic completed"
  end
  if culture.SetCurrentGovernment == nil then
    return false, "this game has no gameplay route to change government"
  end
  local ok, err = pcall(culture.SetCurrentGovernment, culture, row.Index)
  if not ok then
    return false, "the game refused the change: " .. tostring(err)
  end
  Game:SetProperty(govProp(owner, "CHANGED"), turn)
  local after = call(culture, "GetCurrentGovernment")
  return true, "government=" .. name .. (after ~= nil and (":now=" .. tostring(after)) or "")
end

-- Policy slot orders. X = slot index, I = policy index or -1 to empty the
-- slot. Emptying uses the real ClearPolicySlot; putting a card in needs a
-- gameplay slot call, which the game does not offer (checked at load).
Gov.SLOT_CALLS = { "SlotPolicy", "SetSlotPolicy", "SetPolicyInSlot", "EnactPolicy" }

function Gov.SlotCall(culture)
  for _, name in ipairs(Gov.SLOT_CALLS) do
    if culture ~= nil and culture[name] ~= nil then
      return name
    end
  end
  return nil
end

-- The local seat's attacks use this too. Offers are distance-based; this is
-- the resolver those offers describe (the UI operation check is a different
-- path and rejects them).
function Gov.AttackUnit(owner, unitId, x, y)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "unit_not_found"
  end
  return Civ6Ai_Orders._ResolveAttack(unit, x, y)
end

function Gov.SetPolicySlot(owner, slot, policyIndex)
  local culture = call(Players[owner], "GetCulture")
  if culture == nil then
    return false, "no culture object for this player"
  end
  local slots = call(culture, "GetNumPolicySlots") or 0
  if slot == nil or slot < 0 or slot >= slots then
    return false, "there is no policy slot " .. tostring(slot) .. " (you have " .. tostring(slots) .. ")"
  end
  if policyIndex == nil or policyIndex < 0 then
    if culture.ClearPolicySlot == nil then
      return false, "this game has no gameplay route to empty a policy slot"
    end
    local ok = pcall(culture.ClearPolicySlot, culture, slot)
    return ok, ok and ("slot" .. slot .. "=empty") or "the game refused to empty the slot"
  end
  local row = GameInfo.Policies[policyIndex]
  if row == nil then
    return false, "unknown policy card"
  end
  if call(culture, "IsPolicyUnlocked", row.Index) ~= true and call(culture, "IsPolicyUnlocked", row.Hash) ~= true then
    return false, row.PolicyType .. " is not unlocked yet"
  end
  if call(culture, "GetSlotPolicy", slot) == row.Index then
    return true, "slot" .. slot .. "=" .. row.PolicyType .. ":already"
  end
  local fn = Gov.SlotCall(culture)
  if fn == nil then
    return false, "policy cards cannot be slotted for this seat from a game script "
      .. "(the game only offers that to the local player's screen); the game's own AI keeps choosing its cards"
  end
  local ok, err = pcall(culture[fn], culture, row.Index, slot)
  if not ok or call(culture, "GetSlotPolicy", slot) ~= row.Index then
    return false, "the game refused " .. row.PolicyType .. " in slot " .. slot .. (ok and "" or (": " .. tostring(err)))
  end
  return true, "slot" .. slot .. "=" .. row.PolicyType
end

-- Pantheon: the faith cost is the game's RELIGION_PANTHEON_MIN_FAITH; it is
-- taken from the balance unless the engine call already took it.
function Gov.PantheonCost()
  local row = GameInfo.GlobalParameters ~= nil and GameInfo.GlobalParameters["RELIGION_PANTHEON_MIN_FAITH"] or nil
  return tonumber(row and row.Value) or 25
end

function Gov.FoundPantheon(owner, beliefIndex)
  local p = Players[owner]
  local rel = call(p, "GetReligion")
  local game = Game.GetReligion ~= nil and Game.GetReligion() or nil
  if rel == nil or game == nil then
    return false, "religion objects are not available"
  end
  local belief = beliefIndex ~= nil and GameInfo.Beliefs[beliefIndex] or nil
  if belief == nil then
    return false, "unknown belief"
  end
  if belief.BeliefClassType ~= "BELIEF_CLASS_PANTHEON" then
    return false, belief.BeliefType .. " is not a pantheon belief"
  end
  local have = call(rel, "GetPantheon")
  if have ~= nil and have >= 0 then
    local cur = GameInfo.Beliefs[have]
    return false, "you already have a pantheon (" .. rowName(cur, "BeliefType") .. ")"
  end
  if call(game, "IsInSomePantheon", belief.Index) == true then
    return false, belief.BeliefType .. " was already taken by another civilization"
  end
  local cost = Gov.PantheonCost()
  local faith = call(rel, "GetFaithBalance") or 0
  if faith < cost then
    return false, "a pantheon needs " .. cost .. " faith; you have " .. math.floor(faith)
  end
  if call(rel, "CanCreatePantheon") == false then
    return false, "the game does not allow this civilization to found a pantheon now"
  end
  local ok, err = pcall(game.FoundPantheon, game, owner, belief.Index)
  local after = call(rel, "GetPantheon")
  if not ok or after ~= belief.Index then
    return false, "the game refused the pantheon" .. (ok and "" or (": " .. tostring(err)))
  end
  local faithAfter = call(rel, "GetFaithBalance") or faith
  local charged = faith - faithAfter
  if charged < cost and rel.ChangeFaithBalance ~= nil then
    pcall(rel.ChangeFaithBalance, rel, -(cost - charged))
  end
  return true, "pantheon=" .. belief.BeliefType .. ":faith=" .. math.floor(faith) .. ">" .. math.floor(call(rel, "GetFaithBalance") or 0)
end

-- A Holy Site (or a civilization's replacement for it) at x,y owned by owner.
local function holySiteCity(owner, x, y)
  local plot = Map.GetPlot(x, y)
  if plot == nil or call(plot, "GetOwner") ~= owner then
    return nil
  end
  local d = call(plot, "GetDistrictType")
  local row = d ~= nil and d >= 0 and GameInfo.Districts[d] or nil
  if row == nil then
    return nil
  end
  local isHoly = row.DistrictType == "DISTRICT_HOLY_SITE"
  if not isHoly and GameInfo.DistrictReplaces ~= nil then
    for r in GameInfo.DistrictReplaces() do
      if r.CivUniqueDistrictType == row.DistrictType and r.ReplacesDistrictType == "DISTRICT_HOLY_SITE" then
        isHoly = true
      end
    end
  end
  if not isHoly then
    return nil
  end
  local city = Cities ~= nil and Cities.GetPlotPurchaseCity ~= nil and Cities.GetPlotPurchaseCity(plot) or nil
  if city == nil then
    city = call(plot, "GetWorkingCity")
  end
  return city
end

-- Found a religion with a Great Prophet standing on your Holy Site (the unit
-- is used up), plus one belief of each class that is still free: Founder,
-- Follower, and, when the ruleset has them, Worship and Enhancer.
function Gov.FoundReligion(owner, religionIndex, unitId, ...)
  local p = Players[owner]
  local rel = call(p, "GetReligion")
  local game = Game.GetReligion ~= nil and Game.GetReligion() or nil
  if rel == nil or game == nil then
    return false, "religion objects are not available"
  end
  local made = call(rel, "GetReligionTypeCreated")
  if made ~= nil and made >= 0 then
    return false, "you already founded a religion (" .. rowName(GameInfo.Religions[made], "ReligionType") .. ")"
  end
  local religion = religionIndex ~= nil and GameInfo.Religions[religionIndex] or nil
  if religion == nil or religion.Pantheon == true then
    return false, "unknown religion"
  end
  if call(game, "HasBeenFounded", religion.Index) == true then
    return false, religion.ReligionType .. " was already founded by someone else"
  end
  local unit = unitId ~= nil and unitId >= 0 and Civ6Ai_Orders._Unit(owner, unitId) or nil
  if unit == nil then
    return false, "a religion is founded by a Great Prophet; give the prophet's unit id"
  end
  local urow = GameInfo.Units[unit:GetType()]
  if urow == nil or urow.UnitType ~= "UNIT_GREAT_PROPHET" then
    return false, "that unit is not a Great Prophet"
  end
  local city = holySiteCity(owner, unit:GetX(), unit:GetY())
  if city == nil then
    return false, "the Great Prophet must stand on your own Holy Site district"
  end
  local beliefs, seenClass = {}, {}
  for _, b in ipairs({ ... }) do
    if b ~= nil and b >= 0 then
      local row = GameInfo.Beliefs[b]
      if row == nil or row.BeliefClassType == "BELIEF_CLASS_PANTHEON" then
        return false, "belief " .. tostring(b) .. " is not a religion belief"
      end
      if seenClass[row.BeliefClassType] then
        return false, "pick beliefs of different kinds (one Founder, one Follower, one Worship, one Enhancer)"
      end
      if call(game, "IsInSomeReligion", row.Index) == true then
        return false, row.BeliefType .. " is already used by another religion"
      end
      seenClass[row.BeliefClassType] = true
      beliefs[#beliefs + 1] = row
    end
  end
  local ok, err = pcall(game.FoundReligion, game, owner, religion.Index)
  if not ok or call(rel, "GetReligionTypeCreated") ~= religion.Index then
    return false, "the game refused to found " .. religion.ReligionType .. (ok and "" or (": " .. tostring(err)))
  end
  local added = {}
  for _, row in ipairs(beliefs) do
    if pcall(game.AddBelief, game, owner, row.Index) then
      added[#added + 1] = row.BeliefType
    end
  end
  local holy = pcall(rel.SetHolyCity, rel, city:GetID()) and "holy_city" or "no_holy_city"
  pcall(function() city:GetReligion():SetAllCityToReligion(religion.Index) end)
  pcall(UnitManager.Kill, unit)
  return true, "religion=" .. religion.ReligionType .. ":beliefs=" .. (#added > 0 and table.concat(added, "+") or "none")
    .. ":" .. holy .. ":city=" .. tostring(city:GetName())
end

-- Great people. I = GreatPersonIndividuals index.
local function timelineEntry(gp, individual)
  local ok, list = pcall(gp.GetTimeline, gp)
  if not ok or type(list) ~= "table" then
    return nil
  end
  for _, e in ipairs(list) do
    if e.Individual == individual then
      return e
    end
  end
  return nil
end

function Gov.RecruitGreatPerson(owner, individual)
  local gp = Game.GetGreatPeople ~= nil and Game.GetGreatPeople() or nil
  local row = individual ~= nil and GameInfo.GreatPersonIndividuals[individual] or nil
  if gp == nil or row == nil then
    return false, "unknown great person"
  end
  local entry = timelineEntry(gp, row.Index)
  if entry == nil then
    return false, row.GreatPersonIndividualType .. " is not available right now"
  end
  if call(gp, "CanRecruitPerson", owner, row.Index) ~= true then
    return false, "not enough great person points to recruit " .. row.GreatPersonIndividualType
      .. " (needs " .. tostring(entry.Cost) .. ")"
  end
  local ok, err = pcall(gp.RecruitPerson, gp, owner, row.Index)
  local after = timelineEntry(gp, row.Index)
  if not ok or (after ~= nil and after.Claimant ~= owner) then
    return false, "the game refused the recruit" .. (ok and "" or (": " .. tostring(err)))
  end
  return true, "recruited=" .. row.GreatPersonIndividualType
end

-- Patronize: pay gold (X = 0) or faith (X = 1) instead of points.
function Gov.PatronizeGreatPerson(owner, individual, useFaith)
  local p = Players[owner]
  local gp = Game.GetGreatPeople ~= nil and Game.GetGreatPeople() or nil
  local row = individual ~= nil and GameInfo.GreatPersonIndividuals[individual] or nil
  if gp == nil or row == nil then
    return false, "unknown great person"
  end
  local entry = timelineEntry(gp, row.Index)
  if entry == nil then
    return false, row.GreatPersonIndividualType .. " is not available right now"
  end
  local yieldRow = GameInfo.Yields[useFaith and "YIELD_FAITH" or "YIELD_GOLD"]
  local y = yieldRow and yieldRow.Index or (useFaith and 5 or 2)
  local what = useFaith and "faith" or "gold"
  local cost = call(gp, "GetPatronizeCost", owner, row.Index, y)
  if call(gp, "CanPatronizePerson", owner, row.Index, y) ~= true then
    return false, "cannot patronize " .. row.GreatPersonIndividualType .. " with " .. what
      .. (cost ~= nil and (" (costs " .. math.floor(cost) .. ")") or "")
  end
  if cost == nil or cost <= 0 then
    return false, "the game gave no " .. what .. " price for " .. row.GreatPersonIndividualType
  end
  local bank = useFaith and call(p, "GetReligion") or call(p, "GetTreasury")
  local balance = useFaith and call(bank, "GetFaithBalance") or call(bank, "GetGoldBalance")
  if balance == nil or balance < cost then
    return false, "patronizing needs " .. math.floor(cost) .. " " .. what .. "; you have " .. math.floor(balance or 0)
  end
  local ok, err = pcall(gp.GrantPerson, gp, row.Index, entry.Class, entry.Era, 0, owner, false)
  local after = timelineEntry(gp, row.Index)
  if not ok or (after ~= nil and after.Claimant ~= owner) then
    return false, "the game refused to grant " .. row.GreatPersonIndividualType .. (ok and "" or (": " .. tostring(err)))
  end
  if useFaith then
    pcall(bank.ChangeFaithBalance, bank, -cost)
  else
    pcall(bank.ChangeGoldBalance, bank, -cost)
  end
  return true, "patronized=" .. row.GreatPersonIndividualType .. ":" .. what .. "=" .. math.floor(cost)
end

function Gov.Governor(owner)
  return false, "governors cannot be appointed, assigned or promoted for this seat from a game script "
    .. "(the game only offers that to the local player's screen); the game's own AI manages this seat's governors"
end

-- Trade routes, great-person activation, envoys, and corps/army have no
-- call in this Gameplay script. A host InGame script cannot apply them for
-- an AI seat either. They stay unoffered. An order that still arrives fails
-- closed here.
--
-- The command that replicates is the local player's own operation.
-- OrderChannel.Send calls UI.RequestPlayerOperation with Game.GetLocalPlayer()
-- and PlayerOperations.EXECUTE_SCRIPT. Every PC runs that handler in this
-- file. Passing an AI player id is the governor path: the screen ignores a
-- seat that is not the local player, and the request never becomes a command
-- the other PCs replay.
--
-- UnitManager.RequestOperation and RequestCommand (make a route, activate a
-- great person, form a corps) start only for the local player's unit. They
-- are nil in this script. An AI unit fails the owner check on the host, the
-- same way CanStartOperation is empty for an AI seat. GetInfluence() only
-- reads the token pool. The token setters are not in this script, and a host
-- UI write of them is the same local-only mutation: live sends never moved
-- a token.
--
-- Aiming a UI operation at an AI seat would require
-- PlayerManager.SetLocalPlayerAndObserver. Civ6Ai_Apply._WithLocalPlayer
-- refuses that in a network game (local_player_swap_blocked_mp). The swap
-- is this PC's view. The other PCs do not swap, so a mutation that lands
-- only on the host desyncs. ExposedMembers and LuaEvents stay inside one
-- process. They do not cross the network.
--
-- Re-offering the orders would only send them back through EXECUTE_SCRIPT
-- into these fail-closed returns. The game's own AI keeps traders, great
-- people, envoys, and formations.
--
-- Trade routes. This script does not call the UI route creator.
-- Traders stay with the game's own AI (they are not model-commanded).
function Gov.MakeTradeRoute(owner, unitId, destCityId)
  return false, "trade_route_unavailable:no_gameplay_route:player=" .. tostring(owner)
    .. ":unit=" .. tostring(unitId) .. ":city=" .. tostring(destCityId)
end

-- Explore walks toward fog. A move that reveals nothing is not a success: a
-- scout can be ordered onto a tile it already sees, the move call returns, and
-- the revealed count stays flat. Success is a higher revealed count.
-- IsRevealed takes a plot index. Passing (x, y) tested index == x.
-- After two turns with no new tiles, the next order steps onto the nearest
-- unrevealed frontier (or the frontier nearest a revealed unmet city or
-- city-state). Ships step onto unrevealed water from the first order.
function Gov.Explore(owner, unitId)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "stale_unit_id"
  end
  local vis = PlayersVisibility ~= nil and PlayersVisibility[owner] or nil
  if vis == nil or vis.IsRevealed == nil then
    return false, "explore_unavailable:no_visibility"
  end
  if Map == nil or Map.GetPlotCount == nil or Map.GetPlotByIndex == nil then
    return false, "explore_unavailable:no_plot_index"
  end
  local plotCount = Map.GetPlotCount()
  if type(plotCount) ~= "number" or plotCount <= 0 then
    return false, "explore_unavailable:no_plot_index"
  end
  local function revealed(plot)
    if plot == nil or plot.GetIndex == nil then
      return false
    end
    local ok, result = pcall(function() return vis:IsRevealed(plot:GetIndex()) end)
    return ok and result == true
  end
  local function areaOf(plot)
    if plot ~= nil and plot.GetArea ~= nil then
      local ok, area = pcall(function() return plot:GetArea() end)
      if ok then return area end
    end
    return nil
  end
  local function adjacent(x, y, dir)
    if Map.GetAdjacentPlot == nil then
      return nil
    end
    local ok, plot = pcall(Map.GetAdjacentPlot, x, y, dir)
    if ok then
      return plot
    end
    return nil
  end
  local function countRevealed()
    local count = 0
    for i = 0, plotCount - 1 do
      local p = Map.GetPlotByIndex(i)
      if revealed(p) then
        count = count + 1
      end
    end
    return count
  end
  local function propKey(field)
    return "CIV6AI_EXPLORE_" .. tostring(owner) .. "_" .. tostring(unitId) .. "_" .. field
  end
  local function propGet(field)
    if Game == nil or Game.GetProperty == nil then
      return nil
    end
    local ok, value = pcall(function() return Game:GetProperty(propKey(field)) end)
    if ok then
      return num(value)
    end
    return nil
  end
  local function propSet(field, value)
    if Game == nil or Game.SetProperty == nil then
      return
    end
    pcall(function() Game:SetProperty(propKey(field), value) end)
  end
  local before = countRevealed()
  local turn = (Game ~= nil and Game.GetCurrentGameTurn ~= nil) and (num(Game.GetCurrentGameTurn()) or 0) or 0
  local lastN = propGet("N")
  local lastT = propGet("T")
  local streak = propGet("S") or 0
  local lastX, lastY = propGet("X"), propGet("Y")
  if lastN ~= nil and lastT ~= nil and turn > lastT then
    if before > lastN then
      streak = 0
    else
      streak = streak + (turn - lastT)
    end
  elseif lastN ~= nil and before > lastN then
    streak = 0
  end
  local stuck = streak >= 2
  -- A no_path frontier stays the nearest tile forever when some other unit
  -- reveals a tile and resets the quiet streak. Remember those plots.
  local failed = {}
  local function failKey(x, y)
    return tostring(x) .. "," .. tostring(y)
  end
  local failCount = propGet("FN") or 0
  if failCount > 8 then
    failCount = 8
  end
  if failCount < 0 then
    failCount = 0
  end
  for i = 1, failCount do
    local packed = propGet("F" .. tostring(i))
    if packed ~= nil and packed >= 0 then
      failed[failKey(math.floor(packed / 100000), packed % 100000)] = true
    end
  end
  local function rememberFail(x, y)
    local key = failKey(x, y)
    if failed[key] then
      return
    end
    failed[key] = true
    local list = {}
    for i = 1, failCount do
      local packed = propGet("F" .. tostring(i))
      if packed ~= nil and packed >= 0 then
        list[#list + 1] = packed
      end
    end
    list[#list + 1] = x * 100000 + y
    while #list > 8 do
      table.remove(list, 1)
    end
    failCount = #list
    propSet("FN", failCount)
    for i = 1, 8 do
      propSet("F" .. tostring(i), list[i] or -1)
    end
  end
  local function unreachableMove(why)
    local text = tostring(why or "")
    return string.find(text, "no_path", 1, true) ~= nil
      or text == "impassable"
      or string.find(text, "impassable", 1, true) ~= nil
  end
  local row = GameInfo.Units[unit:GetType()]
  local sea = row ~= nil and row.Domain == "DOMAIN_SEA"
  local ux, uy = unit:GetX(), unit:GetY()
  local here = Map.GetPlot(ux, uy)
  local unitArea = areaOf(here)
  local function waterOf(plot)
    return call(plot, "IsWater") == true
  end
  local function blocked(plot)
    return call(plot, "IsImpassable") == true
  end
  local function sameBody(plot, requireArea)
    return (not requireArea) or unitArea == nil or areaOf(plot) == unitArea
  end
  -- Same landmass or water body first. The nearest fog edge on another
  -- continent sends a land unit into the coast, where it stops.
  local function nearestBorder(requireArea)
    local best, bestD = nil, 1e9
    for i = 0, plotCount - 1 do
      local p = Map.GetPlotByIndex(i)
      if p ~= nil and p.GetX ~= nil then
        local x, y = p:GetX(), p:GetY()
        if revealed(p) and waterOf(p) == sea and not blocked(p) and not (x == ux and y == uy)
            and sameBody(p, requireArea) and failed[failKey(x, y)] ~= true then
          local d = Map.GetPlotDistance(ux, uy, x, y)
          if d < bestD then
            for dir = 0, 5 do
              local a = adjacent(x, y, dir)
              if a ~= nil and not revealed(a) then
                best, bestD = p, d
                break
              end
            end
          end
        end
      end
    end
    return best, bestD
  end
  -- Revealed city of an unmet major, or any city-state. Hidden city plots are
  -- not beacons: the coordinate is used only after IsRevealed is true.
  local function beacons()
    local marks = {}
    if Players == nil then
      return marks
    end
    local diplo = call(Players[owner], "GetDiplomacy")
    for id = 0, 63 do
      if id ~= owner and Players[id] ~= nil and call(Players[id], "IsAlive") == true
        and call(Players[id], "IsBarbarian") ~= true then
        local major = call(Players[id], "IsMajor")
        local met = diplo ~= nil and call(diplo, "HasMet", id) == true
        if major == false or (major == true and not met) then
          local cities = call(Players[id], "GetCities")
          if cities ~= nil and cities.Members ~= nil then
            pcall(function()
              for _, city in cities:Members() do
                local x, y = call(city, "GetX"), call(city, "GetY")
                local plot = (x ~= nil and y ~= nil and Map.GetPlot ~= nil) and Map.GetPlot(x, y) or nil
                if revealed(plot) then
                  marks[#marks + 1] = { x = x, y = y }
                end
              end
            end)
          end
        end
      end
    end
    return marks
  end
  local function nearestFog(requireArea, marks)
    local best, bestD, bestBeacon = nil, 1e9, 1e9
    for i = 0, plotCount - 1 do
      local p = Map.GetPlotByIndex(i)
      if p ~= nil and p.GetX ~= nil then
        local x, y = p:GetX(), p:GetY()
        local skip = failed[failKey(x, y)] == true
          or (stuck and lastX ~= nil and lastY ~= nil and x == lastX and y == lastY)
        if not skip and not revealed(p) and waterOf(p) == sea and not blocked(p) and sameBody(p, requireArea) then
          local frontier = Map.GetPlotDistance(ux, uy, x, y) <= 1
          if not frontier then
            for dir = 0, 5 do
              local a = adjacent(x, y, dir)
              if a ~= nil and revealed(a) then
                frontier = true
                break
              end
            end
          end
          if frontier then
            local dUnit = Map.GetPlotDistance(ux, uy, x, y)
            local dBeacon = 1e9
            for _, mark in ipairs(marks) do
              local db = Map.GetPlotDistance(x, y, mark.x, mark.y)
              if db < dBeacon then
                dBeacon = db
              end
            end
            local better = false
            if #marks > 0 then
              better = dBeacon < bestBeacon or (dBeacon == bestBeacon and dUnit < bestD)
            else
              better = dUnit < bestD
            end
            if better then
              best, bestD, bestBeacon = p, dUnit, dBeacon
            end
          end
        end
      end
    end
    return best, bestD
  end
  local best, bestD = nil, nil
  local otherArea = false
  local tx, ty, okMove, why
  local attempts = 0
  while attempts < 6 do
    attempts = attempts + 1
    best, bestD, otherArea = nil, nil, false
    -- After a no_path step, try fog even for a land unit that is not stuck yet.
    if sea or stuck or attempts > 1 then
      local marks = beacons()
      best, bestD = nearestFog(true, marks)
      if best == nil then
        best, bestD = nearestFog(false, marks)
        otherArea = best ~= nil
      end
    end
    if best == nil then
      otherArea = false
      best, bestD = nearestBorder(true)
      if best == nil then
        best, bestD = nearestBorder(false)
        otherArea = best ~= nil
      end
    end
    if best == nil then
      break
    end
    tx, ty = best:GetX(), best:GetY()
    okMove, why = Civ6Ai_Orders._MoveOnce(owner, unitId, tx, ty)
    if not unreachableMove(why) then
      break
    end
    rememberFail(tx, ty)
  end
  if tx == nil then
    return false, "explore_unavailable:map_known"
  end
  local after = countRevealed()
  propSet("N", after)
  propSet("T", turn)
  propSet("S", streak)
  propSet("X", tx)
  propSet("Y", ty)
  local reason = "explore_to=" .. tostring(tx) .. "," .. tostring(ty) .. ":d=" .. tostring(bestD)
  if otherArea then
    reason = reason .. ":other_area"
  end
  if sea then
    reason = reason .. ":sea"
  end
  if stuck then
    reason = reason .. ":stuck"
  end
  if after > before then
    return true, reason .. ":new=" .. tostring(after - before)
  end
  local detail = (okMove and "no_new_tiles") or tostring(why or "no_new_tiles")
  return false, "explore_no_reveal:" .. reason .. ":" .. detail
end

function Gov.ActivateGreatPerson(owner, unitId, mode)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "stale_unit_id"
  end
  if mode == 1 then
    local row = GameInfo.Units[unit:GetType()]
    local gp = call(unit, "GetGreatPerson")
    local isGP = gp ~= nil or (row ~= nil and row.UnitType ~= nil and string.find(row.UnitType, "GREAT_", 1, true) ~= nil)
    if not isGP then
      return false, "only a great person can retire"
    end
    if UnitManager == nil or UnitManager.Kill == nil then
      return false, "this game has no gameplay route to retire a great person"
    end
    UnitManager.Kill(unit, false)
    if Civ6Ai_Orders._Unit(owner, unitId) ~= nil then
      return false, "the game refused to retire that great person"
    end
    return true, "retired"
  end
  -- The great-person action is a UI command. See Gov.MakeTradeRoute: a host
  -- RequestOperation does not sync for an AI seat, and this script cannot
  -- call it. Retire (mode 1) still uses UnitManager.Kill above. The snapshot
  -- does not offer either action; the game's own AI uses the unit.
  return false, "activate_unavailable:no_gameplay_activate"
end

local function cityById(owner, cityId)
  for _, c in ipairs(sortedMembers(call(Players[owner], "GetCities"))) do
    if c:GetID() == cityId then
      return c
    end
  end
  return nil
end

local function warType(surprise)
  if WarTypes == nil then
    return nil
  end
  if surprise and WarTypes.SURPRISE_WAR ~= nil then
    return WarTypes.SURPRISE_WAR
  end
  return WarTypes.FORMAL_WAR
end

-- Firaxis scenario scripts (AlexanderScenario, NubiaScenario, VikingScenario,
-- WarMachineScenario): Players[n]:GetDiplomacy():DeclareWarOn(other, WarTypes.FORMAL_WAR, true).
function Gov.DeclareWar(owner, other, surprise)
  local them = Players[other]
  if them == nil or call(them, "IsAlive") ~= true then
    return false, "that civilization is not in the game"
  end
  local diplo = call(Players[owner], "GetDiplomacy")
  if diplo == nil or diplo.DeclareWarOn == nil then
    return false, "this game has no gameplay route to declare war"
  end
  if call(diplo, "IsAtWarWith", other) == true then
    return false, "you are already at war with them"
  end
  if call(diplo, "CanDeclareWarOn", other) == false then
    return false, "the game does not allow declaring war on them now"
  end
  local wt = warType(surprise)
  local ok, err
  if wt ~= nil then
    ok, err = pcall(diplo.DeclareWarOn, diplo, other, wt, true)
  else
    ok, err = pcall(diplo.DeclareWarOn, diplo, other)
  end
  if not ok then
    return false, "the game refused the declaration" .. (err ~= nil and (": " .. tostring(err)) or "")
  end
  if call(diplo, "IsAtWarWith", other) ~= true then
    return false, "the declaration did not take effect"
  end
  return true, "war_on=" .. tostring(other)
end

-- PiratesScenario_StartScript: pDiplo:MakePeaceWith(other) and CanMakePeaceWith.
function Gov.MakePeace(owner, other)
  local them = Players[other]
  if them == nil or call(them, "IsAlive") ~= true then
    return false, "that civilization is not in the game"
  end
  local diplo = call(Players[owner], "GetDiplomacy")
  if diplo == nil or diplo.MakePeaceWith == nil then
    return false, "this game has no gameplay route to make peace"
  end
  if call(diplo, "IsAtWarWith", other) ~= true then
    return false, "you are not at war with them"
  end
  if call(diplo, "CanMakePeaceWith", other) == false then
    return false, "the game does not allow peace with them now"
  end
  local ok, err = pcall(diplo.MakePeaceWith, diplo, other)
  if not ok then
    return false, "the game refused peace" .. (err ~= nil and (": " .. tostring(err)) or "")
  end
  -- A one-sided call can leave the other seat at war, and a failed read (nil)
  -- is not peace. Gold is paid only after this returns true.
  local theirDiplo = call(Players[other], "GetDiplomacy")
  if theirDiplo ~= nil then
    local okGet, fn = pcall(function() return theirDiplo.MakePeaceWith end)
    if okGet and type(fn) == "function" then
      pcall(fn, theirDiplo, owner)
    end
  end
  -- War can also sit on the team. Clear that flag when the engine exposes it,
  -- or the player call succeeds and the other seat keeps attacking.
  local myTeam = call(Players[owner], "GetTeam")
  local theirTeam = call(Players[other], "GetTeam")
  if Teams ~= nil and myTeam ~= nil and theirTeam ~= nil and Teams[myTeam] ~= nil then
    local team = Teams[myTeam]
    local okPeace, teamPeace = pcall(function() return team.MakePeace end)
    if okPeace and type(teamPeace) == "function" then
      pcall(teamPeace, team, theirTeam)
    end
    local okSet, setAtWar = pcall(function() return team.SetAtWar end)
    if okSet and type(setAtWar) == "function" then
      pcall(setAtWar, team, theirTeam, false)
    end
  end
  local ours = call(diplo, "IsAtWarWith", other)
  local theirs = call(theirDiplo, "IsAtWarWith", owner)
  if ours ~= false or theirs ~= false then
    -- Their seat is still at war. Put our flag back so the snapshot does not
    -- say peace while they keep attacking, and do not pay the gold.
    if theirs == true and ours ~= true then
      local okDecl, fn = pcall(function() return diplo.DeclareWarOn end)
      if okDecl and type(fn) == "function" then
        pcall(fn, diplo, other)
      end
    end
    return false, "peace did not take effect"
  end
  return true, "peace_with=" .. tostring(other)
end

-- An agreed deal (the other seat accepted it a turn earlier). Signed amounts,
-- + = owner gives. All checks run before any change, so it applies whole or not at all.
-- mode bits: 1 peace, 2 friendship, 4 alliance, 8 open borders, 16 embassy, 32 delegation (both ways).
-- {setter, checker, civic/tech both seats need}. Only delegation and permanent
-- alliance setters appear in Firaxis scripts; the rest are verified after the call.
local PACTS = {
  [2] = { "SetHasDeclaredFriendship", "HasDeclaredFriendship" },
  [4] = { "SetHasAllied", "HasAllied", "CIVIC_DIPLOMATIC_SERVICE" },
  [8] = { "SetOpenBorders", "HasOpenBordersFrom", "CIVIC_EARLY_EMPIRE" },
  [16] = { "SetHasEmbassyAt", "HasEmbassyAt", "TECH_WRITING" },
  [32] = { "SetHasDelegationAt", "HasDelegationAt" },
}

local function knows(p, id)
  if id == nil then
    return true
  end
  local civic, tech = GameInfo.Civics[id], GameInfo.Technologies[id]
  if civic ~= nil then
    return call(call(p, "GetCulture"), "HasCivic", civic.Index) == true
  end
  return tech ~= nil and call(call(p, "GetTechs"), "HasTech", tech.Index) == true
end

-- Envoys. The influence-token setters are not available in this script: every
-- live send came back without moving a token. Do not call them. A host UI
-- write through GetInfluence does not sync for an AI seat (see
-- Gov.MakeTradeRoute). The snapshot does not offer the order; the game's
-- own AI sends envoys.
function Gov.SendEnvoy(owner, minor)
  return false, "envoy_unavailable:no_gameplay_route"
end

function Gov.Deal(owner, other, gold, r1, a1, r2, a2, mode)
  local me, them = Players[owner], Players[other]
  if them == nil or call(them, "IsAlive") ~= true then
    return false, "that civilization is not in the game"
  end
  local tMe, tThem = call(me, "GetTreasury"), call(them, "GetTreasury")
  local rMe, rThem = call(me, "GetResources"), call(them, "GetResources")
  gold = gold or 0
  local payer = gold > 0 and tMe or tThem
  if gold ~= 0 and (call(payer, "GetGoldBalance") or 0) < math.abs(gold) then
    return false, "not enough gold for the deal"
  end
  local legs = {}
  for _, leg in ipairs({ { r1, a1 }, { r2, a2 } }) do
    if leg[1] ~= nil and leg[1] >= 0 and leg[2] ~= nil and leg[2] ~= 0 then
      local from = leg[2] > 0 and rMe or rThem
      if from == nil or from.ChangeResourceAmount == nil then
        return false, "this game has no gameplay route to move resources"
      end
      if (call(from, "GetResourceAmount", leg[1]) or 0) < math.abs(leg[2]) then
        return false, "not enough " .. tostring(GameInfo.Resources[leg[1]].ResourceType) .. " for the deal"
      end
      legs[#legs + 1] = leg
    end
  end
  mode = mode or 0
  for _, bit in ipairs(sortedKeys(PACTS)) do
    local pact = PACTS[bit]
    if math.floor(mode / bit) % 2 == 1 and not (knows(me, pact[3]) and knows(them, pact[3])) then
      return false, pact[2] .. " needs " .. tostring(pact[3]) .. " on both sides"
    end
  end
  if mode % 2 == 1 then
    local ok, why = Gov.MakePeace(owner, other)
    if not ok then
      return false, why
    end
  end
  local dMe, dThem = call(me, "GetDiplomacy"), call(them, "GetDiplomacy")
  for _, bit in ipairs({ 2, 4, 8, 16, 32 }) do
    local pact = PACTS[bit]
    if math.floor(mode / bit) % 2 == 1 then
      if dMe == nil or dMe[pact[1]] == nil then
        return false, "this game has no gameplay route for " .. pact[1]
      end
      pcall(dMe[pact[1]], dMe, other, true)
      pcall(dThem[pact[1]], dThem, owner, true)
      if call(dMe, pact[2], other) ~= true then
        return false, "the game refused " .. pact[1]
      end
    end
  end
  if gold ~= 0 then
    tMe:ChangeGoldBalance(-gold)
    tThem:ChangeGoldBalance(gold)
  end
  for _, leg in ipairs(legs) do
    rMe:ChangeResourceAmount(leg[1], -leg[2])
    rThem:ChangeResourceAmount(leg[1], leg[2])
  end
  return true, "deal_with=" .. tostring(other)
end

local UNAVAILABLE_COST = 1000000000

local function debit(owner, useFaith, cost)
  local p = Players[owner]
  if useFaith then
    local rel = call(p, "GetReligion")
    local bal = call(rel, "GetFaithBalance") or 0
    if bal < cost then
      return false, "needs " .. math.floor(cost) .. " faith; you have " .. math.floor(bal)
    end
    pcall(rel.ChangeFaithBalance, rel, -cost)
    return true, bal
  end
  local tre = call(p, "GetTreasury")
  local bal = call(tre, "GetGoldBalance") or 0
  if bal < cost then
    return false, "needs " .. math.floor(cost) .. " gold; you have " .. math.floor(bal)
  end
  pcall(tre.ChangeGoldBalance, tre, -cost)
  return true, bal
end

local function credit(owner, useFaith, cost)
  local p = Players[owner]
  if useFaith then
    local rel = call(p, "GetReligion")
    pcall(rel.ChangeFaithBalance, rel, cost)
  else
    local tre = call(p, "GetTreasury")
    pcall(tre.ChangeGoldBalance, tre, cost)
  end
end

-- Gold/faith purchase: debit the treasury, then spawn the unit (UnitManager.InitUnit,
-- Firaxis scenarios and this file's own MP tests) or complete the building
-- (BuildQueue:CreateIncompleteBuilding at 100%, TunerCityPanel.lua).
function Gov.PurchaseItem(owner, cityId, itemIndex, isBuilding, useFaith, cost)
  -- Disabled: vanilla-only mechanics. There is no gameplay-side purchase call,
  -- and debit + InitUnit/CreateIncompleteBuilding replaces the game's purchase.
  if true then
    return false, "item purchase is not available"
  end
  local city = cityById(owner, cityId)
  if city == nil then
    return false, "stale_city_id:" .. tostring(cityId)
  end
  local row, hash, typeName
  if isBuilding then
    row = GameInfo.Buildings[itemIndex]
    hash = row and row.Hash
    typeName = row and row.BuildingType
  else
    row = GameInfo.Units[itemIndex]
    hash = row and row.Hash
    typeName = row and row.UnitType
  end
  if row == nil or hash == nil then
    return false, "unknown item to purchase"
  end
  if isBuilding then
    local buildings = call(city, "GetBuildings")
    if call(buildings, "HasBuilding", row.Index) == true then
      return false, typeName .. " is already in that city"
    end
  end
  if type(cost) ~= "number" or cost <= 0 then
    return false, typeName .. " cannot be purchased with " .. (useFaith and "faith" or "gold") .. " in that city"
  end
  local okPay, why = debit(owner, useFaith, cost)
  if not okPay then
    return false, why
  end
  local made = false
  if isBuilding then
    local bq = call(city, "GetBuildQueue")
    local plot = Map.GetPlot(city:GetX(), city:GetY())
    local index = plot ~= nil and call(plot, "GetIndex") or nil
    if bq ~= nil and bq.CreateIncompleteBuilding ~= nil and index ~= nil then
      made = pcall(bq.CreateIncompleteBuilding, bq, row.Index, index, 100)
    end
    made = made and call(call(city, "GetBuildings"), "HasBuilding", row.Index) == true
  else
    local unit
    local okU
    okU, unit = pcall(UnitManager.InitUnit, owner, typeName, city:GetX(), city:GetY())
    made = okU and unit ~= nil
  end
  if not made then
    credit(owner, useFaith, cost)
    return false, "the game refused to create " .. typeName
  end
  return true, "bought=" .. typeName .. ":" .. (useFaith and "faith" or "gold") .. "=" .. math.floor(cost)
    .. ":city=" .. tostring(cityId)
end

-- Tile buy: Plot:SetOwner is a gameplay setter (AustraliaScenario.lua). Cost
-- is CityGold:GetPlotPurchaseCost, the same figure PlotInfo.lua shows on the coin.
function Gov.PurchaseTile(owner, cityId, x, y)
  local city = cityById(owner, cityId)
  local plot = Map.GetPlot(x, y)
  if city == nil then
    return false, "stale_city_id:" .. tostring(cityId)
  end
  if plot == nil then
    return false, "there is no tile at " .. tostring(x) .. "," .. tostring(y)
  end
  local plotOwner = call(plot, "GetOwner")
  if plotOwner ~= nil and plotOwner >= 0 then
    return false, "that tile is already owned"
  end
  local gold = call(city, "GetGold")
  local index = call(plot, "GetIndex")
  local cost = type(index) == "number" and call(gold, "GetPlotPurchaseCost", index) or nil
  if type(cost) ~= "number" or cost <= 0 or cost >= UNAVAILABLE_COST then
    return false, "that city cannot buy the tile at " .. tostring(x) .. "," .. tostring(y)
  end
  local okPay, why = debit(owner, false, cost)
  if not okPay then
    return false, why
  end
  local ok = pcall(plot.SetOwner, plot, owner, city:GetID())
  if not ok or call(plot, "GetOwner") ~= owner then
    pcall(plot.SetOwner, plot, owner)
  end
  if call(plot, "GetOwner") ~= owner then
    credit(owner, false, cost)
    return false, "the game refused to grant that tile"
  end
  return true, "tile=" .. tostring(x) .. "," .. tostring(y) .. ":gold=" .. math.floor(cost)
    .. ":city=" .. tostring(cityId)
end

-- Pillage the improvement under a combat unit. TunerMapPanel uses
-- ImprovementBuilder.SetImprovementPillaged; PlotToolTip reads it back with
-- plot:IsImprovementPillaged. The unit must be standing on that tile.
function Gov.PillageImprovement(owner, unitId, x, y)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "unit_not_found"
  end
  local row = GameInfo.Units[unit:GetType()]
  if row == nil or (num(row.Combat) or 0) <= 0 then
    return false, "only a combat unit can pillage"
  end
  local ux, uy = call(unit, "GetX"), call(unit, "GetY")
  if type(x) == "number" and x >= 0 and type(y) == "number" and y >= 0 then
    if ux ~= x or uy ~= y then
      return false, "that unit is not on " .. tostring(x) .. "," .. tostring(y)
    end
  end
  local plot = Map.GetPlot(ux, uy)
  if plot == nil or plot.IsImprovementPillaged == nil then
    return false, "this game has no gameplay route to read a pillaged improvement"
  end
  local imp = call(plot, "GetImprovementType")
  if type(imp) ~= "number" or imp < 0 then
    return false, "there is no improvement on that tile"
  end
  if plot:IsImprovementPillaged() == true then
    return false, "that improvement is already pillaged"
  end
  if ImprovementBuilder == nil or ImprovementBuilder.SetImprovementPillaged == nil then
    return false, "this game has no gameplay route to pillage an improvement"
  end
  local okSet = pcall(ImprovementBuilder.SetImprovementPillaged, plot, true)
  if not okSet or plot:IsImprovementPillaged() ~= true then
    return false, "the game refused to pillage that improvement"
  end
  pcall(UnitManager.FinishMoves, unit)
  local irow = GameInfo.Improvements[imp]
  return true, "pillaged=" .. tostring(irow ~= nil and irow.ImprovementType or imp)
    .. ":plot=" .. tostring(ux) .. "," .. tostring(uy)
end

-- Upgrade: pay the live GetUpgradeCost (the packet cost is only a hint; a UI
-- read of -1 must not be charged), then replace the unit on its tile.
-- InitUnit in a gameplay script takes the unit Index. A type string creates
-- nothing, and the tile stays blocked until Kill is told not to delay death.
function Gov.UpgradeUnit(owner, unitId, typeIndex, cost)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  local row = GameInfo.Units[typeIndex]
  if unit == nil or row == nil then
    return false, "stale_unit_or_type"
  end
  if type(cost) ~= "number" or cost < 0 then
    cost = call(unit, "GetUpgradeCost")
  end
  if type(cost) ~= "number" or cost < 0 then
    return false, "upgrade cost is unknown, so the unit was not replaced"
  end
  local x, y, dmg = unit:GetX(), unit:GetY(), call(unit, "GetDamage") or 0
  local xp = call(call(unit, "GetExperience"), "GetExperiencePoints") or 0
  local okPay, why = debit(owner, false, cost)
  if not okPay then
    return false, why
  end
  local function spawn(typeArg)
    if UnitManager == nil or UnitManager.InitUnit == nil or typeArg == nil then
      return nil
    end
    local okU, new = pcall(UnitManager.InitUnit, owner, typeArg, x, y)
    if okU and new ~= nil then
      return new
    end
    return nil
  end
  -- The old unit still occupies the tile, so the first create usually fails.
  -- Kill with the delay flag false, then create by Index (the gameplay
  -- argument). The type string is only a fallback.
  local created = spawn(row.Index)
  if created == nil then
    pcall(UnitManager.Kill, unit, false)
    created = spawn(row.Index) or spawn(row.UnitType)
  else
    pcall(UnitManager.Kill, unit, false)
  end
  if created == nil then
    credit(owner, false, cost)
    return false, "the game refused to create " .. tostring(row.UnitType)
      .. " (InitUnit did not accept the type index or the type name)"
  end
  call(created, "SetDamage", dmg)
  call(call(created, "GetExperience"), "ChangeExperience", xp)
  pcall(UnitManager.FinishMoves, created)
  return true, "upgraded=" .. row.UnitType .. ":gold=" .. tostring(cost)
end

function Gov.PromoteUnit(owner, unitId, promoIndex)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  local exp = call(unit, "GetExperience")
  local row = GameInfo.UnitPromotions[promoIndex]
  if exp == nil or row == nil then
    return false, "no_promotion_route"
  end
  if exp.SetPromotion ~= nil then
    if not pcall(exp.SetPromotion, exp, row.Index, true) then
      pcall(exp.SetPromotion, exp, row.Index)
    end
  end
  if call(exp, "HasPromotion", row.Index) ~= true and exp.ChangePromotion ~= nil then
    pcall(exp.ChangePromotion, exp, row.Index)
  end
  if call(exp, "HasPromotion", row.Index) ~= true then
    return false, "the game refused " .. row.UnitPromotionType
      .. " (SetPromotion did not grant it; the unit was not changed)"
  end
  pcall(UnitManager.FinishMoves, unit)
  return true, "promoted=" .. row.UnitPromotionType
end

-- Corps/army (fleet/armada): the unit absorbs an adjacent same-type unit (I).
-- The formation is set while that partner is still alive. Killing it first
-- makes SetMilitaryFormation a no-op and the order reports failure after the
-- partner is already gone.
-- Field lookup on the formation enum. A missing name is nil; using it as a
-- table key throws "table index is nil". Live builds use STANDARD_FORMATION;
-- the long *_MILITARY_FORMATION names are the other family.
local function formationConst(F, ...)
  for i = 1, select("#", ...) do
    local name = select(i, ...)
    local ok, value = pcall(function() return F[name] end)
    if ok and type(value) == "number" then
      return value
    end
  end
  return nil
end

function Gov.JoinFormation(owner, unitId, otherId)
  local unit, other = Civ6Ai_Orders._Unit(owner, unitId), Civ6Ai_Orders._Unit(owner, otherId)
  local F = MilitaryFormationTypes
  if unit == nil or other == nil or F == nil then
    return false, "no_formation_route: a unit, its partner, or formation types are missing; nothing was removed"
  end
  local standard = formationConst(F, "STANDARD_MILITARY_FORMATION", "STANDARD_FORMATION")
  local corps = formationConst(F, "CORPS_MILITARY_FORMATION", "CORPS_FORMATION")
  local army = formationConst(F, "ARMY_MILITARY_FORMATION", "ARMY_FORMATION")
  if corps == nil or army == nil then
    return false, "no_formation_route: corps or army formation types are missing; nothing was removed"
  end
  local current = call(unit, "GetMilitaryFormation")
  local target = nil
  if current == corps then
    target = army
  elseif current == army then
    target = nil
  elseif current == standard or (standard == nil and current ~= corps and current ~= army) then
    -- No standard constant: a formation that is neither corps nor army is a single unit.
    target = corps
  end
  if target == nil or unit:GetType() ~= other:GetType()
      or Map.GetPlotDistance(unit:GetX(), unit:GetY(), other:GetX(), other:GetY()) > 1 then
    return false, "needs an adjacent unit of the same type that is not already a corps or army"
  end
  if unit.SetMilitaryFormation ~= nil then
    pcall(unit.SetMilitaryFormation, unit, target)
  end
  if call(unit, "GetMilitaryFormation") ~= target then
    -- The formation operation is UI-only. A host RequestOperation does not
    -- sync for an AI seat (see Gov.MakeTradeRoute). Leave both units when
    -- the gameplay setter does not stick.
    return false, "the game refused to form the corps or army; both units are unchanged (SetMilitaryFormation did not stick)"
  end
  if Civ6Ai_Orders._Unit(owner, otherId) ~= nil then
    pcall(UnitManager.Kill, other, false)
  end
  pcall(UnitManager.FinishMoves, unit)
  return true, "formation=" .. tostring(target)
end

-- Spread religion onto a city, or a guru heal onto a friendly religious unit.
-- Pressure comes from the unit row's ReligiousStrength. A missing method or a
-- zero strength fails without spending a charge.
function Gov.SpreadReligion(owner, unitId, x, y, mode)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  if unit == nil then
    return false, "stale_unit_id"
  end
  if x == nil or y == nil then
    return false, "missing_target"
  end
  if Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y) > 1 then
    return false, "that tile is not adjacent to the religious unit"
  end
  local row = GameInfo.Units[unit:GetType()]
  local rel = call(unit, "GetReligion")
  local charges = call(rel, "GetSpreadCharges")
  if type(charges) ~= "number" or charges <= 0 then
    return false, "that unit has no religious charges left"
  end
  if mode == 1 then
    local amount = tonumber(row and row.ReligiousStrength) or 0
    if amount <= 0 and GameInfo.GlobalParameters ~= nil then
      for param in GameInfo.GlobalParameters() do
        local name = tostring(param.Name or "")
        if string.find(name, "HEAL", 1, true) and string.find(name, "RELIG", 1, true) then
          amount = tonumber(param.Value) or 0
          if amount > 0 then break end
        end
      end
    end
    if amount <= 0 then
      return false, "this game does not publish a religious heal amount, so no charge was spent"
    end
    local plot = Map.GetPlot(x, y)
    local target = nil
    if plot ~= nil and Units ~= nil and Units.GetUnitsInPlot ~= nil then
      for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
        if other:GetOwner() == owner and other:GetID() ~= unit:GetID() then
          target = other
          break
        end
      end
    end
    if target == nil then
      return false, "no friendly unit on that tile to heal"
    end
    call(target, "ChangeDamage", -amount)
    call(rel, "ChangeSpreadCharges", -1)
    pcall(UnitManager.FinishMoves, unit)
    return true, "healed=" .. tostring(amount)
  end
  local pressure = tonumber(row and row.ReligiousStrength) or 0
  if pressure <= 0 then
    return false, "that unit has no religious strength to spread, so no charge was spent"
  end
  local religionType = call(rel, "GetReligionType")
  if type(religionType) ~= "number" or religionType < 0 then
    return false, "that unit has no religion to spread"
  end
  local city = nil
  if Cities ~= nil and Cities.GetCityInPlot ~= nil then
    local okC, found = pcall(Cities.GetCityInPlot, x, y)
    if okC then city = found end
  end
  local cityRel = call(city, "GetReligion")
  if city == nil or cityRel == nil or cityRel.AddReligiousPressure == nil then
    return false, "there is no city on that tile, or this game has no gameplay route to add religious pressure"
  end
  local okP, err = pcall(cityRel.AddReligiousPressure, cityRel, owner, religionType, pressure)
  if not okP then
    return false, "the game refused the spread: " .. tostring(err)
  end
  call(rel, "ChangeSpreadCharges", -1)
  pcall(UnitManager.FinishMoves, unit)
  return true, "spread=" .. tostring(pressure) .. ":city=" .. tostring(city:GetID())
end

-- A live enemy unit, city, or district on the plot. The id is what the strike log records.
function Civ6Ai_Orders._LiveStrikeTarget(owner, x, y)
  local plot = Map ~= nil and Map.GetPlot ~= nil and Map.GetPlot(x, y) or nil
  if plot ~= nil and Units ~= nil and Units.GetUnitsInPlot ~= nil then
    local bestId, bestStrength = nil, -1
    for _, other in ipairs(Units.GetUnitsInPlot(plot) or {}) do
      if other:GetOwner() ~= owner and not Civ6Ai_Orders._IsDead(other)
          and Civ6Ai_Orders._AtWar(owner, other:GetOwner()) then
        local row = GameInfo ~= nil and GameInfo.Units[other:GetType()] or nil
        local strength = row ~= nil and (num(row.Combat) or 0) or 0
        if strength > bestStrength then
          bestId, bestStrength = other:GetID(), strength
        end
      end
    end
    if bestId ~= nil then
      return bestId
    end
  end
  if Cities ~= nil and Cities.GetCityInPlot ~= nil then
    local okC, city = pcall(Cities.GetCityInPlot, x, y)
    if okC and city ~= nil and city:GetOwner() ~= owner and Civ6Ai_Orders._AtWar(owner, city:GetOwner()) then
      local id = city:GetID()
      if id ~= nil then
        return id
      end
    end
  end
  if Players ~= nil then
    for pid = 0, 63 do
      if pid ~= owner and Players[pid] ~= nil and Civ6Ai_Orders._AtWar(owner, pid) then
        for _, district in ipairs(sortedMembers(call(Players[pid], "GetDistricts"))) do
          if call(district, "GetX") == x and call(district, "GetY") == y then
            local id = call(district, "GetID")
            if id ~= nil then
              return id
            end
          end
        end
      end
    end
  end
  return nil
end

-- Gameplay often has CityManager but no CityCommandTypes.PARAM_*. The strike
-- hash and plot keys then come from GameInfo / UnitOperationTypes.
function Civ6Ai_Orders._CityStrikeCommand()
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

function Civ6Ai_Orders._CityStrikeParams(x, y)
  local params = {}
  local function put(axis, value)
    local keys = {}
    if CityCommandTypes ~= nil then
      keys[#keys + 1] = axis == "x" and CityCommandTypes.PARAM_X or CityCommandTypes.PARAM_Y
    end
    if UnitOperationTypes ~= nil then
      keys[#keys + 1] = axis == "x" and UnitOperationTypes.PARAM_X or UnitOperationTypes.PARAM_Y
    end
    keys[#keys + 1] = axis == "x" and "PARAM_X" or "PARAM_Y"
    keys[#keys + 1] = string.upper(axis)
    for _, key in ipairs(keys) do
      if key ~= nil then
        params[key] = value
      end
    end
  end
  put("x", x)
  put("y", y)
  return params
end

function Civ6Ai_Orders.CityStrikeAvailable()
  return CityManager ~= nil and CityManager.CanStartCommand ~= nil
    and CityManager.RequestCommand ~= nil and Civ6Ai_Orders._CityStrikeCommand() ~= nil
end

-- true: this plot is a legal strike. false: the engine refused this plot.
-- nil: the command API is missing.
function Civ6Ai_Orders._CityStrikeCan(city, x, y)
  local cmd = Civ6Ai_Orders._CityStrikeCommand()
  if CityManager == nil or CityManager.CanStartCommand == nil or cmd == nil then
    return nil
  end
  local params = Civ6Ai_Orders._CityStrikeParams(x, y)
  local tries = {
    function() return CityManager.CanStartCommand(city, cmd, params) end,
    function() return CityManager.CanStartCommand(city, cmd, true, params, false) end,
  }
  local blocked = false
  for _, fn in ipairs(tries) do
    local ok, can = pcall(fn)
    if ok and can == true then
      return true
    end
    if ok and can == false then
      blocked = true
    end
  end
  if blocked then
    return false
  end
  local okBare, canBare = pcall(CityManager.CanStartCommand, city, cmd)
  if okBare and canBare == true then
    return true
  end
  if okBare and canBare == false then
    return false
  end
  return nil
end

-- The engine's city ranged attack. CanStartCommand is the gate; a district is
-- never passed to forecast, ChangeDamage, or Kill (that read 0xffffffff).
function Civ6Ai_Orders._CityRangeAttack(city, x, y)
  if not Civ6Ai_Orders.CityStrikeAvailable() then
    return false, "city_strike_unavailable"
  end
  local cmd = Civ6Ai_Orders._CityStrikeCommand()
  local params = Civ6Ai_Orders._CityStrikeParams(x, y)
  local can = Civ6Ai_Orders._CityStrikeCan(city, x, y)
  if can == false then
    return false, "city_strike_refused"
  end
  local okReq, err = pcall(CityManager.RequestCommand, city, cmd, params)
  if not okReq then
    okReq, err = pcall(CityManager.RequestCommand, city, cmd, true, params)
  end
  if not okReq then
    return false, "city_strike_refused:" .. trimErr(err)
  end
  return true, "city_strike"
end

-- City ranged strike, once per city per turn (synced property).
function Gov.CityStrike(owner, cityId, x, y)
  local city = cityById(owner, cityId)
  local key = "CIV6AI_STRIKE_" .. tostring(owner) .. "_" .. tostring(cityId)
  if city == nil then
    return false, "stale_city_id"
  end
  if num(Game:GetProperty(key)) == Game.GetCurrentGameTurn() then
    return false, "city already struck this turn"
  end
  local defenderId = Civ6Ai_Orders._LiveStrikeTarget(owner, x, y)
  if defenderId == nil then
    return false, "no_enemy_on_plot"
  end
  if Map.GetPlotDistance(city:GetX(), city:GetY(), x, y) > 2 then
    return false, "out_of_range"
  end
  log("city_strike|city=" .. tostring(cityId) .. "|x=" .. tostring(x) .. "|y=" .. tostring(y)
    .. "|defender=" .. tostring(defenderId))
  local ok, reason = Civ6Ai_Orders._CityRangeAttack(city, x, y)
  if not ok then
    return false, reason
  end
  Game:SetProperty(key, Game.GetCurrentGameTurn())
  return true, reason
end

-- An improvement (builder, or fort) on the unit's tile; spends one build charge.
function Gov.BuildImprovement(owner, unitId, impIndex)
  local unit = Civ6Ai_Orders._Unit(owner, unitId)
  local row = GameInfo.Improvements[impIndex]
  local plot = unit ~= nil and Map.GetPlot(unit:GetX(), unit:GetY()) or nil
  if plot == nil or row == nil or ImprovementBuilder == nil or ImprovementBuilder.SetImprovementType == nil then
    return false, "no_improvement_route"
  end
  if call(plot, "GetOwner") ~= owner then
    return false, "not_your_territory"
  end
  if (call(unit, "GetBuildCharges") or 0) <= 0 then
    return false, "no_build_charges"
  end
  if ImprovementBuilder.CanHaveImprovement ~= nil
      and call(ImprovementBuilder, "CanHaveImprovement", plot, row.Index, call(Players[owner], "GetTeam")) == false then
    return false, "tile_cannot_have:" .. row.ImprovementType
  end
  pcall(ImprovementBuilder.SetImprovementType, plot, row.Index, owner)
  if call(plot, "GetImprovementType") ~= row.Index and ImprovementBuilder.SetImprovement ~= nil then
    pcall(ImprovementBuilder.SetImprovement, plot, row.Index, owner)
  end
  if call(plot, "GetImprovementType") ~= row.Index then
    return false, "the game refused " .. row.ImprovementType
  end
  call(unit, "ChangeBuildCharges", -1)
  pcall(UnitManager.FinishMoves, unit)
  return true, "built=" .. row.ImprovementType
end
Gov.BuildFort = Gov.BuildImprovement

function Civ6Ai_Orders._DoDeal(sender, o)
  local why = Civ6Ai_Orders._Authorize(sender, o.P)
  if why ~= nil then
    return false, why
  end
  local k = o.K
  if k == Civ6Ai_Orders.K.WAR then
    return Gov.DeclareWar(o.P, o.I, o.X == 1)
  elseif k == Civ6Ai_Orders.K.DEAL then
    return Gov.Deal(o.P, o.I, o.W, o.X, o.Y, o.I2, o.I3, o.A)
  elseif k == Civ6Ai_Orders.K.ENVOY then
    return Gov.SendEnvoy(o.P, o.I)
  elseif k == Civ6Ai_Orders.K.BUY then
    return Gov.PurchaseItem(o.P, o.X, o.I, o.U == 1, o.Y == 1, o.V)
  elseif k == Civ6Ai_Orders.K.BUY_TILE then
    return Gov.PurchaseTile(o.P, o.I, o.X, o.Y)
  end
  return false, "unknown_kind"
end

function Civ6Ai_Orders._DoWork(sender, o)
  local why = Civ6Ai_Orders._Authorize(sender, o.P)
  if why ~= nil then
    return false, why
  end
  return Gov.PillageImprovement(o.P, o.U, o.X, o.Y)
end

-- Synced channel dispatch for the governance kinds.
function Civ6Ai_Orders._DoGovernance(sender, o)
  local why = Civ6Ai_Orders._Authorize(sender, o.P)
  if why ~= nil then
    return false, why
  end
  local k = o.K
  if k == Civ6Ai_Orders.K.GOVERNMENT then
    return Gov.ChangeGovernment(o.P, o.I)
  elseif k == Civ6Ai_Orders.K.POLICY then
    return Gov.SetPolicySlot(o.P, o.X, o.I)
  elseif k == Civ6Ai_Orders.K.PANTHEON then
    return Gov.FoundPantheon(o.P, o.I)
  elseif k == Civ6Ai_Orders.K.RELIGION then
    return Gov.FoundReligion(o.P, o.I, o.U, o.X, o.Y, o.V, o.W)
  elseif k == Civ6Ai_Orders.K.GP_RECRUIT then
    return Gov.RecruitGreatPerson(o.P, o.I)
  elseif k == Civ6Ai_Orders.K.GP_PATRONIZE then
    return Gov.PatronizeGreatPerson(o.P, o.I, o.X == 1)
  elseif k == Civ6Ai_Orders.K.GOVERNOR then
    return Gov.Governor(o.P)
  end
  return false, "unknown_kind"
end

-- Read-only load probe: which culture/governor/religion/great-people calls
-- this game's gameplay scripts really have (logged once per load).
function Gov.Probe()
  local p = nil
  for id = 0, 62 do
    if Players[id] ~= nil and call(Players[id], "IsAlive") and call(Players[id], "IsMajor") then
      p = Players[id]
      break
    end
  end
  local objects = {
    { "PlayerCulture", call(p, "GetCulture") }, { "PlayerGovernors", call(p, "GetGovernors") },
    { "PlayerReligion", call(p, "GetReligion") }, { "GameReligion", Game.GetReligion ~= nil and Game.GetReligion() or nil },
    { "GameGreatPeople", Game.GetGreatPeople ~= nil and Game.GetGreatPeople() or nil },
    { "GreatPeoplePoints", call(p, "GetGreatPeoplePoints") },
    { "Unit", sortedMembers(call(p, "GetUnits"))[1] },
    { "UnitExperience", call(sortedMembers(call(p, "GetUnits"))[1], "GetExperience") },
  }
  for _, pair in ipairs(objects) do
    local okM, names = pcall(Civ6Ai_Orders.MethodNames, pair[2])
    log("gov_probe|" .. pair[1] .. "=" .. tostring(okM and names or ("error:" .. tostring(names))))
  end
  log("gov_probe|slot_call=" .. tostring(Gov.SlotCall(call(p, "GetCulture"))))
end

-- ---------------------------------------------------------------------------
-- Multiplayer test mode. Scripted checks the host runs on game day to find
-- out which routes work in a real two-PC game. Off unless a TEST_MODE order
-- switched it on (a synced game property), and only the controller may send
-- them. Each returns ok, reason; the reason is logged on every PC.
-- ---------------------------------------------------------------------------
function Civ6Ai_Orders.MethodNames(obj)
  local names, seen = {}, {}
  local function add(k)
    k = tostring(k)
    if not seen[k] and not string.match(k, "^__") then
      seen[k] = true
      names[#names + 1] = k
    end
  end
  local function scan(t, depth)
    if type(t) ~= "table" or depth > 3 then
      return
    end
    for k, v in pairs(t) do
      if type(v) == "function" then
        add(k)
      end
    end
    local mt = getmetatable(t)
    if mt ~= nil and type(mt) == "table" then
      scan(mt.__index, depth + 1)
    end
  end
  if obj == nil then
    return "nil"
  end
  scan(obj, 0)
  local okMt, mt = pcall(getmetatable, obj)
  if okMt and type(mt) == "table" then
    scan(mt, 1)
    scan(mt.__index, 1)
  end
  table.sort(names)
  if #names == 0 then
    return "none:" .. type(obj)
  end
  return table.concat(names, ",")
end

local function barbarianId()
  for id = 0, 63 do
    local p = Players[id]
    if p ~= nil and call(p, "IsBarbarian") then
      return id
    end
  end
  return nil
end

-- First empty passable land plot next to x,y, in fixed direction order.
local function freeLandNear(x, y)
  for dir = 0, 5 do
    local plot = Map.GetAdjacentPlot(x, y, dir)
    if plot ~= nil and not call(plot, "IsWater") and not call(plot, "IsImpassable") and not call(plot, "IsMountain")
        and not call(plot, "IsCity") then
      local busy = false
      if Units ~= nil and Units.GetUnitsInPlot ~= nil then
        for _ in ipairs(Units.GetUnitsInPlot(plot) or {}) do
          busy = true
        end
      end
      if not busy then
        return plot:GetX(), plot:GetY()
      end
    end
  end
  return nil, nil
end

local function firstCity(owner)
  local list = sortedMembers(call(Players[owner], "GetCities"))
  return list[1]
end

Civ6Ai_Orders.Tests = {}

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_INTROSPECT] = function(sender, o, params)
  local p = Players[o.P]
  local unit = sortedMembers(call(p, "GetUnits"))[1]
  local city = firstCity(o.P)
  local plot = unit ~= nil and Map.GetPlot(unit:GetX(), unit:GetY()) or nil
  local objects = {
    { "UnitManager", UnitManager }, { "CityManager", CityManager }, { "Cities", Cities }, { "Units", Units },
    { "Unit", unit }, { "Experience", call(unit, "GetExperience") }, { "City", city },
    { "BuildQueue", call(city, "GetBuildQueue") }, { "Techs", call(p, "GetTechs") }, { "Culture", call(p, "GetCulture") },
    { "Player", p }, { "Diplomacy", call(p, "GetDiplomacy") }, { "Treasury", call(p, "GetTreasury") }, { "Game", Game },
    { "Map", Map }, { "Plot", plot }, { "ImprovementBuilder", ImprovementBuilder }, { "CombatManager", CombatManager },
  }
  for _, pair in ipairs(objects) do
    log("introspect|" .. pair[1] .. "=" .. Civ6Ai_Orders.MethodNames(pair[2]))
  end
  -- Does a string parameter survive the network trip? Logged only (compare
  -- both PCs' logs); kept out of the result so it cannot skew the order hash.
  log("introspect|note_type=" .. type(params.Note) .. "|note=" .. tostring(params.Note))
  return true, "logged"
end

-- API survey: list what the synced side can call on cities, build queues,
-- districts, religion, trade, great people and governors, using the first
-- major civ that owns a city. Logged only; the result is just a count.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_API_SURVEY] = function(sender, o)
  local owner, city
  for id = 0, 62 do
    local p = Players[id]
    if p ~= nil and call(p, "IsAlive") and call(p, "IsMajor") then
      local c = firstCity(id)
      if c ~= nil then
        owner, city = id, c
        break
      end
    end
  end
  local p = owner ~= nil and Players[owner] or Players[o.P]
  local unit = sortedMembers(call(p, "GetUnits"))[1]
  local districts = call(city, "GetDistricts")
  local district = nil
  if districts ~= nil then
    local okD, list = pcall(function() return sortedMembers(districts) end)
    district = okD and list[1] or nil
  end
  local gp = call(Game, "GetGreatPeople")
  local objects = {
    { "City", city }, { "BuildQueue", call(city, "GetBuildQueue") }, { "CityDistricts", districts },
    { "District", district }, { "CityBuildings", call(city, "GetBuildings") }, { "CityCitizens", call(city, "GetCitizens") },
    { "CityReligion", call(city, "GetReligion") }, { "CityGold", call(city, "GetGold") }, { "CityGrowth", call(city, "GetGrowth") },
    { "CityTrade", call(city, "GetTrade") }, { "CityYields", call(city, "GetYields") },
    { "PlayerDistricts", call(p, "GetDistricts") }, { "PlayerReligion", call(p, "GetReligion") }, { "PlayerTrade", call(p, "GetTrade") },
    { "Governors", call(p, "GetGovernors") }, { "GreatPeoplePoints", call(p, "GetGreatPeoplePoints") },
    { "Resources", call(p, "GetResources") }, { "Influence", call(p, "GetInfluence") }, { "Stats", call(p, "GetStats") },
    { "AiMilitary", call(p, "GetAi_Military") },
    { "GameGreatPeople", gp }, { "GameReligion", call(Game, "GetReligion") }, { "TradeManager", call(Game, "GetTradeManager") },
    { "GameDiplomacy", call(Game, "GetGameDiplomacy") }, { "Quests", call(Game, "GetQuestsManager") },
    { "UnitGreatPerson", call(unit, "GetGreatPerson") }, { "UnitReligion", call(unit, "GetReligion") },
    { "PlayerManager", PlayerManager }, { "DealManager", DealManager },
  }
  local n = 0
  for _, pair in ipairs(objects) do
    local okM, names = pcall(Civ6Ai_Orders.MethodNames, pair[2])
    log("survey|" .. pair[1] .. "=" .. tostring(okM and names or ("error:" .. tostring(names))))
    n = n + 1
  end
  return true, "owner=" .. tostring(owner) .. ":objects=" .. n
end

-- Put an enemy next to unit U: a barbarian warrior, and with I == 1 also an
-- extra slinger for seat P (a ranged attacker for the attack checks).
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_SPAWN_ENEMY] = function(sender, o)
  local unit = Civ6Ai_Orders._Unit(o.P, o.U)
  if unit == nil then
    return false, "unit_not_found"
  end
  local barb = barbarianId()
  if barb == nil then
    return false, "no_barbarian_player"
  end
  local x, y = freeLandNear(unit:GetX(), unit:GetY())
  if x == nil then
    return false, "no_free_plot"
  end
  local ok, spawned = pcall(UnitManager.InitUnit, barb, "UNIT_WARRIOR", x, y)
  if not ok or spawned == nil then
    return false, "init_unit_failed:" .. tostring(spawned)
  end
  local note = "enemy=" .. tostring(call(spawned, "GetID")) .. "@" .. x .. "," .. y
  if o.I == 1 then
    local sx, sy = freeLandNear(unit:GetX(), unit:GetY())
    if sx ~= nil then
      local okS, slinger = pcall(UnitManager.InitUnit, o.P, "UNIT_SLINGER", sx, sy)
      note = note .. ":slinger=" .. tostring(okS and call(slinger, "GetID")) .. "@" .. sx .. "," .. sy
    end
  end
  return true, note
end

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_MELEE_MOVE] = function(sender, o)
  local unit = Civ6Ai_Orders._Unit(o.P, o.U)
  if unit == nil then
    return false, "unit_not_found"
  end
  if (call(unit, "GetMovesRemaining") or 0) <= 0 and UnitManager.RestoreMovement ~= nil then
    pcall(UnitManager.RestoreMovement, unit)
  end
  return Civ6Ai_Orders._MeleeStep(unit, o.X, o.Y)
end

-- Fallback combat: take damage off the enemy on X,Y directly.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_SCRIPTED_COMBAT] = function(sender, o)
  local plot = Map.GetPlot(o.X, o.Y)
  local target = nil
  for _, other in ipairs((plot ~= nil and Units ~= nil and Units.GetUnitsInPlot ~= nil) and (Units.GetUnitsInPlot(plot) or {}) or {}) do
    if other:GetOwner() ~= o.P then
      target = other
      break
    end
  end
  if target == nil then
    return false, "no_enemy_on_plot"
  end
  local before = call(target, "GetDamage") or 0
  local routes = {}
  if target.ChangeDamage ~= nil then
    local ok = pcall(target.ChangeDamage, target, 30)
    routes[#routes + 1] = "unit.ChangeDamage=" .. tostring(ok)
  end
  if (call(target, "GetDamage") or 0) == before and target.SetDamage ~= nil then
    local ok = pcall(target.SetDamage, target, before + 30)
    routes[#routes + 1] = "unit.SetDamage=" .. tostring(ok)
  end
  local after = call(target, "GetDamage") or 0
  return after ~= before, "damage=" .. before .. ">" .. after .. ":" .. table.concat(routes, ",")
end

-- Fallback production: create a warrior in seat P's first city directly.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_SCRIPTED_PRODUCTION] = function(sender, o)
  local city = firstCity(o.P)
  if city == nil then
    return false, "no_city"
  end
  local ok, unit = pcall(UnitManager.InitUnit, o.P, "UNIT_WARRIOR", city:GetX(), city:GetY())
  if not ok or unit == nil then
    return false, "init_unit_failed:" .. tostring(unit)
  end
  return true, "warrior=" .. tostring(call(unit, "GetID")) .. ":city=" .. tostring(city:GetID())
end

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_IMPROVEMENT] = function(sender, o)
  local plot = Map.GetPlot(o.X, o.Y)
  local row = GameInfo.Improvements ~= nil and GameInfo.Improvements["IMPROVEMENT_FARM"] or nil
  if plot == nil or row == nil or ImprovementBuilder == nil or ImprovementBuilder.SetImprovementType == nil then
    return false, "improvement_route_missing"
  end
  local before = call(plot, "GetImprovementType")
  local ok = pcall(ImprovementBuilder.SetImprovementType, plot, row.Index, o.P)
  local after = call(plot, "GetImprovementType")
  return ok and after == row.Index, "improvement=" .. tostring(before) .. ">" .. tostring(after)
end

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_EXPERIENCE] = function(sender, o)
  local unit = Civ6Ai_Orders._Unit(o.P, o.U)
  local exp = call(unit, "GetExperience")
  if exp == nil or exp.ChangeExperience == nil then
    return false, "experience_route_missing"
  end
  local before = call(exp, "GetExperiencePoints")
  local ok = pcall(exp.ChangeExperience, exp, 15)
  local after = call(exp, "GetExperiencePoints")
  return ok and after ~= before, "xp=" .. tostring(before) .. ">" .. tostring(after)
    .. ":can_promote=" .. tostring(call(exp, "CanPromote"))
end

-- A multi-tile move, walked along the engine's path (the real move route).
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_FAR_MOVE] = function(sender, o)
  local unit = Civ6Ai_Orders._Unit(o.P, o.U)
  if unit == nil then
    return false, "unit_not_found"
  end
  if (call(unit, "GetMovesRemaining") or 0) <= 0 and UnitManager.RestoreMovement ~= nil then
    pcall(UnitManager.RestoreMovement, unit)
  end
  local before = call(unit, "GetMovesRemaining")
  local ok, reason = Civ6Ai_Orders._Route("MoveUnitAlongPathForPlayer", o.P, o.U, o.X, o.Y)
  return ok, tostring(reason) .. ":target=" .. tostring(o.X) .. "," .. tostring(o.Y)
    .. ":moves=" .. tostring(before) .. ">" .. tostring(call(unit, "GetMovesRemaining"))
end

local function plotFree(plot)
  if plot == nil or call(plot, "IsWater") or call(plot, "IsImpassable") or call(plot, "IsMountain") or call(plot, "IsCity") then
    return false
  end
  if Units ~= nil and Units.GetUnitsInPlot ~= nil then
    for _ in ipairs(Units.GetUnitsInPlot(plot) or {}) do
      return false
    end
  end
  return true
end

-- Two free, adjacent land plots within 4 tiles of X,Y, scanned in a fixed
-- order so every PC picks the same ones. Returns ax, ay, bx, by.
local function probeSite(x, y)
  for r = 1, 4 do
    for dy = -r, r do
      for dx = -r, r do
        local a = Map.GetPlot(x + dx, y + dy)
        if plotFree(a) then
          local bx, by = freeLandNear(a:GetX(), a:GetY())
          if bx ~= nil then
            return a:GetX(), a:GetY(), bx, by
          end
        end
      end
    end
  end
  return nil
end

-- A fresh attacker for seat P (a warrior, or a slinger when ranged) next to a
-- fresh barbarian warrior, near unit U. Returns attacker, barb, or nil, why.
function Civ6Ai_Orders._ProbePair(o, ranged)
  local anchor = Civ6Ai_Orders._Unit(o.P, o.U)
  if anchor == nil then
    return nil, "unit_not_found"
  end
  local barb = barbarianId()
  if barb == nil then
    return nil, "no_barbarian_player"
  end
  local ax, ay, bx, by = probeSite(anchor:GetX(), anchor:GetY())
  if ax == nil then
    return nil, "no_free_plots"
  end
  local okA, attacker = pcall(UnitManager.InitUnit, o.P, ranged and "UNIT_SLINGER" or "UNIT_WARRIOR", ax, ay)
  local okB, enemy = pcall(UnitManager.InitUnit, barb, "UNIT_WARRIOR", bx, by)
  if not okA or attacker == nil or not okB or enemy == nil then
    return nil, "init_unit_failed"
  end
  if (call(attacker, "GetMovesRemaining") or 0) <= 0 and UnitManager.RestoreMovement ~= nil then
    pcall(UnitManager.RestoreMovement, attacker)
  end
  return attacker, enemy
end

-- Read-only look at the engine's combat calls, then one native route:
-- I = 0 melee step into the enemy with MoveUnit, I = 1 ranged forecast only,
-- I = 2 CombatManager.GenerateCombatResults. The enemy is remembered so the
-- next turn's damage check shows effects that land late.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_COMBAT_PROBE] = function(sender, o)
  local mode = num(o.I) or 0
  local attacker, enemy = Civ6Ai_Orders._ProbePair(o, mode == 1)
  if attacker == nil then
    return false, enemy
  end
  local ctype = Civ6Ai_Orders._CombatType(attacker)
  local notes = { "mode=" .. mode, "ctype=" .. tostring(ctype) }
  local okCan, can = pcall(CombatManager.CanAttackTarget, attacker:GetComponentID(), enemy:GetComponentID(), ctype)
  notes[#notes + 1] = "can=" .. tostring(okCan) .. "/" .. tostring(can)
  local toA, toD = Civ6Ai_Orders._Forecast(attacker, enemy, ctype)
  notes[#notes + 1] = "forecast=" .. tostring(toA) .. "/" .. tostring(toD)
  local before = call(enemy, "GetDamage") or 0
  local attBefore = call(attacker, "GetDamage") or 0
  if mode == 0 then
    local okStep = pcall(UnitManager.MoveUnit, attacker, enemy:GetX(), enemy:GetY())
    notes[#notes + 1] = "step=" .. tostring(okStep)
  elseif mode == 2 then
    local okGen, res = pcall(CombatManager.GenerateCombatResults, attacker:GetComponentID(), enemy:GetComponentID(), ctype)
    local keys = {}
    if type(res) == "table" then
      for k in pairs(res) do
        keys[#keys + 1] = tostring(k)
      end
      table.sort(keys)
    end
    notes[#notes + 1] = "generate=" .. tostring(okGen) .. "/" .. type(res) .. (okGen and "" or ("/" .. tostring(res)))
      .. "/keys=" .. table.concat(keys, ";")
  end
  local after = call(enemy, "GetDamage") or 0
  notes[#notes + 1] = "def_dmg=" .. before .. ">" .. after
  notes[#notes + 1] = "att_dmg=" .. attBefore .. ">" .. tostring(call(attacker, "GetDamage"))
  notes[#notes + 1] = "att_moves=" .. tostring(call(attacker, "GetMovesRemaining"))
  Game:SetProperty("CIV6AI_PROBE_" .. mode, { owner = enemy:GetOwner(), id = enemy:GetID(), dmg = after })
  -- ok means the forecast works; the notes carry what each route did.
  return toA ~= nil, table.concat(notes, ":")
end

-- Next turn: did any probe's enemy take damage after the probe had finished?
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_DAMAGE_CHECK] = function(sender, o)
  local notes = {}
  for mode = 0, 2 do
    local rec = Game:GetProperty("CIV6AI_PROBE_" .. mode)
    if type(rec) == "table" then
      local p = Players[rec.owner]
      local unit = p ~= nil and p:GetUnits():FindID(rec.id) or nil
      notes[#notes + 1] = "m" .. mode .. "=" .. tostring(rec.dmg) .. ">" .. (unit ~= nil and tostring(call(unit, "GetDamage")) or "gone")
    else
      notes[#notes + 1] = "m" .. mode .. "=none"
    end
  end
  return true, table.concat(notes, ":")
end

-- The real attack route on a fresh pair: I = 0 melee, I = 1 ranged.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_RESOLVED_ATTACK] = function(sender, o)
  local attacker, enemy = Civ6Ai_Orders._ProbePair(o, num(o.I) == 1)
  if attacker == nil then
    return false, enemy
  end
  return Civ6Ai_Orders._ResolveAttack(attacker, enemy:GetX(), enemy:GetY())
end

-- Can the model steer what the engine AI builds, using only real engine
-- levers? I == 0 applies three levers, I == 1 reads back (run on later turns),
-- I == 2 undoes the unit switch.
--   seat P: the engine AI's own unit-construction switch (AiMilitary) and the
--           first city's citizen focus set to production.
--   seat U: a district placed (not built) in its first city, to see whether
--           the AI then chooses to build it.
Civ6Ai_Orders._steer = Civ6Ai_Orders._steer or {}

local function productionName(city)
  local bq = call(city, "GetBuildQueue")
  local cur = call(bq, "CurrentlyBuilding")
  if type(cur) == "number" and GameInfo ~= nil and GameInfo.Types ~= nil then
    for row in GameInfo.Types() do
      if row.Hash == cur then
        return row.Type
      end
    end
  end
  return tostring(cur)
end

local function isUnitName(name)
  return string.sub(tostring(name), 1, 5) == "UNIT_"
end

local function cityLines(owner)
  local parts = {}
  for _, city in ipairs(sortedMembers(call(Players[owner], "GetCities"))) do
    local name = productionName(city)
    parts[#parts + 1] = tostring(city:GetID()) .. "=" .. name .. (isUnitName(name) and "(unit)" or "")
  end
  return table.concat(parts, ",")
end

local function aiMilitary(owner)
  return call(Players[owner], "GetAi_Military")
end

-- Whether a district's own tech and civic requirements are met. Used instead
-- of BuildQueue:CanProduce, which answered false for every district in a
-- gameplay script (LAN round 2) even while the AI was building a Campus.
local function districtUnlocked(owner, row)
  if row.TraitType ~= nil or row.DistrictType == "DISTRICT_CITY_CENTER" or row.DistrictType == "DISTRICT_WONDER" then
    return false
  end
  if row.PrereqTech ~= nil then
    local t = GameInfo.Technologies[row.PrereqTech]
    if t == nil or call(call(Players[owner], "GetTechs"), "HasTech", t.Index) ~= true then
      return false
    end
  end
  if row.PrereqCivic ~= nil then
    local c = GameInfo.Civics[row.PrereqCivic]
    if c == nil or call(call(Players[owner], "GetCulture"), "HasCivic", c.Index) ~= true then
      return false
    end
  end
  return true
end

-- The first unlocked district the city does not have, with a plot the engine
-- says can take it. Returns row, plot, how legality was checked.
local function districtSite(owner, city)
  local bq = call(city, "GetBuildQueue")
  local owned = {}
  for _, v in ipairs(call(city, "GetOwnedPlots") or {}) do
    local plot = type(v) == "number" and Map.GetPlotByIndex(v) or v
    if plot ~= nil then
      owned[#owned + 1] = plot
    end
  end
  table.sort(owned, function(a, b) return a:GetIndex() < b:GetIndex() end)
  local seen = {}
  for row in GameInfo.Districts() do
    if districtUnlocked(owner, row) and not call(bq, "HasDistrictBeenPlaced", row.Index) then
      local hasCheck = owned[1] ~= nil and owned[1].CanHaveDistrict ~= nil
      for _, plot in ipairs(owned) do
        if hasCheck then
          if call(plot, "CanHaveDistrict", row.Index, owner, city:GetID()) == true then
            return row, plot, "CanHaveDistrict"
          end
        elseif not call(plot, "IsWater") and not call(plot, "IsMountain") and not call(plot, "IsCity")
            and (call(plot, "GetDistrictType") or -1) < 0 and (call(plot, "GetResourceType") or -1) < 0
            and Map.GetPlotDistance(plot:GetX(), plot:GetY(), city:GetX(), city:GetY()) == 1 then
          return row, plot, "plain_land_next_to_city"
        end
      end
      seen[#seen + 1] = row.DistrictType .. "(" .. (hasCheck and "no_legal_plot" or "no_plot") .. ",can=" .. tostring(call(bq, "CanProduce", row.Hash, true)) .. ")"
    end
  end
  return nil, nil, "no_district[" .. table.concat(seen, ",") .. "]"
end

-- Lever 3: a placed (unbuilt) district in seat q's first city. Tried again on
-- each read until the city can take one.
local function steerPlaceDistrict(st)
  if st.district ~= nil then
    return "district=already"
  end
  local qCity = st.q ~= nil and firstCity(st.q) or nil
  if qCity == nil then
    return "district=no_city"
  end
  local row, plot, how = districtSite(st.q, qCity)
  if row == nil or plot == nil then
    return "district=" .. tostring(row and row.DistrictType) .. ":" .. how
  end
  local bq = qCity:GetBuildQueue()
  local tries = {}
  local unpackArgs = table.unpack or unpack
  for _, args in ipairs({ { row.Index, plot:GetIndex(), 0 }, { row.Index, plot:GetIndex() } }) do
    local okC, err = pcall(bq.CreateIncompleteDistrict, bq, unpackArgs(args))
    tries[#tries + 1] = tostring(okC) .. (okC and "" or ("(" .. tostring(err) .. ")"))
    if call(bq, "HasDistrictBeenPlaced", row.Index) then
      break
    end
  end
  local placed = call(bq, "HasDistrictBeenPlaced", row.Index)
  st.district, st.qCity = row, qCity:GetID()
  return "district=" .. row.DistrictType .. "@" .. plot:GetX() .. "," .. plot:GetY() .. "(" .. how .. "):tries="
    .. table.concat(tries, "/") .. ":placed=" .. tostring(placed) .. ":now=" .. productionName(qCity)
end

local function steerApply(o)
  local prev = Civ6Ai_Orders._steer or {}
  local st = { p = o.P, q = o.U, r = o.X, district = prev.district, qCity = prev.qCity }
  Civ6Ai_Orders._steer = st
  local out = {}
  -- Lever 1: the engine AI's unit-construction switch.
  local ai = aiMilitary(o.P)
  local before = call(ai, "CanConstructUnits")
  local okAllow = ai ~= nil and ai.AllowUnitConstruction ~= nil and pcall(ai.AllowUnitConstruction, ai, false)
  out[#out + 1] = "allow_units_off=" .. tostring(okAllow) .. ":can=" .. tostring(before) .. ">" .. tostring(call(ai, "CanConstructUnits"))
  out[#out + 1] = "p_cities=" .. cityLines(o.P)
  -- Lever 2: the first city's citizen focus.
  local city = firstCity(o.P)
  local citizens = call(city, "GetCitizens")
  local prod = GameInfo.Yields["YIELD_PRODUCTION"]
  if citizens ~= nil and prod ~= nil and citizens.SetFavoredYield ~= nil then
    local okF = pcall(citizens.SetFavoredYield, citizens, prod.Index, true)
    out[#out + 1] = "focus_production=" .. tostring(okF) .. ":favored=" .. tostring(call(citizens, "IsYieldFavored", prod.Index))
    st.focusCity = city:GetID()
  else
    out[#out + 1] = "focus_production=no_route"
  end
  if o.U ~= nil then
    out[#out + 1] = "q_cities=" .. cityLines(o.U)
  end
  out[#out + 1] = steerPlaceDistrict(st)
  return true, table.concat(out, ";")
end

local function steerRead()
  local st = Civ6Ai_Orders._steer
  if st.p == nil then
    return false, "not_applied"
  end
  local out = {}
  out[#out + 1] = "can_units=" .. tostring(call(aiMilitary(st.p), "CanConstructUnits"))
  out[#out + 1] = "p_cities=" .. cityLines(st.p)
  if st.focusCity ~= nil then
    local city = call(Players[st.p], "GetCities")
    city = city ~= nil and call(city, "FindID", st.focusCity) or nil
    out[#out + 1] = "focus=" .. tostring(call(call(city, "GetCitizens"), "IsYieldFavored", GameInfo.Yields["YIELD_PRODUCTION"].Index))
  end
  if st.q ~= nil then
    out[#out + 1] = "q_cities=" .. cityLines(st.q)
  end
  if st.r ~= nil then
    out[#out + 1] = "control_cities=" .. cityLines(st.r)
  end
  if st.district == nil then
    out[#out + 1] = steerPlaceDistrict(st)
  else
    local cities = call(Players[st.q], "GetCities")
    local city = cities ~= nil and call(cities, "FindID", st.qCity) or nil
    local bq = call(city, "GetBuildQueue")
    out[#out + 1] = "district=" .. st.district.DistrictType .. ":placed=" .. tostring(call(bq, "HasDistrictBeenPlaced", st.district.Index))
      .. ":has=" .. tostring(call(call(city, "GetDistricts"), "HasDistrict", st.district.Index))
      .. ":progress=" .. tostring(call(bq, "HasDistrictProductionProgress", st.district.Index))
      .. ":now=" .. productionName(city)
  end
  return true, table.concat(out, ";")
end

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_PRODUCTION_STEER] = function(sender, o)
  if o.P == nil or Players[o.P] == nil then
    return false, "no_seat"
  end
  if o.I == 3 then
    -- Test setup only: give seat U Writing so its city can place a Campus.
    local techs = call(Players[o.U or o.P], "GetTechs")
    local row = GameInfo.Technologies ~= nil and GameInfo.Technologies["TECH_WRITING"] or nil
    if techs == nil or row == nil or techs.SetTech == nil then
      return false, "no_tech_route"
    end
    local ok = pcall(techs.SetTech, techs, row.Index, true)
    local has = call(techs, "HasTech", row.Index) == true
    -- Place the district now, before the AI picks its own next build.
    local st = { p = o.P, q = o.U or o.P, r = o.X }
    Civ6Ai_Orders._steer = st
    local placed = has and steerPlaceDistrict(st) or "district=skipped"
    return ok and has, "writing=" .. tostring(has) .. ";" .. placed
  elseif o.I == 1 then
    return steerRead()
  elseif o.I == 2 then
    local ai = aiMilitary(Civ6Ai_Orders._steer.p or o.P)
    local ok = ai ~= nil and ai.AllowUnitConstruction ~= nil and pcall(ai.AllowUnitConstruction, ai, true)
    return ok == true, "allow_units_on=" .. tostring(ok) .. ":can=" .. tostring(call(ai, "CanConstructUnits"))
  end
  return steerApply(o)
end


-- ---------------------------------------------------------------------------
-- Build strategies (Data/Civ6Ai_Strategies.sql). The engine AI calls these
-- before each player's turn ('Call Lua Function' strategy conditions); a true
-- answer switches on that strategy's one-item favoured list. The answer comes
-- only from the synced game property CIV6AI_FORCE_<player>, so every PC gives
-- the same answer.
-- ---------------------------------------------------------------------------
Civ6Ai_Orders.FORCE_TARGETS = {
  { fn = "Civ6AiForceArcher", id = 1, kind = "unit", item = "UNIT_ARCHER", tech = "TECH_ARCHERY" },
  { fn = "Civ6AiForceGranary", id = 2, kind = "building", item = "BUILDING_GRANARY", tech = "TECH_POTTERY" },
  { fn = "Civ6AiForceCampus", id = 3, kind = "district", item = "DISTRICT_CAMPUS", tech = "TECH_WRITING" },
}
Civ6Ai_Orders._forceSeen = Civ6Ai_Orders._forceSeen or {}

function Civ6Ai_Orders.ForceTarget(owner)
  return num(Game:GetProperty("CIV6AI_FORCE_" .. tostring(owner))) or 0
end

function Civ6Ai_Orders._ForceCondition(target, owner, threshold)
  local active = Civ6Ai_Orders.ForceTarget(owner) == target.id
  local turn = Game.GetCurrentGameTurn()
  if Civ6Ai_Orders._forceSeenTurn ~= turn then
    Civ6Ai_Orders._forceSeen, Civ6Ai_Orders._forceSeenTurn = {}, turn
  end
  local key = tostring(owner) .. ":" .. target.id
  local seen = Civ6Ai_Orders._forceSeen
  seen[key] = (seen[key] or 0) + 1
  if seen[key] == 1 and (active or Civ6Ai_Orders.ForceTarget(owner) ~= 0) then
    log("strategy_call|turn=" .. tostring(Game.GetCurrentGameTurn()) .. "|player=" .. tostring(owner)
      .. "|fn=" .. target.fn .. "|active=" .. tostring(active))
  end
  return active
end

function Civ6Ai_Orders.RegisterForceStrategies()
  for _, target in ipairs(Civ6Ai_Orders.FORCE_TARGETS) do
    GameEvents[target.fn].Add(function(owner, threshold)
      local ok, v = pcall(Civ6Ai_Orders._ForceCondition, target, owner, threshold)
      return ok and v == true
    end)
  end
end

-- How far seat owner has got with a target: units owned, building built,
-- district built or placed, and what each city is producing.
local function forceProgress(owner, target)
  local player = Players[owner]
  if target.kind == "unit" then
    local n = 0
    local row = GameInfo.Units[target.item]
    for _, u in ipairs(sortedMembers(call(player, "GetUnits"))) do
      if row ~= nil and u:GetType() == row.Index then
        n = n + 1
      end
    end
    return "have=" .. n
  end
  local built, placed = 0, 0
  for _, city in ipairs(sortedMembers(call(player, "GetCities"))) do
    if target.kind == "building" then
      local row = GameInfo.Buildings[target.item]
      if row ~= nil and call(call(city, "GetBuildings"), "HasBuilding", row.Index) == true then
        built = built + 1
      end
    else
      local row = GameInfo.Districts[target.item]
      if row ~= nil and call(call(city, "GetDistricts"), "HasDistrict", row.Index) == true then
        built = built + 1
      end
      if row ~= nil and call(call(city, "GetBuildQueue"), "HasDistrictBeenPlaced", row.Index) == true then
        placed = placed + 1
      end
    end
  end
  return "built=" .. built .. (target.kind == "district" and (":placed=" .. placed) or "")
end

-- Every seat's progress on every target (the control seat is compared on all).
local function forceRead(seats)
  local out = {}
  for _, owner in ipairs(seats) do
    local parts = { "seat" .. owner .. "[force=" .. Civ6Ai_Orders.ForceTarget(owner) .. "]" }
    for _, target in ipairs(Civ6Ai_Orders.FORCE_TARGETS) do
      parts[#parts + 1] = target.item .. ":" .. forceProgress(owner, target)
    end
    parts[#parts + 1] = "cities=" .. cityLines(owner)
    out[#out + 1] = table.concat(parts, ",")
  end
  return table.concat(out, ";")
end

-- Test: switch on one build strategy per seat. Seats P, U, X get targets 1, 2,
-- 3; seat Y is the untouched control. I == 3 is setup (every seat gets all
-- three unlocking techs, then the strategies are switched on), I == 1 reads
-- back, I == 2 switches them off.
Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_FORCE_BUILD] = function(sender, o)
  local seats, forced = {}, { o.P, o.U, o.X }
  for _, s in ipairs({ o.P, o.U, o.X, o.Y }) do
    if s ~= nil and Players[s] ~= nil then
      seats[#seats + 1] = s
    end
  end
  if #seats == 0 then
    return false, "no_seat"
  end
  if o.I == 3 then
    local out = {}
    for _, s in ipairs(seats) do
      local techs = call(Players[s], "GetTechs")
      local got = {}
      for _, target in ipairs(Civ6Ai_Orders.FORCE_TARGETS) do
        local row = GameInfo.Technologies[target.tech]
        if techs ~= nil and techs.SetTech ~= nil and row ~= nil then
          pcall(techs.SetTech, techs, row.Index, true)
        end
        got[#got + 1] = target.tech .. "=" .. tostring(row ~= nil and call(techs, "HasTech", row.Index) == true)
      end
      out[#out + 1] = "seat" .. s .. "[" .. table.concat(got, ",") .. "]"
    end
    for i, target in ipairs(Civ6Ai_Orders.FORCE_TARGETS) do
      if forced[i] ~= nil and Players[forced[i]] ~= nil then
        Game:SetProperty("CIV6AI_FORCE_" .. forced[i], target.id)
      end
    end
    return true, table.concat(out, ";") .. ";" .. forceRead(seats)
  elseif o.I == 2 then
    for _, s in ipairs(seats) do
      Game:SetProperty("CIV6AI_FORCE_" .. s, 0)
    end
    return true, "force_off;" .. forceRead(seats)
  end
  return true, forceRead(seats)
end


-- ---------------------------------------------------------------------------
-- Build priorities (Data/Civ6Ai_Priorities.sql, generated with this table by
-- scripts/gen_priorities.py). One engine AI strategy per category and level;
-- each strategy is on while the synced property CIV6AI_PRIO_<player>_<id>
-- equals its level. A player has at most one posture and up to
-- PRIORITY_MAX_FOCUS other categories on. The engine AI still picks the
-- concrete item and city; the strategies only shift what it favours.
-- ---------------------------------------------------------------------------
-- BEGIN GENERATED PRIORITY_IDS (scripts/gen_priorities.py)
Civ6Ai_Orders.PRIORITY_IDS = {
  { id = 1, key = "peace", group = "posture" },
  { id = 2, key = "war", group = "posture" },
  { id = 3, key = "total_war", group = "posture" },
  { id = 4, key = "naval_war", group = "posture" },
  { id = 5, key = "naval_total_war", group = "posture" },
  { id = 6, key = "defense", group = "posture" },
  { id = 7, key = "air_power", group = "posture" },
  { id = 8, key = "science_victory", group = "focus" },
  { id = 9, key = "culture_victory", group = "focus" },
  { id = 10, key = "religious_victory", group = "focus" },
  { id = 11, key = "diplomatic_victory", group = "focus" },
  { id = 12, key = "domination_victory", group = "focus" },
  { id = 13, key = "fix_bankruptcy", group = "focus" },
  { id = 14, key = "gold", group = "focus" },
  { id = 15, key = "trade", group = "focus" },
  { id = 16, key = "amenities", group = "focus" },
  { id = 17, key = "growth", group = "focus" },
  { id = 18, key = "production", group = "focus" },
  { id = 19, key = "expansion", group = "focus" },
  { id = 20, key = "improvements", group = "focus" },
  { id = 21, key = "wonders", group = "focus" },
  { id = 22, key = "great_people", group = "focus" },
  { id = 23, key = "faith", group = "focus" },
  { id = 24, key = "exploration", group = "focus" },
  { id = 26, key = "naval", group = "focus" },
  { id = 25, key = "settlers_only", group = "focus" },
}
Civ6Ai_Orders.PRIORITY_MAX_FOCUS = 3
Civ6Ai_Orders.PRIORITY_MAX_LEVEL = 3
-- END GENERATED PRIORITY_IDS

function Civ6Ai_Orders._PriorityById(id)
  for _, cat in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
    if cat.id == id then
      return cat
    end
  end
  return nil
end

function Civ6Ai_Orders.PriorityLevel(owner, id)
  return num(Game:GetProperty("CIV6AI_PRIO_" .. tostring(owner) .. "_" .. tostring(id))) or 0
end

-- Active priorities of one player: list of { id, key, group, level }, by id.
function Civ6Ai_Orders.PriorityLevels(owner)
  local out = {}
  for _, cat in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
    local lvl = Civ6Ai_Orders.PriorityLevel(owner, cat.id)
    if lvl > 0 then
      out[#out + 1] = { id = cat.id, key = cat.key, group = cat.group, level = lvl }
    end
  end
  return out
end

local function prioText(owner)
  local parts = {}
  for _, a in ipairs(Civ6Ai_Orders.PriorityLevels(owner)) do
    parts[#parts + 1] = a.key .. ":" .. a.level
  end
  return #parts > 0 and table.concat(parts, "+") or "none"
end
Civ6Ai_Orders._PrioText = prioText

local function setPrio(owner, id, level)
  Game:SetProperty("CIV6AI_PRIO_" .. tostring(owner) .. "_" .. tostring(id), level)
end

-- PRIORITY order: P = player, I = category id (0 clears every category),
-- X = level 0..PRIORITY_MAX_LEVEL (0 switches that category off).
function Civ6Ai_Orders._SetPriority(sender, o)
  local owner = o.P
  local problem = Civ6Ai_Orders._Authorize(sender, owner)
  if problem ~= nil then
    return false, problem
  end
  if call(Players[owner], "IsMajor") == false then
    return false, "not_major"
  end
  local id, level = o.I, o.X or 0
  if level < 0 or level > Civ6Ai_Orders.PRIORITY_MAX_LEVEL or level ~= math.floor(level) then
    return false, "bad_level"
  end
  if id == 0 then
    for _, cat in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
      setPrio(owner, cat.id, 0)
    end
    return true, "prio_cleared|player=" .. tostring(owner)
  end
  local cat = id ~= nil and Civ6Ai_Orders._PriorityById(id) or nil
  if cat == nil then
    return false, "bad_priority"
  end
  if level > 0 and cat.group == "posture" then
    for _, other in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
      if other.group == "posture" and other.id ~= id then
        setPrio(owner, other.id, 0)
      end
    end
  elseif level > 0 and Civ6Ai_Orders.PriorityLevel(owner, id) == 0 then
    local focus = 0
    for _, a in ipairs(Civ6Ai_Orders.PriorityLevels(owner)) do
      if a.group ~= "posture" then
        focus = focus + 1
      end
    end
    if focus >= Civ6Ai_Orders.PRIORITY_MAX_FOCUS then
      return false, "too_many_focus"
    end
  end
  setPrio(owner, id, level)
  return true, "prio|player=" .. tostring(owner) .. "|set=" .. cat.key .. ":" .. level .. "|now=" .. prioText(owner)
end

Civ6Ai_Orders._prioSeen = Civ6Ai_Orders._prioSeen or {}

function Civ6Ai_Orders._PrioCondition(id, level, owner)
  local active = Civ6Ai_Orders.PriorityLevel(owner, id) == level
  if active then
    local turn = Game.GetCurrentGameTurn()
    if Civ6Ai_Orders._prioSeenTurn ~= turn then
      Civ6Ai_Orders._prioSeen, Civ6Ai_Orders._prioSeenTurn = {}, turn
    end
    local key = tostring(owner) .. ":" .. id
    if not Civ6Ai_Orders._prioSeen[key] then
      Civ6Ai_Orders._prioSeen[key] = true
      local cat = Civ6Ai_Orders._PriorityById(id)
      log("prio_call|turn=" .. tostring(turn) .. "|player=" .. tostring(owner) .. "|cat=" .. tostring(cat and cat.key)
        .. "|level=" .. level)
    end
  end
  return active
end

function Civ6Ai_Orders.RegisterPriorityStrategies()
  local n = 0
  for _, cat in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
    for level = 1, Civ6Ai_Orders.PRIORITY_MAX_LEVEL do
      local ev = GameEvents["Civ6AiPrio_" .. cat.id .. "_" .. level]
      if ev ~= nil and ev.Add ~= nil then
        local id, lvl = cat.id, level
        ev.Add(function(owner, threshold)
          local ok, v = pcall(Civ6Ai_Orders._PrioCondition, id, lvl, owner)
          return ok and v == true
        end)
        n = n + 1
      end
    end
  end
  return n
end

-- Early-game build order for engine-AI seats (Data/Civ6Ai_Strategies.sql).
-- Game state only (synced), so every PC answers the same. "expand" or "threat"
-- for a seat the model drives with fewer than EARLY_CITY_TARGET cities by
-- EARLY_TURN; nil otherwise. Same rule as InGame Civ6Ai_Production.
Civ6Ai_Orders.EARLY_CITY_TARGET = 3
Civ6Ai_Orders.EARLY_TURN = 60
Civ6Ai_Orders.THREAT_RADIUS = 6
Civ6Ai_Orders._earlyCache = Civ6Ai_Orders._earlyCache or {}

-- Threat = hostile land combat power near our cities that our own army near
-- them does not already cover. Hostile: a barbarian, or a player we are at war
-- with. Scouts and civilians are not a threat; a barbarian camp within
-- CAMP_RADIUS counts as one unit; a war with a major counts WAR_WEIGHT. Our
-- land combat units (not recon) within THREAT_RADIUS of a city defend. Only
-- units on tiles the seat sees count (camps: revealed tiles). Threat while
-- hostiles > defenders (a tie is not a threat), so a seat that already built its answer goes
-- back to expanding (T36 live: a barbarian scout two tiles out kept P0 in
-- threat from T13 with nine military units and zero settlers).
Civ6Ai_Orders.CAMP_RADIUS = 4
Civ6Ai_Orders.WAR_WEIGHT = 2

local function landCombat(unit)
  local row = GameInfo.Units ~= nil and GameInfo.Units[call(unit, "GetType")] or nil
  if row == nil then
    return true
  end
  if row.FormationClass ~= nil and row.FormationClass ~= "FORMATION_CLASS_LAND_COMBAT" then
    return false
  end
  if row.PromotionClass == "PROMOTION_CLASS_RECON" then
    return false
  end
  return (tonumber(row.Combat) or 0) > 0 or (tonumber(row.RangedCombat) or 0) > 0
end
Civ6Ai_Orders._LandCombat = landCombat

function Civ6Ai_Orders.ThreatInfo(owner)
  local player = Players[owner]
  local diplo = call(player, "GetDiplomacy")
  local hostiles, defenders = 0, 0
  for _, other in ipairs(PlayerManager.GetAliveMajorIDs()) do
    if other ~= owner and call(diplo, "IsAtWarWith", other) == true then
      hostiles = hostiles + Civ6Ai_Orders.WAR_WEIGHT
      break
    end
  end
  local camp = GameInfo.Improvements["IMPROVEMENT_BARBARIAN_CAMP"]
  local campIndex = camp ~= nil and camp.Index or nil
  local hostile = {}
  local function isHostile(o)
    if o == nil or o < 0 or o == owner then return false end
    if hostile[o] == nil then
      hostile[o] = call(Players[o], "IsBarbarian") == true or call(diplo, "IsAtWarWith", o) == true
    end
    return hostile[o]
  end
  -- Only what the seat can see: hostile units on visible tiles, camps on
  -- revealed tiles (counting fogged units leaked hidden information).
  local vis = PlayersVisibility ~= nil and PlayersVisibility[owner] or nil
  local function visible(x, y)
    if vis == nil then return true end
    local ok, v = pcall(vis.IsVisible, vis, x, y)
    return not ok or v == true
  end
  local function revealed(x, y)
    if vis == nil then return true end
    local ok, v = pcall(vis.IsRevealed, vis, x, y)
    return not ok or v == true
  end
  local r = Civ6Ai_Orders.THREAT_RADIUS
  local seen = {}
  local cities = sortedMembers(call(player, "GetCities"))
  for _, c in ipairs(cities) do
    local cx, cy = c:GetX(), c:GetY()
    for dx = -r, r do
      for dy = -r, r do
        local plot = Map.GetPlot(cx + dx, cy + dy)
        if plot ~= nil then
          local px, py = plot:GetX(), plot:GetY()
          local key = px .. "," .. py
          local d = Map.GetPlotDistance(cx, cy, px, py)
          if d <= r and not seen[key] then
            seen[key] = true
            if campIndex ~= nil and d <= Civ6Ai_Orders.CAMP_RADIUS and plot:GetImprovementType() == campIndex
                and revealed(px, py) then
              hostiles = hostiles + 1
            end
            local seenHere = visible(px, py)
            for _, u in ipairs(Units.GetUnitsInPlot(plot) or {}) do
              local o = u:GetOwner()
              if o == owner then
                if landCombat(u) then defenders = defenders + 1 end
              elseif seenHere and isHostile(o) and landCombat(u) then
                hostiles = hostiles + 1
              end
            end
          end
        end
      end
    end
  end
  return hostiles, defenders
end

function Civ6Ai_Orders.ThreatNear(owner)
  local hostiles, defenders = Civ6Ai_Orders.ThreatInfo(owner)
  -- Threatened only while visible hostiles outnumber our army there (a tie
  -- is not a threat).
  return hostiles > defenders, hostiles, defenders
end

-- Most cities this seat has ever held (synced Game property, raised at turn start).
-- The early rules are for a new empire: a seat that reached EARLY_CITY_TARGET
-- and then lost cities does not go back to settler-first.
function Civ6Ai_Orders.PeakCities(owner)
  local key = "CIV6AI_PEAK_CITIES_" .. tostring(owner)
  local peak = num(Game:GetProperty(key)) or 0
  local cities = call(Players[owner], "GetCities")
  local n = num(call(cities, "GetCount")) or #sortedMembers(cities)
  if n > peak then
    Game:SetProperty(key, n)
    peak = n
  end
  return peak, n
end

-- The vanilla STRATEGY_RAPID_EXPANSION conditions: no city under threat and no
-- war with a major (Victories.xml "Cities Under Threat" / "Major Civ Wars").
function Civ6Ai_Orders.AtWarWithMajor(owner)
  local diplo = call(Players[owner], "GetDiplomacy")
  if diplo == nil or PlayerManager == nil then
    return false
  end
  for _, other in ipairs(PlayerManager.GetAliveMajorIDs()) do
    if other ~= owner and call(diplo, "IsAtWarWith", other) == true then
      return true
    end
  end
  return false
end

-- Early-expansion rules apply while the seat is a new empire: 1..2 cities now,
-- never held EARLY_CITY_TARGET, not at war with a major, no city threatened.
function Civ6Ai_Orders.EarlyOpen(owner)
  local p = Players ~= nil and Players[owner] or nil
  if p == nil or call(p, "IsMajor") ~= true then
    return false, "not_major"
  end
  local peak, n = Civ6Ai_Orders.PeakCities(owner)
  if n < 1 or peak >= Civ6Ai_Orders.EARLY_CITY_TARGET then
    return false, "cities=" .. tostring(n) .. ":peak=" .. tostring(peak)
  end
  if Civ6Ai_Orders.AtWarWithMajor(owner) then
    return false, "major_war"
  end
  local ok, threat = pcall(Civ6Ai_Orders.ThreatNear, owner)
  if ok and threat == true then
    return false, "city_threatened"
  end
  return true, ""
end

local mode_detail = ""
function Civ6Ai_Orders.EarlyMode(owner)
  local turn = Game.GetCurrentGameTurn()
  local key = tostring(owner) .. ":" .. tostring(turn)
  local cached = Civ6Ai_Orders._earlyCache[key]
  if cached ~= nil then
    return cached ~= "" and cached or nil
  end
  local mode = ""
  mode_detail = ""
  local player = Players[owner]
  if player ~= nil and call(player, "IsMajor") == true and turn <= Civ6Ai_Orders.EARLY_TURN
      and #Civ6Ai_Orders.PriorityLevels(owner) > 0 then
    local peak, n = Civ6Ai_Orders.PeakCities(owner)
    if n >= 1 and peak < Civ6Ai_Orders.EARLY_CITY_TARGET then
      local ok, threat, h, d = pcall(Civ6Ai_Orders.ThreatNear, owner)
      mode = (ok and threat == true) and "threat" or "expand"
      if ok then
        mode_detail = "|hostiles=" .. tostring(h) .. "|defenders=" .. tostring(d)
      end
    end
  end
  Civ6Ai_Orders._earlyCache[key] = mode
  if mode ~= "" then
    log("early_mode|turn=" .. tostring(turn) .. "|player=" .. tostring(owner) .. "|mode=" .. mode .. mode_detail)
  end
  return mode ~= "" and mode or nil
end

-- Early settle levers (Data/Civ6Ai_Strategies.sql CIV6AI_STRATEGY_EARLY_SETTLE):
-- an AI major (not human) with 1 or 2 cities. Synced state only (city count).
function Civ6Ai_Orders.EarlySettle(owner)
  local p = Players ~= nil and Players[owner] or nil
  if p == nil or call(p, "IsHuman") == true then
    -- AI strategies only steer the game's own AI; a human seat has none.
    return false
  end
  return (Civ6Ai_Orders.EarlyOpen(owner)) == true
end

function Civ6Ai_Orders.RegisterEarlyStrategies()
  local fn = "Civ6AiEarlySettle"
  local settleEv = GameEvents ~= nil and GameEvents[fn] or nil
  if settleEv ~= nil and settleEv.Add ~= nil then
    settleEv.Add(function(owner, threshold)
      local ok, yes = pcall(Civ6Ai_Orders.EarlySettle, owner)
      return ok and yes == true
    end)
  end
  local early = { Civ6AiEarlyExpand = "expand", Civ6AiEarlyThreat = "threat" }
  for _, fn in ipairs(sortedKeys(early)) do
    local want = early[fn]
    local ev = GameEvents[fn]
    if ev ~= nil and ev.Add ~= nil then
      ev.Add(function(owner, threshold)
        local ok, mode = pcall(Civ6Ai_Orders.EarlyMode, owner)
        return ok and mode == want
      end)
    end
  end
end

-- Test: priority read-back. Seats P, U, X, Y. I == 3 grants every seat the
-- same unlocking techs (so all can build ships, campuses, markets); I == 1
-- reads each seat's units by formation, districts, production and priorities.
Civ6Ai_Orders.PRIORITY_TEST_TECHS = {
  "TECH_POTTERY", "TECH_ARCHERY", "TECH_SAILING", "TECH_BRONZE_WORKING", "TECH_WRITING",
  "TECH_CELESTIAL_NAVIGATION", "TECH_CURRENCY", "TECH_MASONRY", "TECH_ASTROLOGY", "TECH_IRRIGATION",
}

local function prioRead(owner)
  local player = Players[owner]
  local counts = { land = 0, naval = 0, civ = 0, other = 0 }
  for _, u in ipairs(sortedMembers(call(player, "GetUnits"))) do
    local row = GameInfo.Units[u:GetType()]
    local fc = row and row.FormationClass or ""
    if fc == "FORMATION_CLASS_LAND_COMBAT" then
      counts.land = counts.land + 1
    elseif fc == "FORMATION_CLASS_NAVAL" then
      counts.naval = counts.naval + 1
    elseif fc == "FORMATION_CLASS_CIVILIAN" then
      counts.civ = counts.civ + 1
    else
      counts.other = counts.other + 1
    end
  end
  local dist, nb, ncity = {}, 0, 0
  for _, city in ipairs(sortedMembers(call(player, "GetCities"))) do
    ncity = ncity + 1
    for row in GameInfo.Districts() do
      if row.DistrictType ~= "DISTRICT_CITY_CENTER" and call(call(city, "GetDistricts"), "HasDistrict", row.Index) == true then
        local short = string.gsub(row.DistrictType, "^DISTRICT_", "")
        dist[#dist + 1] = short
      end
    end
    for row in GameInfo.Buildings() do
      if call(call(city, "GetBuildings"), "HasBuilding", row.Index) == true then
        nb = nb + 1
      end
    end
  end
  return "seat" .. owner .. "[prio=" .. prioText(owner) .. ",cities=" .. ncity .. ",land=" .. counts.land
    .. ",naval=" .. counts.naval .. ",civilian=" .. counts.civ .. ",other=" .. counts.other .. ",buildings=" .. nb
    .. ",districts=" .. (#dist > 0 and table.concat(dist, "/") or "none") .. ",prod=" .. cityLines(owner) .. "]"
end

Civ6Ai_Orders.Tests[Civ6Ai_Orders.K.TEST_PRIORITY] = function(sender, o)
  local seats = {}
  for _, s in ipairs({ o.P, o.U, o.X, o.Y }) do
    if s ~= nil and s >= 0 and Players[s] ~= nil then
      seats[#seats + 1] = s
    end
  end
  if #seats == 0 then
    return false, "no_seat"
  end
  local out = {}
  if o.I == 3 then
    for _, s in ipairs(seats) do
      local techs = call(Players[s], "GetTechs")
      local got = 0
      for _, t in ipairs(Civ6Ai_Orders.PRIORITY_TEST_TECHS) do
        local row = GameInfo.Technologies[t]
        if techs ~= nil and techs.SetTech ~= nil and row ~= nil then
          pcall(techs.SetTech, techs, row.Index, true)
          if call(techs, "HasTech", row.Index) == true then
            got = got + 1
          end
        end
      end
      out[#out + 1] = "seat" .. s .. "_techs=" .. got .. "/" .. #Civ6Ai_Orders.PRIORITY_TEST_TECHS
    end
  end
  for _, s in ipairs(seats) do
    out[#out + 1] = prioRead(s)
  end
  return true, table.concat(out, ";")
end


function Civ6Ai_Orders.RunTest(sender, o, params)
  if o.K == Civ6Ai_Orders.K.TEST_MODE then
    local controller = Civ6Ai_Orders._Controller()
    if controller ~= nil and controller ~= sender then
      return false, "not_controller"
    end
    local on = num(params.V) == 1
    if on and num(Game:GetProperty("CIV6AI_MPTEST")) ~= 1 then
      Game:SetProperty("CIV6AI_MPTEST_START", Game.GetCurrentGameTurn())
    end
    if controller == nil then
      Game:SetProperty("CIV6AI_CONTROLLER", sender)
    end
    Game:SetProperty("CIV6AI_MPTEST", on and 1 or (num(params.V) == 2 and 2 or 0))
    return true, "test_mode=" .. tostring(num(params.V))
  end
  if num(Game:GetProperty("CIV6AI_MPTEST")) ~= 1 then
    return false, "test_mode_off"
  end
  local controller = Civ6Ai_Orders._Controller()
  if controller ~= nil and controller ~= sender then
    return false, "not_controller"
  end
  local fn = Civ6Ai_Orders.Tests[o.K]
  if fn == nil then
    return false, "unknown_test"
  end
  local okRun, ok, reason = pcall(fn, sender, o, params)
  if not okRun then
    return false, "test_error:" .. tostring(ok)
  end
  return ok == true, reason
end

function Civ6Ai_Orders.Init()
  GameEvents.Civ6AiOrder.Add(function(sender, params)
    local ok, err = pcall(Civ6Ai_Orders.OnOrder, sender, params)
    if not ok then
      log("handler_error|" .. tostring(err))
    end
  end)
  if GameEvents.OnGameTurnStarted ~= nil then
    GameEvents.OnGameTurnStarted.Add(Civ6Ai_Orders.OnGameTurnStarted)
  end
  GameEvents.PlayerTurnStartComplete.Add(function(owner)
    local ok, err = pcall(Civ6Ai_Orders.OnPlayerTurnStartComplete, owner)
    if not ok then
      log("turn_start_error|player=" .. tostring(owner) .. "|" .. tostring(err))
      Civ6Ai_Orders._NoteTurnStartError(owner, err)
    end
    Civ6Ai_Orders._PublishTurnStart(owner)
  end)
  Civ6Ai_Orders.RegisterForceStrategies()
  local nPrio = Civ6Ai_Orders.RegisterPriorityStrategies()
  Civ6Ai_Orders.RegisterEarlyStrategies()
  local shared = Civ6Ai_Orders._Shared()
  shared.OrdersVersion = Civ6Ai_Orders.VERSION
  shared.OrderChecksum = Civ6Ai_Orders.Checksum
  shared.PriorityLevels = Civ6Ai_Orders.PriorityLevels
  shared.Gov = Civ6Ai_Orders.Gov
  shared.RunHostFallbacks = Civ6Ai_Orders._RunHostFallbacks
  shared.WasHandled = Civ6Ai_Orders.WasHandled
  shared.MarkHandled = Civ6Ai_Orders.MarkHandled
  shared.CityStrikeAvailable = Civ6Ai_Orders.CityStrikeAvailable
  shared.CityStrikeCan = Civ6Ai_Orders._CityStrikeCan
  shared.ReadUnitGoal = Civ6Ai_Orders._ReadGoal
  if Game ~= nil and Game.SetProperty ~= nil then
    pcall(function()
      Game:SetProperty("CIV6AI_CITY_STRIKE", Civ6Ai_Orders.CityStrikeAvailable() and 1 or 0)
    end)
  end
  pcall(Civ6Ai_Orders.Gov.Probe)
  log("load|version=" .. Civ6Ai_Orders.VERSION .. "|prio_conditions=" .. tostring(nPrio) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
end

Civ6Ai_Orders.Init()


-- Below EARLY_CITY_LIMIT cities an AI seat runs the fixed EARLY_SET build
-- priorities (mirrors sidecar civ6_priorities.EARLY_SET). Gameplay context at
-- turn start, so every client sets the same synced properties; it does not
-- depend on the sidecar's hint packets reaching the fallback pass.
Civ6Ai_Orders.EARLY_CITY_LIMIT = 3
Civ6Ai_Orders.EARLY_SET = { peace = 1, expansion = 3, improvements = 1 }

function Civ6Ai_Orders.ApplyEarlyLock(owner)
  -- Every major, the host (human-flagged) seat included: the levels are the
  -- seat's saved production weights and the prompt's preset facts.
  local p = Players ~= nil and Players[owner] or nil
  if p == nil or call(p, "IsMajor") == false then
    return false
  end
  local open, why = Civ6Ai_Orders.EarlyOpen(owner)
  -- The snapshot (UI) reads this so the prompt's preset facts match the rule.
  Game:SetProperty("CIV6AI_EARLY_OPEN_" .. tostring(owner), open and 1 or 0)
  if not open then
    return false
  end
  -- The early set is only the starting default: once the seat has levels (this
  -- default or a preset it picked) its choice stands, so a seat can pick
  -- islands or coastal_expansion with 1-2 cities.
  if #Civ6Ai_Orders.PriorityLevels(owner) > 0 then
    return true
  end
  local n = #sortedMembers(call(p, "GetCities"))
  local changed = 0
  for _, cat in ipairs(Civ6Ai_Orders.PRIORITY_IDS) do
    local want = Civ6Ai_Orders.EARLY_SET[cat.key] or 0
    if Civ6Ai_Orders.PriorityLevel(owner, cat.id) ~= want then
      setPrio(owner, cat.id, want)
      changed = changed + 1
    end
  end
  if changed > 0 then
    log("early_lock|player=" .. tostring(owner) .. "|cities=" .. tostring(n) .. "|now=" .. prioText(owner))
  end
  return true
end
