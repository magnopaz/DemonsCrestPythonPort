#include "level.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

static bool ReadInt(cJSON *obj, const char *key, int *out) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(v))
        return false;
    *out = v->valueint;
    return true;
}

static bool ReadFloat(cJSON *obj, const char *key, float *out) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(v))
        return false;
    *out = (float)v->valuedouble;
    return true;
}

static float ReadFloatOr(cJSON *obj, const char *key, float fallback) {
    float v = fallback;
    ReadFloat(obj, key, &v);
    return v;
}

static uint16_t *ReadU16Array(cJSON *obj, const char *key, int *count) {
    cJSON *arr = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsArray(arr))
        return NULL;
    int n = cJSON_GetArraySize(arr);
    uint16_t *out = malloc((size_t)n * sizeof(*out));
    if (!out)
        return NULL;
    for (int i = 0; i < n; i++) {
        cJSON *v = cJSON_GetArrayItem(arr, i);
        if (!cJSON_IsNumber(v)) {
            free(out);
            return NULL;
        }
        out[i] = (uint16_t)v->valueint;
    }
    *count = n;
    return out;
}

static uint8_t *ReadU8Array(cJSON *obj, const char *key, int *count) {
    cJSON *arr = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsArray(arr))
        return NULL;
    int n = cJSON_GetArraySize(arr);
    uint8_t *out = malloc((size_t)n);
    if (!out)
        return NULL;
    for (int i = 0; i < n; i++) {
        cJSON *v = cJSON_GetArrayItem(arr, i);
        if (!cJSON_IsNumber(v)) {
            free(out);
            return NULL;
        }
        out[i] = (uint8_t)v->valueint;
    }
    *count = n;
    return out;
}

static bool LoadBgLayer(BgLayer *layer, cJSON *obj) {
    memset(layer, 0, sizeof(*layer));
    cJSON *name = cJSON_GetObjectItemCaseSensitive(obj, "name");
    if (cJSON_IsString(name))
        snprintf(layer->name, sizeof(layer->name), "%s", name->valuestring);
    if (!ReadInt(obj, "map_width", &layer->map_w) ||
        !ReadInt(obj, "map_height", &layer->map_h) ||
        !ReadInt(obj, "scroll_x", &layer->scroll_x) ||
        !ReadInt(obj, "scroll_y", &layer->scroll_y))
        return false;
    cJSON *bands = cJSON_GetObjectItemCaseSensitive(obj, "hdma_bands");
    if (cJSON_IsArray(bands)) {
        int nb = cJSON_GetArraySize(bands);
        if (nb > 8)
            nb = 8;
        for (int i = 0; i < nb; i++) {
            cJSON *b = cJSON_GetArrayItem(bands, i);
            int lines = 0;
            float factor = 1.0f;
            if (ReadInt(b, "lines", &lines) &&
                ReadFloat(b, "factor", &factor) && lines > 0) {
                layer->hdma_bands[layer->hdma_band_count].lines = lines;
                layer->hdma_bands[layer->hdma_band_count].factor = factor;
                layer->hdma_band_count++;
            }
        }
    }
    int count = 0;
    layer->tiles = ReadU16Array(obj, "tilemap", &count);
    if (!layer->tiles || count != layer->map_w * layer->map_h) {
        fprintf(stderr, "level: %s tilemap size %d != %d\n",
                layer->name, count, layer->map_w * layer->map_h);
        return false;
    }
    return true;
}

static bool LoadCollision(Collision *col, cJSON *obj) {
    memset(col, 0, sizeof(*col));
    if (!ReadInt(obj, "cell", &col->cell) ||
        !ReadInt(obj, "width", &col->width) ||
        !ReadInt(obj, "height", &col->height))
        return false;
    int count = 0;
    col->attrs = ReadU8Array(obj, "attrs", &count);
    if (!col->attrs || count != col->width * col->height) {
        fprintf(stderr, "level: collision size %d != %d\n",
                count, col->width * col->height);
        return false;
    }
    return true;
}

static bool Level_LoadFile(Level *level, const Assets *assets,
                           const char *path) {
    memset(level, 0, sizeof(*level));
    level->area_id = 1;
    level->gate_next_area = -1;
    level->backdrop = (Color){8, 8, 16, 255};
    level->backdrop_parallax = 0.5f;
    level->backdrop_y = 0;
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "level: cannot open %s\n", path);
        return false;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = malloc((size_t)size + 1);
    if (!text) {
        fclose(f);
        return false;
    }
    size_t got = fread(text, 1, (size_t)size, f);
    fclose(f);
    text[got] = '\0';

    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root) {
        fprintf(stderr, "level: %s is not valid JSON\n", path);
        return false;
    }

    bool ok = false;
    cJSON *world = cJSON_GetObjectItemCaseSensitive(root, "world");
    cJSON *camera = cJSON_GetObjectItemCaseSensitive(root, "camera");
    cJSON *spawn = cJSON_GetObjectItemCaseSensitive(root, "spawn");
    cJSON *player = cJSON_GetObjectItemCaseSensitive(root, "player");
    cJSON *collision = cJSON_GetObjectItemCaseSensitive(root, "collision");
    cJSON *bg = cJSON_GetObjectItemCaseSensitive(root, "bg");
    cJSON *play = cJSON_GetObjectItemCaseSensitive(root, "play");
    if (!world || !camera || !spawn || !player || !collision || !bg)
        goto done;

    cJSON *name = cJSON_GetObjectItemCaseSensitive(root, "name");
    if (cJSON_IsString(name))
        snprintf(level->name, sizeof(level->name), "%s", name->valuestring);
    ReadInt(root, "area_id", &level->area_id);
    ReadInt(root, "gate_next_area", &level->gate_next_area);
    cJSON *backdrop = cJSON_GetObjectItemCaseSensitive(root, "backdrop");
    if (cJSON_IsArray(backdrop) && cJSON_GetArraySize(backdrop) >= 3) {
        int rgb[3] = {8, 8, 16};
        for (int i = 0; i < 3; i++) {
            cJSON *v = cJSON_GetArrayItem(backdrop, i);
            if (cJSON_IsNumber(v))
                rgb[i] = v->valueint;
        }
        level->backdrop = (Color){(unsigned char)rgb[0],
                                  (unsigned char)rgb[1],
                                  (unsigned char)rgb[2], 255};
    }
    ReadFloat(root, "backdrop_parallax", &level->backdrop_parallax);
    ReadInt(root, "backdrop_y", &level->backdrop_y);
    if (level->backdrop_parallax < 0.0f)
        level->backdrop_parallax = 0.0f;

    if (!ReadInt(world, "width", &level->world_w) ||
        !ReadInt(world, "height", &level->world_h) ||
        !ReadFloat(camera, "x", &level->camera_x) ||
        !ReadFloat(camera, "y", &level->camera_y) ||
        !ReadFloat(spawn, "x", &level->spawn_x) ||
        !ReadFloat(spawn, "y", &level->spawn_y))
        goto done;

    cJSON *spawns = cJSON_GetObjectItemCaseSensitive(root, "spawns");
    if (cJSON_IsArray(spawns)) {
        int ns = cJSON_GetArraySize(spawns);
        if (ns > DC_MAX_LEVEL_SPAWNS)
            ns = DC_MAX_LEVEL_SPAWNS;
        for (int i = 0; i < ns; i++) {
            cJSON *sp = cJSON_GetArrayItem(spawns, i);
            LevelSpawn *dst = &level->spawns[level->spawn_count];
            if (!ReadFloat(sp, "x", &dst->x) || !ReadFloat(sp, "y", &dst->y))
                continue;
            ReadInt(sp, "flags", &dst->flags);
            level->spawn_count++;
        }
    }

    cJSON *transitions = cJSON_GetObjectItemCaseSensitive(root, "transitions");
    if (cJSON_IsArray(transitions)) {
        int nt = cJSON_GetArraySize(transitions);
        if (nt > DC_MAX_LEVEL_TRANSITIONS)
            nt = DC_MAX_LEVEL_TRANSITIONS;
        for (int i = 0; i < nt; i++) {
            cJSON *tr = cJSON_GetArrayItem(transitions, i);
            LevelTransition *dst = &level->transitions[level->transition_count];
            memset(dst, 0, sizeof(*dst));
            dst->next_area = -1;
            ReadInt(tr, "next_area", &dst->next_area);
            ReadInt(tr, "spawn_id", &dst->spawn_id);
            ReadInt(tr, "pad_mask", &dst->pad_mask);
            ReadFloat(tr, "x", &dst->x);
            ReadFloat(tr, "y", &dst->y);
            dst->half_w = ReadFloatOr(tr, "half_w", 12.0f);
            dst->half_h = ReadFloatOr(tr, "half_h", 24.0f);
            ReadInt(tr, "type", &dst->type);
            level->transition_count++;
        }
    }

    float max_cam_x = (float)level->world_w - 256.0f;
    if (max_cam_x < 0.0f)
        max_cam_x = 0.0f;
    float max_cam_y = (float)level->world_h - 224.0f;
    if (max_cam_y < 0.0f)
        max_cam_y = 0.0f;
    level->camera_min_x = ReadFloatOr(camera, "min_x", 0.0f);
    level->camera_max_x = ReadFloatOr(camera, "max_x", max_cam_x);
    level->camera_min_y = ReadFloatOr(camera, "min_y", 0.0f);
    level->camera_max_y = ReadFloatOr(camera, "max_y", max_cam_y);

    level->play_min_x = ReadFloatOr(play, "min_x", 6.0f);
    level->play_max_x = ReadFloatOr(play, "max_x",
                                    (float)level->world_w - 6.0f);
    level->play_min_y = ReadFloatOr(play, "min_y", 22.0f);
    level->play_max_y = ReadFloatOr(play, "max_y",
                                    (float)level->world_h);

    level->player_texture = assets->player;
    if (!ReadFloat(player, "feet_x", &level->player_feet_x) ||
        !ReadFloat(player, "feet_y", &level->player_feet_y))
        goto done;

    if (!LoadCollision(&level->collision, collision))
        goto done;

    int bg_count = cJSON_GetArraySize(bg);
    if (bg_count != 2) {
        fprintf(stderr, "level: expected 2 BG layers, got %d\n", bg_count);
        goto done;
    }
    for (int i = 0; i < bg_count; i++) {
        if (!LoadBgLayer(&level->bg[i], cJSON_GetArrayItem(bg, i)))
            goto done;
    }
    level->bg_count = bg_count;

    cJSON *sprites = cJSON_GetObjectItemCaseSensitive(root, "sprites");
    if (cJSON_IsArray(sprites)) {
        int n = cJSON_GetArraySize(sprites);
        if (n > (int)(sizeof(level->sprites) / sizeof(level->sprites[0])))
            n = (int)(sizeof(level->sprites) / sizeof(level->sprites[0]));
        for (int i = 0; i < n; i++) {
            cJSON *s = cJSON_GetArrayItem(sprites, i);
            cJSON *tex = cJSON_GetObjectItemCaseSensitive(s, "texture");
            StaticSprite *dst = &level->sprites[level->sprite_count];
            if (!cJSON_IsString(tex))
                continue;
            dst->texture = strstr(tex->valuestring, "item") ? assets->item
                                                            : assets->player;
            if (!ReadFloat(s, "x", &dst->x) || !ReadFloat(s, "y", &dst->y))
                continue;
            level->sprite_count++;
        }
    }

    cJSON *objects = cJSON_GetObjectItemCaseSensitive(root, "objects");
    if (cJSON_IsArray(objects)) {
        int n = cJSON_GetArraySize(objects);
        if (n > DC_MAX_LEVEL_OBJECTS)
            n = DC_MAX_LEVEL_OBJECTS;
        for (int i = 0; i < n; i++) {
            cJSON *o = cJSON_GetArrayItem(objects, i);
            cJSON *type = cJSON_GetObjectItemCaseSensitive(o, "type");
            if (!cJSON_IsString(type))
                continue;
            LevelObject *dst = &level->objects[level->object_count];
            memset(dst, 0, sizeof(*dst));
            if (strcmp(type->valuestring, "urn") == 0)
                dst->type = LEVEL_OBJECT_URN;
            else if (strcmp(type->valuestring, "enemy") == 0)
                dst->type = LEVEL_OBJECT_ENEMY;
            else if (strcmp(type->valuestring, "platform") == 0)
                dst->type = LEVEL_OBJECT_PLATFORM;
            else if (strcmp(type->valuestring, "pickup_crest") == 0)
                dst->type = LEVEL_OBJECT_PICKUP_CREST;
            else if (strcmp(type->valuestring, "boss") == 0)
                dst->type = LEVEL_OBJECT_BOSS;
            else if (strcmp(type->valuestring, "exit") == 0)
                dst->type = LEVEL_OBJECT_EXIT;
            else if (strcmp(type->valuestring, "npc") == 0)
                dst->type = LEVEL_OBJECT_NPC;
            else if (strcmp(type->valuestring, "talisman") == 0)
                dst->type = LEVEL_OBJECT_TALISMAN;
            else
                continue;
            if (!ReadFloat(o, "x", &dst->x) ||
                !ReadFloat(o, "y", &dst->y))
                continue;
            ReadInt(o, "species", &dst->species);
            ReadInt(o, "flags", &dst->flags);
            if (getenv("DC_DEBUG_OBJ"))
                fprintf(stderr,
                        "level: object %d type %d species %d at %.0f,%.0f\n",
                        level->object_count, (int)dst->type, dst->species,
                        dst->x, dst->y);
            level->object_count++;
        }
    }

    ok = true;

done:
    cJSON_Delete(root);
    if (!ok) {
        Level_Unload(level);
        fprintf(stderr, "level: failed to load %s\n", path);
    }
    return ok;
}

bool Level_Load(Level *level, const Assets *assets, const char *dir) {
    char path[1024];
    const char *area_env = getenv("DC_AREA");
    if (area_env && *area_env) {
        snprintf(path, sizeof(path), "%s/room_area%d.json", dir,
                 atoi(area_env));
        FILE *probe = fopen(path, "rb");
        if (probe) {
            fclose(probe);
            return Level_LoadFile(level, assets, path);
        }
    }
    snprintf(path, sizeof(path), "%s/room.json", dir);
    return Level_LoadFile(level, assets, path);
}

bool Level_LoadArea(Level *level, const Assets *assets, const char *dir,
                    int area_id) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/room_area%d.json", dir, area_id);
    FILE *probe = fopen(path, "rb");
    if (!probe)
        return false;
    fclose(probe);
    Level_Unload(level);
    return Level_LoadFile(level, assets, path);
}

void Level_Unload(Level *level) {
    for (int i = 0; i < 2; i++)
        free(level->bg[i].tiles);
    free(level->collision.attrs);
    memset(level, 0, sizeof(*level));
}

uint8_t Level_AttrAt(const Level *level, float world_x, float world_y) {
    const Collision *c = &level->collision;
    int cx = (int)floorf(world_x / (float)c->cell);
    int cy = (int)floorf(world_y / (float)c->cell);
    if (cx < 0 || cy < 0 || cx >= c->width || cy >= c->height)
        return 0;
    return c->attrs[cy * c->width + cx];
}

bool Level_IsSolidAt(const Level *level, float world_x, float world_y) {
    /* Low 5 bits ($80:8FDB / $80:962B) select the collision shape (0 = empty,
     * 1 = full block, 2..0x1b = slopes/ledges). High 3 bits (0xE0) are
     * environment flags (e.g. 0xA0 has shape 0 and is empty air). */
    return (Level_AttrAt(level, world_x, world_y) & 0x1F) != 0;
}

int Level_SurfaceOffset(uint8_t attr, int local_x) {
    /* Per-tile surface height from the $80:962B jump table. Offsets are
     * measured downward from the block top; 0x03..0x14 are slopes. */
    int shape = attr & 0x1F;
    local_x &= 15;
    switch (shape) {
    case 0x01:
    case 0x15:
    case 0x16:
    case 0x18:
    case 0x19:
    case 0x1A:
    case 0x1B:
        return 0;
    case 0x02:
    case 0x17:
        return 8; /* half-height block */
    case 0x03:
        return ((15 - local_x) >> 1) + 8;
    case 0x04:
        return (15 - local_x) >> 1;
    case 0x05:
        return local_x >> 1;
    case 0x06:
        return (local_x >> 1) + 8;
    case 0x07:
        return ((15 - local_x) >> 2) + 12;
    case 0x08:
        return ((15 - local_x) >> 2) + 8;
    case 0x09:
        return ((15 - local_x) >> 2) + 4;
    case 0x0A:
        return (15 - local_x) >> 2;
    case 0x0B:
        return local_x >> 2;
    case 0x0C:
        return (local_x >> 2) + 4;
    case 0x0D:
        return (local_x >> 2) + 8;
    case 0x0E:
        return (local_x >> 2) + 12;
    case 0x0F:
        return 15 - local_x;
    case 0x10:
        return local_x;
    case 0x11:
        return local_x >> 1;
    case 0x12:
        return (local_x >> 1) + 8;
    case 0x13:
        return (15 - local_x) >> 1;
    case 0x14:
        return ((15 - local_x) >> 1) + 8;
    default:
        return -1;
    }
}

bool Level_IsWallAt(const Level *level, float world_x, float world_y) {
    int shape = Level_AttrAt(level, world_x, world_y) & 0x1F;
    switch (shape) {
    case 0x01: /* full block */
    case 0x15:
    case 0x1A:
    case 0x02: /* half block / ledge */
    case 0x17:
        return true;
    default:
        /* Slopes and 0x16 transitions are walkable surfaces, not walls. */
        return false;
    }
}

uint8_t Level_EnvFlagsAt(const Level *level, float world_x, float world_y) {
    return Level_AttrAt(level, world_x, world_y) & 0xE0;
}

bool Level_IsHazardAt(const Level *level, float world_x, float world_y) {
    /* $80:DEA5: high bits 0x20 (e.g. attr 0x21) damage the player. */
    return Level_EnvFlagsAt(level, world_x, world_y) == 0x20;
}

bool Level_IsBreakableAt(const Level *level, float world_x, float world_y) {
    /* High bits 0x40 (e.g. attr 0x41) mark destructible terrain blocks. */
    return Level_EnvFlagsAt(level, world_x, world_y) == 0x40;
}

bool Level_BreakBlockAt(Level *level, float world_x, float world_y) {
    Collision *c = &level->collision;
    int cx = (int)floorf(world_x / (float)c->cell);
    int cy = (int)floorf(world_y / (float)c->cell);
    if (cx < 0 || cy < 0 || cx >= c->width || cy >= c->height)
        return false;
    uint8_t attr = c->attrs[cy * c->width + cx];
    if ((attr & 0xE0) != 0x40)
        return false;
    c->attrs[cy * c->width + cx] = 0;
    if (level->bg_count >= 2 && level->bg[1].tiles) {
        BgLayer *bg1 = &level->bg[1];
        for (int dy = 0; dy < 2; dy++) {
            for (int dx = 0; dx < 2; dx++) {
                int tx = cx * 2 + dx;
                int ty = cy * 2 + dy;
                if (tx >= 0 && tx < bg1->map_w && ty >= 0 && ty < bg1->map_h)
                    bg1->tiles[ty * bg1->map_w + tx] = 0;
            }
        }
    }
    return true;
}

bool Level_IsWaterAt(const Level *level, float world_x, float world_y) {
    /* $80:94AB: high bits 0x60 mark water blocks ($1045 underwater). */
    return Level_EnvFlagsAt(level, world_x, world_y) == 0x60;
}

bool Level_IsSlopeRampAt(const Level *level, float world_x, float world_y) {
    /* $80:DF82: high bits 0x80 increment $1070, selecting the 0x00B3 -> 0x0166
     * walk acceleration ramp at $80:F065. */
    return Level_EnvFlagsAt(level, world_x, world_y) == 0x80;
}

bool Level_FloorAt(const Level *level, float world_x, float feet_y,
                   float *surface_y) {
    const Collision *c = &level->collision;
    int cx = (int)floorf(world_x / (float)c->cell);
    int cy = (int)floorf(feet_y / (float)c->cell);
    if (cx < 0 || cy < 0 || cx >= c->width || cy >= c->height)
        return false;

    uint8_t attr = c->attrs[cy * c->width + cx];
    int local_x = (int)floorf(world_x) & (c->cell - 1);
    int offset = Level_SurfaceOffset(attr, local_x);
    if (offset < 0)
        return false;

    *surface_y = (float)(cy * c->cell + offset);
    return true;
}
