#!/usr/bin/env python3
"""
find_astro_files.py - Fast astronomical frame locator for Proxmox / remote host.

Searches /mnt/HDD/ASTRO for specified target filenames or stems.
Reads targets from stdin (one filename per line) or command line arguments.
Outputs tab-separated: <requested_name>\t<full_path>

Can be placed on Proxmox at:
  /usr/local/bin/find_astro_files.py
  (or ~/find_astro_files.py)
"""

import argparse
import json
import os
import sys
import time

CACHE_FILE = "/tmp/astro_files_index.json"
CACHE_MAX_AGE_HOURS = 24

def build_or_load_index(root_dir, use_cache=True, force_refresh=False):
    index = {} # stem_lower: relative_or_full_path

    if use_cache and not force_refresh and os.path.exists(CACHE_FILE):
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            if (time.time() - mtime) < (CACHE_MAX_AGE_HOURS * 3600):
                with open(CACHE_FILE, "r") as f:
                    index = json.load(f)
                sys.stderr.write(f"[Cache Hit] Loaded {len(index)} indexed files from {CACHE_FILE}\n")
                sys.stderr.flush()
                return index
        except Exception as e:
            sys.stderr.write(f"[Cache Warning] Failed to read cache: {e}\n")

    sys.stderr.write(f"Indexing storage tree at {root_dir}...\n")
    sys.stderr.flush()

    valid_exts = {".fits", ".fit", ".fts", ".tif", ".tiff"}
    scanned_dirs = 0

    for root, dirs, files in os.walk(root_dir, followlinks=True):
        scanned_dirs += 1
        if scanned_dirs % 50 == 0:
            sys.stderr.write(f"\rScanning... {len(index)} files cataloged ({scanned_dirs} directories)")
            sys.stderr.flush()

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                stem = os.path.splitext(f)[0].lower()
                full_path = os.path.join(root, f)
                # Store exact filename and stem
                index[f.lower()] = full_path
                index[stem] = full_path

    sys.stderr.write(f"\rIndexing complete! Indexed {len(index)} entries across {scanned_dirs} directories.\n")
    sys.stderr.flush()

    if use_cache:
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(index, f)
        except Exception:
            pass

    return index

def main():
    parser = argparse.ArgumentParser(description="Find astronomical image files on storage")
    parser.add_argument("--dir", default="/mnt/HDD/ASTRO", help="Root storage directory")
    parser.add_argument("--no-cache", action="store_true", help="Disable index caching")
    parser.add_argument("--refresh", action="store_true", help="Force rebuild cache")
    parser.add_argument("files", nargs="*", help="Filenames to locate (or pipe via stdin)")
    args = parser.parse_args()

    targets = list(args.files)
    if not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line:
                targets.append(line)

    if not targets:
        sys.stderr.write("No target files provided.\n")
        sys.exit(0)

    root_dir = os.path.abspath(args.dir)
    if not os.path.isdir(root_dir):
        sys.stderr.write(f"ERROR: Root directory not found: {root_dir}\n")
        sys.exit(1)

    index = build_or_load_index(root_dir, use_cache=not args.no_cache, force_refresh=args.refresh)

    found_count = 0
    for target in targets:
        target_lower = target.lower()
        stem_lower = os.path.splitext(target)[0].lower()

        # Match exact filename or stem
        path = index.get(target_lower) or index.get(stem_lower)
        if path and os.path.exists(path):
            print(f"{target}\t{path}")
            found_count += 1

    sys.stderr.write(f"Matched {found_count}/{len(targets)} requested files.\n")
    sys.stderr.flush()

if __name__ == "__main__":
    main()
