import QtQuick

/* A symbol to tap, with the room a finger needs around it. */
Rectangle {
    id: button
    property string icon
    property color tint: Ui.fg
    property int iconSize: 22
    property bool on: false
    signal tapped

    implicitWidth: Ui.touch
    implicitHeight: Ui.touch
    radius: Ui.pill(height)
    color: on || press.pressed ? Ui.pressed : "transparent"
    opacity: enabled ? 1 : 0.35

    Glyph { anchors.centerIn: parent; name: button.icon; tint: button.tint; size: button.iconSize }

    MouseArea {
        id: press
        anchors.fill: parent
        onClicked: button.tapped()
    }
}
