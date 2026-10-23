"""Char budget for Civ VI seat prompts.

Count compact (Civ V style) runs whenever the empire is large. A second ladder
then shortens lower-priority sections until the text is under the seat's
max_prompt_chars. The attached map image is never removed to save characters.

Protected, in every pass: ATTENTION, WAR, REQUIRED COMMANDS, offered command
rows, and the plan / latest situation lines.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

# Compact when the count is greater than this (units > ~10; cities over a threshold).
UNITS_COMPACT_ABOVE = 10
CITIES_COMPACT_ABOVE = 6
# ~60k tokens at 4 chars/token. Slower calls are acceptable.
MAX_PROMPT_CHARS_DEFAULT = 240000
CHARS_PER_TOKEN = 4.0
CATALOG_KEEP = 4
FOREIGN_CITY_KEEP = 8
CHAT_KEEP = 5
RANKINGS_KEEP = 12

from sidecar.civ6_attention import SECTION as ATTENTION_SECTION

PROTECTED_SECTIONS = frozenset({ATTENTION_SECTION, "WAR", "REQUIRED COMMANDS"})

_HEADER = re.compile(r"^=== (.+) ===\n", re.M)
_THOUGHT_TURN = re.compile(r"^T(\d+)\.(situation|strategy)(?:\.vs\.orders)? = ")
_CATALOG_MORE = re.compile(r"^\+\d+ more$")


def estimate_tokens(text: str) -> int:
    """Same 4 chars/token estimate the context-window budget uses for prose."""
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / CHARS_PER_TOKEN)))


def units_need_compact(count: int) -> bool:
    return count > UNITS_COMPACT_ABOVE


def cities_need_compact(count: int) -> bool:
    return count > CITIES_COMPACT_ABOVE


def resolve_max_prompt_chars(snapshot: dict[str, Any] | None, explicit: int | None = None) -> int:
    """Seat target. Explicit wins, then this snapshot, then seat_runtime config.

    0 disables the size ladder. Count compact still runs.
    """
    if explicit is not None:
        return max(0, int(explicit))
    if isinstance(snapshot, dict):
        advciv = snapshot.get("advciv")
        if isinstance(advciv, dict) and isinstance(advciv.get("max_prompt_chars"), int) and not isinstance(advciv.get("max_prompt_chars"), bool):
            return max(0, int(advciv["max_prompt_chars"]))
    try:
        from sidecar.civ6_config import load_local_config, resolve_seat_prompt_chars

        player_id = None
        if isinstance(snapshot, dict):
            decision = snapshot.get("decision")
            if isinstance(decision, dict):
                player_id = decision.get("player_id")
        return resolve_seat_prompt_chars(load_local_config(), player_id)
    except Exception:
        return MAX_PROMPT_CHARS_DEFAULT


def section_sizes(text: str) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for title, chunk in _split_sections(text):
        if not title:
            continue
        sizes[title] = len(chunk)
    return sizes


def store_report(snapshot: dict[str, Any], report: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        return
    advciv = snapshot.get("advciv")
    if not isinstance(advciv, dict):
        snapshot["advciv"] = {}
        advciv = snapshot["advciv"]
    advciv["prompt_budget"] = report


def metrics_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """turn_metrics fields. Empty when this seat did not build a prompt."""
    if not isinstance(snapshot, dict):
        return {}
    advciv = snapshot.get("advciv")
    report = advciv.get("prompt_budget") if isinstance(advciv, dict) else None
    if not isinstance(report, dict):
        return {}
    return {
        "max_prompt_chars": report.get("max_chars"),
        "prompt_chars_before": report.get("before_chars"),
        "prompt_tokens_before_est": report.get("before_tokens_est"),
        "prompt_tokens_est": report.get("after_tokens_est"),
        "prompt_section_chars": report.get("section_chars") or {},
        "prompt_section_chars_before": report.get("section_chars_before") or {},
        "prompt_compactions": list(report.get("compactions") or []),
        "memory_turns_shown": list(report.get("memory_turns_shown") or []),
        "dropped_turns": list(report.get("dropped_turns") or []),
    }


_SHOWN_TURN = re.compile(r"(?:^|\n)(?:T|memory\.T)(\d+)\.", re.M)


def shown_memory_turns(text: str) -> list[int]:
    return sorted({int(match.group(1)) for match in _SHOWN_TURN.finditer(text or "")})


def make_report(before: str, after: str, limit: int, compactions: list[str]) -> dict[str, Any]:
    shown = shown_memory_turns(after)
    prior = shown_memory_turns(before)
    return {
        "max_chars": limit,
        "before_chars": len(before),
        "after_chars": len(after),
        "before_tokens_est": estimate_tokens(before),
        "after_tokens_est": estimate_tokens(after),
        "section_chars": section_sizes(after),
        "section_chars_before": section_sizes(before),
        "compactions": list(compactions),
        "map_image_kept": True,
        "memory_turns_shown": shown,
        "dropped_turns": [turn for turn in prior if turn not in shown],
    }


def compact_to_budget(text: str, limit: int) -> tuple[str, list[str]]:
    """Shorten lower-priority sections until ``text`` fits, or the ladder ends.

    Order is least necessary first: verbose history, repeated legend, distant
    or unchanged catalogs, long production catalogs, leftover city detail,
    coaching prose, then unit stat lines that are not required to give an order.
    """
    if limit <= 0 or len(text) <= limit:
        return text, []
    fired: list[str] = []
    for name, editor in _PASSES:
        if len(text) <= limit:
            break
        updated = _apply(text, editor)
        if updated != text:
            fired.append(name)
            text = updated
    if len(text) > limit:
        fired.append("still_over_budget")
    return text, fired


def _split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADER.finditer(text))
    if not matches:
        return [("", text)]
    chunks: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        chunks.append(("", text[:matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunks.append((match.group(1), text[match.start():end]))
    return chunks


def _apply(text: str, editor: Callable[[str, list[str]], list[str]]) -> str:
    parts: list[str] = []
    for title, chunk in _split_sections(text):
        if not title or title in PROTECTED_SECTIONS:
            parts.append(chunk)
            continue
        parts.append(_edit_body(chunk, lambda lines, title=title: editor(title, lines)))
    return "".join(parts)


def _edit_body(chunk: str, line_fn: Callable[[list[str]], list[str]]) -> str:
    header, _, rest = chunk.partition("\n")
    trailing = ""
    body = rest
    if body.endswith("\n\n"):
        trailing = "\n\n"
        body = body[:-2]
    elif body.endswith("\n"):
        trailing = "\n"
        body = body[:-1]
    lines = body.split("\n") if body else []
    edited = [line for line in line_fn(lines) if line is not None]
    return header + "\n" + "\n".join(edited) + trailing


def _key(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("***"):
        stripped = stripped.strip("*").strip()
    if " = " not in stripped:
        return ""
    return stripped.split(" = ", 1)[0].strip()


def _value(line: str) -> str:
    stripped = line.strip().strip("*").strip()
    if " = " not in stripped:
        return ""
    return stripped.split(" = ", 1)[1].strip()


def _clip_value(line: str, limit: int) -> str:
    """Keep the wire key and the start of a long thought. The plan line stays whole."""
    key = _key(line)
    value = _value(line)
    if not key or len(value) <= limit:
        return line
    cut = value[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > 40:
        cut = cut[:end + 1]
    return f"{key} = {cut}"


def _history(title: str, lines: list[str]) -> list[str]:
    if title == "MEMORY":
        return _trim_memory(lines)
    if title == "THOUGHTS":
        return _trim_thoughts(lines)
    if title == "OPPONENTS":
        return [line for line in lines if not _key(line).startswith(("history.", "opinion."))]
    return lines


def _trim_memory(lines: list[str]) -> list[str]:
    """Long-term memory is trimmable. Keep pinned rows; drop the rest."""
    pinned: set[str] = set()
    for line in lines:
        key = _key(line)
        if key.endswith(".pin") and _value(line).lower() in {"true", "1", "yes"}:
            pinned.add(key.rsplit(".", 1)[0])
        if key.endswith(".pinned") and _value(line).lower() in {"true", "1", "yes"}:
            pinned.add(key.rsplit(".", 1)[0])
    kept: list[str] = []
    for line in lines:
        key = _key(line)
        if not key:
            kept.append(line)
            continue
        stem = key.rsplit(".", 1)[0] if key.endswith((".pin", ".pinned", ".tier", ".score", ".adjusted")) else key
        if stem in pinned or key in pinned:
            kept.append(line)
            continue
        if key.startswith("memory."):
            continue
        kept.append(line)
    return kept


def _trim_thoughts(lines: list[str]) -> list[str]:
    turns = sorted({int(match.group(1)) for line in lines if (match := _THOUGHT_TURN.match(line.strip()))})
    recent = set(turns[-3:])
    kept: list[str] = []
    for line in lines:
        key = _key(line)
        if key.startswith(("plan.", "situation.", "alert.open.", "promise.")) or key == "identity":
            kept.append(line)
            continue
        match = _THOUGHT_TURN.match(line.strip())
        if match:
            turn = int(match.group(1))
            if turn in recent:
                kept.append(_clip_value(line, 480))
            continue
        if key.startswith(("history.", "remembered.", "milestone.")):
            continue
        kept.append(line)
    return kept


def _legend(title: str, lines: list[str]) -> list[str]:
    if title == "GAME":
        return [line for line in lines if _keep_game_line(line)]
    if title == "RESPONSE INSTRUCTIONS":
        return [_shorten_legend_rule(line) for line in lines]
    return lines


def _keep_game_line(line: str) -> bool:
    if " = " in line or line.startswith("#") or line.startswith("You are "):
        return True
    if "Map axes" in line or "x increases" in line:
        return True
    return len(line) <= 80


def _shorten_legend_rule(line: str) -> str:
    if "white peak" not in line and "impassable to land units until" not in line:
        return line
    return (
        "- Never MoveTo a mountain or a water tile this unit cannot enter, or a tile one of your units already holds. "
        "A rejected move says impassable or no_path. The unit then takes one step toward that destination."
    )


def _distant(title: str, lines: list[str]) -> list[str]:
    if title == "EMPIRE":
        return [_shorten_known_list(line) for line in lines]
    if title == "DIPLOMACY":
        return _cap_chat(_drop_diplomacy_notes(lines))
    if title == "OPPONENTS":
        return _cap_foreign_cities(_drop_distant_opponent_lines(lines))
    if title == "WORLD RANKINGS" and len(lines) > RANKINGS_KEEP:
        return lines[:RANKINGS_KEEP]
    return lines


def _shorten_known_list(line: str) -> str:
    key = _key(line)
    if key not in ("empire.techs.known", "empire.civics.known"):
        return line
    value = _value(line)
    if value in ("", "none") or len(value) < 80:
        return line
    count = len([part for part in value.split(",") if part.strip()])
    return f"{key} = {count} known"


def _drop_diplomacy_notes(lines: list[str]) -> list[str]:
    return [line for line in lines if _key(line) not in ("diplomacy.offer.note", "diplomacy.request.note")]


def _cap_chat(lines: list[str]) -> list[str]:
    chat_indexes = [index for index, line in enumerate(lines) if _key(line).startswith(("chat.public.", "chat.private."))]
    drop = set(chat_indexes[:-CHAT_KEEP]) if len(chat_indexes) > CHAT_KEEP else set()
    return [line for index, line in enumerate(lines) if index not in drop]


def _drop_distant_opponent_lines(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for line in lines:
        key = _key(line)
        if key.endswith(".trades") or key.endswith(".strength"):
            continue
        kept.append(line)
    return kept


def _cap_foreign_cities(lines: list[str]) -> list[str]:
    city_indexes = [index for index, line in enumerate(lines) if _key(line).startswith("city.")]
    if len(city_indexes) <= FOREIGN_CITY_KEEP:
        return lines
    must = set()
    for index in city_indexes:
        value = _value(lines[index]).lower()
        if "capital" in value or re.search(r"\d+/\d+", value):
            must.add(index)
    room = FOREIGN_CITY_KEEP - len(must)
    chosen = set(must)
    for index in city_indexes:
        if index in chosen:
            continue
        if room <= 0:
            continue
        chosen.add(index)
        room -= 1
    return [line for index, line in enumerate(lines) if index not in set(city_indexes) or index in chosen]


def _catalogs(title: str, lines: list[str]) -> list[str]:
    kept: list[str] = []
    for line in lines:
        if _key(line) == "unit.ids" and len(line) > 160:
            continue
        kept.append(_shorten_catalog(line))
    return kept


def _shorten_catalog(line: str) -> str:
    key = _key(line)
    if not key.endswith(".production.catalog"):
        return line
    value = _value(line)
    head = ""
    marker = "THREATENED — defense build list first: "
    if value.startswith(marker):
        head = marker
        value = value[len(marker):]
    parts = [part.strip() for part in value.split("|")]
    parts = [part for part in parts if part and not _CATALOG_MORE.match(part)]
    if len(parts) <= CATALOG_KEEP:
        return line
    hidden = len(parts) - CATALOG_KEEP
    shown = " | ".join(parts[:CATALOG_KEEP])
    return f"{key} = {head}{shown} | +{hidden} more"


def _city_detail(title: str, lines: list[str]) -> list[str]:
    if title != "EMPIRE":
        return lines
    return [line for line in lines if not _drop_city_detail(line)]


def _drop_city_detail(line: str) -> bool:
    key = _key(line)
    if not key or key.startswith(("empire.", "alert.", "units.", "unit.")):
        return False
    value = _value(line)
    if key.endswith(".growth"):
        return "STARVING" not in value
    if key.endswith(".power"):
        return "UNPOWERED" not in value
    if key.endswith(".loyalty"):
        try:
            return int(value) >= 100
        except ValueError:
            return False
    return key.endswith((
        ".buildings", ".districts", ".wonders", ".yields", ".housing",
        ".religion", ".amenities", ".mood",
    ))


def _prose(title: str, lines: list[str]) -> list[str]:
    if title == "ADVICE":
        return [line for line in lines if _keep_advice(line)]
    if title == "DIPLOMACY":
        return [line for line in lines if _keep_diplomacy_prose(line)]
    if title == "OPTIONAL COMMANDS":
        return [line for line in lines if not _drop_optional_preamble(line)]
    return lines


def _keep_advice(line: str) -> bool:
    if not line.strip():
        return True
    low = line.lower()
    return any(token in low for token in (
        "war", "threat", "settler", "required commands", "peace", "enemy", "attack",
    ))


def _keep_diplomacy_prose(line: str) -> bool:
    if " = " in line or line.startswith("#") or len(line) <= 180:
        return True
    low = line.lower()
    return "atwar" in low or " at war" in low


def _drop_optional_preamble(line: str) -> bool:
    text = line.strip()
    return text.startswith((
        "OPTIONAL COMMANDS are encouraged",
        "Issue as many optional",
        "There is no cap.",
        "Use only shapes listed",
        "thought.freethinking = optional",
    ))


def _units_budget(title: str, lines: list[str]) -> list[str]:
    if title != "EMPIRE":
        return lines
    kept: list[str] = []
    for line in lines:
        key = _key(line)
        if key.endswith((".combat", ".promotionReady", ".upgrade", ".maxMovement", ".improve", ".settle")):
            continue
        if key.endswith(".moves") and _value(line) not in {"0"}:
            continue
        kept.append(line)
    return kept


_PASSES: tuple[tuple[str, Callable[[str, list[str]], list[str]]], ...] = (
    ("history", _history),
    ("legend", _legend),
    ("distant", _distant),
    ("catalogs", _catalogs),
    ("city_detail", _city_detail),
    ("prose", _prose),
    ("units_budget", _units_budget),
)
