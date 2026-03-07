"""Service for fetching STCP (bus) data from the stcp.pt API."""

import csv
import io
import logging
import math
import zipfile
from datetime import datetime
from pathlib import Path

import aiohttp
import aiofiles

from bot.config import GTFS_DIR, GTFS_STCP_URL
from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=60)

API_BASE = "https://stcp.pt/api"

# Local GTFS stop data for geo-search
_gtfs_bus_stops: list[dict] = []


async def _get(path: str, params: dict | None = None,
               cache_ttl: int | None = None) -> dict | list:
    cache_key = f"stcp:{path}:{params}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{API_BASE}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if cache_ttl is not None:
        _cache.set(cache_key, data, ttl=cache_ttl)
    else:
        _cache.set(cache_key, data)
    return data


async def search_stops(query: str) -> list[dict]:
    """Search for bus stops by name. Returns list of matching stops."""
    try:
        data = await _get("/stops", params={"search": query}, cache_ttl=300)
        results = data.get("results", [])
        return [
            {
                "stop_id": s["stop_id"],
                "name": s["stop_name"],
                "code": s.get("stop_code", s["stop_id"]),
                "zone": s.get("zone_id", ""),
            }
            for s in results[:20]
        ]
    except Exception:
        logger.exception("Error searching stops")
        return []


async def get_stop_real_time(stop_id: str) -> dict:
    """Get real-time arrivals for a specific stop."""
    try:
        data = await _get(f"/stops/{stop_id}/realtime", cache_ttl=30)
        arrivals = []
        for a in data.get("arrivals", []):
            status_emoji = _status_emoji(a.get("status", ""))
            arrival_min = a.get("arrival_minutes")
            if arrival_min is not None:
                if arrival_min <= 0:
                    time_str = "A chegar"
                elif arrival_min == 1:
                    time_str = "1 minuto"
                else:
                    time_str = f"{arrival_min} minutos"
            else:
                est = a.get("estimated_arrival_time", "")
                if est:
                    try:
                        dt = datetime.fromisoformat(est)
                        time_str = dt.strftime("%H:%M")
                    except ValueError:
                        time_str = est
                else:
                    time_str = "?"

            arrivals.append({
                "line": a.get("route_short_name") or a.get("route_long_name", "?"),
                "destination": a.get("trip_headsign", "?"),
                "time": f"{status_emoji} {time_str}",
                "minutes": arrival_min,
                "status": a.get("status", ""),
            })

        return {
            "stop_id": data.get("stop_id", stop_id),
            "stop_name": data.get("stop_name", stop_id),
            "arrivals": arrivals,
        }
    except Exception:
        logger.exception("Error fetching real-time data for stop %s", stop_id)
        return {"stop_id": stop_id, "stop_name": stop_id, "arrivals": []}


async def get_stop_info(stop_id: str) -> dict:
    """Get stop details including routes that serve it."""
    try:
        data = await _get(f"/stops/{stop_id}", cache_ttl=3600)
        routes = []
        for r in data.get("routes", []):
            routes.append({
                "number": r.get("number", r.get("id", "?")),
                "name": r.get("name", "?"),
            })
        return {
            "stop_id": data.get("stop_id", stop_id),
            "name": data.get("stop_name", stop_id),
            "zone": data.get("zone_id", ""),
            "lat": data.get("stop_lat"),
            "lon": data.get("stop_lon"),
            "routes": routes,
        }
    except Exception:
        logger.exception("Error fetching stop info for %s", stop_id)
        return {"stop_id": stop_id, "name": stop_id, "routes": []}


async def get_routes() -> list[dict]:
    """Get all STCP routes."""
    try:
        data = await _get("/routes", cache_ttl=3600)
        if isinstance(data, list):
            route_list = data
        else:
            route_list = data.get("results", data.get("routes", []))
        return [
            {
                "id": r.get("route_id", r.get("id", "")),
                "number": r.get("route_slug", r.get("number", "")),
                "name": r.get("name", r.get("route_long_name", "")),
            }
            for r in route_list[:50]
        ]
    except Exception:
        logger.exception("Error fetching routes")
        return []


async def get_route_stops(route_id: str, direction: int = 0) -> list[dict]:
    """Get stops for a specific route and direction."""
    try:
        data = await _get(
            f"/route/{route_id}/stops/direction",
            params={"direction_id": direction},
            cache_ttl=3600,
        )
        stops = data.get("stops", [])
        return [
            {
                "stop_id": s["stop_id"],
                "name": s["stop_name"],
                "code": s.get("stop_code", s["stop_id"]),
                "seq": s.get("stop_sequence", 0),
            }
            for s in stops
        ]
    except Exception:
        logger.exception("Error fetching route stops")
        return []


async def search_nearby_stops(lat: float, lon: float,
                              radius_km: float = 0.4) -> list[dict]:
    """Search for bus stops near coordinates.

    Tries the API first, then falls back to local GTFS data.
    """
    # Try API first
    try:
        data = await _get(
            "/stops/nearby",
            params={"lat": lat, "lon": lon, "radius": int(radius_km * 1000)},
            cache_ttl=300,
        )
        results = data if isinstance(data, list) else data.get("results", [])
        if results:
            stops = []
            for s in results[:10]:
                stop_lat = s.get("stop_lat")
                stop_lon = s.get("stop_lon")
                dist = 0
                if stop_lat and stop_lon:
                    dist = int(_geo_distance(lat, lon, stop_lat, stop_lon) * 1000)
                stops.append({
                    "stop_id": s.get("stop_id", ""),
                    "name": s.get("stop_name", ""),
                    "distance_m": s.get("distance", dist),
                    "lat": stop_lat,
                    "lon": stop_lon,
                })
            stops.sort(key=lambda x: x["distance_m"])
            return stops
    except Exception:
        logger.debug("Nearby stops API not available, using local GTFS data")

    # Fallback: local GTFS data
    return _search_nearby_local(lat, lon, radius_km)


def _search_nearby_local(lat: float, lon: float,
                         radius_km: float) -> list[dict]:
    """Search for nearby stops using locally downloaded GTFS data."""
    if not _gtfs_bus_stops:
        return []

    stops = []
    for stop in _gtfs_bus_stops:
        dist = _geo_distance(lat, lon, stop["lat"], stop["lon"])
        if dist <= radius_km:
            stops.append({
                "stop_id": stop["stop_id"],
                "name": stop["name"],
                "distance_m": int(dist * 1000),
                "lat": stop["lat"],
                "lon": stop["lon"],
            })

    stops.sort(key=lambda x: x["distance_m"])
    return stops[:10]


async def download_stcp_gtfs() -> bool:
    """Download STCP GTFS data and extract bus stop coordinates."""
    global _gtfs_bus_stops
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = GTFS_DIR / "stcp.zip"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GTFS_STCP_URL, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Failed to download STCP GTFS: HTTP %d", resp.status)
                    return False
                content = await resp.read()
                if len(content) < 100:
                    logger.warning("STCP GTFS download too small")
                    return False

        async with aiofiles.open(zip_path, "wb") as f:
            await f.write(content)

        _gtfs_bus_stops = _extract_stcp_stops(zip_path)
        logger.info("STCP GTFS loaded: %d bus stops", len(_gtfs_bus_stops))
        return True
    except Exception:
        logger.exception("Error downloading STCP GTFS data")
        return False


def _extract_stcp_stops(zip_path: Path) -> list[dict]:
    """Extract stop coordinates from STCP GTFS zip."""
    stops = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        if "stops.txt" not in zf.namelist():
            return []
        with zf.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                lat = row.get("stop_lat", "")
                lon = row.get("stop_lon", "")
                stop_id = row.get("stop_id", "")
                name = row.get("stop_name", "")
                if lat and lon and stop_id and name:
                    try:
                        stops.append({
                            "stop_id": stop_id,
                            "name": name,
                            "lat": float(lat),
                            "lon": float(lon),
                        })
                    except ValueError:
                        continue
    return stops


def _geo_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two points (haversine)."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _status_emoji(status: str) -> str:
    status = status.upper()
    if status == "ON_TIME":
        return "\u2705"  # green check
    elif status == "DELAYED":
        return "\u26a0\ufe0f"  # warning
    elif status == "EARLY":
        return "\u23e9"  # fast forward
    return "\u23f0"  # alarm clock
