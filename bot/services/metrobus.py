"""Service for Porto MetroBus (BRT - Bus Rapid Transit) data.

Uses hardcoded planned/operating lines and frequency-based estimated departures,
following the same patterns as the Metro service.
"""

import logging
import math
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

# MetroBus lines
METROBUS_LINES = {
    "1": {
        "name": "Linha 1 (Boavista)",
        "emoji": "\U0001f68d",  # bus emoji
        "route": "Casa da Música ↔ Matosinhos",
    },
    "2": {
        "name": "Linha 2 (Campo Alegre)",
        "emoji": "\U0001f68d",
        "route": "Praça da Galiza ↔ Antas",
    },
    "3": {
        "name": "Linha 3 (VCI)",
        "emoji": "\U0001f68d",
        "route": "Campanhã ↔ Ramalde",
    },
}

# Complete list of MetroBus stops with line associations and coordinates
STOPS: dict[str, dict] = {
    # Line 1 (Boavista): Casa da Música → Matosinhos
    "Casa da Música (MetroBus)": {"lines": ["1"], "zone": "PRT", "lat": 41.1585, "lon": -8.6305},
    "Rotunda da Boavista": {"lines": ["1"], "zone": "PRT", "lat": 41.1578, "lon": -8.6260},
    "Bom Sucesso": {"lines": ["1"], "zone": "PRT", "lat": 41.1592, "lon": -8.6350},
    "Avenida da Boavista": {"lines": ["1"], "zone": "PRT", "lat": 41.1615, "lon": -8.6420},
    "Fluvial": {"lines": ["1"], "zone": "PRT", "lat": 41.1640, "lon": -8.6490},
    "Fonte da Moura": {"lines": ["1"], "zone": "PRT", "lat": 41.1665, "lon": -8.6530},
    "Francos (MetroBus)": {"lines": ["1"], "zone": "PRT", "lat": 41.1690, "lon": -8.6570},
    "Viso (MetroBus)": {"lines": ["1"], "zone": "PRT", "lat": 41.1720, "lon": -8.6600},
    "Estádio do Bessa": {"lines": ["1"], "zone": "PRT", "lat": 41.1740, "lon": -8.6630},
    "Norton de Matos": {"lines": ["1"], "zone": "MTS", "lat": 41.1760, "lon": -8.6660},
    "Jardim de Matosinhos": {"lines": ["1"], "zone": "MTS", "lat": 41.1790, "lon": -8.6710},
    "Matosinhos (MetroBus)": {"lines": ["1"], "zone": "MTS", "lat": 41.1820, "lon": -8.6750},
    # Line 2 (Campo Alegre): Praça da Galiza → Antas
    "Praça da Galiza": {"lines": ["2"], "zone": "PRT", "lat": 41.1530, "lon": -8.6305},
    "Campo Alegre": {"lines": ["2"], "zone": "PRT", "lat": 41.1510, "lon": -8.6340},
    "Arrábida": {"lines": ["2"], "zone": "PRT", "lat": 41.1485, "lon": -8.6380},
    "Flor da Rosa": {"lines": ["2"], "zone": "PRT", "lat": 41.1475, "lon": -8.6300},
    "Lordelo": {"lines": ["2"], "zone": "PRT", "lat": 41.1465, "lon": -8.6250},
    "Passeio Alegre": {"lines": ["2"], "zone": "PRT", "lat": 41.1460, "lon": -8.6180},
    "Massarelos": {"lines": ["2"], "zone": "PRT", "lat": 41.1470, "lon": -8.6110},
    "Restauração": {"lines": ["2"], "zone": "PRT", "lat": 41.1490, "lon": -8.6050},
    "Constituição": {"lines": ["2"], "zone": "PRT", "lat": 41.1520, "lon": -8.5960},
    "Antas": {"lines": ["2"], "zone": "PRT", "lat": 41.1610, "lon": -8.5860},
    # Line 3 (VCI): Campanhã → Ramalde (circular via VCI)
    "Campanhã (MetroBus)": {"lines": ["3"], "zone": "PRT", "lat": 41.1487, "lon": -8.5853},
    "Via de Cintura Interna Este": {"lines": ["3"], "zone": "PRT", "lat": 41.1530, "lon": -8.5870},
    "Amial": {"lines": ["3"], "zone": "PRT", "lat": 41.1620, "lon": -8.5910},
    "Paranhos": {"lines": ["3"], "zone": "PRT", "lat": 41.1680, "lon": -8.5990},
    "Hospital de São João (MetroBus)": {"lines": ["3"], "zone": "PRT", "lat": 41.1856, "lon": -8.6020},
    "Polo Universitário (MetroBus)": {"lines": ["3"], "zone": "PRT", "lat": 41.1762, "lon": -8.6019},
    "Via de Cintura Interna Oeste": {"lines": ["3"], "zone": "PRT", "lat": 41.1730, "lon": -8.6150},
    "Prelada": {"lines": ["3"], "zone": "PRT", "lat": 41.1720, "lon": -8.6250},
    "Carvalhido": {"lines": ["3"], "zone": "PRT", "lat": 41.1730, "lon": -8.6320},
    "Ramalde (MetroBus)": {"lines": ["3"], "zone": "PRT", "lat": 41.1766, "lon": -8.6395},
}

# Typical frequencies (minutes between departures)
FREQUENCIES = {
    "peak": {"1": 5, "2": 6, "3": 8},
    "off_peak": {"1": 10, "2": 12, "3": 15},
    "weekend": {"1": 12, "2": 15, "3": 18},
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
    """Get all stops for a specific MetroBus line, in order."""
    line_stops = []
    for name, data in STOPS.items():
        if line_id in data["lines"]:
            line_stops.append(name)
    return line_stops


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
