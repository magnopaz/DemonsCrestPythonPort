#!/usr/bin/env python3
"""Fetch the Demon's Crest lore pages from the Ghosts'n Goblins wiki as wikitext.

The wiki is behind a bot check for normal page loads, but the MediaWiki API is
not, so this pulls raw article text into `captures/wiki/` (git-ignored). The
distilled version lives in `docs/LORE.md`; this script exists so that document
can be refreshed instead of retyped.

Usage:
  python3 tools/fetch_wiki_lore.py
  python3 tools/fetch_wiki_lore.py --out /tmp/wiki --titles Somulo,Arma
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://ghostsngoblins.fandom.com/api.php"
TITLES = [
    "Demon's Crest", "Arma", "Firebrand", "Dark Demon", "Grewon", "Flame Lord",
    "Ovnunu", "Hippogriff", "The Black Lotus", "The Wise Man", "Trio the Pago",
    "Phalanx", "Vagrant", "Malwous", "Somulo",
]


def fetch(title: str) -> str | None:
    query = urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "rvprop": "content",
        "rvslots": "main", "titles": title, "format": "json",
        "formatversion": "2", "redirects": "1",
    })
    req = urllib.request.Request(f"{API}?{query}",
                                 headers={"User-Agent": "Mozilla/5.0 (dc-port-docs)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    pages = data.get("query", {}).get("pages", [])
    if not pages or "missing" in pages[0]:
        return None
    return pages[0]["revisions"][0]["slots"]["main"]["content"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "wiki")
    ap.add_argument("--titles", default="", help="comma-separated; default is the full set")
    args = ap.parse_args()

    titles = ([t.strip() for t in args.titles.split(",") if t.strip()]
              if args.titles else TITLES)
    args.out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for title in titles:
        text = fetch(title)
        if text is None:
            print(f"missing: {title}")
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", title) + ".wiki"
        (args.out / name).write_text(text, encoding="utf-8")
        ok += 1
        print(f"{title}: {len(text)} chars -> {name}")
    print(f"fetched {ok}/{len(titles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
