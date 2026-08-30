# src/dndmusic/gui/theme/models.py
"""Theme data model (pure data — no Qt imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class VisualStyle(Enum):
    SCI_FI = "Sci-Fi"
    MEDIEVAL = "Medieval"
    CASUAL = "Casual"
    MINIMAL = "Minimal"


@dataclass
class ThemeConfig:
    name: str
    primary: str
    gradient_colors: List[str] = field(default_factory=lambda: ["#0a1628", "#000000"])
    gradient_angle: int = 180
    accent: str = "#0099cc"
    glow_intensity: float = 0.4
    border_radius: int = 8
    border_width: int = 2
    visual_style: VisualStyle = VisualStyle.SCI_FI
    #: Optional background image, and how it is blended.
    background_image: str = ""
    #: 0 = image invisible, 1 = image at full strength.
    background_opacity: float = 0.5
    #: Black veil over the image, so text stays readable on a busy photo.
    overlay_opacity: float = 0.45

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "primary": self.primary,
            "gradient_colors": list(self.gradient_colors),
            "gradient_angle": self.gradient_angle,
            "accent": self.accent,
            "glow_intensity": self.glow_intensity,
            "border_radius": self.border_radius,
            "border_width": self.border_width,
            "visual_style": self.visual_style.value,
            "background_image": self.background_image,
            "background_opacity": self.background_opacity,
            "overlay_opacity": self.overlay_opacity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThemeConfig":
        payload = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        payload["visual_style"] = VisualStyle(payload.get("visual_style", VisualStyle.SCI_FI.value))
        return cls(**payload)

    @property
    def has_background(self) -> bool:
        return bool(self.background_image)

    def copy(self) -> "ThemeConfig":
        return ThemeConfig(**{**self.to_dict(), "visual_style": self.visual_style})
