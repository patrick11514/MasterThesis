use std::{path::PathBuf, sync::Mutex, thread::current};

use crate::fits::{
    file::ReadImageError,
    image_data_pixels::{ImageData, ImageOptions},
    structs::FitsOpenError,
};

mod file;
mod image_data_pixels;
mod structs;
mod tag;
mod utils;

//public re-exports
pub use image_data_pixels::ImageDataPixels;
pub use structs::FileType;

#[tauri::command]
pub async fn fits_read_image(
    path: PathBuf,
    options: Option<ImageOptions>,
    state: tauri::State<'_, Mutex<crate::AppState>>,
) -> Result<ImageData, String> {
    let state = state.lock().unwrap();

    let image = if let Some(current_image) = &state.current_image && current_image.path == path {
        current_image.data
    } else {

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

    let current_image = crate::app_state::CurrentImage {
        path,
        data: image
    };

    //save current image to app state
    state
        .current_image
        .replace(current_image.clone());

    current_image.data
};

    let bayer_format = fits.get_tag_value(tag::Tag::BayerPattern);

    let converted = image
        .to_js_imagedata()
        .ok_or("Unable to convert image data to js imagedata, unsupported layout")?;

    state.current_image_data.replace(converted);

    Ok(image.data)
}
