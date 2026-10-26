from sidecar import civ6_economy as econ


def _snap(turn, plot, ok_turn=None):
    hist = {"command_results": [{"kind": "APPLY_OK", "turn": ok_turn, "affected_ids": ["UNIT_1"]}]} if ok_turn else {}
    return {"decision": {"turn": turn}, "history": hist,
            "your_units": [{"unit_id": "UNIT_1", "plot_id": plot, "needs_orders": True}]}


def test_idle_for_counts_turns_since_move_or_ok_order(tmp_path):
    s = _snap(10, "PLOT_1_1"); econ.update_tracking(s, tmp_path)
    assert s["civ6"]["economy"]["tracking"]["idle_for"]["UNIT_1"] == 0
    s = _snap(13, "PLOT_1_1"); econ.update_tracking(s, tmp_path)
    assert s["civ6"]["economy"]["tracking"]["idle_for"]["UNIT_1"] == 3
    s = _snap(14, "PLOT_1_1", ok_turn=13); econ.update_tracking(s, tmp_path)
    assert s["civ6"]["economy"]["tracking"]["idle_for"]["UNIT_1"] == 1
    s = _snap(15, "PLOT_2_1"); econ.update_tracking(s, tmp_path)
    assert s["civ6"]["economy"]["tracking"]["idle_for"]["UNIT_1"] == 0
