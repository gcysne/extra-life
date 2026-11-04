# Changelog

## 0.1.0-alpha (2026-11-03)

First version.

- `extralife` command and a systemd user service: syncs emulator save games after a game closes; optionally also
  after login and every 30 minutes (timer off by default, toggle in the plugin).
- Backends: local folder (rsync), rsync over SSH, rclone (Google Drive, Dropbox, OneDrive, S3, WebDAV and the
  other providers rclone supports). `extralife install-rclone` downloads the official build (checksum verified).
- Three-way sync with conflict detection; replaced and deleted versions kept in the remote's history (30 days by
  default) and in a local backup folder; restore any older version.
- Profiles for 20 emulators (EmuDeck paths first, then Flatpak and native defaults). Save states off by default.
- Decky plugin: status, recently saved files, sync now, force push and force pull (all or per emulator), history
  and restore, conflicts, activity log, settings.
- Several providers at once: Google Drive, Dropbox, OneDrive, Box, pCloud (browser sign-in, also from Game Mode
  through Steam's browser), a folder, a NAS over SSH, or any rclone remote. Every sync updates all connected
  providers (with a second pass when one of them brought new saves); connect and disconnect them in the plugin's
  Providers tab or with `extralife provider connect|disconnect`. Settings with a single `[remote]` are converted.
- Plugin: ⚙ cog in the Quick Access title opens the full page; Providers is its first tab; new About tab (version,
  links, creator and credits, license).
- One-line install from the latest release (`get-release.sh`: prebuilt plugin, checksum verified) or from the source
  code (`get.sh`: git clone); README with requirements, what goes where, first steps, update and uninstall.
- Update check: the About tab shows "New version available" when GitHub has a newer release, with the update
  command and a copy button; `extralife update-check`. Releases are built by a GitHub workflow on version tags.
- Sync progress: percentage per run (`extralife progress`), shown as a progress bar in the plugin and as an icon
  with a small progress bar in Steam's status bar while a sync runs.
