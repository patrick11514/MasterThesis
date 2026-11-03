"""
Comprehensive unit tests for AstroGrader V2:
- 6-Element Optical & Statistical Tile Metadata (compute_tile_metadata)
- Physics-Based Synthetic Defect Generator (synthetic_defects.py)
- DualPool2d (Avg+Max pooling) and UniversalFusionWrapper (FiLM modulation)
- Soft label calculation & Star-presence gating
- Dual-input ONNX Export and Numerical Parity
"""

import math
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
import torch

import sys
training_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(training_dir))

from fits_utils import compute_tile_metadata, to_stf_u8, CLASSES
from models.cnn_zoo import DualPool2d, UniversalFusionWrapper, build_model, NUM_CLASSES
from synthetic_defects import (
    inject_synthetic_satellite,
    inject_synthetic_airplane,
    inject_synthetic_psf_defect,
    inject_synthetic_obstruction,
    inject_random_synthetic_defect,
)
from prep_dataset import extract_tile_yolo_segments, normalize_legacy_annotations, _slice_frame_array
from train import AstroPatchDataset, compute_metrics
from iter_manager import extract_cnn_checkpoint_info


class TestAstroGraderV2(unittest.TestCase):
    def test_compute_tile_metadata_structure_and_bounds(self):
        """Tests that compute_tile_metadata returns valid 6-element normalized floats with frame-relative bg_ratio."""
        np.random.seed(42)
        # 512x512 tile
        tile_linear = np.random.normal(loc=0.04, scale=0.005, size=(512, 512, 3)).astype(np.float32)
        tile_stf = np.random.uniform(0.1, 0.4, size=(512, 512, 3)).astype(np.float32)

        # Inject a few synthetic bright stars into STF
        for (sy, sx) in [(100, 100), (200, 250), (400, 300)]:
            tile_stf[sy - 2 : sy + 3, sx - 2 : sx + 3, :] = 0.95

        pixel_scale = 1.85
        meta = compute_tile_metadata(
            tile_linear_rgb=tile_linear,
            tile_stf_rgb=tile_stf,
            frame_median=0.04,
            frame_mad=0.005,
            pixel_scale=pixel_scale,
        )

        self.assertEqual(len(meta), 6)
        for val in meta:
            self.assertIsInstance(val, float)
            self.assertTrue(math.isfinite(val))

        # Pixel scale check
        expected_m0 = round(float(np.log1p(pixel_scale) / 2.5), 4)
        self.assertAlmostEqual(meta[0], expected_m0, places=3)

        # Frame-relative bg_ratio should be ~1.0 when tile median matches frame_median
        self.assertAlmostEqual(meta[1], 1.0, delta=0.05)
        self.assertGreater(meta[2], 0.1)
        self.assertLess(meta[2], 2.0)

        # Star count should detect the injected blobs
        self.assertGreater(meta[3], 0.0)
        self.assertLessEqual(meta[3], 1.0)

        # FWHM and Eccentricity should be bounded in [0, 1]
        self.assertTrue(0.0 <= meta[4] <= 1.0)
        self.assertTrue(0.0 <= meta[5] <= 1.0)

    def test_synthetic_satellite_injection(self):
        """Verifies synthetic satellite streak injection and line annotation format."""
        tile = np.zeros((512, 512, 3), dtype=np.float32)
        mod_tile, cname, annot = inject_synthetic_satellite(tile, bg_med=0.02, bg_mad=0.003)

        self.assertEqual(cname, "satellite_streak")
        self.assertEqual(annot["type"], "line")
        self.assertEqual(annot["label"], "satellite_streak")
        self.assertGreater(float(np.max(mod_tile)), 0.002)
        self.assertEqual(mod_tile.shape, (512, 512, 3))

    def test_synthetic_airplane_injection(self):
        """Verifies synthetic airplane injection with strobe flashes."""
        tile = np.zeros((512, 512, 3), dtype=np.float32)
        mod_tile, cname, annot = inject_synthetic_airplane(tile, bg_med=0.02, bg_mad=0.003)

        self.assertEqual(cname, "airplane")
        self.assertEqual(annot["type"], "line")
        self.assertGreater(float(np.max(mod_tile)), 0.02)
        self.assertGreater(annot["thickness"], 15.0)

    def test_synthetic_obstruction_injection(self):
        """Verifies synthetic obstruction polygon injection."""
        tile = np.ones((512, 512, 3), dtype=np.float32) * 0.5
        mod_tile, cname, annot = inject_synthetic_obstruction(tile, bg_med=0.02, bg_mad=0.003)

        self.assertEqual(cname, "obstruction")
        self.assertEqual(annot["type"], "polygon")
        self.assertGreaterEqual(len(annot["points"]), 3)
        # Attenuation should darken the obstruction region toward 0.02
        self.assertLess(float(np.min(mod_tile)), 0.15)

    def test_synthetic_psf_defect_gating(self):
        """Verifies that PSF defect injection triggers only when stars are present."""
        # Empty sky (noise only) -> should return None
        empty_tile = np.ones((512, 512, 3), dtype=np.float32) * 0.02
        _, cname, _ = inject_synthetic_psf_defect(empty_tile, bg_med=0.02, bg_mad=0.003, mode="star_trail")
        self.assertIsNone(cname)

        # Starry sky -> should trigger
        starry_tile = np.ones((512, 512, 3), dtype=np.float32) * 0.02
        cv2.circle(starry_tile, (250, 250), 15, (0.85, 0.85, 0.85), -1)
        cv2.circle(starry_tile, (100, 100), 12, (0.70, 0.70, 0.70), -1)
        mod_tile, cname_st, ann_st = inject_synthetic_psf_defect(starry_tile, bg_med=0.02, bg_mad=0.003, mode="star_trail")
        self.assertEqual(cname_st, "star_trail")
        self.assertIsNotNone(ann_st)

    def test_dual_pool_and_film_modulation(self):
        """Tests DualPool2d concatenation and UniversalFusionWrapper forward pass."""
        dual_pool = DualPool2d()
        feat_map = torch.randn(2, 64, 16, 16)
        pooled = dual_pool(feat_map)
        self.assertEqual(pooled.shape, (2, 128))

        # Model wrapper test
        model = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES, meta_dim=6)
        x_img = torch.randn(2, 3, 512, 512, requires_grad=True)
        x_meta = torch.randn(2, 6, requires_grad=True)

        logits = model(x_img, x_meta)
        self.assertEqual(logits.shape, (2, NUM_CLASSES))

        # Backward pass gradient verification
        loss = logits.sum()
        loss.backward()
        self.assertIsNotNone(x_img.grad)
        self.assertIsNotNone(x_meta.grad)

    def test_dual_input_onnx_export_and_runtime_parity(self):
        """Tests exporting UniversalFusionWrapper to dual-input ONNX and verifying with onnxruntime."""
        import onnxruntime as ort

        model = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES, meta_dim=6)
        model.eval()

        dummy_img = torch.randn(1, 3, 512, 512, dtype=torch.float32)
        dummy_meta = torch.randn(1, 6, dtype=torch.float32)

        with tempfile.NamedTemporaryFile(suffix=".onnx") as tmp:
            onnx_path = tmp.name
            torch.onnx.export(
                model,
                (dummy_img, dummy_meta),
                onnx_path,
                export_params=True,
                opset_version=18,
                do_constant_folding=True,
                input_names=["image", "meta"],
                output_names=["logits"],
                dynamic_axes={
                    "image": {0: "batch_size"},
                    "meta": {0: "batch_size"},
                    "logits": {0: "batch_size"},
                },
            )

            # Test inference session
            sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            inputs = {inp.name: dummy_img.numpy() if "image" in inp.name else dummy_meta.numpy() for inp in sess.get_inputs()}
            ort_out = sess.run(None, inputs)[0]

            with torch.no_grad():
                torch_out = model(dummy_img, dummy_meta).numpy()

            max_diff = float(np.max(np.abs(torch_out - ort_out)))
            self.assertLess(max_diff, 1e-4)

    def test_yolo_tight_contour_extraction(self):
        """Tests that large star_trail boxes extract tight stellar contours on tile_u8."""
        large_box = {
            "type": "box",
            "label": "star_trail",
            "x": 0.0,
            "y": 0.0,
            "width": 300.0,
            "height": 300.0,
        }

        tile_u8 = np.zeros((512, 512, 3), dtype=np.uint8)
        # Put 2 distinct bright stars inside the box
        tile_u8[50:60, 50:60, :] = 255
        tile_u8[120:130, 120:130, :] = 250

        segments = extract_tile_yolo_segments([large_box], tx=0, ty=0, tile_size=512, tile_u8=tile_u8)
        self.assertGreaterEqual(len(segments), 1)
        for seg in segments:
            parts = seg.split()
            cid = int(parts[0])
            self.assertEqual(cid, CLASSES.index("star_trail"))
            # Polygon vertices should have at least 3 points (6 floats + 1 class id = >= 7 elements)
            self.assertGreaterEqual(len(parts), 7)

    def test_yolo_star_contour_cap_top_30(self):
        """Verifies that dense star fields are capped at most 30 star contours per tile."""
        large_box = {
            "type": "box",
            "label": "star_trail",
            "x": 0.0,
            "y": 0.0,
            "width": 512.0,
            "height": 512.0,
        }
        tile_u8 = np.zeros((512, 512, 3), dtype=np.uint8)
        # Paint 64 distinct bright star blobs on an 8x8 grid
        for r in range(8):
            for c in range(8):
                y0 = 20 + r * 60
                x0 = 20 + c * 60
                tile_u8[y0 : y0 + 8, x0 : x0 + 8, :] = 250

        segments = extract_tile_yolo_segments([large_box], tx=0, ty=0, tile_size=512, tile_u8=tile_u8)
        self.assertEqual(len(segments), 30)

    def test_polygon_overlap_threshold_differentiation(self):
        """
        Tests v3 overlap thresholds:
        - <10% area for obstruction/cloud: skipped for both YOLO and CNN
        - 10%..19% area for obstruction/cloud: emitted for YOLO, but CNN label remains 0.0
        - >=20% area for obstruction/cloud: emitted for YOLO and CNN label = 1.0
        """
        # 1. Tiny 5% obstruction box (114x114 = 12,996 px ~ 4.95% of 512x512)
        tiny_obs = {"type": "box", "label": "obstruction", "x": 0.0, "y": 0.0, "width": 114.0, "height": 114.0}
        self.assertEqual(len(extract_tile_yolo_segments([tiny_obs], tx=0, ty=0, tile_size=512)), 0)

        # 2. Medium 15% obstruction box (200x200 = 40,000 px ~ 15.26% of 512x512)
        med_obs = {"type": "box", "label": "obstruction", "x": 0.0, "y": 0.0, "width": 200.0, "height": 200.0}
        self.assertEqual(len(extract_tile_yolo_segments([med_obs], tx=0, ty=0, tile_size=512)), 1)

        # 3. Verify CNN binary label assignment in _slice_frame_array
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "dataset"
            rgb_f32 = np.full((512, 512, 3), 0.04, dtype=np.float32)

            # 15% overlap -> CNN label for obstruction must be 0.0
            recs_15 = _slice_frame_array(
                rgb_f32=rgb_f32,
                boxes=[med_obs],
                pixel_scale=2.0,
                fits_path=Path("test15.fits"),
                out_dir=out_dir,
                tile_prefix="t15",
                is_val=True,
            )
            obs_idx = CLASSES.index("obstruction")
            self.assertEqual(recs_15[0]["labels"][obs_idx], 0.0)
            self.assertEqual(len(recs_15[0]["yolo_segments"]), 1)

            # 25% overlap (256x256 = 65,536 px = 25% of 512x512) -> CNN label must be 1.0
            large_obs = {"type": "box", "label": "obstruction", "x": 0.0, "y": 0.0, "width": 256.0, "height": 256.0}
            recs_25 = _slice_frame_array(
                rgb_f32=rgb_f32,
                boxes=[large_obs],
                pixel_scale=2.0,
                fits_path=Path("test25.fits"),
                out_dir=out_dir,
                tile_prefix="t25",
                is_val=True,
            )
            self.assertEqual(recs_25[0]["labels"][obs_idx], 1.0)
            self.assertEqual(len(recs_25[0]["yolo_segments"]), 1)

    def test_per_class_optimal_threshold_calibration(self):
        """Tests that compute_metrics calibrates per-class thresholds and iter_manager exports them."""
        # Create validation predictions where class 3 (obstruction) has false positives at 0.50..0.70
        # and true positives at 0.85, so optimal threshold for obstruction is > 0.70
        N = 20
        preds = np.full((N, NUM_CLASSES), 0.05, dtype=np.float32)
        targets = np.zeros((N, NUM_CLASSES), dtype=np.float32)

        obs_idx = CLASSES.index("obstruction")
        # 5 true positives with prob 0.82
        preds[:5, obs_idx] = 0.82
        targets[:5, obs_idx] = 1.0
        # 5 false positives with prob 0.66 (would fail at threshold=0.50, succeed at threshold>=0.67)
        preds[5:10, obs_idx] = 0.66
        targets[5:10, obs_idx] = 0.0

        metrics = compute_metrics(preds, targets, threshold=0.50)
        self.assertIn("optimal_thresholds", metrics)
        self.assertIn("calibrated_macro_f1", metrics)
        opt_t = metrics["optimal_thresholds"]
        self.assertGreater(opt_t["obstruction"], 0.65)
        self.assertGreater(metrics["calibrated_macro_f1"], metrics["macro_f1"])

        # Verify iter_manager extracts optimal_thresholds from checkpoint
        with tempfile.TemporaryDirectory() as tmpdir:
            pt_path = Path(tmpdir) / "best_model.pt"
            torch.save({
                "epoch": 5,
                "model_name": "resnet18",
                "metrics": metrics,
                "optimal_thresholds": opt_t,
                "calibrated_macro_f1": metrics["calibrated_macro_f1"],
            }, pt_path)
            info = extract_cnn_checkpoint_info(pt_path)
            self.assertIn("optimal_thresholds", info)
            self.assertEqual(info["optimal_thresholds"]["obstruction"], opt_t["obstruction"])
            self.assertEqual(info["calibrated_macro_f1"], metrics["calibrated_macro_f1"])

    def test_clean_sky_vignetting_augmentation(self):
        """Tests that AstroPatchDataset applies synthetic vignetting to ~15% of clean sky tiles while preserving clean labels."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            ds_dir = base_dir / "dataset"
            f32_dir = ds_dir / "tiles_f32"
            f32_dir.mkdir(parents=True, exist_ok=True)

            # Save a uniform 0.50 clean tile
            npy_path = f32_dir / "clean_tile.npy"
            np.save(npy_path, np.full((3, 512, 512), 0.50, dtype=np.float32))

            manifest_path = ds_dir / "train_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as fp:
                json.dump([{
                    "tile_id": "clean_tile",
                    "f32_path": "dataset/tiles_f32/clean_tile.npy",
                    "img_path": "dataset/tiles_img/clean_tile.png",
                    "labels": [0.0] * NUM_CLASSES,
                    "meta": [0.4, 1.0, 0.33, 0.2, 0.2, 0.1],
                }], fp)

            ds = AstroPatchDataset(manifest_path, base_dir, input_mode="f32", augment=True)
            torch.manual_seed(0)
            vignetted_seen = False
            for _ in range(40):
                tensor, meta_t, labels_t = ds[0]
                self.assertEqual(float(labels_t.sum().item()), 0.0)
                self.assertEqual(tensor.shape, (3, 512, 512))
                # If vignetting triggered, corners/edges drop well below 0.45 (noise alone is <= 0.02)
                if float(tensor.min().item()) < 0.45:
                    vignetted_seen = True
                    break
            self.assertTrue(vignetted_seen, "Expected synthetic vignetting to trigger on clean sky tile within 40 draws")

    def test_synthetic_obstruction_no_blue_cast_and_coverage(self):
        """
        Verifies that on a realistic OSC frame where Blue linear median is lower than Red/Green,
        synthetic obstructions do not turn bright blue after unlinked AutoSTF and cover >= 20% of the tile.
        """
        np.random.seed(123)
        random_state = np.random.RandomState(123)
        h, w = 512, 512
        # Realistic OSC channel medians: R=0.045, G=0.060, B=0.015
        osc_tile = np.zeros((h, w, 3), dtype=np.float32)
        osc_tile[:, :, 0] = random_state.normal(0.045, 0.002, (h, w))
        osc_tile[:, :, 1] = random_state.normal(0.060, 0.0025, (h, w))
        osc_tile[:, :, 2] = random_state.normal(0.015, 0.001, (h, w))
        osc_tile = np.clip(osc_tile, 0.0, 1.0)

        frame_bg_med = float(np.median(osc_tile))
        frame_mad = 0.002

        for _ in range(10):
            mod_tile, cname, annot = inject_synthetic_obstruction(osc_tile, frame_bg_med, frame_mad)
            self.assertEqual(cname, "obstruction")
            # Check polygon coverage >= 20%
            mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array(annot["points"], dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
            cov = float(np.count_nonzero(mask)) / float(h * w)
            self.assertGreaterEqual(cov, 0.20)

            # Stretch with unlinked AutoSTF and verify Blue inside polygon is not blown out above Red/Green
            stf_u8 = to_stf_u8(mod_tile, rgb_linked=False)
            inside = mask > 0
            mean_r = float(np.mean(stf_u8[:, :, 0][inside]))
            mean_g = float(np.mean(stf_u8[:, :, 1][inside]))
            mean_b = float(np.mean(stf_u8[:, :, 2][inside]))
            # Blue should never dominate Red/Green by > 25 u8 levels
            self.assertLessEqual(mean_b, max(mean_r, mean_g) + 25.0)


if __name__ == "__main__":
    unittest.main()
