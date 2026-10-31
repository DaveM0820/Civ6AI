from sidecar import civ6_unit_trail as trail


def _snap(turn, own_plot, foreign=None):
    snap = {"decision": {"turn": turn}, "your_units": [{"unit_id": "UNIT_1", "plot_id": own_plot}]}
    snap["visible_other_units"] = [{"unit_id": "UNIT_9", "plot_id": foreign}] if foreign else []
    return snap


def test_previous_position_moves_and_stationary(tmp_path):
    assert trail.update(_snap(3, "PLOT_4_5", "PLOT_10_10"), tmp_path) == {}
    out = trail.update(_snap(4, "PLOT_5_5", "PLOT_10_10"), tmp_path)
    assert out["UNIT_1"] == "was at (4,5) on T3"
    assert out["UNIT_9"] == "stationary since T3"
    again = trail.update(_snap(4, "PLOT_5_5", "PLOT_10_10"), tmp_path)  # same-turn rerun
    assert again["UNIT_1"] == "was at (4,5) on T3"
    out = trail.update(_snap(6, "PLOT_5_5", "PLOT_11_10"), tmp_path)
    assert out["UNIT_1"] == "stationary since T4"
    assert out["UNIT_9"] == "was at (10,10) on T4"


def test_prompt_shows_previous_line(tmp_path):
    from sidecar import civ6_wire
    snap = {"_unit_trail": {"UNIT_1": "was at (4,5) on T3"}}
    assert civ6_unit_trail_text(snap) == "was at (4,5) on T3"
    assert hasattr(civ6_wire, "civ6_unit_trail")


def civ6_unit_trail_text(snap):
    return trail.text_for(snap, "UNIT_1")
