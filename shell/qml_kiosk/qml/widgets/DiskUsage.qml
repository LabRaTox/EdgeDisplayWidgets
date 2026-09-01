import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Disk usage: one block per mount point, made of the mount name with its
 * percentage, a bar, and a line of used / total / filesystem underneath.
 *
 * The compact variant drops that last line, which is what makes a row tall
 * enough to push the third disk off a small tile.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["disk_usage"]
    property var payload: null
    property bool compact: false

    function bytes(n) {
        var GiB = 1024 * 1024 * 1024, MiB = 1024 * 1024
        if (n >= GiB) return (n / GiB).toFixed(1) + " GiB"
        if (n >= MiB) return (n / MiB).toFixed(0) + " MiB"
        return n + " B"
    }
    function barColor(percent) {
        if (percent >= 90) return theme ? theme["bad"] : "#f87171"
        if (percent >= 80) return theme ? theme["warn"] : "#facc15"
        return theme ? theme["accent"] : "#00e0ff"
    }

    function receive(module, data) {
        payload = data
        rows.clear()
        var disks = (data && data.disks) || []
        for (var i = 0; i < disks.length; i++) {
            var d = disks[i]
            rows.append({
                "mount": String(d.mountpoint),
                "value": d.percent.toFixed(0) + "%",
                "percent": Math.min(100, d.percent),
                "fill": String(barColor(d.percent)),
                "meta": bytes(d.used) + " / " + bytes(d.total) + " • " + d.fstype
            })
        }
    }

    ListModel { id: rows }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.disk.title")
            Layout.bottomMargin: Style.headingBottom
        }

        // Shown in place of the list
        Text {
            visible: rows.count === 0
            text: bridge.tr("widget.disk.empty")
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 20
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            padding: 6
            Layout.fillWidth: true
        }

        ListView {
            visible: rows.count > 0
            id: list
            model: rows
            spacing: 10                            // between disks
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            topMargin: 6                           // room under the heading
            Layout.fillWidth: true
            Layout.fillHeight: true

            delegate: ColumnLayout {
                width: list.width
                spacing: 4                         // inside one disk

                RowLayout {                        // Mount point and percentage
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        text: model.mount
                        color: root.theme ? root.theme["fg"] : "#e0e0e0"
                        font.pixelSize: 20         // 1rem
                        font.weight: Font.Medium
                        font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignBaseline
                    }
                    Text {
                        text: model.value
                        color: root.theme ? root.theme["fg"] : "#e0e0e0"
                        font.pixelSize: 20
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignBaseline
                    }
                }

                Rectangle {                        // The bar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 8
                    radius: 4
                    color: Qt.rgba(1, 1, 1, 0.06)
                    Rectangle {                    // Its fill
                        width: parent.width * model.percent / 100
                        height: parent.height
                        radius: parent.radius
                        color: model.fill
                        Behavior on width { NumberAnimation { duration: 200 } }
                    }
                }

                Text {                             // Used, total and filesystem
                    visible: !root.compact
                    text: model.meta
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: 16             // 0.8rem
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }
}
