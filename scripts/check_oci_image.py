#!/usr/bin/env python3
"""Validate a multi-platform OCI image archive before it is published.

The release build exports the image as an OCI layout tar. This reads that
archive without a registry or Docker daemon, checks that the requested
platforms are present in the image index, and checks the MCP Registry
ownership label on every platform's config. Exit status 0 means the archive is
valid, 1 means a check failed, and 2 means the command line was wrong.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tarfile
import tempfile
from typing import Any

SERVER_LABEL = "io.modelcontextprotocol.server.name"


def _load(directory: pathlib.Path, digest: str) -> dict[str, Any]:
    """Return the JSON blob stored under an OCI content digest."""
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256":
        raise ValueError(f"unsupported digest algorithm {algorithm!r}")
    path = directory / "blobs" / algorithm / value
    if not path.is_file():
        raise ValueError(f"missing blob {digest}")
    return json.loads(path.read_text(encoding="utf-8"))


def _platforms(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map each os/architecture pair in an image index to its descriptor."""
    return {
        f"{entry.get('platform', {}).get('os')}/{entry.get('platform', {}).get('architecture')}": entry
        for entry in index.get("manifests", [])
        if isinstance(entry, dict) and entry.get("platform")
    }


def validate(
    directory: pathlib.Path,
    expected: list[str],
    label: str = SERVER_LABEL,
    name: str = "io.github.giraygokirmak/tapebasis",
) -> list[str]:
    """Return every problem found in an extracted OCI layout directory."""
    errors: list[str] = []
    layout = directory / "oci-layout"
    index_path = directory / "index.json"
    if not layout.is_file() or not index_path.is_file():
        return [f"{directory}: not an OCI image layout"]
    index = json.loads(index_path.read_text(encoding="utf-8"))
    descriptors = index.get("manifests", [])
    if len(descriptors) != 1:
        return [f"{directory}: expected one root manifest, found {len(descriptors)}"]
    root = descriptors[0]
    document = _load(directory, root["digest"])
    if "manifests" not in document:
        return [f"{directory}: root manifest is not a multi-platform image index"]
    found = _platforms(document)
    for platform in expected:
        if platform not in found:
            errors.append(f"{directory}: missing platform {platform}")
            continue
        manifest = _load(directory, found[platform]["digest"])
        config = _load(directory, manifest["config"]["digest"])
        labels = config.get("config", {}).get("Labels") or {}
        if labels.get(label) != name:
            errors.append(
                f"{directory}: {platform} label {label!r} is {labels.get(label)!r}, expected {name!r}"
            )
        if not config.get("config", {}).get("Env"):
            errors.append(f"{directory}: {platform} config has no environment")
    return errors


def _extract(archive: pathlib.Path) -> tuple[pathlib.Path, tempfile.TemporaryDirectory]:
    """Extract an OCI layout tar and return its directory plus the cleanup owner."""
    temporary = tempfile.TemporaryDirectory(prefix="tapebasis-oci-")
    target = pathlib.Path(temporary.name)
    with tarfile.open(archive) as bundle:
        bundle.extractall(target, filter="data")
    return target, temporary


def root_digest(directory: pathlib.Path) -> str:
    """Return the SHA-256 digest of the sole multi-platform root image index."""
    descriptors = json.loads((directory / "index.json").read_text(encoding="utf-8")).get("manifests", [])
    if len(descriptors) != 1:
        raise ValueError(f"expected one root manifest, found {len(descriptors)}")
    root = descriptors[0]
    digest = root["digest"]
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256" or len(value) != 64:
        raise ValueError(f"unsupported root digest {digest!r}")
    return digest


def main(argv: list[str]) -> int:
    """Print OCI archive findings or its root digest, returning the process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=pathlib.Path, help="OCI layout tar built by buildx")
    parser.add_argument("--digest", action="store_true", help="print the tested root image-index digest")
    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        help="required platform, repeatable (default: linux/amd64 and linux/arm64)",
    )
    parser.add_argument("--label", default=SERVER_LABEL, help="config label to verify")
    parser.add_argument("--name", default="io.github.giraygokirmak/tapebasis", help="required label value")
    args = parser.parse_args(argv)
    platforms = args.platform or ["linux/amd64", "linux/arm64"]
    try:
        directory, temporary = _extract(args.archive)
    except (OSError, tarfile.TarError) as error:
        print(f"{args.archive}: cannot read OCI archive: {error}", file=sys.stderr)
        return 1
    try:
        errors = validate(directory, platforms, args.label, args.name)
        digest = root_digest(directory)
    except (OSError, ValueError, KeyError) as error:
        print(f"{args.archive}: invalid OCI archive: {error}", file=sys.stderr)
        return 1
    finally:
        temporary.cleanup()
    if args.digest and not errors:
        print(digest)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
