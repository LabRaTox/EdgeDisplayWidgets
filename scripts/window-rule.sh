#!/usr/bin/env bash
#
# Keep the kiosk window out of the task manager, the pager and Alt+Tab.
#
# Why this needs a script at all: under Wayland an application cannot ask for
# it. xdg-shell has no window types, so Qt's `Qt::Tool` — which the kiosk does
# set, and which is enough on X11, where it becomes
# _NET_WM_WINDOW_TYPE_UTILITY — reaches a Wayland compositor as an ordinary
# toplevel. Only the compositor can mark the window, and every compositor has
# its own way of being told.
#
# Handled here:
#   KDE Plasma (KWin)   a window rule in kwinrulesrc
#   Hyprland            a windowrule snippet, sourced from hyprland.conf
#   Sway / i3           a for_window line in a config.d snippet
#   any X11 session     nothing to do, the window already asks for itself
#   everything else     a warning, the window will show up in the task list
#
# Idempotent: the rule has a fixed id and is rewritten on every run. Other
# rules are left alone.
#
# Takes effect for windows opened afterwards:
#   systemctl --user restart edge-kiosk

set -euo pipefail

RULE_ID="edge-dashboard-kiosk"
# Matches the Wayland app id, which Qt takes from `setDesktopFileName()` in
# shell/qml_kiosk/main.py. Change one, change the other.
APP_ID="edge-dashboard"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }

# EDGE_KIOSK_NO_FOCUS=1 additionally makes the window refuse the keyboard
# focus, so a tap on the dashboard does not pull the keyboard away from the
# main monitor. Off by default, and that is a deliberate trade: Wayland offers
# no way to take pointer input while refusing the keyboard, so refusing it
# turns every text field on the kiosk into a read-only one.
NO_FOCUS="${EDGE_KIOSK_NO_FOCUS:-0}"

# --------------------------------------------------------------- KDE Plasma

apply_kwin() {
    # Plasma 5 (Kubuntu 22.04 and 24.04, Debian 12) has only the 5 tools; the
    # keys in kwinrulesrc are the same.
    local kwrite kread
    kwrite=$(command -v kwriteconfig6 || command -v kwriteconfig5 || true)
    kread=$(command -v kreadconfig6 || command -v kreadconfig5 || true)
    if [ -z "$kwrite" ] || [ -z "$kread" ]; then
        warn "KDE session, but kwriteconfig/kreadconfig are missing, skipping the window rule."
        return 1
    fi
    local file="kwinrulesrc"

    # Clear out what the deprecated Chromium kiosk wrote under this same id:
    # its rule also pinned output, position, size and fullscreen. Those keys
    # have to go explicitly — `--delete-group` leaves them in the file — and
    # left behind they would apply to the Qt window, which places itself.
    local key
    for key in fullscreen fullscreenrule output outputrule position positionrule \
               size sizerule types; do
        "$kwrite" --file "$file" --group "$RULE_ID" --key "$key" --delete 2>/dev/null || true
    done

    "$kwrite" --file "$file" --group "$RULE_ID" --key Description \
        "Edge Dashboard kiosk (managed by scripts/window-rule.sh)"
    "$kwrite" --file "$file" --group "$RULE_ID" --key wmclass "$APP_ID"
    "$kwrite" --file "$file" --group "$RULE_ID" --key wmclasscomplete --type bool false
    # 1 = exact match on the class.
    "$kwrite" --file "$file" --group "$RULE_ID" --key wmclassmatch 1
    # Rule type 2 = Force: the window cannot turn these back on, and unlike
    # "Apply initially" (4) the setting survives the compositor reconsidering.
    for key in skiptaskbar skipswitcher skippager; do
        "$kwrite" --file "$file" --group "$RULE_ID" --key "$key" --type bool true
        "$kwrite" --file "$file" --group "$RULE_ID" --key "${key}rule" 2
    done

    if [ "$NO_FOCUS" = "1" ]; then
        "$kwrite" --file "$file" --group "$RULE_ID" --key acceptfocus --type bool false
        "$kwrite" --file "$file" --group "$RULE_ID" --key acceptfocusrule 2
        log "kiosk refuses the keyboard focus; text input on it will not work"
    else
        "$kwrite" --file "$file" --group "$RULE_ID" --key acceptfocus --delete 2>/dev/null || true
        "$kwrite" --file "$file" --group "$RULE_ID" --key acceptfocusrule --delete 2>/dev/null || true
    fi

    # Register the rule in the index, keeping any other rule already there.
    local current rules="" part count
    current=$("$kread" --file "$file" --group General --key rules 2>/dev/null || true)
    IFS=',' read -ra parts <<< "$current"
    for part in "${parts[@]}"; do
        [ -n "$part" ] && [ "$part" != "$RULE_ID" ] && rules="${rules:+$rules,}$part"
    done
    rules="${rules:+$rules,}$RULE_ID"
    count=$(awk -F',' '{print NF}' <<< "$rules")
    "$kwrite" --file "$file" --group General --key rules "$rules"
    "$kwrite" --file "$file" --group General --key count "$count"

    log "KWin rule written for app id '${APP_ID}' (${count} rule(s) total)"
    # busctl comes with systemd; qdbus6 is qdbus-qt6 on Fedora and often
    # missing on Debian and Ubuntu.
    if busctl --user call org.kde.KWin /KWin org.kde.KWin reconfigure >/dev/null 2>&1; then
        log "KWin reloaded"
    else
        warn "KWin did not reload, log out and back in"
    fi
}

# ----------------------------------------------------------------- Hyprland

apply_hyprland() {
    local dir="${CONFIG_HOME}/hypr"
    local snippet="${dir}/edge-dashboard.conf"
    [ -d "$dir" ] || mkdir -p "$dir"

    # Hyprland 0.53 replaced `windowrulev2 = effect, class:...` with
    # `windowrule = effect on, match:class ...` and refuses the old form.
    # Older releases do not know the new one, so the version decides.
    local version modern=1
    version=$(hyprctl version 2>/dev/null | sed -n 's/.*[Tt]ag: v\{0,1\}\([0-9]\{1,\}\.[0-9]\{1,\}\).*/\1/p' | head -1)
    if [ -n "$version" ]; then
        local major=${version%%.*} minor=${version#*.}
        if [ "$major" -eq 0 ] && [ "$minor" -lt 53 ]; then modern=0; fi
    fi

    rule() {
        if [ "$modern" = "1" ]; then
            echo "windowrule = $1 on, match:class ^(${APP_ID})\$"
        else
            echo "windowrulev2 = ${1//_/}, class:^(${APP_ID})\$"
        fi
    }

    {
        echo "# Written by scripts/window-rule.sh. Source it from hyprland.conf:"
        echo "#     source = ~/.config/hypr/edge-dashboard.conf"
        # Without no_focus the window behaves normally and only stays from
        # taking the focus when it appears.
        [ "$NO_FOCUS" = "1" ] && rule no_focus
        rule no_initial_focus
    } > "$snippet"
    log "Hyprland snippet written: ${snippet}"

    if grep -qs "edge-dashboard.conf" "${dir}/hyprland.conf"; then
        command -v hyprctl >/dev/null && hyprctl reload >/dev/null 2>&1 &&
            log "Hyprland reloaded"
    else
        warn "add this line to ${dir}/hyprland.conf, it is not sourced yet:"
        warn "    source = ${snippet}"
    fi
}

# --------------------------------------------------------------- Sway / i3

apply_sway() {
    local dir="${CONFIG_HOME}/sway/config.d"
    [ -d "${CONFIG_HOME}/sway" ] || { warn "no sway config directory found"; return 1; }
    mkdir -p "$dir"
    local snippet="${dir}/50-edge-dashboard.conf"
    echo "# Written by scripts/window-rule.sh" > "$snippet"
    # Sway has no skip-taskbar as such; bars read the window list from the
    # tree, and a scratchpad window is not in it. Keeping it simple: mark the
    # window so a bar's config can filter it, and note that in the log.
    echo "for_window [app_id=\"${APP_ID}\"] mark edge-dashboard" >> "$snippet"
    log "Sway snippet written: ${snippet}"
    warn "sway has no skip-taskbar flag; filter the mark 'edge-dashboard' in your bar if it lists windows"
    command -v swaymsg >/dev/null && swaymsg reload >/dev/null 2>&1 && log "sway reloaded"
}

# ------------------------------------------------------------------ dispatch

desktop="${XDG_CURRENT_DESKTOP:-}"
session="${XDG_SESSION_TYPE:-}"

if [ "$session" = "x11" ]; then
    # `Qt.Tool` on the kiosk window already sets _NET_WM_WINDOW_TYPE_UTILITY,
    # which is what a window manager reads to keep a window out of its lists.
    log "X11 session: the window asks for this itself, nothing to configure"
    exit 0
fi

case "${desktop,,}" in
    *kde*|*plasma*)  apply_kwin ;;
    *hyprland*)      apply_hyprland ;;
    *sway*|*i3*)     apply_sway ;;
    "")
        warn "no XDG_CURRENT_DESKTOP set, cannot tell which compositor this is."
        warn "The kiosk window may appear in the task list."
        ;;
    *)
        warn "no window rule known for '${desktop}' under Wayland."
        warn "The kiosk window may appear in the task list; on X11 it would not."
        ;;
esac

log "restart the kiosk for the rule to apply: systemctl --user restart edge-kiosk"
