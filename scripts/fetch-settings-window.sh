#!/usr/bin/env bash
#
# Downloads the settings window of a release, for machines without npm and
# cargo. The release builds it on an old Ubuntu, see
# .github/workflows/settings-window.yml.
#
#   scripts/fetch-settings-window.sh <version> <target file>
#
# Exits non-zero, with the target left alone, when there is nothing to fetch.
# The checksum comes from the same release, so it catches a broken download
# and not a compromised release.

set -euo pipefail

VERSION="$1"
TARGET="$2"
BASE="${EDGE_RELEASE_URL:-https://github.com/LabRaTox/EdgeDisplayWidgets/releases/download}"
ASSET="edgedash-${VERSION}-x86_64-linux.tar.gz"

[ "$(uname -m)" = "x86_64" ] || { echo "no build for $(uname -m)" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

curl -fsSL -o "${WORK}/${ASSET}" "${BASE}/v${VERSION}/${ASSET}"
curl -fsSL -o "${WORK}/${ASSET}.sha256" "${BASE}/v${VERSION}/${ASSET}.sha256"
(cd "$WORK" && sha256sum --quiet -c "${ASSET}.sha256")

tar -C "$WORK" -xzf "${WORK}/${ASSET}" edgedash
mkdir -p "$(dirname "$TARGET")"
install -m755 "${WORK}/edgedash" "$TARGET"
