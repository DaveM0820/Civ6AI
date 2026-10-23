"""Shared snapshot primitives used by legality, wire, and seat memory.

One implementation of list/dict coercion, turn/player, plot coordinates, and
odd-r hex distance. Callers that previously ignored X-wrap pass wrap=False.
"""
from __future__ import annotations

import re
from typing import Any

PLOT_ID_RE = re.compile(r"PLOT_(-?\d+)_(-?\d+)$")


def lst(value: Any) -> list:
    return value if isinstance(value, list) else []


def dct(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def turn(snapshot: dict[str, Any] | None) -> int:
    try:
        return int(dct((snapshot or {}).get("decision")).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def me(snapshot: dict[str, Any] | None) -> str:
    return str(dct((snapshot or {}).get("decision")).get("player_id") or "")


def plot_xy(row: Any) -> tuple[int, int] | None:
    """Read (x, y) from a plot/unit/city row, a PLOT_x_y string, or x/plot_x keys."""
    if row is None:
        return None
    if isinstance(row, str):
        match = PLOT_ID_RE.search(row)
        return (int(match.group(1)), int(match.group(2))) if match else None
    if not isinstance(row, dict):
        return None
    for x_key, y_key in (("x", "y"), ("plot_x", "plot_y")):
        if row.get(x_key) is not None and row.get(y_key) is not None:
            try:
                return int(row[x_key]), int(row[y_key])
            except (TypeError, ValueError):
                break
    match = PLOT_ID_RE.search(str(row.get("plot_id") or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def hex_dist(
    ax: int,
    ay: int,
    bx: int,
    by: int,
    *,
    width: int | None = None,
    wrap: bool = False,
) -> int:
    """Odd-r offset hex distance. wrap=False matches the coaching/command copies."""

    def cube(x: int, y: int) -> tuple[int, int, int]:
        q = x - (y - (y & 1)) // 2
        return q, y, -q - y

    candidates = [(bx, by)]
    if wrap and width:
        candidates.extend(((bx + width, by), (bx - width, by)))
    aq, ar, as_ = cube(ax, ay)
    best: int | None = None
    for cx, cy in candidates:
        bq, br, bs = cube(cx, cy)
        dist = max(abs(aq - bq), abs(ar - br), abs(as_ - bs))
        best = dist if best is None else min(best, dist)
    return int(best or 0)


def unit_by_id(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    want = str(unit_id or "")
    for unit in lst(snapshot.get("your_units")):
        if isinstance(unit, dict) and str(unit.get("unit_id") or "") == want:
            return unit
    return None
