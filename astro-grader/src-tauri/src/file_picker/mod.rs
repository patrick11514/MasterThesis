use fitsio::HeaderValue;
use rayon::prelude::*;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use ts_rs::TS;
use walkdir::WalkDir;

use crate::fits::FileType;

#[derive(serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct File {
    path: PathBuf,
    name: String,
    #[serde(rename = "type")]
    file_type: FileType,
}

fn path_to_file(file_path: PathBuf) -> Option<File> {
    if let Ok(mut fits_file) = fitsio::FitsFile::open(&file_path) {
        if let Ok(hdu) = fits_file.primary_hdu() {
            let file_type = match hdu.read_key::<HeaderValue<String>>(&mut fits_file, "IMAGETYP") {
                Ok(result) => match result.value.to_lowercase().as_str() {
                    "light" | "master light" => FileType::Light,
                    "dark" => FileType::Dark,
                    "flat" => FileType::Flat,
                    "bias" => FileType::Bias,
                    "master dark" => FileType::MasterDark,
                    "master flat" => FileType::MasterFlat,
                    "master bias" => FileType::MasterBias,
                    _ => FileType::Light, // Default to Light if the value is unrecognized
                },
                Err(_) => FileType::Light, // Default to Light if the key is missing or cannot be read
            };

            return Some(File {
                file_type,
                path: file_path.clone(),
                name: file_path
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned(),
            });
        }
    }
    None
}

#[tauri::command]
pub async fn file_picker_recursive(
    extensions: Vec<String>,
    directory: PathBuf,
    channel: tauri::ipc::Channel<usize>,
) -> Vec<File> {
    let dir = WalkDir::new(directory);

    let extensions = extensions
        .into_iter()
        .map(OsString::from)
        .collect::<Vec<_>>();

    let counter = AtomicUsize::new(0);

    let result = dir
        .into_iter()
        .par_bridge()
        .filter_map(|file| file.ok())
        .filter_map(|file| {
            if let Some(ext) = file.path().extension() {
                if extensions.iter().any(|_ext| ext == _ext) {
                    let current_count = counter.fetch_add(1, Ordering::Relaxed) + 1;

                    if current_count % 50 == 0 {
                        let _ = channel.send(current_count);
                    }

                    path_to_file(file.path().to_path_buf())
                } else {
                    None
                }
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    // 4. Send the final count.
    // If the loop finished at 143 files, the UI would be stuck at "100" without this.
    let final_count = counter.load(Ordering::Relaxed);
    let _ = channel.send(final_count);

    result
}

#[tauri::command]
pub async fn file_picker_convert(files: Vec<PathBuf>) -> Vec<File> {
    files.into_par_iter().filter_map(path_to_file).collect()
}
