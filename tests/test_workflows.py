"""Release workflow policy tests, independent of external registry services."""
from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_IF = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"


def _workflow(name: str) -> dict:
    """Load a GitHub Actions workflow while preserving its job and step order."""
    document = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
    assert document.get("on") or document.get(True), f"{name} has no trigger"
    return document


def _commands(job: dict) -> list[str]:
    """Return each action or shell step for order-sensitive workflow checks."""
    return [step.get("run", step.get("uses", "")) for step in job["steps"]]


def test_workflow_yaml_is_valid():
    """Every workflow parses as a mapping with triggers and jobs."""
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        assert document.get("on") or document.get(True)
        assert isinstance(document.get("jobs"), dict)


def test_external_actions_use_verified_commit_pins():
    """Every third-party action is pinned to a commit with a live-version comment."""
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*(\S+)@(\S+)(?:\s+#\s*(\S+))?", line)
            if match is None:
                continue
            owner, ref, version = match.groups()
            if owner.startswith("./"):
                continue
            assert re.fullmatch(r"[0-9a-f]{40}", ref), (path.name, owner, ref)
            assert version and version.startswith("v"), (path.name, owner, version)


def test_setup_node_uses_declared_inputs_with_caching_disabled_by_default():
    """Node setup follows the pinned action's inputs instead of unsupported aliases."""
    for filename in ("test.yml", "release.yml"):
        for job in _workflow(filename)["jobs"].values():
            if job.get("uses"):
                continue
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/setup-node@"):
                    assert set(step["with"]) == {"node-version"}
                    assert step["with"]["node-version"] == "24"


def test_release_only_publishes_from_a_pushed_version_tag():
    """The sole publish job is tag-gated behind the protected release environment."""
    workflow = _workflow("release.yml")
    jobs = workflow["jobs"]
    assert list(jobs) == ["validate", "build", "publish"]
    publish = jobs["publish"]
    assert publish["if"] == PUBLISH_IF
    assert publish["environment"] == "release"
    assert publish["needs"] == "build"
    assert jobs["build"]["needs"] == "validate"
    assert jobs["validate"]["uses"] == "./.github/workflows/test.yml"
    for job in (jobs["validate"], jobs["build"]):
        assert "environment" not in job
        assert "if" not in job


def test_publication_permissions_and_failure_bypasses_are_limited():
    """Only publication receives OIDC and registry writes, without error bypasses."""
    workflow = _workflow("release.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "packages": "write",
        "attestations": "write",
    }
    for name in ("validate", "build"):
        assert "permissions" not in workflow["jobs"][name]
    content = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for forbidden in (
        "UV_PUBLISH_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN", "continue-on-error", "always()",
    ):
        assert forbidden not in content


def test_publish_requires_the_complete_checksummed_artifact_set():
    """Publication cannot rebuild or ignore a missing tested distribution."""
    jobs = _workflow("release.yml")["jobs"]
    steps = jobs["publish"]["steps"]
    commands = _commands(jobs["publish"])
    assert any("actions/download-artifact@" in command for command in commands)
    verification = next(command for command in commands if "sha256sum --check" in command)
    assert "sha256sum --check --strict SHA256SUMS" in verification
    for suffix in ("-py3-none-any.whl", ".tar.gz", ".tgz"):
        assert "test -f" in verification and suffix in verification
    assert "test -f dist/tapebasis-image.tar" in verification
    assert "check_oci_image.py dist/tapebasis-image.tar" in verification
    for filename in ("release.yml", "publish-image.yml"):
        content = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        assert "--ignore-missing" not in content
    for command in commands:
        assert "uv build" not in command
        assert "docker build" not in command
        assert "npm pack " not in command


def test_build_smoke_tests_artifacts_before_upload():
    """The release build exercises Python, npm, OCI and a real local image."""
    commands = _commands(_workflow("release.yml")["jobs"]["build"])
    joined = "\n".join(commands)
    assert "tests/smoke_test.py" in joined
    assert "npm pack --pack-destination dist" in joined
    assert "pytest -q tests/test_packaging.py -k npm" in joined
    assert "check_oci_image.py dist/tapebasis-image.tar" in joined
    assert "docker run --rm" in joined
    upload = next(index for index, command in enumerate(commands) if "actions/upload-artifact@" in command)
    for required in ("tests/smoke_test.py", "pytest -q", "docker run --rm"):
        index = next(index for index, command in enumerate(commands) if required in command)
        assert index < upload


def test_publication_order_stops_at_package_failures():
    """MCP metadata follows the ordered package uploads and their resolution check."""
    steps = _workflow("release.yml")["jobs"]["publish"]["steps"]
    commands = _commands(steps_to_job(steps))
    pypi = next(index for index, command in enumerate(commands) if "uv publish" in command)
    npm = next(index for index, command in enumerate(commands) if "npm publish" in command)
    oci = next(index for index, command in enumerate(commands) if "regctl image import" in command)
    resolves = next(index for index, command in enumerate(commands) if "published artifact" in command)
    registry = next(index for index, command in enumerate(commands) if command.strip() == "./mcp-publisher publish")
    assert pypi < npm < oci < resolves < registry
    joined = "\n".join(commands)
    assert "dist.integrity" in joined
    assert "openssl dgst -sha512" in joined
    assert "NPM_BOOTSTRAPPED: ${{ vars.TAPEBASIS_NPM_BOOTSTRAPPED }}" in yaml.safe_dump(steps)
    assert '[ "$NPM_BOOTSTRAPPED" != "1" ]' in joined
    assert len([command for command in commands if "npm publish" in command]) == 1
    assert "login github-oidc" in joined
    assert "cosign verify-blob" in joined
    assert "MCP_PUBLISHER_SHA256" in joined
    assert "--trusted-publishing always" in joined


def steps_to_job(steps: list[dict]) -> dict:
    """Wrap publish steps for the shared order-inspection helper."""
    return {"steps": steps}


def test_release_identity_is_validated_without_self_updates():
    """The tag and predecessor are validated and CI never changes versions."""
    content = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    first = yaml.safe_load(content)["jobs"]["build"]["steps"][0]
    assert first["with"]["fetch-depth"] == 0
    assert 'check_release.py --tag "$REF_NAME"' in content
    assert '--against "$previous"' in content
    assert re.search(r"(?:version|npm version)\s+(?:--|set)", content) is None


def test_main_and_pull_request_validation_jobs_have_no_upload_capability():
    """Test and artifact-build jobs receive neither registry identity nor login."""
    for filename in ("release.yml", "test.yml", "publish-image.yml"):
        for job in _workflow(filename)["jobs"].values():
            if job.get("uses"):
                continue
            if job.get("environment"):
                assert filename == "release.yml"
                assert job["if"] == PUBLISH_IF
                continue
            content = yaml.safe_dump(job)
            for forbidden in (
                "ghcr.io", "docker/login-action", "packages: write", "id-token: write",
                "npm publish", "uv publish", "mcp-publisher publish",
            ):
                assert forbidden not in content


def test_test_workflow_checks_python_and_npm():
    """CI runs source tests, package smoke tests and launcher tests without publishing."""
    workflow = _workflow("test.yml")
    assert workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"] == [
        "3.10", "3.11", "3.12", "3.13",
    ]
    content = yaml.safe_dump(workflow)
    assert "node-version: '24'" in content or 'node-version: "24"' in content
    for command in (
        "npm ci", "npm run check", "npm test", "npm pack --dry-run", ".venv/bin/python -m pytest -q",
    ):
        assert command in content
    for forbidden in ("npm publish", "uv publish", "id-token: write", "packages: write"):
        assert forbidden not in content


def test_old_image_workflow_only_calls_the_test_suite():
    """The existing workflow entry point cannot become a second publisher."""
    workflow = _workflow("publish-image.yml")
    assert list(workflow["jobs"]) == ["validation"]
    assert workflow["jobs"]["validation"]["uses"] == "./.github/workflows/test.yml"
    content = (ROOT / ".github/workflows/publish-image.yml").read_text(encoding="utf-8")
    assert not content.startswith("//")
    for forbidden in ("docker/login-action", "packages: write", "id-token: write", "ghcr.io"):
        assert forbidden not in content
