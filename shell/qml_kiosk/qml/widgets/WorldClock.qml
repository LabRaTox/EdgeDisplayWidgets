import QtQuick
import QtQuick.Layouts
import ".."
import "../ClockTime.js" as ClockTime

/*
 * Up to six time zones side by side, each with its city and how far it is
 * from local time ("+6 h · tomorrow"). The faces are those of the clock (see
 * ClockFace.qml): analog or digital, any style and scheme.
 *
 * Wide tiles put all zones in one row; narrower ones use two rows, so a clock
 * never becomes a sliver. Zones need the timezones module; without its answer
 * a cell says that it waits.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["timezones"]
    property var options: ({})

    property var offsets: ({})
    property bool haveOffsets: false
    property double now: Date.now()

    function receive(module, data) {
        offsets = (data && data.offsets) || {}
        haveOffsets = true
    }

    function opt(key, fallback) {
        var v = options ? options[key] : undefined
        return v === undefined || v === null || v === "" ? fallback : v
    }

    readonly property var defaults: ["America/New_York", "Europe/London", "Asia/Tokyo", "", "", ""]
    readonly property var zones: {
        var out = []
        var keys = ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5", "zone_6"]
        for (var i = 0; i < keys.length; i++) {
            // An option set to empty means "no zone here", not the default.
            var v = options && options[keys[i]] !== undefined ? options[keys[i]] : defaults[i]
            if (v) out.push(v)
        }
        return out
    }
    readonly property string display: opt("display", "digital")
    readonly property bool showSeconds: opt("seconds", false) === true
    readonly property bool format24: String(opt("hour_format", "24")) !== "12"
    readonly property bool custom: opt("custom_colors", false) === true
    readonly property bool showCity: opt("show_city", true) === true
    readonly property bool showDifference: opt("show_difference", true) === true
    readonly property string dateMode: opt("date", "none")
    readonly property var locale: Qt.locale(bridge.tr("widget.clock.locale"))
    readonly property var localTime: ClockTime.wallTime(now)

    function tr(key) { return bridge.tr(key) }

    Timer {
        interval: root.showSeconds ? 250 : 1000
        running: true
        repeat: true
        onTriggered: root.now = Date.now()
    }

    // One row when the tile is wide enough for square-ish cells, else two.
    readonly property int count: zones.length
    readonly property int columns: count <= 1 ? 1 : (width / Math.max(1, height) >= count * 0.5 ? count : Math.ceil(count / 2))
    readonly property string uiFont: theme ? theme["font-ui"] : "sans-serif"

    Text {
        anchors.centerIn: parent
        visible: root.count === 0
        text: bridge.tr("widget.world_clock.no_zones")
        color: root.theme ? root.theme["fg-muted"] : "#888888"
        font.pixelSize: 18
        font.family: root.uiFont
    }

    GridLayout {
        anchors.fill: parent
        columns: root.columns
        rowSpacing: 12
        columnSpacing: 12

        Repeater {
            model: root.zones
            delegate: ColumnLayout {
                id: cell
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 1
                spacing: 4
                readonly property bool known: root.offsets[modelData] !== undefined
                readonly property var time: ClockTime.wallTime(root.now, known ? root.offsets[modelData] : undefined)

                Text {
                    visible: root.showCity
                    Layout.fillWidth: true
                    text: ClockTime.city(modelData)
                    color: root.theme ? root.theme["fg"] : "#e0e0e0"
                    font.pixelSize: Math.max(12, Math.min(24, root.height * 0.07))
                    font.weight: Font.Medium
                    font.family: root.uiFont
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Rectangle {
                        anchors.fill: parent
                        visible: root.display === "digital" && face.hasFace
                        radius: 10
                        color: face.colours.face
                    }
                    ClockFace {
                        id: face
                        anchors.fill: parent
                        anchors.margins: root.display === "digital" && hasFace ? 8 : 0
                        visible: cell.known
                        theme: root.theme
                        display: root.display
                        style: root.display === "analog" ? root.opt("face_analog", "classic") : root.opt("face_digital", "classic")
                        scheme: root.opt("scheme", "theme")
                        customFace: root.custom ? root.opt("color_face", "") : ""
                        customText: root.custom ? root.opt("color_text", "") : ""
                        customAccent: root.custom ? root.opt("color_accent", "") : ""
                        format24: root.format24
                        showSeconds: root.showSeconds
                        hours: cell.time.hours
                        minutes: cell.time.minutes
                        seconds: cell.time.seconds
                        day: cell.time.day
                        words: style === "words" ? ClockTime.words(cell.time.hours, cell.time.minutes, root.tr) : ""
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: !cell.known
                        text: root.haveOffsets ? bridge.tr("widget.world_clock.unknown_zone") : "…"
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 15
                        font.family: root.uiFont
                    }
                }

                Text {
                    visible: root.showDifference && cell.known
                    Layout.fillWidth: true
                    text: ClockTime.difference(cell.time, root.localTime, root.tr)
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: Math.max(11, Math.min(20, root.height * 0.06))
                    font.family: root.uiFont
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }
                Text {
                    visible: root.dateMode !== "none" && cell.known
                    Layout.fillWidth: true
                    text: ClockTime.dateText(root.locale, cell.time.date, root.dateMode, root.tr)
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: Math.max(11, Math.min(20, root.height * 0.06))
                    font.family: root.uiFont
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }
            }
        }
    }
}
