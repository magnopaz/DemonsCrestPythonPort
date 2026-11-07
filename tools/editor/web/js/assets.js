/* Asset Browser: every PNG in the generated and authored trees, with
   dimensions, provenance and where the game uses it. */

import { api } from "./api.js";
import {
  h, clear, formatBytes, downloadBlob,
} from "./util.js";
import { icon } from "./icons.js";
import { toast, showModal } from "./ui.js";

export class AssetBrowser {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    this.arg = arg;
    this.images = [];
    this.query = "";
    this.source = "all";
    this.sort = "path";
    this.selected = null;
    this.el = null;
  }

  async init() {
    this.buildDom();
    this.container.replaceChildren(this.el);
    await this.reload();
  }

  destroy() { this.el?.remove(); }
  isDirty() { return false; }

  buildDom() {
    this.search = h("input", {
      type: "search", placeholder: "Filter by name, path or usage…",
      oninput: () => { this.query = this.search.value.trim().toLowerCase(); this.renderGrid(); },
    });
    this.sourceSelect = h("select", {
      onchange: () => { this.source = this.sourceSelect.value; this.renderGrid(); },
    },
    h("option", { value: "all", text: "All sources" }),
    h("option", { value: "generated", text: "Generated (ROM)" }),
    h("option", { value: "authored", text: "Authored (edited)" }),
    );
    this.sortSelect = h("select", {
      onchange: () => { this.sort = this.sortSelect.value; this.renderGrid(); },
    },
    h("option", { value: "path", text: "Sort: path" }),
    h("option", { value: "name", text: "Sort: name" }),
    h("option", { value: "size", text: "Sort: file size" }),
    h("option", { value: "dimensions", text: "Sort: dimensions" }),
    );
    this.countLabel = h("span", { class: "asset-count", text: "Loading…" });
    this.grid = h("div", { class: "asset-grid" });
    const toolbar = h("div", { class: "asset-toolbar" },
      icon("image"), h("span", { class: "toolbar-title", text: "Assets" }),
      this.search, this.sourceSelect, this.sortSelect,
      h("button", {
        class: "btn small", type: "button", text: "Refresh",
        onclick: () => this.reload(),
      }, icon("refresh")),
      h("span", { class: "grow" }),
      this.countLabel,
    );
    this.el = h("div", { class: "assets-view" }, toolbar, this.grid);
  }

  async reload() {
    try {
      const data = await api.assets();
      this.images = data.images || [];
      this.renderGrid();
      this.app.setStatus("Asset Browser",
        `${this.images.length} PNG files · generated + authored`);
    } catch (error) {
      toast(`Could not load assets: ${error.message}`, "error");
      clear(this.grid);
      this.grid.appendChild(h("div", { class: "inspector-empty",
        text: error.message }));
    }
  }

  filtered() {
    let list = this.images;
    if (this.source !== "all") list = list.filter((img) => img.source === this.source);
    if (this.query) {
      const tokens = this.query.split(/\s+/).filter(Boolean);
      list = list.filter((img) => {
        const hay = `${img.name} ${img.path} ${(img.usage || []).join(" ")}`.toLowerCase();
        return tokens.every((t) => hay.includes(t));
      });
    }
    const sorted = [...list];
    if (this.sort === "name") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else if (this.sort === "size") sorted.sort((a, b) => b.bytes - a.bytes);
    else if (this.sort === "dimensions") {
      sorted.sort((a, b) => (b.width * b.height) - (a.width * a.height));
    } else sorted.sort((a, b) => a.path.localeCompare(b.path));
    return sorted;
  }

  renderGrid() {
    const list = this.filtered();
    clear(this.grid);
    this.countLabel.textContent = `${list.length} / ${this.images.length} PNG`;
    if (!list.length) {
      this.grid.appendChild(h("div", { class: "inspector-empty",
        text: "No images match the filter." }));
      return;
    }
    const frag = document.createDocumentFragment();
    for (const img of list) {
      const card = h("div", {
        class: `asset-card${this.selected?.key === img.key ? " selected" : ""}`,
        title: `${img.path}\n${img.width}×${img.height} · ${formatBytes(img.bytes)}`,
        onclick: () => { this.selected = img; this.renderGrid(); this.openDetail(img); },
      },
      h("div", { class: "asset-thumb" },
        h("img", { src: img.url, alt: img.name, loading: "lazy",
          draggable: "false" })),
      h("div", { class: "asset-meta" },
        h("div", { class: "asset-name", text: img.name }),
        h("div", { class: "asset-sub" },
          h("span", { text: `${img.width}×${img.height}` }),
          h("span", { text: formatBytes(img.bytes) })),
        h("div", { class: "asset-use",
          title: (img.usage || []).join("\n"),
          text: (img.usage && img.usage.length) ? img.usage[0] : "Unused / library" }),
      ));
      frag.appendChild(card);
    }
    this.grid.appendChild(frag);
  }

  openDetail(img) {
    const info = h("div", { class: "kv" },
      h("dt", { text: "Path" }), h("dd", { text: img.path }),
      h("dt", { text: "Source" }), h("dd", { text: img.source }),
      h("dt", { text: "Dimensions" }), h("dd", { text: `${img.width} × ${img.height}` }),
      h("dt", { text: "Size" }), h("dd", { text: formatBytes(img.bytes) }),
    );
    const usage = h("div", { class: "issue-list" });
    if (img.usage?.length) {
      for (const use of img.usage.slice(0, 40)) {
        usage.appendChild(h("div", { class: "issue", text: use }));
      }
      if (img.usage.length > 40) {
        usage.appendChild(h("div", { class: "issue",
          text: `…and ${img.usage.length - 40} more` }));
      }
    } else {
      usage.appendChild(h("div", { class: "issue",
        text: "No room, species or player record references this image." }));
    }
    const body = h("div", { class: "asset-detail-grid" },
      h("div", { class: "asset-detail-img" },
        h("img", { src: img.url, alt: img.name,
          style: { imageRendering: "pixelated" } })),
      h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
        info,
        h("div", { class: "small dim", text: "Used by" }),
        usage,
        h("div", { class: "row wrap" },
          h("button", {
            class: "btn small", type: "button", text: "Download PNG",
            onclick: () => this.downloadImage(img),
          }, icon("download")),
          h("button", {
            class: "btn small", type: "button", text: "Copy path",
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(img.path);
                toast("Path copied.", "ok", 1200);
              } catch { toast("Clipboard unavailable.", "warn"); }
            },
          }, icon("copy")),
        ),
      ),
    );
    showModal({
      title: img.name,
      body,
      wide: true,
      actions: [{ label: "Close", primary: true }],
    });
  }

  async downloadImage(img) {
    try {
      const response = await fetch(img.url);
      const blob = await response.blob();
      downloadBlob(img.name, blob);
    } catch (error) {
      toast(`Download failed: ${error.message}`, "error");
    }
  }
}
