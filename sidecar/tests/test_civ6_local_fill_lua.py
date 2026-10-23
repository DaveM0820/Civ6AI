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

    def test_apply_drops_hints_quietly(self):
        src = APPLY.read_text(encoding="utf-8")
        self.assertIn('c.kind ~= "fallback_hint"', src)
        self.assertIn("set_build_priority = true", src)


if __name__ == "__main__":
    unittest.main()
