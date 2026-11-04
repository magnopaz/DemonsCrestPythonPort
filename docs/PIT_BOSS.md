# Poço de Ovununu (área 8) — medição do boss

*Primeira sessão do Passo C (2026-11-04). O que está aqui foi medido na take
`rec_stage2_trace/..._pit-of-ovununu` (`docs/TAKES.md` §6.1) e lido da ROM com
`tools/disasm_range.py` (recomp). Ainda não há implementação: este documento
fixa o que o port tem de reproduzir e o que falta medir.*

## 1. O que a take mostra

A arena é montada a partir dos registos que o `room_area8.json` já tem — não há
registo na boss table, e o `gate_next_area` da sala é `-1`:

| slot | espécie | registos | papel medido |
|---|---|---|---|
| 8 | `$69` (105) | 1 | fica fixo em (128,640), no fundo |
| 9 | `$6B` (107) | 1 | sobe atrás do jogador: y 700 → 550 → 471 → 397 → 339 → 252 → 212 |
| 10+ | `$6C` (108) | 11 | olhos que ziguezagueiam à volta do jogador |

O `$6C` tem 11 registos com `flags` 0..10 (o flag escolhe o olho). Os três
`$24` da avenida não têm nada a ver com isto. O jogador entra no poço em
(32,668) e a luta dura ~182 s na take.

O `$69` não é o `$16`: a entrada `$16` da boss table pertence à área 54. O poço
não a usa.

## 2. O que o port tem hoje

`room_area8.json` lista os 14 registos como `"unknown"`. Desde 2026-11-04 o
`objects_init` põe os três (`$69`/`$6B`/`$6C`) no pool como
`LEVEL_OBJECT_UNKNOWN` e o `render.py` desenha-os na posição viva (caixa
magenta). O `$69` liga `pool.pit_fight` pela condição medida; o `$6B` sobe
pela tabela de y da take; o `$6C` continua placeholder (11 olhos parados em
(128,640)). Não há `OBJECT_BOSS` na sala, por isso `boss_present` é falso e o
port ainda não “prende” o jogador na arena enquanto o boss estiver vivo.

A porta `8→10` da door table foi **removida**: o save chamava-se "ruined city
dark avenue before_door" (a avenida é a área 4), a tabela do ROM da área 8 não
tem `8→10`, e a caixa derivada caía em cima do spawn (32,668), expulsando o
jogador no frame 1. Sem ela a área 8 é jogável e a única saída é `8→7`
(pad_mask 8), como no ROM.

**Implementado nesta sessão:** o trigger do `$69` (`player.x < 128` ou
`player.y >= 568`), a subida do `$6B` pela tabela medida (700→209 em ~1350
frames + bob 187..216), os três no pool com render na posição viva, e
`tools/check_pit_boss.py` na regressão. **Falta:** a AI dos 11 `$6C`, o
dano/HP/morte do corpo, a arte e o “lock” da arena enquanto o boss está vivo.

## 3. Handlers (ROM)

| espécie | update | estados | tabela |
|---|---|---|---|
| `$69` | `$83:B96E` | 4 | por ler |
| `$6B` | `$83:BFDD` | 3 | `$83:BFF3` (3 ponteiros) |
| `$6C` | `$83:C7B2` | 4 | por ler |

O `$6B` foi o primeiro a ser decodificado porque é o corpo que sobe e o
comportamento está medido na take.

### `$6B` — tabela exterior (`$83:BFF3`)

```
estado 0 -> $83:BFF9    estado 1 -> $83:C198    estado 2 -> $83:C1C2
```

O estado 0 faz `ldx $06; jmp ($BFFE,X)`: `$06` é um **offset de bytes** na
tabela de sub-estados em `$83:BFFE` (8 entradas):

| offset | handler | o que faz (lido) |
|---|---|---|
| 0 | `$83:C00E` | espera `$1DEA` (flag de início da luta) ≠ 0; passa a offset 2 |
| 2 | `$83:C020` | contador `$3B`; com `$40 == 8` vai a offset 4; senão lê `$E203`→`$48` e `$E20B`→`$3B`, `inc $40` |
| 4 | `$83:C051` | `$3E` (16-bit) -= 1/frame; quando negativo → offset 6 |
| 6 | `$83:C073` | `$3E` += `$000E` (14)/frame até `$0160` (352) → offset 8; escreve `$1E01` e chama `$809D8E` |
| 8 | `$83:C0B0` | `$1DEF = 2`; `$3E` -= 10/frame; quando negativo → offset 10 |
| 10 | `$83:C0DF` | `$1DEF = 4`; `$3E` += `$0020` (32)/frame até `$02A0` (672); mexe em `$1DF0`/`$1DF2`/`$1DD0` |
| 12 | `$83:C145` | `$1DEF = 6`; `$3E` -= `$0030` (48)/frame |
| 14 | `$83:C15D` | `$1DEF = 6`; segue o jogador em X (`$33/$35` com passo ±$30/±$0C) até `$1DD1+$0C == $1DD7`; depois estado 1 |

Constantes já lidas: `$14` = 20 frames de espera; 8 passos na tabela; `$50` =
80 frames; `+14`/frame até `$160`; `-10`/frame; `+32`/frame até `$2A0`;
`-48`/frame; X de repouso `$0080`.

O estado 1 (`$83:C198`) chama `$809D8E`, `$C45C`, calcula
`$1DD1 + $0C - $1DD7` para `$34` e fixa `$31 = $0080`; o estado 2 (`$83:C1C2`)
ainda não foi lido.

## 4. O que a take mediu (fino, 2026-11-04)

Replay da take com leituras de WRAM em $E203 (16 bytes), $1DEA e do registo
do slot 9 a cada 100 frames (a área 8 começa em ~14200):

| frame | $1DEA | $6B x,y | $6B $05/$06 | nota |
|---|---|---|---|---|
| 14200 | 0 | (128,700) | 0/0 | entra na área |
| 14300 | **1** | (128,700) | 0/2 | $69 liga a luta |
| 14400 | 1 | (128,700) | 0/2 | $40=7 |
| 14500 | 1 | (128,687) | 0/6 | começa a subir |
| 14600 | 1 | (128,642) | 0/6 | |
| 14700 | 1 | (128,596) | 0/6 | |
| 14800 | 1 | (128,551) | 0/6 | |
| 14900 | 1 | (128,514) | 0/12 | |
| 15000 | 1 | (128,471) | 0/8 | |
| 15100 | 1 | (128,432) | 0/8 | |
| 15200 | 1 | (128,398) | 0/8 | |
| 15300 | 1 | (128,365) | 0/6 | |
| 15400 | 1 | (128,339) | 0/12 | |
| 15500 | 1 | (128,296) | 0/12 | |
| 15600 | 1 | (128,252) | 0/12 | |
| 15700 | 1 | (128,209) | 0/12 | topo |
| 15800 | 1 | (128,212) | **2/0** | passa ao estado 2 |
| 15900–16900 | 1 | y 187–216 | 2/0 | oscila (bob) |
| 17000 | **0** | (128,216) | 2/0 | a luta acaba |
| 17300 | 0 | (128,700) | 0/0 | o corpo volta ao fundo |

A subida leva ~1400 frames (23 s) de y=700 a y=209; depois o estado 2 oscila
entre ~187 e ~216. O `$69` liga `$1DEA` quando o jogador está em
`$1031 < 0x80` ou `$1034 >= 0x238` (x<128 ou y≥568), que é o caso ao entrar no
poço.

**Correcção da hipótese das tabelas:** `$E203`/`$E20B` são **constantes** na
luta (`15 04 15 05 15 26 15 27` / `15 00 15 01 15 22 15 23`); não são a tabela
de 8 passos da subida. O `$C020` lê-as para `$48`/`$3B` (provável índice de
animação/tempo), mas o movimento vertical vem dos estágios de `$3E` e do scroll
`$1DF0`/`$1DF2`, não delas. A sequência acima é a fonte para a implementação
enquanto o mapeamento de `$3E`→y não estiver feito.

## 5. O que falta medir (bloqueia a implementação fiel)

1. **Mapa `$3E` → y**: os estágios de `$3E` (`$C073` +14/frame até `$160`,
   `$C145` -48, `$C0B0` -10, `$C0DF` +32 até `$2A0`) e o scroll `$1DF0`/`$1DF2`
   movem o corpo, mas ainda não se sabe a relação exacta com o y do objecto.
   A tabela WRAM já foi despejada (é constante, ver §4); falta este mapa para
   reproduzir a subida pela ROM em vez de interpolar a take.
2. **`$1DD0`–`$1DF7`**: são os globais de objecto/scroll do motor (posição,
   OAM, câmara). É preciso mapeá-los para os campos do `Object` do port antes de
   transcrever `$C0DF`/`$C15D`.
3. **Helpers**: `$C3A7`, `$C3A4`, `$809D8E` (allocator? câmara? OAM?).
4. **HP/dano/morte**: a take mostra ~182 s de luta, mas ainda não se mediu
   quantos hits o corpo aguenta nem o que acontece quando morre (a sala não tem
   gate; o caminho de saída é 8→10 ou 8→7).
5. **Arte**: `$69`/`$6B`/`$6C` não têm sheet. A take tem os frames; é preciso
   `capture_boss_window.py`/`replay_capture.py` para os cozer.

## 6. Plano da próxima sessão

1. ~~Reproduzir a take com watch em `$E203`, `$E20B`, `$1DEA`, `$1DF0`~~ —
   feito: as tabelas são constantes e a sequência de y está em §4.
2. Fechar o mapa `$3E`/`$1DF0` → y do objecto (uma sessão de watch em
   `$1DF0`/`$1DF2` durante a subida).
3. Implementar `$69` (trigger `$1DEA`) e `$6B` (subida medida + estado 2 de
   bob); `$6C` como olhos (4 estados, `$83:C7B2`).
4. Cozer a arte da take e ligar o sheet.
5. `tools/check_pit_boss.py` na regressão: afirma a sequência de y medida, os
   11 olhos e o dano ao jogador.

## 6. Aceitação do Passo C (poço)

O boss aparece no poço, sobe pela sequência medida, os olhos voam e ferem o
jogador, o corpo pode ser morto e a sala deixa de estar “em luta”; checker
verde na regressão.
