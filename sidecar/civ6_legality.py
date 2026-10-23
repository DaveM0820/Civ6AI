"""One seat-turn legality layer: ops, tiles, diplo, government, city strikes.

The snapshot already has the game's facts (plots, tech, stacking, legal
commands, war flags, civic-complete). This module is the only place those
facts become "may the seat issue this order?". The prompt offers command
kinds from here; dispatch validates the same way. Per-case prompt nudges
and one-off filters do not live elsewhere.
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

BLACKLIST_TURNS = 10
REJECTION_PROMPT_CAP = 5
STATE_NAME = "legality.json"

# One default per role. Look up by unit_role(), never by a specific unit type.
ROLE_DEFAULTS = {
    "military": "defend",
    "builder": "improve",
    "scout": "explore",
}

ROLE_TYPE_TAGS = (
    ("SETTLER", None),
    ("TRADER", None),
    ("BUILDER", "builder"),
    ("SCOUT", "scout"),
    ("RANGER", "scout"),
    ("RECON", "scout"),
)

ROLE_OF_CLASS = {
    "FORMATION_CLASS_RECON": "scout",
    "FORMATION_CLASS_CIVILIAN": None,
    "FORMATION_CLASS_LAND_COMBAT": "military",
    "FORMATION_CLASS_NAVAL": "military",
    "FORMATION_CLASS_AIR": "military",
    "FORMATION_CLASS_SUPPORT": "military",
}

_PLOT_ID_RE = re.compile(r"PLOT_(-?\d+)_(-?\d+)$")


def _lst(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dct(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _turn(snapshot: dict[str, Any]) -> int:
    try:
        return int(_dct(snapshot.get("decision")).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def _me(snapshot: dict[str, Any]) -> str:
    return str(_dct(snapshot.get("decision")).get("player_id") or "")


def plot_xy(row: dict[str, Any] | None) -> tuple[int, int] | None:
    if not isinstance(row, dict):
        return None
    try:
        if row.get("x") is not None and row.get("y") is not None:
            return int(row["x"]), int(row["y"])
    except (TypeError, ValueError):
        pass
    match = _PLOT_ID_RE.search(str(row.get("plot_id") or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def known_plots(snapshot: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    known = _dct(snapshot.get("known_map"))
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for plot in _lst(known.get("plots")):
        if not isinstance(plot, dict):
            continue
        xy = plot_xy(plot)
        if xy is not None:
            out[xy] = plot
    return out


def is_mountain(plot: dict[str, Any] | None) -> bool:
    if not isinstance(plot, dict):
        return False
    if plot.get("peak"):
        return True
    terrain = str(plot.get("terrain_id") or plot.get("terrain") or "")
    return "MOUNTAIN" in terrain.upper()


def can_embark(snapshot: dict[str, Any]) -> bool:
    research = _dct(_dct(snapshot.get("your_empire")).get("research"))
    known = {str(t) for t in _lst(research.get("known_tech_ids")) if t}
    return "TECH_SHIPBUILDING" in known


def own_occupied_plots(snapshot: dict[str, Any]) -> dict[tuple[int, int], list[str]]:
    held: dict[tuple[int, int], list[str]] = {}
    for unit in _lst(snapshot.get("your_units")):
        if not isinstance(unit, dict):
            continue
        xy = plot_xy(unit)
        uid = str(unit.get("unit_id") or "")
        if xy is None or not uid:
            continue
        held.setdefault(xy, []).append(uid)
    return held


def hex_neighbors(x: int, y: int) -> list[tuple[int, int]]:
    if y & 1:
        deltas = ((1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1))
    else:
        deltas = ((1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1))
    return [(x + dx, y + dy) for dx, dy in deltas]


def unit_role(unit: dict[str, Any]) -> str | None:
    typ = str(unit.get("unit_type_id") or "").upper()
    for tag, role in ROLE_TYPE_TAGS:
        if tag in typ:
            return role
    if int(unit.get("build_charges") or 0) > 0:
        return "builder"
    cls = str(unit.get("unit_class_id") or "").upper()
    if cls in ROLE_OF_CLASS:
        return ROLE_OF_CLASS[cls]
    if "RECON" in cls:
        return "scout"
    if "CIVILIAN" in cls:
        return None
    if str(unit.get("domain_id") or "") in {"DOMAIN_LAND", "DOMAIN_SEA", "DOMAIN_AIR"}:
        if typ.startswith("UNIT_"):
            return "military"
    return None


def _unit_by_id(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    for unit in _lst(snapshot.get("your_units")):
        if isinstance(unit, dict) and str(unit.get("unit_id") or "") == unit_id:
            return unit
    return None


def _ops_from_commands(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    ops: dict[str, set[str]] = {}
    for command in _lst(snapshot.get("legal_commands")):
        if not isinstance(command, dict):
            continue
        fixed = _dct(command.get("fixed_arguments"))
        uid = str(fixed.get("unit_id") or "")
        kind = str(command.get("kind") or "")
        if uid:
            ops.setdefault(uid, set()).add(kind)
    for unit in _lst(snapshot.get("your_units")):
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("unit_id") or "")
        moves = _dct(unit.get("movement")).get("current")
        if uid and (isinstance(moves, (int, float)) and moves > 0 or unit.get("needs_orders")):
            ops.setdefault(uid, set()).add("move_unit")
    return ops


def unit_ops(snapshot: dict[str, Any], unit_id: str) -> set[str]:
    return set(_ops_from_commands(snapshot).get(unit_id) or ())


def tile_passable(snapshot: dict[str, Any], unit: dict[str, Any], x: int, y: int) -> str | None:
    """None if this unit may stand on (x,y). Otherwise a reason code."""
    plots = known_plots(snapshot)
    plot = plots.get((x, y))
    domain = str(unit.get("domain_id") or "DOMAIN_LAND")
    if plot is None:
        return None
    if is_mountain(plot):
        return "impassable"
    water = bool(plot.get("water"))
    if domain != "DOMAIN_SEA" and water and not can_embark(snapshot):
        return "impassable"
    if domain == "DOMAIN_SEA" and not water:
        return "impassable"
    uid = str(unit.get("unit_id") or "")
    holders = own_occupied_plots(snapshot).get((x, y)) or []
    others = [h for h in holders if h != uid]
    if others:
        return "occupied"
    if "BUILDER" in str(unit.get("unit_type_id") or ""):
        owner = plot.get("revealed_owner_id")
        if owner != _me(snapshot):
            return "outside_borders"
    return None


def reachable(snapshot: dict[str, Any], unit: dict[str, Any], dest: tuple[int, int]) -> bool:
    """False only when the known passable component is closed and misses dest."""
    start = plot_xy(unit)
    if start is None or start == dest:
        return True
    plots = known_plots(snapshot)
    if dest not in plots:
        return True
    seen = {start}
    q: deque[tuple[int, int]] = deque([start])
    saw_fog = False
    while q:
        x, y = q.popleft()
        for nx, ny in hex_neighbors(x, y):
            if (nx, ny) in seen:
                continue
            if (nx, ny) == dest:
                return True
            if (nx, ny) not in plots:
                saw_fog = True
                continue
            plot = plots[(nx, ny)]
            if is_mountain(plot):
                continue
            water = bool(plot.get("water"))
            domain = str(unit.get("domain_id") or "DOMAIN_LAND")
            if domain != "DOMAIN_SEA" and water and not can_embark(snapshot):
                continue
            if domain == "DOMAIN_SEA" and not water:
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return saw_fog


def move_problem(snapshot: dict[str, Any], unit_id: str, x: Any, y: Any) -> str | None:
    try:
        tx, ty = int(x), int(y)
    except (TypeError, ValueError):
        return "impassable"
    unit = _unit_by_id(snapshot, str(unit_id))
    if unit is None:
        return None
    reason = tile_passable(snapshot, unit, tx, ty)
    if reason:
        return reason
    if not reachable(snapshot, unit, (tx, ty)):
        return "no_path"
    return None


def city_strike_available(snapshot: dict[str, Any]) -> bool:
    """Same fact the prompt, validator, and unused-strike fallback use."""
    combat = _dct(_dct(snapshot.get("civ6")).get("combat"))
    flag = combat.get("city_strike_available")
    offered = any(
        isinstance(c, dict) and c.get("kind") == "city_attack"
        for c in _lst(snapshot.get("legal_commands"))
    )
    if flag is True or offered:
        return True
    return False


def city_strike_targets(snapshot: dict[str, Any]) -> list[tuple[str, int, int]]:
    if not city_strike_available(snapshot):
        return []
    out: list[tuple[str, int, int]] = []
    for command in _lst(snapshot.get("legal_commands")):
        if not isinstance(command, dict) or command.get("kind") != "city_attack":
            continue
        fixed = _dct(command.get("fixed_arguments"))
        try:
            out.append((str(fixed.get("city_id") or ""), int(fixed["target_x"]), int(fixed["target_y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def change_government_allowed(snapshot: dict[str, Any]) -> bool:
    gov = _dct(_dct(_dct(snapshot.get("civ6")).get("governance")).get("government"))
    return gov.get("change_allowed") is True


def _major(snapshot: dict[str, Any], pid: str) -> dict[str, Any]:
    diplo = _dct(_dct(snapshot.get("civ6")).get("diplomacy"))
    for row in _lst(diplo.get("majors")) + _lst(diplo.get("city_states")):
        if isinstance(row, dict) and str(row.get("player_id") or "") == pid:
            return row
    return {}


def _known_civics_techs(snapshot: dict[str, Any]) -> set[str]:
    empire = _dct(snapshot.get("your_empire"))
    known = {str(c.get("id")) for c in _lst(empire.get("civics")) if isinstance(c, dict) and c.get("key") == "known"}
    known |= {str(t) for t in _lst(_dct(empire.get("research")).get("known_tech_ids")) if t}
    return known


def diplo_actions(snapshot: dict[str, Any], pid: str) -> set[str]:
    """Legal diplomatic verbs toward pid this turn."""
    major = _major(snapshot, pid)
    at_war = major.get("at_war") is True
    known = _known_civics_techs(snapshot)
    actions: set[str] = set()
    if at_war:
        actions.add("PEACE_TREATY")
        actions.add("peace")
    elif major.get("can_declare_war") is True:
        actions.add("DECLARE_WAR")
    if not at_war:
        actions.add("friendship")
        actions.add("delegation")
        if "CIVIC_EARLY_EMPIRE" in known:
            actions.add("open_borders")
        if "TECH_WRITING" in known:
            actions.add("embassy")
        if "CIVIC_DIPLOMATIC_SERVICE" in known and major.get("declared_friendship"):
            actions.add("alliance")
        if _open_friendship_from(snapshot, pid):
            actions.add("ACCEPT_DOF")
    return actions


def _open_friendship_from(snapshot: dict[str, Any], pid: str) -> bool:
    raw = snapshot.get("_session_dir")
    if not raw:
        return False
    root = Path(str(raw))
    path = (root.parent if root.name.startswith("PLAYER_") else root) / "deals.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"), strict=False) if path.is_file() else []
    except (OSError, ValueError):
        return False
    me = _me(snapshot)
    for deal in rows if isinstance(rows, list) else []:
        if not isinstance(deal, dict):
            continue
        if deal.get("status") != "pending" or deal.get("to") != me or str(deal.get("from")) != pid:
            continue
        kinds = {i.get("kind") for i in _lst(deal.get("give")) + _lst(deal.get("want")) if isinstance(i, dict)}
        if "friendship" in kinds:
            return True
    return False


def diplo_problem(snapshot: dict[str, Any], pid: str, action: str) -> str | None:
    allowed = diplo_actions(snapshot, pid)
    token = str(action or "").strip().upper().replace(" ", "_")
    compact = token.replace("_", "")
    if token in {"PEACE", "PEACE_TREATY", "MAKE_PEACE"} or compact in {"PEACE", "PEACETREATY", "MAKEPEACE"}:
        return None if "PEACE_TREATY" in allowed else "peace_not_at_war"
    if token in {"ACCEPT_DOF", "ACCEPT_FRIENDSHIP", "ACCEPT_DECLARED_FRIENDSHIP"}:
        return None if "ACCEPT_DOF" in allowed else "illegal_dof"
    if token in {"DECLARE_WAR", "DECLARE_FORMAL_WAR", "WAR"}:
        return None if "DECLARE_WAR" in allowed else "cannot_declare_war"
    low = str(action or "").strip().lower()
    if low in allowed:
        return None
    return None


def pact_problem(snapshot: dict[str, Any], pid: str, kinds: set, require_unlock: bool = True) -> str | None:
    allowed = diplo_actions(snapshot, pid)
    for kind in sorted(k for k in kinds if k):
        if kind == "peace" and "peace" not in allowed:
            return "peace_not_at_war"
        if kind != "peace" and _major(snapshot, pid).get("at_war") is True:
            return f"no_{kind}_at_war"
        if require_unlock and kind in {"friendship", "alliance", "open_borders", "embassy", "delegation"}:
            if kind not in allowed and kind != "peace":
                if kind == "alliance" and "CIVIC_DIPLOMATIC_SERVICE" not in _known_civics_techs(snapshot):
                    return "alliance needs CIVIC_DIPLOMATIC_SERVICE"
                if kind == "open_borders" and "CIVIC_EARLY_EMPIRE" not in _known_civics_techs(snapshot):
                    return "open_borders needs CIVIC_EARLY_EMPIRE"
                if kind == "embassy" and "TECH_WRITING" not in _known_civics_techs(snapshot):
                    return "embassy needs TECH_WRITING"
    return None


def order_label(command: dict[str, Any]) -> str:
    kind = str(command.get("kind") or "")
    args = _dct(command.get("arguments") or command.get("fixed_arguments"))
    x, y = args.get("target_x", args.get("x")), args.get("target_y", args.get("y"))
    uid = args.get("unit_id") or args.get("city_id") or ""
    if kind == "move_unit" and x is not None:
        return f"MoveTo({x},{y})"
    if kind in {"attack_target", "range_attack", "melee_attack"} and x is not None:
        return f"AttackTo({x},{y})"
    if kind == "city_attack" and x is not None:
        return f"CityStrike({x},{y})"
    if kind == "change_government":
        return f"change_government({args.get('government_id') or ''})"
    if kind == "explore":
        return f"Explore({uid})"
    return f"{kind}({uid})" if uid else kind or str(command.get("command_id") or "order")


def order_problem(snapshot: dict[str, Any], command: dict[str, Any]) -> str | None:
    kind = str(command.get("kind") or "")
    args = _dct(command.get("arguments") or command.get("fixed_arguments"))
    if kind == "move_unit":
        return move_problem(snapshot, str(args.get("unit_id") or ""), args.get("target_x"), args.get("target_y"))
    if kind == "city_attack":
        if not city_strike_available(snapshot):
            return "city_strike_unavailable"
        targets = {(c, x, y) for c, x, y in city_strike_targets(snapshot)}
        try:
            key = (str(args.get("city_id") or ""), int(args.get("target_x")), int(args.get("target_y")))
        except (TypeError, ValueError):
            return "city_strike_unavailable"
        if targets and key not in targets:
            return "city_strike_unavailable"
        return None
    if kind == "change_government":
        return None if change_government_allowed(snapshot) else "government_locked"
    if kind in {"send_diplomatic_action", "execute_deal"}:
        action = str(args.get("action") or args.get("kind") or "")
        pid = str(args.get("target_player_id") or args.get("player_id") or "")
        if action:
            return diplo_problem(snapshot, pid, action)
    return None


def filter_orders(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    rows: list[dict[str, Any]] = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        problem = order_problem(snapshot, command)
        if problem:
            line = f"Rejected last turn: {order_label(command)} - {problem}"
            rejected.append(line)
            rows.append({"order": order_label(command), "reason": problem, "turn": _turn(snapshot)})
            continue
        kept.append(command)
    remember_rejections(snapshot, rows)
    return kept, rejected


def _state_path(snapshot: dict[str, Any]) -> Path | None:
    raw = snapshot.get("_session_dir")
    if not raw:
        return None
    return Path(str(raw)) / STATE_NAME


def load_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(snapshot)
    if path is None or not path.is_file():
        return {"blacklist": {}, "rejections": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError):
        return {"blacklist": {}, "rejections": []}
    return data if isinstance(data, dict) else {"blacklist": {}, "rejections": []}


def save_state(snapshot: dict[str, Any], state: dict[str, Any]) -> None:
    path = _state_path(snapshot)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def remember_rejections(snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    state = load_state(snapshot)
    prev = [r for r in _lst(state.get("rejections")) if isinstance(r, dict)]
    state["rejections"] = (prev + rows)[-24:]
    save_state(snapshot, state)


def rejection_lines(snapshot: dict[str, Any]) -> list[str]:
    turn = _turn(snapshot)
    lines: list[str] = []
    for row in _lst(load_state(snapshot).get("rejections")):
        if not isinstance(row, dict):
            continue
        try:
            when = int(row.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if when != turn - 1 and when != turn:
            continue
        order = str(row.get("order") or "order")
        reason = str(row.get("reason") or "rejected")
        lines.append(f"Rejected last turn: {order} - {reason}")
        if len(lines) >= REJECTION_PROMPT_CAP:
            break
    return lines


def blacklist_key(x: int, y: int) -> str:
    return f"{int(x)},{int(y)}"


def is_blacklisted(snapshot: dict[str, Any], x: int, y: int) -> bool:
    state = load_state(snapshot)
    raw = _dct(state.get("blacklist")).get(blacklist_key(x, y))
    try:
        when = int(raw)
    except (TypeError, ValueError):
        return False
    return _turn(snapshot) - when < BLACKLIST_TURNS


def add_blacklist(snapshot: dict[str, Any], x: int, y: int, turn: int | None = None) -> None:
    state = load_state(snapshot)
    board = dict(_dct(state.get("blacklist")))
    board[blacklist_key(x, y)] = int(turn if turn is not None else _turn(snapshot))
    state["blacklist"] = board
    save_state(snapshot, state)


def ingest_results(snapshot: dict[str, Any]) -> None:
    """Failed explore/move with no_path or no reveal → blacklist that tile."""
    history = _dct(snapshot.get("history"))
    for item in _lst(history.get("command_results")):
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or item.get("summary") or "").lower()
        if "no_path" not in reason and "no_reveal" not in reason and "explore_no_reveal" not in reason:
            continue
        xy = None
        for blob in [item.get("summary"), item.get("reason"), item.get("command_id"), *(_lst(item.get("affected_ids")))]:
            text = str(blob or "")
            m = re.search(r"(-?\d+)[,_](-?\d+)", text)
            if m:
                xy = int(m.group(1)), int(m.group(2))
                break
        if xy is None:
            continue
        try:
            when = int(item.get("turn") or _turn(snapshot))
        except (TypeError, ValueError):
            when = _turn(snapshot)
        add_blacklist(snapshot, xy[0], xy[1], when)


def frontier_target(snapshot: dict[str, Any], unit: dict[str, Any]) -> tuple[int, int] | None:
    """Nearest reachable known tile that touches an unrevealed hex."""
    start = plot_xy(unit)
    if start is None:
        return None
    plots = known_plots(snapshot)
    seen = {start}
    q: deque[tuple[tuple[int, int], tuple[int, int] | None]] = deque([(start, None)])
    while q:
        cur, first_step = q.popleft()
        for nx, ny in hex_neighbors(*cur):
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            if (nx, ny) not in plots:
                if cur != start and not is_blacklisted(snapshot, *cur):
                    if tile_passable(snapshot, unit, *cur) is None:
                        return cur
                continue
            if tile_passable(snapshot, unit, nx, ny) is not None:
                continue
            if is_blacklisted(snapshot, nx, ny):
                continue
            step = first_step or (nx, ny)
            if any(n not in plots for n in hex_neighbors(nx, ny)) and (nx, ny) != start:
                return (nx, ny)
            q.append(((nx, ny), step))
    return None


def _threatened_cities(snapshot: dict[str, Any]) -> list[tuple[int, int]]:
    cities = []
    for city in _lst(snapshot.get("your_cities")):
        if not isinstance(city, dict):
            continue
        xy = plot_xy(city)
        if xy:
            cities.append(xy)
    combat = _dct(_dct(snapshot.get("civ6")).get("combat"))
    hostiles = []
    for row in _lst(combat.get("hostiles")) + _lst(combat.get("hostile_cities")):
        if isinstance(row, dict):
            try:
                hostiles.append((int(row["x"]), int(row["y"])))
            except (KeyError, TypeError, ValueError):
                continue
    threatened = []
    for cx, cy in cities:
        if any(max(abs(cx - hx), abs(cy - hy)) <= 3 for hx, hy in hostiles):
            threatened.append((cx, cy))
    return threatened


def _improve_tile(snapshot: dict[str, Any], unit: dict[str, Any]) -> tuple[int, int] | None:
    here = plot_xy(unit)
    if here is None:
        return None
    me = _me(snapshot)
    occupied = own_occupied_plots(snapshot)
    uid = str(unit.get("unit_id") or "")
    rows: list[tuple[int, int, int, bool]] = []
    for xy, plot in known_plots(snapshot).items():
        if plot.get("water") or is_mountain(plot) or plot.get("city_id") or plot.get("improvement_id"):
            continue
        if me and plot.get("revealed_owner_id") != me:
            continue
        holders = [h for h in occupied.get(xy, []) if h != uid]
        if holders:
            continue
        if move_problem(snapshot, uid, xy[0], xy[1]):
            continue
        dist = max(abs(here[0] - xy[0]), abs(here[1] - xy[1]))
        rows.append((dist, xy[0], xy[1], bool(plot.get("resource_id"))))
    rows.sort(key=lambda r: (not r[3], r[0], r[1], r[2]))
    if not rows:
        return None
    return rows[0][1], rows[0][2]


def _cmd(kind: str, command_id: str, arguments: dict[str, Any], source: str = "fallback") -> dict[str, Any]:
    return {
        "command_id": command_id,
        "kind": kind,
        "arguments": arguments,
        "source": source,
    }


def handled_unit_ids(commands: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for command in commands:
        args = _dct(command.get("arguments") or command.get("fixed_arguments"))
        uid = str(args.get("unit_id") or "")
        if uid:
            out.add(uid)
    return out


def idle_defaults(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Role defaults for units the model did not order. One table, ROLE_DEFAULTS."""
    taken = handled_unit_ids(commands)
    extras: list[dict[str, Any]] = []
    threatened = _threatened_cities(snapshot)
    for unit in _lst(snapshot.get("your_units")):
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("unit_id") or "")
        if not uid or uid in taken:
            continue
        role = unit_role(unit)
        action = ROLE_DEFAULTS.get(role or "")
        if not action:
            continue
        if action == "explore":
            dest = frontier_target(snapshot, unit)
            if dest is not None:
                extras.append(_cmd("move_unit", f"CMD_idle_{uid}_frontier", {
                    "unit_id": uid, "target_x": dest[0], "target_y": dest[1],
                }))
            else:
                extras.append(_cmd("explore", f"CMD_explore_{uid}", {"unit_id": uid}))
        elif action == "improve":
            dest = _improve_tile(snapshot, unit)
            if dest is not None:
                extras.append(_cmd("move_unit", f"CMD_idle_{uid}_improve", {
                    "unit_id": uid, "target_x": dest[0], "target_y": dest[1],
                }))
        elif action == "defend":
            here = plot_xy(unit)
            if threatened and here is not None:
                dest = min(threatened, key=lambda xy: max(abs(here[0] - xy[0]), abs(here[1] - xy[1])))
                if here != dest and move_problem(snapshot, uid, dest[0], dest[1]) is None:
                    extras.append(_cmd("move_unit", f"CMD_idle_{uid}_defend", {
                        "unit_id": uid, "target_x": dest[0], "target_y": dest[1],
                    }))
                    continue
            extras.append(_cmd("unit_posture_fortify", f"CMD_fortify_{uid}", {"unit_id": uid}))
        taken.add(uid)
    return extras


def unused_city_strikes(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not city_strike_available(snapshot):
        return []
    used = {str(_dct(c.get("arguments") or c.get("fixed_arguments")).get("city_id") or "")
            for c in commands if isinstance(c, dict) and c.get("kind") == "city_attack"}
    extras: list[dict[str, Any]] = []
    seen: set[str] = set()
    for command in _lst(snapshot.get("legal_commands")):
        if not isinstance(command, dict) or command.get("kind") != "city_attack":
            continue
        fixed = _dct(command.get("fixed_arguments"))
        cid = str(fixed.get("city_id") or "")
        if not cid or cid in used or cid in seen:
            continue
        seen.add(cid)
        extras.append(_cmd("city_attack", str(command.get("command_id") or f"CMD_idle_strike_{cid}"), {
            "city_id": cid, "target_x": fixed.get("target_x"), "target_y": fixed.get("target_y"),
        }))
    return extras


def idle_units_by_type(snapshot: dict[str, Any], commands: list[dict[str, Any]] | None = None) -> dict[str, int]:
    taken = handled_unit_ids(commands or [])
    counts: dict[str, int] = {}
    for unit in _lst(snapshot.get("your_units")):
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("unit_id") or "")
        if uid in taken:
            continue
        if unit_role(unit) not in ROLE_DEFAULTS:
            continue
        if not (unit.get("needs_orders") or (_dct(unit.get("movement")).get("current") or 0) > 0):
            continue
        typ = str(unit.get("unit_type_id") or "UNIT")
        counts[typ] = counts.get(typ, 0) + 1
    return counts


def idle_prompt_line(snapshot: dict[str, Any]) -> str | None:
    counts = idle_units_by_type(snapshot)
    if not counts:
        return None
    bits = [f"{n} {typ}" for typ, n in sorted(counts.items())]
    return "IDLE: " + ", ".join(bits) + " — host default applied"


def apply_host_defaults(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    extras = idle_defaults(snapshot, commands)
    extras.extend(unused_city_strikes(snapshot, commands + extras))
    return extras
