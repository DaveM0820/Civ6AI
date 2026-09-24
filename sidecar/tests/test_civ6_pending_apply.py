"""Tests for Civ6 pending apply publish path."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
from civ6_pending_apply import (
    apply_confirmed,
    load_apply_payload,
    load_chat_apply_payload,
    publish_apply_payload,
    publish_from_player_dir,
    publish_pending_apply,
    wait_for_apply_confirmation,
)


class Civ6PendingApplyTests(unittest.TestCase):
    def test_load_apply_payload_merges_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp)
            (player_dir / "apply_commands.json").write_text(
                json.dumps({"commands": [{"kind": "set_research_tech", "command_id": "CMD_1", "arguments": {}}]}),
                encoding="utf-8",
            )
            (player_dir / "decision.json").write_text(
                json.dumps(
                    {
                        "validated": {
                            "chat_messages": [{"target": "all", "text": "Saladin greets you."}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = json.loads(load_apply_payload(player_dir) or "{}")
            self.assertEqual(1, len(payload["commands"]))
            self.assertEqual(1, len(payload["chat_messages"]))
            self.assertEqual("Saladin greets you.", payload["chat_messages"][0]["text"])

    def test_load_chat_apply_payload_reads_decision_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp)
            (player_dir / "decision_chat.json").write_text(
                json.dumps(
                    {
                        "validated": {
                            "chat_messages": [{"target": "all", "text": "Gandhi replies."}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = json.loads(load_chat_apply_payload(player_dir) or "{}")
            self.assertEqual([], payload["commands"])
            self.assertEqual(1, len(payload["chat_messages"]))
            self.assertEqual("Gandhi replies.", payload["chat_messages"][0]["text"])

    def test_apply_confirmed_accepts_pending_apply_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "Civ6Ai_InGame: CIV6AI|bridge|pending_apply_ok|player=0\n",
                encoding="utf-8",
            )
            self.assertTrue(apply_confirmed(lua_log, 0, 3))

    def test_apply_confirmed_accepts_inbox_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "Civ6Ai_InGame: CIV6AI|inbox|apply_ready|player=0|turn=3|len=42\n",
                encoding="utf-8",
            )
            self.assertTrue(apply_confirmed(lua_log, 0, 3))

    def test_apply_confirmed_requires_turn_specific_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "Civ6Ai_InGame: CIV6AI|bridge|apply_payload|player=0|turn=17|commands=2\n",
                encoding="utf-8",
            )
            self.assertFalse(apply_confirmed(lua_log, 0, 1))
            self.assertTrue(apply_confirmed(lua_log, 0, 17))

    def test_publish_apply_payload_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "sessions" / "autotest-1" / "PLAYER_0"
            player_dir.mkdir(parents=True)
            (player_dir / "apply_commands.json").write_text(
                json.dumps({"commands": [{"kind": "move_unit", "command_id": "CMD_1", "arguments": {}}]}),
                encoding="utf-8",
            )
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text("", encoding="utf-8")
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=lua_log):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True) as publish:
                    with mock.patch("civ6_pending_apply.wait_for_apply_confirmation", return_value=True) as wait:
                        with mock.patch("civ6_startup_log.log_event"):
                            ok = publish_from_player_dir(player_dir)
            self.assertTrue(ok)
            publish.assert_called_once()
            wait.assert_called_once()

    def test_publish_apply_payload_returns_false_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "sessions" / "autotest-1" / "PLAYER_0"
            player_dir.mkdir(parents=True)
            (player_dir / "apply_commands.json").write_text(
                json.dumps({"commands": [{"kind": "move_unit", "command_id": "CMD_1", "arguments": {}}]}),
                encoding="utf-8",
            )
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text("", encoding="utf-8")
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=lua_log):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True):
                    with mock.patch("civ6_pending_apply.wait_for_apply_confirmation", return_value=False):
                        with mock.patch("civ6_startup_log.log_event"):
                            ok = publish_from_player_dir(player_dir)
            self.assertFalse(ok)

    def test_publish_apply_payload_skips_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "sessions" / "autotest-1" / "PLAYER_0"
            player_dir.mkdir(parents=True)
            marker = player_dir / "apply_turn_0.done"
            marker.write_text("done\n", encoding="utf-8")
            lua_log = Path(tmp) / "Lua.log"
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=lua_log):
                with mock.patch("civ6_pending_apply.apply_confirmed", return_value=True):
                    with mock.patch("civ6_pending_apply.wait_for_apply_confirmation") as wait:
                        ok = publish_apply_payload(
                            player_dir,
                            "autotest-1",
                            0,
                            0,
                            '{"commands":[]}',
                        )
            self.assertTrue(ok)
            wait.assert_not_called()

    def test_publish_pending_apply_delegates_to_inbox(self):
        with mock.patch("civ6_host_channel.inject_apply_payload", return_value=True) as inject:
            with mock.patch("civ6_host_channel.write_pending_apply_lua") as write_lua:
                ok = publish_pending_apply('{"commands":[]}', "sess", 0, 2)
        self.assertTrue(ok)
        write_lua.assert_called_once_with('{"commands":[]}', "sess", 2)
        inject.assert_called_once_with('{"commands":[]}', "sess", 0, 2)


if __name__ == "__main__":
    unittest.main()
