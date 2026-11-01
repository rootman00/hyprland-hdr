"""Hyprland interaction: read state and apply settings.

Hyprland 0.56+ with a Lua config no longer supports ``hyprctl keyword monitor``.
The correct way to change monitor settings live is to run Lua code via
``hyprctl repl 'hl.monitor({ ... })'``. Read the current state with ``hyprctl
monitors -j``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

# Monitor fields managed by the app. The type determines how the value is
# serialized to Lua and how it is formatted in the GUI.
COLOR_FIELDS: dict[str, str] = {
    "cm": "str",
    "bitdepth": "int",
    "supports_hdr": "int",
    "supports_wide_color": "int",
    "sdr_eotf": "str",
    "sdrbrightness": "float",
    "sdrsaturation": "float",
    "sdr_min_luminance": "float",
    "sdr_max_luminance": "int",
    "min_luminance": "float",
    "max_luminance": "int",
    "max_avg_luminance": "int",
}

# Geometry/misc fields that must be kept in the spec so that hl.monitor
# does not reset them to defaults.
GEOMETRY_FIELDS: tuple[str, ...] = (
    "output",
    "mode",
    "position",
    "scale",
    "transform",
    "vrr",
    "mirror",
    "disabled",
    "icc",
    "reserved",
)


class HyprctlError(RuntimeError):
    """hyprctl execution error (no Hyprland, no hyprctl, etc.)."""


def _run(args: list[str]) -> str:
    """Run hyprctl and return stdout, or raise a readable error."""
    exe = shutil.which("hyprctl")
    if exe is None:
        raise HyprctlError("hyprctl not found in $PATH. Are you in a Hyprland session?")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise HyprctlError(f"hyprctl {args[0]} timed out after 10 s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise HyprctlError(f"hyprctl {' '.join(args)} failed: {detail}")
    return proc.stdout


def get_monitors() -> list[dict[str, Any]]:
    """Current monitors from ``hyprctl monitors -j`` (active ones only)."""
    raw = _run(["monitors", "-j"])
    data = json.loads(raw)
    return [m for m in data if not m.get("disabled", False)]


def lua_literal(value: Any) -> str:
    """Convert a Python value to a valid Lua literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, float):
        return repr(round(value, 6))
    if isinstance(value, int):
        return str(value)
    return str(value)


def build_spec(fields: dict[str, Any]) -> str:
    """Build a Lua table ``{ key = value, ... }`` from a dict."""
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key} = {lua_literal(value)}")
    return "{ " + ", ".join(parts) + " }"


def apply_spec(fields: dict[str, Any]) -> None:
    """Apply monitor settings live via ``hl.monitor``."""
    spec = build_spec(fields)
    _run(["repl", f"hl.monitor({spec})"])


def _get_option(name: str) -> Any:
    """Read one option via ``hyprctl getoption <name> -j`` (JSON)."""
    raw = _run(["getoption", name, "-j"])
    data = json.loads(raw)
    for key in ("int", "bool", "str", "float"):
        if key in data:
            return data[key]
    return data.get("set", False)


def get_render_options() -> dict[str, int]:
    """Current color-management render options (live values, as 0/1 ints)."""
    def _as_int(value: Any) -> int:
        return 1 if value is True else 0 if value is False else int(value)

    return {
        "cm_enabled": _as_int(_get_option("render:cm_enabled")),
        "cm_auto_hdr": _as_int(_get_option("render:cm_auto_hdr")),
    }


def apply_render(fields: dict[str, Any]) -> None:
    """Apply ``render`` options live via ``hl.config`` (merges, keeps the rest)."""
    spec = build_spec(fields)
    _run(["repl", f"hl.config({{ render = {spec} }})"])


@dataclass
class Monitor:
    """Merged monitor description: runtime state + config fields."""

    name: str
    description: str = ""
    make: str = ""
    model: str = ""
    # runtime values (hyprctl monitors -j)
    cm: str = "none"
    sdr_brightness: float = 1.0
    sdr_saturation: float = 1.0
    sdr_min_luminance: float = 0.0
    sdr_max_luminance: int = 203
    current_format: str = ""
    hdr_capable: bool = False
    wide_color_capable: bool = False
    # geometry (for writing to hl.monitor)
    mode: str = ""
    position: str = "auto"
    scale: float = 1.0
    # config fields (taken from monitors.lua)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def hdr_on(self) -> bool:
        return self.cm == "hdr"


def runtime_monitor_to_monitor(rt: dict[str, Any]) -> Monitor:
    """Build a Monitor from a ``hyprctl monitors -j`` entry."""
    hw = rt.get("hardwareDetails", {}) or {}
    w = rt.get("width", 0)
    h = rt.get("height", 0)
    rr = rt.get("refreshRate", 60)
    return Monitor(
        name=rt.get("name", "?"),
        description=rt.get("description", ""),
        make=str(rt.get("make", "")),
        model=str(rt.get("model", "")),
        cm=str(rt.get("colorManagementPreset", "none")),
        sdr_brightness=float(rt.get("sdrBrightness", 1.0)),
        sdr_saturation=float(rt.get("sdrSaturation", 1.0)),
        sdr_min_luminance=float(rt.get("sdrMinLuminance", 0.0)),
        sdr_max_luminance=int(rt.get("sdrMaxLuminance", 203)),
        current_format=str(rt.get("currentFormat", "")),
        hdr_capable=bool(hw.get("hdr", False)),
        wide_color_capable=bool(hw.get("bt2020", False) or hw.get("chroma", False)),
        mode=f"{w}x{h}@{int(round(rr))}",
        position=f"{int(rt.get('x', 0))}x{int(rt.get('y', 0))}",
        scale=float(rt.get("scale", 1.0)),
    )
