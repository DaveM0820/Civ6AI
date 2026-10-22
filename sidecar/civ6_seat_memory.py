"""Per-seat memory: situation log, thought folder, plan, milestones, alerts.

The turn file ``memory/{game}_{player}.json`` remains what the next turn loads.
This module also writes a folder ``memory/{game}/{player}/`` (situation.jsonl,
thoughts.jsonl, plan.json) so a seat can be read the way a Civ V log was.
Unknown keys are kept by ``load_thought_memory``; anything not listed there
disappears on the next turn.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sidecar import pipeline_v2 as pipeline

SITUATION_CAP = 80
MILESTONE_CAP = 12
PROMISE_CAP = 20
ALERT_CAP = 24
EVENT_KEY_CAP = 200
# A seat at war, a city, or a military unit with nothing happening for this many turns.
LETHARGY_TURNS = 3
_ATTACK_KINDS = frozenset({"attack_target", "city_attack", "range_attack", "melee_attack"})
KEPT_KEYS = ("plan", "situation_log", "milestones", "promises", "alerts", "tracked", "dropped")

OBJECTIVE_ORDERS = {
    "attack": frozenset({"attack_target", "city_attack"}),
    "peace": frozenset({"execute_deal", "send_diplomatic_action"}),
    "improve": frozenset({"worker_improve"}),
    "settle": frozenset({"found_city"}),
    "research": frozenset({"set_research_tech", "set_research_civic"}),
    "defend": frozenset({"unit_posture_fortify", "attack_target", "city_attack", "queue_production"}),
    "build": frozenset({"queue_production", "set_build_priority", "purchase_item"}),
}

_PROMISE_RE = re.compile(r"\b(i will|i promise|i shall|i won't|i will not)\b", re.I)
_OBJECTIVE_RE = re.compile(
    r"^(attack|peace|improve|settle|research|defend|build)\b\s*(.*)$",
    re.I,
)
_BY_TURN_RE = re.compile(r"\bby\s+T?(\d+)\s*$", re.I)
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _turn(snapshot: dict) -> int:
    try:
        return int((snapshot.get("decision") or {}).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def _me(snapshot: dict) -> str:
    return str((snapshot.get("decision") or {}).get("player_id") or "")


def _name(snapshot: dict, player_id: str) -> str:
    try:
        return pipeline._player_chat_name(snapshot, player_id)
    except Exception:
        return player_id


def _append_event(memory: dict[str, Any], turn: int, key: str, text: str) -> None:
    tracked = memory.setdefault("tracked", {})
    if not isinstance(tracked, dict):
        tracked = {}
        memory["tracked"] = tracked
    seen = [str(item) for item in tracked.get("events") or [] if item]
    if key in seen:
        return
    seen.append(key)
    tracked["events"] = seen[-EVENT_KEY_CAP:]
    log = [row for row in memory.get("situation_log") or [] if isinstance(row, dict)]
    log.append({"turn": int(turn), "text": text[:240]})
    memory["situation_log"] = log[-SITUATION_CAP:]


def _forget_events(memory: dict[str, Any], prefix: str) -> None:
    tracked = memory.get("tracked")
    if not isinstance(tracked, dict):
        return
    tracked["events"] = [key for key in tracked.get("events") or [] if not str(key).startswith(prefix)]


def observe(snapshot: dict, memory: dict[str, Any]) -> dict[str, Any]:
    """Record wars, deals, and city losses, and fill blank opinion/history fields."""
    if not isinstance(memory, dict):
        memory = {}
    turn = _turn(snapshot)
    me = _me(snapshot)
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    diplo = civ6.get("diplomacy") if isinstance(civ6.get("diplomacy"), dict) else {}
    majors = [row for row in diplo.get("majors") or [] if isinstance(row, dict)]
    live_wars: set[str] = set()
    for major in majors:
        pid = str(major.get("player_id") or "")
        if not pid:
            continue
        name = _name(snapshot, pid)
        if major.get("at_war") is True:
            since = major.get("war_since_turn")
            since_text = f"T{since}" if isinstance(since, int) else f"T{turn}"
            live_wars.add(pid)
            _append_event(memory, turn, f"war|{pid}|{since_text}", f"War with {name} since {since_text}.")
        else:
            prior = [key for key in (memory.get("tracked") or {}).get("events") or [] if str(key).startswith(f"war|{pid}|")]
            if prior:
                _append_event(memory, turn, f"peace|{pid}|{turn}", f"Peace with {name} on T{turn}.")
                _forget_events(memory, f"war|{pid}|")
    _note_deals(snapshot, memory, turn, me)
    _note_city_losses(snapshot, memory, turn)
    _refresh_alerts(snapshot, memory, turn)
    _milestone(memory, turn)
    _fill_relations(snapshot, memory, turn, majors)
    return memory


def _note_deals(snapshot: dict, memory: dict[str, Any], turn: int, me: str) -> None:
    try:
        from sidecar import civ6_diplomacy as diplo
    except Exception:
        return
    if not snapshot.get("_session_dir"):
        return
    for deal in diplo.load_deals(snapshot):
        if me and me not in (deal.get("from"), deal.get("to")):
            continue
        other = deal.get("to") if deal.get("from") == me else deal.get("from")
        status = str(deal.get("status") or "")
        if status not in ("pending", "accepted", "rejected", "countered"):
            continue
        when = int(deal.get("done_turn") or deal.get("turn") or turn)
        key = f"deal|{status}|{deal.get('from')}|{deal.get('to')}|{deal.get('turn')}"
        _append_event(
            memory, when, key,
            f"Deal {status} with {_name(snapshot, str(other))} on T{when}.",
        )


def _note_city_losses(snapshot: dict, memory: dict[str, Any], turn: int) -> None:
    tracked = memory.setdefault("tracked", {})
    if not isinstance(tracked, dict):
        tracked = {}
        memory["tracked"] = tracked
    current: dict[str, str] = {}
    for city in snapshot.get("your_cities") or []:
        if isinstance(city, dict) and city.get("city_id"):
            current[str(city["city_id"])] = str(city.get("name") or city["city_id"])
    prev = tracked.get("cities")
    if isinstance(prev, dict):
        for cid, name in prev.items():
            if cid not in current:
                _append_event(memory, turn, f"lost|{cid}|{turn}", f"Lost {name} on T{turn}.")
    if current or isinstance(prev, dict):
        tracked["cities"] = current


def _refresh_alerts(snapshot: dict, memory: dict[str, Any], turn: int) -> None:
    current: dict[str, str] = {}
    economy = (snapshot.get("civ6") or {}).get("economy") if isinstance(snapshot.get("civ6"), dict) else {}
    if isinstance(economy, dict):
        for row in economy.get("cities") or []:
            if isinstance(row, dict) and isinstance(row.get("turns_to_starve"), int):
                name = str(row.get("name") or row.get("city_id") or "city")
                current[f"starve:{row.get('city_id')}"] = (
                    f"{name} is starving (loses a citizen in {row['turns_to_starve']} turns)"
                )
    plots = {}
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    for plot in known.get("plots") or []:
        if isinstance(plot, dict) and plot.get("plot_id"):
            plots[str(plot["plot_id"])] = plot
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        city_plot = str(city.get("plot_id") or "")
        cname = str(city.get("name") or city.get("city_id") or "city")
        for pid in city.get("worked_plot_ids") or []:
            pid = str(pid)
            if not pid or pid == city_plot:
                continue
            plot = plots.get(pid)
            if not isinstance(plot, dict) or "improvement_id" not in plot:
                continue
            if plot.get("improvement_id") or plot.get("water") or plot.get("peak"):
                continue
            current[f"unimproved:{pid}"] = f"{cname} works {pid} with no improvement"
    prior = [row for row in memory.get("alerts") or [] if isinstance(row, dict)]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in prior:
        key = str(row.get("key") or "")
        if key in current and key not in seen:
            out.append({"key": key, "text": current[key], "since_turn": row.get("since_turn", turn)})
            seen.add(key)
    for key, text in current.items():
        if key not in seen:
            out.append({"key": key, "text": text, "since_turn": turn})
    memory["alerts"] = out[:ALERT_CAP]


def _milestone(memory: dict[str, Any], turn: int) -> None:
    if turn <= 0 or turn % 10 != 0:
        return
    rows = [row for row in memory.get("milestones") or [] if isinstance(row, dict)]
    if any(int(row.get("turn") or -1) == turn for row in rows):
        return
    goal = str((memory.get("plan") or {}).get("goal") or "no victory goal yet")
    recent = [str(row.get("text") or "") for row in (memory.get("situation_log") or [])[-6:] if isinstance(row, dict)]
    text = f"T{turn} {goal}."
    if recent:
        text += " " + "; ".join(bit for bit in recent if bit)
    rows.append({"turn": turn, "text": text[:500]})
    memory["milestones"] = rows[-MILESTONE_CAP:]


def _fill_relations(snapshot: dict, memory: dict[str, Any], turn: int, majors: list[dict]) -> None:
    opinions = memory.get("player_opinions")
    histories = memory.get("player_histories")
    if not isinstance(opinions, dict):
        opinions = {}
        memory["player_opinions"] = opinions
    if not isinstance(histories, dict):
        histories = {}
        memory["player_histories"] = histories
    deals: list[dict] = []
    if snapshot.get("_session_dir"):
        try:
            from sidecar import civ6_diplomacy as diplo

            deals = diplo.load_deals(snapshot)
        except Exception:
            deals = []
    me = _me(snapshot)
    for major in majors:
        pid = str(major.get("player_id") or "")
        if not pid.startswith("PLAYER_"):
            continue
        if len(opinions) >= 16 and pid not in opinions:
            break
        name = _name(snapshot, pid)
        at_war = major.get("at_war") is True
        opinion = opinions.get(pid) if isinstance(opinions.get(pid), dict) else {}
        if not str(opinion.get("text") or "").strip():
            if at_war:
                text = f"At war with {name}."
            elif any(d.get("status") == "accepted" and {d.get("from"), d.get("to")} == {me, pid} for d in deals):
                text = f"We have traded with {name}."
            else:
                text = f"At peace with {name}."
            opinions[pid] = {"text": text[:300], "updated_turn": turn}
        history = histories.get(pid) if isinstance(histories.get(pid), dict) else {}
        if not str(history.get("text") or "").strip() and len(histories) < 16:
            bits = []
            if at_war:
                since = major.get("war_since_turn")
                bits.append(f"War with {name} since T{since}." if isinstance(since, int) else f"War with {name}.")
            else:
                bits.append(f"No war with {name} recorded.")
            for deal in deals:
                if {deal.get("from"), deal.get("to")} != {me, pid}:
                    continue
                bits.append(f"T{deal.get('done_turn') or deal.get('turn')} {deal.get('status')} deal.")
                if len(bits) >= 4:
                    break
            histories[pid] = {"text": " ".join(bits)[:300], "updated_turn": turn}


def apply_plan(memory: dict[str, Any], turn: int, update: dict[str, Any]) -> dict[str, Any]:
    plan = memory.get("plan") if isinstance(memory.get("plan"), dict) else {}
    objectives = [row for row in plan.get("objectives") or [] if isinstance(row, dict)]
    goal = update.get("goal")
    if isinstance(goal, str) and goal.strip():
        plan["goal"] = goal.strip()[:120]
    for raw in update.get("objectives") or []:
        parsed = _parse_objective(str(raw))
        if parsed is None:
            continue
        replaced = False
        for row in objectives:
            if row.get("kind") == parsed["kind"] and row.get("status") != "done" and row.get("text") == parsed["text"]:
                row.update(parsed)
                replaced = True
                break
        if not replaced:
            objectives.append(parsed)
    for raw in update.get("done") or []:
        kind = str(raw).strip().split()[0].lower() if str(raw).strip() else ""
        for row in objectives:
            if row.get("status") != "done" and (row.get("kind") == kind or kind and kind in str(row.get("text") or "").lower()):
                row["status"] = "done"
                break
    plan["objectives"] = objectives[-8:]
    plan["updated_turn"] = int(turn)
    memory["plan"] = plan
    return memory


def _parse_objective(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    match = _OBJECTIVE_RE.match(text)
    if not match:
        return {"kind": "build", "text": text[:160], "target_turn": None, "status": "active"}
    kind = match.group(1).lower()
    rest = match.group(2).strip()
    target = None
    by = _BY_TURN_RE.search(rest)
    if by:
        target = int(by.group(1))
        rest = rest[: by.start()].strip(" ,;-")
    return {"kind": kind, "text": (rest or text)[:160], "target_turn": target, "status": "active"}


def record_promises(memory: dict[str, Any], turn: int, texts: list[str]) -> dict[str, Any]:
    rows = [row for row in memory.get("promises") or [] if isinstance(row, dict)]
    have = {str(row.get("text") or "").strip().lower() for row in rows}
    for raw in texts:
        text = str(raw).strip()[:240]
        if not text or text.lower() in have:
            continue
        rows.append({"turn": int(turn), "text": text})
        have.add(text.lower())
        _append_event(memory, turn, f"promise|{turn}|{text.lower()[:80]}", f"Promised: {text}")
    memory["promises"] = rows[-PROMISE_CAP:]
    return memory


def extract_promises(messages: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        if text and _PROMISE_RE.search(text) and text not in out:
            out.append(text[:240])
    return out


def _is_war_command(command: dict[str, Any]) -> bool:
    kind = str(command.get("kind") or "")
    if kind in ("attack_target", "city_attack"):
        return True
    if kind == "send_diplomatic_action":
        action = str((command.get("arguments") or {}).get("action_id") or "")
        return "WAR" in action.upper()
    return False


def _is_peace_command(command: dict[str, Any]) -> bool:
    if str(command.get("kind") or "") != "execute_deal":
        return False
    try:
        return int((command.get("arguments") or {}).get("mode") or 0) & 1 == 1
    except (TypeError, ValueError):
        return False


def contradiction_notes(promises: list[str], commands: list[dict[str, Any]]) -> list[str]:
    """Chat that says peace while the orders attack, or the reverse."""
    notes: list[str] = []
    war = any(_is_war_command(c) for c in commands if isinstance(c, dict))
    peace = any(_is_peace_command(c) for c in commands if isinstance(c, dict))
    for raw in promises:
        low = raw.lower()
        peaceful = any(token in low for token in (
            "peace", "won't attack", "will not attack", "i won't attack", "no war", "not attack",
        ))
        aggressive = any(token in low for token in ("attack", "invade", "declare war")) and not peaceful
        if peaceful and war:
            notes.append(f"chat promised peace but orders attack or declare war: {raw[:160]}")
        elif aggressive and peace:
            notes.append(f"chat promised an attack but orders include peace: {raw[:160]}")
    return notes


def _attack_turn(item: dict[str, Any]) -> int | None:
    kind = str(item.get("order_kind") or "")
    summary = str(item.get("summary") or "").lower()
    if kind not in _ATTACK_KINDS and "attack" not in summary and "battle" not in summary:
        return None
    try:
        return int(item.get("turn"))
    except (TypeError, ValueError):
        return None


def _last_attack_turn(snapshot: dict, memory: dict[str, Any] | None) -> int | None:
    last: int | None = None
    tracked = memory.get("tracked") if isinstance(memory, dict) else None
    if isinstance(tracked, dict) and isinstance(tracked.get("last_attack_turn"), int):
        last = int(tracked["last_attack_turn"])
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    for item in history.get("command_results") or []:
        if not isinstance(item, dict):
            continue
        turn = _attack_turn(item)
        if turn is not None and (last is None or turn > last):
            last = turn
    stamped = snapshot.get("_lethargy_last_attack")
    if isinstance(stamped, int) and not isinstance(stamped, bool) and (last is None or stamped > last):
        last = stamped
    return last


def _idle_city_names(snapshot: dict) -> list[str]:
    names: list[str] = []
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        production = city.get("production") if isinstance(city.get("production"), dict) else {}
        item = production.get("item_id")
        if item and str(item).upper() not in ("NONE", "NULL"):
            continue
        names.append(str(city.get("name") or city.get("city_id") or "city"))
    return names


def _idle_army_bits(snapshot: dict) -> list[str]:
    from sidecar.civ6_wire import _is_civilian

    economy = (snapshot.get("civ6") or {}).get("economy") if isinstance(snapshot.get("civ6"), dict) else {}
    tracking = economy.get("tracking") if isinstance(economy, dict) else {}
    idle = tracking.get("idle_turns") if isinstance(tracking, dict) else {}
    idle = idle if isinstance(idle, dict) else {}
    bits: list[str] = []
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict) or _is_civilian(unit):
            continue
        uid = str(unit.get("unit_id") or "")
        n = idle.get(uid)
        if isinstance(n, bool) or not isinstance(n, int) or n < LETHARGY_TURNS:
            continue
        label = str(unit.get("unit_type_id") or uid).replace("UNIT_", "") or uid
        bits.append(f"{label} idle {n} turns")
    return bits


def lethargy_parts(snapshot: dict, memory: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """(log key, sentence) for a quiet war, an empty city, or an idle army."""
    turn = _turn(snapshot)
    parts: list[tuple[str, str]] = []
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    diplo = civ6.get("diplomacy") if isinstance(civ6.get("diplomacy"), dict) else {}
    last_attack = _last_attack_turn(snapshot, memory)
    attack_quiet = last_attack is None or turn - last_attack >= LETHARGY_TURNS
    names: list[str] = []
    if attack_quiet:
        for major in diplo.get("majors") or []:
            if not isinstance(major, dict) or major.get("at_war") is not True:
                continue
            pid = str(major.get("player_id") or "")
            since = major.get("war_since_turn")
            start: int | None
            try:
                start = int(since) if since is not None and not isinstance(since, bool) else None
            except (TypeError, ValueError):
                start = None
            if start is None and isinstance(memory, dict):
                seen = (memory.get("tracked") or {}).get("wars") if isinstance(memory.get("tracked"), dict) else None
                if isinstance(seen, dict) and isinstance(seen.get(pid), int):
                    start = int(seen[pid])
            if start is None or turn - start < LETHARGY_TURNS:
                continue
            names.append(_name(snapshot, pid) if pid else "that civilization")
    if names:
        who = ", ".join(names[:4])
        more = f" (+{len(names) - 4} more)" if len(names) > 4 else ""
        parts.append((
            "lethargy|war",
            f"At war with {who}{more} and no attack or battle for {LETHARGY_TURNS}+ turns.",
        ))
    cities = _idle_city_names(snapshot)
    if cities:
        shown = ", ".join(cities[:4])
        more = f" (+{len(cities) - 4} more)" if len(cities) > 4 else ""
        parts.append((
            "lethargy|cities",
            f"Idle cities with nothing in production: {shown}{more}.",
        ))
    armies = _idle_army_bits(snapshot)
    if armies:
        shown = ", ".join(armies[:4])
        more = f" (+{len(armies) - 4} more)" if len(armies) > 4 else ""
        parts.append((
            "lethargy|armies",
            f"Idle armies have not moved: {shown}{more}.",
        ))
    return parts


def lethargy_line(snapshot: dict, memory: dict[str, Any] | None = None) -> str | None:
    """One prominent alert, or the line note_lethargy already stamped on this snapshot."""
    stamped = snapshot.get("_lethargy_alert")
    if isinstance(stamped, str) and stamped.strip():
        return stamped
    parts = lethargy_parts(snapshot, memory)
    if not parts:
        return None
    return "LETHARGY: " + " ".join(text for _, text in parts)


def note_lethargy(snapshot: dict, memory: dict[str, Any]) -> dict[str, Any]:
    """Record a quiet war, idle cities, and idle armies on the situation log.

    Runs after economy idle tracking, which is what the army streak reads.
    """
    if not isinstance(memory, dict):
        memory = {}
    turn = _turn(snapshot)
    tracked = memory.setdefault("tracked", {})
    if not isinstance(tracked, dict):
        tracked = {}
        memory["tracked"] = tracked
    last = _last_attack_turn(snapshot, memory)
    if isinstance(last, int):
        tracked["last_attack_turn"] = last
        snapshot["_lethargy_last_attack"] = last
    wars = tracked.get("wars")
    if not isinstance(wars, dict):
        wars = {}
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    diplo = civ6.get("diplomacy") if isinstance(civ6.get("diplomacy"), dict) else {}
    live: set[str] = set()
    for major in diplo.get("majors") or []:
        if isinstance(major, dict) and major.get("at_war") is True and major.get("player_id"):
            pid = str(major["player_id"])
            live.add(pid)
            if pid not in wars:
                since = major.get("war_since_turn")
                try:
                    wars[pid] = int(since) if since is not None and not isinstance(since, bool) else turn
                except (TypeError, ValueError):
                    wars[pid] = turn
    for pid in list(wars):
        if pid not in live:
            wars.pop(pid, None)
    tracked["wars"] = wars
    parts = lethargy_parts(snapshot, memory)
    active = {key for key, _ in parts}
    for key in list(tracked.get("events") or []):
        if str(key).startswith("lethargy|") and str(key) not in active:
            _forget_events(memory, str(key))
    for key, text in parts:
        _append_event(memory, turn, key, "LETHARGY: " + text)
    snapshot["_lethargy_alert"] = ("LETHARGY: " + " ".join(text for _, text in parts)) if parts else None
    return memory


def compact(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": memory.get("plan") if isinstance(memory.get("plan"), dict) else {},
        "promises": [row for row in (memory.get("promises") or []) if isinstance(row, dict)][-6:],
        "alerts": [row for row in (memory.get("alerts") or []) if isinstance(row, dict)][:8],
        "milestones": [row for row in (memory.get("milestones") or []) if isinstance(row, dict)][-1:],
        "situation_log": [row for row in (memory.get("situation_log") or []) if isinstance(row, dict)][-4:],
    }


def prompt_lines(memory: dict[str, Any]) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    plan = memory.get("plan") if isinstance(memory.get("plan"), dict) else {}
    if str(plan.get("goal") or "").strip():
        lines.append(("plan.goal", str(plan["goal"])[:120]))
    index = 0
    for obj in plan.get("objectives") or []:
        if not isinstance(obj, dict) or obj.get("status") == "done":
            continue
        bit = str(obj.get("kind") or "objective")
        if str(obj.get("text") or "").strip():
            bit += " " + str(obj["text"]).strip()
        if isinstance(obj.get("target_turn"), int):
            bit += f" by T{obj['target_turn']}"
        bit += f" ({obj.get('status') or 'active'})"
        lines.append((f"plan.objective.{index}", bit[:200]))
        index += 1
    for row in memory.get("promises") or []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            lines.append((f"promise.T{int(row.get('turn') or 0)}", str(row["text"])[:180]))
    for row in memory.get("alerts") or []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            lines.append((f"alert.open.{index}", str(row["text"])[:180]))
            index += 1
    for row in memory.get("milestones") or []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            lines.append((f"milestone.T{int(row.get('turn') or 0)}", str(row["text"])[:240]))
    for row in memory.get("situation_log") or []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            lines.append((f"situation.T{int(row.get('turn') or 0)}", str(row["text"])[:180]))
    return lines[:16]


def active_objectives(memory: dict[str, Any] | None) -> list[dict[str, Any]]:
    plan = memory.get("plan") if isinstance(memory, dict) else None
    if not isinstance(plan, dict):
        return []
    out = []
    for row in plan.get("objectives") or []:
        if isinstance(row, dict) and str(row.get("status") or "active") == "active" and row.get("kind") in OBJECTIVE_ORDERS:
            out.append(row)
    return out


def memory_folder(root: Path, game_uuid: str, player_id: str) -> Path:
    game = _SAFE.sub("_", str(game_uuid))[:80] or "game"
    player = _SAFE.sub("_", str(player_id))[:40] or "player"
    return root / game / player


def write_folder(thought_path: Path, memory: dict[str, Any], game_uuid: str, player_id: str) -> None:
    folder = memory_folder(thought_path.parent, game_uuid, player_id)
    folder.mkdir(parents=True, exist_ok=True)
    _write_jsonl(folder / "situation.jsonl", memory.get("situation_log"))
    _write_jsonl(folder / "thoughts.jsonl", memory.get("thoughts"))
    plan = memory.get("plan") if isinstance(memory.get("plan"), dict) else {}
    (folder / "plan.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Any) -> None:
    lines = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
