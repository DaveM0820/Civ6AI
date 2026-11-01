from sidecar import map_situational as ms


def _snap(cols, wrap=True, width=74):
    plots = [{"x": x, "y": y, "terrain_id": "TERRAIN_PLAINS"} for x in cols for y in range(18, 23)]
    return {"game": {"map_width": width, "map_height": 46, "wrap_x": wrap}, "known_map": {"plots": plots},
            "your_units": [], "your_cities": [], "decision": {"turn": 5}}


def test_pinned_window_may_cross_seam():
    vp = ms.viewport_rect_from_stored({"x0": 68, "y0": 22, "width": 12, "height": 12}, 74, 46, wrap_x=True)
    assert vp["x0"] == 68 and vp["width"] == 12


def test_pinned_window_clamps_without_wrap():
    vp = ms.viewport_rect_from_stored({"x0": 68, "y0": 22, "width": 12, "height": 12}, 74, 46)
    assert vp["x0"] + vp["width"] <= 74


def test_focus_window_centred_on_x0_wraps():
    vp = ms.viewport_focused_on_tile(0, 20, 74, 46, wrap_x=True)
    assert vp["x0"] > 60 and vp["x0"] + vp["width"] > 74


def test_strategic_centred_on_x0_is_one_block():
    vp = ms.compute_overview_viewport(_snap(list(range(70, 74)) + list(range(0, 5))))
    assert vp["x0"] + vp["width"] > 74 and vp["width"] < 20


def test_strategic_full_width_starts_in_emptiest_column():
    cols = [c for c in range(74) if c not in (30, 31, 32)]
    vp = ms.compute_overview_viewport(_snap(cols))
    assert vp["width"] == 74 and vp["x0"] in (30, 31, 32, 33)


def test_no_wrap_unchanged():
    vp = ms.compute_overview_viewport(_snap(list(range(70, 74)) + list(range(0, 5)), wrap=False))
    assert vp["x0"] == 0 or vp["x0"] + vp["width"] <= 74
