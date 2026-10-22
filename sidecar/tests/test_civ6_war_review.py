"""War-review prompt and binding: reach, peace, empty queues, fortify, reasons."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_apply_results as results
from sidecar import civ6_combat_wire as combat
from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_economy as economy
from sidecar import civ6_wire


def _war_context():
    return {
        "decision": {"player_id": "PLAYER_0", "turn": 100},
        "game": {"map_width": 40, "map_height": 30, "wrap_x": True},
        "known_players": [{
            "player_id": "PLAYER_1", "leader_name": "Montezuma",
            "civilization_id": "CIVILIZATION_AZTEC", "relation": {"at_war": True, "met": True},
        }],
        "your_cities": [{
            "city_id": "CITY_1", "name": "Utrecht", "plot_id": "PLOT_10_10",
            "garrison_unit_ids": [],
            "defense": {"percent": 100, "health_percent": 100, "bombard_damage": 0, "wall_hp": 0, "wall_max_hp": 0},
            "production": {"item_id": None},
            "buildings": [],
        }],
        "your_units": [{
            "unit_id": "UNIT_0_3", "unit_type_id": "UNIT_SPEARMAN", "plot_id": "PLOT_8_10",
            "needs_orders": True, "strength": {"current": 25},
        }],
        "civ6": {"combat": {
            "hostiles": [{
                "owner_player_id": "PLAYER_1", "name": "Warrior", "x": 12, "y": 10,
                "strength": 20, "ranged_strength": 0, "range": 0, "max_moves": 0, "hp": 100,
            }],
            "previews": [],
            "threats": [],
            "units": [],
            "hostile_cities": [],
        }},
    }


class WarReviewTests(unittest.TestCase):
    def test_enemy_with_unreported_moves_is_within_reach_of_the_city(self):
        ctx = _war_context()
        self.assertEqual(combat.enemy_reach(ctx["civ6"]["combat"]["hostiles"][0]), 2)
        self.assertTrue(combat.enemies_within_their_reach(ctx))
        text = "\n".join(combat.war_section_lines(ctx))
        self.assertNotIn("No enemy is within reach", text)
        self.assertIn("within their move range", text)
        self.assertIn("war.city.Utrecht.threat", text)
        self.assertIn("walls=no", text)
        self.assertIn("nearby=", text)
        advice = "\n".join(civ6_wire._advice_section(ctx))
        self.assertNotIn("In peacetime", advice)
        self.assertIn("You are at war", advice)

    def test_far_enemy_is_not_called_in_reach(self):
        ctx = _war_context()
        ctx["civ6"]["combat"]["hostiles"][0]["x"] = 30
        ctx["civ6"]["combat"]["hostiles"][0]["max_moves"] = 2
        text = "\n".join(combat.war_section_lines(ctx))
        self.assertIn("No enemy is within reach of your military this turn.", text)
        self.assertIn("no enemy is within move range", text)
        self.assertNotIn("enemies within their move range", text)
        tactics = "\n".join(combat.tactics_advice_lines(ctx))
        self.assertNotIn("Mass 3+", tactics)
        self.assertIn("do not mass units", tactics)
        advice = "\n".join(civ6_wire._advice_section(ctx))
        self.assertIn("no enemy unit is within move range", advice)
        self.assertNotIn("Mass 3+", advice)

    def test_civilian_and_city_strike_tokens(self):
        self.assertEqual("SpreadReligion(4,5)", command_wire.unit_command_token({
            "kind": "spread_religion", "fixed_arguments": {"target_x": 4, "target_y": 5, "action": "spread"},
        }))
        self.assertEqual("HealReligious(4,5)", command_wire.unit_command_token({
            "kind": "spread_religion", "fixed_arguments": {"target_x": 4, "target_y": 5, "action": "heal"},
        }))
        self.assertEqual("Retire", command_wire.unit_command_token({
            "kind": "activate_great_person", "fixed_arguments": {"retire": 1},
        }))
        self.assertEqual("Activate", command_wire.unit_command_token({
            "kind": "activate_great_person", "fixed_arguments": {},
        }))
        self.assertEqual("TradeRoute(8,9)", command_wire.unit_command_token({
            "kind": "trade_route", "fixed_arguments": {"target_x": 8, "target_y": 9, "city_id": "CITY_131072"},
        }))
        self.assertEqual("FormCorps", command_wire.unit_command_token({
            "kind": "join_formation", "fixed_arguments": {},
        }))
        self.assertEqual("Promote(PROMOTION_BATTLECRY)", command_wire.unit_command_token({
            "kind": "promote_unit", "fixed_arguments": {"promotion_id": "PROMOTION_BATTLECRY"},
        }))
        prop, value = command_wire.city_command_token({
            "kind": "city_attack", "fixed_arguments": {"target_x": 12, "target_y": 10},
        })
        self.assertEqual("rangeStrike", prop)
        self.assertEqual("(12,10)", value)

    def test_empty_queue_is_an_attention_item_and_not_filled(self):
        ctx = _war_context()
        ctx["your_cities"].append({
            "city_id": "CITY_2", "name": "Apeldoorn", "plot_id": "PLOT_4_4",
            "production": {"item_id": "NONE"},
        })
        notes = economy.attention_items(ctx)
        self.assertTrue(any("QUEUE EMPTY" in n and "Utrecht" in n and "Apeldoorn" in n for n in notes))
        self.assertIn("Nothing will be queued for you", notes[0])

    def test_threatened_catalog_leads_with_walls_and_military(self):
        ctx = _war_context()
        ctx["civ6"]["economy"] = {"build_catalog": {
            "BUILDING_MONUMENT": {"category": "building", "cost": 60},
            "BUILDING_WALLS": {"category": "building", "cost": 80},
            "UNIT_ARCHER": {"category": "unit", "ranged": 25, "range": 2, "combat": 15},
            "UNIT_WARRIOR": {"category": "unit", "combat": 20},
        }}
        lines = economy.production_catalog_lines(ctx, {"CITY_1": {"production": [
            "BUILDING_MONUMENT", "UNIT_WARRIOR", "BUILDING_WALLS", "UNIT_ARCHER",
        ]}})
        catalog = next(line for line in lines if "Utrecht.production.catalog" in line)
        self.assertLess(catalog.index("BUILDING_WALLS"), catalog.index("UNIT_ARCHER"))
        self.assertLess(catalog.index("UNIT_ARCHER"), catalog.index("UNIT_WARRIOR"))
        self.assertLess(catalog.index("UNIT_WARRIOR"), catalog.index("BUILDING_MONUMENT"))
        self.assertIn("THREATENED", catalog)

    def test_fortify_resolves_for_a_warrior_and_attack_explains_why(self):
        snap = {
            "your_units": [{
                "unit_id": "UNIT_0_1", "unit_type_id": "UNIT_WARRIOR",
                "plot_id": "PLOT_5_5", "strength": {"current": 20},
            }],
            "legal_commands": [{
                "command_id": "CMD_skip_UNIT_0_1", "kind": "unit_skip",
                "fixed_arguments": {"unit_id": "UNIT_0_1"},
            }],
            "game": {"map_width": 20, "map_height": 20},
        }
        out = command_wire.expand_civ6_command_wire(snap, {"warrior_1.command": "Fortify"})
        self.assertTrue(any(v.startswith("CMD_fortify_") for v in out.values()))
        snap["legal_commands"] = [c for c in snap["legal_commands"] if c["kind"] != "unit_posture_fortify"]
        command_wire.expand_civ6_command_wire(snap, {"warrior_1.command": "AttackTo(9,9)"})
        self.assertTrue(any("no attack is legal" in n for n in command_wire.LAST_UNRESOLVED))

    def test_attack_reasons_are_plain_language(self):
        self.assertIn("0 damage", results.describe_reason("no_effect:zero_damage"))
        self.assertIn("did not apply", results.describe_reason("no_effect:damage_not_applied:forecast=14"))
        self.assertIn("never reported", results.describe_reason("no_result_from_gameplay"))
        crashed = results.describe_reason(
            "no_result_from_gameplay:function expected instead of nil"
        )
        self.assertIn("function expected instead of nil", crashed)
        self.assertIn("do not reissue", crashed)
        order_err = results.describe_reason("order_error:function expected instead of nil")
        self.assertIn("function expected instead of nil", order_err)
        self.assertIn("do not reissue", order_err)
        self.assertNotIn("reissue it", order_err)

    def test_attack_options_carry_the_combat_forecast_and_still_bind(self):
        snap = {
            "your_units": [{
                "unit_id": "UNIT_1_5",
                "unit_type_id": "UNIT_SPEARMAN",
                "needs_orders": True,
                "movement": {"current": 2},
            }],
            "your_cities": [{
                "city_id": "CITY_8",
                "name": "Teotihuacan",
            }],
            "legal_commands": [
                {
                    "command_id": "CMD_attack_UNIT_1_5_17_22",
                    "kind": "attack_target",
                    "fixed_arguments": {
                        "unit_id": "UNIT_1_5", "target_x": 17, "target_y": 22,
                        "target_kind": "city", "ranged": False,
                    },
                },
                {
                    "command_id": "CMD_citystrike_8_18_22",
                    "kind": "city_attack",
                    "fixed_arguments": {"city_id": "CITY_8", "target_x": 18, "target_y": 22},
                },
            ],
            "civ6": {"combat": {"previews": [
                {
                    "unit_id": "UNIT_1_5", "target_x": 17, "target_y": 22,
                    "damage_to_defender": 12, "damage_to_attacker": 4,
                    "prediction": "MAJOR_VICTORY", "ranged": False, "target_kind": "city",
                },
                {
                    "city_id": "CITY_8", "target_x": 18, "target_y": 22,
                    "damage_to_defender": 20, "damage_to_attacker": 0,
                    "prediction": "MAJOR_VICTORY", "ranged": True, "target_kind": "unit",
                    "source": "city",
                },
            ]}},
        }
        tokens = civ6_wire._civ6_unit_tokens(snap)["UNIT_1_5"]
        attack = next(t for t in tokens if t.startswith("AttackTo(17,22)"))
        self.assertIn("~12dmg", attack)
        self.assertIn("~4dmg", attack)
        self.assertEqual(
            command_wire.resolve_unit_token(snap, "UNIT_1_5", attack),
            "CMD_attack_UNIT_1_5_17_22",
        )
        self.assertEqual(
            command_wire.resolve_unit_token(snap, "UNIT_1_5", "AttackTo(17,22)"),
            "CMD_attack_UNIT_1_5_17_22",
        )
        strike = civ6_wire._civ6_city_tokens(snap)["CITY_8"]["rangeStrike"][0]
        self.assertTrue(strike.startswith("(18,22) ("))
        self.assertIn("~20dmg", strike)
        self.assertEqual(
            command_wire.resolve_city_token(snap, "CITY_8", "rangeStrike", strike),
            "CMD_citystrike_8_18_22",
        )
        bare = {
            "legal_commands": snap["legal_commands"][:1],
            "your_units": snap["your_units"],
        }
        self.assertIn("AttackTo(17,22)", civ6_wire._civ6_unit_tokens(bare)["UNIT_1_5"])
        self.assertFalse(any("(" in t.split(")", 1)[-1] for t in civ6_wire._civ6_unit_tokens(bare)["UNIT_1_5"] if t.startswith("AttackTo")))

    def test_strategy_mismatch_is_context_only(self):
        note = results.strategy_orders_note("Attack Utrecht and take it.", [{"kind": "move_unit"}])
        self.assertIn("attacking", note)
        self.assertIsNone(results.strategy_orders_note("Attack Utrecht.", [{"kind": "attack_target"}]))
        memory = {"thoughts": [{"turn": 100, "situation": "War.", "strategy": "Offer peace."}]}
        results.attach_strategy_orders_note(memory, 100, [{"kind": "move_unit"}])
        self.assertIn("peace", memory["thoughts"][0]["orders_note"])


if __name__ == "__main__":
    unittest.main()
