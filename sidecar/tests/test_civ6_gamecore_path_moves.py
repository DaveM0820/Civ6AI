"""A scripted path walk keeps the unit's remaining moves after each step (one-tile-per-turn bug)."""
import pathlib
import unittest

try:
    import lupa
except ImportError:  # pragma: no cover
    lupa = None

MOD = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai"

ENV = r"""
ExposedMembers = {}
Events = setmetatable({}, {__index = function() return {Add = function() end} end})
GameEvents = Events
LuaEvents = Events
function print() end
local function plot(x, y)
  return { GetX = function() return x end, GetY = function() return y end, GetIndex = function() return x * 100 + y end,
    IsWater = function() return false end, IsImpassable = function() return false end, IsMountain = function() return false end,
    GetTerrainType = function() return 0 end, GetFeatureType = function() return -1 end, IsHills = function() return false end,
    GetRouteType = function() return -1 end, GetOwner = function() return -1 end, IsRiverCrossingToPlot = function() return false end,
    IsCliffCrossingToPlot = function() return false end, IsCity = function() return false end }
end
Map = { GetPlot = plot, GetPlotByIndex = function(i) return plot(math.floor(i / 100), i % 100) end,
  GetPlotDistance = function(a, b, c, d) return math.max(math.abs(a - c), math.abs(b - d)) end }
GameInfo = { Units = { [1] = { UnitType = "UNIT_SCOUT", Domain = "DOMAIN_LAND", FormationClass = "FORMATION_CLASS_LAND_COMBAT" } },
  Terrains = {}, Features = {}, Routes = {} }
setmetatable(GameInfo.Terrains, {__index = function() return { MovementCost = 1 } end})
setmetatable(GameInfo.Features, {__index = function() return nil end})
UNIT = { x = 0, y = 0, moves = 3 }
local u = UNIT
function u:GetX() return self.x end
function u:GetY() return self.y end
function u:GetID() return 7 end
function u:GetType() return 1 end
function u:GetOwner() return 0 end
function u:GetMovesRemaining() return self.moves end
function u:GetMaxMoves() return 3 end
function u:IsEmbarked() return false end
Players = { [0] = { GetUnits = function() return { FindID = function(_, id) return id == 7 and u or nil end } end } }
Units = { GetUnitsInPlot = function() return {} end }
UnitManager = {
  GetMoveToPath = function() return { 0, 1, 2, 3 } end,  -- (0,0) (0,1) (0,2) (0,3)
  MoveUnit = function(unit, x, y) unit.x, unit.y, unit.moves = x, y, 0 end,  -- the engine ends movement
  ChangeMovesRemaining = function(unit, d) unit.moves = unit.moves + d end,
}
"""


@unittest.skipIf(lupa is None, "lupa not installed")
class PathMoveTests(unittest.TestCase):
    def test_three_move_scout_walks_three_flat_tiles(self):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(ENV)
        rt.execute((MOD / "Gameplay" / "Civ6Ai_GameCore.lua").read_text(encoding="utf-8"))
        gc = rt.globals().Civ6Ai_GameCore
        # Use the real cost helper; a flat step costs 1 here.
        gc._PlotEnterCost = lambda plot: 1
        rt.execute("Civ6Ai_GameCore._PlotEnterCost = function() return 1 end")
        ok, note = gc.MoveUnitAlongPathForPlayer(0, 7, 0, 3)
        self.assertTrue(ok, note)
        self.assertIn("steps=3", note)
        self.assertEqual(3, rt.globals().UNIT.y)


if __name__ == "__main__":
    unittest.main()
