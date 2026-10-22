"""War and peace orders from civ6.diplomacy facts.

The mod writes can_declare_war / can_make_peace on each met major and city-state
(Civ6Ai_Snapshot._BuildDiplomacy), using the same TeamDiplomacy:CanDeclareWarOn /
CanMakePeaceWith calls as the leader and city-state screens. This module lists
those as optional reply keys and turns a matching reply into a legal command
the order channel already knows how to pack.

War is one-sided (Diplomacy:DeclareWarOn). Trades, peace and friendship are
two-turn deals: a seat offers with deal.<Leader>, the offer waits in the
session's deals.json, and the receiver must answer deal.<From>.respond as a
required row. An accept becomes execute_deal orders on the synced channel
(Gov.Deal moves gold/resources and applies peace or friendship). Every
resource in the offer is sent; the packet carries two resource legs, so
further resources are further orders, not a reason to drop the deal.
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
            "at_war": row.get("at_war") is True,
            "can_declare_war": row.get("can_declare_war") is True,
            "can_make_peace": row.get("can_make_peace") is True,
        })
    return out



DEALS_NAME = "deals.json"
RELATIONS_NAME = "relations.json"
PEACE_WORDS = frozenset({"peace", "peace_treaty", "peacetreaty", "make_peace", "makepace"})
GPT_TURNS = 10
OFFER_TTL = 3
# Pact -> (Gov.Deal bit, civic/tech this seat needs). Applied both ways; peace needs war, the rest peace.
PACTS = {
    "peace": (1, None), "friendship": (2, None), "alliance": (4, "CIVIC_DIPLOMATIC_SERVICE"),
    "open_borders": (8, "CIVIC_EARLY_EMPIRE"), "embassy": (16, "TECH_WRITING"), "delegation": (32, None),
}
_ITEM = re.compile(r"^\s*(\d+)\s+([A-Za-z_]+)\s*$")
_ITEM_REV = re.compile(r"^\s*([A-Za-z_]+)\s*[:x]\s*(\d+)\s*$")  # 'tobacco:2'
_LABEL = re.compile(r"^\s*pacts?\b[^:]*:\s*", re.I)  # 'pacts (both ways): open_borders' -> 'open_borders'


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
    for part in re.split(r",|;|\||\band\b|\+", str(text or "")):
        part = _LABEL.sub("", part)
        word = part.strip().lower().replace(" ", "_")
        if not word or word in ("nothing", "none"):
            continue
        if word in PEACE_WORDS or word in PACTS:
            kind = "peace" if word in PEACE_WORDS else word
            if {"kind": kind} not in items:
                items.append({"kind": kind})
            continue
        m, rev = _ITEM.match(part), _ITEM_REV.match(part)
        if rev:
            m = None
        if (not m and not rev) or int((m or rev).group(1 if m else 2)) <= 0:
            return f"'{part.strip()}' is not '<n> gold', '<n> gpt', '<n> RESOURCE_X' or a pact"
        n, name = (int(m.group(1)), m.group(2).upper()) if m else (int(rev.group(2)), rev.group(1).upper())
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


STRATEGIC_TECH = {"RESOURCE_HORSES": "TECH_ANIMAL_HUSBANDRY", "RESOURCE_IRON": "TECH_BRONZE_WORKING",
                  "RESOURCE_NITER": "TECH_MILITARY_ENGINEERING", "RESOURCE_COAL": "TECH_INDUSTRIALIZATION",
                  "RESOURCE_OIL": "TECH_REFINING", "RESOURCE_ALUMINUM": "TECH_RADIO",
                  "RESOURCE_URANIUM": "TECH_COMBUSTION"}


def _usable_problem(snapshot: dict, items: list[dict[str, Any]]) -> str | None:
    """A strategic you would receive but cannot use yet (its reveal tech is unknown)."""
    known = {str(t) for t in _lst(_dct(_dct(snapshot.get("your_empire")).get("research")).get("known_tech_ids"))}
    if not known:
        return None
    for i in items:
        tech = STRATEGIC_TECH.get(str(i.get("res") or ""))
        if tech and tech not in known:
            return f"{i['res']} is useless to you before {tech}"
    return None


def _pact_problem(snapshot: dict, pid: str, kinds: set) -> str | None:
    """None when this seat may offer every pact in kinds to pid (the other side is checked in Gov.Deal)."""
    major = next((m for m in _lst(diplomacy(snapshot).get("majors")) if isinstance(m, dict)
                  and str(m.get("player_id")) == pid), {})
    empire = _dct(snapshot.get("your_empire"))
    known = {str(c.get("id")) for c in _lst(empire.get("civics")) if isinstance(c, dict) and c.get("key") == "known"}
    known |= {str(t) for t in _lst(_dct(empire.get("research")).get("known_tech_ids"))}
    for kind in sorted(kinds):
        if kind not in PACTS:
            continue
        if (kind == "peace") != bool(major.get("at_war")):
            return "peace needs a war" if kind == "peace" else f"no {kind} while at war"
        need = PACTS[kind][1]
        if need and need not in known:
            return f"{kind} needs {need}"
        if kind == "alliance" and not major.get("declared_friendship"):
            return "alliance needs declared friendship first"
        if major.get({"friendship": "declared_friendship", "alliance": "alliance", "open_borders": "open_borders"}.get(kind, "_")):
            return f"you already have {kind}"
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
        if target["at_war"] or target["can_make_peace"]:
            out.append((f"legal.diplomacy.{target['name']}", "PEACE_TREATY"))
        elif target["can_declare_war"]:
            out.append((f"legal.diplomacy.{target['name']}", "DECLARE_WAR"))
        if target["player_id"].startswith("PLAYER_") and target in _majors(snapshot):
            names.append(target["name"])
    if names:
        out.append(("deal.<Leader>", "give <items> for <items>  (any number of items: <n> gold, <n> gpt, "
                    "<n> RESOURCE_X, or a pact that binds both sides: peace, friendship, alliance, "
                    "open_borders, embassy, delegation; "
                    f"answered next turn; Leader = {' | '.join(names)})"))
        out.append(("cmd", "CMD_propose_* or CMD_accept_* copied from a DIPLOMACY deal-status line"))
    diplo = diplomacy(snapshot)
    if int(diplo.get("envoys_to_give") or 0) > 0:
        for row in _lst(diplo.get("city_states")):
            if isinstance(row, dict) and row.get("name"):
                out.append((f"envoy.{row['name']}", "1"))
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
    return (low.startswith("diplomacy.") or low.startswith("deal.") or low.startswith("envoy.")
            or low == "cmd" or low.startswith("cmd."))


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


def _deal_commands(snapshot: dict, other: str, give: list, want: list, name: str) -> list[str]:
    """execute_deal orders from this seat's side: + = this seat gives.

    The synced packet has two resource fields, which is a transport width,
    not a limit on the deal. Every resource kind is sent; gold and pact mode
    ride on the first order only.
    """
    res: dict[str, int] = {}
    for i in give:
        if "res" in i:
            res[i["res"]] = res.get(i["res"], 0) + i["n"]
    for i in want:
        if "res" in i:
            res[i["res"]] = res.get(i["res"], 0) - i["n"]
    legs = [(r, n) for r, n in res.items() if n]
    chunks = [legs[i:i + 2] for i in range(0, len(legs), 2)] or [[]]
    kinds = {i.get("kind") for i in give + want}
    gold = sum(i.get("gold", 0) for i in give) - sum(i.get("gold", 0) for i in want)
    mode = sum(PACTS[k][0] for k in kinds if k in PACTS)
    ids: list[str] = []
    for index, chunk in enumerate(chunks):
        padded = list(chunk) + [("", 0)] * (2 - len(chunk))
        fixed = {
            "target_player_id": other,
            "gold": gold if index == 0 else 0,
            "res1": padded[0][0], "amt1": padded[0][1], "res2": padded[1][0], "amt2": padded[1][1],
            "mode": mode if index == 0 else 0,
        }
        ids.append(_add_command(
            snapshot, "execute_deal", fixed,
            f"deal with {name}: give {_items_text(give)} for {_items_text(want)}",
        ))
    return ids


# Civ5 catalog kinds this seat can actually apply (Gov.Deal pact bits).
# RESEARCH_AGREEMENT and DEFENSIVE_PACT are in the Civ5 catalog and have no Civ6 setter.
_CATALOG = (("EMBASSY", "embassy"), ("OPEN_BORDERS", "open_borders"), ("DOF", "friendship"), ("PEACE", "peace"))
_PROPOSE_RE = re.compile(r"^(?:CMD_propose_)?PROPOSAL_([A-Z_]+)_PLAYER_(\d+)$")
_ANSWER_RE = re.compile(r"^CMD_(accept|reject)_PLAYER_(\d+)_T(\d+)$", re.I)


def _player_num(pid: str) -> str:
    match = re.search(r"(\d+)$", str(pid or ""))
    return match.group(1) if match else ""


def _civ5_items(items: list) -> str:
    parts = []
    for i in items or []:
        if not isinstance(i, dict):
            continue
        if "kind" in i:
            parts.append(str(i["kind"]))
        elif "gold" in i:
            parts.append(f"gold({i['gold']})")
        elif "gpt" in i:
            parts.append(f"gold_per_turn({i['gpt']})")
        elif "res" in i:
            parts.append(f"resources:{i['res']}({i['n']})")
    return " | ".join(parts) if parts else "none"


def _usable_mark(snapshot: dict, res_id: str) -> str:
    if res_id not in STRATEGIC_TECH:
        return ""
    problem = _usable_problem(snapshot, [{"res": res_id, "n": 1}])
    if problem:
        return f" usable=no ({STRATEGIC_TECH[res_id]})"
    return " usable=yes"


def _bind_envoy(snapshot: dict, key: str, text: str) -> tuple[list[str], list[str]]:
    if text.lower() in ("", "0", "none", "skip", "no"):
        return [], []
    diplo = diplomacy(snapshot)
    if int(diplo.get("envoys_to_give") or 0) < 1:
        return [], [f"{key}: you have no envoys to send"]
    tail = key.split(".", 1)[-1]
    row = None
    for cs in _lst(diplo.get("city_states")):
        if not isinstance(cs, dict):
            continue
        if _norm(tail) in (_norm(cs.get("name")), _norm(cs.get("player_id"))):
            row = cs
            break
    if row is None:
        return [], [f"{key}: not a met city-state"]
    pid = str(row.get("player_id"))
    return [_add_command(snapshot, "send_envoy", {"target_player_id": pid}, f"send an envoy to {row.get('name')}")], []


def _bind_civ5_command(snapshot: dict, text: str) -> tuple[list[str], list[str]]:
    """cmd = CMD_propose_PROPOSAL_* | CMD_accept_* | CMD_reject_* (Civ5 deal reply)."""
    legal = {c.get("command_id") for c in snapshot.get("legal_commands") or [] if isinstance(c, dict)}
    if text in legal and text.startswith("CMD_"):
        return [text], []
    proposed = _PROPOSE_RE.match(text)
    if proposed:
        kind = dict(_CATALOG).get(proposed.group(1))
        if kind is None:
            return [], [f"cmd={text}: that proposal is not a Civ6 deal"]
        pid = f"PLAYER_{proposed.group(2)}"
        return bind_reply(snapshot, f"deal.{pid}", kind)
    answer = _ANSWER_RE.match(text)
    if answer:
        verb, pid, turn = answer.group(1).upper(), f"PLAYER_{answer.group(2)}", int(answer.group(3))
        deals = load_deals(snapshot)
        offer = next((d for d in reversed(deals) if d.get("status") == "pending" and d.get("from") == pid
                      and int(d.get("turn") or 0) == turn and d.get("to") == _me(snapshot)), None)
        if offer is None:
            return [], [f"cmd={text}: no open offer"]
        name = pipeline._player_chat_name(snapshot, pid)
        return bind_reply(snapshot, f"deal.{name}.respond", "ACCEPT" if verb == "ACCEPT" else "REJECT")
    return [], [f"cmd={text}: use a propose_cmd, accept_cmd, or reject_cmd from the deal-status lines"]


def city_state_lines(snapshot: dict) -> list[str]:
    diplo = diplomacy(snapshot)
    rows = [r for r in _lst(diplo.get("city_states")) if isinstance(r, dict)]
    if not rows:
        return []
    lines = ["# == City-states =="]
    have = diplo.get("envoys_to_give")
    if isinstance(have, int):
        lines.append(pipeline._wire_line("diplomacy.envoys_to_give", have))
    for row in rows:
        name = str(row.get("name") or row.get("player_id"))
        bits = [
            f"type={row.get('city_state_type') or '?'}",
            f"your_envoys={row.get('your_envoys') if row.get('your_envoys') is not None else 0}",
            f"suzerain={row.get('suzerain_id') or 'none'}",
            f"suzerain_envoys={row['suzerain_envoys'] if row.get('suzerain_envoys') is not None else 'unknown'}",
            f"at_war={'yes' if row.get('at_war') else 'no'}",
        ]
        if int(diplo.get("envoys_to_give") or 0) > 0:
            bits.append(f"envoy_cmd=envoy.{name}")
        lines.append(pipeline._wire_line(f"diplomacy.citystate.{name}", " ".join(bits)))
    return lines


def _relations_path(snapshot: dict) -> Path | None:
    path = _deals_path(snapshot)
    return path.with_name(RELATIONS_NAME) if path is not None else None


def _load_relations(snapshot: dict) -> dict[str, Any]:
    path = _relations_path(snapshot)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
    except (OSError, ValueError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def remember_wars(snapshot: dict) -> dict[str, Any]:
    """First turn each war is seen, shared by both seats. An engine turn wins when earlier."""
    data = _load_relations(snapshot)
    diplo = diplomacy(snapshot)
    if "majors" not in diplo:
        return data
    me, turn = _me(snapshot), _turn(snapshot)
    if not me:
        return data
    live: set[str] = set()
    changed = False
    for major in _lst(diplo.get("majors")):
        if not isinstance(major, dict) or not major.get("at_war"):
            continue
        pid = str(major.get("player_id") or "")
        if not pid:
            continue
        key = "|".join(sorted((me, pid)))
        live.add(key)
        row = data.get(key) if isinstance(data.get(key), dict) else {}
        since = row.get("since") if isinstance(row.get("since"), int) else None
        engine = major.get("war_since_turn")
        if isinstance(engine, int) and engine >= 0 and (since is None or engine < since):
            since = engine
        if since is None:
            since = turn
        if row.get("since") != since:
            data[key] = {"since": since}
            changed = True
    for key in list(data):
        parts = str(key).split("|")
        if me in parts and key not in live:
            data.pop(key, None)
            changed = True
    path = _relations_path(snapshot)
    if changed and path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return data


def _peace_items(deal: dict) -> bool:
    for side in ("give", "want"):
        for item in deal.get(side) or []:
            if isinstance(item, dict) and item.get("kind") == "peace":
                return True
    return False


def rival_status_line(snapshot: dict, rival_id: str) -> str | None:
    """One line: at war since T81; peace offered T96 pending/rejected."""
    major = next((m for m in _lst(diplomacy(snapshot).get("majors")) if isinstance(m, dict)
                  and str(m.get("player_id")) == str(rival_id)), None)
    if major is None:
        return None
    wars = remember_wars(snapshot)
    me, turn = _me(snapshot), _turn(snapshot)
    key = "|".join(sorted((me, str(rival_id))))
    row = wars.get(key) if isinstance(wars.get(key), dict) else {}
    since = row.get("since") if isinstance(row.get("since"), int) else None
    if major.get("at_war"):
        bits = [f"at war since T{since}" if since is not None else "at war"]
    else:
        bits = []
    name = pipeline._player_chat_name(snapshot, str(rival_id))
    latest: tuple[int, str] | None = None
    for deal in load_deals(snapshot):
        if {deal.get("from"), deal.get("to")} != {me, str(rival_id)} or not _peace_items(deal):
            continue
        status = deal.get("status")
        offered = int(deal.get("turn") or 0)
        age = turn - offered
        done_age = turn - int(deal.get("done_turn") or offered)
        text = ""
        if status == "pending" and age <= OFFER_TTL:
            whose = "you must answer" if deal.get("to") == me else "waiting on them"
            text = f"peace offered T{offered} pending ({whose})"
        elif status == "rejected" and done_age <= OFFER_TTL:
            why = deal.get("reason") or "rejected"
            text = f"peace offered T{offered} rejected ({why})"
        elif status == "accepted" and done_age <= 1:
            text = f"peace accepted T{deal.get('done_turn') or offered}"
        if text and (latest is None or offered >= latest[0]):
            latest = (offered, text)
    if latest:
        bits.append(latest[1])
    if not bits:
        return None
    if major.get("at_war") and latest and "you must answer" in latest[1]:
        bits[-1] += f"; deal.{name}.respond = ACCEPT | REJECT"
    return "; ".join(bits)


def deal_status_lines(snapshot: dict) -> list[str]:
    """Civ5 diplomacy.proposal / pending / deal lines, shared from deals.json."""
    lines = [
        "# == Deal status ==",
        "Chat never executes a trade. Reply cmd = the propose_cmd, accept_cmd, or reject_cmd below. "
        "A resource bundle is deal.<Leader> = give <items> for <items>.",
    ]
    me, turn = _me(snapshot), _turn(snapshot)
    index = 0
    for target in _majors(snapshot):
        pid = target["player_id"]
        for kind, pact in _CATALOG:
            if _pact_problem(snapshot, pid, {pact}):
                continue
            proposal = f"PROPOSAL_{kind}_{pid}"
            cmd = f"CMD_propose_{proposal}"
            if index >= 8:
                break
            lines.append(pipeline._wire_line(
                f"diplomacy.proposal.{index}",
                f"{pid}:{proposal} propose_cmd={cmd}",
            ))
            index += 1
        if index >= 8:
            break
    pending_i = 0
    deal_i = 0
    rejected_i = 0
    in_force = False
    for d in load_deals(snapshot):
        if me not in (d.get("from"), d.get("to")):
            continue
        other = d["to"] if d.get("from") == me else d.get("from")
        we, they = (d.get("give") or [], d.get("want") or []) if d.get("from") == me else (d.get("want") or [], d.get("give") or [])
        status = d.get("status")
        age = turn - int(d.get("turn") or 0)
        if status == "pending" and d.get("to") == me and age <= OFFER_TTL:
            prefix = f"diplomacy.pending.{pending_i}"
            request = f"DEAL_T{d.get('turn')}_{d.get('from')}"
            n = _player_num(str(d.get("from")))
            lines.append(pipeline._wire_line(f"{prefix}.from", d.get("from")))
            lines.append(pipeline._wire_line(f"{prefix}.request_id", request))
            lines.append(pipeline._wire_line(f"{prefix}.we_give", _civ5_items(we)))
            lines.append(pipeline._wire_line(f"{prefix}.they_give", _civ5_items(they)))
            lines.append(pipeline._wire_line(f"{prefix}.accept_cmd", f"CMD_accept_PLAYER_{n}_T{d.get('turn')}"))
            lines.append(pipeline._wire_line(f"{prefix}.reject_cmd", f"CMD_reject_PLAYER_{n}_T{d.get('turn')}"))
            pending_i += 1
        elif status == "pending" and d.get("from") == me and age <= OFFER_TTL:
            lines.append(pipeline._wire_line(
                f"diplomacy.pending.{pending_i}.from", f"{me} (offer sent to {other})"))
            lines.append(pipeline._wire_line(f"diplomacy.pending.{pending_i}.we_give", _civ5_items(we)))
            lines.append(pipeline._wire_line(f"diplomacy.pending.{pending_i}.they_give", _civ5_items(they)))
            pending_i += 1
        elif status == "accepted":
            left = GPT_TURNS - (turn - int(d.get("done_turn") or turn))
            if left < 0:
                continue
            in_force = True
            lines.append(pipeline._wire_line(
                f"diplomacy.deal.{deal_i}",
                f"{other}:DEAL_T{d.get('done_turn') or d.get('turn')} we_give={_civ5_items(we)} "
                f"they_give={_civ5_items(they)} cancelable=false turns_left={max(left, 0)}",
            ))
            deal_i += 1
        elif status == "rejected" and turn - int(d.get("done_turn") or 0) <= OFFER_TTL:
            lines.append(pipeline._wire_line(
                f"diplomacy.rejected.{rejected_i}",
                f"{other}: {d.get('reason') or 'rejected'}; we_give={_civ5_items(we)} they_give={_civ5_items(they)}",
            ))
            rejected_i += 1
    if not in_force:
        lines.append(pipeline._wire_line("diplomacy.deals_in_force", "no deal in force"))
    return lines


def bind_reply(snapshot: dict, key: str, value: Any) -> tuple[list[str], list[str]]:
    """Legal command ids for one diplomacy reply key, plus unresolved notes."""
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    text = str(value or "").strip()
    if low == "cmd" or low.startswith("cmd."):
        return _bind_civ5_command(snapshot, text)
    if low.startswith("envoy."):
        return _bind_envoy(snapshot, low, text)
    target = _match_target(snapshot, key)
    if target is None:
        return [], [f"{key}={value}: not a met rival"]
    pid, name, text = target["player_id"], target["name"], str(value or "").strip()
    if not low.startswith("deal.") and text.upper().replace(" ", "_") in ("ACCEPT_DEAL", "ACCEPT"):
        # legal.diplomacy.X=ACCEPT_DEAL means: accept X's open offer.
        if any(d.get("from") == pid for d in _open_offers_to_me(snapshot)):
            return bind_reply(snapshot, f"deal.{name}.respond", "ACCEPT")
        return [], []
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
            ids = [] if problem else _deal_commands(snapshot, pid, offer.get("want", []), offer.get("give", []), name)
            if not ids:
                offer["status"] = "rejected"
                offer["reason"] = problem or "could not build the deal"
                _save(snapshot, deals)
                return [], [f"{key}: cannot accept, {offer['reason']}; offer rejected"]
            offer["status"] = "accepted"
            offer["gpt"] = [{"from": offer["from"] if side == "give" else offer["to"], "amount": i["gpt"], "left": GPT_TURNS}
                            for side in ("give", "want") for i in offer.get(side, []) if "gpt" in i]
        else:
            offer["status"] = "rejected"
            offer["reason"] = "rejected"
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
        problem = _pact_problem(snapshot, pid, {i.get("kind") for i in give + want} - {None})
        if problem:
            return [], [f"{key}={value}: {problem}"]
        problem = _stock_problem(snapshot, give)
        if problem:
            return [], [f"{key}={value}: {problem}"]
        deals = [d for d in load_deals(snapshot)
                 if not (d.get("status") == "pending" and d.get("from") == _me(snapshot) and d.get("to") == pid)]
        deals.append({"from": _me(snapshot), "to": pid, "give": give, "want": want,
                      "turn": _turn(snapshot), "status": "pending"})
        _save(snapshot, deals)
        return [], []
    if _norm(text) in {w.upper().replace("_", "") for w in PEACE_WORDS} or str(text).strip().upper().replace(" ", "_") in {
        "PEACE", "PEACE_TREATY", "MAKE_PEACE",
    }:
        # Same offer as deal.<Leader> = peace. The other seat accepts it next turn.
        return bind_reply(snapshot, f"deal.{name}", "peace")
    raw = str(text).strip().upper().replace(" ", "_")
    if raw in {"REJECT", "ACCEPT_EMBASSY", "EMBASSY", "ACCEPT_DELEGATION", "DELEGATION"} or raw.startswith("ACCEPT_"):
        return [], [
            f"{key}={value}: {raw} is not a diplomacy order on legal.diplomacy.{name}. "
            f"At peace use DECLARE_WAR. At war use PEACE_TREATY (or deal.{name} = peace). "
            f"An open trade offer is answered with deal.{name}.respond = ACCEPT or REJECT. "
            f"An embassy is deal.{name} = embassy."
        ]
    action = _action_id(value)
    if action is None:
        return [], [
            f"{key}={value}: that is not a legal diplomacy order for {name}. "
            f"At peace use DECLARE_WAR. At war use PEACE_TREATY (or deal.{name} = peace). "
            "Trades and friendship use deal." + name + " = give <items> for <items>."
        ]
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
    if kind == "send_envoy":
        return f"ok - envoy sent to {who}"
    return None


ORDER_LABELS = {
    "send_diplomatic_action": ("diplomacy", "action_id"),
    "execute_deal": ("deal", "target_player_id"),
    "send_envoy": ("envoy", "target_player_id"),
}
