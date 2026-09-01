import QtQuick
import QtQuick.Layouts
import ".."

/*
 * YouTube: the configured videos and playlists as a thumbnail grid. A tap
 * opens the video in a player window that runs as its own process and is
 * gone again once it is closed.
 *
 * Anything playing over MPRIS is paused for the duration and picked up
 * again afterwards.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["youtube"]
    property var payload: null
    property bool compact: false

    property bool resumeMedia: false

    /*
     * The video window loads a page from the backend which then embeds the
     * player. Pointing it straight at the embed fails with error 153: the
     * player wants to sit on a page that has an origin, and the backend
     * serving the page is that origin.
     */
    function embedUrl(kind, id) {
        return bridge.api + "/player.html?kind=" + encodeURIComponent(kind)
             + "&id=" + encodeURIComponent(id)
    }

    /* The entries as a string, to tell a real change from an identical poll:
       without it the grid was thrown away and rebuilt on every payload, which
       reloaded every thumbnail and scrolled the deck back to the top. */
    property string key: ""

    function receive(module, data) {
        payload = data
        var list = (data && data.entries) || []
        var next = []
        for (var k = 0; k < list.length; k++) next.push(list[k].kind + ":" + list[k].id)
        next = next.join("|")
        if (next === key) return
        key = next

        entries.clear()
        for (var i = 0; i < list.length; i++) {
            var e = list[i]
            entries.append({
                "kind": String(e.kind || ""),
                "videoId": String(e.id || ""),
                "title": String(e.title || e.id || ""),
                "author": String(e.author || ""),
                "thumb": e.thumbnail ? String(e.thumbnail)
                       : (e.kind === "video"
                          ? "https://i.ytimg.com/vi/" + e.id + "/hqdefault.jpg" : "")
            })
        }
    }

    /* Pause whatever is playing, then hand the video to the player. */
    function open(kind, id) {
        var url = embedUrl(kind, id)
        var xhr = new XMLHttpRequest()
        xhr.open("GET", bridge.api + "/api/snapshot")
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            var media = null
            try { media = JSON.parse(xhr.responseText).media } catch (e) { media = null }
            var state = media && media.data ? media.data : media
            if (state && state.active && state.playback_status === "Playing") {
                resumeMedia = true
                post("/api/media/pause")
            }
            bridge.openVideo(url)
        }
        xhr.send()
    }

    function post(path) {
        var xhr = new XMLHttpRequest()
        xhr.open("POST", bridge.api + path)
        xhr.send()
    }

    Connections {
        target: bridge
        function onVideoClosed() {
            if (!root.resumeMedia) return
            root.resumeMedia = false
            root.post("/api/media/play")
        }
    }

    ListModel { id: entries }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: "YouTube"
            Layout.bottomMargin: Style.headingBottom
        }

        // Shown in place of the grid
        Text {
            visible: entries.count === 0
            text: bridge.tr("widget.youtube.empty")
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 20
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            padding: 8
            Layout.fillWidth: true
        }

        /*
         * As many columns as fit at 120 pixels each with an 8 pixel gap,
         * with the remainder spread over them.
         */
        GridView {
            id: grid
            visible: entries.count > 0
            model: entries
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            topMargin: 6                               // room under the heading
            Layout.fillWidth: true
            Layout.fillHeight: true

            readonly property int columns: Math.max(1, Math.floor((width + 8) / (120 + 8)))
            cellWidth: width / columns
            cellHeight: Math.round((cellWidth - 8) * 9 / 16) + 4 + metaHeight + 8

            /*
             * The tile is a 16:9 thumbnail plus the two lines under it. The
             * title is set on fixed 15 pixel lines, the second line is
             * measured on real text, because a 10 pixel font does not occupy
             * ten pixels of line.
             */
            Text {
                id: authorSize
                visible: false
                text: "Ag"
                font.pixelSize: 10
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            }
            readonly property int metaHeight: 4 + 2 * 15 + 2 + authorSize.implicitHeight + 6

            delegate: Item {
                width: grid.cellWidth
                height: grid.cellHeight

                Rectangle {                            // One entry
                    anchors.fill: parent
                    anchors.rightMargin: 8
                    anchors.bottomMargin: 8
                    radius: 6
                    clip: true
                    color: root.theme ? root.theme["card-bg"] : "#111111"
                    border.width: 1
                    border.color: press.pressed ? (root.theme ? root.theme["accent"] : "#00e0ff")
                                                : (root.theme ? root.theme["card-border"] : "#222222")
                    scale: press.pressed ? 0.98 : 1
                    Behavior on scale { NumberAnimation { duration: 80 } }

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4

                        Item {                          // its thumbnail
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.round(width * 9 / 16)
                            clip: true

                            Rectangle { anchors.fill: parent; color: "#000000" }
                            Image {
                                anchors.fill: parent
                                source: model.thumb
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                            }
                            Text {                      // shown when there is none
                                anchors.centerIn: parent
                                visible: model.thumb.length === 0
                                text: "▶"
                                color: root.theme ? root.theme["fg-muted"] : "#888888"
                                font.pixelSize: 24
                            }
                        }

                        ColumnLayout {                  // the caption block
                            Layout.fillWidth: true
                            Layout.leftMargin: 6
                            Layout.rightMargin: 6
                            Layout.bottomMargin: 6
                            spacing: 2

                            Text {                      // the title, two lines
                                text: model.title
                                color: root.theme ? root.theme["fg"] : "#e0e0e0"
                                font.pixelSize: 12
                                font.weight: Font.Medium
                                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                                lineHeight: 15               // line-height: 1.25 of 12px
                                lineHeightMode: Text.FixedHeight
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Rectangle {                 // the playlist badge
                                visible: model.kind === "playlist"
                                radius: 3
                                color: root.theme ? root.theme["accent"] : "#00e0ff"
                                implicitWidth: badge.implicitWidth + 8
                                implicitHeight: badge.implicitHeight + 2
                                Text {
                                    id: badge
                                    anchors.centerIn: parent
                                    text: bridge.tr("widget.youtube.playlist_badge").toUpperCase()
                                    color: root.theme ? root.theme["bg"] : "#0a0a0a"
                                    font.pixelSize: 9
                                    font.weight: Font.Bold
                                    font.letterSpacing: 0.5
                                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                                }
                            }
                            Text {                      // the channel
                                visible: model.kind !== "playlist" && model.author.length > 0
                                text: model.author
                                color: root.theme ? root.theme["fg-muted"] : "#888888"
                                font.pixelSize: 10
                                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    MouseArea {
                        id: press
                        anchors.fill: parent
                        onClicked: root.open(model.kind, model.videoId)
                    }
                }
            }
        }
    }
}
