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
# Source: OpenStreetMap / overpass-api.de (operator="Metro do Porto")
STATIONS: dict[str, dict] = {
    # Line A (Blue) — Senhor de Matosinhos ↔ Estádio do Dragão
    "Senhor de Matosinhos": {"lines": ["A"], "zone": "MTS", "lat": 41.1882, "lon": -8.6852},
    "Mercado": {"lines": ["A"], "zone": "MTS", "lat": 41.1875, "lon": -8.6935},
    "Brito Capelo": {"lines": ["A"], "zone": "MTS", "lat": 41.1839, "lon": -8.6915},
    "Matosinhos Sul": {"lines": ["A"], "zone": "MTS", "lat": 41.1801, "lon": -8.6886},
    "Câmara de Matosinhos": {"lines": ["A"], "zone": "MTS", "lat": 41.1806, "lon": -8.6813},
    "Parque de Real": {"lines": ["A"], "zone": "MTS", "lat": 41.1791, "lon": -8.6736},
    "Pedro Hispano": {"lines": ["A"], "zone": "MTS", "lat": 41.1803, "lon": -8.6662},
    "Vasco da Gama": {"lines": ["A"], "zone": "MTS", "lat": 41.1903, "lon": -8.6610},
    "Estádio do Mar": {"lines": ["A"], "zone": "MTS", "lat": 41.1857, "lon": -8.6612},
    # Shared trunk — Senhora da Hora ↔ Campanhã
    "Senhora da Hora": {"lines": ["A", "B", "C", "E", "F"], "zone": "MTS", "lat": 41.1881, "lon": -8.6545},
    "Sete Bicas": {"lines": ["A", "B", "C", "E"], "zone": "MTS", "lat": 41.1824, "lon": -8.6522},
    "Viso": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1772, "lon": -8.6465},
    "Ramalde": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1730, "lon": -8.6419},
    "Francos": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1655, "lon": -8.6364},
    "Casa da Música": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT", "lat": 41.1606, "lon": -8.6287},
    "Carolina Michaelis": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1585, "lon": -8.6219},
    "Lapa": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1571, "lon": -8.6168},
    "Trindade": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT", "lat": 41.1523, "lon": -8.6097},
    "Bolhão": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1498, "lon": -8.6058},
    "Campo 24 de Agosto": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1487, "lon": -8.5987},
    "Heroísmo": {"lines": ["A", "B", "C", "E"], "zone": "PRT", "lat": 41.1465, "lon": -8.5930},
    "Campanhã": {"lines": ["A", "B", "C", "E", "F"], "zone": "PRT", "lat": 41.1507, "lon": -8.5856},
    "Estádio do Dragão": {"lines": ["A", "B", "E"], "zone": "PRT", "lat": 41.1607, "lon": -8.5820},
    # Line C / F — east of Campanhã
    "Nasoni": {"lines": ["C", "F"], "zone": "PRT", "lat": 41.1707, "lon": -8.5773},
    "Nau Vitória": {"lines": ["C", "F"], "zone": "PRT", "lat": 41.1741, "lon": -8.5735},
    "Contumil": {"lines": ["F"], "zone": "GDM", "lat": 41.1657, "lon": -8.5787},
    "Levada": {"lines": ["C", "F"], "zone": "GDM", "lat": 41.1757, "lon": -8.5622},
    "Rio Tinto": {"lines": ["C", "F"], "zone": "GDM", "lat": 41.1794, "lon": -8.5602},
    "Campainha": {"lines": ["C"], "zone": "GDM", "lat": 41.1834, "lon": -8.5538},
    "Baguim": {"lines": ["C"], "zone": "GDM", "lat": 41.1855, "lon": -8.5459},
    "Fânzeres": {"lines": ["F"], "zone": "GDM", "lat": 41.1713, "lon": -8.5428},
    "Venda Nova": {"lines": ["F"], "zone": "GDM", "lat": 41.1751, "lon": -8.5419},
    "Carreira": {"lines": ["F"], "zone": "GDM", "lat": 41.1798, "lon": -8.5435},
    # Line C — Maia / ISMAI
    "Custió": {"lines": ["C"], "zone": "VLG", "lat": 41.2223, "lon": -8.6390},
    "Araújo": {"lines": ["C"], "zone": "VLG", "lat": 41.2169, "lon": -8.6411},
    "Cândido dos Reis": {"lines": ["C"], "zone": "VLG", "lat": 41.2007, "lon": -8.6498},
    "Pias": {"lines": ["C"], "zone": "MAI", "lat": 41.2082, "lon": -8.6472},
    "Fórum da Maia": {"lines": ["C"], "zone": "MAI", "lat": 41.2343, "lon": -8.6240},
    "Parque da Maia": {"lines": ["C"], "zone": "MAI", "lat": 41.2291, "lon": -8.6266},
    "Mandim": {"lines": ["C"], "zone": "MAI", "lat": 41.2536, "lon": -8.6284},
    "Zona Industrial": {"lines": ["C"], "zone": "MAI", "lat": 41.2437, "lon": -8.6285},
    "Castêlo da Maia": {"lines": ["C"], "zone": "MAI", "lat": 41.2627, "lon": -8.6170},
    "ISMAI": {"lines": ["C"], "zone": "MAI", "lat": 41.2689, "lon": -8.6154},
    # Line D — Hospital de São João ↔ Hospital Santos Silva
    "Hospital de São João": {"lines": ["D"], "zone": "PRT", "lat": 41.1832, "lon": -8.6023},
    "IPO": {"lines": ["D"], "zone": "PRT", "lat": 41.1812, "lon": -8.6045},
    "Polo Universitário": {"lines": ["D"], "zone": "PRT", "lat": 41.1746, "lon": -8.6036},
    "Salgueiros": {"lines": ["D"], "zone": "PRT", "lat": 41.1693, "lon": -8.5986},
    "Combatentes": {"lines": ["D"], "zone": "PRT", "lat": 41.1651, "lon": -8.5989},
    "Marquês": {"lines": ["D"], "zone": "PRT", "lat": 41.1613, "lon": -8.6093},
    "Faria Guimarães": {"lines": ["D"], "zone": "PRT", "lat": 41.1572, "lon": -8.6093},
    "Aliados": {"lines": ["D"], "zone": "PRT", "lat": 41.1486, "lon": -8.6110},
    "São Bento": {"lines": ["D"], "zone": "PRT", "lat": 41.1448, "lon": -8.6108},
    "Jardim do Morro": {"lines": ["D"], "zone": "VNG", "lat": 41.1376, "lon": -8.6087},
    "General Torres": {"lines": ["D"], "zone": "VNG", "lat": 41.1339, "lon": -8.6075},
    "Câmara de Gaia": {"lines": ["D"], "zone": "VNG", "lat": 41.1297, "lon": -8.6062},
    "João de Deus": {"lines": ["D"], "zone": "VNG", "lat": 41.1261, "lon": -8.6056},
    "Santo Ovídio": {"lines": ["D"], "zone": "VNG", "lat": 41.1155, "lon": -8.6066},
    "D. João II": {"lines": ["D"], "zone": "VNG", "lat": 41.1195, "lon": -8.6062},
    "Manuel Leão": {"lines": ["D"], "zone": "VNG", "lat": 41.1106, "lon": -8.6000},
    "Vila d'Este": {"lines": ["D"], "zone": "VNG", "lat": 41.0986, "lon": -8.5885},
    "Hospital Santos Silva": {"lines": ["D"], "zone": "VNG", "lat": 41.1058, "lon": -8.5911},
    # Line B — Custóias ↔ Póvoa de Varzim
    "Custóias": {"lines": ["B"], "zone": "MTS", "lat": 41.2003, "lon": -8.6556},
    "Crestins": {"lines": ["B"], "zone": "MTS", "lat": 41.2330, "lon": -8.6566},
    "Esposade": {"lines": ["B"], "zone": "PVZ", "lat": 41.2470, "lon": -8.6640},
    "Vilar do Pinheiro": {"lines": ["B"], "zone": "VCD", "lat": 41.2703, "lon": -8.6795},
    "Modivas Sul": {"lines": ["B"], "zone": "VCD", "lat": 41.2852, "lon": -8.6935},
    "Modivas Centro": {"lines": ["B"], "zone": "VCD", "lat": 41.2937, "lon": -8.6992},
    "Mindelo": {"lines": ["B"], "zone": "VCD", "lat": 41.3151, "lon": -8.7142},
    "Varziela": {"lines": ["B"], "zone": "PVZ", "lat": 41.3342, "lon": -8.7207},
    "Árvore": {"lines": ["B"], "zone": "VCD", "lat": 41.3403, "lon": -8.7255},
    "Azurara": {"lines": ["B"], "zone": "VCD", "lat": 41.3459, "lon": -8.7280},
    "Vila do Conde": {"lines": ["B"], "zone": "VCD", "lat": 41.3591, "lon": -8.7398},
    "Santa Clara": {"lines": ["B"], "zone": "PVZ", "lat": 41.3539, "lon": -8.7356},
    "Portas Fronhas": {"lines": ["B"], "zone": "PVZ", "lat": 41.3693, "lon": -8.7496},
    "Alto de Pega": {"lines": ["B"], "zone": "PVZ", "lat": 41.3644, "lon": -8.7449},
    "São Brás": {"lines": ["B"], "zone": "PVZ", "lat": 41.3732, "lon": -8.7538},
    "Póvoa de Varzim": {"lines": ["B"], "zone": "PVZ", "lat": 41.3777, "lon": -8.7582},
    # Line E (Airport)
    "Aeroporto": {"lines": ["E"], "zone": "MTS", "lat": 41.2372, "lon": -8.6696},
    "Pedras Rubras": {"lines": ["E"], "zone": "MTS", "lat": 41.2463, "lon": -8.6618},
    "Verdes": {"lines": ["E"], "zone": "MTS", "lat": 41.2382, "lon": -8.6583},
    "Lidador": {"lines": ["E"], "zone": "MTS", "lat": 41.2549, "lon": -8.6680},
    "Botica": {"lines": ["E"], "zone": "MAI", "lat": 41.2375, "lon": -8.6652},
    "Fonte do Cuco": {"lines": ["E"], "zone": "MTS", "lat": 41.1942, "lon": -8.6559},
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
        _build_station_mapping()
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


# Mapping from station name -> GTFS stop_id(s)
_station_to_gtfs: dict[str, list[str]] = {}


def _build_station_mapping() -> None:
    """Build mapping from station names to GTFS stop IDs."""
    global _station_to_gtfs
    _station_to_gtfs = {}

    if not _gtfs_stops:
        return

    for station_name, station_data in STATIONS.items():
        matched_ids = []
        station_lat = station_data.get("lat", 0)
        station_lon = station_data.get("lon", 0)

        for stop_id, stop_data in _gtfs_stops.items():
            # Match by proximity (within 200m)
            if station_lat and station_lon:
                dist = _haversine(station_lat, station_lon,
                                  stop_data.get("lat", 0), stop_data.get("lon", 0))
                if dist < 0.2:  # 200 meters
                    matched_ids.append(stop_id)

        if matched_ids:
            _station_to_gtfs[station_name] = matched_ids

    logger.info("Station mapping built: %d/%d stations mapped",
                len(_station_to_gtfs), len(STATIONS))


def search_stations(query: str) -> list[dict]:
    """Search for metro stations by name with smart matching.

    Handles accents (joao → João), abbreviations (D. → Dom),
    and roman numerals (2 → II).
    """
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

    return results


def get_station_lines(station_name: str) -> list[dict]:
    """Get lines that serve a specific station."""
    data = STATIONS.get(station_name)
    if not data:
        # Try smart fuzzy match
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(station_name, list(STATIONS.keys()), min_score=40, max_results=1)
        if matches:
            station_name = matches[0][0]
            data = STATIONS[station_name]
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
    station_data = STATIONS.get(station_name)
    if not station_data:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(station_name, list(STATIONS.keys()), min_score=40, max_results=1)
        if matches:
            station_name = matches[0][0]
            station_data = STATIONS[station_name]
    if not station_data:
        return []

    now = datetime.now()
    current_time = now.time()

    # Check if metro is operating
    if not _is_operating(current_time):
        return [{
            "direction": "Serviço encerrado",
            "time": f"Funcionamento: {OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
            "line": "",
        }]

    # Try GTFS-based schedules first
    if _gtfs_loaded and station_name in _station_to_gtfs:
        gtfs_deps = _get_gtfs_departures(station_name, line_code, count, now)
        if gtfs_deps:
            return gtfs_deps

    # Fallback to frequency estimation
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
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(station_name, list(STATIONS.keys()), min_score=40, max_results=1)
        if matches:
            data = STATIONS[matches[0][0]]
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


def _get_gtfs_departures(station_name: str, line_code: str | None,
                          count: int, now: datetime) -> list[dict]:
    """Get next departures from GTFS stop_times data."""
    stop_ids = _station_to_gtfs.get(station_name, [])
    if not stop_ids:
        return []

    current_time_str = now.strftime("%H:%M:%S")

    # Collect all upcoming departures from all stop_ids for this station
    upcoming = []
    for stop_id in stop_ids:
        times = _gtfs_stop_times.get(stop_id, [])
        for dep_time in times:
            if dep_time >= current_time_str:
                upcoming.append(dep_time)
                if len(upcoming) >= count * 3:  # Get extra for filtering
                    break

    upcoming.sort()

    # Get station's line info
    station_data = STATIONS.get(station_name, {})
    station_lines = station_data.get("lines", [])
    lines_to_show = [line_code] if line_code else station_lines

    departures = []
    for dep_time in upcoming[:count * 2]:
        # Parse time
        try:
            parts = dep_time.split(":")
            hours = int(parts[0]) % 24
            minutes = int(parts[1])
            dep_dt = now.replace(hour=hours, minute=minutes, second=0)

            minutes_until = (dep_dt - now).total_seconds() / 60
            if minutes_until < 0:
                continue

            # Determine time display
            if minutes_until < 1:
                time_str = "< 1 min"
            elif minutes_until < 60:
                time_str = f"{int(minutes_until)} min"
            else:
                time_str = dep_dt.strftime("%H:%M")

            # For each line at this station
            for lc in lines_to_show:
                if lc not in METRO_LINES:
                    continue
                line_data = METRO_LINES[lc]
                # Show terminus as direction
                terminals = line_data.get("route", "").split(" ↔ ")
                direction = terminals[-1] if terminals else ""

                departures.append({
                    "line": f"{line_data['emoji']} {line_data['name']}",
                    "line_code": lc,
                    "direction": direction,
                    "time": time_str,
                    "estimated": False,  # Real GTFS data
                })
        except (ValueError, IndexError):
            continue

    # Deduplicate and limit
    seen = set()
    unique = []
    for dep in departures:
        key = f"{dep['line_code']}:{dep['time']}"
        if key not in seen:
            seen.add(key)
            unique.append(dep)

    return unique[:count]


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
