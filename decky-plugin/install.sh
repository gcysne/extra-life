#!/usr/bin/env bash
# Build the Decky plugin and copy it to ~/homebrew/plugins/extra-life.
# Needs Decky Loader. Node.js >= 20 is used from PATH; if missing, the official Node.js LTS build is downloaded
# once (checksum verified) into ~/.cache/extra-life/node. Only the final copy runs as root (Decky owns the folder).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
PLUGINS="$HOME/homebrew/plugins"
DEST="$PLUGINS/extra-life"
NODE_CACHE="$HOME/.cache/extra-life/node"

say() { printf '\033[1m- %s\033[0m\n' "$*"; }
[[ -d "$PLUGINS" ]] || { echo "Decky Loader not found ($PLUGINS missing); skipping plugin." >&2; exit 0; }

node_ok() { command -v node >/dev/null && [[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]]; }

ensure_node() {
    for d in "$HOME/.local/opt/node/bin" "$NODE_CACHE/bin"; do
        [[ -x "$d/node" ]] && export PATH="$d:$PATH"
    done
    node_ok && return
    local arch base sums file
    case "$(uname -m)" in
        x86_64)  arch=x64 ;;
        aarch64) arch=arm64 ;;
        *) echo "No Node.js build for $(uname -m); install Node.js >= 20 and re-run." >&2; exit 1 ;;
    esac
    base="https://nodejs.org/dist/latest-v22.x"
    say "Node.js not found; downloading Node.js 22 LTS ($arch) from nodejs.org to build the plugin"
    local tmp; tmp="$(mktemp -d)"
    sums="$(curl -fsSL "$base/SHASUMS256.txt")"
    file="$(grep -o "node-v[0-9.]*-linux-$arch.tar.xz" <<<"$sums" | head -1)"
    curl -fsSL "$base/$file" -o "$tmp/$file"
    (cd "$tmp" && grep " $file\$" <<<"$sums" | sha256sum -c --quiet -) || { echo "Node.js checksum mismatch" >&2; exit 1; }
    rm -rf "$NODE_CACHE" && mkdir -p "$NODE_CACHE"
    tar -xJf "$tmp/$file" -C "$NODE_CACHE" --strip-components=1
    rm -rf "$tmp"
    export PATH="$NODE_CACHE/bin:$PATH"
    node_ok || { echo "Node.js setup failed" >&2; exit 1; }
}

ensure_node
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
cd "$SRC"
say "building the Decky plugin (Node.js $(node --version))"
corepack pnpm install --frozen-lockfile --silent
corepack pnpm run --silent typecheck
corepack pnpm run --silent build >/dev/null

# Stage the plugin, then copy it into place.
STAGE="$SRC/build/extra-life"
rm -rf "$STAGE"
mkdir -p "$STAGE/dist"
cp plugin.json package.json main.py "$STAGE/"
for f in LICENSE; do [[ -f "$SRC/../$f" ]] && cp "$SRC/../$f" "$STAGE/"; done
cp dist/index.js "$STAGE/dist/"

# Copy next to (not inside) the watched plugins folder, swap it in with one rename, then restart Decky:
# its hot reload trips over half-copied folders.
TMP="$HOME/homebrew/.extra-life.tmp"
COPY=(sh -c 'rm -rf "$3" && cp -r "$2" "$3" && rm -rf "$1" && mv "$3" "$1" && { systemctl restart plugin_loader 2>/dev/null || true; }' _ "$DEST" "$STAGE" "$TMP")
if [[ -w "$PLUGINS" ]]; then
    "${COPY[@]}"
elif [[ -t 0 || -n "${SUDO_ASKPASS:-}" ]]; then
    say "copying the plugin into $PLUGINS and restarting Decky needs your password (Decky owns that folder)"
    sudo ${SUDO_ASKPASS:+-A} -p "[sudo] password to install the Extra Life Decky plugin: " "${COPY[@]}"
else
    echo "Built and staged at $STAGE. To install, run decky-plugin/install.sh in a terminal (asks for sudo)." >&2
    exit 2
fi
say "Decky plugin installed ($DEST); Decky loads it within a few seconds"
