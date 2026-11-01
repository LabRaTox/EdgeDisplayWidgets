import QtQuick

/*
 * A surface inside a tile, with the theme's corners and colours. Set
 * `interactive` to make the whole card tappable.
 */
Rectangle {
    id: card
    property bool interactive: false
    signal tapped

    radius: Ui.corner
    color: press.pressed ? Ui.pressed : Ui.surface
    border.width: 1
    border.color: Ui.border

    MouseArea {
        id: press
        anchors.fill: parent
        enabled: card.interactive
        onClicked: card.tapped()
    }
}
