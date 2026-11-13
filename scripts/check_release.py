#!/usr/bin/env python3
"""Validate distribution and registry metadata before a release.

Run ``python scripts/check_release.py --tag v1.2.3`` on a tag build, or
``python scripts/check_release.py`` on a branch. Exit status 0 means every
check passed, 1 means at least one check failed and 2 means usage was wrong.
Use ``--root`` to validate another checkout, which the tests do.

The checker never contacts a registry and never reads a token. It only proves
that the version, package names, ownership markers and release tag agree, so a
mismatch stops the workflow before any publish job can run.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = {
    "pyproject": "pyproject.toml",
    "init": "src/tapebasis/__init__.py",
    "package": "package.json",
    "lock": "package-lock.json",
    "server": "server.json",
}
VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
NPM_NAME = re.compile(r"(?:@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*")
SERVER_NAME = re.compile(r"[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+")
GIT_CONTEXT = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
    "GIT_GRAFT_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
}


def _git_environment() -> dict[str, str]:
    """Return the environment with a parent git operation's repository bindings removed."""
    return {key: value for key, value in os.environ.items() if key not in GIT_CONTEXT}


def _read(relative: str) -> str:
    """Return a UTF-8 repository file, raising the original ``OSError`` when absent."""
    return (ROOT / relative).read_text(encoding="utf-8")


def _project(text: str) -> dict:
    """Return the ``[project]`` table parsed as TOML on every supported Python."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    return tomllib.loads(text).get("project", {})


def _git_version(ref: str) -> tuple[bool, str | None]:
    """Return whether ``ref`` resolves and the project version it carries."""
    result = subprocess.run(
        ["git", "show", f"{ref}:pyproject.toml"],
        cwd=ROOT,
        env=_git_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return False, None
    try:
        project = _project(result.stdout)
    except ValueError:
        return True, None
    version = project.get("version")
    return True, version if isinstance(version, str) and version else None


def _load_json(relative: str, errors: list[str]) -> object | None:
    """Return parsed JSON, recording a readable error instead of raising."""
    try:
        text = _read(relative)
    except OSError as exc:
        errors.append(f"{relative}: cannot read ({exc.strerror or exc})")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{relative}: invalid JSON at line {exc.lineno}: {exc.msg}")
        return None


def _matching_packages(packages: object, package: dict, pypi_name: str, version: str) -> bool:
    """Return whether registry entries name this npm and PyPI package at ``version``."""
    if not isinstance(packages, list):
        return False
    entries = {
        entry.get("registryType"): entry
        for entry in packages
        if isinstance(entry, dict) and isinstance(entry.get("registryType"), str)
    }
    npm = entries.get("npm", {})
    pypi = entries.get("pypi", {})
    return (
        npm.get("identifier") == package.get("name")
        and npm.get("version") == version
        and npm.get("registryBaseUrl") == "https://registry.npmjs.org"
        and npm.get("transport") == {"type": "stdio"}
        and pypi.get("identifier") == pypi_name
        and pypi.get("version") == version
        and pypi.get("registryBaseUrl") == "https://pypi.org"
        and pypi.get("transport") == {"type": "stdio"}
    )


def collect(tag: str | None, against: str | None) -> list[str]:
    """Return every metadata mismatch in the checkout, without raising on bad input."""
    errors: list[str] = []
    try:
        project = _project(_read(FILES["pyproject"]))
    except OSError as exc:
        errors.append(f"{FILES['pyproject']}: cannot read ({exc.strerror or exc})")
        project = {}
    except ValueError as exc:
        errors.append(f"{FILES['pyproject']}: invalid TOML: {exc}")
        project = {}
    pypi_name = project.get("name")
    version = project.get("version")
    if not isinstance(pypi_name, str) or not PROJECT_NAME.fullmatch(pypi_name):
        errors.append(f"{FILES['pyproject']}: [project].name must be a distribution name")
        pypi_name = "tapebasis"
    if not isinstance(version, str) or not version:
        errors.append(f"{FILES['pyproject']}: [project].version must be a quoted string")
        version = "<invalid>"
    elif not VERSION.fullmatch(version):
        errors.append(f"{FILES['pyproject']}: unsupported release version {version!r}")

    try:
        init = _read(FILES["init"])
    except OSError as exc:
        errors.append(f"{FILES['init']}: cannot read ({exc.strerror or exc})")
    else:
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
        if not match:
            errors.append(f"{FILES['init']}: __version__ must be a quoted string")
        elif match.group(1) != version:
            errors.append(f"{FILES['init']}: expected __version__={version!r}")

    package = _load_json(FILES["package"], errors)
    if not isinstance(package, dict):
        package = {}
    name = package.get("name")
    if not isinstance(name, str) or not NPM_NAME.fullmatch(name):
        errors.append('package.json: "name" must be a valid npm package name')
    if package.get("version") != version:
        errors.append(f"package.json: expected version {version!r}")
    mcp_name = package.get("mcpName")
    if not isinstance(mcp_name, str) or not mcp_name:
        errors.append('package.json: "mcpName" is required')
    repo = package.get("repository")
    if not isinstance(repo, dict) or not repo.get("url"):
        errors.append('package.json: repository.url is required for trusted publishing')
    if not package.get("license"):
        errors.append('package.json: "license" is required')
    files = package.get("files")
    if not isinstance(files, list) or not files:
        errors.append('package.json: "files" is required to keep the tarball thin')
    bin_entries = package.get("bin")
    if not isinstance(bin_entries, dict) or not isinstance(bin_entries.get("tapebasis"), str):
        errors.append('package.json: bin.tapebasis is required for the launcher')
    else:
        launcher = bin_entries["tapebasis"]
        if not (ROOT / launcher).is_file():
            errors.append(f"package.json: bin.tapebasis points at missing {launcher!r}")
    publish = package.get("publishConfig")
    if not isinstance(publish, dict):
        publish = {}
    if publish.get("registry") != "https://registry.npmjs.org":
        errors.append("package.json: publishConfig.registry must be https://registry.npmjs.org")
    if publish.get("access") != "public":
        errors.append('package.json: publishConfig.access must be "public"')

    lock = _load_json(FILES["lock"], errors)
    if not isinstance(lock, dict):
        lock = {}
    if lock.get("version") != version:
        errors.append(f"package-lock.json: expected version {version!r}")
    if lock.get("name") != name:
        errors.append("package-lock.json: package name does not match package.json")
    root_entry = lock.get("packages", {}).get("") if isinstance(lock.get("packages"), dict) else None
    if not isinstance(root_entry, dict):
        errors.append('package-lock.json: packages[""] entry is required')
    else:
        if root_entry.get("version") != version:
            errors.append(f'package-lock.json: packages[""].version must be {version!r}')
        if root_entry.get("name") != name:
            errors.append('package-lock.json: packages[""].name must match package.json')

    server = _load_json(FILES["server"], errors)
    if not isinstance(server, dict):
        server = {}
    server_name = server.get("name")
    if not isinstance(server_name, str) or not SERVER_NAME.fullmatch(server_name):
        errors.append("server.json: name must be a reverse-DNS name with one slash")
    if server.get("version") != version:
        errors.append(f"server.json: expected version {version!r}")
    description = server.get("description")
    if not isinstance(description, str) or not description:
        errors.append("server.json: description is required")
    elif len(description) > 100:
        errors.append(f"server.json: description is {len(description)} characters, maximum 100")
    if mcp_name != server_name:
        errors.append("package.json: mcpName must match server.json name")
    try:
        readme = _read("README.md")
    except OSError as exc:
        errors.append(f"README.md: cannot read ({exc.strerror or exc})")
    else:
        marker = f"<!-- mcp-name: {server_name} -->"
        if marker not in readme:
            errors.append(f"README.md: missing registry marker {marker!r}")
    if not _matching_packages(server.get("packages", []), package, pypi_name, version):
        errors.append(
            "server.json: npm and PyPI entries must name the declared packages at this version"
        )

    if tag is not None:
        if not VERSION.fullmatch(tag.removeprefix("v")) or tag != f"v{version}":
            errors.append(f"tag {tag!r} must be v{version}")
    if against is not None:
        exists, base = _git_version(against)
        if not exists:
            errors.append(f"cannot read pyproject.toml from git ref {against!r}")
        elif base is None:
            errors.append(f"git ref {against!r} carries no project version")
        elif not VERSION.fullmatch(base):
            errors.append(f"git ref {against!r} carries unsupported project version {base!r}")
        elif not VERSION.fullmatch(version):
            pass  # The invalid working version is already reported above.
        elif base == version:
            errors.append(f"version {version} is unchanged since {against}; bump it for the release")
        elif tuple(map(int, re.findall(r"\d+", version)[:3])) <= tuple(
            map(int, re.findall(r"\d+", base)[:3])
        ):
            errors.append(f"version {version} is not newer than {base} from {against}")
    return errors


def main(argv: list[str]) -> int:
    """Print validation findings and return the process exit status."""
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of lines")
    parser.add_argument("--tag", help="candidate tag to compare with the declared version")
    parser.add_argument("--against", help="git ref whose version must be lower than this release")
    parser.add_argument("--root", type=pathlib.Path, help="checkout to validate (default: this one)")
    args = parser.parse_args(argv)
    if args.root is not None:
        ROOT = args.root.resolve()
    errors = collect(args.tag, args.against)
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    else:
        for error in errors:
            print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
