#!/usr/bin/env bash
#
# Launch Chromium in kiosk mode on the Corsair Xeneon Edge display.
#
# Detection order:
#   1. $EDGE_OUTPUT (if set, take that output name verbatim)
#   2. Wayland: wlr-randr → first output with mode = ${EDGE_WIDTH}x${EDGE_HEIGHT}
#   3. X11:    xrandr     → first connected output with that geometry
#   4. Fallback: chromium --kiosk on the primary display
#
# Override env vars:
#   EDGE_URL=...      (default http://127.0.0.1:8765)
#   EDGE_OUTPUT=DP-3  (force a specific output)
#   EDGE_WIDTH=2560
#   EDGE_HEIGHT=720
#   EDGE_BROWSER=chromium

set -euo pipefail

URL="${EDGE_URL:-http://127.0.0.1:8765}"
OUTPUT="${EDGE_OUTPUT:-}"
RES_W="${EDGE_WIDTH:-2560}"
RES_H="${EDGE_HEIGHT:-720}"

log() { printf '\033[1;36mkiosk:\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mkiosk:\033[0m %s\n' "$*" >&2; }

# ----------------------------------------------------------- pick a browser
BROWSER="${EDGE_BROWSER:-}"
if [ -z "$BROWSER" ]; then
    for cmd in chromium chromium-browser google-chrome google-chrome-stable brave-browser; do
        if command -v "$cmd" >/dev/null 2>&1; then
            BROWSER="$cmd"
            break
        fi
    done
fi
if [ -z "$BROWSER" ]; then
    echo "no Chromium-compatible browser found (set EDGE_BROWSER=...)" >&2
    exit 1
fi

# ----------------------------------------------------------- detect output
session_type="${XDG_SESSION_TYPE:-}"
if [ -z "$session_type" ]; then
    [ -n "${WAYLAND_DISPLAY:-}" ] && session_type=wayland || session_type=x11
fi

pos_x=""
pos_y=""

detect_x11() {
    if ! command -v xrandr >/dev/null 2>&1; then
        return
    fi
    # xrandr output line looks like:
    #   DP-3 connected 2560x720+0+0 (normal left inverted right x axis y axis) ...
    while IFS= read -r line; do
        if [[ "$line" =~ ^([A-Za-z0-9-]+)\ connected.*\ (${RES_W})x(${RES_H})\+([0-9]+)\+([0-9]+) ]]; then
            local out="${BASH_REMATCH[1]}"
            if [ -z "$OUTPUT" ] || [ "$out" = "$OUTPUT" ]; then
                OUTPUT="$out"
                pos_x="${BASH_REMATCH[4]}"
                pos_y="${BASH_REMATCH[5]}"
                return
            fi
        fi
    done < <(xrandr --query)
}

detect_wayland() {
    if ! command -v wlr-randr >/dev/null 2>&1; then
        return
    fi
    # wlr-randr emits one section per output. Order within a section varies
    # between compositors — Position typically comes AFTER Modes — so we
    # collect per-section state and commit at the next section header / EOF.
    #
    # Example section:
    #   DP-3 "Corsair ..."
    #     Modes:
    #       2560x720 px, 240.000 Hz (current, preferred)
    #     Position: 0,0
    local wanted="$OUTPUT"
    local cur_out="" cur_pos="" cur_match=""
    local found_out="" found_pos=""

    commit_section() {
        [ -z "$cur_out" ] && return
        if [ -n "$cur_match" ] && { [ -z "$wanted" ] || [ "$cur_out" = "$wanted" ]; }; then
            # Prefer an exact EDGE_OUTPUT match; otherwise take the first hit.
            if [ -z "$found_out" ] || [ "$cur_out" = "$wanted" ]; then
                found_out="$cur_out"
                found_pos="$cur_pos"
            fi
        fi
        cur_out="" cur_pos="" cur_match=""
    }

    while IFS= read -r line; do
        if [[ "$line" =~ ^([A-Za-z0-9_-]+)[[:space:]] ]]; then
            commit_section
            cur_out="${BASH_REMATCH[1]}"
            continue
        fi
        if [[ "$line" =~ Position:[[:space:]]*([0-9]+),([0-9]+) ]]; then
            cur_pos="${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
        fi
        # Match e.g. "    2560x720 px, 240.000 Hz (current, preferred)".
        # Anchor on a leading space + the exact WxH to avoid matching the
        # "current" keyword from an unrelated mode line.
        if [[ "$line" =~ ^[[:space:]]+${RES_W}x${RES_H}[[:space:]].*current ]]; then
            cur_match=1
        fi
    done < <(wlr-randr 2>/dev/null || true)
    commit_section

    if [ -n "$found_out" ]; then
        OUTPUT="$found_out"
        if [ -n "$found_pos" ]; then
            pos_x="${found_pos% *}"
            pos_y="${found_pos##* }"
        fi
    fi
}

if [ "$session_type" = "wayland" ]; then
    detect_wayland
    if [ -z "$OUTPUT" ]; then
        # X11 fallback (XWayland still exposes via xrandr in many setups)
        detect_x11
    fi
else
    detect_x11
fi

# ----------------------------------------------------------- KWin window rule
#
# KWin (KDE Plasma 6, Wayland) ignores `--window-position` from XWayland
# clients and routes window placement through its own policy — which often
# lands the kiosk on the primary monitor on cold boot, before the target
# output is fully arranged.
#
# Workaround: write a per-session KWin window rule pinning the kiosk
# wmclass to the output we just detected. The rule is upserted (we never
# clobber other rules the user might have) and tagged with our rule id so
# subsequent launches simply update it in place.
maybe_install_kwin_rule() {
    # Only relevant under KDE Plasma; bail silently elsewhere.
    [ -n "${KDE_SESSION_VERSION:-}" ] || return 0
    command -v kwriteconfig6 >/dev/null 2>&1 || return 0
    command -v qdbus6 >/dev/null 2>&1 || return 0
    [ -n "$OUTPUT" ] || return 0
    [ -n "$pos_x" ] && [ -n "$pos_y" ] || return 0

    local rule_id="edge-dashboard-kiosk"
    local rules_file="${XDG_CONFIG_HOME:-$HOME/.config}/kwinrulesrc"
    # Chromium derives the X/Wayland resource class for `--app=URL` as
    # `chrome-<host>__<path>-Default`. Matching on the host-prefixed segment
    # tolerates port changes and trailing-path variations.
    local host
    host=$(printf '%s' "$URL" | sed -E 's|^https?://||; s|[:/].*$||')
    local wmclass_match="chrome-${host}"

    log "installing KWin rule '$rule_id' for output '$OUTPUT' (${RES_W}x${RES_H})"

    # Make sure our rule id is present in [General]/rules without dropping
    # any existing rules the user has set up.
    local existing="" present_count=0
    if [ -r "$rules_file" ]; then
        existing=$(kreadconfig6 --file "$rules_file" --group General --key rules 2>/dev/null || true)
    fi
    case ",${existing}," in
        *,${rule_id},*) :;;
        *)  if [ -z "$existing" ]; then
                kwriteconfig6 --file "$rules_file" --group General --key rules "$rule_id"
            else
                kwriteconfig6 --file "$rules_file" --group General --key rules "${existing},${rule_id}"
            fi;;
    esac
    # Refresh count: number of comma-separated entries in 'rules'.
    local current
    current=$(kreadconfig6 --file "$rules_file" --group General --key rules 2>/dev/null || echo "")
    if [ -n "$current" ]; then
        present_count=$(printf '%s' "$current" | tr ',' '\n' | grep -c .)
        kwriteconfig6 --file "$rules_file" --group General --key count "$present_count"
    fi

    # Rule body — `outputrule=4` / `positionrule=4` etc. mean "Force": KWin
    # overrides any geometry the client requests, so window placement is
    # deterministic regardless of when the kiosk window appears relative
    # to monitor configuration.
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key Description \
        "Edge Dashboard Kiosk (auto-generated by scripts/kiosk.sh)"
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key wmclass "$wmclass_match"
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key wmclassmatch 2
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key wmclasscomplete false
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key types 1
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key output "$OUTPUT"
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key outputrule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key position "${pos_x},${pos_y}"
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key positionrule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key size "${RES_W},${RES_H}"
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key sizerule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key fullscreen true
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key fullscreenrule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skiptaskbar true
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skiptaskbarrule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skippager true
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skippagerrule 4
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skipswitcher true
    kwriteconfig6 --file "$rules_file" --group "$rule_id" --key skipswitcherrule 4

    # Reload KWin so the rule takes effect for the kiosk we're about to spawn.
    qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
}

maybe_install_kwin_rule

# ----------------------------------------------------------- build flags
CHROME_FLAGS=(
    --noerrdialogs
    --disable-infobars
    --disable-translate
    --disable-features=TranslateUI
    --no-first-run
    --autoplay-policy=no-user-gesture-required
    --user-data-dir="${HOME}/.cache/edge-dashboard-chromium"
)

if [ -n "$pos_x" ] && [ -n "$pos_y" ]; then
    log "launching on output '$OUTPUT' at ${pos_x},${pos_y} (${RES_W}x${RES_H})"
    CHROME_FLAGS+=(
        --kiosk
        --window-position="${pos_x},${pos_y}"
        --window-size="${RES_W},${RES_H}"
    )
else
    warn "no ${RES_W}x${RES_H} output detected — falling back to --kiosk on primary display"
    warn "set EDGE_OUTPUT to force a specific output, or run: ${session_type} headless?"
    CHROME_FLAGS+=(--kiosk)
fi

CHROME_FLAGS+=(--app="$URL")

log "exec: $BROWSER ${CHROME_FLAGS[*]}"
exec "$BROWSER" "${CHROME_FLAGS[@]}"
