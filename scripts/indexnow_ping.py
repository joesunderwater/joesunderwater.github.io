#!/usr/bin/env python3
"""Notify IndexNow of page URLs changed in the latest git commit.

Fails softly: print a warning and exit 1 on errors so publish.sh can
continue after a successful push. Exit 0 if there is nothing to send
or the request is accepted.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENDPOINT = "https://api.indexnow.org/indexnow"


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["base_url"] = (cfg.get("base_url") or "").rstrip("/")
    cfg["base_path"] = (cfg.get("base_path") or "").rstrip("/")
    return cfg


def changed_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=ROOT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"IndexNow: could not list changed files ({exc})", file=sys.stderr)
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def file_to_url(cfg: dict, rel: str) -> str | None:
    """Map a repo path under docs/ to its public URL."""
    path = rel.replace("\\", "/")
    prefix = (cfg.get("output_dir") or "docs").rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    if rest.endswith(".txt") and rest[:-4] == (cfg.get("indexnow_key") or ""):
        return None
    if rest in {".nojekyll", "CNAME", "robots.txt", "favicon.svg"}:
        return None
    if rest.endswith(".xml"):
        return f"{cfg['base_url']}{cfg['base_path']}/{rest}"
    if rest.endswith("/index.html"):
        rest = rest[: -len("index.html")]
    elif rest == "index.html":
        rest = ""
    elif rest.endswith(".html"):
        rest = rest[: -len(".html")] + "/"
    else:
        # Images, CSS, icons: skip. IndexNow is for pages.
        return None
    if rest and not rest.startswith("/"):
        rest = "/" + rest
    if rest and not rest.endswith("/"):
        rest += "/"
    if not rest:
        rest = "/"
    return f"{cfg['base_url']}{cfg['base_path']}{rest}"


def main() -> int:
    cfg = load_config()
    key = (cfg.get("indexnow_key") or "").strip()
    if not key:
        print("IndexNow: no indexnow_key in config.json; skipping.")
        return 0
    if not cfg.get("base_url"):
        print("IndexNow: no base_url in config.json; skipping.")
        return 0

    urls = []
    seen = set()
    for rel in changed_files():
        url = file_to_url(cfg, rel)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        print("IndexNow: no page URLs changed; skipping.")
        return 0

    host = cfg["base_url"].split("://", 1)[-1].split("/", 1)[0]
    key_location = f"{cfg['base_url']}{cfg['base_path']}/{key}.txt"
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.getcode()
            body = resp.read()[:200]
    except urllib.error.HTTPError as exc:
        print(
            f"IndexNow: HTTP {exc.code} from api.indexnow.org ({len(urls)} URL(s)).",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — fail softly, any network/error
        print(f"IndexNow: request failed ({exc}).", file=sys.stderr)
        return 1

    if status >= 200 and status < 300:
        print(f"IndexNow: accepted {len(urls)} URL(s) (HTTP {status}).")
        return 0
    print(f"IndexNow: unexpected HTTP {status} ({body!r}).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
