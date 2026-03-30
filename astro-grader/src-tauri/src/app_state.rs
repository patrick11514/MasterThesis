use std::sync::Mutex;

use crate::fits::ImageDataPixels;

#[derive(Debug, Clone)]
struct CurrentImage {
    path: String,
    data: ImageDataPixels,
}

#[derive(Debug, Default)]
pub struct AppState {
    pub current_image: Option<CurrentImage>,
    pub current_image_data: Mutex<Option<Vec<u8>>>,
}
