# Fireball do jogador — geografia na ROM (2026-11-19)

Fonte: `PORTING_NOTES.md` do recomp (secção widescreen, Fase 5/6) +
disassembly confirmado por mim com `disasm_range.py`.

## Factos medidos/confirmados

1. **O fireball É um objecto do pool** ($1080+stride). As notas do
   widescreen localizaram-no com um WRAM watch nas flags em `$1080`.
   Consequência: **o blob do `trace_stage --objects` vê os tiros** —
   qualquer take futura com tiros reais é legível SEM ferramenta nova.
2. **Spawn: `$A91D`** (phantom arm `SpawnFireball_$A91D` no cpu_trace.c
   do oracle, linha 1644).
3. **Despawn autêntico**: o teste "está no ecrã?" em `$82:E6AC`
   (`and #$FF00` — só mantém enquanto o byte alto de x é zero, x∈[0,255]).
   Fora → killer block **`$82:E49E`**: `lda #$08; sta $00; rts`
   (estado 8 = morto). Reprodução do dono: o tiro morre em
   **dx=+257 / dx=-1** (bordas nativas). Confirmado no disasm:
   `$82:E499 jsr $E6AC; bcs $E4A3` (continua vivo) / `E49E` (mata).
4. **Voo** (`$82:E4A3`+): `jsl $809481` (mover/animar com x=`$31`,
   a=`$34`); trilha de chamas: quando `$0016 ∈ {$1C,$1D}` faz
   `jsl $82877B` (spawna registo de partícula, índice por direcção);
   `$E4CB`: timer `$3A` decresce em 8-bit.
5. **O teste de acerto tiro↔inimigo NÃO está extraído** — deve estar
   dentro de `$809481` ou no despacho seguinte. Próximo passo.

## rec_kill_enemies: porque não deu geometria (medido, não assumido)

Os presses do botão de tiro (bit 8 do input log) caem TODOS em
**estado 2 do jogador** — (128,128)/(184,172), ecrãs 82/83/0 em modo
menu: g10424, g10539, g11095, g11195, g12042, g12172, g12341,
g12423, g14104, g14172. Em estado 2 o jogo ignora o botão —
**nenhum fireball nasce** (scan WRAM diferencial $0000-$8000 com banda
1..0x800/frame: zero palavras a mover à velocidade de tiro nos frames
dos disparos; duas corridas). Os ecrãs da galeria **mostram** inimigos
(por isso parecem cenários), mas são pré-visualizações congeladas.

## Take que fecha a convenção do acerto

Sala normal (área 2 esqueletos / área 10 ogres), inimigo **no chão**,
encarado, um tiro de cada tipo, 2-3 s cada. O `--objects` vê o fireball
nascer/voar/morrer no pool; o frame do impacto + posição do inimigo dá
a caixa de acerto autêntica. Receita completa no SESSION_HANDOFF.md.

## Ferramenta desta sessão

`tools/oracle/find_projectiles.py` — diferencial WRAM entre janela com
disparos e baseline calma; endereçamento do debug server é **16-bit
apenas** (banco $7E; `$7F` inacessível; comprimento em DECIMAL).
