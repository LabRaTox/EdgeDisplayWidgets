import QtQuick

/*
 * The picture a theme lays behind the pages, one per page in turn, fading
 * from one to the next when the page changes. Still between changes, so it
 * costs nothing while the display just shows data. Two layers, so that the
 * old picture stays until the new one has loaded.
 */
Item {
    id: wall
    property var sources: []
    property int page: 0

    readonly property string wanted: sources && sources.length ? sources[page % sources.length] : ""
    property bool firstOnTop: true

    visible: wanted !== ""

    Component.onCompleted: first.source = wanted

    onWantedChanged: {
        if (wanted === "") return
        if (firstOnTop) second.source = wanted
        else first.source = wanted
        firstOnTop = !firstOnTop
    }

    Image {
        id: first
        anchors.fill: parent
        sourceSize: Qt.size(wall.width, wall.height)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        opacity: wall.firstOnTop && status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 450 } }
    }

    Image {
        id: second
        anchors.fill: parent
        sourceSize: Qt.size(wall.width, wall.height)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        opacity: !wall.firstOnTop && status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 450 } }
    }
}
