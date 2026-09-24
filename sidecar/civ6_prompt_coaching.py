"""Civ6 soft coaching / REQUIRED COMMANDS helpers ported from Civ5 wire patterns.

Prompt guidance stays coaching (never hard rules). Map axes follow Civ6 hex convention:
Y increases south (unlike Civ5's north-up flipped renderer).
"""
from __future__ import annotations

from typing import Any

from sidecar import pipeline_v2 as pipeline

CIV6_RETREAT_HEAL_HP_THRESHOLD = 30
CIV6_EXPLORE_STALL_TURNS = 5
CIV6_EXPLORE_STALL_BELOW_PCT = 90

CIV6_SETTLER_MAP_ADVICE = (
    "Carefully observe the attached map to choose a settle location, and remember it for "
    "as many turns as the walk takes. Weigh strategic and luxury resources, choke points, "
    "fresh water and coast access, and tile yields (food/production/gold)."
)

CIV6_MOVE_THEN_ATTACK_GUIDANCE = (
    "A unit with leftover movement can often still attack this turn after moving — "
    "do not treat \"already moved\" as \"cannot attack\" unless the unit has 0 moves left "
    "or the attack is otherwise illegal."
)

CIV6_UNIT_STACKING_GUIDANCE = (
    "Civ6 stacking: typically one military formation-class unit per tile, plus one civilian "
    "or support unit; two military units of the same formation class cannot share a tile. "
    "Use corps/armies and support units (e.g. battering ram, siege tower) intentionally."
)


def _civ6_tactical_map_attached(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    try:
        from sidecar.map_situational import tactical_map_attached

        return bool(tactical_map_attached(snapshot))
    except Exception:
        images = snapshot.get("advciv", {})
        if isinstance(images, dict):
            manifest = images.get("map_images")
            if isinstance(manifest, list):
                for row in manifest:
                    if isinstance(row, dict) and str(row.get("role") or "").lower() in {
                        "tactical",
                        "viewport",
                        "focus",
                    }:
                        return True
        return False


def _civ6_attach_map_images(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return True
    return pipeline.map_image_attach_turn(snapshot)


def civ6_required_thought_rows(snapshot: dict[str, Any] | None) -> list[str]:
    """Map-read + thought keys that belong in REQUIRED COMMANDS and the required count."""
    rows: list[str] = []
    if _civ6_attach_map_images(snapshot):
        rows.append(
            "strategicmap.read = one short paragraph on the attached strategic map "
            "(land vs water, chokes, your borders, one takeaway)"
        )
        if _civ6_tactical_map_attached(snapshot):
            rows.append(
                "tacticalmap.read = one short paragraph on the attached tactical map "
                "(key (x,y) for units, cities, resources)"
            )
    rows.append(
        "thought.situation = one paragraph board read this turn "
        "(economy, science, amenities, military, geography; new observations only)"
    )
    rows.append(
        "thought.strategy = one paragraph: long-term path to victory, then this turn's plan "
        "for each required and optional command you will issue"
    )
    return rows


def civ6_optional_commands_preamble_lines(required_count: int | None = None) -> list[str]:
    lines = [
        "OPTIONAL COMMANDS are encouraged every turn — not leftovers. Required rows are only the minimum.",
        "Issue as many optional commands as you want this turn: chat.all, chat.LeaderName, diplomacy deals, "
        "research, map.viewport, extra unit/city orders, and any other listed shape.",
        "There is no cap. Models often emit only required rows — you may keep going with useful optionals.",
        "thought.freethinking = ... is optional free-form reflection (not counted as required).",
    ]
    if required_count is not None:
        n = max(0, int(required_count))
        if n <= 0:
            lines.append(
                "There are no required command rows this turn. Still issue as many optional commands as useful, "
                "numbered from 1."
            )
        else:
            lines.append(
                f"There are {n} required commands. Respond with every required command, enumerated from 1 to {n}."
            )
            lines.append(
                f"After row {n}, add as many optional commands as useful starting at {n + 1}. There is no cap."
            )
    return lines


def civ6_map_axes_wrap_guidance(snapshot: dict[str, Any] | None = None) -> str:
    """Standing map-axis / X-wrap coaching for Civ6 (Y increases south)."""
    width = None
    wrap_x = True
    if isinstance(snapshot, dict):
        game = snapshot.get("game")
        if isinstance(game, dict):
            try:
                width = int(game.get("map_width")) if game.get("map_width") is not None else None
            except (TypeError, ValueError):
                width = None
            if width is not None and width <= 0:
                width = None
            if game.get("wrap_x") is False:
                wrap_x = False
    w_label = str(width) if width is not None else "map.width"
    if width is not None and width >= 20:
        near = width - 10
        seam_example = (
            f"with width {w_label}, a tile at x={near} and a tile at x=10 are 20 tiles apart "
            f"(10+10), not the long way around"
        )
    else:
        seam_example = (
            f"with width {w_label}, a tile at x=width-10 and a tile at x=10 are 20 tiles apart "
            f"(10+10), not the long way around"
        )
    wrap_clause = (
        f"The world wraps on X only (max X loops to 0); Y does not wrap. "
        f"Distance across the X seam uses the short way: {seam_example}."
        if wrap_x
        else "This map does not wrap on X; treat left/right edges as map borders."
    )
    return (
        "Map axes on the strategic/tactical images: game-plot x increases east (right on the image); "
        "game-plot y increases south (down on the image) — Civ6 hex grid. "
        f"{wrap_clause}"
    )


def civ6_unit_health_percent(unit: dict[str, Any]) -> int | None:
    health = unit.get("health")
    if isinstance(health, dict):
        current = health.get("current")
        maximum = health.get("maximum")
        if isinstance(current, int) and isinstance(maximum, int) and maximum > 0:
            return int(current * 100 / maximum)
    raw = unit.get("health_percent")
    if isinstance(raw, int):
        return raw
    return None


def civ6_wounded_hp_label(pct: int | None) -> str | None:
    if not isinstance(pct, int) or pct >= 100:
        return None
    return f"{pct}%"


def _civ6_explored_percent(snapshot: dict[str, Any]) -> int | None:
    known = snapshot.get("known_map")
    if isinstance(known, dict):
        cached = known.get("explored_percent")
        if isinstance(cached, int):
            return cached
    try:
        return pipeline._map_explored_percent(snapshot)
    except Exception:
        return None


def civ6_exploration_attention(snapshot: dict[str, Any]) -> str | None:
    explored = _civ6_explored_percent(snapshot)
    if not isinstance(explored, int) or explored >= CIV6_EXPLORE_STALL_BELOW_PCT:
        return None
    history = snapshot.get("history")
    tracking = history.get("explore_tracking") if isinstance(history, dict) else None
    samples = tracking.get("samples") if isinstance(tracking, dict) else None
    if not isinstance(samples, list) or len(samples) < 2:
        if explored < 25:
            return (
                f"Map only {explored}% explored — soft advice: keep pushing scouts into fog "
                "when safe; under-explored maps hide settle sites and rivals."
            )
        return None
    try:
        newest = max(samples, key=lambda row: int(row.get("turn", -1)) if isinstance(row, dict) else -1)
        newest_turn = int(newest.get("turn", -1))
        newest_revealed = int(newest.get("revealed", -1))
    except (TypeError, ValueError, AttributeError):
        return None
    older = [
        row
        for row in samples
        if isinstance(row, dict)
        and int(row.get("turn", -1)) <= newest_turn - CIV6_EXPLORE_STALL_TURNS
    ]
    if not older:
        return None
    try:
        baseline = max(int(row.get("revealed", -1)) for row in older)
    except (TypeError, ValueError):
        return None
    if newest_revealed >= 0 and baseline >= 0 and newest_revealed <= baseline:
        return (
            f"No new exploration in {CIV6_EXPLORE_STALL_TURNS}+ turns while map is only "
            f"{explored}% explored — soft advice: send a scout or military unit into fog this turn."
        )
    return None


def civ6_low_hp_retreat_attention(snapshot: dict[str, Any]) -> str | None:
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    bits: list[str] = []
    for unit in units:
        hp = civ6_unit_health_percent(unit)
        if not isinstance(hp, int) or hp >= CIV6_RETREAT_HEAL_HP_THRESHOLD:
            continue
        # Skip pure civilians for retreat-heal coaching.
        type_id = str(unit.get("unit_type_id") or "")
        if any(token in type_id for token in ("SETTLER", "BUILDER", "TRADER", "MISSIONARY", "APOSTLE")):
            continue
        unit_id = unit.get("unit_id")
        prefix = wire_ids.get(str(unit_id), "unit") if isinstance(unit_id, str) else "unit"
        bits.append(f"{prefix} at {hp}% HP")
    if not bits:
        return None
    joined = "; ".join(bits[:6])
    more = "" if len(bits) <= 6 else f" (+{len(bits) - 6} more)"
    return (
        f"{joined}{more} — almost always better to retreat and heal "
        "unless this is an intentional sacrifice"
    )


def _civ6_attack_target_keys(snapshot: dict[str, Any]) -> dict[tuple[int, int], list[str]]:
    """Map target plot -> list of friendly unit wire ids that can attack it (from legal_commands)."""
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    grouped: dict[tuple[int, int], list[str]] = {}
    for command in snapshot.get("legal_commands", []) or []:
        if not isinstance(command, dict) or command.get("kind") != "attack_target":
            continue
        fixed = command.get("fixed_arguments") or {}
        if not isinstance(fixed, dict):
            continue
        unit_id = fixed.get("unit_id")
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if x is None or y is None:
            plot_id = fixed.get("plot_id")
            if isinstance(plot_id, str):
                parsed = pipeline._parse_plot_coords(plot_id) if hasattr(pipeline, "_parse_plot_coords") else None
                if isinstance(parsed, tuple) and len(parsed) == 2:
                    x, y = parsed
        try:
            xi, yi = int(x), int(y)
        except (TypeError, ValueError):
            continue
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, unit_id)
        bucket = grouped.setdefault((xi, yi), [])
        if prefix not in bucket:
            bucket.append(prefix)
    return grouped


def civ6_focus_fire_attention(snapshot: dict[str, Any]) -> str | None:
    grouped = _civ6_attack_target_keys(snapshot)
    bits: list[str] = []
    for (x, y), attackers in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(attackers) < 2:
            continue
        bits.append(f"{len(attackers)} friendly units ({', '.join(attackers[:4])}) can hit ({x},{y})")
    if not bits:
        return None
    return (
        " | ".join(bits[:3])
        + " — soft advice: focus-fire the shared target rather than splitting strikes"
    )


def civ6_economy_attention(snapshot: dict[str, Any]) -> list[str]:
    out: list[str] = []
    empire = snapshot.get("your_empire")
    if not isinstance(empire, dict):
        return out
    gold = empire.get("gold")
    gpt = empire.get("gold_per_turn")
    try:
        gold_i = int(gold) if gold is not None else None
        gpt_i = int(gpt) if gpt is not None else None
    except (TypeError, ValueError):
        gold_i, gpt_i = None, None
    if isinstance(gpt_i, int) and gpt_i < 0:
        out.append(
            f"Gold per turn is {gpt_i} — soft advice: bankruptcy / negative GPT shrinks maintenance "
            "headroom and can force unit or building losses; raise income or cut costs."
        )
    if isinstance(gold_i, int) and gold_i < 0:
        out.append(
            f"Treasury is {gold_i} gold — soft advice: clear the deficit before expanding army size."
        )
    amenities = empire.get("amenities")
    if isinstance(amenities, dict):
        net = amenities.get("net")
        try:
            net_i = int(net) if net is not None else None
        except (TypeError, ValueError):
            net_i = None
        if isinstance(net_i, int) and net_i < 0:
            out.append(
                f"Empire amenities net {net_i} — soft advice: unhappy cities grow slower and revolt risk rises; "
                "fix luxuries, entertainment, or policies."
            )
    return out


def civ6_diplomacy_guidance(snapshot: dict[str, Any]) -> list[str]:
    lines = [
        "Diplomacy: when legal.trade / deal rows list a rival, prefer a clear propose line "
        "(legal.trade.offer.Leader = ...) and answer pending deals with accept/reject/counter shapes.",
        "Soft advice: haggle in private DMs (chat.LeaderName) before or with a formal deal — "
        "explain what you want and what you offer.",
        "chat.all is broadcast posture — funny/original tone is welcome; skip spam when the lobby "
        "is already noisy every turn; keep military secrets in DMs.",
    ]
    inventories = snapshot.get("legal_trade_inventory")
    if isinstance(inventories, list) and inventories:
        lines.append(
            "Per-civ tradeable inventories appear under legal trade / inventory rows when known — "
            "offer only items you can actually give."
        )
    return lines


def collect_civ6_attention_items(snapshot: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for fn in (
        civ6_exploration_attention,
        civ6_low_hp_retreat_attention,
        civ6_focus_fire_attention,
    ):
        note = fn(snapshot)
        if note:
            items.append(note)
    items.extend(civ6_economy_attention(snapshot))
    return items


def append_attack_options_to_unit_line(options: list[str], attack_tokens: list[str]) -> list[str]:
    """Append legal attack tokens onto an existing options list (no `| none`, no duplicate rows)."""
    out = list(options)
    for token in attack_tokens:
        if token and token not in out and token != "none":
            out.append(token)
    return out


def civ6_attack_option_tokens_for_unit(unit_id: str, snapshot: dict[str, Any]) -> list[str]:
    """Build attackTo/(x,y)[+preview] tokens from legal attack_target commands for one unit."""
    tokens: list[str] = []
    previews = snapshot.get("strategic_summary", {})
    preview_rows = []
    if isinstance(previews, dict):
        raw = previews.get("combat_previews")
        if isinstance(raw, list):
            preview_rows = [row for row in raw if isinstance(row, dict)]
    for command in snapshot.get("legal_commands", []) or []:
        if not isinstance(command, dict) or command.get("kind") != "attack_target":
            continue
        fixed = command.get("fixed_arguments") or {}
        if not isinstance(fixed, dict) or fixed.get("unit_id") != unit_id:
            continue
        x, y = fixed.get("target_x"), fixed.get("target_y")
        if x is None or y is None:
            continue
        try:
            xi, yi = int(x), int(y)
        except (TypeError, ValueError):
            continue
        label = f"attackTo/({xi},{yi})"
        for row in preview_rows:
            if row.get("attacker_unit_id") != unit_id:
                continue
            if int(row.get("target_x", -1)) != xi or int(row.get("target_y", -1)) != yi:
                continue
            dmg_e = row.get("damage_to_enemy")
            dmg_s = row.get("damage_to_self")
            pred = row.get("prediction")
            bits = []
            if pred:
                bits.append(str(pred))
            if isinstance(dmg_e, int) and isinstance(dmg_s, int):
                bits.append(f"~{dmg_e}toThem/~{dmg_s}toUs")
            if bits:
                label = f"{label}[{','.join(bits)}]"
            break
        if label not in tokens:
            tokens.append(label)
    return tokens


def settler_present(snapshot: dict[str, Any]) -> bool:
    for unit in snapshot.get("your_units", []) or []:
        if not isinstance(unit, dict):
            continue
        type_id = str(unit.get("unit_type_id") or "")
        if "SETTLER" in type_id:
            return True
    return False
