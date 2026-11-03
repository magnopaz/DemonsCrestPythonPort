"""Shared helpers: environment flags, JSON loading and C-compatible rounding."""

from __future__ import annotations

import json
import math
import os
import sys

FX_ONE = 256


def eprint(*args, **kwargs) -> None:
    """Diagnostics go to stderr, like the C build's fprintf(stderr, ...).

    The project's checkers parse stderr for the debug hooks (boss-intro phases,
    audio track probes, gate decisions), so stdout must stay clean.
    """
    kwargs.pop("flush", None)
    print(*args, file=sys.stderr, flush=True, **kwargs)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def env_flag(name: str) -> bool:
    return name in os.environ


def env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def lround(value: float) -> int:
    """C lroundf: round half away from zero."""
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def fx_to_float(value: int) -> float:
    return value / float(FX_ONE)


def float_to_fx(value: float) -> int:
    return lround(value * FX_ONE)


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def file_exists(path: str) -> bool:
    return os.path.isfile(path)


def as_int(value, fallback: int = 0) -> int:
    return int(value) if isinstance(value, (int, float)) else fallback


def as_float(value, fallback: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else fallback
