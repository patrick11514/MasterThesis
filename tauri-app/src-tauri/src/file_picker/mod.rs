use rayon::prelude::*;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use walkdir::WalkDir;

#[tauri::command]
pub async fn recursive(
    extensions: Vec<String>,
    directory: PathBuf,
    channel: tauri::ipc::Channel<usize>,
) -> Vec<PathBuf> {
    let dir = WalkDir::new(directory);

    let extensions = extensions
        .into_iter()
        .map(OsString::from)
        .collect::<Vec<_>>();

    // 1. Initialize a thread-safe atomic counter
    let counter = AtomicUsize::new(0);

    let result = dir
        .into_iter()
        .par_bridge()
        // Simplify the first filter_map
        .filter_map(|file| file.ok())
        .filter_map(|file| {
            if let Some(ext) = file.path().extension() {
                if extensions.iter().any(|_ext| ext == _ext) {
                    // 2. Safely increment the counter across all threads
                    // fetch_add returns the PREVIOUS value, so we add 1 for the current state
                    let current_count = counter.fetch_add(1, Ordering::Relaxed) + 1;

                    // 3. Prevent IPC flooding: Only send update every 50 files
                    if current_count % 50 == 0 {
                        // We ignore the Result here. If the frontend channel dropped,
                        // we just keep processing the files anyway.
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
