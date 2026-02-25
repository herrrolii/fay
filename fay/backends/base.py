from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Protocol, cast

import pyray as rl

from fay.models import BackendResult, EnvironmentInfo, WallpaperState

AUTO_ASPECT_RATIO_FACTOR = 1.75
AUTO_SMALL_RATIO_FACTOR = 0.78
AUTO_SQUAREISH_MIN_RATIO = 0.8
AUTO_SQUAREISH_MAX_RATIO = 1.25


@dataclass(frozen=True)
class ApplyContext:
    screen_width: int
    screen_height: int
    image_size_cache: dict[str, tuple[int, int]]


class WallpaperBackend(Protocol):
    id: str

    def is_available(self, env: EnvironmentInfo) -> bool: ...

    def supports_preview(self) -> bool: ...

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult: ...

    def preview(self, image_path: Path, mode: str, context: ApplyContext) -> BackendResult: ...

    def capture_current(self) -> WallpaperState | None: ...

    def restore(self, state: WallpaperState, context: ApplyContext) -> BackendResult: ...


class CommandBackend:
    id = "base"

    def is_available(self, env: EnvironmentInfo) -> bool:
        return False

    def supports_preview(self) -> bool:
        return True

    def apply(
        self, image_path: Path, mode: str, context: ApplyContext, persist_now: bool
    ) -> BackendResult:
        raise NotImplementedError

    def preview(self, image_path: Path, mode: str, context: ApplyContext) -> BackendResult:
        return self.apply(image_path, mode, context, persist_now=False)

    def capture_current(self) -> WallpaperState | None:
        return None

    def restore(self, state: WallpaperState, context: ApplyContext) -> BackendResult:
        image = state.path
        if not image.exists():
            return BackendResult(ok=False, error=f"Wallpaper not found: {image}")
        return self.apply(image, state.mode, context, persist_now=False)


class UnsupportedModeError(RuntimeError):
    pass


def run_command(command: list[str]) -> BackendResult:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        return BackendResult(ok=False, error=str(exc))

    if result.returncode != 0:
        return BackendResult(
            ok=False,
            error=f"Command failed with exit code {result.returncode}: {' '.join(command)}",
        )
    return BackendResult(ok=True)


def probe_image_size(
    image_path: Path, image_size_cache: dict[str, tuple[int, int]]
) -> tuple[int, int] | None:
    cache_key = str(image_path)
    cached = image_size_cache.get(cache_key)
    if cached is not None:
        return cached

    image = cast(Any, rl.load_image(str(image_path)))
    try:
        width = int(getattr(image, "width", 0))
        height = int(getattr(image, "height", 0))
    finally:
        rl.unload_image(cast(Any, image))

    if width <= 0 or height <= 0:
        return None

    size = (width, height)
    image_size_cache[cache_key] = size
    return size


def resolve_auto_mode(
    image_size: tuple[int, int] | None,
    screen_width: int,
    screen_height: int,
) -> str:
    if image_size is None:
        return "fill"
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return "fill"
    if screen_width <= 0 or screen_height <= 0:
        return "fill"

    width_ratio = image_width / screen_width
    height_ratio = image_height / screen_height

    screen_landscape = screen_width >= screen_height
    image_landscape = image_width >= image_height
    orientation_mismatch = screen_landscape != image_landscape

    screen_ratio = screen_width / screen_height
    image_ratio = image_width / image_height
    ratio_factor = max(screen_ratio / image_ratio, image_ratio / screen_ratio)
    strong_aspect_mismatch = ratio_factor >= AUTO_ASPECT_RATIO_FACTOR
    squareish = AUTO_SQUAREISH_MIN_RATIO <= image_ratio <= AUTO_SQUAREISH_MAX_RATIO
    larger_than_screen = width_ratio >= 1.0 and height_ratio >= 1.0

    if (
        width_ratio <= AUTO_SMALL_RATIO_FACTOR
        and height_ratio <= AUTO_SMALL_RATIO_FACTOR
    ):
        return "center"

    if squareish and larger_than_screen:
        return "fit"

    if orientation_mismatch or strong_aspect_mismatch:
        return "center"

    return "fill"


def effective_mode(
    requested_mode: str,
    image_path: Path,
    context: ApplyContext,
) -> str:
    if requested_mode != "auto":
        return requested_mode
    size = probe_image_size(image_path, context.image_size_cache)
    return resolve_auto_mode(size, context.screen_width, context.screen_height)
