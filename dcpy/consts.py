"""Game constants and enumerations, mirroring the C headers."""

# Player states (player.h)
PLAYER_IDLE = 0
PLAYER_WALK = 1
PLAYER_JUMP = 2
PLAYER_HOVER = 3
PLAYER_FLY = 4
PLAYER_LAND = 5
PLAYER_HURT = 6
PLAYER_DEAD = 7
PLAYER_WALL_CLING = 8
PLAYER_HEADBUTT = 9

# Crest forms (player.h)
CREST_BASE = 0
CREST_EARTH = 1
CREST_AIR = 2
CREST_WATER = 3
CREST_TIME = 4
CREST_ULTIMATE = 5
CREST_COUNT = 6

# Animation clips (anim.h)
ANIM_IDLE = 0
ANIM_WALK = 1
ANIM_JUMP = 2
ANIM_HOVER = 3
ANIM_FALL = 4
ANIM_LAND = 5
ANIM_ATTACK = 6
ANIM_SPELL = 7
ANIM_FLYING = 8
ANIM_HURT = 9
ANIM_DIE = 10
ANIM_CLIP_COUNT = 11

ANIM_CLIP_NAMES = [
    "idle", "walk", "jump", "hover", "fall", "land", "attack", "spell",
    "flying", "hurt", "death",
]

# Object types (object.h)
OBJECT_NONE = 0
OBJECT_URN = 1
OBJECT_PICKUP = 2
OBJECT_ENEMY = 3
OBJECT_PLATFORM = 4
OBJECT_CREST_ITEM = 5
OBJECT_BOSS = 6
OBJECT_ENEMY_SHOT = 7
OBJECT_NPC = 8
OBJECT_TALISMAN = 9

OBJECT_POOL_SIZE = 26

OBJECT_EVENT_PICKUP = 0x01
OBJECT_EVENT_BREAK = 0x02
OBJECT_EVENT_ENEMY_HIT = 0x04
OBJECT_EVENT_BOSS_DEFEATED = 0x08
OBJECT_EVENT_CREST_PICKUP = 0x10
OBJECT_EVENT_FIRE_PIECE = 0x20
OBJECT_EVENT_TALISMAN = 0x40
OBJECT_EVENT_ENEMY_SHOOT = 0x80  # authored enemy fired an attack pattern

# Level object kinds (level.h)
LEVEL_OBJECT_NONE = 0
LEVEL_OBJECT_URN = 1
LEVEL_OBJECT_ENEMY = 2
LEVEL_OBJECT_PLATFORM = 3
LEVEL_OBJECT_PICKUP_CREST = 4
LEVEL_OBJECT_BOSS = 5
LEVEL_OBJECT_EXIT = 6
LEVEL_OBJECT_NPC = 7
LEVEL_OBJECT_TALISMAN = 8
# A species the port has no handler for yet.  The room keeps the record so the
# placement is not lost; the renderer draws a placeholder and the pool ignores
# it until a real handler exists.
LEVEL_OBJECT_UNKNOWN = 9
# A decorative, non-interactive animated object (the cemetery's torch flames,
# species $72).  It is drawn from the species sheet but never enters the pool:
# no collision, no damage, no AI.
LEVEL_OBJECT_DECOR = 10
# A record that exists in the retail object list but draws and does nothing on
# its own (species $9B: eight script-owned pieces in the Scula/Holothurion/Ovnunu
# boss rooms, with no metasprite pointer and no OAM in the oracle capture).
LEVEL_OBJECT_INERT = 11

LEVEL_OBJECT_TYPE_NAMES = {
    "urn": LEVEL_OBJECT_URN,
    "enemy": LEVEL_OBJECT_ENEMY,
    "platform": LEVEL_OBJECT_PLATFORM,
    "pickup_crest": LEVEL_OBJECT_PICKUP_CREST,
    "boss": LEVEL_OBJECT_BOSS,
    "exit": LEVEL_OBJECT_EXIT,
    "npc": LEVEL_OBJECT_NPC,
    "talisman": LEVEL_OBJECT_TALISMAN,
    "unknown": LEVEL_OBJECT_UNKNOWN,
    "decor": LEVEL_OBJECT_DECOR,
    "inert": LEVEL_OBJECT_INERT,
}

# Game states (game.h)
GAME_TITLE = 0
GAME_PLAYING = 1
GAME_PAUSED = 2
GAME_CLEAR = 3
GAME_SUBSCREEN = 4
GAME_OVERWORLD = 5
GAME_SHOP = 6
GAME_PASSWORD = 7
GAME_OPTIONS = 8
GAME_OVER = 9
GAME_ENDING = 10
GAME_DIALOGUE = 11
# The continue hub shown after the death animation: RETRY / SELECT A STAGE /
# END (docs/TAKES.md §6.3). GAME_OVER stays for the colosseum's scripted
# restart path only.
GAME_CONTINUE = 12
# Display-only PASS WORD screen (4x4), reached from the END option.
GAME_PASSWORD_VIEW = 13

# Audio
SFX_JUMP = 0
SFX_LAND = 1
SFX_SHOOT = 2
SFX_BREAK = 3
SFX_PICKUP = 4
SFX_HURT = 5
SFX_ENEMY_HIT = 6
SFX_COUNT = 7

# Authored enemy-sound names (same order as audio.SFX_NAMES).
SFX_NAMES = ["jump", "land", "shoot", "break", "pickup", "hurt",
             "enemy_hit"]
SFX_NAME_TO_ID = {name: index for index, name in enumerate(SFX_NAMES)}

# Music tracks.  The ROM picks a song per room family, so the port carries one
# track per stage (plus the shared boss/town/overworld/ending cues) instead of
# the old title/stage/boss/ending placeholder split.  The names are the asset
# stems: `<assets>/audio/<stem>.wav`.
MUSIC_NONE = 0
MUSIC_TITLE = 1
MUSIC_OVERWORLD = 2
MUSIC_MURKLAND = 3
MUSIC_RUINED_CITY = 4
MUSIC_DARK_FOREST = 5
MUSIC_DARK_FOREST_CAVE = 6
MUSIC_TOWERS_OF_DOOM = 7
MUSIC_POSEIDONIA = 8
MUSIC_POSEIDONIA_DEPTHS = 9
MUSIC_MOUNTAINS = 10
MUSIC_MOUNTAINS_VALLEY = 11
MUSIC_PHALANX = 12
MUSIC_DEMON_HIDEOUT = 13
MUSIC_TOWN = 14
MUSIC_BOSS = 15
MUSIC_BOSS_COMMON = 16
MUSIC_ENDING = 17
MUSIC_TRACK_COUNT = 18

# Indexed by MusicTrack; "" is MUSIC_NONE (no stream).
MUSIC_TRACK_NAMES = [
    "",
    "music_title",
    "music_overworld",
    "music_murkland",
    "music_ruined_city",
    "music_dark_forest",
    "music_dark_forest_cave",
    "music_towers_of_doom",
    "music_poseidonia",
    "music_poseidonia_depths",
    "music_mountains",
    "music_mountains_valley",
    "music_phalanx",
    "music_demon_hideout",
    "music_town",
    "music_boss",
    "music_boss_common",
    "music_ending",
]

# Room area -> track, measured from the ROM's own save states (a room's song is
# fixed, and every room in a stage family shares one; see docs/AUDIO_PLAN.md).
# Areas missing here fall back to the room's level letter (AREA_LEVEL_MUSIC).
AREA_MUSIC = {
    0: MUSIC_BOSS,            # Murkland colosseum (Somulo)
    34: MUSIC_BOSS,           # the colosseum's right-hand room
    2: MUSIC_MURKLAND,        # cemetery
    4: MUSIC_MURKLAND,        # slope
    6: MUSIC_MURKLAND,        # abyss
    8: MUSIC_RUINED_CITY,     # dark avenue
    10: MUSIC_RUINED_CITY,    # reservoir
    18: MUSIC_RUINED_CITY,    # boneyard
    20: MUSIC_DARK_FOREST,    # thorn grove
    22: MUSIC_DARK_FOREST_CAVE,   # underground dyke
    26: MUSIC_DARK_FOREST_CAVE,   # scula cave
    30: MUSIC_DARK_FOREST_CAVE,   # limestone cave
    36: MUSIC_TOWERS_OF_DOOM,  # gryphon spire
    38: MUSIC_TOWERS_OF_DOOM,  # misty skies
    48: MUSIC_POSEIDONIA,      # aquatica
    54: MUSIC_POSEIDONIA,      # temple and hidden chamber
    50: MUSIC_POSEIDONIA_DEPTHS,  # underwater grotto
    52: MUSIC_POSEIDONIA_DEPTHS,  # lair of Holothurion
    58: MUSIC_MOUNTAINS_VALLEY,   # ice crevasse
    60: MUSIC_MOUNTAINS_VALLEY,   # valley of the Grewon
    62: MUSIC_MOUNTAINS,       # ice spire
    64: MUSIC_MOUNTAINS,       # ice spire (upper)
    66: MUSIC_MOUNTAINS,       # ice palace corridor
    68: MUSIC_MOUNTAINS,       # ice palace corridor (inner)
    74: MUSIC_PHALANX,         # front hall
    76: MUSIC_PHALANX,         # western bell tower
    78: MUSIC_PHALANX,         # spiny balcony
    80: MUSIC_PHALANX,         # eastern bell tower
    82: MUSIC_PHALANX,         # hall of agonized souls
    84: MUSIC_BOSS_COMMON,     # Phalanx's chamber (the last fight)
    86: MUSIC_PHALANX,         # demon realm
    88: MUSIC_DEMON_HIDEOUT,   # tunnel
    90: MUSIC_DEMON_HIDEOUT,   # the dark demon
    92: MUSIC_TOWN,            # library
    94: MUSIC_OVERWORLD,       # the Mode 7 world map (MAP_AREA)
    96: MUSIC_TOWN,            # black lotus
}

# Fallback by the room's level letter (room_names.json `level`).
AREA_LEVEL_MUSIC = {
    "0": MUSIC_MURKLAND,
    "I": MUSIC_MURKLAND,
    "II": MUSIC_RUINED_CITY,
    "III": MUSIC_DARK_FOREST,
    "IV": MUSIC_TOWERS_OF_DOOM,
    "V": MUSIC_POSEIDONIA,
    "VI": MUSIC_MOUNTAINS,
    "VII": MUSIC_PHALANX,
    "VIII": MUSIC_DEMON_HIDEOUT,
}

PROJECTILE_POOL_SIZE = 7

DC_CAMPAIGN_AREAS = 128
DC_PASSWORD_LEN = 10
