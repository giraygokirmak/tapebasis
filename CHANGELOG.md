# Changelog

Tapebasis uses semantic versions. Each release section is the reviewed source of its GitHub Release summary.
Registry availability is recorded separately where a tag was published only partially.

## [Unreleased]

## [1.2.1] - 2026-11-19

### Added

- Added Investing.com as a native `INVESTING` peer and the `investing_quote` tool, bringing the MCP
  surface to 56 tools. Native search, including bounded cursor pagination, resolves an unambiguous
  equity or ETF before the exact returned page repeats its symbol, exchange, currency, class,
  instrument id and native path. Ordinary shared quote fields retain normal reconciliation and
  freshness semantics. Analyst populations and technical summaries remain explicitly `INVESTING`
  single-source observations, and Investing failures never hide other provider responses.
- Ordinary stock `lastClose` is not assumed to be a previous close; only the explicit ETF
  `keyStatistics.prevClose` can supply that baseline. Regular and extended prints retain independent
  epoch-millisecond timestamps. Market capitalisation remains structurally `not_comparable` across
  providers with potentially different share-count bases and as-of dates.

### Fixed

- `stock_quote.data` now returns name-free, provider-prefixed rating summaries with totals and every
  supplied class: TradingView's three-month Strong Buy through Strong Sell distribution and Finviz's
  visible-row Buy, Hold, Sell, No Rating and Unclassified distribution. Finviz exact `label_counts`
  preserve Overweight, In-line, Mkt Perform and other actual last labels, while blank labels remain
  in `unlabeled_row_count`. Direct Finviz Buy/Hold/Sell counts and consistent single-source `fields`
  descriptors accompany them. Finviz's total remains
  visible rating actions, not institutions or all analysts. `combined_analysis.data` exposes the same
  TradingView summary. No cross-provider recommendation total is inferred.

### Changed

- Raised package, launcher and MCP Registry versions to `1.2.1`. For this release only, GHCR `1.2`,
  `1` and `latest` may advance after each alias independently matches the verified `1.2.0` digest
  `sha256:91e9f419c8abff54ab9f35285e6306731df1736b8db43959f0d45b0805647c39`. Read-only checks on
  2026-11-19 matched `1.2`, `1`, `1.2.0` and `latest` to this predecessor and found `1.2.1` absent.
  Exact-version replacement, omitted predecessor checks and later-release alias exceptions remain
  forbidden. Package, image, MCP Registry and GitHub Release completion require the protected tag
  publication and any npm staging approval.

## [1.2.0] - 2026-11-18

### Added

- Added 14 `equibles_*` family tools, bringing the MCP surface to 55 tools. They expose 188
  selected official Equibles JSON GET routes through exact `dataset` and documented `filters`, not
  per-endpoint tools or arbitrary URLs. `tapebasis_tool_map` and
  [Equibles Datasets](docs/wiki/Equibles-Datasets.md) provide the frozen route/filter map.
- Grouped calls preserve raw named datasets with `Data by Equibles`, observation freshness,
  reporting delay and `access`. Each dataset makes one authenticated GET with no automatic
  pagination or provider fallback. Live transcripts bypass cache; options retain the actual paid-plan
  requirement and `equibles_options(dataset="chain")` returns the raw chain when the account's plan
  permits it.
- Account-owned portfolio/organization/custom-data/web-feed trackers and binary/CSV assets stay
  excluded. Institution-copy backtests and direct two-institution portfolio comparison are not added.
  Provider ratings, predictions, squeeze scores and AI briefs remain source-labelled, not Tapebasis
  recommendations.

### Changed

- Removed `TAPEBASIS_EQUIBLES_ENTITLEMENT`, the local paid-tier assertion, pre-request
  `not_entitled` response and the old `entitlement` response field. `access` is now the sole public
  access status field. A missing key or real `401` returns `NOT_CONFIGURED`; a real `403` returns
  `PLAN_REQUIRED`, with `partially_available` where another requested dataset succeeds. Free, Plus
  and Pro access follows the actual Equibles response, never an empty or substituted result.
- Route validation accepts only the safe `%3A` normalization needed for `MIC:TICKER` and rejects
  other percent encodings and double encoding. Frozen filters use the reviewed OpenAPI types and
  explicit documented bounds, including UUID identifiers. Every route now has a hermetic HTTP-level
  one-GET regression test.
- Preserved the six established Equibles tools, exact-context EPS comparison and same-FINRA-
  settlement-date short-position comparison. Keyless general tools still make no Equibles request
  and gain no Equibles provider scope. Analyst populations stay separate, and Equibles never becomes
  a general live-price arbitration leg.
- Updated README, wiki, `.env.example` and packaged-server tool count together. Raised package,
  launcher and MCP Registry versions to `1.2.0`. An opt-in live check on 2026-11-18 succeeded for
  `equibles_company(dataset="profile")` with `access: configured`, and returned `PLAN_REQUIRED` for
  `equibles_options(dataset="chain")`. This confirms neither a successful paid-plan options response
  nor redistribution rights; all 188 routes retain hermetic HTTP-level regression coverage.
- For this release only, GHCR `1.2`, `1` and `latest` may advance after each alias independently
  matches the verified `1.1.4` digest
  `sha256:c16423260ee6a777f2fa79e9b799da7e9552b136593d314e09243121b1397597`. Read-only checks on
  2026-11-18 found this predecessor on the existing `1.1`, `1` and `latest` aliases and no `1.2` or
  `1.2.0` manifest. Exact
  version replacement, omitted predecessor checks and later-release alias exceptions remain forbidden.
  Package, image, MCP Registry and GitHub Release completion require the protected tag publication.

### Publication status

- Protected tag run `44356014425` validated and built the release artifacts, published the PyPI wheel
  and sdist, then staged the tested npm tarball for maintainer approval. After two-factor npm approval,
  source-bound continuation `44362229941` verified the original PyPI and npm contents and completed
  GHCR, MCP Registry and the reviewed GitHub Release. The immutable `v1.2.0` tag remains on commit
  `539835d30611ce4f455bf55c64a337d10ff03bbe`; the source artifact ZIP digest is
  `sha256:e4dc03de497c3e08fc0293e5d5233153532d68f46787fe9532332b5d2008671d`.
- GHCR `1.2.0`, `1.2`, `1` and `latest` independently match the tested multi-platform root index
  digest `sha256:91e9f419c8abff54ab9f35285e6306731df1736b8db43959f0d45b0805647c39`. The `1.1` and
  `1.1.4` tags remain on their prior digest. Independent post-publication checks verified the PyPI
  bytes, npm SHA-512 integrity, MCP metadata and reviewed Release body against the original artifacts.

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

### Publication status

- The immutable tag run `44292749356` validated and built the source artifacts, published the PyPI
  wheel and sdist, and staged npm. Artifact `14422891104` was independently downloaded and checked
  against its declared size and SHA-256 digest
  `sha256:119b8f290c1cf91473fa6191fb39c0e3772a2673e381351cb4f95f4aec56a066`.
- Continuation run `44297676282` verified the original tested artifact, compared existing PyPI and npm
  content without re-upload, advanced the reviewed GHCR aliases and completed MCP Registry metadata
  and the reviewed GitHub Release. The npm approval supplied through the registry made its live
  `1.1.4` integrity equal to the tested tarball.
- GHCR `1.1.4`, `1.1`, `1` and `latest` independently match the tested multi-platform root index
  digest `sha256:c16423260ee6a777f2fa79e9b799da7e9552b136593d314e09243121b1397597`. The exact
  `1.1.3` tag remains on the earlier digest; `v1.1.4` remains on the tested source commit
  `ea9166664f9c534eb602bdba929e5ccaaf0bca55`.
- The release environment's npm stage-only token can be revoked now that the staged approval and
  continuation are complete. No live Equibles credential or Enterprise publication rights were verified.

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

[1.2.1]: https://github.com/giraygokirmak/tapebasis/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.4...v1.2.0
[1.1.4]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/giraygokirmak/tapebasis/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/giraygokirmak/tapebasis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/giraygokirmak/tapebasis/releases/tag/v1.0.0
