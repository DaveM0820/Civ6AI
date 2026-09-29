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
    publish_empty_for_turn,
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

    def _player_dir(self, tmp, turn=3, decision_turn=None, commands=None):
        player_dir = Path(tmp) / "sessions" / "autotest-1" / "PLAYER_2"
        player_dir.mkdir(parents=True)
        (player_dir / "snapshot.json").write_text(json.dumps({"decision": {"turn": turn}}), encoding="utf-8")
        decision = {
            "metrics": {"turn": turn if decision_turn is None else decision_turn},
            "commands": commands if commands is not None else [
                {"kind": "move_unit", "command_id": "CMD_1", "arguments": {}}
            ],
            "validated": {"chat_messages": []},
        }
        (player_dir / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        return player_dir

    def test_publish_does_not_wait_and_publishes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = self._player_dir(tmp)
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=None):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True) as publish:
                    with mock.patch("civ6_pending_apply.wait_for_apply_confirmation") as wait:
                        with mock.patch("civ6_startup_log.log_event"):
                            self.assertTrue(publish_from_player_dir(player_dir))
                            self.assertTrue(publish_from_player_dir(player_dir))
            publish.assert_called_once()
            self.assertEqual((2, 3), publish.call_args.args[2:4])
            wait.assert_not_called()
            self.assertIn("id=", (player_dir / "apply_turn_3.done").read_text(encoding="utf-8"))

    def test_publish_waits_when_confirmation_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = self._player_dir(tmp)
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text("", encoding="utf-8")
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=lua_log):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True):
                    with mock.patch("civ6_pending_apply.wait_for_apply_confirmation", return_value=False):
                        with mock.patch("civ6_startup_log.log_event"):
                            ok = publish_from_player_dir(player_dir, confirm_seconds=1)
            self.assertFalse(ok)

    def test_stale_decision_turn_is_not_republished(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = self._player_dir(tmp, turn=1, decision_turn=11)
            with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True) as publish:
                self.assertFalse(publish_from_player_dir(player_dir))
            publish.assert_not_called()

    def test_empty_answer_for_current_turn_publishes_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = self._player_dir(tmp, commands=[])
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=None):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True) as publish:
                    with mock.patch("civ6_startup_log.log_event"):
                        self.assertTrue(publish_from_player_dir(player_dir))
            self.assertEqual({"commands": [], "chat_messages": []}, json.loads(publish.call_args.args[0]))

    def test_publish_empty_for_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = self._player_dir(tmp)
            with mock.patch("civ6_lua_log_bridge.default_lua_log", return_value=None):
                with mock.patch("civ6_pending_apply.publish_pending_apply", return_value=True) as publish:
                    with mock.patch("civ6_startup_log.log_event"):
                        self.assertTrue(publish_empty_for_turn(player_dir))
            self.assertEqual(3, publish.call_args.args[3])

    def test_publish_pending_apply_succeeds_without_inject(self):
        with mock.patch("civ6_host_channel.inject_apply_payload", return_value=False) as inject:
            with mock.patch("civ6_host_channel.write_pending_apply_lua", return_value=2) as write_lua:
                with mock.patch.dict("os.environ", {}, clear=True):
                    ok = publish_pending_apply('{"commands":[]}', "sess", 1, 2)
        self.assertTrue(ok)
        write_lua.assert_called_once_with('{"commands":[]}', "sess", 1, 2, kind="turn")
        inject.assert_not_called()

    def test_publish_pending_apply_fails_when_nothing_written(self):
        with mock.patch("civ6_host_channel.write_pending_apply_lua", return_value=0):
            self.assertFalse(publish_pending_apply('{"commands":[]}', "sess", 1, 2))


if __name__ == "__main__":
    unittest.main()
