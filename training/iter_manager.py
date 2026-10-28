#!/usr/bin/env python3
"""
AstroGrader Model & Experiment Iteration Manager.

Provides a unified CLI to manage, package, compare, and activate model iterations
for research and diploma thesis tracking.

Key capabilities:
- Create named iterations (e.g. iter_1, iter_2, ...) with metadata, dataset stats, and metrics.
- Pick and swap specific checkpoints (YOLO and CNNs) across sessions into an iteration.
- Extract detailed metrics (mAP50, Precision, Recall, F1, Loss, Clean Acc) from .pt and history JSONs.
- Compare iterations side-by-side with delta analysis and LaTeX / Markdown export for thesis chapters.
- Activate any iteration so master_train.py can seamlessly resume / fine-tune from it.
"""

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

import torch

# Ensure training root on sys.path
TRAINING_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING_ROOT))

from fits_utils import CLASSES


ITERATIONS_DIR = TRAINING_ROOT / "iterations"
CHECKPOINTS_DIR = TRAINING_ROOT / "checkpoints"
RUNS_DIR = TRAINING_ROOT / "runs"
SESSIONS_DIR = CHECKPOINTS_DIR / "sessions"


def print_banner(text: str):
    print("\n" + "=" * 70)
    print(f" {text}".center(70))
    print("=" * 70 + "\n")


def parse_yolo_results_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Parses Ultralytics YOLO results.csv into structured per-epoch records."""
    if not csv_path.exists():
        return []
    history = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                epoch_entry = {}
                for k, v in clean_row.items():
                    try:
                        if k == "epoch":
                            epoch_entry[k] = int(v)
                        else:
                            epoch_entry[k] = float(v)
                    except (ValueError, TypeError):
                        epoch_entry[k] = v
                history.append(epoch_entry)
    except Exception as e:
        print(f"Warning: Failed to parse YOLO results.csv: {e}")
    return history


def extract_cnn_checkpoint_info(pt_path: Path) -> Dict[str, Any]:
    """Extracts metadata and validation metrics from a CNN best_model.pt checkpoint."""
    if not pt_path.exists():
        return {}

    info: Dict[str, Any] = {
        "file": str(pt_path),
        "size_mb": round(pt_path.stat().st_size / (1024 * 1024), 2),
    }

    try:
        data = torch.load(pt_path, map_location="cpu", weights_only=False)
        if isinstance(data, dict):
            info["epoch"] = data.get("epoch")
            info["model_name"] = data.get("model_name")
            info["input_mode"] = data.get("input_mode")
            raw_metrics = data.get("metrics", {})
            if raw_metrics:
                info["metrics"] = raw_metrics
                info["macro_f1"] = raw_metrics.get("macro_f1")
                info["clean_sky_accuracy"] = raw_metrics.get("clean_sky_accuracy")
    except Exception as e:
        info["load_error"] = str(e)

    # Also check sibling training_history.json if present
    hist_candidates = [
        pt_path.parent / "training_history.json",
        pt_path.parent / f"{pt_path.stem.replace('_best', '')}_training_history.json",
    ]
    for hist_path in hist_candidates:
        if hist_path.exists():
            try:
                with open(hist_path, "r", encoding="utf-8") as fp:
                    hist = json.load(fp)
                if hist and isinstance(hist, list):
                    info["training_history"] = hist
                    info["total_epochs_run"] = len(hist)
                    best_entry = hist[-1]
                    if info.get("epoch"):
                        matching = [h for h in hist if h.get("epoch") == info["epoch"]]
                        if matching:
                            best_entry = matching[0]
                    else:
                        best_entry = max(hist, key=lambda x: x.get("macro_f1", 0.0))
                        info["best_epoch"] = best_entry.get("epoch", 0)

                    if "best_epoch" not in info and info.get("epoch") is not None:
                        info["best_epoch"] = info["epoch"]

                    info["history_metrics"] = best_entry
                    if "macro_f1" not in info and "macro_f1" in best_entry:
                        info["macro_f1"] = best_entry["macro_f1"]
                    if "clean_sky_accuracy" not in info and "clean_sky_accuracy" in best_entry:
                        info["clean_sky_accuracy"] = best_entry["clean_sky_accuracy"]
                break
            except Exception:
                pass

    return info


def extract_yolo_checkpoint_info(pt_path: Path) -> Dict[str, Any]:
    """Extracts metadata and evaluation metrics from a YOLO best.pt checkpoint."""
    if not pt_path.exists():
        return {}

    info: Dict[str, Any] = {
        "file": str(pt_path),
        "size_mb": round(pt_path.stat().st_size / (1024 * 1024), 2),
    }

    try:
        data = torch.load(pt_path, map_location="cpu", weights_only=False)
        if isinstance(data, dict):
            info["epoch"] = data.get("epoch")
            info["version"] = data.get("version")
            info["date"] = data.get("date")

            train_metrics = data.get("train_metrics", {})
            if train_metrics:
                info["metrics"] = train_metrics
                info["box_map50"] = train_metrics.get("metrics/mAP50(B)")
                info["box_map50_95"] = train_metrics.get("metrics/mAP50-95(B)")
                info["seg_map50"] = train_metrics.get("metrics/mAP50(M)")
                info["seg_map50_95"] = train_metrics.get("metrics/mAP50-95(M)")
                info["box_precision"] = train_metrics.get("metrics/precision(B)")
                info["box_recall"] = train_metrics.get("metrics/recall(B)")
                info["seg_precision"] = train_metrics.get("metrics/precision(M)")
                info["seg_recall"] = train_metrics.get("metrics/recall(M)")
                info["fitness"] = train_metrics.get("fitness")
    except Exception as e:
        info["load_error"] = str(e)

    # Check for results.csv
    csv_candidates = [
        pt_path.parent / "yolo_results.csv",
        pt_path.parent.parent / "results.csv",
        pt_path.parent / "results.csv",
    ]
    for csv_path in csv_candidates:
        if csv_path.exists():
            y_hist = parse_yolo_results_csv(csv_path)
            if y_hist:
                info["training_history"] = y_hist
                info["total_epochs_run"] = len(y_hist)
                best_entry = max(y_hist, key=lambda x: x.get("fitness", x.get("metrics/mAP50(B)", 0.0)))
                info["best_epoch"] = best_entry.get("epoch", -1)
                break

    return info


def compute_dataset_stats(dataset_dir: Path) -> Dict[str, Any]:
    """Calculates dataset sizes, split ratios, and class frequencies from manifests."""
    stats = {
        "dataset_dir": str(dataset_dir),
        "total_tiles": 0,
        "train_tiles": 0,
        "val_tiles": 0,
        "class_counts": {c: 0 for c in CLASSES},
        "clean_tiles": 0,
        "defect_tiles": 0,
    }

    if not dataset_dir.exists():
        return stats

    for split in ["train", "val"]:
        m_file = dataset_dir / f"{split}_manifest.json"
        if m_file.exists():
            try:
                with open(m_file, "r", encoding="utf-8") as fp:
                    tiles = json.load(fp)
                if split == "train":
                    stats["train_tiles"] = len(tiles)
                else:
                    stats["val_tiles"] = len(tiles)
                stats["total_tiles"] += len(tiles)

                for t in tiles:
                    if t.get("is_clean", False):
                        stats["clean_tiles"] += 1
                    else:
                        stats["defect_tiles"] += 1
                    for c_name in t.get("classes", []):
                        if c_name in stats["class_counts"]:
                            stats["class_counts"][c_name] += 1
            except Exception as e:
                stats[f"{split}_error"] = str(e)

    return stats


def get_all_iterations() -> List[Dict[str, Any]]:
    """Loads all iteration manifests sorted by creation date."""
    if not ITERATIONS_DIR.exists():
        return []

    iterations = []
    for item in ITERATIONS_DIR.iterdir():
        if item.is_dir():
            manifest_file = item / "iteration.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    data["_dir"] = str(item)
                    iterations.append(data)
                except Exception as e:
                    print(f"Warning: Failed to load {manifest_file}: {e}")

    iterations.sort(key=lambda x: x.get("created_at", x.get("name", "")))
    return iterations


# =====================================================================
# CLI Actions
# =====================================================================

def cmd_create(args):
    """Creates a new model iteration with picked checkpoints and dataset metadata."""
    iter_name = args.name.strip()
    iter_dir = ITERATIONS_DIR / iter_name
    models_dir = iter_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    print_banner(f"Creating Model Iteration: {iter_name}")

    models_manifest: Dict[str, Any] = {}

    # 1. Resolve YOLO model
    yolo_src = None
    if args.yolo:
        yolo_src = Path(args.yolo).resolve()
    elif args.from_session:
        s_dir = SESSIONS_DIR / args.from_session
        cand = s_dir / "yolo_astro" / "weights" / "best.pt"
        if not cand.exists():
            cand = s_dir / "yolo11_astro" / "weights" / "best.pt"
        if cand.exists():
            yolo_src = cand
    else:
        # Default fallback to legacy mirrors
        cand = RUNS_DIR / "segment" / "yolo_astro" / "weights" / "best.pt"
        if not cand.exists():
            cand = RUNS_DIR / "segment" / "runs" / "segment" / "yolo11_astro" / "weights" / "best.pt"
        if cand.exists():
            yolo_src = cand

    if yolo_src and yolo_src.exists():
        dest = models_dir / "yolo_best.pt"
        shutil.copy2(yolo_src, dest)

        # Copy YOLO results.csv and args.yaml if present
        yolo_run_dir = yolo_src.parent.parent if yolo_src.parent.name == "weights" else yolo_src.parent
        yolo_csv = yolo_run_dir / "results.csv"
        if yolo_csv.exists():
            shutil.copy2(yolo_csv, models_dir / "yolo_results.csv")
        yolo_args = yolo_run_dir / "args.yaml"
        if yolo_args.exists():
            shutil.copy2(yolo_args, models_dir / "yolo_args.yaml")

        info = extract_yolo_checkpoint_info(dest)
        info["source_checkpoint"] = str(yolo_src)
        models_manifest["yolo"] = info
        print(f" [+] Added YOLO checkpoint: {yolo_src} -> {dest}")
        if info.get("seg_map50") is not None:
            print(f"     Mask mAP50: {info.get('seg_map50'):.4f} | Box mAP50: {info.get('box_map50'):.4f}")
    else:
        print(" [-] No YOLO checkpoint found to include.")

    # 2. Resolve CNN models
    cnn_names = args.cnn_models if args.cnn_models else ["astronet", "resnet18", "mobilenet_v3", "efficientnet_b0"]
    for m in cnn_names:
        cnn_src = None
        if args.from_session:
            cand = SESSIONS_DIR / args.from_session / f"{m}_f32" / "best_model.pt"
            if cand.exists():
                cnn_src = cand
        if not cnn_src or not cnn_src.exists():
            cand = CHECKPOINTS_DIR / f"{m}_f32" / "best_model.pt"
            if cand.exists():
                cnn_src = cand

        if cnn_src and cnn_src.exists():
            dest = models_dir / f"{m}_best.pt"
            shutil.copy2(cnn_src, dest)

            # Copy training_history.json if present
            hist_src = cnn_src.parent / "training_history.json"
            if hist_src.exists():
                shutil.copy2(hist_src, models_dir / f"{m}_training_history.json")

            # Also copy ONNX if present
            onnx_src = cnn_src.parent / "best_model.onnx"
            if not onnx_src.exists():
                onnx_src = cnn_src.parent / f"{m}.onnx"
            if onnx_src.exists():
                shutil.copy2(onnx_src, models_dir / f"{m}.onnx")

            info = extract_cnn_checkpoint_info(dest)
            info["source_checkpoint"] = str(cnn_src)
            models_manifest[m] = info
            f1 = info.get("macro_f1")
            acc = info.get("clean_sky_accuracy")
            f1_str = f"{f1:.4f}" if f1 is not None else "N/A"
            acc_str = f"{acc:.4f}" if acc is not None else "N/A"
            print(f" [+] Added CNN {m}: {cnn_src} (Macro F1: {f1_str}, Clean Acc: {acc_str})")
        else:
            print(f" [-] No checkpoint found for CNN {m}")

    # 3. Collect dataset statistics
    ds_path = Path(args.dataset_dir).resolve() if args.dataset_dir else TRAINING_ROOT / "dataset"
    if not (ds_path / "train_manifest.json").exists():
        if (TRAINING_ROOT / "dataset_test" / "train_manifest.json").exists():
            ds_path = TRAINING_ROOT / "dataset_test"

    dataset_stats = compute_dataset_stats(ds_path)

    # 4. Save iteration manifest
    manifest = {
        "name": iter_name,
        "description": args.description or "Model evolutionary iteration",
        "parent_iteration": args.parent or None,
        "created_at": datetime.now().isoformat(),
        "dataset": dataset_stats,
        "models": models_manifest,
    }

    manifest_path = iter_dir / "iteration.json"
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    # Generate summary markdown inside iteration directory
    generate_iteration_markdown(iter_dir, manifest)

    print(f"\n[OK] Iteration '{iter_name}' successfully packaged in: {iter_dir}")
    print(f"     Manifest: {manifest_path}")
    print(f"     Summary Report: {iter_dir / 'summary.md'}\n")


def cmd_add_model(args):
    """Picks a specific model checkpoint from a session or custom path into an existing iteration."""
    iter_name = args.iteration.strip()
    iter_dir = ITERATIONS_DIR / iter_name
    manifest_path = iter_dir / "iteration.json"
    if not manifest_path.exists():
        print(f"Error: Iteration '{iter_name}' does not exist.")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    src_path = Path(args.checkpoint).resolve()
    if not src_path.exists():
        print(f"Error: Checkpoint file '{src_path}' not found.")
        sys.exit(1)

    models_dir = iter_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    m_name = args.model_name.lower().strip()

    if "yolo" in m_name:
        dest = models_dir / "yolo_best.pt"
        shutil.copy2(src_path, dest)
        # Copy YOLO results.csv and args.yaml if present
        yolo_run_dir = src_path.parent.parent if src_path.parent.name == "weights" else src_path.parent
        yolo_csv = yolo_run_dir / "results.csv"
        if yolo_csv.exists():
            shutil.copy2(yolo_csv, models_dir / "yolo_results.csv")
        yolo_args = yolo_run_dir / "args.yaml"
        if yolo_args.exists():
            shutil.copy2(yolo_args, models_dir / "yolo_args.yaml")

        info = extract_yolo_checkpoint_info(dest)
        info["source_checkpoint"] = str(src_path)
        manifest["models"]["yolo"] = info
        print(f"[+] Replaced/Added YOLO checkpoint with {src_path}")
    else:
        dest = models_dir / f"{m_name}_best.pt"
        shutil.copy2(src_path, dest)
        # Copy training_history.json if present
        hist_src = src_path.parent / "training_history.json"
        if hist_src.exists():
            shutil.copy2(hist_src, models_dir / f"{m_name}_training_history.json")

        info = extract_cnn_checkpoint_info(dest)
        info["source_checkpoint"] = str(src_path)
        manifest["models"][m_name] = info
        print(f"[+] Replaced/Added CNN {m_name} checkpoint with {src_path}")

    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    generate_iteration_markdown(iter_dir, manifest)
    print(f"[OK] Iteration '{iter_name}' updated successfully.\n")


def cmd_list(args):
    """Lists all registered iterations and their summary metrics."""
    iterations = get_all_iterations()
    print_banner("Registered Model Iterations")

    if not iterations:
        print("No iterations found in iterations/.")
        print("Create your first iteration using:\n  python iter_manager.py create iter_1 --description 'Initial baseline'\n")
        return

    header = f"{'Iteration':<14} {'Created':<20} {'YOLO Seg mAP50':<16} {'ResNet18 F1':<14} {'Description'}"
    print(header)
    print("-" * 100)
    for it in iterations:
        name = it.get("name", "")
        created = it.get("created_at", "")[:19].replace("T", " ")
        desc = it.get("description", "")
        if len(desc) > 35:
            desc = desc[:32] + "..."

        models = it.get("models", {})
        yolo_info = models.get("yolo", {})
        y_seg = yolo_info.get("seg_map50")
        y_str = f"{y_seg:.4f}" if y_seg is not None else "-"

        rn18_info = models.get("resnet18", {})
        r_f1 = rn18_info.get("macro_f1")
        r_str = f"{r_f1:.4f}" if r_f1 is not None else "-"

        print(f"{name:<14} {created:<20} {y_str:<16} {r_str:<14} {desc}")
    print("-" * 100 + "\n")


def cmd_activate(args):
    """
    Activates an iteration by copying its checkpoints into the unified
    standard locations (checkpoints/<model>_f32/ and runs/segment/yolo_astro/weights/)
    so master_train.py can continue fine-tuning them with --auto-resume.
    """
    iter_name = args.iteration.strip()
    iter_dir = ITERATIONS_DIR / iter_name
    manifest_path = iter_dir / "iteration.json"
    if not manifest_path.exists():
        print(f"Error: Iteration '{iter_name}' does not exist.")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    print_banner(f"Activating Iteration '{iter_name}' for Fine-Tuning")

    models_dir = iter_dir / "models"
    activated_count = 0

    # 1. Activate YOLO
    yolo_file = models_dir / "yolo_best.pt"
    if yolo_file.exists():
        targets = [
            RUNS_DIR / "segment" / "yolo_astro" / "weights" / "best.pt",
            RUNS_DIR / "segment" / "yolo11_astro" / "weights" / "best.pt",
        ]
        for t in targets:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(yolo_file, t)
        print(f" [OK] Activated YOLO -> runs/segment/yolo_astro/weights/best.pt")
        activated_count += 1

    # 2. Activate CNNs
    for pt in models_dir.glob("*_best.pt"):
        if pt.name == "yolo_best.pt":
            continue
        m_name = pt.name.replace("_best.pt", "")
        dest_dir = CHECKPOINTS_DIR / f"{m_name}_f32"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pt, dest_dir / "best_model.pt")
        print(f" [OK] Activated CNN {m_name} -> checkpoints/{m_name}_f32/best_model.pt")
        activated_count += 1

    print(f"\nSuccessfully activated {activated_count} models from iteration '{iter_name}'.")
    print("\nYou can now run master_train.py to fine-tune from this exact iteration:")
    print("  ./env/bin/python3 master_train.py --auto-resume --yolo-epochs 15 --cnn-epochs 10 --lr 0.0003\n")


def cmd_compare(args):
    """Compares two or more iterations and outputs a detailed metric comparison table."""
    iter_names = args.iterations
    if len(iter_names) < 2:
        print("Please specify at least two iterations to compare (e.g. iter_manager.py compare iter_1 iter_2).")
        sys.exit(1)

    loaded = []
    for name in iter_names:
        p = ITERATIONS_DIR / name / "iteration.json"
        if not p.exists():
            print(f"Error: Iteration '{name}' not found.")
            sys.exit(1)
        with open(p, "r", encoding="utf-8") as fp:
            loaded.append(json.load(fp))

    print_banner(f"Comparison: {' vs '.join(iter_names)}")

    # 1. Dataset comparison
    print(f"{'Metric / Feature':<30} " + " ".join([f"{it['name']:<18}" for it in loaded]))
    print("-" * (30 + 19 * len(loaded)))
    print(f"{'Total Tiles':<30} " + " ".join([f"{it['dataset'].get('total_tiles', 0):<18}" for it in loaded]))
    print(f"{'Defect Tiles':<30} " + " ".join([f"{it['dataset'].get('defect_tiles', 0):<18}" for it in loaded]))
    print(f"{'Clean Sky Tiles':<30} " + " ".join([f"{it['dataset'].get('clean_tiles', 0):<18}" for it in loaded]))

    # 2. YOLO Metrics comparison
    print("\n--- Instance Segmentation (YOLO) ---")
    y_keys = [
        ("seg_map50", "Mask mAP50"),
        ("seg_map50_95", "Mask mAP50-95"),
        ("box_map50", "Box mAP50"),
        ("seg_recall", "Mask Recall"),
        ("seg_precision", "Mask Precision"),
    ]
    for key, label in y_keys:
        row = [f"{label:<30}"]
        for it in loaded:
            val = it.get("models", {}).get("yolo", {}).get(key)
            val_str = f"{val:.4f}" if val is not None else "-"
            row.append(f"{val_str:<18}")
        print(" ".join(row))

    # 3. CNN Classification comparison
    print("\n--- Multi-Label Classification Backbones ---")
    cnn_keys = ["macro_f1", "clean_sky_accuracy"]
    all_cnns = sorted(list({m for it in loaded for m in it.get("models", {}).keys() if m != "yolo"}))

    for m in all_cnns:
        print(f"\n Model: {m}")
        for key in cnn_keys:
            label = "Macro F1" if key == "macro_f1" else "Clean Accuracy"
            row = [f"  {label:<28}"]
            for it in loaded:
                val = it.get("models", {}).get(m, {}).get(key)
                val_str = f"{val:.4f}" if val is not None else "-"
                row.append(f"{val_str:<18}")
            print(" ".join(row))

        # Per-class F1 for this CNN
        print(f"  {'Per-Class F1':<28}")
        for c in CLASSES:
            row = [f"    {c:<26}"]
            for it in loaded:
                c_f1 = it.get("models", {}).get(m, {}).get("metrics", {}).get(f"{c}_f1")
                val_str = f"{c_f1:.4f}" if c_f1 is not None else "-"
                row.append(f"{val_str:<18}")
            print(" ".join(row))

    print("\n" + "=" * 70 + "\n")


def cmd_export_thesis(args):
    """Exports clean LaTeX and Markdown tables comparing all iterations for the diploma thesis."""
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    iterations = get_all_iterations()
    if not iterations:
        print("No iterations to export.")
        return

    md_path = out_dir / "model_evolution_thesis.md"
    tex_path = out_dir / "model_evolution_thesis.tex"

    # 1. Generate Markdown
    with open(md_path, "w", encoding="utf-8") as fp:
        fp.write("# Evolutionary Model Iterations Benchmark (Diploma Thesis Chapter)\n\n")
        fp.write("This document summarizes the chronological iterations of defect detection models, ")
        fp.write("showing changes in dataset generation, architecture improvements, and performance metrics.\n\n")

        fp.write("## Overview of Iterations\n\n")
        fp.write("| Iteration | Date | Description | Total Tiles | YOLO Mask mAP50 | ResNet18 Macro F1 |\n")
        fp.write("| :--- | :--- | :--- | :---: | :---: | :---: |\n")
        for it in iterations:
            name = it.get("name")
            date = it.get("created_at", "")[:10]
            desc = it.get("description", "")
            tiles = it.get("dataset", {}).get("total_tiles", "-")
            y_map = it.get("models", {}).get("yolo", {}).get("seg_map50")
            y_str = f"{y_map:.4f}" if y_map is not None else "-"
            r_f1 = it.get("models", {}).get("resnet18", {}).get("macro_f1")
            r_str = f"{r_f1:.4f}" if r_f1 is not None else "-"
            fp.write(f"| `{name}` | {date} | {desc} | {tiles} | **{y_str}** | **{r_str}** |\n")

        fp.write("\n## Per-Class F1 Score Evolution (ResNet18)\n\n")
        fp.write("| Defect Class | " + " | ".join([f"`{it['name']}`" for it in iterations]) + " |\n")
        fp.write("| :--- | " + " | ".join([":---:" for _ in iterations]) + " |\n")
        for c in CLASSES:
            vals = []
            for it in iterations:
                f1 = it.get("models", {}).get("resnet18", {}).get("metrics", {}).get(f"{c}_f1")
                vals.append(f"{f1:.4f}" if f1 is not None else "-")
            fp.write(f"| **{c}** | " + " | ".join(vals) + " |\n")

    # 2. Generate LaTeX Table
    with open(tex_path, "w", encoding="utf-8") as fp:
        fp.write("% Auto-generated model evolution table for LaTeX thesis\n")
        fp.write("\\begin{table}[htbp]\n\\centering\n\\small\n")
        fp.write("\\caption{Evolutionary performance progression across training iterations.}\n")
        fp.write("\\label{tab:model_evolution}\n")
        fp.write("\\begin{tabular}{l l c c c c}\n\\hline\n")
        fp.write("\\textbf{Iteration} & \\textbf{Description} & \\textbf{Tiles} & \\textbf{YOLO mAP50} & \\textbf{ResNet18 F1} & \\textbf{AstroNet F1} \\\\ \\hline\n")
        for it in iterations:
            name = it.get("name")
            desc = it.get("description", "")[:35]
            tiles = it.get("dataset", {}).get("total_tiles", "-")
            y_map = it.get("models", {}).get("yolo", {}).get("seg_map50")
            y_str = f"{y_map:.3f}" if y_map is not None else "--"
            r_f1 = it.get("models", {}).get("resnet18", {}).get("macro_f1")
            r_str = f"{r_f1:.3f}" if r_f1 is not None else "--"
            a_f1 = it.get("models", {}).get("astronet", {}).get("macro_f1")
            a_str = f"{a_f1:.3f}" if a_f1 is not None else "--"
            fp.write(f"{name} & {desc} & {tiles} & {y_str} & {r_str} & {a_str} \\\\\n")
        fp.write("\\hline\n\\end{tabular}\n\\end{table}\n")

    print_banner("Thesis Export Complete")
    print(f" [OK] Markdown report: {md_path}")
    print(f" [OK] LaTeX table:     {tex_path}\n")


def generate_iteration_markdown(iter_dir: Path, manifest: Dict[str, Any]):
    """Generates a human-readable summary.md inside the iteration directory."""
    md_file = iter_dir / "summary.md"
    with open(md_file, "w", encoding="utf-8") as fp:
        fp.write(f"# Iteration Summary: {manifest['name']}\n\n")
        fp.write(f"- **Created:** {manifest.get('created_at')}\n")
        fp.write(f"- **Description:** {manifest.get('description')}\n")
        if manifest.get("parent_iteration"):
            fp.write(f"- **Parent Iteration:** `{manifest.get('parent_iteration')}`\n")

        ds = manifest.get("dataset", {})
        fp.write("\n## Dataset Information\n\n")
        fp.write(f"- **Total Tiles:** {ds.get('total_tiles', 0)} (Train: {ds.get('train_tiles', 0)}, Val: {ds.get('val_tiles', 0)})\n")
        fp.write(f"- **Clean Tiles:** {ds.get('clean_tiles', 0)} | **Defect Tiles:** {ds.get('defect_tiles', 0)}\n\n")
        fp.write("### Defect Class Distribution\n\n")
        fp.write("| Class Name | Count |\n| :--- | :---: |\n")
        for c, count in ds.get("class_counts", {}).items():
            fp.write(f"| `{c}` | {count} |\n")

        fp.write("\n## Packaged Models\n\n")
        models = manifest.get("models", {})
        if "yolo" in models:
            y = models["yolo"]
            fp.write("### YOLO Instance Segmentation\n\n")
            fp.write(f"- **Source Checkpoint:** `{y.get('source_checkpoint')}`\n")
            fp.write(f"- **Mask mAP50:** `{y.get('seg_map50', 'N/A')}` | **Box mAP50:** `{y.get('box_map50', 'N/A')}`\n")
            fp.write(f"- **Mask Recall:** `{y.get('seg_recall', 'N/A')}` | **Mask Precision:** `{y.get('seg_precision', 'N/A')}`\n\n")

            y_hist = y.get("training_history", [])
            if y_hist:
                best_ep = y.get("best_epoch", -1)
                tot_ep = y.get("total_epochs_run", len(y_hist))
                fp.write(f"#### Training Progression (YOLO — Best at Epoch {best_ep} / {tot_ep} run)\n\n")
                fp.write("| Epoch | Train Box Loss | Train Seg Loss | Val Box Loss | Val Seg Loss | Box mAP50 | Mask mAP50 |\n")
                fp.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
                for h in y_hist:
                    ep = h.get("epoch", 0)
                    tr_box = f"{h.get('train/box_loss', 0.0):.4f}"
                    tr_seg = f"{h.get('train/seg_loss', 0.0):.4f}"
                    val_box = f"{h.get('val/box_loss', 0.0):.4f}"
                    val_seg = f"{h.get('val/seg_loss', 0.0):.4f}"
                    b50 = f"{h.get('metrics/mAP50(B)', 0.0):.4f}"
                    m50 = f"{h.get('metrics/mAP50(M)', 0.0):.4f}"
                    if ep == best_ep:
                        fp.write(f"| **{ep}** | **{tr_box}** | **{tr_seg}** | **{val_box}** | **{val_seg}** | **{b50}** | **{m50}** |\n")
                    else:
                        fp.write(f"| {ep} | {tr_box} | {tr_seg} | {val_box} | {val_seg} | {b50} | {m50} |\n")
                fp.write("\n")

        for m_name, info in models.items():
            if m_name == "yolo":
                continue
            fp.write(f"### CNN Model: `{m_name}`\n\n")
            fp.write(f"- **Macro F1:** `{info.get('macro_f1', 'N/A')}` | **Clean Sky Accuracy:** `{info.get('clean_sky_accuracy', 'N/A')}`\n")
            fp.write(f"- **Source Checkpoint:** `{info.get('source_checkpoint')}`\n")
            raw_m = info.get("metrics", {})
            if raw_m:
                fp.write("\n| Class | Precision | Recall | F1 Score |\n| :--- | :---: | :---: | :---: |\n")
                for c in CLASSES:
                    p = raw_m.get(f"{c}_precision", "-")
                    r = raw_m.get(f"{c}_recall", "-")
                    f = raw_m.get(f"{c}_f1", "-")
                    fp.write(f"| `{c}` | {p} | {r} | **{f}** |\n")
                fp.write("\n")

            c_hist = info.get("training_history", [])
            if c_hist:
                best_ep = info.get("best_epoch", info.get("epoch", 0))
                tot_ep = info.get("total_epochs_run", len(c_hist))
                fp.write(f"#### Training Progression (`{m_name}` — Best at Epoch {best_ep} / {tot_ep} run)\n\n")
                fp.write("| Epoch | Train Loss | Val Loss | Macro F1 | Clean Sky Acc | Exact Match |\n")
                fp.write("| :---: | :---: | :---: | :---: | :---: | :---: |\n")
                for h in c_hist:
                    ep = h.get("epoch", 0)
                    tr_loss = f"{h.get('train_loss', 0.0):.4f}"
                    val_loss = f"{h.get('val_loss', 0.0):.4f}"
                    mf1 = f"{h.get('macro_f1', 0.0):.4f}"
                    cacc = f"{h.get('clean_sky_accuracy', 0.0):.4f}"
                    ematch = f"{h.get('exact_match_ratio', 0.0):.4f}"
                    if ep == best_ep:
                        fp.write(f"| **{ep}** | **{tr_loss}** | **{val_loss}** | **{mf1}** | **{cacc}** | **{ematch}** |\n")
                    else:
                        fp.write(f"| {ep} | {tr_loss} | {val_loss} | {mf1} | {cacc} | {ematch} |\n")
                fp.write("\n")


def cmd_backfill(args):
    """Retroactively copies training history and results.csv into an existing iteration and regenerates its reports."""
    iter_name = args.iteration.strip()
    iter_dir = ITERATIONS_DIR / iter_name
    manifest_path = iter_dir / "iteration.json"
    if not manifest_path.exists():
        print(f"Error: Iteration '{iter_name}' does not exist at {manifest_path}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    models_dir = iter_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    session_dir = None
    if args.from_session:
        session_dir = SESSIONS_DIR / args.from_session
    else:
        # Infer session directory from source_checkpoint
        for m_name, m_info in manifest.get("models", {}).items():
            src = m_info.get("source_checkpoint")
            if src and "sessions" in src:
                p = Path(src)
                parts = p.parts
                if "sessions" in parts:
                    idx = parts.index("sessions")
                    if idx + 1 < len(parts):
                        session_dir = Path(*parts[:idx + 2])
                        break

    if session_dir and session_dir.exists():
        print(f" [Backfill] Sourcing history from session: {session_dir}")
    else:
        print(" [Backfill] Session directory not specified/found. Looking for sibling history files...")

    # 1. Backfill YOLO
    y_info = manifest.get("models", {}).get("yolo", {})
    if y_info:
        yolo_csv = None
        yolo_args = None
        if session_dir:
            for y_folder in ["yolo_astro", "yolo11_astro"]:
                cand_csv = session_dir / y_folder / "results.csv"
                if cand_csv.exists():
                    yolo_csv = cand_csv
                    yolo_args = session_dir / y_folder / "args.yaml"
                    break
        if not yolo_csv:
            src_cp = y_info.get("source_checkpoint")
            if src_cp:
                cand_csv = Path(src_cp).parent.parent / "results.csv"
                if cand_csv.exists():
                    yolo_csv = cand_csv
                    yolo_args = Path(src_cp).parent.parent / "args.yaml"

        dest_csv = models_dir / "yolo_results.csv"
        if yolo_csv and yolo_csv.exists():
            shutil.copy2(yolo_csv, dest_csv)
            print(f" [+] Copied YOLO results.csv: {yolo_csv} -> {dest_csv}")
        if yolo_args and yolo_args.exists():
            shutil.copy2(yolo_args, models_dir / "yolo_args.yaml")

        if dest_csv.exists():
            y_hist = parse_yolo_results_csv(dest_csv)
            if y_hist:
                y_info["training_history"] = y_hist
                y_info["total_epochs_run"] = len(y_hist)
                best_entry = max(y_hist, key=lambda x: x.get("fitness", x.get("metrics/mAP50(B)", 0.0)))
                y_info["best_epoch"] = best_entry.get("epoch", -1)
                print(f" [+] Embedded {len(y_hist)} YOLO epochs into manifest (Best: Epoch {y_info['best_epoch']})")

    # 2. Backfill CNNs
    cnn_names = [m for m in manifest.get("models", {}).keys() if m != "yolo"]
    for m in cnn_names:
        m_info = manifest["models"][m]
        hist_src = None
        if session_dir:
            cand_hist = session_dir / f"{m}_f32" / "training_history.json"
            if cand_hist.exists():
                hist_src = cand_hist
        if not hist_src:
            src_cp = m_info.get("source_checkpoint")
            if src_cp:
                cand_hist = Path(src_cp).parent / "training_history.json"
                if cand_hist.exists():
                    hist_src = cand_hist

        dest_hist = models_dir / f"{m}_training_history.json"
        if hist_src and hist_src.exists():
            shutil.copy2(hist_src, dest_hist)
            print(f" [+] Copied {m} history: {hist_src} -> {dest_hist}")

        if dest_hist.exists():
            with open(dest_hist, "r", encoding="utf-8") as fp:
                c_hist = json.load(fp)
            if c_hist and isinstance(c_hist, list):
                m_info["training_history"] = c_hist
                m_info["total_epochs_run"] = len(c_hist)
                if m_info.get("epoch") is not None:
                    m_info["best_epoch"] = m_info["epoch"]
                else:
                    best_entry = max(c_hist, key=lambda x: x.get("macro_f1", 0.0))
                    m_info["best_epoch"] = best_entry.get("epoch", 0)
                print(f" [+] Embedded {len(c_hist)} {m} epochs into manifest (Best: Epoch {m_info['best_epoch']})")

    # Save updated manifest and generate summary.md
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    generate_iteration_markdown(iter_dir, manifest)
    print(f"\n[OK] Iteration '{iter_name}' successfully backfilled with full training history.")
    print(f"     Manifest: {manifest_path}")
    print(f"     Summary Report: {iter_dir / 'summary.md'}\n")


# =====================================================================
# Main Parser
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="AstroGrader Iteration & Thesis Experiment Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. create
    p_create = subparsers.add_parser("create", help="Create and package a new iteration")
    p_create.add_argument("name", type=str, help="Name of iteration (e.g. iter_1, iter_2)")
    p_create.add_argument("--description", "-d", type=str, default="", help="Description of changes and hypothesis")
    p_create.add_argument("--parent", type=str, default=None, help="Parent iteration name")
    p_create.add_argument("--yolo", type=str, default=None, help="Explicit path to YOLO best.pt")
    p_create.add_argument("--cnn-models", nargs="+", default=None, help="CNN model names to package")
    p_create.add_argument("--from-session", type=str, default=None, help="Session folder to source checkpoints from")
    p_create.add_argument("--dataset-dir", type=str, default=None, help="Dataset directory to extract stats from")
    p_create.set_defaults(func=cmd_create)

    # 2. add-model (pick & swap)
    p_add = subparsers.add_parser("add-model", help="Pick and insert a specific checkpoint into an iteration")
    p_add.add_argument("iteration", type=str, help="Target iteration name")
    p_add.add_argument("--model-name", "-m", type=str, required=True, help="Model name (e.g. yolo, resnet18, astronet)")
    p_add.add_argument("--checkpoint", "-c", type=str, required=True, help="Path to checkpoint .pt")
    p_add.set_defaults(func=cmd_add_model)

    # 3. list
    p_list = subparsers.add_parser("list", help="List all iterations and high-level metrics")
    p_list.set_defaults(func=cmd_list)

    # 4. activate
    p_activate = subparsers.add_parser("activate", help="Activate an iteration's models into standard paths for fine-tuning")
    p_activate.add_argument("iteration", type=str, help="Iteration name to activate")
    p_activate.set_defaults(func=cmd_activate)

    # 5. compare
    p_comp = subparsers.add_parser("compare", help="Compare metrics between iterations")
    p_comp.add_argument("iterations", nargs="+", help="Names of iterations to compare")
    p_comp.set_defaults(func=cmd_compare)

    # 6. export-thesis
    p_exp = subparsers.add_parser("export-thesis", help="Export Markdown and LaTeX comparison tables for diploma thesis")
    p_exp.add_argument("--out-dir", type=str, default="thesis_reports", help="Output directory for reports")
    p_exp.set_defaults(func=cmd_export_thesis)

    # 7. backfill
    p_backfill = subparsers.add_parser("backfill", help="Retroactively copy training history and results.csv into an existing iteration")
    p_backfill.add_argument("iteration", type=str, help="Name of iteration to backfill (e.g. v1_ver2)")
    p_backfill.add_argument("--from-session", type=str, default=None, help="Session folder to source history files from")
    p_backfill.set_defaults(func=cmd_backfill)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
