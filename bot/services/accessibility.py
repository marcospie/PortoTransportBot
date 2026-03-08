"""Service for accessibility information at Porto metro stations.

Provides hardcoded accessibility data for all Metro do Porto stations,
including elevator status, ramps, tactile guidance, audio announcements,
and accessible ticket machines.
"""

import logging

from bot.services.metro import STATIONS

logger = logging.getLogger(__name__)

# Stations with elevators currently under maintenance
_MAINTENANCE_STATIONS = {
    "Bolhão",
    "Heroísmo",
    "Salgueiros",
    "Rio Tinto",
    "Póvoa de Varzim",
}

# Accessibility data for all Metro do Porto stations
# All Porto metro stations have elevators, ramps, tactile guidance,
# audio announcements, and accessible ticket machines by design.
ACCESSIBILITY: dict[str, dict] = {}

for _station_name in STATIONS:
    _in_maintenance = _station_name in _MAINTENANCE_STATIONS
    ACCESSIBILITY[_station_name] = {
        "elevator": True,
        "elevator_status": "maintenance" if _in_maintenance else "operational",
        "ramp": True,
        "tactile": True,
        "audio": True,
        "accessible_machines": True,
        "wheelchair_spaces": True,
        "notes_pt": "Elevador em manutenção. Use a rampa de acesso alternativa." if _in_maintenance else "",
        "notes_en": "Elevator under maintenance. Use the alternative access ramp." if _in_maintenance else "",
    }


def get_station_accessibility(name: str) -> dict | None:
    """Get accessibility information for a specific station.

    Args:
        name: Station name (case-insensitive search supported).

    Returns:
        Dict with accessibility data and station name, or None if not found.
    """
    # Exact match first
    if name in ACCESSIBILITY:
        return {"name": name, **ACCESSIBILITY[name]}

    # Case-insensitive match
    name_lower = name.lower()
    for station_name, data in ACCESSIBILITY.items():
        if station_name.lower() == name_lower:
            return {"name": station_name, **data}

    # Fuzzy search
    from bot.utils.search import fuzzy_search
    matches = fuzzy_search(name, list(ACCESSIBILITY.keys()), min_score=60, max_results=1)
    if matches:
        matched_name = matches[0][0]
        return {"name": matched_name, **ACCESSIBILITY[matched_name]}

    return None


def get_accessible_stations() -> list[dict]:
    """Get accessibility info for all metro stations.

    Returns:
        List of dicts with station name and accessibility data.
    """
    results = []
    for station_name, data in ACCESSIBILITY.items():
        results.append({"name": station_name, **data})
    return results


def search_accessible_features(feature_type: str) -> list[dict]:
    """Search for stations by accessibility feature status.

    Args:
        feature_type: One of 'elevator_ok', 'elevator_maintenance',
                      'ramp', 'tactile', 'audio', 'accessible_machines',
                      'wheelchair_spaces'.

    Returns:
        List of dicts with matching station data.
    """
    results = []
    for station_name, data in ACCESSIBILITY.items():
        match = False
        if feature_type == "elevator_ok":
            match = data["elevator"] and data["elevator_status"] == "operational"
        elif feature_type == "elevator_maintenance":
            match = data["elevator"] and data["elevator_status"] == "maintenance"
        elif feature_type in ("ramp", "tactile", "audio", "accessible_machines", "wheelchair_spaces"):
            match = data.get(feature_type, False)
        if match:
            results.append({"name": station_name, **data})
    return results
