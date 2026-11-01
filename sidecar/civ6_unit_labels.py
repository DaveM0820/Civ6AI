"""Stable per-seat unit labels (settler_2 stays settler_2 for the unit's life).

Kept per seat in ``unit_labels.json`` next to ``unit_trail.json``. On first use
the labels are seeded from the old type-count numbering so a running game keeps
the labels it already shows. A new unit gets the next number for its type that
was never used this game; a unit whose type changes (upgrade) gets a new label.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LABEL_FILE = "unit_labels.json"


def _type_of(label: str) -> str:
    return label.rsplit("_", 1)[0]


def assign(units: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, str]:
    """Return {unit_id: label} for the seat's own units and update ``state`` in place."""
    from sidecar import pipeline_v2 as pipeline

    labels = state.get("labels") if isinstance(state.get("labels"), dict) else {}
    nxt = state.get("next") if isinstance(state.get("next"), dict) else {}
    own = sorted((u for u in units if isinstance(u, dict) and isinstance(u.get("unit_id"), str)),
                 key=lambda u: u["unit_id"])
    if not labels:
        pipeline._STABLE_UNIT_LABELS = None
        seeded = pipeline._build_unit_wire_id_map(own)
        labels = dict(seeded)
        for label in seeded.values():
            kind, _, num = label.rpartition("_")
            nxt[kind] = max(int(nxt.get(kind) or 0), int(num) if num.isdigit() else 0)
    out: dict[str, str] = {}
    for unit in own:
        uid = unit["unit_id"]
        kind = pipeline._unit_type_label(unit.get("unit_type_id"))
        label = labels.get(uid)
        if not isinstance(label, str) or _type_of(label) != kind:
            nxt[kind] = int(nxt.get(kind) or 0) + 1
            label = f"{kind}_{nxt[kind]}"
        out[uid] = label
    state["labels"] = out  # dead units drop out; their numbers are not reused
    state["next"] = nxt
    return out


def update_goals(snapshot: dict[str, Any], state: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, dict]:
    """Per-unit goal memory: the model's last MoveTo target, kept until the unit is
    there, gets a different kind of order, or is gone. ``rows`` are last turn's apply rows."""
    from sidecar.civ6_common import plot_xy

    goals = state.get("goals") if isinstance(state.get("goals"), dict) else {}
    units = {str(u.get("unit_id")): u for u in snapshot.get("your_units") or [] if isinstance(u, dict)}
    for row in rows:
        if not isinstance(row, dict) or row.get("source") != "model":
            continue
        fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
        uid = str(fixed.get("unit_id") or "")
        if not uid:
            continue
        if row.get("kind") == "move_unit" and isinstance(fixed.get("target_x"), int) and isinstance(fixed.get("target_y"), int):
            old = goals.get(uid) if isinstance(goals.get(uid), dict) else {}
            same = (old.get("x"), old.get("y")) == (fixed["target_x"], fixed["target_y"])
            goals[uid] = {"x": fixed["target_x"], "y": fixed["target_y"],
                          "set_turn": old.get("set_turn") if same else row.get("turn")}
        elif row.get("kind") not in ("fallback_hint",):
            goals.pop(uid, None)
    for uid in list(goals):
        unit = units.get(uid)
        goal = goals[uid]
        if unit is None or not isinstance(goal, dict) or plot_xy(unit) == (goal.get("x"), goal.get("y")):
            goals.pop(uid, None)
    state["goals"] = goals
    return goals


def activate(snapshot: dict[str, Any], state_dir: Path | str | None) -> dict[str, str]:
    """Load, assign, save, and make the labels the ones every prompt/parse call uses."""
    from sidecar import pipeline_v2 as pipeline

    path = Path(state_dir) / LABEL_FILE if state_dir else None
    state: dict[str, Any] = {}
    if path is not None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            state = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            state = {}
    labels = assign(list(snapshot.get("your_units") or []), state)
    try:
        from sidecar import civ6_apply_results

        decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
        rows: list[dict[str, Any]] = []
        if state_dir and decision.get("turn") is not None:
            turn = int(decision["turn"])
            if state.get("goals_turn") != turn:
                _, rows = civ6_apply_results.latest_turn_rows(
                    civ6_apply_results.load_apply_results(Path(state_dir)), str(decision.get("player_id") or ""), turn)
                state["goals_turn"] = turn
        snapshot["_unit_goals"] = update_goals(snapshot, state, rows)
    except Exception:
        pass
    if path is not None:
        try:
            path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    pipeline._STABLE_UNIT_LABELS = labels
    return labels
