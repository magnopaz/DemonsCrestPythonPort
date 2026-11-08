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

### 8. Help overlay de atalhos — concluído
- **Arquivo:** `tools/editor/web/js/map.js`
- `?` (ou o botão de info na toolbar) abre um modal com 15 atalhos: ferramentas, pan/zoom, grid, preview, minimap, save, undo/redo, copy/paste, delete, nudge e Alt+click.
- O mapa ignora o teclado enquanto qualquer modal está aberto; Esc fecha.

### 9. Heatmap de objetos no minimap — concluído
- **Arquivo:** `tools/editor/web/js/map.js`
- Pontos coloridos sobre a silhueta de colisão: bosses (roxo), inimigos (vermelho), urns (âmbar), talismãs/crests/itens (azul), NPCs (verde), decor (laranja) e portas (quadrado verde).
- Objetos fora dos limites do mundo são ignorados.

### 10. Validação inline de transições — concluído
- **Arquivo:** `tools/editor/web/js/map.js`
- O inspector de uma porta consulta `GET /api/rooms/<dest_area>` (com cache por área) e mostra badge:
  - `✓ Area N · spawn 0 of 1` quando o destino e o spawn existem;
  - `⚠ Area N has 1 spawn(s); spawn_id 99 is out of range`;
  - `✗ Area N does not exist`.
- O badge actualiza ao mudar `next_area` ou `spawn_id`.

### 11. Busca global de objectos — concluído
- **Arquivos:** `editor_data.py` (`search_objects()`), `server.py` (`GET /api/search`), `app.js`, `api.js`, `index.html`, `editor.css`.
- Procura em todos os 113 rooms por área, label/room name, type, species (decimal/hex), nome da espécie, flags e coordenadas; devolve `{area, index, type, species_name, x, y, …}`, com `total` e `truncated`.
- Campo **Search objects…** no topo; debounce 180 ms, até 30 resultados, `Enter` abre o primeiro, `Esc` fecha.
- Clicar num resultado abre `#map/<area>` e selecciona o objecto (via `app.pendingObject` + `MapEditor.init`), centrando a vista nele. Se a room já está aberta, selecciona directamente.

---

## 🔲 Próximas funcionalidades planejadas (ainda não implementadas)

(Nenhuma do plano original em aberto; próximas ideias: grafo com filtro por caminho, exportar o grafo em PNG e comparação de rooms lado a lado.)

---

## Arquivos modificados nesta sessão

| Arquivo | Descrição das mudanças |
|---|---|
| `tools/editor/web/js/map.js` | Minimap, exportação PNG, histórico/Back, transition inspector, help `?`, heatmap, validação de portas |
| `tools/editor/web/js/coverage.js` | Aba Collectibles |
| `tools/editor/web/js/api.js` | Endpoint `collectibles()` |
| `tools/editor/web/js/app.js` | Rota de navegação `#map/<area>` |
| `tools/editor/web/js/icons.js` | Ícone `minimap` |
| `tools/editor/web/css/editor.css` | Estilos do minimap e collectibles |
| `tools/editor/web/index.html` | Integração dos novos elementos |
| `tools/editor/editor_data.py` | `collectibles()`, `campaign_graph()`, `stage_name_for_area()`, `search_objects()` |
| `tools/editor/server.py` | Rotas `/api/collectibles`, `/api/campaign`, `/api/search` |
| `tools/editor/web/js/app.js` | Shell, rota e widget de busca global |
| `tools/editor/web/index.html` | Campo de busca global no topo |
| `tools/editor/web/js/campaign.js` | Campaign Graph View: stage bands, pan/zoom/fit, filtros, tabela, issues, duplo-clique |
| `tools/editor/web/test.html` | Check da Campaign View; lista passa a oito vistas |
| `tools/editor/test_editor.py` | Testes das rotas `/api/campaign` e `/api/collectibles`, cobertura do grafo |
| `tools/editor/server.py` | Rotas `/api/collectibles`, `/api/campaign` |
| `tools/editor/run.sh` | Script de início Linux |
| `tools/dc_extract/fix_species_anchor.py` | Correção menor de âncora |

---

## Verificação (2026-11-08)

- `tools/editor/test_editor.py` → **30/30**.
- Self-test do browser → **31/31**, incluindo `campaign graph view`, `keyboard shortcuts help`, `transition target validation`, `minimap heatmap` e `global object search`.
- Payload real: **113 rooms · 225 edges · 11 stages**.
- Nota operacional: a rota `/api/campaign` já estava em `server.py`; o servidor em execução é que era antigo. Reiniciar o editor após alterações ao backend.
