"""Keyboard/gamepad input plus the deterministic DC_DEMO scripts (input.c)."""

from __future__ import annotations

import os

from . import rl
from .util import env, env_int


class Input:
    __slots__ = ("left", "right", "up", "down", "jump_pressed", "jump_held",
                 "shot_pressed", "shot_held", "special_pressed",
                 "special_held", "subscreen_pressed", "form_next_pressed",
                 "start_pressed", "pause_pressed", "debug_collision")

    def __init__(self):
        self.left = False
        self.right = False
        self.up = False
        self.down = False
        self.jump_pressed = False
        self.jump_held = False
        self.shot_pressed = False
        self.shot_held = False
        self.special_pressed = False
        self.special_held = False
        self.subscreen_pressed = False
        self.form_next_pressed = False
        self.start_pressed = False
        self.pause_pressed = False
        self.debug_collision = False


class InputState:
    __slots__ = ("prev_jump", "prev_shot", "prev_special", "prev_subscreen",
                 "prev_form_next", "prev_start", "prev_pause", "prev_debug")

    def __init__(self):
        self.prev_jump = False
        self.prev_shot = False
        self.prev_special = False
        self.prev_subscreen = False
        self.prev_form_next = False
        self.prev_start = False
        self.prev_pause = False
        self.prev_debug = False


_demo_mode = None
_debug_env = None
_demo_frame = 0
_deterministic = None


def _pad_down(button: int) -> bool:
    return rl.IsGamepadAvailable(0) and rl.IsGamepadButtonDown(0, button)


def input_read(inp: Input, st: InputState) -> None:
    global _demo_mode, _debug_env, _demo_frame, _deterministic
    if _demo_mode is None:
        _demo_mode = env_int("DC_DEMO") or 0
    if _debug_env is None:
        _debug_env = env_int("DC_DEBUG_COLLISION") or 0
    if _deterministic is None:
        _deterministic = "DC_RUN_FRAMES" in os.environ

    deterministic = _deterministic
    stick_x = rl.GetGamepadAxisMovement(0, rl.GAMEPAD_AXIS_LEFT_X) \
        if rl.IsGamepadAvailable(0) else 0.0
    stick_y = rl.GetGamepadAxisMovement(0, rl.GAMEPAD_AXIS_LEFT_Y) \
        if rl.IsGamepadAvailable(0) else 0.0

    left = (not deterministic and (rl.IsKeyDown(rl.KEY_LEFT) or
                                   rl.IsKeyDown(rl.KEY_A) or
                                   _pad_down(rl.GAMEPAD_BUTTON_LEFT_FACE_LEFT))) or \
           (not deterministic and stick_x < -0.35)
    right = (not deterministic and (rl.IsKeyDown(rl.KEY_RIGHT) or
                                    rl.IsKeyDown(rl.KEY_D) or
                                    _pad_down(rl.GAMEPAD_BUTTON_LEFT_FACE_RIGHT))) or \
            (not deterministic and stick_x > 0.35)
    up = (not deterministic and (rl.IsKeyDown(rl.KEY_UP) or
                                 rl.IsKeyDown(rl.KEY_W) or
                                 _pad_down(rl.GAMEPAD_BUTTON_LEFT_FACE_UP))) or \
         (not deterministic and stick_y < -0.35)
    down = (not deterministic and (rl.IsKeyDown(rl.KEY_DOWN) or
                                   rl.IsKeyDown(rl.KEY_S) or
                                   _pad_down(rl.GAMEPAD_BUTTON_LEFT_FACE_DOWN))) or \
           (not deterministic and stick_y > 0.35)
    jump = not deterministic and (rl.IsKeyDown(rl.KEY_Z) or
                                  rl.IsKeyDown(rl.KEY_SPACE) or
                                  _pad_down(rl.GAMEPAD_BUTTON_RIGHT_FACE_RIGHT))
    shot = not deterministic and (rl.IsKeyDown(rl.KEY_X) or
                                  rl.IsKeyDown(rl.KEY_J) or
                                  _pad_down(rl.GAMEPAD_BUTTON_RIGHT_FACE_LEFT) or
                                  _pad_down(rl.GAMEPAD_BUTTON_RIGHT_FACE_UP))
    special = not deterministic and (rl.IsKeyDown(rl.KEY_C) or
                                     rl.IsKeyDown(rl.KEY_K) or
                                     _pad_down(rl.GAMEPAD_BUTTON_RIGHT_FACE_DOWN))
    subscreen = not deterministic and (
        rl.IsKeyDown(rl.KEY_TAB) or rl.IsKeyDown(rl.KEY_I) or
        rl.IsKeyDown(rl.KEY_V) or
        _pad_down(rl.GAMEPAD_BUTTON_LEFT_TRIGGER_2) or
        _pad_down(rl.GAMEPAD_BUTTON_RIGHT_THUMB))
    form_next = not deterministic and (
        rl.IsKeyDown(rl.KEY_Q) or rl.IsKeyDown(rl.KEY_E) or
        _pad_down(rl.GAMEPAD_BUTTON_LEFT_TRIGGER_1) or
        _pad_down(rl.GAMEPAD_BUTTON_RIGHT_TRIGGER_1))
    start = not deterministic and (rl.IsKeyDown(rl.KEY_ENTER) or
                                   _pad_down(rl.GAMEPAD_BUTTON_MIDDLE_RIGHT))
    pause = not deterministic and (rl.IsKeyDown(rl.KEY_ESCAPE) or
                                   _pad_down(rl.GAMEPAD_BUTTON_MIDDLE_LEFT))
    debug = rl.IsKeyDown(rl.KEY_F1) or (_debug_env or 0) > 0

    mode = _demo_mode
    if mode == 1:
        _demo_frame += 1
        right = 30 < _demo_frame < 210
        jump = (90 <= _demo_frame < 130) or (160 <= _demo_frame < 200)
        up = 165 <= _demo_frame < 200
    elif mode == 2:
        _demo_frame += 1
        right = 30 < _demo_frame < 90
        jump = 90 <= _demo_frame < 120
    elif mode == 3:
        _demo_frame += 1
        right = (120 <= _demo_frame < 150) or (488 <= _demo_frame < 546)
        left = 210 <= _demo_frame < 240
        jump = (300 <= _demo_frame < 308) or (368 <= _demo_frame < 428) or \
               (488 <= _demo_frame < 496)
        up = 488 <= _demo_frame < 496
    elif mode == 4:
        _demo_frame += 1
        jump = (30 <= _demo_frame < 31) or (100 <= _demo_frame < 130)
    elif mode == 5:
        _demo_frame += 1
        right = 20 <= _demo_frame < 70
        special = (85 <= _demo_frame < 86) or (160 <= _demo_frame < 161)
        jump = 110 <= _demo_frame < 150
        up = 120 <= _demo_frame < 150
    elif mode == 6:
        _demo_frame += 1
        right = 31 <= _demo_frame < 42
        left = 332 <= _demo_frame < 343
        jump = ((63 <= _demo_frame < 65) or (108 <= _demo_frame < 155) or
                (202 <= _demo_frame < 228) or (230 <= _demo_frame < 231) or
                (263 <= _demo_frame < 264) or (359 <= _demo_frame < 361) or
                (404 <= _demo_frame < 451))
    elif mode == 7:
        _demo_frame += 1
        right = 20 <= _demo_frame < 45
        shot = _demo_frame in (50, 68, 86)
        left = 110 <= _demo_frame < 140
        shot = shot or _demo_frame in (150, 168)
    elif mode == 40:
        _demo_frame += 1
        left = _demo_frame >= 5
    elif mode == 36:
        _demo_frame += 1
        right = _demo_frame >= 5
    elif mode == 35:
        _demo_frame += 1
        down = _demo_frame in (10, 14, 18)
        start = _demo_frame == 30
    elif mode == 34:
        _demo_frame += 1
        special = _demo_frame == 30
        start = _demo_frame in (45, 60, 75)
    elif mode == 8:
        _demo_frame += 1
        left = 20 <= _demo_frame < 220
        right = 260 <= _demo_frame < 1200
        jump = (260 <= _demo_frame < 285) or (286 <= _demo_frame < 287) or \
               (1000 <= _demo_frame < 1001)
    elif mode == 9:
        _demo_frame += 1
        right = (20 <= _demo_frame < 40) or (95 <= _demo_frame < 135)
        jump = (45 <= _demo_frame < 70) or (95 <= _demo_frame < 125)
        shot = 52 <= _demo_frame < 54
    elif mode == 10:
        _demo_frame += 1
        phase = _demo_frame - 60
        shot = phase >= 0 and (phase % 20) < 2
    elif mode == 11:
        _demo_frame += 1
        form_next = _demo_frame in (10, 40, 90, 120, 140)
        right = (15 <= _demo_frame < 35) or (95 <= _demo_frame < 170)
        special = _demo_frame in (18, 150)
        jump = 45 <= _demo_frame < 85
        up = 55 <= _demo_frame < 85
        shot = _demo_frame in (100, 155)
    elif mode == 12:
        _demo_frame += 1
        right = _demo_frame >= 20
        shot = _demo_frame >= 40 and (_demo_frame % 24) < 2
        jump = (_demo_frame % 180) >= 120 and (_demo_frame % 180) < 150
    elif mode == 33:
        _demo_frame += 1
        start = _demo_frame == 640
    elif mode == 32:
        _demo_frame += 1
        down = _demo_frame == 2
        start = _demo_frame == 6
    elif mode == 31:
        _demo_frame += 1
        start = _demo_frame == 4
    elif mode == 30:
        _demo_frame += 1
        subscreen = _demo_frame == 3
        down = _demo_frame in (6, 8)
        start = _demo_frame == 12
    elif mode == 15:
        _demo_frame += 1
        phase = _demo_frame % 240
        right = _demo_frame > 10
        jump = phase in (30, 40)
        shot = (_demo_frame % 26) == 0 and _demo_frame > 30
    elif mode == 14:
        _demo_frame += 1
        right = (20 <= _demo_frame < 130) or (620 <= _demo_frame < 1120)
        shot = 150 <= _demo_frame < 560 and (_demo_frame % 40) == 0
    elif mode == 13:
        _demo_frame += 1
        start = _demo_frame == 5
        right = _demo_frame >= 20
        shot = _demo_frame >= 60 and (_demo_frame % 24) < 2

    inp.left = left
    inp.right = right
    inp.up = up
    inp.down = down
    inp.jump_held = jump
    inp.jump_pressed = jump and not st.prev_jump
    inp.shot_held = shot
    inp.shot_pressed = shot and not st.prev_shot
    inp.special_held = special
    inp.special_pressed = special and not st.prev_special
    inp.subscreen_pressed = subscreen and not st.prev_subscreen
    inp.form_next_pressed = form_next and not st.prev_form_next
    inp.start_pressed = start and not st.prev_start
    inp.pause_pressed = pause and not st.prev_pause
    inp.debug_collision = debug

    st.prev_jump = jump
    st.prev_shot = shot
    st.prev_special = special
    st.prev_subscreen = subscreen
    st.prev_form_next = form_next
    st.prev_start = start
    st.prev_pause = pause
    st.prev_debug = debug
