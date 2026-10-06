"""Offline checks for the synced order channel (Gameplay/Civ6Ai_Orders.lua,
InGame/Civ6Ai_OrderChannel.lua): per-turn order queue, sender rules, combat."""
import pathlib
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

    def test_idle_units_end_their_turn_but_builders_stay_with_game_ai(self):
        self.rt.execute("GameInfo.Units[2] = {BuildCharges=3}; table.insert(Players[2].units, MkUnit(2,10,1,1,2))")
        self.order(0, K=2, P=2, I=4, S=7, B=1, J=1, N=1, T=6)
        self.turn_start(2, turn=6)
        self.assertEqual(self.rt.eval("Players[2].units[2].moves"), 0)
        self.assertEqual(self.rt.eval("Players[2].units[4].moves"), 2)

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
        self.assertTrue(self.last()["reason"].startswith("ranged:def_dmg=0>30:att_dmg=0>0"))
        self.assertEqual(self.rt.eval("Players[2].units[3].moves"), 0)

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
        self.assertEqual(self.rt.eval("Players[2].units[1].dmg"), 20)
        self.assertEqual(self.rt.eval("Players[1].units[2].dmg"), 35)

    def test_melee_kill_advances_into_plot(self):
        self.rt.execute("Players[2].war = {[1]=true}; local e = MkUnit(1,3,10,11,0); e.dmg = 80;"
                        " table.insert(Players[1].units, e)")
        self.order(0, K=7, P=2, U=7, X=10, Y=11, S=13)
        self.assertIn("killed=true", self.last()["reason"])
        self.assertEqual(self.rt.eval("#Players[1].units"), 1)
        self.assertEqual(self.rt.eval("Players[2].units[1].y"), 11)

    def test_far_move_uses_path_route(self):
        self.rt.execute("ExposedMembers.Civ6Ai.MoveUnitAlongPathForPlayer = function(p,u,x,y) path_called = {p,u,x,y}; return true, 'path' end")
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
        rt.execute("TURN = 7")
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.DrainResults(), 0)
        self.assertEqual(rt.eval("recorded[1].reason"), "no_result_from_gameplay")

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
        self.assertEqual(len(ids), 24)
        for cat in ids:
            for level in (1, 2, 3):
                self.assertEqual(len(_vals(self.rt.eval("GameEvents['Civ6AiPrio_%d_%d'].fns" % (cat.id, level)))), 1)

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

    def test_improve_walks_then_builds(self):
        self.rt.execute("Players[2].units[1].charges=3")
        self.order(0, K=21, P=2, U=7, I=0, X=10, Y=11, S=98)
        self.assertTrue(self.last()["ok"], self.last())
        self.assertEqual(self.rt.eval("Map.GetPlot(10,11).improvement"), 0)
        self.assertEqual(self.rt.eval("Players[2].units[1].charges"), 2)

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
        self.order(0, K=19, P=2, U=0, X=131072, Y=0, I=0, S=99)
        self.assertTrue(self.last()["ok"], self.last()["reason"])

    def test_trade_explore_activate_guarded_fallback(self):
        self.order(0, K=25, P=2, U=7, S=100)
        self.assertFalse(self.last()["ok"])
        self.assertIn("explore_unavailable", self.last()["reason"])
        self.order(0, K=26, P=2, U=7, S=101)
        self.assertFalse(self.last()["ok"])
        self.assertIn("activate_unavailable", self.last()["reason"])
        self.order(0, K=24, P=2, U=7, I=3, S=102)
        self.assertFalse(self.last()["ok"])
        self.assertTrue("stale_city_id" in self.last()["reason"] or "trade" in self.last()["reason"])


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
        self.order(0, K=18, P=2, I=1, S=2)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertIsNone(self.rt.eval("Players[2].war[1]"))

    def test_war_refused_when_already_at_war(self):
        self.rt.execute("Players[2]:GetDiplomacy(); Players[2].war[1]=true")
        self.order(0, K=17, P=2, I=1, S=3)
        self.assertEqual(self.last()["reason"], "you are already at war with them")

    def test_buy_unit_debits_gold_and_spawns(self):
        self._add_city()
        self.rt.execute("Players[2]:GetTreasury()")
        before = self.rt.eval("#Players[2].units")
        gold = self.rt.eval("Players[2].gold")
        self.order(0, K=19, P=2, U=0, X=3, Y=0, I=0, S=4)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertEqual(self.rt.eval("#Players[2].units"), before + 1)
        self.assertEqual(self.rt.eval("Players[2].gold"), gold - 40)

    def test_buy_tile_sets_owner(self):
        self._add_city()
        self.rt.execute("Players[2]:GetTreasury()")
        gold = self.rt.eval("Players[2].gold")
        self.order(0, K=20, P=2, I=3, X=6, Y=7, S=5)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertEqual(self.rt.eval("Map.GetPlot(6,7).owner"), 2)
        self.assertEqual(self.rt.eval("Players[2].gold"), gold - 25)

    def test_improve_places_and_spends_charge(self):
        self.rt.execute("Players[2].units[1].charges=3; Players[2].units[1].x=6; Players[2].units[1].y=7")
        self.order(0, K=21, P=2, U=7, I=0, X=6, Y=7, S=6)
        self.assertTrue(self.last()["ok"], self.last()["reason"])
        self.assertEqual(self.rt.eval("Map.GetPlot(6,7).improvement"), 0)
        self.assertEqual(self.rt.eval("Players[2].units[1].charges"), 2)

    def test_improve_refused_without_charges(self):
        self.rt.execute("Players[2].units[1].charges=0; Players[2].units[1].x=6; Players[2].units[1].y=7")
        self.order(0, K=21, P=2, U=7, I=0, X=6, Y=7, S=7)
        self.assertEqual(self.last()["reason"], "that unit has no build charges left")
        self.assertIsNone(self.rt.eval("Map.GetPlot(6,7).improvement"))


class OrderChannelDealTests(OrderChannelTests):
    def test_war_peace_purchase_pack_integer_fields(self):
        rt = self.rt
        d = self.decision([
            '{kind="send_diplomatic_action", arguments={target_player_id="PLAYER_1", action_id="DECLARE_WAR"}}',
            '{kind="propose_peace", arguments={target_player_id="PLAYER_3"}}',
            '{kind="purchase_item", arguments={city_id="CITY_3", item_id="UNIT_WARRIOR"}}',
            '{kind="purchase_tile", arguments={city_id="CITY_3", target_x=6, target_y=7}}',
            '{kind="worker_improve", arguments={unit_id="UNIT_7", improvement_id="IMPROVEMENT_FARM", target_x=6, target_y=7}}',
        ])
        self.assertEqual(rt.globals().Civ6Ai_OrderChannel.SendDecision(2, d, 6), 5)
        sent = [dict(p.items()) for p in _vals(rt.eval("sent"))]
        self.assertEqual([p["K"] for p in sent], [17, 18, 19, 20, 21])
        self.assertEqual(sent[0]["I"], 1)
        self.assertEqual(sent[0]["X"], 0)
        self.assertEqual(sent[1]["I"], 3)
        self.assertEqual(sent[2]["X"], 3)
        self.assertEqual(sent[2]["I"], 0)
        self.assertEqual(sent[2]["U"], 0)
        self.assertEqual((sent[3]["I"], sent[3]["X"], sent[3]["Y"]), (3, 6, 7))
        self.assertEqual((sent[4]["U"], sent[4]["I"], sent[4]["X"], sent[4]["Y"]), (7, 0, 6, 7))


if __name__ == "__main__":
    unittest.main()
