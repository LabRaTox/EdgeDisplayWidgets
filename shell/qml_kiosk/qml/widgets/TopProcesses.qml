import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Top processes: one line per process, name on the left, load and memory
 * right-aligned. The name takes whatever the two figures leave.
 *
 * Those two keep a minimum width, so the numbers stay in line while the
 * values jump around.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["top_processes"]
    property var payload: null
    property bool compact: false

    function bytes(n) {
        var GiB = 1024 * 1024 * 1024, MiB = 1024 * 1024
        if (n >= GiB) return (n / GiB).toFixed(1) + " GiB"
        if (n >= MiB) return (n / MiB).toFixed(0) + " MiB"
        return Math.round(n / 1024) + " KiB"
    }

    function receive(module, data) {
        payload = data
        var list = (data && data.processes) || []
        /*
         * Patch in place while the set of processes is the same length: a
         * clear() would throw the rows away several times a minute and the
         * list would flicker and lose its scroll position.
         */
        if (list.length !== rows.count) rows.clear()
        for (var i = 0; i < list.length; i++) {
            var p = list[i]
            var entry = {
                "name": String(p.name || ""),
                "cpu": p.cpu_percent.toFixed(1) + "%",
                "mem": bytes(p.rss)
            }
            if (i < rows.count) {
                for (var field in entry) rows.setProperty(i, field, entry[field])
            } else {
                rows.append(entry)
            }
        }
    }

    ListModel { id: rows }

    /*
     * The two figure columns, measured on the actual mono font rather than
     * multiplied out from a character count, because a digit is not as wide
     * as the font size. The heading sits over the same widths.
     */
    Text {
        id: cpuProbe
        visible: false
        text: "99.9%"
        font.pixelSize: 20
        font.family: root.theme ? root.theme["font-mono"] : "monospace"
    }
    Text {
        id: memProbe
        visible: false
        text: "999.9 GiB"
        font.pixelSize: 20
        font.family: root.theme ? root.theme["font-mono"] : "monospace"
    }
    readonly property int cpuWidth: cpuProbe.implicitWidth
    readonly property int memWidth: memProbe.implicitWidth + 4   // rightPadding

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.top_processes.title")
            Layout.bottomMargin: Style.headingBottom
        }

        /*
         * The column heading. It carries the same constraints as a row below,
         * so the three columns line up without either side knowing the other's
         * widths.
         */
        RowLayout {
            visible: rows.count > 0
            Layout.fillWidth: true
            Layout.bottomMargin: 4
            spacing: 12

            Text {
                text: bridge.tr("widget.top_processes.col.name")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                leftPadding: 4
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text {
                text: bridge.tr("widget.top_processes.col.cpu")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                horizontalAlignment: Text.AlignRight
                Layout.minimumWidth: root.cpuWidth
            }
            Text {
                text: bridge.tr("widget.top_processes.col.mem")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                horizontalAlignment: Text.AlignRight
                rightPadding: 4
                Layout.minimumWidth: root.memWidth
            }
        }

        Rectangle {
            visible: rows.count > 0
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.bottomMargin: 2
            color: root.theme ? root.theme["card-border"] : "#222222"
        }

        // Shown in place of the list
        Text {
            visible: rows.count === 0
            text: bridge.tr("widget.top_processes.empty")
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 20
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            padding: 6
            Layout.fillWidth: true
        }

        ListView {
            id: list
            visible: rows.count > 0
            model: rows
            spacing: 6                             // between rows
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            topMargin: 6                           // room under the heading
            Layout.fillWidth: true
            Layout.fillHeight: true

            delegate: RowLayout {
                width: list.width
                spacing: 12                        // between columns

                Text {                             // The process
                    text: model.name
                    color: root.theme ? root.theme["fg"] : "#e0e0e0"
                    font.pixelSize: 20             // 1rem
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    leftPadding: 4                 // the row's own inset
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignBaseline
                }
                Text {                             // Its load
                    text: model.cpu
                    color: root.theme ? root.theme["accent"] : "#00e0ff"
                    font.pixelSize: 20
                    font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    horizontalAlignment: Text.AlignRight
                    Layout.minimumWidth: root.cpuWidth
                    Layout.alignment: Qt.AlignBaseline
                }
                Text {                             // Its memory
                    text: model.mem
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: 20
                    font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    horizontalAlignment: Text.AlignRight
                    rightPadding: 4
                    Layout.minimumWidth: root.memWidth
                    Layout.alignment: Qt.AlignBaseline
                }
            }
        }
    }
}
