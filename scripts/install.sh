#!/usr/bin/env bash
# Hippocamp installer.
#
# Usage:
#   curl -sSL https://hippocamp.run/install | bash                    # default: claude, local store
#   curl -sSL https://hippocamp.run/install | bash -s -- claude       # specify host
#   curl -sSL https://hippocamp.run/install | bash -s -- claude ~/Dropbox/Hippocamp
#
#   # or:
#   bash scripts/install.sh [host] [path]
#
# Installs hippocamp[mcp,embeddings] and wires it into the chosen host.
# If `path` is given, every machine that runs install.sh with the same
# path (and shares that folder via Dropbox / iCloud / Syncthing) will
# see the same memory.
#
# Supported hosts: claude, claude-desktop, cursor, gemini-cli

set -euo pipefail

HOST="${1:-claude}"
STORE_PATH="${2:-}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "hippocamp installer: python3 is required but not on PATH." >&2
    exit 1
fi

echo "→ Installing hippocamp..."
python3 -m pip install --upgrade --quiet 'hippocamp[mcp,embeddings]'

echo "→ Wiring hippocamp into ${HOST}..."
if [ -n "$STORE_PATH" ]; then
    hippocamp setup "$HOST" --path "$STORE_PATH"
else
    hippocamp setup "$HOST"
fi

echo ""
echo "Done. Restart ${HOST} and try: \"remember that I prefer terse replies\""
echo "Then in any later session: \"what do you remember about me?\""
