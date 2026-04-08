use std::collections::HashMap;

#[derive(Debug, Default, Clone, serde::Serialize, serde::Deserialize)]
pub struct FeState {
    pub nights: HashMap<String, Vec<String>>,
}
