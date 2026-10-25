import QtQuick
import QtQuick.Layouts
import QtCore
import ".."

/*
 * Notes in three columns: folders on the left, the notes of the chosen
 * folder in the middle with a search, the open note on the right with its
 * tools. Saved to the backend over its REST routes.
 *
 * Folders: "all notes", the built-in quick notes, the user's own folders
 * (a long press renames or deletes one), and two smart ones that filter
 * instead of holding: pinned, and changed today.
 *
 * Typing schedules a save 600 ms later; switching or deleting flushes first,
 * so a quick edit followed by a tap on another note is not lost.
 *
 * Narrower tiles drop the folder column first, then show either the list or
 * the open note, with a way back.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["notes"]
    property bool compact: false
    /** Set by the window: the shared confirm dialog. */
    property var confirm: null

    property var notes: []
    property var folders: []
    // "all", "quick", "pinned", "today" or a folder id.
    property string view: "all"
    property string activeId: ""
    property string search: ""
    property string status: ""
    property bool statusError: false
    // The folder whose name is being edited, "" when none.
    property string renaming: ""
    property string menu: ""                       // "palette", "move" or ""
    property point menuAt: Qt.point(0, 0)

    // Open a menu under its button; the right edge lines up with the button's.
    function toggleMenu(name, button) {
        if (menu === name) { menu = ""; return }
        menuAt = button.mapToItem(root, button.width, button.height + 6)
        menu = name
    }
    property bool editorInFront: false
    property double now: Date.now()

    // From the notes module: where the notes are kept, whether that store
    // answers, and a revision that goes up whenever the notes changed.
    property string storage: "local"
    property string storeState: "local"
    property string storeError: ""
    property int revision: -1
    readonly property bool joplin: storage === "joplin"
    readonly property bool joplinReady: !joplin || storeState === "connected"

    function receive(module, data) {
        var first = revision < 0
        var wasReady = joplinReady
        var otherStore = (data.storage || "local") !== storage
        var newRevision = data.revision !== revision
        storage = data.storage || "local"
        storeState = data.state || "local"
        storeError = data.error || ""
        revision = data.revision
        if (!joplinReady) return
        // The first answer only says where things are, the list is loaded
        // already. After that: something changed, Joplin answers again, or
        // the settings switched the store.
        if (otherStore || (!first && (newRevision || !wasReady))) refresh()
    }

    // Typing, or about to save: a reload must not swap the text under the cursor.
    function editing() {
        return pending !== null || titleField.activeFocus || bodyField.activeFocus
    }

    function joplinMessage() {
        if (storeError === "rejected") return bridge.tr("widget.notes.joplin_rejected")
        if (storeError === "timeout") return bridge.tr("widget.notes.joplin_timeout")
        if (storeState === "pairing") return bridge.tr("widget.notes.joplin_pairing")
        if (storeState === "needs_auth") return bridge.tr("widget.notes.joplin_needs_auth")
        return bridge.tr("widget.notes.joplin_offline")
    }

    readonly property int debounceMs: 600

    Settings {
        id: prefs
        category: "notes"
        property int textSize: 1
        // Folder colours as JSON, by view id ("all", "quick", a folder id).
        // A folder without an entry uses the theme's accent.
        property string folderTints: "{}"
    }

    readonly property bool showFolders: width >= 1100
    // The side columns grow with the tile, within limits.
    readonly property int folderWidth: Math.max(260, Math.min(400, width * 0.16))
    readonly property int listWidth: Math.max(340, Math.min(520, width * 0.24))
    readonly property bool narrow: width < 720
    readonly property bool showList: !narrow || !editorInFront
    readonly property bool showEditor: !narrow || editorInFront

    // -- colours --------------------------------------------------------------

    function themed(key, fallback) { return root.theme && root.theme[key] ? root.theme[key] : fallback }
    readonly property var tints: ["", "#f59e0b", "#facc15", "#34d399", "#38bdf8", "#a78bfa", "#f472b6"]
    property var folderTints: ({})
    Component.onCompleted: {
        try { folderTints = JSON.parse(prefs.folderTints) || {} } catch (e) { folderTints = {} }
        refresh()
    }

    function tintOf(which) {
        return folderTints[which] ? folderTints[which] : themed("accent", "#f59e0b")
    }

    function setTint(which, colour) {
        var next = Object.assign({}, folderTints)
        if (colour) next[which] = colour
        else delete next[which]
        folderTints = next
        prefs.folderTints = JSON.stringify(next)
    }

    // The whole tile takes the colour of the folder being shown.
    readonly property color accent: tintOf(view)
    readonly property color fg: themed("fg", "#e0e0e0")
    readonly property color muted: themed("fg-muted", "#888888")
    readonly property color border: themed("card-border", "#2a2a2a")
    readonly property string uiFont: themed("font-ui", "sans-serif")
    readonly property var sizes: [{ body: 17, title: 26 }, { body: 20, title: 30 }, { body: 24, title: 34 }]

    // -- what is shown --------------------------------------------------------

    function isToday(ms) {
        return new Date(ms * 1000).toDateString() === new Date(root.now).toDateString()
    }

    function inView(note, which) {
        if (which === "all") return true
        if (which === "pinned") return note.pinned
        if (which === "today") return isToday(note.updated_at)
        return note.folder === which
    }

    function count(which) {
        var n = 0
        for (var i = 0; i < notes.length; i++) if (inView(notes[i], which)) n++
        return n
    }

    readonly property var shown: {
        var needle = search.trim().toLowerCase()
        var out = []
        for (var i = 0; i < notes.length; i++) {
            var note = notes[i]
            if (!inView(note, view)) continue
            if (needle && (note.title + "\n" + note.body).toLowerCase().indexOf(needle) < 0) continue
            out.push(note)
        }
        out.sort(function (a, b) {
            if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
            return b.updated_at - a.updated_at
        })
        return out
    }

    function viewName(which) {
        var fixed = { all: "widget.notes.folder_all", quick: "widget.notes.folder_quick",
                      pinned: "widget.notes.folder_pinned", today: "widget.notes.folder_today" }
        if (fixed[which]) return bridge.tr(fixed[which])
        for (var i = 0; i < folders.length; i++) if (folders[i].id === which) return folders[i].name
        return ""
    }

    function activeNote() {
        for (var i = 0; i < notes.length; i++)
            if (notes[i].id === activeId) return notes[i]
        return null
    }

    function preview(body) {
        return body.replace(/\s+/g, " ").trim()
    }

    // Day and month names in the dashboard's language, not the system's.
    readonly property var locale: Qt.locale(bridge.tr("widget.notes.locale"))

    function stamp(seconds) {
        var minutes = Math.floor((root.now - seconds * 1000) / 60000)
        if (minutes < 1) return bridge.tr("widget.notes.just_now")
        if (minutes < 60) return bridge.tr("widget.notes.minutes").replace("{n}", minutes)
        var d = new Date(seconds * 1000)
        if (isToday(seconds)) return root.locale.toString(d, bridge.tr("widget.notes.time_format"))
        return root.locale.toString(d, bridge.tr("widget.notes.day_format"))
    }

    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.now = Date.now() }

    // -- talking to the backend ------------------------------------------------

    function request(method, path, body, done, fail) {
        var xhr = new XMLHttpRequest()
        xhr.open(method, bridge.api + path)
        if (body) xhr.setRequestHeader("Content-Type", "application/json")
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status >= 200 && xhr.status < 300) {
                var parsed = null
                try { parsed = JSON.parse(xhr.responseText) } catch (e) { parsed = null }
                if (done) done(parsed)
            } else if (fail) {
                fail(xhr.status, xhr.responseText)
            }
        }
        xhr.send(body ? JSON.stringify(body) : "")
    }

    function refresh() {
        request("GET", "/api/notes", null, function (data) {
            notes = (data && data.notes) || []
            folders = (data && data.folders) || []
            if (!activeNote()) activeId = shown.length > 0 ? shown[0].id : ""
            if (!editing()) showActive()
            if (statusError) setStatus("", false)
        }, function (code) {
            // Joplin not answering is shown by its own notice.
            if (code !== 503) setStatus(bridge.tr("widget.notes.load_failed"), true)
        })
    }

    function replaceNote(saved) {
        var list = notes.slice()
        var found = false
        for (var i = 0; i < list.length; i++)
            if (list[i].id === saved.id) { list[i] = saved; found = true }
        if (!found) list.push(saved)
        notes = list
    }

    function create() {
        flush()
        var folder = (view === "all" || view === "pinned" || view === "today") ? "" : view
        request("POST", "/api/notes", { title: "", body: "", folder: folder, pinned: view === "pinned" },
            function (note) {
                if (!note) return
                search = ""
                replaceNote(note)
                activeId = note.id
                editorInFront = true
                showActive()
                titleField.forceActiveFocus()
            },
            function () { setStatus(bridge.tr("widget.notes.create_failed"), true) })
    }

    function update(fields) {
        var note = activeNote()
        if (!note) return
        flush()
        var payload = { id: note.id, title: titleField.text, body: bodyField.text }
        for (var k in fields) payload[k] = fields[k]
        request("POST", "/api/notes", payload, function (saved) {
            if (saved) replaceNote(saved)
        }, function () { setStatus(bridge.tr("widget.notes.save_failed"), true) })
    }

    function remove(id) {
        if (!confirm || !id) return
        confirm.ask(bridge.tr("widget.notes.delete_confirm"), bridge.tr("common.delete"), true,
            function (ok) {
                if (!ok) return
                pending = null
                saveTimer.stop()
                var index = -1
                for (var i = 0; i < shown.length; i++) if (shown[i].id === id) index = i
                request("DELETE", "/api/notes/" + encodeURIComponent(id), null, function () {
                    notes = notes.filter(function (n) { return n.id !== id })
                    if (activeId === id) {
                        var next = shown.length > 0 ? shown[Math.min(Math.max(index, 0), shown.length - 1)] : null
                        activeId = next ? next.id : ""
                        if (!next) editorInFront = false
                    }
                    showActive()
                }, function () { setStatus(bridge.tr("widget.notes.delete_failed"), true) })
            })
    }

    function addFolder() {
        request("POST", "/api/notes/folders", { name: bridge.tr("widget.notes.new_folder") }, function (folder) {
            if (!folder) return
            folders = folders.concat([folder])
            view = folder.id
            renaming = folder.id
        }, function () { setStatus(bridge.tr("widget.notes.folder_failed"), true) })
    }

    function renameFolder(id, name) {
        renaming = ""
        name = name.trim()
        if (!name) return
        request("POST", "/api/notes/folders/" + encodeURIComponent(id), { name: name }, function (folder) {
            if (!folder) return
            folders = folders.map(function (f) { return f.id === folder.id ? folder : f })
        }, function () { setStatus(bridge.tr("widget.notes.folder_failed"), true) })
    }

    function deleteFolder(id) {
        if (!confirm) return
        confirm.ask(bridge.tr("widget.notes.delete_folder_confirm").replace("{name}", viewName(id)),
                    bridge.tr("common.delete"), true, function (ok) {
            if (!ok) return
            renaming = ""
            request("DELETE", "/api/notes/folders/" + encodeURIComponent(id), null, function () {
                folders = folders.filter(function (f) { return f.id !== id })
                notes = notes.map(function (n) {
                    if (n.folder !== id) return n
                    var copy = Object.assign({}, n); copy.folder = ""; return copy
                })
                if (view === id) view = "all"
                setTint(id, "")
            }, function () { setStatus(bridge.tr("widget.notes.folder_failed"), true) })
        })
    }

    // -- saving ---------------------------------------------------------------

    property var pending: null

    function schedule() {
        var note = activeNote()
        if (!note || loading) return
        pending = { id: note.id, title: titleField.text, body: bodyField.text }
        setStatus("…", false)
        saveTimer.restart()
    }

    function flush() {
        if (!pending) return
        var payload = pending
        pending = null
        saveTimer.stop()
        request("POST", "/api/notes", payload, function (saved) {
            if (!saved) return
            replaceNote(saved)
            setStatus("", false)
        }, function () { setStatus(bridge.tr("widget.notes.save_failed"), true) })
    }

    function setStatus(text, isError) { status = text; statusError = isError === true }

    function open(id) {
        menu = ""
        editorInFront = true
        if (id === activeId) return
        flush()
        activeId = id
        showActive()
    }

    function choose(which) {
        menu = ""
        if (which === view) return
        flush()
        view = which
        search = ""
        if (!activeNote() || !inView(activeNote(), which)) {
            activeId = shown.length > 0 ? shown[0].id : ""
            showActive()
        }
        editorInFront = false
    }

    /*
     * Put the open note into the fields, always: this runs when the note
     * being shown changes, never on a save coming back, so there is no
     * cursor to protect. `loading` keeps the writes from looking like typing:
     * assigning to a TextEdit fires onTextChanged just as a keypress does.
     */
    property bool loading: false
    function showActive() {
        var note = activeNote()
        loading = true
        titleField.text = note ? note.title : ""
        bodyField.text = note ? note.body : ""
        loading = false
    }

    // A checklist mark at the start of the line the cursor is in: none, open,
    // done, none again.
    function toggleCheck() {
        if (!activeNote()) return
        var text = bodyField.text
        var pos = bodyField.cursorPosition
        var start = text.lastIndexOf("\n", pos - 1) + 1
        var line = text.substring(start)
        var replaced, shift
        if (line.indexOf("☐ ") === 0) { replaced = "☑ "; shift = 0 }
        else if (line.indexOf("☑ ") === 0) { replaced = ""; shift = -2 }
        else { replaced = "☐ "; shift = 2 }
        var cut = (line.indexOf("☐ ") === 0 || line.indexOf("☑ ") === 0) ? 2 : 0
        bodyField.text = text.substring(0, start) + replaced + text.substring(start + cut)
        bodyField.cursorPosition = Math.max(start, pos + shift)
        bodyField.forceActiveFocus()
    }

    /*
     * A tap on a ☐ or ☑ at the start of a line ticks it, or unticks it.
     * Only a tap on the box itself counts; anywhere else the editor just
     * places the cursor, as before. Returns whether it ticked.
     */
    function tickAt(x, y) {
        if (!activeNote()) return false
        var text = bodyField.text
        var pos = bodyField.positionAt(x, y)
        var start = text.lastIndexOf("\n", pos - 1) + 1
        var box = text.charAt(start)
        if (box !== "☐" && box !== "☑") return false
        var left = bodyField.positionToRectangle(start)
        var right = bodyField.positionToRectangle(start + 1)
        // A little slack around the glyph: it is small for a finger.
        if (x > right.x + 8 || y < left.y - 4 || y > left.y + left.height + 4) return false
        var cursor = bodyField.cursorPosition
        bodyField.text = text.substring(0, start) + (box === "☐" ? "☑" : "☐") + text.substring(start + 1)
        bodyField.cursorPosition = Math.min(cursor, bodyField.text.length)
        return true
    }

    Timer { id: saveTimer; interval: root.debounceMs; onTriggered: root.flush() }

    // -- building blocks --------------------------------------------------------

    component Icon: Image {
        property string name
        property color tint: root.accent
        property int size: 20
        source: name ? bridge.iconUrl("ti:" + name, tint) : ""
        sourceSize.width: size
        sourceSize.height: size
        width: size
        height: size
    }

    component ToolButton: Rectangle {
        id: tool
        property string icon
        property color tint: root.accent
        property bool on: false
        signal tapped
        implicitWidth: 44
        implicitHeight: 44
        radius: 10
        color: on || press.pressed ? Qt.alpha(root.accent, 0.18) : "transparent"
        opacity: enabled ? 1 : 0.35
        Icon { anchors.centerIn: parent; name: tool.icon; tint: tool.tint; size: 22 }
        MouseArea { id: press; anchors.fill: parent; enabled: tool.enabled; onClicked: tool.tapped() }
    }

    component SectionLabel: RowLayout {
        property string label
        property string count: ""
        Layout.fillWidth: true
        Layout.topMargin: 12
        Layout.bottomMargin: 4
        Text {
            Layout.fillWidth: true
            text: parent.label.toUpperCase()
            color: root.muted
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.6
            font.family: root.uiFont
        }
        Text {
            visible: parent.count !== ""
            text: parent.count
            color: root.muted
            font.pixelSize: 13
            font.family: root.uiFont
        }
    }

    component FolderRow: Rectangle {
        id: row
        property string which
        property string icon
        property string label
        property bool editable: false
        readonly property bool selected: root.view === which
        readonly property bool editing: root.renaming === which && editable
        Layout.fillWidth: true
        implicitHeight: 48
        radius: 10
        color: selected ? Qt.alpha(root.accent, 0.2) : (press.pressed ? Qt.rgba(1, 1, 1, 0.05) : "transparent")

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            spacing: 12
            Icon { name: row.icon; size: 20; tint: root.tintOf(row.which) }
            Text {
                visible: !row.editing
                Layout.fillWidth: true
                text: row.label
                color: root.fg
                font.pixelSize: 17
                font.weight: row.selected ? Font.Medium : Font.Normal
                font.family: root.uiFont
                elide: Text.ElideRight
            }
            TextInput {
                id: nameInput
                visible: row.editing
                Layout.fillWidth: true
                text: row.label
                color: root.fg
                font.pixelSize: 17
                font.family: root.uiFont
                selectByMouse: true
                clip: true
                onVisibleChanged: if (visible) { text = row.label; forceActiveFocus(); selectAll() }
                onAccepted: root.renameFolder(row.which, text)
                onActiveFocusChanged: if (!activeFocus && row.editing) root.renameFolder(row.which, text)
                Keys.onEscapePressed: root.renaming = ""
            }
            Text {
                visible: !row.editing
                text: root.count(row.which)
                color: root.muted
                font.pixelSize: 14
                font.family: root.uiFont
            }
            ToolButton {
                visible: row.editing
                implicitWidth: 36
                implicitHeight: 36
                icon: "trash"
                tint: root.themed("bad", "#ef4444")
                onTapped: root.deleteFolder(row.which)
            }
        }
        MouseArea {
            id: press
            anchors.fill: parent
            enabled: !row.editing
            onClicked: root.choose(row.which)
            onPressAndHold: if (row.editable) root.renaming = row.which
        }
    }

    // -- layout ---------------------------------------------------------------

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // The folders.
        ColumnLayout {
            visible: root.showFolders
            Layout.fillWidth: false
            Layout.preferredWidth: root.folderWidth
            Layout.maximumWidth: root.folderWidth
            Layout.fillHeight: true
            Layout.rightMargin: 16
            spacing: 2

            Text {
                text: bridge.tr("widget.notes.folders")
                color: root.fg
                font.pixelSize: 30
                font.weight: Font.Bold
                font.family: root.uiFont
                Layout.bottomMargin: 8
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentHeight: folderColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                    id: folderColumn
                    width: parent.width
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        SectionLabel { label: bridge.tr("widget.notes.section_local") }
                        ToolButton {
                            implicitWidth: 36
                            implicitHeight: 36
                            Layout.topMargin: 8
                            icon: "folder-plus"
                            onTapped: root.addFolder()
                        }
                    }
                    FolderRow { which: "all"; icon: "file-text"; label: root.viewName("all") }
                    FolderRow { which: "quick"; icon: "notes"; label: root.viewName("quick") }
                    Repeater {
                        model: root.folders
                        delegate: FolderRow {
                            which: modelData.id
                            icon: "folder"
                            label: modelData.name
                            editable: true
                        }
                    }

                    SectionLabel { label: bridge.tr("widget.notes.section_smart") }
                    FolderRow { which: "pinned"; icon: "pin"; label: root.viewName("pinned") }
                    FolderRow { which: "today"; icon: "list-check"; label: root.viewName("today") }
                }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.border }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                spacing: 8
                Rectangle {
                    implicitWidth: 8
                    implicitHeight: 8
                    radius: 4
                    color: root.statusError ? root.themed("bad", "#ef4444") : root.themed("ok", "#22c55e")
                }
                Text {
                    Layout.fillWidth: true
                    text: root.statusError ? root.status
                          : bridge.tr(root.joplin ? "widget.notes.saved_joplin" : "widget.notes.saved_locally")
                    color: root.statusError ? root.themed("bad", "#ef4444") : root.muted
                    font.pixelSize: 13
                    font.family: root.uiFont
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle { visible: root.showFolders; Layout.fillHeight: true; implicitWidth: 1; color: root.border }

        // The notes of the folder.
        ColumnLayout {
            visible: root.showList
            Layout.fillWidth: root.narrow
            Layout.preferredWidth: root.narrow ? -1 : root.listWidth
            Layout.maximumWidth: root.narrow ? Number.POSITIVE_INFINITY : root.listWidth
            Layout.fillHeight: true
            Layout.leftMargin: root.showFolders ? 16 : 0
            Layout.rightMargin: root.narrow ? 0 : 16
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.viewName(root.view)
                    color: root.fg
                    font.pixelSize: 30
                    font.weight: Font.Bold
                    font.family: root.uiFont
                    elide: Text.ElideRight
                }
                ToolButton { icon: "edit"; onTapped: root.create() }
            }

            Rectangle {                                  // the search
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 10
                color: Qt.rgba(1, 1, 1, 0.06)
                border.width: searchInput.activeFocus ? 1 : 0
                border.color: root.accent
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 10
                    Icon { name: "search"; tint: root.muted; size: 18 }
                    TextInput {
                        id: searchInput
                        Layout.fillWidth: true
                        text: root.search
                        color: root.fg
                        font.pixelSize: 16
                        font.family: root.uiFont
                        clip: true
                        onTextEdited: root.search = text
                        Text {
                            visible: parent.text.length === 0
                            text: bridge.tr("widget.notes.search")
                            color: root.muted
                            font: parent.font
                        }
                    }
                }
            }

            // Joplin chosen, but not reachable or not connected yet.
            Rectangle {
                visible: !root.joplinReady
                Layout.fillWidth: true
                implicitHeight: joplinNotice.implicitHeight + 24
                radius: 10
                color: Qt.alpha(root.accent, 0.12)
                border.width: 1
                border.color: Qt.alpha(root.accent, 0.5)
                ColumnLayout {
                    id: joplinNotice
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10
                    Text {
                        Layout.fillWidth: true
                        text: root.joplinMessage()
                        color: root.fg
                        font.pixelSize: 15
                        font.family: root.uiFont
                        wrapMode: Text.WordWrap
                    }
                    Rectangle {
                        visible: root.storeState === "needs_auth"
                        implicitWidth: connectText.implicitWidth + 28
                        implicitHeight: 40
                        radius: 8
                        color: connectPress.pressed ? Qt.darker(root.accent, 1.2) : root.accent
                        Text {
                            id: connectText
                            anchors.centerIn: parent
                            text: bridge.tr("widget.notes.joplin_connect")
                            color: root.themed("bg", "#111214")
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            font.family: root.uiFont
                        }
                        MouseArea {
                            id: connectPress
                            anchors.fill: parent
                            onClicked: {
                                var xhr = new XMLHttpRequest()
                                xhr.open("POST", bridge.api + "/api/modules/notes/command/connect")
                                xhr.send()
                            }
                        }
                    }
                }
            }

            SectionLabel { label: bridge.tr("widget.notes.section_notes"); count: String(root.shown.length) }

            Text {
                visible: root.shown.length === 0
                Layout.fillWidth: true
                Layout.topMargin: 20
                text: root.search ? bridge.tr("widget.notes.no_match") : bridge.tr("widget.notes.empty")
                color: root.muted
                font.pixelSize: 16
                font.family: root.uiFont
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            ListView {
                id: noteList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                boundsBehavior: Flickable.StopAtBounds
                model: root.shown
                delegate: Rectangle {
                    id: card
                    width: noteList.width
                    implicitHeight: cardContent.implicitHeight + 22
                    radius: 12
                    readonly property bool selected: modelData.id === root.activeId
                    color: selected ? Qt.alpha(root.accent, 0.22) : (cardPress.pressed ? Qt.rgba(1, 1, 1, 0.05) : "transparent")

                    RowLayout {
                        id: cardContent
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 11
                        anchors.leftMargin: 14
                        spacing: 10
                        Icon {
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: 2
                            visible: modelData.pinned === true
                            name: "pin"
                            size: 18
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title || bridge.tr("widget.notes.untitled")
                                    color: root.fg
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                    font.family: root.uiFont
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: root.stamp(modelData.updated_at)
                                    color: root.muted
                                    font.pixelSize: 13
                                    font.family: root.uiFont
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: root.preview(modelData.body)
                                color: root.muted
                                font.pixelSize: 15
                                font.family: root.uiFont
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                    }
                    MouseArea { id: cardPress; anchors.fill: parent; onClicked: root.open(modelData.id) }
                }
            }
        }

        Rectangle { visible: root.showList && root.showEditor; Layout.fillHeight: true; implicitWidth: 1; color: root.border }

        // The open note.
        ColumnLayout {
            visible: root.showEditor
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: root.narrow ? 0 : 16
            spacing: 0

            RowLayout {                                  // the tools
                Layout.fillWidth: true
                spacing: 4
                ToolButton {
                    visible: root.narrow
                    icon: "arrow-left"
                    onTapped: { root.flush(); root.editorInFront = false }
                }
                ToolButton {
                    enabled: root.activeNote() !== null
                    icon: root.activeNote() && root.activeNote().pinned ? "pinned" : "pin"
                    on: root.activeNote() !== null && root.activeNote().pinned === true
                    onTapped: root.update({ pinned: !root.activeNote().pinned })
                }
                ToolButton {
                    enabled: root.activeNote() !== null
                    icon: "trash"
                    onTapped: root.remove(root.activeId)
                }
                Rectangle { implicitWidth: 1; implicitHeight: 24; color: root.border; Layout.leftMargin: 8; Layout.rightMargin: 8 }
                ToolButton {
                    icon: "text-size"
                    tint: root.fg
                    onTapped: prefs.textSize = (prefs.textSize + 1) % root.sizes.length
                }
                ToolButton {
                    enabled: root.activeNote() !== null
                    icon: "list-check"
                    tint: root.fg
                    onTapped: root.toggleCheck()
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: root.status !== "" && !root.statusError
                    text: root.status
                    color: root.muted
                    font.pixelSize: 14
                    font.family: root.uiFont
                }
                ToolButton {
                    id: paletteButton
                    icon: "palette"
                    on: root.menu === "palette"
                    onTapped: root.toggleMenu("palette", paletteButton)
                }
                ToolButton {
                    id: moveButton
                    enabled: root.activeNote() !== null
                    icon: "dots"
                    tint: root.fg
                    on: root.menu === "move"
                    onTapped: root.toggleMenu("move", moveButton)
                }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.border; Layout.topMargin: 8 }

            Text {
                visible: root.activeNote() === null
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: bridge.tr("widget.notes.nothing_open")
                color: root.muted
                font.pixelSize: 17
                font.family: root.uiFont
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap
            }

            Flickable {
                id: page
                visible: root.activeNote() !== null
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentHeight: pageColumn.implicitHeight + 40
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                    id: pageColumn
                    // A readable line length, centred, like the picture.
                    width: Math.min(page.width - 32, 760)
                    x: (page.width - width) / 2
                    y: 20
                    spacing: 10

                    Text {
                        Layout.fillWidth: true
                        text: root.activeNote()
                              ? root.locale.toString(new Date(root.activeNote().updated_at * 1000), bridge.tr("widget.notes.date_format"))
                              : ""
                        color: root.muted
                        font.pixelSize: 13
                        font.family: root.uiFont
                        horizontalAlignment: Text.AlignHCenter
                    }
                    TextEdit {
                        id: titleField
                        Layout.fillWidth: true
                        color: root.fg
                        font.pixelSize: root.sizes[prefs.textSize].title
                        font.weight: Font.Bold
                        font.family: root.uiFont
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        onTextChanged: root.schedule()
                        onActiveFocusChanged: if (!activeFocus) root.flush()
                        Keys.onReturnPressed: function (event) { bodyField.forceActiveFocus(); event.accepted = true }
                        Text {
                            visible: parent.text.length === 0
                            text: bridge.tr("widget.notes.title_placeholder")
                            color: root.muted
                            font: parent.font
                        }
                    }
                    TextEdit {
                        id: bodyField
                        Layout.fillWidth: true
                        Layout.minimumHeight: 200
                        color: root.fg
                        font.pixelSize: root.sizes[prefs.textSize].body
                        font.family: root.uiFont
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        onTextChanged: root.schedule()
                        onActiveFocusChanged: if (!activeFocus) root.flush()
                        TapHandler {
                            onTapped: function (point) { root.tickAt(point.position.x, point.position.y) }
                        }
                        Text {
                            visible: parent.text.length === 0
                            text: bridge.tr("widget.notes.body_placeholder")
                            color: root.muted
                            font: parent.font
                        }
                    }
                }
            }
        }
    }

    // -- menus ------------------------------------------------------------------

    MouseArea {                                      // a tap outside closes them
        anchors.fill: parent
        z: 9
        visible: root.menu !== ""
        onClicked: root.menu = ""
    }

    Rectangle {
        visible: root.menu === "palette"
        z: 10
        x: Math.max(0, root.menuAt.x - width)
        y: root.menuAt.y
        width: Math.max(paletteRow.implicitWidth, paletteTitle.implicitWidth) + 24
        height: 100
        radius: 12
        // Opaque: the card colour of most themes is see-through.
        color: Qt.lighter(root.themed("bg", "#111214"), 1.6)
        border.width: 1
        border.color: root.border
        Text {
            id: paletteTitle
            x: 12
            y: 12
            text: bridge.tr("widget.notes.folder_colour").replace("{name}", root.viewName(root.view)).toUpperCase()
            color: root.muted
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.family: root.uiFont
        }
        Row {
            id: paletteRow
            x: 12
            y: 44
            spacing: 10
            Repeater {
                model: root.tints
                delegate: Rectangle {
                    width: 36
                    height: 36
                    radius: 18
                    color: modelData !== "" ? modelData : root.themed("accent", "#f59e0b")
                    border.width: (root.folderTints[root.view] || "") === modelData ? 3 : 0
                    border.color: root.fg
                    MouseArea { anchors.fill: parent; onClicked: { root.setTint(root.view, modelData); root.menu = "" } }
                }
            }
        }
    }

    Rectangle {
        visible: root.menu === "move"
        z: 10
        x: Math.max(0, root.menuAt.x - width)
        y: root.menuAt.y
        width: 280
        height: Math.min(moveColumn.implicitHeight + 16, root.height - y - 8)
        radius: 12
        // Opaque: the card colour of most themes is see-through.
        color: Qt.lighter(root.themed("bg", "#111214"), 1.6)
        border.width: 1
        border.color: root.border
        clip: true
        Flickable {
            anchors.fill: parent
            anchors.margins: 8
            contentHeight: moveColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: moveColumn
                width: parent.width
                Text {
                    width: parent.width
                    leftPadding: 10
                    bottomPadding: 6
                    text: bridge.tr("widget.notes.move_to").toUpperCase()
                    color: root.muted
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    font.family: root.uiFont
                }
                Repeater {
                    // Joplin has no note outside a notebook.
                    model: (root.joplin ? [] : [{ id: "", name: bridge.tr("widget.notes.no_folder") }])
                           .concat([{ id: "quick", name: root.viewName("quick") }], root.folders)
                    delegate: Rectangle {
                        id: target
                        width: moveColumn.width
                        height: 44
                        radius: 8
                        readonly property bool current: root.activeNote() !== null && root.activeNote().folder === modelData.id
                        color: movePress.pressed ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            Text {
                                Layout.fillWidth: true
                                text: modelData.name
                                color: root.fg
                                font.pixelSize: 16
                                font.family: root.uiFont
                                elide: Text.ElideRight
                            }
                            Icon { visible: target.current; name: "check"; size: 18 }
                        }
                        MouseArea {
                            id: movePress
                            anchors.fill: parent
                            onClicked: { root.menu = ""; root.update({ folder: modelData.id }) }
                        }
                    }
                }
            }
        }
    }
}
