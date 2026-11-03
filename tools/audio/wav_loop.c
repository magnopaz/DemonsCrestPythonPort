/*
 * wav_loop — find the loop period of a rendered track and cut a seamless loop.
 *
 * Music for the port comes from the game's own APU: either rendered from a .spc
 * (tools/audio/spc_render) or captured from the oracle's live DSP output.  Both
 * produce a WAV of a track that the original driver plays in a loop, so the
 * period is measurable: a 10 ms RMS-envelope correlation gives the coarse
 * period, then an exact sample-domain search (+-250 samples) minimises the mean
 * |difference| over a window.  `--loop-out` cuts that period, and the seam check
 * reports whether the cut is actually continuous.
 *
 * A true loop is periodic by construction, so the last sample of the cut and the
 * sample after it must differ by no more than ordinary adjacent samples do; the
 * tool prints both numbers instead of asserting.
 *
 * Usage:
 *   wav_loop live.wav --find-loop 4,110 --loop-start 30 --loop-out loop.wav
 *   wav_loop live.wav --csv            # per-second RMS profile
 */
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ENV_BUCKET 320 /* ~10 ms at 32040 Hz */

typedef struct {
  int rate;
  int frames;
  int16_t *pcm;
} Wav;

static int read_wav(const char *path, Wav *out) {
  FILE *f = fopen(path, "rb");
  if (!f) return -1;
  uint8_t hdr[12];
  if (fread(hdr, 1, 12, f) != 12 || memcmp(hdr, "RIFF", 4) ||
      memcmp(hdr + 8, "WAVE", 4)) {
    fclose(f);
    return -1;
  }
  int channels = 0, bits = 0, rate = 0;
  for (;;) {
    uint8_t ch[8];
    if (fread(ch, 1, 8, f) != 8) { fclose(f); return -1; }
    uint32_t size = (uint32_t)ch[4] | ((uint32_t)ch[5] << 8) |
                    ((uint32_t)ch[6] << 16) | ((uint32_t)ch[7] << 24);
    if (!memcmp(ch, "fmt ", 4)) {
      uint8_t fmt[16];
      if (size < 16 || fread(fmt, 1, 16, f) != 16) { fclose(f); return -1; }
      channels = fmt[2] | (fmt[3] << 8);
      rate = fmt[4] | (fmt[5] << 8) | (fmt[6] << 16) | ((uint32_t)fmt[7] << 24);
      bits = fmt[14] | (fmt[15] << 8);
      if (size > 16) fseek(f, (long)(size - 16), SEEK_CUR);
    } else if (!memcmp(ch, "data", 4)) {
      if (channels != 2 || bits != 16) { fclose(f); return -1; }
      int frames = (int)(size / 4);
      int16_t *pcm = malloc((size_t)frames * 2 * sizeof(int16_t));
      if (!pcm) { fclose(f); return -1; }
      size_t got = fread(pcm, sizeof(int16_t) * 2, (size_t)frames, f);
      fclose(f);
      out->rate = rate;
      out->frames = (int)got;
      out->pcm = pcm;
      return 0;
    } else {
      fseek(f, (long)size + (long)(size & 1), SEEK_CUR);
    }
  }
}

static void wr32le(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static void wr16le(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
}

static int write_wav(const char *path, const int16_t *pcm, int start, int count,
                     int rate) {
  uint32_t data_bytes = (uint32_t)count * 4;
  uint8_t hdr[44];
  memcpy(hdr, "RIFF", 4);
  wr32le(hdr + 4, 36 + data_bytes);
  memcpy(hdr + 8, "WAVEfmt ", 8);
  wr32le(hdr + 16, 16);
  wr16le(hdr + 20, 1);
  wr16le(hdr + 22, 2);
  wr32le(hdr + 24, (uint32_t)rate);
  wr32le(hdr + 28, (uint32_t)rate * 4);
  wr16le(hdr + 32, 4);
  wr16le(hdr + 34, 16);
  memcpy(hdr + 36, "data", 4);
  wr32le(hdr + 40, data_bytes);
  FILE *o = fopen(path, "wb");
  if (!o) return -1;
  int ok = fwrite(hdr, 1, sizeof(hdr), o) == sizeof(hdr) &&
           fwrite(&pcm[(size_t)start * 2], 2, (size_t)data_bytes / 2, o) ==
               (size_t)data_bytes / 2;
  fclose(o);
  if (!ok) remove(path);
  return ok ? 0 : -1;
}

static double window_diff(const int16_t *pcm, int a, int b, int len) {
  long long acc = 0;
  for (int i = 0; i < len; i++) {
    int dl = pcm[(size_t)(a + i) * 2] - pcm[(size_t)(b + i) * 2];
    int dr = pcm[(size_t)(a + i) * 2 + 1] - pcm[(size_t)(b + i) * 2 + 1];
    acc += (dl < 0 ? -dl : dl) + (dr < 0 ? -dr : dr);
  }
  return (double)acc / (2.0 * len);
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s track.wav [--find-loop MIN,MAX] [--loop-start S]"
                    " [--loop-out PATH] [--csv] [--json]\n", argv[0]);
    return 2;
  }
  const char *in_path = argv[1];
  double loop_min = 0, loop_max = 0, loop_start = -1;
  double snap = 0;
  const char *loop_out = NULL;
  bool csv = false, json = false;
  for (int i = 2; i < argc; i++) {
    if (!strcmp(argv[i], "--find-loop") && i + 1 < argc) {
      if (sscanf(argv[++i], "%lf,%lf", &loop_min, &loop_max) != 2) return 2;
    } else if (!strcmp(argv[i], "--loop-start") && i + 1 < argc) {
      loop_start = atof(argv[++i]);
    } else if (!strcmp(argv[i], "--snap-start") && i + 1 < argc) {
      snap = atof(argv[++i]);
    } else if (!strcmp(argv[i], "--loop-out") && i + 1 < argc) {
      loop_out = argv[++i];
    } else if (!strcmp(argv[i], "--csv")) {
      csv = true;
    } else if (!strcmp(argv[i], "--json")) {
      json = true;
    } else {
      fprintf(stderr, "wav_loop: unknown arg %s\n", argv[i]);
      return 2;
    }
  }

  Wav w;
  if (read_wav(in_path, &w) != 0) {
    fprintf(stderr, "wav_loop: cannot read %s (16-bit stereo PCM only)\n", in_path);
    return 1;
  }
  const int16_t *pcm = w.pcm;
  int produced = w.frames;
  int rate = w.rate;

  double peakL = 0, peakR = 0, sumL = 0, sumR = 0;
  for (int i = 0; i < produced; i++) {
    int l = abs(pcm[i * 2]), r = abs(pcm[i * 2 + 1]);
    if (l > peakL) peakL = l;
    if (r > peakR) peakR = r;
    sumL += (double)pcm[i * 2] * pcm[i * 2];
    sumR += (double)pcm[i * 2 + 1] * pcm[i * 2 + 1];
  }
  double rmsL = produced ? sqrt(sumL / produced) : 0;
  double rmsR = produced ? sqrt(sumR / produced) : 0;

  if (csv) {
    int step = rate;
    printf("t_seconds,rms\n");
    for (int i = 0; i + step <= produced; i += step) {
      double acc = 0;
      for (int k = 0; k < step; k++) {
        double m = (pcm[(size_t)(i + k) * 2] + pcm[(size_t)(i + k) * 2 + 1]) / 2.0;
        acc += m * m;
      }
      printf("%.3f,%.1f\n", (double)i / rate, sqrt(acc / step));
    }
  }

  long period = 0;
  double period_score = 0;
  double cand[5] = {-2, -2, -2, -2, -2};
  int cand_lag[5] = {0, 0, 0, 0, 0};
  if (loop_max > loop_min) {
    int env_n = produced / ENV_BUCKET;
    float *env = calloc((size_t)env_n, sizeof(float));
    if (env) {
      for (int i = 0; i < env_n; i++) {
        long long acc = 0;
        for (int k = 0; k < ENV_BUCKET; k++) {
          int s = i * ENV_BUCKET + k;
          acc += abs(pcm[s * 2]) + abs(pcm[s * 2 + 1]);
        }
        env[i] = (float)acc / (2.0f * ENV_BUCKET);
      }
      double mean = 0;
      for (int i = 0; i < env_n; i++) mean += env[i];
      mean /= env_n ? env_n : 1;
      for (int i = 0; i < env_n; i++) env[i] = (float)(env[i] - mean);

      int lag_lo = (int)(loop_min * rate / ENV_BUCKET);
      int lag_hi = (int)(loop_max * rate / ENV_BUCKET);
      if (lag_lo < 1) lag_lo = 1;
      if (lag_hi > env_n - 1) lag_hi = env_n - 1;
      /* Correlation must rest on at least half the envelope, otherwise a long
       * lag compares a handful of points and scores a spurious 1.0. */
      int min_overlap = env_n / 2;
      double best = -2;
      int best_lag = 0;
      for (int lag = lag_lo; lag <= lag_hi; lag++) {
        int n = env_n - lag;
        if (n < min_overlap) break;
        double dot = 0, na = 0, nb = 0;
        for (int i = 0; i < n; i++) {
          double a = env[i], b = env[i + lag];
          dot += a * b; na += a * a; nb += b * b;
        }
        double c = (na > 0 && nb > 0) ? dot / sqrt(na * nb) : -2;
        if (c > best) { best = c; best_lag = lag; }
        for (int k = 0; k < 5; k++) {
          if (c > cand[k]) {
            for (int j = 4; j > k; j--) { cand[j] = cand[j-1]; cand_lag[j] = cand_lag[j-1]; }
            cand[k] = c; cand_lag[k] = lag;
            break;
          }
        }
      }
      long coarse = (long)best_lag * ENV_BUCKET;
      int win_start = produced / 2;
      int win_len = 6 * rate;
      if (win_start + win_len >= produced) {
        win_start = produced / 3;
        win_len = produced - win_start - 1;
      }
      if (win_len < 1024) win_len = produced / 2;
      double best_diff = -1;
      long best_p = coarse;
      for (long p = coarse - 250; p <= coarse + 250; p++) {
        if (p <= 0 || win_start + p + win_len > produced) continue;
        double d = window_diff(pcm, win_start, win_start + (int)p, win_len);
        if (best_diff < 0 || d < best_diff) { best_diff = d; best_p = p; }
      }
      period = best_p;
      period_score = best_diff < 0 ? 0 : best_diff;
      free(env);
    }
  }

  int start = -1, count = 0, written = 0;
  double seam_jump = 0, avg_step = 0;
  if (loop_out && period > 0) {
    start = loop_start >= 0 ? (int)(loop_start * rate + 0.5) : 0;
    if (start + period > produced) start = produced - (int)period;
    if (start < 0) start = 0;
    count = (int)period;
    /* Snap the cut to the point whose end flows into its start most cleanly:
     * the music is periodic, so the sample after the cut should equal the first
     * sample of the cut. Search +-snap seconds around the requested start. */
    if (snap > 0) {
      int win = (int)(snap * rate);
      int lo = start - win, hi = start + win;
      if (lo < 0) lo = 0;
      if (hi + count + 1 >= produced) hi = produced - count - 2;
      double best = -1;
      int best_i = start;
      for (int a = lo; a <= hi; a++) {
        int d0 = abs(pcm[(size_t)a * 2] - pcm[(size_t)(a + count) * 2]) +
                 abs(pcm[(size_t)a * 2 + 1] - pcm[(size_t)(a + count) * 2 + 1]);
        int d1 = a > 0 ? abs(pcm[(size_t)(a - 1) * 2] -
                             pcm[(size_t)(a + count - 1) * 2]) +
                         abs(pcm[(size_t)(a - 1) * 2 + 1] -
                             pcm[(size_t)(a + count - 1) * 2 + 1])
                       : 0;
        double d = d0 + d1;
        if (best < 0 || d < best) { best = d; best_i = a; }
      }
      start = best_i;
    }
    if (write_wav(loop_out, pcm, start, count, rate) == 0) written = 1;
    int after = start + count;
    if (after < produced) {
      int dl = pcm[(size_t)after * 2] - pcm[(size_t)(after - 1) * 2];
      int dr = pcm[(size_t)after * 2 + 1] - pcm[(size_t)(after - 1) * 2 + 1];
      seam_jump = (abs(dl) + abs(dr)) / 2.0;
    }
    /* Typical adjacent-sample step over the cut, to judge the seam. */
    double acc = 0;
    for (int i = 1; i < count; i++) {
      int dl = pcm[(size_t)(start + i) * 2] - pcm[(size_t)(start + i - 1) * 2];
      int dr = pcm[(size_t)(start + i) * 2 + 1] -
               pcm[(size_t)(start + i - 1) * 2 + 1];
      acc += (abs(dl) + abs(dr)) / 2.0;
    }
    avg_step = count > 1 ? acc / (count - 1) : 0;
  }

  if (json) {
    printf("{\"ok\":true,\"wav\":\"%s\",\"frames\":%d,\"rate\":%d,"
           "\"seconds\":%.3f,\"peak_l\":%.0f,\"peak_r\":%.0f,"
           "\"rms_l\":%.1f,\"rms_r\":%.1f,\"period_samples\":%ld,"
           "\"period_seconds\":%.6f,\"period_diff\":%.2f,\"loop_written\":%d,"
           "\"loop_start\":%d,\"loop_frames\":%d,\"seam_jump\":%.1f,"
           "\"avg_step\":%.2f",
           in_path, produced, rate, (double)produced / rate, peakL, peakR,
           rmsL, rmsR, period, period ? (double)period / rate : 0, period_score,
           written, start, count, seam_jump, avg_step);
    if (loop_out) printf(",\"loop_out\":\"%s\"", loop_out);
    printf(",\"candidates\":[");
    for (int k = 0; k < 5; k++)
      printf("%s{\"seconds\":%.4f,\"corr\":%.4f}", k ? "," : "",
             (double)cand_lag[k] * ENV_BUCKET / rate, cand[k]);
    printf("]}\n");
  } else if (!csv) {
    printf("%s: %d frames %.2f s @ %d Hz, rms %.1f/%.1f\n", in_path, produced,
           (double)produced / rate, rate, rmsL, rmsR);
    if (period)
      printf("period %ld frames (%.4f s), mean|diff| %.2f\n", period,
             (double)period / rate, period_score);
    if (written)
      printf("loop %s: %d frames from %d, seam jump %.1f (typical step %.2f)\n",
             loop_out, count, start, seam_jump, avg_step);
  }

  free(w.pcm);
  return 0;
}
