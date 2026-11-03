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


def _pulse_turn_src():
    import re
    from pathlib import Path
    src = (PRODUCTION.parent / "Civ6Ai_InGame.lua").read_text(encoding="utf-8")
    m = re.search(r"function Civ6Ai_InGame\._PulseTurn\(playerID\).*?\nend", src, re.S)
    assert m
    return m.group(0)


def _pulse_rt(applied):
    lua = _rt(applied)
    lua.execute("Civ6Ai_Bridge.RunTurnPulse = function() end; Civ6Ai_InGame = {}")
    lua.execute(_pulse_turn_src())
    return lua


def test_pulse_that_only_sent_request_does_not_bypass_hold():
    lua = _pulse_rt(False)
    lua.execute("Civ6Ai_InGame._PulseTurn(0)")
    assert lua.eval("#REQUESTS") == 0


def test_pulse_that_applied_reply_fills_immediately():
    lua = _pulse_rt(True)
    lua.execute("Civ6Ai_InGame._PulseTurn(0)")
    assert lua.eval("#REQUESTS") == 1
