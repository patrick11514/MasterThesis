use rayon::prelude::*;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use walkdir::WalkDir;

#[tauri::command]
pub async fn file_picker_recursive(
    extensions: Vec<String>,
    directory: PathBuf,
    channel: tauri::ipc::Channel<usize>,
) -> Vec<PathBuf> {
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

                    Some(file.path().to_owned())
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
