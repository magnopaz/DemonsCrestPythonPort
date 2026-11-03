# Plan — Original *Demon's Crest* Fully Playable

**Rewritten:** 2026-10-24 · **Basis:** the 113 extracted rooms, 186 save probes,
the sprite/map/reference folders in `docs/`, and the current build's checks.
The step-by-step history lives in `docs/PROJECT_STATE.md`; this document only
answers two questions: **what can be done with the material at hand**, and
**what still needs input**.

---

## 1. Status snapshot

| Dimension | Now | Evidence |
|---|---|---|
| Rooms | **113/113 load** (areas 0–112) | `check_areas.py` |
| Campaign loop | title → area 0 → clear → overworld → travel → boss → ending | `check_playthrough.py` 6/6 |
| Boss entries clearing | 7/7 | `check_campaign.py` |
| Regression | **PASS** — demos, boss clears, 6 doors, endings, save/password | `run_regression.py` |
| Navigation (graph) | **103/113 (91%) reachable via real doors**; 113/113 with gates | `check_navigation.py` |
| Doors known | 139 edges (107 extracted/observed + 32 from the level notes) | `area_graph.json` |
| Named rooms | **36** (33 with a community map) | `room_names.json` |
| Backdrops (BG2) | **22 areas** | `bg2_area*_pal*.png` |
| Species sheets | **30** loaded (silently capped at 16 until this week) | `species_anim.json` |
| Object placements | 294 (14 boss objects) | room JSONs |
| Save probes | 186 dumps (placements, OAM, CGRAM, VRAM, text, markers) | `oracle_probe/` |
| Text | 518 strings, paged dialogue, talkable NPCs, two shop stocks | `text_strings.json` |
| Endings | 4 variants, completion-based gating, regression-checked | `endings.json` |
| Overworld | real Mode 7 map, rotation/zoom, **17 stage markers drawn** | `map_markers.json` |
| Bosses ported | **Somulo** — pattern, five poses, fireball + firewall art, six hits | Steps 68–70 |

**Constraints that shape everything below**

1. Your `.sav` states restore WRAM/VRAM **but not the CPU** (they boot to the
   copyright screen), so they are *data snapshots*, not resumable gameplay.
2. A **fresh recomp session can be driven** with synthetic input (verified), but
   only as far as the title screen allows without progression.
3. Save coordinates are **level-space**; rooms are **chunk-space** (a map is a
   composite of several areas), so doors are re-pointed or clamped, never copied.
4. Area ids **above 112 are invalid** (`$008D=118` decodes to garbage tables).
5. The sprite folders mix **ripped sheets** (usable) with **hi-res fan
   animations** (reference only — they clash with the SNES style).

---

## 1b. Deliveries (MVP framing)

The work is now organised as playable slices, each with a definition-of-done
table, rather than only as systems:

| delivery | scope | state |
|---|---|---|
| **MVP 1 — Somulo** | new game → colosseum → the six-hit dragon fight → gate to area 34 | **done**, see [`MVP_SOMULO.md`](MVP_SOMULO.md) |
| **MVP 2 — Murkland cemetery** | area 2 fully playable: rooms, enemies, urns, doors, stage boss | next |
| MVP 3+ | more stages, the shops/library, endings | later |

## 2. What I can do with what I have — no new input

Ordered by player-visible value per unit of work.

### A1. Firebrand form sprites — **done (clean component pass)**

The first band-split pass made the animation worse, so the captured
`player_anim` became the default while the cutting was fixed. The current baker
uses measured per-sheet clip regions and takes **connected pose components**, so
captions, merged poses and half-sprites are gone. All six forms now have clean
clips and are the default; `DC_PLAYER_FORMS=0` restores the captured base sheet
for comparison.

The sprites themselves are correct and 1:1. Their cadence now follows the
captured base animation (walk 7/7/9/7/7/9, plus the jump/fall/land/attack
patterns), sampled across the available form poses.
`bake_player_forms.py` now finds connected pose components inside measured
per-sheet clip regions, keys the sheet background to transparency and writes
`fb_<form>_<clip>_<i>.png`; `player_forms.json` holds the clips, and
`Assets_PlayerAnimForForm` selects them from `crest_form`. The form rows include
the white/gold hurt palette pose, and missing clips (for example the form sheets
have no spell row) use attack/hover/idle fallbacks. **Outcome:** the player
looks like the game in every form, with no captions or slivers.

### A2. Enemy sprite coverage from the two enemy sheets
`Enemies 1.gif` / `Enemies 2.gif` cover most regular enemies. Match their entries
to the species seen in probes (97 distinct), then replace the remaining
silhouettes.
**Outcome:** far fewer placeholder enemies. **Size:** ~3 sessions · **Risk:**
medium (species↔sprite matching).

### Captured gameplay is now the sprite source

The recording feature paid off immediately: Somulo's species frames are now cut
from a **real recorded fight** (`captures/rec_somulo`) instead of a sprite sheet,
and the take settled two fights facts the sheets could not: **six hits** and a
**32-frame hurt flash with invulnerability**. Boss animation for every remaining
boss can be produced the same way — record, replay, extract.

### A3. Next bosses: Arma, then Phalanx — **Arma first pass done**
Arma is species `$A5` (the saves place him in areas 3, 23, 36 and 67). His sheet
is labelled, so the port now has real poses (idle / breath / dive / hurt) and a
state machine: hover with a slow bob, then either a two-shot **breath attack**
aimed at Firebrand or a **divebomb** along his line, with a stagger when hit and
a climb back to his post. His breath is a plain shot — only Somulo's fireball
leaves a firewall.
**Remaining:** authentic cadence and the second fight's palette/hurricane (his
sheet has both), Phalanx's two phases, and the remaining bosses.
**Size:** ~1 session per boss · **Risk:** medium (timing needs B3).

### A2. Enemy sprite coverage — still blocked
The two enemy sheets have no species labels, and the probe OAM is fragmented, so
species↔sprite identity is the blocker. The tractable route is to compose each
species from its OAM + VRAM with the right palette and match that against the
sheets automatically; that is a tooling task, not a data request.

### A4. Boss arena wiring (gates and phases)
Area 0 already gates to 34. Wire 84 → demon realm after phase 2, 86/90 as the two
final fights, and the mid-boss gates of 74/82.
**Outcome:** the endgame flows without stage-select. **Size:** ~1 session.

### A5. Interiors: library NPC, wise man, Black Lotus
The talisman lines (`$85:8C51..8DD0`), the wise man's vellum line (`$85:8370`)
and both Black Lotus stock lists are decoded. Show the talisman description for
the equipped talisman at the library, and the spell shop at the wise man.
**Outcome:** the city interiors behave like the game. **Size:** ~1 session.

### A6. Terrain mechanics
Lava damage, ice friction, wind zones (areas 38/46), water currents, breakables
(Buster blocks, headbutt statues), moving platforms — on top of the existing
collision attributes.
**Outcome:** levels stop being flat floors. **Size:** ~2–3 sessions.

### A7. Endings presentation
Keep the map backdrop, add the credits roll from the ending reference, and make
the good/true sequences use the completion score already gated.
**Outcome:** endings feel like endings. **Size:** ~1–2 sessions.

### A8. Overworld polish
Align the 17 extracted markers with the map art (Mode 7 affine or a calibration
offset) and model the **stage unlock change** seen in `map_new_stages` (the final
stage disappears, four open).
**Outcome:** the map works as the game's hub. **Size:** ~1 session.

### A9. Quality: long-route test, docs, release packaging
Extend the regression to a long route (several levels, shops, one boss per
level), write release notes, keep the plans current.
**Size:** ~1–2 sessions.

**Total without new input: ~14–19 sessions**, and it would make the game *play
and look* much closer to the original.

---

## 3. What still needs input — and why

### B1. Doors for the last gate-dependent areas (highest value)
`1, 35, 43, 46, 57, 63, 77, 83, 99, 109` — each needs an `entrance` and a
`before_door` save named with the map name, exactly like the earlier batches.
Also the 4 chunks with no outgoing edge — **14, 3, 30, 9**: a save standing at
their exit tells me whether it is a `to_map` door or a genuine dead end.

### B2. The missing riverbank save
`lvl_III_dark-forest-riverbank_limestone` was listed but is not on disk; without
it the limestone → riverbank link stays unknown.

### B3. Boss behaviour references
For Somulo, screenshots plus your description were enough. For **Arma, Scula,
Holothurion, Phalanx (two phases), the demon-realm boss and the Dark Demon** I
can port structure from the sheets, but not authentic timing/attack selection.
A short video per fight — or notes like the Somulo ones (attacks, weak point, hit
count, phase trigger) — is enough to extract cadence.

### B4. Ending saves
One save *at* each ending (normal/good/true especially) lets me capture the real
frames and sequences instead of approximating them.

### B5. Talisman effects
The library describes the talismans by name; their actual gameplay effects are
still guesses in the port. A sentence per talisman is enough.

### B6. Audio (optional)
The port uses replacement tracks. Real BRR/DSP extraction is a large task; only
worth it if authenticity matters more than time.

---

## 4. Milestone status

| Milestone | Status | Next step |
|---|---|---|
| **M1 Navigation** | **~91%** — graph, 139 doors, re-point/clamp policy, 6 in-game door tests | B1 saves close the last 10 areas |
| **M2 Placements** | Partial — 294 placements; probes hold 648 live objects, most in level space | A2 then re-merge |
| **M3 Bosses** | Somulo playable; others generic | A3 + B3 |
| **M4 Sprites** | 30 sheets; Somulo animated; bosses from screenshots | A1/A2 |
| **M5 Terrain** | Slopes, water, platforms only | A6 |
| **M6 Forms** | All forms switchable, one shared sprite | A1 |
| **M7 Items/NPCs** | Shops (two stocks), NPC talk, four endings; talisman effects guessed | A5 + B5 |
| **M8 Endings** | Four variants gated by completion; narration real; sequences simple | A7 + B4 |
| **M9 Audio/menus/QA** | Replacement audio, basic menus, strong regression | A9, optional B6 |

---

## 5. Suggested order

1. **A1** Firebrand forms — biggest visible upgrade, lowest risk.
2. **A3** Arma — the boss pipeline is proven on Somulo.
3. **A2** enemy sheets as far as the matching goes.
4. **A4/A5** arena wiring and interiors.
5. **A6/A7** terrain and endings.
6. **B1** whenever the door saves arrive — it closes navigation.

---

## 6. Fan-game bridge

- **Prequel Somulo battle:** framework, animated Somulo, firewall and arena all
  exist; a prequel scene reuses them with another trigger.
- **Original campaign:** M1–M9 above.
- **Sequel (`Reign of the Red Blaze`):** needs the three generalisations already
  identified — data-driven stages, an event/cutscene runner, a parameterised
  boss framework — with the Somulo pipeline as the prototype.

---

## 7. Five concrete next actions

1. Bake the five Firebrand form sheets and drive them from `crest_form`.
2. Port Arma phase 1 from his sheet and the two saved encounters.
3. Match the `Enemies 1/2` sheet entries to the probe species list.
4. Wire the library NPC and the wise man shop.
5. Add the credits/ending sequence from the ending references.
