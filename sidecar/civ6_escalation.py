"""Per-seat model escalation when a seat is struggling.

Last turn's signals, one point each:
  fail_share   at least CIV6AI_ESCALATION_FAIL_PERCENT of the orders were rejected
               by the sidecar, failed in game, had no effect, or were dropped
  repeats      an order was rejected or failed again for the same reason
  idle         CIV6AI_ESCALATION_IDLE_UNITS units idle on one tile for
               CIV6AI_ESCALATION_IDLE_TURNS turns or more
  stale        thought.situation repeated the turn before (civ6_turn_delta)

At CIV6AI_ESCALATION_SIGNALS points the seat steps up one rung of the ladder
for the next call; after CIV6AI_ESCALATION_CLEAN_TURNS turns under that it
steps back down one rung. Rung 0 is the seat's own model config (seat_models,
env). The ladder is a profile from config "escalation" or env
CIV6AI_ESCALATION_PROFILE. Escalated spend per seat is capped by
CIV6AI_ESCALATION_COST_CAP_CENTS. The chosen rung rides on
snapshot['_escalation'] and civ6_config.apply_seat_runtime applies it, so the
normal provider path makes the call.
"""
from __future__ import annotations

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


def signals(snapshot: dict[str, Any], dropped: list[Any] | None = None) -> dict[str, Any]:
    """Last turn's struggle signals for this seat."""
    from sidecar import civ6_apply_results as results
    from sidecar import civ6_legality as legality

    turn = _turn(snapshot)
    items = [i for i in _lst(_dct(snapshot.get("history")).get("command_results")) if isinstance(i, dict)]
    current = [i for i in items if i.get("kind") in (results.KIND_OK, results.KIND_FAILED, results.KIND_NO_EFFECT)]
    last = max((int(i.get("turn") or 0) for i in current), default=None)
    sent = [i for i in current if int(i.get("turn") or 0) == last] if last is not None else []
    bad = sum(1 for i in sent if i.get("kind") != results.KIND_OK)
    dropped_n = len([d for d in (dropped or []) if str(d).strip()])
    total = len(sent) + dropped_n
    failed = bad + dropped_n
    share = (100 * failed // total) if total else 0
    out: dict[str, Any] = {"orders": total, "failed": failed, "fail_percent": share, "hits": []}
    if total >= settings.get_int("CIV6AI_ESCALATION_MIN_ORDERS") and share >= settings.get_int(
            "CIV6AI_ESCALATION_FAIL_PERCENT"):
        out["hits"].append("fail_share")
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
    if _dct(_dct(snapshot.get("_turn_delta")).get("stale")):
        out["hits"].append("stale")
    out["score"] = len(out["hits"])
    return out


def decide(snapshot: dict[str, Any], memory: dict[str, Any] | None, cfg: Any = None,
           dropped: list[Any] | None = None) -> dict[str, Any]:
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
    else:
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
    choice = dict(rungs[rung - 1]) if rung > 0 else {}
    out = {
        "turn": turn, "profile": profile, "rung": rung, "rungs": len(rungs), "reason": reason,
        "signals": sig, "model": choice.get("model"), "reasoning_effort": choice.get("reasoning_effort"),
        "spent_usd": round(spent, 6), "cap_usd": cap,
    }
    history = [h for h in _lst(state.get("history")) if isinstance(h, dict) and int(h.get("turn") or -1) != turn]
    if reason in ("step_up", "step_down", "cost_cap"):
        history.append({"turn": turn, "rung": rung, "reason": reason, "hits": sig["hits"]})
    memory[STATE_KEY] = {"turn": turn, "base": base, "rung": rung, "clean": clean,
                         "spent_usd": spent, "history": history[-20:], "profile": profile}
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
