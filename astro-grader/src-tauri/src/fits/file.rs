use std::path::PathBuf;

use crate::{
    app_state::AppState,
    fits::{
        image_data_pixels::{ImageDataPixels, ImageOptions},
        tag::Tag,
        utils::{self, normalize_data},
    },
};

#[derive(Debug)]
pub enum ReadImageError {
    ReadImageFailed,
    UnableToExtractImageSize,
}

pub struct FitsFile {
    file: fitsio::FitsFile,
    hdu: fitsio::hdu::FitsHdu,
}

impl FitsFile {
    pub fn new(path: PathBuf, state: &AppState) -> Result<Self, super::structs::FitsOpenError> {
        let mut file =
            fitsio::FitsFile::open(path).map_err(|_| super::structs::FitsOpenError::OpenError)?;
        let hdu = file
            .primary_hdu()
            .map_err(|_| super::structs::FitsOpenError::NoHudFound)?;

        Ok(FitsFile { file, hdu })
    }

    pub fn get_tag_value(&mut self, tag: super::tag::Tag) -> Option<String> {
        self.get_tag_custom::<String>(tag)
    }

    pub fn get_tag_custom<T>(&mut self, tag: super::tag::Tag) -> Option<T>
    where
        fitsio::headers::HeaderValue<T>: fitsio::headers::ReadsKey,
    {
        let keys = super::tag::get_tag(tag);
        for key in keys {
            if let Ok(value) = self
                .hdu
                .read_key::<fitsio::headers::HeaderValue<T>>(&mut self.file, key)
            {
                return Some(value.value);
            }
        }

        None
    }

    pub fn read_image(
        &mut self,
    ) -> Result<super::image_data_pixels::ImageDataPixels, ReadImageError> {
        let bayer_pat = self.get_tag_value(Tag::BayerPattern);

        let mut data: Vec<f32> = self
            .hdu
            .read_image(&mut self.file)
            .map_err(|_| ReadImageError::ReadImageFailed)?;

        if let fitsio::hdu::HduInfo::ImageInfo { shape, image_type } = &self.hdu.info {
            if let Some(bayer_pattern) = bayer_pat {
                //Normalize data
                normalize_data(&mut data, image_type);

                let image_data = ImageDataPixels::from_fits(shape, data);

                let offset = (
                    super::utils::normalize_offset(self.get_tag_custom::<i32>(Tag::XBayerOffset)),
                    super::utils::normalize_offset(self.get_tag_custom::<i32>(Tag::YBayerOffset)),
                );

                let debayered = utils::debayer_data(image_data, bayer_pattern, offset);
                return Ok(debayered);
            }

            let mut data = ImageDataPixels::from_fits(shape, data);
            data.to_rgb_layout(); //Directly convert to RGB layout if needed, this will modify the data in place and avoid unnecessary copies

            return Ok(data);
        }
        Err(ReadImageError::UnableToExtractImageSize)
    }

    pub fn read_image_options(&mut self, options: ImageOptions) -> Option<ImageDataPixels> {
        None
    }
}
