import os
import unittest
from unittest import mock

from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_fallbacks as fallbacks


def _snap():
    return {
        "decision": {"player_id": "PLAYER_0", "turn": 5},
        "game": {"map_width": 40, "map_height": 40},
        "known_map": {"plots": []},
        "your_cities": [{"city_id": "CITY_1", "plot_id": "PLOT_20_20"}],
        "your_units": [
            {"unit_id": "UNIT_W", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
             "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_2_2", "movement": {"current": 2}},
            {"unit_id": "UNIT_SET", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_5_5",
             "settle": {"here_ok": False, "sites": [
                 {"x": 19, "y": 20, "dist": 2},  # too close to CITY_1
                 {"x": 9, "y": 5, "dist": 4},
                 {"x": 7, "y": 5, "dist": 2},
             ]}},
        ],
        "legal_commands": [],
    }


class FallbackLedgerTests(unittest.TestCase):
    def test_hints_cover_model_ordered_and_dropped_units(self):
        # Lua decides; the sidecar sends a target whatever the model ordered, so a
        # dropped or failed model order still leaves its unit a fallback.
        model = [{"kind": "move_unit", "arguments": {"unit_id": "UNIT_W", "target_x": 3, "target_y": 2}}]
        units = {h["arguments"]["unit_id"] for h in fallbacks.plan(_snap(), model)}
        self.assertEqual({"UNIT_W", "UNIT_SET"}, units)
        self.assertTrue(all(h["kind"] == "fallback_hint" for h in fallbacks.plan(_snap(), [])))

    def test_settler_hint_is_the_nearest_legal_listed_site_or_here(self):
        snap = _snap()
        hint = [h for h in fallbacks.unit_hints(snap) if h["arguments"]["unit_id"] == "UNIT_SET"][0]["arguments"]
        self.assertEqual(("settle", 4, 7, 5), (hint["role"], hint["role_code"], hint["target_x"], hint["target_y"]))
        snap["your_units"][1]["settle"]["here_ok"] = True
        hint = [h for h in fallbacks.unit_hints(snap) if h["arguments"]["unit_id"] == "UNIT_SET"][0]["arguments"]
        self.assertEqual((5, 5), (hint["target_x"], hint["target_y"]))

    def test_kill_switch_sends_no_hints(self):
        with mock.patch.dict(os.environ, {"CIV6AI_FALLBACK_LEDGER": "0"}):
            self.assertEqual([], fallbacks.plan(_snap(), []))

    def test_ledger_model_ok_wins_and_failed_model_yields_to_fallback(self):
        rows = [
            {"kind": "move_unit", "ok": True, "source": "model", "fixed_arguments": {"unit_id": "1"}},
            {"kind": "attack_target", "ok": True, "source": "fallback", "fixed_arguments": {"unit_id": "1"}},
            {"kind": "move_unit", "ok": False, "source": "model", "fixed_arguments": {"unit_id": "2"}},
            {"kind": "unit_posture_fortify", "ok": True, "source": "fallback", "fixed_arguments": {"unit_id": "2"}},
            {"kind": "move_unit", "ok": False, "source": "model", "fixed_arguments": {"unit_id": "3"}},
            {"kind": "fallback_hint", "ok": True, "source": "hint", "fixed_arguments": {"unit_id": "4"}},
        ]
        self.assertEqual({"unit:1": "model", "unit:2": "fallback", "unit:3": "model_failed"}, fallbacks.ledger(rows))

    def test_illegal_settle_is_rejected_not_redirected(self):
        snap = _snap()
        command_wire.LAST_UNRESOLVED.clear()
        self.assertIsNone(command_wire.resolve_unit_token(snap, "UNIT_SET", "Settle(19,20)"))
        self.assertTrue(any(n.startswith("Rejected last turn: Settle(19,20)") for n in command_wire.LAST_UNRESOLVED))
        self.assertEqual([], snap["legal_commands"])


if __name__ == "__main__":
    unittest.main()
