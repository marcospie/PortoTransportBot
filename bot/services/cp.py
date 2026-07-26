"""Service for CP Comboios de Portugal train data in the Porto area.

Departures are **real** and come from CP's own published timetable.

The data source is the MOTIS transit API at ``https://europe.motis-project.de``,
the same open-source instance the metro service already uses.  MOTIS ingests
CP's official GTFS feed (``pt_Comboios-de-Portugal(CP).gtfs.zip``, agency
``1094_CP``), so ``/api/v1/stoptimes`` returns the actual next trains at a
station -- with the real headsign (destination), the real line name and the
real scheduled minute -- in a single request.

Verified 2026-07-26:

* ``GET /api/v1/geocode?text=Porto-Campanhã`` -> HTTP 200, returns the CP stop
  id ``pt-Comboios-de-Portugal(CP)_94_2006``.
* ``GET /api/v1/stoptimes?stopId=pt-Comboios-de-Portugal(CP)_94_2006`` ->
  HTTP 200, returns ``stopTimes`` with ``routeShortName`` ("Linha de Aveiro",
  "Linha do Marco", "IR", "IC", ...), ``headsign``, ``directionId`` and
  ``place.departure``.

Fallback chain used by :func:`get_next_departures_async`:

1. MOTIS ``stoptimes`` for the station's known CP stop id (real timetable).
2. MOTIS ``geocode`` to discover a stop id at runtime for stations missing
   from :data:`MOTIS_STOP_IDS`, then step 1 again.
3. :func:`get_next_departures` -- a *typical frequency* description.  This
   deliberately does **not** invent a departure minute; it reports the usual
   interval and is labelled as an estimate so the UI can say so out loud.

Anything user-visible produced by step 3 carries ``estimated=True`` and an
``interval_min`` so the handler can render an honest "typical frequency, not a
real timetable" message.
"""

import logging
import math
import unicodedata
from datetime import datetime, time, timezone

import aiohttp

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

#: Cache for MOTIS responses (departures move fast, keep it short).
_cache = TTLCache(default_ttl=90)

# ---------------------------------------------------------------------------
# MOTIS (real CP timetable) configuration
# ---------------------------------------------------------------------------

MOTIS_BASE_URL = "https://europe.motis-project.de/api/v1"
MOTIS_STOPTIMES_URL = f"{MOTIS_BASE_URL}/stoptimes"
MOTIS_GEOCODE_URL = f"{MOTIS_BASE_URL}/geocode"

#: Seconds before a MOTIS request is abandoned and the fallback kicks in.
MOTIS_TIMEOUT = 8.0

#: Prefix of every stop id belonging to CP's GTFS feed inside MOTIS.
MOTIS_CP_STOP_PREFIX = "pt-Comboios-de-Portugal"

#: Substrings identifying CP as the operating agency in a MOTIS stoptime.
_CP_AGENCY_HINTS = ("comboios de portugal", "1094_cp")

# Station name -> MOTIS stop id, resolved via the MOTIS geocode endpoint and
# cross-checked against the stop sequences of real CP trips.
MOTIS_STOP_IDS: dict[str, str] = {
    "Porto-Campanha": "pt-Comboios-de-Portugal(CP)_94_2006",
    "Porto-São Bento": "pt-Comboios-de-Portugal(CP)_94_1008",
    "Ermesinde": "pt-Comboios-de-Portugal(CP)_94_4002",
    "Contumil": "pt-Comboios-de-Portugal(CP)_94_3004",
    "Rio Tinto": "pt-Comboios-de-Portugal(CP)_94_3038",
    "Valongo": "pt-Comboios-de-Portugal(CP)_94_8086",
    "General Torres": "pt-Comboios-de-Portugal(CP)_94_39172",
    "Espinho": "pt-Comboios-de-Portugal(CP)_94_39008",
    "Aveiro": "pt-Comboios-de-Portugal(CP)_94_38000",
    "Braga": "pt-Comboios-de-Portugal(CP)_94_29157",
    "Guimarães": "pt-Comboios-de-Portugal(CP)_94_24000",
    "Marco de Canaveses": "pt-Comboios-de-Portugal(CP)_94_9001",
    "Caíde": "pt-Comboios-de-Portugal(CP)_94_8383",
    "Paredes": "pt-Comboios-de-Portugal(CP)_94_8276",
    "Penafiel": "pt-Comboios-de-Portugal(CP)_94_8318",
    "Nine": "pt-Comboios-de-Portugal(CP)_94_6007",
    "Viana do Castelo": "pt-Comboios-de-Portugal(CP)_94_18002",
    "Granja": "pt-Comboios-de-Portugal(CP)_94_39040",
    "Espinho-Vouga": "pt-Comboios-de-Portugal(CP)_94_44016",
    "Miramar": "pt-Comboios-de-Portugal(CP)_94_39073",
    "Valadares": "pt-Comboios-de-Portugal(CP)_94_39115",
    "Cete": "pt-Comboios-de-Portugal(CP)_94_8227",
    "Lordelo": "pt-Comboios-de-Portugal(CP)_94_28191",
    "Recarei - Sobreira": "pt-Comboios-de-Portugal(CP)_94_8177",
    "São Romão": "pt-Comboios-de-Portugal(CP)_94_4077",
    "Leça do Balio": "pt-Comboios-de-Portugal(CP)_94_21071",
    "São Gemil": "pt-Comboios-de-Portugal(CP)_94_21006",
    "Trofa": "pt-Comboios-de-Portugal(CP)_94_4630",
    "Lousado": "pt-Comboios-de-Portugal(CP)_94_5009",
    "Vizela": "pt-Comboios-de-Portugal(CP)_94_28233",
    "Santo Tirso": "pt-Comboios-de-Portugal(CP)_94_28068",
    # "São Félix da Marinha" is intentionally absent: CP has no station with
    # that name (the stop at those coordinates is Aguda), so it can only ever
    # be served by the honest frequency estimate.
}

# CP route names as they appear in MOTIS (accent-free) -> our line ids.
_ROUTE_NAME_TO_LINE: dict[str, str] = {
    "linha de aveiro": "aveiro",
    "linha de braga": "braga",
    "linha de guimaraes": "guimaraes",
    "linha do marco": "marco",
    "linha do minho": "minho",
    "linha de leixoes": "leixoes",
}

# CP long-distance / regional service codes -> readable label.
_SERVICE_LABELS: dict[str, str] = {
    "AP": "Alfa Pendular",
    "IC": "Intercidades",
    "IR": "Inter-Regional",
    "R": "Regional",
    "U": "Urbano",
    "CP": "CP",
}

# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

# CP train lines serving the Porto area.  Routes describe the real terminals
# of the services CP actually runs (checked against its GTFS feed).
CP_LINES = {
    "aveiro": {
        "name": "Linha de Aveiro",
        "emoji": "\U0001f7e2",  # green circle
        "route": "São Bento ↔ Campanhã ↔ Espinho ↔ Aveiro",
        "type": "urbano",
    },
    "braga": {
        "name": "Linha de Braga",
        "emoji": "\U0001f535",  # blue circle
        "route": "São Bento ↔ Campanhã ↔ Ermesinde ↔ Braga",
        "type": "urbano",
    },
    "guimaraes": {
        "name": "Linha de Guimarães",
        "emoji": "\U0001f7e1",  # yellow circle
        "route": "São Bento ↔ Campanhã ↔ Ermesinde ↔ Guimarães",
        "type": "urbano",
    },
    "marco": {
        "name": "Linha do Marco",
        "emoji": "\U0001f7e0",  # orange circle
        "route": "São Bento ↔ Campanhã ↔ Caíde ↔ Marco de Canaveses",
        "type": "urbano",
    },
    "minho": {
        "name": "Linha do Minho",
        "emoji": "\U0001f534",  # red circle
        "route": "Campanhã ↔ Nine ↔ Viana do Castelo",
        "type": "regional",
    },
    "leixoes": {
        "name": "Linha de Leixões",
        "emoji": "\U0001f7e4",  # brown circle
        "route": "Leça do Balio ↔ Campanhã ↔ Espinho ↔ Aveiro",
        "type": "urbano",
    },
}

# Real station order along each line, taken from the stop sequence of actual
# CP trips (MOTIS ``/api/v1/trip``), restricted to the stations this bot knows
# about.  This -- not dict insertion order -- is what the line map renders and
# what tells us which way a train is heading from a given station.
LINE_STATION_ORDER: dict[str, list[str]] = {
    "aveiro": [
        "Porto-São Bento",
        "Porto-Campanha",
        "General Torres",
        "Valadares",
        "Miramar",
        "São Félix da Marinha",
        "Granja",
        "Espinho",
        "Espinho-Vouga",
        "Aveiro",
    ],
    "braga": [
        "Porto-São Bento",
        "Porto-Campanha",
        "Contumil",
        "Rio Tinto",
        "Ermesinde",
        "São Romão",
        "Trofa",
        "Lousado",
        "Nine",
        "Braga",
    ],
    "guimaraes": [
        "Porto-São Bento",
        "Porto-Campanha",
        "Contumil",
        "Rio Tinto",
        "Ermesinde",
        "São Romão",
        "Trofa",
        "Lousado",
        "Santo Tirso",
        "Lordelo",
        "Vizela",
        "Guimarães",
    ],
    "marco": [
        "Porto-São Bento",
        "Porto-Campanha",
        "Contumil",
        "Rio Tinto",
        "Ermesinde",
        "Valongo",
        "Recarei - Sobreira",
        "Cete",
        "Paredes",
        "Penafiel",
        "Caíde",
        "Marco de Canaveses",
    ],
    "minho": [
        "Porto-Campanha",
        "Ermesinde",
        "Trofa",
        "Nine",
        "Viana do Castelo",
    ],
    "leixoes": [
        "Leça do Balio",
        "São Gemil",
        "Contumil",
        "Porto-Campanha",
        "General Torres",
        "Valadares",
        "Miramar",
        "Granja",
        "Espinho",
        "Aveiro",
    ],
}

# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------

# Porto-area CP stations.  Coordinates come from CP's GTFS feed (several of the
# previous hand-typed values were 5-20 km off, which sent the "map" button and
# the nearby search to the wrong place).
#
# ``lines`` is derived from LINE_STATION_ORDER below so membership and order can
# never drift apart again.
STATIONS: dict[str, dict] = {
    "Porto-Campanha": {"lat": 41.148720, "lon": -8.584835},
    "Porto-São Bento": {"lat": 41.145565, "lon": -8.610221},
    "Ermesinde": {"lat": 41.217037, "lon": -8.554193},
    "Contumil": {"lat": 41.168713, "lon": -8.574778},
    "Rio Tinto": {"lat": 41.184593, "lon": -8.557096},
    "Valongo": {"lat": 41.188260, "lon": -8.487370},
    "General Torres": {"lat": 41.133232, "lon": -8.608435},
    "Espinho": {"lat": 41.006510, "lon": -8.644346},
    "Aveiro": {"lat": 40.643425, "lon": -8.640761},
    "Braga": {"lat": 41.548595, "lon": -8.434369},
    "Guimarães": {"lat": 41.435110, "lon": -8.293786},
    "Marco de Canaveses": {"lat": 41.180960, "lon": -8.136875},
    "Caíde": {"lat": 41.252556, "lon": -8.226812},
    "Paredes": {"lat": 41.203873, "lon": -8.324093},
    "Penafiel": {"lat": 41.217760, "lon": -8.294932},
    "Nine": {"lat": 41.455460, "lon": -8.545069},
    "Viana do Castelo": {"lat": 41.695175, "lon": -8.831417},
    "Granja": {"lat": 41.038470, "lon": -8.647104},
    "Espinho-Vouga": {"lat": 41.002148, "lon": -8.643480},
    "São Félix da Marinha": {"lat": 41.050808, "lon": -8.651249},
    "Miramar": {"lat": 41.067820, "lon": -8.649449},
    "Valadares": {"lat": 41.099228, "lon": -8.632000},
    "Cete": {"lat": 41.172203, "lon": -8.354048},
    "Lordelo": {"lat": 41.365467, "lon": -8.363733},
    "Recarei - Sobreira": {"lat": 41.153780, "lon": -8.399092},
    "São Romão": {"lat": 41.278255, "lon": -8.553094},
    "Leça do Balio": {"lat": 41.208424, "lon": -8.629551},
    "São Gemil": {"lat": 41.197197, "lon": -8.579095},
    "Trofa": {"lat": 41.337437, "lon": -8.547573},
    "Lousado": {"lat": 41.351250, "lon": -8.526194},
    "Vizela": {"lat": 41.379074, "lon": -8.312387},
    "Santo Tirso": {"lat": 41.350815, "lon": -8.473167},
}

# Properly accented / official names for stations whose dict key is kept for
# backwards compatibility with existing callback data and stored favourites.
DISPLAY_NAMES: dict[str, str] = {
    "Porto-Campanha": "Porto-Campanhã",
}

# Misspellings, alternative spellings and names used by other modules, mapped
# to the canonical station key.  Resolution goes exact -> alias -> accent and
# punctuation insensitive -> fuzzy, so a typo can no longer make a lookup fall
# through to fuzzy matching and silently pick a *different* station.
STATION_ALIASES: dict[str, str] = {
    # Porto-Campanhã: the accented spelling used by zones.py / trip_planner.
    "Porto-Campanhã": "Porto-Campanha",
    "Campanhã": "Porto-Campanha",
    "Campanha": "Porto-Campanha",
    "Porto Campanha": "Porto-Campanha",
    "Porto Campanhã": "Porto-Campanha",
    # Porto-São Bento
    "São Bento": "Porto-São Bento",
    "Porto São Bento": "Porto-São Bento",
    "Porto-Sao Bento": "Porto-São Bento",
    # "Lousãdo" was a typo for Lousado.
    "Lousãdo": "Lousado",
    # "Receão" was a corruption of Recarei - Sobreira (the station that really
    # sits at those coordinates, between Valongo and Cete on the Douro line).
    # "Receção" is the spelling zones.py currently uses.
    "Receão": "Recarei - Sobreira",
    "Receção": "Recarei - Sobreira",
    "Recarei": "Recarei - Sobreira",
    "Sobreira": "Recarei - Sobreira",
    # Other spellings seen in the wild.
    "Caide": "Caíde",
    "Caíde de Rei": "Caíde",
    "Leça": "Leça do Balio",
    "Espinho Vouga": "Espinho-Vouga",
}

# Typical frequencies (minutes between trains).  These are *estimates*, only
# ever used by the honest fallback in :func:`get_next_departures`.
FREQUENCIES = {
    "peak": {"aveiro": 30, "braga": 30, "guimaraes": 30, "marco": 60,
             "minho": 120, "leixoes": 60},
    "off_peak": {"aveiro": 60, "braga": 60, "guimaraes": 60, "marco": 90,
                 "minho": 180, "leixoes": 60},
    "weekend": {"aveiro": 60, "braga": 60, "guimaraes": 60, "marco": 120,
                "minho": 180, "leixoes": 120},
}

# Operating hours
OPERATING_HOURS = {"start": time(5, 30), "end": time(0, 30)}

#: Direction label used when the service is closed (kept for handler compat).
CLOSED_DIRECTION = "Serviço encerrado"


def _normalize(name: str) -> str:
    """Lower-case, strip accents and punctuation for tolerant name matching."""
    if not isinstance(name, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = "".join(
        c if c.isalnum() or c.isspace() else " " for c in stripped.lower()
    )
    return " ".join(cleaned.split())


def _build_line_membership() -> None:
    """Derive ``STATIONS[name]["lines"]`` from :data:`LINE_STATION_ORDER`."""
    for data in STATIONS.values():
        data["lines"] = []
    for line_id, ordered in LINE_STATION_ORDER.items():
        for station_name in ordered:
            data = STATIONS.get(station_name)
            if data is None:
                logger.warning("Line %s references unknown station %s",
                               line_id, station_name)
                continue
            if line_id not in data["lines"]:
                data["lines"].append(line_id)


_build_line_membership()

# Normalised index over canonical names *and* aliases, built once at import.
_NORMALIZED_INDEX: dict[str, str] = {}
for _name in STATIONS:
    _NORMALIZED_INDEX[_normalize(_name)] = _name
for _display_key, _display in DISPLAY_NAMES.items():
    _NORMALIZED_INDEX.setdefault(_normalize(_display), _display_key)
for _alias, _target in STATION_ALIASES.items():
    if _target in STATIONS:
        _NORMALIZED_INDEX.setdefault(_normalize(_alias), _target)


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

def resolve_station_name(name: str) -> str | None:
    """Resolve any spelling of a station to its canonical key.

    Tries, in order: exact key, explicit alias, accent/punctuation-insensitive
    match.  Returns ``None`` when nothing matches (callers that want fuzzy
    matching on top should use :func:`_resolve_or_fuzzy`).
    """
    if not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate:
        return None
    if candidate in STATIONS:
        return candidate
    alias = STATION_ALIASES.get(candidate)
    if alias in STATIONS:
        return alias
    return _NORMALIZED_INDEX.get(_normalize(candidate))


def _resolve_or_fuzzy(name: str, min_score: int = 40) -> str | None:
    """Resolve a name exactly/by alias, falling back to fuzzy matching."""
    resolved = resolve_station_name(name)
    if resolved:
        return resolved
    if not isinstance(name, str) or not name.strip():
        return None
    from bot.utils.search import fuzzy_search
    matches = fuzzy_search(name, list(STATIONS.keys()),
                           min_score=min_score, max_results=1)
    return matches[0][0] if matches else None


def display_name(name: str) -> str:
    """Human-facing name for a station (correctly accented, official form)."""
    resolved = resolve_station_name(name)
    if resolved is None:
        return name
    return DISPLAY_NAMES.get(resolved, resolved)


def _lines_info(line_ids: list[str], detailed: bool = False) -> list[dict]:
    """Build the per-line info dicts returned by the public helpers."""
    out = []
    for line_id in line_ids:
        line_data = CP_LINES.get(line_id, {})
        entry = {
            "id": line_id,
            "name": line_data.get("name", line_id),
            "emoji": line_data.get("emoji", "\U0001f686"),
        }
        if detailed:
            entry["route"] = line_data.get("route", "")
            entry["type"] = line_data.get("type", "")
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Search / station info
# ---------------------------------------------------------------------------

def search_stations(query: str) -> list[dict]:
    """Search for CP stations by name with smart matching.

    An exact, alias or accent-insensitive hit is always returned first so that
    typing "Campanhã" can no longer be beaten by a fuzzy match on a different
    station.
    """
    from bot.utils.search import fuzzy_search

    query = query.strip() if isinstance(query, str) else ""
    if not query:
        return []

    names = [name for name, _ in
             fuzzy_search(query, list(STATIONS.keys()),
                          min_score=15, max_results=15)]

    exact = resolve_station_name(query)
    if exact:
        names = [exact] + [n for n in names if n != exact]

    results = []
    for name in names:
        data = STATIONS[name]
        results.append({
            "name": name,
            "display": DISPLAY_NAMES.get(name, name),
            "lines": _lines_info(data["lines"]),
            "lat": data["lat"],
            "lon": data["lon"],
        })

    return results


def get_station_info(name: str) -> dict | None:
    """Get detailed station information."""
    resolved = _resolve_or_fuzzy(name)
    if not resolved:
        return None
    data = STATIONS[resolved]

    return {
        "name": resolved,
        "display": DISPLAY_NAMES.get(resolved, resolved),
        "lat": data["lat"],
        "lon": data["lon"],
        "lines": _lines_info(data["lines"], detailed=True),
    }


# ---------------------------------------------------------------------------
# Real departures via MOTIS
# ---------------------------------------------------------------------------

def get_stop_id(station_name: str) -> str | None:
    """Return the MOTIS/CP stop id for a station, if we know one."""
    resolved = resolve_station_name(station_name)
    if not resolved:
        return None
    return MOTIS_STOP_IDS.get(resolved)


async def _geocode_stop_id(station_name: str) -> str | None:
    """Look a CP stop id up at runtime via the MOTIS geocode endpoint.

    Used only for stations missing from :data:`MOTIS_STOP_IDS`; results are
    cached so a miss costs at most one request per cache window.
    """
    resolved = resolve_station_name(station_name) or station_name
    cache_key = f"cp:geo:{resolved}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached or None

    text = DISPLAY_NAMES.get(resolved, resolved).replace("-", " ")
    params = {"text": text, "language": "pt"}
    try:
        timeout = aiohttp.ClientTimeout(total=MOTIS_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(MOTIS_GEOCODE_URL, params=params) as resp:
                if resp.status != 200:
                    logger.warning("MOTIS geocode returned HTTP %s for %s",
                                   resp.status, resolved)
                    return None
                payload = await resp.json(content_type=None)
    except Exception:
        logger.debug("MOTIS geocode request failed for %s", resolved,
                     exc_info=True)
        return None

    stop_id = None
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidate = item.get("id") or ""
            if (item.get("type") == "STOP"
                    and str(candidate).startswith(MOTIS_CP_STOP_PREFIX)):
                stop_id = candidate
                break

    # Cache misses too (as "") so we do not hammer geocode for stations that
    # simply do not exist in CP's feed.
    _cache.set(cache_key, stop_id or "", ttl=3600)
    return stop_id


async def _fetch_stoptimes(stop_id: str, count: int = 24,
                           now: datetime | None = None) -> list[dict]:
    """Fetch raw ``stopTimes`` entries for a CP stop id from MOTIS."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    params = {
        "stopId": stop_id,
        "time": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": str(max(1, count)),
        "arriveBy": "false",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=MOTIS_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(MOTIS_STOPTIMES_URL, params=params) as resp:
                if resp.status != 200:
                    logger.warning("MOTIS stoptimes returned HTTP %s for %s",
                                   resp.status, stop_id)
                    return []
                payload = await resp.json(content_type=None)
    except Exception:
        logger.debug("MOTIS stoptimes request failed for %s", stop_id,
                     exc_info=True)
        return []

    if not isinstance(payload, dict):
        return []
    stop_times = payload.get("stopTimes")
    return stop_times if isinstance(stop_times, list) else []


def _is_cp_service(stop_time: dict) -> bool:
    """True when a MOTIS stoptime is operated by CP (not RENFE, buses, ...)."""
    agency = str(stop_time.get("agencyName", "")).lower()
    agency_id = str(stop_time.get("agencyId", "")).lower()
    if any(hint in agency for hint in _CP_AGENCY_HINTS):
        return True
    if any(hint in agency_id for hint in _CP_AGENCY_HINTS):
        return True
    return False


def _line_label(route_short_name: str) -> tuple[str, str]:
    """Map a MOTIS ``routeShortName`` to ``(line_id, display label)``."""
    raw = (route_short_name or "").strip()
    line_id = _ROUTE_NAME_TO_LINE.get(_normalize(raw), "")
    if line_id:
        line_data = CP_LINES.get(line_id, {})
        emoji = line_data.get("emoji", "\U0001f686")
        return line_id, f"{emoji} {line_data.get('name', raw)}"

    code = raw.split()[0].upper() if raw else ""
    label = _SERVICE_LABELS.get(code)
    if label:
        return "", f"\U0001f686 {label}"
    return "", f"\U0001f686 {raw}" if raw else "\U0001f686 CP"


def _parse_stoptimes(stop_times: list[dict], line_id: str | None = None,
                     now: datetime | None = None) -> list[dict]:
    """Turn MOTIS ``stopTimes`` into departure dicts.

    Both real directions of every line appear naturally, because MOTIS returns
    one entry per trip with the trip's own headsign -- no guessing from route
    endpoints.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    departures: list[dict] = []
    seen: set[tuple] = set()

    for stop_time in stop_times:
        if not isinstance(stop_time, dict):
            continue
        if stop_time.get("cancelled") or stop_time.get("tripCancelled"):
            continue
        if not _is_cp_service(stop_time):
            continue

        place = stop_time.get("place") or {}
        dep_str = place.get("departure") or place.get("scheduledDeparture")
        if not dep_str:
            continue
        try:
            dep_dt = datetime.fromisoformat(str(dep_str).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if dep_dt.tzinfo is None:
            dep_dt = dep_dt.replace(tzinfo=timezone.utc)

        minutes_until = (dep_dt - moment).total_seconds() / 60
        if minutes_until < -1:
            continue

        route_short = str(stop_time.get("routeShortName", ""))
        dep_line_id, line_display = _line_label(route_short)
        if line_id and dep_line_id != line_id:
            continue

        headsign = str(stop_time.get("headsign", "")).strip()
        direction = headsign or (stop_time.get("tripTo") or {}).get("name", "")
        direction = display_name(direction) if direction else route_short

        key = (dep_str, direction, route_short)
        if key in seen:
            continue
        seen.add(key)

        if minutes_until < 1:
            time_display = "< 1 min"
        elif minutes_until < 60:
            time_display = f"{int(minutes_until)} min"
        else:
            time_display = dep_dt.astimezone().strftime("%H:%M")

        departures.append({
            "direction": direction,
            "time": time_display,
            "line": line_display,
            "line_id": dep_line_id,
            "service": route_short,
            "train": str(stop_time.get("tripShortName", "")),
            "minutes": max(0, int(minutes_until)),
            "estimated": False,
            "scheduled": True,
            "realtime": bool(stop_time.get("realTime")),
            "direction_id": str(stop_time.get("directionId", "")),
        })

    departures.sort(key=lambda d: d.get("minutes", 999))
    return departures


def _balance_directions(departures: list[dict], count: int) -> list[dict]:
    """Trim to ``count`` entries without losing a whole direction.

    The soonest departure of every distinct direction is seeded first (so users
    always see both ways of a line, not five trains one way), then the
    remaining slots are filled with the next-earliest departures overall.
    """
    if len(departures) <= count:
        return departures

    picked: list[dict] = []
    seen_directions: set[str] = set()
    for dep in departures:  # already sorted by minutes
        direction = dep.get("direction", "")
        if direction not in seen_directions:
            seen_directions.add(direction)
            picked.append(dep)
            if len(picked) >= count:
                break

    if len(picked) < count:
        chosen = {id(d) for d in picked}
        for dep in departures:
            if id(dep) in chosen:
                continue
            picked.append(dep)
            if len(picked) >= count:
                break

    picked.sort(key=lambda d: d.get("minutes", 999))
    return picked


async def get_realtime_departures(station_name: str,
                                  line_id: str | None = None,
                                  count: int = 6) -> list[dict]:
    """Next real CP departures from a station, straight from CP's timetable.

    Returns ``[]`` (never raises) when the station is unknown to CP's feed or
    MOTIS cannot be reached, so callers can fall back gracefully.
    """
    resolved = _resolve_or_fuzzy(station_name)
    if not resolved:
        return []

    cache_key = f"cp:rt:{resolved}:{line_id or 'all'}:{count}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    stop_id = MOTIS_STOP_IDS.get(resolved)
    if not stop_id:
        stop_id = await _geocode_stop_id(resolved)
    if not stop_id:
        logger.debug("No CP stop id known for station %s", resolved)
        return []

    stop_times = await _fetch_stoptimes(stop_id, count=max(count * 4, 12))
    if not stop_times:
        return []

    departures = _balance_directions(
        _parse_stoptimes(stop_times, line_id=line_id), count)
    if departures:
        _cache.set(cache_key, departures)
    return departures


async def get_next_departures_async(station_name: str,
                                    line_id: str | None = None,
                                    count: int = 5) -> list[dict]:
    """Next departures, preferring CP's real timetable.

    Chain: MOTIS stoptimes (real) -> MOTIS geocode + stoptimes (real) ->
    frequency estimate (clearly flagged with ``estimated=True``).
    """
    try:
        real = await get_realtime_departures(station_name, line_id=line_id,
                                            count=max(count, 6))
        if real:
            return real
    except Exception:
        logger.debug("CP real timetable unavailable for %s", station_name,
                     exc_info=True)
    return get_next_departures(station_name, line_id, count)


# ---------------------------------------------------------------------------
# Honest frequency fallback
# ---------------------------------------------------------------------------

def get_line_directions(line_id: str, station_name: str) -> list[str]:
    """Real onward terminals reachable from ``station_name`` on ``line_id``.

    Derived from :data:`LINE_STATION_ORDER`, so a terminus yields a single
    direction instead of the old "both endpoints for every station" bug.
    """
    ordered = LINE_STATION_ORDER.get(line_id, [])
    if len(ordered) < 2:
        return []

    resolved = resolve_station_name(station_name) or station_name
    if resolved in ordered:
        index = ordered.index(resolved)
        directions = []
        if index > 0:
            directions.append(ordered[0])
        if index < len(ordered) - 1:
            directions.append(ordered[-1])
        if directions:
            return [display_name(d) for d in directions]

    return [display_name(ordered[0]), display_name(ordered[-1])]


def format_interval(minutes: int, lang: str = "pt") -> str:
    """Describe a typical headway without pretending to be a departure time."""
    if lang == "en":
        return f"every ~{minutes} min"
    return f"a cada ~{minutes} min"


def get_next_departures(station_name: str, line_id: str | None = None,
                        count: int = 5) -> list[dict]:
    """Typical service description for a station -- **not** a real timetable.

    This is the last link in the fallback chain used when CP's timetable cannot
    be reached.  It deliberately reports the usual interval between trains per
    direction instead of inventing a departure at a precise minute, and every
    entry carries ``estimated=True`` plus ``interval_min`` so the UI can label
    it honestly.
    """
    resolved = _resolve_or_fuzzy(station_name)
    if not resolved:
        return []
    station_data = STATIONS[resolved]

    now = datetime.now()

    if not _is_operating(now.time()):
        return [{
            "direction": CLOSED_DIRECTION,
            "time": (
                f"Funcionamento: "
                f"{OPERATING_HOURS['start'].strftime('%H:%M')} - "
                f"{OPERATING_HOURS['end'].strftime('%H:%M')}"
            ),
            "line": "",
            "line_id": "",
            "estimated": True,
            "closed": True,
        }]

    frequencies = FREQUENCIES[_get_frequency_type(now)]

    lines_to_check = [line_id] if line_id else list(station_data["lines"])

    departures: list[dict] = []
    for lid in lines_to_check:
        line_data = CP_LINES.get(lid)
        if not line_data:
            continue
        interval = frequencies.get(lid, 60)
        for direction in get_line_directions(lid, resolved):
            departures.append({
                "direction": direction,
                "time": format_interval(interval),
                "line": f"{line_data['emoji']} {line_data['name']}",
                "line_id": lid,
                "estimated": True,
                "scheduled": False,
                "realtime": False,
                "interval_min": interval,
                "minutes": interval,
            })

    departures.sort(key=lambda d: (d.get("interval_min", 999),
                                   d.get("direction", "")))
    return departures[:count * 2]


# ---------------------------------------------------------------------------
# Geography / lines
# ---------------------------------------------------------------------------

def get_nearby_stations(lat: float, lon: float,
                        radius_km: float = 2.0) -> list[dict]:
    """Find CP stations within a given radius of coordinates."""
    nearby = []
    for name, data in STATIONS.items():
        slat = data.get("lat")
        slon = data.get("lon")
        if not slat or not slon:
            continue
        dist = _haversine(lat, lon, slat, slon)
        if dist <= radius_km:
            nearby.append({
                "name": name,
                "display": DISPLAY_NAMES.get(name, name),
                "distance_m": int(dist * 1000),
                "lines": _lines_info(data["lines"]),
                "lat": slat,
                "lon": slon,
            })
    nearby.sort(key=lambda x: x["distance_m"])
    return nearby[:10]


def get_all_lines() -> list[dict]:
    """Get information about all CP train lines."""
    return [
        {
            "id": lid,
            "name": data["name"],
            "emoji": data["emoji"],
            "route": data["route"],
            "type": data["type"],
            "station_count": len(get_line_stations(lid)),
        }
        for lid, data in CP_LINES.items()
    ]


def get_line_stations(line_id: str) -> list[str]:
    """Stations of a CP line **in real route order**.

    The order comes from :data:`LINE_STATION_ORDER` (the stop sequence of real
    CP trips), not from dict insertion order, so the rendered line map matches
    the actual line.
    """
    return list(LINE_STATION_ORDER.get(line_id, []))


def get_line_stations_display(line_id: str) -> list[str]:
    """Same as :func:`get_line_stations` but with user-facing names."""
    return [display_name(name) for name in get_line_stations(line_id)]


def get_frequency_info(line_id: str) -> dict:
    """Typical frequency information for a line (an estimate, not a timetable)."""
    return {
        "peak": f"A cada {FREQUENCIES['peak'].get(line_id, '?')} min",
        "off_peak": f"A cada {FREQUENCIES['off_peak'].get(line_id, '?')} min",
        "weekend": f"A cada {FREQUENCIES['weekend'].get(line_id, '?')} min",
        "hours": (
            f"{OPERATING_HOURS['start'].strftime('%H:%M')} - "
            f"{OPERATING_HOURS['end'].strftime('%H:%M')}"
        ),
        "estimated": True,
    }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance in km between two points on Earth."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_operating(current_time: time) -> bool:
    """Check if CP trains are currently operating."""
    start = OPERATING_HOURS["start"]
    end = OPERATING_HOURS["end"]
    if end < start:  # crosses midnight
        return current_time >= start or current_time <= end
    return start <= current_time <= end


def _get_frequency_type(now: datetime) -> str:
    """Determine the current frequency type based on day/time."""
    weekday = now.weekday()
    hour = now.hour

    if weekday >= 5:
        return "weekend"
    if 7 <= hour <= 9 or 17 <= hour <= 19:
        return "peak"
    return "off_peak"


async def close() -> None:
    """No-op kept for API symmetry with the other real-time services."""
    return None
