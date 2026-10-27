from sidecar import civ6_apply_results as ar
from sidecar import run_civ6


def _snap():
    return {
        "your_units": [{"unit_id": "UNIT_7", "plot_id": "PLOT_24_23", "unit_type_id": "UNIT_SETTLER"}],
        "legal_commands": [
            {"command_id": "CMD_found_UNIT_7", "kind": "found_city", "fixed_arguments": {"unit_id": "UNIT_7"}},
            {"command_id": "CMD_UNIT_7_found_24_24", "kind": "move_unit",
             "fixed_arguments": {"unit_id": "UNIT_7", "target_x": 24, "target_y": 24}},
        ],
    }


def test_arrived_settler_founds_instead_of_retargeting():
    snap = _snap()
    rows = [{"command_id": "CMD_UNIT_7_found_24_23", "ok": True, "reason": "moved:24,23"}]
    snap["_found_arrivals"] = ar.found_arrivals(snap, rows)
    assert snap["_found_arrivals"] == ["UNIT_7"]
    out = run_civ6.found_on_arrival(snap, [{"command_id": "CMD_UNIT_7_found_24_24", "arguments": {}}])
    assert out == [{"command_id": "CMD_found_UNIT_7", "arguments": {}}]


def test_not_arrived_keeps_orders():
    snap = _snap()
    rows = [{"command_id": "CMD_UNIT_7_found_25_23", "ok": True}]
    snap["_found_arrivals"] = ar.found_arrivals(snap, rows)
    cmds = [{"command_id": "CMD_UNIT_7_found_24_24", "arguments": {}}]
    assert run_civ6.found_on_arrival(snap, cmds) == cmds


def test_no_legal_found_keeps_orders():
    snap = _snap()
    snap["legal_commands"] = snap["legal_commands"][1:]
    snap["_found_arrivals"] = ["UNIT_7"]
    cmds = [{"command_id": "CMD_UNIT_7_found_24_24", "arguments": {}}]
    assert run_civ6.found_on_arrival(snap, cmds) == cmds


def test_arrival_counts_even_when_snapshot_predates_the_move():
    snap = _snap()  # snapshot still shows (24,23)
    rows = [{"command_id": "CMD_UNIT_7_found_24_24", "ok": True, "reason": "moved:24,24"}]
    assert ar.found_arrivals(snap, rows) == ["UNIT_7"]
    rows = [{"command_id": "CMD_UNIT_7_found_49_17", "ok": True, "reason": "path:50,15>49,17:steps=2:len=3:stop=arrived"}]
    assert ar.found_arrivals(snap, rows) == ["UNIT_7"]
    rows = [{"command_id": "CMD_UNIT_7_found_24_11", "ok": True, "reason": "partial_path:23,12>24,12:steps=1:stop=no_moves_left"}]
    assert ar.found_arrivals(snap, rows) == []


def test_inject_uses_rows_labelled_this_turn(tmp_path):
    import json
    snap = _snap()
    snap["decision"] = {"player_id": "PLAYER_2", "turn": 42}
    rows = [
        {"player_id": "PLAYER_2", "turn": 41, "command_id": "CMD_UNIT_7_found_24_24", "ok": True, "reason": "moved:24,24", "event": "apply_result"},
        {"player_id": "PLAYER_2", "turn": 42, "command_id": "CMD_UNIT_7_found_24_23", "ok": True, "reason": "moved:24,23", "event": "apply_result"},
    ]
    (tmp_path / "PLAYER_2").mkdir()
    for path in (tmp_path / "apply-results.jsonl", tmp_path / "PLAYER_2" / "apply-results.jsonl"):
        path.write_text("\n".join(json.dumps(r) for r in rows))
    ar.inject_command_results(snap, tmp_path)
    assert snap["_found_arrivals"] == ["UNIT_7"]
