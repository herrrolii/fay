# fay

Small raylib overlay that shows a bottom carousel of wallpaper previews and applies the selected file with `feh`.

## Run

```bash
uv run python main.py ~/Pictures/Wallpapers
```

## Controls

- `Left/Right` (or `A/D`, `H/L`): move selection in the carousel (wraps at ends)
- `Enter` or `Space`: apply selected image with `feh`
- `R`: refresh directory contents
- `Esc` or `Q`: quit

## Useful flags

```bash
uv run python main.py ~/Pictures/Wallpapers --width 1100 --height 280 --mode bg-fill
```
