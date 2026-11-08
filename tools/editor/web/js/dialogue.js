/* Dialogue editor: the 518 ROM text blocks, the pages the game really draws
   (the loader caps pages/lines), the 8x8 font preview, and the text_find
   needles the game uses.  Edits go to assets/authored/text_strings.json. */

import { api } from "./api.js";
import {
  h, clear, loadImage, clamp,
} from "./util.js";
import { icon } from "./icons.js";
import {
  toast, confirmDialog, showModal, tabs,
} from "./ui.js";

const SAMPLE_ROWS = 6;

function clonePages(pages) {
  return (pages || []).map((page) =>
    (Array.isArray(page) ? page : []).map((line) => String(line)));
}

/* The loader's rules, kept in one place so the preview follows the editor. */
function splitLine(src, lineMax) {
  const out = [];
  let buf = "";
  for (const ch of String(src)) {
    if (ch === "j") {
      if (buf) out.push(buf);
      buf = "";
    } else if (buf.length + 1 < lineMax) {
      buf += ch;
    }
  }
  if (buf) out.push(buf);
  return out;
}

function simulate(pages, caps) {
  const out = [];
  let kept = 0;
  for (const page of pages || []) {
    if (kept >= caps.pages) break;
    const lines = [];
    for (const line of Array.isArray(page) ? page : []) {
      if (lines.length >= caps.lines) break;
      for (const piece of splitLine(line, caps.line_max)) {
        if (lines.length >= caps.lines) break;
        lines.push(piece.replace(/\[/g, "'").replace(/\\/g, "."));
      }
    }
    if (lines.length) {
      out.push(lines);
      kept += 1;
    }
  }
  return out;
}

function normalize(text) {
  return String(text).toUpperCase().replace(/[^A-Z0-9]+/g, " ");
}

function blockMatches(block, tokens) {
  if (!tokens.length) return true;
  const hay = [
    `#${block.index}`, block.addr, block.preview,
    ...(block.pages || []).flat(), ...(block.used_by || []),
  ].join(" ").toLowerCase();
  return tokens.every((token) => hay.includes(token));
}

export class DialogueEditor {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    this.arg = arg;
    this.data = null;
    this.blocks = [];
    this.index = Number.parseInt(arg, 10);
    this.hadArg = Number.isFinite(this.index);
    if (!this.hadArg) this.index = 0;
    this.routeArg = this.hadArg ? String(this.index) : "";
    this.page = 0;
    this.draftPages = [];
    this.dirty = false;
    this.query = "";
    this.proseOnly = true;
    this.fontImage = null;
    this.el = null;
    this._onResize = () => { if (!this.destroyed) this.drawPreview(); };
    this.destroyed = false;
  }

  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    window.addEventListener("resize", this._onResize);
    this.bindKeys();
    await this.reload({ initial: true });
  }

  destroy() {
    this.destroyed = true;
    window.removeEventListener("resize", this._onResize);
    this.unbindKeys();
    this.el?.remove();
  }

  isDirty() { return this.dirty; }
  dirtyPromptKey() { return `#dialogue/${this.index}`; }
  get block() { return this.blocks.find((b) => b.index === this.index) || null; }

  /* ------------------------------------------------------------------ DOM */
  buildDom() {
    this.saveBtn = h("button", {
      class: "btn", type: "button", title: "Save (Ctrl+S)",
      onclick: () => this.save(),
    }, icon("save"), h("span", { text: "Save" }));
    this.revertBtn = h("button", {
      class: "btn", type: "button", title: "Revert this block",
      onclick: () => this.revert(),
    }, icon("undo"), h("span", { text: "Revert" }));
    this.search = h("input", {
      type: "search", placeholder: "Search text, address or index…",
      oninput: () => {
        this.query = this.search.value.trim().toLowerCase();
        this.renderList();
      },
    });
    this.proseCheck = h("input", {
      type: "checkbox", checked: true,
      onchange: () => { this.proseOnly = this.proseCheck.checked; this.renderList(); },
    });
    this.counter = h("span", { class: "asset-count", text: "Loading…" });

    const toolbar = h("div", { class: "toolbar" },
      h("span", { class: "toolbar-title", text: "Dialogue" }),
      h("label", { class: "check" }, this.proseCheck, "Dialogue only"),
      this.search,
      h("span", { class: "sep" }),
      this.saveBtn, this.revertBtn,
      h("button", {
        class: "btn small", type: "button", text: "Font atlas",
        onclick: () => this.showFont(),
      }, icon("grid")),
      h("span", { class: "grow" }),
      this.counter,
    );

    this.list = h("div", { class: "dialogue-list" });
    this.leftPanel = h("aside", { class: "panel left" },
      h("div", { class: "panel-head" }, icon("book"),
        h("span", { text: "Text blocks" })),
      this.list,
    );

    this.canvas = h("canvas", { id: "dialogue-canvas" });
    this.stageInfo = h("div", { class: "dialogue-info", text: "—" });
    this.pageLabel = h("span", { class: "zoom-label", text: "1 / 1" });
    this.prevBtn = h("button", {
      class: "btn small", type: "button", text: "‹",
      onclick: () => this.setPage(this.page - 1),
    });
    this.nextBtn = h("button", {
      class: "btn small", type: "button", text: "›",
      onclick: () => this.setPage(this.page + 1),
    });
    this.stage = h("div", { class: "dialogue-stage" },
      h("div", { class: "dialogue-stage-head" },
        h("span", { class: "mono", text: "WHAT THE GAME DISPLAYS" }),
        h("span", { class: "spacer" }),
        this.prevBtn, this.pageLabel, this.nextBtn,
      ),
      h("div", { class: "dialogue-canvas-wrap" }, this.canvas),
      this.stageInfo,
      h("div", { class: "dialogue-hint",
        text: "The loader keeps 8 pages × 8 lines, splits on 'j' and cuts " +
          "each line to 47 characters.  The editor draws exactly that." }),
    );

    this.info = h("div", { class: "section-body" });
    this.editorPage = h("select", {
      onchange: () => this.setPage(Number(this.editorPage.value)),
    });
    this.textarea = h("textarea", {
      class: "dialogue-text", spellcheck: "false", rows: 8,
      oninput: () => {
        if (!this.block) return;
        this.draftPages[this.page] = this.textarea.value.split("\n");
        this.markDirty();
        this.drawPreview();
        this.renderInfo();
      },
    });
    this.addPageBtn = h("button", {
      class: "btn small", type: "button", text: "Add page",
      onclick: () => this.addPage(),
    });
    this.delPageBtn = h("button", {
      class: "btn small", type: "button", text: "Remove page",
      onclick: () => this.removePage(),
    });
    this.blockTab = h("div", { class: "dialogue-block" });
    this.usagesTab = h("div", { class: "usage-list" });
    this.rightTabs = tabs([
      { id: "block", label: "Block", render: () => this.blockTab },
      { id: "usages", label: "Usages", render: () => this.usagesTab },
    ]);
    this.rightPanel = h("aside", { class: "panel right" },
      h("div", { class: "panel-head" }, icon("info"),
        h("span", { text: "Inspector" })),
      this.rightTabs.el,
    );

    this.el = h("div", { class: "editor dialogue-editor" },
      toolbar,
      h("div", { class: "editor-body" },
        this.leftPanel,
        this.stage,
        this.rightPanel,
      ),
    );
    this.app.setStatus("Dialogue editor", "Reading text_strings.json…");
  }

  bindKeys() {
    this.onKey = (event) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "s") {
        event.preventDefault();
        this.save();
      }
    };
    document.addEventListener("keydown", this.onKey);
  }

  unbindKeys() {
    if (this.onKey) document.removeEventListener("keydown", this.onKey);
  }

  /* ----------------------------------------------------------------- data */
  async reload({ initial = false } = {}) {
    try {
      const data = await api.text();
      this.data = data;
      this.blocks = data.blocks || [];
      if (initial && !this.hadArg) {
        const used = this.blocks.find((b) => b.used_by?.length);
        if (used) this.index = used.index;
      }
      if (!this.block) {
        this.index = clamp(this.index, 0, Math.max(0, this.blocks.length - 1));
      }
      if (!this.fontImage && data.font?.url) {
        this.fontImage = await loadImage(data.font.url);
      }
      this.counter.textContent =
        `${data.stats.blocks} blocks · ${data.stats.prose} dialogue · ` +
        `${data.stats.authored} edited`;
      this.renderList();
      this.loadBlock({ keepDirty: false });
      this.renderUsages();
      this.app.setStatus("Dialogue editor",
        `${data.stats.blocks} blocks · ${data.stats.with_warnings} with loader warnings · ` +
        `${data.usages.filter((u) => !u.found).length} missing needle(s)`);
    } catch (error) {
      toast(`Could not load the dialogue: ${error.message}`, "error");
      clear(this.list);
      this.list.appendChild(h("div", { class: "inspector-empty", text: error.message }));
    }
  }

  loadBlock({ keepDirty = false } = {}) {
    const block = this.block;
    if (!block) return;
    if (!keepDirty) {
      this.draftPages = clonePages(block.pages);
      this.dirty = false;
      this.page = 0;
      this.app.setSaveState("", "Idle");
      this.saveBtn.classList.remove("primary");
    }
    this.page = clamp(this.page, 0, Math.max(0, this.draftPages.length - 1));
    this.renderList();
    this.renderInfo();
    this.renderEditor();
    this.drawPreview();
  }

  /* --------------------------------------------------------------- list */
  visibleBlocks() {
    const tokens = this.query.split(/\s+/).filter(Boolean);
    return this.blocks.filter((block) => {
      if (this.proseOnly && !block.prose) return false;
      return blockMatches(block, tokens);
    });
  }

  renderList() {
    if (!this.blocks.length) return;
    const rows = this.visibleBlocks();
    clear(this.list);
    const frag = document.createDocumentFragment();
    for (const block of rows) {
      const badges = [];
      if (block.authored) badges.push(h("span", { class: "badge gold", text: "edit" }));
      if (block.warnings.length) {
        badges.push(h("span", {
          class: "badge warn", text: `${block.warnings.length}w`,
        }));
      }
      if (block.used_by.length) badges.push(h("span", { class: "badge green", text: "used" }));
      frag.appendChild(h("button", {
        class: `dialogue-row${block.index === this.index ? " active" : ""}`,
        type: "button",
        title: `${block.addr || "no address"} · ${block.pages.length} page(s)`,
        onclick: () => this.selectBlock(block.index),
      },
      h("span", { class: "idx", text: `#${block.index}` }),
      h("span", { class: "preview", text: block.preview || "(empty)" }),
      h("span", { class: "row-badges" }, ...badges),
      ));
    }
    if (!rows.length) {
      frag.appendChild(h("div", { class: "inspector-empty", text: "No blocks match." }));
    }
    this.list.appendChild(frag);
    this.counter.textContent =
      `${rows.length} / ${this.blocks.length} blocks · ${this.data?.stats.prose || 0} dialogue`;
  }

  async selectBlock(index) {
    if (index === this.index) return;
    if (this.dirty) {
      const ok = await confirmDialog("Discard unsaved text?",
        "This block has unsaved edits. Switching blocks will lose them.",
        { okLabel: "Discard edits", danger: true });
      if (!ok) return;
    }
    this.index = index;
    this.routeArg = String(index);
    this.app.navigate(`#dialogue/${index}`, { replace: true });
    this.loadBlock();
  }

  /* --------------------------------------------------------------- info */
  renderInfo() {
    const block = this.block;
    if (!block) return;
    const loaded = simulate(this.draftPages, this.data.caps);
    clear(this.info);
    this.info.append(
      h("dl", { class: "kv" },
        h("dt", { text: "Block" }), h("dd", { text: `#${block.index}` }),
        h("dt", { text: "ROM" }), h("dd", { text: block.addr || "—" }),
        h("dt", { text: "Length" }), h("dd", { text: `${block.length} B` }),
        h("dt", { text: "Raw pages" }), h("dd", { text: String(this.draftPages.length) }),
        h("dt", { text: "Shown" }), h("dd", { text: `${loaded.length} page(s)` }),
        h("dt", { text: "Chars" }), h("dd", { text: String(block.chars) }),
        h("dt", { text: "Used by" }), h("dd", {
          text: block.used_by.length ? block.used_by.join(", ") : "—",
        }),
      ),
      block.authored
        ? h("div", { class: "badge gold", text: "authored override" })
        : h("div", { class: "badge", text: "generated (ROM)" }),
    );
    if (block.warnings.length) {
      const list = h("div", { class: "issue-list" });
      for (const warning of block.warnings) {
        list.appendChild(h("div", {
          class: `issue ${warning.level === "error" ? "error"
            : warning.level === "warning" ? "warning" : ""}`,
        },
        h("div", { text: warning.message }),
        h("div", { class: "code", text: warning.code }),
        ));
      }
      this.info.append(h("div", { class: "dialogue-subhead", text: "Loader warnings" }), list);
    } else {
      this.info.append(h("div", { class: "issue ok", text: "Loads without warnings." }));
    }
  }

  renderEditor() {
    clear(this.blockTab);
    clear(this.editorPage);
    for (let i = 0; i < this.draftPages.length; i += 1) {
      this.editorPage.appendChild(h("option", {
        value: String(i), selected: i === this.page, text: `Page ${i + 1}`,
      }));
    }
    this.textarea.value = (this.draftPages[this.page] || []).join("\n");
    this.blockTab.append(
      this.info,
      h("div", { class: "section-head", text: "Edit raw pages" }),
      h("div", { class: "field" },
        h("span", { text: "Page" }),
        h("div", { class: "row" }, this.editorPage, this.addPageBtn, this.delPageBtn),
      ),
      this.textarea,
      h("div", { class: "field-note",
        text: "One line per row.  'j' is the ROM's in-line break; '[' is an " +
          "apostrophe and '\\' is a period." }),
      h("div", { class: "row" },
        h("span", { class: "field-note grow",
          text: dirtyText(this.dirty) }),
        h("button", {
          class: "btn small primary", type: "button", text: "Save block",
          onclick: () => this.save(),
        }),
      ),
    );
  }

  setPage(page) {
    if (!this.block) return;
    const next = clamp(page, 0, Math.max(0, this.draftPages.length - 1));
    if (next === this.page) return;
    this.page = next;
    this.editorPage.value = String(this.page);
    this.renderEditor();
    this.drawPreview();
  }

  addPage() {
    if (!this.block) return;
    this.draftPages.push(["NEW PAGE"]);
    this.page = this.draftPages.length - 1;
    this.markDirty();
    this.renderEditor();
    this.drawPreview();
    this.renderInfo();
  }

  removePage() {
    if (!this.block || this.draftPages.length <= 1) {
      toast("A block needs at least one page", "warn");
      return;
    }
    this.draftPages.splice(this.page, 1);
    this.page = clamp(this.page, 0, this.draftPages.length - 1);
    this.markDirty();
    this.renderEditor();
    this.drawPreview();
    this.renderInfo();
  }

  markDirty() {
    if (this.dirty) return;
    this.dirty = true;
    this.app.setSaveState("dirty", "Unsaved");
    this.saveBtn.classList.add("primary");
  }

  /* -------------------------------------------------------------- preview */
  drawPreview() {
    const caps = this.data?.caps || { pages: 8, lines: 8, line_max: 48, glyph: 8, line_height: 10 };
    const pad = 12;
    const width = caps.line_max * caps.glyph + pad * 2;
    const height = caps.lines * caps.line_height + pad * 2;
    // Integer scaling only: a pixel-art font stretched by 1.6x looks like
    // noise, and the preview must be readable to be useful.
    const available = Math.max(200, (this.canvas.parentElement?.clientWidth || 640) - 36);
    const scale = clamp(Math.floor(available / width), 1, 5);
    const canvas = this.canvas;
    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.style.width = `${width * scale}px`;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#07080b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#3a4050";
    ctx.lineWidth = 1;
    ctx.strokeRect((pad - 5.5) * scale, (pad - 5.5) * scale,
      (width - pad * 2 + 11) * scale, (height - pad * 2 + 11) * scale);
    const pages = simulate(this.draftPages, caps);
    const shown = pages[this.page] || [];
    if (!this.fontImage) {
      ctx.fillStyle = "#6f7587";
      ctx.font = `${10 * scale}px monospace`;
      ctx.fillText("font.png not found", pad * scale, (pad + 12) * scale);
      this.pageLabel.textContent = "—";
      this.stageInfo.textContent = "No font atlas at assets/generated/font.png";
      return;
    }
    const cell = this.data.font.cell || 8;
    const columns = this.data.font.columns || 16;
    const first = this.data.font.first || 32;
    const last = this.data.font.last || 126;
    for (let line = 0; line < shown.length; line += 1) {
      const text = shown[line];
      for (let col = 0; col < text.length; col += 1) {
        const code = text.charCodeAt(col);
        if (code < first || code > last) continue;
        const index = code - first;
        const sx = (index % columns) * cell;
        const sy = Math.floor(index / columns) * cell;
        ctx.drawImage(this.fontImage, sx, sy, cell, cell,
          (pad + col * caps.glyph) * scale,
          (pad + line * caps.line_height) * scale,
          caps.glyph * scale, cell * scale);
      }
    }
    this.pageLabel.textContent =
      `${this.page + 1} / ${Math.max(1, this.draftPages.length)}`;
    this.prevBtn.disabled = this.page <= 0;
    this.nextBtn.disabled = this.page >= this.draftPages.length - 1;
    if (!pages.length) {
      this.stageInfo.textContent = "The game would draw nothing for this block";
    } else if (this.page >= pages.length) {
      this.stageInfo.textContent =
        `raw page ${this.page + 1} is dropped by the ${caps.pages}-page cap`;
    } else {
      this.stageInfo.textContent =
        `shown page ${this.page + 1} of ${pages.length} · ${shown.length} line(s) · ` +
        `${this.draftPages.length} raw page(s)`;
    }
  }

  /* --------------------------------------------------------------- usages */
  renderUsages() {
    clear(this.usagesTab);
    const usages = this.data?.usages || [];
    const missing = usages.filter((u) => !u.found);
    this.usagesTab.appendChild(h("div", { class: "field-note",
      text: `${usages.length} text_find needle(s) in dcpy/game.py · ` +
        `${missing.length} missing.  A missing needle means the game shows no dialogue.` }));
    for (const usage of usages) {
      this.usagesTab.appendChild(h("button", {
        class: `usage-row${usage.found ? "" : " missing"}`,
        type: "button",
        title: usage.where,
        onclick: () => {
          if (!usage.found) return;
          this.selectBlock(usage.index);
          this.rightTabs.select("block");
        },
      },
      h("span", { class: usage.found ? "badge green" : "badge red",
        text: usage.found ? String(usage.index) : "—" }),
      h("span", { class: "usage-needle", text: usage.needle }),
      h("span", { class: "usage-where", text: usage.where }),
      ));
    }
  }

  /* ---------------------------------------------------------------- save */
  async save() {
    if (!this.block) return;
    try {
      const result = await api.saveText(this.index, this.draftPages);
      if (!result.ok) {
        const message = result.errors?.[0]?.message || result.error || "save failed";
        toast(message, "error", 5000);
        return;
      }
      this.dirty = false;
      this.app.setSaveState("saved", "Saved");
      this.saveBtn.classList.remove("primary");
      toast(`Block #${this.index} saved`, "ok");
      await this.reload();
      this.app.setSaveState("saved", "Saved");
    } catch (error) {
      toast(`Save failed: ${error.message}`, "error");
    }
  }

  async revert() {
    if (!this.block) return;
    if (this.block.authored) {
      const ok = await confirmDialog("Revert this block?",
        "The authored override is deleted and the generated ROM text returns.",
        { okLabel: "Revert block", danger: true });
      if (!ok) return;
      try {
        const result = await api.deleteText(this.index);
        if (!result.ok) {
          toast(result.error || "revert failed", "error");
          return;
        }
        toast(`Block #${this.index} reverted`, "ok");
        await this.reload();
      } catch (error) {
        toast(`Revert failed: ${error.message}`, "error");
      }
      return;
    }
    if (this.dirty) {
      const ok = await confirmDialog("Discard local edits?",
        "This block has unsaved edits; reverting restores the loaded pages.",
        { okLabel: "Discard edits", danger: true });
      if (!ok) return;
    }
    this.draftPages = clonePages(this.block.pages);
    this.page = 0;
    this.dirty = false;
    this.app.setSaveState("", "Idle");
    this.saveBtn.classList.remove("primary");
    this.renderEditor();
    this.drawPreview();
    this.renderInfo();
  }

  /* ---------------------------------------------------------------- font */
  showFont() {
    const font = this.data?.font;
    if (!font?.url) {
      toast("font.png is missing", "warn");
      return;
    }
    const cell = font.cell || 8;
    const cols = font.columns || 16;
    const rows = font.rows || 6;
    const zoom = 4;
    const canvas = h("canvas", {
      width: cols * cell * zoom,
      height: rows * cell * zoom,
      style: { imageRendering: "pixelated", width: `${cols * cell * zoom}px` },
    });
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#07080b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const img = this.fontImage;
    loadImage(font.url).then((loaded) => {
      if (!loaded) return;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(loaded, 0, 0, loaded.width, loaded.height,
        0, 0, cols * cell * zoom, rows * cell * zoom);
    });
    showModal({
      title: `BG3 font · 0x${font.first.toString(16).toUpperCase()}..` +
        `0x${font.last.toString(16).toUpperCase()} · ${font.filled} filled`,
      body: h("div", { class: "font-atlas" },
        canvas,
        h("div", { class: "field-note",
          text: `${cols} columns × ${rows} rows of ${cell}×${cell} px, drawn at ${zoom}×. ` +
            `The first cell is 0x${font.first.toString(16).toUpperCase()} (space).` })),
      wide: true,
      actions: [{ label: "Close", value: null }],
    });
  }
}

function dirtyText(dirty) {
  return dirty ? "Unsaved edits — Ctrl+S saves this block."
    : "No unsaved edits.";
}
