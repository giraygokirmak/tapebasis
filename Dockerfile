# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

# eMudhra/emSign CA incident (Oct 2026): python base images built before the fix ship a pip and
# certifi that still trust the compromised chain. Upgrade both before anything else touches PyPI.
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2.2" "certifi>=2026.10.19"

# Install system deps and uv
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh

WORKDIR /app

# Copy only the distribution inputs. Setuptools includes the coinlist text files
# as package data; the installed package, not a checkout, supplies them at runtime.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ ./src/

# Install the package and its dependencies into the system Python
RUN uv pip install --system .

# ---- Stage 2: Runtime ----
FROM python:3.11-slim

# MCP Registry ownership verification for the published OCI image.
LABEL io.modelcontextprotocol.server.name="io.github.giraygokirmak/tapebasis"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/tapebasis /usr/local/bin/tapebasis

# The installed package contains the coinlist text files. Do not copy the
# checkout into runtime: credentials and local state must not enter the image.

# eMudhra/emSign CA incident (Oct 2026): python base images built before the fix ship a pip and
# certifi that still trust the compromised chain. Upgrade both before anything else touches PyPI.
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2.2" "certifi>=2026.10.19"

# Create non-root user for security
RUN useradd -m mcpuser && chown -R mcpuser:mcpuser /app

# tini becomes PID 1. Python does not reap children, so without a reaper every
# process that the runtime starts inside the container's PID namespace and then
# abandons (the HEALTHCHECK exec is the steady case: its parent lives outside
# the namespace, so it is reparented to PID 1) is left behind as a zombie, one
# per check. tini also forwards SIGTERM to the server, so `docker stop` still
# shuts down through uvicorn's graceful path instead of a bare kill.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Chart PNGs and the health-monitor baselines are written here; mount a volume to
# keep both (and the drift detection history) across restarts.
RUN mkdir -p /home/mcpuser/.tapebasis/charts /home/mcpuser/.tapebasis/state \
    && chown -R mcpuser:mcpuser /home/mcpuser/.tapebasis
ENV FINVIZ_CHART_DIR=/home/mcpuser/.tapebasis/charts
ENV TAPEBASIS_HEALTH_STATE=/home/mcpuser/.tapebasis/state/health_state.json

USER mcpuser

# Expose the HTTP port
EXPOSE 8000

# Health check (cheap: reads the cached monitor verdict, no upstream call)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the MCP server over streamable-http (ideal for Docker/remote deployments).
# tini is PID 1 and execs this as a child, so a zombie has a parent that reaps
# it. `docker run --init` would also work; baking it in means the published
# image is safe even when the caller does not pass `--init`.
ENTRYPOINT ["/usr/bin/tini", "--", "tapebasis"]
CMD ["streamable-http", "--host", "0.0.0.0", "--port", "8000"]
