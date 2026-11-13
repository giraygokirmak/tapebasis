#!/usr/bin/env bash
# Mirror docs/wiki/*.md into the repository's GitHub wiki.
#
# The wiki is a separate git repository (<repo>.wiki.git) that GitHub only
# creates after the *first* page exists. There is no API to create it, so the
# one-time bootstrap is manual:
#
#   1. Open https://github.com/giraygokirmak/tapebasis/wiki
#   2. Choose "Create the first page", save anything (this script overwrites it)
#
# After that this script is idempotent: it clones, replaces the pages, and
# pushes. Docs are authored in docs/wiki/ with wiki-style links (Home
# Getting-Started, ...), so the same bytes work in both places.
#
# Usage: scripts/publish-wiki.sh [--dry-run]
set -euo pipefail

REPO="giraygokirmak/tapebasis"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs/wiki"
WORK="$(mktemp -d)"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

if [[ ! -d "$SRC" ]]; then
    echo "error: $SRC not found, run this from the repository" >&2
    exit 1
fi

echo "==> cloning wiki"
if ! git clone -q "https://github.com/${REPO}.wiki.git" "$WORK/wiki" 2>/dev/null; then
    cat >&2 <<'EOF'
error: the wiki repository does not exist yet.

GitHub creates it only once a first page has been added in the web UI:
  https://github.com/giraygokirmak/tapebasis/wiki
Choose "Create the first page" and save it, this script overwrites the content.
EOF
    exit 1
fi

echo "==> replacing pages from docs/wiki"
find "$WORK/wiki" -maxdepth 1 -name '*.md' -delete
cp "$SRC"/*.md "$WORK/wiki/"

cd "$WORK/wiki"
git add -A
if git diff --cached --quiet; then
    echo "==> wiki already up to date"
    exit 0
fi

git -c user.name="Macit Giray Gökırmak" \
    -c user.email="giray@gokirmak.gen.tr" \
    commit -q -m "Sync wiki from docs/wiki"

if (( DRY_RUN )); then
    echo "==> dry run; would push:"
    git show --stat --oneline HEAD
    exit 0
fi

echo "==> pushing"
git push -q origin HEAD
echo "==> done: https://github.com/${REPO}/wiki"
