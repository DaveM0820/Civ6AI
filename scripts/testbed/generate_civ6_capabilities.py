"""Generate config/civ6-command-capabilities.json from civ6-mcp reference + Civ6Ai kind map."""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
REF = ROOT / "artifacts/reference/civ6-mcp/src/civ_mcp/server.py"
OUT = ROOT / "config/civ6-command-capabilities.json"

# Actionable MCP tools -> one or more kinds
TOOL_KINDS: dict[str, list[dict]] = {
    "set_research": [
        {"kind": "set_research_tech", "tier": "v1", "wire_scope": "empire", "wire": "legal.research.tech"},
        {"kind": "set_research_civic", "tier": "v1", "wire_scope": "empire", "wire": "legal.research.civic"},
    ],
    "set_city_production": [{"kind": "queue_production", "tier": "v1", "wire_scope": "city", "wire": "{City}.changeProduction"}],
    "purchase_item": [{"kind": "purchase_item", "tier": "v1", "wire_scope": "city", "wire": "{City}.purchase"}],
    "purchase_tile": [{"kind": "purchase_tile", "tier": "v1.1", "wire_scope": "city", "wire": "{City}.buyTile"}],
    "set_city_focus": [{"kind": "set_city_focus", "tier": "v1", "wire_scope": "city", "wire": "{City}.changeFocus"}],
    "unit_action": [
        {"kind": "move_unit", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.moveTo", "mcp_action": "move"},
        {"kind": "attack_target", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.attackTo", "mcp_action": "attack"},
        {"kind": "unit_posture_fortify", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.stance=fortify", "mcp_action": "fortify"},
        {"kind": "unit_posture_heal", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.stance=heal", "mcp_action": "heal"},
        {"kind": "unit_posture_alert", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.stance=alert", "mcp_action": "alert"},
        {"kind": "unit_posture_sleep", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.stance=sleep", "mcp_action": "sleep"},
        {"kind": "unit_skip", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.stance=skip", "mcp_action": "skip"},
        {"kind": "automate_explore", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.automate=explore", "mcp_action": "automate"},
        {"kind": "delete_unit", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.delete", "mcp_action": "delete", "risk": "high"},
        {"kind": "found_city", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.foundCity", "mcp_action": "found_city"},
        {"kind": "worker_improve", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.improve", "mcp_action": "improve"},
        {"kind": "worker_repair", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.repair", "mcp_action": "repair"},
        {"kind": "worker_remove_improvement", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.removeImprovement", "mcp_action": "remove_improvement"},
        {"kind": "worker_remove_feature", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.removeFeature", "mcp_action": "remove_feature"},
        {"kind": "worker_build_route", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.buildRoute", "mcp_action": "build_route"},
        {"kind": "sacrifice_charges", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.sacrificeCharges", "mcp_action": "sacrifice_charges"},
        {"kind": "trade_route", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.tradeRoute", "mcp_action": "trade_route"},
        {"kind": "teleport_trader", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.teleport", "mcp_action": "teleport"},
        {"kind": "activate_great_person", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.activate", "mcp_action": "activate"},
        {"kind": "spread_religion", "tier": "v1.1", "wire_scope": "unit", "wire": "{unit}.spreadReligion", "mcp_action": "spread_religion"},
    ],
    "upgrade_unit": [{"kind": "upgrade_unit", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.upgrade"}],
    "promote_unit": [{"kind": "promote_unit", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.promote"}],
    "city_action": [
        {"kind": "city_attack", "tier": "v1.1", "wire_scope": "city", "wire": "{City}.attack", "mcp_action": "attack"},
        {"kind": "resolve_city_capture", "tier": "v1", "wire_scope": "empire", "wire": "legal.capture", "risk": "high on raze"},
    ],
    "spy_action": [
        {"kind": "spy_travel", "tier": "v1.1", "wire_scope": "unit", "wire": "{spy}.spyAction=travel@(x,y)", "mcp_action": "travel"},
        {"kind": "spy_mission", "tier": "v1.1", "wire_scope": "unit", "wire": "{spy}.spyAction=MISSION@(x,y)"},
    ],
    "appoint_governor": [{"kind": "appoint_governor", "tier": "v1", "wire_scope": "empire", "wire": "legal.governor.appoint"}],
    "assign_governor": [{"kind": "assign_governor", "tier": "v1", "wire_scope": "empire", "wire": "legal.governor.assign"}],
    "promote_governor": [{"kind": "promote_governor", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.governor.promote"}],
    "choose_pantheon": [{"kind": "choose_pantheon", "tier": "v1", "wire_scope": "empire", "wire": "legal.pantheon"}],
    "found_religion": [{"kind": "found_religion", "tier": "v1", "wire_scope": "empire", "wire": "legal.religion"}],
    "choose_dedication": [{"kind": "choose_dedication", "tier": "v1", "wire_scope": "empire", "wire": "legal.dedication"}],
    "set_policies": [{"kind": "set_policies", "tier": "v1", "wire_scope": "empire", "wire": "legal.policies"}],
    "change_government": [{"kind": "change_government", "tier": "v1", "wire_scope": "empire", "wire": "legal.government"}],
    "send_envoy": [{"kind": "send_envoy", "tier": "v1", "wire_scope": "empire", "wire": "legal.envoy"}],
    "send_diplomatic_action": [{"kind": "send_diplomatic_action", "tier": "v1", "wire_scope": "empire", "wire": "legal.diplomacy.{Leader}", "risk": "high when war"}],
    "form_alliance": [{"kind": "form_alliance", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.alliance.{Leader}"}],
    "propose_trade": [{"kind": "propose_trade", "tier": "v1", "wire_scope": "empire", "wire": "legal.trade.offer.{Leader}"}],
    "propose_peace": [{"kind": "propose_peace", "tier": "v1", "wire_scope": "empire", "wire": "legal.peace.{Leader}"}],
    "respond_to_diplomacy": [{"kind": "respond_to_diplomacy", "tier": "v1", "wire_scope": "empire", "wire": "legal.diplomacy.respond.{Leader}"}],
    "respond_to_trade": [{"kind": "respond_to_trade", "tier": "v1", "wire_scope": "empire", "wire": "legal.trade.respond.{Leader}"}],
    "recruit_great_person": [{"kind": "recruit_great_person", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.gp.recruit"}],
    "patronize_great_person": [{"kind": "patronize_great_person", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.gp.patronize"}],
    "reject_great_person": [{"kind": "reject_great_person", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.gp.reject"}],
    "queue_wc_votes": [{"kind": "queue_wc_votes", "tier": "v1.1", "wire_scope": "empire", "wire": "legal.wc.votes"}],
    "skip_remaining_units": [{"kind": "skip_remaining_units", "tier": "host", "wire_scope": "host"}],
    "end_turn": [{"kind": "end_turn", "tier": "host", "wire_scope": "host"}],
    "dismiss_popup": [{"kind": "dismiss_popup", "tier": "host", "wire_scope": "host"}],
}

# v1 gaps (not in civ6-mcp today) + host-only helpers
EXTRA_CAPABILITIES: list[dict] = [
    {"kind": "cancel_deal", "tier": "v1", "wire_scope": "empire", "wire": "legal.deal.cancel.{Leader}"},
    {"kind": "clear_production_queue", "tier": "v1", "wire_scope": "city", "wire": "{City}.clearQueue"},
    {"kind": "remove_queue_order", "tier": "v1", "wire_scope": "city", "wire": "{City}.removeQueueOrder"},
    {"kind": "coastal_raid", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.coastalRaid"},
    {"kind": "pillage_improvement", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.pillage"},
    {"kind": "embark", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.embark"},
    {"kind": "disembark", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.disembark"},
    {"kind": "rebase_aircraft", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.rebase"},
    {"kind": "wmd_strike", "tier": "v1", "wire_scope": "unit", "wire": "cmd.N", "risk": "high"},
    {"kind": "swap_units", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.swapTo"},
    {"kind": "rock_band_concert", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.concert"},
    {"kind": "archaeologist_excavate", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.excavate"},
    {"kind": "naturalist_national_park", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.nationalPark"},
    {"kind": "seaside_resort", "tier": "v1", "wire_scope": "unit", "wire": "{unit}.seasideResort"},
    {"kind": "chat", "tier": "v1", "wire_scope": "empire", "wire": "chat.all|chat.{Leader}", "authority": "social_only"},
    {"kind": "spy_escape_route", "tier": "host", "wire_scope": "host", "lua_builder": "espionage.build_spy_escape_route"},
]


def main() -> None:
    # Prefer live civ6-mcp tool list when vendored; otherwise use TOOL_KINDS keys
    # so public checkouts without artifacts/reference still regenerate config.
    if REF.is_file():
        text = REF.read_text(encoding="utf-8")
        tools = re.findall(r"@mcp\.tool[^\n]*\nasync def (\w+)", text)
    else:
        tools = sorted(TOOL_KINDS.keys())

    capabilities: list[dict] = []
    seen_kinds: set[str] = set()
    for tool in tools:
        for entry in TOOL_KINDS.get(tool, []):
            row = dict(entry)
            row["mcp_tool"] = tool
            kind = row["kind"]
            if kind in seen_kinds:
                continue
            seen_kinds.add(kind)
            capabilities.append(row)

    for row in EXTRA_CAPABILITIES:
        if row["kind"] not in seen_kinds:
            capabilities.append(dict(row))
            seen_kinds.add(row["kind"])

    doc = {
        "schema_version": "civ6ai-command-capabilities/1",
        "rule": "Only currently executable instances enter legal_commands; unsupported kinds are never advertised.",
        "reference": "artifacts/reference/civ6-mcp",
        "mcp_tool_count": len(tools),
        "mcp_tools": sorted(tools),
        "tier_notes": {
            "v1": "Required for hybrid-control single-player gate",
            "v1.1": "Implement after v1 soak",
            "host": "Mod host only, not LLM",
            "deferred": "Not v1",
        },
        "capabilities": sorted(capabilities, key=lambda r: r["kind"]),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    v1 = sum(1 for c in capabilities if c.get("tier") == "v1")
    print(f"tools={len(tools)} kinds={len(capabilities)} v1={v1} -> {OUT}")


if __name__ == "__main__":
    main()
