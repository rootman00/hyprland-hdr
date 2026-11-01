"""Unit tests for the pure (no Hyprland) parts of hyprhdr.

Run from the project root:  python3 -m unittest discover
"""

import datetime
import os
import tempfile
import unittest

from hyprhdr import backend, configfile, i18n, settings, sun


class TestLuaLiteral(unittest.TestCase):
    def test_bool(self):
        self.assertEqual(backend.lua_literal(True), "true")
        self.assertEqual(backend.lua_literal(False), "false")

    def test_string_escaping(self):
        self.assertEqual(backend.lua_literal('a"b\\c'), '"a\\"b\\\\c"')

    def test_numbers(self):
        self.assertEqual(backend.lua_literal(10), "10")
        self.assertEqual(backend.lua_literal(1.5), "1.5")

    def test_build_spec_skips_none(self):
        spec = backend.build_spec({"cm": "hdr", "bitdepth": None, "x": 1.5})
        self.assertIn('cm = "hdr"', spec)
        self.assertIn("x = 1.5", spec)
        self.assertNotIn("bitdepth", spec)


class TestParseBody(unittest.TestCase):
    def test_strips_comment_outside_string(self):
        spec = configfile._parse_body('    cm = "hdr",   -- force HDR\n    x = 1')
        self.assertEqual(spec["cm"], "hdr")
        self.assertEqual(spec["x"], 1)

    def test_keeps_dashes_inside_string(self):
        # "--" inside a quoted value must not be treated as a comment.
        spec = configfile._parse_body('    mode = "a--b",\n    cm = "srgb" -- c')
        self.assertEqual(spec["mode"], "a--b")
        self.assertEqual(spec["cm"], "srgb")

    def test_unescape(self):
        self.assertEqual(configfile._parse_value('"a\\"b"'), 'a"b')
        self.assertEqual(configfile._parse_value('"a\\\\b"'), "a\\b")


class TestParseMonitorSpecs(unittest.TestCase):
    SAMPLE = """hl.monitor({
    output = "DP-3",
    mode = "2560x1440@240",
    position = "auto",
    scale = 1,
    bitdepth = 10,             -- 10-bit
    cm = "hdr",                -- force HDR
    sdrbrightness = 1.199237,
    max_avg_luminance = 250
})
"""

    def test_parse(self):
        specs = configfile.parse_monitor_specs(self.SAMPLE)
        self.assertEqual(len(specs), 1)
        s = specs[0]
        self.assertEqual(s["output"], "DP-3")
        self.assertEqual(s["mode"], "2560x1440@240")
        self.assertEqual(s["bitdepth"], 10)
        self.assertEqual(s["cm"], "hdr")
        self.assertAlmostEqual(s["sdrbrightness"], 1.199237)
        self.assertEqual(s["max_avg_luminance"], 250)


class TestApplyUpdates(unittest.TestCase):
    def test_updates_value_preserves_comment(self):
        body = '    output = "DP-3",\n    cm = "hdr",   -- comment'
        out = configfile._apply_updates(body, {"cm": "srgb"})
        self.assertIn('cm = "srgb",   -- comment', out)

    def test_appends_missing_key_adds_comma(self):
        # The last field has no trailing comma; the appended field must be
        # separated with a comma to stay valid Lua.
        body = '    output = "DP-3",\n    cm = "srgb"'
        out = configfile._apply_updates(body, {"bitdepth": 10})
        self.assertIn('cm = "srgb",', out)
        self.assertIn("bitdepth = 10,", out)

    def test_preserves_trailing_newline(self):
        body = '    output = "DP-3",\n    cm = "hdr",\n'
        out = configfile._apply_updates(body, {"cm": "srgb"})
        self.assertTrue(out.endswith("\n"))


class TestSave(unittest.TestCase):
    def _write(self, text: str) -> str:
        d = tempfile.mkdtemp()
        path = os.path.join(d, "monitors.lua")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_creates_block_when_output_missing(self):
        path = self._write("hl.monitor({\n    output = \"DP-3\",\n    cm = \"hdr\"\n})\n")
        cf = configfile.MonitorConfigFile(path)
        cf.load()
        cf.save(
            "DP-6",
            {"cm": "hdr", "bitdepth": 10, "max_luminance": 1000},
            geometry={"mode": "2560x1440@240", "position": "auto", "scale": 1.0},
        )
        specs = configfile.parse_monitor_specs(cf.text or "")
        outputs = [s["output"] for s in specs]
        self.assertIn("DP-3", outputs)
        self.assertIn("DP-6", outputs)
        new = next(s for s in specs if s["output"] == "DP-6")
        self.assertEqual(new["cm"], "hdr")
        self.assertEqual(new["bitdepth"], 10)
        self.assertEqual(new["mode"], "2560x1440@240")

    def test_raises_when_missing_and_no_geometry(self):
        path = self._write("hl.monitor({\n    output = \"DP-3\",\n    cm = \"hdr\"\n})\n")
        cf = configfile.MonitorConfigFile(path)
        cf.load()
        with self.assertRaises(KeyError):
            cf.save("DP-6", {"cm": "hdr"})


class TestRender(unittest.TestCase):
    CONFIG = """hl.monitor({
    output = "DP-6",
    cm = "hdr",
})
hl.config({
    render = {
        cm_enabled = 1,      -- master
        cm_auto_hdr = 0      -- auto
    }
})
"""

    def test_parse_render_spec(self):
        spec = configfile.parse_render_spec(self.CONFIG)
        self.assertEqual(spec["cm_enabled"], 1)
        self.assertEqual(spec["cm_auto_hdr"], 0)

    def test_update_render_preserves_comments(self):
        out = configfile._update_render(self.CONFIG, {"cm_auto_hdr": 1})
        self.assertIn("cm_auto_hdr = 1      -- auto", out)
        self.assertIn("cm_enabled = 1,      -- master", out)

    def test_save_updates_render_and_monitor(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "monitors.lua")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.CONFIG)
        cf = configfile.MonitorConfigFile(path)
        cf.load()
        cf.save(
            "DP-6",
            {"cm": "auto"},
            render_updates={"cm_auto_hdr": 1, "cm_enabled": 1},
        )
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        specs = configfile.parse_monitor_specs(text)
        self.assertEqual(specs[0]["cm"], "auto")
        render = configfile.parse_render_spec(text)
        self.assertEqual(render["cm_auto_hdr"], 1)
        self.assertEqual(render["cm_enabled"], 1)

    def test_append_render_block_when_missing(self):
        out = configfile._update_render(
            'hl.monitor({\n    output = "DP-6",\n    cm = "hdr"\n})\n',
            {"cm_auto_hdr": 1, "cm_enabled": 1},
        )
        self.assertIn("hl.config({", out)
        render = configfile.parse_render_spec(out)
        self.assertEqual(render["cm_auto_hdr"], 1)


class TestNightSchedule(unittest.TestCase):
    def _at(self, hour: int, minute: int = 0) -> datetime.datetime:
        return datetime.datetime(2026, 1, 1, hour, minute)

    def test_disabled(self):
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=False)
        self.assertFalse(settings.is_night(s, self._at(23)))

    def test_within_window(self):
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=True, night_start_hour=22, night_end_hour=7)
        self.assertTrue(settings.is_night(s, self._at(23)))
        self.assertTrue(settings.is_night(s, self._at(3)))
        self.assertFalse(settings.is_night(s, self._at(12)))

    def test_no_wrap(self):
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=True, night_start_hour=9, night_end_hour=17)
        self.assertTrue(settings.is_night(s, self._at(12)))
        self.assertFalse(settings.is_night(s, self._at(20)))

    def test_load_save_roundtrip(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "settings.json")
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=True, night_brightness=0.8)
        settings.save_settings(s, path)
        loaded = settings.load_settings(path)
        self.assertTrue(loaded["night_enabled"])
        self.assertEqual(loaded["night_brightness"], 0.8)
        self.assertEqual(loaded["night_end_hour"], settings.DEFAULT_SETTINGS["night_end_hour"])

    def test_language_default_fills_missing(self):
        self.assertEqual(settings.DEFAULT_SETTINGS["language"], "en")
        d = tempfile.mkdtemp()
        path = os.path.join(d, "settings.json")
        settings.save_settings({"night_enabled": True}, path)
        loaded = settings.load_settings(path)
        self.assertEqual(loaded["language"], "en")

    def test_sun_mode_window(self):
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=True,
                 schedule_mode="sun", sunset_hour=18.5, sunrise_hour=7.0)
        self.assertTrue(settings.is_night(s, self._at(19)))
        self.assertTrue(settings.is_night(s, self._at(23)))
        self.assertTrue(settings.is_night(s, self._at(6, 30)))
        self.assertFalse(settings.is_night(s, self._at(12)))

    def test_sun_mode_falls_back_when_no_data(self):
        s = dict(settings.DEFAULT_SETTINGS, night_enabled=True,
                 schedule_mode="sun", sunset_hour=None, sunrise_hour=None,
                 night_start_hour=22, night_end_hour=7)
        self.assertTrue(settings.is_night(s, self._at(23)))


class TestSun(unittest.TestCase):
    def test_hour_float_utc_to_local(self):
        from zoneinfo import ZoneInfo
        self.assertAlmostEqual(
            sun.hour_float("2026-01-01T15:00:00+00:00", ZoneInfo("Europe/Moscow")), 18.0
        )
        self.assertAlmostEqual(
            sun.hour_float("2026-01-01T00:30:00Z", ZoneInfo("UTC")), 0.5
        )

    def test_fmt_hour(self):
        from hyprhdr import gui
        self.assertEqual(gui._fmt_hour(18.7), "18:42")
        self.assertEqual(gui._fmt_hour(7.0), "07:00")
        self.assertEqual(gui._fmt_hour(23.999), "00:00")


class TestI18n(unittest.TestCase):
    def test_default_is_english(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Quit"), "Quit")

    def test_russian_translation(self):
        try:
            i18n.set_language("ru")
            self.assertEqual(i18n.tr("Quit"), "Выход")
            self.assertEqual(i18n.tr("Save to config"), "Сохранить в конфиг")
        finally:
            i18n.set_language("en")

    def test_unknown_key_falls_back_to_english(self):
        try:
            i18n.set_language("ru")
            self.assertEqual(i18n.tr("Some Untranslated String 123"), "Some Untranslated String 123")
        finally:
            i18n.set_language("en")

    def test_unknown_language_falls_back(self):
        i18n.set_language("xx")
        self.assertEqual(i18n.get_language(), "en")


class TestTrayIcon(unittest.TestCase):
    def test_icon_pixmap_sizes_and_bytes(self):
        from hyprhdr import tray
        pix = tray.icon_pixmaps()
        self.assertEqual([p[0] for p in pix], [16, 22, 24, 32, 48, 64, 128])
        for w, h, data in pix:
            self.assertEqual(w, h)
            self.assertEqual(len(data), w * h * 4)
            # The centre (sun disc) must be opaque: alpha byte > 0.
            center = (h // 2) * w * 4 + (w // 2) * 4
            self.assertGreater(data[center], 0)


if __name__ == "__main__":
    unittest.main()
