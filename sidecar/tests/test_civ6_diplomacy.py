"""War / peace reply binding and optional keys from civ6.diplomacy facts."""
from __future__ import annotations

import unittest

from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_diplomacy as diplo


def _snap(**extra):
    snap = {
        "decision": {"player_id": "PLAYER_0", "turn": 12},
        "known_players": [
            {
                "player_id": "PLAYER_1",
                "leader_id": "LEADER_CLEOPATRA",
                "leader_name": "Cleopatra",
                "relation": {"met": True},
            }
        ],
        "legal_commands": [],
        "civ6": {
            "diplomacy": {
                "majors": [
                    {"player_id": "PLAYER_1", "can_declare_war": True, "can_make_peace": False},
                ],
                "city_states": [],
            }
        },
    }
    snap.update(extra)
    return snap


class DiplomacyWireTests(unittest.TestCase):
    def test_pending_delegation_is_required_and_binds(self):
        snap = _snap()
        snap["civ6"]["diplomacy"]["pending_requests"] = [{
            "session_id": 9,
            "from_player_id": "PLAYER_1",
            "type": "DIPLOMATIC_DELEGATION",
            "items": [],
        }]
        rows = diplo.required_rows(snap)
        self.assertEqual(rows[0][0], "diplomacy.Cleopatra.respond")
        ids, notes = diplo.bind_reply(snap, "diplomacy.Cleopatra.respond", "ACCEPT")
        self.assertEqual(notes, [])
        self.assertTrue(ids)
        command = snap["legal_commands"][-1]
        self.assertEqual(command["kind"], "respond_to_diplomacy")
        self.assertEqual(command["fixed_arguments"]["response"], "ACCEPT")
        self.assertEqual(command["fixed_arguments"]["session_id"], 9)

    def test_optional_keys_list_declare_war(self):
        hints = diplo.optional_key_hints(_snap())
        self.assertIn(("legal.diplomacy.Cleopatra", "DECLARE_WAR"), hints)
        self.assertFalse(any(k.startswith("legal.peace") for k, _ in hints))

    def test_bind_declare_war(self):
        snap = _snap()
        ids, notes = diplo.bind_reply(snap, "legal.diplomacy.Cleopatra", "DECLARE_WAR")
        self.assertEqual(notes, [])
        self.assertEqual(len(ids), 1)
        cmd = snap["legal_commands"][0]
        self.assertEqual(cmd["kind"], "send_diplomatic_action")
        self.assertEqual(cmd["fixed_arguments"]["target_player_id"], "PLAYER_1")
        self.assertEqual(cmd["fixed_arguments"]["action_id"], "DECLARE_WAR")

    def test_bind_peace_only_when_allowed(self):
        snap = _snap()
        ids, notes = diplo.bind_reply(snap, "legal.peace.Cleopatra", "apply")
        self.assertEqual(ids, [])
        self.assertTrue(notes)
        snap["civ6"]["diplomacy"]["majors"][0]["can_declare_war"] = False
        snap["civ6"]["diplomacy"]["majors"][0]["can_make_peace"] = True
        ids, notes = diplo.bind_reply(snap, "legal.peace.Cleopatra", "apply")
        self.assertEqual(notes, [])
        self.assertEqual(snap["legal_commands"][-1]["kind"], "propose_peace")

    def test_command_wire_expand_binds_diplomacy_key(self):
        snap = _snap()
        out = command_wire.expand_civ6_command_wire(snap, {"legal.diplomacy.Cleopatra": "DECLARE_WAR"})
        self.assertTrue(any(str(k).startswith("cmd.") for k in out))
        self.assertEqual(command_wire.LAST_UNRESOLVED, [])

    def test_adapter_keeps_war_peace_flags(self):
        from sidecar import civ6_adapter

        snap = _snap()
        civ6_adapter.normalize_civ6_diplomacy(snap)
        major = snap["civ6"]["diplomacy"]["majors"][0]
        self.assertTrue(major["can_declare_war"])
        self.assertFalse(major["can_make_peace"])

    def test_purchase_token_includes_faith(self):
        token = command_wire.city_command_token({
            "kind": "purchase_item",
            "fixed_arguments": {"item_id": "UNIT_MISSIONARY", "yield": "faith", "city_id": "CITY_0"},
        })
        self.assertEqual(token, ("purchase", "UNIT_MISSIONARY:faith"))
        token = command_wire.city_command_token({
            "kind": "purchase_item",
            "fixed_arguments": {"item_id": "UNIT_MISSIONARY", "yield": "faith", "city_id": "CITY_0"},
        })
        self.assertEqual(token, ("purchase", "UNIT_MISSIONARY:faith"))

    def test_improve_token_and_reply_bind(self):
        token = command_wire.unit_command_token({
            "kind": "worker_improve",
            "fixed_arguments": {"unit_id": "UNIT_3", "improvement_id": "IMPROVEMENT_FARM"},
        })
        self.assertEqual(token, "Improve(IMPROVEMENT_FARM)")
        snap = {
            "your_units": [{"unit_id": "UNIT_3", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_6_7"}],
            "legal_commands": [{
                "command_id": "CMD_improve_UNIT_3_IMPROVEMENT_FARM",
                "kind": "worker_improve",
                "fixed_arguments": {
                    "unit_id": "UNIT_3",
                    "improvement_id": "IMPROVEMENT_FARM",
                    "target_x": 6,
                    "target_y": 7,
                },
            }],
        }
        out = command_wire.expand_civ6_command_wire(snap, {"builder_1.improve": "IMPROVEMENT_FARM"})
        self.assertEqual(out.get("cmd.0"), "CMD_improve_UNIT_3_IMPROVEMENT_FARM")
        self.assertEqual(command_wire.LAST_UNRESOLVED, [])


if __name__ == "__main__":
    unittest.main()
