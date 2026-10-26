"""Prompt fixes from the root-cause review: city strikes, war wording, gold, governors, chat."""
import unittest

from sidecar import civ6_combat_wire as cw
from sidecar import civ6_governance as gov
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire


def _ctx(previews, cities):
    return {"decision": {"player_id": "PLAYER_0", "turn": 40}, "your_cities": cities,
            "civ6": {"combat": {"previews": previews}}, "known_players": [], "your_units": []}


class CityStrikeTests(unittest.TestCase):
    def test_city_row_names_the_city_and_needs_walls(self):
        walled = {"city_id": "CITY_1", "name": "Athens", "defense": {"wall_max_hp": 100}}
        bare = {"city_id": "CITY_2", "name": "Sparta", "defense": {"wall_max_hp": 0}}
        rows = [
            {"city_id": "CITY_1", "unit_id": None, "target_x": 3, "target_y": 4, "attacker_strength": 20, "defender_strength": 10, "ranged": True},
            {"city_id": "CITY_2", "unit_id": None, "target_x": 3, "target_y": 5, "attacker_strength": 20, "defender_strength": 10, "ranged": True},
            {"city_id": "CITY_1", "unit_id": None, "target_x": 3, "target_y": 6, "attacker_strength": 0, "defender_strength": 10, "ranged": True},
        ]
        text = "\n".join(cw.strike_lines(_ctx(rows, [walled, bare])))
        self.assertNotIn("None", text)
        self.assertIn("rangeStrike(3,4)", text)
        self.assertNotIn("(3,5)", text)
        self.assertNotIn("(3,6)", text)


class AdviceTests(unittest.TestCase):
    def test_barbarians_only_is_not_called_war(self):
        ctx = _ctx([], [])
        ctx["civ6"]["combat"]["hostiles"] = [{"x": 1, "y": 1, "owner": "PLAYER_63"}]
        text = "\n".join(civ6_wire._advice_section(ctx))
        self.assertNotIn("You are at war", text)
        self.assertIn("not at war", text)


class GoldNagTests(unittest.TestCase):
    def test_no_gold_nag_without_a_sink_and_upgrade_named_when_one_exists(self):
        snap = {"your_empire": {"gold": 900, "gold_per_turn": 10}, "legal_commands": []}
        note, _ = coaching.civ6_idle_resources(snap)
        self.assertTrue(note is None or "gold" not in note)
        snap["legal_commands"] = [{"command_id": "C1", "kind": "upgrade_unit",
                                   "fixed_arguments": {"unit_id": "UNIT_5", "unit_type_id": "UNIT_SWORDSMAN", "cost": 100}}]
        note, _ = coaching.civ6_idle_resources(snap)
        self.assertIn("upgrade", note)
        self.assertIn("Swordsman", note)


class GovernorTests(unittest.TestCase):
    def test_unplaced_governor_gets_an_assign_row(self):
        gv = {"supported": True, "appointed": [{"id": "GOVERNOR_PINGALA"}, {"id": "GOVERNOR_MAGNUS", "city": "Athens"}]}
        self.assertEqual(["PINGALA"], gov._unplaced_governors(gv))


class ChatOriginalityTests(unittest.TestCase):
    def test_prompt_asks_for_original_chat(self):
        from sidecar import civ6_adapter

        wire = civ6_wire.build_civ6_model_wire_text(civ6_adapter.build_classical_golden_snapshot())
        self.assertIn("always make original statements unique to your own personality and situation", wire)
        self.assertIn("Do not repeat or paraphrase what other players have said in chat", wire)


if __name__ == "__main__":
    unittest.main()
