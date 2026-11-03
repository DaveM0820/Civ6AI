"""Research / civic targets: the seat names a far tech or civic, the sidecar walks the path.

The prerequisite tree is a static copy of the game's gameplay DB (assets/civ6/research_tree.json,
Base + Rise and Fall + Gathering Storm). Nothing here calls the game: the chosen step goes out
as the ordinary synced set_research_tech / set_research_civic order, so it stays lockstep-safe.
An explicit model research/civic order in the same reply always wins.
"""
from __future__ import annotations

import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

TREE_PATH = Path(__file__).resolve().parent / "assets" / "civ6" / "research_tree.json"

KINDS = {
    "tech": {"tree": "techs", "prefix": "TECH_", "command": "set_research_tech", "field": "tech_id",
             "plan": "research_target", "label": "Research target", "cmd_prefix": "CMD_research_"},
    "civic": {"tree": "civics", "prefix": "CIVIC_", "command": "set_research_civic", "field": "civic_id",
              "plan": "civic_target", "label": "Civic target", "cmd_prefix": "CMD_civic_"},
}
CLEAR_WORDS = {"", "NONE", "CLEAR", "NULL", "OFF", "NO"}


def _dct(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _lst(v: Any) -> list:
    return v if isinstance(v, list) else []


@lru_cache(maxsize=1)
def tree() -> dict:
    try:
        return json.loads(TREE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"eras": [], "techs": {}, "civics": {}}


def nice(type_id: str) -> str:
    for p in ("TECH_", "CIVIC_"):
        if type_id.startswith(p):
            type_id = type_id[len(p):]
    return type_id.replace("_", " ").title()


def resolve(kind: str, value: Any) -> str | None:
    """Model text -> TECH_* / CIVIC_* id, '' to clear, None if unknown."""
    spec = KINDS[kind]
    raw = re.sub(r"[\s\-]+", "_", str(value or "").strip().strip('"').strip()).upper()
    if raw in CLEAR_WORDS:
        return ""
    ids = tree().get(spec["tree"], {})
    for cand in (raw, spec["prefix"] + raw):
        if cand in ids:
            return cand
    return None


# ---------------------------------------------------------------- snapshot facts

def _gov_block(snapshot: dict, kind: str) -> dict:
    from sidecar.civ6_governance import governance

    return _dct(governance(snapshot).get(KINDS[kind]["tree"]))


def known(snapshot: dict, kind: str) -> set[str]:
    emp = _dct(snapshot.get("your_empire"))
    if kind == "tech":
        return {str(t) for t in _lst(_dct(emp.get("research")).get("known_tech_ids")) if t}
    out = set()
    for row in _lst(emp.get("civics")):
        if isinstance(row, dict) and row.get("id"):
            out.add(str(row["id"]))
        elif isinstance(row, str):
            out.add(row)
    return out


def current(snapshot: dict, kind: str) -> str | None:
    cur = _gov_block(snapshot, kind).get("current")
    return str(cur) if cur else None


def option_turns(snapshot: dict, kind: str) -> dict[str, int]:
    out = {}
    for o in _lst(_gov_block(snapshot, kind).get("options")):
        if isinstance(o, dict) and o.get("id") and isinstance(o.get("turns"), (int, float)) and o["turns"] >= 0:
            out[str(o["id"])] = int(o["turns"])
    return out


def researchable(snapshot: dict, kind: str) -> set[str]:
    ids = {str(o.get("id")) for o in _lst(_gov_block(snapshot, kind).get("options")) if isinstance(o, dict) and o.get("id")}
    return ids


def legal_choices(snapshot: dict, kind: str) -> set[str]:
    spec = KINDS[kind]
    out = set()
    for c in _lst(snapshot.get("legal_commands")):
        if isinstance(c, dict) and c.get("kind") == spec["command"]:
            v = _dct(c.get("fixed_arguments")).get(spec["field"])
            if v:
                out.add(str(v))
    return out


def _turn_scale(snapshot: dict, kind: str) -> float | None:
    """Turns per base-cost point, from the options the game already timed."""
    nodes = tree().get(KINDS[kind]["tree"], {})
    ratios = sorted(t / nodes[i]["cost"] for i, t in option_turns(snapshot, kind).items()
                    if i in nodes and nodes[i].get("cost") and t > 0)
    return ratios[len(ratios) // 2] if ratios else None


def est_turns(snapshot: dict, kind: str, node_id: str) -> int | None:
    timed = option_turns(snapshot, kind)
    if node_id in timed:
        return timed[node_id]
    if node_id == current(snapshot, kind):
        left = _gov_block(snapshot, kind).get("turns_left")
        if isinstance(left, (int, float)) and left >= 0:
            return int(left)
    scale = _turn_scale(snapshot, kind)
    cost = tree().get(KINDS[kind]["tree"], {}).get(node_id, {}).get("cost")
    if scale is None or not cost:
        return None
    return max(1, math.ceil(cost * scale))


# ---------------------------------------------------------------- path

def path(snapshot: dict, kind: str, target: str) -> list[str]:
    """Unknown prerequisites of target (and target), in a researchable order, cheapest-ready first."""
    nodes = tree().get(KINDS[kind]["tree"], {})
    if target not in nodes:
        return []
    have = known(snapshot, kind)
    need: set[str] = set()
    stack = [target]
    while stack:
        n = stack.pop()
        if n in need or n in have or n not in nodes:
            continue
        need.add(n)
        stack.extend(nodes[n].get("prereqs") or [])
    order: list[str] = []
    done = set(have)
    while need:
        ready = [n for n in need if all(p in done or p not in nodes for p in nodes[n].get("prereqs") or [])]
        if not ready:  # cycle guard
            ready = list(need)
        ready.sort(key=lambda n: (nodes[n].get("cost") or 0, n))
        pick = ready[0]
        order.append(pick)
        done.add(pick)
        need.discard(pick)
    return order


def target_of(snapshot: dict, kind: str) -> str | None:
    plan = _dct(_dct(snapshot.get("_seat_memory")).get("plan"))
    t = plan.get(KINDS[kind]["plan"])
    return str(t) if isinstance(t, str) and t else None


def next_step(snapshot: dict, kind: str) -> tuple[str | None, list[str]]:
    """(step to order now, backups) from the target path, limited to legal choices."""
    target = target_of(snapshot, kind)
    if not target:
        return None, []
    legal = legal_choices(snapshot, kind)
    steps = [s for s in path(snapshot, kind, target) if s in legal]
    if not steps:
        return None, []
    nodes = tree().get(KINDS[kind]["tree"], {})
    timed = option_turns(snapshot, kind)
    steps.sort(key=lambda s: (timed.get(s, 10**6), nodes.get(s, {}).get("cost") or 0, s))
    return steps[0], steps[1:3]


# ---------------------------------------------------------------- memory

def observe(snapshot: dict, memory: dict) -> dict:
    """Clear a target once it is known; leave a one-turn 'reached' note."""
    if not isinstance(memory, dict):
        return memory
    plan = memory.get("plan") if isinstance(memory.get("plan"), dict) else None
    if plan is None:
        return memory
    turn = _dct(snapshot.get("decision")).get("turn")
    for kind, spec in KINDS.items():
        key = spec["plan"]
        t = plan.get(key)
        if isinstance(t, str) and t and t in known(snapshot, kind):
            plan.pop(key, None)
            plan[key + "_reached"] = {"id": t, "turn": turn}
            _log(snapshot, kind, t, "-", "reached")
        reached = plan.get(key + "_reached")
        if isinstance(reached, dict) and isinstance(turn, int) and isinstance(reached.get("turn"), int) \
                and turn - reached["turn"] > 1:
            plan.pop(key + "_reached", None)
    return memory


def apply_update(plan: dict, update: dict, turn: int) -> None:
    for spec in KINDS.values():
        key = spec["plan"]
        if key not in update:
            continue
        val = update.get(key)
        if val == "":
            plan.pop(key, None)
        elif isinstance(val, str) and val:
            plan[key] = val
            plan[key + "_turn"] = int(turn)
            plan.pop(key + "_reached", None)


# ---------------------------------------------------------------- orders

def _is_kind(cmd: dict, kind: str) -> bool:
    spec = KINDS[kind]
    return cmd.get("kind") == spec["command"] or str(cmd.get("command_id") or "").startswith(spec["cmd_prefix"])


def _player(snapshot: dict) -> str:
    pid = str(_dct(snapshot.get("decision")).get("player_id") or "")
    m = re.search(r"(\d+)$", pid)
    return m.group(1) if m else pid


def _log(snapshot: dict, kind: str, target: str, step: str, source: str) -> None:
    print(f"research|target|player={_player(snapshot)}|kind={kind}|target={target}|step={step}|source={source}",
          file=sys.stderr)


def auto_commands(snapshot: dict, commands: list[dict]) -> list[dict]:
    """At a choice point with no model research/civic order, order the next step toward the target."""
    out = []
    for kind, spec in KINDS.items():
        target = target_of(snapshot, kind)
        if not target:
            continue
        explicit = next((c for c in commands if isinstance(c, dict) and _is_kind(c, kind)), None)
        if explicit is not None:
            chosen = _dct(explicit.get("arguments")).get(spec["field"]) or \
                str(explicit.get("command_id") or "")[len(spec["cmd_prefix"]):]
            _log(snapshot, kind, target, str(chosen), "model")
            continue
        step, _ = next_step(snapshot, kind)
        if step is None:
            continue
        out.append({"command_id": spec["cmd_prefix"] + step, "kind": spec["command"],
                    "arguments": {spec["field"]: step}, "source": "research_target"})
        _log(snapshot, kind, target, step, "auto")
    return out


def path_backups(snapshot: dict, kind: str, chosen: str) -> list[str]:
    """Backups for an order: other legal on-path steps first."""
    target = target_of(snapshot, kind)
    if not target:
        return []
    legal = legal_choices(snapshot, kind)
    return [s for s in path(snapshot, kind, target) if s in legal and s != chosen][:2]


# ---------------------------------------------------------------- prompt

def _status(snapshot: dict, kind: str, node: str, have: set[str], cur: str | None, opts: set[str]) -> str:
    if node in have:
        return "known"
    if node == cur:
        t = est_turns(snapshot, kind, node)
        return f"researching {t}t" if t is not None else "researching"
    if node in opts:
        t = est_turns(snapshot, kind, node)
        return f"researchable {t}t" if t is not None else "researchable"
    return "locked"


def target_lines(snapshot: dict) -> list[str]:
    lines = []
    plan = _dct(_dct(snapshot.get("_seat_memory")).get("plan"))
    for kind, spec in KINDS.items():
        reached = plan.get(spec["plan"] + "_reached")
        if isinstance(reached, dict) and reached.get("id"):
            lines.append(f"{spec['label']} {nice(str(reached['id']))} reached — target cleared; "
                         f"set plan.{spec['plan']} for the next one.")
        target = target_of(snapshot, kind)
        if not target:
            continue
        steps = path(snapshot, kind, target)
        if not steps:
            continue
        cur = current(snapshot, kind)
        if cur in steps:  # in progress first
            steps = [cur] + [s for s in steps if s != cur]
        parts, total = [], 0
        for s in steps:
            t = est_turns(snapshot, kind, s)
            total += t or 0
            parts.append(f"{nice(s)} ({t}t)" if t is not None else nice(s))
        lines.append(f"{spec['label']}: {nice(target)} — path: {' → '.join(parts)}; ~{total} turns "
                     "(auto-ordered when you give no research order; your explicit order always wins).")
    return lines


def tree_lines(snapshot: dict, kind: str) -> list[str]:
    """Compact tree for the earliest unfinished era and the next one."""
    spec = KINDS[kind]
    nodes = tree().get(spec["tree"], {})
    eras = tree().get("eras", [])
    if not nodes or not eras:
        return []
    have = known(snapshot, kind)
    open_eras = [e for e in eras if any(n["era"] == e and i not in have for i, n in nodes.items())]
    if not open_eras:
        return []
    start = eras.index(open_eras[0])
    show = eras[start:start + 2]
    cur = current(snapshot, kind)
    opts = researchable(snapshot, kind)
    label = "Tech tree" if kind == "tech" else "Civic tree"
    out = [f"{label} ({' + '.join(nice(e.replace('ERA_', '')) for e in show)}; '<-' = prerequisites):"]
    for era in show:
        ids = sorted((i for i, n in nodes.items() if n["era"] == era),
                     key=lambda i: (nodes[i].get("cost") or 0, i))
        done = [nice(i) for i in ids if i in have]
        out.append(f"  {nice(era.replace('ERA_', ''))}" + (f" — known: {', '.join(done)}" if done else ""))
        for i in ids:
            if i in have:
                continue
            line = f"    {nice(i)} [{_status(snapshot, kind, i, have, cur, opts)}]"
            pre = nodes[i].get("prereqs") or []
            if pre:
                line += " <- " + ", ".join(f"{nice(p)} [{_status(snapshot, kind, p, have, cur, opts)}]" for p in pre)
            out.append(line)
    return out


def prompt_lines(snapshot: dict) -> list[str]:
    try:
        return target_lines(snapshot) + tree_lines(snapshot, "tech") + tree_lines(snapshot, "civic")
    except Exception as error:  # never block a seat-turn on the tree view
        print(f"research tree skipped: {error}", file=sys.stderr)
        return []
