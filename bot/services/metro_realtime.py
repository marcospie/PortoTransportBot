"""Metro do Porto departures via the MOTIS stoptimes API.

MOTIS (https://europe.motis-project.de) is an open-source multi-modal transit
router that ingests GTFS data from transit agencies across Europe, including
Metro do Porto.  The /api/v1/stoptimes endpoint returns all upcoming departures
from a given stop — including line, headsign (direction), and scheduled times —
in a single request.

This replaces the previous approach of querying the /plan endpoint with
neighbour stations, which often missed directions and required multiple
parallel requests.  The stoptimes endpoint is simpler, faster, and returns
both directions for every line serving a station.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=90)  # 90-second cache

# MOTIS European transit API — stoptimes endpoint returns all departures at a stop
_MOTIS_STOPTIMES_URL = "https://europe.motis-project.de/api/v1/stoptimes"

# Mapping from station name (as used in our STATIONS dict) to MOTIS stop ID.
# These were discovered by querying the MOTIS /plan endpoint for each line
# and extracting stopId from itinerary legs and intermediate stops.
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
}

# Line code to internal bot code mapping
_ROUTE_TO_LINE = {
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
    "E": "E",
    "F": "F",
}


def get_stop_id(station_name: str) -> Optional[str]:
    """Get the MOTIS stop ID for a station name."""
    return _STATION_STOP_IDS.get(station_name)


async def _query_stoptimes(stop_id: str, count: int = 20) -> list[dict]:
    """Query MOTIS stoptimes endpoint for all departures at a stop."""
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "stopId": stop_id,
        "time": time_str,
        "n": str(count),
        "arriveBy": "false",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_MOTIS_STOPTIMES_URL, params=params)
            if resp.status_code != 200:
                logger.warning("MOTIS stoptimes API returned HTTP %d", resp.status_code)
                return []
            return resp.json().get("stopTimes", [])
    except Exception:
        logger.debug("MOTIS stoptimes request failed", exc_info=True)
        return []


def _parse_stoptimes(stop_times: list[dict]) -> list[dict]:
    """Parse MOTIS stoptimes response into departure dicts."""
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
            "route_color": st.get("routeColor", ""),
        })

    departures.sort(key=lambda x: x.get("minutes", 999))
    return departures


async def get_realtime_departures(station_name: str,
                                   count: int = 8) -> list[dict]:
    """Get next departures for a metro station via MOTIS stoptimes API.

    Queries the stoptimes endpoint directly with the station's stop ID,
    which returns all upcoming departures including every line and direction.
    No need for neighbour queries or direction balancing hacks.

    Returns a list of departure dicts compatible with
    ``metro.get_next_departures()``.
    """
    cache_key = f"rt:{station_name}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    stop_id = _STATION_STOP_IDS.get(station_name)
    if not stop_id:
        logger.warning("No MOTIS stop ID for station: %s", station_name)
        return []

    stop_times = await _query_stoptimes(stop_id, count=count * 3)
    if not stop_times:
        return []

    departures = _parse_stoptimes(stop_times)

    # Balance directions so both are represented, then limit
    from bot.services.metro import _balance_directions
    departures = _balance_directions(departures, count)

    if departures:
        _cache.set(cache_key, departures)

    return departures


async def close():
    """No-op kept for API compatibility."""
    pass
