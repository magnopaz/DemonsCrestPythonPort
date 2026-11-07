"""Procedural audio (port of audio.c).

The C port synthesizes every sound itself and only reads the ROM-rendered
music when the asset pipeline produced one.  This module builds the same
22050 Hz mono 16-bit PCM and hands it to raylib through the same calls:
`LoadMusicStream` for `<assets>/audio/music_*.wav`, an in-memory WAV for the
procedural loops, and a `Wave` for the sound effects.

The ROM path is now the normal one: `tools/audio/` renders every stage theme
and every sound effect from the emulated console's own DSP, so `<assets>/audio`
holds one looping WAV per track and one short WAV per effect.  The procedural
synth below is only the fallback for a build without those assets.
"""

from __future__ import annotations

import math
import sys
from array import array

from . import rl
from .util import eprint
from .consts import (AREA_LEVEL_MUSIC, AREA_MUSIC, MUSIC_BOSS,
                     MUSIC_BOSS_COMMON, MUSIC_DARK_FOREST,
                     MUSIC_DARK_FOREST_CAVE, MUSIC_DEMON_HIDEOUT, MUSIC_ENDING,
                     MUSIC_MOUNTAINS, MUSIC_MOUNTAINS_VALLEY, MUSIC_MURKLAND,
                     MUSIC_NONE, MUSIC_OVERWORLD, MUSIC_PHALANX,
                     MUSIC_POSEIDONIA, MUSIC_POSEIDONIA_DEPTHS,
                     MUSIC_RUINED_CITY, MUSIC_TITLE, MUSIC_TOWERS_OF_DOOM,
                     MUSIC_TOWN, MUSIC_TRACK_COUNT, MUSIC_TRACK_NAMES, SFX_BREAK,
                     SFX_COUNT, SFX_ENEMY_HIT, SFX_HURT, SFX_JUMP, SFX_LAND,
                     SFX_PICKUP, SFX_SHOOT)
from .util import env_flag, file_exists

MUSIC_SR = 22050
MUSIC_STEP_SECONDS = 0.25
MUSIC_STEPS = 64
MAX_SFX_FRAMES = 22050

# Sound effect asset stems, indexed by SFX id.  `tools/audio/capture_sfx.py`
# writes these; a build without them keeps the procedural stand-ins.
SFX_NAMES = [
    "sfx_jump", "sfx_land", "sfx_shoot", "sfx_break", "sfx_pickup",
    "sfx_hurt", "sfx_enemy_hit",
]

ready = False
sfx = [rl.Sound() for _ in range(SFX_COUNT)]
sfx_from_rom = [False] * SFX_COUNT
music = [rl.Music() for _ in range(MUSIC_TRACK_COUNT)]
music_wav = [None] * MUSIC_TRACK_COUNT
music_loaded = [False] * MUSIC_TRACK_COUNT
music_from_rom = [False] * MUSIC_TRACK_COUNT
asset_dir = ""
current_track = MUSIC_NONE
master_vol = 1.0

_probe_ticks = 0


def _debug(message: str) -> None:
    eprint(message)


def track_asset_name(track: int) -> str | None:
    """The ROM's own track for this game state, or None for MUSIC_NONE."""
    if track <= MUSIC_NONE or track >= MUSIC_TRACK_COUNT:
        return None
    stem = MUSIC_TRACK_NAMES[track]
    return f"{stem}.wav" if stem else None


def music_for_area(area: int, level: str = "") -> int:
    """The track a room plays: the measured table first, then its stage."""
    track = AREA_MUSIC.get(area)
    if track is not None:
        return track
    return AREA_LEVEL_MUSIC.get(level, AREA_LEVEL_MUSIC["I"])


def _load_rom_track(track: int) -> bool:
    """Load the ROM-rendered track when the asset pipeline produced one."""
    name = track_asset_name(track)
    if not name or not asset_dir:
        return False
    path = f"{asset_dir}/audio/{name}"
    if not file_exists(path):
        return False
    loaded = rl.LoadMusicStream(rl.cstr(path))
    if not rl.IsMusicValid(loaded):
        return False
    loaded.looping = True
    music[track] = loaded
    music_loaded[track] = True
    music_from_rom[track] = True
    if env_flag("DC_AUDIO_DEBUG"):
        _debug(f"audio: track {track} <- {path} "
               f"({float(rl.GetMusicTimeLength(loaded)):.2f} s, "
               f"{int(loaded.stream.sampleRate)} Hz, ROM)")
    return True


def _put16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF


def _put32(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF
    buf[offset + 2] = (value >> 16) & 0xFF
    buf[offset + 3] = (value >> 24) & 0xFF


def _wrap_wav(pcm: array, frames: int) -> bytes:
    """The same 44-byte mono 16-bit PCM WAV header the C builds."""
    data_bytes = frames * 2
    size = 44 + data_bytes
    wav = bytearray(size)
    wav[0:4] = b"RIFF"
    _put32(wav, 4, 36 + data_bytes)
    wav[8:16] = b"WAVEfmt "
    _put32(wav, 16, 16)
    _put16(wav, 20, 1)       # PCM
    _put16(wav, 22, 1)       # mono
    _put32(wav, 24, MUSIC_SR)
    _put32(wav, 28, MUSIC_SR * 2)
    _put16(wav, 32, 2)
    _put16(wav, 34, 16)
    wav[36:40] = b"data"
    _put32(wav, 40, data_bytes)
    data = pcm.tobytes()
    if sys.byteorder != "little":
        swapped = array("h", pcm)
        swapped.byteswap()
        data = swapped.tobytes()
    wav[44:] = data
    return bytes(wav)


def _note_hz(midi: int) -> float:
    return 440.0 * math.pow(2.0, (midi - 69) / 12.0)


def _square(phase: float, amp: float) -> int:
    return int((amp if phase < 0.5 else -amp) * 32767.0)


# Track data: 64-step loops, one per game state family.
_STAGE_MELODY = [
    69, 72, 76, 72, 69, 72, 76, 79, 65, 69, 72, 69, 65, 69, 72, 76,
    67, 71, 74, 71, 67, 71, 74, 79, 64, 67, 71, 67, 64, 67, 71, 74,
    69, 72, 76, 79, 76, 72, 69, 65, 65, 69, 72, 76, 72, 69, 65, 62,
    67, 71, 74, 79, 74, 71, 67, 64, 64, 67, 71, 74, 71, 67, 64, 57,
]
_STAGE_BASS = [45, 45, 41, 41, 43, 43, 40, 40,
               45, 45, 41, 41, 43, 43, 40, 40]
_TITLE_MELODY = [
    57, 60, 64, 69, 64, 60, 57, 60, 55, 59, 62, 67, 62, 59, 55, 59,
    53, 57, 60, 65, 60, 57, 53, 57, 52, 55, 59, 64, 59, 55, 52, 55,
    57, 60, 64, 69, 72, 69, 64, 60, 55, 59, 62, 67, 71, 67, 62, 59,
    53, 57, 60, 65, 69, 65, 60, 57, 52, 55, 59, 64, 67, 64, 59, 55,
]
_TITLE_BASS = [33, 33, 31, 31, 29, 29, 28, 28,
               33, 33, 31, 31, 29, 29, 28, 28]
_BOSS_MELODY = [
    64, 64, 67, 64, 62, 62, 64, 62, 60, 60, 63, 60, 58, 58, 60, 58,
    64, 67, 70, 67, 64, 67, 70, 73, 62, 65, 68, 65, 62, 65, 68, 71,
    64, 64, 67, 64, 62, 62, 64, 62, 60, 63, 67, 70, 63, 60, 58, 55,
    52, 55, 58, 61, 58, 55, 52, 55, 53, 56, 59, 62, 59, 56, 53, 50,
]
_BOSS_BASS = [28, 28, 28, 28, 26, 26, 26, 26,
              24, 24, 24, 24, 23, 23, 23, 23]
_ENDING_MELODY = [
    69, 67, 65, 64, 65, 67, 69, 72, 71, 69, 67, 65, 67, 69, 71, 74,
    72, 71, 69, 67, 69, 71, 72, 76, 74, 72, 71, 69, 67, 65, 64, 62,
    64, 65, 67, 69, 71, 72, 74, 76, 74, 72, 71, 69, 67, 65, 64, 62,
    60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 57,
]
_ENDING_BASS = [45, 45, 43, 43, 41, 41, 40, 40,
                45, 45, 43, 43, 41, 41, 40, 40]

# The four procedural loops that used to be the whole soundtrack.  A build
# without `assets/generated/audio` still gets one of them per track family, so
# the game is never silent; each family is pinned to the loop whose character
# matches it best.
_TRACK_DEFS = (
    (None, None, 0.0, 0.0),
    (_TITLE_MELODY, _TITLE_BASS, 0.30, 0.5),
    (_STAGE_MELODY, _STAGE_BASS, 0.25, 0.5),
    (_BOSS_MELODY, _BOSS_BASS, 0.20, 0.25),
    (_ENDING_MELODY, _ENDING_BASS, 0.36, 0.5),
)

# MusicTrack -> index into _TRACK_DEFS for the no-assets fallback.
_PROC_FALLBACK = {
    MUSIC_TITLE: 1,
    MUSIC_OVERWORLD: 2,
    MUSIC_MURKLAND: 2,
    MUSIC_RUINED_CITY: 2,
    MUSIC_DARK_FOREST: 2,
    MUSIC_DARK_FOREST_CAVE: 2,
    MUSIC_TOWERS_OF_DOOM: 2,
    MUSIC_POSEIDONIA: 2,
    MUSIC_POSEIDONIA_DEPTHS: 2,
    MUSIC_MOUNTAINS: 2,
    MUSIC_MOUNTAINS_VALLEY: 2,
    MUSIC_PHALANX: 2,
    MUSIC_DEMON_HIDEOUT: 2,
    MUSIC_TOWN: 1,
    MUSIC_BOSS: 3,
    MUSIC_BOSS_COMMON: 3,
    MUSIC_ENDING: 4,
}


def _build_track_pcm(melody, bass, step_frames: int, duty: float) -> array:
    frames = step_frames * MUSIC_STEPS
    pcm = array("h", bytes(frames * 2))
    for s in range(MUSIC_STEPS):
        mf = _note_hz(melody[s])
        bi = (s // 4) % 16
        bf = _note_hz(bass[bi])
        base = s * step_frames
        for k in range(step_frames):
            tt = k / MUSIC_SR
            env = 1.0 - k / step_frames
            mix = int((1.0 if math.fmod(tt * mf, 1.0) < duty else -1.0) *
                      0.18 * env * 32767.0) + \
                _square(math.fmod(tt * bf, 1.0), 0.22)
            if mix > 32767:
                mix = 32767
            elif mix < -32768:
                mix = -32768
            pcm[base + k] = mix
    return pcm


def _build_all_tracks() -> None:
    for i in range(MUSIC_TITLE, MUSIC_TRACK_COUNT):
        # The ROM's track wins when the asset build produced one; the
        # procedural loop below is only the no-assets fallback.
        if _load_rom_track(i):
            continue
        if env_flag("DC_AUDIO_DEBUG"):
            _debug(f"audio: track {i} <- procedural "
                   f"(no {track_asset_name(i) or '?'})")
        melody, bass, step, duty = _TRACK_DEFS[_PROC_FALLBACK.get(i, 2)]
        step_frames = int(MUSIC_SR * step)
        frames = step_frames * MUSIC_STEPS
        try:
            pcm = _build_track_pcm(melody, bass, step_frames, duty)
        except MemoryError:
            continue
        try:
            wav = _wrap_wav(pcm, frames)
        except MemoryError:
            continue
        # Keep the WAV bytes alive until shutdown, mirroring music_wav[] in C.
        music_wav[i] = wav
        music[i] = rl.LoadMusicStreamFromMemory(b".wav", wav, len(wav))
        if rl.IsMusicValid(music[i]):
            music[i].looping = True
            music_loaded[i] = True


def _build_sfx_pcm(seconds: float, f0: float, f1: float, noise: float,
                   amp: float):
    """Build one effect's PCM; returns (buffer, frames) or (None, 0)."""
    frames = int(MUSIC_SR * seconds)
    if frames > MAX_SFX_FRAMES:
        frames = MAX_SFX_FRAMES
    if frames <= 0:
        return None, 0
    try:
        pcm = rl.ffi.new("signed short[]", frames)
    except MemoryError:
        return None, 0
    seed = 0x12345678
    for i in range(frames):
        u = i / frames
        freq = f0 + (f1 - f0) * u
        t = i / MUSIC_SR
        env = 1.0 - u
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        n = ((seed >> 8) % 2001 - 1000) / 1000.0
        tone = 1.0 if math.fmod(t * freq, 1.0) < 0.5 else -1.0
        v = tone * (1.0 - noise) + n * noise
        sample = int(v * env * amp * 32767.0)
        if sample > 32767:
            sample = 32767
        elif sample < -32768:
            sample = -32768
        pcm[i] = sample
    return pcm, frames


def _make_sfx(seconds: float, f0: float, f1: float, noise: float,
              amp: float):
    pcm, frames = _build_sfx_pcm(seconds, f0, f1, noise, amp)
    if pcm is None:
        return rl.Sound()
    wave = rl.Wave(frames, MUSIC_SR, 16, 1, pcm)
    return rl.LoadSoundFromWave(wave)


def _load_rom_sfx(sfx_id: int) -> bool:
    """Load the console's own effect for this id when the asset exists."""
    if not asset_dir or sfx_id < 0 or sfx_id >= len(SFX_NAMES):
        return False
    path = f"{asset_dir}/audio/{SFX_NAMES[sfx_id]}.wav"
    if not file_exists(path):
        return False
    loaded = rl.LoadSound(rl.cstr(path))
    if not rl.IsSoundValid(loaded):
        return False
    sfx[sfx_id] = loaded
    sfx_from_rom[sfx_id] = True
    if env_flag("DC_AUDIO_DEBUG"):
        _debug(f"audio: sfx {SFX_NAMES[sfx_id]} <- {path} (ROM)")
    return True


def audio_init(assets_dir) -> bool:
    global ready, asset_dir
    ready = False
    asset_dir = ""
    if assets_dir:
        asset_dir = str(assets_dir)[:1023]
    if (env_flag("DC_NO_AUDIO") or env_flag("DC_RUN_FRAMES")) and \
            not env_flag("DC_AUDIO_FORCE"):
        return False
    if env_flag("DC_AUDIO_DEBUG"):
        _debug("audio: init start")
    try:
        rl.InitAudioDevice()
        device_ready = rl.IsAudioDeviceReady()
    except Exception:
        device_ready = False
    if not device_ready:
        if env_flag("DC_AUDIO_DEBUG"):
            _debug("audio: device not ready; running silent")
        return False

    # The console's effects first; the procedural stand-ins only fill the ids
    # the asset build did not produce.
    for i in range(SFX_COUNT):
        _load_rom_sfx(i)
    if not sfx_from_rom[SFX_JUMP]:
        sfx[SFX_JUMP] = _make_sfx(0.12, 300.0, 620.0, 0.05, 0.35)
    if not sfx_from_rom[SFX_LAND]:
        sfx[SFX_LAND] = _make_sfx(0.09, 180.0, 70.0, 0.45, 0.30)
    if not sfx_from_rom[SFX_SHOOT]:
        sfx[SFX_SHOOT] = _make_sfx(0.11, 900.0, 260.0, 0.25, 0.30)
    if not sfx_from_rom[SFX_BREAK]:
        sfx[SFX_BREAK] = _make_sfx(0.16, 220.0, 90.0, 0.75, 0.35)
    if not sfx_from_rom[SFX_PICKUP]:
        sfx[SFX_PICKUP] = _make_sfx(0.22, 660.0, 1320.0, 0.0, 0.30)
    if not sfx_from_rom[SFX_HURT]:
        sfx[SFX_HURT] = _make_sfx(0.20, 160.0, 55.0, 0.25, 0.35)
    if not sfx_from_rom[SFX_ENEMY_HIT]:
        sfx[SFX_ENEMY_HIT] = _make_sfx(0.08, 500.0, 220.0, 0.4, 0.28)

    _build_all_tracks()
    ready = True
    if env_flag("DC_AUDIO_DEBUG"):
        loaded = 0
        rom = 0
        for i in range(MUSIC_TITLE, MUSIC_TRACK_COUNT):
            loaded += 1 if music_loaded[i] else 0
            rom += 1 if music_from_rom[i] else 0
        sfx_rom = sum(1 for v in sfx_from_rom if v)
        _debug(f"audio: device ready, {loaded}/{MUSIC_TRACK_COUNT - 1} "
               f"tracks loaded ({rom} from ROM), "
               f"{sfx_rom}/{SFX_COUNT} effects from ROM")
    return True


def audio_shutdown() -> None:
    global ready, current_track
    if not ready:
        if rl.IsAudioDeviceReady():
            rl.CloseAudioDevice()
        return
    for i in range(SFX_COUNT):
        if rl.IsSoundValid(sfx[i]):
            rl.UnloadSound(sfx[i])
        sfx_from_rom[i] = False
    for i in range(MUSIC_TITLE, MUSIC_TRACK_COUNT):
        if music_loaded[i]:
            rl.UnloadMusicStream(music[i])
        music_wav[i] = None
        music_loaded[i] = False
        music_from_rom[i] = False
    current_track = MUSIC_NONE
    rl.CloseAudioDevice()
    ready = False


def audio_update() -> None:
    global _probe_ticks
    if ready and MUSIC_NONE < current_track < MUSIC_TRACK_COUNT and \
            music_loaded[current_track]:
        rl.UpdateMusicStream(music[current_track])
    # DC_AUDIO_PROBE: report the stream clock so a headless run can prove the
    # track is really playing (a loaded-but-silent stream would stay at 0).
    if env_flag("DC_AUDIO_PROBE") and ready and \
            MUSIC_NONE < current_track < MUSIC_TRACK_COUNT and \
            music_loaded[current_track]:
        _probe_ticks += 1
        if _probe_ticks % 60 == 0:
            stream = music[current_track]
            _debug(f"audio: probe track={current_track} "
                   f"rom={1 if music_from_rom[current_track] else 0} "
                   f"time={float(rl.GetMusicTimePlayed(stream)):.3f} "
                   f"playing={1 if rl.IsMusicStreamPlaying(stream) else 0}")


def audio_play(sfx_id: int) -> None:
    if not ready or sfx_id < 0 or sfx_id >= SFX_COUNT:
        return
    if rl.IsSoundValid(sfx[sfx_id]):
        rl.PlaySound(sfx[sfx_id])


def audio_start_music(track: int = MUSIC_MURKLAND) -> None:
    """Start the first real track; callers pass the room's own theme."""
    audio_set_track(track)


def audio_set_track(track: int) -> None:
    global current_track
    if not ready or track == current_track:
        return
    if track < MUSIC_NONE or track >= MUSIC_TRACK_COUNT:
        return
    if MUSIC_NONE < current_track < MUSIC_TRACK_COUNT and \
            music_loaded[current_track]:
        rl.StopMusicStream(music[current_track])
    current_track = track
    if env_flag("DC_AUDIO_DEBUG"):
        _debug(f"audio: track {track}")
    if track > MUSIC_NONE and music_loaded[track] and \
            not rl.IsMusicStreamPlaying(music[track]):
        rl.PlayMusicStream(music[track])


def audio_set_volume(volume: float) -> None:
    global master_vol
    volume = float(volume)
    if volume < 0.0:
        volume = 0.0
    if volume > 1.0:
        volume = 1.0
    master_vol = volume
    if ready:
        rl.SetMasterVolume(master_vol)


def audio_get_volume() -> float:
    return master_vol
