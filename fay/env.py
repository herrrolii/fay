from __future__ import annotations

import os
import shutil
from typing import Iterable

from fay.models import EnvironmentInfo


KNOWN_COMMANDS = (
    "feh",
    "gsettings",
    "swaybg",
    "swaymsg",
    "swww",
    "awww",
    "swww-daemon",
    "hyprctl",
)


def detect_environment(extra_commands: Iterable[str] = ()) -> EnvironmentInfo:
    command_names: set[str] = set(KNOWN_COMMANDS)
    command_names.update(extra_commands)

    available_commands = {
        command for command in command_names if shutil.which(command) is not None
    }

    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    desktop_session = os.environ.get("DESKTOP_SESSION", "").strip()
    current_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").strip()
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "").strip()
    x_display = os.environ.get("DISPLAY", "").strip()

    sway = bool(os.environ.get("SWAYSOCK")) or "sway" in current_desktop.lower()
    hyprland = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or (
        "hyprland" in current_desktop.lower()
    )

    return EnvironmentInfo(
        session_type=session_type,
        desktop_session=desktop_session,
        current_desktop=current_desktop,
        wayland_display=wayland_display,
        x_display=x_display,
        sway=sway,
        hyprland=hyprland,
        commands=available_commands,
    )


def has_command(env: EnvironmentInfo, command: str) -> bool:
    return command in env.commands


def is_gnome_session(env: EnvironmentInfo) -> bool:
    value = f"{env.current_desktop}:{env.desktop_session}".lower()
    return "gnome" in value or "ubuntu" in value
