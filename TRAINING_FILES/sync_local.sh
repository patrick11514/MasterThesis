#!/usr/bin/env bash
# Sync raw astronomical images (FITS/TIFF) into TRAINING_FILES
#
# Usage:
#   ./sync_local.sh [source_dir] [options]
#
# Examples:
#   # Search local folder on this PC:
#   ./sync_local.sh /path/to/local/astro_images
#   ./sync_local.sh --local --source-dir /media/external/ASTRO
#
#   # Search remote Proxmox storage over SSH:
#   ./sync_local.sh
#   ./sync_local.sh --host proxmox --remote-dir /mnt/HDD/ASTRO
#
#   # Test run without copying:
#   ./sync_local.sh /path/to/local/astro_images --dry-run
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node "$DIR/../scripts/sync_local.js" "$DIR" "$@"
