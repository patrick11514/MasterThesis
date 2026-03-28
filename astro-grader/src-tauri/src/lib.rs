use std::path::Path;

use fitsio::hdu::HduInfo;
use rayon::iter::ParallelIterator;
use rayon::prelude::*;
use tauri::{http, Manager, State};

use crate::app_state::AppState;

mod config;
mod file_picker;
mod fits;

#[tauri::command]
async fn test3(src: String) -> tauri::ipc::Response {
    println!("starting thread test3 for {}", src);
    tokio::task::spawn_blocking(move || {
        println!("got data");
        let src_path = Path::new(&src);

        let mut f = fitsio::FitsFile::open(src_path).unwrap();
        let hdu = f.hdu(0).unwrap();

        let (width, height, pixels): (usize, usize, Vec<f32>) = match hdu.info {
            HduInfo::ImageInfo { ref shape, .. } => {
                let height = shape[0];
                let width = shape[1];
                let pixels: Vec<f32> = hdu.read_image(&mut f).unwrap();
                (width, height, pixels)
            }
            _ => panic!("Not an image"),
        };

        // 4x4 downsampling + RGGB debayer
        let new_w = width / 4;
        let new_h = height / 4;

        println!(
            "Downsampling from {}x{} to {}x{}",
            width, height, new_w, new_h
        );

        let mut rgb_data = Vec::with_capacity(3 * new_w * new_h);

        for y in 0..new_h {
            for x in 0..new_w {
                let mut sum_r = 0.0;
                let mut count_r = 0.0;
                let mut sum_g = 0.0;
                let mut count_g = 0.0;
                let mut sum_b = 0.0;
                let mut count_b = 0.0;

                for dy in 0..4 {
                    let oy = y * 4 + dy;
                    if oy >= height {
                        continue;
                    }
                    for dx in 0..4 {
                        let ox = x * 4 + dx;
                        if ox >= width {
                            continue;
                        }

                        let val = pixels[oy * width + ox];

                        // RGGB pattern
                        // row even: R G R G
                        // row odd:  G B G B
                        let is_even_row = oy % 2 == 0;
                        let is_even_col = ox % 2 == 0;

                        match (is_even_row, is_even_col) {
                            (true, true) => {
                                sum_r += val;
                                count_r += 1.0;
                            } // R
                            (true, false) => {
                                sum_g += val;
                                count_g += 1.0;
                            } // G
                            (false, true) => {
                                sum_g += val;
                                count_g += 1.0;
                            } // G
                            (false, false) => {
                                sum_b += val;
                                count_b += 1.0;
                            } // B
                        }
                    }
                }

                let r = if count_r > 0.0 { sum_r / count_r } else { 0.0 };
                let g = if count_g > 0.0 { sum_g / count_g } else { 0.0 };
                let b = if count_b > 0.0 { sum_b / count_b } else { 0.0 };

                rgb_data.push(r);
                rgb_data.push(g);
                rgb_data.push(b);
            }
        }

        // Return Width, Height (u32 each) + float32 rgb_data
        let mut out_bytes = Vec::with_capacity(8 + rgb_data.len() * 4);
        out_bytes.extend_from_slice(&(new_w as u32).to_le_bytes());
        out_bytes.extend_from_slice(&(new_h as u32).to_le_bytes());
        for &val in &rgb_data {
            out_bytes.extend_from_slice(&val.to_le_bytes());
        }

        tauri::ipc::Response::new(out_bytes)
    })
    .await
    .unwrap()
}

#[tauri::command]
async fn test4_stretch(
    data: Vec<u8>,
    width: u32,
    height: u32,
    linked: bool,
    stretch_level: f32,
) -> tauri::ipc::Response {
    println!("starting test4_stretch");
    tokio::task::spawn_blocking(move || {
        // cast bytes back to f32. Ensure data length is divisible by 4.
        let float_data: &[f32] = bytemuck::cast_slice(&data);
        let num_pixels = (width * height) as usize;

        // Pass 1: find min/max
        let (mut r_min, mut r_max, mut g_min, mut g_max, mut b_min, mut b_max) = float_data
            .par_chunks_exact(3)
            .fold(
                || (f32::MAX, f32::MIN, f32::MAX, f32::MIN, f32::MAX, f32::MIN),
                |acc, pixel| {
                    let r = pixel[0];
                    let g = pixel[1];
                    let b = pixel[2];
                    (
                        acc.0.min(r),
                        acc.1.max(r),
                        acc.2.min(g),
                        acc.3.max(g),
                        acc.4.min(b),
                        acc.5.max(b),
                    )
                },
            )
            .reduce(
                || (f32::MAX, f32::MIN, f32::MAX, f32::MIN, f32::MAX, f32::MIN),
                |a, b| {
                    (
                        a.0.min(b.0),
                        a.1.max(b.1),
                        a.2.min(b.2),
                        a.3.max(b.3),
                        a.4.min(b.4),
                        a.5.max(b.5),
                    )
                },
            );

        if linked {
            let overall_min = r_min.min(g_min).min(b_min);
            let overall_max = r_max.max(g_max).max(b_max);
            r_min = overall_min;
            r_max = overall_max;
            g_min = overall_min;
            g_max = overall_max;
            b_min = overall_min;
            b_max = overall_max;
        }

        let r_range = if r_max - r_min > 0.0 {
            r_max - r_min
        } else {
            1.0
        };
        let g_range = if g_max - g_min > 0.0 {
            g_max - g_min
        } else {
            1.0
        };
        let b_range = if b_max - b_min > 0.0 {
            b_max - b_min
        } else {
            1.0
        };

        let mtf = |x: f32, m: f32| -> f32 {
            if x <= 0.0 {
                return 0.0;
            }
            if x >= 1.0 {
                return 1.0;
            }
            if (m - 0.5).abs() < 1e-5 {
                return x;
            }
            ((m - 1.0) * x) / ((2.0 * m - 1.0) * x - m)
        };

        // Pass 2: stretch and convert to u8 rgba
        let mut rgba = vec![0u8; num_pixels * 4];

        let chunks = float_data.par_chunks_exact(3);
        let out_chunks = rgba.par_chunks_exact_mut(4);

        chunks.zip(out_chunks).for_each(|(pixel, out)| {
            let mut r = (pixel[0] - r_min) / r_range;
            let mut g = (pixel[1] - g_min) / g_range;
            let mut b = (pixel[2] - b_min) / b_range;

            r = mtf(r, stretch_level);
            g = mtf(g, stretch_level);
            b = mtf(b, stretch_level);

            out[0] = (r * 255.0).clamp(0.0, 255.0) as u8;
            out[1] = (g * 255.0).clamp(0.0, 255.0) as u8;
            out[2] = (b * 255.0).clamp(0.0, 255.0) as u8;
            out[3] = 255;
        });

        tauri::ipc::Response::new(rgba)
    })
    .await
    .unwrap()
}

mod app_state;

static URL_PREFIXES: [&str; 4] = [
    "astro-grader://",
    "http://astro-grader.localhost/",
    "https://astro-grader.localhost/",
    "astro-grader://localhost/",
];

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .register_uri_scheme_protocol("astro-grader", |app, request| {
            let raw_uri = request.uri().to_string();
            let mut path = raw_uri;
            for prefix in URL_PREFIXES {
                if let Some(stripped) = path.strip_prefix(prefix) {
                    path = stripped.to_string();
                    break;
                }
            }

            println!("Normalized URI: {}", path);
            let trimmed = path.trim_matches('/');
            println!("Trimmed URI: {}", trimmed);

            if trimmed == "preview" {
                let state: State<AppState> = app.app_handle().state();
                let buffer = state.current_image_data.lock().unwrap().clone();

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
            test3,
            test4_stretch,
            //File Picker Module
            file_picker::file_picker_recursive,
            file_picker::file_picker_convert,
            //Config Module
            config::config_get,
            config::config_set,
            //Fits
            fits::fits_read_image
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
