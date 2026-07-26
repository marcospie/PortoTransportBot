import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
GTFS_DIR = DATA_DIR / "gtfs"

# ---------------------------------------------------------------------------
# GTFS feeds — resolved dynamically from the Porto open data portal (CKAN)
# ---------------------------------------------------------------------------
# The portal publishes a *new resource* every time a feed is updated and keeps
# the old ones, so any hardcoded ``.../download/<dated-filename>.zip`` URL rots:
# the pinned STCP URL below used to be ``gtfs_static_03_03_2026.zip``, which
# returns HTTP 404 (verified).  Worse, the portal regularly publishes 0-byte
# resources (the current "Mais Recente" metro file is 0 bytes), so "newest"
# alone is not a safe selector either.
#
# ``bot.services.gtfs_catalog`` style resolution lives in ``resolve_latest_gtfs_url``
# below: ask CKAN for the dataset, then pick the most recently modified resource
# that actually has bytes.  The hardcoded lists stay as an offline fallback.
CKAN_BASE = "https://opendata.porto.digital/api/3/action"

# CKAN dataset ids (stable — these are the dataset UUIDs, not resource UUIDs)
CKAN_METRO_DATASET = "15f22603-a216-492a-ab1c-40b1d8aa2f08"
CKAN_STCP_DATASET = "5275c986-592c-43f5-8f87-aabbd4e4f3a4"

# Minimum plausible size for a GTFS zip; the portal serves 0-byte placeholders.
GTFS_MIN_BYTES = 1000

# Offline fallback URLs, newest working first. All verified HTTP 200 with
# non-zero length at the time of writing.
GTFS_METRO_URLS = [
    # 07-04-2026 — 379 KB
    "https://opendata.porto.digital/dataset/"
    "15f22603-a216-492a-ab1c-40b1d8aa2f08/resource/"
    "5e2b445d-b85b-4afb-9116-90b24327151c/download/___",
    # 20-02-2026 — 362 KB
    "https://opendata.porto.digital/dataset/"
    "15f22603-a216-492a-ab1c-40b1d8aa2f08/resource/"
    "a8375fac-8ded-4858-9c45-83f9be814900/download/"
    "horarios_gtfs_mdp_20_02_2026.zip",
    # 06-09-2024 — 388 KB, last resort
    "https://opendata.porto.digital/dataset/"
    "15f22603-a216-492a-ab1c-40b1d8aa2f08/resource/"
    "f592c53a-e669-4cac-9e28-ab84b87e7f6b/download/"
    "horarios_gtfs_09_09_2024.zip",
]

# Offline fallback for STCP (25-07-2026, 5.9 MB — verified HTTP 200).
# ``bot.services.stcp`` imports this as a plain string, so it must stay one;
# prefer ``resolve_latest_gtfs_url(CKAN_STCP_DATASET)`` when a network call is
# acceptable.
GTFS_STCP_URL = (
    "https://opendata.porto.digital/dataset/"
    "5275c986-592c-43f5-8f87-aabbd4e4f3a4/resource/"
    "96c0ba2f-feb1-47c1-8e39-8588d0b5768d/download/gtfs_feed.zip"
)
GTFS_STCP_URLS = [GTFS_STCP_URL]


def _resource_sort_key(resource: dict) -> str:
    """Newest-first sort key for a CKAN resource."""
    return (resource.get("last_modified")
            or resource.get("created")
            or "")


def parse_gtfs_resources(package: dict) -> list[str]:
    """Pick usable GTFS zip URLs from a CKAN ``package_show`` result.

    Returns download URLs ordered newest first, skipping resources that are
    empty (``size`` 0) or obviously not a feed archive.  Pure function so it
    can be unit-tested without network access.
    """
    result = package.get("result", package) or {}
    candidates = []
    for res in result.get("resources", []) or []:
        url = res.get("url") or ""
        if not url:
            continue
        fmt = (res.get("format") or "").upper()
        if fmt not in ("GTFS", "ZIP"):
            continue
        size = res.get("size")
        # size is None for some resources — keep those, they may still be fine.
        if isinstance(size, (int, float)) and size < GTFS_MIN_BYTES:
            continue
        candidates.append(res)

    candidates.sort(key=_resource_sort_key, reverse=True)
    return [res["url"] for res in candidates]


async def resolve_latest_gtfs_url(dataset_id: str,
                                  timeout: float = 15.0) -> list[str]:
    """Resolve current GTFS download URLs for a CKAN dataset, newest first.

    Returns ``[]`` on any failure so callers can fall back to the pinned
    lists above.
    """
    import logging

    import aiohttp

    logger = logging.getLogger(__name__)
    url = f"{CKAN_BASE}/package_show"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params={"id": dataset_id},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    logger.warning("CKAN package_show HTTP %d for %s",
                                   resp.status, dataset_id)
                    return []
                payload = await resp.json()
    except Exception:
        logger.warning("CKAN package_show request failed for %s",
                       dataset_id, exc_info=True)
        return []

    if not payload.get("success"):
        logger.warning("CKAN package_show unsuccessful for %s", dataset_id)
        return []

    urls = parse_gtfs_resources(payload)
    if not urls:
        logger.warning("CKAN returned no usable GTFS resource for %s",
                       dataset_id)
    return urls


# ---------------------------------------------------------------------------
# Metro do Porto lines
# ---------------------------------------------------------------------------
# ``route`` endpoints double as direction headsigns, so they must match the
# real terminus *and* the station names in ``bot.services.metro.STATIONS``.
# Verified against routes.txt/trips.txt of the 07-04-2026 Metro do Porto GTFS
# feed (trip_headsign values: "Senhor de Matosinhos"/"Estádio do Dragão",
# "Póvoa de Varzim", "ISMAI"/"Campanhã", "Hospital São João"/"Vila d'Este",
# "Aeroporto", "Fânzeres"/"Senhora da Hora").
METRO_LINES = {
    "A": {"name": "Linha Azul", "emoji": "🔵", "route": "Senhor de Matosinhos ↔ Estádio do Dragão"},
    "B": {"name": "Linha Vermelha", "emoji": "🔴", "route": "Póvoa de Varzim ↔ Estádio do Dragão"},
    # Line C terminates at Campanhã, not Campainha — Campainha is a Line F
    # station on the Gondomar branch.
    "C": {"name": "Linha Verde", "emoji": "🟢", "route": "ISMAI ↔ Campanhã"},
    # Line D runs the full Gaia extension past Santo Ovídio to Vila d'Este.
    "D": {"name": "Linha Amarela", "emoji": "🟡", "route": "Vila d'Este ↔ Hospital de São João"},
    "E": {"name": "Linha Violeta", "emoji": "🟣", "route": "Aeroporto ↔ Estádio do Dragão"},
    "F": {"name": "Linha Laranja", "emoji": "🟠", "route": "Fânzeres ↔ Senhora da Hora"},
}
