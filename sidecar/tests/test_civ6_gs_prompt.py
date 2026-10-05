"""Gathering Storm climate, city power, and strategic stockpiles.

Lua builders are mocked engine (lupa). Wire lines are Python-only so they still
run when lupa is missing.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_adapter
from sidecar import civ6_gs_wire as gs_wire
from sidecar import civ6_wire

ROOT = Path(__file__).resolve().parents[2]
INGAME = ROOT / "mod" / "Civ6Ai" / "InGame"

MOCKS = r"""
Locale = {Lookup = function(s) return s end}
GameClimate = {
  GetTotalCO2Footprint = function() return 1840 end,
  GetPlayerCO2Footprint = function(id, last) return id == 0 and 420 or 0 end,
  GetClimateChangeLevel = function() return 2 end,
  GetTemperatureChange = function() return 1.2 end,
  GetNextSeaLevelRiseTurns = function() return 8 end,
  GetTilesFlooded = function() return 4 end,
  GetTilesSubmerged = function() return 1 end,
  GetStormPercentChance = function() return 12 end,
  GetFloodPercentChance = function() return 8 end,
  GetDroughtPercentChance = function() return 5 end,
}
local function resource_iter()
  local rows = {
    {ResourceType = "RESOURCE_IRON", ResourceClassType = "RESOURCECLASS_STRATEGIC", Index = 0},
    {ResourceType = "RESOURCE_OIL", ResourceClassType = "RESOURCECLASS_STRATEGIC", Index = 1},
    {ResourceType = "RESOURCE_WINE", ResourceClassType = "RESOURCECLASS_LUXURY", Index = 2},
  }
  local i = 0
  return function()
    i = i + 1
    return rows[i]
  end
end
GameInfo = { Resources = resource_iter }
local amounts = {RESOURCE_IRON = 42, RESOURCE_OIL = 8, RESOURCE_WINE = 2}
local caps = {RESOURCE_IRON = 50, RESOURCE_OIL = 50, RESOURCE_WINE = 0}
local acc = {RESOURCE_IRON = 3, RESOURCE_OIL = 0}
local unit_d = {RESOURCE_IRON = 1}
local power_d = {RESOURCE_OIL = 4}
local resources = {
  GetResourceAmount = function(self, key) return amounts[key] or 0 end,
  GetResourceStockpileCap = function(self, key) return caps[key] or 0 end,
  GetReservedResourceAmount = function(self, key) return 0 end,
  GetResourceAccumulationPerTurn = function(self, key) return acc[key] or 0 end,
  GetResourceImportPerTurn = function(self, key) return 0 end,
  GetBonusResourcePerTurn = function(self, key) return 0 end,
  GetUnitResourceDemandPerTurn = function(self, key) return unit_d[key] or 0 end,
  GetPowerResourceDemandPerTurn = function(self, key) return power_d[key] or 0 end,
}
local athens_power = {
  GetFreePower = function() return 0 end,
  GetTemporaryPower = function() return 0 end,
  GetRequiredPower = function() return 6 end,
  IsFullyPowered = function() return false end,
  IsFullyPoweredByActiveProject = function() return false end,
}
local rome_power = {
  GetFreePower = function() return 8 end,
  GetTemporaryPower = function() return 2 end,
  GetRequiredPower = function() return 8 end,
  IsFullyPowered = function() return true end,
  IsFullyPoweredByActiveProject = function() return false end,
}
local quiet_power = {
  GetFreePower = function() return 0 end,
  GetTemporaryPower = function() return 0 end,
  GetRequiredPower = function() return 0 end,
  IsFullyPowered = function() return true end,
  IsFullyPoweredByActiveProject = function() return false end,
}
local athens = {
  GetID = function() return 0 end, GetName = function() return "Athens" end,
  GetPower = function() return athens_power end,
}
local rome = {
  GetID = function() return 1 end, GetName = function() return "Rome" end,
  GetPower = function() return rome_power end,
}
quiet = {
  GetID = function() return 2 end, GetName = function() return "Quiet" end,
  GetPower = function() return quiet_power end,
}
POWER_CITIES = {athens, rome, quiet}
local function members()
  local i = 0
  return function()
    i = i + 1
    local city = POWER_CITIES[i]
    if city then return i, city end
  end
end
Players = {}
Players[0] = {
  GetCities = function() return {Members = members} end,
  GetResources = function() return resources end,
}
Civ6Ai_Util = {}
function Civ6Ai_Util.JsonArrayList() return {} end
function Civ6Ai_Util.JsonNull() return "NULL" end
function Civ6Ai_Util.PlayerId(i) return "PLAYER_" .. tostring(i) end
function Civ6Ai_Util.Log(s) LOGGED = (LOGGED or "") .. s .. "\n" end
Civ6Ai_Production = { _WireCityId = function(city) return "CITY_" .. tostring(city:GetID()) end }
"""


def _to_py(value):
    if hasattr(value, "items") and not isinstance(value, (str, bytes, dict)):
        items = list(value.items())
        if items and all(isinstance(k, int) for k, _ in items):
            return [_to_py(v) for _, v in sorted(items)]
        return {k: _to_py(v) for k, v in items}
    return value


def _gs_snapshot() -> dict:
    snap = civ6_adapter.build_classical_golden_snapshot()
    snap["civ6"]["climate"] = {
        "source": "ClimateScreen.lua GameClimate",
        "co2_world": 1840,
        "co2_you": 420,
        "level": 2,
        "temperature_c_tenths": 12,
        "sea_rise_turns": 8,
        "tiles_flooded": 4,
        "tiles_submerged": 1,
        "storm_pct": 12,
        "flood_pct": 8,
        "drought_pct": 5,
    }
    snap["civ6"]["power"] = {
        "source": "CityBannerManager.lua city:GetPower",
        "cities_powered": 1,
        "cities_needing": 2,
        "cities": [
            {"city_id": "CITY_ATHENS", "name": "Athens", "required": 6, "free": 0,
             "temporary": 0, "powered": False, "powered_by_project": False},
            {"city_id": "CITY_CORINTH", "name": "Corinth", "required": 8, "free": 8,
             "temporary": 2, "powered": True, "powered_by_project": False},
        ],
    }
    snap["civ6"]["stockpiles"] = {
        "source": "TopPanel_Expansion2.lua GetResources stockpile",
        "strategics": [
            {"resource_id": "RESOURCE_IRON", "amount": 42, "cap": 50, "reserved": 0,
             "per_turn": 3, "from_improvements": 3, "import": 0, "bonus": 0,
             "unit_demand": 1, "power_demand": 0},
            {"resource_id": "RESOURCE_OIL", "amount": 8, "cap": 50, "reserved": 0,
             "per_turn": 0, "from_improvements": 0, "import": 0, "bonus": 0,
             "unit_demand": 0, "power_demand": 4},
        ],
    }
    return snap


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LuaLateGameTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute((INGAME / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))

    def test_climate_when_co2_underway(self):
        block = _to_py(self.lua.eval("Civ6Ai_Snapshot._BuildClimate(0)"))
        self.assertEqual(block["co2_world"], 1840)
        self.assertEqual(block["co2_you"], 420)
        self.assertEqual(block["level"], 2)
        self.assertEqual(block["temperature_c_tenths"], 12)
        self.assertEqual(block["sea_rise_turns"], 8)
        self.assertEqual(block["tiles_flooded"], 4)
        self.assertEqual(block["storm_pct"], 12)

    def test_climate_omitted_before_industrial(self):
        self.lua.execute("""
GameClimate.GetTotalCO2Footprint = function() return 0 end
GameClimate.GetPlayerCO2Footprint = function() return 0 end
GameClimate.GetClimateChangeLevel = function() return 0 end
GameClimate.GetTemperatureChange = function() return 0 end
""")
        self.assertIsNone(self.lua.eval("Civ6Ai_Snapshot._BuildClimate(0)"))

    def test_climate_omitted_without_gathering_storm(self):
        self.lua.execute("GameClimate = nil")
        self.assertIsNone(self.lua.eval("Civ6Ai_Snapshot._BuildClimate(0)"))

    def test_power_only_cities_that_need_or_make_it(self):
        block = _to_py(self.lua.eval("Civ6Ai_Snapshot._BuildPower(0)"))
        ids = [row["city_id"] for row in block["cities"]]
        self.assertEqual(ids, ["CITY_0", "CITY_1"])
        self.assertNotIn("CITY_2", ids)
        by_id = {row["city_id"]: row for row in block["cities"]}
        self.assertFalse(by_id["CITY_0"]["powered"])
        self.assertEqual(by_id["CITY_0"]["required"], 6)
        self.assertTrue(by_id["CITY_1"]["powered"])
        self.assertEqual(block["cities_powered"], 1)
        self.assertEqual(block["cities_needing"], 2)

    def test_power_omitted_when_no_city_needs_it(self):
        self.lua.execute("POWER_CITIES = {quiet}")
        self.assertIsNone(self.lua.eval("Civ6Ai_Snapshot._BuildPower(0)"))

    def test_stockpiles_strategics_only_when_nonzero(self):
        block = _to_py(self.lua.eval("Civ6Ai_Snapshot._BuildStockpiles(0)"))
        ids = [row["resource_id"] for row in block["strategics"]]
        self.assertEqual(ids, ["RESOURCE_IRON", "RESOURCE_OIL"])
        self.assertNotIn("RESOURCE_WINE", ids)
        iron = block["strategics"][0]
        self.assertEqual(iron["amount"], 42)
        self.assertEqual(iron["cap"], 50)
        self.assertEqual(iron["per_turn"], 3)
        self.assertEqual(iron["unit_demand"], 1)
        self.assertEqual(block["strategics"][1]["power_demand"], 4)

    def test_stockpiles_omitted_without_gs_cap_api(self):
        self.lua.execute("Players[0].GetResources = function() return {GetResourceAmount = function() return 1 end} end")
        self.assertIsNone(self.lua.eval("Civ6Ai_Snapshot._BuildStockpiles(0)"))


class LateGameWireTests(unittest.TestCase):
    def test_empire_and_city_lines(self):
        snap = _gs_snapshot()
        empire = "\n".join(gs_wire.empire_lines(snap))
        self.assertIn("empire.climate.level = 2", empire)
        self.assertIn("1840 world, 420 yours", empire)
        self.assertIn("+1.2 C", empire)
        self.assertIn("8 turns to next rise", empire)
        self.assertIn("storm 12%", empire)
        self.assertIn("empire.power = 1 of 2 cities powered (Athens short 6)", empire)
        self.assertIn("empire.stockpile.iron = 42/50 (+3/turn; units 1)", empire)
        self.assertIn("empire.stockpile.oil = 8/50 (power 4)", empire)
        athens = "\n".join(gs_wire.city_lines(snap, snap["your_cities"][0], "Athens"))
        self.assertIn("Athens.power = 0+0 / 6 UNPOWERED", athens)
        attention = gs_wire.attention_items(snap)
        self.assertTrue(any("Athens" in item for item in attention))

    def test_prompt_includes_lines_and_golden_stays_quiet(self):
        snap = _gs_snapshot()
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertIn("empire.climate.co2", wire)
        self.assertIn("empire.stockpile.iron", wire)
        self.assertIn("Cities unpowered: Athens", wire)
        golden = civ6_adapter.build_classical_golden_snapshot()
        golden_wire = civ6_wire.build_civ6_model_wire_text(golden)
        self.assertNotIn("empire.climate", golden_wire)
        self.assertNotIn("empire.stockpile", golden_wire)
        self.assertNotIn("empire.power", golden_wire)

    def test_schema_accepts_gs_blocks(self):
        snap = _gs_snapshot()
        civ6_adapter.normalize_civ6_snapshot(snap)
        self.assertEqual(snap["civ6"]["climate"]["level"], 2)
        self.assertEqual(snap["civ6"]["stockpiles"]["strategics"][0]["resource_id"], "RESOURCE_IRON")


class LiveSnapshotGsSchemaTest(unittest.TestCase):
    def test_live_runtime_snapshot_still_upgrades(self):
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t1-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertNotIn("climate", snap.get("civ6", {}))


if __name__ == "__main__":
    unittest.main()
