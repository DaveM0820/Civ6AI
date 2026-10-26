import unittest
from pathlib import Path

from sidecar import civ6_priorities as P

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Production.lua"


class SettlersOnlyPresetTest(unittest.TestCase):
    def test_preset_is_ancient_and_parses(self):
        preset = P.PRESET_BY_KEY["settlers_only"]
        self.assertEqual(int(preset["min_era"]), 0)
        self.assertEqual(P.preset_levels("settlers_only"), {P.BY_KEY["settlers_only"]["id"]: 3})
        self.assertIn("settlers only", preset["desc"])
        self.assertIn(preset, P.available_presets({}))


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class SettlersOnlyFillTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(PRODUCTION.read_text(encoding="utf-8"))

    def _run(self, ids, on):
        return self.lua.execute(
            "local opts = {}\n"
            + "".join(f"opts[#opts+1] = {{ id = '{i}', tags = {{}} }}\n" for i in ids)
            + "local lv = {}\n"
            + (f"lv[Civ6Ai_Production.PRIORITY_KEY_ID.settlers_only] = 3\n" if on else "")
            + "local out, note = Civ6Ai_Production.SettlersOnly(opts, { levels = lv })\n"
            + "return #out, note, out[1] and out[1].id\n"
        )

    def test_keeps_only_settler(self):
        self.assertEqual(self._run(["UNIT_BUILDER", "UNIT_SETTLER", "BUILDING_MONUMENT"], True), (1, "settler", "UNIT_SETTLER"))

    def test_falls_back_when_no_settler(self):
        n, note, _ = self._run(["UNIT_BUILDER", "BUILDING_MONUMENT"], True)
        self.assertEqual((n, note), (2, "fallback"))

    def test_off_is_untouched(self):
        n, note, _ = self._run(["UNIT_BUILDER", "UNIT_SETTLER"], False)
        self.assertEqual((n, note), (2, None))


if __name__ == "__main__":
    unittest.main()


class SettlersOnlyWeightTest(unittest.TestCase):
    def test_all_in_settler_dominates_and_rivals_clamped(self):
        cat = P.BY_KEY["settlers_only"]
        self.assertEqual(P.scaled(cat["pseudo"]["PSEUDOYIELD_UNIT_SETTLER"], 3), 1000)
        self.assertEqual(P.scaled(cat["pseudo"]["PSEUDOYIELD_IMPROVEMENT"], 3), -100)


try:
    import lupa as _lupa
except ImportError:  # pragma: no cover
    _lupa = None


@unittest.skipIf(_lupa is None, "lupa not installed")
class EarlyLockGameplayTest(unittest.TestCase):
    def _rt(self, cities, human=False):
        from sidecar.tests import test_civ6ai_orders_lua as T
        rt = _lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(T.FAKE_ENV)
        rt.execute((T.MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())
        rt.execute("""
          Players[6] = { IsHuman = function() return %s end, IsMajor = function() return true end,
            GetCities = function() return { GetCount = function() return %d end } end }
        """ % ("true" if human else "false", cities))
        return rt, rt.globals().Civ6Ai_Orders

    def _levels(self, O):
        ids = {c["key"]: c["id"] for c in P.CATEGORIES}
        return {k: O.PriorityLevel(6, ids[k]) for k in ("peace", "expansion", "improvements", "war")}

    def test_ai_seat_below_three_cities_gets_early_set(self):
        rt, O = self._rt(2)
        O.PriorityLevel  # exists
        self.assertTrue(O.ApplyEarlyLock(6))
        self.assertEqual(self._levels(O), {"peace": 1, "expansion": 3, "improvements": 1, "war": 0})

    def test_three_cities_or_human_untouched(self):
        for cities, human in ((3, False), (1, True)):
            rt, O = self._rt(cities, human)
            self.assertFalse(O.ApplyEarlyLock(6))
            self.assertEqual(self._levels(O)["expansion"], 0)

    def test_matches_sidecar_early_set(self):
        rt, O = self._rt(1)
        want = {P.BY_ID[c]["key"]: l for c, l in P.early_levels().items()}
        got = {k: v for k, v in dict(O.EARLY_SET.items()).items()}
        self.assertEqual(want, got)


@unittest.skipIf(_lupa is None, "lupa not installed")
class SettlerDivertTest(unittest.TestCase):
    def _run(self, pop, current, negative_ok=True, stock=0):
        from sidecar.tests import test_civ6ai_orders_lua as T
        rt = _lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(T.FAKE_ENV)
        rt.execute((T.MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text())
        rt.execute("""
          Made = {}
          GameInfo.Units = GameInfo.Units or {}
          GameInfo.Units["UNIT_SETTLER"] = { Index = 3, Cost = 80, PopulationCost = 1, PrereqPopulation = 2 }
          Progress = 30
          Pop = %d
          City = { GetID = function() return 1 end, GetX = function() return 4 end, GetY = function() return 5 end,
            GetPopulation = function() return Pop end, ChangePopulation = function(self, d) Pop = Pop + d end,
            GetYield = function() return 10 end,
            GetBuildQueue = function() return {
              CurrentlyBuilding = function() return "%s" end,
              GetUnitCost = function() return 20 end,
              GetProductionProgress = function() return Progress end,
              AddProgress = function(self, n) if %s or n > 0 then Progress = Progress + n end end } end }
          Players[6] = { IsHuman = function() return false end, IsMajor = function() return true end,
            GetCities = function() return { GetCount = function() return 1 end,
              Members = function() local d = false; return function() if d then return nil end; d = true; return 1, City end end } end }
          UnitManager = UnitManager or {}
          UnitManager.InitUnit = function(o, t, x, y) Made[#Made + 1] = t; return {} end
          Game:SetProperty("CIV6AI_SETTLER_STOCK_6_1", %d)
        """ % (pop, current, "true" if negative_ok else "false", stock))
        rt.globals().Civ6Ai_Orders.DivertToSettlers(6, rt.eval("Players[6]"))
        return (rt.eval("Progress"), rt.eval("Game:GetProperty('CIV6AI_SETTLER_STOCK_6_1')"),
                rt.eval("#Made"), rt.eval("Pop"))

    def test_moves_half_of_production_into_stock(self):
        self.assertEqual(self._run(2, "UNIT_BUILDER"), (25, 5, 0, 2))

    def test_trains_settler_when_stock_reaches_cost(self):
        self.assertEqual(self._run(3, "UNIT_BUILDER", stock=18), (25, 3, 1, 2))

    def test_no_credit_when_engine_refuses_negative(self):
        self.assertEqual(self._run(2, "UNIT_BUILDER", negative_ok=False), (30, 0, 0, 2))

    def test_skips_pop_one_and_settler_builds(self):
        self.assertEqual(self._run(1, "UNIT_BUILDER")[1], 0)
        self.assertEqual(self._run(2, "UNIT_SETTLER")[1], 0)


class SettlerBuyFactTest(unittest.TestCase):
    def test_states_gold_and_cheapest_cost(self):
        snap = {"your_empire": {"gold": 120}, "your_cities": [{"city_id": "C1", "name": "Rome"}],
                "legal_commands": [{"kind": "purchase_item", "fixed_arguments":
                                    {"item_id": "UNIT_SETTLER", "cost": 230, "city_id": "C1"}}]}
        text = P.settler_buy_fact(snap)
        self.assertIn("Gold: 120.", text)
        self.assertIn("A settler costs 230 gold in Rome", text)
        self.assertIn("No city can buy", P.settler_buy_fact({"your_empire": {"gold": 5}}))
