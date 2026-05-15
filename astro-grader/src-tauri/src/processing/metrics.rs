use std::{
    collections::HashMap,
    ffi::{CStr, c_char, c_void},
    path::PathBuf,
    ptr,
};

use rayon::prelude::*;
use sep_sys::*;

use crate::processing::scoring;
use crate::{
    file_picker::File,
    fits::{FitsFile, FrameState, ImageDataPixels, ImageStats},
    state::fe_state::FeState,
    state::{
        CalibrationProgressMessage, CalibrationProgressStep, CalibrationRunStatus,
        CalibrationStepKind, CalibrationStepStatus,
    },
};

const BACKGROUND_TILE_SIZE: i64 = 64;
const BACKGROUND_FILTER_SIZE: i64 = 3;
const STAR_DETECTION_SIGMA: f32 = 3.0;
const MIN_STAR_AREA: i32 = 5;

struct SepBackground(*mut sep_bkg);

impl Drop for SepBackground {
    fn drop(&mut self) {
        unsafe {
            if !self.0.is_null() {
                sep_bkg_free(self.0);
            }
        }
    }
}

struct SepCatalog(*mut sep_catalog);

impl Drop for SepCatalog {
    fn drop(&mut self) {
        unsafe {
            if !self.0.is_null() {
                sep_catalog_free(self.0);
            }
        }
    }
}

fn sep_error(status: i32) -> String {
    let mut buffer = [0 as c_char; 512];

    unsafe {
        sep_get_errmsg(status, buffer.as_mut_ptr());
        let short_message = CStr::from_ptr(buffer.as_ptr())
            .to_string_lossy()
            .trim()
            .to_string();

        let mut detail_buffer = [0 as c_char; 512];
        sep_get_errdetail(detail_buffer.as_mut_ptr());
        let detail = CStr::from_ptr(detail_buffer.as_ptr())
            .to_string_lossy()
            .trim()
            .to_string();

        if detail.is_empty() || detail == short_message {
            short_message
        } else {
            format!("{short_message}: {detail}")
        }
    }
}

fn build_sep_image(pixels: &[f32], width: usize, height: usize) -> sep_image {
    sep_image {
        data: pixels.as_ptr().cast::<c_void>(),
        noise: ptr::null(),
        mask: ptr::null(),
        segmap: ptr::null(),
        dtype: SEP_TFLOAT,
        ndtype: SEP_TFLOAT,
        mdtype: SEP_TINT,
        sdtype: SEP_TINT,
        segids: ptr::null_mut(),
        idcounts: ptr::null_mut(),
        numids: 0,
        w: width as i64,
        h: height as i64,
        noiseval: 0.0,
        noise_type: SEP_NOISE_NONE,
        gain: 1.0,
        maskthresh: 0.0,
    }
}

fn image_path_for_metrics(file: &File) -> PathBuf {
    file.calibrated_frame
        .as_ref()
        .cloned()
        .unwrap_or_else(|| file.path().clone())
}

pub fn classify_frame(
    raw_score: f32,
    normalized_score: Option<f32>,
    stats: &ImageStats,
    max_fwhm: f32,
) -> FrameState {
    let fwhm = stats.fwhm.unwrap_or(f32::INFINITY);
    let star_count = stats.star_count.unwrap_or(0);

    // ---------------------------------------------------------
    // 1. ABSOLUTE HARD LIMITS (Pass 1 & Pass 2)
    // ---------------------------------------------------------
    if star_count < 50 {
        return FrameState::Rejected;
    }

    if fwhm > max_fwhm {
        return FrameState::Rejected;
    }

    // ---------------------------------------------------------
    // 2. STATISTICAL LIMITS (Pass 2 Only)
    // ---------------------------------------------------------
    // Only apply the sigma threshold if we actually calculated the normal distribution!
    if let Some(norm_score) = normalized_score {
        let bg_norm = scoring::norm_bg(stats.background_contrast);
        const BG_REJECT_NORM_THRESHOLD: f32 = 0.25;

        // Reject if the score is mediocre (< 1.5 sigma) AND the background is washed out
        if norm_score < 0.50 && bg_norm > BG_REJECT_NORM_THRESHOLD {
            return FrameState::Rejected;
        }

        // Reject if the frame is generally very poor (> 2 sigma deviation)
        if norm_score < 0.33 {
            return FrameState::Rejected;
        }
    }

    FrameState::Accepted
}

pub fn extract_metrics_from_pixels(
    pixels: &[f32],
    width: usize,
    height: usize,
) -> Result<ImageStats, String> {
    if pixels.is_empty() || width == 0 || height == 0 {
        return Err("Image is empty".to_string());
    }

    let input_image = build_sep_image(pixels, width, height);

    let mut background_ptr = ptr::null_mut();
    let background_status = unsafe {
        sep_background(
            &input_image,
            BACKGROUND_TILE_SIZE,
            BACKGROUND_TILE_SIZE,
            BACKGROUND_FILTER_SIZE,
            BACKGROUND_FILTER_SIZE,
            0.0,
            &mut background_ptr,
        )
    };

    if background_status != 0 {
        return Err(format!(
            "SEP background estimation failed: {}",
            sep_error(background_status)
        ));
    }

    let background = SepBackground(background_ptr);
    let global_background = unsafe { sep_bkg_global(background.0) };
    let global_background_rms = unsafe { sep_bkg_globalrms(background.0) };

    let mut background_subtracted = pixels.to_vec();
    let subtract_status = unsafe {
        sep_bkg_subarray(
            background.0,
            background_subtracted.as_mut_ptr().cast::<c_void>(),
            SEP_TFLOAT,
        )
    };

    if subtract_status != 0 {
        return Err(format!(
            "SEP background subtraction failed: {}",
            sep_error(subtract_status)
        ));
    }

    let detection_image = build_sep_image(&background_subtracted, width, height);
    let detection_threshold = if global_background_rms > 0.0 {
        STAR_DETECTION_SIGMA * global_background_rms
    } else {
        STAR_DETECTION_SIGMA
    };

    let convolution: [f32; 9] = [1.0, 2.0, 1.0, 2.0, 4.0, 2.0, 1.0, 2.0, 1.0];
    let mut catalog_ptr = ptr::null_mut();
    let extract_status = unsafe {
        sep_extract(
            &detection_image,
            detection_threshold,
            SEP_THRESH_ABS,
            MIN_STAR_AREA,
            convolution.as_ptr(),
            3,
            3,
            SEP_FILTER_CONV,
            16,
            0.05,
            1,
            1.0,
            &mut catalog_ptr,
        )
    };

    if extract_status != 0 {
        return Err(format!(
            "SEP extraction failed: {}",
            sep_error(extract_status)
        ));
    }

    let background_contrast = if global_background_rms.abs() > f32::EPSILON {
        Some(global_background / global_background_rms)
    } else {
        Some(global_background)
    };

    if catalog_ptr.is_null() {
        return Ok(ImageStats {
            star_count: Some(0),
            fwhm: None,
            hfd: None,
            eccentricity: None,
            background_contrast,
            quality_score: None,
        });
    }

    let catalog = SepCatalog(catalog_ptr);
    let object_count = unsafe { (*catalog.0).nobj.max(0) as usize };

    let mut star_count = 0u32;
    let mut fwhm_sum = 0.0f32;
    let mut hfd_sum = 0.0f32;
    let mut eccentricity_sum = 0.0f32;

    for index in 0..object_count {
        let flag = unsafe { *(*catalog.0).flag.add(index) };
        if flag & (SEP_OBJ_TRUNC | SEP_OBJ_DOVERFLOW) != 0 {
            continue;
        }

        let a = unsafe { *(*catalog.0).a.add(index) } as f32;
        let b = unsafe { *(*catalog.0).b.add(index) } as f32;
        let x = unsafe { *(*catalog.0).x.add(index) };
        let y = unsafe { *(*catalog.0).y.add(index) };

        if !a.is_finite() || !b.is_finite() || a <= 0.0 || b <= 0.0 {
            continue;
        }

        let major = a.max(b);
        let minor = a.min(b);
        let fwhm = 2.354_820_3_f32 * (major * minor).sqrt();
        let eccentricity = if major > 0.0 {
            (1.0 - (minor * minor) / (major * major)).max(0.0).sqrt()
        } else {
            0.0
        };

        let mut flux_radius = [0.0f64; 1];
        let flux_fraction = [0.5f64; 1];
        let mut radius_flag = 0i16;
        let radius_status = unsafe {
            sep_flux_radius(
                &detection_image,
                x,
                y,
                (major as f64 * 4.0).max(4.0),
                0,
                0,
                0,
                ptr::null(),
                flux_fraction.as_ptr(),
                1,
                flux_radius.as_mut_ptr(),
                &mut radius_flag,
            )
        };

        let hfd = if radius_status == 0 && flux_radius[0].is_finite() && flux_radius[0] > 0.0 {
            (2.0 * flux_radius[0]) as f32
        } else {
            fwhm
        };

        star_count += 1;
        fwhm_sum += fwhm;
        hfd_sum += hfd;
        eccentricity_sum += eccentricity;
    }

    let usable_stars = star_count as f32;
    Ok(ImageStats {
        star_count: Some(star_count),
        fwhm: if usable_stars > 0.0 {
            Some(fwhm_sum / usable_stars)
        } else {
            None
        },
        hfd: if usable_stars > 0.0 {
            Some(hfd_sum / usable_stars)
        } else {
            None
        },
        eccentricity: if usable_stars > 0.0 {
            Some(eccentricity_sum / usable_stars)
        } else {
            None
        },
        background_contrast,
        quality_score: None,
    })
}

fn score_distribution(values: &[f32]) -> Vec<f32> {
    if values.is_empty() {
        return Vec::new();
    }

    let mean = values.iter().copied().sum::<f32>() / values.len() as f32;
    let variance = values
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta
        })
        .sum::<f32>()
        / values.len() as f32;

    let sigma = variance.sqrt();
    if sigma <= f32::EPSILON {
        return vec![1.0; values.len()];
    }

    // Inside score_distribution() in metrics.rs
    values
        .iter()
        .map(|value| {
            let z_score = (*value - mean) / sigma;

            // Map the [-3.0 to +3.0] curve smoothly into [0.0 to 1.0]
            // z = -3.0 -> 0.0 (Terrible)
            // z =  0.0 -> 0.5 (Average)
            // z = +3.0 -> 1.0 (Flawless)
            let mapped = 0.5 + (z_score / 6.0);

            mapped.clamp(0.0, 1.0)
        })
        .collect()
}

fn copy_metrics_back_to_raw_nights(
    state: &mut FeState,
    metrics_by_path: &HashMap<String, (ImageStats, FrameState)>,
) {
    for night_files in state.raw_nights.values_mut() {
        for raw_file in night_files {
            let path_buf = raw_file
                .calibrated_frame
                .clone()
                .unwrap_or_else(|| raw_file.path().clone());
            let path = normalize_path(&path_buf);

            if let Some((stats, state_value)) = metrics_by_path.get(&path) {
                raw_file.stats = Some(stats.clone());
                raw_file.state = *state_value;
            }
        }
    }
}

fn normalize_path(p: &PathBuf) -> String {
    // Use a consistent representation for keys: forward slashes, no trailing slash
    let s = p.to_string_lossy().to_string();
    let s = s.replace('\\', "/");
    if s.ends_with('/') && s.len() > 1 {
        s.trim_end_matches('/').to_string()
    } else {
        s
    }
}

pub fn run_metrics(
    state: &mut FeState,
    channel: tauri::ipc::Channel<CalibrationProgressMessage>,
    cross_night_reference: bool,
    max_fwhm: f32,
) -> Result<(), String> {
    // Helper to get current time
    fn now_millis() -> u64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    }

    // Build progress steps (one step per session)
    let mut steps: Vec<CalibrationProgressStep> = Vec::new();
    for session in &state.grouped_nights {
        let session_label = format!(
            "{} - {}",
            session.fingerprint.name, session.fingerprint.filter
        );
        steps.push(CalibrationProgressStep {
            id: format!("{}:Metrics", session.uuid),
            kind: CalibrationStepKind::Light,
            label: "Metrics".to_string(),
            session_uuid: session.uuid.clone(),
            session_label,
            count: session.lights.len(),
            completed_count: 0,
            skipped_count: 0,
            rejected_count: 0,
            status: CalibrationStepStatus::Pending,
            started_at: None,
            ended_at: None,
            error: None,
        });
    }

    let started_at = now_millis();
    let mut progress = CalibrationProgressMessage {
        started_at,
        finished_at: None,
        status: if steps.is_empty() {
            CalibrationRunStatus::Completed
        } else {
            CalibrationRunStatus::Running
        },
        current_step_id: None,
        steps: steps.clone(),
    };

    // send initial progress
    let _ = channel.send(progress.clone());

    let mut metrics_by_path = HashMap::<String, (ImageStats, FrameState)>::new();
    let mut raw_score_by_path = HashMap::<String, f32>::new();
    let mut score_sources_by_session = Vec::with_capacity(state.grouped_nights.len());

    for (session_index, session) in state.grouped_nights.iter_mut().enumerate() {
        progress.steps[session_index].status = CalibrationStepStatus::Running;
        progress.steps[session_index].started_at = Some(now_millis());
        progress.current_step_id = Some(progress.steps[session_index].id.clone());
        let _ = channel.send(progress.clone());

        let mut score_source = Vec::with_capacity(session.lights.len());

        // Parallel metrics extraction per-session. We collect per-light results and
        // then merge them back into the session in a single-threaded step to
        // avoid mutable aliasing issues.
        let outcomes: Vec<Result<(usize, ImageStats, FrameState), String>> = session
            .lights
            .par_iter()
            .enumerate()
            .map(|(i, light)| {
                let image_path = image_path_for_metrics(light);
                println!("[METRICS] Processing file {}: {}", i, image_path.display());

                let mut fits = FitsFile::new(image_path.clone()).map_err(|_| {
                    format!(
                        "Unable to open calibrated frame for metrics: {}",
                        image_path.display()
                    )
                })?;

                let image = ImageDataPixels::from_fits(&mut fits).map_err(|_| {
                    format!(
                        "Unable to read calibrated frame for metrics: {}",
                        image_path.display()
                    )
                })?;

                let mut stats = extract_metrics_from_pixels(
                    &image.pixels,
                    image.data.width,
                    image.data.height,
                )?;

                // Compute score and detect trails (raw_score preserved for final decisions)
                let (raw_score, is_trail) = scoring::compute_score(&stats);
                stats.quality_score = Some(raw_score);
                println!(
                    "  [RAW_SCORE] raw_score={:.3}, is_trail={}, stars={:?}, fwhm={:?}",
                    raw_score, is_trail, stats.star_count, stats.fwhm
                );

                let mut state_after = classify_frame(raw_score, None, &stats, max_fwhm);
                if is_trail {
                    state_after = FrameState::Rejected;
                    println!("  [STATE] Trail detected -> {:?}", state_after);
                } else {
                    println!("  [STATE] Initial classification -> {:?}", state_after);
                }

                Ok((i, stats, state_after))
            })
            .collect();

        // Check for errors
        for r in &outcomes {
            if let Err(e) = r {
                return Err(e.clone());
            }
        }

        // Merge results back into session and update progress counters
        let mut processed = 0usize;
        let mut rejected = 0usize;
        for r in outcomes.into_iter().map(|r| r.unwrap()) {
            let (idx, stats, new_state) = r;
            if let Some(light) = session.lights.get_mut(idx) {
                light.stats = Some(stats.clone());
                light.state = new_state;
                println!("[MERGE] File {} merged with state: {:?}", idx, new_state);
            }

            processed += 1;
            if new_state == FrameState::Rejected {
                rejected += 1;
            }

            // record star counts for cross-night scoring distribution
            if let Some(raw_score) = stats.quality_score {
                score_source.push(raw_score);
            }

            // record raw score for the image so cross-night normalization doesn't
            // mask obviously-bad raw frames when we decide final state
            if let Some(light) = session.lights.get(idx) {
                let image_path = image_path_for_metrics(light);
                let image_path_key = normalize_path(&image_path);
                raw_score_by_path
                    .insert(image_path_key.clone(), stats.quality_score.unwrap_or(0.0));
                metrics_by_path.insert(image_path_key, (stats.clone(), new_state));
            }
        }

        progress.steps[session_index].completed_count = processed;
        progress.steps[session_index].rejected_count = rejected;
        println!(
            "[SESSION] Session {} complete: {} processed, {} rejected",
            session_index, processed, rejected
        );
        let _ = channel.send(progress.clone());

        score_sources_by_session.push(score_source);
        progress.steps[session_index].ended_at = Some(now_millis());
        progress.steps[session_index].status = CalibrationStepStatus::Completed;
        progress.current_step_id = None;
        let _ = channel.send(progress.clone());
    }

    if cross_night_reference {
        println!("[CROSS_NIGHT] Applying cross-night normalization...");
        let all_scores: Vec<f32> = score_sources_by_session
            .iter()
            .flat_map(|scores: &Vec<f32>| scores.iter().copied())
            .collect();
        let scores = score_distribution(&all_scores);
        let mut score_index = 0usize;

        for session in &mut state.grouped_nights {
            for light in &mut session.lights {
                let score = scores.get(score_index).copied().unwrap_or(1.0);
                score_index += 1;
                let image_path = image_path_for_metrics(light);
                let key = normalize_path(&image_path);

                if let Some(stats) = &mut light.stats {
                    // store normalized score for UI, but decide final state using
                    // the raw score when it indicates clear failure
                    let raw_score = raw_score_by_path
                        .get(&key)
                        .copied()
                        .unwrap_or(stats.quality_score.unwrap_or(0.0));
                    stats.quality_score = Some(score);
                    println!(
                        "[CROSS_NIGHT_APPLY] {} raw={:.3}, normalized={:.3}, prev_state={:?}",
                        key, raw_score, score, light.state
                    );

                    // Replace the complex if/else block with just this:
                    if light.state == FrameState::Rejected {
                        println!("  -> Keeping previous Rejected state (e.g., Trail)");
                    } else {
                        // Let classify_frame decide using the new, tighter normalized score!
                        light.state = classify_frame(raw_score, Some(score), stats, max_fwhm);
                        println!("  -> Classified -> {:?}", light.state);
                    }

                    metrics_by_path.insert(key, (stats.clone(), light.state));
                }
            }
        }
    } else {
        println!("[PER_SESSION] Applying per-session normalization (no cross-night)...");
        for (session, score_source) in state
            .grouped_nights
            .iter_mut()
            .zip(score_sources_by_session.into_iter())
        {
            let scores = score_distribution(&score_source);

            for (light, score) in session.lights.iter_mut().zip(scores.into_iter()) {
                let image_path = image_path_for_metrics(light);
                let key = normalize_path(&image_path);

                if let Some(stats) = &mut light.stats {
                    // Get raw score for decision-making
                    let raw_score = raw_score_by_path
                        .get(&key)
                        .copied()
                        .unwrap_or(stats.quality_score.unwrap_or(0.0));
                    stats.quality_score = Some(score);
                    println!(
                        "[PER_SESSION_APPLY] {} raw={:.3}, normalized={:.3}, prev_state={:?}",
                        key, raw_score, score, light.state
                    );

                    // Preserve rejections found during Pass 1 (like obvious satellite trails or hard limits)
                    if light.state == FrameState::Rejected {
                        println!("  -> Keeping previous Rejected state");
                    } else {
                        // Let your centralized function handle ALL the logic!
                        light.state = classify_frame(raw_score, Some(score), stats, max_fwhm);
                        println!("  -> Classified with normalized score -> {:?}", light.state);
                    }

                    metrics_by_path.insert(key, (stats.clone(), light.state));
                }
            }
        }
    }

    // After the final per-frame classification (which may have changed states
    // during the cross-night or per-session distribution step), recompute the
    // rejected counts for each session so the progress reflects final values.
    for (session_index, session) in state.grouped_nights.iter().enumerate() {
        let mut rejected_final = 0usize;
        for light in &session.lights {
            if light.state == FrameState::Rejected {
                rejected_final += 1;
            }
        }

        if let Some(step) = progress.steps.get_mut(session_index) {
            step.rejected_count = rejected_final;
            step.completed_count = session.lights.len();
        }
    }

    // Send updated progress so the UI sees final rejected counts.
    let _ = channel.send(progress.clone());

    // Copy metrics back to raw_nights so FE can persist the final per-file states.
    println!(
        "[COPY_METRICS] Writing {} metrics back to raw_nights",
        metrics_by_path.len()
    );
    copy_metrics_back_to_raw_nights(state, &metrics_by_path);

    // Recompute final rejected counts from the authoritative `state` (raw/grouped
    // nights may have been updated by copy_metrics_back_to_raw_nights) and send
    // an updated progress message so the UI matches the returned FeState.
    let mut total_rejected_final = 0usize;
    let mut total_processed = 0usize;
    for (session_index, session) in state.grouped_nights.iter().enumerate() {
        let mut rejected_final = 0usize;
        for light in &session.lights {
            if light.state == FrameState::Rejected {
                rejected_final += 1;
            }
            total_processed += 1;
        }
        total_rejected_final += rejected_final;

        if let Some(step) = progress.steps.get_mut(session_index) {
            step.rejected_count = rejected_final;
            step.completed_count = session.lights.len();
            println!(
                "[FINAL_SESSION] Session {}: {} total, {} rejected",
                session_index,
                session.lights.len(),
                rejected_final
            );
        }
    }

    println!(
        "[FINAL_SUMMARY] Total: {} processed, {} rejected",
        total_processed, total_rejected_final
    );
    progress.finished_at = Some(now_millis());
    progress.status = CalibrationRunStatus::Completed;
    let _ = channel.send(progress.clone());

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_inlier_frames() {
        let stats = ImageStats {
            star_count: Some(10),
            fwhm: Some(2.0),
            hfd: None,
            eccentricity: None,
            background_contrast: None,
            quality_score: None,
        };

        assert_eq!(classify_frame(0.2, &stats, 3.0), FrameState::Accepted);
    }

    #[test]
    fn rejects_outliers_above_fwhm_threshold() {
        let stats = ImageStats {
            star_count: Some(10),
            fwhm: Some(4.0),
            hfd: None,
            eccentricity: None,
            background_contrast: None,
            quality_score: None,
        };

        assert_eq!(classify_frame(-0.5, &stats, 3.0), FrameState::Rejected);
    }

    #[test]
    fn keeps_outliers_below_fwhm_threshold_accepted() {
        let stats = ImageStats {
            star_count: Some(10),
            fwhm: Some(2.0),
            hfd: None,
            eccentricity: None,
            background_contrast: None,
            quality_score: None,
        };

        assert_eq!(classify_frame(-0.5, &stats, 3.0), FrameState::Accepted);
    }

    #[test]
    fn rejects_high_background_even_if_fwhm_low() {
        let stats = ImageStats {
            star_count: Some(10),
            fwhm: Some(2.0),
            hfd: None,
            eccentricity: None,
            background_contrast: Some(10.0), // normalized -> 10/20 = 0.5 > 0.25
            quality_score: None,
        };

        // With a negative score this should be rejected due to high background.
        assert_eq!(classify_frame(-0.2, &stats, 3.0), FrameState::Rejected);
    }
}
