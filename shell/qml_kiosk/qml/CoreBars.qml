import QtQuick

/*
 * Per-core load: one bar per core, a filled track each.
 *
 * All of them are painted into a single item. One item per core, each with an
 * animated height of its own, accounted for half of a memory growth of 50 MB
 * per minute, and the picture is the same either way.
 */
Canvas {
    id: bars
    property var theme
    property var values: []

    implicitHeight: Style.coreHeight
    renderStrategy: Canvas.Cooperative

    onValuesChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var n = values ? values.length : 0
        if (n === 0) return
        var gap = Style.coreGap
        var w = (width - gap * (n - 1)) / n
        var track = theme ? theme["card-border"] : "#20ffffff"
        var fill = theme ? theme["accent"] : "#00e0ff"
        var r = Style.coreRadius
        for (var i = 0; i < n; i++) {
            var x = i * (w + gap)
            var v = Math.max(0, Math.min(100, values[i])) / 100
            var h = Math.max(1, height * v)
            ctx.fillStyle = track
            ctx.beginPath(); ctx.roundedRect(x, 0, w, height, r, r); ctx.fill()
            ctx.fillStyle = fill
            ctx.beginPath(); ctx.roundedRect(x, height - h, w, h, r, r); ctx.fill()
        }
    }
}
