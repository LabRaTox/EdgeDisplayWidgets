import QtQuick
import ".."

/* GPU: load, VRAM, temperature and power, curve. Says so when there is none. */
MetricWidget {
    id: root
    /** The module this widget listens to; nothing else reaches it. */
    readonly property var moduleNames: ["nvidia"]
    property var payload: null
    property var history: []

    heading: payload && payload.available && payload.name
             ? payload.name : bridge.tr("widget.gpu.title")
    maxValue: 100
    tickFormat: function (v) { return Math.round(v) + "%" }
    bigText: payload && payload.available ? Math.round(payload.gpu_percent) + "%" : "–"
    subText: {
        if (!payload) return "–"
        if (!payload.available) return payload.reason || bridge.tr("widget.gpu.no_nvidia")
        var gib = 1024 * 1024 * 1024
        var parts = [(payload.vram.used / gib).toFixed(1) + " / " + (payload.vram.total / gib).toFixed(1) + " GiB",
                     payload.temp_c + "°C"]
        if (payload.power_w !== null && payload.power_w !== undefined)
            parts.push(Math.round(payload.power_w) + " W")
        return parts.join(" • ")
    }
    series: [{ values: history, color: theme ? theme["accent"] : "#00e0ff" }]
    opacity: payload && !payload.available ? 0.55 : 1.0     // Dimmed when there is no card

    function receive(module, data) {
        payload = data
        noteArrival()
        if (!data || !data.available) return
        var h = history.slice()
        h.push(data.gpu_percent)
        if (h.length > 60) h.shift()
        history = h
    }
}
