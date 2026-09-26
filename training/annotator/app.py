"""
Minimalist FastAPI backend for FITS Image Tagging and Defect Annotation.
Serves interactive canvas UI, renders real-time AutoSTF stretched previews,
and saves multi-label bounding boxes in JSON and YOLO format.
"""

import io
import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fits_utils import load_fits_unified_rgb, to_stf_u8

app = FastAPI(title="AstroGrader Minimalist FITS Annotator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cache current loaded fits image: {path: (rgb_f32, metadata)}
IMAGE_CACHE = {}


class BoundingBox(BaseModel):
    id: str
    label: str  # satellite_streak, airplane, cloud, obstruction, star_trail
    type: str = "box"  # "box", "line", "polygon"
    x: float = 0.0     # pixel coords on full image
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    points: Optional[List[List[float]]] = None  # [[x0, y0], [x1, y1], ...] for polygon


class FrameAnnotation(BaseModel):
    file_name: str
    width: int
    height: int
    global_star_trailing: bool = False
    global_cloud: bool = False
    is_clean: bool = True
    boxes: List[BoundingBox] = []


CLASSES = [
    "satellite_streak",
    "airplane",
    "cloud",
    "obstruction",
    "star_trail",
]


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/files")
def list_fits_files(dir_path: str = Query(..., description="Directory containing FITS files")):
    p = Path(dir_path).resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {dir_path}")

    extensions = ("*.fits", "*.fit", "*.FITS", "*.FIT")
    files = []
    for ext in extensions:
        files.extend(list(p.glob(ext)))

    files = sorted(set(files))
    result = []
    for f in files:
        annot_json = f.with_suffix(".json")
        result.append({
            "name": f.name,
            "path": str(f),
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
            "annotated": annot_json.exists(),
        })

    return {"directory": str(p), "files": result}


@app.get("/api/preview")
def get_fits_preview(
    path: str = Query(...),
    shadows: float = Query(-2.80),
    target_bg: float = Query(0.25),
    mode: str = Query("stf"),
    linked: bool = Query(False),
    max_dim: int = Query(2048, description="Max width/height for display downscale"),
):
    fits_path = Path(path).resolve()
    if not fits_path.exists():
        raise HTTPException(status_code=404, detail="FITS file not found")

    cache_key = str(fits_path)
    if cache_key in IMAGE_CACHE:
        rgb_f32, meta = IMAGE_CACHE[cache_key]
    else:
        try:
            rgb_f32, meta = load_fits_unified_rgb(fits_path)
            # Keep cache small: max 3 entries
            if len(IMAGE_CACHE) >= 3:
                IMAGE_CACHE.pop(next(iter(IMAGE_CACHE)))
            IMAGE_CACHE[cache_key] = (rgb_f32, meta)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read FITS: {str(e)}")

    # Downscale for interactive web canvas if image is massive (e.g. 6k x 4k)
    h, w, _ = rgb_f32.shape
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        # Fast nearest/area downscale
        rgb_preview = rgb_f32[::int(1/scale), ::int(1/scale)]
    else:
        rgb_preview = rgb_f32
        scale = 1.0

    stf_u8 = to_stf_u8(rgb_preview, shadows_clipping=shadows, target_bg=target_bg, rgb_linked=linked, mode=mode)

    pil_img = Image.fromarray(stf_u8, mode="RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=88)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="image/jpeg",
        headers={
            "X-Original-Width": str(w),
            "X-Original-Height": str(h),
            "X-Preview-Scale": str(scale),
        },
    )


@app.get("/api/annotations")
def get_annotations(path: str = Query(...)):
    fits_path = Path(path).resolve()
    json_path = fits_path.with_suffix(".json")
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read annotations: {e}")

    # Return empty default
    return {
        "file_name": fits_path.name,
        "width": 0,
        "height": 0,
        "global_star_trailing": False,
        "global_cloud": False,
        "is_clean": True,
        "boxes": [],
    }


@app.post("/api/annotations")
def save_annotations(path: str = Query(...), annot: FrameAnnotation = ...):
    fits_path = Path(path).resolve()
    json_path = fits_path.with_suffix(".json")
    txt_path = fits_path.with_suffix(".txt")

    # Clean status: if any box exists or global flags are checked, not clean
    if len(annot.boxes) > 0 or annot.global_star_trailing or annot.global_cloud:
        annot.is_clean = False
    else:
        annot.is_clean = True

    # Save rich JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(annot.model_dump(), f, indent=2)

    # Save YOLO format TXT: <class_id> <x_center> <y_center> <width> <height> (normalized 0..1)
    if annot.width > 0 and annot.height > 0:
        lines = []
        for box in annot.boxes:
            if box.label in CLASSES:
                cid = CLASSES.index(box.label)
                if box.type == "polygon" and box.points and len(box.points) >= 3:
                    min_x = min(p[0] for p in box.points)
                    min_y = min(p[1] for p in box.points)
                    max_x = max(p[0] for p in box.points)
                    max_y = max(p[1] for p in box.points)
                    bx, by, bw, bh = min_x, min_y, max(max_x - min_x, 4.0), max(max_y - min_y, 4.0)
                elif box.type == "line" and box.x1 is not None and box.x2 is not None:
                    bx = min(box.x1, box.x2)
                    by = min(box.y1, box.y2)
                    bw = max(abs(box.x2 - box.x1), 4.0)
                    bh = max(abs(box.y2 - box.y1), 4.0)
                else:
                    bx, by, bw, bh = box.x, box.y, box.width, box.height
                xc = (bx + bw / 2.0) / annot.width
                yc = (by + bh / 2.0) / annot.height
                norm_w = bw / annot.width
                norm_h = bh / annot.height
                lines.append(f"{cid} {xc:.6f} {yc:.6f} {norm_w:.6f} {norm_h:.6f}")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    return {"status": "ok", "boxes_count": len(annot.boxes), "is_clean": annot.is_clean}


@app.delete("/api/annotations")
def delete_annotations(path: str = Query(...)):
    fits_path = Path(path).resolve()
    json_path = fits_path.with_suffix(".json")
    txt_path = fits_path.with_suffix(".txt")

    if json_path.exists():
        json_path.unlink()
    if txt_path.exists():
        txt_path.unlink()

    return {"status": "ok", "deleted": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

