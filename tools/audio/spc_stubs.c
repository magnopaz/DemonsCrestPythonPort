/* Stubs for the oracle's observability hooks, so its SPC700 + S-DSP cores can
 * be built into the offline .spc renderer (tools/audio/spc_render.c) without
 * the runner's RTL, audio device, or trace storage.  The renderer never
 * enables the shadow mixer or the forensic verifiers, so no-ops are exact. */
#include <stddef.h>
#include <stdint.h>

#include "audio_trace.h"
#include "snes/dsp_shadow.h"

/* apu.c's timer diagnostic counter lives in common_rtl.c. */
uint64_t g_apu_timer0_total_ticks;

/* The port-ring handshake snapshot (defined in audio_trace.c in the runner). */
uint8_t g_audio_trace_out_ports[4];
uint32_t g_audio_trace_apu_cycles;

void audio_trace_on_sample(int16_t l, int16_t r, int dropped, uint32_t ring_fill) {
  (void)l; (void)r; (void)dropped; (void)ring_fill;
}
void audio_trace_on_reg_write(uint8_t addr, uint8_t val) { (void)addr; (void)val; }
void audio_trace_on_consume(uint64_t read_idx, uint32_t count, uint32_t avail_after) {
  (void)read_idx; (void)count; (void)avail_after;
}
void audio_trace_on_shadow_div(double dl, double dr) { (void)dl; (void)dr; }
void audio_trace_on_faithful_div(double d) { (void)d; }
void audio_trace_on_brr_compare(uint16_t block, uint8_t header, uint8_t sample,
                                int canon, int reference, int old, int older) {
  (void)block; (void)header; (void)sample;
  (void)canon; (void)reference; (void)old; (void)older;
}
void audio_trace_on_echo_div(double d) { (void)d; }
void audio_trace_on_pace(int consumer_active, uint32_t baseline_cycles) {
  (void)consumer_active; (void)baseline_cycles;
}
void audio_trace_on_guest_sync(int frame_boundary, uint64_t cycles) {
  (void)frame_boundary; (void)cycles;
}
void audio_trace_on_fast_forward_discard(uint32_t samples,
                                         uint32_t occupancy_after) {
  (void)samples; (void)occupancy_after;
}
void audio_trace_on_output_underflow(uint32_t occupancy, uint32_t missing_frames) {
  (void)occupancy; (void)missing_frames;
}
void audio_trace_on_output_priming(uint32_t occupancy) { (void)occupancy; }
void audio_trace_on_cpu_port_write(uint8_t port, uint8_t val) { (void)port; (void)val; }
void audio_trace_on_cpu_port_apply(uint8_t port, uint8_t val) { (void)port; (void)val; }
void audio_trace_on_spc_port_read(uint8_t port, uint8_t val) { (void)port; (void)val; }
void audio_trace_on_spc_port_write(uint8_t port, uint8_t val) { (void)port; (void)val; }
void audio_trace_on_cpu_port_read(uint8_t port, uint8_t val) { (void)port; (void)val; }

DspShadow* dsp_shadow_create(void) { return NULL; }
void dsp_shadow_free(DspShadow* sh) { (void)sh; }
void dsp_shadow_process(DspShadow* sh, Dsp* dsp, int canonL, int canonR,
                        int* outL, int* outR) {
  (void)sh; (void)dsp;
  if (outL) *outL = canonL;
  if (outR) *outR = canonR;
}
void dsp_shadow_verify_brr(const uint8_t* aram, uint16_t blockStart,
                           int oldSeed, int olderSeed, const int16_t* canonOut16) {
  (void)aram; (void)blockStart; (void)oldSeed; (void)olderSeed; (void)canonOut16;
}
void dsp_shadow_verify_echo(const int16_t* firL, const int16_t* firR,
                            const int8_t* coeff, int idx,
                            int canonSumL, int canonSumR) {
  (void)firL; (void)firR; (void)coeff; (void)idx; (void)canonSumL; (void)canonSumR;
}
