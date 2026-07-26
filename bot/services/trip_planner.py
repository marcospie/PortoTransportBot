"""Multimodal trip planning for Porto public transport.

Two planners live in this module:

1. **MOTIS** (:func:`plan_trip_from_coords_async`) — the *real* planner.
   ``https://europe.motis-project.de/api/v1/plan`` is the public
   `transitous <https://transitous.org/api/>`_ MOTIS instance.  It ingests the
   GTFS feeds of STCP, Metro do Porto, CP and the rest of Europe, so it plans
   multimodally against **real timetables**: actual departure times, real
   waiting time between legs, real transfers and real headsigns.  Verified with
   live requests (see the module docstring test in tests/test_routes_location.py
   and the report notes): the endpoint requires a non-generic ``User-Agent``
   header — the transitous usage policy rejects default library agents with
   HTTP 403.

2. **The local haversine estimator** (:func:`plan_trip_from_coords`) — an
   explicit *offline fallback* used only when MOTIS cannot be reached.  It has
   no timetable at all: it derives ride times from straight-line distance and
   average speeds, and therefore does **not** know about waiting times.  Every
   option it produces is flagged ``estimated=True`` / ``source="estimate"`` so
   the presentation layer can label it as a rough estimate instead of passing
   it off as an itinerary.
"""

import heapq
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from bot.services.metro import (
    STATIONS as METRO_STATIONS,
    search_stations as metro_search,
)
from bot.services.cp import (
    STATIONS as CP_STATIONS,
    search_stations as cp_search,
    CP_LINES,
)
from bot.services.metrobus import (
    STOPS as METROBUS_STOPS,
    search_stops as metrobus_search,
    METROBUS_LINES,
)
from bot.config import METRO_LINES

logger = logging.getLogger(__name__)

PORTO_TZ = ZoneInfo("Europe/Lisbon")

# Walking speed: ~5 km/h -> ~80 m/min
WALK_SPEED_M_PER_MIN = 80

# Average speeds in km/h, used *only* by the offline estimator.
AVERAGE_SPEEDS = {
    "metro": 30,
    "bus": 15,
    "train": 50,
    "metrobus": 20,
}

# Maximum walking distance to consider a stop reachable (metres)
MAX_WALK_M = 1500

# Offline estimator tuning
TRANSFER_PENALTY_MIN = 3        # minutes lost changing line/vehicle
WALK_TRANSFER_MAX_M = 800       # how far we will walk between two stops
MAX_GRAPH_TRANSFERS = 3         # metro->bus->metro and friends are allowed
MAX_TOTAL_MIN = 180             # prune absurd itineraries

# ---------------------------------------------------------------------------
# MOTIS (transitous) — timetable-backed planning
# ---------------------------------------------------------------------------
MOTIS_BASE_URL = "https://europe.motis-project.de"
MOTIS_PLAN_URL = f"{MOTIS_BASE_URL}/api/v1/plan"
# transitous rejects generic library user-agents with HTTP 403, so identify us.
MOTIS_USER_AGENT = "PortoTransportBot/1.0 (+https://github.com/porto-transport-bot)"
MOTIS_TIMEOUT = 15.0

SOURCE_MOTIS = "motis"
SOURCE_ESTIMATE = "estimate"

# MOTIS leg "mode" -> our internal mode name.
_MOTIS_MODE_MAP = {
    "WALK": "walk",
    "BIKE": "walk",
    "CAR": "walk",
    "BUS": "bus",
    "COACH": "bus",
    "TROLLEYBUS": "bus",
    "SUBWAY": "metro",
    "TRAM": "metro",
    "METRO": "train",
    "RAIL": "train",
    "REGIONAL_RAIL": "train",
    "REGIONAL_FAST_RAIL": "train",
    "LONG_DISTANCE": "train",
    "HIGHSPEED_RAIL": "train",
    "NIGHT_RAIL": "train",
    "FERRY": "train",
}

# Agency name fragments are more reliable than MOTIS' generic mode names:
# CP suburban trains come back as mode "METRO", for instance.
_AGENCY_MODE_HINTS = (
    ("metro do porto", "metro"),
    ("comboios de portugal", "train"),
    ("transportes colectivos do porto", "bus"),
    ("stcp", "bus"),
)


@dataclass
class TripStep:
    """A single step in a trip."""
    mode: str  # walk, metro, bus, train, metrobus
    from_name: str
    to_name: str
    line: str = ""
    duration_min: int = 0
    direction: str = ""
    # Timetable data (MOTIS only) — local Europe/Lisbon "HH:MM" strings.
    departure_time: str = ""
    arrival_time: str = ""
    wait_min: int = 0


@dataclass
class TripOption:
    """A complete trip option from origin to destination."""
    steps: list[TripStep] = field(default_factory=list)
    total_time_min: int = 0
    transfers: int = 0
    zones: list[str] = field(default_factory=list)
    # ``estimated`` is True when the option came from the offline haversine
    # estimator and therefore has no timetable behind it.
    estimated: bool = False
    source: str = SOURCE_MOTIS
    departure_time: str = ""
    arrival_time: str = ""


# ===================================================================
# Geometry helpers
# ===================================================================

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two points on Earth."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _walk_time(dist_km: float) -> int:
    """Estimated walking time in minutes."""
    return max(1, round(dist_km * 1000 / WALK_SPEED_M_PER_MIN))


def _ride_time(dist_km: float, mode: str) -> int:
    """Estimated ride time in minutes for a given mode."""
    speed = AVERAGE_SPEEDS.get(mode, 20)
    return max(1, round(dist_km / speed * 60))


# ===================================================================
# Coordinate validation (used by the commuter profile setup too)
# ===================================================================

# Generous bounding box around the Porto metropolitan area / CP suburban range.
PORTO_REGION_BOUNDS = {
    "lat_min": 40.6,
    "lat_max": 42.2,
    "lon_min": -9.3,
    "lon_max": -7.6,
}


def is_valid_porto_coords(lat, lon) -> bool:
    """True when *lat*/*lon* is a usable point in the Porto region.

    Rejects ``None``, non-numeric values, the null island (0.0, 0.0) that the
    old commuter setup happily stored, and anything outside the region the bot
    has data for.  Storing an out-of-range coordinate silently corrupts a
    profile, so this fails closed.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lon_f):
        return False
    # Exactly zero is never a real Porto coordinate — it is the "missing value"
    # default that used to get written into profiles.
    if lat_f == 0.0 or lon_f == 0.0:
        return False
    b = PORTO_REGION_BOUNDS
    return (b["lat_min"] <= lat_f <= b["lat_max"]
            and b["lon_min"] <= lon_f <= b["lon_max"])


# ===================================================================
# Location resolution
# ===================================================================

def resolve_location(text: str) -> dict | None:
    """Resolve a text query to a transport location with coordinates.

    Returns dict with keys: name, lat, lon, type, and optionally lines, zone.
    Returns None if nothing matched.
    """
    if not text or not text.strip():
        return None

    query = text.strip()

    # Try metro stations first
    results = metro_search(query)
    if results:
        station = results[0]
        name = station["name"]
        data = METRO_STATIONS[name]
        return {
            "name": name,
            "lat": data["lat"],
            "lon": data["lon"],
            "type": "metro",
            "lines": data["lines"],
            "zone": data.get("zone", ""),
        }

    # Try CP train stations
    results = cp_search(query)
    if results:
        station = results[0]
        name = station["name"]
        data = CP_STATIONS[name]
        return {
            "name": name,
            "lat": data["lat"],
            "lon": data["lon"],
            "type": "train",
            "lines": data["lines"],
            "zone": "",
        }

    # Try metrobus stops
    results = metrobus_search(query)
    if results:
        stop = results[0]
        name = stop["name"]
        data = METROBUS_STOPS[name]
        return {
            "name": name,
            "lat": data["lat"],
            "lon": data["lon"],
            "type": "metrobus",
            "lines": data["lines"],
            "zone": data.get("zone", ""),
        }

    return None


async def resolve_location_any(text: str) -> dict | None:
    """Resolve a query across *every* mode, including STCP bus stops.

    :func:`resolve_location` only knows the statically bundled metro / CP /
    MetroBus data.  STCP stops (the densest network in the city) need an async
    lookup, and the result is only accepted when it carries usable
    coordinates — a stop without coordinates is useless for planning and used
    to be stored as ``0.0``.
    """
    result = resolve_location(text)
    if result:
        return result

    from bot.services import stcp

    try:
        stops = await stcp.search_stops(text)
    except Exception:
        logger.debug("STCP stop search failed", exc_info=True)
        return None

    for stop in (stops or [])[:3]:
        lat = stop.get("lat")
        lon = stop.get("lon")
        if lat is None or lon is None:
            # The search endpoint does not return coordinates; ask the stop
            # detail endpoint, which does.
            try:
                info = await stcp.get_stop_info(stop.get("stop_id", ""))
            except Exception:
                continue
            if info.get("error"):
                continue
            lat, lon = info.get("lat"), info.get("lon")
        if is_valid_porto_coords(lat, lon):
            return {
                "name": stop.get("name") or text,
                "lat": float(lat),
                "lon": float(lon),
                "type": "bus",
                "lines": [],
                "zone": stop.get("zone", ""),
            }

    return None


def _get_nearby_all(lat: float, lon: float, radius_km: float = 1.0) -> list[dict]:
    """Find all nearby transport nodes of any type."""
    nodes: list[dict] = []

    # Metro stations
    for name, data in METRO_STATIONS.items():
        dist = _haversine(lat, lon, data["lat"], data["lon"])
        if dist <= radius_km:
            nodes.append({
                "name": name,
                "lat": data["lat"],
                "lon": data["lon"],
                "type": "metro",
                "lines": data["lines"],
                "zone": data.get("zone", ""),
                "dist_km": dist,
            })

    # CP train stations
    for name, data in CP_STATIONS.items():
        dist = _haversine(lat, lon, data["lat"], data["lon"])
        if dist <= radius_km:
            nodes.append({
                "name": name,
                "lat": data["lat"],
                "lon": data["lon"],
                "type": "train",
                "lines": data["lines"],
                "zone": "",
                "dist_km": dist,
            })

    # MetroBus stops
    for name, data in METROBUS_STOPS.items():
        dist = _haversine(lat, lon, data["lat"], data["lon"])
        if dist <= radius_km:
            nodes.append({
                "name": name,
                "lat": data["lat"],
                "lon": data["lon"],
                "type": "metrobus",
                "lines": data["lines"],
                "zone": data.get("zone", ""),
                "dist_km": dist,
            })

    nodes.sort(key=lambda n: n["dist_km"])
    return nodes


def _collect_zones(*nodes: dict) -> list[str]:
    """Collect unique zone codes from nodes, preserving order."""
    zones: list[str] = []
    for n in nodes:
        z = n.get("zone", "")
        if z and z not in zones:
            zones.append(z)
    return zones


def _find_common_metro_lines(origin_lines: list[str], dest_lines: list[str]) -> list[str]:
    """Find metro lines common to both origin and destination."""
    return [l for l in origin_lines if l in dest_lines]


# ===================================================================
# Direction ("headsign") resolution
# ===================================================================

def _line_endpoints(route: str) -> list[str]:
    """Split a ``"A ↔ B"`` route description into its two termini."""
    if not route or "↔" not in route:
        return []
    return [part.strip() for part in route.split("↔") if part.strip()]


_terminus_cache: dict[tuple[str, str], tuple[float, float] | None] = {}


def _terminus_coords(name: str, mode: str) -> tuple[float, float] | None:
    """Resolve a terminus *name* (as written in the line config) to coords.

    The line configs use abbreviations ("Sto. Ovídio", "Hospital de S. João")
    that are not dict keys, so this goes through each service's fuzzy search.
    The result is memoised: the fuzzy search is expensive and the line configs
    are static, while the network search asks for directions thousands of times.
    """
    if not name:
        return None
    cache_key = (mode, name)
    if cache_key in _terminus_cache:
        return _terminus_cache[cache_key]
    resolved = _terminus_coords_uncached(name, mode)
    _terminus_cache[cache_key] = resolved
    return resolved


def _terminus_coords_uncached(name: str, mode: str) -> tuple[float, float] | None:
    try:
        if mode == "metro":
            hits = metro_search(name)
            if hits:
                data = METRO_STATIONS.get(hits[0]["name"])
                if data:
                    return data["lat"], data["lon"]
        elif mode == "train":
            hits = cp_search(name)
            if hits:
                data = CP_STATIONS.get(hits[0]["name"])
                if data:
                    return data["lat"], data["lon"]
        elif mode == "metrobus":
            hits = metrobus_search(name)
            if hits:
                data = METROBUS_STOPS.get(hits[0]["name"])
                if data:
                    return data["lat"], data["lon"]
    except Exception:
        logger.debug("Could not resolve terminus %r for %s", name, mode, exc_info=True)
    return None


def _direction_towards(route: str, mode: str,
                       origin_lat: float, origin_lon: float,
                       dest_lat: float, dest_lon: float) -> str:
    """Pick the terminus of *route* that the traveller is heading towards.

    The old code always used the *last* endpoint of the route string, which is
    wrong roughly half of the time.  Lines here are linear, so the right
    headsign is the terminus we get *closer to* by travelling from origin to
    destination — picking "nearest to the destination" alone is not enough,
    because a mid-line destination can sit closer to the terminus behind you.
    """
    endpoints = _line_endpoints(route)
    if not endpoints:
        return ""
    if len(endpoints) == 1:
        return endpoints[0]

    scored: list[tuple[float, float, str]] = []
    for name in endpoints:
        coords = _terminus_coords(name, mode)
        if coords is None:
            continue
        from_origin = _haversine(coords[0], coords[1], origin_lat, origin_lon)
        from_dest = _haversine(coords[0], coords[1], dest_lat, dest_lon)
        scored.append((from_dest, from_origin, name))

    if not scored:
        return endpoints[-1]

    # Termini we are approaching (the destination is between us and them).
    ahead = [s for s in scored if s[0] < s[1]]
    candidates = ahead or scored
    candidates.sort(key=lambda s: s[0])
    return candidates[0][2]


def _get_line_name(mode: str, line_code: str) -> str:
    """Get the display name for a line given its mode and code."""
    if mode == "metro":
        info = METRO_LINES.get(line_code, {})
        return info.get("name", f"Linha {line_code}")
    elif mode == "train":
        info = CP_LINES.get(line_code, {})
        return info.get("name", line_code)
    elif mode == "metrobus":
        info = METROBUS_LINES.get(line_code, {})
        return info.get("name", f"Linha {line_code}")
    return line_code


def _get_line_route(mode: str, line_code: str) -> str:
    """Get the ``"A ↔ B"`` route description for a line."""
    if mode == "metro":
        return METRO_LINES.get(line_code, {}).get("route", "")
    if mode == "train":
        return CP_LINES.get(line_code, {}).get("route", "")
    if mode == "metrobus":
        return METROBUS_LINES.get(line_code, {}).get("route", "")
    return ""


# ===================================================================
# Offline estimator — single-mode builders
# ===================================================================

def _find_metro_transfer_station(
    origin_name: str, origin_lines: set[str],
    dest_name: str, dest_lines: set[str],
) -> tuple[str, str, str] | None:
    """Find the best transfer station for a metro-to-metro trip.

    Returns (transfer_station, line_from, line_to) or None.
    """
    best = None
    best_score = float("inf")

    origin_data = METRO_STATIONS.get(origin_name, {})
    dest_data = METRO_STATIONS.get(dest_name, {})
    if not origin_data or not dest_data:
        return None

    origin_lat, origin_lon = origin_data["lat"], origin_data["lon"]
    dest_lat, dest_lon = dest_data["lat"], dest_data["lon"]

    for transfer_name, transfer_data in METRO_STATIONS.items():
        if transfer_name == origin_name or transfer_name == dest_name:
            continue
        transfer_lines = set(transfer_data["lines"])
        lines_from_origin = origin_lines & transfer_lines
        lines_to_dest = transfer_lines & dest_lines
        if lines_from_origin and lines_to_dest:
            # Prefer transfers where the two lines are different
            for l1 in lines_from_origin:
                for l2 in lines_to_dest:
                    if l1 != l2:
                        t_lat, t_lon = transfer_data["lat"], transfer_data["lon"]
                        score = (_haversine(origin_lat, origin_lon, t_lat, t_lon) +
                                 _haversine(t_lat, t_lon, dest_lat, dest_lon))
                        if score < best_score:
                            best_score = score
                            best = (transfer_name, l1, l2)

    return best


def _build_direct_metro(origin_node: dict, dest_node: dict,
                        walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a direct metro route if both nodes are on the same line."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))
    common = o_lines & d_lines

    if not common:
        return None

    line_code = sorted(common)[0]  # pick first alphabetically for consistency
    line_name = _get_line_name("metro", line_code)

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "metro")

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    direction = _direction_towards(_get_line_route("metro", line_code), "metro",
                                   origin_node["lat"], origin_node["lon"],
                                   dest_node["lat"], dest_node["lon"])

    steps.append(TripStep(
        mode="metro",
        from_name=origin_node["name"],
        to_name=dest_node["name"],
        line=line_name,
        duration_min=ride_min,
        direction=direction,
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride_min + walk_dest_min
    zones = _collect_zones(origin_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones,
                      estimated=True, source=SOURCE_ESTIMATE)


def _build_metro_with_transfer(origin_node: dict, dest_node: dict,
                                walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a metro route with one transfer."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))

    transfer = _find_metro_transfer_station(
        origin_node["name"], o_lines, dest_node["name"], d_lines
    )
    if not transfer:
        return None

    transfer_name, line1_code, line2_code = transfer
    transfer_data = METRO_STATIONS[transfer_name]

    dist1 = _haversine(origin_node["lat"], origin_node["lon"],
                       transfer_data["lat"], transfer_data["lon"])
    dist2 = _haversine(transfer_data["lat"], transfer_data["lon"],
                       dest_node["lat"], dest_node["lon"])

    ride1 = _ride_time(dist1, "metro")
    ride2 = _ride_time(dist2, "metro")

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    steps.append(TripStep(
        mode="metro",
        from_name=origin_node["name"],
        to_name=transfer_name,
        line=_get_line_name("metro", line1_code),
        duration_min=ride1,
        direction=_direction_towards(_get_line_route("metro", line1_code), "metro",
                                     origin_node["lat"], origin_node["lon"],
                                     transfer_data["lat"], transfer_data["lon"]),
    ))

    steps.append(TripStep(
        mode="metro",
        from_name=transfer_name,
        to_name=dest_node["name"],
        line=_get_line_name("metro", line2_code),
        duration_min=ride2,
        direction=_direction_towards(_get_line_route("metro", line2_code), "metro",
                                     transfer_data["lat"], transfer_data["lon"],
                                     dest_node["lat"], dest_node["lon"]),
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride1 + TRANSFER_PENALTY_MIN + ride2 + walk_dest_min
    transfer_node = {"zone": transfer_data.get("zone", "")}
    zones = _collect_zones(origin_node, transfer_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=1, zones=zones,
                      estimated=True, source=SOURCE_ESTIMATE)


def _build_direct_train(origin_node: dict, dest_node: dict,
                        walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a direct train route if both nodes share a CP line."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))
    common = o_lines & d_lines

    if not common:
        return None

    line_id = sorted(common)[0]
    line_name = _get_line_name("train", line_id)

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "train")

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    steps.append(TripStep(
        mode="train",
        from_name=origin_node["name"],
        to_name=dest_node["name"],
        line=line_name,
        duration_min=ride_min,
        direction=_direction_towards(_get_line_route("train", line_id), "train",
                                     origin_node["lat"], origin_node["lon"],
                                     dest_node["lat"], dest_node["lon"]),
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride_min + walk_dest_min
    zones = _collect_zones(origin_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones,
                      estimated=True, source=SOURCE_ESTIMATE)


def _build_direct_metrobus(origin_node: dict, dest_node: dict,
                           walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a direct metrobus route if both nodes share a line."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))
    common = o_lines & d_lines

    if not common:
        return None

    line_code = sorted(common)[0]
    line_name = _get_line_name("metrobus", line_code)

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "metrobus")

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    steps.append(TripStep(
        mode="metrobus",
        from_name=origin_node["name"],
        to_name=dest_node["name"],
        line=line_name,
        duration_min=ride_min,
        direction=_direction_towards(_get_line_route("metrobus", line_code), "metrobus",
                                     origin_node["lat"], origin_node["lon"],
                                     dest_node["lat"], dest_node["lon"]),
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride_min + walk_dest_min
    zones = _collect_zones(origin_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones,
                      estimated=True, source=SOURCE_ESTIMATE)


# ===================================================================
# Offline estimator — network search (no arbitrary leg limit)
# ===================================================================

_graph_cache: dict[str, object] | None = None


def _build_graph() -> dict:
    """Build (and memoise) the static metro + CP + MetroBus network graph.

    The old planner hard-coded "at most one metro transfer" and "exactly two
    multimodal legs", which made metro→bus→metro impossible.  This graph has no
    such limit: a Dijkstra over (stop, line) states finds chains of any length
    up to :data:`MAX_GRAPH_TRANSFERS` transfers.
    """
    global _graph_cache
    if _graph_cache is not None:
        return _graph_cache

    nodes: list[dict] = []
    for name, data in METRO_STATIONS.items():
        nodes.append({"name": name, "type": "metro", "lat": data["lat"],
                      "lon": data["lon"], "lines": list(data.get("lines", [])),
                      "zone": data.get("zone", "")})
    for name, data in CP_STATIONS.items():
        if not data.get("lat") or not data.get("lon"):
            continue
        nodes.append({"name": name, "type": "train", "lat": data["lat"],
                      "lon": data["lon"], "lines": list(data.get("lines", [])),
                      "zone": ""})
    for name, data in METROBUS_STOPS.items():
        nodes.append({"name": name, "type": "metrobus", "lat": data["lat"],
                      "lon": data["lon"], "lines": list(data.get("lines", [])),
                      "zone": data.get("zone", "")})

    line_members: dict[tuple[str, str], list[int]] = {}
    for idx, node in enumerate(nodes):
        for line in node["lines"]:
            line_members.setdefault((node["type"], line), []).append(idx)

    walk_edges: dict[int, list[tuple[int, int]]] = {}
    max_walk_km = WALK_TRANSFER_MAX_M / 1000
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if a["type"] == b["type"] and a["name"] == b["name"]:
                continue
            dist = _haversine(a["lat"], a["lon"], b["lat"], b["lon"])
            if dist > max_walk_km:
                continue
            minutes = _walk_time(dist)
            walk_edges.setdefault(i, []).append((j, minutes))
            walk_edges.setdefault(j, []).append((i, minutes))

    _graph_cache = {
        "nodes": nodes,
        "line_members": line_members,
        "walk_edges": walk_edges,
    }
    return _graph_cache


def _plan_graph(origin_lat: float, origin_lon: float,
                dest_lat: float, dest_lon: float,
                max_options: int = 3) -> list[TripOption]:
    """Dijkstra over the static network. Returns estimate-flagged options."""
    graph = _build_graph()
    nodes: list[dict] = graph["nodes"]           # type: ignore[assignment]
    line_members = graph["line_members"]         # type: ignore[assignment]
    walk_edges = graph["walk_edges"]             # type: ignore[assignment]

    radius_km = MAX_WALK_M / 1000

    origin_access: dict[int, int] = {}
    dest_access: dict[int, int] = {}
    for idx, node in enumerate(nodes):
        d_o = _haversine(origin_lat, origin_lon, node["lat"], node["lon"])
        if d_o <= radius_km:
            origin_access[idx] = _walk_time(d_o)
        d_d = _haversine(dest_lat, dest_lon, node["lat"], node["lon"])
        if d_d <= radius_km:
            dest_access[idx] = _walk_time(d_d)

    if not origin_access or not dest_access:
        return []

    # state = (node_idx, line_key or None, transfers)
    best: dict[tuple, int] = {}
    prev: dict[tuple, tuple] = {}
    heap: list[tuple] = []
    counter = 0

    for idx, walk_min in origin_access.items():
        state = (idx, None, 0)
        if best.get(state, 10 ** 9) <= walk_min:
            continue
        best[state] = walk_min
        prev[state] = (None, TripStep(mode="walk", from_name="",
                                      to_name=nodes[idx]["name"],
                                      duration_min=walk_min))
        counter += 1
        heapq.heappush(heap, (walk_min, counter, state))

    goals: list[tuple[int, tuple]] = []

    while heap:
        cost, _, state = heapq.heappop(heap)
        if cost > best.get(state, 10 ** 9):
            continue
        idx, line_key, transfers = state

        if line_key is not None and idx in dest_access:
            goals.append((cost + dest_access[idx], state))

        if cost > MAX_TOTAL_MIN:
            continue

        node = nodes[idx]

        # Ride edges: board any line serving this stop.
        for line in node["lines"]:
            key = (node["type"], line)
            same_line = (line_key == key)
            new_transfers = transfers if (same_line or line_key is None) else transfers + 1
            if new_transfers > MAX_GRAPH_TRANSFERS:
                continue
            penalty = 0 if (same_line or line_key is None) else TRANSFER_PENALTY_MIN
            for other in line_members.get(key, ()):
                if other == idx:
                    continue
                target = nodes[other]
                dist = _haversine(node["lat"], node["lon"],
                                  target["lat"], target["lon"])
                ride = _ride_time(dist, node["type"])
                new_cost = cost + penalty + ride
                if new_cost > MAX_TOTAL_MIN:
                    continue
                new_state = (other, key, new_transfers)
                if new_cost >= best.get(new_state, 10 ** 9):
                    continue
                best[new_state] = new_cost
                prev[new_state] = (state, TripStep(
                    mode=node["type"],
                    from_name=node["name"],
                    to_name=target["name"],
                    line=_get_line_name(node["type"], line),
                    duration_min=ride,
                    direction=_direction_towards(
                        _get_line_route(node["type"], line), node["type"],
                        node["lat"], node["lon"],
                        target["lat"], target["lon"]),
                ))
                counter += 1
                heapq.heappush(heap, (new_cost, counter, new_state))

        # Walk transfers between nearby stops (this is what makes
        # metro -> bus -> metro style chains reachable).
        if line_key is not None:
            for other, walk_min in walk_edges.get(idx, ()):
                new_state = (other, None, transfers)
                new_cost = cost + walk_min
                if new_cost > MAX_TOTAL_MIN:
                    continue
                if new_cost >= best.get(new_state, 10 ** 9):
                    continue
                best[new_state] = new_cost
                prev[new_state] = (state, TripStep(
                    mode="walk",
                    from_name=node["name"],
                    to_name=nodes[other]["name"],
                    duration_min=walk_min,
                ))
                counter += 1
                heapq.heappush(heap, (new_cost, counter, new_state))

    if not goals:
        return []

    goals.sort(key=lambda g: g[0])

    options: list[TripOption] = []
    seen_signatures: set[str] = set()
    for total, state in goals:
        steps: list[TripStep] = []
        cursor = state
        zone_nodes: list[dict] = []
        while cursor is not None:
            parent, step = prev[cursor]
            if step is not None:
                steps.append(step)
            zone_nodes.append(nodes[cursor[0]])
            cursor = parent
        steps.reverse()
        zone_nodes.reverse()

        final_walk = dest_access[state[0]]
        steps.append(TripStep(mode="walk", from_name=nodes[state[0]]["name"],
                              to_name="", duration_min=final_walk))

        signature = "|".join(f"{s.mode}:{s.line}:{s.from_name}->{s.to_name}"
                             for s in steps)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        ride_steps = [s for s in steps if s.mode != "walk"]
        if not ride_steps:
            continue

        options.append(TripOption(
            steps=steps,
            total_time_min=total,
            transfers=max(0, len(ride_steps) - 1),
            zones=_collect_zones(*zone_nodes),
            estimated=True,
            source=SOURCE_ESTIMATE,
        ))
        if len(options) >= max_options:
            break

    return options


def plan_trip_from_coords(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
) -> list[TripOption]:
    """OFFLINE ESTIMATE: plan a trip between two sets of coordinates.

    This is the fallback planner. It has no timetable: ride times come from
    straight-line distance and average speeds, and **waiting time is not
    modelled at all**. Every returned option is flagged ``estimated=True`` so
    callers can label it accordingly. Prefer
    :func:`plan_trip_from_coords_async`, which uses real schedules.

    Returns a list of TripOption sorted by total_time_min (fastest first).
    """
    radius = MAX_WALK_M / 1000  # convert to km

    origin_nodes = _get_nearby_all(origin_lat, origin_lon, radius_km=radius)
    dest_nodes = _get_nearby_all(dest_lat, dest_lon, radius_km=radius)

    if not origin_nodes or not dest_nodes:
        return []

    options: list[TripOption] = []

    # Try all single-mode direct routes
    for o_node in origin_nodes[:5]:
        o_walk = _walk_time(o_node["dist_km"])
        for d_node in dest_nodes[:5]:
            d_walk = _walk_time(d_node["dist_km"])

            if o_node["type"] == "metro" and d_node["type"] == "metro":
                opt = _build_direct_metro(o_node, d_node, o_walk, d_walk)
                if opt:
                    options.append(opt)
                # Also try with transfer
                opt = _build_metro_with_transfer(o_node, d_node, o_walk, d_walk)
                if opt:
                    options.append(opt)

            if o_node["type"] == "train" and d_node["type"] == "train":
                opt = _build_direct_train(o_node, d_node, o_walk, d_walk)
                if opt:
                    options.append(opt)

            if o_node["type"] == "metrobus" and d_node["type"] == "metrobus":
                opt = _build_direct_metrobus(o_node, d_node, o_walk, d_walk)
                if opt:
                    options.append(opt)

    # Network search: any number of legs / modes, up to MAX_GRAPH_TRANSFERS.
    try:
        options.extend(_plan_graph(origin_lat, origin_lon, dest_lat, dest_lon))
    except Exception:
        logger.exception("Offline network search failed")

    # Deduplicate similar options (same sequence of modes and lines)
    seen: set[str] = set()
    unique: list[TripOption] = []
    for opt in options:
        key = "|".join(f"{s.mode}:{s.line}:{s.from_name}->{s.to_name}" for s in opt.steps)
        if key not in seen:
            seen.add(key)
            unique.append(opt)

    # Sort by total time
    unique.sort(key=lambda o: (o.total_time_min, o.transfers))
    return unique[:5]


def plan_trip(origin_text: str, dest_text: str) -> list[TripOption]:
    """OFFLINE ESTIMATE: plan a trip between two text-described locations.

    Resolves the locations first, then delegates to plan_trip_from_coords.
    Returns a list of TripOption sorted by total_time_min (fastest first).
    """
    origin = resolve_location(origin_text)
    dest = resolve_location(dest_text)

    if not origin or not dest:
        return []

    return plan_trip_from_coords(
        origin["lat"], origin["lon"],
        dest["lat"], dest["lon"],
    )


# ===================================================================
# MOTIS — real, timetable-backed planning
# ===================================================================

def _motis_mode(leg: dict) -> str:
    """Map a MOTIS leg onto one of our internal transport modes."""
    agency = (leg.get("agencyName") or "").lower()
    for fragment, mode in _AGENCY_MODE_HINTS:
        if fragment in agency:
            return mode
    return _MOTIS_MODE_MAP.get((leg.get("mode") or "").upper(), "bus")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _local_hhmm(value: str) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return ""
    return parsed.astimezone(PORTO_TZ).strftime("%H:%M")


def _leg_line_name(leg: dict) -> str:
    """Human line label for a MOTIS transit leg."""
    for key in ("routeShortName", "displayName", "routeLongName", "tripShortName"):
        value = leg.get(key)
        if value:
            return str(value)
    return ""


def _parse_motis_itinerary(itinerary: dict) -> TripOption | None:
    """Convert one MOTIS itinerary into a :class:`TripOption`."""
    legs = itinerary.get("legs") or []
    if not legs:
        return None

    steps: list[TripStep] = []
    previous_arrival: datetime | None = None
    transit_legs = 0

    for leg in legs:
        mode = _motis_mode(leg)
        duration_s = leg.get("duration") or 0
        duration_min = max(1, round(duration_s / 60)) if duration_s else 0
        from_name = (leg.get("from") or {}).get("name") or ""
        to_name = (leg.get("to") or {}).get("name") or ""
        start = _parse_iso(leg.get("startTime", ""))
        end = _parse_iso(leg.get("endTime", ""))

        # MOTIS "START"/"END" placeholders are not real stop names.
        if from_name.upper() == "START":
            from_name = ""
        if to_name.upper() == "END":
            to_name = ""

        wait_min = 0
        if mode != "walk" and previous_arrival is not None and start is not None:
            wait_min = max(0, round((start - previous_arrival).total_seconds() / 60))

        if mode == "walk":
            steps.append(TripStep(
                mode="walk",
                from_name=from_name,
                to_name=to_name,
                duration_min=duration_min or 1,
                departure_time=_local_hhmm(leg.get("startTime", "")),
                arrival_time=_local_hhmm(leg.get("endTime", "")),
            ))
        else:
            transit_legs += 1
            steps.append(TripStep(
                mode=mode,
                from_name=from_name,
                to_name=to_name,
                line=_leg_line_name(leg),
                duration_min=duration_min or 1,
                direction=leg.get("headsign") or "",
                departure_time=_local_hhmm(leg.get("startTime", "")),
                arrival_time=_local_hhmm(leg.get("endTime", "")),
                wait_min=wait_min,
            ))

        if end is not None:
            previous_arrival = end

    if not steps:
        return None

    duration_s = itinerary.get("duration") or 0
    total_min = max(1, round(duration_s / 60)) if duration_s else sum(
        s.duration_min for s in steps)

    transfers = itinerary.get("transfers")
    if not isinstance(transfers, int) or transfers < 0:
        transfers = max(0, transit_legs - 1)

    return TripOption(
        steps=steps,
        total_time_min=total_min,
        transfers=transfers,
        zones=[],
        estimated=False,
        source=SOURCE_MOTIS,
        departure_time=_local_hhmm(itinerary.get("startTime", "")),
        arrival_time=_local_hhmm(itinerary.get("endTime", "")),
    )


async def motis_plan(origin_lat: float, origin_lon: float,
                     dest_lat: float, dest_lon: float,
                     when: datetime | None = None,
                     num_itineraries: int = 4) -> list[TripOption] | None:
    """Query the MOTIS ``/api/v1/plan`` endpoint.

    Returns a list of options, ``[]`` when MOTIS answered but found nothing, and
    ``None`` when MOTIS could not be reached at all (so the caller can fall back
    to the offline estimator and say so).
    """
    if not is_valid_porto_coords(origin_lat, origin_lon):
        return None
    if not is_valid_porto_coords(dest_lat, dest_lon):
        return None

    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=PORTO_TZ)

    params = {
        "fromPlace": f"{origin_lat},{origin_lon}",
        "toPlace": f"{dest_lat},{dest_lon}",
        "time": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arriveBy": "false",
        "numItineraries": str(num_itineraries),
    }

    try:
        async with httpx.AsyncClient(timeout=MOTIS_TIMEOUT) as client:
            resp = await client.get(
                MOTIS_PLAN_URL,
                params=params,
                headers={"User-Agent": MOTIS_USER_AGENT},
            )
        if resp.status_code != 200:
            logger.warning("MOTIS /plan returned HTTP %d", resp.status_code)
            return None
        payload = resp.json()
    except Exception:
        logger.info("MOTIS /plan request failed", exc_info=True)
        return None

    itineraries = payload.get("itineraries")
    if itineraries is None:
        logger.warning("MOTIS /plan answered without an 'itineraries' key")
        return None

    options: list[TripOption] = []
    for itinerary in itineraries:
        parsed = _parse_motis_itinerary(itinerary)
        if parsed is not None:
            options.append(parsed)

    options.sort(key=lambda o: (o.total_time_min, o.transfers))
    return options


async def plan_trip_from_coords_async(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    when: datetime | None = None,
) -> list[TripOption]:
    """Plan a trip using real timetables, falling back to the offline estimator.

    MOTIS covers STCP buses, Metro do Porto and CP trains together, with real
    departure times, waiting times and transfers.  When it is unreachable the
    haversine estimator takes over and its options carry ``estimated=True``.
    """
    options = await motis_plan(origin_lat, origin_lon, dest_lat, dest_lon, when=when)
    if options:
        return options[:5]

    if options == []:
        logger.info("MOTIS found no itinerary; trying the offline estimator")

    return plan_trip_from_coords(origin_lat, origin_lon, dest_lat, dest_lon)


async def plan_trip_async(origin_text: str, dest_text: str) -> list[TripOption]:
    """Text-based variant of :func:`plan_trip_from_coords_async`."""
    origin = await resolve_location_any(origin_text)
    dest = await resolve_location_any(dest_text)
    if not origin or not dest:
        return []
    return await plan_trip_from_coords_async(
        origin["lat"], origin["lon"], dest["lat"], dest["lon"],
    )
