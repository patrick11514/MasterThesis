"""
CNN Architecture Zoo for Astronomical Defect Detection.
All models accept Unified 3-Channel Input [batch, 3, 512, 512] of type float32.
Outputs 5 multi-label logits corresponding to:
[0: satellite_streak, 1: airplane, 2: cloud, 3: obstruction, 4: star_trail]
(Empty / all below threshold = Clean Sky).
"""

from typing import Optional
import torch
import torch.nn as nn
import torchvision.models as models

NUM_CLASSES = 5


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


class AstroNet(nn.Module):
    """
    Pure Astronomical CNN trained from scratch on raw float32 patterns.
    Lightweight, fast, and specifically regularized for faint streaks and diffuse gradients.
    """
    def __init__(self, in_channels: int = 3, num_classes: int = NUM_CLASSES):
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

        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        self.dropout = nn.Dropout(p=0.2)
        self.classifier = nn.Linear(256, num_classes)

        # Kaiming Normal Initialization
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
        out = self.pool(out)
        out = torch.flatten(out, 1)
        out = self.dropout(out)
        logits = self.classifier(out)
        return logits


def build_model(
    model_name: str,
    pretrained: bool = True,
    num_classes: int = NUM_CLASSES,
) -> nn.Module:
    """
    Factory function for instantiating multi-label CNN models.
    Supports: 'astronet', 'resnet18', 'resnet34', 'mobilenet_v3', 'efficientnet_b0'.
    """
    name = model_name.lower().replace("-", "_")

    if name in ("astronet", "pure_cnn"):
        # Always trained from scratch
        return AstroNet(in_channels=3, num_classes=num_classes)

    elif name == "resnet18":
        weights = models.ResNet18_Weights.DEFAULT if pretrained else None
        model = models.resnet18(weights=weights)
        in_feat = model.fc.in_features
        model.fc = nn.Linear(in_feat, num_classes)
        return model

    elif name == "resnet34":
        weights = models.ResNet34_Weights.DEFAULT if pretrained else None
        model = models.resnet34(weights=weights)
        in_feat = model.fc.in_features
        model.fc = nn.Linear(in_feat, num_classes)
        return model

    elif name in ("mobilenet_v3", "mobilenet_v3_small"):
        weights = models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        model = models.mobilenet_v3_small(weights=weights)
        in_feat = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(in_feat, num_classes)
        return model

    elif name == "mobilenet_v3_large":
        weights = models.MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
        model = models.mobilenet_v3_large(weights=weights)
        in_feat = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(in_feat, num_classes)
        return model

    elif name == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b0(weights=weights)
        in_feat = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_feat, num_classes)
        return model

    else:
        raise ValueError(
            f"Unknown model name '{model_name}'. Choose from: "
            "astronet, resnet18, resnet34, mobilenet_v3, efficientnet_b0"
        )
