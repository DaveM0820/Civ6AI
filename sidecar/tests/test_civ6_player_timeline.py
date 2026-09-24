"""Tests for Civ VI player timeline builder."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMELINE_SCRIPT = ROOT / "scripts" / "testbed" / "civ6_player_timeline.py"


class Civ6PlayerTimelineTests(unittest.TestCase):
    def test_build_timeline_line(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            player = Path(tmp) / "PLAYER_1"
            player.mkdir(parents=True)
            (player / "journal.jsonl").write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "private": {"turn": 3, "player_id": "PLAYER_1"},
                        "response": {"thought": {"situation": "Scout east.", "strategy": "Expand."}},
                        "validated": {"commands": [{"command_id": "CMD_x"}]},
                        "metrics": {"wall_ms": 42},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            (player / "apply-results.jsonl").write_text(
                json.dumps(
                    {
                        "event": "apply_result",
                        "turn": 3,
                        "ok": True,
                        "kind": "set_research_tech",
                        "empire": {"gold": 5},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            out = player / "timeline.jsonl"
            proc = subprocess.run(
                [sys.executable, str(TIMELINE_SCRIPT), str(player), "--output", str(out)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr or proc.stdout)
            line = json.loads(out.read_text(encoding="utf-8").strip())
            self.assertEqual(3, line["turn"])
            self.assertEqual("Scout east.", line["thought_situation"])


if __name__ == "__main__":
    unittest.main()
