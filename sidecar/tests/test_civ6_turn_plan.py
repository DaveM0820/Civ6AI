"""Turn plan (thought.plan): required row, kept in the thought row's decision slot,
shown back as T<n>.plan with the newest kept under the journal budget; REVERSING
signal for units that turn back on their own path."""
from __future__ import annotations

from sidecar import civ6_adapter, civ6_apply_results, civ6_escalation, civ6_turn_delta, civ6_wire
from sidecar import civ6_turn_importance as importance
from sidecar import pipeline_v2 as pipeline

PLAN = "Move warrior_1 east toward (20,14) to scout the coast; scout_2 keeps exploring the NE coast."


def test_flat_and_normalized_response_keep_the_plan():
    flat = {"3.thought.situation": "s", "4.thought.strategy": "t", "5.thought.plan": PLAN}
    flat = {k.split(".", 1)[1]: v for k, v in flat.items()}
    assert pipeline._thought_from_flat(flat)["plan"] == PLAN
    snap = civ6_adapter.build_classical_golden_snapshot()
    out = pipeline.normalize_model_response(snap, {"thought": {"situation": "s", "strategy": "t", "plan": PLAN},
                                                    "decision_summary": "x", "commands": [], "chat_messages": []})
    assert out["thought"]["plan"] == PLAN


def test_wire_asks_for_the_plan_and_shows_recent_plans():
    snap = civ6_adapter.build_classical_golden_snapshot()
    turn = int(snap["decision"]["turn"])
    snap.setdefault("history", {})["thought_memory"] = [
        {"turn": turn - 2, "situation": "a", "strategy": "b", "decision": "old plan"},
        {"turn": turn - 1, "situation": "c", "strategy": "d", "decision": PLAN},
    ]
    wire = civ6_wire.build_civ6_model_wire_text(snap)
    assert "thought.plan" in wire and "(20,14)" in wire  # required row with the example
    assert f"T{turn - 1}.plan = {PLAN}" in wire
    assert wire.index(f"T{turn - 2}.plan") < wire.index(f"T{turn - 1}.plan")  # printed oldest first


def test_journal_budget_keeps_the_newest_plan(monkeypatch):
    snap = civ6_adapter.build_classical_golden_snapshot()
    turn = int(snap["decision"]["turn"])
    rows = [{"turn": turn - k, "situation": "x" * 300, "strategy": "y" * 300, "decision": f"plan {turn - k}"}
            for k in range(6, 0, -1)]
    snap.setdefault("history", {})["thought_memory"] = rows
    cfg = dict(importance.load_config(), journal_char_budget=900)
    monkeypatch.setattr(importance, "load_config", lambda: cfg)
    wire = civ6_wire.build_civ6_model_wire_text(snap)
    assert f"plan {turn - 1}" in wire
    assert f"plan {turn - 6}" not in wire


def test_said_vs_did_reads_the_plan_too():
    memory = {"thoughts": [{"turn": 4, "strategy": "win by science", "decision": "I will set build priorities now."}]}
    civ6_apply_results.attach_strategy_orders_note(memory, 4, [{"kind": "move_unit"}])
    assert "set build priorities" in memory["thoughts"][0]["orders_note"]


def _snap(turn, x, y):
    return {"decision": {"player_id": "PLAYER_0", "turn": turn},
            "your_units": [{"unit_id": "U1", "unit_type_id": "UNIT_SCOUT", "plot_id": f"PLOT_{x}_{y}"}],
            "your_cities": [], "civ6": {"diplomacy": {}}, "history": {}}


def test_reversal_is_flagged_and_feeds_escalation(tmp_path):
    memory: dict = {}
    for turn, (x, y) in enumerate([(10, 10), (14, 10), (10, 11)], start=1):
        snap = _snap(turn, x, y)
        civ6_turn_delta.observe(snap, memory)
    assert snap["_turn_delta"]["reversing"]
    assert any(line.startswith("REVERSING: scout_1") or line.startswith("REVERSING: ")
               for line in civ6_turn_delta.attention_items(snap))
    snap["_session_dir"] = str(tmp_path)
    assert "oscillation" in civ6_escalation.signals(snap)["hits"]
    # same-turn rerun does not double-count, and steady travel is not a reversal
    rerun = _snap(3, 10, 11)
    civ6_turn_delta.observe(rerun, memory)
    assert rerun["_turn_delta"]["reversing"] == snap["_turn_delta"]["reversing"]
    memory = {}
    for turn, (x, y) in enumerate([(10, 10), (13, 10), (16, 11)], start=1):
        snap = _snap(turn, x, y)
        civ6_turn_delta.observe(snap, memory)
    assert "reversing" not in snap["_turn_delta"]
