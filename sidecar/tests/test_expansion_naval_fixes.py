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


from sidecar import civ6_legality as lg
from sidecar import civ6_prompt_coaching as coaching


def _snap(techs, ocean=True):
    plots = [{"x": 0, "y": 0, "terrain_id": "TERRAIN_PLAINS"},
             {"x": 1, "y": 0, "water": True, "terrain_id": "TERRAIN_COAST"},
             {"x": 2, "y": 0, "water": True, "terrain_id": "TERRAIN_OCEAN" if ocean else "TERRAIN_COAST"},
             {"x": 3, "y": 0, "terrain_id": "TERRAIN_PLAINS"}]
    return {"known_map": {"plots": plots},
            "your_empire": {"research": {"known_tech_ids": techs}},
            "your_units": [{"unit_id": "S", "unit_type_id": "UNIT_SETTLER", "domain_id": "DOMAIN_LAND", "x": 0, "y": 0},
                           {"unit_id": "G", "unit_type_id": "UNIT_GALLEY", "domain_id": "DOMAIN_SEA", "x": 1, "y": 0}]}


def test_embark_coast_ok_with_shipbuilding_and_closed_without():
    assert lg.move_problem(_snap([]), "S", 1, 0) == "impassable"
    assert lg.move_problem(_snap(["TECH_SHIPBUILDING"]), "S", 1, 0) is None


def test_ocean_needs_cartography_for_land_and_ships():
    snap = _snap(["TECH_SHIPBUILDING"])
    assert lg.move_problem(snap, "S", 2, 0) == "ocean_needs_cartography"
    assert lg.move_problem(snap, "G", 2, 0) == "ocean_needs_cartography"
    carto = _snap(["TECH_SHIPBUILDING", "TECH_CARTOGRAPHY"])
    assert lg.move_problem(carto, "S", 3, 0) is None
    assert lg.move_problem(carto, "G", 2, 0) is None


def test_settler_crosses_coast_to_another_island():
    assert lg.move_problem(_snap(["TECH_SHIPBUILDING"], ocean=False), "S", 3, 0) is None


def test_cartography_status_line():
    snap = _snap(["TECH_SHIPBUILDING"])
    assert "needs Buttress" in coaching._water_and_embark_clause(snap)
    snap["civ6"] = {"governance": {"techs": {"options": [{"id": "TECH_CARTOGRAPHY"}]}}}
    assert "researchable now" in coaching._water_and_embark_clause(snap)
    snap["civ6"] = {"governance": {"techs": {"options": [], "cartography_needs": ["TECH_SQUARE_RIGGING"]}}}
    assert "needs Square Rigging" in coaching._water_and_embark_clause(snap)


def test_first_settler_not_penalised_and_idle_settlers_capped():
    from sidecar import civ6_priorities as pr
    base = {"levels": {}, "pop": 3, "land": True, "need_expansion": False, "missing_monument": True}
    one = dict(base, cities=1)
    two = dict(base, cities=2)
    s1 = pr.item_score("UNIT_SETTLER", ["PSEUDOYIELD_UNIT_SETTLER"], one, "unit")
    s2 = pr.item_score("UNIT_SETTLER", ["PSEUDOYIELD_UNIT_SETTLER"], two, "unit")
    assert s1 - s2 == 40
    assert pr.item_score("BUILDING_MONUMENT", [], one) == 0
    assert pr.item_score("BUILDING_MONUMENT", [], two) == 15
    many = dict(one, unit_counts={"UNIT_SETTLER": 2})
    assert pr.item_score("UNIT_SETTLER", ["PSEUDOYIELD_UNIT_SETTLER"], many, "unit") == s1 - 100


def test_foundcity_sorts_first_and_fresh_water_is_not_a_blocker():
    from sidecar import civ6_wire
    toks = sorted(["MoveTo(x,y)", "FoundCity", "Skip"], key=civ6_wire._token_sort_key)
    assert toks[0] == "FoundCity"
    lines = coaching.settler_fact_lines("settler_1", {"settle": {"here_ok": True, "fresh_water": False}}, {})
    assert "FoundCity legal here, no fresh water (optional" in lines[0]


def test_game_ai_units_get_no_command_row():
    from sidecar import civ6_wire
    trader = {"unit_id": "T", "unit_type_id": "UNIT_TRADER", "can_act": False, "needs_orders": False,
              "movement": {"current": 2}}
    assert civ6_wire._game_ai_civilian(trader)


def test_recommended_sites_drop_too_close_and_occupied():
    from sidecar import civ6_command_wire as cw
    snap = {"game": {"map_width": 74, "wrap_x": True},
            "your_cities": [{"x": 10, "y": 10}],
            "visible_other_units": [{"plot_id": "PLOT_20_10", "owner_player_id": "PLAYER_63"}],
            "civ6": {"settle_recommended": [{"x": 13, "y": 10}, {"x": 20, "y": 10}, {"x": 16, "y": 10}]},
            "your_units": []}
    rows = cw.game_settle_recommendations(snap)
    assert [(r["x"], r["y"], r["label"]) for r in rows] == [(16, 10, "S1")]


def test_unit_labels_stable_when_same_type_unit_dies(tmp_path):
    from sidecar import civ6_unit_labels as ul, pipeline_v2 as pl
    a = {"unit_id": "UNIT_1", "unit_type_id": "UNIT_SETTLER"}
    b = {"unit_id": "UNIT_2", "unit_type_id": "UNIT_SETTLER"}
    try:
        assert ul.activate({"your_units": [a, b]}, tmp_path) == {"UNIT_1": "settler_1", "UNIT_2": "settler_2"}
        labels = ul.activate({"your_units": [b]}, tmp_path)
        assert labels == {"UNIT_2": "settler_2"}
        assert pl._build_unit_wire_id_map([b]) == {"UNIT_2": "settler_2"}
        c = {"unit_id": "UNIT_0", "unit_type_id": "UNIT_SETTLER"}
        assert ul.activate({"your_units": [b, c]}, tmp_path)["UNIT_0"] == "settler_3"
        # foreign / unregistered units fall back to plain numbering
        assert pl._build_unit_wire_id_map([{"unit_id": "X", "unit_type_id": "UNIT_WARRIOR"}]) == {"X": "warrior_1"}
    finally:
        pl._STABLE_UNIT_LABELS = None


def test_unit_goal_memory_kept_until_arrival():
    from sidecar import civ6_unit_labels as ul
    state = {}
    snap = {"your_units": [{"unit_id": "U", "x": 1, "y": 1}]}
    row = {"source": "model", "kind": "move_unit", "turn": 5,
           "fixed_arguments": {"unit_id": "U", "target_x": 9, "target_y": 4}}
    assert ul.update_goals(snap, state, [row]) == {"U": {"x": 9, "y": 4, "set_turn": 5}}
    assert ul.update_goals(snap, state, [dict(row, turn=6)])["U"]["set_turn"] == 5
    snap["your_units"][0].update(x=9, y=4)
    assert ul.update_goals(snap, state, []) == {}


def test_open_borders_not_bought_twice(monkeypatch):
    from sidecar import civ6_diplomacy as dip
    deals = [{"from": "PLAYER_0", "to": "PLAYER_3", "give": [{"res": "RESOURCE_HORSES", "n": 16}],
              "want": [{"kind": "open_borders"}], "turn": 52, "status": "accepted", "done_turn": 52}]
    monkeypatch.setattr(dip, "load_deals", lambda snap: deals)
    snap = {"decision": {"turn": 53, "player_id": "PLAYER_0"}}
    assert "already have open borders" in dip._pact_in_force_problem(snap, "PLAYER_0", "PLAYER_3", [{"kind": "open_borders"}])
    assert dip._pact_in_force_problem(snap, "PLAYER_0", "PLAYER_5", [{"kind": "open_borders"}]) is None
    snap["decision"]["turn"] = 90
    assert dip._pact_in_force_problem(snap, "PLAYER_0", "PLAYER_3", [{"kind": "open_borders"}]) is None
