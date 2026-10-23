"""Pure-Python mirror of Civ5Ai_Apply plot_occupied move retry orchestration."""
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple


RETRYABLE_KINDS = frozenset({"move_unit", "attack_target"})


ApplyFn = Callable[[Dict[str, Any]], Tuple[bool, str]]

