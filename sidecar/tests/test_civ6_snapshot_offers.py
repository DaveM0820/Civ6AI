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
        self.assertEqual(["PLAYER_0"], ids)
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


    def test_improve_sites_are_each_builders_nearest_tiles(self):
        """A far quarry must not be the only Improve offer for every builder."""
        self.lua.execute(
            r"""
            local function iter(list)
              local i = 0
              return function() i = i + 1; return list[i] end
            end
            local plots = {}
            local function plot(x, y, terrain, feature, resource)
              plots[x .. "," .. y] = {
                GetX=function() return x end, GetY=function() return y end,
                GetOwner=function() return 0 end,
                IsCity=function() return false end, IsWater=function() return false end,
                IsMountain=function() return false end, IsRiver=function() return false end,
                GetImprovementType=function() return -1 end,
                GetDistrictType=function() return -1 end,
                GetTerrainType=function() return terrain end,
                GetFeatureType=function() return feature end,
                GetResourceType=function() return resource end,
              }
            end
            plot(11, 10, 0, 1, -1)
            for y = 12, 18 do plot(10, y, 0, -1, 3) end
            plot(12, 12, 0, -1, 3)
            plot(41, 40, 0, -1, -1)
            Map = {
              GetPlot = function(x, y) return plots[x .. "," .. y] end,
              GetPlotDistance = function(ax, ay, bx, by)
                return math.max(math.abs(ax - bx), math.abs(ay - by))
              end,
            }
            Players = { [0] = {
              GetTechs = function() return { HasTech = function(_, idx) return idx ~= 5 end } end,
              GetCulture = function() return { HasCivic = function() return true end } end,
            }}
            GameInfo = {
              Units = { [0] = { UnitType = "UNIT_BUILDER" } },
              Terrains = { [0] = { TerrainType = "TERRAIN_GRASS" } },
              Features = { [1] = { FeatureType = "FEATURE_FOREST", Removable = true } },
              Resources = { [3] = { ResourceType = "RESOURCE_STONE" } },
              Technologies = { TECH_MACHINERY = { Index = 5 } },
              Improvements = function()
                return iter({
                  { ImprovementType = "IMPROVEMENT_FARM", Buildable = true },
                  { ImprovementType = "IMPROVEMENT_QUARRY", Buildable = true },
                  { ImprovementType = "IMPROVEMENT_LUMBER_MILL", Buildable = true, PrereqTech = "TECH_MACHINERY" },
                })
              end,
              Improvement_ValidTerrains = function()
                return iter({ { ImprovementType = "IMPROVEMENT_FARM", TerrainType = "TERRAIN_GRASS" } })
              end,
              Improvement_ValidFeatures = function()
                return iter({ { ImprovementType = "IMPROVEMENT_LUMBER_MILL", FeatureType = "FEATURE_FOREST" } })
              end,
              Improvement_ValidResources = function()
                return iter({ { ImprovementType = "IMPROVEMENT_QUARRY", ResourceType = "RESOURCE_STONE" } })
              end,
              Improvement_ValidBuildUnits = function()
                return iter({
                  { ImprovementType = "IMPROVEMENT_FARM", UnitType = "UNIT_BUILDER" },
                  { ImprovementType = "IMPROVEMENT_QUARRY", UnitType = "UNIT_BUILDER" },
                  { ImprovementType = "IMPROVEMENT_LUMBER_MILL", UnitType = "UNIT_BUILDER" },
                })
              end,
            }
            local function unit(id, x, y)
              return {
                GetID = function() return id end, GetOwner = function() return 0 end,
                GetType = function() return 0 end, GetX = function() return x end, GetY = function() return y end,
                GetBuildCharges = function() return 3 end,
              }
            end
            UNIT_A = unit(1, 10, 10)
            UNIT_B = unit(2, 40, 40)
            Civ6Ai_Snapshot._impRules = nil
            CMDS_A = {}
            CMDS_B = {}
            Civ6Ai_Snapshot._AddBuilderImproveCommands(CMDS_A, 0, UNIT_A, "UNIT_A")
            Civ6Ai_Snapshot._impRules = nil
            Civ6Ai_Snapshot._AddBuilderImproveCommands(CMDS_B, 0, UNIT_B, "UNIT_B")
            """
        )

        def sites(table):
            found = []
            n = len(table)
            for i in range(1, n + 1):
                fixed = table[i].fixed_arguments
                found.append((int(fixed.target_x), int(fixed.target_y), str(fixed.improvement_id)))
            return found

        a = sites(self.lua.globals().CMDS_A)
        b = sites(self.lua.globals().CMDS_B)
        self.assertIn((11, 10, "IMPROVEMENT_FARM"), a)
        self.assertEqual((11, 10, "IMPROVEMENT_FARM"), a[0])
        self.assertNotIn((11, 10, "IMPROVEMENT_FARM"), b)
        self.assertIn((41, 40, "IMPROVEMENT_FARM"), b)
        self.assertTrue(all(item[2] != "IMPROVEMENT_QUARRY" for item in b))
        self.assertLess(sum(1 for item in a if item[2] == "IMPROVEMENT_QUARRY"), len(a))



    def test_promotion_uses_experience_and_is_offered_when_legal(self):
        self.lua.execute(
            r"""
            local function iter(rows)
              local i = 0
              return function()
                i = i + 1
                return rows[i]
              end
            end
            local exp = {
              ready = true,
              CanPromote = function(self) return self.ready end,
              HasPromotion = function() return false end,
              GetExperiencePoints = function() return 20 end,
              GetExperienceForNextLevel = function() return 15 end,
            }
            UNIT = {
              GetType = function() return 0 end,
              GetX = function() return 0 end,
              GetY = function() return 0 end,
              GetExperience = function() return exp end,
            }
            EXP = exp
            Players = { [1] = {} }
            Map = { GetPlot = function() return nil end }
            GameInfo = {
              Units = { [0] = { PromotionClass = "PROMOTION_CLASS_MELEE", UnitType = "UNIT_WARRIOR" } },
              UnitPromotions = function()
                return iter({
                  { Index = 1, UnitPromotionType = "PROMOTION_BATTLECRY", PromotionClass = "PROMOTION_CLASS_MELEE" },
                  { Index = 2, UnitPromotionType = "PROMOTION_RANGER", PromotionClass = "PROMOTION_CLASS_RECON" },
                })
              end,
              UnitPromotionPrereqs = function() return iter({}) end,
            }
            CMDS = {}
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot
        self.assertTrue(snap._UnitPromotionReady(self.lua.globals().UNIT))
        self.lua.execute("EXP.ready = false; EXP.CanPromote = nil")
        self.assertTrue(snap._UnitPromotionReady(self.lua.globals().UNIT))
        self.lua.execute("EXP.GetExperiencePoints = function() return 1 end")
        self.assertFalse(snap._UnitPromotionReady(self.lua.globals().UNIT))
        self.lua.execute("EXP.CanPromote = function(self) return true end")
        snap._AddProgressionCommands(self.lua.globals().CMDS, 1, self.lua.globals().UNIT, "UNIT_1")
        cmds = self.lua.globals().CMDS
        promos = [cmds[i] for i in range(1, len(cmds) + 1) if cmds[i].kind == "promote_unit"]
        self.assertEqual(1, len(promos))
        self.assertEqual("PROMOTION_BATTLECRY", promos[0].fixed_arguments.promotion_id)

    def test_city_strike_is_offered_in_range_and_survives_the_command_cap(self):
        self.lua.execute(
            r"""
            Civ6Ai_Production = { _WireCityId = function(city) return "CITY_" .. tostring(city:GetID()) end }
            Map = { GetPlotDistance = function(ax, ay, bx, by) return math.abs(ax - bx) + math.abs(ay - by) end }
            local city = {
              GetID = function() return 7 end,
              GetX = function() return 10 end,
              GetY = function() return 10 end,
            }
            local function members(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  if list[i] then return i, list[i] end
                end
              end
            end
            CityCommandTypes = { RANGE_ATTACK = 7, PARAM_X = "x", PARAM_Y = "y" }
            CityManager = { CanStartCommand = function() return true end }
            Players = { [1] = { GetCities = function() return { Members = members({ city }) } end } }
            Civ6Ai_Snapshot._HostileTargets = function()
              return {
                { x = 12, y = 10, who = "unit" },
                { x = 20, y = 10, who = "unit" },
                { x = 11, y = 10, who = "city" },
              }
            end
            CMDS = {}
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot
        snap._AddCityStrikeCommands(self.lua.globals().CMDS, 1)
        cmds = self.lua.globals().CMDS
        targets = [(cmds[i].fixed_arguments.target_x, cmds[i].fixed_arguments.target_y) for i in range(1, len(cmds) + 1)]
        self.assertEqual([(12, 10)], targets)
        self.assertTrue(all(cmds[i].kind == "city_attack" for i in range(1, len(cmds) + 1)))
        self.lua.execute(
            "CityCommandTypes = { RANGE_ATTACK = 7 }; CMDS2 = {}; "
            "function Civ6Ai_Snapshot._CityStrikeCan() return true end"
        )
        snap._AddCityStrikeCommands(self.lua.globals().CMDS2, 1)
        self.assertGreaterEqual(int(self.lua.eval("#CMDS2")), 1)

        self.lua.execute(
            r"""
            local unit = {}
            Civ6Ai_Snapshot._AddProductionCommands = function() end
            Civ6Ai_Snapshot._AddPurchaseCommands = function() end
            Civ6Ai_Snapshot._IterateUnits = function() return { unit } end
            Civ6Ai_Snapshot._UnitNeedsOrders = function() return true end
            Civ6Ai_Snapshot._UnitWireId = function() return "UNIT_1" end
            Civ6Ai_Snapshot._UnitInfo = function() return {} end
            Civ6Ai_Snapshot._IsMilitaryInfo = function() return false end
            Civ6Ai_Snapshot._AddAttackCommands = function() end
            Civ6Ai_Snapshot._AddPillageCommand = function() end
            Civ6Ai_Snapshot._AddAdjacentMoveCommands = function(commands)
              for i = 1, 520 do
                commands[#commands + 1] = { kind = "move_unit", command_id = "M" .. i, fixed_arguments = {} }
              end
            end
            Players[1].GetUnits = function() return {} end
            Players[1].GetTechs = function() return nil end
            """
        )
        capped = snap._BuildLegalCommands(1, "PLAYER_1")
        self.assertEqual(500, len(capped))
        self.assertEqual("city_attack", capped[1].kind)

    def test_religion_great_person_and_trader_commands_follow_legality(self):
        self.lua.execute(
            r"""
            Map = {
              GetPlotDistance = function(ax, ay, bx, by) return math.abs(ax - bx) + math.abs(ay - by) end,
              GetPlot = function(x, y)
                return {
                  GetX = function() return x end, GetY = function() return y end,
                  GetIndex = function() return x * 1000 + y end,
                }
              end,
              GetNeighborPlots = function(x, y, dist)
                return { { GetX = function() return x + 1 end, GetY = function() return y end } }
              end,
            }
            local function members(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  if list[i] then return i, list[i] end
                end
              end
            end
            local campus = {
              GetType = function() return 3 end,
              GetX = function() return 4 end,
              GetY = function() return 4 end,
            }
            local holy = {
              GetType = function() return 4 end,
              GetX = function() return 8 end,
              GetY = function() return 8 end,
            }
            local ownCity = {
              GetDistricts = function() return { Members = members({ campus, holy }) } end,
              GetX = function() return 4 end, GetY = function() return 4 end,
              GetID = function() return 1 end, GetOwner = function() return 1 end,
            }
            local foreign = {
              GetX = function() return 5 end, GetY = function() return 4 end,
              GetID = function() return 131072 end, GetOwner = function() return 2 end,
            }
            Players = {
              [1] = { GetCities = function() return { Members = members({ ownCity }) } end },
              [2] = { GetCities = function() return { Members = members({ foreign }) } end },
            }
            GameInfo = {
              Units = {
                [1] = { UnitType = "UNIT_APOSTLE", ReligiousStrength = 110 },
                [2] = { UnitType = "UNIT_GURU", ReligiousStrength = 0 },
                [3] = { UnitType = "UNIT_GREAT_SCIENTIST", GreatPersonClassType = "GREAT_PERSON_CLASS_SCIENTIST" },
                [4] = { UnitType = "UNIT_GREAT_GENERAL", GreatPersonClassType = "GREAT_PERSON_CLASS_GENERAL" },
                [5] = { UnitType = "UNIT_TRADER" },
              },
              Districts = {
                [3] = { DistrictType = "DISTRICT_CAMPUS" },
                [4] = { DistrictType = "DISTRICT_HOLY_SITE" },
              },
              GlobalParameters = function()
                return (function()
                  local rows = { { Name = "RELIGION_HEAL_CHARGES", Value = 25 } }
                  local i = 0
                  return function()
                    i = i + 1
                    return rows[i]
                  end
                end)()
              end,
            }
            local rel = {
              GetSpreadCharges = function() return 2 end,
              GetReligionType = function() return 3 end,
            }
            local apostle = {
              GetType = function() return 1 end, GetX = function() return 5 end, GetY = function() return 3 end,
              GetID = function() return 11 end, GetReligion = function() return rel end,
            }
            local guru = {
              GetType = function() return 2 end, GetX = function() return 4 end, GetY = function() return 4 end,
              GetID = function() return 12 end, GetOwner = function() return 1 end,
              GetReligion = function() return rel end,
            }
            local friend = {
              GetOwner = function() return 1 end, GetID = function() return 99 end,
            }
            Units = { GetUnitsInPlot = function(plot)
              if plot:GetX() == 5 and plot:GetY() == 4 then return { friend } end
              return {}
            end }
            local scientist = {
              GetType = function() return 3 end, GetX = function() return 4 end, GetY = function() return 4 end,
              GetGreatPerson = function() return { Activate = function() end } end,
            }
            local general = {
              GetType = function() return 4 end, GetX = function() return 4 end, GetY = function() return 4 end,
              GetGreatPerson = function() return {} end,
            }
            local trader = {
              GetType = function() return 5 end, GetX = function() return 4 end, GetY = function() return 4 end,
            }
            Cities = { GetCityInPlot = function() return ownCity end }
            Game = { GetTradeManager = function()
              return {
                CanCreateTradeRoute = function(_, owner, fromIdx, toIdx) return toIdx == 5004 end,
                CreateTradeRoute = function() return true end,
              }
            end }
            APOSTLE, GURU, SCIENTIST, GENERAL, TRADER = apostle, guru, scientist, general, trader
            """
        )
        snap = self.lua.globals().Civ6Ai_Snapshot

        def kinds_for(unit, unit_id, adder):
            self.lua.execute("CMDS = {}")
            adder(self.lua.globals().CMDS, 1, unit, unit_id)
            cmds = self.lua.globals().CMDS
            return [(cmds[i].kind, dict(cmds[i].fixed_arguments.items())) for i in range(1, len(cmds) + 1)]

        spread = kinds_for(self.lua.globals().APOSTLE, "UNIT_A", snap._AddReligionCommands)
        self.assertEqual([("spread_religion", {"unit_id": "UNIT_A", "target_x": 5, "target_y": 4, "action": "spread"})], spread)
        heal = kinds_for(self.lua.globals().GURU, "UNIT_G", snap._AddReligionCommands)
        self.assertEqual([("spread_religion", {"unit_id": "UNIT_G", "target_x": 5, "target_y": 4, "action": "heal"})], heal)
        self.lua.execute("GameInfo.GlobalParameters = function() return function() return nil end end")
        self.assertEqual([], kinds_for(self.lua.globals().GURU, "UNIT_G", snap._AddReligionCommands))

        # Activate, retire, and trade routes are UI operations. They are not offered.
        self.assertEqual([], kinds_for(self.lua.globals().SCIENTIST, "UNIT_S", snap._AddActivateCommand))
        self.assertEqual([], kinds_for(self.lua.globals().GENERAL, "UNIT_N", snap._AddActivateCommand))
        self.assertEqual([], kinds_for(self.lua.globals().TRADER, "UNIT_T", snap._AddTradeRouteCommands))
        # The local seat's own trader: the vanilla MAKE_TRADE_ROUTE request, every
        # destination the game allows (other seats stay with the game's AI).
        self.lua.execute(r"""
            Game.GetLocalPlayer = function() return 1 end
            TRADER.GetMovesRemaining = function() return 1 end
            TRADER.GetID = function() return 7 end
            GameInfo.Units[5].MakeTradeRoute = true
            UnitOperationTypes = { MAKE_TRADE_ROUTE = 77, PARAM_X0 = "x0", PARAM_Y0 = "y0", PARAM_X1 = "x1", PARAM_Y1 = "y1" }
            PlayerManager = PlayerManager or {}
            PlayerManager.GetAliveIDs = function() return { 2 } end
            Locale = Locale or { Lookup = function(s) return s end }
            UnitManager = UnitManager or {}
            UnitManager.CanStartOperation = function(u, op, _, p) return op == 77 and p.x0 ~= nil end
            Map.GetPlotDistance = function() return 3 end
        """)
        routes = kinds_for(self.lua.globals().TRADER, "UNIT_T", snap._AddTradeRouteCommands)
        self.assertTrue(routes and all(k == "trade_route" for k, _ in routes), routes)
        self.assertEqual("PLAYER_2", routes[0][1]["destination_player_id"])
        self.lua.execute("Game.GetLocalPlayer = function() return 0 end")
        self.assertEqual([], kinds_for(self.lua.globals().TRADER, "UNIT_T", snap._AddTradeRouteCommands))
        self.lua.execute("SCIENTIST.GetGreatPerson = function() return {} end")
        self.assertEqual([], kinds_for(self.lua.globals().SCIENTIST, "UNIT_S", snap._AddActivateCommand))

    def test_embark_site_is_recorded_when_nothing_is_walkable(self):
        self.lua.execute(
            r"""
            Map = {
              GetPlot = function(x, y)
                if not ((x == 10 and y == 10) or (x == 22 and y == 10)) then return nil end
                return {
                  GetX = function() return x end, GetY = function() return y end,
                  GetIndex = function() return x * 100 + y end,
                  IsWater = function() return false end, IsImpassable = function() return false end,
                  IsFreshWater = function() return false end, IsRiver = function() return false end,
                  GetOwner = function() return -1 end,
                  GetArea = function() return { GetID = function() return x == 22 and 2 or 1 end } end,
                }
              end,
              GetPlotDistance = function(ax, ay, bx, by) return math.max(math.abs(ax - bx), math.abs(ay - by)) end,
            }
            local function members(list)
              return function()
                local i = 0
                return function()
                  i = i + 1
                  if list[i] then return i, list[i] end
                end
              end
            end
            local city = { GetX = function() return 10 end, GetY = function() return 10 end }
            Players = {}
            for pid = 0, 3 do
              Players[pid] = { GetCities = function() return { Members = members({}) } end }
            end
            Players[0].GetCities = function() return { Members = members({ city }) } end
            Players[1].GetTechs = function()
              return { HasTech = function(_, idx) return idx == 4 end }
            end
            GameInfo = {
              Units = { [0] = { UnitType = "UNIT_SETTLER", FoundCity = true } },
              Technologies = { TECH_SHIPBUILDING = { Index = 4 }, TECH_CARTOGRAPHY = { Index = 8 } },
            }
            UnitManager = { GetMoveToPath = function() return {} end }
            PlayersVisibility = { [1] = { IsRevealed = function() return true end } }
            ExposedMembers = { Civ6Ai = { CanFoundCityForPlayer = function() return false, "unit_cannot_found_city" end } }
            UNIT = {
              GetOwner = function() return 1 end, GetID = function() return 7 end,
              GetType = function() return 0 end, GetX = function() return 10 end, GetY = function() return 10 end,
            }
            """
        )
        facts = self.lua.globals().Civ6Ai_Snapshot._AddSettleFacts(self.lua.globals().UNIT)
        self.assertEqual(0, len(facts.sites))
        self.assertTrue(bool(facts.no_reachable_site))
        self.assertEqual(22, facts.embark_site.x)
        self.assertEqual(10, facts.embark_site.y)
        self.assertTrue(bool(facts.embark_site.can_embark))
        self.assertFalse(bool(facts.embark_site.can_ocean))

    def test_research_turns_left_uses_the_engine_not_the_floored_yield(self):
        self.lua.execute(
            r"""
            Civ6Ai_Snapshot._BuildYourCities = function() return {} end
            Civ6Ai_Snapshot._BuildUnitCounts = function() return {} end
            local function empty()
              return function() return nil end
            end
            GameInfo = {
              Technologies = function()
                local rows = { { Index = 3, TechnologyType = "TECH_STEEL" } }
                local i = 0
                return function()
                  i = i + 1
                  return rows[i]
                end
              end,
              Civics = empty,
            }
            TECHS = {
              GetResearchingTech = function() return 3 end,
              GetScienceYield = function() return 10.2 end,
              GetResearchProgress = function() return 39 end,
              GetResearchCost = function() return 100 end,
              GetTurnsLeft = function() return 6 end,
              HasTech = function() return false end,
            }
            local player = {
              GetTeam = function() return 0 end,
              GetScore = function() return 0 end,
              GetTreasury = function()
                return {
                  GetGoldBalance = function() return 0 end,
                  GetGoldYield = function() return 0 end,
                  GetTotalMaintenance = function() return 0 end,
                }
              end,
              GetTechs = function() return TECHS end,
              GetCulture = function()
                return { GetCultureYield = function() return 0 end, HasCivic = function() return false end }
              end,
            }
            Players = { [0] = player }
            PLAYER = player
            """
        )
        empire = self.lua.globals().Civ6Ai_Snapshot._BuildYourEmpire(0, self.lua.globals().PLAYER)
        self.assertEqual("TECH_STEEL", empire.research.tech_id)
        self.assertEqual(6, empire.research.estimated_turns_remaining)
        self.lua.execute("TECHS.GetTurnsLeft = nil")
        empire = self.lua.globals().Civ6Ai_Snapshot._BuildYourEmpire(0, self.lua.globals().PLAYER)
        # Remaining 61 at 10.2 science is 6 turns. Flooring the yield to 10 makes it 7.
        self.assertEqual(6, empire.research.estimated_turns_remaining)

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

    def test_settler_move_to_listed_site_packs_found_arrival(self):
        snap = {
            "game": {"map_width": 40, "map_height": 40},
            "your_units": [{
                "unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_10_10",
                "settle": {"here_ok": True, "coastal": True, "sites": [{"x": 12, "y": 11, "dist": 2, "coastal": True}]},
            }],
            "legal_commands": [],
        }
        cmd = command_wire.resolve_unit_token(snap, "UNIT_SETTLER_1", "MoveTo(12,11)")
        extra = next(c for c in snap["legal_commands"] if c["command_id"] == cmd)
        self.assertEqual("move", extra["fixed_arguments"]["intent"])
        self.assertEqual(0, extra["fixed_arguments"]["A"])
        lines = "\n".join(command_wire.sitrep_offer_lines(snap))
        self.assertIn("founding here is legal", lines)
        self.assertIn("coastal", lines)

    def test_own_tile_move_is_rejected_even_when_found_is_offered(self):
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
        command_wire.LAST_UNRESOLVED.clear()
        self.assertEqual("CMD_UNIT_SETTLER_1_skip", command_wire.resolve_unit_token(snap, "UNIT_SETTLER_1", "MoveTo(10,10)"))
        self.assertTrue(any(n.startswith("Rejected last turn: MoveTo(10,10)") and "already on that tile" in n
                            for n in command_wire.LAST_UNRESOLVED))

    def test_own_tile_move_adds_no_offer(self):
        for legal in ([], [{"command_id": "CMD_fortify_UNIT_W", "kind": "unit_posture_fortify",
                            "fixed_arguments": {"unit_id": "UNIT_W"}}]):
            snap = {
                "game": {"map_width": 40, "map_height": 40},
                "your_units": [{"unit_id": "UNIT_W", "unit_type_id": "UNIT_WARRIOR", "plot_id": "PLOT_10_10"}],
                "legal_commands": list(legal),
            }
            # Own-tile MoveTo holds the unit (vanilla Skip); no move offer is added.
            self.assertEqual("CMD_UNIT_W_skip", command_wire.resolve_unit_token(snap, "UNIT_W", "MoveTo(10,10)"))
            self.assertFalse(any(c.get("kind") == "move_unit" for c in snap["legal_commands"]))

    def test_improve_on_unoffered_tile_is_rejected(self):
        offer = {"command_id": "CMD_B_farm_3_4", "kind": "move_unit",
                 "fixed_arguments": {"unit_id": "UNIT_B", "target_x": 3, "target_y": 4,
                                     "improvement_id": "IMPROVEMENT_FARM", "intent": "improve",
                                     "A": 2, "G": 1, "goal": 1}}
        snap = {"your_units": [{"unit_id": "UNIT_B", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_1_1"}],
                "legal_commands": [offer]}
        command_wire.LAST_UNRESOLVED.clear()
        self.assertEqual("CMD_B_farm_3_4",
                         command_wire.resolve_unit_token(snap, "UNIT_B", "Improve(3,4,IMPROVEMENT_FARM)"))
        self.assertIsNone(command_wire.resolve_unit_token(snap, "UNIT_B", "Improve(9,9,IMPROVEMENT_FARM)"))
        self.assertTrue(any("no Improve is offered" in n for n in command_wire.LAST_UNRESOLVED))

    def test_unknown_unit_token_names_the_real_ids(self):
        snap = {
            "your_units": [{"unit_id": "UNIT_BUILDER_1", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_1_1"}],
            "legal_commands": [],
        }
        command_wire.expand_civ6_command_wire(snap, {"builder_10.command": "MoveTo"})
        notes = " ".join(command_wire.LAST_UNRESOLVED)
        self.assertIn("builder_10", notes)
        self.assertIn("not one of your units", notes)
        self.assertIn("builder_1", notes)

    def test_unit_alias_resolves_and_out_of_range_does_not(self):
        snap = {
            "game": {"map_width": 20, "map_height": 20},
            "your_units": [
                {"unit_id": "UNIT_B", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_1_1"},
                {"unit_id": "UNIT_B2", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_2_2"},
            ],
            "legal_commands": [],
        }
        out = command_wire.expand_civ6_command_wire(snap, {"Builder_1.command": "MoveTo(3,3)"})
        self.assertTrue(str(out.get("cmd.0", "")).startswith("CMD_"))
        out = command_wire.expand_civ6_command_wire(snap, {"builder-1.command": "MoveTo(4,4)"})
        self.assertTrue(str(out.get("cmd.0", "")).startswith("CMD_"))
        out = command_wire.expand_civ6_command_wire(snap, {"builder_01.command": "MoveTo(5,5)"})
        self.assertTrue(str(out.get("cmd.0", "")).startswith("CMD_"))
        command_wire.expand_civ6_command_wire(snap, {"builder_10.command": "MoveTo(6,6)"})
        self.assertIn("builder_10", " ".join(command_wire.LAST_UNRESOLVED))
        one = {
            "game": {"map_width": 20, "map_height": 20},
            "your_units": [{"unit_id": "UNIT_B", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_1_1"}],
            "legal_commands": [{
                "command_id": "CMD_attack_UNIT_B_3_3",
                "kind": "attack_target",
                "fixed_arguments": {"unit_id": "UNIT_ONLY", "target_x": 3, "target_y": 3},
            }],
        }
        # A real attack offer for the ordered unit is sent as that attack.
        one["your_units"] = [{"unit_id": "UNIT_ONLY", "unit_type_id": "UNIT_WARRIOR", "plot_id": "PLOT_1_1"}]
        bound = command_wire.resolve_unit_token(one, "UNIT_ONLY", "MoveTo(3,3)")
        self.assertEqual("CMD_attack_UNIT_B_3_3", bound)

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
        self.assertEqual("move", extra["fixed_arguments"]["intent"])
        self.assertEqual(0, extra["fixed_arguments"]["A"])
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
        self.assertNotIn("settler_1.settle.sites", lines)  # no settle-site suggestions
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
