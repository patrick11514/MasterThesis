use std::{
    ffi::{OsStr, OsString},
    path::PathBuf,
};

use rayon::iter::{ParallelBridge, ParallelIterator};
use tauri::{
    plugin::{Builder, TauriPlugin},
    Runtime,
};
use walkdir::WalkDir;

#[tauri::command]
pub async fn recursive(extensions: Vec<String>, directory: PathBuf) -> Vec<PathBuf> {
    let dir = WalkDir::new(directory);

    let extensions = extensions
        .into_iter()
        .map(|ext| OsString::from(ext))
        .collect::<Vec<_>>();

    return dir
        .into_iter()
        .par_bridge()
        .filter_map(|file| {
            if let Ok(file) = file {
                Some(file)
            } else {
                None
            }
        })
        .filter_map(|file| {
            if let Some(ext) = &file.path().extension() {
                if extensions.iter().any(|_ext| ext == _ext) {
                    Some(file.path().to_owned())
                } else {
                    None
                }
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
}
