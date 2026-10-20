# Iteration Summary: v2

- **Created:** 2026-10-20T13:27:55.862917
- **Description:** trained with better plane data
- **Parent Iteration:** `v1`

## Dataset Information

- **Total Tiles:** 29430 (Train: 23535, Val: 5895)
- **Clean Tiles:** 17787 | **Defect Tiles:** 11643

### Defect Class Distribution

| Class Name | Count |
| :--- | :---: |
| `satellite_streak` | 1900 |
| `airplane` | 821 |
| `cloud` | 4394 |
| `obstruction` | 1501 |
| `star_trail` | 1539 |
| `unfocused_star` | 2006 |

## Packaged Models

### YOLO Instance Segmentation

- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-18_16-22-13/yolo_astro/weights/best.pt`
- **Mask mAP50:** `0.33555` | **Box mAP50:** `0.43546`
- **Mask Recall:** `0.38916` | **Mask Precision:** `0.42755`

### CNN Model: `astronet`

- **Macro F1:** `0.4075` | **Clean Sky Accuracy:** `0.724`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-18_16-22-13/astronet_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.2143 | 0.6 | **0.3158** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.5702 | 0.8344 | **0.6775** |
| `obstruction` | 0.4926 | 0.8418 | **0.6215** |
| `star_trail` | 0.2016 | 0.645 | **0.3071** |
| `unfocused_star` | 0.3811 | 0.8322 | **0.5228** |

### CNN Model: `resnet18`

- **Macro F1:** `0.4562` | **Clean Sky Accuracy:** `0.7579`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-18_16-22-13/resnet18_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.4375 | 0.6759 | **0.5312** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.5862 | 0.9367 | **0.7211** |
| `obstruction` | 0.4892 | 0.8608 | **0.6239** |
| `star_trail` | 0.2209 | 0.645 | **0.3291** |
| `unfocused_star` | 0.3919 | 0.8277 | **0.532** |

### CNN Model: `mobilenet_v3`

- **Macro F1:** `0.4755` | **Clean Sky Accuracy:** `0.7913`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-18_16-22-13/mobilenet_v3_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.4688 | 0.7241 | **0.5691** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6804 | 0.9156 | **0.7807** |
| `obstruction` | 0.5909 | 0.6582 | **0.6228** |
| `star_trail` | 0.217 | 0.51 | **0.3045** |
| `unfocused_star` | 0.4451 | 0.8166 | **0.5762** |

### CNN Model: `efficientnet_b0`

- **Macro F1:** `0.4573` | **Clean Sky Accuracy:** `0.7803`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-18_16-22-13/efficientnet_b0_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.4929 | 0.7172 | **0.5843** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6685 | 0.95 | **0.7848** |
| `obstruction` | 0.3239 | 0.5823 | **0.4163** |
| `star_trail` | 0.2725 | 0.65 | **0.384** |
| `unfocused_star` | 0.4366 | 0.8389 | **0.5743** |

