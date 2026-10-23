"""Escalation ladder, CHANGED SINCE LAST TURN, stale-situation warning, said vs did, repeat legal moves."""
from __future__ import annotations

import json

import pytest

from sidecar import civ6_attention, civ6_escalation, civ6_legality, civ6_turn_delta
from sidecar import civ6_apply_results as results
from sidecar.civ6_config import Civ6AiLocalConfig, apply_seat_runtime


def _unit(uid, typ, x, y, **extra):
    row = {"unit_id": uid, "unit_type_id": typ, "plot_id": f"PLOT_{x}_{y}", "domain_id": "DOMAIN_LAND",
           "movement": {"current": 2, "maximum": 2}, "needs_orders": True}
    row.update(extra)
    return row


def _snap(turn, units=(), cities=(), contacts=(), session=None):
    snap = {
        "schema_version": "civ6ai-input/1",
        "decision": {"player_id": "PLAYER_0", "turn": turn},
        "your_units": list(units),
        "your_cities": list(cities),
        "civ6": {"diplomacy": {"majors": [], "city_states": list(contacts)}},
        "known_map": {"plots": []},
        "legal_commands": [],
        "history": {},
    }
    if session is not None:
        snap["_session_dir"] = str(session)
    return snap


def _city(cid, name, x, y):
    return {"city_id": cid, "name": name, "plot_id": f"PLOT_{x}_{y}"}


def test_changed_since_last_turn_settler_founded_lost_contact_war():
    memory: dict = {}
    t1 = _snap(10, units=[_unit("U1", "UNIT_SETTLER", 17, 24), _unit("U2", "UNIT_SETTLER", 5, 5),
                          _unit("U3", "UNIT_WARRIOR", 17, 24)],
               cities=[_city("C1", "Pokrovka", 17, 20)],
               contacts=[{"player_id": "PLAYER_13", "name": "Hunza", "at_war": False}])
    civ6_turn_delta.observe(t1, memory)
    assert t1["_turn_delta"]["changes"] is None  # first turn has no baseline
    t2 = _snap(11, units=[_unit("U3", "UNIT_WARRIOR", 17, 24), _unit("U9", "UNIT_SETTLER", 16, 23)],
               cities=[_city("C1", "Pokrovka", 17, 20), _city("C2", "Neapolis", 17, 24)],
               contacts=[{"player_id": "PLAYER_13", "name": "Hunza", "at_war": False},
                         {"player_id": "PLAYER_14", "name": "Kabul", "at_war": True}])
    civ6_turn_delta.observe(t2, memory)
    changes = t2["_turn_delta"]["changes"]
    text = " ".join(changes)
    assert "NEW city Neapolis at (17,24)" in text
    assert "LOST Settler" in text and "(5,5)" in text  # the far settler vanished
    assert "(17,24) (killed" not in text  # the founding settler is not reported lost
    assert "new Settler" in text and "met Kabul" in text and "WAR with Kabul" in text
    lines = civ6_attention.lines(t2)
    assert lines[0].startswith("CHANGED SINCE LAST TURN (T10)")
    # same-turn rerun diffs against the same baseline
    rerun = _snap(11, units=t2["your_units"], cities=t2["your_cities"], contacts=t2["civ6"]["diplomacy"]["city_states"])
    civ6_turn_delta.observe(rerun, memory)
    assert rerun["_turn_delta"]["changes"] == changes


def test_nothing_changed_line_and_stale_warning():
    memory = {"thoughts": [
        {"turn": 8, "situation": "My warrior blocks the settler at seventeen twenty four again"},
        {"turn": 9, "situation": "My warrior blocks the settler at seventeen twenty four again today"},
    ]}
    civ6_turn_delta.observe(_snap(9), memory)
    snap = _snap(10)
    civ6_turn_delta.observe(snap, memory)
    lines = civ6_turn_delta.attention_items(snap)
    assert "no city, unit, contact or war changed" in lines[0]
    assert any(line.startswith("REPEATING: your T9 situation") for line in lines)


def test_said_vs_did_priorities_and_attention():
    note = results.strategy_orders_note(
        "I will set build priorities to 'expansion:3, improvements:2' and Improve(16,23,QUARRY).",
        [{"kind": "move_unit", "fixed_arguments": {"intent": "move"}}])
    assert "set build priorities" in note and "improve a tile" in note
    assert results.strategy_orders_note(
        "I will set build priorities to expansion.", [{"kind": "set_build_priority"}]) is None
    memory = {"thoughts": [{"turn": 9, "situation": "a", "orders_note": note}]}
    snap = _snap(10)
    civ6_turn_delta.observe(snap, memory)
    assert any(line.startswith("SAID vs DID (T9)") for line in civ6_turn_delta.attention_items(snap))


def test_repeat_rejection_lists_legal_moves(tmp_path):
    plots = [{"x": x, "y": y, "water": (x, y) == (18, 24)} for x in range(15, 20) for y in range(22, 27)]
    snap = _snap(12, units=[_unit("UNIT_W", "UNIT_WARRIOR", 17, 24, unit_class_id="FORMATION_CLASS_LAND_COMBAT")],
                 session=tmp_path)
    snap["known_map"]["plots"] = plots
    rows = [{"order": "MoveTo(18,24)", "reason": "impassable", "turn": t, "unit_id": "UNIT_W"} for t in (9, 10, 11)]
    (tmp_path / civ6_legality.STATE_NAME).write_text(json.dumps({"blacklist": {}, "rejections": rows}))
    line = civ6_legality.rejection_lines(snap)[0]
    assert "rejected on 3 turns" in line and "legal moves for" in line
    assert "(18,24)" not in line.split("legal moves for", 1)[1]
    rows = rows[1:]
    (tmp_path / civ6_legality.STATE_NAME).write_text(json.dumps({"blacklist": {}, "rejections": rows}))
    assert "legal moves" not in civ6_legality.rejection_lines(snap)[0]  # only 2 repeats


def _struggling(turn, tmp_path):
    snap = _snap(turn, session=tmp_path)
    snap["history"]["command_results"] = [
        {"kind": results.KIND_FAILED, "turn": turn - 1, "summary": "x"},
        {"kind": results.KIND_FAILED, "turn": turn - 1, "summary": "y"},
        {"kind": results.KIND_OK, "turn": turn - 1, "summary": "z"},
    ]
    snap["_turn_delta"] = {"stale": {"turn": turn - 1, "overlap": 90}}
    return snap


def _clean(turn, tmp_path):
    snap = _snap(turn, session=tmp_path)
    snap["history"]["command_results"] = [{"kind": results.KIND_OK, "turn": turn - 1, "summary": "ok"}] * 4
    return snap


def test_escalation_ladder_up_down_and_model_override(tmp_path, monkeypatch):
    monkeypatch.delenv("CIV6AI_ESCALATION_PROFILE", raising=False)
    monkeypatch.setenv("CIV6AI_ESCALATION_CLEAN_TURNS", "2")
    cfg = Civ6AiLocalConfig(provider="openrouter", model="qwen/qwen3.7-flash", reasoning_effort="off",
                            seat_models={"0": {"model": "qwen/qwen3.7-flash", "reasoning_effort": "off"}},
                            escalation={"profile": "test"})
    memory: dict = {}
    s1 = _struggling(5, tmp_path)
    esc = civ6_escalation.decide(s1, memory, cfg, ["Rejected last turn: MoveTo(18,24) - impassable"])
    assert esc["rung"] == 1 and esc["reason"] == "step_up"
    assert set(esc["signals"]["hits"]) >= {"fail_share", "stale"}
    run = apply_seat_runtime(cfg, s1)
    assert run.model == civ6_escalation.HAIKU and run.reasoning_effort == "off"
    # same-turn rerun keeps the decision
    assert civ6_escalation.decide(_struggling(5, tmp_path), memory, cfg, ["r"])["rung"] == 1
    s2 = _struggling(6, tmp_path)
    assert civ6_escalation.decide(s2, memory, cfg, ["r"])["rung"] == 2
    assert apply_seat_runtime(cfg, s2).reasoning_effort == "low"
    assert civ6_escalation.decide(_struggling(7, tmp_path), memory, cfg, ["r"])["reason"] == "at_top"
    assert civ6_escalation.decide(_clean(8, tmp_path), memory, cfg)["rung"] == 2
    assert civ6_escalation.decide(_clean(9, tmp_path), memory, cfg)["reason"] == "step_down"
    s10 = _clean(10, tmp_path)
    civ6_escalation.decide(s10, memory, cfg)
    s11 = _clean(11, tmp_path)
    assert civ6_escalation.decide(s11, memory, cfg)["rung"] == 0
    tier0 = apply_seat_runtime(cfg, s11)
    assert tier0.model == "qwen/qwen3.7-flash" and tier0.reasoning_effort == "off"
    fields = civ6_escalation.metrics_fields(s11)
    assert fields["escalation_rung"] == 0 and fields["escalation_profile"] == "test"


def test_escalation_real_profile_and_cost_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("CIV6AI_ESCALATION_PROFILE", "real")
    monkeypatch.setenv("CIV6AI_ESCALATION_COST_CAP_CENTS", "1")
    cfg = Civ6AiLocalConfig(provider="openrouter", model=civ6_escalation.HAIKU, reasoning_effort="off")
    memory: dict = {}
    s1 = _struggling(5, tmp_path)
    esc = civ6_escalation.decide(s1, memory, cfg, ["r"])
    assert esc["profile"] == "real" and esc["rung"] == 1
    run = apply_seat_runtime(cfg, s1)
    assert run.model == civ6_escalation.HAIKU and run.reasoning_effort == "low"
    civ6_escalation.record_cost(memory, s1, 0.02)
    civ6_escalation.record_cost(memory, s1, 0.02)  # same turn charges once
    assert memory["escalation"]["spent_usd"] == pytest.approx(0.02)
    s2 = _struggling(6, tmp_path)
    assert civ6_escalation.decide(s2, memory, cfg, ["r"])["reason"] == "cost_cap"
    assert apply_seat_runtime(cfg, s2).reasoning_effort == "off"


def test_escalation_off_profile_never_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("CIV6AI_ESCALATION_PROFILE", "off")
    memory: dict = {}
    assert civ6_escalation.decide(_struggling(5, tmp_path), memory, None, ["r"])["rung"] == 0
