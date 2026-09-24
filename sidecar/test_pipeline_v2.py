import copy
from typing import Any
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from urllib import error as urllib_error

from sidecar import pipeline_v2 as p
from sidecar import map_render
from sidecar import run_v2


def amount(current=0, maximum=0, change=0):
    return {"current": current, "maximum": maximum, "change_per_turn": change}


def commerce():
    return {key: {"percent": 25, "rate": 1} for key in ("gold", "research", "culture", "espionage")}


def relation():
    return {"met": True, "at_war": False, "open_borders": False, "defensive_pact": False,
            "vassal": False, "attitude_id": "ATTITUDE_CAUTIOUS", "attitude_value": 0}


def snapshot():
    empty_summary = {key: [] for key in ("city_alerts", "economy_alerts", "military_alerts", "diplomacy_alerts", "resource_alerts")}
    empty_summary["ratios"] = []
    return {
        "schema_version": "civ4ai-input/2",
        "decision": {"turn": 1, "year": 500, "phase": "strategic_decision", "player_id": "PLAYER_0", "reason": "test"},
        "personality": {"identity": "alexander-0", "leader_id": "LEADER_ALEXANDER", "leader_name": "Alexander",
            "civilization_id": "CIVILIZATION_GREECE"},
        "game": {"era_id": "ERA_MEDIEVAL", "start_era_id": "ERA_MEDIEVAL", "game_speed_id": "GAMESPEED_QUICK",
            "difficulty_id": "HANDICAP_NOBLE", "calendar_id": "CALENDAR_DEFAULT", "map_script": "Duel.py",
            "world_size_id": "WORLDSIZE_DUEL", "climate_id": "CLIMATE_TEMPERATE", "sea_level_id": "SEALEVEL_MEDIUM",
            "map_width": 2, "map_height": 1, "wrap_x": False, "wrap_y": False, "max_turns": 500,
            "options": [], "victory_ids": ["VICTORY_CONQUEST"], "network_multiplayer": False},
        "your_empire": {"team_id": "TEAM_0", "score": 100, "gold": 50, "gold_per_turn": 3, "commerce": commerce(),
            "costs": {"unit_cost": 1, "unit_supply": 0, "city_maintenance": 1, "civic_upkeep": 0, "inflation": 0},
            "research": {"tech_id": "TECH_FEUDALISM", "progress": 10, "cost": 100, "research_per_turn": 10,
                "estimated_turns_remaining": 9, "queue": ["TECH_FEUDALISM"], "known_tech_ids": ["TECH_AGRICULTURE"]},
            "civics": [{"key": "CIVICOPTION_GOVERNMENT", "id": "CIVIC_DESPOTISM"}],
            "religion": {"state_religion_id": None, "convertible_religion_ids": [], "conversion_timer": 0},
            "resources": [], "unit_counts": {"total": 1, "workers": 0, "settlers": 0, "military": 1,
                "missionaries": 0, "spies": 0, "great_people": 0, "idle": 1, "upgradeable": 0},
            "anarchy_turns": 0, "golden_age_turns": 0, "war_weariness": 0, "victory_progress": []},
        "your_cities": [{"city_id": "CITY_0", "name": "Athens", "plot_id": "PLOT_0_0", "area_id": "AREA_0",
            "is_capital": True, "is_coastal": False, "population": 2, "food": amount(5, 22, 2),
            "production": {"item_id": "UNIT_ARCHER", "progress": 3, "cost": 25, "production_per_turn": 4, "estimated_turns_remaining": 6},
            "production_queue": [{"order_index": 0, "kind": "unit", "item_id": "UNIT_ARCHER", "progress": 3, "cost": 25}],
            "yields": {"food": 4, "production": 3, "commerce": 2}, "commerce": commerce(),
            "happiness": {"positive": 3, "negative": 1, "net": 2}, "health": {"positive": 3, "negative": 1, "net": 2},
            "maintenance": 1, "culture": amount(10, 100, 2), "great_people": amount(0, 100, 0), "specialists": [],
            "buildings": ["BUILDING_PALACE"], "religions": [], "corporations": [], "trade_routes": [],
            "worked_plot_ids": ["PLOT_0_0"], "automation": {"citizens": False, "production": False},
            "defense": {"percent": 20, "bombard_damage": 0}, "occupation_turns": 0, "garrison_unit_ids": ["UNIT_0"]}],
        "your_units": [{"unit_id": "UNIT_0", "unit_type_id": "UNIT_ARCHER", "unit_class_id": "UNITCLASS_ARCHER",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_0_0", "health": amount(100, 100, 0), "strength": amount(3, 3, 0),
            "movement": amount(1, 1, 0), "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_CITY_DEFENSE", "cargo_unit_ids": [], "can_act": True,
            "needs_orders": True, "upgrade_options": []}],
        "known_players": [{"player_id": "PLAYER_1", "team_id": "TEAM_1", "leader_id": "LEADER_CAESAR",
            "civilization_id": "CIVILIZATION_ROME", "score": 90, "population": 2, "land": 5, "power": 80,
            "known_capital_city_id": "CITY_1", "known_religion_id": None, "known_civic_ids": [], "known_tech_ids": [], "relation": relation()}],
        "known_other_cities": [{"city_id": "CITY_1", "owner_player_id": "PLAYER_1", "name": "Rome", "plot_id": "PLOT_1_0",
            "area_id": "AREA_0", "knowledge": "visible", "last_seen_turn": 1, "population": 2, "is_capital": True, "visible_defense": 20}],
        "visible_other_units": [],
        "diplomacy": {"relations": [{"player_id": "PLAYER_1", "relation": relation()}], "active_deals": [],
            "pending_requests": [], "available_proposals": [], "legal_trade_inventory": [], "private_inbox": []},
        "known_map": {"format": "plot-grid-v1", "visibility_mode": "player_visible",
            "plots": [{"plot_id": "PLOT_0_0", "x": 0, "y": 0, "knowledge": "visible", "last_seen_turn": 1,
                "area_id": "AREA_0", "terrain_id": "TERRAIN_GRASS", "water": False, "hills": False, "peak": False,
                "fresh_water": True, "river_edges": [], "revealed_owner_id": "PLAYER_0", "feature_id": None,
                "improvement_id": None, "route_id": None, "resource_id": None, "yields": {"food": 2, "production": 1, "commerce": 0},
                "defense_percent": 0, "city_id": "CITY_0", "worked_by_city_id": "CITY_0", "visible_stack_ids": []}],
            "areas": [{"area_id": "AREA_0", "water": False, "revealed_plot_count": 1}], "frontiers": [], "visible_stacks": [],
            "image": {"attached": True, "format": "png-grid-v1", "width": 8, "height": 4,
                "legend": [{"symbol": "green", "meaning": "grass"}], "label_ids": ["CITY_0"]}},
        "strategic_summary": empty_summary,
        "history": {"accepted_decisions": [], "command_results": [], "public_events": [], "diplomacy_events": [], "memory_summary": "Defend Athens."},
        "advciv": {"default_unit_controller": "advciv", "fallback_policy": p.ADVCIV_FALLBACK_POLICY,
            "recommendations": [{"recommendation_id": "REC_RESEARCH", "kind": "research", "execution_state": "applied_reversible",
                "summary": "Research Feudalism", "rationale_facts": ["Military defense"], "affected_ids": ["TECH_FEUDALISM"],
                "proposed_command_ids": ["CMD_RESEARCH"]}]},
        "legal_commands": [{"command_id": "CMD_RESEARCH", "kind": "choose_research", "description": "Research Feudalism",
            "fixed_arguments": {"tech_id": "TECH_FEUDALISM"}, "parameter_domains": {}, "affected_ids": ["TECH_FEUDALISM"], "runtime_status": "tested"},
            {"command_id": "CMD_SLIDER", "kind": "change_commerce", "description": "Set research slider",
             "fixed_arguments": {}, "parameter_domains": {"percent": {"type": "integer", "minimum": 0, "maximum": 100, "step": 10}},
             "affected_ids": ["PLAYER_0"], "runtime_status": "implemented_untested"}]
    }


def sample_thought():
    return {
        "situation": "Greece holds Athens with one archer defending.",
        "strategy": "Research Feudalism and fortify the capital.",
    }


def with_thought(response: dict) -> dict:
    merged = dict(response)
    if "thought" not in merged:
        merged["thought"] = sample_thought()
    return merged


def minimal_model_response():
    return {
        "thought": sample_thought(),
        "decision_summary": "Hold and research.",
        "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "accept"}],
        "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}}],
        "chat_messages": [{
            "target": "all",
            "text": "Status: defend Athens. Plan: research. Action: CMD_RESEARCH.",
            "grounding_ids": ["CITY_0"],
        }],
    }


class PipelineV2Tests(unittest.TestCase):
    def test_current_legacy_fixture_upgrades_to_v2_and_selects_research(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        state = p.build_model_input(legacy)
        self.assertEqual("civ4ai-input/2", state["schema_version"])
        self.assertTrue(any(item["kind"] == "choose_research" for item in state["legal_commands"]))

    def test_legacy_city_metrics_are_preserved_in_v2_snapshot(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["cities"][0].update({"food": 7, "food_difference": 2, "production": 4, "production_needed": 20,
            "production_turns_left": 4, "happy": 3, "unhappy": 1, "health": 2, "unhealth": 1,
            "production_per_turn": 5, "commerce_gold": 2, "commerce_research": 8, "commerce_culture": 1,
            "commerce_espionage": 0, "yield_food": 9, "yield_production": 5, "yield_commerce": 7,
            "maintenance": 3, "culture": 20, "great_people_progress": 12, "great_people_rate": 2,
            "defense_damage": 4, "occupation_turns": 1, "citizens_automated": True,
            "production_automated": False, "production_queue": [{"order_index": 0, "kind": "building",
                "item_id": "BUILDING_GRANARY", "progress": 4, "cost": 20}],
            "buildings": ["BUILDING_PALACE"], "specialists": [{"specialist_id": "SPECIALIST_SCIENTIST",
                "assigned": 1, "free": 0, "joined": 0}], "religions": ["RELIGION_BUDDHISM"],
            "corporations": [], "worked_plot_ids": ["PLOT_1_1"]})
        state = p.build_model_input(legacy)
        city = state["your_cities"][0]
        self.assertEqual(7, city["food"]["current"])
        self.assertEqual(20, city["production"]["cost"])
        self.assertEqual(8, city["commerce"]["research"]["rate"])
        self.assertEqual("BUILDING_GRANARY", city["production"]["item_id"])
        self.assertEqual(["BUILDING_PALACE"], city["buildings"])
        self.assertEqual(1, city["specialists"][0]["assigned"])
        self.assertEqual(9, city["yields"]["food"])
        self.assertTrue(city["automation"]["citizens"])

    def test_unrevealed_grid_cells_are_not_in_model_snapshot(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["width"] = legacy["settings"]["width"] = 2
        legacy["visible"]["height"] = legacy["settings"]["height"] = 1
        legacy["visible"]["grid"] = [".?"]
        legacy["visible"].pop("plots", None)
        state = p.build_model_input(legacy)
        self.assertEqual(["PLOT_0_0"], [row["plot_id"] for row in state["known_map"]["plots"]])

    def test_dll_plot_visibility_and_revealed_owner_are_preserved(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["plots"] = [{
            "plot_id": "PLOT_1_2", "x": 1, "y": 2, "knowledge": "remembered", "last_seen_turn": None,
            "area_id": "AREA_3", "terrain_id": "TERRAIN_PLAINS", "water": False, "hills": True,
            "peak": False, "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_2",
            "feature_id": None, "improvement_id": "IMPROVEMENT_FARM", "route_id": "ROUTE_ROAD",
            "resource_id": "BONUS_WHEAT", "yields": {"food": 0, "production": 0, "commerce": 0},
            "defense_percent": 25, "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []}]
        state = p.build_model_input(legacy)
        plot = state["known_map"]["plots"][0]
        self.assertEqual("remembered", plot["knowledge"])
        self.assertEqual("PLAYER_2", plot["revealed_owner_id"])
        self.assertEqual("IMPROVEMENT_FARM", plot["improvement_id"])

    def test_legacy_unit_detail_is_preserved_in_v2_snapshot(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["units"][0].update({"unit_class_id": "UNITCLASS_ARCHER", "domain_id": "DOMAIN_LAND",
            "health_current": 73, "health_max": 100, "moves_left": 30, "max_moves": 60, "level": 3,
            "experience": 8, "activity_id": "ACTIVITY_HEAL", "unit_ai_role": "UNITAI_CITY_DEFENSE",
            "promotions": ["PROMOTION_COMBAT1"], "mission_queue": [{"mission_id": "MISSION_HEAL",
                "target_plot_id": None}], "cargo_unit_ids": [], "upgrade_options": [{"unit_type_id": "UNIT_LONGBOWMAN",
                "gold_cost": 80}], "needs_orders": False})
        state = p.build_model_input(legacy)
        unit = state["your_units"][0]
        self.assertEqual(73, unit["health"]["current"])
        self.assertEqual("UNITCLASS_ARCHER", unit["unit_class_id"])
        self.assertEqual(["PROMOTION_COMBAT1"], unit["promotion_ids"])
        self.assertEqual("MISSION_HEAL", unit["mission_queue"][0]["mission_id"])
        self.assertEqual(80, unit["upgrade_options"][0]["gold_cost"])

    def test_dll_empire_detail_is_preserved_in_v2_snapshot(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["empire"] = {"team_id": "TEAM_0", "score": 321, "gold": 88, "gold_per_turn": -3,
            "commerce": {key: {"percent": 25, "rate": index + 1} for index, key in enumerate(("gold", "research", "culture", "espionage"))},
            "costs": {"unit_cost": 4, "unit_supply": 2, "city_maintenance": 7, "civic_upkeep": 3, "inflation": 1},
            "research_queue": ["TECH_GUILDS"], "known_tech_ids": ["TECH_FEUDALISM"],
            "civics": [{"key": "CIVICOPTION_GOVERNMENT", "id": "CIVIC_HEREDITARY_RULE"}],
            "state_religion_id": "RELIGION_BUDDHISM", "resources": [{"resource_id": "BONUS_IRON",
                "available": 2, "surplus": 1, "imported": 0, "exported": 0}],
            "unit_counts": {"total": 8, "workers": 2, "settlers": 1, "military": 5, "missionaries": 0,
                "spies": 0, "great_people": 0, "idle": 3, "upgradeable": 2},
            "anarchy_turns": 0, "golden_age_turns": 4, "war_weariness": 6}
        state = p.build_model_input(legacy)
        empire = state["your_empire"]
        self.assertEqual(321, empire["score"])
        self.assertEqual(-3, empire["gold_per_turn"])
        self.assertEqual(["TECH_GUILDS"], empire["research"]["queue"])
        self.assertEqual("RELIGION_BUDDHISM", empire["religion"]["state_religion_id"])
        self.assertEqual(2, empire["unit_counts"]["workers"])

    def test_public_players_relations_and_typed_deals_are_preserved(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["public"]["players"] = [{"id": "PLAYER_1", "team_id": 1, "leader_id": "LEADER_CAESAR",
            "civilization_id": "CIVILIZATION_ROME", "score": 90, "population": 3, "land": 12, "power": 80,
            "at_war": False, "capital_city_id": "CITY_1_0"}]
        legacy["visible"]["diplomacy"] = [{"other_player_id": "PLAYER_1", "at_war": False,
            "open_borders": True, "defensive_pact": False, "attitude_id": 2, "war_plan_id": 0}]
        legacy["visible"]["active_deals"] = [{"deal_id": "DEAL_3", "other_player_id": "PLAYER_1",
            "our_items": [{"trade_item_id": "DEAL_3_OUR_0", "kind": "TRADE_RESOURCES",
                "data_id": "BONUS_IRON", "amount": None, "denial_id": None}], "their_items": [],
            "turns_active": 4, "cancelable": True}]
        state = p.build_model_input(legacy)
        self.assertEqual("CIVILIZATION_ROME", state["known_players"][0]["civilization_id"])
        self.assertTrue(state["diplomacy"]["relations"][0]["relation"]["open_borders"])
        self.assertEqual("BONUS_IRON", state["diplomacy"]["active_deals"][0]["our_items"][0]["data_id"])

    def test_known_players_only_include_snapshot_public_players(self):
        """DLL omits unmet civs from public.players; sidecar must not invent rivals."""
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["public"]["players"] = [
            {"id": "PLAYER_1", "team_id": 1, "leader_id": "LEADER_CAESAR",
                "civilization_id": "CIVILIZATION_ROME", "score": 90, "population": 3,
                "land": 12, "power": 80, "at_war": False},
        ]
        state = p.build_model_input(legacy)
        self.assertEqual(["PLAYER_1"], [row["player_id"] for row in state["known_players"]])
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("rival.PLAYER_1.score", wire)
        self.assertNotIn("rival.PLAYER_2", wire)

    def test_pending_diplomacy_preserves_exact_typed_offer_and_responses(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_requests"] = [{"request_id": "DIPLO_TRADE_0_1",
            "from_player_id": "PLAYER_1", "comment_id": 7,
            "our_items": [{"trade_item_id": "DIPLO_TRADE_0_1_OUR_0", "kind": "TRADE_GOLD",
                "data_id": None, "amount": 30, "denial_id": None}],
            "their_items": [{"trade_item_id": "DIPLO_TRADE_0_1_THEIR_0", "kind": "TRADE_RESOURCES",
                "data_id": "BONUS_IRON", "amount": None, "denial_id": None}],
            "response_ids": ["DIPLO_ACCEPT", "DIPLO_REJECT"]}]
        request = p.build_model_input(legacy)["diplomacy"]["pending_requests"][0]
        self.assertEqual(["DIPLO_ACCEPT", "DIPLO_REJECT"], request["legal_response_ids"])
        self.assertEqual("TRADE_GOLD", request["our_items"][0]["kind"])
        self.assertEqual("TRADE_RESOURCES", request["their_items"][0]["kind"])
        self.assertEqual("diplomacy_request", p.build_model_input(legacy)["decision"]["reason"])

    def test_pending_diplomacy_wire_shows_trade_terms_and_response_cmds(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_requests"] = [{"request_id": "DIPLO_TRADE_0_1",
            "from_player_id": "PLAYER_1", "comment_id": 7,
            "our_items": [{"trade_item_id": "DIPLO_TRADE_0_1_OUR_0", "kind": "TRADE_GOLD",
                "data_id": None, "amount": 30, "denial_id": None}],
            "their_items": [{"trade_item_id": "DIPLO_TRADE_0_1_THEIR_0", "kind": "TRADE_RESOURCES",
                "data_id": "BONUS_IRON", "amount": None, "denial_id": None}],
            "response_ids": ["DIPLO_ACCEPT", "DIPLO_REJECT"]}]
        legacy["legal_actions"] = [{"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_ACCEPT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_ACCEPT"},
            {"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_REJECT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_REJECT"}]
        state = p.build_model_input(legacy)
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("diplomacy.pending.0.we_give = gold(30)", wire)
        self.assertIn("diplomacy.pending.0.they_give = resources:iron", wire)
        self.assertIn("diplomacy.pending.0.accept_cmd =", wire)
        self.assertIn("diplomacy.pending.0.reject_cmd =", wire)

    def test_pending_trade_offer_adds_mandatory_response_instructions(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_requests"] = [{"request_id": "DIPLO_TRADE_0_1",
            "from_player_id": "PLAYER_1", "comment_id": 7,
            "our_items": [{"trade_item_id": "DIPLO_TRADE_0_1_OUR_0", "kind": "TRADE_GOLD",
                "data_id": None, "amount": 30, "denial_id": None}],
            "their_items": [{"trade_item_id": "DIPLO_TRADE_0_1_THEIR_0", "kind": "TRADE_RESOURCES",
                "data_id": "BONUS_IRON", "amount": None, "denial_id": None}],
            "response_ids": ["DIPLO_ACCEPT", "DIPLO_REJECT"]}]
        legacy["legal_actions"] = [{"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_ACCEPT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_ACCEPT"},
            {"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_REJECT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_REJECT"}]
        state = p.build_model_input(legacy)
        instructions = p._model_response_instructions(state)
        self.assertIn("TRADE OFFER — RESPOND THIS TURN", instructions)
        self.assertIn("Respond only while that exact offer is still pending", instructions)
        self.assertIn("accept_cmd", instructions)
        self.assertIn("reject_cmd", instructions)
        self.assertIn("counteroffer_cmd", instructions)
        self.assertIn("chat.LeaderName", instructions)

    def test_diplomacy_proposals_surface_in_model_input_and_wire(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_proposals"] = [{"proposal_id": "PROPOSAL_OPEN_BORDERS_1",
            "target_player_id": "PLAYER_1", "proposal_index": 0}]
        legacy["legal_actions"] = [{"action_id": "propose_diplomacy:PROPOSAL_OPEN_BORDERS_1",
            "kind": "propose_diplomacy", "proposal_id": "PROPOSAL_OPEN_BORDERS_1",
            "target_player_id": "PLAYER_1", "proposal_index": 0}]
        state = p.build_model_input(legacy)
        proposals = state["diplomacy"]["available_proposals"]
        self.assertEqual(1, len(proposals))
        self.assertEqual("PROPOSAL_OPEN_BORDERS_1", proposals[0]["proposal_id"])
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("diplomacy.proposal.0 = PLAYER_1:PROPOSAL_OPEN_BORDERS_1", wire)

    def test_counteroffer_trade_terms_attach_to_pending_request(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_requests"] = [{"request_id": "DIPLO_TRADE_0_1",
            "from_player_id": "PLAYER_1", "comment_id": 7, "our_items": [], "their_items": [],
            "response_ids": ["DIPLO_ACCEPT", "DIPLO_REJECT"]}]
        legacy["visible"]["counteroffer_proposals"] = [{"counteroffer_id": "COUNTER_0_1",
            "request_id": "DIPLO_TRADE_0_1", "from_player_id": "PLAYER_1", "counteroffer_index": 0,
            "our_items": [{"trade_item_id": "COUNTER_0_1_OUR_0", "kind": "TRADE_OPEN_BORDERS",
                "data_id": None, "amount": None, "denial_id": None}],
            "their_items": [{"trade_item_id": "COUNTER_0_1_THEIR_0", "kind": "TRADE_GOLD",
                "data_id": None, "amount": 50, "denial_id": None}]}]
        legacy["legal_actions"] = {
            "counteroffer_diplomacy": [{"action_id": "counteroffer_diplomacy:DIPLO_TRADE_0_1:COUNTER_0_1",
                "kind": "counteroffer_diplomacy", "request_id": "DIPLO_TRADE_0_1",
                "counteroffer_id": "COUNTER_0_1", "v2_kind": "counteroffer"}],
        }
        state = p.build_model_input(legacy)
        counter = state["diplomacy"]["pending_requests"][0]["counteroffer"]
        self.assertEqual("TRADE_OPEN_BORDERS", counter["our_items"][0]["kind"])
        self.assertEqual("TRADE_GOLD", counter["their_items"][0]["kind"])
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("diplomacy.pending.0.counter_we_give = open_borders", wire)
        self.assertIn("diplomacy.pending.0.counter_they_give = gold(50)", wire)
        self.assertIn("diplomacy.pending.0.counteroffer_cmd =", wire)

    def test_pending_diplomacy_response_is_closed_host_command(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["diplomacy_requests"] = [{"request_id": "DIPLO_TRADE_0_1",
            "from_player_id": "PLAYER_1", "comment_id": 7, "our_items": [], "their_items": [],
            "response_ids": ["DIPLO_ACCEPT", "DIPLO_REJECT"]}]
        legacy["legal_actions"] = [{"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_ACCEPT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_ACCEPT"},
            {"action_id": "respond_diplomacy:DIPLO_TRADE_0_1:DIPLO_REJECT",
            "kind": "respond_diplomacy", "request_id": "DIPLO_TRADE_0_1", "response_id": "DIPLO_REJECT"}]
        # The model sees only exact catalog entries and cannot alter the offer.
        # Runtime conversion is separately source-checked because Civ IV uses Python 2.
        state = p.build_model_input(legacy)
        response_commands = [row for row in state["legal_commands"] if row["kind"] == "respond_to_deal"]
        self.assertEqual(2, len(response_commands))
        self.assertEqual({"DIPLO_ACCEPT", "DIPLO_REJECT"},
            {row["fixed_arguments"]["response_id"] for row in response_commands})

    def test_cancel_deal_and_counteroffer_map_to_v2_kinds(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["active_deals"] = [{"deal_id": "DEAL_12", "other_player_id": "PLAYER_1",
            "our_items": [], "their_items": [], "turns_active": 3, "cancelable": True}]
        legacy["visible"]["counteroffer_proposals"] = [{"counteroffer_id": "COUNTER_0_1",
            "request_id": "DIPLO_TRADE_0_1", "from_player_id": "PLAYER_1", "counteroffer_index": 0}]
        legacy["legal_actions"] = {
            "cancel_deal": [{"action_id": "cancel_deal:DEAL_12", "kind": "cancel_deal",
                "deal_id": "DEAL_12", "v2_kind": "cancel_deal"}],
            "counteroffer_diplomacy": [{"action_id": "counteroffer_diplomacy:DIPLO_TRADE_0_1:COUNTER_0_1",
                "kind": "counteroffer_diplomacy", "request_id": "DIPLO_TRADE_0_1",
                "counteroffer_id": "COUNTER_0_1", "v2_kind": "counteroffer"}],
        }
        state = p.build_model_input(legacy)
        kinds = {row["kind"] for row in state["legal_commands"]}
        self.assertIn("cancel_deal", kinds)
        self.assertIn("counteroffer", kinds)

    def test_each_upgraded_legal_command_has_a_closed_host_catalog_entry(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        state = p.build_model_input(legacy)
        for command in state["legal_commands"]:
            response = with_thought({"decision_summary": "test", "recommendation_decisions": [],
                "commands": [{"command_id": command["command_id"], "arguments": {}}],
                "chat_messages": []})
            result = p.validate_model_response(state, response)
            self.assertEqual([], result["rejections"], command["command_id"])

    def test_generic_game_adapter_keeps_specific_model_command_kind(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["legal_actions"] = [{"action_id": "city_task:CITY_0_0:TASK_CONSCRIPT:INT_0:INT_0",
            "kind": "city_task", "v2_kind": "draft_unit", "city_id": "CITY_0_0",
            "task_id": "TASK_CONSCRIPT", "data1_id": "INT_0", "data2_id": "INT_0"}]
        state = p.build_model_input(legacy)
        command = state["legal_commands"][0]
        self.assertEqual("draft_unit", command["kind"])
        self.assertNotIn("v2_kind", command["fixed_arguments"])

    def test_advc_reversible_recommendations_enter_prompt_without_duplicate_execution(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        action_id = legacy["legal_actions"][0]["action_id"] if isinstance(legacy["legal_actions"], list) else legacy["legal_actions"]["set_research"][0]["action_id"]
        legacy["advc_recommendations"] = [{"recommendation_id": "REC_CURRENT_RESEARCH", "kind": "research",
            "execution_state": "applied_reversible", "summary": "Continue native research", "rationale_facts": [],
            "affected_ids": ["TECH_AGRICULTURE"], "proposed_action_ids": [action_id]}]
        state = p.build_model_input(legacy)
        recommendation = state["advciv"]["recommendations"][0]
        self.assertEqual("applied_reversible", recommendation["execution_state"])
        validated = p.validate_model_response(state, with_thought({"decision_summary": "retain", "recommendation_decisions": [],
            "commands": [], "chat_messages": []}))
        resolution = p.resolve_recommendations(state, validated, lambda _rec: None)
        self.assertEqual([], resolution["selected_command_ids"])

    def test_multi_command_batch_receives_contiguous_host_sequences(self):
        state = snapshot()
        response = with_thought({"decision_summary": "two independent choices", "recommendation_decisions": [],
            "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}},
                         {"command_id": "CMD_SLIDER", "arguments": {"percent": 50}}], "chat_messages": []})
        validated = p.validate_model_response(state, response)
        private = {"game_uuid": "G", "turn": 1, "phase": "strategic_decision", "player_id": "PLAYER_0",
            "state_hash": "S", "catalog_hash": "C", "dll_fingerprint": "D", "sequence_cursor": 0,
            "legal_commands": {item["command_id"]: item for item in state["legal_commands"]}}
        commands = p.bind_approved_commands(private, validated)
        self.assertEqual([0, 1], [item["sequence"] for item in commands])

    def test_capability_catalog_is_unique_and_only_proven_command_is_advertised_tested(self):
        catalog = json.loads((p.ROOT / "config" / "command-capabilities-v2.json").read_text(encoding="utf-8"))
        kinds = [item["kind"] for item in catalog["capabilities"]]
        self.assertEqual(len(kinds), len(set(kinds)))
        tested = sorted(item["kind"] for item in catalog["capabilities"] if item.get("runtime") == "tested")
        self.assertEqual(sorted([
            "end_turn", "auto_moves", "choose_research", "adopt_civics", "change_commerce",
            "unit_posture_mission", "found_city", "worker_build", "set_upgrade_reserve",
        ]), tested)

    def test_snapshot_is_strict_and_prompt_has_no_host_metadata(self):
        state = p.build_model_input(snapshot())
        prompt = p.build_responses_input(state)
        text = prompt[0]["content"][0]["text"]
        self.assertNotIn("game_uuid", text)
        bad = copy.deepcopy(state)
        bad["your_cities"][0]["secret"] = 1
        with self.assertRaisesRegex(p.BoundaryError, "secret"):
            p.validate_snapshot(bad)

    def test_exact_json_rejects_duplicate_and_trailing_content(self):
        with self.assertRaises(p.BoundaryError):
            p.parse_exact_json('{"commands":[],"commands":[]}')
        with self.assertRaises(p.BoundaryError):
            p.parse_exact_json('{} trailing')

    def test_valid_response_binds_private_metadata(self):
        state = snapshot()
        response = with_thought({"decision_summary": "Keep the native research choice.",
            "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "accept", "replacement_command_ids": []}],
            "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}}],
            "chat_messages": [{"target": "all", "text": "I know Athens needs defense; I will research Feudalism.", "grounding_ids": ["CITY_0"]}]})
        validated = p.validate_model_response(state, response)
        private = {"game_uuid": "G", "turn": 1, "phase": "strategic_decision", "player_id": "PLAYER_0",
            "state_hash": "S", "catalog_hash": "C", "dll_fingerprint": "D", "sequence_cursor": 4}
        commands = p.bind_approved_commands(private, validated)
        self.assertEqual(4, commands[0]["sequence"])
        self.assertNotIn("game_uuid", response)

    def test_illegal_items_are_noops_and_omitted_advice_falls_back(self):
        state = snapshot()
        response = with_thought({"decision_summary": "No override.", "recommendation_decisions": [],
            "commands": [{"command_id": "UNKNOWN", "arguments": {}}],
            "chat_messages": [{"target": "all", "text": "Invented.", "grounding_ids": ["SECRET_CITY"]}]})
        validated = p.validate_model_response(state, response)
        self.assertEqual([], validated["commands"])
        self.assertEqual(2, len(validated["rejections"]))
        self.assertEqual("applied_reversible", validated["omitted_recommendations"][0]["execution_state"])

    def test_one_valid_command_survives_broken_neighbors(self):
        state = snapshot()
        response = with_thought({"decision_summary": "Partial.", "recommendation_decisions": [],
            "commands": [
                "not-an-object",
                {"command_id": "UNKNOWN", "arguments": {}},
                {"command_id": "CMD_RESEARCH", "arguments": {}},
            ],
            "chat_messages": []})
        validated = p.validate_model_response(state, response)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertGreaterEqual(len(validated["rejections"]), 2)

    def test_applied_reversible_cannot_be_rejected(self):
        response = with_thought({"decision_summary": "Reject.",
            "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "reject", "replacement_command_ids": []}],
            "commands": [], "chat_messages": []})
        validated = p.validate_model_response(snapshot(), response)
        self.assertEqual([], validated["recommendation_decisions"])
        self.assertEqual("illegal_recommendation_decision", validated["rejections"][0]["category"])

    def test_recommendation_accept_and_replace_produce_deterministic_commands(self):
        state = snapshot()
        response = with_thought({"decision_summary": "Apply native research recommendation.",
            "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "accept", "replacement_command_ids": []}],
            "commands": [], "chat_messages": []})
        validated = p.validate_model_response(state, response)
        resolution = p.resolve_recommendations(state, validated, lambda _: None)
        self.assertEqual([], resolution["selected_command_ids"])
        self.assertEqual([], resolution["ordinary_commands"])

        state["advciv"]["recommendations"][0]["execution_state"] = "deferred_irreversible"
        replacement = with_thought({"decision_summary": "replace", "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "replace", "replacement_command_ids": ["CMD_RESEARCH"]}], "commands": [], "chat_messages": []})
        replacement_result = p.validate_model_response(state, replacement)
        replacement_resolution = p.resolve_recommendations(state, replacement_result, lambda _: None)
        self.assertEqual(["CMD_RESEARCH"], replacement_resolution["selected_command_ids"])

    def test_deferred_recommendation_uses_native_fallback_when_omitted(self):
        state = snapshot()
        state["advciv"]["recommendations"][0]["execution_state"] = "deferred_irreversible"
        called = []
        validated = p.validate_model_response(state, with_thought({"decision_summary": "fallback", "recommendation_decisions": [], "commands": [], "chat_messages": []}))
        resolution = p.resolve_recommendations(state, validated, lambda rec: called.append(rec["recommendation_id"]))
        self.assertEqual(["REC_RESEARCH"], called)
        self.assertEqual(["CMD_RESEARCH"], resolution["selected_command_ids"])

    def test_adapter_failure_does_not_stop_later_command(self):
        commands = [{"sequence": 0, "command_id": "BAD", "arguments": {}},
                    {"sequence": 1, "command_id": "GOOD", "arguments": {"x": 1}}]
        results = p.execute_commands(commands, {"BAD": lambda _: (_ for _ in ()).throw(RuntimeError("boom")), "GOOD": lambda args: args["x"]})
        self.assertEqual(["noop", "applied"], [item["status"] for item in results])

    def test_deterministic_map_png(self):
        with tempfile.TemporaryDirectory() as directory:
            first = p.render_known_map_png(snapshot(), Path(directory) / "a.png")
            second = p.render_known_map_png(snapshot(), Path(directory) / "b.png")
            self.assertEqual(first["sha256"], second["sha256"])

    def test_circuit_breaker(self):
        breaker = p.CircuitBreaker({})
        for _ in range(3):
            breaker.record("PLAYER_0", False)
        self.assertTrue(breaker.open("PLAYER_0"))
        breaker.record("PLAYER_0", True)
        self.assertFalse(breaker.open("PLAYER_0"))

    def test_circuit_breaker_skips_recoverable_decision_summary_schema_failures(self):
        breaker = p.CircuitBreaker({})
        for _ in range(3):
            breaker.record_failure("PLAYER_4", "response_schema", "decision_summary: '' should be non-empty")
        self.assertFalse(breaker.open("PLAYER_4"))
        breaker.record_failure("PLAYER_4", "response_schema", "commands: invalid")
        self.assertEqual(1, breaker.failures.get("PLAYER_4", 0))

    def test_normalize_backfills_decision_summary_from_thought_strategy(self):
        state = snapshot()
        flat = {
            "thought.situation": "Gold is zero and the warrior is idle.",
            "thought.strategy": "Shift commerce to gold and send the warrior north.",
            "cmd.1": "CMD_RESEARCH",
        }
        cleaned = p.normalize_model_response(state, p.expand_flat_response(flat))
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual("Shift commerce to gold and send the warrior north.", validated["decision_summary"])

    def test_expand_flat_response_recovers_cmd_key_suffix_as_command_id(self):
        state = snapshot()
        flat = {
            "thought.situation": "Research is the priority.",
            "thought.strategy": "Research Feudalism now.",
            "cmd.1.CMD_RESEARCH": "legal.choose_research.FEUDALISM",
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])

    def test_expand_flat_response_preserves_nested_thought_with_flat_cmds(self):
        state = snapshot()
        flat = {
            "thought": {
                "situation": "Settler and archer on the coast.",
                "strategy": "Found the capital and scout the island.",
            },
            "decision_summary": "Found the capital and scout the island.",
            "cmd.1": "CMD_RESEARCH",
            "chat.1.target": "all",
            "chat.1.text": "We rise.",
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual("Settler and archer on the coast.", validated["thought"]["situation"])
        self.assertEqual("Found the capital and scout the island.", validated["thought"]["strategy"])

    def test_wire_response_without_thought_accepts_commands(self):
        """Flat wire with cmd/chat/decision_summary only — no JSON Schema whole-turn failure."""
        state = snapshot()
        flat = {
            "chat.1.target": "all",
            "chat.1.text": "Workers prepare the earth.",
            "cmd.1": "CMD_RESEARCH",
            "decision_summary": "Capital population growth; prioritizing worker production.",
        }
        cleaned = p.normalize_model_response(state, p.expand_flat_response(flat))
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual(1, len(validated["chat_messages"]))
        self.assertTrue(validated["thought"]["situation"])
        self.assertTrue(validated["thought"]["strategy"])

    def test_interactive_end_turn_and_pop_research_map_to_v2_kinds(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["visible"]["interactive"] = {
            "elections": [{"interactive_index": 0}],
            "votes": [], "events": [], "splits": [], "launches": [], "found_religion": [],
            "advanced_start": {"active": False, "points": 0}}
        legacy["legal_actions"] = {
            "interactive_action": [{"action_id": "interactive_action:0", "kind": "interactive_action",
                "interactive_index": 0, "v2_kind": "choose_election"}],
            "pop_research": [{"action_id": "pop_research:TECH_FEUDALISM", "kind": "pop_research",
                "tech_id": "TECH_FEUDALISM", "v2_kind": "remove_queue_order"}],
            "end_turn": [{"action_id": "end_turn", "kind": "end_turn", "v2_kind": "end_turn"}],
            "auto_moves": [{"action_id": "auto_moves", "kind": "auto_moves", "v2_kind": "auto_moves"}],
        }
        state = p.build_model_input(legacy)
        kinds = {row["kind"] for row in state["legal_commands"]}
        self.assertTrue({"choose_election", "remove_queue_order"}.issubset(kinds))
        self.assertNotIn("end_turn", kinds)
        self.assertNotIn("auto_moves", kinds)

    def test_city_task_v2_kinds_include_specialist_and_fate_actions(self):
        legacy = json.loads((p.ROOT / "fixtures" / "turn_0001_state.json").read_text(encoding="utf-8"))
        legacy["legal_actions"] = [
            {"action_id": "city_task:CITY_0_0:TASK_CHANGE_SPECIALIST:INT_0:INT_1", "kind": "city_task",
                "v2_kind": "change_specialist", "city_id": "CITY_0_0", "task_id": "TASK_CHANGE_SPECIALIST",
                "data1_id": "INT_0", "data2_id": "INT_1"},
            {"action_id": "city_task:CITY_0_0:TASK_LIBERATE:INT_1:INT_0", "kind": "city_task",
                "v2_kind": "liberate_city", "city_id": "CITY_0_0", "task_id": "TASK_LIBERATE",
                "data1_id": "INT_1", "data2_id": "INT_0"},
        ]
        state = p.build_model_input(legacy)
        kinds = {row["kind"] for row in state["legal_commands"]}
        self.assertIn("change_specialist", kinds)
        self.assertIn("liberate_city", kinds)

    def test_personality_identity_follows_live_snapshot(self):
        state = snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "player.json"
            run_v2._apply_personality(state, path)
            stale = json.loads(path.read_text(encoding="utf-8"))
            stale["leader_name"] = "Caesar"
            stale["leader_id"] = "LEADER_CAESAR"
            stale["civilization_id"] = "CIVILIZATION_ROME"
            path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            run_v2._apply_personality(state, path)
            self.assertEqual("Alexander", state["personality"]["leader_name"])
            self.assertEqual("LEADER_ALEXANDER", state["personality"]["leader_id"])

    def test_previous_journal_supplies_memory_and_response_continuity(self):
        state = snapshot()
        record = {"private": {"turn": 3}, "response": {"decision_summary": "Defend Athens."},
            "validated": {"commands": [{"command_id": "CMD_RESEARCH"}]},
            "model": {"response_id": "resp_previous"}}
        response_id = run_v2._apply_previous_turn(state, record)
        self.assertEqual("resp_previous", response_id)
        self.assertEqual("Defend Athens.", state["history"]["memory_summary"])
        self.assertEqual(["CMD_RESEARCH"], state["history"]["accepted_decisions"][0]["affected_ids"])

    def test_fresh_map_image_is_generated_for_every_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "turn.jsonl"
            state = snapshot()
            state["decision"]["turn"] = 0
            url, image_path = run_v2._map_image_url(state, None, journal)
            self.assertTrue(image_path.is_file())
            self.assertEqual(f"turn{map_render.model_image_suffix()}", image_path.name)
            self.assertTrue(url.startswith("data:image/png;base64,"))
            archive_svg = Path(directory) / "map_images" / "turn" / "PLAYER_0_turn_000000.map.svg"
            archive_model = Path(directory) / "map_images" / "turn" / "PLAYER_0_turn_000000.map.png"
            self.assertTrue(archive_svg.is_file())
            self.assertTrue(archive_model.is_file())
            state["decision"]["turn"] = 1
            url_turn_1, _ = run_v2._map_image_url(state, image_path, journal)
            self.assertIsNotNone(url_turn_1)

    def test_model_map_image_is_fixed_png(self):
        with tempfile.TemporaryDirectory() as directory:
            state = snapshot()
            state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
            meta = map_render.render_known_map_model_image(state, Path(directory) / "model.png")
            mime, raw = p._parse_image_data_url(meta["data_url"])
            self.assertEqual("image/png", mime)
            self.assertEqual(map_render.MODEL_IMAGE_SIZE, meta["width"])
            self.assertEqual(map_render.MODEL_IMAGE_SIZE, meta["height"])
            self.assertGreater(len(raw), 100)

    def test_deterministic_map_svg(self):
        with tempfile.TemporaryDirectory() as directory:
            state = snapshot()
            state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
            first = map_render.render_known_map_svg(state, Path(directory) / "a.svg")
            second = map_render.render_known_map_svg(state, Path(directory) / "b.svg")
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual("svg-grid-v2", first["format"])
            svg_text = Path(directory, "a.svg").read_text(encoding="utf-8")
            self.assertIn("viewport", svg_text)

    def test_map_tile_px_default(self):
        self.assertEqual(24, map_render.DEFAULT_TILE_PX)
        self.assertEqual(24, map_render.resolve_map_tile_px())

    def test_map_stack_suppresses_duplicate_unit_marker(self):
        state = snapshot()
        state["decision"]["player_id"] = "PLAYER_0"
        state["known_map"]["visible_stacks"] = [
            {
                "stack_id": "STACK_1_1",
                "owner_player_id": "PLAYER_0",
                "plot_id": "PLOT_1_1",
                "unit_count": 3,
                "type_mix_ids": ["UNIT_WARRIOR"],
            }
        ]
        state["your_units"] = [
            {
                "unit_id": "UNIT_0_1",
                "plot_id": "PLOT_1_1",
                "unit_type_id": "UNIT_WARRIOR",
            }
        ]
        viewport = {"x0": 0, "y0": 0, "width": 4, "height": 4}
        markers = map_render.build_tile_markers(state, viewport)
        kinds = [m.get("kind") for m in markers.get((1, 1), [])]
        self.assertEqual(["stack"], kinds)

    def test_map_solo_stack_uses_unit_icon_not_stack(self):
        state = snapshot()
        state["decision"]["player_id"] = "PLAYER_0"
        state["known_map"]["visible_stacks"] = [
            {
                "stack_id": "STACK_2_2",
                "owner_player_id": "PLAYER_0",
                "plot_id": "PLOT_2_2",
                "unit_count": 1,
                "type_mix_ids": ["UNIT_SCOUT"],
            }
        ]
        state["your_units"] = [
            {
                "unit_id": "UNIT_0_2",
                "plot_id": "PLOT_2_2",
                "unit_type_id": "UNIT_SCOUT",
            }
        ]
        viewport = {"x0": 0, "y0": 0, "width": 4, "height": 4}
        markers = map_render.build_tile_markers(state, viewport)
        kinds = [m.get("kind") for m in markers.get((2, 2), [])]
        self.assertEqual(["unit"], kinds)

    def test_compute_viewport_includes_full_revealed_area(self):
        state = snapshot()
        state["game"]["map_width"] = 40
        state["game"]["map_height"] = 30
        state["known_map"]["plots"] = []
        state["known_map"]["visibility_grid"] = ["." * 40 for _ in range(30)]
        plot_index = map_render.build_render_plot_index(state)
        viewport = map_render.compute_viewport(state, plot_index)
        self.assertEqual(0, viewport["x0"])
        self.assertEqual(0, viewport["y0"])
        self.assertEqual(40, viewport["width"])
        self.assertEqual(30, viewport["height"])

    def test_compute_viewport_respects_max_viewport_tiles_env(self):
        state = snapshot()
        state["game"]["map_width"] = 40
        state["game"]["map_height"] = 30
        state["known_map"]["plots"] = []
        state["known_map"]["visibility_grid"] = ["." * 40 for _ in range(30)]
        plot_index = map_render.build_render_plot_index(state)
        with mock.patch.dict(os.environ, {"CIV4AI_MAP_MAX_VIEWPORT_TILES": "24"}):
            viewport = map_render.compute_viewport(state, plot_index)
        self.assertEqual(24, viewport["width"])
        self.assertEqual(24, viewport["height"])

    def test_large_viewport_omits_tile_coord_labels(self):
        state = snapshot()
        state["game"]["map_width"] = 120
        state["game"]["map_height"] = 120
        state["known_map"]["plots"] = [
            {
                "plot_id": f"PLOT_{x}_{y}", "x": x, "y": y, "knowledge": "visible",
                "terrain_id": "TERRAIN_GRASS", "water": False, "hills": False, "peak": False,
                "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
                "fresh_water": False, "river_edges": [], "revealed_owner_id": None,
                "feature_id": None, "improvement_id": None, "route_id": None,
                "resource_id": None, "defense_percent": 0, "city_id": None,
                "worked_by_city_id": None, "visible_stack_ids": [],
            }
            for x in range(20)
            for y in range(20)
        ]
        state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
        with tempfile.TemporaryDirectory() as directory:
            meta = map_render.render_known_map_svg(state, Path(directory) / "large.svg")
            svg = Path(directory, "large.svg").read_text(encoding="utf-8")
        self.assertTrue(meta["show_axis_labels"])
        self.assertFalse(meta["show_tile_coord_labels"])
        self.assertIn('text-anchor="middle"', svg)
        self.assertNotIn(',</text>', svg)
        self.assertLessEqual(max(meta["width"], meta["height"] - 96), map_render.resolve_max_canvas_px() + 24)

    def test_typical_viewport_shows_axis_and_tile_coords(self):
        state = snapshot()
        state["game"]["map_width"] = 80
        state["game"]["map_height"] = 60
        state["known_map"]["plots"] = [
            {
                "plot_id": f"PLOT_{x}_{y}", "x": x, "y": y, "knowledge": "visible",
                "terrain_id": "TERRAIN_GRASS", "water": False, "hills": False, "peak": False,
                "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
                "fresh_water": False, "river_edges": [], "revealed_owner_id": None,
                "feature_id": None, "improvement_id": None, "route_id": None,
                "resource_id": None, "defense_percent": 0, "city_id": None,
                "worked_by_city_id": None, "visible_stack_ids": [],
            }
            for x in range(8)
            for y in range(8)
        ]
        state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
        with tempfile.TemporaryDirectory() as directory:
            meta = map_render.render_known_map_svg(state, Path(directory) / "coords.svg")
            svg = Path(directory, "coords.svg").read_text(encoding="utf-8")
        self.assertTrue(meta["show_axis_labels"])
        self.assertTrue(meta["show_tile_coord_labels"])
        self.assertIn("0,0</text>", svg)

    def test_axis_label_font_scales_with_tile_px(self):
        small = map_render._axis_label_font(12, 0, 0, 24, 24)
        large = map_render._axis_label_font(24, 0, 0, 8, 8)
        self.assertLess(small, large)
        wide_coords = map_render._axis_label_font(24, 90, 0, 20, 20)
        self.assertLessEqual(wide_coords, large)

    def test_stack_tile_owner_before_culture_borders(self):
        state = snapshot()
        state["game"]["map_width"] = 3
        state["game"]["map_height"] = 2
        state["known_map"]["plots"] = [
            {"plot_id": "PLOT_0_0", "x": 0, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": None, "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": ["STACK_1"]},
            {"plot_id": "PLOT_1_0", "x": 1, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": None, "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
        ]
        state["known_map"]["visible_stacks"] = [
            {"stack_id": "STACK_1", "plot_id": "PLOT_0_0", "owner_player_id": "PLAYER_1", "unit_count": 1},
        ]
        owner_index = map_render.build_territory_owner_index(
            state, map_render.build_render_plot_index(state),
        )
        self.assertEqual("PLAYER_1", owner_index[(0, 0)])
        tinted = map_render._tile_fill(state["known_map"]["plots"][0], ".", "revealed", "PLAYER_1")
        self.assertNotEqual(tinted, map_render.TERRAIN_COLORS["TERRAIN_GRASS"])
        with tempfile.TemporaryDirectory() as directory:
            meta = map_render.render_known_map_svg(state, Path(directory) / "stack_owner.svg")
            svg = Path(directory, "stack_owner.svg").read_text(encoding="utf-8")
        self.assertIn('stroke="#901e1e"', svg)

    def test_effective_tile_px_shrinks_for_large_viewport(self):
        self.assertEqual(12, map_render._effective_tile_px(24, 80, 80))

    def test_map_svg_viewport_covers_all_revealed_plots(self):
        state = snapshot()
        state["game"]["map_width"] = 78
        state["game"]["map_height"] = 56
        state["known_map"]["plots"] = [
            {"plot_id": "PLOT_0_0", "x": 0, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_0", "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
            {"plot_id": "PLOT_77_55", "x": 77, "y": 55, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_0", "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
        ]
        state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
        meta = map_render.render_known_map_svg(state)
        self.assertEqual(0, meta["viewport"]["x0"])
        self.assertEqual(0, meta["viewport"]["y0"])
        self.assertEqual(78, meta["viewport"]["width"])
        self.assertEqual(56, meta["viewport"]["height"])

    def test_territory_tint_and_borders(self):
        state = snapshot()
        state["game"]["map_width"] = 4
        state["game"]["map_height"] = 2
        state["known_map"]["plots"] = [
            {"plot_id": "PLOT_0_0", "x": 0, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_0", "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
            {"plot_id": "PLOT_1_0", "x": 1, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_1", "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
            {"plot_id": "PLOT_2_0", "x": 2, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": "PLAYER_1", "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
            {"plot_id": "PLOT_3_0", "x": 3, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": None, "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            meta = map_render.render_known_map_svg(state, Path(directory) / "territory.svg")
            svg = Path(directory, "territory.svg").read_text(encoding="utf-8")
        tinted = map_render._tile_fill(state["known_map"]["plots"][0], ".", "revealed")
        self.assertNotEqual(tinted, map_render.TERRAIN_COLORS["TERRAIN_GRASS"])
        # P0 east stripe and P1 west stripe sit on opposite sides of the shared edge.
        self.assertIn('stroke="#1e4884"', svg)  # darkened PLAYER_0 blue
        self.assertIn('stroke="#901e1e"', svg)  # darkened PLAYER_1 red
        self.assertIn('x1="34" y1="14" x2="34" y2="34"', svg)  # P0 inward east stripe
        self.assertIn('x1="38" y1="14" x2="38" y2="34"', svg)  # P1 inward west stripe
        legend = {entry["meaning"] for entry in meta["legend"]}
        self.assertTrue(any("territory" in meaning for meaning in legend))

    def test_city_culture_ring_fills_territory(self):
        state = snapshot()
        state["game"]["map_width"] = 5
        state["game"]["map_height"] = 5
        state["your_cities"] = [{
            "city_id": "CITY_0", "name": "Capital", "plot_id": "PLOT_2_2", "owner_player_id": "PLAYER_0",
            "population": 4, "culture": {"current": 500, "maximum": 0, "change_per_turn": 0},
            "is_capital": True, "area_id": "AREA_0", "is_coastal": False,
        }]
        state["known_map"]["visibility_grid"] = ["....." for _ in range(5)]
        state["known_map"]["plots"] = []
        owner_index = map_render.build_territory_owner_index(
            state, map_render.build_render_plot_index(state),
        )
        self.assertEqual("PLAYER_0", owner_index.get((2, 2)))
        self.assertEqual("PLAYER_0", owner_index.get((2, 1)))
        self.assertEqual("PLAYER_0", owner_index.get((3, 2)))

    def test_map_svg_fixture_golden_hashes(self):
        fixture_dir = p.ROOT / "fixtures" / "map_snapshots"
        for name in ("p0_t2.json", "p0_t32.json", "p4_t32.json"):
            path = fixture_dir / name
            if not path.is_file():
                continue
            state = json.loads(path.read_text(encoding="utf-8"))
            state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
            with tempfile.TemporaryDirectory() as directory:
                a = map_render.render_known_map_svg(state, Path(directory) / "a.svg")
                b = map_render.render_known_map_svg(state, Path(directory) / "b.svg")
                self.assertEqual(a["sha256"], b["sha256"])

    def test_map_wire_includes_legend_and_advciv_policy(self):
        state = snapshot()
        state.setdefault("known_map", {}).setdefault("image", {})["attached"] = True
        map_render.render_known_map_svg(state)
        wire = p.build_model_wire_text(state)
        self.assertNotIn("map.legend.", wire)
        self.assertNotIn("map.image_format", wire)
        self.assertNotIn("map.width", wire)
        self.assertNotIn("advciv.unit_controller", wire)
        self.assertIn("advciv.unit_policy", wire)
        self.assertIn(p.ADVCIV_FALLBACK_POLICY, wire)

    def test_map_svg_sparse_plots_use_visibility_grid(self):
        state = snapshot()
        state["game"]["map_width"] = 5
        state["game"]["map_height"] = 3
        state["known_map"]["plots"] = [
            {"plot_id": "PLOT_1_1", "x": 1, "y": 1, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": None, "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
        ]
        state["known_map"]["visibility_grid"] = [".....", ".....", "....."]
        meta = map_render.render_known_map_svg(state)
        self.assertEqual(15, meta["rendered_tiles"])

    def test_ensure_known_map_merges_grid_when_plots_sparse(self):
        state = snapshot()
        state["game"]["map_width"] = 4
        state["game"]["map_height"] = 3
        state["known_map"]["plots"] = [
            {"plot_id": "PLOT_0_0", "x": 0, "y": 0, "knowledge": "visible", "terrain_id": "TERRAIN_GRASS",
             "water": False, "hills": False, "peak": False, "area_id": "AREA_0", "yields": {"food": 0, "production": 0, "commerce": 0},
             "fresh_water": False, "river_edges": [], "revealed_owner_id": None, "feature_id": None,
             "improvement_id": None, "route_id": None, "resource_id": None, "defense_percent": 0,
             "city_id": None, "worked_by_city_id": None, "visible_stack_ids": []},
        ]
        state["known_map"]["visibility_grid"] = ["....", ".~..", "...."]
        count = p.ensure_known_map_plots(state)
        self.assertEqual(12, count)

    def test_model_instructions_hybrid_unit_policy(self):
        state = snapshot()
        instructions = p._model_instructions(state, api_thinking=False)
        self.assertIn("After your response the host applies only your explicit overrides", instructions)
        self.assertIn("After you give your commands, AdvCiv (the base AI mod)", instructions)
        self.assertIn("thought.situation", instructions)
        self.assertIn("=== INSTRUCTIONS ===", instructions)
    def test_normalize_live_response_shapes_model_json(self):
        state = snapshot()
        messy = with_thought({
            "decision_summary": {"turn": 36, "research": "TECH_FEUDALISM"},
            "recommendation_decisions": [
                {"recommendation_id": "REC_RESEARCH", "decision": "retain"},
                {"recommendation_id": "UNKNOWN", "decision": "accept"},
            ],
            "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}}],
            "chat_messages": [{
                "target": "all",
                "target_player_id": None,
                "text": "Status: defend Athens. Plan: research. Action: CMD_RESEARCH.",
                "grounding_ids": ["TECH_FEUDALISM", "CITY_0", "UNIT_0"],
            }],
        })
        cleaned = p.normalize_model_response(state, messy)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual("accept", validated["recommendation_decisions"][0]["decision"])
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual("all", validated["chat_messages"][0]["target"])
        self.assertNotIn("target_player_id", validated["chat_messages"][0])
        self.assertIn("CITY_0", validated["chat_messages"][0]["grounding_ids"])
        self.assertNotIn("TECH_FEUDALISM", validated["chat_messages"][0]["grounding_ids"])

    def test_model_deadline_matches_plan(self):
        self.assertEqual(90, p.MODEL_DEADLINE_SECONDS)

    def test_normalize_strips_fixed_command_arguments(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_UNIT_SLEEP",
            "kind": "unit_posture_mission",
            "description": "Sleep unit",
            "fixed_arguments": {
                "unit_id": "UNIT_0",
                "mission_id": "MISSION_SLEEP",
                "data1_id": "INT_-1",
                "data2_id": "INT_-1",
                "target_plot_id": "NONE",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_0"],
            "runtime_status": "implemented_untested",
        })
        messy = with_thought({
            "decision_summary": "Fortify and sleep.",
            "recommendation_decisions": [],
            "commands": [{
                "command_id": "CMD_UNIT_SLEEP",
                "arguments": {
                    "unit_id": "UNIT_0",
                    "mission_id": "MISSION_SLEEP",
                    "data1_id": "INT_-1",
                    "data2_id": "INT_-1",
                    "target_plot_id": "NONE",
                },
            }],
            "chat_messages": [],
        })
        cleaned = p.normalize_model_response(state, messy)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_UNIT_SLEEP"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual({}, validated["commands"][0]["arguments"])

    def test_call_model_uses_gemini_when_provider_gemini(self):
        state = snapshot()
        wire = json.dumps(minimal_model_response())
        interaction_payload = {
            "id": "int_test_chain_001",
            "model": "gemini-2.5-flash",
            "status": "completed",
            "steps": [
                {
                    "type": "thought",
                    "summary": [{"type": "text", "text": "Berlin is coastal and rivals are near."}],
                },
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": wire}],
                },
            ],
            "usage": {
                "total_input_tokens": 10,
                "total_output_tokens": 20,
                "total_thought_tokens": 5,
                "total_tokens": 35,
            },
        }

        class FakeGeminiResponse:
            status = 200

            def __init__(self, payload: dict[str, Any]):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request, timeout=45):
            self.assertIn("generativelanguage.googleapis.com", request.full_url)
            self.assertIn("/interactions", request.full_url)
            return FakeGeminiResponse(interaction_payload)

        with mock.patch.dict(os.environ, {
            "CIV4AI_MODEL_PROVIDER": "gemini",
            "CIV4AI_GEMINI_API": "interactions",
            "OPENAI_API_KEY": "openai-key",
            "GEMINI_API_KEY": "gemini-key",
        }, clear=False):
            result, metadata = p.call_model(state, "openai-key", opener=fake_urlopen)
        self.assertEqual(metadata["provider"], "gemini")
        self.assertEqual(metadata["api"], "interactions")
        self.assertEqual(metadata["response_id"], "int_test_chain_001")
        self.assertIn("Berlin is coastal", metadata.get("private_thought", ""))
        self.assertEqual(result["commands"][0]["command_id"], "CMD_RESEARCH")

    def test_call_gemini_interactions_retries_without_chain_on_empty_output(self):
        state = snapshot()
        wire = json.dumps(minimal_model_response())
        empty_chain_payload = {
            "id": "int_chain_empty",
            "model": "gemini-2.5-flash",
            "status": "completed",
            "steps": [{"type": "thought", "summary": [{"type": "text", "text": "thinking only"}]}],
            "usage": {"total_input_tokens": 5, "total_output_tokens": 0, "total_tokens": 5},
        }
        ok_payload = {
            "id": "int_retry_ok",
            "model": "gemini-2.5-flash",
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": wire}]}],
            "usage": {"total_input_tokens": 10, "total_output_tokens": 20, "total_tokens": 30},
        }
        bodies: list[dict] = []

        class FakeGeminiResponse:
            status = 200

            def __init__(self, payload: dict[str, Any]):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request, timeout=45):
            body = json.loads(request.data.decode("utf-8"))
            bodies.append(body)
            if body.get("previous_interaction_id"):
                return FakeGeminiResponse(empty_chain_payload)
            return FakeGeminiResponse(ok_payload)

        with mock.patch.dict(os.environ, {
            "CIV4AI_MODEL_PROVIDER": "gemini",
            "CIV4AI_GEMINI_API": "interactions",
            "GEMINI_API_KEY": "gemini-key",
        }, clear=False):
            result, metadata = p.call_gemini(
                state, "gemini-key", previous_interaction_id="int_turn0_ok", opener=fake_urlopen,
            )
        self.assertEqual(2, len(bodies))
        self.assertIn("previous_interaction_id", bodies[0])
        self.assertNotIn("previous_interaction_id", bodies[1])
        self.assertTrue(metadata.get("interaction_chain_retry"))
        self.assertEqual(result["commands"][0]["command_id"], "CMD_RESEARCH")

    def test_legend_layout_uses_text_width_not_fixed_stride(self):
        from sidecar import map_render as mr

        canvas_w = 180
        legend_font = 10
        legend_swatch = 8
        items, strip_h = mr._layout_legend_items(mr.TERRAIN_LEGEND, canvas_w, legend_font, legend_swatch)
        xs = [lx for lx, _ly, _label, _color in items]
        self.assertGreaterEqual(len(set(xs)), 2)
        self.assertGreater(strip_h, legend_font)
        for lx, ly_row, label, color in items:
            self.assertTrue(label)
            self.assertTrue(color.startswith("#"))

    def test_call_model_falls_back_to_openai_on_gemini_rate_limit(self):
        state = snapshot()
        openai_payload = {
            "id": "resp_primary",
            "model": p.RESPONSES_MODEL,
            "output": [{"type": "message", "content": [{"type": "output_text",
                "text": json.dumps(minimal_model_response())}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }
        gemini_calls = 0

        def fake_urlopen(request, timeout=45):
            nonlocal gemini_calls
            url = request.full_url
            if "generativelanguage.googleapis.com" in url:
                gemini_calls += 1
                raise urllib_error.HTTPError(url, 429, "rate limit", {}, io.BytesIO(b'{"error":"rate_limit"}'))
            if "api.openai.com" in url:
                class FakeOpenAIResponse:
                    status = 200

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                    def read(self, size=-1):
                        return json.dumps(openai_payload).encode("utf-8")

                return FakeOpenAIResponse()
            raise AssertionError(url)

        with mock.patch.dict(os.environ, {
            "CIV4AI_MODEL_PROVIDER": "gemini",
            "OPENAI_API_KEY": "openai-key",
            "GEMINI_API_KEY": "gemini-key",
        }, clear=False):
            result, metadata = p.call_model(state, "openai-key", opener=fake_urlopen)
        self.assertEqual(3, gemini_calls)
        self.assertEqual(metadata["provider"], "openai")
        self.assertEqual(metadata["fallback_from"], "gemini")
        self.assertEqual(result["commands"][0]["command_id"], "CMD_RESEARCH")

    def test_call_model_rate_limit_without_openai_key(self):
        state = snapshot()

        def fake_urlopen(request, timeout=45):
            raise urllib_error.HTTPError(request.full_url, 429, "rate limit", {}, io.BytesIO(b'{"error":"rate_limit"}'))

        with mock.patch.dict(os.environ, {
            "CIV4AI_MODEL_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-key",
        }, clear=True):
            with self.assertRaises(p.BoundaryError) as ctx:
                p.call_model(state, "", opener=fake_urlopen)
        self.assertEqual(ctx.exception.category, "rate_limit")

    def test_call_model_rate_limit_fallback_disabled(self):
        state = snapshot()

        def fake_urlopen(request, timeout=45):
            raise urllib_error.HTTPError(request.full_url, 429, "rate limit", {}, io.BytesIO(b'{"error":"rate_limit"}'))

        with mock.patch.dict(os.environ, {
            "CIV4AI_MODEL_PROVIDER": "gemini",
            "OPENAI_API_KEY": "openai-key",
            "GEMINI_API_KEY": "gemini-key",
            "CIV4AI_DISABLE_MODEL_FALLBACK": "1",
        }, clear=False):
            with self.assertRaises(p.BoundaryError) as ctx:
                p.call_model(state, "openai-key", opener=fake_urlopen)
        self.assertEqual(ctx.exception.category, "rate_limit")
        self.assertNotIn("OpenAI", str(ctx.exception))

    def test_unit_wire_prompt_solo_and_stack(self):
        state = snapshot()
        state["your_units"].append({
            "unit_id": "UNIT_1", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "UNITCLASS_WARRIOR",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_0_0",
            "health": {"current": 30, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 3, "maximum": 3, "change_per_turn": 0},
            "movement": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("stack.position = (0,0)", wire)
        self.assertIn("stack.size = 2", wire)
        self.assertIn("stack.archer_1.hp", wire)
        self.assertIn("stack.warrior_1.hp", wire)
        self.assertIn("archer_1.attack", wire)

    def test_stack_legal_move_to_and_resolve(self):
        state = snapshot()
        state["your_units"].append({
            "unit_id": "UNIT_1", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "UNITCLASS_WARRIOR",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_0_0",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 3, "maximum": 3, "change_per_turn": 0},
            "movement": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["legal_commands"].append({
            "command_id": "CMD_MOVE_WARRIOR",
            "kind": "move_group",
            "description": "Move warrior",
            "fixed_arguments": {
                "unit_id": "UNIT_1",
                "mission_id": "MISSION_MOVE_TO",
                "data1_id": "INT_1",
                "data2_id": "INT_0",
                "target_plot_id": "PLOT_1_0",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_1"],
            "runtime_status": "tested",
        })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("stack.moveTo = (1,0)", wire)
        resolved = p.resolve_property_wire(state, {"stack.moveTo": "(1,0)"})
        self.assertIn("CMD_MOVE_WARRIOR", resolved.values())

    def test_unit_automate_wire_labels(self):
        state = snapshot()
        state["your_units"].append({
            "unit_id": "UNIT_7", "unit_type_id": "UNIT_WORKER", "unit_class_id": "UNITCLASS_WORKER",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_0_0",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 0, "maximum": 0, "change_per_turn": 0},
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_WORKER", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["your_units"].append({
            "unit_id": "UNIT_8", "unit_type_id": "UNIT_SCOUT", "unit_class_id": "UNITCLASS_SCOUT",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_1_1",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["legal_commands"].extend([
            {
                "command_id": "CMD_worker_automate_build",
                "kind": "automate_unit",
                "description": "Automate worker improvements",
                "fixed_arguments": {
                    "unit_id": "UNIT_7",
                    "command_id": "COMMAND_AUTOMATE",
                    "data1_id": "INT_0",
                    "data2_id": "INT_-1",
                    "target_id": "NONE",
                },
                "parameter_domains": {},
                "affected_ids": ["UNIT_7"],
                "runtime_status": "implemented_untested",
            },
            {
                "command_id": "CMD_scout_automate_explore",
                "kind": "automate_unit",
                "description": "Automate scout exploration",
                "fixed_arguments": {
                    "unit_id": "UNIT_8",
                    "command_id": "COMMAND_AUTOMATE",
                    "data1_id": "INT_3",
                    "data2_id": "INT_-1",
                    "target_id": "NONE",
                },
                "parameter_domains": {},
                "affected_ids": ["UNIT_8"],
                "runtime_status": "implemented_untested",
            },
        ])
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("worker_1.automate = build", wire)
        self.assertIn("scout_1.automate = explore", wire)
        resolved = p.resolve_property_wire(state, {"worker_1.automate": "build"})
        self.assertIn("CMD_worker_automate_build", resolved.values())

    def test_stack_move_to_with_coordinate_prefix(self):
        state = snapshot()
        state["your_units"].append({
            "unit_id": "UNIT_1", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "UNITCLASS_WARRIOR",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_0_0",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 3, "maximum": 3, "change_per_turn": 0},
            "movement": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["your_units"].append({
            "unit_id": "UNIT_2", "unit_type_id": "UNIT_SCOUT", "unit_class_id": "UNITCLASS_SCOUT",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_1_1",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "movement": {"current": 2, "maximum": 2, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["your_units"].append({
            "unit_id": "UNIT_3", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "UNITCLASS_WARRIOR",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_1_1",
            "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
            "strength": {"current": 3, "maximum": 3, "change_per_turn": 0},
            "movement": {"current": 1, "maximum": 1, "change_per_turn": 0},
            "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
            "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
            "can_act": True, "needs_orders": True, "upgrade_options": [],
        })
        state["legal_commands"].append({
            "command_id": "CMD_MOVE_ARCHER",
            "kind": "move_group",
            "description": "Move archer",
            "fixed_arguments": {
                "unit_id": "UNIT_0",
                "mission_id": "MISSION_MOVE_TO",
                "data1_id": "INT_1",
                "data2_id": "INT_0",
                "target_plot_id": "PLOT_1_0",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_0"],
            "runtime_status": "tested",
        })
        state["legal_commands"].append({
            "command_id": "CMD_MOVE_SCOUT",
            "kind": "move_group",
            "description": "Move scout",
            "fixed_arguments": {
                "unit_id": "UNIT_2",
                "mission_id": "MISSION_MOVE_TO",
                "data1_id": "INT_2",
                "data2_id": "INT_1",
                "target_plot_id": "PLOT_2_1",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_2"],
            "runtime_status": "tested",
        })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("stack.0_0.moveTo = (1,0)", wire)
        self.assertIn("stack.1_1.moveTo = (2,1)", wire)
        resolved = p.resolve_property_wire(state, {"stack.1_1.moveTo": "(2,1)"})
        self.assertIn("CMD_MOVE_SCOUT", resolved.values())

    def test_compact_unit_wire_omits_stats_when_many_units(self):
        state = snapshot()
        for index in range(5):
            state["your_units"].append({
                "unit_id": f"UNIT_{index + 10}", "unit_type_id": "UNIT_WARRIOR",
                "unit_class_id": "UNITCLASS_WARRIOR", "domain_id": "DOMAIN_LAND",
                "plot_id": f"PLOT_{index}_0",
                "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
                "strength": {"current": 2, "maximum": 2, "change_per_turn": 0},
                "movement": {"current": 1, "maximum": 1, "change_per_turn": 0},
                "level": 1, "experience": 0, "promotion_ids": [], "activity_id": "ACTIVITY_AWAKE",
                "mission_queue": [], "unit_ai_role": "UNITAI_EXPLORE", "cargo_unit_ids": [],
                "can_act": True, "needs_orders": index % 2 == 0, "upgrade_options": [],
            })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn(".position = ", wire)
        self.assertNotIn(".hp = ", wire)
        self.assertNotIn(".attack = ", wire)
        self.assertIn(".needsOrders = true", wire)

    def test_compact_city_wire_keeps_capital_details(self):
        state = snapshot()
        state["your_cities"] = []
        for index in range(10):
            state["your_cities"].append({
                "city_id": f"CITY_{index}", "name": "Athens" if index == 0 else f"City{index}",
                "plot_id": f"PLOT_{index}_0",
                "area_id": "AREA_0", "is_capital": index == 0, "is_coastal": False,
                "population": 2, "production": {"item_id": "UNIT_WARRIOR", "progress": 0, "cost": 10,
                    "production_per_turn": 2, "estimated_turns_remaining": 5},
                "buildings": ["BUILDING_BARRACKS"] if index else ["BUILDING_PALACE"],
            })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("Athens.buildings", wire)
        self.assertIn("Athens.population", wire)
        self.assertIn("City9.position", wire)
        self.assertNotIn("City9.buildings", wire)
        self.assertNotIn("City9.population", wire)

    def test_unit_property_wire_resolve(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_UNIT_MISSION_FORTIFY",
            "kind": "unit_posture_mission",
            "description": "Fortify",
            "fixed_arguments": {
                "unit_id": "UNIT_0",
                "mission_id": "MISSION_FORTIFY",
                "data1_id": "INT_-1",
                "data2_id": "INT_-1",
                "target_plot_id": "NONE",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_0"],
            "runtime_status": "implemented_untested",
        })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("archer_1.stance = fortify", wire)
        flat = {
            "thought.situation": "Archer holds Athens.",
            "thought.strategy": "Fortify.",
            "decision_summary": "Fortify archer.",
            "archer_1.stance": "fortify",
        }
        cleaned = p.normalize_model_response(state, p.expand_flat_response(flat))
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_UNIT_MISSION_FORTIFY"], [c["command_id"] for c in validated["commands"]])

    def test_city_property_wire_prompt_and_resolve(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_set_city_production_CITY_0_TRAIN_UNIT_WORKER",
            "kind": "queue_production",
            "description": "Queue worker",
            "fixed_arguments": {"city_id": "CITY_0", "build_id": "TRAIN:UNIT_WORKER"},
            "parameter_domains": {},
            "affected_ids": ["CITY_0"],
            "runtime_status": "implemented_untested",
        })
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("Athens.changeProduction = worker", wire)
        self.assertIn("Athens.population = 2", wire)
        flat = {
            "thought.situation": "Athens needs improvements.",
            "thought.strategy": "Queue a worker.",
            "decision_summary": "Queue worker in Athens.",
            "Athens.changeProduction": "worker",
        }
        cleaned = p.normalize_model_response(state, p.expand_flat_response(flat))
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(
            ["CMD_set_city_production_CITY_0_TRAIN_UNIT_WORKER"],
            [item["command_id"] for item in validated["commands"]],
        )

    def test_flat_wire_prompt_and_expand_round_trip(self):
        state = snapshot()
        context = p.build_playable_context(state)
        self.assertNotIn("plots", context.get("known_map", {}))
        wire = p.build_flat_wire_prompt(context)
        self.assertIn("turn = 1", wire)
        self.assertIn("legal.1 = CMD_RESEARCH", wire)
        self.assertIn("Alexander playing as GREECE (PLAYER_0)", wire)
        flat = {
            "thought.situation": "Athens is secure; Rome is nearby.",
            "thought.strategy": "Push Feudalism research.",
            "decision_summary": "Research feudalism.",
            "cmd.0": "CMD_RESEARCH",
            "chat.0.target": "all",
            "chat.0.text": "Research feudalism now.",
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual(1, len(validated["chat_messages"]))

    def test_expand_flat_response_recovers_wire_lines_in_summary(self):
        state = snapshot()
        flat = {
            "thought.situation": "Commerce can shift to research.",
            "thought.strategy": "Research Feudalism this turn.",
            "decision_summary": (
                "Shift commerce to research.\n"
                "cmd.0 = CMD_RESEARCH\n"
                "chat.0.target = all\n"
                "chat.0.text = Research feudalism now.\n"
            ),
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual(1, len(validated["chat_messages"]))

    def test_expand_flat_response_merges_cmd_keys_with_empty_nested_lists(self):
        state = snapshot()
        flat = {
            "thought.situation": "Hold.",
            "thought.strategy": "Research.",
            "decision_summary": "Research feudalism.",
            "commands": [],
            "chat_messages": [{"target": "all", "text": "Research feudalism now."}],
            "cmd.0": "CMD_RESEARCH",
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual(1, len(validated["chat_messages"]))

    def test_resolve_legal_numbered_cmd_id(self):
        state = snapshot()
        state["legal_commands"] = [
            {"command_id": "CMD_RESEARCH", "kind": "choose_research", "description": "Research",
             "fixed_arguments": {"tech_id": "TECH_FEUDALISM"}, "parameter_domains": {}, "affected_ids": [], "runtime_status": "tested"},
            {"command_id": "CMD_CIVIC_SLAVERY", "kind": "adopt_civics", "description": "Adopt slavery",
             "fixed_arguments": {"civic_option_id": "CIVICOPTION_LABOR", "civic_id": "CIVIC_SLAVERY"},
             "parameter_domains": {}, "affected_ids": [], "runtime_status": "tested"},
        ]
        resolved = p.resolve_property_wire(state, {"legal.2": "CMD_CIVIC_SLAVERY"})
        cmd_ids = [v for k, v in resolved.items() if k.startswith("cmd.")]
        self.assertEqual(["CMD_CIVIC_SLAVERY"], cmd_ids)

    def test_resolve_legal_numbered_civic_label(self):
        state = snapshot()
        state["legal_commands"] = [
            {"command_id": "CMD_RESEARCH", "kind": "choose_research", "description": "Research",
             "fixed_arguments": {"tech_id": "TECH_FEUDALISM"}, "parameter_domains": {}, "affected_ids": [], "runtime_status": "tested"},
            {"command_id": "CMD_CIVIC_SLAVERY", "kind": "adopt_civics", "description": "Adopt slavery",
             "fixed_arguments": {"civic_option_id": "CIVICOPTION_LABOR", "civic_id": "CIVIC_SLAVERY"},
             "parameter_domains": {}, "affected_ids": [], "runtime_status": "tested"},
        ]
        resolved = p.resolve_property_wire(state, {"legal.2": "slavery"})
        self.assertEqual("CMD_CIVIC_SLAVERY", [v for k, v in resolved.items() if k.startswith("cmd.")][0])

    def test_chat_history_trimmed_in_wire(self):
        state = snapshot()
        state["history"]["public_events"] = [
            {"turn": turn, "kind": "CHAT_PUBLIC", "summary": f"line {turn}", "affected_ids": ["PLAYER_0"]}
            for turn in range(20)
        ]
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        public_lines = [line for line in wire.splitlines() if line.startswith("chat.public.")]
        self.assertLessEqual(len(public_lines), p.chat_history_max_messages())

    def test_expand_flat_response_recovers_semicolon_wire_in_summary(self):
        state = snapshot()
        flat = {
            "thought.situation": "Settlers are needed after Chivalry.",
            "thought.strategy": "Research Chivalry and queue settlers.",
            "decision_summary": (
                "Research Chivalry and queue settlers; "
                "cmd.0 = CMD_RESEARCH; "
                "chat.0.target = all; "
                "chat.0.text = Athens prepares."
            ),
        }
        expanded = p.expand_flat_response(flat)
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in validated["commands"]])
        self.assertEqual(1, len(validated["chat_messages"]))
        self.assertEqual("Research Chivalry and queue settlers", validated["decision_summary"])

    def test_scrub_wire_from_summary(self):
        text = "Hold the line; cmd.0 = CMD_RESEARCH; chat.0.text = Go."
        self.assertEqual("Hold the line", p.scrub_wire_from_summary(text))

    def test_ensure_known_map_plots_from_entities_when_thinned(self):
        state = snapshot()
        state["known_map"]["plots"] = []
        count = p.ensure_known_map_plots(state)
        self.assertGreater(count, 0)
        self.assertEqual(count, len(state["known_map"]["plots"]))

    def test_ensure_known_map_plots_from_visibility_grid(self):
        state = snapshot()
        state["known_map"]["plots"] = []
        state["game"]["map_width"] = 4
        state["game"]["map_height"] = 3
        state["known_map"]["image"]["width"] = 4
        state["known_map"]["image"]["height"] = 3
        state["known_map"]["visibility_grid"] = ["....", ".~..", "...."]
        count = p.ensure_known_map_plots(state)
        self.assertEqual(12, count)
        water = sum(1 for plot in state["known_map"]["plots"] if plot["water"])
        self.assertEqual(1, water)

    def test_ensure_known_map_plots_visibility_grid_uses_viewport_origin(self):
        state = snapshot()
        state["known_map"]["plots"] = []
        state["game"]["map_width"] = 20
        state["game"]["map_height"] = 20
        state["known_map"]["viewport"] = {"x0": 5, "y0": 7, "width": 3, "height": 2}
        state["known_map"]["visibility_grid"] = ["...", "..~"]
        count = p.ensure_known_map_plots(state)
        self.assertEqual(6, count)
        coords = {(plot["x"], plot["y"]) for plot in state["known_map"]["plots"]}
        self.assertEqual(
            {(5, 7), (6, 7), (7, 7), (5, 8), (6, 8), (7, 8)},
            coords,
        )
        state = snapshot()
        state["decision"]["turn"] = 0
        self.assertTrue(p.map_image_attach_turn(state))
        state["decision"]["turn"] = 1
        state["decision"]["player_id"] = "PLAYER_0"
        self.assertTrue(p.map_image_attach_turn(state))
        state["decision"]["turn"] = 1
        state["decision"]["player_id"] = "PLAYER_1"
        self.assertTrue(p.map_image_attach_turn(state))

    def test_map_image_attach_turn_staggered_when_configured(self):
        state = snapshot()
        with mock.patch.dict(os.environ, {"CIV4AI_MAP_IMAGE_CADENCE": "7"}):
            state["decision"]["turn"] = 0
            self.assertTrue(p.map_image_attach_turn(state))
            state["decision"]["turn"] = 1
            self.assertFalse(p.map_image_attach_turn(state))

    def test_coalesce_cmds_and_chat_message_shapes(self):
        p1 = {
            "decision_summary": "Research feudalism.",
            "cmds": [{"cmd": "CMD_RESEARCH", "args": []}],
            "chat_messages": [{"chat_type": "chat.public", "target": "all", "text": "Hello world."}],
        }
        coalesced = p.coalesce_model_response_shape(p1)
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in coalesced["commands"]])
        self.assertEqual(1, len(coalesced["chat_messages"]))
        p2 = {
            "decision_summary": "Fortify.",
            "cmd": ["CMD_end_turn_"],
            "chat_message": [{"target": "all", "text": "We stand ready."}],
        }
        coalesced2 = p.coalesce_model_response_shape(p2)
        self.assertEqual(["CMD_end_turn_"], [item["command_id"] for item in coalesced2["commands"]])
        expanded = p.expand_flat_response(coalesced2)
        self.assertEqual(1, len(expanded["chat_messages"]))

    def test_parse_model_text_json_plus_flat_tail(self):
        text = (
            '{"decision_summary":"Hold."}\n'
            "cmd.0 = CMD_RESEARCH\n"
            "chat.0.target = all\n"
            "chat.0.text = Research now.\n"
        )
        parsed = p.parse_model_text(text)
        expanded = p.expand_flat_response(parsed)
        self.assertEqual("Hold.", expanded["decision_summary"])
        self.assertEqual(["CMD_RESEARCH"], [item["command_id"] for item in expanded["commands"]])

    def test_model_instructions_require_flat_wire_not_json(self):
        wire = p.build_model_wire_text(snapshot())
        self.assertIn("never JSON", wire)
        self.assertIn("thought.situation", wire)
        self.assertIn("=== INSTRUCTIONS ===", wire)
        self.assertIn("=== LEGAL COMMANDS ===", wire)
        self.assertIn("decision_summary", wire)
        self.assertIn("ends your turn automatically", wire)
        self.assertIn("legal.1", wire)
        self.assertIn("Do not queue production already building", wire)
        self.assertNotIn("never use generic placeholders", wire)

    def test_wire_public_chat_uses_summary_with_sender(self):
        state = snapshot()
        state["history"]["public_events"] = [
            {"turn": 2, "kind": "CHAT_PUBLIC", "summary": "Amsterdam is founded!", "affected_ids": ["PLAYER_1"]},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("Caesar: Amsterdam is founded!", wire)

    def test_model_instructions_include_chat_banter_guidance(self):
        state = snapshot()
        state["personality"]["leader_traits"] = {"aggression": "high", "diplomacy": "guarded"}
        wire = p.build_model_wire_text(state)
        self.assertIn("sparse", wire.lower())
        self.assertIn("skip most turns", wire)
        self.assertIn("Never spam chat.all", wire)
        self.assertIn("sharp banter", wire)
        self.assertIn("chat.public", wire)
        self.assertIn("hold off", wire.lower())
        self.assertNotIn("competitive banter", wire)
        self.assertNotIn("silence is normal and preferred", wire)

    def test_model_instructions_hold_off_when_lobby_chat_every_turn(self):
        state = snapshot()
        state["decision"]["turn"] = 5
        state["history"]["public_events"] = [
            {"turn": 3, "kind": "CHAT_PUBLIC", "summary": "Hi", "affected_ids": ["PLAYER_1"]},
            {"turn": 4, "kind": "CHAT_PUBLIC", "summary": "Hey", "affected_ids": ["PLAYER_1"]},
            {"turn": 5, "kind": "CHAT_PUBLIC", "summary": "Bow to me!", "affected_ids": ["PLAYER_1"]},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("Lobby chat cadence", wire)
        self.assertIn("skip chat.all this turn", wire.lower())

    def test_model_instructions_quiet_lobby_allows_occasional_all(self):
        state = snapshot()
        state["decision"]["turn"] = 5
        state["history"]["public_events"] = [
            {"turn": 5, "kind": "CHAT_PUBLIC", "summary": "Bow to me!", "affected_ids": ["PLAYER_1"]},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("occasional chat.all reply is fine", wire.lower())
        self.assertNotIn("skip chat.all this turn", wire.lower())

    def test_model_instructions_include_dm_guidance(self):
        wire = p.build_model_wire_text(snapshot())
        self.assertIn("chat.private.tN.*", wire)
        self.assertIn("reply only to DMs from this turn", wire)
        self.assertNotIn("reply only to turn 1", wire)
        self.assertIn("not older lines", wire)
        self.assertIn("skip most turns", wire)
        self.assertIn("DM recipients: Caesar", wire)
        self.assertIn("rival.PLAYER_1 = Caesar playing as ROME", wire)

    def test_model_instructions_nudge_after_long_chat_gap(self):
        state = snapshot()
        state["decision"]["turn"] = 12
        state["history"]["public_events"] = [
            {"turn": 2, "kind": "CHAT_PUBLIC", "summary": "Athens stands ready.", "affected_ids": ["PLAYER_0"]},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("10 turns since your last public chat", wire)

    def test_model_instructions_flag_pending_dms(self):
        state = snapshot()
        state["diplomacy"]["private_inbox"] = [
            {"message_id": "CHAT_0_1_000001", "from_player_id": "PLAYER_1",
                "turn": 1, "text": "Want to team up?"},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("DMs received this turn: Caesar (PLAYER_1)", wire)
        self.assertIn("you may reply privately on turn 1", wire)

    def test_model_instructions_keep_stale_dms_in_wire_but_not_pending(self):
        state = snapshot()
        state["decision"]["turn"] = 5
        state["diplomacy"]["private_inbox"] = [
            {"message_id": "CHAT_0_1_000001", "from_player_id": "PLAYER_1",
                "turn": 0, "text": "Want to team up?"},
        ]
        wire = p.build_model_wire_text(state)
        self.assertIn("chat.private.t0.0", wire)
        self.assertIn("reply only to turn 5", wire)
        self.assertNotIn("DMs received this turn:", wire)

    def test_chat_shortcut_syntax(self):
        state = snapshot()
        flat = {
            "thought.situation": "Test",
            "thought.strategy": "Test",
            "decision_summary": "Chat shortcuts.",
            "chat.all": "Hello everyone.",
            "chat.Caesar": "Meet me in private.",
        }
        expanded = p.expand_flat_response(flat)
        self.assertEqual(2, len(expanded["chat_messages"]))
        self.assertEqual("all", expanded["chat_messages"][0]["target"])
        self.assertEqual("Hello everyone.", expanded["chat_messages"][0]["text"])
        self.assertEqual("player", expanded["chat_messages"][1]["target"])
        self.assertEqual("Caesar", expanded["chat_messages"][1]["target_player_id"])
        cleaned = p.normalize_model_response(state, expanded)
        validated = p.validate_model_response(state, cleaned)
        self.assertEqual("PLAYER_1", validated["chat_messages"][1]["target_player_id"])

    def test_propose_deal_injects_private_chat_when_missing(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_propose_diplomacy_PLAYER_1_PROPOSAL_DEFENSIVE_PACT_1",
            "kind": "propose_deal",
            "description": "Propose defensive pact to Caesar",
            "fixed_arguments": {
                "target_player_id": "PLAYER_1",
                "proposal_id": "PROPOSAL_DEFENSIVE_PACT_1",
            },
            "parameter_domains": {},
            "affected_ids": ["PLAYER_1", "PROPOSAL_DEFENSIVE_PACT_1"],
            "runtime_status": "implemented_untested",
        })
        response = {
            "thought": sample_thought(),
            "decision_summary": "Secure Rome with a defensive pact.",
            "recommendation_decisions": [],
            "commands": [{"command_id": "CMD_propose_diplomacy_PLAYER_1_PROPOSAL_DEFENSIVE_PACT_1", "arguments": {}}],
            "chat_messages": [],
        }
        normalized = p.normalize_model_response(state, response)
        self.assertEqual(1, len(normalized["chat_messages"]))
        chat = normalized["chat_messages"][0]
        self.assertEqual("player", chat["target"])
        self.assertEqual("PLAYER_1", chat["target_player_id"])
        self.assertIn("Caesar", chat["text"])
        validated = p.validate_model_response(state, normalized)
        self.assertEqual(1, len(validated["chat_messages"]))

    def test_model_instructions_gandhi_voice(self):
        state = snapshot()
        state["personality"]["leader_id"] = "LEADER_GANDHI"
        state["personality"]["leader_name"] = "Gandhi"
        wire = p._model_instructions(state)
        role = p._model_role_instruction(state)
        self.assertIn("unhinged Gandhi", wire)
        self.assertIn("nuclear weapons", wire)
        self.assertIn("Gandhi exception", wire)
        self.assertIn("standalone bombs", wire)
        self.assertIn("Rapid chat.all chains", wire)
        self.assertIn("legendary unhinged Gandhi", role)
        self.assertIn("nuclear-apocalypse energy", role)

    def test_build_personality_derives_leader_display_name(self):
        source = {
            "turn": 0, "year": -4000, "active_player_id": 1, "game_uuid": "test",
            "player": {"leader_id": "LEADER_WASHINGTON", "civilization_id": "CIVILIZATION_AMERICA",
                "research_id": "TECH_HUNTING"},
            "empire": {}, "visible": {"width": 1, "height": 1, "grid": ["?"], "cities": [], "units": []},
            "public": {"players": []}, "settings": {"width": 1, "height": 1},
            "legal_actions": [],
        }
        state = p.build_model_input(source)
        self.assertEqual("Washington", state["personality"]["leader_name"])
        wire = p.build_model_wire_text(state)
        self.assertIn("player = Washington playing as AMERICA (PLAYER_1)", wire)
        role = p._model_role_instruction(state)
        self.assertIn("playing as the AMERICA civilization", role)
        self.assertNotIn("leader of", role)

    def test_model_instructions_include_move_guidance_when_moves_legal(self):
        wire = p.build_model_wire_text(snapshot())
        self.assertIn("as many city/unit/empire lines as you need", wire)
        self.assertIn("unitId.moveTo = (x,y)", wire)
        self.assertIn("carefully inspect the attached minimap", wire)

    def test_model_instructions_include_move_guidance_when_moves_legal_with_cmd(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_MOVE_SCOUT",
            "kind": "move_group",
            "description": "Move scout",
            "fixed_arguments": {
                "unit_id": "UNIT_0",
                "mission_id": "MISSION_MOVE_TO",
                "data1_id": "INT_1",
                "data2_id": "INT_0",
                "target_plot_id": "PLOT_1_0",
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_0"],
            "runtime_status": "tested",
        })
        wire = p.build_model_wire_text(state)
        self.assertIn("as many city/unit/empire lines as you need", wire)
        self.assertIn("unitId.moveTo = (x,y)", wire)
        self.assertIn("carefully inspect the attached minimap", wire)

    def test_upgrade_legacy_source_preserves_leader_traits(self):
        source = {
            "turn": 1, "year": 500, "active_player_id": 0, "game_uuid": "test",
            "player": {"leader_id": "LEADER_ALEXANDER", "leader_name": "Alexander",
                "civilization_id": "CIVILIZATION_GREECE", "research_id": "TECH_POTTERY",
                "leader_traits": {"aggression": "high", "diplomacy": "guarded"}},
            "public": {"players": []}, "visible": {}, "settings": {"width": 2, "height": 1},
            "legal_actions": {}, "advc_recommendations": []}
        state = p.build_model_input(source)
        self.assertEqual("high", state["personality"]["leader_traits"]["aggression"])

    def test_normalize_leader_traits_flattens_trait_ids(self):
        traits = p._normalize_leader_traits({
            "military_flavor": 8,
            "trait_ids": ["TRAIT_PHILOSOPHICAL", "TRAIT_ORGANIZED"],
        })
        self.assertEqual("8", traits["military_flavor"])
        self.assertEqual("PHILOSOPHICAL,ORGANIZED", traits["trait_ids"])
        state = snapshot()
        state["player"] = {
            "leader_id": "LEADER_WILLEM",
            "leader_name": "Willem",
            "civilization_id": "CIVILIZATION_DUTCH",
            "leader_traits": {
                "military_flavor": 8,
                "base_peace_weight": 2,
                "trait_ids": ["TRAIT_PHILOSOPHICAL", "TRAIT_ORGANIZED"],
            },
        }
        source = {
            "turn": 1, "year": 500, "active_player_id": 0, "game_uuid": "test",
            "player": state["player"],
            "public": {"players": []}, "visible": {}, "settings": {"width": 2, "height": 1},
            "legal_actions": {}, "advc_recommendations": []}
        built = p.build_model_input(source)
        p.validate_snapshot(built)

    def test_personality_leader_traits_follow_live_snapshot(self):
        state = snapshot()
        state["personality"]["leader_traits"] = {"military_flavor": "5"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "player.json"
            run_v2._apply_personality(state, path)
            state["personality"]["leader_traits"] = {"military_flavor": "9"}
            run_v2._apply_personality(state, path)
            self.assertEqual("9", state["personality"]["leader_traits"]["military_flavor"])

    def test_compact_legal_wire_groups_commands(self):
        state = json.loads((p.ROOT / "fixtures" / "map_snapshots" / "p0_t2.json").read_text(encoding="utf-8"))
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("Capital.changeProduction = settler | worker | scout", wire)
        self.assertIn("archer_1.stance = skip | fortify | sentry", wire)
        self.assertIn("legal.commerce.research = 100", wire)
        self.assertIn("legal.expansion = settle | balanced | defend", wire)
        self.assertNotIn("CHANGE_WORKING_PLOT", wire)
        self.assertNotIn("CMD_city_task", wire)

    def test_compact_legal_wire_smaller_than_verbose(self):
        state = json.loads((p.ROOT / "fixtures" / "map_snapshots" / "p0_t2.json").read_text(encoding="utf-8"))
        compact = p.build_flat_wire_prompt(p.build_playable_context(state))
        with mock.patch.dict(os.environ, {"CIV4AI_COMPACT_LEGAL_WIRE": "0", "CIV4AI_COMPACT_SITUATION_WIRE": "0"}):
            verbose = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertLess(len(compact), len(verbose) * 0.7)

    def test_legal_commerce_wire_resolve(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_set_commerce_COMMERCE_RESEARCH_PERCENT_100",
            "kind": "change_commerce",
            "description": "Research 100",
            "fixed_arguments": {"commerce_id": "COMMERCE_RESEARCH", "percent_id": "PERCENT_100"},
            "parameter_domains": {},
            "affected_ids": [],
            "runtime_status": "implemented_untested",
        })
        flat = {"legal.commerce.research": "100"}
        resolved = p.resolve_property_wire(state, flat)
        self.assertEqual("CMD_set_commerce_COMMERCE_RESEARCH_PERCENT_100", resolved["cmd.0"])

    def test_city_health_buckets_legacy_negative_rate(self):
        buckets = p._city_health_buckets({"health": -1, "unhealth": 2})
        self.assertEqual(0, buckets["positive"])
        self.assertEqual(2, buckets["negative"])
        self.assertEqual(-2, buckets["net"])

    def test_city_health_buckets_good_bad_fields(self):
        buckets = p._city_health_buckets({"good_health": 4, "bad_health": 1})
        self.assertEqual(4, buckets["positive"])
        self.assertEqual(1, buckets["negative"])
        self.assertEqual(3, buckets["net"])

    def test_allow_empty_commands_when_legal_nonempty(self):
        state = snapshot()
        state["advciv"]["recommendations"] = []
        response = with_thought({"decision_summary": "Thinking.", "recommendation_decisions": [],
                    "commands": [], "chat_messages": []})
        validated = p.validate_model_response(state, response)
        self.assertEqual([], validated["commands"])
        self.assertTrue(any(r.get("category") == "no_model_commands" for r in validated["rejections"]))

    def test_sanitize_summary_cmd_without_matching_commands(self):
        state = snapshot()
        response = with_thought({"decision_summary": "Execute CMD_DECLARE_WAR this turn.",
                    "recommendation_decisions": [],
                    "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}}],
                    "chat_messages": []})
        validated = p.validate_model_response(state, response)
        self.assertEqual(1, len(validated["commands"]))
        self.assertNotIn("CMD_DECLARE_WAR", validated["decision_summary"])

    def test_wire_legal_declare_war_risk_annotation(self):
        state = snapshot()
        state["legal_commands"].append({
            "command_id": "CMD_DECLARE_WAR", "kind": "declare_war", "description": "War",
            "fixed_arguments": {}, "parameter_domains": {}, "affected_ids": ["TEAM_1"],
            "runtime_status": "implemented_untested"})
        wire = p.build_flat_wire_prompt(state)
        self.assertIn("risk=high", wire)
        self.assertIn("CMD_DECLARE_WAR", wire)
        self.assertIn("# 1.", wire)

    def test_normalize_snapshot_skips_no_research_placeholder(self):
        source = {
            "turn": 1, "year": 500, "active_player_id": 0, "game_uuid": "test",
            "player": {"leader_id": "LEADER_ALEXANDER", "leader_name": "Alexander",
                "civilization_id": "CIVILIZATION_GREECE", "research_id": "NO_TECH"},
            "public": {"players": []}, "visible": {}, "settings": {"width": 2, "height": 1},
            "legal_actions": {}, "advc_recommendations": []}
        state = p.build_model_input(source)
        self.assertFalse(any(item["command_id"] == "CMD_NO_RESEARCH" for item in state["legal_commands"]))

    def test_playable_wire_text_omits_nested_json_blob(self):
        state = snapshot()
        wire = p.build_model_wire_text(state)
        self.assertNotIn('"schema_version"', wire)
        self.assertIn("turn =", wire)
        self.assertIn("=== CURRENT SITUATION ===", wire)

    def test_public_stats_in_wire_prompt(self):
        state = snapshot()
        state["decision"]["year"] = 1250
        state["your_empire"]["score"] = 321
        state["your_empire"]["costs"] = {
            "unit_cost": 4, "unit_supply": 2, "city_maintenance": 7, "civic_upkeep": 3, "inflation": 1,
        }
        state["your_empire"]["unit_counts"]["settlers"] = 2
        state["known_players"][0]["score"] = 90
        state["known_players"][0]["population"] = 3
        state["known_players"][0]["land"] = 12
        state["known_players"][0]["power"] = 80
        state["known_players"][0]["relation"]["open_borders"] = True
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("game.year = 1250", wire)
        self.assertIn("empire.score = 321", wire)
        self.assertIn("empire.cities = 1", wire)
        self.assertIn("empire.commerce.research.percent = 25", wire)
        self.assertIn("empire.costs.city_maintenance = 7", wire)
        self.assertIn("empire.units.settlers = 2", wire)
        self.assertIn("rival.PLAYER_1.score = 90", wire)
        self.assertIn("rival.PLAYER_1.population = 3", wire)
        self.assertIn("rival.PLAYER_1.land = 12", wire)
        self.assertIn("rival.PLAYER_1.power = 80", wire)
        self.assertIn("rival.PLAYER_1.open_borders = true", wire)

    def test_thought_turns_for_prompt_recent_and_milestones(self):
        self.assertEqual([10, 20, 30, 31, 32, 33, 34, 35],
                         p.thought_turns_for_prompt(36))
        self.assertEqual([], p.thought_turns_for_prompt(0))

    def test_inject_thought_history_and_wire_prompt(self):
        state = snapshot()
        state["decision"]["turn"] = 36
        memory = {
            "session_key": "game:player:0",
            "thoughts": [
                {"turn": 10, "situation": "Early expansion.", "strategy": "Explore."},
                {"turn": 35, "situation": "Rome is cautious.", "strategy": "Fortify Athens."},
            ],
        }
        p.inject_thought_history(state, memory)
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("thought.t10.situation = Early expansion.", wire)
        self.assertNotIn("thought.t35.strategy", wire)
        self.assertNotIn("thought.t11.", wire)

    def test_thought_memory_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thought.json"
            session_key = "game-1:player:0"
            memory = p.load_thought_memory(path, session_key)
            memory = p.append_thought(memory, 5, "Turn five.", "Hold.")
            p.save_thought_memory(path, memory)
            loaded = p.load_thought_memory(path, session_key)
            self.assertEqual(1, len(loaded["thoughts"]))
            memory = p.append_thought(loaded, 5, "Turn five revised.", "Hold harder.")
            self.assertEqual("Turn five revised.", memory["thoughts"][0]["situation"])

    def test_expand_flat_parses_opinion_lines(self):
        state = snapshot()
        flat = {
            "thought.situation": "Rome lurks across the sea.",
            "thought.strategy": "Fortify Athens and research.",
            "decision_summary": "Hold Athens.",
            "opinion.Caesar": "Dangerous neighbor; trade when useful.",
            "recommendation_decisions": [],
            "commands": [],
            "chat_messages": [],
        }
        expanded = p.expand_flat_response(flat, state)
        self.assertEqual(
            {"PLAYER_1": "Dangerous neighbor; trade when useful."},
            expanded["player_opinions"],
        )

    def test_update_player_opinions_persists_and_wire_includes_them(self):
        state = snapshot()
        state["decision"]["turn"] = 10
        memory = {
            "session_key": "game:player:0",
            "thoughts": [],
            "player_opinions": {},
        }
        memory = p.update_player_opinions(
            memory,
            8,
            {"PLAYER_1": "Caesar is cautious but a useful trading partner."},
        )
        p.inject_thought_history(state, memory)
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("opinion.Caesar =", wire)
        self.assertNotIn("opinion.PLAYER_1 =", wire)
        self.assertIn("useful trading partner", wire)
        memory = p.update_player_opinions(
            memory,
            10,
            {"PLAYER_1": "Caesar proved reliable on open borders."},
        )
        self.assertEqual(
            "Caesar proved reliable on open borders.",
            memory["player_opinions"]["PLAYER_1"]["text"],
        )
        self.assertEqual(10, memory["player_opinions"]["PLAYER_1"]["updated_turn"])

    def test_normalize_model_response_cleans_player_opinions(self):
        state = snapshot()
        response = with_thought({
            "decision_summary": "Hold Athens.",
            "player_opinions": {"PLAYER_1": "Wary neighbor."},
            "recommendation_decisions": [{"recommendation_id": "REC_RESEARCH", "decision": "accept"}],
            "commands": [{"command_id": "CMD_RESEARCH", "arguments": {}}],
            "chat_messages": [],
        })
        normalized = p.normalize_model_response(state, response)
        self.assertEqual(
            {"text": "Wary neighbor.", "updated_turn": 1},
            normalized["player_opinions"]["PLAYER_1"],
        )

    def test_substitute_player_ids_in_chat_text(self):
        state = snapshot()
        text = p._substitute_player_ids_in_text(
            "PLAYER_1, your bluster amuses me.",
            state,
        )
        self.assertEqual("Caesar, your bluster amuses me.", text)

    def test_opinion_wire_key_uses_leader_name(self):
        state = snapshot()
        self.assertEqual("opinion.Caesar", p._opinion_wire_key(state, "PLAYER_1"))

    def test_load_thought_memory_bootstraps_from_extracted_blob(self):
        session_key = "seed-abc:player:0"
        extracted = {
            "history": {
                "civ4ai_thought_memory": {
                    "session_key": session_key,
                    "thoughts": [{"turn": 5, "situation": "Board tight.", "strategy": "Expand."}],
                    "player_opinions": {"PLAYER_1": {"text": "Wary.", "updated_turn": 5}},
                    "player_histories": {"PLAYER_1": {"text": "T5 met.", "updated_turn": 5}},
                },
            },
        }
        memory = p.load_thought_memory(Path("missing.json"), session_key, extracted)
        self.assertEqual(session_key, memory["session_key"])
        self.assertEqual("Wary.", memory["player_opinions"]["PLAYER_1"]["text"])
        self.assertEqual("T5 met.", memory["player_histories"]["PLAYER_1"]["text"])

    def test_player_history_appends_and_wire_uses_leader_name(self):
        state = snapshot()
        memory = {"session_key": "k", "thoughts": [], "player_opinions": {}, "player_histories": {}}
        memory = p.update_player_histories(memory, 3, {"PLAYER_1": "T0 greeted in lobby."})
        memory = p.update_player_histories(memory, 11, {"PLAYER_1": "T11 met for first time."})
        self.assertEqual(
            "T0 greeted in lobby. T11 met for first time.",
            memory["player_histories"]["PLAYER_1"]["text"],
        )
        p.inject_thought_history(state, memory)
        wire = p.build_flat_wire_prompt(p.build_playable_context(state))
        self.assertIn("history.Caesar = T0 greeted in lobby. T11 met for first time.", wire)
        self.assertNotIn("history.PLAYER_1 =", wire)

    def test_expand_flat_parses_history_line(self):
        state = snapshot()
        flat = {
            "thought.situation": "Caesar sent a message.",
            "thought.strategy": "Watch Rome.",
            "decision_summary": "Hold.",
            "history.Caesar": "T4 public taunt in lobby.",
            "recommendation_decisions": [],
            "commands": [],
            "chat_messages": [],
        }
        expanded = p.expand_flat_response(flat, state)
        self.assertEqual(
            {"PLAYER_1": "T4 public taunt in lobby."},
            expanded["player_histories"],
        )

    def test_normalize_keeps_opinions_for_lobby_chat_rivals_before_meet(self):
        state = snapshot()
        state["known_players"].append({
            "player_id": "PLAYER_5",
            "team_id": "TEAM_5",
            "leader_id": "LEADER_MEHMED",
            "leader_name": "Mehmed II",
            "civilization_id": "CIVILIZATION_OTTOMAN",
            "relation": relation(),
        })
        state["history"]["public_events"] = [
            {"turn": 1, "kind": "CHAT_PUBLIC", "summary": "Hello lobby.", "affected_ids": ["PLAYER_5"]},
        ]
        response = with_thought({
            "decision_summary": "Scout and hold.",
            "opinion.Mehmed II": "Boisterous Ottoman; watch closely.",
            "recommendation_decisions": [],
            "commands": [],
            "chat_messages": [],
        })
        normalized = p.normalize_model_response(state, response)
        self.assertEqual(
            "Boisterous Ottoman; watch closely.",
            normalized["player_opinions"]["PLAYER_5"]["text"],
        )

    def test_history_block_keeps_recent_public_chat_only(self):
        events = [
            {"turn": index, "kind": "CHAT_PUBLIC", "summary": f"msg{index}", "affected_ids": []}
            for index in range(20)
        ]
        trimmed = p._recent_history_events(events, 12)
        self.assertEqual(12, len(trimmed))
        self.assertEqual(8, trimmed[0]["turn"])
        self.assertEqual(19, trimmed[-1]["turn"])


class RunFixtureShimTests(unittest.TestCase):
    def test_run_fixture_offline_smoke(self) -> None:
        from sidecar import run_fixture

        with tempfile.TemporaryDirectory() as temporary:
            journal = Path(temporary) / "journal.json"
            personality = Path(temporary) / "personality.json"
            argv = [
                "run_fixture",
                "--state",
                str(p.ROOT / "fixtures" / "map_snapshots" / "p0_t2.json"),
                "--journal",
                str(journal),
                "--personality",
                str(personality),
            ]
            with mock.patch.object(sys, "argv", argv):
                run_fixture.main()
            self.assertTrue(journal.is_file())
            record = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
            self.assertIn(record.get("status"), {"approved", "fallback"})


if __name__ == "__main__":
    unittest.main()
