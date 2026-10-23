"""Per-seat resource visibility: reveal tech/civic and tile knowledge."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_diplomacy, civ6_visibility

ROOT = Path(__file__).resolve().parents[2]
SNAP_LUA = ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua"


def _snap(techs, civics=(), plots=()):
    return {
        "your_empire": {"research": {"known_tech_ids": list(techs)},
                        "civics": [{"key": "known", "id": c} for c in civics]},
        "known_map": {"plots": [dict(p) for p in plots]},
    }


class PythonFilterTests(unittest.TestCase):
    def test_trajan_t20_uranium_and_oil_hidden_in_ancient_era(self):
        snap = _snap(["TECH_POTTERY", "TECH_MINING", "TECH_ASTROLOGY", "TECH_BRONZE_WORKING"], plots=[
            {"plot_id": "PLOT_53_35", "knowledge": "visible", "resource_id": "RESOURCE_URANIUM"},
            {"plot_id": "PLOT_56_36", "knowledge": "remembered", "resource_id": "RESOURCE_OIL"},
            {"plot_id": "PLOT_1_1", "knowledge": "visible", "resource_id": "RESOURCE_IRON"},
            {"plot_id": "PLOT_1_2", "knowledge": "visible", "resource_id": "RESOURCE_HORSES"},
            {"plot_id": "PLOT_1_3", "knowledge": "remembered", "resource_id": "RESOURCE_WHEAT"},
        ])
        self.assertEqual(civ6_visibility.filter_snapshot_resources(snap), 3)
        got = {p["plot_id"]: p["resource_id"] for p in snap["known_map"]["plots"]}
        self.assertEqual(got, {"PLOT_53_35": None, "PLOT_56_36": None, "PLOT_1_1": "RESOURCE_IRON",
                               "PLOT_1_2": None, "PLOT_1_3": "RESOURCE_WHEAT"})

    def test_reveal_after_tech_and_civic(self):
        snap = _snap(["TECH_COMBUSTION"], ["CIVIC_NATURAL_HISTORY"])
        self.assertTrue(civ6_visibility.resource_revealed(snap, "RESOURCE_URANIUM"))
        self.assertTrue(civ6_visibility.resource_revealed(snap, "RESOURCE_ANTIQUITY_SITE"))
        self.assertFalse(civ6_visibility.resource_revealed(snap, "RESOURCE_SHIPWRECK"))

    def test_unrevealed_tile_drops_resource(self):
        snap = _snap([], plots=[{"plot_id": "P", "knowledge": "unknown", "resource_id": "RESOURCE_WHEAT"}])
        civ6_visibility.filter_snapshot_resources(snap)
        self.assertIsNone(snap["known_map"]["plots"][0]["resource_id"])

    def test_filter_is_per_seat(self):
        plots = [{"plot_id": "P", "knowledge": "visible", "resource_id": "RESOURCE_NITER"}]
        a = _snap(["TECH_MILITARY_ENGINEERING"], plots=plots)
        b = _snap([], plots=plots)
        civ6_visibility.filter_snapshot_resources(a)
        civ6_visibility.filter_snapshot_resources(b)
        self.assertEqual(a["known_map"]["plots"][0]["resource_id"], "RESOURCE_NITER")
        self.assertIsNone(b["known_map"]["plots"][0]["resource_id"])

    def test_diplomacy_uses_shared_table(self):
        self.assertEqual(civ6_diplomacy.STRATEGIC_TECH["RESOURCE_URANIUM"], "TECH_COMBUSTION")


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LuaRevealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("Civ6Ai_Util = { Log = function() end, JsonArrayList = function() return {} end, JsonNull = function() return nil end }")
        self.lua.execute(SNAP_LUA.read_text(encoding="utf-8"))
        self.lua.execute(r"""
          GameInfo = {
            Resources = { [0] = {ResourceType='RESOURCE_URANIUM', PrereqTech='TECH_COMBUSTION', Hash=11},
                          [1] = {ResourceType='RESOURCE_WHEAT', Hash=12} },
            Technologies = { TECH_COMBUSTION = {Index=5} }, Civics = {},
          }
          function mkplayer(has, vis)
            local res = {}
            if vis ~= nil then res.IsResourceVisible = function(self, h) return vis[h] == true end end
            return { GetResources=function() return res end,
                     GetTechs=function() return { HasTech=function(self, i) return has end } end }
          end
          function plot(i) return { GetResourceType=function() return i end } end
        """)

    def name(self, pid, idx):
        return self.lua.eval(f"Civ6Ai_Snapshot._ResourceTypeName(plot({idx}), {pid})")

    def test_prereq_fallback(self):
        self.lua.execute("Players = { [0] = mkplayer(false), [1] = mkplayer(true) }")
        self.assertIsNone(self.name(0, 0))
        self.assertEqual(self.name(1, 0), "RESOURCE_URANIUM")
        self.assertEqual(self.name(0, 1), "RESOURCE_WHEAT")

    def test_engine_visibility_wins(self):
        self.lua.execute("Players = { [0] = mkplayer(true, {[12]=true}) }")
        self.assertIsNone(self.name(0, 0))
        self.assertEqual(self.name(0, 1), "RESOURCE_WHEAT")


if __name__ == "__main__":
    unittest.main()
