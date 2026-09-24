"""Tests for snapshot-based prompt gates."""
from __future__ import annotations

import unittest

from sidecar import prompt_gates


def _snap(**overrides):
    snapshot = {
        "decision": {"turn": 8},
        "game": {
            "era_id": "ERA_ANCIENT",
            "game_speed_id": "GAMESPEED_STANDARD",
            "world_size_id": "WORLDSIZE_STANDARD",
            "map_script": "Continents",
        },
        "personality": {
            "civilization_id": "CIVILIZATION_GREECE",
            "leader_id": "LEADER_ALEXANDER",
        },
        "your_empire": {
            "unit_counts": {"settlers": 0},
            "research": {"known_tech_ids": ["TECH_AGRICULTURE"]},
        },
        "your_cities": [{"city_id": "CITY_ATHENS"}],
        "legal_commands": [{"kind": "move_unit"}],
    }
    snapshot.update(overrides)
    return snapshot


class PromptGateTests(unittest.TestCase):
    def test_empty_spec_always_matches(self):
        self.assertTrue(prompt_gates.matches(_snap(), {}))
        self.assertTrue(prompt_gates.matches(_snap(), None))

    def test_turn_and_speed_scale(self):
        spec = {"turn_lte": 15, "turn_scale": "speed"}
        self.assertTrue(prompt_gates.matches(_snap(), spec))
        late = _snap()
        late["decision"] = {"turn": 16}
        self.assertFalse(prompt_gates.matches(late, spec))
        marathon = _snap()
        marathon["decision"] = {"turn": 40}
        marathon["game"] = {**marathon["game"], "game_speed_id": "GAMESPEED_MARATHON"}
        self.assertTrue(prompt_gates.matches(marathon, spec))

    def test_tech_civ_map(self):
        self.assertTrue(prompt_gates.matches(_snap(), {"tech_all": ["TECH_AGRICULTURE"]}))
        self.assertFalse(prompt_gates.matches(_snap(), {"tech_all": ["TECH_SAILING"]}))
        self.assertTrue(prompt_gates.matches(_snap(), {"tech_none": ["TECH_ASTRONOMY"]}))
        self.assertTrue(prompt_gates.matches(_snap(), {"civ_in": ["CIVILIZATION_GREECE"]}))
        self.assertFalse(prompt_gates.matches(_snap(), {"civ_in": ["CIVILIZATION_ZULU"]}))
        self.assertTrue(prompt_gates.matches(_snap(), {"map_script_in": ["continents"]}))
        self.assertTrue(prompt_gates.matches(_snap(), {"world_size_in": ["WORLDSIZE_STANDARD"]}))

    def test_any_not_and_gated_lines(self):
        spec = {"any": [{"turn_lte": 5}, {"era_in": ["ERA_ANCIENT"]}]}
        late_ancient = _snap()
        late_ancient["decision"] = {"turn": 40}
        self.assertTrue(prompt_gates.matches(late_ancient, spec))
        classical = _snap()
        classical["decision"] = {"turn": 40}
        classical["game"] = {**classical["game"], "era_id": "ERA_CLASSICAL"}
        self.assertFalse(prompt_gates.matches(classical, spec))
        self.assertFalse(prompt_gates.matches(_snap(), {"not": {"civ_in": ["CIVILIZATION_GREECE"]}}))
        lines = prompt_gates.gated_lines(
            _snap(),
            [
                {"when": {"turn_lte": 15}, "lines": ["early"]},
                {"when": {"turn_gte": 50}, "lines": ["late"]},
            ],
        )
        self.assertEqual(["early"], lines)


if __name__ == "__main__":
    unittest.main()
