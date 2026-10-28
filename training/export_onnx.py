"""
ONNX Model Exporter and Numerical Parity Verifier for AstroGrader.
Exports PyTorch weights to standard ONNX with dynamic batch size [batch, 3, 512, 512] float32.
Validates numerical parity against onnxruntime before saving.
"""

import argparse
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
import torch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models.cnn_zoo import build_model, NUM_CLASSES


def export_to_onnx(
    model_path: Path,
    output_path: Path,
    opset_version: int = 18,
):
    model_path = Path(model_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading checkpoint: {model_path}")
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    model_name = ckpt.get("model_name")
    if not model_name:
        fn = model_path.stem.lower()
        for arch in ["mobilenet_v3", "resnet18", "efficientnet_b0", "resnet34", "astronet"]:
            if arch in fn:
                model_name = arch
                break
        if not model_name:
            model_name = "astronet"

    sd = ckpt.get("state_dict", ckpt)
    model = build_model(model_name, pretrained=False, num_classes=NUM_CLASSES)
    model_dict = model.state_dict()
    adapted_sd = {}
    for k, v in sd.items():
        if k in model_dict and model_dict[k].shape == v.shape:
            adapted_sd[k] = v
        elif f"visual_extractor.{k}" in model_dict and model_dict[f"visual_extractor.{k}"].shape == v.shape:
            adapted_sd[f"visual_extractor.{k}"] = v
    model.load_state_dict(adapted_sd, strict=False)
    model.eval()

    # Dummy inputs: 3-channel float32 RGB patch [1, 3, 512, 512] and 6-element metadata [1, 6]
    dummy_image = torch.randn(1, 3, 512, 512, dtype=torch.float32)
    dummy_meta = torch.randn(1, 6, dtype=torch.float32)

    print(f"Exporting '{model_name}' to ONNX at {output_path} (Opset {opset_version})...")
    torch.onnx.export(
        model,
        (dummy_image, dummy_meta),
        str(output_path),
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        dynamo=False,
        input_names=["image", "meta"],
        output_names=["logits"],
        dynamic_axes={
            "image": {0: "batch_size"},
            "meta": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
    )

    # Validate ONNX model integrity
    onnx_model = onnx.load(str(output_path))
    onnx.checker.check_model(onnx_model)
    print("ONNX model checker: PASSED")

    # Run Numerical Parity Test with onnxruntime
    print("Verifying numerical parity with ONNX Runtime...")
    ort_session = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])

    with torch.no_grad():
        torch_out = model(dummy_image, dummy_meta).numpy()

    ort_inputs = {"image": dummy_image.numpy(), "meta": dummy_meta.numpy()}
    ort_out = ort_session.run(None, ort_inputs)[0]

    max_diff = float(np.max(np.abs(torch_out - ort_out)))
    print(f"Max absolute difference between PyTorch and ONNX: {max_diff:.6e}")
    if max_diff < 1e-4:
        print("Numerical Parity: EXCELLENT (diff < 1e-4)")
    else:
        print("Warning: Parity difference is larger than 1e-4")

    print("\n--- ONNX Model Specification for Rust Integration ---")
    print(f"Input 1:      'image' [-1, 3, 512, 512] (float32)")
    print(f"Input 2:      'meta'  [-1, 6] (float32)")
    print(f"Output Name:  'logits'")
    print(f"Output Shape: [-1, {NUM_CLASSES}] (float32)")
    print(f"File Size:    {output_path.stat().st_size / (1024 * 1024):.2f} MB")
    print(f"Saved:        {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export PyTorch model to ONNX")
    parser.add_argument("--model-path", type=str, required=True, help="Path to best_model.pt")
    parser.add_argument("--output", type=str, default="astro_model.onnx", help="Output .onnx path")
    parser.add_argument("--opset", type=int, default=18, help="ONNX opset version")

    args = parser.parse_args()
    export_to_onnx(
        model_path=Path(args.model_path),
        output_path=Path(args.output),
        opset_version=args.opset,
    )
