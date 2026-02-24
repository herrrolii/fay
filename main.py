import argparse
from collections import OrderedDict
from collections import deque
import fcntl
import hashlib
import os
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any, cast

import pyray as rl

WINDOW_TITLE = "fay wallpaper picker"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
FEH_MODES = ("auto", "bg-fill", "bg-center", "bg-max", "bg-scale", "bg-tile")
FEH_AUTO_ASPECT_RATIO_FACTOR = 1.75
FEH_AUTO_SMALL_RATIO_FACTOR = 0.78
FEH_AUTO_SQUAREISH_MIN_RATIO = 0.8
FEH_AUTO_SQUAREISH_MAX_RATIO = 1.25
HOLD_REPEAT_DELAY = 0.22
HOLD_REPEAT_INTERVAL = 0.055
DEFAULT_PREVIEW_DELAY = 0.18
THUMB_MAX_WIDTH = 720
THUMB_MAX_HEIGHT = 480
THUMB_BUILD_BUDGET_IDLE = 1
THUMB_CACHE_VERSION = "v1"


def _rl_int(name: str) -> int:
    return cast(int, getattr(rl, name))


FLAG_WINDOW_UNDECORATED = _rl_int("FLAG_WINDOW_UNDECORATED")
FLAG_WINDOW_TOPMOST = _rl_int("FLAG_WINDOW_TOPMOST")
FLAG_WINDOW_TRANSPARENT = _rl_int("FLAG_WINDOW_TRANSPARENT")
KEY_NULL = _rl_int("KEY_NULL")
KEY_ESCAPE = _rl_int("KEY_ESCAPE")
KEY_Q = _rl_int("KEY_Q")
KEY_R = _rl_int("KEY_R")
KEY_RIGHT = _rl_int("KEY_RIGHT")
KEY_D = _rl_int("KEY_D")
KEY_L = _rl_int("KEY_L")
KEY_LEFT = _rl_int("KEY_LEFT")
KEY_A = _rl_int("KEY_A")
KEY_H = _rl_int("KEY_H")
KEY_ENTER = _rl_int("KEY_ENTER")
KEY_KP_ENTER = _rl_int("KEY_KP_ENTER")
DEFAULT_VISIBLE_CARDS = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bottom overlay wallpaper picker using raylib + feh."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Directory containing wallpaper images (defaults to current working directory).",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=list(FEH_MODES),
        help="Wallpaper mode. 'auto' picks bg-fill or bg-center based on image size/orientation.",
    )
    parser.add_argument("--width", type=int, default=1000, help="Overlay width in pixels.")
    parser.add_argument(
        "--height", type=int, default=260, help="Overlay height in pixels."
    )
    parser.add_argument(
        "--margin",
        type=int,
        default=20,
        help="Distance from bottom of the screen in pixels.",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=None,
        help="Monitor index (defaults to current monitor).",
    )
    parser.add_argument(
        "--visible-cards",
        type=int,
        default=DEFAULT_VISIBLE_CARDS,
        help="Maximum cards shown at once (even values are reduced by one).",
    )
    parser.add_argument(
        "--auto-preview",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply wallpaper while browsing after a short delay (enabled by default).",
    )
    parser.add_argument(
        "--preview-delay",
        type=float,
        default=DEFAULT_PREVIEW_DELAY,
        help="Seconds to stay on a card before auto-preview applies (used with --auto-preview).",
    )
    return parser.parse_args()


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


def get_runtime_dir() -> Path:
    xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        path = Path(xdg_runtime_dir)
        if path.exists() and path.is_dir():
            return path
    return Path("/tmp")


def get_lock_path() -> Path:
    lock_name = f"fay-{os.getuid()}.lock"
    return get_runtime_dir() / lock_name


def acquire_single_instance_lock(lock_path: Path) -> Any | None:
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(lock_path, "w", encoding="utf-8")
    except OSError:
        return None

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None

    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
    except OSError:
        pass

    return lock_file


def focus_existing_window(window_title: str) -> bool:
    commands = [
        ["xdotool", "search", "--name", window_title, "windowactivate"],
        ["wmctrl", "-a", window_title],
    ]

    for command in commands:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            continue
        if result.returncode == 0:
            return True
    return False


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


def resolve_feh_mode(
    image_path: Path,
    mode: str,
    screen_width: int,
    screen_height: int,
    image_size_cache: dict[str, tuple[int, int]],
    thumbnail_store: ThumbnailStore,
    allow_probe: bool = True,
) -> str:
    if mode != "auto":
        return mode

    cache_key = str(image_path)
    image_size = image_size_cache.get(cache_key)
    if image_size is None:
        image_size = thumbnail_store.get_cached_dimensions(image_path)
        if image_size is not None:
            image_size_cache[cache_key] = image_size

    if image_size is None and allow_probe:
        image = cast(Any, rl.load_image(str(image_path)))
        try:
            width = int(getattr(image, "width", 0))
            height = int(getattr(image, "height", 0))
        finally:
            rl.unload_image(cast(Any, image))

        if width <= 0 or height <= 0:
            return "bg-fill"
        image_size = (width, height)
        image_size_cache[cache_key] = image_size
        thumbnail_store.remember_dimensions(image_path, width, height)

    if image_size is None:
        return "bg-fill"

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return "bg-fill"
    if screen_width <= 0 or screen_height <= 0:
        return "bg-fill"

    width_ratio = image_width / screen_width
    height_ratio = image_height / screen_height

    screen_landscape = screen_width >= screen_height
    image_landscape = image_width >= image_height
    orientation_mismatch = screen_landscape != image_landscape

    screen_ratio = screen_width / screen_height
    image_ratio = image_width / image_height
    ratio_factor = max(screen_ratio / image_ratio, image_ratio / screen_ratio)
    strong_aspect_mismatch = ratio_factor >= FEH_AUTO_ASPECT_RATIO_FACTOR
    squareish = FEH_AUTO_SQUAREISH_MIN_RATIO <= image_ratio <= FEH_AUTO_SQUAREISH_MAX_RATIO
    larger_than_screen = width_ratio >= 1.0 and height_ratio >= 1.0

    # Very small images (in both dimensions) should not be stretched.
    if (
        width_ratio <= FEH_AUTO_SMALL_RATIO_FACTOR
        and height_ratio <= FEH_AUTO_SMALL_RATIO_FACTOR
    ):
        return "bg-center"

    # Large square-ish images on wide/tall screens usually look best fit-to-screen.
    if squareish and larger_than_screen:
        return "bg-max"

    if orientation_mismatch or strong_aspect_mismatch:
        return "bg-center"

    return "bg-fill"


def build_wallpaper_command(
    image_path: Path,
    mode: str,
    screen_width: int,
    screen_height: int,
    image_size_cache: dict[str, tuple[int, int]],
    thumbnail_store: ThumbnailStore,
    allow_probe: bool = True,
    persist_selection: bool = True,
) -> list[str]:
    effective_mode = resolve_feh_mode(
        image_path,
        mode,
        screen_width,
        screen_height,
        image_size_cache,
        thumbnail_store,
        allow_probe,
    )
    command = ["feh"]
    if not persist_selection:
        command.append("--no-fehbg")
    command.extend([f"--{effective_mode}", str(image_path)])
    return command


class AsyncFehRunner:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending_command: list[str] | None = None
        self._running = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="fay-feh-runner", daemon=False
        )
        self._thread.start()

    def submit(self, command: list[str]) -> None:
        with self._condition:
            if self._closed:
                return
            self._pending_command = list(command)
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending_command is None and not self._closed:
                    self._condition.wait()
                if self._closed and self._pending_command is None:
                    return
                command = self._pending_command
                if command is None:
                    continue
                self._pending_command = None
                self._running = True

            try:
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except OSError:
                pass
            finally:
                with self._condition:
                    self._running = False
                    self._condition.notify_all()

    def flush(self) -> None:
        with self._condition:
            while self._pending_command is not None or self._running:
                self._condition.wait()

    def shutdown(self, flush_pending: bool = True) -> None:
        if flush_pending:
            self.flush()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join()


def get_startup_feh_command() -> list[str] | None:
    fehbg_path = Path("~/.fehbg").expanduser()
    if not fehbg_path.exists():
        return None

    try:
        lines = fehbg_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    last_command: list[str] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parts = shlex.split(stripped)
        except ValueError:
            continue
        if parts and Path(parts[0]).name == "feh":
            last_command = parts
    return last_command


def extract_image_paths_from_feh(command: list[str]) -> list[Path]:
    return [Path(arg).expanduser() for arg in command[1:] if not arg.startswith("-")]


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def sample_curve(x: float, points: list[tuple[float, float]]) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for idx in range(1, len(points)):
        x0, y0 = points[idx - 1]
        x1, y1 = points[idx]
        if x <= x1:
            if x1 == x0:
                return y1
            t = (x - x0) / (x1 - x0)
            return lerp(y0, y1, t)
    return points[-1][1]


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


def place_window_at_bottom(width: int, height: int, margin: int, monitor: int) -> None:
    monitor_pos = rl.get_monitor_position(monitor)
    monitor_x = int(monitor_pos.x)
    monitor_y = int(monitor_pos.y)
    monitor_width = rl.get_monitor_width(monitor)
    monitor_height = rl.get_monitor_height(monitor)

    x = monitor_x + (monitor_width - width) // 2
    y = monitor_y + monitor_height - height - margin
    rl.set_window_position(max(monitor_x, x), max(monitor_y, y))


def fit_texture_rect(texture: Any, box: rl.Rectangle) -> rl.Rectangle:
    if texture.width <= 0 or texture.height <= 0:
        return box

    scale = min(box.width / texture.width, box.height / texture.height)
    width = texture.width * scale
    height = texture.height * scale
    x = box.x + (box.width - width) * 0.5
    y = box.y + (box.height - height) * 0.5
    return rl.Rectangle(x, y, width, height)


def draw_preview_card(
    cache: TextureCache,
    image_path: Path,
    card: rl.Rectangle,
    tint: rl.Color,
    selected: bool,
) -> None:
    shadow = rl.Rectangle(card.x + 4, card.y + 8, card.width, card.height)
    rl.draw_rectangle_rounded(shadow, 0.07, 8, rl.Color(0, 0, 0, 130))

    frame_color = rl.Color(245, 245, 245, 245) if selected else rl.Color(205, 205, 205, 215)
    rl.draw_rectangle_rounded(card, 0.07, 8, frame_color)

    inner = rl.Rectangle(card.x + 5, card.y + 5, card.width - 10, card.height - 10)
    rl.draw_rectangle_rounded(inner, 0.06, 8, rl.Color(10, 12, 15, tint.a))

    texture = cache.get(image_path)
    if texture is None:
        rl.draw_rectangle_rounded(inner, 0.06, 8, rl.Color(50, 55, 66, tint.a))
        rl.draw_line(
            int(inner.x + 10),
            int(inner.y + 10),
            int(inner.x + inner.width - 10),
            int(inner.y + inner.height - 10),
            rl.Color(180, 180, 180, 200),
        )
        rl.draw_line(
            int(inner.x + 10),
            int(inner.y + inner.height - 10),
            int(inner.x + inner.width - 10),
            int(inner.y + 10),
            rl.Color(180, 180, 180, 200),
        )
        return

    source = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
    destination = fit_texture_rect(texture, inner)
    rl.draw_texture_pro(
        cast(Any, texture),
        source,
        destination,
        rl.Vector2(0, 0),
        0.0,
        tint,
    )


def main() -> int:
    args = parse_args()
    lock_handle = acquire_single_instance_lock(get_lock_path())
    if lock_handle is None:
        focus_existing_window(WINDOW_TITLE)
        return 0

    wallpaper_dir = Path(args.directory).expanduser() if args.directory else Path.cwd()
    max_visible_cards = max(1, args.visible_cards)
    startup_feh_command = get_startup_feh_command()
    feh_runner = AsyncFehRunner()

    images = list_images(wallpaper_dir)
    selected = 0
    confirmed_selection = False

    if startup_feh_command and images:
        image_lookup = {str(path.resolve()): idx for idx, path in enumerate(images)}
        for startup_image in reversed(extract_image_paths_from_feh(startup_feh_command)):
            key = str(startup_image.resolve())
            found = image_lookup.get(key)
            if found is not None:
                selected = found
                break

    rl.set_config_flags(FLAG_WINDOW_UNDECORATED | FLAG_WINDOW_TOPMOST | FLAG_WINDOW_TRANSPARENT)
    rl.init_window(args.width, args.height, WINDOW_TITLE)
    rl.set_target_fps(60)
    rl.set_exit_key(KEY_NULL)

    monitor = args.monitor if args.monitor is not None else rl.get_current_monitor()
    monitor_width = rl.get_monitor_width(monitor)
    monitor_height = rl.get_monitor_height(monitor)
    place_window_at_bottom(args.width, args.height, args.margin, monitor)

    thumbnail_store = ThumbnailStore(
        get_thumbnail_cache_dir(), THUMB_MAX_WIDTH, THUMB_MAX_HEIGHT
    )
    cache = TextureCache(thumbnail_store)
    image_size_cache: dict[str, tuple[int, int]] = {}
    transparent = rl.Color(0, 0, 0, 0)
    center_x = args.width * 0.5
    center_y = args.height * 0.52
    animation_offset = 0.0
    depth_points = [(0.0, 1.0), (1.0, 0.76), (2.0, 0.56), (3.0, 0.42)]
    alpha_points = [(0.0, 255.0), (1.0, 205.0), (2.0, 155.0), (3.0, 100.0)]
    gap_points = [
        (0.0, 0.0),
        (1.0, args.width * 0.24),
        (2.0, args.width * 0.4),
        (3.0, args.width * 0.52),
    ]
    held_direction = 0
    hold_elapsed = 0.0
    repeat_elapsed = 0.0
    auto_preview_enabled = args.auto_preview
    preview_delay = max(0.0, args.preview_delay)
    selection_dwell_time = 0.0
    last_auto_preview_index: int | None = None

    while True:
        frame_time = rl.get_frame_time()
        if rl.window_should_close() or rl.is_key_pressed(KEY_ESCAPE) or rl.is_key_pressed(KEY_Q):
            if not confirmed_selection and startup_feh_command:
                feh_runner.submit(startup_feh_command)
            break

        moved = False
        visible_count = 1
        side_count = 0
        if rl.is_key_pressed(KEY_R):
            images = list_images(wallpaper_dir)
            selected = clamp(selected, 0, max(0, len(images) - 1))
            cache.clear()
            image_size_cache.clear()
            selection_dwell_time = 0.0
            last_auto_preview_index = None

        if images:
            previous_selected = selected
            visible_count = min(len(images), max_visible_cards)
            if visible_count % 2 == 0:
                visible_count -= 1
            visible_count = max(1, visible_count)
            side_count = visible_count // 2
            request_side = min(len(images) - 1, side_count + 2)
            for rel in range(-request_side, request_side + 1):
                cache.request(images[(selected + rel) % len(images)])

            slide_delta = 0
            navigation_key_down = False
            moved_from_initial_press = False
            moved_from_repeat = False
            if len(images) > 1:
                right_down = (
                    rl.is_key_down(KEY_RIGHT) or rl.is_key_down(KEY_D) or rl.is_key_down(KEY_L)
                )
                left_down = (
                    rl.is_key_down(KEY_LEFT) or rl.is_key_down(KEY_A) or rl.is_key_down(KEY_H)
                )

                direction_down = 0
                if right_down and not left_down:
                    direction_down = 1
                elif left_down and not right_down:
                    direction_down = -1
                navigation_key_down = direction_down != 0

                if direction_down == 0:
                    held_direction = 0
                    hold_elapsed = 0.0
                    repeat_elapsed = 0.0
                elif direction_down != held_direction:
                    held_direction = direction_down
                    hold_elapsed = 0.0
                    repeat_elapsed = 0.0
                    slide_delta = direction_down
                    moved_from_initial_press = True
                else:
                    hold_elapsed += frame_time
                    if hold_elapsed >= HOLD_REPEAT_DELAY:
                        repeat_elapsed += frame_time
                        while repeat_elapsed >= HOLD_REPEAT_INTERVAL:
                            slide_delta += held_direction
                            repeat_elapsed -= HOLD_REPEAT_INTERVAL
                        if slide_delta != 0:
                            moved_from_repeat = True

            if slide_delta != 0:
                step = 1 if slide_delta > 0 else -1
                for _ in range(abs(slide_delta)):
                    selected = (selected + step) % len(images)
                    animation_offset += float(step)
                moved = True

            if selected != previous_selected:
                selection_dwell_time = 0.0
                last_auto_preview_index = None
            elif navigation_key_down:
                selection_dwell_time = 0.0
            else:
                selection_dwell_time += frame_time

            if rl.is_key_pressed(KEY_ENTER) or rl.is_key_pressed(KEY_KP_ENTER):
                feh_runner.submit(
                    build_wallpaper_command(
                        images[selected],
                        args.mode,
                        monitor_width,
                        monitor_height,
                        image_size_cache,
                        thumbnail_store,
                        True,
                        True,
                    )
                )
                confirmed_selection = True
                break

            if moved:
                prefetch_side = min(len(images) - 1, side_count + 1)
                for rel in range(-prefetch_side, prefetch_side + 1):
                    cache.request(images[(selected + rel) % len(images)])
                animation_offset = max(-3.0, min(3.0, animation_offset))

            if (
                auto_preview_enabled
                and moved
                and moved_from_initial_press
                and not moved_from_repeat
                and abs(slide_delta) == 1
            ):
                feh_runner.submit(
                    build_wallpaper_command(
                        images[selected],
                        args.mode,
                        monitor_width,
                        monitor_height,
                        image_size_cache,
                        thumbnail_store,
                        False,
                        False,
                    )
                )
                last_auto_preview_index = selected

            if (
                auto_preview_enabled
                and not navigation_key_down
                and selection_dwell_time >= preview_delay
                and last_auto_preview_index != selected
            ):
                selected_texture = cache.get(images[selected])
                if selected_texture is not None:
                    feh_runner.submit(
                        build_wallpaper_command(
                            images[selected],
                            args.mode,
                            monitor_width,
                            monitor_height,
                            image_size_cache,
                            thumbnail_store,
                            False,
                            False,
                        )
                    )
                    last_auto_preview_index = selected

            if not navigation_key_down:
                thumbnail_store.process(THUMB_BUILD_BUDGET_IDLE)

            animation_offset = lerp(animation_offset, 0.0, 0.24)
            if abs(animation_offset) < 0.01:
                animation_offset = 0.0
        else:
            held_direction = 0
            hold_elapsed = 0.0
            repeat_elapsed = 0.0
            selection_dwell_time = 0.0
            last_auto_preview_index = None

        rl.begin_drawing()
        rl.clear_background(transparent)

        if images:
            candidate_span = min(len(images) - 1, side_count + 2)
            closest_by_index: dict[int, tuple[float, float]] = {}
            for rel in range(-candidate_span, candidate_span + 1):
                idx = (selected + rel) % len(images)
                pos = rel + animation_offset
                depth = abs(pos)
                prev = closest_by_index.get(idx)
                if prev is None or depth < prev[0]:
                    closest_by_index[idx] = (depth, pos)

            ranked = sorted(
                ((depth, idx, pos) for idx, (depth, pos) in closest_by_index.items()),
                key=lambda item: item[0],
            )
            visible_entries = ranked[:visible_count]

            for _, idx, pos in sorted(visible_entries, key=lambda item: item[0], reverse=True):
                depth = abs(pos)
                scale = sample_curve(depth, depth_points)
                card_w = args.width * 0.35 * scale
                card_h = args.height * 0.78 * scale
                offset_mag = sample_curve(depth, gap_points)
                offset_x = offset_mag * (1 if pos >= 0 else -1)

                card = rl.Rectangle(
                    center_x + offset_x - card_w * 0.5,
                    center_y - card_h * 0.5,
                    card_w,
                    card_h,
                )
                alpha = int(sample_curve(depth, alpha_points))
                tint = rl.Color(255, 255, 255, alpha)
                draw_preview_card(cache, images[idx], card, tint, depth < 0.32)
        rl.end_drawing()

    feh_runner.shutdown(flush_pending=True)
    cache.clear()
    rl.close_window()
    try:
        lock_handle.close()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
