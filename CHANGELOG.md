# Changelog

## 1.7.4 · 8 November 2026

### New

- **Wallpapers in themes**: a theme plugin can bring pictures that lie behind
  the pages, one per page in turn, fading on a page change
- **Plugins by the same author**: a click on an author's name, on a card or
  a detail page, shows all of their plugins

### Changed

- Other distributions and desktops:
  - the installer stops early without systemd, and on NixOS
  - package hints for openSUSE (zypper) and for image-based systems such as
    Bazzite and Silverblue (rpm-ostree)
  - the window rule works on Plasma 5
  - KWin reloads without `qdbus6`, and the tray check no longer needs it
  - the installer and the settings window hand the display variables to the
    user services, so the kiosk finds its screen on sway, Hyprland and X11
    window managers
  - `XDG_CONFIG_HOME` is honoured for the user units
  - Flatpak and Snap apps get their icons in the quick action app picker
  - GPU names are found on Debian, Ubuntu and openSUSE
- The kiosk only rebuilds its pages when the layout really changed. Saving a
  module option no longer resets running countdowns
- After the backend comes back, the kiosk reads the config again
- The network chart scales back down once a peak has scrolled out
- The config file is written readable for its owner only, it holds API keys
- The kiosk finds the Xeneon by its model name and in device pixels, so a
  scaled or rotated output works. With several screens and no match it waits
  in a window instead of covering the main monitor, and it hides while the
  display is unplugged
- Programs started from quick actions, Steam games and the settings window
  run in a systemd scope of their own and survive a restart of the backend
- Autostart on XFCE, Cinnamon, MATE, LXQt and other sessions without
  `graphical-session.target`, through an XDG autostart entry. The installer
  names the line to add on Hyprland, Sway and i3
- The tray icon appears when the panel starts after the backend or restarts
- The backend refuses requests for foreign host names while bound to
  loopback (DNS rebinding). `EDGE_ALLOWED_HOSTS` adds names
- The Hyprland snippet uses the `windowrule` syntax of 0.53 and later, and
  `windowrulev2` on older versions
- Kiosk: pages out of view are no longer drawn, and clocks, weather age,
  heartbeat and media progress rest while their page is hidden. A running
  countdown still rings. Widget guide: rest while out of view
- Kiosk: a data frame is converted once per widget that wants it rather than
  once per tile, sensor and disk rows are updated in place, and the media
  progress ticks once a second instead of four times
- Dependencies updated

### Fixed

- Saving the settings of the Quick Actions widget deleted the commands, URLs
  and folders of every action
- Clicking into a secret field and saving something else erased the stored
  secret
- Wallpapers: the picture darkened while fading, loaded twice at start,
  jumped to the first page's picture on every save and stayed in memory
  after switching to a theme without wallpapers
- The kiosk opened two connection attempts per failure while the backend was
  away
- Two saves at the same moment could overwrite each other or tear modules
  down twice
- A probe that hung kept running after every reload
- A note typed just before a page rebuild was lost
- The settings window froze while reading a large dropped file or starting
  the services, and left a zombie process per opened link
- Dashboard texts were missing in the settings window when it started before
  the backend
- A store sign-in that expired or was declined kept polling forever
- An installation that failed for lack of disk space was reported as
  "installed, but its module failed to load"
- The weather tile cut off the rain line under the hourly forecast once an
  hour with rain came in after the tile was built
- Smaller fixes: version numbers with unusual digits, media actions with a
  `name` field, Joplin answers that are not JSON, autostart status when
  systemctl hangs, Tuya errors no longer show the user id

## 1.7.3 · 1 November 2026

### New

- **Building blocks for widgets** in `EdgeDash`: `Card`, `Chip`, `IconButton`,
  `ActionButton`, `Fab`, `SectionHeader`, `Slider`, `Glyph` and the `Ui`
  singleton. They follow the theme, down to its corners. Using them is a
  choice, the guide has the design rules

### Fixed

- A plugin no longer counts a Python package another plugin brought as its
  own, which left it broken once that plugin was removed

## 1.7.1 · 1 November 2026

### New

- **One-line install and update** for systems without the Arch package:
  `scripts/get.sh`

### Changed

- On Arch the installer names the packages for the system PySide6 when the
  kiosk cannot load
- README brought up to date

## 1.7.0 · 1 November 2026

### New

- **Plugin dependencies**: a plugin names what it needs under `dependencies`
  in its manifest, Python packages and packages of the distribution, on Arch,
  Debian, Ubuntu and Fedora. They show on the plugin
  page and install along with the plugin. Python packages need no rights and
  land in a folder of the plugin's own; system packages ask for the password.
  What cannot be installed blocks the plugin and names the command to run.
  The package now depends on `uv` and `python-packaging`
- **Plugin settings pages**: a plugin can bring its own page for the settings
  dialog, in a sandboxed frame
- **Search and sorting** on the plugin page: by name in both directions,
  newest first and best rated
- The settings window comes as a finished program with every release, built
  on an old Ubuntu so it runs on current distributions too. `install.sh`
  downloads it when `npm` and `cargo` are missing
- **More distributions**: `install.sh` now runs through on Ubuntu 22.04 and
  24.04, Debian 13, Fedora 43 and Bazzite. Without a recent PySide6 on the
  system the kiosk gets a virtualenv of its own with PySide6 from PyPI, and
  the installer names the system libraries it needs, with the command
- The installer pins Python 3.13 and leaves out the development packages
- Plugins install off the event loop, so the display keeps
  updating during a long installation

## 1.6.0 · 25 October 2026

The first release with a package. Backend and settings window share one
version number from here on.

### New

- **Arch package**: `packaging/aur/` builds `edge-dashboard` with `makepkg`,
  and every release carries a built package. Installed this way the
  settings live in `~/.config/edge-dashboard/config.yaml`
- **Plugin store**: widgets and themes install, update and uninstall from
  the store, checked by SHA-256. Local install from a zip or a folder, and
  sign-in and submission from the settings window
- **Plugins page** in the settings window: built-in and store widgets by
  category, a switch for each widget's modules, plugin settings, detail
  pages with screenshots and ratings
- **Notes**: folders with their own colours, search, pinning and checklists
  that tick with a tap. Stored locally or in Joplin, over its local API
- **Clock**: local time or any time zone, 11 analog and 11 digital faces,
  ten colour schemes (one follows the theme), countdown with a gong
- **World clock**: up to six time zones side by side, with the difference
  to local time
- **GPU module** for NVIDIA and AMD, integrated graphics included
- Quick actions: text and icon size per tile; YouTube playlists expand into
  their videos
- Help menu: links to the issue tracker and the Discord server

### Changed

- The layout editor shows widget names, and an arrow opens a tile's
  options; options that do not apply are hidden
- Modules that are new in `config.yaml` run for older local configs too
- README rewritten, with new screenshots

### Fixed

- Confirm dialogs (delete a note, run a quick action) open again under
  Qt 6.12
- Installing a plugin no longer crashes the backend on NVIDIA systems
- Two-digit sizes can be typed into the quick action fields
- Shared `youtu.be/…?list=` links start at the shared video
- Store images are served sandboxed
