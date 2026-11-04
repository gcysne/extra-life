# Settings

`~/.config/extra-life/config.toml`. Change values with `extralife config set <key> <value>` (or by hand; the
command rewrites the file without comments). See the current values with `extralife config get`.

| Key | Default | Meaning |
|---|---|---|
| `device_name` | host name | shown in the history and in "saved on" |
| `[providers.<id>]` | | one table per connected provider ([backends.md](backends.md)); written by `provider connect` |
| `providers.<id>.type` | | `local`, `rclone` or `rsync-ssh` |
| `providers.<id>.path` | | folder (`local`) or folder on the host (`rsync-ssh`) |
| `providers.<id>.remote` | | rclone `remote:folder` |
| `providers.<id>.rclone_config` | rclone's own | rclone.conf holding the sign-in (sign-in providers: `~/.config/extra-life/rclone.conf`) |
| `providers.<id>.host` | | ssh host (`rsync-ssh`) |
| `providers.<id>.rclone` | bundled, then PATH | rclone binary |
| `providers.<id>.args` | `[]` | extra rclone or ssh arguments, e.g. `["--bwlimit", "2M"]` |
| `sync.on_game_exit` | `true` | sync when a game closes (needs the Decky plugin) |
| `sync.include_states` | `false` | also sync save states |
| `sync.propagate_deletes` | `true` | a save deleted on one device is removed on the others (kept in history/backup) |
| `sync.history_days` | `30` | how long replaced versions stay on the remote |
| `sync.backup_days` | `30` | how long local backups of replaced files stay |
| `sync.wait_for_exit` | `60` | seconds the background sync waits for a running emulator to close |
| `profiles.enabled` | `["auto"]` | `auto` = every profile found on this device; or a list of ids |
| `profiles.disabled` | `[]` | ids never synced |
| `[vars]` | | your own path variables for profiles |

Settings from 0.1.0-alpha (a single `[remote]` table) are read as one provider and rewritten in the new form the
next time a setting changes.

The periodic sync is the systemd timer `extralife-sync.timer` (after login, then every 30 minutes). It is **off by
default** (syncs happen when a game closes): turn it on with the plugin's "Sync every 30 minutes" toggle or
`systemctl --user enable --now extralife-sync.timer`, off with `disable --now`. Reinstalling keeps your choice. To change the
interval: `systemctl --user edit extralife-sync.timer` and set `OnUnitActiveSec=`.

