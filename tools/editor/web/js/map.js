/* Map Builder: room visualisation, collision/tile painting, objects, doors,
   spawns, bounds, music and a game-accurate camera preview. */

import { api } from "./api.js";
import {
  $, h, clear, fitCanvas, getImage, loadImage, clamp, fmod, floorAt,
  decodeTile, encodeTile, surfaceOffset, deepClone, downloadCanvas,
  speciesHex, padHex,
} from "./util.js";
import { icon } from "./icons.js";
import {
  toast, showModal, confirmDialog, showSpeciesPicker, section, issueList,
  playAudio, stopAudio, speciesThumb,
} from "./ui.js";

const TILE = 8;
const CELL = 16;
const VIEW_W = 256;
const VIEW_H = 224;

const OBJECT_COLORS = {
  enemy: "#d06a8a",
  boss: "#b98ae0",
  urn: "#cf9a55",
  platform: "#9aa0b2",
  pickup_crest: "#e0c14a",
  exit: "#4fc9a8",
  npc: "#79a8e8",
  talisman: "#e08a3c",
  unknown: "#e05a8a",
  decor: "#7d8a5a",
  inert: "#555a66",
};

const RECT_COLORS = {
  play: "#e0b95c",
  camera: "#7aa7e8",
  viewport: "#d9dce6",
};

function clampView(v, lo, hi) { return clamp(v, lo, hi); }

export class MapEditor {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    const [routeArea, routeMode] = String(arg || "").split("/");
    this.area = Number.parseInt(routeArea, 10);
    if (!Number.isFinite(this.area) || this.area < 0) {
      this.area = app.rooms[0]?.area ?? 2;
    }
    this.initialPreview = routeMode === "preview";
    this.initialCompare = routeMode === "compare";
    this.initialMode = ["collision", "tiles", "tile", "object"].includes(routeMode)
      ? (routeMode === "collision" ? "collision" :
        routeMode === "object" ? "object" : "tile") : null;
    this.routeArg = String(this.area);
    this.room = null;
    this.assets = null;
    this.source = "generated";
    this.authored = false;
    this.generated = false;
    this.validation = null;
    this.dirty = false;
    this.originalRoom = null;
    this.compareToOriginal = false;

    this.tool = "select";
    this.brush = { shape: 1, env: 0, size: 1, mode: "paint" };
    this.tile = { layer: 1, pal: 0, index: 0, flipH: false, flipV: false };
    this.show = {
      bg0: true, bg1: true, collision: false, objects: true, bounds: true,
      grid: true, labels: true, transitions: true,
    };
    this.showMinimap = true;
    this.navHistory = [];
    this._spawnCache = new Map();
    this.view = { x: 0, y: 0, zoom: 1 };
    this.preview = { on: false, x: 0, y: 0 };
    this.selection = null;
    this.hover = null;
    this.undoStack = [];
    this.redoStack = [];
    this.drag = null;
    this.stroke = null;
    this.spaceDown = false;
    this.needsRender = true;
    this.raf = 0;
    this.destroyed = false;
    this._resizeObserver = null;
    this._previewImage = null;
    this._place = { type: "enemy", speciesKey: null, flags: 0 };
    this.clipboard = null;
  }

  /* -------------------------------------------------------------- lifecycle */
  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    this.bindCanvas();
    this.bindMinimapEvents();
    this._resizeObserver = new ResizeObserver(() => {
      this.resizeCanvas();
      this.invalidate();
    });
    this._resizeObserver.observe(this.canvasHost);
    this.bindKeys();
    await this.loadRoom(this.area, { initial: true });
    if (this.app.pendingObject && this.app.pendingObject.area === this.area) {
      const pending = this.app.pendingObject;
      this.app.pendingObject = null;
      const index = Number(pending.index);
      const obj = this.room.objects?.[index];
      if (obj) {
        this.select({ kind: "object", index });
        this.centerOn(obj.x, obj.y);
      }
    }
    if (this.initialPreview) this.togglePreview(true);
    if (this.initialCompare) {
      if (this.compareCheck) this.compareCheck.checked = true;
      await this.setCompareToOriginal(true);
    }
    if (this.initialMode) {
      if (this.initialMode === "collision") this.show.collision = true;
      this.setTool(this.initialMode);
      this.syncViewChecks();
      if (this.initialMode === "tile" && this.bgSection) {
        this.bgSection.el.open = true;
      }
      if (this.initialMode === "object" && (this.room.objects || []).length) {
        this.select({ kind: "object", index: 0 });
        this.centerOn(this.room.objects[0].x, this.room.objects[0].y);
      }
    }
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
  dirtyPromptKey() { return `#map/${this.area}`; }

  markDirty() {
    if (!this.dirty) {
      this.dirty = true;
      this.app.setSaveState("dirty", "Unsaved");
      this.saveBtn?.classList.add("primary");
      if (this.saveLabel) this.saveLabel.textContent = "Save *";
    }
  }

  markClean() {
    this.dirty = false;
    this.app.setSaveState("saved", "Saved");
    this.saveBtn?.classList.remove("primary");
    if (this.saveLabel) this.saveLabel.textContent = "Save";
  }

  invalidate() { this.needsRender = true; }

  startLoop() {
    const loop = () => {
      if (this.destroyed) return;
      if (this.needsRender) {
        this.needsRender = false;
        try { this.render(); } catch (error) {
          console.error(error);
          const hud = document.getElementById("map-hud-cursor");
          if (hud) hud.textContent = `Render error: ${error.message}`;
        }
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
    this.saveMenuBtn = h("button", {
      class: "btn icon", type: "button", title: "Save options…",
      onclick: () => this.showSaveMenu(),
    }, "▾");
    this.undoBtn = h("button", {
      class: "btn icon", type: "button", title: "Undo (Ctrl+Z)",
      onclick: () => this.undo(),
    }, icon("undo"));
    this.redoBtn = h("button", {
      class: "btn icon", type: "button", title: "Redo (Ctrl+Y)",
      onclick: () => this.redo(),
    }, icon("redo"));
    this.zoomLabel = h("span", { class: "zoom-label", text: "100%" });
    this.validationBadge = h("button", {
      class: "btn ghost small", type: "button", title: "Show validation",
      onclick: () => this.showValidation(),
    }, "Validate");

    this.roomSelect = h("select", { class: "room-select", title: "Room" });
    this.roomSelect.addEventListener("change", () => {
      const area = Number(this.roomSelect.value);
      if (area === this.area) return;
      if (this.dirty) {
        confirmDialog("Discard unsaved changes?",
          "Loading another room will discard the current edits.",
          { okLabel: "Discard & load", danger: true }).then((ok) => {
          if (ok) this.loadRoom(area);
          else this.roomSelect.value = String(this.area);
        });
      } else {
        this.loadRoom(area);
      }
    });

    const toolBtn = (tool, iconName, label, key) => h("button", {
      class: "tool-btn", type: "button", title: `${label} (${key})`,
      dataset: { tool },
      onclick: () => this.setTool(tool),
    }, icon(iconName), h("span", { text: label }), h("kbd", { text: key }));

    this.toolButtons = [
      toolBtn("select", "cursor", "Select", "V"),
      toolBtn("collision", "collision", "Collision", "C"),
      toolBtn("tile", "tile", "Tiles", "T"),
      toolBtn("object", "skull", "Objects", "O"),
      toolBtn("door", "door", "Door", "D"),
      toolBtn("spawn", "spawn", "Spawn", "S"),
      toolBtn("pan", "move", "Pan", "H"),
    ];

    this.previewBtn = h("button", {
      class: "tool-btn", type: "button", title: "Game preview (P)",
      onclick: () => this.togglePreview(),
    }, icon("eye"), h("span", { text: "Preview" }));
    this.renderBtn = h("button", {
      class: "btn small", type: "button",
      title: "Render this room with the actual game engine",
      onclick: () => this.renderInGame(),
    }, icon("play"), h("span", { text: "Render in game" }));
    this.minimapBtn = h("button", {
      class: `btn icon ${this.showMinimap ? "active" : ""}`, type: "button",
      title: "Toggle Minimap (M)",
      onclick: () => this.toggleMinimap(),
    }, icon("minimap"));
    this.exportMapBtn = h("button", {
      class: "btn small", type: "button",
      title: "Export full composite room map as PNG",
      onclick: () => this.exportFullRoomPng(),
    }, icon("download"), h("span", { text: "Full map PNG" }));
    this.helpBtn = h("button", {
      class: "btn icon", type: "button",
      title: "Keyboard shortcuts (?)",
      onclick: () => this.showShortcutsHelp(),
    }, icon("info"));

    this.backBtn = h("button", {
      class: "btn small", type: "button", style: { display: "none" },
      title: "Go back to previous room",
      onclick: () => {
        if (this.navHistory && this.navHistory.length) {
          const prev = this.navHistory.pop();
          this.requestLoadArea(prev, false);
        }
      },
    }, h("span", { id: "map-back-label", text: "← Back" }));

    const toolbar = h("div", { class: "toolbar" },
      h("span", { class: "toolbar-title", text: "Room" }),
      this.roomSelect,
      this.backBtn,
      h("button", {
        class: "btn icon", type: "button", title: "New room…",
        onclick: () => this.showNewRoomDialog(),
      }, icon("plus")),
      h("button", {
        class: "btn icon", type: "button", title: "Reload from disk",
        onclick: () => this.reload(),
      }, icon("refresh")),
      this.saveBtn, this.saveMenuBtn,
      h("div", { class: "sep" }),
      h("span", { class: "toolbar-title", text: "Tool" }),
      ...this.toolButtons,
      h("div", { class: "sep" }),
      this.undoBtn, this.redoBtn,
      h("div", { class: "sep" }),
      h("button", {
        class: "btn icon", type: "button", title: "Zoom out (-)",
        onclick: () => this.zoomBy(1 / 1.25),
      }, icon("zoomOut")),
      this.zoomLabel,
      h("button", {
        class: "btn icon", type: "button", title: "Zoom in (+)",
        onclick: () => this.zoomBy(1.25),
      }, icon("zoomIn")),
      h("button", {
        class: "btn icon", type: "button", title: "Fit room (0)",
        onclick: () => this.fit(),
      }, icon("fit")),
      h("div", { class: "sep" }),
      this.previewBtn,
      this.renderBtn,
      this.minimapBtn,
      this.exportMapBtn,
      this.helpBtn,
      h("span", { class: "grow" }),
      this.validationBadge,
    );

    this.canvas = h("canvas", { id: "map-canvas" });
    this.minimapCanvas = h("canvas", { class: "minimap-canvas" });
    this.minimapHost = h("div", { id: "map-minimap", title: "Click/drag to navigate room (M)" }, this.minimapCanvas);
    if (!this.showMinimap) this.minimapHost.classList.add("hidden");

    this.canvasHost = h("div", { class: "canvas-host" },
      this.canvas,
      this.minimapHost,
      h("div", { class: "canvas-vignette" }),
      h("div", { class: "canvas-hud" },
        h("div", { class: "chip", id: "map-hud-room", text: "—" }),
        h("div", { class: "chip", id: "map-hud-cursor", text: "—" }),
        h("div", { class: "chip", id: "map-hud-status", text: "" }),
      ),
      h("div", { class: "canvas-help" },
        h("div", { class: "hint", id: "map-hint",
          text: "Wheel zoom · middle/space drag to pan · click to select" }),
        h("div", { class: "canvas-legend", id: "map-legend" },
          h("span", {}, h("i", { class: "legend-dot", style: { background: "#4fc98a" } }), "solid"),
          h("span", {}, h("i", { class: "legend-dot", style: { background: "#e06060" } }), "hazard"),
          h("span", {}, h("i", { class: "legend-dot", style: { background: "#5a9ae0" } }), "water"),
          h("span", {}, h("i", { class: "legend-dot", style: { background: "#e0a13c" } }), "breakable"),
        ),
      ),
      h("div", { class: "canvas-hud", id: "preview-bar",
        style: { left: "auto", right: "8px", display: "none",
          pointerEvents: "auto" } },
        h("div", { class: "chip", text: "GAME PREVIEW 256×224" }),
        h("div", { class: "chip", id: "preview-coords", text: "camera 0,0" }),
        h("div", { class: "row" },
          h("button", {
            class: "btn small", type: "button", text: "At spawn",
            onclick: () => this.previewAtSpawn(),
          }),
          h("button", {
            class: "btn small", type: "button", text: "At camera",
            onclick: () => this.previewAtCamera(),
          }),
          h("button", {
            class: "btn small", type: "button", text: "PNG",
            onclick: () => this.savePreviewPng(),
          }),
          h("button", {
            class: "btn small", type: "button", text: "Full PNG",
            onclick: () => this.exportFullRoomPng(),
          }),
        ),
      ),
    );

    this.leftPanel = h("aside", { class: "panel left" });
    this.rightPanel = h("aside", { class: "panel right" });
    this.buildLeftPanel();
    this.buildRightPanel();

    this.el = h("div", { class: "editor map-editor" },
      toolbar,
      h("div", { class: "editor-body" },
        this.leftPanel,
        this.canvasHost,
        this.rightPanel,
      ),
    );
  }

  /* ------------------------------------------------------------- left panel */
  buildLeftPanel() {
    clear(this.leftPanel);
    this.leftPanel.appendChild(h("div", { class: "panel-head" },
      icon("map"), h("span", { text: "Room" })));

    /* Map ------------------------------------------------------------ */
    this.nameInput = h("input", {
      type: "text", placeholder: "Room name",
      oninput: () => { this.room.name = this.nameInput.value; this.markDirty(); },
    });
    this.areaLabel = h("span", { class: "mono dim" });
    this.atlasSelect = h("select", {
      onchange: () => {
        this.room.bg_atlas_area = Number(this.atlasSelect.value);
        this.markDirty();
        this.refreshRoomAssets();
      },
    });
    this.musicSelect = h("select", {
      onchange: () => {
        if (this.musicSelect.value === "") delete this.room.music;
        else this.room.music = Number(this.musicSelect.value);
        this.markDirty();
        this.syncMusicButton();
      },
    });
    this.musicPlayBtn = h("button", {
      class: "btn icon", type: "button", title: "Preview music",
      onclick: () => this.playMusicPreview(),
    }, icon("music"));
    this.sourceBadge = h("span", { class: "badge" });
    this.backdropColor = h("input", {
      type: "color",
      oninput: () => {
        const hex = this.backdropColor.value;
        this.room.backdrop = [
          parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16),
          parseInt(hex.slice(5, 7), 16),
        ];
        this.markDirty();
        this.invalidate();
      },
    });
    this.backdropParallax = h("input", {
      type: "number", step: "0.05", min: "0", max: "8",
      oninput: () => {
        this.room.backdrop_parallax = Number(this.backdropParallax.value) || 0;
        this.markDirty(); this.invalidate();
      },
    });
    this.backdropY = h("input", {
      type: "number", step: "1",
      oninput: () => {
        this.room.backdrop_y = Number(this.backdropY.value) || 0;
        this.markDirty(); this.invalidate();
      },
    });
    this.gateNext = h("input", {
      type: "number", step: "1", min: "0",
      oninput: () => {
        this.room.gate_next_area = Number(this.gateNext.value);
        this.markDirty();
      },
    });
    this.gateMarker = h("input", {
      type: "number", step: "1",
      oninput: () => {
        this.room.gate_marker = Number(this.gateMarker.value);
        this.markDirty();
      },
    });
    this.gateEntry = h("input", {
      type: "number", step: "1",
      oninput: () => {
        this.room.gate_entry = Number(this.gateEntry.value);
        this.markDirty();
      },
    });

    const mapSec = section("Room & Music", { open: true });
    mapSec.body.append(
      h("div", { class: "row" }, this.sourceBadge, h("span", { class: "grow" }),
        this.areaLabel),
      h("div", { class: "field wide" }, h("span", { text: "Name" }), this.nameInput),
      h("div", { class: "field" }, h("span", { text: "Tile atlas" }), this.atlasSelect),
      h("div", { class: "field" }, h("span", { text: "Music" }),
        h("div", { class: "row" }, this.musicSelect, this.musicPlayBtn)),
      h("div", { class: "field-2" },
        h("div", { class: "field wide" }, h("span", { text: "Backdrop" }), this.backdropColor),
        h("div", { class: "field wide" }, h("span", { text: "Parallax" }), this.backdropParallax),
      ),
      h("div", { class: "field" }, h("span", { text: "Backdrop Y" }), this.backdropY),
      h("details", { class: "section-inner" },
        h("summary", { class: "small dim", text: "Gate / room flags" }),
        h("div", { style: { display: "flex", flexDirection: "column", gap: "6px",
          marginTop: "6px" } },
          h("div", { class: "field" }, h("span", { text: "Gate area" }), this.gateNext),
          h("div", { class: "field" }, h("span", { text: "Gate marker" }), this.gateMarker),
          h("div", { class: "field" }, h("span", { text: "Gate entry" }), this.gateEntry),
        ),
      ),
    );

    /* World & bounds ------------------------------------------------- */
    this.worldW = h("input", {
      type: "number", step: "8", min: "256",
      oninput: () => { this.pendingWidth = Number(this.worldW.value); },
    });
    this.worldH = h("input", {
      type: "number", step: "8", min: "224",
      oninput: () => { this.pendingHeight = Number(this.worldH.value); },
    });
    this.resizeBtn = h("button", {
      class: "btn small", type: "button", text: "Resize…",
      onclick: () => this.showResizeDialog(),
    });
    const playInput = (key) => h("input", {
      type: "number", step: "1",
      oninput: (event) => {
        this.room.play[key] = Number(event.target.value);
        this.markDirty(); this.invalidate();
      },
    });
    this.playMinX = playInput("min_x");
    this.playMaxX = playInput("max_x");
    this.playMinY = playInput("min_y");
    this.playMaxY = playInput("max_y");
    const camInput = (key) => h("input", {
      type: "number", step: "1",
      oninput: (event) => {
        this.room.camera[key] = Number(event.target.value);
        this.markDirty(); this.invalidate();
      },
    });
    this.camMinX = camInput("min_x");
    this.camMaxX = camInput("max_x");
    this.camMinY = camInput("min_y");
    this.camMaxY = camInput("max_y");
    this.camX = h("input", {
      type: "number", step: "1",
      oninput: (event) => {
        this.room.camera.x = Number(event.target.value);
        this.markDirty(); this.invalidate();
      },
    });
    this.camY = h("input", {
      type: "number", step: "1",
      oninput: (event) => {
        this.room.camera.y = Number(event.target.value);
        this.markDirty(); this.invalidate();
      },
    });
    const worldSec = section("World & Bounds", { open: true });
    worldSec.body.append(
      h("div", { class: "field" }, h("span", { text: "World" }),
        h("div", { class: "row" }, this.worldW, h("span", { class: "muted", text: "×" }),
          this.worldH, this.resizeBtn)),
      h("div", { class: "tiny muted", text: "play bounds (px)" }),
      h("div", { class: "field-4" }, this.playMinX, this.playMaxX,
        this.playMinY, this.playMaxY),
      h("div", { class: "tiny muted", text: "camera limits (px)" }),
      h("div", { class: "field-4" }, this.camMinX, this.camMaxX,
        this.camMinY, this.camMaxY),
      h("div", { class: "tiny muted", text: "camera start (px)" }),
      h("div", { class: "field-4" }, this.camX, this.camY),
    );

    /* View ----------------------------------------------------------- */
    const toggle = (key, label) => {
      const input = h("input", {
        type: "checkbox", checked: this.show[key],
        onchange: (event) => {
          this.show[key] = event.target.checked;
          this.invalidate();
        },
      });
      this.viewChecks[key] = input;
      return h("label", { class: "check" }, input, label);
    };
    this.viewChecks = {};
    const viewSec = section("View", { open: true });
    this.compareCheck = h("input", {
      type: "checkbox", checked: false,
      onchange: () => this.setCompareToOriginal(this.compareCheck.checked),
    });
    viewSec.body.append(
      h("div", { class: "row wrap" },
        toggle("bg0", "BG0"), toggle("bg1", "BG1"),
        toggle("collision", "Collision"), toggle("objects", "Objects"),
        toggle("transitions", "Doors"), toggle("bounds", "Bounds"),
        toggle("grid", "Grid"), toggle("labels", "Labels"),
      ),
      h("label", { class: "check" }, this.compareCheck,
        "Compare current collision/objects with generated"),
      h("div", { class: "field-note",
        text: "Collision overlay shows the gameplay shape and the 0x20/40/60/80 environment flags. Compare highlights every cell that differs from assets/generated." }),
    );

    /* Backgrounds ---------------------------------------------------- */
    this.bg0Info = h("div", { class: "field-note" });
    this.bg1Info = h("div", { class: "field-note" });
    this.bg0ScrollX = h("input", {
      type: "number", step: "1", oninput: (e) => {
        this.room.bg[0].scroll_x = Number(e.target.value);
        this.markDirty(); this.invalidate(); this.drawTilePicker();
      },
    });
    this.bg0ScrollY = h("input", {
      type: "number", step: "1", oninput: (e) => {
        this.room.bg[0].scroll_y = Number(e.target.value);
        this.markDirty(); this.invalidate(); this.drawTilePicker();
      },
    });
    this.tileLayerSelect = h("select", {
      onchange: () => {
        this.tile.layer = Number(this.tileLayerSelect.value);
        this.tile.index = 0; this.tile.pal = 0;
        this.refreshPaletteTabs(); this.drawTilePicker();
        this.setTool("tile");
      },
    },
    h("option", { value: "1", text: "BG1 · world layer" }),
    h("option", { value: "0", text: "BG0 · parallax layer" }));
    this.paletteTabs = h("div", { class: "palette-tabs" });
    this.tileCanvas = h("canvas", { id: "tile-picker", width: "512", height: "512" });
    this.tileSelectedPreview = h("canvas", { class: "preview", width: "64", height: "64" });
    this.tileSelectedText = h("div", { class: "small mono dim" });
    this.tileFlipH = h("input", {
      type: "checkbox", onchange: () => {
        this.tile.flipH = this.tileFlipH.checked; this.drawTilePicker();
      },
    });
    this.tileFlipV = h("input", {
      type: "checkbox", onchange: () => {
        this.tile.flipV = this.tileFlipV.checked; this.drawTilePicker();
      },
    });
    this.tilePickInfo = h("div", { class: "field-note" });
    const bgSec = section("Backgrounds", { open: false });
    this.bgSection = bgSec;
    bgSec.body.append(
      h("div", { class: "field" }, h("span", { text: "Tile layer" }), this.tileLayerSelect),
      this.paletteTabs,
      h("div", { class: "tile-picker-wrap" }, this.tileCanvas),
      h("div", { class: "tile-selected" }, this.tileSelectedPreview,
        h("div", { class: "grow" }, this.tileSelectedText,
          h("div", { class: "row small" },
            h("label", { class: "check" }, this.tileFlipH, "Flip H"),
            h("label", { class: "check" }, this.tileFlipV, "Flip V"),
          ),
        ),
      ),
      this.tilePickInfo,
      h("div", { class: "field-note",
        text: "Left click paints the tile, right click erases, Alt+click picks." }),
      h("hr"),
      this.bg0Info, this.bg1Info,
      h("div", { class: "field" }, h("span", { text: "BG0 scroll X" }), this.bg0ScrollX),
      h("div", { class: "field" }, h("span", { text: "BG0 scroll Y" }), this.bg0ScrollY),
    );

    /* Collision ------------------------------------------------------ */
    this.shapeGrid = h("div", { class: "shape-grid" });
    this.envButtons = h("div", { class: "row wrap" });
    this.brushSummary = h("div", { class: "field-note" });
    this.collisionStats = h("div", { class: "field-note" });
    this.brushSize = h("select", {
      onchange: () => {
        this.brush.size = Number(this.brushSize.value);
        this.brushSummary.textContent = this.brushDescription();
      },
    },
    h("option", { value: "1", text: "1 × 1 cell" }),
    h("option", { value: "2", text: "2 × 2 cells" }),
    h("option", { value: "3", text: "3 × 3 cells" }),
    h("option", { value: "4", text: "4 × 4 cells" }));
    this.preserveShape = h("input", {
      type: "checkbox", onchange: () => {
        this.brush.preserveShape = this.preserveShape.checked;
        this.brushSummary.textContent = this.brushDescription();
      },
    });
    this.paintMode = "paint";
    this.modeButtons = ["paint", "rect", "fill"].map((mode) => h("button", {
      class: `btn small${mode === "paint" ? " active" : ""}`, type: "button",
      text: mode === "paint" ? "Paint" : mode === "rect" ? "Rectangle" : "Fill",
      onclick: () => {
        this.paintMode = mode; this.brush.mode = mode;
        this.modeButtons.forEach((b) => b.classList.toggle("active",
          b.textContent.toLowerCase().startsWith(mode)));
        this.setTool("collision");
      },
    }));
    const colSec = section("Collision & Hazards", { open: true });
    colSec.body.append(
      h("div", { class: "row wrap" }, ...this.modeButtons,
        h("span", { class: "muted small", text: "Brush" }), this.brushSize),
      h("label", { class: "check" }, this.preserveShape,
        "Keep the existing shape when painting a flag"),
      this.shapeGrid,
      h("div", { class: "tiny muted", text: "Environment flag (applies on top of the shape)" }),
      this.envButtons,
      this.brushSummary,
      h("hr"),
      this.collisionStats,
      h("div", { class: "field-note",
        text: "Alt+click picks the cell under the cursor. Right click erases. Hazard, water and breakable live in the top three attr bits." }),
    );

    /* Objects -------------------------------------------------------- */
    this.objectTypeSelect = h("select", {
      onchange: () => {
        this._place.type = this.objectTypeSelect.value;
        this.updatePlaceChip();
        this.setTool("object");
      },
    });
    this.placeChip = h("div", { class: "species-chip" });
    this.placeFlags = h("input", {
      type: "number", step: "1", min: "0", max: "255", value: "0",
      oninput: () => { this._place.flags = Number(this.placeFlags.value) || 0; },
    });
    this.placeBtn = h("button", {
      class: "btn primary", type: "button", text: "Place on map",
      onclick: () => this.setTool("object"),
    });
    this.objectList = h("div", { class: "obj-list" });
    this.objectFilter = h("input", {
      type: "search", placeholder: "Filter objects…",
      oninput: () => this.refreshObjectList(),
    });
    const objSec = section("Objects & Doors", { open: false });
    objSec.body.append(
      h("div", { class: "field" }, h("span", { text: "Type" }), this.objectTypeSelect),
      this.placeChip,
      h("div", { class: "field" }, h("span", { text: "Flags" }), this.placeFlags),
      h("div", { class: "row" }, this.placeBtn,
        h("button", {
          class: "btn", type: "button", text: "Choose…",
          onclick: () => this.choosePlaceSpecies(),
        })),
      h("div", { class: "row" },
        h("button", {
          class: "btn small", type: "button", text: "+ Door",
          onclick: () => this.setTool("door"),
        }),
        h("button", {
          class: "btn small", type: "button", text: "+ Spawn",
          onclick: () => this.setTool("spawn"),
        }),
        h("span", { class: "grow" }),
        h("span", { class: "muted small", text: "click map to add" }),
      ),
      h("hr"),
      this.objectFilter,
      this.objectList,
    );

    for (const sec of [mapSec, worldSec, viewSec, bgSec, colSec, objSec]) {
      this.leftPanel.appendChild(sec.el);
    }
    this.buildShapePalette();
    this.buildEnvButtons();
  }

  buildShapePalette() {
    clear(this.shapeGrid);
    const shapes = this.app.meta?.shape_values || [];
    this.shapeButtons = new Map();
    for (const shape of shapes) {
      const canvas = h("canvas", { width: "64", height: "32" });
      const btn = h("button", {
        class: "shape-btn", type: "button",
        title: `${shape.label} · 0x${padHex(shape.value)}`,
        onclick: () => {
          this.brush.shape = shape.value;
          this.updateShapeSelection();
          this.setTool("collision");
        },
      }, canvas, h("span", { text: shape.value === 0 ? "Clear" : padHex(shape.value) }));
      this.shapeButtons.set(shape.value, btn);
      this.shapeGrid.appendChild(btn);
      this.drawShapeThumb(canvas, shape.value);
    }
    this.updateShapeSelection();
  }

  drawShapeThumb(canvas, attr) {
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const hgt = canvas.height;
    ctx.clearRect(0, 0, w, hgt);
    ctx.fillStyle = "#0c0e13";
    ctx.fillRect(0, 0, w, hgt);
    if (!attr) {
      ctx.strokeStyle = "#3a4050";
      ctx.setLineDash([2, 2]);
      ctx.strokeRect(1, 1, w - 2, hgt - 2);
      return;
    }
    const sx = w / 16;
    const sy = hgt / 20;
    const pts = [];
    for (let x = 0; x < 16; x += 1) {
      const off = surfaceOffset(attr, x);
      if (off < 0) continue;
      pts.push([x * sx, 4 + off * sy]);
    }
    if (pts.length) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const [x, y] of pts) ctx.lineTo(x, y);
      ctx.lineTo(w, hgt);
      ctx.lineTo(0, hgt);
      ctx.closePath();
      ctx.fillStyle = "rgba(121,208,189,.14)";
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const [x, y] of pts) ctx.lineTo(x, y);
      ctx.strokeStyle = "#79d0bd";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  buildEnvButtons() {
    clear(this.envButtons);
    this.envButtonsData = this.app.meta?.env_flags || [
      { value: 0, label: "None" }, { value: 0x20, label: "Hazard" },
      { value: 0x40, label: "Breakable" }, { value: 0x60, label: "Water" },
      { value: 0x80, label: "Slope ramp" },
    ];
    this.envButtonsData.forEach((env) => {
      const btn = h("button", {
        class: `btn small${this.brush.env === env.value ? " active" : ""}`,
        type: "button", text: env.label,
        onclick: () => {
          this.brush.env = env.value;
          [...this.envButtons.children].forEach((b, i) => {
            b.classList.toggle("active", this.envButtonsData[i].value === env.value);
          });
          this.brushSummary.textContent = this.brushDescription();
          this.setTool("collision");
        },
      });
      this.envButtons.appendChild(btn);
    });
  }

  brushDescription() {
    const shape = this.app.meta?.shape_values?.find((s) => s.value === this.brush.shape);
    const env = this.app.meta?.env_flags?.find((e) => e.value === this.brush.env);
    const value = (this.brush.shape | this.brush.env) & 0xff;
    return `Attr 0x${padHex(value, 2)} · ${shape?.label || "Empty"}${this.brush.env ? " + " + env?.label : ""}${this.brush.preserveShape ? " · keep shape" : ""} · ${this.brush.size}×${this.brush.size} · ${this.paintMode}`;
  }

  updateShapeSelection() {
    for (const [value, btn] of this.shapeButtons || []) {
      btn.classList.toggle("active", value === this.brush.shape);
    }
    if (this.brushSummary) this.brushSummary.textContent = this.brushDescription();
  }

  /* ------------------------------------------------------------ right panel */
  buildRightPanel() {
    clear(this.rightPanel);
    this.rightPanel.appendChild(h("div", { class: "panel-head" },
      icon("info"), h("span", { text: "Inspector" })));
    this.inspectorTitle = h("div", { class: "inspector-title" },
      h("span", { class: "name", text: "Nothing selected" }));
    this.inspectorBody = h("div", { class: "inspector-content" });
    this.rightPanel.append(this.inspectorTitle, this.inspectorBody);
    this.refreshInspector();
  }

  /* ------------------------------------------------------------- room load */
  async loadRoom(area, { initial = false } = {}) {
    this.app.setStatus(`Loading area ${area}…`);
    const data = await api.room(area);
    this.area = area;
    this.routeArg = String(area);
    this.room = data.room;
    this.assets = data.assets;
    this.source = data.source;
    this.authored = data.authored;
    this.generated = data.generated;
    this.validation = data.validation;
    this.selection = null;
    this.undoStack = [];
    this.redoStack = [];
    this.dirty = false;
    this.originalRoom = null;
    this.compareToOriginal = false;
    if (this.compareCheck) this.compareCheck.checked = false;
    this.fillRoomSelect();
    this.roomSelect.value = String(area);
    history.replaceState(null, "", `#map/${area}`);
    this.app.setSaveState("saved", this.source === "authored" ? "Override" : "Generated");
    this.saveBtn.classList.remove("primary");
    if (this.saveLabel) this.saveLabel.textContent = "Save";
    this.syncRoomInputs();
    this.refreshAllPanels();
    this.resizeCanvas();
    this.fit();
    await this.preloadRoomImages();
    this.invalidate();
    this.updateStatus();
    const label = data.label || `Area ${area}`;
    $("#map-hud-room") && ($("#map-hud-room").innerHTML =
      `${label} · <b>${this.room.world.width}×${this.room.world.height}</b>`);
    if (!initial) toast(`Loaded ${label}`, "ok", 1600);
    this.updateBackBtn();
    this.app.setStatus(`Room: ${label}`,
      `${this.room.world.width}×${this.room.world.height} · ${this.room.objects?.length || 0} objects`);
  }

  async refreshRoomAssets() {
    try {
      const data = await api.roomAssets(this.area, this.room.bg_atlas_area);
      this.assets = data.assets;
      await this.preloadRoomImages();
      this.refreshPaletteTabs();
      this.drawTilePicker();
      this.invalidate();
    } catch (error) {
      toast(`Could not load atlas: ${error.message}`, "error");
    }
  }

  async setCompareToOriginal(on) {
    if (!on) {
      this.compareToOriginal = false;
      this.originalRoom = null;
      this.refreshCollisionStats();
      this.refreshInspector();
      this.invalidate();
      return;
    }
    if (!this.generated) {
      this.compareCheck.checked = false;
      toast("This room has no generated original to compare with.", "warn");
      return;
    }
    try {
      const data = await api.originalRoom(this.area);
      this.originalRoom = data.room;
      this.compareToOriginal = true;
      const diff = this.diffSummary();
      toast(`Comparing with generated · ${diff?.collision || 0} changed collision cells`,
        "ok", 2200);
      this.refreshCollisionStats();
      this.refreshInspector();
      this.invalidate();
    } catch (error) {
      this.compareCheck.checked = false;
      toast(`Could not load generated room: ${error.message}`, "error");
    }
  }

  diffSummary() {
    const orig = this.originalRoom;
    if (!orig || !this.room) return null;
    const cur = this.room;
    const oc = orig.collision || {};
    const cc = cur.collision || {};
    let collision = 0;
    const rows = Math.min(oc.height || 0, cc.height || 0);
    const cols = Math.min(oc.width || 0, cc.width || 0);
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) {
        const a = oc.attrs?.[y * oc.width + x] ?? 0;
        const b = cc.attrs?.[y * cc.width + x] ?? 0;
        if (a !== b) collision += 1;
      }
    }
    if (oc.width !== cc.width || oc.height !== cc.height) collision += 1;
    const countDiff = (a, b) => {
      const aa = Array.isArray(a) ? a : [];
      const bb = Array.isArray(b) ? b : [];
      let changed = 0;
      for (let i = 0; i < Math.max(aa.length, bb.length); i += 1) {
        if (JSON.stringify(aa[i] ?? null) !== JSON.stringify(bb[i] ?? null)) {
          changed += 1;
        }
      }
      return changed;
    };
    const fields = [];
    for (const key of ["world", "play", "camera", "spawn", "music",
      "bg_atlas_area", "backdrop", "backdrop_parallax", "backdrop_y"]) {
      if (JSON.stringify(orig[key] ?? null) !== JSON.stringify(cur[key] ?? null)) {
        fields.push(key);
      }
    }
    return {
      collision,
      objects: countDiff(orig.objects, cur.objects),
      doors: countDiff(orig.transitions, cur.transitions),
      spawns: countDiff(orig.spawns, cur.spawns),
      fields,
    };
  }

  preloadRoomImages() {
    const urls = [];
    for (const set of [this.assets?.bg0, this.assets?.bg1]) {
      for (const tex of set || []) if (tex?.url) urls.push(tex.url);
    }
    if (this.assets?.backdrop?.url) urls.push(this.assets.backdrop.url);
    if (this.assets?.player?.url) urls.push(this.assets.player.url);
    if (this.assets?.item?.url) urls.push(this.assets.item.url);
    if (this.assets?.heart?.url) urls.push(this.assets.heart.url);
    for (const obj of this.room?.objects || []) {
      const sp = this.app.speciesFor(obj.species, obj.flags);
      if (sp?.first_frame?.url) urls.push(sp.first_frame.url);
    }
    const status = document.getElementById("map-hud-status");
    this.assetsReady = false;
    if (status) {
      status.style.display = "";
      status.textContent = `Loading ${urls.length} images…`;
    }
    const promise = Promise.all([...new Set(urls)].map((u) => loadImage(u)));
    promise.then(() => {
      this.assetsReady = true;
      if (status) {
        status.textContent = "";
        status.style.display = "none";
      }
      this.invalidate();
    });
    return promise;
  }

  /* -------------------------------------------------------------- sync UI */
  fillRoomSelect() {
    if (!this.roomSelect) return;
    clear(this.roomSelect);
    const rooms = [...this.app.rooms].sort((a, b) => a.area - b.area);
    for (const room of rooms) {
      const suffix = room.source === "authored" ? " · edited" : "";
      this.roomSelect.appendChild(h("option", {
        value: room.area,
        text: `${room.label}${suffix}`,
        selected: room.area === this.area,
      }));
    }
    if (!rooms.some((room) => room.area === this.area)) {
      this.roomSelect.appendChild(h("option", {
        value: this.area, text: `Area ${this.area} · New room`,
        selected: true,
      }));
    }
    this.roomSelect.value = String(this.area);
  }

  syncRoomInputs() {
    if (!this.room) return;
    const set = (el, value) => {
      if (document.activeElement === el) return;
      el.value = value ?? "";
    };
    set(this.nameInput, this.room.name);
    this.areaLabel.textContent = `area ${this.area}`;
    this.worldW.value = this.room.world.width;
    this.worldH.value = this.room.world.height;
    this.pendingWidth = this.room.world.width;
    this.pendingHeight = this.room.world.height;
    const atlas = this.room.bg_atlas_area ?? this.area;
    this.fillAtlasSelect(atlas);
    this.fillMusicSelect();
    set(this.backdropParallax, this.room.backdrop_parallax ?? 0.5);
    set(this.backdropY, this.room.backdrop_y ?? 0);
    const rgb = this.room.backdrop || [8, 8, 16];
    this.backdropColor.value =
      `#${rgb.map((c) => padHex(clamp(Number(c) || 0, 0, 255), 2)).join("")}`;
    set(this.playMinX, this.room.play.min_x);
    set(this.playMaxX, this.room.play.max_x);
    set(this.playMinY, this.room.play.min_y);
    set(this.playMaxY, this.room.play.max_y);
    set(this.camMinX, this.room.camera.min_x);
    set(this.camMaxX, this.room.camera.max_x);
    set(this.camMinY, this.room.camera.min_y);
    set(this.camMaxY, this.room.camera.max_y);
    set(this.camX, this.room.camera.x);
    set(this.camY, this.room.camera.y);
    set(this.gateNext, this.room.gate_next_area ?? 0);
    set(this.gateMarker, this.room.gate_marker ?? 0);
    set(this.gateEntry, this.room.gate_entry ?? 0);
    set(this.bg0ScrollX, this.room.bg[0]?.scroll_x ?? 0);
    set(this.bg0ScrollY, this.room.bg[0]?.scroll_y ?? 0);
    this.sourceBadge.textContent = this.source === "authored" ? "Authored override" :
      this.source === "new" ? "New room" : "Generated";
    this.sourceBadge.className = `badge ${this.source === "authored" ? "gold" :
      this.source === "new" ? "green" : "blue"}`;
    if (this.compareCheck) this.compareCheck.disabled = !this.generated;
    this.syncMusicButton();
    this.updateValidationBadge();
  }

  fillAtlasSelect(current) {
    clear(this.atlasSelect);
    const areas = [...new Set([...this.app.rooms.map((r) => r.area), current])]
      .sort((a, b) => a - b);
    for (const area of areas) {
      const label = this.app.rooms.find((r) => r.area === area)?.label ||
        `Area ${area}`;
      this.atlasSelect.appendChild(h("option", {
        value: area, selected: area === current,
        text: `${label} (${area})`,
      }));
    }
  }

  fillMusicSelect() {
    clear(this.musicSelect);
    const fallback = this.app.meta?.default_music?.[String(this.area)];
    this.musicSelect.appendChild(h("option", {
      value: "",
      selected: this.room.music === undefined || this.room.music === null,
      text: `Area default (${this.app.meta?.music?.[fallback]?.name || "?"})`,
    }));
    for (const track of this.app.meta?.music || []) {
      this.musicSelect.appendChild(h("option", {
        value: track.id, selected: Number(this.room.music) === track.id,
        text: `${track.id} · ${track.name}`,
      }));
    }
  }

  syncMusicButton() {
    const trackId = this.room.music ?? this.app.meta?.default_music?.[String(this.area)];
    const track = this.app.meta?.music?.[trackId];
    this.musicPlayBtn.disabled = !track?.url;
    this.musicPlayBtn.title = track?.url
      ? `Preview “${track.name}”` : "This track has no rendered WAV";
  }

  playMusicPreview() {
    const trackId = this.room.music ?? this.app.meta?.default_music?.[String(this.area)];
    const track = this.app.meta?.music?.[trackId];
    if (!track?.url) { toast("No audio file for this track.", "warn"); return; }
    const playing = playAudio(track.url, 0.5);
    toast(`${playing ? "Playing" : "Stopped"} ${track.name}`, "", 1200);
  }

  refreshAllPanels() {
    this.syncRoomInputs();
    this.refreshBackgroundInfo();
    this.refreshPaletteTabs();
    this.drawTilePicker();
    this.refreshCollisionStats();
    this.refreshPlaceOptions();
    this.refreshObjectList();
    this.refreshInspector();
    this.updateShapeSelection();
    this.updateToolUi();
    this.updateUndoUi();
    this.updateValidationBadge();
  }

  refreshBackgroundInfo() {
    const bg0 = this.room.bg[0] || {};
    const bg1 = this.room.bg[1] || {};
    this.bg0Info.textContent =
      `BG0 ${bg0.map_width}×${bg0.map_height} tiles · ${this.assets?.has_bg2 ? "bg2 atlas" : "bg1 atlas fallback"}`;
    this.bg1Info.textContent =
      `BG1 ${bg1.map_width}×${bg1.map_height} tiles · world layer`;
  }

  refreshCollisionStats() {
    const col = this.room.collision;
    let solid = 0, hazard = 0, water = 0, breakable = 0, slope = 0;
    for (const attr of col.attrs) {
      if (attr & 0x1f) solid += 1;
      const env = attr & 0xe0;
      if (env === 0x20) hazard += 1;
      else if (env === 0x40) breakable += 1;
      else if (env === 0x60) water += 1;
      else if (env === 0x80) slope += 1;
    }
    this.collisionStats.textContent =
      `${col.width}×${col.height} cells · solid ${solid} · hazard ${hazard} · water ${water} · breakable ${breakable} · ramp ${slope}` +
      (this.originalRoom ? ` · ${this.diffSummary()?.collision || 0} changed vs generated` : "");
    this.brushSummary.textContent = this.brushDescription();
  }

  refreshPlaceOptions() {
    clear(this.objectTypeSelect);
    for (const type of this.app.meta?.object_types || []) {
      this.objectTypeSelect.appendChild(h("option", {
        value: type.value, text: type.label,
        selected: type.value === this._place.type,
      }));
    }
    if (!this._place.speciesKey) {
      const firstEnemy = this.app.species.find((s) => s.kind === "enemy") ||
        this.app.species[0];
      this._place.speciesKey = firstEnemy?.key || null;
    }
    this.updatePlaceChip();
    this.placeFlags.value = this._place.flags;
  }

  updatePlaceChip() {
    clear(this.placeChip);
    const type = this._place.type;
    const needsSpecies = ["enemy", "boss", "npc", "urn", "pickup_crest", "decor", "inert", "unknown"].includes(type);
    if (!needsSpecies) {
      this.placeChip.append(
        h("div", { class: "meta" },
          h("div", { class: "n", text: this.app.meta?.object_types?.find((t) => t.value === type)?.label || type }),
          h("div", { class: "s", text: "No species" })),
      );
      return;
    }
    const sp = this.app.peakSpecies(this._place.speciesKey);
    this.placeChip.append(
      speciesThumb(sp, 40),
      h("div", { class: "meta" },
        h("div", { class: "n", text: sp?.name || "No species" }),
        h("div", { class: "s", text: sp ? `${sp.species_hex} · ${sp.key}` : "Choose…" })),
    );
  }

  async choosePlaceSpecies() {
    const chosen = await showSpeciesPicker(this.app.species,
      this._place.speciesKey, { title: "Species to place" });
    if (!chosen) return;
    this._place.speciesKey = chosen.key;
    this._place.flags = chosen.variant === "boss" ? chosen.flags : this._place.flags;
    this.placeFlags.value = this._place.flags;
    this.updatePlaceChip();
    this.setTool("object");
  }

  refreshPaletteTabs() {
    clear(this.paletteTabs);
    const set = this.tile.layer === 0 ? this.assets?.bg0 : this.assets?.bg1;
    for (let pal = 0; pal < 8; pal += 1) {
      const tex = set?.[pal];
      const btn = h("button", {
        class: `palette-tab${this.tile.pal === pal ? " active" : ""}`,
        type: "button", text: String(pal), disabled: !tex?.url,
        title: tex?.url ? `Palette ${pal}` : "Palette not present in this atlas",
        onclick: () => {
          this.tile.pal = pal;
          this.refreshPaletteTabs();
          this.drawTilePicker();
        },
      });
      this.paletteTabs.appendChild(btn);
    }
    if (!set?.[this.tile.pal]?.url) {
      const first = set?.findIndex((t) => t?.url);
      if (first >= 0) {
        this.tile.pal = first;
        this.refreshPaletteTabs();
      }
    }
  }

  drawTilePicker() {
    if (!this.tileCanvas) return;
    const ctx = this.tileCanvas.getContext("2d");
    const w = this.tileCanvas.width;
    const hgt = this.tileCanvas.height;
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, w, hgt);
    ctx.fillStyle = "#0a0b0f";
    ctx.fillRect(0, 0, w, hgt);
    const set = this.tile.layer === 0 ? this.assets?.bg0 : this.assets?.bg1;
    const tex = set?.[this.tile.pal];
    const img = tex?.url ? getImage(tex.url) : null;
    if (img) {
      ctx.drawImage(img, 0, 0, 256, 256, 0, 0, w, hgt);
    } else {
      if (tex?.url) loadImage(tex.url).then(() => this.drawTilePicker());
      ctx.fillStyle = "#2a2e3a";
      ctx.font = "14px monospace";
      ctx.fillText("palette not loaded", 14, 28);
    }
    // Grid: 32 × 32 base tiles, each drawn at 16 px in this 512 px view.
    const step = w / 32;
    ctx.strokeStyle = "rgba(220,225,235,.12)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 32; i += 1) {
      ctx.beginPath(); ctx.moveTo(i * step, 0); ctx.lineTo(i * step, hgt); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i * step); ctx.lineTo(w, i * step); ctx.stroke();
    }
    const sx = (this.tile.index % 32) * step;
    const sy = Math.floor(this.tile.index / 32) * step;
    ctx.strokeStyle = "#e0a13c";
    ctx.lineWidth = 3;
    ctx.strokeRect(sx + 1.5, sy + 1.5, step - 3, step - 3);
    ctx.fillStyle = "rgba(224,161,60,.16)";
    ctx.fillRect(sx, sy, step, step);
    // Selected preview, with flips.
    const pctx = this.tileSelectedPreview.getContext("2d");
    pctx.imageSmoothingEnabled = false;
    pctx.clearRect(0, 0, 64, 64);
    pctx.fillStyle = "#0a0b0f";
    pctx.fillRect(0, 0, 64, 64);
    if (img) {
      pctx.save();
      pctx.translate(this.tile.flipH ? 64 : 0, this.tile.flipV ? 64 : 0);
      pctx.scale(this.tile.flipH ? -1 : 1, this.tile.flipV ? -1 : 1);
      pctx.drawImage(img, (this.tile.index % 32) * 8,
        Math.floor(this.tile.index / 32) * 8, 8, 8, 0, 0, 64, 64);
      pctx.restore();
    }
    this.tileSelectedText.textContent =
      `tile ${this.tile.index} · pal ${this.tile.pal}` +
      (this.tile.flipH ? " · flipH" : "") + (this.tile.flipV ? " · flipV" : "");
    const word = encodeTile(this.tile.index, this.tile.pal, this.tile.flipH,
      this.tile.flipV);
    this.tilePickInfo.textContent =
      `word 0x${padHex(word, 4)} · layer ${this.tile.layer === 0 ? "BG0" : "BG1"}`;
  }

  /* --------------------------------------------------------------- canvas */
  bindCanvas() {
    const canvas = this.canvas;
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event));
    canvas.addEventListener("pointermove", (event) => this.onPointerMove(event));
    canvas.addEventListener("pointerup", (event) => this.onPointerUp(event));
    canvas.addEventListener("pointercancel", (event) => this.onPointerUp(event));
    canvas.addEventListener("pointerleave", () => {
      this.hover = null;
      this.invalidate();
    });
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      if (this.preview.on) return;
      const { px, py } = this.eventCss(event);
      const before = this.screenToWorld(px, py);
      const factor = Math.exp(-event.deltaY * 0.0014);
      this.zoomBy(factor, px, py, before);
    }, { passive: false });
    this.tileCanvas.addEventListener("pointerdown", (event) => {
      const rect = this.tileCanvas.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width * 512;
      const y = (event.clientY - rect.top) / rect.height * 512;
      const tileX = Math.floor(x / 16);
      const tileY = Math.floor(y / 16);
      if (tileX < 0 || tileY < 0 || tileX >= 32 || tileY >= 32) return;
      this.tile.index = tileY * 32 + tileX;
      this.drawTilePicker();
      this.setTool("tile");
    });
  }

  resizeCanvas() {
    if (!this.canvas) return;
    const size = fitCanvas(this.canvas);
    this.canvasSize = size;
    this.dpr = size.dpr;
    this.cssW = size.width / size.dpr;
    this.cssH = size.height / size.dpr;
    this.invalidate();
  }

  eventCss(event) {
    const rect = this.canvas.getBoundingClientRect();
    return { px: event.clientX - rect.left, py: event.clientY - rect.top };
  }

  screenToWorld(px, py) {
    return {
      x: this.view.x + px / this.view.zoom,
      y: this.view.y + py / this.view.zoom,
    };
  }

  worldToScreen(wx, wy) {
    return {
      x: (wx - this.view.x) * this.view.zoom,
      y: (wy - this.view.y) * this.view.zoom,
    };
  }

  fit() {
    if (!this.room || !this.cssW) return;
    const w = this.room.world.width;
    const hgt = this.room.world.height;
    const pad = 32;
    const z = Math.min((this.cssW - pad) / w, (this.cssH - pad) / hgt);
    this.view.zoom = clamp(z, 0.08, 8);
    this.view.x = (w - this.cssW / this.view.zoom) / 2;
    this.view.y = (hgt - this.cssH / this.view.zoom) / 2;
    this.updateZoomLabel();
    this.invalidate();
  }

  zoomBy(factor, anchorX = null, anchorY = null, before = null) {
    if (!this.room) return;
    const px = anchorX ?? this.cssW / 2;
    const py = anchorY ?? this.cssH / 2;
    const world = before || this.screenToWorld(px, py);
    this.view.zoom = clamp(this.view.zoom * factor, 0.08, 8);
    this.view.x = world.x - px / this.view.zoom;
    this.view.y = world.y - py / this.view.zoom;
    this.updateZoomLabel();
    this.invalidate();
  }

  updateZoomLabel() {
    this.zoomLabel.textContent = `${Math.round(this.view.zoom * 100)}%`;
  }

  /* --------------------------------------------------------------- render */
  render() {
    if (!this.canvas || !this.room) return;
    const dpr = this.dpr || 1;
    const ctx = this.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, this.cssW, this.cssH);
    ctx.fillStyle = "#06070a";
    ctx.fillRect(0, 0, this.cssW, this.cssH);
    if (this.preview.on) {
      this.renderPreview(ctx);
      return;
    }
    ctx.setTransform(dpr * this.view.zoom, 0, 0, dpr * this.view.zoom,
      -this.view.x * this.view.zoom * dpr, -this.view.y * this.view.zoom * dpr);

    this.drawBackdropEdit(ctx);
    if (this.show.bg0) this.drawLayer(ctx, 0);
    if (this.show.bg1) this.drawLayer(ctx, 1);
    if (this.show.collision) this.drawCollision(ctx);
    if (this.compareToOriginal) this.drawCollisionDiff(ctx);
    if (this.show.objects) this.drawObjects(ctx);
    if (this.show.transitions) this.drawTransitions(ctx);
    if (this.show.bounds) this.drawBounds(ctx);
    this.drawSpawns(ctx);
    this.drawGrid(ctx);
    this.drawSelectionWorld(ctx);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.drawLabels(ctx);
    this.drawHud(ctx);
    this.drawMinimap();
  }

  visibleWorldRect() {
    return {
      x: this.view.x,
      y: this.view.y,
      w: this.cssW / this.view.zoom,
      h: this.cssH / this.view.zoom,
    };
  }

  layerOrigin(index) {
    if (index === 1) {
      const layer = this.room.bg[1];
      return { x: 0, y: layer.offset_y || 0 };
    }
    const layer = this.room.bg[0];
    return {
      x: (layer.scroll_x || 0) - (this.room.camera.x || 0),
      y: (layer.scroll_y || 0) - (this.room.camera.y || 0),
    };
  }

  drawLayer(ctx, index) {
    const layer = this.room.bg[index];
    if (!layer) return;
    const origin = this.layerOrigin(index);
    const clip = this.visibleWorldRect();
    const set = index === 0 ? this.assets?.bg0 : this.assets?.bg1;
    this.drawLayerTiles(ctx, layer, set, origin.x, origin.y,
      clip.x, clip.y, clip.x + clip.w, clip.y + clip.h, false, false);
  }

  drawLayerTiles(ctx, layer, palettes, originX, originY,
    clipX, clipY, clipX2, clipY2, wrapX, wrapY) {
    const mw = layer.map_width | 0;
    const mh = layer.map_height | 0;
    if (!mw || !mh) return;
    const tx0 = Math.floor((clipX - originX) / TILE) - 1;
    const tx1 = Math.ceil((clipX2 - originX) / TILE) + 1;
    const ty0 = Math.floor((clipY - originY) / TILE) - 1;
    const ty1 = Math.ceil((clipY2 - originY) / TILE) + 1;
    const tiles = layer.tilemap || [];
    for (let ty = ty0; ty <= ty1; ty += 1) {
      let mapTy = ty;
      if (wrapY) mapTy = ((ty % mh) + mh) % mh;
      else if (ty < 0 || ty >= mh) continue;
      const row = mapTy * mw;
      for (let tx = tx0; tx <= tx1; tx += 1) {
        let mapTx = tx;
        if (wrapX) mapTx = ((tx % mw) + mw) % mw;
        else if (tx < 0 || tx >= mw) continue;
        const word = tiles[row + mapTx];
        if (!word) continue;
        const pal = (word >> 10) & 7;
        const tex = palettes?.[pal];
        const img = tex?.url ? getImage(tex.url) : null;
        if (!img) {
          if (tex?.url) loadImage(tex.url).then(() => this.invalidate());
          continue;
        }
        const decoded = decodeTile(word);
        const dx = originX + tx * TILE;
        const dy = originY + ty * TILE;
        ctx.drawImage(img, decoded.srcX, decoded.srcY, TILE, TILE,
          dx, dy, TILE, TILE);
      }
    }
  }

  drawBackdropEdit(ctx) {
    const tex = this.assets?.backdrop;
    if (!tex?.url) return;
    const img = getImage(tex.url);
    if (!img) { loadImage(tex.url).then(() => this.invalidate()); return; }
    const clip = this.visibleWorldRect();
    const parallax = Number(this.room.backdrop_parallax) || 0;
    const y = Number(this.room.backdrop_y) || 0;
    let off = -fmod(this.view.x * parallax, img.width);
    if (off > 0) off -= img.width;
    ctx.save();
    ctx.globalAlpha = 0.5;
    for (let x = off; x < clip.x + clip.w; x += img.width) {
      ctx.drawImage(img, x, y);
    }
    ctx.restore();
  }

  drawGrid(ctx) {
    if (!this.show.grid) return;
    const clip = this.visibleWorldRect();
    const zoom = this.view.zoom;
    const step = CELL;
    const skip = step * zoom < 5 ? 4 : 1;
    ctx.save();
    ctx.lineWidth = 1 / zoom;
    ctx.strokeStyle = "rgba(160,170,190,.075)";
    const x0 = Math.floor(clip.x / step) * step;
    const y0 = Math.floor(clip.y / step) * step;
    ctx.beginPath();
    for (let x = x0; x < clip.x + clip.w; x += step * skip) {
      ctx.moveTo(x, clip.y); ctx.lineTo(x, clip.y + clip.h);
    }
    for (let y = y0; y < clip.y + clip.h; y += step * skip) {
      ctx.moveTo(clip.x, y); ctx.lineTo(clip.x + clip.w, y);
    }
    ctx.stroke();
    // 128 px major grid.
    ctx.strokeStyle = "rgba(224,161,60,.10)";
    ctx.beginPath();
    for (let x = Math.floor(clip.x / 128) * 128; x < clip.x + clip.w; x += 128) {
      ctx.moveTo(x, clip.y); ctx.lineTo(x, clip.y + clip.h);
    }
    for (let y = Math.floor(clip.y / 128) * 128; y < clip.y + clip.h; y += 128) {
      ctx.moveTo(clip.x, y); ctx.lineTo(clip.x + clip.w, y);
    }
    ctx.stroke();
    // World border.
    ctx.strokeStyle = "rgba(224,161,60,.32)";
    ctx.lineWidth = 1.5 / zoom;
    ctx.strokeRect(0, 0, this.room.world.width, this.room.world.height);
    // Tile grid while painting tiles.
    if (this.tool === "tile" && zoom >= 1) {
      ctx.strokeStyle = "rgba(121,208,189,.10)";
      ctx.lineWidth = 1 / zoom;
      ctx.beginPath();
      for (let x = Math.floor(clip.x / TILE) * TILE; x < clip.x + clip.w;
        x += TILE) {
        ctx.moveTo(x, clip.y); ctx.lineTo(x, clip.y + clip.h);
      }
      for (let y = Math.floor(clip.y / TILE) * TILE; y < clip.y + clip.h;
        y += TILE) {
        ctx.moveTo(clip.x, y); ctx.lineTo(clip.x + clip.w, y);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  drawCollision(ctx, clip = null) {
    const col = this.room.collision;
    const cell = col.cell || CELL;
    const activeClip = clip || this.visibleWorldRect();
    const cx0 = Math.max(0, Math.floor(activeClip.x / cell));
    const cy0 = Math.max(0, Math.floor(activeClip.y / cell));
    const cx1 = Math.min(col.width - 1, Math.ceil((activeClip.x + activeClip.w) / cell));
    const cy1 = Math.min(col.height - 1, Math.ceil((activeClip.y + activeClip.h) / cell));
    const zoom = clip ? 1 : this.view.zoom;
    ctx.save();
    ctx.lineWidth = 1 / zoom;
    for (let cy = cy0; cy <= cy1; cy += 1) {
      for (let cx = cx0; cx <= cx1; cx += 1) {
        const attr = col.attrs[cy * col.width + cx] || 0;
        if (!attr) continue;
        const shape = attr & 0x1f;
        const env = attr & 0xe0;
        const x = cx * cell;
        const y = cy * cell;
        let color = "#4fc98a";
        if (env === 0x20) color = "#e06060";
        else if (env === 0x40) color = "#e0a13c";
        else if (env === 0x60) color = "#5a9ae0";
        else if (env === 0x80) color = "#b98ae0";
        ctx.fillStyle = color + "22";
        ctx.fillRect(x, y, cell, cell);
        if (shape) {
          const pts = [];
          for (let sx = 0; sx < cell; sx += 1) {
            const off = surfaceOffset(attr, sx);
            if (off < 0) continue;
            pts.push([x + sx, y + off]);
          }
          if (pts.length) {
            ctx.beginPath();
            ctx.moveTo(pts[0][0], pts[0][1]);
            for (const [px, py] of pts) ctx.lineTo(px, py);
            ctx.strokeStyle = color;
            ctx.lineWidth = Math.max(1, 1.4 / zoom);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(x, y + cell);
            for (const [px, py] of pts) ctx.lineTo(px, py);
            ctx.lineTo(x + cell, y + cell);
            ctx.closePath();
            ctx.fillStyle = color + "20";
            ctx.fill();
          }
        }
        ctx.strokeStyle = color + "55";
        ctx.lineWidth = 1 / zoom;
        if (zoom >= 0.75) {
          ctx.strokeRect(x + 0.5 / zoom, y + 0.5 / zoom,
            cell - 1 / zoom, cell - 1 / zoom);
        }
      }
    }
    ctx.restore();
  }

  drawCollisionDiff(ctx) {
    const cur = this.room.collision;
    const orig = this.originalRoom?.collision;
    if (!cur || !orig) return;
    const cell = cur.cell || CELL;
    const clip = this.visibleWorldRect();
    const cx0 = Math.max(0, Math.floor(clip.x / cell));
    const cy0 = Math.max(0, Math.floor(clip.y / cell));
    const cx1 = Math.min(cur.width - 1, Math.ceil((clip.x + clip.w) / cell));
    const cy1 = Math.min(cur.height - 1, Math.ceil((clip.y + clip.h) / cell));
    ctx.save();
    ctx.lineWidth = 2 / this.view.zoom;
    for (let cy = cy0; cy <= cy1; cy += 1) {
      for (let cx = cx0; cx <= cx1; cx += 1) {
        const a = (cx < orig.width && cy < orig.height)
          ? (orig.attrs[cy * orig.width + cx] ?? 0) : -1;
        const b = cur.attrs[cy * cur.width + cx] ?? 0;
        if (a === b) continue;
        const x = cx * cell;
        const y = cy * cell;
        ctx.fillStyle = "rgba(255,90,208,.18)";
        ctx.fillRect(x, y, cell, cell);
        ctx.strokeStyle = "#ff5ad0";
        ctx.strokeRect(x + 1 / this.view.zoom, y + 1 / this.view.zoom,
          cell - 2 / this.view.zoom, cell - 2 / this.view.zoom);
      }
    }
    ctx.restore();
  }

  objectArt(obj) {
    const sp = this.app.speciesFor(obj.species, obj.flags);
    const frame = sp?.first_frame;
    if (frame?.url) {
      const img = getImage(frame.url);
      if (!img) { loadImage(frame.url).then(() => this.invalidate()); return null; }
      return {
        img, ax: frame.anchor_x || 0, ay: frame.anchor_y || 0,
        w: img.width, h: img.height, species: sp,
      };
    }
    return null;
  }

  objectBox(obj) {
    if (obj.type === "platform") {
      return { x: obj.x - 16, y: obj.y, w: 32, h: 6 };
    }
    const art = this.objectArt(obj);
    if (art) {
      return { x: obj.x - art.ax, y: obj.y - art.ay,
        w: art.w, h: art.h };
    }
    if (obj.type === "pickup_crest") {
      const tex = this.assets?.heart;
      const img = tex?.url ? getImage(tex.url) : null;
      if (img) return { x: obj.x - img.width / 2, y: obj.y - img.height,
        w: img.width, h: img.height };
    }
    if (obj.type === "talisman") {
      const tex = this.assets?.item;
      const img = tex?.url ? getImage(tex.url) : null;
      if (img) return { x: obj.x - img.width / 2, y: obj.y - img.height,
        w: img.width, h: img.height };
    }
    return { x: obj.x - 8, y: obj.y - 16, w: 16, h: 16 };
  }

  drawObjects(ctx) {
    const list = this.room.objects || [];
    list.forEach((obj, index) => {
      const selected = this.selection?.kind === "object" &&
        this.selection.index === index;
      const art = this.objectArt(obj);
      if (obj.type === "platform") {
        ctx.fillStyle = "#84806f";
        ctx.fillRect(obj.x - 16, obj.y, 32, 6);
        ctx.strokeStyle = "#c8c0a8";
        ctx.lineWidth = 1;
        ctx.strokeRect(obj.x - 16 + 0.5, obj.y + 0.5, 31, 5);
        return;
      }
      if (obj.type === "talisman") {
        const tex = this.assets?.item;
        const img = tex?.url ? getImage(tex.url) : null;
        if (img) {
          const tints = ["#ffe680", "#d2d2e6", "#aac8ff", "#ffc8a0", "#beffbe"];
          ctx.globalAlpha = 0.95;
          ctx.drawImage(img, obj.x - img.width / 2, obj.y - img.height);
          ctx.globalAlpha = 1;
        }
        return;
      }
      if (obj.type === "pickup_crest") {
        const tex = this.assets?.heart;
        const img = tex?.url ? getImage(tex.url) : null;
        if (img) {
          ctx.drawImage(img, obj.x - img.width / 2, obj.y - img.height);
          return;
        }
      }
      if (art) {
        const flip = obj.facing < 0;
        if (flip) {
          ctx.save();
          ctx.translate(obj.x, obj.y);
          ctx.scale(-1, 1);
          ctx.drawImage(art.img, -art.ax, -art.ay);
          ctx.restore();
        } else {
          ctx.drawImage(art.img, obj.x - art.ax, obj.y - art.ay);
        }
      } else {
        const color = OBJECT_COLORS[obj.type] || "#e05a8a";
        ctx.fillStyle = color + "44";
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.fillRect(obj.x - 7, obj.y - 14, 14, 14);
        ctx.strokeRect(obj.x - 7 + 0.5, obj.y - 14 + 0.5, 13, 13);
      }
      if (selected) {
        const box = this.objectBox(obj);
        ctx.strokeStyle = "#ffd36a";
        ctx.lineWidth = Math.max(1, 1.3 / this.view.zoom);
        ctx.setLineDash([4 / this.view.zoom, 3 / this.view.zoom]);
        ctx.strokeRect(box.x - 2, box.y - 2, box.w + 4, box.h + 4);
        ctx.setLineDash([]);
      }
    });
  }

  drawTransitions(ctx) {
    const zoom = this.view.zoom;
    for (let i = 0; i < (this.room.transitions || []).length; i += 1) {
      const tr = this.room.transitions[i];
      const selected = this.selection?.kind === "transition" &&
        this.selection.index === i;
      const x = tr.x - (tr.half_w || 12);
      const y = tr.y - (tr.half_h || 24);
      const w = (tr.half_w || 12) * 2;
      const hgt = (tr.half_h || 24) * 2;
      ctx.fillStyle = selected ? "rgba(121,208,189,.28)" : "rgba(79,201,168,.12)";
      ctx.fillRect(x, y, w, hgt);
      ctx.strokeStyle = selected ? "#a9ffe6" : "#4fc9a8";
      ctx.lineWidth = Math.max(1, 1.2 / zoom);
      ctx.setLineDash([5 / zoom, 3 / zoom]);
      ctx.strokeRect(x + 0.5 / zoom, y + 0.5 / zoom, w, hgt);
      ctx.setLineDash([]);
    }
  }

  drawSpawns(ctx) {
    const primary = this.room.spawn || { x: 0, y: 0 };
    const playerTex = this.assets?.player;
    const img = playerTex?.url ? getImage(playerTex.url) : null;
    if (img) {
      ctx.globalAlpha = 0.82;
      ctx.drawImage(img, primary.x - (this.room.player?.feet_x || 0),
        primary.y - (this.room.player?.feet_y || 0));
      ctx.globalAlpha = 1;
    }
    const drawMarker = (x, y, index, isPrimary) => {
      const selected = this.selection?.kind === "spawn" && this.selection.index === index;
      ctx.strokeStyle = selected ? "#fff3c4" : isPrimary ? "#7fe0a8" : "#4f9a76";
      ctx.lineWidth = Math.max(1, 1.2 / this.view.zoom);
      ctx.beginPath();
      ctx.arc(x, y - 8, 7, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x - 10, y - 8); ctx.lineTo(x + 10, y - 8);
      ctx.moveTo(x, y - 18); ctx.lineTo(x, y + 2);
      ctx.stroke();
    };
    drawMarker(primary.x, primary.y, -1, true);
    (this.room.spawns || []).forEach((sp, i) => {
      if (i === 0 && Math.abs(sp.x - primary.x) < 0.01 &&
          Math.abs(sp.y - primary.y) < 0.01) return;
      drawMarker(sp.x, sp.y, i, false);
    });
  }

  rectFor(kind) {
    if (kind === "play") {
      const p = this.room.play;
      return { x: p.min_x, y: p.min_y, w: p.max_x - p.min_x,
        h: p.max_y - p.min_y };
    }
    if (kind === "camera") {
      const c = this.room.camera;
      return { x: c.min_x, y: c.min_y, w: c.max_x - c.min_x,
        h: c.max_y - c.min_y };
    }
    return { x: this.room.camera.x, y: this.room.camera.y,
      w: VIEW_W, h: VIEW_H };
  }

  drawBounds(ctx) {
    const zoom = this.view.zoom;
    for (const kind of ["play", "camera", "viewport"]) {
      const rect = this.rectFor(kind);
      const selected = this.selection?.kind === "bounds" &&
        this.selection.which === kind;
      ctx.strokeStyle = RECT_COLORS[kind];
      ctx.globalAlpha = selected ? 0.95 : 0.5;
      ctx.lineWidth = (selected ? 2 : 1) / zoom;
      ctx.setLineDash(kind === "viewport" ? [] : [6 / zoom, 4 / zoom]);
      ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      if (kind !== "viewport") {
        const handles = this.rectHandles(rect);
        ctx.fillStyle = RECT_COLORS[kind];
        for (const pt of Object.values(handles)) {
          ctx.fillRect(pt.x - 3 / zoom, pt.y - 3 / zoom, 6 / zoom, 6 / zoom);
        }
      } else {
        // A grab tab at the top-left of the camera viewport.
        ctx.fillStyle = "#d9dce6";
        ctx.fillRect(rect.x - 2 / zoom, rect.y - 8 / zoom, 34 / zoom, 6 / zoom);
        ctx.fillStyle = "#0b0c10";
        ctx.font = `${8 / zoom}px monospace`;
        ctx.fillText("camera", rect.x + 2 / zoom, rect.y - 3.4 / zoom);
      }
    }
  }

  rectHandles(rect) {
    const { x, y, w, h: hgt } = rect;
    return {
      nw: { x, y }, n: { x: x + w / 2, y }, ne: { x: x + w, y },
      e: { x: x + w, y: y + hgt / 2 }, se: { x: x + w, y: y + hgt },
      s: { x: x + w / 2, y: y + hgt }, sw: { x, y: y + hgt },
      w: { x, y: y + hgt / 2 }, move: { x: x + w / 2, y: y + hgt / 2 },
    };
  }

  drawSelectionWorld(ctx) {
    if (!this.selection) return;
    if (this.selection.kind === "bounds") {
      const rect = this.rectFor(this.selection.which);
      ctx.strokeStyle = "#ffd36a";
      ctx.lineWidth = 1.5 / this.view.zoom;
      ctx.setLineDash([3 / this.view.zoom, 3 / this.view.zoom]);
      ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
      ctx.setLineDash([]);
    }
    if (this.stroke?.mode === "rect" && this.stroke.start && this.stroke.end) {
      const { start, end } = this.stroke;
      const x0 = Math.min(start.x, end.x);
      const y0 = Math.min(start.y, end.y);
      const x1 = Math.max(start.x, end.x);
      const y1 = Math.max(start.y, end.y);
      const cell = this.room.collision.cell || CELL;
      ctx.fillStyle = "rgba(224,161,60,.25)";
      ctx.strokeStyle = "#e0a13c";
      ctx.lineWidth = 1 / this.view.zoom;
      ctx.fillRect(Math.floor(x0 / cell) * cell, Math.floor(y0 / cell) * cell,
        (Math.floor(x1 / cell) - Math.floor(x0 / cell) + 1) * cell,
        (Math.floor(y1 / cell) - Math.floor(y0 / cell) + 1) * cell);
      ctx.strokeRect(Math.floor(x0 / cell) * cell, Math.floor(y0 / cell) * cell,
        (Math.floor(x1 / cell) - Math.floor(x0 / cell) + 1) * cell,
        (Math.floor(y1 / cell) - Math.floor(y0 / cell) + 1) * cell);
    }
  }

  drawLabels(ctx) {
    if (!this.show.labels || this.view.zoom < 0.55) return;
    const label = (text, wx, wy, color = "#d9dce6", offsetY = -4) => {
      const p = this.worldToScreen(wx, wy);
      if (p.x < -100 || p.x > this.cssW + 100 || p.y < -30 ||
        p.y > this.cssH + 30) return;
      ctx.font = "10px 'Segoe UI', sans-serif";
      const metrics = ctx.measureText(text);
      const pad = 3;
      ctx.fillStyle = "rgba(8,9,12,.72)";
      ctx.fillRect(p.x - pad, p.y + offsetY - 10, metrics.width + pad * 2, 13);
      ctx.fillStyle = color;
      ctx.fillText(text, p.x, p.y + offsetY);
    };
    if (this.tool === "collision" || this.tool === "tile") {
      // Cursor readout lives in the HUD; labels stay quiet while painting.
    }
    const hovered = this.hoverObject;
    (this.room.objects || []).forEach((obj, index) => {
      const selected = this.selection?.kind === "object" &&
        this.selection.index === index;
      if (!selected && index !== hovered && this.view.zoom < 1.5) return;
      if (!selected && index !== hovered) return;
      const sp = this.app.speciesFor(obj.species, obj.flags);
      const text = sp ? `${sp.name} · ${speciesHex(obj.species)}` :
        `${obj.type} ${speciesHex(obj.species)}`;
      label(text, obj.x, this.objectBox(obj).y, "#ffd36a");
    });
    for (let i = 0; i < (this.room.transitions || []).length; i += 1) {
      const tr = this.room.transitions[i];
      const selected = this.selection?.kind === "transition" &&
        this.selection.index === i;
      if (!selected && this.view.zoom < 0.8) continue;
      label(`→ ${tr.next_area ?? "?"} · sp ${tr.spawn_id ?? 0}`, tr.x,
        tr.y - (tr.half_h || 24), "#4fc9a8");
    }
    const primary = this.room.spawn || { x: 0, y: 0 };
    label("SPAWN", primary.x, primary.y - 20, "#7fe0a8", -12);
  }

  drawHud(ctx) {
    const room = this.room;
    const sel = this.selection;
    let left = "";
    if (this.hover) {
      const cell = room.collision.cell || CELL;
      const cx = Math.floor(this.hover.x / cell);
      const cy = Math.floor(this.hover.y / cell);
      const attr = (cx >= 0 && cy >= 0 && cx < room.collision.width &&
        cy < room.collision.height)
        ? room.collision.attrs[cy * room.collision.width + cx] : 0;
      const layer = room.bg[this.tile.layer === 0 ? 0 : 1];
      const origin = this.layerOrigin(this.tile.layer === 0 ? 0 : 1);
      const tx = Math.floor((this.hover.x - origin.x) / TILE);
      const ty = Math.floor((this.hover.y - origin.y) / TILE);
      let word = 0;
      if (tx >= 0 && ty >= 0 && tx < layer.map_width && ty < layer.map_height) {
        word = layer.tilemap[ty * layer.map_width + tx] || 0;
      }
      left = `x ${Math.floor(this.hover.x)}  y ${Math.floor(this.hover.y)}` +
        ` · cell ${cx},${cy} · attr 0x${padHex(attr, 2)}` +
        ` · tile 0x${padHex(word, 4)}`;
    } else {
      left = "hover the map for coordinates";
    }
    const hud = $("#map-hud-cursor");
    if (hud) hud.textContent = left;
    const hint = $("#map-hint");
    if (hint) {
      if (this.tool === "collision") {
        hint.textContent = "Collision paint · left = apply · right = erase · Alt = pick · use Rectangle/Fill for areas";
      } else if (this.tool === "tile") {
        hint.textContent = "Tile paint · left = apply · right = erase · Alt = pick · choose the palette and tile on the left";
      } else if (this.tool === "object") {
        hint.textContent = "Place mode · click to stamp the selected object · Esc/V returns to select";
      } else if (this.tool === "door") {
        hint.textContent = "Door mode · click to add a transition at the cursor";
      } else if (this.tool === "spawn") {
        hint.textContent = "Spawn mode · click to set the primary spawn · Shift+click adds another spawn";
      } else if (this.tool === "pan") {
        hint.textContent = "Pan · drag with the left mouse button";
      } else {
        hint.textContent = "Wheel zoom · middle/space drag to pan · drag objects/doors · arrow keys nudge · Del removes";
      }
    }
  }

  /* ------------------------------------------------------------- preview */
  togglePreview(force = null) {
    this.preview.on = force ?? !this.preview.on;
    if (this.preview.on) {
      this.preview.x = this.room.camera.x || 0;
      this.preview.y = this.room.camera.y || 0;
      $("#preview-bar").style.display = "flex";
      this.previewBtn.classList.add("active");
      this.setTool("select");
    } else {
      $("#preview-bar").style.display = "none";
      this.previewBtn.classList.remove("active");
    }
    this.invalidate();
  }

  previewAtSpawn() {
    this.preview.x = clamp((this.room.spawn?.x || 0) - VIEW_W / 2,
      this.room.camera.min_x ?? 0, this.room.camera.max_x ?? 1e9);
    this.preview.y = clamp((this.room.spawn?.y || 0) - VIEW_H / 2,
      this.room.camera.min_y ?? 0, this.room.camera.max_y ?? 1e9);
    this.invalidate();
  }

  previewAtCamera() {
    this.preview.x = this.room.camera.x || 0;
    this.preview.y = this.room.camera.y || 0;
    this.invalidate();
  }

  savePreviewPng() {
    const out = document.createElement("canvas");
    out.width = VIEW_W;
    out.height = VIEW_H;
    const ctx = out.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    this.renderGameView(ctx, this.preview.x, this.preview.y);
    downloadCanvas(`area${this.area}_preview.png`, out);
  }

  exportFullRoomPng() {
    if (!this.room?.world) return;
    const worldW = this.room.world.width || 256;
    const worldH = this.room.world.height || 224;

    const out = document.createElement("canvas");
    out.width = worldW;
    out.height = worldH;
    const ctx = out.getContext("2d");
    ctx.imageSmoothingEnabled = false;

    // Background fill
    ctx.fillStyle = "#06070a";
    ctx.fillRect(0, 0, worldW, worldH);

    // BG0
    if (this.show.bg0 && this.room.bg?.[0]) {
      const orig0 = this.layerOrigin(0);
      this.drawLayerTiles(ctx, this.room.bg[0], this.assets?.bg0, orig0.x, orig0.y,
        0, 0, worldW, worldH, false, false);
    }
    // BG1
    if (this.show.bg1 && this.room.bg?.[1]) {
      const orig1 = this.layerOrigin(1);
      this.drawLayerTiles(ctx, this.room.bg[1], this.assets?.bg1, orig1.x, orig1.y,
        0, 0, worldW, worldH, false, false);
    }
    // Collision
    if (this.show.collision) {
      this.drawCollision(ctx, { x: 0, y: 0, w: worldW, h: worldH });
    }
    // Objects
    if (this.show.objects) {
      this.drawObjects(ctx);
    }
    // Transitions and spawns
    if (this.show.transitions) {
      this.drawTransitions(ctx);
    }
    this.drawSpawns(ctx);

    downloadCanvas(`area${this.area}_full.png`, out);
    toast(`Exported full room image (${worldW}×${worldH})`, "ok");
  }

  toggleMinimap() {
    this.showMinimap = !this.showMinimap;
    if (this.minimapHost) {
      this.minimapHost.classList.toggle("hidden", !this.showMinimap);
    }
    if (this.minimapBtn) {
      this.minimapBtn.classList.toggle("active", this.showMinimap);
    }
    if (this.showMinimap) this.invalidate();
  }

  bindMinimapEvents() {
    if (!this.minimapHost) return;
    let isNavigating = false;

    const navigateTo = (e) => {
      if (!this.room?.world || !this.minimapCanvas) return;
      const rect = this.minimapCanvas.getBoundingClientRect();
      const worldW = this.room.world.width || 256;
      const worldH = this.room.world.height || 224;
      const scale = Math.min((rect.width - 8) / worldW, (rect.height - 8) / worldH);
      const offsetX = (rect.width - worldW * scale) / 2;
      const offsetY = (rect.height - worldH * scale) / 2;

      const clickX = e.clientX - rect.left - offsetX;
      const clickY = e.clientY - rect.top - offsetY;

      const targetX = clickX / scale;
      const targetY = clickY / scale;

      const visW = this.cssW / this.view.zoom;
      const visH = this.cssH / this.view.zoom;

      this.view.x = targetX - visW / 2;
      this.view.y = targetY - visH / 2;
      this.invalidate();
    };

    this.minimapHost.onpointerdown = (e) => {
      e.stopPropagation();
      isNavigating = true;
      try { this.minimapHost.setPointerCapture(e.pointerId); } catch {}
      navigateTo(e);
    };

    this.minimapHost.onpointermove = (e) => {
      if (!isNavigating) return;
      e.stopPropagation();
      navigateTo(e);
    };

    this.minimapHost.onpointerup = (e) => {
      if (!isNavigating) return;
      isNavigating = false;
      try { this.minimapHost.releasePointerCapture(e.pointerId); } catch {}
    };
  }

  drawMinimap() {
    if (!this.minimapCanvas || !this.room?.world || !this.showMinimap) return;
    const canvas = this.minimapCanvas;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.floor(rect.width * dpr) || canvas.height !== Math.floor(rect.height * dpr)) {
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
    }
    const mctx = canvas.getContext("2d");
    mctx.save();
    mctx.scale(dpr, dpr);
    mctx.clearRect(0, 0, rect.width, rect.height);

    const worldW = this.room.world.width || 256;
    const worldH = this.room.world.height || 224;
    const scale = Math.min((rect.width - 8) / worldW, (rect.height - 8) / worldH);
    const offsetX = (rect.width - worldW * scale) / 2;
    const offsetY = (rect.height - worldH * scale) / 2;

    // Room background box
    mctx.fillStyle = "#14161f";
    mctx.fillRect(offsetX, offsetY, worldW * scale, worldH * scale);
    mctx.strokeStyle = "#2b3040";
    mctx.lineWidth = 1;
    mctx.strokeRect(offsetX, offsetY, worldW * scale, worldH * scale);

    // Draw collision silhouette
    const col = this.room.collision;
    if (col && Array.isArray(col.attrs)) {
      const cellW = 16 * scale;
      const cellH = 16 * scale;
      const gridW = col.width || Math.ceil(worldW / 16);
      for (let i = 0; i < col.attrs.length; i++) {
        const val = col.attrs[i];
        if (!val) continue;
        const cx = (i % gridW) * 16;
        const cy = Math.floor(i / gridW) * 16;
        const env = val & 0xE0;
        mctx.fillStyle = env === 0x20 ? "#e06060" : env === 0x40 ? "#e0a13c" : env === 0x60 ? "#5a9ae0" : "#4fc98a";
        mctx.fillRect(offsetX + cx * scale, offsetY + cy * scale, Math.max(1, cellW), Math.max(1, cellH));
      }
    }

    // Object heatmap: enemies, bosses, items, urns and decor.
    const heat = (obj) => {
      if (obj.type === "boss") return "#c084fc";
      if (obj.type === "enemy") return "#f87171";
      if (obj.type === "urn") return "#e0a13c";
      if (obj.type === "talisman" || obj.type === "pickup_crest" ||
          obj.type === "item" || obj.type === "crest") return "#38bdf8";
      if (obj.type === "npc") return "#4ade80";
      if (obj.type === "decor") return "#fb923c";
      return "#e5e7eb";
    };
    for (const obj of this.room.objects || []) {
      const x = Number(obj.x) || 0;
      const y = Number(obj.y) || 0;
      if (x < 0 || y < 0 || x > worldW || y > worldH) continue;
      mctx.fillStyle = heat(obj);
      mctx.fillRect(offsetX + x * scale - 1, offsetY + y * scale - 1, 2.5, 2.5);
    }
    for (const tr of this.room.transitions || []) {
      const x = Number(tr.x) || 0;
      const y = Number(tr.y) || 0;
      mctx.strokeStyle = "#4ade80";
      mctx.lineWidth = 1;
      mctx.strokeRect(offsetX + x * scale - 1.5, offsetY + y * scale - 1.5, 3, 3);
    }

    // Viewport box
    const vis = this.visibleWorldRect();
    const vx = offsetX + vis.x * scale;
    const vy = offsetY + vis.y * scale;
    const vw = vis.w * scale;
    const vh = vis.h * scale;

    mctx.strokeStyle = "#e0a13c";
    mctx.lineWidth = 1.5;
    mctx.strokeRect(vx, vy, vw, vh);
    mctx.fillStyle = "rgba(224, 161, 60, 0.15)";
    mctx.fillRect(vx, vy, vw, vh);

    mctx.restore();
  }

  updateBackBtn() {
    if (!this.backBtn) return;
    if (this.navHistory && this.navHistory.length > 0) {
      this.backBtn.style.display = "";
      const prev = this.navHistory[this.navHistory.length - 1];
      const lbl = this.backBtn.querySelector("#map-back-label");
      if (lbl) lbl.textContent = `← Area ${prev}`;
    } else {
      this.backBtn.style.display = "none";
    }
  }

  async renderInGame(frames = 120) {
    const loading = h("div", {
      style: { display: "flex", flexDirection: "column", gap: "8px" },
    },
    h("div", { class: "row" },
      h("span", {
        style: { width: "18px", height: "18px", border: "2px solid var(--line)",
          borderTopColor: "var(--accent)", borderRadius: "50%",
          animation: "spin 0.8s linear infinite", display: "inline-block" },
      }),
      h("span", { text: "Starting the game engine and rendering 120 frames…" })),
    h("div", { class: "field-note",
      text: "This runs the actual Python port headlessly with a temporary copy of the current room. It does not save anything." }),
    );
    const body = h("div", { style: { display: "flex", flexDirection: "column",
      gap: "10px", minWidth: "520px" } }, loading);
    showModal({
      title: "Render in game", body, wide: true,
      actions: [{ label: "Close", primary: true }],
    });
    this.app.setStatus("Rendering in game…", `area ${this.area}`);
    try {
      const result = await api.renderRoom(this.area, this.room, frames);
      if (!result.ok) {
        const detail = result.detail || result.error || "unknown error";
        clear(body);
        body.append(
          h("div", { class: "issue error", text: "The game did not produce a frame." }),
          h("pre", { class: "issue",
            style: { whiteSpace: "pre-wrap", maxHeight: "300px",
              overflow: "auto", fontSize: "10px" },
            text: detail }),
        );
        return;
      }
      clear(body);
      const img = h("img", {
        src: result.url, alt: `Area ${this.area} rendered by the game`,
        style: { width: "512px", height: "448px", imageRendering: "pixelated",
          border: "1px solid var(--line)", borderRadius: "4px",
          background: "#000", alignSelf: "center" },
      });
      body.append(
        img,
        h("div", { class: "row wrap" },
          h("a", {
            class: "btn small", href: result.url, download: `area${this.area}_game.png`,
          }, icon("download"), "Save PNG"),
          h("a", {
            class: "btn small", href: result.url, target: "_blank",
            rel: "noopener",
          }, icon("link"), "Open in new tab"),
          h("span", { class: "field-note",
            text: `${result.width}×${result.height} · ${result.frames} frames · ${result.ms} ms` }),
        ),
        h("div", { class: "field-note",
          text: "Rendered by dcpy.main with the room exactly as edited (authored species and enemy definitions also apply). The HUD and intro banner are part of the game frame." }),
      );
      this.app.setStatus(`Rendered area ${this.area} in game`, result.path);
    } catch (error) {
      clear(body);
      body.append(
        h("div", { class: "issue error", text: error.message }),
        error.payload?.validation
          ? issueList(error.payload.validation) : null,
        error.payload?.detail ? h("pre", {
          class: "issue", style: { whiteSpace: "pre-wrap", maxHeight: "300px",
            overflow: "auto", fontSize: "10px" },
          text: error.payload.detail,
        }) : null,
      );
      this.app.setStatus("Render failed", error.message);
    }
  }

  renderPreview(ctx) {
    const scale = Math.max(1, Math.floor(Math.min(
      (this.cssW - 36) / VIEW_W, (this.cssH - 36) / VIEW_H)));
    const w = VIEW_W * scale;
    const hgt = VIEW_H * scale;
    const ox = Math.floor((this.cssW - w) / 2);
    const oy = Math.floor((this.cssH - hgt) / 2);
    ctx.save();
    ctx.fillStyle = "#06070a";
    ctx.fillRect(0, 0, this.cssW, this.cssH);
    ctx.fillStyle = "#000";
    ctx.fillRect(ox - 2, oy - 2, w + 4, hgt + 4);
    ctx.translate(ox, oy);
    ctx.scale(scale, scale);
    ctx.beginPath();
    ctx.rect(0, 0, VIEW_W, VIEW_H);
    ctx.clip();
    this.renderGameView(ctx, this.preview.x, this.preview.y);
    ctx.restore();
    ctx.strokeStyle = "#3a4050";
    ctx.lineWidth = 1;
    ctx.strokeRect(ox - 2.5, oy - 2.5, w + 5, hgt + 5);
    ctx.fillStyle = "rgba(224,161,60,.85)";
    ctx.font = "10px monospace";
    ctx.fillText(`${scale}× · ${this.preview.x},${this.preview.y}`, ox + 4, oy - 6 > 10 ? oy - 6 : oy + hgt + 13);
    const coords = $("#preview-coords");
    if (coords) coords.textContent = `camera ${this.preview.x},${this.preview.y}`;
  }

  renderGameView(ctx, camX, camY) {
    const room = this.room;
    const bg = room.backdrop || [0, 0, 0];
    ctx.fillStyle = `rgb(${bg[0] || 0},${bg[1] || 0},${bg[2] || 0})`;
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    // Backdrop (screen-locked, parallax).
    const bd = this.assets?.backdrop;
    const bdImg = bd?.url ? getImage(bd.url) : null;
    if (bdImg) {
      const parallax = Number(room.backdrop_parallax) || 0;
      let off = -fmod(camX * parallax, bdImg.width);
      if (off > 0) off -= bdImg.width;
      const y = Number(room.backdrop_y) || 0;
      for (let x = off; x < VIEW_W; x += bdImg.width) {
        ctx.drawImage(bdImg, x, y);
      }
    }
    // BG0: screen-locked / parallax layer with optional HDMA bands.
    const bg0 = room.bg[0];
    if (bg0 && this.show.bg0) {
      const wrapY = room.world.height > 256;
      let originY = camY + (bg0.scroll_y || 0) - (room.camera.y || 0);
      if (wrapY && bg0.map_height * TILE > VIEW_H) {
        originY = fmod(camY * 0.5, bg0.map_height * TILE - VIEW_H);
      }
      const bands = bg0.hdma_bands || [];
      if (bands.length) {
        let scan = 0;
        const camDx = camX - (room.camera.x || 0);
        for (const band of bands) {
          if (scan >= VIEW_H) break;
          const next = Math.min(VIEW_H, scan + (band.lines || 0));
          const bandX = (bg0.scroll_x || 0) + camDx * (band.factor ?? 1);
          ctx.save();
          ctx.beginPath();
          ctx.rect(0, scan, VIEW_W, next - scan);
          ctx.clip();
          this.drawLayerTiles(ctx, bg0, this.assets?.bg0, bandX, originY,
            0, scan, VIEW_W, next, true, wrapY);
          ctx.restore();
          scan = next;
        }
      } else {
        const originX = camX + (bg0.scroll_x || 0) - (room.camera.x || 0);
        this.drawLayerTiles(ctx, bg0, this.assets?.bg0, originX, originY,
          0, 0, VIEW_W, VIEW_H, true, wrapY);
      }
    }
    // BG1: world layer (offset_y carries a per-room vertical correction).
    if (room.bg[1] && this.show.bg1) {
      this.drawLayerTiles(ctx, room.bg[1], this.assets?.bg1, camX,
        camY + (room.bg[1].offset_y || 0),
        0, 0, VIEW_W, VIEW_H, false, false);
    }
    // Objects.
    if (this.show.objects) {
      for (const obj of room.objects || []) {
        const art = this.objectArt(obj);
        const x = obj.x - camX;
        const y = obj.y - camY;
        if (x < -80 || x > VIEW_W + 80 || y < -100 || y > VIEW_H + 100) continue;
        if (obj.type === "platform") {
          ctx.fillStyle = "#84806f";
          ctx.fillRect(x - 16, y, 32, 6);
          continue;
        }
        if (art) {
          if (obj.facing < 0) {
            ctx.save();
            ctx.translate(x, y);
            ctx.scale(-1, 1);
            ctx.drawImage(art.img, -art.ax, -art.ay);
            ctx.restore();
          } else {
            ctx.drawImage(art.img, x - art.ax, y - art.ay);
          }
        } else {
          ctx.strokeStyle = "#ff50dc";
          ctx.strokeRect(x - 6, y - 12, 12, 12);
        }
      }
      // Player spawn silhouette.
      const pTex = this.assets?.player;
      const pImg = pTex?.url ? getImage(pTex.url) : null;
      if (pImg) {
        ctx.globalAlpha = 0.9;
        ctx.drawImage(pImg,
          (room.spawn?.x || 0) - (room.player?.feet_x || 0) - camX,
          (room.spawn?.y || 0) - (room.player?.feet_y || 0) - camY);
        ctx.globalAlpha = 1;
      }
    }
  }

  /* ----------------------------------------------------------- interactions */
  setTool(tool, { silent = false } = {}) {
    this.tool = tool;
    this.canvas.style.cursor = tool === "pan" ? "grab" :
      tool === "collision" || tool === "tile" ? "crosshair" : "default";
    for (const btn of this.toolButtons || []) {
      btn.classList.toggle("active", btn.dataset.tool === tool);
    }
    if (tool === "collision") this.show.collision = true;
    if (tool === "tile") this.show.bg1 = true;
    if (!silent) this.updateToolUi();
    this.syncViewChecks();
    this.invalidate();
  }

  updateToolUi() {
    this.syncViewChecks();
    this.updateUndoUi();
  }

  syncViewChecks() {
    if (!this.viewChecks) return;
    for (const [key, input] of Object.entries(this.viewChecks)) {
      input.checked = !!this.show[key];
    }
  }

  updateUndoUi() {
    if (this.undoBtn) this.undoBtn.disabled = !this.undoStack.length;
    if (this.redoBtn) this.redoBtn.disabled = !this.redoStack.length;
  }

  onPointerDown(event) {
    if (!this.room) return;
    const { px, py } = this.eventCss(event);
    const world = this.screenToWorld(px, py);
    try { this.canvas.setPointerCapture?.(event.pointerId); } catch { /* synthetic event */ }
    if (this.preview.on) {
      this.preview.x = clamp(Math.round(world.x - VIEW_W / 2),
        this.room.camera.min_x ?? 0, this.room.camera.max_x ?? 1e9);
      this.preview.y = clamp(Math.round(world.y - VIEW_H / 2),
        this.room.camera.min_y ?? 0, this.room.camera.max_y ?? 1e9);
      this.invalidate();
      return;
    }
    if (event.button === 1 || this.spaceDown || this.tool === "pan") {
      this.drag = { kind: "pan", startPx: px, startPy: py,
        startX: this.view.x, startY: this.view.y };
      this.canvas.style.cursor = "grabbing";
      return;
    }
    if (this.tool === "collision" && (event.button === 0 || event.button === 2)) {
      if (event.altKey && event.button === 0) { this.pickCollision(world); return; }
      this.beginCollisionStroke(world, event);
      return;
    }
    if (this.tool === "tile" && (event.button === 0 || event.button === 2)) {
      if (event.altKey && event.button === 0) { this.pickTile(world); return; }
      this.beginTileStroke(world, event);
      return;
    }
    if (this.tool === "object" && event.button === 0) {
      this.placeObject(world, event);
      return;
    }
    if (this.tool === "door" && event.button === 0) {
      this.addTransition(world);
      return;
    }
    if (this.tool === "spawn" && event.button === 0) {
      this.setSpawnAt(world, event.shiftKey);
      return;
    }
    if (event.button !== 0) return;
    const hit = this.hitTest(world);
    if (!hit) {
      this.select(null);
      return;
    }
    this.select(hit);
    this.startDrag(hit, world);
  }

  onPointerMove(event) {
    if (!this.room) return;
    const { px, py } = this.eventCss(event);
    const world = this.screenToWorld(px, py);
    this.hover = world;
    if (this.drag) {
      this.updateDrag(px, py, world);
      this.invalidate();
      return;
    }
    if (this.stroke) {
      this.updateStroke(world);
      this.invalidate();
      return;
    }
    this.hover = world;
    this.updateHover(world);
    this.invalidate();
  }

  onPointerUp(event) {
    if (this.stroke) this.finishStroke();
    if (this.drag) {
      this.lastDragWasMove = this.drag.moved;
      this.drag = null;
      this.canvas.style.cursor = this.tool === "pan" ? "grab" : "default";
    }
    this.invalidate();
  }

  updateHover(world) {
    const hit = this.hitTest(world);
    this.hoverObject = hit?.kind === "object" ? hit.index : null;
    const el = $("#map-hud-cursor");
    if (el) {
      if (hit?.kind === "object") {
        const obj = this.room.objects[hit.index];
        const sp = this.app.speciesFor(obj.species, obj.flags);
        el.textContent = `${sp?.name || obj.type} · ${speciesHex(obj.species)} · ${Math.floor(obj.x)},${Math.floor(obj.y)}`;
      }
    }
  }

  hitTest(world) {
    const objects = this.room.objects || [];
    for (let i = objects.length - 1; i >= 0; i -= 1) {
      const box = this.objectBox(objects[i]);
      if (world.x >= box.x && world.x <= box.x + box.w &&
        world.y >= box.y && world.y <= box.y + box.h) {
        return { kind: "object", index: i };
      }
    }
    const transitions = this.room.transitions || [];
    for (let i = transitions.length - 1; i >= 0; i -= 1) {
      const tr = transitions[i];
      const hw = tr.half_w || 12;
      const hh = tr.half_h || 24;
      if (Math.abs(world.x - tr.x) <= hw && Math.abs(world.y - tr.y) <= hh) {
        return { kind: "transition", index: i };
      }
    }
    for (let i = (this.room.spawns || []).length - 1; i >= 0; i -= 1) {
      const sp = this.room.spawns[i];
      if (Math.hypot(world.x - sp.x, world.y - (sp.y - 8)) < 11) {
        return { kind: "spawn", index: i };
      }
    }
    const primary = this.room.spawn;
    if (primary && Math.hypot(world.x - primary.x,
      world.y - (primary.y - 8)) < 11) {
      return { kind: "spawn", index: -1 };
    }
    if (this.show.bounds) {
      const tol = 7 / this.view.zoom + 2;
      for (const kind of ["play", "camera"]) {
        const rect = this.rectFor(kind);
        const handles = this.rectHandles(rect);
        for (const [name, pt] of Object.entries(handles)) {
          if (name === "move") continue;
          if (Math.abs(world.x - pt.x) <= tol && Math.abs(world.y - pt.y) <= tol) {
            return { kind: "bounds", which: kind, handle: name };
          }
        }
      }
      const vp = this.rectFor("viewport");
      if (Math.hypot(world.x - vp.x, world.y - vp.y) < 12 / this.view.zoom + 2) {
        return { kind: "bounds", which: "viewport", handle: "move" };
      }
    }
    return null;
  }

  select(selection) {
    const same = JSON.stringify(selection) === JSON.stringify(this.selection);
    this.selection = selection;
    if (!same) this.refreshInspector();
    if (selection) this.updatePlacePanelFromSelection();
    this.invalidate();
  }

  startDrag(hit, world) {
    if (hit.kind === "object") {
      const obj = this.room.objects[hit.index];
      this.drag = { kind: "object", index: hit.index, handle: null,
        startWorld: world, orig: { x: obj.x, y: obj.y }, moved: false };
    } else if (hit.kind === "transition") {
      const tr = this.room.transitions[hit.index];
      this.drag = { kind: "transition", index: hit.index,
        startWorld: world, orig: { x: tr.x, y: tr.y }, moved: false };
    } else if (hit.kind === "spawn") {
      const sp = hit.index === -1 ? this.room.spawn : this.room.spawns[hit.index];
      this.drag = { kind: "spawn", index: hit.index, startWorld: world,
        orig: { x: sp.x, y: sp.y }, moved: false };
    } else if (hit.kind === "bounds") {
      this.drag = {
        kind: "bounds", which: hit.which, handle: hit.handle,
        startWorld: world, startRect: this.rectFor(hit.which),
        startCamera: { x: this.room.camera.x, y: this.room.camera.y },
        moved: false,
      };
    }
  }

  updateDrag(px, py, world) {
    if (this.drag.kind === "pan") {
      this.view.x = this.drag.startX - (px - this.drag.startPx) / this.view.zoom;
      this.view.y = this.drag.startY - (py - this.drag.startPy) / this.view.zoom;
      this.drag.moved = true;
      return;
    }
    if (!this.drag.undoPushed) {
      this.pushUndo("move");
      this.drag.undoPushed = true;
    }
    this.drag.moved = true;
    const dx = world.x - this.drag.startWorld.x;
    const dy = world.y - this.drag.startWorld.y;
    if (this.drag.kind === "object") {
      const obj = this.room.objects[this.drag.index];
      obj.x = Math.round(this.drag.orig.x + dx);
      obj.y = Math.round(this.drag.orig.y + dy);
      this.markDirty();
    } else if (this.drag.kind === "transition") {
      const tr = this.room.transitions[this.drag.index];
      tr.x = Math.round(this.drag.orig.x + dx);
      tr.y = Math.round(this.drag.orig.y + dy);
      this.markDirty();
    } else if (this.drag.kind === "spawn") {
      const sp = this.drag.index === -1 ? this.room.spawn :
        this.room.spawns[this.drag.index];
      sp.x = Math.round(this.drag.orig.x + dx);
      sp.y = Math.round(this.drag.orig.y + dy);
      if (this.drag.index === -1 && this.room.spawns?.[0]) {
        this.room.spawns[0].x = sp.x;
        this.room.spawns[0].y = sp.y;
      }
      this.markDirty();
    } else if (this.drag.kind === "bounds") {
      this.dragBounds(dx, dy);
      this.markDirty();
    }
  }

  dragBounds(dx, dy) {
    const d = this.drag;
    const snapTo = (v) => Math.round(v);
    const rect = d.startRect;
    if (d.which === "viewport") {
      this.room.camera.x = clamp(snapTo(d.startCamera.x + dx),
        this.room.camera.min_x ?? 0, this.room.camera.max_x ?? 1e9);
      this.room.camera.y = clamp(snapTo(d.startCamera.y + dy),
        this.room.camera.min_y ?? 0, this.room.camera.max_y ?? 1e9);
      return;
    }
    let x0 = rect.x;
    let y0 = rect.y;
    let x1 = rect.x + rect.w;
    let y1 = rect.y + rect.h;
    const move = d.handle === "move";
    if (move || d.handle.includes("w")) x0 += dx;
    if (move || d.handle.includes("e")) x1 += dx;
    if (move || d.handle.includes("n")) y0 += dy;
    if (move || d.handle.includes("s")) y1 += dy;
    if (x1 < x0 + 16) x1 = x0 + 16;
    if (y1 < y0 + 16) y1 = y0 + 16;
    if (d.which === "play") {
      const p = this.room.play;
      p.min_x = Math.round(x0); p.max_x = Math.round(x1);
      p.min_y = Math.round(y0); p.max_y = Math.round(y1);
    } else if (d.which === "camera") {
      const c = this.room.camera;
      c.min_x = Math.max(0, Math.round(x0));
      c.max_x = Math.round(x1);
      c.min_y = Math.max(0, Math.round(y0));
      c.max_y = Math.round(y1);
    }
  }

  /* --------------------------------------------------------------- painting */
  beginCollisionStroke(world, event, erase = false) {
    const mode = erase ? "paint" : this.brush.mode;
    this.pushUndo("paint collision");
    this.stroke = { tool: "collision", mode, erase: erase || event.button === 2,
      value: (this.brush.shape | this.brush.env) & 0xff,
      env: this.brush.env, preserve: !!this.brush.preserveShape,
      size: this.brush.size, start: world, end: world, last: null };
    if (mode === "fill") {
      this.floodCollision(world);
      this.stroke = null;
      this.markDirty();
      this.invalidate();
      return;
    }
    if (mode === "paint") {
      this.paintCollisionAt(world);
      this.stroke.last = world;
    }
    this.invalidate();
  }

  collisionValueAt(idx, stroke = this.stroke) {
    if (!stroke || stroke.erase) return 0;
    if (stroke.preserve) {
      return ((this.room.collision.attrs[idx] || 0) & 0x1f) | stroke.env;
    }
    return stroke.value;
  }

  paintCollisionAt(world) {
    const col = this.room.collision;
    const cell = col.cell || CELL;
    const cx = Math.floor(world.x / cell);
    const cy = Math.floor(world.y / cell);
    const size = this.stroke?.size || 1;
    for (let oy = 0; oy < size; oy += 1) {
      for (let ox = 0; ox < size; ox += 1) {
        const x = cx + ox;
        const y = cy + oy;
        if (x < 0 || y < 0 || x >= col.width || y >= col.height) continue;
        const idx = y * col.width + x;
        col.attrs[idx] = this.collisionValueAt(idx);
      }
    }
    this.markDirty();
    this.refreshCollisionStats();
  }

  floodCollision(world) {
    const col = this.room.collision;
    const cell = col.cell || CELL;
    const startX = Math.floor(world.x / cell);
    const startY = Math.floor(world.y / cell);
    if (startX < 0 || startY < 0 || startX >= col.width || startY >= col.height) return;
    const from = col.attrs[startY * col.width + startX];
    const to = this.stroke.erase ? 0 : this.stroke.value;
    if (from === to) return;
    const stack = [[startX, startY]];
    const seen = new Uint8Array(col.width * col.height);
    while (stack.length) {
      const [x, y] = stack.pop();
      if (x < 0 || y < 0 || x >= col.width || y >= col.height) continue;
      const idx = y * col.width + x;
      if (seen[idx] || col.attrs[idx] !== from) continue;
      seen[idx] = 1;
      col.attrs[idx] = this.collisionValueAt(idx, this.stroke);
      stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
    }
    this.refreshCollisionStats();
    this.markDirty();
  }

  updateStroke(world) {
    const stroke = this.stroke;
    if (!stroke) return;
    if (stroke.mode === "rect") {
      stroke.end = world;
      return;
    }
    if (stroke.tool === "collision") {
      if (stroke.last) {
        // Interpolate the gap between pointer events.
        const cell = this.room.collision.cell || CELL;
        const x0 = Math.floor(stroke.last.x / cell);
        const y0 = Math.floor(stroke.last.y / cell);
        const x1 = Math.floor(world.x / cell);
        const y1 = Math.floor(world.y / cell);
        const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
        for (let i = 1; i <= steps; i += 1) {
          const t = steps ? i / steps : 0;
          this.paintCollisionAt({
            x: (x0 + (x1 - x0) * t) * cell,
            y: (y0 + (y1 - y0) * t) * cell,
          });
        }
      } else {
        this.paintCollisionAt(world);
      }
      stroke.last = world;
    } else if (stroke.tool === "tile") {
      this.paintTileAt(world);
    }
  }

  finishStroke() {
    const stroke = this.stroke;
    this.stroke = null;
    if (!stroke) return;
    if (stroke.mode === "rect" && stroke.start && stroke.end) {
      if (stroke.tool === "collision") {
        const cell = this.room.collision.cell || CELL;
        const x0 = Math.floor(Math.min(stroke.start.x, stroke.end.x) / cell);
        const x1 = Math.floor(Math.max(stroke.start.x, stroke.end.x) / cell);
        const y0 = Math.floor(Math.min(stroke.start.y, stroke.end.y) / cell);
        const y1 = Math.floor(Math.max(stroke.start.y, stroke.end.y) / cell);
        const col = this.room.collision;
        for (let y = y0; y <= y1; y += 1) {
          for (let x = x0; x <= x1; x += 1) {
            if (x >= 0 && y >= 0 && x < col.width && y < col.height) {
              const idx = y * col.width + x;
              col.attrs[idx] = this.collisionValueAt(idx, {
                erase: stroke.erase, preserve: stroke.preserve,
                env: stroke.env, value: stroke.value,
              });
            }
          }
        }
        this.refreshCollisionStats();
      } else if (stroke.tool === "tile") {
        this.fillTileRect(stroke.start, stroke.end, stroke.erase, stroke.layer);
      }
      this.markDirty();
    }
    this.invalidate();
  }

  pickCollision(world) {
    const col = this.room.collision;
    const cell = col.cell || CELL;
    const cx = Math.floor(world.x / cell);
    const cy = Math.floor(world.y / cell);
    if (cx < 0 || cy < 0 || cx >= col.width || cy >= col.height) return;
    const attr = col.attrs[cy * col.width + cx] || 0;
    this.brush.shape = attr & 0x1f;
    this.brush.env = attr & 0xe0;
    this.updateShapeSelection();
    [...this.envButtons.children].forEach((b, i) => {
      b.classList.toggle("active",
        this.envButtonsData[i].value === this.brush.env);
    });
    this.brushSummary.textContent = this.brushDescription();
    toast(`Picked attr 0x${padHex(attr, 2)}`, "", 1100);
  }

  /* ----------------------------------------------------------------- tiles */
  tileOrigin(layerIndex) {
    if (layerIndex === 1) {
      return { x: 0, y: this.room.bg[1]?.offset_y || 0 };
    }
    const layer = this.room.bg[0];
    return { x: (layer.scroll_x || 0) - (this.room.camera.x || 0),
      y: (layer.scroll_y || 0) - (this.room.camera.y || 0) };
  }

  beginTileStroke(world, event) {
    this.pushUndo("paint tiles");
    const erase = event.button === 2;
    this.stroke = { tool: "tile", mode: this.brush.mode === "paint" ? "paint" :
      this.brush.mode, erase,
      value: encodeTile(this.tile.index, this.tile.pal,
        this.tile.flipH, this.tile.flipV),
      start: world, end: world, last: null,
      layer: this.tile.layer, size: this.brush.size };
    if (this.stroke.mode === "fill") {
      this.floodTiles(world);
      this.stroke = null;
      this.markDirty();
      this.invalidate();
      return;
    }
    this.paintTileAt(world);
    this.stroke.last = world;
  }

  tileCoords(world, layerIndex) {
    const layer = this.room.bg[layerIndex];
    const origin = this.tileOrigin(layerIndex);
    const tx = Math.floor((world.x - origin.x) / TILE);
    const ty = Math.floor((world.y - origin.y) / TILE);
    return { layer, tx, ty, origin };
  }

  paintTileAt(world) {
    const stroke = this.stroke;
    if (!stroke) return;
    const layerIndex = stroke.layer;
    const { layer, tx, ty } = this.tileCoords(world, layerIndex);
    const size = stroke.size || 1;
    for (let oy = 0; oy < size; oy += 1) {
      for (let ox = 0; ox < size; ox += 1) {
        const x = tx + ox;
        const y = ty + oy;
        if (x < 0 || y < 0 || x >= layer.map_width || y >= layer.map_height) continue;
        layer.tilemap[y * layer.map_width + x] = stroke.erase ? 0 : stroke.value;
      }
    }
    this.markDirty();
  }

  floodTiles(world) {
    const stroke = this.stroke;
    const layerIndex = stroke.layer;
    const { layer, tx, ty } = this.tileCoords(world, layerIndex);
    if (tx < 0 || ty < 0 || tx >= layer.map_width || ty >= layer.map_height) return;
    const from = layer.tilemap[ty * layer.map_width + tx] || 0;
    const to = stroke.erase ? 0 : stroke.value;
    if (from === to) return;
    const stack = [[tx, ty]];
    const seen = new Uint8Array(layer.map_width * layer.map_height);
    while (stack.length) {
      const [x, y] = stack.pop();
      if (x < 0 || y < 0 || x >= layer.map_width || y >= layer.map_height) continue;
      const idx = y * layer.map_width + x;
      if (seen[idx] || (layer.tilemap[idx] || 0) !== from) continue;
      seen[idx] = 1;
      layer.tilemap[idx] = to;
      stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
    }
    this.markDirty();
  }

  fillTileRect(start, end, erase, layerIndex = this.tile.layer) {
    const layer = this.room.bg[layerIndex];
    const origin = this.tileOrigin(layerIndex);
    const x0 = Math.floor((Math.min(start.x, end.x) - origin.x) / TILE);
    const x1 = Math.floor((Math.max(start.x, end.x) - origin.x) / TILE);
    const y0 = Math.floor((Math.min(start.y, end.y) - origin.y) / TILE);
    const y1 = Math.floor((Math.max(start.y, end.y) - origin.y) / TILE);
    const value = erase ? 0 : encodeTile(this.tile.index, this.tile.pal,
      this.tile.flipH, this.tile.flipV);
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        if (x >= 0 && y >= 0 && x < layer.map_width && y < layer.map_height) {
          layer.tilemap[y * layer.map_width + x] = value;
        }
      }
    }
  }

  pickTile(world) {
    const layerIndex = this.tile.layer;
    const { layer, tx, ty } = this.tileCoords(world, layerIndex);
    if (tx < 0 || ty < 0 || tx >= layer.map_width || ty >= layer.map_height) return;
    const word = layer.tilemap[ty * layer.map_width + tx] || 0;
    const decoded = decodeTile(word);
    this.tile.index = decoded.tile;
    this.tile.pal = decoded.pal;
    this.tile.flipH = decoded.flipH;
    this.tile.flipV = decoded.flipV;
    this.tileFlipH.checked = this.tile.flipH;
    this.tileFlipV.checked = this.tile.flipV;
    this.refreshPaletteTabs();
    this.drawTilePicker();
    toast(`Picked tile ${decoded.tile} pal ${decoded.pal}`, "", 1100);
  }

  /* --------------------------------------------------------------- objects */
  placeObject(world, event) {
    const type = this._place.type;
    const needsSpecies = ["enemy", "boss", "npc", "urn", "pickup_crest",
      "decor", "inert", "unknown"].includes(type);
    const sp = this.app.peakSpecies(this._place.speciesKey);
    if (needsSpecies && !sp) {
      toast("Choose a species first.", "warn");
      this.choosePlaceSpecies();
      return;
    }
    const obj = {
      type,
      species: needsSpecies ? sp.species : 0,
      flags: this._place.flags || 0,
      x: Math.round(world.x),
      y: Math.round(world.y),
    };
    if (type === "talisman") obj.species = 0;
    this.pushUndo("add object");
    this.room.objects = this.room.objects || [];
    this.room.objects.push(obj);
    const index = this.room.objects.length - 1;
    this.select({ kind: "object", index });
    this.setTool("select", { silent: true });
    this.markDirty();
    this.refreshObjectList();
    this.invalidate();
  }

  addTransition(world) {
    this.pushUndo("add door");
    this.room.transitions = this.room.transitions || [];
    const area = this.area;
    const tr = {
      next_area: area === 0 ? 0 : area,
      spawn_id: 0, pad_mask: 255,
      x: Math.round(world.x), y: Math.round(world.y),
      half_w: 12, half_h: 24, type: 0,
    };
    this.room.transitions.push(tr);
    this.select({ kind: "transition", index: this.room.transitions.length - 1 });
    this.setTool("select", { silent: true });
    this.markDirty();
    this.invalidate();
  }

  setSpawnAt(world, addSecondary = false) {
    const x = Math.round(world.x);
    const y = Math.round(world.y);
    this.pushUndo("set spawn");
    if (addSecondary && this.room.spawns) {
      this.room.spawns.push({ x, y, flags: 0 });
      this.select({ kind: "spawn", index: this.room.spawns.length - 1 });
    } else {
      this.room.spawn = { x, y };
      this.room.spawns = this.room.spawns || [];
      if (!this.room.spawns.length) this.room.spawns.push({ x, y, flags: 0 });
      else {
        this.room.spawns[0].x = x;
        this.room.spawns[0].y = y;
      }
      this.select({ kind: "spawn", index: -1 });
    }
    this.setTool("select", { silent: true });
    this.markDirty();
    this.invalidate();
  }

  deleteSelection() {
    const sel = this.selection;
    if (!sel) return;
    if (sel.kind === "object") {
      this.pushUndo("delete object");
      this.room.objects.splice(sel.index, 1);
      this.select(null);
      this.refreshObjectList();
    } else if (sel.kind === "transition") {
      this.pushUndo("delete door");
      this.room.transitions.splice(sel.index, 1);
      this.select(null);
    } else if (sel.kind === "spawn") {
      if (sel.index === -1) {
        toast("The primary spawn cannot be deleted; move it instead.", "warn");
        return;
      }
      this.pushUndo("delete spawn");
      this.room.spawns.splice(sel.index, 1);
      this.select(null);
    } else {
      return;
    }
    this.markDirty();
    this.invalidate();
  }

  duplicateSelection() {
    const sel = this.selection;
    if (sel?.kind === "object") {
      const obj = deepClone(this.room.objects[sel.index]);
      obj.x += 16; obj.y += 16;
      this.pushUndo("duplicate object");
      this.room.objects.push(obj);
      this.select({ kind: "object", index: this.room.objects.length - 1 });
    } else if (sel?.kind === "transition") {
      const tr = deepClone(this.room.transitions[sel.index]);
      tr.x += 16;
      this.pushUndo("duplicate door");
      this.room.transitions.push(tr);
      this.select({ kind: "transition", index: this.room.transitions.length - 1 });
    } else {
      return;
    }
    this.markDirty();
    this.refreshObjectList();
    this.invalidate();
  }

  copySelection() {
    const sel = this.selection;
    if (sel?.kind === "object") {
      this.clipboard = { kind: "object", data: deepClone(this.room.objects[sel.index]) };
      toast("Object copied.", "", 1100);
    } else if (sel?.kind === "transition") {
      this.clipboard = { kind: "transition",
        data: deepClone(this.room.transitions[sel.index]) };
      toast("Door copied.", "", 1100);
    }
  }

  pasteClipboard() {
    if (!this.clipboard) { toast("Clipboard is empty.", "warn", 1200); return; }
    if (this.clipboard.kind === "object") {
      const obj = deepClone(this.clipboard.data);
      obj.x += 16; obj.y += 16;
      this.pushUndo("paste object");
      this.room.objects = this.room.objects || [];
      this.room.objects.push(obj);
      this.select({ kind: "object", index: this.room.objects.length - 1 });
      this.refreshObjectList();
    } else {
      const tr = deepClone(this.clipboard.data);
      tr.x += 16; tr.y += 16;
      this.pushUndo("paste door");
      this.room.transitions = this.room.transitions || [];
      this.room.transitions.push(tr);
      this.select({ kind: "transition", index: this.room.transitions.length - 1 });
    }
    this.markDirty();
    this.invalidate();
  }

  async requestLoadArea(area, trackHistory = true) {
    if (!Number.isFinite(Number(area))) return;
    if (this.dirty) {
      const ok = await confirmDialog("Discard unsaved changes?",
        `Opening area ${area} will discard the current edits.`,
        { okLabel: "Discard & open", danger: true });
      if (!ok) return;
    }
    if (trackHistory && this.area !== undefined && Number(area) !== this.area) {
      if (!this.navHistory) this.navHistory = [];
      this.navHistory.push(this.area);
    }
    await this.loadRoom(Number(area));
    this.updateBackBtn();
  }

  snapSelectionToFloor() {
    const sel = this.selection;
    const obj = sel?.kind === "object" ? this.room.objects[sel.index] : null;
    if (!obj) return;
    const floor = floorAt(this.room.collision, obj.x, obj.y + 4);
    if (floor === null) { toast("No floor under this object.", "warn"); return; }
    this.pushUndo("snap to floor");
    obj.y = floor;
    this.markDirty();
    this.refreshInspector();
    this.invalidate();
  }

  /* ---------------------------------------------------------------- bounds */
  setBoundsValue(kind, key, value) {
    const target = kind === "play" ? this.room.play : this.room.camera;
    target[key] = Number(value);
    if (key.startsWith("min") && target[key] > target[key.replace("min", "max")]) {
      target[key.replace("min", "max")] = target[key];
    }
    if (key.startsWith("max") && target[key] < target[key.replace("max", "min")]) {
      target[key.replace("max", "min")] = target[key];
    }
    this.markDirty();
    this.invalidate();
  }

  /* ------------------------------------------------------------------ undo */
  pushUndo(label = "edit") {
    if (this._restoring) return;
    this.undoStack.push({ label, room: deepClone(this.room) });
    if (this.undoStack.length > 80) this.undoStack.shift();
    this.redoStack = [];
    this.updateUndoUi();
  }

  undo() {
    if (!this.undoStack.length) return;
    const entry = this.undoStack.pop();
    this.redoStack.push({ label: entry.label, room: deepClone(this.room) });
    this._restoring = true;
    this.room = entry.room;
    this._restoring = false;
    this.afterUndoRedo();
    toast(`Undo: ${entry.label}`, "", 1200);
  }

  redo() {
    if (!this.redoStack.length) return;
    const entry = this.redoStack.pop();
    this.undoStack.push({ label: entry.label, room: deepClone(this.room) });
    this._restoring = true;
    this.room = entry.room;
    this._restoring = false;
    this.afterUndoRedo();
    toast(`Redo: ${entry.label}`, "", 1200);
  }

  afterUndoRedo() {
    if (this.selection?.kind === "object" &&
      this.selection.index >= (this.room.objects || []).length) {
      this.selection = null;
    }
    this.markDirty();
    this.refreshAllPanels();
    this.invalidate();
  }

  /* -------------------------------------------------------------- inspector */
  refreshInspector() {
    clear(this.inspectorBody);
    const sel = this.selection;
    const title = this.inspectorTitle.querySelector(".name");
    if (!this.room) {
      title.textContent = "Loading…";
      this.inspectorBody.append(h("div", { class: "inspector-hint",
        text: "Reading the room and its asset atlases…" }));
      return;
    }
    if (!sel) {
      title.textContent = "Nothing selected";
      this.inspectorBody.append(
        h("div", { class: "inspector-hint",
          text: "Select an object, door, spawn or bounds handle on the canvas. The left panel edits the room itself." }),
        h("div", { class: "kv" },
          h("dt", { text: "Objects" }), h("dd", { text: this.room.objects?.length || 0 }),
          h("dt", { text: "Doors" }), h("dd", { text: this.room.transitions?.length || 0 }),
          h("dt", { text: "Spawns" }), h("dd", { text: this.room.spawns?.length || 0 }),
          h("dt", { text: "Collision" }), h("dd", { text: `${this.room.collision.width}×${this.room.collision.height}` }),
          h("dt", { text: "Source" }), h("dd", { text: this.source }),
        ),
        h("hr"),
        h("div", { class: "small dim", text: "Validation" }),
        issueList(this.validation),
        h("button", {
          class: "btn small", type: "button", text: "Validate now",
          onclick: () => this.runValidation(),
        }),
        this.originalRoom ? h("div", { style: { display: "flex",
          flexDirection: "column", gap: "4px" } },
          h("hr"),
          h("div", { class: "small dim", text: "Changes vs generated" }),
          h("div", { class: "kv" },
            h("dt", { text: "Collision" }), h("dd", { text: `${this.diffSummary()?.collision || 0} cells` }),
            h("dt", { text: "Objects" }), h("dd", { text: this.diffSummary()?.objects || 0 }),
            h("dt", { text: "Doors" }), h("dd", { text: this.diffSummary()?.doors || 0 }),
            h("dt", { text: "Spawns" }), h("dd", { text: this.diffSummary()?.spawns || 0 }),
            h("dt", { text: "Fields" }), h("dd", { text: (this.diffSummary()?.fields || []).join(", ") || "—" }),
          ),
          h("div", { class: "field-note",
            text: "Magenta cells in the canvas are collision cells that differ from assets/generated. Disable Compare in the View panel to hide them." }),
        ) : null,
      );
      return;
    }
    if (sel.kind === "object") {
      const obj = this.room.objects[sel.index];
      if (!obj) { this.select(null); return; }
      const sp = this.app.speciesFor(obj.species, obj.flags);
      title.textContent = sp?.name || `${obj.type} object`;
      this.buildObjectInspector(obj, sel.index, sp);
    } else if (sel.kind === "transition") {
      const tr = this.room.transitions[sel.index];
      if (!tr) { this.select(null); return; }
      title.textContent = `Door → area ${tr.next_area ?? "?"}`;
      this.buildTransitionInspector(tr, sel.index);
    } else if (sel.kind === "spawn") {
      const sp = sel.index === -1 ? this.room.spawn : this.room.spawns[sel.index];
      if (!sp) { this.select(null); return; }
      title.textContent = sel.index === -1 ? "Primary spawn" : `Spawn ${sel.index}`;
      this.buildSpawnInspector(sp, sel.index);
    } else if (sel.kind === "bounds") {
      title.textContent = sel.which === "play" ? "Play bounds" :
        sel.which === "camera" ? "Camera limits" : "Camera start";
      this.buildBoundsInspector(sel.which);
    }
  }

  numbered(label, value, onChange, opts = {}) {
    const input = h("input", {
      type: "number", value, step: opts.step ?? 1,
      min: opts.min ?? undefined, max: opts.max ?? undefined,
      oninput: () => {
        const v = Number(input.value);
        if (!Number.isFinite(v)) return;
        onChange(v);
      },
    });
    return h("div", { class: "field" }, h("span", { text: label }), input);
  }

  buildObjectInspector(obj, index, sp) {
    const speciesButton = h("button", {
      class: "btn small", type: "button", text: "Choose…",
      onclick: async () => {
        const chosen = await showSpeciesPicker(this.app.species, sp?.key,
          { title: "Object species" });
        if (!chosen) return;
        this.pushUndo("change object species");
        obj.species = chosen.species;
        if (chosen.variant === "boss") obj.flags = chosen.flags;
        this.markDirty();
        this.refreshInspector();
        this.refreshObjectList();
        this.invalidate();
      },
    });
    const typeSelect = h("select", {
      onchange: () => {
        this.pushUndo("change object type");
        obj.type = typeSelect.value;
        this.markDirty();
        this.refreshInspector();
        this.refreshObjectList();
        this.invalidate();
      },
    }, (this.app.meta?.object_types || []).map((t) => h("option", {
      value: t.value, text: t.label, selected: t.value === obj.type,
    })));
    const flagsInput = h("input", {
      type: "number", value: obj.flags ?? 0, min: "0", max: "255",
      oninput: () => {
        obj.flags = Number(flagsInput.value) || 0;
        this.markDirty();
        this.invalidate();
      },
    });
    const xInput = h("input", {
      type: "number", value: obj.x,
      oninput: () => { obj.x = Number(xInput.value); this.markDirty(); this.invalidate(); },
    });
    const yInput = h("input", {
      type: "number", value: obj.y,
      oninput: () => { obj.y = Number(yInput.value); this.markDirty(); this.invalidate(); },
    });
    const art = this.objectArt(obj);
    const preview = h("div", { class: "species-chip" },
      speciesThumb(sp, 44),
      h("div", { class: "meta" },
        h("div", { class: "n", text: sp?.name || "No art" }),
        h("div", { class: "s",
          text: `${speciesHex(obj.species)} · key ${sp?.key || "—"}${sp?.variant === "boss" ? " · boss flags " + (obj.flags ?? 0) : ""}` }),
      ),
      speciesButton,
    );
    this.inspectorBody.append(
      preview,
      h("div", { class: "field" }, h("span", { text: "Type" }), typeSelect),
      h("div", { class: "field" }, h("span", { text: "Flags" }), flagsInput),
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "X" }), xInput),
        h("div", { class: "field" }, h("span", { text: "Y" }), yInput),
      ),
      h("div", { class: "field-note",
        text: obj.type === "talisman"
          ? "Talisman flags select the item: 0 Buster, 1 Tornado, 2 Claw, 3 Demon Fire, 4 hand."
          : obj.type === "boss"
            ? "Boss flags select palette/encounter variants (Arma: 0, 2, 4)."
            : obj.type === "enemy"
              ? "Enemy flags bit 0 flips the initial facing." : "" }),
      h("div", { class: "row wrap" },
        h("button", { class: "btn small", type: "button", text: "Snap to floor",
          onclick: () => this.snapSelectionToFloor() }),
        h("button", { class: "btn small", type: "button", text: "Copy",
          onclick: () => this.copySelection() }),
        h("button", { class: "btn small", type: "button", text: "Duplicate",
          onclick: () => this.duplicateSelection() }),
        h("button", { class: "btn small danger", type: "button", text: "Delete",
          onclick: () => this.deleteSelection() }),
      ),
      h("div", { class: "field-note",
        text: "Drag the sprite on the canvas to move it. Arrow keys nudge by 1 px (Shift = 8 px)." }),
    );
  }

  async checkTransitionTarget(tr, badge) {
    if (!badge) return;
    const area = Number(tr.next_area);
    const known = this.app.rooms.some((r) => r.area === area);
    if (!known) {
      badge.className = "field-note transition-check bad";
      badge.textContent = `✗ Area ${area} does not exist`;
      return;
    }
    badge.className = "field-note transition-check";
    badge.textContent = "Checking destination…";
    try {
      let info = this._spawnCache.get(area);
      if (!info) {
        const detail = await api.room(area);
        const room = detail.room || {};
        info = {
          spawns: Array.isArray(room.spawns) ? room.spawns.length : 0,
          hasPrimary: Boolean(room.spawn),
        };
        this._spawnCache.set(area, info);
      }
      if (!badge.isConnected) return;
      const sid = Number(tr.spawn_id) || 0;
      const valid = sid < info.spawns || (sid === 0 && info.hasPrimary);
      badge.className = `field-note transition-check ${valid ? "ok" : "bad"}`;
      badge.textContent = valid
        ? `✓ Area ${area} · spawn ${sid}${info.spawns ? ` of ${info.spawns}` : " (primary)"}`
        : `⚠ Area ${area} has ${info.spawns} spawn(s); spawn_id ${sid} is out of range`;
    } catch (err) {
      if (!badge.isConnected) return;
      badge.className = "field-note transition-check bad";
      badge.textContent = `⚠ Could not load Area ${area}: ${err.message}`;
    }
  }

  buildTransitionInspector(tr, index) {
    const areaOptions = [...new Set([...this.app.rooms.map((r) => r.area),
      tr.next_area ?? 0])].sort((a, b) => a - b);
    const nextArea = h("select", {
      onchange: () => {
        tr.next_area = Number(nextArea.value);
        this.markDirty();
        this.refreshInspector();
      },
    }, areaOptions.map((area) => h("option", {
      value: area, selected: Number(tr.next_area) === area,
      text: this.app.rooms.find((r) => r.area === area)?.label || `Area ${area}`,
    })));
    const inp = (key, label, step = 1) => {
      const input = h("input", {
        type: "number", value: tr[key] ?? 0, step,
        oninput: () => { tr[key] = Number(input.value); this.markDirty(); this.invalidate(); },
      });
      return h("div", { class: "field" }, h("span", { text: label }), input);
    };

    const padSelect = h("select", {
      onchange: () => {
        const val = Number(padSelect.value);
        if (val >= 0) {
          tr.pad_mask = val;
          padInput.value = String(val);
          this.markDirty();
        }
      },
    },
      h("option", { value: "255", text: "Touch / Any (255)", selected: tr.pad_mask === 255 || tr.pad_mask === undefined }),
      h("option", { value: "8", text: "Up button (8)", selected: tr.pad_mask === 8 }),
      h("option", { value: "4", text: "Down button (4)", selected: tr.pad_mask === 4 }),
      h("option", { value: "-1", text: "Custom…", selected: ![255, 8, 4, undefined].includes(tr.pad_mask) })
    );

    const padInput = h("input", {
      type: "number", value: tr.pad_mask ?? 255,
      oninput: () => {
        tr.pad_mask = Number(padInput.value);
        this.markDirty();
        padSelect.value = [255, 8, 4].includes(tr.pad_mask) ? String(tr.pad_mask) : "-1";
      },
    });

    const targetBadge = h("div", { class: "field-note transition-check",
      text: "Checking destination…" });
    const spawnInput = h("input", {
      type: "number", value: tr.spawn_id ?? 0,
      oninput: () => {
        tr.spawn_id = Number(spawnInput.value) || 0;
        this.markDirty();
        this.checkTransitionTarget(tr, targetBadge);
      },
    });

    this.inspectorBody.append(
      h("div", { class: "field" }, h("span", { text: "Next area" }), nextArea),
      targetBadge,
      h("div", { class: "field-2" }, inp("x", "X"), inp("y", "Y")),
      h("div", { class: "field-2" }, inp("half_w", "Half W"), inp("half_h", "Half H")),
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "Spawn ID" }), spawnInput),
        h("div", { class: "field" }, h("span", { text: "Trigger pad" }), padSelect)
      ),
      h("div", { class: "field-2" },
        inp("type", "Type"),
        h("div", { class: "field" }, h("span", { text: "Pad mask" }), padInput)
      ),
      h("div", { class: "row wrap" },
        h("button", {
          class: "btn small", type: "button", text: "Open target",
          disabled: !this.app.rooms.some((r) => r.area === Number(tr.next_area)),
          onclick: () => this.requestLoadArea(tr.next_area),
        }),
        (this.navHistory && this.navHistory.length) ? h("button", {
          class: "btn small", type: "button",
          text: `Back to Area ${this.navHistory[this.navHistory.length - 1]}`,
          onclick: () => {
            const prev = this.navHistory.pop();
            this.requestLoadArea(prev, false);
          },
        }) : null,
        h("button", { class: "btn small", type: "button", text: "Copy",
          onclick: () => this.copySelection() }),
        h("button", { class: "btn small", type: "button", text: "Duplicate",
          onclick: () => this.duplicateSelection() }),
        h("button", { class: "btn small danger", type: "button", text: "Delete",
          onclick: () => this.deleteSelection() }),
      ),
      h("div", { class: "field-note",
        text: "The transition rectangle is the trigger area. next_area points at room_area<N>.json; spawn_id selects the destination spawn." }),
    );
    this.checkTransitionTarget(tr, targetBadge);
  }

  buildSpawnInspector(sp, index) {
    const x = h("input", {
      type: "number", value: sp.x,
      oninput: () => { sp.x = Number(x.value); this.markDirty(); this.invalidate(); },
    });
    const y = h("input", {
      type: "number", value: sp.y,
      oninput: () => { sp.y = Number(y.value); this.markDirty(); this.invalidate(); },
    });
    const flags = h("input", {
      type: "number", value: sp.flags ?? 0,
      oninput: () => { sp.flags = Number(flags.value) || 0; this.markDirty(); },
    });
    this.inspectorBody.append(
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "X" }), x),
        h("div", { class: "field" }, h("span", { text: "Y" }), y),
      ),
      h("div", { class: "field" }, h("span", { text: "Flags" }), flags),
      h("div", { class: "row wrap" },
        index !== -1 ? h("button", {
          class: "btn small", type: "button", text: "Make primary",
          onclick: () => {
            this.pushUndo("make spawn primary");
            this.room.spawn = { x: this.room.spawns[index].x,
              y: this.room.spawns[index].y };
            this.markDirty();
            this.refreshInspector();
            this.invalidate();
          },
        }) : null,
        h("button", { class: "btn small danger", type: "button", text: "Delete",
          onclick: () => this.deleteSelection() }),
      ),
      h("div", { class: "field-note",
        text: "The primary spawn is where the room starts without a transition. Additional spawns can be targeted by doors via spawn_id." }),
    );
  }

  buildBoundsInspector(which) {
    const read = (label, value, onChange) => this.numbered(label, value, onChange);
    if (which === "play") {
      const p = this.room.play;
      this.inspectorBody.append(
        h("div", { class: "field-2" },
          read("min x", p.min_x, (v) => this.setBoundsValue("play", "min_x", v)),
          read("max x", p.max_x, (v) => this.setBoundsValue("play", "max_x", v))),
        h("div", { class: "field-2" },
          read("min y", p.min_y, (v) => this.setBoundsValue("play", "min_y", v)),
          read("max y", p.max_y, (v) => this.setBoundsValue("play", "max_y", v))),
        h("div", { class: "field-note",
          text: "Players cannot leave the play rectangle. The yellow rectangle is drawn over the map." }),
      );
    } else if (which === "camera") {
      const c = this.room.camera;
      this.inspectorBody.append(
        h("div", { class: "field-2" },
          read("min x", c.min_x, (v) => this.setBoundsValue("camera", "min_x", v)),
          read("max x", c.max_x, (v) => this.setBoundsValue("camera", "max_x", v))),
        h("div", { class: "field-2" },
          read("min y", c.min_y, (v) => this.setBoundsValue("camera", "min_y", v)),
          read("max y", c.max_y, (v) => this.setBoundsValue("camera", "max_y", v))),
        h("div", { class: "field-note",
          text: "Camera limits clamp the deadzone camera. The blue rectangle shows the allowed camera rectangle." }),
      );
    } else {
      const c = this.room.camera;
      this.inspectorBody.append(
        h("div", { class: "field-2" },
          read("x", c.x, (v) => { c.x = v; this.markDirty(); this.invalidate(); }),
          read("y", c.y, (v) => { c.y = v; this.markDirty(); this.invalidate(); })),
        h("div", { class: "field-note",
          text: "Initial camera position. The white rectangle is the 256×224 screen at that position." }),
      );
    }
  }

  updatePlacePanelFromSelection() {
    if (this.selection?.kind !== "object") return;
    const obj = this.room.objects[this.selection.index];
    if (!obj) return;
    const sp = this.app.speciesFor(obj.species, obj.flags);
    if (sp) this._place.speciesKey = sp.key;
    this._place.type = obj.type;
    this._place.flags = obj.flags ?? 0;
    this.objectTypeSelect.value = obj.type;
    this.placeFlags.value = obj.flags ?? 0;
    this.updatePlaceChip();
  }

  refreshObjectList() {
    if (!this.objectList) return;
    clear(this.objectList);
    const filter = (this.objectFilter?.value || "").toLowerCase();
    const rows = [];
    (this.room.objects || []).forEach((obj, index) => {
      const sp = this.app.speciesFor(obj.species, obj.flags);
      const text = `${obj.type} ${sp?.name || speciesHex(obj.species)}`;
      if (filter && !text.toLowerCase().includes(filter) &&
        !String(obj.species).includes(filter)) return;
      const row = h("div", {
        class: `obj-row${this.selection?.kind === "object" && this.selection.index === index ? " active" : ""}`,
        title: `${text} at ${obj.x},${obj.y}`,
        onclick: () => {
          this.select({ kind: "object", index });
          this.centerOn(obj.x, obj.y);
        },
      },
      h("i", { class: "swatch", style: { background: OBJECT_COLORS[obj.type] || "#888" } }),
      h("span", { class: "label", text }),
      h("span", { class: "coords", text: `${Math.round(obj.x)},${Math.round(obj.y)}` }),
      );
      rows.push(row);
    });
    if (!rows.length) {
      this.objectList.appendChild(h("div", { class: "inspector-empty",
        style: { padding: "18px" }, text: "No objects." }));
    } else {
      rows.forEach((r) => this.objectList.appendChild(r));
    }
  }

  centerOn(wx, wy) {
    this.view.x = wx - this.cssW / 2 / this.view.zoom;
    this.view.y = wy - this.cssH / 2 / this.view.zoom;
    this.invalidate();
  }

  /* ------------------------------------------------------------- validation */
  async runValidation() {
    try {
      const data = await api.validateRoom(this.area, this.room);
      this.validation = data;
      this.updateValidationBadge();
      if (!this.selection) this.refreshInspector();
      const errors = data.errors?.length || 0;
      const warnings = data.warnings?.length || 0;
      toast(`Validation: ${errors} error(s), ${warnings} warning(s)`,
        errors ? "error" : warnings ? "warn" : "ok");
      return data;
    } catch (error) {
      toast(`Validation failed: ${error.message}`, "error");
      return null;
    }
  }

  updateValidationBadge() {
    if (!this.validationBadge) return;
    const errors = this.validation?.errors?.length || 0;
    const warnings = this.validation?.warnings?.length || 0;
    this.validationBadge.textContent = errors
      ? `${errors} error${errors === 1 ? "" : "s"}`
      : warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : "Valid";
    this.validationBadge.className = `btn small ${errors ? "danger" :
      warnings ? "" : "ghost"}`;
  }

  showValidation() {
    showModal({
      title: "Room validation",
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        h("div", { class: "field-note",
          text: "Hard errors block saving. Warnings are data the engine clamps or ignores." }),
        issueList(this.validation)),
      wide: true,
      actions: [
        { label: "Validate again", onClick: () => { this.runValidation(); return false; } },
        { label: "Close", primary: true },
      ],
    });
  }

  /* ------------------------------------------------------------------ save */
  async save(target = "authored") {
    if (!this.room) return;
    this.room.area_id = this.area;
    this.app.setStatus("Validating and saving…");
    try {
      const result = await api.saveRoom(this.area, this.room, target);
      if (!result.ok) {
        this.validation = result.validation;
        this.updateValidationBadge();
        this.showValidation();
        toast("Save blocked — fix the errors first.", "error");
        return;
      }
      this.validation = result.validation;
      this.source = target === "generated" ? "generated" : "authored";
      this.authored = target !== "generated";
      this.generated = true;
      this.markClean();
      this.updateValidationBadge();
      this.refreshInspector();
      this.app.reloadRooms().then((rooms) => {
        this.app.rooms = rooms;
        this.fillRoomSelect();
        this.roomSelect.value = String(this.area);
      });
      toast(`Saved ${result.path}${result.backup ? ` · backup ${result.backup}` : ""}`,
        "ok", 3600);
      this.app.setStatus(`Saved ${result.path}`,
        `${this.room.world.width}×${this.room.world.height}`);
    } catch (error) {
      this.app.setSaveState("error", "Error");
      toast(`Save failed: ${error.message}`, "error", 5000);
    }
  }

  showSaveMenu() {
    showModal({
      title: "Save options",
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        h("div", { class: "field-note",
          text: "Authored is the normal target: it writes assets/authored/rooms/room_areaN.json, which the game prefers at load time. Generated overwrites the ROM-derived room (a backup is kept)." }),
        h("button", {
          class: "btn primary", type: "button", text: "Save to authored overlay",
          onclick: () => { this.save("authored"); },
        }),
        h("button", {
          class: "btn", type: "button", text: "Save into generated assets",
          onclick: async () => {
            const ok = await confirmDialog("Overwrite generated room?",
              `This writes assets/generated/room_area${this.area}.json and removes any authored override. A timestamped backup is kept.`,
              { okLabel: "Overwrite generated", danger: true });
            if (ok) this.save("generated");
          },
        }),
        h("hr"),
        h("button", {
          class: "btn", type: "button", text: "Export room JSON…",
          onclick: () => {
            const blob = new Blob([JSON.stringify(this.room, null, 1)],
              { type: "application/json" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `room_area${this.area}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
          },
        }),
        this.authored && this.generated ? h("button", {
          class: "btn danger", type: "button", text: "Revert to generated room",
          onclick: async () => {
            const ok = await confirmDialog("Remove authored override?",
              "The authored room file is deleted and the generated room loads again.",
              { okLabel: "Revert", danger: true });
            if (!ok) return;
            try {
              await api.revertRoom(this.area);
              toast("Authored override removed.", "ok");
              await this.loadRoom(this.area);
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
      const ok = await confirmDialog("Reload room?",
        "Unsaved changes will be lost.", { okLabel: "Reload", danger: true });
      if (!ok) return;
    }
    await this.loadRoom(this.area);
  }

  /* ------------------------------------------------------------------ dialogs */
  showNewRoomDialog() {
    const areas = new Set(this.app.rooms.map((r) => r.area));
    let nextArea = 200;
    while (areas.has(nextArea)) nextArea += 1;
    const areaInput = h("input", { type: "number", value: nextArea, min: "0",
      max: "4095" });
    const nameInput = h("input", { type: "text", value: `area${nextArea}` });
    const sizeSelect = h("select", {},
      h("option", { value: "512x256", selected: true, text: "512 × 256 (two screens wide)" }),
      h("option", { value: "256x224", text: "256 × 224 (one screen)" }),
      h("option", { value: "1024x512", text: "1024 × 512" }),
      h("option", { value: "2048x512", text: "2048 × 512" }),
      h("option", { value: "custom", text: "Custom…" }),
    );
    const widthInput = h("input", { type: "number", value: 512, min: "256",
      step: "8" });
    const heightInput = h("input", { type: "number", value: 256, min: "224",
      step: "8" });
    const atlasSelect = h("select", {});
    for (const room of this.app.rooms) {
      atlasSelect.appendChild(h("option", {
        value: room.area, selected: room.area === this.area,
        text: `${room.label} (${room.area})`,
      }));
    }
    const template = h("select", {},
      h("option", { value: "blank", text: "Blank (transparent layers)" }),
      h("option", { value: "floor", text: "Floor + walls" }),
    );
    widthInput.disabled = true;
    heightInput.disabled = true;
    sizeSelect.addEventListener("change", () => {
      if (sizeSelect.value === "custom") {
        widthInput.disabled = false;
        heightInput.disabled = false;
      } else {
        widthInput.disabled = true;
        heightInput.disabled = true;
        const [w, hgt] = sizeSelect.value.split("x").map(Number);
        widthInput.value = w;
        heightInput.value = hgt;
      }
    });
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "9px" } },
      h("div", { class: "field" }, h("span", { text: "Area id" }), areaInput),
      h("div", { class: "field" }, h("span", { text: "Name" }), nameInput),
      h("div", { class: "field" }, h("span", { text: "Size" }), sizeSelect),
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "Width" }), widthInput),
        h("div", { class: "field" }, h("span", { text: "Height" }), heightInput)),
      h("div", { class: "field" }, h("span", { text: "Tile atlas" }), atlasSelect),
      h("div", { class: "field" }, h("span", { text: "Template" }), template),
      h("div", { class: "field-note",
        text: "The new room is saved to assets/authored/rooms. Its tile atlas can borrow another area's background art; leave it on this area to use the shared global atlas." }),
    );
    const dlg = showModal({
      title: "New room",
      body,
      actions: [
        { label: "Cancel" },
        {
          label: "Create",
          primary: true,
          onClick: async () => {
            const area = Number(areaInput.value);
            if (this.app.rooms.some((r) => r.area === area)) {
              toast(`Area ${area} already exists; pick a free id.`, "error");
              return false;
            }
            try {
              const data = await api.newRoom({
                area,
                width: Number(widthInput.value),
                height: Number(heightInput.value),
                name: nameInput.value || `area${area}`,
                atlas_area: Number(atlasSelect.value),
                template: template.value,
              });
              dlg.close();
              this.area = area;
              this.routeArg = String(area);
              this.room = data.room;
              this.assets = await api.roomAssets(area, this.room.bg_atlas_area)
                .then((d) => d.assets).catch(() => null);
              this.source = "new";
              this.authored = false;
              this.generated = false;
              this.validation = data.validation;
              this.selection = null;
              this.undoStack = [];
              this.redoStack = [];
              this.dirty = true;
              this.app.setSaveState("dirty", "Unsaved");
              this.roomSelect.value = String(area);
              this.fillRoomSelect();
              history.replaceState(null, "", `#map/${area}`);
              this.syncRoomInputs();
              this.refreshAllPanels();
              this.fit();
              await this.preloadRoomImages();
              this.invalidate();
              toast(`Created area ${area}. Save to write it to disk.`, "ok");
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

  showResizeDialog() {
    const width = h("input", { type: "number", value: this.room.world.width,
      min: "256", step: "8" });
    const height = h("input", { type: "number", value: this.room.world.height,
      min: "224", step: "8" });
    const bg0 = h("input", { type: "checkbox" });
    const col = h("input", { type: "checkbox", checked: true });
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "9px" } },
      h("div", { class: "field-2" },
        h("div", { class: "field" }, h("span", { text: "Width" }), width),
        h("div", { class: "field" }, h("span", { text: "Height" }), height)),
      h("label", { class: "check" }, bg0, "Resize the BG0 parallax layer to the new world"),
      h("label", { class: "check" }, col, "Resize the collision grid"),
      h("div", { class: "field-note",
        text: "BG1 always resizes to cover the new world. Data outside the new bounds is dropped; data inside is preserved." }),
    );
    const dlg = showModal({
      title: "Resize room",
      body,
      actions: [
        { label: "Cancel" },
        {
          label: "Resize",
          primary: true,
          onClick: async () => {
            try {
              const data = await api.resizeRoom(this.area, this.room,
                Number(width.value), Number(height.value), bg0.checked,
                col.checked);
              this.pushUndo("resize room");
              this.room = data.room;
              this.validation = data.validation;
              this.markDirty();
              this.refreshAllPanels();
              this.fit();
              this.invalidate();
              dlg.close();
            } catch (error) {
              toast(`Resize failed: ${error.message}`, "error");
              return false;
            }
            return true;
          },
        },
      ],
    });
  }

  /* --------------------------------------------------------------- keyboard */
  showShortcutsHelp() {
    const rows = [
      ["V / C / T / O / D / S / H", "Select · Collision · Tiles · Objects · Door · Spawn · Pan"],
      ["Space-drag / middle-drag", "Pan the canvas"],
      ["Wheel / + / -", "Zoom at cursor / in / out"],
      ["0", "Fit the room"],
      ["G", "Toggle the tile grid"],
      ["P", "Toggle the 256×224 game preview"],
      ["M", "Toggle the minimap"],
      ["Ctrl+S", "Save the room"],
      ["Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y", "Undo / redo"],
      ["Ctrl+C / Ctrl+V / Ctrl+D", "Copy / paste / duplicate the selection"],
      ["Delete / Backspace", "Delete the selection"],
      ["Arrows / Shift+Arrows", "Nudge 1 px / 8 px"],
      ["Alt+click", "Pick the collision cell under the cursor"],
      ["Esc", "Deselect and return to Select"],
      ["?", "Open this shortcut sheet"],
    ];
    const table = h("table", { class: "shortcut-table" },
      h("thead", null,
        h("tr", null,
          h("th", { text: "Key" }),
          h("th", { text: "Action" }),
        ),
      ),
      h("tbody", null, ...rows.map(([keys, action]) => h("tr", null,
        h("td", null, h("kbd", { text: keys })),
        h("td", { text: action }),
      ))),
    );
    showModal({
      title: "Keyboard shortcuts",
      body: h("div", { class: "shortcut-body" },
        table,
        h("p", { class: "muted", text:
          "Doors: D places a transition, S sets the spawn. " +
          "Collision: right-click erases, Alt-click picks. " +
          "The canvas hint stays visible while the map is open." }),
      ),
      actions: [{ label: "Close", primary: true }],
    });
  }

  bindKeys() {
    this._onKeyDown = (event) => {
      if (this.destroyed) return;
      // A modal owns the keyboard while it is open.
      if (document.querySelector("#modal-root .modal-backdrop")) return;
      if (event.code === "Space") this.spaceDown = true;
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
      if ((event.ctrlKey || event.metaKey) && key === "d") {
        event.preventDefault(); this.duplicateSelection(); return;
      }
      if (editing) return;
      if (key === "?") { event.preventDefault(); this.showShortcutsHelp(); return; }
      if ((event.ctrlKey || event.metaKey) && key === "c") {
        event.preventDefault(); this.copySelection(); return;
      }
      if ((event.ctrlKey || event.metaKey) && key === "v") {
        event.preventDefault(); this.pasteClipboard(); return;
      }
      if (key === "escape") {
        this.select(null); this.setTool("select"); this.stroke = null; return;
      }
      if (key === "delete" || key === "backspace") {
        event.preventDefault(); this.deleteSelection(); return;
      }
      if (key === "v") this.setTool("select");
      else if (key === "c") this.setTool("collision");
      else if (key === "t") this.setTool("tile");
      else if (key === "o") this.setTool("object");
      else if (key === "d") this.setTool("door");
      else if (key === "s" && !event.ctrlKey) this.setTool("spawn");
      else if (key === "h") this.setTool("pan");
      else if (key === "p") this.togglePreview();
      else if (key === "0") this.fit();
      else if (key === "+" || key === "=") this.zoomBy(1.25);
      else if (key === "-") this.zoomBy(1 / 1.25);
      else if (key === "g") { this.show.grid = !this.show.grid; this.invalidate(); }
      else if (event.key.startsWith("Arrow") && this.selection) {
        event.preventDefault();
        const step = event.shiftKey ? 8 : 1;
        const sel = this.selection;
        const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
        const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
        this.pushUndo("nudge");
        if (sel.kind === "object") {
          const obj = this.room.objects[sel.index];
          obj.x += dx; obj.y += dy;
        } else if (sel.kind === "transition") {
          const tr = this.room.transitions[sel.index];
          tr.x += dx; tr.y += dy;
        } else if (sel.kind === "spawn") {
          const sp = sel.index === -1 ? this.room.spawn : this.room.spawns[sel.index];
          sp.x += dx; sp.y += dy;
          if (sel.index === -1 && this.room.spawns[0]) {
            this.room.spawns[0].x = sp.x; this.room.spawns[0].y = sp.y;
          }
        }
        this.markDirty();
        this.refreshInspector();
        this.invalidate();
      }
    };
    this._onKeyUp = (event) => {
      if (event.code === "Space") this.spaceDown = false;
    };
    window.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("keyup", this._onKeyUp);
  }

  unbindKeys() {
    window.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("keyup", this._onKeyUp);
  }

  updateStatus() {
    if (!this.room) return;
    this.app.setStatus(
      `Map Builder · ${this.app.rooms.find((r) => r.area === this.area)?.label || "Area " + this.area}`,
      `${this.room.world.width}×${this.room.world.height} px · ${this.room.objects?.length || 0} objects · ${this.room.transitions?.length || 0} doors · zoom ${Math.round(this.view.zoom * 100)}%`,
    );
  }
}
