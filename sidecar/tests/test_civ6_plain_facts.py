from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire


def _snap():
    return {
        "game": {"map_width": 40, "wrap_x": False},
        "your_cities": [{"name": "LOC_CITY_NAME_QUSQU", "x": 10, "y": 10}],
        "your_units": [
            {"unit_id": "UNIT_7", "unit_type_id": "UNIT_SETTLER", "plot_id": "12,10", "x": 12, "y": 10},
            {"unit_id": "UNIT_8", "unit_type_id": "UNIT_SETTLER", "plot_id": "20,10", "x": 20, "y": 10},
        ],
        "known_map": {"plots": [
            {"x": 12, "y": 10, "water": False, "terrain_id": "TERRAIN_PLAINS"},
            {"x": 20, "y": 10, "water": True, "terrain_id": "TERRAIN_OCEAN"},
        ]},
        "your_empire": {"research": {"known_tech_ids": ["TECH_SHIPBUILDING"]}},
    }


def test_too_close_names_city_and_rule():
    snap = _snap()
    text = coaching.found_block_text(snap, snap["your_units"][0], "too_close_to_city")
    assert "Qusqu is 2 tiles away" in text and "at least 4 tiles" in text


def test_embarked_on_ocean():
    snap = _snap()
    assert coaching.embarked_text(snap["your_units"][1], snap).startswith("embarked on ocean")
    assert coaching.embarked_text(snap["your_units"][0], snap) is None


def test_ocean_rule_without_cartography():
    assert "ocean (deep water) needs Cartography" in coaching._water_and_embark_clause(_snap())


def test_found_alert_uses_unit_name():
    snap = _snap()
    out = civ6_wire._plain_found_alert(snap, "UNIT_7 cannot found a city on its tile (too_close_to_city).")
    assert "UNIT_7" not in out and "Qusqu" in out


def test_move_failure_names_blocker_and_stack_rule():
    from sidecar import civ6_apply_results as ar
    snap = _snap()
    text = ar.move_failure_text(snap, "warrior_1", 12, 10, "plot_occupied", "PLAYER_0")
    assert "UNIT_7" not in text and "Settler" in text and "can share" in text
    own = ar.move_failure_text(snap, "warrior_1", 12, 10, "already_there", "PLAYER_0")
    assert "already on (12,10)" in own


def test_upgrade_and_used_great_person_are_not_lost():
    from sidecar import civ6_turn_delta as td
    prev = {"units": {"U1": {"type": "UNIT_MAN_AT_ARMS", "label": "man_at_arms_1", "plot": "5,5"},
                      "U2": {"type": "UNIT_GREAT_MERCHANT", "label": "great_merchant_1", "plot": "6,6"}}}
    now = {"units": {"U3": {"type": "UNIT_MUSKETMAN", "label": "musketman_1", "plot": "5,5"}}}
    text = " | ".join(td.diff(prev, now))
    assert "LOST" not in text and "UPGRADED man_at_arms_1" in text and "used" in text


def test_idle_military_becomes_required_with_idle_count(monkeypatch):
    snap = {"your_units": [{"unit_id": "UNIT_9", "unit_type_id": "UNIT_ARCHER", "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
                            "plot_id": "3,3", "needs_orders": False}],
            "civ6": {"economy": {"tracking": {"idle_for": {"UNIT_9": 7}}}}}
    monkeypatch.setattr(civ6_wire, "_civ6_unit_tokens", lambda s: {"UNIT_9": ["MoveTo(4,3)", "Fortify"]})
    monkeypatch.setattr(civ6_wire, "_required_unit_options", lambda t: t)
    rows = dict(civ6_wire._civ6_required_rows(snap))
    hint = next(v for k, v in rows.items() if k.endswith(".command"))
    assert "idle 7 turns" in hint


def test_host_envoy_binds_to_city_state(monkeypatch):
    from sidecar import civ6_diplomacy as d
    import sidecar.civ6_fallbacks as fb
    snap = {"legal_commands": [], "diplomacy": {"envoys_to_give": 1, "city_states": [
        {"player_id": "PLAYER_20", "name": "Cardiff", "at_war": False}]}}
    monkeypatch.setattr(d, "diplomacy", lambda s: s["diplomacy"])
    monkeypatch.setattr(fb, "is_local_seat", lambda s: True)
    ids, notes = d._bind_envoy(snap, "envoy.send", "Cardiff, Brussels")
    assert len(ids) == 1 and notes
    monkeypatch.setattr(fb, "is_local_seat", lambda s: False)
    assert d._bind_envoy(snap, "envoy.send", "Cardiff")[0] == []


def test_compact_plots_get_defaults_back():
    from sidecar import civ6_adapter
    snap = {"known_map": {"plots": [{"x": 2, "y": 3, "terrain_id": "TERRAIN_COAST", "water": True, "knowledge": "visible"}]}}
    civ6_adapter._fill_plot_defaults(snap)
    p = snap["known_map"]["plots"][0]
    assert p["plot_id"] == "PLOT_2_3" and p["hills"] is False and p["city_id"] is None and p["water"] is True


def test_lua_compact_plot_drops_empty_fields():
    import lupa
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai" / "InGame"
    lua = lupa.LuaRuntime()
    lua.execute("Civ6Ai_Util = {}\n" + "function Civ6Ai_Util.JsonNull() return setmetatable({}, {__json_null=true}) end\n"
                + "function Civ6Ai_Util._IsJsonNull(v) local m = type(v)=='table' and getmetatable(v); return m and m.__json_null == true or false end\n"
                + "Civ6Ai_Snapshot = {}\n")
    src = (root / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8", errors="replace")
    start = src.index("Civ6Ai_Snapshot.PLOT_CONSTANT")
    end = src.index("\nend\n", src.index("function Civ6Ai_Snapshot._CompactPlot")) + 5
    lua.execute(src[start:end])
    rec = lua.eval("Civ6Ai_Snapshot._CompactPlot({x=1, y=2, water=false, hills=true, area_id='AREA_0', "
                   "city_id=Civ6Ai_Util.JsonNull(), visible_stack_ids={}, terrain_id='TERRAIN_PLAINS'})")
    assert sorted(rec.keys()) == ["hills", "terrain_id", "x", "y"]
