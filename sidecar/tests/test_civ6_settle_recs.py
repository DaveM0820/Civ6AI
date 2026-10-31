from sidecar.civ6_command_wire import game_settle_recommendations


def test_game_settle_recommendations_labels_and_dedupes():
    snap = {"civ6": {"settle_recommended": [{"x": 3, "y": 4}, {"x": 3, "y": 4}, {"x": 9, "y": 1}]}}
    rows = game_settle_recommendations(snap)
    assert [(r["x"], r["y"], r["label"]) for r in rows] == [(3, 4, "S1"), (9, 1, "S2")]


def test_no_recommendations_without_block():
    assert game_settle_recommendations({}) == []


def test_settle_recommended_passes_snapshot_schema():
    import json
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "decision-input-civ6.json").read_text())
    prop = schema["$defs"]["civ6_extension"]["properties"]["settle_recommended"]
    assert prop["items"]["required"] == ["x", "y"]


def test_snapshot_with_todays_fields_validates():
    """settle_recommended plus compact plots (dropped defaults) pass the schema boundary."""
    from sidecar import civ6_adapter
    import copy
    snap = copy.deepcopy(civ6_adapter.load_golden_snapshot())
    snap["civ6"]["settle_recommended"] = [{"x": 3, "y": 4}, {"x": 9, "y": 1}]
    snap["known_map"]["plots"] = [{"x": 1, "y": 2, "terrain_id": "TERRAIN_GRASS", "knowledge": "visible"}]
    civ6_adapter.normalize_civ6_snapshot(snap)
    assert snap["known_map"]["plots"][0]["river_edges"] == []
