#!/usr/bin/env python3
"""
AstroGrader: High-Throughput Airplane Screening Tool.

Recursively scans raw FITS directories (e.g. NAS storage archives) for rare airplane streaks.
Uses a multithreaded CPU preloader (AutoSTF + 512x512 tile slicing + optical metadata)
pipelined directly into GPU CNN inference (MobileNetV3 with channels_last + bfloat16 AMP).

Matches are automatically symlinked into an output directory and paired with draft YOLO
polygon annotations (marked favorite=True) for 1-click review in annotator/app.py.
"""

import os
import sys

# Configure AMD ROCm / MIOpen environment optimizations before importing torch
os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
os.environ.setdefault("MIOPEN_DEBUG_CONV_WINOGRAD", "1")

# Ensure ROCm SDK shared library paths and unversioned .so symlinks exist
conda_prefix = os.environ.get("CONDA_PREFIX")
if conda_prefix:
    import glob
    sdk_lib_candidates = glob.glob(
        os.path.join(conda_prefix, "lib", "python*", "site-packages", "_rocm_sdk_libraries_*", "lib")
    )
    for lib_dir in sdk_lib_candidates:
        if os.path.isdir(lib_dir):
            for f in glob.glob(os.path.join(lib_dir, "*.so.*")):
                base = f.split(".so.")[0] + ".so"
                if not os.path.exists(base):
                    try:
                        os.symlink(os.path.basename(f), base)
                    except OSError:
                        pass
            current_ld = os.environ.get("LD_LIBRARY_PATH", "")
            if lib_dir not in current_ld.split(":"):
                os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{current_ld}" if current_ld else lib_dir

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import queue
import signal
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
import torch
from tqdm import tqdm

# Ensure training root on sys.path
TRAINING_ROOT = Path(__file__).resolve().parent
if str(TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_ROOT))

from fits_utils import (
    load_fits_unified_rgb,
    to_auto_stf_f32,
    to_stf_u8,
    compute_tile_metadata,
    CLASSES,
)
from models.cnn_zoo import build_model, NUM_CLASSES
from prep_dataset import get_tile_offsets


AIRPLANE_IDX = CLASSES.index("airplane") if "airplane" in CLASSES else 1


def resolve_default_model(model_arg: Optional[str]) -> Optional[Path]:
    """Finds the best available CNN classifier checkpoint."""
    if model_arg:
        p = Path(model_arg).resolve()
        if p.exists():
            return p
        alt = (TRAINING_ROOT / model_arg).resolve()
        if alt.exists():
            return alt

    candidates = [
        TRAINING_ROOT / "iterations" / "v1_ver2" / "models" / "mobilenet_v3_best.pt",
        TRAINING_ROOT / "checkpoints" / "mobilenet_v3_f32" / "best_model.pt",
        TRAINING_ROOT / "iterations" / "v1_ver2" / "models" / "resnet18_best.pt",
        TRAINING_ROOT / "checkpoints" / "resnet18_f32" / "best_model.pt",
        TRAINING_ROOT / "checkpoints" / "astronet_f32" / "best_model.pt",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def resolve_default_yolo_model(yolo_arg: Optional[str]) -> Optional[Path]:
    """Finds the best available YOLO segmentation model checkpoint."""
    if yolo_arg:
        p = Path(yolo_arg).resolve()
        if p.exists():
            return p
        alt = (TRAINING_ROOT / yolo_arg).resolve()
        if alt.exists():
            return alt

    candidates = [
        TRAINING_ROOT / "iterations" / "v1_ver2" / "models" / "yolo_best.pt",
        TRAINING_ROOT / "runs" / "segment" / "yolo_astro" / "weights" / "best.pt",
        TRAINING_ROOT / "runs" / "segment" / "yolo11_astro" / "weights" / "best.pt",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def collect_existing_stems(dir_path: Optional[Path]) -> Set[str]:
    """Collects lowercase file stems from a directory for O(1) deduplication."""
    stems = set()
    if not dir_path or not dir_path.exists():
        return stems

    for p in dir_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".fits", ".fit", ".json"):
            stems.add(p.stem.lower())
            if p.suffix.lower() == ".json":
                # Also index stem if it has a double extension like frame.fits.json
                stems.add(p.name.replace(".json", "").lower())
    return stems


class PreloadedFrame:
    """Container for CPU pre-processed FITS frame data ready for inference."""
    def __init__(
        self,
        fits_path: Path,
        tiles_tensor: torch.Tensor,
        metas_tensor: torch.Tensor,
        coords: List[Tuple[int, int]],
        preview_u8: np.ndarray,
        width: int,
        height: int,
    ):
        self.fits_path = fits_path
        self.tiles_tensor = tiles_tensor
        self.metas_tensor = metas_tensor
        self.coords = coords
        self.preview_u8 = preview_u8
        self.width = width
        self.height = height


def preprocess_frame(
    fits_path: Path,
    tile_size: int = 512,
    stride: int = 512,
) -> Optional[PreloadedFrame]:
    """Preloads, stretches, slices, and extracts metadata for a FITS frame on CPU."""
    try:
        rgb_f32, meta = load_fits_unified_rgb(fits_path)
        h, w, _ = rgb_f32.shape
        frame_med = float(meta.get("frame_median", 0.05))
        frame_mad = float(meta.get("frame_mad", 0.005))
        pixel_scale = float(meta.get("pixel_scale", 2.39))

        norm_f32 = to_auto_stf_f32(rgb_f32, rgb_linked=False)
        preview_u8 = to_stf_u8(rgb_f32, rgb_linked=False)

        x_offsets = get_tile_offsets(w, tile_size, stride)
        y_offsets = get_tile_offsets(h, tile_size, stride)

        tiles_list = []
        metas_list = []
        coords_list = []

        for y in y_offsets:
            for x in x_offsets:
                x_end = x + tile_size
                y_end = y + tile_size

                tile_lin = rgb_f32[y:y_end, x:x_end]
                tile_norm = norm_f32[y:y_end, x:x_end]

                # Ensure exact tile_size x tile_size
                if tile_norm.shape[0] != tile_size or tile_norm.shape[1] != tile_size:
                    padded_norm = np.zeros((tile_size, tile_size, 3), dtype=np.float32)
                    padded_lin = np.zeros((tile_size, tile_size, 3), dtype=np.float32)
                    padded_norm[:tile_norm.shape[0], :tile_norm.shape[1]] = tile_norm
                    padded_lin[:tile_lin.shape[0], :tile_lin.shape[1]] = tile_lin
                    tile_norm = padded_norm
                    tile_lin = padded_lin

                # Planar float32 [3, 512, 512]
                planar = np.transpose(tile_norm, (2, 0, 1)).astype(np.float32)
                meta_vec = compute_tile_metadata(tile_lin, tile_norm, frame_med, frame_mad, pixel_scale)

                tiles_list.append(planar)
                metas_list.append(meta_vec)
                coords_list.append((x, y))

        tiles_tensor = torch.from_numpy(np.stack(tiles_list, axis=0))
        metas_tensor = torch.tensor(metas_list, dtype=torch.float32)

        return PreloadedFrame(
            fits_path=fits_path,
            tiles_tensor=tiles_tensor,
            metas_tensor=metas_tensor,
            coords=coords_list,
            preview_u8=preview_u8,
            width=w,
            height=h,
        )
    except Exception as e:
        return None


def run_yolo_draft_annotation(
    yolo_model,
    frame: PreloadedFrame,
    hit_tile_indices: List[int],
    tile_size: int = 512,
    device: str = "cpu",
) -> List[Dict]:
    """Runs YOLO on candidate hit tiles and converts detections to global frame coordinates."""
    if yolo_model is None or not hit_tile_indices:
        return []

    boxes: List[Dict] = []
    ts = int(time.time() * 1000)

    try:
        tiles_to_scan = []
        tile_coords = []
        for idx in hit_tile_indices:
            tx, ty = frame.coords[idx]
            crop = frame.preview_u8[ty : ty + tile_size, tx : tx + tile_size]
            if crop.shape[0] == tile_size and crop.shape[1] == tile_size:
                tiles_to_scan.append(crop)
                tile_coords.append((tx, ty))

        if not tiles_to_scan:
            return []

        results = yolo_model.predict(
            source=tiles_to_scan,
            conf=0.15,
            imgsz=tile_size,
            device=device,
            verbose=False,
        )

        for res, (tx, ty) in zip(results, tile_coords):
            if res.boxes is None or len(res.boxes) == 0:
                continue

            has_masks = res.masks is not None and len(res.masks) > 0

            for b_idx in range(len(res.boxes)):
                cid = int(res.boxes.cls[b_idx].item())
                conf = float(res.boxes.conf[b_idx].item())
                cname = CLASSES[cid] if 0 <= cid < len(CLASSES) else f"class_{cid}"

                # Keep airplane detections, or high confidence detections
                if cname != "airplane" and conf < 0.35:
                    continue

                bx1, by1, bx2, by2 = res.boxes.xyxy[b_idx].tolist()
                gx = float(bx1 + tx)
                gy = float(by1 + ty)
                gw = float(bx2 - bx1)
                gh = float(by2 - by1)

                poly_coords = None
                if has_masks and b_idx < len(res.masks.xy):
                    raw_poly = res.masks.xy[b_idx]
                    if len(raw_poly) >= 3:
                        pts = np.array(raw_poly, dtype=np.float32)
                        approx = cv2.approxPolyDP(pts, epsilon=1.5, closed=True)
                        poly_coords = [[round(float(p[0][0] + tx), 1), round(float(p[0][1] + ty), 1)] for p in approx]

                box_item = {
                    "id": f"airplane_yolo_{ts}_{len(boxes)}",
                    "label": cname,
                    "confidence": round(conf, 3),
                }
                if poly_coords and len(poly_coords) >= 3:
                    box_item["type"] = "polygon"
                    box_item["points"] = poly_coords
                    box_item["x"] = gx
                    box_item["y"] = gy
                    box_item["width"] = gw
                    box_item["height"] = gh
                else:
                    box_item["type"] = "box"
                    box_item["x"] = gx
                    box_item["y"] = gy
                    box_item["width"] = gw
                    box_item["height"] = gh

                boxes.append(box_item)

    except Exception as e:
        pass

    return boxes


def safe_symlink(src: Path, dst: Path):
    """Creates a symlink from dst to src; falls back to copy if filesystem does not support symlinks."""
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        import shutil
        shutil.copy2(src, dst)


def main():
    parser = argparse.ArgumentParser(
        description="AstroGrader: High-Throughput Airplane Candidate Screening Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target-dir", "-t", type=str, nargs="+", required=True,
        help="Path(s) to directory/directories with raw FITS files to scan recursively",
    )
    parser.add_argument(
        "--out-dir", "-o", type=str, default="./AIRPLANE_CANDIDATES",
        help="Output directory where candidate frames will be symlinked and annotated",
    )
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Path to CNN model checkpoint (.pt). Defaults to best mobilenet_v3 in iterations/ or checkpoints/",
    )
    parser.add_argument(
        "--yolo-model", "-y", type=str, default=None,
        help="Path to YOLO segmentation model (.pt) to auto-draft airplane polygons",
    )
    parser.add_argument(
        "--training-dir", type=str, default=None,
        help="Path to existing labeled dataset directory (e.g. ../TRAINING_FILES) to skip already labeled frames",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=4,
        help="Number of CPU worker threads for parallel FITS preloading and AutoSTF stretching",
    )
    parser.add_argument(
        "--tile-size", type=int, default=512,
        help="Tile crop size in pixels",
    )
    parser.add_argument(
        "--stride", type=int, default=512,
        help="Tile stride in pixels (512 = non-overlapping for maximum screening speed)",
    )
    parser.add_argument(
        "--prob-single", type=float, default=0.65,
        help="Probability threshold to flag a frame if any single tile exceeds it",
    )
    parser.add_argument(
        "--prob-multi", type=float, default=0.35,
        help="Lower probability threshold for multi-tile hit detection",
    )
    parser.add_argument(
        "--min-hits", type=int, default=2,
        help="Number of tiles required to exceed --prob-multi to flag a frame",
    )
    parser.add_argument(
        "--batch-size", type=int, default=32,
        help="Inference batch size across tiles of a single frame",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="Inference device ('cuda', 'cuda:0', 'cpu', or None for auto-detect)",
    )
    parser.add_argument(
        "--no-yolo", action="store_true",
        help="Disable YOLO draft polygon segmentation; only flag candidates via CNN",
    )
    parser.add_argument(
        "--max-frames", type=int, default=None,
        help="Stop after scanning N frames (useful for testing)",
    )
    parser.add_argument(
        "--log-file", type=str, default=None,
        help="Custom path to candidate log file (default: <out-dir>/candidates.log)",
    )
    parser.add_argument(
        "--no-amp", action="store_true",
        help="Disable bfloat16 mixed precision on GPU",
    )

    args = parser.parse_args()

    # Resolve output directory
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = Path(args.log_file).resolve() if args.log_file else (out_dir / "candidates.log")

    # Resolve training directory for deduplication
    training_dirs = []
    if args.training_dir:
        training_dirs.append(Path(args.training_dir).resolve())
    else:
        for cand_dir in [
            TRAINING_ROOT / "TRAINING_FILES",
            TRAINING_ROOT.parent / "TRAINING_FILES",
            Path("TRAINING_FILES").resolve(),
        ]:
            if cand_dir.exists():
                training_dirs.append(cand_dir)

    print("\n" + "=" * 70)
    print(" AstroGrader: Airplane Screening & Candidate Harvester".center(70))
    print("=" * 70)

    # 1. Resolve CNN model
    model_path = resolve_default_model(args.model)
    if not model_path or not model_path.exists():
        print(f"\nError: Could not locate CNN model checkpoint. Specified: {args.model}")
        print("Please train a model or specify --model path/to/model.pt")
        sys.exit(1)

    print(f"\n[+] Loaded CNN Classifier: {model_path.name}")
    print(f"    Path: {model_path}")

    # Determine model architecture name
    model_arch = "mobilenet_v3"
    name_lower = model_path.stem.lower()
    for arch in ["mobilenet_v3", "resnet18", "astronet", "resnet34", "efficientnet_b0"]:
        if arch in name_lower:
            model_arch = arch
            break

    # Setup PyTorch Device
    if args.device:
        device = torch.device(args.device)
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[+] Compute Device: {device} (ROCm / CUDA)")

    # Build and load CNN
    cnn_model = build_model(model_arch, pretrained=False, num_classes=NUM_CLASSES)
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    state_dict = ckpt.get("state_dict", ckpt) if isinstance(ckpt, dict) else ckpt
    cnn_model.load_state_dict(state_dict)
    cnn_model.eval()

    if device.type == "cuda":
        cnn_model = cnn_model.to(device, memory_format=torch.channels_last)
    else:
        cnn_model = cnn_model.to(device)

    # 2. Resolve YOLO model
    yolo_model = None
    if not args.no_yolo:
        yolo_path = resolve_default_yolo_model(args.yolo_model)
        if yolo_path and yolo_path.exists():
            try:
                from ultralytics import YOLO
                yolo_model = YOLO(str(yolo_path))
                print(f"[+] Loaded YOLO Instance Segmenter: {yolo_path.name}")
            except Exception as e:
                print(f"[-] Warning: Failed to initialize YOLO ({e}). Skipping draft polygons.")
        else:
            print("[-] No YOLO checkpoint found. Candidate frames will have bounding box drafts.")

    # 3. Build Deduplication Sets
    existing_stems = set()
    for td in training_dirs:
        stems = collect_existing_stems(td)
        existing_stems.update(stems)
        print(f"[+] Indexed {len(stems)} existing files from training directory: {td}")

    out_stems = collect_existing_stems(out_dir)
    print(f"[+] Indexed {len(out_stems)} previously flagged candidates in: {out_dir}")

    # 4. Discover Target FITS Files
    print("\n[+] Recursively scanning target directories for FITS files...")
    target_dirs = [Path(d).resolve() for d in args.target_dir]
    raw_files: List[Path] = []
    extensions = ("*.fits", "*.fit", "*.FITS", "*.FIT")

    for td in target_dirs:
        if not td.exists():
            print(f"    Warning: Target directory does not exist: {td}")
            continue
        for ext in extensions:
            raw_files.extend(list(td.rglob(ext)))

    raw_files = sorted(set(raw_files))
    print(f"[+] Total raw FITS files discovered: {len(raw_files):,}")

    if not raw_files:
        print("No FITS files found to process. Exiting.")
        return

    # Filter out already labeled or processed files
    files_to_process = []
    skipped_count = 0

    for f in raw_files:
        # Check if local .json already exists
        if f.with_suffix(".json").exists():
            skipped_count += 1
            continue
        # Check if already in training set
        if f.stem.lower() in existing_stems:
            skipped_count += 1
            continue
        # Check if already processed into out_dir
        if f.stem.lower() in out_stems or (out_dir / f.name).exists():
            skipped_count += 1
            continue

        files_to_process.append(f)

    print(f"[+] Skipped {skipped_count:,} files (already labeled or previously flagged)")
    print(f"[+] Eligible files queued for screening: {len(files_to_process):,}\n")

    if args.max_frames:
        files_to_process = files_to_process[:args.max_frames]
        print(f"[+] Limited by --max-frames to: {len(files_to_process):,}\n")

    if not files_to_process:
        print("All discovered files have already been processed or labeled!")
        return

    # 5. Pipelined Multithreaded Execution Setup
    frame_queue: queue.Queue = queue.Queue(maxsize=max(8, args.workers * 2))
    stop_event = threading.Event()
    stats_lock = threading.Lock()

    scanned_count = 0
    candidate_count = 0
    start_time = time.time()

    def signal_handler(sig, frame):
        print("\n\n[!] Interruption received (Ctrl+C). Halting scanner gracefully...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)

    def producer_worker(file_list: List[Path]):
        """CPU worker fetching and preprocessing FITS frames into the queue."""
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for fits_path in file_list:
                if stop_event.is_set():
                    break
                future = executor.submit(preprocess_frame, fits_path, args.tile_size, args.stride)
                try:
                    preloaded = future.result()
                    if preloaded is not None:
                        while not stop_event.is_set():
                            try:
                                frame_queue.put(preloaded, timeout=0.5)
                                break
                            except queue.Full:
                                pass
                except Exception:
                    pass

        # Sentinel to signal completion
        frame_queue.put(None)

    producer_thread = threading.Thread(target=producer_worker, args=(files_to_process,), daemon=True)
    producer_thread.start()

    # Log header
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"\n--- Airplane Screening Session Started: {datetime.now().isoformat()} ---\n")
        lf.write(f"Model: {model_path.name} | Stride: {args.stride} | Prob Single: {args.prob_single} | Multi: {args.prob_multi} (min {args.min_hits} tiles)\n")

    use_amp = (device.type == "cuda" and not args.no_amp)

    # 6. Main Inference Consumer Loop
    pbar = tqdm(total=len(files_to_process), desc="Screening FITS", unit="frame")

    try:
        while not stop_event.is_set():
            try:
                item = frame_queue.get(timeout=0.5)
            except queue.Empty:
                if not producer_thread.is_alive():
                    break
                continue

            if item is None:
                # Producer finished
                break

            frame: PreloadedFrame = item
            num_tiles = frame.tiles_tensor.size(0)

            # GPU Forward Pass in batches
            all_probs = []
            for b_start in range(0, num_tiles, args.batch_size):
                b_end = min(b_start + args.batch_size, num_tiles)
                b_images = frame.tiles_tensor[b_start:b_end]
                b_metas = frame.metas_tensor[b_start:b_end]

                if device.type == "cuda":
                    b_images = b_images.to(device, memory_format=torch.channels_last, non_blocking=True)
                else:
                    b_images = b_images.to(device)
                b_metas = b_metas.to(device, non_blocking=True)

                with torch.no_grad():
                    with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                        logits = cnn_model(b_images, b_metas)
                        probs = torch.sigmoid(logits.float()).cpu().numpy()
                        all_probs.append(probs)

            all_probs = np.concatenate(all_probs, axis=0) if all_probs else np.zeros((0, NUM_CLASSES))

            # Evaluate Airplane Defect Probability
            airplane_probs = all_probs[:, AIRPLANE_IDX]
            hit_indices = [idx for idx, p in enumerate(airplane_probs) if p >= args.prob_multi]
            hit_tiles = len(hit_indices)
            max_prob = float(airplane_probs.max()) if len(airplane_probs) > 0 else 0.0

            is_candidate = (hit_tiles >= args.min_hits) or (max_prob >= args.prob_single)

            with stats_lock:
                scanned_count += 1

            if is_candidate:
                with stats_lock:
                    candidate_count += 1
                    c_num = candidate_count

                # 1. Console notification
                msg = (
                    f"\n✈ [AIRPLANE CANDIDATE #{c_num}] {frame.fits_path.name} | "
                    f"Max Prob: {max_prob:.3f} | Hit Tiles: {hit_tiles}/{num_tiles}"
                )
                pbar.write(msg)

                # 2. Append to log file
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] CANDIDATE #{c_num}: "
                        f"{frame.fits_path} (max_prob={max_prob:.4f}, hit_tiles={hit_tiles}/{num_tiles})\n"
                    )

                # 3. Symlink FITS into out_dir
                dst_fits = out_dir / frame.fits_path.name
                safe_symlink(frame.fits_path, dst_fits)

                # 4. Generate YOLO draft polygon annotation
                draft_boxes = []
                if yolo_model is not None:
                    draft_boxes = run_yolo_draft_annotation(
                        yolo_model=yolo_model,
                        frame=frame,
                        hit_tile_indices=hit_indices,
                        tile_size=args.tile_size,
                        device=str(device) if device.type == "cuda" else "cpu",
                    )

                # Fallback: create draft bounding box around highest-confidence tile if YOLO didn't segment
                if not draft_boxes and hit_tiles > 0:
                    best_tile_idx = int(np.argmax(airplane_probs))
                    btx, bty = frame.coords[best_tile_idx]
                    draft_boxes.append({
                        "id": f"airplane_cnn_{int(time.time() * 1000)}_0",
                        "label": "airplane",
                        "type": "box",
                        "x": float(btx),
                        "y": float(bty),
                        "width": float(args.tile_size),
                        "height": float(args.tile_size),
                        "confidence": round(max_prob, 3),
                    })

                # Write draft .json with favorite=True for 1-click annotator verification
                dst_json = out_dir / f"{frame.fits_path.stem}.json"
                annotation_data = {
                    "file_name": frame.fits_path.name,
                    "width": frame.width,
                    "height": frame.height,
                    "global_star_trailing": False,
                    "global_cloud": False,
                    "is_clean": False,
                    "favorite": True,
                    "candidate_score": round(max_prob, 4),
                    "candidate_hit_tiles": hit_tiles,
                    "boxes": draft_boxes,
                }
                with open(dst_json, "w", encoding="utf-8") as jf:
                    json.dump(annotation_data, jf, indent=2)

            pbar.update(1)
            pbar.set_postfix({
                "candidates": candidate_count,
                "q": frame_queue.qsize(),
            })

    finally:
        pbar.close()
        stop_event.set()

    elapsed = time.time() - start_time
    fps = scanned_count / max(elapsed, 0.001)

    print("\n" + "=" * 70)
    print(" Airplane Screening Session Summary".center(70))
    print("=" * 70)
    print(f"Total FITS files discovered: {len(raw_files):,}")
    print(f"Skipped (already labeled):   {skipped_count:,}")
    print(f"Frames scanned this session: {scanned_count:,}")
    print(f"Airplane candidates flagged: {candidate_count:,}")
    print(f"Total elapsed time:          {elapsed:.1f}s ({fps:.2f} frames/sec)")
    print(f"Candidate symlinks location: {out_dir}")
    print(f"Detailed log file:           {log_path}")
    print("=" * 70)

    if candidate_count > 0:
        print("\nNext Step:")
        print(f"  To review and 1-click verify candidates in the interactive annotator UI, run:")
        print(f"  cd {TRAINING_ROOT / 'annotator'} && python app.py --data-dir {out_dir}\n")


if __name__ == "__main__":
    main()
