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


def test_api_probe_is_read_only_chunked_and_once():
    import re
    from pathlib import Path
    src = (PRODUCTION.parents[1] / "Gameplay" / "Civ6Ai_Orders.lua").read_text(encoding="utf-8")
    a = src.index("function Civ6Ai_Orders._ProbeNames")
    b = src.index("function Civ6Ai_Orders.OnGameTurnStarted")
    body = src[a:b]
    assert "SetProperty" not in body and "RequestOperation(" not in body
    assert "CreateBuilding(" not in body and "FinishProgress(" not in body
    assert "AddProgress(" not in body and "CreateTradeRoute(" not in body
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("Civ6Ai_Orders={} LOG={} function log(s) LOG[#LOG+1]=s end "
                "function call(o,m,...) local f=o and o[m] if f then return f(o,...) end end")
    lua.execute(body)
    lua.execute("""
      local names = {}
      for i = 1, 45 do names['F' .. string.format('%02d', i)] = function() end end
      local BQ = setmetatable({}, {__index = names})
      local C = {GetBuildQueue = function() return BQ end}
      local cities = {Members = function() local d = false return function() if d then return nil end d = true return 0, C end end}
      Players = {[0] = {IsMajor = function() return true end, GetCities = function() return cities end}}
      Game = {GetCurrentGameTurn = function() return 1 end}
      Civ6Ai_Orders.ProbeApi() Civ6Ai_Orders.ProbeApi()""")
    logs = list(lua.globals().LOG.values())
    bq = [l for l in logs if "obj=BuildQueue" in l and "part=" in l]
    assert len(bq) == 2 and "part=1/2" in bq[0] and "count=45" in bq[0]
    assert any("obj=BuildQueue|callable=" in l for l in logs)
    assert any("obj=CityManager|missing" in l for l in logs)
