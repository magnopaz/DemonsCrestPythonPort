# Plano — Revisão de sprites e animações (port Demon's Crest)

**Data:** 2026-10-25  
**Escopo:** revisão do projeto `DemonsCrestNativePort` com foco em sprites e
animações, cruzando `docs/PLAN_SPRITES_ANIMATION.md`, `docs/PROJECT_STATE.md`,
`docs/PLAN_FULL_PLAYABLE.md`, `docs/MVP_SOMULO.md` e o código atual.  
**Objetivo:** identificar problemas concretos e propor um plano de melhoria
executável, sem alterar o jogo nesta etapa.

---

## 1. Resumo executivo

O port tem uma base sólida de extração (OAM/VRAM/CGROM, metasprites, capturas
de espécies), mas a camada de **animação em tempo de execução ainda é
imperativa e específica por espécie**. O resultado é que cada novo inimigo/boss
exige edições em `src/render.c` com números mágicos, e a maior parte das
espécies capturadas tem **um único frame**. Além disso, **sprites de objeto não
são espelhados** conforme o facing, o que quebra a leitura visual em pelo menos
metade dos encontros.

A causa raiz não é falta de arte: é a ausência de um **contrato de dados de
animação comum** (clips + estados) e de um **gate automatizado de recomposição**
que valide sprite, âncora e paleta contra o emulador.

---

## 2. Problemas identificados

### P1 — Animação de inimigos não é data-driven

- Em `src/render.c`, `DrawObjects` seleciona o frame com `if (o->species == 0xA5 …)`,
  `if (o->species == 0x09 …)`, `if (o->species == 0x13 || 0x86 …)`,
  `if (o->species == 0x33 …)`. Qualquer espécie nova precisa de mais um bloco.
- `species_anim.json` só tem `frames[]` (lista linear) + `duration` genérico;
  não há noção de **clip** (idle/walk/attack/hurt/die) nem de estado.
- Consequência: animações não correspondem ao estado real do objeto; o timer
  avança linearmente mesmo em estados de ataque/morte.

**Arquivos:** `src/render.c` (`DrawObjects`), `src/object.h` (`Object`),
`src/assets.c` (`LoadSpeciesSheets`), `tools/dc_extract/extract_species.py`.

### P2 — Sprites de objeto não respeitam `facing`

- `Object` tem campo `facing`, mas `DrawObjects` sempre usa `sf->texture`
  (nunca a versão espelhada). Inimigos que andam para a esquerda aparecem
  virados para a direita.
- `SpeciesFrame` não possui textura espelhada (ao contrário de `AnimStep`,
  que tem `flipped`). O trap #6 do projeto diz que retângulos de origem negativos
  no raylib são não confiáveis, então o espelho precisa ser pré-baked.

**Arquivos:** `src/assets.h` (`SpeciesFrame`), `src/assets.c`, `src/render.c`.

### P3 — Cobertura de animação é mínima

- `species_anim.json` tem 32 espécies, mas **26 delas têm apenas 1 frame**.
  Apenas `0x09` (6), `0x0a`/`0x13`/`0x86` (6), `0x33` (4) e `0xa5` (4)
  têm ciclos.
- `capture_species.py` captura apenas 3 frames por espécie (`--frames 2,4,6`) e
  não deixa a IA do inimigo evoluir; por isso o dedup colapsa tudo em 1 pose.
- Não existe captura longa por espécie equivalente a `capture_anim.py` para o
  player.

**Arquivos:** `tools/oracle/capture_species.py`, `tools/dc_extract/extract_species.py`.

### P4 — Durações e âncoras heterogêneas

- Todas as poses de espécie usam `duration = 6` (ou `pose_frames`), mesmo
  quando o original usa cadências diferentes.
- `anchor_y` varia até ~14 px entre frames da mesma espécie (ex.: `0x07`:
  35.0 → 48.34), indicando que a âncora foi derivada do crop, não da posição
  real do objeto (viola o princípio do `PLAN_SPRITES_ANIMATION.md` §2).
- `anchor_x` é fracionário (`round(..., 2)`), mas o render usa `float` e trunca
  na conversão; inconsistência de sub-pixel.

**Arquivos:** `tools/dc_extract/extract_species.py`, `src/render.c`.

### P5 — Pipeline A (OAM compositor) ainda não validado

- `tools/dc_extract/oam_compose.py` tem flag `BIG_ENDIAN_DUMP` suspeita e
  comentários dizendo que o gate de recomposição ainda não passou.
- A decodificação de quadrantes 16×16 (`base_tile + col + row*16`) pode estar
  errada para bosses multi-parte (Somulo perde partes do corpo).
- Não existe ferramenta de **recomposição diff** (renderizar todos os objetos +
  BG a partir dos dados extraídos e comparar com `dump_frame_raw`). Sem isso,
  o gate de aceitação (≤0,5 % de pixels diferentes) não é executável.

**Arquivos:** `tools/dc_extract/oam_compose.py`, `docs/PLAN_SPRITES_ANIMATION.md` §3/§7.

### P6 — Bosses multi-parte não recompostos

- Somulo é desenhado como um único sprite (`species 0x33`), mas no original é
  composto por OAM slots separados (`$33/$35/$36/$37`).
- A entrada (frames 2475/2516/2596) não pode ser recortada limpa porque o
  compositor ainda perde partes do corpo; o commit `96697f3` animou com 3 frames
  recortados da gameplay, com resíduos de cenário.
- `PLAN_SPRITES_ANIMATION.md` §3 já prevê agrupamento por pool position, mas
  não foi aplicado aos bosses.

**Arquivos:** `src/render.c` (frames 0–3 de `0x33`), `docs/MVP_SOMULO.md`.

### P7 — Player forms desativados por padrão

- `Assets_PlayerAnimForForm` retorna a animação capturada (`player_anim`) a
  menos que `DC_PLAYER_FORMS=1`. Motivo documentado: corte irregular das sheets
  (3–5 frames em vez de 5–6, slivers, captions capturadas).
- `bake_player_forms.py` usa keying por cor dominante + split por banda, que
  falha em linhas irregulares.
- Consequência: as seis formas continuam usando a mesma arte com tint.

**Arquivos:** `src/assets.c` (`Assets_PlayerAnimForForm`), `tools/dc_extract/bake_player_forms.py`,
`docs/PLAN_FULL_PLAYABLE.md` §A1.

### P8 — Animações faltantes do player

- `AnimClipId` tem apenas 8 clips; faltam `hurt`, `die`, `wall_cling`,
  `hover` distinto de `fly`, `attack` carregado.
- Player forms não têm clips próprios (reutilizam base).
- `fly` reutiliza `hover` (documentado como temporário).

**Arquivos:** `src/anim.h`, `src/anim.c`, `src/player.c`.

### P9 — Backgrounds e parallax incompletos

- Apenas 22 áreas têm BG2 real; as demais usam camada transparente.
- Parallax HDMA (`$84:AF65`) só está wired para a área 1.
- O coliseu (área 0) ainda tem problemas de piso/posicionamento (MVP doc:
  "feet sit below the room's floor").

**Arquivos:** `tools/dc_extract/bg2_captures.json`, `src/render.c` (`DrawLayer`),
`docs/MVP_SOMULO.md`.

### P10 — Somulo: entrada e segunda fase

- A entrada tem estados 0–7, mas reutiliza um único frame full-body; faltam
  sprites de olhos fechados/abertos, rugido, portão abrindo.
- A segunda fase (área 34) não está staged como encontro.
- Boca/flame effect no momento do disparo ausente.

**Arquivos:** `src/object.c` (estados 0–7), `docs/MVP_SOMULO.md`.

### P11 — Hitboxes e colisão desacopladas da arte

- AABB do player é fixo (12×22) independente do frame; para inimigos a hitbox
  é derivada de `o->timer`/espécie, não do sprite.
- Bosses usam hitbox hardcoded (40×46 para `0x33`).

**Arquivos:** `src/render.c`, `src/object.c`.

---

## 3. Objetivo do plano

1. Tornar a animação **data-driven** (clips + estados) para player, inimigos e
   bosses, eliminando números mágicos em `render.c`.
2. Garantir **espelhamento correto** por facing.
3. Validar sprites por **recomposição pixel-a-pixel** contra o emulador.
4. Cobrir **≥ 80 % das espécies** com ciclos de ≥ 3 poses.
5. Completar backgrounds/parallax e a entrada do Somulo.

---

## 4. Plano de execução

### Fase 0 — Contrato de dados (1 sessão)

**Tarefas**
- Versionar `species_anim.json` para v2 com estrutura:
  ```json
  { "species": { "33": { "clips": {
        "idle":  { "frames": [3], "loop": false },
        "walk":  { "frames": [0,1,2], "loop": true, "durations": [9,9,9] },
        "hurt":  { "frames": [4], "loop": false }
  }}}}
  ```
- Adicionar `SpeciesClip`/`SpeciesAnim` em `src/assets.h` (análogo a
  `AnimClip`/`PlayerAnim`).
- `LoadSpeciesSheets` passa a carregar clips; fallback linear se v1.
- Manter compatibilidade retro (ler v1 como clip único `idle`).

**Arquivos:** `src/assets.h`, `src/assets.c`, `tools/dc_extract/extract_species.py`.

**Aceite:** build passa; espécies existentes continuam renderizando.

### Fase 1 — Render data-driven + espelhamento (1–2 sessões)

**Tarefas**
- Adicionar `flipped` em `SpeciesFrame` e carregar textura espelhada em
  `LoadSpeciesSheets` (mesmo padrão de `LoadStepTextures`).
- Em `DrawObjects`, selecionar clip por `(type, state)` via tabela, não por
  espécie:
  - `OBJECT_ENEMY`: `state==0` → idle, `state==1` → walk, `state==2` → attack,
    `hit_flash>0` → hurt.
  - `OBJECT_BOSS`: mapear estados existentes (0 idle, 1 windup, 2 fire, 4 hurt,
    7 blind-walk) para clips.
- Espelhar sprite quando `o->facing < 0` (usar `flipped`).
- Remover todos os `if (o->species == …)` de `DrawObjects`; mover regras
  específicas para a tabela de clips no JSON.

**Arquivos:** `src/assets.h`, `src/assets.c`, `src/render.c`.

**Aceite:** regressão passa; inimigos viram corretamente nos demos 10/12.

### Fase 2 — Pipeline A validado (2 sessões)

**Tarefas**
- Corrigir decodificação de quadrantes 16×16 em `oam_compose.py` (validar
  contra `extract.py::compose_oam`, que já decodifica corretamente).
- Implementar `tools/dc_extract/recompose_diff.py`:
  - entrada: pasta de probe + dados extraídos (sprites + BG).
  - renderiza frame completo em CPU (BG1/BG2 + OAM) e compara com
    `dump_frame_raw`/`frame.bmp`.
  - saída: % de pixels diferentes, maior componente de alpha, relatório.
- Adicionar ao `run_regression.py` um check por espécie quando
  `DC_SPRITE_GATE=1`: sem pixels preto-opacos, sem componente alpha > 1 %,
  âncoras consistentes ≤ 2 px.

**Arquivos:** `tools/dc_extract/oam_compose.py`, novo `recompose_diff.py`,
`tools/run_regression.py`.

**Aceite:** recomposição de um frame de referência com ≤ 0,5 % de diferença.

### Fase 3 — Recaptura de espécies com sequências longas (2–3 sessões)

**Tarefas**
- Estender `capture_species.py` para capturar N frames (ex.: 60) em intervalos
  de 4–6 frames, mantendo o objeto ativo e permitindo que a IA evolua.
- Suportar `--frames 4,8,12,...,60` e dump de WRAM por frame (para classificar
  por estado `$00`/substate).
- `extract_species.py` classifica poses por estado do objeto (init/substate)
  em vez de dedup cego; emite clips separados.
- Re-bake todas as 32 espécies; substituir as de 1 frame.

**Arquivos:** `tools/oracle/capture_species.py`, `tools/dc_extract/extract_species.py`.

**Aceite:** ≥ 25 espécies com ≥ 3 poses; `species_anim.json` v2.

### Fase 4 — Player forms e animações faltantes (2 sessões)

**Tarefas**
- Reescrever o corte de `bake_player_forms.py` usando caixas medidas por
  espécie (tabela manual de bandas por sheet), em vez de detecção automática.
- Adicionar clips `hurt`, `die`, `wall_cling` ao `player_anim.json` (capturar
  via `capture_anim.py` com segmentos novos).
- Ativar forms por padrão quando a cobertura for ≥ 6 clips por forma.
- Diferenciar `hover` de `fly` (capturar clip separado).

**Arquivos:** `tools/dc_extract/bake_player_forms.py`, `src/anim.h`, `src/anim.c`,
`src/player.c`, `src/assets.c`.

**Aceite:** `DC_PLAYER_FORMS=1` não é mais necessário; todas as formas animam.

### Fase 5 — Bosses multi-parte (2 sessões)

**Tarefas**
- Aplicar Pipeline A (agrupamento por pool position) ao Somulo e gerar
  `enemy_33_idle/walk/attack/hurt.png` com âncoras exatas.
- Substituir os 4 frames recortados da gameplay pelos frames compostos.
- Repetir para Arma (0xA5), Hippogriff (0x09), Grewon (0x13), Phalanx (0x86).
- Implementar entrada do Somulo com sprites dedicados (olhos fechados/abertos,
  rugido) e staging da área 34.

**Arquivos:** `tools/dc_extract/oam_compose.py`, `src/render.c`,
`src/object.c`, `docs/MVP_SOMULO.md`.

**Aceite:** walk do Somulo sem resíduos; recomposição ≤ 0,5 %.

### Fase 6 — Backgrounds e parallax (1–2 sessões)

**Tarefas**
- Adicionar uma entrada em `bg2_captures.json` por área jogável (capturar frame
  via transição real, não poke de `$008D` — trap #22).
- Re-bake BG2 para as áreas restantes.
- Decodificar tabela `$84:AF65` por área e wired no `DrawLayer`.
- Corrigir piso do coliseu (rebuild BG1 a partir de VRAM; já iniciado).

**Arquivos:** `tools/dc_extract/bg2_captures.json`, `tools/dc_extract/rebake_bg2.py`,
`src/render.c`.

**Aceite:** `audit_campaign.py` reporta BG2 em ≥ 80 % das áreas jogáveis.

### Fase 7 — Gates de regressão e aceitação (0,5 sessão)

**Tarefas**
- Adicionar ao `run_regression.py` checks de sprite (quando assets existirem):
  - sem pixels preto-opacos em PNGs de espécie;
  - âncoras consistentes ≤ 2 px dentro de um clip;
  - recomposição ≤ 0,5 % (modo `DC_SPRITE_GATE=1`).
- Documentar o fluxo de bake em `docs/TOOLING.md`.

**Arquivos:** `tools/run_regression.py`, `docs/TOOLING.md`.

**Aceite:** `run_regression.py` continua PASS; gate de sprite opcional PASS.

---

## 5. Mudanças de código sugeridas (detalhes)

### 5.1 `SpeciesFrame` com espelho

```c
typedef struct SpeciesFrame {
    Texture2D texture;
    Texture2D flipped;   /* pré-baked, como AnimStep.flipped */
    int anchor_x, anchor_y;
    int duration;
    int width, height;
} SpeciesFrame;
```

Carregar em `LoadSpeciesSheets` com `ImageFlipHorizontal` (padrão já usado para
`player_flipped`).

### 5.2 Seleção de clip por estado

Substituir o bloco de `if (o->species == …)` por:

```c
static int SpeciesClipFor(const Object *o) {
    if (o->hit_flash > 0) return SPECIES_CLIP_HURT;
    switch (o->type) {
    case OBJECT_ENEMY:
        return (o->state >= 2) ? SPECIES_CLIP_ATTACK
                               : (o->state == 1 ? SPECIES_CLIP_WALK
                                                : SPECIES_CLIP_IDLE);
    case OBJECT_BOSS:
        return BossClipFor(o); /* tabela por espécie no JSON */
    default: return SPECIES_CLIP_IDLE;
    }
}
```

### 5.3 Object com temporização de animação

Adicionar a `Object`:
```c
int anim_clip;
int anim_step;
int anim_timer;
```
Atualizar em `Objects_Update` ou em `DrawObjects` (como `Player_Animate`).

### 5.4 Âncoras inteiras

Mudar `anchor_x`/`anchor_y` em `SpeciesFrame` e no JSON para `int`, e no
extractor usar `round()` (inteiro), eliminando sub-pixel.

---

## 6. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Pipeline A ainda não validado; pode gerar sprites errados | Gate de recomposição antes de aceitar qualquer asset novo |
| Recaptura longa de 97 espécies consome tempo | Priorizar espécies usadas em MVP 2 (área 2) e bosses |
| Player forms podem continuar com corte ruim | Tabela manual de bandas por sheet; validar com contact sheet |
| Mudança de schema quebra assets antigos | Loader aceita v1 e v2; v1 vira clip único `idle` |
| Espelhamento pré-baked dobra uso de VRAM | Texturas são pequenas; impacto desprezível |

---

## 7. Ordem sugerida

1. Fase 0 (contrato) + Fase 1 (render data-driven + flip) — desbloqueia tudo.
2. Fase 2 (Pipeline A validado) — garante qualidade.
3. Fase 3 (recaptura) — cobertura.
4. Fase 4 (player forms) — visual.
5. Fase 5 (bosses) — MVP 2+.
6. Fase 6 (backgrounds).
7. Fase 7 (gates).

---

## 8. Critério de sucesso final

- `run_regression.py` PASS com gate de sprite opcional PASS.
- Nenhum `if (o->species == …)` em `src/render.c`.
- ≥ 25 espécies com ≥ 3 poses.
- Todos os inimigos viram conforme `facing`.
- Recomposição de frame de referência ≤ 0,5 % de diferença.
- Player forms ativos por padrão.

---

*Documento gerado como sugestão de melhoria; não altera código nem assets.*