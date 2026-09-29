"""WORLD RANKINGS prompt section for Civ VI seats (civ6.rankings from the Lua snapshot).

Mirrors the in-game World Rankings screen (Base WorldRankings.lua + Expansion2
replacement): each victory ranks teams by Game.GetVictoryProgressForTeam, then the
screen's tiebreakers (primary stat, secondary stat, score). Every alive major is
listed like the screen does; unmet players are shown as "Unmet Civilization N"
(their numbers are visible on the in-game screen too, their identity is not).
"""
from __future__ import annotations

from typing import Any, Callable

from sidecar import pipeline_v2 as pipeline

_RULESET_LABEL = {
    "EXPANSION2": "Gathering Storm",
    "EXPANSION1": "Rise and Fall",
    "BASE": "base game",
}


def _block(context: dict[str, Any]) -> dict[str, Any]:
    civ6 = context.get("civ6") if isinstance(context, dict) else None
    block = civ6.get("rankings") if isinstance(civ6, dict) else None
    return block if isinstance(block, dict) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "?"
    return str(int(n)) if n == int(n) else f"{n:.1f}"


def _signed(value: float) -> str:
    text = _fmt(abs(value))
    return f"+{text}" if value >= 0 else f"-{text}"


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _names(context: dict[str, Any], players: list[dict[str, Any]]) -> dict[str, str]:
    """player_id -> display label ("You", "Leader (Civ)", or "Unmet Civilization N")."""
    out: dict[str, str] = {}
    unmet = 0
    known = {str(r.get("player_id")): r for r in context.get("known_players", []) or [] if isinstance(r, dict)}
    for row in sorted(players, key=lambda r: str(r.get("player_id"))):
        pid = str(row.get("player_id"))
        if row.get("is_you"):
            out[pid] = "You"
        elif row.get("met") is True:
            leader = row.get("leader_name")
            if not leader and pid in known:
                leader = pipeline._rival_leader_name(known[pid])
            civ = pipeline._readable_id(str(row.get("civilization_id") or ""), "CIVILIZATION_")
            out[pid] = f"{leader or pid} ({civ})" if civ else str(leader or pid)
        else:
            unmet += 1
            out[pid] = f"Unmet Civilization {unmet}"
    return out


def _sorted(players: list[dict[str, Any]], victory: str, primary: Callable[[dict], Any],
            secondary: Callable[[dict], Any]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple:
        progress = row.get("victory_progress")
        prog = _num(progress.get(victory)) if isinstance(progress, dict) else None
        return (
            -(prog if prog is not None else 0.0),
            -(_num(primary(row)) or 0.0),
            -(_num(secondary(row)) or 0.0),
            -(_num(row.get("score")) or 0.0),
            str(row.get("player_id")),
        )
    return sorted(players, key=key)


def _victory_lines(key: str, title: str, players: list[dict[str, Any]], names: dict[str, str],
                   victory: str, primary: Callable[[dict], Any], primary_label: str,
                   secondary: Callable[[dict], Any], secondary_label: str,
                   detail: Callable[[dict], str], enabled: Any) -> list[str]:
    order = _sorted(players, victory, primary, secondary)
    if not order:
        return []
    lines = [f"# {title}" + ("  (victory type disabled in this game)" if enabled is False else "")]
    you_index = next((i for i, r in enumerate(order) if r.get("is_you")), None)
    if you_index is not None:
        you = order[you_index]
        leader = order[0]
        text = f"rank {you_index + 1} of {len(order)}; {detail(you)}"
        yp, lp = _num(primary(you)), _num(primary(leader))
        ys, ls = _num(secondary(you)), _num(secondary(leader))
        if you_index == 0 and len(order) > 1:
            runner = order[1]
            rp, rs = _num(primary(runner)), _num(secondary(runner))
            gaps = []
            if yp is not None and rp is not None and yp != rp:
                gaps.append(f"{_signed(yp - rp)} {primary_label}")
            if ys is not None and rs is not None and ys != rs:
                gaps.append(f"{_signed(ys - rs)} {secondary_label}")
            runner_name = names.get(str(runner.get('player_id')), '?')
            if gaps:
                text += f"; you lead {runner_name} by " + ", ".join(gaps)
            else:
                text += f"; tied with {runner_name} on these stats (ahead on score tiebreak)"
        elif you_index > 0:
            gaps = []
            if yp is not None and lp is not None and yp != lp:
                gaps.append(f"{_signed(yp - lp)} {primary_label}")
            if ys is not None and ls is not None and ys != ls:
                gaps.append(f"{_signed(ys - ls)} {secondary_label}")
            leader_name = names.get(str(leader.get('player_id')), '?')
            if gaps:
                text += f"; leader {leader_name} (you " + ", ".join(gaps) + ")"
            else:
                text += f"; tied with leader {leader_name} on these stats (behind on score tiebreak)"
        lines.append(pipeline._wire_line(f"rankings.{key}.you", text))
    table = " | ".join(
        f"{i}. {names.get(str(r.get('player_id')), '?')}: {detail(r)}" for i, r in enumerate(order, start=1))
    lines.append(pipeline._wire_line(f"rankings.{key}", table))
    return lines


def world_rankings_lines(context: dict[str, Any]) -> list[str]:
    """=== WORLD RANKINGS === body; empty when the snapshot carries no civ6.rankings."""
    block = _block(context)
    players = [p for p in _list(block.get("players")) if isinstance(p, dict)]
    if not players:
        return []
    names = _names(context, players)
    ruleset = str(block.get("ruleset") or "")
    enabled = block.get("victories_enabled") if isinstance(block.get("victories_enabled"), dict) else {}
    xp2 = ruleset == "EXPANSION2"
    dip_needed = block.get("diplomatic_vp_needed")

    def label(pid: Any) -> str:
        return names.get(str(pid), "Unmet Civilization")

    # Space race details only once anyone has a spaceport or a launch (else pure noise).
    space_started = any(p.get("has_spaceport") or (_num(p.get("space_projects_done")) or 0) > 0
                        or (_num(p.get("science_vp")) or 0) > 0 for p in players)

    def science_detail(r: dict) -> str:
        bits = [f"{_fmt(r.get('techs_researched'))} techs", f"{_fmt(r.get('science_yield'))} science/turn"]
        total = _num(r.get("space_projects_total"))
        if space_started:
            if total:
                bits.append(f"space race {_fmt(r.get('space_projects_done'))}/{_fmt(total)} launches")
            if r.get("has_spaceport"):
                bits.append("has spaceport")
            if _num(r.get("science_vp_needed")):
                bits.append(f"{_fmt(r.get('science_vp'))}/{_fmt(r.get('science_vp_needed'))} light-years")
        return ", ".join(bits)

    def culture_detail(r: dict) -> str:
        bits = [f"{_fmt(r.get('tourism'))} tourism/turn", f"{_fmt(r.get('culture_yield'))} culture/turn",
                f"{_fmt(r.get('domestic_tourists'))} domestic tourists",
                f"{_fmt(r.get('foreign_tourists'))}/{_fmt(r.get('tourists_needed'))} foreign tourists needed"]
        if not r.get("is_you"):
            mine, theirs = _num(r.get("your_tourists_visiting_them")), _num(r.get("their_tourists_visiting_you"))
            if mine or theirs:
                bits.append(f"your tourists there {_fmt(mine or 0)}, theirs visiting you {_fmt(theirs or 0)}")
            if r.get("you_culturally_dominant") is True:
                bits.append("you are culturally dominant over them")
            elif r.get("they_culturally_dominant") is True:
                bits.append("they are culturally dominant over you")
        if _num(r.get("turns_until_culture_victory")) is not None:
            bits.append(f"culture victory in {_fmt(r.get('turns_until_culture_victory'))} turns")
        return ", ".join(bits)

    def domination_detail(r: dict) -> str:
        captured = [label(pid) for pid in _list(r.get("captured_capitals"))]
        bits = [f"{_fmt(r.get('military_strength'))} military strength"]
        if captured:
            bits.append(f"holds {len(captured)} foreign original capital(s) ({', '.join(captured)})")
        if r.get("has_original_capital") is False:
            bits.append("no capital yet" if r.get("has_capital") is False else "lost own original capital")
        return ", ".join(bits)

    total_civs = len(players)

    def religion_detail(r: dict) -> str:
        bits = [f"{_fmt(r.get('faith_yield'))} faith/turn",
                f"{_fmt(r.get('cities_following_religion'))} cities follow their religion"]
        founded = r.get("religion_founded")
        if isinstance(founded, dict):
            converted = [label(pid) for pid in _list(r.get("civs_converted"))]
            bits.append(f"founded {founded.get('name') or founded.get('id')}, converted {len(converted)}/{total_civs} civs"
                        + (f" ({', '.join(converted)})" if converted else ""))
        elif r.get("is_you"):
            bits.append("no religion founded")
        majority = r.get("majority_religion")
        if isinstance(majority, dict):
            bits.append(f"majority religion {majority.get('name') or majority.get('id')}")
        return ", ".join(bits)

    def diplo_detail(r: dict) -> str:
        need = f"/{_fmt(dip_needed)}" if _num(dip_needed) else ""
        bits = [f"{_fmt(r.get('diplomatic_vp'))}{need} diplomatic victory points"]
        if _num(r.get("favor")) is not None:
            per_turn = _num(r.get("favor_per_turn"))
            bits.append(f"{_fmt(r.get('favor'))} favor" + (f" ({_signed(per_turn)}/turn)" if per_turn is not None else ""))
        return ", ".join(bits)

    met_count = sum(1 for p in players if p.get("met") is True and not p.get("is_you"))
    unmet_count = sum(1 for p in players if p.get("met") is not True and not p.get("is_you"))
    rules = _RULESET_LABEL.get(ruleset, ruleset or "unknown ruleset")
    lines = [
        f"# Same numbers as the in-game World Rankings screen ({rules}); {total_civs} civs alive, "
        f"{met_count} met, {unmet_count} unmet (shown as Unmet Civilization N, identity hidden). "
        "Ranked like the screen: victory progress, then the listed stats, then score. "
        "Domination = hold every original capital; count 0 unless listed.",
    ]
    lines += _victory_lines("science", "Science victory", players, names, "VICTORY_TECHNOLOGY",
                            lambda r: r.get("techs_researched"), "techs",
                            lambda r: r.get("science_yield"), "science/turn",
                            science_detail, enabled.get("VICTORY_TECHNOLOGY"))
    lines += _victory_lines("culture", "Culture victory (win when your foreign tourists exceed every civ's domestic tourists)",
                            players, names, "VICTORY_CULTURE",
                            lambda r: r.get("tourism"), "tourism/turn",
                            lambda r: r.get("culture_yield"), "culture/turn",
                            culture_detail, enabled.get("VICTORY_CULTURE"))
    lines += _victory_lines("domination", "Domination victory (hold every original capital)", players, names,
                            "VICTORY_CONQUEST",
                            lambda r: r.get("military_strength"), "military strength",
                            lambda r: len(_list(r.get("captured_capitals"))), "capitals",
                            domination_detail, enabled.get("VICTORY_CONQUEST"))
    lines += _victory_lines("religion", "Religious victory (your religion the majority in every civ)", players, names,
                            "VICTORY_RELIGIOUS",
                            lambda r: r.get("cities_following_religion"), "cities following",
                            lambda r: r.get("faith_yield"), "faith/turn",
                            religion_detail, enabled.get("VICTORY_RELIGIOUS"))
    if xp2 or any(_num(p.get("diplomatic_vp")) for p in players):
        lines += _victory_lines("diplomatic", "Diplomatic victory", players, names, "VICTORY_DIPLOMATIC",
                                lambda r: r.get("diplomatic_vp"), "diplomatic points",
                                lambda r: r.get("favor"), "favor",
                                diplo_detail, enabled.get("VICTORY_DIPLOMATIC"))
    else:
        lines.append(pipeline._wire_line(
            "rankings.diplomatic", f"n/a — diplomatic victory and favor need Gathering Storm (this game: {rules})"))
    return lines
