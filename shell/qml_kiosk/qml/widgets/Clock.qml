import QtQuick
import QtQuick.Layouts
import ".."

/* Clock: no backend module, ticks by itself. */
Item {
    id: root
    property var theme
    /** No backend module; declared so every widget answers the same question. */
    readonly property var moduleNames: []
    property var options: ({})
    readonly property bool showSeconds: options && options.show_seconds === true
    property string timeText: ""
    property string dateText: ""

    function refresh() {
        var now = new Date()
        var pad = function (n) { return (n < 10 ? "0" : "") + n }
        timeText = pad(now.getHours()) + ":" + pad(now.getMinutes())
                 + (showSeconds ? ":" + pad(now.getSeconds()) : "")
        dateText = now.toLocaleDateString(Qt.locale(), "dddd, d. MMMM")
    }

    Component.onCompleted: refresh()
    Timer {
        interval: root.showSeconds ? 250 : 1000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 6
        Text {
            text: root.timeText
            color: root.theme ? root.theme["fg"] : "#e0e0e0"
            font.pixelSize: 96
            font.weight: bridge.metrics.clock_weight
            font.family: root.theme ? root.theme["font-display"] : "sans-serif"
            Layout.alignment: Qt.AlignHCenter
        }
        Text {
            text: root.dateText
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 22
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            Layout.alignment: Qt.AlignHCenter
        }
    }
}
