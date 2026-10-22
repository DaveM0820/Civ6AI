"""Local autotest production queue scored from the existing build-priority lists."""
from __future__ import annotations

import unittest
from pathlib import Path

from sidecar import civ6_economy as economy
from sidecar import civ6_priorities as prio

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover - optional dev dependency
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Production.lua"


def _cand(type_id: str, row: dict | None = None) -> dict:
    tags, kind = prio.tags_for_item(type_id, row)
    return {"id": type_id, "tags": tags, "kind": kind}


def _basic():
    return [
        _cand("UNIT_SETTLER"),
        _cand("BUILDING_GRANARY"),
        _cand("BUILDING_MONUMENT"),
        _cand("UNIT_WARRIOR", {"combat": 20}),
        _cand("UNIT_ARCHER", {"ranged": 25, "combat": 15}),
        _cand("BUILDING_WALLS"),
    ]


class ProductionScoreTests(unittest.TestCase):
    def test_peace_early_city_picks_a_settler_from_the_expansion_list(self):
        situation = prio.compose_situation(
            cities=1, pop=2, land=True, turn=10, era=0, builders=1, military=1,
            missing_monument=True, missing_granary=True,
        )
        scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
        self.assertEqual(115, scores["UNIT_SETTLER"])
        self.assertEqual(25, scores["BUILDING_GRANARY"])
        self.assertEqual(20, scores["BUILDING_MONUMENT"])
        self.assertEqual(-20, scores["UNIT_WARRIOR"])
        self.assertEqual(("UNIT_SETTLER", 115), prio.pick_build(_basic(), situation))

    def test_major_war_uses_the_war_list_and_breaks_ties_by_type_id(self):
        situation = prio.compose_situation(
            major_wars=1, cities=3, pop=4, land=True, turn=40, era=0,
            builders=3, military=6,
        )
        scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
        self.assertEqual(30, scores["UNIT_ARCHER"])
        self.assertEqual(30, scores["UNIT_WARRIOR"])
        self.assertEqual(-5, scores["BUILDING_MONUMENT"])
        self.assertEqual(-45, scores["UNIT_SETTLER"])
        self.assertEqual("UNIT_ARCHER", prio.pick_build(_basic(), situation)[0])

    def test_short_army_at_war_adds_the_defense_list(self):
        situation = prio.compose_situation(
            major_wars=1, cities=3, pop=4, land=True, turn=40, era=0,
            builders=3, military=1,
        )
        scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
        self.assertEqual(100, scores["BUILDING_WALLS"])
        self.assertEqual(75, scores["UNIT_ARCHER"])
        self.assertEqual(60, scores["UNIT_WARRIOR"])
        self.assertEqual("BUILDING_WALLS", prio.pick_build(_basic(), situation)[0])

    def test_warlike_peace_adds_half_the_war_list(self):
        situation = prio.compose_situation(
            warlike=True, cities=4, pop=3, land=True, turn=20, era=0,
            builders=4, military=5,
        )
        self.assertTrue(situation["half_war"])
        self.assertNotIn(prio.BY_KEY["war"]["id"], situation["levels"])
        scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
        # peace combat -20 plus floor(50 / 2); peace culture 5 plus floor(-10 / 2).
        self.assertEqual(5, scores["UNIT_WARRIOR"])
        self.assertEqual(0, scores["BUILDING_MONUMENT"])
        self.assertEqual(-35, scores["UNIT_SETTLER"])
        self.assertGreater(scores["UNIT_WARRIOR"], -20)
        self.assertEqual("UNIT_WARRIOR", prio.pick_build(
            [_cand("UNIT_WARRIOR", {"combat": 20}), _cand("BUILDING_MONUMENT")], situation,
        )[0])

    def test_half_of_a_negative_war_weight_floors(self):
        weights = prio.weight_vector({}, half_war=True)
        self.assertEqual(-8, weights["PSEUDOYIELD_IMPROVEMENT"])
        self.assertEqual(-10, weights["PSEUDOYIELD_UNIT_SETTLER"])

    def test_repeating_the_last_item_loses_to_the_other_military_type(self):
        situation = prio.compose_situation(
            major_wars=1, cities=3, pop=4, land=True, turn=40, era=0,
            builders=3, military=6, last="UNIT_WARRIOR",
        )
        scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
        self.assertEqual(-20, scores["UNIT_WARRIOR"])
        self.assertEqual(30, scores["UNIT_ARCHER"])
        self.assertEqual("UNIT_ARCHER", prio.pick_build(_basic(), situation)[0])

    def test_no_land_or_low_population_blocks_the_settler(self):
        low = prio.compose_situation(
            cities=1, pop=1, land=True, turn=10, era=0, builders=1, military=1,
            missing_granary=True, missing_monument=True,
        )
        blocked = prio.compose_situation(
            cities=1, pop=2, land=False, turn=10, era=0, builders=1, military=1,
            missing_granary=True,
        )
        for situation in (low, blocked):
            scores = {c["id"]: prio.item_score(c["id"], c["tags"], situation, c["kind"]) for c in _basic()}
            self.assertLess(scores["UNIT_SETTLER"], scores["BUILDING_GRANARY"])
            self.assertEqual("BUILDING_GRANARY", prio.pick_build(_basic(), situation)[0])

    def test_a_city_state_war_does_not_turn_on_the_war_list(self):
        snap = {
            "decision": {"turn": 40},
            "known_players": [{
                "player_id": "PLAYER_2", "leader_id": "LEADER_MINOR_CIV_AMSTERDAM",
                "relation": {"at_war": True},
            }],
            "your_cities": [{"city_id": "CITY_1", "population": 4, "plot_id": "PLOT_1_1"}],
            "your_units": [{"unit_id": "UNIT_1", "unit_type_id": "UNIT_WARRIOR"}],
            "civ6": {"priorities": []},
        }
        situation = prio.situation_for_city(snap, snap["your_cities"][0])
        self.assertNotIn(prio.BY_KEY["war"]["id"], situation["levels"])
        warrior = _cand("UNIT_WARRIOR", {"combat": 20})
        self.assertEqual(-20, prio.item_score(warrior["id"], warrior["tags"], situation, warrior["kind"]))

    def test_saved_defense_is_not_downgraded(self):
        defense = prio.BY_KEY["defense"]["id"]
        situation = prio.compose_situation(saved={defense: 3}, threatened=True, military=5, cities=1)
        self.assertEqual(3, situation["levels"][defense])
        walls = _cand("BUILDING_WALLS")
        self.assertEqual(400, prio.item_score(walls["id"], walls["tags"], situation, walls["kind"]))

    def test_prompt_says_the_test_seat_uses_the_same_lists(self):
        lines = "\n".join(prio.prompt_lines({"civ6": {"priorities": []}}))
        self.assertIn("these same lists", lines)
        self.assertIn("warlike leader", lines)
        self.assertIn("too few cities", lines)
        self.assertIn("Nothing will be queued for you", "\n".join(economy.attention_items({
            "your_cities": [{"city_id": "CITY_1", "name": "Utrecht", "production": {"item_id": "NONE"}}],
            "civ6": {"priorities": []},
        })))

    def test_unthreatened_catalog_follows_the_peace_list(self):
        snap = {
            "decision": {"turn": 120},
            "game": {"map_width": 20, "map_height": 20},
            "your_cities": [{
                "city_id": "CITY_1", "name": "Utrecht", "plot_id": "PLOT_1_1", "population": 3,
                "buildings": ["BUILDING_MONUMENT", "BUILDING_GRANARY"],
                "districts": ["DISTRICT_CAMPUS"],
            }],
            "your_units": [
                {"unit_id": "UNIT_1", "unit_type_id": "UNIT_WARRIOR"},
                {"unit_id": "UNIT_2", "unit_type_id": "UNIT_BUILDER"},
            ],
            "civ6": {"priorities": [], "combat": {"hostiles": []}, "economy": {"build_catalog": {
                "UNIT_WARRIOR": {"category": "unit", "combat": 20, "cost": 40},
                "BUILDING_BARRACKS": {"category": "building", "cost": 80},
                "PROJECT_ENHANCE_DISTRICT": {"category": "project", "cost": 50},
            }}},
        }
        lines = economy.production_catalog_lines(snap, {"CITY_1": {"production": [
            "UNIT_WARRIOR", "BUILDING_BARRACKS", "PROJECT_ENHANCE_DISTRICT",
        ]}})
        catalog = next(line for line in lines if "production.catalog" in line)
        self.assertNotIn("THREATENED", catalog)
        self.assertLess(catalog.index("BUILDING_BARRACKS"), catalog.index("PROJECT_ENHANCE_DISTRICT"))
        self.assertLess(catalog.index("PROJECT_ENHANCE_DISTRICT"), catalog.index("UNIT_WARRIOR"))

    def test_generated_weights_are_the_priority_lists(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import gen_priorities

        text = PRODUCTION.read_text(encoding="utf-8")
        self.assertNotIn("WAR_PROFILE", text)
        self.assertNotIn("PEACE_PROFILE", text)
        self.assertIn("not an ordered", text)
        self.assertIn(gen_priorities.production_weight_block(), text)
        self.assertIn("PSEUDOYIELD_UNIT_COMBAT = -20", text.split("PRIORITY_GROUP", 1)[0])


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class ProductionLuaScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(PRODUCTION.read_text(encoding="utf-8"))

    def test_lua_pick_matches_python_on_the_same_lists(self):
        cases = [
            dict(cities=1, pop=2, land=True, turn=10, era=0, builders=1, military=1,
                 missing_monument=True, missing_granary=True),
            dict(major_wars=1, cities=3, pop=4, land=True, turn=40, era=0, builders=3, military=6),
            dict(major_wars=1, cities=3, pop=4, land=True, turn=40, era=0, builders=3, military=6,
                 last="UNIT_WARRIOR"),
            dict(warlike=True, cities=4, pop=3, land=True, turn=20, era=0, builders=4, military=5),
            dict(cities=1, pop=1, land=True, turn=10, era=0, builders=1, military=1, missing_granary=True),
        ]
        for raw in cases:
            situation = prio.compose_situation(**raw)
            fields = ", ".join(
                f"{key} = {self._lua(value)}" for key, value in raw.items()
            )
            picked, score = self.lua.execute(
                "local situation = Civ6Ai_Production.ComposeSituation({" + fields + "})\n"
                "local candidates = {\n"
                "  { id = 'UNIT_SETTLER', tags = {'PSEUDOYIELD_UNIT_SETTLER'}, kind = 'unit' },\n"
                "  { id = 'BUILDING_GRANARY', tags = {'YIELD_FOOD'}, kind = 'building' },\n"
                "  { id = 'BUILDING_MONUMENT', tags = {'YIELD_CULTURE'}, kind = 'building' },\n"
                "  { id = 'UNIT_WARRIOR', tags = {'PSEUDOYIELD_UNIT_COMBAT', 'PROMOTION_CLASS_MELEE'}, kind = 'unit' },\n"
                "  { id = 'UNIT_ARCHER', tags = {'PSEUDOYIELD_UNIT_COMBAT', 'PROMOTION_CLASS_RANGED'}, kind = 'unit' },\n"
                "  { id = 'BUILDING_WALLS', tags = {'PSEUDOYIELD_CITY_DEFENSES'}, kind = 'building' },\n"
                "}\n"
                "return Civ6Ai_Production.PickBuild(candidates, situation)\n"
            )
            self.assertEqual(prio.pick_build(_basic(), situation), (picked, score), raw)

    def test_lua_tags_follow_the_same_gameinfo_fields(self):
        self.lua.execute(
            """
            local function rows(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  return list[i]
                end
              end
            end
            GameInfo = {
              Units = rows({
                { UnitType = "UNIT_WARRIOR", Combat = 20 },
                { UnitType = "UNIT_ARCHER", Combat = 15, RangedCombat = 25, PromotionClass = "PROMOTION_CLASS_RANGED" },
                { UnitType = "UNIT_SETTLER", FoundCity = true },
                { UnitType = "UNIT_BUILDER", BuildCharges = 3 },
                { UnitType = "UNIT_SCOUT", PromotionClass = "PROMOTION_CLASS_RECON", Combat = 10 },
                { UnitType = "UNIT_AZTEC_EAGLE_WARRIOR", TraitType = "TRAIT_LEGEND", Combat = 28 },
              }),
              Buildings = rows({
                { BuildingType = "BUILDING_MONUMENT" },
                { BuildingType = "BUILDING_GRANARY", Housing = 2 },
                { BuildingType = "BUILDING_WALLS" },
                { BuildingType = "BUILDING_LIBRARY", PrereqDistrict = "DISTRICT_CAMPUS" },
              }),
              Building_YieldChanges = rows({
                { BuildingType = "BUILDING_LIBRARY", YieldType = "YIELD_SCIENCE", YieldChange = 2 },
              }),
              Districts = rows({ { DistrictType = "DISTRICT_ACROPOLIS" } }),
              DistrictReplaces = rows({
                { CivUniqueDistrictType = "DISTRICT_ACROPOLIS", ReplacesDistrictType = "DISTRICT_THEATER" },
              }),
              CivilizationTraits = rows({
                { CivilizationType = "CIVILIZATION_AZTEC", TraitType = "TRAIT_LEGEND" },
              }),
              LeaderTraits = rows({}),
              AiLists = rows({ { ListType = "GILGAMESH", LeaderType = "LEADER_GILGAMESH" } }),
              AiFavoredItems = rows({
                { ListType = "GILGAMESH", Item = "PSEUDOYIELD_UNIT_COMBAT", Value = 25 },
                { ListType = "PEACEFUL", Item = "PSEUDOYIELD_UNIT_COMBAT", Value = -10 },
              }),
            }
            PlayerConfigurations = {
              [0] = {
                GetCivilizationTypeName = function() return "CIVILIZATION_AZTEC" end,
                GetLeaderTypeName = function() return "LEADER_MONTEZUMA" end,
              },
              [1] = {
                GetCivilizationTypeName = function() return "CIVILIZATION_SUMERIA" end,
                GetLeaderTypeName = function() return "LEADER_GILGAMESH" end,
              },
            }
            Game = { GetCurrentGameTurn = function() return 4 end }
            """
        )
        samples = {
            "UNIT_WARRIOR": {"Combat": 20},
            "UNIT_ARCHER": {"Combat": 15, "RangedCombat": 25, "PromotionClass": "PROMOTION_CLASS_RANGED"},
            "UNIT_SETTLER": {"FoundCity": True},
            "UNIT_BUILDER": {"BuildCharges": 3},
            "UNIT_SCOUT": {"PromotionClass": "PROMOTION_CLASS_RECON", "Combat": 10},
            "BUILDING_MONUMENT": {},
            "BUILDING_GRANARY": {"Housing": 2},
            "BUILDING_WALLS": {},
            "BUILDING_LIBRARY": {"PrereqDistrict": "DISTRICT_CAMPUS", "yield_changes": {"YIELD_SCIENCE": 2}},
            "DISTRICT_ACROPOLIS": {"ReplacesDistrictType": "DISTRICT_THEATER"},
        }
        for type_id, row in samples.items():
            count = int(self.lua.eval(f"#Civ6Ai_Production._TagsFor('{type_id}')"))
            lua_tags = [self.lua.eval(f"Civ6Ai_Production._TagsFor('{type_id}')[{i}]") for i in range(1, count + 1)]
            self.assertEqual(prio.tags_for_item(type_id, row)[0], lua_tags, type_id)
        self.assertTrue(self.lua.eval("Civ6Ai_Production._Warlike(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Production._Warlike(1)"))

    def test_autotest_queue_picks_from_the_lists_and_a_real_game_does_not(self):
        queued, build = self.lua.execute(
            """
            Civ6Ai_Config = { IsAutotest = function() return false end }
            if Civ6Ai_Production.AutoqueueEmptyCities(0) ~= 0 then return -1, "gated" end
            Civ6Ai_Config.IsAutotest = function() return true end
            local city = {
              GetID = function() return 7 end,
              GetX = function() return 2 end,
              GetY = function() return 2 end,
              GetPopulation = function() return 2 end,
              GetBuildQueue = function()
                return {
                  GetSize = function() return 0 end,
                  CanProduce = function() return true end,
                  GetCurrentProductionTypeHash = function() return 0 end,
                }
              end,
            }
            Players = {
              [0] = {
                IsAlive = function() return true end,
                IsMajor = function() return true end,
                GetDiplomacy = function() return { IsAtWarWith = function() return false end } end,
                GetCities = function()
                  return { Members = function()
                    local i = 0
                    return function()
                      i = i + 1
                      if i == 1 then return i, city end
                    end
                  end }
                end,
                GetUnits = function() return { Members = function() return function() end end } end,
              },
            }
            PlayerConfigurations = {}
            Game = {
              GetLocalPlayer = function() return 0 end,
              GetCurrentGameTurn = function() return 10 end,
              GetProperty = function() return nil end,
            }
            GameInfo = {
              Units = function()
                local rows = {
                  { UnitType = "UNIT_SETTLER", Hash = 11, FoundCity = true },
                  { UnitType = "UNIT_WARRIOR", Hash = 12, Combat = 20 },
                }
                local i = 0
                return function() i = i + 1; return rows[i] end
              end,
              Buildings = function()
                local rows = { { BuildingType = "BUILDING_MONUMENT", Hash = 21 } }
                local i = 0
                return function() i = i + 1; return rows[i] end
              end,
              Districts = function() return function() end end,
              Projects = function() return function() end end,
            }
            CityManager = {
              CanStartOperation = function() return true end,
              RequestOperation = function()
                city.GetBuildQueue = function()
                  return {
                    GetSize = function() return 1 end,
                    GetCurrentProductionTypeHash = function() return 11 end,
                  }
                end
                return true
              end,
            }
            CityOperationTypes = { BUILD = 1, PARAM_UNIT_TYPE = "unit", PARAM_INSERT_MODE = "mode", VALUE_EXCLUSIVE = 1 }
            local n = Civ6Ai_Production.AutoqueueEmptyCities(0)
            return n, Civ6Ai_Production._GetCityProduction(city)
            """
        )
        self.assertEqual(1, queued)
        self.assertEqual("UNIT_SETTLER", build)
        self.assertEqual(0, self.lua.eval("Civ6Ai_Production.AutoqueueEmptyCities(1)"))

    def test_nil_request_waits_for_the_next_pass_before_not_stuck(self):
        first, second, missed, later, counts, log = self.lua.execute(
            """
            local logs = {}
            local requests = 0
            Civ6Ai_Util = { Log = function(line) logs[#logs + 1] = line end }
            Civ6Ai_Config = { IsAutotest = function() return true end }
            local hash = 0
            local city = {
              GetID = function() return 7 end,
              GetX = function() return 2 end,
              GetY = function() return 2 end,
              GetPopulation = function() return 2 end,
              GetBuildQueue = function()
                return {
                  GetSize = function() return hash == 0 and 0 or 1 end,
                  CanProduce = function() return true end,
                  GetCurrentProductionTypeHash = function() return hash end,
                }
              end,
            }
            Players = {
              [0] = {
                IsAlive = function() return true end,
                IsMajor = function() return true end,
                GetDiplomacy = function() return { IsAtWarWith = function() return false end } end,
                GetCities = function()
                  return { Members = function()
                    local i = 0
                    return function()
                      i = i + 1
                      if i == 1 then return i, city end
                    end
                  end }
                end,
                GetUnits = function() return { Members = function() return function() end end } end,
              },
            }
            PlayerConfigurations = {}
            Game = {
              GetLocalPlayer = function() return 0 end,
              GetCurrentGameTurn = function() return 10 end,
              GetProperty = function() return nil end,
            }
            GameInfo = {
              Units = function()
                local rows = { { UnitType = "UNIT_SETTLER", Hash = 11, FoundCity = true } }
                local i = 0
                return function() i = i + 1; return rows[i] end
              end,
              Buildings = function() return function() end end,
              Districts = function() return function() end end,
              Projects = function() return function() end end,
            }
            CityManager = {
              CanStartOperation = function() return true end,
              RequestOperation = function()
                requests = requests + 1
                return nil
              end,
            }
            CityOperationTypes = { BUILD = 1, PARAM_UNIT_TYPE = "unit", PARAM_INSERT_MODE = "mode", VALUE_EXCLUSIVE = 1 }
            local function joined()
              return table.concat(logs, "\\n")
            end
            Civ6Ai_Production.BeginQueuePass()
            local same1 = Civ6Ai_Production.AutoqueueEmptyCities(0)
            local same2 = Civ6Ai_Production.AutoqueueEmptyCities(0)
            Civ6Ai_Production.EndQueuePass()
            local afterSame = requests
            local afterSameLog = joined()
            local missed = Civ6Ai_Production.AutoqueueEmptyCities(0)
            local afterMiss = requests
            local afterMissLog = joined()
            hash = 11
            local later = Civ6Ai_Production.AutoqueueEmptyCities(0)
            return same1, same2, missed, later,
              afterSame .. ":" .. afterMiss .. ":" .. tostring(requests),
              afterSameLog .. "||" .. afterMissLog .. "||" .. joined()
            """
        )
        self.assertEqual(0, first)
        self.assertEqual(0, second)
        self.assertEqual(0, missed)
        self.assertEqual(1, later)
        same_requests, miss_requests, total_requests = counts.split(":")
        self.assertEqual(("1", "2", "2"), (same_requests, miss_requests, total_requests))
        same_log, miss_log, full_log = log.split("||")
        self.assertNotIn("not_stuck", same_log)
        self.assertNotIn("production|autoqueue|player=", same_log)
        self.assertIn("production|autoqueue|not_stuck|city=7|wanted=UNIT_SETTLER|current=nil|result=nil", miss_log)
        self.assertNotIn("production|autoqueue|player=", miss_log)
        self.assertIn("production|autoqueue|player=0|city=7|build=UNIT_SETTLER|turn=10", full_log)

    @staticmethod
    def _lua(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return "'" + value.replace("'", "") + "'"
        return str(int(value))


if __name__ == "__main__":
    unittest.main()
