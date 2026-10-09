#!/usr/bin/env python3
"""
AstroGrader: Master End-to-End Astronomical Training Pipeline.
Orchestrates:
1. Parallel slicing of full-resolution FITS into 512x512 tiles for CNNs and YOLO-seg.
2. Training Ultralytics YOLO11-seg with Early Stopping.
3. Training CNN Backbones (AstroNet, ResNet18, MobileNetV3, EfficientNetB0) with Early Stopping.
4. Exporting models to ONNX.
5. Comprehensive benchmark comparison summary report.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Dict, List, Optional

# Ensure training root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_analyzer import analyze_dataset, print_cli_report
from prep_dataset import prepare_dataset
from train_yolo import train_yolo
from fits_utils import CLASSES


def print_banner(text: str):
    print("\n" + "=" * 70)
    print(f" {text}".center(70))
    print("=" * 70 + "\n")


def run_cnn_training(
    model_name: str,
    dataset_dir: Path,
    epochs: int,
    batch_size: int,
    patience: int,
    lr: float,
    device_arg: Optional[str],
    out_dir: Path,
) -> Dict:
    """Invokes train.py as a subprocess to keep PyTorch CUDA context clean between architectures."""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "train.py"),
        "--model", model_name,
        "--dataset-dir", str(dataset_dir),
        "--epochs", str(epochs),
        "--batch-size", str(batch_size),
        "--patience", str(patience),
        "--lr", str(lr),
        "--out-dir", str(out_dir),
    ]

    print(f"\n>>> Running CNN Training: {model_name} (Epochs: {epochs}, Patience: {patience})")
    t0 = time.time()
    env = os.environ.copy()
    if device_arg:
        env["CUDA_VISIBLE_DEVICES"] = device_arg

    ret = subprocess.run(cmd, env=env)
    elapsed = time.time() - t0

    history_path = out_dir / f"{model_name}_f32" / "training_history.json"
    best_f1 = 0.0
    clean_acc = 0.0
    best_epoch = 0

    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as fp:
                hist = json.load(fp)
            if hist:
                best_entry = max(hist, key=lambda x: x.get("macro_f1", 0.0))
                best_f1 = best_entry.get("macro_f1", 0.0)
                clean_acc = best_entry.get("clean_sky_accuracy", 0.0)
                best_epoch = best_entry.get("epoch", 0)
        except Exception as e:
            print(f"Warning: Failed to parse history for {model_name}: {e}")

    return {
        "model": model_name,
        "success": (ret.returncode == 0),
        "elapsed_sec": elapsed,
        "best_epoch": best_epoch,
        "macro_f1": best_f1,
        "clean_sky_acc": clean_acc,
        "checkpoint": str(out_dir / f"{model_name}_f32" / "best_model.pt"),
    }


def main():
    parser = argparse.ArgumentParser(description="AstroGrader Master Training Pipeline")

    # Dataset & Paths
    parser.add_argument("--data-dir", type=str, default="TRAINING_FILES", nargs="+",
                        help="Path(s) to raw FITS and JSON annotations directory")
    parser.add_argument("--out-dir", type=str, default="dataset",
                        help="Output directory for sliced CNN dataset")
    parser.add_argument("--yolo-dir", type=str, default="dataset_yolo",
                        help="Output directory for YOLO segmentation dataset")
    parser.add_argument("--val-split", type=float, default=0.2,
                        help="Validation split ratio (default: 0.2)")

    # Slicing parameters
    parser.add_argument("--tile-size", type=int, default=512, help="Tile crop size (default: 512)")
    parser.add_argument("--stride", type=int, default=460, help="Tile stride in pixels (default: 460)")
    parser.add_argument("--bg-ratio", type=float, default=0.15,
                        help="Ratio of clean background tiles to include in YOLO dataset (default: 0.15)")

    # Execution phases
    parser.add_argument("--skip-prep", action="store_true", help="Skip dataset slicing")
    parser.add_argument("--skip-yolo", action="store_true", help="Skip YOLO segmentation training")
    parser.add_argument("--skip-cnn", action="store_true", help="Skip CNN classification training")

    # Models & Hyperparameters
    parser.add_argument("--cnn-models", nargs="+", default=["astronet", "resnet18", "mobilenet_v3", "efficientnet_b0"],
                        help="CNN models to train")
    parser.add_argument("--yolo-backbone", type=str, default="yolo11n-seg.pt",
                        help="YOLO model backbone weights")
    parser.add_argument("--yolo-epochs", type=int, default=30, help="Epochs for YOLO training")
    parser.add_argument("--yolo-batch", type=int, default=16, help="Batch size for YOLO")
    parser.add_argument("--cnn-epochs", type=int, default=20, help="Epochs for CNN models")
    parser.add_argument("--cnn-batch", type=int, default=16, help="Batch size for CNNs")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--patience", type=int, default=5,
                        help="Early stopping patience in epochs (default: 5)")
    parser.add_argument("--device", type=str, default=None, help="Device to use (e.g. 0, cpu)")
    parser.add_argument("--no-amp", action="store_true", help="Disable mixed precision")
    parser.add_argument("--no-onnx", action="store_true", help="Skip ONNX exports")

    args = parser.parse_args()

    overall_start = time.time()
    print_banner("AstroGrader: Master End-to-End Training Pipeline")

    # Step 0: Dataset Health Pre-Check
    print_banner("Step 0: Dataset Health Pre-Check")
    try:
        health_stats = analyze_dataset(args.data_dir)
        print_cli_report(health_stats)
    except Exception as e:
        print(f"Warning: Health check skipped due to error: {e}")

    # Step 1: Dataset Slicing & Preparation
    if not args.skip_prep:
        print_banner("Step 1: Parallel FITS Slicing for CNNs and YOLO-seg")
        prepare_dataset(
            data_dir=args.data_dir,
            out_dir=Path(args.out_dir),
            val_split=args.val_split,
            tile_size=args.tile_size,
            stride=args.stride,
            export_yolo=True,
            yolo_dir=args.yolo_dir,
            bg_ratio=args.bg_ratio,
        )
    else:
        print("\n>>> Skipping Step 1: Dataset Slicing (--skip-prep)")

    benchmark_results = []

    # Step 2: YOLO11 Instance Segmentation Training
    if not args.skip_yolo:
        print_banner("Step 2: Ultralytics YOLO11-seg Training")
        t0_yolo = time.time()
        yaml_path = Path(args.yolo_dir) / "dataset.yaml"
        if not yaml_path.exists():
            print(f"Error: YOLO config {yaml_path} does not exist. Ensure Step 1 completed successfully.")
        else:
            train_yolo(
                model_name=args.yolo_backbone,
                data_yaml=str(yaml_path),
                epochs=args.yolo_epochs,
                batch=args.yolo_batch,
                imgsz=args.tile_size,
                device=args.device,
                name="yolo11_astro",
                lr0=args.lr,
                patience=args.patience,
                amp=not args.no_amp,
                export_onnx=not args.no_onnx,
            )
            elapsed_yolo = time.time() - t0_yolo
            benchmark_results.append({
                "model": "YOLO11-seg",
                "task": "Instance Segmentation",
                "metric_name": "Mask / Box mAP",
                "metric_val": "Saved in runs/segment",
                "elapsed": f"{elapsed_yolo:.1f}s",
                "checkpoint": f"runs/segment/yolo11_astro/weights/best.pt",
            })
    else:
        print("\n>>> Skipping Step 2: YOLO Training (--skip-yolo)")

    # Step 3: CNN Multi-Model Training
    if not args.skip_cnn:
        print_banner("Step 3: CNN Backbones Multi-Model Training")
        checkpoints_dir = Path("checkpoints")
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        for m_name in args.cnn_models:
            res = run_cnn_training(
                model_name=m_name,
                dataset_dir=Path(args.out_dir),
                epochs=args.cnn_epochs,
                batch_size=args.cnn_batch,
                patience=args.patience,
                lr=args.lr,
                device_arg=args.device,
                out_dir=checkpoints_dir,
            )
            benchmark_results.append({
                "model": res["model"],
                "task": "Multi-Label Classification",
                "metric_name": "Macro F1 / Clean Acc",
                "metric_val": f"{res['macro_f1']:.4f} / {res['clean_sky_acc']:.4f} (ep {res['best_epoch']})",
                "elapsed": f"{res['elapsed_sec']:.1f}s",
                "checkpoint": res["checkpoint"],
            })
    else:
        print("\n>>> Skipping Step 3: CNN Training (--skip-cnn)")

    # Step 4: Master Benchmark Report
    total_elapsed = time.time() - overall_start
    print_banner("Pipeline Execution Summary & Model Benchmarks")
    print(f"Total Pipeline Runtime: {total_elapsed:.1f}s\n")

    header = f"{'Model':<18} {'Task':<26} {'Key Metric':<30} {'Time':<9} {'Checkpoint'}"
    print(header)
    print("-" * 105)
    for b in benchmark_results:
        print(f"{b['model']:<18} {b['task']:<26} {b['metric_val']:<30} {b['elapsed']:<9} {b['checkpoint']}")
    print("-" * 105 + "\n")


if __name__ == "__main__":
    main()
