# Why it looks the way it does

Nothing in this file is part of the program any more. These are decisions
that were made, written down so nobody undoes them by accident. For how
things stand today, see the [README](../README.md).

## From a Chromium kiosk to a QML window

*31 August to 1 September 2026*

The display was Chromium in kiosk mode, started from a shell script, loading
the same page you could open in a browser.

Two things argued against it.

**The window could not be placed.** Chromium is an XWayland client. KWin
ignores the geometry such a client asks for, and on a cold boot the window
regularly landed on the primary monitor, because the Xeneon was not arranged
yet at that point. The workaround was a generated KWin rule carrying a fixed
geometry.

**Memory grew.** Under Wayland Qt WebEngine stopped releasing compositor
layers. Measured over several runs on 31 August 2026 it was roughly 20 MB a
minute. On a display that runs for weeks, that ends in the OOM killer.

The kiosk creates the window itself now, in Qt Quick. That lets it put the
window on a screen directly, instead of telling another process through a rule
where to place itself. It sits at about 130 MB and stays there.

The `[edge-dashboard-kiosk]` group in `~/.config/kwinrulesrc` still exists,
but it does something else: it keeps the window out of the task list, carries
no geometry, and is written by `scripts/window-rule.sh`. Older installations
still have the stale geometry keys in there; the script clears them out on its
next run.

A browser comes back only for a video, in a process of its own that ends with
the video. The system-wide Qt WebEngine is the build with the codecs that play
YouTube.

## No dashboard in a browser any more

*1 September 2026*

After the move to QML the display existed twice: once in QML for the panel,
once in JavaScript for the browser. Both had to be maintained, and every new
widget had to be built twice.

What that bought was out of proportion. The backend listens on `127.0.0.1`,
so the dashboard was reachable from the very machine the kiosk runs on and
nowhere else. Reaching it from a second device would have meant changing the
bind address.

Deleted were `frontend/js/`, `index.html` and the stylesheets `base.css`,
`widgets.css` and `fonts.css`, about 5500 lines together. The server has
answered `/` with a 404 since.

What stayed in `frontend/` is what the kiosk and the settings window read:

* `css/themes/` and `locales/`, which the kiosk reads straight off disk
* `player.html`, which the video window fetches over HTTP
* `vendor/`, which serves the Tabler icons, the fonts and the settings
  window's emoji data set

The JS files doubled as the layout editor's registry: it listed what was in
`frontend/js/widgets/` and read `static variants` out of the source with a
regular expression. That is one manifest per widget in `widgets/` now.

The fonts used to be loaded through `fonts.css`. The kiosk window never had a
replacement for that, so `industrial`, `nightclub` and `toxic` had been
running on a substitute typeface ever since the move. The kiosk now loads the
files from `vendor/fonts/` itself at startup.

## Sensors are addressed by where they sit

*1 September 2026*

A `sensor_focus` tile stores which reading it shows. That id used to be
`hwmon3/k10temp:1`: the directory name under `/sys/class/hwmon` plus the chip
name and the number of the temperature input.

The kernel hands out hwmon numbers at boot, in the order drivers register.
That is unique for one run but not the same across reboots. With three NVMe
drives all reporting as `nvme`, a tile would have shown a different drive
afterwards.

The id now names the address the hardware sits at, taken from the hwmon
entry's `device` link: `k10temp@0000:00:18.3:1` for the CPU,
`spd5118@7-0051:1` for a memory module. A PCI slot and an i2c address do not
change while the part stays in the same socket. NVMe drives link to their
controller number, which is a counter again, so the search walks one level
further to the slot.

The chip name stays part of the id. It can therefore only ever match the same
chip in the same place, never a neighbour. Where two readings would still
share an id, the module appends the hwmon slot and logs a warning: those two
lose their stability, but no tile shows a foreign value.

Old ids match nothing. Only the sensor picker in the `sensor_focus` widget is
affected; it is picked once more, and until then the tile says the sensor is
no longer reported.

---

[README](../README.md) · [Deutsch](entscheidungen.md)
