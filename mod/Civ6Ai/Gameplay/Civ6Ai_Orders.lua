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
-- Unit orders arrive in batches (B = batch id, J = index, N = count). The batch
-- is applied when its last order arrives, with the same retry passes the
-- single-player apply uses (a move blocked by another of the seat's own units
-- is retried after the others moved).
--
-- Local-only bookkeeping (results for the host's apply log, checksums for the
-- sync reports) goes into ExposedMembers.Civ6Ai, which each PC keeps for itself
-- and never feeds back into game state.
Civ6Ai_Orders = Civ6Ai_Orders or {}
Civ6Ai_Orders.VERSION = 1
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
  RESOLVE = 8,
  PRIORITY = 9,
  GOVERNMENT = 10,
  POLICY = 11,
  PANTHEON = 12,
  RELIGION = 13,
  GP_RECRUIT = 14,
  GP_PATRONIZE = 15,
  GOVERNOR = 16,
  HOLD = 20,
  REPORT = 30,
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
}
Civ6Ai_Orders.UNIT_KINDS = {
  [1] = "move_unit", [4] = "found_city", [5] = "unit_skip", [6] = "unit_posture_fortify",
  [7] = "attack_target", [2] = "set_research_tech", [3] = "set_research_civic",
}
Civ6Ai_Orders.MAX_PASSES = 4
Civ6Ai_Orders._batches = Civ6Ai_Orders._batches or {}
Civ6Ai_Orders._ordered = Civ6Ai_Orders._ordered or {}

local function log(s)
  print(Civ6Ai_Orders.TAG .. s)
end

local function call(obj, name, ...)
  if obj == nil or obj[name] == nil then
    return nil
  end
  local ok, v = pcall(obj[name], obj, ...)
  if ok then
    return v
  end
  return nil
end

local function num(v)
  return tonumber(v)
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
-- ordered only by the controller, the human whose first HOLD order claimed
-- the AI seats (the host). The claim is a synced game property, so every PC
-- accepts and refuses the same orders.
function Civ6Ai_Orders._Controller()
  return num(Game:GetProperty("CIV6AI_CONTROLLER"))
end

function Civ6Ai_Orders._SenderProblem(sender, owner)
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
  if controller ~= nil and controller ~= sender then
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

function Civ6Ai_Orders._DoCommand(sender, o)
  local k = o.K
  local owner = o.P
  local why = Civ6Ai_Orders._SenderProblem(sender, owner)
  if why ~= nil then
    return false, why
  end
  if k == Civ6Ai_Orders.K.MOVE then
    local unit = Civ6Ai_Orders._Unit(owner, o.U)
    if unit ~= nil and Map.GetPlotDistance(unit:GetX(), unit:GetY(), o.X, o.Y) > 1 then
      return Civ6Ai_Orders._Route("MoveUnitAlongPathForPlayer", owner, o.U, o.X, o.Y)
    end
    return Civ6Ai_Orders._Route("MoveUnitForPlayer", owner, o.U, o.X, o.Y)
  elseif k == Civ6Ai_Orders.K.RESEARCH then
    return Civ6Ai_Orders._Route("SetResearchForPlayer", owner, o.I)
  elseif k == Civ6Ai_Orders.K.CIVIC then
    return Civ6Ai_Orders._Route("SetCivicForPlayer", owner, o.I)
  elseif k == Civ6Ai_Orders.K.FOUND then
    return Civ6Ai_Orders._Route("FoundCityForPlayer", owner, o.U)
  elseif k == Civ6Ai_Orders.K.SKIP or k == Civ6Ai_Orders.K.FORTIFY then
    return Civ6Ai_Orders._Route("FinishMovesForPlayer", owner, o.U)
  elseif k == Civ6Ai_Orders.K.ATTACK then
    return Civ6Ai_Orders._Attack(owner, o)
  end
  return false, "unknown_kind"
end

-- An AI seat's attack, melee or ranged. The gameplay script has no attack
-- operation (UnitManager.RequestOperation is UI-only, and MoveUnit into an
-- enemy does nothing: MP test T4 melee_no_effect), so the fight is resolved
-- here with the engine's own numbers: CombatManager.SimulateAttackVersus gives
-- the damage each side takes (the same forecast the combat preview shows),
-- which is applied to both units. The same code runs on every PC in the game,
-- so the outcome stays in sync.
function Civ6Ai_Orders._Attack(owner, o)
  local unit = Civ6Ai_Orders._Unit(owner, o.U)
  if unit == nil then
    return false, "unit_not_found"
  end
  local ready, why = Civ6Ai_Orders._Route("ReadyUnitForPlayer", owner, o.U)
  if not ready and why ~= "gamecore_unavailable:ReadyUnitForPlayer" then
    return false, why
  end
  return Civ6Ai_Orders._ResolveAttack(unit, o.X, o.Y)
end

function Civ6Ai_Orders._IsRanged(unit)
  local row = GameInfo.Units[unit:GetType()]
  return row ~= nil and (num(row.RangedCombat) or 0) > 0 and (num(row.Range) or 0) > 0
end

function Civ6Ai_Orders._CombatType(unit)
  if CombatTypes == nil then
    return nil
  end
  if not Civ6Ai_Orders._IsRanged(unit) then
    return CombatTypes.MELEE
  end
  if (call(unit, "GetBombardCombat") or 0) > (call(unit, "GetRangedCombat") or 0) then
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
    if other:GetOwner() ~= owner then
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
    if other:GetOwner() ~= owner then
      total = total + (call(other, "GetDamage") or 0)
      count = count + 1
    end
  end
  return total, count
end

function Civ6Ai_Orders._AtWar(owner, other)
  local them = Players[other]
  if them ~= nil and them.IsBarbarian ~= nil and them:IsBarbarian() then
    return true
  end
  local diplo = call(Players[owner], "GetDiplomacy")
  local atWar = call(diplo, "IsAtWarWith", other)
  return atWar == true
end

-- Damage each side takes, from the engine's forecast. Returns
-- attackerDamage, defenderDamage, or nil, reason.
function Civ6Ai_Orders._Forecast(unit, defender, combatType)
  if CombatManager == nil or CombatManager.SimulateAttackVersus == nil or CombatResultParameters == nil then
    return nil, "no_combat_forecast"
  end
  local ok, res = pcall(CombatManager.SimulateAttackVersus, unit:GetComponentID(), defender:GetComponentID(), combatType)
  if not ok or type(res) ~= "table" then
    return nil, "forecast_failed"
  end
  local a = res[CombatResultParameters.ATTACKER]
  local d = res[CombatResultParameters.DEFENDER]
  if type(a) ~= "table" or type(d) ~= "table" then
    return nil, "forecast_empty"
  end
  return num(a[CombatResultParameters.DAMAGE_TO]) or 0, num(d[CombatResultParameters.DAMAGE_TO]) or 0
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

Civ6Ai_Orders.ATTACK_XP = { melee = 3, ranged = 2, kill_bonus = 2 }

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
  local defender = Civ6Ai_Orders._Defender(x, y, owner)
  if defender == nil then
    return false, "no_enemy_on_plot"
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
  local defBefore = call(defender, "GetDamage") or 0
  local attBefore = call(unit, "GetDamage") or 0
  Civ6Ai_Orders._ChangeDamage(defender, toDefender)
  Civ6Ai_Orders._ChangeDamage(unit, toAttacker)
  local killed = Civ6Ai_Orders._IsDead(defender)
  local lost = Civ6Ai_Orders._IsDead(unit)
  local defAfter = call(defender, "GetDamage") or 0
  if killed and call(defender, "IsDead") ~= true then
    pcall(UnitManager.Kill, defender)
  end
  if lost then
    pcall(UnitManager.Kill, unit)
  else
    local exp = call(unit, "GetExperience")
    local xp = (ranged and Civ6Ai_Orders.ATTACK_XP.ranged or Civ6Ai_Orders.ATTACK_XP.melee)
      + (killed and Civ6Ai_Orders.ATTACK_XP.kill_bonus or 0)
    if exp ~= nil and exp.ChangeExperience ~= nil then
      pcall(exp.ChangeExperience, exp, xp)
    end
    -- A melee winner moves into the emptied plot, as in a normal attack.
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

-- Apply a complete batch with retry passes; record each result.
function Civ6Ai_Orders._ApplyBatch(sender, batch)
  local pending = {}
  for j = 1, batch.n do
    if batch.orders[j] ~= nil then
      pending[#pending + 1] = batch.orders[j]
    else
      Civ6Ai_Orders._Record(sender, { S = -1, K = 0, P = batch.p }, false, "batch_order_missing:" .. j)
    end
  end
  for pass = 1, Civ6Ai_Orders.MAX_PASSES do
    if #pending == 0 then
      break
    end
    local nextPending, progress = {}, false
    for _, o in ipairs(pending) do
      local ok, reason = Civ6Ai_Orders._DoCommand(sender, o)
      if ok then
        progress = true
        if o.U ~= nil then
          Civ6Ai_Orders._MarkOrdered(o.P, o.U)
        end
        Civ6Ai_Orders._Record(sender, o, true, reason)
      elseif retryable(o.K, reason) and pass < Civ6Ai_Orders.MAX_PASSES then
        nextPending[#nextPending + 1] = o
      else
        Civ6Ai_Orders._Record(sender, o, false, reason)
      end
    end
    if not progress then
      for _, o in ipairs(nextPending) do
        Civ6Ai_Orders._Record(sender, o, false, "plot_occupied_exhausted")
      end
      break
    end
    pending = nextPending
  end
end

function Civ6Ai_Orders._MarkOrdered(owner, unitId)
  local turn = Game.GetCurrentGameTurn()
  local rec = Civ6Ai_Orders._ordered[owner]
  if rec == nil or rec.turn ~= turn then
    rec = { turn = turn, units = {} }
    Civ6Ai_Orders._ordered[owner] = rec
  end
  rec.units[unitId] = true
end

-- End the turn for an AI seat's units the model did not order (the model's
-- "resolve" at the end of its orders). Held units already have no moves.
function Civ6Ai_Orders._Resolve(sender, owner)
  local why = Civ6Ai_Orders._SenderProblem(sender, owner)
  if why ~= nil then
    return false, why
  end
  local rec = Civ6Ai_Orders._ordered[owner]
  local turn = Game.GetCurrentGameTurn()
  local ordered = (rec ~= nil and rec.turn == turn) and rec.units or {}
  local count = 0
  local p = Players[owner]
  local list = {}
  for _, u in (call(p, "GetUnits") or { Members = function() return function() return nil end end }):Members() do
    list[#list + 1] = u
  end
  table.sort(list, function(a, b) return a:GetID() < b:GetID() end)
  for _, u in ipairs(list) do
    if not ordered[u:GetID()] and (call(u, "GetMovesRemaining") or 0) > 0 then
      if pcall(UnitManager.FinishMoves, u) then
        count = count + 1
      end
    end
  end
  return true, "resolved=" .. count
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

function Civ6Ai_Orders._Record(sender, o, ok, reason)
  local shared = Civ6Ai_Orders._Shared()
  local turn = Game.GetCurrentGameTurn()
  shared.OrderHash = mixString(shared.OrderHash or 7, table.concat({
    tostring(turn), tostring(sender), tostring(o.S), tostring(o.K), tostring(ok), tostring(reason or "") }, "|"))
  shared.OrderCount = (shared.OrderCount or 0) + 1
  shared.OrderResults = shared.OrderResults or {}
  table.insert(shared.OrderResults, {
    sender = sender, seq = o.S, kind = o.K, player = o.P, turn = turn, ok = ok, reason = tostring(reason or ""),
  })
  while #shared.OrderResults > 512 do
    table.remove(shared.OrderResults, 1)
  end
  log("result|turn=" .. turn .. "|from=" .. tostring(sender) .. "|seq=" .. tostring(o.S) .. "|kind=" .. tostring(o.K)
    .. "|player=" .. tostring(o.P) .. "|unit=" .. tostring(o.U) .. "|ok=" .. tostring(ok)
    .. "|reason=" .. tostring(reason or "") .. "|hash=" .. tostring(shared.OrderHash))
end

-- ---------------------------------------------------------------------------
-- Checksum of synced state
-- ---------------------------------------------------------------------------
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

function Civ6Ai_Orders.OnGameTurnStarted(turn)
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
    I = num(params.I), S = num(params.S) or -1,
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
  if num(params.T) ~= turn then
    Civ6Ai_Orders._Record(sender, o, false, "stale_turn:" .. tostring(params.T))
    return
  end
  if k == Civ6Ai_Orders.K.HOLD then
    Civ6Ai_Orders._Hold(sender, o, num(params.V) == 1)
  elseif k == Civ6Ai_Orders.K.PRIORITY then
    local ok, reason = Civ6Ai_Orders._SetPriority(sender, o)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  elseif k ~= nil and k >= Civ6Ai_Orders.K.GOVERNMENT and k <= Civ6Ai_Orders.K.GOVERNOR then
    local ok, reason = Civ6Ai_Orders._DoGovernance(sender, o)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  elseif k == Civ6Ai_Orders.K.RESOLVE then
    local ok, reason = Civ6Ai_Orders._Resolve(sender, o.P)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  elseif k == Civ6Ai_Orders.K.PING then
    local n = (num(Game:GetProperty("CIV6AI_PINGS")) or 0) + 1
    Game:SetProperty("CIV6AI_PINGS", n)
    Civ6Ai_Orders._Record(sender, o, true, "pings=" .. n)
  elseif k ~= nil and k >= Civ6Ai_Orders.K.TEST_MODE then
    local ok, reason = Civ6Ai_Orders.RunTest(sender, o, params)
    Civ6Ai_Orders._Record(sender, o, ok, reason)
  elseif Civ6Ai_Orders.UNIT_KINDS[k] ~= nil then
    Civ6Ai_Orders._Batch(sender, o, params)
  else
    Civ6Ai_Orders._Record(sender, o, false, "unknown_kind")
  end
  Game:SetProperty("CIV6AI_LAST_SEQ_" .. tostring(sender), o.S)
end

function Civ6Ai_Orders._Batch(sender, o, params)
  local b, j, n = num(params.B), num(params.J), num(params.N)
  if b == nil or j == nil or n == nil or n < 1 or j < 1 or j > n then
    Civ6Ai_Orders._ApplyBatch(sender, { n = 1, p = o.P, orders = { o } })
    return
  end
  local cur = Civ6Ai_Orders._batches[sender]
  if cur ~= nil and cur.id ~= b then
    log("batch_abandoned|from=" .. tostring(sender) .. "|batch=" .. tostring(cur.id))
    Civ6Ai_Orders._ApplyBatch(sender, cur)
    cur = nil
  end
  if cur == nil then
    cur = { id = b, n = n, p = o.P, orders = {} }
    Civ6Ai_Orders._batches[sender] = cur
  end
  cur.orders[j] = o
  if j == n then
    Civ6Ai_Orders._batches[sender] = nil
    Civ6Ai_Orders._ApplyBatch(sender, cur)
  end
end

-- HOLD: turn the turn-start freeze on or off for one AI seat. The first HOLD
-- claims the controller role for its sender.
function Civ6Ai_Orders._Hold(sender, o, on)
  local p = Players[o.P]
  if p == nil or call(p, "IsHuman") then
    Civ6Ai_Orders._Record(sender, o, false, "hold_needs_ai_seat")
    return
  end
  local s = Players[sender]
  if s == nil or not call(s, "IsHuman") then
    Civ6Ai_Orders._Record(sender, o, false, "sender_not_human")
    return
  end
  local controller = Civ6Ai_Orders._Controller()
  if controller == nil then
    Game:SetProperty("CIV6AI_CONTROLLER", sender)
  elseif controller ~= sender then
    Civ6Ai_Orders._Record(sender, o, false, "not_controller")
    return
  end
  Game:SetProperty("CIV6AI_HOLD_" .. tostring(o.P), on and 1 or 0)
  Civ6Ai_Orders._Record(sender, o, true, on and "hold_on" or "hold_off")
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
  if current ~= nil and current == row.Index then
    return false, "you already have " .. name
  end
  local turn = Game.GetCurrentGameTurn()
  if num(Game:GetProperty(govProp(owner, "CHANGED"))) == turn then
    return false, "government was already changed this turn"
  end
  -- Gameplay scripts have no GetCurrentGovernment, so "no government yet" only
  -- counts when it can be read; otherwise a civic must have completed.
  local fresh = (current ~= nil and current < 0) or call(culture, "CivicCompletedThisTurn") == true
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
-- is used up), plus up to two beliefs (one Founder, one Follower).
function Gov.FoundReligion(owner, religionIndex, unitId, beliefA, beliefB)
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
  for _, b in ipairs({ beliefA, beliefB }) do
    if b ~= nil and b >= 0 then
      local row = GameInfo.Beliefs[b]
      if row == nil or row.BeliefClassType == "BELIEF_CLASS_PANTHEON" then
        return false, "belief " .. tostring(b) .. " is not a religion belief"
      end
      if seenClass[row.BeliefClassType] then
        return false, "pick beliefs of different kinds (one Founder, one Follower)"
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

-- Synced channel dispatch for the governance kinds.
function Civ6Ai_Orders._DoGovernance(sender, o)
  local why = Civ6Ai_Orders._SenderProblem(sender, o.P)
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
    return Gov.FoundReligion(o.P, o.I, o.U, o.X, o.Y)
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
  local problem = Civ6Ai_Orders._SenderProblem(sender, owner)
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
  Civ6Ai_Orders.RegisterForceStrategies()
  local nPrio = Civ6Ai_Orders.RegisterPriorityStrategies()
  local shared = Civ6Ai_Orders._Shared()
  shared.OrdersVersion = Civ6Ai_Orders.VERSION
  shared.OrderChecksum = Civ6Ai_Orders.Checksum
  shared.PriorityLevels = Civ6Ai_Orders.PriorityLevels
  shared.Gov = Civ6Ai_Orders.Gov
  pcall(Civ6Ai_Orders.Gov.Probe)
  log("load|version=" .. Civ6Ai_Orders.VERSION .. "|prio_conditions=" .. tostring(nPrio) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
end

Civ6Ai_Orders.Init()
