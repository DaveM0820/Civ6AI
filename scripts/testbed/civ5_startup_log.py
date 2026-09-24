"""Unified startup / autotest trace log (Python + mirrored Lua events)."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

_LOGGERS: dict[str, logging.Logger] = {}


def _mirror_log_dir(lua_log: Path | None) -> Path | None:
    if lua_log is None:
        return None
    return lua_log.parent / "civ5ai" / "autotest"


def startup_log_paths(civ5ai_root: Path, lua_log: Path | None = None) -> list[Path]:
    paths = [civ5ai_root / "autotest" / "startup.log"]
    mirror = _mirror_log_dir(lua_log)
    if mirror is not None:
        paths.append(mirror / "startup.log")
    return paths


def configure_startup_logging(
    civ5ai_root: Path,
    lua_log: Path | None = None,
    *,
    logger_name: str = "civ5ai.startup",
) -> logging.Logger:
    """Attach a file handler writing the same lines to civ5ai + Logs/civ5ai mirrors."""
    logger = logging.getLogger(logger_name)
    if logger_name in _LOGGERS:
        return _LOGGERS[logger_name]
    logger.setLevel(logging.INFO)
    logger.propagate = True
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for path in startup_log_paths(civ5ai_root, lua_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    _LOGGERS[logger_name] = logger
    return logger


def close_startup_logging(logger_name: str = "civ5ai.startup") -> None:
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _LOGGERS.pop(logger_name, None)


def log_event(
    civ5ai_root: Path,
    event: str,
    lua_log: Path | None = None,
    **fields: Any,
) -> None:
    logger = configure_startup_logging(civ5ai_root, lua_log)
    extra = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    message = event if not extra else f"{event} {extra}"
    logger.info(message)


def append_startup_line(civ5ai_root: Path, line: str, lua_log: Path | None = None) -> None:
    text = line.rstrip("\n") + "\n"
    for path in startup_log_paths(civ5ai_root, lua_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


def _lua_log_read_tail(lua_log: Path, tail_bytes: int = 16000) -> str:
    size = lua_log.stat().st_size
    read_size = min(size, max(1024, tail_bytes))
    with lua_log.open("rb") as handle:
        handle.seek(max(0, size - read_size))
        return handle.read().decode("utf-8", errors="replace")


def lua_log_tail_has_pattern(
    lua_log: Path,
    pattern: str,
    *,
    tail_bytes: int = 16000,
) -> bool:
    if not lua_log.is_file():
        return False
    return pattern in _lua_log_read_tail(lua_log, tail_bytes)


def chunk_has_exact_marker(chunk: str, marker: str) -> bool:
    """Find marker in chunk; reject when extra digits follow (turn=1 inside turn=17)."""
    start = 0
    while True:
        idx = chunk.find(marker, start)
        if idx == -1:
            return False
        end = idx + len(marker)
        if end >= len(chunk) or not chunk[end].isdigit():
            return True
        start = idx + 1


def lua_log_tail_has_exact_marker(
    lua_log: Path,
    marker: str,
    *,
    tail_bytes: int = 16000,
) -> bool:
    if not lua_log.is_file():
        return False
    return chunk_has_exact_marker(_lua_log_read_tail(lua_log, tail_bytes), marker)


def wait_for_lua_log_pattern(
    lua_log: Path,
    pattern: str,
    *,
    timeout_seconds: float = 45.0,
    poll_seconds: float = 0.25,
    check_tail_first: bool = True,
    start_offset: int | None = None,
) -> bool:
    if not lua_log.is_file():
        return False
    if check_tail_first and start_offset is None and lua_log_tail_has_pattern(lua_log, pattern):
        return True
    deadline = time.monotonic() + max(0.5, timeout_seconds)
    offset = start_offset if start_offset is not None else lua_log.stat().st_size
    while time.monotonic() < deadline:
        size = lua_log.stat().st_size
        if size < offset:
            offset = 0
        if size > offset:
            with lua_log.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read().decode("utf-8", errors="replace")
                offset = handle.tell()
            if pattern in chunk:
                return True
        time.sleep(poll_seconds)
    return False


def wait_for_lua_log_exact_marker(
    lua_log: Path,
    marker: str,
    *,
    timeout_seconds: float = 45.0,
    poll_seconds: float = 0.25,
    check_tail_first: bool = True,
    start_offset: int | None = None,
) -> bool:
    if not lua_log.is_file():
        return False
    if check_tail_first and start_offset is None and lua_log_tail_has_exact_marker(lua_log, marker):
        return True
    deadline = time.monotonic() + max(0.5, timeout_seconds)
    offset = start_offset if start_offset is not None else lua_log.stat().st_size
    while time.monotonic() < deadline:
        size = lua_log.stat().st_size
        if size < offset:
            offset = 0
        if size > offset:
            with lua_log.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read().decode("utf-8", errors="replace")
                offset = handle.tell()
            if chunk_has_exact_marker(chunk, marker):
                return True
        time.sleep(poll_seconds)
    return False


_CIV6AI_TAIL_MARKERS = (
    "bridge|inbox",
    "bridge|apply",
    "bridge|pulse",
    "autotest|",
    "apply|ok|",
    "end_turn",
)


def tail_lua_log_to_startup(
    civ5ai_root: Path,
    lua_log: Path | None,
    *,
    offset: int = 0,
    max_lines: int = 40,
) -> int:
    """Copy recent CIV6AI-related Lua.log lines into startup.log."""
    if lua_log is None or not lua_log.is_file():
        return offset
    size = lua_log.stat().st_size
    read_offset = offset
    if read_offset > size:
        read_offset = 0
    with lua_log.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(read_offset)
        chunk = handle.read()
        new_offset = handle.tell()
    if not chunk:
        return new_offset
    matched: list[str] = []
    for raw in chunk.splitlines():
        if "CIV6AI|" not in raw:
            continue
        marker = raw.find("CIV6AI|")
        line = raw[marker:].strip()
        payload = line[7:] if line.startswith("CIV6AI|") else line
        if any(token in payload for token in _CIV6AI_TAIL_MARKERS):
            matched.append(f"lua|{payload}")
    if matched:
        tail = matched[-max_lines:]
        for entry in tail:
            append_startup_line(civ5ai_root, entry, lua_log)
    return new_offset


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Civ6 autotest startup trace log")
    parser.add_argument("--civ5ai-root", type=Path, required=True)
    parser.add_argument("--lua-log", type=Path, default=None)
    parser.add_argument("--event", default="startup")
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()
    configure_startup_logging(args.civ5ai_root, args.lua_log)
    fields: dict[str, Any] = {}
    if args.session_id:
        fields["session_id"] = args.session_id
    log_event(args.civ5ai_root, args.event, lua_log=args.lua_log, **fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
