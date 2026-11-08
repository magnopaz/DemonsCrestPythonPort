const NS = "http://www.w3.org/2000/svg";

const PATHS = {
  map: ["M1.5 4 6 2l4 2 4.5-2v10L10 14l-4-2-4.5 2z", "M6 2v10", "M10 4v10"],
  skull: ["M4.2 7.2a3.8 3.8 0 1 1 7.6 0v1.6l-1 .9V12H5.2v-2.3l-1-.9z",
          "M6 7.2h.01", "M10 7.2h.01", "M6.5 10.2v1.4", "M8 10.2v1.4", "M9.5 10.2v1.4"],
  player: ["M8 2.4a2.1 2.1 0 1 1 0 4.2 2.1 2.1 0 0 1 0-4.2z",
           "M8 6.8v3.6", "M4.8 13.8 8 10.6l3.2 3.2",
           "M4.2 5.2 1.6 3.2v4.2", "M11.8 5.2 14.4 3.2v4.2"],
  image: ["M2.5 3.5h11v9h-11z", "M2.5 12.5 6.5 8l2.5 2.5 2-2 2.5 2.5", "M5.6 6.2a.9.9 0 1 0 0-.01"],
  save: ["M3 2.5h8l2.5 2.5v8.5h-11z", "M5 2.5v3.5h6V2.5", "M4.8 10.5h6.4v3H4.8z"],
  undo: ["M6 4 2.5 7.5 6 11", "M2.5 7.5H9a3.8 3.8 0 0 1 0 7.6H7"],
  redo: ["M10 4l3.5 3.5L10 11", "M13.5 7.5H7a3.8 3.8 0 0 0 0 7.6h2"],
  plus: ["M8 3v10", "M3 8h10"],
  trash: ["M3 4.5h10", "M6 2.5h4l.6 2H5.4z", "M4.5 4.5l.6 9h5.8l.6-9", "M6.8 7v4.5", "M9.2 7v4.5"],
  cursor: ["M4 2l8 6-3.7.6L10.5 13l-1.7.9-2.2-4.4L4 12.2z"],
  grid: ["M2.5 2.5h11v11h-11z", "M2.5 6.2h11", "M2.5 9.8h11", "M6.2 2.5v11", "M9.8 2.5v11"],
  tile: ["M2.5 2.5h5v5h-5z", "M8.5 2.5h5v5h-5z", "M2.5 8.5h5v5h-5z", "M8.5 8.5h5v5h-5z"],
  collision: ["M2.5 2.5h11v11h-11z", "M2.5 9.5c2-2 4 2 6 0s3-1 5 0", "M2.5 12.5h11"],
  door: ["M3.5 2.5h9v11h-9z", "M10 2.5v11", "M9 8h.01"],
  spawn: ["M8 2v3", "M8 11v3", "M2 8h3", "M11 8h3", "M8 5.5A2.5 2.5 0 1 1 8 10.5 2.5 2.5 0 0 1 8 5.5z"],
  zoomIn: ["M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9z", "M10.5 10.5l3 3", "M7 5v4", "M5 7h4"],
  zoomOut: ["M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9z", "M10.5 10.5l3 3", "M5 7h4"],
  fit: ["M2.5 6V2.5H6", "M10 2.5h3.5V6", "M13.5 10v3.5H10", "M6 13.5H2.5V10"],
  eye: ["M1.5 8s2.4-4 6.5-4 6.5 4 6.5 4-2.4 4-6.5 4S1.5 8 1.5 8z", "M8 6.2a1.8 1.8 0 1 1 0 3.6 1.8 1.8 0 0 1 0-3.6z"],
  play: ["M5 3l7 5-7 5z"],
  pause: ["M5.5 3.5v9", "M10.5 3.5v9"],
  stop: ["M4 4h8v8H4z"],
  download: ["M8 2.5v8", "M5 8l3 3 3-3", "M3 13.5h10"],
  upload: ["M8 11V3", "M5 6l3-3 3 3", "M3 13.5h10"],
  search: ["M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9z", "M10.5 10.5l3 3"],
  copy: ["M5.5 5.5h8v8h-8z", "M2.5 10.5v-8h8"],
  refresh: ["M13 8a5 5 0 1 1-1.5-3.6", "M13 2.5V6h-3.5"],
  gear: ["M8 5.7a2.3 2.3 0 1 1 0 4.6 2.3 2.3 0 0 1 0-4.6z",
         "M8 1.5v2", "M8 12.5v2", "M1.5 8h2", "M12.5 8h2", "M3.4 3.4l1.4 1.4", "M11.2 11.2l1.4 1.4", "M12.6 3.4l-1.4 1.4", "M4.8 11.2l-1.4 1.4"],
  warning: ["M8 2.5 14 13H2z", "M8 6v3.5", "M8 11.2h.01"],
  check: ["M3 8.5l3.2 3L13 4.5"],
  close: ["M3.5 3.5l9 9", "M12.5 3.5l-9 9"],
  link: ["M6.5 9.5l3-3", "M5.5 11.5l-1 1a2.8 2.8 0 0 1-4-4l2-2a2.8 2.8 0 0 1 4 0", "M10.5 4.5l1-1a2.8 2.8 0 0 1 4 4l-2 2a2.8 2.8 0 0 1-4 0"],
  layers: ["M8 2 14 5 8 8 2 5z", "M2 8l6 3 6-3", "M2 11l6 3 6-3"],
  palette: ["M8 2a6 6 0 1 0 0 12c1.2 0 1.5-.8 1.2-1.6-.3-.9 0-1.4.9-1.4H11a3 3 0 0 0 3-3A6 6 0 0 0 8 2z", "M5 6h.01", "M8 4.8h.01", "M11 6h.01"],
  spark: ["M8 1.5l1.3 4.2L13.5 7l-4.2 1.3L8 12.5l-1.3-4.2L2.5 7l4.2-1.3z"],
  arrowRight: ["M2.5 8h11", "M9.5 4l4 4-4 4"],
  folder: ["M2 4h4l1.2 1.5H14v7.5H2z"],
  target: ["M8 2.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11z", "M8 5.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"],
  move: ["M8 2v12", "M2 8h12", "M5.5 4.5 8 2l2.5 2.5", "M5.5 11.5 8 14l2.5-2.5", "M4.5 5.5 2 8l2.5 2.5", "M11.5 5.5 14 8l-2.5 2.5"],
  info: ["M8 2.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11z", "M8 7v4", "M8 4.8h.01"],
  music: ["M6 12V4l7-1.5v8", "M4 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M11 12.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"],
  book: ["M2.5 3.5c1.8-.9 3.8-.9 5.5 0v9c-1.7-.9-3.7-.9-5.5 0z",
         "M13.5 3.5c-1.8-.9-3.8-.9-5.5 0v9c1.7-.9 3.7-.9 5.5 0z",
         "M8 3.5v9"],
  chart: ["M2.5 13.5h11", "M4.2 11.2V7.6", "M8 11.2V4.2", "M11.8 11.2V6.2"],
  clipboard: ["M5.5 3.2h5v1.6h-5z", "M4 4.2h8v9.3H4z", "M6.4 7.8h3.2",
              "M6.4 10.2h3.2"],
  compass: ["M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z", "M10.8 5.2l-2.1 4.3-3.5 1.3 2.1-4.3z"],
  gem: ["M4.5 2.5h7l2.5 4-6 7-6-7z", "M2 6.5h12", "M6 2.5l2 4 2-4"],
  minimap: ["M2.5 2.5h11v11h-11z", "M7.5 7.5h4.5v4.5H7.5z"],
};

export function icon(name, size = 16) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.45");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const paths = PATHS[name] || PATHS.info;
  for (const d of paths) {
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  return svg;
}

export function applyStaticIcons(root = document) {
  for (const node of root.querySelectorAll("[data-icon]")) {
    if (node.dataset.iconDone) continue;
    node.dataset.iconDone = "1";
    node.appendChild(icon(node.dataset.icon));
  }
}
