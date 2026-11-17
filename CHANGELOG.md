# Changelog

Tapebasis uses semantic versions. Each release section is the reviewed source of its GitHub Release summary.
Registry availability is recorded separately where a tag was published only partially.

## [1.1.2] - 2026-11-17

### Added

- Added TradingView analyst target bounds and the forecast page's five-bucket rating distribution
  using its actual scanner fields, while keeping its SSR target-estimate population separate.
- Added Finviz visible-row rating distributions, preserved rating and price-target transitions, and
  per-row implied upside computed only from the same SSR's `lastClose` and newest target. Unknown
  final rating labels stay unclassified. Missing, invalid and nonpositive targets leave upside null,
  as do non-finite inputs and results.

### Fixed

- Bounded PyPI and npm post-publication retries to explicit incomplete results, accepting only verified content.
- Added a separately approved continuation using the original tested tag artifacts for an older immutable tag.
- Allowed a protected continuation whose current main commit exactly equals the immutable source tag's
  commit. The original Release push, tag target, metadata, successful build and artifact digest remain
  mandatory; another dispatch run still cannot supply source artifacts.
- Preserved MCP-only recovery as a read-only package and image path.
- Prevented GHCR authorization or transport errors from triggering image writes.
- Associated reviewed Release notes with an existing verified tag without resubmitting a workflow-changing
  `target_commitish` that the built-in token cannot modify.
- Passed npm publication an explicit `./` local-tarball path instead of an accidental GitHub repository shortcut.
- Replaced direct npm publication with staged publication, so a maintainer approves each version with
  two-factor authentication on npm before GHCR, the MCP Registry and the Release notes are completed.
- Diagnosed npm's token-exchange rejection as this repository's immutable OIDC subject claims, reported
  upstream as [npm/cli#9969](https://github.com/npm/cli/issues/9969), rather than a trusted-publisher
  mismatch. Kept verbose non-secret diagnostics.
- Retained tokenless `setup-node` because pinned v4's `registry-url` injects a placeholder credential.

### Release process

- Kept `v1.1.1` immutable; raised the declared next version to `1.1.2` without claiming its publication.
- Added separate `resume_*` package continuation and `notes_*` Release-note dispatch pairs, preserving
  MCP-only recovery's prohibition on package and image writes.
- Bootstrapped a reviewed historical Release note for `1.0.0` without moving its tag, and documented the
  rejected `1.1.0` and partial `1.1.1` publication states without implying unavailable package releases.
- Added explicit HTTP-status GHCR lookups and tests for fatal authorization, transport and conflict cases.
- Bound the approved `v1.1.1` GHCR `1` and `latest` alias advancement to its tested source image and
  the verified predecessor digest for `1.0.0`. Added a separate `1.1.2`-only exception for `1.1`, `1`
  and `latest`, requiring each alias to match the verified `1.1.1` digest immediately before its copy.
  Both options reject every other version. Exact-version or unrelated conflicts, wrong predecessors,
  authorization failures and transport failures cannot advance the affected alias. Other release and
  MCP-only recovery paths receive neither exception, and matching registry content is not uploaded again.
- Added per-file PyPI continuation so an existing verified wheel or sdist is never re-uploaded.

- Reviewed changelog sections become idempotently updated GitHub Release notes for source tags.

## [1.1.1] - 2026-11-17

### Fixed

- Added the declared `tomli` fallback for release source metadata on Python 3.10.

### Publication status

- PyPI wheel and sdist match the original tested tag artifacts byte-for-byte. Continuation runs
  `44089890432` and `44092787410` failed before any npm upload after npm rejected this repository's
  immutable OIDC subject claims. Neither run may be retried.
- Run `44106300065` staged the original tested npm tarball with the release-only stage credential.
  A maintainer approved it with npm two-factor authentication. Run `44107314499` then verified its
  live SHA-512 integrity without staging or uploading it again. npm `1.1.1` and its `latest` tag now
  match the original tarball; the stage-only credential still requires revocation when staging ends.
- Run `44107314499` completed GHCR without replacing matching package content. The `1.1.1`, `1.1`,
  `1` and `latest` aliases independently match the tested image root digest
  `sha256:18a54e02f28d195030cd02ee1f45088eeb05a34792d532197f143f6a73a209d7`. MCP Registry metadata
  for `1.1.1` matches the immutable source `server.json`, and the GitHub Release carries this reviewed
  changelog section. The `v1.1.1` tag remains on its original source commit.

## [1.1.0] - 2026-11-17

### Added

- Added real-feed symbol news, newest-first merging and provider-corroborated consensus.
- Added provider-labelled analyst targets, separate contributor and rating populations, and target comparisons.
- Added MCP-only recovery validated against the original approved tag-run artifacts.

### Publication status

- The release tag was rejected during validation. No registry package or image was published for this tag.

## [1.0.0] - 2026-11-15

### Added

- Published the initial multi-provider Tapebasis MCP server, Python package, npm launcher and OCI image.
- Added explicit provider provenance, comparison semantics and protected tag publication.

### Publication status

- PyPI, npm and the tested GHCR image were published and verified by protected recovery.
- MCP Registry metadata remains at this version while later package releases are completed.

[1.1.2]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/giraygokirmak/tapebasis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/giraygokirmak/tapebasis/releases/tag/v1.0.0
