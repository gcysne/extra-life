# How Extra Life works

## Pieces

```
Decky plugin (Game Mode) ──game closed / resumed──▶ systemctl --user start extralife-sync.service
       │                                                        │
       └── extralife <command> --json ──┐                       ▼
                                        ├──▶ extralife (Python) ──▶ backend (folder | rsync-ssh | rclone)
systemd timer (optional, off by default) ┘
```

There is no long-running daemon: every sync is one run of `extralife`, started by the systemd user service (timer,
plugin, or by hand). A file lock makes sure only one run happens at a time on a device; a lock file on the remote
(`lock.json`, expires after 15 minutes) keeps two devices from syncing at the same moment.

## What gets synced

Profiles (`profiles/*.toml`) list each emulator's save folders ("sets"). On each device the first existing
candidate path is used, symlinks resolved, so a set can live in different places on different devices. A set is
identified by `profile/set` (e.g. `ryujinx/saves`), not by its local path.

## Sync rules

For every file Extra Life compares three SHA-256 hashes: the file here, the file in the remote manifest, and the
remote manifest as this device left it after its last sync (the *base*, in
`~/.local/state/extra-life/providers/<id>/base/`, one per provider: with several providers connected, each is
compared and synced in turn, see [backends.md](backends.md#how-several-providers-stay-the-same)).

| Here vs base | Remote vs base | Result |
|---|---|---|
| changed | unchanged | upload; the previous remote version is copied to history |
| unchanged | changed | download; the local file is backed up first |
| deleted | unchanged | remote copy moves to history (`sync.propagate_deletes`) |
| unchanged | deleted | local file moves to the local backup (`sync.propagate_deletes`) |
| changed | changed differently | **conflict**: nothing is touched until you choose a side |
| same content on both sides | | nothing to do |

On a device's first sync every file that differs from the remote is a conflict (there is no base yet). Use
`extralife pull` (take the cloud's) or `extralife push` (take this device's) to settle them at once.

**Force push / pull** ignore the base: push uploads every local file that differs, pull downloads every remote
file that differs. Neither deletes files that exist on only one side.

Downloads are written next to the target and swapped in with one rename, after their hash is checked against the
manifest; the original modification time is kept. Sets whose emulator is running are skipped (the service waits up
to `sync.wait_for_exit` seconds for it to close first). Force push is allowed while an emulator runs; pulls are not.

## Remote layout

```
extra-life.json                               format marker
lock.json                                     present while a device syncs
devices/<device-id>.json                      devices using this remote, last sync time
manifests/<profile>/<set>.json                sha256, size, mtime and the device of every file's latest version
data/<profile>/<set>/<file>                   latest versions, same tree as on the device
history/<UTC stamp>_<device>/<profile>/<set>/<file>   versions replaced or deleted by that sync
```

`data/` is a plain copy of your saves: you can browse or download it with any tool. History folders older than
`sync.history_days` are deleted once a day; local backups (`~/.local/state/extra-life/backup/`) after
`sync.backup_days`.

## Local files

| Path | What |
|---|---|
| `~/.config/extra-life/config.toml` | settings |
| `~/.config/extra-life/profiles/` | your own profiles (override shipped ones with the same id) |
| `~/.local/state/extra-life/` | hash cache, last run, activity log, backups, `progress.json`; per provider (`providers/<id>/`): base manifests, conflicts, last run |
| `~/.local/share/extra-life/bin/rclone` | rclone downloaded by `extralife install-rclone` |

## Progress

While a sync runs, `~/.local/state/extra-life/progress.json` holds its progress (percent, provider, phase, emulator;
`extralife progress` prints it). Each provider is an equal share of the run. Inside one provider: connecting and
reading the manifests (8%), comparing every save folder (to 25%), then the transfers, weighted by bytes plus a fixed
cost per file, with live byte counts from rclone (`--stats`) and rsync (`--info=progress2`). The percentage never
goes backwards. The Decky plugin shows it as a bar in its panel and as an icon in Steam's status bar that disappears
when the sync ends.
