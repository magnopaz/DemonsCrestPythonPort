"""Player, crest-form and projectile animation sheets (port of anim.c)."""

from __future__ import annotations

import os

from . import rl
from .util import eprint
from .consts import ANIM_CLIP_COUNT, ANIM_CLIP_NAMES
from .util import as_int, file_exists, read_json

DC_ANIM_MAX_STEPS = 64
DC_PROJECTILE_MAX_STEPS = 16


class AnimStep:
    __slots__ = ("texture", "flipped", "anchor_x", "anchor_y", "duration")

    def __init__(self):
        self.texture = rl.Texture2D()
        self.flipped = rl.Texture2D()
        self.anchor_x = 0
        self.anchor_y = 0
        self.duration = 1


class AnimClip:
    __slots__ = ("first_step", "step_count", "loop")

    def __init__(self):
        self.first_step = 0
        self.step_count = 0
        self.loop = False


class PlayerAnim:
    __slots__ = ("steps", "clips", "ready")

    def __init__(self):
        self.steps = []
        self.clips = [AnimClip() for _ in range(ANIM_CLIP_COUNT)]
        self.ready = False


class ProjectileAnim:
    __slots__ = ("steps", "step_count", "loop", "ready")

    def __init__(self):
        self.steps = []
        self.step_count = 0
        self.loop = False
        self.ready = False


def _load_step_textures(step: AnimStep, path: str) -> bool:
    image = rl.LoadImage(os.fsencode(path))
    if not image.data:
        eprint(f"anim: failed to load {path}", flush=True)
        return False
    step.texture = rl.LoadTextureFromImage(image)
    rl.ImageFlipHorizontal(rl.ffi.addressof(image))
    step.flipped = rl.LoadTextureFromImage(image)
    rl.UnloadImage(image)
    if not rl.IsTextureValid(step.texture) or not rl.IsTextureValid(step.flipped):
        eprint(f"anim: failed to create textures for {path}", flush=True)
        if rl.IsTextureValid(step.texture):
            rl.UnloadTexture(step.texture)
        if rl.IsTextureValid(step.flipped):
            rl.UnloadTexture(step.flipped)
        step.texture = rl.Texture2D()
        step.flipped = rl.Texture2D()
        return False
    rl.SetTextureFilter(step.texture, 0)
    rl.SetTextureFilter(step.flipped, 0)
    return True


def anim_unload(anim: PlayerAnim) -> None:
    for step in anim.steps:
        if rl.IsTextureValid(step.texture):
            rl.UnloadTexture(step.texture)
        if rl.IsTextureValid(step.flipped):
            rl.UnloadTexture(step.flipped)
    anim.steps = []
    anim.clips = [AnimClip() for _ in range(ANIM_CLIP_COUNT)]
    anim.ready = False


def _parse_clips(anim: PlayerAnim, clips, directory: str) -> bool:
    if not isinstance(clips, dict):
        return False
    total = 0
    for clip_id in range(ANIM_CLIP_COUNT):
        clip = clips.get(ANIM_CLIP_NAMES[clip_id])
        if not isinstance(clip, dict):
            continue
        steps = clip.get("steps")
        if not isinstance(steps, list):
            anim_unload(anim)
            return False
        dst = anim.clips[clip_id]
        dst.first_step = total
        dst.loop = bool(clip.get("loop"))
        if len(steps) <= 0 or total + len(steps) > DC_ANIM_MAX_STEPS:
            anim_unload(anim)
            return False
        for item in steps:
            tex = item.get("texture") if isinstance(item, dict) else None
            step = AnimStep()
            if not isinstance(tex, str) or "anchor_x" not in item or \
                    "anchor_y" not in item:
                anim_unload(anim)
                return False
            step.anchor_x = as_int(item.get("anchor_x"))
            step.anchor_y = as_int(item.get("anchor_y"))
            step.duration = as_int(item.get("duration"), 1)
            if step.duration < 1:
                step.duration = 1
            if not _load_step_textures(step, os.path.join(directory, tex)):
                anim_unload(anim)
                return False
            anim.steps.append(step)
            total += 1
        dst.step_count = len(steps)
    anim.ready = len(anim.steps) > 0
    return anim.ready


def anim_load(anim: PlayerAnim, directory: str) -> bool:
    path = os.path.join(directory, "player_anim.json")
    if not file_exists(path):
        return False
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return False
    return _parse_clips(anim, root.get("clips"), directory)


def anim_load_forms(anims: list[PlayerAnim], max_forms: int,
                    directory: str) -> int:
    path = os.path.join(directory, "player_forms.json")
    if not file_exists(path):
        return 0
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return 0
    count = 0
    for entry in root.get("forms") or []:
        if count >= max_forms:
            break
        form = entry.get("form")
        if not isinstance(form, (int, float)):
            continue
        index = int(form)
        if index < 0 or index >= max_forms:
            continue
        if _parse_clips(anims[index], entry.get("clips"), directory):
            count += 1
    return count


def anim_unload_forms(anims: list[PlayerAnim], count: int) -> None:
    for i in range(count):
        anim_unload(anims[i])


def anim_step(anim: PlayerAnim, clip: int, index: int):
    if not anim.ready or clip < 0 or clip >= ANIM_CLIP_COUNT:
        return None
    c = anim.clips[clip]
    if c.step_count <= 0:
        return None
    if index < 0:
        index = 0
    if index >= c.step_count:
        index = c.step_count - 1
    return anim.steps[c.first_step + index]


def projectile_anim_load(anim: ProjectileAnim, directory: str) -> bool:
    path = os.path.join(directory, "fireball_anim.json")
    if not file_exists(path):
        return False
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return False
    steps = root.get("steps")
    if not isinstance(steps, list) or not steps or \
            len(steps) > DC_PROJECTILE_MAX_STEPS:
        return False
    anim.loop = bool(root.get("loop"))
    for item in steps:
        tex = item.get("texture") if isinstance(item, dict) else None
        step = AnimStep()
        if not isinstance(tex, str) or "anchor_x" not in item or \
                "anchor_y" not in item:
            projectile_anim_unload(anim)
            return False
        step.anchor_x = as_int(item.get("anchor_x"))
        step.anchor_y = as_int(item.get("anchor_y"))
        step.duration = as_int(item.get("duration"), 1)
        if step.duration < 1:
            step.duration = 1
        if not _load_step_textures(step, os.path.join(directory, tex)):
            projectile_anim_unload(anim)
            return False
        anim.steps.append(step)
        anim.step_count += 1
    anim.ready = anim.step_count > 0
    return anim.ready


def projectile_anim_unload(anim: ProjectileAnim) -> None:
    for step in anim.steps:
        if rl.IsTextureValid(step.texture):
            rl.UnloadTexture(step.texture)
        if rl.IsTextureValid(step.flipped):
            rl.UnloadTexture(step.flipped)
    anim.steps = []
    anim.step_count = 0
    anim.ready = False


def projectile_anim_step(anim: ProjectileAnim, index: int):
    if not anim.ready or anim.step_count <= 0:
        return None
    if index < 0:
        index = 0
    if index >= anim.step_count:
        if not anim.loop:
            index = anim.step_count - 1
        else:
            index %= anim.step_count
    return anim.steps[index]
