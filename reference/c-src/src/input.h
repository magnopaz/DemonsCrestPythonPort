#ifndef DC_INPUT_H
#define DC_INPUT_H

#include <stdbool.h>

typedef struct Input {
    bool left;
    bool right;
    bool up;
    bool down;
    bool jump_pressed;
    bool jump_held;
    bool shot_pressed;   /* SNES Y ($105C): Fireball */
    bool shot_held;
    bool special_pressed; /* SNES A ($105E): Talisman / Headbutt */
    bool special_held;
    bool subscreen_pressed; /* SNES X ($1E4C -> $80:DC12): Crest/Item menu */
    bool form_next_pressed; /* L/R quick Crest form cycle */
    bool start_pressed;
    bool pause_pressed;
    bool debug_collision;
} Input;

typedef struct InputState {
    bool prev_jump;
    bool prev_shot;
    bool prev_special;
    bool prev_subscreen;
    bool prev_form_next;
    bool prev_start;
    bool prev_pause;
    bool prev_debug;
} InputState;

void Input_Read(Input *input, InputState *state);

#endif
