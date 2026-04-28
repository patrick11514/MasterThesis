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

#[derive(Debug)]
pub enum FitsWriteError {
    CreateFailed,
    OpenForEditFailed,
    OpenPrimaryHduFailed,
    WriteImageFailed,
    WriteHeaderFailed,
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

    pub fn create(
        path: PathBuf,
        shape: &[usize],
        image_type: fitsio::images::ImageType,
    ) -> Result<Self, FitsWriteError> {
        let image_description = fitsio::images::ImageDescription {
            data_type: image_type,
            dimensions: shape,
        };

        let mut file = fitsio::FitsFile::create(path)
            .with_custom_primary(&image_description)
            .open()
            .map_err(|_| FitsWriteError::CreateFailed)?;

        let hdu = file
            .primary_hdu()
            .map_err(|_| FitsWriteError::OpenPrimaryHduFailed)?;

        Ok(FitsFile { file, hdu })
    }

    pub fn edit(path: PathBuf) -> Result<Self, FitsWriteError> {
        let mut file =
            fitsio::FitsFile::edit(path).map_err(|_| FitsWriteError::OpenForEditFailed)?;
        let hdu = file
            .primary_hdu()
            .map_err(|_| FitsWriteError::OpenPrimaryHduFailed)?;

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

    pub fn write_image_f32(&mut self, data: &[f32]) -> Result<(), FitsWriteError> {
        self.hdu
            .write_image(&mut self.file, data)
            .map_err(|_| FitsWriteError::WriteImageFailed)?;

        Ok(())
    }

    pub fn write_key_string(&mut self, key: &str, value: &str) -> Result<(), FitsWriteError> {
        self.hdu
            .write_key(&mut self.file, key, value)
            .map_err(|_| FitsWriteError::WriteHeaderFailed)?;

        Ok(())
    }

    pub fn write_key_f32(&mut self, key: &str, value: f32) -> Result<(), FitsWriteError> {
        self.hdu
            .write_key(&mut self.file, key, value)
            .map_err(|_| FitsWriteError::WriteHeaderFailed)?;

        Ok(())
    }

    pub fn write_key_i32(&mut self, key: &str, value: i32) -> Result<(), FitsWriteError> {
        self.hdu
            .write_key(&mut self.file, key, value)
            .map_err(|_| FitsWriteError::WriteHeaderFailed)?;

        Ok(())
    }
}
