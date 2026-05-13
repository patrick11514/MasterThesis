use std::path::PathBuf;

use astro_grader_lib::fits::{FitsFile, ImageDataPixels};
use astro_grader_lib::processing::{metrics, scoring};

fn classify_final(score: f32, fwhm: Option<f32>, max_fwhm: f32, is_trail: bool) -> &'static str {
    let f = fwhm.unwrap_or(f32::INFINITY);
    if is_trail || (score < 0.0 && f > max_fwhm) {
        "Rejected"
    } else {
        "Accepted"
    }
}

fn main() {
    let dir = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "../test_fits/playground".to_string());
    let max_fwhm: f32 = std::env::args()
        .nth(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(8.0);

    let path = PathBuf::from(dir);
    if !path.exists() {
        eprintln!("Path {:?} does not exist", path);
        std::process::exit(1);
    }

    println!(
        "path,star_count,fwhm,hfd,eccentricity,background_contrast,quality_score,is_trail,final_state"
    );

    let mut entries: Vec<_> = std::fs::read_dir(&path)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.path()
                .extension()
                .map(|ext| ext.to_string_lossy().to_lowercase() == "fits")
                .unwrap_or(false)
        })
        .collect();

    entries.sort_by_key(|e| e.path());

    for entry in entries {
        let p = entry.path();
        let display = p.to_string_lossy().to_string();
        match FitsFile::new(p.clone()) {
            Ok(mut fits) => match ImageDataPixels::from_fits(&mut fits) {
                Ok(image) => match metrics::extract_metrics_from_pixels(
                    &image.pixels,
                    image.data.width,
                    image.data.height,
                ) {
                    Ok(mut stats) => {
                        let (score, is_trail) = scoring::compute_score(&stats);
                        stats.quality_score = Some(score);
                        let mut final_state = metrics::classify_frame(score, &stats, max_fwhm);
                        if is_trail {
                            final_state = astro_grader_lib::fits::FrameState::Rejected;
                        }

                        let final_state_str = match final_state {
                            astro_grader_lib::fits::FrameState::Accepted => "Accepted",
                            astro_grader_lib::fits::FrameState::Rejected => "Rejected",
                            _ => "Other",
                        };

                        println!(
                            "{},{},{:?},{:?},{:?},{:?},{:.4},{},{}",
                            display,
                            stats.star_count.unwrap_or(0),
                            stats.fwhm,
                            stats.hfd,
                            stats.eccentricity,
                            stats.background_contrast,
                            stats.quality_score.unwrap_or(0.0),
                            is_trail,
                            final_state_str
                        );
                    }
                    Err(e) => eprintln!("Failed extract metrics {}: {:?}", display, e),
                },
                Err(e) => eprintln!("Failed read image {}: {:?}", display, e),
            },
            Err(e) => eprintln!("Failed open {}: {:?}", display, e),
        }
    }
}
