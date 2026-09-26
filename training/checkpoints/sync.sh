#!/bin/bash
set -e

DEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEST_DIR"

if [ -f ~/scripts/api_key ]; then
    source ~/scripts/api_key
fi

if [ -z "$API_KEY" ]; then
    echo "Error: API_KEY not set in environment or ~/scripts/api_key"
    exit 1
fi

echo "Downloading and syncing trained checkpoints from remote store..."
curl -s "https://upload.patrick115.eu/api/folder/a577231e-2386-4cf2-8775-95bdf56d9b42?token=$API_KEY" | tar -xf -
echo "Sync completed successfully."
