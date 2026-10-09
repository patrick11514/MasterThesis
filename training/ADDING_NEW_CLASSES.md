# How to Add New Defect Classes in AstroGrader

This guide explains how to add new astronomical defect classes (such as `unfocused_stars`) to the AstroGrader training pipeline, web annotator, and inference engine.

---

## 1. Architecture Overview

AstroGrader uses a single source of truth for all defect classes defined in [`training/fits_utils.py`](file:///home/patrick115/Projects/MasterThesis/training/fits_utils.py).
Raw annotations stored in `.json` files use human-readable string labels (e.g. `{"label": "satellite_streak", ...}`). Because labels are string-based, existing annotation files **never break** when you introduce a new class.

When slicing data for neural networks, each 512x512 tile is mapped into:
1. **Multi-hot float vector** for CNNs (e.g. `[0, 0, 1, 0, 0, 0]` where length equals `len(CLASSES)`).
2. **YOLO class ID integer** for instance segmentation (e.g. `0` to `len(CLASSES) - 1`).

---

## 2. Step-by-Step Instructions

### Step 1: Add the Class to the Central Registry

Open [`training/fits_utils.py`](file:///home/patrick115/Projects/MasterThesis/training/fits_utils.py) and append your new class to `CLASSES`, `CLASS_HEX_COLORS`, and `CLASS_RGB_COLORS`:

```python
CLASSES = [
    "satellite_streak",
    "airplane",
    "cloud",
    "obstruction",
    "star_trail",
    "unfocused_stars",   # <-- New Class
]

CLASS_HEX_COLORS = {
    "satellite_streak": "#e53e3e",
    "airplane": "#ed8936",
    "cloud": "#4299e1",
    "obstruction": "#9f7aea",
    "star_trail": "#ecc94b",
    "unfocused_stars": "#38b2ac",  # Teal accent
}

CLASS_RGB_COLORS = {
    "satellite_streak": (229, 62, 62),
    "airplane": (237, 137, 54),
    "cloud": (66, 153, 225),
    "obstruction": (159, 122, 234),
    "star_trail": (236, 201, 75),
    "unfocused_stars": (56, 178, 172),
}
```

> **Note**: The web annotator backend automatically serves this list via `/api/classes`. The web UI dynamically generates the button `[6] Unfocused Stars` and keybinding `6` without any manual HTML edits!

---

### Step 2: Check Model Class Count (`models/cnn_zoo.py`)

In [`training/models/cnn_zoo.py`](file:///home/patrick115/Projects/MasterThesis/training/models/cnn_zoo.py), `NUM_CLASSES` is dynamically computed as:
```python
NUM_CLASSES = len(CLASSES)
```
Any instantiated model (`AstroNet`, `ResNet18`, `MobileNetV3`, `EfficientNetB0`) will automatically construct its classification head with the correct number of output logits.

---

### Step 3: Annotate Samples in the Web Annotator

1. Launch the web annotator:
   ```bash
   cd training/annotator
   python app.py
   ```
2. Open `http://127.0.0.1:8000`.
3. You will see the new class button (e.g. `[6] Unfocused Stars`).
4. Select the class or press `6`, then draw boxes, streak lines, or polygons around unfocused stars.
5. Save annotations (`S`). The output JSON will record:
   ```json
   {
     "id": "box_172846...",
     "label": "unfocused_stars",
     "type": "polygon",
     "points": [[...], [...]]
   }
   ```

---

### Step 4: Re-slice the Dataset

Run [`training/prep_dataset.py`](file:///home/patrick115/Projects/MasterThesis/training/prep_dataset.py) (or use the master training script):

```bash
python prep_dataset.py --data-dir ../TRAINING_FILES --out-dir dataset --export-yolo
```

This will:
- Re-slice all frames into 512x512 tiles.
- Write multi-hot vectors of length `len(CLASSES)` in `dataset/train_manifest.json`.
- Generate `dataset_yolo/dataset.yaml` with the updated class mapping:
  ```yaml
  names:
    0: satellite_streak
    1: airplane
    2: cloud
    3: obstruction
    4: star_trail
    5: unfocused_stars
  ```

---

### Step 5: Retrain YOLO and CNNs

You can run the master script to train both YOLO and CNN backbones:

```bash
python master_train.py --data-dir ../TRAINING_FILES --yolo-epochs 30 --cnn-epochs 20
```

Or train them individually:
```bash
# YOLO11 instance segmentation
python train_yolo.py --epochs 30

# CNN multi-label classification
python train.py --model astronet --epochs 20
python train.py --model resnet18 --epochs 20
```

---

### Step 6: Synchronize the Rust Engine (AstroGrader Desktop App)

If deploying to the AstroGrader desktop application:
1. Update `CLASSES` in `training/rust_example/src/main.rs`:
   ```rust
   pub const CLASSES: [&str; 6] = [
       "satellite_streak",
       "airplane",
       "cloud",
       "obstruction",
       "star_trail",
       "unfocused_stars",
   ];
   ```
2. Update the corresponding class list and enum in `astro-grader/src-tauri/src/`.
