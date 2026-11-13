"""Release workflow policy tests, independent of external registry services."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name="release.yml"):
    """Return a parsed workflow document."""
    document = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    assert isinstance(document, dict) and isinstance(document.get("jobs"), dict)
    return document


def commands(job):
    """Return shell or action commands in workflow order."""
    return "\n".join(step.get("run", step.get("uses", "")) for step in job.get("steps", []))


def test_workflows_parse_and_actions_are_pinned():
    """Workflow files are valid and third-party actions are immutable commits."""
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        assert isinstance(yaml.safe_load(path.read_text()), dict)
        for match in re.finditer(r"uses:\s*([\w./-]+)@(\S+)(?:\s+#\s*(\S+))?", path.read_text()):
            owner, reference, version = match.groups()
            if not owner.startswith("./"):
                assert re.fullmatch(r"[0-9a-f]{40}", reference), owner
                assert version and version.startswith("v"), owner


def test_only_tag_publishes_packages_and_recovery_is_main_only():
    """Normal publication uses release; MCP-only recovery uses another protected environment."""
    jobs = workflow()["jobs"]
    assert jobs["publish"]["if"] == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
    assert jobs["publish"]["needs"] == "build" and jobs["publish"]["environment"] == "release"
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write", "packages": "write", "attestations": "write"}
    assert jobs["build"]["needs"] == "validate"
    assert jobs["recover-mcp"]["needs"] == "recover-source"
    assert jobs["recover-mcp"]["environment"] == "release-recovery"
    assert jobs["recover-mcp"]["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert jobs["recover-source"]["permissions"] == {"contents": "read", "actions": "read"}
    for name in ("recover-source", "recover-mcp"):
        assert "github.event_name == 'workflow_dispatch'" in jobs[name]["if"]
        assert "github.ref == 'refs/heads/main'" in jobs[name]["if"]
        assert "inputs.recover_source_run != ''" in jobs[name]["if"]
        assert "inputs.recover_tag != ''" in jobs[name]["if"]
        assert "id-token: write" not in yaml.safe_dump(jobs["recover-source"])


def test_recovery_cannot_write_any_package_or_image():
    """Recovery only checks existing packages and may create missing MCP metadata."""
    text = yaml.safe_dump(workflow()["jobs"]["recover-mcp"])
    for forbidden in ("uv publish", "npm publish", "regctl image import", "regctl image copy", "registry login", "packages: write"):
        assert forbidden not in text
    for required in ("release_artifact_source.py", "sha256sum --check --strict SHA256SUMS", "--require-existing", "verify_ghcr.sh", "cosign verify-blob", "publish recovered-server.json"):
        assert required in text
    assert "steps.mcp.outputs.mcp_status == 'missing'" in text
    assert "NPM_BOOTSTRAPPED" in text
    assert jobs_have_no_error_bypass()


def jobs_have_no_error_bypass():
    """Return whether ordinary jobs lack failure-suppression directives."""
    content = (ROOT / ".github/workflows/release.yml").read_text()
    return "continue-on-error" not in content and "always(" not in content


def test_normal_publish_verifies_artifacts_and_never_reuploads_matches():
    """Existing PyPI, npm and GHCR content is compared before conditional publication."""
    text = yaml.safe_dump(workflow()["jobs"]["publish"])
    assert "actions/download-artifact@" in text
    assert "sha256sum --check --strict SHA256SUMS" in text
    assert "check_oci_image.py dist/tapebasis-image.tar" in text
    assert "steps.pypi.outputs.pypi_status == 'missing'" in text
    assert "release_registry.py pypi" in text and "--trusted-publishing always" in text
    assert "steps.npm.outputs.npm_status == 'missing'" in text
    assert "release_registry.py npm" in text
    assert "scripts/verify_ghcr.sh \"$VERSION\" publish-missing" in text
    assert "mcp-publisher publish server.json" in text
    assert "steps.mcp.outputs.mcp_status == 'missing'" in text
    assert "cosign verify-blob" in text
    helper = (ROOT / "scripts/verify_ghcr.sh").read_text()
    assert "image import" in helper and "registry login" in helper


def test_release_checks_are_not_bypassed_by_manual_recovery():
    """Manual runs with recovery inputs do not build a replacement tag artifact."""
    jobs = workflow()["jobs"]
    condition = jobs["build"]["if"]
    assert "github.event_name != 'workflow_dispatch'" in condition
    assert "inputs.recover_source_run == '' && inputs.recover_tag == ''" in condition
    for job in jobs.values():
        text = yaml.safe_dump(job)
        for forbidden in ("UV_PUBLISH_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN"):
            assert forbidden not in text


def test_test_and_image_workflows_have_no_package_uploads():
    """Validation entry points do not acquire publishing credentials."""
    for filename in ("test.yml", "publish-image.yml"):
        text = yaml.safe_dump(workflow(filename))
        for forbidden in ("uv publish", "npm publish", "id-token: write", "packages: write", "mcp-publisher publish"):
            assert forbidden not in text
