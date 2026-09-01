pragma Singleton
import QtQuick

/*
 * The sizes that are the same in every theme.
 *
 * The `rem` values in the comments are the ones the design was drawn in,
 * against a 20 pixel root, so 0.95rem is 19 pixels. They are kept as literals
 * rather than as a formula, because a wrong conversion would be invisible in
 * the code and obvious on the display.
 *
 * Anything a theme may change lives in `bridge.metrics` instead, and the
 * colours in `bridge.theme`, both filled by theme.py at runtime.
 */
QtObject {
    // The heading row of a metric widget
    readonly property int metricHeadBottom: 4

    // Under the tile heading
    readonly property int headingBottom: 8

    // The detail line under the large figure
    readonly property int subSize: 19              // 0.95rem
    readonly property int subBottom: 8

    // The chart and its axis
    readonly property int axisSize: 14             // 0.7rem
    readonly property int axisWidth: 35            // 2.5em at 0.7rem
    readonly property int axisGap: 8
    readonly property int chartMinHeight: 60
    readonly property int chartTicks: 5

    // The CPU core bars
    readonly property int coreHeight: 44
    readonly property int coreGap: 3
    readonly property int coreRadius: 2
    readonly property int coreTop: 10

    // Page grid. Only the fallback: `--gap` is a theme variable, and the
    // window reads it from the theme (clean asks for 12).
    readonly property int pageGap: 8
}
