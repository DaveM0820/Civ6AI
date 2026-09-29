-- Civ6Ai multiplayer test mode. For game day with a second PC: the host PC
-- (Civ6Ai_Paths.MpTest = 1) runs a short scripted sequence over about ten
-- turns on top of the normal model loop, every PC ends its turns by itself,
-- and every check's result lands in both PCs' Lua.log (CIV6AI|orders|...).
-- scripts/mp_test_report.py reads the host log and says what worked.
--
-- Nothing here changes game state directly: every check is an order sent
-- through Civ6Ai_OrderChannel and run by Gameplay/Civ6Ai_Orders.lua on every PC.
Civ6Ai_MpTest = Civ6Ai_MpTest or {}
Civ6Ai_MpTest.LAST_STEP = 24
Civ6Ai_MpTest.STEP_DELAY_SECONDS = 8
Civ6Ai_MpTest.END_TURN_DELAY_SECONDS = 25
Civ6Ai_MpTest.LATE_TURN_HOLD_SECONDS = 40
Civ6Ai_MpTest._done = Civ6Ai_MpTest._done or {}
Civ6Ai_MpTest._state = Civ6Ai_MpTest._state or {}

local K = function() return Civ6Ai_OrderChannel.K end

local function log(s)
  Civ6Ai_Util.Log("mp_test|" .. s)
end

-- Game:GetProperty returns no value at all (not nil) for an unset key in the
-- UI context, and tonumber() with no argument throws, so read it into a local first.
local function prop(name)
  local ok, v = pcall(function() return Game:GetProperty(name) end)
  if not ok or v == nil then
    return nil
  end
  return tonumber(v)
end

function Civ6Ai_MpTest.IsHostRunner()
  return Civ6Ai_OrderChannel ~= nil and Civ6Ai_OrderChannel.IsActive() and Civ6Ai_Config.IsMpTest()
    and Civ6Ai_Config.IsHostPc()
end

-- Test mode on in this game (synced), seen by every PC.
function Civ6Ai_MpTest.IsOn()
  return Civ6Ai_OrderChannel ~= nil and Civ6Ai_OrderChannel.IsActive() and prop("CIV6AI_MPTEST") == 1
end

function Civ6Ai_MpTest.Step()
  local start = prop("CIV6AI_MPTEST_START")
  if start == nil then
    return 0
  end
  return Game.GetCurrentGameTurn() - start
end

function Civ6Ai_MpTest.Say(text)
  log("say|" .. text)
  if Civ6Ai_Chat ~= nil and Civ6Ai_Chat._SendNetworkChat ~= nil then
    pcall(Civ6Ai_Chat._SendNetworkChat, "[Civ6Ai test] " .. text)
  end
end

-- ---------------------------------------------------------------------------
-- Picking test subjects (read only)
-- ---------------------------------------------------------------------------
local function members(coll)
  local out = {}
  if coll ~= nil and coll.Members ~= nil then
    for _, v in coll:Members() do
      out[#out + 1] = v
    end
  end
  table.sort(out, function(a, b) return a:GetID() < b:GetID() end)
  return out
end

local function isMelee(unit)
  local row = GameInfo.Units[unit:GetType()]
  return row ~= nil and (tonumber(row.Combat) or 0) > 0 and (tonumber(row.RangedCombat) or 0) == 0
    and row.Domain == "DOMAIN_LAND"
end

local function plotFree(plot)
  if plot == nil or plot:IsWater() or plot:IsImpassable() or plot:IsCity() then
    return false
  end
  if plot.IsMountain ~= nil and plot:IsMountain() then
    return false
  end
  local units = Units.GetUnitsInPlot(plot)
  return units == nil or #units == 0
end

-- The AI seat and its melee unit the scripted checks use.
function Civ6Ai_MpTest.PickSubject()
  for _, seat in ipairs(Civ6Ai_InGame._mpHoldSeats or {}) do
    local p = Players[seat]
    if p ~= nil and p:IsAlive() then
      for _, u in ipairs(members(p:GetUnits())) do
        if u:GetX() >= 0 and isMelee(u) then
          return seat, u
        end
      end
    end
  end
  return nil, nil
end

function Civ6Ai_MpTest._FarTarget(unit)
  for radius = 3, 2, -1 do
    for dx = -radius, radius do
      for dy = -radius, radius do
        local x, y = unit:GetX() + dx, unit:GetY() + dy
        local plot = Map.GetPlot(x, y)
        if plot ~= nil and Map.GetPlotDistance(unit:GetX(), unit:GetY(), x, y) == radius and plotFree(plot) then
          return x, y
        end
      end
    end
  end
  return nil, nil
end

function Civ6Ai_MpTest._FarmPlot(seat)
  local city = members(Players[seat]:GetCities())[1]
  if city == nil then
    return nil, nil
  end
  for dir = 0, 5 do
    local plot = Map.GetAdjacentPlot(city:GetX(), city:GetY(), dir)
    if plot ~= nil and not plot:IsWater() and not plot:IsCity() and plot:GetImprovementType() < 0
        and plot:GetOwner() == seat and not plot:IsImpassable() then
      return plot:GetX(), plot:GetY()
    end
  end
  return nil, nil
end

-- The barbarian our step-2 spawn put next to the subject (read from results).
function Civ6Ai_MpTest._EnemyNear(unit)
  for dir = 0, 5 do
    local plot = Map.GetAdjacentPlot(unit:GetX(), unit:GetY(), dir)
    for _, other in ipairs(plot ~= nil and (Units.GetUnitsInPlot(plot) or {}) or {}) do
      local owner = Players[other:GetOwner()]
      if owner ~= nil and owner:IsBarbarian() then
        return plot:GetX(), plot:GetY()
      end
    end
  end
  return nil, nil
end

-- ---------------------------------------------------------------------------
-- The schedule (host)
-- ---------------------------------------------------------------------------
Civ6Ai_MpTest.Steps = {}

Civ6Ai_MpTest.Steps[0] = function(seat, unit)
  local send = Civ6Ai_OrderChannel.Send
  send(K().TEST_MODE, { V = 1 })
  Civ6Ai_OrderChannel.EnsureHolds(Civ6Ai_InGame._mpHoldSeats or {})
  send(K().TEST_INTROSPECT, { P = seat or 0, Note = "civ6ai-note" })
  send(K().PING, {})
  Civ6Ai_MpTest.Say("Multiplayer test started. Turns end by themselves; it takes about 25 turns. Please don't quit yet.")
end

Civ6Ai_MpTest.Steps[1] = function(seat, unit)
  if unit == nil then
    return log("step1|no_subject")
  end
  local x, y = Civ6Ai_MpTest._FarTarget(unit)
  if x ~= nil then
    Civ6Ai_OrderChannel.Send(K().TEST_FAR_MOVE, { P = seat, U = unit:GetID(), X = x, Y = y })
  end
  Civ6Ai_OrderChannel.Send(K().TEST_EXPERIENCE, { P = seat, U = unit:GetID() })
  local fx, fy = Civ6Ai_MpTest._FarmPlot(seat)
  if fx ~= nil then
    Civ6Ai_OrderChannel.Send(K().TEST_IMPROVEMENT, { P = seat, X = fx, Y = fy })
  else
    log("step1|no_farm_plot")
  end
end

Civ6Ai_MpTest.Steps[2] = function(seat, unit)
  if unit == nil then
    return log("step2|no_subject")
  end
  local send = Civ6Ai_OrderChannel.Send
  send(K().TEST_SPAWN_ENEMY, { P = seat, U = unit:GetID(), I = 1 })
  -- Native combat routes on fresh pairs: melee step, ranged forecast, and
  -- CombatManager.GenerateCombatResults. Step 3 checks them again a turn later.
  for mode = 0, 2 do
    send(K().TEST_COMBAT_PROBE, { P = seat, U = unit:GetID(), I = mode })
  end
end

-- Seat P's slinger that can shoot X,Y (the one step 2 spawned), or nil.
function Civ6Ai_MpTest._SlingerFor(seat, x, y)
  for _, u in ipairs(members(Players[seat]:GetUnits())) do
    local row = GameInfo.Units[u:GetType()]
    if row ~= nil and row.UnitType == "UNIT_SLINGER" and Map.GetPlotDistance(u:GetX(), u:GetY(), x, y) == 1 then
      return u
    end
  end
  return nil
end

Civ6Ai_MpTest.Steps[3] = function(seat, unit)
  local send = Civ6Ai_OrderChannel.Send
  send(K().TEST_DAMAGE_CHECK, { P = seat or 0 })
  if unit == nil then
    return log("step3|no_subject")
  end
  -- The real attack route on fresh pairs.
  send(K().TEST_RESOLVED_ATTACK, { P = seat, U = unit:GetID(), I = 1 })
  send(K().TEST_RESOLVED_ATTACK, { P = seat, U = unit:GetID(), I = 0 })
  local ex, ey = Civ6Ai_MpTest._EnemyNear(unit)
  if ex == nil then
    log("step3|no_enemy_next_to_subject")
  else
    -- The model's own attack command, as a live game would send it: the
    -- slinger shoots first, then the subject attacks in melee.
    local commands = {}
    local slinger = Civ6Ai_MpTest._SlingerFor(seat, ex, ey)
    if slinger ~= nil then
      commands[#commands + 1] = { kind = "attack_target", arguments = { unit_id = "UNIT_" .. slinger:GetID(), target_x = ex, target_y = ey } }
    end
    commands[#commands + 1] = { kind = "attack_target", arguments = { unit_id = "UNIT_" .. unit:GetID(), target_x = ex, target_y = ey } }
    Civ6Ai_OrderChannel.SendDecision(seat, { commands = commands })
  end
  send(K().TEST_SCRIPTED_PRODUCTION, { P = seat })
end

Civ6Ai_MpTest.Steps[4] = function()
  for _ = 1, 25 do
    Civ6Ai_OrderChannel.Send(K().PING, {})
  end
  Civ6Ai_OrderChannel.Send(K().PING, {}, Game.GetCurrentGameTurn() - 1)
end

-- Step 5 sends its orders after the host ends its turn (see _OnLocalTurnEnd).
Civ6Ai_MpTest.Steps[5] = function()
  Civ6Ai_MpTest._lateTurn = Game.GetCurrentGameTurn()
end

Civ6Ai_MpTest.Steps[6] = function(seat)
  Civ6Ai_OrderChannel.Send(K().PING, {})
  Civ6Ai_OrderChannel.Send(K().TEST_API_SURVEY, { P = seat or 0 })
end

-- Can the normal interface requests act for an AI seat? The single-player
-- route switches the local player to the AI seat first; step 7 logs whether
-- that switch exists here, then sends the plain requests (no switch) for the
-- AI seat's city production, a unit move and research, and reads back after a
-- few seconds whether each one took effect. The per-turn checksum shows
-- whether the game stayed in sync afterwards.
function Civ6Ai_MpTest._PickResearch(player)
  local techs = player:GetTechs()
  local current = techs:GetResearchingTech()
  for row in GameInfo.Technologies() do
    if row.Index ~= current and techs:CanResearch(row.Index) and not techs:HasTech(row.Index) then
      return row, current
    end
  end
  return nil, current
end

function Civ6Ai_MpTest._PickBuild(city)
  local current = Civ6Ai_Production._GetCityProduction(city)
  for _, id in ipairs({ "UNIT_SCOUT", "UNIT_WARRIOR", "UNIT_SLINGER", "BUILDING_MONUMENT", "UNIT_BUILDER", "UNIT_SETTLER" }) do
    local item = Civ6Ai_Production._ResolveBuildItem(id)
    local bq = city:GetBuildQueue()
    if id ~= current and item ~= nil and bq ~= nil and bq:CanProduce(item.Hash, true) then
      return id, current
    end
  end
  return nil, current
end

function Civ6Ai_MpTest._UiProbe(seat, unit)
  local player = Players[seat]
  local r = { seat = seat }
  local function try(label, fn)
    local ok, a, b = pcall(fn)
    log("ui_probe|" .. label .. "|pcall=" .. tostring(ok) .. "|" .. tostring(a) .. "|" .. tostring(b))
  end
  -- City production.
  local city = members(player:GetCities())[1]
  if city ~= nil then
    local buildId, before = Civ6Ai_MpTest._PickBuild(city)
    r.city, r.build, r.buildBefore = city, buildId, before
    if buildId ~= nil then
      local item, paramKey = Civ6Ai_Production._ResolveBuildItem(buildId)
      local p = {}
      p[paramKey] = item.Hash
      try("city_can_start", function() return CityManager.CanStartOperation(city, CityOperationTypes.BUILD, p, true) end)
      p[CityOperationTypes.PARAM_INSERT_MODE] = CityOperationTypes.VALUE_EXCLUSIVE
      try("city_request|want=" .. buildId .. "|before=" .. tostring(before),
        function() return CityManager.RequestOperation(city, CityOperationTypes.BUILD, p) end)
    else
      log("ui_probe|city|no_build_choice|before=" .. tostring(before))
    end
  else
    log("ui_probe|city|no_city")
  end
  -- Unit move.
  if unit ~= nil then
    local x, y = Civ6Ai_MpTest._FarTarget(unit)
    r.unit, r.ux, r.uy, r.tx, r.ty = unit, unit:GetX(), unit:GetY(), x, y
    if x ~= nil then
      local p = {}
      p[UnitOperationTypes.PARAM_X] = x
      p[UnitOperationTypes.PARAM_Y] = y
      try("unit_can_start|moves=" .. tostring(unit:GetMovesRemaining()),
        function() return UnitManager.CanStartOperation(unit, UnitOperationTypes.MOVE_TO, nil, p) end)
      try("unit_request|from=" .. r.ux .. "," .. r.uy .. "|to=" .. x .. "," .. y,
        function() return UnitManager.RequestOperation(unit, UnitOperationTypes.MOVE_TO, p) end)
    end
  end
  -- Research.
  local tech, before = Civ6Ai_MpTest._PickResearch(player)
  r.tech, r.techBefore = tech, before
  if tech ~= nil then
    local ops = PlayerOperations or PlayerOperationTypes
    log("ui_probe|research_ops|PlayerOperations=" .. tostring(PlayerOperations ~= nil)
      .. "|PlayerOperationTypes=" .. tostring(PlayerOperationTypes ~= nil))
    if ops ~= nil then
      local p = {}
      p[ops.PARAM_TECH_TYPE] = tech.Hash
      p[ops.PARAM_INSERT_MODE] = ops.VALUE_EXCLUSIVE
      try("research_request|want=" .. tech.TechnologyType .. "|before=" .. tostring(before),
        function() return UI.RequestPlayerOperation(seat, ops.RESEARCH, p) end)
    end
  end
  return r
end

function Civ6Ai_MpTest._UiProbeReadBack(r)
  local player = Players[r.seat]
  if r.city ~= nil and r.build ~= nil then
    local city = CityManager.GetCity(r.seat, r.city:GetID())
    local now = city and Civ6Ai_Production._GetCityProduction(city)
    log("ui_probe_result|city|want=" .. r.build .. "|before=" .. tostring(r.buildBefore) .. "|now=" .. tostring(now)
      .. "|took_effect=" .. tostring(now == r.build))
  end
  if r.unit ~= nil and r.tx ~= nil then
    local u = player:GetUnits():FindID(r.unit:GetID())
    local x, y = u and u:GetX(), u and u:GetY()
    log("ui_probe_result|unit|from=" .. r.ux .. "," .. r.uy .. "|to=" .. r.tx .. "," .. r.ty
      .. "|now=" .. tostring(x) .. "," .. tostring(y) .. "|took_effect=" .. tostring(x ~= r.ux or y ~= r.uy))
  end
  if r.tech ~= nil then
    local now = player:GetTechs():GetResearchingTech()
    log("ui_probe_result|research|want=" .. r.tech.Index .. "|before=" .. tostring(r.techBefore) .. "|now=" .. tostring(now)
      .. "|took_effect=" .. tostring(now == r.tech.Index))
  end
end

-- The old step 7 (plain interface requests for an AI seat) showed on
-- 2026-09-26 that they have no effect in multiplayer; _UiProbe stays for reference.
--
-- Production steering (steps 2-9): can the engine AI's production be steered
-- with real engine levers? Step 2 gives the district seat Writing (test setup
-- only), step 3 applies the levers (first AI seat: unit construction off and
-- production focus; second AI seat: a placed Campus), steps 4-9 read back what
-- every AI city is building, with a third AI seat as an untouched control, and
-- step 9 turns unit construction on again.
function Civ6Ai_MpTest._SteerSeats()
  local seats = {}
  for _, seat in ipairs(Civ6Ai_InGame._mpHoldSeats or {}) do
    local p = Players[seat]
    if p ~= nil and p:IsAlive() and p:GetCities() ~= nil and p:GetCities():GetCount() > 0 then
      seats[#seats + 1] = seat
    end
  end
  return seats[1], seats[2], seats[3]
end

function Civ6Ai_MpTest._Steer(mode)
  local st = Civ6Ai_MpTest._state.steer
  if st == nil then
    local p, q, r = Civ6Ai_MpTest._SteerSeats()
    if p == nil then
      return log("steer|no_ai_seat_with_city")
    end
    st = { p = p, q = q, r = r }
    Civ6Ai_MpTest._state.steer = st
    log("steer|seats|p=" .. p .. "|q=" .. tostring(q) .. "|control=" .. tostring(r))
  end
  Civ6Ai_OrderChannel.Send(K().TEST_PRODUCTION_STEER, { P = st.p, U = st.q, X = st.r, I = mode })
end

-- Steering orders sent at each step (mode 3 setup, 0 apply, 1 read, 2 undo).
-- Rounds 2-3 (2026-09-27) settled those levers; kept for reference, not sent.
Civ6Ai_MpTest.STEER_BY_STEP = {}

-- Forced-build strategies (Data/Civ6Ai_Strategies.sql): four AI seats, the
-- first three each switched into one single-item strategy (Archer, Granary,
-- Campus) and the fourth left as a control. Step 2 gives every seat the
-- unlocking techs and switches the strategies on, steps 3-13 read back what
-- each seat has and is building, step 13 switches them off.
function Civ6Ai_MpTest._ForceSeats()
  local seats = {}
  for _, seat in ipairs(Civ6Ai_InGame._mpHoldSeats or {}) do
    local p = Players[seat]
    if p ~= nil and p:IsAlive() and p:GetCities() ~= nil and p:GetCities():GetCount() > 0 then
      seats[#seats + 1] = seat
    end
  end
  return seats
end

function Civ6Ai_MpTest._Force(mode)
  local st = Civ6Ai_MpTest._state.force
  if st == nil then
    local seats = Civ6Ai_MpTest._ForceSeats()
    if #seats == 0 then
      return log("force|no_ai_seat_with_city")
    end
    st = { p = seats[1], u = seats[2], x = seats[3], y = seats[4] }
    Civ6Ai_MpTest._state.force = st
    log("force|seats|archer=" .. tostring(st.p) .. "|granary=" .. tostring(st.u) .. "|campus=" .. tostring(st.x)
      .. "|control=" .. tostring(st.y))
  end
  Civ6Ai_OrderChannel.Send(K().TEST_FORCE_BUILD, { P = st.p, U = st.u, X = st.x, Y = st.y, I = mode })
end

-- Round of 2026-09-27 settled that; kept for reference, not sent.
Civ6Ai_MpTest.FORCE_BY_STEP = {}

-- Build priorities (Data/Civ6Ai_Priorities.sql) through the real PRIORITY
-- order the model will use. Every AI major with a city plays freely (holds
-- released so settlers and builders act normally); the first three get
-- priorities and the fourth is the control:
--   A: total_war all-in (after war light, to check one posture replaces another)
--   B: science_victory all-in + growth strong + gold light (stacking), then a
--      fourth focus that must be refused
--   C: naval_total_war all-in
-- Step 1 gives every seat the same techs and reads a baseline, step 2 sets the
-- priorities, steps 3-21 read back, step 22 clears them.
Civ6Ai_MpTest.PRIO_PLAN = {
  { { 2, 1 }, { 3, 3 } },
  { { 8, 3 }, { 17, 2 }, { 14, 1 }, { 15, 1 } },
  { { 5, 3 } },
}
Civ6Ai_MpTest.PRIO_SET_STEP = 2
Civ6Ai_MpTest.PRIO_CLEAR_STEP = 22

function Civ6Ai_MpTest._PrioSeats()
  local st = Civ6Ai_MpTest._state.prio
  if st ~= nil then
    return st
  end
  local seats = {}
  for i = 0, 63 do
    local p = Players[i]
    if p ~= nil and p:IsAlive() and p:IsMajor() and not p:IsHuman() and p:GetCities() ~= nil
        and p:GetCities():GetCount() > 0 then
      seats[#seats + 1] = i
    end
  end
  st = { seats = seats }
  Civ6Ai_MpTest._state.prio = st
  log("prio|seats|total_war=" .. tostring(seats[1]) .. "|stacked=" .. tostring(seats[2]) .. "|naval=" .. tostring(seats[3])
    .. "|control=" .. tostring(seats[4]) .. "|count=" .. #seats)
  return st
end

function Civ6Ai_MpTest._PrioRead(mode)
  local s = Civ6Ai_MpTest._PrioSeats().seats
  if #s == 0 then
    return log("prio|no_ai_seat_with_city")
  end
  Civ6Ai_OrderChannel.Send(K().TEST_PRIORITY, { P = s[1], U = s[2] or -1, X = s[3] or -1, Y = s[4] or -1, I = mode })
end

function Civ6Ai_MpTest._PrioStep(step)
  if step == 1 then
    Civ6Ai_MpTest._holdsReleased = true
    for _, seat in ipairs(Civ6Ai_InGame._mpHoldSeats or {}) do
      Civ6Ai_OrderChannel.Send(K().HOLD, { P = seat, V = 0 })
    end
    return Civ6Ai_MpTest._PrioRead(3)
  end
  local s = Civ6Ai_MpTest._PrioSeats().seats
  if step == Civ6Ai_MpTest.PRIO_SET_STEP then
    for i, orders in ipairs(Civ6Ai_MpTest.PRIO_PLAN) do
      if s[i] ~= nil then
        for _, pair in ipairs(orders) do
          Civ6Ai_OrderChannel.Send(K().PRIORITY, { P = s[i], I = pair[1], X = pair[2] })
        end
      end
    end
  elseif step == Civ6Ai_MpTest.PRIO_CLEAR_STEP then
    for i = 1, #Civ6Ai_MpTest.PRIO_PLAN do
      if s[i] ~= nil then
        Civ6Ai_OrderChannel.Send(K().PRIORITY, { P = s[i], I = 0, X = 0 })
      end
    end
  end
  if step >= 2 and step <= Civ6Ai_MpTest.PRIO_CLEAR_STEP + 1 then
    Civ6Ai_MpTest._PrioRead(1)
  end
end

-- The unit and combat checks of steps 1-6 are settled; this round runs only
-- the priority test so nothing spawns next to the seats being compared.
for step = 1, Civ6Ai_MpTest.LAST_STEP - 1 do
  Civ6Ai_MpTest.Steps[step] = function()
    Civ6Ai_MpTest._PrioStep(step)
  end
end

Civ6Ai_MpTest.Steps[Civ6Ai_MpTest.LAST_STEP] = function()
  Civ6Ai_MpTest._holdsReleased = nil
  for _, seat in ipairs(Civ6Ai_InGame._mpHoldSeats or {}) do
    Civ6Ai_OrderChannel.Send(K().HOLD, { P = seat, V = 0 })
  end
  Civ6Ai_OrderChannel.Send(K().TEST_MODE, { V = 2 })
  Civ6Ai_MpTest.Say("Multiplayer test finished. Thanks! You can quit the game now.")
end

function Civ6Ai_MpTest._RunHostStep()
  local step = Civ6Ai_MpTest.IsOn() and Civ6Ai_MpTest.Step() or 0
  if prop("CIV6AI_MPTEST") == 2 or step > Civ6Ai_MpTest.LAST_STEP then
    return
  end
  local key = tostring(Game.GetCurrentGameTurn())
  if Civ6Ai_MpTest._done[key] then
    return
  end
  Civ6Ai_MpTest._done[key] = true
  local seat, unit = Civ6Ai_MpTest.PickSubject()
  log("step|n=" .. step .. "|turn=" .. key .. "|seat=" .. tostring(seat) .. "|unit=" .. tostring(unit and unit:GetID()))
  local fn = Civ6Ai_MpTest.Steps[step]
  if fn ~= nil then
    local ok, err = pcall(fn, seat, unit)
    if not ok then
      log("step_error|n=" .. step .. "|" .. tostring(err))
    end
  end
  for _, mode in ipairs(Civ6Ai_MpTest.STEER_BY_STEP[step] or {}) do
    local ok, err = pcall(Civ6Ai_MpTest._Steer, mode)
    if not ok then
      log("steer_error|" .. tostring(err))
    end
  end
  for _, mode in ipairs(Civ6Ai_MpTest.FORCE_BY_STEP[step] or {}) do
    local ok, err = pcall(Civ6Ai_MpTest._Force, mode)
    if not ok then
      log("force_error|" .. tostring(err))
    end
  end
end

-- ---------------------------------------------------------------------------
-- Turn flow (every PC while test mode is on)
-- ---------------------------------------------------------------------------
function Civ6Ai_MpTest._SkipOwnUnits()
  Civ6Ai_Apply.ResolveAllUnitOrders(Game.GetLocalPlayer())
end

function Civ6Ai_MpTest._ScheduleEndTurn(turn, delay)
  local started = Civ6Ai_OrderChannel._Now()
  Civ6Ai_Util.ScheduleTick(function()
    if Game.GetCurrentGameTurn() ~= turn or not Civ6Ai_Autotest._TurnStillActive(Game.GetLocalPlayer()) then
      return false
    end
    if Civ6Ai_OrderChannel._Now() - started < delay then
      return true
    end
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(Game.GetLocalPlayer())
    Civ6Ai_MpTest._SkipOwnUnits()
    if UI.CanEndTurn ~= nil and not UI.CanEndTurn() then
      return Civ6Ai_OrderChannel._Now() - started < delay + 60
    end
    local ok, why = Civ6Ai_Autotest._RequestEndTurn()
    log("end_turn|turn=" .. turn .. "|ok=" .. tostring(ok) .. "|" .. tostring(why))
    return false
  end)
end

function Civ6Ai_MpTest._OnLocalTurnBegin()
  local turn = Game.GetCurrentGameTurn()
  if Civ6Ai_MpTest._begunTurn == turn then
    return
  end
  if Civ6Ai_MpTest.IsHostRunner() and prop("CIV6AI_MPTEST") ~= 2 then
    Civ6Ai_MpTest._begunTurn = turn
    local started = Civ6Ai_OrderChannel._Now()
    Civ6Ai_Util.ScheduleTick(function()
      if Game.GetCurrentGameTurn() ~= turn then
        return false
      end
      if Civ6Ai_OrderChannel._Now() - started < Civ6Ai_MpTest.STEP_DELAY_SECONDS then
        return true
      end
      Civ6Ai_MpTest._RunHostStep()
      return false
    end)
    Civ6Ai_MpTest._ScheduleEndTurn(turn, Civ6Ai_MpTest.END_TURN_DELAY_SECONDS)
  elseif Civ6Ai_MpTest.IsOn() then
    Civ6Ai_MpTest._begunTurn = turn
    -- The other PC waits longer on the late-order turn so the host's orders
    -- sent after its own end turn still land inside this turn.
    local delay = Civ6Ai_MpTest.END_TURN_DELAY_SECONDS
    if Civ6Ai_MpTest.Step() == 5 then
      delay = delay + Civ6Ai_MpTest.LATE_TURN_HOLD_SECONDS
    end
    Civ6Ai_MpTest._ScheduleEndTurn(turn, delay)
  end
end

function Civ6Ai_MpTest._OnLocalTurnEnd()
  if Civ6Ai_MpTest.IsHostRunner() and Civ6Ai_MpTest._lateTurn == Game.GetCurrentGameTurn() then
    Civ6Ai_MpTest._lateTurn = nil
    local seat, unit = Civ6Ai_MpTest.PickSubject()
    Civ6Ai_OrderChannel.Send(K().PING, {})
    if unit ~= nil then
      local x, y = Civ6Ai_MpTest._FarTarget(unit)
      if x ~= nil then
        Civ6Ai_OrderChannel.Send(K().TEST_FAR_MOVE, { P = seat, U = unit:GetID(), X = x, Y = y })
      end
    end
    log("late_orders_sent|turn=" .. Game.GetCurrentGameTurn())
  end
end

function Civ6Ai_MpTest.Initialize()
  if Civ6Ai_MpTest._initialized or Civ6Ai_OrderChannel == nil or not Civ6Ai_OrderChannel.IsActive() then
    return
  end
  Civ6Ai_MpTest._initialized = true
  if Events.LocalPlayerTurnBegin ~= nil then
    Events.LocalPlayerTurnBegin.Add(Civ6Ai_MpTest._OnLocalTurnBegin)
  end
  if Events.LocalPlayerTurnEnd ~= nil then
    Events.LocalPlayerTurnEnd.Add(Civ6Ai_MpTest._OnLocalTurnEnd)
  end
  log("ready|host_runner=" .. tostring(Civ6Ai_MpTest.IsHostRunner()) .. "|on=" .. tostring(Civ6Ai_MpTest.IsOn()))
end
