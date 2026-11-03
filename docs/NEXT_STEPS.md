# Próximos passos para terminar o jogo

*Escrito a 2026-11-03, no fim da sessão que fechou o Arma → Earth Crest →
área 94 e o mapa em Mode 7. Números medidos nessa sessão com
`python3 tools/report_coverage.py` — voltar a correr esse comando antes de
planear, porque é ele que diz quanto falta de verdade.*

---

## 0. Antes de tocar em código

- **`HEAD` é `c666823` e a árvore está suja**: 11 ficheiros modificados + 7
  novos (`dcpy/mode7.py`, `docs/ARMA_AI.md`, `tools/check_arma.py`,
  `tools/check_map_mode7.py`, `tools/dc_extract/apply_gate_table.py`,
  `tools/report_coverage.py`, `docs/NEXT_STEPS.md`). Nada
  disto está commitado. Primeiro passo da próxima sessão: rever e commitar o
  que está verificado (`python3 tools/run_regression.py` → PASS), senão o
  trabalho do Arma/mapa perde-se num `git checkout`.
- Verde de referência: `DISPLAY=:99 python3 tools/run_regression.py` (Xvfb em
  `:99`; sem ele os demos falham com "X11: Failed to open display").
- Checkers do milestone: `tools/check_arma.py`, `tools/check_map_mode7.py`,
  `tools/check_bosses.py`, `tools/check_campaign.py`.

## 1. Onde o jogo está (medido, não estimado)

```
rooms extracted ............ 113  {'playable': 69, 'partial': 44, 'empty': 0}
rooms with objects ......... 55
objects placed in JSON ..... 269  (25 species)
objects listed in the ROM .. 853  (80 species, 90 areas)
typed by the extractor ..... 262  (17 species)
DROPPED .................... 591  (63 species)
  top 20 of those cover .... 451 records (76% of the gap)
  most common dropped ...... $50x41, $9Cx38, $63x35, $79x35, $68x30, $73x27,
                             $71x26, $9Bx24, $6Cx22, $65x22
rooms with a BG2 tilemap ... 65/113
species sprite sheets ...... 28
music tracks ............... 1
```

A leitura dura: **68% dos objectos que o original coloca nunca chegam ao
port**, porque `SPECIES_KIND_MAP` (em `tools/dc_extract/extract.py`, 17
entradas) descarta tudo o que não conhece. O jogo *parece* completo numa
captura de ecrã e está vazio por dentro.

---

## 2. A fila, por ordem de dependência

### Passo 1 — Parar de descartar objectos (1 sessão) — **fazer primeiro**

Não vale a pena portar handlers enquanto o extractor os deita fora: não se
consegue medir o progresso nem detectar regressões.

- `tools/dc_extract/extract.py`: dar um `kind` a **todas** as espécies; as
  desconhecidas ficam `"unknown"` em vez de serem saltadas. O `type` já é lido
  no `room JSON`; o port tem de tolerar `"unknown"` e desenhar um placeholder
  até haver handler/arte.
- `tools/audit_campaign.py` + `tools/report_coverage.py`: o número que interessa
  é "objectos colocados / 853", não "salas jogáveis".
- **Aceitação**: soma dos `objects` nos 113 JSON == 853; `run_regression.py`
  continua PASS; uma sala com espécie desconhecida carrega e desenha o
  placeholder em vez de rebentar.

### Passo 2 — As 20 espécies mais comuns (3–5 sessões)

Cobrem **451 dos 591** registos em falta. Ordem por frequência:
`$50`(41), `$9C`(38), `$63`(35), `$79`(35), `$68`(30), `$73`(27), `$71`(26),
`$9B`(24), `$6C`(22), `$65`(22), `$20`(18), `$B0`(18), `$93`(17), `$12`(17),
`$7D`(16), `$06`(16), `$70`(14), `$72`(13), `$30`(12), `$61`(10).

Método já provado duas vezes (ghoul `$67`, Arma `$A5`):

1. `tools/oracle/trace_stage.py save <sav>` ou `replay <take>` para ver a
   espécie em movimento; `probe_slot_record.py --slot N` para o registo cru.
2. `set_wram_watch` no campo de estado para apanhar os blocos que escrevem (foi
   assim que saiu a tabela `BE:E731` do Arma).
3. `tools/disasm_range.py` no handler → transcrever para `dcpy/object.py`.
4. `tools/capture_species.py` para o sheet + `dcpy/species_anim` para as
   sequências.
5. Um `tools/check_<specie>.py` que falha se a AI divergir (o `check_arma.py` é
   o modelo), ligado ao `run_regression.py`.

**Aceitação por espécie**: aparece, anda, ataca com o mesmo ciclo, pode ser
morto, larga o que o original larga; checker verde.

### Passo 3 — Gerador de BG2 em runtime (1–2 sessões)

Hoje só as áreas 1 e 3 têm fundo real (bakeado de capturas). 65/113 salas têm
tilemap de BG2 mas o resto depende de capturas — e as salas sem captura ficam
escuras.

- Decodificar `$84:A057` (DMA do tilemap a partir de `$7F`) e o streaming de CHR
  `$80:BFB5`/`$80:C11B`.
- **Aceitação**: uma sala sem captura desenha o mesmo BG2 que o oracle, lado a
  lado, sem PNG pré-cozinhado; `build_assets.sh` deixa de precisar do
  `bg2_captures.json` para essas salas.

### Passo 4 — Restantes bosses (1 sessão cada)

12 salas com boss na tabela. Feitos: Hippogriff (`$09`), Somulo (`$33`), Arma
(`$A5`, com 16/18/20/22 em falta). Faltam: Scula (`$7B`/`$7C`), Phalanx
(`$86`/`$8D` — segunda forma), Holothurion, Ovnunu, Grewon, Dark Demon, Flame
Lord, `$16`, `$58`, `$6F`, `$82`, `$BC`.

Para cada um: mesma receita do Arma; o que muda é a tabela de despacho e as
constantes. `docs/ARMA_AI.md` serve de molde de documentação (handler, tabela,
estados, constantes, ciclo medido, o que ficou por fazer).

### Passo 5 — História, menus e apresentação

- Intro/coliseu, os quatro endings, créditos e o subscreen retail com o motor de
  texto que já existe (`game_text`/`script`), hoje a funcionar só em parte.
- NPCs de cidade com diálogo completo (`$96` está colocado numa sala só).
- Password retail: algoritmo por descobrir. Codec nativo funciona; o vector
  `QFFF KNRR DDLR XGTQ` é o alvo para o inverter.
- Minijogo do headbutt (arena do coliseu).

### Passo 6 — Áudio

- 1 faixa (`music_boss.wav`). A rota "correr o driver SPC700 in-process" está
  **fechada por medição** (`docs/AUDIO_PLAN.md`): sem um 65C816 em lockstep, o
  handshake IPL não se reproduz. Não repetir a experiência.
- Caminho realista: (a) extrair BRR/SFX individualmente e tocar samples, ou
  (b) banda sonora de substituição, uma faixa por área/boss/menu.
- **Aceitação**: todas as salas com música, sem cortes no loop, volume
  coerente; `check_audio.py` cobre duração/seam como hoje.

### Passo 7 — Release

- CI (regressão + audit + screenshots), build macOS, perf (target 60 fps em
  máquina modesta), packaging com extracção do ROM do utilizador.
- **Legal**: nada de assets derivados no repo — o extractor corre na máquina de
  quem tem a ROM.
- **Definição de completo** (do `FULL_CAMPAIGN_PLAN.md`): arranque a frio →
  título → new game → coliseu → cemitério → mapa → todas as fases, lojas e
  bosses → todos os endings, **sem hooks de desenvolvimento**; e um
  `ROM → extractor → assets` limpo que produza o jogo inteiro sem dados manuais.

---

## 3. O que ficou solto desta sessão

Nada disto bloqueia; está aqui para não se perder.

- **Arma**: estados 16/18/20/22, o chooser `$809D8E` (`BE:ED13`), os spawns
  `$A6`/`$A7`/`$A8` e o drop visual do crest. A cadeia medida e a pergunta em
  aberto do `$1DCE` estão em `docs/ARMA_AI.md`.
- **Spawn da área 3**: o registo do ROM é mesmo (64,1180) (`40 00 9c 04`), mas o
  save tem o jogador em (681,156) com câmara 0 — os spawns não são coordenadas
  de mundo iguais às dos objectos. Entrar na área 3 pelo caminho normal cai no
  fundo do abismo; o combate verifica-se com `DC_START_X/Y`.
- **Mapa**: rotação do plano (a referência não roda), a "smear" do horizonte pelo
  clamp de profundidade, e a interacção — os nós são projectados mas o pouso
  ainda usa a lista antiga de nós.
- **14 chamas `$72` da área 1** continuam descartadas pelo extractor (entram no
  Passo 1).

---

## 4. Como trabalhar (o que funcionou)

1. **Medir antes de planear**: `tools/report_coverage.py`, `audit_campaign.py`,
   `trace_stage.py`. Nada de estimativas.
2. **ROM primeiro**: disassemble/observar o oracle, depois escrever o port. Sempre
   que se "adivinhou", voltou-se atrás.
3. **Um checker por feature**, ligado ao `run_regression.py` no mesmo commit. Os
   checkers antigos também envelhecem: nesta sessão dois deles
   (`check_bosses`, `check_campaign`) assumiam comportamento errado e tiveram de
   ser corrigidos junto com o código.
4. **Verificar visualmente o que o checker não vê** (`DC_SCREENSHOT_RT` +
   `vision_analyze`), mas sem confiar no olho para o que um número pode provar.
