# Audio: playing the ROM's music and sound effects

Status: **every stage theme is the ROM's own audio**, one looping WAV per room
family, selected by the port from a measured room table.  One sound effect
(the jump) is the console's own; the rest are still synthesised (see
"Still to do").  The colosseum theme (`music_boss.wav`, area 0) was the first
one captured; this session extended the same pipeline to the whole game.

## What "correct" means here

- the colosseum theme (and every other stage/town track) played from the ROM's own
  music data, not an imitation;
- the original SFX: jump, land, wing flap, fireball, urn break, pickup, hurt,
  enemy hit, boss roar, gate, menu;
- the same trigger points the original uses (the port already fires events for
  most of them — `OBJECT_EVENT_BREAK`, `OBJECT_EVENT_ENEMY_HIT`, etc.).

## The hard part, stated plainly

The SNES soundtrack lives in SPC700 code plus BRR samples driven by the S-DSP.
There is **no** audio data you can just read out and play: the music *is* a
program for the APU. Three routes:

1. **Emulate the APU** (SPC700 + DSP) and feed it the ROM's audio program.
2. **Render offline, ship audio files.**
3. **Re-author the music natively** from the sequence data.

## What was done (2026-11-02)

### The dump: the oracle's APU snapshots cleanly

`spc_dump <path>` (debug server) already existed: it writes a standard `.spc`
v0.30 (64 KB ARAM + 128 DSP registers + SPC700 registers + a synthesized
`$F0-$FF` IO region). `tools/audio/dump_spc.py` drives it deterministically —
resume a save paused, run N frames, snapshot — and records provenance: the
save's and ROM's SHA-1, the frame, and **the guest's area byte (`$008D`)** so a
dump cannot be silently attributed to the wrong room. Verified on
`somulo_player_control.sav`: area 0, `music.spc` = 66,048 bytes,
`spc_pc=0x046A`.

### The trap: a bare `.spc` does not survive this game's driver

`tools/audio/spc_render.c` renders a `.spc` offline with the oracle's own
SPC700 + S-DSP cores and can trace the SPC's PC stream. Result: after a bare
resume the driver plays ~2 s and then executes data, ending in a `STOP` (0xFF)
at `$FFB5`.

Measured evidence:

- the first PCs are the driver's main loop (`$046A` port poll → `$02FC` timer
  accumulate → `BEQ $02F9`), with timer 0 running (target 64, counter
  advancing) — so the load itself is right;
- the derail is not a bad snapshot: six dumps at different frames all die the
  same way, and replaying the CPU→APU port writes captured by `audio_events`
  does not save it;
- the **live** game never executes that `STOP`: `SNESRECOMP_SPC_TRACE=1` over
  600 frames reports no HALT.

Conclusion: this driver needs the CPU behind it (it polls `$F4` and takes
branches on the game's command handshake), so a `.spc` resumed with no CPU is
not a viable render source here. Whether a full SPC player (game-music-emu,
which models timer IRQs) would fare better is **untested** and is the first
thing to try if the offline path is ever needed again — the tool and the dump
are kept for exactly that.

### The route that works: the oracle's own DSP output

`audio_wav <path> [start] [count]` dumps the DSP's native output ring (32040 Hz
stereo, the S-DSP rate). That is the emulated console's own samples, which is
what the plan allows and what "real audio" means here.

`tools/audio/capture_music.py` records it deterministically:

- resume the save, settle, then **neutralise the object pool** (`$1080`,
  stride `$50`, 26 slots — zero the active byte of every slot). Area 0's save
  is mid-boss-fight, so a naive capture is full of roars and hits; with the
  enemies gone the capture is music only (peak 25,121 → 11,043, RMS steady at
  ~1,778) and no SFX are triggered.
- run 120 s, then pull the last N seconds from the ring.

### The loop is measured, not guessed

`tools/audio/wav_loop.c` finds the period with a 10 ms RMS-envelope
correlation, refines it in the sample domain, then snaps the cut point to where
the end flows into the start most cleanly.

Measured on the colosseum capture:

| value | measurement |
|---|---|
| period | 1,311,739 samples = **40.941 s** (envelope correlation 0.880; the 20.47 s peak is its half) |
| seam jump | **210.5** vs a typical adjacent-sample step of **415.1** → 0.51× |
| asset | `assets/generated/audio/music_boss.wav`, 32,040 Hz stereo, RMS 1,778, peak 9,502 |

A seam smaller than an ordinary sample step is why the loop has no click — the
cut does not need a crossfade, and the check refuses a cut whose seam exceeds
4× the typical step.

### In the port

`src/audio.c` loads `<assets>/audio/<track>.wav` for each `MusicTrack` and
falls back to the procedural loop only when the file is absent. `Music.looping`
is on, and a headless run with a null ALSA PCM shows the stream clock crossing
the boundary (`t=40.875 → 0.553`), i.e. raylib restarts the track at the exact
sample boundary.

Debug hooks: `DC_AUDIO_DEBUG=1` prints which file each track loaded from
(`ROM` vs `procedural`), and `DC_AUDIO_PROBE=1` prints
`audio: probe track= rom= time= playing=` every 60 frames.

### Verification (no ear test)

`tools/check_audio_assets.py`, run by `tools/run_regression.py` (77 = no
assets, i.e. skip):

1. **asset** — manifest hash, 32,040 Hz stereo, non-silent, frame count, loop
   length in range, seam ratio ≤ 4×;
2. **playback** — a headless run at the track's area logs
   `music_boss.wav ... (ROM)` and a probe line with `rom=1`, `playing=1`, and a
   stream clock that advanced;
3. **determinism** — the same 600-frame demo with audio forced on and with
   `DC_NO_AUDIO=1` produces **byte-identical** trace CSVs, so audio cannot
   perturb the simulation.

### Reproducing it

```sh
tools/audio/build_audio_tools.sh         # spc_render + apu_host
python3 tools/audio/dump_spc.py --save <save> --out captures/audio/<name>   # .spc artifact
python3 tools/audio/make_music_asset.py  # capture -> loop -> asset + manifest
python3 tools/check_audio_assets.py      # the three checks above
```

`tools/build_assets.sh` runs the music step (reusing `captures/audio/` when
present, capturing from the oracle otherwise, and skipping cleanly when neither
exists); `--no-audio` disables it. Track specs live in
`tools/audio/music_tracks.json`. Every generated file stays git-ignored.

## Route 1 investigation: can the port run the driver itself? (2026-11-02, S1)

Yes in principle, and the pieces are now identified — but **not from a snapshot**.

### The upload is the CPU's, and the game does not declare an HLE hook

`recomp/bank00.cfg` has no `hle_spc_upload` directive, so Demon's Crest uploads
the sound driver through the plain IPL byte-by-byte protocol, driven by guest
code. There is no tidy "block stream in the ROM" to lift: the CPU half of the
transfer is real work the console did.

Measured on a cold boot (`tools/audio/boot_capture.py`):

| observation | measurement |
|---|---|
| driver in ARAM | by frame 20 (`$046A` region non-zero) |
| idle point at frame 60 | PC `$048C`/`$0470` (the `$046A` port-poll loop) |
| first upload | 2001 CPU writes between samples 561 and 1346 (~0.8 s) |
| next CPU→APU traffic | none until sample ~68,700 |
| second upload (music bank) | 1999 writes at sample ~68,746 (frame ~128) |
| after that | **no CPU→APU writes at all**, and music plays |

Two consequences: the driver is self-sufficient during playback (no per-frame
commands), and everything the port needs to reproduce is the two uploads.

### Booting an embedded APU from the clean image works

`tools/audio/apu_host` (new) boots the oracle's SPC700 + DSP from a captured
ARAM image and an entry PC. From the frame-60 image, entry `$046A`:

```
aram f0060 entry 0x046A: rendered 20.00 s, peak 0/0 rms 0.0/0.0, halted_at=-1
```

No halt and no sound — correct: the driver is idling and no music bank is
loaded. The core, the image and the loader are fine.

### But mid-song `.spc` snapshots derail, and the DSP is the trigger

Every mid-song snapshot (colosseum fight, title screen with music) derails in
the embedded APU after ~13k instructions, ending in a `STOP` executed from data.
Isolating the input:

| render | result |
|---|---|
| `.spc` with all 128 DSP registers | derails (executes data, `STOP` at `$FE83`/`$FFB5`) |
| `.spc`, DSP registers skipped (`DC_SPC_NO_DSP=1`) | no halt, silent |
| `.spc`, DSP registers loaded but echo disabled (`DC_SPC_NO_ECHO=1`) | no halt, music plays ~5 s then goes quiet (rms ~1.9) |

So the driver's behaviour depends on the **DSP's echo state**, not only on ARAM
and the register image. A `.spc` cannot carry the DSP's per-voice and echo
state, which is why resuming one hijacks the driver's control flow — the same
reason the earlier six-dump sweep failed.

### What the port's APU host must do (next step)

1. **Boot**: upload the driver image (a captured post-boot ARAM is enough — it
   runs forever) and jump to the entry.
2. **Load a song**: replay the bank upload *with the handshake*. A raw replay of
   the captured writes produces silence, because the IPL transfer is
   request/acknowledge: the CPU writes a byte and waits for the SPC's answer on
   `$2142`/`$2143` before the next one. The oracle's RTL already models this
   (`apu_waitForTransferReady`, `apu_finishHleTransfer`) and is the reference to
   port.
3. **Play**: nothing else — playback needs no commands, so SFX become the only
   runtime traffic (their ids are in the captured stream).

Success criterion for the next session: `apu_host` renders 60 s of the
colosseum theme from the embedded APU, A/B against `music_boss.wav`, without a
halt and without echo tricks.

Tools added for this: `apu_host.c` (boot + render + port replay + ARAM dump),
`boot_capture.py`, `press_probe.py`, `aram_compare.py` (live-vs-offline ARAM
diff), `capture_upload.py`, and the `--aram`/`--entry`/`--ports`/`--port-offset`
flags they use.

### Where the capture of that handshake stands

Two blockers, both measured:

- The driver's code region is in the ROM **linearly**, not as a length/target
  block stream: ARAM `$02C0..$0DA0` is byte-identical to file `0x3010C..0x30BEC`
  (constant delta `0x2FE4C`), and the bytes right after that region are not a
  terminator. So there is no header to parse — a "boot from ROM" path would copy
  that region directly, and the *bank* would have to come from elsewhere.
- The CPU->APU writes cannot be captured through `audio_events`: that command
  reads the general event ring, and the DSP's register writes (thousands per
  second) push the transfer out of it within a second. A dedicated port ring
  exists (`AUDIO_TRACE_PORT_RING`, 65536 events, written to `.apu.tsv` by
  `state_dump.c`) but **no debug-server command exposes it**, and adding one
  needs the oracle to build — currently broken by unrelated widescreen work
  (`src/dc_widescreen.c` calls `PpuSetWidescreenLayerRightEdge`, which the
  submodule no longer has).

### The port ring, and what the replay showed

The ring was exposed (a `port_events <path>` command was added to the oracle's
debug server, next to `spc_dump`) and the oracle was rebuilt — the build was
blocked by unrelated widescreen work, see the note at the end. With it:

- a cold boot produces **96,314 port events**; in the window from the frame-60
  ARAM to frame 145, **16,669** of them are CPU writes — the byte-by-byte IPL
  transfer (3-4 writes per byte), starting 35,892 samples after the ARAM dump;
- replaying those 16,669 writes into the embedded APU with a naive "wait for any
  change on the output ports" handshake (`apu_host --handshake`) is **silent**:
  30 s rendered, `halted_at=-1`, rms 0.0.

Two concrete gaps were then found and closed, in this order:

1. **The timer was missing.** ARAM alone does not describe the driver's
   timebase, and this driver's main loop is `MOV A,$FD` (timer 0) + accumulate.
   Booting from ARAM with the default (disabled) timer left the driver deaf:
   **33 acknowledgements out of 16,669 writes**. Loading the `.spc`'s synthesized
   `$F0-$FF` region at the same frame (`--spc-io`) raised that to **2,789**: the
   driver answers now, so the transfer path is live.
2. **The render clock is wrong for a handshake.** `apu_host` renders in sample
   time (32 APU cycles per output sample) while the handshake burns APU cycles
   inside the write loop, so the same run consumed 5.55e9 cycles (172 s of APU
   time) to produce a 30 s file. Even audio that did play would be compressed in
   time. The fix is to drive the file from APU time — emit a sample whenever
   `dsp_cycle` produces one — and let the write schedule follow that clock.

**Pacing now works.** With the timer fix, APU-time rendering and a heuristic
that paces only the transfer's own writes (a port-0 value that is the next index;
the CPU's `0xF9` polling writes must not be paced), a run acknowledges **8,348 of
8,617** writes — 97%. The driver is following the transfer.

**And it is still silent**, so the problem is no longer timing but content: the
bytes are delivered and acknowledged, and nothing plays. Two measurements shape
the next attempt:

- the driver does **not** answer `$CC` with the IPL ROM's `$AA/$BB` ready pair
  (post-boot it runs its own transfer routine): waiting for that pair at the
  block start stalls the whole replay (0 acks), so `$CC` is written unperformed;
- the best-acknowledged run ends mid-transfer (its window stops at frame 134),
  and the later window that reaches the end starts from a different point and
  collapses to 52 acks. The transfer has to be captured **complete and from its
  own beginning**, which the port ring can only do for a bounded window — so the
  transfer's length has to be established first (count the index sequence: it is
  the byte count), and the ring sampled at the exact frames that bracket it.

The capture is now complete: sampling the ring every 4 frames over the transfer
and merging on the sample clock reconstructs **65,936** CPU writes (the dumps
overlap, so it is complete rather than truncated). Replaying that whole stream
acknowledges **33,325 of 65,936** writes — about half — and still renders
silence.

### The conclusion, and the two honest ways forward

A write log cannot reconstruct a handshake. It records what the CPU wrote at
wall-clock sample times, not what it wrote *in response to each acknowledge*, so
two writes that the console separated by an ack can look adjacent in the log and
vice versa. Half the writes landing is exactly the symptom: the driver follows
the parts that happen to line up and drifts on the rest. Booting from ARAM taken
*after* the transfer (frame 200, bank loaded) plus the timer is also silent, so
the missing piece is the transfer's own state machine, not the data.

Option 1 was then implemented and measured, and it closes the question the other
way:

- the port ring now records `outPorts[0..3]` with every `cpu_wr`
  (`g_audio_trace_out_ports`, published by `apu_writePortNow`), and
  `apu_host --state-wait` waits for exactly that state before writing each byte;
- with the stack pointer loaded from the `.spc` (a real bug: `--aram` used to
  start with `SP=0xEF`, so the driver's `RET` popped garbage), the embedded
  driver is healthy — after 2 s with no traffic it sits at `$0470` with `SP=$CD`,
  i.e. inside its port-poll loop;
- replaying the recorded stream with exact state waits still fails: **238
  acknowledgements out of 65,943**, and the driver ends at `$0A12`, off the poll
  loop.

The recorded states explain why: the console's stream begins at an index the
driver's own counter was already at (`$F9`) while our ARAM image is from before
the transfer (counter 0), so the two never agree on which byte comes next. In
other words the transfer has to be reproduced as a *protocol*, not as a log — the
data alone cannot say where in the transfer the console was.

### What finally worked, and what it showed

A different approach beat all the snapshot and handshake attempts: **replay the
console's whole timeline from power-on**. `apu_host --fresh` starts from
`apu_reset()` and applies the captured CPU writes at their recorded sample
times; `tools/audio/capture_boot_ports.py` merges repeated port-ring dumps so the
stream is complete from sample 0 (130,666 writes over 1,200 frames).

The result is real progress:

- the driver boots and runs: after 20 s the embedded APU sits at **`$046A`**, and
  after 21 s at **`$0302`** — the same poll loop and tempo loop the live console
  sits in;
- `tools/audio/compare_ab.py` measures the console's own timeline for the first
  time: music starts at **second 6** (frame ~360) and plays through second 9,
  then goes quiet;
- but the embedded run is silent through that window, and a byte-for-byte ARAM
  diff at frame 1260 shows **hundreds of pages differ** (`$0059..`, `$3400`,
  `$3D00`, `$5200`, ...). The replay reaches the same *code*, then diverges in
  *state*.

The divergence is the transfer's timing: the CPU's writes were queued with
per-write APU-cycle timestamps (`apu_schedulePortWrite`), while a sample index
only resolves 32 cycles and several writes share one bucket (the four writes of
the IPL request all land at sample 561). Spacing them by a fixed 24 cycles is
what let the driver boot at all, but it is still an approximation, and a
byte-by-byte handshake accumulates the error.

The cycle stamps were then recorded (the ring now carries `apu_cycles` per
event, published by `apu_writePortNow` next to `outPorts`) and replayed exactly:

| replay mode | driver ends at | audio |
|---|---|---|
| sample index + 24-cycle spacing | `$0302` (the console's tempo loop) | silent |
| exact cycle stamp, one write per cycle | `$15C9` | derails |

The obvious explanation — that the two clocks do not share an origin — was then
measured and **ruled out**. Polling `get_apu_misc` (the APU cycle counter) and
`audio_stats` (produced samples) at frames 0..600:

```
frame  cycles      produced   cycles/produced
    1       25266         790   31.9823
   60     1033458       32296   31.9996
  600    10261013      320657   32.0000
```

The ratio is exactly 32 from the first frame, so a fresh `apu_reset()` and the
oracle's counter do share an origin. The difference between the two replays is
elsewhere, and the first write shows it: the console's very first `$2143` write
carries cycle stamp **0**, while the sample-index replay lands it at sample 561
(cycle ~17,952) because the capture bucket is coarse. The exact replay applies it
at cycle 0, as the console did, and that is the run that derails.

Moving that first write to the second one's stamp (`0` → `17941`) was tested and
changes nothing: the run still ends at `$15C9`. So the cycle-0 event is not the
cause either.

What is left is the meaning of the stamp itself. The oracle runs the APU in
bursts (`apu_runToGuestCycle`), so `apu->cycles` at the hook is the cycle at
which the *emulator* applied the write, not necessarily the cycle at which the
console's CPU issued it — the queue drains when the emulator gets there. A
sample-index replay with 24-cycle spacing happens to land inside the window the
driver accepts; the exact-stamp replay lands where the emulator did, and the
driver takes a different branch.

That was tested as a shift sweep over the whole stream:

```
shift +16   -> driver ends at FFD2 (still inside the IPL)
shift +64   -> FFCF (IPL wait loop)
shift +256  -> 09A2
shift +1024 -> FFD2
shift +4096 -> FFCF
```

No shift boots it, and the unshifted stream stops at `$15C9` while the
sample-index replay reaches `$0302`. Even replaying only the first four writes
leaves the IPL waiting, which means those writes are not the upload request at
all — the real transfer happens inside the long stream, and the driver's
byte-by-byte handshake amplifies whatever drift the replay carries.

### Conclusion after measuring it

A native port has no 65C816 to be in lockstep with. The oracle keeps the SPC in
sync because it steps both CPUs together, so every port write lands at exactly
the right APU cycle; feeding a recorded stream to a continuously running APU
cannot reproduce that — the handshake is a feedback loop, and its timing is part
of the data.

So the in-process route needs one of:

1. **lockstep emulation of the 65C816** — out of scope for a native port;
2. **a richer state than `.spc`**, carrying per-voice envelope/decode state and
   the driver's own variables, so the driver can start from a state it accepts;
3. **pre-rendering**, which is what ships today and is verified.

The measurements above are the reason to stop pushing route 1 without (1) or
(2): it is not a matter of finding the right replay technique, it is a missing
input.

Two clean ways to get it, both small:

1. **Log the handshake state.** Extend the port ring's `cpu_wr` entries with the
   SPC's `outPorts[0..3]` at the moment of the write (about 20 lines across
   `audio_trace.h`, the record site and the `.apu.tsv` writer). The replay then
   waits for exactly the state the console had before each byte, instead of
   guessing which writes are paced.
2. **Read the driver's routine.** Disassemble `$046A` and the caller at `$02F9`
   in the captured ARAM and implement the transfer as code, which is the route
   `apu_host` would eventually ship anyway.

Until one of those lands, the port keeps the rendered assets, which are the
shipped path and are verified.

### A note on the oracle tree

The recomp checkout had a build-blocking mismatch unrelated to audio:
`src/dc_widescreen.c` calls `PpuSetWidescreenLayerRightEdge`, which the
snesrecomp submodule no longer provides (its neighbours survive as
`PpuSetWidescreenLayerClamp` etc.). To rebuild for the capture I put a four-line
no-op shim at the top of that file, marked `TEMPORARY BUILD SHIM`. It is the
user's in-progress widescreen work, so it should be replaced by the real call —
the shim only makes the file compile and disables that one policy.

## Still to do

1. **Route 1, step 2**: the handshake upload above. Until it works the rendered
   assets are the shipping path, and this is the difference between 5 MB per
   track and 64 KB of ARAM.
2. **SFX**: the seven event triggers still synthesise. On route 1 they come for
   free (same driver, same voices); until then, the capture-window approach or
   reading the BRR sample the driver keyed on are the options.
3. **A track per area**, not per game state: `src/game.c` currently picks
   `MUSIC_TITLE/STAGE/BOSS/ENDING`. `room_names.json` (34 maps) is the table to
   extend, with `music_tracks.json` gaining one entry per area that has its own
   theme. Capturing needs a save state in each area (312 exist in the oracle's
   `build-trace/saves/`).
4. **Format at campaign scale**: one 40 s WAV is 5 MB; 30 tracks would be
   ~150 MB. FLAC keeps the sample-exact loop and halves that; OGG is smaller but
   its encoder delay/padding makes a sample-exact loop harder. If route 1 lands,
   this question disappears.

### Raw material for the next step: the driver's routines

Captured from the frame-60 ARAM image. This is what has to be read and
re-implemented as the host side of the transfer.

`$02E0-$030F` — driver init / main loop

```
02E0: E8 40 C5 FA 00 E8 F1 C5 F1 00 E8 01 C4 B2 C5 F6
02F0: 00 9C C5 F7 00 9C FD DA DD 3F 6A 04 E5 FD 00 60
0300: 84 B1 C4 B1 F0 F3 8B B1 8D 02 E8 F9 6D 2D 60 98
```

`$0460-$048F` — port poll + transfer routine

```
0460: F2 5F A8 0A 2D 3D 5D 00 00 31 E5 F4 00 65 F4 00
0470: D0 F8 FD F0 17 2D AB B2 3F 8D 04 E8 31 C5 F1 00
0480: 00 00 00 E4 B2 C5 F6 00 AE C5 F7 00 6F 68 F0 90
```

`$0A00-$0A2F` — where the failed replay ended up. It decodes as code, not data
(`E4 A2` = `MOV A,$A2`, `3F 1F 0A` = `CALL $0A1F`, `3F DF 08` = `CALL $08DF`,
`2D` = `PUSH A`, `D4 00`/`D4 08` = `MOV $00+X,A`/`MOV $08+X,A`, `6F` = `RET`), so
the driver did branch into a real handler — this is the most likely entry of the
transfer routine and the place to start reading.

```
0A00: A0 E4 A2 3F 1F 0A 3F DF 08 2D 3F DF 08 D4 00 AE
0A10: D4 08 6F E8 02 60 94 00 D4 00 90 02 BB 08 6F C4
0A20: A0 F4 10 28 97 04 A0 D4 10 6F AE AE AE AE E3 B0
```

## The whole soundtrack (2026-11-07)

The single-track pipeline above generalised without changing its shape: capture
from the oracle's DSP ring, measure the loop, write a WAV.  What was missing was
two tables and a way to talk to the sound driver.

### Which room plays which song: read it out of APU RAM

Clustering captures by their spectrum does not separate the tracks — every song
uses the same BRR instruments, so chroma and band profiles of different songs
overlap (measured: 0.9+ similarity between unrelated tracks).  The song itself
is in APU RAM: diffing the ARAM of three saves that must share a track (the
cemetery rooms) against seven that must not showed two regions, `$0E00-$12FF`
and `$2D00-$2FFF`, that are identical inside one song and differ between songs.
`tools/audio/song_survey.py` sweeps every save state, loads it with `load_state`
(the APU half of a `.sav` restores even though the title's own resume chunk
does not) and hashes those regions.

Result: **216 saves group into 36 song signatures, and every room family falls
out cleanly** — Murkland, the ruined city, both Dark Forest songs, the towers,
both Poseidonia songs, both mountain songs, Phalanx's fortress, the demon's
hideout, the town rooms, the overworld and the boss themes.  `consts.AREA_MUSIC`
is that table (room area id -> `MusicTrack`), with the room's level letter as the
fallback for a room no save covered.

### The APU command protocol

`tools/audio/input_probe.py` found it by pressing one button at a time: the game
writes the three argument bytes to ports 1-3 and the command id to port 0.  Port
0 = `$01` is the jump.  `$F9` on port 0 is a poll (the game re-writes it while
waiting for the driver's acknowledgement on port 2) and not a command; `$CC`
starts an IPL data transfer, during which ports 0/1 carry index/data and 2/3 the
target address.  `tools/audio/apu_commands.py` decodes that stream.

### Sound effects: cancelling the music

Two runs from the same save state that differ only in the buttons pressed have
the same music, so subtracting them leaves the effect.  That silently does not
work at first: the emulator produces audio faster than a dummy device drains it,
so the output ring drops samples at wall-clock-dependent points and two
"identical" runs differ by ~1,900 LSB mean.  Pacing the emulation to real time
(`paced_run()` in `tools/audio/capture_sfx.py`) removes the drops — `audio_stats`
reports `dropped=0` and the two runs then compare **bit-identical** (0 LSB
residual over the pre-command window).  The captured difference is cut at each
decoded command, trimmed where the envelope falls below a tenth of its peak
(past that it is the music voice the driver stole) and peak-normalised.

`tools/audio/make_sfx_asset.py` maps the ids whose trigger is unambiguous into
`<assets>/audio/sfx_<name>.wav`.  Today that is the jump (`$01`).  Two more ids
were captured (`$07`, `$16` from a combat room) but their trigger is not proven,
so they are deliberately not wired in — guessing one into `SFX_HURT` would be
worse than the stand-in it replaced.

### Reproducing it

```sh
# 1. one capture per track (resumable; ~6 min each at 180 s)
python3 tools/audio/capture_tracks.py
python3 tools/audio/capture_tracks.py --only music_boss --force

# 2. cut the loops + write the manifest
python3 tools/audio/make_music_asset.py --use-capture

# 3. the effects (paced A/B runs, then the id -> name map)
python3 tools/audio/capture_sfx.py --all
python3 tools/audio/make_sfx_asset.py

# 4. verify
python3 tools/check_audio_assets.py --python .venv/Scripts/python.exe
```

On Windows the oracle's binary carries the `.exe` suffix, `load_state` needs the
snapshot converted to the L3 header (`tools/audio/oracle.py` does the launch and
the connect), and any path echoed back inside a JSON reply must be sent with
forward slashes.
