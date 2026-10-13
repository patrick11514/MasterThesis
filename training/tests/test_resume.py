"""
Unit tests for Model Checkpoint Resumption and Fine-tuning in AstroGrader.
"""

import sys
from pathlib import Path
import tempfile
import unittest

import torch
import torch.nn as nn

# Ensure training root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from models.cnn_zoo import build_model, NUM_CLASSES


class TestResumeCheckpoint(unittest.TestCase):
    def test_checkpoint_save_and_reload(self):
        """Verify that saving model state dict and reloading it into a fresh instance reproduces exact parameters."""
        model_orig = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
        
        # Perturb one parameter so it's not default initialized
        with torch.no_grad():
            list(model_orig.parameters())[0].add_(0.5)

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "test_best.pt"
            torch.save({
                "epoch": 7,
                "model_name": "astronet",
                "state_dict": model_orig.state_dict(),
                "metrics": {"macro_f1": 0.885},
            }, ckpt_path)

            self.assertTrue(ckpt_path.exists())

            # Load checkpoint in fresh model instance
            model_new = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
            ckpt_data = torch.load(ckpt_path, map_location="cpu")
            state_dict = ckpt_data["state_dict"]

            model_new.load_state_dict(state_dict)

            # Compare all weights
            for p1, p2 in zip(model_orig.parameters(), model_new.parameters()):
                self.assertTrue(torch.allclose(p1, p2))

    def test_flexible_head_resumption(self):
        """Verify that loading weights when classes match or differ handles key filtering gracefully."""
        model_orig = build_model("resnet18", pretrained=False, num_classes=NUM_CLASSES)
        model_dict = model_orig.state_dict()

        # Simulate checkpoint saved with 5 classes instead of 6
        old_classes = 5
        model_old = build_model("resnet18", pretrained=False, num_classes=old_classes)
        old_dict = model_old.state_dict()

        # Filter out mismatching layer keys
        filtered_dict = {}
        for k, v in old_dict.items():
            if k in model_dict and model_dict[k].shape == v.shape:
                filtered_dict[k] = v

        # Feature extractor layers should match
        self.assertIn("conv1.weight", filtered_dict)
        # Final linear classifier layer should be filtered out due to shape mismatch
        self.assertNotIn("fc.weight", filtered_dict)

        # Update model dict with matching layers
        model_dict.update(filtered_dict)
        model_orig.load_state_dict(model_dict)
        self.assertEqual(model_orig.fc.out_features, NUM_CLASSES)


if __name__ == "__main__":
    unittest.main()
