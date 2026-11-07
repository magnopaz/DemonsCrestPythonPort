/* Small DOM, geometry and sprite helpers shared by every editor. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key === "html") el.innerHTML = value;
      else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
      else if (key === "dataset") Object.assign(el.dataset, value);
      else if (key.startsWith("on") && typeof value === "function") {
        el.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "value" || key === "checked" || key === "selected") {
        el[key] = value;
      } else if (value === true) {
        el.setAttribute(key, "");
      } else {
        el.setAttribute(key, String(value));
      }
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function frag(...children) {
  const f = document.createDocumentFragment();
  append(f, children);
  return f;
}

export function on(el, type, fn, opts) {
  el.addEventListener(type, fn, opts);
  return () => el.removeEventListener(type, fn, opts);
}

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const snap = (v, step) => Math.round(v / step) * step;
export const lerp = (a, b, t) => a + (b - a) * t;

export function fmod(a, b) {
  return ((a % b) + b) % b;
}

export function debounce(fn, delay = 120) {
  let timer = 0;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

export function throttle(fn, delay = 50) {
  let last = 0;
  let timer = 0;
  return (...args) => {
    const now = performance.now();
    const left = delay - (now - last);
    if (left <= 0) {
      clearTimeout(timer);
      last = now;
      fn(...args);
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = 0;
        last = performance.now();
        fn(...args);
      }, left);
    }
  };
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function formatBytes(n) {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatNumber(n, digits = 1) {
  if (!Number.isFinite(n)) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

export function padHex(n, width = 2) {
  return Number(n).toString(16).toUpperCase().padStart(width, "0");
}

export function speciesHex(id) {
  return `0x${padHex(id, 2)}`;
}

/* ------------------------------------------------------------------ images */
const imageCache = new Map();
const resolvedImages = new Map();

export function loadImage(url) {
  if (!url) return Promise.resolve(null);
  if (imageCache.has(url)) return imageCache.get(url);
  const promise = new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      resolvedImages.set(url, img);
      resolve(img);
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
  imageCache.set(url, promise);
  return promise;
}

export function getImage(url) {
  if (!url) return null;
  if (resolvedImages.has(url)) return resolvedImages.get(url);
  loadImage(url);
  return null;
}

export function preload(urls) {
  return Promise.all([...new Set(urls.filter(Boolean))].map(loadImage));
}

/* --------------------------------------------------------------- tile math */
export function decodeTile(word) {
  const w = Number(word) || 0;
  const tile = w & 0x3ff;
  const pal = (w >> 10) & 7;
  return {
    word: w,
    tile,
    pal,
    flipH: !!(w & 0x4000),
    flipV: !!(w & 0x8000),
    srcX: (w & 0x4000 ? 256 : 0) + (tile % 32) * 8,
    srcY: (w & 0x8000 ? 256 : 0) + Math.floor(tile / 32) * 8,
  };
}

export function encodeTile(tile, pal, flipH = false, flipV = false) {
  return (tile & 0x3ff) | ((pal & 7) << 10) |
    (flipH ? 0x4000 : 0) | (flipV ? 0x8000 : 0);
}

export function surfaceOffset(attr, localX) {
  const shape = attr & 0x1f;
  const x = localX & 15;
  switch (shape) {
    case 0x01: case 0x15: case 0x16: case 0x18: case 0x19: case 0x1a: case 0x1b: return 0;
    case 0x02: case 0x17: return 8;
    case 0x03: return ((15 - x) >> 1) + 8;
    case 0x04: return (15 - x) >> 1;
    case 0x05: return x >> 1;
    case 0x06: return (x >> 1) + 8;
    case 0x07: return ((15 - x) >> 2) + 12;
    case 0x08: return ((15 - x) >> 2) + 8;
    case 0x09: return ((15 - x) >> 2) + 4;
    case 0x0a: return (15 - x) >> 2;
    case 0x0b: return x >> 2;
    case 0x0c: return (x >> 2) + 4;
    case 0x0d: return (x >> 2) + 8;
    case 0x0e: return (x >> 2) + 12;
    case 0x0f: return 15 - x;
    case 0x10: return x;
    case 0x11: return x >> 1;
    case 0x12: return (x >> 1) + 8;
    case 0x13: return (15 - x) >> 1;
    case 0x14: return ((15 - x) >> 1) + 8;
    default: return -1;
  }
}

export function floorAt(collision, worldX, feetY) {
  const cell = collision.cell || 16;
  const cx = Math.floor(worldX / cell);
  const cy = Math.floor(feetY / cell);
  if (cx < 0 || cy < 0 || cx >= collision.width || cy >= collision.height) return null;
  const attr = collision.attrs[cy * collision.width + cx] || 0;
  const off = surfaceOffset(attr, Math.floor(worldX) & (cell - 1));
  return off < 0 ? null : cy * cell + off;
}

/* ------------------------------------------------------------------ canvas */
export function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(rect.width * dpr));
  const h = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  return { width: canvas.width, height: canvas.height, dpr };
}

export function drawChecker(ctx, x, y, w, h, size = 8, a = "#12141b", b = "#0c0e13") {
  for (let yy = 0; yy < h; yy += size) {
    for (let xx = 0; xx < w; xx += size) {
      ctx.fillStyle = ((xx / size + yy / size) & 1) ? a : b;
      ctx.fillRect(x + xx, y + yy, size, size);
    }
  }
}

/* ---------------------------------------------------------------- files */
export function downloadBlob(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export function downloadCanvas(name, canvas) {
  canvas.toBlob((blob) => {
    if (blob) downloadBlob(name, blob);
  }, "image/png");
}

export function readFileDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

export function deepClone(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

export function uid(prefix = "u") {
  return `${prefix}${Math.random().toString(36).slice(2, 9)}`;
}

export function csvOf(values) {
  return values.join(", ");
}

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}
