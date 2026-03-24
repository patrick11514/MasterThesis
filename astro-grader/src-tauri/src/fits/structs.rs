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
pub enum FitsOpenError {
    OpenError,
    NoHudFound,
}
