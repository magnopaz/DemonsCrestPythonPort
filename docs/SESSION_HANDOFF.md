# Handoff — fim da sessão de 2026-11-03

*Para retomar noutra sessão. Ler isto primeiro, depois `docs/NEXT_STEPS.md`.*

## Estado

- Repo: `~/Projetos/opencode/DemonsCrestPythonPort`
- `HEAD` = `942e978` (*Type $9B as inert…*), **árvore limpa**.
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
