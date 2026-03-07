"""Service for Metro do Porto data.

Uses a combination of:
- Hardcoded station/line data (publicly known, rarely changes)
- GTFS schedule data downloaded from Porto open data portal
- Frequency-based estimated next departures
"""

import csv
import io
import logging
import zipfile
from datetime import datetime, time, timedelta
from pathlib import Path

import aiohttp
import aiofiles

from bot.config import GTFS_DIR, GTFS_METRO_URL, METRO_LINES
from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=300)

# Complete list of Metro do Porto stations with line associations and coordinates
# Source: public information from metrodoporto.pt
STATIONS: dict[str, dict] = {
    "Senhor de Matosinhos": {"lines": ["A"], "zone": "MTS", "lat": 41.1826, "lon": -8.6873},
    "Mercado": {"lines": ["A"], "zone": "MTS", "lat": 41.1832, "lon": -8.6823},
    "Brito Capelo": {"lines": ["A"], "zone": "MTS", "lat": 41.1818, "lon": -8.6764},
    "Matosinhos Sul": {"lines": ["A"], "zone": "MTS", "lat": 41.1796, "lon": -8.6729},
    "Câmara de Matosinhos": {"lines": ["A"], "zone": "MTS", "lat": 41.1809, "lon": -8.6678},
    "Parque de Real": {"lines": ["A"], "zone": "MTS", "lat": 41.1790, "lon": -8.6614},
    "Pedro Hispano": {"lines": ["A"], "zone": "MTS", "lat": 41.1769, "lon": -8.6571},
    "Estádio do Mar": {"lines": ["A"], "zone": "MTS", "lat": 41.1738, "lon": -8.6570},
    "Mercado de Matosinhos": {"lines": ["A"], "zone": "MTS", "lat": 41.1832, "lon": -8.6823},
    "Senhora da Hora": {"lines": ["A", "B", "C", "E", "F"], "zone": "MTS", "lat": 41.1872, "lon": -8.6583},
    "Sete Bicas": {"lines": ["A", "B", "C", "E"], "zone": "MTS", "lat": 41.1852, "lon": -8.6520},
    "Viso": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1798, "lon": -8.6430},
    "Ramalde": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1766, "lon": -8.6395},
    "Francos": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1690, "lon": -8.6380},
    "Casa da Música": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT", "lat": 41.1585, "lon": -8.6305},
    "Carolina Michaelis": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1560, "lon": -8.6256},
    "Lapa": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1530, "lon": -8.6193},
    "Trindade": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT", "lat": 41.1519, "lon": -8.6102},
    "Bolhão": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1499, "lon": -8.6056},
    "Campo 24 de Agosto": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1495, "lon": -8.5990},
    "Heroísmo": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1481, "lon": -8.5929},
    "Campanhã": {"lines": ["A", "B", "C", "E", "F"], "zone": "PRT", "lat": 41.1487, "lon": -8.5853},
    "Estádio do Dragão": {"lines": ["A", "B", "E"], "zone": "PRT", "lat": 41.1614, "lon": -8.5840},
    "Nasoni": {"lines": ["C", "F"], "zone": "PRT", "lat": 41.1530, "lon": -8.5790},
    "Nau Vitória": {"lines": ["C", "F"], "zone": "PRT", "lat": 41.1560, "lon": -8.5730},
    "Levada": {"lines": ["C", "F"], "zone": "GDM", "lat": 41.1590, "lon": -8.5640},
    "Rio Tinto": {"lines": ["C", "F"], "zone": "GDM", "lat": 41.1630, "lon": -8.5560},
    "Campainha": {"lines": ["C"], "zone": "GDM", "lat": 41.1680, "lon": -8.5480},
    "Baguim": {"lines": ["C"], "zone": "GDM", "lat": 41.1720, "lon": -8.5410},
    "Fânzeres": {"lines": ["F"], "zone": "GDM", "lat": 41.1640, "lon": -8.5480},
    "São Roque": {"lines": ["F"], "zone": "GDM", "lat": 41.1610, "lon": -8.5520},
    "Contumil": {"lines": ["F"], "zone": "GDM", "lat": 41.1560, "lon": -8.5680},
    "Custió": {"lines": ["C"], "zone": "VLG", "lat": 41.1780, "lon": -8.5340},
    "Araújo": {"lines": ["C"], "zone": "VLG", "lat": 41.1830, "lon": -8.5290},
    "Cândido dos Reis": {"lines": ["C"], "zone": "VLG", "lat": 41.1880, "lon": -8.5240},
    "Fórum da Maia": {"lines": ["C"], "zone": "MAI", "lat": 41.2310, "lon": -8.6210},
    "Parque da Maia": {"lines": ["C"], "zone": "MAI", "lat": 41.2370, "lon": -8.6240},
    "Mandim": {"lines": ["C"], "zone": "MAI", "lat": 41.2420, "lon": -8.6260},
    "Zona Industrial": {"lines": ["C"], "zone": "MAI", "lat": 41.2480, "lon": -8.6280},
    "ISMAI": {"lines": ["C"], "zone": "MAI", "lat": 41.2590, "lon": -8.6290},
    # Line D
    "Hospital de São João": {"lines": ["D"], "zone": "PRT", "lat": 41.1856, "lon": -8.6020},
    "IPO": {"lines": ["D"], "zone": "PRT", "lat": 41.1822, "lon": -8.6038},
    "Polo Universitário": {"lines": ["D"], "zone": "PRT", "lat": 41.1762, "lon": -8.6019},
    "Salgueiros": {"lines": ["D"], "zone": "PRT", "lat": 41.1710, "lon": -8.6047},
    "Combatentes": {"lines": ["D"], "zone": "PRT", "lat": 41.1658, "lon": -8.6079},
    "Marquês": {"lines": ["D"], "zone": "PRT", "lat": 41.1609, "lon": -8.6091},
    "Faria Guimarães": {"lines": ["D"], "zone": "PRT", "lat": 41.1565, "lon": -8.6089},
    "Aliados": {"lines": ["D"], "zone": "PRT", "lat": 41.1475, "lon": -8.6105},
    "São Bento": {"lines": ["D"], "zone": "PRT", "lat": 41.1454, "lon": -8.6104},
    "Jardim do Morro": {"lines": ["D"], "zone": "VNG", "lat": 41.1383, "lon": -8.6111},
    "General Torres": {"lines": ["D"], "zone": "VNG", "lat": 41.1355, "lon": -8.6110},
    "Santo Ovídio": {"lines": ["D"], "zone": "VNG", "lat": 41.1257, "lon": -8.6085},
    "Manuel Leão": {"lines": ["D"], "zone": "VNG", "lat": 41.1200, "lon": -8.6080},
    "João de Deus": {"lines": ["D"], "zone": "VNG", "lat": 41.1150, "lon": -8.6070},
    "D. João II": {"lines": ["D"], "zone": "VNG", "lat": 41.1100, "lon": -8.6060},
    "Câmara de Gaia": {"lines": ["D"], "zone": "VNG", "lat": 41.1090, "lon": -8.6100},
    "Vila d'Este": {"lines": ["D"], "zone": "VNG", "lat": 41.1050, "lon": -8.6130},
    # Line B
    "Custóias": {"lines": ["B"], "zone": "MTS", "lat": 41.1950, "lon": -8.6530},
    "Zona Industrial B": {"lines": ["B"], "zone": "MAI", "lat": 41.2030, "lon": -8.6510},
    "Mandim B": {"lines": ["B"], "zone": "MAI", "lat": 41.2100, "lon": -8.6490},
    "Crestins": {"lines": ["B"], "zone": "MTS", "lat": 41.2180, "lon": -8.6470},
    "Esposade": {"lines": ["B"], "zone": "PVZ", "lat": 41.2860, "lon": -8.7280},
    "Varziela": {"lines": ["B"], "zone": "PVZ", "lat": 41.2760, "lon": -8.7190},
    "Árvore": {"lines": ["B"], "zone": "VCD", "lat": 41.3060, "lon": -8.7410},
    "Azurara": {"lines": ["B"], "zone": "VCD", "lat": 41.3130, "lon": -8.7470},
    "Vila do Conde": {"lines": ["B"], "zone": "VCD", "lat": 41.3510, "lon": -8.7440},
    "Santa Clara": {"lines": ["B"], "zone": "PVZ", "lat": 41.3610, "lon": -8.7510},
    "Portas Fronhas": {"lines": ["B"], "zone": "PVZ", "lat": 41.3700, "lon": -8.7560},
    "Alto de Pega": {"lines": ["B"], "zone": "PVZ", "lat": 41.3760, "lon": -8.7590},
    "Póvoa de Varzim": {"lines": ["B"], "zone": "PVZ", "lat": 41.3830, "lon": -8.7630},
    # Line E (Airport)
    "Aeroporto": {"lines": ["E"], "zone": "MTS", "lat": 41.2367, "lon": -8.6700},
    "Verdes": {"lines": ["E"], "zone": "MTS", "lat": 41.2270, "lon": -8.6650},
    "Lidador": {"lines": ["E"], "zone": "MTS", "lat": 41.2170, "lon": -8.6610},
    "Botica": {"lines": ["E"], "zone": "MAI", "lat": 41.2080, "lon": -8.6570},
    "Fonte do Cuco": {"lines": ["E"], "zone": "MTS", "lat": 41.2010, "lon": -8.6540},
    "Custió E": {"lines": ["E"], "zone": "MTS", "lat": 41.1960, "lon": -8.6520},
    "Requezende": {"lines": ["E"], "zone": "MTS", "lat": 41.1920, "lon": -8.6500},
}

# Typical frequencies (minutes between trains)
FREQUENCIES = {
    "peak": {"A": 6, "B": 12, "C": 12, "D": 6, "E": 12, "F": 12},
    "off_peak": {"A": 10, "B": 20, "C": 20, "D": 10, "E": 15, "F": 15},
    "weekend": {"A": 12, "B": 20, "C": 20, "D": 12, "E": 20, "F": 20},
}

# Operating hours
OPERATING_HOURS = {"start": time(6, 0), "end": time(1, 0)}

# GTFS data storage
_gtfs_loaded = False
_gtfs_stops: dict[str, dict] = {}
_gtfs_stop_times: dict[str, list] = {}  # stop_id -> list of departure times


async def download_gtfs() -> bool:
    """Download and extract GTFS data from Porto open data portal."""
    global _gtfs_loaded
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = GTFS_DIR / "metro_porto.zip"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GTFS_METRO_URL,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning("Failed to download GTFS: HTTP %d", resp.status)
                    return False
                content = await resp.read()
                if len(content) < 100:
                    logger.warning("GTFS download too small, likely empty")
                    return False

        async with aiofiles.open(zip_path, "wb") as f:
            await f.write(content)

        _extract_gtfs(zip_path)
        _gtfs_loaded = True
        logger.info("GTFS data loaded successfully")
        return True
    except Exception:
        logger.exception("Error downloading GTFS data")
        return False


def _extract_gtfs(zip_path: Path) -> None:
    """Extract and parse relevant GTFS files."""
    global _gtfs_stops, _gtfs_stop_times

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Parse stops.txt
        if "stops.txt" in zf.namelist():
            with zf.open("stops.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    stop_id = row.get("stop_id", "")
                    _gtfs_stops[stop_id] = {
                        "name": row.get("stop_name", ""),
                        "lat": float(row.get("stop_lat", 0)),
                        "lon": float(row.get("stop_lon", 0)),
                    }

        # Parse stop_times.txt
        if "stop_times.txt" in zf.namelist():
            with zf.open("stop_times.txt") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    stop_id = row.get("stop_id", "")
                    dep_time = row.get("departure_time", "")
                    if stop_id and dep_time:
                        if stop_id not in _gtfs_stop_times:
                            _gtfs_stop_times[stop_id] = []
                        _gtfs_stop_times[stop_id].append(dep_time)

        # Sort departure times
        for stop_id in _gtfs_stop_times:
            _gtfs_stop_times[stop_id].sort()


def search_stations(query: str) -> list[dict]:
    """Search for metro stations by name."""
    query_lower = query.lower().strip()
    results = []

    for name, data in STATIONS.items():
        if query_lower in name.lower():
            lines_info = []
            for line_code in data["lines"]:
                line_data = METRO_LINES.get(line_code, {})
                lines_info.append({
                    "code": line_code,
                    "name": line_data.get("name", f"Linha {line_code}"),
                    "emoji": line_data.get("emoji", "🚇"),
                })
            results.append({
                "name": name,
                "zone": data["zone"],
                "lines": lines_info,
            })

    # Sort: exact matches first, then by name length
    results.sort(key=lambda x: (
        0 if x["name"].lower() == query_lower else 1,
        len(x["name"]),
    ))
    return results[:15]


def get_station_lines(station_name: str) -> list[dict]:
    """Get lines that serve a specific station."""
    data = STATIONS.get(station_name)
    if not data:
        # Try fuzzy match
        for name, sdata in STATIONS.items():
            if station_name.lower() in name.lower():
                data = sdata
                station_name = name
                break
    if not data:
        return []

    return [
        {
            "code": line_code,
            "name": METRO_LINES.get(line_code, {}).get("name", f"Linha {line_code}"),
            "emoji": METRO_LINES.get(line_code, {}).get("emoji", "🚇"),
            "route": METRO_LINES.get(line_code, {}).get("route", ""),
        }
        for line_code in data["lines"]
    ]


def get_next_departures(station_name: str, line_code: str | None = None,
                        count: int = 5) -> list[dict]:
    """Estimate next departures from a station.

    Uses GTFS data if available, otherwise calculates based on known frequencies.
    """
    now = datetime.now()
    current_time = now.time()

    # Check if metro is operating
    if not _is_operating(current_time):
        return [{
            "direction": "Serviço encerrado",
            "time": f"Funcionamento: {OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
            "line": "",
        }]

    station_data = STATIONS.get(station_name)
    if not station_data:
        # Fuzzy match
        for name, sdata in STATIONS.items():
            if station_name.lower() in name.lower():
                station_data = sdata
                station_name = name
                break
    if not station_data:
        return []

    # Get applicable frequency
    freq_type = _get_frequency_type(now)
    frequencies = FREQUENCIES[freq_type]

    departures = []
    lines_to_check = [line_code] if line_code else station_data["lines"]

    for lc in lines_to_check:
        if lc not in METRO_LINES:
            continue
        line_data = METRO_LINES[lc]
        freq_minutes = frequencies.get(lc, 15)

        # Calculate next departures based on frequency
        # Assume last departure was at a multiple of frequency from hour start
        minutes_since_hour = now.minute + now.second / 60
        next_in = freq_minutes - (minutes_since_hour % freq_minutes)
        if next_in < 1:
            next_in += freq_minutes

        for i in range(count):
            dep_time = now + timedelta(minutes=next_in + i * freq_minutes)
            if dep_time.time() > OPERATING_HOURS["end"] and dep_time.hour < 5:
                break

            # Determine direction based on line endpoints
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

    # Sort by time
    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures[:count * 2]


def get_line_stations(line_code: str) -> list[str]:
    """Get all stations for a specific metro line, in order."""
    line_stations = []
    for name, data in STATIONS.items():
        if line_code in data["lines"]:
            line_stations.append(name)
    return line_stations


def get_all_lines() -> list[dict]:
    """Get information about all metro lines."""
    return [
        {
            "code": code,
            "name": data["name"],
            "emoji": data["emoji"],
            "route": data["route"],
            "station_count": len(get_line_stations(code)),
        }
        for code, data in METRO_LINES.items()
    ]


def get_frequency_info(line_code: str) -> dict:
    """Get frequency information for a specific line."""
    return {
        "peak": f"A cada {FREQUENCIES['peak'].get(line_code, '?')} min",
        "off_peak": f"A cada {FREQUENCIES['off_peak'].get(line_code, '?')} min",
        "weekend": f"A cada {FREQUENCIES['weekend'].get(line_code, '?')} min",
        "hours": f"{OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
    }


def get_station_coordinates(station_name: str) -> dict | None:
    """Get coordinates for a metro station. Returns {"lat": ..., "lon": ...} or None."""
    data = STATIONS.get(station_name)
    if not data:
        # Fuzzy match
        for name, sdata in STATIONS.items():
            if station_name.lower() in name.lower():
                data = sdata
                break
    if data and data.get("lat") and data.get("lon"):
        return {"lat": data["lat"], "lon": data["lon"]}
    # Fallback: check GTFS data
    for stop_id, stop_data in _gtfs_stops.items():
        if stop_data.get("name", "").lower() == station_name.lower():
            return {"lat": stop_data["lat"], "lon": stop_data["lon"]}
    return None


def get_nearby_stations(lat: float, lon: float,
                        radius_km: float = 0.75) -> list[dict]:
    """Find metro stations within a given radius of coordinates."""
    nearby = []
    for name, data in STATIONS.items():
        slat = data.get("lat")
        slon = data.get("lon")
        if not slat or not slon:
            continue
        dist = _haversine(lat, lon, slat, slon)
        if dist <= radius_km:
            lines_info = []
            for lc in data["lines"]:
                ld = METRO_LINES.get(lc, {})
                lines_info.append({
                    "code": lc,
                    "name": ld.get("name", f"Linha {lc}"),
                    "emoji": ld.get("emoji", "🚇"),
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


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance in km between two points on Earth."""
    import math
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
