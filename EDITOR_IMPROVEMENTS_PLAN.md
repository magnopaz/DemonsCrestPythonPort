# Plano de Melhorias do Editor — Demon's Crest Python Port

> Arquivo de acompanhamento criado em 2026-11-08.

## Estado atual (branch `develop`)

O editor já possui: Map Builder, Enemy Editor, Player Editor, Dialogue, Coverage, Checks e Asset Browser.

---

## ✅ Funcionalidades JÁ implementadas nesta sessão

### 1. Minimap interativo (Map Builder)
- **Arquivo:** `tools/editor/web/js/map.js`
- Canvas sobreposto ao canto inferior-direito do mapa com silhueta de colisão colorida por tipo de ambiente (sólido / hazard / água / breakable) e viewport destacado.
- Clique/arrastar no minimap navega o canvas principal para aquela região.
- Tecla `M` ou botão na toolbar liga/desliga o minimap.
- Renderiza via `drawMinimap()` a cada frame do canvas.

### 2. Exportar room completo como PNG (Map Builder)
- **Arquivo:** `tools/editor/web/js/map.js`
- Botão **Full map PNG** na toolbar e no menu Preview.
- Renderiza off-screen todos os layers visíveis (BG0/BG1, colisão, objetos, transições, spawns) em dimensões reais do mundo e faz download como `area<N>_full.png`.

### 3. Navegação histórico de rooms + botão Back (Map Builder)
- **Arquivo:** `tools/editor/web/js/map.js`
- `requestLoadArea(area, trackHistory = true)` empilha a área anterior em `navHistory`.
- Botão **← Back** aparece na toolbar quando há histórico; some quando vazia.
- Transition inspector mostra botão **"Back to Area N"** após navegar por um link de transição.

### 4. Transition Inspector aprimorado (Map Builder)
- **Arquivo:** `tools/editor/web/js/map.js`
- Painel lateral de edição de transições com link clicável para a área de destino.
- Exibe campos `dest_area`, `dest_spawn`, `x`, `y`, `width`, `height`, `type` com inputs numéricos.

### 5. Aba "Collectibles" na Coverage View
- **Arquivo:** `tools/editor/web/js/coverage.js`
- Nova aba no painel Coverage listando todos os objetos coletáveis (Crests, Talismans, Urns, outros) por área.
- Filtros por categoria, busca textual, e botão **Edit room** para navegar direto à área no Map Builder.
- Dados fornecidos pela nova API `/api/collectibles`.

### 6. Backend: `collectibles()` e `campaign_graph()` (editor_data.py)
- **Arquivo:** `tools/editor/editor_data.py`
- `Workspace.collectibles()`: varre todos os rooms, identifica objetos coletáveis (por `type` ou `flags`), agrupa por categoria e retorna JSON com sumário.
- `Workspace.campaign_graph()`: grafo de conectividade de todos os rooms — nós com metadados de área, estágio, transições, spawns, gate; arestas de transições; detecção de issues (broken doors, dead ends, unreachable rooms).
- `stage_name_for_area()`: heurística de classificação de estágio por número de área e música.

### 7. Campaign Graph View (aba Campaign) — concluído
- **Arquivos:** `tools/editor/web/js/campaign.js`, `index.html`, `app.js`, `api.js`, `icons.js`, `editor.css`
- Canvas com 113 rooms em faixas de estágio (ordem de campanha, não alfabética), portas a verde e gates a âmbar; badge `AUTH`, `DEAD END` e ponto vermelho para broken doors/spawns inválidos.
- Pan/zoom, **Fit** (campanha inteira), **Reset View**, foco no room selecionado no arranque, `ResizeObserver` e duplo-clique para `#map/<area>`.
- Filtros de busca, estágio (foca o primeiro room) e **Issues only**; vistas Visual Graph, Room Table e Navigation Issues.
- Painel lateral com saídas/entradas (portas duplicadas colapsadas), spawns, música/estágio e **Open in Map Builder**.
- Rota `GET /api/campaign` devolve `{nodes, edges, stages, issues, stats}`.
- **Verificação:** 113 rooms · 225 edges · 11 stages; `test_editor` 29/29; self-test 27/27.

---

## 🔲 Próximas funcionalidades planejadas (ainda não implementadas)

### B. Keyboard shortcuts overlay (Help overlay)
- Exibir painel com todos os atalhos de teclado ao pressionar `?`.
- Já existe `bindKeys()` em map.js — apenas montar o HTML de ajuda contextual.

### C. Heatmap de objetos no minimap
- Sobrepor pontos coloridos no minimap representando posições de inimigos, itens e transições.
- Extensão simples de `drawMinimap()`.

### D. Validação visual inline de transições
- No painel lateral de transição, mostrar badge verde/vermelho se `dest_area` existe e se `dest_spawn` é válido naquela área.
- Chamar `GET /api/rooms/<dest_area>` em background.

### E. Busca global de objetos
- Barra de busca que encontra qualquer objeto (por `type`, nome, área) em todos os rooms.
- Rota: `GET /api/search?q=...` no backend.

---

## Arquivos modificados nesta sessão

| Arquivo | Descrição das mudanças |
|---|---|
| `tools/editor/web/js/map.js` | Minimap, exportação PNG, histórico/Back, transition inspector melhorado |
| `tools/editor/web/js/coverage.js` | Aba Collectibles |
| `tools/editor/web/js/api.js` | Endpoint `collectibles()` |
| `tools/editor/web/js/app.js` | Rota de navegação `#map/<area>` |
| `tools/editor/web/js/icons.js` | Ícone `minimap` |
| `tools/editor/web/css/editor.css` | Estilos do minimap e collectibles |
| `tools/editor/web/index.html` | Integração dos novos elementos |
| `tools/editor/editor_data.py` | `collectibles()`, `campaign_graph()`, `stage_name_for_area()` |
| `tools/editor/web/js/campaign.js` | Campaign Graph View: stage bands, pan/zoom/fit, filtros, tabela, issues, duplo-clique |
| `tools/editor/web/test.html` | Check da Campaign View; lista passa a oito vistas |
| `tools/editor/test_editor.py` | Testes das rotas `/api/campaign` e `/api/collectibles`, cobertura do grafo |
| `tools/editor/server.py` | Rotas `/api/collectibles`, `/api/campaign` |
| `tools/editor/run.sh` | Script de início Linux |
| `tools/dc_extract/fix_species_anchor.py` | Correção menor de âncora |

---

## Verificação (2026-11-08)

- `tools/editor/test_editor.py` → **29/29**.
- Self-test do browser → **27/27**, incluindo `campaign graph view` e `eight editor views`.
- Payload real: **113 rooms · 225 edges · 11 stages**.
- Nota operacional: a rota `/api/campaign` já estava em `server.py`; o servidor em execução é que era antigo. Reiniciar o editor após alterações ao backend.
