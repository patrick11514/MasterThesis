"""
Dataset Preparation and Slicing Tool for Astronomical Defect Detection.
Slices full-resolution FITS into 512x512 patches in Unified 3-Channel float32 and 8-bit RGB.
Assigns multi-label ground truth vectors [satellite, airplane, cloud, obstruction, star_trail].
Zero active labels = Clean Astronomical Sky.
"""

import argparse
import json
from pathlib import Path
import random
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image

from fits_utils import (
    load_fits_unified_rgb,
    to_asinh_f32,
    to_auto_stf_f32,
    to_stf_u8,
)

CLASSES = [
    "satellite_streak",
    "airplane",
    "cloud",
    "obstruction",
    "star_trail",
]


def box_intersects_tile(box: dict, tile_x: int, tile_y: int, tile_size: int) -> bool:
    """Checks if a bounding box overlaps with a 512x512 tile window."""
    bx = box["x"]
    by = box["y"]
    bw = box["width"]
    bh = box["height"]

    # Box coordinates
    b_x1, b_y1 = bx, by
    b_x2, b_y2 = bx + bw, by + bh

    # Tile coordinates
    t_x1, t_y1 = tile_x, tile_y
    t_x2, t_y2 = tile_x + tile_size, tile_y + tile_size

    # Intersection rectangle
    ix1 = max(b_x1, t_x1)
    iy1 = max(b_y1, t_y1)
    ix2 = min(b_x2, t_x2)
    iy2 = min(b_y2, t_y2)

    if ix2 > ix1 and iy2 > iy1:
        # Check that intersection area is non-trivial (at least 20 pixels)
        inter_area = (ix2 - ix1) * (iy2 - iy1)
        return inter_area >= 20.0
    return False


def slice_fits_frame(
    fits_path: Path,
    out_dir: Path,
    tile_size: int = 512,
    stride: int = 460,
    norm_mode: str = "asinh",  # 'asinh' or 'stf'
) -> List[Dict]:
    """
    Slices a single FITS frame into 512x512 tiles and generates metadata records.
    """
    rgb_f32, meta = load_fits_unified_rgb(fits_path)
    h, w, _ = rgb_f32.shape

    # Pre-normalize the full image to desired float representation
    if norm_mode == "asinh":
        norm_f32 = to_asinh_f32(rgb_f32)
    else:
        norm_f32 = to_auto_stf_f32(rgb_f32)

    # 8-bit preview for PNG saving
    preview_u8 = to_stf_u8(rgb_f32)

    # Load annotations if available
    json_path = fits_path.with_suffix(".json")
    annotations = {"boxes": [], "global_star_trailing": False}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                annotations = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse {json_path}: {e}")

    boxes = annotations.get("boxes", [])
    global_star_trailing = annotations.get("global_star_trailing", False)

    records = []
    base_name = fits_path.stem

    f32_dir = out_dir / "tiles_f32"
    img_dir = out_dir / "tiles_img"
    f32_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    # Grid slicing across frame
    tile_idx = 0
    for y in range(0, max(1, h - tile_size + 1), stride):
        for x in range(0, max(1, w - tile_size + 1), stride):
            # Ensure crop stays within image boundaries
            x_end = min(x + tile_size, w)
            y_end = min(y + tile_size, h)
            x_start = max(0, x_end - tile_size)
            y_start = max(0, y_end - tile_size)

            tile_f32 = norm_f32[y_start:y_end, x_start:x_end]
            tile_u8 = preview_u8[y_start:y_end, x_start:x_end]

            # Determine multi-label vector: [sat, plane, cloud, obstruction, star_trail]
            labels = [0] * len(CLASSES)
            matched_classes = []

            for b in boxes:
                lbl = b.get("label")
                if lbl in CLASSES and box_intersects_tile(b, x_start, y_start, tile_size):
                    c_idx = CLASSES.index(lbl)
                    labels[c_idx] = 1
                    matched_classes.append(lbl)

            if global_star_trailing:
                st_idx = CLASSES.index("star_trail")
                labels[st_idx] = 1
                matched_classes.append("star_trail")

            is_clean = (sum(labels) == 0)

            tile_id = f"{base_name}_x{x_start}_y{y_start}"
            npy_path = f32_dir / f"{tile_id}.npy"
            png_path = img_dir / f"{tile_id}.png"

            # Save float32 planar NCHW [3, 512, 512] for direct PyTorch/ONNX loading
            planar_f32 = np.transpose(tile_f32, (2, 0, 1)).astype(np.float32)
            np.save(npy_path, planar_f32)

            # Save 8-bit PNG
            pil_tile = Image.fromarray(tile_u8)
            pil_tile.save(png_path, format="PNG")

            records.append({
                "tile_id": tile_id,
                "source_file": fits_path.name,
                "x": x_start,
                "y": y_start,
                "width": tile_size,
                "height": tile_size,
                "f32_path": str(npy_path.relative_to(out_dir.parent)),
                "img_path": str(png_path.relative_to(out_dir.parent)),
                "labels": labels,  # multi-hot vector [0, 0, 1, 0, 0]
                "classes": list(set(matched_classes)),
                "is_clean": is_clean,
            })
            tile_idx += 1

    return records


def prepare_dataset(
    data_dir: Path,
    out_dir: Path,
    val_split: float = 0.2,
    tile_size: int = 512,
    stride: int = 460,
    norm_mode: str = "asinh",
    seed: int = 42,
):
    """
    Prepares train and validation sets with frame-level isolation to prevent data leakage.
    """
    random.seed(seed)
    data_dir = Path(data_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    extensions = ("*.fits", "*.fit", "*.FITS", "*.FIT")
    fits_files = []
    for ext in extensions:
        fits_files.extend(list(data_dir.glob(ext)))
    fits_files = sorted(set(fits_files))

    if not fits_files:
        print(f"No FITS files found in {data_dir}")
        return

    print(f"Found {len(fits_files)} FITS files in {data_dir}")

    # Group-based train/val split (by source file)
    random.shuffle(fits_files)
    num_val = max(1, int(len(fits_files) * val_split)) if len(fits_files) > 1 else 0
    val_files = set(fits_files[:num_val])
    train_files = set(fits_files[num_val:])

    train_records = []
    val_records = []

    for f in fits_files:
        is_val = f in val_files
        split_name = "val" if is_val else "train"
        print(f"Slicing [{split_name}]: {f.name}...")
        try:
            records = slice_fits_frame(f, out_dir, tile_size=tile_size, stride=stride, norm_mode=norm_mode)
            if is_val:
                val_records.extend(records)
            else:
                train_records.extend(records)
        except Exception as e:
            print(f"  Error slicing {f.name}: {e}")

    # Write manifests
    with open(out_dir / "train_manifest.json", "w", encoding="utf-8") as fp:
        json.dump(train_records, fp, indent=2)

    with open(out_dir / "val_manifest.json", "w", encoding="utf-8") as fp:
        json.dump(val_records, fp, indent=2)

    # Class summary statistics
    print("\nDataset Preparation Complete!")
    print(f"Total training tiles:   {len(train_records)}")
    print(f"Total validation tiles: {len(val_records)}")

    for split_name, recs in [("Train", train_records), ("Val", val_records)]:
        clean_count = sum(1 for r in recs if r["is_clean"])
        defects_count = len(recs) - clean_count
        print(f"\n{split_name} Set Summary:")
        print(f"  Clean sky tiles:  {clean_count}")
        print(f"  Defect tiles:     {defects_count}")
        for i, cls_name in enumerate(CLASSES):
            c_count = sum(1 for r in recs if r["labels"][i] == 1)
            print(f"    - {cls_name}: {c_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Astronomical FITS dataset slicer")
    parser.add_argument("--data-dir", type=str, default="../test_fits", help="Directory with FITS files")
    parser.add_argument("--out-dir", type=str, default="dataset", help="Output directory for sliced tiles")
    parser.add_argument("--tile-size", type=int, default=512, help="Patch size in pixels")
    parser.add_argument("--stride", type=int, default=460, help="Stride between patches (smaller = overlap)")
    parser.add_argument("--norm-mode", type=str, default="asinh", choices=["asinh", "stf"])
    parser.add_argument("--val-split", type=float, default=0.2, help="Validation split ratio")

    args = parser.parse_args()
    prepare_dataset(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        val_split=args.val_split,
        tile_size=args.tile_size,
        stride=args.stride,
        norm_mode=args.norm_mode,
    )
