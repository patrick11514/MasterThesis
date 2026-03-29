use rayon::iter::{IntoParallelRefMutIterator, ParallelIterator};

use crate::fits::image_data_pixels::ImageDataLayout;

pub fn normalize_offset(offset: Option<i32>) -> usize {
    let offset = offset.unwrap_or(0);

    if offset < 0 {
        (offset + 2) as usize
    } else {
        offset as usize
    }
}

pub fn debayer_data(
    data: super::image_data_pixels::ImageDataPixels,
    bayer_pattern: String,
    offset: (usize, usize),
) -> super::image_data_pixels::ImageDataPixels {
    assert!(bayer_pattern.len() == 4);
    assert!(bayer_pattern.contains('R'));
    assert!(bayer_pattern.contains('G'));
    assert!(bayer_pattern.contains('B'));

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

    super::image_data_pixels::ImageDataPixels {
        data: super::image_data_pixels::ImageData {
            bayer_pattern: Some(bayer_pattern),
            width: new_width,
            height: new_height,
            depth: 3,
            layout: ImageDataLayout::RGB,
        },
        pixels: rgb_data,
    }
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
