# Demon's Crest Content Toolkit

A local, browser-based editor suite for the Python port:

- **Map Builder** — load an existing room or create a new one; paint BG tiles,
  collision, hazards, water and breakable blocks; place enemies, bosses, urns,
  platforms and items; edit doors, spawns, play/camera bounds and per-room
  music; preview the room exactly as the game draws it.
- **Enemy Editor** — load a species or create a new one; import images as
  animation frames; set anchors and durations; build state animations; edit HP,
  contact damage, movement AI, attack patterns and sound slots; test the
  pattern on the stage.
- **Player Editor** — edit Firebrand's base animation and the six crest forms
  (Normal, Ground, Aerial, Tidal, Legendary, Ultimate): frames, order, anchors,
  durations, loop flags and all 11 animation clips, with the 12x22 hitbox drawn
  on the stage.
- **Asset Browser** — every PNG in `assets/generated` and `assets/authored`
  with dimensions, size and the rooms/species/player records that use it.

It is not a pixel-art editor: frames and backgrounds are loaded as PNGs, and
tile/background editing picks tiles out of the existing atlases.

## Start it

From the repository root:

```sh
python tools/editor/server.py
```

or double-click `tools/editor/run.bat` on Windows / run `tools/editor/run.sh`
on Linux. The server prints a `http://127.0.0.1:8765/` URL and opens it. It
binds to localhost only.

Options: `--port N`, `--host 127.0.0.1`, `--assets DIR`,
`--authored DIR`, `--no-browser`.

The editor uses only the Python standard library and the browser; there is no
build step and no CDN.

## Where changes go

Saving never overwrites the ROM-derived tree by default:

| What | Default target |
|---|---|
| Rooms | `assets/authored/rooms/room_area<N>.json` |
| Species animation | `assets/authored/species_anim.json` |
| Player base animation | `assets/authored/player_anim.json` |
| Player forms | `assets/authored/player_forms.json` |
| Enemy stats/attacks/sounds | `assets/authored/enemies.json` |
| Imported images | `assets/authored/sprites/` |
| Backups | `assets/authored/backups/` |

The game already prefers that overlay:

- `dcpy/level.py` loads a room from `assets/authored/rooms` first, then from
  `assets/generated`, and falls back if an authored file is broken.
- `dcpy/assets.py` merges `assets/authored/species_anim.json` over the
  generated species entries and resolves textures from
  `assets/authored/sprites/`.
- `dcpy/enemy_defs.py` loads the authored enemy definitions at startup.
- `dcpy/anim.py` merges `assets/authored/player_anim.json` clip-by-clip over the
  base player sheet, and `player_forms.json` form-by-form over the six
  generated crest forms.

For a checkout that keeps authored content elsewhere, set
`DC_AUTHORED_ROOMS` (room overlay directory) and `DC_AUTHORED_DIR` (species,
enemy definitions and sprites). The server takes the same locations through
`--authored`.

The **Save options** menu also offers **Save into generated assets** (a
timestamped backup is kept) and **Export room/species JSON**. Use the generated
target deliberately: it replaces the extracted content and removes the
authored override for that room/species.

## Map Builder

**Rooms.** Pick a room in the toolbar. The status badge says whether it is
`Generated`, `Authored override` or a new unsaved room. `+` creates a new area;
`Resize…` changes the world size and grows/crops the collision grid and BG1.
The **Tile atlas** selector lets a new map borrow another area's extracted
background atlas (`bg_atlas_area` in the room JSON).

**Tools** (also shown as keyboard shortcuts):

| Key | Tool | What it does |
|---|---|---|
| `V` | Select | select/drag objects, doors, spawns and bounds handles |
| `C` | Collision | paint the collision shape + environment flag |
| `T` | Tiles | paint BG0/BG1 tiles from the atlas |
| `O` | Objects | stamp the selected type/species |
| `D` | Door | add a transition at the click point |
| `S` | Spawn | set the primary spawn (Shift+click adds another) |
| `H` | Pan | hand tool (or middle mouse / Space-drag anywhere) |

Other keys: `Ctrl+S` save, `Ctrl+Z` / `Ctrl+Y` undo/redo, `Ctrl+C` / `Ctrl+V`
copy/paste the selected object or door, `Ctrl+D` duplicate, `Del` delete,
arrows nudge 1 px (Shift = 8 px), `0` fit, `+/-` zoom, `G` grid, `P` preview,
`Esc` deselect. Wheel zooms at the cursor.

**Collision.** Choose a shape (solid, wedges, ramps) and an environment flag
(hazard, breakable, water, ramp). The value written is
`shape | flag` (`0x20/0x40/0x60/0x80`). Paint, rectangle or fill modes; right
click erases; `Alt`+click picks the cell under the cursor. **Keep the existing
shape** turns the brush into a flag-only brush, which is the quick way to mark
existing solid ground as hazard/water/breakable. Hazard/water/breakable cells
are coloured in the overlay and counted in the panel.

**Backgrounds.** The layer picker selects BG0 (parallax) or BG1 (world). The
tile picker shows the 256×256 base tiles of the current palette; flip H/V are
stored in the map word. BG0 paints in layer space, which is anchored by its
`scroll_x/scroll_y` relative to the room camera start.

**Objects.** Choose a type and species, then click the map. Flags are
type-specific: enemy bit 0 flips the initial facing, talisman flags 0“4 select
the item, boss flags select palette/encounter variants (Arma 0/2/4). The
inspector can snap an object to the floor, duplicate or delete it. The object
list filters by name/species.

**Doors and spawns.** A door is a transition trigger: `next_area`, `spawn_id`,
`pad_mask`, `type` and the half-size rectangle. `spawn_id` indexes the
destination room's `spawns` array. The primary spawn is `spawn`; extra spawns
are stored in `spawns`.

**Bounds.** Yellow = play bounds, blue = camera limits, white = the initial
camera viewport. Drag a corner/edge handle, or type exact values in the panel.

**Compare.** In the View panel, –Compare current collision/objects with
generated“ fetches the ROM-derived room and paints every changed collision cell
magenta; the inspector lists changed collision cells, objects, doors, spawns
and room fields. This is the quick way to review a correction pass without
diffing JSON by hand.

**Music.** The selector stores the track id in the room JSON; leaving it on
–Area default“ omits the field. The runtime uses `level.music` when present,
otherwise the measured area table. The play button streams the ROM-rendered
WAV from `assets/generated/audio`.

**Game preview.** `Preview` (or `P`) renders the room with the game's own
layer rules: backdrop parallax, BG0 wrapping/HDMA bands, world-space BG1,
objects and the player spawn. Camera x/y is shown in the preview bar; `At
spawn`/`At camera` jump to those positions, `PNG` downloads the 256×224 frame.

**Render in game.** `Render in game` runs the actual Python port headlessly
with a temporary copy of the *unsaved* room (through `DC_AUTHORED_ROOMS`), and
shows the real 256×224 game frame with HUD. It takes a few seconds, does not
save the room, and is the definitive check when the editor preview and the
game disagree. The output PNGs land in `captures/editor_render/`.

## Enemy Editor

**Species list.** Filter by enemies/bosses/NPCs/edited, or search by name, key
or species id. `New` creates an entry with a placeholder 32×32 frame (replace
it with `Upload…` or `From asset`).

**Frames.** Every frame is a PNG plus `anchor_x`, `anchor_y` and `duration`.
The anchor is the pixel placed at the object's world position: X is the body
centre, Y the feet. `Pick on stage` lets you click the anchor directly. The
strip plays the selected sequence; frame cards select/edit a frame. The
Python port keeps up to 64 frames per species (the C reference keeps 10); the
authored Belth entry (`$68`) is a 32-frame example with `state_names`
(`idle`, `taunt`, `walk`, `attack`, `jump`, `charge`, `turn`, `hurt`, `death`)
baked from `docs/sprites/…Belth.gif`.

**Animation.** States 0“15 each hold up to 8 frame indices (the loader cap);
click a chip to select that frame, right-click to remove it, `+` appends the
selected frame. `Hurt` is the white-flash pose and `Default` is the single pose
used when no state animation is active. The sequence picker in the stage
toolbar previews `All frames`, the default pose or a specific state.

**Stats.** `HP`, contact damage, defense, invulnerability, movement AI
(walker/flyer/charger/turret/stationary), speed, aggro range, bob, gravity and
`Override native AI`. The three ported enemy handlers (`$2C`, `$07`, `$67`)
keep their exact ROM AI by default; new species use the data-driven profile.
`Override native AI` is the explicit opt-in for replacing a ported handler.
Boss objects keep their native movement/AI; ranged and melee patterns from the
profile are layered on top (lunge is enemy-only), and HP/contact damage apply.

**Attacks.** Up to 8 patterns. Projectile/spread/burst patterns spawn enemy
shots with a count, spread, speed, damage, projectile species, aim mode and
sound. `lunge` and `melee` are close-range. The stage's `Test patterns` toggle
shows the timing and projectile fan illustratively.

**Sounds.** Spawn/attack/hurt/death slots map to the captured effects
(`jump`, `land`, `shoot`, `break`, `pickup`, `hurt`, `enemy_hit`). The runtime
queues them through `ObjectPool.sfx_queue`; the play button previews the WAV.

**Save.** `Ctrl+S` validates and writes the authored species entry plus the
enemy definition sidecar. `Save options` can export JSON or revert the authored
override.

## Player Editor

**Targets.** The left list contains the shared Firebrand base sheet and the six
crest forms. `Base` edits `player_anim.json`; forms 0-5 edit one entry each in
`player_forms.json`. The game selects a form sheet by `crest_form` and falls
back to the base sheet if that form is missing.

**Clips.** All 11 clip names are listed (`idle`, `walk`, `jump`, `hover`,
`fall`, `land`, `attack`, `spell`, `flying`, `hurt`, `death`); a clip exists
only when it has frames. The checkbox controls whether it loops in game. Empty
clips are omitted on save (the loader rejects a clip with zero steps).

**Stage.** The toolbar selects a clip, speed, flip, hitbox and anchor picking.
The dashed cyan box is the 12x22 gameplay hitbox at the current anchor. Hover
over nothing; `Pick anchor` + click sets the anchor from the image pixel under
the cursor. Frame cards at the bottom select the edit frame.

**Frames.** `Add frame` takes an asset, an uploaded PNG or a copy of the
selected frame. Each frame has a texture, `anchor_x`, `anchor_y` and a duration
in 60 Hz ticks. `<- Move` / `Move ->` reorder; `Replace image` keeps the old
anchor/duration; `Delete` removes it. Total steps across all clips are capped at
64 by `DC_ANIM_MAX_STEPS`.

**Form and Stats.** The Form tab edits the display name (editor only), shows the
clip overview and validation. Stats are read-only engine constants from
`dcpy/player.py`; the editor changes animation sheets, not physics.

**Save and revert.** `Ctrl+S` validates and writes the authored target. Revert
deletes that authored entry and reloads the generated sheet. A timestamped
backup lands in `assets/authored/backups/`.

## Asset Browser

Search by filename/path/usage, filter generated vs authored, sort by path,
name, size or dimensions. Click a card for a large preview, metadata and the
records that reference it. Use **Copy path** to paste a path into a JSON entry.

## HTTP API

The UI is a thin client over a small JSON API; useful for scripts:

| Route | Purpose |
|---|---|
| `GET /api/health` | project paths, room/species counts |
| `GET /api/meta` | music, SFX, object types, collision shapes, limits |
| `GET /api/rooms` | room index (area, label, source, size, counts, music) |
| `GET /api/rooms/<area>` | room JSON + resolved atlas/backdrop URLs + validation |
| `POST /api/rooms/<area>` | save `{room, target}` (`authored` or `generated`) |
| `DELETE /api/rooms/<area>` | remove the authored override |
| `POST /api/rooms/<area>/resize` | resize world/collision/BG1 (optionally BG0) |
| `POST /api/rooms/<area>/validate` | validate a room object |
| `POST /api/rooms/<area>/render` | run the game headlessly on an unsaved room and return a PNG URL |
| `GET /api/rooms/<area>/original` | the generated room, for the Compare view |
| `GET /api/rooms/<area>/assets?atlas=N` | atlas URLs for a room |
| `GET /api/species` | merged species index |
| `GET /api/species/<key>` | one species + definition + resolved frame URLs |
| `POST /api/species/<key>` | save `{entry, definition, target}` |
| `DELETE /api/species/<key>` | remove the authored species override |
| `GET /api/player` | base + six form summaries, clip names and limits |
| `GET /api/player/<target>` | one player sheet (`base` or `0`..`5`) with resolved frame URLs |
| `POST /api/player/<target>` | save one player sheet |
| `DELETE /api/player/<target>` | remove one authored player override |
| `POST /api/player/validate` | validate `{target, entry}` |
| `GET /api/assets` | image index with dimensions/usage |
| `POST /api/assets/upload` | `{name, data(base64 PNG), overwrite}` |
| `POST /api/validate/species` | validate an entry/definition |

## Verification

Backend tests (temporary project tree, no real assets touched):

```sh
python tools/editor/test_editor.py
python tools/editor/test_boss_patterns.py   # headless game, authored boss volley
```

Browser self-test (loads the real editor in an iframe, drives painting,
selection, saving, enemy editing and the API; writes
`captures/editor_selftest.json`):

```sh
# with the editor server running on port 8799
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" \
  --headless=new --disable-gpu --window-size=1600,1200 \
  --virtual-time-budget=90000 \
  --screenshot=captures/editor_test_page.png \
  http://127.0.0.1:8799/web/test.html
```

Runtime checks used during development:

```sh
# the game reads the authored overlay
DC_AREA=48 DC_RUN_FRAMES=3 DC_TRACE_CSV=captures/player.csv \
  .venv/bin/python -m dcpy.main --assets assets/generated
```

## Notes and limits

- Only PNG images are accepted for frames/imports; the editor checks the PNG
  signature and the IHDR dimensions, and warns above 64×64 (the sprite
  pipeline target).
- The loader keeps at most 64 frames per species, 16 states and 8 frames per
  state; the editor enforces the same caps. The 64-frame limit is a Python-port
  extension: the frozen C reference keeps 10, so authored species with more
  frames are Python-only content.
- Player sheets use the game's 11 clip names and share a 64-step budget per
  target. The Player Editor does not edit movement constants; those are in
  `dcpy/player.py`.
- Game preview approximates HDMA bands and does not draw the HUD; it is for
  layout verification, not a replacement for running the game.
- The room schema is the game's own; unknown keys are preserved on save.
- Saving a room/species into `assets/generated` is destructive by design and
  is only offered through the explicit Save options menu.
