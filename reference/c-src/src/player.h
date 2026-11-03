#ifndef DC_PLAYER_H
#define DC_PLAYER_H

#include <stdbool.h>
#include <stdint.h>

#include "anim.h"
#include "level.h"
#include "input.h"

typedef enum PlayerState {
    PLAYER_IDLE,
    PLAYER_WALK,
    PLAYER_JUMP,
    PLAYER_HOVER,
    PLAYER_FLY,
    PLAYER_LAND,
    PLAYER_HURT,
    PLAYER_DEAD,
    PLAYER_WALL_CLING,
    PLAYER_HEADBUTT
} PlayerState;

typedef enum CrestForm {
    CREST_BASE = 0,     /* Normal Gargoyle (Fire Crest variants) */
    CREST_EARTH = 1,    /* Earth Gargoyle (shoulder tackle, ground-bound) */
    CREST_AIR = 2,      /* Aerial Gargoyle (unlimited free flight) */
    CREST_WATER = 3,    /* Water Gargoyle (free underwater swim) */
    CREST_TIME = 4,     /* Legendary Gargoyle (halved damage, heavy shot) */
    CREST_ULTIMATE = 5, /* Ultimate Gargoyle (all abilities + charged shot) */
    CREST_COUNT = 6
} CrestForm;

typedef struct Player {
    /* Public pixel-space position/velocity used by the camera, renderer and
     * trace output. The authoritative movement state is 8.8 fixed point. */
    float x;          /* feet centre, world pixels */
    float y;
    float vx;
    float vy;

    int32_t x_fx;     /* world X, 8.8 fixed ($1030) */
    int32_t y_fx;     /* world Y, 8.8 fixed ($1033) */
    int32_t vy_fx;    /* vertical velocity, native sign (down = +) */
    int32_t walk_speed_fx; /* $1020, 8.8 fixed */

    bool on_ground;
    bool on_slope;    /* $1070 terrain flag ($80:DF82: attr & 0xE0 == 0x80) */
    bool underwater;  /* $1045 water flag ($80:94AB: attr & 0xE0 == 0x60) */
    bool fly_enabled; /* debug/crest flight, off for base Gargoyle */
    int facing;       /* -1 left, +1 right */
    int prev_dir;     /* $0072, previous direction input */
    int jump_sub;     /* $1006: 0 takeoff, 2 launch, 4 flight */
    PlayerState state;
    float anim_time;

    int crest_form;        /* $1002: current CrestForm (0..5) */
    uint8_t crests_mask;   /* unlocked crests bitmask */
    int fire_element;      /* 0 Fireball, 1 Buster, 2 Tornado, 3 Claw, 4 Demon */
    int active_talisman;   /* 0 Crown, 1 Skull, 2 Armor, 3 Fang, 4 Hand */
    uint8_t talisman_mask; /* owned talismans bitmask */
    int potions;           /* filled healing urns (0..5) */
    int scrolls;           /* filled spell vellum (0..5) */
    int gold;              /* currency collected */

    int wall_cling_dir; /* -1 left wall, +1 right wall, 0 none */
    int dash_timer;     /* Earth/Ultimate shoulder dash or headbutt frames */

    int special_timer; /* frames left in the A/Talisman animation */
    int shot_timer;    /* frames left in the Y/Fireball animation */
    int land_timer;    /* frames left in the landing animation */
    bool shot_fired;   /* one-frame event consumed by the projectile pool */

    int hp;            /* $1062 */
    int max_hp;        /* $1E50 */
    int invuln_timer;  /* contact-damage immunity */
    int knockback_timer;
    int knockback_dir;
    bool jump_started; /* one-frame audio/event flags */
    bool landed_event;
    bool hurt_event;
    bool block_broken_event;

    int anim_clip;    /* current AnimClipId, -1 before the first frame */
    int anim_step;
    int anim_timer;
} Player;

void Player_Init(Player *player, const Level *level);
void Player_Update(Player *player, Level *level, const Input *input);
void Player_Animate(Player *player, const PlayerAnim *anim);
void Player_CycleForm(Player *player, int delta);
const char *Player_FormName(int form);

#endif
