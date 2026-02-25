from __future__ import annotations

from pathlib import Path

from fay.backends.base import ApplyContext, CommandBackend, effective_mode, run_command
from fay.env import has_command
from fay.models import BackendResult, EnvironmentInfo


SWAYBG_MODE_MAP = {
    "fill": "fill",
    "fit": "fit",
    "center": "center",
    "tile": "tile",
}


class SwaybgBackend(CommandBackend):
    id = "swaybg"

    def is_available(self, env: EnvironmentInfo) -> bool:
        return env.sway and has_command(env, "swaymsg")

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        resolved = effective_mode(mode, image_path, context)
        sway_mode = SWAYBG_MODE_MAP.get(resolved, "fill")
        return run_command(
            [
                "swaymsg",
                "output",
                "*",
                "bg",
                str(image_path),
                sway_mode,
            ]
        )
