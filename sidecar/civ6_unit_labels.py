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
    if path is not None:
        try:
            path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    pipeline._STABLE_UNIT_LABELS = labels
    return labels
