import QtQuick
import QtQuick.Layouts
import ".."

/*
 * The strip along the top: state dot, state word, sequence number, uptime,
 * then the clock pushed to the right edge by a spacer.
 *
 * Its own padding (6 by 16) and font size (0.85rem) differ from every other
 * widget, because at 32 pixels tall the usual 12 pixel inset leaves no room.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["heartbeat"]
    function receive(module, data) { payload = data }
    property var payload: null
    property bool online: false
    property var options: ({})
    readonly property bool showSeconds: options && options.show_seconds === true

    property string nowText: ""
    function tick() {
        nowText = new Date().toLocaleTimeString(Qt.locale(),
            showSeconds ? "hh:mm:ss" : "hh:mm")
    }
    Component.onCompleted: tick()
    Timer {
        // Fast when seconds show, otherwise twice a minute is plenty.
        interval: root.showSeconds ? 500 : 30000
        running: true
        repeat: true
        onTriggered: root.tick()
    }

    function uptimeText(value) {
        var seconds = Number(value)
        // With the seconds shown the strip counts along with the backend;
        // otherwise it reads as a duration.
        if (showSeconds) return seconds.toFixed(1) + " s"
        if (!seconds || seconds < 0) return "–"
        if (seconds < 60) return "< 1 min"
        if (seconds < 3600) return Math.floor(seconds / 60) + " min"
        if (seconds < 86400) {
            var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60)
            return m === 0 ? h + " h" : h + " h " + m + " min"
        }
        // Past a day the hours stop being the interesting part.
        var d = Math.floor(seconds / 86400), rest = Math.floor((seconds % 86400) / 3600)
        return rest === 0 ? d + " T" : d + " T " + rest + " h"
    }

    // Its own inset: 6 by 16, gap 16, items centred
    readonly property int padH: 16
    readonly property int padV: 6

    /*
     * Centred on the tile rather than filling it. The strip is 32 pixels
     * tall, and a theme may ask for a larger inset than that leaves room for:
     * clean sets 16 top and bottom, which is the whole height. Anchoring to
     * the middle lets the row overflow evenly in both directions, so it
     * still looks centred.
     */
    RowLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: implicitHeight
        spacing: 16

        RowLayout {
            Layout.alignment: Qt.AlignVCenter
            spacing: 8
            Rectangle {
                width: 8; height: 8; radius: 4
                color: root.online ? (root.theme ? root.theme["ok"] : "#4ade80")
                                   : (root.theme ? root.theme["bad"] : "#f87171")
            }
            Text {
                // The state word: 14px, uppercase, wide spacing
                text: (root.online ? bridge.tr("widget.heartbeat.status.connected")
                                   : bridge.tr("widget.heartbeat.status.disconnected")).toUpperCase()
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1.4
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            }
        }

        Row {
            Layout.alignment: Qt.AlignVCenter
            spacing: 0
            Text {
                // `seq <strong>…</strong>`: the gap is a space in the markup.
                text: bridge.tr("widget.heartbeat.seq") + " "
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 17
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
            Text {
                text: root.payload ? root.payload.seq : "–"
                color: root.theme ? root.theme["fg"] : "#e0e0e0"
                font.pixelSize: 17
                font.weight: Font.Medium
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
        }

        Row {
            Layout.alignment: Qt.AlignVCenter
            spacing: 0
            Text {
                text: bridge.tr("widget.heartbeat.uptime") + " "
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 17
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
            Text {
                text: root.payload ? root.uptimeText(root.payload.uptime) : "–"
                color: root.theme ? root.theme["fg"] : "#e0e0e0"
                font.pixelSize: 17
                font.weight: Font.Medium
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
        }

        Item { Layout.fillWidth: true }          // Pushes the clock to the right edge

        Text {
            Layout.alignment: Qt.AlignVCenter
            text: root.nowText
            color: root.theme ? root.theme["fg"] : "#e0e0e0"
            font.pixelSize: 17
            font.weight: Font.Medium
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
        }
    }
}
