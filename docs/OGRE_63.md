# Ogre (`$63`) — a máquina lida da ROM, medida na take do estágio III

*Escrito a 2026-11-18, mesma sessão do port. Fontes: `disasm_range.py` no
banco `$83`, e o replay da take do estágio III (`rec_stage3_trace`,
`--objects` com o blob de estados `#$05.$06.$3B`) sobre as áreas 10/12,
que cobrem 13 dos 35 registos. Áreas 6/13/33 ficam sem take — os
restantes 22 registos partilham a mesma máquina.*

---

## 1. Os registos

35 registos: **7 na área 6, 7 na 10, 6 na 12, 7 na 13, 8 na 33**; flags
`128`/`129`. Hoje o extractor tipa-os `unknown`; o port encaminha-os por
espécie para um inimigo real (tem folha de 1 pose cozida, e a take
mostra-os a morrer a tiros com pickup).

## 2. Despacho (tabelas byte-indexadas, como o Belth)

```asm
83:9FAA  sep #$30
         ldx $05
         jsr ($9FB5,X)      ; estados: 0 → $9FBB, 2 → $A03C, 4 → $A116
         jmp $80F83D        ; cauda comum
```

Estado 0 (`$9FBB`): `ldx $06; jmp ($9FC0,X)` — subestados {0 → `$9FC4`,
2 → `$A002`}.

- **sub@0 `$9FC4` — a sonda**: `rep #$31; $34 → $1E; $34 += $0068`
  (o alvo da aterragem fica **104 px abaixo**); `ldy #$DC17; jsl $809CA4`
  (a sonda rectangular do censo §4, com o registo `$DC17`); se falha
  (`bcs`) → espera; senão: `$06=2`, random 0..15 → `$39 = $DC1B[X]`
  (salto), `$39>>=1 → $3A = $DC2B[X]` (duração), `$26=$1A`, `$09=4`.
- **sub@2 `$A002` — a contagem**: `dec $3A` → 0: **estado 2**, `$06=$39`,
  random → `$38 = $DC2E[X]`; e **se flags ≠ 0**: apaga-se o par
  (`$06=0, $0C=0, $41=0, $38=4`) e **`lda #$02; xba; lda #$91; jsl
  $82877B`** — nasce a espécie **`$91` (a peça lançada)**.

Estado 2 (`$A03C`): `ldx $06; jmp ($A041,X)` {0 → `$A047`, 2 → `$A0D1`,
4 → `$A0DA`} com a sub-tabela `$A04C` {0 → `$A054`, 2 → `$A063`, 4 →
`$A074`, 6 → `$A09C`, …} — o arco: `$A054` (som `$1A`, `$3B=2`), `$A063`
(`$3E=$18, $3D=2, $3B=4`), `$A074` (**`jsr $A253; jsl $808B9C`** (a
física do censo §4), **`jsl $808C31`** (colisão), `$38` conta → `$3B=6`,
som `$02`, `$809E7F`, `$3B=8`…). As fases `$3B` andam 2 → 4 → 6 → 8.

Estado 4 (`$A116`): o pousar/pós-salto (por ler em detalhe — a medição
deu-lhe a dwell).

## 3. Medido (take estágio III, áreas 10/12, blob de estados)

- **Estados vivos: {0: 155, 2: 22, 4: 141}** amostras; **subestados
  {0, 2, 4, 6}** — todos pares; **fases {0, 2, 4, 6}** — o `$3B` 2→4→6
  do arco confirmado ao vivo.
- **Ciclo por slot** (área 10, slot 8, o mais limpo): `(0,0)` idle →
  `(0,2)` armado → `(2,0,6)` no ar → `(4,2)/(4,4)/(4,6)` aterrado →
  re-armar. Período ~440 frames; janela armado→no ar ~40; a fase
  aterrada dura ~300 e **anda** (não é paragem).
- **Arco**: y 87 → 52 (subida de ~35 px), deslocação ~200 px por salto
  **na direcção do jogador** (o ogre persegue-o aos saltos: 576 → 1178
  na área 10).
- **`$91` nasce exactamente no frame em que o ogre vai ao ar** (g5041:
  ausente; g5061: presente) — o ramo das flags é o spawn da peça.
- **Nenhum ogre morre na janela medida** — os `$57` que piscam são
  **corações de urnas partidas**, não mortes (a verificação por slot
  mostra todos os ogres vivos do início ao fim da janela). A morte
  fica por medir numa take onde o jogador os mate, ou por leitura da
  convenção de acerto da ROM (NEXT_STEPS §3).
- **O estado 4 anda**: entre saltos, o ogre desliza ~0,5–0,75 px/frame
  na direcção do jogador (slot 8: (576,87) → (680,151) entre dois
  saltos) — não é uma paragem estática.
- *Os dados `$DC1B/$DC2B/$DC2E` leem-se como código nos bytes — o mesmo
  padrão das tabelas `$DF9C` do Belth; as constantes do port vêm da
  medição dos arcos, não desses bytes.*

## 4. O port

`dcpy/object.py`: `OGRE_*` (constantes medidas), `_spawn_ogre`
(inimigo real: tipo `OBJECT_ENEMY`, hp 2, folha de 1 pose), e
`_ogre_update`:

- estado 0 sub 0: encara o jogador; sonda o chão 104 px abaixo na
  direcção do salto (`level_floor_at`, a leitura do `$809CA4`); arma
  com contagem de 40;
- no descolar: **nasce a peça `$91`** (placeholder com vida de 300
  frames — a máquina própria fica pendente; sem isto o pool encheria);
- estado 2: parábola medida (apex 35 px, ~40 frames, ~200 px na
  direcção do encaramento; fases 2/4/6);
- estado 4: **anda** ~0,5 px/frame na direcção do jogador durante os
  ~300 frames medidos, depois volta a armar;
- contacto danifica o jogador (o ramo genérico dos inimigos);
- **sempre atingível** — acrescentado ao lado do ghoul na condição do
  `objects_check_projectiles` (os `$05` do ogre são estados de
  comportamento, não uma fase de "emerge").

`tools/check_ogre.py` (na regressão): 7 registos colocados, ≥1 ciclo
completo (estado 2 depois 4), ≥100 px de viagem, peças `$91` nascem e
expiram (pico ≤4 vivas).

## 5. Pendente

1. **A máquina da peça `$91`** (o que ela faz depois de lançada — hoje é
   placeholder com prazo; precisa de leitura da ROM + take).
2. **A convenção do acerto no chão**: o fireball nasce 18 px acima dos
   pés e a caixa do inimigo é ±12 — um tiro ao nível do chão não alcança
   um inimimo no chão (NEXT_STEPS §3, precisa da convenção da ROM). A
   take mostra ogres a morrer a tiros; o *kill* entra no checker quando
   a convenção fechar.
3. As tabelas `$DC1B/$DC2B/$DC2E` e o estado 4 (`$A116`) por ler.
4. Áreas 6/13/33 sem take — os 22 registos restantes usam a mesma
   máquina; uma take que passe por elas valida a colocação.
