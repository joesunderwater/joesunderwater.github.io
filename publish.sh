#!/usr/bin/env bash
# Commit and push the current tree to origin/main only if something changed.
# Does not rebuild the site; run ./update.sh first.
#
# Usage:
#   ./publish.sh
#   ./publish.sh "Add 20 pin articles for 2026-11-11 and rebuild site"
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .git ]]; then
  echo "ERROR: this directory is not a git repository." >&2
  exit 1
fi

git add -A
if git diff --cached --quiet && git diff --quiet; then
  echo "Nothing to publish (working tree clean)."
  exit 0
fi

# If add -A staged nothing (all ignored) and worktree is clean except untracked ignored:
if git diff --cached --quiet; then
  echo "Nothing to publish (no staged changes)."
  exit 0
fi

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  DATE=$(date +%F)
  MSG="Update Joe Hartmann Finds site (${DATE})"
fi

git commit -m "$MSG"

# Rebase onto remote main so a concurrent daily publish is not overwritten.
if ! git pull --rebase origin main; then
  echo "ERROR: git pull --rebase failed. The commit is local; not pushing." >&2
  exit 1
fi

git push origin HEAD:main
echo "Published to origin/main."

# Notify IndexNow of page URLs in the commit just pushed. Never fail the publish.
if python3 scripts/indexnow_ping.py; then
  :
else
  echo "WARNING: IndexNow ping failed; the site was still published." >&2
fi
