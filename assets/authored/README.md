# assets/authored

Hand-made and AI-assisted art that is **not derived from the ROM**. This
directory is git-tracked, unlike `assets/generated/` (rebuilt by
`tools/build_assets.sh` and git-ignored).

Rules:

1. One sprite per file, named `<prefix>_<subject>_<clip>_<index>.png`
   (e.g. `spr_imp_walk_0.png`, `fb_new_idle_1.png`).
2. Every PNG has a sibling `.json` from `tools/gen/pixelize.py` with the
   anchors, the palette and the provenance of the image (`source`). Add
   `model`, `lora` and `seed` by hand when the sprite came from a generator —
   a fan game that grows for years needs to know where a pixel came from.
3. Species ids for authored content start at `0x100`; ROM species are one byte,
   so `0x100+` cannot collide (`Assets_SpeciesSheet()` compares an `int`).
4. Respect the engine budgets before committing: ≤64x64 px, ≤15 opaque colours,
   binary alpha, `anchor_y` on the feet, ≤64 frames per species sheet
   (`DC_SPECIES_FRAMES`; the Python port extends the C reference's 10),
   `player_forms[6]` for playable forms.
5. `species_entries.json` in this directory is the merge payload for
   `assets/generated/species_anim.json`, written by
   `tools/gen/compose_species.py`. That file is an object keyed by species id in
   lowercase hex (`{"species": {"120": {...}}}`); merge with a dict update so
   re-running is idempotent. The snippet is in
   `docs/AI_CHARACTER_PIPELINE.md` §6.
6. The visual Enemy Editor writes `species_anim.json` (only the entries it
   changed), `enemies.json` (stats/attacks/sounds) and imported PNGs under
   `sprites/` here. The Player Editor writes `player_anim.json` (base sheet) and
   `player_forms.json` (one entry per crest form). The runtime merges those over
   the generated entries at startup, so no manual merge is needed for
   editor-authored content. The Map Builder writes `rooms/` and the game
   prefers those rooms over `assets/generated/room_area*.json`.
7. Current contents: species `0x120`, "grave imp" — 4 walk + 2 idle + 1 hurt,
   32x40 each, 15 colours, the first enemy built by Pipeline C (§7.5 of that
   doc); species `0x68`, Belth — 32 frames (idle, taunt, walk, attack, jump,
   charge, turn, hurt, death) baked from the labelled boss sheet by
   `tools/dc_extract/bake_belth_animation.py`; and the room overrides in
   `rooms/`.

Everything here still has to pass the same gate as the ROM art:

```
python tools/audit_sprites.py --assets assets/generated --strict
```
