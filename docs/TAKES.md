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

Falta só a **porta de ida**. Entrou pelo caminho pragmático em 2026-11-04:
`tools/dc_extract/apply_door_table.py` escreve as três transições medidas
(`source: "take_door"`, caixa 16×16, `pad_mask: 8`, spawn 0) e
`game_check_transitions` passou a exigir o botão. O caminho fiel (tipar os três
`$24` como controladores de porta) fica para o Passo 2 — o extractor ainda os
chama `pickup_crest`.

O dump de objectos da take (`trace_stage.py replay --objects`, passo 200)
confirma `room_area4.json` objecto a objecto (hex): `$57@360,232`, quatro
`$57` em 536/552/568/584, `$96@568,437` e os três `$24` em (424,420),
(664,420) e (824,116). Nenhum dos 11 registos extraídos falta nem sobra. É a prova de que a
área 4 está certa e de que `$24` é mesmo o controlador de porta.

## 6. As duas takes de rota completa (2026-11-04)

Ambas começam no boot (`gframe = frame + 1`) e são só input. Medidas com
`tools/oracle/scan_take.py` (duas leituras por amostra, passo 20).

### 6.1 `..._dark-avenue_to_..._pit-of-ovununu` — 25 076 frames (418 s)

| área | loader | frames | tempo | extensão |
|---|---|---|---|---|
| boot | 0 | 1–501 | 8,3 s | — |
| menu | 160 | 521–861 | 5,7 s | — |
| password | 164 | 881–3161 | 38,0 s | — |
| mapa | 188 | 3201–3681 | 8,0 s | — |
| dark avenue | **4** | 3701–4541 | 14,0 s | x 0–973, y 0–429 |
| reservoir | **5** | 4561–6521 | 32,7 s | x 35–1952 |
| catacombs | **6** | 6541–11001 | 74,3 s | x 45–1894, y 92–861 |
| darkened catacombs | **7** | 11021–14101 | 51,3 s | x 48–971, y 49–845 |
| pit of ovununu | **8** | 14121–25061 | 182,3 s | x 16–971, y 77–768 |

Portas: 4→5 em x≈1000 (o extractor tem `x=1008`), 5→6 em x≈1894 (fim da
sala 5), 6→7 em (424,845), 7→8 em (971,140). O encadeamento
`room_area{4→5→6→7→8}` do extractor bate certo com a take, sem portas em falta.

O log de input mostra o que dispara cada porta, e confirma o `pad_mask` da
`room_areaN.json`: 4→5 é só andar para a direita (`pad_mask 255`);
5→6, 6→7 e 7→8 são precedidas de um toque de **up** de um frame (`inputs=16`,
bit 0x10 na tabela do recomp) e as três têm `pad_mask: 8`. Ou seja `8` é o bit
de up do ROM e o port tem de o respeitar — hoje ignora `pad_mask` e transita por
proximidade (`dcpy/game.py::game_check_transitions`).

O poço (área 8) é a arena do boss de olhos: no frame 14600 vê-se a massa verde
com um olho central e pequenos olhos à volta, e no 17000 os olhos voam como
projécteis. **Não é a espécie `$16`**: o dump de objectos durante a luta mostra
a arena montada a partir das três espécies que o `room_area8.json` já lista:

| slot | espécie | comportamento medido |
|---|---|---|
| 8 | `$69` (105) | fica em (128,640), fixo no fundo |
| 9 | `$6B` (107) | sobe atrás do jogador: y 700 → 550 → 471 → 397 → 339 → 252 → 212 … |
| 10–20+ | `$6C` (108) | muitos, ziguezagueiam à volta do jogador (os olhos que voam) |

O `$6B` é o corpo/olho principal que persegue em Y; os `$6C` são os olhos
lançados. A tabela `BOSSES` do `tools/check_bosses.py` põe o `$16` na **área
54** (que no `room_area54.json` só tem as peças `$9B` inertes) — é outra
entrada, a reconciliar; o poço não a usa.

### 6.2 `..._dark-avenue_to_..._reservoir_to_..._boneyard` — 23 056 frames (384 s)

| área | loader | frames | tempo |
|---|---|---|---|
| dark avenue | **4** | 3961–5261 | 21,7 s |
| **black lotus** | **48** | 5281–6361 | 18,0 s |
| dark avenue | 4 | 6381–6821 | 7,3 s |
| black lotus | 48 | 6841–7441 | 10,0 s |
| dark avenue | 4 | 7461–7861 | 6,7 s |
| reservoir | 5 | 7881–9561 | 28,0 s |
| boneyard | **9** | 9581–23041 | 224,3 s |

A entrada no Black Lotus é em **x≈829, y=124** — a terceira porta up, que até
aqui só estava inferida por simetria com as outras duas. Fica confirmada.

### 6.3 Morrer devolve o jogador ao spawn 0 da mesma sala

Nas duas takes o jogador morre e volta ao **spawn 0 da mesma sala**, sem mudar
de área:

| take | morte | respawn |
|---|---|---|
| boneyard | (1905, 332) | (48, 412) em g22261 |
| boneyard | (1952, 332) | (48, 412) em g17681 |
| pit of ovununu | (161, 290) | (32, 668) em g17261 |
| pit of ovununu | (163, 562) | (32, 668) em ~g24650 |

O estado do jogador vai a `16` (sub 2/6) durante ~1–2 s e a seguir aparece um
**menu de continue** sobre a cena congelada (frame 22171 da take do cemitério):

```
  RETRY
  SELECT A STAGE
  END
```

com um cursor na primeira opção e `00000000` no canto superior esquerdo. O log
de input mostra `start` em g22153 e g22229 (a escolha) e depois `left`/`right`;
escolhido RETRY, o ecrã vai a preto (frame 22271) e o jogador reaparece no
**spawn 0 da mesma sala**, com a barra de vida cheia (frame 22331).

As três opções, confirmadas pelo utilizador:

| opção | destino |
|---|---|
| RETRY | recarrega a mesma sala no spawn 0, vida cheia (medido) |
| SELECT A STAGE | vai para o mapa em Mode 7 |
| END | mostra o ecrã `PASS WORD` (4×4, `PUSH START BUTTON`); o password gerado leva sempre ao mapa |

Ou seja: morrer não é game over nenhum — é o hub do jogo. O port tem isto
errado hoje: `Game_HandleDeath` (C e Python) só reinicia a área 0 e manda as
outras para um `GAME_OVER` inventado que espera ENTER e não tem caminho de volta
para a sala nem para o mapa.

