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

# Complete list of Metro do Porto stations with line associations
# Source: public information from metrodoporto.pt
STATIONS: dict[str, dict] = {
    "Senhor de Matosinhos": {"lines": ["A"], "zone": "MTS"},
    "Mercado": {"lines": ["A"], "zone": "MTS"},
    "Brito Capelo": {"lines": ["A"], "zone": "MTS"},
    "Matosinhos Sul": {"lines": ["A"], "zone": "MTS"},
    "Câmara de Matosinhos": {"lines": ["A"], "zone": "MTS"},
    "Parque de Real": {"lines": ["A"], "zone": "MTS"},
    "Pedro Hispano": {"lines": ["A"], "zone": "MTS"},
    "Estádio do Mar": {"lines": ["A"], "zone": "MTS"},
    "Mercado de Matosinhos": {"lines": ["A"], "zone": "MTS"},  # alt name
    "Senhora da Hora": {"lines": ["A", "B", "C", "E", "F"], "zone": "MTS"},
    "Sete Bicas": {"lines": ["A", "B", "C", "E"], "zone": "MTS"},
    "Viso": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Ramalde": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Francos": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Casa da Música": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT"},
    "Carolina Michaelis": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Lapa": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Trindade": {"lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT"},
    "Bolhão": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Campo 24 de Agosto": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Heroísmo": {"lines": ["A", "B", "C", "E"], "zone": "PRT"},
    "Campanhã": {"lines": ["A", "B", "C", "E", "F"], "zone": "PRT"},
    "Estádio do Dragão": {"lines": ["A", "B", "E"], "zone": "PRT"},
    "Nasoni": {"lines": ["C", "F"], "zone": "PRT"},
    "Nau Vitória": {"lines": ["C", "F"], "zone": "PRT"},
    "Levada": {"lines": ["C", "F"], "zone": "GDM"},
    "Rio Tinto": {"lines": ["C", "F"], "zone": "GDM"},
    "Campainha": {"lines": ["C"], "zone": "GDM"},
    "Baguim": {"lines": ["C"], "zone": "GDM"},  # alt
    "Fânzeres": {"lines": ["F"], "zone": "GDM"},
    "São Roque": {"lines": ["F"], "zone": "GDM"},  # alt
    "Contumil": {"lines": ["F"], "zone": "GDM"},  # alt
    "Custió": {"lines": ["C"], "zone": "VLG"},
    "Araújo": {"lines": ["C"], "zone": "VLG"},
    "Cândido dos Reis": {"lines": ["C"], "zone": "VLG"},
    "Fórum da Maia": {"lines": ["C"], "zone": "MAI"},
    "Parque da Maia": {"lines": ["C"], "zone": "MAI"},
    "Mandim": {"lines": ["C"], "zone": "MAI"},
    "Zona Industrial": {"lines": ["C"], "zone": "MAI"},
    "ISMAI": {"lines": ["C"], "zone": "MAI"},
    # Line D
    "Hospital de São João": {"lines": ["D"], "zone": "PRT"},
    "IPO": {"lines": ["D"], "zone": "PRT"},
    "Polo Universitário": {"lines": ["D"], "zone": "PRT"},
    "Salgueiros": {"lines": ["D"], "zone": "PRT"},
    "Combatentes": {"lines": ["D"], "zone": "PRT"},
    "Marquês": {"lines": ["D"], "zone": "PRT"},
    "Faria Guimarães": {"lines": ["D"], "zone": "PRT"},
    "Aliados": {"lines": ["D"], "zone": "PRT"},
    "São Bento": {"lines": ["D"], "zone": "PRT"},
    "Jardim do Morro": {"lines": ["D"], "zone": "VNG"},
    "General Torres": {"lines": ["D"], "zone": "VNG"},
    "Santo Ovídio": {"lines": ["D"], "zone": "VNG"},
    "Manuel Leão": {"lines": ["D"], "zone": "VNG"},
    "João de Deus": {"lines": ["D"], "zone": "VNG"},
    "D. João II": {"lines": ["D"], "zone": "VNG"},
    "Câmara de Gaia": {"lines": ["D"], "zone": "VNG"},
    "Vila d'Este": {"lines": ["D"], "zone": "VNG"},  # extension
    # Line B
    "Custóias": {"lines": ["B"], "zone": "MTS"},
    "Zona Industrial B": {"lines": ["B"], "zone": "MAI"},
    "Mandim B": {"lines": ["B"], "zone": "MAI"},  # different from line C
    "Crestins": {"lines": ["B"], "zone": "MTS"},
    "Esposade": {"lines": ["B"], "zone": "PVZ"},  # alt
    "Varziela": {"lines": ["B"], "zone": "PVZ"},
    "Árvore": {"lines": ["B"], "zone": "VCD"},
    "Azurara": {"lines": ["B"], "zone": "VCD"},
    "Vila do Conde": {"lines": ["B"], "zone": "VCD"},
    "Santa Clara": {"lines": ["B"], "zone": "PVZ"},
    "Portas Fronhas": {"lines": ["B"], "zone": "PVZ"},  # alt
    "Alto de Pega": {"lines": ["B"], "zone": "PVZ"},
    "Póvoa de Varzim": {"lines": ["B"], "zone": "PVZ"},
    # Line E (Airport)
    "Aeroporto": {"lines": ["E"], "zone": "MTS"},
    "Verdes": {"lines": ["E"], "zone": "MTS"},
    "Lidador": {"lines": ["E"], "zone": "MTS"},  # alt
    "Botica": {"lines": ["E"], "zone": "MAI"},
    "Fonte do Cuco": {"lines": ["E"], "zone": "MTS"},
    "Custió E": {"lines": ["E"], "zone": "MTS"},  # alt name
    "Requezende": {"lines": ["E"], "zone": "MTS"},  # alt
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
