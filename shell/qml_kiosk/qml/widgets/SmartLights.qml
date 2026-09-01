import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

/*
 * Smart lights: two columns of device cards, each with a switch, a
 * brightness slider and the colour presets. Commands go to the backend's
 * own control route.
 *
 * A tap changes the card immediately and the backend confirms afterwards.
 * Without that a lamp would only appear to react on the next poll, which is
 * thirty seconds away; if the command fails, the card falls back to the
 * reported state and shows the reason.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["smart_lights"]
    property var payload: null
    property bool compact: false

    readonly property var providerLabel: ({ "govee": "Govee", "tuya": "Tuya" })
    readonly property var presets: [
        { hex: "#ff3030", key: "widget.smart_lights.color.red" },
        { hex: "#ff8a1a", key: "widget.smart_lights.color.orange" },
        { hex: "#ffe066", key: "widget.smart_lights.color.warmwhite" },
        { hex: "#a0ff60", key: "widget.smart_lights.color.lime" },
        { hex: "#30c2ff", key: "widget.smart_lights.color.cyan" },
        { hex: "#7a4dff", key: "widget.smart_lights.color.violet" },
        { hex: "#ffffff", key: "widget.smart_lights.color.white" }
    ]

    property string note: ""
    property string errors: ""
    /** id -> what we last asked for, until the next poll confirms it. */
    property var optimistic: ({})
    /** The device set the cards were built from, to spot a real change. */
    property string deviceKey: ""

    /*
     * A ListModel, not a plain array: a card has to redraw the moment it is
     * tapped, and a property of a JavaScript object handed to a delegate
     * notifies nobody. Tapping a lamp would then do nothing visible until
     * the next poll came in.
     */
    ListModel { id: devices }

    function receive(module, data) {
        payload = data
        var list = (data && data.devices) || []
        var errs = (data && data.errors) || {}

        var real = [], unconfigured = []
        for (var prov in errs) {
            if (!errs[prov]) continue
            if (errs[prov] === "not configured") unconfigured.push(providerLabel[prov] || prov)
            else real.push((providerLabel[prov] || prov) + ": " + errs[prov])
        }
        errors = real.join("  •  ")

        if (list.length === 0) {
            devices.clear()
            deviceKey = ""
            note = unconfigured.length > 0
                 ? bridge.tr("widget.smart_lights.not_configured")
                        .replace("{providers}", unconfigured.join(" + "))
                 : bridge.tr("widget.smart_lights.no_devices")
            return
        }
        note = ""

        var key = []
        for (var k = 0; k < list.length; k++) key.push(list[k].id)
        key = key.join("|")
        if (key !== deviceKey) {
            devices.clear()
            for (var n = 0; n < list.length; n++) devices.append(entry(list[n]))
            deviceKey = key
            return
        }
        // The same lamps: patch the values rather than rebuild, or every poll
        // would throw away the cards while someone is using them.
        for (var i = 0; i < list.length && i < devices.count; i++) {
            var next = entry(list[i])
            for (var field in next) devices.setProperty(i, field, next[field])
        }
    }

    function entry(d) {
        var opt = optimistic[d.id] || {}
        return {
            "deviceId": String(d.id),
            "name": String(d.name),
            "provider": String(providerLabel[d.provider] || d.provider),
            "online": d.online === true,
            "hasBrightness": d.has_brightness === true,
            "hasColor": d.has_color === true,
            "on": opt.on !== undefined ? opt.on : d.on === true,
            "brightness": opt.brightness !== undefined ? opt.brightness : (d.brightness || 0)
        }
    }

    /** Remember what we asked for, so the next poll does not undo it. */
    function remember(id, key, value) {
        var all = optimistic
        var held = all[id] || {}
        held[key] = value
        all[id] = held
        optimistic = all
        forgetTimer.restart()
    }

    Timer {
        id: forgetTimer
        interval: 5000
        onTriggered: root.optimistic = ({})
    }

    function send(id, action, value, card) {
        card.pending = true
        card.status = ""
        card.statusError = false
        var xhr = new XMLHttpRequest()
        xhr.open("POST", bridge.api + "/api/smart_lights/" + encodeURIComponent(id) + "/control")
        xhr.setRequestHeader("Content-Type", "application/json")
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            card.pending = false
            var body = {}
            try { body = JSON.parse(xhr.responseText) } catch (e) { body = {} }
            if (xhr.status < 200 || xhr.status >= 300 || body.ok !== true) {
                card.status = body.error || ("HTTP " + xhr.status)
                card.statusError = true
                root.optimistic = ({})
                card.clearStatus.restart()
            }
        }
        xhr.send(JSON.stringify({ action: action, value: value }))
    }

    ColorDialog {
        id: picker
        property var card: null
        onAccepted: if (card) card.colorChosen(selectedColor)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // Shown in place of the cards
        Text {
            visible: root.note.length > 0
            text: root.note
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 20
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            padding: 8
            Layout.fillWidth: true
        }

        /*
         * Two equal columns with an 8 pixel gap, packed to the top. A
         * GridView cannot do it, since it fits whole cells only and two
         * columns plus the gap do not go into the width; it would fall back
         * to a single column.
         */
        Flickable {
            id: cards
            visible: root.note.length === 0
            clip: true
            contentHeight: grid.height
            boundsBehavior: Flickable.StopAtBounds
            Layout.fillWidth: true
            Layout.fillHeight: true

            GridLayout {
                id: grid
                width: cards.width
                columns: 2
                columnSpacing: 8
                rowSpacing: 8

                Repeater {
                    model: devices

                    Card {
                        theme: root.theme
                        // Bound to the model, so a write below redraws the card.
                        deviceId: model.deviceId
                        name: model.name
                        provider: model.provider
                        online: model.online
                        hasBrightness: model.hasBrightness
                        hasColor: model.hasColor
                        on: model.on
                        brightness: model.brightness

                        // One card is 396 by 131.
                        Layout.fillWidth: true
                        Layout.preferredHeight: 131

                        onToggled: {
                            if (!online) return
                            var next = !on
                            model.on = next
                            root.remember(deviceId, "on", next)
                            root.send(deviceId, next ? "on" : "off", undefined, this)
                        }
                        onBrightnessPicked: function (level) {
                            model.brightness = level
                            root.remember(deviceId, "brightness", level)
                            root.send(deviceId, "brightness", level, this)
                        }
                        onColorPicked: function (colour) {
                            // Both providers want the lamp on before a colour.
                            if (!on) toggled()
                            root.send(deviceId, "color",
                                      { r: Math.round(colour.r * 255),
                                        g: Math.round(colour.g * 255),
                                        b: Math.round(colour.b * 255) }, this)
                        }
                    }
                }
            }
        }

        // What a provider reported as broken
        Text {
            visible: root.errors.length > 0
            text: root.errors
            color: root.theme ? root.theme["bad"] : "#f87171"
            font.pixelSize: 15                             // 0.75rem
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    // One device card
    component Card: Rectangle {
        id: card
        property var theme
        property string deviceId: ""
        property string name: ""
        property string provider: ""
        property bool online: true
        property bool hasBrightness: false
        property bool hasColor: false
        property bool on: false
        property int brightness: 0

        property bool pending: false
        property string status: ""
        property bool statusError: false
        property alias clearStatus: statusTimer
        readonly property color accent: theme ? theme["accent"] : "#00e0ff"

        signal toggled()
        signal brightnessPicked(int level)
        signal colorPicked(color colour)

        function colorChosen(colour) { colorPicked(colour) }

        radius: 8
        opacity: online ? 1 : 0.55                          // Dimmed while unreachable
        color: on ? Qt.rgba(accent.r, accent.g, accent.b, 0.08)
                  : Qt.rgba(1, 1, 1, 0.04)
        border.width: 1
        border.color: pending ? (theme ? theme["warn"] : "#facc15")
                    : on ? Qt.rgba(accent.r, accent.g, accent.b, 0.4)
                         : (theme ? theme["card-border"] : "#222222")
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Timer { id: statusTimer; interval: 2000; onTriggered: card.statusError = false }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 12                          // padding 10px 12px
            anchors.rightMargin: 12
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            spacing: 6

            RowLayout {                                     // Name and switch, 26 high
                Layout.fillWidth: true
                Layout.preferredHeight: 26
                spacing: 10
                Text {
                    text: card.name
                    color: card.theme ? card.theme["fg"] : "#e0e0e0"
                    font.pixelSize: 19                      // 0.95rem
                    font.weight: Font.Medium
                    font.family: card.theme ? card.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                Rectangle {                                 // The switch
                    width: 44
                    height: 24
                    radius: 12
                    color: card.on ? card.accent : Qt.rgba(1, 1, 1, 0.08)
                    border.width: 1
                    border.color: card.on ? card.accent
                                          : (card.theme ? card.theme["card-border"] : "#222222")
                    opacity: card.online ? 1 : 0.5
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Rectangle {                             // Its knob
                        y: 1
                        x: card.on ? 21 : 1
                        width: 20
                        height: 20
                        radius: 10
                        color: card.on ? (card.theme ? card.theme["bg"] : "#0a0a0a")
                                       : (card.theme ? card.theme["fg"] : "#e0e0e0")
                        Behavior on x { NumberAnimation { duration: 140 } }
                    }
                    MouseArea { anchors.fill: parent; onClicked: card.toggled() }
                }
            }

            RowLayout {                                     // The brightness row, 22 high
                visible: card.hasBrightness
                Layout.fillWidth: true
                Layout.preferredHeight: 22
                spacing: 8

                Item {                                      // The slider
                    id: slider
                    Layout.fillWidth: true
                    Layout.preferredHeight: 22
                    enabled: card.online && card.on
                    opacity: enabled ? 1 : 0.4
                    // While dragging the knob follows the finger; otherwise
                    // it follows the lamp.
                    property int level: card.brightness
                    property bool dragging: false

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 4
                        radius: 2
                        color: Qt.rgba(1, 1, 1, 0.1)
                    }
                    Rectangle {                             // the thumb
                        id: knob
                        width: 18
                        height: 18
                        radius: 9
                        anchors.verticalCenter: parent.verticalCenter
                        x: (slider.width - width) * Math.max(0, slider.level - 1) / 99
                        color: card.accent
                        border.width: 2
                        border.color: card.theme ? card.theme["bg"] : "#0a0a0a"
                    }
                    MouseArea {
                        anchors.fill: parent
                        function levelAt(px) {
                            var ratio = Math.max(0, Math.min(1, (px - knob.width / 2)
                                                 / (slider.width - knob.width)))
                            return Math.round(1 + ratio * 99)
                        }
                        onPressed: function (m) { slider.dragging = true; slider.level = levelAt(m.x) }
                        onPositionChanged: function (m) { if (slider.dragging) slider.level = levelAt(m.x) }
                        // Sent on release, not per pixel:
                        // dragging would otherwise fire a command per pixel.
                        onReleased: {
                            slider.dragging = false
                            card.brightnessPicked(slider.level)
                        }
                    }
                }
                Text {                                      // The percentage
                    text: card.brightness > 0 ? card.brightness + "%" : "–"
                    color: card.theme ? card.theme["fg-muted"] : "#888888"
                    font.pixelSize: 16                      // 0.8rem
                    font.family: card.theme ? card.theme["font-mono"] : "monospace"
                    horizontalAlignment: Text.AlignRight
                    Layout.minimumWidth: 34                 // 3.5ch
                }
            }

            Flow {                                          // The colour presets, 24 high
                visible: card.hasColor
                Layout.fillWidth: true
                Layout.preferredHeight: 24
                spacing: 5
                Repeater {
                    model: root.presets
                    Rectangle {
                        required property var modelData
                        width: 24
                        height: 24
                        radius: 12
                        color: modelData.hex
                        border.width: 1
                        border.color: Qt.rgba(1, 1, 1, 0.2)
                        scale: swatch.pressed ? 0.95 : 1
                        Behavior on scale { NumberAnimation { duration: 80 } }
                        MouseArea {
                            id: swatch
                            anchors.fill: parent
                            onClicked: card.colorPicked(parent.color)
                        }
                    }
                }
                Item {                                      // The free colour picker
                    width: 24
                    height: 24
                    Canvas {                                // 1px dashed circle
                        anchors.fill: parent
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            ctx.strokeStyle = card.theme ? card.theme["fg-muted"] : "#888888"
                            ctx.lineWidth = 1
                            ctx.setLineDash([3, 3])
                            ctx.beginPath()
                            ctx.arc(width / 2, height / 2, width / 2 - 1, 0, 2 * Math.PI)
                            ctx.stroke()
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        text: "🎨"
                        font.pixelSize: 12
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { picker.card = card; picker.open() }
                    }
                }
            }

            RowLayout {                                     // Provider and status, 19 high
                Layout.fillWidth: true
                Layout.preferredHeight: 19
                Text {
                    text: card.provider.toUpperCase()
                    color: card.theme ? card.theme["fg-muted"] : "#888888"
                    font.pixelSize: 14                      // 0.7rem
                    font.letterSpacing: 0.5
                    font.family: card.theme ? card.theme["font-ui"] : "sans-serif"
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: card.statusError ? card.status : card.status.toUpperCase()
                    color: card.statusError ? (card.theme ? card.theme["bad"] : "#f87171")
                                            : (card.theme ? card.theme["fg-muted"] : "#888888")
                    font.pixelSize: 14
                    font.letterSpacing: card.statusError ? 0 : 0.5
                    font.family: card.theme ? card.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    Layout.maximumWidth: card.width * 0.6
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
