"""Previous known tile per visible unit (own and foreign) for one seat.

Kept per seat in ``unit_trail.json``. Foreign units are only what this seat's
snapshot shows, so nothing leaks between seats. The prompt gets one short line
per unit: "was at (x,y) on T12" after a move, or "stationary since T9".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRAIL_FILE = "unit_trail.json"


def _coords(plot: Any) -> str | None:
    from sidecar import pipeline_v2
    xy = pipeline_v2._parse_plot_coords(plot)
    return f"({xy[0]},{xy[1]})" if xy is not None else None


def update(snapshot: dict[str, Any], state_dir: Path | str | None) -> dict[str, str]:
    """Update the seat's trail file and attach {unit_id: text} as snapshot['_unit_trail']."""
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    try:
        turn = int(decision.get("turn", 0))
    except (TypeError, ValueError):
        turn = 0
    path = Path(state_dir) / TRAIL_FILE if state_dir else None
    state: dict[str, Any] = {}
    if path is not None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            state = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            state = {}
    out: dict[str, str] = {}
    units = list(snapshot.get("your_units") or []) + list(snapshot.get("visible_other_units") or [])
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
            continue
        uid, plot = unit["unit_id"], unit.get("plot_id")
        if _coords(plot) is None:
            continue
        prev = state.get(uid) if isinstance(state.get(uid), dict) else None
        if prev is not None and prev.get("turn") == turn:
            rec = prev  # same-turn rerun keeps the first run's view
        elif prev is None:
            rec = {"plot": plot, "turn": turn, "since": turn}
        elif prev.get("plot") != plot:
            rec = {"plot": plot, "turn": turn, "since": turn,
                   "prev_plot": prev.get("plot"), "prev_turn": prev.get("turn")}
        else:
            rec = dict(prev, turn=turn)
        state[uid] = rec
        prev_xy = _coords(rec.get("prev_plot"))
        if rec.get("since") == turn and prev_xy and isinstance(rec.get("prev_turn"), int):
            out[uid] = f"was at {prev_xy} on T{rec['prev_turn']}"
        elif isinstance(rec.get("since"), int) and rec["since"] < turn:
            out[uid] = f"stationary since T{rec['since']}"
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    snapshot["_unit_trail"] = out
    return out


def text_for(snapshot: dict[str, Any], unit_id: Any) -> str | None:
    trail = snapshot.get("_unit_trail")
    return trail.get(unit_id) if isinstance(trail, dict) and isinstance(unit_id, str) else None
