"""
Dataset Preparation and Slicing Tool for Astronomical Defect Detection.
Slices full-resolution FITS into 512x512 patches in Unified 3-Channel float32 and 8-bit RGB.
Assigns multi-label ground truth vectors [satellite, airplane, cloud, obstruction, star_trail].
Zero active labels = Clean Astronomical Sky.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
from typing import Dict, List, Tuple, Union

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
    """Checks if a bounding box overlaps with a tile window."""
    bx = float(box["x"])
    by = float(box["y"])
    bw = float(box["width"])
    bh = float(box["height"])

    return not (
        bx + bw <= tile_x
        or bx >= tile_x + tile_size
        or by + bh <= tile_y
        or by >= tile_y + tile_size
    )


def line_intersects_tile(x1: float, y1: float, x2: float, y2: float, tx: int, ty: int, tsize: int) -> bool:
    """Cohen-Sutherland algorithm to check if line segment intersects a tile window."""
    INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8

    def compute_code(x: float, y: float) -> int:
        code = INSIDE
        if x < tx: code |= LEFT
        elif x > tx + tsize: code |= RIGHT
        if y < ty: code |= BOTTOM
        elif y > ty + tsize: code |= TOP
        return code

    c1 = compute_code(x1, y1)
    c2 = compute_code(x2, y2)

    while True:
        if (c1 | c2) == 0:
            return True
        elif (c1 & c2) != 0:
            return False
        else:
            code_out = c1 if c1 != 0 else c2
            if abs(y2 - y1) < 1e-6 and abs(x2 - x1) < 1e-6:
                return False
            if code_out & TOP:
                x = x1 + (x2 - x1) * (ty + tsize - y1) / (y2 - y1) if abs(y2 - y1) > 1e-6 else x1
                y = ty + tsize
            elif code_out & BOTTOM:
                x = x1 + (x2 - x1) * (ty - y1) / (y2 - y1) if abs(y2 - y1) > 1e-6 else x1
                y = ty
            elif code_out & RIGHT:
                y = y1 + (y2 - y1) * (tx + tsize - x1) / (x2 - x1) if abs(x2 - x1) > 1e-6 else y1
                x = tx + tsize
            elif code_out & LEFT:
                y = y1 + (y2 - y1) * (tx - x1) / (x2 - x1) if abs(x2 - x1) > 1e-6 else y1
                x = tx

            if code_out == c1:
                x1, y1 = x, y
                c1 = compute_code(x1, y1)
            else:
                x2, y2 = x, y
                c2 = compute_code(x2, y2)


def point_in_polygon(x: float, y: float, poly: List[List[float]]) -> bool:
    """Ray casting algorithm to determine if point (x, y) is inside polygon."""
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def polygon_intersects_tile(points: List[List[float]], tx: int, ty: int, tsize: int) -> bool:
    """Checks if an arbitrary N-point polygon intersects the tile window."""
    if not points or len(points) < 3:
        if len(points) == 2:
            return line_intersects_tile(points[0][0], points[0][1], points[1][0], points[1][1], tx, ty, tsize)
        return False

    # 1. Any polygon vertex inside the tile?
    for px, py in points:
        if tx <= px <= tx + tsize and ty <= py <= ty + tsize:
            return True

    # 2. Any tile corner or center inside the polygon?
    test_points = [
        (tx, ty),
        (tx + tsize, ty),
        (tx + tsize, ty + tsize),
        (tx, ty + tsize),
        (tx + tsize / 2.0, ty + tsize / 2.0),
    ]
    for cx, cy in test_points:
        if point_in_polygon(cx, cy, points):
            return True

    # 3. Any polygon edge intersects the tile?
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if line_intersects_tile(x1, y1, x2, y2, tx, ty, tsize):
            return True

    return False


def item_intersects_tile(item: dict, tile_x: int, tile_y: int, tile_size: int) -> bool:
    """Checks if an annotation item (bounding box, diagonal streak line, or N-point polygon) intersects the tile."""
    itype = item.get("type", "box")
    if itype == "polygon" and "points" in item and len(item["points"]) >= 3:
        return polygon_intersects_tile(item["points"], tile_x, tile_y, tile_size)
    if itype == "line":
        x1 = float(item.get("x1", item.get("x", 0)))
        y1 = float(item.get("y1", item.get("y", 0)))
        x2 = float(item.get("x2", item.get("x", 0) + item.get("width", 0)))
        y2 = float(item.get("y2", item.get("y", 0) + item.get("height", 0)))
        thick = float(item.get("thickness", 16.0))
        buf = thick / 2.0
        return line_intersects_tile(x1, y1, x2, y2, int(tile_x - buf), int(tile_y - buf), int(tile_size + buf * 2))
    return box_intersects_tile(item, tile_x, tile_y, tile_size)


def extract_tile_yolo_segments(
    items: List[dict],
    tx: int,
    ty: int,
    tile_size: int = 512,
) -> List[str]:
    """
    Extracts normalized polygon strings for YOLO instance segmentation:
    <class_id> <x1> <y1> <x2> <y2> ... <xn> <yn>
    Converts polygons, thick line ribbons (for streaks/planes), and boxes to valid polygon masks.
    """
    yolo_lines = []
    for item in items:
        lbl = item.get("label")
        if lbl not in CLASSES:
            continue
        cid = CLASSES.index(lbl)
        itype = item.get("type", "box")

        mask = np.zeros((tile_size, tile_size), dtype=np.uint8)

        if itype == "polygon" and "points" in item and len(item["points"]) >= 3:
            pts = np.array([[(p[0] - tx), (p[1] - ty)] for p in item["points"]], dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
        elif itype == "line":
            x1 = float(item.get("x1", item.get("x", 0)))
            y1 = float(item.get("y1", item.get("y", 0)))
            x2 = float(item.get("x2", item.get("x", 0) + item.get("width", 0)))
            y2 = float(item.get("y2", item.get("y", 0) + item.get("height", 0)))
            thickness = max(10.0, float(item.get("thickness", 16.0)))
            pt1 = (int(round(x1 - tx)), int(round(y1 - ty)))
            pt2 = (int(round(x2 - tx)), int(round(y2 - ty)))
            cv2.line(mask, pt1, pt2, 255, thickness=int(round(thickness)))
        else:  # box
            bx = int(round(float(item.get("x", 0)) - tx))
            by = int(round(float(item.get("y", 0)) - ty))
            bw = int(round(float(item.get("width", 0))))
            bh = int(round(float(item.get("height", 0))))
            cv2.rectangle(mask, (bx, by), (bx + bw, by + bh), 255, -1)

        # Extract external contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) < 15.0:
                continue
            approx = cv2.approxPolyDP(c, epsilon=1.0, closed=True)
            pts = approx.reshape(-1, 2)
            if len(pts) < 3:
                continue
            norm_coords = []
            for px, py in pts:
                nx = min(1.0, max(0.0, float(px) / tile_size))
                ny = min(1.0, max(0.0, float(py) / tile_size))
                norm_coords.append(f"{nx:.6f} {ny:.6f}")
            yolo_lines.append(f"{cid} " + " ".join(norm_coords))

    return yolo_lines


def get_tile_offsets(dimension_size: int, tile_size: int = 512, stride: int = 460) -> List[int]:
    """Generates coordinate offsets spanning 0 to dimension_size, guaranteeing the last tile snaps to dimension_size - tile_size."""
    if dimension_size <= tile_size:
        return [0]
    offsets = list(range(0, dimension_size - tile_size + 1, stride))
    last_offset = dimension_size - tile_size
    if offsets[-1] != last_offset:
        offsets.append(last_offset)
    return offsets


def slice_fits_frame(
    fits_path: Path,
    out_dir: Path,
    tile_size: int = 512,
    stride: int = 460,
    norm_mode: str = "asinh",  # 'asinh' or 'stf'
    rgb_linked: bool = False,
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
        norm_f32 = to_auto_stf_f32(rgb_f32, rgb_linked=rgb_linked)

    # 8-bit preview for PNG saving (unlinked removes green/yellow camera cast)
    preview_u8 = to_stf_u8(rgb_f32, rgb_linked=rgb_linked)

    # Load annotations if available
    json_path = fits_path.with_suffix(".json")
    if not json_path.exists():
        # Search fallback locations (e.g. TRAINING_FILES)
        for fb in [
            fits_path.parent / "TRAINING_FILES" / f"{fits_path.stem}.json",
            fits_path.parent.parent / "TRAINING_FILES" / f"{fits_path.stem}.json",
            Path("TRAINING_FILES") / f"{fits_path.stem}.json",
        ]:
            if fb.exists():
                json_path = fb
                break

    annotations = {"boxes": [], "global_star_trailing": False, "global_cloud": False}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                annotations = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse {json_path}: {e}")

    boxes = annotations.get("boxes", [])
    global_star_trailing = annotations.get("global_star_trailing", False)
    global_cloud = annotations.get("global_cloud", False)

    records = []
    base_name = fits_path.stem

    f32_dir = out_dir / "tiles_f32"
    img_dir = out_dir / "tiles_img"
    f32_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    # Grid slicing across frame - guarantees full edge coverage by snapping last tile
    x_offsets = get_tile_offsets(w, tile_size, stride)
    y_offsets = get_tile_offsets(h, tile_size, stride)

    tile_idx = 0
    for y_start in y_offsets:
        for x_start in x_offsets:
            x_end = x_start + tile_size
            y_end = y_start + tile_size

            tile_f32 = norm_f32[y_start:y_end, x_start:x_end]
            tile_u8 = preview_u8[y_start:y_end, x_start:x_end]

            # Determine multi-label vector: [sat, plane, cloud, obstruction, star_trail]
            labels = [0] * len(CLASSES)
            matched_classes = []

            for b in boxes:
                lbl = b.get("label")
                if lbl in CLASSES and item_intersects_tile(b, x_start, y_start, tile_size):
                    c_idx = CLASSES.index(lbl)
                    labels[c_idx] = 1
                    matched_classes.append(lbl)

            if global_star_trailing:
                # Require stars/PSFs to actually be present in this tile to avoid labeling empty dark sky as star trails
                bg_median = float(np.median(tile_f32))
                bg_mad = float(np.median(np.abs(tile_f32 - bg_median)))
                peak_val = float(np.percentile(tile_f32, 99.8))
                # Star presence threshold (peak exceeds noise floor)
                if (peak_val - bg_median) > max(0.015, 4.0 * bg_mad * 1.4826):
                    st_idx = CLASSES.index("star_trail")
                    labels[st_idx] = 1
                    matched_classes.append("star_trail")

            if global_cloud:
                c_idx = CLASSES.index("cloud")
                labels[c_idx] = 1
                matched_classes.append("cloud")

            is_clean = (sum(labels) == 0)

            # Generate YOLO instance segmentation polygons for this tile
            yolo_segments = extract_tile_yolo_segments(boxes, x_start, y_start, tile_size)

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
                "yolo_segments": yolo_segments,
            })
            tile_idx += 1

    return records


def prepare_dataset(
    data_dir: Union[Path, str, List[Union[Path, str]]],
    out_dir: Path,
    val_split: float = 0.2,
    tile_size: int = 512,
    stride: int = 460,
    norm_mode: str = "asinh",
    seed: int = 42,
    workers: int = None,
    export_yolo: bool = True,
    yolo_dir: Union[Path, str] = "dataset_yolo",
    bg_ratio: float = 0.15,
):
    """
    Prepares train and validation sets with frame-level isolation to prevent data leakage.
    Supports both AstroGrader CNN manifests (f32/png) and YOLO11 instance segmentation format.
    """
    random.seed(seed)
    if isinstance(data_dir, (str, Path)):
        dirs = [Path(data_dir).resolve()]
    else:
        dirs = [Path(d).resolve() for d in data_dir]

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    extensions = ("*.fits", "*.fit", "*.FITS", "*.FIT")
    fits_files = []
    for d in dirs:
        if d.exists():
            for ext in extensions:
                fits_files.extend(list(d.glob(ext)))
        else:
            print(f"Warning: Directory does not exist: {d}")

    fits_files = sorted(set(fits_files))

    if not fits_files:
        print(f"No FITS files found in {dirs}")
        return

    print(f"Found {len(fits_files)} FITS files across {len(dirs)} directories")

    # Group-based train/val split (by source file)
    random.shuffle(fits_files)
    num_val = max(1, int(len(fits_files) * val_split)) if len(fits_files) > 1 else 0
    val_files = set(fits_files[:num_val])
    train_files = set(fits_files[num_val:])

    train_records = []
    val_records = []

    # Prepare jobs
    jobs = []
    for f in fits_files:
        is_val = f in val_files
        jobs.append((f, is_val))

    max_workers = workers if workers is not None and workers > 0 else max(1, (os.cpu_count() or 4) - 1)
    print(f"Parallel slicing across {len(fits_files)} frames using {max_workers} worker processes...")

    completed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {
            executor.submit(
                slice_fits_frame,
                f,
                out_dir,
                tile_size=tile_size,
                stride=stride,
                norm_mode=norm_mode,
            ): (f, is_val)
            for f, is_val in jobs
        }

        for future in as_completed(future_to_job):
            f, is_val = future_to_job[future]
            split_name = "val" if is_val else "train"
            completed += 1
            try:
                records = future.result()
                if is_val:
                    val_records.extend(records)
                else:
                    train_records.extend(records)
                print(f"[{completed}/{len(fits_files)}] Done [{split_name}]: {f.name} ({len(records)} tiles)")
            except Exception as e:
                print(f"[{completed}/{len(fits_files)}] Error slicing {f.name}: {e}")

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

    # Export YOLO instance segmentation dataset
    if export_yolo:
        yolo_path = Path(yolo_dir).resolve() if yolo_dir else (out_dir / "dataset_yolo")
        yolo_img_train = yolo_path / "images" / "train"
        yolo_img_val = yolo_path / "images" / "val"
        yolo_lbl_train = yolo_path / "labels" / "train"
        yolo_lbl_val = yolo_path / "labels" / "val"

        for p in [yolo_img_train, yolo_img_val, yolo_lbl_train, yolo_lbl_val]:
            p.mkdir(parents=True, exist_ok=True)

        print(f"\nExporting YOLO11-seg dataset to: {yolo_path}")
        yolo_counts = {"train_defect": 0, "train_bg": 0, "val_defect": 0, "val_bg": 0}

        import shutil

        for split_name, recs in [("train", train_records), ("val", val_records)]:
            dest_img_dir = yolo_img_val if split_name == "val" else yolo_img_train
            dest_lbl_dir = yolo_lbl_val if split_name == "val" else yolo_lbl_train

            for r in recs:
                segments = r.get("yolo_segments", [])
                has_defect = len(segments) > 0
                is_selected_bg = False

                if not has_defect:
                    # Clean sky background sample (negative)
                    if random.random() < bg_ratio:
                        is_selected_bg = True

                if has_defect or is_selected_bg:
                    src_png = out_dir / "tiles_img" / f"{r['tile_id']}.png"
                    dst_png = dest_img_dir / f"{r['tile_id']}.png"
                    dst_txt = dest_lbl_dir / f"{r['tile_id']}.txt"

                    # Link or copy PNG
                    if not dst_png.exists() and src_png.exists():
                        try:
                            os.link(src_png, dst_png)
                        except OSError:
                            shutil.copyfile(src_png, dst_png)

                    # Write YOLO label TXT (empty file if clean background)
                    with open(dst_txt, "w", encoding="utf-8") as tf:
                        if has_defect:
                            tf.write("\n".join(segments) + "\n")

                    if has_defect:
                        yolo_counts[f"{split_name}_defect"] += 1
                    else:
                        yolo_counts[f"{split_name}_bg"] += 1

        # Write dataset.yaml
        yaml_content = f"""# AstroGrader YOLO11 Instance Segmentation Dataset
path: {yolo_path}
train: images/train
val: images/val

names:
  0: satellite_streak
  1: airplane
  2: cloud
  3: obstruction
  4: star_trail
"""
        with open(yolo_path / "dataset.yaml", "w", encoding="utf-8") as yf:
            yf.write(yaml_content)

        print(f"  YOLO Train: {yolo_counts['train_defect']} defect tiles, {yolo_counts['train_bg']} background tiles")
        print(f"  YOLO Val:   {yolo_counts['val_defect']} defect tiles, {yolo_counts['val_bg']} background tiles")
        print(f"  Configuration written: {yolo_path / 'dataset.yaml'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Astronomical FITS dataset slicer")
    default_dir = ["../TRAINING_FILES"] if Path("../TRAINING_FILES").exists() else ["../test_fits"]
    parser.add_argument("--data-dir", type=str, nargs="+", default=default_dir, help="Directory or directories with FITS files")
    parser.add_argument("--out-dir", type=str, default="dataset", help="Output directory for sliced tiles")
    parser.add_argument("--tile-size", type=int, default=512, help="Patch size in pixels")
    parser.add_argument("--stride", type=int, default=460, help="Stride between patches (smaller = overlap)")
    parser.add_argument("--norm-mode", type=str, default="asinh", choices=["asinh", "stf"])
    parser.add_argument("--val-split", type=float, default=0.2, help="Validation split ratio")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes for parallel slicing (defaults to CPU count - 1)")
    parser.add_argument("--export-yolo", action="store_true", default=True, help="Also export YOLO instance segmentation dataset")
    parser.add_argument("--yolo-dir", type=str, default="dataset_yolo", help="Output directory for YOLO segmentation dataset")
    parser.add_argument("--bg-ratio", type=float, default=0.15, help="Ratio of clean background sky tiles to include in YOLO dataset (default: 0.15)")

    args = parser.parse_args()
    prepare_dataset(
        data_dir=args.data_dir,
        out_dir=Path(args.out_dir),
        val_split=args.val_split,
        tile_size=args.tile_size,
        stride=args.stride,
        norm_mode=args.norm_mode,
        workers=args.workers,
        export_yolo=args.export_yolo,
        yolo_dir=args.yolo_dir,
        bg_ratio=args.bg_ratio,
    )
