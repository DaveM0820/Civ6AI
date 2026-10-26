"""Offline checks for the synced order channel (Gameplay/Civ6Ai_Orders.lua,
InGame/Civ6Ai_OrderChannel.lua): per-turn order queue, sender rules, combat."""
import pathlib
import re
import unittest

try:
    import lupa
except ImportError:  # pragma: no cover
    lupa = None

MOD = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai"

FAKE_ENV = r"""
local function event() local e = {fns={}}; function e.Add(f) table.insert(e.fns, f) end; return e end
GameEvents = setmetatable({}, {__index=function(t,k) local e=event(); rawset(t,k,e); return e end})
ExposedMembers = {}
local props = {}
local turn = 5
Game = {}
function Game.GetCurrentGameTurn() return turn end
function Game:SetProperty(k,v) props[k]=v end
function Game:GetProperty(k) return props[k] end
function SetTurn(t) turn = t end
function GetProp(k) return props[k] end
logs = {}
print = function(s) table.insert(logs, s) end
Map = {GetPlotDistance=function(a,b,c,d) return math.max(math.abs(a-c), math.abs(b-d)) end}
local plots = {}
function Map.GetPlot(x,y)
  local k = tostring(x) .. "," .. tostring(y)
  if plots[k] == nil then
    plots[k] = {x=x,y=y,owner=-1,
      GetX=function(s) return s.x end, GetY=function(s) return s.y end,
      GetOwner=function(s) return s.owner end, SetOwner=function(s,p) s.owner=p end,
      GetIndex=function(s) return s.x*1000+s.y end,
      GetImprovementType=function(s) return s.improvement end}
  end
  return plots[k]
end
local function mkUnit(owner,id,x,y,typ)
  local u = {owner=owner,id=id,x=x,y=y,moves=2,typ=typ,dmg=0}
  function u:GetID() return self.id end
  function u:GetOwner() return self.owner end
  function u:GetX() return self.x end
  function u:GetY() return self.y end
  function u:GetType() return self.typ end
  function u:GetMovesRemaining() return self.moves end
  function u:GetDamage() return self.dmg end
  function u:GetMaxDamage() return 100 end
  function u:ChangeDamage(n) self.dmg = self.dmg + n end
  function u:GetComponentID() return self end
  function u:GetAttacksRemaining() return 1 end
  function u:GetRange() return (GameInfo.Units[self.typ].Range or 0) end
  function u:GetExperience() local me=self; return {ChangeExperience=function(_, n) me.xp=(me.xp or 0)+n end} end
  function u:GetBuildCharges() return self.charges or 0 end
  function u:ChangeBuildCharges(n) self.charges = (self.charges or 0) + n end
  return u
end
MkUnit = mkUnit
local function mkPlayer(id,human,units)
  local p = {id=id,human=human,units=units}
  function p:IsAlive() return true end
  function p:IsHuman() return self.human end
  function p:IsTurnActive() return self.active ~= false end
  function p:GetUnits()
    local me=self
    return {Members=function() local i=0; return function() i=i+1; if me.units[i] then return i, me.units[i] end end end,
            FindID=function(_, id) for _,u in ipairs(me.units) do if u.id==id then return u end end end}
  end
  function p:GetCities() return {Members=function() return function() return nil end end} end
  function p:GetTreasury()
    local me=self
    me.gold = me.gold or 200
    return {GetGoldBalance=function() return me.gold end,
            ChangeGoldBalance=function(_, n) me.gold = me.gold + n end}
  end
  function p:GetReligion()
    local me=self
    me.faith = me.faith or 0
    return {GetFaithBalance=function() return me.faith end,
            ChangeFaithBalance=function(_, n) me.faith = me.faith + n end}
  end
  function p:IsBarbarian() return self.barb == true end
  function p:GetTeam() return self.id end
  function p:GetDiplomacy()
    local me=self
    me.war = me.war or {}
    return {
      IsAtWarWith=function(_, o) return me.war[o] == true end,
      CanDeclareWarOn=function(_, o) return me.war[o] ~= true end,
      CanMakePeaceWith=function(_, o) return me.war[o] == true end,
      DeclareWarOn=function(_, o) me.war[o] = true end,
      MakePeaceWith=function(_, o) me.war[o] = nil end,
    }
  end
  function p:GetTechs()
    local me=self
    me.knownTech = me.knownTech or {}
    return {
      HasTech=function(_, i) return me.knownTech[i] == true end,
      GetResearchingTech=function() return me.researching end,
      SetResearchingTech=function(_, i) me.researching = i end,
    }
  end
  function p:GetCulture()
    local me=self
    me.knownCivic = me.knownCivic or {}
    return {
      HasCivic=function(_, i) return me.knownCivic[i] == true end,
      GetProgressingCivic=function() return me.progressingCivic end,
    }
  end
  return p
end
GameInfo = {Units={[0]={Combat=20,UnitType="UNIT_WARRIOR",Hash=100},[1]={Combat=15,RangedCombat=25,Range=2},
                    UNIT_WARRIOR={Index=0,UnitType="UNIT_WARRIOR",Hash=100}},
            Buildings={BUILDING_MONUMENT={Index=2,BuildingType="BUILDING_MONUMENT",Hash=200},[2]={BuildingType="BUILDING_MONUMENT",Hash=200}},
            Yields={YIELD_GOLD={Index=0},YIELD_FAITH={Index=5}},
            Improvements={IMPROVEMENT_FARM={Index=0,ImprovementType="IMPROVEMENT_FARM"},
                          [0]={Index=0,ImprovementType="IMPROVEMENT_FARM"}}}
WarTypes = {FORMAL_WAR=1, SURPRISE_WAR=2}
Players = {[0]=mkPlayer(0,true,{mkUnit(0,1,5,5,0)}), [1]=mkPlayer(1,true,{mkUnit(1,2,6,6,0)}),
           [2]=mkPlayer(2,false,{mkUnit(2,7,10,10,0), mkUnit(2,8,11,10,0), mkUnit(2,9,12,10,1)})}
Units = {GetUnitsInPlot=function(plot)
  local out = {}
  for id=0,63 do local p=Players[id]; if p then for _,u in ipairs(p.units) do
    if u.x==plot.x and u.y==plot.y then out[#out+1]=u end end end end
  return out end}
UnitOperationTypes = {MOVE_TO=1, RANGE_ATTACK=2, AIR_ATTACK=3, COASTAL_RAID=4, PARAM_X="x", PARAM_Y="y", PARAM_MODIFIERS="mods"}
UnitOperationMoveModifiers = {ATTACK=1, MOVE_IGNORE_UNEXPLORED_DESTINATION=2, NONE=0}
attackOps = {}
CombatTypes = {MELEE=0, RANGED=1, BOMBARD=2}
CombatResultParameters = {ATTACKER="A", DEFENDER="D", DAMAGE_TO="dmg"}
CombatManager = {SimulateAttackVersus=function(a, d, ctype)
  if ctype == CombatTypes.MELEE then return {A={dmg=20}, D={dmg=35}} end
  return {A={dmg=0}, D={dmg=30}} end}
UnitManager = {
  Kill=function(u) u.dead=true; local p=Players[u.owner]; for i,x in ipairs(p.units) do if x==u then table.remove(p.units,i) break end end end,
  MoveUnit=function(u,x,y) u.x=x; u.y=y; u.moves=u.moves-1 end,
  FinishMoves=function(u) u.moves=0 end,
  RestoreMovement=function(u) u.moves=2 end,
  CanStartOperation=function(unit, op, _, params)
    local row = GameInfo.Units[unit:GetType()]
    local ranged = row and (row.Range or 0) > 0 and ((row.RangedCombat or 0) > 0 or (row.Bombard or 0) > 0)
    if op == UnitOperationTypes.RANGE_ATTACK then return ranged == true end
    if op == UnitOperationTypes.MOVE_TO then return not ranged end
    return false
  end,
  RequestOperation=function(unit, op, params)
    attackOps[#attackOps+1] = {id=unit.id, op=op, x=params.x, y=params.y}
    unit.moves = 0
    return true
  end,
  InitUnit=function(pid, typ, x, y)
    local p=Players[pid]; local id=100+#p.units; local u=MkUnit(pid,id,x,y,0); table.insert(p.units,u); return u end,
}
ImprovementBuilder = {
  CanHaveImprovement=function(plot, idx, team) return true end,
  SetImprovementType=function(plot, idx, owner) plot.improvement = idx end,
}
-- GameCore routes: a move fails with plot_occupied while a seat unit sits there.
ExposedMembers.Civ6Ai = {
  MoveUnitForPlayer=function(p,uid,x,y)
    for _,u in ipairs(Players[p].units) do if u.x==x and u.y==y then return false, "plot_occupied" end end
    for _,u in ipairs(Players[p].units) do if u.id==uid then u.x=x; u.y=y; u.moves=0; return true, "moved" end end
    return false, "unit_not_found" end,
  MoveUnitAlongPathForPlayer=function(p,uid,x,y)
    for _,u in ipairs(Players[p].units) do if u.x==x and u.y==y and u.id~=uid then return false, "plot_occupied" end end
    for _,u in ipairs(Players[p].units) do if u.id==uid then u.x=x; u.y=y; u.moves=0; return true, "moved" end end
    return false, "unit_not_found" end,
  SetResearchForPlayer=function(p,i) Players[p].tech=i; return true, "tech="..i end,
  SetCivicForPlayer=function(p,i) Players[p].civic=i; return true, "civic="..i end,
  FinishMovesForPlayer=function(p,uid) return true, "finished" end,
  CanFoundCityForPlayer=function(p,uid)
    for _,u in ipairs(Players[p].units) do if u.id==uid then
      if GameInfo.Units[u.typ] and GameInfo.Units[u.typ].FoundCity then return true, "" end
    end end
    return false, "unit_cannot_found_city" end,
  FoundCityForPlayer=function(p,uid)
    for i,u in ipairs(Players[p].units) do if u.id==uid then
      Players[p].founded = {x=u.x, y=u.y}; table.remove(Players[p].units, i); return true, "founded"
    end end
    return false, "stale_unit_id" end,
}
published = {}
LuaEvents = {Civ6Ai_PlayerTurnStartComplete=function(p)
  table.insert(published, {p=p, y=Players[2].units[1].y}) end}
"""


def _vals(t):
    return list(t.values()) if t is not None else []


@unittest.skipIf(lupa is None, "lupa not installed")
class OrdersGameplayTests(unittest.TestCase):
    def setUp(self):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.rt.execute(FAKE_ENV)
        self.rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())

    def order(self, sender, **params):
        params.setdefault("T", 5)
        self.rt.globals().Civ6Ai_Orders.OnOrder(sender, self.rt.table_from(params))

    def results(self):
        return [dict(r.items()) for r in _vals(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))]

    def last(self):
        return self.results()[-1]

    def turn_start(self, owner, turn=None):
        if turn is not None:
            self.rt.globals().SetTurn(turn)
        self.rt.eval("GameEvents.PlayerTurnStartComplete.fns[1]")(owner)

    def _early_world(self, cities=1, war=False, barb_at=None):
        self.rt.execute("""
          EarlyCities = {}
          BarbUnits = {}
          for i = 1, %d do EarlyCities[i] = { GetID = function() return i end, GetX = function() return 10 * i end, GetY = function() return 10 end } end
          Players[7] = {
            IsMajor = function() return true end,
            GetCities = function() return { Members = function() local i = 0; return function() i = i + 1; if EarlyCities[i] then return i, EarlyCities[i] end end end } end,
            GetDiplomacy = function() return { IsAtWarWith = function(_, o) return %s and o == 8 end } end,
          }
          Players[8] = { IsMajor = function() return true end, IsBarbarian = function() return false end }
          Players[63] = { IsBarbarian = function() return true end }
          PlayerManager = PlayerManager or {}
          PlayerManager.GetAliveMajorIDs = function() return { 7, 8 } end
          GameInfo.Improvements = GameInfo.Improvements or {}
          Units = Units or {}
          Units.GetUnitsInPlot = function(plot) return BarbUnits[plot:GetX() .. "," .. plot:GetY()] or {} end
          Civ6Ai_Orders._earlyCache = {}
          Game:SetProperty("CIV6AI_PRIO_7_19", 3)
        """ % (cities, "true" if war else "false"))
        if barb_at is not None:
            self.rt.execute('BarbUnits["%d,%d"] = { { GetOwner = function() return 63 end } }' % barb_at)

    def test_early_mode_expand_then_threat_then_off(self):
        O = self.rt.globals().Civ6Ai_Orders
        self._early_world(cities=1)
        self.assertEqual("expand", O.EarlyMode(7))
        self._early_world(cities=1, barb_at=(13, 12))
        self.assertEqual("threat", O.EarlyMode(7))
        self._early_world(cities=1, war=True)
        self.assertEqual("threat", O.EarlyMode(7))
        self._early_world(cities=3)
        self.assertIsNone(O.EarlyMode(7))
        self._early_world(cities=1)
        self.rt.globals().SetTurn(61)
        self.assertIsNone(O.EarlyMode(7))

    def test_early_threat_clears_once_army_outnumbers_hostiles(self):
        O = self.rt.globals().Civ6Ai_Orders
        self._early_world(cities=1, barb_at=(13, 12))
        self.rt.execute("""
          GameInfo.Units = GameInfo.Units or {}
          GameInfo.Units["UNIT_SCOUT"] = { Combat = 10, PromotionClass = "PROMOTION_CLASS_RECON", FormationClass = "FORMATION_CLASS_LAND_COMBAT" }
          GameInfo.Units["UNIT_WARRIOR"] = { Combat = 20, PromotionClass = "PROMOTION_CLASS_MELEE", FormationClass = "FORMATION_CLASS_LAND_COMBAT" }
          BarbUnits["10,10"] = { { GetOwner = function() return 7 end, GetType = function() return "UNIT_WARRIOR" end },
                                 { GetOwner = function() return 7 end, GetType = function() return "UNIT_WARRIOR" end } }
        """)
        self.assertEqual("expand", O.EarlyMode(7))
        self._early_world(cities=1)
        self.rt.execute('BarbUnits["12,12"] = { { GetOwner = function() return 63 end, GetType = function() return "UNIT_SCOUT" end } }')
        self.assertEqual("expand", O.EarlyMode(7))  # a barbarian scout is not a threat

    def test_early_strategy_handlers_answer_from_early_mode(self):
        self._early_world(cities=1)
        expand = self.rt.eval("GameEvents.Civ6AiEarlyExpand.fns[1]")
        threat = self.rt.eval("GameEvents.Civ6AiEarlyThreat.fns[1]")
        self.assertTrue(expand(7, 0))
        self.assertFalse(threat(7, 0))

    def test_registers_event_handler(self):
        self.assertEqual(len(_vals(self.rt.eval("GameEvents.Civ6AiOrder.fns"))), 1)
        self.assertEqual(len(_vals(self.rt.eval("GameEvents.OnGameTurnStarted.fns"))), 1)
        self.assertEqual(len(_vals(self.rt.eval("GameEvents.PlayerTurnStartComplete.fns"))), 1)

    def test_first_ai_order_claims_controller_and_blocks_others(self):
        self.order(0, K=2, P=2, I=3, S=1)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_CONTROLLER')"), 0)
        self.order(1, K=1, P=2, U=7, X=10, Y=11, S=2)
        self.assertEqual(self.last()["reason"], "not_controller")
        self.assertEqual(self.rt.eval("Players[2].units[1].y"), 10)

    def test_human_cannot_order_other_humans_units(self):
        self.order(1, K=1, P=0, U=1, X=5, Y=6, S=3)
        self.assertEqual(self.last()["reason"], "not_owner")

    def test_stale_turn_recorded_not_applied(self):
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=4, T=4)
        self.assertTrue(self.last()["reason"].startswith("stale_turn"))
        self.assertEqual(self.rt.eval("Players[2].units[1].y"), 10)

    def test_batch_queued_until_seat_turn_starts_then_retries_occupied(self):
        # Unit 7 moves onto unit 8's tile; unit 8 moves away second. Pass 1
        # fails 7 (occupied), moves 8; pass 2 moves 7.
        self.order(0, K=1, P=2, U=7, X=11, Y=10, S=5, B=9, J=1, N=2, T=6)
        self.order(0, K=1, P=2, U=8, X=11, Y=11, S=6, B=9, J=2, N=2, T=6)
        self.assertIsNone(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_T')"), 6)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_LAST_SEQ_0')"), 6)
        self.turn_start(2, turn=6)
        res = self.results()
        self.assertEqual([r["seq"] for r in res], [6, 5])
        self.assertTrue(all(r["ok"] for r in res))
        self.assertEqual(self.rt.eval("Players[2].units[1].x"), 11)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_T')"), -1)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_STARTED_2')"), 6)

    def test_queue_is_game_state_and_survives_a_reload(self):
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1, T=6)
        self.rt.execute("Civ6Ai_Orders = nil; GameEvents.PlayerTurnStartComplete.fns = {}")
        self.rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[2].tech"), 4)

    def test_snapshot_published_after_queue_ran(self):
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=5, B=9, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        pub = dict(self.rt.eval("published[1]").items())
        self.assertEqual((pub["p"], pub["y"]), (2, 11))
        self.assertEqual(self.rt.eval("ExposedMembers.Civ6Ai.TurnStartComplete[2]"), 6)

    def test_no_queue_leaves_seat_to_the_game_ai(self):
        self.turn_start(2, turn=6)
        self.assertIsNone(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))
        self.assertEqual(self.rt.eval("Players[2].units[2].moves"), 2)

    def test_unordered_units_go_to_game_ai_same_turn_builders_too(self):
        # Like Civ 5: a unit with no successful order is left to the game's AI
        # this turn (moves kept), not held for two idle turns.
        self.rt.execute("GameInfo.Units[2] = {BuildCharges=3}; table.insert(Players[2].units, MkUnit(2,10,1,1,2))")
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[2].units[2].moves"), 2)
        self.assertEqual(self.rt.eval("Players[2].units[4].moves"), 2)
        logs = [str(x) for x in _vals(self.rt.eval("logs"))]
        self.assertTrue(any("finish_idle|player=2|" in l and "native=" in l and "native=0" not in l for l in logs), logs)

    def test_model_ordered_unit_ends_its_turn_so_game_ai_cannot_override(self):
        # Unit 8 told to Skip (hold): the order succeeds and the unit's moves
        # end, so the game's AI cannot move it; unordered units keep moves.
        uid = self.rt.eval("Players[2].units[2].id")
        self.order(0, K=5, P=2, U=uid, S=9, B=2, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        res = self.results()
        self.assertTrue(any(r["seq"] == 9 and r["ok"] for r in res), res)
        self.assertEqual(self.rt.eval("Players[2].units[2].moves"), 0)
        self.assertEqual(self.rt.eval("Players[2].units[1].moves"), 2)

    def test_human_seat_units_are_never_finished(self):
        self.rt.execute("Players[2].human = true")
        self.rt.globals().Civ6Ai_Orders._FinishIdleUnits(2, None)
        self.assertEqual(self.rt.eval("Players[2].units[1].moves"), 2)

    def test_fallback_never_touches_a_model_ordered_unit(self):
        # Unit 7's model move succeeds; its defend hint must not run. Unit 8 has
        # no model order, so its defend hint (fortify) runs as a fallback.
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=70, B=7, J=1, N=3, T=6)
        self.order(0, K=36, P=2, U=7, A=3, X=-1, Y=-1, S=71, B=7, J=2, N=3, T=6)
        self.order(0, K=36, P=2, U=8, A=3, X=-1, Y=-1, S=72, B=7, J=3, N=3, T=6)
        self.turn_start(2, turn=6)
        res = self.results()
        fallback_units = {r["unit"] for r in res if r.get("source") == "fallback"}
        self.assertNotIn(7, fallback_units, res)
        self.assertIn(8, fallback_units, res)
        self.assertEqual((self.rt.eval("Players[2].units[1].x"), self.rt.eval("Players[2].units[1].y")), (10, 11))
        logs = [str(x) for x in _vals(self.rt.eval("logs"))]
        self.assertFalse(any("source=fallback" in line and "entity=unit:7|" in line for line in logs), logs)

    def test_failed_model_order_leaves_the_unit_to_the_fallback(self):
        # A model attack that fails (no enemy there) does not count as handled.
        self.order(0, K=7, P=2, U=7, X=15, Y=15, S=80, B=8, J=1, N=2, T=6)
        self.order(0, K=36, P=2, U=7, A=3, X=-1, Y=-1, S=81, B=8, J=2, N=2, T=6)
        self.turn_start(2, turn=6)
        res = self.results()
        self.assertTrue(any(r["seq"] == 80 and not r["ok"] for r in res), res)
        self.assertTrue(any(r.get("source") == "fallback" and r["unit"] == 7 and r["ok"] for r in res), res)

    def test_settler_fallback_founds_on_its_hinted_site(self):
        self.rt.execute("GameInfo.Units[3] = {FoundCity=true, UnitType='UNIT_SETTLER'}; Players[2].units[2].typ = 3")
        self.order(0, K=36, P=2, U=8, A=4, X=11, Y=10, S=95, B=11, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual({"x": 11, "y": 10}, dict(self.rt.eval("Players[2].founded").items()))

    def test_hints_get_a_result_and_are_not_orders(self):
        self.order(0, K=36, P=2, U=8, A=2, X=-1, Y=-1, S=90, B=10, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        hint = [r for r in self.results() if r["seq"] == 90]
        self.assertEqual(1, len(hint))
        self.assertEqual("hint", hint[0]["source"])
        self.assertEqual(self.rt.eval("Players[2].units[2].x"), 11)  # improve hint without target: no move

    def test_late_batch_runs_while_seat_turn_is_active(self):
        self.turn_start(2)
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1)
        self.assertTrue(self.last()["ok"])
        self.assertEqual(self.rt.eval("Players[2].tech"), 4)
        self.rt.execute("Players[2].active = false")
        # Same turn still applies (T1 LAN: FINISH_SEAT can race EXECUTE_SCRIPT).
        self.order(0, K=2, P=2, I=5, S=8, B=2, J=1, N=1)
        self.assertTrue(self.last()["ok"])
        self.assertEqual(self.rt.eval("Players[2].tech"), 5)
        # A batch for a past turn after the seat ended is still rejected.
        self.order(0, K=2, P=2, I=6, S=9, B=3, J=1, N=1, T=4)
        self.assertEqual(self.last()["reason"], "stale_turn:4")

    def test_same_turn_batch_queued_for_this_turn_plays_at_seat_turn_start(self):
        # Same-turn timing (SP): the seat is snapshotted during the host's turn 5
        # before its own turn 5 started, so the answer is a batch for turn 5.
        self.turn_start(2, turn=4)
        self.rt.globals().SetTurn(5)
        self.rt.execute("for _, u in ipairs(Players[2].units) do u.GetMaxMoves = function() return 2 end end")
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=5, B=9, J=1, N=1, T=5)
        self.assertIsNone(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_T')"), 5)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any("queued|player=2|for_turn=5" in line for line in logs))
        self.turn_start(2)
        self.assertTrue(self.last()["ok"])
        self.assertEqual(self.rt.eval("Players[2].units[1].y"), 11)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any("queue_apply|player=2|turn=5|orders=1" in line for line in logs))
        units = [line for line in logs if "queue_units|player=2|turn=5" in line]
        self.assertEqual(1, len(units))
        self.assertIn("below_full=0", units[0])
        self.assertIn("7@10,10:2/2", units[0])

    def test_batch_for_a_past_or_far_turn_is_refused(self):
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1, T=4)
        self.assertEqual(self.last()["reason"], "stale_turn:4")
        self.order(0, K=2, P=2, I=4, S=8, B=2, J=1, N=1, T=7)
        self.assertEqual(self.last()["reason"], "stale_turn:7")
        self.assertIsNone(self.rt.eval("GetProp('CIV6AI_Q_2_T')"))

    def test_open_batch_is_flushed_once_its_turn_passes(self):
        self.order(0, K=2, P=2, I=4, S=21, B=8, J=1, N=2, T=5)
        self.assertEqual(self.results(), [])
        self.rt.globals().SetTurn(6)
        self.rt.globals().Civ6Ai_Orders.OnGameTurnStarted(6)
        reasons = [r["reason"] for r in self.results()]
        self.assertIn("stale_turn:5", reasons)
        self.assertIn("batch_order_missing:2", reasons)

    def test_queue_for_a_missed_turn_is_dropped(self):
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=7)
        self.assertEqual(self.last()["reason"], "stale_turn:6")
        self.assertIsNone(self.rt.eval("Players[2].tech"))

    def test_new_batch_flushes_incomplete_old_one(self):
        self.order(0, K=2, P=2, I=3, S=7, B=1, J=1, N=2, T=6)
        self.order(0, K=2, P=2, I=4, S=8, B=2, J=1, N=1, T=6)
        reasons = [r["reason"] for r in self.results()]
        self.assertIn("batch_order_missing:2", reasons)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[2].tech"), 4)

    def test_ranged_attack_uses_engine_forecast(self):
        self.rt.execute("Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,4,13,10,0))")
        self.order(0, K=7, P=2, U=9, X=13, Y=10, S=11)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(self.last()["reason"].startswith("ranged:def_dmg=0>30:att_dmg=0>0"), self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[2].units[3].moves"), 0)
        self.assertEqual(self.rt.eval("Players[1].units[#Players[1].units].dmg"), 30)
        self.assertEqual(self.rt.eval("#attackOps"), 0)

    def test_ranged_attack_respects_range(self):
        self.rt.execute("Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,4,15,10,0))")
        self.order(0, K=7, P=2, U=9, X=15, Y=10, S=11)
        self.assertEqual(self.last()["reason"], "out_of_range:3")

    def test_melee_attack_needs_enemy_adjacency_and_war(self):
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=12)
        self.assertEqual(self.last()["reason"], "no_enemy_on_plot")
        self.rt.execute("table.insert(Players[1].units, MkUnit(1,3,10,11,0))")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=13)
        self.assertEqual(self.last()["reason"], "not_at_war")
        self.rt.execute("Players[2].war = {[1]=true}")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=14)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(self.last()["reason"].startswith("melee:"), self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[2].units[1].dmg"), 20)
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 35)
        self.assertEqual(self.rt.eval("#attackOps"), 0)

    def test_attack_and_city_strike_run_before_a_move(self):
        # The move is listed first and would spend the unit (moves left = 0).
        # The attack must still land, and the city strike must run before it.
        self.rt.execute("Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,3,10,11,0))")
        self.order(0, K=1, P=2, U=7, X=9, Y=10, S=21, B=3, J=1, N=3, T=6)
        self.order(0, K=31, P=2, I=99, X=10, Y=11, S=22, B=3, J=2, N=3, T=6)
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=23, B=3, J=3, N=3, T=6)
        self.turn_start(2, turn=6)
        res = self.results()
        self.assertEqual([r["kind"] for r in res[:3]], [31, 7, 1])
        attack = next(r for r in res if r["kind"] == 7)
        self.assertTrue(attack["ok"], attack["reason"])
        self.assertTrue(str(attack["reason"]).startswith("melee:"), attack["reason"])
        # Melee (35) plus the idle archer's auto shot (30).
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 65)
        self.assertEqual(self.rt.eval("Players[2].units[2].dmg"), 0)
        self.assertEqual(self.rt.eval("#attackOps"), 0)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any(
            "CIV6AI|attacks|player=2|turn=6|executed=1|failed=1|unit=1|city=0" in line
            for line in logs
        ), logs)
        self.assertTrue(any("CIV6AI|attacks|auto|player=2|turn=6|unit=1|city=0" in line for line in logs), logs)
        self.assertTrue(any("AUTO_U_9_10_11" in line for line in logs), logs)

    def test_move_onto_enemy_attacks_when_it_can(self):
        self.rt.execute("Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,3,10,11,0))")
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=40)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(str(self.last()["reason"]).startswith("attack_instead:melee"), self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 35)
        self.order(0, K=1, P=2, U=9, X=10, Y=11, S=41)
        self.assertTrue(str(self.last()["reason"]).startswith("attack_instead:ranged"), self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 65)
        self.rt.execute(
            "Map.GetPlot(10,11):SetOwner(2); "
            "GameInfo.Units[2] = {BuildCharges=3, Combat=0}; "
            "table.insert(Players[2].units, MkUnit(2,40,8,10,2))"
        )
        self.order(0, K=1, P=2, U=40, X=10, Y=11, S=42)
        self.assertFalse(self.last()["ok"])
        self.assertIn("cannot attack", str(self.last()["reason"]))
        self.rt.execute("table.insert(Players[1].units, MkUnit(1,5,15,15,0))")
        self.order(0, K=1, P=2, U=8, X=15, Y=15, S=43)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(str(self.last()["reason"]).startswith("approached:"), self.last()["reason"])
        self.assertNotEqual(
            (self.rt.eval("Players[2].units[2].x"), self.rt.eval("Players[2].units[2].y")),
            (11, 10),
        )

    def test_out_of_reach_move_attacks_when_a_move_remains(self):
        self.rt.execute(
            "Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,5,15,15,0)); "
            "ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = function(p,uid,x,y) "
            "for _,u in ipairs(Players[p].units) do if u.id==uid then u.x=x; u.y=y; "
            "if u.moves > 0 then u.moves = u.moves - 1 end; return true, 'moved' end end "
            "return false, 'missing' end"
        )
        self.order(0, K=1, P=2, U=8, X=15, Y=15, S=44)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIn("attack_instead:melee:def_dmg=0>35", str(self.last()["reason"]))
        self.assertTrue(str(self.last()["reason"]).startswith("approached:"), self.last()["reason"])
        self.assertEqual(self.rt.eval("#attackOps"), 0)
        self.assertEqual(self.rt.eval("Players[1].units[#Players[1].units].dmg"), 35)

    def test_zero_hp_city_is_an_engine_attack_not_a_refused_capture(self):
        self.rt.execute(r"""
          DefenseTypes = {DISTRICT_OUTER=1, DISTRICT_GARRISON=2}
          local district = {id=42, x=20, y=20, wdmg=0, gdmg=200}
          function district:GetID() return self.id end
          function district:GetX() return self.x end
          function district:GetY() return self.y end
          function district:GetType() return 0 end
          function district:GetMaxDamage(t) if t == 1 then return 0 end return 200 end
          function district:GetDamage(t) if t == 1 then return self.wdmg end return self.gdmg end
          function district:ChangeDamage(t, n)
            local cap = t == 1 and 0 or 200
            local cur = t == 1 and self.wdmg or self.gdmg
            local nxt = cur + n
            if nxt > cap then nxt = cap end
            if t == 1 then self.wdmg = nxt else self.gdmg = nxt end
          end
          local city = {id=7, owner=1, x=20, y=20}
          function city:GetID() return self.id end
          function city:GetOwner() return self.owner end
          function city:GetX() return self.x end
          function city:GetY() return self.y end
          function city:GetDistricts()
            return {Members=function()
              local i=0
              return function() i=i+1; if i==1 then return i, district end end
            end}
          end
          Cities = {GetCityInPlot=function(x, y) if x == 20 and y == 20 then return city end end}
          CityManager = { TransferCity = function(c, owner) c.owner = owner end }
          Players[1].war = {[2]=true}
          Players[2].war = {[1]=true}
          table.insert(Players[2].units, MkUnit(2, 30, 20, 21, 0))
          zeroCity = district
          zeroCityObj = city
        """)
        self.order(0, K=7, P=2, U=30, X=20, Y=20, S=72)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIn("captured=true", str(self.last()["reason"]))
        self.assertNotIn("damage_not_applied", str(self.last()["reason"]))
        self.assertNotIn("zero_damage", str(self.last()["reason"]))
        self.assertEqual(self.rt.eval("zeroCity.gdmg"), 200)
        self.assertEqual(self.rt.eval("zeroCityObj.owner"), 2)
        self.assertEqual(self.rt.eval("Players[2].units[#Players[2].units].x"), 20)
        self.assertEqual(self.rt.eval("Players[2].units[#Players[2].units].y"), 20)
        self.assertEqual(self.rt.eval("#attackOps"), 0)
        # A hit that reduces the city to 0 captures through AcquireCity when
        # TransferCity is absent. Damage that does not stick on a living city
        # is still refused. Ranged fire does not take the city. A forecast
        # that throws still captures a city that is already at 0 HP.
        self.rt.execute(r"""
          CityManager.TransferCity = nil
          Players[2].AcquireCity = function(self, city)
            city.owner = 2
          end
          local function mk(id, x, y, gdmg, gmax, wmax, clamp)
            local d = {id=id, x=x, y=y, wdmg=0, gdmg=gdmg, gmax=gmax, wmax=wmax}
            function d:GetID() return self.id end
            function d:GetX() return self.x end
            function d:GetY() return self.y end
            function d:GetType() return 0 end
            function d:GetComponentID() return self end
            function d:GetMaxDamage(t) if t == 1 then return self.wmax end return self.gmax end
            function d:GetDamage(t) if t == 1 then return self.wdmg end return self.gdmg end
            function d:ChangeDamage(t, n)
              if not clamp then return end
              if t == 1 then self.wdmg = math.min(self.wmax, self.wdmg + n)
              else self.gdmg = math.min(self.gmax, self.gdmg + n) end
            end
            local c = {id=id, owner=1, x=x, y=y, district=d}
            function c:GetID() return self.id end
            function c:GetOwner() return self.owner end
            function c:GetX() return self.x end
            function c:GetY() return self.y end
            function c:GetDistricts()
              local me = self
              return {Members=function()
                local i = 0
                return function() i = i + 1; if i == 1 then return i, me.district end end
              end}
            end
            return c
          end
          lowCity = mk(11, 22, 22, 180, 200, 0, true)
          stuckCity = mk(12, 24, 24, 0, 200, 100, false)
          rangedCity = mk(13, 26, 26, 200, 200, 0, true)
          deadThrow = mk(14, 28, 28, 200, 200, 0, true)
          deadThrow.district.GetComponentID = nil
          setmetatable(deadThrow.district, {__index = function(_, key)
            if key == "GetComponentID" then error("function expected instead of nil") end
          end})
          local prev = Cities.GetCityInPlot
          function Cities.GetCityInPlot(x, y)
            if x == 22 and y == 22 then return lowCity end
            if x == 24 and y == 24 then return stuckCity end
            if x == 26 and y == 26 then return rangedCity end
            if x == 28 and y == 28 then return deadThrow end
            return prev(x, y)
          end
          table.insert(Players[2].units, MkUnit(2, 31, 22, 23, 0))
          table.insert(Players[2].units, MkUnit(2, 32, 24, 25, 0))
          table.insert(Players[2].units, MkUnit(2, 33, 26, 28, 1))
          table.insert(Players[2].units, MkUnit(2, 34, 28, 29, 0))
        """)
        self.order(0, K=7, P=2, U=31, X=22, Y=22, S=73)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIn("captured=true", str(self.last()["reason"]))
        self.assertEqual(self.rt.eval("lowCity.owner"), 2)
        self.assertEqual(self.rt.eval("Players[2]:GetUnits():FindID(31).x"), 22)
        self.assertEqual(self.rt.eval("Players[2]:GetUnits():FindID(31).y"), 22)
        self.order(0, K=7, P=2, U=32, X=24, Y=24, S=74)
        self.assertFalse(self.last()["ok"])
        self.assertIn("damage_not_applied", str(self.last()["reason"]))
        self.assertEqual(self.rt.eval("stuckCity.owner"), 1)
        self.order(0, K=7, P=2, U=33, X=26, Y=26, S=75)
        self.assertFalse(self.last()["ok"], self.last()["reason"])
        self.assertIn("damage_not_applied", str(self.last()["reason"]))
        self.assertEqual(self.rt.eval("rangedCity.owner"), 1)
        self.order(0, K=7, P=2, U=34, X=28, Y=28, S=76)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIn("captured=true", str(self.last()["reason"]))
        self.assertNotIn("forecast_failed", str(self.last()["reason"]))
        self.assertEqual(self.rt.eval("deadThrow.owner"), 2)

    def test_impassable_move_steps_toward_the_target(self):
        self.rt.execute(r"""
          local peak = Map.GetPlot(14, 10)
          function peak:IsImpassable() return true end
          function peak:IsMountain() return true end
          local sea = Map.GetPlot(12, 8)
          function sea:IsWater() return true end
          local orig = ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer
          ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = function(p, uid, x, y)
            local plot = Map.GetPlot(x, y)
            if plot.IsWater ~= nil and plot:IsWater() == true then return false, "water" end
            if plot.IsMountain ~= nil and plot:IsMountain() == true then return false, "impassable" end
            return orig(p, uid, x, y)
          end
        """)
        self.order(0, K=1, P=2, U=9, X=14, Y=10, S=62, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        reasons = [str(row["reason"]) for row in self.results()]
        self.assertTrue(any("step_toward:14,10>13,10" in reason for reason in reasons), reasons)
        self.assertEqual(self.rt.eval("Players[2].units[3].x"), 13)
        self.assertEqual(self.rt.eval("Players[2].units[3].y"), 10)
        self.rt.execute("Players[2].units[3].x = 12; Players[2].units[3].y = 10; Players[2].units[3].moves = 2")
        self.order(0, K=1, P=2, U=9, X=12, Y=8, S=63, B=1, J=1, N=1, T=7)
        self.turn_start(2, turn=7)
        reasons = [str(row["reason"]) for row in self.results()]
        self.assertTrue(any("step_toward:12,8>12,9" in reason for reason in reasons), reasons)
        self.assertNotEqual((self.rt.eval("Players[2].units[3].x"), self.rt.eval("Players[2].units[3].y")), (12, 8))

    def test_ranged_auto_fires_after_a_failed_move(self):
        self.rt.execute(r"""
          Players[2].war = {[1]=true}
          table.insert(Players[1].units, MkUnit(1,4,13,10,0))
          local peak = Map.GetPlot(12, 11)
          function peak:IsImpassable() return true end
          function peak:IsMountain() return true end
        """)
        self.order(0, K=1, P=2, U=9, X=12, Y=11, S=60, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertIn("impassable", [r["reason"] for r in self.results()])
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertTrue(any("AUTO_U_9_13_10" in line for line in logs), logs)

    def test_ranged_auto_fires_when_the_move_leaves_a_target_in_range(self):
        self.rt.execute(r"""
          Players[2].war = {[1]=true}
          table.insert(Players[1].units, MkUnit(1,4,14,10,0))
          ExposedMembers.Civ6Ai.MoveUnitForPlayer = function(p,uid,x,y)
            for _,u in ipairs(Players[p].units) do
              if u.id==uid then u.x=x; u.y=y; u.moves=u.moves-1; return true, "moved" end
            end
            return false, "missing"
          end
        """)
        self.order(0, K=1, P=2, U=9, X=12, Y=9, S=61, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[2].units[3].x"), 12)
        self.assertEqual(self.rt.eval("Players[2].units[3].y"), 9)
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertFalse(any("AUTO_U_9_14_10" in line for line in logs), logs)
        self.assertFalse(any("source=fallback" in line and "entity=unit:9" in line for line in logs), logs)

    def test_ranged_auto_skips_melee_humans_and_lethal_forecasts(self):
        self.rt.execute("Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,3,10,11,0))")
        self.order(0, K=1, P=2, U=7, X=9, Y=10, S=50, B=1, J=1, N=1, T=6, AR=0)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 0)
        self.rt.execute(
            "Players[0].units[1].typ = 1; Players[0].war = {[1]=true}; "
            "table.insert(Players[1].units, MkUnit(1,6,6,6,0))"
        )
        self.order(0, K=2, P=0, I=3, S=52, B=3, J=1, N=1, T=6, AR=2)
        self.turn_start(0, turn=6)
        logs = " ".join(list(self.rt.eval("logs").values()))
        self.assertIn("attacks|auto|player=0", logs)
        self.rt.execute("Players[0].units[1].moves = 2")
        self.order(0, K=2, P=0, I=4, S=55, B=6, J=1, N=1, T=7)
        self.turn_start(0, turn=7)
        human_logs = [line for line in list(self.rt.eval("logs").values()) if "attacks|auto|player=0" in line]
        self.assertEqual(1, len(human_logs), human_logs)
        self.rt.execute(
            "CombatManager.SimulateAttackVersus = function(a, d, ctype) return {A={dmg=100}, D={dmg=30}} end; "
            "Players[2].units[3].moves = 2"
        )
        self.order(0, K=2, P=2, I=3, S=53, B=4, J=1, N=1, T=8)
        self.turn_start(2, turn=8)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any("skipped=1" in line and "attacks|auto|player=2" in line for line in logs), logs)

    def test_refused_attack_batch_logs_why_it_did_not_run(self):
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=1, B=9, J=1, N=1, T=4)
        self.assertEqual(self.last()["reason"], "stale_turn:4")
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any(
            "CIV6AI|attacks|player=2|turn=4|executed=0|failed=1" in line
            and "reason=stale_turn:4" in line
            for line in logs
        ), logs)

    def test_second_batch_same_turn_merges_into_one_queue(self):
        # One queue per seat per turn: a second batch for the same turn merges, nothing is dropped.
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=1, B=1, J=1, N=1, T=6)
        self.order(0, K=2, P=2, I=4, S=2, B=2, J=1, N=1, T=6)
        reasons = [r["reason"] for r in (self.results() or [])]
        self.assertFalse(any(str(r).startswith("queue_replaced") for r in reasons), reasons)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_N')"), 2)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any("queue_merged|player=2|turn=6|orders=2" in line for line in logs), logs)

    def test_same_unit_order_in_second_batch_supersedes(self):
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=1, B=1, J=1, N=1, T=6)
        self.order(0, K=1, P=2, U=7, X=12, Y=11, S=2, B=2, J=1, N=1, T=6)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_N')"), 1)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_Q_2_1_X')"), 12)

    def test_replaced_queue_records_the_attack_it_dropped(self):
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=1, B=1, J=1, N=1, T=6)
        self.rt.globals().SetTurn(6)
        self.order(0, K=2, P=2, I=4, S=2, B=2, J=1, N=1, T=7)
        reasons = [r["reason"] for r in self.results()]
        self.assertIn("queue_replaced:6", reasons)
        logs = list(self.rt.eval("logs").values())
        self.assertTrue(any(
            "executed=0|failed=1" in line and "reason=queue_replaced" in line
            for line in logs
        ), logs)

    def test_builder_move_outside_borders_is_allowed(self):
        # Civ VI builders walk outside borders; only improving needs own tiles.
        self.rt.execute(
            "GameInfo.Units[2] = {BuildCharges=3}; "
            "table.insert(Players[2].units, MkUnit(2,40,3,4,2)); "
            "Map.GetPlot(5,6):SetOwner(-1)"
        )
        self.order(0, K=1, P=2, U=40, X=5, Y=6, S=30)
        self.assertNotEqual(self.last()["reason"], "outside_borders")

    def test_city_attack_and_strike_without_get_district_id(self):
        # Gameplay cities have no GetDistrictID. The centre comes from the city
        # plot, or from the city's district list. Neither call may throw.
        self.rt.execute(r"""
          DefenseTypes = {DISTRICT_OUTER=1, DISTRICT_GARRISON=2}
          local function mkDistrict(id, x, y)
            local d = {id=id, x=x, y=y, wdmg=0, gdmg=0}
            function d:GetID() return self.id end
            function d:GetX() return self.x end
            function d:GetY() return self.y end
            function d:GetComponentID() return self end
            function d:GetType() return 0 end
            function d:GetMaxDamage(t) if t == 1 then return 100 end return 200 end
            function d:GetDamage(t) if t == 1 then return self.wdmg end return self.gdmg end
            function d:ChangeDamage(t, n)
              if t == 1 then self.wdmg = self.wdmg + n else self.gdmg = self.gdmg + n end
            end
            return d
          end
          centerA = mkDistrict(42, 20, 20)
          centerB = mkDistrict(43, 30, 30)
          local function mkCity(id, owner, x, y, districts)
            local c = {id=id, owner=owner, x=x, y=y, districts=districts}
            function c:GetID() return self.id end
            function c:GetOwner() return self.owner end
            function c:GetX() return self.x end
            function c:GetY() return self.y end
            function c:GetDistricts()
              local me=self
              return {Members=function()
                local i=0
                return function() i=i+1; local d=me.districts[i]; if d then return i, d end end
              end}
            end
            return c
          end
          cityA = mkCity(7, 1, 20, 20, {})
          cityB = mkCity(8, 2, 30, 30, {centerB})
          local plotA = Map.GetPlot(20, 20)
          function plotA:GetDistrictID() return 42 end
          local p1, p2 = Players[1], Players[2]
          function p1:GetDistricts()
            return {FindID=function(_, id) if id == 42 then return centerA end end,
                    Members=function() return function() return nil end end}
          end
          function p1:GetCities()
            return {Members=function()
              local i=0; local cs={cityA}
              return function() i=i+1; if cs[i] then return i, cs[i] end end
            end}
          end
          function p2:GetCities()
            return {Members=function()
              local i=0; local cs={cityB}
              return function() i=i+1; if cs[i] then return i, cs[i] end end
            end}
          end
          Cities = {GetCityInPlot=function(x, y) if x == 20 and y == 20 then return cityA end end}
          Players[1].war = {[2]=true}
          Players[2].war = {[1]=true}
          table.insert(Players[2].units, MkUnit(2, 30, 20, 21, 0))
          table.insert(Players[1].units, MkUnit(1, 40, 31, 30, 0))
          CityCommandTypes = { RANGE_ATTACK = 9, PARAM_X = "x", PARAM_Y = "y" }
          cityStrikeCalls = {}
          CityManager = {
            CanStartCommand = function(city, cmd, params)
              return params.x == 31 and params.y == 30
            end,
            RequestCommand = function(city, cmd, params)
              cityStrikeCalls[#cityStrikeCalls + 1] = city:GetID()
            end,
          }
        """)
        self.assertIsNone(self.rt.eval("cityA.GetDistrictID"))
        self.assertIsNone(self.rt.eval("cityB.GetDistrictID"))
        self.assertEqual(self.rt.eval("Civ6Ai_Orders._CityCenterDistrict(cityA).id"), 42)
        self.assertEqual(self.rt.eval("Civ6Ai_Orders._CityCenterDistrict(cityB).id"), 43)
        self.order(0, K=7, P=2, U=30, X=20, Y=20, S=70, B=3, J=1, N=2, T=6)
        self.order(0, K=31, P=2, I=8, X=31, Y=30, S=71, B=3, J=2, N=2, T=6)
        self.turn_start(2, turn=6)
        by_seq = {r["seq"]: r for r in self.results()}
        self.assertTrue(by_seq[70]["ok"], by_seq[70]["reason"])
        self.assertIn("city_hp", str(by_seq[70]["reason"]))
        self.assertGreater(self.rt.eval("centerA.wdmg"), 0)
        self.assertTrue(by_seq[71]["ok"], by_seq[71]["reason"])
        self.assertEqual(by_seq[71]["reason"], "city_strike")
        self.assertEqual(self.rt.eval("Players[1].units[#Players[1].units].dmg"), 0)
        self.assertEqual(self.rt.eval("#cityStrikeCalls"), 1)
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertTrue(any("city_strike|city=8|x=31|y=30|defender=40" in s for s in logs), logs)
        self.assertFalse(any("turn_start_error" in s for s in logs))

    def test_city_strike_does_not_need_param_x_on_city_command_types(self):
        # Gameplay has CityManager but often no CityCommandTypes.PARAM_X.
        # That used to return city_strike_unavailable for every auto strike.
        self.rt.execute(r"""
          CityCommandTypes = { RANGE_ATTACK = 9 }
          UnitOperationTypes.PARAM_X = "x"
          UnitOperationTypes.PARAM_Y = "y"
          cityStrikeCalls = {}
          CityManager = {
            CanStartCommand = function(city, cmd, params)
              return type(params) == "table" and (params.x == 31 or params.X == 31)
            end,
            RequestCommand = function(city, cmd, params)
              cityStrikeCalls[#cityStrikeCalls + 1] = params.x or params.X
            end,
          }
          local city = {id=8, owner=2, x=30, y=30}
          function city:GetID() return self.id end
          function city:GetOwner() return self.owner end
          function city:GetX() return self.x end
          function city:GetY() return self.y end
          Players[2].GetCities = function()
            return {Members=function()
              local i=0
              return function() i=i+1; if i==1 then return i, city end end
            end}
          end
          Players[1].war = {[2]=true}
          Players[2].war = {[1]=true}
          table.insert(Players[1].units, MkUnit(1, 77, 31, 30, 0))
        """)
        self.assertTrue(self.rt.eval("Civ6Ai_Orders.CityStrikeAvailable()"))
        self.order(0, K=31, P=2, I=8, X=31, Y=30, S=80)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertEqual(self.last()["reason"], "city_strike")
        self.assertNotEqual(self.last()["reason"], "city_strike_unavailable")
        self.assertEqual(self.rt.eval("#cityStrikeCalls"), 1)

    def test_city_strike_stops_after_the_first_failure(self):
        # A dead unit is not a target. A district is. After one refusal the
        # next strike in the batch is not sent to the engine.
        self.rt.execute(r"""
          CityCommandTypes = { RANGE_ATTACK = 9, PARAM_X = "x", PARAM_Y = "y" }
          cityStrikeCalls = {}
          CityManager = {
            CanStartCommand = function() return true end,
            RequestCommand = function(city, cmd, params)
              cityStrikeCalls[#cityStrikeCalls + 1] = params.x
            end,
          }
          local city = {id=8, owner=2, x=30, y=30}
          function city:GetID() return self.id end
          function city:GetOwner() return self.owner end
          function city:GetX() return self.x end
          function city:GetY() return self.y end
          Players[2].GetCities = function()
            return {Members=function()
              local i=0
              return function() i=i+1; if i==1 then return i, city end end
            end}
          end
          Players[1].war = {[2]=true}
          Players[2].war = {[1]=true}
          local dead = MkUnit(1, 41, 32, 30, 0)
          dead.dmg = 100
          table.insert(Players[1].units, dead)
          table.insert(Players[1].units, MkUnit(1, 40, 31, 30, 0))
          local fort = {id=55, x=30, y=31}
          function fort:GetID() return self.id end
          function fort:GetX() return self.x end
          function fort:GetY() return self.y end
          Players[1].GetDistricts = function()
            return {Members=function()
              local i=0
              return function() i=i+1; if i==1 then return i, fort end end
            end}
          end
        """)
        self.order(0, K=31, P=2, I=8, X=32, Y=30, S=1, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual(self.last()["reason"], "no_enemy_on_plot")
        self.assertEqual(self.rt.eval("#cityStrikeCalls"), 0)
        self.order(0, K=31, P=2, I=8, X=30, Y=31, S=2, B=2, J=1, N=1, T=7)
        self.turn_start(2, turn=7)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertTrue(any("city_strike|city=8|x=30|y=31|defender=55" in s for s in logs), logs)
        self.rt.execute("CityManager.CanStartCommand = function() return false end; cityStrikeCalls = {}")
        self.order(0, K=31, P=2, I=8, X=31, Y=30, S=3, B=3, J=1, N=2, T=8)
        self.order(0, K=31, P=2, I=8, X=30, Y=31, S=4, B=3, J=2, N=2, T=8)
        self.turn_start(2, turn=8)
        by_seq = {r["seq"]: r for r in self.results()}
        self.assertEqual(by_seq[3]["reason"], "city_strike_refused")
        self.assertEqual(by_seq[4]["reason"], "city_strike_stopped")
        self.assertEqual(self.rt.eval("#cityStrikeCalls"), 0)

    def test_city_attack_survives_a_throwing_method_lookup(self):
        # Gameplay userdata throws "function expected instead of nil" from
        # __index. A missing GetDistrictID or GetComponentID must not abort
        # the turn; the forecast arguments are evaluated before pcall.
        self.rt.execute(r"""
          DefenseTypes = {DISTRICT_OUTER=1, DISTRICT_GARRISON=2}
          local district = {id=42, x=20, y=20, wdmg=0, gdmg=0}
          function district:GetID() return self.id end
          function district:GetX() return self.x end
          function district:GetY() return self.y end
          function district:GetType() return 0 end
          function district:GetMaxDamage(t) if t == 1 then return 100 end return 200 end
          function district:GetDamage(t) if t == 1 then return self.wdmg end return self.gdmg end
          function district:ChangeDamage(t, n)
            if t == 1 then self.wdmg = self.wdmg + n else self.gdmg = self.gdmg + n end
          end
          setmetatable(district, {__index = function(_, key)
            if key == "GetComponentID" or key == "GetDistrictID" then
              error("function expected instead of nil")
            end
          end})
          local city = {id=7, owner=1, x=20, y=20}
          function city:GetID() return self.id end
          function city:GetOwner() return self.owner end
          function city:GetX() return self.x end
          function city:GetY() return self.y end
          function city:GetDistricts()
            return {Members=function()
              local i=0
              return function()
                i=i+1
                if i == 1 then return i, district end
              end
            end}
          end
          setmetatable(city, {__index = function(_, key)
            if key == "GetDistrictID" then error("function expected instead of nil") end
          end})
          local plot = Map.GetPlot(20, 20)
          setmetatable(plot, {__index = function(self, key)
            if key == "GetDistrictID" then error("function expected instead of nil") end
            return rawget(self, key)
          end})
          centerThrow = district
          cityThrow = city
          local p1 = Players[1]
          function p1:GetCities()
            return {Members=function()
              local i=0
              return function() i=i+1; if i == 1 then return i, city end end
            end}
          end
          Cities = {GetCityInPlot=function(x, y) if x == 20 and y == 20 then return city end end}
          Players[1].war = {[2]=true}
          Players[2].war = {[1]=true}
          table.insert(Players[2].units, MkUnit(2, 30, 20, 21, 0))
        """)
        self.assertEqual(self.rt.eval("Civ6Ai_Orders._CityCenterDistrict(cityThrow).id"), 42)
        self.order(0, K=7, P=2, U=30, X=20, Y=20, S=80, B=4, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        row = {r["seq"]: r for r in self.results()}[80]
        self.assertFalse(row["ok"], row["reason"])
        self.assertIn("forecast_failed", str(row["reason"]))
        self.assertNotIn("function expected instead of nil", str(row["reason"]))
        self.assertEqual(self.rt.eval("centerThrow.wdmg"), 0)
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertFalse(any("turn_start_error" in s for s in logs))

    def test_one_throwing_order_still_runs_the_rest(self):
        self.rt.execute(r"""
          local orig = Civ6Ai_Orders._Execute
          function Civ6Ai_Orders._Execute(sender, o)
            if o.U == 7 then error("function expected instead of nil") end
            return orig(sender, o)
          end
        """)
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=5, B=9, J=1, N=2, T=6)
        self.order(0, K=1, P=2, U=8, X=11, Y=11, S=6, B=9, J=2, N=2, T=6)
        self.turn_start(2, turn=6)
        by_seq = {r["seq"]: r for r in self.results()}
        self.assertFalse(by_seq[5]["ok"])
        self.assertTrue(str(by_seq[5]["reason"]).startswith("order_error:"))
        self.assertIn("function expected instead of nil", by_seq[5]["reason"])
        self.assertTrue(by_seq[6]["ok"], by_seq[6]["reason"])
        self.assertEqual(self.rt.eval("Players[2].units[2].y"), 11)
        self.assertEqual(self.rt.eval("ExposedMembers.Civ6Ai.TurnStartComplete[2]"), 6)
        logs = [str(s) for s in _vals(self.rt.eval("logs"))]
        self.assertFalse(any("turn_start_error" in s for s in logs))

    def test_turn_start_error_is_kept_by_turn(self):
        self.rt.globals().Civ6Ai_Orders._NoteTurnStartError(2, "function expected instead of nil")
        self.assertEqual(
            self.rt.eval("ExposedMembers.Civ6Ai.TurnStartErrors[2][5]"),
            "function expected instead of nil",
        )

    def test_zero_melee_forecast_retries_without_combat_type(self):
        self.rt.execute(
            "Players[2].war = {[1]=true}; table.insert(Players[1].units, MkUnit(1,3,10,11,0));"
            "CombatManager.SimulateAttackVersus=function(a, d, ctype)"
            " if ctype == nil then return {A={dmg=4}, D={dmg=12}} end"
            " return {A={dmg=0}, D={dmg=0}} end"
        )
        forecast_a, forecast_d = self.rt.eval(
            "function() return Civ6Ai_Orders._Forecast(Players[2].units[1], Players[1].units[2], CombatTypes.MELEE) end"
        )()
        self.assertEqual(forecast_d, 12)
        self.assertEqual(forecast_a, 4)
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=15)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIn("def_dmg=0>12", self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 12)

    def test_melee_kill_advances_into_plot(self):
        self.rt.execute("Players[2].war = {[1]=true}; local e = MkUnit(1,3,10,11,0); e.dmg = 80;"
                        " table.insert(Players[1].units, e)")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=13)
        self.assertIn("killed=true", self.last()["reason"])
        self.assertEqual(self.rt.eval("#Players[1].units"), 1)
        self.assertEqual(self.rt.eval("Players[2].units[1].y"), 11)

    def test_kill_runs_when_engine_already_reports_dead(self):
        # IsDead() is true at max damage; the kill must still run (corpse bug).
        self.rt.execute("Players[2].war = {[1]=true}; local e = MkUnit(1,3,10,11,0); e.dmg = 80;"
                        " function e:IsDead() return self.dmg >= 100 end;"
                        " table.insert(Players[1].units, e)")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=13)
        self.assertIn("killed=true", self.last()["reason"])
        self.assertEqual(self.rt.eval("#Players[1].units"), 1)

    def test_zero_hp_leftover_is_removed_not_targeted(self):
        self.rt.execute("Players[2].war = {[1]=true}; local e = MkUnit(1,3,10,11,0); e.dmg = 100;"
                        " table.insert(Players[1].units, e)")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=13)
        self.assertEqual(self.rt.eval("#Players[1].units"), 1)
        self.assertNotIn("def_dmg=100>100", self.last()["reason"])

    def test_far_move_uses_path_route(self):
        self.rt.execute(
            "ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = function(p,u,x,y) "
            "path_called = {p,u,x,y}; "
            "for _, unit in ipairs(Players[p].units) do if unit.id == u then unit.x = x; unit.y = y end end; "
            "return true, 'path' end"
        )
        self.order(0, K=1, P=2, U=7, X=13, Y=13, S=20)
        self.assertEqual(self.last()["reason"], "path")
        self.assertEqual(self.rt.eval("path_called[3]"), 13)

    def test_test_ops_need_test_mode(self):
        self.order(0, K=56, P=2, U=7, S=14)
        self.assertEqual(self.last()["reason"], "test_mode_off")
        self.order(0, K=49, V=1, S=15)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_MPTEST')"), 1)

    def test_introspect_keeps_note_out_of_result(self):
        self.order(0, K=49, V=1, S=16)
        self.order(0, K=50, P=2, S=17, Note="hello")
        self.assertEqual(self.last()["reason"], "logged")
        self.assertTrue(any("note=hello" in l for l in _vals(self.rt.eval("logs"))))

    def test_api_survey_logs_and_survives_missing_objects(self):
        self.order(0, K=49, V=1, S=18)
        self.order(0, K=61, P=2, S=19)
        self.assertIn("objects=", self.last()["reason"])
        logs = _vals(self.rt.eval("logs"))
        self.assertTrue(any("survey|City=" in l for l in logs))

    def test_production_steer_apply_read_and_undo(self):
        self.rt.execute(r"""
          local function mkCity(owner, id, cur)
            local c = {owner=owner, id=id, cur=cur, placed={}, favored={}}
            function c:GetID() return self.id end
            function c:GetX() return 1 end
            function c:GetY() return 1 end
            local me = c
            local bq = {}
            function bq:CurrentlyBuilding() return me.cur end
            function bq:CanProduce(h) return h == 777 end
            function bq:HasDistrictBeenPlaced(i) return me.placed[i] == true end
            function bq:CreateIncompleteDistrict(i, plotIndex, pct) me.placed[i] = true; me.cur = "DISTRICT_CAMPUS" end
            function c:GetBuildQueue() return bq end
            function c:GetCitizens() return {SetFavoredYield=function(_, y, on) me.favored[y] = on end,
                                             IsYieldFavored=function(_, y) return me.favored[y] == true end} end
            function c:GetDistricts() return {HasDistrict=function() return false end} end
            local plot = {x=2, y=3}
            function plot:GetIndex() return 42 end
            function plot:GetX() return 2 end
            function plot:GetY() return 3 end
            function plot:CanHaveDistrict() return true end
            function c:GetOwnedPlots() return {plot} end
            return c
          end
          local function cities(list)
            return {Members=function() local i=0; return function() i=i+1; if list[i] then return i, list[i] end end end,
                    FindID=function(_, id) for _,c in ipairs(list) do if c.id==id then return c end end end}
          end
          local c2, c3 = mkCity(2, 11, "UNIT_WARRIOR"), mkCity(3, 21, "BUILDING_MONUMENT")
          local p2 = Players[2]
          local p3 = setmetatable({}, {__index=p2})
          Players[3] = p3
          function p2:GetCities() return cities({c2}) end
          function p3:GetCities() return cities({c3}) end
          local allow = true
          function p2:GetAi_Military() return {AllowUnitConstruction=function(_, on) allow = on end,
                                                       CanConstructUnits=function() return allow end} end
          local districts = {{Index=0, Hash=1, DistrictType="DISTRICT_CITY_CENTER"}, {Index=3, Hash=777, DistrictType="DISTRICT_CAMPUS", PrereqTech="TECH_WRITING"}}
          GameInfo.Districts = function() local i=0; return function() i=i+1; return districts[i] end end
          GameInfo.Yields = {YIELD_PRODUCTION={Index=1}}
          SteerCity3 = c3
          local writing = false
          GameInfo.Technologies = {TECH_WRITING={Index=9}}
          function p3:GetTechs() return {SetTech=function(_, i, on) writing = (i == 9 and on) end,
                                         HasTech=function(_, i) return i == 9 and writing end} end
        """)
        self.order(0, K=49, V=1, S=39)
        self.order(0, K=62, P=2, U=3, I=3, S=38)
        self.assertEqual(self.last()["reason"],
                         "writing=true;district=DISTRICT_CAMPUS@2,3(CanHaveDistrict):tries=true:placed=true:now=DISTRICT_CAMPUS")
        self.order(0, K=49, V=1, S=40)
        self.order(0, K=62, P=2, U=3, X=2, I=0, S=41)
        r = self.last()["reason"]
        self.assertTrue(self.last()["ok"])
        self.assertIn("allow_units_off=true:can=true>false", r)
        self.assertIn("p_cities=11=UNIT_WARRIOR(unit)", r)
        self.assertIn("focus_production=true:favored=true", r)
        self.assertIn("district=already", r)
        self.order(0, K=62, P=2, U=3, I=1, S=42)
        r = self.last()["reason"]
        self.assertIn("can_units=false", r)
        self.assertIn("focus=true", r)
        self.assertIn("district=DISTRICT_CAMPUS:placed=true", r)
        self.assertIn("control_cities=11=UNIT_WARRIOR(unit)", r)
        self.order(0, K=62, P=2, U=3, I=2, S=43)
        self.assertIn("allow_units_on=true:can=true", self.last()["reason"])

    def test_force_build_setup_conditions_read_and_off(self):
        self.rt.execute(r"""
          local techs = {}
          GameInfo.Technologies = {TECH_ARCHERY={Index=1}, TECH_POTTERY={Index=2}, TECH_WRITING={Index=3}}
          GameInfo.Units.UNIT_ARCHER = {Index=1}
          GameInfo.Buildings = {BUILDING_GRANARY={Index=5}}
          GameInfo.Districts = {DISTRICT_CAMPUS={Index=3}}
          for _, id in ipairs({3, 4, 5}) do
            Players[id] = setmetatable({units={}}, {__index=Players[2]})
          end
          for id = 2, 5 do
            local p = Players[id]
            techs[id] = {}
            function p:GetTechs() return {SetTech=function(_, i, on) techs[id][i] = on end,
                                          HasTech=function(_, i) return techs[id][i] == true end} end
          end
        """)
        self.order(0, K=49, V=1, S=50)
        self.order(0, K=63, P=2, U=3, X=4, Y=5, I=3, S=51)
        r = self.last()["reason"]
        self.assertTrue(self.last()["ok"])
        self.assertIn("seat5[TECH_ARCHERY=true,TECH_POTTERY=true,TECH_WRITING=true]", r)
        self.assertIn("seat2[force=1],UNIT_ARCHER:have=1", r)  # the fake seat 2 owns one ranged unit (type 1)
        self.assertIn("seat5[force=0]", r)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_FORCE_3')"), 2)
        fire = lambda fn, p: self.rt.eval("GameEvents.%s.fns[1](%d, 0)" % (fn, p))
        self.assertTrue(fire("Civ6AiForceArcher", 2))
        self.assertFalse(fire("Civ6AiForceGranary", 2))
        self.assertTrue(fire("Civ6AiForceGranary", 3))
        self.assertTrue(fire("Civ6AiForceCampus", 4))
        self.assertFalse(fire("Civ6AiForceCampus", 5))
        self.assertFalse(fire("Civ6AiForceArcher", 5))
        logs = _vals(self.rt.eval("logs"))
        self.assertTrue(any("strategy_call|turn=5|player=2|fn=Civ6AiForceArcher|active=true" in l for l in logs))
        self.assertFalse(any("player=5" in l and "strategy_call" in l for l in logs))
        self.order(0, K=63, P=2, U=3, X=4, Y=5, I=2, S=52)
        self.assertIn("force_off", self.last()["reason"])
        self.assertFalse(fire("Civ6AiForceArcher", 2))

    def test_force_build_needs_a_seat(self):
        self.order(0, K=49, V=1, S=53)
        self.order(0, K=63, I=1, S=54)
        self.assertEqual(self.last()["reason"], "no_seat")

    def test_checksum_report_match_and_mismatch(self):
        rt = self.rt
        rt.globals().Civ6Ai_Orders.OnGameTurnStarted(5)
        mine = dict(rt.eval("ExposedMembers.Civ6Ai.Checksums[5]").items())
        self.order(1, K=30, T=5, H=mine["sum"], R=mine["orders"], Q=mine["count"], S=18)
        self.assertEqual(rt.eval("ExposedMembers.Civ6Ai.SyncReports[1].verdict"), "match")
        self.order(1, K=30, T=5, H=mine["sum"] + 1, R=mine["orders"], Q=mine["count"], S=19)
        self.assertTrue(rt.eval("ExposedMembers.Civ6Ai.SyncReports[1].verdict").startswith("MISMATCH:sum=false"))

    def test_finish_seat_zeroes_remaining_moves(self):
        self.assertGreater(self.rt.eval("Players[2].units[1].moves"), 0)
        self.order(0, K=23, P=2, S=21, T=5)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(self.last()["reason"].startswith("finish_seat="))
        self.assertEqual(self.rt.eval("Players[2].units[1].moves"), 0)
        self.assertEqual(self.rt.eval("Players[2].units[2].moves"), 0)

    def test_checksum_tracks_units_and_damage(self):
        before = self.rt.eval("Civ6Ai_Orders.Checksum()")
        self.rt.execute("Players[2].units[1].dmg = 10")
        self.assertNotEqual(before, self.rt.eval("Civ6Ai_Orders.Checksum()"))

    def test_handler_is_deterministic_across_pcs(self):
        # Two PCs fed the same orders end with the same order hash.
        def run():
            rt = lupa.LuaRuntime(unpack_returned_tuples=True)
            rt.execute(FAKE_ENV)
            rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())
            for p in ({"K": 2, "P": 2, "I": 3, "S": 1, "T": 5},
                      {"K": 1, "P": 2, "U": 7, "X": 11, "Y": 10, "S": 2, "B": 1, "J": 1, "N": 2, "T": 6},
                      {"K": 1, "P": 2, "U": 8, "X": 11, "Y": 11, "S": 3, "B": 1, "J": 2, "N": 2, "T": 6}):
                rt.globals().Civ6Ai_Orders.OnOrder(0, rt.table_from(p))
            rt.globals().SetTurn(6)
            rt.eval("GameEvents.PlayerTurnStartComplete.fns[1]")(2)
            return rt.eval("ExposedMembers.Civ6Ai.OrderHash"), rt.eval("Civ6Ai_Orders.Checksum()")
        self.assertEqual(run(), run())

    def test_gov_attack_unit_uses_the_ai_resolver(self):
        self.rt.execute("Players[0].war = {[1] = true}")
        ok, reason = self.rt.eval("function() return Civ6Ai_Orders.Gov.AttackUnit(0, 1, 6, 6) end")()
        self.assertTrue(ok, reason)
        self.assertIn("melee", str(reason))
        self.assertGreater(int(self.rt.eval("Players[1].units[1].dmg")), 0)
        self.assertEqual(self.rt.eval("#attackOps"), 0)


CHANNEL_ENV = r"""
logs = {}
sent = {}
Civ6Ai_Util = {Log=function(s) table.insert(logs, s) end, ScheduleTick=function(fn) table.insert(ticks, fn) end}
ticks = {}
recorded = {}
Civ6Ai_Apply = {
  _RecordResult=function(pid, cmd, ok, reason) table.insert(recorded, {pid=pid, kind=cmd.kind, ok=ok, reason=reason}) end,
  _ParseUnitNumericId=function(id) return tonumber(tostring(id):match("(%d+)$")) end,
  _ResolveTargetCoords=function(a) return a.target_x or a.x, a.target_y or a.y end,
}
ExposedMembers = {Civ6Ai = {}}
GameConfiguration = {IsNetworkMultiplayer=function() return true end}
PlayerOperations = {EXECUTE_SCRIPT = 99}
UI = {RequestPlayerOperation=function(me, op, params) table.insert(sent, params) end}
now = 0
Automation = {GetTime=function() return now end}
TURN = 5
Game = {GetLocalPlayer=function() return 0 end, GetCurrentGameTurn=function() return TURN end,
        GetProperty=function(_, k) return nil end}
GameInfo = {Technologies={TECH_MINING={Index=3}}, Civics={},
            Units={UNIT_WARRIOR={Index=0,UnitType="UNIT_WARRIOR"}},
            Buildings={BUILDING_MONUMENT={Index=1,BuildingType="BUILDING_MONUMENT"}},
            Improvements={IMPROVEMENT_FARM={Index=0,ImprovementType="IMPROVEMENT_FARM"}}}
Players = {[2]={IsHuman=function() return false end}}
"""


@unittest.skipIf(lupa is None, "lupa not installed")
class OrderChannelTests(unittest.TestCase):
    def setUp(self):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.rt.execute(CHANNEL_ENV)
        self.rt.execute((MOD / "InGame" / "Civ6Ai_OrderChannel.lua").read_text())

    def decision(self, cmds):
        lua = "return {commands={" + ",".join(cmds) + "}}"
        return self.rt.execute(lua)

    def test_decision_becomes_one_batch_and_results_flow_back(self):
        rt = self.rt
        d = self.decision([
            '{kind="move_unit", arguments={unit_id="UNIT_2_7", x=10, y=11}}',
            '{kind="set_research_tech", arguments={tech_id="TECH_MINING"}}',
            '{kind="queue_production", arguments={city_id="C1"}}',
        ])
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6), 2)
        sent = [dict(p.items()) for p in _vals(rt.eval("sent"))]
        self.assertEqual([p["K"] for p in sent], [1, 2])
        self.assertEqual({p["OnStart"] for p in sent}, {"Civ6AiOrder"})
        self.assertEqual({p["T"] for p in sent}, {6})
        self.assertEqual([(p["J"], p["N"]) for p in sent], [(1, 2), (2, 2)])
        self.assertEqual(sent[0]["U"], 7)
        self.assertEqual(sent[1]["I"], 3)
        rec = [dict(r.items()) for r in _vals(rt.eval("recorded"))]
        self.assertEqual(rec[0]["reason"], "production_requires_local_player")
        # Gameplay reports both results; the channel records them.
        rt.execute("ExposedMembers.Civ6Ai.OrderResults = {"
                   "{sender=0, seq=%d, ok=true, reason='moved'}, {sender=0, seq=%d, ok=false, reason='x'}}"
                   % (sent[0]["S"], sent[1]["S"]))
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 0)
        rec = [dict(r.items()) for r in _vals(rt.eval("recorded"))]
        self.assertEqual([(r["kind"], r["ok"]) for r in rec[1:]], [("move_unit", True), ("set_research_tech", False)])

    def test_result_missing_once_the_turn_it_was_for_is_over(self):
        rt = self.rt
        d = self.decision(['{kind="unit_skip", arguments={unit_id="UNIT_2_8"}}'])
        rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6)
        rt.execute("TURN = 6")
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 1)
        self.assertIsNone(rt.eval("recorded[1]"))
        # The turn the order was for can end on the same tick the result is written.
        rt.execute("TURN = 7")
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 1)
        self.assertIsNone(rt.eval("recorded[1]"))
        rt.execute("TURN = 8")
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 0)
        self.assertEqual(rt.eval("recorded[1].reason"), "no_result_from_gameplay")

    def test_missing_result_includes_the_turn_start_error(self):
        rt = self.rt
        d = self.decision(['{kind="unit_skip", arguments={unit_id="UNIT_2_8"}}'])
        rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6)
        rt.execute("ExposedMembers.Civ6Ai.TurnStartErrors = {[2]={[6]='function expected instead of nil'}}")
        rt.execute("TURN = 8")
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 0)
        self.assertEqual(
            rt.eval("recorded[1].reason"),
            "no_result_from_gameplay:function expected instead of nil",
        )

    def test_report_uses_local_checksum(self):
        rt = self.rt
        rt.execute("ExposedMembers.Civ6Ai.Checksums = {[5]={sum=11, orders=22, count=3}}")
        self.assertTrue(rt.globals().Civ6Ai_OrderChannel.SendReport(5))
        p = dict(rt.eval("sent[1]").items())
        self.assertEqual((p["K"], p["T"], p["H"], p["R"], p["Q"]), (30, 5, 11, 22, 3))


PATH_ENV = r"""
Civ6Ai_GameCore = {}
unit = {x=0, y=0, moves=2}
function unit:GetX() return self.x end
function unit:GetY() return self.y end
function unit:GetMovesRemaining() return self.moves end
function unit:GetID() return 7 end
function unit:GetMaxMoves() return 3 end
function unit:GetType() return 1 end
GameInfo = { Units = { [1] = { Domain = "DOMAIN_LAND" } } }
function Civ6Ai_GameCore.StepCost() return 1 end
function Civ6Ai_GameCore._ChargeStep() end
function Civ6Ai_GameCore._FindUnit(p, id) return nil, unit, "" end
function Civ6Ai_GameCore._Call(o, n) return o[n](o) end
restored = 0
function Civ6Ai_GameCore._RestoreMoves() restored = restored + 1 end
-- a step costs 1 move; a step is refused when no moves are left
function Civ6Ai_GameCore.CanMoveUnitToForPlayer(p, id, x, y)
  if unit.moves <= 0 then return false, "no_moves_left" end
  return true, ""
end
Map = {}
function Map.GetPlot(x, y) return {GetIndex=function() return y * 100 + x end} end
function Map.GetPlotByIndex(i) return {GetX=function() return i % 100 end, GetY=function() return math.floor(i / 100) end} end
UnitManager = {
  GetMoveToPath=function(u, idx) return {0, 1, 2, 3} end,
  MoveUnit=function(u, x, y) u.x = x; u.y = y; u.moves = u.moves - 1 end,
}
"""


@unittest.skipIf(lupa is None, "lupa not installed")
class PathMoveTests(unittest.TestCase):
    def test_sender_and_gameplay_kind_tables_match(self):
        import re
        def kinds(path, table):
            src = (MOD / path).read_text()
            body = src[src.index(table + " = {"):]
            body = body[:body.index("}")]
            return dict(re.findall(r"([A-Z_]+)\s*=\s*(\d+)", body))
        self.assertEqual(kinds("InGame/Civ6Ai_OrderChannel.lua", "Civ6Ai_OrderChannel.K"),
                         kinds("Gameplay/Civ6Ai_Orders.lua", "Civ6Ai_Orders.K"))

    def run_path(self, moves):
        src = (MOD / "Gameplay" / "Civ6Ai_GameCore.lua").read_text()

        def fn(name):
            start = src.index("function Civ6Ai_GameCore." + name + "(")
            return src[start:src.index("\nend\n", start) + 5]
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(PATH_ENV + "\n" + fn("_FirstStepCost") + fn("MoveUnitAlongPathForPlayer"))
        rt.execute("unit.moves = %d" % moves)
        return rt, rt.eval("Civ6Ai_GameCore.MoveUnitAlongPathForPlayer(1, 7, 3, 0)")

    def test_walks_whole_path_when_moves_allow(self):
        rt, (ok, reason) = self.run_path(3)
        self.assertTrue(ok)
        self.assertEqual(reason, "path:0,0>3,0:steps=3:len=4:stop=arrived")

    def test_stops_partway_when_moves_run_out(self):
        rt, (ok, reason) = self.run_path(2)
        self.assertTrue(ok)
        self.assertEqual(reason, "partial_path:0,0>2,0:steps=2:len=4:stop=no_moves_left")
        self.assertEqual(rt.eval("unit.x"), 2)

    def test_mountain_destination_is_impassable_not_no_path(self):
        rt, _ = self.run_path(3)
        rt.execute(
            """
            function Map.GetPlot(x, y)
              return {
                GetIndex = function() return 1 end,
                IsMountain = function() return true end,
                IsImpassable = function() return false end,
              }
            end
            path_calls = 0
            function UnitManager.GetMoveToPath()
              path_calls = path_calls + 1
              return {}
            end
            """
        )
        ok, reason = rt.eval("Civ6Ai_GameCore.MoveUnitAlongPathForPlayer(1, 7, 3, 0)")
        self.assertFalse(ok)
        self.assertEqual("impassable", reason)
        self.assertEqual(0, rt.eval("path_calls"))


class MpTestModuleTests(unittest.TestCase):
    @unittest.skipIf(lupa is None, "lupa not installed")
    def test_mp_test_script_parses(self):
        rt = lupa.LuaRuntime()
        rt.execute("return function() " + (MOD / "InGame" / "Civ6Ai_MpTest.lua").read_text() + " end")

    def test_report_summarizes_sync_and_checks(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mp_test_report", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "mp_test_report.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log = "\n".join([
            "[1] CIV6AI|orders|result|turn=5|from=0|seq=1|kind=57|player=2|unit=7|ok=true|reason=far:1,1>3,1|hash=9",
            "[2] CIV6AI|orders|result|turn=5|from=0|seq=2|kind=40|player=nil|unit=nil|ok=false|reason=stale_turn:4|hash=9",
            "[3] CIV6AI|orders|sync|turn=5|from=1|their_sum=3|my_sum=3|verdict=match",
            "[4] CIV6AI|orders|sync|turn=6|from=1|their_sum=3|my_sum=4|verdict=MISMATCH:sum=false:orders=true",
        ])
        text = mod.summarize(log)
        self.assertIn("OUT OF SYNC", text)
        self.assertIn("turn 6", text)
        self.assertIn("multi-tile move: 1/1 worked", text)
        self.assertIn("stale orders refused: 1", text)


@unittest.skipIf(lupa is None, "lupa not installed")
class PriorityOrderTests(unittest.TestCase):
    def setUp(self):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.rt.execute(FAKE_ENV)
        self.rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())
        self.O = self.rt.globals().Civ6Ai_Orders

    def order(self, sender, **params):
        params.setdefault("T", 5)
        self.O.OnOrder(sender, self.rt.table_from(params))
        return [dict(r.items()) for r in _vals(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))][-1]

    def level(self, owner, cid):
        return self.O.PriorityLevel(owner, cid)

    def cond(self, cid, level, owner):
        fns = _vals(self.rt.eval("GameEvents['Civ6AiPrio_%d_%d'].fns" % (cid, level)))
        self.assertEqual(len(fns), 1)
        return fns[0](owner, 0)

    def test_every_category_and_level_registered(self):
        ids = _vals(self.O.PRIORITY_IDS)
        self.assertEqual(len(ids), 25)
        for cat in ids:
            for level in (1, 2, 3):
                self.assertEqual(len(_vals(self.rt.eval("GameEvents['Civ6AiPrio_%d_%d'].fns" % (cat.id, level)))), 1)

    def test_settlers_only_is_accepted(self):
        r = self.order(0, K=9, P=2, I=25, X=3, S=1)
        self.assertTrue(r["ok"], r["reason"])
        self.assertEqual(self.level(2, 25), 3)

    def test_set_turns_on_exactly_that_level(self):
        r = self.order(0, K=9, P=2, I=8, X=3, S=1)
        self.assertTrue(r["ok"], r["reason"])
        self.assertEqual(self.level(2, 8), 3)
        self.assertTrue(self.cond(8, 3, 2))
        self.assertFalse(self.cond(8, 2, 2))
        self.assertFalse(self.cond(8, 3, 1))
        self.assertTrue(any("prio_call" in str(s) and "science_victory" in str(s) for s in _vals(self.rt.eval("logs"))))

    def test_one_posture_replaces_another(self):
        self.order(0, K=9, P=2, I=2, X=1, S=1)
        r = self.order(0, K=9, P=2, I=3, X=3, S=2)
        self.assertTrue(r["ok"])
        self.assertEqual(self.level(2, 2), 0)
        self.assertEqual(self.level(2, 3), 3)
        self.assertIn("now=total_war:3", r["reason"])

    def test_focus_limit_and_releveling(self):
        for s, (cid, lv) in enumerate([(8, 3), (17, 2), (14, 1)], 1):
            self.assertTrue(self.order(0, K=9, P=2, I=cid, X=lv, S=s)["ok"])
        r = self.order(0, K=9, P=2, I=15, X=1, S=9)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "too_many_focus")
        self.assertTrue(self.order(0, K=9, P=2, I=14, X=3, S=10)["ok"])  # re-level an active focus
        self.assertTrue(self.order(0, K=9, P=2, I=2, X=2, S=11)["ok"])  # posture is not a focus
        self.assertEqual(self.level(2, 14), 3)

    def test_clear_all(self):
        self.order(0, K=9, P=2, I=8, X=3, S=1)
        self.order(0, K=9, P=2, I=3, X=2, S=2)
        r = self.order(0, K=9, P=2, I=0, X=0, S=3)
        self.assertTrue(r["ok"])
        self.assertEqual(len(_vals(self.O.PriorityLevels(2))), 0)

    def test_rejects_bad_input_and_foreign_sender(self):
        self.assertEqual(self.order(0, K=9, P=2, I=99, X=1, S=1)["reason"], "bad_priority")
        self.assertEqual(self.order(0, K=9, P=2, I=8, X=4, S=2)["reason"], "bad_level")
        self.order(0, K=9, P=2, I=8, X=1, S=3)  # sender 0 becomes controller
        self.assertEqual(self.order(1, K=9, P=2, I=8, X=1, S=4)["reason"], "not_controller")
        self.assertEqual(self.order(1, K=9, P=0, I=8, X=1, S=5)["reason"], "not_owner")
        self.assertTrue(self.order(1, K=9, P=1, I=8, X=1, S=6)["ok"])  # a human sets their own

    def test_order_changes_checksum_state_on_every_pc(self):
        before = self.rt.eval("ExposedMembers.Civ6Ai.OrderHash")
        self.order(0, K=9, P=2, I=5, X=3, S=1)
        self.assertNotEqual(self.rt.eval("ExposedMembers.Civ6Ai.OrderHash"), before)


@unittest.skipIf(lupa is None, "lupa not installed")
class WpAApplyCoreTests(unittest.TestCase):
    def setUp(self):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.rt.execute(FAKE_ENV)
        self.rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())

    def order(self, sender, **params):
        params.setdefault("T", 5)
        self.rt.globals().Civ6Ai_Orders.OnOrder(sender, self.rt.table_from(params))

    def results(self):
        return [dict(r.items()) for r in _vals(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))]

    def last(self):
        return self.results()[-1]

    def turn_start(self, owner, turn=None):
        if turn is not None:
            self.rt.globals().SetTurn(turn)
        self.rt.eval("GameEvents.PlayerTurnStartComplete.fns[1]")(owner)
    def test_city_num_sends_full_id(self):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(CHANNEL_ENV)
        rt.execute((MOD / "InGame" / "Civ6Ai_OrderChannel.lua").read_text())
        self.assertEqual(rt.eval('Civ6Ai_OrderChannel._CityNum("CITY_65536")'), 65536)
        self.assertEqual(rt.eval('Civ6Ai_OrderChannel._CityNum("CITY_3")'), 3)

    def test_self_target_move_holds(self):
        self.order(0, K=1, P=2, U=7, X=10, Y=10, S=90)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertTrue(self.last()["reason"].startswith("self_target_hold"))
        self.assertEqual(self.last()["decision_turn"], 5)

    def test_religion_self_target_does_not_pass_plot_as_belief(self):
        self.rt.execute(
            "RELIG_EXTRA = nil; Civ6Ai_Orders.Gov.FoundReligion = function(owner, rel, unit, ...)"
            " RELIG_EXTRA = {...}; return true, 'founded' end"
        )
        self.order(0, K=1, P=2, U=7, X=10, Y=10, A=3, I=7, V=8, W=9, S=102)
        self.assertEqual(int(self.rt.eval("RELIG_EXTRA[1]")), 8)
        self.assertEqual(int(self.rt.eval("RELIG_EXTRA[2]")), 9)
        self.assertIsNone(self.rt.eval("RELIG_EXTRA[3]"))
        self.assertTrue(self.last()["ok"], self.last())

    def test_stale_unit_id(self):
        self.order(0, K=1, P=2, U=999, X=10, Y=11, S=91)
        self.assertEqual(self.last()["reason"], "stale_unit_id")
        self.assertFalse(self.last()["ok"])

    def test_research_fallback_when_primary_known(self):
        self.rt.execute("Players[2].knownTech = {[3]=true}")
        self.order(0, K=2, P=2, I=3, I2=4, I3=5, S=92)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertTrue(self.last()["reason"].startswith("ok_superseded:3>4"))
        self.assertEqual(self.rt.eval("Players[2].tech"), 4)

    def test_research_all_known_is_noop_success(self):
        self.rt.execute("Players[2].knownTech = {[3]=true, [4]=true, [5]=true}")
        self.order(0, K=2, P=2, I=3, I2=4, I3=5, S=93)
        self.assertEqual(self.last()["reason"], "tech_already_known")
        self.assertTrue(self.last()["ok"])

    def test_move_retargets_occupied_neighbour(self):
        # Unit 8 sits on 11,10 and is not ordered, so retries cannot free the tile.
        self.order(0, K=1, P=2, U=7, X=11, Y=10, S=94, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertIn("retargeted", self.last()["reason"])
        self.assertNotEqual((self.rt.eval("Players[2].units[1].x"), self.rt.eval("Players[2].units[1].y")), (10, 10))
        self.assertNotEqual((self.rt.eval("Players[2].units[1].x"), self.rt.eval("Players[2].units[1].y")), (11, 10))

    def test_persistent_goal_continues_next_turn(self):
        self.rt.execute(
            "path_n = 0; ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = function(p,u,x,y) "
            "path_n = path_n + 1; local unit; for _,z in ipairs(Players[p].units) do if z.id==u then unit=z end end; "
            "if unit then unit.x = unit.x + 1 end; return true, 'partial_path' end"
        )
        self.order(0, K=1, P=2, U=7, X=14, Y=10, G=1, S=95, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("GetProp('CIV6AI_GOAL_2_7_X')"), 14)
        self.assertEqual(self.rt.eval("path_n"), 1)
        self.turn_start(2, turn=7)
        self.assertEqual(self.rt.eval("path_n"), 2)
        self.assertEqual(self.rt.eval("Players[2].units[1].x"), 12)

    def test_found_on_arrival_at_target(self):
        self.rt.execute("GameInfo.Units[0].FoundCity = true")
        self.order(0, K=1, P=2, U=7, X=10, Y=11, G=1, A=1, S=96)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertIn("found_on_arrival", self.last()["reason"])
        self.assertEqual(self.rt.eval("Players[2].founded.y"), 11)

    def test_self_target_settler_founds_when_legal(self):
        self.rt.execute("GameInfo.Units[0].FoundCity = true")
        self.order(0, K=1, P=2, U=7, X=10, Y=10, S=97)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertEqual(self.rt.eval("Players[2].founded.x"), 10)

    def test_channel_packs_goal_fallbacks_and_new_kinds(self):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(CHANNEL_ENV)
        rt.execute((MOD / "InGame" / "Civ6Ai_OrderChannel.lua").read_text())
        d = rt.execute(
            'return {commands={'
            '{kind="move_unit", arguments={unit_id="UNIT_2_7", x=30, y=12, goal=1, intent="found"}},'
            '{kind="set_research_tech", arguments={tech_id="TECH_MINING", tech_id_2="TECH_MINING"}},'
            '{kind="explore", arguments={unit_id="UNIT_2_8"}},'
            '{kind="trade_route", arguments={unit_id="UNIT_2_9", city_id="CITY_131072"}},'
            '{kind="activate_great_person", arguments={unit_id="UNIT_2_10"}},'
            '}}'
        )
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6, 5), 5)
        sent = [dict(p.items()) for p in _vals(rt.eval("sent"))]
        self.assertEqual([p["K"] for p in sent], [1, 2, 25, 24, 26])
        self.assertEqual(sent[0]["G"], 1)
        self.assertEqual(sent[0]["A"], 1)
        self.assertEqual(sent[1]["I2"], 3)
        self.assertEqual(sent[3]["I"], 131072)
        self.assertEqual({p["D"] for p in sent}, {5})

    def test_send_drops_string_fields_from_execute_script(self):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(CHANNEL_ENV)
        rt.execute((MOD / "InGame" / "Civ6Ai_OrderChannel.lua").read_text())
        seq = rt.globals().Civ6Ai_OrderChannel.Send(1, rt.table_from({
            "P": 2, "U": 7, "X": 10.9, "Y": 11, "note": "plot", "G": True,
        }), 6)
        self.assertIsNotNone(seq)
        sent = dict(_vals(rt.eval("sent"))[0].items())
        self.assertEqual(sent["X"], 10)
        self.assertEqual(sent["G"], 1)
        self.assertNotIn("note", sent)

    def test_purchase_uses_full_city_id(self):
        self.rt.execute(r"""
          local c = {id=131072, x=4, y=5, buildings={}}
          function c:GetID() return self.id end
          function c:GetX() return self.x end
          function c:GetY() return self.y end
          function c:GetGold()
            return {GetPurchaseCost=function() return 40 end, GetPlotPurchaseCost=function() return 25 end}
          end
          function c:GetBuildings()
            local me=self
            return {HasBuilding=function(_, i) return me.buildings[i]==true end}
          end
          function c:GetBuildQueue()
            local me=self
            return {CreateIncompleteBuilding=function(_, idx) me.buildings[idx]=true end}
          end
          local p=Players[2]
          function p:GetCities()
            local cities={c}
            return {Members=function()
              local i=0
              return function() i=i+1; if cities[i] then return i, cities[i] end end
            end, FindID=function(_, id) if id==c.id then return c end end}
          end
        """)
        self.rt.execute("Players[2]:GetTreasury()")
        self.order(0, K=19, P=2, U=0, X=131072, Y=0, I=0, V=40, S=99)
        self.assertFalse(self.last()["ok"])  # item purchase disabled (vanilla-only)

    def _install_explore_map(self, *, sea=False, reveal_on_move=False, move=True):
        # (2,1) unit, same landmass fog edge at revealed (1,1) beside fog (0,1).
        # (4,1) is a nearer other-area fog edge and must not win for a land unit.
        self.rt.execute(
            """
          EXPLORE_ARGS = {}
          EXPLORE_SPEC = {}
          local function put(x, y, area, revealed)
            EXPLORE_SPEC[tostring(x) .. "," .. tostring(y)] = {area = area, revealed = revealed}
          end
          put(0, 1, 1, false)
          put(1, 1, 1, true)
          put(2, 1, 1, true)
          put(3, 1, 2, true)
          put(4, 1, 2, false)
          Players[2].units[1].x = 2
          Players[2].units[1].y = 1
          GameInfo.Units[0].Domain = "%s"
          local oldGet = Map.GetPlot
          function Map.GetPlot(x, y)
            local p = oldGet(x, y)
            local s = EXPLORE_SPEC[tostring(x) .. "," .. tostring(y)]
            p.area = s and s.area or 1
            p.revealed = s and s.revealed or false
            p.water = %s
            function p:IsWater() return self.water end
            function p:IsImpassable() return false end
            function p:GetArea() return self.area end
            function p:GetIndex() return self.y * 10 + self.x end
            return p
          end
          function Map.GetPlotCount() return 6 end
          function Map.GetPlotByIndex(i)
            local coords = {{2, 1}, {3, 1}, {1, 1}, {0, 1}, {4, 1}, {5, 1}}
            local c = coords[i + 1]
            if c == nil then return Map.GetPlot(0, 0) end
            return Map.GetPlot(c[1], c[2])
          end
          function Map.GetAdjacentPlot(x, y, dir)
            local odd = (y %% 2) == 1
            local d = odd and {{1, 0}, {1, 1}, {0, 1}, {-1, 0}, {0, -1}, {1, -1}}
              or {{1, 0}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}}
            local step = d[dir + 1]
            if step == nil then return nil end
            return Map.GetPlot(x + step[1], y + step[2])
          end
          function Map.GetPlotDistance(x1, y1, x2, y2)
            return math.abs(x1 - x2) + math.abs(y1 - y2)
          end
          PlayersVisibility = {}
          PlayersVisibility[2] = {
            IsRevealed = function(_, index)
              table.insert(EXPLORE_ARGS, index)
              local x = index %% 10
              local y = math.floor(index / 10)
              return Map.GetPlot(x, y).revealed == true
            end,
          }
          local function applyMove(p, uid, x, y)
            if not %s then return true, "moved" end
            for _, u in ipairs(Players[p].units) do
              if u.id == uid then u.x = x; u.y = y; u.moves = 0 end
            end
            if %s then
              local function reveal(px, py)
                local row = EXPLORE_SPEC[tostring(px) .. "," .. tostring(py)]
                if row ~= nil then row.revealed = true end
              end
              reveal(x, y)
              for dir = 0, 5 do
                local a = Map.GetAdjacentPlot(x, y, dir)
                if a ~= nil then reveal(a:GetX(), a:GetY()) end
              end
            end
            return true, "moved"
          end
          ExposedMembers.Civ6Ai.MoveUnitForPlayer = applyMove
          ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = applyMove
            """
            % (
                "DOMAIN_SEA" if sea else "DOMAIN_LAND",
                "true" if sea else "false",
                "true" if move else "false",
                "true" if reveal_on_move else "false",
            )
        )








    def test_trade_explore_activate_guarded_fallback(self):
        self.order(0, K=25, P=2, U=7, S=100)
        self.assertFalse(self.last()["ok"])
        self.assertIn("explore_removed", self.last()["reason"])
        self.order(0, K=26, P=2, U=7, S=101)
        self.assertFalse(self.last()["ok"])
        self.assertIn("activate_unavailable", self.last()["reason"])
        self.order(0, K=24, P=2, U=7, I=3, S=102)
        self.assertFalse(self.last()["ok"])
        self.assertTrue("stale_city_id" in self.last()["reason"] or "trade" in self.last()["reason"])

    def test_upgrade_uses_the_type_index_and_does_not_kill_when_the_cost_is_unknown(self):
        self.rt.execute(r"""
          INIT_ARGS = {}
          KILLED = {}
          GameInfo.Units[0].Index = 0
          GameInfo.Units[0].UnitType = "UNIT_SWORDSMAN"
          UnitManager.Kill = function(u)
            table.insert(KILLED, u.id)
            u.dead = true
            local p = Players[u.owner]
            for i, x in ipairs(p.units) do if x == u then table.remove(p.units, i) break end end
          end
          UnitManager.InitUnit = function(pid, typ, x, y)
            table.insert(INIT_ARGS, typ)
            if type(typ) ~= "number" then return nil end
            for _, u in ipairs(Players[pid].units) do
              if u.x == x and u.y == y and not u.dead then return nil end
            end
            local u = MkUnit(pid, 200, x, y, typ)
            table.insert(Players[pid].units, u)
            return u
          end
        """)
        self.order(0, K=27, P=2, U=7, I=0, V=-1, S=210)
        self.assertFalse(self.last()["ok"])
        self.assertIn("upgrade cost is unknown", self.last()["reason"])
        self.assertIsNotNone(self.rt.eval("Players[2]:GetUnits():FindID(7)"))
        self.assertEqual(0, len(_vals(self.rt.eval("KILLED"))))

        self.order(0, K=27, P=2, U=7, I=0, V=10, S=211)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertIn("upgraded=UNIT_SWORDSMAN", self.last()["reason"])
        args = [int(value) for value in _vals(self.rt.eval("INIT_ARGS"))]
        self.assertTrue(args)
        self.assertTrue(all(value == 0 for value in args))
        self.assertIsNone(self.rt.eval("Players[2]:GetUnits():FindID(7)"))
        self.assertIsNotNone(self.rt.eval("Players[2]:GetUnits():FindID(200)"))

    def test_corps_forms_while_the_partner_is_alive_and_leaves_both_when_it_cannot(self):
        self.rt.execute(r"""
          MilitaryFormationTypes = {
            STANDARD_MILITARY_FORMATION = 0,
            CORPS_MILITARY_FORMATION = 1,
            ARMY_MILITARY_FORMATION = 2,
          }
          for _, u in ipairs(Players[2].units) do
            u.formation = 0
            function u:GetMilitaryFormation() return self.formation or 0 end
            function u:SetMilitaryFormation(f)
              local alive = false
              for _, other in ipairs(Players[self.owner].units) do
                if other.id ~= self.id and other.typ == self.typ and not other.dead then
                  alive = true
                end
              end
              if alive then self.formation = f end
            end
          end
        """)
        self.order(0, K=29, P=2, U=7, I=8, S=220)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertIn("formation=", self.last()["reason"])
        self.assertEqual(1, int(self.rt.eval("Players[2]:GetUnits():FindID(7).formation")))
        self.assertIsNone(self.rt.eval("Players[2]:GetUnits():FindID(8)"))

        self.rt.execute(r"""
          for _, u in ipairs(Players[2].units) do
            function u:SetMilitaryFormation(f) end
            u.formation = 0
          end
        """)
        # Unit 8 is already gone. Use the other warrior-type neighbour? Unit 9 is type 1.
        # Put a fresh same-type partner back and make formation a no-op.
        self.rt.execute(r"""
          local partner = MkUnit(2, 8, 11, 10, 0)
          partner.formation = 0
          function partner:GetMilitaryFormation() return self.formation or 0 end
          function partner:SetMilitaryFormation(f) end
          table.insert(Players[2].units, partner)
          local lead = Players[2]:GetUnits():FindID(7)
          function lead:SetMilitaryFormation(f) end
          lead.formation = 0
        """)
        self.order(0, K=29, P=2, U=7, I=8, S=221)
        self.assertFalse(self.last()["ok"], self.last())
        self.assertIn("both units are unchanged", self.last()["reason"])
        self.assertIsNotNone(self.rt.eval("Players[2]:GetUnits():FindID(7)"))
        self.assertIsNotNone(self.rt.eval("Players[2]:GetUnits():FindID(8)"))

    def test_formation_uses_the_short_constant_names_and_never_indexes_nil(self):
        self.rt.execute(r"""
          MilitaryFormationTypes = {
            STANDARD_FORMATION = 0,
            CORPS_FORMATION = 1,
            ARMY_FORMATION = 2,
          }
          for _, u in ipairs(Players[2].units) do
            u.formation = 0
            function u:GetMilitaryFormation() return self.formation or 0 end
            function u:SetMilitaryFormation(f)
              local alive = false
              for _, other in ipairs(Players[self.owner].units) do
                if other.id ~= self.id and other.typ == self.typ and not other.dead then
                  alive = true
                end
              end
              if alive then self.formation = f end
            end
          end
        """)
        self.order(0, K=29, P=2, U=7, I=8, S=222)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertIn("formation=", self.last()["reason"])
        self.rt.execute(r"""
          MilitaryFormationTypes = { ARMY_FORMATION = 2 }
          local partner = MkUnit(2, 8, 11, 10, 0)
          partner.formation = 0
          function partner:GetMilitaryFormation() return self.formation or 0 end
          function partner:SetMilitaryFormation(f) end
          table.insert(Players[2].units, partner)
        """)
        self.order(0, K=29, P=2, U=7, I=8, S=223)
        self.assertFalse(self.last()["ok"], self.last())
        self.assertIn("corps or army", self.last()["reason"])
        self.assertIsNotNone(self.rt.eval("Players[2]:GetUnits():FindID(8)"))

    def test_unread_move_results_are_not_evicted_at_512(self):
        self.rt.execute(r"""
          local shared = Civ6Ai_Orders._Shared()
          shared.OrderResults = {}
          for i = 1, 600 do
            Civ6Ai_Orders._Record(0, {S=i, K=1, P=1, U=7, D=5}, true, "moved:1,1")
          end
        """)
        self.assertEqual(600, self.rt.eval("#Civ6Ai_Orders._Shared().OrderResults"))
        self.assertEqual(1, self.rt.eval("Civ6Ai_Orders._Shared().OrderResults[1].seq"))
        self.rt.execute(r"""
          local shared = Civ6Ai_Orders._Shared()
          shared.OrderResults[1]._taken = true
          Civ6Ai_Orders._Record(0, {S=601, K=1, P=1, U=7, D=5}, true, "moved:2,2")
        """)
        self.assertEqual(600, self.rt.eval("#Civ6Ai_Orders._Shared().OrderResults"))
        self.assertNotEqual(1, self.rt.eval("Civ6Ai_Orders._Shared().OrderResults[1].seq"))

    def test_a_success_that_does_not_move_the_unit_says_so(self):
        self.rt.execute('ExposedMembers.Civ6Ai.MoveUnitForPlayer = function() return true, "" end')
        self.order(0, K=1, P=2, U=7, X=10, Y=11, S=301)
        self.assertFalse(self.last()["ok"], self.last())
        self.assertIn("move_not_applied", self.last()["reason"])
        self.assertEqual(10, self.rt.eval("Players[2]:GetUnits():FindID(7).x"))
        self.assertEqual(10, self.rt.eval("Players[2]:GetUnits():FindID(7).y"))

    def test_spread_spends_a_charge_only_when_pressure_is_applied(self):
        self.rt.execute(r"""
          GameInfo.Units[0].ReligiousStrength = 80
          GameInfo.Units[0].UnitType = "UNIT_MISSIONARY"
          REL = { charges = 2, religion = 3 }
          function REL:GetSpreadCharges() return self.charges end
          function REL:GetReligionType() return self.religion end
          function REL:ChangeSpreadCharges(n) self.charges = self.charges + n end
          Players[2].units[1].GetReligion = function() return REL end
          CITY = { got = nil }
          function CITY:GetID() return 9 end
          function CITY:GetReligion()
            local me = self
            return { AddReligiousPressure = function(_, owner, rtype, amount)
              me.got = { owner = owner, rtype = rtype, amount = amount }
            end }
          end
          Cities = { GetCityInPlot = function(x, y)
            if x == 10 and y == 11 then return CITY end
            return nil
          end }
        """)
        self.order(0, K=35, P=2, U=7, X=10, Y=11, A=0, S=230)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertEqual(1, int(self.rt.eval("REL.charges")))
        self.assertEqual(80, int(self.rt.eval("CITY.got.amount")))
        self.rt.execute("GameInfo.Units[0].ReligiousStrength = 0")
        self.order(0, K=35, P=2, U=7, X=10, Y=11, A=1, S=231)
        self.assertFalse(self.last()["ok"])
        self.assertIn("no charge was spent", self.last()["reason"])
        self.assertEqual(1, int(self.rt.eval("REL.charges")))


@unittest.skipIf(lupa is None, "lupa not installed")
class DealOrdersTests(unittest.TestCase):
    def setUp(self):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.rt.execute(FAKE_ENV)
        self.rt.execute((MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())

    def order(self, sender, **params):
        params.setdefault("T", 5)
        self.rt.globals().Civ6Ai_Orders.OnOrder(sender, self.rt.table_from(params))

    def last(self):
        return [dict(r.items()) for r in _vals(self.rt.eval("ExposedMembers.Civ6Ai.OrderResults"))][-1]
    def _add_city(self):
        self.rt.execute(r"""
          local c = {id=3, x=4, y=5, buildings={}}
          function c:GetID() return self.id end
          function c:GetX() return self.x end
          function c:GetY() return self.y end
          function c:GetGold()
            return {GetPurchaseCost=function() return 40 end, GetPlotPurchaseCost=function() return 25 end}
          end
          function c:GetBuildings()
            local me=self
            return {HasBuilding=function(_, i) return me.buildings[i]==true end}
          end
          function c:GetBuildQueue()
            local me=self
            return {CreateIncompleteBuilding=function(_, idx) me.buildings[idx]=true end}
          end
          local p=Players[2]
          function p:GetCities()
            local cities={c}
            return {Members=function()
              local i=0
              return function() i=i+1; if cities[i] then return i, cities[i] end end
            end}
          end
        """)

    def test_declare_war_then_peace(self):
        self.order(0, K=17, P=2, I=1, X=0, S=1)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertTrue(self.rt.eval("Players[2].war[1]"))
        self.order(0, K=33, P=2, I=1, W=0, X=-1, Y=0, I2=-1, I3=0, A=1, S=2)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIsNone(self.rt.eval("Players[2].war[1]"))

    def test_peace_that_leaves_the_other_side_at_war_does_not_pay(self):
        self.rt.execute(r"""
          Players[2]:GetDiplomacy(); Players[2].war[1] = true
          Players[1]:GetDiplomacy(); Players[1].war[2] = true
          Players[2]:GetTreasury(); Players[1]:GetTreasury()
          local orig = Players[1].GetDiplomacy
          Players[1].GetDiplomacy = function(self)
            local d = orig(self)
            d.MakePeaceWith = function() end
            return d
          end
        """)
        gold = self.rt.eval("Players[2].gold")
        self.order(0, K=33, P=2, I=1, W=10, X=-1, Y=0, I2=-1, I3=0, A=1, S=9)
        self.assertFalse(self.last()["ok"], self.last())
        self.assertIn("peace did not take effect", self.last()["reason"])
        self.assertEqual(gold, self.rt.eval("Players[2].gold"))
        self.assertTrue(self.rt.eval("Players[2].war[1]"))

    def test_war_refused_when_already_at_war(self):
        self.rt.execute("Players[2]:GetDiplomacy(); Players[2].war[1]=true")
        self.order(0, K=17, P=2, I=1, S=3)
        self.assertEqual(self.last()["reason"], "you are already at war with them")

    def test_buy_unit_is_disabled(self):
        self._add_city()
        self.rt.execute("Players[2]:GetTreasury()")
        before = self.rt.eval("#Players[2].units")
        gold = self.rt.eval("Players[2].gold")
        self.order(0, K=19, P=2, U=0, X=3, Y=0, I=0, V=40, S=4)
        self.assertFalse(self.last()["ok"])
        self.assertEqual(self.rt.eval("#Players[2].units"), before)
        self.assertEqual(self.rt.eval("Players[2].gold"), gold)

    def test_buy_tile_sets_owner(self):
        self._add_city()
        self.rt.execute("Players[2]:GetTreasury()")
        gold = self.rt.eval("Players[2].gold")
        self.order(0, K=20, P=2, I=3, X=6, Y=7, S=5)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertEqual(self.rt.eval("Map.GetPlot(6,7).owner"), 2)
        self.assertEqual(self.rt.eval("Players[2].gold"), gold - 25)

class OrderChannelDealTests(OrderChannelTests):
    def test_war_peace_purchase_pack_integer_fields(self):
        rt = self.rt
        rt.execute("Civ6Ai_Snapshot = {_PurchaseCost = function() return 40 end}; CityManager = {GetCity = function() return {} end}")
        d = self.decision([
            '{kind="send_diplomatic_action", arguments={target_player_id="PLAYER_1", action_id="DECLARE_WAR"}}',
            '{kind="execute_deal", arguments={target_player_id="PLAYER_3", gold=50, res1="", amt1=0, res2="", amt2=0, mode=1}}',
            '{kind="purchase_item", arguments={city_id="CITY_3", item_id="UNIT_WARRIOR"}}',
            '{kind="purchase_tile", arguments={city_id="CITY_3", target_x=6, target_y=7}}',
            '{kind="worker_improve", arguments={unit_id="UNIT_7", improvement_id="IMPROVEMENT_FARM", target_x=6, target_y=7}}',
        ])
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6), 5)
        sent = [dict(p.items()) for p in _vals(rt.eval("sent"))]
        self.assertEqual([p["K"] for p in sent], [17, 33, 19, 20, 21])
        self.assertEqual(sent[0]["I"], 1)
        self.assertEqual(sent[0]["X"], 0)
        self.assertEqual((sent[1]["I"], sent[1]["W"], sent[1]["X"], sent[1]["A"]), (3, 50, -1, 1))
        self.assertEqual(sent[2]["X"], 3)
        self.assertEqual(sent[2]["I"], 0)
        self.assertEqual((sent[2]["U"], sent[2]["V"]), (0, 40))
        self.assertEqual((sent[3]["I"], sent[3]["X"], sent[3]["Y"]), (3, 6, 7))
        self.assertEqual((sent[4]["U"], sent[4]["I"], sent[4]["X"], sent[4]["Y"]), (7, 0, 6, 7))


# Methods that exist on these objects inside a Gameplay script. UI-only calls
# such as RequestOperation and CanStartOperation are absent there, so a hit
# that is not in this set fails the check below.
_GAMEPLAY_ENGINE = {
    "UnitManager": {
        "MoveUnit", "FinishMoves", "Kill", "InitUnit", "RestoreMovement",
        "ChangeMovesRemaining", "GetMoveToPath", "PlaceUnit",
    },
    "CityManager": {"CanStartCommand", "RequestCommand", "TransferCity"},
    "CombatManager": {
        "SimulateAttackVersus", "SimulateAttackInto", "CanAttackTarget",
        "GenerateCombatResults",
    },
    "UI": set(),
}
_ENGINE_CALL = re.compile(
    r"\b(UnitManager|CityManager|CombatManager|UI)\.([A-Za-z_][A-Za-z0-9_]*)"
)


def _strip_lua_comments(source: str) -> str:
    """Drop Lua comments, keeping newlines so reported lines match the file."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith("--", i):
            long = re.match(r"--\[(=*)\[", source[i:])
            if long:
                close = "]" + long.group(1) + "]"
                end = source.find(close, i + len(long.group(0)))
                if end < 0:
                    break
                out.append("\n" * source.count("\n", i, end))
                i = end + len(close)
                continue
            end = source.find("\n", i)
            if end < 0:
                break
            i = end
            continue
        ch = source[i]
        if ch in ("'", '"'):
            out.append(ch)
            i += 1
            while i < n:
                out.append(source[i])
                if source[i] == "\\":
                    i += 1
                    if i < n:
                        out.append(source[i])
                    i += 1
                    continue
                if source[i] == ch:
                    i += 1
                    break
                i += 1
            continue
        long = re.match(r"\[(=*)\[", source[i:])
        if long:
            close = "]" + long.group(1) + "]"
            end = source.find(close, i + len(long.group(0)))
            if end < 0:
                break
            out.append("\n" * source.count("\n", i, end))
            i = end + len(close)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _unknown_engine_calls(path: str, source: str) -> list[str]:
    found: list[str] = []
    for lineno, line in enumerate(_strip_lua_comments(source).splitlines(), 1):
        for manager, method in _ENGINE_CALL.findall(line):
            if method not in _GAMEPLAY_ENGINE[manager]:
                found.append(f"{path}:{lineno} {manager}.{method}")
    return found


class GameplayApiTests(unittest.TestCase):
    def test_gameplay_scripts_call_only_gameplay_engine_functions(self):
        unknown: list[str] = []
        stripped: list[str] = []
        for path in sorted((MOD / "Gameplay").glob("*.lua")):
            text = path.read_text()
            unknown.extend(_unknown_engine_calls(path.name, text))
            stripped.append(_strip_lua_comments(text))
        self.assertEqual(unknown, [])
        body = "\n".join(stripped)
        for required in (
            "UnitManager.MoveUnit",
            "UnitManager.Kill",
            "UnitManager.PlaceUnit",
            "CityManager.RequestCommand",
            "CityManager.CanStartCommand",
            "CityManager.TransferCity",
            "CombatManager.SimulateAttackVersus",
        ):
            self.assertIn(required, body)
        for banned in (
            "UnitManager.RequestOperation",
            "UnitManager.CanStartOperation",
            "CityManager.RequestOperation",
            "CityManager.CanStartOperation",
            "UI.RequestPlayerOperation",
            "CreateTradeRoute",
            "CanCreateTradeRoute",
            "RequestPolicyChanges",
            "ChangeTokensToGive",
            "ChangeTokensReceived",
            "GiveTokenToPlayer",
            ".Activate(",
            ":Activate(",
        ):
            self.assertNotIn(banned, body)

    def test_host_ui_path_cannot_sync_trade_gp_envoy_or_formation(self):
        # These four have no Gameplay call. A host InGame RequestOperation is
        # not a synced command for an AI seat; the comment records why, and
        # the stripped script still must not call the UI operation.
        text = (MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text(encoding="utf-8")
        for phrase in (
            "They stay unoffered",
            "Game.GetLocalPlayer()",
            "EXECUTE_SCRIPT",
            "local_player_swap_blocked_mp",
            "do not cross the network",
            "GetInfluence()",
            "only on the host desyncs",
        ):
            self.assertIn(phrase, text)
        stripped = _strip_lua_comments(text)
        for banned in (
            "UnitManager.RequestOperation",
            "UI.RequestPlayerOperation",
            "CreateTradeRoute",
            "ChangeTokensToGive",
            ".Activate(",
            ":Activate(",
        ):
            self.assertNotIn(banned, stripped)
        self.assertIn("trade_route_unavailable:no_gameplay_route", stripped)
        self.assertIn("activate_unavailable:no_gameplay_activate", stripped)
        self.assertIn("envoy_unavailable:no_gameplay_route", stripped)

    def test_ui_only_operation_is_rejected_and_comments_are_not(self):
        sample = (
            "UnitManager.RequestOperation(unit, op, params)\n"
            "-- UnitManager.CanStartOperation is UI-only\n"
            "CityManager.RequestCommand(city, cmd, params)\n"
        )
        self.assertEqual(
            _unknown_engine_calls("sample.lua", sample),
            ["sample.lua:1 UnitManager.RequestOperation"],
        )


if __name__ == "__main__":
    unittest.main()
