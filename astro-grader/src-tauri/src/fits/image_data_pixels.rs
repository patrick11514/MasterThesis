use rayon::{
    iter::{IndexedParallelIterator, ParallelIterator},
    slice::ParallelSliceMut,
};
use ts_rs::TS;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageData {
    pub bayer_pattern: Option<String>,
    pub depth: usize,
    pub width: usize,
    pub height: usize,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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
                depth: 1,
            },
            pixels: data,
        }
    }

    pub fn to_js_imagedata(&self) -> Vec<u8> {
        let width = self.data.width;
        let height = self.data.height;
        let plane_area = width * height;

        // If data is already in correct rgbrgb order (or grayscale), process normally
        if self.data.depth == 1 || self.data.bayer_pattern.is_some() {
            let pixels = &self.pixels;
            let mut out_bytes = Vec::with_capacity(pixels.len() * 4);
            for &val in pixels.iter() {
                out_bytes.extend_from_slice(&val.to_le_bytes());
            }
            return out_bytes;
        }

        // Assume RGB planar data (depth == 3) that needs interleaving
        assert_eq!(
            self.data.depth, 3,
            "Planar interleaving currently expects exactly 3 channels (RGB)"
        );

        // 1. Split the massive single slice into three distinct planar slices
        let (r_plane, gb_plane) = self.pixels.split_at(plane_area);
        let (g_plane, b_plane) = gb_plane.split_at(plane_area);

        // 2. Pre-allocate the exact size of the final byte array to avoid resizing
        // (total pixels * 3 channels * 4 bytes per f32)
        let total_bytes = plane_area * 3 * 4;
        let mut out_bytes = vec![0u8; total_bytes];

        // 3. Grab a mutable slice of just the pixel data area
        let pixel_bytes = &mut out_bytes[..];

        // 4. Iterate over the output bytes in chunks of 12 (3 f32s * 4 bytes each)
        pixel_bytes
            .par_chunks_exact_mut(12)
            .enumerate()
            .for_each(|(i, chunk)| {
                // The CPU hardware prefetcher will detect these three independent linear reads
                let r_bytes = r_plane[i].to_le_bytes();
                let g_bytes = g_plane[i].to_le_bytes();
                let b_bytes = b_plane[i].to_le_bytes();

                // Write the little-endian bytes directly into the pre-allocated chunk
                chunk[0..4].copy_from_slice(&r_bytes);
                chunk[4..8].copy_from_slice(&g_bytes);
                chunk[8..12].copy_from_slice(&b_bytes);
            });

        out_bytes
    }
}
