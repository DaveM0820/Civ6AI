"""Per-seat model escalation when a seat is struggling.

Last turn's signals, one point each:
  fail_share   at least CIV6AI_ESCALATION_FAIL_PERCENT of the orders were rejected
               by the sidecar, failed in game, had no effect, or were dropped
  repeats      an order was rejected or failed again for the same reason
  idle         CIV6AI_ESCALATION_IDLE_UNITS units idle on one tile for
               CIV6AI_ESCALATION_IDLE_TURNS turns or more
  stale        thought.situation repeated the turn before (civ6_turn_delta)
  oscillation  a unit turned back on its own path (civ6_turn_delta REVERSING)

Pipeline faults (queue_replaced, no_result_from_gameplay) and chat/deal pacing
drops are not the model's fault and never count. A fail share at or above
CIV6AI_ESCALATION_SEVERE_FAIL_PERCENT counts as two points on its own. A turn
with any signal is not clean, so a seat that keeps failing stays escalated.

At CIV6AI_ESCALATION_SIGNALS points the seat steps up one rung of the ladder
for the next call; after CIV6AI_ESCALATION_CLEAN_TURNS turns under that it
steps back down one rung. Rung 0 is the seat's own model config (seat_models,
env). The ladder is a profile from config "escalation" or env
CIV6AI_ESCALATION_PROFILE. Escalated spend per seat is capped by
CIV6AI_ESCALATION_COST_CAP_CENTS. After an escalated call on turn T the seat
uses tier 0 until turn T + CIV6AI_ESCALATION_COOLDOWN_TURNS (reason "cooldown";
the ladder rung is kept, only the call is held back). The last escalated turn
is kept in the escalation state and, when that is missing (fresh memory), read
back from the seat's journal. The chosen rung rides on
snapshot['_escalation'] and civ6_config.apply_seat_runtime applies it, so the
normal provider path makes the call.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sidecar import settings
from sidecar.civ6_common import dct as _dct
from sidecar.civ6_common import lst as _lst

STATE_KEY = "escalation"
SNAPSHOT_KEY = "_escalation"
HAIKU = "anthropic/claude-haiku-5.5"

# A rung overrides only the fields it names; the rest stay at the seat's tier 0.
DEFAULT_PROFILES: dict[str, list[dict[str, str]]] = {
    "off": [],
    # Cheap tier 0 (e.g. qwen flash, reasoning off): step up to Haiku, then Haiku thinking.
    "test": [
        {"model": HAIKU, "reasoning_effort": "off"},
        {"model": HAIKU, "reasoning_effort": "low"},
    ],
    # Haiku is tier 0 in seat_models: escalation raises its thinking.
    "real": [
        {"reasoning_effort": "low"},
        {"reasoning_effort": "medium"},
        {"reasoning_effort": "high"},
    ],
}
DEFAULT_PROFILE = "test"
log = logging.getLogger(__name__)


def _turn(snapshot: dict[str, Any]) -> int:
    try:
        return int(_dct(snapshot.get("decision")).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def ladder(cfg: Any = None) -> tuple[str, list[dict[str, str]]]:
    """(profile name, rungs above tier 0) from env, then config, then the default."""
    block = _dct(getattr(cfg, "escalation", None)) if cfg is not None else {}
    profiles = dict(DEFAULT_PROFILES)
    for name, rungs in _dct(block.get("profiles")).items():
        if isinstance(rungs, list):
            profiles[str(name)] = [dict(r) for r in rungs if isinstance(r, dict)]
    name = (settings.get("CIV6AI_ESCALATION_PROFILE", None, skip_empty=True)
            or str(block.get("profile") or DEFAULT_PROFILE)).strip().lower()
    return name, list(profiles.get(name, []))


PIPELINE_REASON_PREFIXES = ("queue_replaced", "no_result_from_gameplay")
PACING_DROP_MARKERS = ("came too soon", "near-repeat", "chat to ", "public chat", "already sent",
                       "deal.", "deal-status", "chat.")


def _pipeline_fault(item: dict[str, Any]) -> bool:
    return str(item.get("reason") or "").startswith(PIPELINE_REASON_PREFIXES)


def _counts_as_drop(text: Any) -> bool:
    t = str(text or "").strip()
    return bool(t) and not any(m in t for m in PACING_DROP_MARKERS)


def signals(snapshot: dict[str, Any], dropped: list[Any] | None = None) -> dict[str, Any]:
    """Last turn's struggle signals for this seat."""
    from sidecar import civ6_apply_results as results
    from sidecar import civ6_legality as legality

    turn = _turn(snapshot)
    items = [i for i in _lst(_dct(snapshot.get("history")).get("command_results")) if isinstance(i, dict)]
    current = [i for i in items if i.get("kind") in (results.KIND_OK, results.KIND_FAILED, results.KIND_NO_EFFECT)]
    last = max((int(i.get("turn") or 0) for i in current), default=None)
    sent = [i for i in current if int(i.get("turn") or 0) == last] if last is not None else []
    pipeline_n = sum(1 for i in sent if _pipeline_fault(i))
    sent = [i for i in sent if not _pipeline_fault(i)]
    bad = sum(1 for i in sent if i.get("kind") != results.KIND_OK)
    dropped_n = len([d for d in (dropped or []) if _counts_as_drop(d)])
    total = len(sent) + dropped_n
    failed = bad + dropped_n
    share = (100 * failed // total) if total else 0
    out: dict[str, Any] = {"orders": total, "failed": failed, "fail_percent": share, "hits": [],
                           "pipeline_faults": pipeline_n}
    weight = 0
    if total >= settings.get_int("CIV6AI_ESCALATION_MIN_ORDERS") and share >= settings.get_int(
            "CIV6AI_ESCALATION_FAIL_PERCENT"):
        out["hits"].append("fail_share")
        if share >= settings.get_int("CIV6AI_ESCALATION_SEVERE_FAIL_PERCENT"):
            weight = 1  # a severe fail share is worth two points by itself
    rows = [r for r in _lst(legality.load_state(snapshot).get("rejections")) if isinstance(r, dict)]
    turns_of = legality._rejection_turns(rows)
    repeat = any(
        len(turns_of.get((str(r.get("order") or "order"), str(r.get("reason") or "rejected")), ())) >= 2
        for r in rows if int(r.get("turn") or 0) in (turn - 1, turn)
    ) or any(isinstance(i.get("repeats"), int) and i["repeats"] > 1 and i.get("kind") == results.KIND_FAILED
             for i in sent)
    if repeat:
        out["hits"].append("repeats")
    idle = _dct(_dct(_dct(snapshot.get("civ6")).get("economy")).get("tracking")).get("idle_turns")
    long_idle = sum(1 for v in _dct(idle).values()
                    if isinstance(v, int) and v >= settings.get_int("CIV6AI_ESCALATION_IDLE_TURNS"))
    out["idle_units"] = long_idle
    if long_idle >= settings.get_int("CIV6AI_ESCALATION_IDLE_UNITS"):
        out["hits"].append("idle")
    delta = _dct(snapshot.get("_turn_delta"))
    if _dct(delta.get("stale")):
        out["hits"].append("stale")
    if _lst(delta.get("reversing")):
        out["hits"].append("oscillation")
    out["score"] = len(out["hits"]) + weight
    return out


def last_escalated_turn_from_journal(path: Any) -> int | None:
    """Latest turn whose journal metrics show a call above tier 0, or None."""
    if not path or not os.path.isfile(str(path)):
        return None
    best = None
    try:
        with open(str(path), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    m = _dct(json.loads(line).get("metrics"))
                except (ValueError, AttributeError):
                    continue
                if int(m.get("escalation_rung") or 0) > 0 and m.get("escalation_reason") != "cooldown":
                    t = m.get("turn")
                    if isinstance(t, int):
                        best = t if best is None else max(best, t)
    except OSError:
        return None
    return best


def decide(snapshot: dict[str, Any], memory: dict[str, Any] | None, cfg: Any = None,
           dropped: list[Any] | None = None, journal_path: Any = None) -> dict[str, Any]:
    """Pick this turn's rung, store state on memory, set snapshot['_escalation']."""
    memory = memory if isinstance(memory, dict) else {}
    turn = _turn(snapshot)
    state = dict(_dct(memory.get(STATE_KEY)))
    profile, rungs = ladder(cfg)
    if int(state.get("turn") or -1) == turn and isinstance(state.get("base"), dict):
        base = state["base"]  # same-turn rerun keeps the first decision's starting point
    else:
        base = {"rung": int(state.get("rung") or 0), "clean": int(state.get("clean") or 0)}
    rung, clean = int(base.get("rung") or 0), int(base.get("clean") or 0)
    sig = signals(snapshot, dropped)
    reason = "steady"
    if sig["score"] >= settings.get_int("CIV6AI_ESCALATION_SIGNALS"):
        clean = 0
        if rung < len(rungs):
            rung += 1
            reason = "step_up"
        else:
            reason = "at_top"
    elif sig["score"] == 0:
        clean += 1
        if rung > 0 and clean >= settings.get_int("CIV6AI_ESCALATION_CLEAN_TURNS"):
            rung -= 1
            clean = 0
            reason = "step_down"
    rung = min(rung, len(rungs))
    spent = float(state.get("spent_usd") or 0.0)
    cap = settings.get_int("CIV6AI_ESCALATION_COST_CAP_CENTS") / 100.0
    if rung > 0 and spent >= cap:
        rung, reason = 0, "cost_cap"
    call_rung = rung
    last = state.get("last_escalated_turn")
    if last is None and "last_escalated_turn" not in state:
        last = last_escalated_turn_from_journal(journal_path)
    last = int(last) if isinstance(last, (int, float)) else None
    cooldown = settings.get_int("CIV6AI_ESCALATION_COOLDOWN_TURNS")
    if call_rung > 0 and cooldown > 0 and last is not None and last != turn and turn < last + cooldown:
        log.info("escalation suppressed: seat cooldown, turn %s, last escalated %s, next allowed %s (rung %s, hits %s)",
                 turn, last, last + cooldown, rung, sig["hits"])
        call_rung, reason = 0, "cooldown"
    if call_rung > 0:
        last = turn
    choice = dict(rungs[call_rung - 1]) if call_rung > 0 else {}
    out = {
        "turn": turn, "profile": profile, "rung": call_rung, "ladder_rung": rung, "rungs": len(rungs), "reason": reason,
        "signals": sig, "model": choice.get("model"), "reasoning_effort": choice.get("reasoning_effort"),
        "spent_usd": round(spent, 6), "cap_usd": cap, "last_escalated_turn": last,
        "cooldown_turns": cooldown,
    }
    history = [h for h in _lst(state.get("history")) if isinstance(h, dict) and int(h.get("turn") or -1) != turn]
    if reason in ("step_up", "step_down", "cost_cap"):
        history.append({"turn": turn, "rung": rung, "reason": reason, "hits": sig["hits"]})
    memory[STATE_KEY] = {"turn": turn, "base": base, "rung": rung, "clean": clean,
                         "spent_usd": spent, "history": history[-20:], "profile": profile,
                         "last_escalated_turn": last}
    snapshot[SNAPSHOT_KEY] = out
    return out


def record_cost(memory: dict[str, Any] | None, snapshot: dict[str, Any], cost: Any) -> None:
    """Add this turn's model cost to the escalated spend when it ran above tier 0."""
    if not isinstance(memory, dict):
        return
    esc = _dct(snapshot.get(SNAPSHOT_KEY))
    state = memory.get(STATE_KEY)
    if not esc or not isinstance(state, dict) or int(esc.get("rung") or 0) <= 0:
        return
    if state.get("charged_turn") == esc.get("turn"):
        return  # a same-turn rerun does not charge twice
    try:
        amount = float(cost or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    state["spent_usd"] = round(float(state.get("spent_usd") or 0.0) + amount, 6)
    state["charged_turn"] = esc.get("turn")


def metrics_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    esc = _dct(snapshot.get(SNAPSHOT_KEY))
    if not esc:
        return {}
    sig = _dct(esc.get("signals"))
    return {
        "escalation_profile": esc.get("profile"),
        "escalation_rung": esc.get("rung"),
        "escalation_reason": esc.get("reason"),
        "escalation_hits": list(sig.get("hits") or []),
        "escalation_fail_percent": sig.get("fail_percent"),
        "escalation_model": esc.get("model"),
        "escalation_effort": esc.get("reasoning_effort"),
        "escalation_spent_usd": esc.get("spent_usd"),
    }
