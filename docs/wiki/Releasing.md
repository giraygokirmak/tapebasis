# Releasing

The `v1.0.0` wheel, sdist and npm launcher are published and match the original tag-run artifacts.
GHCR serves `1.0.0`, `1.0`, `1` and `latest` for `linux/amd64` and `linux/arm64`, all with the tested
root digest `sha256:4ff12fdcdc79e7c5cd065a3ffb685dcbe6daee518442b7751e0479e0da1e3167`.
The protected recovery independently verified these package bytes and image tags, and MCP Registry
metadata is published for `1.0.0`. The npm trusted publisher configuration has not yet completed a real
OIDC publish, so package availability does not prove that configuration works.
For `v1.1.1`, continuation run `44089890432` verified the original tested PyPI files without re-upload
but failed its missing npm publish with `ENEEDAUTH`. The npm `1.1.1` version remains absent. GHCR,
MCP and GitHub Release steps were skipped: GHCR `1.1.1` and `1.1` remain absent, `1` and `latest`
remain on the tested `1.0.0` image, MCP metadata remains at `1.0.0`, and only `v1.0.0` has an ordinary
GitHub Release. No retry of that run is permitted. The in-development `1.1.2` release is not published.
The rejected `v1.1.0` run
`44060097251` has no tested release artifacts: its Python 3.10 validation failed before the build or
protected publication started. No package, image, MCP entry or ordinary GitHub Release is published for
this tag; its reviewed publication status remains in `CHANGELOG.md`. Do not move the tag or synthesize
release artifacts for it.
Older partial releases require registry-specific inspection and protected continuation; their Git tags alone do not establish registry completeness.

## Partial release recovery

When a tag run fails partway through, do not retry the failed run. A retry reuses the old tag's YAML
and can attempt duplicate uploads. Instead, use the main-only `release-recovery` workflow dispatch.

### Prerequisites

1. Create a GitHub environment named `release-recovery` with deployment restricted to `main` and
   required reviewer approval. This is separate from the normal `release` environment.
2. Set `TAPEBASIS_NPM_BOOTSTRAPPED=1` as a **release-recovery environment variable**, not a secret,
   if the npm package was manually bootstrapped before the first tag. The `release` environment's
   variable is not automatically available to this separate environment. Keep it unset before the
   bootstrap has actually completed.

### Recovery procedure

1. Identify the failed source run ID and the immutable tag (e.g., `v1.0.0`).
2. Dispatch `release.yml` on `main` with `recover_source_run` and `recover_tag` inputs.
3. Recovery skips ordinary main validation and artifact rebuilding. Instead, it requires the original
   tag run's validation and build jobs to have passed and its protected publish job to have started.
   It validates that source run's tag, commit, source metadata and artifact digest, then downloads the
   exact tested artifacts. GitHub Contents API base64 line wrapping and normal ZIP files without Unix
   file-type bits are accepted, but checksums, safe paths and expected members remain mandatory. It
   verifies PyPI, npm, and GHCR content match those artifacts without uploading anything.
4. Only if all package registries match does it proceed to publish missing MCP Registry metadata.
   The read-only registry checker accepts `--output` after every subcommand, so it can write the
   status GitHub Actions consumes before deciding whether publication is needed. If any package is
   missing or differs, or this status lookup fails, the job stops and cannot modify packages or images.
5. After completion, verify each registry independently: PyPI files, npm integrity, GHCR tags, and
   MCP Registry metadata.

## Protected package continuation

Use this only when the original tested artifacts exist and an approved tag publish job started but left
publishable registry content absent. Do not move the tag or rebuild replacement artifacts.

1. Restrict the `release` environment to both `v*` tags and `main`, with required reviewer approval.
   The tag-only restriction is sufficient for new releases, but not for a main-dispatched continuation.
2. Inspect every registry and identify the source tag and its completed original run ID. Confirm which
   artifacts are already visible and which are explicitly absent. A differing artifact is never replaced.
3. Dispatch `release.yml` on `main` with `resume_source_run` and `resume_tag`. These two inputs must be
   supplied together, with the other input pairs empty. The package continuation requires the original
   protected publish job to have started, unlike the notes-only route below. It validates all source
   release identities, the live tag target and GitHub's immutable artifact ZIP digest, then independently
   downloads the same artifacts after approval.
4. Existing matching packages and image tags are verified, not uploaded again. On PyPI this comparison
   is per distribution file: a release with a verified wheel but absent sdist, or the reverse, uploads
   only that absent file. Any unexpected, duplicate or conflicting file remains fatal. Other absent
   PyPI files,
   npm content, GHCR tags or MCP metadata enter their corresponding write step. Any conflict, transport
   failure or non-404 lookup stops publication unless an explicit predecessor digest was reviewed for
   that continuation. The `v1.1.1` continuation alone advances `1` and `latest`, and only when a second
   manifest lookup matches the tested `1.0.0` root digest
   `sha256:4ff12fdcdc79e7c5cd065a3ffb685dcbe6daee518442b7751e0479e0da1e3167`. It copies those
   aliases to the tested `1.1.1` root digest
   `sha256:18a54e02f28d195030cd02ee1f45088eeb05a34792d532197f143f6a73a209d7`. An exact-version or
   minor-version conflict, wrong predecessor, other tag, authorization failure or other mismatch remains
   fatal. Ordinary tag publication and every other continuation keep missing-only image writes.
   Review that predecessor before dispatching or approving any comparable future exception.
5. Only after all registry checks does it write the source tag's Reviewed GitHub Release notes from the
   dispatched main commit's `CHANGELOG.md`. Use the notes-only operation when a publication step should
   not run at all.

Every dispatch run ID is passed through an environment variable, never inserted into a shell command.
The protected writer checks out the dispatched main revision for its helpers and notes, not the old tag's
workflow. Tag binding still requires the old immutable commit and its tested artifact.

## Reviewed GitHub Release notes

Create a `release-notes` environment restricted to `main`, with required reviewer approval. It has only
`contents: write` and `actions: read`, no package permission or OIDC identity. It cannot upload packages,
import or copy images, or publish MCP metadata. The normal and resumed package paths also create or update
Release notes after their registry checks, using their package identity and tested source commit.

To fill only missing or stale notes for a validated source tag whose immutable artifact is intact,
including a tag whose publish job never started:
dispatch on `main` with `notes_source_run` and `notes_tag`. Supply both values and no other operation pair.
The original tag validation and build must both have passed, and its immutable artifact must still be
available and intact. The writer reads the section for the old tag's version from the dispatched main
`CHANGELOG.md`, verifies the live tag still targets the tested source commit, and creates or patches only
that release's title and body. A read-back must match before the step succeeds. It does not claim that a
source tag was committed at the dispatched main revision, and it does not auto-generate a commit list.
After this verification, the Release request deliberately omits `target_commitish`. GitHub otherwise subjects that
field to its workflow-modification authorization when the old commit changed workflow files. The built-in
`GITHUB_TOKEN` cannot receive that separate authority even with `contents: write`; no personal access token or tag
movement is used. An existing immutable tag is always verified before the Release is created or patched.

All three dispatch pairs are mutually exclusive. Blank, incomplete or mixed input dispatches perform no
registry or Release write. Blank dispatches still run ordinary validation without publication. All
publication jobs use non-cancelling concurrency within their class, so two package writers cannot race.

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
- Reviewed changelog summaries for the declared version are mandatory. Each GitHub Release uses that
  section rather than an auto-generated commit list. PyPI's file-level status is `verified`, `missing`
  or `partial`; separate wheel and sdist outputs ensure attestations and uploads cover only absent
  files. Post-upload reads wait for incomplete status and accept only eventual `verified` content.
  GHCR publication authenticates once before any import or alias copy, including when the exact image
  already exists. PyPI and npm post-upload reads retry only explicit `missing` or `partial` package
  results for a finite interval and require eventual verified content. GHCR distinguishes HTTP 404
  absence through its registry API and compares `Docker-Content-Digest` with the tested OCI archive.
  Unrelated error text, authorization failures and conflicting digests never authorize a write. The
  sole reviewed alias exception for `v1.1.1` is stated above and does not apply automatically elsewhere.
- Publication is sequential within the approval-gated publish job: PyPI, then npm, then GHCR. Each
  step must succeed before the next one starts. Only after those package versions resolve does the
  job publish `server.json` to the MCP Registry. A registry has no transaction that can retract an
  earlier successful upload automatically when a later step fails.
- `publish-image.yml` retains its filename but only calls the validation workflow. Main, pull requests
  and manual runs have no registry publication. An approved release tags its tested image `latest`;
  there is no moving main-branch image.

## GitHub release approval

Create one protected environment named `release`. Restrict its deployments to `v*` tags for ordinary
releases, and also `main` when an older immutable tag needs an explicit package continuation. Require
maintainer review in either case. Gate all registry uploads through this one approval. Do not
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
   automation token is used. The pinned `setup-node` v4 deliberately has no `registry-url`: although
   newer npm examples include it, v4 also injects a `NODE_AUTH_TOKEN` placeholder and dummy credential.
   The tested tarball's `publishConfig.registry` already selects `https://registry.npmjs.org`. Keep this
   setup tokenless rather than following that example blindly. On a public repository publishing a
   public package, trusted publishing creates provenance automatically. The publish command passes the
   tested tarball as `npm publish "./dist/tapebasis-${VERSION}.tgz" --access public --loglevel verbose`.
   The leading `./` is required for a relative local path: without it npm interprets
   `dist/tapebasis-1.1.1.tgz` as a GitHub repository shortcut and attempts an unrelated SSH `ls-remote`,
   failing before any npm publication or OIDC authentication. Do not confuse that argument-parsing error
   with a trusted publisher rejection. Verbose logging exposes the otherwise hidden token-exchange body
   message when publication ends in generic `ENEEDAUTH`. Read only that non-secret message and never
   copy or expose token values. An account mismatch, including repository, workflow, environment or
   direct-publish permission, still requires maintainer correction on npm; the diagnostic is not itself
   a publisher repair. Any next publication uses a fresh dispatch and separate `release` approval.
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
   same implementation used by Python 3.11 and later rather than accepting malformed metadata.
   Source-artifact metadata validation uses the same `tomli` fallback and validates the original
   version, package lockfiles, `__version__` and source server manifest as one identity. Add the reviewed
   `CHANGELOG.md` section for this version in the same commit. Add
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
