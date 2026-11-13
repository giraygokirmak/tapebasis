"""
Chart service, server-rendered PNG charts from ``/chart.ashx``.

Why a PNG and not an SVG/JSON series
------------------------------------
finviz's chart image endpoint is the only public, unauthenticated chart route.
``/chart.ashx?t=VCIG&ty=c&ta=1&p=d&s=l`` answers **302 →**
``https://charts2-node.finviz.com/chart?...`` with an ``image/png`` body
(~18-25 KB at the default 466×219).

The redirect target reveals the real parameter vocabulary, which is what this
module drives *directly* (one hop saved, and width/height become controllable):

==========================  ==================================================
``t``                       ticker
``tf``                      ``d`` daily, ``w`` weekly, ``m`` monthly
``ct``                      ``candle_stick``, ``line_chart``, ``heikin_ashi``
``s``                       ``linear`` or ``logarithmic`` (``log`` → HTTP 400)
``w`` / ``h``               pixel size (default 466×219)
``bw`` ``bm`` ``bb``        bar width / margin / border flags
``pm`` / ``am``             pre-market / after-market overlay flags
``o[i][ot]`` ``o[i][op]``   overlay indicator type / period (``sma``)
==========================  ==================================================

Note the 400s: an unknown ``ct`` or ``s=log`` yields ``Invalid request`` with a
text/plain body, so parameters are validated here instead of being forwarded
blindly.
"""
from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.utils.validators import (
    clamp_int,
    validate_period,
    validate_scale,
    validate_ticker,
)

CHART_HOST = "https://charts2-node.finviz.com/chart"

#: Public -> upstream chart type names.
_CHART_TYPE_MAP = {
    "c": "candle_stick",
    "candle": "candle_stick",
    "candle_stick": "candle_stick",
    "l": "line_chart",
    "line": "line_chart",
    "line_chart": "line_chart",
    "h": "heikin_ashi",
    "heikin_ashi": "heikin_ashi",
}

_SCALE_MAP = {"l": "linear", "linear": "linear", "log": "logarithmic"}

DEFAULT_DIR = os.environ.get(
    "FINVIZ_CHART_DIR", os.path.join(os.path.expanduser("~"), ".tapebasis", "charts")
)

#: Bounds the only files this service owns. Operator-provided directories are
#: otherwise left alone: unknown filenames and unrelated content are never pruned.
MAX_CHART_FILES = 32
_CHART_FILENAME = re.compile(
    r"^\^?[A-Z0-9][A-Z0-9.\-^]{0,11}_[dwm]_.+_\d{8}T\d{12}Z\.png$"
)


def _resolve_chart_type(chart_type: str) -> str:
    key = (chart_type or "c").strip().lower()
    if key not in _CHART_TYPE_MAP:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid chart_type {chart_type!r}; expected candle, line or heikin_ashi",
            chart_type=chart_type,
            allowed=sorted(_CHART_TYPE_MAP),
        )
    return _CHART_TYPE_MAP[key]


def build_chart_url(
    ticker: str,
    *,
    period: str = "d",
    chart_type: str = "c",
    scale: str = "l",
    width: int = 900,
    height: int = 500,
    technicals: bool = True,
) -> str:
    """Build the ``charts2-node`` URL for one chart (also used by tests)."""
    symbol = validate_ticker(ticker)
    period = validate_period(period)
    ct = _resolve_chart_type(chart_type)
    scale_key = validate_scale(scale)
    width = clamp_int(width, low=200, high=2000, name="width")
    height = clamp_int(height, low=150, high=1200, name="height")

    params = [
        f"w={width}",
        f"h={height}",
        "bw=2",
        "bm=1",
        "bb=1",
        f"t={quote(symbol)}",
        f"tf={period}",
        f"s={_SCALE_MAP[scale_key]}",
        "pm=0",
        "am=0",
        f"ct={ct}",
    ]
    if technicals:
        # Matches the overlay set the finviz quote page requests by default.
        params += [
            "o[0][ot]=sma",
            "o[0][op]=20",
            "o[0][oc]=DC32B363",
            "o[1][ot]=sma",
            "o[1][op]=50",
            "o[1][oc]=FF8F33C6",
            "o[2][ot]=sma",
            "o[2][op]=200",
            "o[2][oc]=DCB3326D",
        ]
    return CHART_HOST + "?" + "&".join(params)


async def download_chart(
    ticker: str,
    *,
    period: str = "d",
    chart_type: str = "c",
    scale: str = "l",
    width: int = 900,
    height: int = 500,
    technicals: bool = True,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Download a chart PNG to disk and return its path plus provenance.

    The file is written to ``FINVIZ_CHART_DIR`` (default
    ``~/.tapebasis/charts``) so a Docker deployment can mount a volume there.
    The returned ``path`` is absolute and is what an MCP client should hand to
    an image viewer.

    Raises:
        FinvizServiceError: ``UPSTREAM_ERROR`` when the endpoint returns
            something that is not a PNG, ``INTERNAL_ERROR`` when the file
            cannot be written.
    """
    url = build_chart_url(
        ticker,
        period=period,
        chart_type=chart_type,
        scale=scale,
        width=width,
        height=height,
        technicals=technicals,
    )
    symbol = validate_ticker(ticker)
    png = await finviz_client.fetch_bytes(url)
    if not png.startswith(b"\x89PNG"):
        raise FinvizServiceError(
            ErrorCode.UPSTREAM_ERROR,
            "Chart endpoint did not return a PNG (finviz rejects unknown "
            "combination with HTTP 400 'Invalid request')",
            url=url,
        )

    directory = output_dir or DEFAULT_DIR
    try:
        path = _write_local_copy(
            png,
            ticker=symbol,
            period=validate_period(period),
            chart_type=chart_type,
            output_dir=output_dir,
        )
    except OSError as exc:
        raise FinvizServiceError(
            ErrorCode.INTERNAL_ERROR,
            f"Could not write chart to {directory}: {exc}",
            directory=directory,
        ) from exc
    return {
        "ticker": symbol,
        "path": os.path.abspath(path),
        "bytes": len(png),
        "width": clamp_int(width, low=200, high=2000, name="width"),
        "height": clamp_int(height, low=150, high=1200, name="height"),
        "period": validate_period(period),
        "chart_type": chart_type,
        "scale": validate_scale(scale),
        "technicals": technicals,
        "source": url,
    }


def _prune_local_copies(directory: str) -> None:
    """Remove oldest service-generated PNGs beyond the fixed retention limit."""
    entries = []
    try:
        with os.scandir(directory) as children:
            for entry in children:
                if (
                    entry.is_file()
                    and entry.name.endswith(".png")
                    and _CHART_FILENAME.fullmatch(entry.name)
                ):
                    entries.append((entry.stat().st_mtime_ns, entry.name))
    except OSError:
        return
    for _, name in sorted(entries, reverse=True)[MAX_CHART_FILES:]:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            # The current response must not fail because an old local copy
            # could not be pruned. Do not delete unknown files to compensate.
            continue


def _write_local_copy(
    png: bytes,
    *,
    ticker: str,
    period: str,
    chart_type: str,
    output_dir: str | None = None,
) -> str:
    """Persist one fetched PNG, prune older copies and return its absolute path."""
    directory = output_dir or DEFAULT_DIR
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{ticker}_{period}_{chart_type}_{stamp}.png"
    path = os.path.join(directory, filename)
    with open(path, "wb") as handle:
        handle.write(png)
    _prune_local_copies(directory)
    return path


async def get_chart_base64(
    ticker: str,
    *,
    period: str = "d",
    chart_type: str = "c",
    scale: str = "l",
    width: int = 900,
    height: int = 500,
    technicals: bool = True,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Return one fetched PNG inline and, when writable, as a local copy.

    Fetch exactly once so ``stock_chart`` can serve remote MCP clients and
    preserve its path without requesting the same chart twice. A local write
    failure leaves ``path`` null and records a warning; the inline image stays
    available. Only service-generated PNGs are pruned, at most
    ``MAX_CHART_FILES`` files.
    """
    url = build_chart_url(
        ticker,
        period=period,
        chart_type=chart_type,
        scale=scale,
        width=width,
        height=height,
        technicals=technicals,
    )
    png = await finviz_client.fetch_bytes(url)
    if not png.startswith(b"\x89PNG"):
        raise FinvizServiceError(
            ErrorCode.UPSTREAM_ERROR,
            "Chart endpoint did not return a PNG",
            url=url,
        )
    symbol = validate_ticker(ticker)
    warnings: list[str] = []
    path = None
    try:
        path = os.path.abspath(
            _write_local_copy(
                png,
                ticker=symbol,
                period=validate_period(period),
                chart_type=chart_type,
                output_dir=output_dir,
            )
        )
    except OSError as exc:
        warnings.append(
            f"The chart is available inline, but its local copy was not retained: {exc}"
        )
    return {
        "ticker": symbol,
        "mime_type": "image/png",
        "path": path,
        "bytes": len(png),
        "width": clamp_int(width, low=200, high=2000, name="width"),
        "height": clamp_int(height, low=150, high=1200, name="height"),
        "period": validate_period(period),
        "chart_type": chart_type,
        "scale": validate_scale(scale),
        "technicals": technicals,
        "image_base64": base64.b64encode(png).decode("ascii"),
        "source": url,
        "warnings": warnings,
    }
