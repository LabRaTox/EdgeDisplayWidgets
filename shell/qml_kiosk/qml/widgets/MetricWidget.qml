import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import ".."

/*
 * The shape cpu, gpu and ram share: a heading with a large figure beside it,
 * a line of detail underneath, then the chart filling the rest. The network
 * widget draws the same parts itself, because it shows two figures.
 */
Item {
    id: root
    property var theme
    property string heading: ""
    property string bigText: ""
    property string subText: ""
    property bool compact: false
    property alias chart: chartLoader.item
    property var series: []
    property real maxValue: 100
    property var tickFormat: function (v) { return Math.round(v) + "" }

    /*
     * How long the curve has to travel one sample width: the measured gap
     * between two payloads, not a fixed second. A module's interval is a
     * config value the widget knows nothing about and which changes while
     * running, so measuring is the only way the motion stays in step with
     * the data.
     */
    property int gapMs: 1000
    property double _lastArrival: 0
    function noteArrival() {
        var now = Date.now()
        if (_lastArrival > 0) {
            var observed = Math.max(200, Math.min(10000, now - _lastArrival))
            gapMs = Math.round(gapMs * 0.7 + observed * 0.3)
        }
        _lastArrival = now
    }
    default property alias extra: extraSlot.data

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        /*
         * Name and details in one column on the left, the figure beside it on
         * the right, both starting at the same top edge. Putting the details
         * below the whole row instead leaves a gap the height of the figure.
         */
        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: Style.subBottom
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: Style.metricHeadBottom

                Heading {
                    theme: root.theme
                    label: root.heading
                    Layout.fillWidth: true
                }

                Text {
                    text: root.subText
                    visible: text !== ""
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: Style.subSize
                    font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            Text {
                text: root.bigText
                color: root.theme ? root.theme["accent"] : "#00e0ff"
                font.pixelSize: bridge.metrics.metric_size
                font.weight: bridge.metrics.metric_weight
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
                font.letterSpacing: -0.56          // -0.01em at 2.8rem
                Layout.alignment: Qt.AlignTop
                // Trim the leading the font reserves above the digits, so the
                // top of the number lines up with the top of the heading.
                topPadding: -Math.round(bridge.metrics.metric_size * 0.18)

                // The glow a theme puts on the figure
                layer.enabled: bridge.effects.metric_glow_color !== ""
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: bridge.effects.metric_glow_color
                    shadowBlur: Math.min(1, bridge.effects.metric_glow_blur / 32)
                    shadowHorizontalOffset: 0
                    shadowVerticalOffset: 0
                    blurMax: 32
                }
            }
        }

        Loader {
            id: chartLoader
            active: !root.compact
            visible: active
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: active ? Style.chartMinHeight : 0
            sourceComponent: Chart {
                theme: root.theme
                series: root.series
                maxValue: root.maxValue
                tickFormat: root.tickFormat
                gapMs: root.gapMs
            }
        }

        Item {
            id: extraSlot
            Layout.fillWidth: true
            Layout.preferredHeight: childrenRect.height
            visible: !root.compact && children.length > 0
        }
    }
}
