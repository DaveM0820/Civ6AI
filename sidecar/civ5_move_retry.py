"""Pure-Python mirror of Civ5Ai_Apply plot_occupied move retry orchestration."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


RETRYABLE_KINDS = frozenset({"move_unit", "attack_target"})


def is_plot_occupied_retryable_kind(kind: Optional[str]) -> bool:
    return kind in RETRYABLE_KINDS


def count_plot_occupied_retryable(commands: Sequence[Dict[str, Any]] | None) -> int:
    if not commands:
        return 0
    return sum(1 for c in commands if c and is_plot_occupied_retryable_kind(c.get("kind")))


def move_retry_max_passes(commands: Sequence[Dict[str, Any]] | None) -> Tuple[int, int]:
    move_like = count_plot_occupied_retryable(commands)
    max_passes = move_like
    if max_passes < 1:
        max_passes = 1
    if max_passes > 32:
        max_passes = 32
    return max_passes, move_like


def command_unit_id_for_log(command: Optional[Dict[str, Any]]) -> str:
    if not command:
        return ""
    args = command.get("arguments") or {}
    if args.get("unit_id") is not None:
        return str(args["unit_id"])
    return str(command.get("command_id") or "")


ApplyFn = Callable[[Dict[str, Any]], Tuple[bool, str]]


def apply_with_plot_occupied_retries(
    commands: Sequence[Dict[str, Any]],
    apply_fn: ApplyFn,
) -> List[str]:
    """
    Mirror of Civ5Ai_Apply._ApplyDecisionImpl move-retry loop (minus game side effects).

    apply_fn(command) -> (success, reason). reason \"plot_occupied\" on failure defers
    retryable kinds.
    """
    lines: List[str] = []
    pending = list(commands)
    max_passes, move_like = move_retry_max_passes(commands)
    budget = f"apply|move_retry_budget|move_like={move_like}|max_passes={max_passes}"
    lines.append(budget)

    for pass_num in range(1, max_passes + 1):
        retry: List[Dict[str, Any]] = []
        pass_successes = 0
        pass_tried = 0
        for command in pending:
            pass_tried += 1
            kind = command.get("kind")
            unit_log = command_unit_id_for_log(command)
            cmd_id = command.get("command_id")
            success, reason = apply_fn(command)
            if success:
                soft_skip = reason in (
                    "automation_soft_skip_no_moves",
                    "found_soft_skip_city_already_here",
                )
                if soft_skip:
                    lines.append(f"apply|skip|{kind}|{reason}|{cmd_id}")
                else:
                    pass_successes += 1
                    line = f"apply|ok|{kind}|{cmd_id}"
                    if pass_num > 1:
                        line = f"{line}|pass={pass_num}|unit={unit_log}|retry"
                    lines.append(line)
            elif reason == "plot_occupied" and is_plot_occupied_retryable_kind(kind):
                retry.append(command)
                line = f"apply|defer|{kind}|plot_occupied|pass={pass_num}|unit={unit_log}"
                if cmd_id is not None:
                    line = f"{line}|{cmd_id}"
                lines.append(line)
            else:
                line = f"apply|fail|{kind}|{reason}"
                if cmd_id is not None:
                    line = f"{line}|{cmd_id}"
                lines.append(line)

        if pass_num > 1 or retry:
            lines.append(
                f"apply|retry_pass|pass={pass_num}|tried={pass_tried}"
                f"|ok={pass_successes}|still_deferred={len(retry)}"
            )

        pending = retry
        if not pending:
            break
        if pass_num == max_passes:
            break
        if pass_num > 1 and pass_successes == 0:
            break

    for command in pending:
        kind = command.get("kind")
        unit_log = command_unit_id_for_log(command)
        cmd_id = command.get("command_id")
        line = f"apply|fail|{kind}|plot_occupied|unit={unit_log}"
        if cmd_id is not None:
            line = f"{line}|{cmd_id}"
        lines.append(line)
    return lines
