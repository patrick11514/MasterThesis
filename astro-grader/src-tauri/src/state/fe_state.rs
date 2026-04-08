use std::collections::HashMap;

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize)]
pub struct FeFile {
    pub path: String,
    pub name: String,
    #[serde(rename = "type")]
    pub file_type: String,
}

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize)]
pub struct FeState {
    pub nights: HashMap<String, Vec<FeFile>>,
    pub current_preview_file: Option<String>,
}
