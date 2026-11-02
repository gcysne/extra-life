#!/usr/bin/env bash
# Remove what install.sh added. Keeps settings, sync state and backups unless --purge is given.
# Your saves and everything already in the cloud are never touched.
set -euo pipefail

LIB="$HOME/.local/lib/extra-life"
UNITS="$HOME/.config/systemd/user"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
say() { printf '\033[1m- %s\033[0m\n' "$*"; }

say "stopping the background sync"
systemctl --user disable --now extralife-sync.timer 2>/dev/null || true
systemctl --user stop extralife-sync.service 2>/dev/null || true
rm -f "$UNITS/extralife-sync.service" "$UNITS/extralife-sync.timer"
systemctl --user daemon-reload 2>/dev/null || true

say "removing the program"
rm -rf "$LIB" "$HOME/.local/bin/extralife"

PLUGIN="$HOME/homebrew/plugins/extra-life"
if [[ -d "$PLUGIN" ]]; then
    say "removing the Decky plugin (Decky owns that folder: needs your password)"
    sudo ${SUDO_ASKPASS:+-A} -p "[sudo] password to remove the Extra Life Decky plugin: " \
        sh -c 'rm -rf "$1" && { systemctl restart plugin_loader 2>/dev/null || true; }' _ "$PLUGIN" \
        || echo "Couldn't remove $PLUGIN; delete it as root." >&2
fi

if [[ $PURGE == 1 ]]; then
    say "removing settings, sync state, local backups and the downloaded rclone"
    rm -rf "$HOME/.config/extra-life" "$HOME/.local/state/extra-life" "$HOME/.local/share/extra-life"
else
    echo "Kept settings (~/.config/extra-life) and local backups (~/.local/state/extra-life). Use --purge to remove them."
fi
