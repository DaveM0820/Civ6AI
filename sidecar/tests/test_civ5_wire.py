"""Tests for Civ V wire prompt builder."""
from __future__ import annotations

import unittest

from sidecar import civ5_adapter
from sidecar import civ5_wire
from sidecar import pipeline_v2 as pipeline


class Civ5WireTests(unittest.TestCase):
    def test_sections_present(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("=== CURRENT SITUATION ===", wire)
        self.assertIn("=== MAP ===", wire)
        self.assertIn("=== LEGAL COMMANDS ===", wire)
        self.assertIn("=== INSTRUCTIONS ===", wire)
        self.assertTrue(wire.startswith("=== INSTRUCTIONS ==="))
        self.assertIn("units.nativeControl", wire)
        self.assertIn("cities.nativeProduction", wire)
        self.assertIn("units.needOrders", wire)
        self.assertIn("map.ruins = (13,21)", wire)
        self.assertIn("empire.gold = 86 (+12)", wire)
        self.assertIn("empire.science = 4/25 (+18)", wire)
        self.assertIn("Athens.currentProduction = UNIT_SPEARMAN (5 turns left)", wire)
        self.assertNotIn("map.hex", wire)
        self.assertNotIn("map.coords", wire)
        self.assertNotIn("map.script", wire)
        self.assertNotIn("# minimap attached", wire)
        self.assertIn("Reply with one key = value line per statement", wire)
        self.assertIn("Never JSON", wire)
        self.assertIn("unitId.moveTo = (14,22)", wire)
        self.assertIn("You may still order units that are not listed.", wire)
        self.assertNotIn("there is no move list", wire)
        self.assertNotIn("Hex grid: Y increases south.", wire)
        self.assertNotIn("Never spam chat.all", wire)
        self.assertNotIn("reply only to turn ", wire)

    def test_need_orders_lists_each_idle_unit(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("=== REQUIRED ORDERS THIS TURN ===", wire)
        idle = [unit for unit in snapshot.get("your_units", []) if unit.get("needs_orders")]
        self.assertTrue(idle)
        self.assertIn("units.needOrders =", wire)
        self.assertIn("can move 2 tiles", wire)
        self.assertIn("scout_1 can move 2 tiles", wire)
        self.assertNotIn("Scout at", wire)
        self.assertIn("scout_1", wire)
        self.assertIn("settler_1", wire)
        self.assertIn("spearman_1", wire)
        self.assertIn(".needsOrders = true", wire)
        self.assertIn("Needs orders:", wire)
        self.assertIn("even if it does not need orders", wire.lower())
        self.assertIn("leftover awake units are skipped after apply", wire.lower())
        self.assertNotIn("Community Patch native AI moves unmoved units", wire)

    def test_need_orders_lists_available_order_types(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        worker = {
            **snapshot["your_units"][0],
            "unit_id": "UNIT_WORKER_1",
            "unit_type_id": "UNIT_WORKER",
            "unit_class_id": "UNITCLASS_WORKER",
            "plot_id": snapshot["your_cities"][0]["plot_id"],
            "needs_orders": True,
            "can_act": True,
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
        }
        snapshot["your_units"].append(worker)
        snapshot["legal_commands"].extend([
            {
                "command_id": "CMD_move_UNIT_WORKER_1",
                "kind": "move_unit",
                "fixed_arguments": {"unit_id": "UNIT_WORKER_1"},
                "parameter_domains": {},
                "affected_ids": ["UNIT_WORKER_1"],
                "runtime_status": "tested",
            },
            {
                "command_id": "CMD_improve_UNIT_WORKER_1_BUILD_FARM",
                "kind": "improve_tile",
                "fixed_arguments": {"unit_id": "UNIT_WORKER_1", "build_id": "BUILD_FARM"},
                "parameter_domains": {},
                "affected_ids": ["UNIT_WORKER_1"],
                "runtime_status": "tested",
            },
            {
                "command_id": "CMD_automate_UNIT_WORKER_1_AUTOMATE_BUILD",
                "kind": "automate_unit",
                "fixed_arguments": {"unit_id": "UNIT_WORKER_1", "automate_id": "AUTOMATE_BUILD"},
                "parameter_domains": {},
                "affected_ids": ["UNIT_WORKER_1"],
                "runtime_status": "tested",
            },
            {
                "command_id": "CMD_skip_UNIT_WORKER_1",
                "kind": "unit_skip",
                "fixed_arguments": {"unit_id": "UNIT_WORKER_1"},
                "parameter_domains": {},
                "affected_ids": ["UNIT_WORKER_1"],
                "runtime_status": "tested",
            },
        ])
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn(
            "worker_1 can [moveTo | improve=BUILD_FARM | automate=build | stance=skip]. worker_1 can move 2 tiles this turn",
            wire,
        )
        self.assertNotIn("Worker at", wire)
        self.assertIn("worker_1.automate = build", wire)
        self.assertIn("unitId.automate = build|explore", wire)
        self.assertIn("Brackets list the order types available", wire)
        flat = {
            "thought.situation": "Two idle workers in the capital.",
            "thought.strategy": "Automate improvements.",
            "decision_summary": "Automate worker_1.",
            "worker_1.automate": "build",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_automate_UNIT_WORKER_1_AUTOMATE_BUILD", command_ids)

    def test_ai_player_keeps_community_patch_leftovers(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["advciv"]["default_unit_controller"] = "native"
        snapshot["advciv"]["fallback_policy"] = (
            "Community Patch AI moves unmoved units after LLM apply."
        )
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("Community Patch AI moves leftover units", wire)
        self.assertNotIn("Leftover units are skipped after apply.", wire)
        self.assertIn("units.needOrders =", wire)

    def test_legal_commands_list_research_and_production_not_moves(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("legal.research.tech", wire)
        self.assertIn("Athens.production", wire)
        self.assertNotIn("scout_1.moveTo = (", wire)

    def test_movement_hint_in_instructions(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("unitId.moveTo = (x,y)", wire)
        self.assertIn("maxMovement", wire)
        self.assertIn("wastes leftover movement", wire.lower())
        self.assertNotIn("no move list", wire.lower())

    def test_late_game_instructions_omitted_when_not_legal(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertNotIn("legal.ideology", wire)
        self.assertNotIn("legal.policyBranch", wire)
        self.assertNotIn("unitId.improve", wire)
        self.assertNotIn("found_pantheon", wire.lower())

    def test_thought_memory_and_opinions_in_wire(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot.setdefault("history", {})
        snapshot["history"]["thought_memory"] = [
            {"turn": 1, "situation": "Met a scout near the river.", "strategy": "Expand east."}
        ]
        snapshot["history"]["player_opinions"] = {
            "PLAYER_1": {"text": "Cautious neighbor.", "updated_turn": 1}
        }
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("thought.t1.situation", wire)
        self.assertIn("Met a scout near the river.", wire)
        self.assertIn("opinion.", wire)
        routed = pipeline.build_model_wire_text(snapshot)
        self.assertIn("=== CURRENT SITUATION ===", routed)
        self.assertIn("=== INSTRUCTIONS ===", routed)

    def test_golden_wire_stable(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        first = civ5_wire.build_civ5_model_wire_text(snapshot).strip()
        second = civ5_wire.build_civ5_model_wire_text(snapshot).strip()
        self.assertEqual(first, second)

    def test_production_wire_resolves_with_change_production_alias(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        flat = {
            "thought.situation": "Queue settler.",
            "thought.strategy": "Expand.",
            "decision_summary": "Queue settler in Athens.",
            "Athens.production": "UNIT_SETTLER",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_athens_prod_settler", command_ids)

    def test_chat_history_and_dm_recipients_in_wire(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot.setdefault("history", {})
        snapshot["history"]["public_events"] = [
            {
                "turn": 8,
                "kind": "CHAT_PUBLIC",
                "summary": "The Nile remembers.",
                "affected_ids": ["PLAYER_1"],
            }
        ]
        snapshot.setdefault("diplomacy", {})
        snapshot["diplomacy"]["private_inbox"] = [
            {
                "message_id": "CHAT_8_PLAYER_1_PLAYER_0_0",
                "turn": 8,
                "from_player_id": "PLAYER_1",
                "text": "Meet me at the river.",
            }
        ]
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("chat.public.t8.0", wire)
        self.assertIn("The Nile remembers.", wire)
        self.assertIn("chat.private.t8.0", wire)
        self.assertIn("Meet me at the river.", wire)
        self.assertIn("chat.all / chat.LeaderName", wire)
        self.assertIn("DM recipients: Cleopatra", wire)

    def test_chat_all_and_met_leader_dm_validate(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        flat = {
            "thought.situation": "Egypt is on the border.",
            "thought.strategy": "Speak in public and privately.",
            "decision_summary": "Greet ALL and DM Cleopatra.",
            "chat.all": "Athens hears the world.",
            "chat.Cleopatra": "A word in private, Pharaoh.",
        }
        expanded = pipeline.expand_flat_response(flat, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        chats = validated["chat_messages"]
        self.assertEqual(2, len(chats))
        self.assertEqual("all", chats[0]["target"])
        self.assertEqual("Athens hears the world.", chats[0]["text"])
        self.assertEqual("player", chats[1]["target"])
        self.assertEqual("PLAYER_1", chats[1]["target_player_id"])
        self.assertEqual("A word in private, Pharaoh.", chats[1]["text"])

    def test_unmet_leader_dm_dropped_all_kept(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["known_players"] = []
        flat = {
            "thought.situation": "Alone on the coast.",
            "thought.strategy": "Broadcast only.",
            "decision_summary": "Speak to ALL.",
            "chat.all": "Is anyone there?",
            "chat.Cleopatra": "You should not get this.",
        }
        expanded = pipeline.expand_flat_response(flat, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        chats = validated["chat_messages"]
        self.assertEqual(1, len(chats))
        self.assertEqual("all", chats[0]["target"])
        self.assertEqual("Is anyone there?", chats[0]["text"])

    def test_txt_key_leader_name_still_resolves_chat_leader(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["known_players"][0]["leader_name"] = "TXT_KEY_LEADER_CLEOPATRA"
        snapshot["known_players"][0]["leader_id"] = "LEADER_CLEOPATRA"
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("DM recipients: Cleopatra", wire)
        self.assertNotIn("TXT_KEY_LEADER_CLEOPATRA", wire)
        flat = {
            "thought.situation": "Met Egypt.",
            "thought.strategy": "DM the pharaoh.",
            "decision_summary": "Private line to Cleopatra.",
            "chat.Cleopatra": "We should talk.",
        }
        expanded = pipeline.expand_flat_response(flat, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        self.assertEqual("PLAYER_1", validated["chat_messages"][0]["target_player_id"])

    def test_production_optional_without_catalog(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"] = [
            item for item in snapshot["legal_commands"] if item.get("kind") != "queue_production"
        ]
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("cityName.production = UNIT_*", wire)
        self.assertIn("Set cityName.production if you want a specific item", wire)
        self.assertNotIn("For every city below, set production this turn", wire)

    def test_diplomacy_proposals_on_wire(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["diplomacy"]["available_proposals"] = [
            {
                "proposal_id": "PROPOSAL_EMBASSY_PLAYER_1",
                "target_player_id": "PLAYER_1",
                "proposal_index": 0,
            }
        ]
        snapshot["legal_commands"].append({
            "command_id": "CMD_propose_PROPOSAL_EMBASSY_PLAYER_1",
            "kind": "propose_deal",
            "description": "Propose EMBASSY to PLAYER_1",
            "fixed_arguments": {
                "proposal_id": "PROPOSAL_EMBASSY_PLAYER_1",
                "target_player_id": "PLAYER_1",
            },
            "parameter_domains": {},
            "affected_ids": ["PLAYER_1"],
            "runtime_status": "tested",
        })
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("diplomacy.proposal.0", wire)
        self.assertIn("CMD_propose_PROPOSAL_EMBASSY_PLAYER_1", wire)
        self.assertIn("cmd.N = CMD_propose_*", wire)

    def test_declare_war_on_wire(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append({
            "command_id": "CMD_declare_war_PLAYER_1",
            "kind": "declare_war",
            "description": "Declare war on PLAYER_1",
            "fixed_arguments": {"target_player_id": "PLAYER_1"},
            "parameter_domains": {},
            "affected_ids": ["PLAYER_1"],
            "runtime_status": "tested",
        })
        snapshot["strategic_summary"]["diplomacy_alerts"] = [
            {
                "kind": "WAR_MOVE_BLOCKED",
                "severity": "warning",
                "affected_ids": ["UNIT_1002", "PLAYER_1"],
                "text": (
                    "You tried to move UNIT_1002 into Napoleon's territory. "
                    "That would declare war. Use cmd.N = CMD_declare_war_PLAYER_1 "
                    "this turn if you want war."
                ),
            }
        ]
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("CMD_declare_war_PLAYER_1", wire)
        self.assertIn("cmd.N = CMD_declare_war_PLAYER_*", wire)
        self.assertIn("Do not walk into a rival's land to start a war", wire)
        self.assertIn("alert.diplomacy.0", wire)
        self.assertIn("CMD_declare_war_PLAYER_1 this turn if you want war", wire)
        flat = {
            "thought.situation": "Napoleon blocked the pass.",
            "thought.strategy": "Declare war, then enter.",
            "decision_summary": "Declare war on Napoleon this turn.",
            "cmd.0": "CMD_declare_war_PLAYER_1",
        }
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_declare_war_PLAYER_1", command_ids)

    def test_settle_sites_and_optional_found_city(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append({
            "command_id": "CMD_found_UNIT_SETTLER_1",
            "kind": "found_city",
            "description": "Found city with UNIT_SETTLER_1",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1"},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "tested",
        })
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("settler_1.settle.here = (16,24) inland dry", wire)
        self.assertIn("settler_1.settle.look = (14,22)+2 coast river ruins DEER", wire)
        self.assertIn("foundcity is optional", wire.lower())
        self.assertIn("gold hex rings mark better settle tiles", wire)
        self.assertNotIn("as soon as a legal tile is available", wire)
        instructions = civ5_wire.build_civ5_response_instructions(snapshot)
        self.assertIn("foundCity is optional", instructions)

    def test_required_policy_promotion_maya_and_expansion_hints(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["your_cities"] = [snapshot["your_cities"][0]]
        snapshot["your_units"] = [
            {
                **snapshot["your_units"][2],
                "needs_orders": True,
                "promotion_ready": True,
            }
        ]
        snapshot["your_empire"]["unit_counts"]["settlers"] = 0
        snapshot["your_empire"]["commerce"]["culture"] = {
            "percent": 0,
            "rate": 5,
            "stored": 40,
            "next_policy_cost": 36,
            "free_policies": 1,
        }
        snapshot["legal_commands"].extend([
            {
                "command_id": "CMD_policy_TRADITION",
                "kind": "adopt_social_policy",
                "fixed_arguments": {"policy_id": "POLICY_TRADITION"},
                "parameter_domains": {},
                "runtime_status": "tested",
            },
            {
                "command_id": "CMD_promote_UNIT_SPEARMAN_1_PROMOTION_COMBAT1",
                "kind": "promote_unit",
                "fixed_arguments": {
                    "unit_id": "UNIT_SPEARMAN_1",
                    "promotion_id": "PROMOTION_COMBAT1",
                },
                "parameter_domains": {},
                "runtime_status": "tested",
            },
            {
                "command_id": "CMD_maya_UNIT_SCIENTIST",
                "kind": "choose_maya_bonus",
                "fixed_arguments": {"unit_type_id": "UNIT_SCIENTIST"},
                "parameter_domains": {},
                "runtime_status": "tested",
            },
        ])
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn("legal.policy = POLICY_TRADITION", wire)
        self.assertIn("spearman_1.promote = PROMOTION_COMBAT1", wire)
        self.assertIn("legal.mayaBonus = UNIT_SCIENTIST", wire)
        self.assertIn("empire.culture = 40 (+5)", wire)
        self.assertIn("empire.culture.nextPolicy = 36", wire)
        self.assertIn("policy screen blocks End Turn", wire)
        self.assertIn("UNIT_SETTLER", wire)
        instructions = civ5_wire.build_civ5_response_instructions(snapshot)
        self.assertIn("Do not queue a worker first", instructions)
        self.assertIn("legal.policy", instructions)
        self.assertIn("unitId.promote", instructions)

    def test_early_game_expansion_instructions_only_through_turn_15(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["decision"]["turn"] = 8
        early = civ5_wire.build_civ5_response_instructions(snapshot)
        self.assertIn("Exploration and early expansion", early)
        self.assertIn("advances exploration, expansion, or defense", early)
        self.assertIn("exploration, expansion", early)
        snapshot["decision"]["turn"] = 16
        later = civ5_wire.build_civ5_response_instructions(snapshot)
        self.assertNotIn("Exploration and early expansion", later)
        self.assertNotIn("advances exploration, expansion, or defense", later)
        self.assertIn("your path to victory and this turn's actions", later)
        snapshot["decision"]["turn"] = 40
        snapshot["game"]["game_speed_id"] = "GAMESPEED_MARATHON"
        marathon = civ5_wire.build_civ5_response_instructions(snapshot)
        self.assertIn("Exploration and early expansion", marathon)

    def test_promote_wire_resolves_to_command(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append({
            "command_id": "CMD_promote_UNIT_SPEARMAN_1_PROMOTION_COMBAT1",
            "kind": "promote_unit",
            "fixed_arguments": {
                "unit_id": "UNIT_SPEARMAN_1",
                "promotion_id": "PROMOTION_COMBAT1",
            },
            "parameter_domains": {},
            "runtime_status": "tested",
        })
        flat = {
            "thought.situation": "Veteran spearman.",
            "thought.strategy": "Take Combat I.",
            "decision_summary": "Promote spearman.",
            "spearman_1.promote": "PROMOTION_COMBAT1",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_promote_UNIT_SPEARMAN_1_PROMOTION_COMBAT1", command_ids)

    def test_need_orders_covers_ranged_air_and_religious_units(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        base = snapshot["your_units"][0]
        archer = {
            **base,
            "unit_id": "UNIT_ARCHER_1",
            "unit_type_id": "UNIT_ARCHER",
            "unit_class_id": "UNITCLASS_ARCHER",
            "domain_id": "DOMAIN_LAND",
            "needs_orders": True,
            "can_act": True,
            "range": 2,
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
        }
        bomber = {
            **base,
            "unit_id": "UNIT_BOMBER_1",
            "unit_type_id": "UNIT_BOMBER",
            "unit_class_id": "UNITCLASS_BOMBER",
            "domain_id": "DOMAIN_AIR",
            "needs_orders": True,
            "can_act": True,
            "range": 10,
            "movement": {"current": 0, "maximum": 0, "change_per_turn": 0},
        }
        missionary = {
            **base,
            "unit_id": "UNIT_MISSIONARY_1",
            "unit_type_id": "UNIT_MISSIONARY",
            "unit_class_id": "UNITCLASS_MISSIONARY",
            "domain_id": "DOMAIN_LAND",
            "needs_orders": True,
            "can_act": True,
            "movement": {"current": 4, "maximum": 4, "change_per_turn": 0},
        }
        paratrooper = {
            **base,
            "unit_id": "UNIT_PARATROOPER_1",
            "unit_type_id": "UNIT_PARATROOPER",
            "unit_class_id": "UNITCLASS_PARATROOPER",
            "domain_id": "DOMAIN_LAND",
            "needs_orders": True,
            "can_act": True,
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
        }
        snapshot["your_units"].extend([archer, bomber, missionary, paratrooper])

        def _cmd(kind: str, unit_id: str, **extra: object) -> dict:
            prefix = {
                "spread_religion": "spread",
                "remove_heresy": "heresy",
                "air_patrol": "intercept",
                "upgrade_unit": "upgrade",
            }.get(kind, kind)
            args = {"unit_id": unit_id, **extra}
            suffix = f"_{extra['unit_type_id']}" if "unit_type_id" in extra else ""
            affected = [unit_id]
            extra_id = extra.get("unit_type_id")
            if isinstance(extra_id, str):
                affected.append(extra_id)
            return {
                "command_id": f"CMD_{prefix}_{unit_id}{suffix}",
                "kind": kind,
                "description": kind,
                "fixed_arguments": args,
                "parameter_domains": {},
                "affected_ids": affected,
                "runtime_status": "tested",
            }

        snapshot["legal_commands"].extend([
            _cmd("move_unit", "UNIT_ARCHER_1"),
            _cmd("attack_target", "UNIT_ARCHER_1"),
            _cmd("range_attack", "UNIT_ARCHER_1"),
            _cmd("unit_skip", "UNIT_ARCHER_1"),
            _cmd("rebase", "UNIT_BOMBER_1"),
            _cmd("range_attack", "UNIT_BOMBER_1"),
            _cmd("air_patrol", "UNIT_BOMBER_1"),
            _cmd("unit_skip", "UNIT_BOMBER_1"),
            _cmd("move_unit", "UNIT_MISSIONARY_1"),
            _cmd("spread_religion", "UNIT_MISSIONARY_1"),
            _cmd("unit_skip", "UNIT_MISSIONARY_1"),
            _cmd("move_unit", "UNIT_PARATROOPER_1"),
            _cmd("paradrop", "UNIT_PARATROOPER_1"),
            _cmd("pillage", "UNIT_PARATROOPER_1"),
            _cmd("upgrade_unit", "UNIT_PARATROOPER_1", unit_type_id="UNIT_INFANTRY"),
            _cmd("unit_skip", "UNIT_PARATROOPER_1"),
        ])
        wire = civ5_wire.build_civ5_model_wire_text(snapshot)
        self.assertIn(
            "archer_1 can [moveTo | attackTo | rangedAttack | stance=skip]. "
            "archer_1 can move 2 tiles this turn. archer_1 can rangedAttack 2 tiles.",
            wire,
        )
        self.assertNotIn("range_attack", wire)
        self.assertNotIn("attack_target", wire)
        self.assertIn(
            "bomber_1 can [rebaseTo | rangedAttack | intercept | stance=skip]. "
            "bomber_1 can rangedAttack 10 tiles.",
            wire,
        )
        self.assertNotIn("bomber_1 can move", wire)
        self.assertNotIn("bomber_1 can [moveTo", wire)
        self.assertIn(
            "missionary_1 can [moveTo | spread | stance=skip]. missionary_1 can move 4 tiles",
            wire,
        )
        self.assertIn(
            "paratrooper_1 can [moveTo | paradropTo | pillage | upgrade=UNIT_INFANTRY | stance=skip]. "
            "paratrooper_1 can move 2 tiles",
            wire,
        )
        self.assertIn("unitId.rangedAttack = (x,y)", wire)
        self.assertIn("unitId.upgrade = UNIT_*", wire)
        self.assertIn("unitId.rebaseTo = (x,y)", wire)
        self.assertIn("unitId.spread = apply", wire)
        self.assertIn("Aircraft rebase", wire)
        self.assertIn("Religious units walk", wire)

        flat = {
            "thought.situation": "Special unit orders.",
            "thought.strategy": "Strike, rebase, spread, and jump.",
            "decision_summary": "Use each special ability.",
            "archer_1.rangedAttack": "(20,21)",
            "bomber_1.rebaseTo": "(10,11)",
            "missionary_1.spread": "apply",
            "paratrooper_1.paradropTo": "(12,13)",
            "paratrooper_1.upgrade": "UNIT_INFANTRY",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_range_UNIT_ARCHER_1_20_21", command_ids)
        self.assertIn("CMD_rebase_UNIT_BOMBER_1_10_11", command_ids)
        self.assertIn("CMD_spread_UNIT_MISSIONARY_1", command_ids)
        self.assertIn("CMD_paradrop_UNIT_PARATROOPER_1_12_13", command_ids)
        self.assertIn("CMD_upgrade_UNIT_PARATROOPER_1_UNIT_INFANTRY", command_ids)


if __name__ == "__main__":
    unittest.main()
