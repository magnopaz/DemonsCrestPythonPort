# Roadmap

Status: playable campaign foundation — all 113 areas extracted, multi-room
transitions, crest forms, boss/overworld/menu flow and per-area BG atlases are
in place; remaining work is content fidelity (per-species OAM, text, audio).
Per-area BG2 backdrops now come from oracle frames (Areas 1 and 3), the Windows
build works against a local raylib, and `tools/audit_campaign.py` audits every
generated room.

Full-campaign remaining work is tracked in
[`docs/FULL_CAMPAIGN_PLAN.md`](FULL_CAMPAIGN_PLAN.md).

## Done

- Standalone CMake + C11 + raylib project.
- ROM verification, the native CHR decompressor, and extraction of all 113
  valid areas from the ROM block tables.
- 256×224 render target, integer scaling, 60 Hz update.
- BG1/BG2 tilemaps with per-palette flip atlases.
- OAM-composed player and item sprites.
- Walk, jump, hover, fireball shot, first-pass collision and viewport bounds.
- Deterministic demo input for screenshots (`DC_DEMO=1|2|5|6|7|8|9|10|11|12|13`).
- Debug collision overlay (`F1`), FPS (`F3`).
- Animation capture through the recomp debug server's state ring.
- Firebrand animation frames: static idle, 6-pose walk cycle, jump rise,
  hover, fall, landing, Y fireball spit and A spell. Frame-based animation
  state machine.
- Attack and landing timers; fly/jump state flicker fixed.
- Authentic Bank `$80` player state machine ported to 8.8 fixed point
  (`src/player.c`): grounded, jump takeoff substates, B-release jump cut,
  gravity, terminal fall, hover toggle and SNES Y/A input mapping.
- Movement validated against `save0`: 603-frame trace, max delta
  `x=0.00 px`, `y=0.53 px` (`DC_DEMO=6`).
- Fireball projectile pool (`src/projectile.c`): 7 slots, original spawn
  offset/velocity, palette-6 OAM extraction, pillar and screen-edge despawn.
- Full 2048×256 Area 1 room from the populated ROM screen row (`--full-room`),
  with a 128×16 collision grid and horizontally looping BG2.
- `$80:962B` slope-surface table: Firebrand walks up/down `0x03..0x14` slopes
  and spawns at `y=164` on `attr=0x09`.
- Camera deadzone scrolling across the full room; `DC_DEMO=8` exercises it.
- 26-slot object pool (`src/object.c`) with data-driven Area 1 object list:
  destructible urns (`species $57`), bouncing hearts (`$85:C180` arc) and a
  first-pass species `$67` ghoul that chases, damages and drops hearts.
- BG3 status bar extracted from `save0`: health bar + three crest slots, wired
  to `$1062`/`$1E50` HP and drawn at the top of the frame.
- Fixed 60 Hz simulation accumulator decoupled from display refresh;
  `DC_RUN_FRAMES` remains deterministic one-update-per-loop.
- Pre-baked horizontal player/fireball textures (no negative-source flips).
- `tools/run_regression.py` + `tools/run_regression.sh` + CTest exercise
  demos 6, 7, 9, 10, 11 and 12 and assert physics, projectile, pickup, enemy, Crest cycling and campaign transitions
  invariants.
- Original procedural audio: looping chiptune theme plus jump/land/shoot/break/
  pickup/hurt/enemy-hit SFX; no ROM audio data.
- **ROM music (2026-11-02)**: the colosseum theme (area 0) is the game's own
  audio, captured from the oracle's S-DSP output and played through
  `LoadMusicStream` as `assets/generated/audio/music_boss.wav` — 32,040 Hz
  stereo, measured loop period 40.941 s, seam 0.51× a typical sample step (so
  no click), verified to wrap in raylib (`t=40.875 → 0.553`) and to leave
  `DC_NO_AUDIO=1` byte-identical. `src/audio.c` keeps the procedural tracks as
  a fallback when the assets are absent. The pipeline is
  `tools/audio/{dump_spc,capture_music,make_music_asset}.py` +
  `tools/audio/wav_loop.c`, specs in `tools/audio/music_tracks.json`, checks in
  `tools/check_audio_assets.py` (inside `run_regression.py`).
  A bare `.spc` does **not** resume this driver (it plays ~2 s then halts on a
  `STOP` executed from data); the evidence is in `docs/AUDIO_PLAN.md`.
  **Still procedural:** the seven SFX, and one track per game state rather than
  per area.
- Title / Playing / Paused / Area Clear flow with an exit trigger from the
  Area 1 object list (`species $09`, x=1920).
- Full-campaign foundation:
  - native ROM CHR decompressor (`$80:C2AF`/`$80:C300`) and `$98:C000`/
    `$98:D000` decoders in `tools/dc_extract/extract.py`;
  - all 113 valid areas emitted as `room_area<N>.json` with 2D multi-row/
    vertical grids, collision, spawns (`$81:A1A9`), transitions
    (`$81:981A`) and object lists (`$81:C874`);
  - per-area BG atlases from ROM CHR + ROM palettes, loaded on demand;
  - OAM metasprite decoder (`$8B:8000` via `$80:D9A7`) with real ROM
    heart/Crest pickup and ghoul sprites;
  - BG2 HDMA scanline parallax from `$84:AF65` (32/44/28/46/74-line bands);
  - multi-room `Level_LoadArea`/`Game_TransitionToArea`, boss-gated
    `$81:97DA` exits, and all 113 rooms loadable;
  - Area 0 Somulo boss with HP bar, skeleton/bat/gargoyle enemies, moving
    platforms, crest/life-stone pickups, gold, hazards, water and breakable
    terrain;
  - six Gargoyle forms with Earth/Ultimate dash, Air flight, Water swim,
    Time/Ultimate damage reduction, Fire-Crest elements, wall cling and
    overhead headbutt;
  - Crest/Item subscreen (`Tab`/`X`), shop, generated password, options,
    game over, ending, and a Mode 7-style overworld with six landing nodes.

## Campaign foundation (this session)

- `dc_extract` regenerates 113 area rooms + per-area atlases from the ROM in
  about 65 s; generated output is ~57 MB and stays git-ignored.
- `DC_AREA=N` loads a specific campaign room; `DC_CAMPAIGN=1` enables
  transitions; `DC_BOSS_DEFEATED=1` skips bosses for flow tests; `DC_STATE=`
  renders each menu; `DC_NO_HDMA=1` disables scanline parallax.
- `tools/run_regression.py` now also covers demo 11 (Crest cycling), demo 12
  (Area 0 → Area 17 gate) and direct Area 2/3 loads.

## Physics constants and Bank `$80` state machine recovered

Disassembly of Bank `$80` (`$80:DB00..F310`) recovered Firebrand's true state
machine and fixed-point constants (note: `$85:C1D4` was proved to be the
bouncing heart pickup routine, not Firebrand's jump):

| Value | Original (`$80:DB00..F310`) | Ported `src/player.c` |
|---|---|---|
| initial walk step | `$1020 = 0x00B3` (`$80:F0BE`) → 0.6992 px/frame | `PLAYER_WALK_INITIAL_FX`; slope path, awaiting the `$1070` probe |
| max walk speed | `$1020 = 0x0166` (`$80:F0D0`) → 1.3984 px/frame | exact `0x0166` Q8.8; flat ground keeps the cap (matches `save0`) |
| jump velocity | `$1022 = 0x059C` (`$80:E170`) → 5.6094 px/frame | `-0x059C` y-down; substates 0→2→4 before integration |
| variable jump cut | `$80:E227`: if rising (`$23 >= 0`) and B released (`$59 == 0`), `$22 = 0` | `vy_fx = 0` on the first substate-4 frame with B released |
| gravity | `$1026 = 0x0038` (`$80:E070`, `$80:ED11`) → 0.21875 px/frame² | exact `0x0038` Q8.8 |
| hover (`State 0x06`) | `$80:E1A3` / `$80:E29F`: B in air zeroes `$22 = 0`, bypasses gravity | `PLAYER_HOVER`, `vy_fx = 0`; B press enters/exits (`State 0x04`/`0x04`) |
| terminal fall | `0xFA00` (`$80:8D03`) → -6.0 px/frame | exact `0x0600` y-down |

Pad mapping at `$80:DB00..DB40` (via WRAM masks `$1E3A..$1E4C`) and `save0`:

- **B** (`$1E3A` → `$1059`/`$105A`) = Jump / Hover toggle;
- **Y** (`$1E3C` → `$105B`/`$105C`) = Fireball shot (spawns projectile via `$80:F222`);
- **A** (`$1E3E` → `$105D`/`$105E`) = Talisman/Spell (`State 0x16`) or Headbutt (`State 0x1A`);
- **X** (`$1E4C` → `$80:DC12`) = Item/Crest subscreen;
- In `save0`, world X moves 14 px in 10 frames (1.40 px/frame) and a B tap lifts
  the feet ~11 px over ~14 frames (`0x059C` initial velocity cut to `0` on B
  release under `0x0038` gravity).

## Measurement tooling (done)

1. **Native trace output**
   - `DC_TRACE_CSV=path` writes
     `frame, x, y, vx, vy, state, camera_x, camera_y`.

2. **Recomp oracle trace**
   - `save0` (ROM Area 3, `screens 52, 53`) is a clean normal-gameplay state;
     the `stage_600` landing route (ROM Area 1, `screens 8, 9`) is a cinematic
     and must not be used for physics probes.
   - OAM traces are the reliable visual position source; the `$1000` task Y
     oscillates during idle.
   - The debug server's 6000-frame state ring drives deterministic animation
     capture (`tools/oracle/capture_anim.py`).

3. **Diff harness**
   - `tools/oracle/compare.py` aligns the two CSVs and reports the first
     divergent frame.
   - Acceptance remains: ≤1 px / 1 frame divergence over 600 frames.
   - `tools/oracle/export_capture_csv.py` turns a `capture_anim.py` directory
     into the oracle CSV shape; `tools/oracle/segments_save0_physics.json` is
     the repeatable walk/tap-jump/hold-jump/hover route.
   - Latest Step 3 result: 603 frames, max delta `x=0.00 px`, `y=0.53 px`.

## Campaign fidelity pass (2026-10-23 continuation)

- **Per-area BG2 backdrops from oracle frames.** `extract.py` reads
  `tools/dc_extract/bg2_captures.json` (`area -> {dir, frame}`), copies that
  `capture_anim.py` frame's BG2 tilemap into the room document with the original
  BG2-vs-BG1 scroll offset, and bakes the area's BG atlases from the capture's
  VRAM/CGRAM. Areas 1 (`stage_600`) and 3 (`save0`, frame 20614) now show their
  real backdrops (Area 3 renders the mountain/ruins view instead of black).
- **BG2 is generated by the guest.** `$84:A057` DMAs the tilemap to VRAM
  `$4000` from WRAM bank `$7F`, using `$84:C311`/`$84:C312` indexed by `$00F9`
  (static fallback: ROM `$81:8068`). There is no ROM tilemap table to extract;
  that is why the capture manifest exists.
- **Species dispatch mapped.** `$82:8000/$8180/$8300/$8480` are 192-entry
  tables indexed by `species*2`; init entries are 5-byte `JSL $83:xxxx; RTS`
  thunks (species `$67` → `$82:F382` → `$83:AF19`, update `$83:AF74`). This is
  the starting point for per-species OAM/AI.
- **WRAM `$008D` is not a room switch.** `$84:F0DA..F0EF` advances it by 2;
  writing it through the debug server (`write_ram 8d ...`) left VRAM identical
  over 120 frames. Per-area oracle captures must use the game's transition/script
  path.
- **Campaign audit.** `tools/audit_campaign.py` reports dimensions,
  BG1/collision coverage, BG2 presence, spawn support, object bounds and
  transition/gate targets for all 113 rooms: currently 69 playable, 44 partial,
  2 with BG2, 45 with at least one structural issue (mostly zero-collision
  boss/cutscene arenas). `--strict` is CI-ready.
- **Windows build.** CMake `-DDC_RAYLIB_ROOT` links a local `libraylib.a`;
  `tools/build_windows.ps1` builds against the raylib Windows installer and can
  run the game. Verified with raylib 6.2 + MinGW GCC 16.2; the regression suite
  passes with the regenerated assets. `DC_WINDOW_INFO=1` prints window/render
  target size and scale.

- **Save/options persistence.** `Game_SaveProgress`/`Game_LoadProgress`
  write a versioned JSON save (`saves/dc_save.json`, `DC_SAVE_PATH` override)
  holding area, cleared stages, HP, Crests/forms, Talismans, Fire element, Urns,
  Spells, gold and volume; autosave runs on area clear, overworld entry and
  exit. The title menu shows `CONTINUE` only when a save exists. Deterministic
  runs stay disk-free unless `DC_SAVE_FORCE=1`; `DC_RESUME=1` resumes headless.
  `run_regression.py` autosaves in one run and asserts area/max HP/gold after
  resuming in a second.
- **HUD health bar.** The baked `hud_bar.png` is a brightness mask, so the
  renderer now tints the empty part dark and the filled part red instead of
  drawing a flat white bar.
- **Native password codec.** Ten letters from `BCDFGHJKLMNPQRSTVWXYZ` encode a
  32-bit payload (stages, max HP, Crests/form, Urns, Spells, Talismans) plus an
  FNV-1a checksum; the screen supports letter entry, rejects invalid codes and
  restores progress. `DC_PASSWORD` applies a code at boot,
  `DC_PASSWORD_SELFTEST=1` runs 2000 round-trips, and the regression suite
  cross-checks a Python-generated code against the C decoder.
- **Text format cracked.** The script is plain ASCII (0x01 line break, 0x02
  page break, 0x5D page terminator) rendered through BG3 with tile index equal
  to the ASCII code. extract_text.py produces 	ext_strings.json (518
  strings) and capture_menu.py + extract_font.py bake the BG3 ASCII font
  into ont.png. A renderer and dialogue state are the next step.
- **Ghoul handler start.** `src/object.c` now runs the authentic state-0 drop
  from `$83:AF74` (lift Y 9, vx `0x50`, vy `0x398`, gravity `0x40`, 3-frame
  windup, 6-frame landing) before the placeholder chase, and `$B2E8`/`$B298`/
  `$B2B1`/`$B2C7` are decoded in the docs. States 1–4 and the `$DEA2` random
  behaviour dispatch remain.
- **Per-species sprites from injected objects.** capture_species.py writes a
  minimal object record (`$00 = 1`, species, position) into the first slot so
  the guest runs that species' init and draws it in the current room; no area
  travel is needed. `extract_species.py` isolates the object's OAM cluster
  (world→screen offset derived from the player's feet anchor), composes it with
  the captured CGRAM and emits `enemy_<species>_<n>.png` + `species_anim.json`,
  which `src/assets.c`/`src/render.c` now use per species. Urn `$57`, pickup
  `$49`, `$2D` and the ghoul `$67` bake correctly; species whose init expects
  spawner-supplied fields still draw the player sheet and are rejected
  automatically.
- **`$81:AE11` ruled out as the species sprite map.** Cross-area constraint
  testing (666 area pairs) shows 55% contradictions, so that table is the
  room's ambient animation list. The object fields `$28/$2A/$2E` are also not
  sprite pointers: `$2A` is a map/offset table base used by the collision probe
  at `$80:91C7`. Per-species art therefore comes from the injected-object
  capture above, not from a single ROM table found so far.

## Next (ordered by dependency)

1. **Content fidelity**
   - Bake per-species OAM groups. The init thunks store three `$8B`-bank frame
     pointers in object fields `$28/$2A/$2E` (species `$67` →
     `$DE87/$DE7B/$DE6C`), so decoding bank `$8B`'s data block and the CHR
     base/palette is the shortest path to real enemy sprites
     (skeletons, bats, wall gargoyles, Somulo, Phalanx, Dark Demon).
   - Add one `capture_anim.py` frame per remaining area to
     `tools/dc_extract/bg2_captures.json`, and extract `$98:E000` mid-stage CHR
     streaming plus tile animation; finish the per-area palettes.
   - Port the real species `$67` handler (`$83:AF74`) and the remaining
     `$82:8000` species table entries.
2. **Story and menus**
   - Text/dialogue/cutscene format from the ROM, town NPCs, shop dialogue,
     exact password decode and save persistence.
   - Multiple ending rules (Bad/Normal/True/Dark Demon) driven by crest and
     item collection.
3. **Audio & release**
   - ROM BRR/DSP/sequence extraction or a replacement soundtrack, plus
     music/SFX volume options.
   - Windows/macOS builds, packaging, and windows CI.

## Done recently

1. **Audio, title/pause/clear flow (Step 9, vertical-slice portion)**
   - `src/audio.c` synthesizes an original looping chiptune theme and seven
     gameplay SFX; it degrades silently without an audio device and is skipped
     for deterministic `DC_RUN_FRAMES` runs.
   - Game states Title / Playing / Paused / Clear. Enter/Start begins, Escape/
     Back pauses, and the object-list exit at x=1920 triggers Area Clear with
     restart.
   - `DC_TITLE`, `DC_NO_AUDIO`, `DC_AUDIO_DEBUG` and `DC_AUDIO_FORCE` expose
     the flow/audio paths for testing.

2. **Engine hardening & regression harness (Step 8)**
   - `main.c` now uses a fixed 60 Hz accumulator decoupled from display
     refresh; `DC_RUN_FRAMES` keeps one update per loop for deterministic
     captures.
   - Player and fireball animations load a pre-baked mirrored texture instead
     of relying on negative `DrawTexturePro` source widths.
   - `tools/run_regression.py` (also exposed as `tools/run_regression.sh` and
     CTest `regression`) runs demos 6/7/9/10/11/12 and asserts physics, projectile,
     pickup, enemy and HP invariants. `ctest` passes.
   - Remaining polish: real enemy/HUD art and audio.

3. **Object system, urn, heart pickup & HUD (Steps 6–7)**
   - `src/object.c` implements a 26-slot pool and loads the `$81:C874` object
     list for Area 1: four destructible urns (`species $57`) and four species
     `$67` enemies.
   - Urns shatter on fireball contact and drop a pickup with the `$85:C180`
     arc: initial 4.0 px/frame up, gravity 0.25, bounce decay 1.0 per landing.
     Touching it increments HP up to max.
   - The first-pass enemy emerges, chases within 220 px, damages on contact
     with knockback/invulnerability, dies to fireballs and drops a heart.
   - `extract_anim.py` bakes the save0 BG3 HUD (`hud_bar.png`,
     `hud_slots.png`); `render.c` draws the 6-point health bar, three crest
     slots and highlights the active spell slot.
   - `DC_DEMO=9` exercises urn → heart → heal; `DC_DEMO=10` with
     `DC_START_X` exercises enemy chase, damage and drop.

4. **Full-room Area 1 map, slopes & camera scrolling (Step 5)**
   - `extract.py --full-room` emits the populated 8-screen Area 1 row as a
     2048×256 BG1 map and a 128×16 collision grid. The ROM grid's second row is
     all-zero padding, so it is omitted and recorded in `manifest.json`.
   - All 492 referenced BG1 tiles are already in the `stage_600` VRAM atlas; no
     CHR decode or extra capture was required.
   - Decoded the `$80:962B` surface table (`0x03..0x14`) and added
     `Level_FloorAt`/`Level_SurfaceOffset`; spawn is `y=164` on `attr=0x09`
     and the `0x07..0x0e` hill is walkable both ways.
   - Unlocked camera bounds and added horizontal/vertical deadzones; BG2 loops
     horizontally. `DC_DEMO=8` walks left then hovers right across pillars.
   - Remaining polish: BG2 HDMA per-scanline parallax and the `$1070` walk-speed
     ramp are not wired yet.

5. **Y Fireball shot & projectile pool (Step 4)**
   - Captured `Y` in `save0`: the grounded shot animation is 17 frames
     (idle press frame + 6-frame pose A + 10-frame pose B), and the projectile
     spawns on the press frame in object slot `$1080`.
   - Recovered the spawn/velocity values: X = `floor(player.x) + 3`,
     Y = `floor(player.y) - 8`, horizontal velocity `0x0300` (3.0 px/frame).
   - `extract_anim.py` now separates the palette-6 projectile OAM group from
     the palette-7 player body, emits `fireball_0..8.png` +
     `fireball_anim.json`, and exports the real `Y` clip as `attack` while
     keeping the `A` clip as `spell`.
   - `src/projectile.c` implements the 7-slot pool (`$1080..$1260`, stride
     `$50`); shots despawn on the stone pillar or when they leave the camera
     viewport. `DC_DEMO=7` exercises right shots into the pillar and a
     long left-facing shot; `DC_TRACE_PROJECTILES=path` logs every active slot.

6. **Bank `$80` player state machine ported (Step 3)**
   - `src/player.c` now stores positions, velocities and walk speed as 8.8
     fixed point and follows the recovered grounded / jump-substate / hover
     flow (`$80:E0EE`, `$80:E1DA`, `$80:E29F`).
   - Jump takeoff holds position on the press frame, integrates through
     substates 0→2→4, then applies the `$80:E227` B-release cut on the first
     substate-4 frame.
   - Hover is `State 0x06`: B in air zeroes `vy`, freezes vertical motion and
     bypasses gravity; the next B press returns to `State 0x04` and falls.
   - `Y`/`X`/`J` (gamepad west/top) trigger the Fireball shot input; `A`/`C`/
     `K` (gamepad south) remain Talisman/Headbutt. Step 4 later replaced the
     placeholder shot clip with the captured Y animation.
   - `save0` validation via `DC_DEMO=6` and
     `tools/oracle/segments_save0_physics.json`: 603 frames, max delta
     `x=0.00 px`, `y=0.53 px` (threshold 1 px). The residual Y delta is the
     known `$1000` task-idle oscillation, not a physics divergence.

7. **Graveyard Area 1 extraction & collision alignment**
   - Updated `tools/dc_extract/extract.py` default `--area` to `1` (`screens 8,
     9` = `slots 9, 10`) and regenerated `assets/generated/room.json`.
   - Masked block collision shapes by `attr & 0x1F` (`$80:8FDB`) so `0xA0`
     environment blocks are ignored as air.
   - Fixed `Player_Init` ground snapping (`y=160` instead of `y=176`) and fixed
     `land_timer` so it only triggers on airborne-to-grounded transitions.
   - Verified stone pillar (`cx=24`, `x=384..399`, `y=128..159`) and floor
     (`by=10`, `y=160..175`) alignment in `physics_check.png`.

8. **Animation extraction**
   - Captured OAM/VRAM/CGRAM per frame through the debug-server state ring.
   - Extracted idle, 6-pose walk, jump rise, hover/fly, fall, landing, Y shot,
     A spell and fireball clips with per-frame anchors and frame durations.
   - Added `src/anim.c` and a frame-based animation state machine.

## Guardrails

- Never commit `assets/generated/` or `captures/`; they are ROM-derived.
- Do not tune physics by feel when a trace can answer the question.
- Keep the engine frame-based and deterministic; no float delta time in logic.
- One routine at a time: port, trace, compare, then move on.
