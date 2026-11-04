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

`room_area8.json` lista os 14 registos como `"unknown"`: aparecem como
placeholders magenta e não têm AI. Não há `OBJECT_BOSS` na sala, por isso
`boss_present` é falso e as duas transições (`8→10` e `8→7`) funcionam — o que
também quer dizer que o port não tem como “prender” o jogador na arena
enquanto o boss estiver vivo.

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

## 4. O que falta medir (bloqueia a implementação fiel)

1. **Tabelas `$E203`/`$E20B`**: são WRAM, não ROM (o banco `$E2` não existe no
   cartucho). O init de outro sítio escreve os 8 alvos e os 8 tempos. Sem eles
   a subida tem de vir da take (y medido), não da ROM. Precisam de um
   `set_wram_watch`/dump durante a luta.
2. **`$1DD0`–`$1DF7`**: são os globais de objecto/scroll do motor (posição,
   OAM, câmara). É preciso mapeá-los para os campos do `Object` do port antes de
   transcrever `$C0DF`/`$C15D`.
3. **Helpers**: `$C3A7`, `$C3A4`, `$809D8E` (allocator? câmara? OAM?).
4. **HP/dano/morte**: a take mostra ~182 s de luta, mas ainda não se mediu
   quantos hits o corpo aguenta nem o que acontece quando morre (a sala não tem
   gate; o caminho de saída é 8→10 ou 8→7).
5. **Arte**: `$69`/`$6B`/`$6C` não têm sheet. A take tem os frames; é preciso
   `capture_boss_window.py`/`replay_capture.py` para os cozer.

## 5. Plano da próxima sessão

1. Reproduzir a take com watch em `$E203`, `$E20B`, `$1DEA`, `$1DF0` e dump das
   duas tabelas de 8 bytes.
2. Mapear `$1DD0`–`$1DF7` para o `Object` (provavelmente posição/OAM, não
   estado de AI).
3. Implementar `$6B` com a máquina acima; `$69` fixo como núcleo; `$6C` como
   olhos (4 estados, `$83:C7B2`).
4. Cozer a arte da take e ligar o sheet.
5. `tools/check_pit_boss.py` na regressão: afirma a sequência de y medida, os
   11 olhos e o dano ao jogador.

## 6. Aceitação do Passo C (poço)

O boss aparece no poço, sobe pela sequência medida, os olhos voam e ferem o
jogador, o corpo pode ser morto e a sala deixa de estar “em luta”; checker
verde na regressão.
