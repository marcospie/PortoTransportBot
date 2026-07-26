"""Metro do Porto departures via the MOTIS stoptimes API.

MOTIS (https://europe.motis-project.de) is an open-source multi-modal transit
router that ingests GTFS data from transit agencies across Europe, including
Metro do Porto.  The /api/v1/stoptimes endpoint returns all upcoming departures
from a given stop — including line, headsign (direction), and scheduled times —
in a single request.

Three things about this API that the code has to respect
-------------------------------------------------------
1. **``mode=SUBWAY`` is mandatory.**  Metro stations share a stop complex with
   STCP buses, and ``stoptimes`` returns the *combined* list ordered by time.
   At Trindade a request without a mode filter comes back as 50/50 STCP buses
   and zero metro departures (verified), so every metro departure was silently
   dropped by the mode filter below and the caller fell back to guesses.
2. **``realTime`` is per-stoptime and is usually ``false``.**  The feed carries
   scheduled times; Metro do Porto publishes no GTFS-RT trip updates to this
   instance.  The flag is propagated as-is so the UI can say "Horário previsto"
   instead of implying live tracking.
3. **The feed can be entirely out of date.**  In July 2026 the earliest metro
   departure this instance would return was three weeks in the future, because
   its Metro do Porto calendar had no service for the current date.  Anything
   beyond ``_HORIZON_MINUTES`` is therefore discarded rather than presented as
   "the next train".
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=90)  # 90-second cache for departures
# Short negative cache so a failing/unreachable API is not re-hit (with a 10s
# timeout) by every single user request.
_negative_cache = TTLCache(default_ttl=20)
# Stop IDs resolved from the geocode API; long TTL because they only change
# when MOTIS reimports the GTFS feed.
_stop_id_cache = TTLCache(default_ttl=21600)  # 6 hours

# MOTIS European transit API
_MOTIS_BASE = "https://europe.motis-project.de/api/v1"
_MOTIS_STOPTIMES_URL = f"{_MOTIS_BASE}/stoptimes"
_MOTIS_GEOCODE_URL = f"{_MOTIS_BASE}/geocode"

# Only metro modes; see note 1 in the module docstring.
_MOTIS_MODE = "SUBWAY"

# Discard departures further ahead than this; see note 3.
_HORIZON_MINUTES = 180

# A geocoded stop must be within this distance of the station we asked for,
# otherwise the name matched something unrelated.
_MAX_RESOLVE_DISTANCE_KM = 1.0

# Sentinel stored in the negative cache.
_FAILED = "__failed__"

# Fallback mapping from station name to MOTIS stop ID.
#
# These ids come from the Metro do Porto GTFS stop_ids as imported by MOTIS
# (``pt-Metro-Porto_<gtfs stop_id>``) and are correct as of 2026-07.  They are
# only a fallback: MOTIS regenerates ids when it reimports a feed, so
# ``resolve_stop_id()`` re-resolves by name+coordinates and caches the result
# whenever a lookup using these comes back empty.
_STATION_STOP_IDS: dict[str, str] = {
    # Line A — Senhor de Matosinhos ↔ Estádio do Dragão
    "Senhor de Matosinhos": "pt-Metro-Porto_5723",
    "Mercado": "pt-Metro-Porto_5716",
    "Brito Capelo": "pt-Metro-Porto_5700",
    "Matosinhos Sul": "pt-Metro-Porto_5715",
    "Câmara de Matosinhos": "pt-Metro-Porto_5701",
    "Parque de Real": "pt-Metro-Porto_5719",
    "Pedro Hispano": "pt-Metro-Porto_5720",
    "Vasco da Gama": "pt-Metro-Porto_5727",
    "Estádio do Mar": "pt-Metro-Porto_5709",
    # Shared trunk — Senhora da Hora ↔ Campanhã/Estádio do Dragão
    "Senhora da Hora": "pt-Metro-Porto_5724",
    "Sete Bicas": "pt-Metro-Porto_5725",
    "Viso": "pt-Metro-Porto_5729",
    "Ramalde": "pt-Metro-Porto_5721",
    "Francos": "pt-Metro-Porto_5711",
    "Casa da Música": "pt-Metro-Porto_5706",
    "Carolina Michaelis": "pt-Metro-Porto_5704",
    "Lapa": "pt-Metro-Porto_5713",
    "Trindade": "pt-Metro-Porto_5726",
    "Bolhão": "pt-Metro-Porto_5699",
    "Campo 24 de Agosto": "pt-Metro-Porto_5697",
    "Heroísmo": "pt-Metro-Porto_5712",
    "Campanhã": "pt-Metro-Porto_5703",
    "Estádio do Dragão": "pt-Metro-Porto_5708",
    # Line C / F — east of Campanhã
    "Nasoni": "pt-Metro-Porto_5717",
    "Nau Vitória": "pt-Metro-Porto_5718",
    "Contumil": "pt-Metro-Porto_5707",
    "Levada": "pt-Metro-Porto_5714",
    "Rio Tinto": "pt-Metro-Porto_5722",
    "Campainha": "pt-Metro-Porto_5702",
    "Baguim": "pt-Metro-Porto_5698",
    "Fânzeres": "pt-Metro-Porto_5710",
    "Venda Nova": "pt-Metro-Porto_5728",
    "Carreira": "pt-Metro-Porto_5705",
    # Line C — Maia / ISMAI
    "Custió": "pt-Metro-Porto_5757",
    "Araújo": "pt-Metro-Porto_5754",
    "Cândido dos Reis": "pt-Metro-Porto_5755",
    "Pias": "pt-Metro-Porto_5764",
    "Fórum da Maia": "pt-Metro-Porto_5760",
    "Parque da Maia": "pt-Metro-Porto_5763",
    "Mandim": "pt-Metro-Porto_5762",
    "Zona Industrial": "pt-Metro-Porto_5765",
    "Castêlo da Maia": "pt-Metro-Porto_5756",
    "ISMAI": "pt-Metro-Porto_5761",
    # Line D — Hospital de São João ↔ Hospital Santos Silva
    "Hospital de São João": "pt-Metro-Porto_5791",
    "IPO": "pt-Metro-Porto_5772",
    "Polo Universitário": "pt-Metro-Porto_5776",
    "Salgueiros": "pt-Metro-Porto_5777",
    "Combatentes": "pt-Metro-Porto_5768",
    "Marquês": "pt-Metro-Porto_5775",
    "Faria Guimarães": "pt-Metro-Porto_5770",
    "Aliados": "pt-Metro-Porto_5766",
    "São Bento": "pt-Metro-Porto_5778",
    "Jardim do Morro": "pt-Metro-Porto_5773",
    "General Torres": "pt-Metro-Porto_5771",
    "Câmara de Gaia": "pt-Metro-Porto_5767",
    "João de Deus": "pt-Metro-Porto_5774",
    "Santo Ovídio": "pt-Metro-Porto_5792",
    "D. João II": "pt-Metro-Porto_5769",
    "Manuel Leão": "pt-Metro-Porto_5812",
    "Vila d'Este": "pt-Metro-Porto_5813",
    "Hospital Santos Silva": "pt-Metro-Porto_5811",
    # Line B — Póvoa de Varzim
    "Custóias": "pt-Metro-Porto_5734",
    "Crestins": "pt-Metro-Porto_5733",
    "Esposade": "pt-Metro-Porto_5736",
    "Vilar do Pinheiro": "pt-Metro-Porto_5753",
    "Modivas Sul": "pt-Metro-Porto_5743",
    "Modivas Centro": "pt-Metro-Porto_5741",
    "Mindelo": "pt-Metro-Porto_5740",
    "Varziela": "pt-Metro-Porto_5749",
    "Árvore": "pt-Metro-Porto_5731",
    "Azurara": "pt-Metro-Porto_5732",
    "Vila do Conde": "pt-Metro-Porto_5752",
    "Santa Clara": "pt-Metro-Porto_5747",
    "Portas Fronhas": "pt-Metro-Porto_5745",
    "Alto de Pega": "pt-Metro-Porto_5730",
    "São Brás": "pt-Metro-Porto_5748",
    "Póvoa de Varzim": "pt-Metro-Porto_5746",
    # Line E — Aeroporto
    "Aeroporto": "pt-Metro-Porto_5782",
    "Pedras Rubras": "pt-Metro-Porto_5744",
    "Verdes": "pt-Metro-Porto_5750",
    "Lidador": "pt-Metro-Porto_5739",
    "Botica": "pt-Metro-Porto_5783",
    "Fonte do Cuco": "pt-Metro-Porto_5737",
    # Line B — added 2026-07: present in the GTFS feed and verified
    # against MOTIS geocode (pt-Metro-Porto_5742 / _5735).
    "VC Fashion Outlet I Modivas": "pt-Metro-Porto_5742",
    "Espaço Natureza": "pt-Metro-Porto_5735",
}

# MOTIS ``routeShortName`` -> internal bot line code.
# The Metro do Porto feed publishes route_id "Bexp" with short name "Bx" for the
# Line B express service. It is the same red line to a passenger, so map both
# spellings onto "B" — otherwise it renders as a colourless "🚇 Linha Bexp".
_ROUTE_TO_LINE = {
    "A": "A",
    "B": "B",
    "Bexp": "B",
    "BEXP": "B",
    "Bx": "B",
    "BX": "B",
    "C": "C",
    "D": "D",
    "E": "E",
    "F": "F",
}


def get_stop_id(station_name: str) -> Optional[str]:
    """Get the known MOTIS stop ID for a station name (no network access).

    Prefers a previously resolved id, then the hardcoded fallback table.
    """
    cached = _stop_id_cache.get(f"stopid:{station_name}")
    if isinstance(cached, str) and cached != _FAILED:
        return cached
    return _STATION_STOP_IDS.get(station_name)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# GTFS/MOTIS spellings for stations this bot names differently.
_GEOCODE_QUERY_ALIASES = {
    "Campo 24 de Agosto": "24 de Agosto",
    "Sete Bicas": "NorteShopping I Sete Bicas",
    "Câmara de Gaia": "Câmara Gaia",
    "Câmara de Matosinhos": "Câmara Matosinhos",
    "Fórum da Maia": "Fórum Maia",
    "Parque da Maia": "Parque Maia",
    "Polo Universitário": "Pólo Universitário",
    "Hospital de São João": "Hospital São João",
    "Zona Industrial": "Zona Indústrial",
}


async def _geocode_stop_id(station_name: str) -> Optional[str]:
    """Look up a Metro do Porto stop ID by name, sanity-checked by distance."""
    from bot.services.metro import STATIONS

    station = STATIONS.get(station_name)
    if not station:
        return None

    query = _GEOCODE_QUERY_ALIASES.get(station_name, station_name)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_MOTIS_GEOCODE_URL, params={"text": query})
            if resp.status_code != 200:
                logger.warning(
                    "MOTIS geocode HTTP %d resolving stop id for %s",
                    resp.status_code, station_name)
                return None
            features = resp.json()
    except Exception:
        logger.warning("MOTIS geocode request failed for %s",
                       station_name, exc_info=True)
        return None

    if not isinstance(features, list):
        logger.warning("MOTIS geocode returned unexpected payload for %s",
                       station_name)
        return None

    best: Optional[tuple[float, str]] = None
    for feat in features:
        if not isinstance(feat, dict) or feat.get("type") != "STOP":
            continue
        stop_id = feat.get("id") or ""
        if "Metro-Porto" not in stop_id:
            continue
        try:
            dist = _haversine_km(station["lat"], station["lon"],
                                 float(feat["lat"]), float(feat["lon"]))
        except (KeyError, TypeError, ValueError):
            continue
        if dist <= _MAX_RESOLVE_DISTANCE_KM and (best is None or dist < best[0]):
            best = (dist, stop_id)

    if best is None:
        logger.warning(
            "MOTIS geocode found no Metro do Porto stop within %.1f km of %s",
            _MAX_RESOLVE_DISTANCE_KM, station_name)
        return None

    logger.info("Resolved MOTIS stop id for %s: %s (%.0f m away)",
                station_name, best[1], best[0] * 1000)
    return best[1]


async def resolve_stop_id(station_name: str,
                          force_refresh: bool = False) -> Optional[str]:
    """Resolve a station's MOTIS stop ID, caching the answer.

    Order: resolution cache -> hardcoded fallback -> geocode API. With
    ``force_refresh`` the hardcoded fallback is skipped, which is how a stale
    id gets repaired after MOTIS reimports its GTFS data.
    """
    from bot.services.metro import STATIONS

    cache_key = f"stopid:{station_name}"
    if not force_refresh:
        cached = _stop_id_cache.get(cache_key)
        if isinstance(cached, str) and cached != _FAILED:
            return cached
        fallback = _STATION_STOP_IDS.get(station_name)
        if fallback:
            return fallback

    # Never geocode a name we do not recognise as a station.
    if station_name not in STATIONS:
        return None

    if _stop_id_cache.get(f"resolvefail:{station_name}") == _FAILED:
        return _STATION_STOP_IDS.get(station_name)

    resolved = await _geocode_stop_id(station_name)
    if resolved:
        _stop_id_cache.set(cache_key, resolved)
        # Mark as checked against the live API so we do not re-geocode on
        # every request when the feed simply has nothing scheduled.
        _stop_id_cache.set(f"verified:{station_name}", resolved)
        return resolved

    # Remember the failure briefly so we do not geocode on every request, and
    # warn loudly: silent fallback to frequency guesses is what made the
    # previous breakage invisible.
    _stop_id_cache.set(f"resolvefail:{station_name}", _FAILED, ttl=300)
    logger.warning(
        "Could not resolve a MOTIS stop id for %s; falling back to the "
        "hardcoded id (%s). Realtime lookups may be degraded.",
        station_name, _STATION_STOP_IDS.get(station_name))
    return _STATION_STOP_IDS.get(station_name)


async def _query_stoptimes(stop_id: str, count: int = 20) -> list[dict]:
    """Query the MOTIS stoptimes endpoint for metro departures at a stop."""
    if _negative_cache.get(f"fail:{stop_id}") == _FAILED:
        logger.debug("Skipping MOTIS request for %s — recent failure cached",
                     stop_id)
        return []

    now = datetime.now(timezone.utc)
    time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "stopId": stop_id,
        "time": time_str,
        "n": str(count),
        "arriveBy": "false",
        # Without this the response is dominated by STCP buses sharing the
        # stop complex and contains no metro departures at all.
        "mode": _MOTIS_MODE,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_MOTIS_STOPTIMES_URL, params=params)
            if resp.status_code != 200:
                logger.warning("MOTIS stoptimes API returned HTTP %d for %s",
                               resp.status_code, stop_id)
                _negative_cache.set(f"fail:{stop_id}", _FAILED)
                return []
            return resp.json().get("stopTimes", [])
    except Exception:
        logger.warning("MOTIS stoptimes request failed for %s",
                       stop_id, exc_info=True)
        _negative_cache.set(f"fail:{stop_id}", _FAILED)
        return []


def _parse_stoptimes(stop_times: list[dict]) -> list[dict]:
    """Parse a MOTIS stoptimes response into departure dicts.

    ``realtime`` reflects the per-stoptime ``realTime`` flag from the API — it
    is NOT hardcoded to True. Downstream (``bot.utils.formatting``) uses it to
    choose between "Atualizado às" (live) and "Horário previsto" (timetable),
    so forcing it True made every scheduled time look like live tracking.
    """
    from bot.config import METRO_LINES

    now = datetime.now(timezone.utc)
    departures = []
    seen = set()

    for st in stop_times:
        mode = st.get("mode", "")
        if mode not in ("SUBWAY", "TRAM", "RAIL"):
            continue

        agency = st.get("agencyName", "").lower()
        if agency and agency not in ("metro do porto", "metro"):
            continue

        place = st.get("place", {})
        dep_str = place.get("departure", "")
        if not dep_str:
            continue

        headsign = st.get("headsign", "")
        route_short = st.get("routeShortName", "")

        # Deduplicate by time + direction
        dedup_key = (dep_str, headsign)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Parse departure time
        try:
            dep_dt = datetime.fromisoformat(dep_str.replace("Z", "+00:00"))
            if dep_dt.tzinfo is None:
                dep_dt = dep_dt.replace(tzinfo=timezone.utc)
            minutes_until = (dep_dt - now).total_seconds() / 60
        except (ValueError, TypeError):
            continue

        if minutes_until < -1:
            continue
        if minutes_until > _HORIZON_MINUTES:
            # Feed calendar does not cover today; see note 3 in the docstring.
            continue

        # Was this a live prediction, or just the timetable?
        is_realtime = bool(st.get("realTime", False))
        scheduled = place.get("scheduledDeparture") or dep_str

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
            # Honest: True only when MOTIS reported a live prediction.
            "realtime": is_realtime,
            "scheduled_departure": scheduled,
            "route_color": st.get("routeColor", ""),
        })

    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures


async def get_realtime_departures(station_name: str,
                                  count: int = 8) -> list[dict]:
    """Get next departures for a metro station via the MOTIS stoptimes API.

    Resolves the station's stop ID (cached, with a hardcoded fallback), queries
    the stoptimes endpoint for metro modes only, and returns departures in both
    directions.

    If the first lookup yields nothing, the stop ID is re-resolved against the
    geocode API once and the query retried — this repairs the case where MOTIS
    reimported its GTFS feed and every numeric stop ID shifted.

    Returns a list of departure dicts compatible with
    ``metro.get_next_departures()``.
    """
    cache_key = f"rt:{station_name}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    stop_id = await resolve_stop_id(station_name)
    if not stop_id:
        logger.warning("No MOTIS stop ID for station: %s", station_name)
        return []

    stop_times = await _query_stoptimes(stop_id, count=count * 3)
    departures = _parse_stoptimes(stop_times) if stop_times else []

    if not departures and _stop_id_cache.get(f"verified:{station_name}") is None:
        # Maybe the id went stale. Re-resolve once and retry. The "verified"
        # marker stops this from geocoding on every request when the real reason
        # for the empty result is that the feed has no service scheduled.
        fresh_id = await resolve_stop_id(station_name, force_refresh=True)
        if fresh_id and fresh_id != stop_id:
            logger.warning(
                "MOTIS stop id for %s changed (%s -> %s); retrying",
                station_name, stop_id, fresh_id)
            stop_times = await _query_stoptimes(fresh_id, count=count * 3)
            departures = _parse_stoptimes(stop_times) if stop_times else []

    if not departures:
        # Cache the empty result briefly so a feed with no current service does
        # not cause a fresh 10s-timeout request on every user interaction.
        _cache.set(cache_key, [], ttl=30)
        return []

    # Balance directions so both are represented, then limit
    from bot.services.metro import _balance_directions
    departures = _balance_directions(departures, count)

    if departures:
        _cache.set(cache_key, departures)

    return departures


async def close():
    """No-op kept for API compatibility."""
    pass
