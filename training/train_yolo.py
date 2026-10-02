#!/usr/bin/env python3
"""
AstroGrader: YOLO11 Instance Segmentation Training Runner.
Trains Ultralytics YOLO11-seg on sliced astronomical defect tiles (512x512).
Evaluates Mask/Box mAP and exports to ONNX for the AstroGrader Rust engine.
"""

import argparse
import os
from pathlib import Path
import sys

import torch
from ultralytics import YOLO


def check_dataset_yaml(yaml_path: Path) -> Path:
    """Ensures dataset.yaml exists and resolves absolute path."""
    resolved = yaml_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            f"YOLO dataset config not found at: {resolved}\n"
            f"Please run prep_dataset.py first, for example:\n"
            f"  python prep_dataset.py --data-dir ../TRAINING_FILES --out-dir dataset --export-yolo"
        )
    return resolved


def train_yolo(
    model_name: str = "yolo11n-seg.pt",
    data_yaml: str = "dataset_yolo/dataset.yaml",
    epochs: int = 30,
    batch: int = 16,
    imgsz: int = 512,
    device: str = None,
    workers: int = 8,
    project: str = "runs/segment",
    name: str = "yolo11_astro",
    lr0: float = 0.001,
    export_onnx: bool = True,
):
    yaml_path = check_dataset_yaml(Path(data_yaml))

    # Auto-detect device
    if device is None or device == "":
        if torch.cuda.is_available():
            device = "0"
            device_name = torch.cuda.get_device_name(0)
        else:
            device = "cpu"
            device_name = "CPU"
    else:
        device_name = device

    print("=" * 60)
    print("      AstroGrader: YOLO11-seg Instance Segmentation Training")
    print("=" * 60)
    print(f"Model Backbone: {model_name}")
    print(f"Dataset YAML:   {yaml_path}")
    print(f"Image Size:     {imgsz}x{imgsz}")
    print(f"Batch Size:     {batch}")
    print(f"Epochs:         {epochs}")
    print(f"Device:         {device} ({device_name})")
    print(f"Save Run:       {project}/{name}")
    print("=" * 60 + "\n")

    # Load YOLO11 segmentation model
    model = YOLO(model_name)

    # Train model
    # Note: flipud and fliplr are 0.5 because astronomical images are rotationally invariant.
    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        batch=batch,
        imgsz=imgsz,
        device=device,
        workers=workers,
        project=project,
        name=name,
        exist_ok=True,
        lr0=lr0,
        fliplr=0.5,
        flipud=0.5,
        mosaic=0.5,
        close_mosaic=5,
        verbose=True,
    )

    print("\n" + "=" * 60)
    print("                 Training Complete - Validating")
    print("=" * 60)

    # Validate best checkpoint
    metrics = model.val()

    # Report Box and Mask metrics
    print("\nValidation Metrics Summary:")
    if hasattr(metrics, "box"):
        print(f"  Box  mAP@50:    {metrics.box.map50 * 100:.2f}%")
        print(f"  Box  mAP@50-95: {metrics.box.map * 100:.2f}%")
    if hasattr(metrics, "seg"):
        print(f"  Mask mAP@50:    {metrics.seg.map50 * 100:.2f}%")
        print(f"  Mask mAP@50-95: {metrics.seg.map * 100:.2f}%")

    # Export to ONNX if requested
    if export_onnx:
        print("\nExporting best model to ONNX for AstroGrader Rust engine...")
        try:
            onnx_path = model.export(
                format="onnx",
                imgsz=imgsz,
                dynamic=False,
                simplify=True,
            )
            print(f"  Exported ONNX model: {onnx_path}")
        except Exception as e:
            print(f"  Warning: ONNX export failed: {e}")

    print("\nAll done! Weights and validation figures saved under:")
    print(f"  {Path(project) / name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstroGrader YOLO11-seg Training Runner")
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n-seg.pt",
        help="Model backbone weights (e.g. yolo11n-seg.pt, yolo11s-seg.pt, yolo11m-seg.pt)",
    )
    parser.add_argument(
        "--data",
        type=str,
        default="dataset_yolo/dataset.yaml",
        help="Path to YOLO dataset.yaml file",
    )
    parser.add_argument("--epochs", type=int, default=30, help="Number of epochs to train")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=512, help="Image size in pixels (default: 512)")
    parser.add_argument("--device", type=str, default=None, help="Device (0, cpu, or auto)")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader worker threads")
    parser.add_argument("--project", type=str, default="runs/segment", help="Project save directory")
    parser.add_argument("--name", type=str, default="yolo11_astro", help="Experiment name")
    parser.add_argument("--lr", type=float, default=0.001, help="Initial learning rate")
    parser.add_argument(
        "--no-onnx",
        action="store_true",
        help="Skip automatic ONNX export after training",
    )

    args = parser.parse_args()
    train_yolo(
        model_name=args.model,
        data_yaml=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        project=args.project,
        name=args.name,
        lr0=args.lr,
        export_onnx=not args.no_onnx,
    )
