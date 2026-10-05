"""Gathering Storm climate, city power, and strategic stockpiles on the Civ VI prompt.

Reads optional ``civ6.climate`` / ``civ6.power`` / ``civ6.stockpiles`` written by
Civ6Ai_Snapshot from the same engine calls ClimateScreen.lua, CityBannerManager.lua,
CityPanelPower.lua, and TopPanel_Expansion2.lua use. Each block is omitted until
it is relevant, so classical-era prompts stay unchanged.
"""
from __future__ import annotations

from typing import Any

from sidecar import pipeline_v2 as pipeline


def _block(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    civ6 = snapshot.get("civ6") if isinstance(snapshot, dict) else None
    block = civ6.get(name) if isinstance(civ6, dict) else None
    return block if isinstance(block, dict) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "?"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    if signed and value > 0:
        return "+" + text
    return text


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _resource_key(resource_id: str) -> str:
    return pipeline._readable_id(resource_id, "RESOURCE_").replace(" ", "_").lower()


def _city_name(snapshot: dict[str, Any], row: dict[str, Any]) -> str:
    city_id = str(row.get("city_id") or "")
    for city in snapshot.get("your_cities") or []:
        if isinstance(city, dict) and str(city.get("city_id")) == city_id:
            return pipeline._city_prompt_name(city)
    name = row.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return pipeline._readable_id(city_id, "CITY_")


def _climate_lines(snapshot: dict[str, Any]) -> list[str]:
    climate = _block(snapshot, "climate")
    if not climate:
        return []
    lines: list[str] = []
    level = _num(climate.get("level"))
    if level is not None:
        lines.append(pipeline._wire_line("empire.climate.level", int(level)))
    co2_world = _num(climate.get("co2_world"))
    co2_you = _num(climate.get("co2_you"))
    if co2_world is not None or co2_you is not None:
        world = _fmt(co2_world)
        yours = _fmt(co2_you)
        lines.append(pipeline._wire_line("empire.climate.co2", f"{world} world, {yours} yours"))
    tenths = _num(climate.get("temperature_c_tenths"))
    temp = (tenths / 10.0) if tenths is not None else _num(climate.get("temperature_c"))
    if temp is not None:
        lines.append(pipeline._wire_line("empire.climate.temperature", f"{_fmt(temp, signed=True)} C"))
    sea_bits = []
    sea_turns = _num(climate.get("sea_rise_turns"))
    if sea_turns is not None:
        sea_bits.append(f"{int(sea_turns)} turns to next rise")
    flooded = _num(climate.get("tiles_flooded"))
    submerged = _num(climate.get("tiles_submerged"))
    if flooded is not None or submerged is not None:
        sea_bits.append(f"{_fmt(flooded)} tiles flooded, {_fmt(submerged)} submerged")
    if sea_bits:
        lines.append(pipeline._wire_line("empire.climate.sea", "; ".join(sea_bits)))
    hazards = []
    for key, label in (("storm_pct", "storm"), ("flood_pct", "flood"), ("drought_pct", "drought")):
        value = _num(climate.get(key))
        if value is not None:
            hazards.append(f"{label} {int(value)}%")
    if hazards:
        lines.append(pipeline._wire_line("empire.climate.hazards", ", ".join(hazards)))
    return lines


def _power_cities(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _list(_block(snapshot, "power").get("cities")) if isinstance(row, dict)]


def _power_current(row: dict[str, Any]) -> float:
    if row.get("powered_by_project") is True:
        required = _num(row.get("required")) or 0.0
        return required
    return (_num(row.get("free")) or 0.0) + (_num(row.get("temporary")) or 0.0)


def _power_shortfall(row: dict[str, Any]) -> float:
    if row.get("powered") is True:
        return 0.0
    required = _num(row.get("required")) or 0.0
    return max(0.0, required - _power_current(row))


def _power_summary_lines(snapshot: dict[str, Any]) -> list[str]:
    cities = _power_cities(snapshot)
    if not cities:
        return []
    powered = sum(1 for row in cities if row.get("powered") is True)
    shorts = []
    for row in cities:
        gap = _power_shortfall(row)
        if gap > 0:
            shorts.append(f"{_city_name(snapshot, row)} short {_fmt(gap)}")
    text = f"{powered} of {len(cities)} cities powered"
    if shorts:
        text += " (" + "; ".join(shorts) + ")"
    return [pipeline._wire_line("empire.power", text)]


def city_lines(snapshot: dict[str, Any], city: dict[str, Any], name: str) -> list[str]:
    city_id = str(city.get("city_id") or "")
    for row in _power_cities(snapshot):
        if str(row.get("city_id")) != city_id:
            continue
        free = _fmt(_num(row.get("free")))
        temp = _fmt(_num(row.get("temporary")))
        required = _fmt(_num(row.get("required")))
        if row.get("powered") is True:
            status = "powered (project)" if row.get("powered_by_project") is True else "powered"
        else:
            status = "UNPOWERED"
        return [pipeline._wire_line(f"{name}.power", f"{free}+{temp} / {required} {status}")]
    return []


def _stockpile_lines(snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for row in _list(_block(snapshot, "stockpiles").get("strategics")):
        if not isinstance(row, dict) or not isinstance(row.get("resource_id"), str):
            continue
        key = _resource_key(row["resource_id"])
        amount = _fmt(_num(row.get("amount")))
        cap = _num(row.get("cap"))
        text = f"{amount}/{_fmt(cap)}" if cap else amount
        bits = []
        reserved = _num(row.get("reserved"))
        if reserved:
            bits.append(f"{_fmt(reserved)} reserved")
        per_turn = _num(row.get("per_turn"))
        if per_turn:
            bits.append(f"{_fmt(per_turn, signed=True)}/turn")
        unit_demand = _num(row.get("unit_demand"))
        if unit_demand:
            bits.append(f"units {_fmt(unit_demand)}")
        power_demand = _num(row.get("power_demand"))
        if power_demand:
            bits.append(f"power {_fmt(power_demand)}")
        if bits:
            text += " (" + "; ".join(bits) + ")"
        lines.append(pipeline._wire_line(f"empire.stockpile.{key}", text))
    return lines


def empire_lines(snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for builder in (_climate_lines, _power_summary_lines, _stockpile_lines):
        try:
            lines.extend(builder(snapshot))
        except Exception:
            continue
    return lines


def attention_items(snapshot: dict[str, Any]) -> list[str]:
    names = [_city_name(snapshot, row) for row in _power_cities(snapshot)
             if row.get("powered") is not True]
    if not names:
        return []
    return [f"***Cities unpowered: {', '.join(names)}***"]
