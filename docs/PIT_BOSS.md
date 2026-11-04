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

## 7. Os 11 olhos `$6C` medidos (2026-11-04, sessão 2)

Ferramenta nova: `tools/oracle/measure_pit_eyes.py` repete a take e despeja,
por amostra, os slots 8–25 (`$00` flags, `$02` espécie, `$05` estado, `$06`
subestado, x/y 8.8) e, com `--extra`, os globais `$1DD0..$1E08` e as tabelas
`$E2C0..$E300`/`$E380..$E3E0`. Duas corridas: 14100–25061 passo 10 (11 000
frames, 14 min — a luta corre a ~15 fps) e 14100–17350 passo 10 com globais.

### 7.1 Papéis e flags

O `room_area8.json` tem 11 registos `$6C` com `flags` 0..10. No pool:
slots 10–19 = satélites (`$00` passa a `$16`), slot 20 = **olho central**
(`$00` = `$12`). O central é o que fica no corpo: em todos os frames medidos
`x = $1DD3 + 1`, `y = $1DD5 + $1C` (confere ao pixel).

### 7.2 Ciclo medido da luta

`$1DEA` sobe em 14201 e a luta repete-se: 14181–17271, 17271–18861,
18861–20731, 20731–23241, 23241–24651 (reset = `$00` dos olhos volta a `1`,
`state 0 sub 0`, corpo a y=700). Só o **primeiro** ciclo corre a máquina de
lançamento; nos outros os satélites ficam em `sub 4`.

| evento | frame (take) | nota |
|---|---|---|
| `$1DEA = 1` | 14201 | satélites `sub 2` (parque), central `state 2` |
| `$1DF7 = 4` e corpo começa a subir | 14421 | satélites → `sub 4` |
| `$1DEF` cicla 0→2→4→6 | 14531+ | período ~200 frames, medido |
| corpo no topo | ~15750 | `$6B` `state 0 sub 12` → `state 2` (bob) |
| 1.º lançamento (`sub 6`) | 15791 (olho 0), 15821 (1), 15851 (7), 16651 (2) | |
| `sub 10`/`sub 12`/`sub 14` | 16141–16871 | só no ciclo 1 |
| `$1DEA = 0` | 17271 | reset da sala (o jogador morreu) |

Parque (14201–14420): x fixo por olho = 96, 104, 112, 115, 122, 136, 143, 153,
162, 166; y = corpo + (18, 8, 32, −3, 30, 18, 22, 14, 2, 32).

Em `sub 4` os olhos **seguem o corpo com atraso próprio** (o desvio cresce de
~20 px até 45–123 px no topo). O perfil por olho é uma rampa de velocidade
(pico 0,51–0,85 px/frame) que acelera/desacelera com o ciclo de `$1DEF`, e o
`cmp` de `+1/−1` px/frame de `$83:C8D5`/`$83:C8F4` puxa o olho para a banda
`$1DD5 − $D8 + $E2E1 ± $E2E3`.

### 7.3 A máquina de `$83:C7B2`

Estado 0 (`$06` por `$83:C7D3`, 8 entradas de 2 bytes, offsets 0..14):

| sub | handler | o que faz |
|---|---|---|
| 0 | `$C7E3` | init: `$06 = 2`, anim `$0C`, `$36 = 3`, `$0A = $20`, `$07 = 1` |
| 2 | `$C80E` | parque: `x = $E2DF,Y`, `y = $1DD5 − $D8 + $E2E1,Y ± $E2E3,Y`; `$1DF7 != 0` → sub 4 |
| 4 | `$C838` | enxame: `$38` 0/2 → `$C84F`/`$C864`; gravidade `$E2E5,Y`, acel `$E2E7,Y`; fase `$1DEF` escolhe `$C893`/`$C89D`/`$C8A7`/`$C8B1` (acelera ou trava, integra, puxa ±1 px); `$1DDE == 0` → sub 6 |
| 6 | `$C913` | lançamento: `$38` → `$83:C918` (10 entradas): `$C92C` (`$38=2`, `$3D=$3C`, `$49=4`, `$4F=$12`), `$C945` (anim `$18`, sonda `$D07C`), `$C963` (`$3D −= 6`), `$C996` (`$3D −= $25`, `< $40` → `$38=8`), `$C9B5` (sorteia `$3F` de `$E407`/`$E41D`), `$C9D4` (`$3D += 6` até `$150`, sonda `$809CA4`, `$D198`, `$809D8E`), `$CA2C`/`$CA45`/`$CA4E`/`$CA74` (volta) |
| 8..14 | `$CB6A`, `$CB7D`, `$CC00`, `$CAAE` | retorno/espera; `$CAAE` zera `$3D/$3E` e sorteia `$06` em `$E423` |

Subestados 6+ têm cauda partilhada: `jsr ($C7D3,X)` e depois `ldx $49;
jmp ($CCBF,X)` (`$49` 0/2/4 → `$CCC5`/`$CCD4`/`$CD13`).

Estado 2 (`$CD14`): `x = $1DD3 + 1`, `y = $1DD5 + $1C`, anim por `$E3CC[$1DD9]`;
sub-tabela `$CD4A`. Estados 4 (`$CDCE`, `$3B = $34` e depois
`jsl $828777` = despawn) e 6 (`$CE18`, spawna um `$6C` filho) **não ocorrem**
nos 11 000 frames medidos — ficam descodificados, não portados.

### 7.4 O que o port faz agora

- `$6B` espera 199 frames em y=700 (a tabela de §4 começa em 14400, a flag em
  14201) e só depois sobe — antes subia 200 frames cedo.
- `$6C` flags 0..9: parque no x medido, `sub 2` → `sub 4` aos 220 frames, e em
  `sub 4` o y = corpo + a **tabela de desvio medida** (passo de 20 frames,
  `_PIT_EYE_TRACK`). Comparado com a take: erro máximo 2 px em toda a subida.
- `$6C` flag 10: `state 2` preso ao corpo em (+1, +28).
- `check_pit_boss.py` passa a afirmar: o corpo ainda em 700 ao frame 200, a
  subida, o bob, o x de parque dos 10 satélites, o desvio ao corpo em t=600,
  1200 e 1500 (tolerância 4 px) e o olho central.

### 7.5 O que falta (por ordem)

1. **Tabelas `$E2D5/$E2DF/$E2E1/$E2E3/$E2E5/$E2E7`**: o handler faz
   `ldy $E2D5,X` (X = `$03`) e indexa `$E2E1,Y` etc. Em WRAM `$E2C0..$E300` só
   existe uma tabela de words `$15xx` (números de tile), pelo que o valor de
   `$03`/o banco de dados (DBR) ainda não está fechado — daí o port usar a
   take. Fechar isto substitui `_PIT_EYE_TRACK` pela regra do ROM.
2. **Lançamento (`sub 6`+)**: falta portar `$D0BE` (anim), `$D07C`/`$D198`
   (sondas/timers), `$809CA4` (probe rectangular), `$809D8E`, `$808C95`/
   `$808C99` (integradores) e `$BC904B` (RNG). É o que faz os olhos voar e
   ferir o jogador.
3. Dano/HP/morte do corpo, arte (`$69`/`$6B`/`$6C` sem sheet) e o lock da
   arena.
