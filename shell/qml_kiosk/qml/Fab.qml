import QtQuick

/*
 * The one thing a view is there for, floating over it: the round button in
 * the corner of a tile. Anchor it yourself, and leave room under a list so
 * its last row can scroll out from beneath.
 */
Rectangle {
    id: button
    property string icon: "plus"
    signal tapped

    implicitWidth: 56
    implicitHeight: 56
    radius: Math.min(Ui.corner * 1.5, width / 3)
    color: press.pressed ? Qt.darker(Ui.accent, 1.2) : Ui.accent

    Glyph { anchors.centerIn: parent; name: button.icon; tint: Ui.onAccent; size: 26 }

    MouseArea {
        id: press
        anchors.fill: parent
        onClicked: button.tapped()
    }
}
