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
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import editor_data
import server as editor_server

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
        source = self.assets / "enemy_2c_0.png"
        png = source.read_bytes()
        result = self.ws.save_upload("my imp.png",
                                     base64.b64encode(png).decode())
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["texture"].startswith("sprites/"))
        # The expected size comes from the PNG itself; the sprite pipeline has
        # changed the width of this sheet before.
        self.assertEqual((result["width"], result["height"]),
                         editor_data.png_size(source))
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


class EditorTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-text-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        self.assets.joinpath("text_strings.json").write_text(json.dumps({
            "strings": [
                {"addr": "81:8000", "length": 10,
                 "pages": [["HELLO WORLD"]]},
                {"addr": "81:8010", "length": 20,
                 "pages": [["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                            "L8", "L9"]]},
                {"addr": "81:8020", "length": 12,
                 "pages": [["FOO jBAR", "BAZ"]]},
            ]
        }), encoding="utf-8")
        self.assets.joinpath("font.json").write_text(json.dumps({
            "cell": 8, "columns": 16, "rows": 6, "first": 32, "last": 126,
            "filled": 96,
        }), encoding="utf-8")
        game_dir = self.root / "dcpy"
        game_dir.mkdir()
        game_dir.joinpath("game.py").write_text(
            "def shop(script):\n"
            "    return text_find(game.script, \"HELLO WORLD\")\n\n"
            "BOSS_INTRO_TEXT = {23: \"NOT IN THE SCRIPT\"}\n",
            encoding="utf-8")
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_matches_the_loader(self):
        data = self.ws.text_index()
        self.assertEqual(data["stats"]["blocks"], 3)
        self.assertEqual(data["stats"]["truncated_lines"], 1)
        self.assertEqual(data["stats"]["blocks_over_lines"], 1)
        block = data["blocks"][2]
        self.assertEqual(block["loaded"], [["FOO ", "BAR", "BAZ"]])
        self.assertEqual(block["line_counts"], [3])
        self.assertEqual(block["pages"], [["FOO jBAR", "BAZ"]])
        self.assertFalse(block["authored"])
        codes = {w["code"] for w in data["blocks"][1]["warnings"]}
        self.assertIn("text.lines.cap", codes)

    def test_usages_resolve_against_the_game_source(self):
        data = self.ws.text_index()
        usages = {u["needle"]: u for u in data["usages"]}
        self.assertTrue(usages["HELLO WORLD"]["found"])
        self.assertEqual(usages["HELLO WORLD"]["index"], 0)
        self.assertFalse(usages["NOT IN THE SCRIPT"]["found"])
        self.assertEqual(usages["NOT IN THE SCRIPT"]["source"], "boss_intro")
        self.assertIn("HELLO WORLD", data["blocks"][0]["used_by"])

    def test_save_and_delete_text_overlay(self):
        result = self.ws.save_text(0, [["HELLO EDITED"], ["SECOND PAGE"]])
        self.assertTrue(result["ok"], result)
        path = self.authored / "text_strings.json"
        self.assertTrue(path.is_file())
        root = json.loads(path.read_text())
        self.assertEqual(root["strings"]["0"]["pages"],
                         [["HELLO EDITED"], ["SECOND PAGE"]])
        data = self.ws.text_index()
        self.assertEqual(data["blocks"][0]["pages"],
                         [["HELLO EDITED"], ["SECOND PAGE"]])
        self.assertTrue(data["blocks"][0]["authored"])
        self.assertEqual(data["stats"]["authored"], 1)
        self.assertTrue(self.ws.delete_text(0)["ok"])
        self.assertFalse(path.exists())
        self.assertFalse(self.ws.text_index()["blocks"][0]["authored"])

    def test_text_rejects_non_font_characters(self):
        result = self.ws.save_text(0, [["CAFÉ"]])
        self.assertFalse(result["ok"])
        self.assertIn("errors", result)
        self.assertEqual(result["errors"][0]["code"], "text.chars.ascii")

    def test_text_loader_overlay_is_read_by_the_game(self):
        try:
            from dcpy import text as dc_text
        except Exception as exc:  # raylib missing: keep the suite runnable
            self.skipTest(f"dcpy.text unavailable: {exc}")
        self.assertTrue(self.ws.save_text(0, [["HELLO FROM THE OVERLAY"]])["ok"])
        script = dc_text.TextScript()
        self.assertTrue(dc_text.text_load_script(script, str(self.assets)))
        self.assertEqual(script.count, 3)
        self.assertEqual(script.pages[0][0], ["HELLO FROM THE OVERLAY"])
        self.assertEqual(dc_text.text_find(script, "FROM THE OVERLAY"), 0)

    def test_editor_caps_match_dcpy_text(self):
        source = (ROOT / "dcpy" / "text.py").read_text(encoding="utf-8")
        for name in ("TEXT_MAX_STRINGS", "TEXT_MAX_PAGES", "TEXT_MAX_LINES",
                     "TEXT_LINE_MAX", "TEXT_GLYPH_W", "TEXT_LINE_H"):
            value = getattr(editor_data, name)
            self.assertRegex(source, rf"(?m)^{name}\s*=\s*{value}\b", name)


class EditorCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-coverage-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "generated" / "room_area48.json",
                     self.assets / "room_area48.json")
        shutil.copy2(ROOT / "assets" / "generated" / "enemy_2c_0.png",
                     self.assets / "enemy_2c_0.png")
        (self.assets / "species_anim.json").write_text(json.dumps({
            "species": {"2c": {
                "species": 44,
                "frames": [{"texture": "enemy_2c_0.png", "anchor_x": 12,
                            "anchor_y": 37, "duration": 8}],
                "states": {"0": [0]},
            }}
        }), encoding="utf-8")
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)

    def tearDown(self):
        self.tmp.cleanup()

    def test_coverage_counts_objects_and_sheets(self):
        cov = self.ws.coverage()
        totals = cov["totals"]
        self.assertEqual(totals["rooms"], 1)
        self.assertEqual(totals["objects"], 1)
        self.assertEqual(totals["unknown"], 0)
        self.assertEqual(totals["handled"], 1)
        self.assertEqual(totals["boss_records"], 1)
        self.assertEqual(totals["species_with_records"], 1)
        self.assertEqual(cov["rooms"][0]["area"], 48)
        self.assertTrue(cov["rooms"][0]["valid"])
        row = next(r for r in cov["species"] if r["species"] == 44)
        self.assertEqual(row["records"], 0)
        self.assertTrue(row["has_art"])
        self.assertEqual(row["canonical_key"], "2c")
        boss = next(r for r in cov["species"] if r["species"] == 150)
        self.assertTrue(boss["boss"])
        self.assertFalse(boss["has_art"])
        self.assertEqual(boss["records"], 1)

    def test_coverage_cache_sees_an_authored_room(self):
        loaded = self.ws.load_room(48)
        room = loaded["room"]
        room["objects"].append({"type": "enemy", "species": 44, "flags": 0,
                                "x": 72, "y": 180, "source": "test"})
        self.assertTrue(self.ws.save_room(48, room, "authored")["ok"])
        cov = self.ws.coverage()
        self.assertEqual(cov["totals"]["objects"], 2)
        self.assertEqual(cov["totals"]["unknown"], 0)
        row = next(r for r in cov["species"] if r["species"] == 44)
        self.assertEqual(row["records"], 1)
        self.assertEqual(row["unknown"], 0)


class EditorChecksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-checks-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "check_sample.py").write_text(
            '"""Sample gate for the editor tests."""\n'
            'print("sample: PASS (nothing to do)")\n',
            encoding="utf-8")
        (tools / "run_regression.py").write_text(
            '"""Full regression (stub)."""\n'
            'print("regression: PASS (stub)")\n',
            encoding="utf-8")
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_and_run_a_check(self):
        listing = self.ws.list_checks()
        names = [c["name"] for c in listing["checks"]]
        self.assertEqual(names, ["check_sample", "regression"])
        sample = listing["checks"][0]
        self.assertEqual(sample["description"],
                         "Sample gate for the editor tests.")
        result = self.ws.run_check("check_sample", 60)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("PASS", result["stdout"])
        self.assertIn("PASS", result["summary"])
        again = self.ws.list_checks()["checks"][0]
        self.assertEqual(again["last"]["status"], "pass")

    def test_regression_name_maps_to_run_regression_py(self):
        result = self.ws.run_check("regression", 60)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["command"].endswith("tools/run_regression.py"))

    def test_rejects_paths_outside_the_tool_list(self):
        self.assertFalse(self.ws.run_check("../server", 30)["ok"])
        self.assertFalse(self.ws.run_check("check_missing", 30)["ok"])


class EditorApiV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dc-editor-api2-")
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets" / "generated"
        self.authored = self.root / "assets" / "authored"
        self.assets.mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "generated" / "room_area48.json",
                     self.assets / "room_area48.json")
        (self.assets / "text_strings.json").write_text(json.dumps({
            "strings": [{"addr": "81:8000", "length": 10,
                         "pages": [["HELLO WORLD"]]}]
        }), encoding="utf-8")
        self.ws = editor_data.Workspace(self.root, self.assets, self.authored)
        self.httpd = editor_server.EditorServer(("127.0.0.1", 0), self.ws)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode())

    def test_coverage_and_text_routes(self):
        status, coverage = self.request("/api/coverage")
        self.assertEqual(status, 200)
        self.assertTrue(coverage["ok"])
        self.assertEqual(coverage["totals"]["rooms"], 1)
        status, text = self.request("/api/text")
        self.assertEqual(status, 200)
        self.assertEqual(text["stats"]["blocks"], 1)
        status, block = self.request("/api/text/0")
        self.assertEqual(status, 200)
        self.assertEqual(block["block"]["pages"], [["HELLO WORLD"]])
        status, saved = self.request("/api/text/0", "POST",
                                     {"pages": [["EDITED"]]})
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved["ok"])
        status, _ = self.request("/api/text/0")
        self.assertEqual(status, 200)
        status, deleted = self.request("/api/text/0", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["ok"])

    def test_campaign_and_collectibles_routes(self):
        status, camp = self.request("/api/campaign")
        self.assertEqual(status, 200)
        self.assertTrue(camp["ok"])
        self.assertEqual(camp["stats"]["total_rooms"], len(camp["nodes"]))
        self.assertIn("issues", camp)
        self.assertIn("stages", camp)
        status, col = self.request("/api/collectibles")
        self.assertEqual(status, 200)
        self.assertTrue(col["ok"])
        self.assertIn("collectibles", col)
        self.assertIn("summary", col)

    def test_check_routes(self):
        status, listing = self.request("/api/checks")
        self.assertEqual(status, 200)
        self.assertIsInstance(listing["checks"], list)
        status, result = self.request("/api/checks/run", "POST",
                                      {"name": "check_nope"})
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

    def test_web_modules_are_not_cached(self):
        # The UI is edited in place; a cached module would hide every change
        # until a hard reload.
        with urllib.request.urlopen(self.base + "/web/js/app.js") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")


class EditorProjectTextTests(unittest.TestCase):
    """Read-only checks against this checkout's real text data."""

    def setUp(self):
        self.assets = ROOT / "assets" / "generated"
        if not (self.assets / "text_strings.json").is_file():
            self.skipTest("assets/generated/text_strings.json is missing")

    def test_every_text_find_needle_resolves(self):
        ws = editor_data.Workspace(ROOT, self.assets,
                                   ROOT / "assets" / "authored")
        data = ws.text_index()
        self.assertGreaterEqual(len(data["usages"]), 20)
        missing = [u for u in data["usages"] if not u["found"]]
        self.assertFalse(missing, "; ".join(
            f"{u['needle']} ({u['where']})" for u in missing))

    def test_cemetery_bg1_offset(self):
        # Area 1's BG1 tilemap is authored 53 px above the world origin; the
        # world-space offset is a separate field so area 4's camera-relative
        # scroll_y stays ignored.
        ws = editor_data.Workspace(ROOT, self.assets,
                                   ROOT / "assets" / "authored")
        room = ws.load_room(1)
        self.assertIsNotNone(room)
        assert room is not None
        room = room["room"]
        bg1 = room["bg"][1]
        self.assertEqual(bg1["scroll_y"], 0)
        self.assertEqual(bg1["offset_y"], 53)

    def test_campaign_graph_covers_every_room(self):
        ws = editor_data.Workspace(ROOT, self.assets,
                                   ROOT / "assets" / "authored")
        graph = ws.campaign_graph()
        self.assertEqual(graph["stats"]["total_rooms"],
                         len(ws.all_room_areas()))
        self.assertEqual(len(graph["nodes"]), len(ws.all_room_areas()))
        self.assertGreater(len(graph["edges"]), 100)
        self.assertEqual(len(graph["stages"]), 11)
        self.assertGreater(graph["stats"]["dead_ends"], 0)

    def test_dialogue_view_caps_are_respected(self):
        ws = editor_data.Workspace(ROOT, self.assets,
                                   ROOT / "assets" / "authored")
        data = ws.text_index()
        self.assertEqual(data["caps"]["pages"], 8)
        self.assertLessEqual(data["stats"]["blocks"], data["caps"]["strings"])
        # Every block that the index reports must load at least one page.
        empty = [b["index"] for b in data["blocks"] if not b["loaded"]]
        self.assertFalse(empty, f"blocks with no displayable pages: {empty}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
