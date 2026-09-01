import QtQuick

/*
 * The sparkline: axis, grid lines and one curve per series.
 *
 * Five grid lines at 0/25/50/75/100 percent in the muted colour at 28
 * percent, a 1.5 pixel curve, and the area under it filled with the same
 * colour at 15 percent. The newest sample sits at the right edge and the
 * left stays empty until the buffer has filled.
 *
 * Between samples the whole curve can slide left by exactly one sample width,
 * so the picture moves at the speed the data arrives instead of jumping. That
 * is a transform in the scene graph, which is what the GPU does anyway, but it
 * is off by default: see `travel`.
 */
Item {
    id: chart
    property var theme
    property int samples: 60
    property real maxValue: 100
    property var series: []              // [{ values: [], color: c }]
    property var tickFormat: function (v) { return Math.round(v) + "" }
    /*
     * Off: the curve steps once per sample. Sliding costs nothing measurable
     * here, but a picture that moves continuously is restless to sit next to
     * on a panel that is on all day. Set to true to get it back.
     */
    property bool travel: false
    /** Measured gap between samples, so the speed follows the module's interval. */
    property int gapMs: 1000

    implicitHeight: Style.chartMinHeight

    readonly property int ticks: Style.chartTicks
    readonly property color gridColor: {
        var base = theme ? theme["fg-muted"] : "#888888"
        return Qt.rgba(Qt.color(base).r, Qt.color(base).g, Qt.color(base).b, 0.28)
    }

    Item {
        id: axis
        // As wide as the widest label, never below the minimum. Measuring
        // only the maximum value is not enough: with data rates the middle
        // label ("388.2 kB/s") is longer than the top one ("1.3 MB/s").
        width: Math.max(Style.axisWidth, measure.widest)
        height: parent.height

        Repeater {
            model: chart.ticks
            Text {
                required property int index
                text: chart.tickFormat(chart.maxValue * (chart.ticks - 1 - index) / (chart.ticks - 1))
                color: chart.theme ? chart.theme["fg-muted"] : "#888888"
                font.pixelSize: Style.axisSize
                font.family: chart.theme ? chart.theme["font-mono"] : "monospace"
                width: axis.width
                horizontalAlignment: Text.AlignRight
                y: index * (axis.height - height) / (chart.ticks - 1)
            }
        }
    }

    Item {
        id: measure
        visible: false
        property real widest: 0
        function update() {
            var w = 0
            for (var i = 0; i < probes.count; i++) {
                // itemAt is null while the repeater is still building.
                var probe = probes.itemAt(i)
                if (probe) w = Math.max(w, probe.width)
            }
            widest = w
        }
        Repeater {
            id: probes
            model: chart.ticks
            Text {
                required property int index
                text: chart.tickFormat(chart.maxValue * (chart.ticks - 1 - index)
                                       / (chart.ticks - 1))
                font.pixelSize: Style.axisSize
                font.family: chart.theme ? chart.theme["font-mono"] : "monospace"
                onWidthChanged: measure.update()
                Component.onCompleted: measure.update()
            }
        }
    }

    Item {
        id: plot
        anchors.left: axis.right
        anchors.leftMargin: Style.axisGap
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        clip: true

        // The grid, drawn once and only repainted on a resize or theme change.
        Canvas {
            id: grid
            anchors.fill: parent
            renderStrategy: Canvas.Cooperative
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = chart.gridColor
                ctx.lineWidth = 1
                for (var i = 0; i < chart.ticks; i++) {
                    // Half a pixel, so a one pixel line lands on the pixel
                    // instead of being spread over two.
                    var y = Math.round(i * (height - 1) / (chart.ticks - 1)) + 0.5
                    ctx.beginPath()
                    ctx.moveTo(0, y)
                    ctx.lineTo(width, y)
                    ctx.stroke()
                }
            }
            Component.onCompleted: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            Connections {
                target: chart
                // `parent` inside Connections is not the canvas; address it.
                function onGridColorChanged() { grid.requestPaint() }
            }
        }

        Canvas {
            id: curves
            // One sample wider than the plot, so sliding left never uncovers
            // an empty strip on the right.
            width: parent.width + stepX
            height: parent.height
            renderStrategy: Canvas.Cooperative

            readonly property real stepX: parent.width / (chart.samples - 1)
            property real offset: 0
            transform: Translate { x: -curves.offset }

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                for (var s = 0; s < chart.series.length; s++) {
                    var entry = chart.series[s]
                    var values = entry.values || []
                    if (values.length < 2) continue
                    var colour = Qt.color(entry.color)
                    var start = chart.samples - values.length
                    var xFor = function (i) { return (start + i) * stepX }
                    var yFor = function (v) {
                        var c = Math.max(0, Math.min(chart.maxValue, v))
                        return height - (c / (chart.maxValue || 1)) * height
                    }

                    ctx.beginPath()
                    ctx.moveTo(xFor(0), yFor(values[0]))
                    for (var i = 1; i < values.length; i++) ctx.lineTo(xFor(i), yFor(values[i]))
                    ctx.lineWidth = 1.5
                    ctx.strokeStyle = colour
                    ctx.stroke()

                    // Area under the curve.
                    ctx.lineTo(xFor(values.length - 1), height)
                    ctx.lineTo(xFor(0), height)
                    ctx.closePath()
                    ctx.fillStyle = Qt.rgba(colour.r, colour.g, colour.b, 0.15)
                    ctx.fill()
                }
            }

            NumberAnimation {
                id: slide
                target: curves
                property: "offset"
                from: 0
                to: curves.stepX
                duration: chart.gapMs
                easing.type: Easing.Linear
            }

            function advance() {
                requestPaint()
                if (!chart.travel) { offset = 0; return }
                slide.stop()
                offset = 0
                slide.start()
            }
        }
    }

    onSeriesChanged: curves.advance()
    onMaxValueChanged: curves.requestPaint()
}
