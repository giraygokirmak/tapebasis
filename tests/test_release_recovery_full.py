"""Offline tests for release package identity and recovery source verification."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import urllib.error
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    """Load one release helper without importing the application."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    """Supply one finite in-memory response to an offline fixture."""
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size=-1):
        body, self.body = self.body, b""
        return body


def test_pypi_compares_actual_files_and_only_404_means_missing(tmp_path, monkeypatch):
    """Existing PyPI files are downloaded and compared, not trusted by their metadata."""
    bodies = {"tapebasis-1.0.0-py3-none-any.whl": b"wheel", "tapebasis-1.0.0.tar.gz": b"sdist"}
    for name, body in bodies.items():
        (tmp_path / name).write_bytes(body)
    entries = [{"filename": name, "digests": {"sha256": hashlib.sha256(body).hexdigest()}, "url": f"https://files.test/{name}"} for name, body in bodies.items()]
    module = load("release_registry")
    monkeypatch.setattr(module, "_get", lambda url, missing_ok=False: Response({"urls": entries}).body if url.endswith("/json") else bodies[url.rsplit("/", 1)[-1]])
    assert module.check_pypi("tapebasis", "1.0.0", tmp_path) == "verified"
    monkeypatch.setattr(module, "_get", lambda url, missing_ok=False: Response({"urls": entries}).body if url.endswith("/json") else b"different")
    with pytest.raises(module.RegistryError, match="bytes differ"):
        module.check_pypi("tapebasis", "1.0.0", tmp_path)
    monkeypatch.setattr(module, "_get", lambda url, missing_ok=False: None)
    assert module.check_pypi("tapebasis", "1.0.0", tmp_path) == "missing"
    assert module.main(["pypi", "--version", "1.0.0", "--dist", str(tmp_path), "--require-existing"]) == 1


def test_npm_and_mcp_accept_only_verified_content(tmp_path, monkeypatch):
    """Mismatched npm integrity and MCP metadata stop rather than being overwritten."""
    tarball = b"known tarball"
    (tmp_path / "tapebasis-1.0.0.tgz").write_bytes(tarball)
    module = load("release_registry")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: {"version": "1.0.0", "dist": {"integrity": integrity}})
    assert module.check_npm("tapebasis", "1.0.0", tmp_path) == "verified"
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: {"version": "1.0.0", "dist": {"integrity": "sha512-other"}})
    with pytest.raises(module.RegistryError):
        module.check_npm("tapebasis", "1.0.0", tmp_path)
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: None)
    assert module.check_npm("tapebasis", "1.0.0", tmp_path) == "missing"
    assert module.main(["npm", "--version", "1.0.0", "--dist", str(tmp_path), "--require-existing"]) == 1
    server = {"name": "io.github.giraygokirmak/tapebasis", "version": "1.0.0"}
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: {"servers": [{"server": server, "_meta": {"status": "active"}}]})
    assert module.check_mcp(server, "1.0.0") == "verified"
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: {"servers": [{"server": {**server, "title": "different"}}]})
    with pytest.raises(module.RegistryError):
        module.check_mcp(server, "1.0.0")


def test_registry_errors_and_malformed_metadata_stop(monkeypatch):
    """HTTP authorization failures are never interpreted as missing packages."""
    module = load("release_registry")

    def denied(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://pypi.invalid", 403, "denied", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", denied)
    with pytest.raises(module.RegistryError, match="403"):
        module._get("https://pypi.invalid", missing_ok=True)
    with pytest.raises(module.RegistryError):
        module.check_mcp({"name": "wrong", "version": "1.0.0"}, "1.0.0")


def source_fixture():
    """Return the essential successful-source, approved-but-failed publish tuple."""
    run = {"id": 43435266134, "event": "push", "name": "Release", "head_branch": "v1.0.0", "head_sha": "a" * 40, "status": "completed"}
    jobs = [
        {"name": "Validate / test (3.12)", "conclusion": "success", "status": "completed"},
        {"name": "Build release artifacts", "conclusion": "success", "status": "completed"},
        {"name": "Publish 1.0.0", "conclusion": "failure", "status": "completed", "started_at": "2026-11-13T13:49:43Z", "completed_at": "2026-11-13T13:51:40Z"},
    ]
    artifact = {"name": "release-artifacts", "expired": False, "workflow_run": {"id": run["id"]}, "size_in_bytes": 7, "digest": "sha256:" + "b" * 64}
    return run, jobs, artifact


def test_source_requires_original_tag_build_and_started_approval():
    """Wrong tag, expired artifact, unapproved publish, or unrelated run cannot recover."""
    module = load("release_artifact_source")
    run, jobs, artifact = source_fixture()
    module.validate_source(run, jobs, artifact, "1.0.0", "c" * 40)
    for change in ({"head_branch": "main"}, {"head_sha": "c" * 40}, {"event": "workflow_dispatch"}):
        with pytest.raises(module.SourceError):
            module.validate_source({**run, **change}, jobs, artifact, "1.0.0", "c" * 40)
    for change in ({"expired": True}, {"size_in_bytes": 0}, {"digest": "sha256:invalid"}):
        with pytest.raises(module.SourceError):
            module.validate_source(run, jobs, {**artifact, **change}, "1.0.0", "c" * 40)
    for publisher in ({**jobs[-1], "conclusion": "skipped"}, {**jobs[-1], "started_at": None}, {**jobs[-1], "status": "in_progress"}):
        with pytest.raises(module.SourceError):
            module.validate_source(run, jobs[:-1] + [publisher], artifact, "1.0.0", "c" * 40)


def test_download_checks_size_digest_and_redirect_credential_scope(tmp_path, monkeypatch):
    """Damaged or partial ZIPs are removed and Authorization is stripped cross-host."""
    module = load("release_artifact_source")
    artifact = {"size_in_bytes": 7, "digest": "sha256:" + "0" * 64, "archive_download_url": "https://api.github.com/artifact"}
    seen = []
    monkeypatch.setattr(module, "OPENER", type("Opener", (), {"open": lambda self, request, timeout: seen.append(request.headers["Authorization"]) or Response(b"bad zip")})())
    with pytest.raises(module.SourceError, match="digest"):
        module.download(artifact, "test-token", tmp_path / "artifact.zip")
    assert seen == ["Bearer test-token"]
    assert not (tmp_path / "artifact.zip.partial").exists()
    handler = module.SameHostRedirects()
    request = urllib.request.Request("https://api.github.com/artifact", headers={"Authorization": "Bearer test-token"})
    redirect = handler.redirect_request(request, None, 302, "Found", {}, "https://objects.githubusercontent.com/artifact")
    assert not redirect.has_header("Authorization")


def test_extract_rejects_traversal_symlink_and_incomplete_zip(tmp_path):
    """Only the expected regular-file artifact names can be extracted."""
    module = load("release_artifact_source")
    for name in ("../escape", "link"):
        path = tmp_path / f"{name.replace('/', '_')}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(name, b"unsafe")
        with pytest.raises(module.SourceError):
            module.extract(path, tmp_path / (name.replace('/', '_') + "-dist"), "1.0.0")
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    with pytest.raises(module.SourceError, match="incomplete"):
        module.extract(empty, tmp_path / "empty-dist", "1.0.0")


def ghcr_workspace(tmp_path):
    """Prepare a fake regctl and a no-delay sleep for deterministic GHCR tests."""
    workspace = tmp_path / "workspace"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / "dist").mkdir()
    (workspace / "scripts/check_oci_image.py").write_text('print("sha256:" + "a" * 64)\n')
    (workspace / "scripts/verify_ghcr.sh").write_bytes((ROOT / "scripts/verify_ghcr.sh").read_bytes())
    binary = tmp_path / "bin"
    binary.mkdir()
    calls = tmp_path / "calls"
    (binary / "regctl").write_text("""#!/usr/bin/env bash
printf "%s\\n" "$*" >> "$CALLS"
if [ "$1" = manifest ]; then
  if [ "$FAIL" = 1 ]; then exit 1; fi
  printf '%s' "$DIGEST"
fi
""")
    (binary / "regctl").chmod(stat.S_IRWXU)
    (binary / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (binary / "sleep").chmod(stat.S_IRWXU)
    return workspace, calls, binary


def test_ghcr_all_tags_retries_mismatch_and_never_imports_in_verify_mode(tmp_path):
    """Every published tag must be the tested digest, with network-only retries."""
    workspace, calls, binary = ghcr_workspace(tmp_path)
    environment = {"GITHUB_REPOSITORY": "example/tapebasis", "PATH": str(binary) + ":/usr/bin:/bin", "REGCTL": str(binary / "regctl"), "CALLS": str(calls), "GHCR_RETRY_SECONDS": "0", "FAIL": "0", "DIGEST": "sha256:" + "a" * 64}
    result = subprocess.run(["bash", "scripts/verify_ghcr.sh", "1.0.0"], cwd=workspace, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().count("manifest get") == 4
    assert "image import" not in calls.read_text() and "registry login" not in calls.read_text()
    calls.write_text("")
    result = subprocess.run(["bash", "scripts/verify_ghcr.sh", "1.0.0"], cwd=workspace, env={**environment, "DIGEST": "sha256:" + "b" * 64}, capture_output=True, text=True)
    assert result.returncode != 0 and "has digest" in result.stderr
    assert "image copy" not in calls.read_text()
    calls.write_text("")
    result = subprocess.run(["bash", "scripts/verify_ghcr.sh", "1.0.0"], cwd=workspace, env={**environment, "FAIL": "1"}, capture_output=True, text=True)
    assert result.returncode != 0 and "not readable" in result.stderr
    assert calls.read_text().count("manifest get") == 5
