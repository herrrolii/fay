from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable

import pyray as rl

from fay.backends.base import ApplyContext, effective_mode
from fay.backends.registry import BackendRegistry
from fay.env import detect_environment
from fay.media import (
    THUMB_BUILD_BUDGET_IDLE,
    THUMB_MAX_HEIGHT,
    THUMB_MAX_WIDTH,
    TextureCache,
    ThumbnailStore,
    get_thumbnail_cache_dir,
    list_images,
)
from fay.models import BackendResult, WallpaperState, normalize_mode
from fay.ui import (
    FLAG_WINDOW_TOPMOST,
    FLAG_WINDOW_TRANSPARENT,
    FLAG_WINDOW_UNDECORATED,
    KEY_A,
    KEY_D,
    KEY_ENTER,
    KEY_ESCAPE,
    KEY_H,
    KEY_KP_ENTER,
    KEY_L,
    KEY_LEFT,
    KEY_NULL,
    KEY_Q,
    KEY_R,
    KEY_RIGHT,
    clamp,
    draw_preview_card,
    lerp,
    place_window_at_bottom,
    sample_curve,
)

WINDOW_TITLE = "fay wallpaper picker"
DEFAULT_VISIBLE_CARDS = 5
HOLD_REPEAT_DELAY = 0.22
HOLD_REPEAT_INTERVAL = 0.055
DEFAULT_PREVIEW_DELAY = 0.18


class AsyncActionRunner:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending_action: Callable[[], object] | None = None
        self._running = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="fay-preview-runner", daemon=False
        )
        self._thread.start()

    def submit(self, action: Callable[[], object]) -> None:
        with self._condition:
            if self._closed:
                return
            self._pending_action = action
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending_action is None and not self._closed:
                    self._condition.wait()
                if self._closed and self._pending_action is None:
                    return
                action = self._pending_action
                self._pending_action = None
                self._running = True

            try:
                if action is not None:
                    action()
            except Exception:
                pass
            finally:
                with self._condition:
                    self._running = False
                    self._condition.notify_all()

    def shutdown(self, flush_pending: bool) -> None:
        if flush_pending:
            with self._condition:
                while self._pending_action is not None or self._running:
                    self._condition.wait()
        with self._condition:
            self._closed = True
            self._pending_action = None
            self._condition.notify_all()
        self._thread.join()


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


def get_state_file_path() -> Path:
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        state_dir = Path(xdg_state_home).expanduser()
    else:
        state_dir = Path("~/.local/state").expanduser()
    return state_dir / "fay" / "last_selection.json"


def save_last_selection(state: WallpaperState) -> None:
    path = get_state_file_path()
    payload = {
        "backend_id": state.backend_id,
        "image_path": state.image_path,
        "mode": state.mode,
        "backend_state": state.backend_state,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def load_last_selection() -> WallpaperState | None:
    path = get_state_file_path()
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    backend_id = payload.get("backend_id")
    image_path = payload.get("image_path")
    mode = payload.get("mode")
    backend_state = payload.get("backend_state")
    if not isinstance(backend_id, str) or not isinstance(image_path, str):
        return None
    if not isinstance(mode, str):
        mode = "fill"
    if not isinstance(backend_state, dict):
        backend_state = {}

    return WallpaperState(
        backend_id=backend_id,
        image_path=image_path,
        mode=mode,
        backend_state=backend_state,
    )


def monitor_size(monitor: int | None) -> tuple[int, int, int]:
    if monitor is None:
        monitor = rl.get_current_monitor()
    width = rl.get_monitor_width(monitor)
    height = rl.get_monitor_height(monitor)
    return monitor, width, height


def should_use_transparent_window(
    explicit: bool | None,
    env_session_type: str,
    wayland_display: str,
) -> bool:
    if explicit is not None:
        return explicit
    if env_session_type == "wayland" or wayland_display:
        return False
    return True


def run_picker(args: Any) -> int:
    env = detect_environment()
    registry = BackendRegistry()
    choice = registry.resolve(env, args.backend)
    backend = choice.backend
    if backend is None:
        print(f"fay: {choice.reason}")
        print(build_diagnostics(registry, env))
        return 1

    lock_handle = acquire_single_instance_lock(get_lock_path())
    if lock_handle is None:
        focus_existing_window(WINDOW_TITLE)
        return 0

    wallpaper_dir = Path(args.directory).expanduser() if args.directory else Path.cwd()
    images = list_images(wallpaper_dir)
    max_visible_cards = max(1, args.visible_cards)
    normalized_mode = normalize_mode(args.mode)

    startup_state = backend.capture_current()
    selected = 0
    if startup_state and images:
        image_lookup = {str(path.resolve()): idx for idx, path in enumerate(images)}
        try:
            startup_key = str(startup_state.path.resolve())
        except OSError:
            startup_key = str(startup_state.path)
        found = image_lookup.get(startup_key)
        if found is not None:
            selected = found

    use_transparent = should_use_transparent_window(
        args.transparent,
        env.session_type,
        env.wayland_display,
    )

    flags = FLAG_WINDOW_UNDECORATED | FLAG_WINDOW_TOPMOST
    if use_transparent:
        flags |= FLAG_WINDOW_TRANSPARENT

    rl.set_config_flags(flags)
    rl.init_window(args.width, args.height, WINDOW_TITLE)
    rl.set_target_fps(60)
    rl.set_exit_key(KEY_NULL)

    monitor, monitor_width, monitor_height = monitor_size(args.monitor)
    place_window_at_bottom(args.width, args.height, args.margin, monitor)

    thumbnail_store = ThumbnailStore(
        get_thumbnail_cache_dir(), THUMB_MAX_WIDTH, THUMB_MAX_HEIGHT
    )
    cache = TextureCache(thumbnail_store)
    image_size_cache: dict[str, tuple[int, int]] = {}
    apply_context = ApplyContext(
        screen_width=monitor_width,
        screen_height=monitor_height,
        image_size_cache=image_size_cache,
    )
    preview_runner = AsyncActionRunner()

    transparent = rl.Color(0, 0, 0, 0)
    panel = rl.Color(16, 18, 22, 235)
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
    auto_preview_enabled = args.auto_preview and backend.supports_preview()
    preview_delay = max(0.0, args.preview_delay)
    selection_dwell_time = 0.0
    last_auto_preview_index: int | None = None

    final_result = BackendResult(ok=True)
    final_state_to_save: WallpaperState | None = None
    exit_kind = "cancel"

    while True:
        frame_time = rl.get_frame_time()
        if rl.window_should_close() or rl.is_key_pressed(KEY_ESCAPE) or rl.is_key_pressed(KEY_Q):
            exit_kind = "cancel"
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
                selected_image = images[selected]
                resolved_mode = effective_mode(normalized_mode, selected_image, apply_context)
                final_result = backend.apply(
                    selected_image,
                    resolved_mode,
                    apply_context,
                    persist_now=True,
                )
                if final_result.ok:
                    final_state_to_save = WallpaperState(
                        backend_id=backend.id,
                        image_path=str(selected_image),
                        mode=resolved_mode,
                    )
                    exit_kind = "confirm"
                else:
                    exit_kind = "error"
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
                preview_path = images[selected]
                preview_runner.submit(
                    lambda path=preview_path: backend.preview(
                        path,
                        normalized_mode,
                        apply_context,
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
                    preview_path = images[selected]
                    preview_runner.submit(
                        lambda path=preview_path: backend.preview(
                            path,
                            normalized_mode,
                            apply_context,
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
        rl.clear_background(transparent if use_transparent else panel)

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

    preview_runner.shutdown(flush_pending=False)
    cache.clear()
    rl.close_window()
    try:
        lock_handle.close()
    except OSError:
        pass

    if exit_kind == "cancel" and startup_state is not None:
        _ = backend.restore(startup_state, apply_context)

    if exit_kind == "confirm" and final_state_to_save is not None:
        save_last_selection(final_state_to_save)

    if not final_result.ok:
        print(f"fay: {final_result.error or 'wallpaper apply failed'}")
        return 1

    return 0


def run_restore(args: Any) -> int:
    env = detect_environment()
    registry = BackendRegistry()

    state = load_last_selection()
    if state is None:
        print("fay: no saved wallpaper selection found")
        return 1

    backend = None
    if args.backend != "auto":
        choice = registry.resolve(env, args.backend)
        backend = choice.backend
        if backend is None:
            print(f"fay: {choice.reason}")
            print(build_diagnostics(registry, env))
            return 1
    else:
        preferred = registry.get(state.backend_id)
        if preferred and preferred.is_available(env):
            backend = preferred
        else:
            choice = registry.resolve(env, "auto")
            backend = choice.backend
            if backend is None:
                print(f"fay: {choice.reason}")
                print(build_diagnostics(registry, env))
                return 1

    apply_context = ApplyContext(screen_width=0, screen_height=0, image_size_cache={})
    result = backend.apply(state.path, state.mode, apply_context, persist_now=True)
    if not result.ok:
        print(f"fay: {result.error or 'restore failed'}")
        return 1
    return 0


def run_diagnose(args: Any) -> int:
    env = detect_environment()
    registry = BackendRegistry()
    print(build_diagnostics(registry, env))
    return 0


def build_diagnostics(registry: BackendRegistry, env: Any) -> str:
    lines: list[str] = []
    lines.append("Environment:")
    lines.append(f"  session_type: {env.session_type or 'unknown'}")
    lines.append(f"  current_desktop: {env.current_desktop or 'unknown'}")
    lines.append(f"  desktop_session: {env.desktop_session or 'unknown'}")
    lines.append(f"  wayland_display: {env.wayland_display or '-'}")
    lines.append(f"  x_display: {env.x_display or '-'}")
    lines.append(f"  sway: {env.sway}")
    lines.append(f"  hyprland: {env.hyprland}")
    lines.append(
        "  commands: "
        + (", ".join(sorted(env.commands)) if env.commands else "(none detected)")
    )
    lines.append("")
    lines.append("Backends:")
    for backend in registry.backends:
        available = backend.is_available(env)
        lines.append(
            f"  {backend.id}: {'available' if available else 'unavailable'}"
        )

    choice = registry.resolve(env, "auto")
    lines.append("")
    lines.append(f"Auto backend: {choice.backend.id if choice.backend else 'none'}")
    lines.append(f"Reason: {choice.reason}")

    return "\n".join(lines)
