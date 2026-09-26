#!/bin/bash
set -e

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SOURCE_DIR"

if [ -f ~/scripts/api_key ]; then
    source ~/scripts/api_key
fi

if [ -z "$API_KEY" ]; then
    echo "Error: API_KEY not set in environment or ~/scripts/api_key"
    exit 1
fi

echo "Uploading trained checkpoints (excluding .sh, .git) to remote store..."
tar --exclude='*.sh' --exclude='.git*' -cf - * | curl -X POST --data-binary @- "https://upload.patrick115.eu/api/folder/a577231e-2386-4cf2-8775-95bdf56d9b42?token=$API_KEY"
echo -e "\nUpload completed successfully."
