#ifndef DC_OBJECT_H
#define DC_OBJECT_H

#include <stdbool.h>
#include <stdint.h>

#include "level.h"
#include "player.h"
#include "projectile.h"

#define OBJECT_POOL_SIZE 26

#define OBJECT_EVENT_PICKUP 0x01
#define OBJECT_EVENT_BREAK 0x02
#define OBJECT_EVENT_ENEMY_HIT 0x04
#define OBJECT_EVENT_BOSS_DEFEATED 0x08
#define OBJECT_EVENT_CREST_PICKUP 0x10
#define OBJECT_EVENT_FIRE_PIECE 0x20
#define OBJECT_EVENT_TALISMAN   0x40

typedef enum ObjectType {
    OBJECT_NONE = 0,
    OBJECT_URN = 1,
    OBJECT_PICKUP = 2,
    OBJECT_ENEMY = 3,
    OBJECT_PLATFORM = 4,
    OBJECT_CREST_ITEM = 5,
    OBJECT_BOSS = 6,
    OBJECT_ENEMY_SHOT = 7, /* hostile projectile (species $67) */
    OBJECT_NPC = 8,       /* talkable city NPC (species $96) */
    OBJECT_TALISMAN = 9   /* floating talisman pickup; species = index */
} ObjectType;

typedef struct Object {
    bool active;
    ObjectType type;
    int species;
    int flags;
    int32_t x_fx, y_fx;
    int32_t origin_x_fx, origin_y_fx;
    int32_t vx_fx, vy_fx;
    int32_t bounce_fx; /* $39: remaining bounce velocity for pickups */
    int state;
    int substate; /* $06: per-species state machine substate */
    int phase;    /* countdown for the current substate ($3B) */
    int hops;     /* $38: hop counter inside a burst */
    int burst;    /* $3A: animation step inside a burst */
    int spit_cd;    /* $3C: frames until the next child in a volley */
    int spit_left;  /* $3D: children left in the volley */
    int saved_state;/* $42: state a finished action returns to */
    int hide_timer; /* $43: cooldown before the next decision */
    int target_x_fx;/* $3F: x the leap was aimed at */
    int landings;   /* $41: ground contacts of the leap */
    int hit_flash; /* frames of white flash after taking a hit */
    int facing;   /* $09: 1 right, -1 left */
    int hp;
    int max_hp;
    int timer;
} Object;

typedef struct ObjectPool {
    Object slots[OBJECT_POOL_SIZE];
    int events; /* one-frame sound/effect flags */
    bool boss_alive;
    bool boss_defeated;
    bool boss_present; /* an OBJECT_BOSS was spawned in this room */
    int boss_phase;    /* 1 until a two-form boss transforms */
    int last_fire_piece;
    int last_talisman; /* 1..4 = Buster/Tornado/Claw/Demon Fire */
} ObjectPool;

void Objects_Init(ObjectPool *pool, const Level *level);
void Objects_Update(ObjectPool *pool, const Level *level, Player *player);
void Objects_CheckProjectiles(ObjectPool *pool, ProjectilePool *projectiles);

#endif
