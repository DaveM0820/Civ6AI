"""Research / civic targets: static tree, path, auto step, prompt lines, plan keys."""
from sidecar import civ6_command_wire as cw
from sidecar import civ6_research_target as rt
from sidecar import civ6_seat_memory as mem
from sidecar import civ6_wire
from sidecar.tests.test_civ6_wp_c_feedback import _snap

KNOWN = ["TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_MINING", "TECH_ASTROLOGY"]


def _gov_snap(target=None, civic_target=None, legal=("TECH_SAILING", "TECH_ARCHERY", "TECH_WRITING")):
    snap = _snap()
    snap["your_empire"]["research"] = {"known_tech_ids": list(KNOWN)}
    snap["your_empire"]["civics"] = [{"key": "known", "id": "CIVIC_CODE_OF_LAWS"}]
    snap.setdefault("civ6", {})["governance"] = {
        "techs": {"current": "TECH_IRRIGATION", "turns_left": 2, "science_per_turn": 5,
                  "options": [{"id": t, "turns": 5} for t in ("TECH_SAILING", "TECH_ARCHERY", "TECH_WRITING")]},
        "civics": {"current": "CIVIC_CRAFTSMANSHIP", "turns_left": 3,
                   "options": [{"id": "CIVIC_FOREIGN_TRADE", "turns": 6}]},
    }
    snap["legal_commands"] = snap.get("legal_commands", []) + [
        {"command_id": "CMD_research_" + t, "kind": "set_research_tech", "fixed_arguments": {"tech_id": t}}
        for t in legal] + [
        {"command_id": "CMD_civic_CIVIC_FOREIGN_TRADE", "kind": "set_research_civic",
         "fixed_arguments": {"civic_id": "CIVIC_FOREIGN_TRADE"}}]
    plan = {}
    if target:
        plan["research_target"] = target
    if civic_target:
        plan["civic_target"] = civic_target
    snap["_seat_memory"] = {"plan": plan}
    return snap


def test_tree_matches_game_db_for_the_sea_techs():
    techs = rt.tree()["techs"]
    assert techs["TECH_SHIPBUILDING"]["prereqs"] == ["TECH_SAILING"]
    assert techs["TECH_CARTOGRAPHY"]["prereqs"] == ["TECH_BUTTRESS"]  # Gathering Storm
    assert len(techs) == 77 and len(rt.tree()["civics"]) == 61


def test_resolve_accepts_names_and_clear():
    assert rt.resolve("tech", "Shipbuilding") == "TECH_SHIPBUILDING"
    assert rt.resolve("tech", "TECH_CARTOGRAPHY") == "TECH_CARTOGRAPHY"
    assert rt.resolve("civic", "political philosophy") == "CIVIC_POLITICAL_PHILOSOPHY"
    assert rt.resolve("tech", "none") == ""
    assert rt.resolve("tech", "Warp Drive") is None


def test_path_and_auto_step_when_model_is_silent():
    snap = _gov_snap("TECH_SHIPBUILDING")
    assert rt.path(snap, "tech", "TECH_SHIPBUILDING") == ["TECH_SAILING", "TECH_SHIPBUILDING"]
    cmds = rt.auto_commands(snap, [])
    assert cmds == [{"command_id": "CMD_research_TECH_SAILING", "kind": "set_research_tech",
                     "arguments": {"tech_id": "TECH_SAILING"}, "source": "research_target"}]


def test_explicit_model_order_wins():
    snap = _gov_snap("TECH_SHIPBUILDING")
    model = [{"command_id": "CMD_research_TECH_ARCHERY", "kind": "set_research_tech", "arguments": {"tech_id": "TECH_ARCHERY"}}]
    assert rt.auto_commands(snap, model) == []


def test_no_step_when_not_a_choice_point():
    snap = _gov_snap("TECH_SHIPBUILDING", legal=())
    assert rt.auto_commands(snap, []) == []


def test_backups_prefer_the_path():
    snap = _gov_snap("TECH_CARTOGRAPHY")
    packed = cw.pack_apply_command(snap, {"command_id": "CMD_research_TECH_ARCHERY", "kind": "set_research_tech",
                                         "arguments": {"tech_id": "TECH_ARCHERY"}})
    on_path = set(rt.path(snap, "tech", "TECH_CARTOGRAPHY"))
    assert packed["arguments"]["tech_id_2"] in on_path


def test_plan_keys_set_clear_and_reach():
    reply = {"plan.research_target": "Shipbuilding", "plan.civic_target": "CIVIC_POLITICAL_PHILOSOPHY"}
    update = cw.extract_plan(reply)
    assert reply == {} and update["research_target"] == "TECH_SHIPBUILDING"
    memory = mem.apply_plan({}, 10, update)
    assert memory["plan"]["research_target"] == "TECH_SHIPBUILDING"
    memory = mem.apply_plan(memory, 11, cw.extract_plan({"plan.civic_target": "none"}))
    assert "civic_target" not in memory["plan"]
    snap = _gov_snap()
    snap["your_empire"]["research"]["known_tech_ids"].append("TECH_SHIPBUILDING")
    snap["decision"]["turn"] = 40
    memory = rt.observe(snap, memory)
    assert "research_target" not in memory["plan"]
    snap["_seat_memory"] = {"plan": memory["plan"]}
    assert any("reached" in line for line in rt.target_lines(snap))


def test_full_prompt_shows_path_and_tree():
    snap = _gov_snap("TECH_SHIPBUILDING", "CIVIC_POLITICAL_PHILOSOPHY")
    text = civ6_wire.build_civ6_model_wire_text(snap)
    assert "Research target: Shipbuilding — path: Sailing (5t) → Shipbuilding (" in text
    assert "Civic target: Political Philosophy — path:" in text
    assert "Tech tree (Ancient + Classical" in text
    assert "Shipbuilding [locked] <- Sailing [researchable 5t]" in text
    assert "Irrigation [researching 2t]" in text
    assert "Civic tree (Ancient + Classical" in text
