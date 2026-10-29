# hdr-manager

A small GUI for visual HDR management on Wayland (Hyprland 0.56+ with a
**Lua config**, e.g. CachyOS). Toggle HDR and adjust SDR tone-mapping live.

## Features (v1)

- **HDR** toggle (`cm = "hdr"` ↔ `cm = "srgb"`)
- **SDR brightness** (`sdrbrightness`) — the main control against washed-out SDR in HDR
- **SDR saturation** (`sdrsaturation`)
- **SDR max luminance** (`sdr_max_luminance`, nits)
- **Peak brightness** of the HDR panel (`max_luminance`, nits)
- **Average brightness / ABL** (`max_avg_luminance`)
- **SDR EOTF** (gamma) and **color depth** (8/10-bit)
- **Monitor reference** — measured panel values and an "Apply reference" button
  that resets luminance limits to factory values
- Live apply (slider → monitor immediately) and **save to config**

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

## How it works

On Hyprland 0.56+ the config provider is Lua, so the old
`hyprctl keyword monitor` **does not work**. The app uses:

- **read:** `hyprctl monitors -j`
- **apply:** `hyprctl repl 'hl.monitor({ ... })'` (call the Lua API live)
- **save:** edit `~/.config/hypr/config/monitors.lua` in place, with a backup to
  `monitors.lua.bak` before each write

## Structure

```
hdr-manager/
├── main.py               # entry point
├── hyprhdr/
│   ├── backend.py        # hyprctl: read/write, Lua literals
│   ├── configfile.py     # parse and edit monitors.lua
│   ├── reference.py      # database of measured values for known monitors
│   └── gui.py            # GTK4/libadwaita interface
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

## Limitations and TODO

- Currently targets `hl.monitor({ ... })` blocks (Lua config). The classic
  single-line `monitor = ...` in a `.conf` is not supported.
- Config editing only touches fields inside an existing `hl.monitor` block for
  the selected `output`.
- **Next:** automatic adjustment — a time-of-day night mode (lowering
  brightness/saturation in the evening) and/or content-based auto-HDR
  (`render.cm_auto_hdr`). The extension point is
  `hyprhdr/gui.py::HdrWindow._set_field`; parameter access is already isolated
  in `backend.apply_spec`.
