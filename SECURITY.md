# Security

Report vulnerabilities privately through GitHub's "Report a vulnerability" (Security tab), not in public issues.

What Extra Life touches: your emulator save folders (read, and written only when a newer version is pulled; the
replaced file is backed up first), its own folders (`~/.config/extra-life`, `~/.local/state/extra-life`,
`~/.local/share/extra-life`) and the remote you configure. It never uploads emulator keys, firmware or BIOS files
(profiles exclude them). Cloud credentials stay in rclone's own config (`~/.config/rclone/rclone.conf`); for
private data, wrap the remote in an rclone `crypt` remote (docs/backends.md).
