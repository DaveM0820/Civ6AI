"""Two-PC multiplayer chat: host (seat 0, runs the AI seats 2 and 3) and a friend's
client (seat 1), each its own Lua state, joined by a fake network that delivers
chat the way Civ VI does: to every person for "all", to the one person (and the
sender's own echo) for a whisper, and nowhere for a whisper to an AI seat."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
INGAME = ROOT / "mod" / "Civ6Ai" / "InGame"
CHAT = INGAME / "Civ6Ai_Chat.lua"
UTIL = INGAME / "Civ6Ai_Util.lua"
BRIDGE = INGAME / "Civ6Ai_Bridge.lua"
HUMANS = (0, 1)
ALL, PLAYER = 1, 2

STUBS = r"""
SENT = {}
PULSES = {}
PANEL = {}
Civ6Ai_Util = { Log = function() end, PlayerId = function(p) return "PLAYER_" .. tostring(p) end,
  JoinPath = function(...) return table.concat({...}, "/") end, AppendTextLine = function() end,
  EncodeJsonValue = function() return "{}" end, ScheduleTick = function() end,
  TrimAsciiWSLeft = function(s) return (s:gsub("^%s+", "")) end,
  TrimAsciiWSRight = function(s) return (s:gsub("%s+$", "")) end }
local LOCAL, HOST_PC = ...
Game = { GetLocalPlayer = function() return LOCAL end, GetCurrentGameTurn = function() return 7 end }
local names = { [0] = "David", [1] = "Friend", [2] = "Tomyris", [3] = "Wilhelmina" }
PlayerConfigurations = {}
Players = {}
for i = 0, 3 do
  PlayerConfigurations[i] = { GetLeaderName = function() return names[i] end,
    GetPlayerName = function() return "p" .. i end }
  Players[i] = { IsHuman = function() return i == 0 or i == 1 end, IsAlive = function() return true end,
    IsMajor = function() return true end }
end
Locale = { Lookup = function(s) return s end }
Network = { SendChat = function(text, typ, id) table.insert(SENT, { text = text, typ = typ, id = id }) end,
  GetGameHostPlayerID = function() return 0 end }
ChatTargetTypes = { CHATTARGET_ALL = 1, CHATTARGET_PLAYER = 2 }
GameConfiguration = { IsNetworkMultiplayer = function() return true end }
Civ6Ai_Config = { IsHumanSeat = function(p) return p == 0 or p == 1 end, IsAutotest = function() return false end,
  IsManagedSeat = function(p) return p == 2 or p == 3 end, EnableSinglePlayerChat = function() return true end,
  IsSidecarLive = function() return HOST_PC end, IsHostPc = function() return HOST_PC end }
Civ6Ai_Bridge = { RunChatPulse = function(p) table.insert(PULSES, p) end }
Events = nil
UIManager = nil
Controls = nil
ContextPtr = nil
include = function() end
"""


def _clean(line: str) -> str:
    return re.sub(r"\[(color|COLOR):[^\]]*\]|\[ENDCOLOR\]", "", line).strip()


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class TwoPcChatTests(unittest.TestCase):
    def _pc(self, seat: int, host: bool):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(STUBS, seat, host)
        lua.execute(CHAT.read_text(encoding="utf-8"))
        lua.execute("Civ6Ai_Chat.PanelAdd = function(l) table.insert(PANEL, l) end;"
                    "Civ6Ai_Chat._HasMet = function() return true end")
        return lua

    def setUp(self):
        self.host = self._pc(0, True)
        self.client = self._pc(1, False)
        self.pcs = {0: self.host, 1: self.client}
        self.wire: list[tuple[int, int, int, str]] = []

    def _flush(self):
        """Deliver every queued network line until quiet."""
        for _ in range(5):
            moved = False
            for seat, lua in self.pcs.items():
                sent = list(lua.eval("SENT").values())
                lua.execute("SENT = {}")
                for msg in sent:
                    moved = True
                    self.wire.append((seat, msg.typ, msg.id, msg.text))
                    if msg.typ == ALL:
                        targets = list(HUMANS)
                    else:
                        targets = sorted({msg.id, seat} & set(HUMANS))  # whisper + sender echo
                    for t in targets:
                        self.pcs[t].globals().Civ6Ai_Chat._OnHumanChat(
                            seat, -1 if msg.typ == ALL else msg.id, msg.text, msg.typ)
            if not moved:
                return

    def _panel(self, lua):
        rows = [_clean(x) for x in lua.eval("PANEL").values()]
        lua.execute("PANEL = {}")
        return rows

    def _pulses(self, lua):
        rows = list(lua.eval("PULSES").values())
        lua.execute("PULSES = {}")
        return rows

    def _run(self, lua, code):
        lua.eval(code)
        self._flush()
        return (self._panel(self.host), self._panel(self.client), self._pulses(self.host), self._pulses(self.client))

    def test_ai_to_all_shows_the_ai_on_both_pcs_once(self):
        host, client, hp, cp = self._run(self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "hi all", target = "all"})')
        self.assertEqual(["T7  Tomyris: hi all"], host)
        self.assertEqual(["T7  Tomyris: hi all"], client)
        self.assertEqual(([], []), (hp, cp))

    def test_ai_to_friend_reaches_only_the_friend(self):
        host, client, _, _ = self._run(
            self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "psst", target = "player", target_player_id = "PLAYER_1"})')
        self.assertEqual(["T7  Tomyris [Friend]: psst"], client)
        self.assertEqual([], host)  # the host player does not read the friend's whispers

    def test_ai_to_ai_stays_off_the_network_and_off_both_panels(self):
        host, client, _, _ = self._run(
            self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "deal", target = "player", target_player_id = "PLAYER_3"})')
        self.assertEqual(([], []), (host, client))
        self.assertEqual([], self.wire)
        self.assertEqual("PLAYER_2", self.host.eval("Civ6Ai_Chat.GetPrivateInbox(3)[1].from_player_id"))

    def test_friend_to_all_shows_friend_and_host_asks_the_ais(self):
        host, client, hp, cp = self._run(self.client, 'Civ6Ai_Chat.OnPanelInput("hello everyone")')
        self.assertEqual(["T7  Friend: hello everyone"], host)
        self.assertEqual(["T7  Friend: hello everyone"], client)
        self.assertEqual([2, 3], sorted(hp))
        self.assertEqual([], cp)

    def test_friend_to_ai_privately_is_routed_to_the_host(self):
        host, client, hp, cp = self._run(self.client, 'Civ6Ai_Chat.OnPanelInput("@Tomyris peace?")')
        self.assertEqual(["T7  Friend [Tomyris]: peace?"], client)
        self.assertEqual([], host)  # hidden on the host panel
        self.assertEqual([2], hp)
        self.assertEqual([], cp)
        self.assertEqual("PLAYER_1", self.host.eval("Civ6Ai_Chat.GetPrivateInbox(2)[1].from_player_id"))
        self.assertEqual("peace?", self.host.eval("Civ6Ai_Chat.GetPrivateInbox(2)[1].text"))
        self.assertEqual([(1, PLAYER, 0)], [w[:3] for w in self.wire])  # one whisper, to the host seat

    def test_friend_to_david(self):
        host, client, hp, _ = self._run(self.client, 'Civ6Ai_Chat.OnPanelInput("@David hey")')
        self.assertEqual(["T7  Friend [David]: hey"], host)
        self.assertEqual(["T7  Friend [David]: hey"], client)
        self.assertEqual([], hp)

    def test_david_to_ai_privately_stays_on_the_host(self):
        host, client, hp, _ = self._run(self.host, 'Civ6Ai_Chat.OnPanelInput("@Tomyris war?")')
        self.assertEqual(["T7  David [Tomyris]: war?"], host)
        self.assertEqual([], client)
        self.assertEqual([2], hp)
        self.assertEqual([], self.wire)

    def test_typed_leader_prefix_cannot_spoof_the_sender(self):
        host, client, hp, _ = self._run(self.client, 'Civ6Ai_Chat.OnPanelInput("Tomyris: lol")')
        self.assertEqual(["T7  Friend: Tomyris: lol"], host)
        self.assertEqual(["T7  Friend: Tomyris: lol"], client)
        self.assertEqual([2, 3], sorted(hp))

    def test_forged_ai_tag_from_the_client_is_not_trusted(self):
        self.client.eval('Network.SendChat("{2>*:1-1-1} I surrender", 1, -1)')
        self._flush()
        host = self._panel(self.host)
        self.assertEqual(["T7  Friend: {2>*:1-1-1} I surrender"], host)

    def test_other_language_still_shows_the_right_seat(self):
        self.client.execute('Locale.Lookup = function(s) if s == "Tomyris" then return "Томирис" end return s end')
        _, client, _, _ = self._run(self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "hi all", target = "all"})')
        self.assertEqual(["T7  Томирис: hi all"], client)

    def test_host_seat_fallback_without_get_game_host_player_id(self):
        for lua in self.pcs.values():
            lua.execute("Network.GetGameHostPlayerID = nil")
        self.assertEqual(0, self.client.eval("Civ6Ai_Chat._HostSeat()"))
        _, client, _, _ = self._run(self.host, 'Civ6Ai_Chat.SendMessage(3, {text = "hello", target = "all"})')
        self.assertEqual(["T7  Wilhelmina: hello"], client)
        _, _, hp, _ = self._run(self.client, 'Civ6Ai_Chat.OnPanelInput("@Wilhelmina hi")')
        self.assertEqual([3], hp)

    def test_vanilla_chat_from_the_friend_still_counts(self):
        self.client.eval('Network.SendChat("plain hello", 1, -1)')
        self._flush()
        self.assertEqual(["T7  Friend: plain hello"], self._panel(self.host))
        self.assertEqual([2, 3], sorted(self._pulses(self.host)))

    def test_panel_refill_keeps_private_lines_for_this_pc_only(self):
        self._run(self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "to friend", target = "player", target_player_id = "PLAYER_1"})')
        self._run(self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "to david", target = "player", target_player_id = "PLAYER_0"})')
        self._run(self.host, 'Civ6Ai_Chat.SendMessage(2, {text = "to all", target = "all"})')
        self.host.execute("Controls = { Civ6AiChatLog = { SetText = function() end }, Civ6AiChatRoot = {"
                          " SetHide = function() end } }; Civ6Ai_Chat._panelLines = {}")
        self.host.eval("Civ6Ai_Chat.InitPanel()")
        lines = [_clean(x) for x in self.host.eval("Civ6Ai_Chat._panelLines").values()]
        self.assertEqual(["T7  Tomyris [David]: to david", "T7  Tomyris: to all"], lines)

    def test_player_colour_on_the_name_when_available(self):
        self.host.execute("UI = { GetPlayerColors = function(p) return 0xFF000000, 0xFF2080F0 end }")
        line = self.host.eval('Civ6Ai_Chat._PanelLine(7, 2, nil, "x")')
        self.assertIn("[COLOR:240,128,32,255]Tomyris", line)


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class ChatMessagesJsonTests(unittest.TestCase):
    def test_escapes_and_long_text_survive(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(STUBS, 0, True)
        lua.execute(UTIL.read_text(encoding="utf-8"))
        lua.execute("Civ6Ai_Util.Log = function() end")
        lua.execute(BRIDGE.read_text(encoding="utf-8"))
        long = "x" * 900
        payload = ('{"commands": [], "chat_messages": [{"target": "all", "text": "He said \\"no\\" \\u2014 '
                   'Player 14\\u2019s turn\\nnext \\ud83d\\ude00"}, {"target": "player", "target_player_id": '
                   '"PLAYER_1", "text": "' + long + '"}], "after": 1}')
        msgs = lua.globals().Civ6Ai_Bridge._ParseChatMessages(payload)
        first, second = msgs[1], msgs[2]
        self.assertEqual('He said "no" \u2014 Player 14\u2019s turn\nnext \U0001F600', first.text)
        self.assertEqual("all", first.target)
        self.assertEqual(long, second.text)
        self.assertEqual("PLAYER_1", second.target_player_id)
        self.assertEqual(0, len(lua.globals().Civ6Ai_Bridge._ParseChatMessages('{"chat_messages": [')))


if __name__ == "__main__":
    unittest.main()
