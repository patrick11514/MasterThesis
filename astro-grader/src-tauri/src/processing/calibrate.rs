use std::{
    collections::HashMap,
    hash::Hasher,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

use rayon::iter::{IntoParallelRefMutIterator, ParallelIterator};
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
    let bayer = src.get_tag_value(Tag::BayerPattern);
    let x_bayer_offset = src.get_tag_custom::<i32>(Tag::XBayerOffset);
    let y_bayer_offset = src.get_tag_custom::<i32>(Tag::YBayerOffset);

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
    if let Some(value) = bayer {
        dst.write_key_string("BAYERPAT", value.trim())
            .map_err(|_| "Unable to write BAYERPAT into master frame".to_string())?;
    }
    if let Some(value) = x_bayer_offset {
        dst.write_key_i32("XBAYROFF", value)
            .map_err(|_| "Unable to write XBAYROFF into master frame".to_string())?;
    }
    if let Some(value) = y_bayer_offset {
        dst.write_key_i32("YBAYROFF", value)
            .map_err(|_| "Unable to write YBAYROFF into master frame".to_string())?;
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

    let mut first_fits = FitsFile::new(frames[0].path().clone())
        .map_err(|_| "Unable to open first frame for master generation".to_string())?;
    let first_image = ImageDataPixels::from_fits(&mut first_fits)
        .map_err(|_| "Unable to read first frame pixels for master generation".to_string())?;

    let expected_width = first_image.data.width;
    let expected_height = first_image.data.height;
    let expected_depth = first_image.data.depth;
    let expected_layout = first_image.data.layout.clone();

    let mut accumulator = first_image.pixels.clone();

    for frame in frames.iter().skip(1) {
        let mut fits = FitsFile::new(frame.path().clone())
            .map_err(|_| "Unable to open frame for master generation".to_string())?;

        let image = ImageDataPixels::from_fits(&mut fits)
            .map_err(|_| "Unable to read frame pixels for master generation".to_string())?;

        if image.data.width != expected_width
            || image.data.height != expected_height
            || image.data.depth != expected_depth
            || image.data.layout != expected_layout
            || image.pixels.len() != accumulator.len()
        {
            return Err(format!(
                "Incompatible frame dimensions/layout while building master {}",
                master_type.as_file_name_part()
            ));
        }

        for (acc, px) in accumulator.iter_mut().zip(image.pixels.iter()) {
            *acc += *px;
        }
    }

    let count = frames.len() as f32;
    for px in &mut accumulator {
        *px /= count;
    }

    let master_image = ImageDataPixels {
        data: first_image.data,
        pixels: accumulator,
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
