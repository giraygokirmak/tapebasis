#!/usr/bin/env python3
"""Create or update a tag's GitHub Release from its reviewed changelog section.

The caller supplies a source commit already bound to the tested release artifacts.
This helper verifies that live tag target again, then writes only release notes.
It never moves a tag or uploads a registry package or image.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

COMMIT = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")


class NotesError(Exception):
    """Reject an unsupported version, unsuitable note or GitHub API failure."""


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Remove repository credentials before following a redirect to another origin."""

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


def section(path: pathlib.Path, version: str) -> str:
    """Return the complete reviewed changelog section for one declared version."""
    try:
        document = path.read_text(encoding="utf-8")
    except OSError as error:
        raise NotesError(f"cannot read changelog: {error}") from error
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*$", re.MULTILINE)
    matches = list(pattern.finditer(document))
    if len(matches) != 1:
        raise NotesError(f"changelog must contain exactly one {version} section")
    start = matches[0].end()
    following = re.search(r"^## ", document[start:], re.MULTILINE)
    end = start + following.start() if following else len(document)
    summary = "\n".join(
        line for line in document[start:end].strip().splitlines()
        if not re.match(r"^\[[0-9]+(?:\.[0-9]+){2}[^]]*\]:\s+\S+", line)
    ).strip()
    if not summary:
        raise NotesError(f"changelog {version} section is empty")
    return summary + "\n"


def request(url: str, token: str, method: str = "GET", payload: dict | None = None,
            missing_ok: bool = False) -> dict | None:
    """Return a GitHub JSON object or None only for an allowed missing Release."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise NotesError("release notes allow only the GitHub API origin")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "tapebasis-release-notes",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with OPENER.open(req, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise NotesError(f"GitHub returned HTTP {error.code} for {error.url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise NotesError(f"GitHub release-notes request failed: {error}") from error
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotesError("GitHub release-notes response is not JSON") from error
    if not isinstance(document, dict):
        raise NotesError("GitHub release-notes response is not an object")
    return document


def verify_tag(repository: str, token: str, tag: str, expected_commit: str) -> None:
    """Require an annotated or lightweight live tag to resolve to the tested commit."""
    if not COMMIT.fullmatch(expected_commit):
        raise NotesError("a full tested source commit is required")
    base = f"https://api.github.com/repos/{repository}"
    reference = request(f"{base}/git/ref/tags/{urllib.parse.quote(tag, safe='')}", token)
    target = reference.get("object", {})
    sha = target.get("sha")
    if target.get("type") == "tag" and COMMIT.fullmatch(sha or ""):
        annotated = request(f"{base}/git/tags/{sha}", token)
        sha = annotated.get("object", {}).get("sha")
    if target.get("type") not in {"commit", "tag"} or sha != expected_commit:
        raise NotesError("the immutable tag does not point to the tested source commit")


def notes_arguments(repository: str, ref_name: str, version: str, commit: str) -> bool:
    """Validate a release job's ref outputs and return whether to publish notes."""
    if not ref_name and not version:
        return False
    if not REPOSITORY.fullmatch(repository) or not VERSION.fullmatch(version):
        raise NotesError("release notes need a valid repository and semantic version")
    if ref_name != f"v{version}" or not COMMIT.fullmatch(commit):
        raise NotesError("release ref, source version and source commit must agree")
    return True


def publish(repository: str, token: str, tag: str, version: str, body: str,
            expected_commit: str) -> str:
    """Verify the live tag and create or synchronize only its reviewed notes."""
    verify_tag(repository, token, tag, expected_commit)
    base = f"https://api.github.com/repos/{repository}/releases"
    current = request(f"{base}/tags/{tag}", token, missing_ok=True)
    title = f"Tapebasis {version}"
    # This tag already exists and verify_tag bound it to expected_commit. Sending
    # target_commitish anyway makes GitHub require separate workflow-modification
    # authority when that old commit changed workflows, which GITHUB_TOKEN cannot have.
    values = {"tag_name": tag, "name": title, "body": body}
    if current:
        if current.get("tag_name") != tag or current.get("draft") or current.get("prerelease"):
            raise NotesError("existing GitHub Release identity or release kind differs")
        result = request(f"{base}/{current['id']}", token, method="PATCH", payload=values)
    else:
        result = request(base, token, method="POST", payload=values)
    if result.get("tag_name") != tag or result.get("name") != title or result.get("body") != body:
        raise NotesError("GitHub Release response differs from the requested notes")
    confirmed = request(f"{base}/tags/{tag}", token)
    if confirmed != result:
        raise NotesError("published GitHub Release notes do not read back identically")
    print(json.dumps({"tag": tag, "name": result.get("name"), "release_id": result.get("id")}))
    return "verified"


def main(argv: list[str]) -> int:
    """Publish a reviewed version summary and report its GitHub Release identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--changelog", type=pathlib.Path, default=pathlib.Path("CHANGELOG.md"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args(argv)
    try:
        if not REPOSITORY.fullmatch(args.repository):
            raise NotesError("a valid repository identity is required")
        if not VERSION.fullmatch(args.version) or args.tag != f"v{args.version}":
            raise NotesError("tag and changelog version must agree")
        body = section(args.changelog, args.version)
        publish(args.repository, args.token, args.tag, args.version, body, args.commit)
    except (NotesError, ValueError, TypeError, KeyError) as error:
        print(f"release notes failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
