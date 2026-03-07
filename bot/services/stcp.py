"""Service for fetching STCP (bus) data from the stcp.pt API."""

import logging
from datetime import datetime

import aiohttp

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=60)

API_BASE = "https://stcp.pt/api"


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


def _status_emoji(status: str) -> str:
    status = status.upper()
    if status == "ON_TIME":
        return "\u2705"  # green check
    elif status == "DELAYED":
        return "\u26a0\ufe0f"  # warning
    elif status == "EARLY":
        return "\u23e9"  # fast forward
    return "\u23f0"  # alarm clock
