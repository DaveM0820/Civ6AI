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
    inbox_inject_enabled,
    inject_apply_payload,
    pending_apply_id,
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

    def _patched(self, tmp):
        mod_in_game = Path(tmp) / "InGame"
        mod_in_game.mkdir(parents=True)
        return mod_in_game, (
            mock.patch("civ6_host_channel.civ6_mod_in_game_dirs", return_value=[mod_in_game]),
            mock.patch("civ6_host_channel._queue_state_path", return_value=Path(tmp) / "queue.json"),
        )

    def test_write_pending_apply_lua_scopes_session_player_and_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod_in_game, (p1, p2) = self._patched(tmp)
            with p1, p2:
                written = write_pending_apply_lua('{"commands":[]}', "autotest-99", 2, 4)
                pending = (mod_in_game / "Civ6Ai_PendingApply.lua").read_text(encoding="utf-8")
                self.assertEqual(1, written)
                self.assertIn('["2:turn"]', pending)
                self.assertIn('session_id = "autotest-99"', pending)
                self.assertIn("player = 2,", pending)
                self.assertIn("turn = 4,", pending)
                self.assertIn("apply_id = ", pending)
                clear_pending_apply_lua()
                cleared = (mod_in_game / "Civ6Ai_PendingApply.lua").read_text(encoding="utf-8")
            self.assertIn("Civ6Ai_PendingApplyMeta = nil", cleared)
            self.assertNotIn("autotest-99", cleared)

    def test_seats_do_not_overwrite_each_other_and_old_sessions_drop(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod_in_game, (p1, p2) = self._patched(tmp)
            with p1, p2:
                write_pending_apply_lua('{"a":1}', "old-sess", 0, 9)
                write_pending_apply_lua('{"a":2}', "sess", 0, 1)
                write_pending_apply_lua('{"a":3}', "sess", 1, 1)
                write_pending_apply_lua('{"a":4}', "sess", 1, 1, kind="chat")
                pending = (mod_in_game / "Civ6Ai_PendingApply.lua").read_text(encoding="utf-8")
            self.assertNotIn("old-sess", pending)
            for key in ('["0:turn"]', '["1:turn"]', '["1:chat"]'):
                self.assertIn(key, pending)

    def test_pending_apply_id_is_stable_and_scoped(self):
        a = pending_apply_id("{}", "s", 1, 2)
        self.assertEqual(a, pending_apply_id("{}", "s", 1, 2))
        self.assertNotEqual(a, pending_apply_id("{}", "s", 1, 3))
        self.assertNotEqual(a, pending_apply_id("{}", "s", 2, 2))
        self.assertNotEqual(a, pending_apply_id("{}", "s", 1, 2, "chat"))

    def test_inject_missing_module_logs_once_and_returns_false(self):
        import civ6_host_channel as channel

        channel._INJECT_UNAVAILABLE_LOGGED = False
        with mock.patch.dict(sys.modules, {"civ6_ui_automation": None}):
            with self.assertLogs("civ6_host_channel", level="INFO") as logs:
                self.assertFalse(channel.inject_apply_lines(["x"]))
                self.assertFalse(channel.inject_apply_lines(["y"]))
        self.assertEqual(1, sum("inbox inject unavailable" in line for line in logs.output))

    def test_inbox_inject_is_opt_in(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(inbox_inject_enabled())
        with mock.patch.dict("os.environ", {"CIV6AI_INBOX_INJECT": "1"}):
            self.assertTrue(inbox_inject_enabled())


if __name__ == "__main__":
    unittest.main()
