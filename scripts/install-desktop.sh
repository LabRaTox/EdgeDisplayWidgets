#!/usr/bin/env bash
#
# Give the settings window an icon and a menu entry, and the kiosk window an
# identity.
#
# Why this is needed when running from a checkout: a Wayland task manager
# identifies a window by its app id — `edgedash` here — and looks for a
# matching .desktop file to get the name and the icon from. Installed from the
# .deb both come along; run out of the repository, neither exists, and the
# window shows up in the task list as a question mark.
#
# Installs into ~/.local/share, so nothing here needs root and nothing
# collides with a packaged copy in /usr/share.
#
# Idempotent: every run overwrites what it wrote last time.

set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_SRC="${PROJECT_DIR}/gui/src-tauri/icons"

# The app id Tauri gives the window, and therefore the base name of both the
# icon and the .desktop file. It comes from `mainBinaryName` in
# gui/src-tauri/tauri.conf.json — change one, change the other.
APP_ID="edgedash"

BINARY="${PROJECT_DIR}/gui/src-tauri/target/release/${APP_ID}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }

# theme directory : source file. The sources are rendered from
# backend/brand.py by scripts/make-icon.py, which is also what the tray draws.
ICONS=(
    "32x32:32x32.png"
    "64x64:64x64.png"
    "128x128:128x128.png"
    "256x256:128x128@2x.png"
    "512x512:icon.png"
)

for entry in "${ICONS[@]}"; do
    size="${entry%%:*}"
    file="${entry#*:}"
    source="${ICON_SRC}/${file}"
    if [ ! -f "$source" ]; then
        warn "icon missing: ${source} (run: uv run python scripts/make-icon.py)"
        continue
    fi
    target_dir="${DATA_DIR}/icons/hicolor/${size}/apps"
    mkdir -p "$target_dir"
    cp "$source" "${target_dir}/${APP_ID}.png"
done
log "icons installed under ${DATA_DIR}/icons/hicolor"

# The entry itself. Two things about it are load-bearing:
#
#   StartupWMClass  ties the running window to this file. A task manager
#                   matches the window's app id against it, not against the
#                   file name, and without it the window has no icon.
#   Categories      exactly one main category. Two (Utility;Settings;) put the
#                   application into the menu twice on some desktops.
mkdir -p "${DATA_DIR}/applications"
DESKTOP="${DATA_DIR}/applications/${APP_ID}.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=EDGE//DASH
GenericName=Edge Dashboard Settings
Comment=Einstellungen für das Edge Dashboard
Comment[en]=Settings for the Edge Dashboard
Keywords=edge;dashboard;xeneon;kiosk;
Keywords[de]=edge;dashboard;xeneon;kiosk;einstellungen;
Exec=${BINARY}
Icon=${APP_ID}
StartupWMClass=${APP_ID}
StartupNotify=true
Categories=Settings;
Terminal=false
EOF
log "menu entry written: ${DESKTOP}"

# The kiosk window carries its own app id, `edge-dashboard`, set with
# setDesktopFileName() in shell/qml_kiosk/main.py. Without a file of that name
# the desktop portal refuses to register the window ("App info not found") and
# the window has no icon of its own. NoDisplay keeps it out of the menu: it is
# a service that systemd starts, not something anyone launches by hand.
KIOSK_ID="edge-dashboard"
KIOSK_DESKTOP="${DATA_DIR}/applications/${KIOSK_ID}.desktop"
cat > "$KIOSK_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Edge Dashboard
GenericName=Kiosk window
Comment=Das Kioskfenster auf dem Xeneon Edge
Comment[en]=The kiosk window on the Xeneon Edge
Exec=/usr/bin/python3 -m qml_kiosk.main
Path=${PROJECT_DIR}
Icon=${APP_ID}
StartupWMClass=${KIOSK_ID}
NoDisplay=true
Terminal=false
EOF
log "kiosk window identity written: ${KIOSK_DESKTOP}"

if [ ! -x "$BINARY" ]; then
    warn "the settings window is not built yet — the entry points at:"
    warn "  ${BINARY}"
    warn "build it with: cd gui && npm run tauri build"
fi

# Caches. The first two are a speed-up that a desktop keeping none rebuilds on
# its own, but the third is not optional on KDE: Plasma reads its menu from
# ksycoca, and until that is rebuilt the entry exists on disk without showing
# up in the launcher or in KRunner.
command -v gtk-update-icon-cache >/dev/null &&
    gtk-update-icon-cache -q -t -f "${DATA_DIR}/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null &&
    update-desktop-database -q "${DATA_DIR}/applications" 2>/dev/null || true
if command -v kbuildsycoca6 >/dev/null; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 && log "KDE menu cache rebuilt"
fi

log "done. A running settings window has to be restarted to pick up a new icon."
