# Changelog

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
