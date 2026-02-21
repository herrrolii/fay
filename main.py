import argparse
from collections import OrderedDict
import subprocess
from pathlib import Path

from pyray import *

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bottom overlay wallpaper picker using raylib + feh."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="~/.config/rice/current/theme/wallpapers",
        help="Directory containing wallpaper images.",
    )
    parser.add_argument(
        "--mode",
        default="bg-fill",
        choices=["bg-fill", "bg-center", "bg-max", "bg-scale", "bg-tile"],
        help="feh background mode.",
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


def apply_wallpaper(image_path: Path, mode: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["feh", f"--{mode}", str(image_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "feh not found in PATH."

    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "feh failed."
        return False, message
    return True, f"Applied: {image_path.name}"


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


class TextureCache:
    def __init__(self, max_items: int = 24) -> None:
        self.max_items = max_items
        self.cache: OrderedDict[str, object] = OrderedDict()
        self.failed: set[str] = set()

    def get(self, image_path: Path):
        key = str(image_path)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key in self.failed:
            return None

        texture = load_texture(key)
        if texture.id == 0:
            self.failed.add(key)
            return None

        self.cache[key] = texture
        if len(self.cache) > self.max_items:
            _, oldest = self.cache.popitem(last=False)
            if oldest.id != 0:
                unload_texture(oldest)
        return texture

    def clear(self) -> None:
        for texture in self.cache.values():
            if texture.id != 0:
                unload_texture(texture)
        self.cache.clear()
        self.failed.clear()


def place_window_at_bottom(width: int, height: int, margin: int, monitor: int) -> None:
    monitor_pos = get_monitor_position(monitor)
    monitor_x = int(monitor_pos.x)
    monitor_y = int(monitor_pos.y)
    monitor_width = get_monitor_width(monitor)
    monitor_height = get_monitor_height(monitor)

    x = monitor_x + (monitor_width - width) // 2
    y = monitor_y + monitor_height - height - margin
    set_window_position(max(monitor_x, x), max(monitor_y, y))


def fit_texture_rect(texture, box: Rectangle) -> Rectangle:
    if texture.width <= 0 or texture.height <= 0:
        return box

    scale = min(box.width / texture.width, box.height / texture.height)
    width = texture.width * scale
    height = texture.height * scale
    x = box.x + (box.width - width) * 0.5
    y = box.y + (box.height - height) * 0.5
    return Rectangle(x, y, width, height)


def draw_preview_card(
    cache: TextureCache,
    image_path: Path,
    card: Rectangle,
    tint: Color,
    selected: bool,
) -> None:
    shadow = Rectangle(card.x + 4, card.y + 8, card.width, card.height)
    draw_rectangle_rounded(shadow, 0.07, 8, Color(0, 0, 0, 130))

    frame_color = Color(245, 245, 245, 245) if selected else Color(205, 205, 205, 215)
    draw_rectangle_rounded(card, 0.07, 8, frame_color)

    inner = Rectangle(card.x + 5, card.y + 5, card.width - 10, card.height - 10)
    draw_rectangle_rounded(inner, 0.06, 8, Color(10, 12, 15, tint.a))

    texture = cache.get(image_path)
    if texture is None:
        draw_rectangle_rounded(inner, 0.06, 8, Color(50, 55, 66, tint.a))
        draw_line(
            int(inner.x + 10),
            int(inner.y + 10),
            int(inner.x + inner.width - 10),
            int(inner.y + inner.height - 10),
            Color(180, 180, 180, 200),
        )
        draw_line(
            int(inner.x + 10),
            int(inner.y + inner.height - 10),
            int(inner.x + inner.width - 10),
            int(inner.y + 10),
            Color(180, 180, 180, 200),
        )
        return

    source = Rectangle(0, 0, float(texture.width), float(texture.height))
    destination = fit_texture_rect(texture, inner)
    draw_texture_pro(
        texture,
        source,
        destination,
        Vector2(0, 0),
        0.0,
        tint,
    )


def main() -> int:
    args = parse_args()
    wallpaper_dir = Path(args.directory).expanduser()

    images = list_images(wallpaper_dir)
    selected = 0
    status = ""
    status_color = LIGHTGRAY
    status_frames = 0

    if not wallpaper_dir.exists() or not wallpaper_dir.is_dir():
        status = f"Directory not found: {wallpaper_dir}"
        status_color = ORANGE
        status_frames = 1000000

    set_config_flags(FLAG_WINDOW_UNDECORATED | FLAG_WINDOW_TOPMOST)
    init_window(args.width, args.height, "fay wallpaper picker")
    set_target_fps(60)
    set_exit_key(KEY_NULL)

    monitor = args.monitor if args.monitor is not None else get_current_monitor()
    place_window_at_bottom(args.width, args.height, args.margin, monitor)

    cache = TextureCache()
    background_color = Color(16, 18, 22, 255)
    panel_color = Color(24, 28, 35, 255)
    panel = Rectangle(0, 0, float(args.width), float(args.height))
    center_x = args.width * 0.5
    center_y = args.height * 0.52

    while True:
        if window_should_close() or is_key_pressed(KEY_ESCAPE) or is_key_pressed(KEY_Q):
            break

        moved = False
        if is_key_pressed(KEY_R):
            images = list_images(wallpaper_dir)
            selected = clamp(selected, 0, max(0, len(images) - 1))
            status = ""
            status_frames = 0
            cache.clear()

        if images:
            if (
                is_key_pressed(KEY_RIGHT)
                or is_key_pressed(KEY_D)
                or is_key_pressed(KEY_L)
            ):
                selected = min(selected + 1, len(images) - 1)
                moved = True
            if (
                is_key_pressed(KEY_LEFT)
                or is_key_pressed(KEY_A)
                or is_key_pressed(KEY_H)
            ):
                selected = max(selected - 1, 0)
                moved = True

            if (
                is_key_pressed(KEY_ENTER)
                or is_key_pressed(KEY_KP_ENTER)
                or is_key_pressed(KEY_SPACE)
            ):
                ok, message = apply_wallpaper(images[selected], args.mode)
                if ok:
                    status = ""
                    status_frames = 0
                else:
                    status = message
                    status_color = RED
                    status_frames = 150

            if moved:
                cache.get(images[selected])
                if selected - 1 >= 0:
                    cache.get(images[selected - 1])
                if selected + 1 < len(images):
                    cache.get(images[selected + 1])

        begin_drawing()
        clear_background(background_color)
        draw_rectangle_rounded(panel, 0.06, 10, panel_color)
        draw_rectangle_lines_ex(panel, 1.0, Color(120, 130, 145, 180))

        if not images:
            draw_text("No images found in directory.", 24, args.height // 2 - 12, 24, ORANGE)
        else:
            scales = {0: 1.0, 1: 0.76, 2: 0.56}
            alphas = {0: 255, 1: 205, 2: 155}
            gaps = {0: 0.0, 1: args.width * 0.24, 2: args.width * 0.4}
            order = [-2, 2, -1, 1, 0]

            for rel in order:
                idx = selected + rel
                if idx < 0 or idx >= len(images):
                    continue

                depth = abs(rel)
                scale = scales[depth]
                card_w = args.width * 0.35 * scale
                card_h = args.height * 0.78 * scale
                offset_x = gaps[depth] * (1 if rel > 0 else -1)

                card = Rectangle(
                    center_x + offset_x - card_w * 0.5,
                    center_y - card_h * 0.5,
                    card_w,
                    card_h,
                )
                tint = Color(255, 255, 255, alphas[depth])
                draw_preview_card(cache, images[idx], card, tint, rel == 0)

        if status and status_frames > 0:
            status_box = Rectangle(12, args.height - 34, args.width - 24, 24)
            draw_rectangle_rounded(status_box, 0.2, 8, Color(0, 0, 0, 145))
            draw_text(status, 20, args.height - 29, 16, status_color)
            status_frames -= 1
        end_drawing()

    cache.clear()
    close_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
