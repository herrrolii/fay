from __future__ import annotations

import argparse
import shutil
import sys
from typing import Sequence

from fay.models import MODE_CHOICES


BACKEND_CHOICES = ("auto", "feh", "gnome")
POSITION_CHOICES = (
    "bottom",
    "top",
    "center",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
)
DEFAULT_VISIBLE_CARDS = 5
MAX_VISIBLE_CARDS = 15
DEFAULT_PREVIEW_DELAY = 0.18
HELP_MAX_POSITION = 36
HELP_WIDTH = 110


class FayHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog: str) -> None:
        term_width = shutil.get_terminal_size(fallback=(HELP_WIDTH, 24)).columns
        width = max(64, min(HELP_WIDTH, term_width - 2))
        max_help_position = max(22, min(HELP_MAX_POSITION, width // 3))
        super().__init__(prog, max_help_position=max_help_position, width=width)

    def _format_action(self, action: argparse.Action) -> str:
        if action.help is argparse.SUPPRESS:
            return ""

        lines: list[str] = []
        action_header = self._format_action_invocation(action)
        action_indent = " " * self._current_indent
        lines.append(f"{action_indent}{action_header}\n")

        if action.help:
            help_text = self._expand_help(action)
            help_indent_size = self._current_indent + 2
            help_width = max(20, self._width - help_indent_size)
            help_lines = self._split_lines(help_text, help_width)
            help_indent = " " * help_indent_size
            for line in help_lines:
                lines.append(f"{help_indent}{line}\n")

        lines.append("\n")

        for subaction in self._iter_indented_subactions(action):
            lines.append(self._format_action(subaction))

        return "".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in {"restore", "diagnose"}:
        return _parse_subcommand_args(args)
    return _parse_picker_args(args)


def _parse_picker_args(args: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fay",
        description="Wallpaper overlay picker using raylib.",
        formatter_class=FayHelpFormatter,
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
        metavar="BACKEND",
        help="Wallpaper backend to use (auto by default).",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=list(MODE_CHOICES),
        metavar="MODE",
        help="Wallpaper mode: auto/fill/fit/center/tile.",
    )
    parser.add_argument("--width", type=int, default=1000, help="Overlay width in pixels.")
    parser.add_argument("--height", type=int, default=260, help="Overlay height in pixels.")
    parser.add_argument(
        "--position",
        default="bottom",
        choices=POSITION_CHOICES,
        metavar="POSITION",
        help="Preset window position (default: bottom).",
    )
    parser.add_argument(
        "--x",
        type=int,
        default=None,
        help="Manual center X position in monitor coordinates (requires --y, overrides --position).",
    )
    parser.add_argument(
        "--y",
        type=int,
        default=None,
        help="Manual center Y position in monitor coordinates (requires --x, overrides --position).",
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
        help=(
            f"Maximum cards shown at once (1-{MAX_VISIBLE_CARDS}; "
            "larger values are capped, even values are reduced by one)."
        ),
    )
    preview_group = parser.add_mutually_exclusive_group()
    preview_group.add_argument(
        "--auto-preview",
        dest="auto_preview",
        action="store_true",
        default=True,
        help="Apply wallpaper while browsing after a short delay (enabled by default).",
    )
    preview_group.add_argument(
        "--no-preview",
        dest="auto_preview",
        action="store_false",
        help="Disable wallpaper auto-preview while browsing.",
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
        help="Force transparent or opaque window background (default: transparent when supported).",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print environment/backend detection info and exit.",
    )
    parsed = parser.parse_args(args)
    if (parsed.x is None) != (parsed.y is None):
        parser.error("--x and --y must be provided together")
    return parsed


def _parse_subcommand_args(args: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fay", formatter_class=FayHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore = subparsers.add_parser("restore", help="Reapply last confirmed wallpaper.")
    restore.add_argument(
        "--backend",
        default="auto",
        choices=BACKEND_CHOICES,
        metavar="BACKEND",
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
