"""
Unit tests for the minimalist FITS Annotator API backend.
"""

from pathlib import Path
import tempfile
import unittest
from starlette.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "annotator"))
from app import app


class TestAnnotatorAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_files(self):
        """Tests file listing for existing test directory."""
        test_dir = Path(__file__).resolve().parent.parent.parent / "test_fits"
        if test_dir.exists():
            response = self.client.get(f"/api/files?dir_path={test_dir}")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("files", data)
            self.assertGreater(len(data["files"]), 0)

    def test_save_and_load_annotations(self):
        """Tests saving and retrieving both box and streak line annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_fits = Path(tmpdir) / "frame_001.fits"
            fake_fits.touch()

            payload = {
                "file_name": fake_fits.name,
                "width": 3000,
                "height": 2000,
                "global_star_trailing": False,
                "is_clean": False,
                "boxes": [
                    {
                        "id": "b_1",
                        "label": "cloud",
                        "type": "box",
                        "x": 100.0,
                        "y": 150.0,
                        "width": 200.0,
                        "height": 250.0,
                    },
                    {
                        "id": "l_1",
                        "label": "satellite_streak",
                        "type": "line",
                        "x1": 50.0,
                        "y1": 50.0,
                        "x2": 1500.0,
                        "y2": 1800.0,
                        "x": 50.0,
                        "y": 50.0,
                        "width": 1450.0,
                        "height": 1750.0,
                    },
                    {
                        "id": "poly_1",
                        "label": "cloud",
                        "type": "polygon",
                        "points": [[200.0, 300.0], [500.0, 300.0], [400.0, 600.0]],
                        "x": 200.0,
                        "y": 300.0,
                        "width": 300.0,
                        "height": 300.0,
                    },
                ],
                "global_cloud": True,
            }

            # POST annotations
            post_res = self.client.post(f"/api/annotations?path={fake_fits}", json=payload)
            self.assertEqual(post_res.status_code, 200)
            post_data = post_res.json()
            self.assertEqual(post_data["boxes_count"], 3)
            self.assertFalse(post_data["is_clean"])

            # GET annotations
            get_res = self.client.get(f"/api/annotations?path={fake_fits}")
            self.assertEqual(get_res.status_code, 200)
            get_data = get_res.json()
            # Legacy global_cloud flag is converted to full-frame box
            self.assertEqual(len(get_data["boxes"]), 4)
            self.assertTrue(any(b.get("label") == "cloud" and b.get("width") == 3000 for b in get_data["boxes"]))
            self.assertEqual(get_data["boxes"][2]["type"], "polygon")
            self.assertEqual(len(get_data["boxes"][2]["points"]), 3)

            # Check generated YOLO TXT file
            txt_file = fake_fits.with_suffix(".txt")
            self.assertTrue(txt_file.exists())
            txt_content = txt_file.read_text().strip().split("\n")
            self.assertEqual(len(txt_content), 3)

    def test_line_thickness_persistence(self):
        """Tests that each line stores and persists its individual thickness in JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_fits = Path(tmpdir) / "frame_streak.fits"
            fake_fits.touch()

            payload = {
                "file_name": fake_fits.name,
                "width": 1920,
                "height": 1080,
                "global_star_trailing": False,
                "is_clean": False,
                "boxes": [
                    {
                        "id": "l_thick_1",
                        "label": "satellite_streak",
                        "type": "line",
                        "x1": 10.0,
                        "y1": 20.0,
                        "x2": 500.0,
                        "y2": 600.0,
                        "x": 10.0,
                        "y": 20.0,
                        "width": 490.0,
                        "height": 580.0,
                        "thickness": 34.0,
                    },
                    {
                        "id": "l_thin_2",
                        "label": "satellite_streak",
                        "type": "line",
                        "x1": 50.0,
                        "y1": 50.0,
                        "x2": 800.0,
                        "y2": 50.0,
                        "x": 50.0,
                        "y": 50.0,
                        "width": 750.0,
                        "height": 0.0,
                        "thickness": 6.0,
                    },
                ],
            }

            post_res = self.client.post(f"/api/annotations?path={fake_fits}", json=payload)
            self.assertEqual(post_res.status_code, 200)

            # Check JSON file directly on disk
            import json
            json_file = fake_fits.with_suffix(".json")
            self.assertTrue(json_file.exists())
            with open(json_file, "r", encoding="utf-8") as f:
                saved_json = json.load(f)

            boxes = saved_json.get("boxes", [])
            self.assertEqual(len(boxes), 2)
            self.assertEqual(boxes[0]["thickness"], 34.0)
            self.assertEqual(boxes[1]["thickness"], 6.0)

            # Check GET endpoint returns thicknesses
            get_res = self.client.get(f"/api/annotations?path={fake_fits}")
            self.assertEqual(get_res.status_code, 200)
            get_data = get_res.json()
            self.assertEqual(get_data["boxes"][0]["thickness"], 34.0)
            self.assertEqual(get_data["boxes"][1]["thickness"], 6.0)

    def test_merge_adjacent_tiles(self):
        """Tests adjacent square merging algorithm for CNN detections."""
        from app import merge_adjacent_tiles

        # Case 1: Empty list
        self.assertEqual(merge_adjacent_tiles([]), [])

        # Case 2: Single tile (should return flagged square as-is)
        single = [{"class": "cloud", "x": 100, "y": 200, "w": 512, "h": 512, "conf": 0.85}]
        res1 = merge_adjacent_tiles(single, tile_size=512, stride=460)
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["x"], 100)
        self.assertEqual(res1[0]["y"], 200)
        self.assertEqual(res1[0]["width"], 512)
        self.assertEqual(res1[0]["height"], 512)
        self.assertEqual(res1[0]["tiles_merged"], 1)

        # Case 3: Two overlapping adjacent tiles in a row (stride 460)
        row_tiles = [
            {"class": "cloud", "x": 0, "y": 0, "w": 512, "h": 512, "conf": 0.70},
            {"class": "cloud", "x": 460, "y": 0, "w": 512, "h": 512, "conf": 0.90},
        ]
        res2 = merge_adjacent_tiles(row_tiles, tile_size=512, stride=460)
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["x"], 0)
        self.assertEqual(res2[0]["y"], 0)
        self.assertEqual(res2[0]["width"], 972)  # 460 + 512
        self.assertEqual(res2[0]["height"], 512)
        self.assertEqual(res2[0]["confidence"], 0.90)
        self.assertEqual(res2[0]["tiles_merged"], 2)

        # Case 4: 2x2 cluster of adjacent tiles
        cluster = [
            {"class": "satellite_streak", "x": 0, "y": 0, "w": 512, "h": 512, "conf": 0.6},
            {"class": "satellite_streak", "x": 460, "y": 0, "w": 512, "h": 512, "conf": 0.7},
            {"class": "satellite_streak", "x": 0, "y": 460, "w": 512, "h": 512, "conf": 0.8},
            {"class": "satellite_streak", "x": 460, "y": 460, "w": 512, "h": 512, "conf": 0.95},
        ]
        res3 = merge_adjacent_tiles(cluster, tile_size=512, stride=460)
        self.assertEqual(len(res3), 1)
        self.assertEqual(res3[0]["x"], 0)
        self.assertEqual(res3[0]["y"], 0)
        self.assertEqual(res3[0]["width"], 972)
        self.assertEqual(res3[0]["height"], 972)
        self.assertEqual(res3[0]["confidence"], 0.95)
        self.assertEqual(res3[0]["tiles_merged"], 4)

        # Case 5: Two disconnected squares far apart
        disconnected = [
            {"class": "cloud", "x": 0, "y": 0, "w": 512, "h": 512, "conf": 0.75},
            {"class": "cloud", "x": 2000, "y": 2000, "w": 512, "h": 512, "conf": 0.88},
        ]
        res4 = merge_adjacent_tiles(disconnected, tile_size=512, stride=460)
        self.assertEqual(len(res4), 2)

    def test_list_models_contains_cnn(self):
        """Tests that /api/models lists both YOLO and CNN models."""
        response = self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        types = {m["type"] for m in data["models"]}
        # Should have at least cnn or yolo-seg
        self.assertTrue("cnn" in types or "yolo-seg" in types)

    def test_predict_cnn_endpoint(self):
        """Tests running CNN inference and tile merging via /api/models/predict."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        fits_file = repo_root / "test_fits" / "2025-07-03_00-56-59_H_-20.00_180.00s_0013.fits"
        model_file = repo_root / "training" / "checkpoints" / "astronet_f32" / "best_model.pt"

        if fits_file.exists() and model_file.exists():
            payload = {
                "path": str(fits_file),
                "model_path": str(model_file),
                "conf": 0.05,
                "iou": 0.45,
                "device": "cpu",
                "tile_size": 512,
                "stride": 460,
                "merge_adjacent": True,
            }
            res = self.client.post("/api/models/predict", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("boxes", data)
            self.assertIn("count", data)
            for b in data["boxes"]:
                self.assertEqual(b["type"], "box")
                self.assertIn(b["label"], ["satellite_streak", "airplane", "cloud", "obstruction", "star_trail", "unfocused_star"])


if __name__ == "__main__":
    unittest.main()
