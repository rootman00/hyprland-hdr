"""Чтение и правка Hyprland-конфига (monitors.lua) на месте.

Конфиг CachyOS/Lua объявляет мониторы вызовом ``hl.monitor({ ... })``. Этот
модуль умеет находить такие блоки, разбирать поля ``ключ = значение`` и
аккуратно обновлять отдельные поля, сохраняя комментарии и форматирование.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from .backend import lua_literal

_HL_MONITOR_START = re.compile(r"hl\.monitor\s*\(\s*\{")
_LINE_RE = re.compile(
    r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)"
    r'("[^"]*"|\'[^\']*\'|[^\s,][^,]*?)(\s*,?\s*(?:--.*)?)$'
)


def find_config_path() -> str | None:
    """Вернуть путь к файлу мониторов, если он есть (иначе None)."""
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    candidates = [
        os.path.join(xdg, "hypr", "config", "monitors.lua"),
        os.path.join(xdg, "hypr", "monitors.lua"),
        os.path.join(xdg, "hypr", "monitors.conf"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _parse_value(raw: str) -> Any:
    raw = raw.strip().rstrip(",")
    if not raw:
        return None
    if raw[0] in "\"'":
        quote = raw[0]
        if len(raw) >= 2 and raw[-1] == quote:
            inner = raw[1:-1]
        else:
            inner = raw[1:]
        return (
            inner.replace('\\"', '"')
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _parse_body(body: str) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    for raw_line in body.splitlines():
        line = raw_line
        idx = line.find("--")
        if idx >= 0:
            line = line[:idx]
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1)
        value = _parse_value(m.group(2).rstrip(","))
        spec[key] = value
    return spec


def _find_bodies(text: str) -> list[tuple[int, int]]:
    """Индексы пар ``{ ... }`` для каждого ``hl.monitor({`` (start, end).

    Индексы отсчитываются в оригинальном тексте. Сканер пропускает ``--``
    комментарии и строки в кавычках, чтобы скобки внутри них не ломали баланс.
    """
    bodies: list[tuple[int, int]] = []
    n = len(text)
    i = 0
    while True:
        m = _HL_MONITOR_START.search(text, i)
        if not m:
            break
        brace_start = text.find("{", m.start())
        depth = 0
        j = brace_start
        while j < n:
            c = text[j]
            if c == "-" and j + 1 < n and text[j + 1] == "-":
                nl = text.find("\n", j)
                j = n if nl == -1 else nl
                continue
            if c in "\"'":
                quote = c
                j += 1
                while j < n and text[j] != quote:
                    if text[j] == "\\":
                        j += 1
                    j += 1
                j += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    bodies.append((brace_start, j))
                    break
            j += 1
        i = j + 1
    return bodies


def parse_monitor_specs(text: str) -> list[dict[str, Any]]:
    """Все мониторы из конфига: список словарей (включая ``output``)."""
    specs: list[dict[str, Any]] = []
    for start, end in _find_bodies(text):
        body = text[start + 1 : end]
        spec = _parse_body(body)
        if "output" in spec:
            specs.append(spec)
    return specs


def _replace_value(line: str, key: str, new_lua: str) -> str | None:
    """Заменить значение поля в строке, сохранив запятую и комментарий."""
    m = _LINE_RE.match(line)
    if m and m.group(2) == key:
        return m.group(1) + m.group(2) + m.group(3) + new_lua + m.group(5)
    return None


def _indent_of(body: str) -> str:
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped:
            return line[: len(line) - len(stripped)]
    return "    "


def _apply_updates(body: str, updates: dict[str, Any]) -> str:
    indent = _indent_of(body)
    lines = body.split("\n")
    out: list[str] = []

    for line in lines:
        replaced = False
        for key, value in updates.items():
            new_line = _replace_value(line, key, lua_literal(value))
            if new_line is not None:
                out.append(new_line)
                replaced = True
                break
        if not replaced:
            out.append(line)

    # Добавить недостающие ключи перед закрывающей скобкой.
    present = {m.group(2) for m in (_LINE_RE.match(l) for l in out) if m}
    for key, value in updates.items():
        if key not in present:
            out.append(f"{indent}{key} = {lua_literal(value)},")

    return "\n".join(out)


class MonitorConfigFile:
    """Обёртка над файлом конфига с безопасной записью (бэкап + in-place)."""

    def __init__(self, path: str):
        self.path = path
        self.text: str | None = None

    def load(self) -> str:
        with open(self.path, "r", encoding="utf-8") as fh:
            self.text = fh.read()
        return self.text

    def specs(self) -> list[dict[str, Any]]:
        if self.text is None:
            self.load()
        return parse_monitor_specs(self.text or "")

    def backup(self) -> str:
        bak = f"{self.path}.bak"
        shutil.copy2(self.path, bak)
        return bak

    def save(self, output: str, updates: dict[str, Any]) -> str:
        """Обновить поля монитора ``output`` и записать файл. Возвращает путь бэкапа."""
        if self.text is None:
            self.load()
        text = self.text or ""
        bodies = _find_bodies(text)
        target = None
        for start, end in bodies:
            spec = _parse_body(text[start + 1 : end])
            if spec.get("output") == output:
                target = (start, end)
                break
        if target is None:
            raise KeyError(
                f"Блок hl.monitor({{ output = {output!r}, ... }}) не найден в {self.path}"
            )

        start, end = target
        body = text[start + 1 : end]
        new_body = _apply_updates(body, updates)
        new_text = text[: start + 1] + new_body + text[end:]

        bak = self.backup()
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        self.text = new_text
        return bak
