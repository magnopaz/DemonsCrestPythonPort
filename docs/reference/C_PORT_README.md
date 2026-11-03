# Demon's Crest — Native Fan Game

A native C11 + raylib foundation for a Demon's Crest fan game. The original
game is used as the reference: level/object data and graphics are extracted
from the player's own ROM, and the recompilation project is used as a
frame-accurate oracle for movement and timing.

> **No ROM data is distributed with this project.** The `assets/generated/`
> and `captures/` directories are git-ignored. You must own Demon's Crest
> (USA) and generate them locally.

**Full project state, recovered technical details, traps and next steps:
[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).**

**Full-campaign gap analysis and remaining work:
[`docs/FULL_CAMPAIGN_PLAN.md`](docs/FULL_CAMPAIGN_PLAN.md).**

## Current state

- 256×224 render target, integer-scaled, 60 Hz update.
- Extracted full graveyard starting room from ROM **Area 1** (`screens 8, 9` =
  bottom-row `slots 9, 10`), 2048×256 px across the populated 8-screen row,
  with the stone pillar (`cx=24`, `x=384..399`, `y=128..159`) beneath the urn
  at `(385, 111)`.
- BG1 comes from the ROM block tables for all eight screens; BG2 is the
  captured 64×32 forest backdrop and loops horizontally as the camera scrolls.
- Slope surface heights decoded from the `$80:962B` jump table: Firebrand
  walks up/down the `0x07..0x0e` hill, stands at `y=164` on `attr=0x09`, and
  the camera follows across the full room with horizontal and vertical
  deadzones.
- Player and item sprites extracted from OAM.
- Walk, jump, hover and fall driven by the authentic Bank `$80` state machine
  in 8.8 fixed point, with slope-aware floor collision and viewport bounds.
  `B + Up` flight is a debug-only extra (`DC_FLY_DEBUG=1`).
- Firebrand animation set extracted from `save0` (ROM Area 3, `screens 52, 53`):
  idle, 6-pose walk cycle, jump rise, hover/fly, fall, landing, 17-frame Y
  fireball spit and 31-frame A spell.
- Bank `$80` (`$80:DB00..F310`) player state machine and constants ported:
  - walk speed `$1020`: flat ground keeps the `0x0166` cap (1.398 px/frame);
    the `0x00B3` first step and `$80:8B85` ramp belong to the `$1070` terrain
    path and are not wired to the new slope surface table yet,
  - jump initial velocity `$1022 = 0x059C` (5.609 px/frame; `0x02CE`
    underwater), with immediate `vy = 0` cut on B release while rising
    (`$80:E227`),
  - gravity `$1026 = 0x0038` (0.21875 px/frame²; `0x002A` underwater), terminal
    fall `0xFA00` (-6.0 px/frame),
  - mid-air hover (`State 0x06` at `$80:E1A3` / `$80:E29F`): pressing B in air
    zeroes `$1022` (`vy = 0`) and bypasses gravity; pressing B again returns to
    falling (`State 0x04`). (`$85:C1D4` was identified as the dropped heart
    bounce routine, not player jump.)
- Fireball shot implemented end to end:
  - 7-slot projectile pool (`src/projectile.c`) matching `$1080..$1260`,
  - spawn on the Y press frame at `floor(player.x) + 3`,
    `floor(player.y) - 8` with velocity `0x0300` (3.0 px/frame),
  - palette-6 OAM stream baked as `fireball_0..8.png` + `fireball_anim.json`,
  - despawn on solid walls or camera viewport exit, mirrored for left shots.
- Object system (`src/object.c`, 26 slots) driven by the Area 1 `$81:C874`
  object list:
  - four destructible urns (`species $57`) at the listed positions,
  - fireball hits shatter urns and drop a heart with the `$85:C180` arc
    (4.0 px/frame pop-up, 0.25 gravity, decreasing bounces),
  - touching a heart increments HP up to max,
  - species `$67` ghouls run their ROM state machine (`$83:AF74`: perched
    volley, hop, chase), damage on contact with knockback and drop hearts when
    killed by fireballs.
- BG3 HUD extracted from `save0`: six-point health bar plus three crest slots
  at the top of the frame; the active spell slot is highlighted.
- Fixed 60 Hz simulation with a frame-time accumulator; presentation refresh
  is decoupled while `DC_RUN_FRAMES` remains deterministic.
- Player/fireball animation frames have pre-baked mirrored textures, so the
  renderer no longer uses negative source rectangles.
- `ctest` / `tools/run_regression.sh` runs deterministic demos and asserts
  physics, projectile, pickup, enemy and HP invariants.
- Original procedural audio: a looping chiptune theme plus jump, land, shoot,
  break, pickup, hurt and enemy-hit SFX (no ROM audio data).
- Vertical-slice flow: title screen, pause overlay, and the cemetery's mid-boss
  gate — the Hippogriff (species `$09` at `x=1920`) blocks the way to Area 2
  until he is killed.
- Full-campaign foundation:
  - native ROM CHR decompressor (`$80:C2AF`/`$80:C300`) and `$98:C000`/
    `$98:D000` table decoders;
  - all 113 valid ROM areas extracted to `room_area<N>.json` with 2D
    multi-row/vertical grids, collision, spawns, transitions and object lists;
  - per-area BG atlases baked from ROM CHR/palettes and swapped per room;
  - OAM metasprite decoder (`$8B:8000`) with real ROM item/Crest and ghoul
    sprites;
  - BG2 HDMA scanline parallax from `$84:AF65` for Area 1;
  - per-area BG2 backdrops from oracle frames: `tools/dc_extract/bg2_captures.json`
    maps an area to a `capture_anim.py` frame; the extractor bakes that frame's
    BG2 tilemap plus a capture-based atlas (Area 1 and Area 3 are baked today).
    The guest generates BG2 tilemaps at runtime (`$84:A057` DMAs them from WRAM
    `$7F`), so this is the interim path until the generator is decoded;
  - multi-room transitions, boss gates and boss fights (Area 0 Somulo, Area 1
    Hippogriff);
  - six Gargoyle forms with Earth dash, Air flight, Water swim, Time/Ultimate
    defense, Fire-Crest elements, wall cling and headbutt;
  - skeleton/bat/gargoyle enemies, moving platforms, crest/Life-Stone pickups,
    gold, hazards, water and breakable terrain;
  - Crest/Item subscreen (`Tab`), shop, password/options/game-over/ending
    screens and an overworld map with six landing nodes (still drawn as a baked
    texture through a rotating `Camera2D`; the original Mode 7 plane is coming).
- `tools/audit_campaign.py` reports per-room structure (BG1/collision coverage,
  BG2 presence, spawn support, object/transition bounds) and classifies rooms as
  playable / partial / empty; `--strict` is suitable for CI.
- Save/options persistence: campaign progression (area, cleared stages, HP,
  Crests/forms, Talismans, Urns, Spells, gold) and the music volume are written
  to `saves/dc_save.json` on area clear, overworld entry and exit. When a save
  exists the title menu gains a `CONTINUE` entry (and `DC_RESUME=1` resumes for
  headless tests). `DC_SAVE_PATH`, `DC_NO_SAVE` and `DC_SAVE_FORCE` control it;
  deterministic `DC_RUN_FRAMES` runs never touch the disk.
- HUD health bar uses the extracted mask with dark/red tints (missing health is
  dark, current HP is red) instead of the previous flat white bar.
- Native password system: 10 letters carry stages, max HP, Crests/form, Urns,
  Spells and Talismans plus an 8-bit checksum, with an interactive entry screen
  (up/down letter, left/right move, Enter applies, invalid codes rejected).
  `DC_PASSWORD=<code>` applies a code at boot and `DC_PASSWORD_SELFTEST=1`
  runs 2000 round-trips for CI. The retail algorithm is still unknown.
- Per-species enemy sprites: `tools/oracle/capture_species.py` injects a minimal
  object record so the guest initialises and draws a chosen species in the
  current room (no area travel), and `tools/dc_extract/extract_species.py` bakes
  the object's OAM cluster into `enemy_<species>_<n>.png` + `species_anim.json`.
  **23 of the 25 species referenced by rooms now have their own art — 261 of 269
  placed objects (97%)** — most of it baked straight from the ROM: the species→
  metasprite mapping only exists in memory, so `tools/dc_extract/
  match_group_from_oam.py` recovers it by matching the guest's live OAM against
  `$8B:8000` frame signatures and `bake_rom_species.py` composes the result with
  `compose_rom_metasprite`. The object draw puts the metasprite origin ~19 px
  above the object position; the baker measures that per species. The two
  remaining ids are not sprite objects: `$01` platform and `$24` talisman (drawn
  at the player). The `$09` Hippogriff sheet is baked pose by pose with the
  VRAM/CGRAM of the frame that drew each pose (`bake_hippogriff.py`): the guest
  streams OBJ CHR per animation frame, so one capture only holds the tiles of
  the pose on screen.
- Windows build on the raylib Windows installer (`tools/build_windows.ps1`,
  `-DDC_RAYLIB_ROOT`), verified with raylib 6.2 + MinGW GCC 16.2.
- Campaign-specific debug hooks: `DC_AREA`, `DC_CAMPAIGN`, `DC_BOSS_DEFEATED`,
  `DC_BOSS_HP`, `DC_STATE`, `DC_NO_HDMA`, `DC_UNDERWATER`.
- Saved-state validation from `save0` (normal graveyard gameplay):
  - walk speed measured 1.40 px/frame,
  - default SNES bindings (`$80:DB00` via `$1E3A..$1E4C`): **B = Jump/Hover**,
    **Y = Fireball shot** (spawns in `$1080..$1260` via `$80:F222`), **A =
    Talisman/Headbutt** (`State 0x16` / `0x1A`), **X = Subscreen**,
  - B tap is an ~11 px / 14-frame hop; holding B gives the full jump arc,
  - 603-frame `DC_DEMO=6` replay (validated before the full-room terrain
    change): max delta `x=0.00 px`, `y=0.53 px`.
- Debug collision overlay (`F1` or `DC_DEBUG_COLLISION=1`), FPS (`F3`).

This is a playable campaign foundation, not a finished game. The next milestone
is content fidelity: per-species OAM/AI, BG2/mid-stage CHR, text/cutscenes,
exact password/save and ROM audio.

### Current limitations

- All 113 areas load, and **65 of them now have a real BG2 backdrop** baked from
  an oracle capture. The mapping from save states to extracted rooms is solved
  (`area = WRAM $008D / 2`, verified three ways in `docs/SAVE_TO_AREA.md`); the
  remaining rooms have no verified save yet, so their BG2 stays transparent
  until one is captured (the layer is generated by the guest at runtime, not
  stored in the ROM block tables).
- A handful of rooms (notably areas 43, 42, 30 and 29) still render mostly
  black: the BG1 extraction only fills the screens the reference capture covers,
  and their atlases are complete, so the fix is a capture-based BG1 rebake, not
  new art.
- BG2 parallax now uses the recovered `$84:AF65` HDMA bands in Area 1; other
  areas still need their own scanline tables.
- Six Gargoyle forms are implemented with movement/abilities and palette tints,
  but real per-form OAM sheets and animations are still needed.
- Per-species enemy AI is ported for the `$67` ghoul only; skeletons, bats and
  gargoyles still run the generic patrol/chase until their `$82:8300` handlers
  are ported. Their sprites are baked per species now. Note that species `$10`
  and `$81` are NPC/prop species, not enemies.
- The `$1070` probe is wired (`attr & 0xE0 == 0x80`) and selects the
  `0x00B3 → 0x0166` ramp, but exact per-shape oracle comparison remains.
- Hurt/death player animations are still missing. The `$67` ghoul now runs its
  ROM handler (`$83:AF74`), but its `$80F81D` animation streams are still mapped
  onto the baked poses and the pacing tables are not byte-for-byte
  (`docs/GHOUL_AI.md`). HUD icons remain approximations.
- No audio from the original ROM yet; the current music/SFX are original
  procedural development placeholders.
- Text/dialogue/cutscenes and the exact retail password algorithm are stubs;
  the clear/password/ending screens are functional but minimal, and the
  password codec is a native checksummed format rather than the retail code.
  Native save persistence (above) is in place, but it is not the retail SRAM
  format.
- The HUD health bar is scaled from the extracted six-point bar and highlights
  the active Crest form; the exact retail talisman-slot icons are not done.

## Requirements

- CMake 3.20+
- A C11 compiler
- Python 3 with Pillow
- Demon's Crest (USA), SHA-256
  `18d40a807d5f88c5b6a1ad849eec7e0f189225d9a1586037c850f6680b5844de`

- raylib is fetched automatically at configure time. Set `-DDC_RAYLIB_ROOT` to
  use a local raylib install instead (required for the offline Windows build).
  On Fedora the desktop build also needs the X11/GL development headers:

```sh
sudo dnf install libXrandr-devel libXinerama-devel libXcursor-devel \
  libXi-devel libX11-devel mesa-libGL-devel alsa-lib-devel
```

## 1. Capture a reference frame

Use the recompilation project's trace build. The `gameplay.script` route reaches
the first playable area at frame 43659 and dumps the machine 600 frames later.

```sh
RECOMP_DIR=/path/to/DemonsCrestSNESRecomp \
ROM="/path/to/Demon's Crest (USA).sfc" \
./tools/capture_graveyard.sh
```

Or run it by hand:

```sh
cd /path/to/DemonsCrestSNESRecomp
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
SNESRECOMP_DUMP_DIR=/path/to/DemonsCrestNativePort/captures/graveyard \
./build-trace/DemonsCrestSNESRecomp "/path/to/Demon's Crest (USA).sfc" \
  --script scripts/routes/gameplay.script
```

Copy/rename the four files the extractor needs:

```text
captures/graveyard/stage_600.vram.bin
captures/graveyard/stage_600.cgram.bin
captures/graveyard/stage_600.oam.bin
captures/graveyard/stage_600.regs.json
```

The `dump` command writes the framebuffer too; it is useful for visual
comparison but the extractor does not need it.

## 2. Extract assets

```sh
python3 tools/dc_extract/extract.py \
  --rom "/path/to/Demon's Crest (USA).sfc" \
  --dump captures/graveyard \
  --prefix stage_600 \
  --area 1 \
  --screens 9,10 \
  --full-room \
  --out assets/generated
```

`--full-room` builds every screen in the captured 8-screen row (2048×256 px
for Area 1) from the ROM block tables; omit it for the old two-screen
256×224 viewport slice.

Per-area BG2 backdrops come from an optional manifest,
`tools/dc_extract/bg2_captures.json`:

```json
{"areas": {"3": {"dir": "captures/anim", "frame": 20614}}}
```

Each entry points at a `capture_anim.py` frame (its `.json` + `.vram.bin`).
The extractor copies that frame's BG2 tilemap into the room document, keeps the
original BG2-vs-BG1 scroll offset, and bakes the area's BG atlases from the
capture's VRAM/CGRAM so streamed tiles are covered. Use `--bg2-map <path>` to
point at another manifest, or `--bg2-map` at an empty file to disable it.

Outputs:

- `room.json` — full-row BG1 tilemap, looping BG2 backdrop, slope collision
  grid, spawn, camera/play bounds.
- `room_area<N>.json` — one 2D room document per valid ROM area (113 areas),
  with spawns, transitions, boss gate and object list.
- `bg_area<N>_pal<P>.png` — per-area BG atlases baked from ROM CHR/palettes
  (palettes used by that area only).
- `bg_pal0..7.png` — 4bpp BG tile atlases for the captured Area 1 frame.
- `obj_pal0..7.png` — 4bpp OBJ tile atlases.
- `player_idle.png` — Firebrand composed from OAM.
- `item_00.png` — the visible item composed from OAM.
- `heart_00..01.png` / `enemy_00..01.png` — real ROM metasprite item and ghoul.
- `campaign.json` — area list, Gargoyle palettes and Area 1 HDMA bands.
- `manifest.json` — ROM identity and capture provenance.

A full extractor run writes about 57 MB and takes roughly a minute. The
generated directory is git-ignored and never distributed.

## 2b. Capture and extract Firebrand animations

The trace build exposes a 6000-frame per-frame state ring plus a TCP debug
server. `capture_anim.py` starts it paused, resumes a copy of `save0.sav`, and
drives absolute frame targets with held buttons. It then saves OAM, CGRAM,
registers and VRAM for each frame.

```sh
python3 tools/oracle/capture_anim.py \
  --recomp /path/to/DemonsCrestSNESRecomp \
  --rom "/path/to/Demon's Crest (USA).sfc" \
  --save /path/to/DemonsCrestSNESRecomp/saves/save0.sav \
  --out captures/anim

python3 tools/dc_extract/extract_anim.py \
  --dump captures/anim \
  --out assets/generated \
  --clean
```

This writes `player_idle_0.png`, `player_walk_0..5.png`,
`player_jump_0..2.png`, `player_hover_0.png`, `player_fall_0..1.png`,
`player_land_0..1.png`, `player_attack_0..2.png`, `player_spell_0..2.png`,
`fireball_0..8.png`, `hud_bar.png`, `hud_slots.png`, `player_anim.json` and
`fireball_anim.json`. The real item/Crest and ghoul PNGs
(`heart_00..01.png`, `enemy_00..01.png`) are baked by `extract.py` from ROM
CHR/OAM.
The engine falls back to `player_idle.png` if the player JSON is absent, and
skips the HUD if `hud_bar.png`/`hud_slots.png` are absent.

## 2c. Validate Step 3 movement against `save0`

```sh
python3 tools/oracle/capture_anim.py \
  --recomp /path/to/DemonsCrestSNESRecomp \
  --rom "/path/to/Demon's Crest (USA).sfc" \
  --save /path/to/DemonsCrestSNESRecomp/saves/save0.sav \
  --segments tools/oracle/segments_save0_physics.json \
  --out captures/phys

python3 tools/oracle/export_capture_csv.py captures/phys -o /tmp/oracle_phys.csv

DC_DEMO=6 DC_RUN_FRAMES=603 DC_TRACE_CSV=/tmp/native_demo6.csv \
  ./build/demonscrest   # xvfb-run -a when headless

python3 tools/oracle/compare.py /tmp/native_demo6.csv /tmp/oracle_phys.csv \
  --oracle-start 0 --threshold 1.0
```

Expected: 603 frames compared, max delta `x=0.00 px`, `y=0.53 px`.

## 3. Build and run

Linux/macOS (raylib fetched by CMake):

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/demonscrest
```

Windows (MinGW + the raylib Windows installer, offline):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1
# or point CMake at any raylib tree with a prebuilt libraylib.a:
cmake -S . -B build -G "MinGW Makefiles" -DDC_RAYLIB_ROOT=C:\raylib\raylib
cmake --build build
build\demonscrest.exe --assets assets\generated
```

`-DDC_RAYLIB_ROOT` skips the `FetchContent` download and links the local
`libraylib.a`; the script defaults to `C:\raylib\raylib` and builds serially
because some Windows shells restrict the jobserver named pipe used by
make/ninja.

Use `--assets <dir>` to load assets from another directory.

## Regenerating assets

`assets/generated/` and `captures/` are ROM-derived and git-ignored, so a fresh
clone needs one extraction pass (ROM required, no assets are redistributed):

```powershell
# 1. Base extraction from the ROM + a gameplay capture set
python tools/dc_extract/extract.py --rom "<rom>" --dump captures\graveyard `
    --prefix stage_600 --area 1 --screens 9,10 --full-room --out assets\generated

# 2. Optional: extra areas / shop / map from recomp save states
python tools/oracle/capture_save_frames.py --save 7  --out captures\save7  --frames 0,20
python tools/oracle/capture_save_frames.py --save 8  --out captures\save8  --frames 0,20
python tools/oracle/capture_save_frames.py --save 9  --out captures\save9  --frames 0,20
python tools/oracle/capture_save_frames.py --save 10 --out captures\save10 --frames 0,20
python tools/dc_extract/build_world_map.py --capture captures\save11 --frame 61
python tools/dc_extract/build_endings.py

# 3. Verify
python tools/run_regression.py --binary build\demonscrest --assets assets\generated
```

`tools/dc_extract/bg2_captures.json` lists which areas have captured backdrops
(2, 3, 48, 58, 74); drop new `captures/saveN` frames there to dress more rooms.

## Status & verification

The port is playable from the title screen through the campaign loop to the
endings. A full sweep before each release:

| Check | Command | Current result |
|---|---|---|
| Regression suite | `python tools/run_regression.py --binary ... --assets ...` | **PASS** (demos 6/7/9/10/11/12/13, boss data/runtime, Hippogriff fight, boss clears, area subset, playthrough, endings, save/password) |
| All rooms load | `python tools/check_areas.py --binary ... --assets ...` | **113/113 ok** |
| Boss stage clears | `python tools/check_campaign.py --binary ... --assets ...` | **11 boss entries clear** (55 rooms have no boss) |
| Campaign flow | `python tools/check_playthrough.py --binary ... --assets ...` | **6/6 steps** (title → clear → map → stage travel → boss clear → ending) |

Known fidelity gaps (tracked in `docs/PROJECT_STATE.md`): many enemies still run
a generic patrol/chase rather than their `$82:8300` handler, most areas have no
captured BG2 backdrop, the overworld is a camera-rotated baked texture rather
than the original Mode 7 plane, and audio is a replacement soundtrack rather
than ROM BRR/DSP data.

## Controls

| Action | Keyboard | Gamepad | Original SNES (`$80:DB00`) |
|---|---|---|---|
| Move | Arrows / WASD | D-pad | D-pad |
| Jump / hover | Z or Space | B (right face) | **B** (`$1E3A`) |
| Fly upward (debug only) | Z + Up | B + Up | Crest-dependent |
| Fireball shot | X or J | X / Y (west/top) | **Y** (`$1E3C`) |
| Talisman / Headbutt / Earth dash | C or K | A (south) | **A** (`$1E3E`) |
| Crest/Item subscreen | Tab or I | — | **X** (`$1E4C`) |
| Cycle Gargoyle form | Q / E | L / R | — |
| Start / confirm | Enter | Start | Start |
| Pause / resume | Escape | Back | Start |
| Collision overlay | F1 | — | — |
| FPS | F3 | — | — |

## Development hooks

These environment variables exist for deterministic testing:

| Variable | Effect |
|---|---|
| `DC_RUN_FRAMES=N` | Run N updates then exit (used for screenshots) |
| `DC_SCREENSHOT=name.png` | Save the last presented frame (raylib writes it in the working directory) |
| `DC_TRACE_CSV=path` | Write per-frame player/camera state as CSV |
| `DC_DEMO=1` | Walk right, jump, then fly (long demo) |
| `DC_DEMO=2` | Walk right into the pillar, jump and land (short demo) |
| `DC_DEMO=3` | Mirrors the physics probe timing |
| `DC_DEMO=4` | Tap-jump vs hold-jump comparison |
| `DC_DEMO=5` | Animation regression: walk, special, jump, fly |
| `DC_DEMO=6` | Exact `save0` Step 3 physics replay (603 frames) |
| `DC_DEMO=7` | Fireball demo: right shots into the pillar, long left shot |
| `DC_DEMO=8` | Full-room traversal: walk left, then hover right across pillars |
| `DC_DEMO=9` | Urn → bouncing heart → heal regression |
| `DC_DEMO=10` | Enemy chase/damage/drop regression (pair with `DC_START_X`) |
| `DC_DEMO=11` | Crest-form cycle, Earth dash, Air flight, Aerial shots |
| `DC_DEMO=12` | Campaign traversal and boss-gate flow |
| `DC_DEMO=13` | Title → NEW GAME → Area 0 flow |
| `DC_START_X` / `DC_START_Y` | Override the player spawn for focused tests |
| `DC_TRACE_OBJECTS=path` | Write active object slots as CSV |
| `DC_TRACE_PROJECTILES=path` | Write per-frame active projectile slots as CSV |
| `DC_FLY_DEBUG=1` | Enable the non-canonical B+Up vertical flight |
| `DC_TITLE=1` | Force the title screen even with `DC_RUN_FRAMES` |
| `DC_NO_AUDIO=1` | Disable audio device/music/SFX |
| `DC_AUDIO_DEBUG=1` | Print audio device/music status |
| `DC_AUDIO_FORCE=1` | Allow audio in deterministic `DC_RUN_FRAMES` runs |
| `DC_DEBUG_COLLISION=1` | Enable the `F1` collision overlay in headless runs |
| `DC_LAYER_MASK=1\|2\|3` | Draw BG2 only / BG1 only / both |
| `DC_AREA=N` | Load `room_areaN.json` instead of `room.json` |
| `DC_CAMPAIGN=1` | Enable campaign transitions/overworld progression |
| `DC_STATE=name` | Render a menu state (`title`, `overworld`, `subscreen`, `shop`, `password`, `options`, `clear`, `gameover`, `ending`) |
| `DC_BOSS_DEFEATED=1` | Skip boss spawns for campaign flow tests |
| `DC_BOSS_HP=N` | Override boss HP |
| `DC_GOLD=N` | Starting gold for shop/subscreen testing |
| `DC_POTIONS=N` / `DC_SCROLLS=N` | Starting Urn/Spell counts |
| `DC_UNLOCK_ALL=1` | Unlock all six Gargoyle forms |
| `DC_NO_HDMA=1` | Disable the BG2 scanline parallax bands |
| `DC_UNDERWATER=1` | Force underwater physics |
| `DC_WINDOW_INFO=1` | Print window/render-target size and integer scale once per frame |
| `DC_SAVE_PATH=path` | Native save file (default `saves/dc_save.json`) |
| `DC_NO_SAVE=1` | Disable save loading/writing |
| `DC_SAVE_FORCE=1` | Allow saving inside deterministic `DC_RUN_FRAMES` runs |
| `DC_RESUME=1` | Boot straight into the saved run instead of the title |
| `DC_PASSWORD=<code>` | Apply a native 10-letter password at boot |
| `DC_PASSWORD_SELFTEST=1` | Run password codec round-trips and exit (CI) |
| `DC_NO_STORY=1` | Skip the crest/item story beats |
| `DC_ENDING=bad\|normal\|good\|true` | Preview an ending variant |
| `DC_TALK=<step>` | Preview the city NPC conversation page |
| `DC_STORY_TEST=<crest>` / `DC_STORY_PAGE=n` | Open a story page directly |
| `DC_FIRE_TEST=<1..4>` | Open a fire-crest piece page directly |
| `DC_LAYER_MASK=<bits>` | Draw only selected BG layers (1 = BG2, 2 = BG1) |
| `python tools/dc_extract/build_world_map.py ...` | Bake the Mode 7 world map from a capture |
| `DC_BG2_MERGE_FRAMES=<n>` | Frames merged when baking a captured BG2 atlas |
| `SNESRECOMP_LAYER_MASK` | On the recomp side, isolate BG/OBJ layers for comparison |

Example:

```sh
DC_DEMO=2 DC_RUN_FRAMES=120 DC_TRACE_CSV=/tmp/native.csv ./build/demonscrest
```

### Regression test

After building and extracting assets:

```sh
./tools/run_regression.sh
# or
cd build && ctest --output-on-failure
```

The harness runs the deterministic demos through `DC_RUN_FRAMES`, writes trace
CSVs, and asserts known movement, fireball, pickup, enemy, HP, Crest-form and
campaign-transition invariants. It also boots every boss room (`check_bosses`),
the species `$67` ghoul state machine and the Area 1 Hippogriff fight (spawn,
260-frame stone phase, kill and the gate to Area 2), plus the console's
28+64+28-frame room fade. Save/options persistence is checked twice: one run
autosaves (with `DC_SAVE_FORCE`), a second run resumes it and the trace must
report the same area, max HP and gold. The password codec is exercised twice:
the binary self-test, and a Python-generated code applied via `DC_PASSWORD`
must restore max HP and form. On Linux the runner re-executes itself under
`xvfb-run` when no display is set. It exits with code 77 (CTest skip) when the
binary or generated assets are missing.

### Campaign audit

`tools/audit_campaign.py` checks every generated room document without running
the game: world/collision/BG dimensions, BG1 and collision coverage, BG2
presence, spawn support, object bounds and transition/gate targets. Rooms are
classified as `playable`, `partial` or `empty`.

```sh
python3 tools/audit_campaign.py
python3 tools/audit_campaign.py --strict --json /tmp/campaign_audit.json
```

`--strict` exits non-zero when a playable room breaks a structural invariant, so
it can gate CI alongside the regression suite.

## Layout

```
src/                  native engine
src/anim.c            player_anim.json / fireball_anim.json loaders
src/projectile.c      7-slot fireball pool
src/object.c          26-slot urn/enemy/pickup pool
src/audio.c           procedural music/SFX
tools/dc_extract/     extraction from ROM + dump (room and animation frames)
tools/dc_extract/bg2_captures.json  area -> oracle frame map for BG2 backdrops
tools/dc_extract/extract_species.py per-species sprite baking from injected
                                    object captures
tools/dc_extract/bake_hippogriff.py  per-pose bake for species $09 (VRAM at
                                    the frame that drew each pose)
tools/oracle/capture_species.py     injected-object species capture
tools/audit_campaign.py             per-room structural audit
tools/build_windows.ps1             offline MinGW build against local raylib
tools/capture_graveyard.sh  recomp dump helper
tools/oracle/         WRAM/OAM trace parsers, probe routes, comparison and
                      debug-server animation capture
captures/             per-run recomp dumps (git-ignored)
assets/generated/     extracted assets (git-ignored)
docs/PLAN_FULL_PLAYABLE.md plan to make the original fully playable (milestones M1-M9)
docs/PROJECT_STATE.md full handoff: state, findings, traps, next steps
docs/FULL_CAMPAIGN_PLAN.md full-campaign remaining-work plan
docs/ROADMAP.md       next milestones
```

The larger feasibility study is in the recompilation repository at
`docs/NATIVE_PORT_PLAN.md`.

## Legal

The engine and tools are original code. The ROM, extracted graphics, maps,
music and any other game data remain the property of Capcom. Do not commit or
distribute the generated assets. For a public release, either require the
player's own ROM at generation time or replace the original art/music with
licensed or original assets.
