"""One registry for the ATTENTION section and its Event.<name>.log rows.

Each provider owns one topic and returns structured items. The event name
comes from the provider, not from matching words in the note text. Order of
PROVIDERS is the order the lines appear in the prompt. Priority 0 is never
trimmed; under the prompt budget the highest number goes first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

SECTION = "ATTENTION"


@dataclass(frozen=True)
class Item:
    topic: str
    text: str
    event: str | None = None  # Event.<event>.log row the model writes a thought for
    priority: int = 0  # lower is more urgent; the section itself is budget-protected
    commands: tuple[str, ...] = ()


def _one(topic: str, fn: Callable[[dict], str | None], event: str | None = None, priority: int = 2):
    def provide(context: Any) -> list[Item]:
        note = fn(context if isinstance(context, dict) else {})
        return [Item(topic, note, event, priority)] if note else []
    return provide


def _many(topic: str, fn: Callable[[Any], Iterable[str]], event: str | None = None, *,
          coerce: bool = False, priority: int = 2):
    def provide(context: Any) -> list[Item]:
        arg = (context if isinstance(context, dict) else {}) if coerce else context
        return [Item(topic, line, event, priority) for line in fn(arg) if line]
    return provide


def _idle_resources(context: Any) -> list[Item]:
    from sidecar import civ6_prompt_coaching as coaching

    note, spends_gold = coaching.civ6_idle_resources(context if isinstance(context, dict) else {})
    return [Item("economy", note, "Economy" if spends_gold else None, 3)] if note else []


def _blocked(context: Any) -> list[Item]:
    from sidecar import civ6_apply_results

    lines = civ6_apply_results.blocked_attention_lines(context if isinstance(context, dict) else {})
    return [Item("blocked", line, None, 1) for line in lines if line]


def _settle(context: Any) -> list[Item]:
    """The one settle/expansion owner: found now, walk to a listed site, or train/buy a Settler."""
    from sidecar import pipeline_v2 as pipeline
    from sidecar import civ6_prompt_coaching as coaching
    from sidecar.civ6_command_wire import labeled_settle_sites
    from sidecar.civ6_wire import no_city_sites_lines

    snap = context if isinstance(context, dict) else {}
    units = [u for u in snap.get("your_units") or [] if isinstance(u, dict)]
    settlers = [u for u in units if u.get("unit_type_id") == "UNIT_SETTLER"]
    has_city = any(isinstance(c, dict) for c in snap.get("your_cities") or [])
    items: list[Item] = []
    if settlers:
        wire = pipeline._build_unit_wire_id_map(units)
        legal = {
            str((c.get("fixed_arguments") or {}).get("unit_id") or "")
            for c in snap.get("legal_commands") or []
            if isinstance(c, dict) and c.get("kind") == "found_city"
        }
        sites = labeled_settle_sites(snap)
        found_now: list[str] = []
        walk: list[str] = []
        for unit in settlers[:4]:
            uid = str(unit.get("unit_id") or "")
            name = wire.get(uid, uid)
            if uid in legal:
                found_now.append(name)
                continue
            own = [f"({s['x']},{s['y']})" for s in sites if s.get("unit_id") == uid][:4]
            walk.append(f"{name}.command = MoveTo one of {', '.join(own)}" if own else f"{name}.command = MoveTo a site you pick")
        commands = tuple(f"{n}.command = FoundCity" for n in found_now) + tuple(walk)
        bits: list[str] = []
        if not has_city:
            bits.append("No capital yet: every turn without one costs all science, culture and production.")
        if found_now:
            target = "the capital" if not has_city else "a city"
            bits.append(
                f"Found {target} this turn: {'; '.join(c for c in commands if c.endswith('FoundCity'))}, "
                "unless a clearly better listed site is within about 3 tiles."
            )
        if walk:
            bits.append("; ".join(walk) + ", then FoundCity on arrival. Do not trek more than about 3 tiles"
                        + (" for a capital." if not has_city else " or park a Settler in a city."))
        bits.append("Keep a military unit next to each Settler until it founds.")
        bits.append(coaching.CIV6_SETTLER_MAP_ADVICE)
        items.append(Item("settle", "SETTLE: " + " ".join(bits), "Settle", 0 if not has_city else 1, commands))
    expansion = coaching.civ6_expansion_attention(snap)
    if expansion:
        items.append(Item("settle", expansion, None, 2))
    items.extend(Item("settle", line, None, 1) for line in no_city_sites_lines(context) if line)
    return items


def _module_items(module: str, topic: str, priority: int = 2):
    def provide(context: Any) -> list[Item]:
        import importlib

        mod = importlib.import_module(f"sidecar.{module}")
        return [Item(topic, line, None, priority) for line in mod.attention_items(context) if line]
    return provide


def _coaching(name: str):
    def call(snapshot: Any):
        from sidecar import civ6_prompt_coaching as coaching

        return getattr(coaching, name)(snapshot)
    return call


PROVIDERS: tuple[Callable[[Any], list[Item]], ...] = (
    _one("explore", _coaching("civ6_exploration_attention"), "Explore", 3),
    _one("explore", _coaching("civ6_naval_explore_attention"), "Explore", 3),
    _one("lethargy", _coaching("civ6_lethargy_attention"), "Lethargy", 2),
    _one("war", _coaching("civ6_low_hp_retreat_attention"), "Wounded", 1),
    _one("war", _coaching("civ6_focus_fire_attention"), "FocusFire", 1),
    _settle,
    _one("military", _coaching("civ6_military_cap_attention"), None, 3),
    _one("rejected", _coaching("civ6_rejected_last_turn_attention"), "Blocked", 1),
    _one("idle", _coaching("civ6_host_default_attention"), None, 3),
    _idle_resources,
    _many("loyalty", _coaching("civ6_loyalty_attention"), "Economy", coerce=True, priority=1),
    _many("economy", _coaching("civ6_economy_attention"), "Economy", coerce=True, priority=2),
    _blocked,
    _module_items("civ6_combat_wire", "war", 1),
    _module_items("civ6_economy", "economy"),
    _module_items("civ6_gs_wire", "governance"),
    _module_items("civ6_governance", "governance"),
)


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def collect(context: Any) -> list[Item]:
    """Every provider's items in registry order, first copy of each line kept."""
    seen: set[str] = set()
    out: list[Item] = []
    for provide in PROVIDERS:
        for item in provide(context):
            key = _key(item.text)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def lines(context: Any) -> list[str]:
    return [item.text for item in collect(context)]


def event_names(context: Any) -> list[str]:
    """Event names in first-seen order, one row each."""
    names: list[str] = []
    for item in collect(context):
        if item.event and item.event not in names:
            names.append(item.event)
    return names
