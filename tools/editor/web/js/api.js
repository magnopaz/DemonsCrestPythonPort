/* Thin JSON client for the local editor server. */

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = new Error(payload?.error || `${response.status} ${response.statusText}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const api = {
  health: () => request("/api/health"),
  meta: () => request("/api/meta"),
  rooms: () => request("/api/rooms"),
  room: (area) => request(`/api/rooms/${area}`),
  player: () => request("/api/player"),
  playerEntry: (target) => request(`/api/player/${target}`),
  savePlayer: (target, entry) => request(`/api/player/${target}`, {
    method: "POST", body: JSON.stringify({ entry }),
  }),
  deletePlayer: (target) => request(`/api/player/${target}`, { method: "DELETE" }),
  validatePlayer: (target, entry) => request("/api/player/validate", {
    method: "POST", body: JSON.stringify({ target, entry }),
  }),
  roomAssets: (area, atlas) => request(
    `/api/rooms/${area}/assets${atlas === undefined ? "" : `?atlas=${atlas}`}`),
  originalRoom: (area) => request(`/api/rooms/${area}/original`),
  newRoom: (body) => request("/api/rooms/new", {
    method: "POST", body: JSON.stringify(body),
  }),
  saveRoom: (area, room, target = "authored") => request(`/api/rooms/${area}`, {
    method: "POST", body: JSON.stringify({ room, target }),
  }),
  revertRoom: (area) => request(`/api/rooms/${area}`, { method: "DELETE" }),
  resizeRoom: (area, room, width, height, resizeBg0 = false,
    resizeCollision = true) => request(`/api/rooms/${area}/resize`, {
    method: "POST",
    body: JSON.stringify({ room, width, height, resize_bg0: resizeBg0,
      resize_collision: resizeCollision }),
  }),
  validateRoom: (area, room) => request(`/api/rooms/${area}/validate`, {
    method: "POST", body: JSON.stringify({ room }),
  }),
  renderRoom: (area, room, frames = 90) => request(
    `/api/rooms/${area}/render`, {
      method: "POST", body: JSON.stringify({ room, frames }),
    }),
  species: () => request("/api/species"),
  speciesDetail: (key) => request(`/api/species/${encodeURIComponent(key)}`),
  saveSpecies: (key, entry, definition, target = "authored") => request(
    `/api/species/${encodeURIComponent(key)}`, {
      method: "POST",
      body: JSON.stringify({ entry, definition, target }),
    }),
  deleteSpecies: (key) => request(`/api/species/${encodeURIComponent(key)}`, {
    method: "DELETE",
  }),
  assets: () => request("/api/assets"),
  coverage: () => request("/api/coverage"),
  campaign: () => request("/api/campaign"),
  search: (q, limit = 100) => request(
    `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  collectibles: () => request("/api/collectibles"),
  text: () => request("/api/text"),
  textBlock: (index) => request(`/api/text/${index}`),
  saveText: (index, pages) => request(`/api/text/${index}`, {
    method: "POST", body: JSON.stringify({ pages }),
  }),
  deleteText: (index) => request(`/api/text/${index}`, { method: "DELETE" }),
  checks: () => request("/api/checks"),
  runCheck: (name, timeout = 180) => request("/api/checks/run", {
    method: "POST", body: JSON.stringify({ name, timeout }),
  }),
  upload: (name, data, overwrite = false) => request("/api/assets/upload", {
    method: "POST", body: JSON.stringify({ name, data, overwrite }),
  }),
};
