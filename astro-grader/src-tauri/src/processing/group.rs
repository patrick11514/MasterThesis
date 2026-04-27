use std::collections::HashMap;

use crate::{
    file_picker::File,
    fits::{FileType, FitsFile, Tag},
    state::GroupFramesProgress,
    state::fe_state::{AstroSession, SessionFingerprint},
};

#[derive(Debug, Clone)]
struct FrameMetadata {
    source_night: String,
    camera: Option<String>,
    filter: Option<String>,
    telescope: Option<String>,
    exposure: Option<f32>,
    gain: Option<f32>,
    temperature: Option<f32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionKind {
    Light,
    Dark,
    Flat,
    Bias,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FileKind {
    Light,
    Calibration { kind: SessionKind, is_master: bool },
}

#[derive(Debug, Clone)]
struct SessionMatchData {
    source_night: String,
    camera: Option<String>,
    filter: Option<String>,
    telescope: Option<String>,
    exposure: Option<f32>,
    gain: Option<f32>,
    temperature: Option<f32>,
}

#[derive(Debug, Clone)]
struct SessionBucket {
    key: String,
    fingerprint: SessionFingerprint,
    match_data: SessionMatchData,
    lights: Vec<File>,
    master_dark: Option<File>,
    darks: Vec<File>,
    master_flat: Option<File>,
    flats: Vec<File>,
    master_bias: Option<File>,
    biases: Vec<File>,
}

impl SessionBucket {
    fn new(key: String, fingerprint: SessionFingerprint, match_data: SessionMatchData) -> Self {
        Self {
            key,
            fingerprint,
            match_data,
            lights: Vec::new(),
            master_dark: None,
            darks: Vec::new(),
            master_flat: None,
            flats: Vec::new(),
            master_bias: None,
            biases: Vec::new(),
        }
    }

    fn has_master(&self, kind: SessionKind) -> bool {
        match kind {
            SessionKind::Light => false,
            SessionKind::Dark => self.master_dark.is_some(),
            SessionKind::Flat => self.master_flat.is_some(),
            SessionKind::Bias => self.master_bias.is_some(),
        }
    }

    fn push(&mut self, kind: SessionKind, is_master: bool, file: File) {
        match kind {
            SessionKind::Light => self.lights.push(file),
            SessionKind::Dark => {
                if is_master {
                    self.master_dark = Some(file);
                } else {
                    self.darks.push(file);
                }
            }
            SessionKind::Flat => {
                if is_master {
                    self.master_flat = Some(file);
                } else {
                    self.flats.push(file);
                }
            }
            SessionKind::Bias => {
                if is_master {
                    self.master_bias = Some(file);
                } else {
                    self.biases.push(file);
                }
            }
        }
    }

    fn into_session(self) -> AstroSession {
        use crate::state::fe_state::MasterOrFrames;

        AstroSession {
            uuid: self.key,
            fingerprint: self.fingerprint,
            lights: self.lights,
            darks: if let Some(master) = self.master_dark {
                MasterOrFrames::Master(master)
            } else {
                MasterOrFrames::Frames(self.darks)
            },
            flats: if let Some(master) = self.master_flat {
                MasterOrFrames::Master(master)
            } else {
                MasterOrFrames::Frames(self.flats)
            },
            biases: if let Some(master) = self.master_bias {
                MasterOrFrames::Master(master)
            } else {
                MasterOrFrames::Frames(self.biases)
            },
        }
    }
}

fn format_optional_text(value: Option<&str>) -> String {
    value.unwrap_or_default().trim().to_lowercase()
}

fn format_optional_float(value: Option<f32>) -> String {
    value.map(|value| format!("{value:.3}")).unwrap_or_default()
}

fn approx_equal(left: f32, right: f32) -> bool {
    (left - right).abs() <= 0.01
}

fn round_to_step(value: Option<f32>, step: f32) -> Option<f32> {
    let value = value?;

    if step <= 0.0 {
        return Some(value);
    }

    Some((value / step).round() * step)
}

fn normalize_file_type(file_type: &FileType) -> FileKind {
    match file_type {
        FileType::Light => FileKind::Light,
        FileType::Dark => FileKind::Calibration {
            kind: SessionKind::Dark,
            is_master: false,
        },
        FileType::MasterDark => FileKind::Calibration {
            kind: SessionKind::Dark,
            is_master: true,
        },
        FileType::Flat => FileKind::Calibration {
            kind: SessionKind::Flat,
            is_master: false,
        },
        FileType::MasterFlat => FileKind::Calibration {
            kind: SessionKind::Flat,
            is_master: true,
        },
        FileType::Bias => FileKind::Calibration {
            kind: SessionKind::Bias,
            is_master: false,
        },
        FileType::MasterBias => FileKind::Calibration {
            kind: SessionKind::Bias,
            is_master: true,
        },
    }
}

fn read_optional_float(fits: &mut FitsFile, tag: Tag) -> Option<f32> {
    fits.get_tag_custom::<f32>(tag)
        .or_else(|| fits.get_tag_custom::<f64>(tag).map(|value| value as f32))
        .or_else(|| {
            fits.get_tag_value(tag)
                .and_then(|value| value.parse::<f32>().ok())
        })
}

fn read_frame_metadata(file: &File, source_night: &str) -> Option<FrameMetadata> {
    let mut fits = FitsFile::new(file.path().clone()).ok()?;

    Some(FrameMetadata {
        source_night: source_night.to_string(),
        camera: fits
            .get_tag_value(Tag::Camera)
            .map(|value| value.trim().to_lowercase())
            .filter(|value| !value.is_empty()),
        filter: fits
            .get_tag_value(Tag::Filter)
            .map(|value| value.trim().to_lowercase())
            .filter(|value| !value.is_empty()),
        telescope: fits
            .get_tag_value(Tag::Telescope)
            .map(|value| value.trim().to_lowercase())
            .filter(|value| !value.is_empty()),
        exposure: read_optional_float(&mut fits, Tag::ExposureTime),
        gain: read_optional_float(&mut fits, Tag::Gain),
        temperature: read_optional_float(&mut fits, Tag::Temperature),
    })
}

fn light_session_key(metadata: &FrameMetadata) -> String {
    format!(
        "light:{}:{}:{}:{}:{}:{}:{}",
        metadata.source_night,
        format_optional_text(metadata.camera.as_deref()),
        format_optional_text(metadata.filter.as_deref()),
        format_optional_text(metadata.telescope.as_deref()),
        format_optional_float(metadata.exposure),
        format_optional_float(metadata.gain),
        format_optional_float(metadata.temperature)
    )
}

fn calibration_session_key(kind: SessionKind, metadata: &FrameMetadata) -> String {
    let kind_prefix = match kind {
        SessionKind::Light => "light",
        SessionKind::Dark => "dark",
        SessionKind::Flat => "flat",
        SessionKind::Bias => "bias",
    };

    format!(
        "{kind_prefix}:{}:{}:{}:{}:{}:{}:{}",
        metadata.source_night,
        format_optional_text(metadata.camera.as_deref()),
        format_optional_text(metadata.filter.as_deref()),
        format_optional_text(metadata.telescope.as_deref()),
        format_optional_float(metadata.exposure),
        format_optional_float(metadata.gain),
        format_optional_float(metadata.temperature)
    )
}

fn master_calibration_session_key(kind: SessionKind, metadata: &FrameMetadata) -> String {
    let kind_prefix = match kind {
        SessionKind::Light => "light",
        SessionKind::Dark => "master-dark",
        SessionKind::Flat => "master-flat",
        SessionKind::Bias => "master-bias",
    };

    format!(
        "{kind_prefix}:{}:{}:{}:{}:{}",
        metadata.source_night,
        format_optional_text(metadata.camera.as_deref()),
        format_optional_text(metadata.filter.as_deref()),
        format_optional_text(metadata.telescope.as_deref()),
        format_optional_float(metadata.exposure)
    )
}

fn create_session_fingerprint(metadata: &FrameMetadata) -> SessionFingerprint {
    SessionFingerprint {
        name: metadata.source_night.clone(),
        camera: metadata.camera.clone().unwrap_or_default(),
        filter: metadata.filter.clone().unwrap_or_default(),
        exposure: metadata.exposure.unwrap_or_default(),
        gain: metadata.gain.unwrap_or_default(),
        temperature: metadata.temperature.unwrap_or_default(),
    }
}

fn create_session_match_data(metadata: &FrameMetadata) -> SessionMatchData {
    SessionMatchData {
        source_night: metadata.source_night.clone(),
        camera: metadata.camera.clone(),
        filter: metadata.filter.clone(),
        telescope: metadata.telescope.clone(),
        exposure: metadata.exposure,
        gain: metadata.gain,
        temperature: metadata.temperature,
    }
}

fn matches_optional_text(session_value: Option<&str>, metadata_value: Option<&str>) -> bool {
    metadata_value.is_none_or(|value| session_value == Some(value))
}

fn matches_optional_float(session_value: Option<f32>, metadata_value: Option<f32>) -> bool {
    metadata_value
        .is_none_or(|value| session_value.is_some_and(|session| approx_equal(session, value)))
}

fn master_calibration_matches_session(
    kind: SessionKind,
    session: &SessionMatchData,
    metadata: &FrameMetadata,
) -> bool {
    matches_optional_text(session.camera.as_deref(), metadata.camera.as_deref())
        && matches_optional_text(session.telescope.as_deref(), metadata.telescope.as_deref())
        && matches_optional_float(session.exposure, metadata.exposure)
        && match kind {
            SessionKind::Flat => {
                matches_optional_text(session.filter.as_deref(), metadata.filter.as_deref())
            }
            SessionKind::Light | SessionKind::Dark | SessionKind::Bias => true,
        }
}

fn calibration_matches_session(
    kind: SessionKind,
    session: &SessionMatchData,
    metadata: &FrameMetadata,
) -> bool {
    match kind {
        SessionKind::Light => {
            matches_optional_text(session.camera.as_deref(), metadata.camera.as_deref())
                && matches_optional_text(session.filter.as_deref(), metadata.filter.as_deref())
                && matches_optional_float(session.exposure, metadata.exposure)
                && matches_optional_float(session.gain, metadata.gain)
                && matches_optional_float(session.temperature, metadata.temperature)
        }
        SessionKind::Dark => {
            matches_optional_text(session.camera.as_deref(), metadata.camera.as_deref())
                && matches_optional_float(session.exposure, metadata.exposure)
                && matches_optional_float(session.gain, metadata.gain)
                && matches_optional_float(session.temperature, metadata.temperature)
        }
        SessionKind::Flat => {
            matches_optional_text(session.camera.as_deref(), metadata.camera.as_deref())
                && matches_optional_text(session.filter.as_deref(), metadata.filter.as_deref())
                && matches_optional_float(session.gain, metadata.gain)
        }
        SessionKind::Bias => {
            matches_optional_text(session.camera.as_deref(), metadata.camera.as_deref())
                && matches_optional_float(session.gain, metadata.gain)
        }
    }
}

fn bucket_has_master_match(
    bucket: &SessionBucket,
    kind: SessionKind,
    metadata: &FrameMetadata,
) -> bool {
    bucket.has_master(kind)
        && master_calibration_matches_session(kind, &bucket.match_data, metadata)
}

fn insert_calibration_file(
    light_sessions: &mut HashMap<String, SessionBucket>,
    kind: SessionKind,
    is_master: bool,
    metadata: FrameMetadata,
    file: File,
) {
    if !is_master
        && light_sessions
            .values()
            .any(|bucket| bucket_has_master_match(bucket, kind, &metadata))
    {
        return;
    }

    let mut matched_any = false;

    for bucket in light_sessions.values_mut() {
        if !is_master
            && kind == SessionKind::Flat
            && bucket.match_data.source_night != metadata.source_night
        {
            continue;
        }

        let matches = if is_master {
            master_calibration_matches_session(kind, &bucket.match_data, &metadata)
        } else {
            calibration_matches_session(kind, &bucket.match_data, &metadata)
        };

        if matches {
            bucket.push(kind, is_master, file.clone());
            matched_any = true;
        }
    }

    if matched_any {
        return;
    }

    let key = if is_master {
        master_calibration_session_key(kind, &metadata)
    } else {
        calibration_session_key(kind, &metadata)
    };

    let bucket = light_sessions.entry(key.clone()).or_insert_with(|| {
        SessionBucket::new(
            key,
            create_session_fingerprint(&metadata),
            create_session_match_data(&metadata),
        )
    });

    bucket.push(kind, is_master, file);
}

pub fn group_preview_nights(
    preview_nights: HashMap<String, Vec<File>>,
    channel: tauri::ipc::Channel<GroupFramesProgress>,
    temperature_step: f32,
    exposure_step: f32,
    gain_step: f32,
) -> Vec<AstroSession> {
    let total_files = preview_nights
        .values()
        .map(|files| files.len())
        .sum::<usize>();
    let mut processed_files = 0usize;

    let mut light_sessions: HashMap<String, SessionBucket> = HashMap::new();
    let mut master_calibration_files: Vec<(SessionKind, FrameMetadata, File)> = Vec::new();
    let mut calibration_files: Vec<(SessionKind, FrameMetadata, File)> = Vec::new();

    for (night_name, files) in preview_nights {
        for file in files {
            processed_files += 1;
            let _ = channel.send(GroupFramesProgress {
                processed: processed_files,
                total: total_files,
            });

            let file_kind = normalize_file_type(file.file_type());

            let Some(metadata) = read_frame_metadata(&file, &night_name) else {
                continue;
            };

            let metadata = FrameMetadata {
                source_night: metadata.source_night,
                camera: metadata.camera,
                filter: metadata.filter,
                telescope: metadata.telescope,
                exposure: round_to_step(metadata.exposure, exposure_step),
                gain: round_to_step(metadata.gain, gain_step),
                temperature: round_to_step(metadata.temperature, temperature_step),
            };

            match file_kind {
                FileKind::Light => {
                    let key = light_session_key(&metadata);
                    let bucket = light_sessions.entry(key.clone()).or_insert_with(|| {
                        SessionBucket::new(
                            key,
                            create_session_fingerprint(&metadata),
                            create_session_match_data(&metadata),
                        )
                    });
                    bucket.push(SessionKind::Light, false, file);
                }
                FileKind::Calibration { kind, is_master } => {
                    if is_master {
                        master_calibration_files.push((kind, metadata, file));
                    } else {
                        calibration_files.push((kind, metadata, file));
                    }
                }
            }
        }
    }

    for (kind, metadata, file) in master_calibration_files {
        insert_calibration_file(&mut light_sessions, kind, true, metadata, file);
    }

    for (kind, metadata, file) in calibration_files {
        insert_calibration_file(&mut light_sessions, kind, false, metadata, file);
    }

    let _ = channel.send(GroupFramesProgress {
        processed: total_files,
        total: total_files,
    });

    let mut grouped = light_sessions
        .into_values()
        .map(SessionBucket::into_session)
        .collect::<Vec<_>>();

    grouped.sort_by(|left, right| {
        left.fingerprint
            .name
            .cmp(&right.fingerprint.name)
            .then_with(|| left.fingerprint.filter.cmp(&right.fingerprint.filter))
            .then_with(|| {
                left.fingerprint
                    .exposure
                    .total_cmp(&right.fingerprint.exposure)
            })
            .then_with(|| left.fingerprint.gain.total_cmp(&right.fingerprint.gain))
            .then_with(|| {
                left.fingerprint
                    .temperature
                    .total_cmp(&right.fingerprint.temperature)
            })
    });

    grouped
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_file(file_type: FileType) -> File {
        serde_json::from_value(serde_json::json!({
            "path": "/tmp/test.fits",
            "name": "test.fits",
            "type": file_type,
            "default_headers": {
                "exposure_time": 60.0,
                "gain": 1.0,
                "temperature": -20.0
            },
            "stats": null,
            "calibrated_frame": null,
            "state": "Default"
        }))
        .expect("test file should deserialize")
    }

    fn test_metadata(source_night: &str) -> FrameMetadata {
        FrameMetadata {
            source_night: source_night.to_string(),
            camera: Some("camera-a".to_string()),
            filter: Some("luminance".to_string()),
            telescope: Some("f/5 scope".to_string()),
            exposure: Some(60.0),
            gain: Some(1.0),
            temperature: Some(-20.0),
        }
    }

    #[test]
    fn normalize_file_type_distinguishes_master_variants() {
        assert_eq!(
            normalize_file_type(&FileType::MasterDark),
            FileKind::Calibration {
                kind: SessionKind::Dark,
                is_master: true,
            }
        );
        assert_eq!(
            normalize_file_type(&FileType::MasterFlat),
            FileKind::Calibration {
                kind: SessionKind::Flat,
                is_master: true,
            }
        );
        assert_eq!(
            normalize_file_type(&FileType::MasterBias),
            FileKind::Calibration {
                kind: SessionKind::Bias,
                is_master: true,
            }
        );
    }

    #[test]
    fn master_matching_ignores_temperature_but_keeps_core_tags() {
        let session = SessionMatchData {
            source_night: "2026-03-09".to_string(),
            camera: Some("camera-a".to_string()),
            filter: Some("luminance".to_string()),
            telescope: Some("f/5 scope".to_string()),
            exposure: Some(60.0),
            gain: Some(2.0),
            temperature: Some(-5.0),
        };

        let matching = FrameMetadata {
            source_night: "2026-03-09".to_string(),
            camera: Some("camera-a".to_string()),
            filter: Some("luminance".to_string()),
            telescope: Some("f/5 scope".to_string()),
            exposure: Some(60.0),
            gain: Some(1.0),
            temperature: Some(-20.0),
        };

        let different_temperature = FrameMetadata {
            temperature: Some(-30.0),
            ..matching.clone()
        };

        assert!(master_calibration_matches_session(
            SessionKind::Flat,
            &session,
            &different_temperature
        ));

        let missing_filter = FrameMetadata {
            filter: Some("red".to_string()),
            ..matching.clone()
        };

        assert!(!master_calibration_matches_session(
            SessionKind::Flat,
            &session,
            &missing_filter
        ));
    }

    #[test]
    fn master_dark_prevents_matching_normal_dark_frames() {
        let master_file = test_file(FileType::MasterDark);
        let normal_file = test_file(FileType::Dark);

        let mut buckets = HashMap::new();
        let metadata = test_metadata("2026-03-09");

        let bucket = SessionBucket::new(
            "light:2026-03-09:camera-a:luminance:f/5 scope:60.000:1.000:-20.000".to_string(),
            create_session_fingerprint(&metadata),
            create_session_match_data(&metadata),
        );
        buckets.insert(bucket.key.clone(), bucket);

        insert_calibration_file(
            &mut buckets,
            SessionKind::Dark,
            true,
            metadata.clone(),
            master_file,
        );

        insert_calibration_file(
            &mut buckets,
            SessionKind::Dark,
            false,
            FrameMetadata {
                temperature: Some(-35.0),
                ..metadata
            },
            normal_file,
        );

        let bucket = buckets.values().next().expect("bucket should exist");
        assert_eq!(bucket.darks.len(), 0);
        assert!(bucket.master_dark.is_some());
    }

    #[test]
    fn normal_dark_can_match_across_nights_when_metadata_matches() {
        let mut buckets = HashMap::new();

        let light_metadata = FrameMetadata {
            source_night: "2026-03-05".to_string(),
            camera: Some("camera-a".to_string()),
            filter: Some("luminance".to_string()),
            telescope: None,
            exposure: Some(60.0),
            gain: Some(200.0),
            temperature: Some(-20.0),
        };

        let bucket = SessionBucket::new(
            "light:2026-03-05:camera-a:luminance::60.000:200.000:-20.000".to_string(),
            create_session_fingerprint(&light_metadata),
            create_session_match_data(&light_metadata),
        );
        buckets.insert(bucket.key.clone(), bucket);

        let dark_metadata_other_night = FrameMetadata {
            source_night: "2026-03-09".to_string(),
            camera: Some("camera-a".to_string()),
            filter: None,
            telescope: Some("scope value present only on dark".to_string()),
            exposure: Some(60.0),
            gain: Some(200.0),
            temperature: Some(-20.0),
        };

        insert_calibration_file(
            &mut buckets,
            SessionKind::Dark,
            false,
            dark_metadata_other_night,
            test_file(FileType::Dark),
        );

        let bucket = buckets.values().next().expect("bucket should exist");
        assert_eq!(bucket.darks.len(), 1);
    }
}
