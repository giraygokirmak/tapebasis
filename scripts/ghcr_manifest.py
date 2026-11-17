#!/usr/bin/env python3
"""Classify GHCR manifests by registry HTTP status and the exact tested digest.

Only HTTP 404 means absence. Transport, authorization and malformed-response
failures are terminal. This helper never changes an image or writes credentials.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))


class ManifestError(Exception):
    """Reject a lookup that cannot safely authorize a manifest write."""


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Remove registry credentials before following a redirect to another origin."""

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


def _response(request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
    """Return a bounded response with normalized HTTP header names."""
    with OPENER.open(request, timeout=60) as response:
        body = response.read(16385)
        if len(body) > 16384:
            raise ManifestError("GHCR returned an oversized response")
        return response.status, {
            key.lower(): value for key, value in response.headers.items()
        }, body


def pull_token(repository: str, owner: str = "", token: str = "") -> str:
    """Read a scoped GHCR pull token, keeping all credential errors terminal."""
    query = urllib.parse.urlencode({
        "service": "ghcr.io", "scope": f"repository:{repository}:pull",
    })
    request = urllib.request.Request(f"https://ghcr.io/token?{query}", headers={
        "Accept": "application/json", "User-Agent": "tapebasis-ghcr-verifier",
    })
    if token:
        if not owner:
            raise ManifestError("a repository owner is required with GHCR_TOKEN")
        credentials = base64.b64encode(f"{owner}:{token}".encode()).decode()
        request.add_header("Authorization", f"Basic {credentials}")
    try:
        status, headers, body = _response(request)
    except urllib.error.HTTPError as error:
        error.close()
        raise ManifestError(f"GHCR token lookup returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ManifestError(f"GHCR token lookup failed: {error}") from error
    if status != 200 or "application/json" not in headers.get("content-type", "").lower():
        raise ManifestError("GHCR token endpoint did not return JSON")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError("GHCR token endpoint returned malformed JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("token"), str) or not document["token"]:
        raise ManifestError("GHCR token endpoint returned no usable token")
    return document["token"]


def manifest_status(repository: str, tag: str, expected: str,
                    owner: str = "", token: str = "") -> tuple[int, str]:
    """Return match, mismatch, absence or a terminal error for one image tag."""
    if not REPOSITORY.fullmatch(repository) or not DIGEST.fullmatch(expected):
        raise ManifestError("a valid repository and tested root digest are required")
    if not tag or "/" in tag or "\\" in tag or any(character.isspace() for character in tag):
        raise ManifestError("an image tag must be one nonempty safe reference")
    bearer = pull_token(repository, owner, token)
    reference = urllib.parse.quote(tag, safe="")
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{repository}/manifests/{reference}", method="HEAD",
        headers={
            "Authorization": f"Bearer {bearer}", "Accept": ACCEPT,
            "User-Agent": "tapebasis-ghcr-verifier",
        },
    )
    try:
        status, headers, _body = _response(request)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return 2, "manifest absent (HTTP 404)"
        raise ManifestError(f"GHCR manifest lookup returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ManifestError(f"GHCR manifest lookup failed: {error}") from error
    if status != 200:
        raise ManifestError(f"GHCR manifest lookup returned HTTP {status}")
    digest = headers.get("docker-content-digest", "")
    if not DIGEST.fullmatch(digest):
        raise ManifestError("GHCR returned no valid manifest digest")
    if digest != expected:
        return 1, f"manifest digest {digest}, expected tested image {expected}"
    return 0, digest


def main(argv: list[str]) -> int:
    """Print one safe lookup result and map it to the shell verifier's status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected", required=True)
    # The production API origin remains fixed; the shell test injects its lookup helper.
    args = parser.parse_args(argv)
    try:
        status, result = manifest_status(
            args.repository, args.tag, args.expected,
            os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
            os.environ.get("GHCR_TOKEN", ""),
        )
    except ManifestError as error:
        print(f"GHCR {args.tag} lookup failed: {error}", file=sys.stderr)
        return 3
    print(result, file=sys.stderr if status else sys.stdout)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
