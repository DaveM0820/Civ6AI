from sidecar import civ6_recall_facts as r


def _snap(tmp_path, turn, units):
    return {"decision": {"turn": turn}, "_session_dir": str(tmp_path), "visible_other_units": units,
            "known_players": []}


def test_barbarian_last_seen_lifecycle(tmp_path):
    slinger = {"owner_player_id": "PLAYER_63", "unit_id": "U1", "unit_type_id": "UNIT_SLINGER", "plot_id": "PLOT_42_14"}
    rival = {"owner_player_id": "PLAYER_2", "unit_id": "U9", "unit_type_id": "UNIT_WARRIOR", "plot_id": "PLOT_1_1"}
    assert r.barbarian_last_seen(_snap(tmp_path, 24, [slinger, rival])) == []          # visible now: not repeated
    assert r.barbarian_last_seen(_snap(tmp_path, 25, [])) == ["Barbarian Slinger (42,14) T24"]
    assert r.barbarian_last_seen(_snap(tmp_path, 26, [dict(slinger, plot_id="PLOT_43_14")])) == []  # visible again
    assert r.barbarian_last_seen(_snap(tmp_path, 31, [])) == ["Barbarian Slinger (43,14) T26"]
    assert r.barbarian_last_seen(_snap(tmp_path, 32, [])) == []                         # older than 5 turns


def test_landmass_line_flood_fill():
    plots = [{"x": x, "y": 4, "terrain_id": "TERRAIN_PLAINS"} for x in (2, 3, 4)]
    plots += [{"x": 5, "y": 4, "water": True}, {"x": 7, "y": 4, "terrain_id": "TERRAIN_PLAINS"}]
    snap = {"known_map": {"plots": plots}, "your_cities": [{"plot_id": "PLOT_3_4", "is_capital": True}],
            "your_units": [], "game": {"map_width": 20}}
    line = r.landmass_line(snap)
    assert line.startswith("3 known land tiles; unrevealed land on it: may continue past (2,4)")
    assert "Shipbuilding" in line
    snap["your_units"] = [{"domain_id": "DOMAIN_SEA"}]
    assert "Shipbuilding" not in r.landmass_line(snap)
    # fully ringed by known water: none
    ring = [{"x": x, "y": y, "water": True} for x in range(0, 6) for y in range(2, 7) if (x, y) != (3, 4)]
    snap2 = {"known_map": {"plots": ring + [{"x": 3, "y": 4}]}, "your_cities": [{"plot_id": "PLOT_3_4"}],
             "your_units": [], "game": {"map_width": 20}}
    assert "unrevealed land on it: none" in r.landmass_line(snap2)


def test_full_wire_text_includes_landmass_line():
    import json, os
    path = "/workspace/ji.json"
    if not os.path.exists(path):
        import pytest; pytest.skip("fixture absent")
    from sidecar import civ6_wire
    snap = json.load(open(path))["snapshot"]
    assert "map.landmass = " in civ6_wire.build_civ6_model_wire_text(snap)
