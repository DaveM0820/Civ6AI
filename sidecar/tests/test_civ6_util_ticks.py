"""Civ6Ai_Util tick pump: ticks scheduled from inside a running tick survive."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover - optional dev dependency
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
UTIL = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Util.lua"


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class TickPumpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(
            """
            ExposedMembers = {}
            Events = nil
            ContextPtr = {
              SetUpdate = function(self, fn) _upd = fn end,
              ClearUpdate = function(self) _upd = nil end,
            }
            """
        )
        self.lua.execute(UTIL.read_text(encoding="utf-8"))
        self.lua.execute("Civ6Ai_Util.Log = function(s) end")

    def frames(self, n: int) -> None:
        self.lua.execute(f"for i = 1, {n} do if _upd then _upd() end end")

    def test_ticks_scheduled_inside_a_tick_are_kept(self) -> None:
        # Live shape: the host's apply tick finishes its pulse, which schedules
        # the seat-answer watcher and then the end-turn barrier.
        self.lua.execute(
            """
            runs = { watcher = 0, barrier = 0 }
            local n = 0
            Civ6Ai_Util.ScheduleTick(function()
              n = n + 1
              if n < 3 then return true end
              Civ6Ai_Util.ScheduleTick(function() runs.watcher = runs.watcher + 1; return true end)
              Civ6Ai_Util.ScheduleTick(function() runs.barrier = runs.barrier + 1; return runs.barrier < 5 end)
              return false
            end)
            """
        )
        self.frames(20)
        runs = self.lua.globals().runs
        self.assertEqual(runs.barrier, 5)
        self.assertGreater(runs.watcher, 5)
        self.assertEqual(self.lua.eval("#Civ6Ai_Util._ticks"), 1)

    def test_schedule_outside_a_pump_still_runs_at_once(self) -> None:
        self.lua.execute("ran = 0; Civ6Ai_Util.ScheduleTick(function() ran = ran + 1; return false end)")
        self.assertEqual(self.lua.globals().ran, 1)
        self.assertEqual(self.lua.eval("#Civ6Ai_Util._ticks"), 0)

    def test_erroring_tick_is_dropped_and_others_survive(self) -> None:
        self.lua.execute(
            """
            ok_runs = 0
            Civ6Ai_Util.ScheduleTick(function() error("boom") end)
            Civ6Ai_Util.ScheduleTick(function() ok_runs = ok_runs + 1; return ok_runs < 3 end)
            """
        )
        self.frames(5)
        self.assertEqual(self.lua.globals().ok_runs, 3)
        self.assertEqual(self.lua.eval("#Civ6Ai_Util._ticks"), 0)


if __name__ == "__main__":
    unittest.main()
