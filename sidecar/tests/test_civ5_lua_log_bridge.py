"""Tests for Civ5 Lua.log snapshot reconstruction and stale-turn drop."""
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
from civ5_lua_log_bridge import (
    keep_current_snapshot_blobs,
    parse_blob_lines,
    process_lua_log_blobs,
)


def _frame(
    payload: str,
    session: str = "live-1",
    player: int = 0,
    turn: int = 1,
    live: int = 1,
    kind: str = "snapshot",
) -> str:
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    chunk_size = 180
    chunks = [encoded[i : i + chunk_size] for i in range(0, max(len(encoded), 1), chunk_size)]
    blob_id = f"{session}_{player}_{turn}_{kind}"
    lines = [
        f"Civ5Ai_InGame: CIV5AI|blob|begin|{kind}|{blob_id}|{len(chunks)}|{live}|{player}|{turn}|{session}"
    ]
    for index, chunk in enumerate(chunks):
        lines.append(f"Civ5Ai_InGame: CIV5AI|blob|c|{blob_id}|{index}|{chunk}")
    lines.append(f"Civ5Ai_InGame: CIV5AI|blob|end|{blob_id}")
    return "\n".join(lines) + "\n"


class Civ5LuaLogBridgeTests(unittest.TestCase):
    def test_parse_roundtrip(self):
        payload = json.dumps({"decision": {"player_id": "PLAYER_0", "turn": 2}})
        blobs = parse_blob_lines(_frame(payload, turn=2))
        self.assertEqual(1, len(blobs))
        self.assertEqual("snapshot", blobs[0]["kind"])
        self.assertEqual(0, blobs[0]["player"])
        self.assertEqual(2, blobs[0]["turn"])
        self.assertEqual(payload, blobs[0]["payload"])

    def test_keep_current_snapshot_drops_older_turns(self):
        text = (
            _frame('{"turn":0}', turn=0)
            + _frame('{"turn":1}', turn=1)
            + _frame('{"turn":7}', turn=7)
        )
        blobs = keep_current_snapshot_blobs(parse_blob_lines(text))
        self.assertEqual(1, len(blobs))
        self.assertEqual(7, blobs[0]["turn"])
        self.assertEqual('{"turn":7}', blobs[0]["payload"])

    def test_keep_current_snapshot_drops_old_chat_when_snapshot_moved_on(self):
        text = _frame('{"chat":0}', turn=0, kind="snapshot_chat") + _frame('{"turn":5}', turn=5)
        blobs = keep_current_snapshot_blobs(parse_blob_lines(text))
        self.assertEqual(1, len(blobs))
        self.assertEqual("snapshot", blobs[0]["kind"])
        self.assertEqual(5, blobs[0]["turn"])

    def test_keep_current_snapshot_keeps_same_turn_chat(self):
        text = _frame('{"turn":4}', turn=4) + _frame('{"chat":4}', turn=4, kind="snapshot_chat")
        blobs = keep_current_snapshot_blobs(parse_blob_lines(text))
        kinds = [blob["kind"] for blob in blobs]
        self.assertEqual({"snapshot", "snapshot_chat"}, set(kinds))
        self.assertTrue(all(blob["turn"] == 4 for blob in blobs))

    def test_process_runs_only_latest_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lua_log = root / "Lua.log"
            lua_log.write_text(
                _frame('{"turn":0}', session="sess", turn=0)
                + _frame('{"turn":3}', session="sess", turn=3)
                + _frame('{"turn":8}', session="sess", turn=8),
                encoding="utf-8",
            )
            civ5ai = root / "civ5ai"
            civ5ai.mkdir()
            ran_turns = []

            def fake_run(job, repo):
                args = job["args"]
                state = Path(args[args.index("--state") + 1])
                ran_turns.append(json.loads(state.read_text(encoding="utf-8"))["turn"])
                player_dir = Path(args[args.index("--session-dir") + 1])
                (player_dir / "decision.json").write_text('{"commands":[]}\n', encoding="utf-8")

            with mock.patch("civ5_lua_log_bridge._run_job", side_effect=fake_run):
                with mock.patch("civ5_pending_apply.publish_from_player_dir", return_value=True):
                    ran = process_lua_log_blobs(lua_log, civ5ai, ROOT, python="python")
            self.assertEqual(1, ran)
            self.assertEqual([8], ran_turns)
            snapshot = civ5ai / "sessions" / "sess" / "PLAYER_0" / "snapshot.json"
            self.assertEqual('{"turn":8}', snapshot.read_text(encoding="utf-8"))

    def test_parse_skips_blob_with_missing_chunk(self):
        payload = json.dumps({"decision": {"player_id": "PLAYER_0", "turn": 2, "pad": "x" * 200}})
        text = _frame(payload, turn=2)
        lines = text.splitlines()
        chunk_indexes = [i for i, line in enumerate(lines) if "|blob|c|" in line]
        self.assertGreater(len(chunk_indexes), 1)
        del lines[chunk_indexes[-1]]
        blobs = parse_blob_lines("\n".join(lines) + "\n")
        self.assertEqual([], blobs)

    def test_complete_log_bytes_holds_partial_last_line(self):
        from civ5_lua_log_bridge import _complete_log_bytes

        complete, rest = _complete_log_bytes(b"full\npartial")
        self.assertEqual(b"full\n", complete)
        self.assertEqual(b"partial", rest)


if __name__ == "__main__":
    unittest.main()
