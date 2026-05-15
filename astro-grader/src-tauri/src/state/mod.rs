use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::{
    config,
    state::{
        fe_state::{AstroSession, FeState, load_fe_state, save_fe_state},
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
pub struct CalibrateRequest {
    pub storage_mode: config::CalibrationStorageMode,
    pub temp_folder_path: String,
}

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub enum FileBatchOperationKind {
    Move,
    Delete,
}

#[derive(Debug, Clone, Copy, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub enum FileBatchOperationStatus {
    Running,
    Completed,
    Failed,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, ts_rs::TS)]
#[ts(export)]
pub struct FileBatchOperationProgressMessage {
    pub started_at: u64,
    pub finished_at: Option<u64>,
    pub status: FileBatchOperationStatus,
    pub operation: FileBatchOperationKind,
    pub processed_count: usize,
    pub total_count: usize,
    pub current_path: Option<String>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FileBatchOperationRequest {
    pub operation: FileBatchOperationKind,
    pub paths: Vec<String>,
    pub target_directory: Option<String>,
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}

fn send_file_batch_progress(
    channel: &tauri::ipc::Channel<FileBatchOperationProgressMessage>,
    progress: &FileBatchOperationProgressMessage,
) {
    let _ = channel.send(progress.clone());
}

fn path_name(path: &Path) -> Result<PathBuf, String> {
    let name = path
        .file_name()
        .ok_or_else(|| format!("Path has no file name: {}", path.display()))?;

    Ok(PathBuf::from(name))
}

fn build_move_target(target_directory: &Path, source_path: &Path) -> Result<PathBuf, String> {
    Ok(target_directory.join(path_name(source_path)?))
}

fn file_exists(path: &Path) -> bool {
    path.exists()
}

fn move_file(source_path: &Path, target_path: &Path) -> Result<(), String> {
    if file_exists(target_path) {
        return Err(format!("Target already exists: {}", target_path.display()));
    }

    match fs::rename(source_path, target_path) {
        Ok(()) => Ok(()),
        Err(error) if error.raw_os_error() == Some(18) => {
            fs::copy(source_path, target_path).map_err(|copy_error| {
                format!("Failed to copy {}: {}", source_path.display(), copy_error)
            })?;
            fs::remove_file(source_path).map_err(|remove_error| {
                format!(
                    "Failed to remove source {}: {}",
                    source_path.display(),
                    remove_error
                )
            })?;
            Ok(())
        }
        Err(error) => Err(format!(
            "Failed to move {}: {}",
            source_path.display(),
            error
        )),
    }
}

fn delete_file(source_path: &Path) -> Result<(), String> {
    fs::remove_file(source_path)
        .map_err(|error| format!("Failed to delete {}: {}", source_path.display(), error))
}

fn remove_paths_from_fe_state(fe_state: &mut FeState, removed_paths: &HashSet<String>) {
    if removed_paths.is_empty() {
        return;
    }

    for files in fe_state.raw_nights.values_mut() {
        files.retain(|file| !removed_paths.contains(file.path().to_string_lossy().as_ref()));
    }
    fe_state.raw_nights.retain(|_, files| !files.is_empty());

    for session in &mut fe_state.grouped_nights {
        session
            .lights
            .retain(|file| !removed_paths.contains(file.path().to_string_lossy().as_ref()));
    }
    fe_state
        .grouped_nights
        .retain(|session: &AstroSession| !session.lights.is_empty());

    if fe_state
        .current_preview_file
        .as_ref()
        .is_some_and(|path| removed_paths.contains(path))
    {
        fe_state.current_preview_file = None;
    }

    if fe_state.grouped_nights.is_empty() {
        fe_state.active_grouped_session_uuid = None;
        return;
    }

    let still_exists = fe_state.grouped_nights.iter().any(|session| {
        fe_state
            .active_grouped_session_uuid
            .as_ref()
            .is_some_and(|uuid| uuid == &session.uuid)
    });

    if !still_exists {
        fe_state.active_grouped_session_uuid = Some(fe_state.grouped_nights[0].uuid.clone());
    }
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

#[tauri::command]
pub async fn batch_file_operation(
    request: FileBatchOperationRequest,
    channel: tauri::ipc::Channel<FileBatchOperationProgressMessage>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<FeState, String> {
    if request.paths.is_empty() {
        return Err("No files selected".to_string());
    }

    if matches!(request.operation, FileBatchOperationKind::Move)
        && request.target_directory.is_none()
    {
        return Err("A target directory is required for move operations".to_string());
    }

    let mut fe_state = {
        let state = state
            .lock()
            .map_err(|_| "Failed to acquire app state lock".to_string())?;

        state.fe_state.clone()
    };

    let started_at = now_millis();
    let mut progress = FileBatchOperationProgressMessage {
        started_at,
        finished_at: None,
        status: FileBatchOperationStatus::Running,
        operation: request.operation,
        processed_count: 0,
        total_count: request.paths.len(),
        current_path: None,
        error: None,
    };

    send_file_batch_progress(&channel, &progress);

    let operation_result = tokio::task::spawn_blocking(move || -> Result<FeState, String> {
        let mut removed_paths = HashSet::new();

        for path_string in &request.paths {
            let source_path = PathBuf::from(path_string);
            progress.current_path = Some(path_string.clone());
            send_file_batch_progress(&channel, &progress);

            if !source_path.exists() {
                progress.status = FileBatchOperationStatus::Failed;
                progress.finished_at = Some(now_millis());
                progress.error = Some(format!(
                    "Source file no longer exists: {}",
                    source_path.display()
                ));
                send_file_batch_progress(&channel, &progress);
                return Err(progress
                    .error
                    .clone()
                    .unwrap_or_else(|| "Unknown file operation error".to_string()));
            }

            match request.operation {
                FileBatchOperationKind::Move => {
                    let target_directory = request.target_directory.as_ref().ok_or_else(|| {
                        "A target directory is required for move operations".to_string()
                    })?;
                    let target_directory = PathBuf::from(target_directory);
                    fs::create_dir_all(&target_directory).map_err(|error| {
                        format!(
                            "Failed to create target directory {}: {}",
                            target_directory.display(),
                            error
                        )
                    })?;
                    let target_path = build_move_target(&target_directory, &source_path)?;
                    move_file(&source_path, &target_path)?;
                }
                FileBatchOperationKind::Delete => {
                    delete_file(&source_path)?;
                }
            }

            removed_paths.insert(path_string.clone());
            progress.processed_count += 1;
            send_file_batch_progress(&channel, &progress);
        }

        progress.status = FileBatchOperationStatus::Completed;
        progress.finished_at = Some(now_millis());
        progress.current_path = None;
        send_file_batch_progress(&channel, &progress);

        remove_paths_from_fe_state(&mut fe_state, &removed_paths);

        Ok(fe_state)
    })
    .await
    .map_err(|error| format!("File operation task failed: {}", error))??;

    let mut state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    state.fe_state = operation_result.clone();

    Ok(operation_result)
}
