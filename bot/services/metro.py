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

from bot.config import GTFS_DIR, GTFS_METRO_URL, GTFS_METRO_URLS, METRO_LINES
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
# trip_id -> {route_id, service_id, headsign, direction_id}
_gtfs_trips: dict[str, dict] = {}
# service_id -> {monday..sunday: bool}
_gtfs_calendar: dict[str, dict] = {}
# stop_id -> list of {trip_id, departure_time}
_gtfs_stop_times: dict[str, list[dict]] = {}


async def download_gtfs() -> bool:
    """Download and extract GTFS data from Porto open data portal.

    Tries multiple URLs in order, falling back to older files if the newest
    is empty or unavailable (the portal sometimes has 0-byte uploads).
    """
    global _gtfs_loaded
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = GTFS_DIR / "metro_porto.zip"

    urls = GTFS_METRO_URLS if GTFS_METRO_URLS else [GTFS_METRO_URL]

    for url in urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url,
                                       timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("GTFS download HTTP %d from %s", resp.status, url)
                        continue
                    content = await resp.read()
                    if len(content) < 1000:
                        logger.warning("GTFS file too small (%d bytes), skipping: %s",
                                       len(content), url)
                        continue

            async with aiofiles.open(zip_path, "wb") as f:
                await f.write(content)

            _extract_gtfs(zip_path)
            _build_station_mapping()
            _gtfs_loaded = True
            logger.info("GTFS data loaded successfully from %s "
                         "(%d stops, %d trips, %d services)",
                         url, len(_gtfs_stops), len(_gtfs_trips), len(_gtfs_calendar))
            return True
        except Exception:
            logger.exception("Error downloading GTFS from %s", url)
            continue

    logger.error("All GTFS download URLs failed")
    return False


def _extract_gtfs(zip_path: Path) -> None:
    """Extract and parse relevant GTFS files including trips and calendar."""
    global _gtfs_stops, _gtfs_stop_times, _gtfs_trips, _gtfs_calendar

    _gtfs_stops = {}
    _gtfs_trips = {}
    _gtfs_calendar = {}
    _gtfs_stop_times = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find files — they may be in a subdirectory
        names = zf.namelist()
        def _find(fname: str) -> str | None:
            for n in names:
                if n.endswith(fname):
                    return n
            return None

        # Parse calendar.txt — which services run on which days
        cal_file = _find("calendar.txt")
        if cal_file:
            with zf.open(cal_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    sid = row.get("service_id", "")
                    if sid:
                        _gtfs_calendar[sid] = {
                            "monday": row.get("monday") == "1",
                            "tuesday": row.get("tuesday") == "1",
                            "wednesday": row.get("wednesday") == "1",
                            "thursday": row.get("thursday") == "1",
                            "friday": row.get("friday") == "1",
                            "saturday": row.get("saturday") == "1",
                            "sunday": row.get("sunday") == "1",
                        }

        # Parse trips.txt — route, service, headsign (direction) per trip
        trips_file = _find("trips.txt")
        if trips_file:
            with zf.open(trips_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    tid = row.get("trip_id", "")
                    if tid:
                        _gtfs_trips[tid] = {
                            "route_id": row.get("route_id", ""),
                            "service_id": row.get("service_id", ""),
                            "headsign": row.get("trip_headsign", ""),
                            "direction_id": row.get("direction_id", "0"),
                        }

        # Parse stops.txt
        stops_file = _find("stops.txt")
        if stops_file:
            with zf.open(stops_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    stop_id = row.get("stop_id", "")
                    _gtfs_stops[stop_id] = {
                        "name": row.get("stop_name", ""),
                        "lat": float(row.get("stop_lat", 0)),
                        "lon": float(row.get("stop_lon", 0)),
                    }

        # Parse stop_times.txt — store trip_id with each departure
        st_file = _find("stop_times.txt")
        if st_file:
            with zf.open(st_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    stop_id = row.get("stop_id", "")
                    dep_time = row.get("departure_time", "")
                    trip_id = row.get("trip_id", "")
                    if stop_id and dep_time and trip_id:
                        if stop_id not in _gtfs_stop_times:
                            _gtfs_stop_times[stop_id] = []
                        _gtfs_stop_times[stop_id].append({
                            "trip_id": trip_id,
                            "time": dep_time,
                        })

        # Sort by departure time
        for stop_id in _gtfs_stop_times:
            _gtfs_stop_times[stop_id].sort(key=lambda x: x["time"])


# Mapping from station name -> GTFS stop_id(s)
_station_to_gtfs: dict[str, list[str]] = {}

# Day-of-week names matching calendar.txt columns
_DOW_NAMES = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]


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
    """Get next departures from GTFS data with day filtering and directions."""
    stop_ids = _station_to_gtfs.get(station_name, [])
    if not stop_ids:
        return []

    current_time_str = now.strftime("%H:%M:%S")
    day_name = _DOW_NAMES[now.weekday()]

    # Collect upcoming departures with trip info
    upcoming = []
    for stop_id in stop_ids:
        entries = _gtfs_stop_times.get(stop_id, [])
        for entry in entries:
            dep_time = entry["time"]
            if dep_time < current_time_str:
                continue

            trip_id = entry["trip_id"]
            trip = _gtfs_trips.get(trip_id)
            if not trip:
                continue

            # Filter by day of week using calendar
            service_id = trip["service_id"]
            cal = _gtfs_calendar.get(service_id)
            if cal and not cal.get(day_name, False):
                continue

            # Filter by line if requested
            route_id = trip["route_id"]
            if line_code and route_id.upper() != line_code.upper():
                # Also match Bexp -> B
                if not (line_code.upper() == "B" and route_id.upper() == "BEXP"):
                    continue

            upcoming.append({
                "time": dep_time,
                "route_id": route_id,
                "headsign": trip["headsign"],
                "direction_id": trip["direction_id"],
            })

            if len(upcoming) >= count * 4:
                break

    upcoming.sort(key=lambda x: x["time"])

    departures = []
    for entry in upcoming:
        try:
            parts = entry["time"].split(":")
            hours = int(parts[0]) % 24
            minutes = int(parts[1])
            dep_dt = now.replace(hour=hours, minute=minutes, second=0)

            minutes_until = (dep_dt - now).total_seconds() / 60
            if minutes_until < 0:
                continue

            if minutes_until < 1:
                time_str = "< 1 min"
            elif minutes_until < 60:
                time_str = f"{int(minutes_until)} min"
            else:
                time_str = dep_dt.strftime("%H:%M")

            # Map route_id to line code (Bexp -> B)
            route_id = entry["route_id"].upper()
            lc = route_id if route_id in METRO_LINES else route_id.rstrip("EXP")
            if lc not in METRO_LINES:
                lc = route_id[0] if route_id else "?"
            line_data = METRO_LINES.get(lc, {})

            departures.append({
                "line": f"{line_data.get('emoji', '🚇')} {line_data.get('name', f'Linha {lc}')}",
                "line_code": lc,
                "direction": entry["headsign"],
                "time": time_str,
                "minutes": int(minutes_until),
                "estimated": False,
            })
        except (ValueError, IndexError):
            continue

    # Deduplicate: same line + direction + time
    seen = set()
    unique = []
    for dep in departures:
        key = f"{dep['line_code']}:{dep['direction']}:{dep['time']}"
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
