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
- Moving selection automatically applies wallpaper with `feh` (once per slide)
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

`--visible-cards` is the max shown at once. If the computed count is even, it is reduced by one so both sides stay symmetric.

`--mode` supports: `auto` (default), `bg-fill`, `bg-center`, `bg-max`, `bg-scale`, `bg-tile`.
In `auto` mode, `fay` uses:
- `bg-center` for images smaller than the monitor, or with opposite orientation (portrait vs landscape).
- `bg-center` for extreme aspect-ratio mismatch (ratio factor >= `1.75`).
- `bg-fill` otherwise.
