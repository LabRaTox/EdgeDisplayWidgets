import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Network: down and up as two figures, one above the other, and two curves
 * on a shared axis that rescales when traffic exceeds it.
 */
Item {
    id: root
    property var theme
    /** The module this widget listens to; nothing else reaches it. */
    readonly property var moduleNames: ["system"]
    property var payload: null
    property bool compact: false
    property var rxHistory: []
    property var txHistory: []
    property real ceiling: 1024 * 1024        // 1 MB/s to start with

    /*
     * Two formats: the figures show one decimal for kB/s, the axis none.
     * `768 kB/s` on the axis, `5.7 kB/s` above it.
     */
    function rate(bps) {
        if (bps >= 1048576) return (bps / 1048576).toFixed(1) + " MB/s"
        if (bps >= 1024) return (bps / 1024).toFixed(1) + " kB/s"
        return Math.round(bps) + " B/s"
    }
    function axisRate(bps) {
        if (bps >= 1048576) return (bps / 1048576).toFixed(1) + " MB/s"
        if (bps >= 1024) return (bps / 1024).toFixed(0) + " kB/s"
        return Math.round(bps) + " B/s"
    }

    function receive(module, data) {
        payload = data
        if (!data || !data.network) return
        var rx = data.network.rx_bytes_per_s
        var tx = data.network.tx_bytes_per_s
        var a = rxHistory.slice(); a.push(rx); if (a.length > 60) a.shift(); rxHistory = a
        var b = txHistory.slice(); b.push(tx); if (b.length > 60) b.shift(); txHistory = b
        var peak = Math.max(rx, tx)
        if (peak > ceiling * 0.9) ceiling = Math.max(peak * 1.5, ceiling)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Heading {
            theme: root.theme
            label: bridge.tr("widget.network.title")
            Layout.bottomMargin: Style.headingBottom
        }

        // The two rates, one below the other: 32px, line height 1.05, 2 apart
        ColumnLayout {
            spacing: 2
            Layout.fillWidth: true
            Layout.bottomMargin: Style.subBottom
            Text {
                text: "↓ " + root.rate(root.payload && root.payload.network
                                       ? root.payload.network.rx_bytes_per_s : 0)
                color: root.theme ? root.theme["accent"] : "#00e0ff"
                font.pixelSize: 32
                font.weight: Font.Medium
                lineHeight: 1.05
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
            Text {
                text: "↑ " + root.rate(root.payload && root.payload.network
                                       ? root.payload.network.tx_bytes_per_s : 0)
                color: root.theme ? root.theme["accent-2"] : "#ff4488"
                font.pixelSize: 32
                font.weight: Font.Medium
                lineHeight: 1.05
                font.family: root.theme ? root.theme["font-mono"] : "monospace"
            }
        }

        /*
         * Unloaded rather than hidden in the compact variant, as MetricWidget
         * does it: that is the whole point of the variant. Two canvases that
         * are not there paint nothing and hold no texture, while a hidden
         * pair still repaints on every sample.
         */
        Loader {
            active: !root.compact
            visible: active
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: active ? Style.chartMinHeight : 0
            sourceComponent: Chart {
                theme: root.theme
                maxValue: root.ceiling
                tickFormat: root.axisRate
                series: [
                    { values: root.rxHistory, color: root.theme ? root.theme["accent"] : "#00e0ff" },
                    { values: root.txHistory, color: root.theme ? root.theme["accent-2"] : "#ff4488" }
                ]
            }
        }
    }
}
