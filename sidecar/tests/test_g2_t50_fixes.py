from sidecar import civ6_legality as lg, civ6_apply_results as ar, map_situational as ms


def _plot(x, y, water=False):
    p = {"x": x, "y": y, "terrain_id": "TERRAIN_COAST" if water else "TERRAIN_PLAINS"}
    if water:
        p["water"] = True
    return p


def _snap(water, cities=(), units=(), turn=10, width=40):
    plots = [_plot(x, y, (x, y) in water) for x in range(8) for y in range(8)]
    return {"known_map": {"plots": plots}, "your_cities": [{"x": x, "y": y, "plot_id": f"PLOT_{x}_{y}"} for x, y in cities],
            "your_units": list(units), "decision": {"turn": turn}, "game": {"map_width": width},
            "civ6": {}, "your_empire": {"research": {"known_tech_ids": []}}}


def test_ship_may_enter_own_coastal_city():
    ship = {"unit_id": "U1", "plot_id": "PLOT_2_3", "domain_id": "DOMAIN_SEA", "unit_type_id": "UNIT_GALLEY"}
    s = _snap({(2, 3), (2, 4)}, cities=[(3, 3)], units=[ship])
    assert lg.tile_passable(s, ship, 3, 3) is None
    assert lg.tile_passable(s, ship, 4, 3) == "impassable"
    text = ar.move_failure_text(s, "galley_1", 4, 3, "land", "P0", "DOMAIN_SEA", ship)
    assert "land; ships" in text and "(3,3)" in text  # nearest water list includes the city


def test_ship_in_city_can_leave():
    ship = {"unit_id": "U1", "plot_id": "PLOT_3_3", "domain_id": "DOMAIN_SEA", "unit_type_id": "UNIT_GALLEY"}
    s = _snap({(2, 3), (2, 4)}, cities=[(3, 3)], units=[ship])
    assert lg.reachable(s, ship, (2, 4))


def _repeat_snap(fail_turn, since, now):
    s = _snap(set(), turn=now, units=[{"unit_id": "UNIT_9", "plot_id": "PLOT_2_2", "unit_type_id": "UNIT_SETTLER"}])
    s["history"] = {"command_results": [{"kind": "APPLY_FAILED", "unit": "UNIT_9", "turn": fail_turn, "reason": "stack_limit",
                                          "order_kind": "move_unit", "command_id": "CMD_move_UNIT_9_3_2",
                                          "affected_ids": ["UNIT_9"], "summary": "settler MoveTo(3,2) failed"}]}
    s["_unit_since"] = {"UNIT_9": since}
    return s


def _blocked(s):
    _, match = ar._failure_matcher(s)
    return match("move_unit", "UNIT_9", 3, 2) is not None


def test_repeat_guard_expires_and_needs_same_origin():
    fresh = _repeat_snap(fail_turn=10, since=8, now=11)
    assert _blocked(fresh)
    assert not _blocked(_repeat_snap(fail_turn=45, since=48, now=50))  # P1 case: moved since
    assert not _blocked(_repeat_snap(fail_turn=10, since=8, now=20))   # expired


def test_strategic_window_keeps_seam_island_together():
    plots = [_plot(x, y) for x in list(range(0, 4)) + list(range(66, 74)) for y in range(10, 14)]
    s = {"game": {"map_width": 74, "map_height": 46, "wrap_x": True}, "known_map": {"plots": plots},
         "your_units": [], "your_cities": [], "decision": {"turn": 5}}
    vp = ms.compute_overview_viewport(s)
    assert vp["width"] < 30 and vp["x0"] + vp["width"] > 74
    assert "of 74x46" in ms.format_strategic_window(vp, 74, 46)


def test_strategic_map_marks_sites():
    import inspect
    from sidecar import map_render_civ6
    assert 'show_settle_labels = image_role != "overview"' not in inspect.getsource(map_render_civ6)
