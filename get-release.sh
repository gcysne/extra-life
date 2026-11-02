#!/usr/bin/env bash
# Install or update Extra Life from the latest GitHub release (no git, no Node.js needed):
#
#   curl -fsSL https://github.com/gcysne/extra-life/releases/latest/download/get-release.sh | bash
#   ... | bash -s -- --no-plugin        # install.sh options
#
# Downloads extra-life.tar.gz and SHA256SUMS from the same release, checks the checksum, unpacks it to a temporary
# folder and runs its install.sh. Settings, sign-ins and sync state are kept.
set -euo pipefail
REPO="${EXTRALIFE_REPO_SLUG:-gcysne/extra-life}"
BASE="https://github.com/$REPO/releases/${EXTRALIFE_RELEASE:-latest}/download"
[[ "${EXTRALIFE_RELEASE:-latest}" != latest ]] && BASE="https://github.com/$REPO/releases/download/$EXTRALIFE_RELEASE"
BASE="${EXTRALIFE_RELEASE_BASE:-$BASE}"      # testing: a local mirror of the release assets

for tool in curl tar sha256sum python3; do
    command -v "$tool" >/dev/null || { echo "$tool is required (it ships with SteamOS)." >&2; exit 1; }
done
mkdir -p "$HOME/.cache/extra-life"
WORK="$(mktemp -d "$HOME/.cache/extra-life/release.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "- downloading Extra Life from $BASE"
curl -fsSL --retry 3 -o "$WORK/extra-life.tar.gz" "$BASE/extra-life.tar.gz"
curl -fsSL --retry 3 -o "$WORK/SHA256SUMS" "$BASE/SHA256SUMS"
echo "- checking the download"
(cd "$WORK" && grep ' extra-life.tar.gz$' SHA256SUMS | sha256sum -c --quiet -) \
    || { echo "Checksum mismatch: nothing was installed." >&2; exit 1; }
tar -C "$WORK" -xzf "$WORK/extra-life.tar.gz"
echo "- Extra Life $(cat "$WORK/extra-life/VERSION")"
cd "$WORK/extra-life"
# Piped from curl, stdin is this script: give install.sh the terminal (for the sudo password prompt).
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
    ./install.sh "$@" </dev/tty
else
    ./install.sh "$@"
fi
