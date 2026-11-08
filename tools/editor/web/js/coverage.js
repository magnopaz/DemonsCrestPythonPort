/* Project coverage: what the rooms contain, which species have a handler and
   which still draw the magenta placeholder.  This is the browser view of
   `tools/report_coverage.py`, joined with the authored art sheets. */

import { api } from "./api.js";
import { h, clear } from "./util.js";
import { icon } from "./icons.js";
import { toast, showModal, tabs } from "./ui.js";

const TYPE_LABELS = {
  unknown: "unknown",
  enemy: "enemy",
  boss: "boss",
  urn: "urn",
  decor: "decor",
  inert: "inert",
  npc: "npc",
  platform: "platform",
  pickup_crest: "crest",
  talisman: "talisman",
  exit: "exit",
};

function typeSummary(types) {
  return Object.entries(types || {})
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${count} ${TYPE_LABELS[type] || type}`)
    .join(" · ");
}

function matches(query, ...fields) {
  if (!query) return true;
  const hay = fields.join(" ").toLowerCase();
  return query.split(/\s+/).filter(Boolean).every((token) => hay.includes(token));
}

export class CoverageView {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    this.arg = arg;
    this.data = null;
    this.query = "";
    this.filter = "all";
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
      type: "search", placeholder: "Filter by species, name, area or room…",
      oninput: () => { this.query = this.search.value.trim().toLowerCase(); this.renderAll(); },
    });
    this.filterSelect = h("select", {
      onchange: () => { this.filter = this.filterSelect.value; this.renderAll(); },
    },
    h("option", { value: "all", text: "All species" }),
    h("option", { value: "placeholder", text: "With placeholders" }),
    h("option", { value: "only-placeholder", text: "Placeholder only" }),
    h("option", { value: "no-art", text: "No art sheet" }),
    h("option", { value: "boss", text: "Bosses" }),
    h("option", { value: "authored", text: "Edited sheets" }),
    );
    this.countLabel = h("span", { class: "asset-count", text: "Loading…" });
    this.stats = h("div", { class: "stat-grid" });
    this.tabView = tabs([
      { id: "species", label: "Species", render: () => this.renderSpecies() },
      { id: "rooms", label: "Rooms", render: () => this.renderRooms() },
      { id: "collectibles", label: "Collectibles", render: () => this.renderCollectibles() },
      { id: "gaps", label: "Gaps", render: () => this.renderGaps() },
    ]);
    this.el = h("div", { class: "assets-view coverage-view" },
      h("div", { class: "asset-toolbar" },
        icon("chart"), h("span", { class: "toolbar-title", text: "Coverage" }),
        this.search, this.filterSelect,
        h("button", {
          class: "btn small", type: "button", text: "Refresh",
          onclick: () => this.reload(),
        }, icon("refresh")),
        h("button", {
          class: "btn small", type: "button", text: "Copy report",
          onclick: () => this.copyReport(),
        }, icon("copy")),
        h("span", { class: "grow" }),
        this.countLabel,
      ),
      this.stats,
      this.tabView.el,
    );
  }

  async reload() {
    try {
      const data = await api.coverage();
      this.data = data;
      this.countLabel.textContent =
        `${data.totals.rooms} rooms · ${data.totals.objects} objects`;
      this.app.setStatus("Project coverage",
        `${data.totals.handled} handled · ${data.totals.unknown} placeholders · ` +
        `${data.totals.species_with_art}/${data.totals.species_with_records} species with art`);
      this.renderAll();
    } catch (error) {
      toast(`Could not load coverage: ${error.message}`, "error");
      clear(this.stats);
      this.stats.appendChild(h("div", { class: "inspector-empty", text: error.message }));
    }
  }

  renderAll() {
    if (!this.data) return;
    this.renderStats();
    this.tabView.select(this.tabView.active || "species");
  }

  /* --------------------------------------------------------------- stats */
  renderStats() {
    const totals = this.data.totals;
    clear(this.stats);
    const pct = totals.objects
      ? Math.round((100 * totals.unknown) / totals.objects) : 0;
    const card = (label, value, sub, filter) => h("button", {
      class: `stat-card${filter ? " link" : ""}` +
        `${filter && this.filter === filter ? " active" : ""}`,
      type: "button",
      onclick: filter ? () => {
        this.filter = this.filter === filter ? "all" : filter;
        this.filterSelect.value = this.filter;
        this.renderAll();
      } : undefined,
    },
    h("div", { class: "stat-value", text: String(value) }),
    h("div", { class: "stat-label", text: label }),
    h("div", { class: "stat-sub", text: sub }),
    );
    this.stats.append(
      card("Objects in rooms", totals.objects,
        `${totals.handled} handled · ${totals.unknown} placeholder`),
      card("Placeholders", totals.unknown, `${pct}% of every placed record`,
        "placeholder"),
      card("Species fully handled", `${totals.species_fully_handled}/${totals.species_with_records}`,
        `${totals.species_handled} have at least one handled record`),
      card("Species with art", `${totals.species_with_art}/${totals.species_with_records}`,
        `${totals.art_missing_records} records still have no sheet`, "no-art"),
      card("Rooms", totals.rooms,
        `${totals.authored_rooms} authored · ${totals.invalid_rooms} invalid`),
      card("Boss records", totals.boss_records,
        `${totals.transitions} doors · ${totals.spawns} spawns`),
    );
  }

  /* ------------------------------------------------------------- filters */
  filteredSpecies() {
    const rows = this.data?.species || [];
    return rows.filter((row) => {
      if (this.filter === "placeholder" && !row.unknown) return false;
      if (this.filter === "only-placeholder" && !row.placeholder_only) return false;
      if (this.filter === "no-art" && (row.has_art || row.records === 0)) return false;
      if (this.filter === "boss" && !row.boss) return false;
      if (this.filter === "authored" && !row.authored) return false;
      return matches(this.query, row.name, row.species_hex, row.species,
        (row.keys || []).join(" "), (row.rooms || []).join(" "));
    });
  }

  filteredRooms() {
    return (this.data?.rooms || []).filter((room) =>
      matches(this.query, room.area, room.name, room.label, room.music,
        room.effective_music, room.source));
  }

  /* ------------------------------------------------------------- species */
  renderSpecies() {
    if (!this.data) return h("div", { class: "inspector-empty", text: "Loading coverage…" });
    const rows = this.filteredSpecies();
    const body = h("div", { class: "coverage-table-wrap" });
    if (!rows.length) {
      body.appendChild(h("div", { class: "inspector-empty", text: "No species match." }));
      return body;
    }
    const tbody = h("tbody");
    const frag = document.createDocumentFragment();
    for (const row of rows) {
      const art = row.has_art
        ? h("span", { class: "badge green", text: `${row.art_frames}f` })
        : h("span", { class: "badge red", text: "none" });
      const unknown = row.unknown
        ? h("span", { class: "muted tiny", text: ` · ${row.unknown}?` })
        : null;
      const sheet = row.canonical_key
        ? h("span", { class: "mono tiny", text: row.canonical_key })
        : h("span", { class: "muted tiny", text: "—" });
      const tr = h("tr", {
        class: "clickable",
        title: row.canonical_key
          ? "Open this sheet in the Enemy Editor"
          : "No animation sheet yet — click for the rooms",
        onclick: () => this.openSpecies(row),
      },
      h("td", {}, h("span", { class: "mono", text: row.species_hex })),
      h("td", {},
        h("div", { class: "cell-title" },
          h("span", { text: row.name }),
          row.boss ? h("span", { class: "badge purple", text: "boss" }) : null),
        h("div", { class: "cell-sub", text: typeSummary(row.types) })),
      h("td", { class: "num" }, String(row.records), unknown),
      h("td", { class: "num" }, String(row.rooms.length)),
      h("td", {}, art),
      h("td", {}, sheet),
      );
      frag.appendChild(tr);
    }
    tbody.appendChild(frag);
    body.appendChild(h("table", { class: "data-table" },
      h("thead", {}, h("tr", {},
        h("th", { text: "Id" }), h("th", { text: "Species" }),
        h("th", { class: "num", text: "Records" }),
        h("th", { class: "num", text: "Rooms" }),
        h("th", { text: "Art" }), h("th", { text: "Sheet" }))),
      tbody));
    return body;
  }

  openSpecies(row) {
    if (row.canonical_key) {
      this.app.navigate(`#enemy/${encodeURIComponent(row.canonical_key)}`);
      return;
    }
    const body = h("div", { class: "field wide" },
      h("div", { class: "inspector-hint",
        text: `${row.name} (${row.species_hex}) has no animation sheet. ` +
          `It appears in ${row.rooms.length} room(s); creating a sheet in the ` +
          "Enemy Editor removes the magenta placeholder." }),
      h("div", { class: "room-chip-list" },
        ...row.rooms.map((area) => h("button", {
          class: "btn small", type: "button", text: `Area ${area}`,
          onclick: () => { dlg.close(null); this.app.navigate(`#map/${area}`); },
        }))),
    );
    const dlg = showModal({
      title: `${row.name} · ${row.species_hex}`,
      body, narrow: false,
      actions: [{ label: "Close", value: null }],
    });
  }

  /* --------------------------------------------------------------- rooms */
  renderRooms() {
    if (!this.data) return h("div", { class: "inspector-empty", text: "Loading coverage…" });
    const rows = this.filteredRooms();
    const body = h("div", { class: "coverage-table-wrap" });
    if (!rows.length) {
      body.appendChild(h("div", { class: "inspector-empty", text: "No rooms match." }));
      return body;
    }
    const tbody = h("tbody");
    const frag = document.createDocumentFragment();
    for (const room of rows) {
      const flag = room.unknown
        ? h("span", { class: "badge red", text: `${room.unknown}` })
        : h("span", { class: "muted tiny", text: "0" });
      frag.appendChild(h("tr", {
        class: "clickable",
        title: "Open this room in the Map Builder",
        onclick: () => this.app.navigate(`#map/${room.area}`),
      },
      h("td", { class: "mono" }, String(room.area)),
      h("td", {}, h("div", { class: "cell-title", text: room.label }),
        h("div", { class: "cell-sub", text: room.name })),
      h("td", { class: "num" }, String(room.objects)),
      h("td", { class: "num" }, flag),
      h("td", { class: "num" }, String(room.transitions)),
      h("td", {}, `${room.world.width}×${room.world.height}`),
      h("td", {}, this.app.meta?.music?.[room.effective_music]?.name ||
        `#${room.effective_music}`),
      h("td", {}, room.authored
        ? h("span", { class: "badge gold", text: "authored" })
        : h("span", { class: "muted tiny", text: "generated" })),
      h("td", {}, room.valid
        ? h("span", { class: "badge green", text: "ok" })
        : h("span", { class: "badge red", text: `${room.errors} err` })),
      ));
    }
    tbody.appendChild(frag);
    body.appendChild(h("table", { class: "data-table" },
      h("thead", {}, h("tr", {},
        h("th", { text: "Area" }), h("th", { text: "Room" }),
        h("th", { class: "num", text: "Objects" }),
        h("th", { class: "num", text: "?" }),
        h("th", { class: "num", text: "Doors" }),
        h("th", { text: "Size" }), h("th", { text: "Music" }),
        h("th", { text: "Source" }), h("th", { text: "State" }))),
      tbody));
    return body;
  }

  /* ---------------------------------------------------------------- gaps */
  renderGaps() {
    if (!this.data) return h("div", { class: "inspector-empty", text: "Loading coverage…" });
    const placed = (this.data.species || []).filter((row) => row.records > 0);
    const placeholders = placed.filter((row) => row.unknown > 0)
      .sort((a, b) => b.unknown - a.unknown);
    const noArt = placed.filter((row) => !row.has_art)
      .sort((a, b) => b.records - a.records);
    const body = h("div", { class: "gap-columns" });

    const list = (title, rows, renderRow) => {
      const wrap = h("div", { class: "gap-panel" },
        h("div", { class: "gap-head" }, h("span", { text: title }),
          h("span", { class: "badge", text: String(rows.length) })),
        h("div", { class: "gap-list" },
          ...rows.map(renderRow)),
      );
      return wrap;
    };

    body.append(
      list("Placeholder records", placeholders, (row) => h("button", {
        class: "gap-row", type: "button", onclick: () => this.openSpecies(row),
      },
      h("span", { class: "mono", text: row.species_hex }),
      h("span", { class: "gap-name", text: row.name }),
      h("span", { class: "badge red", text: `${row.unknown}` }),
      h("span", { class: "muted tiny", text: `${row.rooms.length} room(s)` }),
      )),
      list("Records without art", noArt, (row) => h("button", {
        class: "gap-row", type: "button", onclick: () => this.openSpecies(row),
      },
      h("span", { class: "mono", text: row.species_hex }),
      h("span", { class: "gap-name", text: row.name }),
      h("span", { class: "badge", text: `${row.records}` }),
      h("span", { class: "muted tiny", text: `${row.rooms.length} room(s)` }),
      )),
    );
    return body;
  }

  /* -------------------------------------------------------- collectibles */
  renderCollectibles() {
    const wrap = h("div", { class: "collectibles-panel" });
    const listWrap = h("div");
    wrap.appendChild(listWrap);

    let currentFilter = "all";

    const renderItems = (data) => {
      clear(listWrap);
      const items = (data.collectibles || []).filter((item) => {
        if (currentFilter !== "all" && item.category !== currentFilter) return false;
        if (this.query) {
          const hay = `${item.area} ${item.room_label} ${item.name} ${item.description} ${item.type}`.toLowerCase();
          if (!this.query.split(/\s+/).every((token) => hay.includes(token))) return false;
        }
        return true;
      });

      const summary = data.summary || {};
      const bar = h("div", { class: "row wrap", style: { gap: "8px", marginBottom: "12px" } },
        h("span", { class: "badge", text: `Total: ${summary.total || 0}` }),
        h("button", {
          class: `btn small ${currentFilter === "all" ? "primary" : ""}`,
          type: "button", text: "All",
          onclick: () => { currentFilter = "all"; renderItems(data); },
        }),
        h("button", {
          class: `btn small ${currentFilter === "crest" ? "primary" : ""}`,
          type: "button", text: `Crests (${summary.crest || 0})`,
          onclick: () => { currentFilter = "crest"; renderItems(data); },
        }),
        h("button", {
          class: `btn small ${currentFilter === "talisman" ? "primary" : ""}`,
          type: "button", text: `Talismans (${summary.talisman || 0})`,
          onclick: () => { currentFilter = "talisman"; renderItems(data); },
        }),
        h("button", {
          class: `btn small ${currentFilter === "urn" ? "primary" : ""}`,
          type: "button", text: `Urns (${summary.urn || 0})`,
          onclick: () => { currentFilter = "urn"; renderItems(data); },
        })
      );

      const table = h("table", { class: "coverage-table" },
        h("thead", null,
          h("tr", null,
            h("th", { text: "Area" }),
            h("th", { text: "Category" }),
            h("th", { text: "Name" }),
            h("th", { text: "Location (X, Y)" }),
            h("th", { text: "Flags" }),
            h("th", { text: "Description" }),
            h("th", { text: "Action" })
          )
        )
      );

      const tbody = h("tbody");
      for (const it of items) {
        const catBadgeClass = it.category === "crest" ? "badge yellow"
          : it.category === "talisman" ? "badge blue"
          : it.category === "urn" ? "badge" : "badge green";

        tbody.appendChild(h("tr", null,
          h("td", null, h("span", { class: "mono", text: `Area ${it.area}` })),
          h("td", null, h("span", { class: catBadgeClass, text: it.category })),
          h("td", null, h("strong", { text: it.name })),
          h("td", null, h("span", { class: "mono", text: `(${it.x}, ${it.y})` })),
          h("td", null, h("span", { class: "mono", text: String(it.flags) })),
          h("td", null, it.description),
          h("td", null, h("button", {
            class: "btn small",
            type: "button",
            text: "Edit room",
            onclick: () => this.app.navigate(`#map/${it.area}`),
          }))
        ));
      }
      table.appendChild(tbody);
      listWrap.append(bar, table);
    };

    if (this.collectiblesData) {
      renderItems(this.collectiblesData);
    } else {
      listWrap.textContent = "Loading collectibles…";
      api.collectibles()
        .then((data) => {
          this.collectiblesData = data;
          renderItems(data);
        })
        .catch((err) => {
          listWrap.textContent = `Error: ${err.message}`;
        });
    }

    return wrap;
  }

  /* -------------------------------------------------------------- report */
  copyReport() {
    if (!this.data) return;
    const totals = this.data.totals;
    const placed = (this.data.species || []).filter((row) => row.records > 0);
    const lines = [
      "# Demon's Crest — object coverage",
      "",
      `- rooms: ${totals.rooms} (${totals.authored_rooms} authored)`,
      `- objects: ${totals.objects} (${totals.handled} handled, ` +
        `${totals.unknown} placeholder)`,
      `- species: ${totals.species_with_records} placed, ` +
        `${totals.species_fully_handled} fully handled, ` +
        `${totals.species_with_art} with art`,
      "",
      "| id | species | records | unknown | rooms | art |",
      "|---|---|---|---|---|---|",
      ...placed.map((row) =>
        `| ${row.species_hex} | ${row.name} | ${row.records} | ${row.unknown} | ` +
        `${row.rooms.length} | ${row.has_art ? row.art_frames + "f" : "none"} |`),
    ];
    const text = lines.join("\n");
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text)
        .then(() => toast("Coverage report copied", "ok"))
        .catch(() => toast("Could not copy the report", "error"));
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      toast("Coverage report copied", "ok");
    }
  }
}
