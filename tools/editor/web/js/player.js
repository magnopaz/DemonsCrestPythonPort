/* Player Editor: Firebrand's base sheet and the six crest forms.
   Edits go to assets/authored/player_anim.json and player_forms.json; images
   are loaded from the shared asset tree, never painted here. */

import { api } from "./api.js";
import {
  h, clear, fitCanvas, getImage, loadImage, clamp, drawChecker,
  readFileDataURL, deepClone,
} from "./util.js";
import { icon } from "./icons.js";
import { toast, showModal, confirmDialog } from "./ui.js";

const CLIPS = [
  "idle", "walk", "jump", "hover", "fall", "land", "attack", "spell",
  "flying", "hurt", "death",
];
const LOOPING = new Set(["idle", "walk", "hover", "flying"]);
const FRAME_MS = 1000 / 60;
const ENGINE_STATS = [
  ["Hitbox", "12 x 22 px"],
  ["Walk (max)", "1.40 px/frame"],
  ["Walk acceleration", "0.0117 px/frame^2"],
  ["Jump impulse", "5.59 px/frame"],
  ["Gravity", "0.219 px/frame^2"],
  ["Terminal fall", "6.00 px/frame"],
  ["Fly up", "2.00 px/frame"],
  ["Shot window", "17 frames"],
  ["Special window", "31 frames"],
  ["Forms", "6 (fixed)"],
];

function textureFromAsset(asset) {
  if (!asset) return "";
  const path = asset.path || "";
  if (asset.source === "authored" && path.startsWith("assets/authored/")) {
    return path.slice("assets/authored/".length);
  }
  if (path.startsWith("assets/generated/")) {
    return path.slice("assets/generated/".length);
  }
  return asset.name || "";
}

function defaultLoop(name) {
  return LOOPING.has(name);
}

function stripStep(step) {
  const out = {
    texture: step.texture,
    anchor_x: Math.round(Number(step.anchor_x) || 0),
    anchor_y: Math.round(Number(step.anchor_y) || 0),
    duration: Math.max(1, Math.round(Number(step.duration) || 6)),
  };
  if (step.width) out.width = Math.round(step.width);
  if (step.height) out.height = Math.round(step.height);
  return out;
}

export class PlayerEditor {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    const [routeTarget, routeTab] = String(arg || "").split("/");
    this.target = /^(base|[0-5])$/.test(routeTarget || "") ? routeTarget : "base";
    this.initialTab = ["clip", "form", "stats", "help"].includes(routeTab)
      ? routeTab : null;
    this.tab = this.initialTab || "clip";
    this.overview = null;
    this.detail = null;
    this.entry = null;
    this.clips = {};
    this.clip = "idle";
    this.selectedFrame = 0;
    this.playIndex = 0;
    this.play = true;
    this.speed = 1;
    this.flip = false;
    this.showHitbox = true;
    this.pickAnchor = false;
    this.playTimer = 0;
    this.dirty = false;
    this.needsRender = true;
    this.raf = 0;
    this.lastTs = 0;
    this.destroyed = false;
    this.stageTransform = null;
    this.assetCache = null;
    this._resizeObserver = null;
  }

  /* --------------------------------------------------------------- lifecycle */
  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    this.bindCanvas();
    this.bindKeys();
    this._resizeObserver = new ResizeObserver(() => {
      this.resizeCanvas();
      this.invalidate();
    });
    this._resizeObserver.observe(this.stageWrap);
    await this.loadOverview();
    await this.loadTarget(this.target, { initial: true });
    if (this.initialTab) this.setTab(this.initialTab);
    this.startLoop();
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this._resizeObserver?.disconnect();
    this.unbindKeys();
    this.el?.remove();
  }

  isDirty() { return this.dirty; }
  dirtyPromptKey() { return `#player/${this.target}`; }

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
      if (this.needsRender || this.play) {
        this.needsRender = false;
        try { this.draw(); } catch (error) { console.error(error); }
      }
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  /* -------------------------------------------------------------------- DOM */
  buildDom() {
    this.saveLabel = h("span", { text: "Save" });
    this.saveBtn = h("button", {
      class: "btn primary", type: "button",
      onclick: () => this.save(),
    }, icon("save"), this.saveLabel);
    this.validateBadge = h("span", { class: "badge blue", text: "Not validated" });
    this.sourceBadge = h("span", { class: "badge blue", text: "Generated" });
    this.revertBtn = h("button", {
      class: "btn", type: "button", text: "Revert",
      onclick: () => this.revert(),
    });

    const toolbar = h("div", { class: "toolbar" },
      h("div", { class: "toolbar-title", text: "PLAYER" }),
      h("button", {
        class: "btn small", type: "button", text: "Base",
        title: "Firebrand base animation",
        onclick: () => this.switchTarget("base"),
      }),
      h("button", {
        class: "btn small", type: "button", text: "Forms",
        title: "Select a crest form on the left",
        onclick: () => this.formList?.scrollIntoView({ behavior: "smooth" }),
      }),
      h("div", { class: "sep" }),
      this.saveBtn,
      h("button", {
        class: "btn small", type: "button", text: "Validate",
        onclick: () => this.validate(),
      }),
      this.revertBtn,
      h("span", { class: "grow" }),
      this.sourceBadge,
      this.validateBadge,
    );

    this.formList = h("div", { class: "enemy-list" });
    this.clipList = h("div", { class: "clip-list" });
    this.leftPanel = h("aside", { class: "panel left" },
      h("div", { class: "panel-header" },
        h("span", { text: "Forms" }),
        h("span", { class: "badge", text: "6" })),
      this.formList,
      h("div", { class: "panel-header", style: { borderTop: "1px solid var(--line)" } },
        h("span", { text: "Clips" }),
        h("span", { class: "badge", text: "11" })),
      this.clipList,
      h("div", { class: "field-note", style: { padding: "8px 10px" },
        text: "Base is the shared Firebrand sheet. Forms are the six crest forms; each one overrides its own clips." }),
    );

    this.playBtn = h("button", {
      class: "tool-btn", type: "button", title: "Play / pause (Space)",
      onclick: () => this.togglePlay(),
    }, icon("play"));
    this.clipSelect = h("select", {
      class: "room-select", style: { width: "135px" },
      onchange: () => {
        this.clip = this.clipSelect.value;
        this.selectedFrame = 0;
        this.playTimer = 0;
        this.play = true;
        this.updatePlayButton();
        this.renderAll();
      },
    });
    this.speedSelect = h("select", {
      onchange: () => { this.speed = Number(this.speedSelect.value) || 1; },
    },
    h("option", { value: "0.5", text: "0.5x" }),
    h("option", { value: "1", text: "1x" }),
    h("option", { value: "2", text: "2x" }));
    this.speedSelect.value = "1";
    this.flipBtn = h("button", {
      class: "tool-btn", type: "button", title: "Flip preview",
      onclick: () => { this.flip = !this.flip; this.flipBtn.classList.toggle("active", this.flip); this.invalidate(); },
    }, icon("undo"));
    this.hitboxBtn = h("button", {
      class: "tool-btn active", type: "button", title: "Show 12 x 22 player hitbox",
      onclick: () => { this.showHitbox = !this.showHitbox; this.hitboxBtn.classList.toggle("active", this.showHitbox); this.invalidate(); },
    }, icon("target"));
    this.anchorBtn = h("button", {
      class: "tool-btn", type: "button", title: "Click the stage to set the anchor",
      onclick: () => {
        this.pickAnchor = !this.pickAnchor;
        this.anchorBtn.classList.toggle("active", this.pickAnchor);
        if (this.pickAnchor) {
          this.play = false;
          this.playIndex = this.selectedFrame;
          this.updatePlayButton();
        }
        this.invalidate();
      },
    }, icon("cursor"));
    this.hud = h("span", { class: "mono small dim", text: "" });

    this.stageCanvas = h("canvas", { id: "player-stage" });
    this.stageWrap = h("div", { class: "stage-canvas-wrap" }, this.stageCanvas);
    this.frameStrip = h("div", { class: "frame-strip" });

    this.stageToolbar = h("div", { class: "stage-toolbar" },
      this.playBtn,
      this.clipSelect,
      this.speedSelect,
      h("div", { class: "sep" }),
      this.flipBtn,
      this.hitboxBtn,
      this.anchorBtn,
      h("div", { class: "sep" }),
      h("button", {
        class: "btn small", type: "button", text: "Add frame +",
        onclick: () => this.addFrameMenu(),
      }),
      h("span", { class: "grow" }),
      this.hud,
    );

    this.tabs = h("div", { class: "tabs" });
    this.tabButtons = {};
    for (const [id, label] of [["clip", "Clip"], ["form", "Form"],
      ["stats", "Stats"], ["help", "Help"]]) {
      this.tabButtons[id] = h("button", {
        class: "tab-btn", type: "button", text: label,
        onclick: () => this.setTab(id),
      });
      this.tabs.appendChild(this.tabButtons[id]);
    }
    this.tabBody = h("div", { class: "tab-body" });
    this.rightPanel = h("aside", { class: "panel right" },
      this.tabs, this.tabBody);

    this.stage = h("div", { class: "enemy-stage-wrap" },
      this.stageToolbar, this.stageWrap, this.frameStrip);

    this.el = h("div", { class: "editor enemy-editor player-editor" },
      toolbar,
      h("div", { class: "editor-body" },
        this.leftPanel, this.stage, this.rightPanel),
    );
    this.populateClipSelect();
    this.setTab(this.tab);
  }

  populateClipSelect() {
    clear(this.clipSelect);
    for (const name of CLIPS) {
      this.clipSelect.appendChild(h("option", {
        value: name, text: `${name} (${this.clipSteps(name).length})`,
      }));
    }
    this.clipSelect.value = this.clip;
  }

  /* --------------------------------------------------------------- data load */
  async loadOverview() {
    try {
      this.overview = await api.player();
    } catch (error) {
      toast(`Could not load player data: ${error.message}`, "error");
      this.overview = { base: null, forms: [] };
    }
    this.renderFormList();
  }

  async loadTarget(target, { initial = false } = {}) {
    if (!initial && this.dirty) {
      const ok = await confirmDialog("Discard unsaved changes?",
        "Switching player target will lose the current edits.",
        { okLabel: "Discard changes", danger: true });
      if (!ok) return false;
    }
    try {
      const data = await api.playerEntry(target);
      this.target = String(target);
      this.detail = data;
      this.entry = data.entry || {};
      this.clips = deepClone(this.entry.clips || {});
      this.source = data.source;
      this.routeArg = this.target;
      this.app.currentRouteArg = this.target;
      history.replaceState(null, "",
        `#player/${this.target}${this.tab && this.tab !== "clip" ? "/" + this.tab : ""}`);
      if (!this.clips[this.clip]) {
        this.clip = this.clips.idle ? "idle" : (Object.keys(this.clips)[0] || "idle");
      }
      this.selectedFrame = clamp(this.selectedFrame, 0,
        Math.max(0, this.clipSteps(this.clip).length - 1));
      this.playIndex = this.selectedFrame;
      this.play = true;
      this.playTimer = 0;
      this.dirty = false;
      this.app.setSaveState("saved", "Saved");
      if (this.saveLabel) this.saveLabel.textContent = "Save";
      await this.preloadFrames();
      this.syncSource();
      this.renderAll();
      this.invalidate();
      return true;
    } catch (error) {
      toast(`Could not load player: ${error.message}`, "error");
      return false;
    }
  }

  async preloadFrames() {
    const urls = [];
    for (const clip of Object.values(this.clips)) {
      for (const step of clip?.steps || []) {
        if (step.url) urls.push(step.url);
      }
    }
    await Promise.all([...new Set(urls)].map((url) => loadImage(url)));
  }

  async switchTarget(target) {
    if (String(target) === this.target) return;
    const ok = await this.loadTarget(target);
    if (ok) this.renderAll();
  }

  syncSource() {
    const authored = this.source === "authored";
    this.sourceBadge.textContent = authored ? "Authored" : "Generated";
    this.sourceBadge.className = `badge ${authored ? "gold" : "blue"}`;
    this.revertBtn.disabled = !authored;
    this.revertBtn.style.opacity = authored ? "1" : ".4";
  }

  /* ------------------------------------------------------------------ lists */
  renderFormList() {
    if (!this.formList || !this.overview) return;
    clear(this.formList);
    const items = [this.overview.base, ...(this.overview.forms || [])]
      .filter(Boolean);
    for (const form of items) {
      const active = String(form.target) === this.target;
      this.formList.appendChild(h("div", {
        class: `enemy-row${active ? " active" : ""}`,
        onclick: () => this.switchTarget(form.target),
      },
      form.thumb?.url
        ? h("img", { src: form.thumb.url, alt: form.name, loading: "lazy" })
        : h("div", { class: "species-placeholder", text: "?" }),
      h("div", { class: "meta grow" },
        h("div", { class: "n", text: form.target === "base"
          ? "Firebrand (base)" : `${form.form} · ${form.name}` }),
        h("div", { class: "s",
          text: `${form.clip_count} clips · ${form.steps} frames` })),
      form.overridden ? h("span", { class: "badge gold", text: "E" }) : null,
      ));
    }
  }

  renderClipList() {
    if (!this.clipList) return;
    clear(this.clipList);
    for (const name of CLIPS) {
      const steps = this.clipSteps(name);
      const active = name === this.clip;
      this.clipList.appendChild(h("div", {
        class: `clip-row${active ? " active" : ""}`,
        onclick: () => {
          this.clip = name;
          this.selectedFrame = 0;
          this.playTimer = 0;
          this.play = steps.length > 0;
          this.updatePlayButton();
          this.renderAll();
        },
      },
      h("span", { class: "name", text: name }),
      h("span", { class: "badge", text: `${steps.length}` }),
      this.clipData(name)?.loop ? h("span", { class: "tiny muted", text: "loop" }) : null,
      ));
    }
  }

  /* ----------------------------------------------------------------- canvas */
  bindCanvas() {
    this.stageCanvas.addEventListener("mousedown", (event) => {
      if (!this.pickAnchor) return;
      const rect = this.stageCanvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const tf = this.stageTransform;
      const frame = this.currentFrame();
      if (!tf || !frame) return;
      let px = (x - tf.ox) / tf.scale;
      if (this.flip) px = tf.width - px;
      const py = (y - tf.oy) / tf.scale;
      frame.anchor_x = Math.round(clamp(px, 0, tf.width));
      frame.anchor_y = Math.round(clamp(py, 0, tf.height));
      this.markDirty();
      this.pickAnchor = false;
      this.anchorBtn.classList.remove("active");
      this.renderAll();
      this.invalidate();
      toast(`Anchor set to ${frame.anchor_x},${frame.anchor_y}`, "ok", 1200);
    });
  }

  resizeCanvas() {
    if (!this.stageCanvas) return;
    const size = fitCanvas(this.stageCanvas);
    this.dpr = size.dpr;
    this.cssW = size.width / size.dpr;
    this.cssH = size.height / size.dpr;
    this.invalidate();
  }

  draw() {
    if (!this.stageCanvas) return;
    if (!this.dpr) this.resizeCanvas();
    const ctx = this.stageCanvas.getContext("2d");
    const dpr = this.dpr || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const W = this.cssW || 600;
    const H = this.cssH || 400;
    const grad = ctx.createRadialGradient(W * 0.45, H * 0.5, 20,
      W * 0.45, H * 0.5, Math.max(W, H) * 0.75);
    grad.addColorStop(0, "#181c26");
    grad.addColorStop(1, "#07080b");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
    drawChecker(ctx, 0, Math.round(H * 0.72), W, H, 16, "#0e1016", "#0a0c11");
    ctx.strokeStyle = "#222736";
    ctx.beginPath();
    ctx.moveTo(0, Math.round(H * 0.72) + .5);
    ctx.lineTo(W, Math.round(H * 0.72) + .5);
    ctx.stroke();

    const frame = this.play ? this.displayedFrame() : this.currentFrame();
    const img = frame?.url ? getImage(frame.url) : null;
    if (frame?.url && !img) loadImage(frame.url).then(() => this.invalidate());
    if (!frame) {
      ctx.fillStyle = "#8b91a3";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(`No frames in "${this.clip}" - add one on the right.`, W / 2, H / 2);
      this.stageTransform = null;
      return;
    }
    const iw = img?.width || frame.actual_width || frame.width || 16;
    const ih = img?.height || frame.actual_height || frame.height || 16;
    const scale = clamp(Math.floor(Math.min((W - 120) / Math.max(1, iw),
      (H - 150) / Math.max(1, ih))), 1, 7);
    const ax = Number(frame.anchor_x) || 0;
    const ay = Number(frame.anchor_y) || 0;
    const centerX = Math.round(W * 0.5);
    const floorY = Math.round(H * 0.72);
    const ox = centerX - ax * scale;
    const oy = floorY - ay * scale;
    this.stageTransform = { ox, oy, scale, width: iw, height: ih, ax, ay };

    ctx.fillStyle = "rgba(0,0,0,.45)";
    ctx.beginPath();
    ctx.ellipse(centerX, floorY + 3, Math.max(10, iw * scale * 0.32),
      3 + scale, 0, 0, Math.PI * 2);
    ctx.fill();

    if (this.showHitbox) {
      const hw = 6 * scale;
      const hh = 22 * scale;
      ctx.strokeStyle = "rgba(90,200,255,.75)";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(centerX - hw, floorY - hh, hw * 2, hh);
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(90,200,255,.65)";
      ctx.font = "9px Consolas, monospace";
      ctx.textAlign = "left";
      ctx.fillText("12 x 22 hitbox", centerX + hw + 6, floorY - 4);
    }

    if (img) {
      ctx.save();
      if (this.flip) {
        ctx.translate(centerX * 2, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(img, ox, oy, iw * scale, ih * scale);
      ctx.restore();
      ctx.strokeStyle = "rgba(224,161,60,.35)";
      ctx.strokeRect(ox + .5, oy + .5, iw * scale, ih * scale);
    } else {
      ctx.fillStyle = "#e0a13c";
      ctx.font = "11px Consolas, monospace";
      ctx.textAlign = "center";
      ctx.fillText("loading frame...", centerX, floorY - 10);
    }

    // Anchor marker.
    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(centerX - 7, floorY + .5);
    ctx.lineTo(centerX + 7, floorY + .5);
    ctx.moveTo(centerX + .5, floorY - 7);
    ctx.lineTo(centerX + .5, floorY + 7);
    ctx.stroke();
    ctx.fillStyle = "#ffd166";
    ctx.font = "9px Consolas, monospace";
    ctx.textAlign = "center";
    ctx.fillText("anchor", centerX, floorY + 17);
  }

  /* ------------------------------------------------------------- playback */
  currentClipData() {
    return this.clipData(this.clip);
  }

  clipData(name) {
    const clip = this.clips[name];
    return clip && typeof clip === "object" ? clip : null;
  }

  clipSteps(name = this.clip) {
    const steps = this.clipData(name)?.steps;
    return Array.isArray(steps) ? steps : [];
  }

  currentFrame() {
    const steps = this.clipSteps();
    if (!steps.length) return null;
    this.selectedFrame = clamp(this.selectedFrame, 0, steps.length - 1);
    return steps[this.selectedFrame];
  }

  displayedFrame() {
    const steps = this.clipSteps();
    if (!steps.length) return null;
    return steps[clamp(this.playIndex, 0, steps.length - 1)] || steps[0];
  }

  advance(dt) {
    if (!this.play) return;
    const steps = this.clipSteps();
    if (!steps.length) return;
    if (this.playIndex >= steps.length) this.playIndex = 0;
    const step = steps[this.playIndex];
    this.playTimer += dt * 60 * this.speed;
    if (this.playTimer < Math.max(1, Number(step.duration) || 1)) return;
    this.playTimer = 0;
    this.playIndex += 1;
    if (this.playIndex >= steps.length) {
      if (this.clipData(this.clip)?.loop) {
        this.playIndex = 0;
      } else {
        this.playIndex = steps.length - 1;
        this.selectedFrame = this.playIndex;
        this.play = false;
        this.updatePlayButton();
      }
    }
    this.invalidate();
  }

  togglePlay() {
    this.play = !this.play;
    if (this.play) {
      this.playTimer = 0;
      const steps = this.clipSteps();
      if (this.playIndex >= steps.length - 1 && !this.clipData(this.clip)?.loop) {
        this.playIndex = 0;
      }
    }
    this.updatePlayButton();
    this.invalidate();
  }

  updatePlayButton() {
    if (!this.playBtn) return;
    clear(this.playBtn);
    this.playBtn.appendChild(icon(this.play ? "pause" : "play"));
    this.playBtn.title = this.play ? "Pause (Space)" : "Play (Space)";
  }

  renderAll() {
    this.renderFormList();
    this.renderClipList();
    this.populateClipSelect();
    this.renderFrameStrip();
    this.renderTab();
    this.updateHud();
    this.invalidate();
  }

  updateHud() {
    if (!this.hud) return;
    const steps = this.clipSteps();
    const n = steps.length ? this.selectedFrame + 1 : 0;
    const total = Object.values(this.clips)
      .reduce((sum, clip) => sum + (clip?.steps?.length || 0), 0);
    this.hud.textContent = `${this.detail?.title || "player"} · ${this.clip} ${n}/${steps.length} · ${total} frames`;
  }

  renderFrameStrip() {
    if (!this.frameStrip) return;
    clear(this.frameStrip);
    const steps = this.clipSteps();
    for (let i = 0; i < steps.length; i += 1) {
      const step = steps[i];
      const img = step.url ? getImage(step.url) : null;
      this.frameStrip.appendChild(h("button", {
        class: `frame-card${i === this.selectedFrame ? " active" : ""}`,
        type: "button",
        onclick: () => {
          this.selectedFrame = i;
          this.playIndex = i;
          this.play = false;
          this.updatePlayButton();
          this.renderAll();
        },
      },
      h("div", { class: "thumb" },
        img ? h("img", { src: step.url, alt: step.texture }) : null),
      h("div", { class: "frame-meta" },
        h("span", { text: String(i) }),
        h("span", { text: `${step.duration}f` })),
      ));
    }
    this.frameStrip.appendChild(h("button", {
      class: "frame-card add", type: "button", title: "Add frame",
      onclick: () => this.addFrameMenu(),
    }, icon("plus"), h("div", { class: "frame-meta", text: "Add" })));
  }

  /* ------------------------------------------------------------------- tabs */
  setTab(id) {
    this.tab = id;
    for (const [key, btn] of Object.entries(this.tabButtons || {})) {
      btn.classList.toggle("active", key === id);
    }
    this.renderTab();
  }

  renderTab() {
    if (!this.tabBody) return;
    if (this.tab === "form") return this.renderFormTab();
    if (this.tab === "stats") return this.renderStatsTab();
    if (this.tab === "help") return this.renderHelpTab();
    return this.renderClipTab();
  }

  field(label, input, note = "") {
    return h("label", { class: "field" },
      h("span", { text: label }), input,
      note ? h("span", { class: "field-note", text: note }) : null);
  }

  numberInput(value, onChange, { min = 0, max = 9999 } = {}) {
    const input = h("input", {
      type: "number", min: String(min), max: String(max), value: String(value),
      onchange: () => {
        onChange(clamp(Number(input.value) || 0, min, max));
        input.value = String(clamp(Number(input.value) || 0, min, max));
      },
    });
    return input;
  }

  renderClipTab() {
    clear(this.tabBody);
    const clip = this.clipData(this.clip);
    const steps = this.clipSteps();
    if (!clip) {
      this.tabBody.append(
        h("div", { class: "field-note",
          text: `Clip "${this.clip}" is empty. Add a frame from an asset or upload one.` }),
        h("button", {
          class: "btn primary", type: "button", text: "Add first frame",
          onclick: () => this.addFrameMenu(),
        }),
      );
      return;
    }
    const loopBox = h("input", {
      type: "checkbox", checked: !!clip.loop,
      onchange: () => {
        clip.loop = loopBox.checked;
        this.markDirty();
        this.renderClipList();
        this.invalidate();
      },
    });
    this.tabBody.append(
      h("div", { class: "row wrap" },
        h("label", { class: "check" }, loopBox, "Loop this clip"),
        h("span", { class: "grow" }),
        h("span", { class: "badge", text: `${steps.length} frames` }),
      ),
      h("div", { class: "row wrap" },
        h("button", {
          class: "btn small", type: "button", text: "Add frame",
          onclick: () => this.addFrameMenu(),
        }),
        h("button", {
          class: "btn small", type: "button", text: "From asset",
          onclick: () => this.showAssetPicker(),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Upload",
          onclick: () => this.pickUpload(),
        }),
      ),
      h("div", { class: "obj-list" },
        steps.map((step, index) => this.frameRow(step, index))),
      this.currentFrame() ? this.frameEditor(this.currentFrame()) : null,
      h("div", { class: "field-note",
        text: "Anchor = the pixel placed on Firebrand's world position: X is the body centre, Y the feet. Duration is in 60 Hz ticks." }),
    );
  }

  frameRow(step, index) {
    return h("div", {
      class: `obj-row${index === this.selectedFrame ? " active" : ""}`,
      onclick: () => {
        this.selectedFrame = index;
        this.play = false;
        this.playIndex = index;
        this.updatePlayButton();
        this.renderAll();
      },
    },
    h("span", { class: "label", text: `${index}. ${step.texture}` }),
    h("span", { class: "coords",
      text: `${step.anchor_x},${step.anchor_y} · ${step.duration}f` }),
    );
  }

  frameEditor(frame) {
    const anchorX = this.numberInput(frame.anchor_x, (v) => {
      frame.anchor_x = v;
      this.markDirty();
      this.invalidate();
      this.renderFrameStrip();
    });
    const anchorY = this.numberInput(frame.anchor_y, (v) => {
      frame.anchor_y = v;
      this.markDirty();
      this.invalidate();
      this.renderFrameStrip();
    });
    const duration = this.numberInput(frame.duration, (v) => {
      frame.duration = Math.max(1, v);
      this.markDirty();
      this.renderFrameStrip();
    }, { min: 1, max: 120 });
    const index = this.selectedFrame;
    return h("div", { class: "frame-editor" },
      h("div", { class: "small dim", text: `Selected frame ${index}` }),
      h("div", { class: "row" },
        this.field("Anchor X", anchorX), this.field("Anchor Y", anchorY),
        this.field("Duration", duration)),
      h("div", { class: "row wrap" },
        h("button", {
          class: "btn small", type: "button", text: "<- Move",
          onclick: () => this.moveFrame(-1),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Move ->",
          onclick: () => this.moveFrame(1),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Duplicate",
          onclick: () => this.duplicateFrame(),
        }),
        h("button", {
          class: "btn small", type: "button", text: "Replace image",
          onclick: () => this.showAssetPicker({ replace: true }),
        }),
        h("button", {
          class: "btn small danger", type: "button", text: "Delete",
          onclick: () => this.deleteFrame(),
        }),
      ),
    );
  }

  renderFormTab() {
    clear(this.tabBody);
    const isForm = this.detail?.kind === "form";
    const nameInput = h("input", {
      type: "text",
      value: this.entry?.name || "",
      disabled: !isForm,
      oninput: () => {
        this.entry.name = nameInput.value;
        this.markDirty();
        this.renderFormList();
      },
    });
    const clips = Object.keys(this.clips);
    this.tabBody.append(
      h("div", { class: "small dim",
        text: isForm ? `Crest form ${this.detail.form}` : "Shared base sheet" }),
      this.field("Display name", nameInput,
        isForm ? "Shown in the editor only; the game names forms in code." : ""),
      h("div", { class: "kv" },
        h("dt", { text: "Target" }), h("dd", { text: this.detail?.title || this.target }),
        h("dt", { text: "Source" }), h("dd", { text: this.source }),
        h("dt", { text: "Clips" }), h("dd", { text: String(clips.length) }),
        h("dt", { text: "Frames" }), h("dd", { text: String(this.totalFrames()) }),
      ),
      h("hr"),
      h("div", { class: "small dim", text: "Clip overview" }),
      h("div", { class: "obj-list" },
        CLIPS.map((name) => h("div", { class: "obj-row", onclick: () => {
          this.clip = name;
          this.selectedFrame = 0;
          this.playTimer = 0;
          this.play = true;
          this.updatePlayButton();
          this.renderAll();
        } },
        h("span", { class: "label", text: name }),
        h("span", { class: "coords",
          text: `${this.clipSteps(name).length} frames${this.clipData(name)?.loop ? " · loop" : ""}` }),
        ))),
      h("hr"),
      h("div", { class: "small dim", text: "Validation" }),
      this.lastValidation
        ? h("div", { class: "field-note", text: `${this.lastValidation.errors?.length || 0} error(s), ${this.lastValidation.warnings?.length || 0} warning(s)` })
        : h("div", { class: "field-note", text: "Click Validate to check images, anchors and clip lengths." }),
      h("button", {
        class: "btn small", type: "button", text: "Validate now",
        onclick: () => this.validate(),
      }),
    );
  }

  renderStatsTab() {
    clear(this.tabBody);
    this.tabBody.append(
      h("div", { class: "small dim", text: "Engine constants (read-only)" }),
      h("div", { class: "kv" },
        ...ENGINE_STATS.flatMap(([label, value]) => [
          h("dt", { text: label }), h("dd", { text: value }),
        ])),
      h("div", { class: "field-note",
        text: "Movement, hitbox and shot timings live in dcpy/player.py. The editor changes animation sheets and form names only; changing physics needs a code edit." }),
      h("hr"),
      h("div", { class: "small dim", text: "Form coverage" }),
      h("div", { class: "obj-list" },
        (this.overview?.forms || []).map((form) => h("div", { class: "obj-row" },
          h("span", { class: "label", text: `${form.form} · ${form.name}` }),
          h("span", { class: "coords", text: `${form.clip_count} clips · ${form.steps} frames` }),
        ))),
    );
  }

  renderHelpTab() {
    clear(this.tabBody);
    this.tabBody.append(
      h("div", { class: "small dim", text: "Player Editor" }),
      h("p", { class: "field-note",
        text: "The base sheet is Firebrand's shared animation. Each of the six crest forms has its own clips; the game picks a form's sheet by crest_form, falling back to the base when a form is missing." }),
      h("p", { class: "field-note",
        text: "Edits are authored overrides. Save writes player_anim.json (base) or player_forms.json (one form per entry); the runtime merges them over assets/generated. Revert removes the authored entry." }),
      h("div", { class: "kv" },
        h("dt", { text: "Space" }), h("dd", { text: "play / pause" }),
        h("dt", { text: "Left / Right" }), h("dd", { text: "previous / next frame" }),
        h("dt", { text: "Ctrl+S" }), h("dd", { text: "save" }),
        h("dt", { text: "Delete" }), h("dd", { text: "delete selected frame" }),
      ),
      h("div", { class: "field-note",
        text: "The 12 x 22 dashed box is Firebrand's gameplay hitbox; it is drawn from the anchor, so use it to check where the feet land." }),
    );
  }

  totalFrames() {
    return Object.values(this.clips)
      .reduce((sum, clip) => sum + (clip?.steps?.length || 0), 0);
  }

  /* --------------------------------------------------------------- frames */
  ensureClip(name = this.clip) {
    if (!this.clips[name]) {
      this.clips[name] = { loop: defaultLoop(name), steps: [] };
    }
    if (!Array.isArray(this.clips[name].steps)) this.clips[name].steps = [];
    return this.clips[name];
  }

  async addFrameMenu() {
    showModal({
      title: "Add frame",
      body: h("div", { class: "field wide" },
        h("div", { class: "field-note",
          text: `Add to clip "${this.clip}". Frames are ordered; use the arrows to reorder.` }),
        h("div", { class: "row wrap" },
          h("button", {
            class: "btn primary", type: "button", text: "From asset",
            onclick: (close) => { close(); this.showAssetPicker(); },
          }),
          h("button", {
            class: "btn", type: "button", text: "Upload PNG",
            onclick: (close) => { close(); this.pickUpload(); },
          }),
          h("button", {
            class: "btn", type: "button", text: "Duplicate selected",
            onclick: (close) => { close(); this.duplicateFrame(); },
          }),
        ),
      ),
      narrow: true,
      actions: [{ label: "Cancel" }],
    });
  }

  addFrameFromAsset(asset, { replace = false } = {}) {
    const texture = textureFromAsset(asset);
    if (!texture) return;
    const clip = this.ensureClip();
    const width = Number(asset.width) || 0;
    const height = Number(asset.height) || 0;
    const step = {
      texture,
      url: asset.url,
      actual_width: width,
      actual_height: height,
      width,
      height,
      anchor_x: Math.round(width / 2),
      anchor_y: height,
      duration: 6,
    };
    if (replace && this.currentFrame()) {
      const index = this.selectedFrame;
      const old = clip.steps[index];
      clip.steps[index] = { ...step, anchor_x: old.anchor_x, anchor_y: old.anchor_y, duration: old.duration };
    } else {
      clip.steps.push(step);
      this.selectedFrame = clip.steps.length - 1;
    }
    this.markDirty();
    this.play = false;
    this.playIndex = this.selectedFrame;
    this.updatePlayButton();
    this.renderAll();
    this.invalidate();
    if (step.url) loadImage(step.url).then(() => this.renderAll()).catch(() => {});
  }

  async pickUpload({ replace = false } = {}) {
    const input = h("input", { type: "file", accept: "image/png" });
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const data = await readFileDataURL(file);
        const result = await api.upload(file.name, data);
        if (!result.ok) throw new Error(result.error || "upload failed");
        this.addFrameFromAsset({
          name: result.texture.split("/").pop(),
          path: `assets/authored/${result.texture}`,
          source: "authored",
          url: result.url,
          width: result.width,
          height: result.height,
        }, { replace });
      } catch (error) {
        toast(`Upload failed: ${error.message}`, "error");
      }
    });
    input.click();
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
    let query = this.detail?.kind === "base" ? "player_" : "fb_";
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
          title: `${img.path} · ${img.width}x${img.height}`,
          onclick: () => {
            dlg.close();
            this.addFrameFromAsset(img, { replace });
          },
        },
        h("img", { src: img.url, loading: "lazy", alt: img.name }),
        h("div", { class: "meta" },
          h("div", { class: "n", text: img.name }),
          h("div", { class: "s", text: `${img.width}x${img.height}` })),
        ));
      }
    };
    const search = h("input", {
      type: "search", placeholder: "Filter PNGs...", value: query,
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

  moveFrame(delta) {
    const clip = this.ensureClip();
    const index = this.selectedFrame;
    const next = index + delta;
    if (next < 0 || next >= clip.steps.length) return;
    const [step] = clip.steps.splice(index, 1);
    clip.steps.splice(next, 0, step);
    this.selectedFrame = next;
    this.markDirty();
    this.renderAll();
  }

  duplicateFrame() {
    const frame = this.currentFrame();
    if (!frame) return;
    const clip = this.ensureClip();
    const copy = { ...frame };
    clip.steps.splice(this.selectedFrame + 1, 0, copy);
    this.selectedFrame += 1;
    this.markDirty();
    this.renderAll();
  }

  deleteFrame() {
    const clip = this.ensureClip();
    if (!clip.steps.length) return;
    clip.steps.splice(this.selectedFrame, 1);
    this.selectedFrame = clamp(this.selectedFrame, 0,
      Math.max(0, clip.steps.length - 1));
    this.markDirty();
    this.renderAll();
  }

  /* ------------------------------------------------------------- persistence */
  stripEntry() {
    const clips = {};
    for (const name of CLIPS) {
      const clip = this.clips[name];
      if (!clip) continue;
      const steps = (clip.steps || [])
        .filter((step) => step && step.texture)
        .map(stripStep);
      if (!steps.length) continue;
      clips[name] = { loop: !!clip.loop, steps };
    }
    const entry = { clips };
    if (this.detail?.kind === "form") {
      entry.form = this.detail.form;
      entry.name = String(this.entry?.name || "").trim() ||
        this.detail.title;
    }
    return entry;
  }

  async validate() {
    try {
      const result = await api.validatePlayer(this.target, this.stripEntry());
      this.lastValidation = result;
      this.validateBadge.textContent = result.errors?.length
        ? `${result.errors.length} error(s)`
        : result.warnings?.length
          ? `${result.warnings.length} warning(s)` : "Valid";
      this.validateBadge.className = `badge ${result.errors?.length ? "red" :
        result.warnings?.length ? "gold" : "green"}`;
      showModal({
        title: `Validate ${this.detail?.title || this.target}`,
        body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
          h("div", { class: "field-note",
            text: "Frames need a texture, anchor and duration. The loader keeps 64 total steps across all clips." }),
          result.errors?.length || result.warnings?.length
            ? h("div", { class: "obj-list" },
              [...(result.errors || []), ...(result.warnings || [])].map((item) =>
                h("div", { class: "obj-row" },
                  h("span", { class: "label", text: item.message }),
                  h("span", { class: "coords", text: item.level }))))
            : h("div", { class: "field-note", text: "No problems found." }),
        ),
        wide: true,
        actions: [{ label: "Close", primary: true }],
      });
      this.renderTab();
      return result;
    } catch (error) {
      toast(`Validation failed: ${error.message}`, "error");
      return null;
    }
  }

  async save() {
    if (this.saveBtn) this.saveBtn.disabled = true;
    try {
      const result = await api.savePlayer(this.target, this.stripEntry());
      if (!result.ok) {
        toast("Fix validation errors before saving.", "error");
        this.lastValidation = result.validation;
        this.validateBadge.textContent = "Blocked";
        this.validateBadge.className = "badge red";
        return;
      }
      this.detail = await api.playerEntry(this.target);
      this.entry = this.detail.entry;
      this.clips = deepClone(this.entry.clips || {});
      this.source = this.detail.source;
      this.dirty = false;
      this.syncSource();
      await this.loadOverview();
      this.renderAll();
      this.markClean();
      toast("Player sheet saved to the authored overlay.", "ok");
    } catch (error) {
      toast(`Save failed: ${error.message}`, "error");
    } finally {
      if (this.saveBtn) this.saveBtn.disabled = false;
    }
  }

  async revert() {
    if (!this.detail?.overridden) {
      toast("This is the generated sheet; there is no override to revert.", "warn");
      return;
    }
    const ok = await confirmDialog("Revert to generated?",
      "The authored override for this player target is removed.",
      { okLabel: "Revert", danger: true });
    if (!ok) return;
    try {
      await api.deletePlayer(this.target);
      await this.loadOverview();
      await this.loadTarget(this.target, { initial: true });
      toast("Reverted to the generated sheet.", "ok");
    } catch (error) {
      toast(`Revert failed: ${error.message}`, "error");
    }
  }

  /* ---------------------------------------------------------------- keys */
  bindKeys() {
    this._onKey = (event) => {
      const tag = event.target?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (event.key === " ") {
        event.preventDefault();
        this.togglePlay();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        this.selectedFrame = clamp(this.selectedFrame - 1, 0,
          Math.max(0, this.clipSteps().length - 1));
        this.play = false;
        this.playIndex = this.selectedFrame;
        this.updatePlayButton();
        this.renderAll();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        this.selectedFrame = clamp(this.selectedFrame + 1, 0,
          Math.max(0, this.clipSteps().length - 1));
        this.play = false;
        this.playIndex = this.selectedFrame;
        this.updatePlayButton();
        this.renderAll();
      } else if (event.key === "Delete") {
        event.preventDefault();
        this.deleteFrame();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        this.save();
      }
    };
    window.addEventListener("keydown", this._onKey);
  }

  unbindKeys() {
    if (this._onKey) window.removeEventListener("keydown", this._onKey);
  }
}
