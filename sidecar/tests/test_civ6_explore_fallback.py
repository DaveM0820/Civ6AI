import unittest

from sidecar import civ6_apply_results as ar
from sidecar import civ6_command_wire as wire


def _snapshot(results=None):
    return {
        "decision": {"player_id": "PLAYER_0", "turn": 22},
        "your_units": [{"unit_id": "UNIT_262146", "unit_type_id": "UNIT_SCOUT", "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_42_11"}],
        "known_map": {"plots": [
            {"x": 43, "y": 10, "water": False, "peak": True},
            {"x": 44, "y": 12, "water": False, "peak": False},
        ]},
        "legal_commands": [{"command_id": "CMD_explore_UNIT_262146", "kind": "explore", "fixed_arguments": {"unit_id": "UNIT_262146"}}],
        "history": {"command_results": results or []},
    }


def _move(x, y):
    return {"command_id": f"CMD_UNIT_262146_moveto_{x}_{y}", "kind": "move_unit", "turn": 22,
            "player_id": "PLAYER_0", "arguments": {"unit_id": "UNIT_262146", "target_x": x, "target_y": y}}


class ExploreFallbackTests(unittest.TestCase):
    def test_mountain_move_becomes_explore(self):
        kept, dropped = ar.filter_repeat_failures(_snapshot(), [_move(43, 10)])
        self.assertEqual([c["command_id"] for c in kept], ["CMD_explore_UNIT_262146"])
        self.assertEqual(kept[0]["arguments"], {"unit_id": "UNIT_262146"})
        self.assertTrue(any("mountain" in d for d in dropped))

    def test_repeat_failure_found_from_command_id(self):
        failed = [{"turn": 21, "kind": ar.KIND_FAILED, "order_kind": "move_unit", "unit": "scout_1",
                   "reason": "illegal_move:impassable",
                   "summary": "Last turn you tried to move scout_1 to (44,12) but it failed: impassable",
                   "affected_ids": ["CMD_UNIT_262146_moveto_44_12", "UNIT_262146"]}]
        kept, dropped = ar.filter_repeat_failures(_snapshot(failed), [_move(44, 12)])
        self.assertEqual([c["command_id"] for c in kept], ["CMD_explore_UNIT_262146"])
        self.assertTrue(any("repeat of T21" in d for d in dropped))

    def test_legal_move_kept(self):
        kept, _ = ar.filter_repeat_failures(_snapshot(), [_move(44, 12)])
        self.assertEqual([c["command_id"] for c in kept], ["CMD_UNIT_262146_moveto_44_12"])

    def test_foundcity_with_coords_is_settle(self):
        snap = _snapshot()
        self.assertEqual(wire.resolve_unit_token(snap, "UNIT_262146", "FoundCity(44,12)"),
                         wire.resolve_unit_token(snap, "UNIT_262146", "Settle(44,12)"))


if __name__ == "__main__":
    unittest.main()
