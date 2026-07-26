"""Service for Metro do Porto data.

Data sources, in order of preference:

1. **GTFS feed** from the Porto open data portal (resolved dynamically via the
   CKAN API — see ``bot.config.resolve_latest_gtfs_url``).  When loaded, the
   feed is the source of truth for *which lines serve which station*, the
   *station order along each line*, and *typical headways*.
2. **Offline fallback tables** below (``STATIONS``, ``LINE_STATION_ORDER``,
   ``FREQUENCIES``).  These are a snapshot derived from the 07-04-2026 GTFS
   feed, so they agree with the live feed until the network changes.
3. **Frequency estimates** for next departures when no timetable is available.
   These are always flagged ``estimated: True`` so the UI can label them.

Nothing here is hand-invented: every station, line association and coordinate
was derived from ``routes.txt``/``trips.txt``/``stop_times.txt``/``stops.txt``
of the Metro do Porto GTFS feed.
"""

import csv
import io
import logging
import statistics
import zipfile
from datetime import datetime, time, timedelta
from pathlib import Path

import aiohttp
import aiofiles

from bot.config import (
    CKAN_METRO_DATASET,
    GTFS_DIR,
    GTFS_METRO_URLS,
    GTFS_MIN_BYTES,
    METRO_LINES,
    resolve_latest_gtfs_url,
)

logger = logging.getLogger(__name__)

# GTFS stop names differ slightly from the names this bot shows users (and that
# users search for). Map feed name -> bot name so GTFS-derived data can be
# merged into STATIONS without renaming anything users see.
_GTFS_NAME_ALIASES = {
    "24 de Agosto": "Campo 24 de Agosto",
    "NorteShopping I Sete Bicas": "Sete Bicas",
    "Câmara Gaia": "Câmara de Gaia",
    "Câmara Matosinhos": "Câmara de Matosinhos",
    "Fórum Maia": "Fórum da Maia",
    "Parque Maia": "Parque da Maia",
    "Pólo Universitário": "Polo Universitário",
    "Hospital São João": "Hospital de São João",
    "Zona Indústrial": "Zona Industrial",
}

# GTFS route_id -> user-facing line code. "Bexp" is the Line B express service;
# it is the same red line for the user, not a seventh line.
_GTFS_ROUTE_ALIASES = {"BEXP": "B"}


def _canonical_station_name(gtfs_name: str) -> str:
    return _GTFS_NAME_ALIASES.get(gtfs_name, gtfs_name)


def _canonical_line_code(route_id: str) -> str:
    return _GTFS_ROUTE_ALIASES.get(route_id.upper(), route_id.upper())


# ---------------------------------------------------------------------------
# Offline fallback network data
# ---------------------------------------------------------------------------
# Derived from the Metro do Porto GTFS feed dated 07-04-2026 (routes.txt +
# trips.txt + stop_times.txt + stops.txt). Coordinates are the feed's surveyed
# stop_lat/stop_lon. "lines" folds route "Bexp" into "B".
STATIONS: dict[str, dict] = {
    # --- order source: line A ---
    'Estádio do Dragão': {"lines": ['A', 'B', 'E', 'F'], "zone": 'PRT', "lat": 41.160720, "lon": -8.582416},
    'Campanhã': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.150540, "lon": -8.586245},
    'Heroísmo': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.146700, "lon": -8.592978},
    'Campo 24 de Agosto': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.148800, "lon": -8.598349},
    'Bolhão': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.149780, "lon": -8.605901},
    'Trindade': {"lines": ['A', 'B', 'C', 'D', 'E', 'F'], "zone": 'PRT', "lat": 41.152280, "lon": -8.609299},
    'Lapa': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.157110, "lon": -8.616723},
    'Carolina Michaelis': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.158580, "lon": -8.622246},
    'Casa da Música': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.160580, "lon": -8.628282},
    'Francos': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.165550, "lon": -8.636347},
    'Ramalde': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.172960, "lon": -8.641766},
    'Viso': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'PRT', "lat": 41.177250, "lon": -8.646498},
    'Sete Bicas': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'MTS', "lat": 41.182420, "lon": -8.652149},
    'Senhora da Hora': {"lines": ['A', 'B', 'C', 'E', 'F'], "zone": 'MTS', "lat": 41.188100, "lon": -8.654466},
    'Vasco da Gama': {"lines": ['A'], "zone": 'MTS', "lat": 41.190240, "lon": -8.661037},
    'Estádio do Mar': {"lines": ['A'], "zone": 'MTS', "lat": 41.185770, "lon": -8.661189},
    'Pedro Hispano': {"lines": ['A'], "zone": 'MTS', "lat": 41.180380, "lon": -8.666232},
    'Parque de Real': {"lines": ['A'], "zone": 'MTS', "lat": 41.179110, "lon": -8.673546},
    'Câmara de Matosinhos': {"lines": ['A'], "zone": 'MTS', "lat": 41.180700, "lon": -8.681227},
    'Matosinhos Sul': {"lines": ['A'], "zone": 'MTS', "lat": 41.180170, "lon": -8.688553},
    'Brito Capelo': {"lines": ['A'], "zone": 'MTS', "lat": 41.183910, "lon": -8.691469},
    'Mercado': {"lines": ['A'], "zone": 'MTS', "lat": 41.187480, "lon": -8.693391},
    'Senhor de Matosinhos': {"lines": ['A'], "zone": 'MTS', "lat": 41.188210, "lon": -8.685123},
    # --- order source: line B ---
    'Fonte do Cuco': {"lines": ['B', 'C', 'E'], "zone": 'MTS', "lat": 41.194160, "lon": -8.655771},
    'Custóias': {"lines": ['B', 'E'], "zone": 'MTS', "lat": 41.200290, "lon": -8.655559},
    'Esposade': {"lines": ['B', 'E'], "zone": 'PVZ', "lat": 41.216070, "lon": -8.654541},
    'Crestins': {"lines": ['B', 'E'], "zone": 'MTS', "lat": 41.233010, "lon": -8.656593},
    'Verdes': {"lines": ['B', 'E'], "zone": 'MTS', "lat": 41.238250, "lon": -8.658212},
    'Pedras Rubras': {"lines": ['B'], "zone": 'MTS', "lat": 41.246230, "lon": -8.661807},
    'Lidador': {"lines": ['B'], "zone": 'MTS', "lat": 41.254950, "lon": -8.668018},
    'Vilar do Pinheiro': {"lines": ['B'], "zone": 'VCD', "lat": 41.270300, "lon": -8.679515},
    'Modivas Sul': {"lines": ['B'], "zone": 'VCD', "lat": 41.285250, "lon": -8.693703},
    'Modivas Centro': {"lines": ['B'], "zone": 'VCD', "lat": 41.293680, "lon": -8.699238},
    'VC Fashion Outlet I Modivas': {"lines": ['B'], "zone": 'VCD', "lat": 41.300490, "lon": -8.704004},
    'Mindelo': {"lines": ['B'], "zone": 'VCD', "lat": 41.315080, "lon": -8.714209},
    'Espaço Natureza': {"lines": ['B'], "zone": 'VCD', "lat": 41.321220, "lon": -8.718681},
    'Varziela': {"lines": ['B'], "zone": 'PVZ', "lat": 41.334220, "lon": -8.720721},
    'Árvore': {"lines": ['B'], "zone": 'VCD', "lat": 41.340400, "lon": -8.725555},
    'Azurara': {"lines": ['B'], "zone": 'VCD', "lat": 41.345970, "lon": -8.728122},
    'Santa Clara': {"lines": ['B'], "zone": 'PVZ', "lat": 41.353980, "lon": -8.735826},
    'Vila do Conde': {"lines": ['B'], "zone": 'VCD', "lat": 41.359100, "lon": -8.739870},
    'Alto de Pega': {"lines": ['B'], "zone": 'PVZ', "lat": 41.364640, "lon": -8.745225},
    'Portas Fronhas': {"lines": ['B'], "zone": 'PVZ', "lat": 41.368950, "lon": -8.749558},
    'São Brás': {"lines": ['B'], "zone": 'PVZ', "lat": 41.373460, "lon": -8.754122},
    'Póvoa de Varzim': {"lines": ['B'], "zone": 'PVZ', "lat": 41.378120, "lon": -8.758081},
    # --- order source: line C ---
    'Cândido dos Reis': {"lines": ['C'], "zone": 'VLG', "lat": 41.200700, "lon": -8.649703},
    'Pias': {"lines": ['C'], "zone": 'MAI', "lat": 41.208230, "lon": -8.647122},
    'Araújo': {"lines": ['C'], "zone": 'VLG', "lat": 41.216910, "lon": -8.640978},
    'Custió': {"lines": ['C'], "zone": 'VLG', "lat": 41.222340, "lon": -8.638996},
    'Parque da Maia': {"lines": ['C'], "zone": 'MAI', "lat": 41.229020, "lon": -8.626897},
    'Fórum da Maia': {"lines": ['C'], "zone": 'MAI', "lat": 41.234630, "lon": -8.623937},
    'Zona Industrial': {"lines": ['C'], "zone": 'MAI', "lat": 41.243970, "lon": -8.628555},
    'Mandim': {"lines": ['C'], "zone": 'MAI', "lat": 41.253580, "lon": -8.628308},
    'Castêlo da Maia': {"lines": ['C'], "zone": 'MAI', "lat": 41.262750, "lon": -8.616986},
    'ISMAI': {"lines": ['C'], "zone": 'MAI', "lat": 41.268910, "lon": -8.615387},
    # --- order source: line D ---
    "Vila d'Este": {"lines": ['D'], "zone": 'VNG', "lat": 41.098720, "lon": -8.588716},
    'Hospital Santos Silva': {"lines": ['D'], "zone": 'VNG', "lat": 41.105760, "lon": -8.591075},
    'Manuel Leão': {"lines": ['D'], "zone": 'VNG', "lat": 41.110660, "lon": -8.599958},
    'Santo Ovídio': {"lines": ['D'], "zone": 'VNG', "lat": 41.115550, "lon": -8.606555},
    'D. João II': {"lines": ['D'], "zone": 'VNG', "lat": 41.119660, "lon": -8.606230},
    'João de Deus': {"lines": ['D'], "zone": 'VNG', "lat": 41.126060, "lon": -8.605627},
    'Câmara de Gaia': {"lines": ['D'], "zone": 'VNG', "lat": 41.129670, "lon": -8.606116},
    'General Torres': {"lines": ['D'], "zone": 'VNG', "lat": 41.133870, "lon": -8.607489},
    'Jardim do Morro': {"lines": ['D'], "zone": 'VNG', "lat": 41.137640, "lon": -8.608646},
    'São Bento': {"lines": ['D'], "zone": 'PRT', "lat": 41.144940, "lon": -8.610815},
    'Aliados': {"lines": ['D'], "zone": 'PRT', "lat": 41.148580, "lon": -8.610945},
    'Faria Guimarães': {"lines": ['D'], "zone": 'PRT', "lat": 41.157220, "lon": -8.609141},
    'Marquês': {"lines": ['D'], "zone": 'PRT', "lat": 41.161120, "lon": -8.604272},
    'Combatentes': {"lines": ['D'], "zone": 'PRT', "lat": 41.165300, "lon": -8.598464},
    'Salgueiros': {"lines": ['D'], "zone": 'PRT', "lat": 41.169690, "lon": -8.598744},
    'Polo Universitário': {"lines": ['D'], "zone": 'PRT', "lat": 41.174250, "lon": -8.603607},
    'IPO': {"lines": ['D'], "zone": 'PRT', "lat": 41.181250, "lon": -8.604521},
    'Hospital de São João': {"lines": ['D'], "zone": 'PRT', "lat": 41.183260, "lon": -8.602240},
    # --- order source: line E ---
    'Botica': {"lines": ['E'], "zone": 'MAI', "lat": 41.237520, "lon": -8.665208},
    'Aeroporto': {"lines": ['E'], "zone": 'MTS', "lat": 41.237080, "lon": -8.669442},
    # --- order source: line F ---
    'Fânzeres': {"lines": ['F'], "zone": 'GDM', "lat": 41.171300, "lon": -8.542938},
    'Venda Nova': {"lines": ['F'], "zone": 'GDM', "lat": 41.175160, "lon": -8.541962},
    'Carreira': {"lines": ['F'], "zone": 'GDM', "lat": 41.179820, "lon": -8.543604},
    'Baguim': {"lines": ['F'], "zone": 'GDM', "lat": 41.185570, "lon": -8.545892},
    'Campainha': {"lines": ['F'], "zone": 'GDM', "lat": 41.183450, "lon": -8.553955},
    'Rio Tinto': {"lines": ['F'], "zone": 'GDM', "lat": 41.179420, "lon": -8.560264},
    'Levada': {"lines": ['F'], "zone": 'GDM', "lat": 41.175760, "lon": -8.562120},
    'Nau Vitória': {"lines": ['F'], "zone": 'PRT', "lat": 41.174120, "lon": -8.573534},
    'Nasoni': {"lines": ['F'], "zone": 'PRT', "lat": 41.170770, "lon": -8.577317},
    'Contumil': {"lines": ['F'], "zone": 'GDM', "lat": 41.165710, "lon": -8.578639},
}

# Station order along each line, from the GTFS stop_sequence of the longest
# trip on each route (direction_id=1 where that is the canonical "outbound"
# listing). Needed because dict-insertion order puts branch stations in the
# middle of a line and renders the line map nonsensically.
LINE_STATION_ORDER: dict[str, list[str]] = {
'A': [
        'Estádio do Dragão',
        'Campanhã',
        'Heroísmo',
        'Campo 24 de Agosto',
        'Bolhão',
        'Trindade',
        'Lapa',
        'Carolina Michaelis',
        'Casa da Música',
        'Francos',
        'Ramalde',
        'Viso',
        'Sete Bicas',
        'Senhora da Hora',
        'Vasco da Gama',
        'Estádio do Mar',
        'Pedro Hispano',
        'Parque de Real',
        'Câmara de Matosinhos',
        'Matosinhos Sul',
        'Brito Capelo',
        'Mercado',
        'Senhor de Matosinhos',
    ],
    'B': [
        'Estádio do Dragão',
        'Campanhã',
        'Heroísmo',
        'Campo 24 de Agosto',
        'Bolhão',
        'Trindade',
        'Lapa',
        'Carolina Michaelis',
        'Casa da Música',
        'Francos',
        'Ramalde',
        'Viso',
        'Sete Bicas',
        'Senhora da Hora',
        'Fonte do Cuco',
        'Custóias',
        'Esposade',
        'Crestins',
        'Verdes',
        'Pedras Rubras',
        'Lidador',
        'Vilar do Pinheiro',
        'Modivas Sul',
        'Modivas Centro',
        'VC Fashion Outlet I Modivas',
        'Mindelo',
        'Espaço Natureza',
        'Varziela',
        'Árvore',
        'Azurara',
        'Santa Clara',
        'Vila do Conde',
        'Alto de Pega',
        'Portas Fronhas',
        'São Brás',
        'Póvoa de Varzim',
    ],
    'C': [
        'Campanhã',
        'Heroísmo',
        'Campo 24 de Agosto',
        'Bolhão',
        'Trindade',
        'Lapa',
        'Carolina Michaelis',
        'Casa da Música',
        'Francos',
        'Ramalde',
        'Viso',
        'Sete Bicas',
        'Senhora da Hora',
        'Fonte do Cuco',
        'Cândido dos Reis',
        'Pias',
        'Araújo',
        'Custió',
        'Parque da Maia',
        'Fórum da Maia',
        'Zona Industrial',
        'Mandim',
        'Castêlo da Maia',
        'ISMAI',
    ],
    'D': [
        "Vila d'Este",
        'Hospital Santos Silva',
        'Manuel Leão',
        'Santo Ovídio',
        'D. João II',
        'João de Deus',
        'Câmara de Gaia',
        'General Torres',
        'Jardim do Morro',
        'São Bento',
        'Aliados',
        'Trindade',
        'Faria Guimarães',
        'Marquês',
        'Combatentes',
        'Salgueiros',
        'Polo Universitário',
        'IPO',
        'Hospital de São João',
    ],
    'E': [
        'Estádio do Dragão',
        'Campanhã',
        'Heroísmo',
        'Campo 24 de Agosto',
        'Bolhão',
        'Trindade',
        'Lapa',
        'Carolina Michaelis',
        'Casa da Música',
        'Francos',
        'Ramalde',
        'Viso',
        'Sete Bicas',
        'Senhora da Hora',
        'Fonte do Cuco',
        'Custóias',
        'Esposade',
        'Crestins',
        'Verdes',
        'Botica',
        'Aeroporto',
    ],
    'F': [
        'Fânzeres',
        'Venda Nova',
        'Carreira',
        'Baguim',
        'Campainha',
        'Rio Tinto',
        'Levada',
        'Nau Vitória',
        'Nasoni',
        'Contumil',
        'Estádio do Dragão',
        'Campanhã',
        'Heroísmo',
        'Campo 24 de Agosto',
        'Bolhão',
        'Trindade',
        'Lapa',
        'Carolina Michaelis',
        'Casa da Música',
        'Francos',
        'Ramalde',
        'Viso',
        'Sete Bicas',
        'Senhora da Hora',
    ],
}

# Typical headways in minutes. APPROXIMATE — these are averages, not a
# timetable. When a GTFS feed is loaded, ``_compute_gtfs_headways()`` replaces
# them with values measured from the feed (see ``get_frequency_info``, which
# reports which source was used).
FREQUENCIES = {
    "peak": {"A": 6, "B": 12, "C": 12, "D": 6, "E": 12, "F": 12},
    "off_peak": {"A": 10, "B": 20, "C": 20, "D": 10, "E": 15, "F": 15},
    "weekend": {"A": 12, "B": 20, "C": 20, "D": 12, "E": 20, "F": 20},
}

# Operating hours
OPERATING_HOURS = {"start": time(6, 0), "end": time(1, 0)}

# Only trust GTFS departures this far ahead; a feed whose calendar has expired
# would otherwise present next-month timetables as "the next train".
GTFS_HORIZON_MINUTES = 180

# GTFS data storage
_gtfs_loaded = False
_gtfs_stops: dict[str, dict] = {}
# trip_id -> {route_id, service_id, headsign, direction_id}
_gtfs_trips: dict[str, dict] = {}
# service_id -> {monday..sunday: bool}
_gtfs_calendar: dict[str, dict] = {}
# stop_id -> list of {trip_id, time, secs}
_gtfs_stop_times: dict[str, list[dict]] = {}
# trip_id -> ordered list of stop_ids (from stop_sequence)
_gtfs_trip_stops: dict[str, list[str]] = {}
# Network facts derived from the feed; empty until a feed is parsed.
_derived_station_lines: dict[str, list[str]] = {}
_derived_line_order: dict[str, list[str]] = {}
_derived_headways: dict[str, dict[str, int]] = {}


async def download_gtfs() -> bool:
    """Download and extract GTFS data from the Porto open data portal.

    Resolves the current resource list from the CKAN API first, then falls back
    to the pinned URLs in ``bot.config``. Skips 0-byte/short files, which the
    portal publishes regularly.
    """
    global _gtfs_loaded
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = GTFS_DIR / "metro_porto.zip"

    urls = list(await resolve_latest_gtfs_url(CKAN_METRO_DATASET))
    for fallback in GTFS_METRO_URLS:
        if fallback not in urls:
            urls.append(fallback)
    if not urls:
        logger.error("No metro GTFS URL available (CKAN and fallbacks empty)")
        return False

    for url in urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url,
                                       timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("GTFS download HTTP %d from %s", resp.status, url)
                        continue
                    content = await resp.read()
                    if len(content) < GTFS_MIN_BYTES:
                        logger.warning("GTFS file too small (%d bytes), skipping: %s",
                                       len(content), url)
                        continue

            async with aiofiles.open(zip_path, "wb") as f:
                await f.write(content)

            _extract_gtfs(zip_path)
            _derive_network_from_gtfs()
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


def _gtfs_time_to_seconds(value: str) -> int | None:
    """Parse a GTFS ``HH:MM:SS`` time into seconds after the service day start.

    GTFS allows hours >= 24 for trips that run past midnight but still belong to
    the previous service day (``24:30:00`` is 00:30 the following morning).
    Those must NOT be wrapped with ``% 24`` — doing so moves the departure to
    the start of the same day and makes it look like it already happened.
    """
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    if hours < 0 or not (0 <= minutes < 60) or not (0 <= seconds < 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


def _extract_gtfs(zip_path: Path) -> None:
    """Extract and parse relevant GTFS files including trips and calendar."""
    global _gtfs_stops, _gtfs_stop_times, _gtfs_trips, _gtfs_calendar
    global _gtfs_trip_stops

    _gtfs_stops = {}
    _gtfs_trips = {}
    _gtfs_calendar = {}
    _gtfs_stop_times = {}
    _gtfs_trip_stops = {}

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
                    try:
                        lat = float(row.get("stop_lat", 0) or 0)
                        lon = float(row.get("stop_lon", 0) or 0)
                    except ValueError:
                        lat = lon = 0.0
                    _gtfs_stops[stop_id] = {
                        "name": row.get("stop_name", ""),
                        "lat": lat,
                        "lon": lon,
                    }

        # Parse stop_times.txt — keep trip_id and stop_sequence with each row
        st_file = _find("stop_times.txt")
        seq_rows: dict[str, list[tuple[int, str]]] = {}
        if st_file:
            with zf.open(st_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    stop_id = row.get("stop_id", "")
                    dep_time = row.get("departure_time", "")
                    trip_id = row.get("trip_id", "")
                    if not (stop_id and trip_id):
                        continue

                    if dep_time:
                        secs = _gtfs_time_to_seconds(dep_time)
                        if secs is not None:
                            _gtfs_stop_times.setdefault(stop_id, []).append({
                                "trip_id": trip_id,
                                "time": dep_time,
                                "secs": secs,
                            })

                    try:
                        seq = int(row.get("stop_sequence", 0) or 0)
                    except ValueError:
                        seq = 0
                    seq_rows.setdefault(trip_id, []).append((seq, stop_id))

        # Sort departures chronologically within the service day
        for stop_id in _gtfs_stop_times:
            _gtfs_stop_times[stop_id].sort(key=lambda x: x["secs"])

        # Materialise ordered stop lists per trip
        for trip_id, rows in seq_rows.items():
            rows.sort(key=lambda x: x[0])
            _gtfs_trip_stops[trip_id] = [stop_id for _, stop_id in rows]


# Mapping from station name -> GTFS stop_id(s)
_station_to_gtfs: dict[str, list[str]] = {}

# Day-of-week names matching calendar.txt columns
_DOW_NAMES = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]


def _derive_network_from_gtfs() -> None:
    """Derive station->lines, per-line station order and headways from GTFS.

    This makes the feed authoritative and demotes the hardcoded tables to a
    pure offline fallback. Only stations already known to the bot are updated —
    a brand new station in the feed is logged so it can be added deliberately
    (its name also has to be reachable by search and zone lookup).
    """
    global _derived_station_lines, _derived_line_order

    _derived_station_lines = {}
    _derived_line_order = {}

    if not _gtfs_stops or not _gtfs_trips:
        return

    # --- station -> lines -------------------------------------------------
    station_lines: dict[str, set[str]] = {}
    for stop_id, entries in _gtfs_stop_times.items():
        stop = _gtfs_stops.get(stop_id)
        if not stop:
            continue
        name = _canonical_station_name(stop.get("name", ""))
        for entry in entries:
            trip = _gtfs_trips.get(entry["trip_id"])
            if not trip:
                continue
            code = _canonical_line_code(trip["route_id"])
            if code in METRO_LINES:
                station_lines.setdefault(name, set()).add(code)

    unknown = sorted(n for n in station_lines if n not in STATIONS)
    if unknown:
        logger.warning("GTFS feed has %d station(s) unknown to the bot: %s",
                       len(unknown), ", ".join(unknown))

    for name, codes in station_lines.items():
        if name in STATIONS:
            _derived_station_lines[name] = sorted(codes)
            STATIONS[name]["lines"] = sorted(codes)

    # --- per-line station order ------------------------------------------
    # Use the longest trip per line as the canonical stop sequence; branching
    # lines (B/Bexp) then get the full branch rather than the express subset.
    longest: dict[str, list[str]] = {}
    for trip_id, stop_ids in _gtfs_trip_stops.items():
        trip = _gtfs_trips.get(trip_id)
        if not trip:
            continue
        code = _canonical_line_code(trip["route_id"])
        if code not in METRO_LINES:
            continue
        if code not in longest or len(stop_ids) > len(longest[code]):
            longest[code] = stop_ids

    for code, stop_ids in longest.items():
        ordered = []
        for stop_id in stop_ids:
            stop = _gtfs_stops.get(stop_id)
            if not stop:
                continue
            name = _canonical_station_name(stop.get("name", ""))
            if name in STATIONS and name not in ordered:
                ordered.append(name)
        if ordered:
            _derived_line_order[code] = ordered

    _compute_gtfs_headways()

    logger.info("Derived network from GTFS: %d stations, %d line orders, "
                "%d headway bands",
                len(_derived_station_lines), len(_derived_line_order),
                len(_derived_headways))


def _band_for(weekday: int, hour: int) -> str:
    if weekday >= 5:
        return "weekend"
    if 7 <= hour <= 9 or 17 <= hour <= 19:
        return "peak"
    return "off_peak"


def _compute_gtfs_headways() -> None:
    """Measure typical headways per line and time band from the feed.

    For each line, take the busiest stop and the median gap between successive
    departures in one direction within each band. Median (not mean) so a single
    long overnight gap does not distort the figure.
    """
    global _derived_headways
    _derived_headways = {}

    if not _gtfs_stop_times:
        return

    # departures per (line, band) at the line's busiest stop, one direction
    busiest: dict[str, tuple[str, int]] = {}
    for stop_id, entries in _gtfs_stop_times.items():
        per_line: dict[str, int] = {}
        for entry in entries:
            trip = _gtfs_trips.get(entry["trip_id"])
            if not trip or trip.get("direction_id") != "0":
                continue
            code = _canonical_line_code(trip["route_id"])
            if code in METRO_LINES:
                per_line[code] = per_line.get(code, 0) + 1
        for code, n in per_line.items():
            if code not in busiest or n > busiest[code][1]:
                busiest[code] = (stop_id, n)

    for code, (stop_id, _n) in busiest.items():
        by_band: dict[str, list[int]] = {}
        for entry in _gtfs_stop_times.get(stop_id, []):
            trip = _gtfs_trips.get(entry["trip_id"])
            if not trip or trip.get("direction_id") != "0":
                continue
            if _canonical_line_code(trip["route_id"]) != code:
                continue
            cal = _gtfs_calendar.get(trip["service_id"])
            if not cal:
                continue
            # Represent the service pattern by one weekday it runs on.
            weekday = next((i for i, d in enumerate(_DOW_NAMES) if cal.get(d)), None)
            if weekday is None:
                continue
            hour = (entry["secs"] // 3600) % 24
            by_band.setdefault(_band_for(weekday, hour), []).append(entry["secs"])

        for band, secs in by_band.items():
            secs = sorted(set(secs))
            if len(secs) < 3:
                continue
            gaps = [(b - a) / 60 for a, b in zip(secs, secs[1:]) if b > a]
            # Ignore gaps over an hour (service breaks) so the median reflects
            # the running headway rather than the overnight gap.
            gaps = [g for g in gaps if g <= 60]
            if not gaps:
                continue
            _derived_headways.setdefault(band, {})[code] = max(
                1, int(round(statistics.median(gaps))))


def _active_frequencies(band: str) -> dict[str, int]:
    """Headways for a band, preferring GTFS-measured over hardcoded values."""
    base = dict(FREQUENCIES.get(band, {}))
    base.update(_derived_headways.get(band, {}))
    return base


def _build_station_mapping() -> None:
    """Build mapping from station names to GTFS stop IDs."""
    global _station_to_gtfs
    _station_to_gtfs = {}

    if not _gtfs_stops:
        return

    # Prefer an exact (aliased) name match — it is unambiguous. Fall back to
    # proximity for stations whose feed name we do not recognise.
    by_name: dict[str, list[str]] = {}
    for stop_id, stop_data in _gtfs_stops.items():
        name = _canonical_station_name(stop_data.get("name", ""))
        by_name.setdefault(name, []).append(stop_id)

    for station_name, station_data in STATIONS.items():
        matched_ids = list(by_name.get(station_name, []))

        if not matched_ids:
            station_lat = station_data.get("lat", 0)
            station_lon = station_data.get("lon", 0)
            if station_lat and station_lon:
                for stop_id, stop_data in _gtfs_stops.items():
                    dist = _haversine(station_lat, station_lon,
                                      stop_data.get("lat", 0),
                                      stop_data.get("lon", 0))
                    if dist < 0.2:  # 200 meters
                        matched_ids.append(stop_id)

        if matched_ids:
            _station_to_gtfs[station_name] = matched_ids

    logger.info("Station mapping built: %d/%d stations mapped",
                len(_station_to_gtfs), len(STATIONS))


# Minimum fuzzy-match score for station search. The scorer produces scores in
# disjoint bands (0, <=5 for "under half the tokens matched", 45-60 for "at
# least half", 80+ for substring/exact), so anything at or below 45 is a
# coincidental match like "s bento" -> "Santo Ovídio". Verified against the 70
# search-variation cases in tests/test_comprehensive.py: the lowest score a
# genuinely expected station receives is 52.5, so 50 keeps every real query
# working while dropping the 45-47 junk tier.
SEARCH_MIN_SCORE = 50


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
    matches = fuzzy_search(query, station_names,
                           min_score=SEARCH_MIN_SCORE, max_results=15)

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


async def get_next_departures_async(station_name: str,
                                    line_code: str | None = None,
                                    count: int = 5) -> list[dict]:
    """Get next departures, trying real-time data first.

    Priority: real-time (trip planner) > GTFS schedule > frequency estimate.
    If real-time data only covers one direction, supplement with estimated
    departures for the missing direction(s) so users always see both.
    """
    try:
        from bot.services.metro_realtime import get_realtime_departures
        rt = await get_realtime_departures(station_name, count=count)
        if rt:
            rt = _supplement_missing_directions(station_name, rt, line_code, count)
            return rt
    except Exception:
        logger.debug("Real-time data unavailable, falling back to schedule",
                     exc_info=True)
    return get_next_departures(station_name, line_code, count)


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
    freq_type = _get_frequency_type(now)
    frequencies = _active_frequencies(freq_type)

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
    """Get all stations for a specific metro line, in travel order.

    Order comes from the GTFS stop_sequence when a feed is loaded, otherwise
    from the ``LINE_STATION_ORDER`` snapshot. Falling back to dict-insertion
    order (the old behaviour) put branch stations in the middle of the line and
    made the rendered line map nonsensical.
    """
    code = (line_code or "").upper()

    ordered = _derived_line_order.get(code) or LINE_STATION_ORDER.get(code)
    if ordered:
        # Guard against a feed that references a station we do not know.
        return [name for name in ordered if name in STATIONS]

    return [name for name, data in STATIONS.items() if code in data["lines"]]


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
    """Get frequency information for a specific line.

    ``source`` says whether the numbers were measured from the GTFS feed or are
    the approximate built-in averages, so the UI need not imply precision.
    """
    measured = any(line_code in _derived_headways.get(band, {})
                   for band in ("peak", "off_peak", "weekend"))
    return {
        "peak": f"A cada {_active_frequencies('peak').get(line_code, '?')} min",
        "off_peak": f"A cada {_active_frequencies('off_peak').get(line_code, '?')} min",
        "weekend": f"A cada {_active_frequencies('weekend').get(line_code, '?')} min",
        "hours": f"{OPERATING_HOURS['start'].strftime('%H:%M')} - {OPERATING_HOURS['end'].strftime('%H:%M')}",
        "source": "gtfs" if measured else "approximate",
        "approximate": not measured,
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


def _balance_directions(departures: list[dict], count: int) -> list[dict]:
    """Ensure departures include both directions when available.

    Groups departures by direction and interleaves them so that the final
    list contains a balanced mix rather than all departures from whichever
    direction happens to depart first.
    """
    if len(departures) <= count:
        return departures

    # Group by direction
    by_dir: dict[str, list[dict]] = {}
    for dep in departures:
        d = dep.get("direction", "")
        by_dir.setdefault(d, []).append(dep)

    if len(by_dir) <= 1:
        return departures[:count]

    # Interleave: round-robin across directions, each sorted by time
    dirs = list(by_dir.values())
    result = []
    idx = 0
    while len(result) < count:
        added = False
        for group in dirs:
            if idx < len(group) and len(result) < count:
                result.append(group[idx])
                added = True
        if not added:
            break
        idx += 1

    # Re-sort by departure time so display is chronological
    result.sort(key=lambda x: x.get("minutes", 999))
    return result


def _supplement_missing_directions(station_name: str, rt_deps: list[dict],
                                   line_code: str | None,
                                   count: int) -> list[dict]:
    """Add estimated departures for directions missing from realtime data.

    When the MOTIS API only returns departures in one direction (e.g. only
    "Senhor de Matosinhos" at Vasco da Gama), this adds frequency-based
    estimates for the other direction so users always see both.
    """
    station_data = STATIONS.get(station_name)
    if not station_data:
        return rt_deps

    # Collect all expected directions from line endpoints
    expected_dirs: set[str] = set()
    lines_to_check = [line_code] if line_code else station_data["lines"]
    for lc in lines_to_check:
        line_data = METRO_LINES.get(lc, {})
        route = line_data.get("route", "")
        if " ↔ " in route:
            for endpoint in route.split(" ↔ "):
                expected_dirs.add(endpoint)

    if not expected_dirs:
        return rt_deps

    # Check which directions are present in realtime data
    rt_directions = set(d.get("direction", "") for d in rt_deps)

    # Find missing directions (match by substring to handle headsign variants)
    missing = set()
    for expected in expected_dirs:
        found = False
        for rt_dir in rt_directions:
            if expected.lower() in rt_dir.lower() or rt_dir.lower() in expected.lower():
                found = True
                break
        if not found:
            missing.add(expected)

    if not missing:
        return rt_deps

    # Generate estimated departures for missing directions
    now = datetime.now()
    if not _is_operating(now.time()):
        return rt_deps

    freq_type = _get_frequency_type(now)
    frequencies = _active_frequencies(freq_type)

    supplemental = []
    for lc in lines_to_check:
        line_data = METRO_LINES.get(lc, {})
        route = line_data.get("route", "")
        if " ↔ " not in route:
            continue
        endpoints = route.split(" ↔ ")

        for direction in endpoints:
            if direction not in missing:
                continue

            freq_minutes = frequencies.get(lc, 15)
            minutes_since_hour = now.minute + now.second / 60
            next_in = freq_minutes - (minutes_since_hour % freq_minutes)
            if next_in < 1:
                next_in += freq_minutes

            # Add a few estimated departures for the missing direction
            slots = max(2, count // 2)
            for i in range(slots):
                dep_minutes = int(next_in + i * freq_minutes)
                dep_time = now + timedelta(minutes=dep_minutes)
                supplemental.append({
                    "direction": direction,
                    "time": f"~{dep_time.strftime('%H:%M')}",
                    "line": f"{line_data['emoji']} {line_data['name']}",
                    "line_code": lc,
                    "estimated": True,
                    "minutes": dep_minutes,
                })

    if not supplemental:
        return rt_deps

    combined = rt_deps + supplemental
    return _balance_directions(combined, count)


def _get_gtfs_departures(station_name: str, line_code: str | None,
                         count: int, now: datetime) -> list[dict]:
    """Get next departures from GTFS data with day filtering and directions.

    Handles GTFS service-day offsets: a ``24:30:00`` departure belongs to the
    *previous* service day, so both today's and yesterday's service days are
    considered and each departure time is anchored to its own service day's
    midnight. The old code compared time strings and did ``hour % 24``, which
    mapped a 24:30 departure onto today 00:30 — a negative ``minutes_until``
    that got filtered out, emptying the GTFS path after ~23:00.
    """
    stop_ids = _station_to_gtfs.get(station_name, [])
    if not stop_ids:
        return []

    midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    upcoming = []
    for day_offset in (-1, 0):
        service_midnight = midnight_today + timedelta(days=day_offset)
        day_name = _DOW_NAMES[service_midnight.weekday()]

        for stop_id in stop_ids:
            for entry in _gtfs_stop_times.get(stop_id, []):
                dep_dt = service_midnight + timedelta(seconds=entry["secs"])
                minutes_until = (dep_dt - now).total_seconds() / 60
                if minutes_until < 0 or minutes_until > GTFS_HORIZON_MINUTES:
                    continue

                trip = _gtfs_trips.get(entry["trip_id"])
                if not trip:
                    continue

                # Filter by day of week using the *service day's* weekday
                cal = _gtfs_calendar.get(trip["service_id"])
                if cal and not cal.get(day_name, False):
                    continue

                # Filter by line if requested (Bexp counts as B)
                route_id = trip["route_id"]
                lc = _canonical_line_code(route_id)
                if line_code and lc != line_code.upper():
                    continue

                upcoming.append({
                    "dep_dt": dep_dt,
                    "minutes_until": minutes_until,
                    "line_code": lc,
                    "headsign": trip["headsign"],
                    "direction_id": trip["direction_id"],
                })

    upcoming.sort(key=lambda x: x["minutes_until"])

    departures = []
    for entry in upcoming:
        minutes_until = entry["minutes_until"]
        if minutes_until < 1:
            time_str = "< 1 min"
        elif minutes_until < 60:
            time_str = f"{int(minutes_until)} min"
        else:
            time_str = entry["dep_dt"].strftime("%H:%M")

        lc = entry["line_code"]
        line_data = METRO_LINES.get(lc, {})

        departures.append({
            "line": f"{line_data.get('emoji', '🚇')} {line_data.get('name', f'Linha {lc}')}",
            "line_code": lc,
            "direction": entry["headsign"],
            "time": time_str,
            "minutes": int(minutes_until),
            "estimated": False,
        })

    # Deduplicate: same line + direction + time
    seen = set()
    unique = []
    for dep in departures:
        key = f"{dep['line_code']}:{dep['direction']}:{dep['time']}"
        if key not in seen:
            seen.add(key)
            unique.append(dep)

    return _balance_directions(unique, count)


def _is_operating(current_time: time) -> bool:
    start = OPERATING_HOURS["start"]
    end = OPERATING_HOURS["end"]
    if end < start:  # crosses midnight
        return current_time >= start or current_time <= end
    return start <= current_time <= end


def _get_frequency_type(now: datetime) -> str:
    return _band_for(now.weekday(), now.hour)
