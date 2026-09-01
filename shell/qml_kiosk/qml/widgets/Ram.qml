import QtQuick
import ".."

/*
 * RAM. Same shape as CPU and GPU: heading, load, details below.
 *
 * No name and no clock here: both live in the DMI tables, which only root may
 * read, so there is nothing to show. The temperature is the warmest DIMM the
 * sensors report.
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
        if (!data || !data.ram) return
        var h = history.slice()
        h.push(data.ram.percent)
        if (h.length > 60) h.shift()
        history = h
    }

    heading: "RAM"
    maxValue: 100
    tickFormat: function (v) { return Math.round(v) + "%" }
    bigText: payload && payload.ram ? Math.round(payload.ram.percent) + "%" : "–"
    subText: {
        if (!payload || !payload.ram) return "–"
        var gib = 1024 * 1024 * 1024
        var parts = [(payload.ram.used / gib).toFixed(1) + " / "
                     + (payload.ram.total / gib).toFixed(1) + " GiB"]
        var temp = Temperatures.forChip(sensors, "RAM")
        if (temp !== null) parts.push(Math.round(temp) + "°C")
        return parts.join(" • ")
    }
    series: [{ values: history, color: theme ? theme["accent"] : "#00e0ff" }]
}
