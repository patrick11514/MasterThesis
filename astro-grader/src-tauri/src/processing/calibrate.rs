use std::{
    collections::HashMap,
    hash::Hasher,
    path::{Path, PathBuf},
    sync::atomic::Ordering,
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use rayon::prelude::*;
use twox_hash::XxHash3_64;

use crate::{
    file_picker::File,
    fits::{FitsFile, ImageDataLayout, ImageDataPixels, Tag},
    state::fe_state::{AstroSession, FeState, MasterOrFrames},
    state::{
        CalibrationCancellation, CalibrationProgressMessage, CalibrationProgressStep,
        CalibrationRunStatus, CalibrationStepKind, CalibrationStepStatus,
    },
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum MasterType {
    Dark,
    Flat,
    Bias,
}

impl MasterType {
    fn as_file_name_part(self) -> &'static str {
        match self {
            MasterType::Dark => "dark",
            MasterType::Flat => "flat",
            MasterType::Bias => "bias",
        }
    }

    fn as_image_type_value(self) -> &'static str {
        match self {
            MasterType::Dark => "master dark",
            MasterType::Flat => "master flat",
            MasterType::Bias => "master bias",
        }
    }
}

fn frames_signature(frames: &[File]) -> u64 {
    let mut ids = frames.iter().map(|f| f.uuid()).collect::<Vec<_>>();
    ids.sort_unstable();

    let mut hasher = XxHash3_64::new();
    for id in ids {
        hasher.write(id.as_bytes());
    }

    hasher.finish()
}

fn set_session_master_path(
    session: &mut AstroSession,
    master_type: MasterType,
    path: Option<PathBuf>,
) {
    match master_type {
        MasterType::Dark => session.master_dark = path,
        MasterType::Flat => session.master_flat = path,
        MasterType::Bias => session.master_bias = path,
    }
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}

fn kind_label(kind: &CalibrationStepKind) -> &'static str {
    match kind {
        CalibrationStepKind::Dark => "Stacking dark frames",
        CalibrationStepKind::Flat => "Stacking flat frames",
        CalibrationStepKind::Bias => "Stacking bias frames",
        CalibrationStepKind::Light => "Calibrating light frames",
    }
}

fn master_type_to_step_kind(master_type: MasterType) -> CalibrationStepKind {
    match master_type {
        MasterType::Dark => CalibrationStepKind::Dark,
        MasterType::Flat => CalibrationStepKind::Flat,
        MasterType::Bias => CalibrationStepKind::Bias,
    }
}

fn session_label(session: &AstroSession) -> String {
    let fingerprint = &session.fingerprint;

    if fingerprint.name.is_empty() {
        return "Unnamed session".to_string();
    }

    format!(
        "{} - {} - {:.2}s - gain {:.2} - {:.1}C",
        fingerprint.name,
        fingerprint.filter,
        fingerprint.exposure,
        fingerprint.gain,
        fingerprint.temperature,
    )
}

fn check_cancelled(calibration_cancellation: &CalibrationCancellation) -> Result<(), String> {
    if calibration_cancellation.requested.load(Ordering::Relaxed) {
        return Err("Calibration canceled".to_string());
    }

    Ok(())
}

fn normalize_pixels_if_needed(pixels: &mut [f32]) {
    let max_value = pixels
        .iter()
        .copied()
        .filter(|value| value.is_finite())
        .fold(0.0f32, f32::max);

    if max_value > 1.5 {
        for value in pixels.iter_mut() {
            *value /= max_value;
        }
    }
}

const HOT_PIXEL_SIGMA_FACTOR: f32 = 6.0;
const HOT_PIXEL_ABS_FLOOR: f32 = 0.0005;

fn neighborhood_hot_pixel_threshold(neighbors: &[f32]) -> f32 {
    if neighbors.is_empty() {
        return f32::INFINITY;
    }

    let mut sorted = neighbors.to_vec();
    sorted.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = sorted[sorted.len() / 2];

    let mad = neighbors
        .iter()
        .map(|value| (*value - median).abs())
        .sum::<f32>()
        / neighbors.len() as f32;

    median + HOT_PIXEL_SIGMA_FACTOR * mad.max(1e-12) + HOT_PIXEL_ABS_FLOOR
}

fn replace_hot_pixels_in_plane(
    source_plane: &[f32],
    target_plane: &mut [f32],
    width: usize,
    height: usize,
) -> usize {
    if width < 3 || height < 3 {
        return 0;
    }

    let original = source_plane.to_vec();

    target_plane
        .par_chunks_mut(width)
        .enumerate()
        .map(|(y, row)| {
            if y == 0 || y + 1 == height {
                return 0usize;
            }

            let mut replaced = 0usize;
            for x in 1..(width - 1) {
                let idx = y * width + x;
                let center = original[idx];

                let mut neighbors = [0.0f32; 8];
                let mut k = 0usize;
                for yy in (y - 1)..=(y + 1) {
                    for xx in (x - 1)..=(x + 1) {
                        if yy == y && xx == x {
                            continue;
                        }
                        neighbors[k] = original[yy * width + xx];
                        k += 1;
                    }
                }

                let threshold = neighborhood_hot_pixel_threshold(&neighbors);
                if center > threshold {
                    let mut sorted = neighbors;
                    sorted.sort_unstable_by(|a, b| {
                        a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal)
                    });
                    row[x] = sorted[sorted.len() / 2];
                    replaced += 1;
                }
            }

            replaced
        })
        .sum()
}

fn remove_hot_pixels(img: &mut ImageDataPixels) -> usize {
    let width = img.data.width;
    let height = img.data.height;
    let source = img.pixels.clone();

    match img.data.layout {
        ImageDataLayout::Grayscale => {
            replace_hot_pixels_in_plane(&source, &mut img.pixels, width, height)
        }
        ImageDataLayout::RGBPlanar => {
            let plane_size = width * height;
            let mut replaced = 0usize;

            for channel in 0..img.data.depth {
                let start = channel * plane_size;
                let end = start + plane_size;
                replaced += replace_hot_pixels_in_plane(
                    &source[start..end],
                    &mut img.pixels[start..end],
                    width,
                    height,
                );
            }

            replaced
        }
        ImageDataLayout::RGB => 0,
    }
}

#[derive(Debug, Clone)]
enum CalibrationWorkItemTask {
    Master(MasterType),
    CalibrateLights,
}

#[derive(Debug, Clone)]
struct CalibrationWorkItem {
    session_index: usize,
    task: CalibrationWorkItemTask,
}

fn build_calibration_pipeline(
    state: &FeState,
) -> (Vec<CalibrationWorkItem>, CalibrationProgressMessage) {
    let mut work_items = Vec::new();
    let mut steps = Vec::new();
    let mut master_signatures = std::collections::HashSet::new();

    for (session_index, session) in state.grouped_nights.iter().enumerate() {
        let label = session_label(session);

        for master_type in [MasterType::Dark, MasterType::Flat, MasterType::Bias] {
            let slot = match master_type {
                MasterType::Dark => &session.darks,
                MasterType::Flat => &session.flats,
                MasterType::Bias => &session.biases,
            };

            let MasterOrFrames::Frames(frames) = slot else {
                continue;
            };

            if frames.is_empty() {
                continue;
            }

            let signature = frames_signature(frames);
            let key = (master_type, signature);

            if !master_signatures.insert(key) {
                continue;
            }

            let kind = master_type_to_step_kind(master_type);

            work_items.push(CalibrationWorkItem {
                session_index,
                task: CalibrationWorkItemTask::Master(master_type),
            });

            steps.push(CalibrationProgressStep {
                id: format!("{}:{kind:?}", session.uuid),
                kind,
                label: kind_label(&kind).to_string(),
                session_uuid: session.uuid.clone(),
                session_label: label.clone(),
                count: frames.len(),
                completed_count: 0,
                status: CalibrationStepStatus::Pending,
                started_at: None,
                ended_at: None,
                error: None,
            });
        }
    }

    for (session_index, session) in state.grouped_nights.iter().enumerate() {
        let label = session_label(session);

        if !session.lights.is_empty() {
            let kind = CalibrationStepKind::Light;
            work_items.push(CalibrationWorkItem {
                session_index,
                task: CalibrationWorkItemTask::CalibrateLights,
            });

            steps.push(CalibrationProgressStep {
                id: format!("{}:{kind:?}", session.uuid),
                kind,
                label: kind_label(&kind).to_string(),
                session_uuid: session.uuid.clone(),
                session_label: label.clone(),
                count: session.lights.len(),
                completed_count: 0,
                status: CalibrationStepStatus::Pending,
                started_at: None,
                ended_at: None,
                error: None,
            });
        }
    }

    let started_at = now_millis();
    let status = if steps.is_empty() {
        CalibrationRunStatus::Completed
    } else {
        CalibrationRunStatus::Running
    };

    let progress = CalibrationProgressMessage {
        started_at,
        finished_at: if steps.is_empty() {
            Some(started_at)
        } else {
            None
        },
        status,
        current_step_id: None,
        steps,
    };

    (work_items, progress)
}

fn send_progress(
    channel: &tauri::ipc::Channel<CalibrationProgressMessage>,
    progress: &CalibrationProgressMessage,
) {
    let _ = channel.send(progress.clone());
}

fn write_master_metadata(
    target_path: &Path,
    first_source_frame: &File,
    master_type: MasterType,
) -> Result<(), String> {
    let mut src = FitsFile::new(first_source_frame.path().clone())
        .map_err(|_| "Unable to open source frame for metadata copy".to_string())?;

    let camera = src.get_tag_value(Tag::Camera);
    let telescope = src.get_tag_value(Tag::Telescope);
    let filter = src.get_tag_value(Tag::Filter);
    let exposure = src.get_tag_custom::<f32>(Tag::ExposureTime);
    let gain = src.get_tag_custom::<f32>(Tag::Gain);

    let mut dst = FitsFile::edit(target_path.to_path_buf())
        .map_err(|_| "Unable to open output master frame for metadata write".to_string())?;

    dst.write_key_string("IMAGETYP", master_type.as_image_type_value())
        .map_err(|_| "Unable to write IMAGETYP into master frame".to_string())?;

    if let Some(value) = camera {
        dst.write_key_string("INSTRUME", value.trim())
            .map_err(|_| "Unable to write INSTRUME into master frame".to_string())?;
    }
    if let Some(value) = telescope {
        dst.write_key_string("TELESCOP", value.trim())
            .map_err(|_| "Unable to write TELESCOP into master frame".to_string())?;
    }
    if let Some(value) = filter {
        dst.write_key_string("FILTER", value.trim())
            .map_err(|_| "Unable to write FILTER into master frame".to_string())?;
    }
    if let Some(value) = exposure {
        dst.write_key_f32("EXPTIME", value)
            .map_err(|_| "Unable to write EXPTIME into master frame".to_string())?;
    }
    if let Some(value) = gain {
        dst.write_key_f32("GAIN", value)
            .map_err(|_| "Unable to write GAIN into master frame".to_string())?;
    }

    // Copy Bayer metadata if present so masters can be properly debayered on load
    if let Some(value) = src.get_tag_value(Tag::BayerPattern) {
        dst.write_key_string("BAYERPAT", value.trim())
            .map_err(|_| "Unable to write BAYERPAT into master frame".to_string())?
    }
    if let Some(value) = src.get_tag_custom::<i32>(Tag::XBayerOffset) {
        dst.write_key_i32("XBAYROFF", value)
            .map_err(|_| "Unable to write XBAYROFF into master frame".to_string())?
    }
    if let Some(value) = src.get_tag_custom::<i32>(Tag::YBayerOffset) {
        dst.write_key_i32("YBAYROFF", value)
            .map_err(|_| "Unable to write YBAYROFF into master frame".to_string())?
    }

    Ok(())
}

fn produce_master(
    master_type: MasterType,
    frames: &[File],
    target_path: &Path,
    calibration_cancellation: &CalibrationCancellation,
    on_progress: &dyn Fn(usize),
) -> Result<PathBuf, String> {
    check_cancelled(calibration_cancellation)?;

    if frames.is_empty() {
        return Err(format!(
            "Cannot produce master {} from empty frame list",
            master_type.as_file_name_part()
        ));
    }

    // Streaming approach to avoid loading all frames simultaneously
    // Read first frame to get dimensions
    let mut first_fits = FitsFile::new(frames[0].path().clone())
        .map_err(|_| "Unable to open first frame for master generation".to_string())?;
    let first_image = ImageDataPixels::from_fits(&mut first_fits)
        .map_err(|_| "Unable to read first frame pixels for master generation".to_string())?;

    let expected_width = first_image.data.width;
    let expected_height = first_image.data.height;
    let expected_depth = first_image.data.depth;
    let expected_layout = first_image.data.layout.clone();

    let pixel_count = first_image.pixels.len();
    let nframes = frames.len();

    for frame in frames.iter().skip(1) {
        check_cancelled(calibration_cancellation)?;

        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;
        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        if image.data.width != expected_width
            || image.data.height != expected_height
            || image.data.depth != expected_depth
            || image.data.layout != expected_layout
            || image.pixels.len() != pixel_count
        {
            return Err(format!(
                "Incompatible frame dimensions/layout while building master {}",
                master_type.as_file_name_part()
            ));
        }
    }

    // Use median for Flats and Bias (naturally uniform, dust/defects are sparse)
    // Use sigma-clipped mean for Darks (to reject cosmic rays)
    let use_median = matches!(master_type, MasterType::Flat | MasterType::Bias);

    // Median or unclipped mean path: buffer all samples
    if use_median || nframes < 6 {
        // allocate samples as contiguous [frame0_pixels..., frame1_pixels..., ...]
        let mut samples: Vec<f32> = vec![0.0; pixel_count * nframes];

        for (fi, frame) in frames.iter().enumerate() {
            check_cancelled(calibration_cancellation)?;

            let mut fits = FitsFile::new(frame.path().clone())
                .map_err(|_| "Unable to open frame for master generation".to_string())?;
            let image = ImageDataPixels::from_fits(&mut fits)
                .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

            let offset = fi * pixel_count;
            samples[offset..offset + pixel_count].copy_from_slice(&image.pixels);

            on_progress(fi + 1);
        }

        // compute median per pixel
        let out_pixels: Vec<f32> = (0..pixel_count)
            .into_par_iter()
            .map(|i| {
                let mut vals: Vec<f32> = (0..nframes)
                    .map(|fi| samples[fi * pixel_count + i])
                    .collect();
                let mid = vals.len() / 2;
                vals.select_nth_unstable_by(mid, |a, b| a.partial_cmp(b).unwrap());
                vals[mid]
            })
            .collect();

        let mut out_pixels = out_pixels;
        if matches!(master_type, MasterType::Flat) {
            // Normalize flat master by its maximum value to achieve unity gain
            let max_val = out_pixels.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            if max_val.is_normal() && max_val > 0.0 {
                for value in &mut out_pixels {
                    *value /= max_val;
                }
            }
        }

        let master_image = ImageDataPixels {
            data: first_image.data.clone(),
            pixels: out_pixels,
        };

        // Debug: print master pixel stats before saving
        let (mut min_v, mut max_v, mut sum) = (
            std::f32::INFINITY,
            std::f32::NEG_INFINITY,
            0f64,
        );
        let mut count = 0usize;
        for &p in &master_image.pixels {
            if p.is_finite() {
                if p < min_v {
                    min_v = p;
                }
                if p > max_v {
                    max_v = p;
                }
                sum += p as f64;
                count += 1;
            }
        }
        let mean = if count == 0 { 0.0 } else { sum / count as f64 };
        println!(
            "Produced master ({}) -> min {:.6}, max {:.6}, mean {:.6}",
            target_path.display(),
            min_v,
            max_v,
            mean
        );

        master_image
            .save_to_fits(target_path.to_path_buf())
            .map_err(|_| "Unable to write produced master frame to FITS".to_string())?;

        write_master_metadata(target_path, &frames[0], master_type)?;

        return Ok(target_path.to_path_buf());
    }

    // Sigma-clipped mean path (two-pass Welford + clipping) to avoid holding all frames
    // First pass: compute mean and M2 per pixel (Welford)
    let mut mean: Vec<f64> = vec![0.0; pixel_count];
    let mut m2: Vec<f64> = vec![0.0; pixel_count];

    for (count_idx, frame) in frames.iter().enumerate() {
        check_cancelled(calibration_cancellation)?;

        if count_idx % 10 == 0 || count_idx == nframes - 1 {
            println!(
                "Stacking (Pass 1 - Mean/Variance): Reading frame {}/{}",
                count_idx + 1,
                nframes
            );
        }

        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;
        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        let k = (count_idx + 1) as f64;

        mean.par_iter_mut()
            .zip(m2.par_iter_mut())
            .zip(&image.pixels)
            .for_each(|((m, m2_val), &x_f32)| {
                let x = x_f32 as f64;
                let delta = x - *m;
                *m += delta / k;
                let delta2 = x - *m;
                *m2_val += delta * delta2;
            });
    }

    let mut std: Vec<f64> = vec![0.0; pixel_count];
    for i in 0..pixel_count {
        let var = if nframes > 0 {
            m2[i] / (nframes as f64)
        } else {
            0.0
        };
        std[i] = var.sqrt();
    }

    // Compute clipping bounds
    let k_sigma = 3.0f64;
    let mut lower: Vec<f64> = vec![0.0; pixel_count];
    let mut upper: Vec<f64> = vec![0.0; pixel_count];
    for i in 0..pixel_count {
        lower[i] = mean[i] - k_sigma * std[i];
        upper[i] = mean[i] + k_sigma * std[i];
    }

    // Second pass: accumulate sum and count of non-clipped samples
    let mut sum: Vec<f64> = vec![0.0; pixel_count];
    let mut cnt: Vec<u32> = vec![0; pixel_count];

    for (count_idx, frame) in frames.iter().enumerate() {
        check_cancelled(calibration_cancellation)?;

        if count_idx % 10 == 0 || count_idx == nframes - 1 {
            println!(
                "Stacking (Pass 2 - Sigma Clipping): Reading frame {}/{}",
                count_idx + 1,
                nframes
            );
        }

        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;
        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        sum.par_iter_mut()
            .zip(cnt.par_iter_mut())
            .zip(&image.pixels)
            .enumerate()
            .for_each(|(i, ((s, c), &x_f32))| {
                let x = x_f32 as f64;
                if x >= lower[i] && x <= upper[i] {
                    *s += x;
                    *c += 1;
                }
            });

        on_progress(count_idx + 1);
    }

    let out_pixels: Vec<f32> = (0..pixel_count)
        .into_par_iter()
        .map(|i| {
            if cnt[i] > 0 {
                (sum[i] / (cnt[i] as f64)) as f32
            } else {
                mean[i] as f32
            }
        })
        .collect();

    let master_image = ImageDataPixels {
        data: first_image.data.clone(),
        pixels: out_pixels,
    };

    // Debug: print master pixel stats before saving (sigma-clipped path)
    let (mut min_v, mut max_v, mut sum) = (
        std::f32::INFINITY,
        std::f32::NEG_INFINITY,
        0f64,
    );
    let mut count = 0usize;
    for &p in &master_image.pixels {
        if p.is_finite() {
            if p < min_v {
                min_v = p;
            }
            if p > max_v {
                max_v = p;
            }
            sum += p as f64;
            count += 1;
        }
    }
    let mean = if count == 0 { 0.0 } else { sum / count as f64 };
    println!(
        "Produced master ({}) -> min {:.6}, max {:.6}, mean {:.6}",
        target_path.display(),
        min_v,
        max_v,
        mean
    );

    master_image
        .save_to_fits(target_path.to_path_buf())
        .map_err(|_| "Unable to write produced master frame to FITS".to_string())?;

    write_master_metadata(target_path, &frames[0], master_type)?;

    Ok(target_path.to_path_buf())
}

fn produce_master_dark(
    frames: &[File],
    target_path: &Path,
    calibration_cancellation: &CalibrationCancellation,
    on_progress: &dyn Fn(usize),
) -> Result<PathBuf, String> {
    produce_master(
        MasterType::Dark,
        frames,
        target_path,
        calibration_cancellation,
        on_progress,
    )
}

fn produce_master_flat(
    frames: &[File],
    target_path: &Path,
    calibration_cancellation: &CalibrationCancellation,
    on_progress: &dyn Fn(usize),
) -> Result<PathBuf, String> {
    produce_master(
        MasterType::Flat,
        frames,
        target_path,
        calibration_cancellation,
        on_progress,
    )
}

fn produce_master_bias(
    frames: &[File],
    target_path: &Path,
    calibration_cancellation: &CalibrationCancellation,
    on_progress: &dyn Fn(usize),
) -> Result<PathBuf, String> {
    produce_master(
        MasterType::Bias,
        frames,
        target_path,
        calibration_cancellation,
        on_progress,
    )
}

fn resolve_master_for_slot(
    session: &mut AstroSession,
    master_type: MasterType,
    slot: &MasterOrFrames,
    temp_folder_path: &Path,
    cache: &Arc<Mutex<HashMap<(MasterType, u64), PathBuf>>>,
    calibration_cancellation: &CalibrationCancellation,
    on_progress: &dyn Fn(usize),
) -> Result<(), String> {
    match slot {
        MasterOrFrames::Master(file) => {
            set_session_master_path(session, master_type, Some(file.path().clone()));
            Ok(())
        }
        MasterOrFrames::Frames(frames) => {
            if frames.is_empty() {
                set_session_master_path(session, master_type, None);
                return Ok(());
            }

            let signature = frames_signature(frames);
            let key = (master_type, signature);

            if let Some(path) = cache
                .lock()
                .map_err(|_| "Master cache lock poisoned".to_string())?
                .get(&key)
                .cloned()
            {
                set_session_master_path(session, master_type, Some(path));
                return Ok(());
            }

            let output_path = temp_folder_path.join(format!(
                "master_{}_{}.fits",
                master_type.as_file_name_part(),
                format!("{signature:016x}")
            ));

            let produced_path = if output_path.exists() {
                output_path.clone()
            } else {
                match master_type {
                    MasterType::Dark => produce_master_dark(
                        frames,
                        &output_path,
                        calibration_cancellation,
                        on_progress,
                    ),
                    MasterType::Flat => produce_master_flat(
                        frames,
                        &output_path,
                        calibration_cancellation,
                        on_progress,
                    ),
                    MasterType::Bias => produce_master_bias(
                        frames,
                        &output_path,
                        calibration_cancellation,
                        on_progress,
                    ),
                }?
            };

            {
                let mut guard = cache
                    .lock()
                    .map_err(|_| "Master cache lock poisoned".to_string())?;
                guard.entry(key).or_insert_with(|| produced_path.clone());
            }

            set_session_master_path(session, master_type, Some(produced_path));
            Ok(())
        }
    }
}

pub fn calibrate_light(
    light: &mut [f32],
    dark: Option<&[f32]>,
    flat: Option<&[f32]>,
    bias: Option<&[f32]>,
) {
    let pixel_count = light.len();

    // 1. Calculate the mean of the Bias-subtracted Flat
    let mut flat_mean = 1.0;
    if let Some(flat_data) = flat {
        let flat_sum: f32 = flat_data
            .par_iter()
            .enumerate()
            .map(|(i, &f_val)| {
                let bias_val = bias.map(|b| b[i]).unwrap_or(0.0);
                let mut flat_val = f_val - bias_val;
                if flat_val < 0.0 {
                    flat_val = 0.0;
                }
                flat_val
            })
            .sum();

        flat_mean = flat_sum / (pixel_count as f32);
        if flat_mean == 0.0 {
            flat_mean = 1.0; // avoid division by zero overall
        }
    }

    // 2. The Calibration Loop
    light.par_iter_mut().enumerate().for_each(|(i, pixel)| {
        let sub_val = if let Some(dark_data) = dark {
            dark_data[i]
        } else if let Some(bias_data) = bias {
            bias_data[i]
        } else {
            0.0
        };

        let mut calibrated = *pixel - sub_val;

        if calibrated < 0.0 {
            calibrated = 0.0;
        }

        if let Some(flat_data) = flat {
            let bias_val = bias.map(|b| b[i]).unwrap_or(0.0);
            let flat_norm = (flat_data[i] - bias_val) / flat_mean;

            if flat_norm > 0.0001 {
                calibrated /= flat_norm;
            } else {
                calibrated = 0.0;
            }
        }

        *pixel = calibrated;
    });
}

pub fn run_calibration(
    state: &mut FeState,
    temp_folder_path: &Path,
    targets: &[crate::state::CalibrateFrameTarget],
    channel: tauri::ipc::Channel<CalibrationProgressMessage>,
    calibration_cancellation: &CalibrationCancellation,
) -> Result<(), String> {
    if !temp_folder_path.exists() {
        return Err(format!(
            "Temp folder for master frames does not exist: {}",
            temp_folder_path.to_string_lossy()
        ));
    }
    if !temp_folder_path.is_dir() {
        return Err(format!(
            "Temp folder path is not a directory: {}",
            temp_folder_path.to_string_lossy()
        ));
    }

    let cached_master_frames: Arc<Mutex<HashMap<(MasterType, u64), PathBuf>>> =
        Arc::new(Mutex::new(HashMap::new()));

    let (work_items, mut progress) = build_calibration_pipeline(state);
    send_progress(&channel, &progress);

    if work_items.is_empty() {
        return Ok(());
    }

    for (step_index, work_item) in work_items.iter().enumerate() {
        check_cancelled(calibration_cancellation)?;

        println!(
            "Processing calibration step {}/{}: {:?}",
            step_index + 1,
            work_items.len(),
            work_item.task
        );

        let step = progress
            .steps
            .get_mut(step_index)
            .ok_or_else(|| "Calibration step index out of bounds".to_string())?;
        let started_at = now_millis();
        step.status = CalibrationStepStatus::Running;
        step.started_at = Some(started_at);
        step.ended_at = None;
        step.error = None;
        progress.current_step_id = Some(step.id.clone());
        progress.status = CalibrationRunStatus::Running;
        send_progress(&channel, &progress);

        let session = state
            .grouped_nights
            .get_mut(work_item.session_index)
            .ok_or_else(|| "Calibration session index out of bounds".to_string())?;

        let result = match &work_item.task {
            CalibrationWorkItemTask::Master(master_type) => {
                let slot = match master_type {
                    MasterType::Dark => session.darks.clone(),
                    MasterType::Flat => session.flats.clone(),
                    MasterType::Bias => session.biases.clone(),
                };

                // Use a shared counter so the stacking callback can update progress
                let completed = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
                let completed_clone = completed.clone();

                let on_progress = move |n: usize| {
                    completed_clone.store(n, std::sync::atomic::Ordering::Relaxed);
                };

                let slot_clone = slot.clone();
                let result = resolve_master_for_slot(
                    session,
                    *master_type,
                    &slot_clone,
                    temp_folder_path,
                    &cached_master_frames,
                    calibration_cancellation,
                    &on_progress,
                );

                // Update completed_count one final time after stacking finishes
                let final_count = completed.load(std::sync::atomic::Ordering::Relaxed);
                if let Some(step) = progress.steps.get_mut(step_index) {
                    step.completed_count = final_count;
                }

                result
            }
            CalibrationWorkItemTask::CalibrateLights => {
                for master_type in [MasterType::Dark, MasterType::Flat, MasterType::Bias] {
                    let slot = match master_type {
                        MasterType::Dark => session.darks.clone(),
                        MasterType::Flat => session.flats.clone(),
                        MasterType::Bias => session.biases.clone(),
                    };

                    // Masters should already be in cache; no-op progress callback
                    resolve_master_for_slot(
                        session,
                        master_type,
                        &slot,
                        temp_folder_path,
                        &cached_master_frames,
                        calibration_cancellation,
                        &|_| {},
                    )?;
                }

                let dark_path = session.master_dark.clone();
                let flat_path = session.master_flat.clone();
                let bias_path = session.master_bias.clone();

                let read_master = |path: Option<PathBuf>| -> Result<Option<Vec<f32>>, String> {
                    if let Some(p) = path {
                        let mut fits = FitsFile::new(p.clone())
                            .map_err(|_| "Unable to open master FITS file".to_string())?;
                        let img = ImageDataPixels::from_fits(&mut fits)
                            .map_err(|_| "Unable to read master pixels".to_string())?;
                        let mut pixels = img.pixels;
                        normalize_pixels_if_needed(&mut pixels);
                        Ok(Some(pixels))
                    } else {
                        Ok(None)
                    }
                };

                let dark_pixels = read_master(dark_path)?;
                let flat_pixels = read_master(flat_path)?;
                let bias_pixels = read_master(bias_path)?;

                // Clear stale calibrated_frame references (file was deleted externally)
                // so the frontend state doesn't show a ghost path.
                for f in session.lights.iter_mut() {
                    if let Some(cal_path) = &f.calibrated_frame {
                        if !cal_path.exists() {
                            println!(
                                "  Stale calibrated_frame cleared for: {}",
                                f.path().display()
                            );
                            // Also clear in raw_nights
                            let src = f.path().clone();
                            f.calibrated_frame = None;
                            for night_files in state.raw_nights.values_mut() {
                                if let Some(rf) = night_files.iter_mut().find(|rf| rf.path() == &src) {
                                    rf.calibrated_frame = None;
                                    break;
                                }
                            }
                        }
                    }
                }

                // Skip files that were already successfully calibrated in a previous run,
                // but only if the calibrated file actually still exists on disk.
                let light_files: Vec<_> = session
                    .lights
                    .iter()
                    .filter(|f| f.calibrated_frame.is_none())
                    .cloned()
                    .collect();

                if light_files.is_empty() {
                    println!("  All light frames already calibrated, skipping session.");
                }

                let mut chunk_err = None;

                let num_threads = rayon::current_num_threads();
                let total_chunks = (light_files.len() + num_threads - 1) / num_threads;

                for (chunk_idx, chunk) in light_files.chunks(num_threads).enumerate() {
                    check_cancelled(calibration_cancellation)?;

                    println!(
                        "Calibrating lights (Chunk {}/{}): Processing {} frames...",
                        chunk_idx + 1,
                        total_chunks,
                        chunk.len()
                    );

                    let chunk_result: Result<Vec<(PathBuf, PathBuf)>, String> =
                        chunk.par_iter().map(|light_file| {
                            check_cancelled(calibration_cancellation)?;

                            let target = targets
                                .iter()
                                .find(|t| {
                                    t.source_path == light_file.path().to_string_lossy().to_string()
                                })
                                .ok_or_else(|| {
                                    format!(
                                        "Target path not found for {}",
                                        light_file.path().display()
                                    )
                                })?;

                            let target_path = PathBuf::from(&target.calibrated_path);

                            let mut fits =
                                FitsFile::new(light_file.path().clone()).map_err(|_| {
                                    format!(
                                        "Unable to open light frame: {}",
                                        light_file.path().display()
                                    )
                                })?;
                            let mut img = ImageDataPixels::from_fits(&mut fits).map_err(|_| {
                                format!(
                                    "Unable to read light frame: {}",
                                    light_file.path().display()
                                )
                            })?;

                            normalize_pixels_if_needed(&mut img.pixels);

                            calibrate_light(
                                &mut img.pixels,
                                dark_pixels.as_deref(),
                                flat_pixels.as_deref(),
                                bias_pixels.as_deref(),
                            );

                            let hot_pixels_replaced = remove_hot_pixels(&mut img);

                            // Debug: print basic pixel statistics after calibration
                            let (mut min_v, mut max_v, mut sum) = (
                                std::f32::INFINITY,
                                std::f32::NEG_INFINITY,
                                0f64,
                            );
                            let mut count = 0usize;
                            for &p in &img.pixels {
                                if p.is_finite() {
                                    if p < min_v {
                                        min_v = p;
                                    }
                                    if p > max_v {
                                        max_v = p;
                                    }
                                    sum += p as f64;
                                    count += 1;
                                }
                            }
                            let mean = if count == 0 { 0.0 } else { sum / count as f64 };

                            println!(
                                "Calibrated pixels for {} -> min {:.6}, max {:.6}, mean {:.6}, hotfix:{}",
                                light_file.path().display(),
                                min_v,
                                max_v,
                                mean,
                                hot_pixels_replaced
                            );

                            println!(
                                "  -> Calibrating: {} => {}",
                                light_file.path().display(),
                                target_path.display()
                            );

                            // Save image to target path
                            img.save_to_fits(target_path.clone()).map_err(|_| {
                                format!(
                                    "Unable to write calibrated frame: {}",
                                    target_path.display()
                                )
                            })?;

                            // Copy all FITS headers from original file to calibrated file
                            let mut dst = FitsFile::edit(target_path.clone()).map_err(|_| {
                                "Unable to open output light frame for metadata write".to_string()
                            })?;

                            dst.write_key_string("IMAGETYP", "Light Frame")
                                .map_err(|_| {
                                    "Unable to write IMAGETYP into light frame".to_string()
                                })?;

                            // Also carry over camera, filter, etc.
                            if let Some(value) = fits.get_tag_value(crate::fits::Tag::Camera) {
                                let _ = dst.write_key_string("INSTRUME", value.trim());
                            }
                            if let Some(value) = fits.get_tag_value(crate::fits::Tag::Telescope) {
                                let _ = dst.write_key_string("TELESCOP", value.trim());
                            }
                            if let Some(value) = fits.get_tag_value(crate::fits::Tag::Filter) {
                                let _ = dst.write_key_string("FILTER", value.trim());
                            }
                            if let Some(value) =
                                fits.get_tag_custom::<f32>(crate::fits::Tag::ExposureTime)
                            {
                                let _ = dst.write_key_f32("EXPTIME", value);
                            }
                            if let Some(value) = fits.get_tag_custom::<f32>(crate::fits::Tag::Gain)
                            {
                                let _ = dst.write_key_f32("GAIN", value);
                            }
                            if let Some(value) = fits.get_tag_value(crate::fits::Tag::BayerPattern)
                            {
                                let _ = dst.write_key_string("BAYERPAT", value.trim());
                            }
                            if let Some(value) =
                                fits.get_tag_custom::<i32>(crate::fits::Tag::XBayerOffset)
                            {
                                let _ = dst.write_key_i32("XBAYROFF", value);
                            }
                            if let Some(value) =
                                fits.get_tag_custom::<i32>(crate::fits::Tag::YBayerOffset)
                            {
                                let _ = dst.write_key_i32("YBAYROFF", value);
                            }

                            Ok((light_file.path().clone(), target_path))
                        }).collect();

                    match chunk_result {
                        Err(e) => {
                            chunk_err = Some(e);
                            break;
                        }
                        Ok(completed_pairs) => {
                            // Mutate calibrated_frame on the originals — must be done
                            // single-threaded since session.lights is not Arc/Mutex.
                            for (source_path, cal_path) in &completed_pairs {
                                // Update in session.lights (grouped view)
                                if let Some(f) = session
                                    .lights
                                    .iter_mut()
                                    .find(|f| f.path() == source_path)
                                {
                                    f.calibrated_frame = Some(cal_path.clone());
                                }

                                // Also update in state.raw_nights (flat file list)
                                for night_files in state.raw_nights.values_mut() {
                                    if let Some(f) = night_files
                                        .iter_mut()
                                        .find(|f| f.path() == source_path)
                                    {
                                        f.calibrated_frame = Some(cal_path.clone());
                                        break;
                                    }
                                }
                            }
                        }
                    }

                    // Update completed_count and send progress after each chunk
                    let frames_done = (chunk_idx + 1) * num_threads;
                    let clamped = frames_done.min(light_files.len());
                    if let Some(step) = progress.steps.get_mut(step_index) {
                        step.completed_count = clamped;
                    }
                    send_progress(&channel, &progress);
                }

                if let Some(e) = chunk_err {
                    Err(e)
                } else {
                    Ok(())
                }
            }
        };

        match result {
            Ok(()) => {
                let ended_at = now_millis();
                let step = progress
                    .steps
                    .get_mut(step_index)
                    .ok_or_else(|| "Calibration step index out of bounds".to_string())?;
                step.status = CalibrationStepStatus::Completed;
                step.ended_at = Some(ended_at);
                progress.current_step_id = None;
                send_progress(&channel, &progress);
            }
            Err(error) if error == "Calibration canceled" => {
                let ended_at = now_millis();
                let step = progress
                    .steps
                    .get_mut(step_index)
                    .ok_or_else(|| "Calibration step index out of bounds".to_string())?;
                step.status = CalibrationStepStatus::Cancelled;
                step.ended_at = Some(ended_at);
                progress.current_step_id = None;
                progress.finished_at = Some(ended_at);
                progress.status = CalibrationRunStatus::Cancelled;
                send_progress(&channel, &progress);
                return Err(error);
            }
            Err(error) => {
                let ended_at = now_millis();
                let step = progress
                    .steps
                    .get_mut(step_index)
                    .ok_or_else(|| "Calibration step index out of bounds".to_string())?;
                step.status = CalibrationStepStatus::Failed;
                step.ended_at = Some(ended_at);
                step.error = Some(error.clone());
                progress.current_step_id = None;
                progress.finished_at = Some(ended_at);
                progress.status = CalibrationRunStatus::Failed;
                send_progress(&channel, &progress);
                return Err(error);
            }
        }
    }

    let finished_at = now_millis();
    progress.finished_at = Some(finished_at);
    progress.status = CalibrationRunStatus::Completed;
    send_progress(&channel, &progress);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::normalize_pixels_if_needed;

    #[test]
    fn normalize_pixels_scales_raw_sensor_counts() {
        let mut pixels = vec![0.0, 32767.5, 65535.0];

        normalize_pixels_if_needed(&mut pixels);

        assert!(pixels[0] <= 0.000_001);
        assert!((pixels[1] - 0.5).abs() < 0.000_01);
        assert!((pixels[2] - 1.0).abs() < 0.000_01);
    }

    #[test]
    fn normalize_pixels_leaves_unit_range_untouched() {
        let mut pixels = vec![0.0, 0.25, 0.8, 1.0];

        normalize_pixels_if_needed(&mut pixels);

        assert_eq!(pixels, vec![0.0, 0.25, 0.8, 1.0]);
    }
}
