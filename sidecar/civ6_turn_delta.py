"""What changed since this seat's last turn, and whether its notes keep up.

observe() diffs this snapshot against the compact board stored on the seat's
thought memory last turn: cities gained or lost, units gained or lost (a settler
that vanished next to a new city founded it; any other vanished unit was killed,
captured or disbanded), new contacts, wars started or ended. It also flags a
thought.situation that repeats the turn before, and carries last turn's
"said vs did" note. attention_items() turns all of it into ATTENTION lines,
led by CHANGED SINCE LAST TURN. Same-turn reruns reuse the first diff.
"""
from __future__ import annotations

from typing import Any

from sidecar import settings
from sidecar.civ6_common import dct as _dct
from sidecar.civ6_common import lst as _lst

STATE_KEY = "turn_delta"
SNAPSHOT_KEY = "_turn_delta"
LIST_CAP = 8


def _turn(snapshot: dict[str, Any]) -> int:
    try:
        return int(_dct(snapshot.get("decision")).get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def _xy(plot_id: Any) -> str:
    parts = str(plot_id or "").split("_")
    return f"({parts[1]},{parts[2]})" if len(parts) == 3 and parts[0] == "PLOT" else str(plot_id or "?")


def _type_name(unit_type: Any) -> str:
    text = str(unit_type or "UNIT").upper()
    return text[5:].replace("_", " ").title() if text.startswith("UNIT_") else text.title()


def board(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The compact facts the next turn diffs against."""
    from sidecar import pipeline_v2 as pipeline

    units = [u for u in _lst(snapshot.get("your_units")) if isinstance(u, dict) and u.get("unit_id")]
    labels = pipeline._build_unit_wire_id_map(units)
    diplo = _dct(_dct(snapshot.get("civ6")).get("diplomacy"))
    contacts: dict[str, str] = {}
    wars: list[str] = []
    for row in _lst(diplo.get("majors")) + _lst(diplo.get("city_states")):
        if not isinstance(row, dict) or not row.get("player_id"):
            continue
        pid = str(row["player_id"])
        contacts[pid] = str(row.get("name") or row.get("leader_name") or row.get("civ_name") or pid)
        if row.get("at_war") is True:
            wars.append(pid)
    return {
        "turn": _turn(snapshot),
        "cities": {
            str(c.get("city_id")): {"name": str(c.get("name") or c.get("city_id")), "plot": c.get("plot_id")}
            for c in _lst(snapshot.get("your_cities")) if isinstance(c, dict) and c.get("city_id")
        },
        "units": {
            str(u["unit_id"]): {"type": u.get("unit_type_id"), "plot": u.get("plot_id"),
                                "label": labels.get(str(u["unit_id"]), str(u["unit_id"]))}
            for u in units
        },
        "contacts": contacts,
        "wars": sorted(wars),
    }


def _near(a: Any, b: Any) -> bool:
    from sidecar.civ6_legality import hex_neighbors

    def xy(plot: Any) -> tuple[int, int] | None:
        parts = str(plot or "").split("_")
        try:
            return int(parts[1]), int(parts[2])
        except (IndexError, ValueError):
            return None

    pa, pb = xy(a), xy(b)
    return pa is not None and pb is not None and (pa == pb or pb in hex_neighbors(*pa))


def diff(prev: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Plain change bits, most important first. Empty when nothing changed."""
    bits: list[str] = []
    p_cities, n_cities = _dct(prev.get("cities")), _dct(now.get("cities"))
    p_units, n_units = _dct(prev.get("units")), _dct(now.get("units"))
    new_cities = [n_cities[c] for c in n_cities if c not in p_cities]
    for cid, city in p_cities.items():
        if cid not in n_cities:
            bits.append(f"LOST city {city.get('name')} at {_xy(city.get('plot'))}")
    for city in new_cities:
        bits.append(f"NEW city {city.get('name')} at {_xy(city.get('plot'))}")
    gone = [(uid, u) for uid, u in p_units.items() if uid not in n_units]
    founders = set()
    for uid, unit in gone:
        if "SETTLER" in str(unit.get("type") or "").upper() and any(
                _near(unit.get("plot"), city.get("plot")) for city in new_cities):
            founders.add(uid)
    lost = [(uid, u) for uid, u in gone if uid not in founders]
    # An upgrade replaces the unit with a new one on the same tile; a great
    # person is consumed when used. Neither is a loss.
    gained_now = {uid: u for uid, u in n_units.items() if uid not in p_units}
    upgraded = set()
    for uid, unit in lost:
        typ = str(unit.get("type") or "").upper()
        if "GREAT_" in typ:
            bits.append(f"used {_type_name(unit.get('type'))} {unit.get('label') or uid}")
            upgraded.add(uid)
            continue
        twin = next((g for gid, g in gained_now.items() if g.get("plot") == unit.get("plot")
                     and gid not in upgraded and "GREAT_" not in str(g.get("type") or "").upper()), None)
        if twin is not None:
            twin_id = next(gid for gid, g in gained_now.items() if g is twin)
            upgraded.add(twin_id)
            upgraded.add(uid)
            bits.append(f"UPGRADED {unit.get('label') or uid} to {_type_name(twin.get('type'))} "
                        f"{twin.get('label') or twin_id} at {_xy(unit.get('plot'))}")
    lost = [(uid, u) for uid, u in lost if uid not in upgraded]
    lost.sort(key=lambda row: 0 if "SETTLER" in str(row[1].get("type") or "").upper() else 1)
    for uid, unit in lost[:LIST_CAP]:
        bits.append(f"LOST {_type_name(unit.get('type'))} {unit.get('label') or uid} last at "
                    f"{_xy(unit.get('plot'))} (killed, captured or disbanded; it no longer exists)")
    if len(lost) > LIST_CAP:
        bits.append(f"{len(lost) - LIST_CAP} more units lost")
    gained = [(uid, u) for uid, u in n_units.items() if uid not in p_units and uid not in upgraded]
    gained.sort(key=lambda row: 0 if "SETTLER" in str(row[1].get("type") or "").upper() else 1)
    for uid, unit in gained[:LIST_CAP]:
        bits.append(f"new {_type_name(unit.get('type'))} {unit.get('label') or uid} at {_xy(unit.get('plot'))}")
    if len(gained) > LIST_CAP:
        bits.append(f"{len(gained) - LIST_CAP} more new units")
    p_contacts, n_contacts = _dct(prev.get("contacts")), _dct(now.get("contacts"))
    for pid, name in n_contacts.items():
        if pid not in p_contacts:
            bits.append(f"met {name}")
    p_wars, n_wars = set(_lst(prev.get("wars"))), set(_lst(now.get("wars")))
    for pid in sorted(n_wars - p_wars):
        bits.append(f"WAR with {n_contacts.get(pid, pid)}")
    for pid in sorted(p_wars - n_wars):
        bits.append(f"peace with {n_contacts.get(pid, p_contacts.get(pid, pid))}")
    return bits


TRAIL_LEN = 3
REVERSE_MIN_STEP = 2  # tiles moved in each leg before a turn-back counts


def _plot_xy(plot: Any) -> tuple[int, int] | None:
    parts = str(plot or "").split("_")
    try:
        return int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return None


def update_trails(prev_trails: dict[str, Any], now: dict[str, Any]) -> dict[str, list]:
    """Last TRAIL_LEN turn-start tiles per living unit (dead units drop out)."""
    out: dict[str, list] = {}
    for uid, unit in _dct(now.get("units")).items():
        xy = _plot_xy(unit.get("plot"))
        trail = [list(p) for p in _lst(_dct(prev_trails).get(uid)) if isinstance(p, list) and len(p) == 2]
        if xy is not None and (not trail or tuple(trail[-1]) != xy):
            trail.append(list(xy))
        out[uid] = trail[-TRAIL_LEN:]
    return out


def reversals(trails: dict[str, list], now: dict[str, Any]) -> list[str]:
    """Units whose last move ran back against the move before it."""
    out: list[str] = []
    for uid, trail in trails.items():
        if len(trail) < 3:
            continue
        (x0, y0), (x1, y1), (x2, y2) = trail[-3:]
        ax, ay, bx, by = x1 - x0, y1 - y0, x2 - x1, y2 - y1
        if max(abs(ax), abs(ay)) < REVERSE_MIN_STEP or max(abs(bx), abs(by)) < REVERSE_MIN_STEP:
            continue
        if ax * bx + ay * by < 0:
            label = _dct(_dct(now.get("units")).get(uid)).get("label") or uid
            out.append(f"{label} ({x0},{y0})->({x1},{y1})->({x2},{y2})")
    return out


def _token_overlap(a: str, b: str) -> float:
    from sidecar.civ6_apply_results import token_jaccard

    return token_jaccard(a, b)


def _prior_thoughts(memory: dict[str, Any], turn: int) -> list[dict[str, Any]]:
    rows = [t for t in _lst(memory.get("thoughts")) if isinstance(t, dict) and int(t.get("turn", -1)) < turn]
    rows.sort(key=lambda t: int(t.get("turn") or 0))
    return rows


def stale_situation(memory: dict[str, Any], turn: int) -> dict[str, Any] | None:
    """{'turn': t, 'overlap': pct} when the last situation repeated the one before it."""
    rows = _prior_thoughts(memory, turn)
    if len(rows) < 2:
        return None
    last, before = rows[-1], rows[-2]
    overlap = _token_overlap(str(last.get("situation") or ""), str(before.get("situation") or ""))
    if overlap * 100 >= settings.get_int("CIV6AI_STALE_SITUATION_PERCENT"):
        return {"turn": int(last.get("turn") or 0), "overlap": int(round(overlap * 100))}
    return None


def observe(snapshot: dict[str, Any], memory: dict[str, Any] | None) -> dict[str, Any]:
    """Diff, stale check and said-vs-did for this turn. Sets snapshot['_turn_delta']."""
    memory = memory if isinstance(memory, dict) else {}
    turn = _turn(snapshot)
    state = _dct(memory.get(STATE_KEY))
    now = board(snapshot)
    if int(state.get("turn") or -1) == turn and isinstance(state.get("prev"), dict):
        prev = state["prev"]  # same-turn rerun: diff against the same baseline
    else:
        prev = _dct(state.get("board"))
    delta: dict[str, Any] = {"turn": turn, "since": prev.get("turn"), "changes": diff(prev, now) if prev else None}
    stale = stale_situation(memory, turn)
    if stale:
        delta["stale"] = stale
    rows = _prior_thoughts(memory, turn)
    if rows and isinstance(rows[-1].get("orders_note"), str):
        said = [part.strip() for part in rows[-1]["orders_note"].split(";")
                if "your plan said" in part]
        if said:
            delta["said_vs_did"] = {"turn": int(rows[-1].get("turn") or 0), "notes": said}
    if int(state.get("turn") or -1) == turn and isinstance(state.get("prev_trails"), dict):
        prev_trails = state["prev_trails"]
    else:
        prev_trails = _dct(state.get("trails"))
    trails = update_trails(prev_trails, now)
    reversing = reversals(trails, now)
    if reversing:
        delta["reversing"] = reversing
    memory[STATE_KEY] = {"turn": turn, "board": now, "prev": prev, "trails": trails, "prev_trails": prev_trails}
    snapshot[SNAPSHOT_KEY] = delta
    return memory


def attention_items(context: Any) -> list[str]:
    delta = _dct(context.get(SNAPSHOT_KEY)) if isinstance(context, dict) else {}
    if not delta:
        return []
    out: list[str] = []
    changes = delta.get("changes")
    if isinstance(changes, list):
        since = delta.get("since")
        head = f"CHANGED SINCE LAST TURN (T{since}): " if since is not None else "CHANGED SINCE LAST TURN: "
        if changes:
            out.append(head + "; ".join(changes) + ". Where your earlier notes disagree, these facts win.")
        else:
            out.append(head + "no city, unit, contact or war changed. Write only what is new this turn.")
    stale = _dct(delta.get("stale"))
    if stale:
        out.append(f"REPEATING: your T{stale.get('turn')} situation was {stale.get('overlap')}% the same words as "
                   "the turn before. Do not rewrite it; say what is different this turn and what you will "
                   "do differently.")
    reversing = _lst(delta.get("reversing"))
    if reversing:
        out.append("REVERSING: " + "; ".join(reversing[:LIST_CAP]) + ". Each turned back on its own path. "
                   "Keep one direction per your thought.plan unless something changed, and say what.")
    said = _dct(delta.get("said_vs_did"))
    if said.get("notes"):
        out.append(f"SAID vs DID (T{said.get('turn')}): " + "; ".join(said["notes"])
                   + ". Send the order this turn or drop it from the plan.")
    return out
