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
    opset_version: int = 17,
):
    model_path = Path(model_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading checkpoint: {model_path}")
    ckpt = torch.load(model_path, map_location="cpu")
    model_name = ckpt.get("model_name", "astronet")

    model = build_model(model_name, pretrained=False, num_classes=NUM_CLASSES)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    # Dummy input: 3-channel float32 RGB patch [1, 3, 512, 512]
    dummy_input = torch.randn(1, 3, 512, 512, dtype=torch.float32)

    print(f"Exporting '{model_name}' to ONNX at {output_path} (Opset {opset_version})...")
    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={
            "input": {0: "batch_size"},
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
        torch_out = model(dummy_input).numpy()

    ort_inputs = {"input": dummy_input.numpy()}
    ort_out = ort_session.run(None, ort_inputs)[0]

    max_diff = float(np.max(np.abs(torch_out - ort_out)))
    print(f"Max absolute difference between PyTorch and ONNX: {max_diff:.6e}")
    if max_diff < 1e-4:
        print("Numerical Parity: EXCELLENT (diff < 1e-4)")
    else:
        print("Warning: Parity difference is larger than 1e-4")

    print("\n--- ONNX Model Specification for Rust Integration ---")
    print(f"Input Name:   'input'")
    print(f"Input Shape:  [-1, 3, 512, 512] (float32)")
    print(f"Output Name:  'logits'")
    print(f"Output Shape: [-1, 5] (float32)")
    print(f"File Size:    {output_path.stat().st_size / (1024 * 1024):.2f} MB")
    print(f"Saved:        {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export PyTorch model to ONNX")
    parser.add_argument("--model-path", type=str, required=True, help="Path to best_model.pt")
    parser.add_argument("--output", type=str, default="astro_model.onnx", help="Output .onnx path")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version")

    args = parser.parse_args()
    export_to_onnx(
        model_path=Path(args.model_path),
        output_path=Path(args.output),
        opset_version=args.opset,
    )
