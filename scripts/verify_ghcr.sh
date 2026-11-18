#!/usr/bin/env bash
# Verify every GHCR release tag against the tested OCI root index digest.
# Missing tags have one write. An explicit reviewed predecessor digest can
# authorize only selected aliases to advance under publication. Exact-version
# tags and all other conflicts remain fatal. The bounded 1.1.2 and 1.1.3 options
# hard-code their release identities; they do not create a general future minor-alias policy.
# The full release identity is bound to the source artifacts by the protected
# publish job before this helper runs.
set -euo pipefail

VERSION="${1:?release version is required}"
MODE="${2:-verify}"
ADVANCE_FROM=""
ADVANCE_ALIASES=""
if [ "$#" -eq 4 ] && [ "$MODE" = publish-missing ]; then
    if [ "$3" = --advance-major-latest-from ] && [ "$VERSION" = 1.1.1 ]; then
        ADVANCE_FROM="$4"
        ADVANCE_ALIASES="${VERSION%%.*}:latest"
    elif [ "$3" = --advance-minor-major-latest-from ] && { [ "$VERSION" = 1.1.2 ] || [ "$VERSION" = 1.1.3 ]; }; then
        ADVANCE_FROM="$4"
        ADVANCE_ALIASES="${VERSION%.*}:${VERSION%%.*}:latest"
    else
        printf '%s\n' 'Unknown advance option, or this exception is not reviewed for the release' >&2
        exit 2
    fi
elif [ "$#" -ne 2 ]; then
    printf '%s\n' 'Usage: verify_ghcr.sh VERSION [verify | publish-missing [--advance-major-latest-from DIGEST | --advance-minor-major-latest-from DIGEST]]' >&2
    exit 2
fi
if [ -n "$ADVANCE_FROM" ] && [[ ! "$ADVANCE_FROM" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'The reviewed predecessor must be one SHA-256 digest\n' >&2
    exit 2
fi
IMAGE="ghcr.io/${GITHUB_REPOSITORY:?repository is required}"
VERSION_IMAGE="$IMAGE:$VERSION"
REGCTL="${REGCTL:-./regctl}"
[ "$MODE" = verify ] || [ "$MODE" = publish-missing ]
mkdir -p "${RUNNER_TEMP:-/tmp}"
export REGISTRY_CONFIG="${REGISTRY_CONFIG:-$(mktemp "${RUNNER_TEMP:-/tmp}/tapebasis-regctl.XXXXXX")}"
expected="$(python3 scripts/check_oci_image.py --digest dist/tapebasis-image.tar)"
test -n "$expected"
if [ "$MODE" = publish-missing ]; then
    # Authenticate once before any exact-tag import or existing-tag alias copy.
    printf '%s\n' "${GHCR_TOKEN:?tag publication requires GITHUB_TOKEN}" |
        "$REGCTL" registry login ghcr.io --user "${GITHUB_REPOSITORY_OWNER:?repository owner is required}" --pass-stdin
fi

# Classify manifest existence through HTTP status and Docker-Content-Digest.
# Status 0 is a match, 1 a conflict, 2 absence, and 3 a fatal lookup error.
read_manifest() {
    local tag="$1"
    python3 "${GHCR_LOOKUP:-scripts/ghcr_manifest.py}" \
        --repository "$GITHUB_REPOSITORY" --tag "$tag" --expected "$expected"
}

for tag in "$VERSION" "${VERSION%.*}" "${VERSION%%.*}" latest; do
    if read_manifest "$tag"; then
        printf 'Verified GHCR %s at tested image %s\n' "$tag" "$expected"
        continue
    else
        status=$?
    fi
    if [ "$status" -eq 1 ] && [ "$MODE" = publish-missing ] && [ -n "$ADVANCE_FROM" ]; then
        # The caller's reviewed policy selects each mutable alias explicitly.
        # A second lookup rejects every other predecessor or non-alias tag.
        case ":$ADVANCE_ALIASES:" in
            *":$tag:"*) ;;
            *) exit 1 ;;
        esac
        if python3 "${GHCR_LOOKUP:-scripts/ghcr_manifest.py}" \
            --repository "$GITHUB_REPOSITORY" --tag "$tag" --expected "$ADVANCE_FROM"; then
            status=2
        else
            exit 1
        fi
    fi
    [ "$status" -eq 2 ] || exit 1
    if [ "$MODE" = publish-missing ]; then
        # This branch runs once per absent or explicitly reviewed alias. All
        # later reads require the new tested digest and never write again.
        if [ "$tag" = "$VERSION" ]; then
            "$REGCTL" image import "$VERSION_IMAGE" dist/tapebasis-image.tar
        else
            "$REGCTL" image copy "$VERSION_IMAGE" "$IMAGE:$tag"
        fi
    fi

    verified=false
    for attempt in 1 2 3 4 5; do
        if read_manifest "$tag"; then
            verified=true
            break
        else
            status=$?
        fi
        [ "$status" -eq 2 ] || exit 1
        if [ "$attempt" -lt 5 ]; then
            sleep "${GHCR_RETRY_SECONDS:-10}"
        fi
    done
    if [ "$verified" != true ]; then
        printf 'GHCR %s remains absent after one missing-only write or %s lookups\n' "$tag" "$attempt" >&2
        exit 1
    fi
    printf 'Verified GHCR %s at tested image %s\n' "$tag" "$expected"
done
