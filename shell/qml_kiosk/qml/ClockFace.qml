import QtQuick

/*
 * One clock, analog or digital, drawn into whatever box it gets. The clock
 * and the world clock both use it; neither knows how a face is drawn.
 *
 * The face (`face`) decides the shapes: ticks, numerals, hands, digits. The
 * scheme (`scheme`) decides the colours. Every combination works, so 22
 * faces and 10 schemes do not have to be drawn one by one. The designs are
 * those of the DECK//SWITCH clocks plugin, plus the scheme `theme`, which
 * takes the dashboard's own colours.
 *
 * The time comes in as numbers (`hours`, `minutes`, `seconds`, `day`), already
 * in the zone the tile shows: the caller does the zone arithmetic.
 *
 * Analog faces and the drawn digital ones paint on a Canvas once a second,
 * or once a minute without seconds. Nothing moves in between.
 */
Item {
    id: face
    property var theme
    property string display: "digital"         // analog | digital
    property string style: "classic"           // the face, see ANALOG / DIGITAL
    property string scheme: "theme"
    property string customFace: ""
    property string customText: ""
    property string customAccent: ""
    property bool format24: true
    property bool showSeconds: false
    property int hours: 0
    property int minutes: 0
    property int seconds: 0
    property int day: 1
    // The time in words, filled in by the caller (it knows the language).
    property string words: ""

    // -- colours --------------------------------------------------------------

    readonly property var schemes: ({
        night:  { face: "#111827", text: "#f9fafb", accent: "#ef4444", dim: "#4b5563" },
        light:  { face: "#f8fafc", text: "#0f172a", accent: "#dc2626", dim: "#94a3b8" },
        ocean:  { face: "#0c4a6e", text: "#e0f2fe", accent: "#38bdf8", dim: "#0369a1" },
        forest: { face: "#14532d", text: "#dcfce7", accent: "#4ade80", dim: "#166534" },
        amber:  { face: "#1c1917", text: "#fbbf24", accent: "#f97316", dim: "#57534e" },
        red:    { face: "#0a0a0a", text: "#dc2626", accent: "#f87171", dim: "#450a0a" },
        violet: { face: "#2e1065", text: "#ede9fe", accent: "#c084fc", dim: "#5b21b6" },
        teal:   { face: "#134e4a", text: "#ccfbf1", accent: "#2dd4bf", dim: "#0f766e" },
        none:   { face: "",        text: "#ffffff", accent: "#ef4444", dim: "#6b7280" }
    })

    readonly property var colours: {
        var base
        if (scheme === "theme" || !schemes[scheme]) {
            base = { face: "",
                     text: theme ? theme["fg"] : "#e0e0e0",
                     accent: theme ? theme["accent"] : "#00e0ff",
                     dim: theme ? theme["fg-muted"] : "#6b7280" }
        } else {
            base = Object.assign({}, schemes[scheme])
        }
        if (customFace) base.face = customFace
        if (customText) base.text = customText
        if (customAccent) base.accent = customAccent
        return base
    }
    readonly property bool hasFace: colours.face !== ""
    readonly property string uiFont: theme ? theme["font-ui"] : "sans-serif"
    readonly property string displayFont: theme ? theme["font-display"] : uiFont
    readonly property string monoFont: theme ? theme["font-mono"] : "monospace"
    // The canvas takes only a family Qt knows; anything else falls back to
    // a tiny default instead of to something similar.
    readonly property string canvasFont: Qt.fontFamilies().indexOf(uiFont) >= 0 ? "\"" + uiFont + "\"" : "sans-serif"

    // -- the faces --------------------------------------------------------------

    // ticks: hm hours and minutes, h hours, q quarters, m minutes only (numbers
    // stand at the hours), dots, bars (railway), none.
    // numerals: "" none, 12 all, 4 at 12/3/6/9, roman at 12/3/6/9.
    // hands: taper, bar, thin, rail.
    readonly property var analogFaces: ({
        classic: { ticks: "hm",   numerals: "",      hands: "taper", ring: false, date: false, rim: true },
        numbers: { ticks: "m",    numerals: "12",    hands: "taper", ring: false, date: false, rim: false },
        roman:   { ticks: "h",    numerals: "roman", hands: "thin",  ring: false, date: false, rim: true },
        minimal: { ticks: "q",    numerals: "",      hands: "thin",  ring: false, date: false, rim: false },
        dots:    { ticks: "dots", numerals: "",      hands: "bar",   ring: false, date: false, rim: false },
        railway: { ticks: "bars", numerals: "",      hands: "rail",  ring: false, date: false, rim: false },
        bauhaus: { ticks: "none", numerals: "4",     hands: "thin",  ring: false, date: false, rim: false },
        ring:    { ticks: "none", numerals: "",      hands: "bar",   ring: true,  date: false, rim: false },
        modern:  { ticks: "h",    numerals: "",      hands: "bar",   ring: false, date: false, rim: false },
        chrono:  { ticks: "hm",   numerals: "4",     hands: "taper", ring: false, date: true,  rim: false },
        hands:   { ticks: "none", numerals: "",      hands: "taper", ring: false, date: false, rim: false }
    })
    readonly property var analogStyle: analogFaces[style] || analogFaces.classic
    readonly property var drawnDigital: ["segment", "matrix", "binary", "dayarc"]
    readonly property string digitalStyle: ["classic", "light", "mono", "serif", "segment", "matrix",
                                            "stacked", "flip", "binary", "dayarc", "words"]
                                           .indexOf(style) >= 0 ? style : "classic"
    readonly property bool usesCanvas: display === "analog" || drawnDigital.indexOf(digitalStyle) >= 0

    // -- text of the time ---------------------------------------------------------

    function pad(n) { return (n < 10 ? "0" : "") + n }
    readonly property int shownHour: format24 ? hours : (hours % 12 || 12)
    readonly property string ampm: format24 ? "" : (hours < 12 ? "AM" : "PM")
    readonly property string timeText: (format24 ? pad(shownHour) : String(shownHour)) + ":" + pad(minutes)
                                       + (showSeconds ? ":" + pad(seconds) : "")
    // Digits only, always two per unit: segment, matrix, flip, binary.
    readonly property string digits: pad(shownHour) + pad(minutes) + (showSeconds ? pad(seconds) : "")

    onHoursChanged: canvas.requestPaint()
    onMinutesChanged: canvas.requestPaint()
    onSecondsChanged: if (showSeconds || (display === "analog" && analogStyle.ring)) canvas.requestPaint()
    onColoursChanged: canvas.requestPaint()
    onStyleChanged: canvas.requestPaint()
    onDisplayChanged: canvas.requestPaint()
    onShowSecondsChanged: canvas.requestPaint()
    onFormat24Changed: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    // -- the canvas faces -----------------------------------------------------------

    Canvas {
        id: canvas
        anchors.fill: parent
        visible: face.usesCanvas
        renderStrategy: Canvas.Cooperative

        function point(cx, cy, length, angle) {
            return [cx + Math.sin(angle) * length, cy - Math.cos(angle) * length]
        }

        // A hand as a quadrilateral: `width` at the foot, narrower at the tip.
        function hand(ctx, cx, cy, angle, length, width, colour, tip, tail) {
            var across = angle + Math.PI / 2
            var foot = point(cx, cy, -(tail || 0), angle)
            var head = point(cx, cy, length, angle)
            var b1 = width / 2, b2 = width * tip / 2
            ctx.fillStyle = colour
            ctx.beginPath()
            ctx.moveTo(foot[0] + Math.sin(across) * b1, foot[1] - Math.cos(across) * b1)
            ctx.lineTo(head[0] + Math.sin(across) * b2, head[1] - Math.cos(across) * b2)
            ctx.lineTo(head[0] - Math.sin(across) * b2, head[1] + Math.cos(across) * b2)
            ctx.lineTo(foot[0] - Math.sin(across) * b1, foot[1] + Math.cos(across) * b1)
            ctx.closePath()
            ctx.fill()
            // Round ends; without them thick hands look cut off.
            if (tip >= 0.9) disc(ctx, head[0], head[1], b2, colour)
            disc(ctx, foot[0], foot[1], b1, colour)
        }

        function disc(ctx, x, y, radius, colour) {
            ctx.fillStyle = colour
            ctx.beginPath()
            ctx.arc(x, y, radius, 0, 2 * Math.PI)
            ctx.fill()
        }

        function centredText(ctx, text, x, y, size, maxWidth, colour, bold) {
            ctx.fillStyle = colour
            ctx.textAlign = "center"
            ctx.textBaseline = "middle"
            var px = size
            do {
                ctx.font = (bold ? "bold " : "") + Math.round(px) + "px " + face.canvasFont
                if (ctx.measureText(text).width <= maxWidth) break
                px -= 1
            } while (px > 6)
            ctx.fillText(text, x, y)
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (face.display === "analog") analog(ctx)
            else if (face.digitalStyle === "segment") segment(ctx)
            else if (face.digitalStyle === "matrix") matrix(ctx)
            else if (face.digitalStyle === "binary") binary(ctx)
            else if (face.digitalStyle === "dayarc") dayarc(ctx)
        }

        // -- analog --

        function analog(ctx) {
            var c = face.colours
            var st = face.analogStyle
            var side = Math.min(width, height)
            var cx = width / 2, cy = height / 2
            var r = side / 2 - 2
            if (r <= 4) return

            if (face.hasFace) disc(ctx, cx, cy, r, c.face)
            if (st.rim) {
                ctx.strokeStyle = c.dim
                ctx.lineWidth = Math.max(1, r * 0.025)
                ctx.beginPath(); ctx.arc(cx, cy, r - ctx.lineWidth / 2, 0, 2 * Math.PI); ctx.stroke()
            }
            // Minutes as an arc round the face: the part of the hour gone by.
            if (st.ring) {
                var thick = r * 0.09
                ctx.lineWidth = thick
                ctx.strokeStyle = c.dim
                ctx.beginPath(); ctx.arc(cx, cy, r - thick / 2, 0, 2 * Math.PI); ctx.stroke()
                var part = (face.minutes + face.seconds / 60) / 60
                if (part > 0) {
                    ctx.strokeStyle = c.accent
                    ctx.beginPath()
                    ctx.arc(cx, cy, r - thick / 2, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * part)
                    ctx.stroke()
                }
            }
            ticks(ctx, cx, cy, r, st, c)
            numerals(ctx, cx, cy, r, st, c)
            if (st.date) dateWindow(ctx, cx, cy, r, c)

            var hourA = (face.hours % 12 + face.minutes / 60) / 12 * 2 * Math.PI
            var minA = (face.minutes + face.seconds / 60) / 60 * 2 * Math.PI
            var secA = face.seconds / 60 * 2 * Math.PI
            if (st.hands === "rail") {
                hand(ctx, cx, cy, hourA, r * 0.55, r * 0.11, c.text, 0.8, r * 0.18)
                hand(ctx, cx, cy, minA, r * 0.85, r * 0.08, c.text, 0.75, r * 0.18)
            } else if (st.hands === "bar") {
                hand(ctx, cx, cy, hourA, r * 0.5, r * 0.11, c.text, 1.0, 0)
                if (st.ring) {
                    // With the ring showing the minutes, a dot at the rim is enough.
                    var tipPoint = point(cx, cy, r * 0.955, minA)
                    disc(ctx, tipPoint[0], tipPoint[1], r * 0.075, c.text)
                } else {
                    hand(ctx, cx, cy, minA, r * 0.78, r * 0.075, c.text, 1.0, 0)
                }
            } else if (st.hands === "thin") {
                hand(ctx, cx, cy, hourA, r * 0.5, r * 0.05, c.text, 0.6, 0)
                hand(ctx, cx, cy, minA, r * 0.8, r * 0.035, c.text, 0.6, 0)
            } else {
                hand(ctx, cx, cy, hourA, r * 0.52, r * 0.09, c.text, 0.35, r * 0.08)
                hand(ctx, cx, cy, minA, r * 0.8, r * 0.065, c.text, 0.35, r * 0.1)
            }
            if (face.showSeconds) {
                if (st.hands === "rail") {
                    hand(ctx, cx, cy, secA, r * 0.62, r * 0.025, c.accent, 1.0, r * 0.25)
                    var paddle = point(cx, cy, r * 0.62, secA)
                    disc(ctx, paddle[0], paddle[1], r * 0.1, c.accent)
                } else {
                    hand(ctx, cx, cy, secA, r * 0.88, r * 0.022, c.accent, 1.0, r * 0.18)
                }
            }
            disc(ctx, cx, cy, r * (face.showSeconds ? 0.06 : 0.05), face.showSeconds ? c.accent : c.text)
        }

        function ticks(ctx, cx, cy, r, st, c) {
            if (st.ticks === "none") return
            ctx.lineCap = "butt"
            for (var i = 0; i < 60; i++) {
                var angle = i / 60 * 2 * Math.PI
                var full = i % 5 === 0
                var quarter = i % 15 === 0
                if (st.ticks === "dots") {
                    if (!full) continue
                    var p = point(cx, cy, r * 0.86, angle)
                    disc(ctx, p[0], p[1], r * (quarter ? 0.06 : 0.035), c.text)
                    continue
                }
                if (st.ticks === "q" && !quarter) continue
                if (st.ticks === "h" && !full) continue
                // With every numeral on the face, a tick at the hour would be double.
                if (st.ticks === "m" && full) continue
                var length, thick
                if (st.ticks === "bars") {
                    length = full ? r * 0.2 : r * 0.06
                    thick = full ? r * 0.07 : r * 0.025
                } else if (full) {
                    length = r * (quarter && st.ticks === "q" ? 0.17 : 0.14)
                    thick = r * 0.035
                } else {
                    length = r * 0.06
                    thick = r * 0.014
                }
                var outer = point(cx, cy, r * 0.94, angle)
                var inner = point(cx, cy, r * 0.94 - length, angle)
                ctx.strokeStyle = (full || st.ticks === "bars") ? c.text : c.dim
                ctx.lineWidth = Math.max(1, thick)
                ctx.beginPath(); ctx.moveTo(inner[0], inner[1]); ctx.lineTo(outer[0], outer[1]); ctx.stroke()
            }
        }

        function numerals(ctx, cx, cy, r, st, c) {
            if (!st.numerals) return
            var roman = { 12: "XII", 3: "III", 6: "VI", 9: "IX" }
            var hoursList = st.numerals === "12" ? [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] : [12, 3, 6, 9]
            var distance = st.numerals === "12" ? 0.74 : 0.72
            var size = st.numerals === "12" ? 0.24 : 0.27
            // With ticks at the rim the numerals move inwards a little.
            if (st.ticks === "hm" || st.ticks === "h") distance -= 0.06
            for (var i = 0; i < hoursList.length; i++) {
                var h = hoursList[i]
                if (h === 3 && st.date) continue   // where the date window sits, as on a chronograph
                var p = point(cx, cy, r * distance, h / 12 * 2 * Math.PI)
                centredText(ctx, st.numerals === "roman" ? roman[h] : String(h), p[0], p[1],
                            r * size, r * 0.6, c.text, true)
            }
        }

        function dateWindow(ctx, cx, cy, r, c) {
            var mx = cx + r * 0.62, my = cy
            var b = r * 0.34, h = r * 0.25
            var dark = !face.hasFace || Qt.color(c.face).hslLightness < 0.5
            ctx.fillStyle = dark ? "#f5f5f5" : "#141414"
            ctx.strokeStyle = c.dim
            ctx.lineWidth = Math.max(1, r * 0.012)
            ctx.beginPath()
            ctx.roundedRect(mx - b / 2, my - h / 2, b, h, r * 0.03, r * 0.03)
            ctx.fill(); ctx.stroke()
            centredText(ctx, String(face.day), mx, my, h * 0.85, b * 0.9, dark ? "#141414" : "#f5f5f5", true)
        }

        // -- digital, drawn --

        // Lays out `count` digits in pairs, with room for a colon between pairs.
        function digitRow(count, ratio, gap) {
            var pairs = count / 2
            var dh = height * 0.8, dw = dh * ratio
            var total = count * dw + (count - pairs) * dw * gap + (pairs - 1) * dw * 0.6
            if (total > width) {
                var f = width / total
                dw *= f; dh *= f; total = width
            }
            var x = (width - total) / 2, y = (height - dh) / 2
            var boxes = [], colons = []
            for (var i = 0; i < count; i++) {
                boxes.push([x, y, dw, dh])
                x += dw
                if (i % 2 === 0) x += dw * gap
                else if (i < count - 1) { colons.push([x + dw * 0.3, y + dh / 2]); x += dw * 0.6 }
            }
            return { boxes: boxes, colons: colons, dh: dh }
        }

        function colonDots(ctx, colons, dh, colour) {
            for (var i = 0; i < colons.length; i++) {
                disc(ctx, colons[i][0], colons[i][1] - dh * 0.2, dh * 0.06, colour)
                disc(ctx, colons[i][0], colons[i][1] + dh * 0.2, dh * 0.06, colour)
            }
        }

        readonly property var segments: ({
            "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
            "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"
        })

        function segment(ctx) {
            var c = face.colours
            var row = digitRow(face.digits.length, 0.5, 0.18)
            // Unlit segments: a faint trace, as on a real display, not a second digit.
            var off = Qt.alpha(c.dim, 0.08)
            for (var i = 0; i < row.boxes.length; i++) {
                var bx = row.boxes[i]
                var on = segments[face.digits[i]]
                var x0 = bx[0], y0 = bx[1], x1 = bx[0] + bx[2], y1 = bx[1] + bx[3]
                var d = bx[2] * 0.2, m = y0 + bx[3] / 2
                var shapes = {
                    a: across(x0, x1, y0 + d / 2, d), g: across(x0, x1, m, d), d: across(x0, x1, y1 - d / 2, d),
                    f: upright(x0 + d / 2, y0, m, d), b: upright(x1 - d / 2, y0, m, d),
                    e: upright(x0 + d / 2, m, y1, d), c: upright(x1 - d / 2, m, y1, d)
                }
                for (var name in shapes) {
                    var pts = shapes[name]
                    ctx.fillStyle = on.indexOf(name) >= 0 ? c.text : off
                    ctx.beginPath()
                    ctx.moveTo(pts[0][0], pts[0][1])
                    for (var k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1])
                    ctx.closePath()
                    ctx.fill()
                }
            }
            colonDots(ctx, row.colons, row.dh, c.text)
        }

        function across(x0, x1, y, d) {
            return [[x0 + d * 0.6, y], [x0 + d, y - d / 2], [x1 - d, y - d / 2],
                    [x1 - d * 0.6, y], [x1 - d, y + d / 2], [x0 + d, y + d / 2]]
        }

        function upright(x, ya, yb, d) {
            return [[x, ya + d * 0.6], [x + d / 2, ya + d], [x + d / 2, yb - d],
                    [x, yb - d * 0.6], [x - d / 2, yb - d], [x - d / 2, ya + d]]
        }

        readonly property var matrixFont: ({
            "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
            "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
            "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
            "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
            "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
            "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
            "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
            "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
            "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
            "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"]
        })

        function matrix(ctx) {
            var c = face.colours
            var row = digitRow(face.digits.length, 5 / 7, 0.2)
            var off = Qt.alpha(c.dim, 0.1)
            for (var i = 0; i < row.boxes.length; i++) {
                var bx = row.boxes[i]
                var cell = bx[3] / 7
                var bits = matrixFont[face.digits[i]]
                for (var line = 0; line < 7; line++)
                    for (var col = 0; col < 5; col++)
                        disc(ctx, bx[0] + (col + 0.5) * cell, bx[1] + (line + 0.5) * cell, cell * 0.4,
                             bits[line][col] === "1" ? c.text : off)
            }
            colonDots(ctx, row.colons, row.dh, c.text)
        }

        // One column per digit, from the bottom 1, 2, 4, 8, like the BCD clocks.
        function binary(ctx) {
            var c = face.colours
            var text = face.digits
            var gapUnits = 0.6
            var units = text.length + gapUnits * (text.length / 2 - 1)
            var cell = Math.min(width / units, height / 4)
            var x = (width - cell * units) / 2
            var y0 = (height - cell * 4) / 2
            var off = Qt.alpha(c.dim, 0.43)
            for (var i = 0; i < text.length; i++) {
                var value = parseInt(text[i])
                for (var bit = 0; bit < 4; bit++) {
                    var lit = (value & (1 << bit)) !== 0
                    disc(ctx, x + cell / 2, y0 + (3 - bit + 0.5) * cell, cell * 0.36,
                         lit ? (i % 2 ? c.accent : c.text) : off)
                }
                x += cell
                if (i % 2 === 1) x += cell * gapUnits
            }
        }

        // An arc showing how much of the day is gone; the time sits inside (as Text).
        function dayarc(ctx) {
            var c = face.colours
            var side = Math.min(width, height)
            var r = side / 2
            var thick = r * 0.12
            ctx.lineWidth = thick
            ctx.strokeStyle = c.dim
            ctx.beginPath(); ctx.arc(width / 2, height / 2, r - thick / 2, 0, 2 * Math.PI); ctx.stroke()
            var part = (face.hours * 3600 + face.minutes * 60 + face.seconds) / 86400
            if (part > 0) {
                ctx.strokeStyle = c.accent
                ctx.beginPath()
                ctx.arc(width / 2, height / 2, r - thick / 2, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * part)
                ctx.stroke()
            }
        }
    }

    // -- the text faces ---------------------------------------------------------------

    // Plain digital: classic, light, mono, serif.
    Item {
        anchors.fill: parent
        visible: face.display === "digital" && ["classic", "light", "mono", "serif"].indexOf(face.digitalStyle) >= 0
        Text {
            id: plainTime
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: face.ampm ? -parent.height * 0.08 : 0
            // A little air at the sides, so clocks side by side stay apart.
            width: parent.width * 0.9
            height: parent.height * (face.ampm ? 0.66 : 0.8)
            text: face.timeText
            color: face.colours.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            fontSizeMode: Text.Fit
            minimumPixelSize: 8
            font.pixelSize: 400
            font.weight: face.digitalStyle === "light" ? Font.Light : (face.digitalStyle === "classic" ? bridge.metrics.clock_weight || Font.Bold : Font.Bold)
            font.family: face.digitalStyle === "mono" ? face.monoFont
                         : face.digitalStyle === "serif" ? "serif" : face.displayFont
        }
        Text {
            visible: face.ampm !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: plainTime.bottom
            text: face.ampm
            color: face.colours.accent
            font.pixelSize: Math.max(10, parent.height * 0.16)
            font.weight: Font.Bold
            font.family: face.uiFont
        }
    }

    // Hours above minutes; seconds and AM/PM small beside them.
    Item {
        anchors.fill: parent
        visible: face.display === "digital" && face.digitalStyle === "stacked"
        Column {
            anchors.centerIn: parent
            Repeater {
                model: [face.pad(face.shownHour), face.pad(face.minutes)]
                delegate: Text {
                    width: face.width * 0.8
                    height: face.height * 0.48
                    text: modelData
                    color: index === 0 ? face.colours.text : face.colours.accent
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    fontSizeMode: Text.Fit
                    minimumPixelSize: 8
                    font.pixelSize: 400
                    font.weight: Font.Bold
                    font.family: face.displayFont
                }
            }
        }
        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: [face.showSeconds ? face.pad(face.seconds) : "", face.ampm].filter(function (p) { return p }).join(" ")
            color: face.colours.dim
            font.pixelSize: Math.max(10, face.height * 0.13)
            font.weight: Font.Bold
            font.family: face.uiFont
        }
    }

    // Flip cards: one card per pair of digits, a slit across the middle.
    Row {
        id: flip
        anchors.centerIn: parent
        visible: face.display === "digital" && face.digitalStyle === "flip"
        readonly property int pairs: face.digits.length / 2
        readonly property real gap: face.width * 0.05
        readonly property real cardW: (face.width - gap * (pairs - 1)) / pairs
        readonly property real cardH: Math.min(face.height, cardW * 1.15)
        readonly property bool lightFace: face.hasFace && Qt.color(face.colours.face).hslLightness > 0.5
        spacing: gap
        Repeater {
            model: flip.pairs
            delegate: Rectangle {
                width: flip.cardW
                height: flip.cardH
                radius: Math.max(2, width * 0.12)
                color: flip.lightFace ? "#e2e8f0" : "#28282e"
                Text {
                    anchors.fill: parent
                    anchors.margins: parent.height * 0.08
                    text: face.digits.substr(index * 2, 2)
                    color: face.colours.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    fontSizeMode: Text.Fit
                    minimumPixelSize: 8
                    font.pixelSize: 400
                    font.weight: Font.Bold
                    font.family: face.displayFont
                }
                Rectangle {
                    width: parent.width
                    height: Math.max(1, parent.height * 0.025)
                    anchors.verticalCenter: parent.verticalCenter
                    color: Qt.rgba(0, 0, 0, 0.8)
                }
            }
        }
    }

    // The time inside the day arc.
    Column {
        anchors.centerIn: parent
        visible: face.display === "digital" && face.digitalStyle === "dayarc"
        readonly property real side: Math.min(face.width, face.height)
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.side * 0.68
            height: parent.side * 0.3
            text: (face.format24 ? face.pad(face.shownHour) : String(face.shownHour)) + ":" + face.pad(face.minutes)
            color: face.colours.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            fontSizeMode: Text.Fit
            minimumPixelSize: 8
            font.pixelSize: 400
            font.weight: Font.Bold
            font.family: face.displayFont
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: text !== ""
            text: [face.showSeconds ? face.pad(face.seconds) : "", face.ampm].filter(function (p) { return p }).join(" ")
            color: face.colours.dim
            font.pixelSize: Math.max(10, parent.side * 0.12)
            font.weight: Font.Bold
            font.family: face.uiFont
        }
    }

    // AM/PM beside the drawn digits.
    Text {
        visible: face.display === "digital" && face.ampm !== ""
                 && ["segment", "matrix"].indexOf(face.digitalStyle) >= 0
        anchors.right: parent.right
        anchors.top: parent.top
        text: face.ampm
        color: face.colours.accent
        font.pixelSize: Math.max(10, face.height * 0.14)
        font.weight: Font.Bold
        font.family: face.uiFont
    }

    // In words: the last line in the accent colour.
    Text {
        anchors.fill: parent
        visible: face.display === "digital" && face.digitalStyle === "words"
        text: {
            var parts = face.words.split(" ")
            if (parts.length < 2) return face.words
            var last = parts.pop()
            return parts.join(" ") + " <font color=\"" + face.colours.accent + "\">" + last + "</font>"
        }
        textFormat: Text.StyledText
        color: face.colours.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        fontSizeMode: Text.Fit
        minimumPixelSize: 8
        font.pixelSize: 200
        font.weight: Font.Bold
        font.family: face.displayFont
    }
}
