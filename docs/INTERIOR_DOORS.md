# Interior doors (shops and the library)

These rooms are reached from inside another room (a door you press **up** at), not
from the overworld, and they have no community full-stage map. They are recorded
here rather than in `LEVEL_TRANSITIONS.md` because their coordinates are in
level space and would be clamped into the same spot inside the chunk, producing
ambiguous triggers.

| from | door | to | area |
|---|---|---|---|
| ruined-city-dark-avenue | up (library door) | library | 92 |
| ruined-city-dark-avenue | up (Black Lotus door) | black_lotus | 96 |
| ruined-city-dark-avenue | up (wise man door) | wise_man | 94 |

Notes:

- The names come from the user's save names (`lvl_II_library`, `lvl_II_black_lotus`,
  `lvl_II_wise_man`) and are used by the area banner and stage list.
- The interiors are already extracted rooms; the banner shows **LIBRARY**,
  **BLACK LOTUS** and **WISE MAN** when the port loads areas 92/96/94.
- Wiring the up-doors needs a level-space → chunk-space mapping for level II's
  dark avenue (the avenue is a composite of chunks; its save coordinates reach
  x≈990 while the extracted chunk is 256 px wide). Until then these three doors
  are documented, not walkable.
- `wise_man` sells spells (it asks for a vellum first: `$85:8370`); `black_lotus`
  is the potion shop; the library NPC describes talismans (`$85:8C51..8DD0`).
