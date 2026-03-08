"""Service for CP Comboios de Portugal train data in the Porto area.

Uses hardcoded station/line data and frequency-based departure estimation,
following the same pattern as the metro service.
"""

import logging
import math
from datetime import datetime, time, timedelta

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=300)

# CP train lines serving the Porto area
CP_LINES = {
    "aveiro": {
        "name": "Linha de Aveiro",
        "emoji": "\U0001f7e2",  # green circle
        "route": "Campanha \u2194 Espinho \u2194 Aveiro",
        "type": "urbano",
    },
    "braga": {
        "name": "Linha de Braga",
        "emoji": "\U0001f535",  # blue circle
        "route": "S\u00e3o Bento \u2194 Campanha \u2194 Ermesinde \u2194 Braga",
        "type": "urbano",
    },
    "guimaraes": {
        "name": "Linha de Guimar\u00e3es",
        "emoji": "\U0001f7e1",  # yellow circle
        "route": "Campanha \u2194 Ermesinde \u2194 Guimar\u00e3es",
        "type": "urbano",
    },
    "marco": {
        "name": "Linha do Marco",
        "emoji": "\U0001f7e0",  # orange circle
        "route": "Campanha \u2194 Ca\u00edde \u2194 Marco de Canaveses",
        "type": "urbano",
    },
    "minho": {
        "name": "Linha do Minho",
        "emoji": "\U0001f534",  # red circle
        "route": "Campanha \u2194 Nine \u2194 Viana do Castelo",
        "type": "regional",
    },
}

# Porto-area CP stations with coordinates and line associations
STATIONS: dict[str, dict] = {
    "Porto-Campanha": {
        "lat": 41.1489,
        "lon": -8.5856,
        "lines": ["aveiro", "braga", "guimaraes", "marco", "minho"],
    },
    "Porto-S\u00e3o Bento": {
        "lat": 41.1455,
        "lon": -8.6103,
        "lines": ["braga"],
    },
    "Ermesinde": {
        "lat": 41.2141,
        "lon": -8.5524,
        "lines": ["braga", "guimaraes"],
    },
    "Contumil": {
        "lat": 41.1616,
        "lon": -8.5780,
        "lines": ["braga", "guimaraes", "marco"],
    },
    "Rio Tinto": {
        "lat": 41.1780,
        "lon": -8.5610,
        "lines": ["braga", "guimaraes", "marco"],
    },
    "Valongo": {
        "lat": 41.1932,
        "lon": -8.5010,
        "lines": ["braga", "guimaraes", "marco"],
    },
    "General Torres": {
        "lat": 41.1340,
        "lon": -8.6120,
        "lines": ["aveiro"],
    },
    "Espinho": {
        "lat": 41.0082,
        "lon": -8.6413,
        "lines": ["aveiro"],
    },
    "Aveiro": {
        "lat": 40.6443,
        "lon": -8.6455,
        "lines": ["aveiro"],
    },
    "Braga": {
        "lat": 41.5495,
        "lon": -8.4340,
        "lines": ["braga"],
    },
    "Guimar\u00e3es": {
        "lat": 41.4428,
        "lon": -8.2917,
        "lines": ["guimaraes"],
    },
    "Marco de Canaveses": {
        "lat": 41.1840,
        "lon": -8.1510,
        "lines": ["marco"],
    },
    "Ca\u00edde": {
        "lat": 41.1510,
        "lon": -8.3450,
        "lines": ["marco"],
    },
    "Paredes": {
        "lat": 41.2050,
        "lon": -8.3310,
        "lines": ["marco"],
    },
    "Penafiel": {
        "lat": 41.2050,
        "lon": -8.2820,
        "lines": ["marco"],
    },
    "Nine": {
        "lat": 41.4050,
        "lon": -8.5150,
        "lines": ["braga", "minho"],
    },
    "Viana do Castelo": {
        "lat": 41.6940,
        "lon": -8.8300,
        "lines": ["minho"],
    },
    "Granja": {
        "lat": 41.0516,
        "lon": -8.6368,
        "lines": ["aveiro"],
    },
    "Espinho-Vouga": {
        "lat": 40.9920,
        "lon": -8.6410,
        "lines": ["aveiro"],
    },
    "S\u00e3o F\u00e9lix da Marinha": {
        "lat": 41.0670,
        "lon": -8.6340,
        "lines": ["aveiro"],
    },
    "Miramar": {
        "lat": 41.0780,
        "lon": -8.6360,
        "lines": ["aveiro"],
    },
    "Valadares": {
        "lat": 41.0950,
        "lon": -8.6310,
        "lines": ["aveiro"],
    },
    "Cete": {
        "lat": 41.1770,
        "lon": -8.3570,
        "lines": ["marco"],
    },
    "Lordelo": {
        "lat": 41.1950,
        "lon": -8.4010,
        "lines": ["marco"],
    },
    "Rece\u00e3o": {
        "lat": 41.1720,
        "lon": -8.4340,
        "lines": ["marco"],
    },
    "S\u00e3o Rom\u00e3o": {
        "lat": 41.2040,
        "lon": -8.5340,
        "lines": ["braga", "guimaraes"],
    },
    "Le\u00e7a do Balio": {
        "lat": 41.2100,
        "lon": -8.5880,
        "lines": ["braga"],
    },
    "S\u00e3o Gemil": {
        "lat": 41.2280,
        "lon": -8.5450,
        "lines": ["braga"],
    },
    "Trofa": {
        "lat": 41.3390,
        "lon": -8.5600,
        "lines": ["braga"],
    },
    "Lous\u00e3do": {
        "lat": 41.3820,
        "lon": -8.5120,
        "lines": ["braga", "guimaraes"],
    },
    "Vizela": {
        "lat": 41.3870,
        "lon": -8.3060,
        "lines": ["guimaraes"],
    },
    "Santo Tirso": {
        "lat": 41.3440,
        "lon": -8.4750,
        "lines": ["guimaraes"],
    },
}

# Typical frequencies (minutes between trains)
FREQUENCIES = {
    "peak": {"aveiro": 30, "braga": 30, "guimaraes": 30, "marco": 60, "minho": 120},
    "off_peak": {"aveiro": 60, "braga": 60, "guimaraes": 60, "marco": 90, "minho": 180},
    "weekend": {"aveiro": 60, "braga": 60, "guimaraes": 60, "marco": 120, "minho": 180},
}

# Operating hours
OPERATING_HOURS = {"start": time(5, 30), "end": time(0, 30)}


def search_stations(query: str) -> list[dict]:
    """Search for CP stations by name with smart matching."""
    from bot.utils.search import fuzzy_search

    query = query.strip()
    if not query:
        return []

    station_names = list(STATIONS.keys())
    matches = fuzzy_search(query, station_names, min_score=15, max_results=15)

    results = []
    for name, score in matches:
        data = STATIONS[name]
        lines_info = []
        for line_id in data["lines"]:
            line_data = CP_LINES.get(line_id, {})
            lines_info.append({
                "id": line_id,
                "name": line_data.get("name", line_id),
                "emoji": line_data.get("emoji", "\U0001f686"),
            })
        results.append({
            "name": name,
            "lines": lines_info,
            "lat": data["lat"],
            "lon": data["lon"],
        })

    return results


def get_station_info(name: str) -> dict | None:
    """Get detailed station information."""
    data = STATIONS.get(name)
    if not data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(name, list(STATIONS.keys()), min_score=40, max_results=1)
        if matches:
            name = matches[0][0]
            data = STATIONS[name]
    if not data:
        return None

    lines_info = []
    for line_id in data["lines"]:
        line_data = CP_LINES.get(line_id, {})
        lines_info.append({
            "id": line_id,
            "name": line_data.get("name", line_id),
            "emoji": line_data.get("emoji", "\U0001f686"),
            "route": line_data.get("route", ""),
            "type": line_data.get("type", ""),
        })

    return {
        "name": name,
        "lat": data["lat"],
        "lon": data["lon"],
        "lines": lines_info,
    }


def get_next_departures(station_name: str, line_id: str | None = None,
                        count: int = 5) -> list[dict]:
    """Estimate next departures from a station based on frequencies."""
    station_data = STATIONS.get(station_name)
    if not station_data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(station_name, list(STATIONS.keys()),
                               min_score=40, max_results=1)
        if matches:
            station_name = matches[0][0]
            station_data = STATIONS[station_name]
    if not station_data:
        return []

    now = datetime.now()
    current_time = now.time()

    if not _is_operating(current_time):
        return [{
            "direction": "Servi\u00e7o encerrado",
            "time": (
                f"Funcionamento: "
                f"{OPERATING_HOURS['start'].strftime('%H:%M')} - "
                f"{OPERATING_HOURS['end'].strftime('%H:%M')}"
            ),
            "line": "",
        }]

    freq_type = _get_frequency_type(now)
    frequencies = FREQUENCIES[freq_type]

    departures = []
    lines_to_check = [line_id] if line_id else station_data["lines"]

    for lid in lines_to_check:
        if lid not in CP_LINES:
            continue
        line_data = CP_LINES[lid]
        freq_minutes = frequencies.get(lid, 60)

        minutes_since_hour = now.minute + now.second / 60
        next_in = freq_minutes - (minutes_since_hour % freq_minutes)
        if next_in < 1:
            next_in += freq_minutes

        for i in range(count):
            dep_time = now + timedelta(minutes=next_in + i * freq_minutes)
            if dep_time.time() > OPERATING_HOURS["end"] and dep_time.hour < 5:
                break

            route = line_data.get("route", "")
            endpoints = route.split(" \u2194 ") if " \u2194 " in route else [route, ""]
            # Show terminal destinations
            for direction in [endpoints[0], endpoints[-1]]:
                if direction:
                    departures.append({
                        "direction": direction,
                        "time": f"~{dep_time.strftime('%H:%M')}",
                        "line": f"{line_data['emoji']} {line_data['name']}",
                        "line_id": lid,
                        "estimated": True,
                        "minutes": int(next_in + i * freq_minutes),
                    })

    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures[:count * 2]


def get_nearby_stations(lat: float, lon: float,
                        radius_km: float = 2.0) -> list[dict]:
    """Find CP stations within a given radius of coordinates."""
    nearby = []
    for name, data in STATIONS.items():
        slat = data.get("lat")
        slon = data.get("lon")
        if not slat or not slon:
            continue
        dist = _haversine(lat, lon, slat, slon)
        if dist <= radius_km:
            lines_info = []
            for lid in data["lines"]:
                ld = CP_LINES.get(lid, {})
                lines_info.append({
                    "id": lid,
                    "name": ld.get("name", lid),
                    "emoji": ld.get("emoji", "\U0001f686"),
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
    """Get information about all CP train lines."""
    return [
        {
            "id": lid,
            "name": data["name"],
            "emoji": data["emoji"],
            "route": data["route"],
            "type": data["type"],
            "station_count": len(get_line_stations(lid)),
        }
        for lid, data in CP_LINES.items()
    ]


def get_line_stations(line_id: str) -> list[str]:
    """Get all stations for a specific CP line."""
    line_stations = []
    for name, data in STATIONS.items():
        if line_id in data["lines"]:
            line_stations.append(name)
    return line_stations


def get_frequency_info(line_id: str) -> dict:
    """Get frequency information for a specific line."""
    return {
        "peak": f"A cada {FREQUENCIES['peak'].get(line_id, '?')} min",
        "off_peak": f"A cada {FREQUENCIES['off_peak'].get(line_id, '?')} min",
        "weekend": f"A cada {FREQUENCIES['weekend'].get(line_id, '?')} min",
        "hours": (
            f"{OPERATING_HOURS['start'].strftime('%H:%M')} - "
            f"{OPERATING_HOURS['end'].strftime('%H:%M')}"
        ),
    }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance in km between two points on Earth."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_operating(current_time: time) -> bool:
    """Check if CP trains are currently operating."""
    start = OPERATING_HOURS["start"]
    end = OPERATING_HOURS["end"]
    if end < start:  # crosses midnight
        return current_time >= start or current_time <= end
    return start <= current_time <= end


def _get_frequency_type(now: datetime) -> str:
    """Determine the current frequency type based on day/time."""
    weekday = now.weekday()
    hour = now.hour

    if weekday >= 5:
        return "weekend"
    if 7 <= hour <= 9 or 17 <= hour <= 19:
        return "peak"
    return "off_peak"
