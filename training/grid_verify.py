#!/usr/bin/env python3
"""
AstroGrader: Grid Verification & Multi-Model Comparison Tool.

Runs all selected models (CNNs in PyTorch/ONNX and/or YOLO-seg checkpoints) across
all selected FITS frames in a Model x Image grid, benchmarks inference latency,
evaluates against sibling JSON ground truth annotations when available, generates
side-by-side visual comparison grids, and produces terminal/Markdown/CSV/JSON
leaderboards to compare which models perform best or worst.
"""

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw
import torch

try:
    import onnxruntime as ort
except ImportError:
    ort = None

TRAINING_ROOT = Path(__file__).resolve().parent
if str(TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_ROOT))

from fits_utils import (
    CLASSES,
    calculate_channel_stats,
    calculate_stf,
    compute_tile_metadata,
    load_fits_unified_rgb,
    to_asinh_f32,
    to_auto_stf_f32,
    to_stf_u8,
)
from models.cnn_zoo import NUM_CLASSES, build_model
from prep_dataset import item_intersects_tile, normalize_legacy_annotations
from verify import CLASS_COLORS_RGB, collect_fits_files, draw_diagnostic_overlay, get_tile_offsets


BASE_PRETRAINED_STEMS = {
    "yolov8n-seg",
    "yolov8s-seg",
    "yolov8m-seg",
    "yolo11n-seg",
    "yolo11s-seg",
    "yolo11m-seg",
    "yolo26n-seg",
    "yolo26s-seg",
    "yolo26m-seg",
}

KNOWN_CNN_ARCHS = [
    "mobilenet_v3_large",
    "mobilenet_v3_small",
    "mobilenet_v3",
    "efficientnet_b0",
    "resnet34",
    "resnet18",
    "astronet",
]


@dataclass
class ModelSpec:
    """Descriptor for a discovered model checkpoint to evaluate."""

    label: str
    path: Path
    kind: str  # "cnn_pt", "cnn_onnx", "yolo"
    source: str  # "explicit", "iteration", "session", "checkpoint", "run"


@dataclass
class FrameContext:
    """Precomputed shared FITS buffers, tiled inputs, and optional ground truth."""

    fits_path: Path
    width: int
    height: int
    rgb_f32: np.ndarray
    norm_f32: np.ndarray
    stf_u8: np.ndarray
    tile_positions: List[Tuple[int, int, int, int]]
    cnn_batch_np: np.ndarray
    cnn_meta_np: np.ndarray
    yolo_tiles: List[np.ndarray]
    yolo_coords: List[Tuple[int, int]]
    has_gt: bool
    gt_boxes: List[Dict[str, Any]] = field(default_factory=list)
    gt_classes: Set[str] = field(default_factory=set)
    gt_tile_targets: Optional[np.ndarray] = None  # [N_tiles, len(CLASSES)]


def resolve_device(device_arg: str) -> str:
    """Resolves 'auto', 'cuda', '0', or 'cpu' into a torch/inference device string."""
    raw = (device_arg or "auto").strip().lower()
    if raw in ("auto", ""):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if raw.isdigit():
        return f"cuda:{raw}" if torch.cuda.is_available() else "cpu"
    if raw.startswith("cuda") and not torch.cuda.is_available():
        print("Warning: CUDA requested but not available; falling back to CPU.")
        return "cpu"
    return raw


def _is_yolo_checkpoint(path: Path) -> bool:
    """Heuristically classifies a .pt checkpoint as YOLO-seg vs CNN."""
    lower = str(path).lower().replace("\\", "/")
    if path.suffix.lower() != ".pt":
        return False
    return (
        "yolo" in lower
        or "runs/segment" in lower
        or path.stem.endswith("-seg")
    )


def _derive_model_label(path: Path) -> Tuple[str, str]:
    """Derives a concise display label and source tag from a checkpoint path."""
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(TRAINING_ROOT)
        parts = rel.parts
    except ValueError:
        parts = resolved.parts

    if "iterations" in parts:
        idx = parts.index("iterations")
        iter_name = parts[idx + 1] if idx + 1 < len(parts) else "iter"
        stem = resolved.stem.replace("_best", "")
        if resolved.suffix.lower() == ".onnx":
            stem = f"{stem}_onnx"
        return f"{iter_name}/{stem}", "iteration"

    if "sessions" in parts:
        idx = parts.index("sessions")
        sess_name = parts[idx + 1] if idx + 1 < len(parts) else "session"
        parent_name = resolved.parent.name
        if parent_name == "weights" and idx + 2 < len(parts):
            sub_name = parts[idx + 2]
        else:
            sub_name = parent_name
        suffix = "_onnx" if resolved.suffix.lower() == ".onnx" else ""
        return f"sess:{sess_name}/{sub_name}{suffix}", "session"

    if "runs" in parts and resolved.parent.name == "weights":
        return f"run:{resolved.parent.parent.name}/{resolved.stem}", "run"

    if "checkpoints" in parts and resolved.parent.name not in ("checkpoints", "weights"):
        suffix = "_onnx" if resolved.suffix.lower() == ".onnx" else ""
        return f"{resolved.parent.name}/{resolved.stem}{suffix}", "checkpoint"

    return resolved.stem if resolved.suffix.lower() == ".pt" else f"{resolved.stem}_onnx", "explicit"


def _scan_directory_models(dir_path: Path, fmt: str) -> List[Path]:
    """
    Collects trained model files inside a directory, ignoring intermediate last* checkpoints
    and base pretrained YOLO weights, and deduplicating .pt/.onnx when fmt='pt'.
    """
    candidates: List[Path] = []
    for ext in ("*.pt", "*.onnx"):
        candidates.extend(dir_path.rglob(ext))

    filtered: List[Path] = []
    for p in sorted(candidates):
        if not p.is_file():
            continue
        if p.name in ("last_model.pt", "last.pt"):
            continue
        if p.stem.lower() in BASE_PRETRAINED_STEMS:
            continue
        filtered.append(p.resolve())

    if fmt == "all":
        return filtered
    if fmt == "onnx":
        return [p for p in filtered if p.suffix.lower() == ".onnx"]

    # fmt == "pt": prefer .pt, keep .onnx only if no matching .pt exists in same folder
    pt_files = [p for p in filtered if p.suffix.lower() == ".pt"]
    pt_keys = {(p.parent, p.stem.replace("_best", "").replace("best_model", "")) for p in pt_files}
    pt_parents = {p.parent for p in pt_files}
    out = list(pt_files)
    for p in filtered:
        if p.suffix.lower() == ".onnx":
            key = (p.parent, p.stem)
            if key not in pt_keys and not (p.parent in pt_parents and p.stem in ("model", "best_model")):
                out.append(p)
    return out


def _make_unique_labels(specs: List[ModelSpec]) -> List[ModelSpec]:
    """Ensures every ModelSpec has a unique label."""
    counts: Dict[str, int] = {}
    for s in specs:
        counts[s.label] = counts.get(s.label, 0) + 1

    seen_idx: Dict[str, int] = {}
    for s in specs:
        if counts[s.label] > 1:
            idx = seen_idx.get(s.label, 0) + 1
            seen_idx[s.label] = idx
            s.label = f"{s.label}#{idx}"
    return specs


def collect_model_specs(
    model_patterns: Optional[List[str]] = None,
    iterations: Optional[List[str]] = None,
    sessions: Optional[List[str]] = None,
    fmt: str = "pt",
    cnn_only: bool = False,
    yolo_only: bool = False,
) -> List[ModelSpec]:
    """
    Collects and deduplicates model checkpoints from explicit paths/globs/dirs,
    named iterations, named sessions, or default checkpoint directories.
    """
    raw_paths: List[Tuple[Path, bool]] = []  # (path, is_explicit_file)

    if model_patterns:
        for pat in model_patterns:
            p = Path(pat)
            if p.is_file():
                raw_paths.append((p.resolve(), True))
            elif p.is_dir():
                for m in _scan_directory_models(p, fmt):
                    raw_paths.append((m, False))
            else:
                matched = sorted(Path(m).resolve() for m in __import__("glob").glob(pat))
                if matched:
                    for m in matched:
                        if m.is_file():
                            raw_paths.append((m, True))
                        elif m.is_dir():
                            for sub in _scan_directory_models(m, fmt):
                                raw_paths.append((sub, False))
                else:
                    print(f"Warning: No model found matching '{pat}'")

    if iterations:
        iter_base = TRAINING_ROOT / "iterations"
        if any(it.lower() == "all" for it in iterations):
            iter_dirs = sorted([d for d in iter_base.iterdir() if d.is_dir()]) if iter_base.exists() else []
        else:
            iter_dirs = []
            for it in iterations:
                d = iter_base / it
                if d.is_dir():
                    iter_dirs.append(d)
                else:
                    print(f"Warning: Iteration directory not found: {d}")
        for d in iter_dirs:
            models_sub = d / "models"
            scan_root = models_sub if models_sub.is_dir() else d
            for m in _scan_directory_models(scan_root, fmt):
                raw_paths.append((m, False))

    if sessions:
        sess_base = TRAINING_ROOT / "checkpoints" / "sessions"
        all_sess = (
            sorted([d for d in sess_base.iterdir() if d.is_dir()], key=lambda d: d.name, reverse=True)
            if sess_base.exists()
            else []
        )
        for s_arg in sessions:
            cand = Path(s_arg)
            if cand.is_dir():
                for m in _scan_directory_models(cand, fmt):
                    raw_paths.append((m, False))
            elif s_arg.lower() == "latest":
                if all_sess:
                    for m in _scan_directory_models(all_sess[0], fmt):
                        raw_paths.append((m, False))
                else:
                    print(f"Warning: No sessions found in {sess_base}")
            elif s_arg.lower() == "all":
                for sd in all_sess:
                    for m in _scan_directory_models(sd, fmt):
                        raw_paths.append((m, False))
            else:
                matches = [d for d in all_sess if d.name == s_arg or d.name.startswith(s_arg)]
                if matches:
                    for m in _scan_directory_models(matches[0], fmt):
                        raw_paths.append((m, False))
                else:
                    print(f"Warning: Session '{s_arg}' not found in {sess_base}")

    # Default auto-discovery if user gave no explicit model selectors
    if not model_patterns and not iterations and not sessions:
        ckpt_dir = TRAINING_ROOT / "checkpoints"
        if ckpt_dir.exists():
            for child in sorted(ckpt_dir.iterdir()):
                if child.is_dir() and child.name != "sessions":
                    for m in _scan_directory_models(child, fmt):
                        raw_paths.append((m, False))
        runs_seg = TRAINING_ROOT / "runs" / "segment"
        if runs_seg.exists():
            for m in _scan_directory_models(runs_seg, fmt):
                raw_paths.append((m, False))

        if not raw_paths:
            iter_base = TRAINING_ROOT / "iterations"
            if iter_base.exists():
                iter_dirs = sorted([d for d in iter_base.iterdir() if d.is_dir()])
                if iter_dirs:
                    latest_iter = iter_dirs[-1]
                    for m in _scan_directory_models(latest_iter, fmt):
                        raw_paths.append((m, False))

    seen: Set[Path] = set()
    specs: List[ModelSpec] = []
    for path, _is_explicit in raw_paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)

        suffix = path.suffix.lower()
        if suffix == ".onnx":
            kind = "cnn_onnx"
        elif suffix == ".pt":
            kind = "yolo" if _is_yolo_checkpoint(path) else "cnn_pt"
        else:
            continue

        if cnn_only and kind == "yolo":
            continue
        if yolo_only and kind != "yolo":
            continue

        label, source = _derive_model_label(path)
        specs.append(ModelSpec(label=label, path=path, kind=kind, source=source))

    return _make_unique_labels(specs)


def _infer_cnn_arch_from_name(path: Path) -> str:
    """Infers CNN architecture name from checkpoint filename or parent directory."""
    haystack = f"{path.parent.name}_{path.stem}".lower().replace("-", "_")
    for arch in KNOWN_CNN_ARCHS:
        if arch in haystack:
            return arch
    return "astronet"


def _find_sibling_optimal_thresholds(onnx_path: Path) -> Optional[Dict[str, float]]:
    """Checks sibling .pt checkpoints for calibrated per-class thresholds."""
    stem_base = onnx_path.stem
    candidates = [
        onnx_path.parent / f"{stem_base}_best.pt",
        onnx_path.parent / "best_model.pt",
    ]
    for cand in candidates:
        if cand.exists():
            try:
                ckpt = torch.load(cand, map_location="cpu", weights_only=False)
                if isinstance(ckpt, dict) and isinstance(ckpt.get("optimal_thresholds"), dict):
                    return ckpt["optimal_thresholds"]
            except Exception:
                pass
    return None


def load_model_entry(spec: ModelSpec, device: str) -> Dict[str, Any]:
    """Loads a PyTorch CNN, ONNX CNN, or YOLO-seg checkpoint into a reusable inference handle."""
    if spec.kind == "yolo":
        from ultralytics import YOLO

        model = YOLO(str(spec.path))
        return {
            "spec": spec,
            "kind": "yolo",
            "model": model,
            "optimal_thresholds": None,
            "input_mode": "stf",
        }

    if spec.kind == "cnn_onnx":
        if ort is None:
            raise RuntimeError("onnxruntime is not installed. Install it with: pip install onnxruntime")
        avail = ort.get_available_providers()
        if device.startswith("cuda"):
            preferred = ["ROCMExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            preferred = ["CPUExecutionProvider"]
        providers = [p for p in preferred if p in avail] or ["CPUExecutionProvider"]
        session = ort.InferenceSession(str(spec.path), providers=providers)
        return {
            "spec": spec,
            "kind": "cnn_onnx",
            "model": session,
            "optimal_thresholds": _find_sibling_optimal_thresholds(spec.path),
            "input_mode": "stf",
        }

    # PyTorch CNN
    ckpt = torch.load(spec.path, map_location="cpu", weights_only=False)
    if isinstance(ckpt, dict):
        model_name = ckpt.get("model_name") or _infer_cnn_arch_from_name(spec.path)
        input_mode = ckpt.get("input_mode", "f32")
        opt_thresh = ckpt.get("optimal_thresholds")
        sd = ckpt.get("state_dict", ckpt)
    else:
        model_name = _infer_cnn_arch_from_name(spec.path)
        input_mode = "f32"
        opt_thresh = None
        sd = ckpt

    num_ckpt_classes = NUM_CLASSES
    for k in reversed(list(sd.keys())):
        if (k.endswith(".weight") or k.endswith(".bias")) and len(sd[k].shape) > 0:
            num_ckpt_classes = int(sd[k].shape[0])
            break

    model = build_model(model_name, pretrained=False, num_classes=num_ckpt_classes)
    model_dict = model.state_dict()
    adapted_sd = {}
    for k, v in sd.items():
        if k in model_dict and model_dict[k].shape == v.shape:
            adapted_sd[k] = v
        elif f"visual_extractor.{k}" in model_dict and model_dict[f"visual_extractor.{k}"].shape == v.shape:
            adapted_sd[f"visual_extractor.{k}"] = v
    model.load_state_dict(adapted_sd, strict=False)
    model.to(device)
    model.eval()

    return {
        "spec": spec,
        "kind": "cnn_pt",
        "model": model,
        "model_name": model_name,
        "num_classes": num_ckpt_classes,
        "optimal_thresholds": opt_thresh if isinstance(opt_thresh, dict) else None,
        "input_mode": input_mode,
    }


def _pad_tile_hwc(patch: np.ndarray, tile_size: int) -> np.ndarray:
    """Zero-pads an [H, W, 3] patch to [tile_size, tile_size, 3] if smaller at edges."""
    ph, pw, pc = patch.shape
    if ph == tile_size and pw == tile_size:
        return patch
    padded = np.zeros((tile_size, tile_size, pc), dtype=patch.dtype)
    padded[:ph, :pw, :] = patch
    return padded


def _compute_tile_gt_matrix(
    boxes: List[Dict[str, Any]],
    tile_positions: List[Tuple[int, int, int, int]],
    rgb_f32: np.ndarray,
    norm_f32: np.ndarray,
    tile_size: int,
) -> np.ndarray:
    """
    Computes [N_tiles, len(CLASSES)] binary ground truth matrix matching prep_dataset.py rules.
    """
    n_tiles = len(tile_positions)
    gt = np.zeros((n_tiles, len(CLASSES)), dtype=np.int32)
    if not boxes or n_tiles == 0:
        return gt

    for t_idx, (x_start, y_start, _tw, _th) in enumerate(tile_positions):
        tile_f32 = norm_f32[y_start : y_start + tile_size, x_start : x_start + tile_size]
        bg_median = None
        bg_mad = None
        peak_val = None

        for b in boxes:
            lbl = b.get("label")
            if lbl not in CLASSES:
                continue
            c_idx = CLASSES.index(lbl)

            if lbl in ("cloud", "obstruction"):
                mask = np.zeros((tile_size, tile_size), dtype=np.uint8)
                itype = b.get("type", "box")
                if itype == "polygon" and "points" in b and len(b["points"]) >= 3:
                    pts = np.array([[(p[0] - x_start), (p[1] - y_start)] for p in b["points"]], dtype=np.int32)
                    cv2.fillPoly(mask, [pts], 255)
                elif itype == "line":
                    x1 = float(b.get("x1", b.get("x", 0)))
                    y1 = float(b.get("y1", b.get("y", 0)))
                    x2 = float(b.get("x2", b.get("x", 0) + b.get("width", 0)))
                    y2 = float(b.get("y2", b.get("y", 0) + b.get("height", 0)))
                    thickness = max(10.0, float(b.get("thickness", 16.0)))
                    pt1 = (int(round(x1 - x_start)), int(round(y1 - y_start)))
                    pt2 = (int(round(x2 - x_start)), int(round(y2 - y_start)))
                    cv2.line(mask, pt1, pt2, 255, thickness=int(round(thickness)))
                else:
                    bx = int(round(float(b.get("x", 0)) - x_start))
                    by = int(round(float(b.get("y", 0)) - y_start))
                    bw = int(round(float(b.get("width", 0))))
                    bh = int(round(float(b.get("height", 0))))
                    cv2.rectangle(mask, (bx, by), (bx + bw, by + bh), 255, -1)

                overlap_ratio = float(np.count_nonzero(mask)) / float(tile_size * tile_size)
                if overlap_ratio >= 0.20:
                    gt[t_idx, c_idx] = 1

            elif lbl in ("star_trail", "unfocused_star"):
                if item_intersects_tile(b, x_start, y_start, tile_size):
                    if bg_median is None:
                        bg_median = float(np.median(tile_f32))
                        bg_mad = float(np.median(np.abs(tile_f32 - bg_median)))
                        peak_val = float(np.percentile(tile_f32, 99.8))
                    if (peak_val - bg_median) > max(0.015, 4.0 * bg_mad * 1.4826):
                        gt[t_idx, c_idx] = 1

            else:  # satellite_streak, airplane
                if item_intersects_tile(b, x_start, y_start, tile_size):
                    gt[t_idx, c_idx] = 1

    return gt


def prepare_frame_context(
    fits_path: Path,
    norm_mode: str = "stf",
    rgb_linked: bool = False,
    tile_size: int = 512,
    stride: int = 384,
    need_cnn: bool = True,
    need_yolo: bool = False,
    use_gt: bool = True,
) -> FrameContext:
    """Loads FITS frame once, computes STF/Asinh stretch, slices tiles, and loads optional GT JSON."""
    rgb_f32, meta = load_fits_unified_rgb(fits_path)
    h, w, _ = rgb_f32.shape

    ch_medians, ch_mads = [], []
    for c_idx in range(3):
        c_med, c_mad = calculate_channel_stats(rgb_f32[:, :, c_idx], stride=100)
        ch_medians.append(c_med)
        ch_mads.append(c_mad)
    stf_params = calculate_stf(ch_medians, ch_mads, rgb_linked=rgb_linked)

    if norm_mode == "asinh":
        norm_f32 = to_asinh_f32(rgb_f32)
    else:
        norm_f32 = to_auto_stf_f32(rgb_f32, rgb_linked=rgb_linked, stf_params=stf_params)

    stf_u8 = to_stf_u8(rgb_f32, rgb_linked=rgb_linked, stf_params=stf_params)

    f_med = float(meta.get("frame_median", float(np.median(rgb_f32))))
    f_mad = float(meta.get("frame_mad", float(np.median(np.abs(rgb_f32 - f_med)))))
    pixel_scale = float(meta.get("pixel_scale", 2.39))

    x_offsets = get_tile_offsets(w, tile_size, stride)
    y_offsets = get_tile_offsets(h, tile_size, stride)

    tile_positions: List[Tuple[int, int, int, int]] = []
    cnn_tiles: List[np.ndarray] = []
    cnn_metas: List[List[float]] = []
    yolo_tiles: List[np.ndarray] = []
    yolo_coords: List[Tuple[int, int]] = []

    for y_start in y_offsets:
        for x_start in x_offsets:
            y_end = min(y_start + tile_size, h)
            x_end = min(x_start + tile_size, w)
            tile_positions.append((x_start, y_start, tile_size, tile_size))

            if need_cnn:
                tile_stf = _pad_tile_hwc(norm_f32[y_start:y_end, x_start:x_end], tile_size)
                tile_linear = _pad_tile_hwc(rgb_f32[y_start:y_end, x_start:x_end], tile_size)
                tile_meta = compute_tile_metadata(tile_linear, tile_stf, f_med, f_mad, pixel_scale)
                cnn_tiles.append(np.transpose(tile_stf, (2, 0, 1)))
                cnn_metas.append(tile_meta)

            if need_yolo:
                patch_u8 = _pad_tile_hwc(stf_u8[y_start:y_end, x_start:x_end], tile_size)
                yolo_tiles.append(patch_u8)
                yolo_coords.append((x_start, y_start))

    cnn_batch_np = np.stack(cnn_tiles, axis=0).astype(np.float32) if cnn_tiles else np.empty((0, 3, tile_size, tile_size), dtype=np.float32)
    cnn_meta_np = np.stack(cnn_metas, axis=0).astype(np.float32) if cnn_metas else np.empty((0, 6), dtype=np.float32)

    # Optional sibling JSON ground truth
    json_path = fits_path.with_suffix(".json")
    has_gt = False
    gt_boxes: List[Dict[str, Any]] = []
    gt_classes: Set[str] = set()
    gt_tile_targets: Optional[np.ndarray] = None

    if use_gt and json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as fp:
                ann = json.load(fp)
            gt_boxes = normalize_legacy_annotations(ann, width=w, height=h)["boxes"]
            gt_classes = {b.get("label") for b in gt_boxes if b.get("label") in CLASSES}
            has_gt = True
            if need_cnn:
                gt_tile_targets = _compute_tile_gt_matrix(gt_boxes, tile_positions, rgb_f32, norm_f32, tile_size)
        except Exception as e:
            print(f"  Warning: Failed to parse GT JSON {json_path.name}: {e}")

    return FrameContext(
        fits_path=fits_path,
        width=w,
        height=h,
        rgb_f32=rgb_f32,
        norm_f32=norm_f32,
        stf_u8=stf_u8,
        tile_positions=tile_positions,
        cnn_batch_np=cnn_batch_np,
        cnn_meta_np=cnn_meta_np,
        yolo_tiles=yolo_tiles,
        yolo_coords=yolo_coords,
        has_gt=has_gt,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        gt_tile_targets=gt_tile_targets,
    )


def _calculate_box_iou(b1: List[float], b2: List[float]) -> float:
    """Computes IoU between two [x1, y1, x2, y2] boxes."""
    x1 = max(b1[0], b2[0])
    y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2])
    y2 = min(b1[3], b2[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    a1 = max(0.0, (b1[2] - b1[0]) * (b1[3] - b1[1]))
    a2 = max(0.0, (b2[2] - b2[0]) * (b2[3] - b2[1]))
    denom = a1 + a2 - inter
    return inter / denom if denom > 0.0 else 0.0


def infer_cnn_on_frame(
    entry: Dict[str, Any],
    ctx: FrameContext,
    device: str,
    threshold: float = 0.5,
    use_optimal_thresholds: bool = False,
    batch_size: int = 16,
) -> Dict[str, Any]:
    """Runs chunked CNN inference on pre-sliced frame tiles."""
    n_tiles = len(ctx.tile_positions)
    if n_tiles == 0:
        return {
            "kind": entry["kind"],
            "detections": [],
            "probs": np.empty((0, len(CLASSES)), dtype=np.float32),
            "pred_tile_binary": np.empty((0, len(CLASSES)), dtype=np.int32),
            "pred_classes": set(),
            "class_counts": {},
            "class_max_conf": {},
            "elapsed_sec": 0.0,
        }

    is_onnx = entry["kind"] == "cnn_onnx"
    model_or_session = entry["model"]
    opt_thresh = entry.get("optimal_thresholds") if use_optimal_thresholds else None
    per_class_thresh = [
        float(opt_thresh.get(c, threshold)) if opt_thresh else float(threshold)
        for c in CLASSES
    ]

    prob_chunks: List[np.ndarray] = []
    t0 = time.perf_counter()

    if is_onnx:
        input_names = [inp.name for inp in model_or_session.get_inputs()]
        output_name = model_or_session.get_outputs()[0].name
        for i in range(0, n_tiles, batch_size):
            b_img = ctx.cnn_batch_np[i : i + batch_size]
            b_meta = ctx.cnn_meta_np[i : i + batch_size]
            feed_dict = {input_names[0]: b_img}
            for inp_name in input_names[1:]:
                if "meta" in inp_name.lower():
                    feed_dict[inp_name] = b_meta
            logits = model_or_session.run([output_name], feed_dict)[0]
            probs_chunk = 1.0 / (1.0 + np.exp(-np.clip(logits, -20.0, 20.0)))
            prob_chunks.append(probs_chunk)
    else:
        with torch.no_grad():
            for i in range(0, n_tiles, batch_size):
                b_img = torch.from_numpy(ctx.cnn_batch_np[i : i + batch_size]).to(device)
                b_meta = torch.from_numpy(ctx.cnn_meta_np[i : i + batch_size]).to(device)
                try:
                    logits = model_or_session(b_img, b_meta)
                except TypeError:
                    logits = model_or_session(b_img)
                probs_chunk = torch.sigmoid(logits).cpu().numpy()
                prob_chunks.append(probs_chunk)

    elapsed = time.perf_counter() - t0
    probs_raw = np.concatenate(prob_chunks, axis=0)
    num_out = min(len(CLASSES), probs_raw.shape[1])

    # Align to len(CLASSES) columns
    probs = np.zeros((n_tiles, len(CLASSES)), dtype=np.float32)
    probs[:, :num_out] = probs_raw[:, :num_out]

    pred_binary = np.zeros((n_tiles, len(CLASSES)), dtype=np.int32)
    detections: List[Dict[str, Any]] = []
    pred_classes: Set[str] = set()
    class_counts: Dict[str, int] = {}
    class_max_conf: Dict[str, float] = {}

    for t_idx, ((x, y, tw, th), p_row) in enumerate(zip(ctx.tile_positions, probs)):
        tile_preds = []
        for c_idx in range(num_out):
            cls_name = CLASSES[c_idx]
            conf = float(p_row[c_idx])
            if conf >= per_class_thresh[c_idx]:
                pred_binary[t_idx, c_idx] = 1
                pred_classes.add(cls_name)
                class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                class_max_conf[cls_name] = max(class_max_conf.get(cls_name, 0.0), conf)
                tile_preds.append({"class": cls_name, "confidence": conf})
        if tile_preds:
            detections.append({
                "x": x,
                "y": y,
                "width": tw,
                "height": th,
                "predictions": tile_preds,
            })

    return {
        "kind": entry["kind"],
        "detections": detections,
        "probs": probs,
        "pred_tile_binary": pred_binary,
        "pred_classes": pred_classes,
        "class_counts": class_counts,
        "class_max_conf": class_max_conf,
        "elapsed_sec": elapsed,
        "thresholds_used": per_class_thresh,
    }


def infer_yolo_on_frame(
    entry: Dict[str, Any],
    ctx: FrameContext,
    device: str,
    conf_threshold: float = 0.25,
    iou_nms: float = 0.45,
    tile_size: int = 512,
    batch_size: int = 16,
) -> Dict[str, Any]:
    """Runs YOLO-seg tiled inference with seam IoU deduplication."""
    model = entry["model"]
    yolo_device = "0" if device.startswith("cuda") else "cpu"
    if device.startswith("cuda:"):
        yolo_device = device.split(":", 1)[1]

    raw_detections: List[Dict[str, Any]] = []
    t0 = time.perf_counter()

    for i in range(0, len(ctx.yolo_tiles), batch_size):
        b_tiles = ctx.yolo_tiles[i : i + batch_size]
        b_coords = ctx.yolo_coords[i : i + batch_size]

        try:
            results = model.predict(
                source=b_tiles,
                conf=conf_threshold,
                imgsz=tile_size,
                device=yolo_device,
                verbose=False,
            )
        except Exception:
            results = model.predict(
                source=b_tiles,
                conf=conf_threshold,
                imgsz=tile_size,
                device="cpu",
                verbose=False,
            )

        for res, (tx, ty) in zip(results, b_coords):
            if res.boxes is None or len(res.boxes) == 0:
                continue
            has_masks = res.masks is not None and len(res.masks) > 0
            for idx in range(len(res.boxes)):
                cid = int(res.boxes.cls[idx].item())
                conf = float(res.boxes.conf[idx].item())
                cname = CLASSES[cid] if 0 <= cid < len(CLASSES) else f"class_{cid}"
                bx1, by1, bx2, by2 = res.boxes.xyxy[idx].tolist()
                global_box = [bx1 + tx, by1 + ty, bx2 + tx, by2 + ty]

                poly_coords = None
                if has_masks and idx < len(res.masks.xy):
                    raw_poly = res.masks.xy[idx]
                    if len(raw_poly) >= 3:
                        poly_coords = [(float(px + tx), float(py + ty)) for px, py in raw_poly]

                raw_detections.append({
                    "class": cname,
                    "confidence": conf,
                    "box": global_box,
                    "polygon": poly_coords,
                    "tile_coord": (tx, ty),
                })

    # Seam deduplication across overlapping tiles
    raw_detections.sort(key=lambda d: d["confidence"], reverse=True)
    kept_detections: List[Dict[str, Any]] = []
    for det in raw_detections:
        is_dup = any(
            det["class"] == kept["class"] and _calculate_box_iou(det["box"], kept["box"]) > iou_nms
            for kept in kept_detections
        )
        if not is_dup:
            kept_detections.append(det)

    elapsed = time.perf_counter() - t0

    pred_classes: Set[str] = set()
    class_counts: Dict[str, int] = {}
    class_max_conf: Dict[str, float] = {}
    for det in kept_detections:
        cname = det["class"]
        if cname in CLASSES:
            pred_classes.add(cname)
        class_counts[cname] = class_counts.get(cname, 0) + 1
        class_max_conf[cname] = max(class_max_conf.get(cname, 0.0), float(det["confidence"]))

    return {
        "kind": "yolo",
        "detections": kept_detections,
        "pred_classes": pred_classes,
        "class_counts": class_counts,
        "class_max_conf": class_max_conf,
        "elapsed_sec": elapsed,
        "thresholds_used": [conf_threshold],
    }


def evaluate_cell_vs_gt(pred_classes: Set[str], gt_classes: Set[str]) -> Dict[str, Any]:
    """Evaluates frame-level prediction against ground truth class set."""
    gt_clean = len(gt_classes) == 0
    pred_clean = len(pred_classes) == 0

    if gt_clean and pred_clean:
        outcome = "TN"
    elif not gt_clean and not pred_clean:
        outcome = "TP" if pred_classes == gt_classes else "PARTIAL"
    elif gt_clean and not pred_clean:
        outcome = "FP"
    else:
        outcome = "FN"

    return {
        "outcome": outcome,
        "binary_correct": (gt_clean == pred_clean),
        "exact_match": (pred_classes == gt_classes),
        "missed_classes": sorted(gt_classes - pred_classes),
        "extra_classes": sorted(pred_classes - gt_classes),
    }


def compute_model_summary(
    label: str,
    entry: Dict[str, Any],
    cell_results: List[Dict[str, Any]],
    majority_is_clean: Dict[Path, bool],
) -> Dict[str, Any]:
    """Aggregates per-frame and per-tile metrics across all FITS frames for one model."""
    total = len(cell_results)
    latencies_ms = [c["elapsed_ms"] for c in cell_results]
    clean_pred = sum(1 for c in cell_results if c["is_clean_pred"])
    flagged_pred = total - clean_pred

    # Majority-vote consensus agreement (useful even without GT)
    consensus_hits = sum(
        1 for c in cell_results if c["is_clean_pred"] == majority_is_clean.get(c["fits_path"], c["is_clean_pred"])
    )
    consensus_acc = (consensus_hits / total) if total > 0 else 0.0

    top_confs = [max(c["class_max_conf"].values()) for c in cell_results if c["class_max_conf"]]

    summary: Dict[str, Any] = {
        "model": label,
        "kind": entry["kind"],
        "path": str(entry["spec"].path),
        "total_frames": total,
        "clean_pred": clean_pred,
        "flagged_pred": flagged_pred,
        "avg_latency_ms": round(float(np.mean(latencies_ms)), 1) if latencies_ms else 0.0,
        "total_latency_ms": round(float(np.sum(latencies_ms)), 1) if latencies_ms else 0.0,
        "consensus_agreement": round(consensus_acc, 4),
        "mean_top_conf": round(float(np.mean(top_confs)), 4) if top_confs else 0.0,
    }

    gt_cells = [c for c in cell_results if c["has_gt"]]
    summary["gt_frames"] = len(gt_cells)

    if gt_cells:
        gt_clean_cells = [c for c in gt_cells if len(c["gt_classes"]) == 0]
        gt_defect_cells = [c for c in gt_cells if len(c["gt_classes"]) > 0]

        binary_correct = sum(1 for c in gt_cells if c["gt_eval"]["binary_correct"])
        exact_matches = sum(1 for c in gt_cells if c["gt_eval"]["exact_match"])
        tn = sum(1 for c in gt_clean_cells if c["is_clean_pred"])
        fp = len(gt_clean_cells) - tn
        tp = sum(1 for c in gt_defect_cells if not c["is_clean_pred"])
        fn = len(gt_defect_cells) - tp

        frame_per_class: Dict[str, Dict[str, float]] = {}
        active_f1s: List[float] = []
        for cls_name in CLASSES:
            c_tp = sum(1 for c in gt_cells if cls_name in c["pred_classes"] and cls_name in c["gt_classes"])
            c_fp = sum(1 for c in gt_cells if cls_name in c["pred_classes"] and cls_name not in c["gt_classes"])
            c_fn = sum(1 for c in gt_cells if cls_name not in c["pred_classes"] and cls_name in c["gt_classes"])
            prec = c_tp / (c_tp + c_fp) if (c_tp + c_fp) > 0 else 0.0
            rec = c_tp / (c_tp + c_fn) if (c_tp + c_fn) > 0 else 0.0
            f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            frame_per_class[cls_name] = {
                "tp": c_tp,
                "fp": c_fp,
                "fn": c_fn,
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
            }
            if (c_tp + c_fp + c_fn) > 0:
                active_f1s.append(f1)

        summary["frame_binary_acc"] = round(binary_correct / len(gt_cells), 4)
        summary["frame_exact_match"] = round(exact_matches / len(gt_cells), 4)
        summary["clean_specificity"] = round(tn / len(gt_clean_cells), 4) if gt_clean_cells else None
        summary["defect_recall"] = round(tp / len(gt_defect_cells), 4) if gt_defect_cells else None
        summary["frame_fp"] = fp
        summary["frame_fn"] = fn
        summary["frame_macro_f1"] = round(float(np.mean(active_f1s)), 4) if active_f1s else (
            1.0 if binary_correct == len(gt_cells) else 0.0
        )
        summary["frame_per_class"] = frame_per_class

        # Tile-level metrics for CNNs when GT tile targets are present
        tile_preds_list = [c["pred_tile_binary"] for c in gt_cells if c.get("pred_tile_binary") is not None and c.get("gt_tile_targets") is not None]
        tile_targs_list = [c["gt_tile_targets"] for c in gt_cells if c.get("pred_tile_binary") is not None and c.get("gt_tile_targets") is not None]
        if tile_preds_list:
            all_tp = np.concatenate(tile_preds_list, axis=0)
            all_tt = np.concatenate(tile_targs_list, axis=0)
            tile_f1s: List[float] = []
            tile_per_class: Dict[str, Dict[str, float]] = {}
            for i, cls_name in enumerate(CLASSES):
                t_tp = int(np.sum((all_tp[:, i] == 1) & (all_tt[:, i] == 1)))
                t_fp = int(np.sum((all_tp[:, i] == 1) & (all_tt[:, i] == 0)))
                t_fn = int(np.sum((all_tp[:, i] == 0) & (all_tt[:, i] == 1)))
                t_prec = t_tp / (t_tp + t_fp) if (t_tp + t_fp) > 0 else 0.0
                t_rec = t_tp / (t_tp + t_fn) if (t_tp + t_fn) > 0 else 0.0
                t_f1 = (2.0 * t_prec * t_rec) / (t_prec + t_rec) if (t_prec + t_rec) > 0 else 0.0
                tile_per_class[cls_name] = {
                    "tp": t_tp,
                    "fp": t_fp,
                    "fn": t_fn,
                    "precision": round(t_prec, 4),
                    "recall": round(t_rec, 4),
                    "f1": round(t_f1, 4),
                }
                if (t_tp + t_fp + t_fn) > 0:
                    tile_f1s.append(t_f1)

            clean_mask = np.sum(all_tt, axis=1) == 0
            pred_clean_mask = np.sum(all_tp, axis=1) == 0
            clean_tile_acc = (
                float(np.sum(clean_mask & pred_clean_mask)) / float(np.sum(clean_mask))
                if np.sum(clean_mask) > 0
                else None
            )
            summary["tile_macro_f1"] = round(float(np.mean(tile_f1s)), 4) if tile_f1s else (
                1.0 if (clean_tile_acc == 1.0) else 0.0
            )
            summary["tile_clean_acc"] = round(clean_tile_acc, 4) if clean_tile_acc is not None else None
            summary["tile_per_class"] = tile_per_class

    return summary


def _render_gt_panel(ctx: FrameContext, include_banner: bool = True) -> Tuple[Image.Image, str, Tuple[int, int, int]]:
    """Renders ground truth annotations onto the stretched 8-bit preview."""
    base = Image.fromarray(ctx.stf_u8).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(base)

    for b in ctx.gt_boxes:
        lbl = b.get("label", "unknown")
        col = CLASS_COLORS_RGB.get(lbl, (255, 255, 255))
        fill_rgba = (*col, 70)
        line_rgba = (*col, 235)
        itype = b.get("type", "box")

        if itype == "polygon" and b.get("points") and len(b["points"]) >= 3:
            pts = [(float(p[0]), float(p[1])) for p in b["points"]]
            ov_draw.polygon(pts, fill=fill_rgba)
            ov_draw.line(pts + [pts[0]], fill=line_rgba, width=3)
            ax, ay = pts[0]
        elif itype == "line":
            x1 = float(b.get("x1", b.get("x", 0)))
            y1 = float(b.get("y1", b.get("y", 0)))
            x2 = float(b.get("x2", b.get("x", 0) + b.get("width", 0)))
            y2 = float(b.get("y2", b.get("y", 0) + b.get("height", 0)))
            thick = max(4, int(round(float(b.get("thickness", 16.0)))))
            ov_draw.line([(x1, y1), (x2, y2)], fill=line_rgba, width=thick)
            ax, ay = min(x1, x2), min(y1, y2)
        else:
            bx = float(b.get("x", 0))
            by = float(b.get("y", 0))
            bw = float(b.get("width", 0))
            bh = float(b.get("height", 0))
            ov_draw.rectangle([bx, by, bx + bw, by + bh], fill=fill_rgba, outline=line_rgba, width=3)
            ax, ay = bx, by

        tag = f"GT: {lbl.replace('_', ' ')}"
        bx_pos = max(0, min(int(ax), base.width - len(tag) * 8 - 10))
        by_pos = max(36 if include_banner else 4, min(int(ay) - 18, base.height - 20))
        draw.rectangle([bx_pos, by_pos, bx_pos + len(tag) * 8 + 8, by_pos + 18], fill=col)
        draw.text((bx_pos + 4, by_pos + 2), tag, fill=(255, 255, 255))

    combined = Image.alpha_composite(base, overlay).convert("RGB")
    gt_text = ", ".join(sorted(ctx.gt_classes)) if ctx.gt_classes else "CLEAN SKY"
    header_txt = f"GROUND TRUTH | {gt_text}"
    banner_bg = (16, 48, 32)
    if include_banner:
        c_draw = ImageDraw.Draw(combined)
        c_draw.rectangle([0, 0, combined.width, 32], fill=banner_bg)
        c_draw.text((10, 8), header_txt, fill=(235, 255, 235))
    return combined, header_txt, banner_bg


def _render_model_panel(
    ctx: FrameContext,
    label: str,
    infer_res: Dict[str, Any],
    gt_eval: Optional[Dict[str, Any]],
    include_banner: bool = True,
) -> Tuple[Image.Image, str, Tuple[int, int, int]]:
    """Renders a single model's CNN or YOLO overlay panel onto a PIL Image."""
    min_tag_y = 34 if include_banner else 4
    if infer_res["kind"] == "yolo":
        base = Image.fromarray(ctx.stf_u8).convert("RGBA")
        mask_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        mask_draw = ImageDraw.Draw(mask_layer)
        draw = ImageDraw.Draw(base)

        for det in infer_res["detections"]:
            cname = det["class"]
            conf = det["confidence"]
            poly = det.get("polygon")
            box = det["box"]
            col = CLASS_COLORS_RGB.get(cname, (255, 255, 255))
            if poly and len(poly) >= 3:
                mask_draw.polygon(poly, fill=(*col, 85))
                mask_draw.line(poly + [poly[0]], fill=(*col, 230), width=2)
                ax, ay = poly[0]
            else:
                x1, y1, x2, y2 = box
                mask_draw.rectangle([x1, y1, x2, y2], fill=(*col, 85), outline=(*col, 230), width=2)
                ax, ay = x1, y1
            tag = f"{cname.replace('_', ' ')}: {conf * 100:.1f}%"
            bx = max(0, min(int(ax), base.width - len(tag) * 8 - 8))
            by = max(min_tag_y, min(int(ay) - 18, base.height - 18))
            draw.rectangle([bx, by, bx + len(tag) * 8 + 8, by + 18], fill=col)
            draw.text((bx + 4, by + 2), tag, fill=(255, 255, 255))

        img = Image.alpha_composite(base, mask_layer).convert("RGB")
        final_draw = ImageDraw.Draw(img)
    else:
        img = Image.fromarray(ctx.stf_u8)
        final_draw = ImageDraw.Draw(img)
        for det in infer_res["detections"]:
            x, y, w, h = det["x"], det["y"], det["width"], det["height"]
            for p in det["predictions"]:
                col = CLASS_COLORS_RGB.get(p["class"], (255, 255, 255))
                final_draw.rectangle([x, y, x + w, y + h], outline=col, width=3)
                label_txt = f"{p['class'].replace('_', ' ')}: {p['confidence'] * 100:.1f}%"
                tag_y = max(min_tag_y, y - 18)
                final_draw.rectangle([x, tag_y, x + len(label_txt) * 8 + 8, tag_y + 18], fill=col)
                final_draw.text((x + 4, tag_y + 2), label_txt, fill=(255, 255, 255))

    # Header banner color-coded by GT status (when GT exists) or Clean/Flagged
    if gt_eval:
        outcome = gt_eval["outcome"]
        if outcome in ("TN", "TP"):
            banner_bg = (22, 78, 42)
        elif outcome == "PARTIAL":
            banner_bg = (115, 78, 18)
        else:  # FP / FN
            banner_bg = (128, 28, 28)
        status_suffix = f" | GT:{outcome}"
    else:
        banner_bg = (25, 35, 55) if not infer_res["pred_classes"] else (85, 45, 20)
        status_suffix = ""

    if infer_res["class_counts"]:
        det_summary = ", ".join(
            f"{cls}:{cnt}({infer_res['class_max_conf'][cls]*100:.0f}%)"
            for cls, cnt in sorted(infer_res["class_counts"].items())
        )
    else:
        det_summary = "CLEAN SKY"

    header_txt = f"{label} | {det_summary} | {infer_res['elapsed_sec']*1000:.0f}ms{status_suffix}"
    if include_banner:
        final_draw.rectangle([0, 0, img.width, 32], fill=banner_bg)
        final_draw.text((10, 8), header_txt, fill=(240, 240, 240))
    return img, header_txt, banner_bg


def render_comparison_grid(
    ctx: FrameContext,
    model_outputs: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]],
    out_path: Path,
    panel_width: int = 960,
):
    """Stitches Ground Truth (if available) + all model panels into a single grid PNG."""
    panels: List[Tuple[Image.Image, str, Tuple[int, int, int]]] = []
    if ctx.has_gt:
        panels.append(_render_gt_panel(ctx, include_banner=False))

    for label, infer_res, gt_eval in model_outputs:
        panels.append(_render_model_panel(ctx, label, infer_res, gt_eval, include_banner=False))

    if not panels:
        return

    # Resize image panels first, then draw crisp 1:1 pixel header bars above each panel
    orig_w, orig_h = panels[0][0].size
    target_w = min(orig_w, panel_width) if panel_width > 0 else orig_w
    target_h = max(1, int(round(orig_h * (target_w / float(orig_w)))))

    banner_h = 26
    n = len(panels)
    cols = 1 if n == 1 else (2 if n <= 4 else 3)
    rows = math.ceil(n / cols)
    pad = 8
    title_h = 34
    cell_h = banner_h + target_h

    canvas_w = cols * target_w + (cols + 1) * pad
    canvas_h = title_h + rows * cell_h + (rows + 1) * pad
    grid_img = Image.new("RGB", (canvas_w, canvas_h), (14, 16, 22))
    g_draw = ImageDraw.Draw(grid_img)

    gt_tag = f"GT: {', '.join(sorted(ctx.gt_classes)) if ctx.gt_classes else 'CLEAN'}" if ctx.has_gt else "No GT JSON"
    g_draw.text((pad, 10), f"Grid Verify: {ctx.fits_path.name} ({ctx.width}x{ctx.height}) | {gt_tag}", fill=(225, 230, 240))

    for idx, (panel_img, header_txt, banner_bg) in enumerate(panels):
        r = idx // cols
        c = idx % cols
        px = pad + c * (target_w + pad)
        py = title_h + pad + r * (cell_h + pad)

        resized = (
            panel_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            if panel_img.size != (target_w, target_h)
            else panel_img
        )
        g_draw.rectangle([px, py, px + target_w, py + banner_h], fill=banner_bg)
        g_draw.text((px + 8, py + 7), header_txt[: max(20, target_w // 7)], fill=(242, 244, 248))
        grid_img.paste(resized, (px, py + banner_h))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid_img.save(out_path, format="PNG")


def _format_cell_short(cell: Dict[str, Any]) -> str:
    """Formats a compact Model x Image table cell string."""
    if cell["has_gt"]:
        outcome = cell["gt_eval"]["outcome"]
        if outcome == "TN":
            return "OK(CLEAN)"
        if outcome == "TP":
            cls_tag = "+".join(sorted(cell["pred_classes"]))
            return f"OK({cls_tag})"
        if outcome == "PARTIAL":
            cls_tag = "+".join(sorted(cell["pred_classes"]))
            return f"PART({cls_tag})"
        if outcome == "FP":
            cls_tag = "+".join(sorted(cell["pred_classes"]))
            return f"FP({cls_tag})"
        return "FN(MISSED)"
    if cell["is_clean_pred"]:
        return "CLEAN"
    parts = [f"{k[:4]}:{v}" for k, v in sorted(cell["class_counts"].items())]
    return "FLAG(" + ",".join(parts) + ")"


def _safe_filename(label: str) -> str:
    return label.replace("/", "__").replace(":", "_").replace(" ", "_")


def write_reports(
    out_dir: Path,
    fits_files: List[Path],
    model_labels: List[str],
    summaries: List[Dict[str, Any]],
    matrix: Dict[Path, Dict[str, Dict[str, Any]]],
    has_any_gt: bool,
):
    """Writes grid_summary.md, grid_matrix.csv, and grid_results.json to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. CSV Matrix
    csv_path = out_dir / "grid_matrix.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow([
            "fits_file",
            "model",
            "kind",
            "is_clean_pred",
            "pred_classes",
            "class_counts",
            "class_max_conf",
            "elapsed_ms",
            "has_gt",
            "gt_classes",
            "gt_outcome",
            "binary_correct",
            "exact_match",
        ])
        for f in fits_files:
            for m in model_labels:
                c = matrix.get(f, {}).get(m)
                if not c:
                    continue
                writer.writerow([
                    f.name,
                    m,
                    c["kind"],
                    c["is_clean_pred"],
                    ",".join(sorted(c["pred_classes"])),
                    json.dumps(c["class_counts"]),
                    json.dumps({k: round(v, 4) for k, v in c["class_max_conf"].items()}),
                    round(c["elapsed_ms"], 2),
                    c["has_gt"],
                    ",".join(sorted(c["gt_classes"])) if c["has_gt"] else "",
                    c["gt_eval"]["outcome"] if c.get("gt_eval") else "",
                    c["gt_eval"]["binary_correct"] if c.get("gt_eval") else "",
                    c["gt_eval"]["exact_match"] if c.get("gt_eval") else "",
                ])

    # 2. JSON Report
    json_path = out_dir / "grid_results.json"
    serializable_matrix = {}
    for f in fits_files:
        serializable_matrix[f.name] = {}
        for m in model_labels:
            c = matrix.get(f, {}).get(m)
            if not c:
                continue
            serializable_matrix[f.name][m] = {
                "kind": c["kind"],
                "is_clean_pred": c["is_clean_pred"],
                "pred_classes": sorted(c["pred_classes"]),
                "class_counts": c["class_counts"],
                "class_max_conf": {k: round(v, 4) for k, v in c["class_max_conf"].items()},
                "elapsed_ms": round(c["elapsed_ms"], 2),
                "has_gt": c["has_gt"],
                "gt_classes": sorted(c["gt_classes"]),
                "gt_eval": c.get("gt_eval"),
            }

    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "total_fits": len(fits_files),
                "total_models": len(model_labels),
                "has_ground_truth": has_any_gt,
                "leaderboard": summaries,
                "matrix": serializable_matrix,
            },
            fp,
            indent=2,
        )

    # 3. Markdown Report
    md_path = out_dir / "grid_summary.md"
    with open(md_path, "w", encoding="utf-8") as fp:
        fp.write("# AstroGrader Grid Verification Report\n\n")
        fp.write(f"- **Generated:** {datetime.now().isoformat(timespec='seconds')}\n")
        fp.write(f"- **FITS Frames:** {len(fits_files)}\n")
        fp.write(f"- **Models Evaluated:** {len(model_labels)}\n\n")

        fp.write("## Model Leaderboard\n\n")
        if has_any_gt:
            fp.write("| Rank | Model | Kind | Frame F1 | Binary Acc | Exact Match | Clean Spec | Defect Rec | Tile F1 | Avg Time (ms) |\n")
            fp.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
            for rank, s in enumerate(summaries, 1):
                cs = f"{s['clean_specificity']:.3f}" if s.get("clean_specificity") is not None else "-"
                dr = f"{s['defect_recall']:.3f}" if s.get("defect_recall") is not None else "-"
                tf1 = f"{s['tile_macro_f1']:.3f}" if s.get("tile_macro_f1") is not None else "-"
                fp.write(
                    f"| {rank} | `{s['model']}` | {s['kind']} | **{s.get('frame_macro_f1', 0.0):.3f}** | "
                    f"{s.get('frame_binary_acc', 0.0):.3f} | {s.get('frame_exact_match', 0.0):.3f} | "
                    f"{cs} | {dr} | {tf1} | {s['avg_latency_ms']:.1f} |\n"
                )
        else:
            fp.write("| Rank | Model | Kind | Consensus | Clean Frames | Flagged Frames | Mean Top Conf | Avg Time (ms) |\n")
            fp.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n")
            for rank, s in enumerate(summaries, 1):
                fp.write(
                    f"| {rank} | `{s['model']}` | {s['kind']} | **{s['consensus_agreement']*100:.1f}%** | "
                    f"{s['clean_pred']} | {s['flagged_pred']} | {s['mean_top_conf']:.3f} | {s['avg_latency_ms']:.1f} |\n"
                )

        if has_any_gt:
            fp.write("\n## Per-Class Frame F1 Breakdown\n\n")
            fp.write("| Model | " + " | ".join(f"`{c}`" for c in CLASSES) + " |\n")
            fp.write("| :--- | " + " | ".join(":---:" for _ in CLASSES) + " |\n")
            for s in summaries:
                fpc = s.get("frame_per_class", {})
                vals = []
                for c in CLASSES:
                    info = fpc.get(c, {})
                    supp = info.get("tp", 0) + info.get("fp", 0) + info.get("fn", 0)
                    vals.append(f"{info.get('f1', 0.0):.3f}" if supp > 0 else "-")
                fp.write(f"| `{s['model']}` | " + " | ".join(vals) + " |\n")

        fp.write("\n## Image x Model Comparison Matrix\n\n")
        header_cols = ["FITS File"] + (["Ground Truth"] if has_any_gt else []) + [f"`{m}`" for m in model_labels]
        fp.write("| " + " | ".join(header_cols) + " |\n")
        fp.write("| " + " | ".join([":---"] + [":---:" for _ in header_cols[1:]]) + " |\n")
        for f in fits_files:
            row_cells = [f"`{f.name}`"]
            if has_any_gt:
                first_cell = next(iter(matrix.get(f, {}).values()), None)
                if first_cell and first_cell["has_gt"]:
                    gt_str = ", ".join(sorted(first_cell["gt_classes"])) if first_cell["gt_classes"] else "CLEAN"
                else:
                    gt_str = "No GT"
                row_cells.append(gt_str)
            for m in model_labels:
                c = matrix.get(f, {}).get(m)
                row_cells.append(_format_cell_short(c) if c else "ERR")
            fp.write("| " + " | ".join(row_cells) + " |\n")


def run_grid_verify(
    fits_patterns: List[str],
    model_patterns: Optional[List[str]] = None,
    iterations: Optional[List[str]] = None,
    sessions: Optional[List[str]] = None,
    fmt: str = "pt",
    cnn_only: bool = False,
    yolo_only: bool = False,
    out_dir: Path = Path("grid_verification_output"),
    threshold: float = 0.5,
    yolo_conf: float = 0.25,
    use_optimal_thresholds: bool = False,
    norm_mode: str = "stf",
    rgb_linked: bool = False,
    tile_size: int = 512,
    stride: int = 384,
    batch_size: int = 16,
    device_arg: str = "auto",
    panel_width: int = 960,
    save_individual: bool = False,
    no_images: bool = False,
    no_gt: bool = False,
) -> Dict[str, Any]:
    """Executes the full Model x FITS grid verification pipeline."""
    fits_files = collect_fits_files(fits_patterns)
    if not fits_files:
        print("Error: No valid FITS files found to verify.")
        return {"summaries": [], "matrix": {}}

    model_specs = collect_model_specs(
        model_patterns=model_patterns,
        iterations=iterations,
        sessions=sessions,
        fmt=fmt,
        cnn_only=cnn_only,
        yolo_only=yolo_only,
    )
    if not model_specs:
        print("Error: No valid model checkpoints found. Pass --models, --iterations, or --sessions.")
        return {"summaries": [], "matrix": {}}

    device = resolve_device(device_arg)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 72)
    print("               AstroGrader Grid Verification Runner                  ")
    print("=" * 72)
    print(f"FITS Files:   {len(fits_files)}")
    print(f"Models Found: {len(model_specs)}")
    for idx, sp in enumerate(model_specs, 1):
        print(f"  {idx:2d}. [{sp.kind:8s}] {sp.label:<30s} ({sp.path})")
    print(f"Device:       {device}")
    print(f"Norm Mode:    {norm_mode.upper()} ({'Linked' if rgb_linked else 'Unlinked'} RGB)")
    print(f"Tile / Stride:{tile_size} / {stride} (Batch: {batch_size})")
    print(f"CNN Cut:      {threshold:.2f} ({'per-class optimal if present' if use_optimal_thresholds else 'fixed'})")
    print(f"YOLO Cut:     {yolo_conf:.2f}")
    print(f"Output Dir:   {out_dir}")
    print("=" * 72 + "\n")

    # Load all models once
    loaded_models: List[Tuple[str, Dict[str, Any]]] = []
    for sp in model_specs:
        try:
            entry = load_model_entry(sp, device=device)
            loaded_models.append((sp.label, entry))
        except Exception as e:
            print(f"Warning: Skipping model '{sp.label}' ({sp.path}): {e}")

    if not loaded_models:
        print("Error: Failed to load any models.")
        return {"summaries": [], "matrix": {}}

    need_cnn = any(e["kind"] in ("cnn_pt", "cnn_onnx") for _, e in loaded_models)
    need_yolo = any(e["kind"] == "yolo" for _, e in loaded_models)
    model_labels = [lbl for lbl, _ in loaded_models]

    matrix: Dict[Path, Dict[str, Dict[str, Any]]] = {}
    per_model_cells: Dict[str, List[Dict[str, Any]]] = {lbl: [] for lbl in model_labels}
    has_any_gt = False

    for f_idx, fits_path in enumerate(fits_files, 1):
        print(f"[{f_idx}/{len(fits_files)}] {fits_path.name}")
        try:
            ctx = prepare_frame_context(
                fits_path=fits_path,
                norm_mode=norm_mode,
                rgb_linked=rgb_linked,
                tile_size=tile_size,
                stride=stride,
                need_cnn=need_cnn,
                need_yolo=need_yolo,
                use_gt=not no_gt,
            )
        except Exception as e:
            print(f"  Error loading {fits_path.name}: {e}")
            continue

        if ctx.has_gt:
            has_any_gt = True
            gt_str = ", ".join(sorted(ctx.gt_classes)) if ctx.gt_classes else "CLEAN SKY"
            print(f"  Ground Truth: {gt_str}")
        else:
            print("  Ground Truth: [No sibling .json]")

        matrix[fits_path] = {}
        panel_outputs: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]] = []

        for label, entry in loaded_models:
            if entry["kind"] == "yolo":
                infer_res = infer_yolo_on_frame(
                    entry=entry,
                    ctx=ctx,
                    device=device,
                    conf_threshold=yolo_conf,
                    tile_size=tile_size,
                    batch_size=batch_size,
                )
            else:
                infer_res = infer_cnn_on_frame(
                    entry=entry,
                    ctx=ctx,
                    device=device,
                    threshold=threshold,
                    use_optimal_thresholds=use_optimal_thresholds,
                    batch_size=batch_size,
                )

            pred_classes = infer_res["pred_classes"]
            is_clean_pred = len(pred_classes) == 0
            gt_eval = evaluate_cell_vs_gt(pred_classes, ctx.gt_classes) if ctx.has_gt else None
            elapsed_ms = infer_res["elapsed_sec"] * 1000.0

            cell_record = {
                "fits_path": fits_path,
                "kind": entry["kind"],
                "is_clean_pred": is_clean_pred,
                "pred_classes": pred_classes,
                "class_counts": infer_res["class_counts"],
                "class_max_conf": infer_res["class_max_conf"],
                "elapsed_ms": elapsed_ms,
                "has_gt": ctx.has_gt,
                "gt_classes": ctx.gt_classes,
                "gt_eval": gt_eval,
                "pred_tile_binary": infer_res.get("pred_tile_binary"),
                "gt_tile_targets": ctx.gt_tile_targets,
            }
            matrix[fits_path][label] = cell_record
            per_model_cells[label].append(cell_record)
            panel_outputs.append((label, infer_res, gt_eval))

            det_txt = (
                ", ".join(
                    f"{k}:{v}({infer_res['class_max_conf'][k]*100:.0f}%)"
                    for k, v in sorted(infer_res["class_counts"].items())
                )
                if infer_res["class_counts"]
                else "CLEAN SKY"
            )
            gt_tag = f" | GT:{gt_eval['outcome']}" if gt_eval else ""
            print(f"    - {label:<28s} -> {det_txt:<35s} ({elapsed_ms:6.1f}ms){gt_tag}")

            if save_individual and not no_images:
                indiv_dir = out_dir / "individual" / _safe_filename(label)
                indiv_dir.mkdir(parents=True, exist_ok=True)
                indiv_png = indiv_dir / f"{fits_path.stem}_inspection.png"
                if entry["kind"] == "yolo":
                    panel_img, _, _ = _render_model_panel(ctx, label, infer_res, gt_eval)
                    panel_img.save(indiv_png, format="PNG")
                else:
                    verdict_str = f"Model: {label} | File: {fits_path.name} | Verdict: {'CLEAN SKY' if is_clean_pred else 'FLAGGED'} | Time: {elapsed_ms:.1f}ms"
                    draw_diagnostic_overlay(ctx.stf_u8, infer_res["detections"], indiv_png, verdict_str)

        if not no_images and panel_width != 0:
            grid_png = out_dir / f"{fits_path.stem}_grid.png"
            render_comparison_grid(ctx, panel_outputs, grid_png, panel_width=panel_width)
            print(f"  Saved comparison grid: {grid_png.name}")

    # Compute majority consensus per frame
    majority_is_clean: Dict[Path, bool] = {}
    for f in fits_files:
        cells = list(matrix.get(f, {}).values())
        if not cells:
            continue
        clean_votes = sum(1 for c in cells if c["is_clean_pred"])
        majority_is_clean[f] = clean_votes >= (len(cells) / 2.0)

    summaries = [
        compute_model_summary(lbl, entry, per_model_cells[lbl], majority_is_clean)
        for lbl, entry in loaded_models
        if per_model_cells[lbl]
    ]

    if has_any_gt:
        summaries.sort(
            key=lambda s: (
                s.get("frame_macro_f1", 0.0),
                s.get("frame_binary_acc", 0.0),
                s.get("tile_macro_f1", 0.0) if s.get("tile_macro_f1") is not None else -1.0,
                -s["avg_latency_ms"],
            ),
            reverse=True,
        )
    else:
        summaries.sort(
            key=lambda s: (s["consensus_agreement"], -s["avg_latency_ms"]),
            reverse=True,
        )

    write_reports(out_dir, fits_files, model_labels, summaries, matrix, has_any_gt)

    # Print Terminal Matrix & Leaderboard
    print("\n" + "=" * 72)
    print("                     IMAGE x MODEL MATRIX                           ")
    print("=" * 72)
    col_w = 18
    header_parts = [f"{'FITS File':<28}"]
    if has_any_gt:
        header_parts.append(f"{'GT':<14}")
    header_parts.extend(f"{m[:col_w-1]:<{col_w}}" for m in model_labels)
    print(" ".join(header_parts))
    print("-" * min(160, 30 + (15 if has_any_gt else 0) + col_w * len(model_labels)))

    for f in fits_files:
        row_parts = [f"{f.name[:27]:<28}"]
        if has_any_gt:
            first_c = next(iter(matrix.get(f, {}).values()), None)
            gt_s = ("+".join(sorted(first_c["gt_classes"])) if first_c["gt_classes"] else "CLEAN") if (first_c and first_c["has_gt"]) else "NoGT"
            row_parts.append(f"{gt_s[:13]:<14}")
        for m in model_labels:
            c = matrix.get(f, {}).get(m)
            cell_s = _format_cell_short(c)[: col_w - 1] if c else "ERR"
            row_parts.append(f"{cell_s:<{col_w}}")
        print(" ".join(row_parts))

    print("\n" + "=" * 72)
    print("                  MODEL LEADERBOARD (BEST -> WORST)                 ")
    print("=" * 72)
    if has_any_gt:
        print(f"{'Rank':<5} {'Model':<28} {'Kind':<8} {'FrmF1':<7} {'BinAcc':<7} {'Exact':<7} {'CleanSp':<8} {'DefRec':<7} {'TileF1':<7} {'AvgMs':<7}")
        print("-" * 102)
        for rank, s in enumerate(summaries, 1):
            tag = " [BEST]" if rank == 1 and len(summaries) > 1 else (" [WORST]" if rank == len(summaries) and len(summaries) > 1 else "")
            cs = f"{s['clean_specificity']:.3f}" if s.get("clean_specificity") is not None else "-"
            dr = f"{s['defect_recall']:.3f}" if s.get("defect_recall") is not None else "-"
            tf1 = f"{s['tile_macro_f1']:.3f}" if s.get("tile_macro_f1") is not None else "-"
            print(
                f"#{rank:<4} {s['model']:<28} {s['kind']:<8} {s.get('frame_macro_f1', 0.0):<7.3f} "
                f"{s.get('frame_binary_acc', 0.0):<7.3f} {s.get('frame_exact_match', 0.0):<7.3f} "
                f"{cs:<8} {dr:<7} {tf1:<7} {s['avg_latency_ms']:<7.1f}{tag}"
            )
    else:
        print(f"{'Rank':<5} {'Model':<28} {'Kind':<8} {'Consens':<8} {'Clean':<6} {'Flagged':<8} {'MeanConf':<9} {'AvgMs':<7}")
        print("-" * 88)
        for rank, s in enumerate(summaries, 1):
            print(
                f"#{rank:<4} {s['model']:<28} {s['kind']:<8} {s['consensus_agreement']*100:<7.1f}% "
                f"{s['clean_pred']:<6} {s['flagged_pred']:<8} {s['mean_top_conf']:<9.3f} {s['avg_latency_ms']:<7.1f}"
            )

    print("\nReports saved in:")
    print(f"  - {out_dir / 'grid_summary.md'}")
    print(f"  - {out_dir / 'grid_matrix.csv'}")
    print(f"  - {out_dir / 'grid_results.json'}")
    if not no_images and panel_width != 0:
        print(f"  - {out_dir / '*_grid.png'}")
    print("=" * 72 + "\n")

    return {"summaries": summaries, "matrix": matrix}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run all models across all FITS files in a comparison grid to evaluate which model is best/worst."
    )
    parser.add_argument(
        "--fits",
        type=str,
        nargs="+",
        required=True,
        help="Path(s) to FITS file(s), glob pattern(s), or directory(ies)",
    )
    parser.add_argument(
        "--models",
        type=str,
        nargs="+",
        default=None,
        help="Model path(s), glob pattern(s), or directory(ies). Defaults to checkpoints/ + runs/segment/",
    )
    parser.add_argument(
        "--iterations",
        type=str,
        nargs="+",
        default=None,
        help="Iteration name(s) under training/iterations/ (e.g. v1 v2 v3 or 'all')",
    )
    parser.add_argument(
        "--sessions",
        type=str,
        nargs="+",
        default=None,
        help="Session ID(s) under training/checkpoints/sessions/ (e.g. 'latest', 'all', or ID prefix)",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="pt",
        choices=["pt", "onnx", "all"],
        help="Model format filter when scanning directories (default: pt)",
    )
    parser.add_argument("--cnn-only", action="store_true", help="Evaluate only CNN models")
    parser.add_argument("--yolo-only", action="store_true", help="Evaluate only YOLO-seg models")
    parser.add_argument("--out-dir", type=str, default="grid_verification_output", help="Directory for grid reports and PNGs")
    parser.add_argument("--threshold", type=float, default=0.5, help="CNN detection threshold [0.0 - 1.0] (default: 0.5)")
    parser.add_argument("--yolo-conf", type=float, default=0.25, help="YOLO confidence threshold [0.0 - 1.0] (default: 0.25)")
    parser.add_argument("--use-optimal-thresholds", action="store_true", help="Use per-class optimal_thresholds from CNN checkpoints when available")
    parser.add_argument("--norm-mode", type=str, default="stf", choices=["asinh", "stf"], help="Normalization mode for CNNs (default: stf)")
    parser.add_argument("--linked-rgb", action="store_true", help="Use linked RGB STF (default is unlinked)")
    parser.add_argument("--tile-size", type=int, default=512, help="Tile size in pixels (default: 512)")
    parser.add_argument("--stride", type=int, default=384, help="Tile stride in pixels (default: 384)")
    parser.add_argument("--batch-size", type=int, default=16, help="Inference batch size per forward pass (default: 16)")
    parser.add_argument("--device", type=str, default="auto", help="Device: auto, cpu, cuda, or GPU index (default: auto)")
    parser.add_argument("--panel-width", type=int, default=960, help="Panel width in comparison grid PNGs (0 to skip grid PNGs)")
    parser.add_argument("--save-individual", action="store_true", help="Also save individual full-res per-model inspection PNGs")
    parser.add_argument("--no-images", action="store_true", help="Skip saving all PNG images (benchmark & reports only)")
    parser.add_argument("--no-gt", action="store_true", help="Ignore sibling .json ground truth files and use inter-model consensus")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    run_grid_verify(
        fits_patterns=args.fits,
        model_patterns=args.models,
        iterations=args.iterations,
        sessions=args.sessions,
        fmt=args.format,
        cnn_only=args.cnn_only,
        yolo_only=args.yolo_only,
        out_dir=Path(args.out_dir),
        threshold=args.threshold,
        yolo_conf=args.yolo_conf,
        use_optimal_thresholds=args.use_optimal_thresholds,
        norm_mode=args.norm_mode,
        rgb_linked=args.linked_rgb,
        tile_size=args.tile_size,
        stride=args.stride,
        batch_size=args.batch_size,
        device_arg=args.device,
        panel_width=args.panel_width,
        save_individual=args.save_individual,
        no_images=args.no_images,
        no_gt=args.no_gt,
    )
