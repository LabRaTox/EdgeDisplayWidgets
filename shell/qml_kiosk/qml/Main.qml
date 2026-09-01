import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

/*
 * The dashboard window.
 *
 * A page is a GridLayout built from the same `grid.columns` / `grid.rows` the
 * settings window writes, and a widget sits at its `col`/`row` with its
 * `colspan`/`rowspan`. The translation of the CSS track list happens in
 * bridge.py; from here on the layout model is the config's, unchanged.
 */
ApplicationWindow {
    id: win
    visible: true
    width: 2560
    height: 720
    color: theme ? theme["bg"] : "#0a0a0a"
    title: "Edge Dashboard"
    /*
     * No decoration: this is a display, not a window anyone moves around.
     *
     * Qt.Tool is what keeps it out of the task list and Alt+Tab, but only on
     * X11, where it becomes _NET_WM_WINDOW_TYPE_UTILITY. Wayland has no window
     * types, so there the same job needs a compositor rule, which is what
     * scripts/window-rule.sh writes.
     */
    flags: Qt.Tool | Qt.FramelessWindowHint

    readonly property var theme: bridge.theme
    /*
     * `--gap` is a theme variable, not a constant: the default is 8 pixels and
     * the clean theme raises it to 12. Reading it here keeps the page margin
     * and the space between tiles right for every theme.
     */
    readonly property int gap: theme && theme["gap"] ? parseInt(theme["gap"]) : Style.pageGap

    /*
     * The pages are rebuilt from scratch whenever the layout changes, rather
     * than left to follow the model.
     *
     * A Repeater inside a SwipeView lays the pages out correctly once, but it
     * does not survive a model reset: after the settings window saves, the
     * new page items are no longer positioned by the view and every page ends
     * up stacked on top of the first one. Recreating the view sidesteps that,
     * and costs nothing worth counting, because it only happens on a save.
     */
    Loader {
        id: deck
        anchors.fill: parent
        sourceComponent: pagesComponent
        /** The page that was open, to return to it after the rebuild. */
        property int wanted: 0
        onLoaded: item.currentIndex = Math.max(0, Math.min(wanted, item.count - 1))
    }

    Connections {
        target: bridge
        function onPagesChanged() {
            deck.wanted = deck.item ? deck.item.currentIndex : 0;
            deck.sourceComponent = null;
            deck.sourceComponent = pagesComponent;
        }
    }

    Component {
        id: pagesComponent

        SwipeView {
            id: swipe
            anchors.fill: parent

            Repeater {
                model: bridge.pages

                Item {
                    id: pageItem
                    required property var modelData
                    readonly property var page: modelData

                    GridLayout {
                        anchors.fill: parent
                        /*
                         * The inset sits on each page rather than on the view,
                         * so two pages keep their distance while one is being
                         * dragged in. On the view the pages would touch during
                         * a swipe and the incoming tiles look glued to the
                         * outgoing ones.
                         */
                        anchors.margins: win.gap
                        columns: pageItem.page.columns.length
                        columnSpacing: win.gap
                        rowSpacing: win.gap

                        Repeater {
                            model: pageItem.page.widgets

                            Tile {
                                id: tile
                                required property var modelData
                                readonly property var track: pageItem.page.rows[modelData.row - 1]
                                readonly property bool compact: modelData.variant === "compact"

                                theme: win.theme

                                Layout.column: modelData.col - 1
                                Layout.row: modelData.row - 1
                                Layout.columnSpan: modelData.colspan
                                Layout.rowSpan: modelData.rowspan
                                Layout.fillWidth: true
                                // A row given a pixel size keeps it, the rest share
                                // what is left: that is `32px 1fr 1fr`.
                                Layout.fillHeight: !track || track.fixed === 0
                                Layout.preferredHeight: track && track.fixed > 0 ? track.fixed : -1

                                Loader {
                                    id: loader
                                    anchors.fill: parent

                                    /*
                                   * Each widget is handed only the modules it
                                   * asked for, and decides itself what to do
                                   * with each. Routing everything through one
                                   * shared object instead made every widget
                                   * recompute on every foreign frame, so tiles
                                   * updated five times a second for data that
                                   * arrives once.
                                   */
                                    Connections {
                                        target: bridge
                                        enabled: loader.item !== null && typeof loader.item.receive === "function"
                                        function onDataArrived(module, data) {
                                            if (loader.item.moduleNames.indexOf(module) >= 0)
                                                loader.item.receive(module, data);
                                        }
                                    }

                                    /*
                                     * The file is found by name, not by a
                                     * table: `disk_usage` is `DiskUsage.qml`
                                     * (see Bridge.viewUrl). A new widget
                                     * therefore needs no entry here.
                                     */
                                    source: bridge.viewUrl(tile.modelData.id)

                                    /*
                                     * No file for this id. It says which of
                                     * the two cases it is, because they need
                                     * different fixes and look identical on
                                     * the display otherwise: a widget that
                                     * still has to be written, or a tile the
                                     * layout editor saved without an id,
                                     * which is broken config and not a layout
                                     * gap. An empty tile is never intentional,
                                     * so it is never silently left blank.
                                     */
                                    Heading {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        visible: loader.source == ""
                                        theme: win.theme
                                        label: tile.modelData.id === "" ? "Kachel ohne Widget" : "kein Widget: " + tile.modelData.id
                                    }

                                    onLoaded: {
                                        item.theme = Qt.binding(function () {
                                            return win.theme;
                                        });
                                        // Bound, not assigned: the heartbeat
                                        // strip has to follow the connection.
                                        if (item.hasOwnProperty("online"))
                                            item.online = Qt.binding(function () {
                                                return bridge.online;
                                            });
                                        if (item.hasOwnProperty("compact"))
                                            item.compact = tile.compact;
                                        if (item.hasOwnProperty("confirm"))
                                            item.confirm = ask;
                                        if (item.hasOwnProperty("options"))
                                            item.options = tile.modelData.options;
                                        /*
                                       * A widget may ask for its own inset. Which
                                       * of the two applies is the tile's decision,
                                       * because it depends on the tile's size (see
                                       * Tile.insetV), and that is not known yet at
                                       * this point: the layout runs later.
                                       */
                                        if (item.hasOwnProperty("padH"))
                                            tile.widgetPadH = item.padH;
                                        if (item.hasOwnProperty("padV"))
                                            tile.widgetPadV = item.padV;
                                        // Whatever arrived before this tile existed.
                                        if (typeof item.receive === "function") {
                                            for (var i = 0; i < item.moduleNames.length; i++) {
                                                var m = item.moduleNames[i];
                                                var cached = bridge.cached(m);
                                                if (cached)
                                                    item.receive(m, cached);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    /* One confirm dialog for the whole window, handed to any widget that
       declares a `confirm` property. */
    Confirm {
        id: ask
        anchors.fill: parent
        theme: win.theme
        z: 100
    }

    /*
     * The scanline overlay four of the themes lay over the whole page with
     * `body::after`. One thin line every three pixels, drawn once: they never
     * move, so the scene graph batches them into a single node and they cost
     * nothing per frame.
     *
     * The stylesheets blend them with `screen`, which on these dark grounds
     * is close enough to painting them normally at the same alpha.
     */
    Repeater {
        model: bridge.effects.scanline_color !== "" ? Math.ceil(win.height / bridge.effects.scanline_period) : 0
        Rectangle {
            required property int index
            z: 200
            x: 0
            y: index * bridge.effects.scanline_period
            width: win.width
            height: bridge.effects.scanline_thickness
            color: bridge.effects.scanline_color
        }
    }

    PageIndicator {
        // `swipe` lives inside the component now, so the dots read the view
        // through the loader and fall back to nothing while it is rebuilding.
        count: deck.item ? deck.item.count : 0
        currentIndex: deck.item ? deck.item.currentIndex : 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 4
    }
}
