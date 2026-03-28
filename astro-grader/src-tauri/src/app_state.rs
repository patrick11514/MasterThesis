use std::sync::{Arc, Mutex};

#[derive(Debug, Default)]
pub struct AppState {
    pub current_image_data: Mutex<Option<Vec<u8>>>,
}
