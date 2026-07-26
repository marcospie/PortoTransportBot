"""Accessibility information for Porto metro stations.

What this module may and may not claim
--------------------------------------
It previously hardcoded a list of five stations whose lifts were supposedly
"under maintenance", with no source and no expiry date.  Passengers with reduced
mobility could plan around that invented status, so it has been removed.

There is no public real-time lift/escalator status feed for Metro do Porto
(checked 2026-07-26: the site publishes no such API, and the GTFS feed carries
no ``wheelchair_boarding`` outage information), therefore this module reports
only the **network-wide design standard** that Metro do Porto publishes for its
stations, together with an explicit data-source note, the date that source was
consulted, and a pointer to official channels for live information.

:func:`has_live_elevator_status` returns ``False`` for exactly this reason —
callers must not present the feature flags as live status.
"""

import logging

from bot.services.metro import STATIONS

logger = logging.getLogger(__name__)

# Provenance for everything in this module.
DATA_SOURCE = "Metro do Porto"
DATA_SOURCE_URL = "https://www.metrodoporto.pt"
DATA_SOURCE_DATE = "2026-07-26"

# There is no public live lift-status feed. Keep this False until one exists.
LIVE_ELEVATOR_STATUS_AVAILABLE = False

# Official customer-information channels, offered instead of invented status.
OFFICIAL_INFO_PT = "metrodoporto.pt · Linha Azul 225 081 000"
OFFICIAL_INFO_EN = "metrodoporto.pt · customer line 225 081 000"

_NOTE_PT = (
    "Rede concebida com acesso sem degraus em todas as estações "
    f"(fonte: {DATA_SOURCE}, consultado em {DATA_SOURCE_DATE}). "
    "O estado dos elevadores em tempo real não é verificado por este bot — "
    f"confirma em {OFFICIAL_INFO_PT}."
)
_NOTE_EN = (
    "Step-free access is part of the network design at every station "
    f"(source: {DATA_SOURCE}, retrieved {DATA_SOURCE_DATE}). "
    "Live lift status is not verified by this bot — "
    f"please check {OFFICIAL_INFO_EN}."
)

# Network-wide accessibility standard published by Metro do Porto. These are
# properties of the network, not per-station live measurements; every station
# therefore carries the same values plus the provenance note above.
ACCESSIBILITY: dict[str, dict] = {}

for _station_name in STATIONS:
    ACCESSIBILITY[_station_name] = {
        # Backward-compatible feature keys used by the handler.
        "elevator": True,
        # NOT a live reading: "operational" here means step-free access is
        # provided at this station by design. See has_live_elevator_status().
        "elevator_status": "operational",
        "ramp": True,
        "tactile": True,
        "audio": True,
        "accessible_machines": True,
        "wheelchair_spaces": True,
        # Explicit provenance so nothing here reads as verified live status.
        "step_free": True,
        "live_status_available": LIVE_ELEVATOR_STATUS_AVAILABLE,
        "verified_live": False,
        "data_source": DATA_SOURCE,
        "data_source_url": DATA_SOURCE_URL,
        "data_date": DATA_SOURCE_DATE,
        "notes_pt": _NOTE_PT,
        "notes_en": _NOTE_EN,
    }


def has_live_elevator_status() -> bool:
    """Whether real lift-outage data is available.

    Always ``False`` today: no public feed exists.  Callers should use this to
    decide between "no lifts reported out of service" (which we cannot know)
    and "lift status is not available — check with the operator".
    """
    return LIVE_ELEVATOR_STATUS_AVAILABLE


def get_data_source_note(lang: str = "pt") -> str:
    """Return the plain-text provenance note shown with accessibility data."""
    return _NOTE_EN if lang == "en" else _NOTE_PT


def get_station_accessibility(name: str) -> dict | None:
    """Get accessibility information for a specific station.

    Args:
        name: Station name (case-insensitive and fuzzy search supported).

    Returns:
        Dict with the network accessibility standard, provenance fields and the
        station name, or None if the station is unknown.
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
    """Search for stations by accessibility feature.

    Args:
        feature_type: One of 'elevator_ok', 'elevator_maintenance',
                      'ramp', 'tactile', 'audio', 'accessible_machines',
                      'wheelchair_spaces', 'step_free'.

    Returns:
        List of dicts with matching station data.  ``elevator_maintenance``
        always returns an empty list: no live outage source exists, so claiming
        a station's lift is out of service would be fabrication. Check
        :func:`has_live_elevator_status` before presenting that emptiness as
        "no lifts out of service".
    """
    if feature_type == "elevator_maintenance":
        if not LIVE_ELEVATOR_STATUS_AVAILABLE:
            logger.debug(
                "elevator_maintenance queried but no live lift-status source "
                "is available; returning empty list"
            )
        return []

    results = []
    for station_name, data in ACCESSIBILITY.items():
        if feature_type == "elevator_ok":
            match = data["elevator"] and data["elevator_status"] == "operational"
        elif feature_type in ("ramp", "tactile", "audio", "accessible_machines",
                              "wheelchair_spaces", "step_free"):
            match = data.get(feature_type, False)
        else:
            match = False
        if match:
            results.append({"name": station_name, **data})
    return results
