# Iteration Summary: v1

- **Created:** 2026-10-17T20:30:03.145657
- **Description:** Version 1, on main dataset

## Dataset Information

- **Total Tiles:** 29430 (Train: 23535, Val: 5895)
- **Clean Tiles:** 17775 | **Defect Tiles:** 11655

### Defect Class Distribution

| Class Name | Count |
| :--- | :---: |
| `satellite_streak` | 1890 |
| `airplane` | 850 |
| `cloud` | 4394 |
| `obstruction` | 1505 |
| `star_trail` | 1559 |
| `unfocused_star` | 1975 |

## Packaged Models

### YOLO Instance Segmentation

- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/sessions/2026-10-17_15-46-17/yolo_astro/weights/best.pt`
- **Mask mAP50:** `0.34544` | **Box mAP50:** `0.44453`
- **Mask Recall:** `0.3683` | **Mask Precision:** `0.46023`

### CNN Model: `astronet`

- **Macro F1:** `0.4099` | **Clean Sky Accuracy:** `0.7203`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/astronet_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.2278 | 0.4414 | **0.3005** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.5016 | 0.8522 | **0.6315** |
| `obstruction` | 0.5363 | 0.8418 | **0.6552** |
| `star_trail` | 0.2106 | 0.655 | **0.3187** |
| `unfocused_star` | 0.4014 | 0.8926 | **0.5538** |

### CNN Model: `resnet18`

- **Macro F1:** `0.4611` | **Clean Sky Accuracy:** `0.7712`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/resnet18_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.3814 | 0.6207 | **0.4724** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6722 | 0.85 | **0.7507** |
| `obstruction` | 0.6171 | 0.8671 | **0.7211** |
| `star_trail` | 0.1793 | 0.675 | **0.2833** |
| `unfocused_star` | 0.4226 | 0.745 | **0.5393** |

### CNN Model: `mobilenet_v3`

- **Macro F1:** `0.4873` | **Clean Sky Accuracy:** `0.7868`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/mobilenet_v3_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.4667 | 0.6759 | **0.5521** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6325 | 0.8833 | **0.7371** |
| `obstruction` | 0.655 | 0.7089 | **0.6809** |
| `star_trail` | 0.2485 | 0.62 | **0.3548** |
| `unfocused_star` | 0.4706 | 0.8233 | **0.5989** |

### CNN Model: `efficientnet_b0`

- **Macro F1:** `0.4766` | **Clean Sky Accuracy:** `0.7993`
- **Source Checkpoint:** `/home/patrick115/Projects/MasterThesis/training/checkpoints/efficientnet_b0_f32/best_model.pt`

| Class | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: |
| `satellite_streak` | 0.371 | 0.7931 | **0.5055** |
| `airplane` | 0.0 | 0.0 | **0.0** |
| `cloud` | 0.6872 | 0.9056 | **0.7814** |
| `obstruction` | 0.5178 | 0.8291 | **0.6375** |
| `star_trail` | 0.2791 | 0.635 | **0.3878** |
| `unfocused_star` | 0.4195 | 0.7875 | **0.5474** |

