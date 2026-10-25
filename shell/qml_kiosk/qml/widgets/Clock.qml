import QtQuick
import QtQuick.Layouts
import QtMultimedia
import ".."
import "../ClockTime.js" as ClockTime

/*
 * A clock: local time or a chosen zone, analog or digital, in one of 22
 * faces and 10 colour schemes (see ClockFace.qml), with the place and the
 * date beside it.
 *
 * A tap opens a countdown: pick the minutes, and the tile counts down with a
 * ring that empties, then sounds a gong. Tapping a running countdown offers
 * to stop it. A countdown does not survive a restart of the kiosk.
 *
 * Zones need the timezones module: Qt's JavaScript has no zone database. Until
 * its answer arrives, a tile with a zone shows local time.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["timezones"]
    property var options: ({})

    property var offsets: ({})
    property double now: Date.now()

    function receive(module, data) {
        offsets = (data && data.offsets) || {}
    }

    function opt(key, fallback) {
        var v = options ? options[key] : undefined
        return v === undefined || v === null || v === "" ? fallback : v
    }

    readonly property string zone: opt("timezone", "")
    readonly property string display: opt("display", "digital")
    // `show_seconds` is what the clock had before; tiles saved with it keep it.
    readonly property bool showSeconds: opt("seconds", opt("show_seconds", false)) === true
    readonly property bool format24: String(opt("hour_format", "24")) !== "12"
    readonly property bool custom: opt("custom_colors", false) === true
    readonly property var time: ClockTime.wallTime(now, zone !== "" ? offsets[zone] : undefined)
    readonly property var locale: Qt.locale(bridge.tr("widget.clock.locale"))
    readonly property string place: opt("place_name", "") || ClockTime.city(zone)
    readonly property string dateLine: ClockTime.dateText(locale, time.date, opt("date", "both"),
                                                          function (k) { return bridge.tr(k) })

    function tick() { now = Date.now() }
    Component.onCompleted: tick()
    Timer {
        // Fast enough that the second never lags visibly; the faces only
        // repaint when a shown number changes.
        interval: root.showSeconds || root.counting ? 250 : 1000
        running: true
        repeat: true
        onTriggered: root.tick()
    }

    readonly property color fg: theme ? theme["fg"] : "#e0e0e0"
    readonly property color muted: theme ? theme["fg-muted"] : "#888888"
    readonly property color accent: clock.colours.accent
    readonly property string uiFont: theme ? theme["font-ui"] : "sans-serif"
    readonly property bool wideAnalog: display === "analog" && width > height * 1.4

    // A digital face with a face colour gets a plate behind it.
    Rectangle {
        anchors.fill: parent
        visible: root.display === "digital" && clock.hasFace && !root.counting
        radius: 12
        color: clock.colours.face
    }

    // -- the clock --------------------------------------------------------------

    GridLayout {
        anchors.fill: parent
        anchors.margins: clock.hasFace && root.display === "digital" ? 12 : 0
        visible: !root.counting && root.countdownState !== "done"
        flow: root.wideAnalog ? GridLayout.LeftToRight : GridLayout.TopToBottom
        rowSpacing: 6
        columnSpacing: 24

        Text {
            visible: !root.wideAnalog && root.place !== ""
            Layout.fillWidth: true
            text: root.place
            color: clock.hasFace && root.display === "digital" ? clock.colours.text : root.muted
            font.pixelSize: Math.max(12, Math.min(26, root.height * 0.08))
            font.family: root.uiFont
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        ClockFace {
            id: clock
            Layout.fillWidth: !root.wideAnalog
            Layout.fillHeight: true
            Layout.preferredWidth: root.wideAnalog ? height : -1
            theme: root.theme
            display: root.display
            style: root.display === "analog" ? root.opt("face_analog", "classic") : root.opt("face_digital", "classic")
            scheme: root.opt("scheme", "theme")
            customFace: root.custom ? root.opt("color_face", "") : ""
            customText: root.custom ? root.opt("color_text", "") : ""
            customAccent: root.custom ? root.opt("color_accent", "") : ""
            format24: root.format24
            showSeconds: root.showSeconds
            hours: root.time.hours
            minutes: root.time.minutes
            seconds: root.time.seconds
            day: root.time.day
            words: style === "words" ? ClockTime.words(root.time.hours, root.time.minutes,
                                                        function (k) { return bridge.tr(k) }) : ""
        }

        Text {
            visible: !root.wideAnalog && root.dateLine !== ""
            Layout.fillWidth: true
            text: root.dateLine
            color: clock.hasFace && root.display === "digital" ? clock.colours.text : root.muted
            font.pixelSize: Math.max(12, Math.min(24, root.height * 0.075))
            font.family: root.uiFont
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        // Beside a wide analog face: place and date as a column.
        ColumnLayout {
            visible: root.wideAnalog
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 6
            Text {
                Layout.fillWidth: true
                visible: root.place !== ""
                text: root.place
                color: root.fg
                font.pixelSize: Math.max(14, Math.min(40, root.height * 0.12))
                font.family: root.uiFont
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: root.dateLine !== ""
                text: root.dateLine
                color: root.muted
                font.pixelSize: Math.max(12, Math.min(28, root.height * 0.085))
                font.family: root.uiFont
                wrapMode: Text.WordWrap
            }
        }
    }

    // -- the countdown ------------------------------------------------------------

    // "" none, "pick" choosing, "run" counting, "done" sounding.
    property string countdownState: ""
    property double countdownEnd: 0
    property double countdownTotal: 0
    property bool countingBeforePick: false
    readonly property bool counting: countdownState === "run" || (countdownState === "pick" && countingBeforePick)
    readonly property double remaining: Math.max(0, countdownEnd - now)
    readonly property var presets: [1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120]

    function startCountdown(minutes) {
        countdownTotal = minutes * 60000
        countdownEnd = Date.now() + countdownTotal
        countingBeforePick = false
        countdownState = "run"
        tick()
    }

    function stopCountdown() {
        countingBeforePick = false
        countdownState = ""
        gong.stop()
    }

    onRemainingChanged: {
        if (countdownState === "run" && remaining <= 0) {
            countdownState = "done"
            gong.play()
            doneTimeout.restart()
        }
    }

    function clockText(ms) {
        var s = Math.ceil(ms / 1000)
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
        var p = function (n) { return (n < 10 ? "0" : "") + n }
        return (h > 0 ? h + ":" + p(m) : String(m)) + ":" + p(sec)
    }

    SoundEffect {
        id: gong
        source: Qt.resolvedUrl("../../assets/gong.wav")
        loops: 3
    }

    // A finished countdown goes away by itself after a minute.
    Timer { id: doneTimeout; interval: 60000; onTriggered: if (root.countdownState === "done") root.stopCountdown() }

    // Counting: a ring that empties, the time left inside.
    Item {
        anchors.fill: parent
        visible: root.countdownState === "run" || (root.countdownState === "pick" && root.countingBeforePick)
        opacity: root.countdownState === "pick" ? 0.25 : 1

        Canvas {
            id: ring
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height)
            height: width
            property real part: root.countdownTotal > 0 ? root.remaining / root.countdownTotal : 0
            onPartChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var r = width / 2, thick = r * 0.08
                ctx.lineWidth = thick
                ctx.lineCap = "round"
                ctx.strokeStyle = Qt.alpha(root.muted, 0.35)
                ctx.beginPath(); ctx.arc(r, r, r - thick, 0, 2 * Math.PI); ctx.stroke()
                if (part > 0) {
                    ctx.strokeStyle = root.accent
                    ctx.beginPath()
                    ctx.arc(r, r, r - thick, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * part)
                    ctx.stroke()
                }
            }
        }
        Column {
            anchors.centerIn: parent
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: bridge.tr("widget.clock.countdown")
                color: root.muted
                font.pixelSize: Math.max(12, ring.width * 0.07)
                font.family: root.uiFont
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.clockText(root.remaining)
                color: root.fg
                font.pixelSize: Math.max(16, ring.width * 0.24)
                font.weight: Font.Bold
                font.family: root.theme ? root.theme["font-display"] : root.uiFont
            }
        }
    }

    // Done: the time is up, gently pulsing until tapped.
    Column {
        anchors.centerIn: parent
        visible: root.countdownState === "done"
        spacing: 8
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: bridge.tr("widget.clock.time_up")
            color: root.accent
            font.pixelSize: Math.max(18, Math.min(root.width, root.height) * 0.2)
            font.weight: Font.Bold
            font.family: root.theme ? root.theme["font-display"] : root.uiFont
            SequentialAnimation on opacity {
                running: root.countdownState === "done"
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 700 }
                NumberAnimation { to: 1; duration: 700 }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: bridge.tr("widget.clock.tap_to_close")
            color: root.muted
            font.pixelSize: 16
            font.family: root.uiFont
        }
    }

    // A tap: open the picker, or close what is finished.
    MouseArea {
        anchors.fill: parent
        enabled: root.opt("countdown", true) === true && root.countdownState !== "pick"
        onClicked: {
            if (root.countdownState === "done") {
                root.stopCountdown()
            } else {
                root.countingBeforePick = root.countdownState === "run"
                root.countdownState = "pick"
            }
        }
    }

    // The picker: minutes to count down, or stop the running countdown.
    Rectangle {
        anchors.fill: parent
        visible: root.countdownState === "pick"
        radius: 12
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea { anchors.fill: parent; onClicked: root.countdownState = root.countingBeforePick ? "run" : "" }

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 24, 560)
            spacing: 12
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: bridge.tr("widget.clock.countdown_pick")
                color: root.fg
                font.pixelSize: 18
                font.weight: Font.Medium
                font.family: root.uiFont
            }
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: root.presets
                    delegate: Rectangle {
                        width: 76
                        height: 48
                        radius: 10
                        color: press.pressed ? Qt.alpha(root.accent, 0.35) : Qt.rgba(1, 1, 1, 0.08)
                        border.width: 1
                        border.color: Qt.alpha(root.accent, 0.6)
                        Text {
                            anchors.centerIn: parent
                            text: bridge.tr("widget.clock.minutes").replace("{n}", modelData)
                            color: root.fg
                            font.pixelSize: 17
                            font.family: root.uiFont
                        }
                        MouseArea { id: press; anchors.fill: parent; onClicked: root.startCountdown(modelData) }
                    }
                }
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8
                Repeater {
                    model: root.countingBeforePick ? ["stop", "back"] : ["back"]
                    delegate: Rectangle {
                        implicitWidth: label.implicitWidth + 32
                        implicitHeight: 44
                        radius: 10
                        color: modelData === "stop" ? Qt.alpha(root.theme ? root.theme["bad"] : "#ef4444", 0.25) : Qt.rgba(1, 1, 1, 0.08)
                        Text {
                            id: label
                            anchors.centerIn: parent
                            text: modelData === "stop" ? bridge.tr("widget.clock.countdown_stop") : bridge.tr("widget.clock.countdown_back")
                            color: root.fg
                            font.pixelSize: 16
                            font.family: root.uiFont
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: modelData === "stop" ? root.stopCountdown()
                                                            : (root.countdownState = root.countingBeforePick ? "run" : "")
                        }
                    }
                }
            }
        }
    }
}
