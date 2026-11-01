"""Graphical interface (GTK4 + libadwaita)."""

from __future__ import annotations

import datetime
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import backend
from . import configfile
from . import i18n
from . import reference
from . import settings
from . import sun
from . import tray

APP_ID = "app.hdrmgr.HdrManager"
_HIDDEN_FLAGS = {"--hidden", "--start-hidden", "--tray"}

# Slider description: (key, title, subtitle, min, max, step, digits, unit)
_SLIDERS: list[tuple] = [
    ("sdrbrightness", "SDR brightness", "Brightness of SDR content inside the HDR container", 0.2, 3.0, 0.05, 2, ""),
    ("sdrsaturation", "SDR saturation", "Compensates washed-out SDR in HDR", 0.0, 3.0, 0.05, 2, ""),
    ("sdr_min_luminance", "SDR min luminance", "Black level for the SDR→HDR tone map (nits)", 0.0, 1.0, 0.01, 2, " nits"),
    ("sdr_max_luminance", "SDR max luminance", "White peak for SDR windows (nits)", 50, 500, 5, 0, " nits"),
    ("max_luminance", "Peak brightness (HDR)", "Hardware peak of the panel in nits", 200, 2000, 25, 0, " nits"),
    ("max_avg_luminance", "Average brightness (ABL)", "Average brightness limit (ABL protection)", 50, 1000, 25, 0, " nits"),
]

_EOTFS = ["default", "srgb", "gamma22"]
_BITDEPTHS = ["8", "10"]

# Color mode: (mode id, cm preset, label, description).
_CM_MODES: list[tuple[str, str, str, str]] = [
    ("sdr", "srgb", "SDR", "sRGB, always SDR"),
    ("hdr", "hdr", "HDR", "Wide gamut + PQ, always HDR"),
    ("auto", "srgb", "Auto HDR", "SDR by default, switch to HDR for HDR content"),
]
_MODE_INDEX: dict[str, int] = {mid: i for i, (mid, _cm, _l, _d) in enumerate(_CM_MODES)}

# Targets for ``render.cm_auto_hdr`` (int 1 = hdr, 2 = hdredid). The value 0
# (disabled) is not offered here: it is what the SDR/HDR modes write.
_AUTO_HDR_TARGETS: list[tuple[int, str]] = [
    (1, "hdr (wide gamut + PQ)"),
    (2, "hdredid (EDID + PQ)"),
]

# ``hl.config render`` options the app manages, kept as ints.
_RENDER_FIELDS = {"cm_enabled", "cm_auto_hdr"}


def _coerce(key: str, value: float | str) -> float | int | str:
    t = backend.COLOR_FIELDS.get(key, "float")
    if t == "int":
        return int(round(float(value)))
    if t == "float":
        return float(value)
    return str(value)


def _fmt_hour(hour: float) -> str:
    """Format an hour float (e.g. 18.7) as ``HH:MM``."""
    h = int(hour)
    m = int(round((hour - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h % 24:02d}:{m:02d}"


class _ScaleRow(Adw.PreferencesRow):
    """A row with a slider and a label for the current value."""

    def __init__(self, key, title, subtitle, minimum, maximum, step, digits, unit):
        super().__init__()
        self.key = key
        self.digits = digits
        self.unit = unit
        self._on_changed = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=title, xalign=0.0, hexpand=True)
        label.add_css_class("heading")
        self.value_label = Gtk.Label(label="", xalign=1.0)
        header.append(label)
        header.append(self.value_label)

        box.append(header)

        if subtitle:
            sub_label = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
            sub_label.add_css_class("dim-label")
            box.append(sub_label)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)

        box.append(self.scale)
        self.set_child(box)

        self.scale.connect("value-changed", self._sync_label)

    def connect_changed(self, callback):
        self._on_changed = callback
        self.scale.connect("value-changed", self._emit)

    def _emit(self, _scale):
        if self._on_changed is not None:
            self._on_changed(self.key, self.scale.get_value())

    def _sync_label(self, _scale):
        value = self.scale.get_value()
        if self.digits == 0:
            self.value_label.set_text(f"{int(round(value))}{self.unit}")
        else:
            self.value_label.set_text(f"{value:.{self.digits}f}{self.unit}")

    def set_value_silent(self, value: float):
        # Apply is suppressed by HdrWindow._set_field via the self._loading flag.
        self.scale.set_value(float(value))


class HdrWindow(Adw.Window):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app)

        self._loading = True
        self._timeout_id: int | None = None
        self.config_path: str | None = None
        self.config_file: configfile.MonitorConfigFile | None = None
        self.runtime: list[backend.Monitor] = []
        self.specs: list[dict] = []
        self.spec: dict = {}
        self.current_name: str = ""
        self._config_missing: bool = False
        self.reference: dict = dict(reference.DEFAULT_REFERENCE)
        self.render_spec: dict = {"cm_enabled": 1, "cm_auto_hdr": 0}
        self.night_settings: dict = settings.load_settings()
        i18n.set_language(str(self.night_settings.get("language", "en")))
        self._night_active: bool | None = None
        self._night_timer_id: int | None = None
        self._sun_fetching: bool = False
        self._destroyed: bool = False
        self._syncing_auto_hdr: bool = False

        self.set_title(i18n.tr("HDR Manager"))
        self.set_default_size(460, 620)

        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.quit_btn = Gtk.Button(label=i18n.tr("Quit"))
        self.quit_btn.connect("clicked", self._on_quit)
        header.pack_start(self.quit_btn)
        self.reset_btn = Gtk.Button(label=i18n.tr("Reset"))
        self.reset_btn.connect("clicked", self._on_reset)
        header.pack_start(self.reset_btn)
        self.save_btn = Gtk.Button(label=i18n.tr("Save to config"))
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save)
        header.pack_end(self.save_btn)
        toolbar.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        toolbar.set_content(scroll)

        page = Adw.PreferencesPage()
        scroll.set_child(page)

        # --- Language group ---
        lang_group = Adw.PreferencesGroup(title=i18n.tr("Language"))
        page.add(lang_group)

        self.lang_combo = Adw.ComboRow(title=i18n.tr("Language"))
        self.lang_combo.set_model(Gtk.StringList.new([i18n.LANGUAGE_LABELS[c] for c in i18n.LANGUAGE_ORDER]))
        self.lang_combo.connect("notify::selected", self._on_language_changed)
        lang_group.add(self.lang_combo)
        self.lang_combo.set_selected(i18n.LANGUAGE_ORDER.index(i18n.get_language()))

        # --- Monitor group ---
        mon_group = Adw.PreferencesGroup(title=i18n.tr("Monitor"))
        page.add(mon_group)

        self.mon_combo = Adw.ComboRow(title=i18n.tr("Monitor"))
        self.mon_combo.connect("notify::selected", self._on_monitor_selected)
        mon_group.add(self.mon_combo)

        self.status_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.status_label.set_margin_top(4)
        self.status_label.set_margin_bottom(4)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("dim-label")
        mon_group.add(self.status_label)

        # --- HDR group ---
        self.hdr_group = Adw.PreferencesGroup(title=i18n.tr("HDR"))
        page.add(self.hdr_group)

        self.mode_combo = Adw.ComboRow(title=i18n.tr("Color mode"))
        self.mode_combo.set_model(Gtk.StringList.new([i18n.tr(label) for _mid, _cm, label, _d in _CM_MODES]))
        self.mode_combo.connect("notify::selected", self._on_mode_changed)
        self.hdr_group.add(self.mode_combo)

        self.mode_desc_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.mode_desc_label.set_margin_start(12)
        self.mode_desc_label.set_margin_end(12)
        self.mode_desc_label.add_css_class("dim-label")
        self.hdr_group.add(self.mode_desc_label)

        self.auto_hdr_combo = Adw.ComboRow(title=i18n.tr("Auto HDR target"))
        self.auto_hdr_combo.set_model(
            Gtk.StringList.new([i18n.tr(label) for _val, label in _AUTO_HDR_TARGETS])
        )
        self.auto_hdr_combo.connect("notify::selected", self._on_auto_hdr_changed)
        self.hdr_group.add(self.auto_hdr_combo)

        self.cm_warning_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.cm_warning_label.set_margin_start(12)
        self.cm_warning_label.set_margin_end(12)
        self.cm_warning_label.add_css_class("warning")
        self.cm_warning_label.set_visible(False)
        self.hdr_group.add(self.cm_warning_label)

        self.scale_rows: dict[str, _ScaleRow] = {}
        for key, title, sub, lo, hi, step, digits, unit in _SLIDERS:
            row = _ScaleRow(key, i18n.tr(title), i18n.tr(sub), lo, hi, step, digits, i18n.tr(unit))
            row.connect_changed(self._on_slider)
            self.scale_rows[key] = row
            self.hdr_group.add(row)

        # --- Advanced ---
        adv_group = Adw.PreferencesGroup(title=i18n.tr("Advanced"))
        page.add(adv_group)
        exp = Adw.ExpanderRow(title=i18n.tr("Color and bit-depth settings"))
        adv_group.add(exp)

        self.eotf_combo = Adw.ComboRow(title=i18n.tr("SDR EOTF (gamma)"))
        self.eotf_combo.set_model(Gtk.StringList.new(_EOTFS))
        self.eotf_combo.connect("notify::selected", self._on_eotf_changed)
        exp.add_row(self.eotf_combo)

        self.bitdepth_combo = Adw.ComboRow(title=i18n.tr("Color depth"))
        self.bitdepth_combo.set_model(Gtk.StringList.new(_BITDEPTHS))
        self.bitdepth_combo.connect("notify::selected", self._on_bitdepth_changed)
        exp.add_row(self.bitdepth_combo)

        # --- Monitor reference ---
        ref_group = Adw.PreferencesGroup(title=i18n.tr("Monitor reference"))
        page.add(ref_group)

        self.ref_expander = Adw.ExpanderRow(title=i18n.tr("Panel reference values"))
        ref_group.add(self.ref_expander)

        self.ref_info_label = Gtk.Label(label="", xalign=0.0, wrap=True, selectable=True)
        info_row = Adw.PreferencesRow()
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_margin_top(8)
        info_box.set_margin_bottom(8)
        info_box.set_margin_start(12)
        info_box.set_margin_end(12)
        info_box.append(self.ref_info_label)
        info_row.set_child(info_box)
        self.ref_expander.add_row(info_row)

        apply_row = Adw.ActionRow(title=i18n.tr("Reset luminance limits to reference"))
        self.ref_apply_btn = Gtk.Button(label=i18n.tr("Apply"))
        self.ref_apply_btn.add_css_class("suggested-action")
        self.ref_apply_btn.connect("clicked", self._on_apply_reference)
        apply_row.add_suffix(self.ref_apply_btn)
        apply_row.set_activatable_widget(self.ref_apply_btn)
        self.ref_expander.add_row(apply_row)

        # --- Night mode ---
        night_group = Adw.PreferencesGroup(title=i18n.tr("Night mode (schedule)"))
        page.add(night_group)

        self.night_switch = Adw.SwitchRow(title=i18n.tr("Enable schedule"))
        self.night_switch.set_subtitle(i18n.tr("Lower SDR brightness/saturation at night (HDR mode)"))
        self.night_switch.connect("notify::active", self._on_night_toggled)
        night_group.add(self.night_switch)

        self.night_status_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.night_status_label.set_margin_start(12)
        self.night_status_label.set_margin_end(12)
        self.night_status_label.add_css_class("dim-label")
        night_group.add(self.night_status_label)

        self.night_brightness_row = _ScaleRow(
            "night_brightness", i18n.tr("Night brightness"),
            i18n.tr("SDR brightness while the schedule is active"), 0.2, 3.0, 0.05, 2, "",
        )
        self.night_brightness_row.connect_changed(self._on_night_slider)
        night_group.add(self.night_brightness_row)

        self.night_saturation_row = _ScaleRow(
            "night_saturation", i18n.tr("Night saturation"),
            i18n.tr("SDR saturation while the schedule is active"), 0.0, 3.0, 0.05, 2, "",
        )
        self.night_saturation_row.connect_changed(self._on_night_slider)
        night_group.add(self.night_saturation_row)

        self.night_start_spin = self._make_hour_spin(self.night_settings["night_start_hour"])
        self.night_end_spin = self._make_hour_spin(self.night_settings["night_end_hour"])
        self.night_start_spin.connect("value-changed", self._on_night_time_changed, "night_start_hour")
        self.night_end_spin.connect("value-changed", self._on_night_time_changed, "night_end_hour")

        start_row = Adw.ActionRow(title=i18n.tr("Night starts (hour)"))
        start_row.add_suffix(self.night_start_spin)
        night_group.add(start_row)
        end_row = Adw.ActionRow(title=i18n.tr("Night ends (hour)"))
        end_row.add_suffix(self.night_end_spin)
        night_group.add(end_row)

        self.schedule_mode_combo = Adw.ComboRow(title=i18n.tr("Schedule source"))
        self.schedule_mode_combo.set_model(
            Gtk.StringList.new([i18n.tr("Manual"), i18n.tr("Sun (internet)")])
        )
        self.schedule_mode_combo.connect("notify::selected", self._on_schedule_mode_changed)
        night_group.add(self.schedule_mode_combo)

        self.sun_status_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.sun_status_label.set_margin_start(12)
        self.sun_status_label.set_margin_end(12)
        self.sun_status_label.add_css_class("dim-label")
        night_group.add(self.sun_status_label)

        sun_update_row = Adw.ActionRow(title=i18n.tr("Sun data"))
        self.sun_update_btn = Gtk.Button(label=i18n.tr("Update now"))
        self.sun_update_btn.connect("clicked", self._on_sun_update)
        sun_update_row.add_suffix(self.sun_update_btn)
        sun_update_row.set_activatable_widget(self.sun_update_btn)
        night_group.add(sun_update_row)

        # Initialize night widgets from settings (self._loading is True).
        self.night_switch.set_active(bool(self.night_settings["night_enabled"]))
        self.night_brightness_row.set_value_silent(float(self.night_settings["night_brightness"]))
        self.night_saturation_row.set_value_silent(float(self.night_settings["night_saturation"]))
        self.schedule_mode_combo.set_selected(
            1 if self.night_settings.get("schedule_mode") == "sun" else 0
        )
        self._update_sun_ui()

        self.toast = Adw.ToastOverlay(child=toolbar)
        self.set_content(self.toast)

        self.connect("close-request", self._on_close_request)

    @staticmethod
    def _make_hour_spin(value: int) -> Gtk.SpinButton:
        spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        spin.set_value(float(value))
        return spin

    def _stop_timers(self) -> None:
        """Remove periodic/timeout sources so the window can be destroyed safely."""
        self._destroyed = True
        self._cancel_pending()
        if self._night_timer_id is not None:
            GLib.source_remove(self._night_timer_id)
            self._night_timer_id = None

    def _build_spec(self, monitor: backend.Monitor, cfg: dict | None) -> dict:
        spec: dict = {}
        if cfg:
            for k in backend.GEOMETRY_FIELDS:
                if k in cfg:
                    spec[k] = cfg[k]
            for k in backend.COLOR_FIELDS:
                if k in cfg:
                    spec[k] = cfg[k]
        else:
            spec["output"] = monitor.name
            spec["mode"] = monitor.mode
            spec["position"] = monitor.position
            spec["scale"] = monitor.scale

        # Runtime values take priority, except cm: keep the configured preset
        # (which may be "auto") instead of the runtime-resolved one.
        spec["output"] = monitor.name
        spec.setdefault("cm", monitor.cm)
        spec["sdrbrightness"] = monitor.sdr_brightness
        spec["sdrsaturation"] = monitor.sdr_saturation
        spec["sdr_min_luminance"] = monitor.sdr_min_luminance
        spec["sdr_max_luminance"] = monitor.sdr_max_luminance
        spec.setdefault("mode", monitor.mode)
        spec.setdefault("position", monitor.position)
        spec.setdefault("scale", monitor.scale)

        # Hardware fields missing at runtime are taken from the panel reference.
        ref = self.reference
        spec.setdefault("bitdepth", ref["bitdepth"])
        spec.setdefault("max_luminance", ref["peak_luminance"])
        spec.setdefault("min_luminance", ref["min_luminance"])
        spec.setdefault("max_avg_luminance", ref["max_avg_luminance"])
        spec.setdefault("supports_hdr", ref["supports_hdr"])
        spec.setdefault("supports_wide_color", ref["supports_wide_color"])
        return spec

    def _cfg_for(self, name: str) -> dict | None:
        for s in self.specs:
            if s.get("output") == name:
                return s
        return None

    def _mode_of(self) -> str:
        """Current color mode id ("sdr" | "hdr" | "auto") from cm + cm_auto_hdr.

        HDR is determined by the ``cm`` preset; auto-HDR is a non-HDR preset
        plus ``render.cm_auto_hdr >= 1``.
        """
        cm = str(self.spec.get("cm", "srgb"))
        if cm in ("hdr", "hdredid"):
            return "hdr"
        if int(self.render_spec.get("cm_auto_hdr", 0)) >= 1:
            return "auto"
        return "sdr"

    def _load_state(self) -> None:
        try:
            rt = backend.get_monitors()
        except backend.HyprctlError as exc:
            rt = []
            self._toast(str(exc), error=True)
        self.runtime = [backend.runtime_monitor_to_monitor(m) for m in rt]
        # (re-)read config
        self.specs = []
        self.config_path = configfile.find_config_path()
        if self.config_path:
            self.config_file = configfile.MonitorConfigFile(self.config_path)
            try:
                self.specs = self.config_file.specs()
            except OSError as exc:
                self._toast(i18n.tr("Failed to read config: {exc}").format(exc=exc), error=True)
        self.save_btn.set_sensitive(self.config_path is not None)

        # Read render options (live), used for the auto-HDR toggle and apply.
        try:
            self.render_spec = backend.get_render_options()
        except backend.HyprctlError as exc:
            self.render_spec = {"cm_enabled": 1, "cm_auto_hdr": 0}
            self._toast(str(exc), error=True)

        names = [m.name for m in self.runtime]
        self.mon_combo.set_model(Gtk.StringList.new(names))
        if names:
            self.mon_combo.set_selected(0)
            self._show_monitor(0)

        # Apply the night schedule on load and start the periodic checker.
        self._refresh_night()
        self._update_sun_ui()
        self._maybe_refresh_sun()
        if self._night_timer_id is None:
            self._night_timer_id = GLib.timeout_add_seconds(60, self._night_tick)

    def _show_monitor(self, index: int) -> None:
        if index < 0 or index >= len(self.runtime):
            return
        self._loading = True
        mon = self.runtime[index]
        self.current_name = mon.name
        self.reference = reference.lookup(mon.make, mon.model, mon.description)
        self.spec = self._build_spec(mon, self._cfg_for(mon.name))
        self._config_missing = self.config_path is not None and self._cfg_for(mon.name) is None

        self._update_reference(mon)

        mode = self._mode_of()
        # Migrate the legacy "auto" alias (old auto-HDR wrote cm = "auto");
        # the corrected auto-HDR uses the non-HDR "srgb" base preset.
        if mode == "auto" and str(self.spec.get("cm", "")) == "auto":
            self.spec["cm"] = "srgb"
        self.mode_combo.set_selected(_MODE_INDEX.get(mode, 0))
        self.mode_desc_label.set_text(i18n.tr(_CM_MODES[_MODE_INDEX.get(mode, 0)][3]))
        self._sync_auto_hdr_combo()
        for key, row in self.scale_rows.items():
            row.set_value_silent(float(self.spec.get(key, 0)))

        eotf = str(self.spec.get("sdr_eotf", "default"))
        if eotf in _EOTFS:
            self.eotf_combo.set_selected(_EOTFS.index(eotf))
        bd = str(self.spec.get("bitdepth", 10))
        if bd in _BITDEPTHS:
            self.bitdepth_combo.set_selected(_BITDEPTHS.index(bd))

        self._update_status()
        self._update_cm_warning()
        self._loading = False

    def _update_cm_warning(self) -> None:
        """Warn when color management is off (then every slider is a no-op)."""
        if int(self.render_spec.get("cm_enabled", 1)) == 0:
            self.cm_warning_label.set_text(i18n.tr(
                "Color management is disabled (render.cm_enabled = 0). "
                "The sliders have no effect until it is enabled (requires a Hyprland restart)."
            ))
            self.cm_warning_label.set_visible(True)
        else:
            self.cm_warning_label.set_visible(False)

    def _update_reference(self, mon: backend.Monitor) -> None:
        ref = self.reference
        if ref.get("known"):
            lines = [ref["display_name"]]
            if ref["panel"]:
                lines.append(ref["panel"])
            if ref["hdr_cert"]:
                lines.append(ref["hdr_cert"])
            if ref["gamut"]:
                lines.append(ref["gamut"])
            peak = f"{i18n.tr('HDR peak')}: {ref['peak_luminance']} {i18n.tr('nits')}"
            white = f"{i18n.tr('full-screen white')}: {ref['fullscreen_white']} {i18n.tr('nits')}"
            black = f"{i18n.tr('black')}: {ref['min_luminance']} {i18n.tr('nits')}"
            lines.append(" · ".join([peak, white, black]))
            self.ref_info_label.set_text("\n".join(lines))
            self.ref_apply_btn.set_sensitive(True)
        else:
            self.ref_info_label.set_text(
                i18n.tr('No reference data for "{name}".\nGeneric defaults will be used.').format(
                    name=mon.description or mon.name
                )
            )
            self.ref_apply_btn.set_sensitive(False)

    def _update_status(self) -> None:
        mon = next((m for m in self.runtime if m.name == self.current_name), None)
        if mon is None:
            self.status_label.set_text("")
            return
        fmt = mon.current_format or ""
        bits = i18n.tr("10-bit") if ("2101010" in fmt or "101010" in fmt) else i18n.tr("8-bit")
        parts = [mon.name]
        if mon.hdr_on:
            parts.append(i18n.tr("HDR (PQ)"))
        else:
            parts.append(i18n.tr("SDR"))
        if self._mode_of() == "auto":
            parts.append(i18n.tr("auto-HDR"))
        parts.append(bits)
        if mon.description:
            parts.append(mon.description)
        if self._config_missing:
            parts.append(i18n.tr("no config block — one will be created on save"))
        self.status_label.set_text(" · ".join(parts))

    # ------------------------------------------------------------ apply logic
    def _cancel_pending(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _set_field(self, key: str, value: float | str) -> None:
        if key in _RENDER_FIELDS:
            self.render_spec[key] = int(round(float(value)))
        else:
            self.spec[key] = _coerce(key, value)
        if self._loading:
            return
        self._cancel_pending()
        self._timeout_id = GLib.timeout_add(120, self._flush)

    def _flush(self) -> bool:
        self._timeout_id = None
        try:
            backend.apply_spec(self._effective_spec())
            backend.apply_render(self.render_spec)
            self._toast(i18n.tr("Applied"))
        except backend.HyprctlError as exc:
            self._toast(str(exc), error=True)
        return GLib.SOURCE_REMOVE

    def _toast(self, text: str, error: bool = False) -> None:
        toast = Adw.Toast(title=text)
        if error:
            toast.set_timeout(4)
        self.toast.add_toast(toast)

    def _save_settings(self) -> None:
        """Persist app settings, surfacing (not crashing on) write failures."""
        try:
            settings.save_settings(self.night_settings)
        except OSError as exc:
            self._toast(i18n.tr("Could not save settings: {exc}").format(exc=exc), error=True)

    # ------------------------------------------------------------ night mode
    def _is_night(self) -> bool:
        return settings.is_night(self.night_settings)

    def _effective_spec(self) -> dict:
        """The monitor spec to apply, with night overrides when active."""
        spec = dict(self.spec)
        if self._night_active:
            spec["sdrbrightness"] = float(self.night_settings["night_brightness"])
            spec["sdrsaturation"] = float(self.night_settings["night_saturation"])
        return spec

    def _update_night_ui(self) -> None:
        night = self._night_active is True
        for key in ("sdrbrightness", "sdrsaturation"):
            if key in self.scale_rows:
                self.scale_rows[key].set_sensitive(not night)
        if not self.night_settings.get("night_enabled"):
            self.night_status_label.set_text(i18n.tr("Schedule disabled"))
        elif night:
            self.night_status_label.set_text(i18n.tr("Active — using night values"))
        else:
            self.night_status_label.set_text(i18n.tr("Inactive — using day values"))

    def _refresh_night(self) -> None:
        was = self._night_active
        self._night_active = self._is_night()
        self._update_night_ui()
        if self._loading or not self.current_name:
            return
        if self._night_active or (was is not None and was != self._night_active):
            self._cancel_pending()
            self._flush()

    def _night_tick(self) -> bool:
        was = self._night_active
        self._night_active = self._is_night()
        if self._night_active != was:
            self._update_night_ui()
            if self.current_name:
                self._cancel_pending()
                self._flush()
        self._maybe_refresh_sun()
        return GLib.SOURCE_CONTINUE

    # ------------------------------------------------------- sun-based schedule
    def _update_sun_ui(self) -> None:
        sun_mode = self.night_settings.get("schedule_mode") == "sun"
        self.night_start_spin.set_sensitive(not sun_mode)
        self.night_end_spin.set_sensitive(not sun_mode)
        self.sun_update_btn.set_sensitive(sun_mode)
        if not sun_mode:
            self.sun_status_label.set_text("")
            return
        if self._sun_fetching:
            self.sun_status_label.set_text(i18n.tr("Fetching sun times…"))
            return
        ss = self.night_settings.get("sunset_hour")
        sr = self.night_settings.get("sunrise_hour")
        if ss is None or sr is None:
            self.sun_status_label.set_text(i18n.tr("No sun data yet."))
            return
        upd = self.night_settings.get("sun_updated") or "?"
        self.sun_status_label.set_text(
            f"{i18n.tr('Sunset')} {_fmt_hour(ss)} · "
            f"{i18n.tr('Sunrise')} {_fmt_hour(sr)} · "
            f"{i18n.tr('updated')} {upd}"
        )

    def _maybe_refresh_sun(self) -> None:
        if self.night_settings.get("schedule_mode") != "sun":
            return
        if self.night_settings.get("sun_updated") == datetime.date.today().isoformat():
            return
        self._start_sun_fetch()

    def _start_sun_fetch(self, force: bool = False) -> None:
        if self._sun_fetching:
            return
        if not force and self.night_settings.get("sun_updated") == datetime.date.today().isoformat():
            return
        self._sun_fetching = True
        self._update_sun_ui()
        threading.Thread(target=self._sun_worker, daemon=True).start()

    def _sun_worker(self) -> None:
        ns = self.night_settings
        lat = ns.get("latitude")
        lng = ns.get("longitude")
        tz = ns.get("timezone")
        try:
            if lat is None or lng is None:
                coords = sun.fetch_coordinates()
                if coords:
                    lat = coords["latitude"]
                    lng = coords["longitude"]
                    tz = coords["timezone"]
            if lat is None or lng is None:
                raise RuntimeError("no coordinates")
            times = sun.fetch_sun_times(lat, lng, tz_name=tz)
            GLib.idle_add(self._on_sun_result, times, lat, lng, tz)
        except Exception as exc:  # noqa: BLE001 - network/parse errors are expected
            GLib.idle_add(self._on_sun_error, str(exc))

    def _on_sun_result(self, times, lat, lng, tz) -> None:
        if self._destroyed:
            return
        self._sun_fetching = False
        self.night_settings["sunset_hour"] = times["sunset"]
        self.night_settings["sunrise_hour"] = times["sunrise"]
        self.night_settings["sun_updated"] = datetime.date.today().isoformat()
        self.night_settings["latitude"] = lat
        self.night_settings["longitude"] = lng
        self.night_settings["timezone"] = tz
        self._save_settings()
        self._update_sun_ui()
        self._refresh_night()

    def _on_sun_error(self, msg) -> None:
        if self._destroyed:
            return
        self._sun_fetching = False
        self._toast(i18n.tr("Could not fetch sun times: {msg}").format(msg=msg), error=True)
        self._update_sun_ui()

    def _on_schedule_mode_changed(self, combo, _pspec):
        idx = combo.get_selected()
        mode = "sun" if idx == 1 else "manual"
        self.night_settings["schedule_mode"] = mode
        if self._loading:
            return
        self._save_settings()
        if mode == "sun":
            self._start_sun_fetch(force=True)
        self._update_sun_ui()
        self._refresh_night()

    def _on_sun_update(self, _btn):
        self._start_sun_fetch(force=True)

    # -------------------------------------------------------------- handlers
    def _on_language_changed(self, combo, _pspec):
        if self._loading:
            return
        idx = combo.get_selected()
        if idx < 0 or idx >= len(i18n.LANGUAGE_ORDER):
            return
        code = i18n.LANGUAGE_ORDER[idx]
        if code == i18n.get_language():
            return
        i18n.set_language(code)
        self.night_settings["language"] = code
        self._save_settings()

        app = self.get_application()
        old = self
        old._stop_timers()
        new = HdrWindow(app)
        new._load_state()
        app.win = new
        if app.tray is not None:
            app.tray.set_title(i18n.tr("HDR Manager"))
        new.present()
        GLib.idle_add(old.destroy)

    def _on_monitor_selected(self, combo, _pspec):
        if not self._loading:
            self._show_monitor(combo.get_selected())

    def _on_mode_changed(self, combo, _pspec):
        if self._loading:
            return
        idx = combo.get_selected()
        if idx < 0 or idx >= len(_CM_MODES):
            return
        mid, _cm, _label, desc = _CM_MODES[idx]
        self.mode_desc_label.set_text(i18n.tr(desc))
        if mid == "auto":
            target = _AUTO_HDR_TARGETS[self.auto_hdr_combo.get_selected()][0]
            self._set_field("cm", "srgb")
            self._set_field("cm_auto_hdr", target)
            self._set_field("supports_hdr", 1)
            self._set_field("supports_wide_color", 1)
        elif mid == "hdr":
            self._set_field("cm", "hdr")
            self._set_field("cm_auto_hdr", 0)
            self._set_field("supports_hdr", 1)
            self._set_field("supports_wide_color", 1)
        else:
            self._set_field("cm", "srgb")
            self._set_field("cm_auto_hdr", 0)
        self._sync_auto_hdr_combo()

    def _sync_auto_hdr_combo(self) -> None:
        val = int(self.render_spec.get("cm_auto_hdr", 0))
        idx = None
        for i, (target, _label) in enumerate(_AUTO_HDR_TARGETS):
            if target == val:
                idx = i
                break
        # Only move the combo when it maps to a real target (1 or 2); a value
        # of 0 (SDR/HDR mode) leaves the remembered target untouched.
        if idx is not None:
            self._syncing_auto_hdr = True
            try:
                self.auto_hdr_combo.set_selected(idx)
            finally:
                self._syncing_auto_hdr = False
        self.auto_hdr_combo.set_sensitive(self._mode_of() == "auto")

    def _on_auto_hdr_changed(self, combo, _pspec):
        if self._loading or self._syncing_auto_hdr:
            return
        idx = combo.get_selected()
        if idx < 0 or idx >= len(_AUTO_HDR_TARGETS):
            return
        self._set_field("cm_auto_hdr", _AUTO_HDR_TARGETS[idx][0])

    def _on_slider(self, key: str, value: float) -> None:
        self._set_field(key, value)

    def _on_eotf_changed(self, combo, _pspec):
        if self._loading:
            return
        self._set_field("sdr_eotf", _EOTFS[combo.get_selected()])

    def _on_bitdepth_changed(self, combo, _pspec):
        if self._loading:
            return
        self._set_field("bitdepth", int(_BITDEPTHS[combo.get_selected()]))

    def _on_night_toggled(self, switch, _pspec):
        self.night_settings["night_enabled"] = switch.get_active()
        if not self._loading:
            self._save_settings()
            self._refresh_night()

    def _on_night_slider(self, key: str, value: float) -> None:
        self.night_settings[key] = float(value)
        if self._loading:
            return
        self._save_settings()
        self._refresh_night()

    def _on_night_time_changed(self, spin, key: str) -> None:
        self.night_settings[key] = int(spin.get_value())
        if self._loading:
            return
        self._save_settings()
        self._refresh_night()

    def _on_reset(self, _btn):
        self._load_state()
        self._toast(i18n.tr("Reloaded from Hyprland"))

    def _on_quit(self, _btn):
        self.get_application().quit()

    def _on_close_request(self, *_args):
        # Hide to the tray instead of quitting.
        self.hide()
        return True

    def _reference_fields(self) -> dict:
        ref = self.reference
        return {
            "max_luminance": ref["peak_luminance"],
            "min_luminance": ref["min_luminance"],
            "max_avg_luminance": ref["max_avg_luminance"],
            "sdr_max_luminance": ref["sdr_max_luminance"],
            "bitdepth": ref["bitdepth"],
            "supports_hdr": ref["supports_hdr"],
            "supports_wide_color": ref["supports_wide_color"],
        }

    def _on_apply_reference(self, _btn):
        if not self.reference.get("known"):
            self._toast(i18n.tr("No reference data for this panel"), error=True)
            return
        fields = self._reference_fields()
        self._loading = True
        try:
            for key, value in fields.items():
                self.spec[key] = value
            for key in ("max_luminance", "max_avg_luminance", "sdr_max_luminance"):
                if key in self.scale_rows:
                    self.scale_rows[key].set_value_silent(float(self.spec[key]))
            bd = str(self.spec["bitdepth"])
            if bd in _BITDEPTHS:
                self.bitdepth_combo.set_selected(_BITDEPTHS.index(bd))
        finally:
            self._loading = False
        self._cancel_pending()
        self._flush()
        self._toast(i18n.tr("Reference values applied"))

    def _on_save(self, _btn):
        if self.config_file is None:
            self._toast(i18n.tr("Config file not found"), error=True)
            return
        updates = {
            k: self.spec[k]
            for k in backend.COLOR_FIELDS
            if k in self.spec
        }
        geometry = {
            k: self.spec[k]
            for k in ("mode", "position", "scale")
            if k in self.spec
        }
        try:
            bak = self.config_file.save(
                self.current_name,
                updates,
                geometry=geometry,
                render_updates=dict(self.render_spec),
            )
            self._toast(i18n.tr("Saved (backup: {bak})").format(bak=bak))
        except (OSError, KeyError) as exc:
            self._toast(i18n.tr("Save failed: {exc}").format(exc=exc), error=True)


class HdrApp(Adw.Application):
    def __init__(self, start_hidden: bool = False):
        super().__init__(application_id=APP_ID)
        self.start_hidden = start_hidden
        self.win: HdrWindow | None = None
        self.tray: tray.TrayIcon | None = None

    def do_activate(self):
        first = self.win is None
        if self.win is None:
            self.win = HdrWindow(self)
            self.win._load_state()
        if self.tray is None:
            try:
                self.tray = tray.TrayIcon(i18n.tr("HDR Manager"), self._toggle_window)
            except Exception as exc:  # noqa: BLE001
                print(f"tray unavailable: {exc}", file=sys.stderr)
        # Start hidden only on the very first activation; a later launch
        # (single-instance remote activation) should bring the window up.
        if first and self.start_hidden:
            return
        self.win.present()

    def do_shutdown(self):
        if self.win is not None:
            self.win._stop_timers()
        if self.tray is not None:
            self.tray.close()
            self.tray = None
        super().do_shutdown()

    def _toggle_window(self):
        if self.win is None:
            return
        if self.win.get_visible():
            self.win.hide()
        else:
            self.win.present()


def main() -> int:
    start_hidden = bool(_HIDDEN_FLAGS & set(sys.argv))
    argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a not in _HIDDEN_FLAGS]
    app = HdrApp(start_hidden=start_hidden)
    return app.run(argv)
