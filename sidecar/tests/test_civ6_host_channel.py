"""Tests for Civ6 hidden inbox apply inject path."""
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
from civ6_host_channel import (
    build_apply_lines,
    clear_pending_apply_lua,
    inject_apply_payload,
    write_pending_apply_lua,
)


class Civ6HostChannelTests(unittest.TestCase):
    def test_build_apply_lines_round_trip(self):
        payload = json.dumps({"commands": [{"kind": "move_unit", "command_id": "CMD_1", "arguments": {}}]})
        lines = build_apply_lines(payload, "autotest-1", 2, 5)
        self.assertTrue(lines[0].startswith("CIV6AI|apply|begin|"))
        self.assertTrue(lines[-1].startswith("CIV6AI|apply|end|"))
        apply_id = lines[0].split("|")[3]
        chunks = {}
        for line in lines[1:-1]:
            parts = line.split("|")
            chunk_id = parts[3]
            index = int(parts[4])
            data = parts[5]
            self.assertEqual(apply_id, chunk_id)
            chunks[index] = data
        encoded = "".join(chunks[i] for i in sorted(chunks))
        self.assertEqual(payload, base64.b64decode(encoded).decode("utf-8"))

    def test_inject_apply_payload_uses_inbox(self):
        payload = '{"commands":[]}'
        with mock.patch("civ6_host_channel.inject_apply_lines", return_value=True) as inject:
            ok = inject_apply_payload(payload, "sess", 0, 1)
        self.assertTrue(ok)
        inject.assert_called_once()
        lines = inject.call_args.args[0]
        self.assertTrue(any("CIV6AI|apply|begin|" in line for line in lines))

    def test_write_pending_apply_lua_scopes_session_and_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod_in_game = Path(tmp) / "InGame"
            mod_in_game.mkdir(parents=True)
            with mock.patch("civ6_host_channel.civ6_mod_in_game_dirs", return_value=[mod_in_game]):
                write_pending_apply_lua('{"commands":[]}', "autotest-99", 4)
                pending = (mod_in_game / "Civ6Ai_PendingApply.lua").read_text(encoding="utf-8")
                self.assertIn('session_id = "autotest-99"', pending)
                self.assertNotIn("turn =", pending)
                clear_pending_apply_lua()
                cleared = (mod_in_game / "Civ6Ai_PendingApply.lua").read_text(encoding="utf-8")
            self.assertIn("Civ6Ai_PendingApplyMeta = nil", cleared)


if __name__ == "__main__":
    unittest.main()
