from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MODE_CHOICES = ("auto", "fill", "fit", "center", "tile")


@dataclass(frozen=True)
class EnvironmentInfo:
    session_type: str
    desktop_session: str
    current_desktop: str
    wayland_display: str
    x_display: str
    sway: bool
    hyprland: bool
    commands: set[str] = field(default_factory=set)

    @property
    def is_wayland(self) -> bool:
        return self.session_type == "wayland" or bool(self.wayland_display)

    @property
    def is_x11(self) -> bool:
        return self.session_type == "x11" or bool(self.x_display)


@dataclass(frozen=True)
class WallpaperState:
    backend_id: str
    image_path: str
    mode: str
    backend_state: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.image_path).expanduser()


@dataclass(frozen=True)
class BackendResult:
    ok: bool
    error: str | None = None
