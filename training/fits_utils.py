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
    Matches AstroGrader's Rust algorithm.
    """
    n = len(medians)
    scaled_mads = [mad * 1.4826 for mad in mads]
    channels = [(0.0, 0.5, 1.0) for _ in range(n)]

    if rgb_linked and n == 3:
        inverted = sum(1 for m in medians if m > 0.5)
        if inverted < n:
            c0 = 0.0
            m_avg = 0.0
            for c in range(n):
                if 1.0 + scaled_mads[c] != 1.0:
                    c0 += medians[c] + shadows_clipping * scaled_mads[c]
                m_avg += medians[c]
            c0 = float(np.clip(c0 / float(n), 0.0, 1.0))
            m = mtf_scalar(target_bg, (m_avg / float(n)) - c0)
            channels = [(c0, m, 1.0) for _ in range(n)]
        else:
            c1 = 0.0
            m_avg = 0.0
            for c in range(n):
                m_avg += medians[c]
                if 1.0 + scaled_mads[c] != 1.0:
                    c1 += medians[c] - shadows_clipping * scaled_mads[c]
                else:
                    c1 += 1.0
            c1 = float(np.clip(c1 / float(n), 0.0, 1.0))
            m = mtf_scalar(c1 - (m_avg / float(n)), target_bg)
            channels = [(0.0, m, c1) for _ in range(n)]
    else:
        out = []
        for c in range(n):
            if medians[c] < 0.5:
                c0 = float(np.clip(medians[c] + shadows_clipping * scaled_mads[c], 0.0, 1.0))
                m = mtf_scalar(target_bg, medians[c] - c0)
                out.append((c0, m, 1.0))
            else:
                c1 = float(np.clip(medians[c] - shadows_clipping * scaled_mads[c], 0.0, 1.0))
                m = mtf_scalar(c1 - medians[c], target_bg)
                out.append((0.0, m, c1))
        channels = out

    return channels


def debayer_image(raw_2d: np.ndarray, bayer_pat: str) -> np.ndarray:
    """
    Debayers 2D CFA sensor data into 3-channel [H, W, 3] RGB float32.
    """
    pat = bayer_pat.upper().strip()
    # OpenCV expects uint16 or uint8 for cvtColor, or we can use demosaicing
    # Let's map pattern to OpenCV code:
    code_map = {
        "RGGB": cv2.COLOR_BayerBG2RGB,  # Note OpenCV Bayer naming convention is inverted
        "BGGR": cv2.COLOR_BayerRG2RGB,
        "GRBG": cv2.COLOR_BayerGB2RGB,
        "GBRG": cv2.COLOR_BayerGR2RGB,
    }
    # Direct Bilinear fallback if OpenCV code is unavailable or format issues
    if pat in code_map:
        # cv2.cvtColor requires uint8 or uint16, so let's scale float [0..1] to uint16, demosaic, then back to float
        scaled = np.clip(raw_2d * 65535.0, 0, 65535).astype(np.uint16)
        debayered_u16 = cv2.cvtColor(scaled, code_map[pat])
        return debayered_u16.astype(np.float32) / 65535.0

    # Fallback to simple bilinear demosaic
    h, w = raw_2d.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    # Default fallback: replicate raw as luminance
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
        # Find first image HDU
        hdu = None
        for item in hdul:
            if item.data is not None and item.data.ndim in (2, 3):
                hdu = item
                break
        if hdu is None:
            raise ValueError(f"No 2D or 3D image data found in FITS: {path}")

        header = hdu.header
        raw_data = np.asarray(hdu.data, dtype=np.float32)

    # Clean non-finite values (NaN / Inf)
    np.nan_to_num(raw_data, copy=False, nan=0.0, posinf=1.0, neginf=0.0)

    # Normalize raw data to [0.0, 1.0] based on bitpix or max value
    bitpix = header.get("BITPIX", 16)
    bzero = header.get("BZERO", 0.0)
    bscale = header.get("BSCALE", 1.0)
    raw_data = raw_data * bscale + bzero

    if bitpix == 16:
        max_possible = 65535.0
        data_norm = np.clip(raw_data / max_possible, 0.0, 1.0)
    elif bitpix == 8:
        data_norm = np.clip(raw_data / 255.0, 0.0, 1.0)
    elif bitpix in (32, -32, -64):
        # Float images: if already in [0, 1], keep; otherwise normalize by max
        max_val = float(np.max(raw_data)) if raw_data.size > 0 else 1.0
        if max_val > 1.0:
            data_norm = np.clip(raw_data / max(max_val, 65535.0), 0.0, 1.0)
        else:
            data_norm = np.clip(raw_data, 0.0, 1.0)
    else:
        max_val = float(np.max(raw_data)) if raw_data.size > 0 else 1.0
        data_norm = np.clip(raw_data / max(max_val, 1.0), 0.0, 1.0)

    # Extract Bayer pattern from header
    bayer_pat = explicit_bayer or header.get("BAYERPAT") or header.get("COLORTYP")
    if isinstance(bayer_pat, str):
        bayer_pat = bayer_pat.strip().upper()

    metadata = {
        "file_name": path.name,
        "width": data_norm.shape[-1],
        "height": data_norm.shape[-2],
        "bayer_pattern": bayer_pat,
        "exposure": header.get("EXPTIME"),
        "filter": header.get("FILTER"),
        "camera": header.get("INSTRUME"),
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

    return rgb_f32.astype(np.float32), metadata


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
    softening_factor: float = 3.0,
) -> np.ndarray:
    """
    Astronomical ArcSinh (Asinh) normalization on 3-channel float32.
    Preserves faint signals and satellite streaks while logarithmically compressing bright star cores.
    f(x) = asinh((x - median) / (softening * sigma))
    """
    assert img_rgb.ndim == 3 and img_rgb.shape[2] == 3, "Input must be [H, W, 3]"
    out = np.zeros_like(img_rgb, dtype=np.float32)
    for c in range(3):
        med, mad = calculate_channel_stats(img_rgb[:, :, c], stride=100)
        sigma = max(mad * 1.4826, 1e-5)
        # Shift sky background to ~0
        shifted = (img_rgb[:, :, c] - med) / (softening_factor * sigma)
        # Apply asinh
        stretched = np.arcsinh(np.maximum(shifted, 0.0))
        # Scale to [0.0, 1.0] by 99.8th percentile
        p99 = float(np.percentile(stretched, 99.8))
        scale = max(p99, 1.0)
        out[:, :, c] = np.clip(stretched / scale, 0.0, 1.0)
    return out


def to_stf_u8(
    img_rgb: np.ndarray,
    shadows_clipping: float = -2.80,
    target_bg: float = 0.25,
    rgb_linked: bool = True,
) -> np.ndarray:
    """
    Renders 8-bit RGB image [H, W, 3] in uint8 [0..255] for visual preview and tagging UI.
    """
    stf_float = to_auto_stf_f32(
        img_rgb,
        shadows_clipping=shadows_clipping,
        target_bg=target_bg,
        rgb_linked=rgb_linked,
    )
    return np.clip(stf_float * 255.0, 0, 255).astype(np.uint8)


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
