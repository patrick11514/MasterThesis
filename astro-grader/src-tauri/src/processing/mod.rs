mod calibrate;
mod group;

pub use group::group_preview_nights;

use calibrate::create_master_frames;
use std::path::PathBuf;
use std::sync::Mutex;

use crate::{
    config,
    state::fe_state::AstroSession,
    state::{AppState, CalibrateRequest, GroupFramesProgress},
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
    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;

    let temp_folder = PathBuf::from(&request.temp_folder_path);
    create_master_frames(&mut state.fe_state, &temp_folder)?;
    Ok(())
}
