# Extra Life

Keep your emulator save games safe and in sync across handhelds and PCs. After every play session, Extra Life
uploads the saves that changed to the cloud service or disk you choose, and brings in the ones another device
changed. Nothing is ever overwritten silently: older versions are kept, and saves changed on two devices are
flagged for you to decide.

Built for SteamOS handhelds (Steam Deck, Legion Go, ROG Ally...) with a Decky Loader panel for Game Mode, but the
command and the background service work on any Linux PC.

> Alpha: back up your saves before trying it.

## Features

- **Any storage:** a folder (SD card, USB drive, mounted network share), another machine over SSH (rsync), or any
  cloud [rclone](https://rclone.org) supports: Google Drive, Dropbox, OneDrive, S3, WebDAV/Nextcloud and more.
- **Automatic:** syncs when a game closes (Decky plugin), a few minutes after boot and every 30 minutes.
- **Safe:** compares every file with the last synced state, so it knows which side changed. Saves changed on two
  devices become conflicts, not overwrites. Replaced versions stay in the remote's history (30 days by default) and
  in a local backup folder. Never pulls into a running emulator.
- **Game Mode panel:** last sync, recently saved games, sync now, force push and force pull (all or per emulator),
  browse history and restore an older version, resolve conflicts.
- **20 emulators** out of the box (EmuDeck layout first, then Flatpak and native defaults): RetroArch, Dolphin,
  Ryujinx, PPSSPP, DuckStation, PCSX2, RPCS3, Cemu, Azahar, melonDS, mGBA, RMG, Vita3K, shadPS4, xemu, Xenia,
  Flycast, ScummVM, MAME, BigPEmu. Add your own in a few lines ([docs/profiles.md](docs/profiles.md)).
- Save files only. Save states are optional (off by default); keys, firmware, BIOS, DLC and updates are never
  uploaded.

## Install

In Desktop Mode, in a terminal:

```bash
git clone https://github.com/gcysne/extra-life.git
cd extra-life
./install.sh          # asks for your password only to copy the Decky plugin
extralife setup       # choose where your saves go
```

`install.sh` puts the program in `~/.local/lib/extra-life`, the `extralife` command in `~/.local/bin` and turns on
the background service (systemd user timer). No system files are changed, so it survives SteamOS updates.

### Google Drive (or another cloud)

`extralife setup` → option 2 downloads rclone if needed (official build, checksum verified) and starts
`rclone config`: choose `n` (new remote), name it (e.g. `gdrive`), pick the provider, accept the defaults and sign
in in the browser window. Details and other providers: [docs/backends.md](docs/backends.md).

## Use

From Game Mode: open the Quick Access menu (`…` button) → Extra Life.

From a terminal:

| Command | What it does |
|---|---|
| `extralife status` | setup, last sync, problems |
| `extralife sync` | sync now (both ways) |
| `extralife push` / `pull` | force: this device → cloud / cloud → this device (`--profile ryujinx` for one emulator) |
| `extralife recent` | latest saves, newest first, and which device made them |
| `extralife conflicts`, `resolve --keep local\|cloud --all` | saves changed on two devices |
| `extralife history`, `restore <snapshot> <set> <file>` | older versions |
| `extralife profiles`, `profile disable <id>` | which emulators sync |
| `extralife config set sync.include_states true` | settings ([docs/configuration.md](docs/configuration.md)) |
| `extralife doctor` | check the setup |

## How it works

[docs/architecture.md](docs/architecture.md) explains the sync rules, the remote layout and what happens in every
case (changed here, changed there, changed on both, deleted).

## Remove

`./uninstall.sh` (add `--purge` to also delete settings, local backups and the downloaded rclone). Your saves and
everything already uploaded are not touched.

## License

MIT. See [LICENSE](LICENSE). Contributions welcome: [CONTRIBUTING.md](CONTRIBUTING.md).
