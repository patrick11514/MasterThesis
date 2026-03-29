use std::thread::current;

use rayon::{
    iter::{IndexedParallelIterator, ParallelIterator},
    slice::ParallelSliceMut,
};
use ts_rs::TS;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum ImageDataLayout {
    Grayscale, //Single channel, no bayer pattern
    RGB,       // The pixels are already in RGBRGBRGB... order
    RGBPlanar, // The pixels are in planar format (3 channels in separate planes), needs interleaving
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageData {
    pub bayer_pattern: Option<String>,
    pub depth: usize,
    pub width: usize,
    pub height: usize,
    pub layout: ImageDataLayout,
}

#[derive(Debug, Clone)]
pub struct ImageDataPixels {
    pub data: ImageData,
    pub pixels: Vec<f32>,
}

impl ImageDataPixels {
    pub fn from_fits(shape: &Vec<usize>, data: Vec<f32>) -> Self {
        assert!(shape.len() == 2 || shape.len() == 3);

        if shape.len() == 3 && shape[0] == 3 {
            //Assume RGB data, no bayer pattern
            return ImageDataPixels {
                //Shape is in reverse order
                //shape = [3, 2116, 3804], image_type = Float or shape = [2160, 3840], image_type = UnsignedShort
                data: ImageData {
                    bayer_pattern: None,
                    depth: shape[0],
                    width: shape[2],
                    height: shape[1],
                    layout: ImageDataLayout::RGBPlanar,
                },
                pixels: data,
            };
        }

        //Default grayscale image, no bayer pattern
        //Needs debayering then
        ImageDataPixels {
            data: ImageData {
                bayer_pattern: None,
                width: shape[1],
                height: shape[0],
                depth: 1, // Grayscale or debayered data is always single channel (depth = 1)
                layout: ImageDataLayout::Grayscale,
            },
            pixels: data,
        }
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
}
