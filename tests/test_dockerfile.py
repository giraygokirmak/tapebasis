"""Deployment contract tests for the Docker image (no daemon needed).

These read the files as text on purpose: `docker build` is not available in CI,
but the two properties that decide whether the container leaks processes and
whether it shuts down gracefully are both visible in the files.

The bug these pin: Docker starts the `HEALTHCHECK` (and every `docker exec`)
inside the container's PID namespace, with a parent that lives outside it. The
process is reparented to PID 1, and a PID 1 that never calls `wait()` leaves it
behind as a zombie, one every 30 seconds. Running the server under an init
fixes it, so an init must be present either in the image or in the compose
service, and the entrypoint must actually be the init.

Static build-context assertions also keep environment files, credential names,
source-control state, tests and local environments out of the image. The
package-data assertion protects the symbol lists that the runtime needs.
"""
from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
DOCKERIGNORE = ROOT / ".dockerignore"


def _instructions() -> list[str]:
    """Dockerfile instructions with comments and line continuations resolved."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    joined = text.replace("\\\n", " ")
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_image_installs_an_init():
    assert any(
        instruction.startswith("RUN") and "tini" in instruction
        for instruction in _instructions()
    ), "the runtime stage must install tini, or nothing reaps reparented processes"


def test_entrypoint_runs_the_server_under_the_init():
    entrypoints = [
        instruction
        for instruction in _instructions()
        if instruction.startswith("ENTRYPOINT")
    ]
    assert entrypoints, "no ENTRYPOINT"
    argv = json.loads(entrypoints[-1].split(" ", 1)[1])
    assert argv[0].endswith("tini"), (
        "the server must be exec'd by tini, not run as PID 1 itself: " + repr(argv)
    )
    # `tini -- <command>`: the separator has to be there, otherwise tini treats
    # the server's arguments as its own.
    assert argv[1] == "--", argv
    assert argv[2].endswith("tapebasis"), argv


def test_entrypoint_still_starts_the_http_server():
    cmds = [
        instruction for instruction in _instructions() if instruction.startswith("CMD")
    ]
    assert cmds, "no CMD"
    argv = json.loads(cmds[-1].split(" ", 1)[1])
    assert argv[0] == "streamable-http"
    assert "--host" in argv and argv[argv.index("--host") + 1] == "0.0.0.0"
    assert "--port" in argv and argv[argv.index("--port") + 1] == "8000"


def test_compose_also_enables_init():
    """Compose covers the case where the image is swapped for one without tini."""
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    service = next(
        index for index, line in enumerate(lines) if line.strip() == "tapebasis:"
    )
    own = []
    for line in lines[service + 1:]:
        if line.strip() and not line.startswith(" "):
            break  # next top-level key: the service block ended
        if line.strip().startswith("init:"):
            own.append(line)
    assert own == ["    init: true"], own


def _dockerignore_patterns() -> list[str]:
    """Return active Docker ignore rules without comments or blank lines."""
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize(
    "pattern",
    [
        ".env*",
        "!.env.example",
        ".git/",
        ".venv/",
        "venv/",
        ".tapebasis/",
        "tests/",
        "docs/",
        "__pycache__/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*token*",
        "*secret*",
        "*credential*",
        "secrets/",
        ".secrets/",
    ],
)
def test_build_context_excludes_secrets_and_non_runtime_files(pattern):
    """The context must carry ignore rules for local credentials and state."""
    assert pattern in _dockerignore_patterns()


def test_dockerfile_never_copies_the_checkout_into_an_image():
    """Build only selected distribution inputs, never `COPY . .` or the tree."""
    for instruction in _instructions():
        if not instruction.startswith("COPY "):
            continue
        assert "/app /app" not in instruction, instruction
        parts = instruction.split()
        sources = parts[1:-1]
        assert "." not in sources, instruction
        assert not any(source == "/app" for source in sources), instruction


def test_runtime_contains_installed_package_not_a_checkout():
    """Only installed dependencies may cross from the builder into runtime."""
    assert not any(
        instruction.startswith("COPY --from=builder /app")
        for instruction in _instructions()
    )
    assert "COPY --from=builder /usr/local/bin/tapebasis /usr/local/bin/tapebasis" in (
        _instructions()
    )


def test_environment_example_may_remain_in_build_context():
    """The ignore exception preserves the documented non-secret template."""
    assert not _dockerignore_matches(PurePosixPath(".env.example"))
    assert _dockerignore_matches(PurePosixPath(".env"))
    assert _dockerignore_matches(PurePosixPath("production.env"))


def test_packaged_coinlists_remain_a_build_input():
    """The explicit `src` COPY and package-data rule retain symbol lists."""
    assert "COPY src/ ./src/" in _instructions()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tapebasis = ["providers/tradingview/coinlist/*.txt"]' in pyproject
    coinlists = list(
        (ROOT / "src/tapebasis/providers/tradingview/coinlist").glob("*.txt")
    )
    assert coinlists, "the distribution must include the coinlist data files"
    for path in coinlists:
        relative = PurePosixPath(path.relative_to(ROOT))
        assert not _dockerignore_matches(relative)


def _distribution_input_paths() -> list[PurePosixPath]:
    """Resolve the explicit source COPY while excluding generated egg metadata."""
    source = ROOT / "src"
    return [
        PurePosixPath(path.relative_to(ROOT))
        for path in source.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
    ]


def test_required_distribution_inputs_survive_dockerignore():
    """Every real package module and resource remains available to the build."""
    for relative in _distribution_input_paths():
        assert not _dockerignore_matches(relative), relative


def _dockerignore_matches(relative: PurePosixPath) -> bool:
    """Check whether the checked build rules exclude a repository path."""
    ignored = False
    for pattern in _dockerignore_patterns():
        excluded = not pattern.startswith("!")
        pattern = pattern.removeprefix("!").lstrip("/")
        if pattern.endswith("/") and pattern[:-1] not in relative.parts[:-1]:
            continue
        pattern = pattern.rstrip("/")
        if "/" not in pattern:
            matched = any(fnmatchcase(part, pattern) for part in relative.parts)
        else:
            matched = relative.match(pattern) or any(
                parent.match(pattern) for parent in relative.parents
            )
        if matched:
            ignored = excluded
    return ignored


def test_compose_publishes_only_to_loopback_unless_an_operator_overrides_it():
    """The unauthenticated HTTP service must not default to a public host port."""
    compose = COMPOSE.read_text(encoding="utf-8").splitlines()
    assert any(
        line.strip() == '- "${TAPEBASIS_BIND_ADDRESS:-127.0.0.1}:6013:8000"'
        for line in compose
    )
    assert not any(line.strip() == '- "6013:8000"' for line in compose)
