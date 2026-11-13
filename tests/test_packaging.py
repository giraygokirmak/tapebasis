"""Exercise the launcher and the built package in isolated environments.

The tests never import the checkout through an editable install. They build a
wheel and sdist with uv, install them in temporary locations, and run actual
MCP clients against the packaged server. The npm package is packed and its
launcher is exercised both with a fake executable and with a real MCP stdio
client through the locally built wheel.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required by npm CI")


def _uv() -> str:
    """Require uv on PATH so local and CI packaging use the same executable."""
    executable = shutil.which("uv")
    if executable is None:
        pytest.fail("uv must be on PATH for packaging smoke tests")
    return executable


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    """Build one wheel and one sdist, with no stale output to confuse the tests."""
    destination = tmp_path_factory.mktemp("distributions")
    subprocess.run(
        [_uv(), "build", "--clear", "--no-sources", "--out-dir", str(destination), str(ROOT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(destination.glob("*.whl"))
    sdists = list(destination.glob("*.tar.gz"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    assert len(sdists) == 1, f"expected one sdist, got {sdists}"
    return wheels + sdists


def _pack_and_install_npm(tmp_path: Path) -> Path:
    """Pack the real launcher and return its executable in an isolated npm prefix."""
    subprocess.run(
        ["npm", "pack", ROOT, "--pack-destination", str(tmp_path), "--ignore-scripts", "--json"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    archives = list(tmp_path.glob("tapebasis-*.tgz"))
    assert len(archives) == 1
    install = tmp_path / "install"
    prefix = tmp_path / "prefix"
    install.mkdir()
    subprocess.run(
        ["npm", "install", "--prefix", str(prefix), "--ignore-scripts", "--no-audit",
         "--no-fund", str(archives[0])],
        cwd=install,
        check=True,
        capture_output=True,
        text=True,
    )
    launcher = prefix / "node_modules/.bin/tapebasis"
    assert launcher.is_file()
    return launcher


async def _check_npm_stdio(launcher: Path, env: dict[str, str], cwd: Path) -> None:
    """Initialize the packed launcher's MCP stdio server and require its tool list."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(command=str(launcher), args=[], env=env)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=30)
            assert result.serverInfo.name
            tools = await asyncio.wait_for(session.list_tools(), timeout=30)
            names = {tool.name for tool in tools.tools}
            assert "stock_quote" in names
            assert "tapebasis_health" in names
            assert len(names) == 35


def test_built_distribution_initializes_and_lists_tools(distributions, tmp_path):
    """Install each real artifact outside the checkout and run an MCP session."""
    for artifact in distributions:
        subprocess.run(
            [_uv(), "run", "--no-project", "--python", sys.executable,
             "--with", str(artifact), str(ROOT / "tests/smoke_test.py")],
            cwd=tmp_path,
            check=True,
            env={**os.environ, "TAPEBASIS_HEALTH_ENABLED": "false"},
        )


def test_uvx_local_wheel_needs_no_publish_credentials(distributions, tmp_path):
    """Prove uvx can serve the wheel without PyPI publication credentials."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("UV_PUBLISH_")}
    env.update({
        "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        "UV_TOOL_DIR": str(tmp_path / "uv-tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "uv-bin"),
        "TAPEBASIS_HEALTH_ENABLED": "false",
    })
    wheel = next(path for path in distributions if path.suffix == ".whl")
    result = subprocess.run(
        [_uv(), "tool", "run", "--from", str(wheel), "tapebasis", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "streamable-http" in result.stdout


def test_package_manifest_excludes_test_and_checkout_sources(tmp_path):
    """The npm tarball contains only the launcher and package documentation."""
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(result.stdout)[0]
    files = {entry["path"] for entry in manifest["files"]}
    assert "npm/bin/tapebasis.js" in files
    assert not any(path.startswith("src/") for path in files)
    assert not any(path.startswith("tests/") for path in files)
    assert not any(path.startswith("node_modules/") for path in files)


def test_npm_tarball_installs_and_runs_its_launcher(tmp_path):
    """Install the real packed tarball and execute its exposed command."""
    launcher = _pack_and_install_npm(tmp_path)
    fake_uvx = tmp_path / "fake-uvx"
    record = tmp_path / "record.json"
    fake_uvx.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(record)!r}, 'w').write(json.dumps({{'args': sys.argv[1:], "
        "'mark': os.environ.get('MARK')}))\n",
        encoding="utf-8",
    )
    fake_uvx.chmod(0o755)
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"UV_PUBLISH_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN"}
    }
    env.update({"TAPEBASIS_UVX": str(fake_uvx), "MARK": "packed launcher"})
    result = subprocess.run(
        [str(launcher), "argument with spaces"], cwd=tmp_path / "install", env=env,
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(record.read_text(encoding="utf-8")) == {
        "args": ["tapebasis", "argument with spaces"], "mark": "packed launcher",
    }


def test_npm_tarball_serves_real_mcp_stdio(distributions, tmp_path):
    """The packed launcher runs the local wheel through real MCP discovery."""
    launcher = _pack_and_install_npm(tmp_path)
    wheel = next(path for path in distributions if path.suffix == ".whl")
    wrapper = tmp_path / "uvx-local-wheel"
    wrapper.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f'if [ "$1" != "tapebasis" ]; then\n'
        '  echo "unexpected uvx argument" >&2\n'
        "  exit 2\n"
        "fi\n"
        "shift\n"
        f'exec "{_uv()}" tool run --from "{wheel}" tapebasis "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    install = tmp_path / "install"
    environment = {
        key: value for key, value in os.environ.items()
        if key not in {"TAPEBASIS_UVX", "UV_PUBLISH_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN"}
        and not key.startswith(("UV_", "PYTHON"))
    }
    environment.update({
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        "TAPEBASIS_UVX": str(wrapper),
        "TAPEBASIS_HEALTH_ENABLED": "false",
    })
    asyncio.run(asyncio.wait_for(_check_npm_stdio(launcher, environment, install), timeout=180))
