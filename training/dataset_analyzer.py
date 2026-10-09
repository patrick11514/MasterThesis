#!/usr/bin/env python3
"""
AstroGrader: Astronomical Dataset Pre-Analyzer & Class Health Audit.
Analyzes raw FITS frames and JSON annotations to evaluate class balance,
geometric shape distributions, deficit warnings, and sliced dataset parity.
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Union
import sys

# Ensure training root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fits_utils import CLASSES, CLASS_HEX_COLORS


def analyze_dataset(
    data_dir: Union[str, Path, List[Union[str, Path]]],
    manifest_dir: Optional[Union[str, Path]] = None,
    target_min_samples: int = 30,
) -> Dict:
    """
    Performs full statistical inspection of raw astronomical annotations and sliced manifests.
    """
    if isinstance(data_dir, (str, Path)):
        dirs = [Path(data_dir).resolve()]
    else:
        dirs = [Path(d).resolve() for d in data_dir]

    fits_files = []
    json_files = []
    extensions = ("*.fits", "*.fit", "*.FITS", "*.FIT")

    for d in dirs:
        if d.is_dir():
            for ext in extensions:
                fits_files.extend(list(d.glob(ext)))
            json_files.extend(list(d.glob("*.json")))

    fits_files = sorted(set(fits_files))
    json_files = sorted(set(json_files))

    total_fits = len(fits_files)
    total_json = len(json_files)

    # Class and shape accumulators
    class_counts: Dict[str, int] = {c: 0 for c in CLASSES}
    class_frame_counts: Dict[str, int] = {c: 0 for c in CLASSES}
    shape_counts: Dict[str, int] = {"box": 0, "line": 0, "polygon": 0}
    class_shape_breakdown: Dict[str, Dict[str, int]] = {
        c: {"box": 0, "line": 0, "polygon": 0} for c in CLASSES
    }

    annotated_frames = 0
    clean_frames = 0
    defective_frames = 0
    global_star_trail_frames = 0
    global_cloud_frames = 0
    total_annotations = 0

    unannotated_files: List[str] = []

    # Map fits stems to their json
    json_map = {j.stem: j for j in json_files}

    for f in fits_files:
        stem = f.stem
        j_path = json_map.get(stem)
        if not j_path:
            unannotated_files.append(f.name)
            continue

        annotated_frames += 1
        try:
            with open(j_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            continue

        boxes = data.get("boxes", [])
        gst = data.get("global_star_trailing", False)
        gc = data.get("global_cloud", False)
        is_clean = data.get("is_clean", len(boxes) == 0 and not gst and not gc)

        if gst:
            global_star_trail_frames += 1
        if gc:
            global_cloud_frames += 1

        if is_clean or (len(boxes) == 0 and not gst and not gc):
            clean_frames += 1
        else:
            defective_frames += 1

        total_annotations += len(boxes)
        frame_classes_seen = set()

        for b in boxes:
            lbl = b.get("label", "unknown")
            stype = b.get("type", "box")

            if lbl not in class_counts:
                class_counts[lbl] = 0
                class_frame_counts[lbl] = 0
                class_shape_breakdown[lbl] = {"box": 0, "line": 0, "polygon": 0}

            class_counts[lbl] += 1
            frame_classes_seen.add(lbl)

            if stype in shape_counts:
                shape_counts[stype] += 1
            else:
                shape_counts[stype] = shape_counts.get(stype, 0) + 1

            if stype in class_shape_breakdown[lbl]:
                class_shape_breakdown[lbl][stype] += 1
            else:
                class_shape_breakdown[lbl][stype] = 1

        for c in frame_classes_seen:
            class_frame_counts[c] = class_frame_counts.get(c, 0) + 1

    # Deficit recommendations
    recommendations = []
    class_health = {}
    for c, count in class_counts.items():
        deficit = max(0, target_min_samples - count)
        status = "healthy" if count >= target_min_samples else ("critical" if count < 10 else "low")
        class_health[c] = {
            "count": count,
            "frames": class_frame_counts.get(c, 0),
            "status": status,
            "deficit": deficit,
            "percent": round((count / max(1, total_annotations)) * 100.0, 1),
            "shapes": class_shape_breakdown.get(c, {}),
        }
        if deficit > 0:
            recommendations.append({
                "class": c,
                "current": count,
                "target": target_min_samples,
                "needed": deficit,
                "priority": "High" if count < 10 else "Medium",
                "message": f"Class '{c}' has only {count} sample(s). Recommend tagging at least {deficit} more for reliable generalization.",
            })

    # Sort recommendations by priority (highest needed first)
    recommendations.sort(key=lambda x: x["needed"], reverse=True)

    # Check sliced dataset if directory exists
    sliced_info = None
    m_dir = Path(manifest_dir) if manifest_dir else (dirs[0] / "dataset" if dirs else None)
    if m_dir and (m_dir / "train_manifest.json").exists():
        try:
            with open(m_dir / "train_manifest.json", "r", encoding="utf-8") as fp:
                train_recs = json.load(fp)
            with open(m_dir / "val_manifest.json", "r", encoding="utf-8") as fp:
                val_recs = json.load(fp)

            train_clean = sum(1 for r in train_recs if r.get("is_clean", False))
            val_clean = sum(1 for r in val_recs if r.get("is_clean", False))

            train_class_tiles = {c: 0 for c in CLASSES}
            val_class_tiles = {c: 0 for c in CLASSES}
            for r in train_recs:
                for cls_name in r.get("classes", []):
                    if cls_name in train_class_tiles:
                        train_class_tiles[cls_name] += 1
            for r in val_recs:
                for cls_name in r.get("classes", []):
                    if cls_name in val_class_tiles:
                        val_class_tiles[cls_name] += 1

            sliced_info = {
                "train_tiles": len(train_recs),
                "val_tiles": len(val_recs),
                "train_clean": train_clean,
                "train_defects": len(train_recs) - train_clean,
                "val_clean": val_clean,
                "val_defects": len(val_recs) - val_clean,
                "train_class_tiles": train_class_tiles,
                "val_class_tiles": val_class_tiles,
            }
        except Exception as e:
            sliced_info = {"error": str(e)}

    return {
        "directories": [str(d) for d in dirs],
        "summary": {
            "total_fits": total_fits,
            "total_json": total_json,
            "annotated_frames": annotated_frames,
            "unannotated_frames": len(unannotated_files),
            "clean_frames": clean_frames,
            "defective_frames": defective_frames,
            "total_annotations": total_annotations,
            "global_star_trailing_frames": global_star_trail_frames,
            "global_cloud_frames": global_cloud_frames,
        },
        "class_health": class_health,
        "shape_counts": shape_counts,
        "recommendations": recommendations,
        "sliced_info": sliced_info,
        "unannotated_sample_files": unannotated_files[:10],
    }


def print_cli_report(stats: Dict):
    """Prints a beautiful, informative ANSI terminal summary of dataset health."""
    s = stats["summary"]
    ch = stats["class_health"]
    sc = stats["shape_counts"]
    recs = stats["recommendations"]

    print("\n" + "=" * 70)
    print("        AstroGrader: Astronomical Dataset Health & Balance Report")
    print("=" * 70)
    print(f"Directories Inspected: {', '.join(stats['directories'])}")
    print(f"Total FITS Frames:     {s['total_fits']}")
    print(f"Annotated Frames:      {s['annotated_frames']} ({round(s['annotated_frames'] / max(1, s['total_fits']) * 100, 1)}%)")
    print(f"Unannotated Frames:    {s['unannotated_frames']}")
    print(f"Clean Sky Frames:      {s['clean_frames']}")
    print(f"Defective Frames:      {s['defective_frames']}")
    print(f"Total Shapes Tagged:   {s['total_annotations']}")
    print(f"Shape Distribution:    Box: {sc.get('box', 0)} | Line: {sc.get('line', 0)} | Polygon: {sc.get('polygon', 0)}")
    print("-" * 70)

    print("\n[Class Sample Distribution & Health]")
    header = f"{'Class':<20} {'Samples':<9} {'Share':<8} {'Frames':<8} {'Status':<10} {'Box':<5} {'Line':<5} {'Poly':<5}"
    print(header)
    print("-" * 70)

    for c, info in ch.items():
        shapes = info.get("shapes", {})
        status_label = info["status"].upper()
        if info["status"] == "critical":
            status_colored = f"\033[91m{status_label}\033[0m"
        elif info["status"] == "low":
            status_colored = f"\033[93m{status_label}\033[0m"
        else:
            status_colored = f"\033[92m{status_label}\033[0m"

        print(
            f"{c:<20} {info['count']:<9} {info['percent']:<7}% {info['frames']:<8} "
            f"{status_colored:<19} {shapes.get('box', 0):<5} {shapes.get('line', 0):<5} {shapes.get('polygon', 0):<5}"
        )

    print("\n" + "-" * 70)
    if recs:
        print("\033[93m[Actionable Recommendations & Deficits Detected]\033[0m")
        for idx, r in enumerate(recs, 1):
            p_color = "\033[91m" if r["priority"] == "High" else "\033[93m"
            print(f"  {idx}. [{p_color}{r['priority']} Priority\033[0m] {r['message']}")
    else:
        print("\033[92m[All classes meet the target minimum sample threshold!]\033[0m")

    # Sliced info
    si = stats.get("sliced_info")
    if si and "train_tiles" in si:
        print("\n" + "-" * 70)
        print("[Sliced 512x512 Dataset Parity]")
        print(f"  Training Tiles:   {si['train_tiles']} (Clean: {si['train_clean']}, Defect: {si['train_defects']})")
        print(f"  Validation Tiles: {si['val_tiles']} (Clean: {si['val_clean']}, Defect: {si['val_defects']})")
        print("  Tile counts by class (Train / Val):")
        for c in CLASSES:
            tr_c = si["train_class_tiles"].get(c, 0)
            val_c = si["val_class_tiles"].get(c, 0)
            print(f"    - {c:<18}: {tr_c:<5} train | {val_c:<5} val")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstroGrader Dataset Pre-Analyzer")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="TRAINING_FILES",
        nargs="+",
        help="One or more directories containing FITS and JSON annotations",
    )
    parser.add_argument(
        "--manifest-dir",
        type=str,
        default="dataset",
        help="Directory containing train_manifest.json and val_manifest.json",
    )
    parser.add_argument(
        "--target-min",
        type=int,
        default=30,
        help="Target minimum sample count per class to flag deficits",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of text report")

    args = parser.parse_args()
    results = analyze_dataset(
        args.data_dir,
        manifest_dir=args.manifest_dir,
        target_min_samples=args.target_min,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_cli_report(results)
