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
   - **Track C (Instance Segmentation)**: `YOLO11-seg` (`yolo11n-seg`, `yolo11s-seg`, `yolo11m-seg`) predicting exact polygon defect masks for localized cosmetic rejection in stacking.

---

## Directory Layout

```
training/
├── README.md               # This documentation guide
├── ADDING_NEW_CLASSES.md   # Step-by-step guide for introducing new defect classes
├── requirements.txt        # Pinned Python dependencies
├── fits_utils.py           # Unified 3-channel FITS reader & AutoSTF / Asinh normalizations
├── dataset_analyzer.py     # Dataset class distribution, balance & deficit analyzer
├── master_train.py         # End-to-end master pipeline (slicing + YOLO + CNNs + benchmark)
├── annotator/              # FITS tagging & AI auto-labeling web interface
│   ├── app.py              # FastAPI server with tiled YOLO inference & STF rendering
│   └── static/             # Canvas-based annotation frontend with right sidebar & multi-select
│       ├── index.html
│       ├── style.css
│       └── app.js
├── prep_dataset.py         # Slices full FITS into 512x512 tiles (supports CNN & YOLO-seg)
├── models/
│   └── cnn_zoo.py          # AstroNet, ResNet18/34, MobileNetV3, EfficientNet-B0
├── train.py                # Multi-model CNN training script with early stopping & BCE loss
├── train_yolo.py           # YOLO11-seg instance segmentation runner with early stopping
├── verify.py               # Evaluation & tile-level diagnostic overlays for CNNs
├── verify_yolo.py          # Full-frame FITS verification with polygon segmentation masks
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

# Install base dependencies (CPU / General)
pip install -r requirements.txt
```

#### GPU Acceleration Setup

##### 1. NVIDIA GPUs (CUDA)
For NVIDIA GeForce / RTX / Tesla GPUs, install the standard official CUDA-enabled PyTorch build:

```bash
# PyTorch with CUDA support (e.g., CUDA 12.4/12.6)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

Verify GPU Detection:
```bash
python -c "import torch; print('CUDA Available:', torch.cuda.is_available(), '| Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
```

---

##### 2. Newer AMD Radeon GPUs (RX 90XX series / RDNA4, e.g., RX 9060 XT, RX 9070)
Newer RDNA4 cards (architecture `gfx1200` / `gfx1201`) require AMD's nightly / alpha ROCm wheel builds (such as builds from "TheRock" project / AMD ROCm nightlies):

1. **Install ROCm Nightly Wheels for `gfx120X`**:
   ```bash
   pip install --pre torch torchvision torchaudio \
     --index-url https://rocm.nightlies.amd.com/v2/gfx120X-all/
   ```

2. **Environment Variables for RDNA4**:
   Export the architecture override before running training or ComfyUI:
   ```bash
   # Target RDNA4 ISA
   export HSA_OVERRIDE_GFX_VERSION=12.0.0

   # Memory management tuning for clean HIP memory allocation
   export PYTORCH_HIP_ALLOC_CONF="garbage_collection_threshold:0.8,max_split_size_mb:512"
   ```

3. **Verify ROCm & Architecture Support**:
   ```bash
   python -c "import torch; print('ROCm Available:', torch.cuda.is_available(), '| HIP:', getattr(torch.version, 'hip', None), '| Archs:', torch.cuda.get_arch_list())"
   ```
   *(Should report `Arch list: ['gfx1200', 'gfx1201']` and `CUDA/ROCm Available: True`)*

---

##### 3. Older AMD Radeon GPUs (RX 70XX / RX 60XX series / RDNA3 & RDNA2, e.g., RX 7900 XTX, RX 7800 XT)
For RDNA3 (`gfx1100`, `gfx1101`, `gfx1102`) and RDNA2 (`gfx1030`), use the standard official ROCm builds from PyTorch:

1. **Install PyTorch with Official ROCm**:
   ```bash
   # PyTorch official stable ROCm wheel (e.g., ROCm 6.2):
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
   ```
   *(On Arch Linux, you can alternatively use `sudo pacman -S python-pytorch-opt-rocm`)*

2. **Architecture Override (if needed for consumer Radeon cards)**:
   Some consumer desktop GPUs (e.g. RX 7800 XT / 7700 XT / 6700 XT) need an architecture override to match the closest officially supported enterprise target:
   ```bash
   # For RDNA3 (RX 7900 / 7800 / 7700 / 7600):
   export HSA_OVERRIDE_GFX_VERSION=11.0.0

   # For RDNA2 (RX 6900 / 6800 / 6700):
   export HSA_OVERRIDE_GFX_VERSION=10.3.0
   ```

3. **Verify GPU Detection**:
   ```bash
   python -c "import torch; print('ROCm Available:', torch.cuda.is_available(), '| Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
   ```

---

##### Run Training on GPU
The training scripts in AstroGrader automatically select the device via `torch.device("cuda" if torch.cuda.is_available() else "cpu")`. Pin memory and GPU tensor transfers are handled automatically regardless of whether you are running CUDA or ROCm.

---

### Step 1: FITS Tagging & AI Auto-Labeling Interface

To annotate your raw or calibrated FITS frames:

```bash
python annotator/app.py
```

Open **`http://127.0.0.1:8000`** in your browser.

- **Load Directory**: Enter the directory path containing your `.fits` files (e.g., `../TRAINING_FILES`) and click **Load**.
- **AI Auto-Labeling Panel (Right Sidebar)**:
  - **Select Trained Model**: Automatically detects `.pt` checkpoints in `runs/segment/`, `checkpoints/`, or subdirectories (e.g. `yolo11_astro/weights/best.pt`).
  - **Confidence Slider**: Adjust detection threshold ($0.05$ to $0.90$, default $0.25$).
  - **Run AI Auto-Label (`[M]`)**: Slices the current image into 512×512 tiles with overlap, executes YOLO segmentation inference, removes seam duplicates via IoU NMS, and populates the canvas with polygon annotations.
- **Right Sidebar & Multi-Selection**:
  - **Current Annotations List**: Displays all defect cards with color-coded swatches, geometry type (polygon/box), area in pixels, and model confidence scores.
  - **Bidirectional Hover**: Hovering over a card in the sidebar highlights the corresponding polygon on the canvas (and vice versa).
  - **Multi-Selection**:
    - `Ctrl + Click` (or `Cmd + Click`) on canvas shapes or sidebar cards to select multiple defects.
    - Click **Select All (`Ctrl+A`)** or **Deselect All (`Esc`)**.
    - Click any class tag (e.g., `★ Star Trail`, `🛸 Satellite Streak`) in the sidebar filter to select all annotations belonging to that class.
  - **Batch Drag & Move**: Dragging any selected polygon on the canvas translates all selected shapes concurrently.
  - **Batch Relabel**: Click any class pill in the **Batch Relabel** panel (or press number keys `1`–`6` while items are selected) to instantly convert all selected shapes to that class (e.g., mass-converting misclassified satellite streaks to star trails).
  - **Batch Delete**: Press `Delete` or `Backspace` (or click **Delete Selected**) to remove all selected annotations.
- **Tool Selector (Hotkeys)**:
  - `▢ Box` (`[B]`): For rectangular defect patches. Click and drag on canvas.
  - `⬡ Shape (N-pts)` (`[P]`): For arbitrary freeform defect shapes (e.g. irregular clouds, trees, obstructions). Click $N$ points on the canvas to outline the defect. Double-click, press `Enter`, or click the first green anchor point to close and commit the shape. Press `Esc` to cancel.
  - `╱ Streak Line` (`[L]`): For straight diagonal satellite streaks, airplane trails, or star trails. Click and drag along the line. Includes a **Line Width** slider (2px to 60px) to control the thickness buffer around the streak.
  - `⛶ Full Frame` (`[F]`): Instantly marks the entire frame with the currently active class (e.g. for complete cloud cover or heavy fog).
  - `✂ Preview Cut` (`[C]`): Instantly visualizes the exact $512 \times 512$ dataset tiles that will be sliced! Defective tiles are shaded in their class color, while clean sky tiles are outlined in subtle green.
- **View & Zoom Controls (Hotkeys)**:
  - `[+]` / `[−]`: Zoom in and zoom out (or use mouse scroll wheel). Hotkeys: `+` and `-`.
  - `[1:1]`: View image at 100% pixel-to-pixel resolution.
  - `[Fit]`: Fit and center image within the viewport. Hotkey: `0`.
- **Select Defect Classes (Hotkeys)**:
  - `[1]`: Satellite Streak
  - `[2]`: Airplane
  - `[3]`: Cloud
  - `[4]`: Obstruction
  - `[5]`: Star Trail
  - `[6]`: Unfocused Stars
- **Dataset Health Pre-Analyzer Modal (`📊 Dataset Stats`)**:
  - Click the **Dataset Stats** button in the top toolbar to view a real-time breakdown of annotated images, sample counts per defect class, geometry distribution (polygons vs boxes vs lines), and actionable deficit warnings for under-represented classes.
- **Stretch Controls**:
  - **Stretch Modes**: Switch between `AutoSTF` (standard MTF curve), `Asinh` (astronomical ArcSinh stretch, never blows out stars or background), or `Linear`.
  - **Linked RGB Toggle**: Unchecked by default (`Unlinked STF`). Unlinked mode stretches R, G, and B independently, completely eliminating the strong green/yellow tint common to OSC Bayer sensors! Check `Linked RGB` if you prefer the raw sensor color balance.
  - **Brightness Slider**: Directly controls target background brightness (5% to 50%, default 25%).
  - **Shadows Slider**: Controls black point clipping (-6.0 to 0.0, default -2.8).
  - **Reset STF**: Instantly restores default neutral stretch.
- **Mark / Favorite Frame (`⭐ Mark Frame` / `[K]`)**:
  - Click the **⭐ Mark Frame** button in the header toolbar (or press `[K]`) to bookmark/star frames for later review (e.g. frames with severe defocus or bad tracking).
  - Starred frames are badged with a gold ⭐ in the file list and saved to the annotation JSON (`"favorite": true`).
  - Toggle **⭐ Marked** in the file list header to filter and navigate exclusively through bookmarked frames.
- **File List Sorting (`Sort:` Dropdown)**:
  - Sort frames by **Last Classified (Oldest first)** or **Last Classified (Newest first)** to review previously annotated frames in order of classification.
  - Also supports **Name (A → Z)** and **Name (Z → A)**. Navigation with `Next (D)` and `Prev (A)` automatically follows the chosen sort order.
- **Client-Side URL Hash Persistence**:
  - The currently viewed FITS filename is stored in the browser URL hash (e.g. `http://127.0.0.1:8000/#2024-11-02_..._0078.fits`).
  - Refreshing the browser or sharing the URL directly restores the active image.
- **Automatic Right Sidebar Synchronization**:
  - The right sidebar annotation list and selection state automatically clear and synchronize immediately when switching between frames (preventing stale cards when viewing clean sky).
- **Navigation & Saving**:
  - `[A]` / `Prev`: Go to previous file (auto-saves current).
  - `[D]` / `Next`: Go to next file (auto-saves current).
  - `[W]`: Jump directly to next untagged file.
  - `[U]`: Toggle untagged filter.
  - `[K]`: Toggle mark / favorite frame.
  - `[S]`: Save annotations immediately.
- Annotations are saved alongside your FITS file as `<filename>.json` and `<filename>.txt` (YOLO segmentation format with normalized polygon vertices).

---

### Step 1.5: Dataset Health Pre-Analyzer

Before running intensive model training, run the dataset pre-analyzer to assess sample distribution, check class balance, and receive actionable deficit recommendations:

```bash
python dataset_analyzer.py --data-dir ../TRAINING_FILES
```

Options:
- `--data-dir`: Directory containing `.fits` and `.json` annotation files (default: `../TRAINING_FILES`).
- `--min-deficit`: Threshold below which a class is flagged as critically deficient (default: 20 samples).
- `--json`: Output raw JSON metrics for pipeline integration.

The analyzer reports:
- Number of FITS files, annotated vs unannotated count.
- Sample counts and frequencies per defect class.
- Deficit flags (`CRITICAL DEFICIT: Need X more samples` or `LOW: Consider adding Y samples`).
- Geometric breakdown: polygon count vs bounding box count vs streak line count.

---

### Step 2: Preparing & Slicing Datasets

Slice high-resolution FITS frames into 512×512 tiles with multi-label ground truth:

```bash
python prep_dataset.py --data-dir ../TRAINING_FILES --out-dir dataset --norm-mode asinh
```

Options:
- `--norm-mode asinh`: Normalized using astronomical ArcSinh stretch (preserves full floating-point detail).
- `--norm-mode stf`: Normalized using continuous AutoSTF.
- `--tile-size 512`: Size of the patch in pixels.
- `--stride 460`: Step between tiles (creates ~10% overlap to avoid missing boundary streaks).
- `--val-split 0.2`: 20% validation split isolated by observation frame to prevent data leakage.
- `--workers 12`: Number of parallel worker processes (defaults automatically to `CPU_COUNT - 1` for maximum throughput).
- `--export-yolo`: Simultaneously exports YOLO segmentation format into `--yolo-dir dataset_yolo`.

This outputs:
- `dataset/tiles_f32/`: Sliced tiles stored as `.npy` float32 arrays `[3, 512, 512]`.
- `dataset/tiles_img/`: Sliced tiles saved as 8-bit `.png` for inspection.
- `dataset/train_manifest.json` and `dataset/val_manifest.json`.

---

### Step 3: Training CNN Models

Both CNN (`train.py`) and YOLO (`train_yolo.py`) training scripts support **Early Stopping** (`--patience N`). If validation performance fails to improve for $N$ consecutive epochs, training terminates early and restores the best checkpoint.

#### Track A: Pure CNN Trained from Scratch on Raw `f32` (AstroNet)
Trains our pure residual ConvNet from random weights directly on raw `f32` patterns:

```bash
python train.py --model astronet --input-mode f32 --from-scratch --epochs 25 --patience 7 --batch-size 16
```

#### Track B: Pre-Trained Transfer Learning
Trains standard architectures initialized from ImageNet weights:

```bash
# ResNet-18 baseline
python train.py --model resnet18 --input-mode f32 --epochs 20 --patience 5 --batch-size 16

# MobileNetV3 (ultra-fast for Rust CPU inference)
python train.py --model mobilenet_v3 --input-mode f32 --epochs 20 --patience 5 --batch-size 16

# EfficientNet-B0
python train.py --model efficientnet_b0 --input-mode f32 --epochs 20 --patience 5 --batch-size 16
```

The best checkpoint is automatically saved to `checkpoints/<model_name>_<input_mode>/best_model.pt`.

#### Track C: YOLO11 Instance Segmentation (Pixel-Accurate Masks)
Trains Ultralytics YOLO11-seg on sliced defect tiles with polygon ground truth:

```bash
# Prepare dataset with YOLO segmentation labels
python prep_dataset.py --data-dir ../TRAINING_FILES --out-dir dataset --export-yolo --yolo-dir dataset_yolo

# Train YOLO11-seg (nano backbone, fast & lightweight, patience=10)
python train_yolo.py --model yolo11n-seg.pt --data dataset_yolo/dataset.yaml --epochs 40 --patience 10 --batch 16 --imgsz 512

# For AMD Radeon RX 9060 XT / RDNA4 (gfx1200), disable AMP to prevent MIOpen/CK GPU hangs:
python train_yolo.py --model yolo11n-seg.pt --data dataset_yolo/dataset.yaml --epochs 40 --patience 10 --batch 16 --imgsz 512 --no-amp

# Train YOLO11-seg small backbone (higher mask accuracy)
python train_yolo.py --model yolo11s-seg.pt --data dataset_yolo/dataset.yaml --epochs 40 --patience 10 --batch 16 --imgsz 512 --no-amp
```

Results, checkpoints, and auto-exported ONNX weights are saved under `runs/segment/yolo11_astro/weights/best.pt` and `best.onnx`.

---

### Step 3.5: Master Training Pipeline (`master_train.py`)

To run the complete pipeline—dataset health check, 512×512 slicing for both CNN and YOLO, training YOLO11-seg, and training all CNN architectures (AstroNet, ResNet18, MobileNetV3, EfficientNet-B0)—with a single command:

```bash
python master_train.py --data-dir ../TRAINING_FILES --yolo-model yolo11n-seg.pt --no-amp
```

Useful flags:
- `--skip-prep`: Skip tile slicing if `dataset/` and `dataset_yolo/` already exist.
- `--skip-yolo`: Skip YOLO segmentation training (train only CNNs).
- `--skip-cnns`: Skip CNN training (train only YOLO segmentation).
- `--cnn-models astronet resnet18`: Train a specific subset of CNN models.
- `--cnn-epochs 20 --cnn-patience 5`: Set epochs and early stopping patience for CNNs.
- `--yolo-epochs 30 --yolo-patience 8`: Set epochs and early stopping patience for YOLO.
- `--no-amp`: Disables mixed precision (recommended for RDNA4 ROCm stability).

Upon completion, `master_train.py` outputs a comparative performance summary table comparing parameters, test loss, and F1 scores across all trained architectures.

---

### Adding New Defect Classes

To add a new astronomical defect class (such as `unfocused_stars`):
1. Review the full guide in [ADDING_NEW_CLASSES.md](ADDING_NEW_CLASSES.md).
2. Add the class name and color to `training/fits_utils.py` (`CLASSES`, `CLASS_HEX_COLORS`, `CLASS_RGB_COLORS`).
3. The annotator UI, dataset preparation scripts, and neural network output heads adapt dynamically!

---

### Step 4: Verification & Diagnostic Visual Reports

#### Option 1: CNN Patch Classification Diagnostic Overlays
Run inference on test FITS frames using PyTorch (`.pt`) or ONNX (`.onnx`):

```bash
# Single file
python verify.py --fits image.fits --model-path checkpoints/astronet_f32/best_model.pt

# Wildcard / glob pattern (e.g. all FITS in a directory)
python verify.py --fits *.fits --model-path checkpoints/astronet_f32/best_model.pt --norm-mode asinh

# Whole folder or multiple files
python verify.py --fits ../test_fits/ --model-path checkpoints/astronet_f32/astronet.onnx --norm-mode asinh
```

#### Option 2: YOLO11-seg Pixel-Accurate Mask Overlays
Run full-frame YOLO11-seg inference to inspect semi-transparent defect masks overlaid directly onto the astronomical frame:

```bash
# Verify test frames with trained YOLO11-seg checkpoint
python verify_yolo.py --fits ../test_fits/ --model runs/segment/yolo11_astro/weights/best.pt --conf 0.25

# Single file inspection with custom threshold
python verify_yolo.py --fits image.fits --model runs/segment/yolo11_astro/weights/best.pt --conf 0.3
```

This outputs:
- **Terminal report**: Individual frame verdicts (`CLEAN SKY` or `DEFECT FLAGGED`), defect counts per class, and inference latency.
- **Visual PNG reports**: `verification_output/<filename>_yolo_inspection.png` with color-filled polygon masks and confidence badges rendered over every defect.

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
