import QtQuick
import ".."

/*
 * GPU: load, VRAM, temperature and power, curve, for one NVIDIA or AMD card.
 * Which card is the tile's `card` option; without one, the first dedicated
 * card the module found. Says so when there is none.
 */
MetricWidget {
    id: root
    /** The module this widget listens to; nothing else reaches it. */
    readonly property var moduleNames: ["gpu"]
    property var options: ({})
    property var payload: null
    property var history: []
    // The card the history belongs to; another card starts a new curve.
    property string historyCard: ""

    readonly property var card: {
        if (!payload || !payload.available || !payload.cards) return null
        var wanted = options && options.card ? options.card : payload.default
        for (var i = 0; i < payload.cards.length; i++)
            if (payload.cards[i].id === wanted) return payload.cards[i]
        return null
    }

    heading: card ? card.name : bridge.tr("widget.gpu.title")
    maxValue: 100
    tickFormat: function (v) { return Math.round(v) + "%" }
    bigText: card && card.gpu_percent !== null && card.gpu_percent !== undefined
             ? Math.round(card.gpu_percent) + "%" : "–"
    subText: {
        if (!payload) return "–"
        if (!payload.available) return payload.reason || bridge.tr("widget.gpu.no_gpu")
        if (!card) return bridge.tr("widget.gpu.card_missing")
        if (card.available === false) return card.reason || "–"
        var gib = 1024 * 1024 * 1024
        var parts = [(card.vram.used / gib).toFixed(1) + " / " + (card.vram.total / gib).toFixed(1) + " GiB"]
        if (card.temp_c !== null && card.temp_c !== undefined)
            parts.push(card.temp_c + "°C")
        if (card.power_w !== null && card.power_w !== undefined)
            parts.push(Math.round(card.power_w) + " W")
        return parts.join(" • ")
    }
    series: [{ values: history, color: theme ? theme["accent"] : "#00e0ff" }]
    opacity: card ? 1.0 : 0.55      // Dimmed when there is no card

    function receive(module, data) {
        payload = data
        noteArrival()
        var current = card
        if (!current || current.gpu_percent === null || current.gpu_percent === undefined) return
        var h = current.id === historyCard ? history.slice() : []
        historyCard = current.id
        h.push(current.gpu_percent)
        if (h.length > 60) h.shift()
        history = h
    }
}
