"""Lua: the local seat's sweep fill waits for this turn's model reply (game 5 T6 race)."""
import pytest

lupa = pytest.importorskip("lupa")
from sidecar.tests.test_civ6_local_fill_lua import PRODUCTION, STUBS


def _rt(applied):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUBS)
    lua.execute(PRODUCTION.read_text(encoding="utf-8"))
    lua.execute("APPLIED = %s; Civ6Ai_Bridge = {_WasAppliedThisPulse=function() return APPLIED end}" % ("true" if applied else "false"))
    return lua


def test_sweep_fill_held_until_reply_applied():
    lua = _rt(False)
    assert lua.eval("Civ6Ai_Production.FillEmptyQueuesWeighted(0)") == 0
    assert lua.eval("#REQUESTS") == 0
    lua.execute("APPLIED = true")
    assert lua.eval("Civ6Ai_Production.FillEmptyQueuesWeighted(0)") == 1


def test_after_apply_path_not_held():
    lua = _rt(False)
    assert lua.eval("Civ6Ai_Production.FillEmptyQueuesWeighted(0, true)") == 1


def test_hold_bounded():
    lua = _rt(False)
    for _ in range(40):
        assert lua.eval("Civ6Ai_Production.FillEmptyQueuesWeighted(0)") == 0
    assert lua.eval("Civ6Ai_Production.FillEmptyQueuesWeighted(0)") == 1
