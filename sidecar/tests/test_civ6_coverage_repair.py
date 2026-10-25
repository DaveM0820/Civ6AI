"""Required unit rows must leave the sidecar as bound orders; one targeted repair."""
import json
from pathlib import Path

from sidecar import civ6_coverage as cov
from sidecar import civ6_command_wire as wire

SNAP = Path(__file__).resolve().parents[2] / "fixtures" / "civ6" / "live_t38_coverage_snapshot.json"


def _snap():
    return json.loads(SNAP.read_text(encoding="utf-8"))


def _hold(hint):
    opts = hint.split(" | ")
    return next((o for o in ("Fortify", "Skip", "Automate(explore)") if o in opts), opts[-1])


def _full_reply(snap):
    req = cov.required_unit_rows(snap)
    return req, {f"{i}.{key}": _hold(hint) for i, (key, hint) in enumerate(req.values(), start=1)}


def test_full_reply_is_covered_and_no_repair_call():
    snap = _snap()
    req, reply = _full_reply(snap)
    assert req
    calls = []
    out, stats = cov.repair(snap, reply, lambda p: calls.append(p) or "{}")
    assert calls == [] and out == reply
    assert stats["coverage_missing_before"] == 0


def test_dropped_and_omitted_units_get_one_targeted_ask():
    snap = _snap()
    req, reply = _full_reply(snap)
    (uid_a, (key_a, hint_a)), (uid_b, (key_b, hint_b)) = list(req.items())[:2]
    bad_key = next(k for k in reply if k.endswith(key_a))
    reply[bad_key] = "AttackTo(0,0)"  # binder drops: no legal attack
    reply.pop(next(k for k in reply if k.endswith(key_b)))  # model omitted it
    prompts = []

    def retry(prompt):
        prompts.append(prompt)
        return json.dumps({f"7.{key_a}": _hold(hint_a), key_b: _hold(hint_b)})

    before = list(wire.LAST_UNRESOLVED)
    out, stats = cov.repair(snap, reply, retry)
    assert len(prompts) == 1 and key_a in prompts[0] and key_b in prompts[0]
    assert "no attack is legal" in prompts[0]
    assert stats["coverage_missing_before"] == 2 and stats["coverage_missing_after"] == 0
    assert bad_key not in out and out[key_a] == _hold(hint_a)
    assert list(wire.LAST_UNRESOLVED) == before  # dry run leaves binder state alone


def test_switch_off(monkeypatch):
    monkeypatch.setenv("CIV6AI_COVERAGE_REPAIR", "0")
    snap = _snap()
    _, reply = _full_reply(snap)
    reply.popitem()
    out, stats = cov.repair(snap, reply, lambda p: (_ for _ in ()).throw(AssertionError("called")))
    assert out == reply and stats == {}
