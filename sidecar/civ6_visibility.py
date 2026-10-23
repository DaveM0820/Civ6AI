"""Per-seat visibility filter shared by every resource consumer.

Civ VI hides a resource from a player until that player knows its reveal tech
or civic (Resources.PrereqTech / PrereqCivic), and a tile only shows what the
player has revealed. The snapshot is built per seat, so filtering it once at
normalization means the wire text, ATTENTION, settle scoring, yield estimates,
coaching and the map render all see the same seat-correct view.
"""
from __future__ import annotations

from typing import Any

# Resources.PrereqTech / PrereqCivic (Gathering Storm). Resources not listed have
# no prerequisite (bonus and luxury) and are always visible on a revealed tile.
RESOURCE_REVEAL: dict[str, tuple[str | None, str | None]] = {
    "RESOURCE_HORSES": ("TECH_ANIMAL_HUSBANDRY", None),
    "RESOURCE_IRON": ("TECH_BRONZE_WORKING", None),
    "RESOURCE_NITER": ("TECH_MILITARY_ENGINEERING", None),
    "RESOURCE_COAL": ("TECH_INDUSTRIALIZATION", None),
    "RESOURCE_OIL": ("TECH_REFINING", None),
    "RESOURCE_ALUMINUM": ("TECH_RADIO", None),
    "RESOURCE_URANIUM": ("TECH_COMBUSTION", None),
    "RESOURCE_ANTIQUITY_SITE": (None, "CIVIC_NATURAL_HISTORY"),
    "RESOURCE_SHIPWRECK": (None, "CIVIC_CULTURAL_HERITAGE"),
}

REVEALED_KNOWLEDGE = ("visible", "remembered")


def _dct(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def known_techs(snapshot: dict) -> set[str]:
    research = _dct(_dct(snapshot.get("your_empire")).get("research"))
    return {str(t) for t in research.get("known_tech_ids") or [] if t}


def known_civics(snapshot: dict) -> set[str]:
    rows = _dct(snapshot.get("your_empire")).get("civics") or []
    return {str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")}


def resource_revealed(snapshot: dict, resource_id: Any,
                      techs: set[str] | None = None, civics: set[str] | None = None) -> bool:
    """True when this seat's techs/civics reveal resource_id. Unknown prereq data hides gated ones."""
    rid = str(resource_id or "").strip().upper()
    if not rid:
        return False
    tech, civic = RESOURCE_REVEAL.get(rid, (None, None))
    if tech and tech not in (known_techs(snapshot) if techs is None else techs):
        return False
    if civic and civic not in (known_civics(snapshot) if civics is None else civics):
        return False
    return True


def plot_revealed(plot: dict) -> bool:
    k = plot.get("knowledge")
    return k is None or str(k) in REVEALED_KNOWLEDGE


def filter_snapshot_resources(snapshot: dict) -> int:
    """Strip resources this seat cannot see from every plot list. Returns the count hidden."""
    techs, civics = known_techs(snapshot), known_civics(snapshot)
    hidden = 0
    km = _dct(snapshot.get("known_map"))
    for plot in km.get("plots") or []:
        if not isinstance(plot, dict) or not plot.get("resource_id"):
            continue
        if not plot_revealed(plot) or not resource_revealed(snapshot, plot["resource_id"], techs, civics):
            plot["resource_id"] = None
            hidden += 1
    return hidden
