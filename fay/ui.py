from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pyray as rl

from fay.media import TextureCache


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


def place_window(
    width: int,
    height: int,
    monitor: int,
    position: str,
    center_x: int | None,
    center_y: int | None,
) -> None:
    monitor_pos = rl.get_monitor_position(monitor)
    monitor_x = int(monitor_pos.x)
    monitor_y = int(monitor_pos.y)
    monitor_width = rl.get_monitor_width(monitor)
    monitor_height = rl.get_monitor_height(monitor)

    edge_x = max(32, int(monitor_width * 0.03))
    edge_y = max(48, int(monitor_height * 0.06))

    min_x = monitor_x + edge_x
    max_x = monitor_x + monitor_width - width - edge_x
    min_y = monitor_y + edge_y
    max_y = monitor_y + monitor_height - height - edge_y

    if min_x > max_x:
        min_x = monitor_x
        max_x = monitor_x + monitor_width - width
    if min_y > max_y:
        min_y = monitor_y
        max_y = monitor_y + monitor_height - height

    if center_x is not None and center_y is not None:
        x = monitor_x + center_x - width // 2
        y = monitor_y + center_y - height // 2
    else:
        x = monitor_x + (monitor_width - width) // 2
        y = monitor_y + (monitor_height - height) // 2
        if position == "bottom":
            y = max_y
        elif position == "top":
            y = min_y
        elif position == "top-left":
            x = min_x
            y = min_y
        elif position == "top-right":
            x = max_x
            y = min_y
        elif position == "bottom-left":
            x = min_x
            y = max_y
        elif position == "bottom-right":
            x = max_x
            y = max_y

    x = clamp(x, min_x, max_x)
    y = clamp(y, min_y, max_y)
    rl.set_window_position(x, y)


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
