#include "player.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PLAYER_HALF_W 6.0f
#define PLAYER_HEIGHT 22.0f

/* Bank $80 player constants, all 8.8 fixed point. */
#define PLAYER_WALK_INITIAL_FX 0x00B3 /* $80:F0BE, 0.69921875 px/frame */
#define PLAYER_WALK_MAX_FX 0x0166     /* $80:F0D0, 1.3984375 px/frame */
#define PLAYER_WALK_WATER_FX 0x0100   /* $80:DDB8, 1.0 px/frame underwater */
#define PLAYER_EARTH_DASH_FX 0x0280   /* Earth Gargoyle shoulder tackle */
#define PLAYER_WALK_ACCEL_FX 0x0003   /* $80:F07A, 3/256 px/frame per frame */
#define PLAYER_GRAVITY_FX 0x0038      /* $80:E070, 0.21875 px/frame^2 */
#define PLAYER_GRAVITY_WATER_FX 0x002A /* $80:E076, 0.1640625 px/frame^2 */
#define PLAYER_JUMP_FX 0x059C         /* $80:E170, 5.609375 px/frame */
#define PLAYER_JUMP_WATER_FX 0x02CE   /* $80:E166, 2.8046875 px/frame */
#define PLAYER_TERMINAL_FALL_FX 0x0600 /* $80:8D13, 6.0 px/frame */
#define PLAYER_TERMINAL_FALL_WATER_FX 0x0300 /* $80:8D0B, 3.0 px/frame */
#define PLAYER_FLY_UP_FX 0x0200       /* Air/Ultimate Gargoyle & debug B+Up */
#define PLAYER_SHOT_FRAMES 17         /* Y spit: idle + 6 + 10 frames */
#define PLAYER_SPECIAL_FRAMES 31      /* A State 0x16: 11 + 4 + 16 frames */

#define FX_ONE 256
#define FX_TO_FLOAT(v) ((float)(v) / (float)FX_ONE)
#define FLOAT_TO_FX(v) ((int32_t)lroundf((v) * (float)FX_ONE))

/* Set by the first Player_Init that honours DC_START_X/Y; DC_START_ONCE uses
 * it to keep the hook on the boot room only. */
static bool start_hook_used = false;

static const char *const kFormNames[CREST_COUNT] = {
    "FIRE GARGOYLE",
    "EARTH GARGOYLE",
    "AERIAL GARGOYLE",
    "WATER GARGOYLE",
    "TIME GARGOYLE",
    "ULTIMATE GARGOYLE"
};

const char *Player_FormName(int form) {
    if (form < 0 || form >= CREST_COUNT)
        return kFormNames[0];
    return kFormNames[form];
}

void Player_CycleForm(Player *player, int delta) {
    uint8_t mask = player->crests_mask ? player->crests_mask : 0x3F;
    int cur = player->crest_form;
    for (int step = 0; step < CREST_COUNT; step++) {
        cur = (cur + delta + CREST_COUNT) % CREST_COUNT;
        if (mask & (1u << cur)) {
            player->crest_form = cur;
            break;
        }
    }
    if (player->crest_form == CREST_EARTH &&
        (player->state == PLAYER_HOVER || player->state == PLAYER_FLY ||
         player->state == PLAYER_WALL_CLING)) {
        player->state = PLAYER_JUMP;
        player->jump_sub = 4;
    }
}

/* Horizontal/ceiling collision sampled at the upper body only. The feet row
 * is intentionally excluded so a full block the player stands on does not
 * count as a wall; slopes are walkable by definition. */
static bool PlayerCollides(const Level *level, float x, float y) {
    float left = x - PLAYER_HALF_W;
    float right = x + PLAYER_HALF_W;
    float low = y - 3.0f;
    float mid = y - PLAYER_HEIGHT * 0.5f;
    float top = y - PLAYER_HEIGHT + 1.0f;
    return Level_IsWallAt(level, left, low) ||
           Level_IsWallAt(level, right, low) ||
           Level_IsWallAt(level, left, mid) ||
           Level_IsWallAt(level, right, mid) ||
           Level_IsWallAt(level, left, top) ||
           Level_IsWallAt(level, right, top);
}

/* The feet sample is the player's Y line itself. Level_FloorAt applies the
 * $80:962B slope height table for the block under the feet. */
static bool GroundTop(const Level *level, float x, float feet_y, float *top) {
    return Level_FloorAt(level, x, feet_y, top);
}

static void SyncPublic(Player *player) {
    player->x = FX_TO_FLOAT(player->x_fx);
    player->y = FX_TO_FLOAT(player->y_fx);
    player->vy = FX_TO_FLOAT(player->vy_fx);
}

/* $80:8D03 vertical integrator, converted to y-down:
 *   velocity += gravity; clamp at 6 px/frame (3 px/frame underwater);
 *   position += velocity.
 * Landing uses the $80:962B surface height for the cell under the feet. */
static void IntegrateVertical(Player *player, Level *level) {
    int32_t grav = player->underwater ? PLAYER_GRAVITY_WATER_FX
                                      : PLAYER_GRAVITY_FX;
    int32_t term = player->underwater ? PLAYER_TERMINAL_FALL_WATER_FX
                                      : PLAYER_TERMINAL_FALL_FX;
    player->vy_fx += grav;
    if (player->vy_fx > term)
        player->vy_fx = term;
    if (player->vy_fx < -PLAYER_TERMINAL_FALL_FX)
        player->vy_fx = -PLAYER_TERMINAL_FALL_FX;

    int32_t old_y = player->y_fx;
    player->y_fx += player->vy_fx;
    SyncPublic(player);

    if (player->vy_fx > 0) {
        float surface;
        if (Level_FloorAt(level, player->x, player->y, &surface) &&
            surface <= player->y) {
            player->y_fx = FLOAT_TO_FX(surface);
            player->vy_fx = 0;
            player->on_ground = true;
            player->jump_sub = 0;
            player->landed_event = true;
            SyncPublic(player);
            return;
        }
    } else if (player->vy_fx < 0) {
        /* Headbutt ($80:EC20): break destructible ceiling blocks (0x41). */
        if (player->special_timer > 0 || player->dash_timer > 0) {
            if (Level_BreakBlockAt(level, player->x,
                                   player->y - PLAYER_HEIGHT)) {
                player->block_broken_event = true;
            }
        }
        /* Ceiling: stop the ascent without moving into the block. */
        if (PlayerCollides(level, player->x, player->y)) {
            player->y_fx = old_y;
            player->vy_fx = 0;
            SyncPublic(player);
            return;
        }
    }
    player->on_ground = false;
}

/* Horizontal movement is a single 8.8 add per frame ($80:8D35/8D46). The
 * 0.5 px sweep only resolves the native AABB against the 16 px block grid. */
static void MoveHorizontal(Player *player, const Level *level, int dir,
                           int32_t speed_fx) {
    float old_x = FX_TO_FLOAT(player->x_fx);
    if (dir == 0) {
        player->vx = 0.0f;
        return;
    }

    float step = FX_TO_FLOAT(speed_fx) * (float)dir;
    float target = old_x + step;
    if (!PlayerCollides(level, target, player->y)) {
        player->x_fx += dir * speed_fx;
    } else {
        float reached = old_x;
        float dist = fabsf(step);
        for (float d = 0.5f; d <= dist; d += 0.5f) {
            float nx = old_x + copysignf(d, step);
            if (PlayerCollides(level, nx, player->y))
                break;
            reached = nx;
        }
        player->x_fx = FLOAT_TO_FX(reached);
    }

    SyncPublic(player);
    player->vx = FX_TO_FLOAT(player->x_fx) - old_x;
}

/* $80:F065 slope walk: first step from rest is 0x00B3, then $8B85 adds
 * 3/256 px/frame until the 0x0166 cap. The flat-ground path ($80:F031)
 * deliberately leaves $1020 alone, so normal walking is immediate 1.4 px/f.
 * Slope detection ($1070) is wired in Step 5. */
static void UpdateWalkSpeed(Player *player, int dir, int prev_dir) {
    if (!player->on_slope)
        return;

    if (dir == 0) {
        player->walk_speed_fx -= PLAYER_WALK_ACCEL_FX;
        if (player->walk_speed_fx < 0)
            player->walk_speed_fx = 0;
        return;
    }

    if (prev_dir == 0) {
        player->walk_speed_fx = PLAYER_WALK_INITIAL_FX;
    } else {
        player->walk_speed_fx += PLAYER_WALK_ACCEL_FX;
        if (player->walk_speed_fx > PLAYER_WALK_MAX_FX)
            player->walk_speed_fx = PLAYER_WALK_MAX_FX;
    }
}

static int ReadDirection(const Input *input) {
    /* $0091 bits 0/1. Pressing both keeps the original rightward bias. */
    if (input->left && input->right)
        return 1;
    if (input->left)
        return -1;
    if (input->right)
        return 1;
    return 0;
}

static void EnterJump(Player *player, const Level *level) {
    (void)level;
    player->on_ground = false;
    player->wall_cling_dir = 0;
    player->state = PLAYER_JUMP;
    player->jump_sub = 0;
    int32_t jv = player->underwater ? PLAYER_JUMP_WATER_FX : PLAYER_JUMP_FX;
    player->vy_fx = -jv;
    player->walk_speed_fx = player->underwater ? PLAYER_WALK_WATER_FX
                                               : PLAYER_WALK_MAX_FX;
    player->land_timer = 0;
    player->jump_started = true;
    SyncPublic(player);
}

static void EnterHover(Player *player) {
    if (player->crest_form == CREST_EARTH)
        return; /* Earth Gargoyle cannot hover */
    player->state = PLAYER_HOVER;
    player->wall_cling_dir = 0;
    player->jump_sub = 0;
    player->vy_fx = 0;
    player->walk_speed_fx = PLAYER_WALK_MAX_FX;
    SyncPublic(player);
}

void Player_Init(Player *player, const Level *level) {
    memset(player, 0, sizeof(*player));
    const char *demo = getenv("DC_DEMO");
    bool unlock_all = getenv("DC_UNLOCK_ALL") != NULL ||
                      (demo && strcmp(demo, "11") == 0);
    player->x_fx = FLOAT_TO_FX(level->spawn_x);
    player->y_fx = FLOAT_TO_FX(level->spawn_y);
    const char *start_x = getenv("DC_START_X");
    const char *start_y = getenv("DC_START_Y");
    if (start_hook_used && getenv("DC_START_ONCE")) {
        start_x = NULL;
        start_y = NULL;
    }
    if ((start_x && *start_x) || (start_y && *start_y))
        start_hook_used = true;
    if (start_x && *start_x)
        player->x_fx = FLOAT_TO_FX(strtof(start_x, NULL));
    if (start_y && *start_y)
        player->y_fx = FLOAT_TO_FX(strtof(start_y, NULL));
    player->walk_speed_fx = PLAYER_WALK_MAX_FX;
    player->facing = 1;
    player->state = PLAYER_IDLE;
    player->anim_clip = -1;
    player->fly_enabled = getenv("DC_FLY_DEBUG") != NULL;
    player->crest_form = CREST_BASE;
    player->crests_mask = unlock_all ? 0x3F : 0x01;
    player->talisman_mask = 0x1F;
    player->potions = 2;
    player->scrolls = 1;
    const char *gold_env = getenv("DC_GOLD");
    if (gold_env && *gold_env)
        player->gold = atoi(gold_env);
    const char *pot_env = getenv("DC_POTIONS");
    if (pot_env && *pot_env)
        player->potions = atoi(pot_env);
    const char *scroll_env = getenv("DC_SCROLLS");
    if (scroll_env && *scroll_env)
        player->scrolls = atoi(scroll_env);
    player->max_hp = 6;
    player->hp = 4; /* leave room for heart pickups */
    SyncPublic(player);

    /* Robust spawn placement: clamp into the room, escape solid blocks, and
     * snap to the nearest floor. Streamed areas can place spawn records inside
     * decorations, so try a small spiral before giving up. */
    if (player->x < level->play_min_x + 8.0f)
        player->x_fx = FLOAT_TO_FX(level->play_min_x + 8.0f);
    if (player->x > level->play_max_x - 8.0f)
        player->x_fx = FLOAT_TO_FX(level->play_max_x - 8.0f);
    SyncPublic(player);

    static const float kOffsets[] = {0.0f, 16.0f, -16.0f, 32.0f, -32.0f,
                                     48.0f, -48.0f};
    bool found = false;
    for (int attempt = 0; attempt < 12 && !found; attempt++) {
        float base_x = FX_TO_FLOAT(player->x_fx);
        float base_y = FX_TO_FLOAT(player->y_fx) - (float)(attempt / 2) * 16.0f;
        float ox = kOffsets[attempt % 7];
        float x = base_x + ox;
        float y = base_y;
        if (x < level->play_min_x + 6.0f || x > level->play_max_x - 6.0f)
            continue;
        if (PlayerCollides(level, x, y))
            continue;
        player->x_fx = FLOAT_TO_FX(x);
        player->y_fx = FLOAT_TO_FX(y);
        SyncPublic(player);
        found = true;
    }
    if (!found) {
        if (PlayerCollides(level, player->x, player->y)) {
            player->y_fx = (player->y_fx / (level->collision.cell * FX_ONE)) *
                           level->collision.cell * FX_ONE;
            SyncPublic(player);
        }
    }

    float top;
    if (GroundTop(level, player->x, player->y, &top) &&
        top <= player->y + 24.0f && top >= player->y - 24.0f) {
        player->y_fx = FLOAT_TO_FX(top);
        player->on_ground = true;
        SyncPublic(player);
    } else {
        for (int dy = 4; dy <= 96; dy += 4) {
            float probe = player->y + (float)dy;
            if (player->x < level->play_min_x ||
                player->x > level->play_max_x)
                break;
            if (GroundTop(level, player->x, probe, &top) &&
                top >= player->y - 8.0f && top <= probe + 4.0f) {
                player->y_fx = FLOAT_TO_FX(top);
                player->on_ground = true;
                SyncPublic(player);
                break;
            }
        }
    }
}

void Player_Animate(Player *player, const PlayerAnim *anim) {
    if (!anim->ready)
        return;

    AnimClipId clip;
    if (player->hp <= 0) {
        clip = ANIM_DIE;
    } else if (player->knockback_timer > 0) {
        /* Hurt/death are data-driven when the sheet provides a clip; the base
         * captured sheet does not yet have one, so the fallback below keeps
         * the old behaviour instead of freezing. */
        clip = ANIM_HURT;
    } else if (player->special_timer > 0) {
        clip = ANIM_SPELL;
    } else if (player->shot_timer > 0) {
        clip = ANIM_ATTACK;
    } else {
        switch (player->state) {
        case PLAYER_WALK:
        case PLAYER_HEADBUTT:
            clip = ANIM_WALK;
            break;
        case PLAYER_JUMP:
            /* The recovered state machine separates rise and fall; hover is
             * a distinct State 0x06 before the fall gets here. */
            clip = player->vy_fx < 0 ? ANIM_JUMP : ANIM_FALL;
            break;
        case PLAYER_HOVER:
            clip = ANIM_HOVER;
            break;
        case PLAYER_FLY:
            clip = anim->clips[ANIM_FLYING].step_count > 0
                       ? ANIM_FLYING
                       : ANIM_HOVER;
            break;
        case PLAYER_HURT:
            clip = ANIM_HURT;
            break;
        case PLAYER_DEAD:
            clip = ANIM_DIE;
            break;
        case PLAYER_WALL_CLING:
            clip = ANIM_JUMP;
            break;
        case PLAYER_LAND:
            clip = ANIM_LAND;
            break;
        default:
            clip = ANIM_IDLE;
            break;
        }
    }

    const AnimClip *c = &anim->clips[clip];
    /* A form sheet may be missing a clip (for example the ripped form sheets
     * have no spell row). Fall through to the closest available animation
     * instead of silently showing idle. */
    if (c->step_count <= 0) {
        if (clip == ANIM_SPELL &&
            anim->clips[ANIM_ATTACK].step_count > 0)
            clip = ANIM_ATTACK;
        else if (clip == ANIM_FLYING &&
                 anim->clips[ANIM_HOVER].step_count > 0)
            clip = ANIM_HOVER;
        else if (clip == ANIM_DIE) {
            clip = anim->clips[ANIM_HURT].step_count > 0
                       ? ANIM_HURT
                       : ANIM_IDLE;
        } else if (clip == ANIM_HURT &&
                   anim->clips[ANIM_IDLE].step_count > 0)
            clip = ANIM_IDLE;
        else
            clip = ANIM_IDLE;
        c = &anim->clips[clip];
    }
    if (!anim->ready || c->step_count <= 0)
        return;

    if (player->anim_clip != (int)clip) {
        player->anim_clip = (int)clip;
        player->anim_step = 0;
        player->anim_timer = 0;
    }
    if (c->step_count <= 1) {
        player->anim_step = 0;
        return;
    }

    /* Switching form/animation can leave a step index from the previous
     * clip; clamp before indexing the steps array. */
    if (player->anim_step < 0)
        player->anim_step = 0;
    if (player->anim_step >= c->step_count)
        player->anim_step = c->step_count - 1;

    const AnimStep *step = &anim->steps[c->first_step + player->anim_step];
    player->anim_timer++;
    if (player->anim_timer < step->duration)
        return;

    player->anim_timer = 0;
    player->anim_step++;
    if (player->anim_step >= c->step_count) {
        if (c->loop)
            player->anim_step = 0;
        else
            player->anim_step = c->step_count - 1;
    }
}

void Player_Update(Player *player, Level *level, const Input *input) {
    player->shot_fired = false;
    player->jump_started = false;
    player->landed_event = false;
    player->hurt_event = false;
    player->block_broken_event = false;

    if (player->hp <= 0) {
        player->state = PLAYER_DEAD;
        player->vx = 0.0f;
        player->vy = 0.0f;
        return;
    }

    if (input->form_next_pressed)
        Player_CycleForm(player, 1);

    if (player->special_timer > 0)
        player->special_timer--;
    if (player->shot_timer > 0)
        player->shot_timer--;
    if (player->land_timer > 0)
        player->land_timer--;
    if (player->invuln_timer > 0)
        player->invuln_timer--;
    if (player->dash_timer > 0)
        player->dash_timer--;

    /* $80:DF82 ($1070) slope-ramp and $80:94AB ($1045) underwater probes. */
    player->on_slope = player->on_ground &&
                       Level_IsSlopeRampAt(level, player->x, player->y + 1.0f);
    player->underwater = Level_IsWaterAt(level, player->x, player->y - 8.0f) ||
                         (getenv("DC_UNDERWATER") != NULL);

    /* $80:DEA5: terrain hazard (attr & 0xE0 == 0x20, e.g. spikes 0x21). */
    if (player->invuln_timer == 0 &&
        (Level_IsHazardAt(level, player->x, player->y) ||
         Level_IsHazardAt(level, player->x, player->y - 10.0f))) {
        if (player->hp > 0)
            player->hp--;
        player->invuln_timer = 60;
        player->knockback_timer = 8;
        player->knockback_dir = -player->facing;
        player->hurt_event = true;
    }

    if (input->special_pressed && player->special_timer == 0) {
        player->special_timer = PLAYER_SPECIAL_FRAMES;
        if (player->on_ground &&
            (player->crest_form == CREST_EARTH ||
             player->crest_form == CREST_ULTIMATE)) {
            player->dash_timer = 18;
            player->state = PLAYER_HEADBUTT;
        } else if (!player->on_ground) {
            /* Overhead headbutt ($80:EC20): break 0x41 blocks above head. */
            if (Level_BreakBlockAt(level, player->x,
                                   player->y - PLAYER_HEIGHT - 2.0f)) {
                player->block_broken_event = true;
            }
        }
    }
    if (input->shot_pressed && player->shot_timer == 0) {
        player->shot_timer = PLAYER_SHOT_FRAMES;
        player->shot_fired = true;
    }

    bool can_free_fly = player->fly_enabled ||
                        player->crest_form == CREST_AIR ||
                        player->crest_form == CREST_ULTIMATE;
    bool can_swim = player->underwater &&
                    (player->crest_form == CREST_WATER ||
                     player->crest_form == CREST_ULTIMATE);

    int dir = ReadDirection(input);
    if (player->knockback_timer > 0) {
        player->knockback_timer--;
        dir = player->knockback_dir;
        MoveHorizontal(player, level, dir, 0x0200);
    } else if (player->dash_timer > 0) {
        /* Earth/Ultimate shoulder tackle breaks 0x41 blocks ahead. */
        float ahead_x = player->x + (float)player->facing * (PLAYER_HALF_W + 4.0f);
        if (Level_BreakBlockAt(level, ahead_x, player->y - 8.0f) ||
            Level_BreakBlockAt(level, ahead_x, player->y - 18.0f)) {
            player->block_broken_event = true;
        }
        MoveHorizontal(player, level, player->facing, PLAYER_EARTH_DASH_FX);
    } else if (player->state == PLAYER_WALL_CLING) {
        player->vx = 0.0f;
    } else {
        if (dir != 0)
            player->facing = dir;
        if (player->underwater && !can_swim)
            player->walk_speed_fx = PLAYER_WALK_WATER_FX;
        else if (!player->on_slope)
            player->walk_speed_fx = PLAYER_WALK_MAX_FX;
        UpdateWalkSpeed(player, dir, player->prev_dir);
        MoveHorizontal(player, level, dir, player->walk_speed_fx);
    }
    player->prev_dir = dir;

    if (can_swim) {
        int vdir = (input->down ? 1 : 0) - (input->up ? 1 : 0);
        player->vy_fx = vdir * 0x0180;
        if (vdir != 0) {
            player->on_ground = false;
            player->state = PLAYER_HOVER;
            IntegrateVertical(player, level);
            goto clamp_bounds;
        }
    }

    bool grounded_at_start = player->on_ground;
    if (grounded_at_start) {
        float top = 0.0f;
        bool supported = GroundTop(level, player->x, player->y, &top);
        /* A surface more than a few pixels below the feet means we walked
         * off a ledge; let State 0x04 start falling instead of snapping. */
        if (supported && top > player->y + 6.0f)
            supported = false;
        if (!supported) {
            /* Walked off the block edge: State 0x04 begins falling. */
            player->on_ground = false;
            player->state = PLAYER_JUMP;
            player->jump_sub = 4;
            player->vy_fx = 0;
            IntegrateVertical(player, level);
        } else {
            player->y_fx = FLOAT_TO_FX(top);
            player->vy_fx = 0;
            SyncPublic(player);

            if (input->jump_pressed) {
                EnterJump(player, level);
            } else if (player->dash_timer > 0) {
                player->state = PLAYER_HEADBUTT;
            } else if (dir != 0) {
                player->state = PLAYER_WALK;
            } else if (player->land_timer > 0) {
                player->state = PLAYER_LAND;
            } else {
                player->state = PLAYER_IDLE;
            }
        }
    } else {
        if (player->state == PLAYER_WALL_CLING) {
            /* $80:E3FD: the cling slides. $22 += 3 per frame, capped at
             * 0x00C0 (0.75 px/frame); the ROM does not freeze the player. */
            player->vy_fx += 0x0003;
            if (player->vy_fx > 0x00C0)
                player->vy_fx = 0x00C0;
            int32_t old_y = player->y_fx;
            player->y_fx += player->vy_fx;
            SyncPublic(player);
            if (PlayerCollides(level, player->x, player->y)) {
                player->y_fx = old_y;
                player->vy_fx = 0;
                SyncPublic(player);
            }
            float wall_x = player->x + (float)player->wall_cling_dir * (PLAYER_HALF_W + 1.0f);
            if (!Level_IsWallAt(level, wall_x, player->y - 10.0f)) {
                player->state = PLAYER_JUMP;
                player->jump_sub = 4;
                player->wall_cling_dir = 0;
            } else if (input->jump_pressed) {
                player->facing = -player->wall_cling_dir;
                EnterJump(player, level);
            } else if (input->down) {
                player->state = PLAYER_JUMP;
                player->jump_sub = 4;
                player->wall_cling_dir = 0;
            }
        } else if (player->state == PLAYER_HOVER || player->state == PLAYER_FLY) {
            if (input->jump_pressed) {
                /* $80:E2DF: B exits State 0x06 into State 0x04/0x04. */
                player->state = PLAYER_JUMP;
                player->jump_sub = 4;
                player->vy_fx = 0;
            } else if (can_free_fly && input->up) {
                player->state = PLAYER_FLY;
                player->vy_fx = -PLAYER_FLY_UP_FX;
                int32_t old_y = player->y_fx;
                player->y_fx += player->vy_fx;
                SyncPublic(player);
                if (PlayerCollides(level, player->x, player->y)) {
                    player->y_fx = old_y;
                    player->vy_fx = 0;
                    SyncPublic(player);
                }
            } else {
                player->state = PLAYER_HOVER;
            }
        } else {
            /* State 0x04: substate 0 and 2 advance first, then integrate.
             * Substate 4 applies the $80:E227 B-release cut before gravity. */
            if (player->jump_sub == 0) {
                player->jump_sub = 2;
                IntegrateVertical(player, level);
            } else if (player->jump_sub == 2) {
                player->jump_sub = 4;
                IntegrateVertical(player, level);
            } else if (player->jump_sub == 4 && input->jump_pressed &&
                       player->crest_form != CREST_EARTH) {
                EnterHover(player);
            } else {
                player->jump_sub = 4;
                if (player->vy_fx < 0 && !input->jump_held)
                    player->vy_fx = 0;
                IntegrateVertical(player, level);
            }

            /* $80:E389 Wall Cling (State 0x08): automatic while descending
             * against a tall wall (solid at body and overhead) with the
             * direction held. The ROM does not require A: its handler only
             * probes the two walls, slides, jumps on B and releases on Down. */
            if (!player->on_ground && player->vy_fx > 0 && dir != 0 &&
                player->crest_form != CREST_EARTH &&
                player->crest_form != CREST_WATER) {
                float wall_x = player->x + (float)dir * (PLAYER_HALF_W + 1.0f);
                if (Level_IsWallAt(level, wall_x, player->y - 10.0f) &&
                    Level_IsWallAt(level, wall_x, player->y - 28.0f)) {
                    player->state = PLAYER_WALL_CLING;
                    player->wall_cling_dir = dir;
                    player->vy_fx = 0;
                    SyncPublic(player);
                }
            }

            if (player->on_ground) {
                player->state = PLAYER_LAND;
                player->land_timer = 8;
            } else if (player->state != PLAYER_HOVER &&
                       player->state != PLAYER_FLY &&
                       player->state != PLAYER_WALL_CLING) {
                player->state = PLAYER_JUMP;
            }
        }
    }

clamp_bounds:
    /* Keep Firebrand inside the current room bounds. */
    if (player->x < level->play_min_x) {
        player->x_fx = FLOAT_TO_FX(level->play_min_x);
        player->vx = 0.0f;
    }
    if (player->x > level->play_max_x) {
        player->x_fx = FLOAT_TO_FX(level->play_max_x);
        player->vx = 0.0f;
    }
    if (player->y < level->play_min_y) {
        player->y_fx = FLOAT_TO_FX(level->play_min_y);
        player->vy_fx = 0;
    }
    if (player->y > level->play_max_y) {
        player->y_fx = FLOAT_TO_FX(level->play_max_y);
        player->vy_fx = 0;
        player->on_ground = true;
    }
    SyncPublic(player);

    player->anim_time += 1.0f / 60.0f;
}
