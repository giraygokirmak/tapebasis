"""Validate release metadata against isolated and real temporary git checkouts."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_release.py"
VERSION = re.search(
    r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE,
)[1]
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?"


def _load():
    """Load the release checker without importing any provider modules."""
    spec = importlib.util.spec_from_file_location("check_release_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(root: Path, *arguments: str, environment: dict[str, str] | None = None):
    """Run a command in ``root``, optionally with fixture-only environment variables."""
    command = list(arguments)
    executable = command.pop(0)
    return subprocess.run(
        [executable, *command], cwd=root, check=True, capture_output=True, text=True,
        env=environment,
    )


def _git(root: Path, *arguments: str):
    """Run git with no parent repository configuration or host hook recursion."""
    hooks = root / "no-repository-hooks"
    local_variables = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.split()
    environment = {
        key: value for key, value in os.environ.items()
        if key not in local_variables
        and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }
    environment.update({
        "HOME": str(root),
        "XDG_CONFIG_HOME": str(root / "config"),
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    return _run(
        root,
        "git", "-c", f"core.hooksPath={hooks}", *arguments,
        environment=environment,
    )


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    """Copy every release metadata input into a temporary checkout."""
    for name in ("README.md", "pyproject.toml", "package.json", "package-lock.json", "server.json"):
        (tmp_path / name).write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "src/tapebasis").mkdir(parents=True)
    (tmp_path / "src/tapebasis/__init__.py").write_text(
        (ROOT / "src/tapebasis/__init__.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "npm/bin").mkdir(parents=True)
    (tmp_path / "npm/bin/tapebasis.js").write_text("#!/usr/bin/env node\n", encoding="utf-8")
    checker = _load()
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    return tmp_path, checker


@pytest.fixture()
def history(checkout):
    """Return a complete temporary checkout with an older tagged release."""
    root, checker = checkout
    _project_version(root, "0.9.0")
    # A repository-level OpenCode hook must not recurse into these fixture commits.
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Release Tests")
    _git(root, "config", "user.email", "release-tests@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Previous release")
    _git(root, "tag", "v0.9.0")
    return root, checker


def _project_version(root: Path, version: str | None) -> None:
    """Change the temporary checkout version, using ``None`` for an empty TOML string."""
    for relative, key in (("pyproject.toml", "version"), ("src/tapebasis/__init__.py", "__version__")):
        path = root / relative
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
            if line.startswith(f"{key} = "):
                newline = "\n" if line.endswith("\n") else ""
                line = f'{key} = "{version or ""}"{newline}'
            lines.append(line)
        path.write_text("".join(lines), encoding="utf-8")
    if version:
        for relative in ("package.json", "package-lock.json", "server.json"):
            path = root / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            for key, value in _versioned_json(document, version):
                value[key] = version
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _versioned_json(value, version):
    """Yield key/parent pairs for fields holding a release version."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "version" and isinstance(child, str) and re.fullmatch(VERSION_PATTERN, child):
                yield key, value
            else:
                yield from _versioned_json(child, version)
    elif isinstance(value, list):
        for child in value:
            yield from _versioned_json(child, version)


def _checker(root: Path):
    """Return the release checker scoped to one temporary git checkout."""
    checker = _load()
    checker.ROOT = root
    return checker


def test_repo_release_metadata_agrees():
    """The real repository uses one version and correct ownership metadata."""
    assert _checker(ROOT).collect(tag=f"v{VERSION}", against=None) == []


def test_isolated_checkout_agrees(checkout):
    """A complete isolated checkout passes using its declared version."""
    _, checker = checkout
    assert checker.collect(tag=f"v{VERSION}", against=None) == []


@pytest.mark.parametrize("tag", ["v0.0.0", "1.0.0", "v1.0", "v1.0.0/extra", ""])
def test_wrong_or_malformed_tag_fails_before_any_publish(checkout, tag):
    """An invalid or mismatched tag cannot pass metadata validation."""
    _, checker = checkout
    assert checker.collect(tag=tag, against=None)


@pytest.mark.parametrize("filename", ["package.json", "package-lock.json", "server.json"])
def test_malformed_json_is_reported_not_raised(checkout, filename):
    """Invalid distribution JSON yields a readable failure."""
    root, checker = checkout
    (root / filename).write_text("{not json", encoding="utf-8")
    errors = checker.collect(tag=None, against=None)
    assert any(f"{filename}: invalid JSON at line 1" in error for error in errors)


def test_malformed_toml_is_reported_not_raised(checkout):
    """Invalid project TOML yields findings rather than a traceback."""
    root, checker = checkout
    (root / "pyproject.toml").write_text("[project\nbroken", encoding="utf-8")
    assert any("invalid TOML" in error for error in checker.collect(tag=None, against=None))


def test_toml_parser_covers_the_whole_project_and_pre_311_fallback(checkout, monkeypatch):
    """The same complete parser is selected when tomllib is absent."""
    if sys.version_info >= (3, 11):
        import tomllib as parser
    else:
        import tomli as parser

    def hide_tomllib(name, *args, **kwargs):
        """Route Python 3.11 and later through the same compatibility import."""
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        return original_import(name, *args, **kwargs)

    root, checker = checkout
    original_import = __import__
    monkeypatch.setattr("builtins.__import__", hide_tomllib)
    monkeypatch.delitem(sys.modules, "tomllib", raising=False)
    monkeypatch.setitem(sys.modules, "tomli", parser)
    project = checker._project((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["name"] == "tapebasis"
    assert isinstance(project["dependencies"], list)
    assert "tradingview-screener==3.0.0" in project["dependencies"]


def test_missing_files_are_reported_not_raised(checkout):
    """Missing release inputs stop validation without hiding other errors."""
    root, checker = checkout
    for filename in ("package.json", "package-lock.json", "server.json", "README.md"):
        (root / filename).unlink()
    (root / "npm/bin/tapebasis.js").unlink()
    errors = checker.collect(tag=None, against=None)
    assert sum("cannot read" in error for error in errors) == 4
    (root / "package.json").write_text((ROOT / "package.json").read_text(encoding="utf-8"))
    assert any("points at missing" in error for error in checker.collect(tag=None, against=None))


def test_lock_root_must_carry_package_version(checkout):
    """The npm lockfile's root package must match its manifest and Python version."""
    root, checker = checkout
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    lock["packages"][""]["version"] = "0.0.0"
    (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    assert any('packages[""].version' in error for error in checker.collect(tag=None, against=None))


def test_registry_must_name_the_declared_pypi_project(checkout):
    """Registry metadata cannot substitute another Python distribution."""
    root, checker = checkout
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    server["packages"][1]["identifier"] = "some-other-project"
    (root / "server.json").write_text(json.dumps(server), encoding="utf-8")
    assert any("declared packages" in error for error in checker.collect(tag=None, against=None))


def test_registry_markers_must_match_mcp_name(checkout):
    """Registry ownership markers cannot name another MCP server."""
    root, checker = checkout
    (root / "README.md").write_text("<!-- mcp-name: wrong-name -->\n", encoding="utf-8")
    errors = checker.collect(tag=None, against=None)
    assert any("README.md: missing registry marker" in error for error in errors)


@pytest.mark.parametrize("parent_binding", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_historical_version_ignores_a_parent_repository_binding(
    history, monkeypatch, parent_binding,
):
    """The version checker reads its own root even from a parent git hook."""
    root, checker = history
    _project_version(root, "1.0.0")
    monkeypatch.setenv(parent_binding, str(ROOT / ".git" / "missing-parent-binding"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Parent repository")
    assert checker.collect(tag=None, against="v0.9.0") == []


def test_previous_tag_must_be_older(history):
    """An older git tag is accepted, while the same or a newer version is stopped."""
    root, checker = history
    _project_version(root, "1.0.0")
    assert checker.collect(tag=None, against="v0.9.0") == []
    _git(root, "add", "pyproject.toml")
    _git(root, "commit", "-q", "-m", "Current release")
    assert any("unchanged" in error for error in checker.collect(tag=None, against="HEAD"))
    _git(root, "tag", "v1.0.0")
    _project_version(root, "0.8.0")
    assert any("not newer" in error for error in checker.collect(tag=None, against="v1.0.0"))


def test_missing_or_invalid_git_version_never_silently_passes(history):
    """A missing ref, absent version, and malformed version are explicit failures."""
    root, checker = history
    _project_version(root, "1.0.0")
    assert any("cannot read" in error for error in checker.collect(tag=None, against="not-a-ref"))
    _git(root, "tag", "invalid", "v0.9.0")
    _project_version(root, None)
    _git(root, "add", "pyproject.toml")
    _git(root, "commit", "-q", "-m", "Malformed version")
    _git(root, "tag", "bad-version")
    assert any("no project version" in e for e in checker.collect(tag=None, against="bad-version"))
    _project_version(root, "1.0.0")
    _project_version(root, "1.0")
    _git(root, "add", "pyproject.toml")
    _git(root, "commit", "-q", "-m", "Invalid historical version")
    _git(root, "tag", "supported-version")
    _project_version(root, "1.0.0")
    assert any("unsupported project version" in e for e in checker.collect(tag=None, against="supported-version"))


def test_invalid_working_version_never_silently_passes(history):
    """A valid older ref cannot hide an invalid current release version."""
    root, checker = history
    _project_version(root, "1.0")
    errors = checker.collect(tag=None, against="v0.9.0")
    assert any("unsupported release version" in error for error in errors)


def test_missing_uv_metadata_is_not_needed_at_runtime():
    """The project has no uv package-index credentials as runtime requirements."""
    assert "UV_PUBLISH_TOKEN" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_check_release_command_json_and_alternate_root(checkout):
    """The command validates an explicit root and returns structured failures."""
    root, _ = checkout
    result = _run(root, sys.executable, str(SCRIPT), "--json", "--tag", f"v{VERSION}", "--root", str(root))
    assert json.loads(result.stdout) == {"ok": True, "errors": []}
    (root / "server.json").write_text("{}", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--tag", "v0.0.0", "--root", str(root)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["ok"] is False
