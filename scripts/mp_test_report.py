"""Summarize a Civ6Ai multiplayer test from the host's Lua.log.

Usage: python scripts/mp_test_report.py [path/to/Lua.log]

Reads the CIV6AI|orders|... and CIV6AI|mp_test|... lines the test writes and
prints, in plain words, which checks worked, whether the other PC's game
stayed in sync every turn, and anything that needs a look.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KIND_NAMES = {
    1: "model move", 2: "research", 3: "civic", 4: "found city", 5: "skip unit", 6: "fortify",
    7: "model attack", 8: "end AI units' turn", 20: "AI freeze on/off", 40: "ping", 49: "test mode switch",
    50: "API listing", 51: "spawn enemy", 52: "melee step into enemy", 53: "scripted damage",
    54: "scripted production", 55: "scripted farm", 56: "scripted experience", 57: "multi-tile move",
    58: "combat probe (native routes)", 59: "late damage check", 60: "resolved attack (real route)", 61: "API survey", 62: "production steering", 63: "forced build strategy", 64: "build priorities",
}

FIELD = re.compile(r"(\w+)=([^|]*)")


def fields(line: str) -> dict[str, str]:
    return dict(FIELD.findall(line))


def default_log() -> Path | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from civ6_paths import lua_log_candidates  # type: ignore

        for p in lua_log_candidates():
            if p.is_file():
                return p
    except Exception:
        pass
    return None


def summarize(text: str) -> str:
    results, syncs, notes, turns = [], [], [], []
    for raw in text.splitlines():
        idx = raw.find("CIV6AI|")
        if idx < 0:
            continue
        line = raw[idx:]
        if line.startswith("CIV6AI|orders|result|"):
            results.append(fields(line))
        elif line.startswith("CIV6AI|orders|sync|"):
            syncs.append(fields(line))
        elif line.startswith("CIV6AI|orders|turn|"):
            turns.append(fields(line))
        elif line.startswith("CIV6AI|orders|introspect|note") or line.startswith("CIV6AI|orders|handler_error"):
            notes.append(line)
        elif line.startswith("CIV6AI|mp_test|") and ("swap|" in line or "step_error" in line or "no_" in line):
            notes.append(line)
    out = []
    mism = [s for s in syncs if not s.get("verdict", "").startswith("match")]
    if not syncs:
        out.append("SYNC: no reports from the other PC were seen. The test may not have got past turn 1.")
    elif mism:
        first = mism[0]
        out.append(f"SYNC: the games went OUT OF SYNC. First mismatch at turn {first.get('turn')} "
                   f"(from player {first.get('from')}: {first.get('verdict')}).")
    else:
        t = sorted({int(s["turn"]) for s in syncs if s.get("turn", "").lstrip("-").isdigit()})
        out.append(f"SYNC: the other PC matched on every reported turn ({len(t)} turns, {t[0]} to {t[-1]}).")
    out.append("")
    out.append("CHECKS (latest result per kind):")
    by_kind: dict[int, list[dict]] = {}
    for r in results:
        try:
            by_kind.setdefault(int(r.get("kind", "0")), []).append(r)
        except ValueError:
            pass
    for kind in sorted(by_kind):
        rows = by_kind[kind]
        ok = sum(1 for r in rows if r.get("ok") == "true")
        last = rows[-1]
        name = KIND_NAMES.get(kind, f"kind {kind}")
        out.append(f"  {name}: {ok}/{len(rows)} worked; last: ok={last.get('ok')} {last.get('reason', '')}")
    stale = [r for r in results if r.get("reason", "").startswith("stale_turn")]
    if stale:
        out.append(f"  stale orders refused: {len(stale)} (expected at least 1)")
    if notes:
        out.append("")
        out.append("NOTES:")
        out.extend("  " + n for n in notes[-20:])
    return "\n".join(out)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else default_log()
    if path is None or not path.is_file():
        print("Lua.log not found; pass its path.")
        return 1
    print(summarize(path.read_text(encoding="utf-8", errors="replace")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
