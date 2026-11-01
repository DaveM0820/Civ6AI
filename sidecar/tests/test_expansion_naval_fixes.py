from sidecar import civ6_apply_results as ar


def _mv(reason, tx=73, ty=18):
    return ar._success_text({"kind": "move_unit", "reason": reason,
                             "fixed_arguments": {"unit_id": "U", "target_x": tx, "target_y": ty}})


def test_moved_onto_target_is_arrival_not_partial():
    text = _mv("moved:73,18")
    assert "arrived at (73,18)" in text and "reissue" not in text


def test_moved_short_of_target_is_partial():
    text = _mv("moved:72,18")
    assert "partial" in text and "(72,18)" in text and "(73,18)" in text
