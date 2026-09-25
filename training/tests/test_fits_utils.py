"""
Unit tests for FITS Utilities, AutoSTF, and Unified 3-Channel RGB Contract.
"""

from pathlib import Path
import unittest
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fits_utils import (
    mtf_scalar,
    mtf_array,
    calculate_channel_stats,
    calculate_stf,
    to_auto_stf_f32,
    to_asinh_f32,
    to_stf_u8,
    load_fits_unified_rgb,
    CLASSES,
)


class TestFitsUtils(unittest.TestCase):
    def test_mtf_identity(self):
        """MTF with midtones=0.5 should be the identity function."""
        for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
            self.assertAlmostEqual(mtf_scalar(0.5, val), val, places=5)

    def test_mtf_boundary(self):
        """MTF must always clamp boundaries exactly."""
        for m in [0.1, 0.25, 0.5, 0.8]:
            self.assertEqual(mtf_scalar(m, 0.0), 0.0)
            self.assertEqual(mtf_scalar(m, 1.0), 1.0)

    def test_mtf_array(self):
        arr = np.linspace(0.0, 1.0, 100, dtype=np.float32)
        out = mtf_array(0.25, arr)
        self.assertEqual(out.shape, arr.shape)
        self.assertTrue(np.all(out >= 0.0))
        self.assertTrue(np.all(out <= 1.0))
        # MTF with m < 0.5 should brighten midtones
        self.assertGreater(out[25], arr[25])

    def test_calculate_channel_stats(self):
        data = np.array([10.0, 12.0, 12.0, 14.0, 15.0, 16.0, 100.0], dtype=np.float32)
        med, mad = calculate_channel_stats(data, stride=1)
        self.assertAlmostEqual(med, 14.0, places=3)
        self.assertGreater(mad, 0.0)

    def test_stf_calculation_and_transforms(self):
        # Create a synthetic 100x100x3 dark sky image with background ~ 0.02
        np.random.seed(42)
        synth_rgb = np.random.normal(loc=0.02, scale=0.003, size=(100, 100, 3)).astype(np.float32)
        # Add some bright star pixels
        synth_rgb[20, 20, :] = 0.95
        synth_rgb[50, 50, :] = 0.80
        synth_rgb = np.clip(synth_rgb, 0.0, 1.0)

        # Test continuous AutoSTF
        stf_f32 = to_auto_stf_f32(synth_rgb)
        self.assertEqual(stf_f32.shape, (100, 100, 3))
        self.assertEqual(stf_f32.dtype, np.float32)
        self.assertTrue(np.all(stf_f32 >= 0.0))
        self.assertTrue(np.all(stf_f32 <= 1.0))
        # Sky background should be lifted to ~0.25
        bg_mean = float(np.mean(stf_f32))
        self.assertGreater(bg_mean, 0.15)
        self.assertLess(bg_mean, 0.35)

        # Test Asinh stretch
        asinh_f32 = to_asinh_f32(synth_rgb)
        self.assertEqual(asinh_f32.shape, (100, 100, 3))
        self.assertEqual(asinh_f32.dtype, np.float32)

        # Test 8-bit STF
        stf_u8 = to_stf_u8(synth_rgb)
        self.assertEqual(stf_u8.shape, (100, 100, 3))
        self.assertEqual(stf_u8.dtype, np.uint8)

    def test_real_fits_load_if_present(self):
        test_fits_dir = Path(__file__).resolve().parent.parent.parent / "test_fits"
        fits_candidates = list(test_fits_dir.glob("*.fits"))
        if not fits_candidates:
            self.skipTest("No test FITS found in test_fits/")

        sample_file = fits_candidates[0]
        rgb_f32, meta = load_fits_unified_rgb(sample_file)

        # Verify Unified 3-Channel RGB Contract
        self.assertEqual(rgb_f32.ndim, 3)
        self.assertEqual(rgb_f32.shape[2], 3)
        self.assertEqual(rgb_f32.dtype, np.float32)
        self.assertTrue(np.all(rgb_f32 >= 0.0))
        self.assertTrue(np.all(rgb_f32 <= 1.0))
        self.assertIn("file_name", meta)
        self.assertEqual(meta["file_name"], sample_file.name)


if __name__ == "__main__":
    unittest.main()
