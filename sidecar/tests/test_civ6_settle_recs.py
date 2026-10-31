from sidecar.civ6_command_wire import game_settle_recommendations


def test_game_settle_recommendations_labels_and_dedupes():
    snap = {"civ6": {"settle_recommended": [{"x": 3, "y": 4}, {"x": 3, "y": 4}, {"x": 9, "y": 1}]}}
    rows = game_settle_recommendations(snap)
    assert [(r["x"], r["y"], r["label"]) for r in rows] == [(3, 4, "S1"), (9, 1, "S2")]


def test_no_recommendations_without_block():
    assert game_settle_recommendations({}) == []
