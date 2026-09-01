import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Quick Actions: a deck of touch tiles on a fixed columns x rows grid.
 * Tiles sit at explicit cell coordinates and whatever has none is flowed into
 * the free cells; anything that does not fit goes on a further page. A folder
 * tile opens its own level with a back tile.
 *
 * The deck is display only. It is arranged in the settings window, and what
 * that saves arrives here as a fresh payload.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["quick_actions"]
    property var payload: null
    property bool compact: false
    /** Set by the window: the shared confirm dialog. */
    property var confirm: null

    readonly property int gap: 8
    readonly property int minCell: 44

    property var actions: []
    property int columns: 4
    property int rows: 3
    property var path: []                          // folder ids down to the open level
    property int page: 0
    property int pages: 1
    property string key: ""
    property var folder: null

    function receive(module, data) {
        payload = data
        var list = (data && data.actions) || []
        var next = (data ? data.columns : 4) + "x" + (data ? data.rows : 3) + "|" + treeKey(list)
        if (next === key) return
        key = next
        actions = list
        columns = (data && data.columns) || 4
        rows = (data && data.rows) || 3
        rebuild()
    }

    /* The deck as a string, to tell a real change from an identical poll. */
    function treeKey(tiles) {
        var out = []
        for (var i = 0; i < (tiles || []).length; i++) {
            var a = tiles[i]
            var pos = a.page + "/" + a.x + "/" + a.y + "/" + a.w + "/" + a.h
            out.push(a.kind === "folder"
                ? "F:" + a.id + ":" + a.label + ":" + a.icon + ":" + a.color + ":"
                  + a.text_color + ":" + pos + ":" + a.back_x + "/" + a.back_y
                  + "(" + treeKey(a.tiles) + ")"
                : a.id + ":" + a.label + ":" + a.icon + ":" + a.confirm + ":" + a.color
                  + ":" + a.text_color + ":" + pos + ":" + a.state)
        }
        return out.join("|")
    }

    /* The tiles of the open level, and the folder they sit in. */
    function currentTiles() {
        var list = actions
        var open = null
        var valid = []
        for (var i = 0; i < path.length; i++) {
            var found = null
            for (var j = 0; j < list.length; j++)
                if (list[j].id === path[i] && list[j].kind === "folder") { found = list[j]; break }
            if (!found) break
            valid.push(path[i])
            open = found
            list = found.tiles || []
        }
        path = valid
        folder = open
        return list
    }

    /* Where the back tile sits in the open folder, clamped to the grid. */
    function backCell() {
        if (!folder) return null
        return {
            x: Math.min(Math.max(0, folder.back_x || 0), columns - 1),
            y: Math.min(Math.max(0, folder.back_y || 0), rows - 1)
        }
    }

    /*
     * Give every tile a concrete cell: honour the coordinates it carries,
     * then flow the rest into what is free. Reserved cells, which is the
     * folder's back tile, are blocked on every page.
     */
    function assignPlacements(tiles, cols, rowCount, reserved) {
        var grids = {}
        function ensure(p) {
            if (!grids[p]) {
                var g = []
                for (var y = 0; y < rowCount; y++) {
                    var line = []
                    for (var x = 0; x < cols; x++) line.push(false)
                    g.push(line)
                }
                for (var r = 0; r < reserved.length; r++) {
                    var c = reserved[r]
                    if (c.y >= 0 && c.y < rowCount && c.x >= 0 && c.x < cols) g[c.y][c.x] = true
                }
                grids[p] = g
            }
            return grids[p]
        }
        function span(v, max) { return Math.min(Math.max(1, v || 1), max) }
        function fits(g, x, y, w, h) {
            if (x + w > cols || y + h > rowCount) return false
            for (var j = y; j < y + h; j++)
                for (var i = x; i < x + w; i++)
                    if (g[j][i]) return false
            return true
        }
        function mark(g, x, y, w, h) {
            for (var j = y; j < y + h; j++)
                for (var i = x; i < x + w; i++) g[j][i] = true
        }
        function findFree(g, w, h) {
            for (var y = 0; y <= rowCount - h; y++)
                for (var x = 0; x <= cols - w; x++)
                    if (fits(g, x, y, w, h)) return { x: x, y: y }
            return null
        }
        function positioned(t) {
            return t.x !== undefined && t.x !== null && t.y !== undefined && t.y !== null
        }

        var out = []
        var i, t, w, h
        for (i = 0; i < tiles.length; i++) {
            t = tiles[i]
            if (!positioned(t)) continue
            w = span(t.w, cols); h = span(t.h, rowCount)
            var p = t.page || 0
            var g = ensure(p)
            var x = Math.max(0, Math.min(t.x, cols - w))
            var y = Math.max(0, Math.min(t.y, rowCount - h))
            if (!fits(g, x, y, w, h)) {
                var slot = findFree(g, w, h)
                if (slot) { x = slot.x; y = slot.y }
            }
            mark(g, x, y, w, h)
            out.push({ tile: t, page: p, x: x, y: y, w: w, h: h })
        }
        var flowPage = 0
        for (i = 0; i < tiles.length; i++) {
            t = tiles[i]
            if (positioned(t)) continue
            w = span(t.w, cols); h = span(t.h, rowCount)
            var free = null
            while (!(free = findFree(ensure(flowPage), w, h))) flowPage++
            mark(ensure(flowPage), free.x, free.y, w, h)
            out.push({ tile: t, page: flowPage, x: free.x, y: free.y, w: w, h: h })
        }
        var count = 1
        for (i = 0; i < out.length; i++) count = Math.max(count, out[i].page + 1)
        return { placements: out, pages: count }
    }

    function rebuild() {
        var tiles = currentTiles()
        var back = backCell()
        var result = assignPlacements(tiles, columns, rows, back ? [back] : [])
        pages = result.pages
        if (page >= pages) page = pages - 1
        if (page < 0) page = 0

        deck.clear()
        if (back)
            deck.append({ "isBack": true, "cellX": back.x, "cellY": back.y, "cellW": 1, "cellH": 1,
                          "actionId": "", "label": bridge.tr("widget.quick_actions.back"),
                          "icon": "ti:arrow-back-up", "colour": "", "textColour": "",
                          "isFolder": false, "needsConfirm": false, "state": "" })
        for (var i = 0; i < result.placements.length; i++) {
            var pl = result.placements[i]
            if (pl.page !== page) continue
            var t = pl.tile
            deck.append({
                "isBack": false,
                "cellX": pl.x, "cellY": pl.y, "cellW": pl.w, "cellH": pl.h,
                "actionId": String(t.id),
                "label": String(t.label || t.id),
                "icon": String(t.icon || ""),
                "colour": safeColour(t.color),
                "textColour": safeColour(t.text_color),
                "isFolder": t.kind === "folder",
                "needsConfirm": t.confirm === true,
                "state": t.has_status && (t.state === "on" || t.state === "off") ? t.state : ""
            })
        }
    }

    function safeColour(value) {
        return (typeof value === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value))
               ? value : ""
    }

    /* A reboot or a delete gets the red button in the confirm dialog. */
    function destructive(id, label) {
        return /reboot|shutdown|poweroff|restart|neustart|herunterfahren|delete|löschen/
               .test((id + " " + label).toLowerCase())
    }

    function descend(id) { path = path.concat([id]); page = 0; rebuild() }
    function ascend() { path = path.slice(0, -1); page = 0; rebuild() }
    function goto(next) {
        next = Math.min(Math.max(0, next), pages - 1)
        if (next === page) return
        page = next
        rebuild()
    }

    function run(id, label, needsConfirm, tile) {
        if (needsConfirm && confirm) {
            confirm.ask(bridge.tr("widget.quick_actions.run_confirm").replace("{label}", label),
                        bridge.tr("common.run"), destructive(id, label),
                        function (ok) { if (ok) fire(id, tile) })
            return
        }
        fire(id, tile)
    }

    function fire(id, tile) {
        tile.state = "pending"
        var xhr = new XMLHttpRequest()
        xhr.open("POST", bridge.api + "/api/quick_actions/" + encodeURIComponent(id) + "/run")
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            var body = {}
            try { body = JSON.parse(xhr.responseText) } catch (e) { body = {} }
            var ok = xhr.status >= 200 && xhr.status < 300 && body.ok === true
            tile.state = ok ? "ok" : "err"
            tile.flash.restart()
            // A tile with a live status shows what the run reported.
            if (body.state === "on" || body.state === "off") {
                key = ""                            // redraw even on an identical poll
                rebuild()
            }
        }
        xhr.send()
    }

    ListModel { id: deck }

    // The largest square cell that fits, with the grid centred.
    readonly property int cell: Math.max(minCell, Math.floor(Math.min(
        (area.width - (columns - 1) * gap) / columns,
        (area.height - (rows - 1) * gap) / rows)))
    readonly property int gridWidth: columns * cell + (columns - 1) * gap
    readonly property int gridHeight: rows * cell + (rows - 1) * gap

    ColumnLayout {
        anchors.fill: parent
        spacing: 6                                  // between deck and pager

        Item {
            id: area
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            // Shown in place of the deck
            Text {
                anchors.centerIn: parent
                visible: deck.count === 0
                text: bridge.tr("widget.quick_actions.empty")
                color: root.theme ? root.theme["fg-muted"] : "#888888"
                font.pixelSize: 20
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            }

            Item {
                width: root.gridWidth
                height: root.gridHeight
                anchors.centerIn: parent

                Repeater {
                    model: deck
                    delegate: Tile {
                        theme: root.theme
                        x: model.cellX * (root.cell + root.gap)
                        y: model.cellY * (root.cell + root.gap)
                        width: model.cellW * root.cell + (model.cellW - 1) * root.gap
                        height: model.cellH * root.cell + (model.cellH - 1) * root.gap
                        label: model.label
                        icon: model.icon
                        colour: model.colour
                        textColour: model.textColour
                        isBack: model.isBack
                        isFolder: model.isFolder
                        needsConfirm: model.needsConfirm
                        status: model.state

                        onActivated: {
                            if (isBack) root.ascend()
                            else if (isFolder) root.descend(model.actionId)
                            else root.run(model.actionId, model.label, model.needsConfirm, this)
                        }
                    }
                }
            }
        }

        /*
         * The pager. The strip keeps its 20 pixels even with a single page,
         * only its contents go away: the deck is sized against that height,
         * and letting it collapse would resize every tile as soon as a
         * second page appears.
         */
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 20
            spacing: 10

            Item { Layout.fillWidth: true }
            Arrow {
                visible: root.pages > 1
                theme: root.theme
                glyph: "‹"
                enabled: root.page > 0
                onPressed: root.goto(root.page - 1)
            }
            Row {                                   // the page dots
                visible: root.pages > 1
                spacing: 6
                Layout.alignment: Qt.AlignVCenter
                Repeater {
                    model: root.pages
                    Rectangle {
                        required property int index
                        width: 7
                        height: 7
                        radius: 3.5
                        anchors.verticalCenter: parent === null ? undefined : undefined
                        color: index === root.page ? (root.theme ? root.theme["accent"] : "#00e0ff")
                                                   : (root.theme ? root.theme["fg-muted"] : "#888888")
                        opacity: index === root.page ? 1 : 0.4
                        MouseArea { anchors.fill: parent; onClicked: root.goto(parent.index) }
                    }
                }
            }
            Arrow {
                visible: root.pages > 1
                theme: root.theme
                glyph: "›"
                enabled: root.page < root.pages - 1
                onPressed: root.goto(root.page + 1)
            }
            Item { Layout.fillWidth: true }
        }
    }

    // A pager arrow
    component Arrow: Text {
        property var theme
        property string glyph: ""
        signal pressed()
        text: glyph
        color: theme ? theme["fg-muted"] : "#888888"
        font.pixelSize: 24                          // 1.2rem
        opacity: enabled ? 1 : 0.3
        leftPadding: 4
        rightPadding: 4
        MouseArea {
            anchors.fill: parent
            enabled: parent.enabled
            onClicked: parent.pressed()
        }
    }

    // One tile
    component Tile: Rectangle {
        id: tile
        property var theme
        property string label: ""
        property string icon: ""
        property string colour: ""
        property string textColour: ""
        property bool isBack: false
        property bool isFolder: false
        property bool needsConfirm: false
        property string status: ""                  // "on", "off", or empty
        /** "pending", "ok", "err" while a run is in flight or just done. */
        property string state: ""
        property alias flash: flashTimer
        signal activated()

        readonly property color fg: textColour !== "" ? textColour
                                  : (theme ? theme["fg"] : "#e0e0e0")

        radius: 10
        color: colour !== "" ? colour
             : (isBack ? Qt.rgba(1, 1, 1, 0.02) : Qt.rgba(1, 1, 1, 0.04))
        border.width: 1
        border.color: state === "pending" ? (theme ? theme["warn"] : "#facc15")
                    : state === "ok" ? (theme ? theme["ok"] : "#4ade80")
                    : state === "err" ? (theme ? theme["bad"] : "#f87171")
                    : (theme ? theme["card-border"] : "#222222")
        opacity: isBack ? 0.85 : (state === "pending" ? 0.55 : 1)
        scale: touch.pressed ? 0.96 : 1
        clip: true
        Behavior on scale { NumberAnimation { duration: 80 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Timer { id: flashTimer; interval: 1800; onTriggered: tile.state = "" }

        // The back tile is drawn with a dashed outline.
        Canvas {
            anchors.fill: parent
            visible: tile.isBack
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = tile.theme ? tile.theme["card-border"] : "#222222"
                ctx.lineWidth = 1
                ctx.setLineDash([4, 4])
                ctx.beginPath()
                ctx.roundedRect(0.5, 0.5, width - 1, height - 1, 10, 10)
                ctx.stroke()
            }
        }

        // One tile-status
        Rectangle {
            visible: tile.status !== ""
            x: 6
            y: 5
            width: 9
            height: 9
            radius: 4.5
            color: tile.status === "on" ? (tile.theme ? tile.theme["ok"] : "#4ade80")
                                        : (tile.theme ? tile.theme["fg-muted"] : "#888888")
            opacity: tile.status === "on" ? 1 : 0.4
        }

        // One tile-folder-badge: the folded corner, bottom right
        Canvas {
            visible: tile.isFolder
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: 12
            height: 12
            opacity: 0.6
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.fillStyle = tile.theme ? tile.theme["accent"] : "#00e0ff"
                ctx.beginPath()
                ctx.moveTo(width, 0)
                ctx.lineTo(width, height)
                ctx.lineTo(0, height)
                ctx.closePath()
                ctx.fill()
            }
        }

        // The mark on a tile that asks first
        Text {
            visible: tile.needsConfirm
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 6
            anchors.topMargin: 4
            text: "!"
            color: tile.theme ? tile.theme["warn"] : "#facc15"
            font.pixelSize: 14                      // 0.7rem
            font.weight: Font.Bold
            opacity: 0.7
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 6                   // padding 8px 6px
            anchors.rightMargin: 6
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            spacing: 6

            Item { Layout.fillHeight: true }

            Item {                                  // One tile-icon
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: 38                   // 1.9rem
                implicitHeight: 38
                Image {
                    id: glyph
                    anchors.fill: parent
                    source: bridge.iconUrl(tile.icon, tile.fg)
                    sourceSize.width: 38
                    sourceSize.height: 38
                    fillMode: Image.PreserveAspectFit
                    visible: source != ""
                }
                Text {                              // emoji or plain text
                    anchors.centerIn: parent
                    visible: !glyph.visible
                    text: tile.icon !== "" ? tile.icon : (tile.isFolder ? "▸" : "•")
                    color: tile.fg
                    font.pixelSize: 38
                }
            }

            Text {                                  // One tile-label
                text: tile.label
                color: tile.fg
                font.pixelSize: 16                  // 0.8rem
                font.family: tile.theme ? tile.theme["font-ui"] : "sans-serif"
                lineHeight: 1.15
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Item { Layout.fillHeight: true }
        }

        MouseArea {
            id: touch
            anchors.fill: parent
            enabled: tile.state !== "pending"
            onClicked: tile.activated()
        }
    }
}
