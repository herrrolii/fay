from __future__ import annotations

from dataclasses import dataclass

from fay.backends.base import WallpaperBackend
from fay.backends.feh import FehBackend
from fay.backends.gnome import GnomeBackend
from fay.env import EnvironmentInfo, is_gnome_session


@dataclass(frozen=True)
class BackendChoice:
    backend: WallpaperBackend | None
    reason: str


class BackendRegistry:
    def __init__(self) -> None:
        self.backends: list[WallpaperBackend] = [
            GnomeBackend(),
            FehBackend(),
        ]
        self.by_id = {backend.id: backend for backend in self.backends}

    def get(self, backend_id: str) -> WallpaperBackend | None:
        return self.by_id.get(backend_id)

    def available(self, env: EnvironmentInfo) -> list[WallpaperBackend]:
        return [backend for backend in self.backends if backend.is_available(env)]

    def resolve(self, env: EnvironmentInfo, backend_id: str) -> BackendChoice:
        if backend_id != "auto":
            backend = self.get(backend_id)
            if backend is None:
                return BackendChoice(None, f"Unknown backend: {backend_id}")
            if not backend.is_available(env):
                return BackendChoice(
                    None,
                    f"Backend '{backend_id}' is not available in this environment.",
                )
            return BackendChoice(backend, f"Selected backend '{backend.id}'")

        # Priority: GNOME -> X11 (feh) -> any available.
        if is_gnome_session(env):
            backend = self.by_id.get("gnome")
            if backend and backend.is_available(env):
                return BackendChoice(backend, "Detected GNOME session")

        if env.is_x11:
            backend = self.by_id.get("feh")
            if backend and backend.is_available(env):
                return BackendChoice(backend, "Detected X11 session")

        available = self.available(env)
        if available:
            return BackendChoice(available[0], "Using first available backend")

        return BackendChoice(None, "No supported wallpaper backend detected")

    def supported_backend_ids(self) -> list[str]:
        return ["auto", "feh", "gnome"]
