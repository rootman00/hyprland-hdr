# hdr-manager

A small GUI for visual HDR management on Wayland (Hyprland 0.56+ with a
**Lua config**, e.g. CachyOS). Toggle HDR and adjust SDR tone-mapping live.

## Features (v1)

- **Color mode** selector — **SDR** / **HDR** / **Auto HDR**
- **Auto HDR** — `render.cm_auto_hdr` (selectable target `hdr` or `hdredid`)
  on top of `cm = "srgb"`: SDR by default, auto-switch to HDR for HDR content
- **Night mode (schedule)** — lower SDR brightness/saturation at night and
  restore them in the morning (HDR stays on); either **manual hours** or
  **sun-based** (sunrise/sunset fetched from the internet for your location)
- **SDR brightness** (`sdrbrightness`) — the main control against washed-out SDR in HDR
- **SDR saturation** (`sdrsaturation`)
- **SDR min luminance** (`sdr_min_luminance`, nits) — SDR black level for the tone map
- **SDR max luminance** (`sdr_max_luminance`, nits)
- **Peak brightness** of the HDR panel (`max_luminance`, nits)
- **Average brightness / ABL** (`max_avg_luminance`)
- **SDR EOTF** (gamma) and **color depth** (8/10-bit)
- **Monitor reference** — measured panel values and an "Apply reference" button
  that resets luminance limits to factory values
- Live apply (slider → monitor immediately) and **save to config** — the block
  is edited in place, or created if the current output has none
- **Language** — English (default) or Russian, switchable in the GUI (stored in
  `settings.json`)
- **System tray icon** (StatusNotifierItem) — close the window to hide it to the
  tray, click the icon to bring it back

## Requirements

- Hyprland 0.56+ with a Lua config (tested on 0.57.0)
- `hyprctl` in `$PATH`
- Python 3.10+, PyGObject + GTK4 + libadwaita

Arch Linux:

```bash
sudo pacman -S python python-gobject gtk4 libadwaita
```

## Usage

```bash
cd hdr-manager
python3 main.py
```

Or make it executable:

```bash
chmod +x main.py && ./main.py
```

### System tray

The app registers a monochrome sun tray icon (StatusNotifierItem). Closing the
window hides it to the tray instead of quitting; click the tray icon to show it
again. Use **Quit** in the window header to exit completely.

To start hidden in the tray (e.g. from autostart):

```bash
python3 main.py --hidden
```

### Autostart

An XDG autostart entry is installed at `~/.config/autostart/hdr-manager.desktop`.
It launches the app with `--hidden`, so on login it sits in the tray and opens on
click:

```ini
[Desktop Entry]
Type=Application
Name=HDR Manager
Comment=HDR manager for Hyprland (system tray)
Exec=/usr/bin/python3 /home/kirill/dsh-test/hdr-manager/main.py --hidden
Terminal=false
X-GNOME-Autostart-enabled=true
```

## Tests

The pure (no-Hyprland) parts have unit tests — the Lua config parser and
save/create logic, settings, i18n, sun-time conversion, and the tray icon:

```bash
python3 -m unittest discover
```

### Color modes

The **Color mode** row chooses how the monitor is driven:

| Mode | `cm` | `render.cm_auto_hdr` | Behavior |
|---|---|---|---|
| **SDR** | `srgb` | 0 | Always SDR |
| **HDR** | `hdr` | 0 | Always HDR (wide gamut + PQ) |
| **Auto HDR** | `srgb` | 1 or 2 | SDR by default, auto-switch to HDR for HDR content |

`cm = "auto"` is an *auto colorspace* preset (resolves to sRGB on 8-bit or
wide-gamut on 10-bit); it is **not** "auto HDR" by itself. Auto-HDR is driven by
`render.cm_auto_hdr` (int 0/1/2) on top of a non-HDR `cm` preset — the app uses
`cm = "srgb"` as the base. The **Auto HDR target** row selects what to switch to:
`1` = `hdr` (wide-gamut + PQ, default) or `2` = `hdredid` (EDID primaries + PQ).
With it enabled Hyprland switches the same monitor to HDR for fullscreen HDR
content and back to SDR otherwise — so the desktop stays in SDR in this mode, and
the SDR sliders only affect tone-mapping while HDR is active.

If `render.cm_enabled` is `0` (color management off), the app shows an inline
warning: the sliders have no effect until it is enabled (requires a Hyprland
restart).

### Night mode (schedule)

The app can lower SDR brightness/saturation in the evening and restore them in
the morning while keeping HDR on. Configure it in the **Night mode (schedule)**
group:

- **Enable schedule** — turns the auto-switch on
- **Schedule source** — **Manual** (fixed hours) or **Sun (internet)**
- **Night brightness / saturation** — values applied during the night window
- **Night starts / ends (hour)** — the manual window (wraps midnight, e.g. 22 → 7)
- **Sun data / Update now** — with **Sun** mode, sunrise/sunset are fetched from
  the internet (IP geolocation + sunrise-sunset.org) for your timezone and cached;
  the window then tracks real sunset → sunrise and refreshes once a day

Your main **HDR** sliders are the day values; the night values override them only
inside the window. Night settings are stored separately in
`~/.config/hdr-manager/settings.json` (not in `monitors.lua`).

### Language

The UI is English by default. Switch to Russian with the **Language** row at the
top of the window; the choice is saved in `settings.json` and applied
immediately (the window re-opens in the new language).

## How it works

On Hyprland 0.56+ the config provider is Lua, so the old
`hyprctl keyword monitor` **does not work**. The app uses:

- **read:** `hyprctl monitors -j` (monitors) and `hyprctl getoption render:... -j`
  (render options)
- **apply:** `hyprctl repl 'hl.monitor({ ... })'` for monitor fields and
  `hl.config({ render = { ... } })` for render options (live)
- **save:** edit `~/.config/hypr/config/monitors.lua` in place, with a backup to
  `monitors.lua.bak` before each write (a missing block for the current output is
  created automatically)

## Structure

```
hdr-manager/
├── main.py               # entry point
├── hyprhdr/
│   ├── backend.py        # hyprctl: read/write, Lua literals
│   ├── configfile.py     # parse and edit monitors.lua
│   ├── reference.py      # database of measured values for known monitors
│   ├── settings.py       # language + night-mode schedule settings (JSON)
│   ├── sun.py            # sunrise/sunset + IP-geolocation lookups
│   ├── i18n.py           # English/Russian UI translations
│   ├── tray.py           # StatusNotifierItem tray icon (D-Bus)
│   └── gui.py            # GTK4/libadwaita interface
├── tests/
│   └── test_hyprhdr.py   # parser + save/create unit tests
└── README.md
```

## Reference values

[`hyprhdr/reference.py`](hyprhdr/reference.py) holds measured characteristics of
known panels. For the **Lenovo Legion Pro 27Q-10 (QD-OLED)**:

| Parameter | Value | Source |
|---|---|---|
| HDR peak | **1000 nits** (3% window, up to 1044 on 1%) | lab501 / smzdm |
| Full-screen white | **258–269 nits** | lab501 / smzdm |
| Black | **0 nits** (OLED) | — |
| Gamut | 99% DCI-P3 · 82.6% BT.2020 · 140% sRGB | lab501 / smzdm |
| Certification | DisplayHDR True Black 400 | lab501 |

The app derives defaults for `max_luminance`, `min_luminance`,
`max_avg_luminance`, `sdr_max_luminance` and gamut flags from these values. The
**"Apply reference"** button resets luminance limits to them. To add your own
monitor, add an entry to `MONITORS`.

## Troubleshooting

If HDR/color settings don't apply after saving, check whether another
`hl.monitor({ ... })` block loads **after** `config/monitors.lua`. On setups
with the Noctalia "Hyprland Settings" panel, `~/.config/hypr/hyprland-settings.lua`
holds a generated `hl.monitor` block; in `hyprland.lua` it must be required
**before** `config.monitors` so your HDR settings win:

```lua
require("hyprland-settings")
require("config.monitors")
```

## Limitations and TODO

- Currently targets `hl.monitor({ ... })` blocks (Lua config). The classic
  single-line `monitor = ...` in a `.conf` is not supported.
- Config editing touches fields inside a `hl.monitor` block for the selected
  `output`; if that output has no block yet, saving creates a new one.
- The night schedule switches day/night values instantly at the hour boundary.
  A smooth (fade) transition between the two is a possible improvement.
