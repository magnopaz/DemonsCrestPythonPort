# Plan — sprites, animation and backgrounds

The user reported (2026-10-24) that Somulo's sprint animation looks like debris and
that the colosseum background has black rectangles. Both are real, and both come
from the same weakness: **we have been assembling art with three different
pipelines and no validation gate**. This plan fixes the method, not just the
symptom.

---

## 1. What is actually wrong (evidence)

| symptom | evidence | cause |
|---|---|---|
| Somulo "exploded" while moving | the frames cut from the recorded fight have **113 alpha components** per frame, largest only ~2.2k px | the video pipeline keys the arena by colour; the dragon's dark shading was keyed out too, and the golden floor survived as speckles |
| black patches on the dragon | opaque-black ribcage interior from the sprite sheet | the sheet's interior is painted black; nobody keyed it |
| black rectangles in the background | colosseum wall tiles missing | the BG tilemap references tiles whose CHR was never captured for that area |
| sprite changes size/position between poses | anchors differed by up to 20 px between sources (screenshot, sheet, video) | anchor is derived from the crop, not from the object's real position in the game |
| scale wrong | Somulo drawn at 1.3x, then 1.15x, both guesses | the reference height was read off a screenshot instead of the OAM |

The deeper point: **a screenshot is not a sprite**. Video colour-keying is a
heuristic; a sprite sheet is clean but its layout must be measured; only the
game's own VRAM/OAM is exact. We mixed all three and trusted the results.

---

## 2. Principle

> A sprite or background is accepted only if **re-rendering the captured frame
> from our extracted data matches the emulator's own screenshot pixel for pixel**
> (within a small tolerance), and its alpha mask passes structural checks.

That gate is objective and automatable, and it is the piece that has been
missing.

---

## 3. Pipeline A — exact OAM/VRAM compositor (primary)

The recomp already exposes everything needed over the debug server:
`dump_vram`, `dump_cgram`, `dump_oam`, `dump_frame_raw`, `screenshot`, plus WRAM
reads for the object pool (`$1080`, stride `$50`).

Steps:

1. **Capture a frame with its state**: VRAM, CGRAM, OAM (512 bytes), PPU regs
   (BGMODE, BGnSC, TM/TS), the object pool, and a screenshot from the *same*
   frame (`run_to_frame` then read, never across frames).
2. **Decode OAM properly**: entry → x/y, tile, palette (0–7), priority, flips,
   size; 16×16 entries are four 8×8 tiles in the OAM's quadrant order. Place
   pixels in **screen space** first; this is how the hardware composes them.
3. **Group slots into objects** using the object pool: each pool entry has a
   world position and a species; assign each OAM slot to the nearest object
   within a threshold (and mark unassigned slots as scenery/effects). This is
   the step that failed before — grouping by colour, not by position.
4. **Render each object separately** with its own palette into an atlas frame,
   anchored at the object's pool position (so anchors are exact by construction).
5. **Validate by recomposition**: draw *all* assigned objects plus the background
   at the captured scroll and diff against `dump_frame_raw`. Acceptance: ≤0.5 %
   differing pixels, no component >100 px in the alpha mask.
6. **Emit** `enemy_<species>_<pose>.png` + a JSON entry (texture, anchor,
   duration, pose tag, hitbox from the composed bounds).

This is exact by construction; it is also the only way boss parts (Somulo's
`$33/$35/$36/$37`, Phalanx's `$8D` body) can be reassembled correctly.

## 4. Pipeline B — measured sheet crops (secondary)

For art only available as a sprite sheet (statues, portraits, projectiles):

1. Put a **coordinate grid** on the sheet and read the pose boxes by eye (this
   worked for Hippogriff and Arma).
2. Key only the sheet's background colour, never arbitrary dark pixels.
3. Structural filter: drop alpha components smaller than 1 % of the sprite area;
   reject a crop whose bounding box is wider than the sheet's row pitch.
4. Validate with a contact sheet plus the same structural checks as Pipeline A.

Never use it for multi-part bosses.

## 5. Backgrounds

1. **Rebuild from VRAM**: dump VRAM/CGRAM at the area, then render BG1/BG2 from
   the tilemap + CHR offline, with the captured scroll and HDMA bands. This is
   exact and avoids holes, because the tiles come from the same dump the tilemap
   refers to.
2. **Or** use a community full-stage image (e.g.
   `docs/sprites/…Backgrounds - Cemetery.png`) mapped onto the room's world
   size as a single layer, when the tilemap route is not worth it.
3. Validate by diffing a ported screenshot against a recomp screenshot at the
   same camera position; black rectangles are immediate failures.

## 6. Animation model

- `species_anim.json` keeps `frames[]` with `{texture, anchor, duration, pose}`,
  and each state machine requests a **pose tag** (idle, walk, attack, hurt,
  statue, die) rather than a raw index.
- A walk cycle needs **≥4 leg poses**; if the sheet has a "walking legs" row, the
  compositor composes body + legs per frame (Pipeline A can do this per object).
- Sequences come from a take: classify frames by the object pool's state byte,
  then pick representative frames per state. No colour heuristics.

## 7. Acceptance gates (added to the regression)

For every species used by a playable delivery:

1. no opaque-black pixels;
2. no alpha component larger than 1 % that is disconnected from the main body;
3. anchors consistent within 2 px across the frames of one pose set;
4. a rendered in-game frame diffed against the emulator screenshot (≤0.5 %).

## 8. Work order

| # | task | effect | effort |
|---|---|---|---|
| 1 | Revert Somulo to sheet-composed frames, cleaned, scale 1.15 (**done now**) | no debris, no black patches | done |
| 2 | Build `tools/dc_extract/oam_compose.py` (Pipeline A) + recomposition diff | exact sprites for every boss/enemy | 1–2 sessions |
| 3 | Re-bake Somulo, Hippogriff, Grewon, Phalanx with Pipeline A | correct poses and anchors | 1 session |
| 4 | Background rebuild for area 2 (cemetery), then the MVP 3 areas | no black rectangles | 1–2 sessions |
| 5 | Add the acceptance gates to `run_regression.py` | prevents regressions like this | half a session |
| 6 | Re-record the MVP captures | visual sign-off | user |

## 9. Risks

- **OAM grouping** can still mis-assign when two objects overlap; the pool
  position plus a distance threshold handles the normal case, and the
  recomposition diff catches the rest.
- **Palettes**: each sprite uses a CGRAM row from its OAM palette bits; getting
  that wrong shifts colours (this already bit us once with palette 0).
- **16×16 tiles**: quadrant ordering and the low tile bit must follow the OAM
  entry, or sprites come out as four swapped quadrants.
- **Widescreen margins**: captures taken in widescreen include columns the game
  never authored; capture in 4:3 for sprite work.
