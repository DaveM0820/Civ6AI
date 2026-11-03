"""'Build next' for the game's AI seats (set_build_next).

The model names one item for its seat. The mod switches on that item's
one-entry favoured list (Data/Civ6Ai_BuildNext.sql, weight 1000) through a
synced game property, so the engine AI starts it at the next empty queue in a
city of its own choice, with vanilla costs and modifiers. The pick clears when
a city starts it, or after BUILD_NEXT_TURNS turns. Several cities emptying
their queues the same turn can all start it (accepted tradeoff).
"""
from __future__ import annotations

from typing import Any

COMMAND_KIND = "set_build_next"
REPLY_KEY = "build.next"
REPLY_ALIASES = ("build.next", "build_next", "buildnext", "legal.build.next")
CLEAR = "NONE"
OPTIONS_CAP = 40


def offers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in snapshot.get("legal_commands") or []
            if isinstance(c, dict) and c.get("kind") == COMMAND_KIND
            and isinstance(c.get("fixed_arguments"), dict)]


def supported(snapshot: dict[str, Any]) -> bool:
    return bool(offers(snapshot))


def current_pick(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    block = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    pick = block.get("build_next")
    return pick if isinstance(pick, dict) and pick.get("item_id") else None


def _label(item: str) -> str:
    for prefix in ("UNIT_", "BUILDING_", "DISTRICT_"):
        if item.startswith(prefix):
            return item[len(prefix):].replace("_", " ").title()
    return item


def _option_text(fixed: dict[str, Any]) -> str:
    item = str(fixed.get("item_id") or "")
    turns = fixed.get("turns")
    city = fixed.get("city_name")
    if isinstance(turns, int) and turns > 0:
        where = f" in {city}" if city else ""
        return f"{item} ({turns} turn{'s' if turns != 1 else ''}{where})"
    return item


def prompt_lines(snapshot: dict[str, Any]) -> list[str]:
    rows = [c["fixed_arguments"] for c in offers(snapshot)
            if str(c["fixed_arguments"].get("item_id") or "") != CLEAR]
    if not rows:
        return []
    pick = current_pick(snapshot)
    lines = ["=== BUILD NEXT ==="]
    lines.append(
        "You can name one item your empire builds next. The game starts it in one of your cities the next time "
        "a city's queue empties (the game picks the city, at normal cost); it does not interrupt a build in "
        "progress. If several cities empty their queues the same turn, more than one may start it. The pick "
        "ends when a city starts it, or after a few turns.")
    if pick:
        exp = pick.get("expires_turn")
        lines.append(f"Current pick: {pick.get('item_id')} (set T{pick.get('set_turn', '?')}"
                     + (f", lapses after T{exp} if no city has started it" if isinstance(exp, int) else "") + ").")
    else:
        lines.append("Current pick: none (your production preset decides).")
    shown = rows[:OPTIONS_CAP]
    lines.append("Buildable now (fastest city's turn estimate): " + " | ".join(_option_text(r) for r in shown)
                 + (f" (+{len(rows) - len(shown)} more)" if len(rows) > len(shown) else ""))
    lines.append(f'To set it, add the optional key "{REPLY_KEY}" with one item id, e.g. "{REPLY_KEY}": '
                 f'"{shown[0].get("item_id")}". "{REPLY_KEY}": "{CLEAR}" clears it. Omit the key to keep it.')
    return lines


def is_reply_key(key: str) -> bool:
    return key.strip().lower() in REPLY_ALIASES


def bind_reply(snapshot: dict[str, Any], key: str, value: Any) -> tuple[list[str], list[str]]:
    """(command ids, problems) for a build.next reply value."""
    raw = str(value or "").strip()
    if not raw:
        return [], []
    want = raw.split("(", 1)[0].strip().upper().replace(" ", "_")
    if want in ("NONE", "CLEAR", "OFF"):
        want = CLEAR
    candidates = [want] if want == CLEAR else [want, "UNIT_" + want, "BUILDING_" + want, "DISTRICT_" + want]
    for command in offers(snapshot):
        item = str(command["fixed_arguments"].get("item_id") or "").upper()
        if item in candidates and isinstance(command.get("command_id"), str):
            return [command["command_id"]], []
    return [], [f"{key}:{raw} is not buildable now; pick one listed under BUILD NEXT"]


def buildable(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    block = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    rows = block.get("buildable")
    return [r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("item_id"), str)]


def inject_offers(snapshot: dict[str, Any]) -> int:
    """One set_build_next offer per buildable item the mod listed (AI seats only), plus NONE."""
    rows = buildable(snapshot)
    if not rows:
        return 0
    from sidecar import civ6_legality as legality
    from sidecar.civ6_adapter import _enrich_runtime_legal_command

    added = 0
    for row in rows + [{"item_id": CLEAR}]:
        item = str(row["item_id"])
        fixed: dict[str, Any] = {"item_id": item}
        if isinstance(row.get("turns"), int) and row["turns"] > 0:
            fixed["turns"] = row["turns"]
        if row.get("city_name"):
            fixed["city_name"] = str(row["city_name"])
        legality.add_offer(snapshot, _enrich_runtime_legal_command({
            "command_id": f"CMD_NEXT_{item}",
            "kind": COMMAND_KIND,
            "description": f"build next {item}",
            "fixed_arguments": fixed,
        }))
        added += 1
    return added
