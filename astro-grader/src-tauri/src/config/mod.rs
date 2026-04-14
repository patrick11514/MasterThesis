use tauri::Manager;
use ts_rs::TS;

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

#[derive(serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub struct Config {
    pub night_prefixes: Vec<NightPrefix>,
    #[serde(default = "default_temperature_step")]
    pub temperature_step: f32,
    #[serde(default = "default_zero_step")]
    pub exposure_step: f32,
    #[serde(default = "default_zero_step")]
    pub gain_step: f32,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            night_prefixes: Vec::new(),
            temperature_step: default_temperature_step(),
            exposure_step: default_zero_step(),
            gain_step: default_zero_step(),
        }
    }
}

#[derive(Debug)]
pub enum ConfigError {
    CreateDirectoryError(std::io::Error),
    StringifyError(serde_json::Error),
    WriteFileError(std::io::Error),
    ReadFileError(std::io::Error),
    ParseError(serde_json::Error),
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::CreateDirectoryError(e) => {
                write!(f, "Failed to create config directory: {}", e)
            }
            ConfigError::StringifyError(e) => write!(f, "Failed to serialize config: {}", e),
            ConfigError::WriteFileError(e) => write!(f, "Failed to write config file: {}", e),
            ConfigError::ReadFileError(e) => write!(f, "Failed to read config file: {}", e),
            ConfigError::ParseError(e) => write!(f, "Failed to parse config file: {}", e),
        }
    }
}

pub async fn write_config(
    app_handle: &tauri::AppHandle,
    config: &Config,
) -> Result<(), ConfigError> {
    let config_path = app_handle
        .path()
        .app_config_dir()
        .expect("Could not find config directory")
        .join("config.json");

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
    let config_path = app_handle
        .path()
        .app_config_dir()
        .expect("Could not find config directory")
        .join("config.json");

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
