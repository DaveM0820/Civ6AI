from sidecar import civ6_water, civ6_apply_results as ar, civ6_recall_facts as rf


def _plot(x, y, water=False, terrain=None):
    p = {"x": x, "y": y, "terrain_id": terrain or ("TERRAIN_COAST" if water else "TERRAIN_PLAINS")}
    if water:
        p["water"] = True
    return p


def _snap(plots, units=None, cities=None, techs=None):
    return {"known_map": {"plots": plots}, "your_units": units or [], "your_cities": cities or [],
            "civ6": {}, "game": {"map_width": 40},
            "your_empire": {"research": {"known_tech_ids": techs or []}}}


def _grid(water=(), size=8):
    return [_plot(x, y, (x, y) in water) for x in range(size) for y in range(size)]


def test_enclosed_small_water_is_lake():
    s = _snap(_grid(water={(3, 3)}))
    assert civ6_water.lake_tiles(s) == {(3, 3)}
    assert civ6_water.shore_kind(s, 4, 3) == "lake shore only"
    assert civ6_water.shore_kind(s, 0, 0) == "inland"


def test_water_touching_fog_is_sea():
    s = _snap(_grid(water={(0, 3)}))
    assert civ6_water.shore_kind(s, 1, 3) == "sea coast"


def test_city_counts_split_lake_and_sea():
    s = _snap(_grid(water={(3, 3), (0, 6)}), cities=[{"x": 4, "y": 3}, {"x": 1, "y": 6}])
    assert civ6_water.city_shore_counts(s) == (1, 1)


def test_site_fact_route_length():
    s = _snap(_grid())
    fact = civ6_water.site_fact(s, {"x": 5, "y": 2, "label": "S1"}, [("settler_1", (1, 2))])
    assert fact == "S1 (5,2): inland; on your landmass, land route ~4 tiles from settler_1"


def test_site_fact_other_land():
    plots = [_plot(x, y, water=(x == 3)) for x in range(7) for y in range(4)]
    plots = [p for p in plots]
    s = _snap(plots)
    # close the map edges with water so the settler's land is fully known
    fact = civ6_water.site_fact(s, {"x": 5, "y": 1, "label": "S1"}, [("settler_1", (1, 1))])
    assert "S1 (5,1)" in fact and ("needs embark" in fact or "no known land route" in fact)


def test_ship_land_drop_lists_water():
    s = _snap(_grid(water={(0, 0), (1, 0), (2, 0)}))
    ship = {"unit_id": "U", "plot_id": "PLOT_0_0", "domain_id": "DOMAIN_SEA"}
    text = ar.move_failure_text(s, "galley_1", 2, 1, "land", "P0", "DOMAIN_SEA", ship)
    assert "Nearest reachable water toward it:" in text


def test_stack_limit_not_military_only():
    assert "military units already" not in ar.describe_reason("stack_limit")


def test_landmass_clause_ignores_ships():
    s = _snap(_grid(), units=[{"domain_id": "DOMAIN_SEA"}])
    assert not rf._can_reach_other_land(s)
    s["your_empire"]["research"]["known_tech_ids"] = ["TECH_SHIPBUILDING"]
    assert rf._can_reach_other_land(s)
