"""Watchdog stall restarts: triggers, human long turns, backoff, deterministic errors."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "testbed"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import civ6_stall_restart as sr  # noqa: E402

CFG = {"stall_minutes": 8, "fail_count": 2, "fail_seat_percent": 60, "gap_minutes": 10, "max_per_turn": 3}


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + ",123"


def _fail(t: float, seat: int, err: str = "BoundaryError: game: Additional properties are not allowed") -> str:
    return (f"{_stamp(t)} WARNING Pending snapshot sidecar failed C:\\x\\sessions\\s\\PLAYER_{seat}: "
            f"Command 'x' returned non-zero exit status 1. | Traceback (most recent call last):\n"
            f"  File \"run_civ6.py\", line 1\nsidecar.pipeline_v2.{err}\n")


def _ok(t: float, seat: int) -> str:
    return f"{_stamp(t)} INFO Pending apply published player={seat} turn=4 kind=turn id=abc\n"


class StallDecisionTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def test_all_seats_failing_restarts_with_last_error(self):
        text = "".join(_fail(self.now - 60 + i, s) for i in range(2) for s in (1, 2, 3))
        failures = sr.recent_failures(text, self.now - 3600)
        d = sr.decide(now=self.now, activity={"pending": [], "last_activity": self.now, "turn": 1},
                      failures=failures, seats=3, state={}, cfg=CFG)
        self.assertEqual("restart", d["action"])
        self.assertIn("seats 1,2,3", d["reason"])
        self.assertIn("BoundaryError", d["last_error"])

    def test_a_success_breaks_the_streak(self):
        text = _fail(self.now - 50, 1) + _fail(self.now - 40, 1) + _ok(self.now - 30, 1) + _fail(self.now - 20, 1)
        failures = sr.recent_failures(text, self.now - 3600)
        bad, seats = sr.failing_seats(failures, 1, 2, 60)
        self.assertFalse(bad)

    def test_one_seat_failing_out_of_five_is_not_enough(self):
        text = _fail(self.now - 50, 1) + _fail(self.now - 40, 1)
        failures = sr.recent_failures(text, self.now - 3600)
        d = sr.decide(now=self.now, activity={"pending": [], "last_activity": self.now, "turn": 3},
                      failures=failures, seats=5, state={}, cfg=CFG)
        self.assertEqual("none", d["action"])

    def test_pending_snapshot_idle_too_long_restarts(self):
        d = sr.decide(now=self.now, activity={"pending": ["PLAYER_2"], "last_activity": self.now - 9 * 60, "turn": 7},
                      failures=[], seats=4, state={}, cfg=CFG)
        self.assertEqual("restart", d["action"])
        self.assertIn("PLAYER_2", d["reason"])

    def test_human_long_turn_with_nothing_pending_is_left_alone(self):
        d = sr.decide(now=self.now, activity={"pending": [], "last_activity": self.now - 3600, "turn": 7},
                      failures=[], seats=4, state={}, cfg=CFG)
        self.assertEqual("none", d["action"])

    def test_backoff_and_per_turn_cap(self):
        act = {"pending": ["PLAYER_1"], "last_activity": self.now - 3600, "turn": 9}
        state = {"last_restart": self.now - 5 * 60}
        self.assertEqual("blocked", sr.decide(now=self.now, activity=act, failures=[], seats=2, state=state, cfg=CFG)["action"])
        state = {"last_restart": self.now - 20 * 60, "per_turn": {"9": 3}}
        d = sr.decide(now=self.now, activity=act, failures=[], seats=2, state=state, cfg=CFG)
        self.assertEqual("blocked", d["action"])
        self.assertIn("3 restarts", d["why"])

    def test_same_error_after_a_restart_is_deterministic(self):
        text = "".join(_fail(self.now - 60 + i, s) for i in range(2) for s in (1, 2))
        failures = sr.recent_failures(text, self.now - 3600)
        first = sr.decide(now=self.now, activity={"pending": [], "last_activity": self.now, "turn": 1},
                          failures=failures, seats=2, state={}, cfg=CFG)
        state = sr.record_restart({}, self.now - 30 * 60, first)
        again = sr.decide(now=self.now, activity={"pending": [], "last_activity": self.now, "turn": 1},
                          failures=failures, seats=2, state=state, cfg=CFG)
        self.assertEqual("blocked", again["action"])
        self.assertIn("deterministic", again["why"])

    def test_session_activity_pending_when_snapshot_is_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            seat = Path(tmp) / "PLAYER_1"
            seat.mkdir()
            (seat / "decision.json").write_text("{}")
            (seat / "snapshot.json").write_text(json.dumps({"decision": {"turn": 4}}))
            old = time.time() - 600
            os.utime(seat / "decision.json", (old, old))
            act = sr.session_activity(Path(tmp), [])
            self.assertEqual(["PLAYER_1"], act["pending"])
            self.assertEqual(4, act["turn"])
            os.utime(seat / "decision.json", None)
            os.utime(seat / "snapshot.json", (old, old))
            self.assertEqual([], sr.session_activity(Path(tmp), [])["pending"])

    def test_settings_have_defaults(self):
        cfg = sr.settings_values()
        self.assertEqual(8, cfg["stall_minutes"])
        self.assertEqual(10, cfg["gap_minutes"])
        self.assertEqual(3, cfg["max_per_turn"])


if __name__ == "__main__":
    unittest.main()


class WatchdogStallCheckTests(unittest.TestCase):
    def test_stall_check_restarts_once_then_backs_off(self):
        import importlib.util
        import civ6_paths

        spec = importlib.util.spec_from_file_location("civ6ai_watchdog_sc", ROOT / "scripts" / "live_watchdog.py")
        wd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wd)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "civ6ai"
            seat = root / "sessions" / "S" / "PLAYER_1"
            seat.mkdir(parents=True)
            (root / "runtime.json").write_text(json.dumps({"session_id": "S"}))
            (seat / "snapshot.json").write_text(json.dumps({"decision": {"turn": 2}}))
            old = time.time() - 3600
            os.utime(seat / "snapshot.json", (old, old))
            pid_file = Path(tmp) / "runtime" / "live_workers.json"
            (pid_file.parent / "logs").mkdir(parents=True)
            orig = civ6_paths.civ6ai_root
            civ6_paths.civ6ai_root = lambda: root
            try:
                spawned = []
                self.assertEqual("restart", wd.stall_check(pid_file, spawn_restart=spawned.append))
                self.assertEqual(1, len(spawned))
                self.assertEqual("blocked", wd.stall_check(pid_file, spawn_restart=spawned.append))
                self.assertEqual(1, len(spawned))
            finally:
                civ6_paths.civ6ai_root = orig
