"""Seat timing / stale-replay regressions (session rotation, PendingApply rules in Lua)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
_spec = importlib.util.spec_from_file_location("civ6ai_install_mod_rot", ROOT / "scripts" / "install_mod.py")
install_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_mod)

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover - optional dev dependency
    LuaRuntime = None

from civ6_host_channel import _lua_queue_content


class SessionRotationTests(unittest.TestCase):
    def test_set_session_in_lua_replaces_only_session_line(self):
        text = 'Civ6Ai_Paths = {\r\n  Repo = "C:/x",\r\n  SessionId = "live-old",\r\n}\r\n'
        new, count = install_mod.set_session_in_lua(text, "live-new")
        self.assertEqual(1, count)
        self.assertIn('SessionId = "live-new",\r\n', new)
        self.assertIn('Repo = "C:/x"', new)

    def test_rotate_session_updates_modules_runtime_and_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "civ6ai"
            logs = tmp / "Logs"
            mod = tmp / "Mods" / "Civ6Ai"
            (mod / "InGame").mkdir(parents=True)
            (mod / "InGame" / "Civ6Ai_Paths.lua").write_text('Civ6Ai_Paths = {\n  SessionId = "live-old",\n}\n')
            root.mkdir()
            (root / "runtime.json").write_text(json.dumps({"session_id": "live-old", "managed_seats": "0,1"}))
            old_p0 = root / "sessions" / "live-old" / "PLAYER_0"
            old_p0.mkdir(parents=True)
            for name in ("decision.json", "apply_commands.json", "snapshot.json", "apply_turn_3.done", "memory.json"):
                (old_p0 / name).write_text("{}")
            mirror_p1 = logs / "civ6ai" / "sessions" / "live-old" / "PLAYER_1"
            mirror_p1.mkdir(parents=True)
            (mirror_p1 / "decision_chat.json").write_text("{}")

            info = install_mod.rotate_session("live-new", civ6ai_root=root, mod_dirs=[mod], log_dir=logs)

            self.assertEqual(("live-old", "live-new"), (info["old"], info["new"]))
            self.assertEqual(1, len(info["updated"]))
            self.assertIn('"live-new"', (mod / "InGame" / "Civ6Ai_Paths.lua").read_text())
            runtime = json.loads((root / "runtime.json").read_text())
            self.assertEqual("live-new", runtime["session_id"])
            self.assertEqual("0,1", runtime["managed_seats"])
            self.assertEqual(5, info["archived"])
            self.assertEqual(["memory.json"], sorted(p.name for p in old_p0.iterdir()))
            self.assertTrue((root / "sessions" / "live-new" / "PLAYER_1").is_dir())
            self.assertTrue(list((root / "sessions" / "live-old").glob("_archive_*/PLAYER_0/decision.json")))


class RunCiv6ChatOutputTests(unittest.TestCase):
    def test_chat_decision_does_not_overwrite_turn_apply_commands(self):
        sys.path.insert(0, str(ROOT))
        from sidecar import run_civ6

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            (session_dir / "apply_commands.json").write_text('{"commands":[{"kind":"move_unit"}]}\n')
            record = {"status": "approved", "validated": {}, "commands": [], "metrics": {}}
            run_civ6._write_decision_outputs(session_dir, record, session_dir / "decision_chat.json")
            self.assertIn("move_unit", (session_dir / "apply_commands.json").read_text())
            self.assertTrue((session_dir / "apply_commands_chat.json").is_file())


BRIDGE = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Bridge.lua"

LUA_STUBS = r"""
LOG = {}
APPLIED = {}
PANEL = {}
TICKS = {}
CURRENT_TURN = 1
LOCAL_PLAYER = 0
PENDING_SRC = ""
Game = {
  GetCurrentGameTurn = function() return CURRENT_TURN end,
  GetLocalPlayer = function() return LOCAL_PLAYER end,
}
Players = {}
for i = 0, 4 do Players[i] = {} end
Civ6Ai_Util = { Log = function(m) table.insert(LOG, m) end, CanReadHostFiles = function() return false end,
  ScheduleTick = function(fn) table.insert(TICKS, fn) end }
Civ6Ai_Config = {
  _managedSeats = {[0]=true,[1]=true,[2]=true,[3]=true,[4]=true},
  ShouldRunBridge = function(p) return p >= 0 and p <= 4 end,
  ManagedSeatsList = function() return {0, 1, 2, 3, 4} end,
  SessionId = function() return "sess" end,
  SidecarTimeout = function() return 600 end,
  IsAutotest = function() return false end,
}
Civ6Ai_Apply = {
  ApplyDecision = function(p, d, t) table.insert(APPLIED, {player=p, n=#d.commands, turn=t}) end,
  _IsNetworkMultiplayer = function() return false end,
  ResolveAllUnitOrders = function() end,
}
Civ6Ai_Chat = { PanelAdd = function(line) table.insert(PANEL, line) end }
function RUN_TICKS()
  local keep = {}
  for _, fn in ipairs(TICKS) do if fn() then table.insert(keep, fn) end end
  TICKS = keep
end
include = function(name)
  Civ6Ai_PendingApplyQueue = nil
  local chunk = load(PENDING_SRC)
  chunk()
end
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class BridgePendingApplyLuaTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute(LUA_STUBS)
        self.lua.execute(BRIDGE.read_text(encoding="utf-8"))
        self.g = self.lua.globals()
        self.g.Civ6Ai_Bridge._IsGameplayReady = lambda p: True

    def _publish(self, entries):
        state = {}
        for player, turn, payload, session in entries:
            apply_id = f"id-{session}-{player}-{turn}-{abs(hash(payload)) % 10**8}"
            state[f"{player}:turn"] = {
                "session_id": session, "player": player, "turn": turn, "kind": "turn",
                "apply_id": apply_id, "json": payload,
            }
        self.g.PENDING_SRC = _lua_queue_content(state)

    def _log(self):
        return [self.g.LOG[i] for i in range(1, len(self.g.LOG) + 1)]

    def test_ai_seat_answer_sent_once_for_its_snapshot_turn(self):
        payload = '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{"unit_id":"UNIT_1"}}]}'
        self._publish([(2, 3, payload, "sess")])
        self.g.CURRENT_TURN = 4
        self.assertTrue(self.g.Civ6Ai_Bridge._DeliverSeatDecision(2, 3))
        self.assertEqual(1, len(self.g.APPLIED))
        self.assertEqual((2, 3), (self.g.APPLIED[1].player, self.g.APPLIED[1].turn))
        self.assertFalse(self.g.Civ6Ai_Bridge._DeliverSeatDecision(2, 3))
        self.assertEqual(1, len(self.g.APPLIED))
        self.assertTrue(any("seat_decision_sent|player=2|snapshot_turn=3" in line for line in self._log()))

    def test_ai_seat_rejects_other_session_and_wrong_turn(self):
        payload = '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{}}]}'
        self._publish([(2, 3, payload, "old-game")])
        self.g.CURRENT_TURN = 4
        self.assertFalse(self.g.Civ6Ai_Bridge._DeliverSeatDecision(2, 3))
        self._publish([(2, 1, payload, "sess")])
        self.g.Civ6Ai_Bridge._lastPendingReload = None
        self.assertFalse(self.g.Civ6Ai_Bridge._DeliverSeatDecision(2, 3))
        self.assertEqual(0, len(self.g.APPLIED))
        stale = [line for line in self._log() if "stale" in line]
        self.assertEqual(2, len(stale))

    def test_other_players_entry_is_never_applied(self):
        payload = '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{}}]}'
        self._publish([(1, 3, payload, "sess")])
        self.g.CURRENT_TURN = 4
        self.assertFalse(self.g.Civ6Ai_Bridge._DeliverSeatDecision(2, 3))
        self.assertEqual(0, len(self.g.APPLIED))

    def test_delivery_waits_for_answer_then_stops(self):
        self.g.CURRENT_TURN = 3
        self._publish([])
        self.g.Civ6Ai_Bridge._ScheduleSeatDelivery(2, 3)
        self.lua.execute("RUN_TICKS()")
        self.assertEqual(1, len(self.g.TICKS))
        self._publish([(2, 3, '{"commands":[{"kind":"unit_skip","command_id":"C","arguments":{}}]}', "sess")])
        self.g.Civ6Ai_Bridge._lastPendingReload = None
        self.lua.execute("RUN_TICKS()")
        self.assertEqual(0, len(self.g.TICKS))
        self.assertEqual(1, len(self.g.APPLIED))

    def test_delivery_gives_up_when_the_turn_it_was_for_is_over(self):
        self.g.CURRENT_TURN = 3
        self._publish([])
        self.g.Civ6Ai_Bridge._dumpedKeys["2|3"] = True
        self.g.Civ6Ai_Bridge._ScheduleSeatDelivery(2, 3)
        self.g.CURRENT_TURN = 5
        self.lua.execute("RUN_TICKS()")
        self.assertEqual(0, len(self.g.TICKS))
        self.assertTrue(self.g.Civ6Ai_Bridge.SeatDecisionSettled(2, 3))
        self.assertIn("1 AI player(s) had no answer", self.g.PANEL[1])

    def test_local_seat_stale_turn_logs_once(self):
        payload = '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{}}]}'
        self._publish([(0, 1, payload, "sess")])
        self.g.CURRENT_TURN = 2
        for _ in range(50):
            self.assertFalse(self.g.Civ6Ai_Bridge._TryPendingApplyFromMod(0))
        self.assertEqual(1, sum("pending_apply_stale_turn" in line for line in self._log()))

    def test_status_line_once_every_ai_seat_is_settled(self):
        self.g.CURRENT_TURN = 4
        self.assertTrue(self.g.Civ6Ai_Bridge.SeatDecisionSettled(3, 3))  # no snapshot dumped
        self.g.Civ6Ai_Bridge._dumpedKeys["3|3"] = True
        self.g.Civ6Ai_Bridge._dumpedKeys["4|3"] = True
        self.assertFalse(self.g.Civ6Ai_Bridge.SeatDecisionSettled(3, 3))
        self._publish([(3, 3, '{"commands":[],"chat_messages":[]}', "sess")])
        self.assertTrue(self.g.Civ6Ai_Bridge._DeliverSeatDecision(3, 3))
        self.assertTrue(self.g.Civ6Ai_Bridge.SeatDecisionSettled(3, 3))
        self.assertEqual(0, len(self.g.PANEL))  # seat 4 still out
        self._publish([(4, 3, '{"commands":[],"chat_messages":[]}', "sess")])
        self.g.Civ6Ai_Bridge._lastPendingReload = None
        self.assertTrue(self.g.Civ6Ai_Bridge._DeliverSeatDecision(4, 3))
        self.assertEqual(["T4  All AI orders are in. You can end your turn."], list(self.g.PANEL.values()))

    def test_non_local_seat_can_apply_in_single_player(self):
        self.assertTrue(self.g.Civ6Ai_Bridge._CanApplyInGame(3))

    def test_sp_turn_one_does_not_wait_for_turn_zero(self):
        self.g.CURRENT_TURN = 1
        self.assertEqual(0, int(self.g.Civ6Ai_Bridge.HostWaitSnapshotTurn()))
        self.assertFalse(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(1, 0))

    def test_lan_turn_one_waits_until_this_turn_is_delivered(self):
        self.g.Civ6Ai_Apply._IsNetworkMultiplayer = lambda: True
        self.g.CURRENT_TURN = 1
        self.assertEqual(1, int(self.g.Civ6Ai_Bridge.HostWaitSnapshotTurn()))
        self.assertTrue(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(1, 1))
        self.g.Civ6Ai_Bridge._delivered["1|1"] = False
        self.assertFalse(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(1, 1))

    def test_empty_pending_apply_is_replaced_by_later_commands(self):
        key = self.g.Civ6Ai_Bridge._PulseKey(0)
        self.g.Civ6Ai_Bridge._pulseKeys[key] = True
        self._publish([(0, 1, '{"commands":[]}', "sess")])
        self.assertTrue(self.g.Civ6Ai_Bridge._TryPendingApplyFromMod(0))
        self.assertEqual(0, len(self.g.APPLIED))
        self.assertTrue(self.g.Civ6Ai_Bridge._WasEmptyAppliedThisPulse(0))
        self._publish([(0, 1, '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{}}]}', "sess")])
        self.g.Civ6Ai_Bridge._lastPendingReload = None
        self.assertTrue(self.g.Civ6Ai_Bridge._TryPendingApplyFromMod(0))
        self.assertEqual(1, len(self.g.APPLIED))
        self.assertTrue(any("apply_replace_empty|player=0" in line for line in self._log()))


SAME_TURN_STUBS = r"""
AFTER = {}
ExposedMembers = { Civ6Ai = { TurnStartComplete = {} } }
Civ6Ai_Config.IsAutotest = function() return AUTOTEST end
Civ6Ai_Config.IsFastEndTurn = function() return false end
Civ6Ai_Config.IsHostPc = function() return true end
Civ6Ai_Config.IsManagedSeat = function(p) return p >= 0 and p <= 4 end
Civ6Ai_Config.IsSidecarLive = function() return true end
Civ6Ai_Config.PersonalityPath = function() return "" end
Civ6Ai_Config.RootDir = function() return "root" end
Civ6Ai_Config.SeatSnapshotAt = function() return SNAPSHOT_AT end
AUTOTEST = true
SNAPSHOT_AT = "host_end"
Civ6Ai_Util.JoinPath = function(...) return table.concat({...}, "/") end
Civ6Ai_Util.WriteTextFile = function() return false end
Civ6Ai_Util.ReadTextFile = function() return nil end
Civ6Ai_Util.DumpBlob = function() return true end
Civ6Ai_Snapshot = { Build = function(p) return "{}", {} end }
Civ6Ai_Autotest = { AfterPulse = function(p) table.insert(AFTER, p) end }
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class SameTurnSeatTimingLuaTests(unittest.TestCase):
    """AI seats snapshotted during the host's turn, played at their own turn start."""

    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute(LUA_STUBS)
        self.lua.execute(SAME_TURN_STUBS)
        self.lua.execute(BRIDGE.read_text(encoding="utf-8"))
        self.g = self.lua.globals()
        self.g.Civ6Ai_Bridge._IsGameplayReady = lambda p: True
        self.g.Civ6Ai_Bridge._HasActablePieces = lambda p: True
        self.g.Civ6Ai_Bridge._loadScreenClosed = True
        self.g.CURRENT_TURN = 5
        self.lua.execute("for p = 1, 4 do ExposedMembers.Civ6Ai.TurnStartComplete[p] = 4 end")

    def _log(self):
        return [self.g.LOG[i] for i in range(1, len(self.g.LOG) + 1)]

    def test_host_end_prepulses_every_ai_seat_without_ending_their_turn(self):
        self.assertEqual(0, self.g.Civ6Ai_Bridge.PrepulseSeats("turn_start"))
        self.assertEqual(4, self.g.Civ6Ai_Bridge.PrepulseSeats("host_end"))
        log = self._log()
        for seat in (1, 2, 3, 4):
            self.assertIn(f"bridge|seat_prepulse|player={seat}|turn=5|mode=host_end|seat_started=4", log)
            self.assertTrue(any(f"seat_end_deferred|player={seat}|turn=5|delivery=true" in l for l in log))
        self.assertEqual(0, len(self.g.AFTER))  # no seat ended while not active
        self.assertEqual(5, int(self.g.Civ6Ai_Bridge.HostWaitSnapshotTurn()))
        self.assertTrue(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(1, 5))
        # A second trigger in the same turn does not pulse again.
        self.assertEqual(0, self.g.Civ6Ai_Bridge.PrepulseSeats("host_end"))

    def test_sp_answer_is_for_this_turn_until_the_seat_turn_started(self):
        self.assertEqual(5, int(self.g.Civ6Ai_Bridge.SeatForTurn(1, 5)))
        self.lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete[1] = 5")
        self.assertEqual(6, int(self.g.Civ6Ai_Bridge.SeatForTurn(1, 5)))
        self.g.Civ6Ai_Apply._IsNetworkMultiplayer = lambda: True
        self.assertEqual(6, int(self.g.Civ6Ai_Bridge.SeatForTurn(2, 5)))

    def test_prepulsed_answer_is_sent_for_this_turn(self):
        self.g.Civ6Ai_Bridge.PrepulseSeats("host_end")
        payload = '{"commands":[{"kind":"move_unit","command_id":"CMD_1","arguments":{"unit_id":"UNIT_1"}}]}'
        self.g.PENDING_SRC = _lua_queue_content({"1:turn": {
            "session_id": "sess", "player": 1, "turn": 5, "kind": "turn", "apply_id": "a1", "json": payload}})
        self.lua.execute("Civ6Ai_Apply.ApplyDecision = function(p, d, t, f) table.insert(APPLIED, {player=p, turn=t, for_turn=f}) end")
        self.lua.execute("RUN_TICKS()")
        self.assertEqual(1, len(self.g.APPLIED))
        self.assertEqual((1, 5, 5), (self.g.APPLIED[1].player, self.g.APPLIED[1].turn, self.g.APPLIED[1].for_turn))
        self.assertTrue(any("seat_decision_sent|player=1|snapshot_turn=5|for_turn=5" in l for l in self._log()))
        self.assertFalse(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(1, 5))

    def test_seat_turn_start_ends_turn_once_after_its_queue_ran(self):
        self.g.Civ6Ai_Bridge.PrepulseSeats("host_end")
        self.g.Civ6Ai_Bridge.RunTurnPulse(1)  # PlayerTurnActivated before the queue ran
        self.assertEqual(0, len(self.g.AFTER))
        self.lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete[1] = 5")
        self.g.Civ6Ai_Bridge.RunTurnPulse(1)
        self.g.Civ6Ai_Bridge.RunTurnPulse(1)
        self.assertEqual([1], list(self.g.AFTER.values()))
        self.assertTrue(any("seat_end_after_queue|player=1|turn=5|snapshot_turn=5|prepulsed=true|answer=outstanding" in l
                            for l in self._log()))
        self.assertFalse(any("already_pulsed|player=1" in l for l in self._log()))

    def test_lan_seat_turn_start_reports_the_previous_turns_answer(self):
        # LAN: the answer to the turn 4 snapshot was queued for turn 5.
        self.g.Civ6Ai_Apply._IsNetworkMultiplayer = lambda: True
        self.lua.execute('Civ6Ai_Bridge._prepulseKeys["1|4"] = true; Civ6Ai_Bridge._delivered["1|4"] = true')
        self.lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete[1] = 5")
        self.g.Civ6Ai_Bridge.RunTurnPulse(1)
        self.assertTrue(any("seat_end_after_queue|player=1|turn=5|snapshot_turn=4|prepulsed=true|answer=sent" in l
                            for l in self._log()))

    def test_seat_without_answer_still_ends_its_turn(self):
        self.lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete[2] = 5")
        self.g.Civ6Ai_Bridge.RunTurnPulse(2)
        self.assertEqual([2], list(self.g.AFTER.values()))
        self.assertTrue(any("seat_end_after_queue|player=2|turn=5|snapshot_turn=5|prepulsed=false|answer=none" in l
                            for l in self._log()))

    def test_failed_prepulse_is_settled_so_the_barrier_does_not_wait(self):
        self.g.Civ6Ai_Snapshot.Build = lambda p: None
        self.g.Civ6Ai_Bridge.PrepulseSeats("host_end")
        self.assertFalse(self.g.Civ6Ai_Bridge.SeatAnswerOutstanding(3, 5))
        self.assertEqual(0, len(self.g.AFTER))

    def test_turn_start_mode_prepulses_after_the_host_pulse(self):
        self.g.SNAPSHOT_AT = "turn_start"
        self.g.Civ6Ai_Bridge.RunTurnPulse(0)
        self.assertFalse(any("seat_prepulse" in l for l in self._log()))
        self.lua.execute("RUN_TICKS()")
        self.assertTrue(any("seat_prepulse|player=4|turn=5|mode=turn_start" in l for l in self._log()))
        self.assertEqual(0, self.g.Civ6Ai_Bridge.PrepulseSeats("host_end"))

    def test_human_host_keeps_old_timing(self):
        self.g.AUTOTEST = False
        self.assertEqual(0, self.g.Civ6Ai_Bridge.PrepulseSeats("host_end"))
        self.assertEqual(4, int(self.g.Civ6Ai_Bridge.HostWaitSnapshotTurn()))


class SidecarJobStderrTests(unittest.TestCase):
    def test_failed_sidecar_reports_stderr_and_writes_file(self):
        import subprocess
        from civ6_sidecar_jobs import _run_job

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "PLAYER_1"
            session_dir.mkdir()
            script = Path(tmp) / "boom.py"
            script.write_text("import sys\nsys.stderr.write('Traceback...\\nBoundaryError: bad field\\n')\nsys.exit(1)\n")
            job = {"python": sys.executable, "script": script.name, "args": ["--session-dir", str(session_dir)],
                   "timeout_seconds": 30}
            with self.assertRaises(subprocess.CalledProcessError) as ctx:
                _run_job(job, Path(tmp))
            self.assertIn("BoundaryError: bad field", ctx.exception.stderr)
            self.assertIn("BoundaryError", (session_dir / "sidecar_stderr.txt").read_text())


class NudgeStalenessTests(unittest.TestCase):
    def test_nudge_superseded_by_new_local_turn_is_skipped(self):
        from civ6_lua_log_bridge import _chunk_requests_nudge

        self.assertTrue(_chunk_requests_nudge("x\nCIV6AI|autotest|nudge_enter|player=0\n"))
        self.assertFalse(_chunk_requests_nudge(
            "CIV6AI|autotest|nudge_enter|player=0\nCIV6AI|autotest|local_turn_begin|player=0|turn=5\n"))
        self.assertTrue(_chunk_requests_nudge(
            "CIV6AI|autotest|local_turn_begin|player=0|turn=5\nend_turn_failed|player=0|end_turn_blocked\n"))
        self.assertFalse(_chunk_requests_nudge("CIV6AI|bridge|pulse|player=0\n"))


GAMECORE_STUBS = r"""
LOG = {}
print = function(s) table.insert(LOG, s) end
ExposedMembers = { Civ6Ai = {} }
GameEvents = { PlayerTurnStartComplete = { Add = function() end }, PlayerTurnStarted = { Add = function() end } }
io = nil
os = nil
TURN = 4
Game = { GetCurrentGameTurn = function() return TURN end }
local function mkunit(id, typ, x)
  local u = { id = id, typ = typ, moves = 2, x = x, y = 1 }
  function u:GetID() return self.id end
  function u:GetType() return self.typ end
  function u:GetMovesRemaining() return self.moves end
  function u:GetMaxMoves() return 2 end
  function u:GetX() return self.x end
  function u:GetY() return self.y end
  return u
end
UNITS = { mkunit(1, 0, 1), mkunit(2, 1, 2) }
GameInfo = { Units = { [0] = { BuildCharges = 0 }, [1] = { BuildCharges = 3 } } }
UnitManager = {
  FinishMoves = function(u) u.moves = 0 end,
  RestoreMovement = function(u) u.moves = 2 end,
  MoveUnit = function(u, x, y) if u.moves > 0 then u.x = x; u.y = y end end,
}
Map = { GetPlot = function() return {} end }
local units = { Members = function(self) local i = 0 return function() i = i + 1 if UNITS[i] then return i, UNITS[i] end end end }
Players = {}
for pid = 0, 3 do
  Players[pid] = { IsHuman = function() return pid == 0 end, GetUnits = function() return units end }
end
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class GameCoreMoveTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute(GAMECORE_STUBS)
        self.lua.execute((ROOT / "mod/Civ6Ai/Gameplay/Civ6Ai_GameCore.lua").read_text(encoding="utf-8"))
        self.g = self.lua.globals()
        self.gc = self.g.Civ6Ai_GameCore
        self.gc._FindUnit = self.lua.eval(
            "function(p, id) for _, u in ipairs(UNITS) do if u.id == id then return nil, u, '' end end return nil, nil, 'no_unit' end")

    def test_move_needs_moves_left(self):
        unit = self.g.UNITS[1]
        ok, reason = self.gc.MoveUnitForPlayer(2, 1, 5, 1)
        self.assertTrue(ok, reason)
        self.assertEqual(5, unit.x)
        unit.moves = 0
        self.assertEqual((False, "illegal_move:no_moves_left"), tuple(self.gc.MoveUnitForPlayer(2, 1, 7, 1)))

    def test_planning_uses_full_movement(self):
        # A seat whose orders play at its next turn start plans with full movement.
        self.g.UNITS[1].moves = 0
        self.assertEqual(0, self.gc.UnitMovesForPlayer(2, 1))
        self.assertEqual(2, self.gc.UnitMovesForPlayer(2, 1, True))
        self.assertEqual((False, "no_moves_left"), tuple(self.gc.CanMoveUnitToForPlayer(2, 1, 5, 1)))
        self.assertTrue(self.gc.CanMoveUnitToForPlayer(2, 1, 5, 1, True)[0])


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class SeatFoundAndCivicTests(unittest.TestCase):
    """Seats 1-4 never got found_city in legal_commands; P0 civic had no fallback."""

    def test_gamecore_can_found_checks_type_site_and_territory(self):
        lua = LuaRuntime()
        lua.execute(GAMECORE_STUBS)
        lua.execute((ROOT / "mod/Civ6Ai/Gameplay/Civ6Ai_GameCore.lua").read_text(encoding="utf-8"))
        lua.execute("""
          GameInfo.Units[0].FoundCity = true
          OWNER = -1
          CITY = nil
          Map.GetPlot = function(x, y) return { IsWater = function() return false end,
            IsImpassable = function() return false end, GetOwner = function() return OWNER end } end
          Map.GetPlotDistance = function(ax, ay, bx, by) return math.abs(ax - bx) + math.abs(ay - by) end
          for pid = 0, 3 do
            Players[pid].GetCities = function() return { Members = function()
              local done = false
              return function() if CITY and not done then done = true return 1, CITY end end
            end } end
          end
          Civ6Ai_GameCore._FindUnit = function(p, id)
            for _, u in ipairs(UNITS) do if u.id == id then return Players[p], u, '' end end
            return nil, nil, 'unit_not_found'
          end
        """)
        gc, g = lua.globals().Civ6Ai_GameCore, lua.globals()
        self.assertEqual((True, ""), tuple(gc.CanFoundCityForPlayer(2, 1)))
        self.assertEqual((False, "unit_cannot_found_city"), tuple(gc.CanFoundCityForPlayer(2, 2)))
        g.OWNER = 3
        self.assertEqual((False, "foreign_territory"), tuple(gc.CanFoundCityForPlayer(2, 1)))
        g.OWNER = -1
        lua.execute("CITY = { GetX = function() return 2 end, GetY = function() return 1 end }")
        self.assertEqual((False, "too_close_to_city"), tuple(gc.CanFoundCityForPlayer(2, 1)))

    def test_non_local_settler_gets_found_city_from_gamecore_check(self):
        lua = LuaRuntime()
        lua.execute("Civ6Ai_Util = { Log = function() end }")
        lua.execute((ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))
        lua.execute("""
          Civ6Ai_Config = { IsSeatExperiment = function() return false end }
          local settler = { GetOwner = function() return 2 end, GetID = function() return 65536 end }
          Players = { [2] = { GetUnits = function() return {} end, GetTechs = function() return nil end } }
          GameInfo = { UnitOperations = { UNITOPERATION_FOUND_CITY = { Hash = 7 } } }
          UnitManager = { CanStartOperation = function() return false end }
          ExposedMembers = { Civ6Ai = { CanFoundCityForPlayer = function(p, id) return p == 2 and id == 65536, '' end } }
          Civ6Ai_Snapshot._AddProductionCommands = function() end
          Civ6Ai_Snapshot._IterateUnits = function() return { settler } end
          Civ6Ai_Snapshot._UnitNeedsOrders = function() return true end
          Civ6Ai_Snapshot._UnitWireId = function() return "UNIT_65536" end
          Civ6Ai_Snapshot._EnrichLegalCommand = function(c) return c end
          Civ6Ai_Snapshot._AddAttackCommands = function() end
          Civ6Ai_Snapshot._AddAdjacentMoveCommands = function() end
        """)
        cmds = lua.globals().Civ6Ai_Snapshot._BuildLegalCommands(2, "PLAYER_2")
        kinds = [cmds[i].kind for i in range(1, len(cmds) + 1)]
        self.assertIn("found_city", kinds)

    def test_queued_seat_is_not_offered_city_production(self):
        lua = LuaRuntime()
        lua.execute("Civ6Ai_Util = { Log = function() end }")
        lua.execute((ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))
        lua.execute("""
          Game = { GetLocalPlayer = function() return 0 end }
          LOOKED = false
          Players = setmetatable({}, { __index = function() LOOKED = true end })
        """)
        snap = lua.globals().Civ6Ai_Snapshot
        self.assertTrue(snap._CanQueueProduction(0))
        self.assertFalse(snap._CanQueueProduction(2))
        snap._AddProductionCommands([], 2)
        self.assertFalse(lua.eval("LOOKED"))

    def test_gamecore_adjacent_move_rejects_water_mountain_and_stacking(self):
        lua = LuaRuntime()
        lua.execute(GAMECORE_STUBS)
        lua.execute((ROOT / "mod/Civ6Ai/Gameplay/Civ6Ai_GameCore.lua").read_text(encoding="utf-8"))
        lua.execute("""
          GameInfo.Units[0].Domain = "DOMAIN_LAND"; GameInfo.Units[0].FormationClass = "FORMATION_CLASS_LAND_COMBAT"
          GameInfo.Units[1].Domain = "DOMAIN_LAND"; GameInfo.Units[1].FormationClass = "FORMATION_CLASS_CIVILIAN"
          PLOTS = {
            ["5,1"] = { water = true }, ["6,1"] = { mountain = true }, ["7,1"] = {}, ["8,1"] = { occ = { owner = 2, typ = 0 } },
            ["9,1"] = { occ = { owner = 2, typ = 1 } }, ["10,1"] = { occ = { owner = 3, typ = 1 } },
          }
          Map.GetPlot = function(x, y)
            local d = PLOTS[x .. "," .. y]
            if d == nil then return nil end
            return { IsWater = function() return d.water == true end, IsMountain = function() return d.mountain == true end,
              IsImpassable = function() return false end, IsCity = function() return false end, data = d }
          end
          Units = { GetUnitsInPlot = function(plot)
            local o = plot.data.occ
            if o == nil then return {} end
            return { { GetOwner = function() return o.owner end, GetType = function() return o.typ end } }
          end }
          Civ6Ai_GameCore._FindUnit = function(p, id)
            for _, u in ipairs(UNITS) do if u.id == id then return Players[p], u, '' end end
            return nil, nil, 'unit_not_found'
          end
        """)
        gc = lua.globals().Civ6Ai_GameCore
        can = lambda x: tuple(gc.CanMoveUnitToForPlayer(2, 1, x, 1))
        self.assertEqual((False, "water"), can(5))
        self.assertEqual((False, "impassable"), can(6))
        self.assertEqual((True, ""), can(7))
        self.assertEqual((False, "stack_limit"), can(8))
        self.assertEqual((True, ""), can(9))  # own civilian: warrior may share the plot
        self.assertEqual((False, "occupied_foreign"), can(10))

    def test_local_civic_falls_back_to_gamecore(self):
        lua = LuaRuntime()
        lua.execute("Civ6Ai_Util = { Log = function() end }")
        lua.execute((ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Apply.lua").read_text(encoding="utf-8"))
        lua.execute("""
          CALLS = {}
          Game = { GetLocalPlayer = function() return 0 end }
          GameInfo = { Civics = { CIVIC_CODE_OF_LAWS = { Index = 3 } } }
          PlayerOperationTypes = nil
          ExposedMembers = { Civ6Ai = { SetCivicForPlayer = function(p, i) table.insert(CALLS, p * 100 + i) return true, '' end } }
          Civ6Ai_Apply._IsNetworkMultiplayer = function() return false end
        """)
        ok, reason = lua.eval("function() local ok, r = Civ6Ai_Apply._SetResearchCivic(0, { civic_id = 'CIVIC_CODE_OF_LAWS' }) return ok, r end")()
        self.assertTrue(ok, reason)
        self.assertEqual(3, lua.globals().CALLS[1])


INGAME_STUBS = r"""
include = function() end
PULSES = {}
TICKS = {}
NOW = 1000
Game = { GetLocalPlayer = function() return 0 end, GetCurrentGameTurn = function() return 27 end }
Civ6Ai_Config = { Initialize = function() end, IsAutotest = function() return true end,
  IsManagedSeat = function() return true end, IsSidecarLive = function() return false end,
  ShouldRunBridge = function() return true end,
  ManagedSeatsList = function() return {0, 1, 2, 3, 4} end }
Civ6Ai_SeatExperiment = { Initialize = function() end, OnPlayerTurnActivated = function() end }
Civ6Ai_Autotest = { Initialize = function() end }
Civ6Ai_HostChannel = { Initialize = function() end }
Civ6Ai_Chat = { Initialize = function() end }
Civ6Ai_OrderChannel = { Initialize = function() end }
Civ6Ai_Util = { Log = function() end, InitializeTickPump = function() end, ProbeIo = function() end,
  ScheduleTick = function(fn) table.insert(TICKS, fn) end }
Civ6Ai_Bridge = { RunTurnPulse = function(p) table.insert(PULSES, p) end, RunChatPulse = function() end,
  _LogOnce = function() end, IsLoadScreenClosed = function() return true end,
  _WallClock = function() return NOW end }
LuaEvents = { Civ6Ai_PlayerTurnStartComplete = { Add = function() end } }
Events = { PlayerTurnActivated = { Add = function() end } }
ExposedMembers = { Civ6Ai = {} }
function RUN_TICKS()
  local keep = {}
  for _, fn in ipairs(TICKS) do if fn() then table.insert(keep, fn) end end
  TICKS = keep
end
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LocalSeatTurnStartTests(unittest.TestCase):
    """P0 snapshotted at LocalPlayerTurnBegin, before its movement was restored."""

    def _lua(self):
        lua = LuaRuntime()
        lua.execute(INGAME_STUBS)
        lua.execute((ROOT / "mod/Civ6Ai/InGame/Civ6Ai_InGame.lua").read_text(encoding="utf-8"))
        return lua

    def test_local_pulse_waits_for_gamecore_turn_start_complete(self):
        lua = self._lua()
        g = lua.globals()
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete = { [0] = 26 }")
        g.Civ6Ai_OnLocalPlayerTurnBegin()
        lua.execute("RUN_TICKS()")
        self.assertEqual(0, len(g.PULSES))
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete[0] = 27; RUN_TICKS()")
        self.assertEqual(1, len(g.PULSES))
        lua.execute("RUN_TICKS()")
        self.assertEqual(1, len(g.PULSES))

    def test_local_pulse_immediate_when_turn_start_already_complete(self):
        lua = self._lua()
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete = { [0] = 27 }")
        lua.globals().Civ6Ai_OnLocalPlayerTurnBegin()
        self.assertEqual(1, len(lua.globals().PULSES))

    def test_local_pulse_times_out_after_load(self):
        lua = self._lua()
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete = {}")
        lua.globals().Civ6Ai_OnLocalPlayerTurnBegin()
        lua.execute("RUN_TICKS()")
        self.assertEqual(0, len(lua.globals().PULSES))
        lua.execute("NOW = NOW + 9; RUN_TICKS()")
        self.assertEqual(1, len(lua.globals().PULSES))

    def test_other_seats_pulse_only_after_their_queue_ran(self):
        lua = self._lua()
        g = lua.globals()
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete = {}")
        g.Civ6Ai_OnPlayerTurnActivated(3, True)
        self.assertEqual(0, len(g.PULSES))
        g.Civ6Ai_OnPlayerTurnStartComplete(3)
        self.assertEqual([3], list(g.PULSES.values()))

    def test_other_seats_pulse_from_turn_start_mark(self):
        lua = self._lua()
        g = lua.globals()
        lua.execute("ExposedMembers.Civ6Ai.TurnStartComplete = { [1] = 27 }")
        g.Civ6Ai_InGame._WatchTurnStarts()
        self.assertEqual([1], list(g.PULSES.values()))


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class LocalSeatLegalityTests(unittest.TestCase):
    """P0 was offered water/mountain steps and found_city on its own capital tile."""

    def _lua(self, can_move, can_found, ui_found=True):
        lua = LuaRuntime()
        lua.execute("Civ6Ai_Util = { Log = function() end }")
        lua.execute((ROOT / "mod/Civ6Ai/InGame/Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))
        lua.execute("Game = { GetLocalPlayer = function() return 0 end }")
        lua.execute("UI_FOUND = %s" % ("true" if ui_found else "false"))
        lua.execute("UnitManager = { CanStartOperation = function() return UI_FOUND end }")
        lua.execute(
            "ExposedMembers = { Civ6Ai = { CanMoveUnitToForPlayer = function() return %s, '' end,"
            " CanFoundCityForPlayer = function() return %s, '' end } }"
            % ("true" if can_move else "false", "true" if can_found else "false")
        )
        lua.execute("UNIT = { GetOwner = function() return 0 end, GetID = function() return 262146 end }")
        return lua

    def test_local_seat_move_consults_gamecore(self):
        self.assertFalse(self._lua(False, True).eval("Civ6Ai_Snapshot._GameCoreCanMove(UNIT, 20, 24)"))
        self.assertTrue(self._lua(True, True).eval("Civ6Ai_Snapshot._GameCoreCanMove(UNIT, 19, 25)"))

    def test_local_found_needs_gamecore_site_check(self):
        op = "{ Hash = 7 }"
        self.assertFalse(self._lua(True, False).eval("Civ6Ai_Snapshot._CanFoundCity(UNIT, %s)" % op))
        self.assertTrue(self._lua(True, True).eval("Civ6Ai_Snapshot._CanFoundCity(UNIT, %s)" % op))
        self.assertFalse(self._lua(True, True, ui_found=False).eval("Civ6Ai_Snapshot._CanFoundCity(UNIT, %s)" % op))


if __name__ == "__main__":
    unittest.main()
