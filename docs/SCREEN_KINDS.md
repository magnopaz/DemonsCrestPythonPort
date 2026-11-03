# Screen kinds — what is a room and what is not

`$008D` (the byte the port uses as "area id") is a **screen selector**, not a
room number. Only part of its range is playable rooms; the rest are menus and
cutscenes. Recorded here after the user pointed out that some screens were being
talked about as playable when they are cinematics.

| `$008D` | screen | playable as a room? |
|---|---|---|
| 0–112 | rooms extracted into `assets/generated/room_areaN.json` | **yes** |
| 160 | title / menu screens (`menu_cutscene`) | no — menu code |
| 168 | opening cutscene (`initial_cutscene`) | no — cinematic |
| 188 | Mode 7 overworld | special mode, not a room |
| ≥113 otherwise | decodes to garbage tables (invalid) | no |

Consequences already encoded in the project:

- extraction and the name tool ignore areas above 112;
- `Game_LoadArea` refuses ids outside the room range, so a save taken on a
  cutscene screen cannot be mistaken for a room;
- the navigation graph only contains 0–112.

## The opening cutscene, as captured

`captures/initial_cutscene` (14 935 frames) is the intro narrative: page after
page of text over the gargoyle statues and the six stones —

- "ONE DAY, SIX MAGICAL STONES FELL FROM THE SKY"
- "CRESTS AND THE REALM ERUPTED INTO CIVIL WAR"
- "AND COLLECTED FIVE CRESTS"
- "EARTH, AIR, WATER AND TIME, CREST OF HEAVEN"
- "BUT THE PRICE OF VICTORY WAS HIGH"
- "I HAVE DEFEATED THE RED DEMON"

Those lines already exist in `text_strings.json`, so staging the intro is a
presentation task (pages + the statue/stone art), not a data one. It is **not**
part of MVP 1; the delivery starts when the player has control.
