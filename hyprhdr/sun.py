"""Sunrise/sunset for the sun-based night schedule.

Only **one** network call is needed: ``fetch_coordinates`` looks up the public
IP to get latitude/longitude and the IANA timezone. The sunrise/sunset times
themselves are then computed **locally** with the NOAA solar-position algorithm
(``fetch_sun_times``) — no third-party sun API, so the schedule keeps working
offline once the coordinates are cached.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT = 6.0
_USER_AGENT = "hdr-manager/0.1"

# Official sunrise/sunset zenith: 90° + refraction + solar radius.
_ZENITH_DEG = 90.833


def system_timezone() -> str | None:
    """Best-effort IANA timezone name of this machine (Arch/Debian layout)."""
    try:
        # Arch/CachyOS: /etc/localtime is a symlink into /usr/share/zoneinfo/...
        lt = "/etc/localtime"
        if os.path.islink(lt):
            target = os.readlink(lt)
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        # Debian/Ubuntu: /etc/timezone holds the plain name.
        p = "/etc/timezone"
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                name = fh.read().strip()
            if name:
                return name
    except OSError:
        pass
    return None


def local_tz(tz_name: str | None) -> _dt.tzinfo:
    """A tzinfo for ``tz_name``, falling back to the system's local zone."""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001 - invalid/unavailable name
            pass
    return _dt.datetime.now().astimezone().tzinfo


def hour_float(iso: str, tz: _dt.tzinfo | None = None) -> float:
    """Convert an ISO-8601 timestamp to a local wall-clock hour (e.g. 18.7).

    Naive timestamps are treated as UTC. Pure, no network — unit-testable.
    """
    dt = _dt.datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    local = dt.astimezone(tz or _dt.datetime.now().astimezone().tzinfo)
    return _hour_of(local)


def _hour_of(dt: _dt.datetime) -> float:
    """Local wall-clock hour of ``dt`` as a float (e.g. 7.55)."""
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _open(url: str, timeout: float) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only
        return json.load(resp)


def fetch_coordinates(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    """Approximate location from the public IP (lat/lng + IANA timezone)."""
    providers = (
        ("https://ipwho.is/", lambda d: (
            d.get("latitude"), d.get("longitude"),
            (d.get("timezone") or {}).get("id") if isinstance(d.get("timezone"), dict) else None,
        )),
        # The free tier of ip-api.com is HTTP-only (HTTPS needs a paid key).
        ("http://ip-api.com/json/", lambda d: (
            d.get("lat"), d.get("lon"), d.get("timezone"),
        )),
    )
    for url, extract in providers:
        try:
            data = _open(url, timeout)
        except Exception:  # noqa: BLE001 - try the next provider
            continue
        try:
            lat, lng, tz = extract(data)
        except Exception:  # noqa: BLE001 - malformed payload
            continue
        if lat is None or lng is None:
            continue
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            continue
        return {
            "latitude": lat,
            "longitude": lng,
            "timezone": tz or system_timezone(),
        }
    return None


def _sun_minutes_utc(lat: float, lng: float, date: _dt.date) -> tuple[float | None, float | None]:
    """(sunrise, sunset) as minutes from UTC midnight, or (None, None).

    Standard NOAA/NOAA-spreadsheet formulation; accurate to ~1–2 minutes, which
    is plenty for a night schedule. ``(None, None)`` means polar day/night.
    """
    n = date.timetuple().tm_yday
    g = 2.0 * math.pi / 365.0 * (n - 1)

    # Equation of time (minutes).
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    # Solar declination (radians).
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    lat_rad = math.radians(lat)
    cos_ha = (
        math.cos(math.radians(_ZENITH_DEG))
        / (math.cos(lat_rad) * math.cos(decl))
        - math.tan(lat_rad) * math.tan(decl)
    )
    if cos_ha > 1.0 or cos_ha < -1.0:
        return None, None

    ha_deg = math.degrees(math.acos(cos_ha))
    sunrise = 720.0 - 4.0 * (lng + ha_deg) - eqtime
    sunset = 720.0 - 4.0 * (lng - ha_deg) - eqtime
    return sunrise, sunset


def fetch_sun_times(lat: float, lng: float, tz_name: str | None = None,
                    date: _dt.date | None = None) -> dict[str, float]:
    """Sunrise/sunset as local wall-clock hour floats for ``date`` (today).

    Computed locally (no network). Returns ``{"sunrise": float, "sunset": float}``
    (e.g. 7.55 and 16.87). Raises ``ValueError`` on polar day/night.
    """
    date = date or _dt.date.today()
    sunrise_min, sunset_min = _sun_minutes_utc(lat, lng, date)
    if sunrise_min is None or sunset_min is None:
        raise ValueError("no sunrise/sunset on this date (polar day/night)")

    tz = local_tz(tz_name)
    midnight_utc = _dt.datetime(date.year, date.month, date.day, tzinfo=_dt.timezone.utc)
    sunrise = (midnight_utc + _dt.timedelta(minutes=sunrise_min)).astimezone(tz)
    sunset = (midnight_utc + _dt.timedelta(minutes=sunset_min)).astimezone(tz)
    return {"sunrise": _hour_of(sunrise), "sunset": _hour_of(sunset)}
