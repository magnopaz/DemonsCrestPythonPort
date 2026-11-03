# Próximos passos para terminar o jogo

*Escrito a 2026-11-03, no fim da sessão que fechou o Arma → Earth Crest →
área 94 e o mapa em Mode 7. Números re-medidos depois do Passo 1 (cobertura de
objectos) com `python3 tools/report_coverage.py` — voltar a correr esse comando
antes de planear, porque é ele que diz quanto falta de verdade.*

---

## 0. Antes de tocar em código

- **O Passo 1 está feito e commitado.** A árvore está limpa e
  `python3 tools/run_regression.py` passa com o `check_objects.py` novo ligado.
  Se aparecer trabalho por commitar, é da sessão corrente: rever e commitar
  antes de mexer no extractor.
- Verde de referência: `DISPLAY=:99 python3 tools/run_regression.py` (Xvfb em
  `:99`; sem ele os demos falham com "X11: Failed to open display").
- Checkers do milestone: `tools/check_arma.py`, `tools/check_map_mode7.py`,
  `tools/check_bosses.py`, `tools/check_campaign.py`,
  `tools/check_objects.py`.

## 1. Onde o jogo está (medido, não estimado)

```
rooms extracted ............ 113  {'playable': 69, 'partial': 44, 'empty': 0}
rooms with objects ......... 92
objects placed / ROM ....... 853/853  (100.0%)
objects dropped ............ 0  (0 species)
objects in room JSON ....... 862  (82 species: boss_table 8, npc_table 1, rom 853)
objects listed in the ROM .. 853  (80 species, 90 areas)
species with a handler ..... 17/80  (591 records drawn as placeholders)
rooms with a BG2 tilemap ... 65/113
species sprite sheets ...... 28
music tracks ............... 1
```

A leitura mudou: **já não se perdem objectos**. Todos os 853 registos chegam ao
port; 593 são espécies sem handler e aparecem como marcadores magenta até
haver AI/arte. O trabalho que resta é substituir marcadores por handlers, não
recuperar dados perdidos. O contrato está em `docs/OBJECT_COVERAGE.md`.

---

## 2. A fila, por ordem de dependência

### Passo 1 — Parar de descartar objectos (1 sessão) — **feito**

`extract.py` tipifica todas as espécies (`"unknown"` quando não há handler),
cada objecto leva `source` (`rom` / `boss_table` / `npc_table`), o port carrega
e desenha o placeholder, e `tools/check_objects.py` fecha a porta: por área, a
multiset de espécies tem de bater certo com `rom.object_list(area)`. Resultado:
853/853, 0 em falta. Ver `docs/OBJECT_COVERAGE.md`.

### Passo 2 — As 20 espécies mais comuns (3–5 sessões)

O censo que abre o passo está em `docs/SPECIES_CENSUS.md`:
`python3 tools/species_census.py` resolve as quatro tabelas de despacho
(`$82:8000/8180/8300/8480`), lê a tabela de estados de cada update e diz quantos
estados, que helpers e que arte cada espécie tem. Ordem de ataque:

1. ~~`$72` (13 registos na área 1)~~ — feito como **decor**: chama de 5 frames,
   sem AI, sem dano; `check_flame.py` na regressão. Ver `docs/FLAME_72.md`.
   Pelo caminho corrigiu-se um bug real: `_load_species_sheets` iterava o JSON
   como lista e nenhum sheet de espécie carregava.
2. ~~`$9B` (24 registos)~~ — feito como **inert**: o init não aponta metasprite e
   o oracle não desenha OAM (nem com `--flags 0x80`); era um controlador de
   script, não uma peça visível. Deixou de inventar placeholders nas salas
   52/53/54.
3. `$68` (30, 2 estados) e `$B0` (18, 2 estados) — máquinas pequenas com
   tabelas próprias. `$68` ainda sem arte (a captura não desenha).
4. `$63` (35, 3, arte de 1 pose já cozida) — primeiro inimigo completo.
5. `$06`, `$30`, `$61`; depois os de 5 estados; `$50`/`$20`/`$9C` no fim.

Antes das espécies, portar os helpers partilhados (§4 do censo): probe
rectangular `$809CA4`, colisão `$808C31/$808BED`, allocator `$82877B`, random
`$BC904B`. Sem eles cada espécie é uma ilha.

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
- **Placeholders**: as 14 chamas `$72` da área 1, os `$96` das áreas 46–55 e
  todas as outras espécies sem handler aparecem agora como caixas magenta. É
  intencional; cada handler novo (Passo 2) tira-as do ecrã.

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
