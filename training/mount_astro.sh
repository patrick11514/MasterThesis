#!/usr/bin/env bash
# mount_astro.sh
# Mounts the Astro SMB share (10.10.10.236) using high-performance kernel CIFS.
# Much faster than GNOME GVFS FUSE mounts.

set -euo pipefail

SERVER="10.10.10.236"
SHARE="Astro"
MOUNT_POINT="/mnt/astro"
READ_ONLY=0

print_usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -m, --mount-point DIR   Target mount directory (default: /mnt/astro)
  -s, --server IP         Server address (default: 10.10.10.236)
  --share NAME            SMB share name (default: Astro)
  --ro                    Mount as read-only
  -u, --unmount           Unmount the share
  -h, --help              Show this help message

Examples:
  ./mount_astro.sh
  ./mount_astro.sh --unmount
  ./mount_astro.sh -m /mnt/nas_astro
EOF
}

UNMOUNT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--mount-point)
            MOUNT_POINT="$2"
            shift 2
            ;;
        -s|--server)
            SERVER="$2"
            shift 2
            ;;
        --share)
            SHARE="$2"
            shift 2
            ;;
        --ro)
            READ_ONLY=1
            shift
            ;;
        -u|--unmount)
            UNMOUNT=1
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

if [[ "$UNMOUNT" -eq 1 ]]; then
    if mountpoint -q "$MOUNT_POINT"; then
        echo "[+] Unmounting $MOUNT_POINT..."
        sudo umount "$MOUNT_POINT"
        echo "[+] Successfully unmounted $MOUNT_POINT"
    else
        echo "[-] $MOUNT_POINT is not mounted."
    fi
    exit 0
fi

# Check if already mounted
if mountpoint -q "$MOUNT_POINT"; then
    echo "[!] $MOUNT_POINT is already mounted."
    echo "    To unmount, run: $(basename "$0") --unmount"
    exit 0
fi

# Ensure mount point exists
if [[ ! -d "$MOUNT_POINT" ]]; then
    echo "[+] Creating mount directory: $MOUNT_POINT"
    sudo mkdir -p "$MOUNT_POINT"
fi

# Build mount options:
# - guest: anonymous login without credentials
# - uid/gid: map files to current user
# - rsize=1048576: 1 MB read buffer size for maximum throughput on multi-MB FITS frames
# - cache=loose,actimeo=60: client-side metadata caching to avoid network round-trips
# - iocharset=utf8: proper unicode filename support
MOUNT_OPTS="guest,uid=$(id -u),gid=$(id -g),iocharset=utf8,file_mode=0777,dir_mode=0777,rsize=1048576,cache=loose,actimeo=60"

if [[ "$READ_ONLY" -eq 1 ]]; then
    MOUNT_OPTS="${MOUNT_OPTS},ro"
fi

echo "[+] Mounting //$SERVER/$SHARE to $MOUNT_POINT (Kernel CIFS)..."
sudo mount -t cifs "//$SERVER/$SHARE" "$MOUNT_POINT" -o "$MOUNT_OPTS"

if mountpoint -q "$MOUNT_POINT"; then
    echo "[✔] Successfully mounted //$SERVER/$SHARE -> $MOUNT_POINT"
    echo ""
    echo "You can now run find_airplanes.py with:"
    echo "  python find_airplanes.py --target-dir $MOUNT_POINT/PROJECTS/GLOBAL_TRASH --workers 32 ..."
fi
