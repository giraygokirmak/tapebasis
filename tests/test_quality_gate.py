"""Tests for the quality gate's documentation checks.

The gate is the only thing standing between a green tree and a commit, so its
own checks are tested the same way the provider code is: hermetically, against
a temporary repository, with no network and no dependency on this checkout.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "quality_gate.py"
ROOT = SCRIPT.parents[1]


@pytest.fixture()
def gate():
    """Load the gate script as a module so its checks can be pointed at a temp root."""
    spec = importlib.util.spec_from_file_location("quality_gate_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def tree(tmp_path, gate, monkeypatch):
    """A minimal repository-shaped tree with a frozen baseline."""
    (tree_dir := tmp_path / "repo").mkdir()
    for relative in ("src/tapebasis", "docs/wiki", "scripts"):
        (tree_dir / relative).mkdir(parents=True)
    (tree_dir / "scripts" / "quality_gate_baseline.json").write_text(
        '{"undocumented": []}', encoding="utf-8"
    )
    monkeypatch.setattr(gate, "ROOT", tree_dir)
    return tree_dir


def _git(directory: pathlib.Path, *args: str) -> None:
    subprocess.run(
        # These fixtures are independent repositories, never children of this checkout's hook.
        ["git", "-c", f"core.hooksPath={directory / 'no-repository-hooks'}", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "XDG_CONFIG_HOME": str(directory / "config"),
            "PATH": "/usr/bin:/bin",
            "HOME": str(directory),
        },
    )


def test_em_dash_is_reported_with_its_line(tree, gate):
    page = tree / "docs" / "wiki" / "Home.md"
    page.write_text("first line\nsecond \u2014 line\n", encoding="utf-8")
    assert gate.em_dash() == ["docs/wiki/Home.md:2"]


def test_em_dash_passes_on_clean_text(tree, gate):
    (tree / "docs" / "wiki" / "Home.md").write_text("plain prose\n", encoding="utf-8")
    assert gate.em_dash() == []


def test_em_dash_ignores_a_file_git_does_not_track(tree, gate):
    (tree / ".gitignore").write_text("build/\n", encoding="utf-8")
    (tree / "build").mkdir()
    (tree / "build" / "generated.md").write_text("stale \u2014 artifact\n", encoding="utf-8")
    _git(tree, "init")
    assert gate.em_dash() == []


def test_undocumented_function_outside_the_baseline_fails(tree, gate):
    module = tree / "src" / "tapebasis" / "fresh.py"
    module.write_text("def documented():\n    \"\"\"Say what it does.\"\"\"\n", encoding="utf-8")
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\n\ndef bare(value):\n    return value\n",
        encoding="utf-8",
    )
    failures = gate.undocumented_functions()
    assert len(failures) == 1
    assert "bare has no docstring" in failures[0]


def test_baseline_records_known_debt(tree, gate):
    (tree / "src" / "tapebasis" / "old.py").write_text("def bare():\n    return 1\n", encoding="utf-8")
    baseline = tree / "scripts" / "quality_gate_baseline.json"
    baseline.write_text('{"undocumented": ["old.py::bare"]}', encoding="utf-8")
    assert gate.undocumented_functions() == []
    assert gate.stale_baseline() == []


def test_stale_baseline_is_reported_once_the_function_is_documented(tree, gate):
    (tree / "src" / "tapebasis" / "old.py").write_text(
        'def bare():\n    """Documented now."""\n', encoding="utf-8"
    )
    baseline = tree / "scripts" / "quality_gate_baseline.json"
    baseline.write_text('{"undocumented": ["old.py::bare"]}', encoding="utf-8")
    failures = gate.stale_baseline()
    assert failures == ["old.py: bare is documented now, remove it from scripts/quality_gate_baseline.json"]


def test_vendored_provider_code_is_exempt(tree, gate):
    vendored = tree / "src" / "tapebasis" / "providers" / "finviz"
    vendored.mkdir(parents=True)
    (vendored / "client.py").write_text("def bare():\n    return 1\n", encoding="utf-8")
    assert gate.undocumented_functions() == []


def test_wiki_link_to_a_missing_page_fails(tree, gate):
    (tree / "docs" / "wiki" / "Home.md").write_text("See [Gone](Gone).\n", encoding="utf-8")
    failures = gate.wiki_links()
    assert failures == ["docs/wiki/Home.md -> Gone: no such page"]


def test_wiki_fragment_must_exist(tree, gate):
    (tree / "docs" / "wiki" / "Home.md").write_text("See [D](Development#nope).\n", encoding="utf-8")
    (tree / "docs" / "wiki" / "Development.md").write_text("## Choosing a tolerance\n", encoding="utf-8")
    failures = gate.wiki_links()
    assert failures == ["docs/wiki/Home.md -> Development#nope: no such heading"]


def test_wiki_fragment_resolves_to_a_heading(tree, gate):
    (tree / "docs" / "wiki" / "Home.md").write_text(
        "See [D](Development#choosing-a-tolerance).\n", encoding="utf-8"
    )
    (tree / "docs" / "wiki" / "Development.md").write_text("## Choosing a tolerance\n", encoding="utf-8")
    assert gate.wiki_links() == []


def test_public_surface_reads_signatures():
    spec = importlib.util.spec_from_file_location("quality_gate_signatures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    source = (
        "def public(a, b=1):\n    pass\n"
        "def _private():\n    pass\n"
        "class Box:\n"
        "    def open(self):\n        pass\n"
    )
    assert module._public_surface(source) == {"public(a, b)", "class Box", "Box.open(self)"}


def test_doc_with_code_ignores_a_body_only_change(tree, gate):
    module = tree / "src" / "tapebasis" / "mod.py"
    module.write_text('def public(value):\n    """Doc."""\n    return value\n', encoding="utf-8")
    _git(tree, "init")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", "base")
    module.write_text(
        'def public(value):\n    """Doc."""\n    return value or None\n', encoding="utf-8"
    )
    assert gate.doc_with_code() == []


def test_doc_with_code_requires_documentation_for_a_new_signature(tree, gate):
    module = tree / "src" / "tapebasis" / "mod.py"
    module.write_text('def public(value):\n    """Doc."""\n    return value\n', encoding="utf-8")
    _git(tree, "init")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", "base")
    module.write_text(
        'def public(value, extra):\n    """Doc."""\n    return value\n', encoding="utf-8"
    )
    failures = gate.doc_with_code()
    assert failures == [
        "src/tapebasis/mod.py changes a public signature with no documentation in the "
        "same batch: add the matching edit under docs/ or README.md"
    ]


@pytest.mark.parametrize("parent_binding", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_git_checks_ignore_a_parent_repository_binding(tree, gate, monkeypatch, parent_binding):
    """A stored fixture commit stays in its own repository during a parent git hook."""
    module = tree / "src" / "tapebasis" / "mod.py"
    module.write_text('def public(value):\n    """Doc."""\n    return value\n', encoding="utf-8")
    _git(tree, "init")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", "base")
    module.write_text(
        'def public(value, extra):\n    """Doc."""\n    return value\n', encoding="utf-8"
    )
    (tree / "docs" / "wiki" / "Development.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.setenv(parent_binding, str(ROOT / ".git" / "missing-parent-binding"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Parent repository")
    assert gate.doc_with_code() == []
    assert list(gate._text_files())


def test_doc_with_code_accepts_a_batch_that_carries_docs(tree, gate):
    module = tree / "src" / "tapebasis" / "mod.py"
    module.write_text('def public(value):\n    """Doc."""\n    return value\n', encoding="utf-8")
    _git(tree, "init")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", "base")
    module.write_text(
        'def public(value, extra):\n    """Doc."""\n    return value\n', encoding="utf-8"
    )
    (tree / "docs" / "wiki" / "Development.md").write_text("## Public surface\n", encoding="utf-8")
    assert gate.doc_with_code() == []


def test_tool_count_flags_a_stale_advertisement(tree, gate, monkeypatch):
    monkeypatch.setattr(gate, "_tool_names", lambda: ["a", "b", "c"])
    (tree / "README.md").write_text("All 3 tools.\n", encoding="utf-8")
    (tree / "docs" / "wiki" / "Home.md").write_text("All 4 tools, every provider.\n", encoding="utf-8")
    (tree / "docs" / "wiki" / "Getting-Started.md").write_text("3 tools.\n", encoding="utf-8")
    (tree / "docs" / "wiki" / "Tools-Reference.md").write_text("3 tools.\n", encoding="utf-8")
    failures = gate.tool_count()
    assert failures == ["docs/wiki/Home.md: says 4 tools, the surface has 3"]


def test_tool_coverage_flags_a_tool_missing_from_the_contract(tree, gate, monkeypatch):
    monkeypatch.setattr(gate, "_tool_names", lambda: ["stock_quote", "market_snapshot"])
    (tree / "README.md").write_text("`stock_quote`\n", encoding="utf-8")
    (tree / "docs" / "wiki" / "Tools-Reference.md").write_text("`stock_quote`\n", encoding="utf-8")
    failures = gate.tool_coverage()
    assert failures == [
        "README.md does not name `market_snapshot`",
        "Tools-Reference.md does not name `market_snapshot`",
    ]


def test_every_check_is_a_described_callable(gate):
    for name, (description, check) in gate.CHECKS.items():
        assert name == name.lower()
        assert description
        assert callable(check)
