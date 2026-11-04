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

## Pull request checks

Only the maintainer pushes to `main`; every other change comes as a pull request, reviewed by the code owner
(`.github/CODEOWNERS`). Each pull request gets two automatic security checks:

- **PR security scan** (required, `.github/security/pr_scan.py`): reads what the pull request adds and **rejects it
  upfront** (closes it) on binaries or archives, prompt injection or hidden Unicode, obfuscated, encoded or minified
  code, long numeric or encoded arrays, downloads or installs from sources not listed in
  `.github/security/allowed-sources.txt`, piping downloads into a shell, reverse shells, miners, exfiltration
  endpoints, sudoers or setuid changes, destructive commands on `/` or `~`, package install hooks, and changes to
  `.github/` or `CODEOWNERS`. Risky commands such as `rm -rf`, `sudo`, process kills or credential paths are
  reported as warnings in a review for the maintainer to check.
- **AI security review** (advisory, `.github/security/ai_review.py`): Claude reads the diff as text, with no tools,
  and comments on anything malicious or unsafe the pattern scan can't see.

Needs a tool from a new source? Say so in the pull request: the maintainer decides whether it goes on the allowed
list. False positive? Explain it in a comment; the maintainer can add the `security-reviewed` label.
