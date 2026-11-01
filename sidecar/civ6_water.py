"""Plain water facts: sea coast vs lake shore, and land routes to settle sites.

The snapshot has no lake flag (lakes are TERRAIN_COAST too), so a known water body
fully enclosed by revealed land, with no ocean and at most LAKE_MAX_TILES tiles, is
treated as a lake. A body touching unrevealed tiles counts as sea (cannot tell yet).
"""
from __future__ import annotations

from collections import deque
from typing import Any

from sidecar import civ6_legality as legality

LAKE_MAX_TILES = 9


def _plots(snapshot: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    return legality.known_plots(snapshot)


def lake_tiles(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    plots = _plots(snapshot)
    water = {xy for xy, p in plots.items() if p.get("water")}
    out: set[tuple[int, int]] = set()
    seen: set[tuple[int, int]] = set()
    for start in water:
        if start in seen:
            continue
        body = {start}
        queue = [start]
        open_edge = False
        while queue:
            for n in legality.hex_neighbors(*queue.pop()):
                if n not in plots:
                    open_edge = True
                elif n in water and n not in body:
                    body.add(n)
                    queue.append(n)
        seen |= body
        if (not open_edge and len(body) <= LAKE_MAX_TILES
                and not any(legality.is_ocean(plots[t]) for t in body)):
            out |= body
    return out


def shore_kind(snapshot: dict[str, Any], x: int, y: int, lakes: set | None = None) -> str:
    """'sea coast', 'lake shore only' or 'inland' for the tile (x,y)."""
    plots = _plots(snapshot)
    lakes = lake_tiles(snapshot) if lakes is None else lakes
    adj = [n for n in legality.hex_neighbors(x, y) if (plots.get(n) or {}).get("water")]
    if not adj:
        return "inland"
    return "lake shore only" if all(n in lakes for n in adj) else "sea coast"


def city_xy(city: dict[str, Any]) -> tuple[int, int] | None:
    if isinstance(city.get("x"), int) and isinstance(city.get("y"), int):
        return city["x"], city["y"]
    from sidecar import map_render
    return map_render._parse_plot_coords(city.get("plot_id"))


def city_shore_counts(snapshot: dict[str, Any]) -> tuple[int, int]:
    """(sea-coast cities, lake-only cities)."""
    lakes = lake_tiles(snapshot)
    sea = lake = 0
    for city in snapshot.get("your_cities") or []:
        xy = city_xy(city) if isinstance(city, dict) else None
        if xy is None:
            continue
        kind = shore_kind(snapshot, *xy, lakes)
        sea += kind == "sea coast"
        lake += kind == "lake shore only"
    return sea, lake


def land_steps(snapshot: dict[str, Any], start: tuple[int, int]) -> dict[tuple[int, int], int]:
    """Tiles reachable over known, non-mountain land from start, with hex step counts."""
    plots = _plots(snapshot)
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        for n in legality.hex_neighbors(*cur):
            p = plots.get(n)
            if n in dist or p is None or p.get("water") or legality.is_mountain(p):
                continue
            dist[n] = dist[cur] + 1
            q.append(n)
    return dist


def site_fact(snapshot: dict[str, Any], site: dict[str, Any], settlers: list[tuple[str, tuple[int, int]]],
              lakes: set | None = None) -> str:
    """'S1 (19,32): sea coast; on your landmass, land route ~5 tiles from settler_4'."""
    x, y = site["x"], site["y"]
    plots = _plots(snapshot)
    best: tuple[int, str] | None = None
    for name, xy in settlers:
        steps = land_steps(snapshot, xy).get((x, y))
        if steps is not None and (best is None or steps < best[0]):
            best = (steps, name)
    if best is not None:
        reach = f"on your landmass, land route ~{best[0]} tiles from {best[1]}"
    elif settlers and all(not any(n not in plots for t in land_steps(snapshot, xy)
                                  for n in legality.hex_neighbors(*t)) for _, xy in settlers):
        reach = "on other land (needs embark)"
    elif settlers:
        reach = "no known land route yet (any route runs through unexplored tiles)"
    else:
        reach = ""
    kind = shore_kind(snapshot, x, y, lakes)
    return f"{site.get('label', '')} ({x},{y}): {kind}" + (f"; {reach}" if reach else "")
