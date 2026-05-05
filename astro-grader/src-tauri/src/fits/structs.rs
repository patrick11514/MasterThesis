use ts_rs::TS;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
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

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum FrameState {
    #[default]
    Default,
    Calibrated,
    Accepted,
    Rejected,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct ImageStats {
    pub star_count: Option<u32>,
    pub fwhm: Option<f32>,
    pub hfd: Option<f32>,
    pub eccentricity: Option<f32>,
    pub background_contrast: Option<f32>,
    pub quality_score: Option<f32>,
}

#[derive(Debug)]
pub enum FitsOpenError {
    OpenError,
    NoHudFound,
}
