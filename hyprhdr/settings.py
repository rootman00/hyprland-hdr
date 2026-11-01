"""App-level settings (UI language + night-mode schedule).

Kept separate from the Hyprland config (monitors.lua): these are machine-local
preferences, not Hyprland options, and they must survive config edits.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "en",
    "night_enabled": False,
    "night_brightness": 1.0,
    "night_saturation": 1.0,
    "night_start_hour": 22,
    "night_end_hour": 7,
    # sun-based schedule (fetched from the internet, cached locally)
    "schedule_mode": "manual",   # "manual" | "sun"
    "latitude": None,
    "longitude": None,
    "timezone": None,            # IANA name, e.g. "Europe/Moscow"
    "sunset_hour": None,         # local hour float, e.g. 18.7
    "sunrise_hour": None,        # local hour float, e.g. 7.05
    "sun_updated": None,         # ISO date of the last successful fetch
}


def _night_window(settings: dict[str, Any]) -> tuple[float, float]:
    """(start, end) hour floats; the sun schedule wins when it has data."""
    if settings.get("schedule_mode") == "sun":
        sunset = settings.get("sunset_hour")
        sunrise = settings.get("sunrise_hour")
        if sunset is not None and sunrise is not None:
            return float(sunset), float(sunrise)
    return float(settings["night_start_hour"]), float(settings["night_end_hour"])


def is_night(settings: dict[str, Any], now: datetime.datetime | None = None) -> bool:
    """Whether ``now`` falls inside the night window (supports wrapping midnight)."""
    if not settings.get("night_enabled"):
        return False
    now = now or datetime.datetime.now()
    hour = now.hour + now.minute / 60.0 + now.second / 3600.0
    start, end = _night_window(settings)
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def settings_path() -> str:
    """Path to the app settings JSON file."""
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "hdr-manager", "settings.json")


def load_settings(path: str | None = None) -> dict[str, Any]:
    """Load settings, filling any missing keys from ``DEFAULT_SETTINGS``."""
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return merged


def save_settings(settings: dict[str, Any], path: str | None = None) -> None:
    """Write settings as JSON, creating the directory if needed."""
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
