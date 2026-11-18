# Somulo: análise dos falhanços da regressão e plano (2026-11-17)

## Diagnóstico

**A batalha está correcta; os dados é que estão errados.** Com os rooms
gerados (`DC_AUTHORED_ROOMS` a apontar para uma pasta vazia), o combate passa
todas as asserções:

| asserção da regressão | resultado com room gerado |
|---|---|
| `MVP: the six-hit rhythm` | hp `[6, 5, 4, 3, 2, 1, 0]` ✓ |
| `the first death blow did not faint him` | `(1,0) → (0,6)` (faint) ✓ |
| `he did not come back with 3 hp` | `(3,0)` de volta ✓ |
| `the last three hits did not collapse him` | termina `(0,5)` (colapso) ✓ |
| `the gate after Somulo did not lead to area 34` | áreas `[0, 34]` ✓ |
| `up doors` (área 4) | 6 portas, PASS ✓ |

A causa é o **overlay de rooms autorais** (`assets/authored/rooms/`), que o
loader lê *antes* do gerado (`dcpy/level.py::_load_room_with_override`). Foi
criado no commit `8ec5e85` (toolkit/editor, 2026-11-08) e o
`room_area0.json` autoral:

1. **move o Somulo para (138, 124) com flags 0** — o gerado tem (380, 170)
   flags 128. Com o pé a +23 (a correcção do âncora), ele luta **em cima do
   spawn do jogador** (128, 172); a intro deixa-o em x≈40. O demo caminha para
   a direita e dispara para onde ele *costumava* estar — daí `hp went [6]`,
   `the boss was still alive`, e a porta pós-boss nunca abre.
2. **apaga a porta pós-boss do door_table** (740,191 → 34, `type -2`) e põe
   em vez disso **quatro cópias** de (760,120 → 34) com `source:
   "notes_repointed"` mais uma porta "restored" para a 17 — nenhum dos dois
   na posição verificada.
3. `gate_next_area` 34 em vez de 1.

O `room_area4.json` autoral faz o mesmo género na avenida: repõe o "boss
fantasma" (`$96` tipado boss) e parte as três portas up — o bug que a sessão
de 2026-11-07 tinha corrigido no pipeline gerado.

Dois agravantes:

- `check_mvp_somulo.py` **passa sozinho** com o room autoral porque só testa
  a intro e a estabilidade do y do boss — nunca dispara um tiro. Nada na
  suíte validava a geometria do combate contra o overlay.
- O bisect confirma: `18e42f1` (áudio) verde → `8ec5e85` (toolkit, cria os
  rooms autorais) vermelho; todos os commits seguintes herdam.

A falha de **áudio** da regressão (WAVs por nível não cozidos) é outra coisa,
não é do Somulo — ver o plano, passo 4.

## Plano

1. **Rebase dos rooms autorais 0 e 4 sobre o gerado actual** (meia-hora).
   Regenerar `assets/authored/rooms/room_area{0,4}.json` a partir dos
   gerados — boss de volta a (380,170) flags 128, porta pós-boss (740,191 →
   34) e a tabela de portas da avenida intactas — e reaplicar pelo editor
   apenas o que se quiser mesmo mudar. Se não há edição intencional a
   preservar, apagar os dois ficheiros é equivalente e mais limpo.

2. **Guarda nova: `tools/check_authored_rooms.py`** (~1 h). Para cada room
   autoral, compara com o gerado e falha em campos críticos do motor —
   registos de boss (espécie/flags/posição), transições/portas, spawn,
   `gate_next_area` — a menos que a diferença esteja numa whitelist explícita
   no próprio checker. Entra na regressão. Teria apanhado o `8ec5e85` no
   dia.

3. **Fechar o buraco do `check_mvp_somulo.py`** (meia-hora). Acrescentar um
   passe que mata o boss a sério (o guião do demo 14: caminhar e disparar
   até `hp == 0`, depois atravessar a porta) e afirmar o fim da luta —
   assim a geometria do combate é testada standalone e o overlay errado
   falha logo nesse checker.

4. **Áudio, à parte** (uma sessão): cozer os WAVs por nível que faltam
   (`music_murkland.wav`, etc.) com `tools/audio/make_music_asset.py` —
   exige corridas do oracle por save state; hoje só existe
   `music_boss.wav`. Sem isto a regressão não fica verde, mas não tem nada a
   ver com o Somulo.

Ordem: 1 → 3 → 2 → (4 quando houver tempo de oracle). Depois do 1+3 os
itens do Somulo e das up-doors ficam verdes; o 2 impede a repetição.

## Execução (2026-11-17)

1. **Feito — os rooms autorais 0 e 4 foram apagados** (não havia edição
   intencional a preservar: os BG1 eram cópias velhas de outra extracção —
   2496 vs 2048 tiles no coliseu —, o "notes_repointed" contradizia o
   door_table, e o boss movido partia o combate). O overlay da área 1
   (cemetery BG1 fix) fica. Verificação: `check_up_doors` PASS,
   `test_editor` 30/30, `check_boss_hp` 17 salas/0 erros.
2. **Feito — `tools/check_authored_rooms.py`**, na regressão. Compara cada
   room autoral com o gerado em bosses/transições/spawn/gate/arena e falha
   sem whitelist (a área 1 passa; a nota lista as chaves não-críticas que
   diferem). Teste negativo: com o room_area0 mau reposto do git, falha
   com `bosses`, `transitions` e `gate_next_area` — teria apanhado o
   `8ec5e85` no dia.
3. **Feito — `check_mvp_somulo.py`** ganhou dois passes com o guião do demo
   14: (a) matar a sério — seis tiros `6→0`, o boss morto antes do fim e o
   gate → área 34; (b) `DC_BOSS_HP=1` — o primeiro golpe de morte faz o
   faint `(1,0)→(0,6)`, volta com `(3,0)` e os últimos três colapsam
   `(0,5)`. O checker deixa de passar com a geometria partida.
4. **Pendente** — os WAVs por nível continuam por cozer (áudio à parte).
