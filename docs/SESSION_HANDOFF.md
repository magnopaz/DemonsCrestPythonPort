# Handoff — sessões de 2026-11-03/04

*Para retomar noutra sessão. Ler isto primeiro, depois `docs/NEXT_STEPS.md`.*

## Estado

- Repo: `~/Projetos/opencode/DemonsCrestPythonPort`
- `HEAD` = o commit *Plan the next three steps…* (2026-11-04), **árvore
  limpa**. As secções desta sessão estão no fim do ficheiro.
- Regressão verde: `DISPLAY=:99 python3 tools/run_regression.py` → PASS
  (~7 min). Xvfb em `:99`; sem ele os demos falham com
  "X11: Failed to open display".
- Assets são git-ignored e regeneráveis com `tools/build_assets.sh`
  (precisa da ROM e de `captures/`).

## O que fechou nesta sessão (4 commits)

| commit | conteúdo |
|---|---|
| `2155880` | **Passo 1**: todas as 853 recordações de objecto do ROM chegam ao room JSON (0 em falta); espécies sem handler ficam `"unknown"` e desenham placeholder magenta; `tools/check_objects.py` fecha o contrato; `report_coverage`/`audit_campaign` medem "colocados / 853". |
| `164263a` | **Censo do Passo 2**: `tools/species_census.py` resolve as 4 tabelas de despacho `$82:8000/8180/8300/8480`, lê a tabela de estados de cada update, detecta helpers; `docs/SPECIES_CENSUS.md` com as 20 mais comuns. |
| `35d690a` | **`$72` como decor**: chama de 16×16 com 5 frames nos archotes da área 1; `LEVEL_OBJECT_DECOR`; `tools/check_flame.py`. Corrigiu `dcpy/assets.py::_load_species_sheets`, que iterava `species_anim.json` como lista — **nenhum sheet de espécie carregava**. |
| `942e978` | **`$9B` como inert**: 24 registos (8 peças 2×4 nas salas 52/53/54) que não desenham nada; `LEVEL_OBJECT_INERT`; `capture_species.py --flags`. |

Números actuais (`python3 tools/report_coverage.py`):

```
objects placed / ROM ....... 853/853  (100.0%)
species with a handler ..... 19/80  (554 recordações → placeholder)
placeholders por tipo ...... unknown 556 (inclui 2 $96 obsoletos)
```

## Comandos que importam

```bash
cd ~/Projetos/opencode/DemonsCrestPythonPort

# relatório de cobertura
python3 tools/report_coverage.py
# contrato de objectos + placeholders
DISPLAY=:99 python3 tools/check_objects.py
# chamas $72
DISPLAY=:99 python3 tools/check_flame.py
# censo de espécies (opcional: --species 0x63 --disasm)
python3 tools/species_census.py
# regressão completa
DISPLAY=:99 python3 tools/run_regression.py
```

Regenerar as salas depois de mexer no extractor (ordem do `build_assets.sh`):

```bash
python3 tools/dc_extract/extract.py --rom "../roms/Demon's Crest (USA).sfc" \
    --dump captures/graveyard --prefix stage_600 --area 1 --screens 9,10 \
    --full-room --out assets/generated
python3 tools/dc_extract/apply_boss_table.py --rooms assets/generated
python3 tools/dc_extract/apply_gate_table.py --rom "../roms/Demon's Crest (USA).sfc" --rooms assets/generated
python3 tools/dc_extract/apply_npc_table.py --rooms assets/generated
python3 tools/dc_extract/apply_door_table.py --rooms assets/generated
python3 tools/dc_extract/normalize_rooms.py --rooms assets/generated
```

## Armadilhas descobertas (poupar tempo na próxima)

1. **Saves do oracle**: vivem em
   `../DemonsCrestSNESRecomp/build/saves/`, não em `build-trace/saves/` (essa
   pasta está vazia). O default do `capture_species.py` aponta para a vazia —
   passar sempre `--save ../DemonsCrestSNESRecomp/build/saves/save0.sav`.
2. **`captures/species_top/manifest.json` é reescrito em cada corrida** do
   `capture_species.py`; o `extract_species.py` só coze o que está nesse
   manifest. Capturar espécies em corridas separadas sobrescreve as anteriores.
3. **`species_anim.json` é um objecto** `{"species": {"72": {...}}}`, não uma
   lista. O port C e os bakers usam esse formato; o loader já aceita os dois,
   mas não voltar a escrever listas.
4. **`capture_species.py --flags`**: o registo injectado levava sempre
   `$00 = 1`; espécies cujo init lê as flags corriam o ramo errado. `$9B` com
   `--flags 0x80` continua sem OAM (é invisível); `$68` com `0x84` desaparece.
5. **`extract_species.py` rejeita "player-lookalikes"**: se a janela da captura
   só tem o sprite do jogador, a espécie não é cozida (foi o caso de `$9B` e
   `$50`). Não é bug do extractor.
6. **O `$72` do ROM também gera cópias** (`$D59A`, allocator `$82877B`, limite
   `$0E51 < $E98E`); essa parte não está portada — ver `docs/FLAME_72.md`.

## Próximo: explorar as capturas de estágio do utilizador

O utilizador vai fornecer capturas dos estágios na próxima sessão. O que fazer
com elas, por ordem:

1. **Inventariar**: que estágios/áreas, que formato (frames do oracle?
   screenshots? vídeo?), quantos. Mapear para áreas com
   `captures/save_to_area.json` (219 entradas save→área) e
   `tools/oracle/map_saves_to_areas.py` se forem savestates.
2. **Comparar com o port**: `tools/oracle/capture_room_tour.py`,
   `tools/oracle/compare_rooms.py`, `tools/compare_frames.py` e
   `tools/oracle/room_match.py` (score de BG1 por ecrã) já fazem a comparação
   lado a lado. O port aceita `DC_AREA`, `DC_SCREENSHOT_RT` e `DC_TRACE_CSV`.
3. **O que as capturas podem desbloquear**:
   - BG2 real para as 48 salas que não têm tilemap (Passo 3 do plano);
   - contexto para o `$68` (salas 9/35) e para os bosses 52/53/54;
   - confirmar o ciclo/comportamento do `$72` no cemitério (a captura injectada
     não dá o contexto da sala);
   - posições de spawn/objectos onde o extractor diverge.

## Bloqueios técnicos conhecidos (Passo 2)

- **Helpers de física por portar**: `$808B9C`, `$808BA7`, `$808C31` (movimento
  com colisão), `$80A0FF` (usado pelo `$68`), `$809CA4` (probe rectangular com
  params em WRAM `$7E:E9xx`). Sem eles, `$63` e `$68` não passam de ciclos
  aproximados — não vale a pena fingir.
- **`$63`** (ogre, 35 registos, arte de 1 pose): 3 estados, sub-tabelas em
  `$A04C`/`$9FC0`, chama os helpers acima. É o próximo inimigo "de verdade".
- **`$68`** (30 registos, salas 9/35): 2 estados, estado 0 com 7 subestados
  (`$B3AC`), precisa de `$80A0FF` e de contexto de sala para a arte.
- **Espécies que derrubam o guest ao injectar**: `$9C`, `$79`, `$73`, `$70`,
  `$30` (connection reset). Precisam de contexto/script, não de injecção nua.

## Fecho da sessão (continuação): a take do estágio II

- A take `captures/rec_stage2_trace/stage_II_ruined-city-dark-avenue` foi
  reproduzida desde o boot e mapeada — formato, comandos, armadilhas e
  resultados medidos em `docs/TAKES.md`.
- Corrigido `tools/oracle/trace_stage.py replay`: gravava o replay em JSON com
  espaços, o `sscanf` do debug server descartava todas as linhas e a corrida
  acontecia **sem input** (`samples: 0`, sem erro). Agora escreve compacto, usa
  `gframe` e falha alto quando carrega 0 amostras. `--objects` lista
  `slot:espécie@x,y`.
- Achado que muda o mapa: `$008D` é offset de bytes (área = `$008D/2`). A avenida
  do estágio II é a **área 4** (não 8); biblioteca/wise man/black lotus são
  **46/47/48**. `docs/INTERIOR_DOORS.md` corrigido; `docs/FullMaps/room_names.md`
  ainda tem os valores duplicados.
- Bloqueio seguinte: `pad_mask` em `game_check_transitions` antes de acrescentar
  as três portas up da área 4 em (424,428), (664,428) e (824,124).

## Sessão de 2026-11-04 — as três takes de estágio II

O utilizador gravou três takes em
`../DemonsCrestSNESRecomp/build-trace/captures/rec_stage2_trace/`:

| take | frames | conteúdo |
|---|---|---|
| `stage_II_ruined-city-dark-avenue` | 10 509 | boot → password → avenida, biblioteca, wise man |
| `..._dark-avenue_to_..._reservoir_to_..._pit-of-ovununu` | 25 076 | rota completa até à luta do poço (2 mortes) |
| `..._dark-avenue_to_..._reservoir_to_..._boneyard` | 23 056 | rota até Belth (Black Lotus 2×, 2 mortes) |

Tudo em `docs/TAKES.md` (formato, comandos, armadilhas, rotas, resultados).

**O que ficou assente:**

- `$008D` é offset de bytes: **área = `$008D / 2`**. Avenida = área **4**;
  biblioteca/wise man/black lotus = **46/47/48**; reservatório 5; catacumbas 6;
  catacumbas escuras 7; poço 8; cemitério 9.
- `pad_mask: 8` no room JSON é o bit de **up** do ROM (confirmado no log de
  input). O port ignora `pad_mask` — é o Passo A.
- As três portas up da avenida: (424,428)→46, (664,428)→47, (824,124)→48. A
  volta já existe com `spawn_id` 1/2; a do Black Lotus foi observada na take.
- Morrer abre `RETRY / SELECT A STAGE / END`; RETRY recarrega a mesma sala no
  spawn 0 com HP cheio; SELECT A STAGE vai ao mapa Mode 7; END mostra o ecrã
  `PASS WORD`. O port tem um `GAME_OVER` inventado — Passo B.
- O boss do poço é `$69` (fixo) + `$6B` (sobe atrás do jogador) + `$6C` (olhos
  que voam), não `$16` — Passo C.

**Commits desta sessão:**

| commit | conteúdo |
|---|---|
| `31c5348` | `trace_stage.py replay`: JSON compacto, `gframe`, erro com 0 amostras; `--objects` |
| `7339a03` | objectos da take confirmam `room_area4.json` 1:1 |
| `d233ac1` | `tools/oracle/scan_take.py` (área/HP/posição, 2 leituras por amostra) |
| `353b3f2` | rotas das duas takes + menu de continue + `pad_mask` |
| `ef7f174` | boss do poço = `$69`/`$6B`/`$6C` |
| `807f1e9` | menu de morte é o hub (mapa / password) |

**Próximo:** `docs/NEXT_STEPS.md` §1c — Passo A (`pad_mask` + portas up),
Passo B (menu de morte), Passo C (bosses). Não começar pelos bosses nem pelo
password retail.

## Passo A + B fechados (continuação de 2026-11-04)

| commit | conteúdo |
|---|---|
| `15c6c4d` | **Passo A**: `pad_mask` honrado em `game_check_transitions` (C e Python); as três portas up da avenida (4→46/47/48) entram por `apply_door_table.py` (`source: "take_door"`, 16×16, spawn 0); `tools/check_up_doors.py` na regressão. |
| `81cd09e` | **Passo B**: `GAME_CONTINUE` (12) com 90 frames de morte → RETRY / SELECT A STAGE / END; RETRY usa o restart (mesma área, spawn 0, HP cheio); END = `GAME_PASSWORD_VIEW` (13), 4×4 com o codec nativo zero-padded; `tools/check_death_menu.py` na regressão. |

- Regressão verde: `DISPLAY=:99 python3 tools/run_regression.py` → PASS.
- Hooks novos: `DC_KILL_AT`, `DC_STATE=continue`, `DC_DEMO=41` (up) e
  `DC_DEMO=42..45` (hub de morte); `DC_START_ONCE=1` limita o `DC_START_X/Y`
  à sala de boot.
- **Achado**: o antigo teste da área 2 («skeleton dies to fireballs») era um
  falso positivo — o jogador morria no frame 229 e o trace parava, o que
  parecia a morte do inimigo. Com o hub a simulação continua. O teste passou
  a provar um hit real no inimigo flutuante (ledge em x=1000); o tiro rasteiro
  continua a não acertar inimigos no chão (fireball a 18 px dos pés, caixa
  ±12 em torno da origem) — Passo 2.
- **Achado**: `$96` (actor de script/NPC) estava tipado `boss` no extractor.
  Isso punha `boss_alive` verdadeiro e **fechava todas as transições** da
  avenida (4) e dos interiores (46–49/55) sem `DC_BOSS_CLEAR`. `objects_init`
  (C e Python) passa a spawnar `$96` como NPC quando a sala não tem boss a
  sério e a ignorá-lo quando tem (controlador da arena). `check_up_doors.py`
  ganhou duas corridas sem `DC_BOSS_CLEAR` (4→46, 46→4); `check_playthrough`
  deixou de usar a área 49 como «boss» (não tem boss) e usa a 52.
- **Próximo**: Passo C (poço: `$69`/`$6B`/`$6C`; Belth `$68`).

## Passo C — poço de Ovununu, abertura (2026-11-04)

| commit | conteúdo |
|---|---|
| `abfd192` | medição do boss: papéis das três espécies, handlers, máquina do `$6B` |
| `bb258b8` | replay de WRAM: `$1DEA` em 14300, subida 700→209, tabela `$E203/$E20B` é constante |
| `dec9bad` | abertura implementada: `$69` trigger, `$6B` sobe, pool/render, `check_pit_boss.py` na regressão; porta `8→10` removida |

**O que funciona:** o `$69` liga `pool.pit_fight` quando o jogador está em
`x<128` ou `y>=568`; o `$6B` sobe de y=700 a ~209 em ~1350 frames pela curva
medida na take e faz bob 187..216; os três entram no pool (tipo unknown) e o
render desenha na posição viva; a área 8 é jogável (a porta `8→10` que estava
em cima do spawn foi removida; a única saída é `8→7`, pad 8).

**O que falta:** a AI dos 11 `$6C` (4 estados, `$83:C7B2`), o dano/HP/morte do
corpo, a arte (nenhum dos três tem sheet) e o lock da arena enquanto o boss
estiver vivo. O `check_pit_boss.py` cobre só a abertura.

**Armadilha:** a área 65 tem os mesmos 13 registos (mesma arena noutro id); o
handler do poço corre lá também. A tabela de y e os frames estão em
`docs/PIT_BOSS.md` §4.

**Próxima sessão:** medir o `$6C` na take (slots 10+, posições/flags dos 11
olhos), portar os 4 estados; depois dano/morte, arte e lock.


