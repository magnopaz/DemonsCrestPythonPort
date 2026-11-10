# Phalanx na câmara (área 42) — handler, tabelas e o que a take mede

*Escrito a 2026-11-10. A AI do port **não** é esta: `dcpy/object.py` tem um
drift + orbe inventado para o `$86`/`$8D`. Este documento existe para a
substituir com evidência.*

## 1. Registo e handler

- Duas salas têm o par `$86`/`$88`: **42** (`phalanxs-fortress-phalanxs-chamber`,
  a da take `rec_bad_ending`) e **75**. O registo do ROM da 42 está em
  **(256,136)** e o `$88` em (384,200).
- Handler do `$86`: **`BE:C6A0`** (censo de espécies). Despacha por `$03` (flags
  do registo), não por `$05`:

```
BE:C6A2  lda $03
BE:C6A4  cmp #$02
BE:C6A6  beq $C6BA        ; flags == 2 -> tabela $C6CC
BE:C6A8  ldx $05
BE:C6AA  jsr ($C692,X)    ; flags != 2 -> tabela $C692
...
BE:C6BA  ldx $05
BE:C6BC  jsr ($C6CC,X)
```

Depois de cada estado: `lda $3D / bne / jsl $80F83D / stz $3D` — o estado marca
`$3D` quando não quer que o helper `$80F83D` corra. O que `$80F83D` faz ainda
não está lido.

### Tabelas (6 estados cada)

| `$05` | flags != 2 (`$C692`) | flags == 2 (`$C6CC`) |
|---|---|---|
| 0 | `C82B` | `C6DB` |
| 1 | `C8DA` | `C729` |
| 2 | `C927` | `C76A` |
| 3 | `C95F` | `C786` |
| 4 | `C9CD` | `C7DB` |
| 5 | `CAAD` | `CA8A` |

O caminho da câmara é o **flags 0** (registos sem flag): `C82B`, `C8DA`,
`C927`, `C95F`, `C9CD`, `CAAD`. A take cobre ~70 s de luta (e uma morte), por
isso no máximo dois ou três destes estados chegam a correr.

## 2. O que a take mede

`tools/oracle/measure_phalanx.py` (passo 10, frames 3700–8100) lê o pool por
`read_ram` e despeja cada slot com espécie `$86`/`$88`:

```
python3 tools/oracle/measure_phalanx.py <take> -o /tmp/phalanx.csv \
    --from 3700 --to 8100 --step 10
```

**Corpo (`$86`, slot 8, 429 amostras, frames 3820–8100):**

| frames | posição | nota |
|---|---|---|
| 3820 | (256,136) | o registo do ROM |
| 3970–5170 | (480,136) | parado no canto direito alto |
| 5320 | (480,142) | começa a descer |
| 5470 | (336,173) | |
| 5620 | (249,205) | |
| 5770+ | y ≈ 171–175 | passa a varrer o x: 446→189→414→255→364→251→225→317→404→179→400→271→195 |

Ou seja: o corpo **não** fica em (256,136) — salta para (480,136), espera ~1200
frames e depois patrulha à altura do chão do jogador (y≈172) com varrimentos
horizontais grandes (100–200 px entre amostras de 150 frames).

**Enxame (`$88`, 17 slots):**

- slot 9: o registo do ROM em (384,200); `x` fixo em 384, `y` 198→326, some em
  5670.
- slots 10–18 (flags 1 ou `$80`): nascem todos em **4940–4950**, movem-se numa
  grelha (x 120..504, y 0..327) e morrem entre 5670 e 6020.
- slots 19–25 (flags 1): nascem em **4950** e **duram até ao fim** (8100), x
  120..504, y 1..327.

Nascer 17 objetos em 20 frames e ficarem 7 vivos é o que a AI do port não tem:
ele trata o `$86` como um corpo único com orbe.

## 3. O que falta

1. Transcrever `C82B`/`C8DA` (estado 0/1) e comparar com a posição medida; o
   estado 0 parece ser o "salta para (480,136) e espera".
2. Ler `$80F83D` (o helper chamado no fim de cada estado).
3. Identificar o que o `$88` é: os 17 slots nascem juntos e 7 ficam — pode ser o
   "enxame" que o jogador tem de destruir, ou peças do cenário animadas. A
   resposta está nos estados do `$88` (handler `BE:D77F`, 1 estado no censo).
4. Só depois: `$8D` (segunda forma), que o port cria na morte do `$86` mas cuja
   AI nunca foi lida.

Armadilha herdada: um `read_ram` com comprimento em decimal (ver
`docs/TAKES.md` §4) e o `run_to_frame` que anda ~2 frames por leitura em leituras
grandes.
