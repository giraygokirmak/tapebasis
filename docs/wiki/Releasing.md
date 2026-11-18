# Releasing

The `v1.0.0` wheel, sdist and npm launcher are published and match the original tag-run artifacts.
GHCR serves `1.0.0`, `1.0`, `1` and `latest` for `linux/amd64` and `linux/arm64`, all with the tested
root digest `sha256:4ff12fdcdc79e7c5cd065a3ffb685dcbe6daee518442b7751e0479e0da1e3167`.
The protected recovery independently verified these package bytes and image tags, and MCP Registry
metadata is published for `1.0.0`. npm's trusted publisher has not completed a real OIDC publish:
this repository uses immutable OIDC subject claims, and npm answers that token exchange with
`package not found` before it evaluates the trusted publisher, as reported upstream in
[npm/cli#9969](https://github.com/npm/cli/issues/9969). Package availability therefore does not prove
that configuration works, and the repository cannot switch the claim format off.
For `v1.1.1`, continuation runs `44089890432` and `44092787410` verified the original tested PyPI files
without re-upload but failed before any npm upload. No retry of either run is permitted. Run
`44106300065` staged the tested npm tarball, and the maintainer approved it on npm with two-factor
authentication. Run `44107314499` verified the live npm `1.1.1` SHA-512 integrity against the original
artifact rather than staging or uploading it again, then completed and verified GHCR, MCP Registry
metadata and the ordinary GitHub Release. GHCR `1.1.1`, `1.1`, `1` and `latest` all independently match
the tested root digest
`sha256:18a54e02f28d195030cd02ee1f45088eeb05a34792d532197f143f6a73a209d7`. The release environment's
stage-only token remains limited to the single package but must be revoked when staging is no longer
needed. The `1.1.2` source version was not published; its status remains historical and must not be
rewritten. The current `1.1.3` source adds the Equibles integration and is also not published while
this completed `v1.1.1` status is recorded separately from the existing Release body. No live
Equibles credential or Enterprise agreement has been validated, and registry publication still needs
the protected release steps and maintainer approval described below.
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
   downloads the same artifacts after approval. The source must be the original Release push for the
   immutable tag, never another dispatch run. Current main may be the exact tag commit; source tag,
   metadata, job results and artifact digest still bind it independently. If an earlier tag or
   continuation run left npm merely staged, approve that staged version first and give this
   continuation the same source run and tag. A failed dispatch before the protected writer starts is
   not retried; fix its source-binding or workflow cause on main and dispatch the same original pair again.
4. Existing matching packages and image tags are verified, not uploaded again. On PyPI this comparison
   is per distribution file: a release with a verified wheel but absent sdist, or the reverse, uploads
   only that absent file. Any unexpected, duplicate or conflicting file remains fatal. Other absent
   PyPI files,
   npm content, GHCR tags or MCP metadata enter their corresponding write step. Absent npm content is
   staged for your npm approval, which ends that run before GHCR, MCP or Release notes; no other
   registry treats the stage as a live package. Any conflict, transport
   failure or non-404 lookup stops publication unless an explicit predecessor digest was reviewed for
   that operation. The `v1.1.1` continuation advances `1` and `latest`, and only when a second
   manifest lookup matches the tested `1.0.0` root digest
   `sha256:4ff12fdcdc79e7c5cd065a3ffb685dcbe6daee518442b7751e0479e0da1e3167`. It copies those
   aliases to the tested `1.1.1` root digest
   `sha256:18a54e02f28d195030cd02ee1f45088eeb05a34792d532197f143f6a73a209d7`. An exact-version or
   minor-version conflict, wrong predecessor, other tag, authorization failure or other mismatch remains
   fatal. Independently reviewed `1.1.2` normal tag publication and its package continuation may
   advance `1.1`, `1` and `latest` from that same reviewed `1.1.1` digest by supplying
   `--advance-minor-major-latest-from`. Each alias requires its own second manifest match immediately
   before one copy to the tested new image. The options are valid only for their hard-coded version.
   An exact-version conflict, unrelated conflict, wrong predecessor, wrong version, authorization
   failure or transport failure cannot advance the affected alias. A successfully imported exact tag
   or an earlier approved alias is not retried unnecessarily. Other ordinary tag publications, other
   continuations keep missing-only image writes. MCP-only recovery never writes images. Review a new
   predecessor before dispatching or approving any comparable future exception.
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
  release-bound reviewed alias exceptions for `v1.1.1` and `1.1.2` are stated above and do not apply
  automatically elsewhere.
- Publication is sequential within the approval-gated publish job: PyPI, then npm, then GHCR. Each
  step must succeed before the next one starts. Only after those package versions resolve does the
  job publish `server.json` to the MCP Registry. A registry has no transaction that can retract an
  earlier successful upload automatically when a later step fails.
- `publish-image.yml` retains its filename but only calls the validation workflow. Main, pull requests
  and manual runs have no registry publication. An approved release tags its tested image `latest`;
  there is no moving main-branch image.

## GitHub Release identity

The writer verifies the existing immutable tag's source commit before creating or updating its Release.
It deliberately omits `target_commitish`, so GitHub can show `main` as the target while the Release's tag
still names the immutable artifact source. Do not patch this display field to imply that the old tag moved
or that the main revision is its tested source. The tag object, tag target, source artifact digest,
Release title and reviewed changelog body are the binding checks. A `v1.1.1` Release created after its
npm staging and completion runs therefore has `target_commitish: main`, while its immutable `v1.1.1` tag
still targets the tested `e1b2083406eaac34b72ba1d964cfc51e63610faa` source commit.

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
   not a workflow invocation. The only credential CI ever stores is the short-lived stage-only token
   described below, never a token able to publish directly. Do this bootstrap before the `v1.0.0` tag so
   PyPI does not upload first and then stop at an unprovisioned npm account. After bootstrap, set
   `TAPEBASIS_NPM_BOOTSTRAPPED=1` as a **release
   environment variable** on GitHub. This does not publish anything itself; it records that the manual
   step completed, and later also covers a staged version you approved on npm. Keep the variable unset
   on forks and before bootstrap. The tag job must not upload an already published version again.
4. In the npm package settings, keep **Trusted publishing** configured for GitHub Actions, with
   organization or user `giraygokirmak`, repository `tapebasis`, workflow filename `release.yml`, and
   environment `release`. npm requires Node.js 22.14.0 or newer and npm 11.5.1 or newer. This
   configuration cannot currently authenticate this repository: GitHub emits immutable OIDC subject
   claims, npm answers the token exchange with `package not found`, and the later `ENEEDAUTH` is only a
   secondary error. [npm/cli#9969](https://github.com/npm/cli/issues/9969) tracks the registry fix. The
   claim format cannot be switched off here, so repeating runs does not help.
5. Until that registry fix lands, create a **granular access token** whose package permission is
   **Read and write (stage only)** and whose only selected package is `tapebasis`. Give it no
   organization access, choose the shortest practical expiration, and leave **Bypass 2FA** off. Store it
   only as the `release` environment secret `TAPEBASIS_NPM_STAGE_TOKEN`, and revoke it after the
   release. A stage-only token cannot publish directly: `npm publish` fails with `E_STAGE_REQUIRED`. It
   can still move dist-tags and deprecate versions, so it is not a complete security boundary. Direct
   token publication is also deprecated and will be removed in January 2027, which makes staging the
   supported automation shape rather than a workaround invented here.
6. The publish jobs run `npm stage publish` through a temporary npmrc in `$RUNNER_TEMP`, created with a
   `077` umask and removed by an `EXIT` trap. The secret is read from the environment, never put on the
   command line or printed. Staging needs npm CLI 11.15.0 or newer and Node.js 22.14.0 or newer, which
   the GitHub-hosted Node.js 24 toolchain satisfies. The pinned `setup-node` v4 deliberately has no
   `registry-url`, because v4 also injects a `NODE_AUTH_TOKEN` placeholder and dummy credential. The
   tested tarball's `publishConfig.registry` already selects `https://registry.npmjs.org`. The command
   passes the explicit local path `./dist/tapebasis-${VERSION}.tgz`; without the leading `./` npm would
   treat the argument as a GitHub repository shortcut and fail over SSH before authentication.
   `--loglevel verbose` keeps the non-secret registry rejection visible. Never copy token values out of
   a log.
7. A run that stages a version stops there deliberately. Its summary says the version is staged, not
   published, and GHCR, the MCP Registry and the GitHub Release steps are skipped. Review the staged
   version in npm's **Staged Packages** tab and approve it with two-factor authentication, or run
   `npm stage approve <stage-id> --otp <code>`. The staging command can report success even when nothing
   is live, so its exit status is never the evidence. After your approval, run a second approved path:
   from a tag run, dispatch `resume_source_run=<that-run-id>` and `resume_tag=<that-tag>`; from a
   continuation, dispatch the same `resume_source_run` and `resume_tag` values again. The npm comparison
   then requires the live version and its SHA-512
   integrity to equal the tested tarball before GHCR, MCP and the Release notes run, and a staged-only
   result fails that verification. A token-based staged publication carries no trusted-publishing
   provenance attestation.
8. Remove the bootstrap credential from the local machine with `npm logout` when it is no longer needed.

The npm step never publishes directly and never overwrites registry content. Bootstrap npm once as
above, then approve each staged version. If the version already exists without the release marker, the
job stops. With the marker, it requires the registry's version and SHA-512 integrity to match the tested
tarball instead of uploading an existing version again. GHCR, the MCP Registry and the Release notes
wait for that verification. Do not regard a staged version or any other partial release as completed,
and do not retry a failed run without reviewing each registry.

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
