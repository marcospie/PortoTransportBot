"""Service for Porto MetroBus (BRT - Bus Rapid Transit) data.

Data provenance — read before trusting anything here
----------------------------------------------------
**There is no open dataset for the MetroBus.** Verified 2026-07-26: the Porto
open data portal (CKAN ``package_search``) returns *zero* results for
"metrobus", "brt" and "boavista", and its only two GTFS datasets are Metro do
Porto and STCP — neither of which contains a MetroBus route.  So this module
cannot be GTFS-derived the way :mod:`bot.services.metro` now is.

What was corrected, and against what
------------------------------------
The previous table was not survey data: its coordinates climbed in uniform
0.002-0.003 steps and ran *north-east* to 41.182,-8.675, whereas the real
corridor runs *west* along Avenida da Boavista.  Praça do Império was ~3 km from
its true position.  Coordinates for the stops that correspond to a place we
could verify are now taken from real surveyed feeds:

* ``PR. DO IMPÉRIO`` (41.155866, -8.671349) — STCP GTFS, stops PRI1/PRI4.
* ``BOAVISTA-CASA DA MÚSICA`` (41.158950, -8.629420) — STCP GTFS, stop BCM1.
* ``BOAVISTA (BOM SUCESSO)`` (41.155740, -8.628410) — STCP GTFS, stop BS10.
* ``AV.DA BOAVISTA`` (41.162820, -8.663400) — STCP GTFS, stop ABVT1.
* ``FONTE DA MOURA`` (41.164500, -8.662140) — STCP GTFS, stop FTM1.
* ``FLUVIAL (NORTE)`` (41.152140, -8.655190) — STCP GTFS, stop FLUN1.
* Francos / Viso — Metro do Porto GTFS stops 5711 / 5729.

Stops flagged ``"verified": False`` keep their original approximate position
because no authoritative source for them could be found. ``STOP_DATA_VERIFIED``
and :func:`is_stop_data_verified` let callers say so rather than implying the
list is official.

A second MetroBus corridor is often mentioned in press coverage, but no stop
list or dataset for it could be verified, so **no second line is invented here**.
"""

import logging
import math
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

# No official MetroBus dataset exists (see module docstring). Keep this False so
# the UI can avoid presenting the stop list as published fact.
STOP_DATA_VERIFIED = False
STOP_DATA_SOURCE = (
    "Percurso e terminais confirmados; posições das paragens aproximadas "
    "(não existe dataset aberto do MetroBus)"
)
STOP_DATA_SOURCE_EN = (
    "Route and termini confirmed; stop positions approximate "
    "(no open MetroBus dataset exists)"
)
STOP_DATA_DATE = "2026-07-26"

# MetroBus lines — only Line 1 is known to operate. Terminals verified:
# "Casa da Música" (Metro do Porto GTFS) and "Praça do Império" (STCP GTFS
# stop "PR. DO IMPÉRIO").
METROBUS_LINES = {
    "1": {
        "name": "Linha 1 (Boavista)",
        "emoji": "\U0001f68d",  # bus emoji
        "route": "Casa da Música ↔ Império",
        "route_full": "Casa da Música ↔ Praça do Império",
    },
}

# MetroBus stops. ``verified`` records whether the coordinate came from a real
# surveyed feed (see module docstring) or is still an approximation.
STOPS: dict[str, dict] = {
    "Casa da Música (MetroBus)": {"lines": ["1"], "zone": "PRT",
                                  "lat": 41.158950, "lon": -8.629420,
                                  "verified": True},
    "Rotunda da Boavista": {"lines": ["1"], "zone": "PRT",
                            "lat": 41.157400, "lon": -8.629500,
                            "verified": False},
    "Bom Sucesso": {"lines": ["1"], "zone": "PRT",
                    "lat": 41.155740, "lon": -8.628410,
                    "verified": True},
    "Estádio do Bessa": {"lines": ["1"], "zone": "PRT",
                         "lat": 41.162000, "lon": -8.645500,
                         "verified": False},
    "Avenida da Boavista": {"lines": ["1"], "zone": "PRT",
                            "lat": 41.162820, "lon": -8.663400,
                            "verified": True},
    "Fonte da Moura": {"lines": ["1"], "zone": "PRT",
                       "lat": 41.164500, "lon": -8.662140,
                       "verified": True},
    "Norton de Matos": {"lines": ["1"], "zone": "PRT",
                        "lat": 41.160500, "lon": -8.667000,
                        "verified": False},
    "Fluvial": {"lines": ["1"], "zone": "PRT",
                "lat": 41.152140, "lon": -8.655190,
                "verified": True},
    "Jardim de Matosinhos": {"lines": ["1"], "zone": "MTS",
                             "lat": 41.157500, "lon": -8.669500,
                             "verified": False},
    # Praça do Império, Foz do Douro — inside Porto, not Matosinhos.
    "Império": {"lines": ["1"], "zone": "PRT",
                "lat": 41.155866, "lon": -8.671349,
                "verified": True},
    # Interchanges with the metro, north of the Boavista axis.
    "Francos (MetroBus)": {"lines": ["1"], "zone": "PRT",
                           "lat": 41.165550, "lon": -8.636347,
                           "verified": True},
    "Viso (MetroBus)": {"lines": ["1"], "zone": "PRT",
                        "lat": 41.177250, "lon": -8.646498,
                        "verified": True},
}

# Stop order along Line 1, east (Casa da Música / Boavista) to west (Praça do
# Império). Explicit because dict-insertion order is not a travel order.
LINE_STOP_ORDER: dict[str, list[str]] = {
    "1": [
        "Casa da Música (MetroBus)",
        "Rotunda da Boavista",
        "Bom Sucesso",
        "Francos (MetroBus)",
        "Viso (MetroBus)",
        "Estádio do Bessa",
        "Fonte da Moura",
        "Avenida da Boavista",
        "Norton de Matos",
        "Jardim de Matosinhos",
        "Fluvial",
        "Império",
    ],
}


def is_stop_data_verified() -> bool:
    """False — the MetroBus stop list has no authoritative open source."""
    return STOP_DATA_VERIFIED


# Typical frequencies (minutes between departures). APPROXIMATE: no MetroBus
# timetable is published in machine-readable form.
FREQUENCIES = {
    "peak": {"1": 5},
    "off_peak": {"1": 10},
    "weekend": {"1": 12},
}

# Operating hours
OPERATING_HOURS = {"start": time(6, 0), "end": time(1, 0)}


def search_stops(query: str) -> list[dict]:
    """Search for MetroBus stops by name with smart matching."""
    from bot.utils.search import fuzzy_search

    query = query.strip()
    if not query:
        return []

    stop_names = list(STOPS.keys())
    matches = fuzzy_search(query, stop_names, min_score=15, max_results=15)

    results = []
    for name, score in matches:
        data = STOPS[name]
        lines_info = []
        for line_code in data["lines"]:
            line_data = METROBUS_LINES.get(line_code, {})
            lines_info.append({
                "code": line_code,
                "name": line_data.get("name", f"Linha {line_code}"),
                "emoji": line_data.get("emoji", "\U0001f68d"),
            })
        results.append({
            "name": name,
            "zone": data["zone"],
            "lines": lines_info,
        })

    return results


def get_stop_info(name: str) -> dict | None:
    """Get information about a specific MetroBus stop."""
    data = STOPS.get(name)
    if not data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(name, list(STOPS.keys()), min_score=40, max_results=1)
        if matches:
            name = matches[0][0]
            data = STOPS[name]
    if not data:
        return None

    lines_info = []
    for line_code in data["lines"]:
        line_data = METROBUS_LINES.get(line_code, {})
        lines_info.append({
            "code": line_code,
            "name": line_data.get("name", f"Linha {line_code}"),
            "emoji": line_data.get("emoji", "\U0001f68d"),
            "route": line_data.get("route", ""),
        })

    return {
        "name": name,
        "zone": data["zone"],
        "lat": data["lat"],
        "lon": data["lon"],
        "lines": lines_info,
    }


def get_next_departures(stop_name: str, line_code: str | None = None,
                        count: int = 5) -> list[dict]:
    """Estimate next departures from a MetroBus stop.

    Calculates based on known frequencies (no GTFS for MetroBus).
    """
    stop_data = STOPS.get(stop_name)
    if not stop_data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(stop_name, list(STOPS.keys()), min_score=40, max_results=1)
        if matches:
            stop_name = matches[0][0]
            stop_data = STOPS[stop_name]
    if not stop_data:
        return []

    now = datetime.now()
    current_time = now.time()

    # Check if MetroBus is operating
    if not _is_operating(current_time):
        return [{
            "direction": "Serviço encerrado",
            "time": f"Funcionamento: {OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
            "line": "",
        }]

    # Frequency-based estimation
    freq_type = _get_frequency_type(now)
    frequencies = FREQUENCIES[freq_type]

    departures = []
    lines_to_check = [line_code] if line_code else stop_data["lines"]

    for lc in lines_to_check:
        if lc not in METROBUS_LINES:
            continue
        line_data = METROBUS_LINES[lc]
        freq_minutes = frequencies.get(lc, 15)

        # Calculate next departures based on frequency
        minutes_since_hour = now.minute + now.second / 60
        next_in = freq_minutes - (minutes_since_hour % freq_minutes)
        if next_in < 1:
            next_in += freq_minutes

        for i in range(count):
            dep_time = now + timedelta(minutes=next_in + i * freq_minutes)
            if dep_time.time() > OPERATING_HOURS["end"] and dep_time.hour < 5:
                break

            route = line_data.get("route", "")
            endpoints = route.split(" ↔ ") if " ↔ " in route else [route, ""]

            for direction in endpoints:
                departures.append({
                    "direction": direction,
                    "time": f"~{dep_time.strftime('%H:%M')}",
                    "line": f"{line_data['emoji']} {line_data['name']}",
                    "line_code": lc,
                    "estimated": True,
                    "minutes": int(next_in + i * freq_minutes),
                })

    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures[:count * 2]


def get_nearby_stops(lat: float, lon: float,
                     radius_km: float = 0.5) -> list[dict]:
    """Find MetroBus stops within a given radius of coordinates."""
    nearby = []
    for name, data in STOPS.items():
        slat = data.get("lat")
        slon = data.get("lon")
        if not slat or not slon:
            continue
        dist = _haversine(lat, lon, slat, slon)
        if dist <= radius_km:
            lines_info = []
            for lc in data["lines"]:
                ld = METROBUS_LINES.get(lc, {})
                lines_info.append({
                    "code": lc,
                    "name": ld.get("name", f"Linha {lc}"),
                    "emoji": ld.get("emoji", "\U0001f68d"),
                })
            nearby.append({
                "name": name,
                "distance_m": int(dist * 1000),
                "lines": lines_info,
                "lat": slat,
                "lon": slon,
            })
    nearby.sort(key=lambda x: x["distance_m"])
    return nearby[:10]


def get_all_lines() -> list[dict]:
    """Get information about all MetroBus lines."""
    return [
        {
            "code": code,
            "name": data["name"],
            "emoji": data["emoji"],
            "route": data["route"],
            "stop_count": len(get_line_stops(code)),
        }
        for code, data in METROBUS_LINES.items()
    ]


def get_line_stops(line_id: str) -> list[str]:
    """Get all stops for a specific MetroBus line, in travel order.

    Uses the explicit ``LINE_STOP_ORDER`` sequence; falling back to
    dict-insertion order (the old behaviour) produced a stop list that was not
    a travel order, so the rendered line map made no sense.
    """
    ordered = LINE_STOP_ORDER.get(line_id)
    if ordered:
        return [name for name in ordered if name in STOPS]
    return [name for name, data in STOPS.items() if line_id in data["lines"]]


def get_frequency_info(line_code: str) -> dict:
    """Get frequency information for a specific line."""
    return {
        "peak": f"A cada {FREQUENCIES['peak'].get(line_code, '?')} min",
        "off_peak": f"A cada {FREQUENCIES['off_peak'].get(line_code, '?')} min",
        "weekend": f"A cada {FREQUENCIES['weekend'].get(line_code, '?')} min",
        "hours": f"{OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
    }


def get_stop_coordinates(stop_name: str) -> dict | None:
    """Get coordinates for a MetroBus stop. Returns {"lat": ..., "lon": ...} or None."""
    data = STOPS.get(stop_name)
    if not data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(stop_name, list(STOPS.keys()), min_score=40, max_results=1)
        if matches:
            data = STOPS[matches[0][0]]
    if data and data.get("lat") and data.get("lon"):
        return {"lat": data["lat"], "lon": data["lon"]}
    return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance in km between two points on Earth."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_operating(current_time: time) -> bool:
    start = OPERATING_HOURS["start"]
    end = OPERATING_HOURS["end"]
    if end < start:  # crosses midnight
        return current_time >= start or current_time <= end
    return start <= current_time <= end


def _get_frequency_type(now: datetime) -> str:
    weekday = now.weekday()
    hour = now.hour

    if weekday >= 5:  # Saturday or Sunday
        return "weekend"
    if 7 <= hour <= 9 or 17 <= hour <= 19:
        return "peak"
    return "off_peak"
