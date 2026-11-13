"""Git child repositories must not inherit a parent hook's repository bindings."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL_VARIABLES = subprocess.run(
    ["git", "rev-parse", "--local-env-vars"], cwd=ROOT,
    capture_output=True, text=True, check=True,
).stdout.split()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git using only the fixture's repository and user configuration."""
    environment = {key: value for key, value in os.environ.items() if key not in LOCAL_VARIABLES}
    environment.update({
        "HOME": str(root),
        "XDG_CONFIG_HOME": str(root / "config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    })
    return subprocess.run(
        ["git", *args], cwd=root, env=environment,
        check=True, capture_output=True, text=True,
    )


def _pre_push_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return a linked source worktree, two remotes, and the real pre-push hook."""
    source = tmp_path / "source"
    scripts = source / "scripts"
    docs = source / "docs/wiki"
    scripts.mkdir(parents=True)
    docs.mkdir(parents=True)
    for name in ("publish-wiki.sh", "quality-gate.sh"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    # This routing test substitutes only the project test and documentation
    # interpreter. The real gate, hook, wiki publisher and Git writes run intact.
    probe = scripts / "no-network-check"
    probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    probe.chmod(0o755)
    (docs / "Home.md").write_text("fixture wiki\n", encoding="utf-8")
    _git(source, "init")
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "source")

    main = tmp_path / "main"
    wiki = tmp_path / "wiki"
    _git(tmp_path, "clone", "--bare", str(source), str(main))
    _git(tmp_path, "init", "--bare", str(wiki))
    linked = tmp_path / "linked"
    _git(source, "worktree", "add", "-q", "-b", "linked", str(linked))
    shutil.copy2(ROOT / ".githooks/pre-push", linked / "checked-pre-push")

    wrapper = tmp_path / "run-pre-push"
    wrapper.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        'export TAPEBASIS_WIKI_REPOSITORY="$TARGET_WIKI"\n'
        'export TAPEBASIS_PYTHON="$PWD/scripts/no-network-check"\n'
        'exec "$CHECKED_PRE_PUSH"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return linked, main, wiki, wrapper


def test_parent_push_environment_cannot_rewrite_source_or_wiki_refs(tmp_path, monkeypatch):
    """A nested wiki push changes only the wiki and the linked worktree's sync stamp."""
    source, main, wiki, wrapper = _pre_push_fixture(tmp_path)
    original = _git(main, "rev-parse", "HEAD").stdout.strip()
    git_dir = Path(_git(source, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (source / ".git").is_file()
    monkeypatch.setenv("GIT_DIR", str(git_dir))
    monkeypatch.setenv("GIT_WORK_TREE", str(source))
    monkeypatch.setenv("GIT_INDEX_FILE", str(git_dir / "index"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(git_dir.parent / "no-hooks"))
    monkeypatch.setenv("CHECKED_PRE_PUSH", str(source / "checked-pre-push"))
    monkeypatch.setenv("TARGET_WIKI", str(wiki))
    result = subprocess.run(
        [str(wrapper)], cwd=source,
        input=f"refs/heads/main {original} refs/heads/main {'0' * 40}\n",
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(source, "rev-parse", "HEAD").stdout.strip() == original
    assert _git(main, "rev-parse", "HEAD").stdout.strip() == original
    source_paths = set(_git(source, "ls-tree", "-r", "--name-only", original).stdout.splitlines())
    assert {"docs/wiki/Home.md", "scripts/publish-wiki.sh", "scripts/quality-gate.sh"} <= source_paths
    assert not any(path.startswith("src/") for path in source_paths)
    assert "Home.md" not in source_paths
    published = _git(wiki, "for-each-ref", "--format=%(refname)").stdout.splitlines()
    assert len(published) == 1
    published_ref = published[0]
    published_commit = _git(wiki, "rev-parse", published_ref).stdout.strip()
    assert published_commit != original
    assert _git(wiki, "ls-tree", "-r", "--name-only", published_ref).stdout.splitlines() == [
        "Home.md"
    ]
    assert _git(wiki, "show", f"{published_ref}:Home.md").stdout == "fixture wiki\n"
    wiki_tree = _git(source, "rev-parse", "HEAD:docs/wiki").stdout.strip()
    assert (git_dir / "tapebasis-wiki-sync").read_text(encoding="utf-8") == wiki_tree
    assert _git(source, "status", "--porcelain").stdout.splitlines() == ["?? checked-pre-push"]
