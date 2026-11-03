# Censo das espécies (Passo 2)

*Medido a 2026-11-03 com `python3 tools/species_census.py`. Este documento é o
mapa que faltava para o Passo 2: onde vive cada handler, quantos estados tem, que
helpers partilha e que arte já existe. Voltar a correr a ferramenta antes de
planear — ela lê o ROM, não estimativas.*

## 1. Como o ROM despacha uma espécie

Quatro tabelas de 192 entradas em bank `$82`, indexadas por `species * 2`:

| tabela | endereço | papel |
|---|---|---|
| update | `$82:8000` | chamada por frame (o handler principal) |
| secondary | `$82:8180` | variante/estado alternativo |
| init | `$82:8300` | chamada quando o objecto é alocado |
| aux | `$82:8480` | rotina auxiliar |

As entradas são quase todas stubs de 5 bytes `JSL $83:xxxx; RTS` (bank `$83`,
`$84`, `$85`, `$BC`, `$BE`…). Algumas apontam directo para código no bank `$82`
(`$10`, `$20`, `$06`, `$07`, `$09`, `$2C`, `$01`).

Cada update começa por `SEP #$30; LDX $05; JMP/JSR (tabela,X)`. O `$05` é um
**offset em bytes**, por isso os estados são `0, 2, 4, …`. A tabela fica no meio
do código (entre blocos de instruções), o que faz um desassemblador linear
descarrilar: é preciso ler os ponteiros primeiro e desassemblar cada handler a
partir do endereço certo.

`$9C` é a excepção medida: despacha primeiro em `$03` (modo) e só depois em `$05`.

`tools/species_census.py` resolve as quatro tabelas, lê a tabela de estados e
procura os helpers partilhados nos primeiros 320 bytes de cada update. Com
`--species 0x63 --disasm` desassembla os handlers de estado pelo
`disasm_range.py` do recomp.

## 2. O que existe hoje (medido)

80 espécies colocadas, 853 registos; 63 espécies sem handler no port (591
registos). Distribuição do número de estados entre as desconhecidas:

```
1 estado ....  8      4 estados ...  9      7 estados ...  2
2 estados ... 10      5 estados ... 11      9/10/11/13 ... 1 cada
3 estados ....  8      6 estados ...  6      16 estados ... 4
```

Quatro espécies aparecem com 16 estados porque a leitura da tabela passou do fim
para código seguinte; contam-se à mão ao portar.

## 3. As 20 mais comuns (ordem de registos)

| sp | registos | áreas | estados | arte | update | nota |
|---|---|---|---|---|---|---|
| `$50` | 41 | 4 | 10 | — | `$83:92DB` | máquina grande; `$28/$2E` apontam dados `$D9:7F/$D9:83` |
| `$9C` | 38 | 1 | 5 | — | `$85:C521` | despacha em `$03`, tabela real em `$C533` |
| `$63` | 35 | 5 | 3 | 1 pose | `$83:9FAA` | ogre; estado 0 com 2 subestados, estado 2 com sub-tabela `$A04C` |
| `$79` | 35 | 6 | 5 | — | `$83:E09B` | |
| `$68` | 30 | 2 | 2 | — | `$83:B393` | estado 0 com 7 subestados (`$B3AC`) |
| `$73` | 27 | 2 | 5 | — | `$83:DD06` | |
| `$71` | 26 | 3 | 5 | — | `$85:D243` | |
| `$9B` | 24 | 3 | 2 | — | `$84:CFE2` | sem movimento; só alterna `$0C` com o relógio global `$1DCE` |
| `$6C` | 22 | 2 | 4 | — | `$83:C7B2` | |
| `$65` | 22 | 3 | 5 | — | `$83:A727` | |
| `$20` | 18 | 3 | 10 | — | `$82:C1C8` | |
| `$B0` | 18 | 11 | 2 | — | `$85:CAD2` | tabela de `$03` em `$CADC` (`JSR` absoluto) |
| `$93` | 17 | 2 | 5 | — | `$85:BC93` | |
| `$12` | 17 | 2 | 5 | — | `$BE:9705` | |
| `$7D` | 16 | 3 | 6 | — | `$83:E43A` | |
| `$06` | 16 | 2 | 3 | — | `$82:93A4` | |
| `$70` | 14 | 2 | 1 | — | `$85:CF50` | tabela própria em `$CADC`-style; sem dispatch `$05` |
| `$72` | 13 | 1 | — | 5 poses | `$85:D4CF` | flame spirit; o caminho `$03 == 0` (`$D59A`) **gera clones** (`$82877B`, limite `$0E51 < $E98E`) |
| `$30` | 12 | 2 | 4 | — | `$83:823A` | |
| `$61` | 10 | 2 | 4 | 1 pose | `$83:9BFF` | |

## 4. Helpers partilhados (portar uma vez, usar em todas)

Encontrados por `species_census.py` nos updates das 20:

| helper | endereço | o que é (pelo uso) |
|---|---|---|
| probe rectangular | `$80:9CA4` | parece testar um ponto/rectângulo contra o cenário; recebe `Y = ptr` de parâmetros (ex. `$E982`) |
| colisão/movimento | `$80:8C31`, `$80:8BED`, `$80:8B9C`, `$80:8BA7` | usados antes de aplicar `vx/vy`; `$808C31` devolve carry |
| aim/direcção | `$80:9D8E`, `$809B53`, `$809FA2` | devolvem códigos pequenos (Arma usa `$809D8E`) |
| alloc/free | `$82:877B`, `$82:873D`, `$82:8777`, `$82:87E9` | criar/apagar objectos (o `$72` clona-se por aqui) |
| animação | `$80:F81D` (set), `$80:F83D` (advance) | ids de animação por espécie |
| random | `$BC:904B` | `AND #$0F`/`AND #$0E` conforme a espécie |

O port já reproduz o `$80:F81D/$F83D` de forma indirecta (timer de animação em
`dcpy/object.py`) e tem os helpers de chão/parede em `dcpy/level.py`
(`level_floor_at`, `level_is_wall_at`). O que falta é a camada de "probe com
rectângulo de parâmetros" e o allocator de filhos.

## 5. Arte: o que o oracle deu

`tools/oracle/capture_species.py` injecta a espécie em `save0` e grava OAM/VRAM.
Resultado desta sessão (`captures/species_top`):

| espécie | resultado |
|---|---|
| `$9B`, `$72`, `$61`, `$63`, `$68` | capturadas |
| `$50` | capturada mas **inútil**: o objecto foi para x=-98 e o OAM só tem o player |
| `$9C`, `$79`, `$73`, `$70`, `$30` | **connection reset** — o guest morre ao injectar (o init depende de estado que não existe fora do jogo) |

`tools/dc_extract/extract_species.py` cozeu: `$63` 1 pose, `$68` 1 pose,
`$61` 1 pose, `$72` 5 poses. Os PNGs e as entradas em `species_anim.json` são
locais (assets são git-ignored) e **não** são reproduzidos por
`build_assets.sh`; quando a espécie for portada, o passo de captura tem de entrar
no script.

## 6. Ordem proposta para portar

0. ~~`$72`~~ — **feito** como decor (chama de 5 frames, `check_flame.py`); ver
   `docs/FLAME_72.md`. O censo abaixo continua válido para o resto.
1. `$9B` (24 registos, 2 estados, sem movimento) — o mais barato: valida a
   infraestrutura de estados sem risco de combate.
2. `$68` (30, 2 estados) e `$B0` (18, 2 estados) — máquinas pequenas com
   tabelas próprias.
3. `$63` (35, 3 estados, arte pronta) — primeiro inimigo "de verdade".
4. `$06` (16, 3), `$30` (12, 4), `$61` (10, 4, arte pronta).
5. `$79`/`$73`/`$71`/`$65`/`$93`/`$12` (5 estados cada).
6. `$50`/`$20` (10 estados) e `$9C` (5) por último: são as máquinas maiores.

Cada espécie fecha com: handler transcrito em `dcpy/object.py`, arte no
`species_anim.json` (com passo de build), `SPECIES_KIND_MAP` actualizado (só
quando o comportamento existe) e `tools/check_<sp>.py` ligado ao
`run_regression.py`. O `check_objects.py` garante que o registo nunca desaparece
pelo caminho.

## 7. O que este documento não é

Não é um port. Nenhuma AI foi transcrita nesta sessão — o censo mediu o trabalho
e mostrou que a história de "20 espécies em 3–5 sessões" depende de portar
primeiro os helpers partilhados (§4); sem eles, cada espécie é uma máquina de
estados isolada. O primeiro alvo é o `$9B`, seguido do `$68`/`$B0`.
