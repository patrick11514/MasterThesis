#!/usr/bin/env python3
"""
AstroGrader: YOLO11 Instance Segmentation Verification & Diagnostic Visualizer.
Runs YOLO11-seg inference across full-frame astronomical FITS files via tile slicing,
stitches pixel-accurate segmentation masks, and generates visual inspection overlays.
"""

import argparse
import glob
from pathlib import Path
import time
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
from ultralytics import YOLO

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fits_utils import (
    load_fits_unified_rgb,
    to_asinh_f32,
    to_auto_stf_f32,
    to_stf_u8,
    CLASSES,
)

CLASS_COLORS = {
    "satellite_streak": (229, 62, 62),    # Red
    "airplane": (237, 137, 54),           # Orange
    "cloud": (66, 153, 225),              # Blue
    "obstruction": (159, 122, 234),       # Purple
    "star_trail": (236, 201, 75),         # Yellow
}


def collect_fits_files(patterns: List[str]) -> List[Path]:
    """Expands list of files, directories, and glob patterns into sorted unique Path objects."""
    results = []
    for pat in patterns:
        p = Path(pat)
        if p.is_dir():
            for ext in ("*.fits", "*.fit", "*.FITS", "*.FIT"):
                results.extend(list(p.glob(ext)))
        elif p.is_file():
            results.append(p)
        else:
            matched = glob.glob(pat)
            if matched:
                results.extend([Path(m) for m in matched])
            else:
                print(f"Warning: No file matching '{pat}' found")

    seen = set()
    unique = []
    for f in results:
        resolved = f.resolve()
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            unique.append(resolved)
    return sorted(unique)


def get_tile_offsets(dimension_size: int, tile_size: int = 512, stride: int = 460) -> List[int]:
    """Generates coordinate offsets spanning 0 to dimension_size, guaranteeing edge coverage."""
    if dimension_size <= tile_size:
        return [0]
    offsets = list(range(0, dimension_size - tile_size + 1, stride))
    last_offset = dimension_size - tile_size
    if offsets[-1] != last_offset:
        offsets.append(last_offset)
    return offsets


def run_yolo_fullframe(
    model: YOLO,
    fits_path: Path,
    tile_size: int = 512,
    stride: int = 460,
    conf_threshold: float = 0.25,
    device: str = "cpu",
    rgb_linked: bool = False,
    mode: str = "stf",
) -> Tuple[np.ndarray, List[Dict], float]:
    """
    Loads a FITS frame, slices into tiles, runs YOLO11-seg inference,
    and returns the stretched preview RGB image, detected defect masks in frame coords, and runtime.
    """
    rgb_f32, meta = load_fits_unified_rgb(fits_path)
    h, w, _ = rgb_f32.shape

    # Stretched 8-bit image for YOLO inference and final display
    stf_u8 = to_stf_u8(rgb_f32, rgb_linked=rgb_linked, mode=mode)

    x_offsets = get_tile_offsets(w, tile_size, stride)
    y_offsets = get_tile_offsets(h, tile_size, stride)

    # Collect all tile coordinates and numpy images
    tiles = []
    coords = []
    for y in y_offsets:
        for x in x_offsets:
            patch = stf_u8[y : y + tile_size, x : x + tile_size]
            tiles.append(patch)
            coords.append((x, y))

    t0 = time.perf_counter()

    # Batch inference with YOLO11-seg
    batch_size = 16
    detections = []
    for i in range(0, len(tiles), batch_size):
        batch_tiles = tiles[i : i + batch_size]
        batch_coords = coords[i : i + batch_size]

        results = model.predict(
            source=batch_tiles,
            conf=conf_threshold,
            imgsz=tile_size,
            device=device,
            verbose=False,
        )

        for res, (tx, ty) in zip(results, batch_coords):
            if res.boxes is None or len(res.boxes) == 0:
                continue

            boxes = res.boxes
            has_masks = res.masks is not None and len(res.masks) > 0

            for idx in range(len(boxes)):
                cid = int(boxes.cls[idx].item())
                conf = float(boxes.conf[idx].item())
                cname = CLASSES[cid] if 0 <= cid < len(CLASSES) else f"class_{cid}"

                bx1, by1, bx2, by2 = boxes.xyxy[idx].tolist()
                global_box = [bx1 + tx, by1 + ty, bx2 + tx, by2 + ty]

                # Extract polygon mask if present
                poly_coords = None
                if has_masks and idx < len(res.masks.xy):
                    raw_poly = res.masks.xy[idx]
                    if len(raw_poly) >= 3:
                        poly_coords = [(float(px + tx), float(py + ty)) for px, py in raw_poly]

                detections.append({
                    "class": cname,
                    "confidence": conf,
                    "box": global_box,
                    "polygon": poly_coords,
                    "tile_coord": (tx, ty),
                })

    elapsed = time.perf_counter() - t0
    return stf_u8, detections, elapsed


def draw_yolo_overlay(
    stf_u8: np.ndarray,
    detections: List[Dict],
    out_path: Path,
    summary_text: str,
):
    """
    Renders semi-transparent segmentation masks and label badges directly over the astronomical frame.
    """
    h, w, _ = stf_u8.shape
    base_img = Image.fromarray(stf_u8).convert("RGBA")

    # Overlay layer for semi-transparent filled mask polygons
    mask_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask_draw = ImageDraw.Draw(mask_layer)

    # Outline draw on base
    draw = ImageDraw.Draw(base_img)

    for det in detections:
        cname = det["class"]
        conf = det["confidence"]
        poly = det["polygon"]
        box = det["box"]
        color_rgb = CLASS_COLORS.get(cname, (255, 255, 255))
        fill_rgba = (*color_rgb, 85)   # 33% transparent fill
        line_rgba = (*color_rgb, 230)  # Bright contour

        if poly and len(poly) >= 3:
            # Draw filled mask
            mask_draw.polygon(poly, fill=fill_rgba)
            # Draw crisp contour
            mask_draw.line(poly + [poly[0]], fill=line_rgba, width=2)
            anchor_x, anchor_y = poly[0]
        else:
            # Fallback to bounding box
            x1, y1, x2, y2 = box
            mask_draw.rectangle([x1, y1, x2, y2], fill=fill_rgba, outline=line_rgba, width=2)
            anchor_x, anchor_y = x1, y1

        # Class label tag
        tag = f"{cname.replace('_', ' ')}: {conf * 100:.1f}%"
        badge_w = len(tag) * 8 + 8
        badge_h = 18
        bx = max(0, min(int(anchor_x), w - badge_w))
        by = max(34, min(int(anchor_y) - badge_h, h - badge_h))

        draw.rectangle([bx, by, bx + badge_w, by + badge_h], fill=color_rgb)
        draw.text((bx + 4, by + 2), tag, fill=(255, 255, 255))

    # Composite mask layer onto base
    final_img = Image.alpha_composite(base_img, mask_layer).convert("RGB")
    final_draw = ImageDraw.Draw(final_img)

    # Top summary banner
    banner_h = 32
    final_draw.rectangle([0, 0, w, banner_h], fill=(20, 20, 20))
    final_draw.text((12, 8), summary_text, fill=(240, 240, 240))

    final_img.save(out_path, format="PNG")
    print(f"  Saved YOLO visual inspection overlay: {out_path.name}")


def verify_batch(
    fits_patterns: List[str],
    model_path: Path,
    out_dir: Path,
    conf_threshold: float = 0.25,
    device: str = "cpu",
    rgb_linked: bool = False,
    mode: str = "stf",
):
    fits_files = collect_fits_files(fits_patterns)
    if not fits_files:
        print("Error: No valid FITS files found to verify.")
        return

    model_path = Path(model_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("      AstroGrader: YOLO11-seg Full-Frame Verification")
    print("=" * 60)
    print(f"Model Checkpoint: {model_path.name}")
    print(f"Confidence Cut:   {conf_threshold:.2f}")
    print(f"Device:           {device}")
    print(f"FITS Files Found: {len(fits_files)}")
    print(f"Output Directory: {out_dir}")
    print("=" * 60 + "\n")

    # Load YOLO11-seg model
    model = YOLO(str(model_path))

    for idx, f in enumerate(fits_files, 1):
        print(f"[{idx}/{len(fits_files)}] Processing: {f.name}")
        try:
            stf_u8, detections, elapsed = run_yolo_fullframe(
                model=model,
                fits_path=f,
                conf_threshold=conf_threshold,
                device=device,
                rgb_linked=rgb_linked,
                mode=mode,
            )

            is_clean = len(detections) == 0
            if is_clean:
                verdict = "CLEAN SKY (0 defects detected)"
                summary = f"{f.name} | CLEAN SKY | Latency: {elapsed * 1000:.1f}ms"
            else:
                counts_by_cls = {}
                for d in detections:
                    counts_by_cls[d["class"]] = counts_by_cls.get(d["class"], 0) + 1
                counts_str = ", ".join(f"{cnt} {cls}" for cls, cnt in counts_by_cls.items())
                verdict = f"DEFECTS FLAGGED: {counts_str}"
                summary = f"{f.name} | {counts_str} | Latency: {elapsed * 1000:.1f}ms"

            print(f"  Result:  {verdict}")
            print(f"  Latency: {elapsed * 1000:.1f}ms")

            out_png = out_dir / f"{f.stem}_yolo_inspection.png"
            draw_yolo_overlay(stf_u8, detections, out_png, summary)

        except Exception as e:
            print(f"  Error processing {f.name}: {e}")

    print("\nVerification complete! Visual reports saved in:")
    print(f"  {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstroGrader YOLO11-seg Full-Frame Verification")
    parser.add_argument("--fits", type=str, nargs="+", required=True, help="Path, directory, or glob pattern of FITS files")
    parser.add_argument("--model", type=str, default="yolo11n-seg.pt", help="Path to trained YOLO11 weights (.pt)")
    parser.add_argument("--out-dir", type=str, default="verification_output", help="Directory for visual reports")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold (default: 0.25)")
    parser.add_argument("--device", type=str, default="cpu", help="Device (cpu or 0)")
    parser.add_argument("--linked", action="store_true", help="Use linked RGB STF stretch")
    parser.add_argument("--mode", type=str, default="stf", choices=["stf", "asinh", "linear"], help="Preview stretch mode")

    args = parser.parse_args()
    verify_batch(
        fits_patterns=args.fits,
        model_path=Path(args.model),
        out_dir=Path(args.out_dir),
        conf_threshold=args.conf,
        device=args.device,
        rgb_linked=args.linked,
        mode=args.mode,
    )
