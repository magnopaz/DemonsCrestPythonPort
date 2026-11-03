/*
 * spc_render — render a .spc (v0.30) to WAV with the oracle's own SPC700 and
 * S-DSP cores, and optionally find the music's loop period.
 *
 * Why this exists
 * ---------------
 * The ROM's soundtrack is not sample data you can lift out: it is an SPC700
 * program plus BRR samples driven by the S-DSP.  The recomp's debug server
 * snapshots the live APU as a standard `.spc` (`spc_dump`, 64 KB ARAM + 128
 * DSP registers + SPC700 registers).  This tool renders such a snapshot
 * offline, using the very cores the port's oracle already validated
 * (`snesrecomp/runner/src/snes/{spc,dsp,apu}.c`), so what lands in the game is
 * the ROM's own audio, produced by the same DSP math the console used.
 *
 * It sends no CPU->APU port traffic, so the music driver keeps ticking on its
 * own timers and the render is music only (no gameplay SFX), which is exactly
 * what a music loop needs.
 *
 * Loop finding
 * ------------
 * The driver loops the sequence internally, so the render is periodic after
 * the first pass.  `--find-loop a,b` searches the period in [a,b] seconds:
 * a 10 ms RMS-envelope correlation picks the coarse period, then an exact
 * sample-domain search (+-200 samples) minimises the mean |difference| over a
 * window.  `--loop-out` then cuts `period` samples starting at
 * `--loop-start`, and the seam residual is reported so a bad loop cannot pass
 * silently (a seamless loop has an end sample equal to the start sample,
 * because the signal is periodic by construction).
 *
 * Usage:
 *   spc_render in.spc out.wav --seconds 120 --find-loop 5,110 \
 *              --loop-out loop.wav --loop-start 40
 *
 * Notes on fidelity: a .spc carries ARAM, the 128 DSP registers and the SPC700
 * registers, but not the per-voice envelope/decode position, so every voice
 * key-ons at load.  That is standard SPC-player behaviour: the first fraction
 * of a second is the driver's own attack ramp, not a render bug.  Pick a
 * `--loop-start` after it.
 */
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "apu.h"
#include "dsp.h"
#include "spc.h"

#define SPC_SIZE 0x10200
#define NATIVE_RATE 32040
#define ENV_BUCKET 320 /* ~10 ms of native samples */

static void wr32le(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16);
  p[3] = (uint8_t)(v >> 24);
}

static void wr16le(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}

static int write_wav(const char *path, const int16_t *pcm, int frames,
                     int start, int count, int rate) {
  if (count <= 0 || start < 0 || start + count > frames) return -1;
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

/* Load a v0.30 image into a fresh Apu. Returns 0 on success. */
static int spc_load(Apu *apu, const uint8_t *img) {
  Spc *spc = apu->spc;
  Dsp *dsp = apu->dsp;

  memcpy(apu->ram, img + 0x100, 0x10000);

  spc->pc = (uint16_t)(img[0x25] | (img[0x26] << 8));
  spc->a = img[0x27];
  spc->x = img[0x28];
  spc->y = img[0x29];
  uint8_t psw = img[0x2a];
  spc->n = (psw >> 7) & 1;
  spc->v = (psw >> 6) & 1;
  spc->p = (psw >> 5) & 1;
  spc->b = (psw >> 4) & 1;
  spc->h = (psw >> 3) & 1;
  spc->i = (psw >> 2) & 1;
  spc->z = (psw >> 1) & 1;
  spc->c = (psw >> 0) & 1;
  spc->sp = img[0x2b];

  /* CPU->SPC ports as the engine last saw them, then the timer/IO config.
   * $F1 enables the timers the music driver runs on; without it the driver
   * never ticks, which is the classic "silent .spc" failure. */
  apu->inPorts[0] = img[0x100 + 0xf4];
  apu->inPorts[1] = img[0x100 + 0xf5];
  apu->inPorts[2] = img[0x100 + 0xf6];
  apu->inPorts[3] = img[0x100 + 0xf7];
  apu->inPorts[4] = img[0x100 + 0xf8];
  apu->inPorts[5] = img[0x100 + 0xf9];
  memset(apu->outPorts, 0, sizeof(apu->outPorts));

  uint8_t f1 = img[0x100 + 0xf1];
  for (int i = 0; i < 3; i++) {
    apu->timer[i].enabled = (f1 >> i) & 1;
    apu->timer[i].target = img[0x100 + 0xfa + i];
    apu->timer[i].counter = img[0x100 + 0xfd + i] & 0x0f;
    apu->timer[i].divider = 0;
    apu->timer[i].cycles = 0;
  }
  apu->romReadable = (f1 & 0x80) != 0;
  apu->dspAdr = img[0x100 + 0xf2];

  /* The 128 DSP registers, ascending so pitch/source/ADSR land before KON.
   * DC_SPC_NO_DSP=1 skips them: the SPC does not need them, so this isolates
   * "the DSP register load changes APU RAM" from "the driver needs a CPU". */
  if (!getenv("DC_SPC_NO_DSP"))
    for (int r = 0; r < 0x80; r++)
      dsp_write(dsp, (uint8_t)r, img[0x10100 + r]);
  if (getenv("DC_SPC_NO_ECHO"))
    dsp_write(dsp, 0x6c, (uint8_t)(img[0x10100 + 0x6c] | 0x20));

  if (getenv("DC_SPC_DUMP_LOAD")) {
    fprintf(stderr,
            "load: pc=%04X a=%02X x=%02X y=%02X sp=%02X psw=%02X "
            "f1=%02X timers=%d/%d/%d tgt=%d/%d/%d cnt=%d/%d/%d rom=%d\n",
            spc->pc, spc->a, spc->x, spc->y, spc->sp, psw, f1,
            apu->timer[0].enabled, apu->timer[1].enabled, apu->timer[2].enabled,
            apu->timer[0].target, apu->timer[1].target, apu->timer[2].target,
            apu->timer[0].counter, apu->timer[1].counter, apu->timer[2].counter,
            apu->romReadable);
  }
  return 0;
}

/* Mean |difference| between the two channels of two windows of `len` frames. */
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
  if (argc < 3) {
    fprintf(stderr,
            "usage: %s in.spc out.wav [--seconds N] [--json] "
            "[--find-loop MIN,MAX] [--loop-start S] [--loop-out PATH]\n",
            argv[0]);
    return 2;
  }
  const char *in_path = argv[1];
  const char *out_path = argv[2];
  double seconds = 30.0;
  bool json = false;
  double loop_min = 0, loop_max = 0;
  double loop_start = -1;
  const char *loop_out = NULL;
  int trace_every = 0;
  int timer_phase = -1;
  const char *ports_path = NULL;
  const char *dump_aram_path = NULL;
  long port_offset = 0;

  for (int i = 3; i < argc; i++) {
    if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
      seconds = atof(argv[++i]);
    } else if (!strcmp(argv[i], "--json")) {
      json = true;
    } else if (!strcmp(argv[i], "--find-loop") && i + 1 < argc) {
      if (sscanf(argv[++i], "%lf,%lf", &loop_min, &loop_max) != 2) {
        fprintf(stderr, "spc_render: --find-loop needs MIN,MAX seconds\n");
        return 2;
      }
    } else if (!strcmp(argv[i], "--loop-start") && i + 1 < argc) {
      loop_start = atof(argv[++i]);
    } else if (!strcmp(argv[i], "--loop-out") && i + 1 < argc) {
      loop_out = argv[++i];
    } else if (!strcmp(argv[i], "--trace-every") && i + 1 < argc) {
      trace_every = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--timer-phase") && i + 1 < argc) {
      timer_phase = atoi(argv[++i]);
    } else if (!strcmp(argv[i], "--dump-aram") && i + 1 < argc) {
      dump_aram_path = argv[++i];
    } else if (!strcmp(argv[i], "--ports") && i + 1 < argc) {
      ports_path = argv[++i];
    } else if (!strcmp(argv[i], "--port-offset") && i + 1 < argc) {
      port_offset = atol(argv[++i]);
    } else {
      fprintf(stderr, "spc_render: unknown arg %s\n", argv[i]);
      return 2;
    }
  }

  FILE *f = fopen(in_path, "rb");
  if (!f) {
    fprintf(stderr, "spc_render: cannot open %s\n", in_path);
    return 1;
  }
  uint8_t *img = malloc(SPC_SIZE);
  if (!img) {
    fclose(f);
    return 1;
  }
  size_t got = fread(img, 1, SPC_SIZE, f);
  fclose(f);
  if (got != SPC_SIZE) {
    fprintf(stderr, "spc_render: %s is %zu bytes, expected %d\n", in_path, got,
            SPC_SIZE);
    free(img);
    return 1;
  }
  if (memcmp(img, "SNES-SPC700 Sound File Data", 27) != 0) {
    fprintf(stderr, "spc_render: %s is not a .spc file\n", in_path);
    free(img);
    return 1;
  }

  Apu *apu = apu_init();
  if (!apu || spc_load(apu, img) != 0) {
    fprintf(stderr, "spc_render: failed to load %s\n", in_path);
    return 1;
  }

  if (timer_phase >= 0) {
    /* The .spc carries the timer counter but not the divider phase. Sweeping it
     * answers "is the driver sensitive to where in a timer period it resumes?" */
    for (int i = 0; i < 3; i++) {
      apu->timer[i].divider = (uint8_t)(timer_phase % 256);
      apu->timer[i].cycles = 0;
    }
  }

  int frames = (int)(seconds * NATIVE_RATE + 0.5);
  int16_t *pcm = calloc((size_t)frames * 2, sizeof(int16_t));
  if (!pcm) {
    fprintf(stderr, "spc_render: out of memory for %d frames\n", frames);
    return 1;
  }

  static uint16_t pc_ring[4096];
  static uint8_t op_ring[4096];
  static uint16_t pc_head[300];
  static uint8_t op_head[300];
  unsigned pc_n = 0;
  uint16_t last_pc = 0xffff;
  int derail_seen = 0;
  unsigned derail_at = 0;
  uint16_t derail_pc = 0;
  /* CPU->APU port traffic, replayed at its live sample time. A bare .spc has
   * no CPU behind it; this driver polls $F4 in its main loop and needs the
   * game's command bytes to stay on its rails. */
  static long port_s[20000];
  static int port_p[20000], port_v[20000];
  int port_count = 0;
  if (ports_path) {
    FILE *pf = fopen(ports_path, "r");
    if (!pf) {
      fprintf(stderr, "spc_render: cannot open %s\n", ports_path);
      return 1;
    }
    long s;
    int p, v;
    while (port_count < 20000 && fscanf(pf, "%ld %d %d", &s, &p, &v) == 3) {
      port_s[port_count] = s;
      port_p[port_count] = p;
      port_v[port_count] = v;
      port_count++;
    }
    fclose(pf);
  }
  int port_n = 0;

  int produced = 0;
  int16_t chunk[1024 * 2];
  while (produced < frames) {
    int want = frames - produced;
    if (want > 1024) want = 1024;
    /* 32 APU cycles per native sample (dsp_cycle runs at (cycles & 31) == 0). */
    for (int n = 0; n < want; n++) {
      /* Interleave the CPU's port writes at their live sample time. */
      while (port_n < port_count &&
             port_s[port_n] - port_offset <= produced + n) {
        apu_writePortNow(apu, (uint8_t)port_p[port_n], (uint8_t)port_v[port_n]);
        port_n++;
      }
      for (int k = 0; k < 32; k++) {
        uint16_t pc = apu->spc->pc;
        if (pc != last_pc) {
          if (!derail_seen && pc < 0x0100 && last_pc >= 0x0100) {
            derail_seen = 1;
            derail_at = pc_n;
            derail_pc = pc;
          }
          pc_ring[pc_n & 4095] = pc;
          op_ring[pc_n & 4095] = apu->ram[pc];
          if (pc_n < 300) {
            pc_head[pc_n] = pc;
            op_head[pc_n] = apu->ram[pc];
          }
          pc_n++;
          last_pc = pc;
        }
        apu_cycle(apu);
      }
    }
    uint32_t got_frames = dsp_getSamples(apu->dsp, chunk, want);
    if (got_frames == 0) break;
    if (trace_every > 0 && produced / trace_every !=
                                (produced + (int)got_frames) / trace_every) {
      Dsp *d = apu->dsp;
      fprintf(stderr,
              "[spc t=%.2fs] pc=%04X a=%02X x=%02X y=%02X sp=%02X "
              "in=%02X%02X%02X%02X out=%02X%02X%02X%02X "
              "t0=%d/%d/%d key=%02X env=",
              (double)(produced + got_frames) / NATIVE_RATE, apu->spc->pc,
              apu->spc->a, apu->spc->x, apu->spc->y, apu->spc->sp,
              apu->inPorts[0], apu->inPorts[1], apu->inPorts[2],
              apu->inPorts[3], apu->outPorts[0], apu->outPorts[1],
              apu->outPorts[2], apu->outPorts[3], apu->timer[0].target,
              apu->timer[0].divider, apu->timer[0].counter,
              d->ram[0x4c]);
      for (int v = 0; v < 8; v++)
        fprintf(stderr, "%d:%d,%u,%d ", v, d->channel[v].adsrState,
                d->channel[v].gain, d->channel[v].sampleOut);
      fprintf(stderr, "\n");
    }
    memcpy(&pcm[(size_t)produced * 2], chunk,
           (size_t)got_frames * 2 * sizeof(int16_t));
    produced += (int)got_frames;
  }

  if (dump_aram_path) {
    FILE *af = fopen(dump_aram_path, "wb");
    if (af) {
      fwrite(apu->ram, 1, 0x10000, af);
      fclose(af);
    }
  }

  double sumL = 0, sumR = 0;
  int peakL = 0, peakR = 0;
  long long dcL = 0, dcR = 0;
  for (int i = 0; i < produced; i++) {
    int l = pcm[i * 2], r = pcm[i * 2 + 1];
    sumL += (double)l * l;
    sumR += (double)r * r;
    dcL += l;
    dcR += r;
    if (abs(l) > peakL) peakL = abs(l);
    if (abs(r) > peakR) peakR = abs(r);
  }
  double rmsL = produced ? sqrt(sumL / produced) : 0;
  double rmsR = produced ? sqrt(sumR / produced) : 0;

  if (write_wav(out_path, pcm, produced, 0, produced, NATIVE_RATE) != 0) {
    fprintf(stderr, "spc_render: cannot write %s\n", out_path);
    free(pcm);
    apu_free(apu);
    free(img);
    return 1;
  }

  /* ---- loop search -------------------------------------------------- */
  long period = 0;
  double period_score = 0;
  if (loop_max > loop_min && loop_max > 0) {
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
      /* Mean-removed, unit-norm envelope: correlation of the whole render
       * against itself shifted by the candidate lag. */
      double mean = 0;
      for (int i = 0; i < env_n; i++) mean += env[i];
      mean /= env_n ? env_n : 1;
      double norm = 0;
      for (int i = 0; i < env_n; i++) {
        env[i] = (float)(env[i] - mean);
        norm += (double)env[i] * env[i];
      }
      norm = sqrt(norm);

      int lag_lo = (int)(loop_min * NATIVE_RATE / ENV_BUCKET);
      int lag_hi = (int)(loop_max * NATIVE_RATE / ENV_BUCKET);
      if (lag_lo < 1) lag_lo = 1;
      if (lag_hi > env_n - 1) lag_hi = env_n - 1;

      double best = -2;
      int best_lag = 0;
      for (int lag = lag_lo; lag <= lag_hi; lag++) {
        double dot = 0, na = 0, nb = 0;
        int n = env_n - lag;
        for (int i = 0; i < n; i++) {
          double a = env[i], b = env[i + lag];
          dot += a * b;
          na += a * a;
          nb += b * b;
        }
        double c = (na > 0 && nb > 0) ? dot / sqrt(na * nb) : -2;
        if (c > best) {
          best = c;
          best_lag = lag;
        }
      }
      long coarse = (long)best_lag * ENV_BUCKET;
      /* Exact refinement in the sample domain: mean |diff| over a 6 s window
       * that starts after the first pass. */
      int win_start = produced / 2;
      int win_len = 6 * NATIVE_RATE;
      if (win_start + win_len >= produced) {
        win_start = produced / 3;
        win_len = produced - win_start;
      }
      if (win_len > produced - win_start) win_len = produced - win_start;
      double best_diff = -1;
      long best_p = coarse;
      for (long p = coarse - 200; p <= coarse + 200; p++) {
        if (p <= 0) continue;
        if (win_start + p + win_len > produced) continue;
        double d = window_diff(pcm, win_start, win_start + (int)p, win_len);
        if (best_diff < 0 || d < best_diff) {
          best_diff = d;
          best_p = p;
        }
      }
      period = best_p;
      period_score = best_diff < 0 ? 0 : best_diff;
      free(env);
    }
  }

  int loop_start_frame = -1;
  int loop_count = 0;
  double seam_jump = 0;
  int loop_written = 0;
  if (loop_out && period > 0) {
    int start = loop_start >= 0 ? (int)(loop_start * NATIVE_RATE + 0.5) : 0;
    if (start + period > produced) start = produced - (int)period;
    if (start < 0) start = 0;
    loop_start_frame = start;
    loop_count = (int)period;
    if (write_wav(loop_out, pcm, produced, start, loop_count, NATIVE_RATE) == 0)
      loop_written = 1;
    /* Seam: the frame after the cut must flow into the first frame of the cut
     * as smoothly as any other adjacent pair. */
    int after = start + loop_count;
    if (after < produced) {
      int dl = pcm[(size_t)after * 2] - pcm[(size_t)(after - 1) * 2];
      int dr = pcm[(size_t)after * 2 + 1] - pcm[(size_t)(after - 1) * 2 + 1];
      seam_jump = (abs(dl) + abs(dr)) / 2.0;
    }
  }

  if (derail_seen) {
    fprintf(stderr, "spc_render: control entered zero page at PC %04X after"
                    " instruction %u; preceding 48:\n", derail_pc, derail_at);
    unsigned from = derail_at > 48 ? derail_at - 48 : 0;
    for (unsigned i = from; i < derail_at; i++)
      fprintf(stderr, "%04X:%02X%s", pc_ring[i & 4095], op_ring[i & 4095],
              ((i - from + 1) % 12) ? " " : "\n");
    fprintf(stderr, "\n");
  }

  if (getenv("DC_SPC_PC_RING")) {
    /* The ring keeps the last 4096 distinct PCs; report the head (entry) and
     * the tail (where it ended up), which is what a bad snapshot needs. */
    unsigned head_end = pc_n < 300 ? pc_n : 300;
    fprintf(stderr, "spc_render: first PCs:\n");
    for (unsigned i = 0; i < head_end; i++)
      fprintf(stderr, "%04X:%02X%s", pc_head[i], op_head[i],
              ((i + 1) % 12) ? " " : "\n");
    fprintf(stderr, "\nspc_render: last PCs (%u distinct):\n", pc_n);
    unsigned start_i = pc_n > 96 ? pc_n - 96 : 0;
    for (unsigned i = start_i; i < pc_n; i++)
      fprintf(stderr, "%04X:%02X%s", pc_ring[i & 4095], op_ring[i & 4095],
              ((i - start_i + 1) % 12) ? " " : "\n");
    fprintf(stderr, "\n");
  }

  if (json) {
    printf("{\"ok\":true,\"spc\":\"%s\",\"wav\":\"%s\",\"frames\":%d,"
           "\"rate\":%d,\"seconds\":%.3f,\"peak_l\":%d,\"peak_r\":%d,"
           "\"rms_l\":%.1f,\"rms_r\":%.1f,\"dc_l\":%.3f,\"dc_r\":%.3f,"
           "\"period_samples\":%ld,\"period_seconds\":%.6f,"
           "\"period_diff\":%.2f,\"loop_written\":%d,"
           "\"loop_start\":%d,\"loop_frames\":%d,\"seam_jump\":%.1f}",
           in_path, out_path, produced, NATIVE_RATE,
           (double)produced / NATIVE_RATE, peakL, peakR, rmsL, rmsR,
           produced ? (double)dcL / produced : 0,
           produced ? (double)dcR / produced : 0, period,
           period ? (double)period / NATIVE_RATE : 0, period_score,
           loop_written, loop_start_frame, loop_count, seam_jump);
    if (loop_out)
      printf(",\"loop_out\":\"%s\"", loop_out);
    printf("}\n");
  } else {
    printf("rendered %d frames (%.2f s) %d Hz stereo, peak %d/%d rms %.1f/%.1f\n",
           produced, (double)produced / NATIVE_RATE, NATIVE_RATE, peakL, peakR,
           rmsL, rmsR);
    if (period)
      printf("loop period %ld frames (%.4f s), mean|diff| %.1f\n", period,
             (double)period / NATIVE_RATE, period_score);
    if (loop_written)
      printf("wrote %s: %d frames from %d (seam jump %.1f)\n", loop_out,
             loop_count, loop_start_frame, seam_jump);
  }

  free(pcm);
  apu_free(apu);
  free(img);
  return 0;
}
