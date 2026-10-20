"""War and peace orders from civ6.diplomacy facts.

The mod writes can_declare_war / can_make_peace on each met major and city-state
(Civ6Ai_Snapshot._BuildDiplomacy), using the same TeamDiplomacy:CanDeclareWarOn /
CanMakePeaceWith calls as the leader and city-state screens. This module lists
those as optional reply keys and turns a matching reply into a legal command
the order channel already knows how to pack.

War is one-sided (Diplomacy:DeclareWarOn). Trades, peace and friendship are
two-turn deals: a seat offers with deal.<Leader>, the offer waits in the
session's deals.json, and the receiver must answer deal.<From>.respond as a
required row. An accept becomes one execute_deal order on the synced channel
(Gov.Deal moves gold/resources and applies peace or friendship).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sidecar import pipeline_v2 as pipeline

WAR_ACTIONS = frozenset({
    "DECLARE_WAR", "DECLARE_FORMAL_WAR", "FORMAL_WAR", "WAR",
    "DECLARE_SURPRISE_WAR", "SURPRISE_WAR",
})
SURPRISE_ACTIONS = frozenset({"DECLARE_SURPRISE_WAR", "SURPRISE_WAR"})


def _lst(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dct(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _civ6(snapshot: dict) -> dict:
    block = snapshot.get("civ6") if isinstance(snapshot, dict) else None
    return block if isinstance(block, dict) else {}


def diplomacy(snapshot: dict) -> dict:
    block = _civ6(snapshot).get("diplomacy")
    return block if isinstance(block, dict) else {}


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def _action_id(value: Any) -> str | None:
    token = _norm(value).replace("DECLARE", "DECLARE_")
    compact = _norm(value)
    aliases = {
        "DECLAREWAR": "DECLARE_WAR",
        "WAR": "DECLARE_WAR",
        "FORMALWAR": "DECLARE_WAR",
        "DECLAREFORMALWAR": "DECLARE_WAR",
        "SURPRISEWAR": "DECLARE_SURPRISE_WAR",
        "DECLARESURPRISEWAR": "DECLARE_SURPRISE_WAR",
    }
    raw = str(value or "").strip().upper().replace(" ", "_")
    if raw in WAR_ACTIONS:
        return "DECLARE_SURPRISE_WAR" if raw in SURPRISE_ACTIONS else "DECLARE_WAR"
    mapped = aliases.get(compact)
    if mapped:
        return mapped
    if token in WAR_ACTIONS:
        return "DECLARE_SURPRISE_WAR" if token in SURPRISE_ACTIONS else "DECLARE_WAR"
    return None


def _targets(snapshot: dict) -> list[dict[str, Any]]:
    """Met majors and city-states with a display name and war/peace flags."""
    known = {
        str(row.get("player_id")): row
        for row in snapshot.get("known_players", []) or []
        if isinstance(row, dict) and row.get("player_id")
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    diplo = diplomacy(snapshot)
    for row in _lst(diplo.get("majors")) + _lst(diplo.get("city_states")):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("player_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        rival = known.get(pid) if known.get(pid) else {}
        name = pipeline._player_chat_name(snapshot, pid)
        if name == pid:
            name = str(row.get("name") or rival.get("leader_name") or pid)
        out.append({
            "player_id": pid,
            "name": name,
            "can_declare_war": row.get("can_declare_war") is True,
            "can_make_peace": row.get("can_make_peace") is True,
        })
    return out



DEALS_NAME = "deals.json"
GPT_TURNS = 10
OFFER_TTL = 3
_ITEM = re.compile(r"^\s*(\d+)\s+([A-Za-z_]+)\s*$")


def _me(snapshot: dict) -> str:
    return str(_dct(snapshot.get("decision")).get("player_id") or "")


def _turn(snapshot: dict) -> int:
    try:
        return int(_dct(snapshot.get("decision")).get("turn"))
    except (TypeError, ValueError):
        return 0


def _deals_path(snapshot: dict) -> Path | None:
    raw = snapshot.get("_session_dir") if isinstance(snapshot, dict) else None
    if not raw:
        return None
    root = Path(raw)
    return (root.parent if root.name.startswith("PLAYER_") else root) / DEALS_NAME


def load_deals(snapshot: dict) -> list[dict[str, Any]]:
    path = _deals_path(snapshot)
    try:
        rows = json.loads(path.read_text(encoding="utf-8")) if path else []
    except (OSError, ValueError):
        rows = []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save(snapshot: dict, deals: list[dict[str, Any]]) -> None:
    path = _deals_path(snapshot)
    if path is None:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(deals[-200:], indent=1), encoding="utf-8")
    os.replace(tmp, path)


def parse_items(text: str) -> list[dict[str, Any]] | str:
    """'100 gold, 3 gpt, 1 RESOURCE_IRON' / 'peace' / 'friendship' -> items, or an error."""
    items: list[dict[str, Any]] = []
    for part in re.split(r",|\band\b|\+", str(text or "")):
        word = part.strip().lower()
        if not word or word in ("nothing", "none"):
            continue
        if word in ("peace", "friendship"):
            items.append({"kind": word})
            continue
        m = _ITEM.match(part)
        if not m or int(m.group(1)) <= 0:
            return f"'{part.strip()}' is not '<n> gold', '<n> gpt' or '<n> RESOURCE_X'"
        n, name = int(m.group(1)), m.group(2).upper()
        if name == "GOLD":
            items.append({"gold": n})
        elif name in ("GPT", "GOLD_PER_TURN"):
            items.append({"gpt": n})
        else:
            items.append({"res": name if name.startswith("RESOURCE_") else "RESOURCE_" + name, "n": n})
    return items


def _stock_problem(snapshot: dict, items: list[dict[str, Any]]) -> str | None:
    """None when this seat holds everything it would give."""
    stock = _dct(diplomacy(snapshot).get("your_trade"))
    have = {str(r.get("resource_id")): int(r.get("amount") or 0)
            for r in _lst(stock.get("luxuries")) + _lst(stock.get("strategics")) if isinstance(r, dict)}
    gold = sum(i.get("gold", 0) for i in items)
    gpt = sum(i.get("gpt", 0) for i in items)
    if gold > int(stock.get("gold") or 0):
        return f"you have only {int(stock.get('gold') or 0)} gold"
    if gpt > max(0, int(stock.get("gold_per_turn") or 0)):
        return f"you make only {int(stock.get('gold_per_turn') or 0)} gold per turn"
    for i in items:
        if "res" in i and i["n"] > have.get(i["res"], 0):
            return f"you have {have.get(i['res'], 0)} {i['res']}"
    return None


def _items_text(items: list[dict[str, Any]]) -> str:
    bits = []
    for i in items:
        if "kind" in i:
            bits.append(i["kind"])
        elif "gold" in i:
            bits.append(f"{i['gold']} gold")
        elif "gpt" in i:
            bits.append(f"{i['gpt']} gpt for {GPT_TURNS} turns")
        else:
            bits.append(f"{i['n']} {i['res']}")
    return ", ".join(bits) or "nothing"


def _open_offers_to_me(snapshot: dict) -> list[dict[str, Any]]:
    me, turn = _me(snapshot), _turn(snapshot)
    return [d for d in load_deals(snapshot) if d.get("status") == "pending" and d.get("to") == me
            and turn - int(d.get("turn") or 0) <= OFFER_TTL]


def has_orders(snapshot: dict) -> bool:
    return bool(_targets(snapshot)) or bool(_open_offers_to_me(snapshot))


def required_rows(snapshot: dict) -> list[tuple[str, str]]:
    """Every open offer to this seat must be answered this turn."""
    return [(f"deal.{pipeline._player_chat_name(snapshot, d['from'])}.respond",
             f"ACCEPT | REJECT  # they give {_items_text(d.get('give', []))}; you give {_items_text(d.get('want', []))}")
            for d in _open_offers_to_me(snapshot)]


def optional_key_hints(snapshot: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    names = []
    for target in _targets(snapshot):
        if target["can_declare_war"]:
            out.append((f"legal.diplomacy.{target['name']}", "DECLARE_WAR"))
        if target["player_id"].startswith("PLAYER_") and target in _majors(snapshot):
            names.append(target["name"])
    if names:
        out.append(("deal.<Leader>", "give <n> gold, <n> gpt, <n> RESOURCE_X for <items> | peace | friendship  "
                    f"(answered next turn; Leader = {' | '.join(names)})"))
    return out


def _majors(snapshot: dict) -> list[dict[str, Any]]:
    ids = {str(r.get("player_id")) for r in _lst(diplomacy(snapshot).get("majors")) if isinstance(r, dict)}
    return [t for t in _targets(snapshot) if t["player_id"] in ids]


def trade_lines(snapshot: dict, rival_id: str) -> str:
    """'rival.<Name>.trades' value: deals in force with that rival (pending, running gpt, done in GPT_TURNS)."""
    me, turn = _me(snapshot), _turn(snapshot)
    bits = []
    for d in load_deals(snapshot):
        if {d.get("from"), d.get("to")} != {me, rival_id}:
            continue
        mine = d.get("from") == me
        give, want = (d.get("give", []), d.get("want", [])) if mine else (d.get("want", []), d.get("give", []))
        text = f"you give {_items_text(give)} for {_items_text(want)}"
        if d.get("status") == "pending" and turn - int(d.get("turn") or 0) <= OFFER_TTL:
            bits.append(f"T{d.get('turn')} offer {'sent' if mine else 'received'}: {text}")
        elif d.get("status") == "accepted" and turn - int(d.get("done_turn") or 0) <= GPT_TURNS:
            bits.append(f"T{d.get('done_turn')} accepted: {text}")
        elif d.get("status") == "rejected" and turn - int(d.get("done_turn") or 0) <= 1:
            bits.append(f"T{d.get('done_turn')} rejected: {text}")
    return " | ".join(bits) or "none"


def is_reply_key(key: str) -> bool:
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    return low.startswith("diplomacy.") or low.startswith("deal.")


def _match_target(snapshot: dict, key: str) -> dict[str, Any] | None:
    low = key[len("legal."):] if key.lower().startswith("legal.") else key
    tail = low.split(".", 1)[-1]
    if tail.lower().endswith(".respond"):
        tail = tail[: -len(".respond")]
    wanted = pipeline._resolve_chat_recipient(tail, snapshot)
    for target in _targets(snapshot):
        if wanted == target["player_id"] or _norm(tail) in (_norm(target["name"]), _norm(target["player_id"])):
            return target
    return None


def _add_command(snapshot: dict, kind: str, fixed: dict, description: str) -> str:
    from sidecar.civ6_adapter import _enrich_runtime_legal_command

    legal = snapshot.setdefault("legal_commands", [])
    base = "CMD_DIPLO_" + kind.upper()
    have = {c.get("command_id") for c in legal if isinstance(c, dict)}
    n = 1
    while f"{base}_{n}" in have:
        n += 1
    cid = f"{base}_{n}"
    legal.append(_enrich_runtime_legal_command({
        "command_id": cid, "kind": kind, "description": description[:240], "fixed_arguments": fixed,
    }))
    return cid


def _deal_command(snapshot: dict, other: str, give: list, want: list, name: str) -> str | None:
    """One execute_deal order from this seat's side: + = this seat gives."""
    res: dict[str, int] = {}
    for i in give:
        if "res" in i:
            res[i["res"]] = res.get(i["res"], 0) + i["n"]
    for i in want:
        if "res" in i:
            res[i["res"]] = res.get(i["res"], 0) - i["n"]
    legs = [(r, n) for r, n in res.items() if n]
    if len(legs) > 2:
        return None
    legs += [("", 0)] * (2 - len(legs))
    kinds = {i.get("kind") for i in give + want}
    fixed = {
        "target_player_id": other,
        "gold": sum(i.get("gold", 0) for i in give) - sum(i.get("gold", 0) for i in want),
        "res1": legs[0][0], "amt1": legs[0][1], "res2": legs[1][0], "amt2": legs[1][1],
        "mode": 1 if "peace" in kinds else 2 if "friendship" in kinds else 0,
    }
    return _add_command(snapshot, "execute_deal", fixed, f"deal with {name}: give {_items_text(give)} for {_items_text(want)}")


def bind_reply(snapshot: dict, key: str, value: Any) -> tuple[list[str], list[str]]:
    """Legal command ids for one diplomacy reply key, plus unresolved notes."""
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    target = _match_target(snapshot, key)
    if target is None:
        return [], [f"{key}={value}: not a met rival"]
    pid, name, text = target["player_id"], target["name"], str(value or "").strip()
    if low.startswith("deal.") and low.endswith(".respond"):
        deals = load_deals(snapshot)
        offer = next((d for d in reversed(deals) if d in _open_offers_to_me(snapshot) and d.get("from") == pid), None)
        if offer is None:
            return [], [f"{key}: no open offer from {name}"]
        answer = text.upper()
        if answer not in ("ACCEPT", "REJECT", "YES", "NO"):
            return [], [f"{key}={value}: use ACCEPT or REJECT"]
        offer["done_turn"] = _turn(snapshot)
        ids: list[str] = []
        if answer in ("ACCEPT", "YES"):
            problem = _stock_problem(snapshot, offer.get("want", []))
            cid = None if problem else _deal_command(snapshot, pid, offer.get("want", []), offer.get("give", []), name)
            if cid is None:
                offer["status"] = "rejected"
                _save(snapshot, deals)
                return [], [f"{key}: cannot accept, {problem or 'more than 2 resource kinds'}; offer rejected"]
            ids.append(cid)
            offer["status"] = "accepted"
            offer["gpt"] = [{"from": offer["from"] if side == "give" else offer["to"], "amount": i["gpt"], "left": GPT_TURNS}
                            for side in ("give", "want") for i in offer.get(side, []) if "gpt" in i]
        else:
            offer["status"] = "rejected"
        _save(snapshot, deals)
        return ids, []
    if low.startswith("deal."):
        if text.lower() in ("", "none", "skip", "no"):
            return [], []
        give_text, sep, want_text = re.sub(r"^\s*give\s+", "", text, flags=re.I).partition(" for ")
        if not sep:
            give_text, want_text = "", give_text
        give, want = parse_items(give_text), parse_items(want_text)
        for parsed in (give, want):
            if isinstance(parsed, str):
                return [], [f"{key}={value}: {parsed}"]
        kinds = {i.get("kind") for i in give + want}
        if "peace" in kinds and not target["can_make_peace"]:
            return [], [f"{key}: you are not at war with {name}"]
        problem = _stock_problem(snapshot, give)
        if problem:
            return [], [f"{key}={value}: {problem}"]
        deals = [d for d in load_deals(snapshot)
                 if not (d.get("status") == "pending" and d.get("from") == _me(snapshot) and d.get("to") == pid)]
        deals.append({"from": _me(snapshot), "to": pid, "give": give, "want": want,
                      "turn": _turn(snapshot), "status": "pending"})
        _save(snapshot, deals)
        return [], []
    action = _action_id(value)
    if action is None:
        return [], [f"{key}={value}: only DECLARE_WAR is available here; trades, peace and friendship use deal.{name}"]
    if not target["can_declare_war"]:
        return [], [f"{key}: you cannot declare war on {name} now"]
    return [_add_command(
        snapshot, "send_diplomatic_action",
        {"target_player_id": pid, "action_id": action},
        f"declare war on {name}",
    )], []


def instalment_ids(snapshot: dict) -> list[str]:
    """This turn's gold-per-turn payments this seat owes under accepted deals."""
    me, turn = _me(snapshot), _turn(snapshot)
    deals = load_deals(snapshot)
    ids: list[str] = []
    for d in deals:
        for leg in d.get("gpt", []) if d.get("status") == "accepted" else []:
            if leg.get("from") != me or leg.get("left", 0) <= 0 or leg.get("paid_turn") == turn:
                continue
            other = d["to"] if d["from"] == me else d["from"]
            ids.append(_add_command(snapshot, "execute_deal",
                                    {"target_player_id": other, "gold": leg["amount"], "res1": "", "amt1": 0,
                                     "res2": "", "amt2": 0, "mode": 0}, f"{leg['amount']} gpt to {other}"))
            leg["left"] -= 1
            leg["paid_turn"] = turn
    if ids:
        _save(snapshot, deals)
    return ids


def success_text(kind: str, fixed: dict) -> str | None:
    who = str(fixed.get("target_player_id") or "")
    if kind == "send_diplomatic_action":
        return f"ok - war declared on {who}"
    if kind == "execute_deal":
        return f"ok - deal with {who} done"
    return None


ORDER_LABELS = {
    "send_diplomatic_action": ("diplomacy", "action_id"),
    "execute_deal": ("deal", "target_player_id"),
}
