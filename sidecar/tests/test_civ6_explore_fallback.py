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


class BuilderTests(unittest.TestCase):
    def _snap(self):
        return {
            "decision": {"player_id": "PLAYER_0", "turn": 40},
            "your_units": [{"unit_id": "UNIT_5", "unit_type_id": "UNIT_BUILDER", "domain_id": "DOMAIN_LAND",
                            "plot_id": "PLOT_45_14", "needs_orders": True}],
            "known_map": {"plots": [
                {"x": 43, "y": 14, "water": False, "peak": False, "revealed_owner_id": "PLAYER_0", "resource_id": "RESOURCE_WHEAT"},
                {"x": 44, "y": 15, "water": False, "peak": False, "revealed_owner_id": "PLAYER_0"},
                {"x": 45, "y": 14, "water": False, "peak": False, "revealed_owner_id": "PLAYER_0", "city_id": "CITY_1"},
                {"x": 40, "y": 11, "water": False, "peak": False, "revealed_owner_id": None},
            ]},
            "legal_commands": [],
            "history": {"command_results": []},
        }

    def test_builder_sites_listed_resource_first(self):
        import os

        from sidecar import civ6_prompt_coaching as coaching
        snap = self._snap()
        previous = os.environ.get("CIV4AI_MAP_IMAGE_CADENCE")
        os.environ["CIV4AI_MAP_IMAGE_CADENCE"] = "100"
        try:
            line = coaching.builder_fact_lines("builder_1", snap["your_units"][0], snap)[0]
        finally:
            if previous is None:
                os.environ.pop("CIV4AI_MAP_IMAGE_CADENCE", None)
            else:
                os.environ["CIV4AI_MAP_IMAGE_CADENCE"] = previous
        self.assertIn("(43,14) Wheat", line)
        self.assertLess(line.index("(43,14)"), line.index("(44,15)"))
        self.assertNotIn("(45,14)", line)

    def test_builder_tile_list_dropped_when_map_image_attached(self):
        from sidecar import civ6_prompt_coaching as coaching
        snap = self._snap()
        line = coaching.builder_fact_lines("builder_1", snap["your_units"][0], snap)[0]
        self.assertNotIn("(43,14)", line)
        self.assertIn("blank owned tile", line)

    def test_builder_improve_commands_keep_coordinates(self):
        from sidecar import civ6_prompt_coaching as coaching
        snap = self._snap()
        snap["legal_commands"] = [_improve_cmd(43, 14, "IMPROVEMENT_FARM", unit="UNIT_5")]
        line = coaching.builder_fact_lines("builder_1", snap["your_units"][0], snap)[0]
        self.assertIn("Improve(43,14,IMPROVEMENT_FARM)", line)
        self.assertNotIn("(44,15)", line)

    def test_builder_move_outside_borders_dropped(self):
        snap = self._snap()
        out = {"command_id": "CMD_UNIT_5_moveto_40_11", "kind": "move_unit", "arguments": {"unit_id": "UNIT_5", "target_x": 40, "target_y": 11}}
        ok = {"command_id": "CMD_UNIT_5_moveto_43_14", "kind": "move_unit", "arguments": {"unit_id": "UNIT_5", "target_x": 43, "target_y": 14}}
        kept, dropped = ar.filter_repeat_failures(snap, [out, ok])
        self.assertEqual([c["command_id"] for c in kept], ["CMD_UNIT_5_moveto_43_14"])
        self.assertTrue(any("outside your borders" in d for d in dropped))


if __name__ == "__main__":
    unittest.main()


def _improve_cmd(x, y, imp, unit="UNIT_7"):
    return {"command_id": f"CMD_{unit}_{imp}_improve_{x}_{y}", "kind": "move_unit",
            "fixed_arguments": {"unit_id": unit, "target_x": x, "target_y": y, "improvement_id": imp,
                                "intent": "improve", "A": 2, "G": 1, "goal": 1}}


def test_improve_token_and_resolve():
    from sidecar import civ6_command_wire as cw
    snap = {"legal_commands": [_improve_cmd(3, 4, "IMPROVEMENT_FARM"), _improve_cmd(3, 4, "IMPROVEMENT_MINE"),
                               _improve_cmd(9, 9, "IMPROVEMENT_FARM")]}
    assert cw.unit_command_token(snap["legal_commands"][0]) == "Improve(3,4,IMPROVEMENT_FARM)"
    assert cw.resolve_unit_token(snap, "UNIT_7", "Improve(3,4,IMPROVEMENT_MINE)").endswith("MINE_improve_3_4")
    assert cw.resolve_unit_token(snap, "UNIT_7", "Improve(3,4,MINE)").endswith("MINE_improve_3_4")
    moved = cw.resolve_unit_token(snap, "UNIT_7", "MoveTo(8,9)")
    assert moved is None or "improve" not in moved
    assert cw.resolve_unit_token(snap, "UNIT_7", "Improve(8,9,IMPROVEMENT_FARM)") is None
    assert any("Improve token unresolved: (8,9)" in note for note in cw.LAST_UNRESOLVED)


def test_improve_substitute_nearest():
    from sidecar import civ6_apply_results as ar
    snap = {"legal_commands": [_improve_cmd(3, 4, "IMPROVEMENT_FARM"), _improve_cmd(9, 9, "IMPROVEMENT_FARM")],
            "your_units": [{"unit_id": "UNIT_7", "unit_type_id": "UNIT_BUILDER"}],
            "decision": {"player_id": "PLAYER_0"},
            "known_map": {"plots": [{"x": 10, "y": 9, "revealed_owner_id": "PLAYER_1"}]}}
    move = {"command_id": "x", "kind": "move_unit",
            "arguments": {"unit_id": "UNIT_7", "target_x": 10, "target_y": 9}}
    kept, dropped = ar.filter_repeat_failures(snap, [move])
    assert kept == []
    assert any("outside your borders" in note for note in dropped)
    assert not any("instead" in note for note in dropped)


def test_one_site_per_builder():
    from sidecar import civ6_apply_results as ar
    a = _improve_cmd(3, 4, "IMPROVEMENT_FARM", "UNIT_1")
    b = _improve_cmd(3, 4, "IMPROVEMENT_FARM", "UNIT_2")
    b2 = _improve_cmd(5, 5, "IMPROVEMENT_MINE", "UNIT_2")
    snap = {"legal_commands": [a, b, b2]}
    cmds = [{"command_id": x["command_id"], "kind": "move_unit", "arguments": dict(x["fixed_arguments"])} for x in (a, b)]
    notes: list[str] = []
    out = ar._one_site_per_builder(snap, cmds, notes)
    assert [c["arguments"]["target_x"] for c in out] == [3, 3] and notes == []


def test_clip_sentence_and_usable_deal():
    from sidecar import civ6_wire, civ6_diplomacy
    t = "First sentence here. Second one is long " + "x" * 400
    assert civ6_wire._clip_sentence(t, 100) == "First sentence here."
    snap = {"your_empire": {"research": {"known_tech_ids": ["TECH_MINING"]}}}
    assert civ6_diplomacy._usable_problem(snap, [{"res": "RESOURCE_IRON", "n": 1}])
    assert civ6_diplomacy._usable_problem(snap, [{"res": "RESOURCE_SILK", "n": 1}]) is None
