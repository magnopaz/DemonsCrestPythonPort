/* Shared widgets: toasts, modals, species picker, audio preview, form rows. */

import { $, h, clear, loadImage } from "./util.js";
import { icon } from "./icons.js";

let toastLayer = null;
function toastRoot() {
  if (!toastLayer) toastLayer = $("#toasts");
  return toastLayer;
}

export function toast(message, kind = "", ms = 2800) {
  const el = h("div", { class: `toast ${kind}`.trim(), text: message });
  toastRoot().appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity .18s";
    setTimeout(() => el.remove(), 220);
  }, ms);
  return el;
}

/* ------------------------------------------------------------------ modal */
export function showModal({ title, body, actions = [], wide = false,
  narrow = false, onClose = null }) {
  const root = $("#modal-root");
  const backdrop = h("div", { class: "modal-backdrop" });
  const closeBtn = h("button", {
    class: "modal-close", type: "button", title: "Close (Esc)",
    onclick: () => close(null),
  }, "×");
  const modal = h("div", { class: `modal${wide ? " wide" : ""}${narrow ? " narrow" : ""}` },
    h("div", { class: "modal-header" }, h("h2", { text: title }), closeBtn),
    h("div", { class: "modal-body" }, body),
  );
  const actionBar = h("div", { class: "modal-actions" });
  let done = false;
  const close = (result) => {
    if (done) return;
    done = true;
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    if (onClose) onClose(result);
    modal.dispatchEvent(new CustomEvent("modal-close", { detail: result }));
    resolveFn(result);
  };
  let resolveFn = () => {};
  const promise = new Promise((resolve) => { resolveFn = resolve; });
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      event.preventDefault();
      close(null);
    }
  };
  document.addEventListener("keydown", onKey, true);
  backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) close(null);
  });
  for (const action of actions) {
    const btn = h("button", {
      class: `btn${action.primary ? " primary" : ""}${action.danger ? " danger" : ""}`,
      type: "button",
      text: action.label,
      disabled: action.disabled,
      onclick: async () => {
        if (action.onClick) {
          const keep = await action.onClick(close, modal);
          if (keep === false) return;
        }
        close(action.value ?? true);
      },
    });
    actionBar.appendChild(btn);
  }
  if (actions.length) modal.appendChild(actionBar);
  backdrop.appendChild(modal);
  root.appendChild(backdrop);
  const first = modal.querySelector("input, select, textarea, button");
  if (first) setTimeout(() => first.focus(), 20);
  return { close, promise, modal, body };
}

export function confirmDialog(title, message, { okLabel = "Continue",
  danger = false } = {}) {
  const body = h("div", { class: "inspector-hint", text: message });
  const dlg = showModal({
    title,
    body,
    narrow: true,
    actions: [
      { label: "Cancel", value: false },
      { label: okLabel, primary: !danger, danger, value: true },
    ],
  });
  return dlg.promise.then((v) => v === true);
}

export function promptDialog({ title, label = "", value = "", type = "text",
  note = "", okLabel = "OK" }) {
  const input = h("input", { type, value });
  const body = h("div", { class: "field wide" },
    h("span", { text: label }), input,
    note ? h("div", { class: "field-note", text: note }) : null);
  const dlg = showModal({
    title, body, narrow: true,
    actions: [
      { label: "Cancel", value: null },
      { label: okLabel, primary: true, value: "ok" },
    ],
  });
  const finish = (v) => v === "ok" ? input.value : null;
  dlg.modal.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      dlg.close("ok");
    }
  });
  return dlg.promise.then((v) => v === "ok" ? input.value : null);
}

/* --------------------------------------------------------------- species */
export function showSpeciesPicker(list, currentKey = null, {
  title = "Choose a species", filter = "all" } = {}) {
  let query = "";
  let mode = filter;
  const results = h("div", { class: "species-grid" });
  const search = h("input", {
    type: "search", placeholder: "Search by name, key or species id…",
    oninput: () => { query = search.value.trim().toLowerCase(); render(); },
  });
  const filterBar = h("div", { class: "row wrap" });
  const modes = [["all", "All"], ["enemy", "Enemies"], ["boss", "Bosses"],
    ["npc", "NPCs"]];
  let selected = currentKey;
  const modeButtons = modes.map(([value, label]) => h("button", {
    class: "btn small", type: "button", text: label,
    onclick: () => { mode = value; syncModes(); render(); },
  }));
  const syncModes = () => {
    modeButtons.forEach((btn, i) => btn.classList.toggle("active", modes[i][0] === mode));
  };
  const render = () => {
    clear(results);
    syncModes();
    const tokens = query.split(/\s+/).filter(Boolean);
    const filtered = list.filter((sp) => {
      if (mode !== "all" && sp.kind !== mode) return false;
      if (!tokens.length) return true;
      const hay = `${sp.name} ${sp.key} ${sp.species} ${sp.species_hex} ${sp.variant}`.toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
    if (!filtered.length) {
      results.appendChild(h("div", { class: "inspector-empty", text: "No species match." }));
      return;
    }
    for (const sp of filtered) {
      const thumbUrl = sp.thumb?.url;
      const img = thumbUrl
        ? h("img", { src: thumbUrl, alt: sp.name, draggable: "false" })
        : h("div", { class: "muted tiny", text: "no art" });
      const card = h("button", {
        class: `species-card${sp.key === selected ? " active" : ""}`,
        type: "button",
        title: `${sp.name}\nspecies ${sp.species_hex} · key ${sp.key}`,
        onclick: () => { selected = sp.key; render(); },
        ondblclick: () => dlg.close(sp),
      }, img, h("div", { class: "meta" },
        h("div", { class: "n", text: sp.name }),
        h("div", { class: "s", text: `${sp.species_hex} · ${sp.key} · ${sp.frames}f` }),
      ));
      results.appendChild(card);
    }
  };
  filterBar.append(...modeButtons);
  render();
  const body = h("div", { class: "field wide" },
    h("div", { class: "species-search" }, search),
    filterBar,
    results,
    h("div", { class: "field-note", text: "Double-click a card to choose it immediately." }),
  );
  const dlg = showModal({
    title, body, wide: true,
    actions: [
      { label: "Cancel", value: null },
      { label: "Use species", primary: true, value: "ok" },
    ],
  });
  return dlg.promise.then((v) => {
    if (v !== "ok") return null;
    return list.find((sp) => sp.key === selected) || null;
  });
}

/* ------------------------------------------------------------------ audio */
let audioEl = null;
let audioUrl = null;
export function audioState() {
  return { url: audioUrl, playing: !!audioEl && !audioEl.paused };
}
export function stopAudio() {
  if (audioEl) {
    audioEl.pause();
    audioEl.currentTime = 0;
    audioEl = null;
  }
  audioUrl = null;
}
export function playAudio(url, volume = 0.55) {
  if (!url) return false;
  if (audioUrl === url && audioEl && !audioEl.paused) {
    stopAudio();
    return false;
  }
  stopAudio();
  audioEl = new Audio(url);
  audioEl.volume = volume;
  audioEl.play().catch(() => {});
  audioEl.onended = () => { audioEl = null; audioUrl = null; };
  audioUrl = url;
  return true;
}

/* -------------------------------------------------------------- form rows */
export function field(label, control, note = null) {
  return h("div", { class: "field" },
    h("span", { text: label }),
    h("div", { class: "row" }, control,
      note ? h("span", { class: "field-note", text: note }) : null),
  );
}

export function numberField(label, value, onInput, { min = null, max = null,
  step = 1, width = "100%" } = {}) {
  const input = h("input", {
    type: "number", value: Number.isFinite(Number(value)) ? value : 0,
    min: min ?? undefined, max: max ?? undefined, step,
    style: { width },
    oninput: () => {
      let v = Number(input.value);
      if (!Number.isFinite(v)) return;
      if (min !== null) v = Math.max(min, v);
      if (max !== null) v = Math.min(max, v);
      onInput(v);
    },
  });
  return field(label, input);
}

export function selectField(label, options, value, onChange) {
  const select = h("select", {
    onchange: () => onChange(select.value),
  }, options.map((opt) => {
    const [val, text] = Array.isArray(opt) ? opt : [opt.value, opt.label];
    return h("option", { value: val, selected: String(val) === String(value), text });
  }));
  return field(label, select);
}

export function section(title, { open = true, actions = null } = {}) {
  const body = h("div", { class: "section-body" });
  const summary = h("summary", {}, h("span", { text: title }));
  if (actions) summary.appendChild(h("span", { class: "spacer" }));
  const el = h("details", { class: "section", open },
    summary, body);
  if (actions) {
    // The actions belong beside the summary, but a <details> summary cannot
    // contain interactive controls reliably; put them in the body header.
    body.prepend(h("div", { class: "section-actions" }, actions));
  }
  return { el, body, open: (v) => { el.open = v; } };
}

export function tabs(items) {
  const bar = h("div", { class: "tabs" });
  const body = h("div", { class: "tab-body" });
  const buttons = [];
  let active = items[0]?.id;
  const select = (id) => {
    active = id;
    for (const [btn, item] of buttons) {
      btn.classList.toggle("active", item.id === id);
    }
    clear(body);
    const item = items.find((it) => it.id === id);
    if (item) body.appendChild(item.render());
  };
  for (const item of items) {
    const btn = h("button", {
      class: "tab-btn", type: "button", text: item.label,
      onclick: () => select(item.id),
    });
    buttons.push([btn, item]);
    bar.appendChild(btn);
  }
  if (items.length) select(active);
  return { el: h("div", { class: "tabs-wrap" }, bar, body), select, body,
    get active() { return active; } };
}

export function issueList(validation, { max = 40 } = {}) {
  const wrap = h("div", { class: "issue-list" });
  if (!validation) {
    wrap.appendChild(h("div", { class: "issue", text: "Not validated yet." }));
    return wrap;
  }
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];
  if (!errors.length && !warnings.length) {
    wrap.appendChild(h("div", { class: "issue ok", text: "No problems found." }));
    return wrap;
  }
  for (const issue of errors.slice(0, max)) {
    wrap.appendChild(h("div", { class: "issue error" },
      h("div", { text: issue.message }),
      h("div", { class: "code", text: issue.code }),
    ));
  }
  for (const issue of warnings.slice(0, max)) {
    wrap.appendChild(h("div", { class: "issue warning" },
      h("div", { text: issue.message }),
      h("div", { class: "code", text: issue.code }),
    ));
  }
  const hidden = errors.length + warnings.length - Math.min(errors.length, max) -
    Math.min(warnings.length, max);
  if (hidden > 0) {
    wrap.appendChild(h("div", { class: "issue", text: `…and ${hidden} more` }));
  }
  return wrap;
}

export function speciesThumb(sp, size = 36) {
  if (sp?.thumb?.url) {
    const img = h("img", { src: sp.thumb.url, alt: sp.name, draggable: "false" });
    img.style.width = `${size}px`;
    img.style.height = `${size}px`;
    img.style.objectFit = "contain";
    img.style.imageRendering = "pixelated";
    return img;
  }
  return h("div", {
    class: "muted tiny",
    style: { width: `${size}px`, height: `${size}px`, display: "flex",
      alignItems: "center", justifyContent: "center", border: "1px dashed var(--line)",
      borderRadius: "3px" },
    text: "—",
  });
}

export async function imageOrNull(url) {
  if (!url) return null;
  return loadImage(url);
}
