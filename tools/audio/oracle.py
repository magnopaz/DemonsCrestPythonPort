#!/usr/bin/env python3
"""Shared client for the recomp's debug server (the behavioural oracle).

Every audio tool in this directory drives the same TCP protocol: launch
`DemonsCrestSNESRecomp[.exe] <rom> --paused [--resume-state <sav>]`, then talk
line-oriented JSON over TCP.  This module keeps one copy of the launch, the
connection retry, the path quirks (Windows needs `.exe`, and paths echoed back
inside JSON must use forward slashes) and the small helpers the capture tools
were each re-implementing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
DEFAULT_ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))
NATIVE_RATE = 32040

_EXE_CANDIDATES = (
    ("build-trace", "DemonsCrestSNESRecomp.exe"),
    ("build-trace", "DemonsCrestSNESRecomp"),
    ("build", "DemonsCrestSNESRecomp.exe"),
    ("build", "DemonsCrestSNESRecomp"),
)


def find_exe(recomp: Path | None = None) -> Path:
    """The oracle binary, preferring the trace build (it has the audio rings)."""
    root = Path(recomp or DEFAULT_RECOMP)
    for rel, name in _EXE_CANDIDATES:
        cand = root / rel / name
        if cand.is_file():
            return cand
    raise SystemExit(f"oracle: no DemonsCrestSNESRecomp build under {root}")


def find_saves(recomp: Path | None = None) -> Path:
    root = Path(recomp or DEFAULT_RECOMP)
    for rel in ("build-trace/saves", "build/saves"):
        cand = root / rel
        if cand.is_dir():
            return cand
    raise SystemExit(f"oracle: no saves directory under {root}")


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Client:
    """Line-oriented JSON client for the debug server."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.f = sock.makefile("rwb")

    # -- protocol -------------------------------------------------------
    def cmd(self, text: str) -> dict:
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"oracle: no response to {text!r}")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"oracle: bad reply to {text!r}: {line!r}") from exc
        if "error" in msg:
            raise RuntimeError(f"oracle: {text!r}: {msg['error']}")
        return msg

    # -- convenience ----------------------------------------------------
    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def read(self, addr: int, n: int) -> bytes:
        raw = self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", "")
        return bytes.fromhex(raw)

    def write(self, addr: int, data: bytes) -> None:
        self.cmd(f"write_ram {addr:x} {data.hex()}")

    def run_to(self, target: int, timeout: float = 900.0) -> int:
        if self.frame() >= target:
            return self.frame()
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + timeout
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"oracle: timeout waiting for frame {target}")
            time.sleep(0.01)
        return self.frame()

    def run_frames(self, frames: int) -> int:
        return self.run_to(self.frame() + frames)

    def port_events(self, first: int = 0, limit: int = 8000) -> dict:
        return self.cmd(f"audio_events {first} {limit} 2")

    def close(self) -> None:
        try:
            self.f.close()
        finally:
            self.sock.close()


def connect(port: int, timeout: float = 120.0) -> Client:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=5))
        except OSError as exc:  # not listening yet
            last = exc
            time.sleep(0.1)
    raise SystemExit(f"oracle: no debug server on port {port} ({last})")


class Session:
    """Launch the oracle paused on a save state (or a cold boot) and connect.

    The server rewrites relative path arguments against the game directory, so
    a one-shot resume file is copied inside the recomp tree first — the same
    thing every capture tool did by hand.
    """

    def __init__(self, save: Path | None = None, *, rom: Path | None = None,
                 recomp: Path | None = None, port: int = 4402,
                 extra_args: list[str] | None = None,
                 workdir: Path | None = None) -> None:
        self.recomp = Path(recomp or DEFAULT_RECOMP)
        self.exe = find_exe(self.recomp)
        self.rom = Path(rom or DEFAULT_ROM)
        self.port = port
        self.save = Path(save) if save else None
        self.extra_args = list(extra_args or [])
        self.workdir = Path(workdir or self.recomp)
        self.proc: subprocess.Popen | None = None
        self.client: Client | None = None
        self.log_path: Path | None = None
        self._resume: Path | None = None
        self._log = None

    def __enter__(self) -> "Session":
        if not self.rom.is_file():
            raise SystemExit(f"oracle: missing ROM {self.rom}")
        args = [str(self.exe), str(self.rom), "--paused"]
        if self.save is not None:
            if not self.save.is_file():
                raise SystemExit(f"oracle: missing save {self.save}")
            self._resume = self.recomp / f"_dc_resume_{self.port}.sav"
            shutil.copyfile(self.save, self._resume)
            args += ["--resume-state", str(self._resume)]
        args += self.extra_args
        env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(self.port),
                   SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        self._log = subprocess.DEVNULL
        self.proc = subprocess.Popen(args, cwd=str(self.workdir), env=env,
                                     stdout=self._log, stderr=self._log)
        self.client = connect(self.port)
        return self

    def __exit__(self, *exc) -> None:
        if self.client is not None:
            self.client.close()
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log is not None:
            try:
                self._log.close()
            except Exception:
                pass
        if self._resume is not None:
            try:
                self._resume.unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    print(find_exe())
    print(find_saves())
    return 0


if __name__ == "__main__":
    sys.exit(main())
