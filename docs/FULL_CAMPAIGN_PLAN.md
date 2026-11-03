# Full Campaign Plan — Remaining Work

Last updated: 2026-10-23
Scope: making the **entire original Demon's Crest campaign** playable in the
native fan port, then adding the expanded pre/post-story content.

This is the gap analysis and ordered work plan. `docs/PROJECT_STATE.md` remains
the authoritative technical handoff; this file tracks what is still missing for
a full campaign.

---

## 1. Final target

1. A standalone native game that can start from a cold boot, run the original
   campaign from title/intro through every stage, boss and ending, and expose
   all player forms, items and menus.
2. No emulator and no recompiled 65816 runtime in the shipped game.
3. ROM-derived data generated locally from the player's own ROM.
4. After the original campaign is stable: expanded story content before/after
   the original events, using the same data-driven engine.

The current build is a **vertical slice**, not a full port.

---

## 2. Current state snapshot

Implemented today:

| Area | Status |
|---|---|
| Native C11 + raylib engine | working |
| 256×224 render target, fixed 60 Hz accumulator | working |
| Area 1 populated screen row (2048×256) | extracted |
| BG1 from ROM block tables / looping BG2 (from VRAM dump) | working (Area 1 BG2; Area 3 BG2 from a save0 frame; other backdrops need a capture) |
| Slope surface table (`$80:962B`) and `$1070` ramp | working |
| Base Gargoyle movement, jump, hover, shot, spell | working |
| 7-slot fireball pool (`$1080..$1260`) and palette-6 animation | working |
| 26-slot object pool (`$1080..$1D50` layout) | working |
| Area 1 object list (`$81:C874`: urns, `$67` ghouls, `$09` exit) | parsed |
| Urns (`$57`), `$85:C180` heart pickup, first-pass `$67` ghoul | working (heart/ghoul art now ROM OAM; `$67` AI still first-pass) |
| BG3 HUD (health bar + crest slots from `save0`) | working (active slot follows the current Crest form) |
| Procedural chiptune + SFX | working (development placeholder) |
| Title / Playing / Paused / Area Clear (`species $09`, x=1920) | working |
| Deterministic regression (`ctest` / demos 6, 7, 9, 10, 11, 12) | working |
| All 113 valid ROM areas extracted to `room_area<N>.json` | working |
| Multi-row/vertical room loader, transitions and boss gates | working |
| Per-area BG atlases from ROM CHR/palettes | working (BG2 backdrops beyond Area 1 pending) |
| BG2 HDMA scanline parallax (`$84:AF65`) | working for Area 1 |
| Six Gargoyle forms + Fire-Crest elements + wall cling/headbutt | working (form art is tinted base sheet) |
| Area 0 Somulo boss, skeletons/bats/gargoyles, platforms, crest pickups | working (shared enemy sprites) |
| Overworld, shop, subscreen, generated password, options, endings | working (text/password decode are stubs; native save persistence is in place) |
| Save/options persistence (`saves/dc_save.json`, title CONTINUE) | working |
| Per-area BG2 capture pipeline (`bg2_captures.json`) | working for Areas 1 and 3 |
| Campaign room audit (`tools/audit_campaign.py`) | working (69 playable / 44 partial of 113) |
| Windows build (MinGW + local raylib) | working |
| Full-game campaign | **in progress** |

Missing in one line: per-species OAM/animation fidelity, BG2/mid-stage CHR for
areas beyond Area 1, text/cutscenes/exact password/save, the remaining real
enemy/boss handlers, and ROM audio.

---

## 3. Remaining work by layer

### 3.1 Data and extraction pipeline (critical path)

The pipeline now decodes every valid ROM area into `room_area<N>.json` and bakes
per-area BG atlases from ROM CHR/palettes. It still uses recomp captures for
Area 1's BG2 backdrop, the idle player sprite, `save0` player/fireball
animations and the BG3 HUD, and mid-stage `$98:E000` CHR streaming is not
decoded yet. The full game must eventually be generated from the player's ROM
without requiring recomp dumps.

- [x] Implement the ROM graphics decompressor:
  - `$BD:9953` → `$98:D000` graphics table (24-bit pointer + 16×16 unit count),
  - `$80:C2AF` / `$80:C300` decompressor (16 bytes per call, 8 calls per 16×16
    unit, advancing `0x40` bytes per unit and skipping `+0x200` when bit 9 is
    set),
  - 2bpp and 4bpp tile baking, OBJ size handling and palettes.
- [x] Extract every stage/area/room (including multi-row and vertical grids
  such as Area 2's 8×2 layout and Area 3's 4×5 tower) from:
  - area info `$81:A291` (0-indexed: Area 0 Somulo colosseum, Area 1 Graveyard
    forest, Area 2 catacombs, Area 3 ruins, etc.) and area grid `$81:A6D8`,
  - screens `$8F + set` (`$8000 + screen*128`), superblocks `$92 + set`
    (`$8000 + super*8`),
  - block tiles `$95 + set` (`$8000 + block*8`), block attributes in bank `$98`
    at `$98:8000 + (set<<12) + block` (not bank `$98 + set`),
  - object lists `$81:C874` (normal) and `$81:C9D0` (cleared),
  - sprite lists `$81:AE11` and area palettes `$81:8479`.
- [x] Encode spawn records (`$81:A1A9`), bounding-box transitions (`$81:981A`)
  and the `$81:97DA` boss-gate target into each room document.
- [x] Bake per-area BG atlases (`bg_area<N>_pal<P>.png`) from ROM CHR and the
  ROM palette blocks, limited to palettes each area uses, and load them on
  room transitions.
- [x] BG3 HUD/font layers from ROM CHR: the BG3 character base is `$5000`
  words (`bgTileAdr & 0xF << 12`); `tools/dc_extract/extract_font.py` bakes the
  95-glyph 8x8 font used by every text box, and dialogue renders with it.
- [ ] Extract BG2 backdrops directly from ROM CHR + tilemaps for every area.
  **Partial:** the extractor takes a per-area BG2
  frame from `tools/dc_extract/bg2_captures.json` and bakes its tilemap plus a
  capture-based atlas (Areas 1 and 3 are baked). The guest generates the BG2
  tilemap at runtime (`$84:A057` DMAs from WRAM `$7F`), so there is no raw ROM
  table; the remaining areas each need one oracle frame until the generator is
  decoded.
- [ ] Extract OAM metasprite layouts and animation frame/timing tables for all
  player forms, projectiles, pickups, enemies and bosses. **Partial:** a new
  injected-object oracle capture (`tools/oracle/capture_species.py` +
  `tools/dc_extract/extract_species.py`) bakes per-species enemy PNGs and
  `species_anim.json` from live OAM, and the engine now draws per-species
  sheets for the species whose init is self-contained (urn `$57`, pickup `$49`,
  `$2D`, ghoul `$67`). Species whose init depends on spawner-supplied fields
  still fall back to the shared sheet; reproducing the `$82:8BDB` spawner writes
  is the next step.
- [ ] Handle mid-stage graphics streaming (`$80:BFB5` / `$80:C11B`, including
  `$98:E000` chunks) and tile animation (`$81:C125`).
- [ ] Extract HDMA tables for every area (channel 1 `$210F` `BG2HOFS` is done
  for Area 1), color math, Mode 7, window/priority data and per-room camera
  bounds.
- [x] Generate one common room format for every room (2D multi-screen tilemaps,
  collision, objects, seams/exits, camera, palettes, CHR references).
- [ ] Remove the remaining dependency on per-room VRAM/FB/state-ring captures
  for shipping data: `stage_600` still supplies Area 1 BG2/the idle sprite and
  `save0` supplies player animations and the HUD.
- [ ] Oracle validation per area: compare extracted tilemaps, CGRAM, OAM,
  collision cells and object positions against the recomp.

Acceptance:

- A clean ROM → extractor → assets/room-data pass produces the whole game.
- Every room's BG/collision matches the recomp dump at its camera origin.
- No hand-authored, placeholder or hand-captured room/sprite data is needed.

### 3.2 Level and room engine

- [x] Multi-room loading and unloading, supporting full 2D screen grids
  (multi-row/vertical rooms, not just single 256 px rows) and >2 BG layers.
- [x] Horizontal/vertical screen seams, doors, exits (`species $09`) and
  stage/boss gates (`$81:97DA`, `$81:80A1`).
- [x] Per-room camera bounds and deadzones; room transitions and screen fades.
- [x] Complete collision-attribute decoding for the implemented terrain:
  - the `$1070` probe selects the `0x00B3 → 0x0166` walk-speed ramp
    (`$80:8B85`, `3/256` px/frame²) when `attr & 0xE0 == 0x80`,
  - hazards (`0x20`, e.g. `0x21`), breakable `0x40` blocks, water (`0x60`)
    and slopes/ledges/half blocks are handled.
- [ ] Remaining terrain edge cases: ice/wind flags, pass-through and the exact
  per-shape ramp/hazard behaviour.
- [x] Underwater physics (`$1045` flag: jump `0x02CE`, gravity `0x002A`,
  terminal fall `0xFD00`) and form-specific movement modifiers.
- [x] Moving platforms, breakable terrain (Buster/Earth blocks, headbutt
  ceilings) and object-driven terrain.
- [ ] Full BG priority, color math, windows, mosaic and Mode 7 rendering.
- [x] BG2 HDMA per-scanline parallax (channel 1 `$210F` `BG2HOFS`) for Area 1,
  recovered from `$84:AF65` (32/44/28/46/74-line bands).
- [ ] Tile animation (`$81:C125`) and stage-specific effects (water/lava/weather).
- [ ] Correct foreground/background layering for every room.

Acceptance:

- Every room can be traversed in all directions without stale or missing tiles.
- Camera/scroll/priority/HDMA match the recomp screenshots at reference points.

### 3.3 Player and crest forms

Base Gargoyle grounded/jump/hover/shot only today. The full game needs the
complete Bank `$80` state machine, form system and equipment effects.

- [x] Bank `$80` player state machine foundation (`$80:DB80` / `$80:E002`):
  grounded/jump/hover, wall cling (`State 0x08`), headbutt (`State 0x1A`),
  hurt/knockback and death flow, plus simplified fireball/spell states.
- [ ] Exact remaining state branches: fireball state (`State 0x12`),
  talisman (`State 0x16`) timing, respawn variants and all edge cases.
- [x] Crest transformations and elemental abilities:
  - **Crest of Fire** elements for Base Gargoyle (Fireball, Buster, Tornado,
    Claw, Demon Fire),
  - **Earth Gargoyle** (ground-bound shoulder dash/tackle, obstacle breaking),
  - **Aerial Gargoyle** (free flight, high-angle shot),
  - **Water Gargoyle** (directional swimming, aquatic projectile),
  - **Legendary Gargoyle / Crest of Time** (halved damage, powered shot),
  - **Ultimate Gargoyle / Crest of Heaven** (all abilities + charged shot).
- [x] Base projectile and spell types: normal/charged shot, five Fire-Crest
  elements, consumable Scrolls (Vellum) and Potions/Urns.
- [ ] Tornado platforms and Claw lava-freezing interactions.
- [x] Base inventory and equipment persistence within a run:
  - 6 Crests, 5 passive **Talismans** (Crown, Skull, Armor, Fang, Hand), up to
    5 **Urns**, up to 5 **Vellum**, HP upgrades and gold.
- [ ] Exact talisman effects, icons and the retail pause-subscreen layout.
- [ ] Form-specific animation sets, real form OAM and HUD icons (current forms
  are palette tints of the base sheet; Hurt/Death clips are still needed).
- [ ] Oracle traces for movement in every form and terrain type (including the
  `$1070` slope ramp and `$1045` underwater physics).

Acceptance:

- A scripted input route in each form matches the recomp within ≤1 px / 1 frame.
- All transformations, abilities and items behave like the original.

### 3.4 Objects, enemies, hazards and bosses

The 26-slot object pool (`$1080..$1D50`, stride `$50`, with the first 7 slots
`$1080..$1260` reserved for player projectiles/effects via `$80:F222`) exists.
Urns (`$57`), `$85:C180` heart pickups, the `$09` exit trigger, platforms,
crest pickups, a first-pass `$67` ghoul and several Area 2/3/5 enemy species
are implemented; most still share the ghoul metasprite.

- [x] 26-slot object pool with unified projectile/effect/stage-object slots and
  data-driven spawning from `$81:C874`.
- [ ] Port the complete `$82:8611` object loop (main/secondary update paths
  `$8000`, `$8180`, `$8300`, `$8480`) and `$82:8BDB` spawner; the current loop
  implements the common path only.
- [ ] Port all species handlers from the `$82:8000,X` jump table, starting with
  the real Area 1 species `$67` ghoul handler at `$83:AF74` (current ghoul,
  skeleton, bat and gargoyle AI are first-pass reimplementations). **Partial:**
  the ghoul's init constants and state 0 drop cycle (`$B2B1`/`$AFCB`/`$B000`:
  lift 9, vx `0x50`, vy `0x398`, gravity `0x40`, windup 3, land 6) are ported
  into `src/object.c`, with the full state map documented; states 1–4 and the
  `$DEA2` behaviour dispatch remain.
- [x] Extract and implement the base object set: destructible urns, heart and
  crest/Life-Stone pickups, gold drops, moving platforms, Area 0 Somulo boss,
  skeleton patrols, bats and wall gargoyles.
- [ ] Remaining enemies, enemy projectiles, effects, hazards and crest-
  interactive objects (statues, torches, vines, breakable blocks).
- [ ] Authentic player-object touch (`$80:9C93`) and projectile-enemy collision
  tables: exact hitboxes, damage types, knockback, invulnerability and drops
  (current values are approximations).
- [ ] Remaining boss rooms and AI, boss gates (`$81:97DA`, `$81:80A1`), defeat
  events and stage progression (Somulo and the Area 0 gate are implemented;
  Phalanx forms and Dark Demon are still missing).
- [ ] Enemy/boss OAM, CHR, animation tables and palettes for every species
  (only the shared ghoul sheet is baked today).
- [ ] All object-list entries for cleared areas (`$81:C9D0`) and the remaining
  `$81:C874` species coverage.

Acceptance:

- Every object-list entry in every room spawns and behaves correctly.
- A full enemy/boss regression route matches the recomp.

### 3.5 Menus, overworld, story and game flow

Current title/pause/Area Clear is a vertical-slice skeleton.

- [x] Title menu: New Game, Overworld Map, Password, Options.
- [x] Password screen with a generated progression code (retail encode/decode
  algorithm still pending) and campaign persistence. **Partial:** native
  save/options persistence is implemented (`saves/dc_save.json`, title
  `CONTINUE`, autosave on clear/overworld/exit, regression-covered) and the
  password screen now has a working 10-letter checksummed codec with entry and
  `DC_PASSWORD`/self-test hooks; the retail password/SRAM format is still to be
  decoded.
- [x] Pause item/crest subscreen (`X` → `$80:DC12`): Crest transformation,
  Fire-Crest element, Talisman selection, Urn use and Scroll casting, wired to
  the BG3 HUD active-slot indicator.
- [x] Mode 7-style overworld flight runtime with six landing nodes, stage
  locking, nearest-node landing and shop access (real ROM map data pending).
- [ ] Town NPCs, full shop dialogue and the Headbutt minigame.
- [x] Death, Game Over, Continue and Overworld return flow.
- [x] Text/dialogue system: ASCII script extraction (518 strings), the BG3
  font, paging (`GAME_DIALOGUE`), control-character normalisation (`[`, `j`),
  real shop dialogue, crest/fire-piece story beats and the four endings.

- [x] Four endings (Bad/Normal/Good/True) with transcribed narration, an
  epilogue wired to ROM text `$81:8DF2`, crest-count gating and a regression
  check per variant.
- [ ] Intro/cutscene sequencing (scene camera, timing, per-event script index)
  and the ending artwork.

- [x] Basic story/event flags, boss gates, crest/item collection tracking and
  stage progression (Area 0 gate and overworld stage bits).
- [ ] Localization hooks and text encoding.
- [ ] Full options: music/SFX volume (master volume is done), controls,
  scaling/aspect ratio/fullscreen.

Acceptance:

- Cold boot → title → new game → Area 0 Somulo intro → Area 1 graveyard →
  Mode 7 overworld → all stages, shops and bosses → all endings → credits can
  be completed without development hooks.

### 3.6 Audio

Current audio (`src/audio.c`) is an original procedural chiptune/SFX
replacement.

- [x] Replacement soundtrack skeleton: four procedural loops (title, stage,
  boss, ending) with automatic state-driven switching.
- [ ] Extract SPC700 BRR samples, DSP instruments and music sequences from the
  ROM, or build a complete replacement soundtrack.
- [ ] Per-area, overworld, shop, menu, cutscene and ending music.
- [ ] Port all original SFX triggers (dispatched via `$80:BD57`, e.g. `$58`
  heart pickup) using extracted BRR/DSP sound effects or replacements.
- [ ] Volume/mute/options menu wiring.
- [ ] Legal packaging path for music and SFX.

Acceptance:

- Every stage/boss/menu has music and SFX; no silent gameplay states.

### 3.7 QA, platform and release

- [ ] Full-campaign regression against the recomp (movement, collisions,
  objects, bosses, transitions). **Partial:** `tools/audit_campaign.py` now
  validates every generated room structurally and can gate CI with `--strict`.
- [x] End-to-end playthrough check (`tools/check_playthrough.py`): title →
  clear → overworld → stage travel → boss clear → ending, all six steps green.
- [x] Campaign completion test: every boss stage entry reaches GAME_CLEAR
  (`tools/check_campaign.py`, 7/7) with per-frame state tracing.
- [x] Stage-select overlay listing all 66 stage-entry rooms (every area
  reachable) plus transition fixes for boss-less rooms and door padding.
- [x] Room classification in `campaign.json` (69 playable / 44 partial / 0
  empty) with audit cross-check and native `empty`-room refusal.
- [x] Campaign-wide load coverage: `tools/check_areas.py` boots all 113 rooms
  headless and validates exit/frame count/player bounds; the full sweep passes
  and a 12-area subset runs in `run_regression.py`.
- [ ] BG2 panorama stitching: align captured frames by scroll into a
  room-sized backdrop. **Partial:** multi-frame CHR/tilemap merging is in
  `extract.py` (`DC_BG2_MERGE_FRAMES`); offset alignment is the next step.
- [ ] Per-room geometry/collision validation tooling. **Partial:** the audit
  covers dimensions, BG1/collision coverage, BG2 presence, spawn support,
  object bounds and transition/gate targets; per-tile oracle diffing remains.
- [ ] Performance and memory profiling for all stages.
- [~] Windows and macOS builds (Linux is current). **Windows done:**
  `-DDC_RAYLIB_ROOT` links a local raylib and `tools/build_windows.ps1` builds
  against the raylib Windows installer; macOS untested.
- [ ] Gamepad remapping, save/options persistence.
- [ ] CI for build + regression.
- [ ] Packaging and installer/ROM-extraction flow.

### 3.8 Legal and distribution

- [ ] Never commit ROM-derived assets (`assets/generated/`, `captures/`) or
  generated C / extracted data from the recompilation project.
- [ ] Ship either a local ROM-extraction setup (requiring the player's own USA
  ROM at install/generation time) or fully original/licensed replacement assets.
- [ ] Keep this MIT engine clean of GPL-3.0 code from external format
  references (such as randomizers); reimplement formats from ROM disassembly.
- [ ] Confirm fan-game distribution policy and attribution.
- [ ] Replace development placeholder audio (procedural chiptune/SFX) and the
  shared enemy-species sprites with ROM-extracted local assets or
  licensed/original content for a public release.

---

## 4. Expansion content (pre/post story)

Only after the original campaign is stable.

- [ ] Data-driven scene/dialogue/cutscene authoring tools.
- [ ] New maps, enemies, bosses, forms, items and hazards.
- [ ] New art, animation and music (original/licensed only).
- [ ] Quest/story flags and continuity with the original campaign.
- [ ] New title/menu content and credits.
- [ ] Separate content validation and regression coverage.
- [ ] Legal review of all new assets and story text.

Acceptance:

- New content is authored as data/content, not engine forks.
- The full game remains stable across the original campaign plus expansions.

---

## 5. Recommended order and rough estimates

Estimates are rough and assume one experienced developer; reverse engineering
can expand them.

The campaign foundation is now in place: all 113 areas extract and load,
multi-row rooms/transitions/boss gates work, six Crest forms and the
subscreen/overworld/shop/password/ending flows exist, and Area 0 Somulo is
playable. The next milestone is **content fidelity** (per-species OAM/AI,
BG2/mid-stage CHR, text/cutscenes, exact password/save, ROM audio), followed by
full-campaign QA and release:

| Phase | Work | Depends on | Rough time | Status |
|---|---|---|---|---|
| A | CHR/room/OAM/animation extraction pipeline | current tools | 4–8 weeks | **mostly done**: decompressor, 113 rooms, per-area atlases, basic OAM; BG2/mid-stage streaming remain |
| B | Multi-row rooms, transitions, camera, HDMA, slopes/hazards | A | 4–6 weeks | **done for runtime**: transitions, gates, HDMA Area 1, slope ramp, hazards, water, breakables |
| C | All crest forms, inventory items and player states | B | 6–10 weeks | **foundation done**: six forms, elements, inventory, wall cling/headbutt; real form OAM/animations remain |
| D | Full `$82:8611` object loop, enemies, hazards and bosses | B (crest-specific objects/bosses integrate with C) | 8–12 weeks | **partial**: Somulo, skeletons/bats/gargoyles, platforms, pickups; full species table remains |
| E | Menus, subscreen, Mode 7 overworld, shops, password/save, text/cutscenes, endings | B (subscreen/progression integrate with C, D) | 6–10 weeks | **runtime done**: title/pause/subscreen/shop/password/options/overworld/endings; text/save/exact password remain |
| F | Audio extraction (SPC700 BRR/DSP + sequences) or replacement | current tools / A (stage/event wiring integrates with B, E) | 4–8 weeks | not started |
| G | Full-campaign QA, oracle regression, platform builds, release | C–F | 4–8 weeks | not started |
| H | Pre/post-story expansion content | G | 8+ weeks | not started |

This aligns with the overall project estimate in `docs/PROJECT_STATE.md`:
the **vertical slice is complete**, the **campaign foundation** (Phases A–E
runtime) is in place, and the remaining fidelity/audio/QA work (Phases A–G)
still fits the original **12–24 month** full-port estimate, plus expansion
content (Phase H).

Phases A and B are the critical path for scaling beyond the vertical slice.
Audio extraction/replacement (Phase F), OAM/art decoding and text/script tools
can run in parallel with B–D.

---

## 6. Open technical questions

Resolved in this session:

- ROM CHR decompressor (`$80:C2AF`/`$80:C300`) and `$98:C000`/`$98:D000`
  table layouts, including the `+0x200` bottom-row skip and 24-bit pointers.
- All 113 area grids, spawn records (`$81:A1A9`), transition boxes
  (`$81:981A`), boss-gate targets (`$81:97DA`) and object lists (`$81:C874`).
- OAM metasprite group format (`$8B:8000` via `$80:D9A7`) and the
  `$80:DA33` tile-base carry rule.
- Area 1 BG2 HDMA scanline bands (`$84:AF65`, 32/44/28/46/74 lines with
  0.25/0.125/0.25/0.50/1.25 factors).
- Collision environment flags: `0x20` hazard, `0x40` breakable, `0x60` water,
  `0x80` slope acceleration (`$1070`).
- Object dispatch tables: `$82:8000` (main), `$82:8180` (secondary),
  `$82:8300` (init), `$82:8480` (aux), each 192 entries indexed by `species*2`;
  the init entries are 5-byte `JSL $83:xxxx; RTS` thunks (species `$67` →
  `$82:F382` → `$83:AF19`, update handler `$83:AF74`).
- BG2 backdrop storage: generated by the guest at runtime (`$84:A057` DMAs the
  tilemap from WRAM bank `$7F` via `$84:C311`/`$84:C312` indexed by `$00F9`;
  static fallback from `$81:8068`). Per-area oracle frames are the interim
  extraction path (`tools/dc_extract/bg2_captures.json`).
- WRAM `$008D` semantics: room-sequence/stage id advanced by 2 at
  `$84:F0DA..F0EF` (previous value in `$0E56`); writing it through the debug
  server does **not** load a room.
- Windows build path: `-DDC_RAYLIB_ROOT` + `tools/build_windows.ps1`, verified
  with raylib 6.2 and MinGW GCC 16.2.

Still open:

- Complete stage/area map (`$81:A291` / `$81:A6D8`) and full room count across
  all sets.
- Boss/event scripting system and stage/boss-gate semantics (`$81:97DA`,
  `$81:80A1`, and exit object `species $09`).
- Mode 7 overworld map data, flight physics and landing-point triggers.
- Password encoding/decoding algorithm (including special post-game passwords)
  and modern save/options format.
- Text encoding, font tables and cutscene/dialogue script format.
- Full object species ID (`$02`) → handler table (`$82:8000,X`) coverage;
  the table layout and init thunks are mapped, per-species handlers and their
  OAM/animation data are not.
- Authentic projectile-enemy and player-object (`$80:9C93`) hitbox, damage type,
  invulnerability and drop tables.
- ROM OAM metasprite and animation table layout so player/enemy/pickup sprites
  do not require state-ring captures (`save0`).
- HDMA/color-math/window tables and per-scanline effects beyond Area 1 BG2.
- Mid-stage CHR streaming coverage (`$80:BFB5`, `$80:C11B`, `$98:E000`) and
  tile animation (`$81:C125`).
- Best audio path for distribution (ROM BRR/DSP + sequence extraction vs.
  replacement tracks) and `$80:BD57` SFX dispatch mapping.
- Aspect ratio / widescreen policy and Windows/macOS CI and packaging.

---

## 7. Next concrete engineering tasks

Ordered by remaining fidelity; the campaign foundation (extraction, room
loading, transitions, crests, boss, overworld and menus) is already in place:

1. Bake per-species OAM groups and animation tables from the `$82:8300` init
   handlers; replace the shared ghoul sheet for skeletons, bats, gargoyles,
   Somulo, Phalanx and Dark Demon.
2. Port the full `$82:8611` object loop and remaining `$82:8000` species
   handlers (start with the authentic `$83:AF74` species `$67` ghoul).
3. Extract BG2 backdrops, `$98:E000` mid-stage CHR streaming and tile
   animation for every area; finish per-area palettes. **BG2 path started:**
   add one `capture_anim.py` frame per area to
   `tools/dc_extract/bg2_captures.json` (Areas 1 and 3 are baked); decoding the
   WRAM `$7F` generator would remove the per-area capture requirement.
4. Port exact player-object/projectile hitboxes, damage types, invulnerability
   and drop tables from `$80:9C93` and the object handlers.
5. Extract text/font/dialogue/cutscene script data and implement the text
   engine, intro/cutscenes, shop dialogue and all ending variants.
6. Implement the retail password encode/decode algorithm and save/options
   persistence. **Save persistence and a native password codec are done**
   (`saves/dc_save.json`, title CONTINUE, autosave, 10-letter checksummed
   password with entry UI, regression + self-test); the retail password/SRAM
   decode remains.
7. Extract or replace ROM audio (SPC700 BRR/DSP + sequences, `$80:BD57` SFX)
   and add music/SFX volume options.
8. Run full-campaign oracle regression across all 113 areas, forms and bosses.
9. Windows/macOS builds, packaging and CI.
10. Only then start pre/post-story expansion content.

---

## 8. Definition of done — original campaign

- [ ] Cold boot reaches the title, and New Game runs through the Area 0 Somulo
  colosseum intro into Area 1.
- [ ] Every original stage, multi-row room, door/seam transition and Mode 7
  overworld destination (including town, shops and minigames) is playable.
- [ ] All Gargoyle crest forms, Fire-Crest elemental shots, Talismans,
  Potions/Urns, Scrolls/Vellum, Life Stones and currency work.
- [ ] All enemies, hazards and bosses (including Somulo, stage bosses, all
  Phalanx forms and Dark Demon) work with authentic hitboxes, damage and drops.
- [ ] BG3 HUD, pause item/crest subscreen (`X`), overworld map and
  password/save/game-over flow work.
- [ ] Intro, cutscenes, dialogues, all multiple endings (Bad, Normal, True,
  post-game) and credits play.
- [ ] Music and SFX cover every stage, boss, menu and cutscene without silent
  states or development placeholders.
- [ ] A 100% playthrough is completable without dev hooks.
- [ ] Movement/object/boss regression stays within 1 px / 1 frame of the
  recomp on scripted routes.
- [ ] No ROM-derived asset is committed or distributed, and all temporary
  procedural placeholders are replaced by ROM extraction or final assets.
- [ ] Linux and Windows builds pass the same regression suite.
