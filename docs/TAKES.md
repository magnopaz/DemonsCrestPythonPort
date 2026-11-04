# Capturas de jogo (takes) — como as ler e o que já provaram

*Escrito a 2026-11-03, a partir da take
`captures/rec_stage2_trace/stage_II_ruined-city-dark-avenue`.*

## 1. O que é uma take

O gravador do recomp escreve, com `SNESREC_AUTORECORD=1` (ou Alt+R), uma pasta:

```
<take>/
    input_log.jsonl     {"frame":N,"gframe":M,"inputs":mask} por frame
    frames/             BMPs por frame — vazio quando SNESREC_INPUT_ONLY=1
```

`frame` é o índice do input; `gframe` é o frame do guest. Numa take desde o
boot, `gframe = frame + 1`. **`frames/` vazio não é take inválida**: o log chega
para regenerar qualquer frame por replay.

Máscara do pad (tabela do próprio debug server, `k_controller_names` em
`snesrecomp/runner/src/debug_server.c`):

```
b 0x0001   y 0x0002   select 0x0004   start 0x0008
up 0x0010  down 0x0020  left 0x0040   right 0x0080
a 0x0100   x 0x0200   l 0x0400      r 0x0800
```

## 2. Reproduzir

```bash
# trilha de área/jogador/objectos
python3 tools/oracle/trace_stage.py replay <take> -o /tmp/t.csv --step 20 --objects

# frames de referência (PNG + VRAM + WRAM + PPU)
python3 tools/oracle/replay_capture.py --recording <take> --out /tmp/ref \
    --frames 900,4200,4700 --recomp ../DemonsCrestSNESRecomp \
    --rom "../roms/Demon's Crest (USA).sfc" --png
```

O `trace_stage.py replay` passou a escrever o replay em JSON **compacto** e a
falhar alto quando `replay_input` carrega 0 amostras (ver §4).

## 3. A take da avenida (medida)

10.509 frames (~175 s), desde o boot. Amostrada de 20 em 20 frames:

| frames | onde | notas |
|---|---|---|
| 1–501 | boot | |
| 521–921 | menu/título | `$008D` = 160 durante o menu |
| 941–3561 | password | 43,7 s; frame 3000 mostra o código a meio |
| 3621–4061 | mapa mundo | `$008D` = 188 |
| 4081–4601 | **avenida** | entrada em (64,428); cutscene state 28 |
| 4621–5821 | **biblioteca** | entra em (423,428), interior em (72,188) |
| 5841–8221 | avenida | volta em (424,428) |
| 8241–8881 | **wise man** | entra em (663,428) |
| 8901–10501 | avenida | x até 947; acaba em (946,428) |

Interiores visitados: biblioteca (velho encapuzado a ler) e wise man. O black
lotus não foi visitado.

## 4. Armadilhas (custaram tempo)

1. **`read_ram` leva endereço em hex e comprimento em DECIMAL.** `read_ram 1000 40`
   são 40 bytes (0x28), não 0x40. Pedir 0x40 «em hex» devolve um buffer curto e o
   fatiamento seguinte estoura com `IndexError`.
2. **Antes do primeiro frame não há WRAM:** ler `$1000` no frame 0 devolve
   `{"error":"out of range","max":"0x0"}`. Correr `run_to_frame 1` primeiro.
3. **O debug server lê o replay com `sscanf` e não aceita espaços** depois dos
   dois pontos. `json.dumps` sem `separators` produz linhas que o `sscanf`
   ignora em silêncio — `replay_input` responde `samples: 0` e o jogo fica sem
   input. É o que o `trace_stage.py` fazia antes desta sessão.
4. **Porta do debug server:** se um emulador anterior não morrer, o novo escreve
   `Debug server failed to bind port`. O cliente liga-se ao **antigo**. Matar
   com `kill -9` (SIGTERM é ignorado) e usar uma porta por corrida.
5. `get_frame_extended`/`dump_frame_vram` só servem frames no ring buffer —
   capturar ao vivo durante o replay, não no fim.

## 5. O que a take provou

### `$008D` é offset de bytes: área = `$008D / 2`

A take mostra `$008D` 8 → 92 → 8 → 94. Dividido por dois: **4 → 46 → 4 → 47**.
Confirmado nos dois sentidos:

- o port, com `DC_AREA=4 DC_START_X=64 DC_START_Y=428`, desenha *RUINED CITY
  DARK AVENUE* igual ao oracle no frame 4200;
- `DC_AREA=8` nas mesmas coordenadas desenha uma caverna com um ogre — sala
  errada;
- `assets/generated/room_names.json` já tem 4 = avenida, 46 = library,
  47 = wise_man, 48 = black_lotus (o port usa este ficheiro, portanto está bem);
- `docs/FullMaps/room_names.md` e `docs/INTERIOR_DOORS.md` ainda têm os valores
  **duplicados** (8/92/94/96). São docs estagnados, não código.

### A avenida não precisa de mapeamento level-space → chunk-space

`room_area4.json` é 1024×512 e a take anda em x 0–947, y 150–430 — o mesmo
espaço. A premissa antiga (`INTERIOR_DOORS.md`: «a avenida é um compósito; as
coordenadas do save chegam a x≈990 e o chunk extraído tem 256 px») vinha do id
errado (área 8 tem 256×768).

### As portas dos interiores: posição e o que falta

A sala 4 tem quatro spawns, todos usados pelo jogo:

| spawn | posição | porta |
|---|---|---|
| 0 | (64, 428) | entrada vinda do mapa |
| 1 | (424, 428) | → biblioteca (46) |
| 2 | (664, 428) | → wise man (47) |
| 3 | (824, 124) | → black lotus (48), no balcão superior |

A take confirma a ida: em (423,428) e (663,428) o jogador carrega **up**
(`inputs=0x10`) e a área muda. A volta já está no extractor: `room_area46`
transita para 4 com `spawn_id: 1`, `room_area47` com `spawn_id: 2` — e o
jogador reaparece exactamente em (424,428)/(664,428).

Falta só a **porta de ida**. Dois caminhos:

1. **Fiel**: os três registos de espécie `$24` em (424,420), (664,420) e
   (824,116) são os controladores dessas portas (3 registos, 1 área, 3 estados;
   update `$82:CA02`). O extractor tipa-os `pickup_crest` — tipo errado.
2. **Pragmático**: inserir três transições em `room_area4` com `pad_mask` de up.
   **Bloqueia** em `dcpy/game.py::game_check_transitions`: hoje o port ignora
   `pad_mask` e dispara por proximidade — sem `pad_mask` o jogador é
   teleportado ao passar ao lado da porta.
