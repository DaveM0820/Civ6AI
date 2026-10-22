"""Regression: a real in-game turn-1 snapshot (with audit fields such as
unit health_percent, empire amenities and known_map explored_percent) must pass
the runtime schema. Sample fixtures missed this and blocked every live pulse."""
import json
import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_adapter

ROOT = Path(__file__).resolve().parents[2]
MOD = ROOT / "mod" / "Civ6Ai" / "InGame"


class LiveSnapshotSchemaTest(unittest.TestCase):
    def test_live_runtime_snapshot_upgrades(self):
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t1-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(snap["your_units"][0]["health_percent"], 100)
        self.assertIn("amenities", snap["your_empire"])
        self.assertIn("explored_percent", snap["known_map"])

    def test_live_snapshot_with_city_upgrades(self):
        # Turn-4 snapshot of a seat that founded its capital: city amenities and
        # defense.health_percent made every seat with a city fail the sidecar
        # (empty-apply fallback for all but city-less seats).
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        city = snap["your_cities"][0]
        self.assertIn("amenities", city)
        self.assertEqual(100, city["defense"]["health_percent"])

    def test_live_snapshot_accepts_charges_districts_and_audited_fields(self):
        # T123 rejected every turn: builders carry build_charges and every plot
        # carries district_id (often null). Stamp those, plus the other snapshot
        # fields added alongside them, onto a real captured turn and upgrade it.
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        raw["your_units"][0]["build_charges"] = 3
        plots = raw["known_map"]["plots"]
        for plot in plots:
            plot["district_id"] = None
        plots[1]["district_id"] = "DISTRICT_CAMPUS"
        plots[1]["improvement_pillaged"] = True
        raw["your_cities"][0]["defense"]["wall_hp"] = 80
        raw["your_cities"][0]["defense"]["wall_max_hp"] = 200
        raw["civ6"]["governance"] = {
            "in_anarchy": False,
            "anarchy_turns_left": 0,
            "change_allowed": True,
        }
        raw["civ6"]["diplomacy"] = {
            "majors": [{"player_id": "PLAYER_0", "at_war": True, "war_since_turn": 81}],
            "city_states": [{
                "player_id": "PLAYER_5",
                "your_envoys": 1,
                "suzerain_envoys": 3,
            }],
            "wars": [],
        }
        raw["legal_commands"].append({
            "command_id": "CMD_attack_UNIT_131073_50_28",
            "kind": "attack_target",
            "fixed_arguments": {
                "unit_id": "UNIT_131073",
                "target_x": 50,
                "target_y": 28,
                "target_kind": "unit",
                "ranged": False,
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_131073"],
            "runtime_status": "implemented_untested",
        })
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(3, snap["your_units"][0]["build_charges"])
        by_id = {plot["plot_id"]: plot for plot in snap["known_map"]["plots"]}
        self.assertIsNone(by_id[plots[0]["plot_id"]]["district_id"])
        campus = by_id[plots[1]["plot_id"]]
        self.assertEqual("DISTRICT_CAMPUS", campus["district_id"])
        self.assertTrue(campus["improvement_pillaged"])
        self.assertEqual(80, snap["your_cities"][0]["defense"]["wall_hp"])
        self.assertEqual(200, snap["your_cities"][0]["defense"]["wall_max_hp"])
        diplomacy = snap["civ6"]["diplomacy"]
        self.assertEqual(81, diplomacy["majors"][0]["war_since_turn"])
        self.assertEqual(3, diplomacy["city_states"][0]["suzerain_envoys"])
        self.assertFalse(snap["civ6"]["governance"]["in_anarchy"])
        attack = next(cmd for cmd in snap["legal_commands"] if cmd["kind"] == "attack_target")
        self.assertEqual("unit", attack["fixed_arguments"]["target_kind"])
        self.assertIs(False, attack["fixed_arguments"]["ranged"])

    @unittest.skipIf(LuaRuntime is None, "lupa not installed")
    def test_lua_snapshot_writers_validate_against_schemas(self):
        # Stamping a captured fixture missed embark_site (and, before that,
        # build_charges and district_id). Build the records with the current
        # snapshot Lua and run them through the live sidecar validator, so a
        # new field fails here until schemas/ allows it.
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute((MOD / "Civ6Ai_Util.lua").read_text(encoding="utf-8"))
        lua.execute((MOD / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))
        lua.execute(r"""
            local function rows(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  return list[i]
                end
              end
            end
            local function members(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  if list[i] then return i, list[i] end
                end
              end
            end
            Game = {
              GetCurrentGameTurn = function() return 4 end,
              GetLocalPlayer = function() return 0 end,
              GetProperty = function() return nil end,
            }
            Locale = { Lookup = function(text) return tostring(text) end }
            Civ6Ai_Production = {
              _GetCityProductionState = function() return nil, 0, 0, 0, nil end,
              _WireCityId = function(city) return "CITY_" .. tostring(city:GetID()) end,
            }
            GameInfo = {
              Units = {
                [0] = { UnitType = "UNIT_SETTLER", FoundCity = true, FormationClass = "FORMATION_CLASS_CIVILIAN", Domain = "DOMAIN_LAND" },
                [1] = { UnitType = "UNIT_BUILDER", FormationClass = "FORMATION_CLASS_CIVILIAN", Domain = "DOMAIN_LAND" },
              },
              Technologies = { TECH_SHIPBUILDING = { Index = 4 }, TECH_CARTOGRAPHY = { Index = 8 } },
              Terrains = rows({ { Index = 0, TerrainType = "TERRAIN_GRASS" } }),
              Districts = { [3] = { DistrictType = "DISTRICT_CAMPUS" } },
            }
            Map = {
              GetPlot = function(x, y)
                if not ((x == 10 and y == 10) or (x == 22 and y == 10) or (x == 4 and y == 5)) then
                  return nil
                end
                return {
                  GetX = function() return x end,
                  GetY = function() return y end,
                  GetIndex = function() return x * 100 + y end,
                  IsWater = function() return false end,
                  IsImpassable = function() return false end,
                  IsFreshWater = function() return false end,
                  IsRiver = function() return false end,
                  IsHills = function() return false end,
                  IsMountain = function() return false end,
                  IsNaturalWonder = function() return false end,
                  GetOwner = function() return -1 end,
                  GetTerrainType = function() return 0 end,
                  GetFeatureType = function() return -1 end,
                  GetResourceType = function() return -1 end,
                  GetImprovementType = function() return -1 end,
                  GetDistrictType = function() return (x == 4 and y == 5) and 3 or -1 end,
                  IsImprovementPillaged = function() return x == 4 and y == 5 end,
                  GetArea = function() return { GetID = function() return (x == 22) and 2 or 1 end } end,
                }
              end,
              GetPlotDistance = function(ax, ay, bx, by)
                return math.max(math.abs(ax - bx), math.abs(ay - by))
              end,
            }
            local city = {
              GetID = function() return 9 end,
              GetX = function() return 10 end,
              GetY = function() return 10 end,
              GetName = function() return "Rome" end,
              IsCapital = function() return true end,
              GetPopulation = function() return 2 end,
              GetMaxHitPoints = function() return 200 end,
              GetDamage = function() return 20 end,
            }
            local function unit(id, typ, x, y, charges)
              return {
                GetOwner = function() return 1 end,
                GetID = function() return id end,
                GetType = function() return typ end,
                GetX = function() return x end,
                GetY = function() return y end,
                GetMovesRemaining = function() return 2 end,
                GetMaxMoves = function() return 2 end,
                GetBuildCharges = function() return charges end,
              }
            end
            local settler = unit(7, 0, 10, 10, 0)
            local builder = unit(8, 1, 4, 5, 3)
            Players = {}
            for pid = 0, 3 do
              Players[pid] = { GetCities = function() return { Members = members({}) } end }
            end
            Players[0].GetCities = function() return { Members = members({ city }) } end
            Players[1].GetCities = function() return { Members = members({ city }) } end
            Players[1].GetUnits = function() return { Members = members({ settler, builder }) } end
            Players[1].GetTechs = function()
              return { HasTech = function(_, idx) return idx == 4 end }
            end
            PlayersVisibility = { [1] = { IsRevealed = function() return true end, IsVisible = function() return true end } }
            ExposedMembers = { Civ6Ai = {
              CanFoundCityForPlayer = function() return false, "unit_cannot_found_city" end,
            } }
            local units = Civ6Ai_Snapshot._BuildYourUnits(1)
            local plot = Civ6Ai_Snapshot._BuildPlotRecord(Map.GetPlot(4, 5), 1, 4, PlayersVisibility[1])
            local cities = Civ6Ai_Snapshot._BuildYourCities(1)
            ENCODED = Civ6Ai_Util.EncodeJsonObject({ units = units, plot = plot, cities = cities })
        """)
        generated = json.loads(lua.globals().ENCODED)
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        raw["your_units"] = generated["units"]
        raw["your_cities"] = generated["cities"]
        raw["known_map"]["plots"] = [generated["plot"]]
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        civ6_adapter.validate_civ6_snapshot(snap)
        settler = next(unit for unit in snap["your_units"] if unit["unit_type_id"] == "UNIT_SETTLER")
        embark = settler["settle"]["embark_site"]
        self.assertEqual(22, embark["x"])
        self.assertEqual(10, embark["y"])
        self.assertIs(True, embark["can_embark"])
        self.assertIs(False, embark["can_ocean"])
        self.assertTrue(settler["settle"]["no_reachable_site"])
        builder = next(unit for unit in snap["your_units"] if unit["unit_type_id"] == "UNIT_BUILDER")
        self.assertEqual(3, builder["build_charges"])
        plot = snap["known_map"]["plots"][0]
        self.assertEqual("DISTRICT_CAMPUS", plot["district_id"])
        self.assertIs(True, plot["improvement_pillaged"])
        self.assertIn("wall_hp", snap["your_cities"][0]["defense"])


if __name__ == "__main__":
    unittest.main()
