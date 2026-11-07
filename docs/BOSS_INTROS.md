# Boss intro dialogues (first encounter only)

The user's stage-IV run (2026-11-07) has Arma's second fight with an intro
dialogue the first time and without it on the second encounter.  The port
models that with **one story bit per campaign area**, saved with the game.

The take itself was recorded from a password, so it visits area 23 three times
(17 321, 18 501, 22 801) without showing a long text state — most likely the
intro was already seen in that save.  The trigger is therefore modelled as
"first entry into the area", from the user's description, not measured.

## The table

| area | boss | text (found by substring) | ROM address |
|---|---|---|---|
| 23 | Arma 2 | `I AM ARMA` | `BE:F162` |

The block (7 pages, 172 bytes):

```
I'VE WATCHED YOUR
PROGRESS AND I'M GLAD
THAT I SHALL BE THE / ONE TO PUT AN END TO
YOUR PETTY CRUSADE / I BELIEVE YOU HAVE
HEARD OF ME
I AM ARMA / I WILL BE
YOUR EXECUTIONER!
```

`dcpy/game.py::BOSS_INTRO_TEXT` maps the area to the substring;
`game_maybe_start_boss_intro` opens `GAME_DIALOGUE` (returning to
`GAME_PLAYING`) and sets `story_flags |= 1 << area` **before** showing it, so
a death mid-dialogue cannot replay it.

## Story flags

- `Game.story_flags` is an int bitmask, one bit per area id (0..112).
- Saved as `"story_flags"` in `saves/dc_save.json`; absent in older saves,
  where it defaults to 0 (the checkers that need a preset use
  `DC_STORY_FLAGS=<int>`).
- `DC_NO_STORY` suppresses every intro (timed demos); `DC_INTRO_FORCE=1`
  enables the check under `DC_RUN_FRAMES` for tests.

This is the port's equivalent of the ROM's "intro seen" flag.  The ROM's own
address for that flag is still unmeasured: the take only proves the behaviour
(dialogue once, silent afterwards).  When the address is found, the bit can be
mapped onto it without changing the trigger.

## Text loader fixes found while wiring it

1. **`TEXT_MAX_STRINGS` was 512 and the ROM has 518 blocks.**  The last six
   never loaded, and Arma's intro is one of them (`text_find` returned -1).
   Raised to 640.
2. **`TEXT_MAX_PAGES` was 6.**  Arma's block has 7 pages, so
   "YOUR EXECUTIONER!" was silently dropped.  Raised to 8.
3. **`extract_text.py` glued the preceding `RTL` opcode (0x6B = `k`) to the
   text**, because it is printable: the first line read `kI'VE WATCHED YOUR`.
   The extractor now trims a leading lower-case run (dialogue never starts
   lower-case); the `0x6A` (`j`) line-break code inside the text is untouched.

## The checker

`tools/check_arma2_intro.py` (in the regression) runs area 23 four ways:

1. fresh: `GAME_DIALOGUE` starts within 10 frames, lasts 40..200 frames
   (7 pages at 20), and ends back in `GAME_PLAYING`;
2. `DC_STORY_FLAGS=1<<23`: no dialogue;
3. `DC_NO_STORY=1`: no dialogue (the demo guard wins);
4. save round-trip: the flag is written to `dc_save.json` and resuming that
   save does not replay the intro.
