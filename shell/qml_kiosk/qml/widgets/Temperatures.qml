pragma Singleton
import QtQuick

/*
 * Picks a temperature out of the sensors module.
 *
 * The readings carry `display_chip` ("CPU", "GPU", "RAM", "NVMe") and a
 * `primary` flag for the one that represents the component. Several DIMMs
 * report separately, so for those the warmest is the interesting one.
 */
QtObject {
    function forChip(payload, chip) {
        if (!payload || !payload.available || !payload.readings) return null
        var best = null
        for (var i = 0; i < payload.readings.length; i++) {
            var r = payload.readings[i]
            if ((r.display_chip || "").toUpperCase() !== chip) continue
            if (r.primary) return r.temp_c
            if (best === null || r.temp_c > best) best = r.temp_c
        }
        return best
    }
}
