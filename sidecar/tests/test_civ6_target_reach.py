from sidecar import civ6_combat_wire as cw


def test_target_reach_groups_units_by_target():
    ctx = {"your_units": [{"unit_id": "UNIT_1", "unit_type_id": "UNIT_ARCHER"},
                          {"unit_id": "UNIT_2", "unit_type_id": "UNIT_WARRIOR"}],
           "civ6": {"combat": {"previews": [
               {"unit_id": "UNIT_1", "target_x": 5, "target_y": 6, "ranged": True, "prediction": "MINOR_VICTORY", "defender_strength": 20},
               {"unit_id": "UNIT_2", "target_x": 5, "target_y": 6, "needs_move": True, "distance": 2, "defender_strength": 20},
           ]}}}
    lines = cw.target_reach_lines(ctx)
    assert len(lines) == 1 and "(5,6)" in lines[0] and "2 units" in lines[0]
    assert "can strike now" in lines[0] and "after a move" in lines[0]
