# AGENTS.md

Instructions for agents (and humans) working on this repository. Read before
making changes.

## What this is

A graphical HDR manager for **Hyprland 0.56+ with a Lua config** (e.g. CachyOS).
GTK4 + libadwaita on Python (PyGObject). Toggles HDR and adjusts SDR
tone-mapping live, and saves settings back to the config.

## Critical facts — do not break

1. **`hyprctl keyword monitor ...` does NOT work** on Hyprland 0.56+ with a Lua
   config (the config provider is `lua`). Live writes must go through
   `hyprctl repl 'hl.monitor({ ... })'`. Implemented in
   `hyprhdr/backend.py::apply_spec`.
2. **Read** — `hyprctl monitors -j` (runtime fields are **camelCase**:
   `sdrBrightness`, `sdrSaturation`, `sdrMinLuminance`, `sdrMaxLuminance`,
   `colorManagementPreset`).
3. **Lua config fields** inside `hl.monitor({ ... })` are **snake_case**, with
   non-obvious exceptions: `sdrbrightness` and `sdrsaturation` have **no
   underscore**, while `sdr_min_luminance` / `sdr_max_luminance` **do**. The full
   list is `backend.COLOR_FIELDS`. Don't confuse them with the runtime camelCase
   fields from point 2.
4. **`cm` values**: `"hdr"` (HDR on) ↔ `"srgb"` (SDR); also `"none"`, `"edid"`.
5. **Saving the config** — `hyprhdr/configfile.py`, edits the `hl.monitor({ ... })`
   block in place with a `*.bak` backup before each write. The parser is
   deliberately conservative (line-by-line regex + a brace scanner that skips
   `--` comments and quoted strings). Don't replace it with a "full" Lua parser
   without tests — you risk corrupting the user's config.

## Modules

- `hyprhdr/backend.py` — hyprctl: read/write, Lua literals, the `Monitor` dataclass.
- `hyprhdr/configfile.py` — find/parse/edit `monitors.lua`.
- `hyprhdr/reference.py` — database of measured monitor values (keyed by a
  substring, e.g. `"27q-10"`). Fallback is `DEFAULT_REFERENCE`.
- `hyprhdr/gui.py` — interface; `HdrWindow` holds state and apply logic.
- `main.py` — entry point.

## Conventions

- UI strings and comments are in English; identifiers/keys in English.
- Add a new HDR field via `backend.COLOR_FIELDS` (+ a slider in `gui._SLIDERS`
  if needed). Types `str`/`int`/`float` drive Lua serialization and rounding.
- Live apply goes through `HdrWindow._set_field` (120 ms debounce → `_flush` →
  `backend.apply_spec`). When setting widgets programmatically, set
  `self._loading = True` to avoid re-triggering an apply.
- Geometry (`mode`, `position`, `scale`) must always be present in the spec for
  `hl.monitor`, otherwise Hyprland resets it to defaults — see `_build_spec`.

## How to run / verify

```bash
python3 main.py
python3 -m py_compile hyprhdr/*.py main.py   # quick syntax check
hyprctl monitors -j                          # current state
hyprctl repl 'hl.monitor({ output = "DP-3", cm = "srgb" })'  # manual apply
```

The GUI only works in a live Wayland/Hyprland session; in CI/sandboxes without a
GPU you'll see harmless Vulkan/MESA/dconf warnings — that's expected.

## Extensions (TODO)

- Automatic adjustment — a time-of-day night mode and/or content-based auto-HDR
  via `render.cm_auto_hdr`. The extension points are already isolated:
  `backend.apply_spec` (apply) and `HdrWindow._set_field` (source of changes).
