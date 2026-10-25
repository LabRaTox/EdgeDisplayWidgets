import QtQuick
import QtQuick.Layouts
import EdgeDash

Item {
    id: root
    property var theme
    readonly property var moduleNames: ["moon-phase"]
    property var options: ({})
    property bool compact: false

    property var payload: null

    function receive(module, data) {
        payload = data
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.moon-phase.title")
            Layout.bottomMargin: Style.headingBottom
        }

        Text {
            text: root.payload ? Math.round(root.payload.fraction * 100) + "%" : "–"
            color: root.theme ? root.theme["accent"] : "#00e0ff"
            font.pixelSize: bridge.metrics.metric_size
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }

        Text {
            visible: !root.compact && (root.options && root.options.show_days !== false)
            text: root.payload ? root.payload.days.toFixed(1) + " d" : "–"
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: Style.subSize
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }
    }
}
