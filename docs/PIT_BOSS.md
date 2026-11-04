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

1. ~~Tabelas `$E2D5/$E2DF/$E2E1/$E2E3/$E2E5/$E2E7`~~ — **resolvido**, ver §7.6.
2. ~~Lançamento (`sub 6`+)~~ — **portado**, ver §7.7/§7.8.
3. **Controlador de lançamento do `$69`** (`$B9F1`, §7.8): a rajada de 2–4
   olhos, `$1DDE`/`$1DE9`/`$1DF8` e as tabelas `$E015`/`$E075`. É o que
   substitui os quatro frames de lançamento medidos por uma regra.
4. **`sub 4` exacto** (banda + `$1DEE`/`$1DEF` + integradores): ainda com a
   tabela medida, erro ~25 px na regra pura (§7.6).
5. Dano/HP/morte do corpo, arte (`$69`/`$6B`/`$6C` sem sheet) e o lock da
   arena.

### 7.6 As tabelas dos olhos (resolvido, 2026-11-04 tarde)

**Banco de dados do update de objectos = `$81`.** Foi encontrado por tentativa:
para cada banco do ROM, aplicar a fórmula do handler com as posições medidas e
contar quantos dos 10 satélites batem. `$81` (e o seu espelho `$01`) dá
**10/10**; todos os outros dão 0. As leituras `$E2xx` do handler são deste
banco, não de WRAM — o que estava em `$7E:E2D5` era uma tabela de tiles `$15xx`
e enganou a sessão anterior.

O `$03` de cada slot é a **flag do registo** (0..10), lida do pool em 14451:
`slot 10 → $03=0`, `11 → 1`, …, `19 → 9`, `20 → $0A`. Portanto
`ldy $E2D5,X` = byte em `$81:E2D5+X`, e os bytes são 0, 12, 24, … 108 (o stride
de 12 bytes).

Registo por satélite em `$81:E2DF + 12·flag`:

| campo | endereço | significado |
|---|---|---|
| x | `$E2DF,Y` | x de parque |
| A | `$E2E1,Y` | offset base do y |
| B | `$E2E3,Y` | meia-largura da banda |
| C | `$E2E5,Y` | tecto da velocidade (`$26`) |
| D | `$E2E7,Y` | passo de aceleração (`$24`) |

Com `base = $1DD5 - $D8` (216): parque `y = base + A + B`, banda
`[base + A - B, base + A + B]`, e o `+1/−1` px/frame de `$C8D5`/`$C8F4` puxa o
olho para dentro dela. Os dez pares (x, y) saem 10/10 iguais aos medidos:

```
(96,226,8,52,1) (104,208,16,88,2) (112,216,32,128,3) (115,205,8,48,1)
(122,236,10,40,1) (136,220,14,80,2) (143,206,32,112,3) (153,220,10,80,2)
(162,212,6,51,1) (166,216,32,88,3)
```

O port já usa esta tabela (`_PIT_EYE_ROWS`) para o parque e para o x.

Tabelas do lançamento, todas no mesmo banco:

| tabela | conteúdo |
|---|---|
| `$81:E357` | 0, 48, 95, 143, 181, 212, 235, 251 — velocidade por passo de animação |
| `$81:E360` | 16 bytes — `$09` (frente) por id de animação |
| `$81:E364` | 16 bytes — frame de animação por passo (`$CFBF`) |
| `$81:E407` | 16 bytes (0,0,0,0,0,0,2,2,4,4,4,4,2,2,2,2) — índice em `$E41D`/`$E41E` |
| `$81:E41D`/`$E41E` | valores para `$47`/`$48` (timer de retorno e desvio) |
| `$81:E423` | 16 valores (8..12) — `$06` de regresso (`$CA9D`) |

**Ainda não fecha**: a regra do `sub 4` com esta tabela (banda + velocidade)
reproduz o y de cada olho com erro máximo de **~25 px** (o `_PIT_EYE_TRACK`
medido dá 2 px). Faltam duas coisas para fechar: `$1DEE` (muda de valor durante
a luta e o handler zera `$22`/`$23` quando muda — ler a 1 frame) e o
`$808C95`/`$808C99` exacto por fase. Um replay a passo 1 em 14421–15791 (~10
min) deve chegar lá; depois `_PIT_EYE_TRACK` desaparece.

### 7.7 A máquina de lançamento descodificada (portada, 2026-11-04 noite)

*Nota: as secções 7.7/7.8 descrevem o que ficou portado em `dcpy/object.py`
(`_pit_eye_state6`, `_pit_eye_state10/12/14`, `_pit_launch_probe` e os
auxiliares `$D0BE`/`$CFDF`/`$CF6E`/`$809D8E`/`$D137`/`$809CA4`/`$BC904B`) e o
que continua medido em vez de derivado.*

**Gatilho.** `$1DDE` vale 9 durante o enxame e passa a **0 em 15791** — é isso
que faz cada satélite sair do `sub 4` para o `sub 6` (`$C83D: lda $1DDE; bne`).
`$1DE9` conta os que já saíram (1 em 15791, 2 em 15821, 3 em 15851, 4 em 16651):
os olhos lançam **um de cada vez**, pela ordem das flags. `$1DEE` alterna 4↔8
durante a luta e o handler zera `$22`/`$23` quando muda.

**Subestados** (`$38`, tabela `$83:C918`, 10 entradas de 2 bytes):

| `$38` | handler | o que faz |
|---|---|---|
| 0 | `$C92C` | `$38=2`, `$4F=$12`, `$3D=$3C`, `$3E=0`, `$49=4`, `$4D=0`, `$3C=$0C` |
| 2 | `$C945` | anim `$18`; sonda vertical `$D07C($1C)`; se acertar → `$38=4` e cria um `$6D` (`$82877B`) |
| 4 | `$C963` | `$3D -= 6`; se negativo → `$38=6`, `$39=0`, sorteio `$E407[x]`, `$3D = $E417[$E407[x]]` (0x400/0x580/0x300), `$42++`, `$37=$18`; senão anim `$18` |
| 6 | `$C996` | `$3D -= $25`; quando `< $40` → `$38=8`, `$0A=$30` |
| 8 | `$C9B5` | `$38=10`, `$3A=0`, sorteio → `$47=$E41D[y]`, `$48=$E41E[y]`, `$44=$40` |
| 10 | `$C9D4` | `$3D += 6` até `$150` → `$38=12`; `$44` conta; sonda `$809CA4($E2C0)`; sem toque → `$38=16`; `$D198`; `$809D8E` |
| 12 | `$CA2C` | `$3D -= 7`; se `>= $B8` → corpo do 10; senão `$38=14`, `$3B=$10` |
| 14 | `$CA45` | `$3B -= 1`; a 0 → `$38=10` |
| 16 | `$CA4E` | `$3D -= 8`; se negativo → `$38=18`, `$3B=8`, `$3D=$3F`, `$3E=sorteio`; senão `$CA04` |
| 18 | `$CA74` | `$3B -= 1`; de 8 em 8 avança `$3F` (`$CFBF`); quando `$3F == $3D` → `$3D=$3E=0`, sorteio `$E423[x]` → `$06`, `$38=0` |

**Movimento** (`$CA08`, chamado pelos subestados 2/4/10/12/16):

```
$43 = A (id de animação)
jsr $CFDF                       ; passo de animação ($4F/$3A/$3C)
se $4D == 0:
    $0000/$0001 = $3D/$3E       ; escala
    jsr $D0BE($3C*2)            ; $09 = $E360[A>>3]; e a multiplicação:
                                ;   $20 = $E357[Y] * escala >> 8
                                ;   $22 = $E357[X] * escala >> 8
    jsl $808C77                 ; x += $20 pela frente em $09 (bits 0-1)
    jsl $808C8B                 ; y += $22 pela frente em $09 (bits 2-3)
jmp $CF6E                       ; sub-dispatch em $40
```

`$D0FF` é a multiplicação por hardware (`$4202/$4203`): `resultado =
$E357[i] * $3D/$3E`, e o resultado volta como word (o handler guarda a metade
alta). `$E357` = 0, 48, 95, 143, 181, 212, 235, 251; `$E360` diz a direcção;
`$E364` o frame de animação. Ou seja: **a velocidade do voo é
`speed[passo] × $3D >> 8`** e `$3D` é a rampa (desce no mergulho, sobe na
subida).

**Cauda partilhada** (subestados >= 6): depois do handler corre
`ldx $49; jmp ($CCBF,X)` — `$49` 0/2/4 → `$CCC5` (arma `$49/$4D/$4A/$4B`),
`$CCD4` (`$4A -= $19`; se negativo `$4D=0`, `$49=4`; senão `$0000 = $4A>>2`,
anim `$4C`, `jsl $808C77/$808C8B`) e `$CD13` (`rts`).

**RNG**: `$BC904B` — LCG de 16 bits em `$009C/$009D`:
`r = (3*seed >> 8) & $FF; seed = (seed + r) & $FF; return r`.

Com isto falta só escrever os dez subestados no port e verificar o voo dos
quatro olhos que lançam ([0] 15791, [1] 15821, [7] 15851, [2] 16651). A arte
continua por cozer, por isso o voo verifica-se por posição, não por imagem.

### 7.8 O lançamento portado: o que a take ainda ensinou (2026-11-04 noite)

O `$1DDE` **é indexado por flag** (`$C83D: ldx $03; lda $1DDE,X`): não é um
contador global, é o "estacionado" de cada olho — 9/1 = no parque, 0 = lançado.
Quem o desce é o controlador do `$69` (`$B9F1`, tabela `$B9F6` em `$40`):

| `$40` | o que faz |
|---|---|
| 0 | `$3F = $81:E075[$40 + RNG&$0F]` (2..4, tamanho da rajada); `$40=2`, `$3E=$20` |
| 2 | espera `$3E`; `Y = $81:E015[RNG&$1F]`; procura o primeiro `$1DDE[Y] != 0` (10 tentativas, `Y++ mod 10`); achando: `$1DDE[Y]=0`, `$1DE9++`, `$3E=$20`, `$3F--`; `$3F` a 0 ou nenhum estacionado: `$40=4`, `$3E=$80` |
| 4 | espera `$3E`, volta a `$40=0` |

`$1DF8 == 10` é o gate do "nenhum estacionado" (`$BA4E`), que na janela medida
nunca se aplica. Na take o RNG deu uma rajada de **4**; `$1DE9` conta 1/2/3/4
em 15791/15821/15851/16651. O controlador **não está portado**: os quatro
frames ficam medidos em `_PIT_EYE_LAUNCH` (1590/1620/1650/2450 = take−14201).

Os sorteios dos quatro olhos também ficaram medidos (lidos do slot cru:
`$3D/$3E`, `$47/$48`, `$06` de regresso), porque a semente `$009C` em 14201
não foi lida e o controlador do `$69` também consome o LCG:

| flag | `$3D/$3E` | `$47/$48` | reinício `$06` |
|---|---|---|---|
| 0 | `$0400` | 620 | 10 |
| 1 | `$0300` | 620 | 12 |
| 7 | `$0580` | 364 | 10 |
| 2 | `$0580` | 620 | (a take reinicia antes) |

**Sondas.** `$D07C(A)` compara o y do olho com
`$1DD1 - $1DCE - 8 - $DFCE[|x-$40|] + A` (`$DFCE` é `$81:DFCE`, uma rampa
0..29 dobrada em `$40`); carry = chegou. `$1DD1` satura em **188** de 15711 até
ao fim da luta e `$1DCE` é o scroll (não simulado pelo port), por isso a linha
ficou medida por olho: `_PIT_EYE_REACH` = 206/179/181/191 (y em que o `sub 2`
passa a `sub 4`). `$D137(A)` é `dist² >= A²` (carry = fora) e `$809CA4($E2C0)`
é a caixa ±`$40`/±`$28` à volta do olho. `$D198` faz o timer `$47` de 16 bits
chegar a 0 → `$06=14`; `$D1AE` só decrementa.

**Regresso** (não estava na §7.7): `$06=8` (`$CB6A`: `$44=$C0`, `$3D=0`,
`$38=$0A`, `$06=6`); `$06=10` (`$CB7D`, `$38` 0/2/4/6: aponta 0x20 frames e
depois voa na direcção `$43` com `$3D += 7` até `$200`); `$06=12` (`$CC00`:
`$3D` oscila `$100..$1C0`, `$CC82` roda o código ±8 e ±`$4E`, `$D137($60)` ou
`$44` esgotado → `$38=6`); `$06=14` (`$CAAE`: abranda, espera, voa para o
parque com `$3D=$120` e, quando `0 <= x+4-park_x < 8` e
`0 <= park_y+4-y < 8`, volta a `$06=4`, `$1DDE=1`).

**Verificação (`tools/oracle/measure_pit_eyes.py`, janela 15700–17000).**
Antes da rampa o port segue a take quase à letra: no frame de lançamento e 100
frames depois o erro é 0,7 px (flag 1), 2,2 (7), 2,9 (2) e −5,5 (0, porque a
tabela do enxame satura em t=1580). A partir da rampa o voo da take é puxado
pelo jogador (que anda em ~(220,200)); com o jogador parado no spawn o port
mergulha mais cedo e um olho fica a pairar. Com
`DC_HOLD_PLAYER=210,200` os quatro sobem e voltam:

| flag | parque → mínimo → regresso |
|---|---|
| 0 | 253 → 139 → 261 |
| 1 | 207 → 143 → 221 |
| 7 | 208 → 71 → 227 |
| 2 | 243 → 81 → 225 (re-parqueia em 3853) |

`tools/check_pit_boss.py` passou a `FRAMES = 4000` e afirma, por olho lançado:
`$06=6` no frame de lançamento, subida ≥ 40 px e descida ≥ 50 px depois do
pico. O jogador é fixado com o hook novo `DC_HOLD_PLAYER` (o mesmo sítio da
take); sem ele a luta não é a mesma e o flag 1 não fecha o ciclo.
