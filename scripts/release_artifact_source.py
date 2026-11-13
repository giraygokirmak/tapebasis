#!/usr/bin/env python3
"""Fetch tested artifacts only from an earlier approved tag run.

Recovery binds the entered tag, source run, live tag target, source MCP metadata
and GitHub's immutable ZIP digest before extracting any release file. It never
publishes a package or accepts an expired, partial, or unverified download.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

API = "https://api.github.com"
COMMIT = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class SourceError(Exception):
    """Reject a source run whose provenance or contents cannot be trusted."""


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Remove repository credentials before following a redirect to another host."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        """Return a redirect request with Authorization stripped across origins."""
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None:
            old = urllib.parse.urlsplit(request.full_url)
            new = urllib.parse.urlsplit(redirected.full_url)
            if new.scheme != "https" or (new.scheme, new.netloc) != (old.scheme, old.netloc):
                redirected.remove_header("Authorization")
        return redirected


OPENER = urllib.request.build_opener(SameHostRedirects())


def load_metadata(root: pathlib.Path) -> tuple[str, dict]:
    """Return the common project version and source MCP server manifest."""
    try:
        import tomllib

        version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        server = json.loads((root / "server.json").read_text(encoding="utf-8"))
        lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SourceError(f"cannot read release metadata: {error}") from error
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise SourceError("release version is unsupported")
    if package.get("version") != version or server.get("version") != version:
        raise SourceError("release metadata versions differ")
    if lock.get("version") != version or lock.get("packages", {}).get("", {}).get("version") != version:
        raise SourceError("npm lock versions differ")
    return version, server


def validate_source(run: dict, jobs: list[dict], artifact: dict, version: str, sha: str) -> None:
    """Require a completed approved tag-publish job and a live bound artifact."""
    if run.get("event") != "push" or run.get("name") != "Release" or run.get("head_branch") != f"v{version}":
        raise SourceError("source must be a Release push for the entered version tag")
    if not COMMIT.fullmatch(run.get("head_sha", "")) or run["head_sha"] == sha:
        raise SourceError("source commit is invalid or is the recovery commit itself")
    if run.get("status") != "completed" or artifact.get("name") != "release-artifacts" or artifact.get("expired"):
        raise SourceError("source run or its artifact is unavailable")
    if artifact.get("workflow_run", {}).get("id") != run.get("id"):
        raise SourceError("source artifact is not bound to the run")
    if not isinstance(artifact.get("size_in_bytes"), int) or artifact["size_in_bytes"] <= 0:
        raise SourceError("source artifact has no declared size")
    if not DIGEST.fullmatch(artifact.get("digest", "")):
        raise SourceError("source artifact has no valid SHA-256 digest")
    if not jobs or any(job.get("status") != "completed" for job in jobs):
        raise SourceError("source contains an unfinished job")
    for job in jobs:
        name = job.get("name", "")
        if (name.startswith("Validate /") or name == "Build release artifacts") and job.get("conclusion") != "success":
            raise SourceError(f"source {name} did not complete successfully")
    if not any(job.get("name", "").startswith("Validate /") and job.get("conclusion") == "success" for job in jobs):
        raise SourceError("source tag validation did not pass")
    if not any(job.get("name") == "Build release artifacts" and job.get("conclusion") == "success" for job in jobs):
        raise SourceError("source tag build did not pass")
    publisher = [job for job in jobs if job.get("name") == f"Publish {version}"]
    if len(publisher) != 1 or publisher[0].get("conclusion") not in {"success", "failure", "cancelled"}:
        raise SourceError("source publish job was skipped or cancelled before starting")
    if not publisher[0].get("started_at") or not publisher[0].get("completed_at"):
        raise SourceError("source publish job did not start after its protected approval")


def _api(url: str, headers: dict) -> dict:
    """Read a JSON object from GitHub's API without forwarding credentials cross-host."""
    with OPENER.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
        document = json.load(response)
    if not isinstance(document, dict):
        raise SourceError(f"GitHub did not return an object: {url}")
    return document


def parse_github_json_file(document: dict) -> dict:
    """Parse a base64 Contents API file, accepting only its documented line wrapping."""
    if document.get("encoding") != "base64" or not isinstance(document.get("content"), str):
        raise SourceError("GitHub file response is not base64-encoded content")
    encoded = "".join(document["content"].splitlines())
    try:
        decoded = base64.b64decode(encoded, validate=True)
        document = json.loads(decoded)
    except (ValueError, TypeError) as error:
        raise SourceError(f"GitHub file content is invalid: {error}") from error
    if not isinstance(document, dict):
        raise SourceError("GitHub JSON file does not contain an object")
    return document


def download(artifact: dict, token: str, path: pathlib.Path) -> None:
    """Download and atomically save the exact expected artifact ZIP by size and digest."""
    url = artifact.get("archive_download_url", "")
    if not isinstance(url, str) or urllib.parse.urlsplit(url)[:2] != ("https", "api.github.com"):
        raise SourceError("source download URL is not on api.github.com")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "tapebasis-recovery"})
    temporary = path.with_name(path.name + ".partial")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with OPENER.open(request, timeout=120) as response, temporary.open("xb") as stream:
            while block := response.read(1024 * 1024):
                digest.update(block)
                size += len(block)
                if size > artifact["size_in_bytes"]:
                    raise SourceError("source artifact exceeds its declared size")
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if size != artifact["size_in_bytes"] or "sha256:" + digest.hexdigest() != artifact["digest"]:
            raise SourceError("source artifact size or digest differs")
        os.replace(temporary, path)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        temporary.unlink(missing_ok=True)
        raise SourceError(f"source download failed: {error}") from error
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def extract(archive_path: pathlib.Path, destination: pathlib.Path, version: str) -> None:
    """Extract a regular-file-only, relative-path artifact without following symlinks."""
    expected = {
        "SHA256SUMS",
        "tapebasis-image.tar",
        f"tapebasis-{version}-py3-none-any.whl",
        f"tapebasis-{version}.tar.gz",
        f"tapebasis-{version}.tgz",
    }
    destination.mkdir(exist_ok=True)
    if not destination.resolve().is_dir() or destination.is_symlink():
        raise SourceError("artifact destination is unsafe")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = {entry.filename for entry in entries}
        if len(names) != len(entries) or not expected <= names:
            raise SourceError("source ZIP is incomplete or contains duplicate paths")
        for entry in entries:
            path = pathlib.PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or file_type not in {0, stat.S_IFREG}:
                raise SourceError(f"source ZIP contains unsafe path {entry.filename!r}")
            target = destination.joinpath(*path.parts)
            with archive.open(entry) as source, target.open("xb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)


def main(argv: list[str]) -> int:
    """Fetch an immutable source artifact and emit its verified version and digest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--zip", type=pathlib.Path, default=pathlib.Path("source-artifacts.zip"))
    parser.add_argument("--dist", type=pathlib.Path, default=pathlib.Path("dist"))
    parser.add_argument("--server", type=pathlib.Path, default=pathlib.Path("recovered-server.json"))
    args = parser.parse_args(argv)
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    current = os.environ.get("GITHUB_SHA", "")
    requested_tag = os.environ.get("REQUIRED_TAG", "")
    if not args.run_id.isdecimal() or not args.token:
        parser.error("the run id and GitHub API token are required")
    if not REPOSITORY.fullmatch(repository) or not COMMIT.fullmatch(current) or not os.environ.get("GITHUB_OUTPUT"):
        parser.error("repository, current commit and GitHub output environment are required")
    headers = {"Authorization": f"Bearer {args.token}", "Accept": "application/vnd.github+json", "User-Agent": "tapebasis-recovery"}
    try:
        root = pathlib.Path(__file__).resolve().parents[1]
        version, local_server = load_metadata(root)
        if requested_tag != f"v{version}":
            raise SourceError(f"requested tag must be v{version}, not {requested_tag!r}")
        base = f"{API}/repos/{repository}"
        run = _api(f"{base}/actions/runs/{args.run_id}", headers)
        jobs = _api(f"{base}/actions/runs/{args.run_id}/jobs?per_page=100", headers)
        artifact_page = _api(f"{base}/actions/runs/{args.run_id}/artifacts", headers)
        if jobs.get("total_count", 0) > 100 or artifact_page.get("total_count", 0) > 100:
            raise SourceError("source jobs or artifacts require pagination")
        artifacts = [item for item in artifact_page.get("artifacts", []) if item.get("name") == "release-artifacts"]
        if len(artifacts) != 1:
            raise SourceError("source must have exactly one release-artifacts entry")
        artifact = artifacts[0]
        validate_source(run, jobs.get("jobs", []), artifact, version, current)
        if run.get("repository", {}).get("full_name") != repository:
            raise SourceError("source repository differs")
        reference = _api(f"{base}/git/ref/tags/v{version}", headers)
        target = reference.get("object", {}).get("sha")
        if target != run["head_sha"]:
            if reference.get("object", {}).get("type") != "tag" or not COMMIT.fullmatch(target or ""):
                raise SourceError("source tag is not a valid annotated or lightweight tag")
            target = _api(f"{base}/git/tags/{target}", headers).get("object", {}).get("sha")
        if target != run["head_sha"]:
            raise SourceError("the immutable tag no longer points to the source commit")
        source_page = _api(f"{base}/contents/server.json?ref={run['head_sha']}", headers)
        source_server = parse_github_json_file(source_page)
        if source_server != local_server:
            raise SourceError("source MCP metadata differs from this recovery checkout")
        download(artifact, args.token, args.zip)
        extract(args.zip, args.dist, version)
        args.server.write_text(json.dumps(source_server, indent=2) + "\n", encoding="utf-8")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"version={version}\nartifact_digest={artifact['digest']}\n")
    except (SourceError, OSError, ValueError, KeyError, TypeError, urllib.error.URLError, zipfile.BadZipFile) as error:
        print(f"source artifact rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"run_id": int(args.run_id), "version": version, "artifact_digest": artifact["digest"], "tag_commit": run["head_sha"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
