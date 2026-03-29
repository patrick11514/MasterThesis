use std::path::PathBuf;

use crate::fits::{file::ReadImageError, image_data_pixels::ImageData, structs::FitsOpenError};

mod file;
mod image_data_pixels;
mod structs;
mod tag;
mod utils;

//public re-exports
pub use structs::FileType;

#[tauri::command]
pub async fn fits_read_image(
    path: PathBuf,
    state: tauri::State<'_, crate::AppState>,
) -> Result<ImageData, String> {
    let mut fits = file::FitsFile::new(path).map_err(|err| match err {
        FitsOpenError::OpenError => "Unable to open file, does the file exists?".to_string(),
        FitsOpenError::NoHudFound => "Unable to find primary HDU in fits file".to_string(),
    })?;

    let image = fits.read_image().map_err(|err| match err {
        ReadImageError::ReadImageFailed => "Unable to read image data from fits file".to_string(),
        ReadImageError::UnableToExtractImageSize => {
            "Unable to extract image size from fits file".to_string()
        }
    })?;

    let converted = image.to_js_imagedata();
    *state.current_image_data.lock().unwrap() = Some(converted);

    Ok(image.data)
}
