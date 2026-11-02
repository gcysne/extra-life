# Contributing

Pull requests are welcome, especially new emulator profiles and fixes for paths on other devices or distros.

## Layout

| Part | Where |
|---|---|
| Sync engine, CLI, backends | `extralife/` (Python 3.11+, standard library only) |
| Emulator profiles | `profiles/<id>.toml` ([docs/profiles.md](docs/profiles.md)) |
| Background service | `systemd/` |
| Decky plugin (React frontend, Python backend that calls the CLI) | `decky-plugin/` |
| Install / remove | `install.sh`, `uninstall.sh`, `decky-plugin/install.sh` |
| Tests | `tests/` |

## Before opening a pull request

```bash
python3 -m unittest discover -s tests          # rclone scenarios run too when rclone is installed
shellcheck -S warning install.sh uninstall.sh decky-plugin/install.sh bin/extralife
(cd decky-plugin && corepack pnpm install && corepack pnpm run typecheck && corepack pnpm run build)
```

## Rules

- **Never lose a save.** Anything that replaces or deletes a file must keep the old version (remote history or
  local backup). Add a test for every new path through the engine.
- **Don't sync what isn't a save:** no keys, firmware, BIOS, installed games, DLC or updates. Use `include` to list
  only save data when a folder mixes them.
- **State what you verified.** In a profile, say in a comment which emulator version and install type (EmuDeck,
  Flatpak, AppImage) you checked.
- Device-agnostic: no hard-coded user names, devices or mount points.
- Commits: `topic: message`, topic = `engine`, `backend`, `profile`, `plugin`, `cli`, `install`, `docs`, `ci`, `repo`.

## Releases

1. Set the version in `extralife/__init__.py` and `decky-plugin/package.json` (they must match) and give it a
   section in `CHANGELOG.md` (`## <version>`: it becomes the release notes).
2. Commit, then `git tag v<version> && git push origin v<version>`.
3. `.github/workflows/release.yml` runs the tests, builds `extra-life.tar.gz` (with the prebuilt plugin),
   `get-release.sh` and `SHA256SUMS` (`scripts/make-release.sh`), and publishes them as the **latest** release.
   Never mark it as a pre-release: the update check and `releases/latest/download/...` only see the latest release.
