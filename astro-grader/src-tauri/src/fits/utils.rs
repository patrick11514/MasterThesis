use rayon::iter::{IntoParallelRefMutIterator, ParallelIterator};

use crate::fits::image_data_pixels::{ImageDataLayout, SMH, STFPair};

pub fn normalize_offset(offset: Option<i32>) -> usize {
    let offset = offset.unwrap_or(0);

    if offset < 0 {
        (offset + 2) as usize
    } else {
        offset as usize
    }
}

pub fn debayer_data(
    data: &mut super::image_data_pixels::ImageDataPixels,
    bayer_pattern: String,
    offset: (usize, usize),
) -> bool {
    let pattern_upper = bayer_pattern.to_ascii_uppercase();
    if pattern_upper.len() != 4
        || !pattern_upper.contains('R')
        || !pattern_upper.contains('G')
        || !pattern_upper.contains('B')
    {
        return false;
    }

    let new_width = data.data.width / 2;
    let new_height = data.data.height / 2;

    // 1. Array optimization (Zero-cost stack copy)
    let mut bayer_chars = [' '; 4];
    for (i, c) in bayer_pattern.chars().enumerate().take(4) {
        bayer_chars[i] = c;
    }

    // 2. Extract dimensions so they are `Copy`
    let orig_width = data.data.width;
    let orig_height = data.data.height;

    // 3. Take a slice reference of the pixels.
    // The reference itself is `Copy`, so it can be moved into the closures safely.
    let pixels_ref = data.pixels.as_slice();

    use rayon::prelude::*;

    let rgb_data: Vec<f32> = (0..new_height)
        .into_par_iter()
        .flat_map_iter(|y| {
            (0..new_width).flat_map(move |x| {
                let mut sum_r = 0.0;
                let mut count_r = 0.0;
                let mut sum_g = 0.0;
                let mut count_g = 0.0;
                let mut sum_b = 0.0;
                let mut count_b = 0.0;

                for dy in 0..2 {
                    let oy = y * 2 + dy;
                    if oy >= orig_height {
                        continue;
                    }

                    for dx in 0..2 {
                        let ox = x * 2 + dx;
                        if ox >= orig_width {
                            continue;
                        }

                        // Use the slice reference here
                        let val = pixels_ref[oy * orig_width + ox];

                        // Bitwise optimization: `& 1` is significantly faster than `% 2`
                        let is_even_row = (oy + offset.1) & 1 == 0;
                        let is_even_col = (ox + offset.0) & 1 == 0;

                        let color = match (is_even_row, is_even_col) {
                            (true, true) => bayer_chars[0],
                            (true, false) => bayer_chars[1],
                            (false, true) => bayer_chars[2],
                            (false, false) => bayer_chars[3],
                        };

                        match color {
                            'R' => {
                                sum_r += val;
                                count_r += 1.0;
                            }
                            'G' => {
                                sum_g += val;
                                count_g += 1.0;
                            }
                            'B' => {
                                sum_b += val;
                                count_b += 1.0;
                            }
                            _ => {}
                        }
                    }
                }

                let r = if count_r > 0.0 { sum_r / count_r } else { 0.0 };
                let g = if count_g > 0.0 { sum_g / count_g } else { 0.0 };
                let b = if count_b > 0.0 { sum_b / count_b } else { 0.0 };

                [r, g, b]
            })
        })
        .collect();

    data.pixels = rgb_data;
    data.data.width = new_width;
    data.data.height = new_height;
    data.data.depth = 3;
    data.data.layout = ImageDataLayout::RGB;
    data.data.applied_options.bayer_pattern = Some(bayer_pattern);
    data.data.applied_options.scale = 1.0;
    true
}

pub fn normalize_data(data: &mut Vec<f32>, format: &fitsio::images::ImageType) {
    data.par_iter_mut().for_each(|pixel| {
        *pixel = *pixel
            / match format {
                fitsio::images::ImageType::UnsignedByte => 255.0,
                fitsio::images::ImageType::Byte => 127.0,

                fitsio::images::ImageType::UnsignedShort => 65535.0,
                fitsio::images::ImageType::Short => 32767.0,

                fitsio::images::ImageType::UnsignedLong => 4294967295.0,
                fitsio::images::ImageType::Long => 2147483647.0,

                fitsio::images::ImageType::LongLong => 9223372036854775800.0,

                fitsio::images::ImageType::Float => 1.0,
                fitsio::images::ImageType::Double => 1.0,
            }
    });
}

// Yoinked from official code :) https://pixinsight.com/forum/index.php?threads/programmatic-way-to-do-an-stf-autostretch.6659/
pub fn calculate_channel_stats(data: &[f32], offset: usize, stride: usize) -> (f32, f32) {
    let mut sample: Vec<f32> = data.iter().skip(offset).step_by(stride).copied().collect();

    if sample.is_empty() {
        return (0.0, 0.0);
    }

    let mid = sample.len() / 2;
    let (_, &mut median, _) = sample.select_nth_unstable_by(mid, |a, b| a.partial_cmp(b).unwrap());

    let mut deviations: Vec<f32> = sample.iter().map(|&v| (v - median).abs()).collect();
    let (_, &mut mad, _) = deviations.select_nth_unstable_by(mid, |a, b| a.partial_cmp(b).unwrap());

    (median, mad)
}

fn mtf(target: f32, x: f32) -> f32 {
    if x == 0.0 {
        return 0.0;
    }
    if x == 1.0 {
        return 1.0;
    }
    ((target - 1.0) * x) / (((2.0 * target - 1.0) * x) - target)
}

pub fn calculate_stf(medians: &[f32], mads: &[f32], rgb_linked: bool) -> STFPair {
    let n = medians.len();
    let shadows_clipping = -2.80;
    let target_background = 0.25;

    let scaled_mads: Vec<f32> = mads.iter().map(|&mad| mad * 1.4826).collect();
    let mut channels: Vec<SMH> = vec![[0.0, 0.5, 1.0]; n];

    if rgb_linked && n == 3 {
        let mut inverted_channels = 0;
        for c in 0..n {
            if medians[c] > 0.5 {
                inverted_channels += 1;
            }
        }

        if inverted_channels < n {
            let mut c0 = 0.0;
            let mut m_avg = 0.0;

            for c in 0..n {
                if 1.0 + scaled_mads[c] != 1.0 {
                    c0 += medians[c] + shadows_clipping * scaled_mads[c];
                }
                m_avg += medians[c];
            }

            c0 = (c0 / n as f32).clamp(0.0, 1.0);
            let m = mtf(target_background, (m_avg / n as f32) - c0);

            for c in 0..n {
                channels[c] = [c0, m, 1.0];
            }
        } else {
            let mut c1 = 0.0;
            let mut m_avg = 0.0;

            for c in 0..n {
                m_avg += medians[c];
                if 1.0 + scaled_mads[c] != 1.0 {
                    c1 += medians[c] - shadows_clipping * scaled_mads[c];
                } else {
                    c1 += 1.0;
                }
            }

            c1 = (c1 / n as f32).clamp(0.0, 1.0);
            let m = mtf(c1 - (m_avg / n as f32), target_background);

            for c in 0..n {
                channels[c] = [0.0, m, c1];
            }
        }
    } else {
        for c in 0..n {
            if medians[c] < 0.5 {
                let c0 = if 1.0 + scaled_mads[c] != 1.0 {
                    (medians[c] + shadows_clipping * scaled_mads[c]).clamp(0.0, 1.0)
                } else {
                    0.0
                };
                let m = mtf(target_background, medians[c] - c0);
                channels[c] = [c0, m, 1.0];
            } else {
                let c1 = if 1.0 + scaled_mads[c] != 1.0 {
                    (medians[c] - shadows_clipping * scaled_mads[c]).clamp(0.0, 1.0)
                } else {
                    1.0
                };
                let m = mtf(c1 - medians[c], target_background);
                channels[c] = [0.0, m, c1];
            }
        }
    }

    // Map computed channels to STFPair. For Grayscale (n=1), duplicate the profile across RGB.
    STFPair {
        r: channels[0].clone(),
        g: if n == 3 {
            channels[1].clone()
        } else {
            channels[0].clone()
        },
        b: if n == 3 {
            channels[2].clone()
        } else {
            channels[0].clone()
        },
    }
}
