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
# systemd looks for user units under $XDG_CONFIG_HOME, not always ~/.config.
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
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

#: The oldest PySide6 the kiosk is known to run on.
MIN_PYSIDE="6.10"
#: What PySide6 from PyPI needs from the system. The 64-bit time move renamed
#: two of these on Ubuntu 24.04 and Debian 13, and the old names cannot be
#: installed there.
T64=""
apt-cache show libasound2t64 >/dev/null 2>&1 && T64=t64
KIOSK_LIBS_DEBIAN="libegl1 libgl1 libgbm1 libglib2.0-0${T64} libfontconfig1 libdbus-1-3 libnss3 libasound2${T64} libpulse0 libxkbcommon0 libxkbcommon-x11-0 libxkbfile1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxtst6 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 libwayland-client0 libwayland-cursor0 libwayland-egl1"
KIOSK_LIBS_FEDORA="mesa-libEGL libglvnd-glx mesa-libgbm glib2 fontconfig dbus-libs nss alsa-lib pulseaudio-libs libxkbcommon libxkbcommon-x11 libxkbfile libXcomposite libXdamage libXrandr libXtst xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libwayland-client libwayland-cursor libwayland-egl"
#: Arch has a current PySide6, so there the system's is the one to install.
KIOSK_PACKAGES_ARCH="pyside6 python-yaml qt6-declarative qt6-websockets qt6-multimedia qt6-webengine"
#: The Python both virtualenvs run on.
PYTHON_VERSION="3.13"

#: Collected as we go and printed at the end, so a warning in step two is not
#: lost by the time step seven has scrolled past.
NOTES=()
note() { NOTES+=("$1"); warn "$1"; }

# Package name per distribution, for the hints. Arch is the target, the others
# are there so the message is useful rather than merely correct.
pkg_hint() {
    local arch="$1" debian="$2" fedora="$3"
    # Bazzite, Silverblue, Kinoite and Aurora have dnf too, but their /usr is
    # read-only: packages go into the image and need a reboot.
    if [ -e /run/ostree-booted ]; then echo "rpm-ostree install ${fedora} && systemctl reboot"
    elif command -v pacman >/dev/null; then echo "sudo pacman -S ${arch}"
    elif command -v apt >/dev/null; then echo "sudo apt install ${debian}"
    elif command -v dnf >/dev/null; then echo "sudo dnf install ${fedora}"
    # openSUSE names most libraries like Fedora does; close enough for a hint.
    elif command -v zypper >/dev/null; then echo "sudo zypper install ${fedora}"
    else echo "install: ${arch}"
    fi
}

# ---------------------------------------------------------------- checks

step "Checking what is here"

# Debian and Ubuntu do not package it.
command -v uv >/dev/null || fail "'uv' not found. $(pkg_hint uv 'curl -LsSf https://astral.sh/uv/install.sh | sh' uv | sed 's/^sudo apt install //')"
UV_PATH=$(command -v uv)
log "uv: ${UV_PATH}"

# Void, Alpine, Gentoo with OpenRC, Devuan: no systemd, so no user units to
# run the dashboard. Said now rather than after everything is installed.
command -v systemctl >/dev/null || fail "Edge Dash runs as systemd user services, and this system has no systemctl"
# NixOS has no /usr/bin/python3 and no FHS libraries for the PyPI Qt wheels.
[ -e /etc/NIXOS ] && fail "NixOS is not supported by this installer"

# A user instance has to exist, or none of the units can be enabled. This is a
# property of the session, not of the distribution.
if ! systemctl --user is-system-running >/dev/null 2>&1; then
    if systemctl --user is-system-running 2>&1 | grep -qi "bus"; then
        fail "no systemd user session reachable; run this from a normal desktop session"
    fi
fi
log "systemd user session: reachable"

# The tray icon needs a panel that implements StatusNotifierItem. Most do;
# GNOME needs an extension for it.
# busctl comes with systemd; qdbus6 is called qdbus-qt6 on Fedora and is
# often missing on Debian and Ubuntu.
if busctl --user list 2>/dev/null | grep -q StatusNotifierWatcher; then
    log "tray: a StatusNotifierItem host is running"
elif [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then
    note "GNOME without an AppIndicator extension shows no tray icon.
    Install 'AppIndicator and KStatusNotifierItem Support' to get one.
    Everything else works; the settings window also opens from the app menu."
fi

# ------------------------------------------------------- python dependencies

step "Python dependencies"
cd "$PROJECT_DIR"
# Named, because uv otherwise takes the newest Python, and a new one has no
# finished packages yet: on a system without a compiler that ends the install.
uv sync --no-dev --python "$PYTHON_VERSION"
log "virtualenv ready"

# ------------------------------------------------------------- the kiosk window

# The distribution's PySide6 comes first: it links the system Qt WebEngine,
# which plays H.264 and AAC. Without one that is recent enough, a virtualenv
# of its own takes PySide6 from PyPI. That build has no H.264, which YouTube
# does not need as long as a video exists in VP9, and it weighs about 700 MB.
step "Kiosk window"
KIOSK_VENV="${PROJECT_DIR}/.venv-kiosk"
KIOSK_PYTHON=/usr/bin/python3

system_pyside_fits() {
    /usr/bin/python3 - "$MIN_PYSIDE" 2>/dev/null <<'PY'
import sys
import yaml
import PySide6
import PySide6.QtQuick, PySide6.QtWebEngineWidgets, PySide6.QtWebSockets, PySide6.QtMultimedia

have = tuple(int(part) for part in PySide6.__version__.split(".")[:2])
sys.exit(have < tuple(int(part) for part in sys.argv[1].split(".")))
PY
}

if system_pyside_fits; then
    log "PySide6 of the system: fits"
    rm -rf "$KIOSK_VENV"
else
    log "no recent PySide6 on the system, installing one for the kiosk (about 700 MB)"
    KIOSK_PYTHON="${KIOSK_VENV}/bin/python"
    [ -x "$KIOSK_PYTHON" ] || uv venv --quiet --python "$PYTHON_VERSION" "$KIOSK_VENV"
    uv pip install --quiet --python "$KIOSK_PYTHON" "PySide6>=${MIN_PYSIDE}" pyyaml
    if PROBLEM=$(QT_QPA_PLATFORM=offscreen "$KIOSK_PYTHON" -c "import PySide6.QtQuick, PySide6.QtWebEngineWidgets" 2>&1); then
        log "PySide6 for the kiosk: ready"
    else
        note "PySide6 for the kiosk cannot load: ${PROBLEM##*$'\n'}
    $(pkg_hint "$KIOSK_PACKAGES_ARCH" "$KIOSK_LIBS_DEBIAN" "$KIOSK_LIBS_FEDORA")"
    fi
fi

# ------------------------------------------------------- the settings window

BINARY="${PROJECT_DIR}/gui/src-tauri/target/release/edgedash"

step "Settings window"
if [ "$DO_BUILD" = "0" ]; then
    log "skipped (--no-build)"
elif [ -x "$BINARY" ] && [ "$BINARY" -nt "${PROJECT_DIR}/gui/package.json" ]; then
    log "already built: ${BINARY}"
elif command -v npm >/dev/null && command -v cargo >/dev/null; then
    log "building, this takes a minute or two"
    if (
        cd "${PROJECT_DIR}/gui"
        [ -d node_modules ] || npm install
        # The bundle targets (.deb, AppImage) are not needed to run from a
        # checkout, and the AppImage step pulls tools off the network.
        npm run tauri build -- --no-bundle
    ); then
        log "built: ${BINARY}"
    else
        note "the settings window failed to build; the tray icon will have nothing to open"
    fi
elif VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' "${PROJECT_DIR}/pyproject.toml" | head -1) &&
     "${PROJECT_DIR}/scripts/fetch-settings-window.sh" "$VERSION" "$BINARY"; then
    log "downloaded: ${BINARY}"
else
    note "the settings window could not be downloaded, and building it takes npm and cargo.
    $(pkg_hint 'nodejs npm rust' 'nodejs npm cargo' 'nodejs npm rust')
    The dashboard itself works without it; only the settings UI is missing."
fi

# A downloaded binary brings its code and not its libraries.
if [ -x "$BINARY" ] && ldd "$BINARY" 2>/dev/null | grep -q "not found"; then
    note "the settings window is missing a library.
    $(pkg_hint webkit2gtk-4.1 libwebkit2gtk-4.1-0 webkit2gtk4.1)"
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
        -e "s|__KIOSK_PYTHON__|${KIOSK_PYTHON}|g" \
        "${PROJECT_DIR}/systemd/${unit}" > "${SYSTEMD_USER_DIR}/${unit}"
    log "unit installed: ${SYSTEMD_USER_DIR}/${unit}"
done
systemctl --user daemon-reload

# Sessions without graphical-session.target (XFCE, Cinnamon, MATE, LXQt...)
# never pull the enabled units in. A login entry starts them there; KDE and
# GNOME reach the target, so the entry stays out of their way. The settings
# window's autostart switch writes the same file (backend/autostart.py).
LOGIN_ENTRY="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/edge-dashboard-start.desktop"
write_login_entry() {
    mkdir -p "$(dirname "$LOGIN_ENTRY")"
    cat > "$LOGIN_ENTRY" <<ENTRY
[Desktop Entry]
Type=Application
Name=Edge Dashboard
Comment=Starts the Edge Dashboard services where the session does not
Exec=sh -c "systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE 2>/dev/null; exec systemctl --user start ${UNITS[*]}"
NotShowIn=KDE;GNOME;
NoDisplay=true
X-GNOME-Autostart-enabled=true
ENTRY
}

if [ "$DO_ENABLE" = "1" ]; then
    systemctl --user enable "${UNITS[@]}" >/dev/null 2>&1 && log "enabled for the next login"
    write_login_entry && log "login entry: ${LOGIN_ENTRY}"
    # Tiling compositors read neither the target nor XDG autostart entries
    # unless something like uwsm or dex is set up.
    if ! systemctl --user is-active --quiet graphical-session.target; then
        DESKTOP_NAME="${XDG_CURRENT_DESKTOP:-}"
        case "${DESKTOP_NAME,,}" in
            *hyprland*) note "Hyprland does not start user services by itself. Add to hyprland.conf:
    exec-once = systemctl --user import-environment DISPLAY WAYLAND_DISPLAY; systemctl --user start ${UNITS[*]}" ;;
            *sway*|*i3*) note "${DESKTOP_NAME} does not start user services by itself. Add to its config:
    exec sh -c 'systemctl --user import-environment DISPLAY WAYLAND_DISPLAY; systemctl --user start ${UNITS[*]}'" ;;
        esac
    fi
else
    log "autostart not enabled (--no-autostart)"
fi

if [ "$DO_START" = "1" ]; then
    # The units see only the user manager's environment. KDE and GNOME put
    # the display there; sway, Hyprland without uwsm and many X11 sessions do
    # not, and the kiosk would have no screen to open.
    SESSION_VARS=()
    for var in DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE; do
        [ -n "${!var:-}" ] && SESSION_VARS+=("$var")
    done
    [ ${#SESSION_VARS[@]} -gt 0 ] && systemctl --user import-environment "${SESSION_VARS[@]}"
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
