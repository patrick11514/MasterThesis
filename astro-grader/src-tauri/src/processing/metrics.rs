use std::{
    collections::HashMap,
    ffi::{CStr, c_char, c_void},
    path::PathBuf,
    ptr,
};

use sep_sys::*;

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

fn classify_frame(score: f32, stats: &ImageStats, max_fwhm: f32) -> FrameState {
    let fwhm = stats.fwhm.unwrap_or(f32::INFINITY);

    if score < 0.0 && fwhm > max_fwhm {
        FrameState::Rejected
    } else {
        FrameState::Accepted
    }
}

fn extract_metrics_from_pixels(
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
            32,
            0.005,
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

    values
        .iter()
        .map(|value| {
            let z_score = (*value - mean) / sigma;

            if z_score.abs() >= 3.0 {
                -z_score.abs()
            } else {
                1.0 - (z_score.abs() / 3.0)
            }
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
            let path = path_buf.to_string_lossy().to_string();

            if let Some((stats, state_value)) = metrics_by_path.get(&path) {
                raw_file.stats = Some(stats.clone());
                raw_file.state = *state_value;
            }
        }
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
    let mut score_sources_by_session = Vec::with_capacity(state.grouped_nights.len());

    for (session_index, session) in state.grouped_nights.iter_mut().enumerate() {
        progress.steps[session_index].status = CalibrationStepStatus::Running;
        progress.steps[session_index].started_at = Some(now_millis());
        progress.current_step_id = Some(progress.steps[session_index].id.clone());
        let _ = channel.send(progress.clone());

        let mut score_source = Vec::with_capacity(session.lights.len());

        for light in &mut session.lights {
            let image_path = image_path_for_metrics(light);
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

            let stats =
                extract_metrics_from_pixels(&image.pixels, image.data.width, image.data.height)?;
            score_source.push(stats.star_count.unwrap_or(0) as f32);

            let star_count_str = stats
                .star_count
                .map(|count| count.to_string())
                .unwrap_or_else(|| "0".to_string());
            let fwhm_str = stats
                .fwhm
                .map(|value| format!("{:.2}", value))
                .unwrap_or_else(|| "N/A".to_string());
            let hfd_str = stats
                .hfd
                .map(|value| format!("{:.2}", value))
                .unwrap_or_else(|| "N/A".to_string());
            let ecc_str = stats
                .eccentricity
                .map(|value| format!("{:.2}", value))
                .unwrap_or_else(|| "N/A".to_string());
            let bg_str = stats
                .background_contrast
                .map(|value| format!("{:.2}", value))
                .unwrap_or_else(|| "N/A".to_string());

            println!(
                "{} - {} stars, FWHM: {}, HFD: {}, ecc: {}, bg_contrast: {}",
                image_path.display(),
                star_count_str,
                fwhm_str,
                hfd_str,
                ecc_str,
                bg_str
            );

            light.stats = Some(stats);

            progress.steps[session_index].completed_count += 1;
            let _ = channel.send(progress.clone());
        }

        score_sources_by_session.push(score_source);
        progress.steps[session_index].ended_at = Some(now_millis());
        progress.steps[session_index].status = CalibrationStepStatus::Completed;
        progress.current_step_id = None;
        let _ = channel.send(progress.clone());
    }

    if cross_night_reference {
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

                if let Some(stats) = &mut light.stats {
                    stats.quality_score = Some(score);
                    light.state = classify_frame(score, stats, max_fwhm);
                    metrics_by_path.insert(
                        image_path.to_string_lossy().to_string(),
                        (stats.clone(), light.state),
                    );
                }
            }
        }
    } else {
        for (session, score_source) in state
            .grouped_nights
            .iter_mut()
            .zip(score_sources_by_session.into_iter())
        {
            let scores = score_distribution(&score_source);

            for (light, score) in session.lights.iter_mut().zip(scores.into_iter()) {
                let image_path = image_path_for_metrics(light);

                if let Some(stats) = &mut light.stats {
                    stats.quality_score = Some(score);
                    light.state = classify_frame(score, stats, max_fwhm);
                    metrics_by_path.insert(
                        image_path.to_string_lossy().to_string(),
                        (stats.clone(), light.state),
                    );
                }
            }
        }
    }

    copy_metrics_back_to_raw_nights(state, &metrics_by_path);

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
}
