#!/usr/bin/env python3
"""
AstroGrader: Master End-to-End Astronomical Training Pipeline.
Orchestrates:
1. Parallel slicing of full-resolution FITS into 512x512 tiles for CNNs and YOLO-seg.
2. Training Ultralytics YOLO11-seg with Early Stopping.
3. Training CNN Backbones (AstroNet, ResNet18, MobileNetV3, EfficientNetB0) with Early Stopping.
4. Exporting models to ONNX.
5. Session-based tracking, interrupted run resumption, and per-model continuation.
6. Comprehensive benchmark comparison summary report.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

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


def get_all_sessions(sessions_dir: Path) -> List[Dict]:
    """Scans sessions_dir for valid session directories containing session.json."""
    if not sessions_dir.exists():
        return []

    sessions = []
    for item in sessions_dir.iterdir():
        if item.is_dir():
            s_json = item / "session.json"
            if s_json.exists():
                try:
                    with open(s_json, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    data["_dir"] = str(item)
                    sessions.append(data)
                except Exception as e:
                    print(f"Warning: Failed to load {s_json}: {e}")

    sessions.sort(key=lambda s: s.get("created_at", s.get("session_id", "")), reverse=True)
    return sessions


def resolve_session(session_arg: str, sessions_dir: Path) -> Tuple[str, Path]:
    """
    Resolves session identifier ('latest', full ID, or prefix match) to (session_id, session_path).
    Raises ValueError if not found.
    """
    all_sessions = get_all_sessions(sessions_dir)
    if not all_sessions:
        raise ValueError(f"No sessions found in {sessions_dir}. Cannot resolve '{session_arg}'.")

    if session_arg.lower() == "latest":
        latest = all_sessions[0]
        return latest["session_id"], Path(latest["_dir"])

    # Exact directory match
    exact = sessions_dir / session_arg
    if exact.exists() and (exact / "session.json").exists():
        return session_arg, exact

    # Match by session_id in manifest or prefix match
    matches = []
    for s in all_sessions:
        sid = s.get("session_id", "")
        if sid == session_arg:
            return sid, Path(s["_dir"])
        if sid.startswith(session_arg):
            matches.append((sid, Path(s["_dir"])))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        match_ids = [m[0] for m in matches]
        raise ValueError(f"Ambiguous session identifier '{session_arg}'. Multiple matches found: {match_ids}")

    raise ValueError(f"Session '{session_arg}' not found in {sessions_dir}. Use --list-sessions to see available sessions.")


def list_sessions_cli(sessions_dir: Path):
    """Prints a formatted terminal table showing all training sessions."""
    sessions = get_all_sessions(sessions_dir)
    if not sessions:
        print(f"\nNo training sessions found in {sessions_dir.resolve()}.\n")
        return

    print_banner("AstroGrader: Recorded Training Sessions")
    header = f"{'Session ID':<22} {'Created At':<20} {'Parent':<16} {'Status':<12} {'Models Summary'}"
    print(header)
    print("-" * 110)

    for s in sessions:
        sid = s.get("session_id", "unknown")
        created = s.get("created_at", "unknown")[:19]
        parent = s.get("parent_session") or "-"
        status = s.get("status", "unknown").upper()

        models_data = s.get("models", {})
        summary_parts = []
        for m_name, m_info in models_data.items():
            m_stat = m_info.get("status", "pending")
            short_name = m_name.replace("_astro", "").replace("_f32", "")
            if m_stat == "completed":
                if "macro_f1" in m_info:
                    summary_parts.append(f"{short_name}:DONE(F1={m_info['macro_f1']:.2f})")
                elif "metrics" in m_info and "box_map50" in m_info["metrics"]:
                    summary_parts.append(f"{short_name}:DONE(mAP={m_info['metrics']['box_map50']:.2f})")
                else:
                    summary_parts.append(f"{short_name}:DONE")
            elif m_stat == "in_progress":
                ep = m_info.get("epochs_completed", 0)
                tot = m_info.get("target_epochs", "?")
                summary_parts.append(f"{short_name}:PARTIAL({ep}/{tot})")
            elif m_stat == "failed":
                summary_parts.append(f"{short_name}:FAILED")
            else:
                summary_parts.append(f"{short_name}:PENDING")

        models_str = ", ".join(summary_parts) if summary_parts else "No models recorded"
        print(f"{sid:<22} {created:<20} {parent:<16} {status:<12} {models_str}")

    print("-" * 110 + "\n")


def save_session_manifest(session_dir: Path, manifest: Dict):
    """Safely writes session.json manifest."""
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now().isoformat()
    manifest_path = session_dir / "session.json"
    temp_path = session_dir / "session.json.tmp"
    with open(temp_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)
    temp_path.replace(manifest_path)


def sync_latest_mirrors(session_dir: Path, model_name: str, is_yolo: bool = False):
    """
    Copies newly trained checkpoints to the legacy root directories:
    - CNN: checkpoints/<model_name>_f32/
    - YOLO: runs/segment/yolo11_astro/weights/
    Maintains 100% backwards compatibility for annotator and test scripts.
    """
    try:
        if is_yolo:
            src_weights = session_dir / "yolo11_astro" / "weights"
            dst_weights = Path("runs/segment/yolo11_astro/weights")
            dst_weights.mkdir(parents=True, exist_ok=True)
            for fname in ["best.pt", "last.pt", "best.onnx"]:
                src_f = src_weights / fname
                if src_f.exists():
                    shutil.copy2(src_f, dst_weights / fname)
        else:
            src_dir = session_dir / f"{model_name}_f32"
            dst_dir = Path("checkpoints") / f"{model_name}_f32"
            dst_dir.mkdir(parents=True, exist_ok=True)
            for fname in ["best_model.pt", "last_model.pt", "best_model.onnx", "training_history.json"]:
                src_f = src_dir / fname
                if src_f.exists():
                    shutil.copy2(src_f, dst_dir / fname)
    except Exception as e:
        print(f"Warning: Failed to sync latest mirror for {model_name}: {e}")


def run_cnn_training(
    model_name: str,
    dataset_dir: Path,
    epochs: int,
    batch_size: int,
    patience: int,
    lr: float,
    device_arg: Optional[str],
    out_dir: Path,
    resume_checkpoint: Optional[str] = None,
    resume_state: bool = False,
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
    if resume_checkpoint:
        cmd.extend(["--resume", str(resume_checkpoint)])
    if resume_state:
        cmd.append("--resume-state")

    resume_type = "Exact State Resume" if resume_state else "Weights Fine-Tune"
    resume_msg = f" [{resume_type} from: {resume_checkpoint}]" if resume_checkpoint else ""
    print(f"\n>>> Running CNN Training: {model_name} (Epochs: {epochs}, Patience: {patience}){resume_msg}")
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
    epochs_trained = 0

    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as fp:
                hist = json.load(fp)
            if hist:
                best_entry = max(hist, key=lambda x: x.get("macro_f1", 0.0))
                best_f1 = best_entry.get("macro_f1", 0.0)
                clean_acc = best_entry.get("clean_sky_accuracy", 0.0)
                best_epoch = best_entry.get("epoch", 0)
                epochs_trained = len(hist)
        except Exception as e:
            print(f"Warning: Failed to parse history for {model_name}: {e}")

    return {
        "model": model_name,
        "success": (ret.returncode == 0),
        "elapsed_sec": elapsed,
        "best_epoch": best_epoch,
        "epochs_trained": epochs_trained,
        "macro_f1": best_f1,
        "clean_sky_acc": clean_acc,
        "checkpoint": str(out_dir / f"{model_name}_f32" / "best_model.pt"),
        "last_checkpoint": str(out_dir / f"{model_name}_f32" / "last_model.pt"),
    }


def parse_resume_model_overrides(overrides_list: Optional[List[str]], sessions_dir: Path) -> Dict[str, str]:
    """
    Parses --resume-model overrides, supporting formats:
    - model=session_id (e.g. resnet18=2026-10-15_12-00)
    - model=path/to/checkpoint.pt
    """
    if not overrides_list:
        return {}

    parsed = {}
    for item in overrides_list:
        if "=" not in item:
            print(f"Warning: Invalid format for --resume-model '{item}'. Expected <model>=<session_id_or_path>")
            continue
        m_name, target = item.split("=", 1)
        m_name = m_name.strip()
        target = target.strip()

        target_path = Path(target)
        if target_path.exists() and target_path.is_file():
            parsed[m_name] = str(target_path.resolve())
        else:
            try:
                sid, sdir = resolve_session(target, sessions_dir)
                if m_name in ("yolo", "yolo11", "yolo11_astro"):
                    c_path = sdir / "yolo11_astro" / "weights" / "best.pt"
                else:
                    c_path = sdir / f"{m_name}_f32" / "best_model.pt"
                if c_path.exists():
                    parsed[m_name] = str(c_path.resolve())
                else:
                    print(f"Warning: Checkpoint {c_path} not found in session '{sid}' for model '{m_name}'")
            except Exception as e:
                print(f"Warning: Could not resolve session for --resume-model '{item}': {e}")

    return parsed


def main():
    parser = argparse.ArgumentParser(description="AstroGrader Master Training Pipeline with Session Management")

    # Session Management
    parser.add_argument("--session", type=str, default=None,
                        help="Session name / ID (default: timestamp YYYY-MM-DD_HH-MM-SS)")
    parser.add_argument("--list-sessions", action="store_true",
                        help="List all previous training sessions and their model status, then exit")
    parser.add_argument("--resume-session", type=str, default=None,
                        help="Resume an unfinished/interrupted session in-place ('latest' or session ID)")
    parser.add_argument("--continue-session", type=str, default=None,
                        help="Start a NEW session fine-tuning from a previous session's checkpoints ('latest' or session ID)")
    parser.add_argument("--resume-model", nargs="+", default=None,
                        help="Cherry-pick resume weights per model (format: model=session_id or model=path/to/weights.pt)")
    parser.add_argument("--force-models", nargs="+", default=[],
                        help="When resuming a session, force re-running specific models even if marked completed")

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
    parser.add_argument("--auto-resume", action="store_true",
                        help="Automatically detect and resume from existing best.pt checkpoints for YOLO and CNNs")
    parser.add_argument("--resume-yolo", type=str, default=None,
                        help="Explicit checkpoint to resume / fine-tune YOLO from")
    parser.add_argument("--resume-cnns", action="store_true",
                        help="Automatically resume CNN models from their respective checkpoints/<model>_f32/best_model.pt")

    args = parser.parse_args()

    checkpoints_base = Path("checkpoints")
    sessions_base = checkpoints_base / "sessions"
    sessions_base.mkdir(parents=True, exist_ok=True)

    # Fast Action: List Sessions
    if args.list_sessions:
        list_sessions_cli(sessions_base)
        return

    overall_start = time.time()
    print_banner("AstroGrader: Master End-to-End Training Pipeline")

    # Resolve Session Setup
    session_id = None
    session_dir = None
    parent_session = None
    session_manifest = {}
    is_resuming_existing = False

    model_overrides = parse_resume_model_overrides(args.resume_model, sessions_base)

    if args.resume_session:
        # Resume incomplete session in-place
        res_id, res_dir = resolve_session(args.resume_session, sessions_base)
        session_id = res_id
        session_dir = res_dir
        is_resuming_existing = True
        s_json = session_dir / "session.json"
        if s_json.exists():
            with open(s_json, "r", encoding="utf-8") as fp:
                session_manifest = json.load(fp)
        print(f" [Session] Resuming existing session in-place: {session_id}")
    else:
        # Create a new session
        if args.continue_session:
            parent_id, parent_dir = resolve_session(args.continue_session, sessions_base)
            parent_session = parent_id
            print(f" [Session] Continuing from parent session: {parent_session}")

        now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_id = args.session if args.session else now_str
        session_dir = sessions_base / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        session_manifest = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "parent_session": parent_session,
            "status": "in_progress",
            "config": {
                "yolo_epochs": args.yolo_epochs,
                "cnn_epochs": args.cnn_epochs,
                "batch_size": args.cnn_batch,
                "lr": args.lr,
                "patience": args.patience,
            },
            "models": {},
        }
        print(f" [Session] Initialized new training session: {session_id} (Path: {session_dir})")

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
    models_entry = session_manifest.setdefault("models", {})

    # Helper to check if model was already completed in resumed session
    def should_skip_model(m_key: str) -> bool:
        if not is_resuming_existing:
            return False
        if m_key in args.force_models:
            return False
        prev = models_entry.get(m_key, {})
        return prev.get("status") == "completed"

    try:
        # Step 2: YOLO11 Instance Segmentation Training
        yolo_key = "yolo11_astro"
        if not args.skip_yolo:
            print_banner("Step 2: Ultralytics YOLO11-seg Training")
            if should_skip_model(yolo_key):
                prev = models_entry[yolo_key]
                print(f" [Session Resume] Model YOLO11-seg already completed in session {session_id}. Skipping!")
                benchmark_results.append({
                    "model": "YOLO11-seg",
                    "task": "Instance Segmentation",
                    "metric_name": "Mask / Box mAP",
                    "metric_val": f"Box mAP50: {prev.get('metrics', {}).get('box_map50', 'N/A')}",
                    "elapsed": f"{prev.get('elapsed_sec', 0.0):.1f}s (cached)",
                    "checkpoint": prev.get("checkpoint", ""),
                })
            else:
                t0_yolo = time.time()
                yaml_path = Path(args.yolo_dir) / "dataset.yaml"
                if not yaml_path.exists():
                    print(f"Error: YOLO config {yaml_path} does not exist. Ensure Step 1 completed successfully.")
                else:
                    yolo_backbone = args.yolo_backbone
                    resume_yolo_exact = False

                    # Check for mid-training resume within current session
                    yolo_session_last = session_dir / "yolo11_astro" / "weights" / "last.pt"
                    if is_resuming_existing and yolo_session_last.exists():
                        yolo_backbone = str(yolo_session_last)
                        resume_yolo_exact = True
                        print(f" [Session Resume] Resuming interrupted YOLO run from: {yolo_backbone}")
                    elif "yolo" in model_overrides or "yolo11_astro" in model_overrides:
                        yolo_backbone = model_overrides.get("yolo11_astro", model_overrides.get("yolo"))
                        print(f" [Override] Using explicit YOLO resume weights: {yolo_backbone}")
                    elif args.resume_yolo:
                        yolo_backbone = args.resume_yolo
                        print(f" [Resume] Using specified YOLO resume weights: {yolo_backbone}")
                    elif parent_session:
                        parent_yolo = sessions_base / parent_session / "yolo11_astro" / "weights" / "best.pt"
                        if parent_yolo.exists():
                            yolo_backbone = str(parent_yolo)
                            print(f" [Parent Session] Fine-tuning YOLO from parent session checkpoint: {yolo_backbone}")
                    elif args.auto_resume:
                        default_yolo_best = Path("runs/segment/yolo11_astro/weights/best.pt")
                        if default_yolo_best.exists():
                            yolo_backbone = str(default_yolo_best)
                            print(f" [Auto-Resume] Found previous YOLO champion: {yolo_backbone}. Fine-tuning on new data!")

                    models_entry[yolo_key] = {
                        "status": "in_progress",
                        "task": "Instance Segmentation",
                        "target_epochs": args.yolo_epochs,
                        "resumed_from": yolo_backbone,
                    }
                    save_session_manifest(session_dir, session_manifest)

                    yolo_metrics = train_yolo(
                        model_name=yolo_backbone,
                        data_yaml=str(yaml_path),
                        epochs=args.yolo_epochs,
                        batch=args.yolo_batch,
                        imgsz=args.tile_size,
                        device=args.device,
                        project=str(session_dir),
                        name="yolo11_astro",
                        lr0=args.lr,
                        patience=args.patience,
                        amp=not args.no_amp,
                        export_onnx=not args.no_onnx,
                        resume_training=resume_yolo_exact,
                    )
                    elapsed_yolo = time.time() - t0_yolo

                    yolo_best_pt = session_dir / "yolo11_astro" / "weights" / "best.pt"
                    yolo_last_pt = session_dir / "yolo11_astro" / "weights" / "last.pt"

                    # Mirror to legacy runs/segment/yolo11_astro/
                    sync_latest_mirrors(session_dir, "yolo11_astro", is_yolo=True)

                    models_entry[yolo_key] = {
                        "status": "completed",
                        "task": "Instance Segmentation",
                        "epochs_completed": args.yolo_epochs,
                        "target_epochs": args.yolo_epochs,
                        "metrics": yolo_metrics,
                        "checkpoint": str(yolo_best_pt),
                        "last_checkpoint": str(yolo_last_pt),
                        "resumed_from": yolo_backbone,
                        "elapsed_sec": round(elapsed_yolo, 1),
                    }
                    save_session_manifest(session_dir, session_manifest)

                    b50 = yolo_metrics.get("box_map50", 0.0)
                    s50 = yolo_metrics.get("seg_map50", 0.0)
                    benchmark_results.append({
                        "model": "YOLO11-seg",
                        "task": "Instance Segmentation",
                        "metric_name": "Mask / Box mAP50",
                        "metric_val": f"Box: {b50:.3f} / Mask: {s50:.3f}",
                        "elapsed": f"{elapsed_yolo:.1f}s",
                        "checkpoint": str(yolo_best_pt),
                    })
        else:
            print("\n>>> Skipping Step 2: YOLO Training (--skip-yolo)")

        # Step 3: CNN Multi-Model Training
        if not args.skip_cnn:
            print_banner("Step 3: CNN Backbones Multi-Model Training")

            for m_name in args.cnn_models:
                if should_skip_model(m_name):
                    prev = models_entry[m_name]
                    print(f" [Session Resume] Model {m_name} already completed in session {session_id}. Skipping!")
                    benchmark_results.append({
                        "model": m_name,
                        "task": "Multi-Label Classification",
                        "metric_name": "Macro F1 / Clean Acc",
                        "metric_val": f"{prev.get('macro_f1', 0.0):.4f} / {prev.get('clean_sky_acc', 0.0):.4f} (cached)",
                        "elapsed": f"{prev.get('elapsed_sec', 0.0):.1f}s (cached)",
                        "checkpoint": prev.get("checkpoint", ""),
                    })
                    continue

                cnn_resume_path = None
                resume_state = False

                # 1. Check for mid-training exact state resumption in current session
                session_last_model = session_dir / f"{m_name}_f32" / "last_model.pt"
                if is_resuming_existing and session_last_model.exists():
                    cnn_resume_path = str(session_last_model)
                    resume_state = True
                    print(f" [Session Resume] Resuming exact state for {m_name} from: {cnn_resume_path}")
                # 2. Check per-model CLI override
                elif m_name in model_overrides:
                    cnn_resume_path = model_overrides[m_name]
                    print(f" [Override] Fine-tuning {m_name} from override checkpoint: {cnn_resume_path}")
                # 3. Check parent session best checkpoint
                elif parent_session:
                    parent_best = sessions_base / parent_session / f"{m_name}_f32" / "best_model.pt"
                    if parent_best.exists():
                        cnn_resume_path = str(parent_best)
                        print(f" [Parent Session] Fine-tuning {m_name} from parent session: {cnn_resume_path}")
                # 4. Check global auto-resume / resume_cnns
                elif (args.auto_resume or args.resume_cnns):
                    default_cnn_best = checkpoints_base / f"{m_name}_f32" / "best_model.pt"
                    if default_cnn_best.exists():
                        cnn_resume_path = str(default_cnn_best)
                        print(f" [Auto-Resume] Found previous checkpoint for {m_name}: {cnn_resume_path}. Continuing training!")

                models_entry[m_name] = {
                    "status": "in_progress",
                    "task": "Multi-Label Classification",
                    "target_epochs": args.cnn_epochs,
                    "resumed_from": cnn_resume_path,
                }
                save_session_manifest(session_dir, session_manifest)

                res = run_cnn_training(
                    model_name=m_name,
                    dataset_dir=Path(args.out_dir),
                    epochs=args.cnn_epochs,
                    batch_size=args.cnn_batch,
                    patience=args.patience,
                    lr=args.lr,
                    device_arg=args.device,
                    out_dir=session_dir,
                    resume_checkpoint=cnn_resume_path,
                    resume_state=resume_state,
                )

                if res["success"]:
                    # Mirror to legacy checkpoints/<model_name>_f32/
                    sync_latest_mirrors(session_dir, m_name, is_yolo=False)

                    models_entry[m_name] = {
                        "status": "completed",
                        "task": "Multi-Label Classification",
                        "epochs_completed": res["epochs_trained"],
                        "target_epochs": args.cnn_epochs,
                        "best_epoch": res["best_epoch"],
                        "macro_f1": res["macro_f1"],
                        "clean_sky_acc": res["clean_sky_acc"],
                        "checkpoint": res["checkpoint"],
                        "last_checkpoint": res["last_checkpoint"],
                        "resumed_from": cnn_resume_path,
                        "elapsed_sec": round(res["elapsed_sec"], 1),
                    }
                    save_session_manifest(session_dir, session_manifest)

                    benchmark_results.append({
                        "model": res["model"],
                        "task": "Multi-Label Classification",
                        "metric_name": "Macro F1 / Clean Acc",
                        "metric_val": f"{res['macro_f1']:.4f} / {res['clean_sky_acc']:.4f} (ep {res['best_epoch']})",
                        "elapsed": f"{res['elapsed_sec']:.1f}s",
                        "checkpoint": res["checkpoint"],
                    })
                else:
                    models_entry[m_name]["status"] = "failed"
                    save_session_manifest(session_dir, session_manifest)
                    print(f"Error: Model {m_name} failed during training.")
        else:
            print("\n>>> Skipping Step 3: CNN Training (--skip-cnn)")

        session_manifest["status"] = "completed"
        save_session_manifest(session_dir, session_manifest)

    except KeyboardInterrupt:
        print("\n\n[Session Notice] Training interrupted by user (SIGINT). Preserving session state...")
        session_manifest["status"] = "interrupted"
        save_session_manifest(session_dir, session_manifest)
        print(f"To resume this exact session later, run:\n  python master_train.py --resume-session {session_id}\n")
        return

    # Step 4: Master Benchmark Report
    total_elapsed = time.time() - overall_start
    print_banner(f"Pipeline Execution Summary & Model Benchmarks [Session: {session_id}]")
    print(f"Total Pipeline Runtime: {total_elapsed:.1f}s\n")

    header = f"{'Model':<18} {'Task':<26} {'Key Metric':<30} {'Time':<9} {'Checkpoint'}"
    print(header)
    print("-" * 105)
    for b in benchmark_results:
        print(f"{b['model']:<18} {b['task']:<26} {b['metric_val']:<30} {b['elapsed']:<9} {b['checkpoint']}")
    print("-" * 105 + "\n")


if __name__ == "__main__":
    main()
