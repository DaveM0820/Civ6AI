"""Fix round 6 (g9 T50 review): explore line on the real prompt path, Skip on civilian rows,
fishing-boat sites, home-island and strategy-age facts, cross-seat chat copies."""
from sidecar import civ6_apply_results as ar
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_seat_memory as mem
from sidecar import civ6_wire as wire
from sidecar.tests.test_civ6_fixround5 import _snap


def test_settle_sites_explore_line_reaches_the_full_prompt():
    snap = _snap(["TECH_SHIPBUILDING"])
    # The playable context strips known_map.plots, which the line needs.
    assert wire.few_sites_explore_line(wire.build_civ6_playable_context(snap)) is None
    text = wire.build_civ6_model_wire_text(snap)
    assert "SETTLE SITES:" in text and "Unexplored edge on land" in text


def test_civilian_required_rows_keep_skip_military_rows_do_not():
    assert wire._required_unit_options(["MoveTo(x,y)", "Skip"]) == ["MoveTo(x,y)", "Skip"]
    assert wire._required_unit_options(["MoveTo(x,y)", "Improve(1,1,IMPROVEMENT_FARM)", "Skip"])[-1] == "Skip"
    assert wire._required_unit_options(["MoveTo(x,y)", "Fortify", "Skip"]) == ["MoveTo(x,y)", "Fortify"]


def test_builder_sites_include_owned_sea_resources_after_sailing():
    snap = {"decision": {"player_id": "PLAYER_0"},
            "your_empire": {"research": {"known_tech_ids": ["TECH_SAILING"]}},
            "known_map": {"plots": [
                {"x": 1, "y": 1, "water": True, "terrain_id": "TERRAIN_COAST", "resource_id": "RESOURCE_FISH",
                 "revealed_owner_id": "PLAYER_0"},
                {"x": 2, "y": 1, "water": True, "terrain_id": "TERRAIN_COAST", "revealed_owner_id": "PLAYER_0"},
                {"x": 3, "y": 1, "water": True, "terrain_id": "TERRAIN_OCEAN", "resource_id": "RESOURCE_WHALES",
                 "revealed_owner_id": "PLAYER_0"},
            ]}}
    sites = coaching.builder_improve_sites(snap, 0, 0)
    assert [(s["x"], s["y"]) for s in sites] == [(1, 1)]
    snap["your_empire"]["research"]["known_tech_ids"] = []
    assert coaching.builder_improve_sites(snap, 0, 0) == []


def test_home_island_line_needs_no_home_site_and_no_embark():
    snap = _snap([])
    snap["civ6"] = {"governance": {"techs": {"options": [{"id": "TECH_SHIPBUILDING", "turns": 11}]}}}
    line = wire.home_island_full_line(snap)
    assert line and "Shipbuilding: 11 turns" in line and "Cartography" in line
    assert wire.home_island_full_line(_snap(["TECH_SHIPBUILDING"])) is None
    snap["civ6"]["settle_recommended"] = [{"x": 0, "y": 0}]
    import unittest.mock as mock
    with mock.patch("sidecar.civ6_command_wire.game_settle_recommendations", return_value=[{"x": 0, "y": 2}]):
        assert wire.home_island_full_line(snap) is None


def test_strategy_age_note_after_twenty_turns():
    memory = mem.apply_plan({}, 10, {"strategy": "Science via campuses"})
    assert "plan.strategy.age" not in dict(mem.prompt_lines(memory, 29))
    note = dict(mem.prompt_lines(memory, 30))["plan.strategy.age"]
    assert "20 turns ago (T10)" in note and "omit the key to keep it" in note
    assert "plan.strategy.age" not in dict(mem.prompt_lines(memory))


def test_near_verbatim_copy_of_another_players_line_is_dropped():
    line = "Pella's markets hum with Macedonian ambition; may your builders keep pace with ours."
    snap = {"decision": {"player_id": "PLAYER_2"}, "personality": {"leader_name": "Chandragupta"},
            "history": {"public_events": [{"kind": "CHAT_PUBLIC", "affected_ids": ["PLAYER_0"],
                                           "text": "Alexander: " + line}]}}
    kept, notes = ar.filter_repeat_public_chat(snap, [{"target": "all", "text": line}])
    assert kept == [] and any("copied another player's" in n for n in notes)
    own = "Patna's granaries are full and my Varu are bored; who wants to trade for spices?"
    kept, _ = ar.filter_repeat_public_chat(snap, [{"target": "all", "text": own}])
    assert len(kept) == 1
