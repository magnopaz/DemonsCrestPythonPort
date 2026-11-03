# Named rooms from the level saves

Built by `tools/dc_extract/build_room_names.py` from saves named
`lvl_<level>_<map-name>[_role]`. Each row is an area id observed in a save
plus the map it corresponds to.

| area | level | map | roles | our grid | map grid | note |
|---|---|---|---|---|---|---|
| 0 | 0 | murkland-colosseum | entrance | (3, 2) | (4, 1) | our grid is smaller/larger — see below |
| 2 | I | murkland-cemetery | before_door, entrance | (8, 3) | (8, 2) | our grid is smaller/larger — see below |
| 4 | I | murkland-slope | before_door, entrance | (4, 3) | (8, 3) | our grid is smaller/larger — see below |
| 6 | I | murkland-abyss | before_door, entrance | (2, 5) | (4, 6) | our grid is smaller/larger — see below |
| 8 | II | ruined-city-dark-avenue | before_door, before_door_black_lotus, before_door_library, before_door_wise_man, entrance | (1, 4) | (4, 3) | our grid is smaller/larger — see below |
| 10 | II | ruined-city-reservoir | before_door, entrance, item1, item2 | (5, 3) | (8, 3) | our grid is smaller/larger — see below |
| 18 | II | ruined-city-boneyard | before_door, entrance | (3, 5) | (9, 3) | our grid is smaller/larger — see below |
| 20 | III | dark-forest-thorn-grove | before_door, entrance | (2, 2) | (5, 3) | our grid is smaller/larger — see below |
| 22 | III | dark-forest-underground-dyke | before_door, e1, e2, entrance | (2, 2) | (7, 3) | our grid is smaller/larger — see below |
| 26 | III | dark-forest-scula-cave | before_door, boss, boss_dead, entrance | (8, 2) | (6, 3) | our grid is smaller/larger — see below |
| 34 | 0 | murkland-colosseum | on_the_righ | (8, 2) | (4, 1) | our grid is smaller/larger — see below |
| 36 | IV | towers-of-doom-gryphon-spire | before_door, entrance | (2, 2) | (3, 5) | our grid is smaller/larger — see below |
| 38 | IV | towers-of-doom-misty-skies | before_door, boss, boss_dead, entrance | (1, 7) | (9, 1) | our grid is smaller/larger — see below |
| 48 | V | poseidonia-aquatica | before_door, e1, e2, entrance | (1, 2) | (7, 3) | our grid is smaller/larger — see below |
| 54 | V | poseidonia-temple-and-hidden-chamber | boss, dead, entrance, passage, persecution, persecution_trigged | (1, 2) | (4, 5) | our grid is smaller/larger — see below |
| 58 | VI | mountains-valley-of-the-grewon | before_door, e1, entrance | (1, 2) | (8, 4) | our grid is smaller/larger — see below |
| 62 | VI | mountains-ice-spire | before_door_1, before_door_2, e1, entrance | (1, 2) | (4, 5) | our grid is smaller/larger — see below |
| 64 | VI | mountains-ice-spire | inside_door_1 | (8, 3) | (4, 5) | our grid is smaller/larger — see below |
| 66 | VI | mountains-ice-palace-corridor | before_door, e1, entrance | (8, 2) | (9, 2) | our grid is smaller/larger — see below |
| 68 | VI | mountains-ice-palace-corridor | inside_door, inside_door_before_boss, inside_door_boss | (8, 3) | (9, 2) | our grid is smaller/larger — see below |
| 74 | VII | phalanxs-fortress-front-hall | after_door, before_door, boss, boss_before_door, e1, entrance | (6, 3) | (7, 1) | our grid is smaller/larger — see below |
| 76 | VII | phalanxs-fortress-western-bell-tower | before_door, entrance | (1, 2) | (1, 7) | our grid is smaller/larger — see below |
| 80 | VII | phalanxs-fortress-eastern-bell-tower | before_door, entrance | (1, 2) | (1, 7) | our grid is smaller/larger — see below |
| 82 | VII | phalanxs-fortress-hall-of-agonized-souls | before_door, boss, boss_before_door, e1, entrance | (1, 2) | (10, 2) | our grid is smaller/larger — see below |
| 84 | VII | phalanxs-fortress-phalanxs-chamber | boss, boss2, boss2_cutscene, boss2_talk, boss_cutscene, boss_talk, entrance | (1, 2) | (2, 2) | our grid is smaller/larger — see below |
| 86 | VII | phalanxs-fortress-demon-realm | boss, boss_talk, entrance | (1, 2) | (9, 1) | our grid is smaller/larger — see below |
| 88 | VIII | demons-hideout-tunnel | before_door, entrance | (1, 2) | (4, 3) | our grid is smaller/larger — see below |
| 90 | VIII | demons-hideout-the-dark-demon | entrance, final_boss_second | (1, 2) | (2, 2) | our grid is smaller/larger — see below |
| 92 | II | library | entrance | (4, 5) | - | interior, no community map |
| 94 | II | wise_man | entrance | (4, 5) | - | interior, no community map |
| 96 | II | black_lotus | entrance | (4, 5) | - | interior, no community map |

## What the mismatch means

The player coordinates in the saves fit inside the map dimensions but often
fall outside our extracted world (thorn grove: save x=909 vs our 512 px;
underground dyke: x=1687 vs our 512 px). The ROM grid table
(`$81:A6D8`, read by `area_info`) reports 2x2 for those areas, while the
community maps show 5x3 and 7x3 — and the maps agree with the save
coordinates. So the grid table does **not** describe the full room for
multi-screen areas; the room is a chain/stream of more screen data than that
table holds.

Consequence for M1: room extents must come from the maps (and runtime
observation), not from the static grid table. The next extraction step is to
compose rooms from the map-driven screen lists instead of `area_info`.
