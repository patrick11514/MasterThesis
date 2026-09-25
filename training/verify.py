"""
Verification and Evaluation Tool for AstroGrader CNN Models.
Runs full-frame tile inference on FITS files using PyTorch or ONNX,
benchmarks throughput (tiles/sec), and produces visual diagnostic overlays.
"""

import argparse
from pathlib import Path
import time
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models.cnn_zoo import build_model, NUM_CLASSES
from fits_utils import (
    load_fits_unified_rgb,
    to_asinh_f32,
    to_auto_stf_f32,
    to_stf_u8,
    CLASSES,
)

CLASS_COLORS_RGB = {
    "satellite_streak": (229, 62, 62),     # Red
    "airplane": (237, 137, 54),            # Orange
    "cloud": (66, 153, 225),               # Blue
    "obstruction": (159, 122, 234),        # Purple
    "star_trail": (236, 201, 75),          # Yellow
}


def run_tile_inference(
    model: torch.nn.Module,
    full_f32: np.ndarray,
    tile_size: int = 512,
    stride: int = 384,
    device: str = "cpu",
    threshold: float = 0.5,
) -> Tuple[List[Dict], float]:
    """
    Slices normalized f32 full frame into overlapping tiles, batches them,
    and runs forward inference.
    """
    h, w, _ = full_f32.shape
    planar_f32 = np.transpose(full_f32, (2, 0, 1))  # [3, H, W]

    tiles = []
    positions = []
    for y in range(0, max(1, h - tile_size + 1), stride):
        for x in range(0, max(1, w - tile_size + 1), stride):
            x_end = min(x + tile_size, w)
            y_end = min(y + tile_size, h)
            x_start = max(0, x_end - tile_size)
            y_start = max(0, y_end - tile_size)

            tile = planar_f32[:, y_start:y_end, x_start:x_end]
            tiles.append(tile)
            positions.append((x_start, y_start, tile_size, tile_size))

    if not tiles:
        return [], 0.0

    batch = torch.from_numpy(np.stack(tiles, axis=0)).to(device)

    model.eval()
    t0 = time.perf_counter()
    with torch.no_grad():
        logits = model(batch)
        probs = torch.sigmoid(logits).cpu().numpy()
    elapsed = time.perf_counter() - t0

    detections = []
    for (x, y, tw, th), p in zip(positions, probs):
        tile_detections = []
        for i, cls_name in enumerate(CLASSES):
            if p[i] >= threshold:
                tile_detections.append({
                    "class": cls_name,
                    "confidence": float(p[i]),
                })
        if tile_detections:
            detections.append({
                "x": x,
                "y": y,
                "width": tw,
                "height": th,
                "predictions": tile_detections,
            })

    return detections, elapsed


def draw_diagnostic_overlay(
    stf_u8: np.ndarray,
    detections: List[Dict],
    out_path: Path,
    summary_text: str,
):
    """
    Renders bounding boxes and label tags onto the stretched 8-bit image and saves report.
    """
    img = Image.fromarray(stf_u8)
    draw = ImageDraw.Draw(img)

    for det in detections:
        x, y, w, h = det["x"], det["y"], det["width"], det["height"]
        for p in det["predictions"]:
            col = CLASS_COLORS_RGB.get(p["class"], (255, 255, 255))
            draw.rectangle([x, y, x + w, y + h], outline=col, width=3)

            label = f"{p['class'].replace('_', ' ')}: {p['confidence'] * 100:.1f}%"
            # Text background
            draw.rectangle([x, max(0, y - 18), x + len(label) * 8 + 8, y], fill=col)
            draw.text((x + 4, max(0, y - 16)), label, fill=(255, 255, 255))

    # Top info banner
    banner_h = 32
    draw.rectangle([0, 0, img.width, banner_h], fill=(20, 20, 20))
    draw.text((10, 8), summary_text, fill=(220, 220, 220))

    img.save(out_path, format="PNG")
    print(f"Saved diagnostic overlay to: {out_path}")


def verify_fits_frame(
    fits_path: Path,
    model_path: Path,
    out_dir: Path,
    threshold: float = 0.5,
    device: str = "cpu",
):
    fits_path = Path(fits_path).resolve()
    model_path = Path(model_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- Verifying FITS: {fits_path.name} ---")

    # Load checkpoint
    ckpt = torch.load(model_path, map_location=device)
    model_name = ckpt.get("model_name", "astronet")
    input_mode = ckpt.get("input_mode", "f32")

    print(f"Loading Model: {model_name} (Input Mode: {input_mode})")
    model = build_model(model_name, pretrained=False, num_classes=NUM_CLASSES)
    model.load_state_dict(ckpt["state_dict"])
    model.to(device)

    # Load unified 3-channel FITS
    rgb_f32, meta = load_fits_unified_rgb(fits_path)
    h, w, _ = rgb_f32.shape
    print(f"Image Dimensions: {w} x {h} | Bayer Pattern: {meta['bayer_pattern']}")

    # Pre-normalize
    if "asinh" in input_mode:
        norm_f32 = to_asinh_f32(rgb_f32)
    else:
        norm_f32 = to_auto_stf_f32(rgb_f32)

    stf_u8 = to_stf_u8(rgb_f32)

    # Run tile inference
    detections, infer_time = run_tile_inference(
        model, norm_f32, tile_size=512, stride=384, device=device, threshold=threshold
    )

    # Tally classes
    class_counts = {c: 0 for c in CLASSES}
    for det in detections:
        for p in det["predictions"]:
            class_counts[p["class"]] += 1

    detected_any = any(v > 0 for v in class_counts.values())
    is_clean = not detected_any

    print("\n--- Inference Results ---")
    print(f"Inference latency: {infer_time * 1000:.1f}ms")
    print(f"Overall Quality Verdict: {'CLEAN SKY (ACCEPT)' if is_clean else 'DEFECT DETECTED (FLAGGED)'}")
    for c, cnt in class_counts.items():
        if cnt > 0:
            print(f"  - {c}: detected in {cnt} tiles")

    # Save visual inspection image
    out_png = out_dir / f"{fits_path.stem}_inspection.png"
    verdict_str = f"File: {fits_path.name} | Verdict: {'CLEAN SKY' if is_clean else 'DEFECT DETECTED'} | Time: {infer_time * 1000:.1f}ms"
    draw_diagnostic_overlay(stf_u8, detections, out_png, verdict_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify FITS with trained CNN")
    parser.add_argument("--fits", type=str, required=True, help="Path to test FITS file")
    parser.add_argument("--model-path", type=str, required=True, help="Path to best_model.pt")
    parser.add_argument("--out-dir", type=str, default="verification_output")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--device", type=str, default="cpu")

    args = parser.parse_args()
    verify_fits_frame(
        fits_path=Path(args.fits),
        model_path=Path(args.model_path),
        out_dir=Path(args.out_dir),
        threshold=args.threshold,
        device=args.device,
    )
