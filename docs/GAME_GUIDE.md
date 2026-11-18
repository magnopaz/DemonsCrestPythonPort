# Guia de desenvolvimento — o port de Demon's Crest

*Escrito em 2026-11-17. Complementa os docs específicos (`PIT_BOSS.md`,
`BOSS_HP.md`, `BOSS_INTROS.md`, `ARMA_AI.md`, `TAKES.md`, `TOOLING.md`,
`SESSION_HANDOFF.md`); quando este guia e um doc específico divergirem, o doc
específico ganha.*

---

## 1. O que é isto e como se corre

Um port Python (raylib 6.2 via cffi) do Demon's Crest (SNES), conduzido pelos
mesmos `DC_*` env vars do port nativo em C (`~/Projetos/opencode/DemonsCrestNativePort`).
A fidelidade é a regra: cada comportamento vem de medição (takes do oracle
recompilado) ou de leitura da ROM — nunca de "parece bem".

```sh
cd ~/Projetos/opencode/DemonsCrestPythonPort

# jogar (janela real)
.venv/bin/python -m dcpy.main --assets assets/generated
tools/demonscrest-py                 # atalho com o mesmo contrato

# headless / demos (a regressão inteira precisa disto)
Xvfb :99 -screen 0 1600x1200x24 -nolisten tcp &
DISPLAY=:99 .venv/bin/python tools/run_regression.py
```

**Armadilhas de ambiente** (todas já custaram tempo):

- usar **`.venv/bin/python`** — o `python3` do sistema não tem raylib;
- sem `Xvfb` em `:99` os demos falham com `X11: Failed to open display`;
- editar um valor em Python e reexecutar *no mesmo segundo* pode servir o
  `.pyc` antigo (mtime + tamanho iguais) — apagar `dcpy/__pycache__` se um
  teste parecer não ver a edição;
- `DC_RUN_FRAMES=N` desliga o input real (determinismo) e desliga a save a
  menos que `DC_SAVE_FORCE=1`.

### Os módulos (`dcpy/`)

| ficheiro | papel |
|---|---|
| `main.py` / `__main__.py` | bootstrap, CLI `--assets`, loop 60 Hz |
| `game.py` | estados do jogo, transições, cenas scriptadas, save, traces |
| `player.py` | a máquina de estados do Firebrand (física em 8.8) |
| `object.py` | o pool de 26 objectos: spawn, AI por espécie, projécteis |
| `bosses.py` | HP e dano por forma de todos os bosses (§4.2) |
| `enemy_defs.py` | definições autorais de inimigos (`enemies.json`) |
| `level.py` | rooms: colisão, pisos, rampas, água, portas, spawns |
| `render.py` | desenho: BG, sprites por folha, caixas de debug, HUD |
| `projectile.py` | o pool de bolas de fogo do jogador |
| `input.py` | teclado/gamepad **e os guiões `DC_DEMO`** |
| `text.py` | os 518 blocos de texto da ROM e a caixa de diálogo |
| `audio.py` | trilhas WAV renderizadas + efeitos |
| `mode7.py` | o mapa do mundo em Mode 7 |

### Convenções centrais

- **Fixed point 8.8**: posições e velocidades vivem em inteiros `*_fx`
  (`FX_ONE = 256`); os floats são só a vista pública para a câmara/render.
  Nunca misturar: um `0x0280` na ROM é 2.5 px/frame.
- **Frame = 1/60 s** e o loop é determinístico sob `DC_RUN_FRAMES`.
- **Traces**: `DC_TRACE_CSV` (jogador), `DC_TRACE_OBJECTS` (pool),
  `DC_SCREENSHOT_RT` (PNG por frame). Os checkers comparam traces, não
  screenshots.

---

## 2. Os env vars que importam

| var | efeito |
|---|---|
| `DC_AREA=<id>` | arranca directamente na sala (id = `$008D/2`, 0..112) |
| `DC_RUN_FRAMES=N` | corre N frames e sai; input só dos demos |
| `DC_DEMO=<modo>` | guião de input (§8.4) |
| `DC_START_X/Y`, `DC_START_ONCE` | posiciona o jogador no boot |
| `DC_BOSS_X/Y`, `DC_BOSS_HP`, `DC_BOSS_PHASE` | hooks de teste de bosses |
| `DC_BOSS_CLEAR`, `DC_BOSS_DEFEATED` | simula boss morto |
| `DC_HOLD_PLAYER=x,y` | congela o jogador (usado no poço) |
| `DC_KILL_AT=<frame>` | mata o jogador num frame exacto |
| `DC_NO_AUDIO`, `DC_NO_SAVE`, `DC_NO_STORY`, `DC_NO_OBJ` | desligam subsistemas nos testes |
| `DC_STORY_FLAGS=<int>` | pré-carrega as flags de cenas vistas (§8.2) |
| `DC_INTRO_FORCE=1` | permite a intro do boss sob `DC_RUN_FRAMES` |
| `DC_DIALOGUE_AUTO=N` | avança a caixa de diálogo a cada N frames |
| `DC_AUTHORED_ROOMS=<dir>` | troca a pasta de overlay de rooms (§7.3) |
| `DC_SAVE_PATH`, `DC_SAVE_FORCE` | save em teste |

---

## 3. O jogador (Firebrand) e as suas formas

Tudo vive em `dcpy/player.py`; as constantes no topo são as medidas da ROM:

```
PLAYER_HALF_W = 6.0      PLAYER_HEIGHT = 22.0     hitbox 12×22
PLAYER_WALK_INITIAL_FX = 0x00B3   arranco da caminhada
PLAYER_WALK_MAX_FX      = 0x0166   velocidade máxima (1.35 px/f)
PLAYER_GRAVITY_FX       = 0x0038   (na água 0x002A)
PLAYER_JUMP_FX          = 0x059C   (na água 0x02CE)
PLAYER_TERMINAL_FALL_FX = 0x0600   (na água 0x0300)
PLAYER_FLY_UP_FX        = 0x0200   subida do voo
```

Estados (`consts.py`): `IDLE WALK JUMP HOVER FLY LAND HURT DEAD WALL_CLING
HEADBUTT` (0..9). Animações: 11 clips (`ANIM_*`) com nomes
`idle/walk/jump/hover/fall/land/attack/spell/flying/hurt/death`.

### As seis formas (`CREST_*`)

| forma | const | coluna no `boss_hp.txt` | particularidades |
|---|---|---|---|
| Fire Gargoyle (base) | `CREST_BASE` (0) | Fire | salto + tiro |
| Earth | `CREST_EARTH` (1) | Earth (chão/ar) | dash 0x0280, tiro mais forte no chão |
| Aerial | `CREST_AIR` (2) | Aerial | voo livre |
| Water | `CREST_WATER` (3) | Tidal | física de água |
| Time | `CREST_TIME` (4) | Legendary | dano recebido metade |
| Ultimate | `CREST_ULTIMATE` (5) | Ultimate | tudo + knockback |

- **Trocar de forma**: subscreen no jogo; nos demos, `form_next` (demo 11).
- **Dano que cada forma causa aos bosses**: `dcpy/bosses.py::boss_damage`
  (§4.2). O dano que *recebe* é reduzido a metade com Time/Ultimate ou o
  talismã Armor (`_damage_player` em `object.py`).
- **Arte**: `assets/generated/player_forms.json` + PNGs `fb_<forma>_<clip>_<i>`
  cozidos por `tools/dc_extract/bake_player_forms.py`;
  `assets/authored/player_forms.json` (Player Editor) ganha.
  `DC_PLAYER_FORMS=0` volta à base capturada.

### Como acrescentar uma forma nova

Hoje as formas são as seis da ROM; acrescentar uma sétima toca em:

1. `dcpy/consts.py`: `CREST_<NOME>`, `CREST_COUNT`, e os nomes em
   `player.py::_FORM_NAMES`;
2. `dcpy/bosses.py`: coluna nova em `BossDamage.for_form` (e a linha nos
   bosses afectados, se o documento disser algo diferente);
3. `dcpy/player.py`: física/habilidades (as capacidades testam
   `crest_form in (...)` — ver `player_update` e o voo/dash);
4. `dcpy/render.py`: a folha da forma (`anim_load_forms`) e os desenhos por
   estado;
5. arte: `player_forms.json` (Player Editor) e o HUD (a fileira de crests).

---

## 4. Inimigos, bosses e NPCs

### 4.1 De onde vêm os objectos

Cada sala (`room_area<N>.json`) tem `objects` com
`{type, species, flags, x, y}`. O `objects_init` (`dcpy/object.py`) despacha
pelo `type`:

| type no JSON | const | spawn | uso |
|---|---|---|---|
| `urn` | `LEVEL_OBJECT_URN` | `_spawn_urn` | potes que largam corações |
| `enemy` | `LEVEL_OBJECT_ENEMY` | `_spawn_enemy` | inimigos com handler nativo |
| `platform` | `LEVEL_OBJECT_PLATFORM` | `_spawn_platform` | plataformas móveis |
| `pickup_crest` | `LEVEL_OBJECT_PICKUP_CREST` | `_spawn_crest_item` | pedaços de crest |
| `boss` | `LEVEL_OBJECT_BOSS` | `_spawn_boss` | bosses (o `$96` é o controlador da arena, vira NPC se a sala não tem boss a sério) |
| `npc` | `LEVEL_OBJECT_NPC` | `_spawn_npc` | faláveis |
| `exit` | `LEVEL_OBJECT_EXIT` | — | portas lógicas (o loader mapeia para `transitions`) |
| `talisman` | `LEVEL_OBJECT_TALISMAN` | — | relíquias (Armor, Crown, Claw…) |
| `decor` | `LEVEL_OBJECT_DECOR` | — | decoração sem colisão nem update |
| `inert` | `LEVEL_OBJECT_INERT` | — | objecto presente mas inactivo (ex.: o corpo do poço) |
| `unknown` | `LEVEL_OBJECT_UNKNOWN` | `_spawn_unknown` | espécie sem handler: placeholder magenta na posição viva |

`species` é o byte `$00` da ROM; `flags` o byte `$01` (variante de encontro,
flag de registo, ou índice — depende da espécie). O extractor tipifica tudo
(`tools/dc_extract/extract.py`, `SPECIES_KIND_MAP`); o contrato "853/853
objectos chegam ao room JSON" é afirmado por `tools/check_objects.py`.

### 4.2 HP e dano — onde estão os números

- **Bosses**: `dcpy/bosses.py`. `boss_hp(species, flags)` e
  `boss_damage(species, flags, form, grounded)`. As chaves são
  `(species, flags)` porque os flags escolhem o encontro (Arma 0/2/4 =
  16/32/72 HP). Espécies cujos flags são só bits de registo (Somulo, Grewon,
  Belth) vivem em `SPECIES_HP`/`SPECIES_DAMAGE`.
  - `N/A` no documento → 0 (essa forma não fere o boss);
  - células "2/1" (Dark Demon) → tuplo indexado por `phase`;
  - sem entrada → o boss usa `DEFAULT_BOSS_HP = 8` e o dano do projéctil —
    o `check_boss_hp.py` **falha** se uma espécie nova ficar nesse estado.
- **Inimigos comuns**: HP vem de `enemy_defs.status(species).hp`
  (`assets/authored/enemies.json`, escrito pelo Enemy Editor) com fallback
  para 1; o dano de contacto de `enemy_defs.status().contact_damage`.
- **Caixas de hit**: `objects_check_projectiles` (`object.py`) — urna, ghoul,
  boss (40×46 para o Somulo, 20×24 o resto), os olhos do poço (8×8). O dano
  por forma aplica-se a tudo o que tem linha em `bosses.py`.
- **Poço de Ovununu (área 8)**: só os 10 satélites `$6C` têm HP (3); o corpo
  `$6B` não é alvo de dano e a luta fecha quando os dez morrem — ver
  `docs/PIT_BOSS.md` §7.14 antes de mexer.

### 4.3 Comportamento: os dois caminhos

**A) Handler nativo** (`dcpy/object.py`) — port da máquina de estados da ROM.
É o caminho da fidelidade e o que todos os bosses usam:

1. um update por espécie (ex.: `_ghoul_update`, `_arma_update`,
   `_update_pit_boss`) com os *estados da ROM* (`$05`) e sub-estados (`$06`);
2. os campos do `Object` espelham a DP da ROM: `state`, `substate`, `phase`
   ($3B), `hops` ($38), `spit_cd` ($3C), `hit_flash`, `facing` ($09), etc.;
3. medir antes de portar: `tools/oracle/measure_*.py`, `trace_stage.py
   replay`, `tools/disasm_range.py` (no repo do oracle), `species_census.py`.

**B) Definição autoral** (`assets/authored/enemies.json` via Enemy Editor) —
para espécies novas ou protótipos: `status` (hp, contact_damage), `movement`
(perfis), `attacks` (padrões) e `sounds`. O `object.py` consulta
`enemy_defs.get(species, flags)` e substitui o movimento nativo **só quando
existe definição**. Hoje não há `enemies.json` — tudo corre nativo.

### 4.4 Arte de espécies

- `assets/generated/species_anim.json` — o registo central, formato
  `{"species": {"<hex>": {"frames": [...], "states": {...}}}}`
  (**é um objecto, nunca uma lista** — o loader já tolera ambos, mas os
  bakers escrevem objecto).
- `assets/authored/species_anim.json` e `species_entries.json` — o overlay do
  Enemy Editor; ganham por chave ao gerado.
- Baking: `tools/dc_extract/bake_enemy_sheets.py` (linhas de folhas rotuladas),
  `bake_arma.py` (as três paletas), `bake_player_forms.py`, `bake_scula.py`,
  `bake_somulo_gif.py`; capturas do oracle com `tools/oracle/capture_species.py`
  + `extract_species.py`.
- **O guarda**: `tools/audit_sprites.py --strict` corre na regressão —
  texturas em falta, âncoras fora da imagem e fragmentos de tilemap são
  rejeitados. Um bake mau não entra.

### 4.5 Checklist "nova espécie" (a sério, do zero)

1. **Registo**: a espécie já vem do ROM (object lists) — confere com
   `python3 tools/species_census.py` e `tools/report_coverage.py`. Se é
   *nova* (não existe na ROM), acrescenta um registo num room autoral ou
   `enemies.json` com a `species` escolhida.
2. **Spawn**: garantir que o `objects_init` a encaminha (`unknown` →
   placeholder até haver handler).
3. **Arte**: cozer/autorar a folha (§4.4) e passar `audit_sprites --strict`.
4. **Atributos**: HP/contacto em `enemies.json`, ou HP de boss em
   `bosses.py` (+ o checker revalida contra `docs/boss_hp.txt`).
5. **Comportamento**: handler nativo medido, ou `movement/attacks` autorais;
   se a espécie atira, ver `_spawn_enemy_shot`.
6. **Verificar**: `check_objects.py` (contrato por sala), um checker novo
   com trace a afirmar o comportamento, e a regressão completa.

---

## 5. Física

### 5.1 O jogador

Tudo em 8.8 (`player_update`): gravidade por frame, arrasto, terminal;
água troca as constantes (gravidade 0x2A, salto 0x2CE, terminal 0x300,
caminhar 0x100). O voo (Aerial/Ultimate) sobe a 0x200 e o wall-cling agarra
paredes (`level_is_wall_at`) — o estado `PLAYER_WALL_CLING`. O headbutt
(state 9) parte blocos `level_is_breakable_at`.

### 5.2 O mundo (`dcpy/level.py`)

A colisão é uma grelha 16×16 de *attributes* por sala (vêm das block tables
da ROM). A API que a física usa:

```
level_attr_at(level, x, y)          # o byte de attribute da célula
level_is_solid_at / level_is_wall_at
level_floor_at(level, x, feet_y)    # o chão (com surface offset)
level_surface_offset(attr, local_x) # a tabela de rampas ($80:962B)
level_is_slope_ramp_at / level_is_water_at / level_is_hazard_at
level_is_breakable_at / level_break_block_at
level_env_flags_at                  # bits especiais (0x20/0x40/0x60/0x80)
```

O `collision` do room JSON traz a grelha + `attrs`; o overlay autoral pode
alterá-la (é assim que o BG1 do cemitério foi corrigido).

### 5.3 Objectos

Os inimigos reusam a fixed point: gravidade/bounce em `_spawn_pickup`
(0x0400/0x0040 do `$85:C1D1`), plataformas oscilam ±48 px a 0x80/frame, os
tiros inimigos saem com `vx/vy` inteiros. Os comportamentos medidos (o poço:
subida 700→209 em ~1350 frames pela tabela `_PIT_RISE`, bob 187..216, olhos
com atraso próprio) vivem como **tabelas medidas** em `object.py` — as únicas
fontes são a take e a ROM; quando a regra exacta da ROM não fecha
(`_PIT_EYE_TRACK`), a tabela fica e o motivo está no doc.

**Medir física nova**: grava uma take (`SNESREC_AUTORECORD=1` no oracle, ou
usa as existentes em `~/Projetos/opencode/build-trace/captures/`), replica
com `tools/oracle/trace_stage.py replay <take> --step 20 --objects`, extrai a
curva e escreve a tabela/comparador. Nunca afinar "a olho" contra o port.

---

## 6. Cenários (rooms)

### 6.1 O pipeline de extracção

Os rooms são **gerados a partir da ROM** (git-ignored; regeneráveis):

```sh
bash tools/build_assets.sh    # tudo (precisa da ROM e de captures/)

# à mão, na ordem que importa:
python3 tools/dc_extract/extract.py --rom "../roms/Demon's Crest (USA).sfc" \
    --dump captures/<nome> --prefix stage_<x> --area <id> --screens a,b \
    --full-room --out assets/generated
python3 tools/dc_extract/apply_boss_table.py --rooms assets/generated
python3 tools/dc_extract/apply_gate_table.py --rom "..." --rooms assets/generated
python3 tools/dc_extract/apply_npc_table.py --rooms assets/generated
python3 tools/dc_extract/apply_door_table.py --rooms assets/generated
python3 tools/dc_extract/normalize_rooms.py --rooms assets/generated
```

**IDs de área**: o espaço é 0..112 e `área = $008D / 2` (o `$008D` da WRAM é
um *offset de bytes*). `tools/oracle/scan_take.py <take>` imprime cada mudança
de área de uma take; `captures/save_to_area.json` mapeia 219 saves → áreas.

### 6.2 Anatomia do `room_area<N>.json`

| campo | o que é |
|---|---|
| `world` | tamanho lógico (width/height) |
| `camera` | bandas min/max do scroll |
| `play` | limites onde o jogador pode andar |
| `spawn` / `spawns` | pontos de entrada por id |
| `bg` | BG1/BG2: tilemaps, scroll, paletas |
| `collision` | grelha + attrs 16×16 (§5.2) |
| `transitions` | portas: `{x, y, half_w, half_h, pad_mask, next_area, spawn_id, type}` — `pad_mask` 8 = "up" |
| `objects` | os registos (§4.1) |
| `gate_next_area` / `gate_marker` / `gate_entry` | o portão pós-boss (`$81:97DA`; `$F0` = mapa) |

### 6.3 O overlay autoral — e a guarda

O loader lê `assets/authored/rooms/room_area<N>.json` **antes** do gerado
(`level.py::_load_room_with_override`); `DC_AUTHORED_ROOMS=<dir>` troca a
pasta. É o formato de gravação do **Map Builder** (`python
tools/editor/server.py` — BG, colisão, portas, spawns, inimigos, música por
sala, preview igual ao jogo).

Este overlay já partiu a regressão uma vez: rooms autorais velhos punham o
Somulo em cima do spawn (ver `docs/SOMULO_ROOM_FIX.md`). Por isso existe
**`tools/check_authored_rooms.py`** (na regressão): compara cada room autoral
com o gerado em **bosses, transições, spawn, `gate_next_area` e limites da
arena**; uma diferença sem entrada na `WHITELIST` do checker é erro. Se
editares mesmo um desses campos, acrescenta a entrada com a justificação
medida — nunca com "porque sim".

### 6.4 Como criar/editar uma sala correctamente

1. editar no Map Builder (gravar → `assets/authored/rooms/`) ou regenerar do
   ROM (se for correção de extracção, mexe no extractor, não no JSON);
2. se a sala tem boss, a posição/flags vêm da tabela verificada
   (`tools/check_bosses.py::BOSSES` + `apply_boss_table.py`);
3. correr `check_authored_rooms.py`, `check_objects.py` (multiset por sala) e
   `check_up_doors.py`/`check_navigation.py` se tocaste em portas;
4. um room autoral **não** substitui a extracção — se está mal no gerado,
   corrige-se no extractor.

---

## 7. Cenas scriptadas e apresentação

### 7.1 Os estados do jogo (`consts.py`)

`GAME_TITLE 0 · PLAYING 1 · PAUSED 2 · CLEAR 3 · SUBSCREEN 4 · OVERWORLD 5 ·
SHOP 6 · PASSWORD 7 · OPTIONS 8 · OVER 9 · ENDING 10 · DIALOGUE 11 ·
CONTINUE 12 (hub de morte) · PASSWORD_VIEW 13`.

### 7.2 Diálogo e flags de história

- **Texto**: `assets/generated/text_strings.json` (518 blocos, endereços da
  ROM, páginas/linhas) extraído por `tools/dc_extract/extract_text.py`.
  Códigos: `j` = quebra de linha, `0x02` = nova página, `]` = reticências, `[`
  = apóstrofo. O loader (`dcpy/text.py`) já corta o `RTL` (0x6B='k') que se
  cola ao início dos blocos — não reintroduzir.
- **Mostrar**: `text_find(game.script, "SUBSTRING")` → índice;
  `game.dialogue_text/page/return` + `state = GAME_DIALOGUE`
  (avança com start ou `DC_DIALOGUE_AUTO=N`).
- **"Visto uma vez"**: `game.story_flags` — um bit por área, gravado no save
  (`saves/dc_save.json`, campo `story_flags`). A tabela
  `BOSS_INTRO_TEXT` em `game.py` liga área → texto (a área 23 mostra a intro
  do Arma 2 uma vez). Hooks: `DC_STORY_FLAGS`, `DC_INTRO_FORCE`,
  `DC_NO_STORY`. Ver `docs/BOSS_INTROS.md`.

### 7.3 Cenas existentes

| cena | onde | como se verifica |
|---|---|---|
| intro do Somulo (4 fases: 150/70/280/110 frames, shake) | `game_update_boss_intro` | `check_mvp_somulo.py` (intro + combate + faint + gate) |
| hub de morte (90 frames → RETRY / SELECT A STAGE / END) | `GAME_CONTINUE`, `game_update_continue` | `check_death_menu.py`, demos 42–45 |
| mapa Mode 7 | `mode7.py`, `game_open_overworld` | `check_map_mode7.py` |
| endings (bad/normal/good/true) | `endings.json` + `_game_ending_step`/`_draw_ending`; sem o Crest of Time = bad, com Time (sem os 5 talismãs) = normal, Time + talismãs = good; o gatilho é a morte do `$8D` nas áreas 42/75 (`PHALANX_BOSS_AREAS`) | `check_bad_ending.py`, `docs/ENDINGS.md` |
| lojas / NPCs | `GAME_SHOP`, `game_try_talk` | guiões de texto + demos |

### 7.4 Demos (guiões de input)

`dcpy/input.py`, activados por `DC_DEMO=<modo>` com `DC_RUN_FRAMES`. Os que
a regressão usa: **13** (title → NEW GAME → área 0), **14** (matar o Somulo
a sério e sair pela porta pós-boss), **16** (boss-then-gate do Arma),
**30** (stage select no mapa → área 16), **32** (pause + SAVE escreve o
ficheiro), **33** (Start cancela o attract demo do title), **36** (atravessar
portas à direita, com o `DC_BOSS_CLEAR`), **41** (probe de porta "up"),
**42–45** (hub de morte: RETRY / SELECT / END / PASS WORD). Um guião novo =
um `elif mode == N` nesse ficheiro + um checker que o conduza e compare
traces.

### 7.5 Medir uma cena da ROM (takes + oracle)

```sh
# gravar (no oracle): SNESRECORD com SNESREC_AUTORECORD=1 (ou Alt+R)
# digitalizar a take:
.venv/bin/python tools/oracle/scan_take.py <take> -o /tmp/take.csv --step 20
# replay com pool de objectos:
.venv/bin/python tools/oracle/trace_stage.py replay <take> -o /tmp/t.csv \
    --step 20 --objects
# desassemble da ROM (no repo do oracle):
python3 tools/disasm_range.py 83:C1C2 83:C260 \
    --rom "../roms/Demon's Crest (USA).sfc"
```

Pitfalls do debug server: `read_ram` leva **comprimento em decimal**; sem
`run_to_frame 1` não há WRAM; o `replay_input` exige JSON compacto (o
`sscanf` engole silenciosamente espaços); mata emuladores velhos com
`kill -9` e usa uma porta por corrida. Tudo isto com exemplos está em
`docs/TAKES.md`.

---

## 8. Áudio

A decisão medida (não reabrir): **WAVs renderizados** do DSP do oracle,
não replay do SPC700 in-process (`docs/AUDIO_PLAN.md`). O pipeline é
`tools/audio/make_music_asset.py`: captura a trilha de um save → mede o
loop por correlação de envelope → corta com emenda contínua → grava o
`assets/generated/audio/music_manifest.json` (período, RMS, pico, hash)
para a regressão poder afirmar sem ouvidos.

Estado actual: só `music_boss.wav` está cozido; os WAVs por nível
(`music_murkland.wav`, …) estão pendentes e são a única falha da regressão
completa. Cozer: `python3 tools/audio/make_music_asset.py` (todas) ou
`--track <nome>`; `--use-capture` recorta capturas existentes.

---

## 9. Verificação (a cultura do projecto)

- **Comportamento medido, não resumo.** Cada mudança aterra com um checker
  que compara traces do port contra a ROM/take.
- A regressão: `DISPLAY=:99 .venv/bin/python tools/run_regression.py`
  (~7 min; até ~20 com a máquina carregada). O resumo lista tudo o que
  passou; `FAIL` imprime a lista de mensagens.
- **Escrever um checker**: subprocess com env limpo (pop dos `DC_*` que não
  queres), `DC_TRACE_*` para ficheiros temporais, asserções sobre as
  colunas do trace, `print("PASS (...)"`), exit 0/1 (+77 = "skip, falta
  asset"). Regista no `run_regression.py` perto dos congéneres e acrescenta
  ao texto de PASS.
- Traces: jogador `frame,player_x,player_y,vx,vy,state,camera_x,camera_y,
hp,max_hp,area,form,gold,fire,mode`; pool (`DC_TRACE_OBJECTS`)
`frame,slot,type,x,y,vx,vy,state,hp,flash,species,flags,sub,phase,scale,
anim`; projécteis (`DC_TRACE_PROJECTILES`) `frame,slot,x,y,vx,age`.
- Contratos existentes que devem continuar verdes: `check_objects`
  (853/853), `check_bosses` (+runtime), `check_boss_hp` (HP+dano por forma
  contra `docs/boss_hp.txt`), `check_authored_rooms`, `check_pit_boss` +
  `check_pit_damage`, `check_mvp_somulo`, `check_up_doors`,
  `check_death_menu`, `check_arma`, `check_arma2_intro`,
  `check_bad_ending`, `audit_sprites --strict`, `test_editor`.

---

## 10. Mapa rápido do repositório

```
dcpy/                     motor (ver tabela §1)
assets/generated/         gerado da ROM: rooms, species_anim, text, audio, endings
assets/authored/         overlay do editor: rooms/, species_anim, player_forms,
                          species_entries (não é pixel-art: PNGs + JSON)
tools/demonscrest-py     launcher com o contrato do port C
tools/dc_extract/        extracção + bakers (rooms, texto, sprites, áudio)
tools/oracle/            medição: takes, replay, measure_*, scan_take
tools/editor/            Map/Enemy/Player Editor + Coverage/Checks (server.py)
tools/check_*.py         os gates da regressão
tools/run_regression.py  o guarda-roupa inteiro
docs/                    PIT_BOSS, BOSS_HP, BOSS_INTROS, ARMA_AI, TAKES,
                          TOOLING, SOMULO_ROOM_FIX, SESSION_HANDOFF, …
saves/dc_save.json       a save do jogador (area, HP, crests, story_flags…)
../DemonsCrestSNESRecomp/  o oracle (emulador recompilado + saves + disasm)
../roms/Demon's Crest (USA).sfc   a ROM (apóstrofo! citar sempre em shell)
```

*Quando algo aqui estiver desactualizado, corrige o guia no mesmo commit que
mudou o comportamento — é o combinado com a handoff.*
