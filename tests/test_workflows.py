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


def dispatch_selected(job, values):
    """Evaluate one dispatch-only job condition against exclusive input pairs."""
    expression = job.get("if")
    assert isinstance(expression, str) and expression.startswith("github.event_name == 'workflow_dispatch'")
    assert "github.ref == 'refs/heads/main'" in expression
    comparisons = re.findall(r"inputs\.(\w+) ([!=]=) (''|'[^']*')", expression)
    assert len(comparisons) == 6
    return all((values.get(name, "") == literal.strip("'")) == (operator == "==")
               for name, operator, literal in comparisons)


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


def test_npm_staging_addresses_a_local_tarball_not_a_github_shortcut():
    """Every staging command prevents npm from treating dist/name as a GitHub repository."""
    document = (ROOT / ".github/workflows/release.yml").read_text()
    assert document.count('npm stage publish "./dist/tapebasis-${VERSION}.tgz"') == 2
    assert 'npm stage publish "dist/tapebasis-${VERSION}.tgz"' not in document


def test_npm_staging_is_stage_only_and_requires_maintainer_approval():
    """Both npm paths stage the tested tarball and stop before any other registry."""
    for job_name in ("publish", "resume-publication"):
        job = workflow()["jobs"][job_name]
        setup = next(step for step in job["steps"]
                     if step.get("uses", "").startswith("actions/setup-node@"))
        assert setup["with"] == {"node-version": "24"}
        stages = [step for step in job["steps"] if "npm stage publish" in step.get("run", "")]
        assert len(stages) == 1
        stage = stages[0]
        assert stage["id"] == "npm_stage"
        assert stage["if"] == "steps.npm.outputs.npm_status == 'missing'"
        assert stage["env"]["NPM_STAGE_TOKEN"] == "${{ secrets.TAPEBASIS_NPM_STAGE_TOKEN }}"
        assert "npm stage publish \"./dist/tapebasis-${VERSION}.tgz\"" in " ".join(stage["run"].split())
        assert "--loglevel verbose" in stage["run"]
        assert "npm_staged=true" in stage["run"]
        assert "$RUNNER_TEMP" in stage["run"]
        assert "trap 'rm -f \"$npmrc\"' EXIT" in stage["run"]
        assert "TAPEBASIS_NPM_STAGE_TOKEN" not in stage["run"]
        comparison = next(step for step in job["steps"] if step.get("id") == "npm")
        assert comparison["run"].find("release_registry.py npm") >= 0
        marker = next(step for step in job["steps"] if "NPM_BOOTSTRAPPED" in step.get("run", ""))
        assert marker["if"] == "steps.npm.outputs.npm_status == 'verified'"
        steps = job["steps"]
        for later in steps[steps.index(stage) + 1:]:
            if later.get("name", "").startswith("Report the staged"):
                assert later["if"] == "steps.npm_stage.outputs.npm_staged == 'true'"
                continue
            assert "steps.npm_stage.outputs.npm_staged != 'true'" in later["if"]
    document = (ROOT / ".github/workflows/release.yml").read_text()
    assert "npm publish " not in document
    assert document.count("secrets.TAPEBASIS_NPM_STAGE_TOKEN") == 2
    recovery = yaml.safe_dump(workflow()["jobs"]["recover-mcp"])
    assert "npm stage publish" not in recovery and "NPM_STAGE_TOKEN" not in recovery
    assert "registry-url:" not in document


def test_only_tag_publishes_packages_and_recovery_is_main_only():
    """Normal publication uses release; MCP-only recovery uses another protected environment."""
    jobs = workflow()["jobs"]
    assert "github.event_name == 'push'" in jobs["publish"]["if"]
    assert "startsWith(github.ref, 'refs/tags/v')" in jobs["publish"]["if"]
    assert jobs["publish"]["needs"] == "build" and jobs["publish"]["environment"] == "release"
    assert jobs["publish"]["permissions"] == {"contents": "write", "id-token": "write", "packages": "write", "attestations": "write"}
    assert jobs["build"]["needs"] == "validate"
    assert jobs["recover-mcp"]["needs"] == "recover-source"
    assert jobs["recover-mcp"]["environment"] == "release-recovery"
    assert jobs["recover-mcp"]["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert jobs["recover-mcp"]["concurrency"] == {
        "group": "tapebasis-release-mcp-recovery", "cancel-in-progress": False,
    }
    assert jobs["recover-source"]["permissions"] == {"contents": "read", "actions": "read"}
    for name in ("recover-source", "recover-mcp"):
        assert "github.event_name == 'workflow_dispatch'" in jobs[name]["if"]
        assert "github.ref == 'refs/heads/main'" in jobs[name]["if"]
        assert "inputs.recover_source_run != ''" in jobs[name]["if"]
        assert "inputs.recover_tag != ''" in jobs[name]["if"]
        assert "id-token: write" not in yaml.safe_dump(jobs["recover-source"])
    assert "source-only" not in yaml.safe_dump(jobs["recover-source"])
    for job in jobs.values():
        for step in job.get("steps", []):
            assert "${{ inputs." not in step.get("run", "")


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


def test_package_continuation_is_distinct_and_source_bound():
    """Only explicit paired resume inputs enable the separately approved package writer."""
    document = workflow()
    inputs = document[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"recover_source_run", "recover_tag", "resume_source_run", "resume_tag", "notes_source_run", "notes_tag"}
    jobs = document["jobs"]
    source = jobs["resume-source"]
    publish = jobs["resume-publication"]
    for job in (source, publish):
        for required in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'", "inputs.resume_source_run != ''", "inputs.resume_tag != ''", "inputs.recover_source_run == ''", "inputs.recover_tag == ''"):
            assert required in job["if"]
    assert publish["environment"] == "release"
    assert publish["needs"] == "resume-source"
    assert source["permissions"] == {"contents": "read", "actions": "read"}
    assert "id-token: write" not in yaml.safe_dump(source)
    text = " ".join(yaml.safe_dump(publish).split())
    assert "release_artifact_source.py --source-only" in text
    assert "sha256sum --check --strict SHA256SUMS" in text
    assert "check_oci_image.py dist/tapebasis-image.tar" in text
    assert "check_release.py" not in text and "load_metadata" not in text
    assert "dist/tapebasis-${VERSION}.tgz" in text
    runs = " ".join(" ".join(step.get("run", "").split()) for step in publish["steps"])
    assert 'npm stage publish "./dist/tapebasis-${VERSION}.tgz"' in runs
    assert "uv publish" in runs
    assert "verify_ghcr.sh \"$VERSION\" publish-missing" in text
    assert "--advance-major-latest-from \"$PREVIOUS_RELEASE_DIGEST\"" in " ".join(text.split())
    continuation = workflow()["jobs"]["resume-publication"]["steps"]
    alias = next(step for step in continuation if "reviewed predecessor" in step.get("name", ""))
    assert alias["if"] == "steps.npm_stage.outputs.npm_staged != 'true' && inputs.resume_tag == 'v1.1.1'"
    assert alias["run"].strip().endswith('--advance-major-latest-from "$PREVIOUS_RELEASE_DIGEST"')
    assert alias["env"]["PREVIOUS_RELEASE_DIGEST"] == "sha256:4ff12fdcdc79e7c5cd065a3ffb685dcbe6daee518442b7751e0479e0da1e3167"
    ordinary = next(step for step in continuation if "other GHCR releases" in step.get("name", ""))
    assert ordinary["if"] == "steps.npm_stage.outputs.npm_staged != 'true' && inputs.resume_tag != 'v1.1.1'"
    assert "--advance-major-latest-from" not in ordinary["run"]
    assert "publish source-server.json" in text
    assert "server.json --output \"$GITHUB_OUTPUT\"" not in text.replace("source-server.json --output \"$GITHUB_OUTPUT\"", "")
    assert text.count("--await-visible") == 2
    recovery = yaml.safe_dump(jobs["recover-mcp"])
    assert "uv publish" not in recovery and "npm publish" not in recovery
    assert "publish-missing" not in recovery and "--source-only" not in recovery


def test_dispatch_selects_only_one_complete_operation():
    """Blank, partial and mixed dispatches never select a writing job."""
    jobs = workflow()["jobs"]
    names = ("source_run", "tag")
    paths = ("recover", "resume", "notes")
    cases = [{}, *({f"{prefix}_{name}": "1"} for prefix in paths for name in names)]
    expected = [[] for _ in cases]
    for prefix in paths:
        cases.append({f"{prefix}_source_run": "1", f"{prefix}_tag": "v1.0.0"})
        expected.append([prefix])
    cases.append({"resume_source_run": "1", "notes_tag": "v1.0.0"})
    expected.append([])
    for values, selected in zip(cases, expected, strict=True):
        assert [prefix for prefix in paths
                if dispatch_selected(jobs[f"{prefix}-source"], values)] == selected
    for prefix in ("recover", "resume"):
        suffix = "-mcp" if prefix == "recover" else "-publication"
        for values in cases:
            assert dispatch_selected(jobs[prefix + suffix], values) == dispatch_selected(
                jobs[prefix + "-source"], values)
    notes = jobs["notes-source"]
    assert notes["environment"] == "release-notes"
    assert notes["permissions"] == {"contents": "write", "actions": "read"}
    text = yaml.safe_dump(notes)
    for required in ("--source-only --notes-only", "release_notes.py", "CHANGELOG", "SOURCE_COMMIT"):
        if required != "CHANGELOG":
            assert required in text
    for forbidden in ("uv publish", "npm publish", "mcp-publisher", "regctl", "id-token: write",
                      "packages: write", "attestations: write"):
        assert forbidden not in text
    assert "release_notes.py" in yaml.safe_dump(jobs["publish"])
    assert "release_notes.py" in yaml.safe_dump(jobs["resume-publication"])


def jobs_have_no_error_bypass():
    """Return whether ordinary jobs lack failure-suppression directives."""
    content = (ROOT / ".github/workflows/release.yml").read_text()
    return "continue-on-error" not in content and "always(" not in content


def test_normal_publish_verifies_artifacts_and_never_reuploads_matches():
    """Existing PyPI, npm and GHCR content is compared before conditional publication."""
    text = " ".join(yaml.safe_dump(workflow()["jobs"]["publish"]).split())
    assert "actions/download-artifact@" in text
    assert "sha256sum --check --strict SHA256SUMS" in text
    assert "check_oci_image.py dist/tapebasis-image.tar" in text
    assert "steps.pypi.outputs.pypi_missing_wheel == 'true'" in text
    assert "steps.pypi.outputs.pypi_missing_sdist == 'true'" in text
    publish = next(step for step in workflow()["jobs"]["publish"]["steps"]
                   if step.get("name") == "Publish the distributions to PyPI only when absent")
    assert publish["if"] == (
        "steps.pypi.outputs.pypi_status == 'missing' || "
        "steps.pypi.outputs.pypi_status == 'partial'"
    )
    assert '"${files[@]}"' in text
    assert "release_registry.py pypi" in text and "--trusted-publishing always" in text
    assert "steps.npm.outputs.npm_status == 'missing'" in text
    assert "release_registry.py npm" in text
    assert "scripts/verify_ghcr.sh \"$VERSION\" publish-missing" in text
    assert "mcp-publisher publish server.json" in text
    mcp_publish = next(step for step in workflow()["jobs"]["publish"]["steps"]
                       if step.get("name") == "Publish the server to the MCP Registry only when absent")
    assert "steps.mcp.outputs.mcp_status == 'missing'" in mcp_publish["if"]
    assert text.count("--await-visible") == 2
    assert "cosign verify-blob" in text
    helper = (ROOT / "scripts/verify_ghcr.sh").read_text()
    assert "image import" in helper and "registry login" in helper


def test_release_checks_are_not_bypassed_by_manual_recovery():
    """Manual runs with recovery inputs do not build a replacement tag artifact."""
    jobs = workflow()["jobs"]
    condition = jobs["build"]["if"]
    assert "github.event_name != 'workflow_dispatch'" in condition
    assert "inputs.recover_source_run == '' && inputs.recover_tag == ''" in condition
    assert "inputs.resume_source_run == '' && inputs.resume_tag == ''" in condition
    assert jobs["validate"]["if"] == condition
    assert "needs" not in jobs["recover-source"]
    assert "needs" not in jobs["validate"]
    assert jobs["build"]["needs"] == "validate"
    assert jobs["publish"]["needs"] == "build"
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
