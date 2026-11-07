"""Headless runtime check for the Enemy Editor's boss attack patterns.

Builds a throwaway authored species/definition/room, runs the real game with
``DC_AUTHORED_ROOMS`` and ``DC_AUTHORED_DIR`` pointing at the temp tree, and
asserts that the boss spawned with the authored HP and fired its projectile
volley.  Nothing in the real assets tree is touched.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
assets = ROOT / "assets" / "generated"
tmp = pathlib.Path(tempfile.mkdtemp(prefix="dc-boss-attack-"))
(tmp / "rooms").mkdir()
entry = {
    "species": 0x121,
    "variant": "boss",
    "flags": 0,
    "frames": [{
        "texture": "enemy_2c_0.png", "anchor_x": 12, "anchor_y": 37,
        "duration": 8, "width": 25, "height": 38,
    }],
    "states": {"0": [0], "1": [0]},
    "source": "boss attack test",
}
(tmp / "species_anim.json").write_text(json.dumps({"species": {"121": entry}}))
defn = {
    "version": 1,
    "enemies": {"121": {
        "key": "121", "species": 0x121, "flags": 0, "name": "Pattern Boss",
        "status": {"hp": 12, "contact_damage": 2, "defense": 0,
                   "invulnerable": False},
        "movement": {"ai": "stationary", "speed": 0, "range": 180,
                     "bob": 0, "gravity": False, "override_ai": False},
        "attacks": [{"type": "projectile", "cooldown": 25, "range": 300,
                     "count": 3, "spread": 30, "speed": 1.5, "damage": 2,
                     "species": 0x67, "aim": "player", "sfx": "shoot"}],
        "sounds": {},
    }},
}
(tmp / "enemies.json").write_text(json.dumps(defn))
room = json.loads((assets / "room_area48.json").read_text())
room["objects"] = [{"type": "boss", "species": 0x121, "flags": 0,
                    "x": 150, "y": 160}]
(tmp / "rooms" / "room_area48.json").write_text(json.dumps(room))
trace = tmp / "objects.csv"
env = os.environ.copy()
env.update({
    "DC_AREA": "48", "DC_RUN_FRAMES": "90",
    "DC_AUTHORED_ROOMS": str(tmp / "rooms"),
    "DC_AUTHORED_DIR": str(tmp),
    "DC_TRACE_OBJECTS": str(trace), "DC_NO_AUDIO": "1",
})
proc = subprocess.run([sys.executable, "-m", "dcpy.main", "--assets",
                       str(assets)], cwd=ROOT, env=env, capture_output=True,
                      text=True, timeout=120)
print("game exit", proc.returncode)
if proc.returncode:
    print(proc.stderr[-2000:])
rows = trace.read_text().splitlines()
boss = [r for r in rows if ",289," in r]
shots = [r for r in rows if ",103," in r]
print("boss rows", len(boss), "shot rows", len(shots))
if boss:
    print("first boss", boss[0])
if shots:
    print("first shot", shots[0])
assert proc.returncode == 0
assert boss and shots, "authored boss patterns did not fire"
assert int(boss[0].split(",")[8]) == 12, boss[0]
print("OK")
