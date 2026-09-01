import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Notes: tabs across the top, title and body underneath, saved to the
 * backend over its REST routes.
 *
 * Typing schedules a save 600 ms later; switching or deleting flushes first,
 * so a quick edit followed by a tap on another tab is not lost.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: []
    property bool compact: false
    /** Set by the window: the shared confirm dialog. */
    property var confirm: null

    property var notes: []
    property string activeId: ""
    property string status: ""
    property bool statusError: false

    readonly property int debounceMs: 600

    function activeNote() {
        for (var i = 0; i < notes.length; i++)
            if (notes[i].id === activeId) return notes[i]
        return null
    }

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
                fail(xhr.status)
            }
        }
        xhr.send(body ? JSON.stringify(body) : "")
    }

    function refresh() {
        request("GET", "/api/notes", null, function (data) {
            notes = (data && data.notes) || []
            if (notes.length === 0) { create(bridge.tr("widget.notes.new_note"), ""); return }
            if (!activeNote()) activeId = notes[0].id
            showActive()
        }, function () {
            setStatus(bridge.tr("widget.notes.load_failed"), true)
        })
    }

    function create(title, body) {
        request("POST", "/api/notes", { title: title || bridge.tr("widget.notes.new_note"),
                                        body: body || "" },
            function (note) {
                if (!note) return
                var list = notes.slice(); list.push(note); notes = list
                activeId = note.id
                showActive()
                titleField.forceActiveFocus()
                titleField.selectAll()
            },
            function () { setStatus(bridge.tr("widget.notes.create_failed"), true) })
    }

    function remove(id) {
        if (!confirm) return
        confirm.ask(bridge.tr("widget.notes.delete_confirm"), bridge.tr("common.delete"), true,
            function (ok) {
                if (!ok) return
                request("DELETE", "/api/notes/" + encodeURIComponent(id), null, function () {
                    var list = []
                    for (var i = 0; i < notes.length; i++)
                        if (notes[i].id !== id) list.push(notes[i])
                    notes = list
                    if (activeId === id) activeId = list.length > 0 ? list[0].id : ""
                    if (list.length === 0) { create(bridge.tr("widget.notes.new_note"), ""); return }
                    showActive()
                }, function () { setStatus(bridge.tr("widget.notes.delete_failed"), true) })
            })
    }

    // ------------------------------------------------------------ saving

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
            var list = notes.slice()
            for (var i = 0; i < list.length; i++)
                if (list[i].id === saved.id) list[i] = saved
            notes = list
            setStatus(bridge.tr("common.saved"), false)
        }, function () { setStatus(bridge.tr("widget.notes.save_failed"), true) })
    }

    function setStatus(text, isError) { status = text; statusError = isError === true }

    function switchTo(id) {
        if (id === activeId) return
        flush()
        activeId = id
        showActive()
    }

    /*
     * Put the open note into the fields, always: this runs when the note
     * being shown changes, never on a save coming back, so there is no
     * cursor to protect. Skipping a focused field was worse than useless:
     * tapping another tab does not take the focus out of a TextEdit, so the
     * old text stayed on screen and the next keystroke saved it over the note
     * that had just been opened.
     *
     * `loading` keeps the writes below from looking like typing: assigning to
     * a TextEdit fires onTextChanged just as a keypress does, and without the
     * flag every tab switch would schedule a save.
     */
    property bool loading: false
    function showActive() {
        var note = activeNote()
        loading = true
        titleField.text = note ? note.title : ""
        bodyField.text = note ? note.body : ""
        loading = false
    }

    Timer { id: saveTimer; interval: root.debounceMs; onTriggered: root.flush() }
    Component.onCompleted: refresh()

    ColumnLayout {
        anchors.fill: parent
        spacing: 6                                  // between the parts

        // The tab strip
        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            Flow {
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: root.notes
                    Tab {
                        theme: root.theme
                        label: modelData.title || bridge.tr("widget.notes.untitled")
                        active: modelData.id === root.activeId
                        onPressed: root.switchTo(modelData.id)
                    }
                }
                Tab {                               // the plus
                    theme: root.theme
                    label: "+"
                    plain: true
                    textColor: root.theme ? root.theme["accent"] : "#00e0ff"
                    onPressed: { root.flush(); root.create() }
                }
            }
            Tab {                                   // the cross, pushed to the right
                theme: root.theme
                label: "×"
                plain: true
                textColor: root.theme ? root.theme["bad"] : "#f87171"
                visible: root.activeId !== ""
                Layout.alignment: Qt.AlignTop
                onPressed: root.remove(root.activeId)
            }
        }

        // The note itself
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 4

            Field {                                 // its title
                id: titleField
                theme: root.theme
                placeholder: bridge.tr("widget.notes.title_placeholder")
                fontSize: 19                        // 0.95rem
                fontWeight: Font.Medium
                Layout.fillWidth: true
                onEdited: root.schedule()
                onBlurred: root.flush()
            }

            Field {                                 // its body
                id: bodyField
                theme: root.theme
                placeholder: bridge.tr("widget.notes.body_placeholder")
                fontSize: 18                        // 0.9rem
                mono: true
                multiline: true
                padH: 10
                padV: 8
                Layout.fillWidth: true
                Layout.fillHeight: true
                onEdited: root.schedule()
                onBlurred: root.flush()
            }

            // The save state
            Text {
                text: root.status
                color: root.statusError ? (root.theme ? root.theme["bad"] : "#f87171")
                                        : (root.theme ? root.theme["fg-muted"] : "#888888")
                font.pixelSize: 14                  // 0.7rem
                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                horizontalAlignment: Text.AlignRight
                Layout.fillWidth: true
                Layout.preferredHeight: 18          // min-height 0.9rem
            }
        }
    }

    /* A tab, in its three shapes: a note, the plus, the cross. */
    component Tab: Rectangle {
        id: tab
        property var theme
        property string label: ""
        property bool active: false
        property bool plain: false
        property color textColor: theme ? theme["fg-muted"] : "#888888"
        signal pressed()

        implicitWidth: Math.max(plain ? 32 : 0, Math.min(140, caption.implicitWidth + 20))
        implicitHeight: Math.max(28, caption.implicitHeight + 8)
        radius: 14
        color: active ? (theme ? theme["accent"] : "#00e0ff")
                      : (plain ? "transparent" : Qt.rgba(1, 1, 1, 0.04))
        border.width: 1
        border.color: active ? (theme ? theme["accent"] : "#00e0ff")
                             : (theme ? theme["card-border"] : "#222222")

        Text {
            id: caption
            anchors.centerIn: parent
            width: Math.min(implicitWidth, tab.width - 20)
            text: tab.label
            color: tab.active ? (tab.theme ? tab.theme["bg"] : "#0a0a0a") : tab.textColor
            font.pixelSize: tab.plain ? 20 : 17     // 1rem / 0.85rem
            font.weight: tab.plain ? Font.DemiBold : Font.Normal
            font.family: tab.theme ? tab.theme["font-ui"] : "sans-serif"
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        MouseArea { anchors.fill: parent; onClicked: tab.pressed() }
    }

    /* Title and body: the same box, one line or many. */
    component Field: Rectangle {
        id: field
        property var theme
        property string placeholder: ""
        property alias text: input.text
        property int fontSize: 19
        property int fontWeight: Font.Normal
        property bool mono: false
        property bool multiline: false
        property int padH: 8
        property int padV: 6
        signal edited()
        signal blurred()   // not "left": that name is taken by the anchor line

        implicitHeight: multiline ? 0 : input.implicitHeight + 2 * padV + 2
        color: Qt.rgba(0, 0, 0, 0.2)
        border.width: 1
        border.color: input.activeFocus ? (theme ? theme["accent"] : "#00e0ff")
                                        : (theme ? theme["card-border"] : "#222222")
        radius: 4
        clip: true

        Flickable {
            anchors.fill: parent
            anchors.leftMargin: field.padH
            anchors.rightMargin: field.padH
            anchors.topMargin: field.padV
            anchors.bottomMargin: field.padV
            contentWidth: width
            contentHeight: input.contentHeight
            interactive: field.multiline
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            TextEdit {
                id: input
                width: parent.width
                color: field.theme ? field.theme["fg"] : "#e0e0e0"
                font.pixelSize: field.fontSize
                font.weight: field.fontWeight
                font.family: field.mono ? (field.theme ? field.theme["font-mono"] : "monospace")
                                        : (field.theme ? field.theme["font-ui"] : "sans-serif")
                // A wider line spacing would suit the body, but Qt's editor
                // has no such setting (only the read-only Text has), so it
                // keeps the font's own.
                wrapMode: field.multiline ? TextEdit.Wrap : TextEdit.NoWrap
                selectByMouse: true
                onTextChanged: field.edited()
                onActiveFocusChanged: if (!activeFocus) field.blurred()
                Keys.onReturnPressed: function (event) {
                    if (field.multiline) event.accepted = false
                    else { focus = false; event.accepted = true }
                }
            }
        }

        Text {
            visible: input.text.length === 0
            x: field.padH
            y: field.padV
            text: field.placeholder
            color: field.theme ? field.theme["fg-muted"] : "#888888"
            font.pixelSize: field.fontSize
            font.family: input.font.family
        }
    }
}
