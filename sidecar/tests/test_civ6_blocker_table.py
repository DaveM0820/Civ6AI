"""F7 blocker dispatch table and stall watchdog (Lua, lupa)."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
AUTOTEST = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Autotest.lua"


STUBS = r"""
LOG = {}
AUTOTEST_LOG = {}
NOW = 1000
TURN = 3
Civ6Ai_Util = {
  Log = function(m) table.insert(LOG, m) end,
  ScheduleTick = function(fn) TICKS = TICKS or {}; table.insert(TICKS, fn) end,
  JoinPath = function(...) return table.concat({...}, "/") end,
  WriteTextFile = function() return true end,
  AppendTextLine = function() return true end,
}
Civ6Ai_Config = {
  IsAutotest = function() return true end,
  RootDir = function() return "root" end,
  AutotestStopTurn = function() return 50 end,
  SessionId = function() return "s" end,
}
Civ6Ai_Bridge = { _WallClock = function() return NOW end, SessionId = function() return "s" end, SetSessionId = function() end }
Civ6Ai_Apply = { _SetResearchTech = function() return true, "" end, _SetResearchCivic = function() return true, "" end, ResolveAllUnitOrders = function() end }
Civ6Ai_Production = nil
Game = { GetCurrentGameTurn = function() return TURN end, GetLocalPlayer = function() return 0 end }
Players = { [0] = { IsHuman = function() return true end } }
Events = nil
NotificationManager = {
  GetList = function() return NIDS or {} end,
  Find = function(_, nid) return ENTRIES[nid] end,
  SendActivated = function() ACTIVATED = (ACTIVATED or 0) + 1 end,
  Dismiss = function() DISMISSED = (DISMISSED or 0) + 1 end,
}
EndTurnBlockingTypes = {
  ENDTURN_BLOCKING_RESEARCH = 1,
  ENDTURN_BLOCKING_CIVIC = 2,
  ENDTURN_BLOCKING_PRODUCTION = 3,
  ENDTURN_BLOCKING_FILL_CIVIC_SLOT = 4,
  ENDTURN_BLOCKING_UNITS = 5,
  ENDTURN_BLOCKING_WEIRD = 99,
}
ENTRIES = {}
NIDS = {}
UI = { CanEndTurn = function() return true end, RequestAction = function() end }
ActionTypes = { ACTION_ENDTURN = 1 }
function RUN_TICKS()
  local keep = {}
  for _, fn in ipairs(TICKS or {}) do if fn() then table.insert(keep, fn) end end
  TICKS = keep
end
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class BlockerTableTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.lua.execute(AUTOTEST.read_text(encoding="utf-8"))
        self.g = self.lua.globals()

    def _log(self):
        return [self.g.LOG[i] for i in range(1, len(self.g.LOG) + 1)]

    def test_every_handler_is_callable(self):
        table = self.g.Civ6Ai_Autotest.BLOCKER_HANDLERS
        names = list(table.keys()) if hasattr(table, "keys") else []
        if not names:
            # lupa table
            names = [k for k in table]
        self.assertIn("RESEARCH", [str(n) for n in names])
        self.assertIn("FILL_CIVIC_SLOT", [str(n) for n in names])
        for name in names:
            fn = table[name]
            self.assertTrue(callable(fn), name)

    def test_research_dispatch_logs_handled(self):
        self.lua.execute(
            """
            NIDS = {1}
            ENTRIES = { [1] = {
              IsDismissed = function() return false end,
              GetEndTurnBlocking = function() return EndTurnBlockingTypes.ENDTURN_BLOCKING_RESEARCH end,
            }}
            """
        )
        self.g.Civ6Ai_Autotest._DismissBlockers(0)
        self.assertTrue(any("blocker_handled|type=RESEARCH" in l for l in self._log()))

    def test_unknown_type_logs_unhandled(self):
        self.lua.execute(
            """
            NIDS = {1}
            ENTRIES = { [1] = {
              IsDismissed = function() return false end,
              GetEndTurnBlocking = function() return EndTurnBlockingTypes.ENDTURN_BLOCKING_WEIRD end,
            }}
            """
        )
        self.g.Civ6Ai_Autotest._DismissBlockers(0)
        self.assertTrue(any("blocker_unhandled|type=WEIRD" in l for l in self._log()))

    def test_stall_watchdog_logs_after_cap(self):
        self.g.Civ6Ai_Autotest.STALL_SECONDS = 4
        self.g.Civ6Ai_Autotest.STALL_MAX_ATTEMPTS = 3
        self.g.Civ6Ai_Autotest.StartStallWatchdog()
        self.lua.execute("RUN_TICKS()")
        for _ in range(4):
            self.lua.execute("NOW = NOW + 5")
            self.lua.execute("RUN_TICKS()")
        log = self._log()
        self.assertTrue(any("stall_watch|" in l for l in log))
        self.assertTrue(any("stall|turn=" in l for l in log))


if __name__ == "__main__":
    unittest.main()
