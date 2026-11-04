#include "game.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "audio.h"
#include "cJSON.h"
#include "render.h"

#ifdef _WIN32
#include <direct.h>
#define DC_MKDIR(path) _mkdir(path)
#else
#include <sys/stat.h>
#define DC_MKDIR(path) mkdir(path, 0755)
#endif

/* Native save format (not the retail password). One JSON file holds campaign
 * progression plus the options that should survive a restart. */
#define DC_SAVE_VERSION 2

static void Game_OpenOverworld(Game *game);
static void Game_CompleteArea(Game *game);
static void Game_StartTownTalk(Game *game);
static void Game_TryTalk(Game *game);

/* Campaign stage nodes on the Mode 7 overworld map. */
#define CAMPAIGN_COLOSSEUM 0
#define CAMPAIGN_GRAVEYARD 1
#define CAMPAIGN_CATACOMBS 2
#define CAMPAIGN_RUINS 3
#define CAMPAIGN_LAKE 4
#define CAMPAIGN_DEMON_KEEP 5

static const char *const kFireNames[] = {
    "FIREBALL", "BUSTER", "TORNADO", "CLAW", "DEMON FIRE"
};
static const char *const kTalismanNames[] = {
    "CROWN", "SKULL", "ARMOR", "FANG", "HAND"
};

static void Game_Reset(Game *game) {
    game->intro_timer = 110;
    Player_Init(&game->player, &game->level);
    Projectiles_Init(&game->projectiles);
    Objects_Init(&game->objects, &game->level);
    Camera_Init(&game->camera, &game->level);
    game->objects.boss_alive = false;
    game->objects.boss_defeated = false;
    game->death_timer = 0;
    game->continue_cursor = 0;
    game->transition_phase = 0;
    game->transition_timer = 0;
    Render_SetFade(0.0f);
    if (getenv("DC_BOSS_CLEAR")) {
        /* Cleared room: the boss is gone but the room still "has" one, which is
         * what the post-boss gate checks. */
        game->objects.boss_alive = false;
        game->objects.boss_defeated = true;
    }
    game->state_timer = 0;
}

bool Game_TransitionToArea(Game *game, int area_id, int spawn_id) {
    if (area_id < 0 || area_id >= DC_CAMPAIGN_AREAS)
        return false;
    /* Never enter a room the extractor classified as empty (menu/padding grid):
     * the player would fall through a world with no collision. */
    if (Assets_RoomKind(&game->assets, area_id) == 3) {
        fprintf(stderr, "game: refusing empty room %d\n", area_id);
        return false;
    }
    /* Preserve campaign progression across the level reload. */
    Player saved = game->player;
    int prev_area = game->level.area_id;
    if (!Level_LoadArea(&game->level, &game->assets, game->asset_dir, area_id)) {
        Level_LoadArea(&game->level, &game->assets, game->asset_dir, prev_area);
        Assets_LoadAreaBg(&game->assets, game->level.area_id);
        return false;
    }
    Assets_LoadAreaBg(&game->assets, game->level.area_id);
    Player_Init(&game->player, &game->level);
    game->intro_timer = 110;
    if (getenv("DC_BOSS_CLEAR")) {
        /* Cleared room: the boss is gone but the room still "has" one, which is
         * what the post-boss gate checks. */
        game->objects.boss_alive = false;
        game->objects.boss_defeated = true;
    }
    game->player.max_hp = saved.max_hp > 0 ? saved.max_hp : 6;
    game->player.hp = saved.hp > 0 ? saved.hp : game->player.max_hp;
    game->player.crests_mask = saved.crests_mask;
    game->player.crest_form = saved.crest_form;
    game->player.talisman_mask = saved.talisman_mask;
    game->player.active_talisman = saved.active_talisman;
    game->player.potions = saved.potions;
    game->player.scrolls = saved.scrolls;
    game->player.gold = saved.gold;
    if (game->level.spawn_count > 1 && spawn_id > 0 &&
        spawn_id < game->level.spawn_count) {
        game->player.x_fx =
            (int32_t)lroundf(game->level.spawns[spawn_id].x * 256.0f);
        game->player.y_fx =
            (int32_t)lroundf(game->level.spawns[spawn_id].y * 256.0f);
        game->player.x = game->level.spawns[spawn_id].x;
        game->player.y = game->level.spawns[spawn_id].y;
    }
    Projectiles_Init(&game->projectiles);
    Objects_Init(&game->objects, &game->level);
    Camera_Init(&game->camera, &game->level);
    game->objects.boss_alive = false;
    game->objects.boss_defeated = false;
    game->death_timer = 0;
    game->continue_cursor = 0;
    game->state = GAME_PLAYING;
    game->state_timer = 0;
    return true;
}

/* Room change with the original's fade. Measured on the recomp from a save
 * standing before a door (lvl_I_murkland-slope_before_door), reading INIDISP
 * per frame while walking through it:
 *
 *   fade out  28 frames, brightness 15 -> 0 (kFadeOut)
 *   black     64 frames (the room load happens inside it)
 *   fade in   28 frames, brightness 1 -> 15 (kFadeIn)
 *
 * The old port cut straight to the new room, which is the one visible
 * difference between its transitions and the console's. */
static const uint8_t kFadeOut[28] = {
    14, 13, 13, 12, 12, 11, 11, 10, 10, 9, 9, 8, 8, 7,
    7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0
};
static const uint8_t kFadeIn[28] = {
    1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 7,
    8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14
};
#define DC_FADE_OUT_FRAMES 28
#define DC_FADE_BLACK_FRAMES 64
#define DC_FADE_IN_FRAMES 28

static FILE *s_fade_trace = NULL;
static bool s_fade_trace_open = false;

static void Game_TraceFade(Game *game, float fade) {
    if (!s_fade_trace_open) {
        s_fade_trace_open = true;
        const char *path = getenv("DC_TRACE_FADE");
        if (path && *path)
            s_fade_trace = fopen(path, "w");
        if (s_fade_trace)
            fprintf(s_fade_trace, "frame,phase,timer,fade,area\n");
    }
    if (!s_fade_trace)
        return;
    fprintf(s_fade_trace, "%u,%d,%d,%d,%d\n", game->frame,
            game->transition_phase, game->transition_timer,
            (int)lroundf(fade * 15.0f), game->level.area_id);
    fflush(s_fade_trace);
}

void Game_BeginTransition(Game *game, int area_id, int spawn_id) {
    if (game->transition_phase != 0)
        return;   /* a transition is already running */
    if (game->restart_timer > 0)
        return;   /* the death fade owns the screen */
    if (area_id < 0 || area_id >= DC_CAMPAIGN_AREAS ||
        area_id == game->level.area_id)
        return;
    game->transition_phase = 1;
    game->transition_timer = 0;
    game->transition_area = area_id;
    game->transition_spawn = spawn_id;
}

/* Advances the fade; returns true while the game should keep the simulation
 * frozen. The room load happens on the first black frame, like the console's
 * room-load task, which only consumes $008D after the fade-out. */
bool Game_UpdateTransition(Game *game) {
    if (game->transition_phase == 0)
        return false;
    switch (game->transition_phase) {
    case 1:
        Render_SetFade(kFadeOut[game->transition_timer] / 15.0f);
        Game_TraceFade(game, kFadeOut[game->transition_timer] / 15.0f);
        if (++game->transition_timer >= DC_FADE_OUT_FRAMES) {
            game->transition_phase = 2;
            game->transition_timer = 0;
            Game_TransitionToArea(game, game->transition_area,
                                  game->transition_spawn);
            Render_SetFade(1.0f);
        }
        break;
    case 2:
        Render_SetFade(1.0f);
        Game_TraceFade(game, 1.0f);
        if (++game->transition_timer >= DC_FADE_BLACK_FRAMES) {
            game->transition_phase = 3;
            game->transition_timer = 0;
        }
        break;
    case 3:
        Render_SetFade(kFadeIn[game->transition_timer] / 15.0f);
        Game_TraceFade(game, kFadeIn[game->transition_timer] / 15.0f);
        if (++game->transition_timer >= DC_FADE_IN_FRAMES) {
            game->transition_phase = 0;
            game->transition_timer = 0;
            Render_SetFade(0.0f);
            Game_TraceFade(game, 0.0f);
        }
        break;
    default:
        game->transition_phase = 0;
        Render_SetFade(0.0f);
        return false;
    }
    /* Keep the frame clock running while the simulation is frozen, so timed
     * traces and the fade itself stay on one timeline. */
    game->frame++;
    return true;
}

/* Native password: 10 letters from a 20-symbol alphabet encode a 32-bit
 * progression payload plus an 8-bit FNV-1a checksum (40 bits). The retail
 * encode/decode algorithm is still to be decoded; this format is stable and
 * self-checking, so a mistyped code is rejected instead of corrupting a run.
 *
 * Payload layout: stages[7:0] max_hp[11:8] crests[17:12] form[20:18]
 *                 potions[23:21] scrolls[26:24] talismans[31:27] */
static const char kPasswordAlphabet[] = "BCDFGHJKLMNPQRSTVWXYZ";
#define DC_PASSWORD_ALPHABET 20

static uint8_t Password_Checksum(uint32_t payload) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < 4; i++) {
        h ^= (payload >> (i * 8)) & 0xFFu;
        h *= 16777619u;
    }
    return (uint8_t)(h & 0xFFu);
}

void Game_PasswordEncode(uint32_t payload, char out[DC_PASSWORD_LEN + 1]) {
    uint64_t value = (uint64_t)payload |
                     ((uint64_t)Password_Checksum(payload) << 32);
    for (int i = DC_PASSWORD_LEN - 1; i >= 0; i--) {
        out[i] = kPasswordAlphabet[value % DC_PASSWORD_ALPHABET];
        value /= DC_PASSWORD_ALPHABET;
    }
    out[DC_PASSWORD_LEN] = '\0';
}

bool Game_PasswordDecode(const char *code, uint32_t *payload) {
    uint64_t value = 0;
    int n = 0;
    for (; code[n] && n < DC_PASSWORD_LEN; n++) {
        const char *p = strchr(kPasswordAlphabet, code[n]);
        if (!p)
            return false;
        value = value * DC_PASSWORD_ALPHABET +
                (uint64_t)(p - kPasswordAlphabet);
    }
    if (n != DC_PASSWORD_LEN)
        return false;
    uint32_t pay = (uint32_t)(value & 0xFFFFFFFFu);
    if ((uint8_t)(value >> 32) != Password_Checksum(pay))
        return false;
    if (payload)
        *payload = pay;
    return true;
}

static int ClampInt(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

uint32_t Game_PasswordPayload(const Game *game) {
    const Player *p = &game->player;
    uint32_t v = 0;
    v |= (uint32_t)(game->stages_cleared & 0xFFu);
    v |= (uint32_t)ClampInt(p->max_hp, 1, 15) << 8;
    v |= (uint32_t)(p->crests_mask & 0x3Fu) << 12;
    v |= (uint32_t)ClampInt(p->crest_form, 0, 7) << 18;
    v |= (uint32_t)ClampInt(p->potions, 0, 7) << 21;
    v |= (uint32_t)ClampInt(p->scrolls, 0, 7) << 24;
    v |= (uint32_t)(p->talisman_mask & 0x1Fu) << 27;
    return v;
}

bool Game_ApplyPassword(Game *game, const char *code) {
    uint32_t payload = 0;
    if (!Game_PasswordDecode(code, &payload))
        return false;
    Player *p = &game->player;
    game->stages_cleared = (uint8_t)(payload & 0xFFu);
    p->max_hp = ClampInt((int)((payload >> 8) & 0xFu), 1, 15);
    p->hp = p->max_hp;
    p->crests_mask = (uint8_t)((payload >> 12) & 0x3Fu);
    p->crest_form = (int)((payload >> 18) & 0x7u);
    if (p->crest_form >= CREST_COUNT)
        p->crest_form = CREST_BASE;
    p->potions = (int)((payload >> 21) & 0x7u);
    p->scrolls = (int)((payload >> 24) & 0x7u);
    p->talisman_mask = (uint8_t)((payload >> 27) & 0x1Fu);
    if (!(p->talisman_mask & (1u << p->active_talisman)))
        p->active_talisman = 0;
    return true;
}

void Game_EncodePassword(const Game *game, char out[DC_PASSWORD_LEN + 1]) {
    Game_PasswordEncode(Game_PasswordPayload(game), out);
}

bool Game_PasswordSelfTest(void) {
    uint32_t state = 0x12345678u;
    for (int i = 0; i < 2000; i++) {
        state = state * 1664525u + 1013904223u;
        uint32_t payload = state;
        char code[DC_PASSWORD_LEN + 1];
        Game_PasswordEncode(payload, code);
        uint32_t decoded = 0;
        if (!Game_PasswordDecode(code, &decoded) || decoded != payload) {
            fprintf(stderr, "password selftest: FAIL at %d (%s)\n", i, code);
            return false;
        }
    }
    fprintf(stderr, "password selftest: OK (2000 round-trips)\n");
    return true;
}

static const char *Game_SavePath(void) {
    const char *env = getenv("DC_SAVE_PATH");
    if (env && *env)
        return env;
    return "saves/dc_save.json";
}

static bool Game_SaveDisabled(void) {
    if (getenv("DC_NO_SAVE"))
        return true;
    /* Deterministic runs must stay side-effect free unless a test opts in. */
    if (getenv("DC_RUN_FRAMES") && !getenv("DC_SAVE_FORCE"))
        return true;
    return false;
}

static void Game_MakeSaveDir(const char *path) {
    char dir[512];
    snprintf(dir, sizeof(dir), "%s", path);
    char *slash = strrchr(dir, '/');
    char *bslash = strrchr(dir, '\\');
    if (bslash && (!slash || bslash > slash))
        slash = bslash;
    if (!slash)
        return;
    *slash = '\0';
    if (*dir)
        (void)DC_MKDIR(dir); /* exists already -> EEXIST is fine */
}

bool Game_HasSave(void) {
    if (Game_SaveDisabled())
        return false;
    FILE *f = fopen(Game_SavePath(), "rb");
    if (!f)
        return false;
    fclose(f);
    return true;
}

static int Game_JsonInt(const cJSON *root, const char *key, int fallback) {
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsNumber(item))
        return fallback;
    return item->valueint;
}

bool Game_SaveProgress(const Game *game) {
    if (Game_SaveDisabled())
        return false;
    if (!game->campaign_mode)
        return false;

    cJSON *root = cJSON_CreateObject();
    if (!root)
        return false;
    const Player *p = &game->player;
    cJSON_AddNumberToObject(root, "version", DC_SAVE_VERSION);
    cJSON_AddNumberToObject(root, "area", game->level.area_id);
    cJSON_AddNumberToObject(root, "stages_cleared", game->stages_cleared);
    {
        /* Per-area clear flags, packed as hex (113 bytes -> 226 chars). */
        char hex[DC_CAMPAIGN_AREAS * 2 + 1];
        for (int i = 0; i < DC_CAMPAIGN_AREAS; i++)
            snprintf(hex + i * 2, 3, "%02x", game->area_cleared[i]);
        cJSON_AddStringToObject(root, "area_cleared", hex);
    }
    cJSON_AddNumberToObject(root, "max_hp", p->max_hp);
    cJSON_AddNumberToObject(root, "hp", p->hp);
    cJSON_AddNumberToObject(root, "crests", p->crests_mask);
    cJSON_AddNumberToObject(root, "form", p->crest_form);
    cJSON_AddNumberToObject(root, "talismans", p->talisman_mask);
    cJSON_AddNumberToObject(root, "talisman", p->active_talisman);
    cJSON_AddNumberToObject(root, "fire_element", p->fire_element);
    cJSON_AddNumberToObject(root, "potions", p->potions);
    cJSON_AddNumberToObject(root, "scrolls", p->scrolls);
    cJSON_AddNumberToObject(root, "gold", p->gold);
    cJSON_AddNumberToObject(root, "volume", (double)Audio_GetVolume());

    char *text = cJSON_Print(root);
    cJSON_Delete(root);
    if (!text)
        return false;

    const char *path = Game_SavePath();
    Game_MakeSaveDir(path);
    FILE *f = fopen(path, "wb");
    bool ok = false;
    if (f) {
        ok = fwrite(text, 1, strlen(text), f) == strlen(text);
        fclose(f);
    }
    cJSON_free(text);
    if (!ok)
        fprintf(stderr, "game: cannot write save %s\n", path);
    return ok;
}

bool Game_LoadProgress(Game *game) {
    if (Game_SaveDisabled())
        return false;
    const char *path = Game_SavePath();
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size <= 0 || size > 65536) {
        fclose(f);
        return false;
    }
    char *text = (char *)malloc((size_t)size + 1);
    if (!text) {
        fclose(f);
        return false;
    }
    size_t got = fread(text, 1, (size_t)size, f);
    fclose(f);
    text[got] = '\0';

    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root)
        return false;
    if (Game_JsonInt(root, "version", 0) != DC_SAVE_VERSION) {
        cJSON_Delete(root);
        return false;
    }

    int area = Game_JsonInt(root, "area", game->level.area_id);
    if (area >= 0 && area < DC_CAMPAIGN_AREAS && area != game->level.area_id)
        (void)Game_TransitionToArea(game, area, 0);

    Player *p = &game->player;
    p->max_hp = Game_JsonInt(root, "max_hp", p->max_hp);
    if (p->max_hp < 1)
        p->max_hp = 6;
    if (p->max_hp > 12)
        p->max_hp = 12;
    p->hp = Game_JsonInt(root, "hp", p->max_hp);
    if (p->hp < 1)
        p->hp = 1;
    if (p->hp > p->max_hp)
        p->hp = p->max_hp;
    p->crests_mask = (uint8_t)Game_JsonInt(root, "crests", p->crests_mask);
    int form = Game_JsonInt(root, "form", p->crest_form);
    p->crest_form = (form >= 0 && form < CREST_COUNT) ? form : CREST_BASE;
    p->talisman_mask = (uint8_t)Game_JsonInt(root, "talismans",
                                             p->talisman_mask);
    int talisman = Game_JsonInt(root, "talisman", p->active_talisman);
    p->active_talisman = (talisman >= 0 && talisman < 5) ? talisman : 0;
    p->fire_element = Game_JsonInt(root, "fire_element", p->fire_element) % 5;
    p->potions = Game_JsonInt(root, "potions", p->potions);
    p->scrolls = Game_JsonInt(root, "scrolls", p->scrolls);
    p->gold = Game_JsonInt(root, "gold", p->gold);
    game->stages_cleared = (uint8_t)Game_JsonInt(root, "stages_cleared",
                                                 game->stages_cleared);
    const cJSON *cleared = cJSON_GetObjectItemCaseSensitive(root, "area_cleared");
    if (cJSON_IsString(cleared) && cleared->valuestring) {
        const char *s = cleared->valuestring;
        for (int i = 0; i < DC_CAMPAIGN_AREAS; i++) {
            char byte[3] = {s[i * 2], s[i * 2] ? s[i * 2 + 1] : 0, 0};
            if (!byte[0] || !byte[1])
                break;
            game->area_cleared[i] = (uint8_t)strtoul(byte, NULL, 16);
        }
    }

    const cJSON *vol = cJSON_GetObjectItemCaseSensitive(root, "volume");
    if (cJSON_IsNumber(vol))
        Audio_SetVolume((float)vol->valuedouble);
    cJSON_Delete(root);
    game->has_save = true;
    return true;
}

static void Game_StartEnding(Game *game);

bool Game_Init(Game *game, const char *asset_dir) {
    memset(game, 0, sizeof(*game));
    snprintf(game->asset_dir, sizeof(game->asset_dir), "%s", asset_dir);
    if (!Assets_Load(&game->assets, asset_dir)) {
        fprintf(stderr, "game: asset load failed (run tools/dc_extract first)\n");
        return false;
    }
    if (!Level_Load(&game->level, &game->assets, asset_dir)) {
        Assets_Unload(&game->assets);
        return false;
    }
    Assets_LoadAreaBg(&game->assets, game->level.area_id);
    Player_Init(&game->player, &game->level);
    game->intro_timer = 110;
    Projectiles_Init(&game->projectiles);
    Objects_Init(&game->objects, &game->level);
    Camera_Init(&game->camera, &game->level);
    game->target = LoadRenderTexture(256, 224);
    if (!IsRenderTextureValid(game->target)) {
        fprintf(stderr, "game: failed to create 256x224 render target\n");
        Level_Unload(&game->level);
        Assets_Unload(&game->assets);
        return false;
    }
    SetTextureFilter(game->target.texture, TEXTURE_FILTER_POINT);

    const char *trace_path = getenv("DC_TRACE_CSV");
    if (trace_path && *trace_path) {
        game->trace = fopen(trace_path, "w");
        if (game->trace) {
            fprintf(game->trace,
                    "frame,player_x,player_y,vx,vy,state,camera_x,camera_y,hp,max_hp,area,form,gold,fire,mode\n");
        } else {
            fprintf(stderr, "game: cannot open trace file %s\n", trace_path);
        }
    }

    const char *proj_trace_path = getenv("DC_TRACE_PROJECTILES");
    if (proj_trace_path && *proj_trace_path) {
        game->projectile_trace = fopen(proj_trace_path, "w");
        if (game->projectile_trace) {
            fprintf(game->projectile_trace, "frame,slot,x,y,vx,age\n");
        } else {
            fprintf(stderr, "game: cannot open projectile trace %s\n",
                    proj_trace_path);
        }
    }

    const char *object_trace_path = getenv("DC_TRACE_OBJECTS");
    if (object_trace_path && *object_trace_path) {
        game->object_trace = fopen(object_trace_path, "w");
        if (game->object_trace) {
            fprintf(game->object_trace,
                    "frame,slot,type,x,y,vx,vy,state,hp,flash,species,flags\n");
        } else {
            fprintf(stderr, "game: cannot open object trace %s\n",
                    object_trace_path);
        }
    }

    game->ready = true;
    game->has_save = Game_HasSave();
    if (Text_LoadScript(&game->script, asset_dir)) {
        game->script_ready = true;
        game->shop_welcome = Text_Find(&game->script, "BLACK LOTUS");
        game->shop_full_urn = Text_Find(&game->script, "NEED AN URN");
        game->shop_full_vellum = Text_Find(&game->script, "VELLUM IS");
        game->shop_no_money = Text_Find(&game->script, "CHEAPSKATE");
        game->shop_need_vellum = Text_Find(&game->script, "VELLUM FIRST");
        game->ending_text = Text_Find(&game->script, "PHALANX WOULD");
        game->town_greet = Text_Find(&game->script, "HAVEN'T SEEN YOU");
        game->town_question = Text_Find(&game->script, "ARE YOU A STRANGER");
        game->town_story[0] = Text_Find(&game->script, "FIREBRAND HAS RISEN");
        game->town_story[1] = Text_Find(&game->script, "BURNT THE DEMON REALM");
        game->town_story[2] = Text_Find(&game->script, "RESCUED US");
        game->town_story[3] = Text_Find(&game->script, "ARROGANT FOOL");
        game->town_story[4] = Text_Find(&game->script, "ESCAPED FROM THE COLOSSEUM");
        game->crest_text[CREST_EARTH] =
            Text_Find(&game->script, "CREST OF \"EARTH\"");
        game->crest_text[CREST_AIR] =
            Text_Find(&game->script, "CREST OF \"AIR\"");
        game->crest_text[CREST_WATER] =
            Text_Find(&game->script, "CREST OF \"WATER\"");
        game->crest_text[CREST_TIME] =
            Text_Find(&game->script, "CREST OF \"TIME\"");
        game->fire_text[1] = Text_Find(&game->script, "\"BUSTER\"");
        game->fire_text[2] = Text_Find(&game->script, "\"TORNADO\"");
        game->fire_text[3] = Text_Find(&game->script, "\"CLAW\"");
        game->fire_text[4] = Text_Find(&game->script, "\"DEMON FIRE\"");
        game->dialogue_demo = getenv("DC_DIALOGUE") != NULL;
    }
    const char *password_env = getenv("DC_PASSWORD");
    if (password_env && *password_env) {
        if (Game_ApplyPassword(game, password_env)) {
            game->campaign_mode = true;
            fprintf(stderr, "game: password applied\n");
        } else {
            fprintf(stderr, "game: invalid DC_PASSWORD\n");
        }
    }
    const char *demo = getenv("DC_DEMO");
    bool force_title = getenv("DC_TITLE") != NULL;
    bool automated = !force_title &&
                     (getenv("DC_RUN_FRAMES") ||
                      (demo && *demo && strcmp(demo, "0") != 0));
    game->state = automated ? GAME_PLAYING : GAME_TITLE;
    if (getenv("DC_CAMPAIGN"))
        game->campaign_mode = true;
    /* Debug state selection for screenshots of campaign menus. */
    const char *state_env = getenv("DC_STATE");
    if (state_env && *state_env) {
        if (strcmp(state_env, "title") == 0)
            game->state = GAME_TITLE;
        else if (strcmp(state_env, "overworld") == 0) {
            game->campaign_mode = true;
            Game_OpenOverworld(game);
        } else if (strcmp(state_env, "subscreen") == 0)
            game->state = GAME_SUBSCREEN;
        else if (strcmp(state_env, "pause") == 0)
            game->state = GAME_PAUSED;
        else if (strcmp(state_env, "shop") == 0)
            game->state = GAME_SHOP;
        else if (strcmp(state_env, "password") == 0)
            game->state = GAME_PASSWORD;
        else if (strcmp(state_env, "options") == 0)
            game->state = GAME_OPTIONS;
        else if (strcmp(state_env, "clear") == 0) {
            game->campaign_mode = true;
            Game_CompleteArea(game);
        } else if (strcmp(state_env, "gameover") == 0)
            game->state = GAME_OVER;
        else if (strcmp(state_env, "continue") == 0) {
            /* Test hook: open the death hub without waiting for a death. */
            game->campaign_mode = true;
            game->player.hp = 0;
            game->state = GAME_CONTINUE;
            game->continue_cursor = 0;
        } else if (strcmp(state_env, "ending") == 0)
            Game_StartEnding(game);
    }
    game->state_timer = 0;
    game->kill_at = getenv("DC_KILL_AT") ? atoi(getenv("DC_KILL_AT")) : 0;

    /* Dev hook: jump straight into a story page for deterministic captures
     * (`DC_STORY_TEST=<crest index>`, optional `DC_STORY_PAGE`). */
    if (getenv("DC_STAGE_SELECT"))
        game->stage_select = true;
    const char *stage_sel_env = getenv("DC_STAGE_INDEX");
    if (stage_sel_env && *stage_sel_env)
        game->stage_sel = atoi(stage_sel_env);
    const char *fire_test = getenv("DC_FIRE_TEST");
    if (fire_test && *fire_test && game->script_ready) {
        int piece = atoi(fire_test);
        if (piece >= 1 && piece <= 4 && game->fire_text[piece] >= 0) {
            game->dialogue_text = game->fire_text[piece];
            const char *page = getenv("DC_STORY_PAGE");
            game->dialogue_page = page ? atoi(page) : 0;
            game->dialogue_return = GAME_TITLE;
            game->state = GAME_DIALOGUE;
        }
    }
    /* Dev hook: start the city-NPC conversation at page N (0 greeting,
     * 1 question + YES/NO, 2+ story pages after answering YES). */
    const char *gold = getenv("DC_GOLD");
    if (gold && *gold)
        game->player.gold = atoi(gold);

    const char *talk = getenv("DC_TALK");
    if (talk && *talk && game->script_ready) {
        Game_StartTownTalk(game);
        int step = atoi(talk);
        for (int i = 0; i < step; i++) {
            if (game->talk_choice == 1) {
                int story[6] = {game->town_story[0], game->town_story[1],
                                game->town_story[2], game->town_story[3], -1,
                                -1};
                for (int k = 0; k < 6; k++)
                    if (story[k] >= 0 && game->talk_len < 10)
                        game->talk_seq[game->talk_len++] = story[k];
                game->talk_choice = 0;
            }
            if (game->talk_pos + 1 < game->talk_len) {
                game->talk_pos++;
                game->dialogue_text = game->talk_seq[game->talk_pos];
                game->dialogue_page = 0;
            }
            if (game->dialogue_text == game->town_question &&
                game->talk_pos + 1 >= game->talk_len)
                game->talk_choice = 1;
        }
    }
    const char *story_test = getenv("DC_STORY_TEST");
    if (getenv("DC_STORY_DEBUG"))
        fprintf(stderr, "story: ready=%d crest_text=[%d %d %d %d %d %d]\n",
                game->script_ready, game->crest_text[0], game->crest_text[1],
                game->crest_text[2], game->crest_text[3], game->crest_text[4],
                game->crest_text[5]);
    if (story_test && *story_test && game->script_ready) {
        int crest = atoi(story_test);
        if (crest >= 0 && crest < CREST_COUNT && game->crest_text[crest] >= 0) {
            game->dialogue_text = game->crest_text[crest];
            const char *page = getenv("DC_STORY_PAGE");
            game->dialogue_page = page ? atoi(page) : 0;
            game->dialogue_return = GAME_TITLE;
            game->state = GAME_DIALOGUE;
        }
    }

    Audio_Init(game->asset_dir);
    /* Dev hook: resume the saved run without going through the title menu. */
    if (getenv("DC_RESUME") && game->has_save) {
        if (Game_LoadProgress(game)) {
            game->campaign_mode = true;
            game->state = GAME_PLAYING;
            game->state_timer = 0;
        }
    }
    Audio_StartMusic();
    return true;
}

static bool Game_NarrativeEnabled(void);

static void Game_UpdateSimulation(Game *game) {
    game->objects.events = 0;
    game->objects.last_fire_piece = 0;
    Player_Update(&game->player, &game->level, &game->input);
    if (game->player.jump_started)
        Audio_Play(SFX_JUMP);
    if (game->player.landed_event)
        Audio_Play(SFX_LAND);

    bool shot = game->player.shot_fired;
    /* Existing shots move first; a shot fired this frame stays at its spawn
     * position for one frame, matching the original object loop. */
    Projectiles_Update(&game->projectiles, &game->level, &game->camera);
    if (shot) {
        Projectiles_Spawn(&game->projectiles, &game->player);
        game->player.shot_fired = false;
        Audio_Play(SFX_SHOOT);
    }
    Objects_CheckProjectiles(&game->objects, &game->projectiles);
    Objects_Update(&game->objects, &game->level, &game->player);
    if ((game->objects.events & OBJECT_EVENT_FIRE_PIECE) &&
        Game_NarrativeEnabled()) {
        int piece = game->objects.last_fire_piece;
        if (piece >= 1 && piece <= 4 && game->fire_text[piece] >= 0) {
            game->dialogue_text = game->fire_text[piece];
            game->dialogue_page = 0;
            game->dialogue_return = GAME_PLAYING;
            game->state = GAME_DIALOGUE;
            game->state_timer = 0;
        }
    }
    if (game->objects.events & OBJECT_EVENT_TALISMAN) {
        int talisman = game->objects.last_talisman;
        if (talisman >= 0 && talisman < 5) {
            game->talisman_toast = 150;
            game->talisman_toast_index = talisman;
            Audio_Play(SFX_PICKUP);
        }
    }
    if (game->talisman_toast > 0)
        game->talisman_toast--;
    if (game->player.hurt_event)
        Audio_Play(SFX_HURT);
    if (game->objects.events & OBJECT_EVENT_BREAK)
        Audio_Play(SFX_BREAK);
    if (game->objects.events & OBJECT_EVENT_PICKUP)
        Audio_Play(SFX_PICKUP);
    if (game->objects.events & OBJECT_EVENT_ENEMY_HIT)
        Audio_Play(SFX_ENEMY_HIT);
    if (game->objects.events & OBJECT_EVENT_BOSS_DEFEATED)
        Audio_Play(SFX_BREAK);
    if (game->objects.events & OBJECT_EVENT_CREST_PICKUP)
        Audio_Play(SFX_PICKUP);

    Player_Animate(&game->player,
                       Assets_PlayerAnimForForm(&game->assets,
                                                game->player.crest_form));
    Camera_Update(&game->camera, &game->level, &game->player);

    for (int i = 0; i < game->level.object_count; i++) {
        const LevelObject *o = &game->level.objects[i];
        if (o->type != LEVEL_OBJECT_EXIT)
            continue;
        if (fabsf(game->player.x - o->x) >= 16.0f ||
            fabsf(game->player.y - o->y) >= 32.0f)
            continue;
        /* Boss-gated exits stay closed until the area boss is defeated. */
        if (game->objects.boss_alive)
            break;
        if (!game->campaign_mode) {
            game->state = GAME_CLEAR;
            game->state_timer = 0;
            break;
        }
        int next = game->level.gate_next_area;
        if (next >= 0) {
            Game_BeginTransition(game, next, 0);
        } else {
            game->campaign_mode = true;
            Game_OpenOverworld(game);
        }
        return;
    }


    if (game->projectile_trace) {
        for (int i = 0; i < PROJECTILE_POOL_SIZE; i++) {
            const Projectile *p = &game->projectiles.slots[i];
            if (!p->active)
                continue;
            fprintf(game->projectile_trace, "%u,%d,%.3f,%.3f,%.3f,%d\n",
                    game->frame, i, (float)p->x_fx / 256.0f,
                    (float)p->y_fx / 256.0f, (float)p->vx_fx / 256.0f,
                    p->age);
        }
    }
    if (game->object_trace) {
        for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
            const Object *o = &game->objects.slots[i];
            if (!o->active)
                continue;
            fprintf(game->object_trace,
                    "%u,%d,%d,%.3f,%.3f,%.3f,%.3f,%d,%d,%d,%d,%d\n",
                    game->frame, i, (int)o->type,
                    (float)o->x_fx / 256.0f, (float)o->y_fx / 256.0f,
                    (float)o->vx_fx / 256.0f, (float)o->vy_fx / 256.0f,
                    o->state, o->hp, o->hit_flash, o->species, o->flags);
        }
    }
    game->frame++;
}

static bool PlayerInsideTransition(const Player *player,
                                   const LevelTransition *tr) {
    /* The original box check runs before collision resolution, so a door box
     * embedded in the room's edge wall is reachable while walking into it. */
    /* Pad by roughly the player's half size, not a whole tile: a +20 x-pad
     * made doors trigger from the spawn point of small rooms (instant loop). */
    return fabsf(player->x - tr->x) <= tr->half_w + 10.0f &&
           fabsf(player->y - tr->y) <= tr->half_h + 10.0f;
}

/* The transition records carry a pad mask: the direction that opens the door.
 * The bits follow the ROM's own order, right/left/down/up, so 8 is up --
 * measured on the stage II takes, where 5->6, 6->7 and 7->8 are all preceded
 * by a tap of up (docs/TAKES.md §6.1). 255 is "any direction" and is how the
 * plain walk-through exits are stored; 0 means the field is absent (older room
 * documents) and keeps the pre-pad_mask behaviour. Only the up bit is measured
 * today; the other three exist so a future door never opens on proximity. */
static bool TransitionPadHeld(const Input *input,
                              const LevelTransition *tr) {
    int mask = tr->pad_mask;
    if (mask == 0 || mask == 255)
        return true;
    if ((mask & 8) && input->up)
        return true;
    if ((mask & 4) && input->down)
        return true;
    if ((mask & 2) && input->left)
        return true;
    if ((mask & 1) && input->right)
        return true;
    return false;
}

static void Game_CheckTransitions(Game *game) {
    if (!game->campaign_mode)
        return;
    /* Test/revisit hook: pretend the room's boss is already dead. Applied here
     * because the boss object is spawned during the level load, after the
     * Game_Reset hooks run. */
    if (getenv("DC_BOSS_CLEAR") && game->objects.boss_alive &&
        game->objects.boss_present) {
        game->objects.boss_alive = false;
        game->objects.boss_defeated = true;
    }
    Player *player = &game->player;
    if (!game->objects.boss_alive) {
        for (int i = 0; i < game->level.transition_count; i++) {
            const LevelTransition *tr = &game->level.transitions[i];
            if (tr->next_area < 0 || tr->next_area >= 113 ||
                tr->next_area == game->level.area_id)
                continue;
            if (PlayerInsideTransition(player, tr) &&
                TransitionPadHeld(&game->input, tr)) {
                Game_BeginTransition(game, tr->next_area, tr->spawn_id);
                return;
            }
        }
    }
    /* Boss gate $81:97DA: advancing requires the area boss to be defeated.
     * Rooms without a boss never auto-advance: otherwise a small room whose
     * world width is narrower than the spawn point would gate out instantly. */
    if (getenv("DC_DEBUG_OBJ"))
        fprintf(stderr,
                "gate: next=%d present=%d alive=%d defeated=%d x=%.0f w=%d\n",
                game->level.gate_next_area, game->objects.boss_present,
                game->objects.boss_alive, game->objects.boss_defeated,
                player->x, game->level.world_w);
    if (game->level.gate_next_area >= 0 &&
        game->level.gate_next_area < 113 && game->objects.boss_present &&
        !game->objects.boss_alive) {
        /* Walls keep the player a few pixels inside the world edge, so the
         * gate has to start a little before it. */
        float gate_x = (float)game->level.world_w - 40.0f;
        if (player->x >= gate_x) {
            Game_BeginTransition(game, game->level.gate_next_area, 0);
            return;
        }
    }
}

/* Somulo's entrance, as the recorded fight shows it: he is on the far side of
 * the colosseum behind the gate, his steps shake the screen as he comes through,
 * and he roars before Firebrand has control. Phases:
 *   1  waiting off-screen, distant steps
 *   2  walking in to the arena
 *   3  the roar
 * Returns true while the intro still owns the frame. */
static bool Game_UpdateBossIntro(Game *game) {
    if (game->level.area_id != 0 || game->objects.boss_alive == false) {
        if (game->level.area_id != 0)
            game->boss_intro = 0;
    }
    ObjectPool *pool = &game->objects;
    Object *boss = NULL;
    for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
        Object *o = &pool->slots[i];
        if (o->active && o->type == OBJECT_BOSS) {
            boss = o;
            break;
        }
    }
    if (!boss) {
        game->boss_intro = 0;
        return false;
    }

    /* No control, and no shooting at him during the entrance. */
    game->input.left = false;
    game->input.right = false;
    game->input.up = false;
    game->input.down = false;
    game->input.jump_pressed = false;
    game->input.jump_held = false;
    game->input.shot_pressed = false;
    game->input.shot_held = false;

    game->boss_intro_timer++;
    int f = game->boss_intro_timer;
    /* The real entrance pans the camera with him; the player is not the
     * subject until the roar ends. */
    Camera_Focus(&game->camera, &game->level,
                 (float)boss->x_fx / 256.0f);
    if (game->shake > 0)
        game->camera.x += (float)((game->shake % 5) - 2);
    const int32_t fx_one = 256;
#define FX_ONE fx_one

    switch (game->boss_intro) {
    case 1: /* establishing shot: Firebrand alone, distant thumps off-screen */
        boss->x_fx = (int32_t)(-70.0f * FX_ONE);
        /* The camera stays on the player until Somulo is actually coming. */
        Camera_Focus(&game->camera, &game->level,
                     (float)game->player.x);
        if (f == 1 || (f % 46) == 0)
            game->shake = 10;
        if (f > 150) {
            game->boss_intro = 2;
            game->boss_intro_timer = 0;
        }
        break;
    case 2: /* off-screen, coming closer: heavier and heavier steps */
        boss->x_fx = (int32_t)(-70.0f * FX_ONE);
        if (f == 1 || (f % 22) == 0)
            game->shake = 14;
        if (f > 70) {
            game->boss_intro = 3;
            game->boss_intro_timer = 0;
        }
        break;
    case 3: /* walking in, one heavy step after another */
        boss->state = 8;   /* walking pose; the intro moves him, not the AI */
        /* He stops short of Firebrand: the walk-in ends where the roar can be
         * seen from both characters, and the deadly blind walk is what closes
         * the distance afterwards. Walking him to x=288 walked him *through*
         * the player before the fight even started. */
        if (boss->x_fx < (int32_t)(40.0f * FX_ONE))
            boss->x_fx += (int32_t)(1.3f * FX_ONE);
        if ((f % 24) == 5)
            game->shake = 16;
        if (f > 280) {
            game->boss_intro = 4;
            game->boss_intro_timer = 0;
            game->shake = 26;
        }
        break;
    case 4: /* the roar: this is the beat after which control returns */
        boss->state = 4;   /* the roar pose (head thrust forward, jaws wide) */
        if (f == 1) {
            game->shake = 60;
            boss->hit_flash = 0;
        }
        if (f > 110) {
            game->boss_intro = 0;
            game->boss_intro_timer = 0;
            /* He starts walking blind down the corridor: contact is fatal. */
            boss->state = 7;
            boss->phase = 420;
            boss->substate = 0;
        }
        break;
    default:
        game->boss_intro = 0;
        break;
    }
    if (getenv("DC_BOSS_INTRO_DEBUG")) {
        static int last = -1;
        if (game->boss_intro != last) {
            fprintf(stderr, "boss intro: phase %d at frame %d (boss x=%.1f)\n",
                    game->boss_intro, f, (float)boss->x_fx / FX_ONE);
            last = game->boss_intro;
        }
    }
    return true;
}

static void Game_HandleDeath(Game *game) {
    if (game->player.hp > 0 || game->state != GAME_PLAYING)
        return;
    if (game->restart_timer > 0)
        return;
    /* The colosseum restarts the room (with Somulo's entrance) on death; the
     * other areas show the continue hub after the death animation. */
    if (game->level.area_id == 0 && getenv("DC_DEATH_GAMEOVER") == NULL) {
        game->restart_timer = 90;
        return;
    }
    if (game->death_timer == 0) {
        game->death_timer = 1;
        return;
    }
    if (game->death_timer < DC_DEATH_MENU_DELAY) {
        game->death_timer++;
        return;
    }
    game->state = GAME_CONTINUE;
    game->continue_cursor = 0;
    game->state_timer = 0;
}

/* The native code laid out in the retail 4x4 PASS WORD shape. The retail
 * codec is still not inverted; encoding the same 40-bit value with 16 base-20
 * digits only adds six leading zero symbols ('B'). */
static void Game_PasswordGrid(Game *game) {
    char code[DC_PASSWORD_LEN + 1];
    Game_EncodePassword(game, code);
    int pad = DC_PASSWORD_VIEW_CELLS - DC_PASSWORD_LEN;
    for (int i = 0; i < pad; i++)
        game->password_grid[i] = 'B';
    snprintf(game->password_grid + pad, sizeof(game->password_grid) - pad,
             "%s", code);
}

static void Game_ShowPassword(Game *game) {
    Game_EncodePassword(game, game->password_code);
    Game_PasswordGrid(game);
    game->state = GAME_PASSWORD_VIEW;
    game->state_timer = 0;
    Render_SetFade(0.0f);
}

static void Game_UpdateContinue(Game *game, bool up_pressed,
                                bool down_pressed) {
    if (up_pressed && game->continue_cursor > 0)
        game->continue_cursor--;
    if (down_pressed && game->continue_cursor < 2)
        game->continue_cursor++;
    if (!game->input.start_pressed)
        return;
    if (game->continue_cursor == 0) {
        /* RETRY reloads the same area at spawn 0 with full HP; the restart
         * path already does both, behind its 90-frame black fade. */
        game->state = GAME_PLAYING;
        game->state_timer = 0;
        game->death_timer = 0;
        game->restart_timer = 90;
    } else if (game->continue_cursor == 1) {
        game->death_timer = 0;
        Game_OpenOverworld(game);
    } else {
        Game_ShowPassword(game);
    }
}

/* Dev hooks: place the ship for deterministic landing tests. */
static void Game_OverworldHookPosition(Game *game) {
    const char *ox = getenv("DC_OVERWORLD_X");
    const char *oy = getenv("DC_OVERWORLD_Y");
    if (ox && *ox)
        game->overworld_x = (float)atof(ox);
    if (oy && *oy)
        game->overworld_y = (float)atof(oy);
    const char *oa = getenv("DC_OVERWORLD_ANGLE");
    if (oa && *oa)
        game->overworld_angle = (float)atof(oa);
    const char *oz = getenv("DC_OVERWORLD_ZOOM");
    if (oz && *oz)
        game->overworld_zoom = (float)atof(oz);
}

static void Game_OpenOverworld(Game *game) {
    (void)Game_SaveProgress(game);
    game->state = GAME_OVERWORLD;
    game->state_timer = 0;
    game->overworld_x = 96.0f;
    game->overworld_y = 176.0f;
    game->overworld_angle = 0.0f;
    if (game->overworld_zoom <= 0.0f)
        game->overworld_zoom = 1.0f;
    game->overworld_node = CAMPAIGN_GRAVEYARD;
    Game_OverworldHookPosition(game);
}

/* Deterministic test runs fast-forward story beats; players see them. */
static bool Game_NarrativeEnabled(void) {
    return getenv("DC_RUN_FRAMES") == NULL && getenv("DC_NO_STORY") == NULL;
}

static void Game_CompleteArea(Game *game) {
    int area = game->level.area_id;
    if (area >= 0 && area < 8)
        game->stages_cleared |= (uint8_t)(1u << area);
    if (area >= 0 && area < DC_CAMPAIGN_AREAS)
        game->area_cleared[area] = 1;
    /* Story progression: each cleared area grants the next Gargoyle Crest. */
    int granted = -1;
    switch (area) {
    case 0: granted = CREST_EARTH; break;
    case 1: granted = CREST_AIR; break;
    case 2: granted = CREST_WATER; break;
    case 3: granted = CREST_TIME; break;
    case 4: granted = CREST_ULTIMATE; break;
    default: break;
    }
    if (granted >= 0) {
        static const uint8_t kBits[CREST_COUNT] = {0x01, 0x02, 0x04, 0x08,
                                                  0x10, 0x20};
        game->player.crests_mask |= kBits[granted];
    }
    Game_EncodePassword(game, game->password_code);
    game->state = GAME_CLEAR;
    game->state_timer = 0;
    (void)Game_SaveProgress(game);
    /* Show the ROM's "YOU HAVE FOUND THE CREST OF ..." pages before the clear
     * banner when a crest was just granted and story beats are enabled. */
    if (granted >= 0 && granted < CREST_COUNT &&
        game->crest_text[granted] >= 0 && Game_NarrativeEnabled()) {
        game->dialogue_text = game->crest_text[granted];
        game->dialogue_page = 0;
        game->dialogue_return = GAME_CLEAR;
        game->state = GAME_DIALOGUE;
        game->state_timer = 0;
    }
}

static void Game_UpdateOverworld(Game *game) {
    /* Stage select overlay: X toggles it and it lists every stage entry room
     * from campaign.json, so all extracted content is reachable even where the
     * original map layout is not reproduced. */
    int count = game->assets.stage_count;
    if (game->input.subscreen_pressed && count > 0) {
        game->stage_select = !game->stage_select;
        return;
    }
    if (game->stage_select) {
        if (count <= 0) {
            game->stage_select = false;
        } else {
            if (game->stage_sel >= count)
                game->stage_sel = count - 1;
            if (game->stage_sel < 0)
                game->stage_sel = 0;
            if (game->input.up && game->stage_sel > 0)
                game->stage_sel--;
            if (game->input.down && game->stage_sel + 1 < count)
                game->stage_sel++;
            if (game->input.right && game->stage_sel + 6 < count)
                game->stage_sel += 6;
            if (game->input.left && game->stage_sel >= 6)
                game->stage_sel -= 6;
            if (game->input.start_pressed) {
                int area = game->assets.stage_entries[game->stage_sel];
                if (getenv("DC_STAGE_DEBUG"))
                    fprintf(stderr, "stage: travel frame %u sel %d area %d\n",
                            game->frame, game->stage_sel, area);
                if (Game_TransitionToArea(game, area, 0)) {
                    game->campaign_mode = true;
                    game->stage_select = false;
                    return;
                }
            }
            return;
        }
    }

    const float speed = 1.6f;
    float dx = 0.0f, dy = 0.0f;
    if (game->input.left)
        dx -= speed;
    if (game->input.right)
        dx += speed;
    if (game->input.up)
        dy -= speed;
    if (game->input.down)
        dy += speed;
    game->overworld_x += dx;
    game->overworld_y += dy;
    if (game->overworld_x < 24.0f)
        game->overworld_x = 24.0f;
    if (game->overworld_x > 232.0f)
        game->overworld_x = 232.0f;
    if (game->overworld_y < 152.0f)
        game->overworld_y = 152.0f;
    if (game->overworld_y > 208.0f)
        game->overworld_y = 208.0f;
    game->overworld_angle += (game->input.right ? 1.5f : 0.0f) -
                             (game->input.left ? 1.5f : 0.0f);
    while (game->overworld_angle >= 360.0f)
        game->overworld_angle -= 360.0f;
    while (game->overworld_angle < 0.0f)
        game->overworld_angle += 360.0f;
    /* Shoulder buttons / Q,E zoom the map like the original's view control. */
    if (game->overworld_zoom <= 0.0f)
        game->overworld_zoom = 1.0f;
    if (game->input.form_next_pressed) {
        game->overworld_zoom *= 1.12f;
        if (game->overworld_zoom > 2.0f)
            game->overworld_zoom = 2.0f;
    }

    /* Landing-point selection by nearest horizontal node. */
    static const struct { int node; float x; float y; } kNodes[] = {
        {CAMPAIGN_COLOSSEUM, 40.0f, 168.0f},
        {CAMPAIGN_GRAVEYARD, 96.0f, 176.0f},
        {CAMPAIGN_CATACOMBS, 144.0f, 184.0f},
        {CAMPAIGN_RUINS, 192.0f, 176.0f},
        {CAMPAIGN_LAKE, 64.0f, 200.0f},
        {CAMPAIGN_DEMON_KEEP, 224.0f, 160.0f},
    };
    int nearest = 1;
    float best = 1e9f;
    for (int i = 0; i < 6; i++) {
        float ddx = kNodes[i].x - game->overworld_x;
        float ddy = kNodes[i].y - game->overworld_y;
        float d2 = ddx * ddx + ddy * ddy;
        if (d2 < best) {
            best = d2;
            nearest = kNodes[i].node;
        }
    }
    game->overworld_node = nearest;

    if (game->input.start_pressed) {
        if (nearest == CAMPAIGN_DEMON_KEEP) {
            /* Final keep requires all earlier stages cleared. */
            if ((game->stages_cleared & 0x0F) == 0x0F) {
                Game_StartEnding(game);
                return;
            }
            return;
        }
        Game_TransitionToArea(game, nearest, 0);
        game->campaign_mode = true;
    } else if (game->input.special_pressed) {
        game->state = GAME_SHOP;
        game->state_timer = 0;
    }
}

static void Game_UpdateSubscreen(Game *game, bool left_pressed,
                                 bool right_pressed, bool up_pressed,
                                 bool down_pressed) {
    Player *p = &game->player;
    if (left_pressed)
        Player_CycleForm(p, -1);
    if (right_pressed)
        Player_CycleForm(p, 1);
    if (up_pressed) {
        if (game->subscreen_row > 0)
            game->subscreen_row--;
    }
    if (down_pressed) {
        if (game->subscreen_row < 5)
            game->subscreen_row++;
    }
    if (game->input.special_pressed)
        p->fire_element = (p->fire_element + 1) % 5;
    if (game->input.shot_pressed) {
        p->active_talisman = (p->active_talisman + 1) % 5;
        if (!(p->talisman_mask & (1u << p->active_talisman)))
            p->active_talisman = 0;
    }
    if (game->input.jump_pressed && p->potions > 0) {
        p->potions--;
        if (p->hp < p->max_hp)
            p->hp++;
        Audio_Play(SFX_PICKUP);
    }
    if (game->input.form_next_pressed && p->scrolls > 0) {
        p->scrolls--;
        if (p->hp > 0)
            p->hp--;
        Audio_Play(SFX_SHOOT);
    }
    if (game->input.subscreen_pressed || game->input.start_pressed ||
        game->input.pause_pressed) {
        game->state = GAME_PLAYING;
        game->state_timer = 0;
    }
}

static void Game_UpdateTitle(Game *game, bool up_pressed, bool down_pressed) {
    const int kItemCount = game->has_save ? 5 : 4;
    /* Idle on the title for ~10 s -> attract demo, like the original. */
    if (game->state_timer > 600 && !getenv("DC_NO_ATTRACT")) {
        game->campaign_mode = false;
        game->attract = true;
        game->attract_frame = 0;
        game->menu_cursor = 0;
        if (!Game_TransitionToArea(game, CAMPAIGN_COLOSSEUM, 0))
            Game_Reset(game);
        game->state = GAME_PLAYING;
        game->state_timer = 0;
        game->intro_timer = 0;
        return;
    }
    if (up_pressed && game->menu_cursor > 0)
        game->menu_cursor--;
    if (down_pressed && game->menu_cursor < kItemCount - 1)
        game->menu_cursor++;
    if (!game->input.start_pressed)
        return;
    int item = game->menu_cursor;
    if (game->has_save) {
        if (item == 0) {
            if (Game_LoadProgress(game)) {
                game->campaign_mode = true;
                game->state = GAME_PLAYING;
                game->state_timer = 0;
            }
            return;
        }
        item--;
    }
    switch (item) {
    case 0:
        game->campaign_mode = true;
        game->stages_cleared = 0;
        game->menu_cursor = 0;
        /* Reset run progression: Player_Init applies the 6 HP / 4 HP,
         * Base-Crest, 2 Urns and 1 Spell starting kit. */
        Player_Init(&game->player, &game->level);
        if (!Game_TransitionToArea(game, CAMPAIGN_COLOSSEUM, 0)) {
            Game_Reset(game);
            game->state = GAME_PLAYING;
        }
        break;
    case 1:
        game->campaign_mode = true;
        Game_OpenOverworld(game);
        break;
    case 2:
        Game_EncodePassword(game, game->password_entry);
        game->password_pos = 0;
        game->password_status = 0;
        game->state = GAME_PASSWORD;
        game->state_timer = 0;
        break;
    case 3:
        game->state = GAME_OPTIONS;
        game->state_timer = 0;
        break;
    default:
        break;
    }
}

/* Real stock and prices, read from the store's own menu ($85:88A0):
 * MERCURY 6, SULFUR 10, HERB 25, ELIXIR 100, GINSENG 140. */
static const struct {
    const char *name;
    int price;
    int kind; /* 0 escape, 1 heal some, 2 extra life, 3 full heal */
} kShopStock[] = {
    {"MERCURY", 6, 0},  {"SULFUR", 10, 0}, {"HERB", 25, 1},
    {"ELIXIR", 100, 2}, {"GINSENG", 140, 3},
};
#define SHOP_STOCK_COUNT ((int)(sizeof(kShopStock) / sizeof(kShopStock[0])))
#define SHOP_EXIT_INDEX SHOP_STOCK_COUNT

/* Area 96 (town) sells all five; area 110 has no Ginseng. */
static int ShopStockForArea(const Game *game) {
    if (game->level.area_id == 110)
        return 4;
    return SHOP_STOCK_COUNT;
}

static void Game_ShopBuy(Game *game) {
    const int stock = ShopStockForArea(game);
    if (game->shop_sel >= stock) {
        game->campaign_mode = true;
        Game_OpenOverworld(game);
        return;
    }
    const int price = kShopStock[game->shop_sel].price;
    if (game->player.gold < price) {
        /* "CHEAPSKATE! YOU DON'T HAVE ENOUGH MONEY" ($85:8B17) */
        game->shop_message = game->shop_no_money;
        game->shop_timer = 120;
        return;
    }
    if (kShopStock[game->shop_sel].kind == 0 && game->player.potions >= 5) {
        game->shop_message = game->shop_full_urn;
        game->shop_timer = 120;
        return;
    }
    game->player.gold -= price;
    switch (kShopStock[game->shop_sel].kind) {
    case 0: /* escape potions live in the urn */
        game->player.potions++;
        break;
    case 1: /* HERB: some vitality */
        game->player.hp += 4;
        if (game->player.hp > game->player.max_hp)
            game->player.hp = game->player.max_hp;
        break;
    case 2: /* ELIXIR: an extra life */
        if (game->player.max_hp < 10)
            game->player.max_hp++;
        game->player.hp = game->player.max_hp;
        break;
    case 3: /* GINSENG: all vitality */
        game->player.hp = game->player.max_hp;
        break;
    }
    Audio_Play(SFX_PICKUP);
}

static void Game_UpdateShop(Game *game, bool up_pressed,
                            bool down_pressed) {
    if (game->shop_timer > 0)
        game->shop_timer--;
    const int stock = ShopStockForArea(game);
    if (up_pressed)
        game->shop_sel = (game->shop_sel + stock) % (stock + 1);
    if (down_pressed)
        game->shop_sel = (game->shop_sel + 1) % (stock + 1);
    if (game->input.start_pressed)
        Game_ShopBuy(game);
    if (game->input.pause_pressed) {
        game->campaign_mode = true;
        Game_OpenOverworld(game);
    }
}

static void Game_UpdatePassword(Game *game, bool up_pressed,
                               bool down_pressed, bool left_pressed,
                               bool right_pressed) {
    if (game->password_entry[0] == '\0') {
        Game_EncodePassword(game, game->password_entry);
        game->password_pos = 0;
    }
    if (left_pressed && game->password_pos > 0)
        game->password_pos--;
    if (right_pressed && game->password_pos < DC_PASSWORD_LEN - 1)
        game->password_pos++;
    if (up_pressed || down_pressed) {
        int dir = down_pressed ? 1 : -1;
        char *c = &game->password_entry[game->password_pos];
        const char *p = strchr(kPasswordAlphabet, *c);
        int idx = p ? (int)(p - kPasswordAlphabet) : 0;
        idx = (idx + dir + DC_PASSWORD_ALPHABET) % DC_PASSWORD_ALPHABET;
        *c = kPasswordAlphabet[idx];
        game->password_status = 0;
    }
    if (game->input.start_pressed) {
        if (Game_ApplyPassword(game, game->password_entry)) {
            game->password_status = 1;
            game->campaign_mode = true;
            game->has_save = true;
            Game_OpenOverworld(game);
        } else {
            game->password_status = -1;
        }
    } else if (game->input.pause_pressed) {
        game->state = GAME_TITLE;
        game->state_timer = 0;
    }
}

static void Game_UpdateOptions(Game *game) {
    if (game->input.left)
        Audio_SetVolume(Audio_GetVolume() - 0.1f);
    if (game->input.right)
        Audio_SetVolume(Audio_GetVolume() + 0.1f);
    if (game->input.start_pressed || game->input.pause_pressed) {
        game->state = GAME_TITLE;
        game->state_timer = 0;
    }
}

/* Title, stage, boss and ending loops follow the game state. */
static void Game_SyncMusic(Game *game) {
    int track = MUSIC_STAGE;
    if (game->state == GAME_PLAYING && game->restart_timer > 0) {
        /* Fade out, then hold black for the reload and fade back in. */
        int t_left = game->restart_timer;
        float fade = t_left > 60 ? (float)(90 - t_left) / 30.0f
                                 : (t_left < 20 ? (float)t_left / 20.0f : 1.0f);
        Render_SetFade(fade);
        game->restart_timer--;
        if (game->restart_timer == 0) {
            int area = game->level.area_id;
            Game_TransitionToArea(game, area, 0);
            game->player.hp = game->player.max_hp;
            game->boss_intro = 0;
            game->shake_phase = 0;
            game->shake = 0;
            Render_SetFade(0.0f);
        }
        return;
    }

    if (game->state == GAME_PLAYING && game->boss_intro > 0 &&
        Game_UpdateBossIntro(game))
        return;

    switch ((GameState)game->state) {
    case GAME_TITLE:
        track = MUSIC_TITLE;
        break;
    case GAME_ENDING:
        track = MUSIC_ENDING;
        break;
    case GAME_PLAYING:
    case GAME_PAUSED:
    case GAME_SUBSCREEN:
    case GAME_SHOP:
        track = (game->objects.boss_present && game->objects.boss_alive)
                    ? MUSIC_BOSS
                    : MUSIC_STAGE;
        break;
    case GAME_OVERWORLD:
    case GAME_CLEAR:
    case GAME_DIALOGUE:
    case GAME_PASSWORD:
    case GAME_OPTIONS:
    case GAME_OVER:
    default:
        track = MUSIC_STAGE;
        break;
    }
    Audio_SetTrack(track);
}

/* Start a dialogue page sequence; indices < 0 are skipped. */
static void Game_StartTalk(Game *game, const int *pages, int count) {
    game->talk_len = 0;
    for (int i = 0; i < count && game->talk_len < 10; i++) {
        if (pages[i] >= 0)
            game->talk_seq[game->talk_len++] = pages[i];
    }
    if (game->talk_len == 0)
        return;
    game->talk_pos = 0;
    game->talk_choice = 0;
    game->talk_choice_sel = 0;
    game->dialogue_text = game->talk_seq[0];
    game->dialogue_page = 0;
    game->state = GAME_DIALOGUE;
    game->state_timer = 0;
}

/* The city NPC's conversation: greeting, question, then the story pages. */
static void Game_StartTownTalk(Game *game) {
    int pages[3] = {game->town_greet, game->town_question, -1};
    Game_StartTalk(game, pages, 3);
}

/* A presses near an NPC: 0x96 talks (city), 0x10 opens the shop. */
static void Game_TryTalk(Game *game) {
    if (getenv("DC_DEBUG_OBJ"))
        fprintf(stderr, "trytalk: player %.0f,%.0f\n", game->player.x,
                game->player.y);
    for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
        const Object *o = &game->objects.slots[i];
        if (!o->active)
            continue;
        float ox = (float)o->x_fx / 256.0f;
        float oy = (float)o->y_fx / 256.0f;
        if (fabsf(ox - game->player.x) > 30.0f ||
            fabsf(oy - game->player.y) > 36.0f)
            continue;
        if (getenv("DC_DEBUG_OBJ"))
            fprintf(stderr,
                    "talk: slot %d type %d species %d at %.0f,%.0f "
                    "(player %.0f,%.0f)\n",
                    i, (int)o->type, o->species, ox, oy, game->player.x,
                    game->player.y);
        if (o->species == 0x96 && game->town_greet >= 0) {
            Game_StartTownTalk(game);
            return;
        }
        if (o->species == 0x10) {
            game->state = GAME_SHOP;
            game->state_timer = 0;
            return;
        }
    }
}

/* Writes one trace row per frame regardless of game state, so tests can
 * observe menu/clear/dialogue modes as well as gameplay. */
static void Game_TraceFrame(Game *game) {
    if (!game->trace)
        return;
    {
        fprintf(game->trace,
                "%u,%.3f,%.3f,%.3f,%.3f,%d,%.3f,%.3f,%d,%d,%d,%d,%d,%d,%d\n",
                game->frame, game->player.x, game->player.y,
                game->player.vx, game->player.vy, (int)game->player.state,
                game->camera.x, game->camera.y, game->player.hp,
                game->player.max_hp, game->level.area_id,
                game->player.crest_form, game->player.gold,
                game->player.fire_element, (int)game->state);
    }
}

void Game_Update(Game *game) {
    Input_Read(&game->input, &game->input_state);
    if (game->attract) {
        bool cancel = game->input.start_pressed || game->input.pause_pressed ||
                      game->input.jump_pressed || game->input.special_pressed;
        if (cancel) {
            game->attract = false;
            game->state = GAME_TITLE;
            game->state_timer = 0;
            game->intro_timer = 0;
            return;
        }
        int f = ++game->attract_frame;
        bool right = f > 30 && f < 260;
        bool shoot = (f % 20) == 0;
        game->input.left = false;
        game->input.up = false;
        game->input.down = false;
        game->input.jump_held = false;
        game->input.jump_pressed = false;
        game->input.special_pressed = false;
        game->input.special_held = false;
        game->input.subscreen_pressed = false;
        game->input.form_next_pressed = false;
        game->input.start_pressed = false;
        game->input.pause_pressed = false;
        game->input.right = right;
        game->input.shot_pressed = shoot;
        game->input.shot_held = shoot;
    }
    game->state_timer++;
    if (game->shake > 0)
        game->shake--;

    /* Edge-detect direction presses for menu navigation. */
    bool up_pressed = game->input.up && !game->prev_up;
    bool down_pressed = game->input.down && !game->prev_down;
    bool left_pressed = game->input.left && !game->prev_left;
    bool right_pressed = game->input.right && !game->prev_right;
    game->prev_up = game->input.up;
    game->prev_down = game->input.down;
    game->prev_left = game->input.left;
    game->prev_right = game->input.right;

    switch ((GameState)game->state) {
    case GAME_TITLE:
        Game_UpdateTitle(game, up_pressed, down_pressed);
        break;
    case GAME_PLAYING: {
        /* DC_KILL_AT: test hook that kills the player on a given frame. */
        if (game->kill_at > 0 && game->frame == (unsigned)game->kill_at &&
            game->player.hp > 0)
            game->player.hp = 0;
        /* Death animation / retry fade: the scene keeps running, but the
         * player has no control and no door may fire. */
        if (game->death_timer > 0 || game->restart_timer > 0) {
            Game_UpdateSimulation(game);
            Game_HandleDeath(game);
            break;
        }
        /* A room change owns the frame until its fade finishes: the console
         * runs the room loader inside the black stretch. */
        if (Game_UpdateTransition(game))
            break;
        bool has_exit = false;
        for (int i = 0; i < game->level.object_count; i++) {
            if (game->level.objects[i].type == LEVEL_OBJECT_EXIT) {
                has_exit = true;
                break;
            }
        }
        if (game->level.area_id == 0 && game->boss_intro == 0 &&
            game->shake_phase == 0 && getenv("DC_BOSS_INTRO") == NULL) {
            game->boss_intro = 1;
            game->boss_intro_timer = 0;
            game->shake_phase = 1;
        }
        if (game->campaign_mode && !has_exit &&
            game->level.gate_next_area < 0 && game->input.start_pressed) {
            Game_OpenOverworld(game);
            break;
        }
        if (game->input.special_pressed) {
            Game_TryTalk(game);
            if (game->state != GAME_PLAYING)
                break;
        }
        if (game->input.subscreen_pressed) {
            game->state = GAME_SUBSCREEN;
            game->state_timer = 0;
        } else if (game->input.pause_pressed) {
            game->state = GAME_PAUSED;
            game->menu_cursor = 0;
            game->state_timer = 0;
        } else {
            int area_before = game->level.area_id;
            Game_UpdateSimulation(game);
            Game_HandleDeath(game);
            if (game->state != GAME_PLAYING)
                break;
            if (game->objects.boss_defeated &&
                game->level.area_id == area_before) {
                game->objects.boss_defeated = false;
                game->player.max_hp = game->player.max_hp < 10
                                         ? game->player.max_hp + 1
                                         : game->player.max_hp;
                game->player.hp = game->player.max_hp;
                /* Keep control after a boss defeat only in the opt-in MVP
                 * flow: the player then walks through the gate and the area
                 * transitions (area 0 -> 34). Area 1 is the same kind of room:
                 * the cemetery boss opens the way to the slope, it does not end
                 * a stage or award a crest. Everywhere else the area still
                 * completes on the spot, which the campaign tests rely on. */
                bool keep_control =
                    game->campaign_mode && game->level.gate_next_area >= 0 &&
                    (getenv("DC_MVP_KEEP_CONTROL") != NULL ||
                     game->level.area_id == 1);
                if (!keep_control) {
                    game->campaign_mode = true;
                    Game_CompleteArea(game);
                }
            } else {
                Game_CheckTransitions(game);
            }
        }
        break;
    }
    case GAME_PAUSED: {
        /* RESUME / SAVE / MAP (or TITLE outside campaign mode). */
        const int kItems = 3;
        if (up_pressed && game->menu_cursor > 0)
            game->menu_cursor--;
        if (down_pressed && game->menu_cursor < kItems - 1)
            game->menu_cursor++;
        if (game->input.pause_pressed) {
            game->state = GAME_PLAYING;
            game->state_timer = 0;
            break;
        }
        if (!game->input.start_pressed)
            break;
        if (game->menu_cursor == 0) {
            game->state = GAME_PLAYING;
        } else if (game->menu_cursor == 1) {
            if (Game_SaveProgress(game))
                game->pause_flash = 90;
            break; /* stay on the pause menu */
        } else {
            game->menu_cursor = 0;
            if (game->campaign_mode) {
                Game_OpenOverworld(game);
            } else {
                game->state = GAME_TITLE;
            }
        }
        game->state_timer = 0;
        break;
    }
    case GAME_SUBSCREEN:
        Game_UpdateSubscreen(game, left_pressed, right_pressed, up_pressed,
                             down_pressed);
        break;
    case GAME_OVERWORLD:
        Game_UpdateOverworld(game);
        break;
    case GAME_CLEAR:
        if (game->input.start_pressed) {
            if (game->campaign_mode) {
                Game_OpenOverworld(game);
            } else {
                Game_Reset(game);
                game->state = GAME_PLAYING;
            }
        }
        break;
    case GAME_SHOP:
        Game_UpdateShop(game, up_pressed, down_pressed);
        break;
    case GAME_PASSWORD:
        Game_UpdatePassword(game, up_pressed, down_pressed, left_pressed,
                            right_pressed);
        break;
    case GAME_OPTIONS:
        Game_UpdateOptions(game);
        break;
    case GAME_OVER:
        if (game->input.start_pressed) {
            game->player.hp = game->player.max_hp;
            game->campaign_mode = true;
            Game_OpenOverworld(game);
        }
        break;
    case GAME_CONTINUE:
        Game_UpdateContinue(game, up_pressed, down_pressed);
        break;
    case GAME_PASSWORD_VIEW:
        /* The password leads back to the map (docs/TAKES.md §6.3). */
        if (game->input.start_pressed || game->input.pause_pressed)
            Game_OpenOverworld(game);
        break;
    case GAME_DIALOGUE: {
        int pages = game->script.page_count[game->dialogue_text];
        if (game->talk_len > 0) {
            /* Scripted conversation (city NPC): page the sequence, and show a
             * YES/NO choice on the question page. */
            bool last = game->talk_pos + 1 >= game->talk_len;
            if (last && game->talk_choice == 0 &&
                game->dialogue_text == game->town_question) {
                game->talk_choice = 1;
            }
            if (game->talk_choice == 1) {
                if (up_pressed || down_pressed)
                    game->talk_choice_sel = 1 - game->talk_choice_sel;
                if (game->input.start_pressed) {
                    if (game->talk_choice_sel == 0) {
                        int story[6] = {game->town_story[0],
                                        game->town_story[1],
                                        game->town_story[2],
                                        game->town_story[3], -1, -1};
                        for (int i = 0; i < 6; i++)
                            if (story[i] >= 0 &&
                                game->talk_len < 10) {
                                game->talk_seq[game->talk_len++] = story[i];
                            }
                        game->talk_choice = 0;
                        game->talk_pos++;
                        game->dialogue_text =
                            game->talk_seq[game->talk_pos];
                        game->dialogue_page = 0;
                    } else {
                        game->talk_len = 0;
                        game->state = game->dialogue_return;
                        game->state_timer = 0;
                    }
                }
                break;
            }
            if (game->input.start_pressed) {
                if (game->talk_pos + 1 < game->talk_len) {
                    game->talk_pos++;
                    game->dialogue_text = game->talk_seq[game->talk_pos];
                    game->dialogue_page = 0;
                } else {
                    game->talk_len = 0;
                    game->state = game->dialogue_return;
                    game->state_timer = 0;
                }
            }
            break;
        }
        if (game->input.start_pressed) {
            if (game->dialogue_page + 1 < pages) {
                game->dialogue_page++;
            } else {
                game->state = game->dialogue_return;
                game->state_timer = 0;
            }
        }
        break;
    }
    case GAME_ENDING: {
        const EndingData *ed = &game->assets.endings;
        int variant = game->ending_variant;
        int lines = ed->loaded ? ed->line_count[variant] : 0;
        int narr_pages = (lines + 1) / 2;
        if (game->input.start_pressed) {
            if (game->ending_phase == 0) {
                if (game->ending_page + 1 < narr_pages) {
                    game->ending_page++;
                } else if (ed->loaded && ed->epilogue[variant] >= 0) {
                    game->ending_phase = 1;
                    game->ending_page = 0;
                } else {
                    game->ending_phase = 1;
                    game->ending_page = 0;
                }
            } else {
                int epi = ed->loaded ? ed->epilogue[variant] : -1;
                int epi_pages = (epi >= 0 && game->script_ready)
                                    ? game->script.page_count[epi] : 0;
                if (game->ending_page + 1 < epi_pages) {
                    game->ending_page++;
                } else {
                    game->ending_page = 0;
                    game->ending_phase = 0;
                    game->state = GAME_TITLE;
                }
            }
        }
        break;
    }
    }
    if (game->pause_flash > 0)
        game->pause_flash--;
    if (game->state == GAME_PLAYING && game->intro_timer > 0)
        game->intro_timer--;
    Game_TraceFrame(game);
    Game_SyncMusic(game);
    Audio_Update();
}

static void DrawCentered(const char *text, int y, int size, Color color) {
    Vector2 measure = MeasureTextEx(GetFontDefault(), text, (float)size, 1.0f);
    DrawTextEx(GetFontDefault(), text,
               (Vector2){(256.0f - measure.x) * 0.5f, (float)y},
               (float)size, 1.0f, color);
}

static void DrawCenteredAt(const char *text, float cx, int y, int size,
                           Color color) {
    Vector2 measure = MeasureTextEx(GetFontDefault(), text, (float)size, 1.0f);
    DrawTextEx(GetFontDefault(), text,
               (Vector2){cx - measure.x * 0.5f, (float)y},
               (float)size, 1.0f, color);
}

static void DrawStageSelect(const Game *game) {
    int count = game->assets.stage_count;
    DrawRectangle(0, 0, 256, 224, (Color){6, 8, 14, 255});
    DrawCentered("STAGE SELECT", 14, 14, (Color){240, 220, 150, 255});
    int cleared = 0;
    for (int i = 0; i < count; i++)
        cleared += game->area_cleared[game->assets.stage_entries[i]] ? 1 : 0;
    DrawCentered(TextFormat("%d stages   %d cleared", count, cleared), 32, 9,
                 (Color){150, 200, 240, 255});
    int first = (game->stage_sel / 6) * 6;
    for (int i = 0; i < 6 && first + i < count; i++) {
        int idx = first + i;
        int area = game->assets.stage_entries[idx];
        bool sel = idx == game->stage_sel;
        int kind = Assets_RoomKind(&game->assets, area);
        bool done = game->area_cleared[area] != 0;
        const char *tag = done ? "DONE " : kind == 1 ? "STAGE"
                               : kind == 2 ? "BOSS " : "---- ";
        Color col = sel ? (Color){255, 255, 210, 255}
                        : done ? (Color){150, 230, 170, 255}
                               : (Color){200, 200, 210, 255};
        if (sel)
            DrawRectangle(20, 46 + i * 20, 216, 18,
                          (Color){50, 44, 70, 255});
        const char *nm = game->assets.room_names[area];
        if (nm[0]) {
            char pretty[40] = {0};
            int out = 0;
            for (int k = 0; nm[k] && out < (int)sizeof(pretty) - 1; k++) {
                char ch = nm[k];
                pretty[out++] =
                    ch == '-' ? ' ' : (char)toupper((unsigned char)ch);
            }
            DrawTextEx(GetFontDefault(),
                       TextFormat("%s %s", tag, pretty),
                       (Vector2){26, 49 + i * 20}, 12, 1.0f, col);
        } else {
            DrawTextEx(GetFontDefault(),
                       TextFormat("%s AREA %02d", tag, area),
                       (Vector2){26, 49 + i * 20}, 14, 1.0f, col);
        }
    }
    DrawCentered(TextFormat("PAGE %d / %d", game->stage_sel / 6 + 1,
                            (count + 5) / 6), 170, 9,
                 (Color){180, 180, 190, 255});
    DrawCentered("UP/DOWN SELECT   LEFT/RIGHT PAGE", 188, 9,
                 (Color){200, 220, 255, 255});
    DrawCentered("ENTER TRAVEL   X CLOSE", 204, 9,
                 (Color){200, 220, 255, 255});
}

/* Real Mode 7 world map (save11 capture): draw a 256x224 viewport centred on
 * the ship. Falls back to the procedural map when the asset is missing. */
static bool DrawWorldMapView(const Game *game) {
    if (!IsTextureValid(game->assets.world_map))
        return false;
    float wx = (game->overworld_x - 24.0f) / (232.0f - 24.0f) * 1024.0f;
    float wy = (game->overworld_y - 152.0f) / (208.0f - 152.0f) * 1024.0f;
    /* Mode 7 style affine view: the map rotates around the ship, which stays at
     * the screen centre (like the original's rotation). */
    const float zoom = game->overworld_zoom > 0.0f ? game->overworld_zoom : 1.0f;
    float angle = game->overworld_angle;
    while (angle < 0.0f)
        angle += 360.0f;
    while (angle >= 360.0f)
        angle -= 360.0f;
    /* Rotate a 256x224 source window around the ship so the destination stays a
     * screen-sized quad (raylib handles rotation around the pivot). */
    /* Full-texture draw under a camera transform: translate to the screen
     * centre, rotate, then place the ship's map pixel there. */
    Rectangle src = {0, 0, 1024.0f, 1024.0f};
    Rectangle dst = {0, 0, 1024.0f, 1024.0f};
    Camera2D cam = {0};
    cam.offset = (Vector2){128.0f, 112.0f};
    cam.target = (Vector2){wx, wy};
    cam.rotation = -angle;
    cam.zoom = zoom;
    BeginMode2D(cam);
    DrawTexturePro(game->assets.world_map, src, dst, (Vector2){0, 0}, 0.0f,
                   WHITE);
    /* Stage markers extracted from the map saves (species $94). */
    for (int i = 0; i < game->assets.map_marker_count; i++) {
        float mx = game->assets.map_markers[i][0];
        float my = game->assets.map_markers[i][1];
        float d = hypotf(mx - wx, my - wy);
        Color col = d < 40.0f ? (Color){255, 236, 140, 255}
                              : (Color){235, 235, 245, 255};
        DrawRectangle((int)(mx - 3), (int)(my - 3), 7, 7, col);
        DrawRectangleLines((int)(mx - 4), (int)(my - 4), 9, 9,
                           (Color){40, 40, 60, 255});
    }
    EndMode2D();
    /* Ship cursor at the centre: a small Firebrand marker with a glow. */
    DrawCircleV((Vector2){128.0f, 112.0f}, 7.0f,
                (Color){255, 220, 120, 60});
    if (IsTextureValid(game->assets.player)) {
        Rectangle psrc = {0, 0, (float)game->assets.player.width,
                          (float)game->assets.player.height};
        Rectangle pdst = {128.0f - 8.0f, 112.0f - 12.0f, 16.0f, 16.0f};
        DrawTexturePro(game->assets.player, psrc, pdst,
                       (Vector2){8.0f, 12.0f}, 0.0f, WHITE);
    } else {
        DrawCircleV((Vector2){128.0f, 112.0f}, 2.0f,
                    (Color){200, 60, 40, 255});
    }
    return true;
}

static void DrawOverworld(const Game *game) {
    if (DrawWorldMapView(game)) {
        if (game->talisman_toast > 0 && game->talisman_toast_index >= 0 &&
        game->talisman_toast_index < 5) {
        const char *name = kTalismanNames[game->talisman_toast_index];
        DrawText(TextFormat("%s TALISMAN", name), 60, 196, 10,
                 (Color){255, 236, 170, 255});
    }
    DrawText("OVERWORLD", 8, 6, 10, (Color){240, 232, 200, 255});
        DrawText(TextFormat("GOLD %d", game->player.gold), 190, 6, 10,
                 (Color){255, 224, 120, 255});
        DrawText("X STAGE SELECT   ENTER LAND   Q/E ZOOM", 8, 208, 8,
                 (Color){200, 220, 255, 255});
        return;
    }
    /* Mode 7 style pseudo-3D overworld: horizontal strips shrink toward the
     * horizon, with land/water/path bands and stage nodes. */
    ClearBackground((Color){6, 8, 14, 255});
    for (int y = 0; y < 224; y++) {
        float t = (float)y / 223.0f;
        float depth = 1.0f / (0.08f + t * 0.92f);
        float w = 256.0f * depth;
        float x = 128.0f - w * 0.5f;
        Color col;
        if (y < 70) {
            col = (Color){14 + (int)(t * 20), 10 + (int)(t * 16),
                          32 + (int)(t * 30), 255};
        } else {
            float band = sinf(t * 38.0f + game->overworld_angle * 0.05f);
            int g = 60 + (int)(band * 18.0f);
            col = (Color){18, g, 34, 255};
            if (fabsf(t - 0.62f) < 0.02f || fabsf(t - 0.78f) < 0.025f)
                col = (Color){86, 74, 44, 255};
        }
        DrawRectangle((int)x, y, (int)w + 1, 1, col);
    }

    /* World map nodes */
    static const struct { int node; float x; float y; const char *label; } kNodes[] = {
        {0, 40.0f, 168.0f, "COLOSSEUM"},
        {1, 96.0f, 176.0f, "GRAVEYARD"},
        {2, 144.0f, 184.0f, "CATACOMBS"},
        {3, 192.0f, 176.0f, "RUINS"},
        {4, 64.0f, 200.0f, "LAKE"},
        {5, 224.0f, 160.0f, "DEMON KEEP"},
    };
    for (int i = 0; i < 6; i++) {
        bool active = game->overworld_node == kNodes[i].node;
        Color col = active ? (Color){255, 220, 90, 255}
                           : (Color){150, 140, 120, 255};
        if (kNodes[i].node == 5 &&
            (game->stages_cleared & 0x0F) != 0x0F)
            col = (Color){120, 70, 90, 255};
        DrawCircle((int)kNodes[i].x, (int)kNodes[i].y, active ? 5 : 3, col);
        if (active)
            DrawText(kNodes[i].label,
                     (int)kNodes[i].x - MeasureText(kNodes[i].label, 10) / 2,
                     (int)kNodes[i].y + 8, 10, (Color){255, 240, 200, 255});
    }

    /* Firebrand marker */
    DrawCircle((int)game->overworld_x, (int)game->overworld_y, 4,
               (Color){240, 90, 60, 255});
    DrawTriangle((Vector2){game->overworld_x - 4, game->overworld_y - 8},
                 (Vector2){game->overworld_x + 4, game->overworld_y - 8},
                 (Vector2){game->overworld_x, game->overworld_y - 2},
                 (Color){255, 200, 120, 255});

    DrawRectangle(0, 0, 256, 18, (Color){0, 0, 0, 170});
    DrawText("OVERWORLD", 6, 5, 10, (Color){235, 225, 195, 255});
    DrawText(TextFormat("GOLD %d", game->player.gold), 170, 5, 10,
             (Color){235, 210, 120, 255});
    DrawCentered("ARROWS FLY   ENTER LAND   C SHOP", 208, 10,
                 (Color){200, 200, 200, 255});
}

/* Ending variant from collected power crests (mask bits 1..5):
 * 0 -> bad, 1-2 -> normal, 3-4 -> good, 5 -> true. */
/* Completion percentage used by the endings, following the retail rules:
 * 5 crests + 4 Fire-Crest shots + 5 talismans + 5 urns + 5 vellums + the life
 * extensions (16 in the original; our max HP 5..10 stands in for them). */
static int Game_CompletionPercent(const Game *game) {
    int have = 0, total = 0;
    for (int i = 0; i < 5; i++) {
        total++;
        if (game->player.crests_mask & (1u << i))
            have++;
    }
    total += 4;
    have += game->player.fire_element > 4 ? 4 : game->player.fire_element;
    for (int i = 0; i < 5; i++) {
        total++;
        if (game->player.talisman_mask & (1u << i))
            have++;
    }
    total += 5;
    have += game->player.potions > 5 ? 5 : game->player.potions;
    total += 5;
    have += game->player.scrolls > 5 ? 5 : game->player.scrolls;
    total += 5;
    int life = game->player.max_hp - 5;
    have += life > 5 ? 5 : (life > 0 ? life : 0);
    return total > 0 ? have * 100 / total : 0;
}

/* Bad under 50% completion, normal up to 99%, good at 100% (the true ending
 * also needs the Dark Demon, which is not implemented yet). */
static int Game_EndingVariant(const Game *game) {
    int pct = Game_CompletionPercent(game);
    if (pct >= 100)
        return 2;
    if (pct >= 50)
        return 1;
    return 0;
}

static void Game_StartEnding(Game *game) {
    game->ending_variant = Game_EndingVariant(game);
    const char *env = getenv("DC_ENDING");
    if (env && *env) {
        if (strcmp(env, "bad") == 0)
            game->ending_variant = 0;
        else if (strcmp(env, "normal") == 0)
            game->ending_variant = 1;
        else if (strcmp(env, "good") == 0)
            game->ending_variant = 2;
        else if (strcmp(env, "true") == 0)
            game->ending_variant = 3;
    }
    game->ending_page = 0;
    game->ending_phase = 0;
    game->state = GAME_ENDING;
    game->state_timer = 0;
}

/* Brief area-entry banner: fades in, holds, fades out. */
static void DrawAreaBanner(const Game *game) {
    if (game->intro_timer <= 0 || game->state != GAME_PLAYING)
        return;
    int t = game->intro_timer;
    float alpha = 1.0f;
    if (t > 90)
        alpha = (float)(110 - t) / 20.0f;
    else if (t < 25)
        alpha = (float)t / 25.0f;
    if (alpha < 0.0f)
        alpha = 0.0f;
    if (alpha > 1.0f)
        alpha = 1.0f;
    unsigned char a = (unsigned char)(alpha * 235.0f);
    int kind = Assets_RoomKind(&game->assets, game->level.area_id);
    const char *tag = kind == 1 ? "STAGE" : kind == 2 ? "BOSS STAGE" : "AREA";
    const char *name = game->assets.room_names[game->level.area_id];
    char pretty[48] = {0};
    if (name[0]) {
        /* "dark-forest-thorn-grove" -> "DARK FOREST THORN GROVE" */
        int out = 0;
        for (int i = 0; name[i] && out < (int)sizeof(pretty) - 1; i++) {
            char ch = name[i];
            pretty[out++] = ch == '-' ? ' ' : (char)toupper((unsigned char)ch);
        }
        pretty[out] = 0;
    }
    DrawRectangle(40, 30, 176, 36,
                  (Color){8, 8, 16, (unsigned char)(a * 0.85f)});
    DrawRectangleLines(40, 30, 176, 36, (Color){200, 176, 110, a});
    if (pretty[0])
        DrawCentered(pretty, 34, 11, (Color){240, 232, 200, a});
    else
        DrawCentered(TextFormat("%s %02d", tag, game->level.area_id), 34, 12,
                     (Color){240, 232, 200, a});
    /* The world dimensions are a development aid, not a player-facing caption:
     * they used to be drawn unconditionally, so every room's banner read
     * "STAGE 01 WORLD 768x256". Keep them behind an explicit opt-in. */
    if (getenv("DC_DEBUG_BANNER"))
        DrawCentered(TextFormat("%s %02d   WORLD %dx%d", tag,
                                game->level.area_id, game->level.world_w,
                                game->level.world_h), 52, 9,
                     (Color){170, 180, 200, a});
}

static void DrawSubscreen(const Game *game) {
    const Player *p = &game->player;
    DrawRectangle(0, 0, 256, 224, (Color){8, 8, 18, 235});
    DrawText("CREST / ITEM SUBSCREEN", 12, 8, 10,
             (Color){230, 210, 150, 255});
    DrawText(TextFormat("FORM: %s", Player_FormName(p->crest_form)), 12, 28,
             10, (Color){200, 230, 255, 255});
    DrawText(TextFormat("FIRE: %s", kFireNames[p->fire_element]), 12, 44, 10,
             (Color){255, 180, 120, 255});
    DrawText(TextFormat("TALISMAN: %s", kTalismanNames[p->active_talisman]),
             12, 60, 10, (Color){200, 255, 200, 255});
    DrawText(TextFormat("HP %d/%d", p->hp, p->max_hp), 12, 80, 10,
             (Color){240, 120, 140, 255});
    DrawText(TextFormat("URNS %d/5   SPELLS %d/5   GOLD %d", p->potions,
                        p->scrolls, p->gold), 12, 96, 10,
             (Color){240, 220, 140, 255});
    DrawText("LEFT/RIGHT FORM  A FIRE  Y TALISMAN", 12, 128, 10,
             (Color){190, 190, 190, 255});
    DrawText("Z USE URN  Q CAST SPELL  TAB CLOSE", 12, 144, 10,
             (Color){190, 190, 190, 255});
    DrawText("OWNED CRESTS:", 12, 172, 10, (Color){220, 220, 220, 255});
    for (int i = 0; i < CREST_COUNT; i++) {
        Color c = (p->crests_mask & (1u << i)) ? (Color){230, 220, 160, 255}
                                               : (Color){70, 70, 80, 255};
        DrawRectangle(14 + i * 24, 188, 18, 10, c);
        if (i == p->crest_form)
            DrawRectangleLines(13 + i * 24, 187, 20, 12,
                               (Color){255, 255, 255, 255});
    }
}

static void DrawOverlay(const Game *game) {
    static const char *const kMenu[] = {
        "NEW GAME", "OVERWORLD MAP", "PASSWORD", "OPTIONS"
    };
    static const char *const kMenuWithSave[] = {
        "CONTINUE", "NEW GAME", "OVERWORLD MAP", "PASSWORD", "OPTIONS"
    };
    if (game->attract && game->state == GAME_PLAYING) {
        DrawRectangle(0, 216, 256, 12, (Color){0, 0, 0, 170});
        DrawCentered("DEMO   PRESS START", 217, 9,
                     (Color){230, 220, 180, 255});
    }
    if (game->state == GAME_TITLE) {
        DrawRectangle(0, 0, 256, 224, (Color){0, 0, 0, 185});
        DrawCentered("DEMON'S CREST", 34, 24, (Color){238, 232, 214, 255});
        DrawCentered("NATIVE FAN PORT", 62, 10, (Color){196, 168, 92, 255});
        const char *const *menu = game->has_save ? kMenuWithSave : kMenu;
        const int count = game->has_save ? 5 : 4;
        for (int i = 0; i < count; i++) {
            Color col = game->menu_cursor == i ? (Color){255, 230, 120, 255}
                                               : (Color){190, 190, 190, 255};
            DrawCentered(menu[i], 92 + i * 16, 10, col);
        }
        DrawCentered("ARROWS SELECT   ENTER CONFIRM", 186, 10,
                     (Color){150, 150, 150, 255});
        DrawCentered("F1 COLLISION   ESC PAUSE", 200, 10,
                     (Color){150, 150, 150, 255});
    } else if (game->state == GAME_PAUSED) {
        DrawRectangle(0, 0, 256, 224, (Color){0, 0, 0, 150});
        DrawCentered("PAUSED", 84, 24, (Color){238, 232, 214, 255});
        Color c0 = game->menu_cursor == 0 ? (Color){255, 230, 120, 255}
                                          : (Color){200, 200, 200, 255};
        Color c1 = game->menu_cursor == 1 ? (Color){255, 230, 120, 255}
                                          : (Color){200, 200, 200, 255};
        Color c2 = game->menu_cursor == 2 ? (Color){255, 230, 120, 255}
                                          : (Color){200, 200, 200, 255};
        DrawCentered("RESUME", 124, 10, c0);
        DrawCentered("SAVE", 140, 10, c1);
        DrawCentered(game->campaign_mode ? "RETURN TO MAP" : "QUIT TO TITLE",
                     156, 10, c2);
        if (game->pause_flash > 0)
            DrawCentered("SAVED", 184, 10, (Color){150, 230, 170, 255});
    } else if (game->state == GAME_CONTINUE) {
        /* The death hub over the frozen scene (docs/TAKES.md §6.3). */
        static const char *const kContinue[] = {"RETRY", "SELECT A STAGE",
                                                "END"};
        DrawRectangle(0, 0, 256, 224, (Color){0, 0, 0, 160});
        for (int i = 0; i < 3; i++) {
            bool selected = game->continue_cursor == i;
            Color col = selected ? (Color){255, 230, 120, 255}
                                 : (Color){200, 200, 200, 255};
            DrawCentered(TextFormat("%s%s", selected ? "> " : "  ",
                                    kContinue[i]),
                         92 + i * 18, 12, col);
        }
    } else if (game->state == GAME_PASSWORD_VIEW) {
        DrawRectangle(0, 0, 256, 224, (Color){6, 10, 16, 245});
        DrawCentered("PASS WORD", 22, 20, (Color){230, 220, 170, 255});
        const int cell = 20;
        const int x0 = 128 - (4 * cell) / 2;
        const int y0 = 64;
        for (int i = 0; i < DC_PASSWORD_VIEW_CELLS; i++) {
            int cx = x0 + (i % 4) * cell;
            int cy = y0 + (i / 4) * cell;
            DrawRectangleLines(cx, cy, cell - 2, cell - 2,
                               (Color){60, 90, 120, 255});
            char ch[2] = {game->password_grid[i]
                              ? game->password_grid[i] : 'B', 0};
            DrawCenteredAt(ch, (float)cx + (cell - 2) * 0.5f, cy + 3, 14,
                           (Color){150, 230, 255, 255});
        }
        if ((game->state_timer / 30) % 2 == 0)
            DrawCentered("PUSH START BUTTON", 176, 10,
                         (Color){255, 255, 255, 255});
        if (getenv("DC_PASSWORD_NATIVE_HUD"))
            DrawCentered(TextFormat("NATIVE %s", game->password_code), 196, 8,
                         (Color){170, 170, 185, 255});
    } else if (game->state == GAME_CLEAR) {
        DrawRectangle(0, 0, 256, 224, (Color){0, 0, 0, 185});
        DrawCentered("AREA CLEAR", 62, 24, (Color){238, 232, 214, 255});
        DrawCentered(TextFormat("AREA %d CONQUERED", game->level.area_id), 96,
                     10, (Color){196, 168, 92, 255});
        DrawCentered(TextFormat("PASSWORD %s", game->password_code), 114, 10,
                     (Color){160, 220, 255, 255});
        DrawCentered(TextFormat("MAX HP %d   GOLD %d", game->player.max_hp,
                                game->player.gold), 132, 10,
                     (Color){240, 220, 140, 255});
        if ((game->state_timer / 30) % 2 == 0)
            DrawCentered("PRESS ENTER FOR OVERWORLD", 160, 10,
                         (Color){255, 255, 255, 255});
    } else if (game->state == GAME_SUBSCREEN) {
        DrawSubscreen(game);
    } else if (game->state == GAME_SHOP) {
        DrawRectangle(0, 0, 256, 224, (Color){10, 8, 14, 240});
        if (game->level.area_id == 98 && game->player.scrolls <= 0) {
            if (game->shop_need_vellum >= 0)
                Text_DrawPage(&game->assets, &game->script,
                              game->shop_need_vellum, 0, 16, 40, 220,
                              (Color){240, 236, 220, 255});
            DrawCentered("ESC LEAVE", 208, 10, (Color){170, 170, 170, 255});
            return;
        }
        int y = 10;
        if (game->shop_welcome >= 0)
            y += Text_DrawPage(&game->assets, &game->script,
                               game->shop_welcome, 0, 16, y, 220,
                               (Color){240, 236, 220, 255});
        y += 6;
        const int stock = ShopStockForArea(game);
        for (int i = 0; i <= stock; i++) {
            bool sel = game->shop_sel == i;
            Color col = sel ? (Color){255, 236, 140, 255}
                            : (Color){190, 190, 200, 255};
            const char *label = i < stock ? kShopStock[i].name : "EXIT";
            DrawText(TextFormat("%s %s", sel ? ">" : " ", label), 44,
                     y + i * 12, 10, col);
            if (i < stock)
                DrawText(TextFormat("%4d GP", kShopStock[i].price), 152,
                         y + i * 12, 10, col);
        }
        DrawText(TextFormat("GOLD %d", game->player.gold), 152, 190, 10,
                 (Color){255, 224, 120, 255});
        DrawText(TextFormat("URNS %d/5", game->player.potions), 44, 190, 10,
                 (Color){200, 220, 255, 255});
        if (game->shop_timer > 0 && game->shop_message >= 0)
            Text_DrawPage(&game->assets, &game->script, game->shop_message, 0,
                          16, 170, 220, (Color){255, 210, 160, 255});
        DrawCentered("UP/DOWN  ENTER BUY  ESC LEAVE", 212, 8,
                     (Color){170, 170, 170, 255});
    } else if (game->state == GAME_PASSWORD) {
        DrawRectangle(0, 0, 256, 224, (Color){6, 10, 16, 240});
        DrawCentered("PASSWORD", 40, 20, (Color){230, 220, 170, 255});
        int cw = 16;
        int start = 128 - (DC_PASSWORD_LEN * cw) / 2;
        for (int i = 0; i < DC_PASSWORD_LEN; i++) {
            char ch = game->password_entry[i];
            if (!ch)
                ch = '-';
            bool active = (i == game->password_pos);
            Color col = active ? (Color){255, 230, 120, 255}
                               : (Color){150, 230, 255, 255};
            DrawText(TextFormat("%c", ch), start + i * cw + 5, 86, 20, col);
            if (active)
                DrawRectangleLines(start + i * cw, 84, cw, 26, col);
        }
        if (game->password_status < 0)
            DrawCentered("INVALID CODE", 124, 12, (Color){255, 120, 120, 255});
        else if (game->password_status > 0)
            DrawCentered("PROGRESS RESTORED", 124, 12,
                         (Color){150, 255, 170, 255});
        DrawCentered("UP/DOWN LETTER   LEFT/RIGHT SELECT", 160, 10,
                     (Color){190, 190, 190, 255});
        DrawCentered("ENTER APPLY   ESC BACK", 178, 10,
                     (Color){190, 190, 190, 255});
    } else if (game->state == GAME_OPTIONS) {
        DrawRectangle(0, 0, 256, 224, (Color){8, 8, 14, 240});
        DrawCentered("OPTIONS", 40, 20, (Color){230, 220, 170, 255});
        DrawCentered(TextFormat("VOLUME %d%%", (int)(Audio_GetVolume() * 100)),
                     96, 12, (Color){200, 230, 255, 255});
        DrawCentered("LEFT/RIGHT ADJUST", 120, 10,
                     (Color){190, 190, 190, 255});
        DrawCentered("ENTER / ESC BACK", 168, 10,
                     (Color){190, 190, 190, 255});
    } else if (game->state == GAME_OVER) {
        DrawRectangle(0, 0, 256, 224, (Color){16, 0, 4, 230});
        DrawCentered("GAME OVER", 76, 24, (Color){240, 90, 90, 255});
        DrawCentered("THE DEMON'S CREST IS LOST", 108, 10,
                     (Color){200, 160, 160, 255});
        if ((game->state_timer / 30) % 2 == 0)
            DrawCentered("PRESS ENTER TO CONTINUE", 148, 10,
                         (Color){255, 255, 255, 255});
    } else if (game->state == GAME_DIALOGUE) {
        DrawRectangle(0, 0, 256, 224, (Color){4, 6, 12, 235});
        if (game->dialogue_text >= 0)
            Text_DrawPage(&game->assets, &game->script, game->dialogue_text,
                          game->dialogue_page, 16, 64, 224,
                          (Color){240, 236, 220, 255});
        if (game->talk_choice == 1) {
            Color cy = game->talk_choice_sel == 0 ? (Color){255, 236, 140, 255}
                                                  : (Color){150, 150, 160, 255};
            Color cn = game->talk_choice_sel == 1 ? (Color){255, 236, 140, 255}
                                                  : (Color){150, 150, 160, 255};
            Text_DrawString(&game->assets, "YES", 96, 150, cy);
            Text_DrawString(&game->assets, "NO", 160, 150, cn);
        }
        if ((game->state_timer / 30) % 2 == 0)
            DrawCentered("PRESS ENTER", 196, 10,
                         (Color){200, 200, 200, 255});
    } else if (game->state == GAME_ENDING) {
        /* The reference endings play over the world; use the captured Mode 7
         * map as a dimmed backdrop instead of flat black. */
        if (IsTextureValid(game->assets.world_map)) {
            Rectangle src = {0, 0, 1024.0f, 1024.0f};
            Rectangle dst = {0, 0, 256.0f, 224.0f};
            DrawTexturePro(game->assets.world_map, src, dst, (Vector2){0, 0},
                           0.0f, (Color){110, 110, 150, 255});
        }
        DrawRectangle(0, 0, 256, 224, (Color){4, 6, 12, 205});
        const EndingData *ed = &game->assets.endings;
        int variant = game->ending_variant;
        if (!ed->loaded) {
            DrawCentered("THE DEMON'S CREST", 96, 16,
                         (Color){240, 220, 150, 255});
        } else if (game->ending_phase == 0) {
            int first = game->ending_page * 2;
            DrawCentered(ed->title[variant], 24, 14,
                         (Color){240, 220, 150, 255});
            for (int i = 0; i < 2; i++) {
                int idx = first + i;
                if (idx >= ed->line_count[variant])
                    break;
                Text_DrawString(&game->assets, ed->lines[variant][idx], 12,
                                84 + i * 22, (Color){240, 236, 220, 255});
            }
        } else {
            int epi = ed->epilogue[variant];
            if (epi >= 0 && game->script_ready) {
                Text_DrawPage(&game->assets, &game->script, epi,
                              game->ending_page, 16, 56, 224,
                              (Color){240, 236, 220, 255});
            } else {
                DrawCentered("THE END", 96, 20,
                             (Color){240, 220, 150, 255});
            }
        }
        if ((game->state_timer / 30) % 2 == 0)
            DrawCentered("PRESS ENTER", 206, 10, (Color){200, 200, 200, 255});
    }
}

void Game_Render(Game *game) {
    BeginTextureMode(game->target);
    /* The first Somulo fight hides the HUD on purpose: the player learns
     * their state only in the next room. */
    bool cinematic = game->level.area_id == 0;
    bool show_hud = !cinematic &&
                    (game->state == GAME_PLAYING ||
                    game->state == GAME_PAUSED ||
                    game->state == GAME_SUBSCREEN);
    if (game->state == GAME_OVERWORLD) {
        DrawOverworld(game);
        if (game->stage_select)
            DrawStageSelect(game);
    } else {
        Render_Game(&game->assets, &game->level, &game->camera,
                    &game->player, &game->projectiles, &game->objects,
                    show_hud, game->input.debug_collision);
        DrawAreaBanner(game);
    }
    if (game->state != GAME_PLAYING)
        DrawOverlay(game);
    if (game->dialogue_demo && game->script_ready && game->script.count > 0) {
        /* Dev hook (`DC_DIALOGUE=1`): show the extracted ROM script with the
         * baked BG3 font, advancing a page every two seconds. The real
         * dialogue state will drive this from story events instead. */
        int pages = game->script.page_count[0];
        int page = pages > 0 ? (game->state_timer / 120) % pages : 0;
        int height = 0;
        if (getenv("DC_FONT_TEST")) {
            Text_DrawString(&game->assets, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", 8, 120,
                            (Color){240, 236, 220, 255});
            Text_DrawString(&game->assets, "abcdefghijklmnopqrstuvwxyz", 8, 130,
                            (Color){240, 236, 220, 255});
            Text_DrawString(&game->assets, "0123456789 .,:;!?-'", 8, 140,
                            (Color){240, 236, 220, 255});
            height = 24;
        } else {
            height = Text_DrawPage(&game->assets, &game->script, 0, page, 16,
                                   150, 216, (Color){240, 236, 220, 255});
        }
        if (height > 0)
            Text_DrawString(&game->assets, "ENTER NEXT", 16,
                            150 + height + 6, (Color){170, 170, 185, 255});
    }
    Render_DrawFade();
    EndTextureMode();
}

void Game_Shutdown(Game *game) {
    if (game->ready && game->campaign_mode)
        (void)Game_SaveProgress(game);
    Audio_Shutdown();
    if (game->trace)
        fclose(game->trace);
    if (game->projectile_trace)
        fclose(game->projectile_trace);
    if (game->object_trace)
        fclose(game->object_trace);
    if (IsRenderTextureValid(game->target))
        UnloadRenderTexture(game->target);
    Level_Unload(&game->level);
    Assets_Unload(&game->assets);
    memset(game, 0, sizeof(*game));
}
