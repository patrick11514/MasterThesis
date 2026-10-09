"""
Unit tests for new features: EarlyStopping, Dataset Pre-Analyzer, and Annotator API.
"""

from pathlib import Path
import tempfile
import json
import unittest

import sys
training_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(training_dir))
sys.path.insert(0, str(training_dir / "annotator"))

from train import EarlyStopping
from dataset_analyzer import analyze_dataset
from fits_utils import CLASSES, CLASS_HEX_COLORS
import app
from fastapi.testclient import TestClient


class TestNewFeatures(unittest.TestCase):
    def test_early_stopping_max_mode(self):
        """Tests EarlyStopping in maximizing mode (e.g. macro_f1)."""
        es = EarlyStopping(patience=3, min_delta=0.01, mode="max")

        self.assertFalse(es.step(0.50, epoch=1))
        self.assertEqual(es.best_epoch, 1)

        # Improvement
        self.assertFalse(es.step(0.60, epoch=2))
        self.assertEqual(es.best_epoch, 2)
        self.assertEqual(es.counter, 0)

        # No improvement epoch 3 (counter = 1)
        self.assertFalse(es.step(0.59, epoch=3))
        self.assertEqual(es.counter, 1)

        # No improvement epoch 4 (counter = 2)
        self.assertFalse(es.step(0.58, epoch=4))
        self.assertEqual(es.counter, 2)

        # No improvement epoch 5 (counter = 3 >= patience -> triggers early stop)
        self.assertTrue(es.step(0.57, epoch=5))
        self.assertTrue(es.early_stop)
        self.assertEqual(es.best_epoch, 2)
        self.assertAlmostEqual(es.best_score, 0.60)

    def test_early_stopping_min_mode(self):
        """Tests EarlyStopping in minimizing mode (e.g. val_loss)."""
        es = EarlyStopping(patience=2, min_delta=0.01, mode="min")

        self.assertFalse(es.step(1.0, epoch=1))
        self.assertFalse(es.step(0.8, epoch=2))
        self.assertEqual(es.best_epoch, 2)

        # Counter 1
        self.assertFalse(es.step(0.81, epoch=3))
        # Counter 2 -> trigger
        self.assertTrue(es.step(0.82, epoch=4))
        self.assertEqual(es.best_epoch, 2)
        self.assertAlmostEqual(es.best_score, 0.8)

    def test_dataset_analyzer_synthetic(self):
        """Tests analyze_dataset on a synthetic temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            # Create 2 fake fits files
            f1 = p / "test1.fits"
            f2 = p / "test2.fits"
            f1.touch()
            f2.touch()

            # Annotation 1
            with open(p / "test1.json", "w", encoding="utf-8") as fp:
                json.dump({
                    "file_name": "test1.fits",
                    "width": 1000,
                    "height": 1000,
                    "boxes": [
                        {"id": "b1", "label": "satellite_streak", "type": "line", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
                        {"id": "b2", "label": "cloud", "type": "polygon", "points": [[0,0],[10,0],[10,10]]},
                    ]
                }, fp)

            # Annotation 2: clean sky
            with open(p / "test2.json", "w", encoding="utf-8") as fp:
                json.dump({
                    "file_name": "test2.fits",
                    "width": 1000,
                    "height": 1000,
                    "boxes": [],
                    "is_clean": True,
                }, fp)

            res = analyze_dataset(p, target_min_samples=10)
            s = res["summary"]
            self.assertEqual(s["total_fits"], 2)
            self.assertEqual(s["annotated_frames"], 2)
            self.assertEqual(s["clean_frames"], 1)
            self.assertEqual(s["defective_frames"], 1)
            self.assertEqual(s["total_annotations"], 2)

            ch = res["class_health"]
            self.assertEqual(ch["satellite_streak"]["count"], 1)
            self.assertEqual(ch["cloud"]["count"], 1)
            self.assertEqual(ch["airplane"]["count"], 0)

            # Recommendations should identify deficits
            recs = res["recommendations"]
            self.assertTrue(len(recs) >= 3)

    def test_annotator_api_classes_and_models(self):
        """Tests FastAPI /api/classes and /api/models endpoints."""
        client = TestClient(app.app)

        res_cls = client.get("/api/classes")
        self.assertEqual(res_cls.status_code, 200)
        data_cls = res_cls.json()
        self.assertIn("classes", data_cls)
        self.assertIn("satellite_streak", data_cls["classes"])
        self.assertIn("colors", data_cls)

        res_mod = client.get("/api/models")
        self.assertEqual(res_mod.status_code, 200)
        data_mod = res_mod.json()
        self.assertIn("models", data_mod)

    def test_calculate_iou(self):
        """Tests box IoU helper function."""
        # Non-overlapping
        self.assertEqual(app.calculate_iou([0, 0, 10, 10], [20, 20, 30, 30]), 0.0)
        # Identical
        self.assertAlmostEqual(app.calculate_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        # 50% overlap approx
        iou = app.calculate_iou([0, 0, 10, 10], [5, 0, 15, 10])
        self.assertAlmostEqual(iou, 50.0 / 150.0, places=3)


    def test_favorite_endpoint(self):
        """Tests /api/favorite endpoint toggle and file listing reflection."""
        client = TestClient(app.app)
        with tempfile.TemporaryDirectory() as tmp_dir:
            fits_path = Path(tmp_dir) / "test_frame.fits"
            fits_path.write_bytes(b"FITS_FAKE")

            # Initially not favorite
            res_list = client.get(f"/api/files?dir_path={tmp_dir}")
            self.assertEqual(res_list.status_code, 200)
            files = res_list.json()["files"]
            self.assertEqual(len(files), 1)
            self.assertFalse(files[0]["favorite"])

            # Toggle to favorite
            res_fav = client.post(f"/api/favorite?path={fits_path}&favorite=true")
            self.assertEqual(res_fav.status_code, 200)
            self.assertTrue(res_fav.json()["favorite"])

            # Verify reflected in /api/files
            res_list2 = client.get(f"/api/files?dir_path={tmp_dir}")
            self.assertEqual(res_list2.status_code, 200)
            self.assertTrue(res_list2.json()["files"][0]["favorite"])

            # Verify reflected in /api/annotations
            res_annot = client.get(f"/api/annotations?path={fits_path}")
            self.assertEqual(res_annot.status_code, 200)
            self.assertTrue(res_annot.json()["favorite"])

    def test_annot_mtime_sorting_api(self):
        """Tests that annot_mtime is returned by /api/files and updated upon save."""
        client = TestClient(app.app)
        with tempfile.TemporaryDirectory() as tmp_dir:
            f1 = Path(tmp_dir) / "frame1.fits"
            f2 = Path(tmp_dir) / "frame2.fits"
            f1.write_bytes(b"FITS_1")
            f2.write_bytes(b"FITS_2")

            # Check unannotated mtimes are 0.0
            res = client.get(f"/api/files?dir_path={tmp_dir}")
            files = res.json()["files"]
            self.assertEqual(files[0]["annot_mtime"], 0.0)
            self.assertEqual(files[1]["annot_mtime"], 0.0)

            # Save annotation for frame1
            payload = {
                "file_name": "frame1.fits",
                "width": 100,
                "height": 100,
                "boxes": [],
                "is_clean": True,
            }
            save_res = client.post(f"/api/annotations?path={f1}", json=payload)
            self.assertEqual(save_res.status_code, 200)
            self.assertIn("annot_mtime", save_res.json())
            self.assertGreater(save_res.json()["annot_mtime"], 0.0)

            # Check /api/files now has positive mtime for frame1
            res2 = client.get(f"/api/files?dir_path={tmp_dir}")
            files2 = {f["name"]: f for f in res2.json()["files"]}
            self.assertGreater(files2["frame1.fits"]["annot_mtime"], 0.0)
            self.assertEqual(files2["frame2.fits"]["annot_mtime"], 0.0)


if __name__ == "__main__":
    unittest.main()
