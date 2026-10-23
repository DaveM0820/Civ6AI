"""Byte-identical prompt goldens for the current wire builder."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from sidecar import civ6_adapter
from sidecar import civ6_wire
from sidecar.tests.test_civ6_prompt_budget import _late_snapshot

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "fixtures" / "civ6"


def _write_or_compare(path: Path, text: str) -> str:
    body = text.replace("\r\n", "\n")
    if not path.is_file():
        path.write_text(body, encoding="utf-8")
    return body


def _t1_no_capital() -> dict:
    snap = civ6_adapter.build_classical_golden_snapshot()
    snap["decision"]["turn"] = 1
    snap["your_cities"] = []
    return snap


def _peace_expansion() -> dict:
    return civ6_adapter.build_classical_golden_snapshot()


def _war_in_reach() -> dict:
    snap = civ6_adapter.build_classical_golden_snapshot()
    for rival in snap.get("known_players") or []:
        if isinstance(rival, dict) and rival.get("player_id") == "PLAYER_1":
            relation = rival.setdefault("relation", {})
            relation["at_war"] = True
    civ6 = snap.setdefault("civ6", {})
    diplo = civ6.setdefault("diplomacy", {})
    diplo["majors"] = [{"player_id": "PLAYER_1", "at_war": True, "can_make_peace": True}]
    combat = civ6.setdefault("combat", {})
    combat["hostiles"] = [{
        "unit_id": "UNIT_ENEMY_1",
        "unit_type_id": "UNIT_WARRIOR",
        "owner_player_id": "PLAYER_1",
        "x": 16,
        "y": 23,
    }]
    snap["strategic_summary"]["military_alerts"] = [{
        "text": "Cleopatra's warrior is inside move range of Athens",
    }]
    return snap


def _late_game() -> dict:
    return _late_snapshot()


class ExtraGoldenPromptTests(unittest.TestCase):
    def test_classical_golden_still_matches(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        wire = civ6_wire.build_civ6_model_wire_text(snapshot).strip()
        golden = (GOLDEN_DIR / "prompt-turn-classical-golden.txt").read_text(encoding="utf-8-sig").strip()
        self.assertEqual(golden, wire)

    def test_t1_no_capital_prompt_is_blessed(self):
        self._assert_prompt("prompt-t1-no-capital-golden.txt", _t1_no_capital())

    def test_peace_expansion_prompt_is_blessed(self):
        self._assert_prompt("prompt-peace-expansion-golden.txt", _peace_expansion())

    def test_war_in_reach_prompt_is_blessed(self):
        self._assert_prompt("prompt-war-in-reach-golden.txt", _war_in_reach())

    def test_late_game_prompt_is_blessed(self):
        self._assert_prompt("prompt-late-game-golden.txt", _late_game())

    def _assert_prompt(self, name: str, snapshot: dict) -> None:
        path = GOLDEN_DIR / name
        snap = copy.deepcopy(snapshot)
        text = civ6_wire.build_civ6_model_wire_text(snap).replace("\r\n", "\n")
        expected = _write_or_compare(path, text)
        self.assertEqual(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"), expected)
        self.assertEqual(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"), text)


class MemoryDirHygieneTests(unittest.TestCase):
    def test_thought_memory_uses_env_override(self):
        import os
        import tempfile
        from pathlib import Path

        from sidecar import run_civ6

        previous = os.environ.get("CIV6AI_MEMORY_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CIV6AI_MEMORY_DIR"] = tmp
            try:
                path = run_civ6._thought_memory_path(None, "gate0-test", "PLAYER_0")
            finally:
                if previous is None:
                    os.environ.pop("CIV6AI_MEMORY_DIR", None)
                else:
                    os.environ["CIV6AI_MEMORY_DIR"] = previous
            self.assertEqual(Path(tmp), path.parent)
            self.assertNotEqual(Path("memory"), path.parent)
            repo_memory = ROOT / "memory" / "gate0-test_PLAYER_0.json"
            self.assertFalse(str(path).startswith(str(ROOT / "memory")))
            self.assertNotEqual(path, repo_memory)
