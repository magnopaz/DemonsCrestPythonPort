# AI-assisted character pipeline (Pipeline C)

Status: planning + tooling landed, no model trained yet.
Last updated: 2026-11-02
Tools: `tools/gen/harvest_dataset.py`, `tools/gen/pixelize.py`
Related: `docs/PLAN_SPRITES_ANIMATION.md` (Pipelines A and B), `docs/TOOLING.md`,
`docs/PROJECT_STATE.md`

---

## 1. Verdict

**Yes, a character-creation pipeline is possible on this hardware — but the
diffusion model does not paint the sprite.**

A 16 GB RTX 5060 Ti is enough to train a style LoRA, and enough to run every
generator in this document locally. What it cannot do is produce a shippable
SNES sprite directly: the model returns 1024 px of soft gradients with
thousands of colours, while the engine loads a ≤64 px image with one transparent
index, binary alpha and at most 15 opaque colours, anchored on the feet. The
pipeline below is therefore **generate → constrain → measure → gate**, with the
constraint step deterministic (a tool, not a prompt) and the gate the same one
the ROM-derived art already passes (`tools/audit_sprites.py --strict` inside
`tools/run_regression.py`).

The realistic split of work:

| Task | AI | Deterministic tool | Human |
|---|---|---|---|
| New enemy / NPC **design** (silhouette, palette, silhouette family) | strong | — | approves |
| Pose **variation** of an existing sprite (walk cycle, hurt, attack) | medium | anchors + palette | fixes 5-10 px per frame |
| Final **sprite sheet** (≤8 frames, ≤15 colours, correct anchors) | never | `tools/gen/pixelize.py` | review |
| **Portraits / title art / illustrations** | strong | palette snap | approves |
| **Backgrounds** for new stages | strong | tile/palette check | composites |

Budget the effort as **"AI drafts, a human finishes"**, not "AI generates a
character". For a 15-colour, 48-px-tall sprite the finishing pass is minutes per
pose, and it is what makes the result look like the original game.

### Quick start (this is the whole loop)

```bash
# 1. dataset  -> ~/datasets/dcrest/  (verified: --sheets all --variants 1 = 1,472
#    images = 736 crops x 2 in ~5 min on the Pi; forms-only = 211 crops in 14 s)
python3 tools/gen/harvest_dataset.py --out ~/datasets/dcrest --sheets all --variants 1

# 2. train on the GPU box (25-45 min) -> dcrest_style_v1.safetensors
rsync -av ~/datasets/dcrest/ moop@192.168.0.21:~/datasets/dcrest/
ssh moop@192.168.0.21 'cd sd-scripts && ./train_dcrest.sh'
rsync -av moop@192.168.0.21:~/sd-scripts/runs/dcrest_style_v1.safetensors ~/models/lora/

# 3. generate a design in ComfyUI (1024 px, one pose, plain background)

# 4. constrain it (deterministic, exits non-zero when illegal)
python3 tools/gen/pixelize.py draft.png --height 48 --tile-pad \
    --out assets/authored/spr_imp_idle_0.png --clip idle --species 0x120

# 5. gate it
python3 tools/audit_sprites.py --assets assets/generated --strict
```

Steps 1, 4 and 5 run today. Steps 2-3 need §7 of this document (the box is up
but has no SSH yet) and a human pass between 3 and 4.

---

## 2. What we actually have (measured 2026-11-02)

`docs/sprites/` holds 61 images. The six Firebrand form sheets are the only
style reference that matters for characters:

| sheet | size | distinct colours |
|---|---|---|
| `Playable Characters - Firebrand.gif` | 697×851 | 145 |
| `Playable Characters - Firebrand (Ground).gif` | 531×420 | 87 |
| `Playable Characters - Firebrand (Aerial).gif` | 527×531 | 85 |
| `Playable Characters - Firebrand (Tidal).gif` | 412×486 | 87 |
| `Playable Characters - Firebrand (Legendary).gif` | 699×529 | 95 |
| `Playable Characters - Firebrand (Ultimate).gif` | 699×649 | 99 |
| `Enemies & Bosses - Enemies 1.gif` | 807×1454 | 256 |
| `Enemies & Bosses - Enemies 2.gif` | 793×1103 | 228 |
| `Miscellaneous - NPCs.png` | 155×496 | 72 |

Three facts follow, and they drive the whole dataset design:

1. **These are not clean sprite sheets.** Every file is a single static frame
   (`n_frames == 1` even on the `.gif` files), fully opaque, with the poses
   sitting on a flat background colour and the sheet captions burned into the
   same image. Anything that trains on the whole sheet learns the caption font
   and the background as much as the sprite.
2. **The colour counts are far above the hardware.** SNES 4bpp sprites get 15
   opaque colours; these sheets carry 85-256 because they are community rips
   that stack many palettes (forms, boss variants, hurt/white flash) in one
   image. A naive LoRA learns that rich palette and then produces art this
   engine cannot load.
3. **The poses are small and sparse.** Cropping per pose with the project's own
   measured boxes (`tools/dc_extract/bake_player_forms.py`) yields **211 base
   poses** across the six forms — normal 40, ground 26, aerial 37, tidal 30,
   legendary 39, ultimate 39 — in **13.9 s** on the Pi
   (`tools/gen/harvest_dataset.py`, verified).

211 poses, doubled by mirroring and tripled by palette variants, is a *style*
dataset: it is enough to teach palette discipline, outline weight and
proportion. It is not enough to teach anatomy — that has to come from the base
model and from a reference image at generation time (Stage 3).

---

## 3. Why that CivitAI LoRA felt bad

The model linked in the request
(`civitai.red/models/2730070`, "SNES Demon's Crest Gargoyle player characters")
is the predictable outcome of the material above, and the four usual causes are
worth naming because our pipeline has to avoid all four:

1. **Trained on whole sheets, not poses.** The model learns sheet layout,
   captions and the flat background; outputs come back with text debris and
   half-transparent grids.
2. **512-px or 1024-px targets derived by interpolation.** Sprites upscaled with
   a smooth filter teach smeared edges; the LoRA then produces "pixel-style"
   art with inconsistent pixel size, which cannot be downscaled cleanly.
3. **A tiny dataset pushed hard.** 100-ish images at a high learning rate and
   many epochs memorises the exact poses it saw: it can reproduce Firebrand
   standing, and falls apart on anything new — which is exactly what a fan game
   needs.
4. **Style mixed with character identity.** One LoRA asked to learn both "look
   like Demon's Crest" and "draw this specific gargoyle". Tagging the character
   separately (see the captions the harvester writes) is what lets the style
   transfer to a *new* character.

None of that is fixed by a bigger GPU. It is fixed by the dataset and the
constraint step.

---

## 4. Hard constraints (from this repo, not from taste)

| limit | value | where |
|---|---|---|
| sprite size | ≤64×64 px, 8×8 tiles | SNES OAM; enforced by `pixelize.py` |
| sprite palette | 15 opaque colours + transparency (4bpp) | SNES; enforced by `pixelize.py` |
| colour space | 15-bit BGR555 (5 bits per channel) | SNES CGRAM; `pixelize.py` snaps |
| alpha | binary only, no semi-transparency | engine loads plain PNG alpha |
| frames per species sheet | **8** (`DC_SPECIES_FRAMES`) | `src/assets.h` |
| frames per object state | **8** (`DC_STATE_FRAMES`) | `src/assets.h` |
| species entries | 64 per table (`DC_SPECIES_MAX`), normal and boss tables | `src/assets.h` |
| player forms | **exactly 6** (`player_forms[6]`, indexed by form id) | `src/assets.h` |
| steps per player form | 64 total across all clips (`DC_ANIM_MAX_STEPS`) | `src/anim.h` |
| new-species id space | ids ≥ `0x100` are free | `Assets_SpeciesSheet()` compares an `int`; ROM species are one byte |
| anchor XOR | `anchor_x` = body centre from the lower part of the pose, `anchor_y` = feet (bottom opaque row); the engine bakes the mirror itself | `src/assets.c`, `bake_player_forms.py` |

Consequences for AI work:

- **8 frames per sheet is the real budget.** A new enemy that idles, walks,
  attacks and gets hurt fits in 8 poses, not in a 20-frame animation. Design for
  frame economy, as the original game did.
- **A 7th playable form needs an engine change** (`player_forms[6]`), not just
  art. New *characters* are cheaper as NPCs, enemies or a replacement form.
- **The engine mirrors, you do not.** Generate the character facing right;
  `assets.c` bakes `flipped` per frame.

---

## 5. Governance: what the AI may touch

The guardrail in `docs/ROADMAP.md` stands: ROM-derived art is the ground truth
and Pipelines A/B own it. Pipeline C is for **content that does not exist in the
ROM**:

- allowed: new enemies, new NPCs, new bosses, new stage backdrops, portraits,
  title/promo art, palette variants of authored sprites, new playable forms that
  *replace* one of the six slots;
- not allowed: regenerating Firebrand, Somulo, Phalanx, Arma or any captured
  sprite "in the same style" and shipping it. That path already failed once
  (`docs/PLAN_SPRITES_ANIMATION.md` §1) and it silently breaks frame matching
  (`tools/verify_frame_match.py`).

Authored output lives outside `assets/generated/` (which is ROM-derived and
git-ignored), in **`assets/authored/`**, with a `.json` sidecar per sprite
carrying the source prompt, the model/LoRA and the seed. Provenance is part of
the asset, because a fan game that grows over years needs to know which pixels
came from where.

---

## 6. The pipeline

```
            docs/sprites (6 form sheets, 211 poses)
                     │
        [1] harvest_dataset.py      per-pose crops, 512², integer nearest
                     │                + captions + palette variants
                     ▼
        dataset/ (≈630 images, ~1 min)
                     │
        [2] sdxl_train_network.py   style LoRA, 16 GB, ~30 min
                     ▼
        lora_dcrest_style.safetensors
                     │
   [3] ComfyUI: txt2img / img2img / IP-Adapter (reference sprite)
                     ▼
        1024² design drafts + chosen master pose
                     │
   [4] pose propagation: pose_refs.py (the game's own measured poses)
       + img2img/ControlNet lineart, 0.50 denoise / 0.85 control
                     ▼
        3-8 frames per clip, one consistent silhouette
                     │
   [5] pixelize.py  background key → integer-free scale → ≤15 colours
                     │   BGR555 snap → despeckle → binary alpha → anchors
                     ▼
        assets/authored/spr_<name>_<clip>_<i>.png + .json
                     │
   [6] compose_species.py -> species_entries.json (budget-checked),
       then the idempotent dict merge into species_anim.json
                     ▼
   [7] audit_sprites.py --strict  +  run_regression.py  +  visual diff
```

### Stage 0 — the no-training baseline (do this before training anything)

Half of what "a character pipeline" needs is achievable with **no LoRA at all**:
take an existing sprite as reference and ask for variations of it.

- **Palette variants of authored sprites:** `pixelize.py --palette <hex list>`
  re-maps an existing sprite to a new palette. Free, deterministic, and it is
  literally how SNES games made "new" enemies.
- **Shape variants:** SDXL img2img at 0.35-0.5 denoise over a sprite upscaled 4×,
  with a prompt naming the change ("same gargoyle, bone-white skin, cracked
  horns").
- **IP-Adapter / reference-only** with the original sprite as the style image:
  this is the cheapest way to stay on-model without training.

Train the LoRA when you need *volume* (dozens of designs, consistent look) or
offline reproducibility. Do not train it before Stage 0 has shown that the
base model can even draw this genre.

### Stage 1 — build the dataset

```bash
cd ~/Projetos/DemonsCrestNativePort
python3 tools/gen/harvest_dataset.py --out ~/datasets/dcrest --sheets forms --variants 2
# verified: 633 images (211 poses × 3), 13.9 s for the 211 base crops
```

What it does, and why each part matters:

1. pose boxes come from `bake_player_forms.py` — the same measured boxes that
   produce the player's own animations, so the crops are the poses we know are
   correct;
2. the flat sheet background is keyed to transparency (captions stay behind,
   because the boxes are inside the pose bands);
3. each pose is padded to a square and upscaled by an **integer** factor with
   nearest neighbour — the pixel grid stays a pixel grid;
4. captions are written per image:
   `dcrest snes style, limited palette, hard pixels, dark outline, firebrand gargoyle demon, ground form, walk pose, side view`
   — style tokens first (what the LoRA should learn), subject tokens after (what
   a tag can switch off);
5. `--variants 2` adds two hue-rotated copies per pose. This is the cheapest
   augmentation available and it matches the source material: the game itself
   reused one silhouette with several palettes.

Add the enemies when the form set alone feels thin:

```bash
python3 tools/gen/harvest_dataset.py --out ~/datasets/dcrest \
    --sheets enemies --variants 1     # component harvesting, approximate boxes
# verified 2026-11-02: 1,050 images (525 base crops) in 265 s on the Pi
#   Enemies 1 233, Enemies 2 182, Flame Lord 35, Crawler 30, NPCs 29, Unused 16
```

`--sheets enemies` uses connected components (≥40 px area, ≥20 px tall) instead
of measured boxes, so it is approximate by nature. Sampling 16 crops and looking
at them: **1 in 16 was junk** (a caption/background fragment) — a ~6 % reject
rate. Delete those before training; a couple of dozen bad images inside a
700-image set is enough to teach the LoRA to draw debris.

Totals for `dataset-v1`: **736 base crops** (211 poses from the six forms + 525
component crops), or **1,683 images** with the palette variants used above.

Dataset hygiene, in order of impact:

- review a contact sheet (`montage`/Pillow) and delete crops with two merged
  characters, captions or stray background;
- keep the mirroring decision in the *trainer* (`--flip_aug`), not in the files;
- no bucketing tricks needed: every crop is a square at the same size.

### Stage 2 — train the style LoRA

Base model choice for 16 GB:

| base | fits 16 GB | licence | why / why not |
|---|---|---|---|
| **SDXL** (any anime/illustration finetune) | yes, 1024 px batch 1-2 | OpenRAIL++-M | the pragmatic first target: fastest iterations, best tooling, and pixel-art LoRAs already exist for it |
| FLUX.1-dev | yes with `--network_train_unet_only` + block swap | non-commercial | better prompt adherence, but slow and its licence restricts output use; fine for a free fan game, move on otherwise |
| Qwen-Image (20B) | only with a quantised base (NF4/fp8) + block swap | Apache-2.0 | best text/prompt following, heaviest to train; not a first LoRA |
| Retro Diffusion `RD_FLUX` | inference only (API/local) | commercial tiers | purpose-built pixel art with animation styles; see Stage 4 |

Recommendation: **SDXL, style LoRA, `--network_train_unet_only`**, because the
text encoder is what makes a style leak into every prompt. Base model on this
box: `/Data/ComfyUI/models/checkpoints/ilustmix_v9.safetensors` (verified SDXL
architecture) — the LoRA then loads back into the same family ComfyUI already
loads, so nothing has to be downloaded.

The run is wrapped in `/Data/ml/train_dcrest.sh` (verified: 60-step calibration
run produced a valid 170 MB LoRA). The command it issues:

```bash
accelerate launch --num_cpu_threads_per_process 4 sdxl_train_network.py \
  --pretrained_model_name_or_path /Data/ComfyUI/models/checkpoints/ilustmix_v9.safetensors \
  --dataset_config /Data/ml/datasets/dcrest.toml \
  --output_dir /Data/ml/runs --output_name dcrest_style_v1 \
  --network_module networks.lora --network_dim 32 --network_alpha 16 \
  --network_train_unet_only \
  --resolution 512 --train_batch_size 2 --gradient_checkpointing --sdpa \
  --max_train_steps 1600 --save_every_n_steps 400 --save_every_n_epochs 1 \
  --save_model_as safetensors --save_precision bf16 \
  --learning_rate 1e-4 --text_encoder_lr 0 --lr_scheduler cosine --lr_warmup_steps 100 \
  --optimizer_type AdamW8bit --mixed_precision bf16 \
  --cache_latents --cache_latents_to_disk --shuffle_caption --keep_tokens 5 \
  --max_data_loader_n_workers 2 --seed 42 --no_half_vae \
  --logging_dir /Data/ml/runs/logs --log_with tensorboard
```

The dataset config (`/Data/ml/datasets/dcrest.toml`) is what carries bucketing
and captions: `caption_extension=".txt"`, `batch_size=2`, `resolution=512`,
`enable_bucket=true`, buckets 256-768, `keep_tokens=5` (the five style tokens of
each caption stay fixed while the rest is shuffled).
```

`accelerate config` answers: no distributed, bf16, no DeepSpeed, **no** TPU,
all good with gradient checkpointing.

Settings that matter, and what they buy:

| setting | value | reason |
|---|---|---|
| `network_dim` / `alpha` | 32 / 16 | a style is a low-rank change; dim 64+ memorises poses |
| `network_train_unet_only` | on | stops the style from hijacking every prompt |
| `resolution` | 512 with buckets | sprites are small; 1024 wastes VRAM and blurs pixels |
| `learning_rate` | 1e-4 (unet) | 3e-4 burns the dataset in <300 steps at this size |
| `max_train_steps` | 2000-3000 | with 630 images that is 3-5 epochs |
| `flip_aug` | off | the source is asymmetric on purpose; mirroring is cheap to add later |

Save checkpoints every 2 epochs and **evaluate them, do not trust the loss**:
generate the same prompts with each checkpoint and pick the one where the
subject reads at 48 px after `pixelize.py`. In practice the last checkpoint is
rarely the best one — pixel art degrades into noise as the LoRA gets stronger.

That happened here, measured: `dcrest_style_v1` at **step 1600** versus
**step 800**, same prompt and seed, both pixelized to 48 px — the 1600-step one
came back with brighter, speckled highlights that alias into isolated sparkle
pixels at 48 px, while the 800-step one merges into broader, cleaner clusters.
**Use step 800 as the default for sprite work** and raise the weight
(`strength_model`) if the style is too weak, instead of training longer.

### Stage 3 — generate designs

Work in ComfyUI on the box (it is the fastest way to iterate and it exposes
ControlNet/IP-Adapter without code). For a batch, drive it headless over the
HTTP API — `tools/gen/workflow_sdxl_lora_api.json` is the API-format workflow
that was verified end to end on this box:

```bash
# on the box; ComfyUI must be running (./.venv/bin/python main.py --port 8188)
python3 - <<'PY'
import json, urllib.request
wf = json.load(open("tools/gen/workflow_sdxl_lora_api.json"))
wf["3"]["inputs"]["text"] = "dcrest snes style, limited palette, hard pixels, dark outline, "\
    "a hunched grave imp with a cracked stone mask and bone claws, idle pose, side view, "\
    "plain background, no text"
req = urllib.request.Request("http://127.0.0.1:8188/prompt",
    data=json.dumps({"prompt": wf}).encode(),
    headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=30)))   # -> prompt_id
PY
# poll /history/<prompt_id>, then pull the PNGs from ComfyUI/output/
```

First verified batch (LoRA `dcrest_style_v1`, SDXL base `ilustmix_v9`, 1024 px,
28 steps, CFG 6, seed 4242, 4 images): **all four came back as single
pixel-art creatures with hard pixels, a dark outline and a flat background**,
i.e. directly usable by Stage 5 — no sheet layout, no captions, no second
subject. The style LoRA does its job; the *prompt* controls subject choice only
loosely (a "cracked stone mask" request came back as a bone skull), which is
exactly why Stage 0 (IP-Adapter/reference) exists.

Recipe that survives pixelization:

- resolution 1024×1024, then let `pixelize.py` decide the final size;
- prompt skeleton:
  `dcrest snes style, limited palette, hard pixels, dark outline, <subject>, <pose>, side view, plain background, no text`
- negative: `text, caption, watermark, blurry, anti-aliasing, gradient background, several characters, sprite sheet, grid`
- CFG 5-7, 28-35 steps, LoRA weight 0.6-0.8 (higher melts the silhouette);
- **one subject, one pose, one plain background per image** — a full sheet never
  survives downscaling;
- keep the seed of every design you accept (the `.json` sidecar records it).

Then, to keep proportions on-model for a *new* character derived from an
existing one, add **IP-Adapter** (style/character reference = the closest
existing sprite) or **ControlNet lineart/canny** from a hand-blocked silhouette.
An IP-Adapter reference at weight 0.5-0.7 is usually the difference between
"random demon" and "belongs in this game".

For new stage backdrops the same rules apply with 2 changes: generate at
1024-1536 px wide, and keep the count of distinct colours low enough that the
tile/palette check in Stage 6 passes.

### Stage 4 — animation consistency (the hard part)

Diffusion cannot keep a character consistent across frames. Three workable
routes, best first:

1. **Master pose + ControlNet OpenPose propagation (recommended).** Generate one
   master. Draw or reuse a pose skeleton for each remaining frame (a stick
   figure, 5 minutes in any editor), run img2img at 0.45-0.6 denoise with the
   skeleton as ControlNet input and the master as IP-Adapter reference. The
   silhouette stays, the limbs move.
2. **Block-in over an existing animation — the route that shipped the first
   enemy, and it needs no download.** Reuse the poses and timing of a species the
   game already animates, and repaint the new creature on top with
   **img2img + the SDXL lineart ControlNet** the box already has:

   ```bash
   # 1. cut the source poses with the project's own measured boxes
   python3 tools/gen/pose_refs.py --species 0x2c --out ~/datasets/refs/imp \
       --size 1024 --labels walk0,walk1,walk2,walk3
   # 2. upload the four PNGs into ComfyUI's input/ and repaint each one
   #    (img2img + ControlNetApplyAdvanced + LoRA, workflow in Stage 3)
   # 3. constrain every frame onto ONE palette (see below)
   python3 tools/gen/pixelize.py repaint.png --height 40 --tile-pad \
       --palette 485040,586050,... --out px/walk0.png --clip walk
   ```

   **Settings that held the pose** (measured, two rounds): denoise **0.50** with
   ControlNet strength **0.85**. The first attempt (denoise 0.60 / strength
   0.65) homogenised the four walk poses into nearly the same stance and let the
   hurt frame drift to a different creature; lowering the denoise and holding
   the control harder fixed both. The hurt frame needs ~0.52/0.80 — enough to
   change the pose, not enough to change the character.

   **Palette lock is what makes the frames a set.** Run `pixelize.py` once on the
   best frame, read the 15 colours out of its `.json` sidecar, then pass that
   list as `--palette` for every other frame. Two frames generated minutes apart
   will not agree on their palette on their own, and palette drift is what makes
   a cycle look like four different creatures.
3. **A pixel-art animation model.** Retro Diffusion's animation styles
   (`Idle`, `Attack`, `Jump`, `Crouch`, `Four Angle Walking`, `Big Animation`)
   take a starting frame and return a frame sequence at 64×64 or 128×128. That
   is the closest thing to "generate a sprite sheet" that exists today. Treat
   the output as a draft: it still goes through Stage 5 and a human pass.

Whatever the route, obey the engine budgets: **≤8 frames per species sheet**,
`states` indices ≤8, and the anchor rule from §4. Fewer, better-posed frames
beat more frames.

### Stage 5 — constrain (deterministic)

```bash
python3 tools/gen/pixelize.py drafts/imp_01.png --height 48 --tile-pad \
    --out assets/authored/spr_imp_walk_0.png --clip walk --duration 7 --species 0x120
```

Verified twice, on both a synthetic and a real input:

- soft 768² "diffusion-like" input (a real sprite upscaled 8× with a Gaussian
  blur, a flat background and colour noise) → **32×48, 15 colours,
  BGR555-aligned, binary alpha, one blob**, anchor `(11, 48)`;
- a **real LoRA output** from Stage 3 (1024², flat background) → **40×32** and
  **56×48**, 15 colours each, one blob, anchors `(18, 32)` and `(27, 48)`, and
  in both cases the creature still read as the same skeleton it was at 1024 px —
  the 48 px version kept the skull, jaw, ribcage, arm and foot claws legible;
- a 96-px request is **rejected** with `53x96 exceeds the 64px OAM limit`, so the
  failure path is tested too.

Practical rule from those runs: for a regular enemy ask for **32-48 px tall**;
below 32 px the palette cut starts merging claws and torso into single blobs.

Options that matter:

| flag | use |
|---|---|
| `--height` | target sprite height: 24-32 enemy, 40-48 boss, 48-64 playable |
| `--colors` | 15 by default; lower (11-13) for a flatter, more authentic look |
| `--palette hex,…` | force the game's palette discipline, e.g. reuse the player's own 15 colours |
| `--bg auto\|#RRGGBB\|alpha` | keying: border colour by default, `alpha` trusts the input's matte |
| `--filter box\|nearest\|lanczos` | `box` keeps tone; `nearest` keeps an existing pixel grid |
| `--dither` | 4×4 ordered dither for sky/gradient backgrounds; **never** for sprites |
| `--min-component 4` | despeckle; raise it when the generator leaves crumbs |
| `--tile-pad` | pads to 8×8 tiles, bottom-centred, and reports the OAM footprint |
| `--mirror` | also writes `_flip.png` for comparison against the engine's own flip |
| `--json` | metadata sidecar: anchors, palette, blob sizes, source, errors |

The tool exits non-zero when a hard constraint is violated (too many colours,
>64 px, non-binary alpha, more than 6 blobs). Wire it into any batch script and
treat a non-zero exit as "do not ship".

### Stage 6 — integrate

`tools/gen/compose_species.py` turns a set of pixelized frames into that entry,
enforcing the budgets and re-checking every PNG (size, palette, alpha) instead
of trusting the previous step:

```bash
python3 tools/gen/compose_species.py --spec imp.json --out assets/authored
# species 0x120 (288): 7 frames, states ['0', '1'], hurt=6, default=4
#   spr_120_walk_00.png  32x40 15 colours anchor=(14,40) dur=7   ... etc
```

The spec is the only thing to write by hand:

```json
{ "species": 288,
  "frames": [
    { "src": "px/walk0.png", "clip": "walk", "duration": 7, "anchor_x": 14, "anchor_y": 40 }
  ],
  "states": { "0": [4, 5], "1": [0, 1, 2, 3] },
  "hurt": 6,
  "default": 4 }
```

**`species_anim.json` is an object keyed by the species id in lowercase hex** —
`{"species": {"2c": {...}, "120": {...}}}` — exactly what
`bake_enemy_sheets.py` writes. An array is rejected by the audit with *"no
'species' object"*, so a merge that appends to a list silently breaks the gate
(this bit the first version of this document). A real entry:

```json
{ "species": { "120": {
  "species": 288, "boss": false,
  "frames": [
    { "texture": "spr_120_walk_00.png", "anchor_x": 14, "anchor_y": 40,
      "duration": 7, "width": 32, "height": 40 }
  ],
  "states": { "0": [4, 5], "1": [0, 1, 2, 3] },
  "hurt": 6, "default": 4,
  "source": "Pipeline C (docs/AI_CHARACTER_PIPELINE.md)" } } }
```

`states` is indexed by the engine's **object state** (`o->state`, see
`src/render.c`), so state 0 is idle and state 1 is walk for the enemies this
project ships; `hurt` and `default` cover the other two render paths.

Merge idempotently — dict update, keyed by hex, so re-running is a no-op:

```bash
python3 - <<'PY'
import json, pathlib
assets = pathlib.Path("assets/generated")
authored = pathlib.Path("assets/authored")
target = assets / "species_anim.json"
data = json.loads(target.read_text()) if target.exists() else {"species": {}}
data.setdefault("species", {})
incoming = json.loads((authored / "species_entries.json").read_text())["species"]
data["species"].update(incoming)
target.write_text(json.dumps(data, indent=1) + "\n")
print("species entries:", len(data["species"]))
PY
```

Then copy the PNGs next to the JSON (`assets.c` resolves textures relative to
the same directory) and re-run the gates. Verified on a scratch tree:

```
audit: 0 species, 0 frames, 0 error(s), 0 warning(s)   # empty tree
audit: 1 species, 7 frames, 0 error(s), 0 warning(s)   # after the merge, --strict, exit 0
```

Player form entry (`player_forms.json`, schema read from `src/anim.c`) is a
different shape — a list of forms, each with named clips:

```json
{ "forms": [ { "form": 6,
  "clips": { "idle": { "loop": true,
    "steps": [ { "texture": "fb_new_idle_0.png", "anchor_x": 20,
                 "anchor_y": 44, "duration": 8 } ] } } } ] }
```

### Stage 7 — gates (non-negotiable)

```bash
python3 tools/audit_sprites.py --assets assets/generated --strict
python3 tools/run_regression.py
```

`audit_sprites.py` rejects missing textures, anchors outside the image, a
species reusing another species' exact image, and fragmented captures; the
regression runs it whenever `species_anim.json` exists, so a bad bake cannot
enter the build. On top of that, for every new character:

1. **Silhouette check**: render the sprite at 100 % next to a native sprite;
   if the outline weight or the palette warmth differs, it will read as
   "foreign" in-game.
2. **Anchor check**: `anchor_y` must be the feet for every frame of a clip;
   drift shows up as vertical jitter, which is the bug that made Somulo "slide".
3. **Colour audit**: `pixelize.py` reports the palette; nothing above 15 opaque
   colours, nothing above BGR555 precision.
4. **In-engine screenshot**: `DC_DEMO`/screenshot path plus a visual diff
   against the authored PNG, the same way `verify_frame_match.py` proves the
   player's cycle.

---

## 7. The GPU box

Target: `192.168.0.21`, RTX 5060 Ti 16 GB (Blackwell, `sm_120`), reachable from
this host over the LAN.

**Measured 2026-11-02, from the Pi over SSH:** host `moopc`, Ubuntu 26.04.1,
kernel 7.0.0-29, 12 cores, Python 3.14.4, NVIDIA driver 595.99.02 (CUDA 13.2),
RTX 5060 Ti 16,311 MiB, compute capability **(12, 0)**; `/` has 58 GB free and
`/Data` 114 GB. The generation stack is already installed and this is the part
that changes the plan:

| what | where | state |
|---|---|---|
| ComfyUI (git 7a28332, Oct 2026) | `/Data/ComfyUI` | installed, own `.venv` |
| torch in that venv | — | **2.14.1+cu130, works on sm_120** (bf16 matmul on the GPU verified) |
| SDXL checkpoints | `models/checkpoints` | 5 Illustrious-family SDXL finetunes (6.9-7.4 GB each) |
| LoRAs | `models/loras` | 45, **none is pixel-art/retro** |
| ControlNet | `models/controlnet` | `illustriousXLLineart_v10` (SDXL lineart) + sd15 lineart |
| CLIP vision | `models/clip_vision` | `clip_vision_h` (SDXL) |
| IP-Adapter | `models/ipadapter` | **empty** — download one to use Stage 3's reference route |

Consequence: **no base model has to be downloaded to train the style LoRA.** An
Illustrious checkpoint is SDXL architecture (verified: dual text encoder, 2,515
tensors), which is exactly what `sdxl_train_network.py` expects, so
`ilustmix_v9.safetensors` is a ready base and the LoRA loads back into the same
ComfyUI family the box already uses.

### 7.1 Reach it (already true on this box)

```bash
# from the Pi: is anything listening now? (verified: prints 'open')
python3 -c "import socket;s=socket.socket();s.settimeout(2);print('open' if s.connect_ex(('192.168.0.21',22))==0 else 'closed')"
```

The box already runs Ubuntu's `openssh-server`, so nothing to install. For a
fresh machine the commands are, on Ubuntu/Debian:

```bash
sudo apt install -y openssh-server && sudo systemctl enable --now ssh
```

and on Windows 11 (Administrator PowerShell), if the box is ever rebuilt on
Windows:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

### 7.2 Key authorization (never paste a password into chat)

Login user on the box: **`moop`** (confirmed 2026-11-02). The Pi's key is **not
authorized yet** — a public-key attempt returns
`Permission denied (publickey,password)`, so `authorized_keys` still has to be
written there, once, by hand.

This host already has a dedicated key for this purpose. Its public half:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDsIp59OgKk7GW2Yw/0rhk1pMpCZiNnRrVuWM0IsQ1OL hermes-raspbuntu4
```

Run **on the GPU box** (Linux / WSL):

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDsIp59OgKk7GW2Yw/0rhk1pMpCZiNnRrVuWM0IsQ1OL hermes-raspbuntu4' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

On Windows, write the same line into
`C:\Users\<you>\.ssh\authorized_keys` (note: administrators need
`C:\ProgramData\ssh\administrators_authorized_keys`).

Then from the Pi:

```bash
ssh -i ~/.ssh/id_ed25519_hermes moop@192.168.0.21 nvidia-smi
```

### 7.3 The training stack (installed 2026-11-02)

Two rules: **do not touch ComfyUI's venv** (it is the box's working generator),
and **do not inherit an old wheel** (`sm_120` needs CUDA 13.x builds; a `cu12.6`
wheel stops at `sm_90` and every op dies with "no kernel image is available" —
that is the only real Blackwell trap).

```bash
mkdir -p /Data/ml && cd /Data/ml
git clone --depth 1 https://github.com/kohya-ss/sd-scripts
/usr/bin/python3 -m venv kohya-venv
./kohya-venv/bin/pip install --upgrade pip wheel setuptools
# match the version ComfyUI already runs, so both venvs agree with the driver
./kohya-venv/bin/pip install torch==2.14.1 torchvision \
    --index-url https://download.pytorch.org/whl/cu130
cd sd-scripts && ../kohya-venv/bin/pip install -r requirements.txt
```

**Gotcha, cost me a failed install:** `sd-scripts/requirements.txt` ends with
`-e .`, so `pip install -r` must run **from inside the cloned repo**; running it
from the parent directory fails with *"does not appear to be a Python project"*.

Verified on the box after install: Python 3.14.4, `torch 2.14.1+cu130`,
`get_device_capability() == (12, 0)`, `bitsandbytes 0.50.2`, `diffusers 0.40.0`,
`accelerate 1.15.0`, `transformers 5.17.0`, and `sdxl_train_network.py --help`
imports cleanly.

Files placed on the box:

| path | role |
|---|---|
| `/Data/ml/kohya-venv` | training venv (torch cu130 + sd-scripts) |
| `/Data/ml/sd-scripts` | kohya |
| `/Data/ml/train_dcrest.sh` | the run script (`STEPS=`, `BASE=`, `NAME=` overridable) |
| `/Data/ml/datasets/dcrest.toml` | dataset config (512 px, batch 2, buckets 256-768) |
| `/Data/ml/datasets/dcrest` | the crops, rsynced from the Pi |
| `/Data/ml/runs` | LoRA checkpoints and tensorboard logs |

ComfyUI is already there; start it only when generating:

```bash
cd /Data/ComfyUI && ./.venv/bin/python main.py --listen 0.0.0.0 --port 8188
```

Still missing for the full Stage 3-4 route: an SDXL **IP-Adapter** (the
`ipadapter` folder is empty) and, if you want skeleton-driven pose propagation,
an **OpenPose** ControlNet for SDXL — the box has lineart only. Both are
downloads of a few hundred MB, not blockers for training.

### 7.4 Offload pattern

Datasets are tiny — the full `--sheets all --variants 1` set is **16 MB** for
1,472 PNGs at 512² (measured; transparent backgrounds compress hard) — and the
Pi builds them. So:

```bash
rsync -av ~/datasets/dcrest/ moop@192.168.0.21:/Data/ml/datasets/dcrest/
ssh moop@192.168.0.21 'STEPS=2400 /Data/ml/train_dcrest.sh'
rsync -av moop@192.168.0.21:/Data/ml/runs/dcrest_style_v1.safetensors \
    /Data/ComfyUI/models/loras/     # on the box: same path, no copy needed
```

Generation can run headless too (`ComfyUI` with a workflow JSON driven over
its HTTP API on port 8188), which is what a batch of 40 designs needs; keep the
GUI for iterating on the prompt.

---

## 7.5 The first complete enemy (worked example, 2026-11-02)

Species **`0x120`** ("grave imp"), the first character to go through every stage.
Recorded here because the numbers are the recipe:

| step | what was done | result |
|---|---|---|
| source poses | `pose_refs.py --species 0x2c` — the Scavenger Demon's four measured walk boxes | 4 refs at 1024², one clean pose each |
| repaint | img2img + `illustriousXLLineart_v10` + LoRA step 800, denoise 0.50 / control 0.85, seed 4242 | 4 walk + 2 idle + 1 hurt, same creature in all 7 |
| constrain | `pixelize.py --height 40 --tile-pad`, palette locked from the first accepted frame | 7 × **32×40**, 15 colours, binary alpha, 1 blob, anchor (14, 40) |
| compose | `compose_species.py` with `states {"0":[4,5], "1":[0,1,2,3]}`, `hurt 6`, `default 4` | `species_entries.json`, 7 frames |
| gate | dict merge into a scratch `species_anim.json` + `audit_sprites.py --strict` | `1 species, 7 frames, 0 error(s), 0 warning(s)` |

Files: `assets/authored/spr_120_{walk_00..03,idle_04,idle_05,hurt_06}.png` +
`assets/authored/species_entries.json`.

What this example does **not** do, deliberately: it does not put the imp in a
room. A species entry only makes the art loadable — an area still needs an
object placed with that species id (`apply_boss_table.py` / the room JSON), and
that is gameplay work, not art. The walk is also subtle: the source walk poses
of `$2C` differ by only a few pixels, so the repainted cycle reads as a shuffle
at 40 px. For a stronger cycle, source the poses from `$08` (Ogre Demon) or
hand-edit two of the four frames — which is exactly the "AI drafts, a human
finishes" line from §1.

---

## 8. Time and cost

Local, one-time:

Everything below is **measured on this hardware**, not estimated:

| step | where | measured |
|---|---|---|
| dataset, forms only (211 crops) | Pi | 14 s |
| dataset, `--sheets all --variants 1` (1,472 images) | Pi | ~4 min, 16 MB |
| rsync dataset to the box | LAN | 7 MB/s over ssh, seconds |
| **latent cache, 1,472 images at 512 px** | 5060 Ti | **8.5 min** (2.9 img/s), one-time — `--cache_latents_to_disk` makes later runs skip it |
| **training, batch 2, 512 px, bf16, AdamW8bit, grad-checkpointing** | 5060 Ti | **1.13 it/s** → 1,600 steps ≈ **24 min**, 2,400 steps ≈ 35 min |
| VRAM during training | 5060 Ti | **9.6 GB of 16.3**, ~90 W of 180 W, 2.78 GHz, 51 °C |
| LoRA output, `dim 32` | — | **170 MB** (2,166 tensors: 722 modules × down/up/alpha, standard ComfyUI naming) |
| ComfyUI boot + API | 5060 Ti | ComfyUI 0.42 serves `/system_stats` (verified) |
| per accepted character: 8 frames pixelized + anchored | Pi | ~10 s per frame tool time + 30-60 min human |

Two things the numbers say:

- **VRAM is not the limit, the dataloader is.** 9.6 GB of 16.3 GB used, GPU
  utilisation 16-30 %: the card idles waiting for batches. Raise
  `--max_data_loader_n_workers` (2 → 6-8) and, if `it/s` does not move, raise
  `--train_batch_size` to 3-4 (there is room). Re-measure instead of assuming.
- **dims and resolution cost nothing here.** At 9.6 GB there is headroom for
  `network_dim 64` or 768 px buckets; the trade is quality (a bigger rank
  memorises poses faster), not memory.

Cloud/API alternative: Retro Diffusion and PixelLab both sell grid-aligned
pixel-art generation (and, in Retro Diffusion's case, animation styles) on
subscription/credits; check current pricing on their sites. Use them to
**prototype the look in an afternoon**; train locally when you need volume,
offline reproducibility and no per-image cost.

What the money does not buy: the finishing pass. Budget it either way.

---

## 9. Failure modes (seen in this project and in the field)

- **Training on sheets instead of poses** → captions and background bleed in.
- **Smooth upscaling** → inconsistent pixel size that cannot be downscaled
  cleanly; always integer nearest for training data.
- **Over-trained style LoRA** → pixel art turns into noise textures; evaluate
  checkpoints at 48 px, not at 1024 px.
- **More than one subject per image** → downscaling merges them; one sprite per
  generation.
- **Ignoring the engine budgets** → beautiful 12-frame walk cycles that cannot
  load (`DC_SPECIES_FRAMES 8`).
- **Anchoring from the crop instead of the feet** → jitter; this is exactly the
  bug documented in `docs/PLAN_SPRITES_ANIMATION.md` §1.
- **Shipping generated art over ROM-derived art** → breaks frame matching and
  crosses the project's guardrail.
- **Trusting the tool's exit code alone** → `pixelize.py` proves constraints,
  not intent. Look at the sprite.

---

## 10. Roadmap

- [x] Measure the sprite material and the engine budgets (this document)
- [x] `tools/gen/harvest_dataset.py` — pose crops + captions + palette variants
- [x] `tools/gen/pixelize.py` — constraint pass with hard gates
- [x] SSH to `moop@192.168.0.21` with the Pi's key (§7.1-7.2)
- [x] Training venv on the box: torch 2.14.1+cu130 + kohya, `get_device_capability() == (12, 0)`
- [x] Harvest `--sheets all --variants 1` (1,472 crops, 16 MB) and rsync to `/Data/ml/datasets`
- [x] Calibration run: 60 steps at **1.13 it/s**, valid 170 MB LoRA written
- [ ] Review the contact sheets, delete junk (≈6 % of the enemy crops), freeze `dataset-v1`
- [x] Full `dcrest_style_v1` run: 1,600 steps, 19m47s, loss 0.0433, 5 checkpoints
- [x] Checkpoint evaluation at 48 px → **step 800 beats step 1600** (see Stage 2)
- [x] First sprite end-to-end: LoRA output → `pixelize.py` → 56×48, 15 colours, 1 blob
- [ ] Download an SDXL IP-Adapter (+ OpenPose ControlNet if pose propagation is used)
- [x] First complete enemy: species `0x120`, 7 frames, `audit_sprites --strict` clean (§7.5)
- [ ] Place a new species in a room (object entry) and see it move in-engine
- [ ] Stronger walk cycle: source poses from `$08`, or hand-edit 2 of the 4 frames
- [ ] Wire `pixelize.py`'s non-zero exit into `tools/run_regression.py`
- [ ] Portraits/title art pass (same LoRA, palette snap only)
- [ ] Decide the engine change for a 7th form (`player_forms[6]`) if a new
      playable character is ever wanted

---

## Appendix A — prompt recipes

Style LoRA trigger (from the harvester captions): `dcrest snes style`.

Enemy:
```
dcrest snes style, limited palette, hard pixels, dark outline,
a hunched grave-imp with a cracked stone mask and bone claws, idle pose,
side view, plain background, no text
```
Negative:
```
text, caption, watermark, sprite sheet, grid, blurry, anti-aliasing,
gradient background, several characters, photo, 3d render
```

Portrait / promo art: same trigger, drop `side view`, add
`illustration, dramatic lighting` and generate at 1024 without `--height`
constraints — but still palette-snap before it goes in the game.

## Appendix B — calibration checklist

Run once, on the box, before trusting any number in this document:

1. `nvidia-smi` — driver ≥ 570, 16 GB visible.
2. `torch.cuda.get_device_capability()` → `(12, 0)`.
3. One warm-up step of `sdxl_train_network.py` with the real dataset → note
   `it/s`, multiply by `max_train_steps`.
4. `pixelize.py` on one accepted design → confirm 15 colours, binary alpha,
   ≤64 px, sane blobs.
5. `audit_sprites.py --strict` on the merged asset tree → zero hard errors.

## Appendix C — file map

| path | role |
|---|---|
| `tools/gen/harvest_dataset.py` | sheets → training crops (pose boxes from the project's bakers) |
| `tools/gen/pixelize.py` | any image → engine-legal sprite + metadata sidecar |
| `tools/gen/workflow_sdxl_lora_api.json` | ComfyUI API workflow (SDXL + style LoRA), verified on the box |
| `tools/gen/pose_refs.py` | cut pose references from an existing species' measured boxes |
| `tools/gen/compose_species.py` | frames → budget-checked `species_entries.json` |
| `tools/dc_extract/bake_player_forms.py` | the measured pose boxes (shared, do not duplicate) |
| `tools/audit_sprites.py` | structural gate for `species_anim.json` |
| `tools/run_regression.py` | full acceptance run |
| `assets/authored/` | AI-authored, git-tracked art + provenance JSON |
| `assets/generated/` | ROM-derived, git-ignored, rebuilt by `tools/build_assets.sh` |
| `~/datasets/dcrest/` | training crops (outside the repo) |
