"""Remote Finviz chart responses fetch once and retain only a small local cache."""
from __future__ import annotations

import base64
import json
import os

from mcp.types import TextContent

from tapebasis import fv_access, tools_finviz
from tapebasis.providers.finviz.core.errors import FinvizServiceError
from tapebasis.providers.finviz.core.services import chart_service

PNG = b"\x89PNG\r\n\x1a\nchart-test"


def _chart_payload():
    """Return an independent single-source chart payload for tool-level tests."""
    return {
        "ticker": "AAPL",
        "image_base64": base64.b64encode(PNG).decode("ascii"),
        "mime_type": "image/png",
        "path": "/home/mcpuser/.tapebasis/charts/AAPL.png",
        "bytes": len(PNG),
        "width": 900,
        "height": 500,
        "warnings": [],
        "source": "https://charts2-node.finviz.com/chart?t=AAPL",
    }


async def test_remote_stock_chart_returns_inline_image_and_local_path(monkeypatch):
    """The MCP data block contains base64, MIME type, size and optional path."""
    fetch_count = 0

    async def fake_chart(*args, **kwargs):
        nonlocal fetch_count
        fetch_count += 1
        return _chart_payload()

    monkeypatch.setattr(fv_access, "chart", fake_chart)
    response = await tools_finviz.stock_chart("AAPL")

    assert fetch_count == 1
    assert response["data_provider"] == "FINVIZ"
    assert response["data"]["image_base64"] == base64.b64encode(PNG).decode("ascii")
    assert response["data"]["mime_type"] == "image/png"
    assert response["data"]["bytes"] == len(PNG)
    assert response["image_path"] == response["data"]["path"]
    assert base64.b64decode(response["data"]["image_base64"]) == PNG


async def test_fastmcp_serializes_the_image_inside_the_text_json(monkeypatch):
    """Remote MCP clients receive the base64 fields in ordinary JSON content."""
    from tapebasis import server

    async def fake_chart(*args, **kwargs):
        return _chart_payload()

    monkeypatch.setattr(fv_access, "chart", fake_chart)
    content, result = await server.mcp.call_tool("stock_chart", {"symbol": "AAPL"})
    text = next(item for item in content if isinstance(item, TextContent))
    payload = json.loads(text.text)

    assert payload["data"]["image_base64"] == base64.b64encode(PNG).decode("ascii")
    assert payload["data"]["mime_type"] == "image/png"
    assert base64.b64decode(payload["data"]["image_base64"]) == PNG


async def test_stock_chart_makes_no_second_download_for_local_copy(monkeypatch):
    """The access layer uses the single-fetch inline service, not both services."""
    fetch_count = 0

    async def fake_inline(*args, **kwargs):
        nonlocal fetch_count
        fetch_count += 1
        return _chart_payload()

    async def unexpected_download(*args, **kwargs):
        raise AssertionError("the tool must not download the same chart twice")

    async def direct_call(coro, context):
        return await coro

    monkeypatch.setattr(chart_service, "get_chart_base64", fake_inline)
    monkeypatch.setattr(chart_service, "download_chart", unexpected_download)
    monkeypatch.setattr(fv_access, "_call", direct_call)
    data = await fv_access.chart("AAPL")

    assert fetch_count == 1
    assert data["image_base64"] == base64.b64encode(PNG).decode("ascii")


async def test_inline_service_makes_one_fetch_and_retains_its_local_copy(
    monkeypatch, tmp_path
):
    """Both response forms contain the exact bytes from one upstream response."""
    fetch_count = 0

    async def fake_fetch(url, **kwargs):
        nonlocal fetch_count
        fetch_count += 1
        return PNG

    monkeypatch.setattr(chart_service.finviz_client, "fetch_bytes", fake_fetch)
    data = await chart_service.get_chart_base64("AAPL", output_dir=str(tmp_path))

    assert fetch_count == 1
    assert base64.b64decode(data["image_base64"]) == PNG
    with open(data["path"], "rb") as handle:
        assert handle.read() == PNG
    assert data["mime_type"] == "image/png"
    assert data["warnings"] == []


async def test_inline_image_survives_a_local_write_failure(monkeypatch, tmp_path):
    """A storage failure cannot discard the already downloaded inline image."""

    async def fake_fetch(url, **kwargs):
        return PNG

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(chart_service.finviz_client, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(chart_service, "_write_local_copy", fail_write)
    data = await chart_service.get_chart_base64("AAPL", output_dir=str(tmp_path))

    assert data["path"] is None
    assert base64.b64decode(data["image_base64"]) == PNG
    assert "its local copy was not retained" in data["warnings"][0]


async def test_path_only_service_preserves_typed_disk_errors(monkeypatch, tmp_path):
    """Pre-existing local callers keep their typed filesystem failure contract."""

    async def fake_fetch(url, **kwargs):
        return PNG

    def fail_write(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(chart_service.finviz_client, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(chart_service, "_write_local_copy", fail_write)
    try:
        await chart_service.download_chart("AAPL", output_dir=str(tmp_path))
    except FinvizServiceError as exc:
        assert exc.code == chart_service.ErrorCode.INTERNAL_ERROR
        assert str(tmp_path) in str(exc)
        assert exc.extra["directory"] == str(tmp_path)
    else:
        raise AssertionError("path-only service should preserve its disk error")


async def test_local_retention_does_not_delete_unrelated_files(monkeypatch, tmp_path):
    """The narrow retention rule deletes only old service-generated PNGs."""

    async def fake_fetch(url, **kwargs):
        return PNG

    monkeypatch.setattr(chart_service.finviz_client, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(chart_service, "MAX_CHART_FILES", 2)
    unrelated = tmp_path / "operator-supplied.png"
    unrelated.write_bytes(b"keep")
    similar_but_unknown = tmp_path / "AAPL_d_c_not-a-timestamp.png"
    similar_but_unknown.write_bytes(b"keep")
    for name in ("OLD_1.png", "OLD_2.png"):
        old = tmp_path / name
        old.write_bytes(b"keep")
    generated = [
        tmp_path / f"OLD_d_c_20260101T000000{number:06d}Z.png" for number in range(3)
    ]
    for number, path in enumerate(generated):
        path.write_bytes(b"old")
        os.utime(path, ns=(number * 1_000_000_000, number * 1_000_000_000))

    await chart_service.get_chart_base64("AAPL", output_dir=str(tmp_path))

    assert unrelated.read_bytes() == b"keep"
    assert similar_but_unknown.read_bytes() == b"keep"
    for name in ("OLD_1.png", "OLD_2.png"):
        assert (tmp_path / name).read_bytes() == b"keep"
    assert len(list(tmp_path.glob("OLD_d_*.png"))) == 1
    assert len(list(tmp_path.glob("AAPL_d_c_2*.png"))) == 1
