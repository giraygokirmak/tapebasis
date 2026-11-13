"""Tests for validating built OCI layouts without a registry."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_oci_image.py"


def _load():
    """Load the OCI verifier without any application dependency."""
    spec = importlib.util.spec_from_file_location("check_oci_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _blob(root: Path, value: dict) -> str:
    """Store a JSON OCI blob and return its content-addressed digest."""
    body = json.dumps(value).encode()
    digest = hashlib.sha256(body).hexdigest()
    path = root / "blobs" / "sha256" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return f"sha256:{digest}"


def _archive(tmp_path: Path, label: str = "io.github.giraygokirmak/tapebasis") -> Path:
    """Build a minimal two-platform OCI image archive fixture."""
    root = tmp_path / "layout"
    root.mkdir()
    (root / "oci-layout").write_text(json.dumps({"imageLayoutVersion": "1.0.0"}))
    manifests = []
    for platform in ("linux/amd64", "linux/arm64"):
        os_name, arch = platform.split("/")
        config = _blob(root, {"config": {"Labels": {"io.modelcontextprotocol.server.name": label}, "Env": ["PATH=/usr/local/bin"]}})
        manifest = _blob(root, {"config": {"digest": config}})
        manifests.append({"digest": manifest, "platform": {"os": os_name, "architecture": arch}})
    index = _blob(root, {"manifests": manifests})
    (root / "index.json").write_text(json.dumps({"manifests": [{"digest": index}]}))
    archive = tmp_path / "image.tar"
    with tarfile.open(archive, "w") as bundle:
        for path in root.rglob("*"):
            bundle.add(path, path.relative_to(root))
    return archive


def test_oci_layout_accepts_both_platforms(tmp_path):
    """The verifier accepts a labelled multi-platform OCI archive."""
    checker = _load()
    extracted, temporary = checker._extract(_archive(tmp_path))
    try:
        assert checker.validate(extracted, ["linux/amd64", "linux/arm64"]) == []
    finally:
        temporary.cleanup()


def test_oci_layout_rejects_wrong_label_and_missing_platform(tmp_path):
    """A missing platform or ownership mismatch cannot pass."""
    checker = _load()
    extracted, temporary = checker._extract(_archive(tmp_path, "wrong"))
    try:
        errors = checker.validate(extracted, ["linux/amd64", "linux/arm64", "linux/s390x"])
    finally:
        temporary.cleanup()
    assert any("linux/s390x" in error for error in errors)
    assert any("wrong" in error for error in errors)


def test_oci_cli_validates_a_real_tar(tmp_path):
    """The command accepts a tar file and returns its validation status."""
    result = subprocess.run([sys.executable, str(SCRIPT), str(_archive(tmp_path))], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_oci_cli_reports_tested_root_digest(tmp_path):
    """Digest output is exactly the descriptor digest that regctl reports for GHCR."""
    archive = _archive(tmp_path)
    checker = _load()
    directory, temporary = checker._extract(archive)
    try:
        expected = checker.root_digest(directory)
    finally:
        temporary.cleanup()
    result = subprocess.run([sys.executable, str(SCRIPT), "--digest", str(archive)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_oci_cli_rejects_a_missing_archive_for_Digest(tmp_path):
    """The release fails instead of treating an absent OCI archive as valid."""
    result = subprocess.run([sys.executable, str(SCRIPT), "--digest", str(tmp_path / "missing.tar")], text=True, capture_output=True)
    assert result.returncode != 0
