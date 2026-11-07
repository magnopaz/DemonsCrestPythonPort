# Extracting sprite-sheet frames

This is the working playbook for turning the labelled sheets in `docs/sprites`
into authored animation entries. It is written so a fresh session can continue
the job without re-discovering the method. Belth is the completed reference
case; the rest of the sheets are still to do.

Read `docs/TOOLING.md` first for the existing sprite/ROM tools, and
`tools/editor/README.md` for the editor itself. This file is the extraction
workflow, not a replacement for either.

## 0. TL;DR

- Source art: `docs/sprites/*.gif` and `*.png`. Most GIFs are one static
  labelled sheet, not animated GIFs.
- Destination: `assets/authored/sprites/<target>/` plus an authored
  `assets/authored/species_anim.json` or `player_forms.json`. **One subfolder
  per extraction/target** (`belth/`, `arma/`, `player_aerial/`, ...); never
  drop frames loose in `assets/authored/sprites/`, where the next target
  collides with them.
- **Never edit `assets/generated/` for this job.** It is ROM-derived and
  rebuildable.
- The baker is spec-driven: add a `SPECS` entry to
  `tools/dc_extract/bake_sheet_anim.py` (measured bands, names, species/form)
  and run it. `tools/dc_extract/bake_belth_animation.py` is the documented
  Belth shortcut for the same spec. Measure with
  `tools/dc_extract/sheet_report.py` (rows/poses) and
  `tools/dc_extract/sheet_captions.py` (caption strips); label, crop, key,
  anchor and contact-sheet logic lives in `tools/dc_extract/sheet_lib.py`.
- Validate in the Enemy Editor / Player Editor, then render in game. Commit
  only authored images/JSON and the extraction tool/doc.
- Do not overwrite the existing authored Belth entry, the user's
  `assets/authored/rooms/room_area0.json`, `room_area1.json` or
  `room_area4.json`.

## 1. What the sheets contain

The sheets are community rips (credits are printed on each sheet: Lord
Zymeth / The Spriters Resource). They are not a 1:1 animation timeline:

- Each sheet groups drawings by action (`Idle`, `Walking`, `Attack`, ...).
- A GIF is usually **one frame**; use `Image.n_frames` only to confirm this.
- Captions, palette examples and projectile/effect rows are mixed into the
  same sheet.
- Some rows contain several species or several boss parts.
- The game's animation timing (durations, state numbers) is not on the sheet.
  Durations must be chosen deliberately; copy the style already in
  `assets/generated/player_forms.json` / `species_anim.json` (typically 6-10
  ticks per frame, 1-2 for intro/impact frames).

Important: **the sheet is a drawing reference, not a frame-order oracle.** If
the ROM/recomp has a live capture of the object, prefer the OAM pipeline
(`tools/oracle/capture_boss_poses.py`, `tools/dc_extract/bake_boss_pose.py`,
`bake_rom_species.py`) and use the sheet only to fill gaps. For Belth the live
save had a dormant object and injected OAM stayed hidden, so the labelled sheet
was the practical source. State that in the entry's `source` string.

## 2. Engine limits and formats

### Enemy species (`species_anim.json`)

```json
{
  "species": {
    "68": {
      "species": 104,
      "frames": [
        {"texture": "sprites/belth/belth_00_idle.png",
         "anchor_x": 30, "anchor_y": 58,
         "duration": 10, "width": 60, "height": 58}
      ],
      "states": {"0": [0, 1, 2], "3": [10, 11, 12]},
      "state_names": {"0": "idle", "3": "attack"},
      "hurt": 30,
      "default": 0,
      "source": "Belth.gif: idle/walk/attack/... rows"
    }
  }
}
```

- `texture` is relative to `assets/authored`; `sprites/<target>/...` resolves
  under `assets/authored/sprites/<target>/`. Both the runtime
  (`dcpy/assets.py:_load_one_optional`) and the editor
  (`EditorData.find_asset`) try `authored/<texture>` and
  `authored/sprites/<texture>`, so subfolders need no loader change.
- Max **64 frames** per species (`DC_SPECIES_FRAMES`), **16 states**, **8
  frames per state** (`DC_STATE_FRAMES`).
- `states` values are indices into `frames`; states should be ordered
  animations, not arbitrary piles.
- `hurt` is the white-flash pose; `default` is the single pose used when no
  state animation is active.
- `state_names` is optional editor metadata. It does **not** prove the object
  AI uses those state numbers. Belth's labels are sheet-derived; its native AI
  is not ported yet.

### Player sheets (`player_forms.json` / `player_anim.json`)

```json
{
  "forms": [
    {
      "form": 2,
      "name": "aerial",
      "clips": {
        "idle": {"loop": true, "steps": [
          {"texture": "fb_aerial_idle_0.png",
           "anchor_x": 17, "anchor_y": 49, "duration": 8}
        ]}
      }
    }
  ]
}
```

- Six fixed forms: 0 Normal/base, 1 Ground, 2 Aerial, 3 Tidal, 4 Legendary,
  5 Ultimate.
- The 11 clips are exactly: `idle`, `walk`, `jump`, `hover`, `fall`, `land`,
  `attack`, `spell`, `flying`, `hurt`, `death`.
- Max **64 total steps across all clips of one target**
  (`DC_ANIM_MAX_STEPS`). The per-clip count is bounded by that total.
- A clip with zero steps must be omitted; the loader rejects an empty clip and
  unloads the whole sheet. The editor strips empty clips on save.
- `loop` is a real gameplay flag. Idle/walk/hover/flying normally loop;
  attack/jump/fall/land/hurt/death normally do not.
- Base `player_anim.json` has `{"clips": ...}` and uses the ROM `player_*.png`
  art. Authored forms live in `sprites/player_<name>/` as
  `player_<name>_<index>_<clip>.png`; the older generated `fb_*` files belong
  to `bake_player_forms.py`, which writes to `assets/generated`.

## 3. Inventory

Counts below are the **authored** entries now in
`assets/authored/species_anim.json` / `player_forms.json` (this session's
extraction), with the old generated count in parentheses. They show coverage,
not a quota.

### Boss sheets

| Sheet | Target species | Authored | Rows/labels to map | Notes |
|---|---|---:|---|---|
| `Belth.gif` | `$68` | 32 | idle, taunt, walk, attack, jump, charge, turn, hurt, death | **Done**; see §5.1 |
| `Arma.gif` | `$A5` flags 0 | 19 | idle/laughing/intro/flying/breath/divebomb | Red palette; effects rows skipped |
| `Arma.gif` (2nd fight) | `$A5` flags 2 | 19 | same rows, green palette | Entry `a5_f2` |
| `Ultimate Arma.gif` | `$A5` flags 4 | 24 | + hurricane/demon fire | Entry `a5_f4` |
| `Crawler.gif` | `$82` (+`$83/$84/$85` parts) | 7 (3) | move | Body row only; parts still open |
| `Dark Demon.gif` | `$BC` (+`$8A` effects) | 11 (3) | idle, attack | Top two body rows; `$8A` effects separate |
| `Flame Lord.gif` | `$58` (+`$5C-$5F`) | 4 (3) | idle | Left of the idle row is teleport flame, not the boss |
| `Grewon.gif` | `$13` | 19 (6) | idle/walk/attack/hurt | Second palette repeats the same rows |
| `Hipogriff.gif` | `$09` | 23 (6) | idle/walk/attack | Statue pose and credit block skipped |
| `Holothurion.gif` | `$6F` | 3 | examples/idle/attack/death | Multi-part; examples row only |
| `Ovnunu.gif` | `$16` (+`$17/$18`) | 3 | eyeball/body/attack | Multi-part (eye + parts) |
| `Phalanx.gif` | `$86` (+`$88`) | 8 (6) | idle/gesturing | First form body band |
| `Ultimate Phalanx.gif` | `$8D` | 4 (3) | examples/full body | Second-form body; boss variant |
| `Scula.gif` | `$7B`, `$7C` | 3 each | body/arm/attack/death | Two objects at the same arena position |
| `Somulo.gif` | `$33` (+`$35-$37`) | 4 | head/neck/jaw/fire | Prefer `somulo_native_reference.png`, `clean_somulo.py`; multi-part and hard |
| `NPCs.png` | `$96`, `$97` | 1 | town NPC / guard | Static; not a boss |

The authoritative species map and existing one-off bakers are listed in
`docs/TOOLING.md` §"Boss sheet mappings". Use those species ids exactly.

### Progress checklist

- [x] Belth `$68` (32 frames, `sprites/belth/`)
- [x] Arma `$A5` flags 0/2/4 (19 / 19 / 24 frames, `sprites/arma*/`)
- [x] Crawler `$82` body (7 frames, `sprites/crawler/`; `$83-$85` parts open)
- [x] Dark Demon `$BC` (11 frames, `sprites/dark_demon/`)
- [x] Flame Lord `$58` (4 frames, `sprites/flame_lord/`; fire rows are effects)
- [x] Grewon `$13` (19 frames, `sprites/grewon/`)
- [x] Hipogriff `$09` (23 frames, `sprites/hipogriff/`)
- [ ] Holothurion `$6F` (multi-part; examples row only)
- [ ] Ovnunu `$16` (eye + `$17`/`$18` parts)
- [x] Phalanx `$86` / Ultimate Phalanx `$8D` (8 / 4 frames)
- [ ] Scula `$7B`/`$7C` (two objects, arm poses)
- [ ] Somulo `$33` (use the native-reference part pipeline, not blind crops)
- [ ] Enemies 1 / Enemies 2 species
- [x] Player forms 1-5 (`player_forms.json`; base form 0 stays the
  ROM-captured `player_anim.json`)
- [ ] NPCs `$96`/`$97`

Keep this checklist updated in the same commit as the frames so the next
session can see what is actually left.

### Enemy sheets

`Enemies 1.gif` and `Enemies 2.gif` contain many small enemies in labelled
groups. Current generated entries are mostly 1-3 frames: `$06`, `$07`, `$2C`,
`$2D`, `$2E`, `$49`, `$57`, `$63`, `$65`, `$67`, `$72`, `$79`, `$97`, and
others. Do not guess a species from the drawing; match the sheet caption to
`docs/SPECIES_CENSUS.md`, `docs/TOOLING.md`, and the current
`species_anim.json` `source` / first frame. When a caption is ambiguous, write
a short note in the entry's `source` and leave the species for a reviewer.

### Player sheets

| Sheet | Target | Current | Notes |
|---|---|---:|---|
| `Firebrand.gif` | base `player_anim.json` (form 0 visual) | 8 clips / 21 frames (ROM) | **Not re-baked**: the ROM capture has the game's real cadence; the sheet repeats it plus effect rows |
| `Firebrand (Ground).gif` | form 1 | 8 clips / 27 frames | Ground form (`sprites/player_ground/`) |
| `Firebrand (Aerial).gif` | form 2 | 10 clips / 38 frames | Aerial form; no `spell` on the sheet |
| `Firebrand (Tidal).gif` | form 3 | 10 clips / 31 frames | Tidal form |
| `Firebrand (Legendary).gif` | form 4 | 10 clips / 38 frames | Legendary form |
| `Firebrand (Ultimate).gif` | form 5 | 10 clips / 36 frames | Ultimate form |

The five form entries are authored (previously `player_forms.json` did not
exist, so every form fell back to the base sheet). Counts are one or two below
the old sheet tally because obviously repeated drawings inside a clip are
deduplicated and caption pixels are dropped.

The player sheets include extra rows not represented by the game's 11 clips:
headbutt, wall cling, attack (wall), enter door, fire crest, projectile
effects, overworld hover/flying/turning/stopping, etc. **Do not force every
row into a clip.** Map only character poses that correspond to the 11 clips;
effects and UI are out of scope for `player_forms.json`. The base sheet's
projectile rows (`Fire`, `Breaker`, `Tornado`, `Claw`, `Demon Fire`) are
projectile art, not player animation frames.

## 4. The extraction recipe

### 4.0 The tools

| Tool | What it does |
|---|---|
| `tools/dc_extract/sheet_lib.py` | shared library: background colour, connected components, caption words, row bands, pose boxes, border-flood background key, speck/caption cleanup, body anchor, contact sheet |
| `tools/dc_extract/sheet_report.py` | prints a sheet's captions (as ASCII art), bands and every measured pose box — the measuring step |
| `tools/dc_extract/sheet_captions.py` | stacks a sheet's caption strips into one readable PNG (3x, chunked, with the y range printed); use it with an image-capable model, or read `sheet_report.py` art directly |
| `tools/dc_extract/bake_sheet_anim.py` | the spec-driven baker: one `SPECS` entry per target, writes `sprites/<target>/`, merges `species_anim.json` / writes `player_forms.json`, prints problems and can emit a contact sheet |
| `tools/dc_extract/bake_belth_animation.py` | thin wrapper over `SPECS["belth"]` (documented reference case) |

A spec band is either `{"name", "y": (y0, y1), "x": (x0, x1)}` (split on
background columns), `{..., "split": "components"}` for closely packed player
poses, or `{"name", "boxes": [(x0, y0, x1, y1), ...]}` when a weapon arc or
fire trail bridges two drawings. `min_w`/`min_h`/`max_w` filter specks and
merged pairs; `expect` makes the bake fail loudly when a row's count changes.

### 4.1 Setup

Use the project venv for game/editor commands; system Python with Pillow is
fine for the sheet analysis:

```sh
python -c "from PIL import Image; im=Image.open('docs/sprites/...gif'); print(im.size, getattr(im,'n_frames',1))"
```

Run the grid helper before measuring anything. It writes a 50 px grid over a
copy (never the source):

```python
from PIL import Image, ImageDraw
im = Image.open(SHEET).convert("RGB")
d = ImageDraw.Draw(im)
for x in range(0, im.width, 50):
    d.line([(x, 0), (x, im.height)], fill=(255, 0, 255))
for y in range(0, im.height, 50):
    d.line([(0, y), (im.width, y)], fill=(0, 255, 255))
im.save("captures/<sheet>_grid.png")
```

### 4.2 Measure row bands

Each animation is a horizontal band. Use the grid/captions to write:

```text
name, x0, x1, y0, y1, manual_boxes
idle, 10, 228, 25, 95, []
attack, 0, 540, 118, 228, []
```

- `y0` must exclude the caption text; captions are separate small components
  but it is better not to include them at all.
- `y1` must include the lowest foot/bone but exclude the next row's caption.
- If a weapon arc connects two adjacent bodies, do **not** let column splitting
  cut them. Add manual absolute boxes for that band and leave `manual_boxes`
  empty only for clean rows. Belth's `charge` band is the example.
- Spread rows by action, not by x position; e.g. Belth has idle/taunt/walk in
  one band and attack/jump in the next.

### 4.3 Split poses on background columns

The Belth baker uses this exact logic. Copy it; don't hand-crop 30 times.

```python
from collections import Counter
from PIL import Image

def is_bg(p, bg):
    return abs(p[0]-bg[0]) + abs(p[1]-bg[1]) + abs(p[2]-bg[2]) <= 30

im = Image.open(SHEET).convert("RGB")
small = im.resize((max(1, im.width//4), max(1, im.height//4)))
bg = Counter(small.getdata()).most_common(1)[0][0]  # usually (16,16,41)

band = im.crop((x0, y0, x1, y1))
px = band.load()
runs, start = [], None
for x in range(band.width):
    hit = any(not is_bg(px[x, y], bg) for y in range(band.height))
    if hit and start is None: start = x
    elif not hit and start is not None:
        runs.append((start, x-1)); start = None
if start is not None: runs.append((start, band.width-1))
```

Merge runs separated by 1 px. A clean body row gives one run per pose. A row
where a detached arc/effect touches the next pose gives a too-wide run; replace
that band with manual boxes measured from the grid.

### 4.4 Crop, key and clean

For each run or manual box:

1. Crop to the run's x range and its actual y extent.
2. Convert to RGBA.
3. Key **only** the flat sheet background; do not key near-black interior
   pixels (ribcages, eye sockets, shadows).
4. Remove caption letters and detached specks with
   `tools/sheet_row.py:remove_small_components` (import it or copy it).
5. `crop.getbbox()` after keying; discard empty/tiny crops.
6. Deduplicate identical poses by raw RGBA bytes (some sheets repeat a pose
   with a different caption alignment).

Do not scale, antialias, sharpen or palette-quantise. The port loads the exact
PNG; SNES pixels must remain pixels. Keep transparency binary.

### 4.5 Anchor from the body, not the crop

The anchor is the image pixel that lands on the object's world position. For a
whole-body pose:

- X = centre of the **largest connected component** (the body), not the bbox
  centre, otherwise a wide weapon arc shifts the body off the hitbox.
- Y = bottom of that body component = the feet.
- Store integer `anchor_x` / `anchor_y`.

The Belth baker has `largest_component_anchor()`. For player frames, the same
rule applies; the 12x22 hitbox is drawn from the anchor and the feet should sit
on the floor.

### 4.6 Name and emit

Use a unique prefix so the authored frame cannot collide with generated art:

```text
assets/authored/sprites/<target>/<target>_<index:02d>_<animation>.png
# sprites/belth/belth_00_idle.png
# sprites/arma/arma_03_walk.png
# sprites/player_aerial/player_aerial_02_idle.png
```

Keep the target prefix inside the file name as well as the folder: a texture
copied out of its folder still says what it is, and two targets can never
collide. `bake_sheet_anim.py` writes exactly this shape.

Frame fields:

```json
{"texture": "sprites/belth/belth_00_idle.png",
 "anchor_x": 30, "anchor_y": 58,
 "duration": 10, "width": 60, "height": 58}
```

Durations are 60 Hz ticks: idle/taunt 10, walk/attack 8, impact 1-2, death
6-10. Be consistent within a sheet.

### 4.7 Build the entry

For enemies, write into the **authored** overlay and preserve every other
species entry:

```python
root = json.loads(authored_species_path.read_text())
root["species"]["68"] = entry
atomic_write_json(authored_species_path, root, pretty=True)
```

For players, write one form at a time and preserve other forms:

```python
root = {"forms": existing_forms}
root["forms"] = [f for f in root["forms"] if f.get("form") != form_index]
root["forms"].append(entry)
```

Do **not** write into `assets/generated/species_anim.json` or
`assets/generated/player_forms.json` for this job.

### 4.8 State maps (enemies) and clips (players)

Enemy sheet labels become state names first; assign numeric states after:

```json
"states": {
  "0": [0, 1, 2],
  "1": [3, 4, 5],
  "2": [6, 7, 8, 9],
  "3": [10, 11, 12, 13, 14, 15, 16]
},
"state_names": {"0": "idle", "1": "taunt", "2": "walk", "3": "attack"},
"hurt": 30,
"default": 0
```

Caps: 16 states, 8 frames/state, 64 frames total. If the sheet has more poses
than fit, keep one complete representative cycle per gameplay state (idle,
walk, attack, hurt, death) before adding taunts/turns. Do not make a single
state longer than 8.

Player clips are fixed; use the exact 11 names. A sheet row maps only when the
pose is a character action, not an effect. Set `loop` from gameplay semantics,
not from whether the sheet has repeated drawings.

### 4.9 Contact sheet and review

Always render a contact sheet before loading the editor:

```python
from PIL import Image, ImageDraw
files = sorted(glob("assets/authored/sprites/<prefix>_*.png"))
# 8 columns, label each card with its file name and frame index
```

Read the contact sheet and check:

- no caption text, neighbouring body parts or background rectangle;
- no pose cut in half;
- feet/bones not clipped;
- one pose per card, no duplicate frames;
- the intended animation order is obvious.

## 5. Sheet-specific notes

### 5.1 Belth (completed reference, `$68`)

- Sheet: `SNES - Demon's Crest - Enemies & Bosses - Belth.gif` (862x547).
- Tool: `tools/dc_extract/bake_belth_animation.py`.
- Bands:
  - idle 3, taunt 3, walk 4 in the top row;
  - attack 7, jump 4 in the second row;
  - charge 4 (manual boxes because the arc bridges poses), turn 5 in the third;
  - hurt 1, death 1 in the bottom row.
- Current output: 32 frames under
  `assets/authored/sprites/belth/belth_*.png`, entry `68` in
  `assets/authored/species_anim.json`, state names and hurt frame.
- Command (thin wrapper over `SPECS["belth"]`):

  ```sh
  python tools/dc_extract/bake_belth_animation.py
  # equivalent: python tools/dc_extract/bake_sheet_anim.py --only belth
  ```

- Verified in the Enemy Editor and in a rendered game frame. The state numbers
  are an editor/authoring map; Belth's AI is not ported, so do not claim the
  game will play attack/charge states yet.

### 5.2 Other bosses

The authored boss entries now live in `bake_sheet_anim.py` (`SPECS`):
`arma`, `arma_f2`, `arma_f4`, `crawler`, `dark_demon`, `flame_lord`,
`phalanx`, `ultimate_phalanx`, `grewon`, `hipogriff`. Run one target at a time:

```sh
python tools/dc_extract/bake_sheet_anim.py --only arma --contact
python tools/dc_extract/bake_sheet_anim.py --list
```

The older named bakers (`bake_boss_sheets.py`, `bake_boss_rows.py`,
`bake_holothurion.py`, `bake_scula.py`, `bake_ovnunu.py`) still write to
`assets/generated`; use them only to read their measured boxes, not to ship
authored art.

**State names are provisional.** Arma/Ultimate Arma names come from the
sheet's own captions (Idle, Laughing, Intro, Flying, Breath Attack, Divebomb,
Hurricane, Demon Fire). For the other bosses the names are row-order
inferences (first body row = `idle`, next = `walk`/`attack`, single recoil =
`hurt`); the numbers are an editor map, not proof of the object AI. Rename in
the Editor as the AI is ported. Boss art is not one sprite:

- `Arma`: body plus projectile/effect rows; do not include the effect as a
  body frame. Palette variants are flags 0/2/4, not separate sheets.
- `Crawler`: body plus `$83/$84/$85` parts; bake body first; parts need their
  own entries or compositing, not one huge crop.
- `Dark Demon`: body `$BC`; `$8A` effects separate.
- `Flame Lord`: `$58` body; `$5C-$5F` are other parts/effects. The left of the
  idle row is the teleport flame.
- `Phalanx`: `$86` first form, `$8D` second form; `$88` is a part; don't mix
  the two forms into one state.
- `Somulo`: use `somulo_native_reference.png` and the measured part pipeline,
  not a blind sheet crop. The sheet has head/neck/jaw drawings and fire rows;
  a single whole-body crop will include background/other parts.
- `Holothurion`, `Scula`, `Ovnunu`: the existing bakers use specific example
  rows; extend only after reading the sheet layout.

### 5.3 Player sheets

- `Firebrand.gif` is the normal/base visual. Map `Idle`, `Walking`, `Jump`,
  `Fall`, `Land`, `Attack`, `Hover`, `Flying`, `Hurt`, `Death`. Ignore
  headbutt/wall cling/enter door/fire crest/overworld/projectile rows unless a
  future schema adds them.
- `Firebrand (Ground/Aerial/Tidal/Legendary/Ultimate).gif` map the same
  character rows to forms 1-5. The game flips the texture horizontally based
  on facing, so extract one facing direction and keep the anchor on the body.
- `spell` is not present on most form sheets. Leave it absent; the renderer
  falls back appropriately. Do not invent a spell animation by reusing an
  attack pose unless the user asks for it.
- Base `player_anim.json` is separate from form 0; if you update the base
  sheet, write `assets/authored/player_anim.json` with all clips, not a partial
  file. If you update a form, write only that form's entry.
- Keep the total across all 11 clips at 64 or less; the editor shows the total.

### 5.4 Enemies 1 / Enemies 2

These are dense multi-species sheets. Work caption-by-caption:

1. Crop the caption band and read the enemy name.
2. Match it to a species via `docs/SPECIES_CENSUS.md`, the current
   `species_anim.json` `source`, and the editor's species name.
3. Extract the idle/walk/attack/hurt/death rows that exist; not every enemy has
   all five.
4. Do not merge two enemies into one species just because they share a sheet.
5. Keep one authored entry per species; preserve entries for other species.

If a caption is ambiguous, do not guess a species id. Add a note in the
extraction log and leave the entry for review.

### 5.5 NPCs

`SNES - Demon's Crest - Miscellaneous - NPCs.png` is a static sheet. Match the
town NPC / guard to `$96` / `$97`; these are not animated enemies. A single
frame plus a sensible anchor is enough unless the sheet clearly shows poses.

## 6. Validation and acceptance

Run all of these before calling a sheet done:

```sh
python tools/editor/test_editor.py
python tools/editor/test_boss_patterns.py
```

Start the editor:

```sh
python tools/editor/server.py
```

Open:

- Enemy: `http://127.0.0.1:8765/#enemy/<species-key>`
- Player base: `http://127.0.0.1:8765/#player/base`
- Player form: `http://127.0.0.1:8765/#player/<0-5>`

In the editor:

- every frame loads (no "loading frame..." placeholder);
- anchors land on the feet; use the stage hitbox;
- frame order/loop flags are correct;
- **Validate** reports no errors; warnings are explained;
- **Save** writes `assets/authored/...`, not generated;
- inspect the contact sheet and the frame strip side by side.

Then render the actual game:

- For a boss/enemy, create a temporary room in the editor (copy an area, put
  the object, use **Render in game**) or use the runtime's temp-room path.
  Do not ship a test room.
- For a player sheet, run the game with `DC_AREA=48 DC_RUN_FRAMES=2` and check
  the asset log says 6 crest-form sheets; pick the form in game if you can.
- `python tools/editor/test_boss_patterns.py` must still print `OK`.

Acceptance checklist:

- [ ] Frame count is within the cap and every frame has a texture.
- [ ] No caption text, labels, background rectangles or adjacent poses.
- [ ] Feet/body are not clipped; anchor is on the body, not the weapon.
- [ ] Animation order is meaningful; no duplicate frames unless intentional.
- [ ] Authored JSON preserves other species/forms.
- [ ] Editor validation passes; contact sheet reviewed.
- [ ] Game/editor preview looks correct.
- [ ] No generated file was overwritten.
- [ ] User-authored rooms and the existing Belth entry are untouched.

## 7. Work order

1. **Multi-part bosses** — Holothurion ($6F), Ovnunu ($16 + $17/$18), Scula
   ($7B/$7C, arm poses), Somulo ($33). These need per-part entries or
   compositing; a whole-body crop is wrong. Crawler's `$83-$85` parts too.
2. **Caption decoding** — the state names for the non-Arma bosses are row-order
   inferences. `sheet_captions.py` plus an image-capable reviewer can decode
   the real labels; rename in `SPECS` and re-bake.
3. **Enemies 1/2** — caption-by-caption; smallest frames, largest count.
4. **NPCs** — static frames; quick pass.
5. **Player base sheet** — only if the ROM capture is ever replaced; the base
   sheet has extra effect rows and must not overwrite `player_anim.json`.

Do one sheet/commit at a time so a bad crop cannot wipe out a whole batch.

## 8. Commit protocol

Only commit:

- `docs/SPRITE_SHEET_EXTRACTION.md`
- `assets/authored/sprites/<new frames>.png`
- `assets/authored/species_anim.json` / `player_forms.json`
- the extraction tool/spec used
- doc updates

Never commit `assets/generated/` (ignored/rebuildable) or `captures/`.
Before committing:

```sh
python tools/editor/test_editor.py
git diff --check
git status --short
```

Commit message example:

```text
Extract full Belth/Arma/... sprite-sheet animations
```

## 9. Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Sprite has a dark rectangle | keyed interior black instead of only background | key only the sheet background colour; keep interior darks |
| Caption letters in frame | band starts in caption row | raise `y0`; remove small components |
| Two poses in one frame | weapon arc bridges columns | use manual boxes for that band |
| Body offset from hitbox | anchor at bbox centre | anchor at largest component centre/bottom |
| Feet float/sink | anchor_y not at body bottom | use body component bottom, not crop bottom |
| Whole form disappears in game | an empty clip was saved | omit empty clips; loader rejects zero-step clips |
| Frames land in `assets/authored/sprites/` root | old flat layout | one subfolder per target (`sprites/<target>/`); never mix extractions |
| Caption strip baked into a frame | band starts inside the caption line | lower `y0`; caption glyph pixels are also cleared explicitly |
| Only first N frames load | over 64 frames | reduce to key poses per state |
| Colors wrong | palette/key changed | nearest-neighbour only; no palette quantisation |
| Wrong species | caption guessed | match census/editor; leave ambiguous for review |

## 10. Quick reference

```sh
# inspect sheet
python -c "from PIL import Image; im=Image.open('docs/sprites/...gif'); print(im.size, getattr(im,'n_frames',1))"

# measure rows/poses and read captions
python tools/dc_extract/sheet_report.py --sheet Arma --bands
python tools/dc_extract/sheet_report.py --sheet Arma --caps --caps-y 30:60
python tools/dc_extract/sheet_captions.py --sheet Arma --out captures/arma_captions.png

# spec-driven baker (list, dry-run, one target, contact sheet)
python tools/dc_extract/bake_sheet_anim.py --list
python tools/dc_extract/bake_sheet_anim.py --only arma --dry-run
python tools/dc_extract/bake_sheet_anim.py --only arma --contact

# Belth reference case
python tools/dc_extract/bake_belth_animation.py

# one-row tool
python tools/sheet_row.py --sheet "docs/sprites/...gif" --species 0x2c \
  --x0 0 --x1 420 --y0 300 --y1 380 --source "..." --state 0

# editor + tests
python tools/editor/server.py
python tools/editor/test_editor.py
python tools/editor/test_boss_patterns.py
```

For the authoritative species->sheet map and existing bakers, see
`docs/TOOLING.md` §"Boss sheet mappings" and the scripts in
`tools/dc_extract/`. For the animation data model and editor workflow, see
`tools/editor/README.md` §"Enemy Editor" and §"Player Editor".
