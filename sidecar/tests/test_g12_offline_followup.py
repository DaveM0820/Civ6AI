"""Offline follow-ups for remaining game-12 review bugs (no Civ / no model spend)."""
from __future__ import annotations

from sidecar import civ6_apply_results as ar
from sidecar import civ6_prompt_coaching as coaching


def _snap_units():
    return {
        "player_id": "PLAYER_3",
        "your_units": [
            {
                "unit_id": "UNIT_1",
                "unit_type_id": "UNIT_WARRIOR_MONK",
                "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
                "domain_id": "DOMAIN_LAND",
                "x": 44,
                "y": 18,
            },
            {
                "unit_id": "UNIT_9",
                "unit_type_id": "UNIT_SETTLER",
                "unit_class_id": "FORMATION_CLASS_CIVILIAN",
                "domain_id": "DOMAIN_LAND",
                "x": 45,
                "y": 18,
            },
        ],
        "known_map": {
            "plots": [
                {"x": 45, "y": 18, "water": False, "revealed_owner_id": "PLAYER_3"},
                {"x": 46, "y": 18, "water": True, "revealed_owner_id": "PLAYER_5"},
            ]
        },
    }


def test_stack_failure_names_same_class_blocker_not_civilian():
    snap = _snap_units()
    mover = snap["your_units"][0]
    # Military stepping onto a tile that also has... wait, stack limit is same class.
    # Put another military on the destination.
    snap["your_units"].append({
        "unit_id": "UNIT_2",
        "unit_type_id": "UNIT_WARRIOR",
        "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
        "domain_id": "DOMAIN_LAND",
        "x": 45,
        "y": 18,
    })
    text = ar.move_failure_text(
        snap, "warrior_monk_1", 45, 18, "stack_limit", "PLAYER_3", unit=mover
    )
    assert "warrior" in text.lower() or "UNIT_2" in text or "unit_2" in text.lower()
    # Must not claim the settler blocked a military share that is legal.
    assert "settler" not in text.lower() or "same-class" in text.lower()


def test_foreign_border_step_refusal_mentions_closed_borders():
    snap = _snap_units()
    ship = {
        "unit_id": "UNIT_7",
        "unit_type_id": "UNIT_CARAVEL",
        "unit_class_id": "FORMATION_CLASS_NAVAL",
        "domain_id": "DOMAIN_SEA",
        "x": 45,
        "y": 18,
    }
    snap["your_units"].append(ship)
    text = ar.move_failure_text(
        snap, "caravel_1", 46, 18, "step_refused", "PLAYER_3", domain="DOMAIN_SEA", unit=ship
    )
    assert "closed borders" in text.lower() or "open borders" in text.lower()
    assert "PLAYER_5" in text or "borders of" in text.lower()


def test_exploration_attention_keeps_fact_line_when_metric_present():
    snap = {
        "player_id": "PLAYER_0",
        "_explore_metric": {"percent": 5, "revealed": 50, "total": 1000, "turns_since_reveal": 0},
        "civ6": {"true_explored": {"revealed": 50, "total": 1000, "percent": 5}},
        "history": {"explore_tracking": {"samples": [{"turn": 10, "revealed": 40}, {"turn": 12, "revealed": 50}]}},
    }
    # Even without a stall, the EXPLORATION fact must remain (g12 B6).
    note = coaching.civ6_exploration_attention(snap)
    assert note is not None
    assert "EXPLORATION:" in note
    assert "5%" in note


def test_exploration_attention_not_none_without_older_samples():
    snap = {
        "player_id": "PLAYER_0",
        "history": {
            "explore_tracking": {
                "samples": [{"turn": 50, "revealed": 40}, {"turn": 51, "revealed": 41}]
            }
        },
    }
    # Force explored percent via known_map size heuristics if needed.
    snap["civ6"] = {"map_explored_percent": 5}
    # Patch through _civ6_explored_percent by providing metric-less path:
    # monkey via known fields used by helper.
    from sidecar import civ6_prompt_coaching as c

    original = c._civ6_explored_percent
    c._civ6_explored_percent = lambda _s: 5
    try:
        note = c.civ6_exploration_attention(snap)
    finally:
        c._civ6_explored_percent = original
    assert note is not None
    assert "EXPLORATION:" in note
