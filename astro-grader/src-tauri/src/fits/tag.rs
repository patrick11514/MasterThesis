#[derive(Debug, Clone, Copy)]
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

pub fn get_tag(tag: Tag) -> &'static [&'static str] {
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
