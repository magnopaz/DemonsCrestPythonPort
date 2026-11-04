#include "input.h"

#include <stdlib.h>

#include "raylib.h"

static bool PadDown(int button) {
    return IsGamepadAvailable(0) && IsGamepadButtonDown(0, button);
}

void Input_Read(Input *in, InputState *st) {
    static int demo_mode = -1;
    static int debug_env = -1;
    static int demo_frame = 0;
    if (demo_mode < 0) {
        const char *env = getenv("DC_DEMO");
        demo_mode = env ? atoi(env) : 0;
    }
    if (debug_env < 0) {
        const char *env = getenv("DC_DEBUG_COLLISION");
        debug_env = env ? atoi(env) : 0;
    }

    /* Left stick mirrors the d-pad when pushed past a small dead zone. */
    float stick_x = IsGamepadAvailable(0)
                        ? GetGamepadAxisMovement(0, GAMEPAD_AXIS_LEFT_X) : 0.0f;
    float stick_y = IsGamepadAvailable(0)
                        ? GetGamepadAxisMovement(0, GAMEPAD_AXIS_LEFT_Y) : 0.0f;
    /* Deterministic runs (DC_RUN_FRAMES) must not see physical devices: a held
     * key or a drifting analog stick used to perturb demo scripts. */
    static int deterministic = -1;
    if (deterministic < 0)
        deterministic = getenv("DC_RUN_FRAMES") != NULL;
    if (deterministic && demo_mode == 0) {
        /* Still allow explicit demo scripts below; zero the device state. */
    }
    bool left = !deterministic && (IsKeyDown(KEY_LEFT) || IsKeyDown(KEY_A) ||
                PadDown(GAMEPAD_BUTTON_LEFT_FACE_LEFT)) ||
                (!deterministic && stick_x < -0.35f);
    bool right = (!deterministic && (IsKeyDown(KEY_RIGHT) || IsKeyDown(KEY_D) ||
                  PadDown(GAMEPAD_BUTTON_LEFT_FACE_RIGHT))) ||
                 (!deterministic && stick_x > 0.35f);
    bool up = (!deterministic && (IsKeyDown(KEY_UP) || IsKeyDown(KEY_W) ||
               PadDown(GAMEPAD_BUTTON_LEFT_FACE_UP))) ||
              (!deterministic && stick_y < -0.35f);
    bool down = (!deterministic && (IsKeyDown(KEY_DOWN) || IsKeyDown(KEY_S) ||
                  PadDown(GAMEPAD_BUTTON_LEFT_FACE_DOWN))) ||
                (!deterministic && stick_y > 0.35f);
    bool jump = !deterministic &&
                (IsKeyDown(KEY_Z) || IsKeyDown(KEY_SPACE) ||
                 PadDown(GAMEPAD_BUTTON_RIGHT_FACE_RIGHT)); /* SNES B */
    /* SNES Y ($1E3C -> $105B/$105C) is the Fireball shot. Keyboard X/J and
     * the west/top gamepad faces mirror the original Y button. */
    bool shot = !deterministic &&
                (IsKeyDown(KEY_X) || IsKeyDown(KEY_J) ||
                 PadDown(GAMEPAD_BUTTON_RIGHT_FACE_LEFT) ||
                 PadDown(GAMEPAD_BUTTON_RIGHT_FACE_UP));
    /* SNES A ($1E3E -> $105D/$105E) is Talisman/Headbutt, not the shot. */
    bool special = !deterministic &&
                   (IsKeyDown(KEY_C) || IsKeyDown(KEY_K) ||
                    PadDown(GAMEPAD_BUTTON_RIGHT_FACE_DOWN));
    /* SNES X ($1E4C -> $80:DC12) opens the Crest/Item subscreen. */
    bool subscreen = !deterministic &&
                     (IsKeyDown(KEY_TAB) || IsKeyDown(KEY_I) ||
                      IsKeyDown(KEY_V) ||
                      PadDown(GAMEPAD_BUTTON_LEFT_TRIGGER_2) ||
                      PadDown(GAMEPAD_BUTTON_RIGHT_THUMB));
    bool form_next = !deterministic &&
                     (IsKeyDown(KEY_Q) || IsKeyDown(KEY_E) ||
                      PadDown(GAMEPAD_BUTTON_LEFT_TRIGGER_1) ||
                      PadDown(GAMEPAD_BUTTON_RIGHT_TRIGGER_1));
    bool start = !deterministic && (IsKeyDown(KEY_ENTER) ||
                 PadDown(GAMEPAD_BUTTON_MIDDLE_RIGHT));
    bool pause = !deterministic && (IsKeyDown(KEY_ESCAPE) ||
                 PadDown(GAMEPAD_BUTTON_MIDDLE_LEFT));
    bool debug = IsKeyDown(KEY_F1) || (debug_env > 0);

    /* Deterministic input for screenshots/regressions. */
    if (demo_mode == 1) {
        demo_frame++;
        right = demo_frame > 30 && demo_frame < 210;
        jump = (demo_frame >= 90 && demo_frame < 130) ||
               (demo_frame >= 160 && demo_frame < 200);
        up = demo_frame >= 165 && demo_frame < 200;
    } else if (demo_mode == 2) {
        demo_frame++;
        right = demo_frame > 30 && demo_frame < 90;
        jump = demo_frame >= 90 && demo_frame < 120;
    } else if (demo_mode == 3) {
        /* Mirrors tools/oracle/oracle_physics.script after its 600-frame
         * landing settle: idle 120, right 30, left 30, jump, jump-hold,
         * moving jump. */
        demo_frame++;
        right = (demo_frame >= 120 && demo_frame < 150) ||
                (demo_frame >= 488 && demo_frame < 546);
        left = demo_frame >= 210 && demo_frame < 240;
        jump = (demo_frame >= 300 && demo_frame < 308) ||
               (demo_frame >= 368 && demo_frame < 428) ||
               (demo_frame >= 488 && demo_frame < 496);
        up = demo_frame >= 488 && demo_frame < 496;
    } else if (demo_mode == 4) {
        /* Tap-jump vs hold-jump comparison. */
        demo_frame++;
        jump = (demo_frame >= 30 && demo_frame < 31) ||
               (demo_frame >= 100 && demo_frame < 130);
    } else if (demo_mode == 5) {
        /* Animation regression: walk, special, jump, then fly upward. */
        demo_frame++;
        right = demo_frame >= 20 && demo_frame < 70;
        special = (demo_frame >= 85 && demo_frame < 86) ||
                  (demo_frame >= 160 && demo_frame < 161);
        jump = demo_frame >= 110 && demo_frame < 150;
        up = demo_frame >= 120 && demo_frame < 150;
    } else if (demo_mode == 6) {
        /* Step 3 physics oracle replay from save0 (capture_anim.py frames
         * 20614..21216). demo_frame is one ahead of the trace frame. */
        demo_frame++;
        right = demo_frame >= 31 && demo_frame < 42;
        left = demo_frame >= 332 && demo_frame < 343;
        jump = (demo_frame >= 63 && demo_frame < 65) ||
               (demo_frame >= 108 && demo_frame < 155) ||
               (demo_frame >= 202 && demo_frame < 228) ||
               (demo_frame >= 230 && demo_frame < 231) ||
               (demo_frame >= 263 && demo_frame < 264) ||
               (demo_frame >= 359 && demo_frame < 361) ||
               (demo_frame >= 404 && demo_frame < 451);
    } else if (demo_mode == 7) {
        /* Projectile regression: shoot right into the pillar, then left. */
        demo_frame++;
        right = demo_frame >= 20 && demo_frame < 45;
        shot = demo_frame == 50 || demo_frame == 68 || demo_frame == 86;
        left = demo_frame >= 110 && demo_frame < 140;
        shot = shot || demo_frame == 150 || demo_frame == 168;
    } else if (demo_mode == 40) {
        /* Wall-cling probe: spawn beside a tall wall (area 3, the column at
         * x=336..351) and press into it while falling. The ROM clings on
         * contact and slides; B jumps off, Down releases. */
        demo_frame++;
        left = demo_frame >= 5;
    } else if (demo_mode == 41) {
        /* Up-door probe: stand on the door and tap up at frame 20, the way
         * the stage II take does (position from DC_START_X/DC_START_Y). */
        demo_frame++;
        up = demo_frame >= 20 && demo_frame < 22;
    } else if (demo_mode == 42) {
        /* Death hub, RETRY: the menu opens ~90 frames after the kill. */
        demo_frame++;
        start = demo_frame == 140;
    } else if (demo_mode == 43) {
        /* Death hub, SELECT A STAGE: one down, then start. */
        demo_frame++;
        down = demo_frame == 20;
        start = demo_frame == 40;
    } else if (demo_mode == 44) {
        /* Death hub, END: two downs, then start. */
        demo_frame++;
        down = demo_frame == 20 || demo_frame == 30;
        start = demo_frame == 50;
    } else if (demo_mode == 45) {
        /* Death hub, END then leave the PASS WORD screen: the second start
         * must open the map. */
        demo_frame++;
        down = demo_frame == 20 || demo_frame == 30;
        start = demo_frame == 50 || demo_frame == 110;
    } else if (demo_mode == 36) {
        /* Navigation: walk right through a door merged from the level saves. */
        demo_frame++;
        right = demo_frame >= 5;
    } else if (demo_mode == 35) {
        /* Shop purchase: select ELIXIR (three downs) and buy it. */
        demo_frame++;
        down = demo_frame == 10 || demo_frame == 14 || demo_frame == 18;
        start = demo_frame == 30;
    } else if (demo_mode == 34) {
        /* City NPC conversation: A opens it, Enter pages through it. */
        demo_frame++;
        special = demo_frame == 30;
        start = demo_frame == 45 || demo_frame == 60 || demo_frame == 75;
    } else if (demo_mode == 8) {
        /* Full-room traversal: walk left, then hover right across pillars. */
        demo_frame++;
        left = demo_frame >= 20 && demo_frame < 220;
        right = demo_frame >= 260 && demo_frame < 1200;
        jump = (demo_frame >= 260 && demo_frame < 285) ||
               (demo_frame >= 286 && demo_frame < 287) ||
               (demo_frame >= 1000 && demo_frame < 1001);
    } else if (demo_mode == 9) {
        /* Urn + pickup regression: shoot the urn, then jump to collect the
         * bouncing heart after it lands on the pillar. */
        demo_frame++;
        right = (demo_frame >= 20 && demo_frame < 40) ||
                (demo_frame >= 95 && demo_frame < 135);
        jump = (demo_frame >= 45 && demo_frame < 70) ||
               (demo_frame >= 95 && demo_frame < 125);
        shot = demo_frame >= 52 && demo_frame < 54;
    } else if (demo_mode == 10) {
        /* Enemy regression: pair with DC_START_X near an Area 1 species $67. */
        demo_frame++;
        int phase = demo_frame - 60;
        shot = phase >= 0 && (phase % 20) < 2;
    } else if (demo_mode == 11) {
        /* Campaign systems regression: cycle Crest forms (Earth dash, Air
         * free flight, Water/Time/Ultimate), headbutt/tackle, and subscreen. */
        demo_frame++;
        form_next = (demo_frame == 10 || demo_frame == 40 ||
                     demo_frame == 90 || demo_frame == 120 ||
                     demo_frame == 140);
        right = (demo_frame >= 15 && demo_frame < 35) ||
                (demo_frame >= 95 && demo_frame < 170);
        special = (demo_frame == 18 || demo_frame == 150);
        jump = (demo_frame >= 45 && demo_frame < 85);
        up = (demo_frame >= 55 && demo_frame < 85);
        shot = (demo_frame == 100 || demo_frame == 155);
    } else if (demo_mode == 12) {
        /* Campaign traversal: walk right across areas, shooting enemies. */
        demo_frame++;
        right = demo_frame >= 20;
        shot = demo_frame >= 40 && (demo_frame % 24) < 2;
        jump = (demo_frame % 180) >= 120 && (demo_frame % 180) < 150;
    } else if (demo_mode == 33) {
        /* Attract cancel: let the title demo start, then press Start. */
        demo_frame++;
        start = demo_frame == 640;
    } else if (demo_mode == 32) {
        /* Pause menu: pick SAVE and confirm. */
        demo_frame++;
        down = demo_frame == 2;
        start = demo_frame == 6;
    } else if (demo_mode == 31) {
        /* Overworld landing: confirm the node under the ship. */
        demo_frame++;
        start = demo_frame == 4;
    } else if (demo_mode == 30) {
        /* Stage-select travel: open the list, move down twice, confirm. */
        demo_frame++;
        subscreen = demo_frame == 3;
        down = demo_frame == 6 || demo_frame == 8;
        start = demo_frame == 12;
    } else if (demo_mode == 15) {
        /* MVP 2: a straight run through the cemetery. Walk right, jump the
         * gaps, and fire in bursts so the skeletons and ghouls get engaged. */
        demo_frame++;
        int ph = demo_frame % 240;
        right = (demo_frame > 10);
        jump = (ph == 30) || (ph == 40);
        shot = (demo_frame % 26) == 0 && demo_frame > 30;
    } else if (demo_mode == 14) {
        /* Somulo MVP: he now starts near the player and follows, so the script
         * closes in, shoots the lowered head every 40 frames (the hurt flash
         * lasts 32), then walks to the gate. */
        demo_frame++;
        right = (demo_frame >= 20 && demo_frame < 130) ||
                (demo_frame >= 620 && demo_frame < 1120);
        shot = demo_frame >= 150 && demo_frame < 560 &&
               (demo_frame % 40) == 0;
        } else if (demo_mode == 13) {
        /* Title-menu flow: confirm NEW GAME, then walk right. */
        demo_frame++;
        start = demo_frame == 5;
        right = demo_frame >= 20;
        shot = demo_frame >= 60 && (demo_frame % 24) < 2;
    }

    in->left = left;
    in->right = right;
    in->up = up;
    in->down = down;
    in->jump_held = jump;
    in->jump_pressed = jump && !st->prev_jump;
    in->shot_held = shot;
    in->shot_pressed = shot && !st->prev_shot;
    in->special_held = special;
    in->special_pressed = special && !st->prev_special;
    in->subscreen_pressed = subscreen && !st->prev_subscreen;
    in->form_next_pressed = form_next && !st->prev_form_next;
    in->start_pressed = start && !st->prev_start;
    in->pause_pressed = pause && !st->prev_pause;
    in->debug_collision = debug;

    st->prev_jump = jump;
    st->prev_shot = shot;
    st->prev_special = special;
    st->prev_subscreen = subscreen;
    st->prev_form_next = form_next;
    st->prev_start = start;
    st->prev_pause = pause;
    st->prev_debug = debug;
}
