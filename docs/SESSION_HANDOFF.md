# Handoff — sessões de 2026-11-03 a 2026-11-07

*Para retomar noutra sessão. Ler isto primeiro, depois `docs/NEXT_STEPS.md`.*

## Estado

- Repo: `~/Projetos/opencode/DemonsCrestPythonPort`
- `HEAD` = *Somulo: drop the stale authored rooms, guard the overlay, test the
  fight* (2026-11-17),
  **árvore limpa**. As secções das últimas sessões estão no fim do ficheiro.
- Regressão verde com **`.venv/bin/python`**:
  `DISPLAY=:99 .venv/bin/python tools/run_regression.py` → PASS (~7 min, até
  ~22 min com a máquina carregada). Xvfb em `:99`; sem ele os demos falham com
  "X11: Failed to open display". O `python3` do sistema não tem raylib.
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



## Passo C — os 11 olhos `$6C` (2026-11-04, sessão 2)

| commit | conteúdo |
|---|---|
| (este) | `$6B` espera 199 frames; `$6C` parque + enxame + olho central; checker com 3 amostras; `measure_pit_eyes.py` |

**Ferramenta nova:** `tools/oracle/measure_pit_eyes.py` — repete a take e despeja
os slots 8–25 (flags/estado/subestado/x/y) e, com `--extra`, os globais
`$1DD0..$1E08` e as tabelas `$E2C0..$E300`/`$E380..$E3E0`. A luta corre a
~15 fps no emulador: 25 000 frames levam ~14 min, a janela 14100–17350 ~8 min.

**O que ficou medido** (`docs/PIT_BOSS.md` §7): os 11 registos `$6C` são 10
satélites (`$00 = $16`) + 1 olho central (`$00 = $12`, `state 2` em
`($1DD3+1, $1DD5+$1C)`); a luta repete 5× na take e só o 1.º ciclo lança os
olhos (`sub 6` em 15791–16651, `sub 10/12/14` até 16871); o parque é x fixo
(96..166) e y = corpo + (18, 8, 32, −3, 30, 18, 22, 14, 2, 32); em `sub 4` o
desvio ao corpo cresce até 45–123 px com uma rampa de 0,5–0,85 px/frame que
segue o ciclo de `$1DEF` (0→2→4→6, ~200 frames).

**O que ficou implementado:** `$6B` só arranca 199 frames depois da flag (a
tabela de y começa em 14400, a flag em 14201) — antes subia 200 frames cedo;
os satélites parqueiam no x medido, passam a `sub 4` aos 220 frames e em `sub 4`
o y = corpo + `_PIT_EYE_TRACK` (desvio medido, passo 20 frames) — comparado com
a take o erro máximo é 2 px; o olho central é `state 2` preso ao corpo.
`check_pit_boss.py` afirma agora o parque, o desvio em t=600/1200/1500
(tolerância 4 px), o olho central e o atraso de 199 frames.

**Resolvido na mesma sessão:** as tabelas são do banco **`$81`** (o `$7E:E2D5`
era uma tabela de tiles e enganou a sessão anterior) e o `$03` de cada slot é a
flag do registo. O registo de 12 bytes em `$81:E2DF` dá (x, A, B, C, D) e
reproduz os dez parques 10/10 — `docs/PIT_BOSS.md` §7.6, que também lista as
tabelas do lançamento (`$81:E357/E360/E364/E407/E41D/E41E/E423`). O port já usa
`_PIT_EYE_ROWS`; a regra de `sub 4` com esta tabela ainda dá ~25 px de erro
(falta `$1DEE` e o integrador por fase a 1 frame), por isso o `_PIT_EYE_TRACK`
medido fica até lá.

**O que falta (por ordem):**
1. Fechar `sub 4` com as tabelas (replay a passo 1 em 14421–15791) e apagar
   `_PIT_EYE_TRACK`.
2. O lançamento (`sub 6`+, `$83:C918`): faltam `$D0BE` (anim), `$D07C`/`$D198`
   (sondas/timers), `$809CA4` (probe), `$809D8E`, `$808C95`/`$808C99`
   (integradores) e `$BC904B` (RNG). É o que faz os olhos voar e ferir.
3. Dano/HP/morte do corpo, arte (nenhum dos três tem sheet) e o lock da arena.

**Armadilha:** `tools/disasm_range.py` (repo do recomp) imprimia `ldy $E2D5` para
`LDY $E2D5,X` — o sufixo do modo de endereçamento não saía, e um lookup de
tabela lia-se como constante. Corrigido no recomp (`53a2414`). Ao ler handlers
indexados, confirmar o sufixo antes de acreditar no desvio.

**Regressão:** `DISPLAY=:99 python3 tools/run_regression.py` → PASS (EXIT=0),
com `pit boss` no resumo.


## Passo C — lançamento dos olhos `$6C` (2026-11-04, sessão 3)

**Feito:** a máquina de lançamento e o regresso estão portados em
`dcpy/object.py` — `_pit_eye_state6` (os dez `$38` de `$83:C913`), os estados
`$06=8/10/12/14` (`$CB6A/$CB7D/$CC00/$CAAE`), a cauda `$49` (`$CCBF`) e os
auxiliares `$D0BE`, `$CFDF`, `$CF6E`, `$CFBF`, `$809D8E/$809E2C`
(`$81:8149`), `$D137`, `$809CA4`, `$D198`/`$D1AE` e `$BC904B`. O `Object`
ganhou o bloco `$3D..$4F` que só estes olhos usam.

**O que a take ensinou** (tudo em `docs/PIT_BOSS.md` §7.8):
- `$1DDE` é **por flag** (`ldx $03; lda $1DDE,X`), não um contador global; o
  controlador do `$69` (`$B9F1`, `$40` 0/2/4, tabelas `$81:E015/$E075`,
  `$1DE9`, gate `$1DF8==10`) lança 2–4 por rajada, um de cada 30 frames.
  **Não está portado** — os quatro frames ficam medidos (`_PIT_EYE_LAUNCH`).
- `$D07C` compara com `$1DD1 - $1DCE - 8 - $DFCE[x] + A`; `$1DD1` satura em
  188 e `$1DCE` (scroll) não é simulado → linha medida por olho
  (`_PIT_EYE_REACH` 206/179/181/191).
- Os sorteios `$3D/$3E`, `$47/$48` e `$06` de regresso dos quatro olhos foram
  lidos do slot cru e ficam em `_PIT_EYE_DRAW` (a semente `$009C` não foi
  medida e o `$69` também consome o LCG).
- `tools/oracle/measure_pit_eyes.py` passou a despejar `px/py` (jogador) e o
  slot cru de `$50` bytes — é o que permite ler `$3D/$3E`/`$47/$48`/`$38`.

**Verificação:** antes da rampa o erro é 0,7–5,5 px nos quatro olhos. O voo
completo da take depende da posição do jogador (~(220,200)); com
`DC_HOLD_PLAYER=210,200` (hook novo em `dcpy/player.py`) os quatro sobem e
voltam: 0 `253→139→261`, 1 `207→143→221`, 7 `208→71→227`, 2 `243→81→225`.
`check_pit_boss.py` foi a `FRAMES = 4000` e afirma, por olho, `$06=6` no
lançamento, subida ≥ 40 px e descida ≥ 50 px após o pico.

**O que falta (por ordem):**
1. O controlador do `$69` (§7.8): substituir `_PIT_EYE_LAUNCH` pela regra
   `$40/$3F` + RNG.
2. Fechar `sub 4` com as tabelas e apagar `_PIT_EYE_TRACK` (replay a passo 1
   em 14421–15791).
3. Dano/HP/morte do corpo, arte (nenhum dos três tem sheet) e o lock da arena.

**Armadilha:** o trace de objectos do port (`DC_TRACE_OBJECTS`) passou a levar
`sub,phase,scale,anim` — a coluna do frame de animação chama-se `anim`; se
fosse `frame` colidia com `gframe` no `DictReader` e lia-se a animação em vez
do frame. O `$1030`/`$1033` é que são o x/y do jogador (`$1031` é só a parte
inteira; ler `$1031` dá lixo).

**Regressão:** ver o fim deste ficheiro.

## Passo C — controlador de lançamento do `$69` (2026-11-06, sessão 4)

**Feito:** `$83:B9F1` portado em `dcpy/object.py` — `_update_pit_core` (os quatro
estados do `$69`), `_pit_launch_controller`, `_pit_burst_draw` e
`_pit_start_fight`, com `$1DDE`/`$1DE9`/`$1DF8` no `ObjectPool` e as tabelas
`$81:E015`/`$81:E035`. `_PIT_EYE_LAUNCH` desapareceu.

**O que a ROM corrigiu:**
- O gatilho estava **invertido** no doc e no port: `$B989` sobe `$1DEA` quando
  `x >= $80` **ou** `y < $238` (sair do canto de entrada), não quando `x < 128`
  ou `y >= 568`. `check_pit_boss.py` ganhou 300 frames com o jogador parado no
  spawn e exige o corpo em y=700.
- `$1DDE[0..9]` começa todo a **9** (o `txa` está fora do laço em `$B951`), 1 no
  regresso (`$CB63`) e 0 no lançamento; `$1DE9--` no regresso (`$CB66`).
- `$1DF6` é o "subiu" do `$6B` (`$C18C`, uma vez); `$1DF8` conta mortos
  (`$D207: dec $1DE9; inc $1DF8`).
- O LCG `$BC904B` devolve o **low byte novo**, não o `r = (3*seed)>>8`.
- `$E035` tem 5 linhas de 16 (a primeira rajada usa `$E075`); `$BA02` termina o
  programa quando `$1DE9 == 4`.

**Medição:** o trace build do recomp **morre por volta do frame 15810** (o
debug server fecha o socket, sem mensagem; aconteceu duas vezes, com leituras
grandes e pequenas). `$009C` foi lido a 15601 (`0x9E0B`). A semente que
reproduz as libertações da take é **`0xDC27`** (busca exaustiva): flags 0/1/7 em
1583/1616/1649 e a quarta em 2450, contra 1590/1620/1650/2450 da take
(amostrada de 30 em 30). `_PIT_EYE_DRAW` fica, mas passou a consumir o LCG para
não desalinhar os sorteios seguintes.

**Verificação:** no port, luta no frame 2, corpo no topo em 1549, libertações
0/1/7 em **1585/1618/1651** e a quarta em **2452** — mas a quarta é a flag 3,
não a 2: o voo dos olhos consome o LCG em fases diferentes das do ROM. O tempo
bate, a identidade não; dívida em §7.5.6 de `docs/PIT_BOSS.md`.

**Regressão:** `DISPLAY=:99 python3 tools/run_regression.py` → PASS (EXIT=0),
com `pit boss opening/launch` no resumo.

**Próximo, por ordem:** `sub 4` exacto com as tabelas e apagar `_PIT_EYE_TRACK`;
depois dano/HP/morte (aí entram `$1DF8` e `$1DEB`), arte e lock.


## `sub 4` dos olhos: física lida, tabela mantida (2026-11-06, sessão 5)

**Tentativa:** substituir `_PIT_EYE_TRACK` pela física da banda (`$83:C84F`/
`$C864`). A física está lida e implementada numa experiência, comparada com a
take em 3014 amostras (274 frames × 11 olhos, janela 14421–15788):

- `$C8BB` acelera `$22` até C (`$E2E5`) com passo D (`$E2E7`).
- **`$C8C9` não tem `sta $22`**: faz `lda $22; sec; sbc $24; bpl rts` e só zera
  quando o resultado ficaria negativo. Nas fases 2/6 a velocidade **mantém-se
  no tecto**; o único reset é `$1DEE` mudar (`$C877`).
- `$808C99`/`$808C95` movem `y ∓= $22` (8.8) e `$C8D5`/`$C8F4` fecham a banda
  com `inc/dec $34` (1 px/frame).
- Fases medidas a passo 1: `$1DEF` repete `0→2→4→6→0` (~155 frames) e `$1DEE`
  vira 4 no frame de luta 1552. Declives: fase 0 −0,184 px/frame, 4/6 −0,816,
  fase 2 ora −0,184 ora −0,092 **com o mesmo `$22` e a mesma fase**.

**Resultado:** os dois primeiros ciclos ficam a ≤1 px, mas o erro cresce até
−61 px (flag 3, take 15656–15680). A experiência foi **revertida** — o port
continua com `_PIT_EYE_TRACK` (2 px de erro). Detalhe em `docs/PIT_BOSS.md`
§7.10.

**Armadilha nova:** o `run_to_frame` do debug server do recomp anda ~2 frames
por leitura (os valores repetem-se aos pares e o índice aparece desfasado +1),
por isso um dump "a passo 1" não serve para decidir cadências. Confirmar com
dois `frame` seguidos antes de acreditar num delta de 1 frame.

**O que fecharia o `sub 4`:** saber quantas vezes por frame o pool de objectos
corre (2 bancos? actualização alternada?) ou portar a máquina de estágios do
`$6B` (`$C051/$C073/$C0B0/$C0DF/$C145/$C15D`), que dá `$1DEF` de graça.

**Regressão:** `check_pit_boss.py` → PASS com a árvore revertida.


## HP/dano dos bosses a partir do `boss_hp.txt` (2026-11-06, sessão 6)

**Fonte nova:** `docs/boss_hp.txt` (fornecida pelo utilizador) — HP de todos os
bosses e dano de cada transformação do Firebrand. Ovununu: **10 no corpo, 3 por
olho**; Fire/Buster/Claw/Tidal 1, Demon Fire 3, Earth (chão) 2, Earth (ar) 1,
Aerial 2, Legendary/Ultimate 5.

**Feito (`4725a54`):** o `$6B` nasce com 10 e cada `$6C` com 3 (antes `hp = 1`);
ambos entram no caminho dos projéteis (`objects_check_projectiles` ganhou o
parâmetro `player`, caixas 24×30 e 8×8, flash 8); o dano vem de
`_pit_damage(player)` (Ultimate 5, resto 1 — as outras formas não estão
modeladas). Olho morto faz `pit_dead++` (`$1DF8`); corpo morto fecha a luta como
`$1DEB=2` (`pit_fight` off, `pit_opened=2`, `boss_defeated`).
`tools/check_pit_damage.py` está na regressão: 10 tiros matam o corpo, 3 o olho,
um tiro de 5 mata um olho.

**Takes novas do utilizador:**
- `~/Projetos/opencode/build-trace/captures/rec_stage3_trace/rec_20261107_045055`
  (28 299 frames): áreas 10 → 12 → 14 → **50** (boss, 19 301) → 16 (23 001) →
  **50** (23 701). Duas lutas; depois da primeira morte a floresta deixa de
  arder (estado de mundo por portar).
- `.../rec_stage4_trace/rec_20261107_050932` (34 087 frames): **o boss é o
  Arma 2** (dito pelo utilizador). Primeiro encontro tem diálogo, o segundo não
  — é uma flag de "intro vista".

**Falta:** tabela **área → HP** a partir do `boss_hp.txt` (hoje `_spawn_boss` dá
8 a qualquer boss que não seja `$33`/`$86`; Arma 1 = 16, Arma 2 = 32, Belth 32,
Hippogriff 16/24/64, Grewon 64, Phalanx 50/127/128); flag de diálogo do Arma 2;
animação de morte do corpo do Ovununu (`$05=2`, `$1E05`/`$E29A`, 12 passos).

**Armadilha de ambiente:** correr a regressão com **`.venv/bin/python`**;
`python3` do sistema não tem raylib (`ModuleNotFoundError: No module named
'raylib'`) e a regressão falha antes dos demos.

**Regressão:** `DISPLAY=:99 .venv/bin/python tools/run_regression.py` → PASS
(EXIT=0), resumo com `pit boss opening/launch + damage`.


## HP dos bosses por tabela (2026-11-07, sessão 7)

**Feito:** `dcpy/bosses.py` + `tools/check_boss_hp.py`. O `_spawn_boss` deixou
de usar `6/8/10` e lê `boss_hp(species, flags)`; a segunda forma do Phalanx
nasce com **127** (era 10). Valores de `docs/boss_hp.txt`:

| species | flags | boss | HP |
|---|---|---|---|
| `$A5` | 0/2/4 | Arma 1/2/3 | 16/32/72 |
| `$09` | 0/2/4 | Hippogriff 1/2/3 | 16/24/64 |
| `$7B`/`$7C` | 0 | Scula (Toss/Roll) | 24/10 |
| `$6F` | 0 | Holothurion | 72 |
| `$16` | 0 | Ovununu | 10 |
| `$82` | 0 | Crawler | 36 |
| `$58` | 0 | Flame Lord | 26 |
| `$86`/`$8D` | 0 | Phalanx / 2.ª forma | 50/127 |
| `$BC` | 0 | Dark Demon | 200 |
| `$33` | — | Somulo | 6 (3+3 do guião) |
| `$13` | — | Grewon | 64 |
| `$68` | — | Belth | 32 |

`docs/BOSS_HP.md` tem o mapa completo, as fontes e o que continua fora da
tabela (Flier 1/2, Phalanx 3, forma voadora do Flame Lord).

**Dano por forma (mesma sessão):** `dcpy/bosses.py` ganhou `BOSS_DAMAGE` /
`SPECIES_DAMAGE` — as dez colunas de cada luta — e
`boss_damage(species, flags, form, grounded)`.  Mapa: base = Fire, Earth =
Earth (chão 2 / ar 1), Air = Aerial, Water = Tidal, Time = Legendary, Ultimate
= Ultimate; `N/A` = 0 (imune); células "2/1" (Dark Demon) indexadas por
`phase` (hoje 0).  `_pit_damage` lê a linha do Ovununu (`$16`) e o ramo
`OBJECT_BOSS` usa a linha do boss: Hippogriff Aerial 4, Grewon
Legendary/Ultimate 10, Belth Earth 3, Holothurion imune a Fire.  Somulo (sem
linha, guião) mantém o dano do projétil.  `check_boss_hp.py` ganhou o passe do
dano (17 linhas x 10 colunas) e 11 casos forma→coluna; `check_pit_damage.py`
ganhou 4 casos no ramo genérico (Arma Ultimate/Earth, Crawler N/A, Somulo).

**Checker (na regressão):** quatro passes — o documento contra a tabela (HP e
as dez colunas de dano), os onze casos forma→coluna, todas as salas com boss
contra a tabela, e o boot de cada sala a ler a coluna `hp` do
`DC_TRACE_OBJECTS` (16 salas; 18 verificações com a fase 2 do Phalanx). Uma
espécie nova que caia no fallback 8 falha alto.

**Diálogo de intro do Arma 2 (mesma sessão):** `game.story_flags` (um bit por
área, gravado em `dc_save.json` como `story_flags`) e `BOSS_INTRO_TEXT` /
`game_maybe_start_boss_intro` em `dcpy/game.py`: a área 23 mostra o bloco do
Arma (`BE:F162`, 7 páginas) na primeira entrada e volta a `GAME_PLAYING`.
Hooks: `DC_STORY_FLAGS`, `DC_INTRO_FORCE`, `DC_NO_STORY`.
`tools/check_arma2_intro.py` cobre os quatro casos (novo, bit posto,
`DC_NO_STORY`, save+retoma) e está na regressão.  **Três bugs de texto
encontrados:** `TEXT_MAX_STRINGS` era 512 e o ROM tem 518 blocos (o do Arma
nunca carregava — `text_find` dava -1); `TEXT_MAX_PAGES` era 6 e a 7.ª página
do Arma caía; o `extract_text.py` colava o `RTL` (0x6B = `k`) ao texto, por isso
a primeira linha lia `kI'VE WATCHED YOUR`.  Ver `docs/BOSS_INTROS.md`.

**Achado (ROM):** a tabela de estados do `$6B` (`$83:BFF3`) é indexada pelo
**valor** de `$05` (0/2/4), não por `$05*2`; o estado de morte é `$05=4`, não
`$05=2` como dizia a §7.11. A animação (`$83:C1C2`) são **12 passos de 3
frames** com a tabela `$81:E29A` (`0E 00` ×6) e `$26`/`$27`/`$1E05`; `$C198`
só troca para `$05=4` quando `$1DEB=2`. O `$C504` que mata aos 6 (`$36`) é
**outra espécie** (stub próprio em `$82:F846`; o do `$6B` é `$82:FA9E`), por
isso não contradiz os 10 HP. Falta a rotina de dano partilhada que arma
`$26`/`$1E05`; detalhe em `docs/PIT_BOSS.md` §7.13. **Não portar a animação
antes disso.**

**Próximo:** a morte do corpo do Ovununu (falta a rotina de dano partilhada que
arma `$26`/`$1E05`), `sub 4` exacto, a arte do poço e o lock da arena.  O
diálogo de intro do Arma 2 está feito — ver `docs/BOSS_INTROS.md`.

**Regressão:** `DISPLAY=:99 .venv/bin/python tools/run_regression.py` → PASS
(EXIT=0), resumo com `boss hp/damage (boss_hp.txt)` e `arma2 intro flag`.

## Editor: Coverage, Dialogue e Checks (2026-11-08)

**Contexto:** sessão dedicada a `tools/editor/`, sem mudar o jogo — excepto a
correcção de texto abaixo, que a própria ferramenta encontrou.

**Vistas novas**

- **Coverage** (`/api/coverage`): todos os registos de objecto agrupados por
  espécie, com contagem de salas, arte, sheet, HP autorado e validação por
  sala. Filtros `placeholders`/`sem arte`/`boss`/`editado`; clicar numa espécie
  abre o Enemy Editor, numa sala abre o Map Builder; `Copy report` exporta
  markdown. Lê as salas efectivas (overlay incluído), por isso dá **852**
  objectos contra os **853** registos do ROM do `report_coverage.py`.
- **Dialogue** (`/api/text`): os 518 blocos, a simulação exacta do loader
  (8 páginas × 8 linhas, `j`, 47 chars, `[`→`'`, `\`→`.`), pré-visualização
  com a fonte 8×8 real, avisos do que o loader descarta, e um separador
  `Usages` que resolve com `ast` todas as needles `text_find` de
  `dcpy/game.py` e `BOSS_INTRO_TEXT`. Edição de páginas grava
  `assets/authored/text_strings.json` (só ASCII 0x20–0x7E); `dcpy/text.py`
  aplica esse overlay bloco a bloco.
- **Checks** (`/api/checks`, `/api/checks/run`): lista `tools/check_*.py` +
  `run_regression.py`, corre um de cada vez no venv, devolve stdout/stderr,
  código de saída e duração; usa `$DISPLAY` ou Xvfb `:99` se existir. Timeout
  180 s por omissão (máx. 900).

**Bug real encontrado e corrigido:** três needles do town story atravessavam
quebras de linha do ROM e `text_find` devolvia -1 em silêncio:
`"BURNT THE DEMON REALM"`, `"ARROGANT FOOL"` e
`"ESCAPED FROM THE COLOSSEUM"`. Passaram a `"NEARLY BURNT"`,
`"THANKS TO THAT ARROGANT"` e `"ESCAPED FROM THE"` (blocos 97/99/100). As 22
needles do jogo resolvem agora; há um teste que falha se alguma voltar a não
resolver.

**Verificação:** `tools/editor/test_editor.py` → 26 testes verdes (inclui o
overlay de texto lido por `dcpy.text`, recusa de caracteres fora da fonte,
coverage e o check runner); self-test do browser → 25/25
(`captures/editor_selftest.json`); regressão completa verde. O servidor deixou
de cachear `/web/` (módulos edited in place).

**Ficheiros:** `tools/editor/{editor_data,server}.py`, `README.md`,
`web/js/{coverage,dialogue,checks}.js`, `web/test.html`, `dcpy/text.py`.

## Cemitério: BG1 53 px e objectos restaurados (2026-11-08)

- **BG1 da área 1 estava 53 px acima** do sítio: todas as estátuas do mapa
  original aparecem 53 px mais abaixo. O renderizador ignorava `scroll_y` no
  BG1 de propósito (a área 4 usa-o como offset de câmara), por isso a correção
  passou a ser um campo separado **`offset_y: 53`** em `bg[1]`, aplicado em
  `dcpy/render.py`, no `layerOrigin`/`tileOrigin` do Map Builder e no
  `renderGameView`. `BgLayer` ganhou o slot e a leitura do campo — sem isso o
  render rebentava com `AttributeError`.
- A room authored tinha só **9 objectos**: faltavam os **13 decor `$72`**
  (tochas) e o `$09` em (1920,168) estava como `exit`. Restaurada a lista de
  **22 objectos** da generated (boss `$09` incluído), mantendo a colisão
  authored editada.
- **Verificação:** `check_flame` PASS (13/13 decor), `check_hippogriff` PASS
  (spawn, 260 frames de pedra, gate para a área 2), `check_objects` PASS,
  `test_editor` 27/27, self-test do browser 26/26. `check_boss_hp` passou a
  falhar só a área 0 (`$33` flags 0x80), que é outro problema.
- **Regressão completa continua vermelha** por falhas não relacionadas:
  WAVs ausentes no manifest (`music_town`, `music_murkland`, ...), up doors
  4→46/47/48, Somulo/MVP, `check_transition_fade` (`fade.csv` em falta no
  scratch) e boss HP da área 0.

## Campaign Graph View (2026-11-08)

- A aba **Campaign** (`campaign.js`) já estava no commit `845eade`; esta sessão
  corrigiu o que faltava para ser usável: o canvas ficava em 300×150 porque
  o `resize` só corria num `requestAnimationFrame`, não havia fit/foco e a
  ordem dos estágios era alfabética.
- Agora: `ResizeObserver`, fit à campanha, foco no room selecionado, faixas de
  estágio na ordem de campanha, texto/arestas de porta escondidos no overview,
  duplo-clique abre o Map Builder, portas duplicadas colapsadas e hint de
  navegação.
- `GET /api/campaign` já existia em `server.py`; o processo em execução é que
  era antigo. Reiniciar o editor depois de mexer no backend.
- **Verificação:** payload 113 rooms · 225 edges · 11 stages; `test_editor`
  29/29; self-test do browser 27/27 (`campaign graph view`, `eight editor
  views`).

## Editor polish: help, heatmap e validação de portas (2026-11-08)

- `?` (ou o botão de info na toolbar) abre o **shortcut sheet** com 15
  atalhos; qualquer modal bloqueia o teclado do mapa e Esc fecha.
- O **minimap** ganhou heatmap de objectos (boss/inimigo/urn/item/NPC/decor)
  e as portas aparecem como quadrados verdes.
- O inspector de uma porta consulta a room de destino e mostra
  `✓`/`⚠`/`✗` para `next_area` + `spawn_id`, com cache por área.
- **Verificação:** self-test do browser **30/30** (`keyboard shortcuts help`,
  `transition target validation`, `minimap heatmap`); `test_editor` 29/29.
- **Busca global:** campo no topo (`GET /api/search?q=`) filtra os 113 rooms
  por área/type/species/flags/coordenadas; o clique abre `#map/<area>` e
  selecciona o objecto via `app.pendingObject`. Verificação: 30/30 backend,
  31/31 self-test.

## Bad ending: a câmara do Phalanx e o gatilho (2026-11-10)

**Take nova:** `rec_bad_ending/rec_20261110_080831` (40 054 frames, só input).
Medida em `docs/TAKES.md` §7: `$008D = 84` → **área 42**
(`phalanxs-fortress-phalanxs-chamber`), do frame 3721 ao fim; morte + RETRY em
7761–8200; **a take não tem o ending** — o subscreen está aberto de 10 805 a
39 820 e a gravação acaba lá. O que ela prova é a sala, a intro e o corpo.

| commit | conteúdo |
|---|---|
| `9e82d00` | `tools/oracle/replay_frames.py` (replay + `screenshot` por janela; o dump `SNESRECOMP_FRAME_BMP_DIR` não dispara neste título) e `docs/TAKES.md` §7 |
| `7395771` | §7.1: a intro do Phalanx toca ao entrar na câmara (`AH... YOU'VE ARRIVED...`), corpo em cima do monte de crânios à direita |

**Feito nesta sessão:**

- `tools/dc_extract/extract.py`: `0x86: "boss"` no `SPECIES_KIND_MAP` — os
  registos do ROM das áreas 42 e 75 deixam de ser placeholders.
- `tools/dc_extract/apply_boss_table.py`: um registo da espécie esperada que
  ainda não está tipado boss é **retypado no lugar** (posição e `source` do ROM),
  em vez de ficar um duplicado ao lado.
- `tools/check_bosses.py`: `BOSSES[84]` → **`BOSSES[42]`** em (256,136) e o caso
  runtime `_phase2` mudou para 42. A 84 é "BOSS STAGE 04" e não tem registo de
  Phalanx no ROM — era a duplicação `42×2`. A sala 84 ficou com o `$86`
  retypado `unknown` (assets locais).
- `dcpy/object.py`: `pool.boss_killed_species` (a morte genérica de boss grava a
  espécie; o gatilho precisa de distinguir `$8D` de `$86`, que só muda de fase).
- `dcpy/game.py`: regra de ending por **Crest of Time + talismãs** (ver
  `docs/ENDINGS.md`), gatilho `PHALANX_BOSS_AREAS = (42, 75)` na morte do `$8D`,
  intro da área 42 (`"MUCH EARLIER THAN I"`) e o hook `DC_BOSS_KILL_AT=<frames>`.
- `tools/check_bad_ending.py` (na regressão): regras das cinco combinações,
  cadeia `$86` (25 tiros de Fire) → `$8D` (127 HP) → `boss_defeated`, e três
  corridas no binário: intro abre, `$8D` morto entra em `GAME_ENDING`, e um boss
  noutra área continua a fazer *area clear*.
- **Medição da AI** (`tools/oracle/measure_phalanx.py` + `docs/PHALANX_AI.md`):
  o corpo `$86` está em (256,136) no frame 3820, salta para (480,136) e fica
  ~1200 frames, depois patrulha a y≈172 com varrimentos de 100–200 px; o `$88`
  é um enxame de **17 slots** que nascem em 4940–4950 (7 ficam até ao fim). O
  handler é `BE:C6A0`, com duas tabelas de 6 estados (flags != 2 → `$C692`,
  flags == 2 → `$C6CC`). A AI do port continua a inventada.

**Verificação:** `check_bad_ending` → PASS; `check_bosses --runtime` → PASS
(12 salas, 13 corridas); `check_boss_hp` → só o erro antigo da área 0
(`$33` flags 0x80). `DC_AREA=42` desenha o Phalanx em (255,136) — screenshot
clareado mostra o corpo no monte de crânios, sem placeholder magenta.

**Cenografia do ending (take `captures/badend`, mesma sessão):** a gravação
nova traz os frames e mostra a apresentação toda — 5 páginas de narração
(4 430–7 420) sobre o voo no reino demoníaco, depois o epílogo sobre o retrato
do Firebrand nas chamas com o bloco `$81:8DF2` (8 240–13 900). Implementado:
`bake_ending_capture.py` coze `ending_bad_flight.png` / `ending_bad_portrait.png`
+ `endings_timing.json`; `endings.json` passa a ter `pages` e `page_frames` com as
quebras de linha do jogo (610/430/450/600/490 + 120 de fade); `_game_ending_step`
corre por relógio (sem prompt de botão, como a take mostra) e `_draw_ending`
desenha os dois fundos e as páginas. Ver `docs/ENDINGS.md` §4.

**Falta:** as três falas de morte do Phalanx (`~0x1F3900`) antes do ending; o
texto que a take mostra **depois** do bloco `$81:8DF2` ("MANY NOW ASK IF LIVING
/ UNDER THE RULE OF PHALANX") não está na tabela extraída; o `$88` da câmara
continua `unknown` e a área 75 (o outro par `$86`/`$88`) não foi visitada.

**Correcção de texto (`e277904`):** o extractor apagava **todos** os `]`; na
take o `]` é o reticências dentro da linha ("`AH]]] YOU'VE ARRIVED" lê-se
"AH... YOU'VE ARRIVED"). Passa a manter os interiores, remover só a cauda no
fim da página e o 0x60 inicial; `dcpy/text.py` mapeia `]` → ".". 65 dos 518
blocos mudam; `check_arma2_intro` e `test_editor` (30/30) verdes.


## O fim da luta do Ovununu: o corpo não tem HP (2026-11-17, sessão 8)

**ROM (`docs/PIT_BOSS.md` §7.14):** o handler do `$6B` nunca lê `$1DDE` (a
flag de hurt partilhada) — o corpo **não é um alvo de dano**. O fecho da luta
é o guião do `$69`: `$1DF8 == 10` (os dez satélites mortos) em `$BA4E` põe
`$1DEB=1`; o subestado 4 termina com `$1DEB=2` (`$BCDE`); o hover do corpo
lê o 2 e passa a `$05=4`, onde corre a saída — 12 passos de 3 frames da tabela
`$81:E29A` (`0E 00` ×6, um piscar) e no fim desaparece.

**Port:** o corpo nasce sem HP e as balas passam por ele; só os satélites
`$6C` (flags 0..9) levam dano — 3 HP, `_pit_damage` por forma — e o olho
central (flag 10) também não conta. Dez satélites mortos → o corpo passa ao
estado 4, pisca 36 frames (`PIT_LEAVE_STEPS`/`PIT_LEAVE_FRAMES`; o render
esconde a caixa nos passos com valor 0) e sai com o olho central; `pit_fight`
fecha com `pit_opened=2` (`$1DEB=2`), `boss_defeated` e o evento. O
"10 (main body)" do `boss_hp.txt` fica para o Ovununu `$16` da área 54 (já
está na tabela `dcpy/bosses.py`).

**Checker:** `check_pit_damage.py` reescrito — corpo sem dano, satélite a 3
tiros, central fora da contagem, o ramo `$BA4E` a abrir `pit_opened=1`, a
saída de 36 frames, a luta fechada e o dano por forma 1/2/1/2/1/5/5.
`check_pit_boss.py` (abertura/lançamento) continua PASS sem alterações.

**Correcção que veio daqui:** o `check_boss_hp` falhava no "erro antigo da
área 0" — o jogo carrega `assets/authored/rooms` primeiro
(`_load_room_with_override`) e o room autoral da área 0 tem o Somulo com
flags 0, não 128 como o gerado. O `boss_records` do checker passa a seguir a
mesma precedência; **17 salas, 19 corridas, 0 erros**.

**Notas:** o comprimento do guião entre `$1DEB=1` e `=2` não está medido (a
take não tem kill) — o port arranca a saída no décimo olho morto; quem arma o
`$26` na ROM fica por identificar, mas já não bloqueia nada.

**Próximo:** `sub 4` exacto, a arte do poço e o lock da arena; depois Belth
`$68`.


## Somulo: diagnóstico da regressão vermelha + plano (2026-11-17)

A batalha em si está correcta (com rooms gerados: hp 6→0, faint, 3 hp de
volta, colapso, gate → 34). A causa dos falhanços é o **overlay de rooms
autorais** (`assets/authored/rooms/`, commit `8ec5e85`): o
`room_area0.json` autoral põe o Somulo em (138,124) — em cima do spawn — com
flags 0, apaga a porta pós-boss do door_table e duplica 4× uma porta
"notes_repointed"; o `room_area4.json` repõe o boss fantasma e parte as
up-doors. Prova: `DC_AUTHORED_ROOMS` vazio → up doors PASS e o demo 14 dá
hp [6..0] + área 34. `check_mvp_somulo.py` não apanha porque nunca dispara
um tiro.

**Plano em `docs/SOMULO_ROOM_FIX.md`:** 1) rebase dos rooms autorais 0/4
sobre o gerado (ou apagá-los); 2) `check_authored_rooms.py` que compara
autoral vs gerado nos campos críticos do motor, na regressão; 3) o
`check_mvp_somulo.py` ganha um passe que mata o boss e atravessa a porta;
4) áudio à parte (cozer os WAVs por nível com `make_music_asset.py`, exige
oracle). O áudio é a única peça que não é do Somulo.


## Somulo: arrumado (2026-11-17, execução do plano)

**1 — rooms autorais 0/4 apagados** (`git rm`): eram cópias velhas com o
Somulo em cima do spawn e a porta pós-boss substituída; o overlay da área 1
(cemetery BG1 fix) fica. `check_up_doors` PASS, `test_editor` 30/30,
`check_boss_hp` 0 erros, `check_mvp_somulo` agora planta o boss em y=193 (o
pé do (380,170) do gerado).

**2 — `tools/check_authored_rooms.py`** (novo, na regressão): cada room
autoral é comparado com o gerado em bosses/transições/spawn/gate/arena;
diferença sem whitelist = falha. Teste negativo com o room_area0 mau do git:
falha em `bosses`, `transitions`, `gate_next_area`.

**3 — `check_mvp_somulo.py`** ganhou o combate: dois passes com o guião do
demo 14 (matar `6→0` + gate → 34; e `DC_BOSS_HP=1` com o faint
`(1,0)→(0,6)`, volta `(3,0)`, colapso `(0,5)`). O buraco que deixava o
overlay passar está fechado.

**4 — áudio continua pendente** (WAVs por nível; exige oracle). É a única
falha esperada da regressão completa depois disto.

Ver docs/SOMULO_ROOM_FIX.md (diagnóstico + plano + execução).


## Guia de desenvolvimento (2026-11-17)

**`docs/GAME_GUIDE.md`** — o guia geral pedido pelo utilizador: ambiente e
armadilhas (.venv, Xvfb, pyc), env vars, o jogador e as seis formas, como
adicionar espécie (registo → arte → atributos → comportamento → checker),
onde vivem HP/dano, física (8.8 + API do level.py), rooms e o overlay autoral
com a guarda, cenas scriptadas (diálogo, story_flags, hub de morte,
endings, demos), áudio e a cultura de verificação. Todos os números e nomes
de função foram conferidos contra o código antes de escrever (constantes do
player, fases da intro 150/70/280/110, hitboxes 40×46/20×24/8×8, manifest
em `assets/generated/audio/`, `game_update_continue`, condições dos
endings por `docs/ENDINGS.md`).


## Auditoria do NEXT_STEPS (2026-11-18)

Re-auditado com medição (`report_coverage.py` re-corrido). Corrigido no
`docs/NEXT_STEPS.md`: comando da regressão apontava `python3` (sem raylib —
armadilha conhecida) e dizia "a regressão passa" quando o estado real é
verde-excepto-áudio; números de cobertura desactualizados (handlers 17/80 →
20/80, placeholders 591 → 552, sheets 28 → 31); item da morte duplicado e
desactualizado na secção 3 (feito desde o Passo B); hash de HEAD fixo no texto.
Acrescentado: **Passo 6b — regressão sem render** (medição cProfile:
EndDrawing 49%, game_render 44%, simulação 1.3%; `DC_NO_RENDER` + checker de
paridade de traces; regressão ~20 min → ~2–3 min), estado concreto do áudio
(faixas por nível + pipeline `tools/audio/make_music_asset.py`) e duas regras
de trabalho (guarda dos rooms autorais; conferir branch antes de commitar).


## Passo 6b feito: regressão sem render (2026-11-18)

**`DC_NO_RENDER=1`** em `dcpy/main.py`: em corridas determinísticas salta
`game_render`+`BeginDrawing/EndDrawing` a menos que haja `DC_SCREENSHOT*`
(a captura precisa do frame desenhado — o `check_no_render.py` prova que o
PNG sai na mesma). Novo **`tools/check_no_render.py`** na regressão:
mesmo demo com e sem render → traces **byte-idênticos**; screenshot
funciona; o modo não pode ser no-op. A regressão exporta `DC_NO_RENDER=1`
para todos os filhos; `check_objects`/`check_flame` (que verificam o
**desenho** via `DC_TRACE_PLACEHOLDERS`) fazem `env.pop` — foram os dois
únicos vermelhos da primeira corrida e estão verdes de novo.

Medido: 600 frames 24.7 s → 0.9 s (27×); **regressão completa ~20 min →
4m09s**, mesma lista (só áudio vermelho). Regra nova: um checker que leia
contadores do renderer (`placeholders_drawn`, `decor_drawn`) tem de fazer
`env.pop("DC_NO_RENDER")` — traces não são afectados, o desenho é.

Fica pendente no 6b: cache das bandas do BG (`RenderTexture2D`) para o fps
na janela — não é preciso já.


## Belth ($68): a máquina lida e medida (2026-11-18)

**`docs/BELTH_68.md`** — a espécie do Passo 2/4 estava como placeholder
magenta; agora tem a análise completa no molde do `ARMA_AI.md`:

- **ROM**: despacho por tabelas **byte-indexadas** (`$06` é offset — a lição
  do doc; ler como índice 0..6 cai fora da janela LoROM); 2 estados × 7
  subestados; o estado 1 é o controlador (teleporta com random+colisão,
  broadcast `$4C`), o 0 são as peças (homing ±3px com deadzone 4, tabela de
  fases `$DF89/$DF8E`, sons por fase). Bases `$DF9C/$DF9F/$DFB3` sob
  suspeita (leem-se como código) — confirmar com estados vivos.
- **Medição**: a take §6.2 (`…_to_ruined-city-boneyard` — cuidado: dentro de
  `rec_stage2_trace` há DUAS takes; a outra, só-avenida, nunca chega à área
  9) dá o ciclo: 3–10 peças, **as 21 posições dos registos são as âncoras**
  — todas observadas exactas. A **`rec_level_2` do utilizador** (com o kill)
  fecha o fim: 3–12 peças, **a morte do boss apaga tudo de uma vez**
  (g11841→g11861), o jogador sai pelo mapa ao g14681.
- **Falta para o port**: `$05/$06` no blob do `trace_stage.py` (2 bytes) e
  repetir o replay; helpers por ler (`$B88D/$B87C/$B727/$B73E/$B71A/$B412/
  $B7C8`, JSL `$80A0FF/$809E7F/$80BD51/$80F83D`); arte (captura na sala
  real); depois o handler em `object.py` + `check_belth.py`.
- `rec_level_v` do utilizador também foi digitalizada: áreas 24→27
  (Poseidonia) — sem Belth, fica registada como cobertura.


## Belth portado e verificado (2026-11-18, sessão autónoma)

O ciclo completo da primeira espécie do Passo 2: ROM → medição → port →
checker.

- **`trace_stage.py`** ganhou `#$05.$06.$3B` por slot no blob (aditivo —
  o prefixo `slot:sp@x,y` mantém-se). Estados vivos confirmaram a
  indexação por byte TAMBÉM nos estados: `$05 ∈ {0,2}` (nunca 1 — a
  leitura estática inicial dizia "estado 1"); o controlador nasce
  `(sub 0, fase 0)` → `(2, 6)` numa amostra e vive lá a luta inteira;
  os seus teleportes são re-spawns (7 slots).
- **Descoberta de mecânica**: `$B7FD/$B83F` escrevem em `$1031/$1034` — a
  **task do jogador**. O Belth ARRASTA o jogador a ±3px/frame (deadzone
  4): 7 janelas de arrasto medidas na take do kill. `$80A0FF(Y)` lê
  registos `[dx][dy]` relativos ao chamador em `$83:Y` (Y é ponteiro,
  não índice — mais uma leitura corrigida); `$809E7F` sincroniza o bit de
  espelho com o facing.
- **Port**: `_belth_update`/`_spawn_belth_piece`/`_spawn_belth_controller`
  em `dcpy/object.py` — peças ancoradas com walker e stagger, controlador
  que salta entre âncoras (~400f) e arrasta, kill no ramo genérico com
  **wipe simultâneo das peças**. Desvios documentados no §6 do doc.
- **`tools/check_belth.py`** (na regressão): âncoras, hp 32, saltos,
  arrasto de jogador parado, churn 3–10, kill de um tiro esvazia a sala.
- Regressão completa: ver email/resultado do run em curso; esperado
  verde-excepto-áudio.

Fica por fazer no Belth: arte (captura na sala real), os probes
`$80A0FF` finos, os sons de fase e as tabelas sob suspeita
(`$DF9C/$DF9F/$DFB3`).


## Ogre ($63) portado; $B0 diagnosticado e adiado (2026-11-18, autónomo)

- **`$63`** (`docs/OGRE_63.md`): máquina lida (`$83:9FAA`, estados
  byte-indexados {0,2,4}, sub-tabela `$A04C`, física `$808B9C` +
  colisão `$808C31`) e medida na take do estágio III (blob de estados:
  subestados {0,2,4,6}, fases 2→4→6; ciclo idle→armado 40f→arco 40f com
  apex 35px e ~200px→dwell 300f; **peça `$91` nasce no descolar** — o
  `lda #$91` + `$82877B` do ramo das flags). Port em
  `dcpy/object.py::_ogre_update` com constantes medidas; inimigo real
  (folha de 1 pose), sempre-atingível ao lado do ghoul; peça `$91`
  placeholder com vida de 300f. `check_ogre.py` na regressão: 7
  registos, ciclos, viagem ≥100px, peças nascem e expiram. Pendente: a
  máquina da `$91`, o acerto-no-chão (§3 do NEXT_STEPS), o estado 4
  (`$A116`) fino, áreas 6/13/33 sem take.
- **`$B0`**: NÃO portado de propósito — despacha nas flags (`$03 ×2 →
  ($CADC,X)`, 18 variantes) nas áreas 91–112, **sem take nenhuma**.
  Fica registado no NEXT_STEPS como "precisa de gravação dessas salas".
- Regressão: esperado verde-excepto-áudio com o novo checker (a corrida
  final está no histórico desta sessão).


## Convenção do acerto: estado da caçada (2026-11-18)

Item §3 do NEXT_STEPS (o fireball nasce a `player.y-18` e a caixa do
inimigo é ±12 — tiro no chão não alcança inimigo no chão):

- `$809CA4` **não é** o teste de acerto — é o probe de solidez
  (candidato = posição própria + registo `[dx][dy]`, amostra a colisão
  do nível via `$9C2C`; é o que o ogre usa para aterragens). O teste
  projéctil↔inimigo está noutro handler por identificar.
- Os offsets do port (`PLAYER_FIREBALL_X_OFFSET=10`, `Y_OFFSET=18`)
  vêm do projectile.c sem âncora de ROM anotada.
- **Nenhum ogre morre na janela medida** da take do estágio III (os
  `$57` são urnas) — não há geometria de impacto medida. Faltam: (a)
  achar o handler do fireball na ROM (a espécie/estado dele no censo)
  e ler o teste, ou (b) uma take onde o jogador acerte num inimimo
  parado no chão (basta um esqueleto da área 2 ou um ogre) para medir
  a distância tiro↔alvo no frame do hit.


## rec_map_areas (2026-11-19): 91–112 são inacessíveis; $16/área-54 reconciliado

A take do tour pelo mapa do utilizador (`rec_map_areas`,
`rec_20261119_112516`, 8,8k frames) cobre **0, 80, 82, 94, 52, 49, 55,
54** — as 52/49/55/54 novas. Conclusões:

- **As salas 91–112 não se visitam a andar**: são ecrãs de sistema
  (256×N, **zero portas**, só o `$B0`, sem nome no `room_names.json`).
  Nenhum tour as alcança; o `$B0` só se mede quando a ROM disser
  **quando** é que esses ecrãs carregam (leitura, não gravação — a
  nota está no NEXT_STEPS).
- **`$16`/área 54 e `$6F`/área 52 nunca entram no pool** nos ecrãs de
  arena: são registos dormentes das pré-visualizações do mapa. A
  reconciliação "a `$16` da área 54 é outra entrada" está FECHADA
  (nota nova no TAKES.md §6.1); o "Ovununu" do boss_hp.txt é o lodo do
  poço, não a 54.
- **`$9B` vive**: nos ecrãs de arena as peças "inertes" têm
  estado/subestado a mexer — invisíveis (init sem metasprite) mas com
  script interno. O port não as spawna lá (nada se desenha) — quando o
  papel delas for lido, entra como script invisível.
- Os ecrãs de arena põem **objectos dinâmicos** no pool: `$94`/`$40`
  na 54, `$97`/`$66` na 49/52 — os sprites das pré-visualizações;
  catálogo para quando as pré-visualizações forem portadas (Passo 5).


## rec_kill_enemies (2026-11-19): a galeria dos boss + a geometria dos tiros

A take do utilizador (`rec_kill_enemies`, `rec_20261119_120455`, 15k
frames, "todos os tipos de tiros") cobre **0, 80, 84, 107, 85, 108, 86,
87, 83, 82**:

- **Correcção (a segunda) da nota das salas 91–112**: NÃO são ecrãs de
  sistema inacessíveis — **107/108 são os corredores entre as salas de
  boss** (84→107→85→108→86→107→87). As salas do `$B0` devem ser ramos
  dessa galeria; uma take a percorrer esses ramos destrava a medição.
  A nota "só por leitura da ROM" do commit anterior estava errada.
- O replay fino (passo 4) com o blob de estados está em curso para
  extrair a **geometria dos impactos** (posição do tiro vs do inimigo
  no frame da morte) — a convenção do acerto do §3 do NEXT_STEPS, com
  todos os elementos de tiro do jogador.


## rec_kill_enemies: análise final (2026-11-19)

O replay fino (passo 4, 3750 amostras) confirma: **a take percorre só
menus/galerias** — 0 (intro curta) → 80 → 84/107/85/108/86/107/87
(pré-visualizações da galeria de bosses) → 83/82 (menus). O `0x66`/`$4F`
que aparece no pool são **peças decorativas estáticas** desses ecrãs
(8 registos no `room_area80.json`; posições fixas, jogador em (128,128)
modo menu), não fireballs. **Nenhum tiro foi disparado** — nesses ecrãs
não há inimigos e o botão não faz nada. O valor real da take foi a
descoberta dos corredores 107/108 da galeria (commit anterior).

**A take que falta para a geometria do acerto (§3):** numa sala normal
com inimigos **no chão** — área 2 (os esqueletos no chão perto do
ledge de x≈1000) ou a área 10 (os ogres agora portados) — encara um
inimimo parado e dispara **cada tipo de tiro** uns segundos. O
replay a passo 4 dá o frame exacto do impacto e a distância
tiro↔alvo.


## rec_kill_enemies: CORRECÇÃO da leitura (2026-11-19, input log)

O utilizador corrigiu: **a take TEM jogo real** — e o `input_log.jsonl`
confirma. Os primeiros ~8400 frames são idle (menus a avançar sozinhos);
**a jogada real é g8988→fim**, nas áreas **87/83/0/82**, com inputs
densos (máscaras 1/2/8/16/32/64/128). Os inimigos que ele descreve
("normais, espalhados pelos cenários") são **dinâmicos** — as salas
82/83 têm **0 objectos nos JSONs** e ainda assim o pool enche de
`$66`/`$33`/`$35-38` — spawnadas pelo script da sala, não por
registos. A minha leitura "menus/attract" da janela final estava
ERRADA (a janela inicial até g8400 sim era idle).

**Porque é que a geometria ainda não saiu**: o replay mostra que os
tiros do jogador **não vivem no pool de 26 slots** — nenhum slot se
move a ~3 px/frame durante os disparos (o `0x4F` afinal é peça estática
do ecrã 82). O port também separa os projécteis (ProjectilePool) —
provavelmente com razão. Para medir o impacto falta:
1. achar na ROM o handler do fireball e o **endereço WRAM do array de
   projécteis** (o repo do oracle é recompilador sem símbolos — é
   leitura de ROM, não grep);
2. estender o `trace_stage.py` com um dump desse array;
3. re-replay a MESMA take (`rec_kill_enemies`, janela g8988+) — os
   disparos estão lá, só não são visíveis pelo blob actual.


## Sessão do fireball (2026-11-19, commits abaixo)

`docs/FIREBALL.md` novo: o fireball É objecto do pool (flags $1080),
spawn $A91D, despawn $82:E6AC/$82:E49E (x∈[0,255], morre dx=+257/-1),
voo $82:E4A3 (jsl $809481, trilha $82877B em $0016∈{$1C,$1D}).
**Falta**: o teste de acerto tiro↔inimigo (dentro de $809481 ou o
despacho seguinte) — disasm na próxima sessão. A take que fecha:
sala normal + inimigo no chão + um tiro de cada tipo — o `--objects`
AGORA vê os fireballs (não precisa de ferramenta nova, graças ao
descoberta de que são objectos do pool). `rec_kill_enemies` não dá
geometria: os presses do tiro caem todos em estado 2 (menus/galeria —
medido). Novo tool: `tools/oracle/find_projectiles.py` (diferencial
WRAM; lição: o debug server é endereçamento 16-bit, sem banco $7F).
