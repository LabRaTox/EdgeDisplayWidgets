.pragma library

/*
 * Time arithmetic for the clock and the world clock.
 *
 * Qt's JavaScript knows local time and UTC only. A zone's time is UTC plus
 * the zone's offset, which the timezones module sends in minutes; an empty
 * zone means local time. Everything here returns plain numbers or strings;
 * `tr` is the bridge's translate function, passed in because a library has
 * no access to the window's context.
 */

// The time to show: local, or in a zone with a known offset. `date` is a
// Date whose *local* fields carry the zone's wall time, so Qt's own date
// formatting can be used on it.
function wallTime(nowMs, offsetMinutes) {
    var now = new Date(nowMs)
    if (offsetMinutes === undefined || offsetMinutes === null) {
        return { hours: now.getHours(), minutes: now.getMinutes(), seconds: now.getSeconds(),
                 day: now.getDate(), date: now, offset: -now.getTimezoneOffset() }
    }
    var shifted = new Date(nowMs + offsetMinutes * 60000)
    var wall = new Date(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate(),
                        shifted.getUTCHours(), shifted.getUTCMinutes(), shifted.getUTCSeconds())
    return { hours: wall.getHours(), minutes: wall.getMinutes(), seconds: wall.getSeconds(),
             day: wall.getDate(), date: wall, offset: offsetMinutes }
}

// "Buenos Aires" for "America/Argentina/Buenos_Aires".
function city(zone) {
    if (!zone) return ""
    var parts = zone.split("/")
    return parts[parts.length - 1].replace(/_/g, " ")
}

function dateText(locale, date, mode, tr) {
    if (mode === "date") return locale.toString(date, tr("widget.clock.format_date"))
    if (mode === "weekday") return locale.toString(date, tr("widget.clock.format_weekday"))
    if (mode === "both") return locale.toString(date, tr("widget.clock.format_both"))
    return ""
}

// "+2", "-5:30", "+5:45".
function offsetLabel(minutes) {
    var sign = minutes >= 0 ? "+" : "−"
    var abs = Math.abs(minutes)
    var hours = Math.floor(abs / 60), rest = abs % 60
    return sign + hours + (rest ? ":" + (rest < 10 ? "0" : "") + rest : "")
}

// How far a zone is from local time, with a change of day.
function difference(zoneTime, localTime, tr) {
    var delta = zoneTime.offset - localTime.offset
    var text = delta === 0 ? tr("widget.world_clock.same_time")
                           : tr("widget.world_clock.hours").replace("{offset}", offsetLabel(delta))
    var a = new Date(zoneTime.date.getFullYear(), zoneTime.date.getMonth(), zoneTime.date.getDate())
    var b = new Date(localTime.date.getFullYear(), localTime.date.getMonth(), localTime.date.getDate())
    var days = Math.round((a - b) / 86400000)
    if (days > 0) text += " · " + tr("widget.world_clock.tomorrow")
    else if (days < 0) text += " · " + tr("widget.world_clock.yesterday")
    return text
}

// The time as one says it, rounded to five minutes. From which minute the
// coming hour is named ("halb sechs" against "half past five") is a text of
// the language, `widget.clock.words_next_from`.
function words(hours, minutes, tr) {
    var total = hours * 60 + minutes
    var rounded = Math.floor((total + 2) / 5) * 5
    var hour = Math.floor(rounded / 60) % 24
    var minute = rounded % 60
    var nextFrom = parseInt(tr("widget.clock.words_next_from")) || 35
    if (minute >= nextFrom) hour += 1
    // "ein Uhr", but "fünf nach eins".
    var name = minute === 0 && hour % 12 === 1 ? tr("widget.clock.hour_1_full") : tr(HOURS[hour % 12])
    return tr(PHRASES[minute / 5]).replace("{hour}", name)
}

// Whole keys rather than built ones, so each can be found and checked.
var HOURS = ["widget.clock.hour_00", "widget.clock.hour_01", "widget.clock.hour_02",
             "widget.clock.hour_03", "widget.clock.hour_04", "widget.clock.hour_05",
             "widget.clock.hour_06", "widget.clock.hour_07", "widget.clock.hour_08",
             "widget.clock.hour_09", "widget.clock.hour_10", "widget.clock.hour_11"]
var PHRASES = ["widget.clock.words_00", "widget.clock.words_05", "widget.clock.words_10",
               "widget.clock.words_15", "widget.clock.words_20", "widget.clock.words_25",
               "widget.clock.words_30", "widget.clock.words_35", "widget.clock.words_40",
               "widget.clock.words_45", "widget.clock.words_50", "widget.clock.words_55"]
