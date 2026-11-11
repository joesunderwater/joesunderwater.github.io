#!/usr/bin/env python3
"""List pins in pins.json that do not yet have a content/<id>.md file.

Prints a human-readable briefing and writes build/new-pins.json for batch
article writing (20–200 pins at a time).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from generate import load_config, load_pins, load_articles, slugify  # noqa: E402


def main() -> int:
    cfg = load_config()
    pins_path = Path(cfg["pins_json"])
    if not pins_path.is_file():
        print(f"ERROR: pins.json not found at {pins_path}", file=sys.stderr)
        return 1
    pins = load_pins(pins_path)
    articles = load_articles(ROOT / cfg.get("content_dir", "content"))
    known = set(articles)
    new_pins = [p for p in pins if p.get("id") not in known]
    stale = sorted(known - {p.get("id") for p in pins})

    out_dir = ROOT / "build"
    out_dir.mkdir(exist_ok=True)
    briefing = {
        "new_count": len(new_pins),
        "existing_count": len(known),
        "total_pins": len(pins),
        "stale_content_ids": stale,
        "pins": new_pins,
        "instructions": (
            "Write one content/<id>.md file per pin in the pins array. "
            "Follow content/_template.md and the article rules in README.md. "
            "Research each product by ASIN/product_name before writing. "
            "Do not invent specs, prices, ratings, reviews, or testimonials. "
            "Do not overwrite existing content files. Then run ./update.sh or python3 generate.py."
        ),
    }
    (out_dir / "new-pins.json").write_text(
        json.dumps(briefing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Pins in source: {len(pins)}")
    print(f"Articles already written: {len(known)}")
    print(f"New pins needing articles: {len(new_pins)}")
    if stale:
        print(f"Content files with no matching pin (left as-is): {', '.join(stale)}")
    if not new_pins:
        print("Nothing new to write.")
        return 0
    print("\nNew pins:")
    for p in new_pins:
        suggested = slugify(p.get("product_name") or p.get("title") or p["id"])
        print(
            f"  - {p['id']}: {p.get('product_name')} "
            f"(ASIN {p.get('asin')}, board={p.get('board')}, "
            f"suggested slug={suggested})"
        )
    print(f"\nBriefing written to {out_dir / 'new-pins.json'}")
    print("Write content/<id>.md for each, using content/_template.md, then rebuild.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
