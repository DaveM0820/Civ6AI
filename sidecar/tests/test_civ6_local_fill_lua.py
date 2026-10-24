"""Local seat empty-queue fill: priority-weighted, seeded, one try per city per turn (lupa)."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Production.lua"
APPLY = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Apply.lua"

STUBS = r"""
LOG = {}
REQUESTS = {}
TURN = 4
LOCAL = 0
Civ6Ai_Util = { Log = function(m) table.insert(LOG, m) end }
Civ6Ai_Snapshot = { _Priorities = function(p) return PRIOS or {} end }
Game = { GetCurrentGameTurn = function() return TURN end, GetLocalPlayer = function() return LOCAL end }
CityOperationTypes = { BUILD = 1, PARAM_UNIT_TYPE = 11, PARAM_BUILDING_TYPE = 12, PARAM_PROJECT_TYPE = 13, PARAM_DISTRICT_TYPE = 14 }
local function rows(list) return setmetatable({}, { __call = function()
  local i = 0
  return function() i = i + 1; return list[i] end
end }) end
GameInfo = {
  Units = rows({ { UnitType = "UNIT_WARRIOR", Hash = 101, Cost = 40 }, { UnitType = "UNIT_SETTLER", Hash = 102, Cost = 80 },
                 { UnitType = "UNIT_SPEARMAN", Hash = 103, Cost = 65 } }),
  Buildings = rows({ { BuildingType = "BUILDING_MONUMENT", Hash = 201, Cost = 60 } }),
  Projects = rows({}),
  Districts = rows({}),
}
BLOCKED = { [103] = true }
function makeCity(id, size)
  local city = { id = id, size = size }
  function city:GetID() return self.id end
  function city:GetBuildQueue()
    local c = self
    return {
      GetSize = function() return c.size end,
      CanProduce = function(_, hash) return true end,
    }
  end
  return city
end
CITIES = { makeCity(65536, 0), makeCity(65537, 1) }
Players = { [0] = { GetCities = function() return { Members = function()
  local i = 0
  return function() i = i + 1; if CITIES[i] then return i, CITIES[i] end end
end } end } }
CityManager = {
  CanStartOperation = function(city, op, params) for _, h in pairs(params) do if BLOCKED[h] then return false end end return true end,
  RequestOperation = function(city, op, params) table.insert(REQUESTS, { city = city:GetID(), params = params }) end,
}
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LocalFillTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.lua.execute(PRODUCTION.read_text(encoding="utf-8"))
        self.g = self.lua.globals()

    def fill(self):
        return self.g.Civ6Ai_Production.FillEmptyQueuesWeighted(0)

    def test_fills_only_empty_queue_once_per_turn(self):
        self.assertEqual(1, self.fill())
        reqs = list(self.g.REQUESTS.values())
        self.assertEqual(1, len(reqs))
        self.assertEqual(65536, reqs[0].city)
        hashes = set(reqs[0].params.values())
        self.assertTrue(hashes <= {101, 102, 201})  # never the blocked spearman
        # Same turn: no second attempt even though the stub queue stays empty.
        self.assertEqual(0, self.fill())
        self.assertEqual(1, len(list(self.g.REQUESTS.values())))
        log = [m for m in self.g.LOG.values() if "fill_empty" in m]
        self.assertEqual(1, len(log))
        self.assertIn("|requested", log[0])
        self.assertIn("top=", log[0])
        self.g.TURN = 5
        self.assertEqual(1, self.fill())

    def test_pick_is_deterministic_for_player_city_turn(self):
        self.fill()
        first = dict(list(self.g.REQUESTS.values())[0].params)
        self.lua.execute("REQUESTS = {}; Civ6Ai_Production._fillTried = {}")
        self.fill()
        self.assertEqual(first, dict(list(self.g.REQUESTS.values())[0].params))

    def test_not_local_seat_is_untouched(self):
        self.g.LOCAL = 1
        self.assertEqual(0, self.fill())
        self.assertEqual(0, len(list(self.g.REQUESTS.values())))

    def test_weighted_pick_follows_weights(self):
        opts = self.lua.eval("""{ { id = "A", score = 0 }, { id = "B", score = 99 } }""")
        counts = {"A": 0, "B": 0}
        for seed in range(200):
            pick, _ = self.g.Civ6Ai_Production.WeightedPick(opts, seed)
            counts[pick.id] += 1
        self.assertGreater(counts["B"], counts["A"] * 10)

    def test_weights_are_bounded(self):
        opts = self.lua.eval("""{ { id = "A", score = -300 }, { id = "B", score = 0 }, { id = "C", score = 400 } }""")
        self.g.Civ6Ai_Production.WeightedPick(opts, 1)
        weights = {o.id: o.weight for o in opts.values()}
        self.assertEqual(weights["A"], self.g.Civ6Ai_Production.WEIGHT_FLOOR)
        self.assertEqual(weights["C"], self.g.Civ6Ai_Production.WEIGHT_CAP)

    def test_builder_surplus_penalty_matches_python(self):
        from sidecar import civ6_priorities as prio
        P = self.g.Civ6Ai_Production
        lua_sit = P.ComposeSituation(self.lua.eval("{ builders = 6, builder_charges = 18, open_tiles = 0, cities = 1 }"))
        self.assertTrue(lua_sit.builder_surplus)
        tags = self.lua.eval('{ "PSEUDOYIELD_IMPROVEMENT" }')
        lua_score = P.ScoreBuild("UNIT_BUILDER", tags, lua_sit, "unit")
        py_sit = prio.compose_situation(builders=6, builder_charges=18, open_tiles=0, cities=1)
        self.assertEqual(lua_score, prio.item_score("UNIT_BUILDER", ["PSEUDOYIELD_IMPROVEMENT"], py_sit, "unit"))
        open_sit = P.ComposeSituation(self.lua.eval("{ builders = 1, builder_charges = 2, open_tiles = 5, cities = 1 }"))
        self.assertFalse(open_sit.builder_surplus)

    def _shares(self, opts, seeds=3000, **raw):
        """Pick frequency per id over many seeds with the early situation from raw."""
        P = self.g.Civ6Ai_Production
        parts = ", ".join(f"{k} = {str(v).lower() if isinstance(v, bool) else v}" for k, v in raw.items())
        sit = P.ComposeSituation(self.lua.eval("{ " + parts + " }"))
        counts = {}
        for seed in range(seeds):
            options = self.lua.eval("{ " + ", ".join(
                '{ id = "%s", score = %d, kind = "%s", tags = { %s } }' % (
                    i, sc, k, ", ".join(f'"{t}"' for t in tags)) for i, sc, k, tags in opts) + " }")
            pick, _ = P.WeightedPick(options, seed * 7919 + 13, sit)
            counts[pick.id] = counts.get(pick.id, 0) + 1
        return {k: v / seeds for k, v in counts.items()}, sit

    OPTS = [
        ("UNIT_SETTLER", 100, "unit", ["PSEUDOYIELD_UNIT_SETTLER"]),
        ("UNIT_BUILDER", 10, "unit", ["PSEUDOYIELD_IMPROVEMENT"]),
        ("UNIT_SCOUT", 80, "unit", ["PSEUDOYIELD_UNIT_EXPLORER"]),
        ("UNIT_WARRIOR", 0, "unit", ["PSEUDOYIELD_UNIT_COMBAT"]),
        ("BUILDING_MONUMENT", 60, "building", []),
    ]

    def test_early_shares_half_settler_quarter_builder(self):
        freq, sit = self._shares(self.OPTS, cities=1, pop=2, turn=8)
        self.assertTrue(sit.early)
        self.assertAlmostEqual(1 / 2, freq["UNIT_SETTLER"], delta=0.04)
        self.assertAlmostEqual(1 / 4, freq["UNIT_BUILDER"], delta=0.04)
        rest = freq.get("UNIT_SCOUT", 0) + freq.get("BUILDING_MONUMENT", 0)
        self.assertAlmostEqual(1 / 4, rest, delta=0.04)
        self.assertEqual(0, freq.get("UNIT_WARRIOR", 0))  # no military share in peace
        # The rest keeps the priority weights: scout (score 80) beats monument (60).
        self.assertGreater(freq["UNIT_SCOUT"], freq["BUILDING_MONUMENT"])

    def test_missing_settler_share_goes_to_builder(self):
        opts = [o for o in self.OPTS if o[0] != "UNIT_SETTLER"]  # pop 1: no settler offered
        freq, _ = self._shares(opts, cities=1, pop=1, turn=3)
        self.assertAlmostEqual(3 / 4, freq["UNIT_BUILDER"], delta=0.04)
        opts = [o for o in opts if o[0] != "UNIT_BUILDER"]
        freq, _ = self._shares(opts, cities=1, pop=1, turn=3)
        self.assertAlmostEqual(1.0, freq.get("UNIT_SCOUT", 0) + freq.get("BUILDING_MONUMENT", 0), delta=0.001)

    def test_threat_shifts_to_military_and_keeps_some_settlers(self):
        freq, _ = self._shares(self.OPTS, cities=1, pop=3, turn=12, threatened=True)
        self.assertAlmostEqual(1 / 6, freq.get("UNIT_SETTLER", 0), delta=0.04)
        self.assertAlmostEqual(1 / 2, freq["UNIT_WARRIOR"], delta=0.04)
        self.assertGreater(freq["UNIT_WARRIOR"], freq["UNIT_BUILDER"])

    def test_threat_near_ignores_scouts_and_ends_once_defended(self):
        P = self.g.Civ6Ai_Production
        self.lua.execute("""
          GameInfo.Units = GameInfo.Units or {}
          GameInfo.Units["UNIT_SCOUT"] = { Combat = 10, PromotionClass = "PROMOTION_CLASS_RECON", FormationClass = "FORMATION_CLASS_LAND_COMBAT" }
          GameInfo.Units["UNIT_SPEARMAN"] = { Combat = 25, PromotionClass = "PROMOTION_CLASS_ANTI_CAVALRY", FormationClass = "FORMATION_CLASS_LAND_COMBAT" }
          GameInfo.Units["UNIT_SLINGER"] = { Combat = 5, RangedCombat = 15, PromotionClass = "PROMOTION_CLASS_RANGED", FormationClass = "FORMATION_CLASS_LAND_COMBAT" }
          GameInfo.Improvements = GameInfo.Improvements or {}
          TPlots = {}
          Map = Map or {}
          Map.GetPlot = function(x, y) return { GetX = function() return x end, GetY = function() return y end, GetImprovementType = function() return -1 end } end
          Map.GetPlotDistance = function(ax, ay, bx, by) return math.max(math.abs(ax - bx), math.abs(ay - by)) end
          Units = Units or {}
          Units.GetUnitsInPlot = function(plot) return TPlots[plot:GetX() .. "," .. plot:GetY()] or {} end
          Players[63] = { IsBarbarian = function() return true end }
          Players[0] = Players[0] or {}
          Players[0].GetDiplomacy = function() return { IsAtWarWith = function() return false end } end
          function TUnit(owner, t) return { GetOwner = function() return owner end, GetType = function() return t end } end
          TCities = { Members = function() local done = false; return function() if not done then done = true; return 1, { GetX = function() return 10 end, GetY = function() return 10 end } end end end }
        """)
        def threat(turn, units):
            self.lua.execute("TPlots = {}")
            for xy, owner, typ in units:
                self.lua.execute('TPlots["%s"] = TPlots["%s"] or {}; table.insert(TPlots["%s"], TUnit(%d, "%s"))' % (xy, xy, xy, owner, typ))
            self.lua.execute("Game = Game or {}; Game.GetCurrentGameTurn = function() return %d end" % turn)
            return P.ThreatNear(0, self.lua.eval("TCities"))
        self.assertFalse(threat(100, [("11,12", 63, "UNIT_SCOUT")])[0])  # live P0 T13: a barbarian scout
        self.assertTrue(threat(101, [("12,11", 63, "UNIT_SPEARMAN")])[0])
        t, h, d = threat(102, [("12,11", 63, "UNIT_SPEARMAN"), ("10,10", 0, "UNIT_SLINGER"), ("11,10", 0, "UNIT_SLINGER")])
        self.assertEqual((False, 1, 2), (t, h, d))

    def test_shares_end_at_three_cities_or_turn_sixty(self):
        P = self.g.Civ6Ai_Production
        self.assertFalse(P.ComposeSituation(self.lua.eval("{ cities = 3, pop = 4, turn = 20 }")).early)
        self.assertFalse(P.ComposeSituation(self.lua.eval("{ cities = 1, pop = 4, turn = 61 }")).early)
        self.assertTrue(P.ComposeSituation(self.lua.eval("{ cities = 2, pop = 4, turn = 60 }")).early)
        opts = self.lua.eval("""{ { id = "A", score = 0 }, { id = "B", score = 99 } }""")
        late = P.ComposeSituation(self.lua.eval("{ cities = 3, pop = 4, turn = 20 }"))
        P.WeightedPick(opts, 1, late)
        self.assertEqual([5, 104], sorted(o.weight for o in opts.values()))

    def test_situation_for_counts_builders_and_open_tiles(self):
        self.lua.execute(r"""
          GameInfo.Units[1] = { UnitType = "UNIT_BUILDER", BuildCharges = 3 }
          GameInfo.Units[2] = { UnitType = "UNIT_WARRIOR", Combat = 20 }
          local function mk(t) return { GetType = function() return t end, GetBuildCharges = function() return 3 end } end
          local list = { mk(1), mk(1), mk(2) }
          Players[0].GetUnits = function() return { Members = function()
            local i = 0
            return function() i = i + 1; if list[i] then return i, list[i] end end
          end } end
          for _, c in ipairs(CITIES) do c.GetX = function() return 5 end; c.GetY = function() return 5 end end
          local plots = {}
          Map = { GetPlot = function(x, y)
            local k = x * 100 + y
            if not plots[k] then
              plots[k] = { idx = k, own = (x == 5 and y == 6) and 0 or -1,
                GetIndex = function(p) return p.idx end, GetOwner = function(p) return p.own end,
                IsWater = function() return false end, IsCity = function() return false end,
                GetImprovementType = function() return -1 end, GetDistrictType = function() return -1 end }
            end
            return plots[k]
          end }
          Civ6Ai_Snapshot._LegalImprovementsAt = function() return { "IMPROVEMENT_FARM" } end
        """)
        P = self.g.Civ6Ai_Production
        sit = P.SituationFor(0, self.g.CITIES[1])
        self.assertEqual(sit.unit_counts["UNIT_BUILDER"], 2)
        # 6 charges, 1 open tile: surplus, so another builder is penalised.
        self.assertTrue(sit.builder_surplus)
        self.assertEqual(P.OpenImproveTiles(0, self.g.Players[0].GetCities()), 1)

    def test_apply_drops_hints_quietly(self):
        src = APPLY.read_text(encoding="utf-8")
        self.assertIn('c.kind ~= "fallback_hint"', src)
        self.assertIn("set_build_priority = true", src)


if __name__ == "__main__":
    unittest.main()
