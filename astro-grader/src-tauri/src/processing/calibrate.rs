use std::{
    collections::HashMap,
    hash::Hasher,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

use rayon::iter::{IntoParallelRefMutIterator, ParallelIterator};
use rayon::prelude::*;
use twox_hash::XxHash3_64;

use crate::{
    file_picker::File,
    fits::{FitsFile, ImageDataPixels, Tag},
    state::fe_state::{FeState, MasterOrFrames},
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
    session: &mut crate::state::fe_state::AstroSession,
    master_type: MasterType,
    path: Option<PathBuf>,
) {
    match master_type {
        MasterType::Dark => session.master_dark = path,
        MasterType::Flat => session.master_flat = path,
        MasterType::Bias => session.master_bias = path,
    }
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
) -> Result<PathBuf, String> {
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
            let mut fits = FitsFile::new(frame.path().clone())
                .map_err(|_| "Unable to open frame for master generation".to_string())?;
            let image = ImageDataPixels::from_fits(&mut fits)
                .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

            let offset = fi * pixel_count;
            samples[offset..offset + pixel_count].copy_from_slice(&image.pixels);


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
            let max_val = out_pixels
                .iter()
                .copied()
                .fold(f32::NEG_INFINITY, f32::max);
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
        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;
        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        let k = (count_idx + 1) as f64;
        for i in 0..pixel_count {
            let x = image.pixels[i] as f64;
            let delta = x - mean[i];
            mean[i] += delta / k;
            let delta2 = x - mean[i];
            m2[i] += delta * delta2;
        }
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

    for frame in frames {
        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;
        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        for i in 0..pixel_count {
            let x = image.pixels[i] as f64;
            if x >= lower[i] && x <= upper[i] {
                sum[i] += x;
                cnt[i] += 1;
            }
        }
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

    master_image
        .save_to_fits(target_path.to_path_buf())
        .map_err(|_| "Unable to write produced master frame to FITS".to_string())?;

    write_master_metadata(target_path, &frames[0], master_type)?;

    Ok(target_path.to_path_buf())
}

fn produce_master_dark(frames: &[File], target_path: &Path) -> Result<PathBuf, String> {
    produce_master(MasterType::Dark, frames, target_path)
}

fn produce_master_flat(frames: &[File], target_path: &Path) -> Result<PathBuf, String> {
    produce_master(MasterType::Flat, frames, target_path)
}

fn produce_master_bias(frames: &[File], target_path: &Path) -> Result<PathBuf, String> {
    produce_master(MasterType::Bias, frames, target_path)
}

fn resolve_master_for_slot(
    session: &mut crate::state::fe_state::AstroSession,
    master_type: MasterType,
    slot: &MasterOrFrames,
    temp_folder_path: &Path,
    cache: &Arc<Mutex<HashMap<(MasterType, u64), PathBuf>>>,
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
                    MasterType::Dark => produce_master_dark(frames, &output_path),
                    MasterType::Flat => produce_master_flat(frames, &output_path),
                    MasterType::Bias => produce_master_bias(frames, &output_path),
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

pub fn create_master_frames(state: &mut FeState, temp_folder_path: &Path) -> Result<(), String> {
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

    state
        .grouped_nights
        .par_iter_mut()
        .try_for_each(|session| -> Result<(), String> {
            let darks = session.darks.clone();
            let flats = session.flats.clone();
            let biases = session.biases.clone();

            resolve_master_for_slot(
                session,
                MasterType::Dark,
                &darks,
                temp_folder_path,
                &cached_master_frames,
            )?;

            resolve_master_for_slot(
                session,
                MasterType::Flat,
                &flats,
                temp_folder_path,
                &cached_master_frames,
            )?;

            resolve_master_for_slot(
                session,
                MasterType::Bias,
                &biases,
                temp_folder_path,
                &cached_master_frames,
            )?;

            Ok(())
        })
}
