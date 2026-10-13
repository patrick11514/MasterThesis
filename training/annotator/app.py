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
import cv2
import numpy as np
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fits_utils import (
    load_fits_unified_rgb,
    to_stf_u8,
    CLASSES,
    CLASS_HEX_COLORS,
    CLASS_RGB_COLORS,
)
from dataset_analyzer import analyze_dataset

app = FastAPI(title="AstroGrader Minimalist FITS Annotator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Original-Width", "X-Original-Height", "X-Preview-Scale"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cache current loaded fits image: {path: (rgb_f32, metadata)}
IMAGE_CACHE = {}
YOLO_MODEL_CACHE = {}


class BoundingBox(BaseModel):
    id: str
    label: str  # satellite_streak, airplane, cloud, obstruction, star_trail, unfocused_star
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
    confidence: Optional[float] = None


class FrameAnnotation(BaseModel):
    file_name: str
    width: int
    height: int
    global_star_trailing: bool = False
    global_cloud: bool = False
    is_clean: bool = True
    favorite: bool = False
    boxes: List[BoundingBox] = []


class PredictRequest(BaseModel):
    path: str
    model_path: str
    conf: float = 0.25
    iou: float = 0.45
    tile_size: int = 512
    stride: int = 460
    device: Optional[str] = None


@app.get("/api/classes")
def get_classes():
    return {
        "classes": CLASSES,
        "colors": CLASS_HEX_COLORS,
        "rgb_colors": CLASS_RGB_COLORS,
    }


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
        is_annotated = annot_json.exists()
        is_favorite = False
        annot_mtime = 0.0
        if is_annotated:
            try:
                annot_mtime = float(annot_json.stat().st_mtime)
                with open(annot_json, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                    is_favorite = bool(jdata.get("favorite", False))
            except Exception:
                pass

        result.append({
            "name": f.name,
            "path": str(f),
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
            "annotated": is_annotated,
            "annot_mtime": annot_mtime,
            "favorite": is_favorite,
        })

    return {"directory": str(p), "files": result}


@app.post("/api/favorite")
def toggle_favorite(path: str = Query(...), favorite: bool = Query(...)):
    fits_path = Path(path).resolve()
    json_path = fits_path.with_suffix(".json")
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {
            "file_name": fits_path.name,
            "width": 0,
            "height": 0,
            "global_star_trailing": False,
            "global_cloud": False,
            "is_clean": True,
            "boxes": [],
        }
    data["favorite"] = favorite
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    mtime = float(json_path.stat().st_mtime)
    return {"status": "ok", "favorite": favorite, "annot_mtime": mtime}


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
    raw_scale = min(1.0, max_dim / max(h, w))
    if raw_scale < 1.0:
        new_w, new_h = max(1, int(round(w * raw_scale))), max(1, int(round(h * raw_scale)))
        rgb_preview = cv2.resize(rgb_f32, (new_w, new_h), interpolation=cv2.INTER_AREA)
        scale = new_w / float(w)
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
        "favorite": False,
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

    # Save YOLO format TXT: instance segmentation polygon coordinates or bounding box
    if annot.width > 0 and annot.height > 0:
        lines = []
        for box in annot.boxes:
            if box.label in CLASSES:
                cid = CLASSES.index(box.label)
                if box.type == "polygon" and box.points and len(box.points) >= 3:
                    norm_pts = []
                    for px, py in box.points:
                        nx = min(1.0, max(0.0, float(px) / annot.width))
                        ny = min(1.0, max(0.0, float(py) / annot.height))
                        norm_pts.append(f"{nx:.6f} {ny:.6f}")
                    lines.append(f"{cid} " + " ".join(norm_pts))
                elif box.type == "line" and box.x1 is not None and box.x2 is not None:
                    bx = min(box.x1, box.x2)
                    by = min(box.y1, box.y2)
                    bw = max(abs(box.x2 - box.x1), 4.0)
                    bh = max(abs(box.y2 - box.y1), 4.0)
                    xc = (bx + bw / 2.0) / annot.width
                    yc = (by + bh / 2.0) / annot.height
                    lines.append(f"{cid} {xc:.6f} {yc:.6f} {(bw/annot.width):.6f} {(bh/annot.height):.6f}")
                else:
                    xc = (box.x + box.width / 2.0) / annot.width
                    yc = (box.y + box.height / 2.0) / annot.height
                    lines.append(f"{cid} {xc:.6f} {yc:.6f} {(box.width/annot.width):.6f} {(box.height/annot.height):.6f}")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    mtime = float(json_path.stat().st_mtime) if json_path.exists() else 0.0
    return {"status": "ok", "boxes_count": len(annot.boxes), "is_clean": annot.is_clean, "annot_mtime": mtime}


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


def get_tile_offsets(dimension_size: int, tile_size: int = 512, stride: int = 460) -> List[int]:
    if dimension_size <= tile_size:
        return [0]
    offsets = list(range(0, dimension_size - tile_size + 1, stride))
    last_offset = dimension_size - tile_size
    if offsets[-1] != last_offset:
        offsets.append(last_offset)
    return offsets


def calculate_iou(box1: List[float], box2: List[float]) -> float:
    # box = [x1, y1, x2, y2]
    xA = max(box1[0], box2[0])
    yA = max(box1[1], box2[1])
    xB = min(box1[2], box2[2])
    yB = min(box1[3], box2[3])
    interW = max(0.0, xB - xA)
    interH = max(0.0, yB - yA)
    interArea = interW * interH
    areaA = max(1.0, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    areaB = max(1.0, (box2[2] - box2[0]) * (box2[3] - box2[1]))
    return interArea / float(areaA + areaB - interArea)


@app.get("/api/models")
def list_available_models():
    base_dir = Path(__file__).resolve().parent.parent
    patterns = [
        "runs/segment/**/weights/*.pt",
        "checkpoints/**/*.pt",
        "weights/*.pt",
        "*.pt",
    ]
    models = []
    seen = set()
    for pat in patterns:
        for p in base_dir.glob(pat):
            resolved = p.resolve()
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            rel = str(resolved.relative_to(base_dir))
            is_yolo = "seg" in rel.lower() or "runs/segment" in rel or "yolo" in rel.lower()
            models.append({
                "name": resolved.name,
                "relative_path": rel,
                "full_path": str(resolved),
                "size_mb": round(resolved.stat().st_size / (1024 * 1024), 2),
                "type": "yolo-seg" if is_yolo else "cnn",
                "mtime": resolved.stat().st_mtime,
            })
    models.sort(key=lambda x: x["mtime"], reverse=True)
    return {"models": models}


@app.post("/api/models/predict")
def predict_defect_masks(req: PredictRequest):
    import time
    from ultralytics import YOLO

    fits_path = Path(req.path).resolve()
    if not fits_path.exists():
        raise HTTPException(status_code=404, detail=f"FITS file not found: {req.path}")

    model_file = Path(req.model_path).resolve()
    if not model_file.exists():
        base_dir = Path(__file__).resolve().parent.parent
        alt = (base_dir / req.model_path).resolve()
        if alt.exists():
            model_file = alt
        else:
            raise HTTPException(status_code=404, detail=f"Model checkpoint not found: {req.model_path}")

    cache_key = str(model_file)
    if cache_key not in YOLO_MODEL_CACHE:
        try:
            YOLO_MODEL_CACHE[cache_key] = YOLO(str(model_file))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load YOLO model: {e}")
    model = YOLO_MODEL_CACHE[cache_key]

    fkey = str(fits_path)
    if fkey in IMAGE_CACHE:
        rgb_f32, meta = IMAGE_CACHE[fkey]
    else:
        try:
            rgb_f32, meta = load_fits_unified_rgb(fits_path)
            if len(IMAGE_CACHE) >= 3:
                IMAGE_CACHE.pop(next(iter(IMAGE_CACHE)))
            IMAGE_CACHE[fkey] = (rgb_f32, meta)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load FITS: {e}")

    h, w, _ = rgb_f32.shape
    stf_u8 = to_stf_u8(rgb_f32, shadows_clipping=-2.8, target_bg=0.25, rgb_linked=False, mode="stf")

    x_offsets = get_tile_offsets(w, req.tile_size, req.stride)
    y_offsets = get_tile_offsets(h, req.tile_size, req.stride)

    tiles = []
    coords = []
    for y in y_offsets:
        for x in x_offsets:
            patch = stf_u8[y : y + req.tile_size, x : x + req.tile_size]
            tiles.append(patch)
            coords.append((x, y))

    t0 = time.perf_counter()
    device = req.device
    if not device or device == "auto":
        import torch
        device = "0" if torch.cuda.is_available() else "cpu"

    batch_size = 16
    raw_detections = []

    for i in range(0, len(tiles), batch_size):
        batch_tiles = tiles[i : i + batch_size]
        batch_coords = coords[i : i + batch_size]

        try:
            results = model.predict(
                source=batch_tiles,
                conf=req.conf,
                imgsz=req.tile_size,
                device=device,
                verbose=False,
            )
        except Exception:
            results = model.predict(
                source=batch_tiles,
                conf=req.conf,
                imgsz=req.tile_size,
                device="cpu",
                verbose=False,
            )

        for res, (tx, ty) in zip(results, batch_coords):
            if res.boxes is None or len(res.boxes) == 0:
                continue

            has_masks = res.masks is not None and len(res.masks) > 0

            for idx in range(len(res.boxes)):
                cid = int(res.boxes.cls[idx].item())
                conf = float(res.boxes.conf[idx].item())
                cname = CLASSES[cid] if 0 <= cid < len(CLASSES) else f"class_{cid}"

                bx1, by1, bx2, by2 = res.boxes.xyxy[idx].tolist()
                global_box = [bx1 + tx, by1 + ty, bx2 + tx, by2 + ty]

                poly_coords = None
                if has_masks and idx < len(res.masks.xy):
                    raw_poly = res.masks.xy[idx]
                    if len(raw_poly) >= 3:
                        pts = np.array(raw_poly, dtype=np.float32)
                        approx = cv2.approxPolyDP(pts, epsilon=1.5, closed=True)
                        poly_coords = [[round(float(p[0][0] + tx), 1), round(float(p[0][1] + ty), 1)] for p in approx]

                raw_detections.append({
                    "class": cname,
                    "confidence": conf,
                    "box": global_box,
                    "polygon": poly_coords,
                })

    raw_detections.sort(key=lambda d: d["confidence"], reverse=True)
    kept_detections = []

    for det in raw_detections:
        is_dup = False
        for kept in kept_detections:
            if det["class"] == kept["class"]:
                if calculate_iou(det["box"], kept["box"]) > req.iou:
                    is_dup = True
                    break
        if not is_dup:
            kept_detections.append(det)

    ts_now = int(time.time() * 1000)
    result_boxes = []
    for idx, d in enumerate(kept_detections):
        box_id = f"box_ai_{ts_now}_{idx}"
        cname = d["class"]
        conf = round(d["confidence"], 3)
        gbox = d["box"]

        if d["polygon"] and len(d["polygon"]) >= 3:
            result_boxes.append(BoundingBox(
                id=box_id,
                label=cname,
                type="polygon",
                points=d["polygon"],
                confidence=conf,
                x=gbox[0],
                y=gbox[1],
                width=gbox[2] - gbox[0],
                height=gbox[3] - gbox[1],
            ))
        else:
            result_boxes.append(BoundingBox(
                id=box_id,
                label=cname,
                type="box",
                x=round(gbox[0], 1),
                y=round(gbox[1], 1),
                width=round(gbox[2] - gbox[0], 1),
                height=round(gbox[3] - gbox[1], 1),
                confidence=conf,
            ))

    elapsed = time.perf_counter() - t0

    return {
        "status": "ok",
        "boxes": [b.model_dump() for b in result_boxes],
        "count": len(result_boxes),
        "model": str(model_file.name),
        "elapsed_sec": round(elapsed, 2),
    }


@app.get("/api/dataset/stats")
def get_dataset_stats(dir_path: str = Query(..., description="Directory containing FITS files")):
    p = Path(dir_path).resolve()
    if not p.is_dir():
        base_dir = Path(__file__).resolve().parent.parent.parent
        alt = (base_dir / dir_path).resolve()
        if alt.is_dir():
            p = alt
        else:
            raise HTTPException(status_code=400, detail=f"Directory not found: {dir_path}")

    stats = analyze_dataset(p)
    return stats


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

