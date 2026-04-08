use std::sync::Mutex;

use crate::state::{fe_state::FeState, rust_state::RustState};

mod fe_state;
mod rust_state;

pub use rust_state::CurrentImage;

#[derive(Debug, Default)]
pub struct AppState {
    pub rust_state: RustState,
    pub fe_state: FeState,
}

#[tauri::command]
pub async fn get_fe_state(state: tauri::State<'_, Mutex<AppState>>) -> Result<FeState, String> {
    let state = state
        .lock()
        .map_err(|_| "Failed to acquire app state lock".to_string())?;
    Ok(state.fe_state.clone())
}
