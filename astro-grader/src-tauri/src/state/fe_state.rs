use std::collections::HashMap;

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

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct AstroSession {
    pub uuid: String,
    pub fingerprint: SessionFingerprint,

    //data
    pub lights: Vec<File>,
    pub darks: Vec<File>,
    pub flats: Vec<File>,
    pub biases: Vec<File>,
}

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct FeState {
    pub raw_nights: HashMap<String, Vec<File>>,
    pub grouped_nights: Vec<AstroSession>,
    pub active_grouped_session_uuid: Option<String>,
    pub current_preview_file: Option<String>,
}
