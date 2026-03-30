use std::{path::PathBuf, sync::Mutex};

use crate::fits::ImageDataPixels;

#[derive(Debug, Clone)]
pub struct CurrentImage {
    pub path: PathBuf,
    pub data: ImageDataPixels,
}

#[derive(Debug, Default)]
pub struct AppState {
    pub current_image: Option<CurrentImage>,
    pub current_image_data: Option<Vec<u8>>,
}
