#!/usr/bin/env bash
# Incremental update: detect new pins, remind the operator to write articles,
# rebuild the static site into docs/, and optionally publish to GitHub Pages.
#
# Daily run (after new pins land in pins.json, usually after ~10:30 AM Pacific):
#   ./update.sh              # list new pins, then rebuild whatever articles exist
#   # If new pins were listed, write content/<id>.md for each (see README.md), then:
#   ./update.sh --build-only
#   ./publish.sh             # git add/commit/push only if something changed
#
# Other usage:
#   ./update.sh --build-only # skip the new-pin briefing, just rebuild
#   ./update.sh --check      # list new pins only, do not rebuild
#   ./update.sh --publish    # rebuild (with briefing), then ./publish.sh
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-}"

if [[ "$MODE" != "--build-only" ]]; then
  python3 scripts/list_new_pins.py
  NEW_COUNT=$(python3 -c "import json; print(json.load(open('build/new-pins.json'))['new_count'])" 2>/dev/null || echo 0)
  if [[ "$NEW_COUNT" != "0" ]]; then
    echo
    echo ">>> $NEW_COUNT pin(s) still need content/<id>.md article files."
    echo ">>> Write them now (see README.md and content/_template.md), then rerun ./update.sh --build-only && ./publish.sh."
    echo ">>> Rebuilding the pages that already have articles..."
  fi
fi

if [[ "$MODE" == "--check" ]]; then
  exit 0
fi

python3 generate.py
echo "Done. Preview with: python3 -m http.server --directory docs 8765"
echo "When the tree looks right, publish with: ./publish.sh"

if [[ "$MODE" == "--publish" ]]; then
  echo
  ./publish.sh
fi
