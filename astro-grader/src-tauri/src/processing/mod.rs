mod calibrate;
mod group;
mod metrics;

pub use group::group_preview_nights;

use calibrate::run_calibration;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

use crate::{
    config,
    state::fe_state::{AstroSession, FeState},
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
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
    calibration_cancellation: tauri::State<'_, CalibrationCancellation>,
) -> Result<FeState, String> {
    calibration_cancellation
        .requested
        .store(false, Ordering::Relaxed);

    let mut fe_state = {
        let state_guard = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        state_guard.fe_state.clone()
    };

    // Spawn blocking to prevent Rayon and FITS I/O from starving the Tokio runtime,
    // which freezes IPC channel messaging to the frontend.
    let updated_fe_state = tokio::task::spawn_blocking(move || {
        use tauri::Manager;
        let cancellation_state = app_handle.state::<CalibrationCancellation>();

        let temp_folder = PathBuf::from(&request.temp_folder_path);
        run_calibration(
            &mut fe_state,
            &temp_folder,
            &request.targets,
            channel,
            &cancellation_state,
        )?;

        Ok::<_, String>(fe_state)
    })
    .await
    .map_err(|e| format!("Calibration task failed: {}", e))??;

    let mut state_guard = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state_guard.fe_state = updated_fe_state;

    Ok(state_guard.fe_state.clone())
}

#[tauri::command]
pub async fn run_metrics(
    channel: tauri::ipc::Channel<crate::state::CalibrationProgressMessage>,
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<FeState, String> {
    let config = config::read_config(&app_handle).await.unwrap_or_default();

    let mut fe_state = {
        let state_guard = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        state_guard.fe_state.clone()
    };

    let updated_fe_state = tokio::task::spawn_blocking(move || {
        metrics::run_metrics(
            &mut fe_state,
            channel,
            config.cross_night_reference,
            config.max_fwhm,
        )?;
        Ok::<_, String>(fe_state)
    })
    .await
    .map_err(|e| format!("Metrics task failed: {}", e))??;

    let mut state_guard = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state_guard.fe_state = updated_fe_state;

    Ok(state_guard.fe_state.clone())
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
