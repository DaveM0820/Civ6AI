"""Tests for Civ6 autotest stall watchdog."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
from civ6_autotest_watchdog import collect_progress, run_watchdog


class Civ6AutotestWatchdogTests(unittest.TestCase):
    def test_collect_progress_counts_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions" / "test" / "PLAYER_0"
            sessions.mkdir(parents=True)
            (sessions / "journal.jsonl").write_text('{"status":"approved"}\n', encoding="utf-8")
            (root / "autotest").mkdir()
            (root / "autotest" / "autotest.log").write_text("pulse|turn=1|player=0\n", encoding="utf-8")
            progress = collect_progress(root, None)
            self.assertEqual(1, progress.journal_lines)
            self.assertEqual(1, progress.autotest_pulses)

    def test_stall_triggers_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "autotest").mkdir()

            def fake_capture(out_dir: Path, reason: str) -> dict:
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / "fullscreen.png"
                path.write_bytes(b"png")
                return {"reason": reason, "paths": {"fullscreen": str(path)}}

            clock = [0.0, 0.0, 100.0, 100.0, 200.0, 200.0, 400.0]

            def fake_monotonic() -> float:
                return clock.pop(0) if clock else 400.0

            with mock.patch("civ6_autotest_watchdog.civ6_process_running", return_value=True):
                with mock.patch("civ6_autotest_watchdog.process_host_io", return_value=0):
                    with mock.patch("civ6_autotest_watchdog.tail_lua_log_to_startup", return_value=0):
                        with mock.patch("civ6_autotest_watchdog.time.sleep", side_effect=lambda _: None):
                            with mock.patch("civ6_autotest_watchdog.time.monotonic", side_effect=fake_monotonic):
                                result = run_watchdog(
                                    root,
                                    None,
                                    timeout_seconds=200,
                                    stall_seconds=30,
                                    poll_seconds=30,
                                    screenshot_cooldown=10,
                                    capture_fn=fake_capture,
                                )
            self.assertEqual("timeout", result["status"])
            events_path = root / "autotest" / "stall_events.jsonl"
            self.assertTrue(events_path.is_file())
            lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(row.get("event") == "stall_screenshot" for row in lines))


if __name__ == "__main__":
    unittest.main()
