# Docker

The image runs the server over streamable HTTP as a non-root user, under `tini` as PID 1, with a
healthcheck and a named volume for state.

## Prebuilt image (GHCR)

Every push to `main` publishes a multi-arch image to the GitHub Container Registry, so a deployment
can skip the build entirely:

```bash
docker pull ghcr.io/giraygokirmak/tapebasis:latest
docker run -d --name tapebasis -p 127.0.0.1:6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  ghcr.io/giraygokirmak/tapebasis:latest
curl -s localhost:6013/health
```

| Tag | Points at |
| --- | --- |
| `latest`, `main` | Head of `main` |
| `sha-<shortsha>` | One exact commit |
| `<major>.<minor>.<patch>`, `<major>.<minor>`, `<major>` | A pushed `v*` tag |

One manifest covers `linux/amd64` and `linux/arm64`. The package is public, so no login is needed to
pull it. If you fork the repository, the workflow publishes to your own namespace automatically
(`images: ghcr.io/${{ github.repository }}`) using the built-in `GITHUB_TOKEN`, no extra secret
required.

## Compose (recommended)

```bash
cp .env.example .env      # optional; every setting has a default
docker compose up -d --build
docker compose logs -f
curl -s localhost:6013/health
```

`--build` builds from this checkout. To run the published image through compose instead, drop the
`build:` block (or set `image:` to the GHCR reference) and run `docker compose up -d`.

Host port `6013` is bound to `127.0.0.1` by default; change the mapping in `docker-compose.yml` if
it conflicts with something already running. Compose accepts an explicit `TAPEBASIS_BIND_ADDRESS`
for a deliberate non-loopback deployment. `HOST=0.0.0.0` remains necessary inside the container for
the published port to work; it does not choose the host bind address.

The MCP and health listener is unauthenticated. Remote exposure requires more than changing an
environment setting: the operator must choose a routable host address and place authentication and
transport protection in front of the service. For example, `TAPEBASIS_BIND_ADDRESS=0.0.0.0`
deliberately publishes on every host interface. Do not use that setting on an untrusted network
without a reverse proxy that supplies authentication and TLS. This change does not add authentication
or server-level DNS/host-header filtering.

## Standalone build

```bash
docker build -t tapebasis:latest .
docker run -d --name tapebasis -p 127.0.0.1:6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  tapebasis:latest
```

## What the image does

| Stage | Purpose |
| --- | --- |
| builder | Upgrades pip/certifi, installs `uv`, installs the package system-wide |
| runtime | Copies installed site-packages and the console entrypoint, upgrades pip/certifi again, installs `tini`, drops to `mcpuser` |

The build copies only `pyproject.toml`, README, license files and `src`. Setuptools installs the
package and its coinlist text resources into `site-packages`, and runtime copies that installed
package rather than the checkout. `.dockerignore` excludes environment files except `.env.example`,
credential-shaped filenames, source-control state, tests, docs, local environments, caches and
runtime state. It reduces exposure from both the Docker context and the image. Deployment operators
must still avoid placing secret material under a permitted source filename: filename-based filtering
is a safeguard, not a secret scanner.

Both stages upgrade `pip` and `certifi` before touching PyPI. This is deliberate: base images built
before the eMudhra/emSign CA incident (Oct 2026) ship a `certifi` that still trusts the compromised
chain, and a `pip install` through it would fail or, worse, succeed against the wrong host.

The container runs as `mcpuser`, never root.

## PID 1, zombies and shutdown

The image ships [`tini`](https://github.com/krallin/tini) and uses it as the entrypoint, so the
server is **not** PID 1:

```
ENTRYPOINT ["/usr/bin/tini", "--", "tapebasis"]
```

This is not decoration. Python does not reap children, and Docker starts the `HEALTHCHECK` (and every
`docker exec`) inside the container's PID namespace with a parent that lives outside it. Those
processes are reparented to PID 1, and a PID 1 that never calls `wait()` leaves each one behind as a
zombie: one extra `<defunct>` entry every 30 seconds, forever. `tini` reaps them and forwards
`SIGTERM` to the server, so `docker stop` still takes uvicorn's graceful path instead of a bare kill
and a restart loop.

`docker-compose.yml` additionally sets `init: true`, so the same protection applies if you swap the
image for one that does not bundle `tini`. Running `docker run --init ...` is therefore redundant but
harmless.

If you build your own image from a different base, either install `tini` the same way or always pass
`--init`; without one of the two, the container accumulates zombies until it is restarted.

## Volumes

| Path in container | Volume | Contents |
| --- | --- | --- |
| `/home/mcpuser/.tapebasis` | `tapebasis-state` | Chart PNGs + health baselines |

`stock_chart` includes the PNG in the MCP JSON response, so remote clients do not need access to this
volume. The retained local copy is optional. At most 32 generated chart PNGs are kept, oldest first by
modification time; unrelated files are not removed.

Persisting the health state is not cosmetic: the drift baselines live there. Without the volume,
every restart re-baselines and a slow-moving schema change could be adopted as the new normal.

```bash
docker volume inspect tapebasis_tapebasis-state
```

## Healthcheck

Both the Dockerfile and compose define the same check:

```bash
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
```

It hits `/health`, which reads the **cached** monitor verdict and makes no upstream call. That keeps
the check cheap and independent of third-party availability: a Finviz outage should not mark the
container unhealthy.

| Setting | Value |
| --- | --- |
| interval | 30 s |
| timeout | 5 s |
| start_period | 15 s |
| retries | 3 |

## Environment

Compose sets the values that matter in a container:

```yaml
environment:
  - PORT=8000
  - HOST=0.0.0.0
  - FINVIZ_CACHE_TTL=30
  - FINVIZ_TIMEOUT=25
  - TAPEBASIS_HEALTH_ENABLED=true
  - TAPEBASIS_HEALTH_INTERVAL=300
  - TAPEBASIS_HEALTH_TTL=60
  - TAPEBASIS_HEALTH_STATE=/home/mcpuser/.tapebasis/state/health_state.json
  - FINVIZ_CHART_DIR=/home/mcpuser/.tapebasis/charts
```

`HOST=0.0.0.0` is required inside the container: binding to loopback would make the port mapping
useless.

`.env` is loaded with `required: false`, so a missing file is not an error.

Add `MARKETAUX_API_TOKEN` to `.env` only if you want the licensed news/sentiment path. Nothing
requires it.

### Scaling and rate limits

Limiter state is **per process**. Running several containers (or several replicas) multiplies the
effective request rate against every upstream, and each replica discovers a block on its own before
sharing nothing. If you scale out, raise `TAPEBASIS_<PROVIDER>_MIN_INTERVAL` accordingly, or run a
single replica.

## Verifying a deployment

```bash
# 1. Process up, health endpoint answering
curl -s localhost:6013/health | python -m json.tool

# 2. Container healthy
docker compose ps

# 3. Drift verdicts and rate-limit state
curl -s localhost:6013/health | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('status'), d.get('degraded'), d.get('rate_limits'))"
```

A `degraded: true` from a fresh container usually means an upstream is genuinely down or has changed
shape. Check `docker compose logs` and then [Troubleshooting](Troubleshooting).

## Notes

- **No proxy support** is built in. Every provider reaches its upstream directly. Use
  network-level egress control if you need it.
- The image has no authentication. Compose binds to loopback by default. Do not choose a remote bind
  address without a reverse proxy that adds authentication and TLS.
- Image size is dominated by pandas and the provider layer; it is not a slim image. `curl_cffi`, which
  the Bloomberg provider needs for its TLS impersonation, adds about 14 MB of bundled libcurl.
- Bloomberg needs no extra configuration in the image: `curl_cffi` is a normal dependency, and the
  provider paces itself at one request every 10 s. An egress rule that blocks `bloomberg.com` makes
  `bloomberg_*` return `NONE`, and turns the Bloomberg leg of `stock_quote` into a stated error while
  the other readings still go out. Because of that pace, `stock_prices` asks it about at most
  four tickers per call and names the rest in `warnings`; raise
  `TAPEBASIS_BLOOMBERG_BATCH_MAX` only if you accept the extra latency.
- StockAnalysis needs nothing beyond egress to `stockanalysis.com`; it is plain `httpx`, paced at
  0.5 s, and has no batch cap. An egress rule that blocks it turns its leg of `stock_quote` /
  `stock_prices` / `stock_extended_hours` into an ordinary `errors` entry while the other readings
  still go out.

## Related

- [Configuration](Configuration): every variable
- [Health Monitor](Health-Monitor): what `/health` reports
