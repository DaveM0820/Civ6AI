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
from civ6_lua_log_bridge import _decode_blob_payload, parse_blob_lines, process_lua_log_blobs


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

    def test_parse_utf8_great_work_name_pieta(self):
        payload = json.dumps(
            {
                "governance": {
                    "great_works": [
                        {"work": "GREATWORK_PIETA", "kind": "GREATWORKOBJECT_SCULPTURE", "name": "Pietà (Sculpture)"}
                    ]
                }
            },
            ensure_ascii=False,
        )
        blobs = parse_blob_lines(_frame(payload))
        self.assertEqual(1, len(blobs))
        self.assertIn("Pietà", blobs[0]["payload"])
        self.assertEqual(payload, blobs[0]["payload"])

    def test_parse_legacy_corrupt_utf8_blob_recovers(self):
        """Lua %s+ used to drop 0xA0 continuation bytes (e.g. à in Pietà)."""
        corrupt = b'{"name":"Piet\xc3 (Sculpture)"}'
        encoded = base64.b64encode(corrupt).decode("ascii")
        blob_id = "sess_0_1_snapshot"
        lines = "\n".join(
            [
                f"Civ6Ai_InGame: CIV6AI|blob|begin|snapshot|{blob_id}|1|0|0|1|sess",
                f"Civ6Ai_InGame: CIV6AI|blob|c|{blob_id}|0|{encoded}",
                f"Civ6Ai_InGame: CIV6AI|blob|end|{blob_id}",
            ]
        )
        blobs = parse_blob_lines(lines + "\n")
        self.assertEqual(1, len(blobs))
        self.assertIn("\ufffd", blobs[0]["payload"])

    def test_decode_blob_payload_strict_then_replace(self):
        good = "Pietà".encode("utf-8")
        self.assertEqual("Pietà", _decode_blob_payload(good))
        bad = b"Piet\xc3"
        self.assertEqual("Piet\ufffd", _decode_blob_payload(bad))

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

    def test_sidecar_timeout_does_not_publish_empty_apply(self):
        payload = '{"ok":true}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lua_log = root / "Lua.log"
            lua_log.write_text(_frame(payload, session="sess"), encoding="utf-8")
            civ6ai = root / "civ6ai"
            civ6ai.mkdir()
            published = []

            def boom(job, repo):
                raise TimeoutError("timed out after 180 seconds")

            with mock.patch("civ6_lua_log_bridge._run_job", side_effect=boom), \
                    mock.patch("civ6_pending_apply.publish_empty_for_turn", side_effect=lambda *a, **k: published.append(True)):
                ran = process_lua_log_blobs(lua_log, civ6ai, ROOT, python="python")
            self.assertEqual(0, ran)
            self.assertEqual([], published)


class BlobSplitAcrossReadsTests(unittest.TestCase):
    """A read ending mid-blob used to advance past the begin line and drop the snapshot."""

    def _run(self, lua_log, civ6ai, ran_jobs):
        def fake_run(job, repo):
            ran_jobs.append(job)
            player_dir = Path(job["args"][2])
            (player_dir / "decision.json").write_text('{"commands":[]}\n', encoding="utf-8")
            (player_dir / "apply_commands.json").write_text('{"commands":[]}\n', encoding="utf-8")

        with mock.patch("civ6_lua_log_bridge._run_job", side_effect=fake_run), \
                mock.patch("civ6_lua_log_bridge.time.sleep"), \
                mock.patch("civ6_pending_apply.publish_from_player_dir", create=True):
            return process_lua_log_blobs(lua_log, civ6ai, ROOT, python="python")

    def test_split_blob_is_processed_once_complete(self):
        import civ6_lua_log_bridge as bridge

        bridge._PROCESSED_BLOBS.clear()
        first = _frame('{"p":4}', session="sess", player=4, turn=26)
        second = _frame('{"p":0,"x":"' + "a" * 2000 + '"}', session="sess", player=0, turn=27)
        cut = len(second) // 2
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lua_log = root / "Lua.log"
            civ6ai = root / "civ6ai"
            civ6ai.mkdir()
            lua_log.write_text(first + second[:cut], encoding="utf-8")
            jobs = []
            self.assertEqual(1, self._run(lua_log, civ6ai, jobs))
            with lua_log.open("a", encoding="utf-8") as handle:
                handle.write(second[cut:] + "Civ6Ai_InGame: CIV6AI|bridge|inbox_wait|player=0\n")
            self.assertEqual(1, self._run(lua_log, civ6ai, jobs))
            snap = civ6ai / "sessions" / "sess" / "PLAYER_0" / "snapshot.json"
            self.assertIn('"p":0', snap.read_text(encoding="utf-8"))
            # Nothing new: no re-run of either blob.
            self.assertEqual(0, self._run(lua_log, civ6ai, jobs))
            self.assertEqual(2, len(jobs))

    def test_incomplete_blob_offset(self):
        from civ6_lua_log_bridge import incomplete_blob_offset

        whole = _frame("{}", session="s").encode()
        self.assertIsNone(incomplete_blob_offset(whole))
        partial = b"noise line\n" + whole[: len(whole) - 30]
        self.assertEqual(len(b"noise line\n"), incomplete_blob_offset(partial))
        self.assertEqual(3, incomplete_blob_offset(b"ab\ncd"))

if __name__ == "__main__":
    unittest.main()
