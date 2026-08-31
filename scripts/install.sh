#!/usr/bin/env bash
#
# Edge Dashboard installer. One run should leave a working installation with
# nothing left to do by hand:
#
#   - checks what is needed and says what is missing
#   - syncs the Python dependencies (uv)
#   - builds the settings window, if the toolchain is there
#   - installs its icon and menu entry
#   - tells the compositor to keep the kiosk out of the task list
#   - renders and installs the systemd user units
#   - enables and starts both services
#
# Re-running is safe and idempotent.
#
# Options:
#   --no-build      skip building the settings window
#   --no-start      install everything, but do not enable or start the services
#   --no-autostart  start now, but do not enable them for the next login

set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
UNITS=(edge-dashboard.service edge-kiosk.service)

DO_BUILD=1
DO_START=1
DO_ENABLE=1
for arg in "$@"; do
    case "$arg" in
        --no-build) DO_BUILD=0 ;;
        --no-start) DO_START=0 ;;
        --no-autostart) DO_ENABLE=0 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

#: Collected as we go and printed at the end, so a warning in step two is not
#: lost by the time step seven has scrolled past.
NOTES=()
note() { NOTES+=("$1"); warn "$1"; }

# Package name per distribution, for the hints. Arch is the target, the others
# are there so the message is useful rather than merely correct.
pkg_hint() {
    local arch="$1" debian="$2" fedora="$3"
    if command -v pacman >/dev/null; then echo "sudo pacman -S ${arch}"
    elif command -v apt >/dev/null; then echo "sudo apt install ${debian}"
    elif command -v dnf >/dev/null; then echo "sudo dnf install ${fedora}"
    else echo "install: ${arch}"
    fi
}

# ---------------------------------------------------------------- checks

step "Checking what is here"

command -v uv >/dev/null || fail "'uv' not found. $(pkg_hint uv uv uv)"
UV_PATH=$(command -v uv)
log "uv: ${UV_PATH}"

# A user instance has to exist, or none of the units can be enabled. This is a
# property of the session, not of the distribution.
if ! systemctl --user is-system-running >/dev/null 2>&1; then
    if systemctl --user is-system-running 2>&1 | grep -qi "bus"; then
        fail "no systemd user session reachable; run this from a normal desktop session"
    fi
fi
log "systemd user session: reachable"

# The kiosk window runs on the *system* Python: it needs the distribution's
# PySide6, which links the system Qt WebEngine, and that is the build carrying
# the codecs the YouTube widget plays. The PyPI wheel does not.
if /usr/bin/python3 -c "import PySide6.QtWebEngineWidgets" >/dev/null 2>&1; then
    log "PySide6 (system Python): present"
else
    note "PySide6 is missing for /usr/bin/python3, the kiosk window will not start.
    $(pkg_hint pyside6 python3-pyside6.qtwebenginewidgets python3-pyside6)"
fi

# The tray icon needs a panel that implements StatusNotifierItem. Most do;
# GNOME needs an extension for it.
if command -v qdbus6 >/dev/null && qdbus6 2>/dev/null | grep -q StatusNotifierWatcher; then
    log "tray: a StatusNotifierItem host is running"
elif [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then
    note "GNOME without an AppIndicator extension shows no tray icon.
    Install 'AppIndicator and KStatusNotifierItem Support' to get one.
    Everything else works; the settings window also opens from the app menu."
fi

# ------------------------------------------------------- python dependencies

step "Python dependencies"
cd "$PROJECT_DIR"
uv sync
log "virtualenv ready"

# ------------------------------------------------------- the settings window

BINARY="${PROJECT_DIR}/gui/src-tauri/target/release/edgedash"

step "Settings window"
if [ "$DO_BUILD" = "0" ]; then
    log "skipped (--no-build)"
elif [ -x "$BINARY" ] && [ "$BINARY" -nt "${PROJECT_DIR}/gui/package.json" ]; then
    log "already built: ${BINARY}"
elif command -v npm >/dev/null && command -v cargo >/dev/null; then
    log "building, this takes a minute or two"
    (
        cd "${PROJECT_DIR}/gui"
        [ -d node_modules ] || npm install
        # The bundle targets (.deb, AppImage) are not needed to run from a
        # checkout, and the AppImage step pulls tools off the network.
        npm run tauri build -- --no-bundle
    ) && log "built: ${BINARY}" || note "the settings window failed to build; the tray icon will have nothing to open"
else
    note "npm and cargo are needed to build the settings window.
    $(pkg_hint 'nodejs npm rust' 'nodejs npm cargo' 'nodejs npm rust')
    The dashboard itself works without it; only the settings UI is missing."
fi

# ------------------------------------------------------ desktop integration

step "Desktop integration"
"${PROJECT_DIR}/scripts/install-desktop.sh" || note "icon and menu entry could not be installed"

step "Window rule"
"${PROJECT_DIR}/scripts/window-rule.sh" || note "the kiosk window may show up in the task list"

# Migration from the deprecated Chromium kiosk: an autostart entry pointing at
# the old launcher starts a second kiosk on the same output.
LEGACY_AUTOSTART="${HOME}/.config/autostart/edge-dashboard-kiosk.desktop"
if [ -f "$LEGACY_AUTOSTART" ]; then
    note "a leftover autostart entry starts the old Chromium kiosk alongside this one:
    ${LEGACY_AUTOSTART}
    Remove it: rm '${LEGACY_AUTOSTART}'"
fi

# ------------------------------------------------------------------ services

step "Services"
mkdir -p "$SYSTEMD_USER_DIR"
for unit in "${UNITS[@]}"; do
    [ -f "${PROJECT_DIR}/systemd/${unit}" ] || fail "missing template: systemd/${unit}"
    sed -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" -e "s|__UV__|${UV_PATH}|g" \
        "${PROJECT_DIR}/systemd/${unit}" > "${SYSTEMD_USER_DIR}/${unit}"
    log "unit installed: ${SYSTEMD_USER_DIR}/${unit}"
done
systemctl --user daemon-reload

if [ "$DO_ENABLE" = "1" ]; then
    systemctl --user enable "${UNITS[@]}" >/dev/null 2>&1 && log "enabled for the next login"
else
    log "autostart not enabled (--no-autostart)"
fi

if [ "$DO_START" = "1" ]; then
    systemctl --user restart "${UNITS[@]}"
    sleep 2
    for unit in "${UNITS[@]}"; do
        if systemctl --user is-active --quiet "$unit"; then
            log "${unit}: running"
        else
            note "${unit} did not start. See: journalctl --user -u ${unit} -n 30"
        fi
    done
else
    log "not started (--no-start)"
fi

# -------------------------------------------------------------------- result

PORT=$(sed -n 's/^ *port: *\([0-9]\+\).*/\1/p' "${PROJECT_DIR}/config.yaml" | head -1)
printf '\n\033[1;32m==>\033[0m \033[1mInstallation complete.\033[0m\n\n'
printf '  Dashboard      http://127.0.0.1:%s\n' "${PORT:-8765}"
printf '  Settings       tray icon, or the "EDGE//DASH" entry in the application menu\n'
printf '  Logs           journalctl --user -u edge-dashboard -u edge-kiosk -f\n'
printf '  Stop           systemctl --user stop edge-dashboard edge-kiosk\n'

if [ ${#NOTES[@]} -gt 0 ]; then
    printf '\n\033[1;33m%s point(s) worth reading above:\033[0m\n' "${#NOTES[@]}"
    for n in "${NOTES[@]}"; do printf '  - %s\n' "${n%%$'\n'*}"; done
fi
printf '\n'
