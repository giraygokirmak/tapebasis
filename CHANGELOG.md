# Changelog

Tapebasis uses semantic versions. Each release section is the reviewed source of its GitHub Release summary.
Registry availability is recorded separately where a tag was published only partially.

## [1.1.4] - 2026-11-18

### Added

- `stock_earnings` optionally adds Equibles analyst estimates when
  `TAPEBASIS_EQUIBLES_API_KEY` is set. EPS estimates join `comparisons` only under an exact metric,
  period, statistic, unit, basis and dimension match; insufficient proof goes to
  `declined_comparisons` instead of an agreement or disagreement verdict. Numeric
  `dimAnalystCount` appears separately as single-source EPS-estimate contributor counts keyed by
  period; display strings are not parsed and no count stays null.
- `stock_ownership` optionally compares the same FINRA settlement-date short position with
  Equibles after converting Finviz thousands into shares. It requires the Enterprise entitlement,
  exposes `short_interest_consensus`, leaves the other filing populations single-source and never
  changes the envelope's `FINVIZ` label.
- `stock_quote.data` and `combined_analysis.data` directly expose distinct TradingView target,
  rating-analyst, Buy/Hold/Sell counts and Finviz visible-firm/action counts. The composite also
  mirrors the five real rating categories. Counts are never mixed across populations; a missing
  count is null and a supplied zero stays zero.
- Hermetic integration tests assert keyless zero transport, unchanged `ALL`/`PARTIAL`, exact EPS
  equivalence, settlement-date mismatch, declined comparisons and zero-versus-null counts.

### Changed

- General market `PROVIDER_ORDER`, `ALL_PROVIDERS`, `DEFAULT_ORDER` and freshness arbitration now
  exclude Equibles permanently. `RECONCILIATION_PROVIDER_ORDER` admits its label only for explicit
  configured capability adapters. Without a key there is no Equibles request, providers list,
  provenance, error or coverage effect in either shared tool.
- Dedicated Equibles tools, option chains, live quotes and historical prices retain their existing
  contracts. Live Equibles access and Enterprise publication rights remain unverified.
- Raised package, MCP Registry and launcher versions to `1.1.4`. The release workflow advances
  GHCR `1.1`, `1` and `latest` only after each alias independently matches the verified `1.1.3`
  image digest `sha256:08ded4615b33333c7c0ca988916da4c94f1339b53d664bdaea5b1d4c6f6f9028`.
  Exact-version conflicts, other predecessors and registry lookup failures remain fatal.

## [1.1.3] - 2026-11-18

### Added

- Added six separate Equibles tools backed only by the official authenticated REST API:
  `stock_fundamentals`, `stock_analyst_estimates`, `stock_ownership_flows`,
  `stock_short_positioning`, `stock_options_analytics` and `stock_price_history`.
  The tool surface is now 41 tools; existing Finviz, Yahoo and `stock_options_chain` contracts
  remain unchanged, and Equibles never joins the market fan-out. Raw datasets keep their original
  units, filing evidence, scope and per-dataset freshness and reporting delays.
- Added explicit response and failure contracts for `Data by Equibles`, `as_of`, `reporting_delay`
  and entitlement. Partial dataset failures stay `EQUIBLES`; partial `403` responses expose
  `partially_entitled` and `denied_datasets` rather than silently reducing coverage.
- Added a local Equibles configuration and declared-tier gate. `TAPEBASIS_EQUIBLES_API_KEY` supplies
  the Bearer credential, and `TAPEBASIS_EQUIBLES_ENTITLEMENT=enterprise` asserts that the operator's
  active redistribution agreement covers the restricted Phase 2 datasets. Preflight denials and real
  upstream `403` responses both use `not_entitled`; the flag does not override an actual denial.
- Equibles Rating, squeeze scores and AI Brief are deliberately absent: they are neither requested,
  implemented nor synthesized from the returned observations.
- Added an allowlisted redirect-refusing Equibles transport with sanitized errors, one request per
  selected dataset, no automatic pagination and no transport retries after daily `429`. Public quota
  and reset metadata blocks later requests until reset and appears in `tapebasis_health` under
  `rate_limits`. Health checks inspect only local configuration and the last real quota headers;
  this quota deadline is in-memory only and is not restored after a process restart.
- Added an automatic hermetic Equibles network guard plus tests for route and Enterprise bypass,
  redirects, sanitized errors, cache key rotation, concurrent daily-quota blocking and two event
  loops. No tests use a live credential or Equibles endpoint.

### Changed

- Raised package, MCP Registry and launcher versions to `1.1.3`. Documentation now describes all six
  Equibles tools and the nine provider labels alongside their security, freshness, quota and health
  semantics.

### Publication status

- The immutable tag run `44266286296` validated and built the source artifacts and published the PyPI
  wheel and sdist. It then staged npm with no GHCR, MCP Registry or GitHub Release write. After the
  maintainer approved npm with two-factor authentication, continuation run `44269347824` verified the
  original source ZIP digest
  `sha256:913618ae71494eeb71f72d5d355084def07fd286835b9ca4d34750fa64dbc5d0` and the live PyPI and npm
  bytes, without uploading them again. It completed MCP Registry publication and the GitHub Release.
- GHCR `1.1.3`, `1.1`, `1` and `latest` independently match the tested image root digest
  `sha256:08ded4615b33333c7c0ca988916da4c94f1339b53d664bdaea5b1d4c6f6f9028`. The immutable tag remains
  on the original tested `5a82429360673432338509bc9708f7a2fb25fb62` source commit.
- The npm staging token must be revoked now that this release has completed. No live Equibles credential
  or Enterprise agreement was validated, so endpoint behavior and redistribution rights remain unverified.

### Release process

- Bound the approved `1.1.3` GHCR `1.1`, `1` and `latest` alias advancement to a second live manifest
  match for the independently verified `1.1.2` predecessor digest
  `sha256:bfb7bf0adcc6717c0fd3281bc71182078fc861f7b0f49fb73e78018f847dcddd`. Normal publication and
  its source-bound continuation use this reviewed exception; wrong predecessors, other versions,
  unrelated conflicts and lookup failures remain fatal.
- No live Equibles key or Enterprise agreement was available during validation. Endpoint behavior and
  actual Enterprise publication rights are therefore not claimed as verified. Tagging, package
  publication and registry availability remain separate protected release steps; this version bump
  claims no completed publication or registry availability.

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

[1.1.4]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/giraygokirmak/tapebasis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/giraygokirmak/tapebasis/releases/tag/v1.0.0
