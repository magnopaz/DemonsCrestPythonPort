#ifndef DC_LEVEL_H
#define DC_LEVEL_H

#include <stdbool.h>
#include <stdint.h>
#include "raylib.h"
#include "assets.h"

typedef struct HdmaBand {
    int lines;
    float factor;
} HdmaBand;

typedef struct BgLayer {
    char name[16];
    int map_w;
    int map_h;
    int scroll_x;
    int scroll_y;
    HdmaBand hdma_bands[8];
    int hdma_band_count;
    uint16_t *tiles;
} BgLayer;

typedef struct Collision {
    int cell;
    int width;
    int height;
    uint8_t *attrs;
} Collision;

typedef struct StaticSprite {
    Texture2D texture;
    float x;
    float y;
} StaticSprite;

#define DC_MAX_LEVEL_OBJECTS 64
#define DC_MAX_LEVEL_SPAWNS 8
#define DC_MAX_LEVEL_TRANSITIONS 16

typedef enum LevelObjectType {
    LEVEL_OBJECT_NONE = 0,
    LEVEL_OBJECT_URN,
    LEVEL_OBJECT_ENEMY,
    LEVEL_OBJECT_PLATFORM,
    LEVEL_OBJECT_PICKUP_CREST,
    LEVEL_OBJECT_BOSS,
    LEVEL_OBJECT_EXIT,
    LEVEL_OBJECT_NPC,
    LEVEL_OBJECT_TALISMAN  /* flags = talisman index (0..4) */} LevelObjectType;

typedef struct LevelObject {
    LevelObjectType type;
    int species;
    int flags;
    float x;
    float y;
} LevelObject;

typedef struct LevelSpawn {
    float x;
    float y;
    int flags;
} LevelSpawn;

typedef struct LevelTransition {
    int next_area;
    int spawn_id;
    int pad_mask;
    float x;
    float y;
    float half_w;
    float half_h;
    int type;
} LevelTransition;

typedef struct Level {
    char name[64];
    int area_id;
    int gate_next_area;
    int world_w;
    int world_h;
    Color backdrop;
    float backdrop_parallax; /* 1.0 = world-locked, 0.5 = half-speed */
    int backdrop_y;          /* screen-space y of the image layer */

    BgLayer bg[2];
    int bg_count;

    Collision collision;

    float camera_x;
    float camera_y;
    float camera_min_x;
    float camera_max_x;
    float camera_min_y;
    float camera_max_y;

    float spawn_x;
    float spawn_y;
    LevelSpawn spawns[DC_MAX_LEVEL_SPAWNS];
    int spawn_count;

    LevelTransition transitions[DC_MAX_LEVEL_TRANSITIONS];
    int transition_count;

    float play_min_x;
    float play_max_x;
    float play_min_y;
    float play_max_y;

    Texture2D player_texture;
    float player_feet_x;
    float player_feet_y;

    StaticSprite sprites[16];
    int sprite_count;

    LevelObject objects[DC_MAX_LEVEL_OBJECTS];
    int object_count;
} Level;

bool Level_Load(Level *level, const Assets *assets, const char *dir);
bool Level_LoadArea(Level *level, const Assets *assets, const char *dir,
                    int area_id);
void Level_Unload(Level *level);

uint8_t Level_AttrAt(const Level *level, float world_x, float world_y);
uint8_t Level_EnvFlagsAt(const Level *level, float world_x, float world_y);
bool Level_IsSolidAt(const Level *level, float world_x, float world_y);
bool Level_IsWallAt(const Level *level, float world_x, float world_y);
bool Level_IsHazardAt(const Level *level, float world_x, float world_y);
bool Level_IsBreakableAt(const Level *level, float world_x, float world_y);
bool Level_BreakBlockAt(Level *level, float world_x, float world_y);
bool Level_IsWaterAt(const Level *level, float world_x, float world_y);
bool Level_IsSlopeRampAt(const Level *level, float world_x, float world_y);
bool Level_FloorAt(const Level *level, float world_x, float feet_y,
                   float *surface_y);
int Level_SurfaceOffset(uint8_t attr, int local_x);

#endif
