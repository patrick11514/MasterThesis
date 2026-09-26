"""
Verification and Evaluation Tool for AstroGrader CNN Models.
Runs full-frame tile inference on FITS files using PyTorch or ONNX,
benchmarks throughput (tiles/sec), and produces visual diagnostic overlays.
Supports single files, multiple files, glob patterns, or directories.
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

try:
    import onnxruntime as ort
except ImportError:
    ort = None

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
                print(f"Warning: No file found matching '{pat}'")

    seen = set()
    unique = []
    for f in results:
        resolved = f.resolve()
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            unique.append(resolved)
    return sorted(unique)


def run_tile_inference(
    model_or_session,
    full_f32: np.ndarray,
    tile_size: int = 512,
    stride: int = 384,
    device: str = "cpu",
    threshold: float = 0.5,
    is_onnx: bool = False,
) -> Tuple[List[Dict], float]:
    """
    Slices normalized f32 full frame into overlapping tiles, batches them,
    and runs forward inference using PyTorch or ONNX Runtime.
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

    batch_np = np.stack(tiles, axis=0).astype(np.float32)

    t0 = time.perf_counter()
    if is_onnx:
        input_name = model_or_session.get_inputs()[0].name
        output_name = model_or_session.get_outputs()[0].name
        logits = model_or_session.run([output_name], {input_name: batch_np})[0]
        # Sigmoid with numerical clamp
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -20.0, 20.0)))
    else:
        batch = torch.from_numpy(batch_np).to(device)
        with torch.no_grad():
            logits = model_or_session(batch)
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
    print(f"  Saved diagnostic overlay: {out_path.name}")


def verify_fits_batch(
    fits_patterns: List[str],
    model_path: Path,
    out_dir: Path,
    threshold: float = 0.5,
    device: str = "cpu",
):
    fits_files = collect_fits_files(fits_patterns)
    if not fits_files:
        print("Error: No valid FITS files found to verify.")
        return

    model_path = Path(model_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    is_onnx = model_path.suffix.lower() == ".onnx"
    input_mode = "asinh"

    print(f"\n============================================================")
    print(f"             AstroGrader Verification Runner                ")
    print(f"============================================================")
    print(f"Target Model: {model_path.name} ({'ONNX Runtime' if is_onnx else 'PyTorch'})")
    print(f"Device:       {device}")
    print(f"Files Found:  {len(fits_files)}")
    print(f"Output Dir:   {out_dir}")
    print(f"Threshold:    {threshold:.2f}")
    print(f"============================================================\n")

    # Load model once for all frames
    if is_onnx:
        if ort is None:
            raise RuntimeError("onnxruntime is not installed. Install it with: pip install onnxruntime")
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
        model_or_session = ort.InferenceSession(str(model_path), providers=providers)
    else:
        ckpt = torch.load(model_path, map_location=device)
        model_name = ckpt.get("model_name", "astronet")
        input_mode = ckpt.get("input_mode", "f32")
        model = build_model(model_name, pretrained=False, num_classes=NUM_CLASSES)
        model.load_state_dict(ckpt["state_dict"])
        model.to(device)
        model.eval()
        model_or_session = model

    clean_count = 0
    flagged_count = 0
    defect_frame_counts = {c: 0 for c in CLASSES}

    for idx, fits_path in enumerate(fits_files, 1):
        print(f"[{idx}/{len(fits_files)}] Processing {fits_path.name}...")
        try:
            # Load unified 3-channel FITS
            rgb_f32, meta = load_fits_unified_rgb(fits_path)
            h, w, _ = rgb_f32.shape

            # Pre-normalize
            if "asinh" in input_mode:
                norm_f32 = to_asinh_f32(rgb_f32)
            else:
                norm_f32 = to_auto_stf_f32(rgb_f32)

            stf_u8 = to_stf_u8(rgb_f32)

            # Run tile inference
            detections, infer_time = run_tile_inference(
                model_or_session,
                norm_f32,
                tile_size=512,
                stride=384,
                device=device,
                threshold=threshold,
                is_onnx=is_onnx,
            )

            # Tally classes for this frame
            frame_classes = set()
            class_tile_counts = {c: 0 for c in CLASSES}
            for det in detections:
                for p in det["predictions"]:
                    cname = p["class"]
                    class_tile_counts[cname] += 1
                    frame_classes.add(cname)

            is_clean = len(frame_classes) == 0
            if is_clean:
                clean_count += 1
                verdict_tag = "CLEAN SKY (ACCEPT)"
            else:
                flagged_count += 1
                verdict_tag = "DEFECT DETECTED (FLAGGED)"
                for c in frame_classes:
                    defect_frame_counts[c] += 1

            defect_details = ", ".join(f"{c}: {cnt} tiles" for c, cnt in class_tile_counts.items() if cnt > 0)
            if not defect_details:
                defect_details = "None (clean)"

            print(f"  --> Verdict: {verdict_tag} | Time: {infer_time * 1000:.1f}ms")
            print(f"      Defects: {defect_details}")

            # Save visual inspection image
            out_png = out_dir / f"{fits_path.stem}_inspection.png"
            verdict_str = f"File: {fits_path.name} | Verdict: {'CLEAN SKY' if is_clean else 'FLAGGED'} | Time: {infer_time * 1000:.1f}ms"
            draw_diagnostic_overlay(stf_u8, detections, out_png, verdict_str)

        except Exception as e:
            print(f"  Error processing {fits_path.name}: {e}")

    # Summary report
    print("\n" + "=" * 60)
    print("               BATCH VERIFICATION SUMMARY                   ")
    print("=" * 60)
    print(f"Total frames processed: {len(fits_files)}")
    print(f"  - Clean Sky (ACCEPT):  {clean_count} ({(clean_count / len(fits_files) * 100):.1f}%)")
    print(f"  - Defective (FLAGGED): {flagged_count} ({(flagged_count / len(fits_files) * 100):.1f}%)")
    print("\nDefect Breakdown (Frames Affected):")
    for c in CLASSES:
        print(f"  - {c:18s}: {defect_frame_counts[c]} frame(s)")
    print(f"\nAll inspection images saved in: {out_dir}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify FITS with trained CNN (PyTorch or ONNX)")
    parser.add_argument(
        "--fits",
        type=str,
        nargs="+",
        required=True,
        help="Path(s) to test FITS file(s), glob pattern (e.g. *.fits), or directory",
    )
    parser.add_argument("--model-path", type=str, required=True, help="Path to best_model.pt or model.onnx")
    parser.add_argument("--out-dir", type=str, default="verification_output", help="Directory for inspection PNGs")
    parser.add_argument("--threshold", type=float, default=0.5, help="Detection threshold [0.0 - 1.0]")
    parser.add_argument("--device", type=str, default="cpu", help="Device (cpu or cuda)")

    args = parser.parse_args()
    verify_fits_batch(
        fits_patterns=args.fits,
        model_path=Path(args.model_path),
        out_dir=Path(args.out_dir),
        threshold=args.threshold,
        device=args.device,
    )
