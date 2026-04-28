mod calibrate;
mod group;

pub use group::group_preview_nights;

use calibrate::create_master_frames;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

use crate::{
    config,
    state::fe_state::AstroSession,
    state::{
        AppState, CalibrateRequest, CalibrationCancellation, CalibrationProgressMessage,
        GroupFramesProgress,
    },
};

#[tauri::command]
pub async fn group_frames(
    channel: tauri::ipc::Channel<GroupFramesProgress>,
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<Vec<AstroSession>, String> {
    let config = config::read_config(&app_handle).await.unwrap_or_default();

    let preview_nights = {
        let state = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        state.fe_state.raw_nights.clone()
    };

    let grouped_nights = group_preview_nights(
        preview_nights,
        channel,
        config.temperature_step,
        config.exposure_step,
        config.gain_step,
    );

    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state.grouped_nights = grouped_nights.clone();

    Ok(grouped_nights)
}

#[tauri::command]
pub async fn calibrate(
    request: CalibrateRequest,
    channel: tauri::ipc::Channel<CalibrationProgressMessage>,
    state: tauri::State<'_, Mutex<AppState>>,
    calibration_cancellation: tauri::State<'_, CalibrationCancellation>,
) -> Result<(), String> {
    calibration_cancellation
        .requested
        .store(false, Ordering::Relaxed);

    let mut fe_state = {
        let state = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        state.fe_state.clone()
    };

    let temp_folder = PathBuf::from(&request.temp_folder_path);
    create_master_frames(
        &mut fe_state,
        &temp_folder,
        channel,
        &calibration_cancellation,
    )?;

    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state = fe_state;
    Ok(())
}

#[tauri::command]
pub async fn calibrate_cancel(
    calibration_cancellation: tauri::State<'_, CalibrationCancellation>,
) -> Result<(), String> {
    calibration_cancellation
        .requested
        .store(true, Ordering::Relaxed);
    Ok(())
}
