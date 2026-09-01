import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Sensors: one line per reading, chip on the left, label beside it, the
 * temperature right-aligned. The value column takes what it needs and the
 * rest is split one third to two thirds.
 *
 * The compact variant shortens the list to the readings the backend marked
 * as primary, and falls back to all of them when a machine marks none.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["sensors"]
    property var payload: null
    property bool compact: false
    // Its own inset: 14 by 16
    readonly property int padH: 16
    readonly property int padV: 14

    property string note: ""

    function colorFor(temp) {
        if (temp >= 85) return theme ? theme["bad"] : "#f87171"
        if (temp >= 70) return theme ? theme["warn"] : "#facc15"
        if (temp <= 0)  return theme ? theme["accent-2"] : "#ff4488"
        return theme ? theme["accent"] : "#00e0ff"
    }

    function receive(module, data) {
        payload = data
        rows.clear()
        if (!data || data.available !== true) {
            note = (data && data.reason) ? data.reason : bridge.tr("common.unavailable")
            return
        }
        var readings = data.readings || []
        if (compact) {
            var primary = readings.filter(function (r) { return r.primary })
            if (primary.length > 0) readings = primary
        }
        if (readings.length === 0) {
            note = bridge.tr("widget.sensors.empty")
            return
        }
        note = ""
        for (var i = 0; i < readings.length; i++) {
            var r = readings[i]
            rows.append({
                "chip": String(r.display_chip || r.chip || "").toLowerCase(),
                "label": String(r.display_label || r.label || ""),
                "value": r.temp_c.toFixed(1) + "°C",
                "valueColor": String(colorFor(r.temp_c)),
                "primary": r.primary === true
            })
        }
    }

    ListModel { id: rows }

    /*
     * The three column widths, worked out once for the whole widget. Per row
     * they would only agree as long as every reading rendered to the same
     * number of characters, and the heading has to sit over the same columns
     * anyway. The value column is measured on the widest reading that can
     * occur ("-99.9°C"), so a sub-zero sensor does not shift the row.
     */
    Text {
        id: valueProbe
        visible: false
        text: "-99.9°C"
        font.pixelSize: 17
        font.family: root.theme ? root.theme["font-mono"] : "monospace"
    }
    readonly property int rowMargin: 8
    readonly property int colSpacing: 12
    readonly property int valueWidth: valueProbe.implicitWidth
    readonly property real freeWidth: Math.max(0, list.width - 2 * rowMargin
                                               - valueWidth - 2 * colSpacing)
    readonly property int chipWidth: Math.round(freeWidth / 3)
    readonly property int labelWidth: Math.round(freeWidth - chipWidth)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.sensors.title")
            Layout.bottomMargin: Style.headingBottom
        }

        // Shown in place of the list
        Text {
            visible: root.note.length > 0
            text: root.note
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 17                     // 0.85rem
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            leftPadding: 8
            topPadding: 8
        }

        // The column heading, on the same three widths as the rows below.
        RowLayout {
            visible: root.note.length === 0 && rows.count > 0
            Layout.fillWidth: true
            Layout.leftMargin: root.rowMargin
            Layout.rightMargin: root.rowMargin
            Layout.bottomMargin: 4
            spacing: root.colSpacing

            Text {
                text: bridge.tr("widget.sensors.col.chip")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                elide: Text.ElideRight
                Layout.preferredWidth: root.chipWidth
            }
            Text {
                text: bridge.tr("widget.sensors.col.sensor")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                elide: Text.ElideRight
                Layout.preferredWidth: root.labelWidth
            }
            Text {
                text: bridge.tr("widget.sensors.col.temp")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 14
                font.letterSpacing: 1
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: root.valueWidth
            }
        }

        Rectangle {
            visible: root.note.length === 0 && rows.count > 0
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.bottomMargin: 2
            color: root.theme ? root.theme["card-border"] : "#222222"
        }

        ListView {
            id: list
            visible: root.note.length === 0
            model: rows
            spacing: 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Layout.fillWidth: true
            Layout.fillHeight: true

            delegate: Rectangle {
                width: list.width
                height: line.implicitHeight + 8    // padding 4px top/bottom
                radius: 4
                color: model.primary ? Qt.rgba(1, 1, 1, 0.03) : "transparent"

                RowLayout {
                    id: line
                    anchors.fill: parent
                    anchors.leftMargin: root.rowMargin
                    anchors.rightMargin: root.rowMargin
                    spacing: root.colSpacing

                    // the narrow first column
                    Text {
                        text: model.chip
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 15         // 0.75rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        elide: Text.ElideRight
                        Layout.alignment: Qt.AlignBaseline
                        Layout.preferredWidth: root.chipWidth
                    }
                    // twice as wide
                    Text {
                        text: model.label
                        color: root.theme ? root.theme["fg"] : "#e0e0e0"
                        font.pixelSize: 17         // 0.85rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        elide: Text.ElideRight
                        Layout.alignment: Qt.AlignBaseline
                        Layout.preferredWidth: root.labelWidth
                    }
                    // as wide as the value needs
                    Text {
                        id: value
                        text: model.value
                        color: model.valueColor
                        font.pixelSize: 17
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        horizontalAlignment: Text.AlignRight
                        Layout.preferredWidth: root.valueWidth
                        Layout.alignment: Qt.AlignBaseline
                    }
                }
            }
        }
    }
}
