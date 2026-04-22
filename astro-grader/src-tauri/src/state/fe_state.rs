use std::collections::HashMap;

use serde::de;
use ts_rs::TS;

use crate::file_picker::File;

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct SessionFingerprint {
    pub name: String,
    pub camera: String,
    pub filter: String,
    pub exposure: f32,
    pub gain: f32,
    pub temperature: f32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum MasterOrFrames {
    Master(File),
    Frames(Vec<File>),
}

impl Default for MasterOrFrames {
    fn default() -> Self {
        MasterOrFrames::Frames(vec![])
    }
}

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct AstroSession {
    pub uuid: String,
    pub fingerprint: SessionFingerprint,

    //data
    pub lights: Vec<File>,
    pub darks: MasterOrFrames,
    pub flats: MasterOrFrames,
    pub biases: MasterOrFrames,
}

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct FeState {
    pub raw_nights: HashMap<String, Vec<File>>,
    pub grouped_nights: Vec<AstroSession>,
    pub active_grouped_session_uuid: Option<String>,
    pub current_preview_file: Option<String>,
}

pub async fn save_fe_state(path: String, state: FeState) -> Result<(), String> {
    let json =
        serde_json::to_string(&state).map_err(|_| "Failed to serialize state".to_string())?;
    tokio::fs::write(path, json)
        .await
        .map_err(|_| "Failed to write state to file".to_string())?;
    Ok(())
}

pub async fn load_fe_state(path: String) -> Result<FeState, String> {
    let data = tokio::fs::read_to_string(path)
        .await
        .map_err(|_| "Failed to read state file".to_string())?;
    let state =
        serde_json::from_str(&data).map_err(|_| "Failed to parse state file".to_string())?;
    Ok(state)
}
