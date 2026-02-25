from __future__ import annotations

from pathlib import Path

from fay.backends.base import ApplyContext, CommandBackend, run_command
from fay.env import has_command
from fay.models import BackendResult, EnvironmentInfo


class HyprpaperBackend(CommandBackend):
    id = "hyprpaper"

    def is_available(self, env: EnvironmentInfo) -> bool:
        return env.hyprland and has_command(env, "hyprctl")

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        preload_result = run_command(["hyprctl", "hyprpaper", "preload", str(image_path)])
        if not preload_result.ok:
            return preload_result

        # Empty monitor selector applies to all monitors.
        return run_command(
            ["hyprctl", "hyprpaper", "wallpaper", f",{image_path}"]
        )
