import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import ".."

/*
 * One or two hand-picked sensors, as a curve or as dials.
 *
 * The sensors list shows everything the machine reports; this is the opposite,
 * a tile for the two readings worth watching. Which two is a per-tile option,
 * so the same widget can sit on one page as the CPU package and on another as
 * the two NVMe drives.
 *
 * `line` follows the network widget: both readings on one shared axis, the
 * second in the contrast colour. `circle` puts them side by side as rings that
 * fill towards `max_c`, with the temperature in the middle.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["sensors"]
    property var payload: null
    property bool compact: false
    property var options: ({})

    readonly property string sensorA: (options && options.sensor_a) || ""
    readonly property string sensorB: (options && options.sensor_b) || ""
    /** "line" or "circle"; anything else reads as "line". */
    readonly property string display: (options && options.display) === "circle" ? "circle" : "line"
    /*
     * What a full ring means. The sensors themselves report no limit (`high`
     * and `critical` come back empty on this hardware), so a scale has to be
     * given rather than derived.
     */
    readonly property real maxC: (options && Number(options.max_c) > 0)
                                 ? Number(options.max_c) : 100
    /*
     * A name and a colour per sensor, both optional. Empty means "work it out
     * from the reading" and "use the theme's", so a tile that sets neither
     * takes its look entirely from the sensor and the theme.
     */
    readonly property string labelA: (options && options.label_a) || ""
    readonly property string labelB: (options && options.label_b) || ""
    readonly property string customA: safeColour(options && options.color_a)
    readonly property string customB: safeColour(options && options.color_b)
    /** The unit under the figure. Off leaves the bare number. */
    readonly property bool showUnit: !options || options.show_unit !== false

    /* Only `#rgb` and `#rrggbb` reach a colour property; anything else would
       throw when Qt tries to parse it, and a typo in a config should not take
       the tile down. Same rule as the quick actions tiles. */
    function safeColour(value) {
        return (typeof value === "string"
                && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value)) ? value : ""
    }

    /** The base colour of one reading: the chosen one, else the theme's. */
    function baseColor(custom, first) {
        if (custom !== "") return custom
        if (first) return theme ? theme["accent"] : "#00e0ff"
        return theme ? theme["accent-2"] : "#ff4488"
    }

    property var readingA: null
    property var readingB: null
    property var historyA: []
    property var historyB: []

    /*
     * A chosen colour replaces the normal one and nothing else: hot is still
     * yellow and then red, and below zero still stands out. Letting a colour
     * override those would turn a warning into a decoration.
     */
    function colorFor(temp, base) {
        if (temp === null || temp === undefined) return theme ? theme["fg-muted"] : "#888888"
        if (temp >= 85) return theme ? theme["bad"] : "#f87171"
        if (temp >= 70) return theme ? theme["warn"] : "#facc15"
        if (temp <= 0)  return theme ? theme["accent-2"] : "#ff4488"
        return base
    }

    /** The reading with this id, or null while it is not being reported. */
    function find(id) {
        if (!id || !payload || payload.available !== true) return null
        var list = payload.readings || []
        for (var i = 0; i < list.length; i++)
            if (String(list[i].id) === id) return list[i]
        return null
    }

    function nameOf(reading, custom) {
        if (custom) return custom
        if (!reading) return ""
        var chip = String(reading.display_chip || reading.chip || "")
        var label = String(reading.display_label || reading.label || "")
        return chip && label ? chip + " " + label : (chip || label)
    }

    /** The reading with its unit, or without it when the tile asked for that. */
    function figure(temp) {
        return temp.toFixed(1) + (showUnit ? "°C" : "")
    }

    function push(history, value) {
        var next = history.slice()
        next.push(value)
        if (next.length > 60) next.shift()
        return next
    }

    function receive(module, data) {
        payload = data
        readingA = find(sensorA)
        readingB = find(sensorB)
        if (readingA) historyA = push(historyA, readingA.temp_c)
        if (readingB) historyB = push(historyB, readingB.temp_c)
    }

    /*
     * A tile that was never given a sensor says so, rather than sitting there
     * empty and looking like a widget that failed to load.
     */
    readonly property string note: {
        if (sensorA === "" && sensorB === "") return bridge.tr("widget.sensor_focus.unset")
        if (!payload || payload.available !== true)
            return (payload && payload.reason) ? payload.reason : bridge.tr("common.unavailable")
        if (!readingA && !readingB) return bridge.tr("widget.sensor_focus.missing")
        return ""
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        /*
         * With a single sensor its name is the heading, the way the GPU widget
         * shows the card's name. With two there is no one name to use, and the
         * readings carry their own labels anyway.
         */
        Heading {
            theme: root.theme
            label: (root.readingA && !root.readingB) ? root.nameOf(root.readingA, root.labelA)
                 : (root.readingB && !root.readingA) ? root.nameOf(root.readingB, root.labelB)
                 : bridge.tr("widget.sensor_focus.title")
            Layout.bottomMargin: Style.headingBottom
        }

        Text {
            visible: root.note.length > 0
            text: root.note
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 17
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
            Layout.fillHeight: true
            verticalAlignment: Text.AlignVCenter
        }

        // ------------------------------------------------------------ line

        Loader {
            active: root.note === "" && root.display === "line"
            visible: active
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: ColumnLayout {
                spacing: 0

                // The readings, stacked as the network widget stacks its two rates.
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    Layout.bottomMargin: Style.subBottom
                    Repeater {
                        model: [{ reading: root.readingA, name: root.labelA,
                                  base: root.baseColor(root.customA, true) },
                                { reading: root.readingB, name: root.labelB,
                                  base: root.baseColor(root.customB, false) }]
                        RowLayout {
                            required property var modelData
                            visible: modelData.reading !== null
                            Layout.fillWidth: true
                            spacing: 10
                            Text {
                                text: root.nameOf(modelData.reading, modelData.name)
                                color: root.theme ? root.theme["fg-muted"] : "#888888"
                                font.pixelSize: 17
                                font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignBaseline
                            }
                            Text {
                                text: modelData.reading
                                      ? root.figure(modelData.reading.temp_c) : "–"
                                // The figure warns, the curve keeps its colour:
                                // a line that changes colour halfway through is
                                // harder to read than one that does not.
                                color: root.colorFor(modelData.reading
                                                     ? modelData.reading.temp_c : null,
                                                     modelData.base)
                                font.pixelSize: 32
                                font.weight: Font.Medium
                                lineHeight: 1.05
                                font.family: root.theme ? root.theme["font-mono"] : "monospace"
                                Layout.alignment: Qt.AlignBaseline
                            }
                        }
                    }
                }

                Chart {
                    theme: root.theme
                    maxValue: root.maxC
                    tickFormat: function (v) { return Math.round(v) + "°" }
                    series: [
                        { values: root.historyA, color: root.baseColor(root.customA, true) },
                        { values: root.historyB, color: root.baseColor(root.customB, false) }
                    ]
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: Style.chartMinHeight
                }
            }
        }

        // ---------------------------------------------------------- circle

        Loader {
            active: root.note === "" && root.display === "circle"
            visible: active
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: RowLayout {
                spacing: 16
                Repeater {
                    model: [{ reading: root.readingA, name: root.labelA,
                              base: root.baseColor(root.customA, true) },
                            { reading: root.readingB, name: root.labelB,
                              base: root.baseColor(root.customB, false) }]
                    Dial {
                        required property var modelData
                        visible: modelData.reading !== null
                        theme: root.theme
                        reading: modelData.reading
                        name: modelData.name
                        base: modelData.base
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                    }
                }
            }
        }
    }

    /*
     * One ring. Drawn with a Shape rather than a Canvas: an arc is geometry,
     * so it is re-rendered by the scene graph on a value change instead of
     * repainting a texture on the CPU.
     */
    component Dial: Item {
        id: dial
        property var theme
        property var reading: null
        /** The chosen name, empty for the one worked out from the reading. */
        property string name: ""
        property color base: "#00e0ff"

        readonly property real temp: reading ? reading.temp_c : 0
        readonly property real fraction: Math.max(0, Math.min(1, temp / root.maxC))
        readonly property color ink: root.colorFor(reading ? temp : null, base)
        // As large as the box allows, with room for the caption underneath.
        readonly property real side: Math.max(40, Math.min(width, height - caption.height - 8))
        readonly property real thickness: Math.max(6, side * 0.09)

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 8

            Item {
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: dial.side
                implicitHeight: dial.side

                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer

                    // The track: a full circle in the muted colour.
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(1, 1, 1, 0.08)
                        strokeWidth: dial.thickness
                        capStyle: ShapePath.FlatCap
                        PathAngleArc {
                            centerX: dial.side / 2
                            centerY: dial.side / 2
                            radiusX: (dial.side - dial.thickness) / 2
                            radiusY: (dial.side - dial.thickness) / 2
                            startAngle: -90
                            sweepAngle: 360
                        }
                    }

                    // The value, clockwise from the top.
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: dial.ink
                        strokeWidth: dial.thickness
                        capStyle: ShapePath.RoundCap
                        PathAngleArc {
                            id: arc
                            centerX: dial.side / 2
                            centerY: dial.side / 2
                            radiusX: (dial.side - dial.thickness) / 2
                            radiusY: (dial.side - dial.thickness) / 2
                            startAngle: -90
                            sweepAngle: dial.fraction * 360
                            Behavior on sweepAngle { NumberAnimation { duration: 300 } }
                        }
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 0
                    Text {
                        text: dial.reading ? dial.reading.temp_c.toFixed(1) : "–"
                        color: dial.theme ? dial.theme["fg"] : "#e0e0e0"
                        font.pixelSize: Math.max(18, Math.round(dial.side * 0.26))
                        font.weight: Font.Medium
                        font.family: dial.theme ? dial.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignHCenter
                    }
                    Text {
                        visible: root.showUnit
                        text: "°C"
                        color: dial.theme ? dial.theme["fg-muted"] : "#888888"
                        font.pixelSize: Math.max(11, Math.round(dial.side * 0.11))
                        font.family: dial.theme ? dial.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }

            Text {
                id: caption
                // With a single dial the name is already the heading.
                visible: root.readingA !== null && root.readingB !== null
                text: root.nameOf(dial.reading, dial.name).toUpperCase()
                color: dial.theme ? dial.theme["fg-muted"] : "#888888"
                font.pixelSize: 15
                font.letterSpacing: 1
                font.family: dial.theme ? dial.theme["font-ui"] : "sans-serif"
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: dial.width
            }
        }
    }
}
