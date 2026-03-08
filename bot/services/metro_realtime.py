"""Metro do Porto departures via the MOTIS open transit routing API.

MOTIS (https://europe.motis-project.de) is an open-source multi-modal transit
router that ingests GTFS data from transit agencies across Europe, including
Metro do Porto.  By querying transit routes from a station to its neighbours
we can extract the next departure times, lines, and directions.

This replaces the previous Playwright-based scraper which rendered the
metrodoporto.pt trip planner in a headless browser (slow, fragile, blocked
by proxy environments).

The MOTIS API returns schedule-based data from the Metro do Porto GTFS feed.
Responses are fast (~500ms for parallel queries) and include line codes,
headsigns (directions), colours, and agency info.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=90)  # 90-second cache

# MOTIS European transit routing API
_MOTIS_URL = "https://europe.motis-project.de/api/v1/plan"

# Line code to internal bot code mapping (MOTIS returns short route names)
_ROUTE_TO_LINE = {
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
    "E": "E",
    "F": "F",
}


async def _query_motis(origin_lat: float, origin_lon: float,
                       dest_lat: float, dest_lon: float,
                       num_itineraries: int = 5) -> list[dict]:
    """Query MOTIS for transit itineraries between two points."""
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    params = {
        "fromPlace": f"{origin_lat},{origin_lon}",
        "toPlace": f"{dest_lat},{dest_lon}",
        "time": time_str,
        "mode": "TRANSIT",
        "numItineraries": str(num_itineraries),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_MOTIS_URL, params=params)
            if resp.status_code != 200:
                logger.warning("MOTIS API returned HTTP %d", resp.status_code)
                return []
            return resp.json().get("itineraries", [])
    except Exception:
        logger.debug("MOTIS API request failed", exc_info=True)
        return []


def _get_neighbour_stations(station_name: str) -> list[str]:
    """Get neighbouring stations in opposite directions."""
    from bot.services.metro import STATIONS, get_line_stations

    station_data = STATIONS.get(station_name)
    if not station_data:
        return []

    neighbours = set()
    for line_code in station_data["lines"]:
        line_stations = get_line_stations(line_code)
        if station_name not in line_stations:
            continue
        idx = line_stations.index(station_name)
        if idx > 0:
            neighbours.add(line_stations[idx - 1])
        if idx < len(line_stations) - 1:
            neighbours.add(line_stations[idx + 1])

    return list(neighbours)[:4]


def _extract_departures(itineraries: list[dict],
                        station_name: str) -> list[dict]:
    """Extract metro departures from MOTIS itineraries."""
    from bot.config import METRO_LINES

    now = datetime.now(timezone.utc)
    departures = []
    seen = set()  # (time, direction) to deduplicate

    for itin in itineraries:
        for leg in itin.get("legs", []):
            if leg.get("mode") not in ("SUBWAY", "TRAM", "RAIL"):
                continue
            if leg.get("agencyName", "").lower() not in (
                "metro do porto", "metro", ""
            ):
                continue

            dep_str = leg.get("from", {}).get("departure", "")
            if not dep_str:
                continue

            headsign = leg.get("headsign", "")
            route_short = leg.get("routeShortName", "")

            # Deduplicate by time + direction
            dedup_key = (dep_str, headsign)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Parse departure time
            try:
                dep_dt = datetime.fromisoformat(dep_str)
                if dep_dt.tzinfo is None:
                    dep_dt = dep_dt.replace(tzinfo=timezone.utc)
                minutes_until = (dep_dt - now).total_seconds() / 60
            except (ValueError, TypeError):
                continue

            if minutes_until < -1:
                continue

            # Format time display
            if minutes_until < 1:
                time_display = "< 1 min"
            elif minutes_until < 60:
                time_display = f"{int(minutes_until)} min"
            else:
                time_display = dep_dt.strftime("%H:%M")

            # Map route to line
            line_code = _ROUTE_TO_LINE.get(route_short, "")
            line_data = METRO_LINES.get(line_code, {})
            if line_data:
                line_display = f"{line_data['emoji']} {line_data['name']}"
            else:
                line_display = f"🚇 Linha {route_short}" if route_short else "🚇 Metro"

            departures.append({
                "direction": headsign,
                "time": time_display,
                "line": line_display,
                "line_code": line_code,
                "minutes": max(0, int(minutes_until)),
                "estimated": False,
                "realtime": True,
                "route_color": leg.get("routeColor", ""),
            })

    # Sort by departure time
    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures


async def get_realtime_departures(station_name: str,
                                   count: int = 8) -> list[dict]:
    """Get next departures for a metro station via MOTIS API.

    Queries routes from the station to its neighbours in opposite
    directions.  Each response includes the departure time at the
    origin station, the line, and the headsign (direction).

    Returns a list of departure dicts compatible with
    ``metro.get_next_departures()``.
    """
    cache_key = f"rt:{station_name}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    from bot.services.metro import STATIONS

    station_data = STATIONS.get(station_name)
    if not station_data:
        return []

    origin_lat = station_data.get("lat")
    origin_lon = station_data.get("lon")
    if not origin_lat or not origin_lon:
        return []

    # Get neighbours to query in opposite directions
    neighbours = _get_neighbour_stations(station_name)
    if not neighbours:
        return []

    # Query MOTIS for routes to each neighbour in parallel
    tasks = []
    for neighbour in neighbours:
        ndata = STATIONS.get(neighbour, {})
        nlat, nlon = ndata.get("lat"), ndata.get("lon")
        if nlat and nlon:
            tasks.append(_query_motis(origin_lat, origin_lon, nlat, nlon, 5))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge all itineraries
    all_itineraries = []
    for result in results:
        if isinstance(result, list):
            all_itineraries.extend(result)

    departures = _extract_departures(all_itineraries, station_name)

    # Limit to requested count
    departures = departures[:count]

    if departures:
        _cache.set(cache_key, departures)

    return departures


async def close():
    """No-op kept for API compatibility."""
    pass
