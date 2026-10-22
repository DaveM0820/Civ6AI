"""Local-seat attacks use the same resolver as AI seats; policy apply matches GovernmentScreen."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    import lupa
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    lupa = None
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
APPLY = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Apply.lua"
SNAPSHOT = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Snapshot.lua"


def _apply(extra: str = ""):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("Civ6Ai_Util = { Log = function() end, ScheduleTick = function(fn) end }")
    lua.execute(APPLY.read_text(encoding="utf-8"))
    lua.execute("Civ6Ai_Apply._RecordResult = function() end")
    if extra:
        lua.execute(extra)
    return lua


ATTACK_ENV = r"""
CALLS = {}
REQUESTS = {}
ATTACKS = {}
UnitOperationTypes = {
  MOVE_TO = 1, RANGE_ATTACK = 2, AIR_ATTACK = 3, COASTAL_RAID = 4,
  PARAM_X = "x", PARAM_Y = "y", PARAM_MODIFIERS = "m",
}
UnitOperationMoveModifiers = { NONE = 0, ATTACK = 4, MOVE_IGNORE_UNEXPLORED_DESTINATION = 8 }
UnitManager = {
  CanStartOperation = function(...)
    local n = select("#", ...)
    local unit, op, plot, params, fifth = ...
    table.insert(CALLS, { n = n, op = op, fifth = fifth, params = type(params) })
    if n >= 5 then return false end
    if op == UnitOperationTypes.RANGE_ATTACK and type(params) == "table" then return true end
    return false
  end,
  RequestOperation = function(unit, op, params)
    table.insert(REQUESTS, { op = op })
    return true
  end,
}
Game = { GetLocalPlayer = function() return 0 end }
GameConfiguration = { IsNetworkMultiplayer = function() return false end }
local unit = { id = 5, typ = 0 }
function unit:GetID() return self.id end
function unit:GetType() return self.typ end
function unit:GetX() return 3 end
function unit:GetY() return 4 end
UNIT = unit
Players = {
  [0] = {
    GetUnits = function()
      return { FindID = function(_, id) if id == 5 then return UNIT end end }
    end,
  },
}
GameInfo = { Units = { [0] = { UnitType = "UNIT_ARCHER", RangedCombat = 25, Range = 2 } } }
ExposedMembers = { Civ6Ai = { Gov = {
  AttackUnit = function(owner, id, x, y)
    table.insert(ATTACKS, { owner = owner, id = id, x = x, y = y })
    return true, "melee:def_dmg=0>10"
  end,
} } }
"""


POLICY_ENV = r"""
RECORDED = {}
OPS = {}
REQUEST = nil
gold = 100
unlocks = 0
pending = false
slots = { [0] = 4, [1] = -1 }
Civ6Ai_Util.ScheduleTick = function(fn)
  if unlocks > 0 then pending = true end
  for _ = 1, 100 do
    if not fn() then return end
  end
end
Civ6Ai_Apply._RecordResult = function(pid, cmd, ok, reason)
  table.insert(RECORDED, { ok = ok, reason = reason })
end
Game = { GetLocalPlayer = function() return 0 end, GetCurrentGameTurn = function() return 151 end }
PlayerOperations = { UNLOCK_POLICIES = 11 }
UI = { RequestPlayerOperation = function()
  table.insert(OPS, "unlock")
  unlocks = unlocks + 1
end }
GameInfo = {
  Types = {
    POLICY_DISCIPLINE = { Hash = 888 },
    POLICY_SURVEY = { Hash = 777 },
  },
  GovernmentSlots = { [0] = { GovernmentSlotType = "SLOT_WILDCARD" } },
  Policies = {
    [4] = { Index = 4, PolicyType = "POLICY_DISCIPLINE", Hash = 444, GovernmentSlotType = "SLOT_MILITARY" },
    [3] = { Index = 3, PolicyType = "POLICY_SURVEY", Hash = 333, GovernmentSlotType = "SLOT_MILITARY" },
    POLICY_DISCIPLINE = { Index = 4, PolicyType = "POLICY_DISCIPLINE", Hash = 444, GovernmentSlotType = "SLOT_MILITARY" },
    POLICY_SURVEY = { Index = 3, PolicyType = "POLICY_SURVEY", Hash = 333, GovernmentSlotType = "SLOT_MILITARY" },
  },
}
local culture = {}
function culture:GetNumPolicySlots() return 2 end
function culture:PolicyChangeMade() return false end
function culture:CivicCompletedThisTurn() return false end
function culture:GetNumPolicySlotsOpen() return 1 end
function culture:GetSlotType() return 0 end
function culture:IsPolicyUnlocked() return true end
function culture:GetSlotPolicy(i) return slots[i] end
function culture:GetCostToUnlockPolicies()
  if pending then return 0 end
  return 40
end
function culture:RequestPolicyChanges(clearList, addList)
  local clear, add = {}, {}
  for _, slot in ipairs(clearList) do clear[#clear + 1] = slot end
  for slot, hash in pairs(addList) do add[#add + 1] = tostring(slot) .. "=" .. tostring(hash) end
  table.sort(add)
  REQUEST = { clear = table.concat(clear, ","), add = table.concat(add, ";") }
  slots[0], slots[1] = -1, -1
  for slot, hash in pairs(addList) do
    if hash == 888 then slots[slot] = 4
    elseif hash == 777 then slots[slot] = 3 end
  end
  return true
end
Players = {
  [0] = {
    GetCulture = function() return culture end,
    GetTreasury = function() return { GetGoldBalance = function() return gold end } end,
    GetReligion = function() return { GetFaithBalance = function() return 0 end } end,
  },
}
"""


@unittest.skipIf(lupa is None, "lupa not installed")
class LocalSeatAttackTests(unittest.TestCase):
    def test_single_player_local_attack_uses_the_ai_resolver(self):
        lua = _apply(ATTACK_ENV)
        ok, reason = lua.eval(
            "function() local ok, reason = Civ6Ai_Apply._AttackTarget(0,"
            " { unit_id = 'UNIT_5', target_x = 4, target_y = 4 }) return ok, reason end"
        )()
        self.assertTrue(ok, reason)
        self.assertIn("melee", str(reason))
        self.assertEqual(1, len(lua.globals().ATTACKS))
        self.assertEqual(0, len(lua.globals().CALLS))
        self.assertEqual(0, len(lua.globals().REQUESTS))

    def test_network_local_attack_uses_the_four_arg_check_that_can_start(self):
        lua = _apply(ATTACK_ENV)
        lua.execute("GameConfiguration = { IsNetworkMultiplayer = function() return true end }")
        ok, reason = lua.eval(
            "function() local ok, reason = Civ6Ai_Apply._AttackTarget(0,"
            " { unit_id = 'UNIT_5', target_x = 4, target_y = 5 }) return ok, reason end"
        )()
        self.assertTrue(ok, reason)
        self.assertEqual("ui_attack_requested", reason)
        self.assertEqual(0, len(lua.globals().ATTACKS))
        calls = list(lua.globals().CALLS.values())
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(4, int(call["n"]))
            self.assertIsNone(call["fifth"])
        requested = list(lua.globals().REQUESTS.values())
        self.assertEqual(2, int(requested[0]["op"]))

    def test_network_offer_matches_the_operation_that_can_start(self):
        lua = _apply(ATTACK_ENV)
        lua.execute(SNAPSHOT.read_text(encoding="utf-8"))
        lua.execute("GameConfiguration = { IsNetworkMultiplayer = function() return true end }")
        can_local = lua.eval("function() return Civ6Ai_Snapshot._AttackCanExecute(0, UNIT, 4, 5) end")()
        lua.execute("UnitManager.CanStartOperation = function() return false end")
        blocked = lua.eval("function() return Civ6Ai_Snapshot._AttackCanExecute(0, UNIT, 4, 5) end")()
        other = lua.eval("function() return Civ6Ai_Snapshot._AttackCanExecute(1, UNIT, 4, 5) end")()
        lua.execute("GameConfiguration = { IsNetworkMultiplayer = function() return false end }")
        single = lua.eval("function() return Civ6Ai_Snapshot._AttackCanExecute(0, UNIT, 4, 5) end")()
        self.assertTrue(can_local)
        self.assertFalse(blocked)
        self.assertTrue(other)
        self.assertTrue(single)


@unittest.skipIf(lupa is None, "lupa not installed")
class PolicyApplyTests(unittest.TestCase):
    def _run(self, slots: str, extra: str = ""):
        lua = _apply(POLICY_ENV)
        if extra:
            lua.execute(extra)
        ok, reason = lua.eval(
            "function(slots) local ok, reason = Civ6Ai_Apply._SetPolicies(0,"
            " { kind = 'set_policies' }, { slots = slots }) return ok, reason end"
        )(slots)
        recorded = [dict(row) for row in lua.globals().RECORDED.values()] if lua.globals().RECORDED else []
        return lua, ok, reason, recorded

    def test_unlocks_then_slots_the_type_hash_for_every_slot(self):
        lua, ok, reason, recorded = self._run("1=POLICY_SURVEY")
        self.assertEqual("unlock", lua.eval("OPS[1]"))
        self.assertEqual("0,1", lua.eval("REQUEST.clear"))
        self.assertEqual("0=888;1=777", lua.eval("REQUEST.add"))
        self.assertTrue(recorded, (ok, reason))
        self.assertTrue(recorded[-1]["ok"], recorded[-1]["reason"])
        self.assertNotIn("still holds nothing", recorded[-1]["reason"])
        self.assertIn("POLICY_SURVEY", recorded[-1]["reason"])

    def test_refuses_before_paying_when_the_seat_cannot_afford_the_unlock(self):
        lua, ok, reason, recorded = self._run("1=POLICY_SURVEY", "gold = 10")
        self.assertFalse(ok)
        self.assertIn("40", str(reason))
        self.assertIn("gold", str(reason))
        self.assertIsNone(lua.eval("REQUEST"))
        self.assertEqual(0, len(lua.globals().OPS))
        self.assertEqual([], recorded)

    def test_city_strikes_stop_after_the_first_failure(self):
        lua = _apply(r"""
          STRIKES = {}
          RESULTS = {}
          Game = { GetLocalPlayer = function() return 0 end, GetCurrentGameTurn = function() return 202 end }
          GameConfiguration = { IsNetworkMultiplayer = function() return false end }
          Civ6Ai_Apply._RecordResult = function(pid, cmd, ok, reason)
            table.insert(RESULTS, { id = cmd.command_id, ok = ok, reason = reason })
          end
          Civ6Ai_Apply._GovRoute = function(name)
            table.insert(STRIKES, name)
            return false, "city_strike_refused"
          end
          Civ6Ai_OrderChannel = { _Fields = function() return { K = 31, I = 65536, X = 45, Y = 15 } end }
        """)
        lua.execute(r"""
          Civ6Ai_Apply.ApplyDecision(0, { commands = {
            { kind = "city_attack", command_id = "CMD_citystrike_65536_45_15", arguments = {} },
            { kind = "city_attack", command_id = "CMD_citystrike_65536_46_16", arguments = {} },
          } })
        """)
        strikes = list(lua.globals().STRIKES.values())
        results = [dict(row) for row in lua.globals().RESULTS.values()]
        self.assertEqual(["CityStrike"], strikes)
        self.assertEqual("city_strike_refused", results[0]["reason"])
        self.assertEqual("CMD_citystrike_65536_46_16", results[1]["id"])
        self.assertEqual("city_strike_stopped", results[1]["reason"])

    def test_names_the_empty_slot_instead_of_applying_a_partial_plan(self):
        lua, ok, reason, recorded = self._run("1=POLICY_SURVEY", "slots[0] = -1")
        self.assertFalse(ok)
        self.assertIn("slot 0", str(reason))
        self.assertIn("still holds nothing", str(reason))
        self.assertIsNone(lua.eval("REQUEST"))
        self.assertEqual([], recorded)


if __name__ == "__main__":
    unittest.main()
