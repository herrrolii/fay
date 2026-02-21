# fay

Small raylib overlay that lists wallpapers from a directory and applies the selected file with `feh`.

## Run

```bash
uv run python main.py ~/Pictures/Wallpapers
```

## Controls

- `Up/Down` or `J/K`: move selection
- Mouse wheel / click: move or pick selection
- `Enter` or `Space`: apply selected image with `feh`
- `R`: refresh directory contents
- `Esc` or `Q`: quit

## Useful flags

```bash
uv run python main.py ~/Pictures/Wallpapers --width 1100 --height 280 --mode bg-fill
```
