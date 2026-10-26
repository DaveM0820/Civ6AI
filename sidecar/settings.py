"""One place for sidecar environment settings.

Canonical names are CIV6AI_*. The old CIV4AI_/CIV5AI_/CIV5_ names still work as
aliases; the first one set wins, canonical first, and a legacy hit is logged
once per name.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

# canonical -> legacy aliases, in lookup order
ALIASES: dict[str, tuple[str, ...]] = {
    "CIV6AI_MODEL_PROVIDER": ("CIV4AI_MODEL_PROVIDER",),
    "CIV6AI_OPENAI_REASONING_EFFORT": ("CIV4AI_OPENAI_REASONING_EFFORT",),
    "CIV6AI_GEMINI_API": ("CIV4AI_GEMINI_API",),
    "CIV6AI_DISABLE_MODEL_FALLBACK": ("CIV4AI_DISABLE_MODEL_FALLBACK",),
    "CIV6AI_MEMORY_DIR": ("CIV5AI_MEMORY_DIR",),
    # wire / prompt
    "CIV6AI_COMPACT_LEGAL_WIRE": ("CIV4AI_COMPACT_LEGAL_WIRE",),
    "CIV6AI_COMPACT_SITUATION_WIRE": ("CIV4AI_COMPACT_SITUATION_WIRE",),
    "CIV6AI_WIRE_MAX_UNIT_DETAIL": ("CIV4AI_WIRE_MAX_UNIT_DETAIL",),
    "CIV6AI_PROMPT_DIPLOMACY_BIAS": ("CIV4AI_PROMPT_DIPLOMACY_BIAS",),
    "CIV6AI_THOUGHT_MILESTONES": ("CIV4AI_THOUGHT_MILESTONES",),
    "CIV6AI_THOUGHT_MAX_CHARS": ("CIV4AI_THOUGHT_MAX_CHARS",),
    "CIV6AI_CHAT_MAX_MESSAGES": ("CIV4AI_CHAT_MAX_MESSAGES",),
    "CIV6AI_CHAT_MIN_MESSAGES": ("CIV4AI_CHAT_MIN_MESSAGES",),
    "CIV6AI_CHAT_HISTORY_MAX": ("CIV4AI_CHAT_HISTORY_MAX",),
    "CIV6AI_PLAYER_HISTORY_MAX_CHARS": ("CIV4AI_PLAYER_HISTORY_MAX_CHARS",),
    "CIV6AI_PLAYER_OPINION_MAX_CHARS": ("CIV4AI_PLAYER_OPINION_MAX_CHARS",),
    # map images
    "CIV6AI_MAP_IMAGE_CADENCE": ("CIV4AI_MAP_IMAGE_CADENCE",),
    "CIV6AI_MAP_TILE_PX": ("CIV4AI_MAP_TILE_PX",),
    "CIV6AI_MAP_MAX_VIEWPORT_TILES": ("CIV4AI_MAP_MAX_VIEWPORT_TILES",),
    "CIV6AI_MAP_MAX_COORD_CELLS": ("CIV4AI_MAP_MAX_COORD_CELLS",),
    "CIV6AI_MAP_MAX_CANVAS_PX": ("CIV4AI_MAP_MAX_CANVAS_PX",),
    # One name per image size; the CIV5AI_ and bare CIV5_ spellings were duplicates.
    "CIV6AI_OVERVIEW_MODEL_IMAGE_SIZE": ("CIV5AI_OVERVIEW_MODEL_IMAGE_SIZE", "CIV5_OVERVIEW_MODEL_IMAGE_SIZE"),
    "CIV6AI_TACTICAL_MODEL_IMAGE_SIZE": ("CIV5AI_TACTICAL_MODEL_IMAGE_SIZE", "CIV5_TACTICAL_MODEL_IMAGE_SIZE"),
    "CIV6AI_FOCUS_MODEL_IMAGE_SIZE": ("CIV5AI_FOCUS_MODEL_IMAGE_SIZE", "CIV5_FOCUS_MODEL_IMAGE_SIZE"),
    # context budget
    "CIV6AI_THINKING_PARAGRAPH_TOKENS": ("CIV5AI_THINKING_PARAGRAPH_TOKENS", "CIV4AI_THINKING_PARAGRAPH_TOKENS"),
    "CIV6AI_CONTENT_BLOCK_TOKENS": ("CIV5AI_CONTENT_BLOCK_TOKENS", "CIV4AI_CONTENT_BLOCK_TOKENS"),
    "CIV6AI_CONTEXT_RESERVE_TOKENS": ("CIV5AI_CONTEXT_RESERVE_TOKENS", "CIV4AI_CONTEXT_RESERVE_TOKENS"),
    "CIV6AI_CONTEXT_RESERVE_RATIO": ("CIV5AI_CONTEXT_RESERVE_RATIO", "CIV4AI_CONTEXT_RESERVE_RATIO"),
    "CIV6AI_MODEL_CONTEXT": ("CIV5AI_MODEL_CONTEXT", "CIV4AI_MODEL_CONTEXT", "CIV5AI_CONTEXT_LIMIT", "CIV4AI_CONTEXT_LIMIT"),
    # Civ IV proof-turn harness
    "CIV6AI_PROOF_COMMAND_ID": ("CIV4AI_PROOF_COMMAND_ID",),
    "CIV6AI_PROOF_COMMAND_KIND": ("CIV4AI_PROOF_COMMAND_KIND",),
}

_warned: set[str] = set()


def names(canonical: str) -> tuple[str, ...]:
    return (canonical, *ALIASES.get(canonical, ()))


def get(canonical: str, default: str | None = None, *, skip_empty: bool = False) -> str | None:
    """Value of the first set name (canonical, then aliases), else ``default``.

    ``skip_empty`` treats an empty value as unset, matching ``a or b`` chains.
    """
    for name in names(canonical):
        value = os.environ.get(name)
        if value is None or (skip_empty and not value):
            continue
        if name != canonical and name not in _warned:
            _warned.add(name)
            _log.info("env %s is deprecated; use %s", name, canonical)
        return value
    return default


# Typed knobs with defaults. One row per tunable so callers never parse env by hand.
INT_DEFAULTS: dict[str, tuple[int, int, int]] = {
    # name: (default, min, max)
    # Turns a seat waits before chatting the same recipient again (0 = no cadence gate).
    # A real event with that recipient (war, deal, denouncement, a DM to answer) skips the wait.
    "CIV6AI_CHAT_RECIPIENT_COOLDOWN_TURNS": (0, 0, 50),
    # Public chat.all gets its own, longer wait.
    "CIV6AI_CHAT_PUBLIC_COOLDOWN_TURNS": (0, 0, 50),
    # How many turns back a non-chat diplomatic event still counts as "new" for the gate.
    "CIV6AI_CHAT_EVENT_WINDOW_TURNS": (1, 0, 10),
    # Per-seat model escalation (civ6_escalation). A struggle signal fires when at least
    # this percent of last turn's orders were rejected, failed or dropped.
    "CIV6AI_ESCALATION_FAIL_PERCENT": (40, 1, 100),
    # At or above this share the fail-share signal counts two points (enough to step up alone).
    "CIV6AI_ESCALATION_SEVERE_FAIL_PERCENT": (70, 1, 100),
    # Orders last turn below this count never fire the fail-share signal (too few to judge).
    "CIV6AI_ESCALATION_MIN_ORDERS": (3, 1, 100),
    # Units idle on the same tile for this many turns or more ...
    "CIV6AI_ESCALATION_IDLE_TURNS": (3, 1, 50),
    # ... and at least this many of them fire the idle signal.
    "CIV6AI_ESCALATION_IDLE_UNITS": (3, 1, 100),
    # Signals (fail share, repeat rejections, idle units, stale situation, oscillation) needed to step up one rung.
    "CIV6AI_ESCALATION_SIGNALS": (2, 1, 5),
    # Turns with fewer signals than that before stepping back down one rung.
    "CIV6AI_ESCALATION_CLEAN_TURNS": (3, 1, 50),
    # Spend cap per seat per session on escalated turns, in US cents. Over it the seat stays on tier 0.
    "CIV6AI_ESCALATION_COST_CAP_CENTS": (200, 0, 100000),
    # After an escalated call on turn T the seat stays on its tier-0 model until turn T+N,
    # whatever the signals say. 0 turns the cooldown off.
    "CIV6AI_ESCALATION_COOLDOWN_TURNS": (10, 0, 1000),
    # thought.situation token overlap (percent) with the previous turn that counts as a rewrite.
    "CIV6AI_STALE_SITUATION_PERCENT": (60, 1, 100),
    # Same-reason rejections of one order before the prompt lists that unit's legal moves.
    "CIV6AI_REPEAT_LEGAL_MOVES_AFTER": (3, 1, 20),
    # Live watchdog stall restarts (scripts/testbed/civ6_stall_restart.py).
    # Minutes a seat's snapshot may wait unanswered with no pipeline activity.
    "CIV6AI_WATCHDOG_STALL_MINUTES": (8, 2, 120),
    # Consecutive sidecar failures per seat that count as "failing" ...
    "CIV6AI_WATCHDOG_FAIL_COUNT": (2, 1, 50),
    # ... for at least this percent of seats.
    "CIV6AI_WATCHDOG_FAIL_SEAT_PERCENT": (60, 1, 100),
    # Minimum minutes between two automatic restarts.
    "CIV6AI_WATCHDOG_RESTART_GAP_MINUTES": (10, 1, 240),
    # Automatic restarts allowed per game turn.
    "CIV6AI_WATCHDOG_MAX_RESTARTS_PER_TURN": (3, 0, 20),
}


def get_int(canonical: str) -> int:
    """Clamped int for a name in INT_DEFAULTS; a bad or missing value gives the default."""
    default, lo, hi = INT_DEFAULTS[canonical]
    raw = get(canonical, None, skip_empty=True)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))
