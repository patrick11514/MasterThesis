"""
Multi-Model Training Script for Astronomical Defect Detection.
Supports both Track A (Pure CNN from scratch on raw f32) and Track B (Pre-trained transfer learning).
Optimizes multi-label BCE loss with positive class balancing.
"""

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

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models.cnn_zoo import build_model, NUM_CLASSES
from fits_utils import CLASSES


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

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        rec = self.records[idx]
        labels = torch.tensor(rec["labels"], dtype=torch.float32)

        if self.input_mode == "f32":
            npy_path = self.base_dir / rec["f32_path"]
            # Load float32 [3, 512, 512]
            data = np.load(npy_path).astype(np.float32)
            tensor = torch.from_numpy(data)
        else:
            png_path = self.base_dir / rec["img_path"]
            img = Image.open(png_path).convert("RGB")
            # Convert to [3, 512, 512] float in [0, 1]
            tensor = transforms.ToTensor()(img)

        # Astronomical data augmentation
        if self.augment:
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

        return tensor, labels


def compute_metrics(
    all_preds: np.ndarray,
    all_targets: np.ndarray,
    threshold: float = 0.5,
) -> Dict[str, float]:
    """
    Computes multi-label metrics: Precision, Recall, F1 per class, and Clean Sky Accuracy.
    """
    binary_preds = (all_preds >= threshold).astype(int)
    targets = all_targets.astype(int)

    metrics = {}
    f1_list = []

    for i, cls_name in enumerate(CLASSES):
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
) -> float:
    model.train()
    total_loss = 0.0
    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * images.size(0)

    return total_loss / len(loader.dataset)


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> Tuple[float, Dict[str, float]]:
    model.eval()
    total_loss = 0.0
    all_preds = []
    all_targets = []

    with torch.no_grad():
        for images, targets in loader:
            images = images.to(device)
            targets = targets.to(device)

            outputs = model(images)
            loss = criterion(outputs, targets)
            total_loss += loss.item() * images.size(0)

            probs = torch.sigmoid(outputs).cpu().numpy()
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
    parser.add_argument("--out-dir", type=str, default="checkpoints")
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
    print(f"Using device: {device}")
    print(f"Training Model: {args.model} | Input Mode: {args.input_mode} | From Scratch: {args.from_scratch}")

    train_ds = AstroPatchDataset(train_manifest, dataset_dir.parent, input_mode=args.input_mode, augment=True)
    val_ds = AstroPatchDataset(val_manifest, dataset_dir.parent, input_mode=args.input_mode, augment=False)

    print(f"Train samples: {len(train_ds)} | Val samples: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=2, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=2)

    # Positive class weighting for imbalanced defect frequencies
    with open(train_manifest, "r", encoding="utf-8") as f:
        records = json.load(f)
    if records:
        all_labels = np.array([r["labels"] for r in records])
        pos_counts = np.sum(all_labels, axis=0)
        neg_counts = len(records) - pos_counts
        # Clip pos_weight to [1.0, 10.0]
        pos_weights = np.clip(neg_counts / np.maximum(pos_counts, 1), 1.0, 10.0)
        pos_weight_tensor = torch.tensor(pos_weights, dtype=torch.float32).to(device)
        print(f"Computed Pos Weights: {pos_weights.tolist()}")
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight_tensor)
    else:
        criterion = nn.BCEWithLogitsLoss()

    # Build model
    pretrained = not args.from_scratch and args.model != "astronet"
    model = build_model(args.model, pretrained=pretrained, num_classes=NUM_CLASSES).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    best_f1 = -1.0
    history = []

    start_time = time.time()
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, metrics = evaluate(model, val_loader, criterion, device)
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

        if args.dry_run:
            print("Dry run completed successfully.")
            break

    total_time = time.time() - start_time
    print(f"\nTraining completed in {total_time:.1f}s. Best Macro F1: {best_f1:.4f}")

    with open(out_dir / "training_history.json", "w", encoding="utf-8") as fp:
        json.dump(history, fp, indent=2)


if __name__ == "__main__":
    main()
