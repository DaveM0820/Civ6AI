"""Fix round 5 (g7 T100 review): coast refusal text, plan.strategy, fog edges, build-next expiry."""
from sidecar import civ6_apply_results as ar
from sidecar import civ6_build_next as bn
from sidecar import civ6_command_wire as cw
from sidecar import civ6_seat_memory as mem
from sidecar import civ6_wire as wire


def _snap(techs):
    plots = []
    for x in range(0, 6):
        for y in range(0, 6):
            plots.append({"x": x, "y": y, "water": x >= 3, "terrain_id": "TERRAIN_COAST" if x >= 3 else "TERRAIN_PLAINS",
                          "knowledge": "visible"})
    plots[-1]["revealed_owner_id"] = "PLAYER_14"
    return {
        "player_id": "PLAYER_0",
        "game": {"map_width": 40, "map_height": 30, "wrap_x": False},
        "known_map": {"plots": plots, "revealed_count": len(plots)},
        "your_empire": {"research": {"known_tech_ids": techs}},
        "your_cities": [{"x": 1, "y": 1, "plot_id": "PLOT_1_1"}],
        "your_units": [{"unit_id": "UNIT_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_2_2", "domain_id": "DOMAIN_LAND"}],
    }


def test_coast_refusal_names_the_real_reason_once_the_seat_can_embark():
    snap = _snap(["TECH_SHIPBUILDING"])
    text = ar.move_failure_text(snap, "settler_1", 5, 5, "no_path", "PLAYER_0", "DOMAIN_LAND", snap["your_units"][0])
    assert "cannot enter it" not in text
    assert "embark onto" in text and "no route" in text
    assert "PLAYER_14" in text and "open borders" in text
    stacked = ar.move_failure_text(snap, "settler_1", 4, 2, "path:4,2>4,2:steps=0:len=2:stop=stack_limit", "PLAYER_0",
                                   "DOMAIN_LAND", snap["your_units"][0])
    assert "cannot enter it" not in stacked


def test_coast_refusal_before_shipbuilding_says_so():
    snap = _snap([])
    text = ar.move_failure_text(snap, "settler_1", 4, 2, "impassable", "PLAYER_0", "DOMAIN_LAND", snap["your_units"][0])
    assert "Shipbuilding" in text


def test_plan_strategy_is_kept_replaced_and_shown():
    reply = {"plan.strategy": "Science via campuses;  Rationalism later", "unit.x": "Skip"}
    update = cw.extract_plan(reply)
    assert "plan.strategy" not in reply and update["strategy"].startswith("Science via campuses; Rationalism")
    memory = mem.apply_plan({}, 10, update)
    memory = mem.apply_plan(memory, 11, {"goal": "science"})
    lines = dict(mem.prompt_lines(memory))
    assert lines["plan.strategy"].endswith("(written T10)")
    memory = mem.apply_plan(memory, 20, {"strategy": "Pivot: naval domination"})
    assert dict(mem.prompt_lines(memory))["plan.strategy"] == "Pivot: naval domination (written T20)"


def test_few_sites_line_points_at_fog_edges(monkeypatch=None):
    snap = _snap(["TECH_SHIPBUILDING"])
    line = wire.few_sites_explore_line(snap)
    assert line and line.startswith("SETTLE SITES:")
    assert "Unexplored edge on land" in line and "Unexplored edge on coast" in line
    import unittest.mock as mock
    with mock.patch.object(cw, "game_settle_recommendations", return_value=[{"x": 0, "y": 0}, {"x": 2, "y": 4}]):
        assert wire.few_sites_explore_line(snap) is None


def test_build_next_shows_when_the_pick_lapses():
    snap = {"legal_commands": [{"kind": "set_build_next", "command_id": "CMD_NEXT_UNIT_SETTLER",
                                "fixed_arguments": {"item_id": "UNIT_SETTLER"}}],
            "civ6": {"build_next": {"item_id": "UNIT_SETTLER", "set_turn": 10, "expires_turn": 15}}}
    assert "lapses after T15" in "\n".join(bn.prompt_lines(snap))
