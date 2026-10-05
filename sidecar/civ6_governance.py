"""Civ6Ai government & culture: prompt section, reply keys and legal commands.

The mod writes civ6.governance (Civ6Ai_Snapshot._BuildGovernance): government,
policy slots, civics, religion, governors, great people and great works, read
from the same engine calls as the game's screens. This module

- renders the "GOVERNMENT & CULTURE" prompt section and its ATTENTION items,
- turns the model's reply keys (government, policies, pantheon, religion,
  governor.appoint/assign/promote, greatperson.recruit/patronize) into legal
  commands built on the spot (the choices depend on the reply, e.g. which
  cards go in which slot), which Civ6Ai_Apply / Civ6Ai_Orders then apply.

Anything the reply names that is not on offer becomes an unresolved note
instead of a command, so the model reads a plain reason next turn.
"""
from __future__ import annotations

import re
from typing import Any

REPLY_KEYS = (
    "government", "policies", "pantheon", "religion",
    "governor.appoint", "governor.assign", "governor.promote",
    "greatperson.recruit", "greatperson.patronize",
)
FIXED_ARG_MAX = 128


def _lst(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dct(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


# Sub-blocks the adapter's generic list coercion may wrap in a one-item list
# (e.g. a key named "civics" is treated as a list elsewhere).
_OBJECT_BLOCKS = ("government", "policies", "civics", "techs", "religion", "governors", "great_people", "routes",
                  "great_work_empty_slots")
UNAVAILABLE_COST = 1_000_000_000  # the engine's "cannot patronize" price is INT_MAX


def governance(snapshot: dict) -> dict:
    block = snapshot.get("civ6") if isinstance(snapshot, dict) else None
    gov = _dct(_dct(block).get("governance"))
    if not gov:
        return {}
    fixed = dict(gov)
    for key in _OBJECT_BLOCKS:
        value = fixed.get(key)
        if isinstance(value, list):
            fixed[key] = value[0] if len(value) == 1 and isinstance(value[0], dict) else {}
    return fixed


def supported(snapshot: dict) -> bool:
    return bool(governance(snapshot))


def _short(type_id: Any, prefix: str) -> str:
    text = str(type_id or "")
    return text[len(prefix):] if text.startswith(prefix) else text


def _norm(text: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(text or "").strip().strip('"').strip()).upper()


def _match_id(wanted: Any, ids: list[str], prefixes: tuple[str, ...]) -> str | None:
    """Accept GOVERNMENT_CHIEFDOM, CHIEFDOM or chiefdom for a listed id."""
    token = _norm(wanted)
    if not token:
        return None
    for cand in ids:
        if token == cand.upper():
            return cand
    for prefix in prefixes:
        for cand in ids:
            if cand.upper() == prefix + token:
                return cand
    return None


def _routes(gov: dict) -> dict:
    return _dct(gov.get("routes"))


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _turns(value: Any) -> str | None:
    return f"{value}t" if isinstance(value, (int, float)) and value >= 0 else None


def _research_lines(block: dict, label: str, prefix: str, yield_name: str, boost_name: str) -> list[str]:
    """Current tech/civic and each option with what it unlocks and its boost."""
    if not block:
        return []
    out: list[str] = []
    cur = _short(block.get("current"), prefix) or "none"
    bits = []
    t = _turns(block.get("turns_left"))
    if t and block.get("current"):
        bits.append(f"{t} left")
    rate = block.get(f"{yield_name}_per_turn")
    if rate is not None:
        bits.append(f"{yield_name} {rate}/turn")
    line = f"{label} in progress: {cur}" + (f" ({', '.join(bits)})" if bits else "")
    if block.get("current"):
        if block.get("current_unlocks"):
            line += f" — unlocks {block['current_unlocks']}"
        if block.get("current_boosted"):
            line += f"; {boost_name} earned"
        elif block.get("current_boost"):
            line += f"; {boost_name}: {block['current_boost']}"
    out.append(line)
    opts = [o for o in _lst(block.get("options")) if isinstance(o, dict) and o.get("id") != block.get("current")]
    if opts:
        out.append(f"  {label} options:")
        for o in opts:
            meta = [x for x in (_turns(o.get("turns")),) if x]
            if o.get("boosted"):
                meta.append(f"{boost_name} earned")
            text = f"    {_short(o.get('id'), prefix)}" + (f" ({', '.join(meta)})" if meta else "")
            if o.get("unlocks"):
                text += f" — unlocks {o['unlocks']}"
            elif o.get("unlocks_government"):
                text += " — unlocks governments " + "/".join(
                    _short(x, "GOVERNMENT_") for x in str(o["unlocks_government"]).split("/"))
            if o.get("boost") and not o.get("boosted"):
                text += f"; {boost_name}: {o['boost']}"
            out.append(text)
    return out

def prompt_lines(snapshot: dict) -> list[str]:
    gov = governance(snapshot)
    if not gov:
        return []
    routes = _routes(gov)
    lines: list[str] = []
    g = _dct(gov.get("government"))
    if g:
        cur = _short(g.get("current"), "GOVERNMENT_") or "none yet"
        extra = f" (slots {g['current_slots']})" if g.get("current_slots") else ""
        bonus = f" — bonus: {g['current_bonus']}" if g.get("current_bonus") else ""
        legacy = f"; legacy bonus: {g['current_legacy']}" if g.get("current_legacy") else ""
        lines.append(f"Government: {cur}{extra}{bonus}{legacy}")
        avail = _lst(g.get("available"))
        if avail:
            state = "you may change it this turn" if g.get("change_allowed") else (
                "change not possible this turn — " + str(g.get("change_rule") or "only after a civic completes"))
            lines.append(f"  Other unlocked governments ({state}):")
            for a in avail:
                if not isinstance(a, dict):
                    continue
                anarchy = f", {a['anarchy_turns']} turns of anarchy" if a.get("anarchy_turns") else ""
                bonus = f" — bonus: {a['bonus']}" if a.get("bonus") else ""
                legacy = f"; legacy bonus: {a['legacy']}" if a.get("legacy") else ""
                lines.append(f"    {_short(a.get('id'), 'GOVERNMENT_')} (slots {a.get('slots') or '?'}{anarchy}){bonus}{legacy}")
    p = _dct(gov.get("policies"))
    if p:
        slots = [s for s in _lst(p.get("slots")) if isinstance(s, dict)]
        if slots:
            desc = ", ".join(
                f"{s.get('index')}:{_short(s.get('slot_type'), 'SLOT_')}="
                f"{_short(s.get('policy'), 'POLICY_') if s.get('policy') else 'EMPTY'}" for s in slots)
            lines.append(f"Policy slots: {desc}")
            if not routes.get("policies", True):
                lines.append("  (policy cards for this seat are chosen by the game's own AI; no command can set them here)")
            elif p.get("change_allowed"):
                lines.append("  You may change cards this turn.")
            else:
                lines.append("  Cards can't be changed this turn — " + str(p.get("change_rule") or "only after a civic completes"))
        cards = [c for c in _lst(p.get("available")) if isinstance(c, dict)]
        if cards:
            lines.append("  Unlocked policy cards (type — effect):")
            for c in cards:
                mark = " [slotted]" if c.get("active") else ""
                eff = f" — {c['effect']}" if c.get("effect") else ""
                lines.append(f"    {_short(c.get('id'), 'POLICY_')} ({_short(c.get('slot_type'), 'SLOT_')}){mark}{eff}")
    lines.extend(_research_lines(_dct(gov.get("techs")), "Tech", "TECH_", "science", "eureka"))
    lines.extend(_research_lines(_dct(gov.get("civics")), "Civic", "CIVIC_", "culture", "inspiration"))
    r = _dct(gov.get("religion"))
    if r:
        pan = _short(r.get("pantheon"), "BELIEF_") or "none"
        rel = _short(r.get("religion"), "RELIGION_") or "none"
        lines.append(f"Faith: {r.get('faith', 0)} (+{r.get('faith_per_turn', 0)}/turn); pantheon: {pan}; "
                     f"religion founded: {rel}")
        if not r.get("pantheon"):
            cost = r.get("pantheon_cost")
            state = "you can found one now" if r.get("can_found_pantheon") else f"needs {cost} faith"
            lines.append(f"  Pantheon: {state}.")
            beliefs = [b for b in _lst(r.get("pantheon_beliefs")) if isinstance(b, dict)]
            if beliefs:
                lines.append("  Pantheon beliefs still free: " + "; ".join(
                    _short(b.get("id"), "BELIEF_") + (f" — {b['effect']}" if b.get("effect") else "") for b in beliefs))
        prophets = [x for x in _lst(r.get("prophets")) if isinstance(x, dict)]
        if prophets and not r.get("religion"):
            where = ", ".join(f"{x.get('unit_id')} at ({x.get('x')},{x.get('y')})"
                              + (" on your Holy Site" if x.get("on_holy_site") else " (move it onto your Holy Site)")
                              for x in prophets)
            lines.append(f"  Great Prophet: {where}. Found a religion with the prophet on your own Holy Site district.")
            opts = [str(x) for x in _lst(r.get("religion_options"))]
            if opts:
                lines.append("  Religions still free: " + ", ".join(_short(x, "RELIGION_") for x in opts[:12]))
            for label, key in (
                ("Founder beliefs", "founder_beliefs"),
                ("Follower beliefs", "follower_beliefs"),
                ("Worship beliefs", "worship_beliefs"),
                ("Enhancer beliefs", "enhancer_beliefs"),
            ):
                bl = [b for b in _lst(r.get(key)) if isinstance(b, dict)]
                if bl:
                    lines.append(f"  {label}: " + "; ".join(
                        _short(b.get("id"), "BELIEF_") + (f" — {b['effect']}" if b.get("effect") else "") for b in bl[:14]))
        units = _dct(r.get("religious_units"))
        if units:
            lines.append("  Religious units (moved by the game's AI when you give no order): "
                         + ", ".join(f"{_short(k, 'UNIT_')} x{v}" for k, v in units.items()))
    gv = _dct(gov.get("governors"))
    if gv.get("supported"):
        lines.append(f"Governors: {gv.get('points', 0)} title(s) earned, {gv.get('spent', 0)} spent"
                     + ("; you can appoint a new governor" if gv.get("can_appoint") else ""))
        if not routes.get("governors", True):
            lines.append("  (governors for this seat are managed by the game's own AI; no command can set them here)")
        for a in _lst(gv.get("appointed")):
            if not isinstance(a, dict):
                continue
            where = a.get("city") or "unassigned"
            state = ("established" if a.get("established") else
                     (f"establishing, {a['turns_to_establish']} turns" if a.get("turns_to_establish") else "not established")) \
                if a.get("city") else ""
            earned = [e for e in _lst(a.get("promotion_effects")) if isinstance(e, dict)]
            if earned:
                promos = "; earned promotions: " + "; ".join(
                    _short(e.get("id"), "GOVERNOR_PROMOTION_") + (f" = {e['effect']}" if e.get("effect") else "")
                    for e in earned)
            else:
                promos = f"; promotions {a['promotions']}" if a.get("promotions") else ""
            nxt = [o for o in _lst(a.get("promotion_options")) if isinstance(o, dict)]
            can = ""
            if nxt:
                can = ("; can promote to " if a.get("can_promote") else "; next promotions ") + "; ".join(
                    _short(o.get("id"), "GOVERNOR_PROMOTION_") + (f" — {o['effect']}" if o.get("effect") else "") for o in nxt)
            base = f" [{a['title']}]" if a.get("title") else ""
            lines.append(f"  {_short(a.get('id'), 'GOVERNOR_')}{base}: {where}" + (f" ({state})" if state else "") + promos + can)
        cands = [x for x in _lst(gv.get("candidates")) if isinstance(x, dict)]
        if cands and gv.get("can_appoint"):
            lines.append("  Can appoint: " + "; ".join(
                _short(x.get("id"), "GOVERNOR_") + (f" ({x['title']})" if x.get("title") else "")
                + (f" — {x['effect']}" if x.get("effect") else "") for x in cands))
    gp = _dct(gov.get("great_people"))
    if gp:
        pts = [x for x in _lst(gp.get("points")) if isinstance(x, dict)]
        if pts:
            lines.append("Great person points: " + ", ".join(
                f"{_short(x.get('class'), 'GREAT_PERSON_CLASS_')} {x.get('points')} (+{x.get('per_turn')}/turn)" for x in pts))
        avail = [x for x in _lst(gp.get("available")) if isinstance(x, dict)]
        if avail:
            lines.append("  Great people available now (first civ to reach the cost gets them):")
            for x in avail:
                opts = []
                if x.get("can_recruit"):
                    opts.append("YOU CAN RECRUIT")
                if x.get("gold_cost") and x["gold_cost"] < UNAVAILABLE_COST:
                    opts.append(f"patronize {x['gold_cost']} gold" + (" (affordable)" if x.get("can_patronize_gold") else ""))
                if x.get("faith_cost") and x["faith_cost"] < UNAVAILABLE_COST:
                    opts.append(f"patronize {x['faith_cost']} faith" + (" (affordable)" if x.get("can_patronize_faith") else ""))
                eff = f" — {x['effect']}" if x.get("effect") else ""
                lines.append(f"    {_short(x.get('id'), 'GREAT_PERSON_INDIVIDUAL_')} "
                             f"({_short(x.get('class'), 'GREAT_PERSON_CLASS_')}, cost {x.get('cost')} points"
                             + (f"; {', '.join(opts)}" if opts else "") + f"){eff}")
    if gov.get("favor") is not None:
        rate = f" (+{gov['favor_per_turn']}/turn)" if gov.get("favor_per_turn") is not None else ""
        lines.append(f"Diplomatic favor: {gov['favor']}{rate}")
    works = [w for w in _lst(gov.get("great_works")) if isinstance(w, dict)]
    empty = _dct(gov.get("great_work_empty_slots"))
    if works or empty:
        held = ", ".join(f"{_short(w.get('work'), 'GREATWORK_')} in {w.get('city')}" for w in works) or "none"
        free = ", ".join(f"{_short(k, 'GREATWORKSLOT_')} x{v}" for k, v in empty.items()) or "none"
        lines.append(f"Great works held: {held}; empty great work slots: {free} (the game places new works itself)")
    if not lines:
        return []
    lines.append("Commands (optional keys, see OPTIONAL COMMANDS): "
                 '"government": "CHIEFDOM" | "policies": complete set of cards, e.g. "GOD_KING, DISCIPLINE" '
                 '(or "0=GOD_KING; 1=NONE"; cards go to slots of their type, then wildcard slots; cards left out are removed) | '
                 '"pantheon": "BELIEF_ID" | "religion": "RELIGION_ID: FOUNDER_BELIEF, FOLLOWER_BELIEF" | '
                 '"governor.appoint": "GOVERNOR_ID" | "governor.assign": "GOVERNOR_ID @ CityName" | '
                 '"governor.promote": "GOVERNOR_ID: PROMOTION_ID" | "greatperson.recruit": "INDIVIDUAL_ID" | '
                 '"greatperson.patronize": "INDIVIDUAL_ID: gold|faith". '
                 "If you leave these out the game's own AI makes these choices for you.")
    return lines


def attention_items(snapshot: dict) -> list[str]:
    gov = governance(snapshot)
    if not gov:
        return []
    out: list[str] = []
    routes = _routes(gov)
    p = _dct(gov.get("policies"))
    if routes.get("policies", True) and p.get("empty_slots") and p.get("change_allowed") and _lst(p.get("available")):
        out.append(f"{p['empty_slots']} empty policy slot(s): fill them with the \"policies\" key.")
    g = _dct(gov.get("government"))
    if g.get("change_allowed") and _lst(g.get("available")):
        out.append("A new government is unlocked and can be adopted this turn (\"government\" key).")
    r = _dct(gov.get("religion"))
    if r.get("can_found_pantheon") and not r.get("pantheon"):
        out.append("You have enough faith for a pantheon: pick a belief with the \"pantheon\" key.")
    if not r.get("religion") and any(isinstance(x, dict) and x.get("on_holy_site") for x in _lst(r.get("prophets"))):
        out.append("Your Great Prophet is on a Holy Site: found a religion with the \"religion\" key.")
    gv = _dct(gov.get("governors"))
    if routes.get("governors", True) and gv.get("can_appoint"):
        out.append("A governor title is available: appoint a governor (\"governor.appoint\").")
    gp = _dct(gov.get("great_people"))
    ready = [_short(x.get("id"), "GREAT_PERSON_INDIVIDUAL_") for x in _lst(gp.get("available"))
             if isinstance(x, dict) and x.get("can_recruit")]
    if ready:
        out.append("You can recruit great person " + ", ".join(ready) + " (\"greatperson.recruit\").")
    return out


def optional_key_hints(snapshot: dict) -> list[tuple[str, str]]:
    gov = governance(snapshot)
    if not gov:
        return []
    routes = _routes(gov)
    out: list[tuple[str, str]] = []
    g = _dct(gov.get("government"))
    avail = [_short(a.get("id"), "GOVERNMENT_") for a in _lst(g.get("available")) if isinstance(a, dict)]
    if avail and g.get("change_allowed"):
        out.append(("government", " | ".join(avail)))
    p = _dct(gov.get("policies"))
    if routes.get("policies", True) and p.get("change_allowed") and _lst(p.get("available")):
        out.append(("policies", "CARD, CARD, ... (complete set; see GOVERNMENT & CULTURE)"))
    r = _dct(gov.get("religion"))
    if r.get("can_found_pantheon") and not r.get("pantheon"):
        beliefs = [_short(b.get("id"), "BELIEF_") for b in _lst(r.get("pantheon_beliefs")) if isinstance(b, dict)]
        out.append(("pantheon", " | ".join(beliefs[:12]) or "BELIEF_ID"))
    if not r.get("religion") and _lst(r.get("prophets")) and _lst(r.get("religion_options")):
        out.append(("religion", "RELIGION_ID: FOUNDER_BELIEF, FOLLOWER_BELIEF"))
    gv = _dct(gov.get("governors"))
    if gv.get("supported") and routes.get("governors", True):
        if gv.get("can_appoint"):
            out.append(("governor.appoint", " | ".join(
                _short(x.get("id"), "GOVERNOR_") for x in _lst(gv.get("candidates")) if isinstance(x, dict))))
        if _lst(gv.get("appointed")):
            out.append(("governor.assign", "GOVERNOR_ID @ CityName"))
            if any(isinstance(a, dict) and a.get("can_promote") for a in _lst(gv.get("appointed"))):
                out.append(("governor.promote", "GOVERNOR_ID: PROMOTION_ID"))
    gp = _dct(gov.get("great_people"))
    avail_gp = [x for x in _lst(gp.get("available")) if isinstance(x, dict)]
    rec = [_short(x.get("id"), "GREAT_PERSON_INDIVIDUAL_") for x in avail_gp if x.get("can_recruit")]
    if rec:
        out.append(("greatperson.recruit", " | ".join(rec)))
    pat = [_short(x.get("id"), "GREAT_PERSON_INDIVIDUAL_") for x in avail_gp
           if x.get("can_patronize_gold") or x.get("can_patronize_faith")]
    if pat:
        out.append(("greatperson.patronize", " | ".join(p_ + ": gold|faith" for p_ in pat[:6])))
    return out


# ---------------------------------------------------------------------------
# Reply -> legal commands
# ---------------------------------------------------------------------------
def is_reply_key(key: str) -> bool:
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    low = low.replace("great_person", "greatperson").replace("greatpeople", "greatperson")
    return low in REPLY_KEYS or low in ("governors.appoint", "governors.assign", "governors.promote")


def _canon_key(key: str) -> str:
    low = key.lower()
    if low.startswith("legal."):
        low = low[len("legal."):]
    return low.replace("great_person", "greatperson").replace("greatpeople", "greatperson").replace("governors.", "governor.")


def _add_command(snapshot: dict, kind: str, fixed: dict, description: str) -> str:
    from sidecar.civ6_adapter import _enrich_runtime_legal_command

    legal = snapshot.setdefault("legal_commands", [])
    base = "CMD_GOV_" + kind.upper()
    have = {c.get("command_id") for c in legal if isinstance(c, dict)}
    n = 1
    while f"{base}_{n}" in have:
        n += 1
    cid = f"{base}_{n}"
    legal.append(_enrich_runtime_legal_command({
        "command_id": cid, "kind": kind, "description": description[:240], "fixed_arguments": fixed,
    }))
    return cid


def _split_pair(value: Any, seps: str = ":@=") -> tuple[str, str]:
    text = str(value or "").strip()
    for sep in seps:
        if sep in text:
            a, _, b = text.partition(sep)
            return a.strip(), b.strip()
    return text, ""


def plan_policies(slots: list[dict], cards: list[dict], value: Any) -> tuple[dict[int, str] | None, list[str]]:
    """Wanted slot -> card ('NONE' empties) from the reply; only changed slots are kept."""
    problems: list[str] = []
    card_ids = [str(c.get("id")) for c in cards if c.get("id")]
    card_type = {str(c.get("id")): str(c.get("slot_type") or "") for c in cards}
    current = {int(s.get("index")): (s.get("policy") or "NONE") for s in slots if s.get("index") is not None}
    slot_type = {int(s.get("index")): str(s.get("slot_type") or "") for s in slots if s.get("index") is not None}
    if isinstance(value, list):
        text = ", ".join(str(v) for v in value)
    elif isinstance(value, dict):
        text = "; ".join(f"{k}={v}" for k, v in value.items())
    else:
        text = str(value or "").strip()
    if not text or text.lower() in ("keep", "same", "unchanged", "no change"):
        return None, problems
    wanted: dict[int, str] = {}
    entries = [e.strip() for e in re.split(r"[;,+]", text) if e.strip()]
    if any("=" in e for e in entries):
        for e in entries:
            left, _, right = e.partition("=")
            try:
                idx = int(left.strip())
            except ValueError:
                problems.append(f"bad policy slot entry '{e}'")
                continue
            if idx not in slot_type:
                problems.append(f"there is no policy slot {idx}")
                continue
            if _norm(right) in ("NONE", "EMPTY", ""):
                wanted[idx] = "NONE"
                continue
            cid = _match_id(right, card_ids, ("POLICY_",))
            if cid is None:
                problems.append(f"policy card {right} is not unlocked")
                continue
            wanted[idx] = cid
    else:
        chosen: list[str] = []
        if not (len(entries) == 1 and _norm(entries[0]) in ("NONE", "EMPTY", "CLEAR")):
            for e in entries:
                cid = _match_id(e, card_ids, ("POLICY_",))
                if cid is None:
                    problems.append(f"policy card {e} is not unlocked")
                elif cid not in chosen:
                    chosen.append(cid)
        free = dict.fromkeys(slot_type, None)
        # Keep cards already in a fitting slot where they are.
        for idx, cur in current.items():
            if cur in chosen and cur not in free.values():
                free[idx] = cur
        for cid in chosen:
            if cid in free.values():
                continue
            ctype = card_type.get(cid, "")
            spot = next((i for i in sorted(free) if free[i] is None and slot_type[i] == ctype), None)
            if spot is None:
                spot = next((i for i in sorted(free) if free[i] is None and slot_type[i] == "SLOT_WILDCARD"), None)
            if spot is None:
                problems.append(f"no free {_short(ctype, 'SLOT_').lower()} or wildcard slot for {cid}")
                continue
            free[spot] = cid
        for idx in slot_type:
            wanted[idx] = free[idx] or "NONE"
    changed = {i: c for i, c in wanted.items() if current.get(i, "NONE") != c}
    return changed, problems


def _policy_arg(plan: dict[int, str]) -> list[str]:
    """'0=GOD_KING;1=NONE' strings no longer than FIXED_ARG_MAX (split if needed)."""
    parts = [f"{i}={_short(c, 'POLICY_')}" for i, c in sorted(plan.items())]
    out: list[str] = []
    cur = ""
    for part in parts:
        nxt = part if not cur else cur + ";" + part
        if len(nxt) > FIXED_ARG_MAX and cur:
            out.append(cur)
            cur = part
        else:
            cur = nxt
    if cur:
        out.append(cur)
    return out


def bind_reply(snapshot: dict, key: str, value: Any) -> tuple[list[str], list[str]]:
    """Legal command ids created for one reply key, plus unresolved notes."""
    gov = governance(snapshot)
    ckey = _canon_key(key)
    if not gov:
        return [], [f"{key}: government/culture commands are not available for this seat"]
    if value is None or str(value).strip().lower() in ("", "none", "keep", "no change", "skip"):
        if ckey != "policies":
            return [], []
    routes = _routes(gov)
    ids: list[str] = []
    notes: list[str] = []
    if ckey == "government":
        g = _dct(gov.get("government"))
        avail = [str(a.get("id")) for a in _lst(g.get("available")) if isinstance(a, dict)]
        gid = _match_id(value, avail, ("GOVERNMENT_",))
        if gid is None:
            notes.append(f"{key}={value}: not an unlocked government")
        else:
            ids.append(_add_command(snapshot, "change_government", {"government_id": gid}, f"change government to {gid}"))
    elif ckey == "policies":
        p = _dct(gov.get("policies"))
        if not routes.get("policies", True):
            notes.append(f"{key}: policy cards for this seat are chosen by the game's own AI")
        else:
            slots = [s for s in _lst(p.get("slots")) if isinstance(s, dict)]
            cards = [c for c in _lst(p.get("available")) if isinstance(c, dict)]
            plan, problems = plan_policies(slots, cards, value)
            notes.extend(f"{key}: {x}" for x in problems)
            for arg in _policy_arg(plan or {}):
                ids.append(_add_command(snapshot, "set_policies", {"slots": arg}, f"policy cards {arg}"))
    elif ckey == "pantheon":
        r = _dct(gov.get("religion"))
        beliefs = [str(b.get("id")) for b in _lst(r.get("pantheon_beliefs")) if isinstance(b, dict)]
        bid = _match_id(value, beliefs, ("BELIEF_",))
        if bid is None:
            notes.append(f"{key}={value}: not a free pantheon belief")
        else:
            ids.append(_add_command(snapshot, "found_pantheon", {"belief_id": bid}, f"found pantheon {bid}"))
    elif ckey == "religion":
        r = _dct(gov.get("religion"))
        rel_text, beliefs_text = _split_pair(value, ":(")
        beliefs_text = beliefs_text.rstrip(")")
        rid = _match_id(rel_text, [str(x) for x in _lst(r.get("religion_options"))], ("RELIGION_",))
        pool = [str(b.get("id")) for key2 in (
            "founder_beliefs", "follower_beliefs", "worship_beliefs", "enhancer_beliefs")
                for b in _lst(r.get(key2)) if isinstance(b, dict)]
        chosen = []
        for part in re.split(r"[,;+/]", beliefs_text):
            if part.strip():
                bid = _match_id(part, pool, ("BELIEF_",))
                if bid is None:
                    notes.append(f"{key}: belief {part.strip()} is not free")
                else:
                    chosen.append(bid)
        prophets = [x for x in _lst(r.get("prophets")) if isinstance(x, dict)]
        prophet = next((x for x in prophets if x.get("on_holy_site")), prophets[0] if prophets else None)
        if rid is None:
            notes.append(f"{key}={value}: not a religion you can found now")
        elif prophet is None:
            notes.append(f"{key}: you need a Great Prophet to found a religion")
        else:
            fixed = {"religion_id": rid, "belief_ids": ",".join(chosen[:4]), "unit_id": str(prophet.get("unit_id"))}
            if not fixed["belief_ids"]:
                fixed.pop("belief_ids")
            ids.append(_add_command(snapshot, "found_religion", fixed, f"found religion {rid}"))
    elif ckey.startswith("governor."):
        gv = _dct(gov.get("governors"))
        if not gv.get("supported"):
            notes.append(f"{key}: this game has no governors")
            return ids, notes
        if not routes.get("governors", True):
            notes.append(f"{key}: governors for this seat are managed by the game's own AI")
            return ids, notes
        appointed = [a for a in _lst(gv.get("appointed")) if isinstance(a, dict)]
        app_ids = [str(a.get("id")) for a in appointed]
        action = ckey.split(".", 1)[1]
        if action == "appoint":
            cands = [str(x.get("id")) for x in _lst(gv.get("candidates")) if isinstance(x, dict)]
            gid = _match_id(value, cands, ("GOVERNOR_", "GOVERNOR_THE_"))
            if gid is None:
                notes.append(f"{key}={value}: not a governor you can appoint")
            else:
                ids.append(_add_command(snapshot, "appoint_governor", {"governor_id": gid}, f"appoint {gid}"))
        elif action == "assign":
            gname, city_text = _split_pair(value, "@:=")
            gid = _match_id(gname, app_ids, ("GOVERNOR_", "GOVERNOR_THE_"))
            city_id = None
            for city in _lst(gv.get("cities")):
                if isinstance(city, dict) and (_norm(city.get("name")) == _norm(city_text)
                                               or str(city.get("city_id")) == city_text.strip()):
                    city_id = str(city.get("city_id"))
            if gid is None:
                notes.append(f"{key}={value}: governor not appointed")
            elif city_id is None:
                notes.append(f"{key}={value}: city {city_text} is not yours")
            else:
                ids.append(_add_command(snapshot, "assign_governor", {"governor_id": gid, "city_id": city_id},
                                        f"assign {gid} to {city_text}"))
        elif action == "promote":
            gname, promo_text = _split_pair(value, ":@=")
            gid = _match_id(gname, app_ids, ("GOVERNOR_", "GOVERNOR_THE_"))
            entry = next((a for a in appointed if a.get("id") == gid), None)
            promos = [str(o.get("id")) for o in _lst((entry or {}).get("promotion_options")) if isinstance(o, dict)]
            pid = _match_id(promo_text, promos, ("GOVERNOR_PROMOTION_",))
            if gid is None:
                notes.append(f"{key}={value}: governor not appointed")
            elif pid is None:
                notes.append(f"{key}={value}: not an open promotion for {gid}")
            else:
                ids.append(_add_command(snapshot, "promote_governor", {"governor_id": gid, "promotion_id": pid},
                                        f"promote {gid} with {pid}"))
    elif ckey.startswith("greatperson."):
        gp = _dct(gov.get("great_people"))
        avail = [str(x.get("id")) for x in _lst(gp.get("available")) if isinstance(x, dict)]
        action = ckey.split(".", 1)[1]
        name, yield_text = _split_pair(value, ":@=")
        iid = _match_id(name, avail, ("GREAT_PERSON_INDIVIDUAL_",))
        if iid is None:
            notes.append(f"{key}={value}: not an available great person")
        elif action == "recruit":
            ids.append(_add_command(snapshot, "recruit_great_person", {"individual_id": iid}, f"recruit {iid}"))
        else:
            y = "faith" if "faith" in yield_text.lower() else "gold"
            ids.append(_add_command(snapshot, "patronize_great_person", {"individual_id": iid, "yield": y},
                                    f"patronize {iid} with {y}"))
    return ids, notes


def success_text(kind: str, fixed: dict) -> str | None:
    if kind == "change_government":
        return f"ok — government is now {_short(fixed.get('government_id'), 'GOVERNMENT_')}"
    if kind == "set_policies":
        return f"ok — policy cards set ({fixed.get('slots')})"
    if kind == "found_pantheon":
        return f"ok — pantheon founded: {_short(fixed.get('belief_id'), 'BELIEF_')}"
    if kind == "found_religion":
        return f"ok — religion founded: {_short(fixed.get('religion_id'), 'RELIGION_')}"
    if kind == "recruit_great_person":
        return f"ok — recruited {_short(fixed.get('individual_id'), 'GREAT_PERSON_INDIVIDUAL_')}"
    if kind == "patronize_great_person":
        return f"ok — patronized {_short(fixed.get('individual_id'), 'GREAT_PERSON_INDIVIDUAL_')}"
    if kind == "appoint_governor":
        return f"ok — appointed {_short(fixed.get('governor_id'), 'GOVERNOR_')}"
    if kind == "assign_governor":
        return f"ok — {_short(fixed.get('governor_id'), 'GOVERNOR_')} assigned to {fixed.get('city_id')}"
    if kind == "promote_governor":
        return f"ok — {_short(fixed.get('governor_id'), 'GOVERNOR_')} promoted ({fixed.get('promotion_id')})"
    return None


ORDER_LABELS = {
    "change_government": ("government", "government_id"),
    "set_policies": ("policies", "slots"),
    "found_pantheon": ("pantheon", "belief_id"),
    "found_religion": ("religion", "religion_id"),
    "recruit_great_person": ("greatperson.recruit", "individual_id"),
    "patronize_great_person": ("greatperson.patronize", "individual_id"),
    "appoint_governor": ("governor.appoint", "governor_id"),
    "assign_governor": ("governor.assign", "governor_id"),
    "promote_governor": ("governor.promote", "governor_id"),
}
