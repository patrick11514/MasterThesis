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

from fits_utils import compute_tile_metadata, CLASSES
from models.cnn_zoo import DualPool2d, UniversalFusionWrapper, build_model, NUM_CLASSES
from synthetic_defects import (
    inject_synthetic_satellite,
    inject_synthetic_airplane,
    inject_synthetic_psf_defect,
    inject_synthetic_obstruction,
    inject_random_synthetic_defect,
)
from prep_dataset import extract_tile_yolo_segments, normalize_legacy_annotations


class TestAstroGraderV2(unittest.TestCase):
    def test_compute_tile_metadata_structure_and_bounds(self):
        """Tests that compute_tile_metadata returns valid 6-element normalized floats."""
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

        # Background median and noise ratios should be around 0.33 when tile stats match frame stats
        self.assertGreater(meta[1], 0.1)
        self.assertLess(meta[1], 2.0)
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


if __name__ == "__main__":
    unittest.main()
