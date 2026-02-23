import argparse
from collections import OrderedDict
from collections import deque
import hashlib
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, cast

import pyray as rl

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
FEH_MODES = ("auto", "bg-fill", "bg-center", "bg-max", "bg-scale", "bg-tile")
FEH_AUTO_ASPECT_RATIO_FACTOR = 1.75
HOLD_REPEAT_DELAY = 0.22
HOLD_REPEAT_INTERVAL = 0.055
PREVIEW_APPLY_DELAY = 0.12
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
        default=False,
        help="Apply wallpaper while browsing after a short delay (disabled by default).",
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
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, image_path: Path) -> Path:
        return self.cache_dir / thumbnail_name_for(image_path, self.max_width, self.max_height)

    def request(self, image_path: Path) -> Path:
        thumb_path = self.path_for(image_path)
        key = str(thumb_path)
        if thumb_path.exists():
            return thumb_path
        if key not in self.pending_set and key not in self.failed:
            self.pending.append((image_path, thumb_path))
            self.pending_set.add(key)
        return thumb_path

    def _build_thumbnail(self, image_path: Path, thumb_path: Path) -> bool:
        image = cast(Any, rl.load_image(str(image_path)))
        try:
            width = int(getattr(image, "width", 0))
            height = int(getattr(image, "height", 0))
            if width <= 0 or height <= 0:
                return False

            scale = min(self.max_width / width, self.max_height / height, 1.0)
            if scale < 1.0:
                new_width = max(1, int(width * scale))
                new_height = max(1, int(height * scale))
                rl.image_resize(cast(Any, image), new_width, new_height)

            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            return bool(rl.export_image(cast(Any, image), str(thumb_path)))
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
                continue

            ok = False
            try:
                ok = self._build_thumbnail(image_path, thumb_path)
            except Exception:
                ok = False

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
) -> str:
    if mode != "auto":
        return mode

    cache_key = str(image_path)
    image_size = image_size_cache.get(cache_key)
    if image_size is None:
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

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return "bg-fill"
    if screen_width <= 0 or screen_height <= 0:
        return "bg-fill"

    if image_width < screen_width or image_height < screen_height:
        return "bg-center"

    screen_landscape = screen_width >= screen_height
    image_landscape = image_width >= image_height
    if screen_landscape != image_landscape:
        return "bg-center"

    screen_ratio = screen_width / screen_height
    image_ratio = image_width / image_height
    ratio_factor = max(screen_ratio / image_ratio, image_ratio / screen_ratio)
    if ratio_factor >= FEH_AUTO_ASPECT_RATIO_FACTOR:
        return "bg-center"

    return "bg-fill"


def apply_wallpaper(
    image_path: Path,
    mode: str,
    screen_width: int,
    screen_height: int,
    image_size_cache: dict[str, tuple[int, int]],
) -> tuple[bool, str]:
    effective_mode = resolve_feh_mode(
        image_path, mode, screen_width, screen_height, image_size_cache
    )
    try:
        proc = subprocess.run(
            ["feh", f"--{effective_mode}", str(image_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "feh not found in PATH."

    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "feh failed."
        return False, message
    return True, f"Applied (--{effective_mode}): {image_path.name}"


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
    wallpaper_dir = Path(args.directory).expanduser() if args.directory else Path.cwd()
    max_visible_cards = max(1, args.visible_cards)
    startup_feh_command = get_startup_feh_command()

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
    rl.init_window(args.width, args.height, "fay wallpaper picker")
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
    pending_preview_index: int | None = None
    pending_preview_wait = 0.0

    while True:
        frame_time = rl.get_frame_time()
        if rl.window_should_close() or rl.is_key_pressed(KEY_ESCAPE) or rl.is_key_pressed(KEY_Q):
            if not confirmed_selection and startup_feh_command:
                try:
                    subprocess.run(startup_feh_command, check=False)
                except OSError:
                    pass
            break

        moved = False
        visible_count = 1
        side_count = 0
        if rl.is_key_pressed(KEY_R):
            images = list_images(wallpaper_dir)
            selected = clamp(selected, 0, max(0, len(images) - 1))
            cache.clear()
            image_size_cache.clear()
            if not auto_preview_enabled or not images:
                pending_preview_index = None
                pending_preview_wait = 0.0
            elif pending_preview_index is not None:
                pending_preview_index = clamp(pending_preview_index, 0, len(images) - 1)

        if images:
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
                else:
                    hold_elapsed += frame_time
                    if hold_elapsed >= HOLD_REPEAT_DELAY:
                        repeat_elapsed += frame_time
                        while repeat_elapsed >= HOLD_REPEAT_INTERVAL:
                            slide_delta += held_direction
                            repeat_elapsed -= HOLD_REPEAT_INTERVAL

            if slide_delta != 0:
                step = 1 if slide_delta > 0 else -1
                for _ in range(abs(slide_delta)):
                    selected = (selected + step) % len(images)
                    animation_offset += float(step)
                moved = True
                if auto_preview_enabled:
                    pending_preview_index = selected
                    pending_preview_wait = PREVIEW_APPLY_DELAY
                else:
                    pending_preview_index = None
                    pending_preview_wait = 0.0
            if rl.is_key_pressed(KEY_ENTER) or rl.is_key_pressed(KEY_KP_ENTER):
                pending_preview_index = None
                pending_preview_wait = 0.0
                apply_wallpaper(
                    images[selected],
                    args.mode,
                    monitor_width,
                    monitor_height,
                    image_size_cache,
                )
                confirmed_selection = True
                break

            if moved:
                prefetch_side = min(len(images) - 1, side_count + 1)
                for rel in range(-prefetch_side, prefetch_side + 1):
                    cache.request(images[(selected + rel) % len(images)])
                animation_offset = max(-3.0, min(3.0, animation_offset))

            if auto_preview_enabled and pending_preview_index is not None:
                if pending_preview_index < 0 or pending_preview_index >= len(images):
                    pending_preview_index = None
                    pending_preview_wait = 0.0
                else:
                    pending_preview_wait -= frame_time
                    if pending_preview_wait <= 0.0:
                        apply_wallpaper(
                            images[pending_preview_index],
                            args.mode,
                            monitor_width,
                            monitor_height,
                            image_size_cache,
                        )
                        pending_preview_index = None
                        pending_preview_wait = 0.0

            if not navigation_key_down:
                thumbnail_store.process(THUMB_BUILD_BUDGET_IDLE)

            animation_offset = lerp(animation_offset, 0.0, 0.24)
            if abs(animation_offset) < 0.01:
                animation_offset = 0.0
        else:
            held_direction = 0
            hold_elapsed = 0.0
            repeat_elapsed = 0.0
            pending_preview_index = None
            pending_preview_wait = 0.0

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

    cache.clear()
    rl.close_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
