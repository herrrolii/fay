from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from fay.backends.base import ApplyContext, CommandBackend, effective_mode, run_command
from fay.env import has_command
from fay.models import BackendResult, EnvironmentInfo


SWWW_MODE_MAP = {
    "fill": "crop",
    "fit": "fit",
    "center": "no",
    "tile": "no",
}


class SwwwBackend(CommandBackend):
    def __init__(self, binary: str = "swww") -> None:
        self.binary = binary
        self.id = "swww" if binary == "swww" else "awww"

    def is_available(self, env: EnvironmentInfo) -> bool:
        return env.is_wayland and has_command(env, self.binary)

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        init_result = self._ensure_daemon()
        if not init_result.ok:
            return init_result

        resolved = effective_mode(mode, image_path, context)
        resize_mode = SWWW_MODE_MAP.get(resolved, "crop")
        return run_command(
            [self.binary, "img", str(image_path), "--resize", resize_mode]
        )

    def _ensure_daemon(self) -> BackendResult:
        try:
            query = subprocess.run(
                [self.binary, "query"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            return BackendResult(ok=False, error=str(exc))

        if query.returncode == 0:
            return BackendResult(ok=True)

        init_result = run_command([self.binary, "init"])
        if init_result.ok:
            return init_result

        daemon = "swww-daemon"
        if self.binary == "swww" and shutil.which(daemon):
            daemon_result = run_command([daemon])
            if daemon_result.ok:
                return BackendResult(ok=True)

        return init_result
