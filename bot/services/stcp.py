"""Service for fetching STCP (bus) data from the stcp.pt API.

Endpoint status, verified with live requests on 2026-07-26:

* ``GET /api/stops?search=<q>``                      -> 200, JSON ``{"results": [...]}``
* ``GET /api/stops/<stop_id>``                       -> 200, JSON stop detail + routes
* ``GET /api/stops/<stop_id>/realtime``              -> 200, JSON ``{"arrivals": [...],
  "data_source": "realtime"}``
* ``GET /api/stops/nearby?lat=&lng=&radius=``        -> 200, JSON ``{"stops": [...]}``
  (note: the parameter is ``lng``, **not** ``lon`` — ``lon`` yields HTTP 400)
* ``GET /api/route/<route_id>/stops/direction?direction_id=`` -> 200, JSON ``{"stops": [...]}``

Endpoints that do **not** exist (the SPA returns an HTML 404 page):

* ``GET /api/routes``  -> 404  (route list is therefore built from the GTFS feed)
* ``GET /api/alerts``  -> 404  (see :mod:`bot.services.alerts`)

Every API-backed function distinguishes "the upstream data source failed" from
"the data source answered and there genuinely is nothing".  Failures are
reported with ``error=True`` and a ``source`` of :data:`SOURCE_UNAVAILABLE` /
:data:`SOURCE_NOT_FOUND` so the presentation layer never tells a user "no buses
are coming" when the truth is "we could not ask".
"""

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

# Data-source markers used in the dicts returned by this module.
SOURCE_REALTIME = "realtime"
SOURCE_SCHEDULED = "scheduled"
SOURCE_GTFS = "gtfs"
SOURCE_UNAVAILABLE = "unavailable"
SOURCE_NOT_FOUND = "not_found"

# Negative caching: when the API is down we must not spend a 10s timeout on
# every single user request.  A failure marks the whole API as unavailable for
# FAILURE_TTL seconds; a 404 marks only that one path (for longer, since a
# non-existent stop stays non-existent).
FAILURE_TTL = 60
NOT_FOUND_TTL = 600
REQUEST_TIMEOUT = 10

_failure_cache = TTLCache(default_ttl=FAILURE_TTL)
_API_DOWN_KEY = "stcp:api-down"

# Local GTFS data, populated by download_stcp_gtfs()
_gtfs_bus_stops: list[dict] = []
_gtfs_bus_routes: list[dict] = []
_gtfs_feed_date: str = ""


class STCPUnavailable(Exception):
    """The STCP API could not be reached (network error, timeout, 5xx)."""


class STCPNotFound(STCPUnavailable):
    """The STCP API answered, but the requested resource does not exist."""


class ArrivalsList(list):
    """A list of arrivals that also carries data-source metadata.

    ``get_stop_real_time()`` puts one of these under the ``"arrivals"`` key so
    that callers which only forward ``data["arrivals"]`` (and never see the
    surrounding dict) can still tell an upstream failure apart from a stop with
    genuinely no upcoming buses.
    """

    def __init__(self, items=(), *, error: bool = False,
                 source: str = SOURCE_REALTIME):
        super().__init__(items)
        self.error = error
        self.source = source


def reset_failure_cache() -> None:
    """Forget any recorded API failures (used by tests and /refresh paths)."""
    _failure_cache.clear()


def api_unavailable() -> bool:
    """True while the STCP API is inside its negative-cache back-off window."""
    return _failure_cache.get(_API_DOWN_KEY) is not None


def _note_api_down(reason: str) -> None:
    _failure_cache.set(_API_DOWN_KEY, reason, ttl=FAILURE_TTL)


async def _get(path: str, params: dict | None = None,
               cache_ttl: int | None = None) -> dict | list:
    """GET a JSON document from the STCP API.

    Raises:
        STCPNotFound: the API answered 404 for this path.
        STCPUnavailable: the API is unreachable, timed out or returned 5xx —
            including when a recent failure is still negative-cached.
    """
    cache_key = f"stcp:{path}:{params}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Negative cache: skip the request entirely while we know it will fail.
    if _failure_cache.get(cache_key) is not None:
        raise STCPNotFound(f"{path} recently returned 404")
    down_reason = _failure_cache.get(_API_DOWN_KEY)
    if down_reason is not None:
        raise STCPUnavailable(f"STCP API unavailable ({down_reason})")

    url = f"{API_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 404:
                    _failure_cache.set(cache_key, "404", ttl=NOT_FOUND_TTL)
                    raise STCPNotFound(f"{path} -> HTTP 404")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except STCPUnavailable:
        raise
    except Exception as exc:
        _note_api_down(type(exc).__name__)
        logger.warning("STCP API request failed (%s): %s", path, exc)
        raise STCPUnavailable(str(exc)) from exc

    if cache_ttl is not None:
        _cache.set(cache_key, data, ttl=cache_ttl)
    else:
        _cache.set(cache_key, data)
    return data


def search_stops_local(query: str, max_results: int = 10) -> list[dict]:
    """Search bus stops locally using GTFS data with fuzzy matching.

    Works offline - no API call needed. Good for autocomplete.
    """
    if not _gtfs_bus_stops or not query.strip():
        return []

    from bot.utils.search import fuzzy_search

    names_map: dict[str, dict] = {}
    for stop in _gtfs_bus_stops:
        key = f"{stop['name']} {stop['stop_id']}"
        names_map[key] = stop

    # Also try matching against stop_id directly
    query_upper = query.strip().upper()
    code_matches = []
    for stop in _gtfs_bus_stops:
        if stop["stop_id"].upper().startswith(query_upper):
            code_matches.append(stop)

    # Fuzzy match on names
    name_results = fuzzy_search(query, list(names_map.keys()),
                                min_score=15, max_results=max_results)

    results = []
    seen_ids: set[str] = set()

    # Code matches first (exact prefix on stop code)
    for stop in code_matches[:max_results]:
        if stop["stop_id"] not in seen_ids:
            seen_ids.add(stop["stop_id"])
            results.append({
                "stop_id": stop["stop_id"],
                "name": stop["name"],
                "code": stop["stop_id"],
                "zone": "",
            })

    # Then fuzzy name matches
    for key, _score in name_results:
        stop = names_map[key]
        if stop["stop_id"] not in seen_ids:
            seen_ids.add(stop["stop_id"])
            results.append({
                "stop_id": stop["stop_id"],
                "name": stop["name"],
                "code": stop["stop_id"],
                "zone": "",
            })

    return results[:max_results]


async def search_stops(query: str) -> list[dict]:
    """Search for bus stops by name. Returns list of matching stops.

    Falls back to the locally cached GTFS stop list when the API is down, so
    an outage degrades to offline search rather than to "no results".
    """
    try:
        data = await _get("/stops", params={"search": query}, cache_ttl=300)
        results = data.get("results", [])
        return [
            {
                "stop_id": s["stop_id"],
                "name": s["stop_name"],
                "code": s.get("stop_code") or s["stop_id"],
                "zone": s.get("zone_id", ""),
            }
            for s in results[:20]
        ]
    except Exception:
        logger.debug("API search failed, falling back to local GTFS search")
        return search_stops_local(query)


def _unavailable_arrivals(stop_id: str, stop_name: str | None = None,
                          source: str = SOURCE_UNAVAILABLE) -> dict:
    """Build the honest "we could not fetch anything" real-time payload."""
    return {
        "stop_id": stop_id,
        "stop_name": stop_name or stop_id,
        "arrivals": ArrivalsList(error=True, source=source),
        "error": True,
        "source": source,
        "realtime": False,
        "last_updated": None,
    }


async def get_stop_real_time(stop_id: str) -> dict:
    """Get real-time arrivals for a specific stop.

    Returns a dict with:
        ``arrivals``     — :class:`ArrivalsList` of arrival dicts (may be empty).
        ``error``        — True when the data source could not be consulted.
        ``source``       — ``"realtime"``/``"scheduled"`` on success, otherwise
                           ``"unavailable"`` or ``"not_found"``.
        ``realtime``     — True only when the upstream data really is live.
        ``last_updated`` — upstream timestamp, when provided.

    An empty ``arrivals`` with ``error=False`` means "no buses due"; an empty
    ``arrivals`` with ``error=True`` means "we do not know".
    """
    try:
        data = await _get(f"/stops/{stop_id}/realtime", cache_ttl=30)
    except STCPNotFound:
        logger.info("STCP stop %s not found", stop_id)
        return _unavailable_arrivals(stop_id, source=SOURCE_NOT_FOUND)
    except STCPUnavailable:
        return _unavailable_arrivals(stop_id)
    except Exception:
        logger.exception("Unexpected error fetching real-time data for %s", stop_id)
        return _unavailable_arrivals(stop_id)

    try:
        source = data.get("data_source") or SOURCE_REALTIME
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
                "delay_minutes": a.get("delay_minutes"),
            })

        return {
            "stop_id": data.get("stop_id", stop_id),
            "stop_name": data.get("stop_name", stop_id),
            "arrivals": ArrivalsList(arrivals, error=False, source=source),
            "error": False,
            "source": source,
            "realtime": source == SOURCE_REALTIME,
            "last_updated": data.get("last_updated"),
        }
    except Exception:
        logger.exception("Error parsing real-time data for stop %s", stop_id)
        return _unavailable_arrivals(stop_id)


async def get_stop_info(stop_id: str) -> dict:
    """Get stop details including routes that serve it.

    On failure returns the same shape with ``error=True`` so callers can say
    "could not load" instead of rendering a stop with zero routes.
    """
    try:
        data = await _get(f"/stops/{stop_id}", cache_ttl=3600)
    except STCPNotFound:
        return {"stop_id": stop_id, "name": stop_id, "routes": [],
                "error": True, "source": SOURCE_NOT_FOUND}
    except STCPUnavailable:
        return {"stop_id": stop_id, "name": stop_id, "routes": [],
                "error": True, "source": SOURCE_UNAVAILABLE}
    except Exception:
        logger.exception("Unexpected error fetching stop info for %s", stop_id)
        return {"stop_id": stop_id, "name": stop_id, "routes": [],
                "error": True, "source": SOURCE_UNAVAILABLE}

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
        "error": False,
        "source": SOURCE_REALTIME,
    }


async def get_routes() -> list[dict]:
    """Get all STCP routes.

    ``GET /api/routes`` does not exist (HTTP 404, verified 2026-07-26), so the
    route list comes from the official STCP GTFS feed published on
    opendata.porto.digital and loaded by :func:`download_stcp_gtfs`.  Returns an
    empty list when no route data is available — never invented lines.
    """
    try:
        data = await _get("/routes", cache_ttl=3600)
        route_list = data if isinstance(data, list) else data.get(
            "results", data.get("routes", []))
        api_routes = [
            {
                "id": r.get("route_id", r.get("id", "")),
                "number": r.get("route_slug", r.get("number", "")),
                "name": r.get("name", r.get("route_long_name", "")),
            }
            for r in route_list
        ]
        if api_routes:
            return api_routes
    except STCPUnavailable:
        pass
    except Exception:
        logger.exception("Unexpected error fetching routes from API")

    if _gtfs_bus_routes:
        return list(_gtfs_bus_routes)

    logger.warning(
        "No STCP route data available (API has no /routes endpoint and the "
        "GTFS feed has not been loaded)"
    )
    return []


async def get_route_stops(route_id: str, direction: int = 0) -> list[dict]:
    """Get stops for a specific route and direction.

    Returns an empty list when the route is unknown or the API is unavailable;
    callers should treat that as "could not load", not as "route has no stops".
    """
    try:
        data = await _get(
            f"/route/{route_id}/stops/direction",
            params={"direction_id": direction},
            cache_ttl=3600,
        )
    except STCPUnavailable as exc:
        logger.info("Could not fetch stops for route %s: %s", route_id, exc)
        return []
    except Exception:
        logger.exception("Unexpected error fetching route stops")
        return []

    stops = data.get("stops", [])
    return [
        {
            "stop_id": s["stop_id"],
            "name": s["stop_name"],
            "code": s.get("stop_code") or s["stop_id"],
            "seq": s.get("stop_sequence", 0),
        }
        for s in stops
        if s.get("stop_id") and s.get("stop_name")
    ]


async def search_nearby_stops(lat: float, lon: float,
                              radius_km: float = 0.4) -> list[dict]:
    """Search for bus stops near coordinates.

    Tries the API first, then falls back to local GTFS data.

    The API expects ``lat``/``lng`` (passing ``lon`` returns HTTP 400) and
    answers ``{"stops": [{"id", "name", "latitude", "longitude", "distance"}]}``.
    """
    try:
        data = await _get(
            "/stops/nearby",
            params={"lat": lat, "lng": lon, "radius": int(radius_km * 1000)},
            cache_ttl=300,
        )
        if isinstance(data, list):
            results = data
        else:
            results = data.get("stops") or data.get("results") or []
        stops = []
        for s in results[:10]:
            stop_lat = s.get("latitude", s.get("stop_lat"))
            stop_lon = s.get("longitude", s.get("stop_lon"))
            distance = s.get("distance")
            if distance is None and stop_lat is not None and stop_lon is not None:
                distance = _geo_distance(lat, lon, stop_lat, stop_lon) * 1000
            stops.append({
                "stop_id": s.get("id") or s.get("stop_id", ""),
                "name": s.get("name") or s.get("stop_name", ""),
                "distance_m": int(distance) if distance is not None else 0,
                "lat": stop_lat,
                "lon": stop_lon,
            })
        if stops:
            stops.sort(key=lambda x: x["distance_m"])
            return stops
    except STCPUnavailable:
        logger.debug("Nearby stops API unavailable, using local GTFS data")
    except Exception:
        logger.exception("Unexpected error in nearby stop search")

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


# CKAN dataset holding the official STCP GTFS feed.  A new resource is
# published almost daily, so the pinned URL in bot.config goes stale; this lets
# us discover the current one instead of silently having no bus data.
CKAN_STCP_PACKAGE_URL = (
    "https://opendata.porto.digital/api/3/action/package_show"
    "?id=horarios-paragens-e-rotas-em-formato-gtfs-stcp"
)


async def _discover_latest_gtfs_url() -> str | None:
    """Ask the Porto open-data CKAN portal for the newest STCP GTFS zip URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                CKAN_STCP_PACKAGE_URL,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)
    except Exception:
        logger.debug("Could not query CKAN for the latest STCP GTFS feed",
                     exc_info=True)
        return None

    resources = (payload.get("result") or {}).get("resources") or []
    candidates = [
        r for r in resources
        if str(r.get("format", "")).upper() in ("ZIP", "GTFS")
        and r.get("url") and (r.get("size") or 0) > 100_000
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.get("last_modified") or r.get("created") or "")
    newest = candidates[-1]
    logger.info("Latest STCP GTFS on CKAN: %s (%s)",
                newest.get("name"), newest.get("last_modified"))
    return newest.get("url")


async def _download(url: str) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=60),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning("Failed to download STCP GTFS from %s: HTTP %d",
                                   url, resp.status)
                    return None
                content = await resp.read()
    except Exception:
        logger.exception("Error downloading STCP GTFS data from %s", url)
        return None

    if len(content) < 100 or not content.startswith(b"PK"):
        logger.warning("STCP GTFS download from %s is not a usable zip (%d bytes)",
                       url, len(content))
        return None
    return content


async def download_stcp_gtfs() -> bool:
    """Download STCP GTFS data and extract bus stops and routes.

    Tries the URL pinned in the config first and, if that is stale/broken,
    discovers the newest published resource via the CKAN API.
    """
    global _gtfs_bus_stops, _gtfs_bus_routes, _gtfs_feed_date
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = GTFS_DIR / "stcp.zip"

    urls: list[str] = [GTFS_STCP_URL]
    content = await _download(GTFS_STCP_URL)
    if content is None:
        discovered = await _discover_latest_gtfs_url()
        if discovered and discovered not in urls:
            content = await _download(discovered)

    if content is None:
        logger.warning("STCP GTFS unavailable — bus route list and offline "
                       "stop search will be empty")
        return False

    try:
        async with aiofiles.open(zip_path, "wb") as f:
            await f.write(content)

        _gtfs_bus_stops = _extract_stcp_stops(zip_path)
        _gtfs_bus_routes = _extract_stcp_routes(zip_path)
        _gtfs_feed_date = _extract_feed_date(zip_path)
        logger.info("STCP GTFS loaded: %d bus stops, %d routes (feed %s)",
                    len(_gtfs_bus_stops), len(_gtfs_bus_routes),
                    _gtfs_feed_date or "unknown")
        return bool(_gtfs_bus_stops)
    except Exception:
        logger.exception("Error extracting STCP GTFS data")
        return False


def _read_gtfs_table(zip_path: Path, member: str) -> list[dict]:
    """Read one GTFS csv member as a list of dicts. Missing member -> []."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if member not in zf.namelist():
                return []
            with zf.open(member) as f:
                return list(csv.DictReader(
                    io.TextIOWrapper(f, encoding="utf-8-sig")))
    except Exception:
        logger.exception("Could not read %s from %s", member, zip_path)
        return []


def _extract_stcp_routes(zip_path: Path) -> list[dict]:
    """Extract the bus route list from the GTFS feed's routes.txt."""
    routes = []
    for row in _read_gtfs_table(zip_path, "routes.txt"):
        route_id = (row.get("route_id") or "").strip()
        number = (row.get("route_short_name") or "").strip()
        name = (row.get("route_long_name") or "").strip()
        if not route_id or not (number or name):
            continue
        routes.append({
            "id": number or route_id,
            "number": number or route_id,
            "name": name,
            "source": SOURCE_GTFS,
            "sort_order": (row.get("route_sort_order") or "").strip(),
        })
    routes.sort(key=lambda r: (len(r["number"]), r["number"]))
    return routes


def _extract_feed_date(zip_path: Path) -> str:
    """Return the GTFS feed's publication/validity start date, if declared."""
    for row in _read_gtfs_table(zip_path, "feed_info.txt"):
        for key in ("feed_start_date", "feed_version"):
            value = (row.get(key) or "").strip()
            if value:
                return value
    return ""


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
    if status in ("ON_TIME", "ARRIVING"):
        return "\u2705"  # green check
    elif status == "DELAYED":
        return "\u26a0\ufe0f"  # warning
    elif status == "EARLY":
        return "\u23e9"  # fast forward
    return "\u23f0"  # alarm clock
