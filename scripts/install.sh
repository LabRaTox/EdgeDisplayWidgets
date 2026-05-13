#!/usr/bin/env bash
#
# Edge Dashboard installer.
#   - syncs Python dependencies via uv
#   - renders the systemd user unit and copies it into ~/.config/systemd/user
#   - reloads the systemd user daemon
#
# Re-running is safe and idempotent. Start the service with:
#   systemctl --user start edge-dashboard
# Or enable for auto-start at graphical-session login:
#   systemctl --user enable --now edge-dashboard

set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
TEMPLATE="${PROJECT_DIR}/systemd/edge-dashboard.service"
TARGET="${SYSTEMD_USER_DIR}/edge-dashboard.service"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

if ! command -v uv >/dev/null; then
    fail "'uv' not found. Install with: sudo pacman -S uv"
fi
UV_PATH=$(command -v uv)

if [ ! -f "$TEMPLATE" ]; then
    fail "missing template: $TEMPLATE"
fi

cd "$PROJECT_DIR"

log "syncing Python dependencies (uv sync)"
uv sync

log "rendering systemd unit at $TARGET"
mkdir -p "$SYSTEMD_USER_DIR"
sed \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__UV__|${UV_PATH}|g" \
    "$TEMPLATE" > "$TARGET"

log "reloading systemd user daemon"
systemctl --user daemon-reload

log "install complete."
cat <<EOF

Next steps:
  Run once now:        systemctl --user start  edge-dashboard
  Auto-start at login: systemctl --user enable --now edge-dashboard
  Tail logs:           journalctl --user -u edge-dashboard -f
  Open the kiosk:      $PROJECT_DIR/scripts/kiosk.sh

Service URL: http://127.0.0.1:8765
EOF
