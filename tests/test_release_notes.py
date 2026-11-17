"""Offline tests for reviewed, source-bound GitHub Release summaries."""
from pathlib import Path

import pytest

from tests.test_release_recovery_full import load


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


def test_changelog_has_a_real_summary_for_each_declared_release():
    """Each published package version has a separately reviewed release section."""
    module = load("release_notes")
    for version in ("1.0.0", "1.1.0", "1.1.1", "1.1.2"):
        body = module.section(ROOT / "CHANGELOG.md", version)
        assert len(body.splitlines()) >= 3
        assert "## [" not in body
        for other in ("1.0.0", "1.1.0", "1.1.1", "1.1.2"):
            if version != other:
                assert f"## [{other}]" not in body
    with pytest.raises(module.NotesError, match="exactly one"):
        module.section(ROOT / "CHANGELOG.md", "9.9.9")


def test_release_identity_requires_a_source_bound_live_tag(monkeypatch):
    """No Release write is attempted for an old, moved or mismatched tag."""
    module = load("release_notes")
    for repository, tag, version, commit in (
        ("bad.repo/owner/repo", "v1.1.1", "1.1.1", COMMIT),
        ("owner/repo", "v1.1.2", "1.1.1", COMMIT),
        ("owner/repo", "v1.1.1", "garbage", COMMIT),
        ("owner/repo", "v1.1.1", "1.1.1", "short"),
    ):
        with pytest.raises(module.NotesError):
            module.notes_arguments(repository, tag, version, commit)
    assert module.notes_arguments("owner/repo", "v1.1.1", "1.1.1", COMMIT)
    assert not module.notes_arguments("owner/repo", "", "", "")
    responses = {
        "https://api.github.com/repos/owner/repo/git/ref/tags/v1.1.1": {"object": {"sha": "b" * 40, "type": "tag"}},
        "https://api.github.com/repos/owner/repo/git/tags/" + "b" * 40: {"object": {"sha": COMMIT}},
    }
    monkeypatch.setattr(module, "request", lambda url, *_args, **_kwargs: responses[url])
    module.verify_tag("owner/repo", "token", "v1.1.1", COMMIT)
    with pytest.raises(module.NotesError, match="does not point"):
        module.verify_tag("owner/repo", "token", "v1.1.1", "c" * 40)


def test_release_is_created_or_updated_and_read_back(monkeypatch):
    """Idempotent PATCH and initial POST both carry the source commit and reviewed note."""
    module = load("release_notes")
    reference = {"object": {"sha": COMMIT, "type": "commit"}}
    calls = []

    for existing in (None, {"id": 4, "tag_name": "v1.1.1", "draft": False, "prerelease": False}):
        def request(url, _token, method="GET", payload=None, missing_ok=False):
            """Feed a fake Release and record the requested API mutation."""
            calls.append((url, method, payload))
            if "/git/ref/" in url:
                return reference
            if "/releases/tags/" in url:
                if method != "GET":
                    raise AssertionError("tag lookup must stay read-only")
                return existing if not release_state else release_state[-1]
            if payload is not None:
                release_state.append({"id": 4, "draft": False, "prerelease": False, **payload})
                return release_state[-1]
            raise AssertionError(url)

        release_state = []
        monkeypatch.setattr(module, "request", request)
        assert module.publish("owner/repo", "token", "v1.1.1", "1.1.1", "Summary\n", COMMIT) == "verified"
    values = [call for call in calls if call[1] in {"POST", "PATCH"}]
    assert [call[1] for call in values] == ["POST", "PATCH"]
    for _, _, payload in values:
        assert payload["target_commitish"] == COMMIT
        assert payload["name"] == "Tapebasis 1.1.1"
        assert payload["body"] == "Summary\n"
    assert calls[-1][1] == "GET"


def test_release_rejects_unexpected_http_errors_and_remote_conflicts(monkeypatch):
    """A 403 not missing, and a differing remote Release cannot be overwritten."""
    module = load("release_notes")
    monkeypatch.setattr(module, "verify_tag", lambda *_args: None)

    def deny(*_args, **_kwargs):
        """Reject the request as a terminal authorization failure."""
        raise module.NotesError("HTTP 403")

    monkeypatch.setattr(module, "request", deny)
    with pytest.raises(module.NotesError, match="403"):
        module.publish("owner/repo", "token", "v1.1.1", "1.1.1", "Summary\n", COMMIT)
    monkeypatch.setattr(module, "request", lambda *_args, **_kwargs: {"tag_name": "v0.0.0"})
    with pytest.raises(module.NotesError, match="identity"):
        module.publish("owner/repo", "token", "v1.1.1", "1.1.1", "Summary\n", COMMIT)
