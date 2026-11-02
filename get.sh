#!/usr/bin/env bash
# One-line installer for Extra Life: clone (or update) the repository, then run its install.sh.
#
#   curl -fsSL https://raw.githubusercontent.com/gcysne/extra-life/main/get.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/gcysne/extra-life/main/get.sh | bash -s -- --no-plugin   # install.sh options
#
# The clone goes to ~/extra-life (set EXTRALIFE_SRC to change it) and stays there: updates and uninstall use it.
set -euo pipefail
REPO="${EXTRALIFE_REPO:-https://github.com/gcysne/extra-life.git}"
DIR="${EXTRALIFE_SRC:-$HOME/extra-life}"

command -v git >/dev/null || { echo "git is required (it ships with SteamOS)." >&2; exit 1; }
if [[ -d "$DIR/.git" ]]; then
    echo "- updating $DIR"
    git -C "$DIR" pull --ff-only
elif [[ -e "$DIR" ]]; then
    echo "$DIR exists and isn't an Extra Life clone; set EXTRALIFE_SRC to another folder." >&2; exit 1
else
    echo "- cloning $REPO into $DIR"
    git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"
# Piped from curl, stdin is the script itself: give install.sh the terminal (for the sudo password prompt).
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
    exec ./install.sh "$@" </dev/tty
fi
exec ./install.sh "$@"
