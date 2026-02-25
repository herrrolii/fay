from __future__ import annotations

from pathlib import Path
import shlex

from fay.backends.base import ApplyContext, CommandBackend, effective_mode, run_command
from fay.env import has_command
from fay.models import BackendResult, EnvironmentInfo, WallpaperState


FEH_MODE_MAP = {
    "fill": "bg-fill",
    "fit": "bg-max",
    "center": "bg-center",
    "tile": "bg-tile",
}


class FehBackend(CommandBackend):
    id = "feh"

    def is_available(self, env: EnvironmentInfo) -> bool:
        if not has_command(env, "feh"):
            return False
        return env.is_x11

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        resolved = effective_mode(mode, image_path, context)
        feh_mode = FEH_MODE_MAP.get(resolved, "bg-fill")

        command = ["feh"]
        if not persist_now:
            command.append("--no-fehbg")
        command.extend([f"--{feh_mode}", str(image_path)])
        return run_command(command)

    def capture_current(self) -> WallpaperState | None:
        fehbg_path = Path("~/.fehbg").expanduser()
        if not fehbg_path.exists():
            return None

        try:
            lines = fehbg_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return None

        last_parts: list[str] | None = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                parts = shlex.split(stripped)
            except ValueError:
                continue
            if parts and Path(parts[0]).name == "feh":
                last_parts = parts

        if not last_parts:
            return None

        images = [Path(arg).expanduser() for arg in last_parts[1:] if not arg.startswith("-")]
        if not images:
            return None

        raw_mode = "fill"
        for arg in last_parts:
            if not arg.startswith("--bg-"):
                continue
            value = arg[2:]
            if value == "bg-max":
                raw_mode = "fit"
            elif value == "bg-center":
                raw_mode = "center"
            elif value == "bg-tile":
                raw_mode = "tile"
            elif value in {"bg-fill", "bg-scale"}:
                raw_mode = "fill"

        return WallpaperState(
            backend_id=self.id,
            image_path=str(images[-1]),
            mode=raw_mode,
            backend_state={"command": last_parts},
        )

    def restore(self, state: WallpaperState, context: ApplyContext) -> BackendResult:
        command = state.backend_state.get("command") if state.backend_state else None
        if isinstance(command, list) and command:
            return run_command([str(item) for item in command])
        return super().restore(state, context)
