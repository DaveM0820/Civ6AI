"""Lua: the autotest research/civic fallback must not overwrite the local seat's model choice."""
import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
AUTOTEST = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Autotest.lua"
APPLY = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Apply.lua"


def _chunk(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def _runtime():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
      TURN = 63; LOCAL = 0; RESEARCHING = -1; SENT = {}
      Game = {GetCurrentGameTurn=function() return TURN end, GetLocalPlayer=function() return LOCAL end}
      Civ6Ai_Util = {Log=function() end}
      Civ6Ai_Autotest = {_LogLine=function() end}
      Civ6Ai_Apply = {_SetResearchTech=function() end, _SetResearchCivic=function() end}
    """)
    at = AUTOTEST.read_text(encoding="utf-8")
    lua.execute(_chunk(at, "Civ6Ai_Autotest.MODEL_CHOICE_WAIT", "function Civ6Ai_Autotest._ClearResearchCivicBlockers"))
    lua.execute(_chunk(at, "function Civ6Ai_Autotest._ClearResearchCivicBlockers", "\nend\n") + "\nend\n")
    ap = APPLY.read_text(encoding="utf-8")
    lua.execute(_chunk(ap, "function Civ6Ai_Apply._ResultSource", "function Civ6Ai_Apply._RecordResult"))
    lua.execute("""
      Civ6Ai_Autotest._PickFallbackTech = function() if RESEARCHING < 0 then return 'TECH_CURRENCY' end end
      Civ6Ai_Autotest._PickFallbackCivic = function() return nil end
      Civ6Ai_Autotest._SetFallback = function(p, kind, args) table.insert(SENT, args.tech_id or args.civic_id); return true, 'sent' end
    """)
    return lua


def test_fallback_held_while_model_choice_in_flight():
    lua = _runtime()
    lua.execute("Civ6Ai_Apply._NoteModelChoices(0, {{kind='set_research_tech', command_id='CMD_research_TECH_SHIPBUILDING'}})")
    lua.execute("Civ6Ai_Autotest._ClearResearchCivicBlockers(0)")
    assert lua.eval("#SENT") == 0
    lua.execute("Civ6Ai_Autotest.ClearModelChoice(0, 'set_research_tech'); RESEARCHING = 5")
    lua.execute("Civ6Ai_Autotest._ClearResearchCivicBlockers(0)")
    assert lua.eval("#SENT") == 0  # model choice landed, slot full: nothing to pick


def test_fallback_fires_when_no_model_choice_or_hold_expires():
    lua = _runtime()
    lua.execute("Civ6Ai_Autotest._ClearResearchCivicBlockers(0)")
    assert lua.eval("SENT[1]") == "TECH_CURRENCY"
    lua = _runtime()
    lua.execute("Civ6Ai_Apply._NoteModelChoices(0, {{kind='set_research_tech', command_id='CMD_research_X'}})")
    for _ in range(41):
        lua.execute("Civ6Ai_Autotest._ClearResearchCivicBlockers(0)")
    assert lua.eval("#SENT") == 1


def test_stale_turn_and_ai_seats_not_held():
    lua = _runtime()
    lua.execute("Civ6Ai_Apply._NoteModelChoices(0, {{kind='set_research_tech', command_id='CMD_research_X'}}); TURN = 64")
    lua.execute("Civ6Ai_Autotest._ClearResearchCivicBlockers(0)")
    assert lua.eval("#SENT") == 1
    lua = _runtime()
    lua.execute("Civ6Ai_Apply._NoteModelChoices(3, {{kind='set_research_tech', command_id='CMD_research_X'}})")
    assert lua.eval("next(Civ6Ai_Autotest._modelChoice)") is None


def test_auto_rows_tagged_auto_fallback():
    lua = _runtime()
    assert lua.eval("Civ6Ai_Apply._ResultSource({command_id='CMD_auto_TECH_CURRENCY'}, 'model')") == "auto_fallback"
    assert lua.eval("Civ6Ai_Apply._ResultSource({command_id='CMD_research_TECH_X'}, nil)") == "model"


@pytest.mark.parametrize("path", [AUTOTEST, APPLY])
def test_lua_files_compile(path):
    lua = lupa.LuaRuntime()
    ok = lua.eval("function(src) local f, err = loadstring and loadstring(src) or load(src); return err end")(path.read_text(encoding="utf-8"))
    assert ok is None
