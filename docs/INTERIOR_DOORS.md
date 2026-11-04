# Interior doors (shops and the library)

These rooms are reached from inside another room (a door you press **up** at), not
from the overworld, and they have no community full-stage map. They are recorded
here rather than in `LEVEL_TRANSITIONS.md` because they share their trigger
position with an avenue spawn point.

| from | door | to | area |
|---|---|---|---|
| ruined-city-dark-avenue (4) | up (library door) | library | 46 |
| ruined-city-dark-avenue (4) | up (Black Lotus door) | black_lotus | 48 |
| ruined-city-dark-avenue (4) | up (wise man door) | wise_man | 47 |

Notes:

- Area ids here are **loader areas**, i.e. WRAM `$008D / 2`. Older revisions of
  this page (and `docs/FullMaps/room_names.md`) list the raw `$008D` values
  8/92/94/96; those are double. Measured in `docs/TAKES.md` §5.
- The names come from the user's save names (`lvl_II_library`, `lvl_II_black_lotus`,
  `lvl_II_wise_man`) and are used by the area banner and stage list.
- The interiors are already extracted rooms; the banner shows **LIBRARY**,
  **BLACK LOTUS** and **WISE MAN** when the port loads areas 46/48/47.
- The avenue is a single 1024×512 room (`room_area4.json`), not a composite
  needing a level-space mapping: the take walks x 0–947, y 150–430 in that same
  space.
- The up-doors sit on the avenue's spawn points: library at (424,428), wise man
  at (664,428), Black Lotus at (824,124). The return trip is already extracted:
  `room_area46` transitions to area 4 with `spawn_id: 1`, `room_area47` with
  `spawn_id: 2`, and the player lands back on those exact coordinates.
- Still missing is the outbound door. The three species `$24` records at
  (424,420), (664,420) and (824,116) are the door controllers (3 records, one
  area, 3 states, update `$82:CA02`); the extractor types them `pickup_crest`.
  Wiring them as transitions needs `pad_mask` support in
  `dcpy/game.py::game_check_transitions`, which today triggers on proximity only.
- `wise_man` sells spells (it asks for a vellum first: `$85:8370`); `black_lotus`
  is the potion shop; the library NPC describes talismans (`$85:8C51..8DD0`).
