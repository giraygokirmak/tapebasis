"""Workflow contract tests for package identity and approved partial recovery."""
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]


def test_ghcr_verifies_digest_with_regctl_not_a_raw_token():
    """GHCR reads use the registry protocol and match the tested image root digest."""
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    script = (ROOT / "scripts/verify_ghcr.sh").read_text()
    assert 'Authorization: Bearer ${{ secrets.GITHUB_TOKEN }}' not in workflow
    assert "manifest get" in script and ".GetDescriptor.Digest" in script
    assert "check_oci_image.py --digest" in script
    assert "registry login" in script
    assert "curl --fail" not in script


def test_registry_scripts_and_security_paths_are_syntax_checked():
    """Every added Python and shell release verifier compiles."""
    for name in ("release_registry.py", "release_artifact_source.py", "check_oci_image.py"):
        subprocess.run(["python3", "-m", "py_compile", str(ROOT / "scripts" / name)], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "scripts/verify_ghcr.sh")], check=True)
