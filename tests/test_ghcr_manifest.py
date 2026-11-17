"""Offline tests for explicit GHCR absence and tested-image digest checks."""
from email.message import Message
import io
import urllib.error
import urllib.request

import pytest

from tests.test_release_recovery_full import load


EXPECTED = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


@pytest.mark.parametrize("script", ["release_artifact_source", "release_notes", "ghcr_manifest"])
def test_authenticated_helpers_strip_credentials_on_cross_host_redirects(script):
    """Credential-bearing helpers never forward Authorization to another origin."""
    module = load(script)
    origin = "https://ghcr.io" if script == "ghcr_manifest" else "https://api.github.com"
    request = urllib.request.Request(origin + "/resource", headers={"Authorization": "Bearer secret"})
    handler = module.SameHostRedirects()
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://attacker.invalid/resource",
    )
    assert redirected is not None and not redirected.has_header("Authorization")
    same_origin = handler.redirect_request(
        request, None, 302, "Found", {}, origin + "/next",
    )
    assert same_origin is not None and same_origin.get_header("Authorization") == "Bearer secret"
    assert any(isinstance(item, module.SameHostRedirects) for item in module.OPENER.handlers)
    for location in ("http://api.github.com/next", "https://attacker.invalid@api.github.com/next",
                     "https://api.github.com:444/next"):
        unsafe = handler.redirect_request(request, None, 302, "Found", {}, location)
        assert unsafe is not None and not unsafe.has_header("Authorization")


class _Response:
    """Return bounded registry bytes and preserve normal HTTP header casing."""

    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self.body = body
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        """Return at most the caller's requested bounded byte count."""
        return self.body[:size]


def test_ghcr_uses_only_explicit_404_for_absence_and_checks_digest(monkeypatch):
    """A match, conflict and absence are distinguished without parsing error text."""
    module = load("ghcr_manifest")
    monkeypatch.setattr(module, "pull_token", lambda *_args, **_kwargs: "pull-token")
    responses = [
        _Response(headers={"Docker-Content-Digest": EXPECTED}),
        _Response(headers={"Docker-Content-Digest": OTHER}),
        urllib.error.HTTPError("https://ghcr.io/v2/repo/manifests/latest", 404, "missing", {}, io.BytesIO(b"denied")),
    ]
    seen = []

    def request(value, timeout):
        """Record the manifest method and authorization without network access."""
        seen.append((value.get_method(), value.full_url, value.get_header("Authorization")))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(module.OPENER, "open", request)
    assert module.manifest_status("owner/repo", "1.0.0", EXPECTED) == (0, EXPECTED)
    assert module.manifest_status("owner/repo", "latest", EXPECTED)[0] == 1
    assert module.manifest_status("owner/repo", "latest", EXPECTED) == (2, "manifest absent (HTTP 404)")
    assert seen[0][0] == "HEAD" and seen[0][2] == "Bearer pull-token"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_ghcr_http_failures_are_terminal_even_with_unknown_text(monkeypatch, status):
    """Authentication, authorization and server responses never mean absence."""
    module = load("ghcr_manifest")
    monkeypatch.setattr(module, "pull_token", lambda *_args, **_kwargs: "pull-token")

    def deny(_request, timeout):
        """Raise an HTTP error whose message deliberately resembles absence."""
        raise urllib.error.HTTPError("https://ghcr.io/v2/repo/manifest", status, "manifest unknown", {}, io.BytesIO(b""))

    monkeypatch.setattr(module.OPENER, "open", deny)
    with pytest.raises(module.ManifestError, match=str(status)):
        module.manifest_status("owner/repo", "1.0.0", EXPECTED)
    assert module.main(["--repository", "owner/repo", "--tag", "1.0.0", "--expected", EXPECTED]) == 3


@pytest.mark.parametrize("error", [
    urllib.error.URLError("connection reset"),
    TimeoutError("timed out"),
    OSError("network unavailable"),
])
def test_ghcr_transport_failures_are_terminal(monkeypatch, error):
    """Network failures cannot be confused with a registry not-found response."""
    module = load("ghcr_manifest")
    monkeypatch.setattr(module, "pull_token", lambda *_args, **_kwargs: "pull-token")
    monkeypatch.setattr(module.OPENER, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(module.ManifestError):
        module.manifest_status("owner/repo", "latest", EXPECTED)


def test_ghcr_requires_json_token_and_valid_digest(monkeypatch):
    """Malformed token and manifest responses never produce a writable absence."""
    module = load("ghcr_manifest")
    responses = [
        _Response(headers={"Content-Type": "application/json"}, body=b'{"token":"safe-token"}'),
        _Response(headers={"Docker-Content-Digest": "invalid"}),
        _Response(headers={"Content-Type": "text/plain"}, body=b"forbidden"),
    ]
    monkeypatch.setattr(module.OPENER, "open", lambda *_args, **_kwargs: responses.pop(0))
    with pytest.raises(module.ManifestError, match="valid manifest digest"):
        module.manifest_status("owner/repo", "latest", EXPECTED)
    with pytest.raises(module.ManifestError, match="JSON"):
        module.pull_token("owner/repo")


def test_ghcr_cli_returns_each_classification(monkeypatch, capsys):
    """The shell receives stable match, conflict, absence and terminal statuses."""
    module = load("ghcr_manifest")
    for result, status in (((0, EXPECTED), 0), ((1, "different"), 1),
                           ((2, "HTTP 404"), 2)):
        monkeypatch.setattr(module, "manifest_status", lambda *_args, value=result: value)
        assert module.main(["--repository", "owner/repo", "--tag", "latest", "--expected", EXPECTED]) == status
    assert "different" in capsys.readouterr().err
