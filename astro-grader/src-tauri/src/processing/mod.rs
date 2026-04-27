mod group;
mod calibrate;

pub use group::group_preview_nights;

use std::sync::Mutex;

use crate::{
    config,
    state::{AppState, GroupFramesProgress, CalibrateRequest},
    state::fe_state::AstroSession,
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
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;

    println!(
        "calibrate command stub: mode={:?}, targets={}, temp_folder={}, grouped_sessions={}",
        request.storage_mode,
        request.targets.len(),
        request.temp_folder_path,
        state.fe_state.grouped_nights.len()
    );

    for target in &request.targets {
        println!(
            "calibrate target: source={} calibrated={}",
            target.source_path, target.calibrated_path
        );
    }

    Ok(())
}
