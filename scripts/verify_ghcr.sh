#!/usr/bin/env bash
# Verify every GHCR release tag against the tested OCI root index digest.
# Optional tag-job mode publishes only missing tags, never a verified existing tag.
set -euo pipefail

VERSION="${1:?release version is required}"
MODE="${2:-verify}"
IMAGE="ghcr.io/${GITHUB_REPOSITORY:?repository is required}"
REGCTL="${REGCTL:-./regctl}"
[ "$MODE" = verify ] || [ "$MODE" = publish-missing ]
mkdir -p "${RUNNER_TEMP:-/tmp}"
export REGISTRY_CONFIG="${REGISTRY_CONFIG:-$(mktemp "${RUNNER_TEMP:-/tmp}/tapebasis-regctl.XXXXXX")}"
expected="$(python3 scripts/check_oci_image.py --digest dist/tapebasis-image.tar)"
test -n "$expected"
for tag in "$VERSION" "${VERSION%.*}" "${VERSION%%.*}" latest; do
  actual=""
  for attempt in 1 2 3 4 5; do
    if actual="$("$REGCTL" manifest get "$IMAGE:$tag" --format '{{.GetDescriptor.Digest}}' 2>&1)"; then
      if [ "$actual" = "$expected" ]; then
        break
      fi
      printf 'GHCR %s has digest %s, expected tested image %s\n' "$tag" "$actual" "$expected" >&2
      exit 1
    fi
    actual=""
    if [ "$MODE" = publish-missing ]; then
      if [ "$tag" = "$VERSION" ]; then
        printf '%s\n' "${GHCR_TOKEN:?tag publication requires GITHUB_TOKEN}" |
          "$REGCTL" registry login ghcr.io --user "${GITHUB_REPOSITORY_OWNER:?repository owner is required}" --pass-stdin
        "$REGCTL" image import "$IMAGE:$VERSION" dist/tapebasis-image.tar
      else
        "$REGCTL" image copy "$IMAGE:$VERSION" "$IMAGE:$tag"
      fi
    elif [ "$attempt" -lt 5 ]; then
      sleep "${GHCR_RETRY_SECONDS:-10}"
    fi
  done
  if [ "$actual" != "$expected" ]; then
    printf 'GHCR %s is not readable as tested image %s\n' "$tag" "$expected" >&2
    exit 1
  fi
  printf 'Verified GHCR %s at tested image %s\n' "$tag" "$expected"
done
