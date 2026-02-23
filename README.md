# fay

Small raylib overlay that shows a bottom carousel of wallpaper previews and applies the selected file with `feh`.

## Install

System dependency:
- `feh` must be installed (for example `sudo apt install feh` or `sudo pacman -S feh`).

One-command app install:

```bash
pipx install "git+https://github.com/herrrolii/fay.git"
```

Then run:

```bash
fay
```

## Run

```bash
fay ~/Pictures/Wallpapers
```

`fay` with no arguments defaults to the current working directory.

## Controls

- `Left/Right` (or `A/D`, `H/L`): move selection in the carousel (wraps at ends)
- Hold `Left/Right` (or `A/D`, `H/L`) to continuously scroll quickly
- Auto-preview while browsing is on by default
- With `--auto-preview` / `--no-auto-preview`: single-tap moves preview immediately, while hold-scroll previews after a delay (`--preview-delay`)
- `Enter`: confirm current wallpaper and close
- `Esc` (or `Q`): cancel and restore wallpaper from app start, then close
- `R`: refresh directory contents

## Useful flags

```bash
fay ~/Pictures/Wallpapers --width 1100 --height 280 --mode bg-fill
```

```bash
fay ~/Pictures/Wallpapers --visible-cards 5
```

```bash
fay ~/Pictures/Wallpapers --auto-preview
```

```bash
fay ~/Pictures/Wallpapers --auto-preview --preview-delay 0.25
```

`--visible-cards` is the max shown at once. If the computed count is even, it is reduced by one so both sides stay symmetric.
`--auto-preview` enables delayed `feh` preview while browsing (enabled by default).
`--preview-delay` controls how long selection must stay still before preview applies (default: `0.18` seconds).
Carousel previews use cached thumbnails in `~/.cache/fay/thumbnails` (or `$XDG_CACHE_HOME/fay/thumbnails`).
Cached dimension sidecars are stored with thumbnails and reused for `--mode auto` decisions.

`--mode` supports: `auto` (default), `bg-fill`, `bg-center`, `bg-max`, `bg-scale`, `bg-tile`.
In `auto` mode, `fay` uses:
- `bg-center` for images smaller than the monitor, or with opposite orientation (portrait vs landscape).
- `bg-center` for extreme aspect-ratio mismatch (ratio factor >= `1.75`).
- `bg-fill` otherwise.
