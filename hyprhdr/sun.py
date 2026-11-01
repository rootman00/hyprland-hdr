"""Sunrise/sunset lookups for the sun-based night schedule.

Two network calls are involved, both kept graceful (small timeout, ``None`` on
failure so the caller can fall back to manual hours or the previous cache):

1. IP geolocation → latitude/longitude/timezone (``fetch_coordinates``).
2. sunrise-sunset.org → sunrise/sunset UTC times (``fetch_sun_times``), which
   are converted to local wall-clock hours in the configured IANA timezone.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT = 6.0
_USER_AGENT = "hdr-manager/0.1 (+https://github.com/halideworks)"


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
    return local.hour + local.minute / 60.0 + local.second / 3600.0


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
        ("https://ip-api.com/json/", lambda d: (
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


def fetch_sun_times(lat: float, lng: float, tz_name: str | None = None,
                    date: _dt.date | None = None,
                    timeout: float = DEFAULT_TIMEOUT) -> dict[str, float]:
    """Sunrise/sunset as local wall-clock hour floats for ``date`` (today).

    Returns ``{"sunrise": float, "sunset": float}`` (e.g. 7.05 and 18.7).
    """
    date = date or _dt.date.today()
    url = (
        "https://api.sunrise-sunset.org/json"
        f"?lat={lat}&lng={lng}&date={date.isoformat()}&formatted=0"
    )
    data = _open(url, timeout)
    results = data["results"]
    tz = local_tz(tz_name)
    return {
        "sunrise": hour_float(results["sunrise"], tz),
        "sunset": hour_float(results["sunset"], tz),
    }
