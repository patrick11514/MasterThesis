"""
FITS Reading and Astronomical Image Processing Utilities.
Strictly adheres to the Unified 3-Channel RGB Contract: Vec<(f32, f32, f32)>.
Replicates AstroGrader's native Rust AutoSTF and debayering algorithms.
"""

import math
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import numpy as np
from astropy.io import fits
import cv2

CLASSES = [
    "satellite_streak",
    "airplane",
    "cloud",
    "obstruction",
    "star_trail",
    "unfocused_star"
]

CLASS_HEX_COLORS = {
    "satellite_streak": "#e53e3e",
    "airplane": "#ed8936",
    "cloud": "#4299e1",
    "obstruction": "#9f7aea",
    "star_trail": "#ecc94b",
    "unfocused_star": "#38b2ac",
}

CLASS_RGB_COLORS = {
    "satellite_streak": (229, 62, 62),
    "airplane": (237, 137, 54),
    "cloud": (66, 153, 225),
    "obstruction": (159, 122, 234),
    "star_trail": (236, 201, 75),
    "unfocused_star": (56, 178, 172),
}


def mtf_scalar(m: float, x: float) -> float:
    """Midtone Transfer Function (MTF) formula yoinked from PixInsight / AstroGrader."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if abs(m - 0.5) < 1e-6:
        return x
    denom = (2.0 * m - 1.0) * x - m
    if abs(denom) < 1e-12:
        return 0.0
    val = ((m - 1.0) * x) / denom
    return float(np.clip(val, 0.0, 1.0))


def mtf_array(m: float, x: np.ndarray) -> np.ndarray:
    """Vectorized MTF curve applied over numpy float array."""
    if abs(m - 0.5) < 1e-6:
        return np.clip(x, 0.0, 1.0)
    denom = (2.0 * m - 1.0) * x - m
    # Avoid zero division
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    res = ((m - 1.0) * x) / denom
    return np.clip(res, 0.0, 1.0)


def calculate_channel_stats(data: np.ndarray, stride: int = 100) -> Tuple[float, float]:
    """
    Computes sample median and MAD (Median Absolute Deviation) using statistical sampling.
    Matches AstroGrader's `calculate_channel_stats` in `astro-grader/src-tauri/src/fits/utils.rs`.
    """
    flat = data.reshape(-1)
    if flat.size == 0:
        return 0.0, 0.0
    sample = flat[::stride]
    if sample.size == 0:
        sample = flat

    med = float(np.median(sample))
    deviations = np.abs(sample - med)
    mad = float(np.median(deviations))
    return med, mad


def calculate_stf(
    medians: list[float],
    mads: list[float],
    rgb_linked: bool = True,
    shadows_clipping: float = -2.80,
    target_bg: float = 0.25,
) -> list[Tuple[float, float, float]]:
    """
    Calculates AutoSTF parameters [c0 (shadows), m (midtones), c1 (highlights)] per channel.
    Matches AstroGrader's Rust algorithm with numerical safeguards against blowout / black crush.
    """
    n = len(medians)
    scaled_mads = [max(float(mad) * 1.4826, 1e-5) for mad in mads]
    channels = [(0.0, 0.5, 1.0) for _ in range(n)]

    if rgb_linked and n == 3:
        # Astronomical frames are dark (median << 0.5); only true inverted negatives exceed 0.85
        inverted = sum(1 for m in medians if m > 0.85)
        if inverted < n:
            c0_sum = 0.0
            m_avg = 0.0
            for c in range(n):
                c0_sum += medians[c] + shadows_clipping * scaled_mads[c]
                m_avg += medians[c]
            avg_med = m_avg / float(n)
            # Ensure c0 is strictly below median so median - c0 > 0
            c0 = float(np.clip(c0_sum / float(n), 0.0, max(0.0, avg_med - 1e-4)))
            diff = max(avg_med - c0, 1e-5)
            m = mtf_scalar(target_bg, diff)
            m = float(np.clip(m, 0.005, 0.995))
            channels = [(c0, m, 1.0) for _ in range(n)]
        else:
            c1_sum = 0.0
            m_avg = 0.0
            for c in range(n):
                m_avg += medians[c]
                c1_sum += medians[c] - shadows_clipping * scaled_mads[c]
            avg_med = m_avg / float(n)
            c1 = float(np.clip(c1_sum / float(n), min(1.0, avg_med + 1e-4), 1.0))
            diff = max(c1 - avg_med, 1e-5)
            m = mtf_scalar(diff, target_bg)
            m = float(np.clip(m, 0.005, 0.995))
            channels = [(0.0, m, c1) for _ in range(n)]
    else:
        out = []
        for c in range(n):
            if medians[c] <= 0.85:
                raw_c0 = medians[c] + shadows_clipping * scaled_mads[c]
                c0 = float(np.clip(raw_c0, 0.0, max(0.0, medians[c] - 1e-4)))
                diff = max(medians[c] - c0, 1e-5)
                m = mtf_scalar(target_bg, diff)
                m = float(np.clip(m, 0.005, 0.995))
                out.append((c0, m, 1.0))
            else:
                raw_c1 = medians[c] - shadows_clipping * scaled_mads[c]
                c1 = float(np.clip(raw_c1, min(1.0, medians[c] + 1e-4), 1.0))
                diff = max(c1 - medians[c], 1e-5)
                m = mtf_scalar(diff, target_bg)
                m = float(np.clip(m, 0.005, 0.995))
                out.append((0.0, m, c1))
        channels = out

    return channels


def debayer_image(raw_2d: np.ndarray, bayer_pat: str) -> np.ndarray:
    """
    Debayers 2D CFA sensor data into 3-channel [H, W, 3] RGB float32.
    """
    pat = bayer_pat.upper().strip()
    code_map = {
        "RGGB": cv2.COLOR_BayerBG2RGB,
        "BGGR": cv2.COLOR_BayerRG2RGB,
        "GRBG": cv2.COLOR_BayerGB2RGB,
        "GBRG": cv2.COLOR_BayerGR2RGB,
    }
    if pat in code_map:
        scaled = np.clip(raw_2d * 65535.0, 0, 65535).astype(np.uint16)
        debayered_u16 = cv2.cvtColor(scaled, code_map[pat])
        return debayered_u16.astype(np.float32) / 65535.0

    # Fallback to simple bilinear demosaic
    h, w = raw_2d.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    for c in range(3):
        rgb[:, :, c] = raw_2d
    return rgb


def load_fits_unified_rgb(
    path: Union[str, Path],
    explicit_bayer: Optional[str] = None,
) -> Tuple[np.ndarray, Dict[str, Union[str, int, float, None]]]:
    """
    Loads any FITS file into the Unified 3-Channel RGB float32 format [H, W, 3].
    - If Bayer pattern is detected or passed: debayers to full color RGB.
    - If monochrome: replicates R = G = B across 3 channels.
    - Preserves native dynamic range normalized to [0.0, 1.0].
    """
    path = Path(path)
    with fits.open(path, memmap=False) as hdul:
        hdu = None
        for item in hdul:
            if item.data is not None and item.data.ndim in (2, 3):
                hdu = item
                break
        if hdu is None:
            raise ValueError(f"No 2D or 3D image data found in FITS: {path}")

        header = hdu.header
        raw_data = np.asarray(hdu.data, dtype=np.float32)

    # Clean non-finite values (NaN / Inf) and clip negative bias artifacts
    np.nan_to_num(raw_data, copy=False, nan=0.0, posinf=1.0, neginf=0.0)
    raw_data = np.maximum(raw_data, 0.0)

    # Note: astropy.io.fits AUTOMATICALLY applies BSCALE and BZERO on load!
    # Normalize pixel range to [0.0, 1.0] based on actual max ADU
    bitpix = abs(header.get("BITPIX", 16))
    max_val = float(np.max(raw_data)) if raw_data.size > 0 else 1.0

    if max_val > 255.0 or bitpix == 16:
        # Standard 16-bit unsigned (0..65535)
        data_norm = np.clip(raw_data / 65535.0, 0.0, 1.0)
    elif max_val > 1.0 or bitpix == 8:
        # 8-bit unsigned (0..255)
        data_norm = np.clip(raw_data / 255.0, 0.0, 1.0)
    else:
        # Already normalized floating point [0.0, 1.0]
        data_norm = np.clip(raw_data, 0.0, 1.0)

    # Extract Bayer pattern from header
    bayer_pat = explicit_bayer or header.get("BAYERPAT") or header.get("COLORTYP")
    if isinstance(bayer_pat, str):
        bayer_pat = bayer_pat.strip().upper()

    # Helper to parse float header values safely
    def _parse_header_float(key_names: list, default_val: float) -> float:
        for k in key_names:
            v = header.get(k)
            if v is not None:
                try:
                    vf = float(v)
                    if math.isfinite(vf) and vf > 0.0:
                        return vf
                except (ValueError, TypeError):
                    pass
        return default_val

    focal_length_mm = _parse_header_float(["FOCALLEN", "FOCAL"], 250.0)
    pixel_size_um = _parse_header_float(["XPIXSZ", "PIXSIZE1", "PIXSIZE"], 2.9)
    pixel_scale = float(np.clip((206.265 * pixel_size_um) / max(focal_length_mm, 1e-3), 0.1, 10.0))

    metadata = {
        "file_name": path.name,
        "width": data_norm.shape[-1],
        "height": data_norm.shape[-2],
        "bayer_pattern": bayer_pat,
        "exposure": header.get("EXPTIME"),
        "filter": header.get("FILTER"),
        "camera": header.get("INSTRUME"),
        "focal_length": focal_length_mm,
        "pixel_size": pixel_size_um,
        "pixel_scale": pixel_scale,
    }

    # Handle shape
    if data_norm.ndim == 2:
        if bayer_pat:
            rgb_f32 = debayer_image(data_norm, bayer_pat)
        else:
            # Monochrome: replicate across R=G=B
            rgb_f32 = np.stack([data_norm, data_norm, data_norm], axis=-1)
    elif data_norm.ndim == 3:
        if data_norm.shape[0] == 3:
            # Planar [3, H, W] -> Interleaved [H, W, 3]
            rgb_f32 = np.transpose(data_norm, (1, 2, 0))
        elif data_norm.shape[2] == 3:
            rgb_f32 = data_norm
        else:
            # Single slice or unsupported 3D -> take first slice as mono
            mono = data_norm[0]
            rgb_f32 = np.stack([mono, mono, mono], axis=-1)
    else:
        raise ValueError(f"Unsupported FITS dimension: {data_norm.ndim}")

    rgb_f32 = rgb_f32.astype(np.float32)

    # Frame baseline statistics on linear array before stretching
    frame_med, frame_mad = calculate_channel_stats(rgb_f32, stride=100)
    metadata["frame_median"] = frame_med
    metadata["frame_mad"] = frame_mad

    return rgb_f32, metadata


def compute_tile_metadata(
    tile_linear_rgb: np.ndarray,
    tile_stf_rgb: np.ndarray,
    frame_median: float,
    frame_mad: float,
    pixel_scale: float = 2.39,
) -> list[float]:
    """
    Computes a normalized 6-element float32 optical and statistical metadata vector:
    meta[0]: Normalized pixel scale (arcsec/px)
    meta[1]: Relative background median vs full frame
    meta[2]: Relative noise / contrast ratio vs full frame
    meta[3]: Normalized star count in tile
    meta[4]: Mean stellar FWHM (px)
    meta[5]: Mean stellar eccentricity [0.0, 1.0]
    """
    # 0. Normalized Pixel Scale
    m0 = float(np.log1p(max(0.0, float(pixel_scale))) / 2.5)

    # 1. & 2. Tile Linear Statistics
    tile_med, tile_mad = calculate_channel_stats(tile_linear_rgb, stride=16)
    m1 = float(np.clip((tile_med / max(float(frame_median), 1e-6)) / 3.0, 0.0, 2.0))
    m2 = float(np.clip((tile_mad / max(float(frame_mad), 1e-6)) / 3.0, 0.0, 2.0))

    # STF tile luminance for stellar blob analysis
    if tile_stf_rgb.ndim == 3:
        if tile_stf_rgb.shape[0] == 3 and tile_stf_rgb.shape[2] != 3:
            # Planar [3, H, W]
            lum = np.mean(tile_stf_rgb, axis=0)
        else:
            # Interleaved [H, W, 3]
            lum = np.mean(tile_stf_rgb, axis=2)
    else:
        lum = tile_stf_rgb

    if lum.dtype == np.uint8:
        lum = lum.astype(np.float32) / 255.0
    else:
        lum = lum.astype(np.float32)

    stf_med, stf_mad = calculate_channel_stats(lum, stride=16)
    thresh = float(stf_med + 4.0 * 1.4826 * stf_mad)
    binary = (lum > thresh).astype(np.uint8)

    num_labels, labels_im, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    valid_blobs = []
    for lbl in range(1, num_labels):
        area = int(stats[lbl, cv2.CC_STAT_AREA])
        if 3 <= area <= 400:
            x = int(stats[lbl, cv2.CC_STAT_LEFT])
            y = int(stats[lbl, cv2.CC_STAT_TOP])
            w = int(stats[lbl, cv2.CC_STAT_WIDTH])
            h = int(stats[lbl, cv2.CC_STAT_HEIGHT])
            sub_lum = lum[y : y + h, x : x + w]
            sub_mask = (labels_im[y : y + h, x : x + w] == lbl)
            peak_val = float(np.max(sub_lum[sub_mask])) if np.any(sub_mask) else 0.0
            valid_blobs.append((area, lbl, x, y, w, h, peak_val))

    star_count = len(valid_blobs)
    m3 = float(min(1.0, star_count / 50.0))

    if star_count > 0:
        areas = np.array([b[0] for b in valid_blobs], dtype=np.float32)
        fwhm_px = 2.0 * np.sqrt(areas / np.pi)
        mean_fwhm = float(np.mean(fwhm_px))
        m4 = float(min(1.0, mean_fwhm / 15.0))

        # Top 15 brightest stellar blobs for eccentricity
        valid_blobs.sort(key=lambda b: b[6], reverse=True)
        top_blobs = valid_blobs[:15]
        eccs = []
        for b in top_blobs:
            _, lbl, x, y, w, h, _ = b
            blob_mask = (labels_im[y : y + h, x : x + w] == lbl).astype(np.uint8)
            blob_lum = np.maximum(0.0, lum[y : y + h, x : x + w] - stf_med) * blob_mask
            mom = cv2.moments(blob_lum if np.sum(blob_lum) > 1e-6 else blob_mask)
            m00 = mom["m00"]
            if m00 > 1e-6:
                mu20 = mom["mu20"] / m00
                mu02 = mom["mu02"] / m00
                mu11 = mom["mu11"] / m00
                delta = math.sqrt(max(0.0, (mu20 - mu02) ** 2 + 4.0 * (mu11 ** 2)))
                lambda1 = ((mu20 + mu02) + delta) / 2.0
                lambda2 = max(0.0, ((mu20 + mu02) - delta) / 2.0)
                if lambda1 > 1e-6:
                    ecc = math.sqrt(max(0.0, 1.0 - (lambda2 / lambda1)))
                    eccs.append(min(1.0, ecc))

        m5 = float(np.clip(np.mean(eccs), 0.0, 1.0)) if eccs else 0.0
    else:
        m4 = 0.0
        m5 = 0.0

    return [round(m0, 4), round(m1, 4), round(m2, 4), round(m3, 4), round(m4, 4), round(m5, 4)]


def to_auto_stf_f32(
    img_rgb: np.ndarray,
    shadows_clipping: float = -2.80,
    target_bg: float = 0.25,
    rgb_linked: bool = True,
) -> np.ndarray:
    """
    Transforms unified 3-channel RGB float32 into continuous AutoSTF float32 [0.0, 1.0].
    Preserves full 32-bit floating point precision (no 8-bit quantization).
    """
    assert img_rgb.ndim == 3 and img_rgb.shape[2] == 3, "Input must be [H, W, 3]"
    medians, mads = [], []
    for c in range(3):
        med, mad = calculate_channel_stats(img_rgb[:, :, c], stride=100)
        medians.append(med)
        mads.append(mad)

    stf_params = calculate_stf(
        medians,
        mads,
        rgb_linked=rgb_linked,
        shadows_clipping=shadows_clipping,
        target_bg=target_bg,
    )

    out = np.zeros_like(img_rgb, dtype=np.float32)
    for c in range(3):
        c0, m, c1 = stf_params[c]
        denom = max(c1 - c0, 1e-6)
        norm_ch = np.clip((img_rgb[:, :, c] - c0) / denom, 0.0, 1.0)
        out[:, :, c] = mtf_array(m, norm_ch)

    return out


def to_asinh_f32(
    img_rgb: np.ndarray,
    beta: float = 30.0,
    black_percentile: float = 0.5,
) -> np.ndarray:
    """
    Astronomical ArcSinh (Asinh) normalization on 3-channel float32.
    Smoothly maps faint nebulosity/streaks without clipping stars or blowing out background.
    """
    assert img_rgb.ndim == 3 and img_rgb.shape[2] == 3, "Input must be [H, W, 3]"
    out = np.zeros_like(img_rgb, dtype=np.float32)
    for c in range(3):
        ch = img_rgb[:, :, c]
        bp = float(np.percentile(ch, black_percentile))
        norm = np.maximum(0.0, ch - bp) / max(1.0 - bp, 1e-4)
        out[:, :, c] = np.arcsinh(beta * norm) / np.arcsinh(beta)
    return np.clip(out, 0.0, 1.0)


def to_stf_u8(
    img_rgb: np.ndarray,
    shadows_clipping: float = -2.80,
    target_bg: float = 0.25,
    rgb_linked: bool = True,
    mode: str = "stf",
) -> np.ndarray:
    """
    Renders 8-bit RGB image [H, W, 3] in uint8 [0..255] for visual preview and tagging UI.
    Supports AutoSTF, Asinh, and Linear display modes.
    """
    if mode == "asinh":
        beta = max(1.0, (target_bg / 0.25) * 35.0)
        stretched = to_asinh_f32(img_rgb, beta=beta)
    elif mode == "linear":
        stretched = img_rgb
    else:
        stretched = to_auto_stf_f32(
            img_rgb,
            shadows_clipping=shadows_clipping,
            target_bg=target_bg,
            rgb_linked=rgb_linked,
        )
    return np.clip(stretched * 255.0, 0, 255).astype(np.uint8)


def apply_stretch_jitter(
    img_rgb: np.ndarray,
    clipping_range: Tuple[float, float] = (-3.2, -2.4),
    target_bg_range: Tuple[float, float] = (0.20, 0.30),
) -> np.ndarray:
    """
    Applies random STF stretch jitter for training data augmentation.
    Teaches CNN to be invariant to slight exposure or stretch differences.
    """
    clip = float(np.random.uniform(*clipping_range))
    bg = float(np.random.uniform(*target_bg_range))
    return to_auto_stf_f32(img_rgb, shadows_clipping=clip, target_bg=bg)
