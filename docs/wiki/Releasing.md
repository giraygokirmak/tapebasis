# Releasing

The `v1.0.0` wheel, sdist and npm launcher are published and match their registry digests. GHCR serves
the `1.0.0` image for `linux/amd64` and `linux/arm64`. The normal tag run stopped during its GHCR
verification step before publishing MCP Registry metadata. The MCP Registry entry remains incomplete
until the protected recovery described below succeeds. The npm trusted publisher configuration has not
yet completed a real OIDC publish, so package availability does not prove that configuration works.

## Partial release recovery

When a tag run fails partway through, do not retry the failed run. A retry reuses the old tag's YAML
and can attempt duplicate uploads. Instead, use the main-only `release-recovery` workflow dispatch.

### Prerequisites

1. Create a GitHub environment named `release-recovery` with deployment restricted to `main` and
   required reviewer approval. This is separate from the normal `release` environment.
2. Ensure `TAPEBASIS_NPM_BOOTSTRAPPED=1` is set as a repository variable (not a secret) if the npm
   package was manually bootstrapped before the first tag.

### Recovery procedure

1. Identify the failed source run ID and the immutable tag (e.g., `v1.0.0`).
2. Dispatch `release.yml` on `main` with `recover_source_run` and `recover_tag` inputs.
3. The workflow validates the source run's tag, commit, and artifact digest, then downloads the exact
   tested artifacts. It verifies PyPI, npm, and GHCR content match those artifacts without uploading
   anything.
4. Only if all package registries match does it proceed to publish missing MCP Registry metadata.
   If any package is missing or differs, the job stops and cannot modify packages or images.
5. After completion, verify each registry independently: PyPI files, npm integrity, GHCR tags, and
   MCP Registry metadata.

## Distribution contract

- `test.yml` runs on main and pull requests, with no publishing credentials. It tests the checkout,
  builds and installs the real wheel and sdist, performs an MCP initialize and tools-list exchange,
  tests the npm launcher, packs npm, and checks release metadata.
- `release.yml` also validates main, but its publish job runs only on a pushed `v*` tag. A tag that
  disagrees with the version in `pyproject.toml` stops before any upload.
- The build installs the built Python distributions in isolated environments. `tests/smoke_test.py`
  opens a real MCP stdio client against their console entrypoint; it does not import an editable
  checkout or substitute fake provider checks for the package check.
- npm ships only a launcher and package documentation. It starts `uvx tapebasis`, forwarding stdio,
  arguments and environment. It is not a second TypeScript MCP server. Node.js 18 or newer and uv
  are required on the user's machine.
- A tag build produces the wheel, sdist, npm tarball and OCI image once. The publish job downloads
  those tested artifacts and verifies their SHA-256 checksums instead of silently rebuilding them.
- Publication is sequential within the approval-gated publish job: PyPI, then npm, then GHCR. Each
  step must succeed before the next one starts. Only after those package versions resolve does the
  job publish `server.json` to the MCP Registry. A registry has no transaction that can retract an
  earlier successful upload automatically when a later step fails.
- `publish-image.yml` retains its filename but only calls the validation workflow. Main, pull requests
  and manual runs have no registry publication. An approved release tags its tested image `latest`;
  there is no moving main-branch image.

## GitHub release approval

Create one protected environment named `release`. Restrict its deployments to `v*` tags and require
maintainer review before deployment. Gate all registry uploads through this one approval. Do not
create or rely on separate `pypi`, `npm`, `ghcr` or MCP environments; those names would not match the
workflow. No registry publication secrets need to be stored in the environment.

Protect `v*` tags against unauthorized creation or modification. The workflow cannot infer who created
a tag, so environment approval and tag protection are the human release controls.

## One-time PyPI setup

Use [PyPI's pending trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
before the first release; no existing project or persistent API token is needed.

| Field | Value |
| --- | --- |
| PyPI project name | `tapebasis` |
| Owner | `giraygokirmak` |
| Repository | `tapebasis` |
| Workflow name | `release.yml` |
| Environment name | `release` |

The publish job has `id-token: write` and uses `uv publish --trusted-publishing always`. Do not
configure `UV_PUBLISH_TOKEN`, a PyPI API token, or username/password publishing in CI. A missing or
mismatched pending publisher is an account setup failure and stops at PyPI.

## One-time npm setup

npm requires the package to exist before a trusted publisher can be configured on its package settings
page. That prevents the very first package creation from being authenticated by its as yet unconfigured
OIDC publisher. This is a bootstrap limitation, not a permanent token requirement.

1. Verify `npm view tapebasis version` reports that the package does not exist. If someone else has
   claimed it, choose another available unscoped name and update `package.json`, the lockfile,
   `server.json`, install examples and release checker together. Do not publish over another package.
2. Run the full test and package gate from a clean checkout at the intended release commit.
3. With the npm account that will own the package, run `npm login` interactively. Then publish the
   already tested tarball with `npm publish ./tapebasis-1.0.0.tgz --access public --otp=<current-code>`.
   Complete interactive two-factor authentication as prompted. This is an explicit maintainer action,
   not a workflow invocation. Never put a persistent npm token in a GitHub environment or log it.
   Do this bootstrap before the `v1.0.0` tag so PyPI does not upload first and then stop at an
   unprovisioned npm account. After bootstrap, set `TAPEBASIS_NPM_BOOTSTRAPPED=1` as a **release
   environment variable** on GitHub. This does not publish anything itself; it records that the manual
   step completed. Keep the variable unset on forks and before bootstrap. The tag job must not call
   `npm publish` for this already published version.
4. In the npm package settings, choose **Trusted publishing**, then GitHub Actions, with organization
   or user `giraygokirmak`, repository `tapebasis`, workflow filename `release.yml`, and environment
   `release`. Allow direct `npm publish` for this workflow. The case and filename must match exactly.
   npm requires Node.js 22.14.0 or newer and npm 11.5.1 or newer. A new trusted publisher configuration
   must complete its first successful publish within 2 days, or it expires and must be recreated.
5. The workflow uses GitHub-hosted Node.js 24 and its bundled npm CLI. It exchanges GitHub's OIDC
   identity for a short-lived publish credential; no `NPM_TOKEN`, `NODE_AUTH_TOKEN`, or persistent
   automation token is used. On a public repository publishing a public package, trusted publishing
   creates provenance automatically.
6. Prefer restricting ordinary token publishing in npm after the trusted publisher is working. Remove
   the bootstrap credential from the local machine as usual with `npm logout`.

The npm step deliberately fails rather than falling back to a stored token. Bootstrap npm once as
above, then subsequent tags use trusted publishing. If the version already exists without the release
marker, the job stops. With the marker, it requires the registry's version and SHA-512 integrity to
match the tested tarball instead of uploading an existing version again. Any other version is published
through OIDC; a mismatch stops GHCR and MCP Registry publication. Do not regard a partial release as
completed or retry it without reviewing each registry.

## GHCR setup

The same approved publish job uses the built-in `GITHUB_TOKEN` with `packages: write` and downloads the
tested OCI archive. It publishes `1.0.0`, `1.0`, `1`, and `latest` for this release. It does not publish
a `v`-prefixed image tag. After the first GHCR publication, set the container package's visibility to
public if unauthenticated pulls are intended, then confirm `docker pull` works without credentials.
Creating the environment does not create a package or make it public.

No long-lived container-registry secret is needed. An older main-image package can continue to exist;
release automation neither creates nor changes its visibility.

## MCP Registry setup

The server name is `io.github.giraygokirmak/tapebasis`. `package.json` carries the matching `mcpName`
marker, README carries the PyPI `mcp-name` marker, and the OCI image carries the corresponding ownership
label. These markers are validated before publication, but do not prove that registry publication has
already happened.

The verified `mcp-publisher` executable logs in with `github-oidc`. Publishing from this repository's
GitHub workflow proves the matching GitHub namespace; no separate MCP Registry account or persistent
registry token is needed. The registry currently supports the official npm and PyPI registries used by
`server.json`, and hosts metadata rather than package artifacts. The workflow runs `mcp-publisher
validate` before building, then publishes only after PyPI, npm and GHCR have succeeded and their version
endpoints are readable.

## Version bump and release

1. Run `git fetch --tags` and inspect existing tags and the intended target commit.
2. Update the same semantic version in `pyproject.toml`, `src/tapebasis/__init__.py`, `package.json`,
   the root and `packages[""]` entries of `package-lock.json`, `server.json`, and its npm and PyPI
   package entries. Update registry ownership markers only if the server identity also changes.
3. Run `PATH=<uv-install-directory>:$PATH scripts/quality-gate.sh --commit` locally after installing
   the project and its development extras in `.venv`. Omit the `PATH=` prefix when uv is already
   installed. On Python 3.10 the project installs `tomli`, so `check_release.py` parses TOML with the
   same implementation used by Python 3.11 and later rather than accepting malformed metadata. Add
   `npm test`, `npm run check`, and `npm pack --dry-run` for launcher changes. The full test gate
   already performs the real build, installation and MCP smoke tests.
4. Land the tested commit on main. Do not tag an uncommitted working tree, and do not tag merely to make
   red CI retry. The gate does not tag or publish anything itself. Its pre-push wiki mirror runs in an
   independent child repository with inherited `GIT_*` repository bindings removed, and records its
   sync stamp in the source worktree's actual Git directory. A successful source push therefore cannot
   turn the wiki child commit into a main-branch commit. The production wiki URL is fixed;
   `TAPEBASIS_WIKI_REPOSITORY` exists only to redirect the hermetic Git-context regression test to a
   temporary local wiki. Do not set it for a normal release push.
5. Check the candidate without a previous-ref comparison for the first release:

   ```bash
   python scripts/check_release.py --tag v1.0.0
   ```

   For a later release, compare against an existing previous tag. For example:

   ```bash
   python scripts/check_release.py --tag v1.0.1 --against v1.0.0
   ```

   `--against` requires the git ref to resolve, its version to be valid, and the new version to be newer.
6. Have a maintainer create and push one `v*` tag matching the declared version. Do this only after PyPI
   is provisioned and npm bootstrap is deliberately planned or already completed.
7. Watch Validate, Build release artifacts and Publish. Approve the `release` deployment only after
   checking the successful tests, artifacts and tag. The publish job records no successful publication
   until all steps finish. Branch runs and pull requests never get an upload credential.
8. Check each registry, including the MCP Registry search endpoint, after the job reports success:

   ```bash
   curl 'https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.giraygokirmak/tapebasis'
   ```

## Recovery

Investigate the workflow log and each registry before retrying. PyPI and npm reject republishing an
existing version with different contents; increment versions when a new artifact is required. GHCR tags
can move, so an operator must confirm a release retry does not unexpectedly overwrite a previous one. A
tag mismatch, tests, distribution smoke test, npm launcher test, package inspection, checksum, missing
artifact or earlier publish failure is always release-stopping. There is no `continue-on-error`
publication fallback and no `always()` job bypass. MCP Registry failure comes last, so inspect all
package uploads before deciding how to complete that release.

The OCI archive layout is unit-tested locally and the release workflow builds the real image in CI. A
local environment without a working Docker daemon cannot claim to have completed that image build.

## Smoke-test boundary

One local npm stdio run with MCP Python SDK 1.30.0 completed package installation and tool discovery,
then reported `BrokenResourceError` while the SDK's stdout reader was shutting down. Targeted and
complete gate reruns passed without changing the server or suppressing that exception. The tests contain
no retry or error allowlist. Treat a recurrence as a failed release gate and capture the child's stderr;
do not describe that single observed teardown failure as fixed by a successful rerun. An upstream SDK
fix requires a separate, reproducible dependency change rather than hiding it in the release launcher.

## Related

- [Development](Development): local test and quality-gate commands
- [Docker](Docker): release image tags, build and deployment
- [Design Decisions](Design-Decisions): why credentials and publication are separated
