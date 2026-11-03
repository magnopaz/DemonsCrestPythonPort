#include "audio.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "raylib.h"

#define MUSIC_SR 22050
#define MUSIC_STEP_SECONDS 0.25
#define MUSIC_STEPS 64
#define MAX_SFX_FRAMES 22050

static bool ready;
static Sound sfx[SFX_COUNT];
static Music music[MUSIC_TRACK_COUNT];
static unsigned char *music_wav[MUSIC_TRACK_COUNT];
static bool music_loaded[MUSIC_TRACK_COUNT];
static bool music_from_rom[MUSIC_TRACK_COUNT];
static char asset_dir[1024];
static int current_track = MUSIC_NONE;
static float master_vol = 1.0f;

/* The ROM's own track for each game state, as produced by
 * tools/audio/make_music_asset.py into <assets>/audio/. Missing files are not
 * an error: the procedural stand-in keeps the game audible without assets. */
static const char *TrackAssetName(int track) {
    switch (track) {
    case MUSIC_TITLE:
        return "music_title.wav";
    case MUSIC_STAGE:
        return "music_stage.wav";
    case MUSIC_BOSS:
        return "music_boss.wav";
    case MUSIC_ENDING:
        return "music_ending.wav";
    default:
        return NULL;
    }
}

/* Load the ROM-rendered track when the asset pipeline produced one. */
static bool LoadRomTrack(int track) {
    const char *name = TrackAssetName(track);
    if (!name || !asset_dir[0])
        return false;
    char path[1200];
    snprintf(path, sizeof(path), "%s/audio/%s", asset_dir, name);
    if (!FileExists(path))
        return false;
    Music loaded = LoadMusicStream(path);
    if (!IsMusicValid(loaded))
        return false;
    loaded.looping = true;
    music[track] = loaded;
    music_loaded[track] = true;
    music_from_rom[track] = true;
    if (getenv("DC_AUDIO_DEBUG"))
        fprintf(stderr, "audio: track %d <- %s (%.2f s, %u Hz, ROM)\n", track,
                path, (double)GetMusicTimeLength(loaded),
                (unsigned)loaded.stream.sampleRate);
    return true;
}

static void Put16(unsigned char *p, uint16_t v) {
    p[0] = (unsigned char)(v & 0xFF);
    p[1] = (unsigned char)(v >> 8);
}

static void Put32(unsigned char *p, uint32_t v) {
    p[0] = (unsigned char)(v & 0xFF);
    p[1] = (unsigned char)((v >> 8) & 0xFF);
    p[2] = (unsigned char)((v >> 16) & 0xFF);
    p[3] = (unsigned char)((v >> 24) & 0xFF);
}

static unsigned char *WrapWav(const int16_t *pcm, int frames, int *size_out) {
    int data_bytes = frames * 2;
    int size = 44 + data_bytes;
    unsigned char *wav = malloc((size_t)size);
    if (!wav)
        return NULL;
    memcpy(wav, "RIFF", 4);
    Put32(wav + 4, (uint32_t)(36 + data_bytes));
    memcpy(wav + 8, "WAVEfmt ", 8);
    Put32(wav + 16, 16);
    Put16(wav + 20, 1);       /* PCM */
    Put16(wav + 22, 1);       /* mono */
    Put32(wav + 24, MUSIC_SR);
    Put32(wav + 28, MUSIC_SR * 2);
    Put16(wav + 32, 2);
    Put16(wav + 34, 16);
    memcpy(wav + 36, "data", 4);
    Put32(wav + 40, (uint32_t)data_bytes);
    for (int i = 0; i < frames; i++)
        Put16(wav + 44 + i * 2, (uint16_t)pcm[i]);
    *size_out = size;
    return wav;
}

static float NoteHz(int midi) {
    return 440.0f * powf(2.0f, (float)(midi - 69) / 12.0f);
}

static int16_t Square(float phase, float amp) {
    return (int16_t)((phase < 0.5f ? amp : -amp) * 32767.0f);
}

/* Track data: 64-step loops, one per game state family. */
static const int kStageMelody[64] = {
    69, 72, 76, 72, 69, 72, 76, 79, 65, 69, 72, 69, 65, 69, 72, 76,
    67, 71, 74, 71, 67, 71, 74, 79, 64, 67, 71, 67, 64, 67, 71, 74,
    69, 72, 76, 79, 76, 72, 69, 65, 65, 69, 72, 76, 72, 69, 65, 62,
    67, 71, 74, 79, 74, 71, 67, 64, 64, 67, 71, 74, 71, 67, 64, 57};
static const int kStageBass[16] = {45, 45, 41, 41, 43, 43, 40, 40,
                                   45, 45, 41, 41, 43, 43, 40, 40};
static const int kTitleMelody[64] = {
    57, 60, 64, 69, 64, 60, 57, 60, 55, 59, 62, 67, 62, 59, 55, 59,
    53, 57, 60, 65, 60, 57, 53, 57, 52, 55, 59, 64, 59, 55, 52, 55,
    57, 60, 64, 69, 72, 69, 64, 60, 55, 59, 62, 67, 71, 67, 62, 59,
    53, 57, 60, 65, 69, 65, 60, 57, 52, 55, 59, 64, 67, 64, 59, 55};
static const int kTitleBass[16] = {33, 33, 31, 31, 29, 29, 28, 28,
                                   33, 33, 31, 31, 29, 29, 28, 28};
static const int kBossMelody[64] = {
    64, 64, 67, 64, 62, 62, 64, 62, 60, 60, 63, 60, 58, 58, 60, 58,
    64, 67, 70, 67, 64, 67, 70, 73, 62, 65, 68, 65, 62, 65, 68, 71,
    64, 64, 67, 64, 62, 62, 64, 62, 60, 63, 67, 70, 63, 60, 58, 55,
    52, 55, 58, 61, 58, 55, 52, 55, 53, 56, 59, 62, 59, 56, 53, 50};
static const int kBossBass[16] = {28, 28, 28, 28, 26, 26, 26, 26,
                                  24, 24, 24, 24, 23, 23, 23, 23};
static const int kEndingMelody[64] = {
    69, 67, 65, 64, 65, 67, 69, 72, 71, 69, 67, 65, 67, 69, 71, 74,
    72, 71, 69, 67, 69, 71, 72, 76, 74, 72, 71, 69, 67, 65, 64, 62,
    64, 65, 67, 69, 71, 72, 74, 76, 74, 72, 71, 69, 67, 65, 64, 62,
    60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 57};
static const int kEndingBass[16] = {45, 45, 43, 43, 41, 41, 40, 40,
                                    45, 45, 43, 43, 41, 41, 40, 40};

static void BuildAllTracks(void) {
    struct {
        const int *melody;
        const int *bass;
        float step;
        float duty;
    } defs[MUSIC_TRACK_COUNT] = {
        {NULL, NULL, 0.0f, 0.0f},
        {kTitleMelody, kTitleBass, 0.30f, 0.5f},
        {kStageMelody, kStageBass, 0.25f, 0.5f},
        {kBossMelody, kBossBass, 0.20f, 0.25f},
        {kEndingMelody, kEndingBass, 0.36f, 0.5f},
    };
    for (int i = MUSIC_TITLE; i < MUSIC_TRACK_COUNT; i++) {
        /* The ROM's track wins when the asset build produced one; the
         * procedural loop below is only the no-assets fallback. */
        if (LoadRomTrack(i))
            continue;
        if (getenv("DC_AUDIO_DEBUG"))
            fprintf(stderr, "audio: track %d <- procedural (no %s)\n", i,
                    TrackAssetName(i) ? TrackAssetName(i) : "?");
        /* BuildTrack keeps its WAV alive by returning it through the stream;
         * remember the buffer so Shutdown can free it. */
        int step_frames = (int)(MUSIC_SR * defs[i].step);
        int frames = step_frames * MUSIC_STEPS;
        int16_t *pcm = calloc((size_t)frames, sizeof(int16_t));
        if (!pcm)
            continue;
        for (int s = 0; s < MUSIC_STEPS; s++) {
            float mf = NoteHz(defs[i].melody[s]);
            int bi = (s / 4) % 16;
            float bf = NoteHz(defs[i].bass[bi]);
            for (int k = 0; k < step_frames; k++) {
                float tt = (float)k / MUSIC_SR;
                float env = 1.0f - (float)k / step_frames;
                float duty = defs[i].duty;
                int mix = (int)((fmodf(tt * mf, 1.0f) < duty ? 1.0f : -1.0f) *
                                0.18f * env * 32767.0f) +
                          (int)Square(fmodf(tt * bf, 1.0f), 0.22f);
                if (mix > 32767) mix = 32767;
                if (mix < -32768) mix = -32768;
                pcm[s * step_frames + k] = (int16_t)mix;
            }
        }
        int size = 0;
        music_wav[i] = WrapWav(pcm, frames, &size);
        free(pcm);
        if (!music_wav[i])
            continue;
        music[i] = LoadMusicStreamFromMemory(".wav", music_wav[i], size);
        if (IsMusicValid(music[i])) {
            music[i].looping = true;
            music_loaded[i] = true;
        }
    }
}

static Sound MakeSfx(float seconds, float f0, float f1, float noise,
                     float amp) {
    int frames = (int)(MUSIC_SR * seconds);
    if (frames > MAX_SFX_FRAMES)
        frames = MAX_SFX_FRAMES;
    int16_t *pcm = calloc((size_t)frames, sizeof(int16_t));
    if (!pcm)
        return (Sound){0};
    unsigned seed = 0x12345678u;
    for (int i = 0; i < frames; i++) {
        float u = (float)i / frames;
        float freq = f0 + (f1 - f0) * u;
        float t = (float)i / MUSIC_SR;
        float env = 1.0f - u;
        seed = seed * 1664525u + 1013904223u;
        float n = ((int)(seed >> 8) % 2001 - 1000) / 1000.0f;
        float tone = (fmodf(t * freq, 1.0f) < 0.5f) ? 1.0f : -1.0f;
        float v = tone * (1.0f - noise) + n * noise;
        int sample = (int)(v * env * amp * 32767.0f);
        if (sample > 32767) sample = 32767;
        if (sample < -32768) sample = -32768;
        pcm[i] = (int16_t)sample;
    }
    Wave wave = {0};
    wave.frameCount = (unsigned int)frames;
    wave.sampleRate = MUSIC_SR;
    wave.sampleSize = 16;
    wave.channels = 1;
    wave.data = pcm;
    Sound sound = LoadSoundFromWave(wave);
    free(pcm);
    return sound;
}

bool Audio_Init(const char *assets) {
    ready = false;
    asset_dir[0] = '\0';
    if (assets && *assets)
        snprintf(asset_dir, sizeof(asset_dir), "%s", assets);
    if ((getenv("DC_NO_AUDIO") || getenv("DC_RUN_FRAMES")) &&
        !getenv("DC_AUDIO_FORCE"))
        return false;
    if (getenv("DC_AUDIO_DEBUG"))
        fprintf(stderr, "audio: init start\n");
    InitAudioDevice();
    if (!IsAudioDeviceReady()) {
        if (getenv("DC_AUDIO_DEBUG"))
            fprintf(stderr, "audio: device not ready; running silent\n");
        return false;
    }

    sfx[SFX_JUMP] = MakeSfx(0.12f, 300.0f, 620.0f, 0.05f, 0.35f);
    sfx[SFX_LAND] = MakeSfx(0.09f, 180.0f, 70.0f, 0.45f, 0.30f);
    sfx[SFX_SHOOT] = MakeSfx(0.11f, 900.0f, 260.0f, 0.25f, 0.30f);
    sfx[SFX_BREAK] = MakeSfx(0.16f, 220.0f, 90.0f, 0.75f, 0.35f);
    sfx[SFX_PICKUP] = MakeSfx(0.22f, 660.0f, 1320.0f, 0.0f, 0.30f);
    sfx[SFX_HURT] = MakeSfx(0.20f, 160.0f, 55.0f, 0.25f, 0.35f);
    sfx[SFX_ENEMY_HIT] = MakeSfx(0.08f, 500.0f, 220.0f, 0.4f, 0.28f);

    BuildAllTracks();
    ready = true;
    if (getenv("DC_AUDIO_DEBUG")) {
        int loaded = 0, rom = 0;
        for (int i = MUSIC_TITLE; i < MUSIC_TRACK_COUNT; i++) {
            loaded += music_loaded[i] ? 1 : 0;
            rom += music_from_rom[i] ? 1 : 0;
        }
        fprintf(stderr, "audio: device ready, %d/%d tracks loaded (%d from ROM)\n",
                loaded, MUSIC_TRACK_COUNT - 1, rom);
    }
    return true;
}

void Audio_Shutdown(void) {
    if (!ready) {
        if (IsAudioDeviceReady())
            CloseAudioDevice();
        return;
    }
    for (int i = 0; i < SFX_COUNT; i++) {
        if (IsSoundValid(sfx[i]))
            UnloadSound(sfx[i]);
    }
    for (int i = MUSIC_TITLE; i < MUSIC_TRACK_COUNT; i++) {
        if (music_loaded[i])
            UnloadMusicStream(music[i]);
        free(music_wav[i]);
        music_wav[i] = NULL;
        music_loaded[i] = false;
        music_from_rom[i] = false;
    }
    current_track = MUSIC_NONE;
    CloseAudioDevice();
    ready = false;
}

void Audio_Update(void) {
    if (ready && current_track > MUSIC_NONE && current_track < MUSIC_TRACK_COUNT &&
        music_loaded[current_track])
        UpdateMusicStream(music[current_track]);
    /* DC_AUDIO_PROBE: report the stream clock so a headless run can prove the
     * track is really playing (a loaded-but-silent stream would stay at 0). */
    if (getenv("DC_AUDIO_PROBE") && ready && current_track > MUSIC_NONE &&
        current_track < MUSIC_TRACK_COUNT && music_loaded[current_track]) {
        static int ticks;
        if (++ticks % 60 == 0)
            fprintf(stderr, "audio: probe track=%d rom=%d time=%.3f playing=%d\n",
                    current_track, music_from_rom[current_track] ? 1 : 0,
                    (double)GetMusicTimePlayed(music[current_track]),
                    IsMusicStreamPlaying(music[current_track]) ? 1 : 0);
    }
}

void Audio_Play(SfxId id) {
    if (!ready || id < 0 || id >= SFX_COUNT)
        return;
    if (IsSoundValid(sfx[id]))
        PlaySound(sfx[id]);
}

void Audio_StartMusic(void) {
    Audio_SetTrack(MUSIC_STAGE);
}

void Audio_SetTrack(int track) {
    if (!ready || track == current_track)
        return;
    if (track < MUSIC_NONE || track >= MUSIC_TRACK_COUNT)
        return;
    if (current_track > MUSIC_NONE && current_track < MUSIC_TRACK_COUNT &&
        music_loaded[current_track])
        StopMusicStream(music[current_track]);
    current_track = track;
    if (getenv("DC_AUDIO_DEBUG"))
        fprintf(stderr, "audio: track %d\n", track);
    if (track > MUSIC_NONE && music_loaded[track] &&
        !IsMusicStreamPlaying(music[track]))
        PlayMusicStream(music[track]);
}

void Audio_SetVolume(float volume) {
    if (volume < 0.0f)
        volume = 0.0f;
    if (volume > 1.0f)
        volume = 1.0f;
    master_vol = volume;
    if (ready)
        SetMasterVolume(master_vol);
}

float Audio_GetVolume(void) {
    return master_vol;
}
