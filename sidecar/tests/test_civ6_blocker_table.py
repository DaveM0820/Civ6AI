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
Civ6Ai_Bridge = {
  _WallClock = function() return NOW end,
  SessionId = function() return "s" end,
  SetSessionId = function() end,
  HostWaitSnapshotTurn = function() return TURN end,
  HostEndTurnWaiting = function() return false end,
  SeatAnswerOutstanding = function() return false end,
}
Civ6Ai_Config = {
  IsAutotest = function() return true end,
  RootDir = function() return "root" end,
  AutotestStopTurn = function() return 50 end,
  SessionId = function() return "s" end,
  ManagedSeatsList = function() return {} end,
  ShouldRunBridge = function() return true end,
}
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

    def test_stall_watchdog_does_not_end_turn_while_seats_pending(self):
        self.lua.execute("END_TURN = 0; UI.RequestAction = function() END_TURN = END_TURN + 1 end")
        self.lua.execute(
            "Civ6Ai_Autotest._PendingSeats = function() return {1, 2} end"
        )
        self.g.Civ6Ai_Autotest.STALL_SECONDS = 4
        self.g.Civ6Ai_Autotest.STALL_MAX_ATTEMPTS = 3
        self.g.Civ6Ai_Autotest.StartStallWatchdog()
        self.lua.execute("RUN_TICKS()")
        for _ in range(4):
            self.lua.execute("NOW = NOW + 5")
            self.lua.execute("RUN_TICKS()")
        self.assertEqual(int(self.g.END_TURN), 0)
        self.assertTrue(any("same_turn_wait=true" in l for l in self._log()))


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class UnstackTests(unittest.TestCase):
    """Live T36: five land military units sat in P0's capital because the unit
    skip finished the moves of units the city produced onto an occupied center."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.lua.execute(AUTOTEST.read_text(encoding="utf-8"))
        self.lua.execute(r"""
          GameInfo = { Units = {
            UNIT_SLINGER = { FormationClass = "FORMATION_CLASS_LAND_COMBAT" },
            UNIT_BUILDER = { FormationClass = "FORMATION_CLASS_CIVILIAN" } } }
          PLOTS = {}
          function U(id, owner, t, x, y)
            local u = { id = id, x = x, y = y, moves = 2 }
            function u:GetID() return self.id end
            function u:GetOwner() return owner end
            function u:GetType() return t end
            function u:GetX() return self.x end
            function u:GetY() return self.y end
            function u:GetMovesRemaining() return self.moves end
            local k = x .. "," .. y
            PLOTS[k] = PLOTS[k] or {}
            table.insert(PLOTS[k], u)
            return u
          end
          Map = { GetPlot = function(x, y) return { x = x, y = y } end,
                  GetPlotDistance = function(ax, ay, bx, by) return math.max(math.abs(ax - bx), math.abs(ay - by)) end }
          Units = { GetUnitsInPlot = function(p) return PLOTS[p.x .. "," .. p.y] or {} end }
          UnitOperationTypes = { MOVE_TO = 7, PARAM_X = "X", PARAM_Y = "Y" }
          MOVES = {}; FINISHED = {}
          UnitManager = {
            CanStartOperation = function() return true end,
            RequestOperation = function(u, op, p) table.insert(MOVES, u:GetID() .. ">" .. p.X .. "," .. p.Y) end,
            FinishMoves = function(u) table.insert(FINISHED, u:GetID()) end,
          }
          Civ6Ai_Apply._UnitWasOrdered = function() return true end
        """)
        self.g = self.lua.globals()

    def test_stacked_military_steps_out_instead_of_finishing(self):
        self.lua.execute("""
          A = U(1, 0, "UNIT_SLINGER", 5, 5); B = U(2, 0, "UNIT_SLINGER", 5, 5)
          C = U(3, 0, "UNIT_SLINGER", 6, 5); D = U(4, 63, "UNIT_SLINGER", 4, 5)
          W = U(5, 0, "UNIT_BUILDER", 5, 6)
          Players[0].GetUnits = function() return { Members = function()
            local list, i = { A, B, W }, 0
            return function() i = i + 1; if list[i] then return i, list[i] end end end } end
        """)
        self.g.Civ6Ai_Autotest._SkipUnitMoves(0, True)
        moves = [self.g.MOVES[i] for i in range(1, len(self.g.MOVES) + 1)]
        finished = [self.g.FINISHED[i] for i in range(1, len(self.g.FINISHED) + 1)]
        # 6,5 has our slinger, 4,5 a foreign unit: 5,6 (only our builder) is free.
        self.assertEqual(["1>5,6", "2>5,6"], moves)
        self.assertEqual([5], finished)

    def test_lone_garrison_is_not_moved(self):
        self.lua.execute('A = U(1, 0, "UNIT_SLINGER", 5, 5)')
        self.assertFalse(self.g.Civ6Ai_Autotest._Unstack(0, self.g.A))
