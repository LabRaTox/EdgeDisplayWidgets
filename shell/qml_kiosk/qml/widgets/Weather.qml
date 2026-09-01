import QtQuick
import QtQuick.Layouts
import ".."

/*
 * Weather: the current reading on the left, condition and range beside it,
 * the next 24 hours as a strip along the bottom.
 *
 * The glyph table follows open-meteo's WMO code list, with a night variant
 * for the codes where it matters. The labels come from the locale file, so
 * the strings stay in one place.
 */
Item {
    id: root
    property var theme
    readonly property var moduleNames: ["weather"]
    property var payload: null
    property bool compact: false
    // Its own inset: 16 by 18
    readonly property int padH: 18
    readonly property int padV: 16

    readonly property bool ok: payload && payload.available === true
    property int staleAge: 0

    /*
     * The five signs below carry a variation selector (\uFE0F). Without it Qt
     * picks the monochrome glyph from a text font instead of the colour
     * emoji, so half the strip came out dark.
     */
    readonly property var codeMap: ({
        "0":  { day: "☀\uFE0F",  night: "🌙" },
        "1":  { day: "🌤", night: "🌙" },
        "2":  { day: "⛅\uFE0F", night: "☁\uFE0F"  },
        "3":  { day: "☁\uFE0F",  night: "☁\uFE0F"  },
        "45": { day: "🌫", night: "🌫" },
        "48": { day: "🌫", night: "🌫" },
        "51": { day: "🌦", night: "🌧" },
        "53": { day: "🌦", night: "🌧" },
        "55": { day: "🌧", night: "🌧" },
        "56": { day: "🌨", night: "🌨" },
        "57": { day: "🌨", night: "🌨" },
        "61": { day: "🌦", night: "🌧" },
        "63": { day: "🌧", night: "🌧" },
        "65": { day: "🌧", night: "🌧" },
        "66": { day: "🌨", night: "🌨" },
        "67": { day: "🌨", night: "🌨" },
        "71": { day: "🌨", night: "🌨" },
        "73": { day: "❄\uFE0F",  night: "❄\uFE0F"  },
        "75": { day: "❄\uFE0F",  night: "❄\uFE0F"  },
        "77": { day: "🌨", night: "🌨" },
        "80": { day: "🌦", night: "🌧" },
        "81": { day: "🌧", night: "🌧" },
        "82": { day: "⛈\uFE0F", night: "⛈\uFE0F"  },
        "85": { day: "🌨", night: "🌨" },
        "86": { day: "❄\uFE0F",  night: "❄\uFE0F"  },
        "95": { day: "⛈\uFE0F", night: "⛈\uFE0F"  },
        "96": { day: "⛈\uFE0F", night: "⛈\uFE0F"  },
        "99": { day: "⛈\uFE0F", night: "⛈\uFE0F"  }
    })

    function glyph(code, isDay) {
        var e = codeMap[String(Number(code))]
        if (!e) return "·"
        return isDay ? e.day : e.night
    }
    function label(code) {
        var e = codeMap[String(Number(code))]
        if (!e) return "–"
        return bridge.tr("widget.weather.code." + Number(code))
    }
    function temp(value, unit) {
        if (value === undefined || value === null || isNaN(value)) return "–"
        return Math.round(value) + (unit || "°")
    }
    function hourOf(iso) {
        if (!iso) return ""
        var m = String(iso).match(/T(\d{2}):/)
        return m ? m[1] : iso
    }
    function ageText(seconds) {
        if (seconds < 60)
            return bridge.tr("widget.weather.age_seconds").replace("{value}", seconds)
        if (seconds < 3600)
            return bridge.tr("widget.weather.age_minutes").replace("{value}", Math.round(seconds / 60))
        return bridge.tr("widget.weather.age_hours").replace("{value}", Math.round(seconds / 3600))
    }

    function receive(module, data) {
        payload = data
        hourModel.clear()
        if (!data || data.available !== true) return
        refreshAge()

        var hourly = data.hourly || {}
        var times = hourly.time || []
        var temps = hourly.temperature || []
        var codes = hourly.weather_code || []
        var probs = hourly.precipitation_probability || []
        var unit = (data.units && data.units.temperature) || "°C"

        // Start at the current hour: the forecast reaches back a little.
        anyRain = false
        var now = Date.now()
        var start = 0
        for (var i = 0; i < times.length; i++) {
            var ts = Date.parse(times[i])
            if (!isNaN(ts) && ts >= now - 30 * 60000) { start = i; break }
        }
        for (var j = start; j < Math.min(start + 24, times.length); j++) {
            hourModel.append({
                "time": hourOf(times[j]),
                "icon": glyph(codes[j], true),
                "temp": temp(temps[j], unit),
                "rain": probs[j] !== undefined && probs[j] !== null && probs[j] > 0
                        ? Math.round(probs[j]) + "%" : ""
            })
            if (probs[j] > 0) anyRain = true
        }
        // A model that was cleared can leave the view scrolled where it was.
        hours.positionViewAtBeginning()
    }

    function refreshAge() {
        if (!payload || !payload.stale || !payload.fetched_at) return
        staleAge = Math.max(0, Math.round(Date.now() / 1000 - payload.fetched_at))
    }

    ListModel { id: hourModel }
    /** True as soon as one hour carries a chance of rain: the extra line
        makes every box taller, because they all share one height. */
    property bool anyRain: false

    /*
     * The strip is as tall as one box needs, measured on real text rather than
     * assumed: a 14 pixel font does not occupy 14 pixels of line, and the sum
     * of the guessed numbers was off by several pixels.
     */
    Item {
        id: sizer
        visible: false
        ColumnLayout {
            id: sizerCol
            spacing: 2
            Text { text: "00"; font.pixelSize: 14
                   font.family: root.theme ? root.theme["font-mono"] : "monospace" }
            Text { text: "☀\uFE0F"; font.pixelSize: 24; Layout.preferredHeight: 24 }
            Text { text: "00°C"; font.pixelSize: 16
                   font.family: root.theme ? root.theme["font-mono"] : "monospace" }
            Text { visible: root.anyRain; text: "00%"; font.pixelSize: 13
                   font.family: root.theme ? root.theme["font-mono"] : "monospace" }
        }
    }
    readonly property int rowHeight: sizerCol.implicitHeight + 12   // padding 6px top/bottom

    Timer {
        interval: 30000
        running: true
        repeat: true
        onTriggered: root.refreshAge()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        // The location
        Text {
            visible: text.length > 0
            text: root.ok && root.payload.location && root.payload.location.name
                  ? String(root.payload.location.name).toUpperCase() : ""
            color: root.theme ? root.theme["fg-muted"] : "#888888"
            font.pixelSize: 15                     // 0.75rem
            font.letterSpacing: 1.8                // 0.12em
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
            elide: Text.ElideRight
            Layout.fillWidth: true
            Layout.bottomMargin: 2                 // under the location
        }

        // The current reading
        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            RowLayout {                            // glyph and temperature
                spacing: 12
                Text {
                    text: root.ok ? root.glyph(root.payload.current.weather_code,
                                               root.payload.current.is_day !== false) : "·"
                    color: root.theme ? root.theme["fg"] : "#e0e0e0"
                    font.pixelSize: 64             // 3.2rem
                    lineHeight: 1
                }
                Text {
                    text: root.ok ? root.temp(root.payload.current.temperature,
                                              root.payload.units.temperature) : "–"
                    color: root.theme ? root.theme["accent"] : "#00e0ff"
                    font.pixelSize: 56             // 2.8rem
                    font.weight: Font.Light
                    lineHeight: 1
                    font.family: root.theme ? root.theme["font-mono"] : "monospace"
                }
            }

            ColumnLayout {                         // condition, felt temperature, range
                spacing: 2
                Layout.fillWidth: true
                Text {
                    text: root.ok ? root.label(root.payload.current.weather_code)
                                  : (root.payload && root.payload.error
                                     ? root.payload.error : bridge.tr("common.unavailable"))
                    color: root.theme ? root.theme["fg"] : "#e0e0e0"
                    font.pixelSize: 20             // 1rem
                    font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    text: {
                        if (!root.ok || root.payload.current.apparent_temperature === null
                            || root.payload.current.apparent_temperature === undefined) return ""
                        return bridge.tr("widget.weather.feels_like").replace(
                            "{temp}", root.temp(root.payload.current.apparent_temperature,
                                                root.payload.units.temperature))
                    }
                    color: root.theme ? root.theme["fg-muted"] : "#888888"
                    font.pixelSize: 16             // 0.8rem
                    font.family: root.theme ? root.theme["font-mono"] : "monospace"
                }
                RowLayout {                        // the day's range
                    spacing: 12
                    Layout.topMargin: 4
                    Text {
                        text: "↑ " + (root.ok && root.payload.daily
                                      ? root.temp(root.payload.daily.temperature_max[0],
                                                  root.payload.units.temperature) : "–")
                        color: root.theme ? root.theme["accent"] : "#00e0ff"
                        font.pixelSize: 17         // 0.85rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    }
                    Text {
                        text: "↓ " + (root.ok && root.payload.daily
                                      ? root.temp(root.payload.daily.temperature_min[0],
                                                  root.payload.units.temperature) : "–")
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 17
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                    }
                }
            }
        }

        // Shown when the forecast is old
        Text {
            visible: root.ok && root.payload.stale === true
            text: bridge.tr("widget.weather.stale") + " " + root.ageText(root.staleAge)
            color: root.theme ? root.theme["warn"] : "#ffaa00"
            font.pixelSize: 14                     // 0.7rem
            font.letterSpacing: 0.7                // 0.05em
            font.family: root.theme ? root.theme["font-ui"] : "sans-serif"
        }

        Item { Layout.fillHeight: true }           // margin-top: auto on the strip

        // The hourly strip, flickable because the panel is a touchscreen
        ListView {
            id: hours
            visible: !root.compact
            model: hourModel
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Layout.fillWidth: true
            Layout.preferredHeight: root.rowHeight

            delegate: Rectangle {                  // one hour
                width: Math.max(48, col.implicitWidth + 16)
                height: root.rowHeight
                radius: 6
                color: Qt.rgba(1, 1, 1, 0.025)

                ColumnLayout {
                    id: col
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 2
                    Text {
                        text: model.time
                        color: root.theme ? root.theme["fg-muted"] : "#888888"
                        font.pixelSize: 14         // 0.7rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignHCenter
                    }
                    Text {
                        text: model.icon
                        color: root.theme ? root.theme["fg"] : "#e0e0e0"
                        font.pixelSize: 24         // 1.2rem
                        // line-height 1: the row is 24 pixels whatever the
                        // glyph brings with it, so the temperatures line up.
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        Layout.preferredHeight: 24
                        Layout.alignment: Qt.AlignHCenter
                    }
                    Text {
                        text: model.temp
                        color: root.theme ? root.theme["fg"] : "#e0e0e0"
                        font.pixelSize: 16         // 0.8rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignHCenter
                    }
                    Text {
                        visible: model.rain.length > 0
                        text: model.rain
                        color: root.theme ? root.theme["accent"] : "#00e0ff"
                        font.pixelSize: 13         // 0.65rem
                        font.family: root.theme ? root.theme["font-mono"] : "monospace"
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }
        }
    }
}
