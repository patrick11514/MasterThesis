use std::path::PathBuf;

pub struct FitsFile {
    file: fitsio::FitsFile,
    hdu: fitsio::hdu::FitsHdu,
}

#[derive(Debug)]
pub enum ReadImageError {
    ReadImageFailed,
    UnableToExtractImageSize,
}

impl FitsFile {
    pub fn new(path: PathBuf) -> Result<Self, super::structs::FitsOpenError> {
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

    pub fn get_image_shape(&self) -> Vec<usize> {
        if let fitsio::hdu::HduInfo::ImageInfo { shape, .. } = &self.hdu.info {
            return shape.clone();
        }
        vec![]
    }

    pub fn get_image_type(&self) -> Option<fitsio::images::ImageType> {
        if let fitsio::hdu::HduInfo::ImageInfo { image_type, .. } = &self.hdu.info {
            return Some(*image_type);
        }
        None
    }

    pub fn read_image(&mut self) -> Result<Vec<f32>, ReadImageError> {
        let data = self
            .hdu
            .read_image(&mut self.file)
            .map_err(|_| ReadImageError::ReadImageFailed)?;
        Ok(data)
    }
}
