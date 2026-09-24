# Civ VI map coordinates & location-based commands

**Master doc:** [civ6-llm-ai-research.md §5.3](./civ6-llm-ai-research.md#53-coordinate-system) (consolidated)  
**Parent:** [civ6-research-spikes-01.md](./civ6-research-spikes-01.md)  
**Audience:** Porting `known_map`, `legal_commands`, and `map_render` from Civ IV

---

## TL;DR

| Question | Answer |
|----------|--------|
| What coords does `Map.GetPlot(x, y)` use? | **Grid (plot) coordinates** — same as `plot:GetX()`, `unit:GetX()`. |
| Is it a square grid? | Storage is a **rectangular `width × height` array**, but topology is **hex**. Neighbors are **not** always `(x±1, y±1)`. |
| What do commands use? | **Grid `x`, `y`** in `UnitOperationTypes.PARAM_X / PARAM_Y`, city `PARAM_X/Y`, `purchase_tile(x,y)`, etc. |
| Plot index? | `index = y * Map.GetGridWidth() + x` (see civ6-mcp `map.py`). |
| Hex coords? | Separate system for some **UI events** — convert before `GetPlot` ([forum fix](https://forums.civfanatics.com/threads/adventures-in-border-plots.665278/)). |
| Civ IV difference | Civ IV BTS is a **true square** grid (N/E/S/W rivers); Civ VI is **hex** with 6 directions. |

**Practical rule for the LLM stack:** Treat `(x, y)` everywhere as opaque **grid IDs** returned by the game. For rendering, stagger odd/even rows; for adjacency/pathing, use game APIs — do not assume `dx,dy` neighbors unless you implement offset-hex math.

---

## 1. Three coordinate systems (Firaxis pattern)

Same family as Civ V ([Modiki map terrain](https://modiki.civfanatics.com/index.php/Map_and_terrain_(Civ5))):

| System | Used for | Civ VI access |
|--------|----------|---------------|
| **Grid (plot)** | Logic, saves, Lua commands, `Map.GetPlot` | `plot:GetX()`, `plot:GetY()` |
| **Hex** | Some UI / serial events (culture borders, anchors) | Event args; convert with `ToGridFromHex` |
| **World** | 3D rendering, UI anchors | `GridToWorld` / `HexToWorld` (UI context) |

**Gameplay and civ6-mcp never require hex coords** if you start from `GetX/GetY` or probe with `Map.PlotDirection`.

### Grid vs hex (your “offset every second row” intuition)

Civ uses **offset coordinates** (Red Blob “odd-r” layout): rows are staggered visually, but each tile still has integer `(grid.x, grid.y)` stored in a 2D array.

Community conversion ([CivFanatics](https://forums.civfanatics.com/threads/using-whowards-border-and-plot-iterators-in-civ-6.607334/), [Red Blob Games](https://www.redblobgames.com/grids/hexagons/)):

```lua
-- Grid (plot) → axial-style hex
function ToHexFromGrid(grid)
  return {
    x = grid.x - (grid.y - (grid.y % 2)) / 2,
    y = grid.y
  }
end

-- Hex → grid (required before Map.GetPlot when event gave hex coords)
function ToGridFromHex(hex_x, hex_y)
  local x = hex_x + (hex_y - (hex_y % 2)) / 2
  return x, hex_y
end
```

**Failure mode:** `Events.SerialEventHexCultureChanged` passes **hex** `hexX, hexY`. Calling `Map.GetPlot(hexX, hexY)` without conversion returns the **wrong plot** ([border plots thread](https://forums.civfanatics.com/threads/adventures-in-border-plots.665278/)).

### ASCII: odd-r grid storage vs hex shape

```
Grid indices (x increases →, y increases ↓):

  y=0:  (0,0) (1,0) (2,0) (3,0)     ← row not shifted
  y=1:    (0,1) (1,1) (2,1) (3,1)   ← visually staggered right on map
  y=2:  (0,2) (1,2) (2,2) (3,2)

Each cell has 6 neighbors — neighbor offsets depend on row parity.
Use Map.PlotDirection(x, y, dir) instead of hand-rolled dx,dy.
```

---

## 2. Map storage & indexing

From civ6-mcp [`lua/map.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/map.py):

```lua
local w, h = Map.GetGridSize()   -- width, height in grid coords
local plot = Map.GetPlot(x, y)   -- nil if out of bounds
local idx  = plot:GetIndex()     -- linear index
-- Equivalent: idx = y * w + x  (used in static map dump)
```

| API | Role |
|-----|------|
| `Map.GetPlotCount()` | Total plots |
| `Map.GetPlotByIndex(idx)` | Reverse lookup |
| `Map.GetPlotDistance(x1,y1,x2,y2)` | **Hex distance** (engine-correct) |
| `Map.PlotDirection(x, y, dir)` | Neighbor in `DirectionTypes` |
| `Map.GetUnitsAt(x, y)` | Units on tile (stacking) |
| `PlayersVisibility[me]:IsRevealed(idx)` | Fog / explored |
| `PlayersVisibility[me]:IsVisible(idx)` | Current vision |

**Map size:** Standard maps are ~60×60 to ~106×66 grid cells depending on script; always read `GetGridSize()` at runtime.

---

## 3. How entities reference tiles

### Units

| Field | Source | Notes |
|-------|--------|-------|
| Position | `unit:GetX()`, `unit:GetY()` | Grid coords |
| `unit_index` (civ6-mcp tools) | `UnitManager.GetUnit(me, unit_index)` | Local unit id; [`_helpers.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/_helpers.py) |
| Full id in dumps | `unit:GetID()` | Sometimes combined `owner * 65536 + id` in logs |

Wire format from `get_units`: `x,y` as integers in strings like `12,34`.

### Cities

| Field | Source |
|-------|--------|
| Position | `city:GetX()`, `city:GetY()` |
| `city_id` | `CityManager.GetCity(me, city_id % 65536)` |

District placement and wonders need **extra** `PARAM_X`, `PARAM_Y` on the target tile (not always city center).

### Plots in deals / trade

City trade items use `city_id` (value type), not coordinates — coords come from city lookup.

---

## 4. How commands specify locations

All location parameters are **grid x, y** unless noted.

### Unit movement & combat

From civ6-mcp [`lua/units.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/units.py) (mirrors Firaxis `WorldInput.lua`):

```lua
local params = {}
params[UnitOperationTypes.PARAM_X] = target_x
params[UnitOperationTypes.PARAM_Y] = target_y
-- Optional: PARAM_MODIFIERS = ATTACK for capture moves
if UnitManager.CanStartOperation(unit, UnitOperationTypes.MOVE_TO, nil, params) then
  UnitManager.RequestOperation(unit, UnitOperationTypes.MOVE_TO, params)
end
```

| Tool / op | Location params |
|-----------|-----------------|
| `unit_action` move | `target_x`, `target_y` |
| `unit_action` attack | `target_x`, `target_y` |
| `get_pathing_estimate` | `target_x`, `target_y` → `GetMoveToPath(unit, plotIndex)` |
| Builder improve | Unit's current tile or `BUILD_IMPROVEMENT` params |
| `found_city` | Settler's tile (no target coords) |

**Pathing:** `UnitManager.GetMoveToPath(unit, targetPlot:GetIndex())` returns a list of **plot indices**; waypoints are converted back with `Map.GetPlotByIndex` → `GetX/GetY`. Validates destination: last tile must match requested `(target_x, target_y)`.

**Stacking:** Before move, civ6-mcp checks `Map.GetUnitsAt(target_x, target_y)` for friendly same-formation-class conflicts.

### City / production

From [`lua/cities.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/cities.py):

```lua
tParams[CityOperationTypes.PARAM_X] = target_x
tParams[CityOperationTypes.PARAM_Y] = target_y
CityManager.CanStartOperation(pCity, CityOperationTypes.BUILD, tCheck, true)
CityManager.RequestOperation(pCity, CityOperationTypes.BUILD, tParams)
```

| Action | Location |
|--------|----------|
| District / wonder placement | `target_x`, `target_y` on tile |
| Repair pillaged district | district's `GetX()`, `GetY()` |
| `purchase_tile` | `x`, `y` |
| City ranged strike | `CityCommandTypes.PARAM_X/Y` |

### Map queries (no mutation)

| Tool | Region definition |
|------|-------------------|
| `get_map_area(center_x, center_y, radius)` | **Square** in grid space: `for dy=-r,r for dx=-r,r` — not a true hex ring ([`map.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/map.py)) |
| `get_strategic_map` | Fog rays from cities + scan all revealed tiles |
| `get_settle_advisor` | Scores candidate `(cx, cy)` grid coords |

**Implication:** `radius=2` is a 5×5 **grid square** (25 tiles), slightly different from a hex disk of radius 2. For legal_commands, prefer `Map.GetPlotDistance` when you need true hex range.

---

## 5. Visibility & fog (for `known_map`)

civ6-mcp pattern:

```lua
local vis = PlayersVisibility[me]
local revealed = vis:IsRevealed(plot:GetIndex())
local visible  = vis:IsVisible(plot:GetIndex())
```

| State | Meaning |
|-------|---------|
| Not revealed | Unknown — omit from LLM map or show fog |
| Revealed, not visible | Explored but not currently seen (units may be hidden) |
| Visible | In vision — yields, enemy units on tile populated in `get_map_area` |

Bulk seed: `build_revealed_tiles_seed_query()` iterates all plots, lists revealed `(x,y)` pairs.

**Own units** are listed in `get_map_area` even on non-visible tiles ([`map.py`](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/map.py) — “Own units: always known”).

---

## 6. Civ IV vs Civ VI (porting `map_render.py`)

| Aspect | Civ IV (`sidecar/map_render.py`) | Civ VI |
|--------|----------------------------------|--------|
| Topology | Square 4-neighbor | Hex 6-neighbor |
| `plot_id` | `PLOT_x_y` style in schema | Use `(x,y)` or `index`; no Firaxis `PLOT_` string required |
| River edges | N, E, S, W | `plot:IsRiver()` per tile; different model |
| Territory borders | `territory_owner_grid`, square neighbor check | `plot:GetOwner()`; hex neighbors via `PlotDirection` |
| Renderer cells | Square `tile_px` rectangles | Need **hex or odd-r offset** layout |
| Visibility | `visibility_grid` chars | `IsRevealed` / `IsVisible` per plot |

### Hex rendering (for PNG minimap)

Odd-r **screen** layout (common choice):

```text
tile_w = tile_px
x_screen = tile_px * (grid_x + 0.5 * (grid_y & 1))
y_screen = tile_px * grid_y * 0.75      -- flat-top vertical pitch
```

Alternatively convert grid → axial with `ToHexFromGrid` and use [Red Blob](https://www.redblobgames.com/grids/hexagons/) `axial_to_pixel`.

Civ IV renderer can be reused for **legend, icons, fog mask, territory tint** — only the cell placement function changes.

### Proposed `known_map` schema (Civ6)

Mirror Civ IV `plot-grid-v1` but document coord system:

```json
{
  "format": "plot-grid-v1-civ6",
  "coord_system": "civ6_grid_xy",
  "width": 84,
  "height": 52,
  "plots": [
    {
      "x": 12, "y": 34,
      "knowledge": "visible",
      "terrain_id": "TERRAIN_GRASS",
      "owner_player_id": "PLAYER_2",
      ...
    }
  ],
  "visibility_grid": ["..."]   // optional dense rows, '?' = unrevealed
}
```

Always store **grid** `x,y` in wire + commands — never hex event coords without conversion.

---

## 7. `legal_commands` location domains

When probing move/attack commands for the closed-world catalog:

1. For each idle unit at `(ux, uy)`, enumerate targets:
   - **Melee:** adjacent tiles via `Map.PlotDirection` × 6, or `GetReachableMovement` indices.
   - **Ranged:** `CanStartOperation(RANGE_ATTACK, nil, params)` per candidate tile within range.
2. Emit `fixed_arguments: { "unit_index": N, "target_x": tx, "target_y": ty }`.
3. Cap list size (e.g. top-K by threat/distance) — Civ IV caps at 512 commands total.

**Do not** emit relative directions (`NE`, `3 hex north`) in fixed_arguments — always absolute grid coords the executor can pass to Lua unchanged.

---

## 8. civ6-mcp coordinate gotchas (from production code)

| Gotcha | Detail |
|--------|--------|
| `get_map_area` square | Spatial tracker assumes square iteration — fine for attention logging, not exact hex rings |
| Static map dump | Full map including unrevealed tiles — for spectator replay, not LLM fog map |
| `unit_index` vs `GetID()` | Tools use `UnitManager.GetUnit(me, unit_index)` — match id from `get_units` column |
| `city_id % 65536` | City lookup strips high bits |
| InGame vs GameCore | Move uses InGame `UnitManager`; some reads use GameCore `Players[me]:GetUnits():FindID` |
| Water embark | `get_pathing_estimate` / move diag distinguishes water, mountain, foreign border |

---

## 9. Quick reference links

- [Map.GetPlot (Sukritact KB)](https://sukritact.github.io/Civilization-VI-Modding-Knowledge-Base/Map.GetPlot)
- [UnitManager.MoveUnit / CanStartOperation](https://sukritact.github.io/Civilization-VI-Modding-Knowledge-Base/UnitManager.CanStartOperation)
- [Civ5 grid vs hex (still applies conceptually)](https://modiki.civfanatics.com/index.php/Map_and_terrain_(Civ5))
- [ToGridFromHex / iterators](https://forums.civfanatics.com/threads/using-whowards-border-and-plot-iterators-in-civ-6.607334/)
- [Hex coords in events — wrong GetPlot bug](https://forums.civfanatics.com/threads/adventures-in-border-plots.665278/)
- [civ6-mcp map.lua builders](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/map.py)
- [civ6-mcp units.lua builders](https://github.com/lmwilki/civ6-mcp/blob/main/src/civ_mcp/lua/units.py)
- [Red Blob hex coordinates](https://www.redblobgames.com/grids/hexagons/)

---

## 10. Next implementation steps

- [ ] InGame Lua: print `GetGridSize`, sample `PlotDirection` neighbors for one `(x,y)`  
- [ ] Fixture: one `get_map_area` dump + matching `get_units` positions  
- [ ] `sidecar/map_render_civ6.py`: odd-r layout + `IsRevealed` mask  
- [ ] Document `unit_index` / `city_id` in `civ6-command-capabilities.json`
