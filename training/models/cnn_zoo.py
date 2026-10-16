"""
CNN Architecture Zoo for Astronomical Defect Detection (V2).
All models accept:
- Unified 3-Channel Input: [batch, 3, 512, 512] of type float32.
- 6-element Optical & Statistical Metadata Vector: [batch, 6] of type float32.
Outputs 6 multi-label logits corresponding to:
[0: satellite_streak, 1: airplane, 2: cloud, 3: obstruction, 4: star_trail, 5: unfocused_star]
(Empty / all below threshold = Clean Sky).
"""

from typing import Optional
from pathlib import Path
import sys
import torch
import torch.nn as nn
import torchvision.models as models

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from fits_utils import CLASSES

NUM_CLASSES = len(CLASSES)


class DualPool2d(nn.Module):
    """
    Concatenated AdaptiveAvgPool2d + MaxPool (via amax).
    Preserves both diffuse low-frequency gradients (clouds, vignetting)
    and high-frequency localized activations (1-pixel satellite streaks, strobes).
    Uses amax over spatial dimensions for seamless, robust ONNX export across all Dynamo and TorchScript backends.
    """
    def __init__(self):
        super().__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d((1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        avg_feat = torch.flatten(self.avg_pool(x), 1)
        max_feat = torch.flatten(x.amax(dim=(-2, -1), keepdim=True), 1)
        return torch.cat([avg_feat, max_feat], dim=1)


class UniversalFusionWrapper(nn.Module):
    """
    Late-Fusion Wrapper that conditions deep convolutional features on optical
    and statistical metadata via Feature-wise Linear Modulation (FiLM).
    """
    def __init__(
        self,
        visual_extractor: nn.Module,
        visual_channels: int,
        meta_dim: int = 6,
        num_classes: int = NUM_CLASSES,
    ):
        super().__init__()
        self.visual_extractor = visual_extractor  # Outputs [B, C, H, W]
        self.dual_pool = DualPool2d()             # Outputs [B, 2 * C]
        self.visual_channels = visual_channels
        self.meta_dim = meta_dim
        self.num_classes = num_classes

        vis_dim = visual_channels * 2

        self.meta_net = nn.Sequential(
            nn.Linear(meta_dim, 32),
            nn.LayerNorm(32),
            nn.SiLU(inplace=True),
            nn.Linear(32, 64),
            nn.LayerNorm(64),
            nn.SiLU(inplace=True),
        )

        # FiLM (Feature-wise Linear Modulation) scale & shift from optical metadata
        self.film_gamma = nn.Linear(64, vis_dim)
        self.film_beta = nn.Linear(64, vis_dim)

        self.classifier = nn.Sequential(
            nn.Dropout(p=0.2),
            nn.Linear(vis_dim + 64, 128),
            nn.SiLU(inplace=True),
            nn.Linear(128, num_classes),
        )

    def forward(self, x_img: torch.Tensor, x_meta: Optional[torch.Tensor] = None) -> torch.Tensor:
        feat_map = self.visual_extractor(x_img)
        v_img = self.dual_pool(feat_map)  # [B, 2 * C]

        if x_meta is None:
            x_meta = torch.zeros((x_img.size(0), self.meta_dim), dtype=x_img.dtype, device=x_img.device)

        v_meta = self.meta_net(x_meta)     # [B, 64]
        gamma = 1.0 + self.film_gamma(v_meta)
        beta = self.film_beta(v_meta)
        v_img_modulated = v_img * gamma + beta

        combined = torch.cat([v_img_modulated, v_meta], dim=1)
        return self.classifier(combined)


class AstroResBlock(nn.Module):
    """Basic Residual Block with GroupNorm (better for astronomy and varying batch sizes)."""
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=stride, padding=1, bias=False)
        self.gn1 = nn.GroupNorm(min(8, out_channels), out_channels)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.gn2 = nn.GroupNorm(min(8, out_channels), out_channels)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=stride, bias=False),
                nn.GroupNorm(min(8, out_channels), out_channels),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        res = self.shortcut(x)
        out = self.relu(self.gn1(self.conv1(x)))
        out = self.gn2(self.conv2(out))
        out += res
        return self.relu(out)


class AstroNetTrunk(nn.Module):
    """Convolutional feature extraction trunk for AstroNet [B, 3, H, W] -> [B, 256, H/32, W/32]."""
    def __init__(self, in_channels: int = 3):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=7, stride=2, padding=3, bias=False),
            nn.GroupNorm(8, 32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1),
        )

        self.stage1 = nn.Sequential(
            AstroResBlock(32, 32, stride=1),
            AstroResBlock(32, 32, stride=1),
        )
        self.stage2 = nn.Sequential(
            AstroResBlock(32, 64, stride=2),
            AstroResBlock(64, 64, stride=1),
        )
        self.stage3 = nn.Sequential(
            AstroResBlock(64, 128, stride=2),
            AstroResBlock(128, 128, stride=1),
        )
        self.stage4 = nn.Sequential(
            AstroResBlock(128, 256, stride=2),
            AstroResBlock(256, 256, stride=1),
        )
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
            elif isinstance(m, nn.GroupNorm):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.stem(x)
        out = self.stage1(out)
        out = self.stage2(out)
        out = self.stage3(out)
        out = self.stage4(out)
        return out


def AstroNet(in_channels: int = 3, num_classes: int = NUM_CLASSES, meta_dim: int = 6) -> UniversalFusionWrapper:
    """Instantiates pure AstroNet backbone wrapped in UniversalFusionWrapper."""
    trunk = AstroNetTrunk(in_channels=in_channels)
    return UniversalFusionWrapper(trunk, visual_channels=256, meta_dim=meta_dim, num_classes=num_classes)


def build_model(
    model_name: str,
    pretrained: bool = True,
    num_classes: int = NUM_CLASSES,
    meta_dim: int = 6,
) -> UniversalFusionWrapper:
    """
    Factory function for instantiating multi-modal late-fusion CNN models.
    Supports: 'astronet', 'resnet18', 'resnet34', 'mobilenet_v3', 'efficientnet_b0'.
    """
    name = model_name.lower().replace("-", "_")

    if name in ("astronet", "pure_cnn"):
        return AstroNet(in_channels=3, num_classes=num_classes, meta_dim=meta_dim)

    elif name == "resnet18":
        weights = models.ResNet18_Weights.DEFAULT if pretrained else None
        base = models.resnet18(weights=weights)
        trunk = nn.Sequential(
            base.conv1,
            base.bn1,
            base.relu,
            base.maxpool,
            base.layer1,
            base.layer2,
            base.layer3,
            base.layer4,
        )
        return UniversalFusionWrapper(trunk, visual_channels=512, meta_dim=meta_dim, num_classes=num_classes)

    elif name == "resnet34":
        weights = models.ResNet34_Weights.DEFAULT if pretrained else None
        base = models.resnet34(weights=weights)
        trunk = nn.Sequential(
            base.conv1,
            base.bn1,
            base.relu,
            base.maxpool,
            base.layer1,
            base.layer2,
            base.layer3,
            base.layer4,
        )
        return UniversalFusionWrapper(trunk, visual_channels=512, meta_dim=meta_dim, num_classes=num_classes)

    elif name in ("mobilenet_v3", "mobilenet_v3_small"):
        weights = models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        base = models.mobilenet_v3_small(weights=weights)
        trunk = base.features
        return UniversalFusionWrapper(trunk, visual_channels=576, meta_dim=meta_dim, num_classes=num_classes)

    elif name == "mobilenet_v3_large":
        weights = models.MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
        base = models.mobilenet_v3_large(weights=weights)
        trunk = base.features
        return UniversalFusionWrapper(trunk, visual_channels=960, meta_dim=meta_dim, num_classes=num_classes)

    elif name == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
        base = models.efficientnet_b0(weights=weights)
        trunk = base.features
        return UniversalFusionWrapper(trunk, visual_channels=1280, meta_dim=meta_dim, num_classes=num_classes)

    else:
        raise ValueError(
            f"Unknown model name '{model_name}'. Choose from: "
            "astronet, resnet18, resnet34, mobilenet_v3, efficientnet_b0"
        )
