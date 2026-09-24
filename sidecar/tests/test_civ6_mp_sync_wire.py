"""Pure-Python checks for Civ6Ai M2 mp_move wire format (mirrors Civ6Ai_MpSync.lua)."""
from __future__ import annotations

import re
import unittest

MOVE_RE = re.compile(
    r"^CIV6AI\|mp_move\|([^|]+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)$"
)
PROBE_RE = re.compile(
    r"^CIV6AI\|mp_sync_probe\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)$"
)


def encode_move(seq: str, player_id: int, unit_id: int, x: int, y: int) -> str:
    return f"CIV6AI|mp_move|{seq}|{player_id}|{unit_id}|{x}|{y}"


def encode_probe(player_id: int, unit_id: int, x: int, y: int) -> str:
    return f"CIV6AI|mp_sync_probe|{player_id}|{unit_id}|{x}|{y}"


class Civ6MpSyncWireTests(unittest.TestCase):
    def test_encode_parse_move(self) -> None:
        wire = encode_move("3.0.1", 2, 131073, 55, 36)
        match = MOVE_RE.match(wire)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual("3.0.1", match.group(1))
        self.assertEqual(("2", "131073", "55", "36"), match.groups()[1:])

    def test_encode_parse_probe(self) -> None:
        wire = encode_probe(1, 65536, 10, 12)
        match = PROBE_RE.match(wire)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(("1", "65536", "10", "12"), match.groups())

    def test_reject_garbage(self) -> None:
        self.assertIsNone(MOVE_RE.match("CIV6AI|mp_move|bad"))
        self.assertIsNone(PROBE_RE.match("hello"))
        self.assertIsNone(MOVE_RE.match("CIV6AI|chat|hi"))


if __name__ == "__main__":
    unittest.main()
