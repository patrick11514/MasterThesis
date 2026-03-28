# Astro-Photo Quality Sorter: Automated Culling via Statistical and Machine Learning Approaches

## Project Overview

In deep-sky astrophotography, the final image quality heavily depends on stacking dozens or hundreds of individual exposures. Variations in atmospheric seeing, tracking errors, wind, and passing clouds introduce flawed frames (e.g., bloated stars, trailing, low contrast). Manually reviewing and culling these frames is a highly subjective and time-consuming bottleneck.

This project aims to develop a cross-platform desktop application to automate the sorting of astronomical images (starting with standard `.fits` files) into three distinct categories:

1. **Good:** High-quality frames ready for stacking.
2. **Trash:** Quantifiably flawed frames.
3. **Undecided:** Borderline frames requiring manual user review.

The project is structured in two phases: a deterministic, statistical foundation for the semestral project, followed by a robust Machine Learning expansion for the Master's thesis.

---

## Phase 1: Semestral Project (Statistical Baseline)

The semestral phase focuses on building the core application and a deterministic sorting engine based on traditional astronomical point-spread function (PSF) mathematics.

### Methodology

Images will be grouped by session (night/equipment/target). The engine will extract key image quality metrics and calculate a normal distribution for the session. Frames falling outside an acceptable standard deviation (e.g., beyond a 3-sigma threshold) will be classified as Trash, while borderline cases will be flagged as Undecided.

### Core Metrics Calculated

* **FWHM (Full Width at Half Maximum):** To measure general star bloat.
* **HFR (Half Flux Radius):** A more robust measurement for seeing conditions and focus accuracy, utilizing flux integration.
* **Star Eccentricity:** To detect mount tracking errors, wind gusts, or optical aberrations (trailing).
* **Background Contrast & Sky Level:** To identify passing clouds or severe light pollution gradients.
* **Star Count:** A fallback metric for overall image clarity.

### Technology Stack

* **Core Logic:** Rust (leveraging `tokio` for async I/O and `rayon` for data parallelism to process heavy astronomical files).
* **Source Extraction:** Utilizing C/C++ implementations (e.g., SExtractor algorithms via `sep-sys-rs` bindings) for high-performance pixel-math.
* **Application Framework:** Tauri, providing a lightweight, native cross-platform experience (fully supporting Linux/Wayland environments).
* **User Interface:** SvelteKit combined with TypeScript and TailwindCSS to create a highly responsive, drag-and-drop filtering GUI.

---

## Phase 2: Master's Thesis (Machine Learning Integration)

The Master's thesis will build upon the statistical baseline by introducing Deep Learning, addressing the limitations of purely mathematical sorting in edge cases (e.g., heavy nebulosity confusing background extraction algorithms).

### Research Scope & Implementation

* **Comparative Analysis:** Evaluating the efficiency, accuracy, and computational cost of the Phase 1 statistical model against a trained Neural Network.
* **Active Learning ("Dotrénování"):** Implementing a human-in-the-loop system. The user's manual classification of the "Undecided" folder from Phase 1 will be used as labeled training data to continuously fine-tune the classification model for their specific camera sensor and local seeing conditions.
* **Model Deployment:** Training models locally or via Python/PyTorch, then exporting to ONNX format to be executed directly within the Rust/Tauri backend for seamless user experience without requiring a Python environment.


**Look into it: https://github.com/karpathy/autoresearch?tab=readme-ov-file**

---

## Academic References & Foundations

This project builds upon established astronomical data processing literature, notably:

* *SExtractor: Software for source extraction* (Bertin & Arnouts, 1996) for baseline mesh-based background and moments extraction.
* *Fast Auto-Focus Method and Software for CCD-based Telescopes* (Weber & Brady, 2001) for the mathematical superiority of HFR over FWHM.
* *Noise-based Detection and Segmentation of Nebulous Objects* (Akhlaghi & Ichikawa, 2015) for advanced, threshold-free background sky estimation.