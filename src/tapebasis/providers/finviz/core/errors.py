"""
Structured error envelope and exception types for the Finviz provider.

Every recoverable failure leaves the MCP boundary as a typed error envelope:

    {"error": {"code": "<CODE>", "message": "<human-readable>", **extras}}

Services raise :class:`FinvizServiceError`; the tool layer converts it with
:func:`exception_to_envelope` so MCP clients see one uniform error shape.

Design notes
------------
- ``code`` values are plain strings, safe to branch on from any language.
- ``retryable`` tells the client whether repeating the identical call could
  plausibly succeed (rate limits, timeouts) or not (bad ticker, bad parameter).
- Payload data is never discarded: a partial scrape returns its rows *and* an
  envelope marker via :class:`PartialDataError`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Union


class ErrorCode(str, Enum):
    """Stable string codes for programmatic branching by MCP clients."""

    # Input / validation
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    INVALID_TICKER = "INVALID_TICKER"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # Upstream (finviz.com / charts2-node.finviz.com)
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    ELITE_ONLY = "ELITE_ONLY"

    # Data
    NO_DATA = "NO_DATA"
    PARTIAL_DATA = "PARTIAL_DATA"
    PARSE_ERROR = "PARSE_ERROR"

    # Environment
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def make_error(code: Union[ErrorCode, str], message: str, **extra: Any) -> dict[str, Any]:
    """Construct a structured error envelope.

    Args:
        code: An :class:`ErrorCode` value or its raw string form.
        message: Human-readable description suitable for showing to a user.
        **extra: Additional structured fields, e.g. ``retryable=True``,
            ``ticker="VCIG"``, ``status=429``.

    Returns:
        ``{"error": {"code": ..., "message": ..., **extra}}``
    """
    code_str = code.value if isinstance(code, ErrorCode) else str(code)
    err: dict[str, Any] = {"code": code_str, "message": message}
    if extra:
        err.update(extra)
    return {"error": err}


def is_error(payload: Any) -> bool:
    """True if *payload* is an error envelope produced by :func:`make_error`."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("error"), dict)
        and "code" in payload["error"]
    )


class FinvizServiceError(RuntimeError):
    """Typed service-layer failure carrying an :class:`ErrorCode`.

    Subclasses ``RuntimeError`` so callers using a bare ``except RuntimeError``
    keep working, while the MCP boundary gains a lossless translation.

    Attributes:
        code:  Stable :class:`ErrorCode` for programmatic branching.
        extra: Structured context merged into the envelope
               (e.g. ``ticker="VCIG"``, ``status=429``).
    """

    def __init__(self, code: Union[ErrorCode, str], message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra

    def to_envelope(self) -> dict[str, Any]:
        return make_error(self.code, str(self), **self.extra)


class PartialDataError(Exception):
    """Raised when a scrape produced rows but could not complete.

    The payload rides alongside the PARTIAL_DATA envelope so callers keep the
    data they paid for.

    Attributes:
        payload: The partial result (already shaped like the success value).
        reason:  Human-readable cause ("news endpoint returned 0 rows", ...).
    """

    def __init__(self, payload: Any, reason: str) -> None:
        super().__init__(f"Partial data: {reason}")
        self.payload = payload
        self.reason = reason


def exception_to_envelope(exc: BaseException, *, context: str = "") -> dict[str, Any]:
    """Translate any exception into the structured envelope at the MCP boundary.

    Args:
        exc:     The caught exception.
        context: Tool name prefixed to unexpected-exception messages so the
                 envelope stays diagnosable without a traceback.
    """
    if isinstance(exc, FinvizServiceError):
        return exc.to_envelope()
    if isinstance(exc, PartialDataError):
        env = make_error(
            ErrorCode.PARTIAL_DATA,
            str(exc),
            reason=exc.reason,
            retryable=True,
        )
        env["data"] = exc.payload
        return env
    msg = f"{context} failed: {exc!r}" if context else repr(exc)
    return make_error(ErrorCode.INTERNAL_ERROR, msg, retryable=False)
