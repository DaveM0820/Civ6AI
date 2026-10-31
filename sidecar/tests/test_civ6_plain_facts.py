from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire


def _snap():
    return {
        "game": {"map_width": 40, "wrap_x": False},
        "your_cities": [{"name": "LOC_CITY_NAME_QUSQU", "x": 10, "y": 10}],
        "your_units": [
            {"unit_id": "UNIT_7", "unit_type_id": "UNIT_SETTLER", "plot_id": "12,10", "x": 12, "y": 10},
            {"unit_id": "UNIT_8", "unit_type_id": "UNIT_SETTLER", "plot_id": "20,10", "x": 20, "y": 10},
        ],
        "known_map": {"plots": [
            {"x": 12, "y": 10, "water": False, "terrain_id": "TERRAIN_PLAINS"},
            {"x": 20, "y": 10, "water": True, "terrain_id": "TERRAIN_OCEAN"},
        ]},
        "your_empire": {"research": {"known_tech_ids": ["TECH_SHIPBUILDING"]}},
    }


def test_too_close_names_city_and_rule():
    snap = _snap()
    text = coaching.found_block_text(snap, snap["your_units"][0], "too_close_to_city")
    assert "Qusqu is 2 tiles away" in text and "at least 4 tiles" in text


def test_embarked_on_ocean():
    snap = _snap()
    assert coaching.embarked_text(snap["your_units"][1], snap).startswith("embarked on ocean")
    assert coaching.embarked_text(snap["your_units"][0], snap) is None


def test_ocean_rule_without_cartography():
    assert "ocean (deep water) needs Cartography" in coaching._water_and_embark_clause(_snap())


def test_found_alert_uses_unit_name():
    snap = _snap()
    out = civ6_wire._plain_found_alert(snap, "UNIT_7 cannot found a city on its tile (too_close_to_city).")
    assert "UNIT_7" not in out and "Qusqu" in out


def test_move_failure_names_blocker_and_stack_rule():
    from sidecar import civ6_apply_results as ar
    snap = _snap()
    text = ar.move_failure_text(snap, "warrior_1", 12, 10, "plot_occupied", "PLAYER_0")
    assert "UNIT_7" not in text and "Settler" in text and "can share" in text
    own = ar.move_failure_text(snap, "warrior_1", 12, 10, "already_there", "PLAYER_0")
    assert "already on (12,10)" in own
