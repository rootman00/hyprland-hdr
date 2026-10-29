"""Взаимодействие с Hyprland: чтение состояния и применение настроек.

Hyprland 0.56+ с Lua-конфигом больше не поддерживает ``hyprctl keyword monitor``.
Правильный способ поменять параметры монитора на лету — выполнить Lua-код через
``hyprctl repl 'hl.monitor({ ... })'``. Чтение текущего состояния — ``hyprctl
monitors -j``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

# Поля монитора, которыми управляет программа. Тип определяет, как значение
# сериализуется в Lua и как форматируется в GUI.
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

# Поля геометрии/прочего, которые нужно сохранять в spec, чтобы hl.monitor
# не сбрасывал их в значения по умолчанию.
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
    """Ошибка выполнения hyprctl (нет Hyprland, нет hyprctl и т.п.)."""


def _run(args: list[str]) -> str:
    """Выполнить hyprctl и вернуть stdout, либо поднять понятную ошибку."""
    exe = shutil.which("hyprctl")
    if exe is None:
        raise HyprctlError("hyprctl не найден в $PATH. Это точно Hyprland-сессия?")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise HyprctlError(f"hyprctl {args[0]} не ответил за 10 с") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise HyprctlError(f"hyprctl {' '.join(args)} завершился с ошибкой: {detail}")
    return proc.stdout


def get_monitors() -> list[dict[str, Any]]:
    """Текущие мониторы из ``hyprctl monitors -j`` (только активные)."""
    raw = _run(["monitors", "-j"])
    data = json.loads(raw)
    return [m for m in data if not m.get("disabled", False)]


def lua_literal(value: Any) -> str:
    """Превратить значение Python в корректный литерал Lua."""
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
    """Собрать Lua-таблицу ``{ key = value, ... }`` из словаря."""
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key} = {lua_literal(value)}")
    return "{ " + ", ".join(parts) + " }"


def apply_spec(fields: dict[str, Any]) -> None:
    """Применить параметры монитора на лету через ``hl.monitor``."""
    spec = build_spec(fields)
    _run(["repl", f"hl.monitor({spec})"])


@dataclass
class Monitor:
    """Объединённое описание монитора: runtime-состояние + конфиг-поля."""

    name: str
    description: str = ""
    make: str = ""
    model: str = ""
    # runtime-значения (hyprctl monitors -j)
    cm: str = "none"
    sdr_brightness: float = 1.0
    sdr_saturation: float = 1.0
    sdr_min_luminance: float = 0.0
    sdr_max_luminance: int = 203
    current_format: str = ""
    hdr_capable: bool = False
    wide_color_capable: bool = False
    # геометрия (для записи в hl.monitor)
    mode: str = ""
    position: str = "auto"
    scale: float = 1.0
    # конфиг-поля (берутся из monitors.lua)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def hdr_on(self) -> bool:
        return self.cm == "hdr"


def runtime_monitor_to_monitor(rt: dict[str, Any]) -> Monitor:
    """Собрать Monitor из записи ``hyprctl monitors -j``."""
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
