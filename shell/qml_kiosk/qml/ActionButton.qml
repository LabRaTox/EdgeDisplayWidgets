import QtQuick

/*
 * A button with a word on it. `filled` is for the one main action of a view,
 * in `fill`; the plain kind is for everything beside it, in `tint`.
 */
Rectangle {
    id: button
    property string label
    property string icon
    property bool filled: false
    property color fill: Ui.accent
    property color tint: filled ? Ui.onAccent : Ui.accent
    signal tapped

    implicitWidth: content.implicitWidth + 40
    implicitHeight: Ui.touch
    radius: Ui.pill(height)
    color: filled ? (press.pressed ? Qt.darker(fill, 1.2) : fill) : (press.pressed ? Ui.pressed : "transparent")
    opacity: enabled ? 1 : 0.4

    Row {
        id: content
        anchors.centerIn: parent
        spacing: 8
        Glyph {
            visible: button.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: button.icon
            tint: button.tint
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: button.label
            color: button.tint
            font.pixelSize: 15
            font.weight: Font.DemiBold
            font.family: Ui.font
        }
    }

    MouseArea {
        id: press
        anchors.fill: parent
        onClicked: button.tapped()
    }
}
