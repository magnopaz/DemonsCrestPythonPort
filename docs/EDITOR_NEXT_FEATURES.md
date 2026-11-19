# Editor: verificação e features propostas (2026-11-19)

Revisão do content toolkit (`tools/editor/`) contra tudo o que as
medições recentes ensinaram. O que JÁ existe e está sólido:
Map Builder (tiles/colisão/objectos/portas/spawns/bounds/minimapa/
compare/preview/render-in-game), Enemy Editor (frames/estados 0-15/
stats/AI/movimento/ataques/sons), Player Editor (11 clips, hitbox),
Dialogue (518 blocos, caps reais, usages), Coverage, Campaign (113
salas), Checks, Asset Browser, API HTTP completa. Regressão:
`test_editor` 30/30.

## Gaps medidos — features que as medições justificam

### 1. Importador de trajectórias do oracle (prioridade alta)
O blob do `trace_stage replay --objects` traz, desde o `952c983`, os
estados vivos `$05`/`$06` por frame. O editor não consome isto.
**Feature**: carregar um CSV de blob no Enemy Editor/Map Builder e
(i) desenhar a trajectória por espécie no palco (arcos do ogre: apex
35px, 40 frames aéreos, ~200px; hops do Belth entre âncoras);
(ii) derivar durações de estado medidas → aplicar às durações de
animação; (iii) verificação de âncoras (os 21 registos do Belth = as
âncoras seria um clique, não um script ad-hoc).
**Touchpoints**: `editor_data.py` (parse do CSV, séries por espécie),
rota `POST /api/species/<key>/trace`, overlay no `web/js` do palco.

### 2. Matriz de dano por forma nas definições autorais (alta)
`dcpy/bosses.py` tem `BOSS_DAMAGE` (10 colunas por luta:
Fire/Buster/Claw/Tidal/DemonFire/Earth-chão/Earth-ar/Aerial/Legendary/
Ultimate), mas o schema autoral (`enemies.json` → `enemy_defs.py`)
só tem `status{hp, contact_damage}` — **não há forma de expressar dano
por forma num inimigo autoral**.
**Feature**: campo `forms_damage` (10 chaves, 0=N/A=imune) na definição
+ UI de grelha 10 colunas no tab Stats; runtime: `object.py` usa a
matriz autoral primeiro, senão `boss_damage()`.
**Touchpoints**: `enemy_defs.py` (getter), `object.py:292/460`
(consumo), `server.py` (rota species), tab Stats no web.

### 3. Badges "valor documentado da ROM" (barata, evita erros)
O editor nunca importa `dcpy/bosses.py`: quem edita HP não vê o valor
documentado (`docs/boss_hp.txt` é a fonte de verdade) ao lado.
**Feature**: no Stats, para espécies com entrada documentada, mostrar
`boss_hp(species,flags)` e a linha de `BOSS_DAMAGE` como referência
read-only; um override autoral que contradiga o doc fica sinalizado.
**Touchpoints**: `server.py` importa `dcpy.bosses`; badge no web.

### 4. Faixa do fireball no preview (barata, educativa)
Medido (`docs/FIREBALL.md`): o tiro vive só com x∈[0,255] de ecrã
(morre em dx=+257/-1; teste `$82:E6AC`, killer `$82:E49E`).
**Feature**: no preview do Map Builder e no palco do Player Editor,
desenhar as bordas onde o tiro morre — evita confundir "o tiro
desapareceu" com "bateu na parede".
**Touchpoints**: `editor_data.py` (meta), overlay do palco.

### 5. Camada de spawners para salas autorais (média)
Descoberta da `rec_kill_enemies`: as salas 82/83 enchem os pools com
`$66` **sem nenhum registo JSON** (spawn por script, ainda não
medido). O Map Builder só carimba registos — não há forma de autorar
uma sala com spawns dinâmicos.
**Feature**: lista `spawners` no JSON de sala autoral (espécie, x, y,
count, cadência, gatilho) com overlay próprio; o runtime lê só em
salas autorais. **Rótulo obrigatório "comportamento autoral"** —
nunca apresentado como ROM-derivado (a fidelidade fica limpa).
**Touchpoints**: schema em `editor_data.py` + validação; leitura em
`level.py`/`object.py` num ramo authored-only.

### 6. Coverage: espécies dinâmicas não medidas (barata)
As contagens do Coverage só vêem registos; salas cujo pool do oracle
contém espécies sem registo (82/83, `$66`) ficam invisíveis.
**Feature**: flag na tab Rooms "script-spawned (não medido)" a partir
de um censo mantido à mão (o do FIREBALL.md é o primeiro), ligando ao
fluxo de medir-then-portar.
**Touchpoints**: `report_coverage.py`/rota `/api/coverage`.

### 7. Timings de estado a partir do blob (incluída na #1)
Os estados 0-15 do Enemy Editor aceitam durações manuais; a medição
do blob (fases 2→4→6 do ogre, ~440 frames de ciclo) deve poder
preencher esses campos com um clique em vez de transcrição.

## Ordem sugerida

#3 e #4 primeiro (horas, sem risco), depois #2 (schema+runtime+UI),
depois #1+#7 (a ponte medir→autorar, o maior salto de valor), #5 e #6
quando houver sala autoral nova a precisar delas.
