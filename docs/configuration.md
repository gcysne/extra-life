# Settings

`~/.config/extra-life/config.toml`. Change values with `extralife config set <key> <value>` (or by hand; the
command rewrites the file without comments). See the current values with `extralife config get`.

| Key | Default | Meaning |
|---|---|---|
| `device_name` | host name | shown in the history and in "saved on" |
| `remote.type` | | `local`, `rclone` or `rsync-ssh` ([backends.md](backends.md)) |
| `remote.path` | | folder (`local`) or folder on the host (`rsync-ssh`) |
| `remote.remote` | | rclone `remote:folder` |
| `remote.host` | | ssh host (`rsync-ssh`) |
| `remote.rclone` | bundled, then PATH | rclone binary |
| `remote.args` | `[]` | extra rclone or ssh arguments, e.g. `["--bwlimit", "2M"]` |
| `sync.on_game_exit` | `true` | sync when a game closes (needs the Decky plugin) |
| `sync.include_states` | `false` | also sync save states |
| `sync.propagate_deletes` | `true` | a save deleted on one device is removed on the others (kept in history/backup) |
| `sync.history_days` | `30` | how long replaced versions stay on the remote |
| `sync.backup_days` | `30` | how long local backups of replaced files stay |
| `sync.wait_for_exit` | `60` | seconds the background sync waits for a running emulator to close |
| `profiles.enabled` | `["auto"]` | `auto` = every profile found on this device; or a list of ids |
| `profiles.disabled` | `[]` | ids never synced |
| `[vars]` | | your own path variables for profiles |

The periodic sync is the systemd timer `extralife-sync.timer` (after login, then every 30 minutes):
`systemctl --user disable --now extralife-sync.timer` turns it off (also a toggle in the plugin). To change the
interval: `systemctl --user edit extralife-sync.timer` and set `OnUnitActiveSec=`.
