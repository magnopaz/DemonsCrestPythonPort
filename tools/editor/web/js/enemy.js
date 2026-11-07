/* Enemy Editor: species animations, states, stats, attack patterns and
   sounds. Animation edits go to assets/authored/species_anim.json; the rest
   goes to assets/authored/enemies.json. Images are loaded, never painted. */

import { api } from "./api.js";
import {
  h, clear, fitCanvas, getImage, loadImage, clamp,
  padHex, speciesHex, readFileDataURL, deepClone,
} from "./util.js";
import { icon } from "./icons.js";
import {
  toast, showModal, confirmDialog, showSpeciesPicker, issueList, playAudio,
  stopAudio, speciesThumb,
} from "./ui.js";

const FRAME_MS = 1000 / 60;
const NATIVE_SPECIES = new Set([
  0x2c, 0x07, 0x67, 0x13, 0x09, 0x33, 0x86, 0x8d, 0xa5, 0xbc, 0x34,
]);
const NATIVE_BOSS_SPECIES = new Set([
  0x09, 0x13, 0x33, 0x58, 0x68, 0x69, 0x6b, 0x6c, 0x6f, 0x7b, 0x7c,
  0x82, 0x86, 0x8d, 0xa5, 0xbc, 0x16, 0x17, 0x18,
]);

const TAB_DEFS = [
  ["frames", "Frames"],
  ["animation", "Animation"],
  ["stats", "Stats"],
  ["attacks", "Attacks"],
  ["sounds", "Sounds"],
];

function defaultDefinition(name = "") {
  return {
    name,
    status: {
      hp: 2, contact_damage: 1, defense: 0, invulnerable: false,
    },
    movement: {
      ai: "walker", speed: 0.5, range: 160, bob: 0, gravity: true,
      override_ai: false,
    },
    attacks: [],
    sounds: {},
  };
}

function withDefaults(definition) {
  const base = defaultDefinition(definition?.name || "");
  if (!definition) return base;
  return {
    ...base,
    ...definition,
    status: { ...base.status, ...(definition.status || {}) },
    movement: { ...base.movement, ...(definition.movement || {}) },
    attacks: Array.isArray(definition.attacks) ? definition.attacks : [],
    sounds: { ...(definition.sounds || {}) },
  };
}

function textureFromAsset(asset) {
  if (!asset) return "";
  const path = asset.path || "";
  if (asset.source === "authored" && path.startsWith("assets/authored/")) {
    return path.slice("assets/authored/".length);
  }
  if (path.startsWith("assets/generated/")) {
    return path.slice("assets/generated/".length);
  }
  return asset.name;
}

function stripFrame(frame) {
  const out = {
    texture: frame.texture,
    anchor_x: Math.round(Number(frame.anchor_x) || 0),
    anchor_y: Math.round(Number(frame.anchor_y) || 0),
    duration: Math.max(1, Math.round(Number(frame.duration) || 6)),
  };
  if (frame.width) out.width = Math.round(frame.width);
  if (frame.height) out.height = Math.round(frame.height);
  return out;
}

export class EnemyEditor {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    const [routeKey, routeTab] = String(arg || "").split("/");
    this.key = routeKey && app.species.some((s) => s.key === routeKey)
      ? routeKey : app.species[0]?.key || null;
    this.initialTab = TAB_DEFS.some(([id]) => id === routeTab) ? routeTab : null;
    this.routeArg = this.key;
    this.entry = null;
    this.def = null;
    this.defDirty = false;
    this.source = "generated";
    this.dirty = false;
    this.frames = [];
    this.states = {};
    this.selectedFrame = 0;
    this.activeTab = "frames";
    this.play = true;
    this.sequenceKind = "all";
    this.playIndex = 0;
    this.playTimer = 0;
    this.flip = false;
    this.pickAnchor = false;
    this.testPatterns = false;
    this.sim = { projectiles: [], t: 0, cooldowns: [] };
    this.needsRender = true;
    this.raf = 0;
    this.destroyed = false;
    this._resizeObserver = null;
    this.search = "";
    this.filter = "all";
    this.lastTs = 0;
  }

  /* -------------------------------------------------------------- lifecycle */
  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    this.bindCanvas();
    this.bindKeys();
    this._resizeObserver = new ResizeObserver(() => { this.resizeCanvas(); this.invalidate(); });
    this._resizeObserver.observe(this.stageWrap);
    if (this.key) await this.loadSpecies(this.key);
    else this.renderEmpty();
    if (this.initialTab) this.setTab(this.initialTab);
    this.startLoop();
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this._resizeObserver?.disconnect();
    this.unbindKeys();
    stopAudio();
    this.el?.remove();
  }

  isDirty() { return this.dirty; }
  dirtyPromptKey() { return `#enemy/${this.key}`; }

  markDirty() {
    if (!this.dirty) {
      this.dirty = true;
      this.app.setSaveState("dirty", "Unsaved");
    }
    if (this.saveLabel) this.saveLabel.textContent = "Save *";
  }

  markClean() {
    this.dirty = false;
    this.app.setSaveState("saved", "Saved");
    if (this.saveLabel) this.saveLabel.textContent = "Save";
  }

  invalidate() { this.needsRender = true; }

  startLoop() {
    const loop = (ts) => {
      if (this.destroyed) return;
      const dt = this.lastTs ? Math.min(0.1, (ts - this.lastTs) / 1000) : 0;
      this.lastTs = ts;
      this.advance(dt);
      if (this.needsRender || this.play || this.testPatterns) {
        this.needsRender = false;
        try { this.draw(ts / 1000); } catch (error) { console.error(error); }
      }
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  /* ------------------------------------------------------------------- DOM */
  buildDom() {
    this.saveLabel = h("span", { text: "Save" });
    this.saveBtn = h("button", {
      class: "btn", type: "button", title: "Save (Ctrl+S)",
      onclick: () => this.save(),
    }, icon("save"), this.saveLabel);
    this.validateBadge = h("button", {
      class: "btn ghost small", type: "button", text: "Validate",
      onclick: () => this.validate(),
    });
    this.speciesSelect = h("select", {
      class: "room-select", onchange: () => {
        const key = this.speciesSelect.value;
        if (key && key !== this.key) this.confirmLoad(key);
      },
    });

    this.searchInput = h("input", {
      type: "search", placeholder: "Filter speciesâ€¦",
      style: { width: "100%" }, oninput: () => {
        this.search = this.searchInput.value.trim().toLowerCase();
        this.renderSpeciesList();
      },
    });
    this.filterBar = h("div", { class: "row wrap", style: { padding: "0 8px 6px" } });
    this.speciesList = h("div", { class: "enemy-list" });

    this.stageCanvas = h("canvas", { id: "enemy-stage" });
    this.stageWrap = h("div", { class: "stage-canvas-wrap" },
      this.stageCanvas,
      h("div", { class: "canvas-hud" },
        h("div", { class: "chip", id: "enemy-hud", text: "â€”" }),
      ),
    );

    this.playBtn = h("button", {
      class: "btn icon", type: "button", title: "Play / pause (Space)",
      onclick: () => this.togglePlay(),
    }, icon("pause"));
    this.seqSelect = h("select", {
      onchange: () => {
        this.sequenceKind = this.seqSelect.value;
        this.playIndex = 0; this.playTimer = 0;
      },
    });
    this.speedSelect = h("select", {
      onchange: () => { this.speed = Number(this.speedSelect.value) || 1; },
    },
    h("option", { value: "0.5", text: "0.5Ã—" }),
    h("option", { value: "1", selected: true, text: "1Ã—" }),
    h("option", { value: "2", text: "2Ã—" }),
    h("option", { value: "4", text: "4Ã—" }),
    );
    this.speed = 1;
    this.flipBtn = h("button", {
      class: "btn small", type: "button", text: "Flip",
      onclick: () => { this.flip = !this.flip; this.flipBtn.classList.toggle("active", this.flip); },
    });
    this.anchorBtn = h("button", {
      class: "btn small", type: "button", text: "Pick anchor",
      onclick: () => {
        this.pickAnchor = !this.pickAnchor;
        this.anchorBtn.classList.toggle("active", this.pickAnchor);
      },
    });
    this.testBtn = h("button", {
      class: "btn small", type: "button", text: "Test patterns",
      onclick: () => {
        this.testPatterns = !this.testPatterns;
        this.testBtn.classList.toggle("active", this.testPatterns);
        this.sim = { projectiles: [], t: 0, cooldowns: [] };
      },
    });
    this.stageToolbar = h("div", { class: "stage-toolbar" },
      this.playBtn,
      h("span", { class: "tiny muted", text: "Sequence" }), this.seqSelect,
      h("span", { class: "tiny muted", text: "Speed" }), this.speedSelect,
      this.flipBtn, this.anchorBtn, this.testBtn,
      h("span", { class: "grow" }),
      h("button", {
        class: "btn small", type: "button", text: "Add frame",
        onclick: () => this.showAddFrameMenu(),
      }, icon("plus")),
    );

    this.frameStrip = h("div", { class: "frame-strip" });

    this.tabBar = h("div", { class: "tabs" });
    this.tabButtons = {};
    for (const [id, label] of TAB_DEFS) {
      const btn = h("button", {
        class: "tab-btn", type: "button", text: label,
        onclick: () => this.setTab(id),
      });
      this.tabButtons[id] = btn;
      this.tabBar.appendChild(btn);
    }
    this.tabBody = h("div", { class: "tab-body" });
    this.rightPanel = h("aside", { class: "panel right" },
      h("div", { class: "panel-head" }, icon("skull"),
        h("span", { text: "Species" })),
      this.tabBar,
      this.tabBody,
    );

    this.leftPanel = h("aside", { class: "panel left" },
      h("div", { class: "enemy-side-head" },
        h("span", { class: "toolbar-title", text: "Species" }),
        h("span", { class: "grow" }),
        h("button", {
          class: "btn small", type: "button", text: "New",
          onclick: () => this.showNewSpeciesDialog(),
        }, icon("plus")),
      ),
      h("div", { style: { padding: "0 8px 6px" } }, this.searchInput),
      this.filterBar,
      this.speciesList,
    );

    const toolbar = h("div", { class: "toolbar" },
      h("span", { class: "toolbar-title", text: "Enemy" }),
      this.speciesSelect,
      this.saveBtn,
      h("button", {
        class: "btn icon", type: "button", title: "Save options",
        onclick: () => this.showSaveMenu(),
      }, "â–¾"),
      h("button", {
        class: "btn icon", type: "button", title: "Reload species",
        onclick: () => this.reload(),
      }, icon("refresh")),
      h("button", {
        class: "btn icon", type: "button", title: "Undo frame edit (Ctrl+Z)",
        onclick: () => this.undo(),
      }, icon("undo")),
      h("button", {
        class: "btn icon", type: "button", title: "Redo frame edit (Ctrl+Y)",
        onclick: () => this.redo(),
      }, icon("redo")),
      h("div", { class: "sep" }),
      h("button", {
        class: "btn small", type: "button", text: "Upload frame",
        onclick: () => this.pickUpload(),
      }, icon("upload")),
      h("button", {
        class: "btn small", type: "button", text: "From asset",
        onclick: () => this.showAssetPicker(),
      }, icon("image")),
      h("span", { class: "grow" }),
      this.validateBadge,
    );

    this.el = h("div", { class: "editor enemy-editor" },
      toolbar,
      h("div", { class: "editor-body" },
        this.leftPanel,
        h("div", { class: "enemy-stage-wrap" },
          this.stageToolbar,
          this.stageWrap,
          this.frameStrip,
        ),
        this.rightPanel,
      ),
    );

    this.buildFilters();
    this.buildSeqSelect();
    this.renderSpeciesList();
    this.setTab("frames");
  }

  buildFilters() {
    clear(this.filterBar);
    const modes = [["all", "All"], ["enemy", "Enemies"], ["boss", "Bosses"],
      ["npc", "NPCs"], ["edited", "Edited"]];
    this.filterButtons = modes.map(([value, label]) => h("button", {
      class: `btn small${this.filter === value ? " active" : ""}`,
      type: "button", text: label,
      onclick: () => {
        this.filter = value;
        this.filterButtons.forEach((btn, i) => btn.classList.toggle("active",
          modes[i][0] === value));
        this.renderSpeciesList();
      },
    }));
    this.filterBar.append(...this.filterButtons);
  }

  renderSpeciesList() {
    if (!this.speciesList) return;
    clear(this.speciesList);
    clear(this.speciesSelect);
    const tokens = this.search.split(/\s+/).filter(Boolean);
    const list = this.app.species.filter((sp) => {
      if (this.filter === "edited" && sp.source !== "authored") return false;
      if (this.filter !== "all" && this.filter !== "edited" &&
        sp.kind !== this.filter) return false;
      if (!tokens.length) return true;
      const hay = `${sp.name} ${sp.key} ${sp.species} ${sp.species_hex}`.toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
    for (const sp of this.app.species) {
      this.speciesSelect.appendChild(h("option", {
        value: sp.key, selected: sp.key === this.key,
        text: `${sp.name} (${sp.species_hex}${sp.flags ? " f" + sp.flags : ""})`,
      }));
    }
    if (!list.length) {
      this.speciesList.appendChild(h("div", { class: "inspector-empty",
        text: "No species match." }));
      return;
    }
    for (const sp of list) {
      const row = h("div", {
        class: `enemy-row${sp.key === this.key ? " active" : ""}`,
        title: `${sp.name}\nkey ${sp.key} Â· species ${sp.species_hex}${sp.flags ? " Â· flags " + sp.flags : ""}`,
        onclick: () => { if (sp.key !== this.key) this.confirmLoad(sp.key); },
      },
      speciesThumb(sp, 36),
      h("div", { class: "meta" },
        h("div", { class: "n", text: sp.name }),
        h("div", { class: "s",
          text: `${sp.species_hex} Â· ${sp.frames}f${sp.kind === "boss" ? " Â· boss" : ""}${sp.source === "authored" ? " Â· edited" : ""}` }),
      ));
      this.speciesList.appendChild(row);
    }
  }

  buildSeqSelect() {
    clear(this.seqSelect);
    this.seqSelect.appendChild(h("option", { value: "all", text: "All frames" }));
    this.seqSelect.appendChild(h("option", { value: "default", text: "Default pose" }));
    for (let i = 0; i < 16; i += 1) {
      const label = this.entry?.state_names?.[String(i)];
      this.seqSelect.appendChild(h("option", {
        value: String(i), text: label ? `State ${i} Â· ${label}` : `State ${i}`,
      }));
    }
    this.seqSelect.value = this.sequenceKind;
  }

  /* ------------------------------------------------------------- data load */
  async confirmLoad(key) {
    if (this.dirty) {
      const ok = await confirmDialog("Discard unsaved changes?",
        "Loading another species will discard the current edits.",
        { okLabel: "Discard & load", danger: true });
      if (!ok) return;
    }
    await this.loadSpecies(key);
  }

  async loadSpecies(key) {
    this.app.setStatus(`Loading species ${key}â€¦`);
    const detail = await api.speciesDetail(key);
    this.key = key;
    this.routeArg = key;
    this.source = detail.source || "generated";
    this.entry = detail.entry;
    this.def = detail.definition ? withDefaults(detail.definition) : null;
    this.originalDef = detail.definition ? deepClone(detail.definition) : null;
    this.defDirty = false;
    this._undo = [];
    this._redo = [];
    this.frames = (this.entry.frames || []).map((frame) => ({ ...frame }));
    this.states = deepClone(this.entry.states || {});
    await Promise.all(this.frames.map((frame) =>
      frame.url ? loadImage(frame.url) : Promise.resolve(null)));
    this.selectedFrame = 0;
    this.playIndex = 0;
    this.playTimer = 0;
    this.sequenceKind = "all";
    this.buildSeqSelect();
    this.sim = { projectiles: [], t: 0, cooldowns: [] };
    this.dirty = false;
    this.markClean();
    history.replaceState(null, "", `#enemy/${key}`);
    this.speciesSelect.value = key;
    this.syncSummary();
    this.renderSpeciesList();
    this.renderFrameStrip();
    this.renderFramesTab();
    this.renderTab();
    this.updateHud();
    this.app.setStatus(`Enemy Editor Â· ${this.entryTitle()}`,
      `${this.frames.length} frames Â· ${this.source}${this.defDirty ? " Â· stats" : ""}`);
    this.invalidate();
  }

  syncSummary() {
    this.summary = this.app.species.find((s) => s.key === this.key) || {
      key: this.key, species: this.entry?.species || 0,
      species_hex: speciesHex(this.entry?.species || 0),
      name: this.def?.name || `Species ${(this.entry?.species || 0).toString(16)}`,
      kind: this.entry?.variant === "boss" ? "boss" : "enemy",
      flags: this.entry?.flags || 0, frames: this.frames.length,
      source: this.source, thumb: this.frames[0]?.url
        ? { url: this.frames[0].url } : null,
    };
  }

  entryTitle() {
    const sp = this.app.peakSpecies(this.key);
    return sp?.name || this.def?.name || `Species ${(this.entry?.species || 0).toString(16).toUpperCase()}`;
  }

  updateHud() {
    const el = document.getElementById("enemy-hud");
    if (!el) return;
    const sp = this.entry;
    el.innerHTML = `${this.entryTitle()} Â· <b>${this.frames.length} frames</b>` +
      ` Â· ${speciesHex(sp?.species || 0)} Â· key ${this.key}` +
      (this.play ? " Â· playing" : " Â· paused");
  }

  renderEmpty() {
    this.app.setStatus("Enemy Editor", "No species files found.");
    this.tabBody.appendChild(h("div", { class: "inspector-empty",
      text: "No species entries. Create one with the New button." }));
  }

  /* ------------------------------------------------------------- frame data */
  currentFrame() {
    return this.frames[this.selectedFrame] || null;
  }

  async ensureImage(frame) {
    if (!frame) return null;
    if (!frame.url) return null;
    const img = getImage(frame.url);
    if (img) return img;
    loadImage(frame.url).then(() => this.invalidate());
    return null;
  }

  sequenceFrames() {
    if (this.sequenceKind === "all") return this.frames.map((_, i) => i);
    if (this.sequenceKind === "default") {
      const d = this.entry?.default;
      return Number.isFinite(d) ? [d] : [0];
    }
    const state = this.states[this.sequenceKind];
    if (Array.isArray(state) && state.length) return state;
    return this.frames.map((_, i) => i);
  }

  advance(dt) {
    if (this.play && this.frames.length) {
      const seq = this.sequenceFrames();
      if (seq.length) {
        if (this.playIndex >= seq.length) this.playIndex = 0;
        const frameIndex = seq[this.playIndex] ?? 0;
        const frame = this.frames[frameIndex] || this.frames[0];
        const ms = Math.max(1, Number(frame.duration) || 6) * FRAME_MS;
        this.playTimer += dt * 1000 * (this.speed || 1);
        if (this.playTimer >= ms) {
          this.playTimer = 0;
          this.playIndex = (this.playIndex + 1) % seq.length;
          this.highlightPlayingFrame();
          this.needsRender = true;
        }
      }
    }
    if (this.testPatterns) this.advanceSim(dt);
  }

  displayedFrame() {
    if (this.play) {
      const seq = this.sequenceFrames();
      if (!seq.length) return this.currentFrame();
      return this.frames[seq[this.playIndex] ?? 0] || this.currentFrame();
    }
    return this.currentFrame();
  }

  /* ------------------------------------------------------------------ stage */
  bindCanvas() {
    this.stageCanvas.addEventListener("contextmenu", (e) => e.preventDefault());
    this.stageCanvas.addEventListener("pointerdown", (event) => {
      if (!this.pickAnchor || !this.frames.length) return;
      const frame = this.displayedFrame();
      if (!frame) return;
      const rect = this.stageCanvas.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;
      const t = this.stageTransform;
      if (!t) return;
      let ax = Math.round((sx - t.ox) / t.scale);
      let ay = Math.round((sy - t.oy) / t.scale);
      if (this.flip) ax = Math.round(t.width - ax);
      ax = clamp(ax, -16, t.width + 16);
      ay = clamp(ay, -16, t.height + 16);
      frame.anchor_x = ax;
      frame.anchor_y = ay;
      this.markDirty();
      this.renderFramesTab();
      this.invalidate();
      toast(`Anchor set to ${ax},${ay}`, "ok", 1200);
    });
  }

  resizeCanvas() {
    if (!this.stageCanvas) return;
    const size = fitCanvas(this.stageCanvas);
    this.canvasSize = size;
    this.dpr = size.dpr;
    this.cssW = size.width / size.dpr;
    this.cssH = size.height / size.dpr;
    this.invalidate();
  }

  draw(now) {
    if (!this.stageCanvas || !this.frames.length) {
      if (this.stageCanvas) {
        const ctx = this.stageCanvas.getContext("2d");
        const dpr = this.dpr || 1;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = "#07080b";
        ctx.fillRect(0, 0, this.cssW || 100, this.cssH || 100);
      }
      return;
    }
    const ctx = this.stageCanvas.getContext("2d");
    const dpr = this.dpr || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const W = this.cssW || 600;
    const H = this.cssH || 400;
    // Background.
    const grad = ctx.createRadialGradient(W * 0.42, H * 0.56, 20,
      W * 0.42, H * 0.56, Math.max(W, H) * 0.7);
    grad.addColorStop(0, "#181c26");
    grad.addColorStop(1, "#07080b");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
    // Checker floor.
    const floorY = Math.round(H * 0.78);
    ctx.fillStyle = "#0b0d12";
    ctx.fillRect(0, floorY, W, H - floorY);
    ctx.strokeStyle = "#222736";
    ctx.lineWidth = 1;
    for (let y = floorY; y < H; y += 16) {
      ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(W, y + 0.5); ctx.stroke();
    }
    for (let x = 0; x < W; x += 16) {
      ctx.beginPath(); ctx.moveTo(x + 0.5, floorY); ctx.lineTo(x + 0.5, H); ctx.stroke();
    }
    ctx.strokeStyle = "#465064";
    ctx.beginPath();
    ctx.moveTo(0, floorY + 0.5); ctx.lineTo(W, floorY + 0.5);
    ctx.stroke();

    const frame = this.displayedFrame();
    const img = frame ? getImage(frame.url) : null;
    if (frame?.url && !img) loadImage(frame.url).then(() => this.invalidate());
    const iw = img?.width || frame?.actual_width || frame?.width || 16;
    const ih = img?.height || frame?.actual_height || frame?.height || 16;
    const scale = clamp(Math.floor(Math.min((W - 160) / Math.max(1, iw),
      (H - 140) / Math.max(1, ih))), 1, 6);
    const centerX = Math.round(W * 0.4);
    const ax = Number(frame?.anchor_x) || 0;
    const ay = Number(frame?.anchor_y) || 0;
    const ox = centerX - ax * scale;
    const oy = floorY - ay * scale;
    this.stageTransform = { ox, oy, scale, width: iw, height: ih };
    // Shadow.
    ctx.fillStyle = "rgba(0,0,0,.45)";
    ctx.beginPath();
    ctx.ellipse(centerX, floorY + 3, Math.max(8, iw * scale * 0.35),
      3 + scale, 0, 0, Math.PI * 2);
    ctx.fill();
    if (img) {
      ctx.save();
      if (this.flip) {
        ctx.translate(centerX * 2, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(img, ox, oy, iw * scale, ih * scale);
      ctx.restore();
      // BBox.
      ctx.strokeStyle = "rgba(224,161,60,.25)";
      ctx.lineWidth = 1;
      ctx.strokeRect(ox + 0.5, oy + 0.5, iw * scale - 1, ih * scale - 1);
    } else {
      ctx.strokeStyle = "#ff50dc";
      ctx.strokeRect(centerX - 24, floorY - 48, 48, 48);
    }
    // Anchor marker.
    const anchorScreenX = this.flip ? centerX * 2 - (ox + ax * scale) : ox + ax * scale;
    const anchorScreenY = oy + ay * scale;
    ctx.strokeStyle = "#79d0bd";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(anchorScreenX - 7, anchorScreenY);
    ctx.lineTo(anchorScreenX + 7, anchorScreenY);
    ctx.moveTo(anchorScreenX, anchorScreenY - 7);
    ctx.lineTo(anchorScreenX, anchorScreenY + 7);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(anchorScreenX, anchorScreenY, 3.5, 0, Math.PI * 2);
    ctx.stroke();
    // Player dummy.
    this.drawDummy(ctx, W, floorY, now);
    // Attack simulation.
    if (this.testPatterns) this.drawSimulation(ctx, centerX, floorY, scale, now);
    // Labels.
    ctx.font = "10px monospace";
    ctx.fillStyle = "#8890a2";
    ctx.fillText(`${frame?.texture || "no frame"} Â· ${iw}Ã—${ih} Â· ${scale}Ã—`, 10, 44);
    ctx.fillText(`anchor ${ax},${ay} Â· duration ${frame?.duration ?? 0}f`, 10, 58);
    if (this.pickAnchor) {
      ctx.fillStyle = "#e0a13c";
      ctx.fillText("ANCHOR PICK: click the sprite to place the anchor", 10, 46);
    }
    if (this.testPatterns) {
      ctx.fillStyle = "#79d0bd";
      ctx.fillText("PATTERN TEST (illustrative timing)", 10, this.pickAnchor ? 62 : 46);
    }
  }

  drawDummy(ctx, W, floorY, now) {
    const x = Math.round(W * 0.8);
    const img = getImage("/assets/generated/player_idle.png");
    if (!img) { loadImage("/assets/generated/player_idle.png").then(() => this.invalidate()); }
    if (img) {
      ctx.globalAlpha = 0.85;
      ctx.drawImage(img, x - 16, floorY - 46, 32, 46);
      ctx.globalAlpha = 1;
    } else {
      ctx.fillStyle = "#5a6a80";
      ctx.fillRect(x - 6, floorY - 34, 12, 34);
      ctx.beginPath();
      ctx.arc(x, floorY - 39, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = "#5f6b82";
    ctx.font = "9px monospace";
    ctx.fillText("player", x - 15, floorY + 16);
  }

  simAttacks() {
    if (!this.testPatterns) return;
    const attacks = this.def?.attacks || [];
    if (this.sim.cooldowns.length !== attacks.length) {
      this.sim.cooldowns = attacks.map((a) => Math.max(0, Number(a.cooldown) || 60) * 0.5);
    }
  }

  advanceSim(dt) {
    const attacks = this.def?.attacks || [];
    if (this.sim.cooldowns.length !== attacks.length) {
      this.sim.cooldowns = attacks.map(() => 30);
    }
    this.sim.t += dt;
    attacks.forEach((attack, i) => {
      this.sim.cooldowns[i] -= dt * 60;
      if (this.sim.cooldowns[i] <= 0 && (attack.type === "projectile" ||
        attack.type === "spread" || attack.type === "burst")) {
        this.sim.cooldowns[i] = Math.max(20, Number(attack.cooldown) || 90);
        const count = Math.max(1, Math.min(8, Number(attack.count) || 1));
        const spread = Number(attack.spread) || 0;
        const speed = Math.max(0.2, Number(attack.speed) || 1.5) * 60;
        for (let k = 0; k < count; k += 1) {
          const angle = count === 1 ? 0 : (k / (count - 1) - 0.5) * (spread * Math.PI / 180);
          this.sim.projectiles.push({
            x: 0, y: 0, vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed, age: 0, maxAge: 3,
            species: attack.species,
          });
        }
      }
    });
    for (const p of this.sim.projectiles) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.age += dt;
    }
    this.sim.projectiles = this.sim.projectiles.filter((p) => p.age < p.maxAge);
    this.needsRender = true;
  }

  drawSimulation(ctx, centerX, floorY, scale, now) {
    const attacks = this.def?.attacks || [];
    if (!attacks.length) {
      ctx.fillStyle = "#6f7587";
      ctx.font = "11px sans-serif";
      ctx.fillText("No attack patterns defined", centerX - 60, floorY - 90);
      return;
    }
    const originX = centerX;
    const originY = floorY - 18 * scale;
    for (const p of this.sim.projectiles) {
      const x = originX + p.x;
      const y = originY + p.y;
      const sp = this.app.speciesFor(p.species, 0);
      const img = sp?.first_frame?.url ? getImage(sp.first_frame.url) : null;
      if (img) {
        ctx.drawImage(img, x - img.width / 2, y - img.height / 2);
      } else {
        ctx.fillStyle = "#e06a9a";
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#ffd0e0";
        ctx.stroke();
      }
    }
    // Cooldown bars.
    const baseX = 12;
    let y = (this.cssH || 400) - 16 - attacks.length * 12;
    ctx.font = "9px monospace";
    for (let i = 0; i < attacks.length; i += 1) {
      const a = attacks[i];
      const cd = Math.max(1, Number(a.cooldown) || 90);
      const left = Math.max(0, this.sim.cooldowns[i] || 0);
      ctx.fillStyle = "#2a2e3a";
      ctx.fillRect(baseX, y, 100, 5);
      ctx.fillStyle = "#79d0bd";
      ctx.fillRect(baseX, y, 100 * (1 - left / cd), 5);
      ctx.fillStyle = "#9aa0b2";
      ctx.fillText(`${a.type} ${Math.round(left)}f`, baseX + 106, y + 5);
      y += 12;
    }
  }

  /* -------------------------------------------------------------- frame strip */
  renderFrameStrip() {
    if (!this.frameStrip) return;
    clear(this.frameStrip);
    this.frameCards = [];
    this.frames.forEach((frame, index) => {
      const active = index === this.selectedFrame;
      const thumb = frame.url
        ? h("img", { src: frame.url, alt: frame.texture, draggable: "false" })
        : h("span", { class: "muted tiny", text: "?" });
      const card = h("div", {
        class: `frame-card${active ? " active" : ""}`,
        title: `${frame.texture}\nanchor ${frame.anchor_x},${frame.anchor_y} Â· ${frame.duration}f`,
        onclick: () => {
          this.selectedFrame = index;
          this.play = false;
          this.playIndex = 0;
          this.updatePlayButton();
          this.renderFrameStrip();
          this.renderTab();
          this.invalidate();
        },
      },
      h("span", { class: "idx", text: String(index) }),
      h("div", { class: "thumb" }, thumb),
      h("div", { class: "cap" },
        h("span", { text: `${frame.width || "?"}Ã—${frame.height || "?"}` }),
        h("span", { text: `${frame.duration}f` })),
      );
      this.frameStrip.appendChild(card);
      this.frameCards.push(card);
    });
    this.frameStrip.appendChild(h("div", {
      class: "frame-card add", title: "Add a frame from an image",
      onclick: () => this.showAddFrameMenu(),
    }, "+"));
    this.highlightPlayingFrame();
  }

  highlightPlayingFrame() {
    if (!this.frameCards?.length) return;
    const seq = this.sequenceFrames();
    const playingIndex = this.play
      ? (seq[this.playIndex] ?? this.selectedFrame)
      : this.selectedFrame;
    this.frameCards.forEach((card, index) => {
      card.classList.toggle("playing", index === playingIndex);
    });
  }

  updatePlayButton() {
    clear(this.playBtn);
    this.playBtn.appendChild(icon(this.play ? "pause" : "play"));
    this.playBtn.title = this.play ? "Pause" : "Play";
  }

  togglePlay() {
    this.play = !this.play;
    this.updatePlayButton();
    this.needsRender = true;
  }

  /* ------------------------------------------------------------------ tabs */
  setTab(id) {
    this.activeTab = id;
    for (const [key, btn] of Object.entries(this.tabButtons)) {
      btn.classList.toggle("active", key === id);
    }
    this.renderTab();
  }

  renderTab() {
    clear(this.tabBody);
    if (!this.entry) {
      this.tabBody.appendChild(h("div", { class: "inspector-empty",
        text: "Load or create a species." }));
      return;
    }
    if (this.activeTab === "frames") this.renderFramesTab();
    else if (this.activeTab === "animation") this.renderAnimationTab();
    else if (this.activeTab === "stats") this.renderStatsTab();
    else if (this.activeTab === "attacks") this.renderAttacksTab();
    else if (this.activeTab === "sounds") this.renderSoundsTab();
  }

  inputRow(label, value, onChange, { type = "number", min, max, step } = {}) {
    const input = h("input", {
      type, value: value ?? "",
      min: min ?? undefined, max: max ?? undefined, step: step ?? undefined,
      oninput: () => {
        let v = type === "number" ? Number(input.value) : input.value;
        if (type === "number" && !Number.isFinite(v)) return;
        onChange(v);
      },
    });
    return h("div", { class: "field" }, h("span", { text: label }), input);
  }

  selectRow(label, options, value, onChange) {
    const select = h("select", {
      onchange: () => onChange(select.value),
    }, options.map(([val, text]) => h("option", {
      value: val, text, selected: String(val) === String(value),
    })));
    return h("div", { class: "field" }, h("span", { text: label }), select);
  }

  checkboxRow(label, value, onChange) {
    const input = h("input", {
      type: "checkbox", checked: !!value,
      onchange: () => onChange(input.checked),
    });
    return h("label", { class: "check" }, input, label);
  }

  /* ----------------------------------------------------------------- Frames */
  renderFramesTab() {
    clear(this.tabBody);
    const frame = this.currentFrame();
    if (!frame) {
      this.tabBody.append(
        h("div", { class: "inspector-hint",
          text: "This species has no frames yet. Add a PNG to begin." }),
        h("button", {
          class: "btn primary", type: "button", text: "Add frame",
          onclick: () => this.showAddFrameMenu(),
        }, icon("plus")),
      );
      return;
    }
    const thumb = frame.url ? h("img", {
      src: frame.url, style: { width: "96px", height: "96px",
        objectFit: "contain", imageRendering: "pixelated",
        background: "#090a0e", border: "1px solid var(--line)",
        borderRadius: "4px" },
    }) : h("div", { class: "muted", text: "no image" });
    const anchorX = h("input", {
      type: "number", value: frame.anchor_x,
      oninput: () => { frame.anchor_x = Number(anchorX.value); this.markDirty(); this.invalidate(); },
    });
    const anchorY = h("input", {
      type: "number", value: frame.anchor_y,
      oninput: () => { frame.anchor_y = Number(anchorY.value); this.markDirty(); this.invalidate(); },
    });
    const duration = h("input", {
      type: "number", value: frame.duration, min: "1", max: "255",
      oninput: () => { frame.duration = Math.max(1, Number(duration.value) || 1); this.markDirty(); this.invalidate(); this.renderFrameStrip(); },
    });
    this.tabBody.append(
      h("div", { class: "row" },
        thumb,
        h("div", { class: "grow", style: { display: "flex", flexDirection: "column", gap: "4px" } },
          h("div", { class: "small mono", text: `frame ${this.selectedFrame} / ${this.frames.length - 1}` }),
          h("div", { class: "small dim", text: frame.texture || "â€”" }),
          h("div", { class: "tiny muted",
            text: `${frame.actual_width || frame.width || "?"}Ã—${frame.actual_height || frame.height || "?"} px` }),
        ),
      ),
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "Anchor X" }), anchorX),
        h("div", { class: "field" }, h("span", { text: "Anchor Y" }), anchorY)),
      h("div", { class: "field" }, h("span", { text: "Duration" }), duration),
      h("div", { class: "row wrap" },
        h("button", {
          class: "btn small", type: "button", text: "Pick on stage",
          onclick: () => {
            this.pickAnchor = true;
            this.anchorBtn.classList.add("active");
            this.play = false;
            this.updatePlayButton();
          },
        }, icon("target")),
        h("button", {
          class: "btn small", type: "button", text: "Replaceâ€¦",
          onclick: () => this.showAssetPicker({ replace: true }),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Uploadâ€¦",
          onclick: () => this.pickUpload({ replace: true }),
        }),
      ),
      h("div", { class: "row wrap" },
        h("button", {
          class: "btn small", type: "button", text: "â† Move",
          onclick: () => this.moveFrame(-1),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Move â†’",
          onclick: () => this.moveFrame(1),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Duplicate",
          onclick: () => this.duplicateFrame(),
        }),
        h("button", {
          class: "btn small danger", type: "button", text: "Delete",
          onclick: () => this.deleteFrame(),
        }),
      ),
      h("div", { class: "field-note",
        text: "Anchor = the pixel placed on the object's world position: X is the body centre, Y the feet. Duration is in 60 Hz ticks." }),
      h("hr"),
      h("div", { class: "small dim", text: "Frame list" }),
      h("div", { class: "obj-list" },
        this.frames.map((f, i) => h("div", {
          class: `obj-row${i === this.selectedFrame ? " active" : ""}`,
          onclick: () => {
            this.selectedFrame = i; this.play = false; this.updatePlayButton();
            this.renderFrameStrip(); this.renderFramesTab(); this.invalidate();
          },
        },
        h("span", { class: "label", text: `${i}. ${f.texture}` }),
        h("span", { class: "coords", text: `${f.anchor_x},${f.anchor_y} Â· ${f.duration}f` }),
        ))),
    );
  }

  moveFrame(delta) {
    const index = this.selectedFrame;
    const next = index + delta;
    if (next < 0 || next >= this.frames.length) return;
    this.pushUndo("move frame");
    const [frame] = this.frames.splice(index, 1);
    this.frames.splice(next, 0, frame);
    // Remap state frame indices to follow the frame.
    for (const key of Object.keys(this.states)) {
      this.states[key] = this.states[key].map((value) => {
        if (value === index) return next;
        if (delta > 0 && value > index && value <= next) return value - 1;
        if (delta < 0 && value >= next && value < index) return value + 1;
        return value;
      });
    }
    this.selectedFrame = next;
    this.markDirty();
    this.renderFrameStrip();
    this.renderFramesTab();
    this.invalidate();
  }

  duplicateFrame() {
    const frame = this.currentFrame();
    if (!frame) return;
    this.pushUndo("duplicate frame");
    this.frames.splice(this.selectedFrame + 1, 0, { ...frame });
    this.selectedFrame += 1;
    this.markDirty();
    this.renderFrameStrip();
    this.renderFramesTab();
    this.invalidate();
  }

  async deleteFrame() {
    if (this.frames.length <= 1) {
      toast("A species needs at least one frame.", "warn");
      return;
    }
    const index = this.selectedFrame;
    this.pushUndo("delete frame");
    this.frames.splice(index, 1);
    for (const key of Object.keys(this.states)) {
      this.states[key] = this.states[key]
        .filter((v) => v !== index)
        .map((v) => v > index ? v - 1 : v);
      if (!this.states[key].length) delete this.states[key];
    }
    if (this.entry.hurt === index) delete this.entry.hurt;
    else if (this.entry.hurt > index) this.entry.hurt -= 1;
    if (this.entry.default === index) delete this.entry.default;
    else if (this.entry.default > index) this.entry.default -= 1;
    this.selectedFrame = Math.max(0, Math.min(index, this.frames.length - 1));
    this.markDirty();
    this.renderFrameStrip();
    this.renderFramesTab();
    this.invalidate();
  }

  addFrameFromAsset(asset, { replace = false } = {}) {
    const texture = textureFromAsset(asset);
    const width = asset.width || 0;
    const height = asset.height || 0;
    const frame = {
      texture,
      anchor_x: Math.round(width / 2),
      anchor_y: height,
      duration: 8,
      width, height,
      url: asset.url,
      actual_width: width,
      actual_height: height,
    };
    if (replace && this.currentFrame()) {
      this.pushUndo("replace frame");
      const old = this.currentFrame();
      this.frames[this.selectedFrame] = {
        ...frame, texture, anchor_x: old.anchor_x || frame.anchor_x,
        anchor_y: old.anchor_y || frame.anchor_y,
        duration: old.duration || 8,
      };
    } else {
      this.pushUndo("add frame");
      this.frames.push(frame);
      this.selectedFrame = this.frames.length - 1;
    }
    this.markDirty();
    this.renderFrameStrip();
    this.renderFramesTab();
    this.invalidate();
  }

  async uploadFrameFile(file, { replace = false } = {}) {
    try {
      const data = await readFileDataURL(file);
      const result = await api.upload(file.name, data);
      if (!result.ok) throw new Error(result.error || "upload failed");
      this.addFrameFromAsset({
        path: result.path, url: result.url, width: result.width,
        height: result.height, name: file.name, source: "authored",
      }, { replace });
      toast(`Imported ${file.name} (${result.width}Ã—${result.height})`, "ok");
      if (result.width > 64 || result.height > 64) {
        toast("This image is larger than 64Ã—64; the sprite pipeline expects smaller frames.", "warn", 5000);
      }
    } catch (error) {
      toast(`Import failed: ${error.message}`, "error");
    }
  }

  pickUpload({ replace = false } = {}) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png";
    input.onchange = () => {
      const file = input.files?.[0];
      if (file) this.uploadFrameFile(file, { replace });
    };
    input.click();
  }

  showAddFrameMenu() {
    const dlg = showModal({
      title: "Add a frame",
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        h("div", { class: "field-note",
          text: "Frames are PNG images. The editor loads them; it does not edit pixels." }),
        h("button", {
          class: "btn primary", type: "button", text: "Upload a PNGâ€¦",
          onclick: () => { dlg.close(); this.pickUpload(); },
        }),
        h("button", {
          class: "btn", type: "button", text: "Choose an existing assetâ€¦",
          onclick: () => { dlg.close(); this.showAssetPicker(); },
        }),
      ),
      narrow: true,
    });
  }

  async showAssetPicker({ replace = false } = {}) {
    if (!this.assetCache) {
      try {
        const data = await api.assets();
        this.assetCache = data.images || [];
      } catch (error) {
        toast(`Could not load assets: ${error.message}`, "error");
        return;
      }
    }
    let query = "";
    const grid = h("div", { class: "species-grid" });
    const render = () => {
      clear(grid);
      const list = this.assetCache.filter((img) => {
        if (!img.url) return false;
        if (!query) return true;
        return `${img.name} ${img.path}`.toLowerCase().includes(query);
      }).slice(0, 300);
      for (const img of list) {
        grid.appendChild(h("button", {
          class: "species-card", type: "button",
          title: `${img.path} Â· ${img.width}Ã—${img.height}`,
          onclick: () => { dlg.close(); this.addFrameFromAsset(img, { replace }); },
        },
        h("img", { src: img.url, loading: "lazy", alt: img.name }),
        h("div", { class: "meta" },
          h("div", { class: "n", text: img.name }),
          h("div", { class: "s", text: `${img.width}Ã—${img.height}` })),
        ));
      }
    };
    const search = h("input", {
      type: "search", placeholder: "Filter PNGsâ€¦",
      oninput: () => { query = search.value.trim().toLowerCase(); render(); },
    });
    render();
    const dlg = showModal({
      title: replace ? "Replace frame image" : "Add frame from asset",
      body: h("div", { class: "field wide" }, search, grid),
      wide: true,
      actions: [{ label: "Cancel" }],
    });
  }

  /* -------------------------------------------------------------- Animation */
  renderAnimationTab() {
    clear(this.tabBody);
    const stateKeys = Object.keys(this.states).sort((a, b) => Number(a) - Number(b));
    const addState = h("select", {
      onchange: () => {
        const id = addState.value;
        if (!id) return;
        if (!this.states[id]) this.states[id] = [];
        this.markDirty();
        this.renderAnimationTab();
      },
    },
    h("option", { value: "", text: "Add stateâ€¦" }),
    ...Array.from({ length: 16 }, (_, i) => String(i))
      .filter((id) => !this.states[id])
      .map((id) => h("option", { value: id, text: `State ${id}` })),
    );
    this.tabBody.append(
      h("div", { class: "field-note",
        text: "Each state is a frame sequence the game plays while an object is in that state. Right-click a chip to remove it. Max 8 frames per state (loader cap)." }),
      h("div", { class: "row" },
        addState,
        h("span", { class: "grow" }),
        h("span", { class: "muted small", text: `${stateKeys.length} active` }),
      ),
    );
    for (let id = 0; id < 16; id += 1) {
      const seq = this.states[String(id)];
      if (!seq) continue;
      const row = h("div", { class: `state-row${this.sequenceKind === String(id) ? " active" : ""}` });
      const stateLabel = this.entry.state_names?.[String(id)];
      const chips = h("div", { class: "state-frames" });
      seq.forEach((frameIndex, pos) => {
        chips.appendChild(h("button", {
          class: `frame-chip${frameIndex === this.selectedFrame ? " sel" : ""}`,
          type: "button", text: String(frameIndex),
          title: `frame ${frameIndex} Â· click to select, right-click to remove`,
          onclick: () => {
            this.selectedFrame = clamp(frameIndex, 0, this.frames.length - 1);
            this.play = false;
            this.updatePlayButton();
            this.renderFrameStrip();
            this.renderFramesTab();
            this.invalidate();
          },
          oncontextmenu: (event) => {
            event.preventDefault();
            this.states[String(id)].splice(pos, 1);
            if (!this.states[String(id)].length) delete this.states[String(id)];
            this.markDirty();
            this.renderAnimationTab();
          },
        }));
      });
      chips.appendChild(h("button", {
        class: "state-add", type: "button", text: "+",
        title: "Append the selected frame",
        onclick: () => {
          if (!this.states[String(id)]) this.states[String(id)] = [];
          if (this.states[String(id)].length >= 8) {
            toast("A state holds at most 8 frames.", "warn");
            return;
          }
          this.states[String(id)].push(this.selectedFrame);
          this.markDirty();
          this.renderAnimationTab();
        },
      }));
      row.append(
        h("div", { class: "state-head" },
          h("span", { class: "name", text: `State ${id}` }),
          stateLabel ? h("span", { class: "tiny muted", text: stateLabel }) : null,
          chips,
          h("button", {
            class: "btn small", type: "button", text: "â–¶",
            title: "Preview this state",
            onclick: () => {
              this.sequenceKind = String(id);
              this.seqSelect.value = String(id);
              this.play = true;
              this.playIndex = 0;
              this.updatePlayButton();
            },
          }),
          h("button", {
            class: "btn small danger", type: "button", text: "Ã—",
            title: "Remove state",
            onclick: () => {
              delete this.states[String(id)];
              this.markDirty();
              this.renderAnimationTab();
            },
          }),
        ),
      );
      this.tabBody.appendChild(row);
    }
    const frameOptions = [["", "None"],
      ...this.frames.map((f, i) => [i, `${i} Â· ${f.texture}`])];
    this.tabBody.append(
      h("hr"),
      this.selectRow("Hurt frame", frameOptions, this.entry.hurt ?? "",
        (value) => { this.entry.hurt = value === "" ? undefined : Number(value); this.markDirty(); }),
      this.selectRow("Default pose", frameOptions, this.entry.default ?? "",
        (value) => { this.entry.default = value === "" ? undefined : Number(value); this.markDirty(); }),
      this.inputRow("Duration", this.entry.duration ?? 6,
        (value) => { this.entry.duration = Math.max(1, value); this.markDirty(); },
        { min: 1, max: 255 }),
      h("div", { class: "field-note",
        text: "Hurt is the white flash pose. Default is the single pose used when no state animation is active." }),
    );
  }

  /* ------------------------------------------------------------------ Stats */
  ensureDef() {
    if (!this.def) {
      this.def = defaultDefinition(this.entryTitle());
    } else {
      this.def = withDefaults(this.def);
    }
    return this.def;
  }

  renderStatsTab() {
    clear(this.tabBody);
    const def = this.ensureDef();
    const sp = this.app.peakSpecies(this.key);
    const native = NATIVE_SPECIES.has(Number(this.entry.species));
    const boss = this.entry.variant === "boss" ||
      NATIVE_BOSS_SPECIES.has(Number(this.entry.species));
    this.tabBody.append(
      h("div", { class: "field wide" }, h("span", { text: "Name" }),
        h("input", {
          type: "text", value: def.name || "",
          oninput: (event) => { def.name = event.target.value; this.defDirty = true; this.markDirty(); },
        })),
      h("div", { class: "field-2" },
        this.inputRow("Species id", this.entry.species,
          (value) => { this.entry.species = clamp(value, 0, 65535); this.defDirty = true; this.markDirty(); },
          { min: 0, max: 65535 }),
        h("div", { class: "field" }, h("span", { text: "Hex" }),
          h("span", { class: "mono dim", text: speciesHex(this.entry.species) })),
      ),
      this.selectRow("Variant", [["", "Enemy / NPC"], ["boss", "Boss sheet"]],
        this.entry.variant || "",
        (value) => {
          if (value) this.entry.variant = value; else delete this.entry.variant;
          this.defDirty = true; this.markDirty(); this.renderStatsTab();
        }),
      this.inputRow("Flags", this.entry.flags ?? 0,
        (value) => { this.entry.flags = clamp(value, 0, 255); this.defDirty = true; this.markDirty(); },
        { min: 0, max: 255 }),
      h("div", { class: "field-note",
        text: boss
          ? "Boss objects keep their native movement/AI. Ranged and melee patterns from this profile are layered on top; lunge is enemy-only. HP/contact damage still apply."
          : native
            ? "This species has a native ported handler. The data-driven profile below is only used when Override AI is enabled; HP/contact damage still apply."
            : "This species uses the data-driven profile: movement, attacks and damage are read from enemies.json." }),
      h("hr"),
      h("div", { class: "small dim", text: "Status" }),
      this.inputRow("HP", def.status.hp,
        (value) => { def.status.hp = clamp(value, 1, 255); this.defDirty = true; this.markDirty(); },
        { min: 1, max: 255 }),
      this.inputRow("Contact dmg", def.status.contact_damage,
        (value) => { def.status.contact_damage = clamp(value, 0, 9); this.defDirty = true; this.markDirty(); },
        { min: 0, max: 9 }),
      this.inputRow("Defense", def.status.defense,
        (value) => { def.status.defense = clamp(value, 0, 9); this.defDirty = true; this.markDirty(); },
        { min: 0, max: 9 }),
      this.checkboxRow("Invulnerable", def.status.invulnerable,
        (value) => { def.status.invulnerable = value; this.defDirty = true; this.markDirty(); }),
      h("hr"),
      h("div", { class: "small dim", text: "Movement" }),
      this.selectRow("AI", (this.app.meta?.ai_kinds || ["walker", "flyer", "charger", "turret", "stationary"])
        .map((kind) => [kind, kind[0].toUpperCase() + kind.slice(1)]),
        def.movement.ai,
        (value) => { def.movement.ai = value; this.defDirty = true; this.markDirty(); }),
      this.inputRow("Speed", def.movement.speed,
        (value) => { def.movement.speed = clamp(value, 0, 8); this.defDirty = true; this.markDirty(); },
        { min: 0, max: 8, step: 0.05 }),
      this.inputRow("Range", def.movement.range,
        (value) => { def.movement.range = clamp(value, 0, 4096); this.defDirty = true; this.markDirty(); },
        { min: 0, max: 4096 }),
      this.inputRow("Bob", def.movement.bob,
        (value) => { def.movement.bob = clamp(value, -128, 128); this.defDirty = true; this.markDirty(); },
        { min: -128, max: 128 }),
      this.checkboxRow("Gravity / floor snap", def.movement.gravity,
        (value) => { def.movement.gravity = value; this.defDirty = true; this.markDirty(); }),
      this.checkboxRow("Override native AI", def.movement.override_ai,
        (value) => { def.movement.override_ai = value; this.defDirty = true; this.markDirty(); }),
      h("div", { class: "field-note",
        text: "Speeds are px/frame at 60 Hz. Override AI replaces a ported handler with this profile; use it deliberately." }),
    );
    if (sp) {
      this.tabBody.appendChild(h("div", { class: "kv" },
        h("dt", { text: "Key" }), h("dd", { text: this.key }),
        h("dt", { text: "Source" }), h("dd", { text: this.source }),
        h("dt", { text: "Frames" }), h("dd", { text: String(this.frames.length) }),
      ));
    }
  }

  /* ---------------------------------------------------------------- Attacks */
  renderAttacksTab() {
    clear(this.tabBody);
    const def = this.ensureDef();
    this.tabBody.append(
      h("div", { class: "row" },
        h("span", { class: "small dim", text: "Attack patterns" }),
        h("span", { class: "grow" }),
        h("button", {
          class: "btn small primary", type: "button", text: "+ Add",
          onclick: () => {
            def.attacks.push({
              type: "projectile", cooldown: 120, range: 160, count: 1,
              spread: 0, speed: 1.5, damage: 1, species: 0x67,
              aim: "player", sfx: "", telegraph: 12,
            });
            this.defDirty = true; this.markDirty(); this.renderAttacksTab();
          },
        }),
      ),
      h("div", { class: "field-note",
        text: "Projectile patterns spawn enemy shots. The runtime uses these for data-driven species; the stage preview is illustrative timing." }),
    );
    if (!def.attacks.length) {
      this.tabBody.appendChild(h("div", { class: "inspector-empty",
        text: "No patterns yet. Add one to give the enemy an attack." }));
      return;
    }
    def.attacks.forEach((attack, index) => {
      const card = h("div", { class: "attack-card" });
      const head = h("div", { class: "attack-head" },
        h("span", { class: "name", text: `${index + 1}. ${attack.type}` }),
        h("button", {
          class: "btn small", type: "button", text: "â†‘",
          onclick: () => {
            if (index === 0) return;
            [def.attacks[index - 1], def.attacks[index]] =
              [def.attacks[index], def.attacks[index - 1]];
            this.defDirty = true; this.renderAttacksTab();
          },
        }),
        h("button", {
          class: "btn small", type: "button", text: "â†“",
          onclick: () => {
            if (index >= def.attacks.length - 1) return;
            [def.attacks[index + 1], def.attacks[index]] =
              [def.attacks[index], def.attacks[index + 1]];
            this.defDirty = true; this.renderAttacksTab();
          },
        }),
        h("button", {
          class: "btn small danger", type: "button", text: "Ã—",
          onclick: () => {
            def.attacks.splice(index, 1);
            this.defDirty = true; this.markDirty(); this.renderAttacksTab();
          },
        }),
      );
      const body = h("div", { class: "attack-body" });
      const typeOptions = (this.app.meta?.attack_types ||
        ["projectile", "spread", "burst", "lunge", "melee"])
        .map((type) => [type, type[0].toUpperCase() + type.slice(1)]);
      const projectileOptions = [
        [0x67, "0x67 ghoul shot"], [0x34, "0x34 boss fire"],
      ];
      if (!projectileOptions.some(([value]) => value === attack.species)) {
        projectileOptions.push([attack.species,
          `0x${Number(attack.species || 0).toString(16).toUpperCase()} custom`]);
      }
      body.append(
        this.selectRow("Type", typeOptions, attack.type,
          (value) => { attack.type = value; this.defDirty = true; this.markDirty(); }),
        this.inputRow("Cooldown", attack.cooldown,
          (value) => { attack.cooldown = clamp(value, 1, 3600); this.defDirty = true; this.markDirty(); },
          { min: 1, max: 3600 }),
        this.inputRow("Range", attack.range,
          (value) => { attack.range = clamp(value, 0, 4096); this.defDirty = true; this.markDirty(); },
          { min: 0, max: 4096 }),
        this.inputRow("Count", attack.count,
          (value) => { attack.count = clamp(value, 1, 8); this.defDirty = true; this.markDirty(); },
          { min: 1, max: 8 }),
        this.inputRow("SpreadÂ°", attack.spread,
          (value) => { attack.spread = clamp(value, 0, 90); this.defDirty = true; this.markDirty(); },
          { min: 0, max: 90 }),
        this.inputRow("Speed", attack.speed,
          (value) => { attack.speed = clamp(value, 0.1, 8); this.defDirty = true; this.markDirty(); },
          { min: 0.1, max: 8, step: 0.05 }),
        this.inputRow("Damage", attack.damage,
          (value) => { attack.damage = clamp(value, 0, 9); this.defDirty = true; this.markDirty(); },
          { min: 0, max: 9 }),
        this.selectRow("Aim", [["player", "At player"], ["facing", "Facing"],
          ["up", "Up"], ["down", "Down"]], attack.aim,
          (value) => { attack.aim = value; this.defDirty = true; this.markDirty(); }),
        this.selectRow("Projectile", projectileOptions, attack.species,
          (value) => { attack.species = Number(value); this.defDirty = true; this.markDirty(); }),
        this.selectRow("Sound", [["", "None"], ...(this.app.meta?.sfx || [])
          .map((sfx) => [sfx.name, sfx.name])], attack.sfx,
          (value) => { attack.sfx = value; this.defDirty = true; this.markDirty(); }),
      );
      card.append(head, body);
      this.tabBody.appendChild(card);
    });
  }

  /* ----------------------------------------------------------------- Sounds */
  renderSoundsTab() {
    clear(this.tabBody);
    const def = this.ensureDef();
    const soundOptions = [["", "None"], ...(this.app.meta?.sfx || [])
      .map((sfx) => [sfx.name, sfx.name])];
    this.tabBody.append(
      h("div", { class: "field-note",
        text: "The game maps these authored slots onto its captured effects. Missing WAV files fall back to the procedural sounds." }),
    );
    for (const slot of ["spawn", "attack", "hurt", "death"]) {
      const value = def.sounds?.[slot] || "";
      const select = h("select", {
        onchange: () => {
          if (!def.sounds) def.sounds = {};
          if (select.value) def.sounds[slot] = select.value;
          else delete def.sounds[slot];
          this.defDirty = true; this.markDirty();
        },
      }, soundOptions.map(([val, text]) => h("option", {
        value: val, text, selected: val === value,
      })));
      const sfx = (this.app.meta?.sfx || []).find((s) => s.name === value);
      this.tabBody.appendChild(
        h("div", { class: "sound-row" },
          h("label", { text: slot }),
          select,
          h("button", {
            class: "btn icon", type: "button", title: "Preview",
            disabled: !sfx?.url,
            onclick: () => playAudio(sfx.url, 0.7),
          }, icon("play")),
        ),
      );
    }
    this.tabBody.append(
      h("hr"),
      h("div", { class: "small dim", text: "Attack pattern sounds are set per pattern in the Attacks tab." }),
    );
  }

  /* ------------------------------------------------------------------ undo */
  pushUndo(label) {
    // The enemy editor keeps a compact snapshot of the frame/state data only;
    // undoing does not roll back text fields in the stats tab.
    if (!this._undo) this._undo = [];
    if (!this._redo) this._redo = [];
    this._undo.push({
      label,
      frames: deepClone(this.frames.map((f) => {
        const copy = { ...f };
        delete copy.url;
        return copy;
      })),
      states: deepClone(this.states),
      selected: this.selectedFrame,
    });
    if (this._undo.length > 40) this._undo.shift();
    this._redo = [];
  }

  undo() {
    if (!this._undo?.length) return;
    const entry = this._undo.pop();
    this._redo = this._redo || [];
    this._redo.push({
      frames: deepClone(this.frames),
      states: deepClone(this.states),
      selected: this.selectedFrame,
    });
    this.frames = entry.frames.map((frame) => {
      const found = this.frames.find((f) => f.texture === frame.texture);
      return { ...frame, url: found?.url };
    });
    this.states = entry.states;
    this.selectedFrame = clamp(entry.selected, 0, this.frames.length - 1);
    this.markDirty();
    this.renderFrameStrip();
    this.renderTab();
    this.invalidate();
  }

  redo() {
    if (!this._redo?.length) return;
    const entry = this._redo.pop();
    this._undo = this._undo || [];
    this._undo.push({
      frames: deepClone(this.frames),
      states: deepClone(this.states),
      selected: this.selectedFrame,
    });
    this.frames = entry.frames;
    this.states = entry.states;
    this.selectedFrame = clamp(entry.selected, 0, this.frames.length - 1);
    this.markDirty();
    this.renderFrameStrip();
    this.renderTab();
    this.invalidate();
  }

  /* -------------------------------------------------------------- new/save */
  showNewSpeciesDialog() {
    const used = new Set(this.app.species.map((sp) => sp.species));
    let nextId = 0x120;
    while (used.has(nextId)) nextId += 1;
    const idInput = h("input", { type: "number", value: nextId,
      min: "0", max: "65535" });
    const nameInput = h("input", { type: "text", value: "New Enemy" });
    const kindSelect = h("select", {},
      h("option", { value: "enemy", text: "Enemy" }),
      h("option", { value: "boss", text: "Boss (variant sheet)" }),
    );
    const flagsInput = h("input", { type: "number", value: "0",
      min: "0", max: "255" });
    const hpInput = h("input", { type: "number", value: "2", min: "1", max: "255" });
    const keyPreview = h("span", { class: "mono dim", text: "" });
    const updateKey = () => {
      const id = Number(idInput.value) || 0;
      let key = id.toString(16).padStart(2, "0");
      if (kindSelect.value === "boss") key += `_f${Number(flagsInput.value) || 0}`;
      let suffix = 1;
      const base = key;
      while (this.app.species.some((sp) => sp.key === key)) {
        key = `${base}_${suffix}`; suffix += 1;
      }
      keyPreview.textContent = key;
      return key;
    };
    idInput.addEventListener("input", updateKey);
    flagsInput.addEventListener("input", updateKey);
    kindSelect.addEventListener("change", updateKey);
    updateKey();
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "9px" } },
      h("div", { class: "field" }, h("span", { text: "Species id" }), idInput),
      h("div", { class: "field" }, h("span", { text: "Name" }), nameInput),
      h("div", { class: "field" }, h("span", { text: "Kind" }), kindSelect),
      h("div", { class: "field" }, h("span", { text: "Flags" }), flagsInput),
      h("div", { class: "field" }, h("span", { text: "HP" }), hpInput),
      h("div", { class: "field" }, h("span", { text: "Key" }), keyPreview),
      h("div", { class: "field-note",
        text: "The new entry starts with a placeholder 32Ã—32 frame, so it is immediately visible in the game. Replace it with your own PNG." }),
    );
    const dlg = showModal({
      title: "New enemy",
      body,
      actions: [
        { label: "Cancel" },
        {
          label: "Create",
          primary: true,
          onClick: async () => {
            const key = updateKey();
            const species = Number(idInput.value) || 0;
            const boss = kindSelect.value === "boss";
            try {
              const placeholder = await this.makePlaceholderPng(key, boss);
              const entry = {
                species,
                variant: boss ? "boss" : undefined,
                flags: boss ? Number(flagsInput.value) || 0 : undefined,
                frames: [{
                  texture: placeholder.texture,
                  anchor_x: 16,
                  anchor_y: 32,
                  duration: 8,
                  width: 32,
                  height: 32,
                  url: placeholder.url,
                  actual_width: 32,
                  actual_height: 32,
                }],
                duration: 8,
                states: { 0: [0] },
                source: "created in the editor",
              };
              if (!entry.variant) delete entry.variant;
              if (entry.flags === undefined) delete entry.flags;
              const def = defaultDefinition(nameInput.value || `Species ${speciesHex(species)}`);
              def.status.hp = Math.max(1, Number(hpInput.value) || 2);
              dlg.close();
              this.key = key;
              this.routeArg = key;
              this.entry = entry;
              this.def = def;
              this.originalDef = null;
              this.defDirty = true;
              this._undo = [];
              this._redo = [];
              this.frames = entry.frames.map((f) => ({ ...f }));
              this.states = deepClone(entry.states);
              this.selectedFrame = 0;
              this.source = "new";
              this.dirty = true;
              this.markDirty();
              this.app.species.push({
                key, species, species_hex: speciesHex(species),
                variant: boss ? "boss" : "", flags: boss ? Number(flagsInput.value) || 0 : 0,
                kind: boss ? "boss" : "enemy", frames: 1, states: 1,
                source: "authored", name: def.name,
                thumb: { url: placeholder.url, width: 32, height: 32 },
                first_frame: { url: placeholder.url, anchor_x: 16,
                  anchor_y: 32, width: 32, height: 32 },
                hp: def.status.hp,
              });
              history.replaceState(null, "", `#enemy/${key}`);
              this.renderSpeciesList();
              this.renderFrameStrip();
              this.renderTab();
              this.updateHud();
              this.invalidate();
              toast("New species created. Save it to write the entry.", "ok");
            } catch (error) {
              toast(`Create failed: ${error.message}`, "error");
              return false;
            }
            return true;
          },
        },
      ],
    });
  }

  async makePlaceholderPng(key, boss) {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 32, 32);
    // A tiny horned silhouette: deliberately unmistakable as a placeholder.
    ctx.fillStyle = boss ? "#b98ae0" : "#c06a92";
    ctx.beginPath();
    ctx.ellipse(16, 20, 9, 11, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(16, 10, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = boss ? "#4a2a66" : "#5a2638";
    ctx.beginPath();
    ctx.moveTo(9, 6); ctx.lineTo(11, 1); ctx.lineTo(14, 6); ctx.closePath(); ctx.fill();
    ctx.beginPath();
    ctx.moveTo(18, 6); ctx.lineTo(21, 1); ctx.lineTo(23, 6); ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#ffe6a0";
    ctx.fillRect(11, 9, 3, 3);
    ctx.fillRect(18, 9, 3, 3);
    ctx.fillStyle = "#250d18";
    ctx.fillRect(13, 15, 6, 2);
    ctx.fillStyle = boss ? "#e6d4ff" : "#ffd0e0";
    ctx.fillRect(13, 23, 2, 2);
    ctx.fillRect(17, 23, 2, 2);
    // Corner markers make the anchor/feet easy to see.
    ctx.fillStyle = "rgba(255,255,255,.4)";
    ctx.fillRect(15, 30, 2, 2);
    const data = canvas.toDataURL("image/png");
    const res = await api.upload(`spr_${key}_0.png`, data);
    if (!res.ok) throw new Error(res.error || "upload failed");
    return res;
  }

  stripEntry() {
    const entry = { ...this.entry };
    delete entry.url;
    delete entry.actual_width;
    delete entry.actual_height;
    delete entry._source;
    entry.species = Number(this.entry.species) || 0;
    entry.frames = this.frames.map(stripFrame);
    entry.duration = Math.max(1, Number(this.entry.duration) || 6);
    entry.source = this.entry.source || `edited species ${this.key}`;
    if (this.entry.variant) entry.variant = this.entry.variant;
    else delete entry.variant;
    if (this.entry.variant === "boss") entry.flags = Number(this.entry.flags) || 0;
    else delete entry.flags;
    if (this.states && Object.keys(this.states).length) {
      entry.states = {};
      for (const [id, seq] of Object.entries(this.states)) {
        if (!seq.length) continue;
        entry.states[id] = seq.slice(0, 8).map((v) => clamp(v, 0, this.frames.length - 1));
      }
    } else {
      delete entry.states;
    }
    if (Number.isFinite(this.entry.hurt)) entry.hurt = Number(this.entry.hurt);
    else delete entry.hurt;
    if (Number.isFinite(this.entry.default)) entry.default = Number(this.entry.default);
    else delete entry.default;
    return entry;
  }

  async validate() {
    try {
      const data = await api.validateSpecies(this.key, this.stripEntry(),
        this.def || null);
      this.lastValidation = data;
      this.validateBadge.textContent = data.errors?.length
        ? `${data.errors.length} error${data.errors.length === 1 ? "" : "s"}`
        : data.warnings?.length
          ? `${data.warnings.length} warning${data.warnings.length === 1 ? "" : "s"}`
          : "Valid";
      showModal({
        title: `Validate ${this.entryTitle()}`,
        body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
          h("div", { class: "field-note",
            text: "Frames must exist, anchors must be inside the image, states must reference valid frames, and the loader caps frames at 64 / states at 8 per state." }),
          issueList(data)),
        wide: true,
        actions: [{ label: "Close", primary: true }],
      });
      return data;
    } catch (error) {
      toast(`Validation failed: ${error.message}`, "error");
      return null;
    }
  }

  async save() {
    if (!this.key) return;
    if (!this.frames.length) {
      toast("Add at least one frame before saving.", "error");
      return;
    }
    const entry = this.stripEntry();
    const definition = this.defDirty ? this.def : (this.originalDef || null);
    try {
      const result = await api.saveSpecies(this.key, entry, definition);
      if (!result.ok) {
        this.lastValidation = result.validation;
        showModal({
          title: "Save blocked",
          body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
            issueList(result.validation)),
          wide: true,
          actions: [{ label: "Close", primary: true }],
        });
        toast("Fix the validation errors before saving.", "error");
        return;
      }
      this.source = "authored";
      this.entry = result.entry;
      this.defDirty = false;
      this.originalDef = result.definition || this.def;
      this.def = result.definition || this.def;
      this.markClean();
      this.lastValidation = result.validation;
      this.validateBadge.textContent = result.validation?.errors?.length
        ? `${result.validation.errors.length} errors` : "Saved";
      await this.app.reloadSpecies();
      this.syncSummary();
      this.renderSpeciesList();
      this.renderTab();
      toast(`Saved ${result.path}${result.backup ? ` Â· backup ${result.backup}` : ""}`,
        "ok", 3600);
      this.app.setStatus(`Enemy Editor Â· ${this.entryTitle()}`,
        `saved ${result.path}`);
    } catch (error) {
      toast(`Save failed: ${error.message}`, "error", 5000);
    }
  }

  showSaveMenu() {
    showModal({
      title: "Save options",
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        h("div", { class: "field-note",
          text: "Animation data is written to assets/authored/species_anim.json; stats, attacks and sounds go to assets/authored/enemies.json. The game merges both over the generated data." }),
        h("button", {
          class: "btn primary", type: "button", text: "Save to authored overlay",
          onclick: () => this.save(),
        }),
        h("button", {
          class: "btn", type: "button", text: "Export entry JSONâ€¦",
          onclick: () => {
            const payload = { key: this.key, entry: this.stripEntry(),
              definition: this.def };
            const blob = new Blob([JSON.stringify(payload, null, 1)],
              { type: "application/json" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `species_${this.key}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
          },
        }),
        this.source === "authored" ? h("button", {
          class: "btn danger", type: "button", text: "Revert to generated entry",
          onclick: async () => {
            const ok = await confirmDialog("Remove authored override?",
              "The authored species entry and its enemy definition are deleted.",
              { okLabel: "Revert", danger: true });
            if (!ok) return;
            try {
              await api.deleteSpecies(this.key);
              await this.app.reloadSpecies();
              await this.loadSpecies(this.key);
              toast("Authored override removed.", "ok");
            } catch (error) {
              toast(`Revert failed: ${error.message}`, "error");
            }
          },
        }) : null,
      ),
      actions: [{ label: "Close", primary: true }],
    });
  }

  async reload() {
    if (this.dirty) {
      const ok = await confirmDialog("Reload species?",
        "Unsaved changes will be lost.", { okLabel: "Reload", danger: true });
      if (!ok) return;
    }
    await this.loadSpecies(this.key);
  }

  /* --------------------------------------------------------------- keyboard */
  bindKeys() {
    this._onKey = (event) => {
      if (this.destroyed) return;
      const target = event.target;
      const editing = target instanceof HTMLElement &&
        ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "s") {
        event.preventDefault(); this.save(); return;
      }
      if ((event.ctrlKey || event.metaKey) && key === "z") {
        event.preventDefault(); event.shiftKey ? this.redo() : this.undo(); return;
      }
      if ((event.ctrlKey || event.metaKey) && key === "y") {
        event.preventDefault(); this.redo(); return;
      }
      if (editing) return;
      if (event.code === "Space") {
        event.preventDefault(); this.togglePlay(); return;
      }
      if (event.key === "ArrowLeft" && !event.ctrlKey) {
        this.selectedFrame = Math.max(0, this.selectedFrame - 1);
        this.play = false; this.updatePlayButton();
        this.renderFrameStrip(); this.renderTab(); this.invalidate();
      } else if (event.key === "ArrowRight") {
        this.selectedFrame = Math.min(this.frames.length - 1, this.selectedFrame + 1);
        this.play = false; this.updatePlayButton();
        this.renderFrameStrip(); this.renderTab(); this.invalidate();
      }
    };
    window.addEventListener("keydown", this._onKey);
  }

  unbindKeys() {
    window.removeEventListener("keydown", this._onKey);
  }
}
