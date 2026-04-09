use std::collections::HashMap;
use std::sync::Mutex;

use crate::{
    config,
    file_picker::File,
    fits::{FileType, FitsFile, Tag},
    state::{
        fe_state::{AstroSession, FeState, Nights, SessionFingerprint},
        rust_state::RustState,
    },
};

mod fe_state;
mod rust_state;

pub use rust_state::CurrentImage;

#[derive(Debug, Default)]
pub struct AppState {
    pub rust_state: RustState,
    pub fe_state: FeState,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct GroupFramesProgress {
    pub processed: usize,
    pub total: usize,
}

#[derive(Debug, Clone)]
struct FrameMetadata {
    source_night: String,
    filter: Option<String>,
    exposure: Option<f32>,
    gain: Option<f32>,
    temperature: Option<f32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionKind {
    Light,
    Dark,
    Flat,
    Bias,
}

#[derive(Debug, Clone)]
struct SessionBucket {
    key: String,
    fingerprint: SessionFingerprint,
    lights: Vec<File>,
    darks: Vec<File>,
    flats: Vec<File>,
    biases: Vec<File>,
}

impl SessionBucket {
    fn new(key: String, fingerprint: SessionFingerprint) -> Self {
        Self {
            key,
            fingerprint,
            lights: Vec::new(),
            darks: Vec::new(),
            flats: Vec::new(),
            biases: Vec::new(),
        }
    }

    fn push(&mut self, kind: SessionKind, file: File) {
        match kind {
            SessionKind::Light => self.lights.push(file),
            SessionKind::Dark => self.darks.push(file),
            SessionKind::Flat => self.flats.push(file),
            SessionKind::Bias => self.biases.push(file),
        }
    }

    fn into_session(self) -> AstroSession {
        AstroSession {
            uuid: self.key,
            fingerprint: self.fingerprint,
            lights: self.lights,
            darks: self.darks,
            flats: self.flats,
            biases: self.biases,
        }
    }
}

fn format_optional_text(value: Option<&str>) -> String {
    value.unwrap_or_default().trim().to_lowercase()
}

fn format_optional_float(value: Option<f32>) -> String {
    value.map(|value| format!("{value:.3}")).unwrap_or_default()
}

fn approx_equal(left: f32, right: f32) -> bool {
    (left - right).abs() <= 0.01
}

fn round_to_step(value: Option<f32>, step: f32) -> Option<f32> {
    let value = value?;

    if step <= 0.0 {
        return Some(value);
    }

    Some((value / step).round() * step)
}

fn normalize_file_type(file_type: &FileType) -> SessionKind {
    match file_type {
        FileType::Light => SessionKind::Light,
        FileType::Dark | FileType::MasterDark => SessionKind::Dark,
        FileType::Flat | FileType::MasterFlat => SessionKind::Flat,
        FileType::Bias | FileType::MasterBias => SessionKind::Bias,
    }
}

fn read_optional_float(fits: &mut FitsFile, tag: Tag) -> Option<f32> {
    fits.get_tag_custom::<f32>(tag)
        .or_else(|| fits.get_tag_custom::<f64>(tag).map(|value| value as f32))
        .or_else(|| fits.get_tag_value(tag).and_then(|value| value.parse::<f32>().ok()))
}

fn read_frame_metadata(file: &File, source_night: &str) -> Option<FrameMetadata> {
    let mut fits = FitsFile::new(file.path().clone()).ok()?;

    Some(FrameMetadata {
        source_night: source_night.to_string(),
        filter: fits
            .get_tag_value(Tag::Filter)
            .map(|value| value.trim().to_lowercase())
            .filter(|value| !value.is_empty()),
        exposure: read_optional_float(&mut fits, Tag::ExposureTime),
        gain: read_optional_float(&mut fits, Tag::Gain),
        temperature: read_optional_float(&mut fits, Tag::Temperature),
    })
}

fn light_session_key(metadata: &FrameMetadata) -> String {
    format!(
        "light:{}:{}:{}:{}:{}",
        metadata.source_night,
        format_optional_text(metadata.filter.as_deref()),
        format_optional_float(metadata.exposure),
        format_optional_float(metadata.gain),
        format_optional_float(metadata.temperature)
    )
}

fn calibration_session_key(kind: SessionKind, metadata: &FrameMetadata) -> String {
    let kind_prefix = match kind {
        SessionKind::Light => "light",
        SessionKind::Dark => "dark",
        SessionKind::Flat => "flat",
        SessionKind::Bias => "bias",
    };

    format!(
        "{kind_prefix}:{}:{}:{}:{}:{}",
        metadata.source_night,
        format_optional_text(metadata.filter.as_deref()),
        format_optional_float(metadata.exposure),
        format_optional_float(metadata.gain),
        format_optional_float(metadata.temperature)
    )
}

fn create_session_fingerprint(metadata: &FrameMetadata) -> SessionFingerprint {
    SessionFingerprint {
        name: metadata.source_night.clone(),
        filter: metadata.filter.clone().unwrap_or_default(),
        exposure: metadata.exposure.unwrap_or_default(),
        gain: metadata.gain.unwrap_or_default(),
        temperature: metadata.temperature.unwrap_or_default(),
    }
}

fn calibration_matches_session(
    kind: SessionKind,
    session: &SessionFingerprint,
    metadata: &FrameMetadata,
) -> bool {
    match kind {
        SessionKind::Light => metadata
            .filter
            .as_deref()
            .is_none_or(|value| session.filter == value)
            && metadata
                .exposure
                .is_none_or(|value| approx_equal(session.exposure, value))
            && metadata
                .gain
                .is_none_or(|value| approx_equal(session.gain, value))
            && metadata
                .temperature
                .is_none_or(|value| approx_equal(session.temperature, value)),
        SessionKind::Dark => metadata
            .exposure
            .is_none_or(|value| approx_equal(session.exposure, value))
            && metadata
                .gain
                .is_none_or(|value| approx_equal(session.gain, value))
            && metadata
                .temperature
                .is_none_or(|value| approx_equal(session.temperature, value)),
        SessionKind::Flat => metadata
            .filter
            .as_deref()
            .is_none_or(|value| session.filter == value)
            && metadata
                .gain
                .is_none_or(|value| approx_equal(session.gain, value))
            && metadata
                .temperature
                .is_none_or(|value| approx_equal(session.temperature, value)),
        SessionKind::Bias => metadata
            .gain
            .is_none_or(|value| approx_equal(session.gain, value))
            && metadata
                .temperature
                .is_none_or(|value| approx_equal(session.temperature, value)),
    }
}

fn group_preview_nights(
    preview_nights: HashMap<String, Vec<File>>,
    channel: tauri::ipc::Channel<GroupFramesProgress>,
    temperature_step: f32,
    exposure_step: f32,
    gain_step: f32,
) -> Vec<AstroSession> {
    let total_files = preview_nights.values().map(|files| files.len()).sum::<usize>();
    let mut processed_files = 0usize;

    let mut light_sessions: HashMap<String, SessionBucket> = HashMap::new();
    let mut calibration_files: Vec<(SessionKind, FrameMetadata, File)> = Vec::new();

    for (night_name, files) in preview_nights {
        for file in files {
            processed_files += 1;
            let _ = channel.send(GroupFramesProgress {
                processed: processed_files,
                total: total_files,
            });

            let file_kind = normalize_file_type(file.file_type());

            let Some(metadata) = read_frame_metadata(&file, &night_name) else {
                continue;
            };

            let metadata = FrameMetadata {
                source_night: metadata.source_night,
                filter: metadata.filter,
                exposure: round_to_step(metadata.exposure, exposure_step),
                gain: round_to_step(metadata.gain, gain_step),
                temperature: round_to_step(metadata.temperature, temperature_step),
            };

            match file_kind {
                SessionKind::Light => {
                    let key = light_session_key(&metadata);
                    let bucket = light_sessions.entry(key.clone()).or_insert_with(|| {
                        SessionBucket::new(key, create_session_fingerprint(&metadata))
                    });
                    bucket.push(SessionKind::Light, file);
                }
                SessionKind::Dark | SessionKind::Flat | SessionKind::Bias => {
                    calibration_files.push((file_kind, metadata, file));
                }
            }
        }
    }

    for (kind, metadata, file) in calibration_files {
        let mut matched_any = false;

        for bucket in light_sessions.values_mut() {
            if calibration_matches_session(kind, &bucket.fingerprint, &metadata) {
                bucket.push(kind, file.clone());
                matched_any = true;
            }
        }

        if !matched_any {
            let key = calibration_session_key(kind, &metadata);
            let bucket = light_sessions.entry(key.clone()).or_insert_with(|| {
                SessionBucket::new(key, create_session_fingerprint(&metadata))
            });
            bucket.push(kind, file);
        }
    }

    let _ = channel.send(GroupFramesProgress {
        processed: total_files,
        total: total_files,
    });

    let mut grouped = light_sessions
        .into_values()
        .map(SessionBucket::into_session)
        .collect::<Vec<_>>();

    grouped.sort_by(|left, right| {
        left.fingerprint
            .name
            .cmp(&right.fingerprint.name)
            .then_with(|| left.fingerprint.filter.cmp(&right.fingerprint.filter))
            .then_with(|| left.fingerprint.exposure.total_cmp(&right.fingerprint.exposure))
            .then_with(|| left.fingerprint.gain.total_cmp(&right.fingerprint.gain))
            .then_with(|| left.fingerprint.temperature.total_cmp(&right.fingerprint.temperature))
    });

    grouped
}

#[tauri::command]
pub async fn get_fe_state(state: tauri::State<'_, Mutex<AppState>>) -> Result<FeState, String> {
    let state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    Ok(state.fe_state.clone())
}

#[tauri::command]
pub async fn set_fe_state(
    fe_state: FeState,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state = fe_state;
    Ok(())
}

#[tauri::command]
pub async fn set_fe_current_preview_file(
    path: Option<String>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state.current_preview_file = path;
    Ok(())
}

#[tauri::command]
pub async fn group_frames(
    channel: tauri::ipc::Channel<GroupFramesProgress>,
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<FeState, String> {
    let config = config::read_config(&app_handle)
        .await
        .unwrap_or_default();

    let preview_nights = {
        let state = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        match &state.fe_state.nights {
            Nights::PreviewNights(nights) => nights.clone(),
            Nights::GroupedNights(_) => {
                return Err("Frames are already grouped".to_string());
            }
        }
    };

    let grouped_nights = group_preview_nights(
        preview_nights,
        channel,
        config.temperature_step,
        config.exposure_step,
        config.gain_step,
    );

    let fe_state = FeState {
        nights: Nights::GroupedNights(grouped_nights),
        current_preview_file: None,
    };

    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state = fe_state.clone();

    Ok(fe_state)
}
