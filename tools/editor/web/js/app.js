/* Application shell: boot, routing, shared data and status bar. */

import { api } from "./api.js";
import { $, h, clear } from "./util.js";
import { applyStaticIcons } from "./icons.js";
import { toast, showModal, confirmDialog } from "./ui.js";
import { MapEditor } from "./map.js";
import { EnemyEditor } from "./enemy.js";
import { PlayerEditor } from "./player.js";
import { AssetBrowser } from "./assets.js";
import { CoverageView } from "./coverage.js";
import { DialogueEditor } from "./dialogue.js";
import { ChecksView } from "./checks.js";
import { CampaignView } from "./campaign.js";

const VIEWS = {
  map: { label: "Map Builder", module: MapEditor },
  campaign: { label: "Campaign", module: CampaignView },
  enemy: { label: "Enemy Editor", module: EnemyEditor },
  player: { label: "Player Editor", module: PlayerEditor },
  dialogue: { label: "Dialogue", module: DialogueEditor },
  coverage: { label: "Coverage", module: CoverageView },
  checks: { label: "Checks", module: ChecksView },
  assets: { label: "Asset Browser", module: AssetBrowser },
};

export const app = {
  health: null,
  meta: null,
  rooms: [],
  species: [],
  current: null,
  currentName: null,
  _hashGuard: false,

  MapEditor,
  CampaignView,
  EnemyEditor,
  PlayerEditor,
  AssetBrowser,
  CoverageView,
  DialogueEditor,
  ChecksView,

  setStatus(left, right = "") {
    $("#status-left").textContent = left;
    $("#status-right").textContent = right;
  },

  setSaveState(state, text = "") {
    const el = $("#save-state");
    el.className = `save-state ${state}`;
    el.textContent = text || (state === "dirty" ? "Unsaved" :
      state === "saved" ? "Saved" : state === "error" ? "Error" : "Idle");
  },

  peakSpecies(key) {
    return this.species.find((s) => s.key === key) || null;
  },

  speciesFor(speciesId, flags = 0) {
    const all = this.species.filter((s) => s.species === Number(speciesId));
    if (!all.length) return null;
    if (flags) {
      const exact = all.find((s) => s.flags === flags && s.variant === "boss");
      if (exact) return exact;
    }
    return all.find((s) => s.variant !== "boss") || all[0];
  },

  navigate(hash, { replace = false } = {}) {
    if (replace) {
      history.replaceState(null, "", hash);
      return;
    }
    if (location.hash === hash) return;
    location.hash = hash;
  },

  async reloadRooms() {
    const data = await api.rooms();
    this.rooms = data.rooms || [];
    return this.rooms;
  },

  async reloadSpecies() {
    const data = await api.species();
    this.species = data.species || [];
    return this.species;
  },

  async rebootView() {
    const name = this.currentName;
    const hash = location.hash;
    await this.mount(name, hash, { force: true });
  },
};

function showLoading(container, message = "Loading workspace…") {
  clear(container);
  container.appendChild(h("div", {
    style: {
      height: "100%", display: "flex", alignItems: "center",
      justifyContent: "center", flexDirection: "column", gap: "12px",
      color: "var(--muted)", fontFamily: "var(--mono)", fontSize: "12px",
    },
  },
  h("div", {
    style: { width: "26px", height: "26px", border: "2px solid var(--line)",
      borderTopColor: "var(--accent)", borderRadius: "50%",
      animation: "spin 0.8s linear infinite" },
  }),
  h("div", { text: message })));
}

function showFatal(container, error) {
  clear(container);
  container.appendChild(h("div", {
    style: { padding: "60px 24px", maxWidth: "760px", margin: "0 auto",
      color: "var(--text-dim)", lineHeight: "1.6" },
  },
  h("h2", { style: { color: "var(--danger)" }, text: "The editor could not start" }),
  h("p", { text: error?.message || String(error) }),
  h("pre", {
    style: { whiteSpace: "pre-wrap", fontSize: "11px", color: "var(--muted)",
      background: "var(--panel)", padding: "12px", borderRadius: "4px",
      border: "1px solid var(--line)" },
    text: error?.stack || "",
  }),
  h("p", { class: "inspector-hint",
    text: "Start the server from the repository root with: python tools/editor/server.py" }),
  h("button", {
    class: "btn primary", type: "button", text: "Retry",
    onclick: () => location.reload(),
  })));
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [name, ...rest] = raw.split("/");
  return { name: VIEWS[name] ? name : "map", arg: rest.join("/") };
}

async function mount(name, arg, { force = false } = {}) {
  const container = $("#view");
  if (!VIEWS[name]) name = "map";
  if (app.current) {
    if (!force && app.current.isDirty?.()) {
      const key = app.current.dirtyPromptKey?.() || "";
      const ok = await confirmDialog("Discard unsaved changes?",
        "This editor has unsaved changes. Switching view will lose them.",
        { okLabel: "Discard changes", danger: true });
      if (!ok) {
        app._hashGuard = true;
        history.replaceState(null, "",
          `#${app.currentName}${app.currentRouteArg ? "/" + app.currentRouteArg : ""}`);
        return;
      }
    }
    try { app.current.destroy?.(); } catch (error) { console.error(error); }
    app.current = null;
  }
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  app.currentName = name;
  app.currentRouteArg = arg;
  app.setSaveState("", "Idle");
  showLoading(container);
  try {
    const cls = VIEWS[name].module;
    const view = new cls({ app, container, arg });
    await view.init();
    app.current = view;
    if (!arg && view.routeArg) {
      history.replaceState(null, "", `#${name}/${view.routeArg}`);
    }
  } catch (error) {
    console.error(error);
    showFatal(container, error);
    app.setSaveState("error", "Failed");
  }
}

function onHashChange() {
  if (app._hashGuard) {
    app._hashGuard = false;
    return;
  }
  const { name, arg } = parseHash();
  mount(name, arg);
}

async function boot() {
  window.__dcBooted = true;
  applyStaticIcons();
  const container = $("#view");
  showLoading(container, "Reading the project…");
  try {
    const [health, meta, rooms, species] = await Promise.all([
      api.health(), api.meta(), api.rooms(), api.species(),
    ]);
    app.health = health;
    app.meta = meta;
    app.rooms = rooms.rooms || [];
    app.species = species.species || [];
    $("#project-info").textContent =
      `${app.rooms.length} rooms · ${app.species.length} species`;
    app.setStatus("Ready. Pick a room to edit.",
      "Map · Enemy · Player · Dialogue · Coverage · Checks · Assets");
    const { name, arg } = parseHash();
    await mount(name, arg);
  } catch (error) {
    console.error(error);
    showFatal(container, error);
    app.setSaveState("error", "Failed");
  }
}

window.addEventListener("hashchange", onHashChange);
window.__dcApp = app;
window.addEventListener("beforeunload", (event) => {
  if (app.current?.isDirty?.()) {
    event.preventDefault();
    event.returnValue = "";
  }
});

document.querySelectorAll(".nav-tab").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const name = btn.dataset.view;
    const arg = name === app.currentName ? app.currentRouteArg : "";
    if (name === app.currentName) return;
    if (app.current?.isDirty?.()) {
      const ok = await confirmDialog("Discard unsaved changes?",
        "This editor has unsaved changes. Switching view will lose them.",
        { okLabel: "Discard changes", danger: true });
      if (!ok) return;
      app.current.destroy?.();
      app.current = null;
    }
    const target = `#${name}${arg ? "/" + arg : ""}`;
    if (location.hash === target) onHashChange();
    else location.hash = target;
  });
});

// A tiny style injection for the loading spinner (kept out of the main sheet
// because it is only used by the shell).
const style = document.createElement("style");
style.textContent = "@keyframes spin { to { transform: rotate(360deg); } }";
document.head.appendChild(style);

boot();
