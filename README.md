# fay

Small raylib overlay that shows a bottom carousel of wallpaper previews and applies the selected file with `feh`.

## Run

```bash
uv run python main.py ~/Pictures/Wallpapers
```

## Controls

- `Left/Right` (or `A/D`, `H/L`): move selection in the carousel (wraps at ends)
- Moving selection automatically applies wallpaper with `feh` (once per slide)
- `Enter`: confirm current wallpaper and close
- `Esc` (or `Q`): cancel and restore wallpaper from app start, then close
- `R`: refresh directory contents

## Useful flags

```bash
uv run python main.py ~/Pictures/Wallpapers --width 1100 --height 280 --mode bg-fill
```

```bash
uv run python main.py ~/Pictures/Wallpapers --visible-cards 5
```

`--visible-cards` is the max shown at once. If the computed count is even, it is reduced by one so both sides stay symmetric.
