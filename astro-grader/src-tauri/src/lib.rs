use std::sync::Mutex;

use tauri::{Manager, State, http};

mod config;
mod file_picker;
pub mod fits;
pub mod processing;
mod state;

static URL_PREFIXES: [&str; 4] = [
    "astro-grader://",
    "http://astro-grader.localhost/",
    "https://astro-grader.localhost/",
    "astro-grader://localhost/",
];

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_os::init())
        .manage(Mutex::new(state::AppState::default()))
        .manage(file_picker::ScanCancellation::default())
        .manage(state::CalibrationCancellation::default())
        .register_uri_scheme_protocol("astro-grader", |app, request| {
            let raw_uri = request.uri().to_string();
            let mut path = raw_uri;
            for prefix in URL_PREFIXES {
                if let Some(stripped) = path.strip_prefix(prefix) {
                    path = stripped.to_string();
                    break;
                }
            }

            let trimmed = path.trim_matches('/');
            if trimmed == "preview" {
                let state: State<Mutex<state::AppState>> = app.app_handle().state();
                let buffer = state.lock().unwrap().rust_state.current_image_data.clone();

                return match buffer {
                    Some(data) => http::Response::builder()
                        .header("Content-Type", "application/octet-stream")
                        .header("Access-Control-Allow-Origin", "*")
                        .body(data)
                        .unwrap(),
                    None => http::Response::builder()
                        .header("Access-Control-Allow-Origin", "*")
                        .status(404)
                        .body(vec![])
                        .unwrap(),
                };
            }

            http::Response::builder().status(404).body(vec![]).unwrap()
        })
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            //File Picker Module
            file_picker::file_picker_recursive,
            file_picker::file_picker_cancel_recursive,
            file_picker::file_picker_convert,
            //Config Module
            config::config_get,
            config::config_set,
            config::config_path_get,
            config::config_open_folder,
            //Fits
            fits::fits_read_image,
            //State
            state::get_fe_state,
            state::set_fe_state,
            state::set_fe_current_preview_file,
            processing::group_frames,
            processing::calibrate,
            processing::run_metrics,
            processing::calibrate_cancel,
            state::save_state,
            state::load_state
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
