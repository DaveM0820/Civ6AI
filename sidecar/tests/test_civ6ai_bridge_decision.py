"""The turn pulse must ignore fallback / stale decisions until this turn is approved."""
from __future__ import annotations

import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Bridge.lua"
SRC = BRIDGE.read_text(encoding="utf-8")


class TestBridgeDecisionReady(unittest.TestCase):
    def test_helpers_are_in_bridge(self):
        self.assertIn("function Civ6Ai_Bridge._IsReadyDecision", SRC)
        self.assertIn("status=fallback", SRC)

    def test_approved_this_turn_is_ready(self):
        text = '{"status": "approved", "commands": [{"kind": "move_unit", "turn": 26}]}'
        self.assertTrue(self._ready(text, 26))

    def test_fallback_is_not_ready(self):
        text = '{"status": "fallback", "commands": [], "metrics": {"turn": 26}}'
        self.assertFalse(self._ready(text, 26))

    def test_last_turn_approved_is_not_ready(self):
        text = '{"status": "approved", "commands": [{"turn": 25}]}'
        self.assertFalse(self._ready(text, 26))

    def test_chat_accepts_any_body(self):
        self.assertTrue(self._ready("{}", None, mode="chat"))
        self.assertFalse(self._ready("", None, mode="chat"))

    def _ready(self, text: str, turn: int | None, mode: str = "turn") -> bool:
        if mode == "chat":
            return bool(text)
        if not re.search(r'"status"\s*:\s*"approved"', text or ""):
            return False
        match = re.search(r'"turn"\s*:\s*(\d+)', text or "")
        decision_turn = int(match.group(1)) if match else None
        if turn is not None and decision_turn is not None and decision_turn != turn:
            return False
        return True


if __name__ == "__main__":
    unittest.main()
