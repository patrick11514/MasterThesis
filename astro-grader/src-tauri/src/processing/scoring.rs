use crate::fits::ImageStats;

const W_STAR: f32 = 1.0;
const W_FWHM: f32 = 1.0; // (Increased) Punish blurry stars harder
const W_BG: f32 = 1.5; // (Massively Increased) Clouds tank the score!
const W_ECC: f32 = 0.6;
const W_TRAIL: f32 = 2.0;

const STAR_MAX: f32 = 5000.0; // Give credit for insanely clear nights
const FWHM_MIN: f32 = 1.5;
const FWHM_MAX: f32 = 6.0; // (Tightened)
const BG_MAX: f32 = 10.0; // (Tightened) A background of 10 is now maximum penalty!

fn clamp01(v: f32) -> f32 {
    if v.is_finite() {
        v.max(0.0).min(1.0)
    } else {
        0.0
    }
}

fn norm_star(star_count: Option<u32>) -> f32 {
    let v = star_count.map(|s| s as f32).unwrap_or(0.0);
    clamp01(v / STAR_MAX)
}

fn norm_fwhm(fwhm: Option<f32>) -> f32 {
    match fwhm {
        Some(f) if f.is_finite() => {
            // lower FWHM is better; invert to 0..1 where 0 is best, 1 is worst
            clamp01((f - FWHM_MIN) / (FWHM_MAX - FWHM_MIN))
        }
        _ => 1.0,
    }
}

pub fn norm_bg(bg: Option<f32>) -> f32 {
    clamp01(bg.unwrap_or(0.0) / BG_MAX)
}

fn norm_ecc(ecc: Option<f32>) -> f32 {
    // eccentricity is already 0..1, where 0 is round and 1 is extremely elongated.
    clamp01(ecc.unwrap_or(0.0))
}

/// Detect obvious trails. Returns a trail score in 0..1 and a boolean fast-reject.
// Heuristic: large eccentricity or large HFD/FWHM ratio indicates trails.
// Tuned thresholds: lower eccentricity and HFD/FWHM ratio to catch more subtle
// trails (conservative change per user's request).
const ECC_TRail_THRESHOLD: f32 = 0.6; // was 0.7
const HFD_FWHM_RATIO_THRESHOLD: f32 = 1.6; // was 2.0
const IS_TRAIL_FLAG_THRESHOLD: f32 = 0.55; // slightly lower than before

fn detect_trail(stats: &ImageStats) -> (f32, bool) {
    let ecc = norm_ecc(stats.eccentricity);
    let mut trail = 0.0f32;
    if ecc > ECC_TRail_THRESHOLD {
        trail = ecc;
    }

    if let (Some(hfd), Some(fwhm)) = (stats.hfd, stats.fwhm) {
        if fwhm > 0.0 && hfd / fwhm > HFD_FWHM_RATIO_THRESHOLD {
            trail = trail.max(1.0);
        }
    }

    let is_trail = trail > IS_TRAIL_FLAG_THRESHOLD;
    (clamp01(trail), is_trail)
}

/// Compute final quality score (higher better). Returns (score, trail_flag).
pub fn compute_score(stats: &ImageStats) -> (f32, bool) {
    let s_star = norm_star(stats.star_count);
    let s_fwhm = norm_fwhm(stats.fwhm);
    let s_bg = norm_bg(stats.background_contrast);
    let s_ecc = norm_ecc(stats.eccentricity);

    let (trail_score, is_trail) = detect_trail(stats);

    // Linear combination: star increases score; other factors reduce it.
    // We map to a range where higher is better; negative values indicate poor quality.
    let mut score = 0.0f32;
    score += W_STAR * s_star;
    score -= W_FWHM * s_fwhm;
    score -= W_BG * s_bg;
    score -= W_ECC * s_ecc;
    score -= W_TRAIL * trail_score;

    (score, is_trail)
}
