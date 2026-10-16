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
        self.assertIn("visual_extractor.0.weight", filtered_dict)
        # Final linear classifier layer should be filtered out due to shape mismatch
        self.assertNotIn("classifier.3.weight", filtered_dict)

        # Update model dict with matching layers
        model_dict.update(filtered_dict)
        model_orig.load_state_dict(model_dict)
        self.assertEqual(model_orig.classifier[3].out_features, NUM_CLASSES)

    def test_last_model_state_resumption(self):
        """Verify that optimizer, scheduler, early stopper, and history can be saved and restored from last_model.pt."""
        model = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=10)

        # Take one step so optimizer has state
        loss = sum(p.sum() for p in model.parameters())
        loss.backward()
        optimizer.step()
        scheduler.step()

        with tempfile.TemporaryDirectory() as tmpdir:
            last_ckpt_path = Path(tmpdir) / "last_model.pt"
            history = [{"epoch": 1, "macro_f1": 0.75, "clean_sky_accuracy": 0.88}]
            torch.save({
                "epoch": 1,
                "target_epochs": 10,
                "model_name": "astronet",
                "state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "early_stopper": {"counter": 2, "best_score": 0.82, "best_epoch": 1},
                "best_f1": 0.82,
                "metrics": {"macro_f1": 0.75},
                "history": history,
            }, last_ckpt_path)

            self.assertTrue(last_ckpt_path.exists())

            # Fresh model and optimizer
            model_new = build_model("astronet", pretrained=False, num_classes=NUM_CLASSES)
            opt_new = torch.optim.AdamW(model_new.parameters(), lr=1e-3, weight_decay=1e-4)
            sched_new = torch.optim.lr_scheduler.CosineAnnealingLR(opt_new, T_max=10)

            ckpt_loaded = torch.load(last_ckpt_path, map_location="cpu")
            model_new.load_state_dict(ckpt_loaded["state_dict"])
            opt_new.load_state_dict(ckpt_loaded["optimizer_state_dict"])
            sched_new.load_state_dict(ckpt_loaded["scheduler_state_dict"])

            self.assertEqual(ckpt_loaded["epoch"], 1)
            self.assertEqual(ckpt_loaded["early_stopper"]["counter"], 2)
            self.assertEqual(ckpt_loaded["best_f1"], 0.82)
            self.assertEqual(len(ckpt_loaded["history"]), 1)
            # Verify learning rates match
            self.assertEqual(opt_new.param_groups[0]["lr"], optimizer.param_groups[0]["lr"])

    def test_session_manifest_and_resolution(self):
        """Tests session manifest saving, listing, and resolution helpers."""
        from master_train import (
            get_all_sessions,
            resolve_session,
            save_session_manifest,
            parse_resume_model_overrides,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            s1_dir = sessions_dir / "2026-10-15_10-00-00"
            s2_dir = sessions_dir / "2026-10-16_09-00-00"

            save_session_manifest(s1_dir, {
                "session_id": "2026-10-15_10-00-00",
                "created_at": "2026-10-15T10:00:00",
                "status": "completed",
                "models": {
                    "astronet": {"status": "completed", "macro_f1": 0.91},
                    "resnet18": {"status": "completed", "macro_f1": 0.93},
                },
            })

            save_session_manifest(s2_dir, {
                "session_id": "2026-10-16_09-00-00",
                "created_at": "2026-10-16T09:00:00",
                "status": "in_progress",
                "models": {
                    "astronet": {"status": "completed", "macro_f1": 0.92},
                    "resnet18": {"status": "in_progress", "epochs_completed": 5, "target_epochs": 20},
                },
            })

            sessions = get_all_sessions(sessions_dir)
            self.assertEqual(len(sessions), 2)
            # Should be sorted newest first
            self.assertEqual(sessions[0]["session_id"], "2026-10-16_09-00-00")

            # Resolve 'latest'
            latest_id, latest_path = resolve_session("latest", sessions_dir)
            self.assertEqual(latest_id, "2026-10-16_09-00-00")
            self.assertEqual(latest_path, s2_dir)

            # Resolve exact
            exact_id, exact_path = resolve_session("2026-10-15_10-00-00", sessions_dir)
            self.assertEqual(exact_id, "2026-10-15_10-00-00")
            self.assertEqual(exact_path, s1_dir)

            # Resolve prefix
            pref_id, pref_path = resolve_session("2026-10-15", sessions_dir)
            self.assertEqual(pref_id, "2026-10-15_10-00-00")

            # Test --resume-model parsing
            # Fake a checkpoint file
            fake_ckpt = s1_dir / "astronet_f32" / "best_model.pt"
            fake_ckpt.parent.mkdir(parents=True, exist_ok=True)
            fake_ckpt.write_text("dummy")

            overrides = parse_resume_model_overrides(["astronet=2026-10-15"], sessions_dir)
            self.assertIn("astronet", overrides)
            self.assertEqual(overrides["astronet"], str(fake_ckpt.resolve()))


if __name__ == "__main__":
    unittest.main()
