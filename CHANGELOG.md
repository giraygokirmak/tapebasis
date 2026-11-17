# Changelog

Tapebasis uses semantic versions. Each release section is the reviewed source of its GitHub Release summary.
Registry availability is recorded separately where a tag was published only partially.

## [1.1.2] - 2026-11-17

### Fixed

- Bounded PyPI and npm post-publication retries to explicit incomplete results, accepting only verified content.
- Added a separately approved continuation using the original tested tag artifacts for an older immutable tag.
- Preserved MCP-only recovery as a read-only package and image path.
- Prevented GHCR authorization or transport errors from triggering image writes.
- Associated reviewed Release notes with an existing verified tag without resubmitting a workflow-changing
  `target_commitish` that the built-in token cannot modify.
- Passed npm publication an explicit `./` local-tarball path instead of an accidental GitHub repository shortcut.

### Release process

- Kept `v1.1.1` immutable; raised the declared next version to `1.1.2` without claiming its publication.
- Added separate `resume_*` package continuation and `notes_*` Release-note dispatch pairs, preserving
  MCP-only recovery's prohibition on package and image writes.
- Bootstrapped a reviewed historical Release note for `1.0.0` without moving its tag, and documented the
  rejected `1.1.0` and partial `1.1.1` publication states without implying unavailable package releases.
- Added explicit HTTP-status GHCR lookups and tests for fatal authorization, transport and conflict cases.
- Added per-file PyPI continuation so an existing verified wheel or sdist is never re-uploaded.

- Reviewed changelog sections become idempotently updated GitHub Release notes for source tags.

## [1.1.1] - 2026-11-17

### Fixed

- Added the declared `tomli` fallback for release source metadata on Python 3.10.

### Publication status

- PyPI wheel and sdist match the original tested tag artifacts byte-for-byte.
- npm, GHCR and MCP Registry publication remain pending their separately approved continuation.

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
