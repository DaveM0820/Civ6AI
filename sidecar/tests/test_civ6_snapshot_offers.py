"""WP-B: settle facts, command tokens, builder offers, command_results."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_adapter
from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_wire

ROOT = Path(__file__).resolve().parents[2]
SNAP_LUA = ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua"


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class SnapshotLuaOffersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("Civ6Ai_Util = { Log = function() end, PlotId = function(x,y) return 'PLOT_'..x..'_'..y end, JsonArrayList = function() return {} end, JsonNull = function() return nil end, PlayerId = function(p) return 'PLAYER_'..p end }")
        self.lua.execute(SNAP_LUA.read_text(encoding="utf-8"))

    def test_settle_facts_unranked_legal_sites_and_here_reason(self):
        self.lua.execute(
            r"""
            Map = {
              GetPlot = function(x,y)
                return {
                  GetX=function() return x end, GetY=function() return y end,
                  GetIndex=function() return x*100+y end,
                  IsWater=function() return false end, IsImpassable=function() return false end,
                  IsFreshWater=function() return x==12 and y==10 end, IsRiver=function() return false end,
                  GetOwner=function() return -1 end,
                }
              end,
              GetPlotDistance = function(ax,ay,bx,by) return math.max(math.abs(ax-bx), math.abs(ay-by)) end,
            }
            Players = {}
            for pid=0,3 do
              Players[pid] = { GetCities = function() return { Members = function() return function() return nil end end } end }
            end
            Players[0].GetCities = function()
              local city = { GetX=function() return 10 end, GetY=function() return 10 end }
              return { Members = function()
                local done=false
                return function() if not done then done=true return 1, city end end
              end }
            end
            PlayersVisibility = { [1] = { IsRevealed = function() return true end } }
            ExposedMembers = { Civ6Ai = {
              CanFoundCityForPlayer = function(p,id) return false, 'too_close_to_city' end
            }}
            GameInfo = { Units = { [0] = { UnitType='UNIT_SETTLER', FoundCity=true } } }
            local settler = {
              GetOwner=function() return 1 end, GetID=function() return 7 end,
              GetType=function() return 0 end, GetX=function() return 11 end, GetY=function() return 10 end,
            }
            UNIT = settler
            """
        )
        facts = self.lua.globals().Civ6Ai_Snapshot._AddSettleFacts(self.lua.globals().UNIT)
        self.assertFalse(bool(facts.here_ok))
        self.assertEqual("too_close_to_city", facts.here_reason)
        sites = facts.sites
        dists = [sites[i].dist for i in range(1, len(sites) + 1)]
        self.assertTrue(dists)
        self.assertEqual(sorted(dists), dists)
        coords = [(sites[i].x, sites[i].y) for i in range(1, len(sites) + 1)]
        self.assertNotIn((10, 10), coords)
        self.assertGreater(len(coords), 6)

    def test_known_players_are_met_majors_only(self):
        self.lua.execute(
            r"""
            Players = {}
            PlayerConfigurations = {}
            local function major(id, leader, civ)
              Players[id] = {
                IsAlive = function() return true end,
                IsMajor = function() return true end,
                IsBarbarian = function() return false end,
                GetTeam = function() return id end,
                GetScore = function() return 10 end,
                GetDiplomacy = function()
                  return { HasMet = function() return true end,
                           IsAtWarWith = function() return false end,
                           HasOpenBordersFrom = function() return false end,
                           HasDefensivePact = function() return false end,
                           HasDeclaredFriendship = function() return false end,
                           HasAllied = function() return false end }
                end,
                GetDiplomaticAI = function() return { GetDiplomaticStateIndex = function() return nil end } end,
              }
              PlayerConfigurations[id] = {
                GetLeaderTypeName = function() return leader end,
                GetLeaderName = function() return leader end,
                GetCivilizationTypeName = function() return civ end,
              }
            end
            major(0, "LEADER_JOHN_CURTIN", "CIVILIZATION_AUSTRALIA")
            major(1, "LEADER_ROBERT_THE_BRUCE", "CIVILIZATION_SCOTLAND")
            Players[62] = {
              IsAlive = function() return true end,
              IsMajor = function() return false end,
              IsBarbarian = function() return true end,
              GetTeam = function() return 62 end,
              GetScore = function() return 0 end,
              GetDiplomacy = function()
                return { HasMet = function() return true end, IsAtWarWith = function() return false end }
              end,
            }
            PlayerConfigurations[62] = {
              GetLeaderTypeName = function() return "LEADER_BARBARIAN" end,
              GetLeaderName = function() return "Barbarians" end,
              GetCivilizationTypeName = function() return "CIVILIZATION_BARBARIAN" end,
            }
            Players[61] = {
              IsAlive = function() return true end,
              IsMajor = function() return false end,
              IsBarbarian = function() return false end,
              GetTeam = function() return 61 end,
              GetScore = function() return 0 end,
              GetDiplomacy = function()
                return { HasMet = function() return true end, IsAtWarWith = function() return false end }
              end,
            }
            PlayerConfigurations[61] = {
              GetLeaderTypeName = function() return "LEADER_FREE_CITIES" end,
              GetLeaderName = function() return "Free Cities" end,
              GetCivilizationTypeName = function() return "CIVILIZATION_FREE_CITIES" end,
            }
            Players[3] = {
              IsAlive = function() return true end,
              IsMajor = function() return false end,
              IsBarbarian = function() return false end,
              GetTeam = function() return 3 end,
              GetScore = function() return 0 end,
              GetDiplomacy = function()
                return { HasMet = function() return true end, IsAtWarWith = function() return false end }
              end,
            }
            PlayerConfigurations[3] = {
              GetLeaderTypeName = function() return "LEADER_MINOR_CIV_AMSTERDAM" end,
              GetLeaderName = function() return "Amsterdam" end,
              GetCivilizationTypeName = function() return "CIVILIZATION_AMSTERDAM" end,
            }
            Locale = { Lookup = function(s) return s end }
            """
        )
        rows = self.lua.globals().Civ6Ai_Snapshot._BuildKnownPlayers(1)
        ids = [rows[i].player_id for i in range(1, len(rows) + 1)]
        kinds = [bool(rows[i].is_major) for i in range(1, len(rows) + 1)]
        self.assertEqual(["PLAYER_0"], ids)
        self.assertEqual([True], kinds)
        self.assertNotIn("PLAYER_62", ids)
        self.assertNotIn("PLAYER_61", ids)
        self.assertNotIn("PLAYER_3", ids)

    def test_goal_reads_split_civ6ai_goal_properties(self):
        self.lua.execute(
            r"""
            local props = {
              CIV6AI_GOAL_1_9_X = 18, CIV6AI_GOAL_1_9_Y = 16,
              CIV6AI_GOAL_1_9_A = 1, CIV6AI_GOAL_1_9_T = 2,
            }
            Game = {
              GetCurrentGameTurn = function() return 4 end,
              GetProperty = function(self, k) return props[k] end,
            }
            """
        )
        goal = self.lua.globals().Civ6Ai_Snapshot._UnitGoal(1, 9)
        self.assertEqual(18, goal.x)
        self.assertEqual(16, goal.y)
        self.assertEqual("found", goal.intent)
        self.assertEqual(1, goal.A)

    def test_command_results_labelled_by_decision_turn(self):
        self.lua.execute(
            r"""
            Game = { GetCurrentGameTurn = function() return 4 end }
            GameConfiguration = { IsNetworkMultiplayer = function() return false end }
            ExposedMembers = { Civ6Ai = { OrderResults = {
              { player=1, kind=1, turn=3, apply_turn=3, decision_turn=3, ok=true, reason='ok', unit=9 },
              { player=1, kind=4, turn=3, apply_turn=3, decision_turn=3, ok=false, reason='too_close_to_city', unit=7 },
              { player=2, kind=1, turn=3, apply_turn=3, decision_turn=3, ok=true, reason='ok', unit=1 },
            }}}
            """
        )
        rows = self.lua.globals().Civ6Ai_Snapshot._AddCommandResults(1, 4)
        kinds = [rows[i].kind for i in range(1, len(rows) + 1)]
        self.assertIn("found_city", kinds)
        self.assertTrue(all(rows[i].decision_turn == 3 for i in range(1, len(rows) + 1)))

    def test_builder_skips_improvement_already_on_tile(self):
        self.lua.execute(
            r"""
            GameInfo = { Improvements = {
              [0] = { ImprovementType='IMPROVEMENT_FARM', Index=0, Buildable=true },
            }}
            function GameInfo.Improvements()
              local n=0
              return function()
                n=n+1
                if n==1 then return GameInfo.Improvements[0] end
              end
            end
            Map = { GetPlot = function(x,y)
              return {
                GetX=function() return x end, GetY=function() return y end,
                GetOwner=function() return 1 end,
                GetImprovementType=function() return 0 end,
              }
            end, GetPlotDistance = function(a,b,c,d) return math.max(math.abs(a-c), math.abs(b-d)) end }
            Players = { [1] = { GetTeam = function() return 1 end } }
            ImprovementBuilder = { CanHaveImprovement = function() return true end }
            UnitManager = nil
            local builder = {
              GetBuildCharges=function() return 3 end,
              GetX=function() return 5 end, GetY=function() return 5 end,
            }
            UNIT = builder
            CMDS = {}
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot
        cmds = self.lua.globals().CMDS
        snap._AddBuilderCommands(cmds, 1, self.lua.globals().UNIT, "UNIT_3")
        self.assertEqual(0, len(cmds))

    def test_builder_skips_improvement_reserved_for_other_unit(self):
        # Live T8-T11: an Australian builder was offered only
        # Improve(IMPROVEMENT_ROMAN_FORT), which Improvement_ValidBuildUnits
        # reserves for UNIT_ROMAN_LEGION; gameplay rejected it every turn.
        self.lua.execute(
            r"""
            local rows = {
              [0] = { ImprovementType='IMPROVEMENT_FARM', Index=0, Buildable=true },
              [1] = { ImprovementType='IMPROVEMENT_ROMAN_FORT', Index=1, Buildable=true },
            }
            GameInfo = { Improvements = rows, Units = { [4] = { UnitType='UNIT_BUILDER' } } }
            function GameInfo.Improvements()
              local n=-1
              return function() n=n+1 return rows[n] end
            end
            local valid = {
              { ImprovementType='IMPROVEMENT_FARM', UnitType='UNIT_BUILDER' },
              { ImprovementType='IMPROVEMENT_ROMAN_FORT', UnitType='UNIT_ROMAN_LEGION' },
            }
            GameInfo.Improvement_ValidBuildUnits = function()
              local i=0
              return function() i=i+1 return valid[i] end
            end
            Map = { GetPlot = function(x,y)
              return {
                GetX=function() return x end, GetY=function() return y end,
                GetOwner=function() return (x==5 and y==5) and 1 or -1 end,
                GetImprovementType=function() return -1 end,
              }
            end, GetPlotDistance = function(a,b,c,d) return math.max(math.abs(a-c), math.abs(b-d)) end }
            Players = { [1] = { GetTeam = function() return 1 end } }
            ImprovementBuilder = { CanHaveImprovement = function() return true end }
            UnitManager = nil
            UNIT = {
              GetBuildCharges=function() return 3 end, GetType=function() return 4 end,
              GetX=function() return 5 end, GetY=function() return 5 end,
            }
            CMDS = {}
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot
        cmds = self.lua.globals().CMDS
        snap._AddBuilderCommands(cmds, 1, self.lua.globals().UNIT, "UNIT_3")
        offered = [cmds[i].fixed_arguments.improvement_id for i in range(1, len(cmds) + 1)]
        self.assertEqual(["IMPROVEMENT_FARM"], offered)

    def test_adjacent_moves_only_when_combat_next_to_enemy(self):
        self.lua.execute(
            r"""
            Map = { GetAdjacentPlot = function() return nil end }
            local scout = {
              GetOwner=function() return 1 end, GetID=function() return 1 end,
              GetX=function() return 4 end, GetY=function() return 4 end, GetType=function() return 0 end,
            }
            GameInfo = { Units = { [0] = { Combat=0, FormationClass='FORMATION_CLASS_RECON' } } }
            UNIT = scout
            CMDS = {}
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot
        snap._AddAdjacentMoveCommands(self.lua.globals().CMDS, self.lua.globals().UNIT, "UNIT_1")
        self.assertEqual(0, len(self.lua.globals().CMDS))


class CommandWireVocabTests(unittest.TestCase):
    def test_far_move_without_adjacent_offer(self):
        snap = {
            "game": {"map_width": 40, "map_height": 40},
            "your_units": [{"unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_10_10"}],
            "legal_commands": [
                {"command_id": "CMD_skip_UNIT_SETTLER_1", "kind": "unit_skip",
                 "fixed_arguments": {"unit_id": "UNIT_SETTLER_1"}},
            ],
        }
        cmd = command_wire.resolve_unit_token(snap, "UNIT_SETTLER_1", "MoveTo(30,12)")
        self.assertEqual("CMD_UNIT_SETTLER_1_moveto_30_12", cmd)
        extra = next(c for c in snap["legal_commands"] if c["command_id"] == cmd)
        self.assertEqual(1, extra["fixed_arguments"]["G"])
        self.assertEqual(0, extra["fixed_arguments"]["A"])

    def test_own_tile_move_becomes_found_when_legal(self):
        snap = {
            "game": {"map_width": 40, "map_height": 40},
            "your_units": [{
                "unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_10_10",
                "settle": {"here_ok": True, "sites": []},
            }],
            "legal_commands": [
                {"command_id": "CMD_found_UNIT_SETTLER_1", "kind": "found_city",
                 "fixed_arguments": {"unit_id": "UNIT_SETTLER_1"}},
            ],
        }
        cmd = command_wire.resolve_unit_token(snap, "UNIT_SETTLER_1", "MoveTo(10,10)")
        self.assertEqual("CMD_found_UNIT_SETTLER_1", cmd)
        self.assertTrue(any("self-tile" in n for n in command_wire.LAST_UNRESOLVED))

    def test_settle_token_and_reply(self):
        snap = {
            "game": {"map_width": 40, "map_height": 40},
            "your_units": [{
                "unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_18_20",
                "settle": {"here_ok": False, "here_reason": "too_close_to_city", "coastal": True,
                           "fresh_water": False, "sites": [{"x": 18, "y": 18, "dist": 2, "coastal": True}]},
            }],
            "legal_commands": [],
        }
        out = command_wire.expand_civ6_command_wire(snap, {"settler_1.settle": "(18,18)"})
        self.assertTrue(str(out.get("cmd.0", "")).startswith("CMD_"))
        extra = next(c for c in snap["legal_commands"] if c["command_id"] == out["cmd.0"])
        self.assertEqual("found", extra["fixed_arguments"]["intent"])
        self.assertEqual(1, extra["fixed_arguments"]["A"])
        self.assertEqual(1, extra["fixed_arguments"]["G"])

    def test_improve_destination_token(self):
        snap = {
            "game": {"map_width": 40, "map_height": 40},
            "your_units": [{"unit_id": "UNIT_3", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_6_7"}],
            "legal_commands": [],
        }
        out = command_wire.expand_civ6_command_wire(snap, {"builder_1.improve": "(8,7):IMPROVEMENT_FARM"})
        self.assertIn("cmd.0", out)
        extra = next(c for c in snap["legal_commands"] if c["command_id"] == out["cmd.0"])
        self.assertEqual("worker_improve", extra["kind"])
        self.assertEqual(8, extra["fixed_arguments"]["target_x"])
        self.assertEqual("improve", extra["fixed_arguments"]["intent"])
        self.assertEqual(2, extra["fixed_arguments"]["A"])
        self.assertEqual(1, extra["fixed_arguments"]["G"])

    def test_trade_route_listed_destination(self):
        snap = {
            "your_units": [{"unit_id": "UNIT_9", "unit_type_id": "UNIT_TRADER", "plot_id": "PLOT_1_1"}],
            "legal_commands": [{
                "command_id": "CMD_trade_UNIT_9_CITY_4",
                "kind": "move_unit",
                "fixed_arguments": {
                    "unit_id": "UNIT_9", "city_id": "CITY_4", "target_x": 12, "target_y": 4,
                    "intent": "trade", "A": 4, "G": 1, "goal": 1,
                },
            }],
        }
        out = command_wire.expand_civ6_command_wire(snap, {"trader_1.trade_route": "CITY_4"})
        self.assertEqual("CMD_trade_UNIT_9_CITY_4", out.get("cmd.0"))

    def test_sitrep_includes_settle_facts_on_turn_1(self):
        snap = {
            "your_units": [{
                "unit_id": "UNIT_SETTLER_1",
                "unit_type_id": "UNIT_SETTLER",
                "plot_id": "PLOT_18_20",
                "needs_orders": True,
                "settle": {
                    "here_ok": False,
                    "here_reason": "too_close_to_city",
                    "coastal": True,
                    "fresh_water": False,
                    "sites": [{"x": 20, "y": 19, "dist": 2, "coastal": True, "fresh_water": True}],
                },
            }],
            "history": {"command_results": [{
                "turn": 1, "decision_turn": 1, "apply_turn": 1, "kind": "move_unit",
                "summary": "ok move_unit", "affected_ids": ["UNIT_SETTLER_1"], "ok": True, "effect": "applied",
            }]},
        }
        lines = "\n".join(command_wire.sitrep_offer_lines(snap))
        self.assertIn("settler_1.settle.here", lines)
        self.assertIn("coastal", lines)
        self.assertIn("too_close_to_city", lines)
        self.assertIn("settler_1.settle.sites", lines)
        self.assertIn("S1 (20,19)", lines)
        self.assertIn("dist 2", lines)
        prompt = civ6_wire._append_civ6_unit_situation_wire
        buf: list[str] = []
        prompt(buf, snap)
        joined = "\n".join(buf)
        self.assertIn("settle.here", joined)

    def test_history_command_results_survive_adapter(self):
        snap = civ6_adapter.build_classical_golden_snapshot()
        snap["history"]["command_results"] = [{
            "turn": 36, "decision_turn": 36, "apply_turn": 37, "kind": "move_unit",
            "summary": "fail move_unit no_path", "affected_ids": ["UNIT_SCOUT_1"],
            "ok": False, "reason": "no_path", "effect": "failed", "unit": "UNIT_SCOUT_1",
        }]
        civ6_adapter.normalize_civ6_snapshot(snap)
        row = snap["history"]["command_results"][0]
        self.assertEqual(36, row["decision_turn"])
        self.assertEqual("failed", row["effect"])


if __name__ == "__main__":
    unittest.main()
