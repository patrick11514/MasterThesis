use std::path::PathBuf;

use ts_rs::TS;

use crate::fits::{file::ReadImageError, image_data_pixels::ImageData, structs::FitsOpenError};

mod file;
mod image_data_pixels;
mod structs;
mod tag;
mod utils;

//public re-exports
pub use structs::FileType;

#[tauri::command]
pub async fn fits_read_image(path: PathBuf) -> Result<ImageData, String> {
    tokio::task::spawn_blocking(move || {
        let start = std::time::Instant::now();
        println!("Reading image from fits file: {:?}", path);
        let mut fits = file::FitsFile::new(path).map_err(|err| match err {
            FitsOpenError::OpenError => "Unable to open file, does the file exists?".to_string(),
            FitsOpenError::NoHudFound => "Unable to find primary HDU in fits file".to_string(),
        })?;

        println!("Extracting image data from fits file");

        let image = fits.read_image().map_err(|err| match err {
            ReadImageError::ReadImageFailed => {
                "Unable to read image data from fits file".to_string()
            }
            ReadImageError::UnableToExtractImageSize => {
                "Unable to extract image size from fits file".to_string()
            }
        })?;

        println!("sonverting image data to js imagedata");
        let converted = image.to_js_imagedata();
        println!("Started sending image data to frontend");

        Ok(image.data)
    })
    .await
    .map_err(|_| String::from("Failed to read image"))?
}
