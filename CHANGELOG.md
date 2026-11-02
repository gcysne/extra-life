# Changelog

## 0.1.0-alpha (unreleased)

First version.

- `extralife` command and a systemd user service: syncs emulator save games after a game closes, a few minutes after
  login and every 30 minutes.
- Backends: local folder (rsync), rsync over SSH, rclone (Google Drive, Dropbox, OneDrive, S3, WebDAV and the
  other providers rclone supports). `extralife install-rclone` downloads the official build (checksum verified).
- Three-way sync with conflict detection; replaced and deleted versions kept in the remote's history (30 days by
  default) and in a local backup folder; restore any older version.
- Profiles for 20 emulators (EmuDeck paths first, then Flatpak and native defaults). Save states off by default.
- Decky plugin: status, recently saved files, sync now, force push and force pull (all or per emulator), history
  and restore, conflicts, activity log, settings.
