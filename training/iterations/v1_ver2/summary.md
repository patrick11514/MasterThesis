# Iteration Summary: v1_ver2

- **Created:** 2026-10-27T20:28:58.202281
- **Description:** New and better data, before implementing the dynamic binning, and grayscale simulation

## Dataset Information

- **Total Tiles:** 38739 (Train: 30912, Val: 7827)
- **Clean Tiles:** 23871 | **Defect Tiles:** 14868

### Defect Class Distribution

| Class Name | Count |
| :--- | :---: |
| `satellite_streak` | 2966 |
| `airplane` | 1076 |
| `cloud` | 5114 |
| `obstruction` | 1945 |
| `star_trail` | 2254 |
| `unfocused_star` | 2102 |

## Packaged Models

### YOLO Instance Segmentation

- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-23_10-52-34/yolo_astro/weights/best.pt`
- **Mask mAP50:** `0.32498` | **Box mAP50:** `0.46639`
- **Mask Recall:** `0.58254` | **Mask Precision:** `0.42623`

### CNN Model: `astronet`

- **Macro F1:** `0.3276` | **Clean Sky Accuracy:** `0.4675`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-23_10-52-34/astronet_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.0565 | 0.6856 | **0.1044** |
| `airplane` | 0.0058 | 0.2 | **0.0112** |
| `cloud` | 0.3553 | 0.6332 | **0.4552** |
| `obstruction` | 0.3056 | 0.4488 | **0.3636** |
| `star_trail` | 0.5284 | 0.3901 | **0.4489** |
| `unfocused_star` | 0.4155 | 0.9736 | **0.5824** |

### CNN Model: `resnet18`

- **Macro F1:** `0.6415` | **Clean Sky Accuracy:** `0.688`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-23_10-52-34/resnet18_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.5 | 0.8482 | **0.6291** |
| `airplane` | 1.0 | 0.8 | **0.8889** |
| `cloud` | 0.253 | 0.9687 | **0.4012** |
| `obstruction` | 0.5449 | 0.9171 | **0.6836** |
| `star_trail` | 0.4277 | 0.6568 | **0.518** |
| `unfocused_star` | 0.6005 | 0.9245 | **0.7281** |

### CNN Model: `mobilenet_v3`

- **Macro F1:** `0.7412` | **Clean Sky Accuracy:** `0.8888`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-23_10-52-34/mobilenet_v3_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.5781 | 0.8428 | **0.6858** |
| `airplane` | 0.7143 | 1.0 | **0.8333** |
| `cloud` | 0.658 | 0.7585 | **0.7047** |
| `obstruction` | 0.5789 | 0.9659 | **0.7239** |
| `star_trail` | 0.6277 | 0.7284 | **0.6743** |
| `unfocused_star` | 0.704 | 0.9962 | **0.825** |

### CNN Model: `efficientnet_b0`

- **Macro F1:** `0.7244` | **Clean Sky Accuracy:** `0.828`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-23_10-52-34/efficientnet_b0_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.4869 | 0.8537 | **0.6201** |
| `airplane` | 0.7143 | 1.0 | **0.8333** |
| `cloud` | 0.4104 | 0.9269 | **0.5689** |
| `obstruction` | 0.6923 | 0.922 | **0.7908** |
| `star_trail` | 0.6644 | 0.7383 | **0.6994** |
| `unfocused_star` | 0.7515 | 0.9358 | **0.8336** |

