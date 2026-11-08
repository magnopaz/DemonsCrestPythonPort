/* Check runner: the project's own gates (tools/check_*.py) with their output,
   exit status and timing.  The server runs one check at a time. */

import { api } from "./api.js";
import { h, clear } from "./util.js";
import { icon } from "./icons.js";
import { toast } from "./ui.js";

const STATUS_LABEL = {
  pass: "PASS", fail: "FAIL", warn: "WARN", timeout: "TIMEOUT", error: "ERROR",
};

export class ChecksView {
  constructor({ app, container, arg }) {
    this.app = app;
    this.container = container;
    this.arg = arg;
    this.data = null;
    this.checks = [];
    this.selected = null;
    this.results = {};
    this.running = null;
    this.query = "";
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
      type: "search", placeholder: "Filter checks…",
      oninput: () => { this.query = this.search.value.trim().toLowerCase(); this.renderList(); },
    });
    this.countLabel = h("span", { class: "asset-count", text: "Loading…" });
    this.displayNote = h("div", { class: "checks-note hidden" });
    this.list = h("div", { class: "checks-list" });
    this.console = h("pre", { class: "console", text: "Pick a check and press Run." });
    this.consoleTitle = h("span", { class: "console-title", text: "Output" });
    this.statusPill = h("span", { class: "badge", text: "idle" });
    this.metaLabel = h("span", { class: "muted mono tiny", text: "" });
    this.timeoutInput = h("input", {
      type: "number", value: 180, min: 10, max: 900, step: 10,
      style: { width: "76px" }, title: "Timeout in seconds",
    });
    this.runBtn = h("button", {
      class: "btn primary", type: "button",
      onclick: () => this.runSelected(),
    }, icon("play"), h("span", { text: "Run" }));
    this.copyBtn = h("button", {
      class: "btn small", type: "button", text: "Copy",
      onclick: () => this.copyOutput(),
    }, icon("copy"));
    this.runAllNote = h("span", { class: "field-note",
      text: "The full regression takes several minutes; every check runs in the project venv." });

    this.consoleHead = h("div", { class: "console-head" },
      this.consoleTitle,
      this.statusPill,
      this.metaLabel,
      h("span", { class: "grow" }),
      h("span", { class: "field-note", text: "timeout" }),
      this.timeoutInput, h("span", { class: "field-note", text: "s" }),
      this.copyBtn,
      this.runBtn,
    );
    this.consolePanel = h("div", { class: "console-panel" },
      this.consoleHead,
      this.console,
      h("div", { class: "console-foot" },
        h("span", { class: "mono tiny muted", text: "" },
          this.footerLabel = h("span", { class: "mono tiny muted" })),
        this.runAllNote,
      ),
    );

    this.el = h("div", { class: "assets-view checks-view" },
      h("div", { class: "asset-toolbar" },
        icon("clipboard"), h("span", { class: "toolbar-title", text: "Checks" }),
        this.search,
        h("button", {
          class: "btn small", type: "button", text: "Refresh",
          onclick: () => this.reload(),
        }, icon("refresh")),
        h("span", { class: "grow" }),
        this.countLabel,
      ),
      this.displayNote,
      h("div", { class: "checks-body" }, this.list, this.consolePanel),
    );
  }

  async reload() {
    try {
      const data = await api.checks();
      this.data = data;
      this.checks = data.checks || [];
      for (const check of this.checks) {
        if (check.last && !this.results[check.name]) this.results[check.name] = check.last;
      }
      this.countLabel.textContent = `${this.checks.length} gates`;
      this.renderDisplay();
      if (!this.selected && this.checks.length) {
        this.selected = this.checks[0].name;
      }
      this.renderList();
      this.renderConsole();
      this.app.setStatus("Checks",
        `${this.checks.length} project gates · ${data.display.available ? "display ready" : "no display"}`);
    } catch (error) {
      toast(`Could not list the checks: ${error.message}`, "error");
      clear(this.list);
      this.list.appendChild(h("div", { class: "inspector-empty", text: error.message }));
    }
  }

  renderDisplay() {
    const display = this.data?.display || {};
    if (display.available) {
      this.displayNote.classList.add("hidden");
      return;
    }
    this.displayNote.classList.remove("hidden");
    clear(this.displayNote);
    this.displayNote.append(
      icon("warning"),
      h("span", { text: "No X display.  Checks that boot the game will fail until " }),
      h("code", { text: display.xvfb_command || "Xvfb :99 …" }),
      h("span", { text: " runs (or start the editor from a desktop session)." }),
    );
  }

  visibleChecks() {
    const tokens = this.query.split(/\s+/).filter(Boolean);
    return this.checks.filter((check) => {
      if (!tokens.length) return true;
      const hay = `${check.name} ${check.label} ${check.description}`.toLowerCase();
      return tokens.every((token) => hay.includes(token));
    });
  }

  renderList() {
    clear(this.list);
    const rows = this.visibleChecks();
    const frag = document.createDocumentFragment();
    for (const check of rows) {
      const result = this.results[check.name];
      const status = result?.status;
      const pill = h("span", {
        class: `badge ${status === "pass" ? "green"
          : status === "fail" ? "red"
            : status === "timeout" ? "warn"
              : status === "warn" ? "warn" : ""}`,
        text: status ? STATUS_LABEL[status] || status : "—",
      });
      frag.appendChild(h("button", {
        class: `check-row${check.name === this.selected ? " active" : ""}`,
        type: "button",
        title: check.description,
        onclick: () => { this.selected = check.name; this.renderList(); this.renderConsole(); },
      },
      h("span", { class: "check-icon" }, icon(check.name === "regression" ? "layers" : "check")),
      h("span", { class: "check-meta" },
        h("span", { class: "check-name", text: check.name }),
        h("span", { class: "check-desc", text: check.description }),
      ),
      h("span", { class: "check-badges" },
        check.long ? h("span", { class: "badge warn", text: "long" }) : null,
        check.needs_display ? h("span", { class: "badge", text: "game" }) : null,
        pill,
      ),
      ));
    }
    if (!rows.length) {
      frag.appendChild(h("div", { class: "inspector-empty", text: "No checks match." }));
    }
    this.list.appendChild(frag);
  }

  renderConsole() {
    const check = this.checks.find((item) => item.name === this.selected);
    if (!check) return;
    const result = this.results[check.name];
    this.consoleTitle.textContent = check.name;
    this.metaLabel.textContent = result
      ? `${(result.duration_ms / 1000).toFixed(1)}s · exit ${result.exit_code}` : "";
    this.statusPill.className = `badge ${result?.status === "pass" ? "green"
      : result?.status === "fail" ? "red"
        : result?.status === "timeout" ? "warn" : ""}`;
    this.statusPill.textContent = result ? (STATUS_LABEL[result.status] || result.status) : "idle";
    this.footerLabel.textContent = result?.summary || "";
    const running = this.running === check.name;
    this.runBtn.disabled = !!this.running;
    this.runBtn.querySelector("span").textContent = running ? "Running…" : "Run";
    this.runAllNote.classList.toggle("hidden", !!this.running);
    if (running) {
      this.console.textContent = `$ ${check.file}\n\nrunning…  (this can take a minute)`;
      return;
    }
    if (!result) {
      this.console.textContent =
        `$ ${this.data.python} ${check.file}\n\n` +
        `${check.description}\n\n` +
        "Press Run.  The check runs headlessly and its stdout/stderr appears here.";
      return;
    }
    const parts = [];
    if (result.command) parts.push(`$ ${result.command}`, "");
    parts.push(result.stdout || "");
    if (result.stderr) parts.push("--- stderr ---", result.stderr);
    if (result.timed_out) parts.push("", `--- timeout after ${this.timeoutInput.value}s ---`);
    parts.push("", `exit ${result.exit_code} · ${(result.duration_ms / 1000).toFixed(1)}s`);
    this.console.textContent = parts.join("\n");
    this.console.scrollTop = 0;
  }

  async runSelected() {
    const check = this.checks.find((item) => item.name === this.selected);
    if (!check || this.running) return;
    const timeout = Math.max(10, Math.min(900, Number(this.timeoutInput.value) || 180));
    this.running = check.name;
    this.renderList();
    this.renderConsole();
    this.app.setSaveState("dirty", "Running");
    try {
      const result = await api.runCheck(check.name, timeout);
      if (!result.ok) {
        toast(result.error || "the check could not start", "error", 5000);
        return;
      }
      this.results[check.name] = result;
      if (result.status === "pass") toast(`${check.name}: PASS`, "ok");
      else if (result.status === "warn") toast(`${check.name}: finished with FAIL text`, "warn", 5000);
      else toast(`${check.name}: ${result.status.toUpperCase()}`, "error", 6000);
    } catch (error) {
      toast(`Check failed to run: ${error.message}`, "error", 6000);
    } finally {
      this.running = null;
      this.app.setSaveState("", "Idle");
      this.renderList();
      this.renderConsole();
    }
  }

  copyOutput() {
    const text = this.console.textContent || "";
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text)
        .then(() => toast("Output copied", "ok"))
        .catch(() => toast("Could not copy", "error"));
    }
  }
}
