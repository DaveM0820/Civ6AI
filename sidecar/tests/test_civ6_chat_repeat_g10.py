from sidecar import civ6_apply_results as results


def _snap(events, turn=20, me="PLAYER_1"):
    return {"decision": {"player_id": me, "turn": turn}, "history": {"public_events": events}}


def _ev(sender, turn, text):
    return {"kind": "CHAT_PUBLIC", "affected_ids": [sender], "turn": turn, "text": text}


LINE = ("Harald, your longships may chart waters, but my warriors chart land and I intend "
        "to claim every island before the tides turn.")


def test_own_exact_repeat_within_ten_turns_is_dropped():
    kept, dropped = results.filter_repeat_public_chat(_snap([_ev("PLAYER_1", 13, LINE)]), [{"text": LINE}])
    assert kept == []
    assert any(d.startswith("dropped: chat repeated your own line from turn 13") for d in dropped)


def test_own_near_repeat_is_dropped_but_old_repeat_is_allowed():
    near = LINE.replace("land and", "land, and")
    kept, _ = results.filter_repeat_public_chat(_snap([_ev("PLAYER_1", 15, LINE)]), [{"text": near}])
    assert kept == []
    kept, _ = results.filter_repeat_public_chat(_snap([_ev("PLAYER_1", 5, LINE)]), [{"text": LINE}])
    assert len(kept) == 1


def test_shared_six_word_phrase_from_other_player_is_dropped():
    mine = "Samarkand, your stone is well-placed, but I intend to claim every island before the tides turn."
    kept, dropped = results.filter_repeat_public_chat(_snap([_ev("PLAYER_2", 19, LINE)], me="PLAYER_0"), [{"text": mine}])
    assert kept == []
    assert any("6+ word phrase" in d for d in dropped)


def test_fresh_line_passes():
    fresh = "Lost my warrior to that spearman, but his friends in the quadrireme will find my galley waiting."
    kept, dropped = results.filter_repeat_public_chat(_snap([_ev("PLAYER_2", 19, LINE), _ev("PLAYER_1", 18, LINE)]),
                                                      [{"text": fresh}])
    assert len(kept) == 1 and not dropped
