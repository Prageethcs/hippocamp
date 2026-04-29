#!/usr/bin/env bash
# Hippocamp installer.
#
# Usage:
#   curl -sSL https://hippocamp.so/install | bash
#   # or:
#   bash scripts/install.sh [host]
#
# Installs the hippocamp Python package with MCP + embedding extras,
# then wires it into the host of your choice (default: claude).
#
# Supported hosts: claude, claude-desktop, cursor, gemini-cli

set -euo pipefail

HOST="${1:-claude}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "hippocamp installer: python3 is required but not on PATH." >&2
    exit 1
fi

echo "→ Installing hippocamp..."
python3 -m pip install --upgrade --quiet 'hippocamp[mcp,embeddings]'

echo "→ Wiring hippocamp into ${HOST}..."
hippocamp setup "${HOST}"

echo ""
echo "Done. Memory lives at ~/.hippocamp/store.db."
echo "Run 'hippocamp inspect' anytime to see what's stored."
