# AstroGrader: Deep Learning Astronomical Defect Detection

An end-to-end Machine Learning pipeline for detecting, classifying, and localizing astronomical defects and artifacts (satellite streaks, airplanes, clouds, terrestrial obstructions, and star trails) directly from raw or calibrated `.fits` files.

---

## Key Architectural Principles

1. **Unified 3-Channel RGB Contract (`Vec<(f32, f32, f32)>`)**:
   - The neural network **always** receives a 3-channel RGB representation of type `float32`.
   - **Bayer CFA Frames (One-Shot Color)**: Automatically debayered upfront (RGGB, BGGR, GBRG, GRBG) into full-color RGB `float32`.
   - **Monochrome / Grayscale Frames**: Replicated across all three channels ($R = G = B$).
   - Sensor variations or Bayer patterns will never break model inference or the Rust engine.

2. **Full Dynamic Range `f32` (Zero 8-Bit Quantization Loss)**:
   - AstroGrader stores pixel buffers as [`Vec<f32>`](../astro-grader/src-tauri/src/fits/image_data_pixels.rs).
   - In 16-bit linear data, faint satellite streaks (1–2 px wide) and diffuse clouds occupy only 0.1% to 1% of the dynamic range. Direct casting to 8-bit (`val / 256`) crushes them into quantization noise. By operating directly on `f32`, full precision is preserved.
   - We support **Astronomical Asinh Stretch** ($f(x) = \text{asinh}((x - \mu) / \sigma)$) and continuous **AutoSTF** ($[0.0, 1.0]$ `f32`).

3. **Multi-Label Defect Classification**:
   - Rather than mutually exclusive softmax, we use **Sigmoid multi-label classification** (`BCEWithLogitsLoss`).
   - **Empty / 0 active classes = Clean Astronomical Sky**.
   - Frames or tiles can have 1 to 5 active defect classes simultaneously:
     - `satellite_streak`: Single or multiple straight, continuous lines.
     - `airplane`: Wide trails with periodic blinking strobe dots and paired navigation lines.
     - `cloud`: Diffuse brightness obscuration or gradient extinction.
     - `obstruction`: Terrestrial silhouettes (trees, buildings, antennas, dome edge).
     - `star_trail`: Elongated star shapes caused by tracking failure or wind gusts.

4. **Comparative Benchmark Matrix (Master's Thesis Research Track)**:
   - **Track A (Pure CNN from scratch)**: `AstroNet` / pure residual ConvNet initialized from scratch with random weights, trained **exclusively** on raw astronomical `f32` patches.
   - **Track B (Transfer Learning)**: `ResNet18/34`, `MobileNetV3`, and `EfficientNet-B0` with ImageNet pre-trained weights.

---

## Directory Layout

```
training/
├── README.md               # This documentation guide
├── requirements.txt        # Pinned Python dependencies
├── fits_utils.py           # Unified 3-channel FITS reader & AutoSTF / Asinh normalizations
├── annotator/              # Minimalist FITS tagging web interface
│   ├── app.py              # FastAPI server with dynamic AutoSTF rendering
│   └── static/             # Canvas-based annotation frontend (no flashy styling)
│       ├── index.html
│       ├── style.css
│       └── app.js
├── prep_dataset.py         # Slices full FITS into 512x512 tiles & builds manifests
├── models/
│   └── cnn_zoo.py          # AstroNet, ResNet18/34, MobileNetV3, EfficientNet-B0
├── train.py                # Multi-model training script with BCE loss & metrics
├── verify.py               # Evaluation, throughput benchmark & diagnostic overlays
├── export_onnx.py          # ONNX model exporter with numerical parity check
└── rust_example/           # Standalone Rust engine integration example
    ├── Cargo.toml
    └── src/main.rs
```

---

## Step-by-Step Guide

### Setup Virtual Environment

Ensure you are inside the `training/` directory:

```bash
cd training

# Create virtual environment if it does not exist
python3 -m venv .venv

# Activate environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

### Step 1: Minimalist FITS Tagging Interface

To annotate your raw or calibrated FITS frames:

```bash
python annotator/app.py
```

Open **`http://127.0.0.1:8000`** in your browser.

- **Load Directory**: Enter the directory path containing your `.fits` files (e.g., `../test_fits`) and click **Load**.
- **Draw Bounding Boxes**: Click and drag on the canvas to draw a defect rectangle.
- **Select Defect Classes (Hotkeys)**:
  - `[1]`: Satellite Streak
  - `[2]`: Airplane
  - `[3]`: Cloud
  - `[4]`: Obstruction
  - `[5]`: Star Trail
- **Frame-Level Controls**:
  - `Global Star Trailing`: Check this if tracking was lost and **all** stars across the frame are trailed.
  - `Clean Sky`: Automatically checked if no boxes are present.
- **Interactive STF Stretch**: Adjust the stretch slider to reveal faint streaks or deep shadow trees.
- **Navigation & Saving**:
  - `[A]` / `Prev`: Go to previous file (auto-saves current).
  - `[D]` / `Next`: Go to next file (auto-saves current).
  - `[S]`: Save annotations immediately.
- Annotations are saved alongside your FITS file as `<filename>.json` and `<filename>.txt` (YOLO format).

---

### Step 2: Preparing & Slicing Datasets

Slice high-resolution FITS frames into 512×512 tiles with multi-label ground truth:

```bash
python prep_dataset.py --data-dir ../test_fits --out-dir dataset --norm-mode asinh
```

Options:
- `--norm-mode asinh`: Normalized using astronomical ArcSinh stretch (preserves full floating-point detail).
- `--norm-mode stf`: Normalized using continuous AutoSTF.
- `--tile-size 512`: Size of the patch in pixels.
- `--stride 460`: Step between tiles (creates ~10% overlap to avoid missing boundary streaks).
- `--val-split 0.2`: 20% validation split isolated by observation frame to prevent data leakage.

This outputs:
- `dataset/tiles_f32/`: Sliced tiles stored as `.npy` float32 arrays `[3, 512, 512]`.
- `dataset/tiles_img/`: Sliced tiles saved as 8-bit `.png` for inspection.
- `dataset/train_manifest.json` and `dataset/val_manifest.json`.

---

### Step 3: Training CNN Models

#### Track A: Pure CNN Trained from Scratch on Raw `f32` (AstroNet)
Trains our pure residual ConvNet from random weights directly on raw `f32` patterns:

```bash
python train.py --model astronet --input-mode f32 --from-scratch --epochs 20 --batch-size 16
```

#### Track B: Pre-Trained Transfer Learning
Trains standard architectures initialized from ImageNet weights:

```bash
# ResNet-18 baseline
python train.py --model resnet18 --input-mode f32 --epochs 15 --batch-size 16

# MobileNetV3 (ultra-fast for Rust CPU inference)
python train.py --model mobilenet_v3 --input-mode f32 --epochs 15 --batch-size 16

# EfficientNet-B0
python train.py --model efficientnet_b0 --input-mode f32 --epochs 15 --batch-size 16
```

The best checkpoint is automatically saved to `checkpoints/<model_name>_<input_mode>/best_model.pt`.

---

### Step 4: Verification & Diagnostic Visual Reports

Run inference on an unannotated or test FITS frame:

```bash
python verify.py \
  --fits ../test_fits/2025-07-03_00-56-59_H_-20.00_180.00s_0013.fits \
  --model-path checkpoints/astronet_f32/best_model.pt \
  --out-dir verification_output
```

This outputs:
- **Terminal report**: Inference latency, tile throughput, and quality verdict (`CLEAN SKY` or `DEFECT FLAGGED`).
- **Visual PNG report**: `verification_output/<filename>_inspection.png` with colored bounding boxes and confidence scores rendered over the stretched frame.

---

### Step 5: Exporting to ONNX

Export the best PyTorch model to ONNX format with numerical parity verification:

```bash
python export_onnx.py \
  --model-path checkpoints/astronet_f32/best_model.pt \
  --output astro_model.onnx
```

- Input: `[batch_size, 3, 512, 512]` of type `float32`.
- Output: `[batch_size, 5]` of type `float32`.
- Validates that difference between PyTorch and ONNX Runtime is $< 10^{-4}$.

---

### Step 6: Rust Engine Integration

To run high-performance inference in Rust using `ort`:

```bash
cd rust_example
cargo run --release
```

The Rust runner accepts `Vec<(f32, f32, f32)>` or planar float slices `&[f32]`, tiles the full frame in parallel, and returns structured quality verdicts:

```rust
pub struct FrameInspectionReport {
    pub is_clean: bool,
    pub detected_defects: Vec<String>,
    pub anomalies: Vec<TileAnomaly>,
    pub inference_time_ms: f64,
}
```
