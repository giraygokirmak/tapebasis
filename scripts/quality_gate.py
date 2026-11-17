"""Repository invariants that the quality gate enforces.

Every check is pure and returns a list of human-readable failures. The plugin
runs this file in a child process so a broken import cannot take the gate down.

Exit status is 0 when every check passes, 1 otherwise. The machine-readable
report is always printed to stdout as JSON.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = "scripts/quality_gate_baseline.json"
EM_DASH = "\u2014"
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
TEXT_SUFFIXES = {"", ".md", ".py", ".toml", ".json", ".yml", ".yaml", ".sh", ".example", ".txt"}
DOC_FILES = ("README.md", "NOTICE", "docs/")


def _text_files():
    """Yield every tracked text file with its contents, skipping build output.

    The list comes from git rather than from walking the tree, so a generated
    or ignored artifact cannot fail a check that only speaks about the
    repository's own files. Untracked files that a commit would carry are
    included, because the commit is what the gate judges. A directory that is
    not a git checkout falls back to a plain walk.
    """
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    if listed.returncode == 0:
        candidates = [ROOT / relative for relative in listed.stdout.splitlines() if relative]
    else:
        candidates = sorted(ROOT.rglob("*"))
    for path in candidates:
        relative = path.relative_to(ROOT)
        if SKIP_PARTS & set(relative.parts) or not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def _own_functions():
    """Yield (relative path, node) for our code, skipping the vendored providers."""
    for path in sorted((ROOT / "src" / "tapebasis").rglob("*.py")):
        relative = path.relative_to(ROOT / "src" / "tapebasis")
        if "providers" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield relative.as_posix(), node
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield relative.as_posix(), item


def _undocumented() -> list[tuple[str, ast.AST]]:
    """Yield (relative path, node) for every function without a docstring."""
    return [(relative, node) for relative, node in _own_functions() if not ast.get_docstring(node)]


def undocumented_functions() -> list[str]:
    """Functions that carry no docstring and are not in the frozen baseline.

    The baseline records the debt that predates this gate, mostly in the older
    access layer. A function that is undocumented and absent from the baseline
    is new debt and blocks the commit, so every function written from now on
    arrives documented. Paying the baseline down only ever shrinks it.
    """
    recorded = set(json.loads((ROOT / BASELINE).read_text(encoding="utf-8"))["undocumented"])
    failures = []
    for relative, node in _undocumented():
        if f"{relative}::{node.name}" in recorded:
            continue
        failures.append(f"{relative}:{node.lineno} {node.name} has no docstring")
    return failures


def stale_baseline() -> list[str]:
    """Baseline entries that no longer describe the tree, so the baseline cannot rot."""
    recorded = set(json.loads((ROOT / BASELINE).read_text(encoding="utf-8"))["undocumented"])
    current = {f"{relative}::{node.name}" for relative, node in _undocumented()}
    failures = []
    for key in sorted(recorded - current):
        relative, _, name = key.partition("::")
        failures.append(f"{relative}: {name} is documented now, remove it from {BASELINE}")
    return failures


def em_dash() -> list[str]:
    """The repository forbids the em dash in prose and free text."""
    failures = []
    for path, text in _text_files():
        if EM_DASH not in text:
            continue
        line = text[: text.index(EM_DASH)].count("\n") + 1
        failures.append(f"{path.relative_to(ROOT)}:{line}")
    return failures


def _slug(heading: str) -> str:
    """Turn a Markdown heading into the anchor a wiki link would use."""
    slug = heading.strip().lstrip("#").strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    return re.sub(r"\s+", "-", slug)


def wiki_links() -> list[str]:
    """Every relative wiki link resolves to a page, and every fragment to a heading."""
    wiki = ROOT / "docs" / "wiki"
    pages = {page.stem: page for page in wiki.glob("*.md")}
    anchors = {
        stem: {_slug(line) for line in page.read_text(encoding="utf-8").splitlines() if line.startswith("#")}
        for stem, page in pages.items()
    }
    failures = []
    for page in sorted(wiki.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)\s]+)\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
                continue
            path_part, _, fragment = target.partition("#")
            stem = path_part[:-3] if path_part.endswith(".md") else path_part
            if "/" in stem:
                continue
            if stem not in pages:
                failures.append(f"docs/wiki/{page.name} -> {target}: no such page")
            elif fragment and fragment not in anchors[stem]:
                failures.append(f"docs/wiki/{page.name} -> {target}: no such heading")
    return failures


def _tool_names() -> list[str]:
    """Import the server in a child process and return its registered tool names."""
    code = (
        "import asyncio, json\n"
        "from tapebasis.server import mcp\n"
        "print(json.dumps(sorted(t.name for t in asyncio.run(mcp.list_tools()))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        tail = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise RuntimeError(tail)
    return json.loads(result.stdout)


def tool_coverage() -> list[str]:
    """Every registered MCP tool is named in the README and in the Tools Reference."""
    try:
        names = _tool_names()
    except (RuntimeError, json.JSONDecodeError) as exc:
        return [f"the tool surface failed to import: {exc}"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs" / "wiki" / "Tools-Reference.md").read_text(encoding="utf-8")
    failures = [f"README.md does not name `{name}`" for name in names if f"`{name}`" not in readme]
    failures += [
        f"Tools-Reference.md does not name `{name}`"
        for name in names
        if f"`{name}`" not in reference
    ]
    return failures


def tool_count() -> list[str]:
    """Every advertised tool count matches the registered surface."""
    try:
        count = len(_tool_names())
    except (RuntimeError, json.JSONDecodeError):
        return ["the tool count is unavailable"]
    failures = []
    for relative in (
        "README.md",
        "docs/wiki/Home.md",
        "docs/wiki/Getting-Started.md",
        "docs/wiki/Tools-Reference.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for match in re.finditer(r"(\d+)\s+(?:\w+\s+){0,2}tools\b", text):
            if int(match.group(1)) != count:
                failures.append(f"{relative}: says {match.group(1)} tools, the surface has {count}")
    return failures


def _git(*args: str) -> list[str]:
    """Run a git command and return its non-empty output lines."""
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _pending_paths() -> list[str]:
    """The files a commit would carry: the index when it has content, else the tree."""
    staged = _git("diff", "--cached", "--name-only")
    if staged:
        return staged
    return _git("diff", "--name-only") + _git("ls-files", "--others", "--exclude-standard")


def _signature(node: ast.AST) -> str:
    """Render a function or class node as a stable one-line signature."""
    arguments = getattr(node, "args", None)
    if arguments is None:
        return f"class {node.name}"
    names = [arg.arg for arg in (*arguments.posonlyargs, *arguments.args)]
    names += [f"*{arg.arg}" for arg in arguments.kwonlyargs]
    return f"{node.name}({', '.join(names)})"


def _public_surface(source: str) -> set[str]:
    """The public definitions a module exposes, as signature strings."""
    tree = ast.parse(source)
    surface: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                surface.add(_signature(node))
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_"):
                        surface.add(f"{node.name}.{_signature(item)}")
    return surface


def doc_with_code() -> list[str]:
    """A change to a module's public surface carries a documentation change.

    The rule is one batch: the commit that changes the contract is the commit
    that updates it. Only the public surface counts, so an internal refactor, a
    docstring rewrite or a bug fix inside a body does not demand a docs edit,
    while a new or reshaped function does.
    """
    pending = _pending_paths()
    if not pending:
        return []
    documentation = [path for path in pending if path.startswith(DOC_FILES)]
    if documentation:
        return []
    failures = []
    head_exists = bool(_git("rev-parse", "--verify", "HEAD"))
    for relative in pending:
        if not relative.startswith("src/") or not relative.endswith(".py"):
            continue
        if not head_exists:
            continue
        if not (ROOT / relative).exists():
            # A deleted module has no current surface to compare, and removing
            # code never needs a documentation change. The deletion itself is
            # judged by the documentation sweep, not by this check.
            continue
        tracked = _git("ls-tree", "--name-only", "HEAD", "--", relative)
        if not tracked:
            # A brand-new module has no previous surface to change; its functions
            # are covered by the docstring check.
            continue
        current = (ROOT / relative).read_text(encoding="utf-8")
        previous = "\n".join(_git("show", f"HEAD:{relative}"))
        try:
            changed = _public_surface(current) != _public_surface(previous)
        except SyntaxError:
            changed = True
        if changed:
            failures.append(
                f"{relative} changes a public signature with no documentation in the "
                "same batch: add the matching edit under docs/ or README.md"
            )
    return failures


CHECKS = {
    "undocumented": ("each new function carries a docstring", undocumented_functions),
    "stale-baseline": ("the documentation baseline only shrinks", stale_baseline),
    "em-dash": ("no em dash in tracked text", em_dash),
    "wiki-links": ("relative wiki links and fragments resolve", wiki_links),
    "doc-with-code": ("code and its documentation land in one batch", doc_with_code),
    "tool-coverage": ("every tool is named in the README and the Tools Reference", tool_coverage),
    "tool-count": ("advertised tool counts match the surface", tool_count),
}

if __name__ == "__main__":
    report = {name: check() for name, (_, check) in CHECKS.items()}
    print(json.dumps(report, indent=2))
    sys.exit(0 if not any(report.values()) else 1)
