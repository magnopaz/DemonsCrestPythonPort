# Belth (`$68`) — a máquina lida da ROM

*Escrito a 2026-11-18. Leitura por `tools/disasm_range.py` (banco `$83`), bytes
confirmados por dump directo. A take da luta existe — §6.2 do `TAKES.md`
(`rec_stage2_trace`: 224 s na área 9, duas mortes) — e o ciclo medido entra em
§7 quando o replay do pool estiver processado. Sem este doc, a espécie era um
marcador magenta: 30 registos `unknown` (21 na área 9, 9 na área 35).*

---

## 1. Os registos e as flags

- Área 9 = **bone yard** (nível II, `room_names.json`: `ruined-city-boneyard`);
  área 35 tem os outros 9. A take do §6.2 morre duas vezes em (1905..1952, 332)
  e renasce no spawn 0 (48, 412) — a luta do Belth.
- Flags `$03` do registo, lidas em dois sítios:
  - estado 0, sub@0: `cmp #$04; bcc → $809E7F`; senão `and #$40; tsb $0A`
    — flags ≥ 4 com o bit `$40` marcam `$0A` (a captura injectada com
    `--flags 0x84` fazia a espécie desaparecer porque o init esperava o
    contexto da sala; os registos reais usam 0x82/0x84/0xF4);
  - estado 2, sub@0: `and #$03` — os bits 0–1 são a variante; `cmp #$02`
    compra um random extra; o bit 0 decide o deslocamento **-0x30/ +0x20**
    do ponto de teleporte.

## 2. Despacho — tabelas byte-indexadas (a lição)

```asm
83:B393  sep #$30
        ldx $05               ; estado
        ldx $05               ; estado — TAMBÉM byte-indexado
        jsr ($B3A3,X)         ; $05=0 → $B3A7 (peças), $05=2 → $B54E (controlador)
        lda $0C; bne rtl; jmp $80F83D   ; cauda comum
```

Estado 0 (`$B3A7`): `ldx $06; jmp ($B3AC,X)` — **X é o offset em bytes, não o
índice**. Os subestados escrevem-se como `{0, 2, 4, 6, 8, $0A, $0C}`:

| `$06` | endereço | papel |
|---|---|---|
| 0 | `$B3BA` | espera `$46` e faz o probe inicial |
| 2 | `$B401` | contagem `$39` → apagar ou passar a 4 |
| 4 | `$B41D` | perseguir: probes `$DF79/$DF7D`, distância ao alvo |
| 6 | `$B474` | **tabela de fases do ataque** (0..4) |
| 8 | `$B49D` | tabela própria @`$B4A2` (2 ramos) |
| $0A | `$B4D7` | tabela própria @`$B4DC` (2 ramos) |
| $0C | `$B520` | tabela própria @`$B525` (2 ramos) |

**Quem ler a tabela como índices 0..6 sem dobrar cai em alvos fora da janela
LoROM (`$83:04F0`, `$83:3E80`, `$83:75A0`) e conclui errado.** Os valores
`$06 = 8/$0A/$0C` aparecem por todo o lado (`$B7AC`, `$B71A`, `$B727`, …) e são
perfeitamente válidos porque a indexação é por byte. O controlador usa a
mesma convenção (`jsr ($B563,X)` em `$B54E`).

**Os estados também são byte-indexados** (confirmado ao vivo, §9): a
leitura estática inicial dizia "estado 1 → `$B54E`" por ler a tabela como
índices; o `jsr ($B3A3,X)` com X=`$05` só visita `$B3A7` (com `$05=0`) e
`$B54E` (com **`$05=2`**) — medido: os `$68` do trace usam `$05 ∈ {0,2}`,
nunca 1.

## 3. Estado 0 — as peças (chamas/servos)

- **sub@0 `$B3BA`**: `dec $46` enquanto conta; ao zerar: probe `$80A0FF(Y=$DF75)`;
  se spawn ok (`bcc`): `$06=2`, `$36=4`, `$80BD51(A=$28)`, som `$00`, `$47=1`,
  `$39=$20`, `$3C=$38=0`; depois a leitura de flags de §1.
- **sub@2 `$B401`**: `dec $39` → 0: se `$38 ≠ 0` → **apaga-se** (`$06=0`,
  `$0C=$80`, `$47=0`); senão `$06=4` + som `$16`.
- **sub@4 `$B41D`**: primeiro `$B70C` — se `$36==0` rearma o ciclo
  (`$46=$60`, `$B463`: `$06=2`, `$38=2`, som `$18`, `$39=$30`). Depois conta
  `$3C`; probe `$DF79`; comparação de distância em 16 bits
  (`$34 - 9` vs `$1034`): `bcs` → `$06=6` + som + `$3A=3` (ataque); senão →
  `$06=$0C`. Probe falha (`bcc` no `$DF7D`) → `$06=2`, `$38=2`, som `$18`,
  `$39=$30` (re-loop).
- **sub@6 `$B474`** — o padrão de ataque: `dec $3A` → 0: fase `$3B` 0..4,
  timer `$3A = $DF89[X]` (`0D 86 08 A9 10`), som `$DF8E[X]`, `inc $3B`.
  Na fase 5 → reset (`$3B=0`, `$3C=$20`), `$B412` (`$06=4`, som `$16`), cauda
  `$B7AC`.
- **sub@8 `$B49D`** (tabela `$B4A2`): ramo A `$B4A6`: `$3E=2`, som `$14`,
  `$3D=$78`, cauda `$B7FD`→`$B83F`; ramo B `$B4B6`: `dec $3D` → 0:
  `$3C=$50`, `$4C==0` → broadcast `$B7C8(1)`; senão walker `$B785` +
  `$B7FD`/`$B87C`.
- **sub@$0A `$B4D7`** (tabela `$B4DC`): ramo A `$B4E0`: fase nova
  `$3B = $DF9F[X]`, som `$DF9C[X]`, `$3A=8`; ramo B `$B4F9`: `dec $3A` →
  `dec $3B`; zero → `$06=8, $3E=0` (volta ao sub@8); senão som `$DF9C[X]`,
  `$3A=4`; cauda `$B785`+`$B7FD`→`$B83F`.
  *Nota de desconfiança:* os bytes em `$DF9C/$DF9F` leem-se como código
  (`86 0B A9 E8…`), ao contrário de `$DF89/$DF8E` (`0D 86 08 A9 10 00`
  como timers/sons é plausível). As bases podem ser outras ou a leitura
  estática engana-se — o replay (valores vivos de `$3B/$3A`) decide.
- **sub@$0C `$B520`** (tabela `$B525`): ramo A `$B529`: `$3E=2`, som `$04`,
  `$39=$1B`; ramo B `$B538`: `dec $39` → 0 → jmp `$B47E` (fecha o ciclo de
  fases); `$B88D`/`$B77E`; nalguma condição → `$06=8, $3E=0`.

## 4. Estado 2 — o controlador (o mago)

Dispatcher `$B54E` (`jsr ($B563,X)`, byte-indexado: 0/2/4/6/8/A/C →
`$B571 $B5D8 $B604 $B617 $B649 $B65F $B6DC`). Cauda: se o objecto referenciado
(`$38`) desapareceu → `$4A=1`.

- **sub@0 `$B571` — o teleporte**: `$3A=0`, `$3B=6`, `$3C=0`, `$06=2`,
  `$36=3`; random `$BC904B & $0F` → Y; flags bit0..1 == 2 → random extra;
  carry (bit 0) escolhe offset `-$30`/`+$20`; **`$31 = Y + offset + $46`**
  (16 bits); `$34 = $48 - $20`; **busca por colisão**: `$808C31` com
  `$23=8, $09=4`, repete até `$04` bit 2 — procura uma posição válida;
  depois `$23=1`… (o resto do bloco segue até `$B5D8`).
- **sub@2 `$B5D8`**: conta `$3A`; quando o referenciado entra em `$06==8`
  → `$06=4`, `$809E7F`, som `$1A`, `$3A=$25`; cauda `$B763` (allocator).
- **sub@4 `$B604`**: `dec $3A` → 0: som `$24`, `$06=6`, `$3A=$20`.
- **sub@6 `$B617`**: proximidade `$1031` vs `$31` (< 2 px); senão
  `$808C31+$808BED+$809E7F`; `$04` bits 0/1 → `$06=$0C, $3E=0`; senão
  `dec $3A` → 0: `$06=8, $3A=$14`; cauda `$B73E+$B76B+$B71A+$B727`.
- **sub@8 `$B649`**: `dec $3A` → 0: `$809E7F`, `$06=6`, som `$24`, `$3A=$20`.
- **sub@$0A `$B65F`**: tabela própria @`$B664` (por ler em detalhe).
- **sub@$0C `$B6DC`**: tabela @`$B6E1`: A `$B6E5`: `$3E=2`, som `$1C`,
  `$3A=$19`; B `$B6F4`: `dec $3A` → 0: se `$3C≠0` → allocator `$828777`;
  senão `$3A=$3C`, `$0C=$80` (desaparece), jmp `$B577` (re-arranque do
  sub@0).

## 5. Helpers partilhados

- **`$B7AC`** (cauda comum das peças): `$B88D`; carry → rts; `$B77E` (walker
  reset: `$40=0, $41=4`); **`$06 = 8` se `$3B==0`, senão `$0A`**;
  `$4C==0` → broadcast.
- **`$B7C8(A)**: varre os 26 slots ($1300..$1D00, stride $50) e põe
  **`$4C=1` em todos os slots com bits `$68`** — o "engajou" espalha-se a
  todas as peças da espécie na sala.
- **`$B7FD`**: homing em **X** — move o `$31` do objecto referenciado
  (via espelho `$1031`) para o próprio `$31` a **±3 px/frame com deadzone de
  4 px**; ainda cap `$1022 = -$40` (o vy do alvo).
- **`$B83F`**: homing em **Y** — alvo `$34 + $DFB3[$3B*2]` (offset 16-bit
  por fase), o mesmo ±3/deadzone 4. *Os bytes em `$DFB3` também leem-se
  como código — confirmar com o replay antes de portar o offset por fase.*
- **`$B785`/`$B77E`**: walker horizontal `$40/$41` (periodos 4/10 frames) —
  o meneio de flutuação.
- **`$B70C`**: se `$36==0` → `$46=$60` e re-loop (`$B463`).
- **`$B763`/`$B76B`**: chamadas ao allocator `$828777`.
- Por ler em detalhe: `$B88D`, `$B87C`, `$B727`, `$B73E`, `$B71A`, `$B412`,
  `$B7C8` completa, e os JSL `$80A0FF` (probe/spawn por id — os Y `$DF75/
  $DF79/$DF7D/$DF81/$DF85` são **índices de tabela, não ponteiros**),
  `$809E7F`, `$80BD51`, `$80F83D`, `$80F81D` (som), `$808C31/$808BED`
  (colisão, censo §4), `$BC904B` (random).

## 6. O port (2026-11-18, mesma sessão)

**Implementado em `dcpy/object.py`** (`_spawn_belth_piece`,
`_spawn_belth_controller`, `_belth_update`) e coberto pelo
**`tools/check_belth.py`** (na regressão):

- **Peças**: os 21 registos ancoram na sua posição de registo (todas as 21
  medidas na take), com o walker ±1 px do `$B785/$B77E`; auto-apagam num
  stagger por registo (ramo delete do sub@2), e o controlador re-spawna-as
  ao ritmo de ~90 frames com o tecto medido (sustentado 3–10, pico 12).
- **Controlador** (estado 2, nasce `(sub 0) → (sub 2, fase 6)` como medido):
  hp 32 do `bosses.py`; salta entre âncoras a cada ~400 frames (a cadência
  dos 7 slots da take); **arrasta o jogador** a ±3 px/frame com deadzone 4
  em janelas de ~120 frames por ciclo de 400 — o `$B7FD/$B83F` escreve nas
  fields `$31/$34` da **task do jogador** (`$1031/$1034`), medido como 7
  janelas de arrasto na take.
- **Kill**: no ramo genérico `hp <= 0` do `objects_check_projectiles`, como
  todos os bosses — e **apaga todas as peças no mesmo frame** (a take
  mostra o wipe simultâneo g11841→g11861, sem peças órfãs).
- **Hooks**: `DC_BOSS_HP/X/Y` funcionam no controlador (o checker usa-os
  para matá-lo com um tiro do demo 10); `DC_BOSS_CLEAR`/`DC_BOSS_DEFEATED`
  suprimem a luta para os checkers de navegação.

**Desvios documentados**: (a) o teleporte do controlador é em-place em vez
do delete+respawn multi-slot da ROM — o HP acumulado sobrevive no port
(na ROM deve viver fora do registo); (b) o stagger das peças usa as flags
do registo em vez dos probes `$80A0FF` (a dinâmica medida 3–12 é o alvo, a
regra fina dos probes fica por portar); (c) o arrasto em Y perde contra o
chão (o ROM cap `$1022=-0x40` sugere que puxa no ar) — o arrasto em X é o
mensurável e está coberto; (d) sons/tabelas por confirmar (`$DF8E`,
`$DF9C/$DF9F/$DFB3` sob suspeita) não tocam — o port não emite os sons
de fase ainda.

## 7. O ciclo medido — take §6.2 (replay determinístico do pool)

Replay com `trace_stage.py replay …_to_ruined-city-boneyard --step 30
--objects` (774 amostras). **Atenção à pasta**: dentro de
`rec_stage2_trace` há DUAS takes; a `stage_II_ruined-city-dark-avenue`
(so a avenida) não chega à área 9 — a certa é a que termina em
`…_reservoir_to_ruined-city-boneyard`. O replay entra na área 9 ao
g9571 (§6.2 diz 9581) e os `$68` aparecem do **g9661** até ao fim
(g23041).

- **Quantos**: 3–10 `$68` simultâneos, moda **7**, distribuídos por 16
  slots (8–23). Slots mais persistentes: 8, 15, 16.
- **Âncoras**: as **21 posições dos registos do `room_area9.json` são
  exactamente os pontos onde as peças estacionam** — todas as 21 foram
  observadas no trace; as posições fora dos registos (46 distintas no
  total, ~24 não-âncoras) são intermédias de perseguição, aglomeradas a
  poucos px dos ancoros (ex.: x 627–663, y 374 entre (612,367) e
  (682,367)) — consistente com o homing ±3 px e o walker do §5.
- **Mortes do jogador**: a série tem um vazio no slot 8 entre ~g13261 e
  ~g17701 — a primeira morte da take (§6.3: morte em g17681, RETRY no
  spawn 0) repõe o parque. A segunda morte é ~g22261.
- **Sem o kill**: esta take não mostra o Belth a morrer — o final da
  luta vem da take nova do utilizador (§8).

*Limitação do instrumento*: o blob do trace_stage traz
`slot:espécie@x,y` — sem `$05/$06`. Para o port fina vai querer-se
acrescentar `rec[5]/rec[6]` ao sample (2 bytes) e repetir o replay; a
estrutura de estados já está garantida pela ROM (§2–§5).

## 8. O kill — take do utilizador `rec_level_2` (2026-11-18)

Replay `--step 20 --objects` (746 amostras; a take entra na área 9 ao
g8361 vinda do reservoir). Os `$68` existem de **g8441 a g11841** — na
amostra seguinte (g11861) já não há **nenhum**:

- **a morte do boss apaga todas as peças de uma vez** — sem fade
  escalonado, sem peças órfãs a vaguear (consistente com o broadcast
  `$4C`/`$4A` do §5: as peças sabem que o controlador caiu);
- as últimas peças seguem **ancoradas nos registos** até ao fim
  (ex.: slot 12 em (1592,230), posição exacta de um registo; o jogador
  estava em (1861,332) — a luta terminou na direita da sala);
- o jogador **não morre** nesta take (estados 30/22 são
  hurt/transform; a morte é 16) — vitória limpa, e sai para o mapa
  (área 94) ao g14681;
- **3–12 peças simultâneas** (a §6.2 só chegava a 10) — 28 posições
  distintas, as 21 âncoras dos registos todas presentes outra vez.

### O que falta para portar (actualizado a 2026-11-18)

1. ~~Estados vivos~~ — **feito**, ver §9.
2. **Helpers por ler**: `$B88D`, `$B87C`, `$B727`, `$B73E`, `$B71A`,
   `$B412`, `$B7C8` completa, e os JSL `$80A0FF/$809E7F/$80BD51/$80F83D`
   (as bases `$DF9C/$DF9F/$DFB3` estão sob suspeita — §3/§5).
3. **Arte**: a captura injectada não desenha; precisa de captura na sala
   real (a take do §8 serve de guião) — depois entra no `build_assets.sh`.
4. **Checker**: entrar na área 9 → peças saem do placeholder e ancoram
   nos registos; contagem 3–12; homing ±3/4px; **kill apaga tudo de
   uma vez**; o jogador sai pelo mapa.

## 9. Estados vivos — o replay com `$05/$06/$3B` (2026-11-18)

O `trace_stage.py` ganhou o sufixo `#state.sub.phase` por slot (bytes vivos
`$05/$06/$3B` do registo; o prefixo `slot:sp@x,y` mantém-se compatível).
Repetido o replay da take do §8 (`rec_level_2`, passo 20):

- **Estados medidos: `$05 ∈ {0, 2}`** — 936 amostras de peças (estado 0),
  259 do controlador (estado 2), **nunca 1**: confirma a indexação por
  byte também nos estados (§2) e corrige a leitura estática inicial.
- **Subestados das peças: `{0: 746, 2: 372, 4: 45, 6: 17, 8: 12, C: 3}`**
  (amostras) — todos pares, tal como o §2 previu; o ciclo do slot 8 ao
  vivo: `0 → 2 → 4 → C → 4 → 2 → 0` e o ataque em `sub=6` com fases
  `$3B` 0..5 a rodar.
- **O controlador nasce `(sub 0, fase 0)` e passa a `(sub 2, fase 6)`**
  numa amostra — exactamente o arranque do `$B571` (`$3B=6`, `$06=2`) —
  e **vive em `(2, 6)` a luta inteira** (258/259 amostras). Fase 6 é
  exclusiva do controlador nas medições.
- **O teleporte do controlador é um re-spawn**: ao longo da luta ocupa
  **7 slots diferentes** (20, 21, 17, 18, 19, 16, 14), do primeiro
  (582, 367) ao último (1558, 247) — consistente com os ramos de apagar
  (`$0C=$80`) + allocator `$828777`; não há deslize, há morte/nascimento
  de instância.
- **Peças estacionadas dominam**: `(sub 0)` é 62% das amostras de peça —
  ancoradas nos registos, tal como §7/§8 mediram pelas posições.
