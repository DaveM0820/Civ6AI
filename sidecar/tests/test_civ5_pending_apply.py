"""Tests for Civ5 pending apply: commands plus Civ4-style chat on the same turn."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
from civ5_pending_apply import (
    apply_confirmed,
    load_apply_payload,
    load_chat_apply_payload,
    publish_from_player_dir,
    publish_pending_apply,
    wait_for_apply_confirmation,
)
from sidecar import run_civ5


def _mailbox_player_dir(root: Path, turn: int = 0, player: int = 0, session_id: str = "sess") -> Path:
    player_dir = root / session_id / f"PLAYER_{player}"
    player_dir.mkdir(parents=True)
    (player_dir / "snapshot.json").write_text(
        json.dumps({"decision": {"turn": turn, "player_id": f"PLAYER_{player}"}}),
        encoding="utf-8",
    )
    return player_dir


def _write_mailbox(player_dir: Path, payload: dict, turn: int = 0, player: int = 0, session_id: str = "sess") -> Path:
    path = player_dir / run_civ5.apply_mailbox_filename(session_id, player, turn)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class Civ5PendingApplyTests(unittest.TestCase):
    def test_load_apply_payload_merges_chat_from_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = _mailbox_player_dir(Path(tmp))
            _write_mailbox(
                player_dir,
                {"commands": [{"kind": "set_research_tech", "command_id": "CMD_1", "arguments": {}}]},
            )
            (player_dir / "decision.json").write_text(
                json.dumps(
                    {
                        "validated": {
                            "chat_messages": [{"target": "all", "text": "Harun greets you."}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = json.loads(load_apply_payload(player_dir) or "{}")
            self.assertEqual(1, len(payload["commands"]))
            self.assertEqual(1, len(payload["chat_messages"]))
            self.assertEqual("Harun greets you.", payload["chat_messages"][0]["text"])

    def test_load_apply_payload_prefers_apply_commands_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = _mailbox_player_dir(Path(tmp))
            _write_mailbox(
                player_dir,
                {
                    "commands": [{"kind": "set_research_tech", "command_id": "CMD_1", "arguments": {}}],
                    "chat_messages": [{"target": "all", "text": "From apply."}],
                },
            )
            (player_dir / "decision.json").write_text(
                json.dumps(
                    {
                        "validated": {
                            "chat_messages": [{"target": "all", "text": "From decision."}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = json.loads(load_apply_payload(player_dir) or "{}")
            self.assertEqual("From apply.", payload["chat_messages"][0]["text"])

    def test_load_apply_payload_chat_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = _mailbox_player_dir(Path(tmp))
            _write_mailbox(
                player_dir,
                {
                    "commands": [],
                    "chat_messages": [{"target": "player", "target_player_id": "PLAYER_0", "text": "A word in private."}],
                },
            )
            payload = json.loads(load_apply_payload(player_dir) or "{}")
            self.assertEqual([], payload["commands"])
            self.assertEqual(1, len(payload["chat_messages"]))
            self.assertEqual("A word in private.", payload["chat_messages"][0]["text"])

    def test_load_apply_payload_salvages_valid_commands_from_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = _mailbox_player_dir(Path(tmp))
            path = player_dir / run_civ5.apply_mailbox_filename("sess", 0, 0)
            path.write_text(
                '{"commands":[{"kind":"set_research_tech","command_id":"CMD_research_TECH_POTTERY","arguments":{}},'
                '{"command_id":"CMD_move_UNIT_1002_46_10","kind":"move_unit"',
                encoding="utf-8",
            )
            payload = json.loads(load_apply_payload(player_dir) or "{}")
            ids = [item["command_id"] for item in payload["commands"]]
            self.assertIn("CMD_research_TECH_POTTERY", ids)
            self.assertIn("CMD_move_UNIT_1002_46_10", ids)

    def test_load_apply_payload_empty_commands_is_leftover_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = _mailbox_player_dir(Path(tmp))
            _write_mailbox(player_dir, {"commands": [], "chat_messages": []})
            payload = json.loads(load_apply_payload(player_dir) or "null")
            self.assertEqual([], payload["commands"])
            self.assertEqual([], payload["chat_messages"])

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

    def test_apply_confirmed_ignores_turnless_markers_from_prior_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "Civ5Ai_InGame: CIV5AI|bridge|pending_apply_ok|player=0\n"
                "Civ5Ai_HostInbox: CIV5AI|hostchannel|apply_pending|player=0\n"
                "Civ5Ai_HostInbox: CIV5AI|bridge|apply_skip_duplicate|player=1\n"
                "DiploCorner: CIV5AI|bridge|inbox_apply_done|player=0|attempts=1005\n",
                encoding="utf-8",
            )
            self.assertFalse(apply_confirmed(lua_log, 0, 3))
            self.assertFalse(apply_confirmed(lua_log, 0, 2))
            self.assertFalse(apply_confirmed(lua_log, 1, 2))
            self.assertFalse(apply_confirmed(lua_log, 0, 4))

    def test_apply_confirmed_accepts_inbox_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "Civ5Ai_InGame: CIV5AI|inbox|apply_ready|player=0|turn=3|len=42\n",
                encoding="utf-8",
            )
            self.assertTrue(apply_confirmed(lua_log, 0, 3))

    def test_apply_confirmed_requires_turn_specific_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text(
                "DiploCorner: CIV5AI|apply_payload|player=0|turn=17|commands=2|chat=1\n",
                encoding="utf-8",
            )
            self.assertFalse(apply_confirmed(lua_log, 0, 1))
            self.assertTrue(apply_confirmed(lua_log, 0, 17))

    def test_wait_for_apply_confirmation_accepts_new_inbox_apply_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text("prior|bridge|inbox_apply_done|player=0|attempts=10\n", encoding="utf-8")
            offset = lua_log.stat().st_size
            lua_log.write_text(
                lua_log.read_text(encoding="utf-8")
                + "DiploCorner: CIV5AI|bridge|inbox_apply_done|player=0|attempts=40\n",
                encoding="utf-8",
            )
            self.assertTrue(
                wait_for_apply_confirmation(
                    lua_log, 0, 3, timeout_seconds=0.5, start_offset=offset
                )
            )

    def test_publish_from_player_dir_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "sessions" / "autotest-1" / "PLAYER_0"
            player_dir.mkdir(parents=True)
            (player_dir / "snapshot.json").write_text(
                json.dumps({"decision": {"turn": 0, "player_id": "PLAYER_0"}}),
                encoding="utf-8",
            )
            mailbox = player_dir / run_civ5.apply_mailbox_filename("autotest-1", 0, 0)
            mailbox.write_text(
                json.dumps(
                    {
                        "commands": [{"kind": "move_unit", "command_id": "CMD_1", "arguments": {}}],
                        "chat_messages": [{"target": "all", "text": "On the move."}],
                    }
                ),
                encoding="utf-8",
            )
            lua_log = Path(tmp) / "Lua.log"
            lua_log.write_text("", encoding="utf-8")
            with mock.patch("civ5_lua_log_bridge.default_lua_log", return_value=lua_log):
                with mock.patch("civ5_pending_apply.publish_pending_apply", return_value=True) as publish:
                    with mock.patch("civ5_pending_apply.wait_for_apply_confirmation", return_value=True) as wait:
                        with mock.patch("civ5_startup_log.log_event"):
                            with mock.patch("civ5_host_channel.clear_pending_apply_lua"):
                                ok = publish_from_player_dir(player_dir)
            self.assertTrue(ok)
            publish.assert_called_once()
            wait.assert_called_once()
            sent = json.loads(publish.call_args[0][0])
            self.assertEqual("On the move.", sent["chat_messages"][0]["text"])

    def test_write_pending_apply_lua_uses_base64(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with mock.patch("civ5_host_channel.civ5_apply_pending_dirs", return_value=[directory]):
                from civ5_host_channel import write_pending_apply_lua

                payload = '{"commands":[],"chat_messages":[{"target":"all","text":"Hello"}]}'
                write_pending_apply_lua(payload, "sess-1", 2, 5)
            text = (directory / "apply_pending.lua").read_text(encoding="utf-8")
            self.assertIn("Civ5Ai_ApplyPendingB64", text)
            self.assertNotIn("Civ5Ai_ApplyPendingJson", text)

    def test_publish_pending_apply_delegates_to_inbox(self):
        with mock.patch("civ5_host_channel.inject_apply_payload", return_value=True) as inject:
            with mock.patch("civ5_host_channel.write_pending_apply_lua") as write_lua:
                ok = publish_pending_apply('{"commands":[],"chat_messages":[]}', "sess", 0, 2)
        self.assertTrue(ok)
        write_lua.assert_called_once_with('{"commands":[],"chat_messages":[]}', "sess", 0, 2)
        inject.assert_called_once_with('{"commands":[],"chat_messages":[]}', "sess", 0, 2)

    def test_write_decision_outputs_includes_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            run_civ5._write_decision_outputs(
                session_dir,
                {
                    "status": "ok",
                    "commands": [{"kind": "set_research_tech", "command_id": "CMD_1", "arguments": {"tech_id": "TECH_POTTERY"}}],
                    "validated": {
                        "chat_messages": [{"target": "all", "text": "We seek pottery."}],
                    },
                    "private": {"game_uuid": "sess", "player_id": "PLAYER_0", "turn": 4},
                },
                None,
            )
            apply_data = json.loads(
                (session_dir / run_civ5.apply_mailbox_filename("sess", 0, 4)).read_text(encoding="utf-8")
            )
            self.assertEqual(1, len(apply_data["commands"]))
            self.assertEqual("We seek pottery.", apply_data["chat_messages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
