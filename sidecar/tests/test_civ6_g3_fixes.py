"""Game 3 review fixes: decision turns, naval captures, build next, metrics lock, labels."""
from __future__ import annotations

import json
import threading

import pytest
from pathlib import Path

from sidecar import civ6_apply_results as ar
from sidecar import civ6_build_next as bn
from sidecar import civ6_legality as legality
from sidecar import civ6_turn_delta as td
from sidecar import pipeline_v2 as pipeline


def test_stamp_decision_turns_infers_next_turn_lag(tmp_path: Path):
    journal = [
        {"turn": 10, "commands": [{"command_id": "CMD_a"}, {"command_id": "CMD_skip"}]},
        {"turn": 11, "commands": [{"command_id": "CMD_b"}, {"command_id": "CMD_skip"}]},
    ]
    (tmp_path / "journal.jsonl").write_text("\n".join(json.dumps(j) for j in journal), encoding="utf-8")
    rows = [{"command_id": "CMD_a", "turn": 11}, {"command_id": "CMD_b", "turn": 12},
            {"command_id": "CMD_skip", "turn": 12}]
    assert ar.stamp_decision_turns(rows, tmp_path) >= 2
    assert rows[0]["decision_turn"] == 10 and rows[1]["decision_turn"] == 11
    assert rows[2]["decision_turn"] == 11


def test_stamp_decision_turns_keeps_existing_and_same_turn(tmp_path: Path):
    (tmp_path / "journal.jsonl").write_text(json.dumps({"turn": 5, "commands": [{"command_id": "X"}]}), encoding="utf-8")
    rows = [{"command_id": "X", "turn": 5}, {"command_id": "Y", "turn": 5, "decision_turn": 4}]
    ar.stamp_decision_turns(rows, tmp_path)
    assert rows[0].get("decision_turn", 5) == 5
    assert rows[1]["decision_turn"] == 4


def _naval_snapshot():
    return {
        "your_units": [{"unit_id": "U1", "domain_id": "DOMAIN_SEA"}],
        "known_map": {"plots": [{"x": 1, "y": 1, "water": False}, {"x": 2, "y": 1, "water": True},
                                {"x": 3, "y": 1, "water": False, "city_id": "C9"}]},
        "legal_commands": [
            {"command_id": "land", "kind": "attack_target", "fixed_arguments": {"unit_id": "U1", "target_x": 1, "target_y": 1}},
            {"command_id": "sea", "kind": "attack_target", "fixed_arguments": {"unit_id": "U1", "target_x": 2, "target_y": 1}},
            {"command_id": "city", "kind": "attack_target", "fixed_arguments": {"unit_id": "U1", "target_x": 3, "target_y": 1}},
        ],
    }


def test_galley_not_offered_land_capture():
    snap = _naval_snapshot()
    assert legality.prune_naval_land_attacks(snap) == 1
    assert [c["command_id"] for c in snap["legal_commands"]] == ["sea", "city"]


def test_civilians_never_upgrade():
    assert td._never_upgrades("UNIT_BUILDER") and td._never_upgrades("UNIT_SETTLER")
    assert not td._never_upgrades("UNIT_WARRIOR")


def _bn_snapshot():
    return {"civ6": {"buildable": [{"item_id": "UNIT_ARCHER", "turns": 4, "city_name": "Rome"},
                                   {"item_id": "BUILDING_GRANARY", "turns": 7}],
                     "build_next": {"item_id": "UNIT_ARCHER", "set_turn": 12}},
            "legal_commands": []}


def test_build_next_offers_bind_and_prompt():
    snap = _bn_snapshot()
    assert bn.inject_offers(snap) == 3
    ids = {c["command_id"] for c in snap["legal_commands"]}
    assert ids == {"CMD_NEXT_UNIT_ARCHER", "CMD_NEXT_BUILDING_GRANARY", "CMD_NEXT_NONE"}
    assert all(c["kind"] == "set_build_next" for c in snap["legal_commands"])
    assert bn.bind_reply(snap, "build.next", "granary") == (["CMD_NEXT_BUILDING_GRANARY"], [])
    assert bn.bind_reply(snap, "build.next", "none") == (["CMD_NEXT_NONE"], [])
    cmds, problems = bn.bind_reply(snap, "build.next", "UNIT_KNIGHT")
    assert cmds == [] and problems
    text = "\n".join(bn.prompt_lines(snap))
    assert "BUILD NEXT" in text and "UNIT_ARCHER (4 turns in Rome)" in text and "Current pick: UNIT_ARCHER" in text


def test_build_next_absent_without_buildable():
    snap = {"legal_commands": []}
    assert bn.inject_offers(snap) == 0 and bn.prompt_lines(snap) == []


def test_metrics_lock_serialises(tmp_path: Path):
    path = tmp_path / "turn_metrics.jsonl"
    order = []
    with pipeline.metrics_lock(path) as held:
        assert held
        t = threading.Thread(target=lambda: order.append(("other", pipeline.metrics_lock(path, wait_s=0.1).__enter__())))
        t.start(); t.join()
        order.append("inner_done")
    assert order[0] == ("other", False)
    with pipeline.metrics_lock(path) as held:
        assert held
    assert not path.with_name(path.name + ".lock").exists()


def test_barbarian_owner_label():
    from sidecar import civ6_combat_wire as cw
    ctx = {"players": [{"player_id": "PLAYER_63", "civilization": "CIVILIZATION_BARBARIAN", "kind": "barbarians"}]}
    label = cw._owner_label(ctx, "PLAYER_63")
    assert label in ("Barbarian", "Barbarians") or "PLAYER_63" not in label


def test_build_next_snapshot_keys_pass_schema():
    """The mod's civ6.buildable / civ6.build_next must survive snapshot validation."""
    from sidecar import civ6_adapter
    snap = civ6_adapter.load_golden_snapshot()
    snap["civ6"]["buildable"] = [{"item_id": "UNIT_BUILDER", "turns": 3, "city_name": "Rome"},
                                 {"item_id": "BUILDING_GRANARY", "turns": -1, "city_name": ""}]
    snap["civ6"]["build_next"] = {"item_id": "UNIT_BUILDER", "set_turn": 4}
    civ6_adapter.validate_civ6_snapshot(snap)
    snap["civ6"]["buildable"] = {}  # Lua empty table
    civ6_adapter.normalize_civ6_snapshot(snap)
    assert snap["civ6"]["buildable"] == []


def test_build_next_lua_snapshot_survives_property_errors():
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
Civ6Ai_Util = {}
function Civ6Ai_Util.JsonArrayList() return {} end
function Civ6Ai_Util.BuildNextItems() return {"UNIT_BUILDER"} end
Locale = {Lookup = function(s) return s end}
Game = {GetLocalPlayer = function() return 0 end,
        GetProperty = function(self, k) error("no such property " .. k) end}
local bq = {CanProduce = function() return true end, GetTurnsLeft = function() return 3 end}
local city = {GetBuildQueue = function() return bq end, GetName = function() return "Rome" end}
Players = {[1] = {GetCities = function() return {Members = function() return ipairs({city}) end} end}}
GameInfo = {Units = {UNIT_BUILDER = {Hash = 1}}, Buildings = {}, Districts = {}}
''')
    lua.execute((Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8"))
    assert lua.eval("Civ6Ai_Snapshot._BuildNextPick(1)") is None
    rows = lua.eval("Civ6Ai_Snapshot._BuildableItems(1)")
    assert rows[1]["item_id"] == "UNIT_BUILDER" and rows[1]["turns"] == 3
