from sidecar import run_civ6


def test_wrong_unit_type():
    note = run_civ6.unresolved_order_note("warrior_1.command=Improve(25,14,CAMP)")
    assert "warrior_1 is a Warrior; only Builders can Improve" in note


def test_other_verb():
    note = run_civ6.unresolved_order_note("scout_2.command=Pillage")
    assert "scout_2 is a Scout; Pillage is not one of its legal commands" in note


def test_unparsed_falls_back():
    assert run_civ6.unresolved_order_note("weird") == "dropped: unresolved token weird"
