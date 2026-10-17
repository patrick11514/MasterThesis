# Iteration Summary: iter_1

- **Created:** 2026-10-17T17:55:07.297125
- **Description:** Baseline models before synthetic defect calibration (YOLO11 + initial CNNs)

## Dataset Information

- **Total Tiles:** 30 (Train: 22, Val: 8)
- **Clean Tiles:** 30 | **Defect Tiles:** 0

### Defect Class Distribution

| Class Name | Count |
| :--- | :---: |
| `satellite_streak` | 0 |
| `airplane` | 0 |
| `cloud` | 0 |
| `obstruction` | 0 |
| `star_trail` | 0 |
| `unfocused_star` | 0 |

## Packaged Models

### YOLO Instance Segmentation

- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/runs/segment/runs/segment/yolo11_astro/weights/best.pt`
- **Mask mAP50:** `0.43601` | **Box mAP50:** `0.49411`
- **Mask Recall:** `0.42275` | **Mask Precision:** `0.66792`

### CNN Model: `astronet`

- **Macro F1:** `0.2578` | **Clean Sky Accuracy:** `0.8646`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/astronet_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.0 | 0.0 | **0.0** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6736 | 0.9699 | **0.7951** |
| `obstruction` | 0.0 | 0.0 | **0.0** |
| `star_trail` | 1.0 | 0.3281 | **0.4941** |
| `unfocused_star` | - | - | **-** |

### CNN Model: `resnet18`

- **Macro F1:** `0.3524` | **Clean Sky Accuracy:** `0.837`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/resnet18_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.3029 | 0.5724 | **0.3962** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.5834 | 0.8477 | **0.6912** |
| `obstruction` | 0.4405 | 0.4878 | **0.463** |
| `star_trail` | 0.5109 | 0.629 | **0.5639** |
| `unfocused_star` | 0.0 | 0.0 | **0.0** |

### CNN Model: `mobilenet_v3`

- **Macro F1:** `0.3444` | **Clean Sky Accuracy:** `0.7812`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/mobilenet_v3_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.1667 | 1.0 | **0.2857** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.5529 | 0.3821 | **0.4519** |
| `obstruction` | 0.0 | 0.0 | **0.0** |
| `star_trail` | 1.0 | 0.9688 | **0.9841** |
| `unfocused_star` | - | - | **-** |

