# Species `$72` — as chamas do cemitério (decor)

*Fechado a 2026-11-03. É a primeira espécie do Passo 2 e a primeira a usar o
tipo `decor`.*

## O que o ROM faz

| peça | endereço |
|---|---|
| init | `$85:D429` |
| update | `$85:D4CF` |
| dispatch | `LDX $05` / `JMP ($D4DD,X)` — 5 estados |
| caminho comum (`$03 == 0`) | `$D59A` |

O init (`$85:D429`) guarda `$08` da mesa `$0D33`, liga `$07`/`$36`, põe
`$22 = $FF40` e `$20 = $0040`, aponta o metasprite (`$28 = $E97E`,
`$2A = $E97A`, `$2E = $E9AE`), escolhe `$26 = $40` e `$0C = $80` quando o
registo não traz flags, e arranca a animação por `$80:F81D`.

O caminho comum (`$D59A`) conta `$38` até 0, repõe `$38 = $3C` e faz dois
probes (`$809CA4` com os parâmetros `$E982`/`$E986`); se ambos passarem e
`$0E51 < $E98E`, aloca outro `$72` (`$82877B`), incrementa `$0E51` e põe o
filho em estado 2 com `$38 = $F0`. É a parte que **não** está portada.

Não há, no handler, nenhum teste de contacto com o jogador nem dano: a chama é
efeito visual. O dano do jogo vem do tipo de objecto, não da espécie.

## O que o port faz

- `SPECIES_KIND_MAP` passa a mapear `0x72 -> "decor"`; o extractor escreve
  `"type": "decor"` nos 13 registos da área 1 (e em qualquer outra sala que os
  tenha).
- `dcpy/consts.py` ganha `LEVEL_OBJECT_DECOR = 10`. O pool ignora-o: sem
  colisão, sem dano, sem AI.
- `dcpy/render.py` desenha o sheet da espécie no sítio do registo, com o ciclo
  de 5 frames e durações do `species_anim.json`. Se não houver sheet, cai no
  placeholder magenta (para a ausência continuar visível).
- `DC_TRACE_PLACEHOLDERS=1` passa a imprimir também
  `decor_drawn=… decor_visible=…`.

## Evidência

- Captura do oracle (`captures/species_top/s72`): 5 frames de 16x16, um
  flicker de chama; o extractor cozeu `enemy_72_0..4.png`.
- Screenshot da área 1: as duas caixas magenta que estavam nos fogos
  desapareceram; as chamas aparecem nos dois archotes.
- `tools/check_flame.py` (ligado ao `run_regression.py`): exige os 13 registos
  `decor` na área 1, o sheet com ≥2 frames, `decor_drawn == 13` e
  `placeholders_visible == 0`.

## Bug encontrado pelo caminho: os sheets nunca carregavam

`dcpy/assets.py::_load_species_sheets` iterava `root.get("species")` como se
fosse uma **lista**, mas o formato real (o mesmo do port C e de
`bake_enemy_sheets.py`/`extract_species.py`) é um **objecto** indexado pelo id
em hex — `{"species": {"2c": {...}}}`. Iterar um dict devolve chaves (strings),
o `isinstance(entry, dict)` falhava e **nenhum sheet de espécie era carregado**:
inimigos e bosses desenhavam a arte processual de recurso. Corrigido para aceitar
os dois formatos; o `extract_species.py` também passou a manter o dict.

## Por fazer (documentado, não faked)

- O spawn de cópias em `$D59A` e os parâmetros dos probes (`$E982`/`$E986`/
  `$E98E`) vivem em WRAM `$7E:E9xx`, copiada pelo loader da sala; não estão
  descodificados. O port desenha a chama, não a multiplica.
- Os outros 4 estados (`$D5F9`, `$D618`, `$D53A`, `$D588`) só interessam quando
  o spawn existir.
