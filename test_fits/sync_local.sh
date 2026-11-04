#!/usr/bin/env bash
# Sync raw astronomical images (FITS/TIFF) into test_fits
#
# Usage:
#   ./sync_local.sh [source_dir] [options]
#
# Examples:
#   ./sync_local.sh --quick
#   ./sync_local.sh -q
#   ./sync_local.sh --quick --dry-run
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node "$DIR/../scripts/sync_local.js" "$DIR" "$@"
