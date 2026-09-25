"""
Unit tests for Model Zoo architectures, Metric computation, and Tiling.
"""

from pathlib import Path
import unittest
import numpy as np
import torch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from models.cnn_zoo import build_model, NUM_CLASSES
from prep_dataset import box_intersects_tile
from train import compute_metrics


class TestPipeline(unittest.TestCase):
    def test_astronet_forward(self):
        """Tests pure AstroNet from scratch forward pass."""
        model = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
        model.eval()

        dummy_batch = torch.randn(2, 3, 512, 512, dtype=torch.float32)
        with torch.no_grad():
            logits = model(dummy_batch)

        self.assertEqual(logits.shape, (2, NUM_CLASSES))
        self.assertEqual(logits.dtype, torch.float32)

    def test_mobilenet_v3_forward(self):
        """Tests MobileNetV3 architecture forward pass."""
        model = build_model("mobilenet_v3", pretrained=False, num_classes=NUM_CLASSES)
        model.eval()

        dummy_batch = torch.randn(2, 3, 512, 512, dtype=torch.float32)
        with torch.no_grad():
            logits = model(dummy_batch)

        self.assertEqual(logits.shape, (2, NUM_CLASSES))

    def test_box_intersects_tile(self):
        """Tests bounding box intersection logic with tile window."""
        box = {"x": 100.0, "y": 100.0, "width": 50.0, "height": 50.0}

        # Tile completely covering the box
        self.assertTrue(box_intersects_tile(box, tile_x=0, tile_y=0, tile_size=512))

        # Tile completely far away from the box
        self.assertFalse(box_intersects_tile(box, tile_x=600, tile_y=600, tile_size=512))

        # Tile overlapping partially
        self.assertTrue(box_intersects_tile(box, tile_x=120, tile_y=120, tile_size=512))

    def test_metric_computations(self):
        """Tests multi-label precision, recall, and clean sky accuracy."""
        # 3 samples, 5 classes
        targets = np.array([
            [1, 0, 0, 0, 0],  # satellite
            [0, 0, 1, 0, 0],  # cloud
            [0, 0, 0, 0, 0],  # clean sky
        ])

        # Predicted probabilities
        preds = np.array([
            [0.9, 0.1, 0.1, 0.0, 0.0],  # correct satellite
            [0.2, 0.1, 0.8, 0.0, 0.0],  # correct cloud
            [0.1, 0.1, 0.1, 0.0, 0.0],  # correct clean sky
        ])

        metrics = compute_metrics(preds, targets, threshold=0.5)
        self.assertEqual(metrics["satellite_streak_precision"], 1.0)
        self.assertEqual(metrics["cloud_precision"], 1.0)
        self.assertEqual(metrics["clean_sky_accuracy"], 1.0)
        self.assertEqual(metrics["exact_match_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
