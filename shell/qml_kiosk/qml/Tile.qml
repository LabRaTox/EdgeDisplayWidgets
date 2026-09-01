import QtQuick
import QtQuick.Shapes

/*
 * The frame every widget sits in, plus whatever the theme puts on top.
 *
 * The inset is adjustable because not every widget uses the same one. The
 * heartbeat strip is 32 pixels tall and has `padding: 6px 16px` of its own;
 * with the usual 12 there is no room left and the text sits off centre.
 *
 * The card background is a gradient in some themes and flat in others;
 * theme.py hands over the first stop either way, which at these opacities is
 * indistinguishable from the gradient.
 */
Item {
    id: tile
    property var theme
    property int padH: bridge.metrics.tile_pad_h
    property int padV: bridge.metrics.tile_pad_v
    /*
     * The inset the widget asked for, or -1 when it asked for nothing.
     *
     * A theme that asks for one normally wins, because a theme is meant to
     * be able to change the look of every tile. But `inner` clips, and clean
     * asks for 16 top and bottom while the heartbeat row is 32 pixels tall,
     * which leaves a box of zero height and cut the whole strip away. So the
     * theme wins only while the tile still has room for it.
     */
    property int widgetPadH: -1
    property int widgetPadV: -1
    readonly property bool themeWins: bridge.metrics.padding_from_theme
    readonly property int insetH: widgetPadH >= 0 && (!themeWins || 2 * padH >= width)
                                  ? widgetPadH : padH
    readonly property int insetV: widgetPadV >= 0 && (!themeWins || 2 * padV >= height)
                                  ? widgetPadV : padV
    default property alias content: inner.data

    readonly property var fx: bridge.effects
    readonly property real corner: bridge.metrics.tile_radius
    //: Two corners cut off instead of rounded, as toxic.css does with clip-path.
    readonly property real cut: fx.cut
    readonly property color cardColor: theme ? theme["card-bg"] : "#00000000"
    readonly property color borderColor: theme ? theme["card-border"] : "#00000000"
    //: The glow arrives as a string; as a colour its channels can be read.
    readonly property color glowColor: fx.glow_color !== "" ? fx.glow_color : "#00000000"

    /*
     * `box-shadow: 0 0 12px rgba(...)`, drawn as rings rather than with a
     * blur shader. A shader per tile would re-render on every value that
     * changes; these rings are geometry, they cost one draw call and never
     * repaint. Outlines, not filled shapes, because CSS clips an outer shadow
     * at the border box: with a translucent card a filled glow would shine
     * through the tile and lighten its inside.
     */
    Repeater {
        model: tile.fx.glow_color !== "" ? Math.max(3, Math.round(tile.fx.glow_blur / 2)) : 0

        Rectangle {
            required property int index
            readonly property int rings: Math.max(3, Math.round(tile.fx.glow_blur / 2))
            readonly property real step: tile.fx.glow_blur / rings
            readonly property real out: step * (index + 1)
            //: 1 at the tile, towards 0 at the outer edge of the blur.
            readonly property real falloff: 1 - index / rings

            x: -out + tile.fx.glow_dx
            y: -out + tile.fx.glow_dy
            width: tile.width + 2 * out
            height: tile.height + 2 * out
            radius: tile.corner + out
            color: "transparent"
            // Half a pixel of overlap, otherwise the rings show as stripes.
            border.width: step + 0.5
            border.color: Qt.rgba(tile.glowColor.r, tile.glowColor.g,
                                  tile.glowColor.b, tile.glowColor.a * falloff)
            antialiasing: true
        }
    }

    // The card itself, rounded in most themes.
    Rectangle {
        anchors.fill: parent
        visible: tile.cut <= 0
        color: tile.cardColor
        border.color: tile.borderColor
        border.width: 1
        radius: tile.corner
        antialiasing: true

        // `box-shadow: 0 0 0 1px rgba(...) inset`, a hairline inside the edge.
        Rectangle {
            anchors.fill: parent
            anchors.margins: tile.fx.inset_width / 2
            visible: tile.fx.inset_color !== ""
            color: "transparent"
            border.color: tile.fx.inset_color
            border.width: tile.fx.inset_width
            radius: Math.max(0, parent.radius - tile.fx.inset_width / 2)
            antialiasing: true
        }
    }

    // The same card with two corners cut off: toxic.css turns tiles into
    // frames that way, and a Rectangle has no way of doing it.
    Shape {
        anchors.fill: parent
        visible: tile.cut > 0
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: tile.cardColor
            strokeColor: tile.borderColor
            strokeWidth: 1
            startX: tile.cut; startY: 0.5
            PathLine { x: tile.width - 0.5; y: 0.5 }
            PathLine { x: tile.width - 0.5; y: tile.height - tile.cut }
            PathLine { x: tile.width - tile.cut; y: tile.height - 0.5 }
            PathLine { x: 0.5; y: tile.height - 0.5 }
            PathLine { x: 0.5; y: tile.cut }
            PathLine { x: tile.cut; y: 0.5 }
        }
    }

    /*
     * The diagonal band nightclub.css lays over every tile with a
     * pseudo-element. Its gradient runs at 135 degrees, which is from the top
     * left corner to the bottom right one.
     */
    Shape {
        anchors.fill: parent
        visible: tile.fx.sheen_color !== ""
        opacity: tile.fx.sheen_opacity

        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: tile.width; y2: tile.height
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.4; color: "transparent" }
                GradientStop { position: 0.5; color: tile.fx.sheen_color }
                GradientStop { position: 0.6; color: "transparent" }
                GradientStop { position: 1.0; color: "transparent" }
            }
            startX: 0; startY: 0
            PathLine { x: tile.width; y: 0 }
            PathLine { x: tile.width; y: tile.height }
            PathLine { x: 0; y: tile.height }
        }
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.leftMargin: tile.insetH
        anchors.rightMargin: tile.insetH
        anchors.topMargin: tile.insetV
        anchors.bottomMargin: tile.insetV
        clip: true
    }
}
