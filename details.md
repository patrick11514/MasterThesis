# AstroGrader Project Details: Key Processing Algorithms

This document describes the three core astronomical image processing algorithms implemented in the AstroGrader project: **AutoSTF Calculation**, **Debayering**, and **Frame Stacking**.

---

## 1. AutoSTF Calculation (Auto-Stretch to Fit)

### Overview

AutoSTF (Automatic Stretch-to-Fit) is a real-time image enhancement technique that automatically computes optimal histogram stretching parameters for display. It calculates shadow (black point), midtone (gamma), and highlight (white point) adjustment values for both **linked** (RGB) and **unlinked** (per-channel) modes.

### Implementation Location

- **File**: [astro-grader/src-tauri/src/fits/utils.rs](astro-grader/src-tauri/src/fits/utils.rs#L145-L240)
- **File**: [astro-grader/src-tauri/src/fits/image_data_pixels.rs](astro-grader/src-tauri/src/fits/image_data_pixels.rs#L299-L340)

### Algorithm Steps

#### 1.1 Statistical Sampling

The algorithm samples the image data based on its layout:

```
For Grayscale:
  - Single channel: sample every 100th pixel (stride=100)
  - Returns: median, MAD (Median Absolute Deviation)

For RGB Interleaved (RGBRGBRGB...):
  - Red channel: offset=0, stride=300 (every 3rd triplet starting at R)
  - Green channel: offset=1, stride=300 (every 3rd triplet starting at G)
  - Blue channel: offset=2, stride=300 (every 3rd triplet starting at B)
  - Returns: 3 pairs of (median, MAD)

For RGB Planar (separate RRR...GGG...BBB...):
  - Divide pixels into 3 equal planes
  - Sample each plane independently with stride=100
  - Returns: 3 pairs of (median, MAD)
```

**Statistical Calculation** ([calculate_channel_stats](astro-grader/src-tauri/src/fits/utils.rs#L128-L143)):

- Collects samples by offset and stride
- **Median**: Uses unstable select algorithm (O(n) time)
- **MAD (Median Absolute Deviation)**:
  - Compute deviations: `|sample - median|`
  - Find median of absolute deviations
  - Return MAD value
- MAD is then scaled by `1.4826` to approximate standard deviation

#### 1.2 Channel-Dependent Processing

Depending on whether RGB channels are **linked** or **unlinked**, different stretching is applied:

**Linked Mode** (applied uniformly to all RGB channels):

- Determines if image is inverted based on median values (>0.5 = bright, <0.5 = dark)
- **Dark Image Logic**:
  - `c0 = clamp(avg_median + shadows_clipping × avg_scaled_mad, 0.0, 1.0)`
    - `shadows_clipping = -2.80` (aggressive dark point adjustment)
  - `m = mtf(target_background=0.25, c0_normalized_median)`
  - Result: `[c0, m, 1.0]` applied to all channels
- **Bright Image Logic**:
  - `c1 = clamp(avg_median - shadows_clipping × avg_scaled_mad, 0.0, 1.0)`
  - `m = mtf(c1 - avg_median, target_background=0.25)`
  - Result: `[0.0, m, c1]` applied to all channels

**Unlinked Mode** (per-channel independent):

- For each channel independently:
  - **If dark** (`median < 0.5`):
    - `c0 = clamp(median + (-2.80) × scaled_mad, 0, 1)`
    - `m = mtf(0.25, median - c0)`
    - Output: `[c0, m, 1.0]`
  - **If bright** (`median ≥ 0.5`):
    - `c1 = clamp(median - (-2.80) × scaled_mad, 0, 1)`
    - `m = mtf(c1 - median, 0.25)`
    - Output: `[0.0, m, c1]`

#### 1.3 MTF Transform (Midtone Transfer Function)

```rust
fn mtf(target: f32, x: f32) -> f32 {
    if x == 0.0 { return 0.0; }
    if x == 1.0 { return 1.0; }
    ((target - 1.0) * x) / (((2.0 * target - 1.0) * x) - target)
}
```

This applies a power-law gamma correction to compute the midtone adjustment factor.

### Output Format

```rust
pub struct AutoSFT {
    pub linked: STFPair,    // RGB channels stretched together
    pub unlinked: STFPair,  // Each RGB channel stretched independently
}

pub struct STFPair {
    pub r: [f32; 3],  // [shadow, midtone, highlight] for Red
    pub g: [f32; 3],  // [shadow, midtone, highlight] for Green
    pub b: [f32; 3],  // [shadow, midtone, highlight] for Blue
}
```

**Note**: For grayscale images, the R channel values are duplicated to G and B channels for consistency.

### Reference

Algorithm adapted from PixInsight's official STF implementation (referenced in code comments from forum discussion).

---

## 2. Debayering (Bayer Pattern Demosaicing)

### Overview

Debayering converts single-channel Bayer-pattern raw sensor data into full RGB color images. Raw cameras capture only one color per pixel in a checkerboard Bayer pattern; debayering reconstructs all three color channels at each pixel location.

### Implementation Location

- **File**: [astro-grader/src-tauri/src/fits/utils.rs](astro-grader/src-tauri/src/fits/utils.rs#L15-L115)
- **File**: [astro-grader/src-tauri/src/fits/image_data_pixels.rs](astro-grader/src-tauri/src/fits/image_data_pixels.rs#L203-L235)

### Bayer Pattern Support

The system recognizes and stores Bayer patterns as 4-character strings with offset information:

```
Common Bayer Patterns:
- "RGGB": Red-Green-Green-Blue (most common)
  [R G]
  [G B]
- "BGGR": Blue-Green-Green-Red
- "RGBG": Red-Green-Blue-Green
- "GRBG": Green-Red-Blue-Green

Pattern Metadata:
- x_offset: Horizontal Bayer alignment offset (0 or 1, or -1 normalized to 1)
- y_offset: Vertical Bayer alignment offset (0 or 1, or -1 normalized to 1)
```

### Algorithm: 2×2 Super-Pixel Averaging (Bi-Linear Interpolation)

The debayer method processes the original grayscale image by grouping it into 2×2 pixel blocks and averaging within each block to reconstruct RGB:

**Process**:

```
Input: Grayscale image (width W, height H)
       Bayer pattern (4 chars), x_offset, y_offset

Output: RGB image (width W/2, height H/2, depth 3)
        Pixels in RGBRGBRGB... interleaved format
```

**Per-Block Computation**:
For each 2×2 block at position `(x, y)` in the output (new) image:

```
1. Calculate source coordinates in original image:
   - ox ∈ {x*2, x*2+1}  (left and right columns)
   - oy ∈ {y*2, y*2+1}  (top and bottom rows)

2. For each of the 4 pixels in the 2×2 block:
   - Determine color (R, G, or B) based on:
     * Bayer pattern
     * (ox + x_offset) & 1 == 0  (even column row)
     * (oy + y_offset) & 1 == 0  (even row)

3. Accumulate:
   - sum_r, count_r for Red channel
   - sum_g, count_g for Green channel (usually 2 samples per block)
   - sum_b, count_b for Blue channel

4. Output RGB pixel:
   - R = sum_r / count_r
   - G = sum_g / count_g
   - B = sum_b / count_b
```

**Implementation Details**:

- **Parallelization**: Uses Rayon library to process output blocks in parallel
- **Bitwise Optimization**: Uses `& 1` instead of `% 2` for parity checks (faster on most CPUs)
- **Memory Efficiency**: Operates on slice references to avoid excessive cloning
- **Edge Handling**: Skips coordinates beyond image boundaries gracefully

**Example (RGGB Pattern)**:

```
Original 2×2 block (grayscale):
  [pixel_00  pixel_01]
  [pixel_10  pixel_11]

With RGGB pattern:
  pixel_00 = R value
  pixel_01 = G value
  pixel_10 = G value
  pixel_11 = B value

Output RGB pixel = [R_avg, (G+G)/2, B_avg]
```

### Data Layout Conversion

The algorithm automatically converts image data:

```
Before:  Grayscale layout
  width × height × 1 channel

After:   RGB interleaved layout
  (width/2) × (height/2) × 3 channels
  Stored as [R, G, B, R, G, B, ...]
```

### Bayer Pattern Storage

After successful debayering, the applied Bayer pattern is stored in image metadata:

- `applied_options.bayer_pattern`: Records which pattern was used
- `applied_options.scale`: Set to 1.0 (not downscaled)
- Original pattern information preserved for reference

---

## 3. Frame Stacking (Master Frame Generation)

### Overview

Frame stacking combines multiple individual astronomical frames (lights, darks, flats, biases) into master calibration frames using statistical methods. This improves signal-to-noise ratio and creates reference frames for image calibration.

### Implementation Location

- **File**: [astro-grader/src-tauri/src/processing/calibrate.rs](astro-grader/src-tauri/src/processing/calibrate.rs#L85-L360)
- **Files Grouped**: [astro-grader/src-tauri/src/processing/group.rs](astro-grader/src-tauri/src/processing/group.rs)

### Frame Types and Stacking Strategies

#### 3.1 Master Dark Frames

**Purpose**: Capture thermal noise and read noise from the sensor (no photons)

**Stacking Method**: **Sigma-Clipped Mean** (for ≥6 frames)

- Rejects cosmic rays and hot pixels effectively
- Two-pass Welford algorithm:

  **Pass 1: Compute Mean and M2 (Variance Numerator)**

  ```
  for each frame:
    for each pixel:
      delta = pixel_value - mean
      mean += delta / frame_number
      delta2 = pixel_value - new_mean
      M2 += delta × delta2

  std_dev = sqrt(M2 / frame_count)
  ```

  **Pass 2: Clipping and Mean Calculation**

  ```
  clipping_threshold = 3σ
  lower = mean - 3σ
  upper = mean + 3σ

  for each frame:
    for each pixel:
      if pixel in [lower, upper]:
        accumulate pixel

  final_master = accumulated_sum / non_clipped_count
  ```

**Fallback (≤5 frames)**: **Median** (see below)

#### 3.2 Master Flat Frames

**Purpose**: Correct for uneven illumination and pixel sensitivity variations

**Stacking Method**: **Median** (regardless of frame count)

- Median is inherently robust to dust spots and defects
- Flats are naturally uniform, so sparse defects don't affect median
- **Normalization**: Master flat is divided by its maximum value to achieve unity gain

```rust
max_val = max(all_pixels)
normalized_pixel = original_pixel / max_val
```

#### 3.3 Master Bias Frames

**Purpose**: Record fixed-pattern read noise (zero exposure)

**Stacking Method**: **Median** (regardless of frame count)

- Zero-exposure frames have minimal variation
- Median rejects any anomalies effectively

#### 3.4 Light Frames (Science Data)

**Note**: Light frames are NOT stacked in this implementation. Individual light frames are preserved for calibration and analysis.

### General Median Computation

---

## 4. Metrics and Frame Quality Scoring

### Overview

After calibration, the backend now runs a metrics pass on the calibrated light frames. The metrics pass uses the `sep-sys` bindings to estimate star and background properties for each frame and stores the results in `ImageStats`.

### Implementation Location

- **File**: [astro-grader/src-tauri/src/processing/metrics.rs](astro-grader/src-tauri/src/processing/metrics.rs)
- **File**: [astro-grader/src-tauri/src/fits/structs.rs](astro-grader/src-tauri/src/fits/structs.rs)

### Stored Metrics

- `star_count`: number of detected sources from SEP extraction
- `fwhm`: average full width at half maximum across detected stars
- `hfd`: average half-flux diameter across detected stars
- `eccentricity`: average star eccentricity across detected stars
- `background_contrast`: signed background estimate derived from SEP background statistics
- `quality_score`: per-night normal-distribution score for comparing frames inside the same grouped night

### Quality Scoring

- Frames are compared only inside the same grouped night
- A normal distribution is built from the detected star counts of the night
- Frames near the night mean receive a higher `quality_score`
- Frames beyond `3σ` receive a negative score
- Cross-night comparison is intentionally deferred for now

### Background Estimate

- SEP background estimation is used to measure the overall background level and background RMS
- The stored `background_contrast` keeps the sign of the background level so brighter skies and darker obstructions can be distinguished

---

## 5. Workflow Update

### Calibration State Sync

- Calibration now returns the updated `FeState` to the frontend after the backend finishes
- This ensures `File.calibrated_frame` is visible in the UI immediately after calibration

### Run All Processes

- The command palette now includes **Run all processes** above the existing processing commands
- It runs the processing pipeline sequentially: group nights, calibrate frames, then calculate metrics
- The command uses the same backend state flow as the individual steps, so the UI stays in sync after each stage

For both flat and bias masters (and dark masters with <6 frames):

```rust
// Streaming approach to save memory
samples = allocate(frame_count × pixel_count)

for each frame:
  load frame pixels into samples array
    offset = frame_index × pixel_count

// Parallel median calculation
for each pixel_index:
  collect_values = [samples[0*pixel_count + index],
                    samples[1*pixel_count + index],
                    ...
                    samples[(frame_count-1)*pixel_count + index]]

  mid = collect_values.len() / 2
  collect_values.select_nth_unstable(mid)  // O(n) algorithm
  result[index] = collect_values[mid]
```

**Key Features**:

- Uses unstable `select_nth_unstable` for O(n) median finding (faster than sorting)
- Parallelized over all pixels using Rayon
- Streaming reads to avoid holding all frames in memory simultaneously (for sigma-clipped mean path)

### Master Frame Output

All master frames are written back to FITS format with enhanced metadata:

```rust
shape = match layout {
    Grayscale => [height, width],
    RGBPlanar => [3, height, width],
}

// Preserve calibration metadata from first source frame:
IMAGETYP = "master dark" | "master flat" | "master bias"
INSTRUME = camera name
TELESCOP = telescope name
FILTER = filter name
EXPTIME = exposure time (for darks)
GAIN = sensor gain
BAYERPAT = Bayer pattern (if original was Bayer)
XBAYROFF = X Bayer offset
YBAYROFF = Y Bayer offset
```

### Frame Matching for Automatic Grouping

When associating calibration frames with light frames:

```
Dark Frame Matching:
  ✓ Same camera, same exposure time, same gain, same temperature

Flat Frame Matching:
  ✓ Same camera, same filter (if specified), same gain
  ✗ Temperature-independent (flats vary less with temperature)
  ✗ Night-independent (flats can be reused across multiple nights)

Bias Frame Matching:
  ✓ Same camera, same gain
  ✗ No exposure or filter requirement
```

**Master Detection**: If a master frame exists matching a light session, individual calibration frames of that type are ignored and the master is used instead.

---

## 4. Data Flow and Integration

### Image Reading Pipeline

```
FITS File
    ↓
[Read raw pixels + metadata]
    ↓
[Normalize to [0, 1] range based on FITS data type]
    ↓
[Convert planar RGB to interleaved format if needed]
    ↓
[Apply optional debayering]
    ↓
[Apply optional scaling/downsampling]
    ↓
[Calculate AutoSTF (linked + unlinked)]
    ↓
Display-ready ImageData with STF profiles
```

### Master Frame Generation Pipeline

```
Individual Frames (grouped by type and metadata)
    ↓
[Read all pixels (streaming or buffered)]
    ↓
[Apply statistical method (median or sigma-clipped mean)]
    ↓
[Normalize if flat master]
    ↓
[Write to FITS + metadata]
    ↓
Master Frame (used for calibration)
```

---

## 5. Performance Considerations

- **Parallelization**: All CPU-intensive operations use Rayon thread pool
- **Memory Efficiency**: Sigma-clipped master generation uses streaming to avoid loading all frames
- **Median Finding**: O(n) select algorithm instead of O(n log n) sorting
- **Bayer Offset Handling**: Bitwise operations for parity checking
- **Sampling Strategy**: STF uses 1% sampling (every 100th pixel) for speed without accuracy loss

---

## 6. Known Limitations & Design Notes

1. **RGB Interleaving Only**: Scaling operations require RGB interleaved format (not planar)
2. **2×2 Super-Pixel Debayering**: Simple but effective; does not use advanced algorithms like Lanczos or VNG
3. **No Light Frame Stacking**: Only calibration frames (darks, flats, biases) are stacked
4. **Grayscale Duplication**: Grayscale images duplicate their STF profile across R, G, B for consistency
5. **Fixed Clipping Threshold**: Sigma-clipped mean uses hard-coded 3σ (configurable in principle)
