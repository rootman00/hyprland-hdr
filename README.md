# hdr-manager

Небольшая программа для визуального управления HDR в Wayland (Hyprland 0.56+ с
**Lua-конфигом**, например CachyOS). Позволяет на лету включать/выключать HDR и
крутить параметры SDR-тонмаппинга, как в [gloam](https://github.com/halideworks/gloam),
но для Hyprland.

## Что умеет (v1)

- Переключатель **HDR** (`cm = "hdr"` ↔ `cm = "srgb"`)
- **SDR-яркость** (`sdrbrightness`) — главная «крутилка» против вымытого SDR в HDR
- **SDR-насыщенность** (`sdrsaturation`)
- **SDR max luminance** (`sdr_max_luminance`, в нитах)
- **Пиковая яркость** HDR-панели (`max_luminance`, в нитах)
- **Средняя яркость / ABL** (`max_avg_luminance`)
- **SDR EOTF** (гамма) и **глубина цвета** (8/10 бит)
- **Референс монитора** — справочные (измеренные) значения панели и кнопка
  «Применить референс», сбрасывающая яркостные лимиты к заводским
- Применение на лету (слайдер → сразу к монитору) и **сохранение в конфиг**

## Требования

- Hyprland 0.56+ с Lua-конфигом (проверено на 0.57.0)
- `hyprctl` в `$PATH`
- Python 3.10+, PyGObject + GTK4 + libadwaita

Arch Linux:

```bash
sudo pacman -S python python-gobject gtk4 libadwaita
```

## Запуск

```bash
cd hdr-manager
python3 main.py
```

Или сделать исполняемым:

```bash
chmod +x main.py && ./main.py
```

## Как это работает

В Hyprland 0.56+ конфиг-провайдер — Lua, поэтому старый `hyprctl keyword monitor`
**не работает**. Программа использует:

- **чтение:** `hyprctl monitors -j`
- **применение:** `hyprctl repl 'hl.monitor({ ... })'` (вызов Lua-API на лету)
- **сохранение:** правка `~/.config/hypr/config/monitors.lua` на месте, с бэкапом
  в `monitors.lua.bak` перед каждой записью

## Структура

```
hdr-manager/
├── main.py               # точка входа
├── hyprhdr/
│   ├── backend.py        # hyprctl: чтение/запись, Lua-литералы
│   ├── configfile.py     # парсинг и правка monitors.lua
│   ├── reference.py      # база справочных значений известных мониторов
│   └── gui.py            # интерфейс GTK4/libadwaita
└── README.md
```

## Справочные значения

В [`hyprhdr/reference.py`](hyprhdr/reference.py) лежат измеренные характеристики
известных панелей. Для **Lenovo Legion Pro 27Q-10 (QD-OLED)** это:

| Параметр | Значение | Откуда |
|---|---|---|
| Пик HDR | **1000 нит** (3% окно, до 1044 на 1%) | lab501 / smzdm |
| Полноэкранный белый | **258–269 нит** | lab501 / smzdm |
| Чёрный | **0 нит** (OLED) | — |
| Охват | 99% DCI-P3 · 82.6% BT.2020 · 140% sRGB | lab501 / smzdm |
| Сертификация | DisplayHDR True Black 400 | lab501 |

Из них программа берёт дефолты для `max_luminance`, `min_luminance`,
`max_avg_luminance`, `sdr_max_luminance` и флагов охвата. Кнопка
**«Применить референс»** сбрасывает яркостные лимиты к этим значениям.
Добавить свой монитор — дописать запись в `MONITORS`.

## Ограничения и TODO

- Пока ориентировано на `hl.monitor({ ... })`-блоки (Lua-конфиг). Классический
  однострочный `monitor = ...` в `.conf` не поддерживается.
- Правка конфига — только поля внутри уже существующего блока `hl.monitor` для
  выбранного `output`.
- **Дальше (как в gloam):** автоматический подгон — ночной режим по времени суток
  (снижение яркости/насыщенности вечером) и/или авто-HDR по контенту
  (`render.cm_auto_hdr`). Точка расширения — `hyprhdr/gui.py::HdrWindow._set_field`,
  весь доступ к параметрам уже изолирован в `backend.apply_spec`.
