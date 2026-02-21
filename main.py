import argparse
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


def place_window_at_bottom(width: int, height: int, margin: int, monitor: int) -> None:
    monitor_pos = get_monitor_position(monitor)
    monitor_x = int(monitor_pos.x)
    monitor_y = int(monitor_pos.y)
    monitor_width = get_monitor_width(monitor)
    monitor_height = get_monitor_height(monitor)

    x = monitor_x + (monitor_width - width) // 2
    y = monitor_y + monitor_height - height - margin
    set_window_position(max(monitor_x, x), max(monitor_y, y))


def main() -> int:
    args = parse_args()
    wallpaper_dir = Path(args.directory).expanduser()

    images = list_images(wallpaper_dir)
    selected = 0
    scroll = 0
    status = f"Loaded {len(images)} image(s)."
    status_color = LIGHTGRAY

    if not wallpaper_dir.exists() or not wallpaper_dir.is_dir():
        status = f"Directory not found: {wallpaper_dir}"
        status_color = ORANGE

    set_config_flags(FLAG_WINDOW_UNDECORATED | FLAG_WINDOW_TOPMOST)
    init_window(args.width, args.height, "fay wallpaper picker")
    set_target_fps(60)
    set_exit_key(KEY_NULL)

    monitor = args.monitor if args.monitor is not None else get_current_monitor()
    place_window_at_bottom(args.width, args.height, args.margin, monitor)

    list_top = 44
    list_bottom = args.height - 36
    item_height = 28
    list_color = Color(20, 24, 30, 255)
    selected_color = Color(58, 98, 138, 255)
    background_color = Color(13, 15, 18, 255)

    while True:
        if window_should_close() or is_key_pressed(KEY_ESCAPE) or is_key_pressed(KEY_Q):
            break

        if is_key_pressed(KEY_R):
            images = list_images(wallpaper_dir)
            selected = clamp(selected, 0, max(0, len(images) - 1))
            status = f"Reloaded: {len(images)} image(s)."
            status_color = LIGHTGRAY

        if images:
            if is_key_pressed(KEY_DOWN) or is_key_pressed(KEY_J):
                selected = min(selected + 1, len(images) - 1)
            if is_key_pressed(KEY_UP) or is_key_pressed(KEY_K):
                selected = max(selected - 1, 0)

            wheel = get_mouse_wheel_move()
            if wheel < 0:
                selected = min(selected + 1, len(images) - 1)
            elif wheel > 0:
                selected = max(selected - 1, 0)

            if is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
                mouse = get_mouse_position()
                if 0 <= mouse.x <= args.width and list_top <= mouse.y < list_bottom:
                    clicked_index = scroll + int((mouse.y - list_top) // item_height)
                    if 0 <= clicked_index < len(images):
                        selected = clicked_index

            if (
                is_key_pressed(KEY_ENTER)
                or is_key_pressed(KEY_KP_ENTER)
                or is_key_pressed(KEY_SPACE)
            ):
                ok, message = apply_wallpaper(images[selected], args.mode)
                status = message
                status_color = GREEN if ok else RED

        visible_rows = max(1, (list_bottom - list_top) // item_height)
        if selected < scroll:
            scroll = selected
        if selected >= scroll + visible_rows:
            scroll = selected - visible_rows + 1
        scroll = clamp(scroll, 0, max(0, len(images) - visible_rows))

        begin_drawing()
        clear_background(background_color)

        draw_rectangle(0, 0, args.width, args.height, background_color)
        draw_rectangle(0, list_top - 6, args.width, list_bottom - list_top + 6, list_color)
        draw_rectangle_lines(0, 0, args.width, args.height, GRAY)

        draw_text(
            f"Wallpapers: {wallpaper_dir}",
            12,
            10,
            18,
            RAYWHITE,
        )
        draw_text("Enter/Space: apply | R: refresh | Esc/Q: quit", 12, args.height - 24, 16, GRAY)

        if not images:
            draw_text("No images found in directory.", 12, list_top + 10, 20, ORANGE)
        else:
            end_index = min(len(images), scroll + visible_rows)
            for idx in range(scroll, end_index):
                y = list_top + (idx - scroll) * item_height
                if idx == selected:
                    draw_rectangle(2, y, args.width - 4, item_height, selected_color)
                draw_text(images[idx].name, 12, y + 5, 18, RAYWHITE)

        draw_text(status, 12, args.height - 46, 18, status_color)
        end_drawing()

    close_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
