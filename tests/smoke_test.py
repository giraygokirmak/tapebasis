"""Check that the installed distribution serves MCP over standard I/O.

This module intentionally imports no repository code. Run it in an isolated
interpreter after installing a built wheel or sdist, rather than from an
editable checkout. It returns via ``main`` after checking the distribution
location, the console entry point, and a real MCP ``initialize`` + ``tools/list``
exchange. It never performs an upstream market-data request.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def main() -> None:
    """Exit nonzero if the installed distribution fails any release smoke check."""
    package = importlib.util.find_spec("tapebasis")
    assert package is not None, "the wheel did not install the tapebasis package"
    location = pathlib.Path(package.origin).resolve()
    assert "site-packages" in str(location), f"not an installed distribution: {location}"
    from tapebasis import __version__
    from tapebasis.server import mcp

    version = importlib.metadata.version("tapebasis")
    assert __version__ == version, (version, __version__)
    assert mcp.name, "the installed server has no MCP name"

    executable = pathlib.Path(sys.executable).parent / "tapebasis"
    if os.name == "nt":
        executable = executable.with_suffix(".exe")
    help_result = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "streamable-http" in help_result.stdout

    print(json.dumps({"distribution": version, "package": str(location)}))
    asyncio.run(check_stdio())
    print("smoke: OK")


async def check_stdio() -> None:
    """Initialize the console script and list its registered MCP tools."""
    parameters = StdioServerParameters(
        command="tapebasis",
        args=[],
        env={
            **os.environ,
            "TAPEBASIS_HEALTH_ENABLED": "false",
            "PYTHONUNBUFFERED": "1",
        },
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=30)
            assert result.serverInfo.name
            tools = await asyncio.wait_for(session.list_tools(), timeout=30)
            names = {tool.name for tool in tools.tools}
            assert "stock_quote" in names
            assert "tapebasis_health" in names
            print(json.dumps({"mcp": "initialized", "tools": len(names)}))


if __name__ == "__main__":
    main()
