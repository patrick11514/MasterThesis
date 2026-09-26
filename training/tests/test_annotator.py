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
            self.assertEqual(len(get_data["boxes"]), 3)
            self.assertTrue(get_data.get("global_cloud"))
            self.assertEqual(get_data["boxes"][2]["type"], "polygon")
            self.assertEqual(len(get_data["boxes"][2]["points"]), 3)

            # Check generated YOLO TXT file
            txt_file = fake_fits.with_suffix(".txt")
            self.assertTrue(txt_file.exists())
            txt_content = txt_file.read_text().strip().split("\n")
            self.assertEqual(len(txt_content), 3)


if __name__ == "__main__":
    unittest.main()
