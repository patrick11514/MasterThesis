use std::path::PathBuf;
use std::process::Command;
use tauri::Manager;
use ts_rs::TS;

fn default_temp_folder_path() -> String {
    std::env::temp_dir().to_string_lossy().into_owned()
}

#[derive(serde::Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq, Hash, TS, Default)]
#[ts(export)]
pub enum CalibrationStorageMode {
    #[default]
    NextToOriginal,
    TempFolder,
}

#[derive(serde::Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq, Hash, TS)]
#[ts(export)]
enum Type {
    Prefix,
    Suffix,
}

#[derive(serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct NightPrefix {
    text: String,
    #[serde(rename = "type")]
    prefix_type: Type,
    #[serde(default)]
    match_first: bool,
}

fn default_temperature_step() -> f32 {
    1.0
}

fn default_zero_step() -> f32 {
    0.0
}

fn default_false() -> bool {
    false
}

#[derive(serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct Config {
    pub night_prefixes: Vec<NightPrefix>,
    #[serde(default)]
    pub calibration_storage_mode: CalibrationStorageMode,
    #[serde(default = "default_temp_folder_path")]
    pub temp_folder_path: String,
    #[serde(default = "default_temperature_step")]
    pub temperature_step: f32,
    #[serde(default = "default_zero_step")]
    pub exposure_step: f32,
    #[serde(default = "default_zero_step")]
    pub gain_step: f32,
    #[serde(default = "default_false")]
    pub cross_night_reference: bool,
    #[serde(default = "default_zero_step")]
    pub max_fwhm: f32,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            night_prefixes: Vec::new(),
            calibration_storage_mode: CalibrationStorageMode::NextToOriginal,
            temp_folder_path: default_temp_folder_path(),
            temperature_step: default_temperature_step(),
            exposure_step: default_zero_step(),
            gain_step: default_zero_step(),
            cross_night_reference: default_false(),
            max_fwhm: default_zero_step(),
        }
    }
}

#[derive(Debug)]
pub enum ConfigError {
    MissingConfigDirectory,
    CreateDirectoryError(std::io::Error),
    StringifyError(serde_json::Error),
    WriteFileError(std::io::Error),
    ReadFileError(std::io::Error),
    ParseError(serde_json::Error),
    OpenFolderError(std::io::Error),
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::MissingConfigDirectory => write!(f, "Could not find config directory"),
            ConfigError::CreateDirectoryError(e) => {
                write!(f, "Failed to create config directory: {}", e)
            }
            ConfigError::StringifyError(e) => write!(f, "Failed to serialize config: {}", e),
            ConfigError::WriteFileError(e) => write!(f, "Failed to write config file: {}", e),
            ConfigError::ReadFileError(e) => write!(f, "Failed to read config file: {}", e),
            ConfigError::ParseError(e) => write!(f, "Failed to parse config file: {}", e),
            ConfigError::OpenFolderError(e) => {
                write!(f, "Failed to open config folder in file manager: {}", e)
            }
        }
    }
}

fn config_dir_path(app_handle: &tauri::AppHandle) -> Result<PathBuf, ConfigError> {
    app_handle
        .path()
        .app_config_dir()
        .map_err(|_| ConfigError::MissingConfigDirectory)
}

fn config_file_path(app_handle: &tauri::AppHandle) -> Result<PathBuf, ConfigError> {
    Ok(config_dir_path(app_handle)?.join("config.json"))
}

fn open_folder(path: &std::path::Path) -> Result<(), ConfigError> {
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut cmd = Command::new("explorer");
        cmd.arg(path);
        cmd
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut cmd = Command::new("open");
        cmd.arg(path);
        cmd
    };

    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    let mut command = {
        let mut cmd = Command::new("xdg-open");
        cmd.arg(path);
        cmd
    };

    command.spawn().map_err(ConfigError::OpenFolderError)?;
    Ok(())
}

pub async fn write_config(
    app_handle: &tauri::AppHandle,
    config: &Config,
) -> Result<(), ConfigError> {
    let config_path = config_file_path(app_handle)?;

    if let Some(parent) = config_path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(ConfigError::CreateDirectoryError)?;
    }

    let config_json = serde_json::to_string_pretty(config).map_err(ConfigError::StringifyError)?;
    tokio::fs::write(config_path, config_json)
        .await
        .map_err(ConfigError::WriteFileError)?;

    Ok(())
}

pub async fn read_config(app_handle: &tauri::AppHandle) -> Result<Config, ConfigError> {
    let config_path = config_file_path(app_handle)?;

    if !config_path.exists() {
        return Ok(Config::default());
    }

    let config_json = tokio::fs::read_to_string(config_path)
        .await
        .map_err(ConfigError::ReadFileError)?;
    let config: Config = serde_json::from_str(&config_json).map_err(ConfigError::ParseError)?;

    Ok(config)
}

#[tauri::command]
pub async fn config_get(app_handle: tauri::AppHandle) -> Result<Config, String> {
    read_config(&app_handle).await.map_err(|e| format!("{}", e))
}

#[tauri::command]
pub async fn config_set(app_handle: tauri::AppHandle, config: Config) -> Result<(), String> {
    write_config(&app_handle, &config)
        .await
        .map_err(|e| format!("{}", e))
}

#[tauri::command]
pub async fn config_path_get(app_handle: tauri::AppHandle) -> Result<String, String> {
    config_file_path(&app_handle)
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(|e| format!("{}", e))
}

#[tauri::command]
pub async fn config_open_folder(app_handle: tauri::AppHandle) -> Result<(), String> {
    let config_dir = config_dir_path(&app_handle).map_err(|e| format!("{}", e))?;

    tokio::fs::create_dir_all(&config_dir)
        .await
        .map_err(|e| format!("{}", ConfigError::CreateDirectoryError(e)))?;

    open_folder(&config_dir).map_err(|e| format!("{}", e))
}
