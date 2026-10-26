import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import preflight  # noqa: E402


def test_last_run_refusal_found():
    log = ("x CIV6AI|autotest|enabled|stop_turn=0\n"
           "x CIV6AI|autotest|refuse|turn_timer_on|cpl_smart_timer=0|fix=...\n")
    assert preflight.last_run_turn_timer(log) == "cpl_smart_timer=0"


def test_older_run_refusal_ignored():
    log = ("x CIV6AI|autotest|enabled|stop_turn=0\n"
           "x CIV6AI|autotest|refuse|turn_timer_on|turn_timer=TURNTIMER_STANDARD|fix=...\n"
           "x CIV6AI|autotest|enabled|stop_turn=0\n")
    assert preflight.last_run_turn_timer(log) is None
