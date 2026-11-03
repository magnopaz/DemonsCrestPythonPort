/* apu_wav.h — the one thing every audio tool here needs: write a 16-bit
 * stereo WAV without pulling in a library. Included by the .c files, so the
 * helpers are static. */
#ifndef APU_WAV_H
#define APU_WAV_H

#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void apu_wr32le(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16);
  p[3] = (uint8_t)(v >> 24);
}

static void apu_wr16le(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}

static int apu_write_wav(const char *path, const int16_t *pcm, int frames,
                         int rate) {
  uint32_t data_bytes = (uint32_t)frames * 4;
  uint8_t hdr[44];
  memcpy(hdr, "RIFF", 4);
  apu_wr32le(hdr + 4, 36 + data_bytes);
  memcpy(hdr + 8, "WAVEfmt ", 8);
  apu_wr32le(hdr + 16, 16);
  apu_wr16le(hdr + 20, 1);
  apu_wr16le(hdr + 22, 2);
  apu_wr32le(hdr + 24, (uint32_t)rate);
  apu_wr32le(hdr + 28, (uint32_t)rate * 4);
  apu_wr16le(hdr + 32, 4);
  apu_wr16le(hdr + 34, 16);
  memcpy(hdr + 36, "data", 4);
  apu_wr32le(hdr + 40, data_bytes);
  FILE *o = fopen(path, "wb");
  if (!o) return -1;
  int ok = fwrite(hdr, 1, sizeof(hdr), o) == sizeof(hdr) &&
           fwrite(pcm, 2, (size_t)data_bytes / 2, o) == (size_t)data_bytes / 2;
  fclose(o);
  if (!ok) remove(path);
  return ok ? 0 : -1;
}

#endif
