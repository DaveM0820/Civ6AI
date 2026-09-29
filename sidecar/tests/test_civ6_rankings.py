"""World Rankings: civ6.rankings Lua builder (mocked engine; lupa) and the WORLD RANKINGS wire section."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from sidecar import civ6_rankings_wire as rankings_wire
from sidecar import civ6_wire

ROOT = Path(__file__).resolve().parents[2]
INGAME = ROOT / "mod" / "Civ6Ai" / "InGame"

MOCKS = r"""
Locale = {Lookup = function(s) return s end}
local function gameinfo(rows, key)
  local t = {}
  for i, r in ipairs(rows) do r.Index = i - 1; t[r[key]] = r; t[i - 1] = r end
  return t
end
GameInfo = {
  Projects = gameinfo({{ProjectType = "PROJECT_LAUNCH_EARTH_SATELLITE"}, {ProjectType = "PROJECT_LAUNCH_MOON_LANDING"}}, "ProjectType"),
  Districts = gameinfo({{DistrictType = "DISTRICT_SPACEPORT"}}, "DistrictType"),
  Religions = gameinfo({{ReligionType = "RELIGION_PANTHEON"}, {ReligionType = "RELIGION_BUDDHISM", Name = "LOC_BUDDHISM"}}, "ReligionType"),
  Victories = gameinfo({{VictoryType = "VICTORY_TECHNOLOGY"}}, "VictoryType"),
  Governors = gameinfo({{GovernorType = "GOVERNOR_THE_EDUCATOR"}}, "GovernorType"),
}
Game = {
  IsVictoryEnabled = function(v) return v ~= "VICTORY_DIPLOMATIC" end,
  GetVictoryProgressForTeam = function(v, team) if v == "VICTORY_TECHNOLOGY" then return 0 end return nil end,
  GetReligion = function() return {GetName = function(self, t) return "Buddhism" end} end,
}
local function mk(id, d)
  local stats = {
    GetNumTechsResearched = function() return d.techs end,
    GetTourism = function() return d.tourism end,
    GetMilitaryStrengthWithoutTreasury = function() return d.mil end,
    GetNumCitiesFollowingReligion = function() return d.follow end,
    GetNumProjectsAdvanced = function(self, idx) if d.space and idx == 0 then return 1 end return 0 end,
  }
  local culture = {
    GetCultureYield = function() return d.culture end,
    GetStaycationers = function() return d.stay end,
    GetTouristsTo = function() return d.to end,
    GetTouristsFrom = function(self, other) return 1 end,
    IsDominantOver = function() return false end,
  }
  local city = {
    IsOriginalCapital = function() return true end,
    GetOriginalOwner = function() return d.capOwner or id end,
  }
  local cities = {
    GetCapitalCity = function() return city end,
    Members = function() local done = false; return function() if not done then done = true; return 1, city end end end,
  }
  return {
    GetID = function() return id end, IsAlive = function() return true end, IsMajor = function() return true end,
    IsBarbarian = function() return false end,
    GetTeam = function() return id end, GetScore = function() return d.score end,
    GetStats = function() return stats end, GetCulture = function() return culture end,
    GetTechs = function() return {GetScienceYield = function() return d.sci end} end,
    GetReligion = function() return {
      GetFaithYield = function() return d.faith end,
      GetReligionTypeCreated = function() return d.founded or -1 end,
      GetReligionInMajorityOfCities = function() return d.majority or -1 end,
    } end,
    GetFavor = function() return d.favor end,
    GetFavorPerTurn = function() return d.favor and 2 or nil end,
    GetDiplomacy = function() return {HasMet = function(self, o) return d.meets and d.meets[o] or false end,
                                      GetFavor = function() return 0 end} end,
    GetCities = function() return cities end,
    GetDistricts = function() return {Members = function() return function() return nil end end} end,
  }
end
Players = {}
Players[0] = mk(0, {techs = 3, tourism = 0, mil = 40, follow = 0, culture = 2.5, stay = 0, to = 0, score = 20, sci = 4.2, faith = 1, favor = 7, meets = {[1] = true}, majority = 1})
Players[1] = mk(1, {techs = 5, tourism = 1, mil = 60, follow = 2, culture = 3, stay = 2, to = 0, score = 25, sci = 6, faith = 3, founded = 1, majority = 1, space = true})
Players[2] = mk(2, {techs = 4, tourism = 0, mil = 30, follow = 0, culture = 1, stay = 1, to = 0, score = 18, sci = 5, faith = 0, capOwner = 0})
PlayerManager = {GetAliveMajors = function() return {Players[0], Players[1], Players[2]} end}
PlayerConfigurations = {}
for i = 0, 2 do
  PlayerConfigurations[i] = {GetLeaderName = function() return "Leader" .. i end,
    GetCivilizationTypeName = function() return "CIVILIZATION_C" .. i end,
    GetLeaderTypeName = function() return "LEADER_L" .. i end}
end
Civ6Ai_Util = {}
function Civ6Ai_Util.JsonArrayList() return {} end
function Civ6Ai_Util.JsonNull() return "NULL" end
function Civ6Ai_Util.PlayerId(i) return "PLAYER_" .. tostring(i) end
function Civ6Ai_Util.Log(s) LOGGED = (LOGGED or "") .. s .. "\n" end
"""


def _to_py(value):
    if hasattr(value, "items") and not isinstance(value, (str, bytes, dict)):
        items = list(value.items())
        if items and all(isinstance(k, int) for k, _ in items):
            return [_to_py(v) for _, v in sorted(items)]
        return {k: _to_py(v) for k, v in items}
    return value


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LuaRankingsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute((INGAME / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))

    def test_rankings_block(self):
        block = _to_py(self.lua.eval("Civ6Ai_Snapshot._BuildRankings(0)"))
        self.assertEqual(block["ruleset"], "EXPANSION1")
        self.assertEqual(block["you"], "PLAYER_0")
        rows = {r["player_id"]: r for r in block["players"]}
        self.assertEqual(set(rows), {"PLAYER_0", "PLAYER_1", "PLAYER_2"})
        me, p1, p2 = rows["PLAYER_0"], rows["PLAYER_1"], rows["PLAYER_2"]
        self.assertTrue(me["is_you"])
        self.assertTrue(p1["met"])
        self.assertFalse(p2["met"])
        self.assertNotIn("leader_name", p2)  # unmet: no identity
        self.assertEqual(p1["techs_researched"], 5)
        self.assertEqual(me["science_yield"], 4.2)
        self.assertEqual(me["culture_yield"], 2.5)
        self.assertEqual(p1["military_strength"], 60)
        self.assertEqual(me["tourists_needed"], 3)  # one more than P1's 2 domestic tourists
        self.assertEqual(p1["space_projects_done"], 1)
        self.assertEqual(p1["space_projects_total"], 2)
        self.assertEqual(p1["religion_founded"]["id"], "RELIGION_BUDDHISM")
        self.assertEqual(p1["religion_founded"]["name"], "Buddhism")
        self.assertEqual(p1["civs_converted"], ["PLAYER_0", "PLAYER_1"])
        self.assertEqual(p2["captured_capitals"], ["PLAYER_0"])
        self.assertTrue(me["has_original_capital"])
        self.assertEqual(me["victory_progress"], {"VICTORY_TECHNOLOGY": 0})
        self.assertFalse(block["victories_enabled"]["VICTORY_DIPLOMATIC"])
        self.assertNotIn("diplomatic_vp", me)
        self.assertEqual(me["favor"], 7)  # player:GetFavor() (Gathering Storm API)
        self.assertEqual(me["favor_per_turn"], 2)
        self.assertEqual(p1["favor"], 0)  # falls back to diplomacy:GetFavor()  # base/XP1 engine has no such method

    def test_missing_methods_never_raise(self):
        self.lua.execute("GameInfo.Governors = nil; Game.GetVictoryProgressForTeam = nil; Players[1].GetStats = nil")
        block = _to_py(self.lua.eval("Civ6Ai_Snapshot._BuildRankings(0)"))
        self.assertEqual(block["ruleset"], "BASE")
        rows = {r["player_id"]: r for r in block["players"]}
        self.assertNotIn("techs_researched", rows["PLAYER_1"])
        self.assertEqual(rows["PLAYER_1"]["science_yield"], 6)


def _context(ruleset="EXPANSION1"):
    return {
        "known_players": [{"player_id": "PLAYER_1", "leader_name": "Trajan", "civilization_id": "CIVILIZATION_ROME"}],
        "civ6": {"rankings": {
            "ruleset": ruleset, "you": "PLAYER_0", "diplomatic_vp_needed": 20 if ruleset == "EXPANSION2" else None,
            "victories_enabled": {"VICTORY_TECHNOLOGY": True, "VICTORY_CULTURE": True, "VICTORY_CONQUEST": True,
                                  "VICTORY_RELIGIOUS": False},
            "players": [
                {"player_id": "PLAYER_0", "is_you": True, "met": True, "score": 20, "techs_researched": 3,
                 "science_yield": 4.2, "culture_yield": 2.5, "tourism": 0, "domestic_tourists": 0,
                 "foreign_tourists": 0, "tourists_needed": 3, "military_strength": 40, "faith_yield": 1,
                 "cities_following_religion": 0, "has_original_capital": True, "space_projects_done": 0,
                 "space_projects_total": 2,
                 "victory_progress": {"VICTORY_TECHNOLOGY": 0}},
                {"player_id": "PLAYER_1", "met": True, "leader_name": "Trajan", "civilization_id": "CIVILIZATION_ROME",
                 "score": 25, "techs_researched": 5, "science_yield": 6, "culture_yield": 3, "tourism": 1,
                 "domestic_tourists": 2, "foreign_tourists": 0, "tourists_needed": 1, "military_strength": 60,
                 "faith_yield": 3, "cities_following_religion": 2, "religion_founded": {"id": "RELIGION_BUDDHISM", "name": "Buddhism"},
                 "civs_converted": ["PLAYER_0", "PLAYER_1"], "has_original_capital": True,
                 "your_tourists_visiting_them": 0, "their_tourists_visiting_you": 1,
                 "victory_progress": {"VICTORY_TECHNOLOGY": 0}},
                {"player_id": "PLAYER_2", "met": False, "score": 18, "techs_researched": 4, "science_yield": 5,
                 "military_strength": 30, "captured_capitals": ["PLAYER_0"], "has_original_capital": True,
                 "victory_progress": {"VICTORY_TECHNOLOGY": 0}},
            ],
        }},
    }


class RankingsWireTests(unittest.TestCase):
    def test_section_ranks_and_gaps(self):
        lines = rankings_wire.world_rankings_lines(_context())
        text = "\n".join(lines)
        self.assertIn("rankings.science.you = ", text)
        sci_you = next(l for l in lines if l.startswith("rankings.science.you"))
        self.assertIn("rank 3 of 3", sci_you)
        self.assertIn("leader Trajan (ROME)", sci_you)
        self.assertIn("-2 techs", sci_you)
        self.assertIn("-1.8 science/turn", sci_you)
        self.assertIn("Unmet Civilization 1", text)
        self.assertNotIn("PLAYER_2", text)
        dom_you = next(l for l in lines if l.startswith("rankings.domination.you"))
        self.assertIn("rank 2 of 3", dom_you)
        self.assertIn("holds 1 foreign original capital(s) (You)", text)
        rel = next(l for l in lines if l.startswith("# Religious"))
        self.assertIn("disabled", rel)
        self.assertIn("converted 2/3 civs (You, Trajan", text)
        self.assertIn("foreign tourists needed", text)
        self.assertIn("rankings.diplomatic = n/a", text)
        self.assertNotIn(" favor,", text)
        self.assertNotIn("diplomatic victory points", text)

    def test_gathering_storm_diplomatic(self):
        ctx = _context("EXPANSION2")
        rows = ctx["civ6"]["rankings"]["players"]
        rows[0].update(diplomatic_vp=2, favor=12, favor_per_turn=1)
        rows[1].update(diplomatic_vp=4, favor=30)
        lines = rankings_wire.world_rankings_lines(ctx)
        dip = next(l for l in lines if l.startswith("rankings.diplomatic.you"))
        self.assertIn("rank 2 of 3", dip)
        self.assertIn("2/20 diplomatic victory points", dip)
        self.assertIn("12 favor (+1/turn)", dip)
        self.assertIn("-2 diplomatic points, -18 favor", dip)

    def test_leader_gap(self):
        ctx = _context()
        ctx["civ6"]["rankings"]["players"][0]["military_strength"] = 90
        dom = next(l for l in rankings_wire.world_rankings_lines(ctx) if l.startswith("rankings.domination.you"))
        self.assertIn("rank 1 of 3", dom)
        self.assertIn("you lead Trajan (ROME) by +30 military strength", dom)

    def test_absent_block_is_silent_and_prompt_hook(self):
        self.assertEqual(rankings_wire.world_rankings_lines({}), [])
        prompt = civ6_wire.build_civ6_wire_prompt(_context())
        self.assertIn("=== WORLD RANKINGS ===", prompt)
        self.assertNotIn("=== WORLD RANKINGS ===", civ6_wire.build_civ6_wire_prompt({}))


if __name__ == "__main__":
    unittest.main()
