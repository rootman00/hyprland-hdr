"""Графический интерфейс (GTK4 + libadwaita)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import backend
from . import configfile
from . import reference

APP_ID = "app.hdrmgr.HdrManager"

# Описание слайдеров: (ключ, заголовок, подпись, мин, макс, шаг, знаков, ед., тип)
_SLIDERS: list[tuple] = [
    ("sdrbrightness", "SDR-яркость", "Яркость SDR-контента внутри HDR-контейнера", 0.2, 3.0, 0.05, 2, "", "float"),
    ("sdrsaturation", "SDR-насыщенность", "Компенсирует «вымытость» SDR в HDR", 0.0, 3.0, 0.05, 2, "", "float"),
    ("sdr_max_luminance", "SDR max luminance", "Пик белого для SDR-окон (ниты)", 50, 500, 5, 0, " нит", "int"),
    ("max_luminance", "Пиковая яркость (HDR)", "Аппаратный пик панели в нитах", 200, 2000, 25, 0, " нит", "int"),
    ("max_avg_luminance", "Средняя яркость (ABL)", "Ограничение средней яркости (защита от ABL)", 50, 1000, 25, 0, " нит", "int"),
]

_EOTFS = ["default", "srgb", "gamma22"]
_BITDEPTHS = ["8", "10"]


def _coerce(key: str, value: float | str) -> object:
    t = backend.COLOR_FIELDS.get(key, "float")
    if t == "int":
        return int(round(float(value)))
    if t == "float":
        return float(value)
    return str(value)


class _ScaleRow(Adw.PreferencesRow):
    """Строка со слайдером и подписью текущего значения."""

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
        # Применение гасится в HdrWindow._set_field флагом self._loading.
        self.scale.set_value(float(value))


class HdrWindow(Adw.Window):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app)
        self.set_title("Управление HDR")
        self.set_default_size(460, 620)

        self._loading = True
        self._timeout_id: int | None = None
        self.config_path: str | None = None
        self.config_file: configfile.MonitorConfigFile | None = None
        self.runtime: list[backend.Monitor] = []
        self.specs: list[dict] = []
        self.spec: dict = {}
        self.current_name: str = ""
        self.reference: dict = dict(reference.DEFAULT_REFERENCE)

        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.reset_btn = Gtk.Button(label="Сбросить")
        self.reset_btn.connect("clicked", self._on_reset)
        header.pack_start(self.reset_btn)
        self.save_btn = Gtk.Button(label="Сохранить в конфиг")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save)
        header.pack_end(self.save_btn)
        toolbar.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        toolbar.set_content(scroll)

        page = Adw.PreferencesPage()
        scroll.set_child(page)

        # --- Группа «Монитор» ---
        mon_group = Adw.PreferencesGroup(title="Монитор")
        page.add(mon_group)

        self.mon_combo = Adw.ComboRow(title="Монитор")
        self.mon_combo.connect("notify::selected", self._on_monitor_selected)
        mon_group.add(self.mon_combo)

        self.status_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.status_label.set_margin_top(4)
        self.status_label.set_margin_bottom(4)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("dim-label")
        mon_group.add(self.status_label)

        # --- Группа «HDR» ---
        self.hdr_group = Adw.PreferencesGroup(title="HDR")
        page.add(self.hdr_group)

        self.hdr_switch = Adw.SwitchRow(title="HDR")
        self.hdr_switch.set_subtitle("Широкий цветовой охват + PQ (10 бит)")
        self.hdr_switch.connect("notify::active", self._on_hdr_toggled)
        self.hdr_group.add(self.hdr_switch)

        self.scale_rows: dict[str, _ScaleRow] = {}
        for key, title, sub, lo, hi, step, digits, unit, _t in _SLIDERS:
            row = _ScaleRow(key, title, sub, lo, hi, step, digits, unit)
            row.connect_changed(self._on_slider)
            self.scale_rows[key] = row
            self.hdr_group.add(row)

        # --- Дополнительно ---
        adv_group = Adw.PreferencesGroup(title="Дополнительно")
        page.add(adv_group)
        exp = Adw.ExpanderRow(title="Параметры цвета и разрядность")
        adv_group.add(exp)

        self.eotf_combo = Adw.ComboRow(title="SDR EOTF (гамма)")
        self.eotf_combo.set_model(Gtk.StringList.new(_EOTFS))
        self.eotf_combo.connect("notify::selected", self._on_eotf_changed)
        exp.add_row(self.eotf_combo)

        self.bitdepth_combo = Adw.ComboRow(title="Глубина цвета")
        self.bitdepth_combo.set_model(Gtk.StringList.new(_BITDEPTHS))
        self.bitdepth_combo.connect("notify::selected", self._on_bitdepth_changed)
        exp.add_row(self.bitdepth_combo)

        # --- Референс монитора ---
        ref_group = Adw.PreferencesGroup(title="Референс монитора")
        page.add(ref_group)

        self.ref_expander = Adw.ExpanderRow(title="Справочные значения панели")
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

        apply_row = Adw.ActionRow(title="Сбросить яркостные лимиты к референсу")
        self.ref_apply_btn = Gtk.Button(label="Применить")
        self.ref_apply_btn.add_css_class("suggested-action")
        self.ref_apply_btn.connect("clicked", self._on_apply_reference)
        apply_row.add_suffix(self.ref_apply_btn)
        apply_row.set_activatable_widget(self.ref_apply_btn)
        self.ref_expander.add_row(apply_row)

        self.toast = Adw.ToastOverlay(child=toolbar)
        self.set_content(self.toast)
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

        # Актуальные runtime-значения имеют приоритет.
        spec["output"] = monitor.name
        spec["cm"] = monitor.cm
        spec["sdrbrightness"] = monitor.sdr_brightness
        spec["sdrsaturation"] = monitor.sdr_saturation
        spec["sdr_min_luminance"] = monitor.sdr_min_luminance
        spec["sdr_max_luminance"] = monitor.sdr_max_luminance
        spec.setdefault("mode", monitor.mode)
        spec.setdefault("position", monitor.position)
        spec.setdefault("scale", monitor.scale)

        # Аппаратные поля, которых нет в runtime, берём из референса панели.
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
                self._toast(f"Не удалось прочитать конфиг: {exc}", error=True)
        self.save_btn.set_sensitive(self.config_path is not None)

        names = [m.name for m in self.runtime]
        self.mon_combo.set_model(Gtk.StringList.new(names))
        if names:
            self.mon_combo.set_selected(0)
            self._show_monitor(0)

    def _show_monitor(self, index: int) -> None:
        if index < 0 or index >= len(self.runtime):
            return
        self._loading = True
        mon = self.runtime[index]
        self.current_name = mon.name
        self.reference = reference.lookup(mon.make, mon.model, mon.description)
        self.spec = self._build_spec(mon, self._cfg_for(mon.name))

        self._update_reference(mon)

        self.hdr_switch.set_active(mon.hdr_on)
        for key, row in self.scale_rows.items():
            row.set_value_silent(float(self.spec.get(key, 0)))

        eotf = str(self.spec.get("sdr_eotf", "default"))
        if eotf in _EOTFS:
            self.eotf_combo.set_selected(_EOTFS.index(eotf))
        bd = str(self.spec.get("bitdepth", 10))
        if bd in _BITDEPTHS:
            self.bitdepth_combo.set_selected(_BITDEPTHS.index(bd))

        self._update_status()
        self._loading = False

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
            lines.append(
                f"Пик HDR: {ref['peak_luminance']} нит · "
                f"полноэкранный белый: {ref['fullscreen_white']} нит · "
                f"чёрный: {ref['min_luminance']} нит"
            )
            self.ref_info_label.set_text("\n".join(lines))
            self.ref_apply_btn.set_sensitive(True)
        else:
            self.ref_info_label.set_text(
                f"Справочных данных для «{mon.description or mon.name}» нет.\n"
                "Будут использованы общие дефолты."
            )
            self.ref_apply_btn.set_sensitive(False)

    def _update_status(self) -> None:
        mon = next((m for m in self.runtime if m.name == self.current_name), None)
        if mon is None:
            self.status_label.set_text("")
            return
        fmt = mon.current_format or ""
        bits = "10 бит" if "2101010" in fmt or "10" in fmt else "8 бит"
        parts = [mon.name]
        if mon.hdr_on:
            parts.append("HDR (PQ)")
        else:
            parts.append("SDR")
        parts.append(bits)
        if mon.description:
            parts.append(mon.description)
        self.status_label.set_text(" · ".join(parts))

    # ------------------------------------------------------------ apply logic
    def _set_field(self, key: str, value: float | str) -> None:
        self.spec[key] = _coerce(key, value)
        if self._loading:
            return
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
        self._timeout_id = GLib.timeout_add(120, self._flush)

    def _flush(self) -> bool:
        self._timeout_id = None
        try:
            backend.apply_spec(self.spec)
            self._toast("Применено")
        except backend.HyprctlError as exc:
            self._toast(str(exc), error=True)
        return GLib.SOURCE_REMOVE

    def _toast(self, text: str, error: bool = False) -> None:
        toast = Adw.Toast(title=text)
        if error:
            toast.set_timeout(4)
        self.toast.add_toast(toast)

    # -------------------------------------------------------------- handlers
    def _on_monitor_selected(self, combo, _pspec):
        if not self._loading:
            self._show_monitor(combo.get_selected())

    def _on_hdr_toggled(self, switch, _pspec):
        if self._loading:
            return
        active = switch.get_active()
        self._set_field("cm", "hdr" if active else "srgb")
        if active:
            self._set_field("supports_hdr", 1)
            self._set_field("supports_wide_color", 1)

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

    def _on_reset(self, _btn):
        self._load_state()
        self._toast("Перечитано из Hyprland")

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
            self._toast("Нет справочных данных для этой панели", error=True)
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
        self._flush()
        self._toast("Применены референсные значения")

    def _on_save(self, _btn):
        if self.config_file is None:
            self._toast("Файл конфига не найден", error=True)
            return
        updates = {
            k: self.spec[k]
            for k in backend.COLOR_FIELDS
            if k in self.spec
        }
        try:
            bak = self.config_file.save(self.current_name, updates)
            self._toast(f"Сохранено (бэкап: {bak})")
        except (OSError, KeyError) as exc:
            self._toast(f"Ошибка сохранения: {exc}", error=True)


class HdrApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = HdrWindow(self)
        win.present()
        win._load_state()


def main() -> int:
    app = HdrApp()
    return app.run(None)
