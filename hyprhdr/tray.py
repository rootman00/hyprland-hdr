"""System tray integration via StatusNotifierItem (D-Bus).

Implements the ``org.kde.StatusNotifierItem`` interface directly over the
session bus, so no libappindicator/GTK3 binding is required. Left-click triggers
``on_activate`` (the host decides which button that is). The icon is generated
in pure Python (ARGB32 pixmap), so no icon theme or SVG loader is needed.
"""

from __future__ import annotations

import math
import os
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

SNI_NAME = "org.kde.StatusNotifierItem"
SNI_PATH = "/StatusNotifierItem"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Scroll">
      <arg type="i" name="delta" direction="in"/>
      <arg type="s" name="orientation" direction="in"/>
    </method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewStatus"><arg type="s" name="status"/></signal>
    <signal name="NewToolTip"/>
  </interface>
</node>
"""


def _sun_inside(px: float, py: float, cx: float, cy: float, disc_r: float,
                ray_in: float, ray_out: float, ray_hw: float) -> bool:
    """Whether a point lies inside the sun glyph (disc + 8 rectangular rays)."""
    dx = px - cx
    dy = py - cy
    if dx * dx + dy * dy <= disc_r * disc_r:
        return True
    r = math.hypot(dx, dy)
    if r <= 1e-6:
        return False
    for k in range(8):
        ang = k * math.pi / 4.0
        proj = dx * math.cos(ang) + dy * math.sin(ang)
        if ray_in <= proj <= ray_out:
            perp = abs(-dx * math.sin(ang) + dy * math.cos(ang))
            if perp <= ray_hw:
                return True
    return False


# Monochrome ink (white on a transparent background) so the tray glyph follows
# the panel's foreground and works on both light and dark bars.
_INK = (0xFF, 0xFF, 0xFF)


def _render_icon(size: int) -> bytes:
    """Render a monochrome sun glyph as ARGB32 (A,R,G,B per byte).

    A single-color (white) sun disc with 8 rays on a transparent background.
    Rendered at 4× and box-filtered down for crisp anti-aliased edges.
    """
    ss = 4
    S = size * ss
    cx = cy = S * 0.5
    disc_r = S * 0.18
    ray_in = S * 0.24
    ray_out = S * 0.45
    ray_hw = S * 0.055
    r_, g_, b_ = _INK
    data = bytearray()
    for y in range(size):
        for x in range(size):
            covered = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = x * ss + sx + 0.5
                    py = y * ss + sy + 0.5
                    if _sun_inside(px, py, cx, cy, disc_r, ray_in, ray_out, ray_hw):
                        covered += 1
            n = ss * ss
            if covered == 0:
                data += b"\x00\x00\x00\x00"
            else:
                alpha = int(round(covered / n * 255.0))
                data += bytes((alpha, r_, g_, b_))
    return bytes(data)


def icon_pixmaps() -> list[tuple[int, int, bytes]]:
    """Icon in several sizes, ready for the SNI IconPixmap property."""
    return [(s, s, _render_icon(s)) for s in (16, 22, 24, 32, 48, 64, 128)]


class TrayIcon:
    """A minimal StatusNotifierItem. No context menu (right-click does nothing)."""

    def __init__(self, title: str, on_activate: Callable[[], None]):
        self.title = title
        self.on_activate = on_activate
        self._pixmaps = icon_pixmaps()

        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"

        self._owner_id = Gio.bus_own_name_on_connection(
            self._conn, self._name, Gio.BusNameOwnerFlags.NONE, None, None
        )

        node = Gio.DBusNodeInfo.new_for_xml(_XML)
        iface = node.interfaces[0]
        self._conn.register_object(
            SNI_PATH,
            iface,
            self._on_method_call,
            self._on_get_property,
            None,
        )
        self._register_with_watcher()

    def close(self) -> None:
        """Unregister the object and release the bus name (clean shutdown)."""
        try:
            self._conn.unregister_object(SNI_PATH)
        except Exception:  # noqa: BLE001
            pass
        if self._owner_id is not None:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = None

    def set_title(self, title: str) -> None:
        """Update the tooltip/title (e.g. after a language switch)."""
        self.title = title

    def _register_with_watcher(self) -> None:
        try:
            self._conn.call_sync(
                WATCHER_NAME,
                WATCHER_PATH,
                WATCHER_NAME,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._name,)),
                GLib.VariantType("()"),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except GLib.Error:
            # No watcher (no bar/tray) — the icon simply won't be shown.
            pass

    # ------------------------------------------------------------- callbacks
    def _on_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "Activate":
            invocation.return_value(None)
            self.on_activate()
        elif method in ("SecondaryActivate", "ContextMenu", "Scroll"):
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(SNI_NAME + ".Error", "Unknown method")

    def _on_get_property(self, conn, sender, path, iface, name):
        if name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if name == "Id":
            return GLib.Variant("s", "hdr-manager")
        if name == "Title":
            return GLib.Variant("s", self.title)
        if name == "Status":
            return GLib.Variant("s", "Active")
        if name == "WindowId":
            return GLib.Variant("i", 0)
        if name == "IconName":
            return GLib.Variant("s", "")
        if name == "IconPixmap":
            return self._icon_variant(self._pixmaps)
        if name == "IconThemePath":
            return GLib.Variant("s", "")
        if name == "Menu":
            return GLib.Variant("o", "/NO_DBUSMENU")
        if name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if name in ("AttentionIconName", "AttentionMovieName"):
            return GLib.Variant("s", "")
        if name == "AttentionIconPixmap":
            return self._icon_variant([])
        if name == "ToolTip":
            return self._tooltip_variant()
        return None

    # ------------------------------------------------------------- variants
    @staticmethod
    def _icon_variant(pixmaps: list[tuple[int, int, bytes]]) -> GLib.Variant:
        entries = []
        for w, h, data in pixmaps:
            ay = GLib.Variant("ay", list(data))
            entry = GLib.Variant.new_tuple(
                GLib.Variant("i", w), GLib.Variant("i", h), ay
            )
            entries.append(entry)
        return GLib.Variant.new_array(GLib.VariantType("(iiay)"), entries)

    def _tooltip_variant(self) -> GLib.Variant:
        empty = GLib.Variant.new_array(GLib.VariantType("(iiay)"), [])
        return GLib.Variant.new_tuple(
            GLib.Variant("s", self.title),
            empty,
            GLib.Variant("s", self.title),
            GLib.Variant("s", ""),
        )
