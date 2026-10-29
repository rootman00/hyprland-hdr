"""Reference (factory / measured) values for known monitors.

The app uses these to propose correct HDR tone-mapping defaults
(``max_luminance``, ``min_luminance``, ``max_avg_luminance``,
``sdr_max_luminance`` and gamut/bit-depth flags).

Sources for Legion Pro 27Q-10 (QD-OLED):
- https://lab501.ro/diverse/prezentare-lenovo-legion-pro-27q-10-oled/3
  (258 cd/m² white, 1000 cd/m² peak on a 3% window / 400 cd/m² on 10%,
  99% DCI-P3, 140% sRGB, DisplayHDR True Black 400)
- https://post.smzdm.com/p/a3rqopv7/
  (1044 nits peak on 1%, 1000 on 3%, 786 on 5%, 477 on 10%,
  full-screen 269 nits, 99.44% DCI-P3, 82.56% BT.2020)
"""

from __future__ import annotations

from typing import Any

# Key — a lowercase substring found in the "make model description" string
# from `hyprctl monitors -j`.
MONITORS: dict[str, dict[str, Any]] = {
    "27q-10": {
        "known": True,
        "display_name": "Lenovo Legion Pro 27Q-10 (QD-OLED)",
        "panel": "QD-OLED 26.5\" · 2560×1440 @ 280 Hz",
        "hdr_cert": "DisplayHDR True Black 400 · VESA ClearMR 15000",
        "gamut": "99% DCI-P3 · 82.6% BT.2020 · 140% sRGB",
        # brightness, nits
        "peak_luminance": 1000,       # HDR peak (3% window ≈ 1000 nits)
        "min_luminance": 0,           # OLED — true black
        "fullscreen_white": 258,      # full-screen white ≈ 258–269 nits
        "max_avg_luminance": 250,     # ABL protection (full-screen ceiling)
        "sdr_max_luminance": 250,     # peak white for SDR windows
        # bit depth and gamut
        "bitdepth": 10,
        "supports_hdr": 1,
        "supports_wide_color": 1,
    },
}

# Defaults for panels not in the database (approximate, not measured).
DEFAULT_REFERENCE: dict[str, Any] = {
    "known": False,
    "display_name": "Unknown panel",
    "panel": "",
    "hdr_cert": "",
    "gamut": "",
    "peak_luminance": 800,
    "min_luminance": 0,
    "fullscreen_white": 250,
    "max_avg_luminance": 200,
    "sdr_max_luminance": 203,
    "bitdepth": 10,
    "supports_hdr": 1,
    "supports_wide_color": 1,
}


def lookup(make: str = "", model: str = "", description: str = "") -> dict[str, Any]:
    """Find a reference by monitor make/model/description."""
    combined = f"{make} {model} {description}".lower()
    for pattern, ref in MONITORS.items():
        if pattern in combined:
            return {**DEFAULT_REFERENCE, **ref}
    return dict(DEFAULT_REFERENCE)
