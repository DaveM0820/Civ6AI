"""Trade-route facts for every seat (civ6.trade from the mod snapshot)."""
from __future__ import annotations

from typing import Any


def block(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    trade = civ6.get("trade")
    return trade if isinstance(trade, dict) else None


def prompt_lines(snapshot: dict[str, Any], wire_ids: dict[str, str] | None = None) -> list[str]:
    """'TRADE ROUTES: X/Y in use' plus idle/on-route traders and last turn's route requests."""
    trade = block(snapshot)
    if trade is None:
        return []
    wire_ids = wire_ids or {}
    routes, cap = trade.get("routes"), trade.get("capacity")
    traders = [t for t in trade.get("traders") or [] if isinstance(t, dict)]
    if not isinstance(routes, int) and not traders:
        return []
    head = "TRADE ROUTES: "
    if isinstance(routes, int) and isinstance(cap, int):
        head += f"{routes}/{cap} in use"
        if cap > routes:
            head += f" ({cap - routes} free slot{'s' if cap - routes != 1 else ''})"
    else:
        head += "count unknown"
    bits = []
    for t in traders:
        name = wire_ids.get(str(t.get("unit_id")), str(t.get("unit_id")))
        if t.get("on_route"):
            dest = t.get("destination")
            bits.append(f"{name} on a route" + (f" to {dest}" if dest else ""))
        else:
            bits.append(f"{name} idle at {t.get('x')},{t.get('y')}")
    if bits:
        head += ". Traders: " + "; ".join(bits[:8])
    lines = [head + "."]
    for req in trade.get("last_requests") or []:
        if not isinstance(req, dict):
            continue
        name = wire_ids.get(str(req.get("unit_id")), str(req.get("unit_id")))
        took = "started" if req.get("took") else "did NOT start (trader is not on a route)"
        lines.append(f"Trade route requested on T{req.get('turn')} for {name}: {took}.")
    idle = [t for t in traders if not t.get("on_route")]
    legal = snapshot.get("legal_commands") if isinstance(snapshot.get("legal_commands"), list) else []
    can_route = any(isinstance(c, dict) and c.get("kind") == "trade_route" for c in legal)
    if idle and isinstance(cap, int) and isinstance(routes, int) and cap > routes and not can_route:
        lines.append(
            "Idle traders with free route slots: this seat has no synced TradeRoute order "
            "(the game's own AI is expected to start routes; if they stay idle, that is a known limitation)."
        )
    return lines
