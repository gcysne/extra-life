# Where saves can go (providers)

Connect one or more providers: in the Decky plugin (Browse → **Providers** → Connect), with `extralife setup`
(questions), or with `extralife provider connect <id>`. Every sync updates **all** connected providers;
`extralife provider disconnect <id>` (or Disconnect in the plugin) stops using one at any time. Several devices can
share the same providers.

| id | Provider | Connect from the command line |
|---|---|---|
| `gdrive` | Google Drive | `extralife provider connect gdrive` |
| `dropbox` | Dropbox | `extralife provider connect dropbox` |
| `onedrive` | OneDrive | `extralife provider connect onedrive` |
| `box` | Box | `extralife provider connect box` |
| `pcloud` | pCloud | `extralife provider connect pcloud` |
| `local` | Folder (SD card, USB drive, mounted share) | `extralife provider connect local --path /run/media/deck/MyCard/ExtraLife` |
| `ssh` | NAS or computer over SSH | `extralife provider connect ssh --host nas --path /shares/saves/ExtraLife` |
| `rclone` | Any remote you set up with `rclone config` | `extralife provider connect rclone --remote myremote --folder ExtraLife` |

Everything Extra Life writes goes inside one folder (`ExtraLife` by default, `--folder` to change it); the root of
your cloud storage is never used.

## How several providers stay the same

Each provider is synced in turn and has its own sync state on this device (`~/.local/state/extra-life/providers/<id>/`),
so the three-way compare ([architecture.md](architecture.md)) works per provider. When a later provider brings a
save the earlier ones don't have (another device only syncs with that one), the earlier providers get a second pass
in the same run, so all of them end up with the same files. Conflicts are per provider and say which one holds the
other copy.

**Force pull** always takes one provider (the plugin asks which). **Force push** and **restore** update every
provider.

**Disconnect** removes the provider from the settings and, for sign-in providers, deletes the sign-in Extra Life
stored. Saves already stored there stay where they are, and this device's sync state for it is kept, so connecting
it again later continues where it left off.

## Cloud sign-in providers (Google Drive, Dropbox, OneDrive, Box, pCloud)

These use rclone (downloaded on first use: official build, checksum verified, `~/.local/share/extra-life/bin/`).
Connecting opens the provider's sign-in page: in Game Mode it opens in Steam's browser (press B to come back when
done); from a terminal in your default browser. The sign-in is stored in Extra Life's own rclone config,
`~/.config/extra-life/rclone.conf` (mode 600), not in rclone's main config.

Google Drive is connected with the `drive.file` permission: Extra Life can only see the files it created itself.

If a sign-in page refuses Steam's browser, connect from Desktop Mode: `extralife provider connect gdrive`.

**Note:** rclone's built-in Google client ID is shared by all rclone users and Google is retiring it during 2026.
To use your own: create an OAuth client (type Desktop app) in Google Cloud Console, then
`rclone --config ~/.config/extra-life/rclone.conf config update gdrive client_id=ID client_secret=SECRET` and
connect again.

Status: Google Drive tested (SteamOS 3.9.5, Lenovo Legion Go, rclone v1.75.2), from the command line. The other
sign-in providers and the in-Steam browser sign-in are not tested yet.

## Folder (`local`)

Any mounted folder: SD card, USB drive, or a network share mounted by the system. Copies use rsync (keeps
modification times, writes through temporary files); without rsync, Python's copy is used. If the card or drive
isn't mounted, that provider's sync fails (the others still run) and is retried later; the folder's parent must
exist. A folder on the same card as your games doesn't protect against losing that card.

Status: tested (SteamOS 3.9.5, Lenovo Legion Go, rsync 3.x).

## Other rclone remote (`rclone`)

rclone supports many more services (S3 and compatible stores, Backblaze B2, WebDAV/Nextcloud, Mega, SFTP...,
[list](https://rclone.org/overview/)). Set one up in Desktop Mode with `rclone config` (it goes in rclone's own
`~/.config/rclone/rclone.conf`), then connect it. Disconnecting leaves that rclone remote alone.

**Encryption:** create a `crypt` remote on top of a cloud remote (`rclone config` → new remote → `crypt`, pointing
at e.g. `gdrive:ExtraLife-crypt`) and connect that crypt remote. File names and contents are then encrypted with a
password only your devices know.

Extra Life uses `rclone copy|move --files-from-raw` for transfers (one call per change, server-side copies where
the provider allows) and `rclone lsjson` for listings.

## NAS or computer over SSH (`ssh`)

Needs key-based login (`ssh nas` must work without a password: the service runs unattended) and `rsync`, `sh`,
`find` and `stat` on the host. `--host` is anything `ssh` accepts, including aliases from `~/.ssh/config`.

Status: written, not yet tested on real hardware.
