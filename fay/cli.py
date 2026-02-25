from __future__ import annotations

import argparse
import sys
from typing import Sequence

from fay.models import MODE_CHOICES


BACKEND_CHOICES = ("auto", "feh", "gnome", "swaybg", "swww", "hyprpaper")
DEFAULT_VISIBLE_CARDS = 5
DEFAULT_PREVIEW_DELAY = 0.18


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in {"restore", "diagnose"}:
        return _parse_subcommand_args(args)
    return _parse_picker_args(args)


def _parse_picker_args(args: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fay",
        description="Bottom overlay wallpaper picker using raylib.",
    )
    parser.set_defaults(command="pick")
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Directory containing wallpaper images (defaults to current working directory).",
    )
    parser.add_argument(
        "--backend",
        default="auto",
        choices=BACKEND_CHOICES,
        help="Wallpaper backend to use (auto by default).",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=list(MODE_CHOICES),
        help="Wallpaper mode: auto/fill/fit/center/tile (legacy bg-* aliases still accepted).",
    )
    parser.add_argument("--width", type=int, default=1000, help="Overlay width in pixels.")
    parser.add_argument("--height", type=int, default=260, help="Overlay height in pixels.")
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
        help="Seconds to stay on a card before auto-preview applies.",
    )
    parser.add_argument(
        "--transparent",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force transparent or opaque window background (default: transparent on X11, opaque on Wayland).",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print environment/backend detection info and exit.",
    )
    return parser.parse_args(args)


def _parse_subcommand_args(args: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore = subparsers.add_parser("restore", help="Reapply last confirmed wallpaper.")
    restore.add_argument(
        "--backend",
        default="auto",
        choices=BACKEND_CHOICES,
        help="Backend override for restore.",
    )

    subparsers.add_parser("diagnose", help="Print environment/backend detection info.")

    return parser.parse_args(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    from fay.app import run_diagnose, run_picker, run_restore

    if args.command == "diagnose" or getattr(args, "diagnose", False):
        return run_diagnose(args)
    if args.command == "restore":
        return run_restore(args)
    return run_picker(args)
