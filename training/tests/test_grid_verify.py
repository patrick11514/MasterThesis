"""
Unit tests for grid_verify.py: model discovery, GT evaluation, summary metrics,
and end-to-end synthetic FITS + PyTorch/ONNX grid verification.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from astropy.io import fits
import numpy as np
import torch

TRAINING_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TRAINING_ROOT))

from fits_utils import CLASSES
from grid_verify import (
    ModelSpec,
    collect_model_specs,
    compute_model_summary,
    evaluate_cell_vs_gt,
    run_grid_verify,
)
from models.cnn_zoo import NUM_CLASSES, build_model


class TestGridVerify(unittest.TestCase):
    def test_collect_model_specs_dedup_and_filter(self):
        """Tests directory scanning, format deduplication, and CNN/YOLO filtering."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m_dir = root / "iterations" / "v_test" / "models"
            m_dir.mkdir(parents=True)

            # Should be discovered (pt preferred over sibling onnx when fmt='pt')
            (m_dir / "astronet_best.pt").write_bytes(b"pt")
            (m_dir / "astronet.onnx").write_bytes(b"onnx")
            (m_dir / "yolo_best.pt").write_bytes(b"yolo")
            # Should be ignored when scanning directories
            (m_dir / "last_model.pt").write_bytes(b"last")
            (m_dir / "last.pt").write_bytes(b"last")
            (m_dir / "yolo11n-seg.pt").write_bytes(b"base")
            # Orphan onnx with no matching .pt should still be discovered in fmt='pt'
            (m_dir / "resnet18.onnx").write_bytes(b"onnx_only")

            specs_pt = collect_model_specs(model_patterns=[str(m_dir)], fmt="pt")
            names_pt = {s.path.name for s in specs_pt}
            self.assertEqual(names_pt, {"astronet_best.pt", "yolo_best.pt", "resnet18.onnx"})

            specs_onnx = collect_model_specs(model_patterns=[str(m_dir)], fmt="onnx")
            self.assertEqual({s.path.name for s in specs_onnx}, {"astronet.onnx", "resnet18.onnx"})

            specs_all = collect_model_specs(model_patterns=[str(m_dir)], fmt="all")
            self.assertEqual(
                {s.path.name for s in specs_all},
                {"astronet_best.pt", "astronet.onnx", "yolo_best.pt", "resnet18.onnx"},
            )

            specs_cnn = collect_model_specs(model_patterns=[str(m_dir)], fmt="pt", cnn_only=True)
            self.assertTrue(all(s.kind != "yolo" for s in specs_cnn))
            self.assertEqual({s.path.name for s in specs_cnn}, {"astronet_best.pt", "resnet18.onnx"})

            specs_yolo = collect_model_specs(model_patterns=[str(m_dir)], fmt="pt", yolo_only=True)
            self.assertEqual([s.path.name for s in specs_yolo], ["yolo_best.pt"])

    def test_evaluate_cell_vs_gt_and_summary(self):
        """Tests frame-level GT outcome classification and summary aggregation."""
        self.assertEqual(evaluate_cell_vs_gt(set(), set())["outcome"], "TN")
        self.assertEqual(evaluate_cell_vs_gt({"cloud"}, {"cloud"})["outcome"], "TP")
        self.assertEqual(evaluate_cell_vs_gt({"cloud"}, {"cloud", "airplane"})["outcome"], "PARTIAL")
        self.assertEqual(evaluate_cell_vs_gt({"cloud"}, set())["outcome"], "FP")
        self.assertEqual(evaluate_cell_vs_gt(set(), {"satellite_streak"})["outcome"], "FN")

        f1 = Path("a.fits")
        f2 = Path("b.fits")
        entry = {"kind": "cnn_pt", "spec": ModelSpec(label="m1", path=Path("m1.pt"), kind="cnn_pt", source="explicit")}
        cells = [
            {
                "fits_path": f1,
                "kind": "cnn_pt",
                "is_clean_pred": True,
                "pred_classes": set(),
                "class_counts": {},
                "class_max_conf": {},
                "elapsed_ms": 12.0,
                "has_gt": True,
                "gt_classes": set(),
                "gt_eval": evaluate_cell_vs_gt(set(), set()),
                "pred_tile_binary": np.zeros((2, len(CLASSES)), dtype=np.int32),
                "gt_tile_targets": np.zeros((2, len(CLASSES)), dtype=np.int32),
            },
            {
                "fits_path": f2,
                "kind": "cnn_pt",
                "is_clean_pred": False,
                "pred_classes": {"satellite_streak"},
                "class_counts": {"satellite_streak": 1},
                "class_max_conf": {"satellite_streak": 0.91},
                "elapsed_ms": 18.0,
                "has_gt": True,
                "gt_classes": {"satellite_streak"},
                "gt_eval": evaluate_cell_vs_gt({"satellite_streak"}, {"satellite_streak"}),
                "pred_tile_binary": np.array([[1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]], dtype=np.int32),
                "gt_tile_targets": np.array([[1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]], dtype=np.int32),
            },
        ]
        summary = compute_model_summary("m1", entry, cells, {f1: True, f2: False})
        self.assertEqual(summary["frame_binary_acc"], 1.0)
        self.assertEqual(summary["clean_specificity"], 1.0)
        self.assertEqual(summary["defect_recall"], 1.0)
        self.assertEqual(summary["frame_macro_f1"], 1.0)
        self.assertEqual(summary["tile_macro_f1"], 1.0)
        self.assertEqual(summary["tile_clean_acc"], 1.0)
        self.assertEqual(summary["consensus_agreement"], 1.0)

    def test_end_to_end_grid_verify_synthetic(self):
        """Runs full grid_verify pipeline on synthetic FITS + PyTorch/ONNX CNN checkpoints."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fits_dir = root / "fits"
            models_dir = root / "models"
            out_dir = root / "out"
            fits_dir.mkdir()
            models_dir.mkdir()

            # Create 2 synthetic 512x512 16-bit mono FITS frames + sibling GT JSONs
            rng = np.random.default_rng(7)
            for idx, (fname, is_clean) in enumerate([("clean_01.fits", True), ("streak_02.fits", False)]):
                img_u16 = np.clip(rng.normal(1200, 80, size=(512, 512)), 0, 65535).astype(np.uint16)
                if not is_clean:
                    img_u16[100:104, 50:450] = 35000
                hdu = fits.PrimaryHDU(img_u16)
                hdu.writeto(fits_dir / fname)

                boxes = (
                    []
                    if is_clean
                    else [{"id": "b1", "label": "satellite_streak", "type": "line", "x1": 50, "y1": 102, "x2": 450, "y2": 102}]
                )
                with open((fits_dir / fname).with_suffix(".json"), "w", encoding="utf-8") as fp:
                    json.dump({"file_name": fname, "width": 512, "height": 512, "is_clean": is_clean, "boxes": boxes}, fp)

            # Save two CNN PyTorch checkpoints + export one ONNX model
            m1 = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
            m1.eval()
            torch.save(
                {
                    "model_name": "astronet",
                    "state_dict": m1.state_dict(),
                    "input_mode": "f32",
                    "optimal_thresholds": {c: 0.55 for c in CLASSES},
                },
                models_dir / "astronet_best.pt",
            )

            m2 = build_model("mobilenet_v3", pretrained=False, num_classes=NUM_CLASSES)
            m2.eval()
            torch.save(
                {
                    "model_name": "mobilenet_v3",
                    "state_dict": m2.state_dict(),
                    "input_mode": "f32",
                },
                models_dir / "mobilenet_v3_best.pt",
            )

            dummy_img = torch.randn(1, 3, 512, 512, dtype=torch.float32)
            dummy_meta = torch.randn(1, 6, dtype=torch.float32)
            torch.onnx.export(
                m1,
                (dummy_img, dummy_meta),
                str(models_dir / "astronet.onnx"),
                export_params=True,
                opset_version=18,
                dynamo=False,
                input_names=["image", "meta"],
                output_names=["logits"],
                dynamic_axes={"image": {0: "batch_size"}, "meta": {0: "batch_size"}, "logits": {0: "batch_size"}},
            )

            res = run_grid_verify(
                fits_patterns=[str(fits_dir)],
                model_patterns=[str(models_dir)],
                fmt="all",
                out_dir=out_dir,
                use_optimal_thresholds=True,
                device_arg="cpu",
                panel_width=320,
                save_individual=True,
            )

            self.assertEqual(len(res["summaries"]), 3)
            self.assertTrue((out_dir / "grid_summary.md").exists())
            self.assertTrue((out_dir / "grid_matrix.csv").exists())
            self.assertTrue((out_dir / "grid_results.json").exists())
            self.assertTrue((out_dir / "clean_01_grid.png").exists())
            self.assertTrue((out_dir / "streak_02_grid.png").exists())
            self.assertTrue((out_dir / "individual").is_dir())

            with open(out_dir / "grid_results.json", "r", encoding="utf-8") as fp:
                data = json.load(fp)
            self.assertEqual(data["total_fits"], 2)
            self.assertEqual(data["total_models"], 3)
            self.assertTrue(data["has_ground_truth"])


if __name__ == "__main__":
    unittest.main()
