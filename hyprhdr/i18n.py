"""User-interface translations.

Minimal, dependency-free i18n: source strings are English and a dict maps them
to Russian. English is the default; the user can switch to Russian in the GUI
(persisted in ``settings.json`` under ``language``).
"""

from __future__ import annotations

LANGUAGE_ORDER: tuple[str, ...] = ("en", "ru")
LANGUAGE_LABELS: dict[str, str] = {"en": "English", "ru": "Русский"}

_current: str = "en"

_TRANSLATIONS: dict[str, str] = {
    # --- general / header ---
    "HDR Manager": "Менеджер HDR",
    "Quit": "Выход",
    "Reset": "Сброс",
    "Save to config": "Сохранить в конфиг",
    # --- groups ---
    "Language": "Язык",
    "Monitor": "Монитор",
    "HDR": "HDR",
    "Advanced": "Дополнительно",
    "Monitor reference": "Справка по монитору",
    "Night mode (schedule)": "Ночной режим (расписание)",
    # --- color mode ---
    "Color mode": "Цветовой режим",
    "SDR": "SDR",
    "sRGB, always SDR": "sRGB, всегда SDR",
    "HDR": "HDR",
    "Wide gamut + PQ, always HDR": "Широкий охват + PQ, всегда HDR",
    "Auto HDR": "Авто HDR",
    "SDR by default, switch to HDR for HDR content":
        "SDR по умолчанию, авто-переключение в HDR для HDR-контента",
    "Auto HDR target": "Цель авто-HDR",
    "hdr (wide gamut + PQ)": "hdr (широкий охват + PQ)",
    "hdredid (EDID + PQ)": "hdredid (EDID + PQ)",
    # --- sliders ---
    "SDR brightness": "Яркость SDR",
    "Brightness of SDR content inside the HDR container":
        "Яркость SDR-контента внутри HDR-контейнера",
    "SDR saturation": "Насыщенность SDR",
    "Compensates washed-out SDR in HDR": "Компенсирует выцветание SDR в HDR",
    "SDR min luminance": "Мин. яркость SDR",
    "Black level for the SDR→HDR tone map (nits)":
        "Уровень чёрного для тонального отображения SDR→HDR (ниты)",
    "SDR max luminance": "Макс. яркость SDR",
    "White peak for SDR windows (nits)": "Пик белого для SDR-окон (ниты)",
    "Peak brightness (HDR)": "Пиковая яркость (HDR)",
    "Hardware peak of the panel in nits": "Аппаратный пик панели в нитах",
    "Average brightness (ABL)": "Средняя яркость (ABL)",
    "Average brightness limit (ABL protection)":
        "Лимит средней яркости (защита ABL)",
    " nits": " нит",
    # --- advanced ---
    "Color and bit-depth settings": "Настройки цвета и битовой глубины",
    "SDR EOTF (gamma)": "SDR EOTF (гамма)",
    "Color depth": "Глубина цвета",
    # --- reference ---
    "Panel reference values": "Эталонные значения панели",
    "Reset luminance limits to reference": "Сбросить лимиты яркости к эталонным",
    "Apply": "Применить",
    "HDR peak": "Пик HDR",
    "full-screen white": "белый на весь экран",
    "black": "чёрный",
    "nits": "нит",
    "No reference data for \"{name}\".\nGeneric defaults will be used.":
        "Нет эталонных данных для «{name}».\nБудут использованы общие значения по умолчанию.",
    # --- status line ---
    "HDR (PQ)": "HDR (PQ)",
    "SDR": "SDR",
    "auto-HDR": "авто-HDR",
    "10-bit": "10-бит",
    "8-bit": "8-бит",
    "no config block — one will be created on save":
        "нет блока конфига — будет создан при сохранении",
    # --- night mode ---
    "Enable schedule": "Включить расписание",
    "Lower SDR brightness/saturation at night (HDR mode)":
        "Понижает яркость/насыщенность SDR ночью (режим HDR)",
    "Night brightness": "Ночная яркость",
    "SDR brightness while the schedule is active":
        "Яркость SDR, пока расписание активно",
    "Night saturation": "Ночная насыщенность",
    "SDR saturation while the schedule is active":
        "Насыщенность SDR, пока расписание активно",
    "Night starts (hour)": "Начало ночи (час)",
    "Night ends (hour)": "Конец ночи (час)",
    "Schedule source": "Источник расписания",
    "Manual": "Вручную",
    "Sun (internet)": "По солнцу (интернет)",
    "Update now": "Обновить сейчас",
    "Sun data": "Данные о солнце",
    "Sunset": "Закат",
    "Sunrise": "Восход",
    "updated": "обновлено",
    "Fetching sun times…": "Получаю время восхода/заката…",
    "No sun data yet.": "Данных о солнце пока нет.",
    "Could not fetch sun times: {msg}":
        "Не удалось получить время восхода/заката: {msg}",
    "Color management is disabled (render.cm_enabled = 0). "
    "The sliders have no effect until it is enabled (requires a Hyprland restart).":
        "Цветоуправление выключено (render.cm_enabled = 0). "
        "Слайдеры не действуют, пока оно не включено (требуется перезапуск Hyprland).",
    "Schedule disabled": "Расписание выключено",
    "Active — using night values": "Активно — ночные значения",
    "Inactive — using day values": "Неактивно — дневные значения",
    # --- toasts ---
    "Applied": "Применено",
    "Reloaded from Hyprland": "Перезагружено из Hyprland",
    "Config file not found": "Файл конфига не найден",
    "No reference data for this panel": "Нет эталонных данных для этой панели",
    "Reference values applied": "Эталонные значения применены",
    "Failed to read config: {exc}": "Не удалось прочитать конфиг: {exc}",
    "Could not save settings: {exc}": "Не удалось сохранить настройки: {exc}",
    "Saved (backup: {bak})": "Сохранено (резервная копия: {bak})",
    "Save failed: {exc}": "Ошибка сохранения: {exc}",
}


def set_language(code: str) -> None:
    """Set the active UI language (unknown codes fall back to English)."""
    global _current
    _current = code if code in LANGUAGE_ORDER else "en"


def get_language() -> str:
    """The active UI language code (``en`` or ``ru``)."""
    return _current


def tr(text: str) -> str:
    """Translate a source (English) string into the active language."""
    if _current == "ru":
        return _TRANSLATIONS.get(text, text)
    return text
