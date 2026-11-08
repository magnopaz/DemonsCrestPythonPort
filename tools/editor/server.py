#!/usr/bin/env python3
"""Local web server for the Demon's Crest visual editor suite.

Run it from the repository root (or anywhere):

    python tools/editor/server.py

It serves the editor UI and a small JSON API over the project's own asset and
room files.  No third-party dependency, no build step, no CDN: the browser loads
the PNG/WAV files straight out of ``assets/``.

The server binds to localhost by default.  Saving never overwrites the
ROM-derived files unless you explicitly ask for the "generated" target; the
default is the ``assets/authored`` overlay that the game already prefers.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import editor_data  # noqa: E402

MAX_BODY = 32 * 1024 * 1024


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, workspace: editor_data.Workspace):
        super().__init__(address, EditorHandler)
        self.workspace = workspace
        self.render_lock = threading.Lock()

    def handle_error(self, request, client_address):
        # Browsers close image/audio sockets constantly while the user pans or
        # switches rooms; those resets are not server errors.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class EditorHandler(BaseHTTPRequestHandler):
    server_version = "DC-Editor/1.0"
    protocol_version = "HTTP/1.1"

    # -- helpers ----------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter, one line per request
        if self.path.startswith("/api/") or self.command not in ("GET", "HEAD"):
            sys.stderr.write("%s %s\n" % (self.command, self.path))

    def send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error_json(self, status: int, message: str, **extra) -> None:
        payload = {"ok": False, "error": message}
        payload.update(extra)
        self.send_json(status, payload)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def serve_file(self, path: Path, cache: bool = True) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error_json(404, f"file not found: {path.name}")
            return
        ctype = mimetypes.guess_type(path.name)[0] or \
            "application/octet-stream"
        if ctype.startswith("text/") or ctype in (
                "application/javascript", "application/json"):
            if "charset" not in ctype:
                ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control",
                         "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # -- routing ----------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            if path in ("/", "/index.html"):
                self.serve_file(HERE / "web" / "index.html", cache=False)
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path.startswith("/web/"):
                # The UI is a local development tool; never let the browser
                # serve a stale module after an edit.
                self.serve_static(HERE / "web", path[len("/web/"):],
                                  cache=False)
                return
            if path.startswith("/assets/"):
                self.serve_static(self.server.workspace.root / "assets",
                                  path[len("/assets/"):])
                return
            if path.startswith("/captures/"):
                self.serve_static(self.server.workspace.root / "captures",
                                  path[len("/captures/"):])
                return
            if path == "/api/health":
                self.send_json(200, {"ok": True,
                                     **self.server.workspace.info()})
                return
            if path == "/api/meta":
                self.send_json(200, {"ok": True,
                                     **self.server.workspace.meta()})
                return
            if path == "/api/rooms":
                rooms = self.server.workspace.list_rooms()
                self.send_json(200, {"ok": True, "rooms": rooms})
                return
            if path == "/api/rooms/new":
                self.handle_new_room()
                return
            if path.startswith("/api/rooms/"):
                self.handle_room_get(path)
                return
            if path == "/api/player":
                self.send_json(200, {
                    "ok": True,
                    **self.server.workspace.list_player(),
                })
                return
            if path.startswith("/api/player/"):
                target = urllib.parse.unquote(path[len("/api/player/"):])
                if self.server.workspace.player_target(target) is None:
                    self.send_error_json(404, f"unknown player target {target!r}")
                    return
                detail = self.server.workspace.load_player(target)
                if detail is None:
                    self.send_error_json(404, f"unknown player target {target!r}")
                    return
                self.send_json(200, detail)
                return
            if path == "/api/species":
                self.send_json(200, {
                    "ok": True,
                    "species": self.server.workspace.list_species(),
                })
                return
            if path.startswith("/api/species/"):
                key = urllib.parse.unquote(path[len("/api/species/"):])
                detail = self.server.workspace.load_species(key)
                if detail is None:
                    self.send_error_json(404, f"unknown species key {key!r}")
                    return
                self.send_json(200, {"ok": True, **detail})
                return
            if path == "/api/assets":
                images = self.server.workspace.list_images()
                self.send_json(200, {"ok": True, "images": images})
                return
            if path == "/api/coverage":
                self.send_json(200, {"ok": True,
                                     **self.server.workspace.coverage()})
                return
            if path == "/api/campaign":
                self.send_json(200, self.server.workspace.campaign_graph())
                return
            if path == "/api/collectibles":
                self.send_json(200, self.server.workspace.collectibles())
                return
            if path == "/api/text":
                self.send_json(200, {"ok": True,
                                     **self.server.workspace.text_index()})
                return
            if path.startswith("/api/text/"):
                index = self._parse_index(path, "/api/text/")
                detail = self.server.workspace.load_text(index)
                if detail is None:
                    self.send_error_json(404, f"no text block {index}")
                    return
                self.send_json(200, {"ok": True, **detail})
                return
            if path == "/api/checks":
                self.send_json(200, {"ok": True,
                                     **self.server.workspace.list_checks()})
                return
            self.send_error_json(404, f"no route for {path}")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_error_json(500, str(exc))

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            body = self.read_json()
            if path == "/api/rooms/new":
                self.handle_new_room(body)
                return
            if path.startswith("/api/rooms/"):
                self.handle_room_post(path, body)
                return
            if path == "/api/player/validate":
                target = str(body.get("target") or "base")
                result = self.server.workspace.validate_player(
                    target, body.get("entry") or {})
                self.send_json(200, {"ok": True, **result})
                return
            if path.startswith("/api/player/"):
                target = urllib.parse.unquote(path[len("/api/player/"):])
                self.handle_player_post(target, body)
                return
            if path.startswith("/api/species/"):
                key = urllib.parse.unquote(path[len("/api/species/"):])
                self.handle_species_post(key, body)
                return
            if path == "/api/assets/upload":
                result = self.server.workspace.save_upload(
                    str(body.get("name") or "image.png"),
                    str(body.get("data") or ""),
                    bool(body.get("overwrite")))
                self.send_json(200 if result.get("ok") else 400, result)
                return
            if path.startswith("/api/text/"):
                index = self._parse_index(path, "/api/text/")
                result = self.server.workspace.save_text(index,
                                                         body.get("pages"))
                self.send_json(200 if result.get("ok") else 400, result)
                return
            if path == "/api/checks/run":
                result = self.server.workspace.run_check(
                    str(body.get("name") or ""),
                    editor_data.clamp_int(body.get("timeout"), 180, 10, 900))
                self.send_json(200 if result.get("ok") else 400, result)
                return
            if path == "/api/_selftest":
                results = body.get("results")
                if not isinstance(results, list):
                    raise ValueError("results must be a list")
                out = self.server.workspace.root / "captures" / "editor_selftest.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps({"generated": time.strftime(
                    "%Y-%m-%dT%H:%M:%S"), "results": results}, indent=1),
                    encoding="utf-8")
                self.send_json(200, {"ok": True, "path": str(out)})
                return
            if path == "/api/validate/room":
                room = body.get("room")
                area = body.get("area")
                result = self.server.workspace.validate_room(room, area)
                self.send_json(200, {"ok": True, **result})
                return
            if path == "/api/validate/species":
                key = str(body.get("key") or "")
                entry = body.get("entry") or {}
                definition = body.get("definition") or {}
                ws = self.server.workspace
                result = ws.validate_species(key, entry, definition,
                                             ws._species_entries())
                self.send_json(200, {"ok": True, **result})
                return
            self.send_error_json(404, f"no route for {path}")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_error_json(500, str(exc))

    def do_DELETE(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            ws = self.server.workspace
            if path.startswith("/api/rooms/"):
                area = self._parse_area(path, ws)
                result = ws.revert_room(area)
                self.send_json(200 if result.get("ok") else 404, result)
                return
            if path.startswith("/api/player/"):
                target = urllib.parse.unquote(path[len("/api/player/"):])
                result = ws.delete_player(target)
                self.send_json(200 if result.get("ok") else 404, result)
                return
            if path.startswith("/api/species/"):
                key = path[len("/api/species/"):]
                result = ws.delete_species(key)
                self.send_json(200 if result.get("ok") else 404, result)
                return
            if path.startswith("/api/text/"):
                index = self._parse_index(path, "/api/text/")
                result = ws.delete_text(index)
                self.send_json(200 if result.get("ok") else 404, result)
                return
            self.send_error_json(404, f"no route for {path}")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_error_json(500, str(exc))

    # -- handlers ---------------------------------------------------------
    def serve_static(self, base: Path, relative: str,
                     cache: bool = True) -> None:
        base = base.resolve()
        target = (base / relative).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            self.send_error_json(403, "path escapes the asset tree")
            return
        if not target.is_file():
            self.send_error_json(404, f"file not found: {relative}")
            return
        self.serve_file(target,
                        cache=cache and not relative.endswith(".json"))

    def handle_room_get(self, path: str) -> None:
        ws = self.server.workspace
        rest = path[len("/api/rooms/"):].strip("/")
        parts = rest.split("/")
        area = self._parse_area(path, ws)
        if len(parts) == 1:
            loaded = ws.load_room(area)
            if loaded is None:
                self.send_error_json(404, f"no room for area {area}")
                return
            room = loaded["room"]
            self.send_json(200, {
                "ok": True,
                "area": area,
                "label": ws.room_label(area),
                "source": loaded["source"],
                "authored": loaded["authored"],
                "generated": loaded["generated"],
                "room": room,
                "assets": ws.room_assets(area, room),
                "effective_music": editor_data.clamp_room_music(room)
                if editor_data.clamp_room_music(room) is not None
                else editor_data.default_music_for_area(area),
                "validation": ws.validate_room(room, area),
            })
            return
        if len(parts) == 2 and parts[1] == "validate":
            loaded = ws.load_room(area)
            if loaded is None:
                self.send_error_json(404, f"no room for area {area}")
                return
            self.send_json(200, {"ok": True,
                                 **ws.validate_room(loaded["room"], area)})
            return
        if len(parts) == 2 and parts[1] == "assets":
            loaded = ws.load_room(area)
            room = loaded["room"] if loaded else {}
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            atlas = query.get("atlas", [None])[0]
            if atlas is not None:
                try:
                    room = dict(room)
                    room["bg_atlas_area"] = int(atlas)
                except ValueError:
                    raise ValueError("atlas must be an integer area id") from None
            self.send_json(200, {"ok": True,
                                 "assets": ws.room_assets(area, room)})
            return
        if len(parts) == 2 and parts[1] == "original":
            path = ws.assets / f"room_area{area}.json"
            room = ws._read_json_cached(path)
            if room is None:
                self.send_error_json(404, f"no generated room for area {area}")
                return
            self.send_json(200, {"ok": True, "area": area,
                                 "room": room})
            return
        self.send_error_json(404, f"no route for {path}")

    def handle_room_post(self, path: str, body: dict) -> None:
        ws = self.server.workspace
        rest = path[len("/api/rooms/"):].strip("/")
        parts = rest.split("/")
        area = self._parse_area(path, ws)
        if len(parts) == 2 and parts[1] == "validate":
            room = body.get("room") or {}
            self.send_json(200, {"ok": True,
                                 **ws.validate_room(room, area)})
            return
        if len(parts) == 2 and parts[1] == "resize":
            room = body.get("room") or {}
            out = ws.resize_room(room, int(body.get("width") or 0),
                                 int(body.get("height") or 0),
                                 bool(body.get("resize_bg0")),
                                 bool(body.get("resize_collision", True)))
            self.send_json(200, {"ok": True, "room": out,
                                 "validation": ws.validate_room(out, area)})
            return
        if len(parts) == 2 and parts[1] == "render":
            self.handle_render_room(area, body)
            return
        if len(parts) == 1:
            room = body.get("room")
            if not isinstance(room, dict):
                raise ValueError("body.room must be an object")
            room["area_id"] = area
            result = ws.save_room(area, room,
                                  target=str(body.get("target") or "authored"))
            self.send_json(200 if result.get("ok") else 422, result)
            return
        self.send_error_json(404, f"no route for {path}")

    def handle_new_room(self, body: dict | None = None) -> None:
        body = body or self.read_json()
        ws = self.server.workspace
        area = editor_data.clamp_int(body.get("area"), 200, 0, 4095)
        width = editor_data.clamp_int(body.get("width"), 512, 256, 4096)
        height = editor_data.clamp_int(body.get("height"), 256, 224, 4096)
        name = str(body.get("name") or f"area{area}")
        atlas = body.get("atlas_area")
        atlas_area = editor_data.clamp_int(atlas, area, 0, 4095) \
            if atlas is not None else area
        room = ws.blank_room(area, width, height, name, atlas_area)
        template = str(body.get("template") or "blank")
        if template == "floor":
            col = room["collision"]
            attrs = [0] * (col["width"] * col["height"])
            for x in range(col["width"]):
                attrs[(col["height"] - 2) * col["width"] + x] = 0x01
                attrs[(col["height"] - 1) * col["width"] + x] = 0x01
            for y in range(col["height"] - 2):
                attrs[y * col["width"]] = 0x01
                attrs[y * col["width"] + col["width"] - 1] = 0x01
            col["attrs"] = attrs
            room["spawn"] = {"x": 64, "y": (col["height"] - 3) * 16}
            room["spawns"] = [{"x": 64, "y": room["spawn"]["y"], "flags": 0}]
        self.send_json(200, {"ok": True, "room": room,
                             "validation": ws.validate_room(room, area)})

    def handle_player_post(self, target: str, body: dict) -> None:
        ws = self.server.workspace
        if ws.player_target(target) is None:
            self.send_error_json(404, f"unknown player target {target!r}")
            return
        entry = body.get("entry")
        if not isinstance(entry, dict):
            raise ValueError("body.entry must be an object")
        result = ws.save_player(target, entry)
        if not result.get("ok"):
            validation = result.get("validation") or {
                "ok": False,
                "errors": [{"level": "error", "code": "player.save",
                            "message": result.get("error", "save failed")}],
                "warnings": [],
            }
            self.send_json(400, {"ok": False, "validation": validation})
            return
        self.send_json(200, {"ok": True, **result})

    def handle_species_post(self, key: str, body: dict) -> None:
        ws = self.server.workspace
        entry = body.get("entry")
        if not isinstance(entry, dict):
            raise ValueError("body.entry must be an object")
        definition = body.get("definition")
        if definition is not None and not isinstance(definition, dict):
            raise ValueError("body.definition must be an object or null")
        result = ws.save_species(key, entry, definition,
                                 target=str(body.get("target") or "authored"))
        self.send_json(200 if result.get("ok") else 422, result)

    def handle_render_room(self, area: int, body: dict) -> None:
        """Render the unsaved room with the real game, headless.

        The room is written to a throwaway ``DC_AUTHORED_ROOMS`` directory so
        the game loads exactly what the editor has, without touching the
        user's saved overlay.  ``DC_RUN_FRAMES`` drives the deterministic loop
        and ``DC_SCREENSHOT_RT`` dumps the 256x224 render target.
        """
        ws = self.server.workspace
        room = body.get("room")
        if not isinstance(room, dict):
            raise ValueError("body.room must be an object")
        report = ws.validate_room(room, area)
        if not report["ok"]:
            self.send_json(422, {"ok": False, "validation": report,
                                 "error": "room is not valid"})
            return
        frames = editor_data.clamp_int(body.get("frames"), 90, 1, 900)
        render_dir = ws.root / "captures" / "editor_render"
        render_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = render_dir / f"area{area}_{stamp}_{int(time.time() * 1000) % 1000:03d}.png"
        work = Path(tempfile.mkdtemp(prefix=f"dc-render-{area}-",
                                     dir=str(render_dir)))
        python = _python_executable(ws.root)
        env = os.environ.copy()
        for key in ("DC_DEMO", "DC_TITLE", "DC_STATE", "DC_TRACE_CSV",
                    "DC_TRACE_OBJECTS", "DC_TRACE_PROJECTILES",
                    "DC_SCREENSHOT", "DC_CAMPAIGN",
                    "DC_AUTHORED_ROOMS", "DC_AUTHORED_DIR",
                    "DC_NO_PLAYER", "DC_NO_OBJ", "DC_NO_PROJ",
                    "DC_NO_HDMA", "DC_LAYER_MASK", "DC_DEBUG_OBJ",
                    "DC_BOSS_HP", "DC_BOSS_HURT", "DC_BOSS_PHASE",
                    "DC_BOSS_X", "DC_BOSS_Y", "DC_BOSS_NO_ATTACK",
                    "DC_BOSS_CLEAR", "DC_BOSS_DEFEATED"):
            env.pop(key, None)
        env.update({
            "DC_AREA": str(area),
            "DC_RUN_FRAMES": str(frames),
            "DC_SCREENSHOT_RT": str(out),
            "DC_NO_AUDIO": "1",
            "DC_AUTHORED_ROOMS": str(work),
        })
        started = time.time()
        try:
            room = dict(room)
            room["area_id"] = area
            editor_data.atomic_write_json(
                work / f"room_area{area}.json",
                editor_data.normalize_room(room))
            with self.server.render_lock:
                proc = subprocess.run(
                    [python, "-m", "dcpy.main", "--assets", str(ws.assets)],
                    cwd=str(ws.root), env=env, timeout=150,
                    capture_output=True, text=True)
            elapsed = int((time.time() - started) * 1000)
            if proc.returncode != 0 or not out.is_file():
                tail = ((proc.stderr or "") + "\n" +
                        (proc.stdout or "")).strip()[-4000:]
                self.send_json(500, {
                    "ok": False,
                    "error": f"game render failed (exit {proc.returncode})",
                    "detail": tail,
                })
                return
            # Keep the directory from growing without bound.
            old = sorted(render_dir.glob("area*.png"),
                         key=lambda p: p.stat().st_mtime)
            for path in old[:-40]:
                try:
                    path.unlink()
                except OSError:
                    pass
            self.send_json(200, {
                "ok": True,
                "url": "/captures/editor_render/" + urllib.parse.quote(out.name),
                "path": str(out.relative_to(ws.root)).replace("\\", "/"),
                "width": 256, "height": 224,
                "frames": frames, "ms": elapsed,
            })
        except subprocess.TimeoutExpired:
            self.send_json(500, {"ok": False,
                                 "error": "game render timed out (150 s)"})
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _parse_area(path: str, ws: editor_data.Workspace) -> int:
        rest = path[len("/api/rooms/"):].strip("/")
        token = rest.split("/")[0] if rest else ""
        try:
            area = int(token)
        except ValueError:
            raise ValueError(f"invalid room area {token!r}") from None
        if area < 0 or area > 4095:
            raise ValueError("room area must be 0..4095")
        return area

    @staticmethod
    def _parse_index(path: str, prefix: str) -> int:
        token = path[len(prefix):].strip("/").split("/")[0]
        try:
            index = int(token)
        except ValueError:
            raise ValueError(f"invalid text block index {token!r}") from None
        if index < 0:
            raise ValueError("text block index must be >= 0")
        return index


def _python_executable(root: Path) -> str:
    """Prefer the project venv, which is where raylib is installed."""
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        path = root / rel
        if path.is_file():
            return str(path)
    return sys.executable


def find_open_port(host: str, start: int, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"no free port in {start}..{start + tries - 1}")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--port-tries", type=int, default=20,
                        help="try this many ports when the first is busy")
    parser.add_argument("--assets", default=None,
                        help="asset tree (default: <repo>/assets/generated)")
    parser.add_argument("--authored", default=None,
                        help="editable overlay (default: <assets>/../authored)")
    parser.add_argument("--root", default=str(ROOT),
                        help="repository root (default: this checkout)")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    assets = Path(args.assets).resolve() if args.assets else None
    authored = Path(args.authored).resolve() if args.authored else None
    ws = editor_data.Workspace(root, assets, authored)
    if not (ws.assets / "room.json").is_file() and \
            not any(ws.assets.glob("room_area*.json")):
        print(f"editor: no room files under {ws.assets}", file=sys.stderr)
        print("        pass --assets <dir> or run tools/build_assets.sh first",
              file=sys.stderr)
        return 2
    try:
        port = find_open_port(args.host, args.port, args.port_tries)
    except OSError as exc:
        print(f"editor: {exc}", file=sys.stderr)
        return 2
    httpd = EditorServer((args.host, port), ws)
    url = f"http://{args.host}:{port}/"
    print("Demon's Crest editor suite")
    print(f"  UI:        {url}")
    print(f"  assets:    {ws.assets}")
    print(f"  authored:  {ws.authored}")
    print(f"  rooms:     {len(ws.all_room_areas())}")
    print("  Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\neditor: stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
