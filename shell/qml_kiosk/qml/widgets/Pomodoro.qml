import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtCore
import QtMultimedia
import ".."

/*
 * Pomodoro and stopwatch. No backend module: it counts by itself and keeps
 * its state across restarts, in QSettings. Timestamps are wall clock, so a
 * restart while running does not lose the elapsed time.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: []
    property var options: ({})
    property bool compact: false

    readonly property int workMinutes: (options && options.work_minutes) || 25
    readonly property int shortBreak: (options && options.short_break) || 5
    readonly property int longBreak: (options && options.long_break) || 15
    readonly property int longEvery: (options && options.long_every) || 4

    property string mode: "pomodoro"
    property string phase: "work"
    property int cycle: 1
    property real remainingMs: workMinutes * 60000
    property bool isRunning: false
    property real anchorTs: 0
    property real anchorRemainingMs: 0
    property real swElapsedMs: 0
    property real swAnchorTs: 0
    // Recomputed on every tick; the stopwatch has no stored remainder.
    property real shownMs: 0

    Settings {
        id: store
        category: "pomodoro"
        property string state: ""
    }

    function persist() {
        store.state = JSON.stringify({
            mode: mode, phase: phase, cycle: cycle, remaining_ms: remainingMs,
            running: isRunning, anchor_ts: anchorTs, anchor_remaining_ms: anchorRemainingMs,
            sw_elapsed_ms: swElapsedMs, sw_anchor_ts: swAnchorTs
        })
    }

    function restore() {
        if (!store.state) return
        try {
            var s = JSON.parse(store.state)
            mode = s.mode || "pomodoro"
            phase = s.phase || "work"
            cycle = s.cycle || 1
            remainingMs = s.remaining_ms
            isRunning = s.running === true
            anchorTs = s.anchor_ts || 0
            anchorRemainingMs = s.anchor_remaining_ms || 0
            swElapsedMs = s.sw_elapsed_ms || 0
            swAnchorTs = s.sw_anchor_ts || 0
        } catch (e) {
            // A state file from an older version: start over rather than fail.
        }
    }

    function fmt(ms) {
        var total = Math.max(0, Math.floor(ms / 1000))
        var m = Math.floor(total / 60), s = total % 60
        return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    function phaseLabel() {
        if (mode !== "pomodoro") return bridge.tr("widget.pomodoro.stopwatch_label")
        return bridge.tr("widget.pomodoro.phase." + phase) + " · " + cycle + "/" + longEvery
    }
    function phaseColor() {
        if (mode !== "pomodoro") return theme ? theme["fg-muted"] : "#888888"
        if (phase === "work") return theme ? theme["accent"] : "#00e0ff"
        if (phase === "short_break") return theme ? theme["ok"] : "#4ade80"
        return theme ? theme["accent-2"] : "#ff4488"
    }

    function switchMode(next) {
        if (mode === next) return
        if (isRunning) pause()
        mode = next
        persist(); tick()
    }
    function toggle() { isRunning ? pause() : start() }
    function start() {
        var now = Date.now()
        if (mode === "pomodoro") { anchorTs = now; anchorRemainingMs = remainingMs }
        else { swAnchorTs = now }
        isRunning = true
        persist(); tick()
    }
    function pause() {
        var now = Date.now()
        if (mode === "pomodoro") {
            remainingMs = Math.max(0, anchorRemainingMs - (now - anchorTs))
            anchorTs = 0; anchorRemainingMs = 0
        } else {
            swElapsedMs += now - swAnchorTs
            swAnchorTs = 0
        }
        isRunning = false
        persist(); tick()
    }
    function reset() {
        isRunning = false
        anchorTs = 0; anchorRemainingMs = 0
        if (mode === "pomodoro") {
            phase = "work"; cycle = 1; remainingMs = workMinutes * 60000
        } else {
            swElapsedMs = 0; swAnchorTs = 0
        }
        persist(); tick()
    }
    function skip() { if (mode === "pomodoro") advance(false) }

    function advance(playCue) {
        var wasRunning = isRunning
        if (wasRunning) pause()
        if (phase === "work") {
            var isLong = cycle >= longEvery
            phase = isLong ? "long_break" : "short_break"
            remainingMs = (isLong ? longBreak : shortBreak) * 60000
        } else {
            cycle = phase === "long_break" ? 1 : cycle + 1
            phase = "work"
            remainingMs = workMinutes * 60000
        }
        persist(); tick()
        if (playCue) cue()
        if (wasRunning) start()
    }

    function cue() {
        if (sound.source != "") sound.play()
        flash.start()
    }

    function tick() {
        if (mode !== "pomodoro") {
            shownMs = swElapsedMs + (isRunning && swAnchorTs ? Date.now() - swAnchorTs : 0)
            return
        }
        if (!isRunning) { shownMs = remainingMs; return }
        var left = Math.max(0, anchorRemainingMs - (Date.now() - anchorTs))
        remainingMs = left
        shownMs = left
        if (left <= 0) advance(true)
    }

    Component.onCompleted: { restore(); tick() }

    Timer {
        interval: 200
        running: root.isRunning
        repeat: true
        onTriggered: root.tick()
    }

    SoundEffect {
        id: sound
        source: Qt.resolvedUrl("../../assets/cue.wav")
    }

    // The flash when a phase ends
    Rectangle {
        anchors.fill: parent
        color: root.theme ? root.theme["accent"] : "#00e0ff"
        opacity: 0
        SequentialAnimation on opacity {
            id: flash
            running: false
            NumberAnimation { to: 0.35; duration: 110 }
            NumberAnimation { to: 0; duration: 990; easing.type: Easing.OutQuad }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // The mode switch
        RowLayout {
            spacing: 4
            Layout.alignment: Qt.AlignHCenter
            Repeater {
                model: [{ id: "pomodoro", key: "widget.pomodoro.mode.pomodoro" },
                        { id: "stopwatch", key: "widget.pomodoro.mode.stopwatch" }]
                Rectangle {
                    required property var modelData
                    readonly property bool active: root.mode === modelData.id
                    implicitWidth: modeText.implicitWidth + 24   // padding 4px 12px
                    implicitHeight: modeText.implicitHeight + 8
                    radius: 14
                    color: active ? (root.theme ? root.theme["accent"] : "#00e0ff") : "transparent"
                    border.width: 1
                    border.color: active ? (root.theme ? root.theme["accent"] : "#00e0ff")
                                         : (root.theme ? root.theme["card-border"] : "#222222")
                    Text {
                        id: modeText
                        anchors.centerIn: parent
                        text: bridge.tr(parent.modelData.key)
                        color: parent.active ? (root.theme ? root.theme["bg"] : "#0a0a0a")
                                             : (root.theme ? root.theme["fg-muted"] : "#888888")
                        font.pixelSize: 17                       // 0.85rem
                        font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.switchMode(parent.modelData.id)
                    }
                }
            }
        }

        // The phase line
        Text {
            text: root.phaseLabel().toUpperCase()
            color: root.phaseColor()
            font.pixelSize: 19                                   // 0.95rem
            font.weight: Font.Medium
            font.letterSpacing: 0.5
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            Layout.alignment: Qt.AlignHCenter
        }

        // The clock: 9 percent of the window width, between 50 and 100
        Text {
            text: root.fmt(root.shownMs)
            color: root.theme ? root.theme["fg"] : "#e0e0e0"
            font.pixelSize: Math.max(50, Math.min(100, Math.round(root.Window.width * 0.09)))
            font.weight: Font.DemiBold
            font.family: root.theme ? root.theme["font-mono"] : "monospace"
            lineHeight: 1
            Layout.alignment: Qt.AlignHCenter
            Layout.fillHeight: true
            verticalAlignment: Text.AlignVCenter
        }

        // The buttons
        RowLayout {
            spacing: 8
            Layout.alignment: Qt.AlignHCenter
            Button {
                theme: root.theme
                label: root.isRunning ? bridge.tr("widget.pomodoro.pause")
                                      : bridge.tr("widget.pomodoro.start")
                primary: true
                running: root.isRunning
                onPressed: root.toggle()
            }
            Button {
                theme: root.theme
                label: bridge.tr("widget.pomodoro.reset")
                onPressed: root.reset()
            }
            Button {
                theme: root.theme
                label: bridge.tr("widget.pomodoro.skip")
                visible: root.mode === "pomodoro"
                onPressed: root.skip()
            }
        }
    }

    /* A button, with the primary one turning amber while it runs. */
    component Button: Rectangle {
        id: button
        property var theme
        property string label: ""
        property bool primary: false
        property bool running: false
        signal pressed()

        implicitWidth: caption.implicitWidth + 40                // padding 10px 20px
        implicitHeight: caption.implicitHeight + 20
        radius: 8
        color: primary ? (running ? (theme ? theme["warn"] : "#facc15")
                                  : (theme ? theme["accent"] : "#00e0ff"))
                       : Qt.rgba(1, 1, 1, 0.06)
        border.width: 1
        border.color: primary ? color : (theme ? theme["card-border"] : "#222222")
        scale: area.pressed ? 0.97 : 1                           // :active
        Behavior on scale { NumberAnimation { duration: 80 } }

        Text {
            id: caption
            anchors.centerIn: parent
            text: button.label
            color: button.primary ? (button.theme ? button.theme["bg"] : "#0a0a0a")
                                  : (button.theme ? button.theme["fg"] : "#e0e0e0")
            font.pixelSize: 20                                   // 1rem
            font.weight: button.primary ? Font.DemiBold : Font.Medium
            font.family: button.theme ? button.theme["font-ui"] : "sans-serif"
        }
        MouseArea { id: area; anchors.fill: parent; onClicked: button.pressed() }
    }
}
