"""Plain map facts a seat would otherwise forget: recently seen barbarians, home landmass size."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sidecar import map_render

BARB_MEMORY_NAME = "barbarians_seen.json"
BARB_KEEP_TURNS = 5
BARB_MAX_LINES = 4
LANDMASS_EDGE_CAP = 4
BARBARIAN_IDS = {"PLAYER_63"}


def _turn(snapshot: dict[str, Any]) -> int:
    try:
        return int((snapshot.get("decision") or {}).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def _is_barbarian(snapshot: dict[str, Any], owner: str) -> bool:
    if owner in BARBARIAN_IDS:
        return True
    from sidecar.civ6_wire import civ6_player_kind

    for p in snapshot.get("known_players") or []:
        if isinstance(p, dict) and str(p.get("player_id")) == owner:
            return civ6_player_kind(p) == "barbarians"
    return False


def _memory_path(snapshot: dict[str, Any]) -> Path | None:
    raw = snapshot.get("_session_dir")
    return Path(raw) / BARB_MEMORY_NAME if raw else None


def barbarian_last_seen(snapshot: dict[str, Any]) -> list[str]:
    """Update the seat's barbarian memory; return 'Barbarian Slinger (42,14) T24' for ones not visible now."""
    turn = _turn(snapshot)
    path = _memory_path(snapshot)
    seen: dict[str, dict[str, Any]] = {}
    if path is not None and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            seen = {k: v for k, v in (data.get("units") or {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            seen = {}
    visible: set[str] = set()
    for u in snapshot.get("visible_other_units") or []:
        if not isinstance(u, dict) or not _is_barbarian(snapshot, str(u.get("owner_player_id") or "")):
            continue
        xy = map_render._parse_plot_coords(u.get("plot_id"))
        uid = str(u.get("unit_id") or "")
        if xy is None or not uid:
            continue
        visible.add(uid)
        name = str(u.get("unit_type_id") or "UNIT_UNIT").replace("UNIT_", "", 1).replace("_", " ").title()
        seen[uid] = {"name": name, "x": xy[0], "y": xy[1], "turn": turn}
    seen = {k: v for k, v in seen.items() if turn - int(v.get("turn") or 0) <= BARB_KEEP_TURNS}
    if path is not None:
        try:
            path.write_text(json.dumps({"turn": turn, "units": seen}), encoding="utf-8")
        except OSError:
            pass
    hidden = [v for k, v in seen.items() if k not in visible and int(v.get("turn") or 0) < turn]
    hidden.sort(key=lambda v: -int(v.get("turn") or 0))
    return [f"Barbarian {v['name']} ({v['x']},{v['y']}) T{v['turn']}" for v in hidden[:BARB_MAX_LINES]]


def _neighbors(x: int, y: int, width: int, wrap: bool) -> list[tuple[int, int]]:
    deltas = ([(1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1)] if y & 1
              else [(1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1)])
    out = []
    for dx, dy in deltas:
        nx = x + dx
        if wrap and width > 0:
            nx %= width
        out.append((nx, y + dy))
    return out


def _can_reach_other_land(snapshot: dict[str, Any]) -> bool:
    research = (snapshot.get("your_empire") or {}).get("research") or {}
    known = research.get("known_tech_ids") if isinstance(research, dict) else None
    return isinstance(known, list) and "TECH_SHIPBUILDING" in known


def landmass_line(snapshot: dict[str, Any]) -> str | None:
    """'N known land tiles; unrevealed land on it: ...' for the land the capital stands on."""
    from sidecar.civ6_tactical_view import _capital

    start = _capital(snapshot)
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    plots = [p for p in known.get("plots") or [] if isinstance(p, dict)
             and isinstance(p.get("x"), int) and isinstance(p.get("y"), int)]
    if start is None or not plots:
        return None
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    width = int(game.get("map_width") or 0)
    wrap = bool(game.get("wrap_x")) and width > 0
    land = {(p["x"], p["y"]) for p in plots if not p.get("water")}
    revealed = {(p["x"], p["y"]) for p in plots}
    if start not in land:
        return None
    region = {start}
    queue = [start]
    while queue:
        for n in _neighbors(*queue.pop(), width, wrap):
            if n in land and n not in region:
                region.add(n)
                queue.append(n)
    edges = sorted(t for t in region if any(n not in revealed for n in _neighbors(*t, width, wrap)))
    if edges:
        shown = ", ".join(f"({x},{y})" for x, y in edges[:LANDMASS_EDGE_CAP])
        more = "…" if len(edges) > LANDMASS_EDGE_CAP else ""
        fog = f"unrevealed land on it: may continue past {shown}{more}"
    else:
        fog = "unrevealed land on it: none"
    line = f"{len(region)} known land tiles; {fog}"
    if not _can_reach_other_land(snapshot):
        line += "; land units reach other land only after Shipbuilding (embark); ships can scout it"
    return line
