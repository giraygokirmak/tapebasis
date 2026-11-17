#!/usr/bin/env python3
"""Compare public registry versions with tested release files without uploading.

Only an HTTP 404 means that a version is missing. Any other transport error,
malformed response, or conflicting content is a release-stopping failure.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class RegistryError(Exception):
    """Report an unavailable, malformed, or inconsistent registry result."""


def _get(url: str, missing_ok: bool = False) -> bytes | None:
    """Return public response bytes, or None only for an allowed HTTP 404."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "tapebasis-release-verifier", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise RegistryError(f"registry returned HTTP {error.code} for {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RegistryError(f"registry request failed for {url}: {error}") from error


def _json(url: str, missing_ok: bool = False) -> dict | None:
    """Return a JSON object from one public registry endpoint."""
    body = _get(url, missing_ok)
    if body is None:
        return None
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryError(f"registry returned invalid JSON from {url}") from error
    if not isinstance(document, dict):
        raise RegistryError(f"registry did not return an object from {url}")
    return document


def _local(directory: pathlib.Path, filename: str) -> bytes:
    """Read one named distribution, rejecting traversal and missing artifacts."""
    if pathlib.PurePosixPath(filename).name != filename:
        raise RegistryError(f"unsafe artifact filename {filename!r}")
    try:
        return (directory / filename).read_bytes()
    except OSError as error:
        raise RegistryError(f"cannot read release artifact {filename}: {error}") from error


def pypi_artifacts(package: str, version: str) -> tuple[str, str]:
    """Return the wheel and sdist filenames that form one complete PyPI release."""
    return f"{package}-{version}-py3-none-any.whl", f"{package}-{version}.tar.gz"


def inspect_pypi(package: str, version: str, directory: pathlib.Path) -> tuple[str, list[str]]:
    """Verify each existing file and return the release status and truly absent names."""
    endpoint = f"https://pypi.org/pypi/{urllib.parse.quote(package, safe='')}/{urllib.parse.quote(version, safe='')}/json"
    document = _json(endpoint, missing_ok=True)
    expected = pypi_artifacts(package, version)
    if document is None:
        return "missing", list(expected)
    entries = document.get("urls")
    if not isinstance(entries, list):
        raise RegistryError("PyPI response has no distribution list")
    if not entries:
        raise RegistryError("PyPI release returned no distribution files")
    if any(not isinstance(entry, dict) for entry in entries):
        raise RegistryError("PyPI returned a malformed distribution entry")
    names = [entry.get("filename") for entry in entries]
    if len(set(names)) != len(names) or any(name not in expected for name in names):
        raise RegistryError("PyPI distribution names differ from the tested release")
    for entry in entries:
        filename = entry["filename"]
        local = _local(directory, filename)
        if entry.get("digests", {}).get("sha256") != hashlib.sha256(local).hexdigest():
            raise RegistryError(f"PyPI SHA-256 differs from tested {filename}")
        url = entry.get("url", "")
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme != "https":
            raise RegistryError("PyPI distribution URL is not HTTPS")
        if _get(url) != local:
            raise RegistryError(f"PyPI bytes differ from tested {filename}")
    missing = [name for name in expected if name not in names]
    if not missing:
        return "verified", []
    return "partial", missing


def check_pypi(package: str, version: str, directory: pathlib.Path) -> str:
    """Return verified, missing or partial after comparing every existing PyPI file."""
    return inspect_pypi(package, version, directory)[0]


def check_npm(package: str, version: str, directory: pathlib.Path) -> str:
    """Return missing or verify the existing npm tarball's SHA-512 integrity."""
    endpoint = f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='@')}/{urllib.parse.quote(version, safe='')}"
    document = _json(endpoint, missing_ok=True)
    if document is None:
        return "missing"
    if document.get("version") != version:
        raise RegistryError(f"npm does not serve required {package}@{version}")
    local = _local(directory, f"{package.rsplit('/', 1)[-1]}-{version}.tgz")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(local).digest()).decode("ascii")
    if document.get("dist", {}).get("integrity") != integrity:
        raise RegistryError("npm integrity differs from the tested tarball")
    return "verified"


def await_package(check, package: str, version: str) -> str:
    """Allow a successful upload to become visible without retrying the upload.

    Only ``missing`` or ``partial`` results are retried. A partial release still
    fails after the bounded wait. Conflicts and other errors remain fatal.
    The return value is the checker's successfully verified status.
    """
    try:
        timeout = float(os.environ.get("REGISTRY_PUBLISH_TIMEOUT_SECONDS", "90"))
        interval = float(os.environ.get("REGISTRY_PUBLISH_RETRY_SECONDS", "5"))
    except ValueError as error:
        raise RegistryError("registry publication wait values must be numbers") from error
    if not math.isfinite(timeout) or not math.isfinite(interval) or timeout < 0 or interval <= 0:
        raise RegistryError("registry publication wait needs a nonnegative timeout and positive interval")
    deadline = time.monotonic() + timeout
    while True:
        status = check(package, version)
        if status not in {"missing", "partial"}:
            if status != "verified":
                raise RegistryError(f"{package} {version} status {status!r} is not verified")
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RegistryError(
                f"{package} {version} remains {status} after {timeout:g} seconds"
            )
        time.sleep(min(interval, remaining))


def check_mcp(server: dict, version: str) -> str:
    """Return missing only when this exact MCP version is absent, or verify equality."""
    name = server.get("name")
    if not isinstance(name, str) or not name:
        raise RegistryError("server.json has no name")
    if server.get("version") != version:
        raise RegistryError("server.json version differs from the release version")
    query = urllib.parse.urlencode({"search": name})
    document = _json(f"https://registry.modelcontextprotocol.io/v0.1/servers?{query}")
    entries = document.get("servers") if document else None
    if not isinstance(entries, list):
        raise RegistryError("MCP Registry response has no servers list")
    matched = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("server"), dict):
            raise RegistryError("MCP Registry returned a malformed server entry")
        candidate = entry["server"]
        if candidate.get("name") == name and candidate.get("version") == version:
            matched.append(candidate)
    if not matched:
        return "missing"
    if len(matched) != 1 or matched[0] != server:
        raise RegistryError(f"MCP Registry metadata differs for {name} version {version}")
    return "verified"


def main(argv: list[str]) -> int:
    """Run a read-only comparison and optionally append its GitHub output status."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for registry in ("pypi", "npm"):
        child = subparsers.add_parser(registry)
        child.add_argument("--version", required=True)
        child.add_argument("--dist", required=True, type=pathlib.Path)
        child.add_argument("--package", default="tapebasis")
        child.add_argument("--require-existing", action="store_true")
        child.add_argument(
            "--await-visible",
            action="store_true",
            help="retry only missing results for a bounded period after an upload",
        )
    mcp = subparsers.add_parser("mcp")
    mcp.add_argument("--version", required=True)
    mcp.add_argument("--server", required=True, type=pathlib.Path)
    for child in subparsers.choices.values():
        child.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "mcp":
            server = json.loads(args.server.read_text(encoding="utf-8"))
            status = check_mcp(server, args.version)
        else:
            checker = check_pypi if args.command == "pypi" else check_npm
            missing = []
            if args.command == "pypi" and not args.await_visible:
                status, missing = inspect_pypi(args.package, args.version, args.dist)
            elif args.await_visible:
                status = await_package(
                    lambda package, version: checker(package, version, args.dist),
                    args.package,
                    args.version,
                )
            else:
                status = checker(args.package, args.version, args.dist)
            if args.require_existing and status != "verified":
                raise RegistryError(f"{args.command} release is not fully verified; recovery cannot upload it")
        if args.output is not None:
            with args.output.open("a", encoding="utf-8") as stream:
                stream.write(f"{args.command}_status={status}\n")
                if args.command == "pypi":
                    wheel, sdist = pypi_artifacts(args.package, args.version)
                    stream.write(f"pypi_missing_wheel={str(wheel in missing).lower()}\n")
                    stream.write(f"pypi_missing_sdist={str(sdist in missing).lower()}\n")
    except (RegistryError, OSError, ValueError, TypeError) as error:
        print(f"release registry check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"registry": args.command, "version": args.version, "status": status}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
