import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Window
import ".."

/*
 * Media: cover art on the left across the full height, what is playing
 * beside it, and the transport underneath that.
 *
 * Commands go to the backend's `/api/media/...` routes, so it keeps being
 * the only thing that talks to MPRIS.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["media"]
    property var payload: null
    property bool compact: false
    // Its own inset: 16 all round
    readonly property int padH: 16
    readonly property int padV: 16

    readonly property int usPerSecond: 1000000

    readonly property bool active: payload && payload.available === true
                                   && payload.active === true
    readonly property bool playing: active && payload.playback_status === "Playing"
    /** What the idle state shows in place of the artist. */
    property string reason: ""

    /** The playhead in microseconds, counted forward between payloads. */
    property real positionUs: 0
    property bool scrubbing: false
    property real scrubFraction: 0

    function time(us) {
        if (!isFinite(us) || us <= 0) return "0:00"
        var total = Math.floor(us / usPerSecond)
        var m = Math.floor(total / 60), s = total % 60
        return m + ":" + (s < 10 ? "0" : "") + s
    }

    function receive(module, data) {
        payload = data
        if (!data || data.available !== true)
            reason = (data && data.reason) ? data.reason : bridge.tr("widget.media.unavailable")
        else if (data.active !== true)
            reason = bridge.tr("widget.media.no_active_player_short")
        else
            reason = ""
        advance()
    }

    /*
     * MPRIS never signals the position, so the backend sends an anchor
     * (position, rate, timestamp) whenever something changes and the playhead
     * is counted on from there.
     *
     * Four steps a second, not one per frame: a continuously moving element
     * costs measurably more than the smoothness is worth, which is the same
     * reason the chart does not slide (see Chart.travel).
     */
    function advance() {
        if (!active) { positionUs = 0; return }
        var pos = payload.position_us || 0
        if (playing && payload.position_ts)
            pos += (Date.now() / 1000 - payload.position_ts) * (payload.rate || 1) * usPerSecond
        if (payload.length_us > 0) pos = Math.min(pos, payload.length_us)
        positionUs = pos
    }

    Timer {
        interval: 250
        running: root.playing && !root.scrubbing
        repeat: true
        onTriggered: root.advance()
    }

    // ------------------------------------------------------------ commands

    function post(path, body) {
        var xhr = new XMLHttpRequest()
        xhr.open("POST", bridge.api + path)
        if (body) xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(body ? JSON.stringify(body) : "")
    }

    function toggleShuffle() {
        post("/api/media/shuffle", { enabled: !(payload && payload.shuffle) })
    }
    function cycleLoop() {
        // None -> Track -> Playlist -> None, as the MPRIS spec orders them.
        var cycle = { "None": "Track", "Track": "Playlist", "Playlist": "None" }
        post("/api/media/loop", { status: cycle[payload ? payload.loop_status : "None"] || "Track" })
    }
    function seek(fraction) {
        if (!active || !payload.length_us) return
        post("/api/media/set_position", { position_us: Math.round(fraction * payload.length_us) })
    }

    RowLayout {
        anchors.fill: parent
        spacing: 14                                    // between art and info

        // The art: a square, 18 percent of the window width, 140 to 240
        Rectangle {
            readonly property int side: Math.min(
                root.height,
                Math.max(140, Math.min(240, Math.round(root.Window.width * 0.18))))
            Layout.preferredWidth: side
            Layout.preferredHeight: side
            Layout.alignment: Qt.AlignTop
            radius: 8
            color: Qt.rgba(1, 1, 1, 0.05)
            clip: true

            Image {
                id: cover
                anchors.fill: parent
                source: root.active && root.payload.art_token
                        ? bridge.api + "/api/media/art/" + encodeURIComponent(root.payload.art_token)
                        : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                visible: status === Image.Ready
            }
            Text {                                     // shown when there is no cover
                anchors.centerIn: parent
                visible: !cover.visible
                text: "♪"
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 60                     // 3rem
                font.family: root.theme ? root.theme["font-display"] : "sans-serif"
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Player, title, artist
            ColumnLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 8
                spacing: 0

                Text {                                 // the player
                    text: root.active ? String(root.payload.player || "").toUpperCase() : ""
                    visible: text.length > 0
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: 14                 // 0.7rem
                    font.letterSpacing: 1.68           // 0.12em
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    bottomPadding: 4
                    Layout.fillWidth: true
                }
                Text {                                 // the title
                    text: root.active ? (root.payload.title || "–")
                                      : bridge.tr("widget.media.no_active_player")
                    color: root.theme ? root.theme["fg"] : "#e0e0e0"
                    font.pixelSize: 23                 // 1.15rem
                    font.weight: Font.Medium
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    bottomPadding: 2
                    Layout.fillWidth: true
                }
                Text {                                 // the artist
                    text: root.active ? (root.payload.artist || root.payload.album || "")
                                      : root.reason
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: 18                 // 0.9rem
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            // The position bar
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                spacing: 4

                Item {
                    id: scrubber
                    Layout.fillWidth: true
                    Layout.preferredHeight: 16                 // the thumb
                    enabled: root.active && root.payload.can_seek === true
                    opacity: enabled ? 1 : 0.4

                    readonly property real fraction: {
                        if (root.scrubbing) return root.scrubFraction
                        if (!root.active || !root.payload.length_us) return 0
                        return Math.max(0, Math.min(1, root.positionUs / root.payload.length_us))
                    }

                    Rectangle {                                // the track
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 4
                        radius: 2
                        color: Qt.rgba(1, 1, 1, 0.1)
                    }
                    Rectangle {                                // the thumb
                        id: thumb
                        width: 16
                        height: 16
                        radius: 8
                        anchors.verticalCenter: parent.verticalCenter
                        x: (scrubber.width - width) * scrubber.fraction
                        color: root.theme ? root.theme["accent"] : "#00e0ff"
                    }
                    MouseArea {
                        anchors.fill: parent
                        function fractionAt(px) {
                            return Math.max(0, Math.min(1, (px - thumb.width / 2)
                                            / (scrubber.width - thumb.width)))
                        }
                        onPressed: function (m) {
                            root.scrubbing = true
                            root.scrubFraction = fractionAt(m.x)
                        }
                        onPositionChanged: function (m) {
                            if (root.scrubbing) root.scrubFraction = fractionAt(m.x)
                        }
                        // Sent on release, not per pixel while dragging.
                        onReleased: {
                            root.scrubbing = false
                            root.seek(root.scrubFraction)
                        }
                        onCanceled: root.scrubbing = false
                    }
                }

                RowLayout {                                    // elapsed and total
                    Layout.fillWidth: true
                    Text {
                        text: root.time(root.scrubbing && root.active
                                        ? root.scrubFraction * root.payload.length_us
                                        : root.positionUs)
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 14                     // 0.7rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: root.time(root.active ? root.payload.length_us : 0)
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 14
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    }
                }
            }

            Item { Layout.fillHeight: true }

            // The transport
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Layout.alignment: Qt.AlignHCenter
                spacing: 12

                Item { Layout.fillWidth: true }

                Control {                                      // shuffle
                    theme: root.theme
                    toggle: true
                    on: root.active && root.payload.shuffle === true
                    enabled: root.active
                    glyph: "M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 "
                         + "18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 "
                         + "3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"
                    glyphSize: 20
                    onActivated: root.toggleShuffle()
                }
                Control {
                    theme: root.theme
                    enabled: root.active && root.payload.can_prev === true
                    glyph: "M6 6h2v12H6V6zm3.5 6L20 18V6L9.5 12z"
                    onActivated: root.post("/api/media/prev")
                }
                Control {                                      // play and pause
                    theme: root.theme
                    primary: true
                    enabled: root.active && (root.payload.can_play === true
                                             || root.payload.can_pause === true)
                    glyphSize: 26
                    glyph: root.playing ? "M6 5h4v14H6zm8 0h4v14h-4z" : "M8 5v14l11-7-11-7z"
                    onActivated: root.post("/api/media/play_pause")
                }
                Control {
                    theme: root.theme
                    enabled: root.active && root.payload.can_next === true
                    glyph: "M16 6h2v12h-2V6zM4 6l10.5 6L4 18V6z"
                    onActivated: root.post("/api/media/next")
                }
                Control {                                      // repeat
                    theme: root.theme
                    toggle: true
                    on: root.active && (root.payload.loop_status || "None") !== "None"
                    // The dot would fight the badge, so the loop button has none.
                    showDot: false
                    badge: root.active && root.payload.loop_status === "Track"
                    enabled: root.active
                    glyph: "M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"
                    onActivated: root.cycleLoop()
                }

                Item { Layout.fillWidth: true }
            }
        }
    }

    /*
     * One transport button: a 60 pixel circle. The glyphs are the same
     * 24x24 paths, handed to a Shape rather than cut out of the Tabler
     * sprite, so the transport keeps its own set.
     */
    component Control: Rectangle {
        id: control
        property var theme
        property string glyph: ""
        property int glyphSize: 22
        property bool primary: false
        property bool toggle: false
        property bool on: false
        property bool showDot: true
        property bool badge: false
        signal activated()

        readonly property color accent: theme ? theme["accent"] : "#00e0ff"

        implicitWidth: 60
        implicitHeight: 60
        radius: 30
        color: primary ? accent : (toggle ? "transparent" : Qt.rgba(1, 1, 1, 0.05))
        border.width: 1
        border.color: primary ? accent
                    : (toggle && on) ? accent
                                     : (theme ? theme["card-border"] : "#222222")
        opacity: enabled ? 1 : 0.3                     // button:disabled
        scale: press.pressed && enabled ? 0.94 : 1     // button:active
        Behavior on scale { NumberAnimation { duration: 150 } }
        Behavior on border.color { ColorAnimation { duration: 150 } }

        readonly property color ink: primary ? (theme ? theme["bg"] : "#0a0a0a")
                                   : (toggle && !on) ? (theme ? theme["fg-muted"] : "#888888")
                                   : (toggle && on) ? accent
                                                    : (theme ? theme["fg"] : "#e0e0e0")

        Shape {
            anchors.centerIn: parent
            width: 24
            height: 24
            scale: control.glyphSize / 24
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: control.ink
                strokeColor: "transparent"
                // SVG's default, which the paths above are drawn for.
                fillRule: ShapePath.WindingFill
                PathSvg { path: control.glyph }
            }
        }

        // The dot marking a toggle as on
        Rectangle {
            visible: control.toggle && control.on && control.showDot
            width: 4
            height: 4
            radius: 2
            color: control.accent
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
        }

        // The repeat-one badge
        Rectangle {
            visible: control.badge
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 8
            anchors.topMargin: 8
            width: 14
            height: 14
            radius: 7
            color: control.accent
            Text {
                anchors.centerIn: parent
                text: "1"
                color: control.theme ? control.theme["bg"] : "#0a0a0a"
                font.pixelSize: 10
                font.weight: Font.Bold
            }
        }

        MouseArea {
            id: press
            anchors.fill: parent
            enabled: control.enabled
            onClicked: control.activated()
        }
    }
}
