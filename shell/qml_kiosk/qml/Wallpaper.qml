import QtQuick
import QtQuick.Window

/*
 * The picture a theme lays behind the pages, one per page in turn, fading
 * from one to the next when the page changes. Still between changes, so it
 * costs nothing while the display just shows data.
 *
 * Two layers. The one underneath stays fully opaque, and only the new one on
 * top fades in, once it has loaded. Fading both at once would let the
 * background colour show through halfway, and fading out before the new one
 * is decoded would show nothing at all for a moment.
 */
Item {
    id: wall
    property var sources: []
    property int page: 0

    readonly property string wanted: sources && sources.length ? sources[page % sources.length] : ""
    // The layer that shows the current picture, or will once it has loaded.
    property Image front: first

    visible: wanted !== ""

    function show(url) {
        if (url === "") {
            // A theme without pictures: let both go rather than keep two
            // full-screen images decoded for nothing.
            first.source = ""
            second.source = ""
            return
        }
        if (front.source.toString() === url) return
        var incoming = front === first ? second : first
        fade.stop()
        front.opacity = 1
        front.z = 0
        incoming.z = 1
        incoming.opacity = 0
        incoming.source = url
        front = incoming
        // Already decoded (the same picture as before): no status change
        // will come, so start the fade here.
        if (incoming.status === Image.Ready) fade.restart()
    }

    onWantedChanged: show(wanted)
    Component.onCompleted: show(wanted)

    NumberAnimation {
        id: fade
        target: wall.front
        property: "opacity"
        to: 1
        duration: 450
    }

    // In device pixels, so a scaled output gets a sharp picture. Rounded up
    // to whole pixels and never zero: a zero size would decode at full size.
    readonly property size decodeSize: Qt.size(
        Math.max(1, Math.ceil(width * Screen.devicePixelRatio)),
        Math.max(1, Math.ceil(height * Screen.devicePixelRatio)))

    Image {
        id: first
        anchors.fill: parent
        sourceSize: wall.decodeSize
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        onStatusChanged: if (status === Image.Ready && wall.front === first) fade.restart()
    }

    Image {
        id: second
        anchors.fill: parent
        sourceSize: wall.decodeSize
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        opacity: 0
        onStatusChanged: if (status === Image.Ready && wall.front === second) fade.restart()
    }
}
