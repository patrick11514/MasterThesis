use std::{borrow::Cow, path::PathBuf};

use ts_rs::TS;

#[derive(serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum FileType {
    Light,
    Dark,
    Flat,
    Bias,
    MasterDark,
    MasterFlat,
    MasterBias,
}

#[derive(Debug)]
pub enum Tag {
    ImageType,
    BayerPattern,
    ExposureTime,
    Temperature,
    Gain,
    ObservationDate,
    Filter,
    XBinding,
    YBinding,
    XBayerOffset,
    YBayerOffset,
}

fn get_tag(tag: Tag) -> &'static [&'static str] {
    match tag {
        Tag::ImageType => &["IMAGETYP"],
        Tag::BayerPattern => &["BAYERPAT", "COLORTYP"],
        Tag::ExposureTime => &["EXPTIME", "EXPOSURE"],
        Tag::Temperature => &["CCD-TEMP", "SET-TEMP"],
        Tag::Gain => &["GAIN", "EGAIN"],
        Tag::ObservationDate => &["DATE-OBS"],
        Tag::Filter => &["FILTER"],
        Tag::XBinding => &["XBINNING"],
        Tag::YBinding => &["YBINNING"],
        Tag::XBayerOffset => &["XBAYROFF"],
        Tag::YBayerOffset => &["YBAYROFF"],
    }
}

pub struct FitsFile {
    file: fitsio::FitsFile,
    hdu: fitsio::hdu::FitsHdu,
}

#[derive(Debug)]
pub enum FitsOpenError {
    OpenError,
    NoHudFound,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageData {
    bayer_pattern: Option<String>,
    depth: usize,
    width: usize,
    height: usize,
    pixels: Vec<f32>,
}

impl ImageData {
    pub fn from_fits(shape: &Vec<usize>, data: Vec<f32>) -> Self {
        assert!(shape.len() == 2 || shape.len() == 3);

        if shape.len() == 3 && shape[0] == 3 {
            //Assume RGB data, no bayer pattern
            return ImageData {
                //Shape is in reverse order
                //shape = [3, 2116, 3804], image_type = Float or shape = [2160, 3840], image_type = UnsignedShort
                width: shape[2],
                height: shape[1],
                depth: shape[0],
                pixels: data,
                bayer_pattern: None,
            };
        }

        //Default grayscale image, no bayer pattern
        //Needs debayering then
        ImageData {
            width: shape[1],
            height: shape[0],
            depth: 1,
            pixels: data,
            bayer_pattern: None,
        }
    }

    pub fn to_js_imagedata(&self) -> Vec<u8> {
        //If shape is > 1, we need to convert to RGB pixels
        //If data is debayered, they are in correct rgbrgb order
        let pixels: Cow<Vec<f32>> = if self.depth == 1 || self.bayer_pattern.is_some() {
            Cow::Borrowed(&self.pixels)
        } else {
            //Assume RGB data, just convert to bytes
            let mut rgb_data = Vec::with_capacity(3 * self.width * self.height);

            for y in 0..self.height {
                for x in 0..self.width {
                    for depth in 0..=self.depth {
                        rgb_data.push(
                            self.pixels[y * self.width + x + depth * self.width * self.height],
                        );
                    }
                }
            }

            Cow::Owned(rgb_data)
        };

        let mut out_bytes = Vec::with_capacity(8 + pixels.len() * 4);
        out_bytes.extend_from_slice(&(self.width as u32).to_le_bytes());
        out_bytes.extend_from_slice(&(self.height as u32).to_le_bytes());
        for &val in pixels.iter() {
            out_bytes.extend_from_slice(&val.to_le_bytes());
        }
        out_bytes
    }
}

fn debayer_data(data: ImageData, bayer_pattern: String, offset: (usize, usize)) -> ImageData {
    assert!(bayer_pattern.len() == 4);
    assert!(bayer_pattern.contains('R'));
    assert!(bayer_pattern.contains('G'));
    assert!(bayer_pattern.contains('B'));

    let new_width = data.width / 2;
    let new_height = data.height / 2;

    let mut rgb_data = Vec::with_capacity(3 * new_width * new_height);

    for y in 0..new_height {
        for x in 0..new_width {
            let mut sum_r = 0.0;
            let mut count_r = 0.0;
            let mut sum_g = 0.0;
            let mut count_g = 0.0;
            let mut sum_b = 0.0;
            let mut count_b = 0.0;

            for dy in 0..4 {
                let oy = y * 4 + dy;
                if oy >= data.height {
                    continue;
                }
                for dx in 0..4 {
                    let ox = x * 4 + dx;
                    if ox >= data.width {
                        continue;
                    }

                    let val = data.pixels[oy * data.width + ox];

                    let is_even_row = (oy + offset.1) % 2 == 0;
                    let is_even_col = (ox + offset.0) % 2 == 0;

                    let color = match (is_even_row, is_even_col) {
                        (true, true) => bayer_pattern.chars().nth(0).unwrap(),
                        (true, false) => bayer_pattern.chars().nth(1).unwrap(),
                        (false, true) => bayer_pattern.chars().nth(2).unwrap(),
                        (false, false) => bayer_pattern.chars().nth(3).unwrap(),
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

            rgb_data.push(r);
            rgb_data.push(g);
            rgb_data.push(b);
        }
    }

    ImageData {
        width: new_width,
        height: new_height,
        pixels: rgb_data,
        depth: 3,
        bayer_pattern: Some(bayer_pattern),
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
struct ReadImageOptions {
    debayer: bool,
    bayer_pattern: Option<String>,
    down_sample_factor: Option<usize>,
}

impl FitsFile {
    pub fn new(path: PathBuf) -> Result<Self, FitsOpenError> {
        let mut file = fitsio::FitsFile::open(path).map_err(|_| FitsOpenError::OpenError)?;
        let hdu = file.primary_hdu().map_err(|_| FitsOpenError::NoHudFound)?;

        Ok(FitsFile { file, hdu })
    }

    pub fn get_tag_value(&mut self, tag: Tag) -> Option<String> {
        let keys = get_tag(tag);
        for key in keys {
            if let Ok(value) = self
                .hdu
                .read_key::<fitsio::headers::HeaderValue<String>>(&mut self.file, key)
            {
                return Some(value.value);
            }
        }

        None
    }

    pub fn read_image(&mut self) -> Option<ImageData> {
        let bayer_pat = self.get_tag_value(Tag::BayerPattern);

        let data: Vec<f32> = self.hdu.read_image(&mut self.file).ok()?;

        if let fitsio::hdu::HduInfo::ImageInfo { shape, .. } = &self.hdu.info {
            return Some(ImageData::from_fits(shape, data));
        }
        None
    }

    pub fn read_image_options(&mut self, options: ReadImageOptions) -> Option<ImageData> {
        None
    }
}

#[tauri::command]
pub async fn fits_read_image(path: PathBuf) -> Result<tauri::ipc::Response, String> {
    let mut fits = FitsFile::new(path).map_err(|_| String::from("IDK"))?;
    let image_data = fits.read_image().ok_or(String::from("test"))?;
    Ok(tauri::ipc::Response::new(image_data.to_js_imagedata()))
}
