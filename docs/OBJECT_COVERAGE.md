# Cobertura de objectos: do ROM para a sala

*Escrito a 2026-11-03, depois de fechar o Passo 1 do `NEXT_STEPS.md`.*

O extractor antigo tipificava só as 17 espécies de `SPECIES_KIND_MAP` e
**descartava em silêncio** tudo o resto: 591 dos 853 registos de objecto do ROM
nunca chegavam a um `room_area*.json`. Uma sala parecia completa numa captura e
estava vazia por dentro. Este documento fixa o contrato que impede o regresso
desse modo de falha.

## O contrato

1. **Todos os registos entram.** `tools/dc_extract/extract.py` lê as 113 listas
   de `$81:C874` e escreve um objecto por registo. Não há filtro por espécie nem
   por coordenada.
2. **Cada objecto diz de onde veio** (`source`):
   - `rom` — veio da lista de objectos do ROM (posição e flags do ROM; um boss
     substituído pela tabela verificada mantém `rom`, porque a posição continua
     a ser a do registo);
   - `boss_table` — injectado por `apply_boss_table.py` (bosses que o retail
     cria por script e a lista de objectos não contém);
   - `npc_table` — injectado por `apply_npc_table.py`;
   - `door_table` — usado em transições, não em objectos.
3. **Espécie sem handler fica `"type": "unknown"`**, com o `species` original.
   O port carrega-a, o pool ignora-a e o renderer desenha um marcador magenta
   de 12x12 no sítio do ROM. Nada é inventado sobre o que a espécie faz.
4. **A contagem é uma porta de regressão.** `tools/check_objects.py` compara,
   por área, a multiset de espécies dos objectos `source="rom"` com
   `rom.object_list(area)`; falha se um registo faltar ou aparecer a mais.

## Números medidos (2026-11-03)

```
objects placed / ROM ....... 853/853  (100.0%)
objects dropped ............ 0  (0 species)
objects in room JSON ....... 862  (82 species: boss_table 8, npc_table 1, rom 853)
objects listed in the ROM .. 853  (80 species, 90 areas)
species with a handler ..... 18/80  (578 records drawn as placeholders)
```

Os 9 objectos a mais que 853 são 8 bosses e 1 NPC que o retail cria fora da
lista de objectos; a parte `rom` é exacta e é essa que a porta mede. Por tipo
são 580 placeholders: os 578 registos de espécies sem handler mais os dois
`$96` obsoletos das áreas 52/54. O `$72` (13 registos) já não é placeholder:
passou a decor em `docs/FLAME_72.md`.

Casos conhecidos e deliberados:

- **Áreas 52 e 54**: a lista do ROM traz um boss marcador `$96` no sítio do
  boss real. `apply_boss_table.py` re-tipa-o para `unknown` (fica o marcador
  visível) em vez de apagar o registo; o boss verdadeiro (`$6F`/`$16`) é
  acrescentado.
- **Área 0 (Somulo)**: a tabela move o `$33` de `(32, 88)` para `(380, 170)`,
  porque na posição do ROM ele fica atrás da câmara e o duelo nunca começa.
  O `source` continua `rom`.
- **Três registos fora do mundo extraído** (`$61` na área 31, `$66` na área 80,
  `$B1` na área 107). São dados mortos do ROM: ficam no JSON, o renderer
  ignora-os por estarem fora do mundo, e o `audit_campaign.py` conta-os à parte
  em vez de os tratar como bug estrutural.

## Como verificar

```
python3 tools/report_coverage.py     # 853/853, 0 dropped
python3 tools/check_objects.py       # contrato + placeholders desenhados
DISPLAY=:99 python3 tools/run_regression.py
```

O `check_objects.py` também arranca a sala com mais placeholders e exige que o
renderer os desenhe (`DC_TRACE_PLACEHOLDERS=1` imprime
`placeholders_drawn=… placeholders_visible=…`). Em área 17 isso dá 2 marcadores
visíveis; em área 1 dá 2 no ecrã inicial (as chamas `$72`).

## O que falta

O passo seguinte do plano é dar handler às 20 espécies mais comuns — 451 dos
593 registos em falta. Cada handler substitui o marcador da sua espécie pela
arte e pela AI do ROM; `check_objects.py` continua a garantir que nenhum
registo desaparece pelo caminho.
