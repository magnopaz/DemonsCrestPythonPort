#include "object.h"
#include <stdio.h>

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define FX_ONE 256
#define HEART_POPUP_FX 0x0400 /* $85:C1D1 initial upward velocity 4.0 */
#define HEART_GRAVITY_FX 0x0040 /* $85:C1D1 gravity 0.25 */
#define HEART_BOUNCE_FX 0x0400  /* $85:C1D1 bounce decay 4.0 -> 3.0 ... */
#define HEART_BOUNCE_STEP 0x0100

#define URN_HALF 8.0f
#define HEART_HALF 8.0f

static Object *Alloc(ObjectPool *pool) {
    for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
        if (!pool->slots[i].active)
            return &pool->slots[i];
    }
    return NULL;
}

static void SpawnUrn(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_URN;
    o->species = src->species;
    o->flags = src->flags;
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->hp = 1;
    o->max_hp = 1;
}

static void SpawnPickup(ObjectPool *pool, float x, float bottom_y) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_PICKUP;
    o->x_fx = (int32_t)lroundf(x * FX_ONE);
    o->y_fx = (int32_t)lroundf(bottom_y * FX_ONE);
    o->vy_fx = -HEART_POPUP_FX; /* object convention: positive is up */
    o->bounce_fx = HEART_BOUNCE_FX;
    o->state = 0;
}

static void SpawnEnemy(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_ENEMY;
    o->species = src->species;
    o->flags = src->flags;
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->hp = (src->species == 0x26) ? 3 : 2;
    o->max_hp = o->hp;
    if (getenv("DC_BOSS_HURT") != NULL)  /* test hook: show the damage tint */
        o->hp = o->max_hp > 1 ? o->max_hp / 2 : 1;
    o->state = 0; /* emerge / init */
    o->timer = 24;
    o->vx_fx = (src->flags & 1) ? 0x0080 : -0x0080;
    o->facing = (o->vx_fx >= 0) ? 1 : -1;
}

/* Hostile projectile spawned by the species $67 ghoul ($82877B in the
 * original): the child object runs its own species handler, so the native port
 * models it as a straight-flying object with the captured $67 sprite. */
static void SpawnEnemyShot(ObjectPool *pool, float x, float y, int32_t vx,
                           int32_t vy) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_ENEMY_SHOT;
    o->species = 0x67;
    o->x_fx = (int32_t)lroundf(x * FX_ONE);
    o->y_fx = (int32_t)lroundf(y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->vx_fx = vx;
    o->vy_fx = vy;
    o->hp = 1;
}

/* Somulo's fireball: a normal hostile shot, but marked so that hitting the
 * ground spawns a firewall (its `substate` is used as a flag). */
static void SpawnBossFireball(ObjectPool *pool, float x, float y, int32_t vx,
                              int32_t vy) {
    SpawnEnemyShot(pool, x, y, vx, vy);
    for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
        Object *o = &pool->slots[i];
        if (o->active && o->type == OBJECT_ENEMY_SHOT &&
            o->x_fx == (int32_t)lroundf(x * FX_ONE) &&
            o->y_fx == (int32_t)lroundf(y * FX_ONE)) {
            o->substate = 1;
            o->species = 0x34; /* the fireball object in Area 0 */
            break;
        }
    }
}

/* Firewall: three short-lived flames standing on the ground where a fireball
 * landed. They are enemy shots flagged with state 1 so the update path keeps
 * them in place. */
static void SpawnFirewall(ObjectPool *pool, float x, float y) {
    for (int k = -1; k <= 1; k++) {
        Object *o = Alloc(pool);
        if (!o)
            return;
        memset(o, 0, sizeof(*o));
        o->active = true;
        o->type = OBJECT_ENEMY_SHOT;
        o->species = 0x34;
        o->state = 1;
        o->x_fx = (int32_t)lroundf((x + (float)k * 9.0f) * FX_ONE);
        o->y_fx = (int32_t)lroundf(y * FX_ONE);
        o->origin_x_fx = o->x_fx;
        o->origin_y_fx = o->y_fx;
        o->hp = 1;
    }
}

static void SpawnPlatform(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_PLATFORM;
    o->species = src->species;
    o->flags = src->flags;
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->vx_fx = 0x0080;
}

static void SpawnCrestItem(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_CREST_ITEM;
    o->species = src->species;
    o->flags = src->flags;
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
}

/* Talismans (crown/skull/armor/fang/hand) float in place until collected. */
static void SpawnTalisman(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_TALISMAN;
    o->species = src->flags >= 0 && src->flags < 5 ? src->flags : 3;
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
}

static void SpawnBoss(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_BOSS;
    pool->boss_present = true;
    o->species = src->species;
    o->flags = src->flags;
    /* Test hook: boot the second Phalanx form directly so its art and AI can
     * be smoke-tested without scripting the first form's death. */
    const char *phase_env = getenv("DC_BOSS_PHASE");
    bool forced_second =
        phase_env && *phase_env && atoi(phase_env) == 2 && o->species == 0x86;
    if (forced_second) {
        o->species = 0x8D;
        o->substate = 1;
    }
    float bx = src->x;
    float by = src->y;
    if (src->species == 0x33 && bx < 120.0f) {
        bx = 220.0f;
        by = 160.0f;
    } else if (src->species == 0xA5 && by < 64.0f) {
        by = 140.0f;
    }
    /* The ROM stores a boss's y at the centre of its hitbox, while the port
     * anchors sprites at their feet. Somulo's box is 92 px tall (80x92), so his
     * feet sit 23 px below the stored value -- exactly the colosseum floor
     * (170 + 23 = 193 against a 192 floor line). Without this he stands in the
     * air, which is how the fight shipped until now. */
    if (src->species == 0x33)
        by += 23.0f;
    /* Test hook: place the boss where a grounded demo can reach it. */
    const char *bx_env = getenv("DC_BOSS_X");
    const char *by_env = getenv("DC_BOSS_Y");
    if (bx_env && *bx_env)
        bx = (float)atof(bx_env);
    if (by_env && *by_env)
        by = (float)atof(by_env);
    o->x_fx = (int32_t)lroundf(bx * FX_ONE);
    o->y_fx = (int32_t)lroundf(by * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->hp = (src->species == 0x33) ? 6 : (forced_second ? 10 : 8);
    o->facing = 1; /* sheets face right; the AI updates this as it turns */
    const char *hp_env = getenv("DC_BOSS_HP");
    if (hp_env && *hp_env)
        o->hp = atoi(hp_env);
    o->max_hp = o->hp;
    o->state = 0;
    pool->boss_alive = true;
    if (getenv("DC_BOSS_DEFEATED") != NULL) {
        /* Test hook: the boss starts already defeated so the clear flow can be
         * exercised without fighting. Set the full defeat state, not just an
         * inactive slot. */
        o->active = false;
        o->hp = 0;
        pool->boss_alive = false;
        pool->boss_defeated = true;
        pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
    }
}

/* City NPCs ($96): inert, talkable, drawn from the captured sheet. */
static void SpawnNpc(ObjectPool *pool, const LevelObject *src) {
    Object *o = Alloc(pool);
    if (!o)
        return;
    memset(o, 0, sizeof(*o));
    o->active = true;
    o->type = OBJECT_NPC;
    o->species = (uint8_t)(src->species ? src->species : 0x96);
    o->x_fx = (int32_t)lroundf(src->x * FX_ONE);
    o->y_fx = (int32_t)lroundf(src->y * FX_ONE);
    o->origin_x_fx = o->x_fx;
    o->origin_y_fx = o->y_fx;
    o->hp = 1;
    o->facing = -1;
}

void Objects_Init(ObjectPool *pool, const Level *level) {
    memset(pool, 0, sizeof(*pool));
    pool->boss_phase = 1;
    /* $96 is the script/NPC actor: the shopkeepers and the library old man in
     * 46..49/55, the avenue's townsperson in area 4, and the arena controller
     * in the boss rooms (52/53/54, where it shares the boss's position). The
     * extractor types every $96 record "boss", which blocks every door in the
     * room and shows a boss placeholder. In a room with a real boss it is the
     * controller and stays invisible; anywhere else it is a talkable NPC. */
    bool room_has_boss = false;
    for (int i = 0; i < level->object_count; i++) {
        const LevelObject *o = &level->objects[i];
        if (o->type == LEVEL_OBJECT_BOSS && o->species != 0x96) {
            room_has_boss = true;
            break;
        }
    }
    if (getenv("DC_DEBUG_OBJ"))
        fprintf(stderr, "objects: init with %d level objects\n",
                level->object_count);
    for (int i = 0; i < level->object_count; i++) {
        const LevelObject *o = &level->objects[i];
        if (o->type == LEVEL_OBJECT_URN)
            SpawnUrn(pool, o);
        else if (o->type == LEVEL_OBJECT_ENEMY)
            SpawnEnemy(pool, o);
        else if (o->type == LEVEL_OBJECT_PLATFORM)
            SpawnPlatform(pool, o);
        else if (o->type == LEVEL_OBJECT_PICKUP_CREST)
            SpawnCrestItem(pool, o);
        else if (o->type == LEVEL_OBJECT_BOSS) {
            if (o->species == 0x96) {
                if (!room_has_boss)
                    SpawnNpc(pool, o);
            } else {
                SpawnBoss(pool, o);
            }
        } else if (o->type == LEVEL_OBJECT_NPC)
            SpawnNpc(pool, o);
        else if (o->type == LEVEL_OBJECT_TALISMAN)
            SpawnTalisman(pool, o);
    }
    if (getenv("DC_DEBUG_OBJ")) {
        int n = 0;
        for (int i = 0; i < OBJECT_POOL_SIZE; i++)
            if (pool->slots[i].active) {
                fprintf(stderr, "objects: slot %d type %d species %d at %.0f,%.0f\n",
                        i, (int)pool->slots[i].type, pool->slots[i].species,
                        pool->slots[i].x_fx / 256.0,
                        pool->slots[i].y_fx / 256.0);
                n++;
            }
        fprintf(stderr, "objects: %d active\n", n);
    }
}

static bool PlayerTouches(const Object *o, const Player *player) {
    float ox = (float)o->x_fx / FX_ONE;
    float oy = (float)o->y_fx / FX_ONE - HEART_HALF;
    float px = player->x;
    float py = player->y - 10.0f;
    return fabsf(ox - px) < 16.0f && fabsf(oy - py) < 20.0f;
}

static void DamagePlayer(Player *player, float ox, int amount) {
    if (player->invuln_timer > 0 || player->hp <= 0)
        return;
    /* Time/Ultimate Gargoyle and Armor Talisman halve incoming damage. */
    if ((player->crest_form == CREST_TIME ||
         player->crest_form == CREST_ULTIMATE ||
         player->active_talisman == 2) && amount > 1) {
        amount = (amount + 1) / 2;
    }
    player->hp -= amount;
    if (player->hp < 0)
        player->hp = 0;
    player->invuln_timer = 60;
    player->knockback_timer = 8;
    player->knockback_dir = (ox < player->x) ? 1 : -1;
    player->hurt_event = true;
}

/* ------------------------------------------------------------------------- *
 * Species $67 - Graveyard Ghoul
 *
 * Port of the ROM's own handler: init $83:AF19, update $83:AF74, which
 * dispatches on $05 through the table at $AF7F and on $06 through per-state
 * tables. States are even byte offsets, so each state has four substates
 * (0/2/4/6):
 *
 *   0 $AF89  small hop loop        sub 0 decide, 2 windup, 4 airborne, 6 land
 *   2 $B065  long hop              sub 0 face, 2 windup 32, 4 airborne, 6 land
 *   4 $B0E4  stand and spit        sub 0 face, 2 windup 32, 4 three children
 *                                  on a 64-frame cadence, 6 hold 32
 *   6 $B1AF  leap / child flight   sub 0 aim, 2 fly, 4 impact, 6 despawn
 *   8 $B249  cooldown              sub 0 wait $43, 2 re-check range
 *
 * The hop constants are the ROM's: launch `$22 = 0x0398` (`0x04D0` on odd
 * hops), `$20 = 0x0050`, gravity `$26 = 0x0040`, `$34 -= 9` at launch and
 * `+7` on landing. The long hop uses `$20 = 0x0120`, `$22 = 0x0540`.
 * The live oracle trace (`/tmp/ghoul_trace`, 300 frames, area 1) confirms the
 * observed order 4 -> 0(2,4,6) -> 0(2,...) with the 32/64/32 volley cadence.
 * ------------------------------------------------------------------------- */
#define GHOUL_GRAVITY 0x0040
#define GHOUL_RANGE_X 0x00E0
#define GHOUL_RANGE_Y 0x0050

static void GhoulFace(Object *o, const Player *p) {
    o->facing = (p->x_fx >= o->x_fx) ? 1 : -1;
}

/* $B2E8: |(x + 0x70) - player.x| < 0xE0, the $03 bit 6 flag set, and the
 * player above the ghoul or no more than 0x50 below it. */
static bool GhoulInRange(const Object *o, const Player *p) {
    int32_t dx = (o->x_fx + 0x70 * FX_ONE) - p->x_fx;
    if (labs((long)dx) >= GHOUL_RANGE_X * FX_ONE)
        return false;
    if (!(o->flags & 0x40))
        return false;
    int32_t dy = p->y_fx - o->y_fx;   /* y grows downward */
    return dy < GHOUL_RANGE_Y * FX_ONE;
}

/* One applied step of the ROM's move + gravity, returning true on landing. */
static bool GhoulMove(Object *o, const Level *level) {
    o->x_fx += o->vx_fx;
    o->y_fx += o->vy_fx;
    o->vy_fx += GHOUL_GRAVITY;
    float fx = (float)o->x_fx / FX_ONE;
    float fy = (float)o->y_fx / FX_ONE;
    float surf;
    if (o->vy_fx > 0 && Level_FloorAt(level, fx, fy + 2.0f, &surf) &&
        surf <= fy + 10.0f) {
        o->y_fx = (int32_t)lroundf(surf * FX_ONE);
        o->vx_fx = 0;
        o->vy_fx = 0;
        return true;
    }
    return false;
}

/* $B14F: the spit. The ROM spawns another $67 object at (+-0x13, -0x14) and
 * sets its state to 6, so the "projectile" is a small diving ghoul. */
static void GhoulSpit(ObjectPool *pool, const Object *o) {
    float ox = (float)o->x_fx / FX_ONE + (float)(o->facing * 0x13);
    float oy = (float)o->y_fx / FX_ONE - 0x14;
    /* The child is aimed at its parent's own x ($3F is written from $31 at
     * $B17C), so the distance band is the near one: vx = 0x80, vy = 0x03A0.
     * It does not home across the room; it lobs and falls. */
    SpawnEnemyShot(pool, ox, oy, o->facing * 0x0080, -0x03A0);
}

static void GhoulUpdate(Object *o, const Level *level, const Player *p,
                        ObjectPool *pool) {
    if (getenv("DC_DEBUG_GHOUL"))
        fprintf(stderr, "ghoul t=%d st=%d sub=%d ph=%d x=%.1f y=%.1f\n",
                o->timer, o->state, o->substate, o->phase,
                (float)o->x_fx / FX_ONE, (float)o->y_fx / FX_ONE);
    switch (o->state) {
    case 0: /* $AF89 small hop loop */
        switch (o->substate) {
        case 0:
            if (GhoulInRange(o, p)) {
                GhoulFace(o, p);
                o->hops = 0;
                o->substate = 2;
                o->phase = 3;          /* $3B = 3 */
            } else {
                /* $DEA2 picks at random; the port rotates deterministically so
                 * a replay is reproducible: hop, volley, long hop. */
                o->saved_state = (o->saved_state + 1) % 3;
                if (o->saved_state == 1) {
                    o->state = 4;
                    o->substate = 0;
                } else if (o->saved_state == 2) {
                    o->state = 2;
                    o->substate = 0;
                } else {
                    /* The rotation's third beat is the plain small hop. */
                    GhoulFace(o, p);
                    o->hops = 0;
                    o->substate = 2;
                    o->phase = 3;
                }
            }
            break;
        case 2:
            GhoulFace(o, p);
            if (--o->phase <= 0) {
                o->y_fx -= 9 * FX_ONE;             /* $B2B1 */
                o->vx_fx = o->facing * 0x0050;
                o->vy_fx = -((o->hops & 1) ? 0x04D0 : 0x0398);
                o->substate = 4;
            }
            break;
        case 4:
            if (GhoulMove(o, level)) {
                o->y_fx += 7 * FX_ONE;             /* $B2C7 */
                o->substate = 6;
                o->phase = 6;
            }
            break;
        case 6:
            if (--o->phase <= 0) {
                o->hops++;                          /* $B034 */
                if (o->hops >= 3) {
                    o->substate = 0;
                } else {
                    o->facing = -o->facing;
                    o->substate = 2;
                    o->phase = 3;
                }
            }
            break;
        default:
            o->substate = 0;
            break;
        }
        break;

    case 2: /* $B065 long hop */
        switch (o->substate) {
        case 0:
            GhoulFace(o, p);
            o->substate = 2;
            o->phase = 0x20;
            break;
        case 2:
            if (--o->phase <= 0) {
                o->y_fx -= 9 * FX_ONE;
                o->vx_fx = o->facing * 0x0120;
                o->vy_fx = -0x0540;
                o->substate = 4;
                o->landings = 0;
            }
            break;
        case 4:
            if (GhoulMove(o, level)) {
                o->y_fx += 7 * FX_ONE;
                o->substate = 6;
                o->phase = 0x10;
            }
            break;
        case 6:
            if (--o->phase <= 0) {
                o->state = 4;                       /* $B0DD */
                o->substate = 0;
            }
            break;
        default:
            o->substate = 0;
            break;
        }
        break;

    case 4: /* $B0E4 stand and spit three children */
        switch (o->substate) {
        case 0:
            GhoulFace(o, p);
            o->substate = 2;
            o->phase = 0x20;
            break;
        case 2:
            if (--o->phase <= 0) {
                o->substate = 4;
                o->spit_left = 3;                   /* $3D = 3 */
                o->spit_cd = 0x40;                  /* $3C = 0x40 */
            }
            break;
        case 4:
            if (--o->spit_cd <= 0) {
                GhoulSpit(pool, o);
                o->spit_left--;
                o->spit_cd = 0x40;
                if (o->spit_left <= 0) {
                    o->substate = 6;
                    o->phase = 0x20;
                }
            }
            break;
        case 6:
            if (--o->phase <= 0) {
                /* $B1AB jumps straight into the hop entry, not to the state
                 * dispatcher, so a volley always ends in hops. */
                GhoulFace(o, p);
                o->state = 0;
                o->hops = 0;
                o->substate = 2;
                o->phase = 3;
            }
            break;
        default:
            o->substate = 0;
            break;
        }
        break;

    case 6: /* $B1AF leap, and the child's flight */
        switch (o->substate) {
        case 0: {
            GhoulFace(o, p);
            o->target_x_fx = p->x_fx;
            int32_t dx = o->target_x_fx - o->x_fx;
            int32_t dist = labs((long)dx);
            /* $DEB2/$DEBA/$DEC2: farther targets get more speed and lift. */
            if (dist > 96 * FX_ONE) {
                o->vx_fx = o->facing * 0x0120;
                o->vy_fx = -0x0540;
            } else if (dist > 48 * FX_ONE) {
                o->vx_fx = o->facing * 0x00C0;
                o->vy_fx = -0x0480;
            } else {
                o->vx_fx = o->facing * 0x0080;
                o->vy_fx = -0x03A0;
            }
            o->substate = 2;
            break;
        }
        case 2:
            if (GhoulMove(o, level)) {
                o->substate = 4;
                o->phase = 8;
                o->landings++;
            }
            break;
        case 4:
            if (--o->phase <= 0) {
                o->substate = 6;
                o->phase = 0x20;
            }
            break;
        case 6:
            if (--o->phase <= 0)
                o->active = false;                  /* $828777 */
            break;
        default:
            o->substate = 0;
            break;
        }
        break;

    case 8: /* $B249 cooldown */
        switch (o->substate) {
        case 0:
            o->substate = 2;
            o->hide_timer = 0x50;                   /* $43 = 0x50 */
            break;
        case 2:
            if (--o->hide_timer <= 0) {
                if (!GhoulInRange(o, p)) {
                    o->state = 4;
                    o->substate = 0;
                } else {
                    o->state = 0;
                    o->substate = 0;
                }
            }
            break;
        default:
            o->substate = 0;
            break;
        }
        break;

    default:
        o->state = 0;
        o->substate = 0;
        break;
    }
}

void Objects_Update(ObjectPool *pool, const Level *level, Player *player) {

    pool->boss_alive = false;
    for (int i = 0; i < OBJECT_POOL_SIZE; i++) {
        Object *o = &pool->slots[i];
        if (!o->active)
            continue;

        if (o->type == OBJECT_NPC) {
            o->timer++;
            continue; /* talkable but inert */
        }

        if (o->type == OBJECT_PLATFORM) {
            o->timer++;
            int32_t old_x = o->x_fx;
            o->x_fx += o->vx_fx;
            if (abs(o->x_fx - o->origin_x_fx) > 48 * FX_ONE)
                o->vx_fx = -o->vx_fx;
            float ox = (float)o->x_fx / FX_ONE;
            float oy = (float)o->y_fx / FX_ONE;
            if (player->vy_fx >= 0 &&
                fabsf(player->x - ox) <= 20.0f &&
                player->y >= oy - 4.0f && player->y <= oy + 6.0f) {
                player->y_fx = o->y_fx;
                player->x_fx += (o->x_fx - old_x);
                player->y = oy;
                player->x = (float)player->x_fx / FX_ONE;
                player->vy_fx = 0;
                player->vy = 0.0f;
                player->on_ground = true;
            }
            continue;
        }

        if (o->type == OBJECT_TALISMAN) {
            o->timer++;
            o->y_fx = o->origin_y_fx +
                      (int32_t)(sinf(o->timer * 0.05f) * 3.0f * FX_ONE);
            if (PlayerTouches(o, player)) {
                player->talisman_mask |= (uint8_t)(1u << o->species);
                player->active_talisman = o->species;
                pool->last_talisman = o->species;
                o->active = false;
                pool->events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_TALISMAN;
            }
            continue;
        }

        if (o->type == OBJECT_CREST_ITEM) {
            o->timer++;
            if (PlayerTouches(o, player)) {
                /* Crest pieces in the original grant the next Fire-Crest
                 * element ($BE:A427..A533: Buster, Tornado, Claw, Demon Fire)
                 * before they become plain stat upgrades. */
                if (player->fire_element < 4) {
                    player->fire_element++;
                    pool->last_fire_piece = player->fire_element;
                    pool->events |= OBJECT_EVENT_FIRE_PIECE;
                }
                if (player->max_hp < 10)
                    player->max_hp++;
                player->hp = player->max_hp;
                player->gold += 50;
                if (player->potions < 5)
                    player->potions++;
                o->active = false;
                pool->events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_CREST_PICKUP;
            }
            continue;
        }

        if (o->type == OBJECT_BOSS) {
            if (o->state == 5) {   /* dying: hold the defeated pose, then go */
                o->timer++;
                if (o->phase > 0)
                    o->phase--;
                else
                    o->active = false;
                continue;
            }
            pool->boss_alive = true;
            o->timer++;
            if (o->hit_flash > 0)
                o->hit_flash--;
            int32_t dx = player->x_fx - o->x_fx;
            int32_t dy = (player->y_fx - 16 * FX_ONE) - o->y_fx;
            if (o->species == 0x33) {
                /* Somulo, the colosseum dragon. The head is the weak point and
                 * the fight is a fireball duel: idle -> windup -> fire (low or
                 * high, aimed at Firebrand) -> recover, with a stagger when the
                 * head is hit. Six head hits kill him. */
                if (o->state == 6) {   /* fainted: down, invulnerable, no attacks */
                    if (o->phase > 0) {
                        o->phase--;
                    } else {
                        /* He comes back with three hits left and cannot give
                         * chase any more (substate 3). He stays where he fell:
                         * teleporting him to the room's gate put him out of the
                         * player's reach and the last three hits never landed.
                         * The "stuck in the door" framing belongs to the escape
                         * room, which the port does not model yet. */
                        o->hp = 3;
                        o->max_hp = 3;
                        o->state = 0;
                        o->phase = 40;
                        o->substate = 3;
                    }
                    o->y_fx = o->origin_y_fx;
                    continue;
                }
                if (o->state == 7) {   /* blind walk after the roar */
                    int32_t towards = (player->x_fx > o->x_fx) ? 1 : -1;
                    o->facing = (int)towards;
                    o->x_fx += towards * (int32_t)(0.85f * FX_ONE);
                    if (o->phase > 0)
                        o->phase--;
                    else {
                        o->state = 0;   /* eyes open: the fireball duel */
                        o->phase = 40;
                    }
                    if (player->hp > 0 &&
                        fabsf((float)(player->x_fx - o->x_fx) / FX_ONE) < 70.0f)
                        player->hp = 0;
                    continue;
                }
                if (o->hit_flash > 0 && o->state != 4) {
                    o->state = 4;   /* stagger */
                    o->phase = 36;
                }
                /* The recording shows him walking the corridor after Firebrand:
                 * close the distance when the player runs away. */
                if (o->state == 0 || o->state == 3) {
                    if (dx > 0)
                        o->facing = 1;
                    else if (dx < 0)
                        o->facing = -1;
                    /* Stuck in the gate (substate 3) he cannot give chase, which
                     * is what makes the last three hits possible. */
                    if (o->substate != 3) {
                        if (dx > 150 * FX_ONE)
                            o->x_fx += 0x0090;
                        else if (dx < -150 * FX_ONE)
                            o->x_fx -= 0x0090;
                        int32_t lo = (int32_t)(40.0f * FX_ONE);
                        int32_t hi = (int32_t)((level->play_max_x - 60.0f) *
                                               FX_ONE);
                        if (o->x_fx < lo)
                            o->x_fx = lo;
                        if (o->x_fx > hi)
                            o->x_fx = hi;
                    }
                }
                o->phase--;
                if (getenv("DC_BOSS_NO_ATTACK")) {
                    /* Test hook: hold the duel in its hittable idle. Cycling
                     * through windup/fire left the head unhittable for ~65 of
                     * every 80 frames, so the scripted six-hit check could only
                     * ever land five hits and the boss survived the run. */
                    o->state = 0;
                    o->phase = 40;
                    continue;
                }
                if (o->phase <= 0) {
                    switch (o->state) {
                    case 0: /* idle, breathing */
                        /* Lore rule (Ghosts'n Goblins wiki): he only lowers his
                         * head to shoot when Firebrand is on the ground, and
                         * attacks from above if the player stays airborne. */
                        if (player->on_ground) {
                            o->state = 1;
                            o->phase = 34;
                        } else {
                            o->state = 5;
                            o->phase = 26;
                        }
                        break;
                    case 1: /* windup: head lowered, jaws open */
                        o->state = 2;
                        o->phase = 10;
                        break;
                    case 2: { /* fire */
                        /* Test hook: a passive boss lets the fight loop be
                         * verified without dodging. */
                        if (getenv("DC_BOSS_NO_ATTACK")) {
                            o->state = 0;
                            o->phase = 30;
                            break;
                        }
                        float ox = (float)o->x_fx / FX_ONE;
                        float oy = (float)o->y_fx / FX_ONE;
                        float mouth_x = ox + ((dx > 0) ? 26.0f : -26.0f);
                        float mouth_y = oy + 10.0f;
                        /* Grounded player: the shot goes low and spreads into a
                         * fire wave when it lands (wiki). */
                        o->substate = 1;
                        float target_y = player->y - 2.0f;
                        float tx = player->x - mouth_x;
                        float ty = target_y - mouth_y;
                        float len = sqrtf(tx * tx + ty * ty);
                        if (len < 0.001f)
                            len = 1.0f;
                        SpawnBossFireball(pool, mouth_x, mouth_y,
                                          (int32_t)(tx / len * 1.6f * FX_ONE),
                                          (int32_t)(ty / len * 1.6f * FX_ONE));
                        o->state = 3;
                        o->phase = 20;
                        break;
                    }
                    case 5: { /* airborne player: attack from above, no head dip */
                        float ox = (float)o->x_fx / FX_ONE;
                        float oy = (float)o->y_fx / FX_ONE;
                        float mouth_x = ox;
                        float mouth_y = oy - 40.0f;
                        o->substate = 2;
                        float tx = player->x - mouth_x;
                        float ty = player->y - mouth_y;
                        float len = sqrtf(tx * tx + ty * ty);
                        if (len < 0.001f)
                            len = 1.0f;
                        SpawnBossFireball(pool, mouth_x, mouth_y,
                                          (int32_t)(tx / len * 1.6f * FX_ONE),
                                          (int32_t)(ty / len * 1.6f * FX_ONE));
                        o->state = 3;
                        o->phase = 20;
                        break;
                    }
                    case 3: /* recover */
                        o->state = 0;
                        o->phase = 12;
                        break;
                    case 4: /* stagger over: back to idle */
                        o->state = 0;
                        o->phase = 30;
                        break;
                    default:
                        o->state = 0;
                        o->phase = 30;
                        break;
                    }
                }
                /* The object stays planted: the head dip is a sprite state, not a
                 * translation. Dragging y toward origin+86 used to sink him to
                 * the world bottom (y=256) while idle, which is why the boss
                 * looked like it slid instead of standing and animating. */
                o->y_fx = o->origin_y_fx;
            } else if (o->species == 0x13) {
                /* Grewon: a ground beast. It paces toward Firebrand, crouches,
                 * then charges across the arena, and is helpless while turning
                 * around. */
                if (o->hit_flash > 0 && o->state != 4) {
                    o->state = 4;
                    o->phase = 20;
                }
                o->phase--;
                float surf;
                float ox = (float)o->x_fx / FX_ONE;
                float oy = (float)o->y_fx / FX_ONE;
                if (Level_FloorAt(level, ox, oy, &surf) && oy < surf)
                    o->y_fx = (int32_t)lroundf(surf * FX_ONE);
                if (o->phase <= 0) {
                    switch (o->state) {
                    case 0: /* pace toward the player */
                        o->x_fx += (dx > 0) ? 0x0080 : -0x0080;
                        o->facing = dx > 0 ? 1 : -1;
                        if (abs(dx) < 90 * FX_ONE) {
                            o->state = 1;
                            o->phase = 26;
                        } else {
                            o->phase = 10;
                        }
                        break;
                    case 1: /* crouch before the charge */
                        o->state = 2;
                        o->phase = 64;
                        o->substate = o->facing;
                        break;
                    case 2: /* charge */
                        o->x_fx += (o->substate > 0) ? 0x0300 : -0x0300;
                        if (o->x_fx < level->play_min_x * FX_ONE ||
                            o->x_fx > level->play_max_x * FX_ONE) {
                            o->x_fx = (o->substate > 0)
                                          ? (int32_t)(level->play_max_x *
                                                      FX_ONE)
                                          : (int32_t)(level->play_min_x *
                                                      FX_ONE);
                            o->state = 3;
                            o->phase = 34;
                        } else if (o->phase <= 1) {
                            o->state = 3;
                            o->phase = 34;
                        }
                        break;
                    case 3: /* recover */
                        o->state = 0;
                        o->phase = 20;
                        break;
                    case 4:
                        o->state = 0;
                        o->phase = 20;
                        break;
                    default:
                        o->state = 0;
                        o->phase = 20;
                        break;
                    }
                }
                o->origin_y_fx = o->y_fx;
            } else if (o->species == 0x09) {
                /* Hippogriff: hovers, dives, throws feathers — and now and then
                 * turns back into a statue. Shots do nothing then; a headbutt
                 * wakes him (the recording shows this, randomly). */
                if (o->state == 5) {
                    /* Killed: the rubble stays on the floor for the phase. */
                    if (--o->phase <= 0)
                        o->active = false;
                    continue;
                }
                if (o->state == 6) {
                    /* Stone: shots spark off (the boss branch skips damage while
                     * state 6), only a headbutt at close range wakes him, and
                     * he gets bored after the phase timer runs out. */
                    bool headbutt =
                        player->dash_timer > 0 &&
                        fabsf((float)(player->x_fx - o->x_fx) / FX_ONE) < 30.0f;
                    if (headbutt) {
                        o->state = 0;
                        o->phase = 40;
                        o->hit_flash = 10;
                    } else {
                        o->phase--;
                        if (o->phase <= 0) {
                            o->state = 0;   /* got bored, woke on his own */
                            o->phase = 40;
                        }
                    }
                    continue;
                }
                if (o->hit_flash > 0 && o->state != 4) {
                    o->state = 4;
                    o->phase = 20;
                }
                o->phase--;
                if (o->phase <= 0) {
                    switch (o->state) {
                    case 0: /* hover and track */
                        /* Occasionally turn to stone: 1 in 4 every cycle, or
                         * always with the test hook. */
                        if (getenv("DC_BOSS_STATUE") != NULL ||
                            (o->timer > 120 && (o->hops % 4) == 3)) {
                            o->state = 6;
                            o->phase = 260;
                            o->hops++;
                            break;
                        }
                        o->state = (o->hops++ & 1) ? 1 : 2;
                        o->phase = (o->state == 1) ? 50 : 30;
                        break;
                    case 1: { /* feather volley */
                        float ox = (float)o->x_fx / FX_ONE;
                        float oy = (float)o->y_fx / FX_ONE;
                        for (int k = -1; k <= 1; k++) {
                            float tx = player->x - ox;
                            float ty = (player->y - 12.0f) - oy;
                            float len = sqrtf(tx * tx + ty * ty);
                            if (len < 0.001f)
                                len = 1.0f;
                            SpawnEnemyShot(pool, ox, oy,
                                           (int32_t)(tx / len * 1.3f * FX_ONE +
                                                     k * 0.4f * FX_ONE),
                                           (int32_t)(ty / len * 1.3f * FX_ONE));
                        }
                        o->state = 0;
                        o->phase = 40;
                        break;
                    }
                    case 2: /* dive */
                        o->x_fx += (dx > 0) ? 0x0240 : -0x0240;
                        o->y_fx += (dy > 0) ? 0x0180 : -0x0180;
                        o->state = 3;
                        o->phase = 26;
                        break;
                    case 3: /* climb back */
                        o->x_fx += (o->origin_x_fx - o->x_fx) / 8;
                        o->y_fx += (o->origin_y_fx - o->y_fx) / 8;
                        o->state = 0;
                        o->phase = 30;
                        break;
                    case 4:
                        o->state = 0;
                        o->phase = 20;
                        break;
                    default:
                        o->state = 0;
                        o->phase = 30;
                        break;
                    }
                }
                if (o->state == 0)
                    o->y_fx = o->origin_y_fx +
                              (int32_t)(sinf(o->timer * 0.06f) * 14.0f *
                                        FX_ONE);
            } else if (o->species == 0x86 || o->species == 0x8D) {
                /* Phalanx: the demon form hovers and lobs slow orbs. The
                 * second form keeps the same head AI but uses the $8D body
                 * sheet (the live boss2 save contains $86 + many $8D parts). */
                if (o->hit_flash > 0 && o->state != 4) {
                    o->state = 4;
                    o->phase = 20;
                }
                o->phase--;
                if (o->phase <= 0) {
                    switch (o->state) {
                    case 0: /* drift above the player */
                        o->x_fx += (dx > 0) ? 0x00A0 : -0x00A0;
                        o->y_fx = o->origin_y_fx +
                                  (int32_t)(sinf(o->timer * 0.05f) * 18.0f *
                                            FX_ONE);
                        if (o->timer % 90 == 0) {
                            o->state = 1;
                            o->phase = 26;
                        } else {
                            o->phase = 4;
                        }
                        break;
                    case 1: { /* orb */
                        float ox = (float)o->x_fx / FX_ONE;
                        float oy = (float)o->y_fx / FX_ONE;
                        float tx = player->x - ox;
                        float ty = (player->y - 10.0f) - oy;
                        float len = sqrtf(tx * tx + ty * ty);
                        if (len < 0.001f)
                            len = 1.0f;
                        SpawnEnemyShot(pool, ox, oy + 14.0f,
                                       (int32_t)(tx / len * 1.1f * FX_ONE),
                                       (int32_t)(ty / len * 1.1f * FX_ONE));
                        o->state = 0;
                        o->phase = 60;
                        break;
                    }
                    case 4:
                        o->state = 0;
                        o->phase = 20;
                        break;
                    default:
                        o->state = 0;
                        o->phase = 20;
                        break;
                    }
                }
            } else if (o->species == 0xA5) {
                /* Arma: hovers in place, then either breathes a pair of shots
                 * or divebombs along the player's line, with a stagger when
                 * hit. */
                if (o->hit_flash > 0 && o->state != 4) {
                    o->state = 4;
                    o->phase = 30;
                }
                o->phase--;
                if (o->phase <= 0) {
                    switch (o->state) {
                    case 0: /* hover -> choose an attack */
                        if (o->hops++ & 1) {
                            o->state = 2;   /* dive */
                            o->phase = 60;
                        } else {
                            o->state = 1;   /* breath */
                            o->phase = 24;
                        }
                        break;
                    case 1: { /* breath attack */
                        float ox = (float)o->x_fx / FX_ONE;
                        float oy = (float)o->y_fx / FX_ONE;
                        for (int k = 0; k < 2; k++) {
                            float ty = (player->y - 18.0f - (float)k * 10.0f)
                                       - oy;
                            float tx = player->x - ox;
                            float len = sqrtf(tx * tx + ty * ty);
                            if (len < 0.001f)
                                len = 1.0f;
                            /* Arma's breath is a plain shot: only Somulo's
                             * fireball leaves a firewall. */
                            SpawnEnemyShot(
                                pool, ox + ((tx > 0) ? 16.0f : -16.0f), oy,
                                (int32_t)(tx / len * 1.5f * FX_ONE),
                                (int32_t)(ty / len * 1.5f * FX_ONE));
                        }
                        o->state = 0;
                        o->phase = 60;
                        break;
                    }
                    case 2: /* dive: rush toward the player */
                        if (abs(dx) > 8 * FX_ONE)
                            o->x_fx += (dx > 0) ? 0x0280 : -0x0280;
                        if (dy > 6 * FX_ONE)
                            o->y_fx += 0x0200;
                        else if (dy < -6 * FX_ONE)
                            o->y_fx -= 0x0200;
                        o->state = 3;
                        o->phase = 30;
                        break;
                    case 3: /* climb back to the post */
                        o->x_fx += (o->origin_x_fx - o->x_fx) / 8;
                        o->y_fx += (o->origin_y_fx - o->y_fx) / 8;
                        o->state = 0;
                        o->phase = 50;
                        break;
                    case 4:
                        o->state = 0;
                        o->phase = 30;
                        break;
                    default:
                        o->state = 0;
                        o->phase = 40;
                        break;
                    }
                }
                /* Slow bob while hovering. */
                if (o->state == 0)
                    o->y_fx = o->origin_y_fx +
                              (int32_t)(sinf(o->timer * 0.05f) * 10.0f *
                                        FX_ONE);
            } else {
                /* Hippogriff / Stage Boss: swoop and hover above Firebrand,
                 * and punish with a three-shot spread every 110 frames. */
                if (abs(dx) > 12 * FX_ONE)
                    o->x_fx += (dx > 0) ? 0x0100 : -0x0100;
                int32_t target_y = o->origin_y_fx +
                                   (int32_t)(sinf(o->timer * 0.06f) * 28.0f * FX_ONE);
                if ((o->timer % 140) > 90)
                    target_y = player->y_fx - 12 * FX_ONE;
                if (o->y_fx < target_y)
                    o->y_fx += 0x00C0;
                else if (o->y_fx > target_y)
                    o->y_fx -= 0x00C0;
                (void)dy;
                if (o->timer % 110 == 40) {
                    float bx = (float)o->x_fx / FX_ONE;
                    float by = (float)o->y_fx / FX_ONE;
                    float tx = player->x - bx;
                    float ty = (player->y - 10.0f) - by;
                    float len = sqrtf(tx * tx + ty * ty);
                    if (len < 0.001f)
                        len = 1.0f;
                    tx /= len;
                    ty /= len;
                    for (int k = -1; k <= 1; k++) {
                        float ang = (float)k * 0.35f;
                        float cx = tx * cosf(ang) - ty * sinf(ang);
                        float cy = tx * sinf(ang) + ty * cosf(ang);
                        SpawnEnemyShot(pool, bx, by, (int32_t)(cx * 1.4f * FX_ONE),
                                       (int32_t)(cy * 1.4f * FX_ONE));
                    }
                }
            }
            /* Keep boss art turned toward the player between attack states. */
            if (dx > 8 * FX_ONE)
                o->facing = 1;
            else if (dx < -8 * FX_ONE)
                o->facing = -1;

            float ox = (float)o->x_fx / FX_ONE;
            float oy = (float)o->y_fx / FX_ONE;
            if (fabsf(ox - player->x) < 20.0f &&
                fabsf(oy - (player->y - 11.0f)) < 22.0f) {
                if (player->dash_timer > 0) {
                    o->hp--;
                    pool->events |= OBJECT_EVENT_ENEMY_HIT;
                    player->dash_timer = 0;
                    if (o->hp <= 0) {
                        o->active = false;
                        pool->boss_alive = false;
                        pool->boss_defeated = true;
                        pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
                        SpawnPickup(pool, ox, oy);
                    }
                } else {
                    DamagePlayer(player, ox, 1);
                }
            }
            continue;
        }

        if (o->type == OBJECT_ENEMY) {
            float ox = (float)o->x_fx / FX_ONE;
            float oy = (float)o->y_fx / FX_ONE;
            o->timer++;
            if (o->species == 0x2C) {
                /* Area 2 Skeleton walker: ground patrol. */
                o->state = 1;
                o->x_fx += o->vx_fx;
                ox = (float)o->x_fx / FX_ONE;
                float surf;
                if (Level_IsWallAt(level, ox + (o->vx_fx > 0 ? 8.0f : -8.0f),
                                   oy - 8.0f) ||
                    abs(o->x_fx - o->origin_x_fx) > 96 * FX_ONE) {
                    o->vx_fx = -o->vx_fx;
                    o->facing = (o->vx_fx >= 0) ? 1 : -1;
                }
                if (Level_FloorAt(level, ox, oy + 4.0f, &surf))
                    o->y_fx = (int32_t)lroundf(surf * FX_ONE);
            } else if (o->species == 0x07) {
                /* Area 2/3 Bat/Watcher: sine wave swoop. */
                o->state = 1;
                int32_t dx = player->x_fx - o->x_fx;
                if (abs(dx) < 200 * FX_ONE) {
                    o->x_fx += (dx > 0) ? 0x0080 : -0x0080;
                    o->y_fx = o->origin_y_fx +
                              (int32_t)(sinf(o->timer * 0.08f) * 18.0f * FX_ONE);
                }
            } else if (o->species == 0x67) {
                /* Authentic $83:AF74 handler (see GhoulUpdate above). The
                 * contact-damage tail below still runs for ghouls. */
                GhoulUpdate(o, level, player, pool);
            } else {
                /* Generic enemy for species whose ROM handler is not ported yet.
                 * Placement decides the style: enemies spawned well above a
                 * floor fly (hover + 2D chase), grounded ones patrol and walk
                 * toward the player. Keeps rooms lively without the ghoul's hop
                 * behaviour leaking into every other species. */
                int32_t dx = player->x_fx - o->x_fx;
                int32_t dy = player->y_fx - o->y_fx;
                bool near = labs((long)dx) < 140 * FX_ONE &&
                            labs((long)dy) < 64 * FX_ONE;
                float spawn_x = (float)o->origin_x_fx / FX_ONE;
                float spawn_y = (float)o->origin_y_fx / FX_ONE;
                float floor_y = 0.0f;
                /* No floor under the spawn also means "flying": those spawns
                 * hang over pits or above the walkable layer. */
                bool airborne = !Level_FloorAt(level, spawn_x, spawn_y,
                                               &floor_y) ||
                                floor_y - spawn_y > 24.0f;
                if (airborne) {
                    if (o->state == 2) {
                        /* Dive attack: locked velocity for a few frames. */
                        o->x_fx += o->vx_fx;
                        o->y_fx += o->vy_fx;
                        if (--o->phase <= 0) {
                            o->state = 0;
                            o->phase = 90;
                            o->vx_fx = 0;
                            o->vy_fx = 0;
                        }
                    } else {
                        /* Flyer: drift toward the player, bob around spawn. */
                        o->facing = dx >= 0 ? 1 : -1;
                        if (labs((long)dx) > 8 * FX_ONE)
                            o->x_fx += o->facing * 0x0070;
                        float target_y = (float)o->origin_y_fx / FX_ONE +
                                         sinf(o->timer * 0.07f) * 14.0f;
                        if (fabsf(player->y - 14.0f - target_y) < 60.0f)
                            target_y = player->y - 14.0f;
                        float cur_y = (float)o->y_fx / FX_ONE;
                        if (target_y > cur_y + 1.0f)
                            o->y_fx += 0x0050;
                        else if (target_y < cur_y - 1.0f)
                            o->y_fx -= 0x0050;
                        if (o->phase > 0)
                            o->phase--;
                        else if (labs((long)dx) < 64 * FX_ONE &&
                                 labs((long)dy) < 180 * FX_ONE) {
                            /* Swoop at the player's current position. */
                            float ddx = (float)dx;
                            float ddy = (float)dy;
                            float len = sqrtf(ddx * ddx + ddy * ddy);
                            if (len < 0.001f)
                                len = 1.0f;
                            o->vx_fx = (int32_t)(ddx / len * 3.0f * FX_ONE);
                            o->vy_fx = (int32_t)(ddy / len * 3.0f * FX_ONE);
                            o->state = 2;
                            o->phase = 22;
                        }
                    }
                } else {
                    if (o->state == 2) {
                        /* Ground lunge: short horizontal burst. */
                        o->x_fx += o->facing * 0x0200;
                        float gx = (float)o->x_fx / FX_ONE;
                        float gy = (float)o->y_fx / FX_ONE;
                        float surf;
                        if (Level_FloorAt(level, gx, gy + 4.0f, &surf))
                            o->y_fx = (int32_t)lroundf(surf * FX_ONE);
                        if (--o->phase <= 0) {
                            o->state = 0;
                            o->phase = 80;
                        }
                    } else {
                        if (near) {
                            o->facing = dx >= 0 ? 1 : -1;
                            if (labs((long)dx) > 10 * FX_ONE)
                                o->x_fx += o->facing * 0x0068;
                        } else {
                            if (o->vx_fx == 0)
                                o->vx_fx = 0x0048;
                            o->x_fx += o->vx_fx;
                            if (labs((long)(o->x_fx - o->origin_x_fx)) >
                                48 * FX_ONE) {
                                o->vx_fx = -o->vx_fx;
                                o->facing = (o->vx_fx >= 0) ? 1 : -1;
                            }
                        }
                        float gx = (float)o->x_fx / FX_ONE;
                        float gy = (float)o->y_fx / FX_ONE;
                        float surf;
                        if (Level_FloorAt(level, gx, gy + 4.0f, &surf))
                            o->y_fx = (int32_t)lroundf(surf * FX_ONE);
                        if (o->phase > 0)
                            o->phase--;
                        else if (near && labs((long)dx) > 14 * FX_ONE &&
                                 labs((long)dx) < 52 * FX_ONE) {
                            o->state = 2;
                            o->phase = 14;
                        }
                    }
                }
            }
            ox = (float)o->x_fx / FX_ONE;
            oy = (float)o->y_fx / FX_ONE;
            float px = player->x;
            float py = player->y - 10.0f;
            if (fabsf(ox - px) < 14.0f && fabsf(oy - py) < 18.0f) {
                if (player->dash_timer > 0) {
                    o->hp = 0;
                    o->active = false;
                    pool->events |= OBJECT_EVENT_ENEMY_HIT;
                    SpawnPickup(pool, ox, oy + 8.0f);
                } else {
                    DamagePlayer(player, ox, 1);
                }
            }
            continue;
        }

        if (o->hit_flash > 0)
            o->hit_flash--;

        if (o->type == OBJECT_ENEMY_SHOT) {
            o->timer++;
            float sx = (float)o->x_fx / FX_ONE;
            float sy = (float)o->y_fx / FX_ONE;
            if (o->state == 1) {
                /* Firewall flame: stays put, burns for a while. */
                if (o->timer > 90)
                    o->active = false;
                else if (fabsf(sx - player->x) < 9.0f &&
                         fabsf(sy - (player->y - 6.0f)) < 16.0f)
                    DamagePlayer(player, sx, 1);
                continue;
            }
            o->x_fx += o->vx_fx;
            o->y_fx += o->vy_fx;
            sx = (float)o->x_fx / FX_ONE;
            sy = (float)o->y_fx / FX_ONE;
            bool hit_ground = Level_IsSolidAt(level, sx, sy) ||
                              (Level_FloorAt(level, sx, sy, NULL) && sy >=
                               (float)(level->world_h - 24));
            if (o->timer > 240 || hit_ground ||
                sx < level->play_min_x - 16.0f ||
                sx > level->play_max_x + 16.0f ||
                sy < 0.0f || sy > (float)level->world_h) {
                if (o->substate == 1 && hit_ground)
                    SpawnFirewall(pool, sx, sy - 4.0f);
                o->active = false;
                continue;
            }
            if (fabsf(sx - player->x) < 10.0f &&
                fabsf(sy - (player->y - 10.0f)) < 12.0f) {
                DamagePlayer(player, sx, 1);
                if (o->substate == 1)
                    SpawnFirewall(pool, sx, sy);
                o->active = false;
            }
            continue;
        }

        if (o->type != OBJECT_PICKUP)
            continue;

        if (o->state == 0) {
            o->vy_fx += HEART_GRAVITY_FX;
            if (o->vy_fx > 0x0600)
                o->vy_fx = 0x0600;
            o->y_fx += o->vy_fx;

            float surface;
            float x = (float)o->x_fx / FX_ONE;
            float y = (float)o->y_fx / FX_ONE;
            if (Level_FloorAt(level, x, y, &surface) && y >= surface) {
                o->y_fx = (int32_t)lroundf(surface * FX_ONE);
                o->bounce_fx -= HEART_BOUNCE_STEP;
                if (o->bounce_fx > 0) {
                    o->vy_fx = -o->bounce_fx;
                } else {
                    o->bounce_fx = 0;
                    o->vy_fx = 0;
                    o->state = 1; /* at rest */
                }
            }
        }

        if (PlayerTouches(o, player)) {
            if (player->hp < player->max_hp)
                player->hp++;
            player->gold += 10;
            o->active = false;
            pool->events |= OBJECT_EVENT_PICKUP;
        }
    }
}

void Objects_CheckProjectiles(ObjectPool *pool, ProjectilePool *projectiles) {
    for (int i = 0; i < PROJECTILE_POOL_SIZE; i++) {
        Projectile *p = &projectiles->slots[i];
        if (!p->active)
            continue;
        float px = (float)p->x_fx / FX_ONE;
        float py = (float)p->y_fx / FX_ONE;
        int dmg = p->damage > 0 ? p->damage : 1;

        for (int j = 0; j < OBJECT_POOL_SIZE; j++) {
            Object *o = &pool->slots[j];
            if (!o->active)
                continue;
            float ox = (float)o->x_fx / FX_ONE;
            float oy = (float)o->y_fx / FX_ONE;

            if (o->type == OBJECT_URN) {
                if (fabsf(px - ox) <= URN_HALF + 4.0f &&
                    fabsf(py - oy) <= URN_HALF + 14.0f) {
                    o->active = false;
                    p->active = false;
                    pool->events |= OBJECT_EVENT_BREAK;
                    SpawnPickup(pool, ox, oy + URN_HALF);
                    break;
                }
            } else if (o->type == OBJECT_ENEMY &&
                       (o->species == 0x67 || o->state != 0)) {
                /* Ghouls are hittable in every state: the ROM's $05 values are
                 * behaviour states, not an emerge phase. */
                if (fabsf(px - ox) <= 12.0f && fabsf(py - oy) <= 12.0f) {
                    p->active = false;
                    o->hp -= dmg;
                    o->hit_flash = 8;
                    pool->events |= OBJECT_EVENT_ENEMY_HIT;
                    if (o->hp <= 0) {
                        SpawnPickup(pool, ox, oy + 8.0f);
                        o->active = false;
                    }
                    break;
                }
            } else if (o->type == OBJECT_ENEMY_SHOT) {
                if (fabsf(px - ox) <= 8.0f && fabsf(py - oy) <= 8.0f) {
                    p->active = false;
                    o->active = false;
                    pool->events |= OBJECT_EVENT_ENEMY_HIT;
                    break;
                }
            } else if (o->type == OBJECT_BOSS) {
                if (o->state == 5 || o->state == 6)
                    continue;   /* collapsing or fainted: ignore hits */
                float hw = (o->species == 0x33) ? 40.0f : 20.0f;
                float hh = (o->species == 0x33) ? 46.0f : 24.0f;
                if (fabsf(px - ox) <= hw && fabsf(py - oy) <= hh) {
                    if (o->species == 0x09 && o->state == 6) {
                        p->active = false;   /* spark off the stone */
                        break;
                    }
                    /* Somulo flashes white for ~33 frames after a hit in the
                     * recording and cannot be hit again until it ends, so the
                     * six-hit rhythm is the player's, not a machine gun.
                     * Grewon turns green for 45..75 frames and is invincible
                     * until he changes back: hits during it do nothing. */
                    if ((o->species == 0x33 || o->species == 0x13) &&
                        o->hit_flash > 0)
                        continue;
                    p->active = false;
                    o->hp -= dmg;
                    if (o->species == 0x33)
                        o->hit_flash = 32;
                    else if (o->species == 0x13)
                        o->hit_flash = 60;
                    else
                        o->hit_flash = 8;
                    pool->events |= OBJECT_EVENT_ENEMY_HIT;
                    if (o->hp <= 0) {
                        if (o->species == 0x33) {
                            if (o->hops == 0 && getenv("DC_BOSS_SKIP_FAINT") == NULL) {
                                /* First death blow is not death: he faints
                                 * (wiki). The player is free to move while he is
                                 * down, and he comes back stuck in the gate with
                                 * three hits left. */
                                o->hp = 0;
                                o->hops = 1;
                                o->state = 6;
                                o->phase = 180;
                                o->hit_flash = 0;
                                break;
                            }
                            /* Collapse, lie there, then leave the room. */
                            o->state = 5;
                            o->phase = 90;
                            o->hit_flash = 0;
                            pool->boss_alive = false;
                            pool->boss_defeated = true;
                            pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
                            SpawnPickup(pool, ox, oy + 8.0f);
                            break;
                        }
                        o->active = false;
                        if (o->species == 0x09) {
                            /* The take shows him breaking apart on the floor:
                             * hold the rubble pose for 1.5 s before freeing the
                             * slot. The gate is already open (boss_alive is
                             * cleared below), so this is only presentation. */
                            o->active = true;
                            o->state = 5;
                            o->phase = 90;
                            o->hit_flash = 0;
                            pool->boss_alive = false;
                            pool->boss_defeated = true;
                            pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
                            break;
                        }
                        if (o->species == 0x86 && pool->boss_phase == 1) {
                            /* Phalanx's first form falls and the second rises
                             * from the pit: same head, stronger, and the exit
                             * stays shut until it dies too. */
                            pool->boss_phase = 2;
                            Object *n = Alloc(pool);
                            if (n) {
                                memset(n, 0, sizeof(*n));
                                n->active = true;
                                n->type = OBJECT_BOSS;
                                n->species = 0x8D;
                                n->x_fx = o->x_fx;
                                n->y_fx = o->y_fx + 40 * FX_ONE;
                                n->origin_x_fx = n->x_fx;
                                n->origin_y_fx = n->y_fx;
                                n->hp = 10;
                                n->max_hp = 10;
                                n->substate = 1;   /* second form */
                                pool->boss_alive = true;
                                pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
                            }
                            break;
                        }
                        pool->boss_alive = false;
                        pool->boss_defeated = true;
                        pool->events |= OBJECT_EVENT_BOSS_DEFEATED;
                        SpawnPickup(pool, ox, oy + 8.0f);
                    }
                    break;
                }
            }
        }
    }
}
