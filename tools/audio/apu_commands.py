#!/usr/bin/env python3
"""Decode the CPU->APU command stream.

The driver takes a command as four port writes: the three arguments go to
ports 1, 2 and 3, then the command id to port 0.  Port 0 is re-written with
0xF9 while the game waits for the driver's acknowledgement, so 0xF9 is a poll
and not a command.

This module turns `audio_events` output into (frame, cmd, args) triples, which
is what every analysis in this directory needs.
"""

from __future__ import annotations

from dataclasses import dataclass

POLL = 0xF9


@dataclass
class Command:
    frame: int
    sample: int
    cmd: int
    args: tuple[int, int, int]

    def __str__(self) -> str:
        return (f"f{self.frame} cmd=0x{self.cmd:02x}"
                f" args={self.args[0]:02x},{self.args[1]:02x},{self.args[2]:02x}"
                f" ({self.args[0]},{self.args[1]},{self.args[2]})")


def decode(events: list[dict], keep_polls: bool = False) -> list[Command]:
    """Pair each port-0 write with the args last written to ports 1..3."""
    out: list[Command] = []
    args = [0, 0, 0]
    for ev in events:
        if ev["t"] != "cpu_wr":
            continue
        port = int(ev["adr"], 16)
        val = int(ev["val"], 16)
        if 1 <= port <= 3:
            args[port - 1] = val
        elif port == 0:
            if val == POLL and not keep_polls:
                continue
            out.append(Command(int(ev["aux"]), int(ev["s"]), val,
                               (args[0], args[1], args[2])))
    return out


def drain(client, cursor: int) -> tuple[list[dict], int]:
    out: list[dict] = []
    while True:
        msg = client.port_events(cursor, 8000)
        batch = msg.get("events", [])
        if not batch:
            break
        out.extend(batch)
        cursor = int(batch[-1]["s"]) + 1
        if len(batch) < 8000:
            break
    return out, cursor
