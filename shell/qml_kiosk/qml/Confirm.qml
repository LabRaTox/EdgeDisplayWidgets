import QtQuick

/*
 * The themed replacement for a system confirm dialog: one
 * instance sits over the whole window and every widget asks through it.
 *
 * `ask()` takes a callback rather than returning a promise, which is what
 * QML's JavaScript offers, and the dialog stays modal: a second question
 * while one is open would clobber the first, so the caller has to wait.
 */
Item {
    id: dialog
    property var theme
    property string message: ""
    property string okLabel: ""
    property bool danger: false
    property var callback: null

    visible: opacity > 0
    opacity: 0
    Behavior on opacity { NumberAnimation { duration: 160 } }

    function ask(text, label, isDanger, done) {
        message = text
        okLabel = label || bridge.tr("common.confirm")
        danger = isDanger === true
        callback = done
        opacity = 1
    }

    function close(result) {
        opacity = 0
        var done = callback
        callback = null
        if (done) done(result)
    }

    // The dimmed backdrop
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.7)
        MouseArea { anchors.fill: parent; onClicked: dialog.close(false) }
    }

    // The panel
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(480, Math.max(280, message.implicitWidth + 48))
        height: 22 + message.height + 18 + actions.height + 22
        radius: 8
        color: dialog.theme ? dialog.theme["card-bg"] : "#1a1a1a"
        border.width: 1
        border.color: dialog.theme ? dialog.theme["card-border"] : "#222222"
        scale: dialog.opacity > 0 ? 1 : 0.96
        Behavior on scale { NumberAnimation { duration: 160 } }

        Text {
            id: message
            anchors { left: parent.left; right: parent.right; top: parent.top
                      leftMargin: 24; rightMargin: 24; topMargin: 22 }
            text: dialog.message
            color: dialog.theme ? dialog.theme["fg"] : "#e0e0e0"
            font.pixelSize: 21                     // 1.05rem
            font.family: dialog.theme ? dialog.theme["font-ui"] : "sans-serif"
            lineHeight: 1.4
            wrapMode: Text.WordWrap
        }

        Row {
            id: actions
            anchors { right: parent.right; bottom: parent.bottom
                      rightMargin: 24; bottomMargin: 22 }
            spacing: 10
            layoutDirection: Qt.RightToLeft

            DialogButton {
                theme: dialog.theme
                label: dialog.okLabel
                accentColor: dialog.danger ? (dialog.theme ? dialog.theme["bad"] : "#f87171")
                                           : (dialog.theme ? dialog.theme["accent"] : "#00e0ff")
                filled: true
                onPressed: dialog.close(true)
            }
            DialogButton {
                theme: dialog.theme
                label: bridge.tr("common.cancel")
                onPressed: dialog.close(false)
            }
        }
    }

    // One button
    component DialogButton: Rectangle {
        id: button
        property var theme
        property string label: ""
        property color accentColor: "#00e0ff"
        property bool filled: false
        signal pressed()

        implicitWidth: Math.max(96, caption.implicitWidth + 36)   // padding 10px 18px
        implicitHeight: Math.max(44, caption.implicitHeight + 20)
        radius: 6
        color: filled ? accentColor : Qt.rgba(1, 1, 1, 0.06)
        border.width: 1
        border.color: filled ? accentColor
                             : (theme ? theme["card-border"] : "#222222")
        scale: area.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: 80 } }

        Text {
            id: caption
            anchors.centerIn: parent
            text: button.label
            color: button.filled ? (button.theme ? button.theme["bg"] : "#0a0a0a")
                                 : (button.theme ? button.theme["fg"] : "#e0e0e0")
            font.pixelSize: 19                                     // 0.95rem
            font.weight: button.filled ? Font.DemiBold : Font.Medium
            font.family: button.theme ? button.theme["font-ui"] : "sans-serif"
        }
        MouseArea { id: area; anchors.fill: parent; onClicked: button.pressed() }
    }
}
