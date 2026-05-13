#[derive(Debug, Clone, Copy)]
pub enum Tag {
    ImageType,
    BayerPattern,
    ExposureTime,
    Temperature,
    Gain,
    Camera,
    Telescope,
    ObservationDate,
    Filter,
    XBinding,
    YBinding,
    XBayerOffset,
    YBayerOffset,
    NAXIS1,
    NAXIS2,
}

pub fn get_tag(tag: Tag) -> &'static [&'static str] {
    match tag {
        Tag::ImageType => &["IMAGETYP"],
        Tag::BayerPattern => &["BAYERPAT", "COLORTYP"],
        Tag::ExposureTime => &["EXPTIME", "EXPOSURE"],
        Tag::Temperature => &["CCD-TEMP", "SET-TEMP"],
        Tag::Gain => &["GAIN", "EGAIN"],
        Tag::Camera => &["INSTRUME", "CCDNAME", "CAMERA"],
        Tag::Telescope => &["TELESCOP", "FOCALLEN"],
        Tag::ObservationDate => &["DATE-OBS"],
        Tag::Filter => &["FILTER"],
        Tag::XBinding => &["XBINNING"],
        Tag::YBinding => &["YBINNING"],
        Tag::XBayerOffset => &["XBAYROFF"],
        Tag::YBayerOffset => &["YBAYROFF"],
        Tag::NAXIS1 => &["NAXIS1"],
        Tag::NAXIS2 => &["NAXIS2"],
    }
}
