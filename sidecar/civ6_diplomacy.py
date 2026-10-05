"""War and peace orders from civ6.diplomacy facts.

The mod writes can_declare_war / can_make_peace on each met major and city-state
(Civ6Ai_Snapshot._BuildDiplomacy), using the same TeamDiplomacy:CanDeclareWarOn /
CanMakePeaceWith calls as the leader and city-state screens. This module lists
those as optional reply keys and turns a matching reply into a legal command
the order channel already knows how to pack.

War and peace use Diplomacy:DeclareWarOn / MakePeaceWith. Delegations, embassies,
friendship, denouncements, open borders, and incoming deals use the leader
screen's DiplomacyManager sessions (IsDiplomaticActionValid, RequestSession,
AddResponse). The host answers a session when the model replies.
"""
from __future__ import annotations

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


def pending_requests(snapshot: dict) -> list[dict[str, Any]]:
    return [row for row in _lst(diplomacy(snapshot).get("pending_requests")) if isinstance(row, dict)]


def available_actions(snapshot: dict) -> list[dict[str, Any]]:
    return [row for row in _lst(diplomacy(snapshot).get("available_actions")) if isinstance(row, dict)]


def _request_name(snapshot: dict, row: dict) -> str:
    pid = str(row.get("from_player_id") or "")
    name = pipeline._player_chat_name(snapshot, pid)
    return name if name != pid else pid


def has_orders(snapshot: dict) -> bool:
    if pending_requests(snapshot) or available_actions(snapshot):
        return True
    return any(t["can_declare_war"] or t["can_make_peace"] for t in _targets(snapshot))


def required_rows(snapshot: dict) -> list[tuple[str, str]]:
    """Incoming sessions the model must accept or reject this turn."""
    rows: list[tuple[str, str]] = []
    for row in pending_requests(snapshot):
        name = _request_name(snapshot, row)
        if not name:
            continue
        kind = str(row.get("type") or "session")
        items = row.get("items")
        extra = ""
        if isinstance(items, list) and items:
            extra = " (" + "; ".join(str(x) for x in items[:8]) + ")"
        rows.append((f"diplomacy.{name}.respond", f"ACCEPT | REJECT  # {kind}{extra}"))
    return rows


def optional_key_hints(snapshot: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for target in _targets(snapshot):
        label = target["name"]
        if target["can_declare_war"]:
            out.append((f"legal.diplomacy.{label}", "DECLARE_WAR"))
        if target["can_make_peace"]:
            out.append((f"legal.peace.{label}", "apply"))
    for action in available_actions(snapshot):
        pid = str(action.get("player_id") or "")
        label = pipeline._player_chat_name(snapshot, pid)
        if label == pid:
            label = pid
        session = str(action.get("action") or "")
        if label and session:
            cost = action.get("gold_cost")
            hint = session if not isinstance(cost, int) or cost <= 0 else f"{session} ({cost} gold)"
            out.append((f"legal.session.{label}", hint))
    return out


def is_reply_key(key: str) -> bool:
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    return low.startswith("diplomacy.") or low.startswith("peace.") or low.startswith("session.")


def _match_target(snapshot: dict, key: str) -> dict[str, Any] | None:
    _, _, tail = key.partition(".")
    for prefix in ("diplomacy.", "peace.", "session."):
        if tail.lower().startswith(prefix):
            tail = tail.split(".", 1)[-1]
            break
    wanted = pipeline._resolve_chat_recipient(tail, snapshot)
    for target in _targets(snapshot):
        if wanted == target["player_id"]:
            return target
        if _norm(tail) == _norm(target["name"]) or _norm(tail) == _norm(target["player_id"]):
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


def _respond_name(key: str) -> str:
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    if low.endswith(".respond"):
        low = low[: -len(".respond")]
    if low.startswith("diplomacy."):
        low = low.split(".", 1)[-1]
    return low


def bind_reply(snapshot: dict, key: str, value: Any) -> tuple[list[str], list[str]]:
    """Legal command ids for one diplomacy reply key, plus unresolved notes."""
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    if low.startswith("diplomacy.") and low.endswith(".respond"):
        text = str(value or "").strip().upper()
        if text in ("", "NONE", "SKIP", "LATER"):
            return [], []
        if text not in ("ACCEPT", "REJECT", "POSITIVE", "NEGATIVE", "YES", "NO"):
            return [], [f"{key}={value}: use ACCEPT or REJECT"]
        wanted_name = _respond_name(key)
        match = next((row for row in pending_requests(snapshot)
                      if _norm(_request_name(snapshot, row)) == _norm(wanted_name)), None)
        if match is None:
            return [], [f"{key}: no open diplomacy session from {wanted_name}"]
        response = "ACCEPT" if text in ("ACCEPT", "POSITIVE", "YES") else "REJECT"
        return [_add_command(
            snapshot, "respond_to_diplomacy",
            {"session_id": match.get("session_id"), "response": response,
             "target_player_id": match.get("from_player_id")},
            f"{response.lower()} {match.get('type') or 'session'} from {_request_name(snapshot, match)}",
        )], []
    target = _match_target(snapshot, key)
    if target is None:
        return [], [f"{key}={value}: not a met rival"]
    pid = target["player_id"]
    name = target["name"]
    if low.startswith("session"):
        session_name = str(value or "").strip().upper().split()[0]
        allowed = {str(a.get("action")): a for a in available_actions(snapshot)}
        action = allowed.get(session_name)
        if action is None or str(action.get("player_id")) != pid:
            # match this target
            action = next((a for a in available_actions(snapshot)
                           if str(a.get("player_id")) == pid and str(a.get("action")) == session_name), None)
        if action is None:
            return [], [f"{key}={value}: that session is not open with {name}"]
        return [_add_command(
            snapshot, "diplomatic_session",
            {"target_player_id": pid, "action_id": session_name},
            f"open {session_name} with {name}",
        )], []
    if low.startswith("peace"):
        text = str(value or "").strip().lower()
        if text in ("", "none", "keep", "no", "skip"):
            return [], []
        if not target["can_make_peace"]:
            return [], [f"{key}: you cannot make peace with {name} now"]
        if text not in ("apply", "true", "yes", "peace", "make_peace", "makepeace"):
            return [], [f"{key}={value}: use apply to make peace"]
        return [_add_command(snapshot, "propose_peace", {"target_player_id": pid}, f"make peace with {name}")], []
    action = _action_id(value)
    if action is None:
        return [], [f"{key}={value}: only DECLARE_WAR is available for this seat"]
    if not target["can_declare_war"]:
        return [], [f"{key}: you cannot declare war on {name} now"]
    return [_add_command(
        snapshot, "send_diplomatic_action",
        {"target_player_id": pid, "action_id": action},
        f"declare war on {name}",
    )], []


def success_text(kind: str, fixed: dict) -> str | None:
    who = str(fixed.get("target_player_id") or "")
    if kind == "send_diplomatic_action":
        return f"ok — war declared on {who}"
    if kind == "propose_peace":
        return f"ok — peace with {who}"
    return None


ORDER_LABELS = {
    "send_diplomatic_action": ("diplomacy", "action_id"),
    "propose_peace": ("peace", "target_player_id"),
}
