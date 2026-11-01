# Changelog

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
