# Emulator profiles

A profile says where one emulator keeps its saves. Shipped profiles are in `profiles/`; put your own in
`~/.config/extra-life/profiles/<id>.toml` (same id = replaces the shipped one). Check with `extralife profiles`
and `extralife doctor`.

```toml
id = "myport"                      # lower case, digits, - and _
name = "My Native Port"
processes = ["myport*"]            # process names (globs); while one runs, nothing is pulled into this profile

[[set]]
id = "saves"                       # profile/set is the folder's name on the remote: myport/saves
kind = "saves"                     # or "states" (synced only with sync.include_states = true)
paths = [                          # candidates, first existing folder wins (symlinks are followed)
  "{emudeck_saves}/myport",
  "~/.local/share/myport/saves",
]
include = ["**"]                   # default: everything
exclude = ["*.cfg", "cache/"]      # added to the global excludes (.lock, *.tmp, .DS_Store...)
note = "What this set contains."
```

## Path variables

| Variable | Value |
|---|---|
| `~`, `{home}` | home folder |
| `{emudeck}`, `{emudeck_saves}`, `{emudeck_storage}`, `{emudeck_roms}` | EmuDeck's folders, from `~/.config/EmuDeck/settings.sh` |
| anything under `[vars]` in config.toml | your own, e.g. `ports = "/run/media/deck/SD/Games/ports"` |

A candidate with a variable that isn't defined (no EmuDeck, for example) is skipped.

## Patterns

`*` matches within one folder, `**` across folders, a pattern without `/` matches the file name anywhere, and a
trailing `/` means everything below that folder. Matching ignores case.

## Which profiles sync

By default (`profiles.enabled = ["auto"]`) every profile whose save folder exists on the device. Turn one off with
`extralife profile disable <id>` (or in the plugin's Emulators tab), back to automatic with `extralife profile auto
<id>`.

## Notes on shipped profiles

- **Ryujinx** syncs `bis/user/save`, `saveMeta`, `bis/system/save` (the save index) and `Profiles.json` together;
  keys and firmware are never synced. Folders are numbered, so treat the set as a unit: if two devices play
  different Switch games between syncs, the save index will conflict; settle it with force push or pull from the
  device that has the newer progress.
- **Dolphin Wii** syncs only `title/*/data` from the NAND. **Azahar** syncs only save data and extdata, not
  installed titles. **Xenia** syncs only `00000001` (save) content, not DLC or updates.
- **xemu** keeps every Xbox save inside one virtual disk image (`xbox_hdd.qcow2`), synced as one file.
- Process names are best effort and not verified for every install type. If a sync touches an emulator while it
  runs, add its process name (`cat /proc/<pid>/comm`) to `processes`.
