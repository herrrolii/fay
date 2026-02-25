from __future__ import annotations

from pathlib import Path
import subprocess
from urllib.parse import unquote, urlparse

from fay.backends.base import ApplyContext, CommandBackend, effective_mode, run_command
from fay.env import has_command, is_gnome_session
from fay.models import BackendResult, EnvironmentInfo, WallpaperState


GNOME_MODE_MAP = {
    "fill": "zoom",
    "fit": "scaled",
    "center": "centered",
    "tile": "wallpaper",
}


class GnomeBackend(CommandBackend):
    id = "gnome"

    def is_available(self, env: EnvironmentInfo) -> bool:
        return has_command(env, "gsettings") and is_gnome_session(env)

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        resolved = effective_mode(mode, image_path, context)
        gnome_mode = GNOME_MODE_MAP.get(resolved, "zoom")
        uri = image_path.resolve().as_uri()

        commands = [
            [
                "gsettings",
                "set",
                "org.gnome.desktop.background",
                "picture-options",
                gnome_mode,
            ],
            [
                "gsettings",
                "set",
                "org.gnome.desktop.background",
                "picture-uri",
                uri,
            ],
            [
                "gsettings",
                "set",
                "org.gnome.desktop.background",
                "picture-uri-dark",
                uri,
            ],
        ]

        for command in commands:
            result = run_command(command)
            if not result.ok:
                return result
        return BackendResult(ok=True)

    def capture_current(self) -> WallpaperState | None:
        uri = _read_gsettings("org.gnome.desktop.background", "picture-uri")
        mode = _read_gsettings("org.gnome.desktop.background", "picture-options")
        if not uri:
            return None
        path = _path_from_uri(uri)
        if path is None:
            return None

        normalized_mode = "fill"
        reverse_mode = {v: k for k, v in GNOME_MODE_MAP.items()}
        if mode in reverse_mode:
            normalized_mode = reverse_mode[mode]

        return WallpaperState(
            backend_id=self.id,
            image_path=str(path),
            mode=normalized_mode,
            backend_state={"picture-options": mode},
        )

    def restore(self, state: WallpaperState, context: ApplyContext) -> BackendResult:
        result = self.apply(state.path, state.mode, context, persist_now=False)
        if not result.ok:
            return result

        picture_options = state.backend_state.get("picture-options")
        if isinstance(picture_options, str) and picture_options:
            return run_command(
                [
                    "gsettings",
                    "set",
                    "org.gnome.desktop.background",
                    "picture-options",
                    picture_options,
                ]
            )
        return result


def _read_gsettings(schema: str, key: str) -> str | None:
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    return value


def _path_from_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    return Path(path)
