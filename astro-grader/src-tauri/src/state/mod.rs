use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use crate::{
    config,
    state::{
        fe_state::{FeState, load_fe_state, save_fe_state},
        rust_state::RustState,
    },
};

pub mod fe_state;
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

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub enum CalibrationStepKind {
    Dark,
    Flat,
    Bias,
    Light,
}

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub enum CalibrationStepStatus {
    Pending,
    Running,
    Completed,
    Skipped,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub enum CalibrationRunStatus {
    Running,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub struct CalibrationProgressStep {
    pub id: String,
    pub kind: CalibrationStepKind,
    pub label: String,
    pub session_uuid: String,
    pub session_label: String,
    pub count: usize,
    pub completed_count: usize,
    pub skipped_count: usize,
    pub rejected_count: usize,
    pub status: CalibrationStepStatus,
    pub started_at: Option<u64>,
    pub ended_at: Option<u64>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub struct CalibrationProgressMessage {
    pub started_at: u64,
    pub finished_at: Option<u64>,
    pub status: CalibrationRunStatus,
    pub current_step_id: Option<String>,
    pub steps: Vec<CalibrationProgressStep>,
}

#[derive(Debug, Default)]
pub struct CalibrationCancellation {
    pub requested: AtomicBool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub struct CalibrateFrameTarget {
    pub source_path: String,
    pub calibrated_path: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub struct CalibrateRequest {
    pub storage_mode: config::CalibrationStorageMode,
    pub temp_folder_path: String,
    pub targets: Vec<CalibrateFrameTarget>,
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
pub async fn save_state(
    path: String,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let state = {
        state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?
            .fe_state
            .clone()
    };

    save_fe_state(path, state).await
}

#[tauri::command]
pub async fn load_state(
    path: String,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let data = load_fe_state(path).await?;

    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;

    state.fe_state = data;

    Ok(())
}
