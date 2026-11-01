import QtQuick

/* An icon in a colour: a Tabler name, or anything bridge.iconUrl takes. */
Image {
    property string name
    property color tint: Ui.fg
    property int size: 22

    source: name ? bridge.iconUrl(name.indexOf(":") >= 0 ? name : "ti:" + name, tint) : ""
    sourceSize: Qt.size(size, size)
    width: size
    height: size
}
