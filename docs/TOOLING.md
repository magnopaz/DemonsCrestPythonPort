# Tooling

## Auditing generated sprites

`tools/audit_sprites.py` is the structural gate for `species_anim.json`
(and reports the player/form sheets). It rejects missing textures, anchors
outside the image, duplicate images assigned to different species, and
fragmented captures that are clearly tilemap fragments:

```
python tools/audit_sprites.py --assets assets/generated --strict
python tools/audit_sprites.py --assets assets/generated --quarantine
```

`--quarantine` removes failing species entries from `species_anim.json` and
keeps a `.bak` next to it. `run_regression.py` runs the strict audit when the
asset file exists, so a bad bake cannot silently enter the build.

## Baking the player form sheets

`tools/dc_extract/bake_player_forms.py` uses measured per-sheet clip regions
and connected pose components, not empty-column splitting. It removes captions,
keeps the white/gold hurt pose and writes `fb_<form>_<clip>_<i>.png` plus
`player_forms.json`. The forms are the default; `DC_PLAYER_FORMS=0` restores the
captured base animation.

## Baking Arma's encounter palettes

`tools/dc_extract/bake_arma.py` uses individually measured pose boxes for all
three Arma sheets. Do not replace them with whole sheet rows: the rows contain
captions and several poses, which is what produced the earlier multi-sprite
PNGs. The script writes the base `$A5` art plus two boss variants:

- `flags=2`: green second-fight palette from `Arma.gif`;
- `flags=4`: `Ultimate Arma.gif`.

`Assets_BossSheet(assets, species, flags)` picks the exact object-flag variant;
areas 3/23/36/67 use flags 0/2/4/4 respectively.

## Baking labelled enemy sheet rows

Regular enemies use `tools/dc_extract/bake_enemy_sheets.py`, the enemy
counterpart of `bake_boss_sheets.py`: one measured box per pose, background
flooded from the crop border (dark outlines survive), tiny detached specks
dropped, frames mirrored to face right (the renderer mirrors for
`o->facing < 0`), then merged into `species_anim.json` with `states` for object
states 0/1. Re-running deletes its own stale PNGs, so the output is
deterministic.

Current mappings (see the script header for the measured boxes):

| species | sheet row | poses |
|---|---|---|
| `$2C` skeleton walker | Enemies 1 "Scavenger Demon" | 4 walk |
| `$26` armoured undead | Enemies 1 "Zombie Head / Armor Zombie" | 3 walk |
| `$08` forest ogre | Enemies 2 "Ogre Demon" | 4 unarmed |
| `$07` bat/watcher | Enemies 1 "Vampire Bat" | 3 flight |

`$24/$2D/$2E` are `pickup_crest` objects in `SPECIES_KIND_MAP`, not enemies.

For a one-off row, `tools/sheet_row.py` still works: give it the measured band
(exclude the caption row) and it splits on background columns, keys the flat
background and merges the entry. It is deliberately not a whole-sheet
auto-detector, and its column split can cut a pose in two, so prefer the
measured-box baker above.

```
python tools/sheet_row.py \
  --sheet "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Enemies 1.gif" \
  --species 0x2c --x0 0 --x1 420 --y0 300 --y1 380 \
  --source "Scavenger Demon row" --state 0
```

## Boss sheet mappings

The named boss saves are the authoritative source for species ids. Current
mappings recovered from their live object pools:

| boss/room | species |
|---|---|
| Holothurion (52) | `$6F` (parts `$90`, `$92`) |
| Scula (26) | `$7B`, `$7C` (plus `$7F`) |
| Ovnunu (54) | `$16`, `$17`, `$18` |
| Crawler (ice palace) | `$82` (plus `$83/$84/$85` parts) |
| Belth (boneyard) | `$68` |
| Phalanx (84) | `$86` first form + `$88`; `$8D` second-form body |
| Arma (3/23/36/67) | `$A5` + flags `0/2/4` palette variants |
| demon realm (86) | `$58`, `$5C`, `$5D`, `$5E`, `$5F` |
| final second form (90) | `$BC` (plus `$8A`) |

The demon-realm `$58` object uses `Flame Lord.gif`; the final second form `$BC`
uses `Dark Demon.gif`. Phalanx's second form uses `$8D` and the three full-body
poses from `Ultimate Phalanx.gif`; the second-form object keeps the `$86` head
AI. `tools/check_bosses.py` is the data/runtime gate for these mappings:

```text
python tools/check_bosses.py --binary build/demonscrest.exe \
  --assets assets/generated --runtime
```

It checks the expected species/flags/positions, the base/variant textures, and
boots each room briefly to confirm the boss object actually spawns. The object
trace gained a `flags` column for the Arma palette variants. Boss sheets can be
baked directly from measured full-body boxes with the generic tool:

```text
python tools/dc_extract/bake_boss_rows.py \
  --sheet "docs/sprites/...Dark Demon.gif" --species 0xBC \
  --boxes "6,50,132,148;140,52,272,148;280,52,400,148"
```

`bake_holothurion.py` writes `$6F` from `Holothurion.gif`;
`bake_scula.py` writes `$7B/$7C` from `Scula.gif` (the boss save has two
enemies at the same arena position); `bake_ovnunu.py` writes the temple boss
`$16` from `Ovnunu.gif`; `bake_boss_sheets.py` bakes the five measured boss
rows in one pass — Crawler `$82` (Crawler.gif "Moving" row), Phalanx `$86`
(Phalanx.gif First Fight idle row), the `$8D` second form (Ultimate
Phalanx.gif "Examples" row, written as the `flags=0` boss variant), Flame Lord
`$58` (Flame Lord.gif "Idle" group; the left of that row is the teleport
flame, not the boss) and Dark Demon `$BC` (Dark Demon.gif top body row);
`bake_boss_rows.py` bakes measured full-body boxes
for Belth (`$68`); `clean_somulo.py` removes the two
measured gate-bar columns from the native Somulo reference and re-anchors the
full body at the floor; `bake_somulo_frames.py` replaces that native cut with a
21-frame sheet extraction (16 full-body walk frames from
`docs/reference/somulo_walk.gif`, atlas windup/fire/roar heads, atlas collapsed
body) under `assets/authored/species_anim.json`; `bake_npc96.py` keeps the
area-8 town NPC on `NPCs.png`.
`fix_room_boss_species.py --room room_area52.json --old 150 --new 111` patches
the boss object when the ROM room list names the wrong species.
`add_room_boss.py --room room_area26.json --bosses "123:1320:154,124:1380:154"`
adds the two Scula boss objects from the save positions. The other measured
placements are:

```text
python tools/dc_extract/add_room_boss.py \
  --room assets/generated/room_area3.json --bosses "165:856:1180:0"
python tools/dc_extract/add_room_boss.py \
  --room assets/generated/room_area23.json --bosses "165:640:1932:2"
python tools/dc_extract/add_room_boss.py \
  --room assets/generated/room_area68.json --bosses "130:1808:160"
python tools/dc_extract/add_room_boss.py \
  --room assets/generated/room_area86.json --bosses "88:128:120"
python tools/dc_extract/add_room_boss.py \
  --room assets/generated/room_area90.json --bosses "188:128:120"
```

The fourth field is the object flags (Arma palette); omitted flags are preserved
on a replacement. Crawler uses `y=160` rather than the save's `y=72`: the
original position is almost entirely above the camera at area 68 and cannot be
fought. Arma's area-3/23 objects also had `y=0` despite their cameras sitting at
`y=1040`/`y=1792`; they are moved to `1180`/`1932` in the same chunk.

Some species ids are reused by different object kinds; `species_anim.json`
also supports an optional `"variant": "boss"` entry, used only for
`OBJECT_BOSS`.

## Full-stage map fallback

When a room's ROM BG tilemap is demonstrably wrong, install a community
full-stage map as a world-locked backdrop and leave collision/object data
untouched:

```
python tools/dc_extract/install_full_map_backdrop.py \
  --area 2 \
  --map "docs/FullMaps/images/demons-crest-murkland-cemetery-snes-map.webp" \
  --parallax 1.0 --y -70
```

The tool writes `bg_backdrop_area<N>.png`, replaces the BG tile layers with a
transparent one-cell layer (tile 0 in the baked atlases is transparent), and
sets `backdrop_parallax`/`backdrop_y` in the room JSON. This is the deliberate
fallback for areas whose tilemap/CHR cannot be trusted; the image is expected
to contain baked scenery (and possibly baked props), so it is not a substitute
for a proper ROM/VRAM rebuild.

## Diagnosing background layers

`tools/dc_extract/bg_recompose.py <dump_dir> --frame <reference.png>` renders
BG1/BG2 from the same VRAM/CGRAM/registers and writes the flattened result plus
separate `<out>_bg1.png` / `<out>_bg2.png` layers. Compare the result with the
reference frame before touching the room data; the area-2 investigation showed
that the extracted BG1 tilemap itself was wrong (~47% tile agreement), so an
atlas rebake alone cannot fix that room.

## Replaying a recomp recording

`tools/oracle/replay_capture.py` converts a recorder `input_log.jsonl` into the
format `replay_input` expects, replays it from boot, and dumps exact OAM/CGRAM/
VRAM/WRAM plus a screenshot for requested guest frames:

```
python tools/oracle/replay_capture.py \
  --recording "M:/Opencode/DemonsCrestSNESRecomp/captures/rec_20261027_151150" \
  --out captures/ref --frames 1200,2200,7002 --png
```

This is the reference path for checking a sprite or animation against the
original game without re-playing it.

## Extracting frames from a video

`tools/video_frames.py` pulls frames out of any mp4/mkv using ffmpeg (installed as
a Python wheel, no system install needed):

```
python tools/video_frames.py "C:\path\take.mp4" --every 20 --sheet
```

- `--every N` keeps one frame in N (default 10), `--fps F` asks for F per second;
- `--start/--end SEC` limit the range, `--scale W` downscales;
- `--sheet` writes `contact_sheet.png` with frame numbers, so a whole take can be
  skimmed at once.

Frames land in `<video-name>/frame_00001.png`. Requires
`pip install imageio-ffmpeg` (the tool says so if it is missing).

## Harvesting a training set from the sheets (Pipeline C)

`tools/gen/harvest_dataset.py` turns `docs/sprites/` into per-pose crops a
diffusion trainer can use: pose boxes come from `bake_player_forms.py` for the
six Firebrand forms (component-based harvesting for the enemy sheets), the flat
sheet background is keyed out, each pose is padded to a square and upscaled by
an **integer** nearest-neighbour factor, and every image gets a `.txt` caption.

```
python tools/gen/harvest_dataset.py --out ~/datasets/dcrest --sheets forms --variants 2
python tools/gen/harvest_dataset.py --out ~/datasets/dcrest --sheets enemies --variants 1
```

Measured on the Pi: 211 crops from the form sheets in 14 s, 525 component crops
from the enemy sheets in 265 s. The component route is approximate — about 1 in
16 crops is a caption fragment and must be deleted before training. Output
belongs outside the repo; `manifest.json` records the counts.

## Constraining generated art into a legal sprite

`tools/gen/pixelize.py` is the deterministic bridge between "an image" and "a
sprite this engine can load":

```
python tools/gen/pixelize.py drafts/imp_01.png --height 48 --tile-pad \
  --out assets/authored/spr_imp_walk_0.png --clip walk --duration 7 --species 0x120
```

It keys the background (border colour, an explicit hex, or the input's own
alpha), crops to the opaque box, resizes to `--height`, builds a palette by
weighted median cut over the opaque pixels only, snaps it to the SNES BGR555
space, despeckles, forces binary alpha, measures the anchors the engine expects
(`anchor_y` = feet, `anchor_x` = body centre of the lower part of the pose),
optionally pads to an 8x8 tile grid, and writes a JSON sidecar with the palette,
blob sizes and anchors. It exits non-zero on a hard violation: more than
`--colors` (default 15), larger than 64 px, non-binary alpha, more than six
blobs. Verified on a soft 768x768 "diffusion-like" input: 32x48, 15 colours,
BGR555-aligned, one blob, and a 96 px request correctly rejected.

The workflow these two tools belong to is `docs/AI_CHARACTER_PIPELINE.md`.

## Cutting pose references from an existing species

`tools/gen/pose_refs.py` turns the measured pose boxes of a shipped species into
1024 px reference images an img2img + ControlNet pass can repaint onto a new
creature. It reuses `bake_enemy_sheets.JOBS`, so the poses are the same ones the
game itself animates (and the pixel grid survives: integer nearest upscale on a
white canvas).

```
python3 tools/gen/pose_refs.py --list
python3 tools/gen/pose_refs.py --species 0x2c --out ~/datasets/refs/imp \
    --size 1024 --labels walk0,walk1,walk2,walk3
```

Measured setting that held the pose while repainting: denoise **0.50** with
ControlNet strength **0.85** (0.60/0.65 flattened four distinct walk poses into
one stance). Lock the palette for the whole set by feeding the first accepted
frame's 15 colours back through `pixelize.py --palette`.

## Assembling a species entry

`tools/gen/compose_species.py` collects pixelized frames into a
`species_entries.json` payload for `species_anim.json`, and re-checks every PNG
(≤64 px, ≤15 opaque colours, binary alpha) before writing:

```
python3 tools/gen/compose_species.py --spec imp.json --out assets/authored
```

`species_anim.json` is an **object keyed by species id in lowercase hex**; the
audit rejects an array with "no 'species' object". Merge with a dict update
(snippet in `docs/AI_CHARACTER_PIPELINE.md` §6) and re-run
`audit_sprites.py --strict`. The first enemy built this way (species `0x120`, 7
frames, `1 species, 7 frames, 0 error(s)`) is written up in §7.5 of that doc.

## Belth's missing poses

The generated Belth entry only had the walking row (3 frames) because
`bake_boss_rows.py` was pointed at one measured band. `tools/dc_extract/
bake_belth_animation.py` (a wrapper over `SPECS["belth"]` in
`bake_sheet_anim.py`) slices the labelled `Belth.gif` rows (idle, taunt, walk,
attack, jump, charge, turn, hurt, death), keys the flat sheet background,
removes captions/specks, and writes a 32-frame **authored** entry plus PNGs
under `assets/authored/sprites/belth/`. The entry carries a `state_names` map
so the Enemy Editor shows `State 3 · attack` instead of a bare number.

Every extraction gets its own subfolder (`sprites/<target>/`, texture
`sprites/<target>/<file>.png`) — never loose files in the `sprites/` root.
`bake_sheet_anim.py` is the general baker for the other sheets; see
`docs/SPRITE_SHEET_EXTRACTION.md` §4.0 for the measuring tools.

The Python port's `DC_SPECIES_FRAMES` is now 64 (the frozen C reference keeps
10), so the full authored set loads. The generated entry is untouched; the
authored overlay wins at load time.

```sh
python tools/dc_extract/bake_belth_animation.py
python tools/dc_extract/bake_sheet_anim.py --list
python tools/audit_sprites.py --assets assets/generated --strict
```

## Visual content tools

`tools/editor/` is the browser-based content suite:

- **Map Builder**: rooms, BG0/BG1 tiles, collision shapes and environment
  flags (hazard/water/breakable), objects, doors, spawns, play/camera bounds,
  per-room music, a game-accurate 256x224 preview and a "Render in game"
  button that runs the real Python port headlessly on the unsaved room
  (`DC_AUTHORED_ROOMS` temp copy + `DC_SCREENSHOT_RT`).
- **Enemy Editor**: species frames/anchors/durations, state animations, stats,
  movement AI, attack patterns and sound slots. Authored patterns run for
  data-driven enemies, and ranged/melee patterns are layered onto bosses.
- **Player Editor**: Firebrand's base sheet plus the six crest forms; all 11
  clips (`idle`, `walk`, `jump`, `hover`, `fall`, `land`, `attack`, `spell`,
  `flying`, `hurt`, `death`), frame order/anchors/durations, loop flags and a
  stage with the 12x22 gameplay hitbox. Saves to
  `assets/authored/player_anim.json` and `player_forms.json`; `dcpy/anim.py`
  merges those over the generated sheets.
- **Dialogue**: the 518 ROM text blocks with the pages the loader really
  draws (8 pages × 8 lines, `j` breaks, 47-character lines), a preview using
  the game's 8x8 font, loader warnings, and the `text_find` needles the game
  uses — including any that resolve to nothing. Edits go to
  `assets/authored/text_strings.json`, which `dcpy/text.py` applies.
- **Coverage**: every object record grouped by species, with record/room
  counts, art-sheet status, authored HP and per-room validation; filters for
  placeholders and missing art, with click-through to the Enemy Editor and Map
  Builder. This is the browser view of `tools/report_coverage.py`.
- **Checks**: the project's own gates (`tools/check_*.py` plus the full
  regression) with their output, exit code and timing, run one at a time in
  the project venv. Checks that boot the game need a display (Xvfb `:99` is
  detected automatically).
- **Asset Browser**: every generated and authored PNG with dimensions and the
  rooms/species/player records that use it.

Start it with `python tools/editor/server.py` and open the printed localhost
URL. It writes to `assets/authored/` by default; the runtime already prefers
that overlay (`level.py` for rooms, `assets.py` for species, `enemy_defs.py`
for stats/attacks/sounds, `anim.py` for player sheets, `text.py` for dialogue).
Backend tests: `python tools/editor/test_editor.py`; browser self-test:
`http://127.0.0.1:8765/web/test.html`. Full workflow and API reference:
`tools/editor/README.md`.

For the sprite-sheet extraction playbook (measured bands, column splitting,
anchors, authored overlays, all sheet/species targets), see
[SPRITE_SHEET_EXTRACTION.md](SPRITE_SHEET_EXTRACTION.md).
