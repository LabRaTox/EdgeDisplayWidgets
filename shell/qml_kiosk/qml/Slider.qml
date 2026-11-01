import QtQuick

/*
 * A value from 0 to `maximum`, horizontal or `vertical`, as tall or wide as
 * it is given: the whole area reacts, not just the line.
 *
 * Under the finger it follows the finger and ignores `value`, which also
 * means a message arriving mid-drag does nothing, and for a moment after
 * letting go, while the answer to the last step is on its way. `shown` is
 * what it displays; bind a figure to that, not to your own value.
 *
 * `moved` fires at most every 70 ms during a drag, `finished` once at the end.
 */
Item {
    id: slider
    property int value: 0
    property int maximum: 100
    property bool vertical: false
    property bool dimmed: false
    signal moved(int value)
    signal finished(int value)

    property int dragged: 0
    readonly property bool held: pad.pressed || settling.running
    readonly property int shown: held ? dragged : value
    readonly property real share: Math.min(1, shown / maximum)

    implicitWidth: vertical ? Ui.touch : 200
    implicitHeight: vertical ? 200 : Ui.touch

    Rectangle {
        anchors.centerIn: parent
        width: slider.vertical ? 12 : parent.width
        height: slider.vertical ? parent.height : 12
        radius: Math.min(6, Ui.corner)
        color: Ui.track

        Rectangle {
            y: slider.vertical ? parent.height * (1 - slider.share) : 0
            width: slider.vertical ? parent.width : parent.width * slider.share
            height: slider.vertical ? parent.height * slider.share : parent.height
            radius: parent.radius
            color: slider.dimmed ? Ui.muted : Ui.accent
        }
    }

    Rectangle {
        width: 26
        height: 26
        radius: Ui.pill(height)
        color: slider.dimmed ? Ui.muted : Ui.accent
        border.width: 3
        border.color: Ui.bg
        x: slider.vertical ? (parent.width - width) / 2 : parent.width * slider.share - width / 2
        y: slider.vertical ? parent.height * (1 - slider.share) - height / 2 : (parent.height - height) / 2
    }

    Timer {
        id: pacing
        interval: 70
        onTriggered: slider.moved(slider.dragged)
    }

    Timer { id: settling; interval: 500 }

    MouseArea {
        id: pad
        anchors.fill: parent
        preventStealing: true

        function follow(mouse) {
            var part = slider.vertical ? 1 - mouse.y / height : mouse.x / width
            slider.dragged = Math.round(Math.max(0, Math.min(1, part)) * slider.maximum)
            if (!pacing.running) pacing.start()
        }

        onPressed: function (mouse) { follow(mouse) }
        onPositionChanged: function (mouse) { follow(mouse) }
        onReleased: {
            pacing.stop()
            settling.start()
            slider.finished(slider.dragged)
        }
    }
}
