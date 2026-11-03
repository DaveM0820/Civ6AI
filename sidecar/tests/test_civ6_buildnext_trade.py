"""Build-next category pseudoyield boost (SQL) and trade-route facts/logging."""
from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_trade

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "mod/Civ6Ai/Data"
SNAP_LUA = ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua"

SCHEMA = """
CREATE TABLE Types (Type TEXT PRIMARY KEY, Kind TEXT);
CREATE TABLE Strategies (StrategyType TEXT PRIMARY KEY, VictoryType TEXT, NumConditionsNeeded INT);
CREATE TABLE StrategyConditions (StrategyType TEXT, ConditionFunction TEXT, StringValue TEXT, ThresholdValue INT, Disqualifier INT);
CREATE TABLE AiListTypes (ListType TEXT PRIMARY KEY);
CREATE TABLE AiLists (ListType TEXT PRIMARY KEY, System TEXT);
CREATE TABLE Strategy_Priorities (StrategyType TEXT, ListType TEXT, PRIMARY KEY (StrategyType, ListType));
CREATE TABLE AiFavoredItems (ListType TEXT, Item TEXT, Favored INT, Value INT, PRIMARY KEY (ListType, Item));
CREATE TABLE PseudoYields (PseudoYieldType TEXT PRIMARY KEY);
CREATE TABLE Units (UnitType TEXT PRIMARY KEY, Cost INT, FormationClass TEXT, PseudoYieldType TEXT);
CREATE TABLE Buildings (BuildingType TEXT PRIMARY KEY, Cost INT, IsWonder INT);
CREATE TABLE Districts (DistrictType TEXT PRIMARY KEY, Cost INT);
INSERT INTO PseudoYields VALUES ('PSEUDOYIELD_UNIT_SETTLER'), ('PSEUDOYIELD_UNIT_TRADE'),
  ('PSEUDOYIELD_UNIT_COMBAT'), ('PSEUDOYIELD_UNIT_NAVAL_COMBAT'), ('PSEUDOYIELD_DISTRICT');
INSERT INTO Units VALUES ('UNIT_SETTLER', 80, 'FORMATION_CLASS_CIVILIAN', 'PSEUDOYIELD_UNIT_SETTLER'),
  ('UNIT_TRADER', 40, 'FORMATION_CLASS_CIVILIAN', 'PSEUDOYIELD_UNIT_TRADE'),
  ('UNIT_GALLEY', 65, 'FORMATION_CLASS_NAVAL', NULL), ('UNIT_ARCHER', 60, 'FORMATION_CLASS_LAND_COMBAT', NULL),
  ('UNIT_BUILDER', 50, 'FORMATION_CLASS_CIVILIAN', NULL);
INSERT INTO Buildings VALUES ('BUILDING_GRANARY', 65, 0), ('BUILDING_PYRAMIDS', 200, 1);
INSERT INTO Districts VALUES ('DISTRICT_CAMPUS', 54), ('DISTRICT_CITY_CENTER', 0);
"""


class BuildNextCategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.executescript((DATA / "Civ6Ai_BuildNext.sql").read_text(encoding="utf-8"))

    def boost(self, item: str):
        return self.db.execute(
            "SELECT f.Item, f.Value FROM Strategy_Priorities s JOIN AiLists l ON l.ListType = s.ListType "
            "JOIN AiFavoredItems f ON f.ListType = s.ListType WHERE l.System = 'PseudoYields' AND s.StrategyType = ?",
            ("CIV6AI_NEXT_" + item,)).fetchall()

    def test_each_pick_boosts_its_category(self):
        self.assertEqual([("PSEUDOYIELD_UNIT_SETTLER", 1500)], self.boost("UNIT_SETTLER"))
        self.assertEqual([("PSEUDOYIELD_UNIT_TRADE", 1500)], self.boost("UNIT_TRADER"))
        self.assertEqual([("PSEUDOYIELD_UNIT_NAVAL_COMBAT", 1500)], self.boost("UNIT_GALLEY"))
        self.assertEqual([("PSEUDOYIELD_UNIT_COMBAT", 1500)], self.boost("UNIT_ARCHER"))
        self.assertEqual([("PSEUDOYIELD_DISTRICT", 1500)], self.boost("DISTRICT_CAMPUS"))
        # No vanilla category pseudoyield: favoured list only.
        self.assertEqual([], self.boost("UNIT_BUILDER"))
        self.assertEqual([], self.boost("BUILDING_GRANARY"))
        # The favoured-item list is still there for every pick.
        n = self.db.execute("SELECT COUNT(*) FROM AiFavoredItems WHERE ListType = 'Civ6AiNext_UNIT_BUILDER' AND Favored = 1").fetchone()[0]
        self.assertEqual(1, n)

    def test_boost_beats_every_preset_pseudoyield(self):
        text = (DATA / "Civ6Ai_Priorities.sql").read_text(encoding="utf-8")
        values = [int(v) for v in re.findall(r"PseudoYields', PseudoYieldType, 1, (-?\d+) FROM PseudoYields", text)]
        self.assertTrue(values)
        # Own category cut by the worst preset still beats the biggest rival boost.
        self.assertGreater(1500 + min(values), max(values))


class TradePromptTests(unittest.TestCase):
    def test_routes_traders_and_last_request(self):
        snap = {"civ6": {"trade": {
            "routes": 1, "capacity": 2,
            "traders": [{"unit_id": "UNIT_5", "x": 3, "y": 4, "on_route": False},
                        {"unit_id": "UNIT_6", "on_route": True, "destination": "Rome"}],
            "last_requests": [{"unit_id": "UNIT_5", "turn": 9, "took": False}],
        }}}
        lines = civ6_trade.prompt_lines(snap, {"UNIT_5": "Trader1"})
        self.assertIn("TRADE ROUTES: 1/2 in use (1 free slot)", lines[0])
        self.assertIn("Trader1 idle at 3,4", lines[0])
        self.assertIn("UNIT_6 on a route to Rome", lines[0])
        self.assertIn("T9 for Trader1: did NOT start", lines[1])

    def test_no_block_no_lines(self):
        self.assertEqual([], civ6_trade.prompt_lines({"civ6": {}}))


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class TradeSnapshotLuaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("LOGS = {}; Civ6Ai_Util = { Log = function(s) LOGS[#LOGS+1] = s end, PlayerId = function(p) return 'PLAYER_'..p end }")
        self.lua.execute(SNAP_LUA.read_text(encoding="utf-8"))
        self.lua.execute(r"""
            Game = { GetCurrentGameTurn = function() return 10 end }
            GameInfo = { Units = { [1] = { UnitType = 'UNIT_TRADER', MakeTradeRoute = true }, [2] = { UnitType = 'UNIT_WARRIOR' } } }
            Locale = { Lookup = function(s) return s end }
            local function mk(id, t) return { GetID=function() return id end, GetType=function() return t end,
              GetX=function() return id end, GetY=function() return 1 end, GetMovesRemaining=function() return 1 end } end
            T5, T6, W7 = mk(5, 1), mk(6, 1), mk(7, 2)
            local dest = { GetName = function() return 'Rome' end }
            local city = { GetID=function() return 1 end, GetTrade=function() return { GetOutgoingRoutes = function()
              return { { TraderUnitID = 6, DestinationCityPlayer = 2, DestinationCityID = 3 } } end } end }
            Players = { [0] = {
              GetTrade = function() return { GetNumOutgoingRoutes=function() return 1 end, GetOutgoingRouteCapacity=function() return 2 end } end,
              GetCities = function() return { Members = function() local d=false return function() if not d then d=true return 1, city end end end } end,
              GetUnits = function() return 'U' end } }
            Players[2] = { GetCities = function() return { FindID = function() return dest end } end }
            Civ6Ai_Snapshot._IterateUnits = function() return { T5, T6, W7 } end
            Civ6Ai_Snapshot._UnitMoves = function() return 1 end
            Civ6Ai_Apply = { _tradeRequested = { [0] = { UNIT_5 = { turn = 9 }, UNIT_6 = { turn = 9 } } },
              TradeRequestedThisTurn = function(p, u) return u == 'UNIT_5' and false end }
        """)

    def test_build_trade_block_and_logs(self):
        b = self.lua.globals().Civ6Ai_Snapshot._BuildTrade(0)
        self.assertEqual(1, b.routes)
        self.assertEqual(2, b.capacity)
        traders = [dict(b.traders[i].items()) for i in range(1, len(b.traders) + 1)]
        self.assertEqual(["UNIT_5", "UNIT_6"], [t["unit_id"] for t in traders])
        self.assertFalse(traders[0]["on_route"])
        self.assertTrue(traders[1]["on_route"])
        self.assertEqual("Rome", traders[1]["destination"])
        reqs = {b.last_requests[i].unit_id: b.last_requests[i].took for i in range(1, len(b.last_requests) + 1)}
        self.assertEqual({"UNIT_5": False, "UNIT_6": True}, reqs)
        logs = [self.lua.globals().LOGS[i] for i in range(1, len(self.lua.globals().LOGS) + 1)]
        self.assertTrue(any(l.startswith("trade|status|player=0|t=10|routes=1/2|traders=UNIT_5@5,1:mv=1:idle;UNIT_6") for l in logs), logs)
        self.assertTrue(any("trade|route_check|player=0|unit=UNIT_5|requested_t=9|took=false" in l for l in logs), logs)

    def test_trader_on_route_is_busy(self):
        snap = self.lua.globals().Civ6Ai_Snapshot
        g = self.lua.globals()
        self.assertTrue(snap._TraderBusy(0, g.T6))
        self.assertFalse(snap._TraderBusy(0, g.T5))
        self.assertFalse(snap._TraderBusy(0, g.W7))
        self.lua.execute("Civ6Ai_Apply.TradeRequestedThisTurn = function(p, u) return u == 'UNIT_5' end")
        self.assertTrue(snap._TraderBusy(0, g.T5))


if __name__ == "__main__":
    unittest.main()
