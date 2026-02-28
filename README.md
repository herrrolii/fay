# fay

Small raylib overlay for X11 and GNOME that shows a carousel of wallpaper previews and applies the selected file.

![fay demo](assets/fay-demo.gif)
> Demo wallpapers credit: [dharmx/walls](https://github.com/dharmx/walls).

## Install

```bash
pipx install "git+https://github.com/herrrolii/fay.git"
```

Then run:

```bash
fay ~/Pictures
```

`fay` with no arguments defaults to the current working directory.

## Supported Backends (auto-detected)

- `feh` (generic X11 sessions)
- `gsettings` (GNOME)

Use `fay --diagnose` to see what was detected on your machine.

## Commands

Open picker:

```bash
fay ~/Pictures/Wallpapers
```

Reapply last confirmed wallpaper (for login/startup hooks):

```bash
fay restore
```

Diagnostics:

```bash
fay diagnose
```

List all available arguments:

```bash
fay --help
```

## Controls

- `Left/Right` (or `A/D`, `H/L`): move selection in the carousel (wraps at ends)
- Hold `Left/Right` (or `A/D`, `H/L`) to continuously scroll quickly
- Auto-preview while browsing is on by default (disable with `--no-preview`)
- `Enter`: confirm current wallpaper and close
- `Esc` (or `Q`): cancel and restore wallpaper from app start, then close
- `R`: refresh directory contents

## Useful Flags

```bash
fay ~/Pictures/Wallpapers --width 1100 --height 280
```

```bash
fay ~/Pictures/Wallpapers --visible-cards 5
```

```bash
fay ~/Pictures/Wallpapers --backend auto --mode auto
```

```bash
fay ~/Pictures/Wallpapers --auto-preview --preview-delay 0.25
```

```bash
fay ~/Pictures/Wallpapers --no-preview
```

```bash
fay ~/Pictures/Wallpapers --transparent
```

```bash
fay ~/Pictures/Wallpapers --no-transparent
```

```bash
fay ~/Pictures/Wallpapers --position top-right
```

```bash
fay ~/Pictures/Wallpapers --x 960 --y 860
```

`--visible-cards` is capped at `15` (default `9`). If the computed count is even, it is reduced by one so both sides stay symmetric.
`--position` supports preset locations and keeps a reasonable edge inset by default (for panels/taskbars).
`--x` and `--y` allow manual placement using the window center in monitor coordinates and override `--position`.

`--mode` is backend-agnostic and supports:
- `auto` (default)
- `fill`
- `fit`
- `center`
- `tile`

`--backend` supports: `auto` (default), `feh`, `gnome`.

Auto-preview uses async backend calls and thumbnail caching. Thumbnails are stored in `~/.cache/fay/thumbnails` (or `$XDG_CACHE_HOME/fay/thumbnails`).
First startup in a directory can be slower while `fay` builds its thumbnail/dimension cache.

Confirmed picks are stored in `~/.local/state/fay/last_selection.json` (or `$XDG_STATE_HOME/fay/last_selection.json`) and can be replayed with `fay restore`.
