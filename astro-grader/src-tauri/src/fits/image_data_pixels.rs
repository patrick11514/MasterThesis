use rayon::{
    iter::{IndexedParallelIterator, ParallelIterator},
    slice::ParallelSliceMut,
};
use std::path::PathBuf;
use ts_rs::TS;

use crate::fits::{
    file::{FitsFile, FitsWriteError, ReadImageError},
    utils::{calculate_channel_stats, calculate_stf, debayer_data},
};

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS, PartialEq)]
#[ts(export)]
pub enum ImageDataLayout {
    Grayscale, //Single channel, no bayer pattern
    RGB,       // The pixels are already in RGBRGBRGB... order
    RGBPlanar, // The pixels are in planar format (3 channels in separate planes), needs interleaving
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageOptions {
    //This is bayer pattern of current data representation
    pub bayer_pattern: Option<String>,
    pub scale: f32,
}

impl Default for ImageOptions {
    fn default() -> Self {
        ImageOptions {
            bayer_pattern: None,
            scale: 0.5,
        }
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct BayerPattern {
    pattern: String,
    x_offset: usize,
    y_offset: usize,
}

//Same type we hade in TS
pub type SMH = [f32; 3]; // Shadow, Midtone, Highlight

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct STFPair {
    pub r: SMH,
    pub g: SMH,
    pub b: SMH,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct AutoSFT {
    pub linked: STFPair,
    pub unlinked: STFPair,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageData {
    //this will store currently applied options on the image, so we know, what
    //was currently applied on the image, for example, we will know, if data
    //is already debayered, scaled etc...
    pub applied_options: ImageOptions,
    //this is bayer pattern of original data
    pub original_bayer_pattern: Option<BayerPattern>,
    pub depth: usize,
    pub width: usize,
    pub height: usize,
    pub layout: ImageDataLayout,
    //Precomputed auto-STF for FE
    pub auto_stf: Option<AutoSFT>,
}

#[derive(Debug, Clone)]
pub struct ImageDataPixels {
    pub data: ImageData,
    pub pixels: Vec<f32>,
}

impl ImageDataPixels {
    pub fn from_fits(fits: &mut FitsFile) -> Result<Self, ReadImageError> {
        let data = fits.read_image()?;
        let shape = fits.get_image_shape();
        let bayer_pattern = fits.get_tag_value(crate::fits::tag::Tag::BayerPattern);
        let (x_offset, y_offset) = (
            fits.get_tag_custom::<i32>(crate::fits::tag::Tag::XBayerOffset),
            fits.get_tag_custom::<i32>(crate::fits::tag::Tag::YBayerOffset),
        );

        let bayer_pattern = bayer_pattern.map(|pattern| BayerPattern {
            pattern,
            x_offset: crate::fits::utils::normalize_offset(x_offset),
            y_offset: crate::fits::utils::normalize_offset(y_offset),
        });

        assert!(shape.len() == 2 || shape.len() == 3);

        if shape.len() == 3 && shape[0] == 3 {
            //Assume RGB data, no bayer pattern
            return Ok(ImageDataPixels {
                //Shape is in reverse order
                //shape = [3, 2116, 3804], image_type = Float or shape = [2160, 3840], image_type = UnsignedShort
                data: ImageData {
                    applied_options: ImageOptions {
                        bayer_pattern: None,
                        scale: 1.0,
                    },
                    original_bayer_pattern: bayer_pattern,
                    depth: shape[0],
                    width: shape[2],
                    height: shape[1],
                    layout: ImageDataLayout::RGBPlanar,
                    auto_stf: None,
                },
                pixels: data,
            });
        }

        //Default grayscale image, no bayer pattern
        //Needs debayering then
        Ok(ImageDataPixels {
            data: ImageData {
                applied_options: ImageOptions {
                    bayer_pattern: None,
                    scale: 1.0,
                },
                original_bayer_pattern: bayer_pattern,
                depth: 1,
                width: shape[1],
                height: shape[0],
                layout: ImageDataLayout::Grayscale,
                auto_stf: None,
            },
            pixels: data,
        })
    }

    pub fn save_to_fits(&self, path: PathBuf) -> Result<(), FitsWriteError> {
        let shape = match self.data.layout {
            ImageDataLayout::Grayscale => vec![self.data.height, self.data.width],
            ImageDataLayout::RGBPlanar => vec![3, self.data.height, self.data.width],
            // Master generation should always produce grayscale/RGBPlanar for now.
            ImageDataLayout::RGB => return Err(FitsWriteError::WriteImageFailed),
        };

        // cfitsio's create() fails if the file already exists; delete it first.
        if path.exists() {
            std::fs::remove_file(&path).map_err(|_| FitsWriteError::CreateFailed)?;
        }

        let mut output = FitsFile::create(path, &shape, fitsio::images::ImageType::Float)?;
        output.write_image_f32(&self.pixels)
    }

    // This function normalizes data into two formats:
    // 1. If the data is already in RGBRGB... format (or grayscale - LLLLLL (L = luminance)) we leave them as it is
    // 2. If the data is in planar format (3d array with shape [3, height, width]), we convert it to RGBRGB... format (interleaved)
    pub fn to_rgb_layout(&mut self) {
        if let ImageDataLayout::RGB | ImageDataLayout::Grayscale = self.data.layout {
            // No normalization needed for RGB or grayscale data
            return;
        }

        let width = self.data.width;
        let height = self.data.height;
        let plane_area = width * height;

        let (r_plane, gb_plane) = self.pixels.split_at(plane_area);
        let (g_plane, b_plane) = gb_plane.split_at(plane_area);

        let mut out_data = vec![0.0; self.pixels.len()];
        let new_data = &mut out_data[..];

        new_data
            .par_chunks_exact_mut(3)
            .enumerate()
            .for_each(|(i, chunk)| {
                chunk[0] = r_plane[i];
                chunk[1] = g_plane[i];
                chunk[2] = b_plane[i];
            });

        self.pixels = out_data;
        self.data.layout = ImageDataLayout::RGB;
        self.data.depth = 3;
    }

    pub fn to_js_imagedata(&self) -> Option<Vec<u8>> {
        if let ImageDataLayout::RGBPlanar = self.data.layout {
            return None;
        }

        // safety: we are just reinterpreting the f32 data as u8 which is safe as long as we provide correct length
        let byte_slice: &[u8] = unsafe {
            std::slice::from_raw_parts(self.pixels.as_ptr() as *const u8, self.pixels.len() * 4)
        };

        Some(byte_slice.to_vec())
    }

    pub fn debayer(&mut self, bayer_pattern: Option<String>) -> bool {
        let bayer_pattern = match &self.data.original_bayer_pattern {
            Some(original_pattern) => BayerPattern {
                pattern: bayer_pattern.unwrap_or(original_pattern.pattern.clone()),
                x_offset: original_pattern.x_offset,
                y_offset: original_pattern.y_offset,
            },
            None => {
                if let Some(pattern) = bayer_pattern {
                    BayerPattern {
                        pattern,
                        x_offset: 0,
                        y_offset: 0,
                    }
                } else {
                    return false;
                }
            }
        };

        debayer_data(
            self,
            bayer_pattern.pattern,
            (bayer_pattern.x_offset, bayer_pattern.y_offset),
        );

        true
    }

    pub fn scale(&mut self, scale: f32) {
        // 1. FIX: Use the macro (assert!) and correct the logic
        assert!(
            self.data.layout != ImageDataLayout::RGBPlanar,
            "Scaling is only supported for interleaved RGB or Grayscale format"
        );

        if scale > self.data.applied_options.scale {
            //We can't upscale image...
            return;
        }

        // Use .round() to avoid weird off-by-one pixel dimensions
        let new_width = (self.data.width as f32 * scale).round() as usize;
        let new_height = (self.data.height as f32 * scale).round() as usize;

        // Cache variables to prevent borrowing issues inside the Rayon closure
        let depth = self.data.depth;
        let orig_width = self.data.width;
        let orig_height = self.data.height;
        let orig_pixels = &self.pixels;

        let mut new_pixels = vec![0.0_f32; new_width * new_height * depth];

        // 2. UPGRADE: Parallelize over the new pixel chunks!
        new_pixels
            .par_chunks_exact_mut(depth)
            .enumerate()
            .for_each(|(i, pixel_chunk)| {
                // Reconstruct the X and Y coordinates in the NEW image
                let x = i % new_width;
                let y = i / new_width;

                // 3. FIX: Calculate source coordinates and clamp them using .min()
                // This guarantees we never read out of bounds, even with floating point quirks
                let src_x = ((x as f32 / scale) as usize).min(orig_width - 1);
                let src_y = ((y as f32 / scale) as usize).min(orig_height - 1);

                let src_idx = (src_y * orig_width + src_x) * depth;

                // Copy the channels (works seamlessly for both Grayscale and RGB)
                for c in 0..depth {
                    pixel_chunk[c] = orig_pixels[src_idx + c];
                }
            });

        self.pixels = new_pixels;
        self.data.width = new_width;
        self.data.height = new_height;
        self.data.applied_options.scale = scale;
    }

    pub fn calculate_stf(&mut self) {
        // 1. Extract statistical samples based on memory layout
        let (medians, mads) = match self.data.layout {
            ImageDataLayout::Grayscale => {
                let (med, mad) = calculate_channel_stats(&self.pixels, 0, 100);
                (vec![med], vec![mad]) // 1 Channel
            }
            ImageDataLayout::RGB => {
                let (r_med, r_mad) = calculate_channel_stats(&self.pixels, 0, 300);
                let (g_med, g_mad) = calculate_channel_stats(&self.pixels, 1, 300);
                let (b_med, b_mad) = calculate_channel_stats(&self.pixels, 2, 300);
                (vec![r_med, g_med, b_med], vec![r_mad, g_mad, b_mad]) // 3 Channels
            }
            ImageDataLayout::RGBPlanar => {
                let plane_area = self.data.width * self.data.height;
                let (r_med, r_mad) = calculate_channel_stats(&self.pixels[0..plane_area], 0, 100);
                let (g_med, g_mad) =
                    calculate_channel_stats(&self.pixels[plane_area..plane_area * 2], 0, 100);
                let (b_med, b_mad) =
                    calculate_channel_stats(&self.pixels[plane_area * 2..], 0, 100);
                (vec![r_med, g_med, b_med], vec![r_mad, g_mad, b_mad]) // 3 Channels
            }
        };

        // 2. Compute both linked and unlinked STF profiles
        self.data.auto_stf = Some(AutoSFT {
            linked: calculate_stf(&medians, &mads, true),
            unlinked: calculate_stf(&medians, &mads, false),
        });
    }
}
