# Developing Extra Life

Instructions for an AI coding agent working on this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md) (layout,
checks, rules) and [docs/architecture.md](docs/architecture.md) (sync rules) first. Personal or machine-specific
rules go in `CLAUDE.local.md` (ignored by git).

- **Never lose a save** is the first rule: every code path that replaces or deletes a file keeps the old version
  (remote `history/` or local `backup/`), and gets a test in `tests/test_engine.py` (runs for the local and the
  rclone backend).
- Python: standard library only, 3.11+. The Decky backend (`decky-plugin/main.py`) only calls the CLI with
  `--json`; keep logic in `extralife/`. Decky's bundled Python leaks `LD_LIBRARY_PATH`: child processes go through
  `_env()` / `clean_env()`.
- Don't test against the user's real saves or remote. Use the tests, or `EXTRALIFE_CONFIG_DIR` /
  `EXTRALIFE_STATE_DIR` pointing at a scratch folder with a scratch `local` remote.
- Profiles: only save data; mark what was verified (emulator version, install type).
- Commits: `topic: message` (engine, backend, profile, plugin, cli, install, docs, ci, repo). Update CHANGELOG.md
  for anything users notice.
