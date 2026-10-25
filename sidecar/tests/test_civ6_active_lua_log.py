"""Lua.log resolution follows the log Civ6 is actually writing (newest mtime)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("scripts", "scripts/testbed"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

from civ6_paths import active_lua_log  # noqa: E402
import live_lua_bridge  # noqa: E402


def _log(path: Path, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_newest_candidate_wins_over_list_order(tmp_path):
    stale = _log(tmp_path / "onedrive" / "Lua.log", 1000)
    live = _log(tmp_path / "local" / "Lua.log", 2000)
    missing = tmp_path / "none" / "Lua.log"
    assert active_lua_log([missing, stale, live]) == live
    assert active_lua_log([missing]) is None


def test_bridge_switches_when_other_log_becomes_active(tmp_path):
    a = _log(tmp_path / "a" / "Lua.log", 1000)
    b = _log(tmp_path / "b" / "Lua.log", 1001)
    assert live_lua_bridge.follow_active_log(a, [a, b]) == a  # within slack
    os.utime(b, (5000, 5000))
    assert live_lua_bridge.follow_active_log(a, [a, b]) == b
    assert live_lua_bridge.follow_active_log(b, [a, b]) == b


def test_start_live_does_not_pin_bridge_log():
    src = (ROOT / "scripts" / "start_live.py").read_text(encoding="utf-8")
    assert '"--lua-log"' not in src
    assert "active_lua_log()" in src
