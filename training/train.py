"""
Multi-Model Training Script for Astronomical Defect Detection.
Supports both Track A (Pure CNN from scratch on raw f32) and Track B (Pre-trained transfer learning).
Optimizes multi-label BCE loss with positive class balancing.
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
    sdk_lib_candidates = glob.glob(os.path.join(conda_prefix, "lib", "python*", "site-packages", "_rocm_sdk_libraries_*", "lib"))
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
import json
from pathlib import Path
import time
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models.cnn_zoo import build_model, NUM_CLASSES
from fits_utils import CLASSES


class EarlyStopping:
    """
    Early stops training if monitored metric doesn't improve after `patience` epochs.
    Tracks best metric and best epoch, preventing overfitting.
    """
    def __init__(self, patience: int = 5, min_delta: float = 0.001, mode: str = "max"):
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.best_epoch = 0

    def step(self, current: float, epoch: int) -> bool:
        """Returns True if training should terminate early."""
        if self.patience <= 0:
            return False

        if self.best_score is None:
            self.best_score = current
            self.best_epoch = epoch
            return False

        if self.mode == "max":
            improved = (current - self.best_score) > self.min_delta
        else:
            improved = (self.best_score - current) > self.min_delta

        if improved:
            self.best_score = current
            self.best_epoch = epoch
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True
                return True

        return False


class AstroPatchDataset(Dataset):
    """
    Dataset loader for 512x512 astronomical patches.
    Supports native float32 (.npy) and 8-bit RGB (.png).
    """
    def __init__(
        self,
        manifest_path: Path,
        base_dir: Path,
        input_mode: str = "f32",  # 'f32' or 'img'
        augment: bool = True,
    ):
        self.base_dir = base_dir
        self.input_mode = input_mode
        self.augment = augment

        with open(manifest_path, "r", encoding="utf-8") as f:
            self.records = json.load(f)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        rec = self.records[idx]
        labels = torch.tensor(rec["labels"], dtype=torch.float32)
        meta_val = rec.get("meta", [0.0] * 6)
        meta_tensor = torch.tensor(meta_val, dtype=torch.float32)

        if self.input_mode == "f32":
            p = Path(rec["f32_path"])
            npy_path = self.base_dir / p
            if not npy_path.exists():
                npy_path = p
            # Load float32 [3, 512, 512]
            data = np.load(npy_path).astype(np.float32)
            tensor = torch.from_numpy(data)
        else:
            p = Path(rec["img_path"])
            png_path = self.base_dir / p
            if not png_path.exists():
                png_path = p
            img = Image.open(png_path).convert("RGB")
            # Convert to [3, 512, 512] float in [0, 1]
            tensor = transforms.ToTensor()(img)

        # Astronomical data augmentation
        if self.augment:
            # Mono-camera Rec.601 luminance simulation (25% probability)
            if torch.rand(1).item() < 0.25:
                if not torch.allclose(tensor[0], tensor[1], atol=1e-4):
                    weights = torch.tensor([0.299, 0.587, 0.114], device=tensor.device, dtype=tensor.dtype).view(3, 1, 1)
                    mono = (tensor * weights).sum(dim=0, keepdim=True)
                    tensor = mono.repeat(3, 1, 1)

            # Random 90/180/270 degree rotation
            k = int(torch.randint(0, 4, (1,)).item())
            if k > 0:
                tensor = torch.rot90(tensor, k, [1, 2])

            # Random horizontal flip
            if torch.rand(1).item() > 0.5:
                tensor = torch.flip(tensor, [2])

            # Random vertical flip
            if torch.rand(1).item() > 0.5:
                tensor = torch.flip(tensor, [1])

            # Subtle Gaussian noise injection
            if torch.rand(1).item() > 0.6:
                noise = torch.randn_like(tensor) * 0.005
                tensor = torch.clamp(tensor + noise, 0.0, 1.0)

        return tensor, meta_tensor, labels


def compute_metrics(
    all_preds: np.ndarray,
    all_targets: np.ndarray,
    threshold: float = 0.5,
) -> Dict[str, float]:
    """
    Computes multi-label metrics: Precision, Recall, F1 per class, and Clean Sky Accuracy.
    Binarizes ground truth targets (targets >= 0.5) to seamlessly handle continuous soft targets.
    """
    binary_preds = (all_preds >= threshold).astype(int)
    targets = (all_targets >= 0.5).astype(int)

    metrics = {}
    f1_list = []
    num_classes = min(binary_preds.shape[1], len(CLASSES))

    for i in range(num_classes):
        cls_name = CLASSES[i]
        tp = int(np.sum((binary_preds[:, i] == 1) & (targets[:, i] == 1)))
        fp = int(np.sum((binary_preds[:, i] == 1) & (targets[:, i] == 0)))
        fn = int(np.sum((binary_preds[:, i] == 0) & (targets[:, i] == 1)))

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

        metrics[f"{cls_name}_precision"] = round(prec, 4)
        metrics[f"{cls_name}_recall"] = round(rec, 4)
        metrics[f"{cls_name}_f1"] = round(f1, 4)
        f1_list.append(f1)

    metrics["macro_f1"] = round(float(np.mean(f1_list)), 4)

    # Clean sky metric: true clean vs predicted clean
    pred_clean = (np.sum(binary_preds, axis=1) == 0)
    true_clean = (np.sum(targets, axis=1) == 0)
    clean_acc = np.mean(pred_clean == true_clean) if len(true_clean) > 0 else 0.0
    metrics["clean_sky_accuracy"] = round(float(clean_acc), 4)

    # Exact match ratio (Hamming subset accuracy)
    exact_match = np.mean(np.all(binary_preds == targets, axis=1))
    metrics["exact_match_ratio"] = round(float(exact_match), 4)

    return metrics


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    use_amp: bool = False,
    epoch: int = 1,
    total_epochs: int = 1,
) -> float:
    model.train()
    total_loss = 0.0
    pbar = tqdm(loader, desc=f"Epoch {epoch:02d}/{total_epochs:02d} [Train]", leave=False)
    for images, metas, targets in pbar:
        if device.type == "cuda":
            images = images.to(device, non_blocking=True, memory_format=torch.channels_last)
        else:
            images = images.to(device)
        metas = metas.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        optimizer.zero_grad()
        with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
            outputs = model(images, metas)
            loss = criterion(outputs, targets)
        loss.backward()
        # Gradient norm clipping prevents BatchNorm validation spikes
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        batch_loss = loss.item()
        total_loss += batch_loss * images.size(0)
        pbar.set_postfix(loss=f"{batch_loss:.4f}")

    return total_loss / len(loader.dataset)


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    use_amp: bool = False,
    epoch: int = 1,
    total_epochs: int = 1,
) -> Tuple[float, Dict[str, float]]:
    model.eval()
    total_loss = 0.0
    all_preds = []
    all_targets = []

    pbar = tqdm(loader, desc=f"Epoch {epoch:02d}/{total_epochs:02d} [Val]", leave=False)
    with torch.no_grad():
        for images, metas, targets in pbar:
            if device.type == "cuda":
                images = images.to(device, non_blocking=True, memory_format=torch.channels_last)
            else:
                images = images.to(device)
            metas = metas.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                outputs = model(images, metas)
                loss = criterion(outputs, targets)
            batch_loss = loss.item()
            total_loss += batch_loss * images.size(0)
            pbar.set_postfix(loss=f"{batch_loss:.4f}")

            probs = torch.sigmoid(outputs.float()).cpu().numpy()
            all_preds.append(probs)
            all_targets.append(targets.cpu().numpy())

    avg_loss = total_loss / len(loader.dataset) if len(loader.dataset) > 0 else 0.0
    all_preds = np.concatenate(all_preds, axis=0) if all_preds else np.zeros((0, NUM_CLASSES))
    all_targets = np.concatenate(all_targets, axis=0) if all_targets else np.zeros((0, NUM_CLASSES))

    metrics = compute_metrics(all_preds, all_targets)
    return avg_loss, metrics


def main():
    parser = argparse.ArgumentParser(description="AstroGrader CNN Training Pipeline")
    parser.add_argument("--model", type=str, default="astronet", choices=[
        "astronet", "resnet18", "resnet34", "mobilenet_v3", "efficientnet_b0"
    ])
    parser.add_argument("--dataset-dir", type=str, default="dataset", help="Directory with manifests")
    parser.add_argument("--input-mode", type=str, default="f32", choices=["f32", "img"])
    parser.add_argument("--from-scratch", action="store_true", help="Train from random weights (Track A)")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--resume", "--weights", dest="resume", type=str, default=None,
                        help="Path to existing model checkpoint (.pt) to resume or fine-tune from")
    parser.add_argument("--resume-state", action="store_true",
                        help="Resume exact optimizer, scheduler, early stopper, and epoch state from checkpoint")
    parser.add_argument("--out-dir", type=str, default="checkpoints")
    parser.add_argument("--patience", type=int, default=5, help="Early stopping patience (epochs without improvement, 0 to disable)")
    parser.add_argument("--no-amp", action="store_true", help="Disable mixed precision (bfloat16 AMP)")
    parser.add_argument("--dry-run", action="store_true", help="Run 1 quick batch for testing")

    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    train_manifest = dataset_dir / "train_manifest.json"
    val_manifest = dataset_dir / "val_manifest.json"

    if not train_manifest.exists():
        print(f"Error: {train_manifest} does not exist. Run prep_dataset.py first.")
        return

    out_dir = Path(args.out_dir) / f"{args.model}_{args.input_mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = (device.type == "cuda" and not args.no_amp)
    print(f"Using device: {device} (Mixed Precision AMP: {use_amp}, bfloat16)")
    print(f"Training Model: {args.model} | Input Mode: {args.input_mode} | From Scratch: {args.from_scratch} | Patience: {args.patience}")
    if args.resume:
        print(f"Resume / Fine-tune weights: {args.resume}")

    train_ds = AstroPatchDataset(train_manifest, dataset_dir.parent, input_mode=args.input_mode, augment=True)
    val_ds = AstroPatchDataset(val_manifest, dataset_dir.parent, input_mode=args.input_mode, augment=False)

    print(f"Train samples: {len(train_ds)} | Val samples: {len(val_ds)}")

    pin_mem = (device.type == "cuda")
    num_workers = min(8, os.cpu_count() or 4)
    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=pin_mem,
        persistent_workers=(num_workers > 0),
        prefetch_factor=(2 if num_workers > 0 else None),
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_mem,
        persistent_workers=(num_workers > 0),
        prefetch_factor=(2 if num_workers > 0 else None),
    )

    with open(train_manifest, "r", encoding="utf-8") as f:
        records = json.load(f)
    if records:
        manifest_classes = len(records[0].get("labels", []))
        if manifest_classes != NUM_CLASSES:
            raise ValueError(
                f"Manifest class count mismatch: '{train_manifest}' has {manifest_classes} classes per sample, "
                f"but models are configured with NUM_CLASSES={NUM_CLASSES} ({CLASSES}).\n"
                f"Please re-run dataset preparation to sync manifests with current classes:\n"
                f"  python prep_dataset.py --data-dir ../TRAINING_FILES --out-dir dataset --export-yolo"
            )
        all_labels = np.array([r["labels"] for r in records])
        pos_counts = np.sum(all_labels >= 0.5, axis=0)
        neg_counts = len(records) - pos_counts
        # Square-root damped pos_weight clipped to [1.0, 4.0]
        pos_weights = np.clip(np.sqrt(neg_counts / np.maximum(pos_counts, 1)), 1.0, 4.0)
        pos_weight_tensor = torch.tensor(pos_weights, dtype=torch.float32).to(device)
        print(f"Computed Pos Weights (sqrt-damped [1.0, 4.0]): {pos_weights.tolist()}")
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight_tensor)
    else:
        criterion = nn.BCEWithLogitsLoss()

    # Build model
    pretrained = not args.from_scratch and args.model != "astronet"
    model = build_model(args.model, pretrained=pretrained, num_classes=NUM_CLASSES)
    if device.type == "cuda":
        model = model.to(device, memory_format=torch.channels_last)
    else:
        model = model.to(device)

    # Load resume weights if requested
    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.exists():
            print(f"Error: Specified resume checkpoint not found: {resume_path}")
            return
        checkpoint = torch.load(resume_path, map_location=device)
        state_dict = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
        prev_epoch = checkpoint.get("epoch", "N/A") if isinstance(checkpoint, dict) else "N/A"
        prev_f1 = checkpoint.get("metrics", {}).get("macro_f1", "N/A") if isinstance(checkpoint, dict) else "N/A"

        # Filter out mismatching layer keys (e.g. if num_classes changed)
        model_dict = model.state_dict()
        filtered_dict = {}
        mismatched_keys = []
        for k, v in state_dict.items():
            if k in model_dict and model_dict[k].shape == v.shape:
                filtered_dict[k] = v
            else:
                mismatched_keys.append(k)

        model_dict.update(filtered_dict)
        model.load_state_dict(model_dict)
        print(f" [Resume] Successfully loaded {len(filtered_dict)} layers from {resume_path}")
        print(f"          Checkpoint details: Epoch {prev_epoch}, Macro F1: {prev_f1}")
        if mismatched_keys:
            print(f"          Skipped {len(mismatched_keys)} mismatched or non-matching keys: {mismatched_keys[:3]}...")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    early_stopper = EarlyStopping(patience=args.patience, min_delta=1e-3, mode="max")
    best_f1 = -1.0
    history = []
    start_epoch = 1

    if args.resume and args.resume_state and isinstance(checkpoint, dict):
        if "optimizer_state_dict" in checkpoint:
            try:
                optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
                print(" [Resume] Restored optimizer state.")
            except Exception as e:
                print(f" [Resume] Warning: Could not restore optimizer state: {e}")
        if "scheduler_state_dict" in checkpoint:
            try:
                scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
                print(" [Resume] Restored learning rate scheduler state.")
            except Exception as e:
                print(f" [Resume] Warning: Could not restore scheduler state: {e}")
        if "early_stopper" in checkpoint and isinstance(checkpoint["early_stopper"], dict):
            es_info = checkpoint["early_stopper"]
            early_stopper.counter = es_info.get("counter", 0)
            early_stopper.best_score = es_info.get("best_score", None)
            early_stopper.best_epoch = es_info.get("best_epoch", 0)
            print(f" [Resume] Restored early stopper (patience counter: {early_stopper.counter}, best score: {early_stopper.best_score})")
        if "history" in checkpoint and isinstance(checkpoint["history"], list):
            history = list(checkpoint["history"])
        if "best_f1" in checkpoint:
            best_f1 = float(checkpoint["best_f1"])
        elif "metrics" in checkpoint and "macro_f1" in checkpoint["metrics"]:
            best_f1 = float(checkpoint["metrics"]["macro_f1"])

        start_epoch = int(checkpoint.get("epoch", 0)) + 1
        print(f" [Resume] Resuming exact training state from epoch {start_epoch} (target: {args.epochs})")

        if start_epoch > args.epochs:
            print(f" [Resume] Model already completed {start_epoch - 1} of {args.epochs} epochs. Nothing to train.")
            return

    start_time = time.time()
    for epoch in range(start_epoch, args.epochs + 1):
        t0 = time.time()
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device, use_amp=use_amp, epoch=epoch, total_epochs=args.epochs)
        val_loss, metrics = evaluate(model, val_loader, criterion, device, use_amp=use_amp, epoch=epoch, total_epochs=args.epochs)
        scheduler.step()

        elapsed = time.time() - t0
        macro_f1 = metrics.get("macro_f1", 0.0)
        clean_acc = metrics.get("clean_sky_accuracy", 0.0)

        print(
            f"Epoch [{epoch:02d}/{args.epochs:02d}] "
            f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
            f"Macro F1: {macro_f1:.4f} | Clean Acc: {clean_acc:.4f} | Time: {elapsed:.1f}s"
        )

        history.append({
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            **metrics,
        })

        # Incremental history flush to disk
        with open(out_dir / "training_history.json", "w", encoding="utf-8") as fp:
            json.dump(history, fp, indent=2)

        # Save best model checkpoint
        if macro_f1 > best_f1:
            best_f1 = macro_f1
            torch.save({
                "epoch": epoch,
                "model_name": args.model,
                "state_dict": model.state_dict(),
                "metrics": metrics,
                "input_mode": args.input_mode,
            }, out_dir / "best_model.pt")
            print(f"  --> Saved new best checkpoint (Macro F1: {best_f1:.4f})")

        # Always save last model checkpoint with full optimizer, scheduler and epoch state
        torch.save({
            "epoch": epoch,
            "target_epochs": args.epochs,
            "model_name": args.model,
            "state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "early_stopper": {
                "counter": early_stopper.counter,
                "best_score": early_stopper.best_score,
                "best_epoch": early_stopper.best_epoch,
            },
            "best_f1": best_f1,
            "metrics": metrics,
            "history": history,
            "input_mode": args.input_mode,
        }, out_dir / "last_model.pt")

        if early_stopper.step(macro_f1, epoch):
            print(
                f"\n[Early Stopping Triggered] No improvement for {early_stopper.patience} consecutive epochs.\n"
                f"Peak Macro F1: {early_stopper.best_score:.4f} achieved at epoch {early_stopper.best_epoch}.\n"
                f"Halting training early and preserving best checkpoint."
            )
            break

        if args.dry_run:
            print("Dry run completed successfully.")
            break

    total_time = time.time() - start_time
    print(f"\nTraining completed in {total_time:.1f}s. Best Macro F1: {best_f1:.4f}")

    with open(out_dir / "training_history.json", "w", encoding="utf-8") as fp:
        json.dump(history, fp, indent=2)

    # Automatic ONNX Export of best checkpoint
    best_ckpt_path = out_dir / "best_model.pt"
    if best_ckpt_path.exists():
        onnx_path = out_dir / "best_model.onnx"
        print(f"\nExporting champion model to ONNX: {onnx_path}...")
        try:
            ckpt_data = torch.load(best_ckpt_path, map_location="cpu")
            export_model = build_model(args.model, pretrained=False, num_classes=NUM_CLASSES)
            export_model.load_state_dict(ckpt_data["state_dict"])
            export_model.eval()

            dummy_img = torch.randn(1, 3, 512, 512, dtype=torch.float32)
            dummy_meta = torch.randn(1, 6, dtype=torch.float32)

            torch.onnx.export(
                export_model,
                (dummy_img, dummy_meta),
                str(onnx_path),
                export_params=True,
                opset_version=18,
                do_constant_folding=True,
                dynamo=False,
                input_names=["image", "meta"],
                output_names=["logits"],
                dynamic_axes={
                    "image": {0: "batch_size"},
                    "meta": {0: "batch_size"},
                    "logits": {0: "batch_size"},
                },
            )
            print(f"  Successfully saved {onnx_path.name} ({onnx_path.stat().st_size / (1024 * 1024):.2f} MB)")
        except Exception as e:
            print(f"  Warning: Automatic ONNX export failed: {e}")


if __name__ == "__main__":
    main()
