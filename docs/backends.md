# Where saves can go

Set with `extralife setup` (questions) or `extralife init` (flags). One remote per device; several devices can
share the same remote.

## Folder (`local`)

```bash
extralife init --type local --path /run/media/deck/MyCard/ExtraLife
```

Any mounted folder: SD card, USB drive, or a network share mounted by the system. Copies use rsync (keeps
modification times, writes through temporary files); without rsync, Python's copy is used. If the card or drive
isn't mounted, the sync fails and is retried later; the folder's parent must exist.

Status: tested (SteamOS 3.9.5, Lenovo Legion Go, rsync 3.x).

## Cloud through rclone (`rclone`)

```bash
extralife install-rclone          # or use rclone from your system
~/.local/share/extra-life/bin/rclone config
extralife init --type rclone --remote gdrive:ExtraLife
```

rclone supports Google Drive, Dropbox, OneDrive, Box, pCloud, Mega, S3 and compatible stores, Backblaze B2,
WebDAV/Nextcloud, SFTP and more ([list](https://rclone.org/overview/)). Its remotes and credentials live in rclone's
own config (`~/.config/rclone/rclone.conf`); Extra Life only stores the remote's name.

Setting up a remote needs a browser once (sign-in). Do it in Desktop Mode, or on another computer with
`rclone authorize "drive"` and paste the token when `rclone config` asks.

**Encryption:** create a `crypt` remote on top of the cloud remote (`rclone config` → new remote → `crypt`,
pointing at e.g. `gdrive:ExtraLife-crypt`) and use that crypt remote in Extra Life. File names and contents are
then encrypted with a password only your devices know.

Extra Life uses `rclone copy|move --files-from-raw` for transfers (one call per change, server-side copies where
the provider allows) and `rclone lsjson` for listings.

Status: the full test suite passes against rclone's local backend (rclone v1.75.2). Google Drive: first test
pending.

## Another computer over SSH (`rsync-ssh`)

```bash
extralife init --type rsync-ssh --host nas --path /shares/saves/ExtraLife
```

Needs key-based login (`ssh nas` must work without a password: the service runs unattended) and `rsync`, `sh`,
`find` and `stat` on the host. `--host` is anything `ssh` accepts, including aliases from `~/.ssh/config`.

Status: written, not yet tested on real hardware.
