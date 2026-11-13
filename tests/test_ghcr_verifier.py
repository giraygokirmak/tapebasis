"""Isolated tests for optional GHCR completion in the normal tag job."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_cannot_write_packages_and_requires_cosigned_publisher():
    """Only missing MCP metadata is writable in the separate main-only recovery job."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
    recovery = yaml.safe_dump(jobs["recover-mcp"])
    assert jobs["recover-mcp"]["environment"] == "release-recovery"
    assert jobs["recover-mcp"]["needs"] == "recover-source"
    assert "actions: read" in recovery and "id-token: write" in recovery
    for forbidden in ("uv publish", "npm publish", "regctl image import", "regctl image copy", "registry login", "packages: write"):
        assert forbidden not in recovery
    for required in ("cosign verify-blob", "recovered-server.json", "--require-existing", "verify_ghcr.sh"):
        assert required in recovery
    source = yaml.safe_dump(jobs["recover-source"])
    assert "id-token: write" not in source
    assert "release_artifact_source.py" in source and "check_oci_image.py dist/tapebasis-image.tar" in source
    assert "if: github.event_name != 'workflow_dispatch'" in yaml.safe_dump(jobs["build"])


def test_normal_tag_job_verifies_exact_registry_bytes_before_mcp():
    """Normal publication checks existing files, publishes only missing versions and rechecks each registry."""
    content = yaml.safe_dump(yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]["publish"])
    for required in ("release_registry.py pypi", "release_registry.py npm", "release_registry.py mcp", "steps.pypi.outputs.pypi_status == 'missing'", "steps.npm.outputs.npm_status == 'missing'", "steps.mcp.outputs.mcp_status == 'missing'", "verify_ghcr.sh", "cosign verify-blob"):
        assert required in content
    assert "Authorization: Bearer ${{ secrets.GITHUB_TOKEN }}" not in content
    assert "npm view" not in yaml.safe_dump(yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]["publish"])
