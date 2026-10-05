"""World-tracker chat is sent as the local network player. Other seats prefix
their leader name; incoming lines parse that prefix back to the real seat."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
CHAT = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Chat.lua"

STUBS = r"""
SENT = {}
Civ6Ai_Util = { Log = function() end, PlayerId = function(p) return "PLAYER_" .. tostring(p) end,
  JoinPath = function(...) return table.concat({...}, "/") end, AppendTextLine = function() end,
  EncodeJsonValue = function() return "{}" end, ScheduleTick = function() end }
Game = { GetLocalPlayer = function() return 0 end, GetCurrentGameTurn = function() return 1 end }
PlayerConfigurations = {
  [0] = { GetLeaderName = function() return "LOC_LEADER_LAUTARO_NAME" end, GetPlayerName = function() return "host" end },
  [1] = { GetLeaderName = function() return "Wilhelmina" end, GetPlayerName = function() return "AI_1" end },
}
Locale = { Lookup = function(s) return s end }
Network = { SendChat = function(text, typ, id) table.insert(SENT, {text=text, typ=typ, id=id}) end }
ChatTargetTypes = { CHATTARGET_ALL = 1, CHATTARGET_PLAYER = 2 }
Civ6Ai_Config = { IsHumanSeat = function() return false end, IsAutotest = function() return false end,
  IsManagedSeat = function() return true end, EnableSinglePlayerChat = function() return true end,
  IsSidecarLive = function() return true end }
Events = nil
UIManager = nil
Controls = nil
ContextPtr = nil
include = function() end
"""


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class ChatWireTextTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.lua.execute(CHAT.read_text(encoding="utf-8"))

    def test_local_seat_sends_plain_text(self):
        self.lua.eval('Civ6Ai_Chat.SendMessage(0, { text = "hello", target = "all" })')
        sent = self.lua.eval("SENT[1].text")
        self.assertEqual("hello", sent)

    def test_ai_seat_prefixes_leader_name(self):
        self.lua.eval('Civ6Ai_Chat.SendMessage(1, { text = "trade routes", target = "all" })')
        sent = self.lua.eval("SENT[1].text")
        self.assertEqual("Wilhelmina: trade routes", sent)

    def test_relay_records_the_named_seat_not_the_network_sender(self):
        self.lua.eval('Civ6Ai_Chat._OnHumanChat(0, -1, "Wilhelmina: trade routes", 1)')
        sender = self.lua.eval("Civ6Ai_Chat.GetPublicEvents()[1].affected_ids[1]")
        body = self.lua.eval("Civ6Ai_Chat.GetPublicEvents()[1].text")
        self.assertEqual("PLAYER_1", sender)
        self.assertEqual("trade routes", body)

    def test_plain_human_line_stays_the_network_sender(self):
        self.lua.eval('Civ6Ai_Chat._OnHumanChat(0, -1, "hello", 1)')
        sender = self.lua.eval("Civ6Ai_Chat.GetPublicEvents()[1].affected_ids[1]")
        body = self.lua.eval("Civ6Ai_Chat.GetPublicEvents()[1].text")
        self.assertEqual("PLAYER_0", sender)
        self.assertEqual("hello", body)


if __name__ == "__main__":
    unittest.main()
