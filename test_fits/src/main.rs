use std::path::PathBuf;
// no extra collections needed

#[derive(Debug, Clone)]
struct ImageMetrics {
    min: f32,
    max: f32,
    mean: f32,
    std_dev: f32,
    p01: f32,
    p50: f32,
    p99: f32,
    // Median spread across 4x4 tiles, lower means flatter background.
    tile_median_cv: f32,
    // Number of isolated bright outliers above neighborhood threshold.
    hot_pixels: usize,
}

fn main() -> anyhow::Result<()> {
    // Simple CLI: flags: --flat <path> --dark <path> --bias <path>
    let mut flat: Option<PathBuf> = None;
    let mut dark: Option<PathBuf> = None;
    let mut bias: Option<PathBuf> = None;

    let mut lights: Vec<PathBuf> = Vec::new();

    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--flat" => {
                if let Some(p) = it.next() {
                    flat = Some(PathBuf::from(p));
                }
            }
            "--dark" => {
                if let Some(p) = it.next() {
                    dark = Some(PathBuf::from(p));
                }
            }
            "--bias" => {
                if let Some(p) = it.next() {
                    bias = Some(PathBuf::from(p));
                }
            }
            other => lights.push(PathBuf::from(other)),
        }
    }

    if lights.is_empty() {
        lights = glob::glob("*.fit*")?.filter_map(Result::ok).collect();
    }

    // Load masters if provided
    let flat_pixels = match flat {
        Some(ref p) => Some(load_image_pixels(p)?),
        None => None,
    };
    let dark_pixels = match dark {
        Some(ref p) => Some(load_image_pixels(p)?),
        None => None,
    };
    let bias_pixels = match bias {
        Some(ref p) => Some(load_image_pixels(p)?),
        None => None,
    };

    for light_path in lights {
        println!("Processing {:?}", light_path.display());
        let (pixels, shape) = load_image_pixels(&light_path)?;

        // Validate masters dims
        if let Some(ref f) = flat_pixels {
            if f.0.len() != pixels.len() {
                anyhow::bail!("Flat master has different dimensions than light frame");
            }
        }
        if let Some(ref d) = dark_pixels {
            if d.0.len() != pixels.len() {
                anyhow::bail!("Dark master has different dimensions than light frame");
            }
        }
        if let Some(ref b) = bias_pixels {
            if b.0.len() != pixels.len() {
                anyhow::bail!("Bias master has different dimensions than light frame");
            }
        }

        // Variant: flat-only
        let mut v_flat = pixels.clone();
        calibrate_light(
            &mut v_flat,
            None,
            flat_pixels.as_ref().map(|f| f.0.as_slice()),
            None,
        );
        let out_flat =
            light_path.with_file_name(format!("{}_cal_flat.fits", strip_ext(&light_path)));
        save_image(&out_flat, &v_flat, &shape)?;

        // Variant: bias-only
        let mut v_bias = pixels.clone();
        calibrate_light(
            &mut v_bias,
            None,
            None,
            bias_pixels.as_ref().map(|b| b.0.as_slice()),
        );
        let out_bias =
            light_path.with_file_name(format!("{}_cal_bias.fits", strip_ext(&light_path)));
        save_image(&out_bias, &v_bias, &shape)?;

        // Variant: dark-only
        let mut v_dark = pixels.clone();
        calibrate_light(
            &mut v_dark,
            dark_pixels.as_ref().map(|d| d.0.as_slice()),
            None,
            None,
        );
        let out_dark =
            light_path.with_file_name(format!("{}_cal_dark.fits", strip_ext(&light_path)));
        save_image(&out_dark, &v_dark, &shape)?;

        // Variant: full (dark+bias+flat as provided)
        let mut v_full = pixels.clone();
        calibrate_light(
            &mut v_full,
            dark_pixels.as_ref().map(|d| d.0.as_slice()),
            flat_pixels.as_ref().map(|f| f.0.as_slice()),
            bias_pixels.as_ref().map(|b| b.0.as_slice()),
        );
        let out_full =
            light_path.with_file_name(format!("{}_cal_full.fits", strip_ext(&light_path)));
        save_image(&out_full, &v_full, &shape)?;

        // Variant: full calibration + hot-pixel cleanup
        let mut v_full_hotfix = v_full.clone();
        let hotfix_count = remove_hot_pixels(&mut v_full_hotfix, &shape, 6.0, 0.0005);
        let out_full_hotfix =
            light_path.with_file_name(format!("{}_cal_full_hotfix.fits", strip_ext(&light_path)));
        save_image(&out_full_hotfix, &v_full_hotfix, &shape)?;

        let m_raw = compute_metrics(&pixels, &shape);
        let m_flat = compute_metrics(&v_flat, &shape);
        let m_bias = compute_metrics(&v_bias, &shape);
        let m_dark = compute_metrics(&v_dark, &shape);
        let m_full = compute_metrics(&v_full, &shape);
        let m_hotfix = compute_metrics(&v_full_hotfix, &shape);
        print_metrics("RAW", &m_raw);
        print_metrics("FLAT_ONLY", &m_flat);
        print_metrics("BIAS_ONLY", &m_bias);
        print_metrics("DARK_ONLY", &m_dark);
        print_metrics("FULL", &m_full);
        print_metrics("FULL+HOTFIX", &m_hotfix);
        println!("hotfix_replaced_pixels = {}", hotfix_count);

        println!(
            "Wrote: {}, {}, {}, {}, {}",
            out_flat.display(),
            out_bias.display(),
            out_dark.display(),
            out_full.display(),
            out_full_hotfix.display()
        );
    }

    Ok(())
}

fn strip_ext(p: &PathBuf) -> String {
    p.file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "out".to_string())
}

fn load_image_pixels(path: &PathBuf) -> anyhow::Result<(Vec<f32>, Vec<usize>)> {
    let mut file = fitsio::FitsFile::open(path)?;
    let hdu = file.primary_hdu()?;

    if let fitsio::hdu::HduInfo::ImageInfo { shape, .. } = &hdu.info {
        let pixels: Vec<f32> = hdu.read_image(&mut file)?;
        return Ok((pixels, shape.clone()));
    }

    anyhow::bail!("No image HDU found in {}", path.display())
}

fn save_image(path: &PathBuf, pixels: &[f32], shape: &[usize]) -> anyhow::Result<()> {
    if path.exists() {
        std::fs::remove_file(path)?;
    }

    let image_description = fitsio::images::ImageDescription {
        data_type: fitsio::images::ImageType::Float,
        dimensions: shape,
    };
    let mut fits = fitsio::FitsFile::create(path)
        .with_custom_primary(&image_description)
        .open()?;
    let hdu = fits.primary_hdu()?;
    hdu.write_image(&mut fits, pixels)?;
    Ok(())
}

pub fn calibrate_light(
    light: &mut [f32],
    dark: Option<&[f32]>,
    flat: Option<&[f32]>,
    bias: Option<&[f32]>,
) {
    let pixel_count = light.len();

    // 1. Calculate mean of bias-subtracted flat
    let mut flat_mean = 1.0f32;
    if let Some(flat_data) = flat {
        let mut flat_sum: f32 = 0.0;
        for i in 0..pixel_count {
            let bias_val = bias.map(|b| b[i]).unwrap_or(0.0);
            let mut flat_val = flat_data[i] - bias_val;
            if flat_val < 0.0 {
                flat_val = 0.0;
            }
            flat_sum += flat_val;
        }
        flat_mean = flat_sum / (pixel_count as f32);
        if flat_mean == 0.0 {
            flat_mean = 1.0;
        }
    }

    // 2. Apply calibration per-pixel (serial)
    for i in 0..pixel_count {
        let sub_val = if let Some(d) = dark {
            d[i]
        } else if let Some(b) = bias {
            b[i]
        } else {
            0.0
        };

        let mut calibrated = light[i] - sub_val;
        if calibrated < 0.0 {
            calibrated = 0.0;
        }

        if let Some(flat_data) = flat {
            let bias_val = bias.map(|b| b[i]).unwrap_or(0.0);
            let flat_norm = (flat_data[i] - bias_val) / flat_mean;

            if flat_norm > 0.0001 {
                calibrated /= flat_norm;
            } else {
                calibrated = 0.0;
            }
        }

        light[i] = calibrated;
    }
}

fn compute_metrics(pixels: &[f32], shape: &[usize]) -> ImageMetrics {
    let mut sorted = pixels.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let min = sorted.first().copied().unwrap_or(0.0);
    let max = sorted.last().copied().unwrap_or(0.0);
    let mean = if pixels.is_empty() {
        0.0
    } else {
        pixels.iter().copied().sum::<f32>() / pixels.len() as f32
    };
    let variance = if pixels.is_empty() {
        0.0
    } else {
        pixels
            .iter()
            .map(|value| {
                let delta = *value - mean;
                delta * delta
            })
            .sum::<f32>()
            / pixels.len() as f32
    };

    let (width, height, depth) = shape_to_whd(shape);

    let tile_source: &[f32] = if depth <= 1 {
        pixels
    } else {
        let plane = width.saturating_mul(height);
        &pixels[0..plane.min(pixels.len())]
    };

    ImageMetrics {
        min,
        max,
        mean,
        std_dev: variance.sqrt(),
        p01: percentile(&sorted, 0.01),
        p50: percentile(&sorted, 0.50),
        p99: percentile(&sorted, 0.99),
        tile_median_cv: tile_median_cv(tile_source, width, height),
        hot_pixels: count_hot_pixels(pixels, width, height, depth, 6.0, 0.0005),
    }
}

fn print_metrics(label: &str, metrics: &ImageMetrics) {
    println!(
        "{label}: min:{:.6} p01:{:.6} med:{:.6} p99:{:.6} max:{:.6} mean:{:.6} std:{:.6} tile_cv:{:.6} hot:{}",
        metrics.min,
        metrics.p01,
        metrics.p50,
        metrics.p99,
        metrics.max,
        metrics.mean,
        metrics.std_dev,
        metrics.tile_median_cv,
        metrics.hot_pixels
    );
}

fn shape_to_whd(shape: &[usize]) -> (usize, usize, usize) {
    if shape.len() == 2 {
        (shape[1], shape[0], 1)
    } else if shape.len() == 3 {
        // Planar RGB: [3, height, width]
        (shape[2], shape[1], shape[0])
    } else {
        (0, 0, 0)
    }
}

fn tile_median_cv(pixels: &[f32], width: usize, height: usize) -> f32 {
    if width < 8 || height < 8 {
        return 0.0;
    }

    let gx = 4usize;
    let gy = 4usize;
    let tile_w = width / gx;
    let tile_h = height / gy;
    if tile_w == 0 || tile_h == 0 {
        return 0.0;
    }

    let mut medians = Vec::with_capacity(gx * gy);
    for ty in 0..gy {
        for tx in 0..gx {
            let x0 = tx * tile_w;
            let y0 = ty * tile_h;
            let x1 = if tx == gx - 1 {
                width
            } else {
                (tx + 1) * tile_w
            };
            let y1 = if ty == gy - 1 {
                height
            } else {
                (ty + 1) * tile_h
            };

            let mut tile = Vec::with_capacity((x1 - x0) * (y1 - y0));
            for yy in y0..y1 {
                let row = yy * width;
                for xx in x0..x1 {
                    tile.push(pixels[row + xx]);
                }
            }
            tile.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            medians.push(percentile(&tile, 0.50));
        }
    }

    let mean = medians.iter().copied().sum::<f32>() / medians.len() as f32;
    if mean.abs() <= f32::EPSILON {
        return 0.0;
    }
    let var = medians
        .iter()
        .map(|m| {
            let d = *m - mean;
            d * d
        })
        .sum::<f32>()
        / medians.len() as f32;
    var.sqrt() / mean.abs()
}

fn count_hot_pixels(
    pixels: &[f32],
    width: usize,
    height: usize,
    depth: usize,
    sigma_factor: f32,
    abs_floor: f32,
) -> usize {
    if width < 3 || height < 3 || depth == 0 {
        return 0;
    }

    let plane = width.saturating_mul(height);
    let mut count = 0usize;
    for channel in 0..depth {
        let base = channel.saturating_mul(plane);
        for y in 1..(height - 1) {
            for x in 1..(width - 1) {
                let idx = base + y * width + x;
                let center = pixels[idx];

                let mut neighbors = [0.0f32; 8];
                let mut k = 0usize;
                for yy in (y - 1)..=(y + 1) {
                    for xx in (x - 1)..=(x + 1) {
                        if xx == x && yy == y {
                            continue;
                        }
                        neighbors[k] = pixels[base + yy * width + xx];
                        k += 1;
                    }
                }

                neighbors.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                let med = neighbors[neighbors.len() / 2];
                let mad = neighbors.iter().map(|v| (*v - med).abs()).sum::<f32>()
                    / neighbors.len() as f32;
                let threshold = med + sigma_factor * mad.max(1e-12) + abs_floor;

                if center > threshold {
                    count += 1;
                }
            }
        }
    }
    count
}

fn remove_hot_pixels(
    pixels: &mut [f32],
    shape: &[usize],
    sigma_factor: f32,
    abs_floor: f32,
) -> usize {
    let (width, height, depth) = shape_to_whd(shape);
    if width < 3 || height < 3 || depth == 0 {
        return 0;
    }

    let plane = width.saturating_mul(height);
    let source = pixels.to_vec();
    let mut replaced = 0usize;

    for channel in 0..depth {
        let base = channel.saturating_mul(plane);
        for y in 1..(height - 1) {
            for x in 1..(width - 1) {
                let idx = base + y * width + x;
                let center = source[idx];

                let mut neighbors = [0.0f32; 8];
                let mut k = 0usize;
                for yy in (y - 1)..=(y + 1) {
                    for xx in (x - 1)..=(x + 1) {
                        if xx == x && yy == y {
                            continue;
                        }
                        neighbors[k] = source[base + yy * width + xx];
                        k += 1;
                    }
                }

                neighbors.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                let med = neighbors[neighbors.len() / 2];
                let mad = neighbors.iter().map(|v| (*v - med).abs()).sum::<f32>()
                    / neighbors.len() as f32;
                let threshold = med + sigma_factor * mad.max(1e-12) + abs_floor;

                if center > threshold {
                    pixels[idx] = med;
                    replaced += 1;
                }
            }
        }
    }

    replaced
}

fn print_stats(pixels: &[f32]) {
    let mut sorted = pixels.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let min = sorted.first().copied().unwrap_or(0.0);
    let max = sorted.last().copied().unwrap_or(0.0);
    let mean = pixels.iter().copied().sum::<f32>() / pixels.len() as f32;
    let variance = pixels
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta
        })
        .sum::<f32>()
        / pixels.len() as f32;
    let std_dev = variance.sqrt();
    let p01 = percentile(&sorted, 0.01);
    let p50 = percentile(&sorted, 0.50);
    let p99 = percentile(&sorted, 0.99);

    println!(
        "stats = min:{min:.6} p01:{p01:.6} median:{p50:.6} p99:{p99:.6} max:{max:.6} mean:{mean:.6} std:{std_dev:.6}"
    );
}

fn percentile(sorted: &[f32], pct: f32) -> f32 {
    if sorted.is_empty() {
        return 0.0;
    }

    let rank = (pct.clamp(0.0, 1.0) * (sorted.len().saturating_sub(1) as f32)).round() as usize;
    sorted[rank]
}

fn print_min_window(pixels: &[f32], hdu: &fitsio::hdu::FitsHdu) {
    let (width, height) = match &hdu.info {
        fitsio::hdu::HduInfo::ImageInfo { shape, .. } if shape.len() == 2 => (shape[1], shape[0]),
        _ => return,
    };

    if width == 0 || height == 0 || pixels.is_empty() {
        return;
    }

    let (min_idx, min_value) = pixels
        .iter()
        .enumerate()
        .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
        .map(|(idx, value)| (idx, *value))
        .unwrap();

    let x = min_idx % width;
    let y = min_idx / width;
    println!("min_pixel = value:{min_value:.6} at x:{x} y:{y}");

    let x0 = x.saturating_sub(3);
    let y0 = y.saturating_sub(3);
    let x1 = (x + 3).min(width - 1);
    let y1 = (y + 3).min(height - 1);

    for yy in y0..=y1 {
        let mut row = Vec::new();
        for xx in x0..=x1 {
            let idx = yy * width + xx;
            row.push(format!("{:.4}", pixels[idx]));
        }
        println!("row {yy}: {}", row.join(" "));
    }
}
