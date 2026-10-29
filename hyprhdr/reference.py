"""Справочные (заводские / измеренные) значения для известных мониторов.

По этим данным программа предлагает корректные дефолты для HDR-тонмаппинга
(``max_luminance``, ``min_luminance``, ``max_avg_luminance``, ``sdr_max_luminance``
и флаги цветового охвата/разрядности).

Источники для Legion Pro 27Q-10 (QD-OLED):
- https://lab501.ro/diverse/prezentare-lenovo-legion-pro-27q-10-oled/3
  (белый 258 кд/м², пик 1000 кд/м² на 3% окне / 400 кд/м² на 10%,
  99% DCI-P3, 140% sRGB, DisplayHDR True Black 400)
- https://post.smzdm.com/p/a3rqopv7/
  (пик 1044 нит на 1%, 1000 на 3%, 786 на 5%, 477 на 10%,
  полноэкранный 269 нит, 99.44% DCI-P3, 82.56% BT.2020)
"""

from __future__ import annotations

from typing import Any

# Ключ — подстрока (в нижнем регистре), которая встречается в строке
# "make model description" из `hyprctl monitors -j`.
MONITORS: dict[str, dict[str, Any]] = {
    "27q-10": {
        "known": True,
        "display_name": "Lenovo Legion Pro 27Q-10 (QD-OLED)",
        "panel": "QD-OLED 26.5\" · 2560×1440 @ 280 Гц",
        "hdr_cert": "DisplayHDR True Black 400 · VESA ClearMR 15000",
        "gamut": "99% DCI-P3 · 82.6% BT.2020 · 140% sRGB",
        # яркость, ниты
        "peak_luminance": 1000,       # HDR-пик (3% окно ≈ 1000 нит)
        "min_luminance": 0,           # OLED — истинный чёрный
        "fullscreen_white": 258,      # полноэкранный белый ≈ 258–269 нит
        "max_avg_luminance": 250,     # защита от ABL (полноэкранный потолок)
        "sdr_max_luminance": 250,     # пик белого для SDR-окон
        # разрядность и охват
        "bitdepth": 10,
        "supports_hdr": 1,
        "supports_wide_color": 1,
    },
}

# Дефолты для панелей, которых нет в базе (примерные, не измеренные).
DEFAULT_REFERENCE: dict[str, Any] = {
    "known": False,
    "display_name": "Неизвестная панель",
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
    """Найти референс по make/model/description монитора."""
    combined = f"{make} {model} {description}".lower()
    for pattern, ref in MONITORS.items():
        if pattern in combined:
            return {**DEFAULT_REFERENCE, **ref}
    return dict(DEFAULT_REFERENCE)
