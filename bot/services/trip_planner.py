"""Multimodal trip planning engine for Porto public transport.

Finds routes using any combination of metro, bus, train and metrobus,
ranking options by estimated journey time.
"""

import logging
import math
from dataclasses import dataclass, field

from bot.services.metro import (
    STATIONS as METRO_STATIONS,
    search_stations as metro_search,
    get_nearby_stations as metro_nearby,
)
from bot.services.cp import (
    STATIONS as CP_STATIONS,
    search_stations as cp_search,
    get_nearby_stations as cp_nearby,
    CP_LINES,
)
from bot.services.metrobus import (
    STOPS as METROBUS_STOPS,
    search_stops as metrobus_search,
    get_nearby_stops as metrobus_nearby,
    METROBUS_LINES,
)
from bot.config import METRO_LINES

logger = logging.getLogger(__name__)

# Walking speed: ~5 km/h -> ~80 m/min
WALK_SPEED_M_PER_MIN = 80

# Average speeds in km/h for time estimation
AVERAGE_SPEEDS = {
    "metro": 30,
    "bus": 15,
    "train": 50,
    "metrobus": 20,
}

# Maximum walking distance to consider a stop reachable (metres)
MAX_WALK_M = 1500


@dataclass
class TripStep:
    """A single step in a trip."""
    mode: str  # walk, metro, bus, train, metrobus
    from_name: str
    to_name: str
    line: str = ""
    duration_min: int = 0
    direction: str = ""


@dataclass
class TripOption:
    """A complete trip option from origin to destination."""
    steps: list[TripStep] = field(default_factory=list)
    total_time_min: int = 0
    transfers: int = 0
    zones: list[str] = field(default_factory=list)


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
    line_info = METRO_LINES.get(line_code, {})
    line_name = line_info.get("name", f"Linha {line_code}")

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "metro")

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    # Determine direction from line route
    route = line_info.get("route", "")
    endpoints = route.split(" ↔ ") if " ↔ " in route else ["", ""]
    direction = endpoints[-1]  # default

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

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones)


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

    line1_info = METRO_LINES.get(line1_code, {})
    line2_info = METRO_LINES.get(line2_code, {})

    dist1 = _haversine(origin_node["lat"], origin_node["lon"],
                       transfer_data["lat"], transfer_data["lon"])
    dist2 = _haversine(transfer_data["lat"], transfer_data["lon"],
                       dest_node["lat"], dest_node["lon"])

    ride1 = _ride_time(dist1, "metro")
    ride2 = _ride_time(dist2, "metro")
    transfer_time = 3  # 3 min transfer

    steps: list[TripStep] = []
    if walk_origin_min > 0:
        steps.append(TripStep(mode="walk", from_name="",
                              to_name=origin_node["name"],
                              duration_min=walk_origin_min))

    route1 = line1_info.get("route", "")
    endpoints1 = route1.split(" ↔ ") if " ↔ " in route1 else ["", ""]
    steps.append(TripStep(
        mode="metro",
        from_name=origin_node["name"],
        to_name=transfer_name,
        line=line1_info.get("name", f"Linha {line1_code}"),
        duration_min=ride1,
        direction=endpoints1[-1],
    ))

    route2 = line2_info.get("route", "")
    endpoints2 = route2.split(" ↔ ") if " ↔ " in route2 else ["", ""]
    steps.append(TripStep(
        mode="metro",
        from_name=transfer_name,
        to_name=dest_node["name"],
        line=line2_info.get("name", f"Linha {line2_code}"),
        duration_min=ride2,
        direction=endpoints2[-1],
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride1 + transfer_time + ride2 + walk_dest_min
    transfer_node = {"zone": transfer_data.get("zone", "")}
    zones = _collect_zones(origin_node, transfer_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=1, zones=zones)


def _build_direct_train(origin_node: dict, dest_node: dict,
                        walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a direct train route if both nodes share a CP line."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))
    common = o_lines & d_lines

    if not common:
        return None

    line_id = sorted(common)[0]
    line_info = CP_LINES.get(line_id, {})
    line_name = line_info.get("name", line_id)

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "train")

    route = line_info.get("route", "")
    endpoints = route.split(" ↔ ") if " ↔ " in route else ["", ""]

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
        direction=endpoints[-1],
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride_min + walk_dest_min
    zones = _collect_zones(origin_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones)


def _build_direct_metrobus(origin_node: dict, dest_node: dict,
                           walk_origin_min: int, walk_dest_min: int) -> TripOption | None:
    """Build a direct metrobus route if both nodes share a line."""
    o_lines = set(origin_node.get("lines", []))
    d_lines = set(dest_node.get("lines", []))
    common = o_lines & d_lines

    if not common:
        return None

    line_code = sorted(common)[0]
    line_info = METROBUS_LINES.get(line_code, {})
    line_name = line_info.get("name", f"Linha {line_code}")

    dist = _haversine(origin_node["lat"], origin_node["lon"],
                      dest_node["lat"], dest_node["lon"])
    ride_min = _ride_time(dist, "metrobus")

    route = line_info.get("route", "")
    endpoints = route.split(" ↔ ") if " ↔ " in route else ["", ""]

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
        direction=endpoints[-1],
    ))

    if walk_dest_min > 0:
        steps.append(TripStep(mode="walk", from_name=dest_node["name"],
                              to_name="", duration_min=walk_dest_min))

    total = walk_origin_min + ride_min + walk_dest_min
    zones = _collect_zones(origin_node, dest_node)

    return TripOption(steps=steps, total_time_min=total, transfers=0, zones=zones)


def _build_multimodal(origin_node: dict, dest_node: dict,
                      walk_origin_min: int, walk_dest_min: int,
                      mode1: str, mode2: str,
                      all_origin_nodes: list[dict],
                      all_dest_nodes: list[dict]) -> TripOption | None:
    """Build a two-mode trip (e.g. metro+bus, bus+metro, metro+train).

    Finds the best intermediate transfer point where both modes overlap.
    """
    # For mode1, find the best origin-side node
    origin_mode_nodes = [n for n in all_origin_nodes if n["type"] == mode1]
    # For mode2, find the best dest-side node
    dest_mode_nodes = [n for n in all_dest_nodes if n["type"] == mode2]

    if not origin_mode_nodes or not dest_mode_nodes:
        return None

    # Find a transfer hub: a location served by both modes
    # We look for nodes of mode2 near origin-side mode1 stations,
    # or mode1 nodes near dest-side mode2 stations
    best_option = None
    best_time = float("inf")

    # Strategy: take mode1 from origin to a hub, then mode2 from hub to dest
    # A hub is where a mode1 node and a mode2 node are close together
    for m1_node in origin_mode_nodes[:3]:  # limit search
        # Find mode2 nodes near this mode1 node
        hub_nodes = _get_nearby_all(m1_node["lat"], m1_node["lon"], radius_km=0.8)
        hub_m2 = [n for n in hub_nodes if n["type"] == mode2]

        for hub_node in hub_m2[:2]:
            # Now find if there's a dest-side node of mode2 that connects
            # The hub_node and dest_mode_nodes should share lines
            for d_node in dest_mode_nodes[:3]:
                common_lines = set(hub_node.get("lines", [])) & set(d_node.get("lines", []))
                if not common_lines:
                    continue

                # Calculate times
                walk_to_m1 = walk_origin_min if m1_node == origin_mode_nodes[0] else _walk_time(m1_node["dist_km"])
                dist1 = _haversine(m1_node["lat"], m1_node["lon"],
                                   hub_node["lat"], hub_node["lon"])

                # Check if origin node and m1_node share lines (for same-mode connection)
                o_node = origin_mode_nodes[0]
                common_m1 = set(o_node.get("lines", [])) & set(m1_node.get("lines", []))
                if mode1 == "metro" and o_node["name"] != m1_node["name"] and not common_m1:
                    continue

                ride1 = _ride_time(
                    _haversine(o_node["lat"], o_node["lon"], hub_node["lat"], hub_node["lon"]),
                    mode1
                )

                hub_walk = _walk_time(hub_node["dist_km"]) if hub_node["dist_km"] > 0.05 else 2
                dist2 = _haversine(hub_node["lat"], hub_node["lon"],
                                   d_node["lat"], d_node["lon"])
                ride2 = _ride_time(dist2, mode2)
                walk_to_dest = walk_dest_min if d_node == dest_mode_nodes[0] else _walk_time(
                    _haversine(d_node["lat"], d_node["lon"],
                               dest_node["lat"], dest_node["lon"])
                )

                total = walk_to_m1 + ride1 + hub_walk + ride2 + walk_to_dest
                if total < best_time:
                    best_time = total

                    # Determine line names
                    if mode1 == "metro":
                        o_hub_common = set(o_node.get("lines", [])) & set(m1_node.get("lines", []))
                        if not o_hub_common:
                            o_hub_common = set(o_node.get("lines", []))
                    else:
                        o_hub_common = set(o_node.get("lines", []))
                    line1_code = sorted(o_hub_common)[0] if o_hub_common else ""
                    line2_code = sorted(common_lines)[0]

                    line1_name = _get_line_name(mode1, line1_code)
                    line2_name = _get_line_name(mode2, line2_code)

                    steps: list[TripStep] = []
                    if walk_to_m1 > 0:
                        steps.append(TripStep(mode="walk", from_name="",
                                              to_name=o_node["name"],
                                              duration_min=walk_to_m1))
                    steps.append(TripStep(
                        mode=mode1,
                        from_name=o_node["name"],
                        to_name=hub_node["name"],
                        line=line1_name,
                        duration_min=ride1,
                    ))
                    steps.append(TripStep(
                        mode=mode2,
                        from_name=hub_node["name"],
                        to_name=d_node["name"],
                        line=line2_name,
                        duration_min=ride2,
                    ))
                    if walk_to_dest > 0:
                        steps.append(TripStep(mode="walk", from_name=d_node["name"],
                                              to_name="", duration_min=walk_to_dest))

                    zones = _collect_zones(o_node, hub_node, d_node)
                    best_option = TripOption(
                        steps=steps,
                        total_time_min=total,
                        transfers=1,
                        zones=zones,
                    )

    return best_option


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


def plan_trip_from_coords(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
) -> list[TripOption]:
    """Plan a trip between two sets of coordinates.

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

    # Try multimodal combinations
    multimodal_combos = [
        ("metro", "train"),
        ("train", "metro"),
        ("metro", "metrobus"),
        ("metrobus", "metro"),
    ]
    for mode1, mode2 in multimodal_combos:
        o_node = origin_nodes[0]
        d_node = dest_nodes[0]
        o_walk = _walk_time(o_node["dist_km"])
        d_walk = _walk_time(d_node["dist_km"])
        opt = _build_multimodal(
            o_node, d_node, o_walk, d_walk, mode1, mode2,
            origin_nodes, dest_nodes,
        )
        if opt:
            options.append(opt)

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
    """Plan a trip between two text-described locations.

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
