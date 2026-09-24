# Civ VI Command Catalog & Prompt Spec (TDD)

Authoritative TDD target for Civ6Ai before mod implementation. Derived from local clone of [civ6-mcp](https://github.com/lmwilki/civ6-mcp) at `artifacts/reference/civ6-mcp` and Civ IV [`sidecar/pipeline_v2.py`](sidecar/pipeline_v2.py).

## Reference install

```text
artifacts/reference/civ6-mcp/   # git clone of lmwilki/civ6-mcp (read-only reference)
config/civ6-command-capabilities.json
fixtures/civ6/prompt-turn-classical-golden.txt
fixtures/civ6/response-turn-classical-golden.txt
```

civ6-mcp is **not** the production runtime path (Workshop Lua + `pipeline_v2` sidecar). It is the proven Lua apply catalog.

## MCP tool inventory (local clone)

### Read-only snapshot sources (not LLM commands)

| MCP tool | Snapshot use |
|----------|----------------|
| `get_game_overview` | `game`, `your_empire` core yields |
| `get_units` | `your_units` |
| `get_spies` | spy units |
| `get_cities` | `your_cities` |
| `get_city_production` | production options per city |
| `get_map_area` | local map text / fog |
| `get_settle_advisor` | expansion hints |
| `get_pathing_estimate` | pathing hints |
| `get_global_settle_advisor` | settle sites |
| `get_builder_tasks` | builder priorities |
| `get_empire_resources` | resources |
| `get_strategic_map` | strategic text map |
| `get_diplomacy` | `diplomacy`, rivals |
| `get_tech_civics` | research/civic lists |
| `get_pending_trades` | pending deals |
| `get_policies` | policy slots |
| `get_notifications` | alerts |
| `get_pending_diplomacy` | diplomacy sessions |
| `get_governors` | governors |
| `get_unit_promotions` | promotion options |
| `get_city_states` | city-states |
| `get_pantheon_beliefs` | pantheon choices |
| `get_religion_beliefs` | religion founding UI |
| `get_dedications` | era dedications |
| `get_trade_options` | trade inventory |
| `get_trade_routes` | trade routes |
| `get_trade_destinations` | trader destinations |
| `get_district_advisor` | district placement |
| `get_wonder_advisor` | wonder placement |
| `get_purchasable_tiles` | tile purchase list |
| `get_great_people` | GP pool |
| `get_gp_advisor` | GP activation sites |
| `get_world_congress` | WC session |
| `get_victory_progress` | victory race |
| `get_religion_spread` | religion map |
| `get_diary` | civ6-mcp diary only |

### Actionable MCP tools → `legal_commands` kinds

| MCP tool | Maps to kind(s) |
|----------|-----------------|
| `set_research` | `set_research_tech`, `set_research_civic` |
| `set_city_production` | `queue_production` |
| `purchase_item` | `purchase_item` |
| `purchase_tile` | `purchase_tile` |
| `set_city_focus` | `set_city_focus` |
| `unit_action` | 20 unit kinds (see below) |
| `upgrade_unit` | `upgrade_unit` |
| `promote_unit` | `promote_unit` |
| `city_action` | `city_attack`, `resolve_city_capture` |
| `spy_action` | `spy_travel`, `spy_mission` |
| `appoint_governor` / `assign_governor` / `promote_governor` | governor kinds |
| `choose_pantheon` / `found_religion` | religion empire kinds |
| `choose_dedication` | `choose_dedication` |
| `set_policies` / `change_government` | governance |
| `send_envoy` | `send_envoy` |
| `send_diplomatic_action` / `form_alliance` / `propose_trade` / `propose_peace` / `respond_to_*` | diplomacy |
| `recruit_great_person` / `patronize_great_person` / `reject_great_person` | GP pool |
| `queue_wc_votes` | `queue_wc_votes` |

### `unit_action` sub-actions (civ6-mcp `server.py`)

`move`, `attack`, `fortify`, `skip`, `found_city`, `improve`, `repair`, `remove_improvement`, `remove_feature`, `build_route`, `automate`, `heal`, `alert`, `sleep`, `delete`, `trade_route`, `activate`, `sacrifice_charges`, `teleport`, `spread_religion`

### Host-only (not advertised to LLM)

`end_turn`, `spy_escape_route` (auto on blocker), `dismiss_popup`. **`skip_remaining_units` only after native AI** — not before.

---

## Hybrid control model (default)

Not full unit micro. Matches Civ IV AdvCiv split ([`docs/civ6-llm-ai-research.md`](civ6-llm-ai-research.md) §5.6).

| Domain | Default | LLM override | Opt-out |
|--------|---------|--------------|---------|
| Units | Firaxis native AI moves unmoved units after LLM apply | `moveTo`, `attackTo`, worker ops, etc. | `stance=fortify`, `sleep`, or `alert` |
| Production | Auto/deterministic pick when LLM doesn't override | `{City}.changeProduction` | Omit — city keeps queue or gets auto-pick |

**Apply order:** LLM commands → native AI unit phase → deterministic production for cities still empty → host ends turn.

**Prompt hints:**

```text
units.nativeControl = Firaxis AI moves unmoved units after your commands; use fortify/sleep/alert to hold a unit.
cities.nativeProduction = Cities keep auto production unless you set changeProduction.
```

**`legal_commands` advertising:** Prefer strategic + blocker kinds every turn; unit `moveTo`/`attackTo` only when tactically relevant (or cap K targets per unit) — not every legal tile every turn.

---

## Command catalog (generated from local civ6-mcp)

Regenerate after upstream tool changes:

```powershell
python scripts/testbed/generate_civ6_capabilities.py
```

Current inventory (local clone): **76** MCP tools → **58** capability kinds (**34** v1, remainder v1.1 / host / deferred).

Full JSON: [`config/civ6-command-capabilities.json`](config/civ6-command-capabilities.json)

### Empire

| kind | Wire |
|------|------|
| `set_research_tech` | `legal.research.tech = TECH_*` |
| `set_research_civic` | `legal.research.civic = CIVIC_*` |
| `set_policies` | `legal.policies = 0=POLICY_*,1=...` |
| `change_government` | `legal.government = GOVERNMENT_*` |
| `choose_dedication` | `legal.dedication = {index}` |
| `choose_pantheon` | `legal.pantheon = BELIEF_*` |
| `found_religion` | `legal.religion = ...` (v1.1) |
| `appoint_governor` | `legal.governor.appoint = GOVERNOR_*` |
| `assign_governor` | `legal.governor.assign = GOVERNOR_*@City` |
| `promote_governor` | `legal.governor.promote = GOVERNOR_*:PROMOTION_*` |
| `send_envoy` | `legal.envoy = PLAYER_*` |
| `recruit_great_person` | `legal.gp.recruit = {id}` |
| `patronize_great_person` | `legal.gp.patronize = {id}` |
| `reject_great_person` | `legal.gp.reject = {id}` |
| `queue_wc_votes` | `legal.wc.votes = [{hash,option,target,votes}]` |
| `send_diplomatic_action` | `legal.diplomacy.{Leader} = ACTION` |
| `form_alliance` | `legal.alliance.{Leader} = TYPE` |
| `propose_trade` | `legal.trade.offer.{Leader} = offer:gold=100;request:gpt=3` |
| `propose_peace` | `legal.peace.{Leader} = apply` |
| `respond_to_diplomacy` | `legal.diplomacy.respond.{Leader} = POSITIVE\|NEGATIVE` |
| `respond_to_trade` | `legal.trade.respond.{Leader} = accept\|reject` |
| `resolve_city_capture` | `legal.capture = keep\|reject\|raze\|liberate_founder\|liberate_previous` |

### City

| kind | Wire |
|------|------|
| `queue_production` | `{City}.changeProduction = UNIT_* \| BUILDING_* \| DISTRICT_*@(x,y) \| PROJECT_*@(x,y)` |
| `purchase_item` | `{City}.purchase = UNIT_* \| BUILDING_*` (optional `:faith`) |
| `purchase_tile` | `{City}.buyTile = (x,y)` |
| `set_city_focus` | `{City}.changeFocus = food\|production\|gold\|science\|culture\|faith\|default` |
| `city_attack` | `{City}.attack = (x,y)` |

### Unit

| kind | Wire |
|------|------|
| `move_unit` | `{unit}.moveTo = (x,y)` |
| `attack_target` | `{unit}.attackTo = (x,y)` |
| `swap_units` | `{unit}.swapTo = (x,y)` |
| `unit_posture_*` | `{unit}.stance = fortify\|heal\|alert\|sleep\|skip` |
| `automate_explore` | `{unit}.automate = explore` |
| `upgrade_unit` | `{unit}.upgrade = apply` |
| `promote_unit` | `{unit}.promote = PROMOTION_*` |
| `delete_unit` | `{unit}.delete = apply` |
| `found_city` | `{unit}.foundCity = apply` |
| `worker_*` | `improve`, `repair`, `removeImprovement`, `removeFeature`, `buildRoute` |
| `sacrifice_charges` | `{unit}.sacrificeCharges = apply` |
| `trade_route` | `{unit}.tradeRoute = (x,y)` |
| `teleport_trader` | `{unit}.teleport = (x,y)` |
| `activate_great_person` | `{unit}.activate = apply` |
| `spread_religion` | `{unit}.spreadReligion = apply` |
| `spy_travel` / `spy_mission` | `{spy}.spyAction = travel@(x,y) \| MISSION@(x,y)` |

---

## Prompt structure (flat wire)

Three sections + instructions, matching Civ IV [`build_flat_wire_prompt`](sidecar/pipeline_v2.py):

### `=== CURRENT SITUATION ===`

Civ VI replaces Civ IV commerce sliders with:

```text
empire.science = ...
empire.culture = ...
empire.faith = ...
empire.favor = ...
empire.research.tech = TECH_POTTERY
empire.research.tech.progress = ...
empire.research.civic = CIVIC_CRAFTSMANSHIP
empire.government = GOVERNMENT_CLASSICAL_REPUBLIC
empire.era_score = ...
units.nativeControl = Firaxis AI moves unmoved units after your commands; use fortify/sleep/alert to hold a unit.
cities.nativeProduction = Cities keep auto production unless you set changeProduction.
```

Retain: `thought.tN.situation`, `opinion.*`, `history.*`, per-city/unit lines, rivals, alerts, trade inbox.

### `=== MAP ===`

```text
map.width = 44
map.height = 26
map.hex = odd-r
map.coords = grid x,y; Y increases south
# minimap attached — fog, terrain, units
```

### `=== LEGAL COMMANDS ===`

```text
# Issue as many command lines as you need this turn.
# City: cityName.property = value. Unit: unitId.property = value.
# Unit movement: unitId.moveTo or stack.moveTo = (x,y)
# Districts/wonders: cityName.changeProduction = DISTRICT_CAMPUS@(12,34)
# Empire: legal.research.*, legal.policies, legal.diplomacy.*, legal.trade.*
Athens.changeProduction = UNIT_SETTLER | UNIT_WARRIOR | BUILDING_MONUMENT
scout_1.moveTo = (10,26) | (11,26) | (10,27)
legal.research.tech = TECH_POTTERY
```

### `=== INSTRUCTIONS ===`

See golden fixture [`fixtures/civ6/prompt-turn-classical-golden.txt`](fixtures/civ6/prompt-turn-classical-golden.txt).

Key Civ VI deltas vs Civ IV:

- Role text: **Civilization VI**, not IV
- Hybrid control — native AI for unmoved units; fortify/sleep to opt out; auto production unless overridden
- Compact wire — same thresholds as Civ IV (`WIRE_COMPACT_UNITS_THRESHOLD = 6`, cities = 10); recent chats only; `thought` / `opinion` / `history`
- `chat.all` / `chat.{Leader}` **v1** (sparse; skip most turns)
- Hex note: **Y increases south**

### Model response format

```text
thought.situation = ...
thought.strategy = ...
opinion.Cleopatra = ...        # optional, on change
history.Cleopatra = T12 ...    # optional, major events only
decision_summary = ...
Capital.changeProduction = UNIT_SETTLER
scout_1.moveTo = (10,26)
legal.research.tech = TECH_POTTERY
```

Golden response: [`fixtures/civ6/response-turn-classical-golden.txt`](fixtures/civ6/response-turn-classical-golden.txt)

---

## MCP gap analysis (missing but executable)

Compared local `artifacts/reference/civ6-mcp` (76 tools) to Civ VI Lua surface and Civ IV parity. **civ6-mcp covers the strategic core**; gaps below are candidates for Civ6Ai mod + optional upstream civ6-mcp contributions.

### High priority (strategic / blockers)

| Gap | Decision | Planned kind |
|-----|----------|--------------|
| **Trade counteroffer** | **Out of scope** — keep accept/reject only (simple) | — |
| **Cancel deal / agreement** | **v1 required** | `cancel_deal` |
| **Clear / pop production** | **v1 required** | `clear_production_queue`, `remove_queue_order` |
| **Worship + enhancer beliefs** | **v1 required** | extend `found_religion` or `add_belief` |

### Medium priority — **v1 required** (user confirmed)

| Gap | Planned kind |
|-----|--------------|
| Coastal raid | `coastal_raid` |
| Pillage improvement | `pillage_improvement` |
| Embark / disembark | `embark`, `disembark` |
| Rebase aircraft | `rebase_aircraft` |
| WMD / nuclear strike | `wmd_strike` (risk=high) |
| Swap units | `swap_units` |
| Rock band concert | `rock_band_concert` |
| Archaeologist excavate | `archaeologist_excavate` |
| Naturalist national park | `naturalist_national_park` |
| Seaside resort | `seaside_resort` |

### Low priority / host-auto — **out of scope v1**

| Gap | Notes |
|-----|-------|
| Spy escape route | Host auto in `end_turn` |
| Citizen plot assignment | Auto in Civ VI |
| Builder automate build | Scouts have `automate=explore` only |
| Emergency / random event choice | Add when blocker encountered |
| Harvest vs remove_feature | `remove_feature` covers chop/harvest |

### Already covered (verify only)

- War types → `send_diplomatic_action` casus belli list
- Air attack → `unit_action(attack)` uses `AIR_ATTACK` path
- GP activate / prophet found religion → `activate` + `found_religion`
- WC voting → `queue_wc_votes`
- City capture → `resolve_city_capture` / `city_action`

### civ6-mcp upstream additions (optional)

Civ6Ai mod implements first; optional PRs to reference clone:

1. `cancel_deal`, `clear_city_production` / `pop_production`
2. Extended `found_religion` (worship/enhancer)
3. `unit_action` extensions: coastal_raid, embark, rebase, pillage, culture unit ops

**Explicitly not adding:** `counteroffer_trade` (accept/reject only).

---

## TDD gates

1. `config/civ6-command-capabilities.json` lists every kind with `lua_builder` pointing into `artifacts/reference/civ6-mcp/src/civ_mcp/lua/`
2. Golden prompt/response fixtures parse as flat wire (no JSON braces)
3. `sidecar/tests/test_civ6_wire_prompt.py` validates sections and capability count
4. Live save probe (later): InGame Lua dump vs civ6-mcp reference on same turn

---

## Next implementation steps

1. `sidecar/civ6_wire.py` — property maps + `build_civ6_response_instructions()`
2. Branch in `pipeline_v2.py` or adapter for Civ VI snapshot fields
3. Mod `legal_commands` builder — v1 kinds first
4. Refresh golden fixtures from real Classical-era save
