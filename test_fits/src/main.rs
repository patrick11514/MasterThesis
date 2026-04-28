fn main() -> anyhow::Result<()> {
    let keys = vec![
        "IMAGETYP", "COLORTYP", "EXPTIME", "EXPOSURE", "CCD-TEMP", "SET-TEMP", "GAIN", "EGAIN",
        "DATE-OBS", "FILTER", "XBINNING", "YBINNING", "XBAYROFF", "YBAYROFF", "BAYERPAT",
        "INSTRUME", "TELESCOP",
    ];

    let args: Vec<std::path::PathBuf> = std::env::args()
        .skip(1)
        .map(std::path::PathBuf::from)
        .collect();
    let files: Vec<std::path::PathBuf> = if args.is_empty() {
        glob::glob("*.fit*")?.filter_map(Result::ok).collect()
    } else {
        args
    };

    for file_path in files {
        println!("\nfile = {:?}", file_path.display());
        let mut file = fitsio::FitsFile::open(&file_path)?;
        let hdu = file.primary_hdu()?;

        if let fitsio::hdu::HduInfo::ImageInfo { shape, image_type } = &hdu.info {
            println!("shape = {:?}, image_type = {:?}", shape, image_type);
        }

        for key in &keys {
            if let Ok(value) = hdu.read_key::<fitsio::headers::HeaderValue<String>>(&mut file, key)
            {
                println!("{} = {:?}", key, value.value);
            } else {
                println!("{} = None", key);
            }
        }

        let pixels: Vec<f32> = hdu.read_image(&mut file)?;
        print_stats(&pixels);
        print_min_window(&pixels, &hdu);
    }

    Ok(())
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
