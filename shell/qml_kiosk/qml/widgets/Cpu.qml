import QtQuick
import ".."

/*
 * CPU. Laid out like the GPU widget: the processor's name as the heading, the
 * load beside it, and the details in the line below, temperature included.
 */
MetricWidget {
    id: root
    readonly property var moduleNames: ["system", "sensors"]
    property var payload: null
    property var sensors: null
    property var history: []

    function receive(module, data) {
        if (module === "sensors") { sensors = data; return }
        payload = data
        noteArrival()
        if (!data || !data.cpu) return
        var h = history.slice()
        h.push(data.cpu.percent)
        if (h.length > 60) h.shift()
        history = h
    }

    heading: payload && payload.cpu && payload.cpu.model ? payload.cpu.model : "CPU"
    maxValue: 100
    tickFormat: function (v) { return Math.round(v) + "%" }
    bigText: payload && payload.cpu ? Math.round(payload.cpu.percent) + "%" : "–"
    subText: {
        if (!payload || !payload.cpu) return "–"
        var parts = [payload.cpu.count + " " + bridge.tr("widget.cpu.cores")]
        if (payload.cpu.freq_mhz) parts.push((payload.cpu.freq_mhz / 1000).toFixed(2) + " GHz")
        var temp = Temperatures.forChip(sensors, "CPU")
        if (temp !== null) parts.push(Math.round(temp) + "°C")
        return parts.join(" • ")
    }
    series: [{ values: history, color: theme ? theme["accent"] : "#00e0ff" }]

    CoreBars {
        theme: root.theme
        values: root.payload && root.payload.cpu ? root.payload.cpu.per_core : []
        width: parent ? parent.width : 0
        y: Style.coreTop
    }
}
