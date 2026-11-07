#!/usr/bin/env python3
"""Backend tests for the visual editor suite.

Run with the project venv (only the standard library is used here):

    python tools/editor/test_editor.py

The tests build a temporary project tree so saving never touches the real
assets.  They cover the room overlay, validation, resizing, the species
overlay/definition sidecar and the HTTP API surface.
"""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import editor_data
import server as editor_server

ROOT = Path(__file__).resolve().parents[2]


class EditorDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-test-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "generated" / "enemy_2c_0.png",
                     self.assets / "enemy_2c_0.png")
        shutil.copy2(ROOT / "assets" / "generated" / "room_area48.json",
                     self.assets / "room_area48.json")
        species = {
            "species": {
                "2c": {
                    "species": 44,
                    "frames": [{
                        "texture": "enemy_2c_0.png", "anchor_x": 12,
                        "anchor_y": 37, "duration": 8, "width": 25,
                        "height": 38,
                    }],
                    "states": {"0": [0]},
                    "source": "test",
                }
            }
        }
        (self.assets / "species_anim.json").write_text(json.dumps(species))
        shutil.copy2(ROOT / "assets" / "generated" / "player_idle_0.png",
                     self.assets / "player_idle_0.png")
        player_clip = {
            "idle": {
                "loop": True,
                "steps": [{
                    "texture": "player_idle_0.png", "anchor_x": 16,
                    "anchor_y": 43, "duration": 8,
                }],
            }
        }
        (self.assets / "player_anim.json").write_text(json.dumps(
            {"clips": player_clip}))
        (self.assets / "player_forms.json").write_text(json.dumps({
            "forms": [{"form": 2, "name": "aerial", "clips": player_clip}]
        }))
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blank_room_and_resize(self):
        room = self.ws.blank_room(900, 512, 256, "test")
        report = self.ws.validate_room(room, 900)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(len(room["collision"]["attrs"]), 32 * 16)
        resized = self.ws.resize_room(room, 1024, 512)
        self.assertEqual(resized["world"], {"width": 1024, "height": 512})
        self.assertEqual(len(resized["collision"]["attrs"]), 64 * 32)
        self.assertEqual(len(resized["bg"][1]["tilemap"]), 128 * 64)

    def test_room_save_load_revert(self):
        loaded = self.ws.load_room(48)
        room = loaded["room"]
        room["name"] = "overridden"
        room["music"] = 14
        result = self.ws.save_room(48, room, "authored")
        self.assertTrue(result["ok"], result.get("validation"))
        self.assertTrue((self.authored / "rooms" / "room_area48.json").is_file())
        again = self.ws.load_room(48)
        self.assertEqual(again["source"], "authored")
        self.assertEqual(again["room"]["name"], "overridden")
        self.assertEqual(again["room"]["music"], 14)
        self.assertTrue(self.ws.revert_room(48)["ok"])
        self.assertEqual(self.ws.load_room(48)["source"], "generated")

    def test_bad_room_is_blocked(self):
        room = self.ws.load_room(48)["room"]
        room["collision"]["attrs"] = room["collision"]["attrs"][:-1]
        result = self.ws.save_room(48, room, "authored")
        self.assertFalse(result["ok"])
        self.assertFalse((self.authored / "rooms" / "room_area48.json").exists())

    def test_species_save_definition_and_delete(self):
        detail = self.ws.load_species("2c")
        entry = {k: v for k, v in detail["entry"].items() if k != "url"}
        definition = editor_data.normalize_enemy_def({
            "name": "Test Skeleton",
            "status": {"hp": 5, "contact_damage": 2},
            "movement": {"ai": "walker", "speed": 0.75},
            "attacks": [{"type": "projectile", "cooldown": 90, "count": 2}],
            "sounds": {"attack": "shoot"},
        })
        result = self.ws.save_species("2c", entry, definition)
        self.assertTrue(result["ok"], result.get("validation"))
        self.assertTrue((self.authored / "species_anim.json").is_file())
        root = json.loads((self.authored / "enemies.json").read_text())
        saved = root["enemies"]["2c"]
        self.assertEqual(saved["species"], 44)
        self.assertEqual(saved["flags"], 0)
        self.assertEqual(saved["status"]["hp"], 5)
        again = self.ws.load_species("2c")
        self.assertEqual(again["source"], "authored")
        self.assertEqual(again["definition"]["name"], "Test Skeleton")
        self.assertTrue(self.ws.delete_species("2c")["ok"])
        self.assertFalse((self.authored / "species_anim.json").exists())
        self.assertFalse((self.authored / "enemies.json").exists())

    def test_player_form_save_load_revert(self):
        data = self.ws.list_player()
        self.assertEqual(data["base"]["kind"], "base")
        self.assertEqual(len(data["forms"]), 1)
        detail = self.ws.load_player("2")
        self.assertEqual(detail["source"], "generated")
        entry = {k: v for k, v in detail["entry"].items() if k != "url"}
        entry["name"] = "aerial edited"
        result = self.ws.save_player("2", entry)
        self.assertTrue(result["ok"], result.get("validation"))
        self.assertTrue((self.authored / "player_forms.json").is_file())
        again = self.ws.load_player("2")
        self.assertEqual(again["source"], "authored")
        self.assertEqual(again["entry"]["name"], "aerial edited")
        self.assertEqual(again["entry"]["clips"]["idle"]["steps"][0]["url"],
                         "/assets/generated/player_idle_0.png")
        self.assertTrue(self.ws.delete_player("2")["ok"])
        self.assertFalse((self.authored / "player_forms.json").exists())
        self.assertEqual(self.ws.load_player("2")["source"], "generated")

    def test_upload(self):
        png = (self.assets / "enemy_2c_0.png").read_bytes()
        result = self.ws.save_upload("my imp.png",
                                     base64.b64encode(png).decode())
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["texture"].startswith("sprites/"))
        self.assertEqual((result["width"], result["height"]), (25, 38))
        self.assertTrue((self.root / result["path"]).is_file())
        bad = self.ws.save_upload("x.png", base64.b64encode(b"nope").decode())
        self.assertFalse(bad["ok"])


class EditorApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-api-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "generated" / "room_area48.json",
                     self.assets / "room_area48.json")
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)
        self.httpd = editor_server.EditorServer(("127.0.0.1", 0), self.ws)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, json.loads(response.read().decode())

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode())

    def test_health_meta_rooms(self):
        status, health = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        status, meta = self.get("/api/meta")
        self.assertEqual(len(meta["music"]), 18)
        status, rooms = self.get("/api/rooms")
        self.assertEqual(len(rooms["rooms"]), 1)
        self.assertEqual(rooms["rooms"][0]["area"], 48)

    def test_room_get_and_validate(self):
        status, payload = self.get("/api/rooms/48")
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "generated")
        self.assertIn("assets", payload)
        status, report = self.post("/api/rooms/48/validate",
                                   {"room": payload["room"]})
        self.assertTrue(report["ok"])

    def test_new_save_revert_with_http(self):
        status, template = self.post("/api/rooms/new", {
            "area": 901, "width": 512, "height": 256, "name": "api room",
            "atlas_area": 48, "template": "floor"})
        self.assertEqual(status, 200)
        room = template["room"]
        room["music"] = 5
        status, saved = self.post("/api/rooms/901",
                                  {"room": room, "target": "authored"})
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved["ok"])
        status, loaded = self.get("/api/rooms/901")
        self.assertEqual(loaded["source"], "authored")
        self.assertEqual(loaded["room"]["music"], 5)
        request = urllib.request.Request(self.base + "/api/rooms/901",
                                         method="DELETE")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)

    def test_selftest_endpoint(self):
        status, result = self.post("/api/_selftest", {
            "results": [{"name": "x", "ok": True, "detail": "y"}]})
        self.assertEqual(status, 200)
        self.assertTrue((self.root / "captures" /
                         "editor_selftest.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
