"""Civ 6 tactical close-up: which tiles it frames, and east-west wrap.

Peace: the seat's home territory (cities and owned tiles). When it does not
fit, the window with the most owned tiles (ties go to the capital).
Damage this or last turn (own units/cities hurt, or visible foreign units we
hurt): frame that. At war with no damage: the war front.

Damage is found by comparing HP with the previous call, kept per seat in
``tactical_hp.json`` beside the journal.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from sidecar import map_render

# 12x12 keeps the "x,y" text on every hex readable after the provider shrinks
# the 2048 px image to ~768-1024 px. 15x15 drops it to ~9 px.
TACTICAL_TILES = 12
HP_FILE = "tactical_hp.json"
_PLOT_RE = re.compile(r"^PLOT_(\d+)_(\d+)$")


def _dims(snapshot: dict[str, Any]) -> tuple[int, int, bool]:
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    w = int(game.get("map_width", 1) or 1)
    h = int(game.get("map_height", 1) or 1)
    return w, h, bool(game.get("wrap_x"))


def _xy(plot_id: Any) -> tuple[int, int] | None:
    return map_render._parse_plot_coords(plot_id)


def _dx(a: int, b: int, w: int, wrap: bool) -> int:
    """Signed b - a, shortest way round when the map wraps."""
    d = b - a
    if wrap and w > 0:
        d = (d + w // 2) % w - w // 2
    return d


def _seat(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("decision", {}).get("player_id", ""))


def hp_points(snapshot: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for key, rows in (("u", snapshot.get("your_units")), ("f", snapshot.get("visible_other_units"))):
        for unit in rows or []:
            if not isinstance(unit, dict) or not unit.get("unit_id"):
                continue
            xy = _xy(unit.get("plot_id"))
            hp = unit.get("health_percent")
            if xy is None or not isinstance(hp, (int, float)):
                continue
            out[f"{key}:{unit['unit_id']}"] = {"x": xy[0], "y": xy[1], "hp": int(hp)}
    combat = (snapshot.get("civ6") or {}).get("combat") if isinstance(snapshot.get("civ6"), dict) else None
    seat = _seat(snapshot)
    for city in (combat or {}).get("city_defenses") or []:
        if not isinstance(city, dict) or city.get("owner_player_id") != seat:
            continue
        try:
            hp = int(city.get("hp", 0)) + int(city.get("wall_hp", 0) or 0)
            out[f"c:{city.get('name')}"] = {"x": int(city["x"]), "y": int(city["y"]), "hp": hp}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def update_damage(snapshot: dict[str, Any], seat_dir: Path | None) -> list[tuple[int, int]]:
    """Tiles where damage was dealt this or last turn. Updates the per-seat HP file."""
    turn = int(snapshot.get("decision", {}).get("turn", 0) or 0)
    now = hp_points(snapshot)
    if seat_dir is None:
        return []
    path = Path(seat_dir) / HP_FILE
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    events = [e for e in prev.get("damage", []) if isinstance(e, dict) and turn - int(e.get("turn", -99)) <= 1]
    prev_turn = int(prev.get("turn", -99) or -99)
    old = prev.get("hp") if isinstance(prev.get("hp"), dict) else {}
    if 0 <= turn - prev_turn <= 1:
        for key, row in now.items():
            before = old.get(key)
            if isinstance(before, dict) and int(before.get("hp", 0)) > row["hp"]:
                events.append({"x": row["x"], "y": row["y"], "turn": turn})
    try:
        path.write_text(json.dumps({"turn": turn, "hp": now, "damage": events[-40:]}), encoding="utf-8")
    except OSError:
        pass
    seen: list[tuple[int, int]] = []
    for e in events:
        xy = (int(e["x"]), int(e["y"]))
        if xy not in seen:
            seen.append(xy)
    return seen


def _owned_tiles(snapshot: dict[str, Any]) -> list[tuple[int, int]]:
    seat = _seat(snapshot)
    tiles: list[tuple[int, int]] = []
    plots = (snapshot.get("known_map") or {}).get("plots") or []
    for plot in plots:
        if isinstance(plot, dict) and plot.get("revealed_owner_id") == seat:
            try:
                tiles.append((int(plot["x"]), int(plot["y"])))
            except (KeyError, TypeError, ValueError):
                continue
    for city in snapshot.get("your_cities") or []:
        xy = _xy(city.get("plot_id")) if isinstance(city, dict) else None
        if xy is not None and xy not in tiles:
            tiles.append(xy)
    return tiles


def _capital(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    cities = [c for c in snapshot.get("your_cities") or [] if isinstance(c, dict)]
    for city in sorted(cities, key=lambda c: not c.get("is_capital")):
        xy = _xy(city.get("plot_id"))
        if xy is not None:
            return xy
    for unit in snapshot.get("your_units") or []:
        xy = _xy(unit.get("plot_id")) if isinstance(unit, dict) else None
        if xy is not None:
            return xy
    return None


def _window(cx: int, cy: int, snapshot: dict[str, Any], n: int) -> dict[str, int]:
    w, h, wrap = _dims(snapshot)
    vw, vh = min(n, w), min(n, h)
    x0 = cx - vw // 2
    x0 = x0 % w if wrap else max(0, min(x0, w - vw))
    y0 = max(0, min(cy - vh // 2, h - vh))
    return {"x0": x0, "y0": y0, "width": vw, "height": vh}


def _frame_points(points: list[tuple[int, int]], snapshot: dict[str, Any], n: int,
                  anchor: tuple[int, int] | None) -> dict[str, int]:
    """Window of n x n holding the most points; ties go nearest the anchor."""
    w, _, wrap = _dims(snapshot)
    ref = anchor or points[0]
    rel = [(ref[0] + _dx(ref[0], x, w, wrap), y) for x, y in points]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    if max(xs) - min(xs) < n and max(ys) - min(ys) < n:
        return _window((min(xs) + max(xs) + 1) // 2, (min(ys) + max(ys) + 1) // 2, snapshot, n)
    best = None
    half = n // 2
    for cx, cy in rel:
        count = sum(1 for x, y in rel if -half <= x - cx < n - half and -half <= y - cy < n - half)
        dist = max(abs(cx - ref[0]), abs(cy - ref[1]))
        score = (-count, dist)
        if best is None or score < best[0]:
            best = (score, (cx, cy))
    return _window(best[1][0], best[1][1], snapshot, n)


def pick_tactical_frame(
    snapshot: dict[str, Any],
    *,
    at_war: bool,
    damage: list[tuple[int, int]],
    n: int = TACTICAL_TILES,
) -> tuple[dict[str, int], str]:
    capital = _capital(snapshot)
    if damage:
        rect = _frame_points(damage, snapshot, n, damage[-1])
        return rect, "fighting (damage dealt this or last turn)"
    if at_war:
        from sidecar.map_situational import pick_auto_war_focus_tile

        front = pick_auto_war_focus_tile(snapshot)
        if front is not None:
            return _window(front[0], front[1], snapshot, n), "war front"
    owned = _owned_tiles(snapshot)
    if owned:
        return _frame_points(owned, snapshot, n, capital), "home territory"
    if capital is not None:
        return _window(capital[0], capital[1], snapshot, n), "home territory"
    w, h, _ = _dims(snapshot)
    return _window(w // 2, h // 2, snapshot, n), "map centre"


def rotate_snapshot_x(snapshot: dict[str, Any], shift: int) -> dict[str, Any]:
    """Copy of the snapshot with every x moved left by ``shift`` (mod map width).

    Lets the renderer draw a window that crosses the east-west seam as one
    straight block. Labels add ``shift`` back so they show the game's x.
    """
    w, h, _ = _dims(snapshot)
    out = copy.deepcopy(snapshot)

    def fix(obj: Any) -> Any:
        if isinstance(obj, dict):
            if isinstance(obj.get("x"), int) and isinstance(obj.get("y"), int):
                obj["x"] = (obj["x"] - shift) % w
            if isinstance(obj.get("target_x"), int):
                obj["target_x"] = (obj["target_x"] - shift) % w
            for key, value in list(obj.items()):
                if isinstance(value, str):
                    m = _PLOT_RE.match(value)
                    if m:
                        obj[key] = f"PLOT_{(int(m.group(1)) - shift) % w}_{m.group(2)}"
                else:
                    fix(value)
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                if isinstance(value, str):
                    m = _PLOT_RE.match(value)
                    if m:
                        obj[i] = f"PLOT_{(int(m.group(1)) - shift) % w}_{m.group(2)}"
                else:
                    fix(value)
        return obj

    known = out.get("known_map") if isinstance(out.get("known_map"), dict) else None
    grid = known.get("visibility_grid") if known else None
    if known is not None and isinstance(grid, list) and grid:
        ox, oy = map_render.visibility_grid_origin(snapshot.get("known_map"))
        full = [["?"] * w for _ in range(h)]
        for ry, row in enumerate(grid):
            if not isinstance(row, str) or not 0 <= oy + ry < h:
                continue
            for rx, ch in enumerate(row):
                full[oy + ry][(ox + rx - shift) % w] = ch
        known["visibility_grid"] = ["".join(r) for r in full]
        grid_view = {"x0": 0, "y0": 0, "width": w, "height": h}
        known["viewport"] = grid_view
        if isinstance(known.get("image"), dict):
            known["image"]["viewport"] = dict(grid_view)
        saved = known.pop("visibility_grid")
        saved_vp = known.pop("viewport")
        fix(out)
        known["visibility_grid"] = saved
        known["viewport"] = saved_vp
    else:
        fix(out)
    return out
