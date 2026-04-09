use std::{path::PathBuf, sync::Mutex};

use crate::{
    fits::{
        file::ReadImageError,
        image_data_pixels::{ImageData, ImageOptions},
        structs::FitsOpenError,
        utils::normalize_data,
    },
    state::AppState,
};

mod file;
mod image_data_pixels;
mod structs;
mod tag;
mod utils;

//public re-exports
pub use image_data_pixels::ImageDataPixels;
pub use file::FitsFile;
pub use structs::FileType;
pub use tag::Tag;

#[tauri::command]
pub async fn fits_read_image(
    path: PathBuf,
    mut options: Option<ImageOptions>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<ImageData, String> {
    let preview_path = path.to_string_lossy().to_string();
    let mut state = state.lock().unwrap();

    let mut image = if let Some(current_image) = &state.rust_state.current_image
        && current_image.path == path
    {
        current_image.data.clone()
    } else {
        let mut fits = file::FitsFile::new(path.clone()).map_err(|err| match err {
            FitsOpenError::OpenError => "Unable to open file, does the file exists?".to_string(),
            FitsOpenError::NoHudFound => "Unable to find primary HDU in fits file".to_string(),
        })?;

        let mut image = ImageDataPixels::from_fits(&mut fits).map_err(|err| match err {
            ReadImageError::ReadImageFailed => {
                "Unable to read image data from fits file".to_string()
            }
            ReadImageError::UnableToExtractImageSize => {
                "Unable to extract image size from fits file".to_string()
            }
        })?;

        let image_type = fits.get_image_type().unwrap();

        //Normalize data at first load
        normalize_data(&mut image.pixels, &image_type);
        image.to_rgb_layout();

        let mut current_image = crate::state::CurrentImage { path, data: image };

        //save current image to app state
        state
            .rust_state
            .current_image
            .replace(current_image.clone());
        current_image.data
    };

    if let Some(options) = options {
        if let Some(bayer_pattern) = options.bayer_pattern {
            image.debayer(Some(bayer_pattern));
        }
        //rescale

        if options.scale != image.data.applied_options.scale {
            image.scale(options.scale);
        }
    } else {
        //we debayer the image, because we have saved the original Grayscale
        if !image.debayer(
            None, /* This will use the bayerpattern from FITS if presented */
        ) {
            //If we don't debayer, we set options to default, so we apply
            //The 50% downscaling, so we don't transfer huge grayscale images to FE
            options.replace(ImageOptions::default());
        }
    }

    //calculate auto-STF
    image.calculate_stf();

    let converted = image
        .to_js_imagedata()
        .ok_or("Unable to convert image data to js imagedata, unsupported layout")?;

    state.rust_state.current_image_data.replace(converted);
    state.fe_state.current_preview_file.replace(preview_path);

    Ok(image.data)
}
