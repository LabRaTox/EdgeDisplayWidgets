import QtQuick
import QtQuick.Effects

/*
 * `.widget h3`: uppercase, wide letter spacing, muted.
 *
 * The upper-casing goes through a separate property on purpose. Assigning to
 * `text` in Component.onCompleted, which is the obvious way to imitate
 * text-transform, replaces the binding with a fixed value, and every later
 * update is then silently lost. That is how the GPU widget ended up showing
 * "GPU" forever instead of the card's name.
 */
Text {
    property var theme
    property string label: ""

    text: label.toUpperCase()
    /*
     * The heading colour comes from the theme's own `.widget h3` rule where
     * it has one: cyberpunk sets it to cyan, industrial to red. Only when a
     * theme stays silent does the muted foreground apply.
     */
    color: bridge.effects.heading_color !== "" ? bridge.effects.heading_color
                                               : (theme ? theme["fg-muted"] : "#888888")
    font.pixelSize: bridge.metrics.heading_size
    font.letterSpacing: bridge.metrics.heading_spacing
    font.weight: bridge.metrics.heading_weight
    font.family: theme ? theme["font-ui"] : "sans-serif"
    elide: Text.ElideRight

    // `text-shadow: 0 0 6px rgba(...)`. The layer grows itself to fit the
    // glow, so nothing of it is cut off at the edge of the text.
    layer.enabled: bridge.effects.heading_glow_color !== ""
    layer.effect: MultiEffect {
        shadowEnabled: true
        shadowColor: bridge.effects.heading_glow_color
        shadowBlur: Math.min(1, bridge.effects.heading_glow_blur / 32)
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 0
        blurMax: 32
    }
}
