"""War binding and the two-turn deal flow (offer -> required respond -> execute_deal)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_diplomacy as diplo


def _snap(me="PLAYER_0", other="PLAYER_1", other_name="Cleopatra", session=None, turn=12, **extra):
    snap = {
        "decision": {"player_id": me, "turn": turn},
        "known_players": [{"player_id": other, "leader_name": other_name, "relation": {"met": True}}],
        "legal_commands": [],
        "civ6": {"diplomacy": {
            "majors": [{"player_id": other, "can_declare_war": True, "can_make_peace": False}],
            "city_states": [],
            "your_trade": {"gold": 200, "gold_per_turn": 10,
                           "luxuries": [{"resource_id": "RESOURCE_COTTON", "amount": 1}],
                           "strategics": [{"resource_id": "RESOURCE_IRON", "amount": 20}]},
        }},
    }
    if session:
        snap["_session_dir"] = str(Path(session) / f"{me}")
    snap.update(extra)
    return snap


class DiplomacyWireTests(unittest.TestCase):
    def test_optional_keys_list_war_and_deal(self):
        keys = dict(diplo.optional_key_hints(_snap()))
        self.assertEqual(keys["legal.diplomacy.Cleopatra"], "DECLARE_WAR")
        self.assertIn("Cleopatra", keys["deal.<Leader>"])

    def test_bind_declare_war(self):
        snap = _snap()
        ids, notes = diplo.bind_reply(snap, "legal.diplomacy.Cleopatra", "DECLARE_WAR")
        self.assertEqual(notes, [])
        self.assertEqual(snap["legal_commands"][0]["kind"], "send_diplomatic_action")

    def test_offer_then_required_accept_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _snap(session=tmp)
            ids, notes = diplo.bind_reply(a, "deal.Cleopatra", "give 50 gold, 2 gpt for 1 RESOURCE_SILK")
            self.assertEqual((ids, notes), ([], []))
            b = _snap(me="PLAYER_1", other="PLAYER_0", other_name="Amanitore", session=tmp, turn=13)
            b["civ6"]["diplomacy"]["your_trade"]["luxuries"] = [{"resource_id": "RESOURCE_SILK", "amount": 1}]
            rows = diplo.required_rows(b)
            self.assertEqual(rows[0][0], "deal.Amanitore.respond")
            ids, notes = diplo.bind_reply(b, "deal.Amanitore.respond", "ACCEPT")
            self.assertEqual(notes, [])
            fixed = b["legal_commands"][-1]["fixed_arguments"]
            self.assertEqual((fixed["gold"], fixed["res1"], fixed["amt1"], fixed["mode"]), (-50, "RESOURCE_SILK", 1, 0))
            self.assertEqual(diplo.required_rows(b), [])
            self.assertIn("accepted", diplo.trade_lines(b, "PLAYER_0"))
            a["decision"]["turn"] = 14
            self.assertEqual(len(diplo.instalment_ids(a)), 1)
            self.assertEqual(a["legal_commands"][-1]["fixed_arguments"]["gold"], 2)
            self.assertEqual(diplo.instalment_ids(a), [])

    def test_offer_needs_stock_and_peace_needs_war(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snap(session=tmp)
            self.assertTrue(diplo.bind_reply(snap, "deal.Cleopatra", "give 999 gold for peace")[1])
            self.assertTrue(diplo.bind_reply(snap, "deal.Cleopatra", "peace")[1])
            self.assertEqual(diplo.trade_lines(snap, "PLAYER_1"), "none")

    def test_pacts_gated_and_packed_as_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _snap(session=tmp)
            self.assertIn("CIVIC_EARLY_EMPIRE", diplo.bind_reply(a, "deal.Cleopatra", "open borders")[1][0])
            self.assertIn("DIPLOMATIC_SERVICE", diplo.bind_reply(a, "deal.Cleopatra", "alliance")[1][0])
            a["your_empire"] = {"civics": [{"key": "known", "id": "CIVIC_EARLY_EMPIRE"}]}
            self.assertEqual(diplo.bind_reply(a, "deal.Cleopatra", "open_borders, delegation"), ([], []))
            b = _snap(me="PLAYER_1", other="PLAYER_0", other_name="Amanitore", session=tmp, turn=13)
            diplo.bind_reply(b, "deal.Amanitore.respond", "ACCEPT")
            self.assertEqual(b["legal_commands"][-1]["fixed_arguments"]["mode"], 40)

    def test_reject_closes_offer(self):
        with tempfile.TemporaryDirectory() as tmp:
            diplo.bind_reply(_snap(session=tmp), "deal.Cleopatra", "friendship")
            b = _snap(me="PLAYER_1", other="PLAYER_0", other_name="Amanitore", session=tmp, turn=13)
            self.assertEqual(diplo.bind_reply(b, "deal.Amanitore.respond", "REJECT"), ([], []))
            self.assertEqual(diplo.required_rows(b), [])

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


if __name__ == "__main__":
    unittest.main()
