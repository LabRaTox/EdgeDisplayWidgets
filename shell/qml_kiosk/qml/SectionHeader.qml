import QtQuick

/* The heading of a group inside a tile. For the tile itself see Heading. */
Text {
    property bool alert: false

    color: alert ? Ui.bad : Ui.accent
    font.pixelSize: 13
    font.weight: Font.DemiBold
    font.letterSpacing: 0.8
    font.capitalization: Font.AllUppercase
    font.family: Ui.font
}
