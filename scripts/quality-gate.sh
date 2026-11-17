#!/usr/bin/env bash
# Run every check the quality gate enforces, in the order a command needs them.
#
# This is the single entry point shared by the OpenCode plugin, the git hooks,
# CI and a human at the terminal, so all four agree on what "green" means.
#
# A commit is judged on the working tree: tests, then documentation.
# A push is the moment the result becomes public, so it also mirrors docs/wiki
# into the wiki repository. The mirror is skipped while docs/wiki is unchanged
# since the last successful sync, so a push does not pay for a network round
# trip it does not need.
#
# Exit 0 when the command may proceed. Exit 1 and print a report otherwise.
#
# Usage: scripts/quality-gate.sh [--commit|--push|--tests-only|--docs-only|--wiki-only]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The interpreter that owns the project's dependencies. A gate that runs under
# the wrong interpreter fails for reasons unrelated to the code, so it says so
# instead of reporting a red tree. The project's own environment wins; failing
# that, the last resort is any interpreter on PATH that can already import
# pytest, which is what a container or a system install looks like.
if [[ -n "${TAPEBASIS_PYTHON:-}" ]]; then
    PYTHON="$TAPEBASIS_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
    PYTHON="$ROOT/venv/bin/python"
else
    PYTHON=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c "import pytest" >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
    PYTHON="${PYTHON:-python3}"
fi

if ! "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
    echo "error: $PYTHON cannot import pytest." >&2
    echo "Create the environment from docs/wiki/Development.md or set TAPEBASIS_PYTHON." >&2
    exit 1
fi

mode="${1:-}"
status=0
run_tests=1
run_docs=1
run_wiki=0

case "$mode" in
    --tests-only) run_docs=0 ;;
    --docs-only)  run_tests=0 ;;
    --wiki-only)  run_tests=0; run_docs=0; run_wiki=1 ;;
    --push)       run_wiki=1 ;;
    --commit|"")  ;;
    *)
        echo "error: unknown mode '$mode'" >&2
        exit 2
        ;;
esac

if (( run_tests )); then
    echo "== tests =="
    if ! "$PYTHON" -m pytest -q; then
        status=1
    fi
fi

if (( run_docs )); then
    echo "== documentation =="
    if ! "$PYTHON" scripts/quality_gate.py; then
        status=1
    fi
fi

if (( run_wiki )); then
    echo "== wiki =="
    # An uncommitted page cannot be published on its own: the wiki would then
    # describe a state the repository does not have.
    if [[ -n "$(git status --porcelain -- docs/wiki)" ]]; then
        echo "docs/wiki has uncommitted edits; commit them before pushing" >&2
        status=1
    else
        stamp_file="$ROOT/.git/tapebasis-wiki-sync"
        current="$(git rev-parse HEAD:docs/wiki 2>/dev/null || echo none)"
        recorded=""
        [[ -f "$stamp_file" ]] && recorded="$(cat "$stamp_file")"
        if [[ "$current" == "$recorded" ]]; then
            echo "docs/wiki unchanged since the last sync ($current)"
        elif ! "$ROOT/scripts/publish-wiki.sh"; then
            echo "error: the wiki mirror failed; run scripts/publish-wiki.sh by hand" >&2
            status=1
        else
            printf '%s' "$current" >"$stamp_file"
        fi
    fi
fi

if (( status != 0 )); then
    echo "== gate: FAILED =="
    exit 1
fi

echo "== gate: OK =="
