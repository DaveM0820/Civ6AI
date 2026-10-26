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
from typing import Any, Callable

from sidecar.civ6_common import dct as _dct
from sidecar.civ6_common import lst as _lst
from sidecar.civ6_common import me as _me
from sidecar.civ6_common import plot_xy
from sidecar.civ6_common import turn as _turn
from sidecar.civ6_common import unit_by_id as _unit_by_id
from sidecar import settings

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
    mine = stack_class(unit)
    for other_id in holders:
        if other_id == uid:
            continue
        other = _unit_by_id(snapshot, other_id)
        if other is None or stack_class(other) == mine:
            return "occupied"
    return None


# Civ VI stacking: one unit per formation class per tile. A civilian (settler,
# builder, trader) shares a tile with one combat unit and one support unit.
_CIVILIAN_TAGS = ("SETTLER", "BUILDER", "TRADER", "MISSIONARY", "APOSTLE", "INQUISITOR",
                  "GURU", "ARCHAEOLOGIST", "GREAT_", "NATURALIST", "SPY", "MILITARY_ENGINEER")
_SUPPORT_TAGS = ("BATTERING_RAM", "SIEGE_TOWER", "MEDIC", "SUPPLY_CONVOY", "OBSERVATION_BALLOON",
                 "DRONE", "ANTIAIR_GUN", "MOBILE_SAM")


def stack_class(unit: dict[str, Any]) -> str:
    """The unit's stacking class: civilian, support, land, naval or air."""
    cls = str(unit.get("unit_class_id") or unit.get("formation_class") or "").upper()
    for tag, name in (("CIVILIAN", "civilian"), ("SUPPORT", "support"), ("NAVAL", "naval"),
                      ("AIR", "air"), ("LAND_COMBAT", "land")):
        if cls.startswith("FORMATION_CLASS_") and tag in cls:
            return name
    typ = str(unit.get("unit_type_id") or "").upper()
    if int(unit.get("build_charges") or 0) > 0 or any(tag in typ for tag in _CIVILIAN_TAGS):
        return "civilian"
    if any(tag in typ for tag in _SUPPORT_TAGS):
        return "support"
    domain = str(unit.get("domain_id") or "DOMAIN_LAND")
    return {"DOMAIN_SEA": "naval", "DOMAIN_AIR": "air"}.get(domain, "land")


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


REASON_TEXT = {
    "impassable": "impassable",
    "occupied": "occupied",
    "no_path": "no_path",
    "outside_borders": "builders can only move onto your own tiles; that destination is outside your borders",
    "peace_not_at_war": "peace needs a war",
    "illegal_dof": "no open friendship offer",
    "government_locked": "a government can only be changed on a turn when a civic completed",
    "city_strike_unavailable": "city_strike_unavailable",
    "self_tile_move": "the unit was already on that tile, so it stayed there (Skip)",
    "off_map": "that tile is off the map",
    "improve_tile_not_offered": "no Improve is offered on that tile; use a listed Improve tile",
    "found_city_not_offered": "FoundCity is not offered for this settler here",
    "not_a_legal_site": "not a legal city site (too close to a city, or not land); use a listed settle site",
}


# --- Offer pipeline -------------------------------------------------------
# legality is the only writer of snapshot["legal_commands"]. Other modules
# provide pure offer filters (snapshot, offers) -> offers, registered here by
# name, or add offers through add_offer(). Paths resolve lazily to avoid
# import cycles.
OfferFilter = Callable[[dict[str, Any], list[Any]], list[Any]]

OFFER_FILTERS: dict[str, str] = {
    "adapter_dedupe": "sidecar.civ6_adapter:dedupe_offers",
    "combat_runnable": "sidecar.civ6_combat_wire:runnable_attack_offers",
    "repeat_failures": "sidecar.civ6_apply_results:repeat_failure_offers",
    "no_city_sites": "sidecar.civ6_wire:settler_offers_without_sites",
}


def offer_filter(name: str) -> OfferFilter:
    import importlib

    module, _, attr = OFFER_FILTERS[name].partition(":")
    return getattr(importlib.import_module(module), attr)


def offers(snapshot: dict[str, Any]) -> list[Any] | None:
    legal = snapshot.get("legal_commands")
    return legal if isinstance(legal, list) else None


def apply_offer_filter(snapshot: dict[str, Any], name: str) -> int:
    """Run one registered filter over the offer list. Returns offers dropped."""
    legal = offers(snapshot)
    if legal is None:
        return 0
    kept = offer_filter(name)(snapshot, legal)
    snapshot["legal_commands"] = kept
    return len(legal) - len(kept)


def add_offer(snapshot: dict[str, Any], command: dict[str, Any]) -> str | None:
    """Append one offer unless its command_id is already offered."""
    legal = snapshot.setdefault("legal_commands", [])
    if not isinstance(legal, list):
        return None
    cmd_id = command["command_id"]
    if not any(isinstance(c, dict) and c.get("command_id") == cmd_id for c in legal):
        legal.append(command)
    return str(cmd_id)


def reason_text(code: str) -> str:
    text = str(code or "")
    if text.startswith("no_") and text.endswith("_at_war"):
        return f"no {text[3:-7]} while at war"
    return REASON_TEXT.get(text, text or "rejected")


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


def _move_rejection_text(snapshot: dict[str, Any], args: dict[str, Any], problem: str) -> str | None:
    """Plain 'You tried to move <unit> to tile (x,y). Tile (x,y) is ...' line."""
    try:
        x, y = int(args.get("target_x")), int(args.get("target_y"))
    except (TypeError, ValueError):
        return None
    from sidecar import civ6_apply_results, pipeline_v2 as pipeline

    uid = str(args.get("unit_id") or "")
    units = [u for u in snapshot.get("your_units") or [] if isinstance(u, dict)]
    name = pipeline._build_unit_wire_id_map(units).get(uid, uid)
    return civ6_apply_results.move_failure_text(snapshot, name, x, y, problem, "")


def _legality_rule(snapshot: dict[str, Any], ctx: dict[str, Any]):
    def check(command: dict[str, Any]):
        problem = order_problem(snapshot, command)
        if not problem:
            return None
        line = f"Rejected last turn: {order_label(command)} - {reason_text(problem)}"
        args = _dct(command.get("arguments") or command.get("fixed_arguments"))
        if str(command.get("kind") or "") == "move_unit":
            line = _move_rejection_text(snapshot, args, problem) or line
        row = {"order": order_label(command), "reason": problem, "turn": _turn(snapshot)}
        if args.get("unit_id"):
            row["unit_id"] = str(args.get("unit_id"))
        return line, row
    return check


# Order verdicts: stages of named rules. A rule factory (snapshot, ctx) returns
# check(command) -> None | (line, rejection_row | None). Within a stage the first
# rule that fires drops the order; stages run in order over the survivors.
ORDER_RULES: tuple[tuple[str, ...], ...] = (
    ("legality",),
    ("attack_target", "repeat_failure", "duplicate_destination"),
)
_RULE_PATHS = {
    "attack_target": "sidecar.civ6_apply_results:attack_target_rule",
    "repeat_failure": "sidecar.civ6_apply_results:repeat_failure_rule",
    "duplicate_destination": "sidecar.civ6_apply_results:duplicate_destination_rule",
}


def _order_rule(name: str):
    if name == "legality":
        return _legality_rule
    import importlib

    module, _, attr = _RULE_PATHS[name].partition(":")
    return getattr(importlib.import_module(module), attr)


def filter_orders(snapshot: dict[str, Any], commands: list[dict[str, Any]],
                  stages: tuple[tuple[str, ...], ...] | None = None,
                  ctx: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The only order-verdict function. Default stages: legality only."""
    ctx = {} if ctx is None else ctx
    kept = [c for c in commands if isinstance(c, dict)]
    rejected: list[str] = []
    rows: list[dict[str, Any]] = []
    for stage in stages or ORDER_RULES[:1]:
        checks = [_order_rule(name)(snapshot, ctx) for name in stage]
        survivors: list[dict[str, Any]] = []
        for command in kept:
            verdict = next((v for v in (check(command) for check in checks) if v), None)
            if verdict is None:
                survivors.append(command)
                continue
            rejected.append(verdict[0])
            if verdict[1]:
                rows.append(verdict[1])
        kept = survivors
    remember_rejections(snapshot, rows)
    return kept, rejected


def reject(snapshot: dict[str, Any], label: str, code: str) -> str:
    """Record one model order the sidecar will not run. Returns the prompt line."""
    remember_rejections(snapshot, [{"order": label, "reason": code, "turn": _turn(snapshot)}])
    return f"Rejected last turn: {label} - {reason_text(code)}"


def build_offer_set(snapshot: dict[str, Any]) -> None:
    """The single entry point that turns the game's offers into this turn's offer set."""
    from sidecar import civ6_apply_results, civ6_priorities, civ6_wire

    civ6_priorities.inject_legal_commands(snapshot)
    civ6_wire.prune_settlers_without_sites(snapshot)
    try:
        civ6_apply_results.suppress_failed_offers(snapshot)
    except Exception:  # never block a seat-turn on feedback rows
        pass


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


# What to do instead when the same order keeps being rejected for the same reason.
REPEAT_ADVICE = {
    "occupied": "move the unit that stands there first, or pick another listed destination",
    "impassable": "pick a land tile from the unit's listed options",
    "no_path": "pick a destination on the same landmass",
    "outside_borders": "pick a tile inside your borders",
}
REPEAT_ADVICE_DEFAULT = "order something else for this unit"


def _rejection_turns(rows: list[dict[str, Any]]) -> dict[tuple[str, str], set[int]]:
    seen: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        try:
            when = int(row.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        key = (str(row.get("order") or "order"), str(row.get("reason") or "rejected"))
        seen.setdefault(key, set()).add(when)
    return seen


def legal_moves(snapshot: dict[str, Any], unit_id: str, limit: int = 6) -> list[tuple[int, int]]:
    """Tiles this unit may move to now: offered move targets first, then passable
    tiles within its remaining moves (one step per move point, at least one)."""
    unit = _unit_by_id(snapshot, str(unit_id))
    if unit is None:
        return []
    start = plot_xy(unit)
    out: list[tuple[int, int]] = []
    for cmd in _lst(snapshot.get("legal_commands")):
        if not isinstance(cmd, dict) or cmd.get("kind") != "move_unit":
            continue
        args = _dct(cmd.get("fixed_arguments"))
        if str(args.get("unit_id") or "") != str(unit_id):
            continue
        try:
            xy = int(args.get("target_x")), int(args.get("target_y"))
        except (TypeError, ValueError):
            continue
        if xy != start and xy not in out:
            out.append(xy)
    if start is None:
        return out[:limit]
    try:
        steps = int(_dct(unit.get("movement")).get("current") or 0)
    except (TypeError, ValueError):
        steps = 0
    steps = max(1, min(3, steps))
    plots = known_plots(snapshot)
    frontier, seen = [start], {start}
    for _ in range(steps):
        nxt: list[tuple[int, int]] = []
        for x, y in frontier:
            for xy in hex_neighbors(x, y):
                if xy in seen or xy not in plots:
                    continue
                seen.add(xy)
                if tile_passable(snapshot, unit, xy[0], xy[1]) is None:
                    nxt.append(xy)
                    if xy not in out:
                        out.append(xy)
        frontier = nxt
    return out[:limit]


def legal_moves_text(snapshot: dict[str, Any], unit_id: str) -> str:
    """'legal moves for warrior_1 now: (17,23), (16,24)' or '' when none are known."""
    moves = legal_moves(snapshot, unit_id)
    if not moves:
        return ""
    from sidecar import pipeline_v2 as pipeline

    units = [u for u in _lst(snapshot.get("your_units")) if isinstance(u, dict)]
    name = pipeline._build_unit_wire_id_map(units).get(str(unit_id), str(unit_id))
    return f"legal moves for {name} now: " + ", ".join(f"({x},{y})" for x, y in moves)


def rejection_lines(snapshot: dict[str, Any]) -> list[str]:
    turn = _turn(snapshot)
    lines: list[str] = []
    rows = [r for r in _lst(load_state(snapshot).get("rejections")) if isinstance(r, dict)]
    turns_of = _rejection_turns(rows)
    for row in rows:
        try:
            when = int(row.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if when != turn - 1 and when != turn:
            continue
        order = str(row.get("order") or "order")
        code = str(row.get("reason") or "rejected")
        line = f"Rejected last turn: {order} - {reason_text(code)}"
        repeats = len(turns_of.get((order, code), ()))
        if repeats >= 2:
            line += (f" (rejected on {repeats} turns for the same reason; stop ordering it: "
                     f"{REPEAT_ADVICE.get(code, REPEAT_ADVICE_DEFAULT)})")
        if repeats >= settings.get_int("CIV6AI_REPEAT_LEGAL_MOVES_AFTER") and row.get("unit_id"):
            hint = legal_moves_text(snapshot, str(row.get("unit_id")))
            if hint:
                line += f"; {hint}"
        if line in lines:
            continue
        lines.append(line)
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


def handled_unit_ids(commands: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for command in commands:
        args = _dct(command.get("arguments") or command.get("fixed_arguments"))
        uid = str(args.get("unit_id") or "")
        if uid:
            out.add(uid)
    return out


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
