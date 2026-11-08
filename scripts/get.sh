#!/usr/bin/env bash
#
# Installs or updates Edge Dash from the newest release, for systems without
# the Arch package:
#
#   curl -fsSL https://raw.githubusercontent.com/LabRaTox/EdgeDisplayWidgets/main/scripts/get.sh | bash
#
# Fetches uv if it is missing, unpacks the release and hands over to
# scripts/install.sh, which does the rest. Run it again to update: settings
# and virtualenvs stay, the code is replaced.
#
#   EDGE_INSTALL_DIR   where it goes, ~/.local/share/edge-dashboard/app if unset
#   EDGE_VERSION       a release such as 1.7.0, the newest if unset
#
# Everything sits in main, so a download cut off halfway runs nothing.

set -euo pipefail

REPOSITORY="https://github.com/LabRaTox/EdgeDisplayWidgets"
#: What a release replaces. Everything else in the folder is ours to keep:
#: config.local.yaml and the virtualenvs.
CODE_DIRS=(backend docs examples frontend gui packaging scripts shell systemd widgets)

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

main() {
    local target="${EDGE_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/edge-dashboard/app}"
    local version="${EDGE_VERSION:-}"

    [ "$(uname -m)" = "x86_64" ] || fail "only x86_64 has releases, this is $(uname -m)"
    command -v curl >/dev/null || fail "curl is needed"
    command -v tar >/dev/null || fail "tar is needed"

    if ! command -v uv >/dev/null; then
        log "installing uv"
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
        # Where the uv installer puts it when XDG_BIN_HOME or UV_INSTALL_DIR is set.
        export PATH="${UV_INSTALL_DIR:-${XDG_BIN_HOME:-${HOME}/.local/bin}}:${PATH}"
        command -v uv >/dev/null || fail "uv could not be installed"
    fi

    if [ -z "$version" ]; then
        # The redirect to the newest tag, which unlike the API has no rate limit.
        local latest
        latest=$(curl -fsSLo /dev/null -w '%{url_effective}' "${REPOSITORY}/releases/latest")
        version="${latest##*/v}"
    fi
    case "$version" in
        [0-9]*.[0-9]*) ;;
        *) fail "no release found (got '${version}')" ;;
    esac
    log "Edge Dash ${version} into ${target}"

    # Not local: the trap runs once main has long returned.
    WORK=$(mktemp -d)
    trap 'rm -rf "${WORK:-}"' EXIT
    curl -fsSL -o "${WORK}/source.tar.gz" "${REPOSITORY}/archive/refs/tags/v${version}.tar.gz"
    tar -C "$WORK" -xzf "${WORK}/source.tar.gz" --strip-components=1
    [ -f "${WORK}/scripts/install.sh" ] || fail "the release has no scripts/install.sh"
    rm -f "${WORK}/source.tar.gz"

    mkdir -p "$target"
    local dir
    for dir in "${CODE_DIRS[@]}"; do
        rm -rf "${target:?}/${dir}"
    done
    cp -a "${WORK}/." "$target/"

    cd "$target"
    # Under `curl | bash` stdin is that pipe, not a terminal.
    ./scripts/install.sh "$@" </dev/null
}

main "$@"
