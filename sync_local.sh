#!/usr/bin/env bash
# Sync raw astronomical images (FITS/TIFF) from local directory or remote Proxmox storage
#
# Usage:
#   ./sync_local.sh [target_or_source_dir] [options]
#
# Options:
#   --quick, -q          Fast streaming mode: use remote 'send' and local 'receive'
#   --rsync              Force legacy rsync batch transfer mode
#   --host <host>        SSH remote host (default: proxmox)
#   --refresh            Rebuild remote file index cache (find_astro_files.py)
#   --dry-run            Locate files without downloading/copying
#
# Examples:
#   ./sync_local.sh --quick
#   ./sync_local.sh -q
#   ./sync_local.sh --quick --dry-run
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node "$DIR/scripts/sync_local.js" "$@"
