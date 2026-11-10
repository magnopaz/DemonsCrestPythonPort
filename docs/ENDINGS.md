# Os quatro endings

*Escrito a 2026-11-10, a partir da descrição do utilizador e de
`demon_s_crest_endings_guide.txt`. A cenografia (páginas, tempos, arte) **não
está medida**: a take `rec_bad_ending` tem a batalha, mas acaba com o subscreen
aberto e não mostra o ending (ver `docs/TAKES.md` §7).*

## 1. A regra

O que decide o ending é o que o Firebrand leva consigo quando o Phalanx cai —
não a percentagem de conclusão:

| condição | variante | `game_ending_variant` |
|---|---|---|
| sem o Crest of Time | **bad** — o reino desfaz-se | `0` |
| com o Crest of Time, sem todos os talismãs | **normal** — o Phalanx sela-se no Crest of Heaven | `1` |
| com o Crest of Time e os cinco talismãs | **good** — o Phalanx é vencido de vez | `2` |
| 100% e o Dark Demon morto | **true** — o password do Ultimate Gargoyle | `3` |

O **true** não sai desta luta: pertence ao Dark Demon (área 90 / stage secreto).
O port só o mostra com `DC_ENDING=true`; ligá-lo à morte do `$BC` fica para
quando esse caminho existir.

Antes de 2026-11-10 o port escolhia por percentagem (`>=100` good, `>=50`
normal), o que dava o ending errado a quem tivesse 100% sem o Dark Demon e a
quem tivesse o Crest of Time com poucos itens.

## 2. Gatilho no jogo

`dcpy/game.py::_game_playing_step`, no bloco do `boss_defeated`:

```python
if area_before in PHALANX_BOSS_AREAS and \
        game.objects.boss_killed_species == 0x8D:
    game_start_ending(game)
```

`PHALANX_BOSS_AREAS = (42, 75)` — a câmara da fortaleza (a da take, `$008D = 84`)
e a sala que tem o mesmo par de registos `$86`/`$88` (área 75, tipada boss pelo
mesmo registo do ROM; nenhuma take a visitou). `$86` é a primeira forma;
quando morre, `dcpy/object.py` põe `boss_phase = 2` e nasce o `$8D` com os 127
HP da tabela. Só a morte do `$8D` fecha a luta, e é essa que arranca o ending —
matar só a primeira forma continua a deixar o jogador na arena.

Antes disto, matar o Phalanx chamava `game_complete_area` e voltava ao mapa (e
dava +1 de HP máximo, que é a recompensa do *area clear*).

## 3. O texto

`assets/generated/endings.json` (gerado por `tools/dc_extract/build_endings.py`)
tem as quatro narrações transcritas de capturas de referência (vgmuseum) e o
epílogo do bloco `$81:8DF2` da ROM. **A narração não existe em ASCII na ROM**:
procurei `TAKEN`, `WOUNDED WINGS`, `INFINITY` com high-bit e offsets de tile e
não há nada — deve ser desenhada como tilemap. Até haver capturas do ecrã real,
a transcrição é a melhor fonte que existe.

O que **está** na ROM é o diálogo da luta, em `~0x1F3900` (duas cópias, uma por
caminho). As falas de morte, por ordem:

```
MY POWER IS FADING... BUT YOU SHALL NOT HAVE THE SATISFACTION OF KILLING ME!!
YOU THINK YOU HAVE DESTROYED ME! BUT IT WAS MERELY A SHADOW!
FINALLY. THE ULTIMATE POWER! BEHOLD! THE CREST OF INFINITY!
```

O port ainda não as encena antes do ending (a take não mostra em que momento
cada bloco entra), por isso não estão ligadas.

## 4. Cenografia (por medir)

O `_game_ending_step` atual avança com START, duas linhas por página, sobre o
mapa do mundo escurecido, e volta ao título no fim. É uma aproximação: a take
não tem nenhum frame do ending, e o `docs/PLAN_FULL_PLAYABLE.md` (B4) já dizia
que faltava uma captura por ending. Continua a faltar.
