"""Read and edit the Hyprland config (monitors.lua) in place.

A CachyOS/Lua config declares monitors with ``hl.monitor({ ... })`` calls. This
module finds such blocks, parses ``key = value`` fields, and updates individual
fields carefully, preserving comments and formatting.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from .backend import lua_literal

_HL_MONITOR_START = re.compile(r"hl\.monitor\s*\(\s*\{")
_HL_CONFIG_START = re.compile(r"hl\.config\s*\(\s*\{")
_RENDER_START = re.compile(r"render\s*=\s*\{")
_LINE_RE = re.compile(
    r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)"
    r'("[^"]*"|\'[^\']*\'|[^\s,][^,]*?)(\s*,?\s*(?:--.*)?)$'
)


def find_config_path() -> str | None:
    """Return the path to the monitors file if present, else None."""
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


def _unescape(inner: str) -> str:
    """Unescape ``\\"``, ``\\'`` and ``\\\\`` in a Lua string literal."""
    out: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if c == "\\" and i + 1 < n and inner[i + 1] in "\"'\\":
            out.append(inner[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_inline_comment(line: str) -> str:
    """Remove a Lua ``--`` comment, but not when ``--`` is inside a string."""
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c in "\"'":
            quote = c
            i += 1
            while i < n and line[i] != quote:
                if line[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "-" and i + 1 < n and line[i + 1] == "-":
            return line[:i]
        i += 1
    return line


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
        return _unescape(inner)
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
        line = _strip_inline_comment(raw_line)
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1)
        value = _parse_value(m.group(2).rstrip(","))
        spec[key] = value
    return spec


def _matching_brace(text: str, open_idx: int) -> int | None:
    """Index of the ``}`` matching the ``{`` at ``open_idx``, or None.

    Skips ``--`` comments and quoted strings so braces inside them don't break
    the balance.
    """
    n = len(text)
    depth = 0
    j = open_idx
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
                return j
        j += 1
    return None


def _find_bodies(text: str) -> list[tuple[int, int]]:
    """Indices of ``{ ... }`` pairs for each ``hl.monitor({`` (start, end).

    Indices refer to the original text. The scanner skips ``--`` comments and
    quoted strings so braces inside them don't break the balance.
    """
    bodies: list[tuple[int, int]] = []
    i = 0
    while True:
        m = _HL_MONITOR_START.search(text, i)
        if not m:
            break
        brace_start = text.find("{", m.start())
        end = _matching_brace(text, brace_start)
        if end is None:
            break
        bodies.append((brace_start, end))
        i = end + 1
    return bodies


def parse_monitor_specs(text: str) -> list[dict[str, Any]]:
    """All monitors from the config: a list of dicts (including ``output``)."""
    specs: list[dict[str, Any]] = []
    for start, end in _find_bodies(text):
        body = text[start + 1 : end]
        spec = _parse_body(body)
        if "output" in spec:
            specs.append(spec)
    return specs


def _find_render_body(text: str) -> tuple[int, int] | None:
    """Absolute ``(start, end)`` of the ``render = { ... }`` table inside the
    first ``hl.config({ ... })`` block, or None."""
    m = _HL_CONFIG_START.search(text)
    if not m:
        return None
    config_open = text.find("{", m.start())
    config_close = _matching_brace(text, config_open)
    if config_close is None:
        return None
    seg = text[config_open:config_close]
    rm = _RENDER_START.search(seg)
    if not rm:
        return None
    render_open = config_open + seg.find("{", rm.start())
    render_close = _matching_brace(text, render_open)
    if render_close is None:
        return None
    return render_open, render_close


def parse_render_spec(text: str) -> dict[str, Any]:
    """The ``render = { ... }`` fields from an ``hl.config`` block (may be empty)."""
    pos = _find_render_body(text)
    if pos is None:
        return {}
    start, end = pos
    return _parse_body(text[start + 1 : end])


def _append_render_block(text: str, updates: dict[str, Any]) -> str:
    """Append a new ``hl.config({ render = { ... } })`` block at the end."""
    indent = "    "
    lines = [f"{indent}{k} = {lua_literal(v)}," for k, v in updates.items()]
    block = "hl.config({\n    render = {\n" + "\n".join(lines) + "\n    }\n})\n"
    new_text = text
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text + "\n" + block


def _update_render(text: str, updates: dict[str, Any]) -> str:
    """Update the ``render`` fields inside an ``hl.config`` block in place."""
    pos = _find_render_body(text)
    if pos is None:
        return _append_render_block(text, updates)
    start, end = pos
    body = text[start + 1 : end]
    new_body = _apply_updates(body, updates)
    return text[: start + 1] + new_body + text[end:]


def _replace_value(line: str, key: str, new_lua: str) -> str | None:
    """Replace a field value in a line, preserving the comma and comment."""
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


def _ensure_trailing_comma(line: str) -> str:
    """Add a comma after a field value (before a ``--`` comment) if absent."""
    m = _LINE_RE.match(line)
    if not m:
        return line
    if "," in m.group(5):
        return line
    value = m.group(4)
    idx = line.index(value) + len(value)
    return line[:idx] + "," + line[idx:]


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

    # Add missing keys before the closing brace, keeping the Lua valid: ensure
    # the previous field ends with a comma so the appended field is separated.
    present = {m.group(2) for m in (_LINE_RE.match(l) for l in out) if m}
    missing = [k for k, v in updates.items() if k not in present]
    if missing:
        for idx in range(len(out) - 1, -1, -1):
            if _LINE_RE.match(out[idx]):
                out[idx] = _ensure_trailing_comma(out[idx])
                break
        for key in missing:
            out.append(f"{indent}{key} = {lua_literal(updates[key])},")

    return "\n".join(out)


def _build_block(output: str, geometry: dict[str, Any], updates: dict[str, Any]) -> str:
    """Build a new ``hl.monitor({ ... })`` block for an output."""
    indent = "    "
    lines = ["hl.monitor({", f"{indent}output = {lua_literal(output)},"]
    for key in ("mode", "position", "scale", "transform", "vrr"):
        if key in geometry and geometry[key] is not None:
            lines.append(f"{indent}{key} = {lua_literal(geometry[key])},")
    for key, value in updates.items():
        if value is None:
            continue
        lines.append(f"{indent}{key} = {lua_literal(value)},")
    lines.append("})")
    return "\n".join(lines) + "\n"


class MonitorConfigFile:
    """Wrapper around the config file with safe writing (backup + in-place edit)."""

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

    def render_spec(self) -> dict[str, Any]:
        """The ``render = { ... }`` fields from the config (may be empty)."""
        if self.text is None:
            self.load()
        return parse_render_spec(self.text or "")

    def backup(self) -> str:
        bak = f"{self.path}.bak"
        shutil.copy2(self.path, bak)
        return bak

    def save(
        self,
        output: str,
        updates: dict[str, Any],
        geometry: dict[str, Any] | None = None,
        render_updates: dict[str, Any] | None = None,
    ) -> str:
        """Update the monitor block (and optionally the ``render`` block) and
        write the file in one shot, with one backup.

        If no block for ``output`` exists and ``geometry`` is given, a new
        ``hl.monitor({ ... })`` block is created instead of raising. Returns the
        backup path.
        """
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
            if geometry is None:
                raise KeyError(
                    f"hl.monitor({{ output = {output!r}, ... }}) block not found in {self.path}"
                )
            block = _build_block(output, geometry, updates)
            new_text = text
            if new_text and not new_text.endswith("\n"):
                new_text += "\n"
            new_text += "\n" + block
        else:
            start, end = target
            body = text[start + 1 : end]
            new_body = _apply_updates(body, updates)
            new_text = text[: start + 1] + new_body + text[end:]

        if render_updates:
            new_text = _update_render(new_text, render_updates)

        bak = self.backup()
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        self.text = new_text
        return bak
