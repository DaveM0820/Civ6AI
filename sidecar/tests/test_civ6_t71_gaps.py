"""T71 gap prompts: expansion, idle stock, army cap, quiet explore, blocked moves."""
from __future__ import annotations

import unittest

from sidecar import civ6_apply_results as results
from sidecar import civ6_governance as governance
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire
from sidecar.map_render_civ6 import PEAK_LABEL, WATER_LABEL, _civ6_marker_legend_entries


def _snap(**extra):
    base = {
        "decision": {"player_id": "PLAYER_0", "turn": 70},
        "game": {"turn": 70, "game_speed_id": "GAMESPEED_ONLINE", "map_width": 20, "map_height": 20},
        "your_cities": [{
            "city_id": "CITY_1", "name": "Capital", "population": 6, "plot_id": "PLOT_4_4",
            "production": {"item_id": "BUILDING_MONUMENT"},
        }],
        "your_units": [],
        "legal_commands": [],
        "history": {"command_results": []},
        "civ6": {"priorities": [], "diplomacy": {}, "governance": {}},
    }
    base.update(extra)
    return base


class T71AttentionTests(unittest.TestCase):
    def test_expansion_line_names_the_turn_target_and_settler_due(self):
        snap = _snap()
        snap["your_cities"] = [
            {"city_id": f"CITY_{i}", "name": f"City{i}", "population": 4, "plot_id": "PLOT_1_1",
             "production": {"item_id": "UNIT_WARRIOR"}}
            for i in range(4)
        ]
        text = "\n".join(coaching.collect_civ6_attention_items(snap))
        self.assertIn("EXPANSION: 4 cities", text)
        self.assertIn("aim for 6-8 cities by turn 70", text)
        self.assertIn("this turn's target is 8", text)
        self.assertIn("Settler due:", text)
        self.assertIn('"priorities": "expansion:2"', text)
        self.assertNotIn(".purchase", text)

    def test_settler_due_names_an_affordable_purchase_and_skips_a_dear_one(self):
        snap = _snap(your_empire={"gold": 400})
        snap["civ6"]["governance"] = {"religion": {"faith": 40, "pantheon_cost": 25}}
        snap["legal_commands"] = [{
            "command_id": "CMD_buy_settler",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_SETTLER", "cost": 320},
        }, {
            "command_id": "CMD_buy_faith",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_SETTLER", "cost": 200, "yield": "faith"},
        }, {
            "command_id": "CMD_train_settler",
            "kind": "queue_production",
            "fixed_arguments": {"city_id": "CITY_1", "build_id": "UNIT_SETTLER"},
        }]
        text = coaching.civ6_expansion_attention(snap) or ""
        self.assertIn("Capital.purchase = UNIT_SETTLER (320 gold, you have 400)", text)
        self.assertNotIn("faith", text.split("Settler due:", 1)[-1])
        self.assertIn("Capital.production = UNIT_SETTLER", text)
        self.assertIn('"priorities": "expansion:2"', text)
        snap["your_empire"] = {"gold": 100}
        poor = coaching.civ6_expansion_attention(snap) or ""
        self.assertNotIn(".purchase", poor)
        self.assertIn("Capital.production = UNIT_SETTLER", poor)

    def test_idle_stock_names_gold_faith_envoys_and_a_buy(self):
        snap = _snap(your_empire={"gold": 480, "gold_per_turn": 40})
        snap["civ6"]["diplomacy"] = {"envoys_to_give": 2}
        snap["civ6"]["governance"] = {
            "religion": {"faith": 30, "faith_per_turn": 2, "pantheon_cost": 25, "can_found_pantheon": True},
            "policies": {"empty_slots": 1, "change_allowed": True, "available": [{"id": "POLICY_URBAN_PLANNING"}]},
            "governors": {"can_appoint": True, "supported": True},
            "routes": {"governors": True, "policies": True},
        }
        snap["legal_commands"] = [{
            "command_id": "CMD_buy_settler",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_SETTLER", "cost": 320},
        }, {
            "command_id": "CMD_buy_builder",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_BUILDER", "cost": 200},
        }, {
            "command_id": "CMD_buy_scout",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_SCOUT", "cost": 120},
        }, {
            "command_id": "CMD_buy_warrior",
            "kind": "purchase_item",
            "fixed_arguments": {"city_id": "CITY_1", "item_id": "UNIT_WARRIOR", "cost": 160},
        }]
        text = "\n".join(coaching.collect_civ6_attention_items(snap))
        self.assertIn("480 gold unspent", text)
        self.assertIn("30 faith, enough for a pantheon (25)", text)
        self.assertIn("2 envoys unspent", text)
        self.assertIn("do not order envoy", text)
        self.assertIn("UNIT_SETTLER in Capital (320 gold)", text)
        self.assertIn("UNIT_BUILDER in Capital (200 gold)", text)
        self.assertLess(text.index("UNIT_SETTLER"), text.index("UNIT_BUILDER"))
        self.assertNotIn("UNIT_SCOUT", text)
        self.assertNotIn("UNIT_WARRIOR", text)
        self.assertIn("1 empty policy slot", text)
        self.assertIn("governor title is unassigned", text)

    def test_small_treasury_is_not_called_idle(self):
        snap = _snap(your_empire={"gold": 80, "gold_per_turn": 20})
        snap["civ6"]["governance"] = {"religion": {"faith": 10, "pantheon_cost": 25, "can_found_pantheon": False}}
        text = "\n".join(coaching.collect_civ6_attention_items(snap))
        self.assertNotIn("IDLE:", text)

    def test_peace_army_over_twice_the_cities_is_a_soft_cap(self):
        snap = _snap()
        snap["your_cities"] = [
            {"city_id": f"CITY_{i}", "name": f"City{i}", "population": 3, "plot_id": "PLOT_1_1",
             "production": {"item_id": "UNIT_WARRIOR"}}
            for i in range(4)
        ]
        snap["your_units"] = [
            {"unit_id": f"UNIT_{i}", "unit_type_id": "UNIT_WARRIOR"} for i in range(16)
        ]
        text = "\n".join(coaching.collect_civ6_attention_items(snap))
        self.assertIn("MILITARY: 16 military units for 4 cities", text)
        self.assertIn("at peace", text)

    def test_explore_token_hides_after_two_quiet_turns(self):
        snap = _snap()
        snap["your_units"] = [{"unit_id": "UNIT_9", "movement": {"current": 2}}]
        snap["legal_commands"] = [{
            "command_id": "CMD_explore_UNIT_9", "kind": "explore",
            "fixed_arguments": {"unit_id": "UNIT_9"},
        }]
        snap["history"]["command_results"] = [
            {"turn": 5, "reason": "explore_no_reveal:explore_to=1,1", "affected_ids": ["UNIT_9"], "order_kind": "explore"},
        ]
        self.assertIn("Automate(explore)", civ6_wire._civ6_unit_tokens(snap)["UNIT_9"])
        self.assertTrue(civ6_wire._explore_offered(snap))
        snap["history"]["command_results"].append(
            {"turn": 6, "reason": "explore_no_reveal:stuck", "affected_ids": ["CMD_explore_UNIT_9"], "order_kind": "explore"},
        )
        tokens = civ6_wire._civ6_unit_tokens(snap)["UNIT_9"]
        self.assertIn("Automate(explore)", tokens)
        self.assertTrue(civ6_wire._explore_offered(snap))
        snap["known_map"] = {"explored_percent": 4}
        self.assertTrue(civ6_wire._explore_offered(snap))
        self.assertIn("Automate(explore)", civ6_wire._civ6_unit_tokens(snap)["UNIT_9"])

    def test_step_toward_reason_names_impassable(self):
        text = results.describe_reason("step_toward:12,11>12,10:moved:12,10")
        self.assertIn("impassable", text)
        self.assertIn("(12,11)", text)
        self.assertIn("(12,10)", text)
        self.assertIn("nearest reachable", text)

    def test_government_and_pantheon_are_refused_when_unavailable(self):
        snap = {"civ6": {"governance": {
            "government": {
                "current": "GOVERNMENT_CHIEFDOM",
                "change_allowed": False,
                "available": [{"id": "GOVERNMENT_AUTOCRACY"}],
            },
            "religion": {
                "can_found_pantheon": False,
                "pantheon_cost": 25,
                "faith": 10,
                "pantheon_beliefs": [{"id": "BELIEF_GOD_OF_THE_FORGE"}],
            },
        }}}
        ids, notes = governance.bind_reply(snap, "government", "AUTOCRACY")
        self.assertEqual(ids, [])
        self.assertTrue(any("civic" in note for note in notes))
        ids, notes = governance.bind_reply(snap, "pantheon", "GOD_OF_THE_FORGE")
        self.assertEqual(ids, [])
        self.assertTrue(any("25 faith" in note for note in notes))
        self.assertFalse(any(cmd.get("kind") == "change_government" for cmd in snap.get("legal_commands") or []))
        self.assertFalse(any(cmd.get("kind") == "found_pantheon" for cmd in snap.get("legal_commands") or []))
        missing = {"civ6": {"governance": {
            "government": {
                "current": "GOVERNMENT_CHIEFDOM",
                "available": [{"id": "GOVERNMENT_AUTOCRACY"}],
            },
        }}}
        ids, notes = governance.bind_reply(missing, "government", "AUTOCRACY")
        self.assertEqual(ids, [])
        self.assertTrue(any("civic" in note for note in notes))

    def test_occupied_tiles_are_named_in_attention(self):
        snap = _snap()
        snap["your_units"] = [
            {"unit_id": "UNIT_1", "unit_type_id": "UNIT_BUILDER", "plot_id": "PLOT_4_4",
             "needs_orders": True, "movement": {"current": 2}},
            {"unit_id": "UNIT_2", "unit_type_id": "UNIT_BATTERING_RAM", "unit_class_id": "FORMATION_CLASS_SUPPORT",
             "plot_id": "PLOT_5_5", "needs_orders": True, "movement": {"current": 2}},
        ]
        text = "\n".join(coaching.collect_civ6_attention_items(snap))
        self.assertIn("host default applied", text)

    def test_water_and_mountains_are_named_on_the_legend(self):
        entries = _civ6_marker_legend_entries(
            {},
            {},
            {
                (0, 0): {"water": True, "terrain_id": "TERRAIN_COAST"},
                (1, 0): {"peak": True, "terrain_id": "TERRAIN_GRASS_MOUNTAIN"},
            },
            {"x0": 0, "y0": 0, "width": 2, "height": 1},
        )
        labels = [label for _, label in entries]
        self.assertIn(WATER_LABEL, labels)
        self.assertIn(PEAK_LABEL, labels)
        self.assertIn("impassable", WATER_LABEL)


if __name__ == "__main__":
    unittest.main()
