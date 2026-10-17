# Evolutionary Model Iterations Benchmark (Diploma Thesis Chapter)

This document summarizes the chronological iterations of defect detection models, showing changes in dataset generation, architecture improvements, and performance metrics.

## Overview of Iterations

| Iteration | Date | Description | Total Tiles | YOLO Mask mAP50 | ResNet18 Macro F1 |
| :--- | :--- | :--- | :---: | :---: | :---: |
| `iter_1` | 2026-10-17 | Baseline models before synthetic defect calibration (YOLO11 + initial CNNs) | 30 | **0.4360** | **0.3524** |

## Per-Class F1 Score Evolution (ResNet18)

| Defect Class | `iter_1` |
| :--- | :---: |
| **satellite_streak** | 0.3962 |
| **airplane** | 0.0000 |
| **cloud** | 0.6912 |
| **obstruction** | 0.4630 |
| **star_trail** | 0.5639 |
| **unfocused_star** | 0.0000 |
