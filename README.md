# Astro-photo quality sorter

Stack:
Tauri + Svelte:
- Svelte as simple GUI
- Rust -> multi-thread calculations

Logic:
- Get N .fits files, calulate metrics on them (like star width, background contrast etc...)
- Create create normal distrubution of these stats on all images in group (groupping by nights/equipment/)

https://gemini.google.com/app/f7e18a0e9c241808

Metrics:
- FWHM - Full width at half maximum
- HFR - half flux radius
- star eccentricity
- background contrast
- star count?

File support:
- FITS
- TIF?
- XISF? - https://pixinsight.com/xisf/index.html

Crates:
- Reading FITS files: https://crates.io/crates/fitsio
- SEP? - https://github.com/sep-developers/sep + bindings https://github.com/RReverser/sep-sys-rs?tab=readme-ov-file or writing it myself?


Papers (review):

### 1. Star Width, Shape, and Focus (FWHM & HFR)

* **"Fast Auto-Focus Method and Software for CCD-based Telescopes"** by Larry Weber and Steve Brady (2001/2004).
* *Theoretical Focus:* This is the foundational paper that introduced Half Flux Diameter (HFD) and Half Flux Radius (HFR) to the astrophotography community. It mathematically demonstrates why HFR is far more robust than FWHM when dealing with atmospheric turbulence (seeing) or severely out-of-focus stars. It explains how to move away from peak-value curve fitting and instead use flux integration.


* **"Impact of sensor effects on the astronomical point-spread function"** by J. Meyers and P. Burchat (2015).
* *Theoretical Focus:* An excellent deep dive into how the Point Spread Function (PSF)—and thus FWHM and eccentricity—is distorted by physical sensor characteristics (like the Brighter-Fatter effect). This is highly relevant if you are writing precise shape-measurement routines.



### 2. Core Source Extraction & Canonical Algorithms

* **"SExtractor: Software for source extraction"** by Emmanuel Bertin and Stéphane Arnouts (1996).
* *Theoretical Focus:* This is arguably the most important paper in observational astronomy regarding image processing. It acts as a complete blueprint for the field. It details the exact mathematical algorithms for determining the local background using a meshed grid, iterative sigma-clipping, extracting image moments for shape analysis, and differentiating stars from galaxies.


* **"Point-Source Extraction with MOPEX"** by D. Makovoz and F. R. Marleau (2005).
* *Theoretical Focus:* Details the mathematics behind Point Response Function (PRF) estimation and extracting point sources in complex, background-limited, or confusion-limited (highly crowded) star fields.



### 3. Advanced Background Estimation & Contrast

* **"Noise-based Detection and Segmentation of Nebulous Objects"** by Mohammad Akhlaghi and Takashi Ichikawa (2015).
* *Theoretical Focus:* This paper outlines the algorithms behind the modern tool *NoiseChisel*. It breaks away from traditional SExtractor-style sigma-clipping and proposes a purely statistical, threshold-free approach to finding the true sky background, even when faint structures, clouds, or nebulosity cover the image.


* **"A method of complex background estimation in astronomical images"** by Adam Popowicz and Bogdan Smolka (2015).
* *Theoretical Focus:* Proposes a novel alternative to standard mesh-based background extraction. It uses morphological distance transforms and analyzes the local pixel neighborhood to filter out foreground objects (stars, hot pixels, cosmic rays) to find the baseline sky without requiring complex tuning parameters.


* **"A geometric approach to estimate background in astronomical images"** by S. Maji et al. (2024).
* *Theoretical Focus:* A very recent mathematical approach that uses the method of steepest descent to locate local minima in an image. It is specifically designed to handle "confusion limits" in dense star fields, where traditional algorithms mathematically overestimate the background sky level due to the sheer density of overlapping starlight.