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


@pytest.mark.parametrize("filename", [
    "tapebasis-1.0.0-py3-none-any.whl",
    "tapebasis-1.0.0.tar.gz",
])
def test_pypi_partial_release_only_requests_the_absent_file(tmp_path, monkeypatch, filename):
    """A verified wheel or sdist stays untouched while the other file is uploadable."""
    module = load("release_registry")
    other = "tapebasis-1.0.0.tar.gz" if filename.endswith(".whl") else "tapebasis-1.0.0-py3-none-any.whl"
    body = b"tested-artifact"
    for name in (filename, other):
        (tmp_path / name).write_bytes(body)
    entries = [{"filename": filename, "digests": {"sha256": hashlib.sha256(body).hexdigest()},
                "url": f"https://files.test/{filename}"}]
    downloads = []
    def get(url, missing_ok=False):
        """Return an isolated one-file PyPI release and record byte comparisons."""
        if url.endswith("/json"):
            return Response({"urls": entries}).body
        downloads.append(url)
        return body
    monkeypatch.setattr(module, "_get", get)
    assert module.check_pypi("tapebasis", "1.0.0", tmp_path) == "partial"
    assert module.inspect_pypi("tapebasis", "1.0.0", tmp_path) == ("partial", [other])
    output = tmp_path / "output"
    assert module.main(["pypi", "--version", "1.0.0", "--dist", str(tmp_path), "--output", str(output)]) == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["pypi_status"] == "partial"
    assert values["pypi_missing_wheel"] == str(other.endswith(".whl")).lower()
    assert values["pypi_missing_sdist"] == str(other.endswith(".tar.gz")).lower()
    assert module.main(["pypi", "--version", "1.0.0", "--dist", str(tmp_path), "--require-existing"]) == 1
    assert downloads
    for malformed in (
        [], [{"filename": filename}, {"filename": filename}],
        [{"filename": "unexpected.whl"}],
    ):
        monkeypatch.setattr(module, "_json", lambda *_args, _entries=malformed, **_kwargs: {"urls": _entries})
        with pytest.raises(module.RegistryError):
            module.inspect_pypi("tapebasis", "1.0.0", tmp_path)


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


def test_registry_cli_accepts_workflow_status_output_after_every_subcommand(tmp_path, monkeypatch):
    """The package and MCP status outputs use the same trailing option as the workflow."""
    server = {"name": "io.github.giraygokirmak/tapebasis", "version": "1.0.0"}
    (tmp_path / "recovered-server.json").write_text(json.dumps(server))
    (tmp_path / "tapebasis-1.0.0.tgz").write_bytes(b"tarball")
    (tmp_path / "tapebasis-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "tapebasis-1.0.0.tar.gz").write_bytes(b"sdist")
    module = load("release_registry")
    monkeypatch.setattr(module, "inspect_pypi", lambda *_args: ("verified", []))
    monkeypatch.setattr(module, "check_npm", lambda *_args: "verified")
    monkeypatch.setattr(module, "check_mcp", lambda *_args: "missing")
    for registry in ("pypi", "npm", "mcp"):
        output = tmp_path / f"{registry}-output"
        arguments = [registry, "--version", "1.0.0"]
        if registry == "mcp":
            arguments += ["--server", str(tmp_path / "recovered-server.json")]
        else:
            arguments += ["--dist", str(tmp_path)]
        arguments += ["--output", str(output)]
        assert module.main(arguments) == 0
        expected = "missing" if registry == "mcp" else "verified"
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert values[f"{registry}_status"] == expected
        if registry == "pypi":
            assert values["pypi_missing_wheel"] == values["pypi_missing_sdist"] == "false"


def test_await_package_retries_only_missing_until_verified(monkeypatch):
    """A transient absence becomes verified without sleeping after the successful read."""
    module = load("release_registry")
    statuses = iter(("missing", "missing", "verified"))
    delays = []
    clock = iter((0.0, 0.0, 2.0, 2.0, 4.0))
    monkeypatch.setenv("REGISTRY_PUBLISH_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("REGISTRY_PUBLISH_RETRY_SECONDS", "2")
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module.time, "sleep", delays.append)

    def check(package, version):
        """Return a fixture result while checking the requested package identity."""
        assert (package, version) == ("tapebasis", "1.1.1")
        return next(statuses)

    assert module.await_package(check, "tapebasis", "1.1.1") == "verified"
    assert delays == [2.0, 2.0]


def test_await_package_bounds_persistent_absence(monkeypatch):
    """Persistent absence cannot turn a post-upload check into an endless retry loop."""
    module = load("release_registry")
    attempts = []
    delays = []
    clock = iter((0.0, 0.0, 1.0, 2.0))
    monkeypatch.setenv("REGISTRY_PUBLISH_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("REGISTRY_PUBLISH_RETRY_SECONDS", "1")
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module.time, "sleep", delays.append)
    with pytest.raises(module.RegistryError, match="remains missing after 2 seconds"):
        module.await_package(lambda *_args: attempts.append(1) or "missing", "tapebasis", "1.1.1")
    assert len(attempts) == 3
    assert delays == [1.0, 1.0]


def test_await_package_does_not_retry_conflicts_or_non_404_errors(monkeypatch):
    """Conflicts and non-404 failures escape without a sleep or a second lookup."""
    module = load("release_registry")
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: pytest.fail("must not retry"))
    for result in (module.RegistryError("HTTP 403"), module.RegistryError("invalid JSON"), ValueError("conflicting bytes")):
        def fail(*_args, error=result):
            """Raise the injected terminal registry failure."""
            raise error
        with pytest.raises(type(result)):
            module.await_package(fail, "tapebasis", "1.1.1")
    calls = []
    assert module.await_package(lambda *_args: calls.append(1) or "verified", "tapebasis", "1.1.1") == "verified"
    assert calls == [1]


def test_await_package_waits_for_partial_but_never_accepts_it(monkeypatch):
    """A partial PyPI upload is readable again but is not final verification."""
    module = load("release_registry")
    statuses = iter(("partial", "verified"))
    monkeypatch.setenv("REGISTRY_PUBLISH_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("REGISTRY_PUBLISH_RETRY_SECONDS", "1")
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    assert module.await_package(lambda *_args: next(statuses), "tapebasis", "1.1.1") == "verified"
    monkeypatch.setenv("REGISTRY_PUBLISH_TIMEOUT_SECONDS", "0")
    with pytest.raises(module.RegistryError, match="remains partial"):
        module.await_package(lambda *_args: "partial", "tapebasis", "1.1.1")
    with pytest.raises(module.RegistryError, match="not verified"):
        module.await_package(lambda *_args: "unexpected", "tapebasis", "1.1.1")


def test_await_package_rejects_invalid_bounds(monkeypatch):
    """Malformed, infinite and nonpositive wait settings are explicit failures."""
    module = load("release_registry")
    for timeout, interval in (("nan", "1"), ("-1", "1"), ("no", "1"), ("10", "0"), ("10", "inf")):
        monkeypatch.setenv("REGISTRY_PUBLISH_TIMEOUT_SECONDS", timeout)
        monkeypatch.setenv("REGISTRY_PUBLISH_RETRY_SECONDS", interval)
        with pytest.raises(module.RegistryError, match="wait"):
            module.await_package(lambda *_args: "missing", "tapebasis", "1.1.1")


def test_await_visible_cli_uses_post_upload_wait(tmp_path, monkeypatch):
    """The workflow flag waits for package visibility, rather than permitting an upload."""
    module = load("release_registry")
    calls = []
    monkeypatch.setattr(module, "await_package", lambda check, package, version: calls.append((package, version)) or check(package, version))
    monkeypatch.setattr(module, "check_pypi", lambda *_args: "verified")
    assert module.main(["pypi", "--version", "1.1.1", "--dist", str(tmp_path), "--require-existing", "--await-visible"]) == 0
    assert calls == [("tapebasis", "1.1.1")]


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


def test_source_metadata_uses_toml_fallback_before_311(monkeypatch):
    """Read identical release metadata through the declared pre-3.11 parser."""
    module = load("release_artifact_source")
    if sys.version_info >= (3, 11):
        import tomllib as parser
    else:
        import tomli as parser
    expected = module.load_metadata(ROOT)
    original_import = __import__

    def hide_tomllib(name, *args, **kwargs):
        """Exercise the compatibility import on every test interpreter."""
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        if name == "tomli":
            return parser
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", hide_tomllib)
    monkeypatch.delitem(sys.modules, "tomllib", raising=False)
    monkeypatch.setitem(sys.modules, "tomli", parser)
    assert module.load_metadata(ROOT) == expected


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
    module.validate_source(run, jobs, artifact, "1.0.0")
    for change in ({"head_branch": "main"}, {"head_sha": "not-a-commit"}, {"event": "workflow_dispatch"}):
        with pytest.raises(module.SourceError):
            module.validate_source({**run, **change}, jobs, artifact, "1.0.0")
    for change in ({"expired": True}, {"size_in_bytes": 0}, {"digest": "sha256:invalid"}):
        with pytest.raises(module.SourceError):
            module.validate_source(run, jobs, {**artifact, **change}, "1.0.0")
    for publisher in ({**jobs[-1], "conclusion": "skipped"}, {**jobs[-1], "started_at": None}, {**jobs[-1], "status": "in_progress"}):
        with pytest.raises(module.SourceError):
            module.validate_source(run, jobs[:-1] + [publisher], artifact, "1.0.0")


def test_source_allows_current_main_to_be_the_exact_tag_commit():
    """An immutable tag pushed from current main is still a valid original source."""
    module = load("release_artifact_source")
    run, jobs, artifact = source_fixture()
    assert module.validate_source(run, jobs, artifact, "1.0.0") is None


def test_notes_source_accepts_no_started_publisher_but_not_missing_validation():
    """Older validated tags can receive notes without a prior publication job."""
    module = load("release_artifact_source")
    run, jobs, artifact = source_fixture()
    assert module.validate_source(run, jobs[:-1], artifact, "1.0.0",
                                 notes_only=True) is None
    with pytest.raises(module.SourceError, match="source publish job"):
        module.validate_source(run, jobs[:-1], artifact, "1.0.0")
    for insufficient in (jobs[1:-1], jobs[:-2], [{**jobs[0], "conclusion": "failure"}, jobs[1]]):
        with pytest.raises(module.SourceError):
            module.validate_source(run, insufficient, artifact, "1.0.0",
                                   notes_only=True)
    with pytest.raises(module.SourceError, match="ambiguous"):
        module.validate_source(run, [*jobs, jobs[-1]], artifact, "1.0.0",
                               notes_only=True)


def test_github_json_file_accepts_only_wrapped_base64_objects():
    """The Contents API's newlines are valid, but other encodings and malformed JSON stop."""
    module = load("release_artifact_source")
    server = {"name": "io.github.giraygokirmak/tapebasis", "version": "1.0.0"}
    encoded = base64.b64encode(json.dumps(server).encode()).decode()
    wrapped = "\n".join(encoded[index:index + 60] for index in range(0, len(encoded), 60)) + "\n"
    assert module.parse_github_json_file({"encoding": "base64", "content": wrapped}) == server
    for document in (
        {"encoding": "none", "content": encoded},
        {"encoding": "base64", "content": "not valid base64!"},
        {"encoding": "base64", "content": base64.b64encode(b"[]").decode()},
    ):
        with pytest.raises(module.SourceError):
            module.parse_github_json_file(document)


def test_source_main_accepts_wrapped_contents_base64_before_download(tmp_path, monkeypatch):
    """A real-shaped Contents response cannot reject recovery before artifact extraction."""
    module = load("release_artifact_source")
    run, jobs, artifact = source_fixture()
    version, server = module.load_metadata(ROOT)
    run = {**run, "head_branch": f"v{version}"}
    jobs = [*jobs[:-1], {**jobs[-1], "name": f"Publish {version}"}]
    encoded = base64.b64encode(json.dumps(server).encode()).decode()
    wrapped = "\n".join(encoded[index:index + 60] for index in range(0, len(encoded), 60)) + "\n"
    tag_object = "b" * 40
    extracted = tmp_path / "source-artifacts.zip"
    bodies = {
        "SHA256SUMS": b"checksums",
        "tapebasis-image.tar": b"image",
        f"tapebasis-{version}-py3-none-any.whl": b"wheel",
        f"tapebasis-{version}.tar.gz": b"sdist",
        f"tapebasis-{version}.tgz": b"npm",
    }
    with zipfile.ZipFile(extracted, "w") as archive:
        for name, body in bodies.items():
            archive.writestr(name, body)
    artifact.update({
        "size_in_bytes": extracted.stat().st_size,
        "digest": "sha256:" + hashlib.sha256(extracted.read_bytes()).hexdigest(),
        "archive_download_url": "https://api.github.com/artifact",
    })
    responses = {
        "/actions/runs/43435266134": run,
        "/actions/runs/43435266134/jobs?per_page=100": {"total_count": len(jobs), "jobs": jobs},
        "/actions/runs/43435266134/artifacts": {"total_count": 1, "artifacts": [artifact]},
        f"/git/ref/tags/v{version}": {"object": {"sha": tag_object, "type": "tag"}},
        f"/git/tags/{tag_object}": {"object": {"sha": run["head_sha"]}},
        f"/contents/server.json?ref={run['head_sha']}": {"encoding": "base64", "content": wrapped},
    }
    run = {**run, "repository": {"full_name": "giraygokirmak/tapebasis"}}
    responses["/actions/runs/43435266134"] = run

    class Opener:
        def open(self, request, timeout):
            """Return a matching fixture and reject unexpected network endpoints."""
            if request.full_url == artifact["archive_download_url"]:
                return Response(extracted.read_bytes())
            path = request.full_url.split("/repos/giraygokirmak/tapebasis", 1)[1]
            return Response(responses[path])

    output = tmp_path / "github-output"
    monkeypatch.setattr(module, "OPENER", Opener())
    monkeypatch.setenv("GITHUB_REPOSITORY", "giraygokirmak/tapebasis")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("REQUIRED_TAG", f"v{version}")
    destination = tmp_path / "result.zip"
    assert module.main(["--run-id", "43435266134", "--token", "test-token", "--zip", str(destination), "--dist", str(tmp_path / "dist"), "--server", str(tmp_path / "server.json")]) == 0
    assert destination.read_bytes() == extracted.read_bytes()
    assert (tmp_path / f"dist/tapebasis-{version}.tgz").read_bytes() == b"npm"
    assert json.loads((tmp_path / "server.json").read_text()) == server
    assert f"version={version}" in output.read_text()
    assert "artifact_digest=" + artifact["digest"] in output.read_text()


def test_source_only_binds_old_tag_metadata_instead_of_main_version(tmp_path, monkeypatch):
    """Package continuation accepts an older source identity without weakening its binding."""
    module = load("release_artifact_source")
    run, jobs, artifact = source_fixture()
    server = {"name": "io.github.giraygokirmak/tapebasis", "version": "1.0.0", "packages": [
        {"registryType": "npm", "identifier": "tapebasis", "version": "1.0.0"},
        {"registryType": "pypi", "identifier": "tapebasis", "version": "1.0.0"},
    ]}
    run = {**run, "repository": {"full_name": "giraygokirmak/tapebasis"}}
    documents = {
        "pyproject.toml": b'[project]\nname = "tapebasis"\nversion = "1.0.0"\n',
        "package.json": json.dumps({"name": "tapebasis", "version": "1.0.0"}).encode(),
        "src/tapebasis/__init__.py": b'__version__ = "1.0.0"\n',
        "package-lock.json": json.dumps({"version": "1.0.0", "packages": {"": {"version": "1.0.0"}}}).encode(),
        "server.json": json.dumps(server).encode(),
    }
    responses = {
        "/actions/runs/43435266134": run,
        "/actions/runs/43435266134/jobs?per_page=100": {"total_count": len(jobs), "jobs": jobs},
        "/actions/runs/43435266134/artifacts": {"total_count": 1, "artifacts": [artifact]},
        "/git/ref/tags/v1.0.0": {"object": {"sha": run["head_sha"], "type": "commit"}},
    }
    for name, body in documents.items():
        encoded = base64.b64encode(body).decode()
        responses[f"/contents/{name}?ref={run['head_sha']}"] = {"encoding": "base64", "content": encoded}
    fetched = []
    monkeypatch.setattr(module, "_api", lambda url, _headers: fetched.append(url) or responses[url.split("/repos/giraygokirmak/tapebasis", 1)[1]])
    monkeypatch.setattr(module, "download", lambda *_args: None)
    monkeypatch.setattr(module, "extract", lambda *_args: None)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_REPOSITORY", "giraygokirmak/tapebasis")
    monkeypatch.setenv("GITHUB_SHA", run["head_sha"])
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("REQUIRED_TAG", "v1.0.0")
    server_path = tmp_path / "server.json"
    assert module.main(["--run-id", "43435266134", "--token", "test-token", "--source-only", "--zip", str(tmp_path / "source.zip"), "--dist", str(tmp_path / "dist"), "--server", str(server_path)]) == 0
    assert json.loads(server_path.read_text()) == server
    assert output.read_text().startswith("version=1.0.0\n")
    for name in documents:
        assert f"/contents/{name}?ref={run['head_sha']}" in [url.split("/repos/giraygokirmak/tapebasis", 1)[1] for url in fetched]
    monkeypatch.setenv("REQUIRED_TAG", "v1.0.1")
    assert module.main(["--run-id", "43435266134", "--token", "test-token", "--source-only", "--zip", str(tmp_path / "different.zip"), "--dist", str(tmp_path / "different-dist"), "--server", str(server_path)]) == 1


def test_source_metadata_rejects_mismatched_registry_identity():
    """Continuation cannot pair valid version strings with a different package manifest."""
    module = load("release_artifact_source")
    package = {"name": "tapebasis", "version": "1.0.0"}
    server = {"version": "1.0.0", "packages": [
        {"registryType": "npm", "identifier": "other", "version": "1.0.0"},
        {"registryType": "pypi", "identifier": "tapebasis", "version": "1.0.0"},
    ]}
    lock = {"version": "1.0.0", "packages": {"": {"version": "1.0.0"}}}
    with pytest.raises(module.SourceError, match="npm package"):
        module.check_metadata(
            '[project]\nname="tapebasis"\nversion="1.0.0"\n', package, server, lock,
            '__version__ = "1.0.0"\n',
        )


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


def test_extract_accepts_regular_and_unspecified_unix_file_types(tmp_path):
    """Normal ZIP writers need not assign Unix regular-file mode bits."""
    module = load("release_artifact_source")
    path = tmp_path / "normal.zip"
    files = {
        "SHA256SUMS": b"checksums",
        "tapebasis-image.tar": b"image",
        "tapebasis-1.0.0-py3-none-any.whl": b"wheel",
        "tapebasis-1.0.0.tar.gz": b"sdist",
        "tapebasis-1.0.0.tgz": b"npm",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16 if name == "SHA256SUMS" else 0o644 << 16
            archive.writestr(info, body)
    module.extract(path, tmp_path / "normal-dist", "1.0.0")
    for name, body in files.items():
        assert (tmp_path / "normal-dist" / name).read_bytes() == body


def test_source_metadata_rejects_a_disagreeing_init_version():
    """The source tag's imported package version is part of its immutable identity."""
    module = load("release_artifact_source")
    package = {"name": "tapebasis", "version": "1.0.0"}
    server = {"version": "1.0.0", "packages": [
        {"registryType": "npm", "identifier": "tapebasis", "version": "1.0.0"},
        {"registryType": "pypi", "identifier": "tapebasis", "version": "1.0.0"},
    ]}
    lock = {"version": "1.0.0", "packages": {"": {"version": "1.0.0"}}}
    with pytest.raises(module.SourceError, match="__init__.py"):
        module.check_metadata(
            '[project]\nname="tapebasis"\nversion="1.0.0"\n', package, server, lock,
            '__version__ = "0.9.0"\n',
        )


def ghcr_workspace(tmp_path):
    """Prepare a fake HTTP classifier, registry writer and no-delay sleep."""
    workspace = tmp_path / "workspace"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / "dist").mkdir()
    (workspace / "scripts/check_oci_image.py").write_text('print("sha256:" + "a" * 64)\n')
    for name in ("verify_ghcr.sh", "ghcr_manifest.py"):
        (workspace / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    binary = tmp_path / "bin"
    binary.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("")
    lookup = tmp_path / "lookup.py"
    lookup.write_text('''import os
from pathlib import Path
import sys

args = sys.argv[1:]
tag = args[args.index("--tag") + 1]
root = Path(os.environ["GHCR_STATE"])
calls = Path(os.environ["CALLS"])
with calls.open("a") as stream:
    stream.write(f"lookup {tag}\\n")
status = os.environ.get("LOOKUP_STATUS", "match")
if (
    tag == os.environ.get("AUTH_FAIL_TAG")
    and (
        tag in os.environ.get("MATCH_TAGS", "").split(",")
        or tag in os.environ.get("PREDECESSOR_TAGS", "").split(",")
    )
):
    expected = args[args.index("--expected") + 1]
    auth_before_advance = (
        expected == os.environ.get("PREDECESSOR_DIGEST")
        and os.environ.get("AUTH_FAIL_PREDECESSOR") == "1"
    )
    if (
        os.environ.get("AUTH_FAIL_MODE") == "initial"
        and os.environ.get("AUTH_FAIL_PREDECESSOR") != "1"
    ) or auth_before_advance:
        print("lookup failed: " + os.environ["AUTH_FAIL_ERROR"], file=sys.stderr)
        sys.exit(3)
if status in {"401", "403", "503", "network"}:
    print(f"lookup failed: {status}", file=sys.stderr)
    sys.exit(3)
if status in {"present-before-publish", "exact-present"}:
    state = root / "last-publish"
    written = state.read_text().splitlines() if state.exists() else []
    if status == "exact-present" and tag == os.environ["SOURCE_VERSION"]:
        status = "match"
    else:
        status = "match" if f"ghcr.io/example/tapebasis:{tag}" in written else "absent"
if status in {"approved-alias", "approved-alias-auth"}:
    state = root / "last-publish"
    written = set(state.read_text().splitlines()) if state.exists() else set()
    approved_tags = {
        "1.1.1": {"1", "latest"},
        "1.1.2": {"1.1", "1", "latest"},
        "1.1.3": {"1.1", "1", "latest"},
        "1.1.4": {"1.1", "1", "latest"},
        "1.2.0": {"1.2", "1", "latest"},
    }.get(os.environ["SOURCE_VERSION"], set())
    matched = set(os.environ.get("MATCH_TAGS", "").split(","))
    predecessors = set(os.environ.get("PREDECESSOR_TAGS", "").split(","))
    conflicts = set(os.environ.get("CONFLICT_TAGS", "").split(","))
    reference = "ghcr.io/example/tapebasis:" + tag
    expected = args[args.index("--expected") + 1]
    if tag in conflicts:
        status = "conflict"
    elif reference in written or tag in matched:
        status = "match"
    elif tag in predecessors and expected == os.environ.get("PREDECESSOR_DIGEST"):
        print(expected)
        sys.exit(0)
    elif tag in matched | predecessors:
        status = "conflict"
    else:
        status = "absent"
if status == "remain-absent":
    status = "absent"
if status == "absent":
    print("manifest absent (HTTP 404)", file=sys.stderr)
    sys.exit(2)
if status == "conflict":
    print("has a different digest", file=sys.stderr)
    sys.exit(1)
print("sha256:" + "a" * 64)
''')
    (binary / "regctl").write_text('''#!/usr/bin/env bash
printf "%s\\n" "$*" >> "$CALLS"
if [ "$1" = image ]; then
  if [ -n "${PUBLISH_FAIL:-}" ]; then exit 1; fi
  target="$3"
  [ "$2" != copy ] || target="$4"
  printf '%s\\n' "$target" >> "$GHCR_STATE/last-publish"
fi
''')
    (binary / "regctl").chmod(stat.S_IRWXU)
    (binary / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (binary / "sleep").chmod(stat.S_IRWXU)
    (tmp_path / "ghcr-state").mkdir()
    return workspace, calls, binary


def ghcr_environment(fixture, status="match", python=None):
    """Return hermetic shell inputs for the fake read-only manifest helper."""
    workspace, calls, binary = fixture
    return {
        "GITHUB_REPOSITORY": "example/tapebasis",
        "GITHUB_REPOSITORY_OWNER": "example",
        "GHCR_TOKEN": "token",
        "PATH": str(binary) + ":/usr/bin:/bin",
        "PYTHON": str(python) if python else "",
        "REGCTL": str(binary / "regctl"),
        "CALLS": str(calls),
        "GHCR_STATE": str(calls.parent / "ghcr-state"),
        "GHCR_RETRY_SECONDS": "0",
        "GHCR_LOOKUP": str(calls.parent / "lookup.py"),
        "LOOKUP_STATUS": status,
        "SOURCE_VERSION": "1.0.0",
    }


def run_ghcr(fixture, environment):
    """Execute the shell verifier with no actual GHCR or image credentials."""
    command = [
        "bash", "scripts/verify_ghcr.sh", environment.pop("VERSION", "1.0.0"),
        environment.pop("MODE", "verify"),
    ]
    environment["SOURCE_VERSION"] = command[2]
    if environment.get("ADVANCE"):
        command.extend(environment.pop("ADVANCE").split("=", 1))
    return subprocess.run(command, cwd=fixture[0], env=environment, capture_output=True, text=True)


def test_ghcr_all_tags_retries_absence_and_never_imports_in_verify_mode(tmp_path):
    """Every published tag matches the tested digest and verification never writes."""
    fixture = ghcr_workspace(tmp_path)
    calls = fixture[1]
    result = run_ghcr(fixture, ghcr_environment(fixture))
    assert result.returncode == 0, result.stderr
    assert calls.read_text().count("effectively lookup") == 0
    assert calls.read_text().count("lookup") == 4
    assert "image import" not in calls.read_text() and "registry login" not in calls.read_text()
    calls.write_text("")
    environment = ghcr_environment(fixture, "conflict")
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0 and "digest" in result.stderr
    assert "image copy" not in calls.read_text()
    calls.write_text("")
    result = run_ghcr(fixture, ghcr_environment(fixture, "403"))
    assert result.returncode != 0 and "lookup failed" in result.stderr
    assert calls.read_text().count("lookup") == 1
    for status in ("401", "503", "network"):
        calls.write_text("")
        result = run_ghcr(fixture, ghcr_environment(fixture, status))
        assert result.returncode != 0
        assert "image import" not in calls.read_text() and "image copy" not in calls.read_text()
    calls.write_text("")
    result = run_ghcr(fixture, ghcr_environment(fixture, "remain-absent"))
    assert result.returncode != 0 and "remains absent" in result.stderr
    assert calls.read_text().count("lookup") == 6
    assert "image import" not in calls.read_text() and "image copy" not in calls.read_text()


def test_ghcr_completes_missing_aliases_when_exact_image_already_exists(tmp_path):
    """An existing exact image permits one login and one copy per absent alias."""
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "exact-present")
    environment["MODE"] = "publish-missing"
    result = run_ghcr(fixture, environment)
    assert result.returncode == 0, result.stderr
    commands = fixture[1].read_text().splitlines()
    assert sum(line.startswith("lookup") for line in commands) == 7
    assert sum(line.startswith("registry login") for line in commands) == 1
    assert not any(line.startswith("image import") for line in commands)
    assert sum(line.startswith("image copy") for line in commands) == 3


def test_ghcr_only_explicit_absence_can_publish(tmp_path):
    """An absent exact tag is imported once, then each absent alias is copied once."""
    fixture = ghcr_workspace(tmp_path)
    calls = fixture[1]
    environment = ghcr_environment(fixture, "present-before-publish")
    environment["MODE"] = "publish-missing"
    result = run_ghcr(fixture, environment)
    assert result.returncode == 0, result.stderr
    commands = calls.read_text().splitlines()
    assert sum(line.startswith("lookup") for line in commands) == 8
    assert sum(line.startswith("registry login") for line in commands) == 1
    assert sum(line.startswith("image import") for line in commands) == 1
    assert sum(line.startswith("image copy") for line in commands) == 3
    assert "image copy ghcr.io/example/tapebasis:1.0.0 ghcr.io/example/tapebasis:1.0" in commands
    assert "VERSIONIMAGE" not in calls.read_text()


def test_ghcr_111_advances_only_approved_major_and_latest_aliases(tmp_path):
    """The earlier exception remains limited to 1.1.1's major and latest aliases."""
    fixture = ghcr_workspace(tmp_path)
    predecessor = "sha256:" + "b" * 64
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION="1.1.1",
        MODE="publish-missing",
        ADVANCE="--advance-major-latest-from=" + predecessor,
        PREDECESSOR_DIGEST=predecessor,
        PREDECESSOR_TAGS="1,latest",
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode == 0, result.stderr
    commands = fixture[1].read_text().splitlines()
    assert commands.count("lookup 1") == 3
    assert commands.count("lookup latest") == 3
    copies = [line for line in commands if line.startswith("image copy")]
    assert copies == [
        "image copy ghcr.io/example/tapebasis:1.1.1 ghcr.io/example/tapebasis:1.1",
        "image copy ghcr.io/example/tapebasis:1.1.1 ghcr.io/example/tapebasis:1",
        "image copy ghcr.io/example/tapebasis:1.1.1 ghcr.io/example/tapebasis:latest",
    ]
    assert sum(line.startswith("registry login") for line in commands) == 1
    assert fixture[1].read_text().count("image copy ghcr.io/example/tapebasis:1.1.1 ghcr.io/example/tapebasis:1\n") == 1


@pytest.mark.parametrize("version", ["1.1.2", "1.1.3", "1.1.4", "1.2.0"])
def test_ghcr_bounded_release_advances_only_its_three_reviewed_aliases(tmp_path, version):
    """Each bounded release exception advances its three aliases after a second digest check."""
    fixture = ghcr_workspace(tmp_path)
    predecessor = "sha256:" + "b" * 64
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION=version,
        MODE="publish-missing",
        ADVANCE="--advance-minor-major-latest-from=" + predecessor,
        PREDECESSOR_DIGEST=predecessor,
        PREDECESSOR_TAGS=f"{version.rsplit('.', 1)[0]},1,latest",
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode == 0, result.stderr
    commands = fixture[1].read_text().splitlines()
    for tag in (version.rsplit(".", 1)[0], "1", "latest"):
        assert commands.count("lookup " + tag) == 3
    assert commands.count(f"image import ghcr.io/example/tapebasis:{version} dist/tapebasis-image.tar") == 1
    copies = [line for line in commands if line.startswith("image copy")]
    assert copies == [
        f"image copy ghcr.io/example/tapebasis:{version} ghcr.io/example/tapebasis:{version.rsplit('.', 1)[0]}",
        f"image copy ghcr.io/example/tapebasis:{version} ghcr.io/example/tapebasis:1",
        f"image copy ghcr.io/example/tapebasis:{version} ghcr.io/example/tapebasis:latest",
    ]
    resumed = run_ghcr(fixture, {
        **ghcr_environment(fixture, "approved-alias"),
        "VERSION": version,
        "MODE": "publish-missing",
        "ADVANCE": "--advance-minor-major-latest-from=" + predecessor,
        "PREDECESSOR_DIGEST": predecessor,
    })
    assert resumed.returncode == 0, resumed.stderr
    after = fixture[1].read_text().splitlines()
    assert sum(line.startswith("image") for line in after) == 4
    assert after.count("lookup " + version) == 3
    for tag in (version.rsplit(".", 1)[0], "1", "latest"):
        assert after.count("lookup " + tag) == 4


@pytest.mark.parametrize("version", ["1.0.0", "1.3.0"])
def test_ghcr_bounded_release_option_is_rejected_for_other_versions(tmp_path, version):
    """A future release cannot inherit these specifically reviewed exceptions."""
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "approved-alias")
    environment["VERSION"] = version
    environment["ADVANCE"] = "--advance-minor-major-latest-from=sha256:" + "b" * 64
    result = run_ghcr(fixture, environment)
    assert result.returncode == 2
    assert fixture[1].read_text() == ""


@pytest.mark.parametrize("version", ["1.0.0", "1.1.2", "1.1.3", "1.2.0"])
def test_ghcr_111_option_is_not_a_general_alias_exception(tmp_path, version):
    """The existing exception is also frozen to its reviewed release identity."""
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION=version,
        ADVANCE="--advance-major-latest-from=sha256:" + "b" * 64,
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode == 2
    assert fixture[1].read_text() == ""


@pytest.mark.parametrize("version", ["1.1.2", "1.1.3", "1.1.4", "1.2.0"])
def test_ghcr_bounded_release_rejects_a_wrong_predecessor_without_alias_writes(tmp_path, version):
    """An unreviewed predecessor cannot advance an existing manifest as an alias."""
    fixture = ghcr_workspace(tmp_path)
    reviewed = "sha256:" + "b" * 64
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION=version,
        MODE="publish-missing",
        ADVANCE="--advance-minor-major-latest-from=" + reviewed,
        PREDECESSOR_DIGEST="sha256:" + "c" * 64,
        MATCH_TAGS=version,
        PREDECESSOR_TAGS=f"{version.rsplit('.', 1)[0]},1,latest",
        CONFLICT_TAGS=f"{version.rsplit('.', 1)[0]},1,latest",
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0
    commands = fixture[1].read_text().splitlines()
    assert not any(line.startswith("image copy") for line in commands)
    assert not any(line.startswith("image import") for line in commands)


@pytest.mark.parametrize("version", ["1.1.2", "1.1.3", "1.1.4", "1.2.0", "1.1.1"])
@pytest.mark.parametrize("lookup_read", ["initial", "predecessor"])
@pytest.mark.parametrize("lookup_error", ["403", "network"])
def test_ghcr_lookup_errors_never_authorize_affected_writes(
    tmp_path, version, lookup_read, lookup_error
):
    """Authorization and transport errors stop before the affected tag's write."""
    predecessor = "sha256:" + "b" * 64
    option = (
        "--advance-major-latest-from"
        if version == "1.1.1"
        else "--advance-minor-major-latest-from"
    )
    approved_tags = ("1", "latest") if version == "1.1.1" else (version.rsplit(".", 1)[0], "1", "latest")
    tags = (version, version.rsplit(".", 1)[0], "1", "latest") if lookup_read == "initial" else approved_tags
    for tag in tags:
        fixture = ghcr_workspace(tmp_path / tag)
        environment = ghcr_environment(fixture, "approved-alias-auth")
        environment.update(
            VERSION=version,
            MODE="publish-missing",
            MATCH_TAGS=f"{version},{version.rsplit('.', 1)[0]}" if lookup_read == "initial" else "",
            PREDECESSOR_TAGS=",".join(approved_tags),
            ADVANCE=option + "=" + predecessor,
            PREDECESSOR_DIGEST=predecessor,
            AUTH_FAIL_TAG=tag,
            AUTH_FAIL_MODE=lookup_read,
            AUTH_FAIL_PREDECESSOR="1" if lookup_read == "predecessor" else "0",
            AUTH_FAIL_ERROR=lookup_error,
        )
        result = run_ghcr(fixture, environment)
        assert result.returncode != 0
        assert f"lookup failed: {lookup_error}" in result.stderr
        commands = fixture[1].read_text().splitlines()
        written_aliases = {
            line.rsplit(":", 1)[-1]
            for line in commands
            if line.startswith("image copy")
        }
        assert tag not in written_aliases
        if lookup_read == "initial" and tag in (version, "1.1"):
            assert not any(line.startswith("image") for line in commands)


@pytest.mark.parametrize("version", ["1.1.2", "1.1.3", "1.1.4", "1.2.0"])
def test_ghcr_bounded_release_verify_mode_never_uses_advancement_option(tmp_path, version):
    """An approved publication predecessor grants no authority in verify mode."""
    fixture = ghcr_workspace(tmp_path)
    predecessor = "sha256:" + "b" * 64
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION=version,
        ADVANCE="--advance-minor-major-latest-from=" + predecessor,
        PREDECESSOR_DIGEST=predecessor,
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode == 2
    assert fixture[1].read_text() == ""


def test_ghcr_111_option_rejects_a_minor_alias_conflict(tmp_path):
    """The old exception cannot advance a minor alias even with its predecessor."""
    fixture = ghcr_workspace(tmp_path)
    predecessor = "sha256:" + "b" * 64
    environment = ghcr_environment(fixture, "approved-alias")
    environment.update(
        VERSION="1.1.1",
        MODE="publish-missing",
        ADVANCE="--advance-major-latest-from=" + predecessor,
        PREDECESSOR_DIGEST=predecessor,
        MATCH_TAGS="1.1.1",
        PREDECESSOR_TAGS="1.1",
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0
    commands = fixture[1].read_text().splitlines()
    assert not any(line.startswith("image") for line in commands)


@pytest.mark.parametrize("version", ["1.1.2", "1.1.3", "1.1.4", "1.2.0"])
def test_ghcr_approved_aliases_never_authorize_exact_version_replacement(tmp_path, version):
    """A conflicting immutable exact tag stops before any alias can be written."""
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "conflict")
    environment.update(
        VERSION=version,
        MODE="publish-missing",
        ADVANCE="--advance-minor-major-latest-from=sha256:" + "b" * 64,
        PREDECESSOR_DIGEST="sha256:" + "b" * 64,
    )
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0
    assert "image import" not in fixture[1].read_text()
    assert "image copy" not in fixture[1].read_text()


def test_ghcr_rejects_unapproved_aliases_and_never_advances_in_other_modes(tmp_path):
    """A predecessor cannot replace unrelated images or silently enable alias writes."""
    predecessor = "sha256:" + "b" * 64
    advance = "--advance-major-latest-from=" + predecessor
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "match")
    environment["ADVANCE"] = advance
    result = run_ghcr(fixture, environment)
    assert result.returncode == 2
    for status in ("conflict", "approved-alias"):
        calls = fixture[1]
        calls.write_text("")
        environment = ghcr_environment(fixture, status)
        environment.update(PREDECESSOR_DIGEST=predecessor)
        result = run_ghcr(fixture, environment)
        assert result.returncode != 0
        assert "image copy" not in calls.read_text()
    for invalid in ("", "sha256:" + "b" * 63, "sha256:" + "B" * 64):
        calls.write_text("")
        environment = ghcr_environment(fixture, "conflict")
        environment["ADVANCE"] = "--advance-major-latest-from=" + invalid
        result = run_ghcr(fixture, environment)
        assert result.returncode == 2
        assert "registry login" not in calls.read_text()
    calls.write_text("")
    environment = ghcr_environment(fixture, "conflict")
    environment["ADVANCE"] = "--advance-major-latest-from=" + ("sha256:" + "c" * 64)
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0 and "image copy" not in calls.read_text()


def test_ghcr_failed_publish_is_not_misreported_as_verified(tmp_path):
    """A write failure remains a failure and cannot be bypassed by a later read."""
    fixture = ghcr_workspace(tmp_path)
    environment = ghcr_environment(fixture, "present-before-publish")
    environment.update(MODE="publish-missing", PUBLISH_FAIL="1")
    result = run_ghcr(fixture, environment)
    assert result.returncode != 0
    assert fixture[1].read_text().count("image import") == 1
    assert "image copy" not in fixture[1].read_text()
