import QtQuick

/* A choice: a filter, a date, a tab. `on` marks the one that is chosen. */
Rectangle {
    id: chip
    property string label
    property bool on: false
    signal tapped

    implicitWidth: text.implicitWidth + 28
    implicitHeight: 36
    radius: Ui.pill(height)
    color: on ? Qt.alpha(Ui.accent, 0.2) : (press.pressed ? Ui.pressed : "transparent")
    border.width: on ? 0 : 1
    border.color: Ui.track

    Text {
        id: text
        anchors.centerIn: parent
        text: chip.label
        color: chip.on ? Ui.accent : Ui.fg
        font.pixelSize: 14
        font.weight: chip.on ? Font.DemiBold : Font.Normal
        font.family: Ui.font
    }

    MouseArea {
        id: press
        anchors.fill: parent
        anchors.margins: -4       // a chip is lower than a finger is wide
        onClicked: chip.tapped()
    }
}
