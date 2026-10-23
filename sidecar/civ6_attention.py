"""One registry for the ATTENTION section and its Event.<name>.log rows.

Each provider owns one topic and returns structured items. The event name
comes from the provider, not from matching words in the note text. Order of
PROVIDERS is the order the lines appear in the prompt.
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


def _one(topic: str, fn: Callable[[dict], str | None], event: str | None = None):
    def provide(context: Any) -> list[Item]:
        note = fn(context if isinstance(context, dict) else {})
        return [Item(topic, note, event)] if note else []
    return provide


def _many(topic: str, fn: Callable[[Any], Iterable[str]], event: str | None = None, *, coerce: bool = False):
    def provide(context: Any) -> list[Item]:
        arg = (context if isinstance(context, dict) else {}) if coerce else context
        return [Item(topic, line, event) for line in fn(arg) if line]
    return provide


def _idle_resources(context: Any) -> list[Item]:
    from sidecar import civ6_prompt_coaching as coaching

    note, spends_gold = coaching.civ6_idle_resources(context if isinstance(context, dict) else {})
    return [Item("economy", note, "Economy" if spends_gold else None)] if note else []


def _blocked(context: Any) -> list[Item]:
    from sidecar import civ6_apply_results

    lines = civ6_apply_results.blocked_attention_lines(context if isinstance(context, dict) else {})
    return [Item("blocked", line) for line in lines if line]


def _no_city_sites(context: Any) -> list[Item]:
    from sidecar.civ6_wire import no_city_sites_lines

    return [Item("expansion", line) for line in no_city_sites_lines(context) if line]


def _module_items(module: str, topic: str):
    def provide(context: Any) -> list[Item]:
        import importlib

        mod = importlib.import_module(f"sidecar.{module}")
        return [Item(topic, line) for line in mod.attention_items(context) if line]
    return provide


def _coaching(name: str):
    def call(snapshot: Any):
        from sidecar import civ6_prompt_coaching as coaching

        return getattr(coaching, name)(snapshot)
    return call


PROVIDERS: tuple[Callable[[Any], list[Item]], ...] = (
    _one("explore", _coaching("civ6_exploration_attention"), "Explore"),
    _one("explore", _coaching("civ6_naval_explore_attention"), "Explore"),
    _one("lethargy", _coaching("civ6_lethargy_attention")),
    _one("war", _coaching("civ6_low_hp_retreat_attention"), "Wounded"),
    _one("war", _coaching("civ6_focus_fire_attention"), "FocusFire"),
    _one("expansion", _coaching("civ6_expansion_attention")),
    _one("military", _coaching("civ6_military_cap_attention")),
    _one("rejected", _coaching("civ6_rejected_last_turn_attention")),
    _one("idle", _coaching("civ6_host_default_attention")),
    _idle_resources,
    _many("loyalty", _coaching("civ6_loyalty_attention"), "Economy", coerce=True),
    _many("economy", _coaching("civ6_economy_attention"), "Economy", coerce=True),
    _blocked,
    _no_city_sites,
    _module_items("civ6_combat_wire", "war"),
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
