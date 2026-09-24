"""Tests for Civ6 autotest early progression recovery."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))

from civ6_autotest_recovery import game_started, turn_has_progressed
from civ6_autotest_watchdog import ProgressSnapshot


class Civ6AutotestRecoveryTests(unittest.TestCase):
    def test_turn_has_progressed_past_turn_1(self):
        stuck = ProgressSnapshot(autotest_max_turn=1, journal_lines=1, player_snapshots=1)
        self.assertFalse(turn_has_progressed(stuck))
        advanced = ProgressSnapshot(autotest_max_turn=2, journal_lines=2, turn_metrics_lines=1)
        self.assertTrue(turn_has_progressed(advanced))

    def test_game_started_detects_snapshot(self):
        progress = ProgressSnapshot(player_snapshots=1)
        self.assertTrue(game_started(progress, None))


if __name__ == "__main__":
    unittest.main()
