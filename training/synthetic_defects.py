"""
Physics-Based Synthetic Defect Generator for Astronomical Defect Detection.
Operates strictly on clean linear-space RGB float32 tiles [512, 512, 3] BEFORE AutoSTF stretch.
Injects realistic astronomical artifacts: airplanes, satellite streaks, star trails,
unfocused star donuts, and optical obstructions.
"""

import math
import random
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np


def _random_crossing_line(size: int = 512) -> Tuple[float, float, float, float]:
    """Generates a random straight line that enters from one edge and exits on another edge."""
    edges = ["left", "right", "top", "bottom"]
    edge1, edge2 = random.sample(edges, 2)

    def edge_point(edge: str) -> Tuple[float, float]:
        if edge == "left":
            return 0.0, random.uniform(10.0, size - 10.0)
        elif edge == "right":
            return float(size), random.uniform(10.0, size - 10.0)
        elif edge == "top":
            return random.uniform(10.0, size - 10.0), 0.0
        else:  # bottom
            return random.uniform(10.0, size - 10.0), float(size)

    x1, y1 = edge_point(edge1)
    x2, y2 = edge_point(edge2)
    return x1, y1, x2, y2


def inject_synthetic_satellite(
    linear_tile: np.ndarray,
    bg_med: float,
    bg_mad: float,
) -> Tuple[np.ndarray, str, Dict]:
    """
    Injects a single straight satellite streak into a linear-space tile.
    Optionally simulates satellite tumbling flare with slow, smooth sinusoidal modulation.
    """
    h, w, c = linear_tile.shape
    streak_layer = np.zeros((h, w), dtype=np.float32)

    x1, y1, x2, y2 = _random_crossing_line(h)

    # Length of track
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    num_steps = max(int(length * 2.0), 200)

    # Tumbling modulation: reduced probability and lower frequency to prevent
    # looking like rapid airplane strobe flashes
    is_tumbling = (random.random() < 0.15)
    freq = random.uniform(0.3, 1.8)
    phase = random.uniform(0.0, 2.0 * math.pi)

    t_vals = np.linspace(0.0, 1.0, num_steps, dtype=np.float32)
    px_coords = np.clip(np.round(x1 + t_vals * dx).astype(np.int32), 0, w - 1)
    py_coords = np.clip(np.round(y1 + t_vals * dy).astype(np.int32), 0, h - 1)

    if is_tumbling:
        brightness_mod = 0.5 + 0.5 * np.sin(2.0 * np.pi * freq * t_vals + phase)
    else:
        brightness_mod = np.ones(num_steps, dtype=np.float32)

    for i in range(num_steps):
        streak_layer[py_coords[i], px_coords[i]] = max(
            streak_layer[py_coords[i], px_coords[i]],
            float(brightness_mod[i]),
        )

    # Convolve with Gaussian PSF (sigma in [0.7, 1.4] px for sharp satellite streak)
    sigma = random.uniform(0.7, 1.4)
    ksize = int(math.ceil(sigma * 4.0)) * 2 + 1
    blurred = cv2.GaussianBlur(streak_layer, (ksize, ksize), sigmaX=sigma, sigmaY=sigma)

    # Amplitude scaling based on noise floor (including faint streaks)
    amp_factor = random.uniform(3.0, 18.0) * max(float(bg_mad), 1e-5)
    injected_streak = blurred * amp_factor

    # Slightly chromatic or neutral white
    chroma = [random.uniform(0.9, 1.1) for _ in range(3)]
    modified = np.copy(linear_tile)
    for ch in range(3):
        modified[:, :, ch] += injected_streak * chroma[ch]

    modified = np.clip(modified, 0.0, 1.0)

    annot = {
        "type": "line",
        "label": "satellite_streak",
        "x1": round(x1, 1),
        "y1": round(y1, 1),
        "x2": round(x2, 1),
        "y2": round(y2, 1),
        "thickness": 12.0,
    }

    return modified, "satellite_streak", annot


def inject_synthetic_airplane(
    linear_tile: np.ndarray,
    bg_med: float,
    bg_mad: float,
) -> Tuple[np.ndarray, str, Dict]:
    """
    Injects an airplane track matching real optical/sensor physics:
    - Central steady fuselage or navigation streak.
    - Asymmetric or dual wingtip tracks with offset scaling from [6, 45] px (accounting
      for altitude and focal length).
    - Periodic anti-collision strobes rendered as streaked dashes (15-60 px) rather than dots.
    - True-to-life OSC camera chromatic weights (amber/white fuselage, deep red / green-white wing strobes).
    """
    h, w, _ = linear_tile.shape
    x1, y1, x2, y2 = _random_crossing_line(h)

    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1e-4:
        dist = 1.0
    ux = dx / dist
    uy = dy / dist
    # Perpendicular unit normal
    nx = -uy
    ny = ux

    # Wing separation accounts for altitude (high cruise = narrow, low flyby = wide)
    # and optical focal length. Range: [6.0, 45.0] px
    offset = random.uniform(6.0, 45.0)

    # 3-channel canvas for colored strobes and fuselage
    plane_layer = np.zeros((h, w, 3), dtype=np.float32)

    # 1. Central fuselage / navigation streak (continuous)
    num_steps = max(int(dist * 2.0), 300)
    t_vals = np.linspace(0.0, dist, num_steps, dtype=np.float32)

    # Warm amber / white tint typical for OSC cameras on fuselage light
    fuselage_rgb = np.array([
        random.uniform(0.9, 1.0),
        random.uniform(0.7, 0.88),
        random.uniform(0.2, 0.45)
    ], dtype=np.float32)

    for d in t_vals:
        cx = int(round(x1 + d * ux))
        cy = int(round(y1 + d * uy))
        if 0 <= cx < w and 0 <= cy < h:
            for ch in range(3):
                plane_layer[cy, cx, ch] = max(plane_layer[cy, cx, ch], fuselage_rgb[ch])

    # 2. Side tracks (wingtip lights and periodic dashes)
    # In real flights, one wing carries port (red) strobe/nav, the other starboard (green/white).
    # Side track presence depends on focal length and orientation
    has_left_track = True
    has_right_track = (random.random() < 0.75)  # Can be single-sided or dual-sided

    # Strobe dash parameters:
    # Strobe duration translates to a streak segment of length dash_len during exposure
    dash_len = random.uniform(15.0, 55.0)
    strobe_period = random.uniform(90.0, 320.0)  # distance between flash starts

    # Left wing track: port strobe (predominantly red/amber pulses)
    if has_left_track:
        sign = -1.0
        # Determine whether left track has a faint continuous baseline
        faint_baseline = random.uniform(0.0, 0.25)
        if faint_baseline > 0.05:
            for d in t_vals:
                wx = int(round(x1 + d * ux + sign * offset * nx))
                wy = int(round(y1 + d * uy + sign * offset * ny))
                if 0 <= wx < w and 0 <= wy < h:
                    plane_layer[wy, wx, 0] = max(plane_layer[wy, wx, 0], faint_baseline)
                    plane_layer[wy, wx, 1] = max(plane_layer[wy, wx, 1], faint_baseline * 0.5)

        # Strobes as streaked dashes
        strobe_starts = np.arange(random.uniform(0.0, strobe_period * 0.5), dist, strobe_period)
        for s_start in strobe_starts:
            s_end = min(s_start + dash_len, dist)
            s_steps = max(int((s_end - s_start) * 2.0), 20)
            dash_d = np.linspace(s_start, s_end, s_steps)
            intensity = random.uniform(1.8, 3.8)
            # Port red strobe
            strobe_rgb = (intensity * 1.0, intensity * random.uniform(0.3, 0.5), intensity * 0.1)
            for d in dash_d:
                wx = int(round(x1 + d * ux + sign * offset * nx))
                wy = int(round(y1 + d * uy + sign * offset * ny))
                if 0 <= wx < w and 0 <= wy < h:
                    for ch in range(3):
                        plane_layer[wy, wx, ch] = max(plane_layer[wy, wx, ch], strobe_rgb[ch])

    # Right wing track: starboard strobe (green/white or white flash)
    if has_right_track:
        sign = 1.0
        # Right offset can have slight perspective difference or asymmetry
        r_offset = offset * random.uniform(0.85, 1.15)
        # Periodic dashes
        strobe_starts = np.arange(random.uniform(0.0, strobe_period * 0.5), dist, strobe_period)
        for s_start in strobe_starts:
            s_end = min(s_start + dash_len * random.uniform(0.8, 1.2), dist)
            s_steps = max(int((s_end - s_start) * 2.0), 20)
            dash_d = np.linspace(s_start, s_end, s_steps)
            intensity = random.uniform(1.5, 3.5)
            # Green / white strobe
            strobe_rgb = (intensity * random.uniform(0.5, 1.0), intensity * 1.0, intensity * random.uniform(0.4, 0.9))
            for d in dash_d:
                wx = int(round(x1 + d * ux + sign * r_offset * nx))
                wy = int(round(y1 + d * uy + sign * r_offset * ny))
                if 0 <= wx < w and 0 <= wy < h:
                    for ch in range(3):
                        plane_layer[wy, wx, ch] = max(plane_layer[wy, wx, ch], strobe_rgb[ch])

    # Convolve with Gaussian PSF (sigma in [1.0, 2.0] px)
    sigma = random.uniform(1.0, 2.0)
    ksize = int(math.ceil(sigma * 4.0)) * 2 + 1
    for ch in range(3):
        plane_layer[:, :, ch] = cv2.GaussianBlur(plane_layer[:, :, ch], (ksize, ksize), sigmaX=sigma, sigmaY=sigma)

    # Scale amplitude relative to background noise floor
    amp_factor = random.uniform(10.0, 45.0) * max(float(bg_mad), 1e-5)
    modified = np.clip(linear_tile + plane_layer * amp_factor, 0.0, 1.0)

    annot = {
        "type": "line",
        "label": "airplane",
        "x1": round(x1, 1),
        "y1": round(y1, 1),
        "x2": round(x2, 1),
        "y2": round(y2, 1),
        "thickness": round(offset * 2.2 + 14.0, 1),
    }

    return modified, "airplane", annot


def inject_synthetic_psf_defect(
    linear_tile: np.ndarray,
    bg_med: float,
    bg_mad: float,
    mode: str = "star_trail",
) -> Tuple[np.ndarray, Optional[str], Optional[Union[Dict, List[Dict]]]]:
    """
    Simulates optical PSF defects:
    - mode="star_trail": Directional motion blur applied to stellar flux.
    - mode="unfocused_star": Defocus donut ring kernel applied to stellar flux.
    """
    h, w, c = linear_tile.shape

    # Check star presence gate
    peak_val = float(np.percentile(linear_tile, 99.8))
    if (peak_val - bg_med) <= 6.0 * max(float(bg_mad), 1e-5):
        # Tile has no bright stellar PSFs to trail or defocus
        return linear_tile, None, None

    # Separate stellar flux above background
    stars_layer = np.maximum(0.0, linear_tile - bg_med)
    bg_layer = np.minimum(linear_tile, bg_med + 2.0 * bg_mad)

    if mode == "star_trail":
        length = int(random.uniform(8, 28))
        angle_deg = random.uniform(0.0, 180.0)
        angle_rad = math.radians(angle_deg)

        # Build directional motion-blur line kernel
        ksize = max(length * 2 + 1, 15)
        kernel = np.zeros((ksize, ksize), dtype=np.float32)
        center = ksize // 2

        dx = math.cos(angle_rad)
        dy = math.sin(angle_rad)
        t_vals = np.linspace(-length / 2.0, length / 2.0, length * 3)
        for t in t_vals:
            kx = int(round(center + t * dx))
            ky = int(round(center + t * dy))
            if 0 <= kx < ksize and 0 <= ky < ksize:
                kernel[ky, kx] += 1.0

        ksum = np.sum(kernel)
        if ksum > 1e-6:
            kernel /= ksum
        # Slight flux compensation so trailed stars stay prominent
        kernel *= 1.35

        convolved_stars = np.zeros_like(stars_layer)
        for ch in range(c):
            convolved_stars[:, :, ch] = cv2.filter2D(stars_layer[:, :, ch], -1, kernel)

    else:  # unfocused_star
        outer_radius = int(random.uniform(4, 10))
        hole_ratio = random.uniform(0.0, 0.45)
        inner_radius = int(outer_radius * hole_ratio)

        ksize = outer_radius * 2 + 5
        kernel = np.zeros((ksize, ksize), dtype=np.float32)
        center = ksize // 2

        y_idx, x_idx = np.ogrid[:ksize, :ksize]
        dist_sq = (x_idx - center) ** 2 + (y_idx - center) ** 2
        ring_mask = (dist_sq <= outer_radius ** 2) & (dist_sq >= inner_radius ** 2)
        kernel[ring_mask] = 1.0
        # Soften edges
        kernel = cv2.GaussianBlur(kernel, (3, 3), 0.7)

        ksum = np.sum(kernel)
        if ksum > 1e-6:
            kernel /= ksum

        # Boost star flux before convolution so donuts remain visible above sky background
        boosted_stars = stars_layer * random.uniform(2.5, 4.5)
        convolved_stars = np.zeros_like(stars_layer)
        for ch in range(c):
            convolved_stars[:, :, ch] = cv2.filter2D(boosted_stars[:, :, ch], -1, kernel)

    modified = np.clip(bg_layer + convolved_stars, 0.0, 1.0)

    # Extract bounding boxes around top brightest convolved stars for YOLO
    lum = np.mean(convolved_stars, axis=2)
    star_thresh = float(bg_med + 3.0 * max(bg_mad, 1e-5))
    star_mask = (lum > star_thresh).astype(np.uint8)

    contours, _ = cv2.findContours(star_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    # Sort contours by area / intensity descending
    valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) >= 12.0]
    valid_contours.sort(key=cv2.contourArea, reverse=True)

    for cnt in valid_contours[:10]:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        # Pad box slightly
        pad = 6
        x_pad = max(0, bx - pad)
        y_pad = max(0, by - pad)
        w_pad = min(w - x_pad, bw + pad * 2)
        h_pad = min(h - y_pad, bh + pad * 2)
        boxes.append({
            "type": "box",
            "label": mode,
            "x": float(x_pad),
            "y": float(y_pad),
            "width": float(w_pad),
            "height": float(h_pad),
        })

    if not boxes:
        # Fallback full box if no isolated bright contours
        boxes.append({
            "type": "box",
            "label": mode,
            "x": 0.0,
            "y": 0.0,
            "width": float(w),
            "height": float(h),
        })

    return modified, mode, boxes


def inject_synthetic_obstruction(
    linear_tile: np.ndarray,
    bg_med: float,
    bg_mad: float,
) -> Tuple[np.ndarray, str, Dict]:
    """
    Injects an opaque or semi-translucent boundary obstruction (e.g. roof edge, telescope pier, cable).
    Creates a random edge/corner polygon, attenuates signal, and adds realistic Gaussian noise.
    """
    h, w, c = linear_tile.shape

    # Choose a corner: 0=top-left, 1=top-right, 2=bottom-right, 3=bottom-left
    corner = random.randint(0, 3)
    span_x = random.uniform(120.0, 320.0)
    span_y = random.uniform(120.0, 320.0)

    if corner == 0:  # top-left
        poly_pts = [[0.0, 0.0], [span_x, 0.0], [span_x * 0.7, span_y * 0.8], [0.0, span_y]]
    elif corner == 1:  # top-right
        poly_pts = [[w - span_x, 0.0], [float(w), 0.0], [float(w), span_y], [w - span_x * 0.7, span_y * 0.8]]
    elif corner == 2:  # bottom-right
        poly_pts = [[w - span_x * 0.8, h - span_y * 0.7], [float(w), h - span_y], [float(w), float(h)], [w - span_x, float(h)]]
    else:  # bottom-left
        poly_pts = [[0.0, h - span_y], [span_x * 0.8, h - span_y * 0.7], [span_x, float(h)], [0.0, float(h)]]

    pts_np = np.array(poly_pts, dtype=np.int32)
    binary_mask = np.zeros((h, w), dtype=np.float32)
    cv2.fillPoly(binary_mask, [pts_np], 1.0)

    # Soften edge with Gaussian blur (9..21 px)
    ksize = random.choice([9, 13, 17, 21])
    sigma = random.uniform(3.0, 7.0)
    smooth_mask = cv2.GaussianBlur(binary_mask, (ksize, ksize), sigmaX=sigma, sigmaY=sigma)
    smooth_mask_3d = np.repeat(smooth_mask[:, :, np.newaxis], c, axis=2)

    # Attenuation 85% to 98%
    attenuation = random.uniform(0.85, 0.98)
    simulated_dark = bg_med + np.random.normal(0.0, max(float(bg_mad), 1e-5), (h, w, c)).astype(np.float32)

    modified = linear_tile * (1.0 - smooth_mask_3d * attenuation) + simulated_dark * (smooth_mask_3d * attenuation)
    modified = np.clip(modified, 0.0, 1.0)

    annot = {
        "type": "polygon",
        "label": "obstruction",
        "points": [[round(p[0], 1), round(p[1], 1)] for p in poly_pts],
    }

    return modified, "obstruction", annot


def inject_random_synthetic_defect(
    linear_tile: np.ndarray,
    bg_med: float,
    bg_mad: float,
) -> Tuple[np.ndarray, Optional[str], Optional[Union[Dict, List[Dict]]]]:
    """
    Selects and injects a random synthetic defect onto a clean linear tile.
    """
    choices = [
        "satellite_streak",
        "airplane",
        "star_trail",
        "unfocused_star",
        "obstruction",
    ]
    random.shuffle(choices)

    for choice in choices:
        if choice == "satellite_streak":
            return inject_synthetic_satellite(linear_tile, bg_med, bg_mad)
        elif choice == "airplane":
            return inject_synthetic_airplane(linear_tile, bg_med, bg_mad)
        elif choice in ("star_trail", "unfocused_star"):
            mod_tile, cname, ann = inject_synthetic_psf_defect(linear_tile, bg_med, bg_mad, mode=choice)
            if cname is not None:
                return mod_tile, cname, ann
        elif choice == "obstruction":
            return inject_synthetic_obstruction(linear_tile, bg_med, bg_mad)

    # Fallback to satellite streak if PSF defect was skipped
    return inject_synthetic_satellite(linear_tile, bg_med, bg_mad)
