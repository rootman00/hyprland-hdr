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
4. **`cm` presets**: `"auto"` (recommended — srgb for 8bpc, wide for 10bpc),
   `"srgb"`, `"wide"`, `"dcip3"`, `"dp3"`, `"adobe"`, `"edid"`, `"hdr"`,
   `"hdredid"`. The GUI's color mode maps SDR→`srgb`, HDR→`hdr`, and
   Auto-HDR→`srgb` + `render.cm_auto_hdr`.
5. **Auto HDR** — `render:cm_auto_hdr` is a **render** option, not a monitor
   field. It lives in `hl.config({ render = { ... } })`. Live apply via
   `hl.config({ render = { ... } })` (`backend.apply_render`); read via
   `hyprctl getoption render:cm_auto_hdr -j` (`backend.get_render_options`).
   Auto-HDR = a non-HDR `cm` preset (`srgb`) + `cm_auto_hdr` int 1 (`hdr`) or
   2 (`hdredid`); Hyprland auto-switches to HDR for HDR content. `cm = "auto"` is
   an *auto colorspace* preset, NOT auto-HDR. Runtime `colorManagementPreset`
   reports the **resolved** preset, not the configured one — `gui._build_spec`
   keeps the configured `cm` (don't overwrite it with runtime).
6. **Saving the config** — `hyprhdr/configfile.py`, edits the `hl.monitor({ ... })`
   block in place with a `*.bak` backup before each write. If no block for the
   current `output` exists, `MonitorConfigFile.save(..., geometry=...)` **creates
   one** instead of raising (the GUI always passes geometry). `save(...,
   render_updates=...)` also updates the `hl.config({ render = { ... } })` block.
   The parser is deliberately conservative (line-by-line regex + a brace scanner
   that skips `--` comments and quoted strings). Don't replace it with a "full"
   Lua parser without tests — you risk corrupting the user's config.
   `tests/test_hyprhdr.py` covers the parser and the save/create paths.

## Modules

- `hyprhdr/backend.py` — hyprctl: read/write, Lua literals, the `Monitor` dataclass.
- `hyprhdr/configfile.py` — find/parse/edit `monitors.lua`.
- `hyprhdr/reference.py` — database of measured monitor values (keyed by a
  substring, e.g. `"27q-10"`). Fallback is `DEFAULT_REFERENCE`.
- `hyprhdr/settings.py` — app-level settings (language + night-mode schedule),
  JSON in `~/.config/hdr-manager/settings.json`; also `settings.is_night()` (pure).
- `hyprhdr/i18n.py` — UI translations (English source strings → Russian). Set the
  active language with `i18n.set_language()`, wrap user-facing strings in
  `i18n.tr()`. English is the default.
- `hyprhdr/sun.py` — IP geolocation (`fetch_coordinates`, the only network call,
  `None` on failure) + sunrise/sunset computed **locally** with the NOAA
  algorithm (`fetch_sun_times`, no network; raises on polar day/night).
  `hour_float()` is the pure ISO→local-hour converter.
- `hyprhdr/tray.py` — StatusNotifierItem tray icon over D-Bus (no
  libappindicator needed). The icon is a monochrome (white) sun glyph, ARGB32,
  generated in Python with 4× supersampling, in sizes 16–128 px.
- `hyprhdr/gui.py` — interface; `HdrWindow` holds state and apply logic.
- `main.py` — entry point.

## Conventions

- UI strings and comments are in English; identifiers/keys in English. User-facing
  strings are wrapped in `i18n.tr()` and translated in `hyprhdr/i18n.py` (English
  default, Russian optional). When you add a string, also add its Russian
  translation to `i18n._TRANSLATIONS`.
- Add a new HDR field via `backend.COLOR_FIELDS` (+ a slider in `gui._SLIDERS`
  if needed). Types `str`/`int`/`float` drive Lua serialization and rounding.
- Live apply goes through `HdrWindow._set_field` (120 ms debounce → `_flush`).
  `_flush` applies **both** channels: monitor fields via `backend.apply_spec`
  and render fields via `backend.apply_render`. Keys in `gui._RENDER_FIELDS`
  are routed to `self.render_spec`, everything else to `self.spec`. When setting
  widgets programmatically, set `self._loading = True` to avoid re-triggering an
  apply.
- Geometry (`mode`, `position`, `scale`) must always be present in the spec for
  `hl.monitor`, otherwise Hyprland resets it to defaults — see `_build_spec`.
- Night mode (schedule) overrides `sdrbrightness`/`sdrsaturation` via
  `HdrWindow._effective_spec()` (not by mutating `self.spec`); the day sliders
  stay at their day values. The 60 s `_night_tick` re-applies on window edges;
  user changes to night settings go through `_refresh_night`. The window is
  `settings.is_night()`; with `schedule_mode == "sun"` it uses cached
  `sunset_hour`/`sunrise_hour` (fetched in a background thread by
  `HdrWindow._sun_worker`, re-fetched once a day) and falls back to the manual
  hours until the first successful fetch.

## How to run / verify

```bash
python3 main.py
python3 -m py_compile hyprhdr/*.py main.py tests/*.py   # quick syntax check
python3 -m unittest discover                            # parser/save tests (no GPU needed)
hyprctl monitors -j                                     # current state
hyprctl repl 'hl.monitor({ output = "DP-3", cm = "srgb" })'  # manual apply
```

The GUI only works in a live Wayland/Hyprland session; in CI/sandboxes without a
GPU you'll see harmless Vulkan/MESA/dconf warnings — that's expected.

## Extensions (TODO)

- Smooth day/night transition — the schedule currently switches values instantly
  at the hour boundary; a gradual fade would be nicer. Night mode itself is
  implemented (`hyprhdr/settings.py`, `HdrWindow._night_tick`).

Research-backed backlog (Hyprland 0.54–0.57, wiki `wiki.hypr.land`):

- (Done) `sdr_min_luminance` slider added. `min_luminance` is still
  read/persisted but not shown — its `-1` = "auto from EDID" default needs a
  dedicated "auto" handling before exposing it as a slider.
- (Done) Inline warning when `render.cm_enabled` is false (color management off →
  sliders are no-ops; toggling needs a restart).
- (Fixed) Auto-HDR now uses `cm="srgb"` + `render.cm_auto_hdr` (int 1/2,
  selectable via "Auto HDR target") instead of the legacy `cm="auto"`.
  `cm="auto"` means *auto colorspace*, not "auto HDR".
- `render.cm_force_swizzle` and `enable_10bpc` are legacy/removed in current
  docs — the app does not write them (verify with `hyprctl getoption` before ever
  adding).
- `sdr_eotf` per-monitor values are `default`/`srgb`/`gamma22` (already used);
  the global `render.cm_sdr_eotf` additionally supports `gamma22force`.
- Post-save validation via `hyprctl configerrors`; version-adaptive option
  discovery via `hyprctl descriptions`.
