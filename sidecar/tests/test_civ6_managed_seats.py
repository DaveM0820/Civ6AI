"""Empty ManagedSeats = every major the model should drive (AI, plus local human in autotest)."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Config.lua"

MOCKS = r"""
Civ6Ai_Util = { Log = function() end }
local function major(human)
  return {
    IsHuman = function() return human end,
    IsAlive = function() return true end,
    IsMajor = function() return true end,
  }
end
Players = { [0] = major(true), [1] = major(false), [2] = major(false) }
network = false
GameConfiguration = { IsNetworkMultiplayer = function() return network end }
Civ6Ai_Paths = { Autotest = 1, ManagedSeats = "" }
"""


def _to_bool(value) -> bool:
    return value is True


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class ManagedSeatDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute(CONFIG.read_text(encoding="utf-8"))
        self.lua.eval("Civ6Ai_Config.Initialize()")

    def test_autotest_empty_list_drives_human_and_ais(self):
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(1)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(2)"))
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsHumanSeat(0)"))

    def test_lan_autotest_empty_list_drives_human_and_ais(self):
        self.lua.execute("network = true; Civ6Ai_Config.Initialize()")
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsAutotest()"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(0)"))
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsHumanSeat(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(1)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(2)"))

    def test_lan_without_autotest_drives_ais_not_human(self):
        self.lua.execute("network = true; Civ6Ai_Paths.Autotest = 0; Civ6Ai_Config.Initialize()")
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsAutotest()"))
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsManagedSeat(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsHumanSeat(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(1)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(2)"))

    def test_explicit_list_still_filters(self):
        self.lua.execute('Civ6Ai_Paths.ManagedSeats = "1"; Civ6Ai_Config.Initialize()')
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsManagedSeat(0)"))
        self.assertTrue(self.lua.eval("Civ6Ai_Config.IsManagedSeat(1)"))
        self.assertFalse(self.lua.eval("Civ6Ai_Config.IsManagedSeat(2)"))


if __name__ == "__main__":
    unittest.main()
