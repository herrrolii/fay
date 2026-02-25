from __future__ import annotations

from collections import OrderedDict
from collections import deque
import hashlib
import os
from pathlib import Path
from typing import Any, cast

import pyray as rl

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
THUMB_MAX_WIDTH = 720
THUMB_MAX_HEIGHT = 480
THUMB_BUILD_BUDGET_IDLE = 1
THUMB_CACHE_VERSION = "v1"


def list_images(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(
        [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda path: path.name.lower(),
    )


def get_thumbnail_cache_dir() -> Path:
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        base_dir = Path(xdg_cache_home).expanduser()
    else:
        base_dir = Path("~/.cache").expanduser()
    return base_dir / "fay" / "thumbnails"


def thumbnail_name_for(image_path: Path, max_width: int, max_height: int) -> str:
    try:
        resolved = str(image_path.resolve())
    except OSError:
        resolved = str(image_path)

    stat_size = 0
    stat_mtime_ns = 0
    try:
        stat_result = image_path.stat()
        stat_size = int(stat_result.st_size)
        stat_mtime_ns = int(stat_result.st_mtime_ns)
    except OSError:
        pass

    key_source = (
        f"{resolved}|{stat_size}|{stat_mtime_ns}|{max_width}x{max_height}|{THUMB_CACHE_VERSION}"
    )
    digest = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
    return f"{digest}.png"


class ThumbnailStore:
    def __init__(self, cache_dir: Path, max_width: int, max_height: int) -> None:
        self.cache_dir = cache_dir
        self.max_width = max_width
        self.max_height = max_height
        self.pending: deque[tuple[Path, Path]] = deque()
        self.pending_set: set[str] = set()
        self.failed: set[str] = set()
        self.dimensions_cache: dict[str, tuple[int, int]] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, image_path: Path) -> Path:
        return self.cache_dir / thumbnail_name_for(image_path, self.max_width, self.max_height)

    def _dimensions_path_for(self, thumb_path: Path) -> Path:
        return thumb_path.with_name(f"{thumb_path.name}.dim")

    def _read_dimensions_file(self, path: Path) -> tuple[int, int] | None:
        try:
            parts = path.read_text(encoding="utf-8").strip().split()
        except OSError:
            return None
        if len(parts) != 2:
            return None
        try:
            width = int(parts[0])
            height = int(parts[1])
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    def _write_dimensions_file(self, path: Path, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        try:
            path.write_text(f"{width} {height}\n", encoding="utf-8")
        except OSError:
            pass

    def get_cached_dimensions(self, image_path: Path) -> tuple[int, int] | None:
        key = str(image_path)
        cached = self.dimensions_cache.get(key)
        if cached is not None:
            return cached

        thumb_path = self.path_for(image_path)
        dim_path = self._dimensions_path_for(thumb_path)
        dims = self._read_dimensions_file(dim_path)
        if dims is not None:
            self.dimensions_cache[key] = dims
        return dims

    def remember_dimensions(self, image_path: Path, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        key = str(image_path)
        self.dimensions_cache[key] = (width, height)
        thumb_path = self.path_for(image_path)
        dim_path = self._dimensions_path_for(thumb_path)
        self._write_dimensions_file(dim_path, width, height)

    def request(self, image_path: Path) -> Path:
        thumb_path = self.path_for(image_path)
        key = str(thumb_path)
        dims = self.get_cached_dimensions(image_path)
        if thumb_path.exists():
            if dims is None and key not in self.pending_set and key not in self.failed:
                self.pending.append((image_path, thumb_path))
                self.pending_set.add(key)
            return thumb_path
        if key not in self.pending_set and key not in self.failed:
            self.pending.append((image_path, thumb_path))
            self.pending_set.add(key)
        return thumb_path

    def _probe_dimensions(self, image_path: Path) -> tuple[int, int] | None:
        image = cast(Any, rl.load_image(str(image_path)))
        try:
            width = int(getattr(image, "width", 0))
            height = int(getattr(image, "height", 0))
            if width <= 0 or height <= 0:
                return None
            return width, height
        finally:
            rl.unload_image(cast(Any, image))

    def _build_thumbnail(
        self, image_path: Path, thumb_path: Path
    ) -> tuple[bool, tuple[int, int] | None]:
        image = cast(Any, rl.load_image(str(image_path)))
        try:
            width = int(getattr(image, "width", 0))
            height = int(getattr(image, "height", 0))
            if width <= 0 or height <= 0:
                return False, None

            scale = min(self.max_width / width, self.max_height / height, 1.0)
            if scale < 1.0:
                new_width = max(1, int(width * scale))
                new_height = max(1, int(height * scale))
                rl.image_resize(cast(Any, image), new_width, new_height)

            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            exported = bool(rl.export_image(cast(Any, image), str(thumb_path)))
            if not exported:
                return False, None
            return True, (width, height)
        finally:
            rl.unload_image(cast(Any, image))

    def process(self, max_jobs: int) -> None:
        jobs_done = 0
        while self.pending and jobs_done < max_jobs:
            image_path, thumb_path = self.pending.popleft()
            key = str(thumb_path)
            self.pending_set.discard(key)
            jobs_done += 1

            if thumb_path.exists():
                dims = self.get_cached_dimensions(image_path)
                if dims is None:
                    dims = self._probe_dimensions(image_path)
                    if dims is not None:
                        self.remember_dimensions(image_path, dims[0], dims[1])
                continue

            ok = False
            dimensions: tuple[int, int] | None = None
            try:
                ok, dimensions = self._build_thumbnail(image_path, thumb_path)
            except Exception:
                ok = False

            if ok and dimensions is not None:
                self.remember_dimensions(image_path, dimensions[0], dimensions[1])

            if not ok:
                self.failed.add(key)
                try:
                    thumb_path.unlink()
                except OSError:
                    pass


class TextureCache:
    def __init__(self, thumbnail_store: ThumbnailStore, max_items: int = 24) -> None:
        self.thumbnail_store = thumbnail_store
        self.max_items = max_items
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.failed: set[str] = set()

    def get(self, image_path: Path) -> Any | None:
        thumb_path = self.thumbnail_store.request(image_path)
        key = str(thumb_path)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key in self.failed:
            return None
        if not thumb_path.exists():
            return None

        texture = cast(Any, rl.load_texture(str(thumb_path)))
        if texture.id == 0:
            self.failed.add(key)
            return None

        self.cache[key] = texture
        if len(self.cache) > self.max_items:
            _, oldest = self.cache.popitem(last=False)
            if oldest.id != 0:
                rl.unload_texture(cast(Any, oldest))
        return texture

    def request(self, image_path: Path) -> None:
        self.thumbnail_store.request(image_path)

    def clear(self) -> None:
        for texture in self.cache.values():
            if texture.id != 0:
                rl.unload_texture(cast(Any, texture))
        self.cache.clear()
        self.failed.clear()
