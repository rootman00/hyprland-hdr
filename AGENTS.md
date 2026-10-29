# AGENTS.md

Инструкция для агентов (и людей), работающих с этим репозиторием. Прочитай
перед правками.

## Что это

Графический менеджер HDR для **Hyprland 0.56+ с Lua-конфигом** (например
CachyOS). GTK4 + libadwaita на Python (PyGObject). Позволяет на лету
включать/выключать HDR, крутить SDR-тонмаппинг и сохранять настройки в конфиг.

## Критические факты — не ломать

1. **`hyprctl keyword monitor ...` НЕ работает** в Hyprland 0.56+ с Lua-конфигом
   (конфиг-провайдер `lua`). Запись на лету — только через
   `hyprctl repl 'hl.monitor({ ... })'`. Реализовано в
   `hyprhdr/backend.py::apply_spec`.
2. **Чтение** — `hyprctl monitors -j` (поля runtime в **camelCase**:
   `sdrBrightness`, `sdrSaturation`, `sdrMinLuminance`, `sdrMaxLuminance`,
   `colorManagementPreset`).
3. **Поля Lua-конфига** в `hl.monitor({ ... })` — в **snake_case**, но с
   неочевидными исключениями: `sdrbrightness` и `sdrsaturation` **без
   подчёркивания**, а `sdr_min_luminance` / `sdr_max_luminance` — **с
   подчёркиванием**. Полный список — `backend.COLOR_FIELDS`. Не путать с
   runtime camelCase из п.2.
4. **Значения `cm`**: `"hdr"` (HDR вкл) ↔ `"srgb"` (SDR); также бывают `"none"`,
   `"edid"`.
5. **Сохранение конфига** — `hyprhdr/configfile.py`, правка блока
   `hl.monitor({ ... })` на месте с бэкапом в `*.bak` перед каждой записью.
   Парсер намеренно консервативный (построчные регэкспы + сканер скобок,
   пропускающий `--`-комментарии и строки в кавычках). Не заменяй его на
   «полный» Lua-парсер без тестов — рискуешь повредить пользовательский конфиг.

## Модули

- `hyprhdr/backend.py` — hyprctl: чтение/запись, Lua-литералы, dataclass `Monitor`.
- `hyprhdr/configfile.py` — поиск/парсинг/правка `monitors.lua`.
- `hyprhdr/reference.py` — база измеренных значений мониторов (ключ — подстрока,
  напр. `"27q-10"`). Фолбэк — `DEFAULT_REFERENCE`.
- `hyprhdr/gui.py` — интерфейс; `HdrWindow` — состояние и логика применения.
- `main.py` — точка входа.

## Конвенции

- UI-строки и комментарии — на русском; идентификаторы/ключи — на английском.
- Новое поле HDR добавлять через `backend.COLOR_FIELDS` (+ слайдер в
  `gui._SLIDERS`, если нужен). Типы: `str`/`int`/`float` — определяют
  Lua-сериализацию и округление.
- Применение на лету — через `HdrWindow._set_field` (дебаунс 120 мс →
  `_flush` → `backend.apply_spec`). При программной установке виджетов ставить
  `self._loading = True`, чтобы не триггерить повторное применение.
- Геометрия (`mode`, `position`, `scale`) всегда должна присутствовать в spec
  при `hl.monitor`, иначе Hyprland сбросит её в дефолт — см. `_build_spec`.

## Как запускать / проверять

```bash
python3 main.py
python3 -m py_compile hyprhdr/*.py main.py   # быстрая проверка синтаксиса
hyprctl monitors -j                          # текущее состояние
hyprctl repl 'hl.monitor({ output = "DP-3", cm = "srgb" })'  # ручное применение
```

GUI тестируется только в живой Wayland/Hyprland-сессии; в CI/песочнице без GPU
появляются безвредные предупреждения Vulkan/MESA/dconf — это норма.

## Расширения (TODO)

- Автоподгон как в gloam (ночной режим по времени суток и/или авто-HDR по
  контенту через `render.cm_auto_hdr`). Точки расширения уже изолированы:
  `backend.apply_spec` (применение) и `HdrWindow._set_field` (источник изменений).
