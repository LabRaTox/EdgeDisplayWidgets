pragma Singleton
import QtQuick

/*
 * What the shared building blocks read from the active theme, in one place.
 * A plugin can use it too: `Ui.accent` instead of a colour of its own, which
 * is what makes a tile change with the theme. Everything follows a theme
 * switch by itself.
 *
 * Corners come from the theme's tiles. Round shapes such as chips stay round
 * only where the theme is round: toxic has no rounded corners at all, and a
 * pill would stand out there.
 */
QtObject {
    readonly property var theme: bridge.theme

    function color(key, fallback) { return theme && theme[key] ? theme[key] : fallback }

    readonly property color bg: color("bg", "#0a0a0a")
    readonly property color fg: color("fg", "#e0e0e0")
    readonly property color muted: color("fg-muted", "#888888")
    readonly property color accent: color("accent", "#00e0ff")
    readonly property color accent2: color("accent-2", accent)
    readonly property color ok: color("ok", "#4ade80")
    readonly property color warn: color("warn", "#facc15")
    readonly property color bad: color("bad", "#f87171")
    readonly property color surface: color("card-bg", "#0affffff")
    readonly property color border: color("card-border", "#0fffffff")
    // Text on a filled accent: the page colour, so it stays readable in
    // dark and light themes alike.
    readonly property color onAccent: bg
    // The tint of something being pressed, or of a track.
    readonly property color pressed: Qt.alpha(fg, 0.12)
    readonly property color track: Qt.alpha(fg, 0.14)

    readonly property string font: color("font-ui", "sans-serif")
    readonly property real corner: bridge.metrics.tile_radius

    /** The corner for something of this height that would like to be round. */
    function pill(height) { return corner >= 6 ? height / 2 : corner }

    /** The smallest thing a finger should have to hit. */
    readonly property int touch: 44
}
