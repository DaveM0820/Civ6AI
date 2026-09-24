"""Tests for Lua.log snapshot dump reconstruction."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
from civ6_lua_log_bridge import parse_blob_lines, process_lua_log_blobs


def _frame(payload: str, session: str = "autotest-1", player: int = 0, turn: int = 1, live: int = 0) -> str:
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    chunk_size = 180
    chunks = [encoded[i : i + chunk_size] for i in range(0, max(len(encoded), 1), chunk_size)]
    blob_id = f"{session}_{player}_{turn}_snapshot"
    lines = [
        f"Civ6Ai_InGame: CIV6AI|blob|begin|snapshot|{blob_id}|{len(chunks)}|{live}|{player}|{turn}|{session}"
    ]
    for index, chunk in enumerate(chunks):
        lines.append(f"Civ6Ai_InGame: CIV6AI|blob|c|{blob_id}|{index}|{chunk}")
    lines.append(f"Civ6Ai_InGame: CIV6AI|blob|end|{blob_id}")
    return "\n".join(lines) + "\n"


class Civ6LuaLogBridgeTests(unittest.TestCase):
    def test_parse_roundtrip(self):
        payload = json.dumps({"legal_commands": [{"kind": "found_city"}], "decision": {"player_id": "PLAYER_0"}})
        blobs = parse_blob_lines(_frame(payload))
        self.assertEqual(1, len(blobs))
        self.assertEqual("snapshot", blobs[0]["kind"])
        self.assertEqual(0, blobs[0]["player"])
        self.assertEqual(payload, blobs[0]["payload"])

    def test_process_writes_snapshot_and_runs_job(self):
        payload = '{"ok":true}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lua_log = root / "Lua.log"
            lua_log.write_text(_frame(payload, session="sess"), encoding="utf-8")
            civ6ai = root / "civ6ai"
            civ6ai.mkdir()
            ran_jobs = []

            def fake_run(job, repo):
                ran_jobs.append((job, repo))
                player_dir = Path(job["args"][2])
                (player_dir / "decision.json").write_text('{"commands":[]}\n', encoding="utf-8")
                (player_dir / "apply_commands.json").write_text('{"commands":[]}\n', encoding="utf-8")

            with mock.patch("civ6_lua_log_bridge._run_job", side_effect=fake_run):
                ran = process_lua_log_blobs(lua_log, civ6ai, ROOT, python="python")
            self.assertEqual(1, ran)
            snapshot = civ6ai / "sessions" / "sess" / "PLAYER_0" / "snapshot.json"
            self.assertEqual(payload, snapshot.read_text(encoding="utf-8"))
            self.assertEqual(1, len(ran_jobs))
            mirror = lua_log.parent / "civ6ai" / "sessions" / "sess" / "PLAYER_0" / "decision.json"
            self.assertTrue(mirror.is_file())


if __name__ == "__main__":
    unittest.main()
