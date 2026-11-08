/* Campaign & World Navigation Graph view.
   Visualizes all 113 rooms, door transitions, boss gates, and overworld entries.
   Identifies navigation issues (broken targets, missing spawns, dead ends). */

import { api } from "./api.js";
import { h, clear } from "./util.js";
import { icon } from "./icons.js";
import { toast, tabs } from "./ui.js";

const STAGE_COLORS = {
  "Stage 1 · Murkland": "#e0a13c",
  "Stage 2 · Ruined City & Town": "#60a5fa",
  "Stage 3 · Dark Forest": "#34d399",
  "Stage 4 · Towers of Doom": "#a78bfa",
  "Stage 5 · Poseidonia": "#38bdf8",
  "Stage 6 · Mountains": "#f472b6",
  "Stage 7 · Phalanx's Fortress": "#f87171",
  "Demon's Hideout": "#fb923c",
  "Town & Interiors": "#4ade80",
  "Overworld Map": "#94a3b8",
  "Special & Crypts": "#cbd5e1",
};

const STAGE_ORDER = [
  "Stage 1 · Murkland",
  "Stage 2 · Ruined City & Town",
  "Stage 3 · Dark Forest",
  "Stage 4 · Towers of Doom",
  "Stage 5 · Poseidonia",
  "Stage 6 · Mountains",
  "Stage 7 · Phalanx's Fortress",
  "Demon's Hideout",
  "Town & Interiors",
  "Overworld Map",
  "Special & Crypts",
];

export class CampaignView {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    this.arg = arg;
    this.data = null;
    this.selectedArea = arg ? Number(arg) : 0;
    this.stageFilter = "all";
    this.query = "";
    this.onlyIssues = false;
    this.viewMode = "graph"; // "graph" | "table" | "issues"

    // Canvas graph viewport
    this.camX = 0;
    this.camY = 0;
    this.zoom = 1;
    this.isPanning = false;
    this.panStart = { x: 0, y: 0 };
    this.nodeLayouts = new Map(); // area -> { x, y, w, h }
    this.stageBounds = []; // stage rectangles for the graph background
    this.viewW = 0;
    this.viewH = 0;
    this.resizeObserver = null;
    this.needsFit = true;
    this.needsFocus = true;
  }

  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    await this.reload();
  }

  destroy() {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.el?.remove();
  }

  isDirty() {
    return false;
  }

  buildDom() {
    this.search = h("input", {
      type: "search",
      placeholder: "Search area, name or target…",
      oninput: () => {
        this.query = this.search.value.trim().toLowerCase();
        this.renderCurrentView();
      },
    });

    this.stageSelect = h("select", {
      onchange: () => {
        this.stageFilter = this.stageSelect.value;
        this.layoutGraphNodes();
        const stage = this.data?.stages?.find((s) => s.name === this.stageFilter);
        if (stage && !stage.areas.includes(this.selectedArea)) {
          this.selectedArea = stage.areas[0] ?? this.selectedArea;
        }
        this.needsFocus = true;
        this.needsFit = false;
        this.renderCurrentView();
        this.renderDetail();
      },
    }, h("option", { value: "all", text: "All stages" }));

    this.modeSelect = h("select", {
      onchange: () => {
        this.viewMode = this.modeSelect.value;
        this.renderCurrentView();
      },
    },
      h("option", { value: "graph", text: "Visual Graph" }),
      h("option", { value: "table", text: "Room Table" }),
      h("option", { value: "issues", text: "Navigation Issues" })
    );

    this.issuesOnlyBtn = h("button", {
      class: "btn small",
      type: "button",
      text: "Issues only",
      onclick: () => {
        this.onlyIssues = !this.onlyIssues;
        this.issuesOnlyBtn.classList.toggle("active", this.onlyIssues);
        this.renderCurrentView();
      },
    });

    this.stats = h("div", { class: "stat-grid" });
    this.mainArea = h("div", { class: "campaign-main-area" });
    this.detailPanel = h("div", { class: "campaign-detail-panel" });

    this.el = h("div", { class: "assets-view campaign-view" },
      h("div", { class: "asset-toolbar" },
        icon("compass"),
        h("span", { class: "toolbar-title", text: "Campaign & World Navigator" }),
        this.search,
        this.stageSelect,
        this.modeSelect,
        this.issuesOnlyBtn,
        h("button", {
          class: "btn small",
          type: "button",
          text: "Refresh",
          onclick: () => this.reload(),
        }, icon("refresh")),
        h("span", { class: "grow" }),
        h("span", { id: "campaign-status-label", class: "asset-count", text: "Loading…" })
      ),
      this.stats,
      h("div", { class: "campaign-content-split" },
        this.mainArea,
        this.detailPanel
      )
    );
  }

  async reload() {
    try {
      this.data = await api.campaign();
      this.syncStageOptions();
      this.renderStats();
      this.layoutGraphNodes();
      this.needsFocus = true;
      this.needsFit = false;
      this.renderCurrentView();
      this.renderDetail();
      const statusLbl = this.el.querySelector("#campaign-status-label");
      if (statusLbl) {
        statusLbl.textContent = `${this.data.stats.total_rooms} rooms · ${this.data.stats.total_doors} doors · ${this.data.stats.total_gates} gates`;
      }
    } catch (err) {
      toast(`Failed to load campaign: ${err.message}`, { level: "error" });
    }
  }

  syncStageOptions() {
    clear(this.stageSelect);
    this.stageSelect.appendChild(h("option", { value: "all", text: "All stages" }));
    for (const stage of this.orderedStages()) {
      this.stageSelect.appendChild(h("option", {
        value: stage.name,
        text: `${stage.name} (${stage.areas.length})`,
        selected: this.stageFilter === stage.name,
      }));
    }
  }

  orderedStages() {
    const order = new Map(STAGE_ORDER.map((name, i) => [name, i]));
    return [...(this.data?.stages || [])].sort(
      (a, b) => (order.get(a.name) ?? 99) - (order.get(b.name) ?? 99));
  }

  renderStats() {
    if (!this.data) return;
    const s = this.data.stats;
    clear(this.stats);
    const statCard = (num, label, subtitle = "", onClick = null, isWarn = false) => {
      const card = h("div", {
        class: `stat-card ${onClick ? "clickable" : ""} ${isWarn && num > 0 ? "warn-card" : ""}`,
        onclick: onClick,
      },
        h("div", { class: "stat-value", text: String(num) }),
        h("div", { class: "stat-label", text: label }),
        subtitle ? h("div", { class: "stat-sub", text: subtitle }) : null
      );
      return card;
    };

    this.stats.append(
      statCard(s.total_rooms, "Rooms", `${s.authored_rooms} authored`),
      statCard(s.total_doors, "Doors", "Transitions between rooms"),
      statCard(s.total_gates, "Boss Gates", "Post-boss area unlocks"),
      statCard(s.dead_ends, "Dead Ends", "No exit or gate", () => {
        this.viewMode = "issues";
        this.modeSelect.value = "issues";
        this.renderCurrentView();
      }, s.dead_ends > 0),
      statCard(s.broken_doors + s.invalid_spawns, "Broken Links", `${s.broken_doors} broken, ${s.invalid_spawns} bad spawn`, () => {
        this.viewMode = "issues";
        this.modeSelect.value = "issues";
        this.renderCurrentView();
      }, (s.broken_doors + s.invalid_spawns) > 0)
    );
  }

  layoutGraphNodes() {
    if (!this.data) return;
    this.nodeLayouts.clear();
    this.stageBounds = [];
    const stages = this.orderedStages();
    const nodeWidth = 140;
    const nodeHeight = 54;
    const colGap = 200;
    const rowGap = 70;

    let colIdx = 0;
    for (const st of stages) {
      if (this.stageFilter !== "all" && st.name !== this.stageFilter) continue;
      const areas = st.areas || [];
      const colsInStage = Math.max(1, Math.ceil(areas.length / 10));
      const startCol = colIdx;
      for (let i = 0; i < areas.length; i++) {
        const area = areas[i];
        const subCol = i % colsInStage;
        const row = Math.floor(i / colsInStage);
        const x = (startCol + subCol) * colGap + 60;
        const y = row * rowGap + 60;
        this.nodeLayouts.set(area, { x, y, w: nodeWidth, h: nodeHeight });
      }
      const rows = Math.ceil(areas.length / colsInStage);
      const x0 = startCol * colGap + 40;
      const x1 = (startCol + colsInStage - 1) * colGap + 60 + nodeWidth + 20;
      this.stageBounds.push({
        name: st.name,
        x: x0,
        y: 16,
        w: x1 - x0,
        h: rows * rowGap + 58,
        color: STAGE_COLORS[st.name] || "#94a3b8",
      });
      colIdx += colsInStage + 0.5;
    }
  }

  renderCurrentView() {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    clear(this.mainArea);
    if (!this.data) return;

    if (this.viewMode === "graph") {
      this.renderGraphView();
    } else if (this.viewMode === "table") {
      this.renderTableView();
    } else {
      this.renderIssuesView();
    }
  }

  renderGraphView() {
    const canvasWrap = h("div", { class: "campaign-canvas-wrap" });
    const canvas = h("canvas", { class: "campaign-graph-canvas" });
    canvasWrap.appendChild(canvas);
    canvasWrap.appendChild(h("div", {
      class: "campaign-hint",
      text: "Drag to pan · Wheel to zoom · Double-click a room to open",
    }));

    const controls = h("div", { class: "graph-controls" },
      h("button", {
        class: "btn small", type: "button", text: "+",
        onclick: () => { this.zoom = Math.min(3, this.zoom * 1.25); draw(); }
      }),
      h("button", {
        class: "btn small", type: "button", text: "-",
        onclick: () => { this.zoom = Math.max(0.2, this.zoom / 1.25); draw(); }
      }),
      h("button", {
        class: "btn small", type: "button", text: "Reset View",
        onclick: () => { this.zoom = 1; this.camX = 0; this.camY = 0; draw(); }
      }),
      h("button", {
        class: "btn small", type: "button", text: "Fit",
        onclick: () => { this.needsFit = false; this.needsFocus = false; fitView(); }
      })
    );
    canvasWrap.appendChild(controls);

    this.mainArea.appendChild(canvasWrap);

    const ctx = canvas.getContext("2d");

    const resize = () => {
      const rect = canvasWrap.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      if (width < 2 || height < 2) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      this.viewW = width;
      this.viewH = height;
      if (this.needsFocus) {
        this.needsFocus = false;
        if (!focusArea(this.selectedArea)) fitView(false);
      } else if (this.needsFit) {
        this.needsFit = false;
        fitView(false);
      }
      draw();
    };

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);

      // Background grid
      ctx.fillStyle = "#12141a";
      ctx.fillRect(0, 0, w, h);

      ctx.save();
      ctx.translate(w / 2 + this.camX, h / 2 + this.camY);
      ctx.scale(this.zoom, this.zoom);
      const overview = this.zoom < 0.42;

      // Stage group bands.
      for (const stage of this.stageBounds) {
        ctx.save();
        ctx.globalAlpha = 0.07;
        ctx.fillStyle = stage.color;
        ctx.beginPath();
        ctx.roundRect(stage.x, stage.y, stage.w, stage.h, 8);
        ctx.fill();
        ctx.globalAlpha = 0.35;
        ctx.strokeStyle = stage.color;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
        if (this.zoom >= 0.35) {
          ctx.fillStyle = stage.color;
          ctx.font = "bold 11px system-ui, sans-serif";
          ctx.fillText(stage.name, stage.x + 10, stage.y + 16);
        }
      }

      // Draw Edges
      const seenEdges = new Set();
      for (const edge of this.data.edges || []) {
        const key = `${edge.from}:${edge.to}:${edge.kind}:${edge.spawn_id ?? ""}:${edge.x ?? ""}:${edge.y ?? ""}`;
        if (seenEdges.has(key)) continue;
        seenEdges.add(key);
        if (overview && edge.kind === "door") continue;
        const fromLayout = this.nodeLayouts.get(edge.from);
        const toLayout = this.nodeLayouts.get(edge.to);
        if (!fromLayout || !toLayout) continue;

        const isDoor = edge.kind === "door";
        const isSelected = edge.from === this.selectedArea || edge.to === this.selectedArea;

        ctx.strokeStyle = isSelected
          ? (isDoor ? "#4ade80" : "#fbbf24")
          : (isDoor ? "rgba(74, 222, 128, 0.13)" : "rgba(251, 191, 36, 0.10)");
        ctx.lineWidth = isSelected ? 2.5 : 0.9;

        const startX = fromLayout.x + fromLayout.w;
        const startY = fromLayout.y + fromLayout.h / 2;
        const endX = toLayout.x;
        const endY = toLayout.y + toLayout.h / 2;

        ctx.beginPath();
        const cpX = (startX + endX) / 2;
        ctx.moveTo(startX, startY);
        ctx.bezierCurveTo(cpX, startY, cpX, endY, endX, endY);
        ctx.stroke();

        // Arrow head
        if (!isSelected) continue;
        const arrowSize = 6;
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(endX - arrowSize * 1.5, endY - arrowSize);
        ctx.lineTo(endX - arrowSize * 1.5, endY + arrowSize);
        ctx.closePath();
        ctx.fill();
      }

      // Draw Nodes
      for (const [area, layout] of this.nodeLayouts.entries()) {
        const node = this.data.nodes[area];
        if (!node) continue;

        if (this.query && !this.nodeMatches(node, this.query)) continue;
        if (this.onlyIssues && !this.nodeHasIssues(node)) continue;

        const isSelected = area === this.selectedArea;
        const stageColor = STAGE_COLORS[node.stage] || "#94a3b8";

        // Card background
        ctx.globalAlpha = overview ? 0.62 : 1;
        ctx.fillStyle = overview ? stageColor : (isSelected ? "#222634" : "#181b24");
        ctx.strokeStyle = isSelected ? "#e0a13c" : (overview ? stageColor : "#2a2e3d");
        ctx.lineWidth = isSelected ? 2.5 : 1;

        ctx.beginPath();
        ctx.roundRect(layout.x, layout.y, layout.w, layout.h, 6);
        ctx.fill();
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Stage color stripe
        ctx.fillStyle = stageColor;
        ctx.fillRect(layout.x, layout.y, 4, layout.h);

        // Header: Area ID + badges (only when readable).
        if (this.zoom >= 0.28) {
          ctx.font = "bold 11px system-ui, sans-serif";
          ctx.fillStyle = isSelected ? "#f3f4f6" : "#d1d5db";
          ctx.fillText(`Area ${area}`, layout.x + 10, layout.y + 16);
        }

        if (this.zoom >= 0.45) {
          if (node.authored) {
            ctx.font = "9px system-ui, sans-serif";
            ctx.fillStyle = "#38bdf8";
            ctx.fillText("AUTH", layout.x + layout.w - 32, layout.y + 15);
          }

          ctx.font = "10px system-ui, sans-serif";
          ctx.fillStyle = "#9ca3af";
          const exits = this.uniqueEdges(node.outbound).length;
          const enters = this.uniqueEdges(node.inbound).length;
          ctx.fillText(`${exits} out · ${enters} in`, layout.x + 10, layout.y + 32);

          const noGate = node.gate_next_area === null
            || node.gate_next_area === undefined
            || node.gate_next_area < 0;
          if (node.transitions_count === 0 && noGate) {
            ctx.fillStyle = "#f87171";
            ctx.fillText("DEAD END", layout.x + 10, layout.y + 46);
          } else if (!noGate) {
            ctx.fillStyle = "#fbbf24";
            ctx.fillText(`Gate → ${node.gate_next_area}`, layout.x + 10, layout.y + 46);
          }
        }

        if (this.nodeHasIssues(node)) {
          ctx.fillStyle = "#ef4444";
          ctx.beginPath();
          ctx.arc(layout.x + layout.w - 8, layout.y + 8, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.restore();
      ctx.restore();
    };

    const fitView = (redraw = true) => {
      if (!this.viewW || !this.viewH) return;
      const visible = [];
      for (const [area, layout] of this.nodeLayouts.entries()) {
        const node = this.data.nodes[area];
        if (!node) continue;
        if (this.query && !this.nodeMatches(node, this.query)) continue;
        if (this.onlyIssues && !this.nodeHasIssues(node)) continue;
        visible.push(layout);
      }
      if (!visible.length) return;
      const bounds = (!this.query && !this.onlyIssues && this.stageBounds.length)
        ? this.stageBounds : visible;
      const minX = Math.min(...bounds.map((l) => l.x)) - 20;
      const minY = Math.min(...bounds.map((l) => l.y)) - 20;
      const maxX = Math.max(...bounds.map((l) => l.x + l.w)) + 20;
      const maxY = Math.max(...bounds.map((l) => l.y + l.h)) + 20;
      const z = Math.min((this.viewW - 40) / Math.max(1, maxX - minX),
                         (this.viewH - 40) / Math.max(1, maxY - minY), 1.2);
      this.zoom = Math.max(0.12, Math.min(1.2, z));
      this.camX = -((minX + maxX) / 2) * this.zoom;
      this.camY = -((minY + maxY) / 2) * this.zoom;
      if (redraw) draw();
    };

    const focusArea = (area) => {
      const layout = this.nodeLayouts.get(area);
      if (!layout) return false;
      this.zoom = 0.85;
      const halfW = this.viewW / (2 * this.zoom);
      const halfH = this.viewH / (2 * this.zoom);
      const bounds = this.stageBounds.length
        ? this.stageBounds : [...this.nodeLayouts.values()];
      const minX = Math.min(...bounds.map((b) => b.x)) - 10;
      const minY = Math.min(...bounds.map((b) => b.y)) - 10;
      const maxX = Math.max(...bounds.map((b) => b.x + b.w)) + 10;
      const maxY = Math.max(...bounds.map((b) => b.y + b.h)) + 10;
      let cx = layout.x + layout.w / 2;
      let cy = layout.y + layout.h / 2;
      cx = (maxX - minX <= halfW * 2)
        ? (minX + maxX) / 2
        : Math.max(minX + halfW, Math.min(maxX - halfW, cx));
      cy = (maxY - minY <= halfH * 2)
        ? (minY + maxY) / 2
        : Math.max(minY + halfH, Math.min(maxY - halfH, cy));
      this.camX = -cx * this.zoom;
      this.camY = -cy * this.zoom;
      return true;
    };

    const pickArea = (e) => {
      const rect = canvas.getBoundingClientRect();
      const worldX = (e.clientX - rect.left - (rect.width / 2 + this.camX)) / this.zoom;
      const worldY = (e.clientY - rect.top - (rect.height / 2 + this.camY)) / this.zoom;
      for (const [area, layout] of this.nodeLayouts.entries()) {
        if (worldX >= layout.x && worldX <= layout.x + layout.w &&
            worldY >= layout.y && worldY <= layout.y + layout.h) {
          return area;
        }
      }
      return null;
    };

    // Canvas interactivity
    canvas.onpointerdown = (e) => {
      if (e.button !== 0) return;
      this.isPanning = true;
      this.panStart = { x: e.clientX, y: e.clientY };
      canvas.setPointerCapture(e.pointerId);
    };

    canvas.onpointermove = (e) => {
      if (!this.isPanning) return;
      this.camX += (e.clientX - this.panStart.x);
      this.camY += (e.clientY - this.panStart.y);
      this.panStart = { x: e.clientX, y: e.clientY };
      draw();
    };

    canvas.onpointerup = (e) => {
      if (!this.isPanning) return;
      this.isPanning = false;
      try { canvas.releasePointerCapture(e.pointerId); } catch { /* released */ }

      const area = pickArea(e);
      if (area !== null) {
        this.selectedArea = area;
        this.renderDetail();
        draw();
      }
    };

    canvas.ondblclick = (e) => {
      const area = pickArea(e);
      if (area !== null) this.app.navigate(`#map/${area}`);
    };

    canvas.onwheel = (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      this.zoom = Math.max(0.12, Math.min(3.5, this.zoom * delta));
      draw();
    };

    this.resizeObserver?.disconnect();
    this.resizeObserver = new ResizeObserver(() => resize());
    this.resizeObserver.observe(canvasWrap);
    resize();
  }

  renderTableView() {
    const table = h("table", { class: "coverage-table campaign-table" },
      h("thead", null,
        h("tr", null,
          h("th", { text: "Area" }),
          h("th", { text: "Stage" }),
          h("th", { text: "Label / Name" }),
          h("th", { text: "World Size" }),
          h("th", { text: "Exits" }),
          h("th", { text: "Entrances" }),
          h("th", { text: "Boss Gate" }),
          h("th", { text: "Spawns" }),
          h("th", { text: "Status" }),
          h("th", { text: "Action" })
        )
      )
    );

    const tbody = h("tbody");
    const areas = Object.keys(this.data.nodes).map(Number).sort((a, b) => a - b);

    for (const area of areas) {
      const node = this.data.nodes[area];
      if (this.stageFilter !== "all" && node.stage !== this.stageFilter) continue;
      if (this.query && !this.nodeMatches(node, this.query)) continue;
      if (this.onlyIssues && !this.nodeHasIssues(node)) continue;

      const isDeadEnd = node.transitions_count === 0 &&
        (node.gate_next_area === null || node.gate_next_area === undefined || node.gate_next_area < 0);
      const isSelected = area === this.selectedArea;
      const exits = this.uniqueEdges(node.outbound).length;
      const enters = this.uniqueEdges(node.inbound).length;

      const tr = h("tr", {
        class: `${isSelected ? "selected-row" : ""} clickable`,
        onclick: () => {
          this.selectedArea = area;
          this.renderDetail();
          this.renderCurrentView();
        },
      },
        h("td", null, h("span", { class: "mono", text: String(area) })),
        h("td", null, h("span", { class: "badge", style: { borderColor: STAGE_COLORS[node.stage] || "#64748b" }, text: node.stage })),
        h("td", null, h("strong", { text: node.label })),
        h("td", null, `${node.world_w}×${node.world_h}`),
        h("td", null, String(exits)),
        h("td", null, String(enters)),
        h("td", null, node.gate_next_area >= 0 ? `→ Area ${node.gate_next_area}` : "—"),
        h("td", null, String(node.spawns.length)),
        h("td", null,
          isDeadEnd ? h("span", { class: "status-pill fail", text: "Dead End" })
          : node.authored ? h("span", { class: "status-pill warn", text: "Authored" })
          : h("span", { class: "status-pill pass", text: "Generated" })
        ),
        h("td", null,
          h("button", {
            class: "btn small",
            type: "button",
            text: "Edit map",
            onclick: (e) => {
              e.stopPropagation();
              this.app.navigate(`#map/${area}`);
            },
          })
        )
      );
      tbody.appendChild(tr);
    }

    table.appendChild(tbody);
    this.mainArea.appendChild(table);
  }

  renderIssuesView() {
    const issues = this.data.issues || {};
    const wrap = h("div", { class: "campaign-issues-wrap" });

    const section = (title, items, renderItem) => {
      if (!items || !items.length) return null;
      const box = h("div", { class: "issue-section" },
        h("h3", { text: `${title} (${items.length})` })
      );
      for (const item of items) {
        box.appendChild(renderItem(item));
      }
      return box;
    };

    // Broken doors
    const brokenSec = section("Broken Transitions (Target room does not exist)", issues.broken_doors, (item) => {
      return h("div", { class: "issue-card danger" },
        h("div", { class: "issue-title", text: `Area ${item.from} (${item.from_label})` },
          h("span", { class: "badge fail", text: `Target Area ${item.target_area} not found` })
        ),
        h("div", { class: "issue-desc", text: `Door trigger at (${item.x}, ${item.y}) points to non-existent area ${item.target_area}.` }),
        h("div", { class: "issue-actions" },
          h("button", {
            class: "btn small",
            type: "button",
            text: "Open in Map Builder",
            onclick: () => this.app.navigate(`#map/${item.from}`),
          })
        )
      );
    });

    // Invalid spawns
    const spawnSec = section("Invalid Destination Spawns (Target area lacks spawn_id)", issues.invalid_spawns, (item) => {
      return h("div", { class: "issue-card warn" },
        h("div", { class: "issue-title", text: `Area ${item.from} → Area ${item.to}` },
          h("span", { class: "badge warn", text: `Spawn ${item.spawn_id} out of bounds` })
        ),
        h("div", { class: "issue-desc", text: `Door targets spawn_id=${item.spawn_id}, but Area ${item.to} only has ${item.target_spawn_count} spawn(s).` }),
        h("div", { class: "issue-actions" },
          h("button", {
            class: "btn small",
            type: "button",
            text: "Open source room",
            onclick: () => this.app.navigate(`#map/${item.from}`),
          }),
          h("button", {
            class: "btn small",
            type: "button",
            text: "Open target room",
            onclick: () => this.app.navigate(`#map/${item.to}`),
          })
        )
      );
    });

    // Dead ends
    const deadEndSec = section("Dead Ends (Rooms with no exit and no boss gate)", issues.dead_ends, (item) => {
      return h("div", { class: "issue-card" },
        h("div", { class: "issue-title", text: `Area ${item.area}: ${item.label}` },
          h("span", { class: "badge", text: item.stage })
        ),
        h("div", { class: "issue-desc", text: "This room has 0 outgoing transitions and no boss gate. Verify if it requires an exit door or return path." }),
        h("div", { class: "issue-actions" },
          h("button", {
            class: "btn small",
            type: "button",
            text: "Open in Map Builder",
            onclick: () => this.app.navigate(`#map/${item.area}`),
          })
        )
      );
    });

    if (brokenSec) wrap.appendChild(brokenSec);
    if (spawnSec) wrap.appendChild(spawnSec);
    if (deadEndSec) wrap.appendChild(deadEndSec);

    if (!wrap.children.length) {
      wrap.appendChild(h("div", { class: "panel-empty", text: "No navigation issues found!" }));
    }

    this.mainArea.appendChild(wrap);
  }

  renderDetail() {
    clear(this.detailPanel);
    if (!this.data) return;

    const node = this.data.nodes[this.selectedArea];
    if (!node) {
      this.detailPanel.appendChild(h("div", { class: "panel-empty", text: "Select a room to view details." }));
      return;
    }

    const titleBox = h("div", { class: "detail-header" },
      h("h3", { text: `Area ${node.area}` }),
      h("div", { class: "detail-sub", text: node.label }),
      h("div", { class: "row wrap", style: { marginTop: "8px" } },
        h("span", { class: `status-pill ${node.authored ? "warn" : "pass"}`, text: node.source }),
        h("span", { class: "badge", text: node.stage }),
        h("span", { class: "badge", text: `Music: ${node.music_name}` })
      )
    );

    const openBtn = h("button", {
      class: "btn primary full-width",
      type: "button",
      text: "Open in Map Builder",
      onclick: () => this.app.navigate(`#map/${node.area}`),
    });

    // Exits list
    const exits = this.uniqueEdges(node.outbound);
    const exitsBox = h("div", { class: "detail-section" },
      h("h4", { text: `Exits (${exits.length})` })
    );

    if (exits.length) {
      for (const edge of exits) {
        const isGate = edge.kind === "gate";
        const row = h("div", { class: "transition-chip" },
          h("div", null,
            h("strong", { text: isGate ? `Boss Gate → Area ${edge.target}` : `Door → Area ${edge.target}` }),
            h("div", { class: "meta", text: isGate ? "Triggered after defeating boss" : `Target spawn: ${edge.spawn_id} · pad_mask: ${edge.pad_mask}` })
          ),
          h("button", {
            class: "btn tiny",
            type: "button",
            text: "Inspect",
            onclick: () => {
              this.selectedArea = edge.target;
              this.renderDetail();
              this.renderCurrentView();
            },
          })
        );
        exitsBox.appendChild(row);
      }
    } else {
      exitsBox.appendChild(h("div", { class: "meta-empty", text: "No outgoing transitions." }));
    }

    // Entrances list
    const entrances = this.uniqueEdges(node.inbound);
    const inBox = h("div", { class: "detail-section" },
      h("h4", { text: `Entrances (${entrances.length})` })
    );

    if (entrances.length) {
      for (const edge of entrances) {
        const isEntry = edge.from === -1;
        const row = h("div", { class: "transition-chip" },
          h("div", null,
            h("strong", { text: isEntry ? "Overworld Stage Entry" : `From Area ${edge.from}` }),
            h("div", { class: "meta", text: isEntry ? "Accessible from Mode 7 Overworld" : `via ${edge.kind}` })
          ),
          isEntry ? null : h("button", {
            class: "btn tiny",
            type: "button",
            text: "Inspect",
            onclick: () => {
              this.selectedArea = edge.from;
              this.renderDetail();
              this.renderCurrentView();
            },
          })
        );
        inBox.appendChild(row);
      }
    } else {
      inBox.appendChild(h("div", { class: "meta-empty", text: "No incoming transitions." }));
    }

    // Spawns list
    const spawnsBox = h("div", { class: "detail-section" },
      h("h4", { text: `Spawns (${node.spawns.length})` })
    );

    for (const sp of node.spawns) {
      spawnsBox.appendChild(h("div", { class: "spawn-row" },
        h("span", { class: "mono", text: `Spawn #${sp.id}` }),
        h("span", { text: `(${sp.x}, ${sp.y})` })
      ));
    }

    this.detailPanel.append(
      titleBox,
      openBtn,
      exitsBox,
      inBox,
      spawnsBox
    );
  }

  nodeMatches(node, query) {
    if (!query) return true;
    const str = `${node.area} ${node.label} ${node.name} ${node.stage} ${node.music_name}`.toLowerCase();
    return query.split(/\s+/).every((token) => str.includes(token));
  }

  uniqueEdges(list) {
    const seen = new Set();
    const out = [];
    for (const edge of list || []) {
      const target = edge.target ?? edge.from;
      const key = `${edge.kind}:${target}:${edge.spawn_id ?? ""}:${edge.pad_mask ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(edge);
    }
    return out;
  }

  nodeHasIssues(node) {
    const noGate = node.gate_next_area === null
      || node.gate_next_area === undefined
      || node.gate_next_area < 0;
    if (node.transitions_count === 0 && noGate) return true;
    for (const b of this.data.issues?.broken_doors || []) {
      if (b.from === node.area) return true;
    }
    for (const s of this.data.issues?.invalid_spawns || []) {
      if (s.from === node.area || s.to === node.area) return true;
    }
    return false;
  }
}
