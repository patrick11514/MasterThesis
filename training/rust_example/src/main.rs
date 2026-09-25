//! Standalone Rust example demonstrating ONNX model inference for AstroGrader.
//! Strictly accepts Unified 3-Channel RGB float data: Vec<(f32, f32, f32)> or planar &[f32].

use ndarray::Array4;
use ort::{session::Session, value::Tensor};
use std::path::Path;
use std::time::Instant;

pub const CLASSES: [&str; 5] = [
    "satellite_streak",
    "airplane",
    "cloud",
    "obstruction",
    "star_trail",
];

#[derive(Debug, Clone, serde::Serialize)]
pub struct TileAnomaly {
    pub x: usize,
    pub y: usize,
    pub class_name: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct FrameInspectionReport {
    pub is_clean: bool,
    pub detected_defects: Vec<String>,
    pub anomalies: Vec<TileAnomaly>,
    pub inference_time_ms: f64,
}

pub struct AstroModelRunner {
    session: Session,
}

impl AstroModelRunner {
    pub fn new<P: AsRef<Path>>(onnx_path: P) -> Result<Self, Box<dyn std::error::Error>> {
        let session = Session::builder()?
            .with_intra_threads(4)?
            .commit_from_file(onnx_path)?;
        Ok(Self { session })
    }

    /// Evaluates a single 512x512 RGB tile of floats: Vec<(f32, f32, f32)>
    /// Returns predicted class probabilities [sat, plane, cloud, obstruction, star_trail]
    pub fn evaluate_tile(
        &mut self,
        tile_rgb: &[(f32, f32, f32)], // Length must be 512 * 512
        threshold: f32,
    ) -> Result<Vec<(String, f32)>, Box<dyn std::error::Error>> {
        assert_eq!(tile_rgb.len(), 512 * 512);

        // Convert interleaved Vec<(f32, f32, f32)> to planar NCHW [1, 3, 512, 512]
        let mut input_arr = Array4::<f32>::zeros((1, 3, 512, 512));
        for y in 0..512 {
            for x in 0..512 {
                let idx = y * 512 + x;
                let (r, g, b) = tile_rgb[idx];
                input_arr[[0, 0, y, x]] = r;
                input_arr[[0, 1, y, x]] = g;
                input_arr[[0, 2, y, x]] = b;
            }
        }

        // Run ONNX Session
        let input_tensor = Tensor::from_array(input_arr)?;
        let outputs = self.session.run(ort::inputs!["input" => input_tensor]?)?;
        
        let logits_tensor = outputs["logits"].try_extract_tensor::<f32>()?;
        let logits = logits_tensor.as_slice().unwrap();

        // Multi-label Sigmoid: 1.0 / (1.0 + exp(-logit))
        let mut detected = Vec::new();
        for (i, &l) in logits.iter().enumerate() {
            let prob = 1.0 / (1.0 + (-l).exp());
            if prob >= threshold {
                detected.push((CLASSES[i].to_string(), prob));
            }
        }

        Ok(detected)
    }

    /// Full frame analysis: slices arbitrary HxW RGB frame into 512x512 tiles
    pub fn inspect_full_frame(
        &mut self,
        frame_rgb: &[(f32, f32, f32)],
        width: usize,
        height: usize,
        threshold: f32,
    ) -> Result<FrameInspectionReport, Box<dyn std::error::Error>> {
        let t0 = Instant::now();
        let tile_size = 512;
        let stride = 460;

        let mut anomalies = Vec::new();
        let mut detected_classes = std::collections::HashSet::new();

        for y in (0..height.saturating_sub(tile_size) + 1).step_by(stride) {
            for x in (0..width.saturating_sub(tile_size) + 1).step_by(stride) {
                // Extract 512x512 tile
                let mut tile = Vec::with_capacity(tile_size * tile_size);
                for ty in 0..tile_size {
                    for tx in 0..tile_size {
                        let idx = (y + ty) * width + (x + tx);
                        tile.push(frame_rgb[idx]);
                    }
                }

                let tile_res = self.evaluate_tile(&tile, threshold)?;
                for (cls, conf) in tile_res {
                    detected_classes.insert(cls.clone());
                    anomalies.push(TileAnomaly {
                        x,
                        y,
                        class_name: cls,
                        confidence: conf,
                    });
                }
            }
        }

        let elapsed = t0.elapsed().as_secs_f64() * 1000.0;
        let is_clean = anomalies.is_empty();

        Ok(FrameInspectionReport {
            is_clean,
            detected_defects: detected_classes.into_iter().collect(),
            anomalies,
            inference_time_ms: elapsed,
        })
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("--- AstroGrader Rust ONNX Inference Engine Example ---");
    let model_path = Path::new("../astro_model.onnx");

    if !model_path.exists() {
        println!("Note: Model not found at '{model_path:?}'. Export it first via `python export_onnx.py`.");
        return Ok(());
    }

    println!("Loading ONNX model: {model_path:?}");
    let mut runner = AstroModelRunner::new(model_path)?;

    // Simulate a 1024x1024 frame with dummy float RGB values
    let width = 1024;
    let height = 1024;
    let simulated_frame: Vec<(f32, f32, f32)> = vec![(0.25, 0.25, 0.25); width * height];

    println!("Running frame inspection on {width}x{height} image...");
    let report = runner.inspect_full_frame(&simulated_frame, width, height, 0.5)?;

    println!("\n--- Inspection Report ---");
    println!("Verdict:            {}", if report.is_clean { "CLEAN SKY (ACCEPT)" } else { "DEFECTS FLAGGED" });
    println!("Processing Time:    {:.2} ms", report.inference_time_ms);
    println!("Detected Classes:   {:?}", report.detected_defects);
    println!("Tile Anomalies:     {}", report.anomalies.len());

    Ok(())
}
