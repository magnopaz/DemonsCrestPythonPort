#ifndef DC_AUDIO_H
#define DC_AUDIO_H

#include <stdbool.h>

typedef enum SfxId {
    SFX_JUMP = 0,
    SFX_LAND,
    SFX_SHOOT,
    SFX_BREAK,
    SFX_PICKUP,
    SFX_HURT,
    SFX_ENEMY_HIT,
    SFX_COUNT
} SfxId;

typedef enum MusicTrack {
    MUSIC_NONE = 0,
    MUSIC_TITLE,
    MUSIC_STAGE,
    MUSIC_BOSS,
    MUSIC_ENDING,
    MUSIC_TRACK_COUNT
} MusicTrack;

/* `assets` is the generated-asset directory; <assets>/audio/<track>.wav holds
 * the ROM-rendered music and is optional (procedural stand-ins otherwise). */
bool Audio_Init(const char *assets);
void Audio_Shutdown(void);
void Audio_Update(void);
void Audio_Play(SfxId id);
void Audio_StartMusic(void);
/* Switches the looping track (no-op when unchanged or audio is off). */
void Audio_SetTrack(int track);
void Audio_SetVolume(float volume);
float Audio_GetVolume(void);

#endif
