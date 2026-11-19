# Próximos passos para terminar o jogo

*Escrito a 2026-11-03, no fim da sessão que fechou o Arma → Earth Crest →
área 94 e o mapa em Mode 7. **Re-auditado a 2026-11-18** (Somulo/poço/HP
fechados, overlay de rooms guardado; números re-medidos e itens velhos
corrigidos nesse dia). O comando que diz quanto falta continua a ser
`python3 tools/report_coverage.py` — corrê-lo antes de planear. O HEAD
actual está sempre em `docs/SESSION_HANDOFF.md`, não aqui.*

---

## 0. Antes de tocar em código

- **Ler `docs/SESSION_HANDOFF.md`** — estado, commits, comandos e armadilhas
  da sessão anterior. O HEAD e o estado da árvore estão lá; não fixar hashes
  neste doc.
- **O Passo 1 está feito e commitado.** Se aparecer trabalho por commitar, é
  da sessão corrente: rever e commitar antes de mexer no extractor.
- Verde de referência: `DISPLAY=:99 .venv/bin/python tools/run_regression.py`
  — **`.venv/bin/python`**, o `python3` do sistema não tem raylib; Xvfb em
  `:99`, sem ele os demos falham com "X11: Failed to open display".
  Estado (2026-11-18): **verde excepto o áudio** (Passo 6) — a única falha
  conhecida, não bloqueia os outros passos.
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
species with a handler ..... 20/80  (552 records drawn as placeholders)
rooms with a BG2 tilemap ... 65/113
species sprite sheets ...... 31
music tracks ............... 1
```

A leitura mudou: **já não se perdem objectos**. Todos os 853 registos chegam ao
port; 552 são espécies sem handler e aparecem como marcadores magenta até
haver AI/arte. O trabalho que resta é substituir marcadores por handlers, não
recuperar dados perdidos. O contrato está em `docs/OBJECT_COVERAGE.md`.

---

## 1c. Próximo troço (decidido a 2026-11-04): estágio II jogável de ponta a ponta

As takes de estágio II (`docs/TAKES.md` §6) fecharam o mapa da zona: áreas
4→5→6→7→8 e 4→46/47/48, com coordenadas e `pad_mask` medidos. A ordem abaixo é
por dependência: cada passo desbloqueia o seguinte.

### Passo A — `pad_mask` e as três portas up da avenida (meia sessão) — **feito**

O que está medido: `pad_mask: 8` é o bit de **up** do ROM (5→6, 6→7 e 7→8 são
precedidas de um toque de up de um frame; 4→5 é só andar e tem `255`). As
portas da avenida são (424,428)→46, (664,428)→47 e (824,124)→48, todas no
spawn 0 do destino.

- `dcpy/game.py::game_check_transitions` ignora `pad_mask` e transita por
  proximidade. Passar a exigir o botão: `8` → up premido; `255` → qualquer.
- `dcpy/level.py` já guarda `pad_mask`; o input do port são booleanos, por isso
  o mapeamento é `pad_mask == 8` → `input.up`.
- As três portas entram pelo caminho normal dos assets, não à mão:
  `tools/dc_extract/apply_door_table.py` ganha uma tabela `take_door`
  (`source: "take_door"`, `half_w/half_h = 16`) — os room JSON são gerados.
- Paridade: a mesma mudança em `reference/c-src/src/game.c`.
- **Aceitação**: `tools/check_up_doors.py` (na regressão) — em `DC_AREA=4`
  com o jogador em (424,428), carregar up muda para a área 46; ficar 60 frames
  no mesmo sítio sem carregar **não** muda; (664,428)→47 e (824,124)→48 idem.
  Regressão: as portas 5→6/6→7/7→8 deixam de disparar sem up.

**Resultado (2026-11-04):** feito em `15c6c4d`. `apply_door_table.py` tem a
tabela `TAKE_DOORS` (`source: "take_door"`, 16×16, spawn 0, `pad_mask` 8);
`game_check_transitions` (C e Python) exige o botão; `check_up_doors.py` cobre
os seis casos (três portas novas e as três 5→6/6→7/7→8) e está na regressão.
`DC_DEMO=41` toca up; `DC_START_ONCE=1` mantém o `DC_START_X/Y` na sala de
boot.

**Correcção do `$96`**: o extractor tipa todos os registos `$96` como `boss`,
mas a espécie é o actor de script/NPC (lojistas e velho da biblioteca em
46–49/55, o habitante da avenida na área 4, o controlador da arena em
52/53/54). Como boss, `boss_alive` ficava verdadeiro e **todas as transições
da sala eram saltadas** — a avenida e os interiores estavam fechados sem
`DC_BOSS_CLEAR`. `objects_init` (C e Python) passa a spawnar `$96` como NPC
quando a sala não tem um boss a sério, e a ignorá-lo quando tem (é o
controlador). `check_up_doors.py` ganhou duas corridas sem `DC_BOSS_CLEAR`
(4→46 e 46→4) que falham se o fantasma voltar.

### Passo B — menu de morte `RETRY / SELECT A STAGE / END` (uma sessão) — **feito**

Substitui o `GAME_OVER` inventado (`dcpy/game.py::game_handle_death` e o
equivalente C). Comportamento medido/confirmado:

- RETRY: recarrega a **mesma área no spawn 0** com HP cheio (área 9 → (48,412);
  área 8 → (32,668)); no console há ~1–2 s de animação de morte e depois o ecrã.
- SELECT A STAGE: `game_open_overworld()` — o mapa Mode 7 que já existe.
- END: ecrã `PASS WORD` 4×4 com `PUSH START BUTTON`; o password leva ao mapa.
  Só fica fiel quando o codec retail estiver invertido — até lá, mostrar o codec
  nativo atrás de uma flag e assumir a diferença no HUD.
- Hook de teste `DC_KILL_AT=<frame>` (mata o jogador nesse frame) para o checker.
- **Aceitação**: `tools/check_death_menu.py` (na regressão) — mata na área 9,
  vê o menu, RETRY repõe posição (48,412) e HP cheio; SELECT A STAGE entra em
  `GAME_OVERWORLD`; END desenha o ecrã com as 16 letras.

**Resultado (2026-11-04):** `GAME_CONTINUE` (12) e `GAME_PASSWORD_VIEW` (13)
em C e Python. A morte corre 90 frames de animação e abre o hub; RETRY usa o
restart existente (mesma área, spawn 0, HP cheio, fade de 90 frames); SELECT A
STAGE abre o mapa; END mostra o 4×4 com o codec nativo zero-padded (6 `B` +
10 símbolos — o retail continua por inverter) e START volta ao mapa. O spawn
ROM (48,412) aparece no trace do port como (48,432) porque `Player_Init`
assenta os pés na floor, o mesmo +20 das spawns da avenida. Checker
`tools/check_death_menu.py` na regressão; hooks `DC_KILL_AT` e
`DC_STATE=continue`.

### Passo C — bosses do estágio II (2–3 sessões cada, só depois de A e B) — **em curso**

**Poço (2026-11-04, duas sessões):** a medição está em `docs/PIT_BOSS.md` —
papéis das três espécies, handlers (`$69 $83:B96E`, `$6B $83:BFDD`, `$6C
$83:C7B2`), a máquina do `$6B`, a sequência de y e (novo §7) o ciclo completo
dos 11 `$6C`: parque, `sub 2→4` aos 220 frames, o desvio por olho até 123 px no
topo, o olho central em `state 2` preso ao corpo em (+1, +$1C) e a máquina de
lançamento (`sub 6`+, dez sub-subestados) descodificada mas não portada.
**Implementado:** o `$69` liga o combate pela condição do ROM (`x<128` ou
`y>=568`); o `$6B` espera 199 frames (antes subia cedo) e sobe 700→209 em
~1350 frames com bob; os 11 `$6C` parqueiam no x medido e seguem o corpo dentro
de 4 px da take (`tools/oracle/measure_pit_eyes.py` mede, `_PIT_EYE_TRACK`
guarda). Também se removeu a porta `8→10` que expulsava o jogador no frame 1.
As tabelas dos olhos estão resolvidas (banco `$81`, `$81:E2DF` com stride 12,
`docs/PIT_BOSS.md` §7.6). **Falta:** fechar a regra de `sub 4` com a tabela
(hoje ~25 px de erro; o medido dá 2 px), a arte e o lock da arena. O fim de
luta e a saída do corpo estão feitos (§7.14, 2026-11-17): o corpo não leva
dano, a luta fecha com os dez satélites mortos e o corpo sai a piscar 12×3
frames.

**HP (2026-11-07):** a tabela área→HP existe — `dcpy/bosses.py` lê
`docs/boss_hp.txt` (Arma 16/32/72, Hippogriff 16/24/64, Scula 24/10,
Holothurion 72, Crawler 36, Flame Lord 26, Phalanx 50/127, Dark Demon 200,
Belth 32, Grewon 64; Somulo fica no guião 3+3). `tools/check_boss_hp.py` está na
regressão: compara o documento com a tabela (HP e as dez colunas de dano),
onze casos da forma -> coluna, todas as salas com boss e o `hp` do
`DC_TRACE_OBJECTS` em runtime. O dano por forma já está ligado em todos os
bosses com entrada; `Buster`/`Claw`/`Demon Fire` não existem no port. Ver
`docs/BOSS_HP.md`.

**Diálogo de intro (2026-11-07):** `story_flags` (um bit por área, na save) +
`BOSS_INTRO_TEXT` em `dcpy/game.py`; a área 23 mostra o bloco do Arma
(`BE:F162`, 7 páginas) só na primeira entrada. `tools/check_arma2_intro.py`
cobre os quatro casos e está na regressão. Ver `docs/BOSS_INTROS.md`.

- **Poço (área 8)**: `$6B` sobe atrás do jogador (y 700→212 medido), `$6C` são
  os olhos que voam, `$69` fica fixo no fundo. Não é `$16`; a entrada da área 54
  nessa tabela é outra coisa. Dados em `docs/TAKES.md` §6.1.
- **Belth (área 9)**: `$68`, 30 registos. **A máquina está lida da ROM e
  medida contra duas takes** (`docs/BELTH_68.md`): 2 estados × 7
  subestados byte-indexados, controlador que teleporta + peças que
  homingam ±3px (deadzone 4) e ancoram nas posições dos registos; a take
  §6.2 tem as duas mortes, a `rec_level_2` do utilizador (2026-11-18) tem
  **o kill** — as peças desaparecem todas de uma vez. Falta: estados
  vivos ($05/$06 no blob do trace_stage), arte (captura na sala real) e
  o port em si.

### O que **não** fazer primeiro

- **Password retail**: uma amostra (`WFRF PXFR HSJS ZHCS`) não inverte um codec.
  Com o `END` do Passo B a funcionar, o port passa a colher pares
  estado → password — é a instrumentação que falta.
- **BG2 em runtime (Passo 3)**: as salas do estágio II já têm BG2 e desenham.

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
(`$86`/`$8D` — segunda forma), Holothurion, **Ovnunu do poço — só o sub 4,
a arte e o lock (§1c; o fecho e a saída estão feitos)**, Grewon, Dark Demon,
Flame Lord, `$16`, `$58`, `$6F`, `$82`, `$BC`.

**Phalanx (2026-11-10):** a câmara é a **área 42** (não a 84) e o `$86` vem do
registo do ROM; o `$8D` nasce com 127 HP quando a primeira forma cai, a intro
toca na entrada e a morte do `$8D` arranca o ending (`docs/ENDINGS.md`).
`tools/check_bad_ending.py` cobre-o. Falta a AI real do `$86` — a do port é
aproximada (drift + orbe) — e a cenografia do ending.

Para cada um: mesma receita do Arma; o que muda é a tabela de despacho e as
constantes. `docs/ARMA_AI.md` serve de molde de documentação (handler, tabela,
estados, constantes, ciclo medido, o que ficou por fazer).

### Passo 5 — História, menus e apresentação

- Intro/coliseu, os quatro endings, créditos e o subscreen retail com o motor de
  texto que já existe (`game_text`/`script`), hoje a funcionar só em parte.
- **Endings (2026-11-10):** a regra é Time Crest + talismãs (bad/normal/good) e
  o gatilho é a morte do `$8D` na área 42/75; o `true` continua a ser do Dark
  Demon. Falta a cenografia real (páginas, tempos, arte) — não há captura de
  nenhum ending. Ver `docs/ENDINGS.md`.
- NPCs de cidade com diálogo completo (`$96` está colocado numa sala só).
- Password retail: algoritmo por descobrir. Codec nativo funciona; o vector
  `QFFF KNRR DDLR XGTQ` é o alvo para o inverter.
- Minijogo do headbutt (arena do coliseu).

### Passo 6 — Áudio

- 1 faixa (`music_boss.wav`). A rota "correr o driver SPC700 in-process" está
  **fechada por medição** (`docs/AUDIO_PLAN.md`): sem um 65C816 em lockstep, o
  handshake IPL não se reproduz. Não repetir a experiência.
- **Estado (2026-11-18): é a única falha da regressão.** Faltam as faixas
  por nível — `tools/audio/make_music_asset.py`, manifest em
  `assets/generated/audio/music_manifest.json`: `music_murkland`,
  `music_ruined_city`, `music_dark_forest`, `music_towers_of_doom`,
  `music_poseidonia`, `music_mountains`, `music_phalanx`,
  `music_demon_hideout`, `music_town`, `music_overworld` (pedidas pelas áreas
  88–96 e pelos fallbacks 0–VIII). Exige corridas do oracle com saves por
  nível; nada disto se cozinha localmente sem captura.
- Caminho realista: (a) extrair BRR/SFX individualmente e tocar samples, ou
  (b) banda sonora de substituição, uma faixa por área/boss/menu.
- **Aceitação**: todas as salas com música, sem cortes no loop, volume
  coerente; `check_audio.py` cobre duração/seam como hoje.

### Passo 6b — Infra: regressão sem render (meia sessão)

Medido a 2026-11-18 (600 frames, demo 7, Xvfb, cProfile): `EndDrawing` **49%**
do tempo (present de GL em software), `game_render` **44%** (o BG desenhado
tile-a-tile, 1 902 `DrawTexturePro`/frame), **a simulação inteira 1.3%**
(0.5 ms/frame — ~25 fps headless). A regressão passa 20 minutos a desenhar
framebuffers que nenhum checker lê: os checkers comparam **traces CSV**.

- `DC_NO_RENDER=1` em `dcpy/main.py`: em modo determinístico (`DC_RUN_FRAMES`),
  saltar `game_render` + `BeginDrawing/EndDrawing` quando não há
  `DC_SCREENSHOT*` no ambiente. Esperado: 600 frames de ~24 s → ~2 s; a
  regressão completa de ~20 min → ~2–3 min. É a mudança de maior alavancagem
  do projecto e não toca no framework (ver `docs/GAME_GUIDE.md` §1).
- **Aceitação**: checker de paridade — o mesmo demo com e sem render produz
  **traces idênticos** (o render não pode influenciar a simulação); os PNGs de
  `DC_SCREENSHOT*` continuam a sair quando pedidos.
- Depois, se o fps na janela importar: cachear as bandas do BG em
  `RenderTexture2D` (redesenho só em scroll) — o loop Python das bandas é
  ~14 ms/frame e é o teto de fps mesmo com GPU.

**Resultado (2026-11-18): feito, excepto o cache das bandas.**
`DC_NO_RENDER` em `dcpy/main.py` (só em modo determinístico; um
`DC_SCREENSHOT*` no ambiente desliga-o e captura normalmente);
`tools/check_no_render.py` na regressão prova a paridade — traces
**byte-idênticos** com e sem render, e o caminho das screenshots continua a
renderizar. A regressão exporta `DC_NO_RENDER=1` para todos os filhos; os
checkers que verificam o próprio desenho (`check_objects`, `check_flame`,
via `DC_TRACE_PLACEHOLDERS`) fazem `env.pop` — verificam a renderização,
não a simulação. Medido: 600 frames 24.7 s → 0.9 s (**27×**); a regressão
completa **~20 min → 4m09s**, com a mesma lista verde (só o áudio vermelho).
O cache das bandas do BG (fps na janela) fica pendente — é o único pedaço
deste passo que ainda não vale a pena.

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

- ~~**Morte: menu de continue, não game over**~~ — **feito no Passo B**
  (2026-11-04; retirado daqui na auditoria de 2026-11-18 porque o item tinha
  ficado duplicado e desactualizado: `GAME_CONTINUE`/`game_update_continue`
  + `check_death_menu.py` já cobrem RETRY/SELECT/END).
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
- **Tiro rasteiro não acerta inimigos no chão** (achado no Passo B): o fireball
  nasce a `player.y - 18` (pés) e a colisão com inimigos usa `±12` em torno do
  `o.y`, que também é a origem/spawn (pés). Um esqueleto na mesma floor fica
  fora do alcance por ~6 px. O `run_regression` escondia isto: o antigo teste da
  área 2 passava porque o jogador morria primeiro e o trace parava no frame
  229, o que parecia a morte do inimigo. Com o hub de morte a simulação
  continua e o falso positivo desapareceu. O teste passou a provar um hit real
  no inimigo flutuante da área 2 (ledge em x=1000); corrigir o hitbox dos
  inimigos é Passo 2 — precisa da convenção do ROM, não de um offset adivinhado.

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
5. **Rooms autorais passam pela guarda**: depois de gravar no editor,
   `tools/check_authored_rooms.py` tem de continuar verde — mexer em
   bosses/portas/spawn/gate num room autoral sem entrada justificada na
   whitelist é erro (foi assim que um overlay velho partiu o combate do
   Somulo; `docs/SOMULO_ROOM_FIX.md`).
6. **Conferir a branch antes de commitar** (`git branch --show-current`): o
   `git bisect` deixa o HEAD detached — uma cadeia inteira já ficou órfã por
   se commitar sem verificar (recuperada a 2026-11-18 com fast-forward).
