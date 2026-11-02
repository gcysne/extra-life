#!/usr/bin/env bash
# Install Extra Life for the current user (no root needed except for the Decky plugin copy):
#   ~/.local/lib/extra-life/      the program and the emulator profiles
#   ~/.local/bin/extralife        the command
#   ~/.config/systemd/user/       extralife-sync.service + .timer (timer off by default: sync after login and every 30 min)
#   ~/homebrew/plugins/extra-life the Decky plugin (skipped with --no-plugin or without Decky Loader)
# Settings (~/.config/extra-life) and sync state (~/.local/state/extra-life) are never touched.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
LIB="$HOME/.local/lib/extra-life"
BIN="$HOME/.local/bin/extralife"
UNITS="$HOME/.config/systemd/user"
PLUGIN=1
[[ "${1:-}" == "--no-plugin" ]] && PLUGIN=0

say() { printf '\033[1m- %s\033[0m\n' "$*"; }

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || { echo "Extra Life needs Python 3.11 or newer (python3)." >&2; exit 1; }

say "installing the program to $LIB"
rm -rf "$LIB.new"
mkdir -p "$LIB.new"
cp -r "$SRC/extralife" "$SRC/profiles" "$LIB.new/"
cp "$SRC/uninstall.sh" "$LIB.new/"          # so ~/.local/lib/extra-life/uninstall.sh works for every install method
for f in LICENSE README.md CHANGELOG.md; do cp "$SRC/$f" "$LIB.new/" 2>/dev/null || true; done
find "$LIB.new" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$LIB.old"
[[ -d "$LIB" ]] && mv "$LIB" "$LIB.old"
mv "$LIB.new" "$LIB"
rm -rf "$LIB.old"

mkdir -p "$(dirname "$BIN")"
cat > "$BIN" <<WRAP
#!/bin/sh
exec python3 -s -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from extralife.cli import main; sys.exit(main(sys.argv[1:]))' "$LIB" "\$@"
WRAP
chmod +x "$BIN"

say "installing the background sync (systemd user service; the 30-minute timer stays as you set it, off by default)"
mkdir -p "$UNITS"
cp "$SRC/systemd/extralife-sync.service" "$SRC/systemd/extralife-sync.timer" "$UNITS/"
systemctl --user daemon-reload

if [[ $PLUGIN == 1 && -d "$HOME/homebrew/plugins" ]]; then
    "$SRC/decky-plugin/install.sh" || echo "The Decky plugin wasn't installed; run decky-plugin/install.sh later." >&2
fi

say "done: $("$BIN" --version)"
if [[ ! -f "$HOME/.config/extra-life/config.toml" ]] || ! grep -q '^\[providers\.' "$HOME/.config/extra-life/config.toml"; then
    echo "Next: choose where your saves go. In Game Mode: Quick Access (…) → Extra Life → Connect a provider."
    echo "Or here in a terminal: extralife setup"
fi
