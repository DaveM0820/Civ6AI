"""Shared chat gate: novelty + per-recipient cadence, and the shared tone/diplomacy prompt text."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from sidecar import civ6_apply_results as results
from sidecar import civ6_prompt_coaching as coaching
from sidecar import settings


def _snap(turn=10, events=None, inbox=None):
    return {
        "decision": {"turn": turn, "player_id": "PLAYER_1"},
        "history": {"public_events": list(events or []), "diplomacy_events": []},
        "diplomacy": {"private_inbox": list(inbox or [])},
        "legal_commands": [],
    }


def _dm(turn, to, text):
    return {"turn": turn, "kind": "CHAT_PRIVATE", "text": text, "affected_ids": ["PLAYER_1", to]}


def _pub(turn, text):
    return {"turn": turn, "kind": "CHAT_PUBLIC", "text": text, "affected_ids": ["PLAYER_1"]}


DM2 = {"target": "player", "target_player_id": "PLAYER_2", "text": "Your scouts look lost. Need a map?"}
ALL = {"target": "all", "text": "Whoever settled next to that volcano: bold choice."}


class CadenceGateTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in settings.INT_DEFAULTS:
            os.environ.pop(name, None)

    def test_recent_dm_to_same_recipient_is_dropped(self):
        snap = _snap(events=[_dm(9, "PLAYER_2", "Lovely weather on your border, shame about your army.")])
        kept, dropped = results.filter_repeat_public_chat(snap, [DM2])
        self.assertEqual(kept, [])
        self.assertTrue(any("too soon" in d for d in dropped))

    def test_dm_after_cooldown_is_kept(self):
        snap = _snap(events=[_dm(6, "PLAYER_2", "Lovely weather on your border, shame about your army.")])
        kept, _ = results.filter_repeat_public_chat(snap, [DM2])
        self.assertEqual(kept, [DM2])

    def test_other_recipient_not_blocked(self):
        snap = _snap(events=[_dm(9, "PLAYER_3", "Lovely weather on your border, shame about your army.")])
        kept, _ = results.filter_repeat_public_chat(snap, [DM2])
        self.assertEqual(kept, [DM2])

    def test_inbox_dm_from_recipient_lets_reply_through(self):
        snap = _snap(events=[_dm(9, "PLAYER_2", "Lovely weather on your border, shame about your army.")],
                     inbox=[{"turn": 10, "from_player_id": "PLAYER_2", "text": "Want to trade iron?"}])
        kept, _ = results.filter_repeat_public_chat(snap, [DM2])
        self.assertEqual(kept, [DM2])

    def test_war_event_lets_line_through(self):
        snap = _snap(events=[
            _dm(9, "PLAYER_2", "Lovely weather on your border, shame about your army."),
            {"turn": 10, "kind": "WAR_DECLARED", "text": "war", "affected_ids": ["PLAYER_2", "PLAYER_1"]},
        ])
        kept, _ = results.filter_repeat_public_chat(snap, [DM2])
        self.assertEqual(kept, [DM2])

    def test_diplomatic_order_at_recipient_lets_line_through(self):
        snap = _snap(events=[_dm(9, "PLAYER_2", "Lovely weather on your border, shame about your army.")])
        snap["legal_commands"] = [{"command_id": "CMD_DIPLO_EXECUTE_DEAL_1", "kind": "execute_deal",
                                   "fixed_arguments": {"target_player_id": "PLAYER_2"}}]
        commands = [{"command_id": "CMD_DIPLO_EXECUTE_DEAL_1", "arguments": {}}]
        kept, _ = results.filter_repeat_public_chat(snap, [DM2], commands)
        self.assertEqual(kept, [DM2])

    def test_unit_order_is_not_an_event(self):
        self.assertFalse(results._is_diplo_word("CMD_MOVE_UNIT_WARRIOR_1"))
        self.assertTrue(results._is_diplo_word("DENOUNCED"))

    def test_public_cooldown_and_setting(self):
        snap = _snap(events=[_pub(8, "The river is mine, enjoy the desert.")])
        kept, _ = results.filter_repeat_public_chat(snap, [ALL])
        self.assertEqual(kept, [])
        with mock.patch.dict(os.environ, {"CIV6AI_CHAT_PUBLIC_COOLDOWN_TURNS": "0"}):
            kept, _ = results.filter_repeat_public_chat(snap, [ALL])
        self.assertEqual(kept, [ALL])

    def test_one_line_per_recipient_per_turn(self):
        second = dict(DM2, text="Also, your capital is in a swamp.")
        kept, dropped = results.filter_repeat_public_chat(_snap(), [DM2, second])
        self.assertEqual(kept, [DM2])
        self.assertTrue(dropped)

    def test_prompt_lists_resting_recipients(self):
        snap = _snap(events=[_dm(9, "PLAYER_2", "Lovely weather on your border, shame about your army.")])
        lines = results.chat_cadence_lines(snap, lambda pid: "Gilgamesh")
        self.assertEqual(len(lines), 1)
        self.assertIn("Gilgamesh", lines[0])
        self.assertIn("turn 12", lines[0])
        self.assertEqual(results.chat_cadence_lines(_snap()), [])

    def test_get_int_clamps_and_defaults(self):
        with mock.patch.dict(os.environ, {"CIV6AI_CHAT_RECIPIENT_COOLDOWN_TURNS": "999"}):
            self.assertEqual(settings.get_int("CIV6AI_CHAT_RECIPIENT_COOLDOWN_TURNS"), 50)
        with mock.patch.dict(os.environ, {"CIV6AI_CHAT_RECIPIENT_COOLDOWN_TURNS": "x"}):
            self.assertEqual(settings.get_int("CIV6AI_CHAT_RECIPIENT_COOLDOWN_TURNS"), 3)


class SharedPromptTextTests(unittest.TestCase):
    def test_tone_is_lobby_and_friendly(self):
        low = coaching.CIV6_LOBBY_CHAT_TONE.lower()
        for word in ("lobby", "trash talk", "never hostile", "personality"):
            self.assertIn(word, low)

    def test_diplomacy_psychology(self):
        low = coaching.CIV6_DIPLOMACY_PSYCHOLOGY.lower()
        for word in ("deals", "friendships", "trust", "broken promises", "backstab"):
            self.assertIn(word, low)


if __name__ == "__main__":
    unittest.main()
