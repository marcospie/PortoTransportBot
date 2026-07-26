"""Event data for Porto — FC Porto matches, festivals, concerts, culture.

Two kinds of data live here:

1. **Live FC Porto fixtures** fetched from the club's own (undocumented but
   keyless) app API, verified working on 2026-07-26::

       GET https://api.app.fcporto.pt/v2/teams/1/nextMatches
           ?limit=20&locale=pt&bundle=pt.thingpink.web.fcporto&platform=5
       -> 200, JSON {"data": [{"date", "home_team", "away_team",
                               "place": {"name"}, "competition": {...}}]}

   Only matches at Estádio do Dragão are kept, since those are the ones that
   matter for Porto transport.  ``bundle`` and ``platform`` are mandatory
   (omitting them yields ``{"error": {"http": 400}}``).

2. **A curated dataset of recurring Porto events** (festivals, book fair,
   cultural seasons).  A static dataset silently goes stale, so this module
   never pretends otherwise: :func:`get_events_status` reports a distinguishable
   ``"no_data_for_period"`` state, and :func:`is_dataset_stale` /
   :data:`DATASET_END_DATE` expose when the curated data has run out.  A warning
   is logged whenever stale data is queried.

"Today" is always evaluated in **Europe/Lisbon**, never in the host's local
timezone, so a server in another region does not shift the Porto calendar.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: Porto runs on Europe/Lisbon; never use the host timezone for "today".
PORTO_TZ = ZoneInfo("Europe/Lisbon")

# Event data states reported by get_events_status().
STATE_OK = "ok"
STATE_NONE_TODAY = "none_today"
STATE_NO_DATA = "no_data_for_period"

# Live fixture source (see module docstring).
FCPORTO_FIXTURES_URL = "https://api.app.fcporto.pt/v2/teams/1/nextMatches"
FCPORTO_QUERY = {
    "limit": "20",
    "locale": "pt",
    "bundle": "pt.thingpink.web.fcporto",
    "platform": "5",
}
DRAGAO_VENUE = "Estádio do Dragão"
FIXTURES_REFRESH_SECONDS = 6 * 3600
REQUEST_TIMEOUT = 15

SOURCE_CURATED = "curated"
SOURCE_FCPORTO = "fcporto"


@dataclass
class Event:
    name_pt: str
    name_en: str
    venue_pt: str
    venue_en: str
    date_info_pt: str
    date_info_en: str
    nearest_station: str
    transport_tip_pt: str
    transport_tip_en: str
    category: str  # "football", "festival", "music", "culture"
    emoji: str
    start_date: date
    end_date: date
    #: Where this entry came from — "curated" (static list) or "fcporto" (live).
    source: str = SOURCE_CURATED


_DRAGAO_TIP_PT = ("Metro até Estádio do Dragão (Linhas A/B/E). "
                  "Em dias de jogo há metro extra.")
_DRAGAO_TIP_EN = ("Metro to Estádio do Dragão (Lines A/B/E). "
                  "Extra metro service on match days.")

# ---------------------------------------------------------------------------
# Curated dataset
#
# Recurring Porto events with the dates of their most recently confirmed
# edition. Last reviewed: 2026-07-26.  Football fixtures are NOT listed here:
# they come from the live FC Porto feed, because hardcoded fixtures go stale
# after one season and were previously being shown as if current.
# ---------------------------------------------------------------------------
DATASET_REVIEWED = date(2026, 7, 26)

_CURATED_EVENTS: list[Event] = [
    Event(
        name_pt="Fantasporto 2026",
        name_en="Fantasporto 2026",
        venue_pt="Rivoli — Teatro Municipal",
        venue_en="Rivoli — Municipal Theatre",
        date_info_pt="28 fev — 14 mar",
        date_info_en="Feb 28 — Mar 14",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados (Linha D), 3 min a pé até ao Rivoli.",
        transport_tip_en="Metro to Aliados (Line D), 3 min walk to Rivoli.",
        category="culture",
        emoji="🎬",
        start_date=date(2026, 2, 28),
        end_date=date(2026, 3, 14),
    ),
    Event(
        name_pt="Queima das Fitas do Porto",
        name_en="Queima das Fitas",
        venue_pt="Queimódromo",
        venue_en="Queimódromo",
        date_info_pt="3 — 10 mai",
        date_info_en="May 3 — 10",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F). Autocarros especiais durante o evento.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F). Special buses during the event.",
        category="festival",
        emoji="🎓",
        start_date=date(2026, 5, 3),
        end_date=date(2026, 5, 10),
    ),
    Event(
        name_pt="Feira do Livro do Porto",
        name_en="Porto Book Fair",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="15 mai — 1 jun",
        date_info_en="May 15 — Jun 1",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="culture",
        emoji="📚",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 6, 1),
    ),
    Event(
        name_pt="NOS Primavera Sound",
        name_en="NOS Primavera Sound",
        venue_pt="Parque da Cidade",
        venue_en="Parque da Cidade",
        date_info_pt="4 — 7 jun",
        date_info_en="Jun 4 — 7",
        nearest_station="Matosinhos Sul",
        transport_tip_pt="Metro até Matosinhos Sul (Linha A). Shuttles disponíveis nos dias do festival.",
        transport_tip_en="Metro to Matosinhos Sul (Line A). Shuttles available on festival days.",
        category="music",
        emoji="🎵",
        start_date=date(2026, 6, 4),
        end_date=date(2026, 6, 7),
    ),
    Event(
        name_pt="Serralves em Festa",
        name_en="Serralves em Festa",
        venue_pt="Fundação de Serralves",
        venue_en="Serralves Foundation",
        date_info_pt="13 — 14 jun",
        date_info_en="Jun 13 — 14",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois 15 min a pé ou autocarro 201/203.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then 15 min walk or bus 201/203.",
        category="festival",
        emoji="🎨",
        start_date=date(2026, 6, 13),
        end_date=date(2026, 6, 14),
    ),
    Event(
        name_pt="São João",
        name_en="São João Festival",
        venue_pt="Centro do Porto",
        venue_en="Porto city center",
        date_info_pt="23 — 24 jun",
        date_info_en="Jun 23 — 24",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados ou São Bento. Metro funciona toda a noite de São João.",
        transport_tip_en="Metro to Aliados or São Bento. Metro runs all night on São João.",
        category="festival",
        emoji="🔨",
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 24),
    ),
    Event(
        name_pt="Noites Ritual",
        name_en="Noites Ritual",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="2 jul — 29 ago",
        date_info_en="Jul 2 — Aug 29",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="music",
        emoji="🎶",
        start_date=date(2026, 7, 2),
        end_date=date(2026, 8, 29),
    ),
]

#: All known events (curated + live fixtures).  Mutated **in place** by
#: :func:`refresh_events` so ``from ... import EVENTS`` stays valid and
#: ``EVENTS.index(event)`` keeps working for callback payloads.
EVENTS: list[Event] = list(_CURATED_EVENTS)

EVENT_CATEGORIES = {
    "football": {"name_pt": "Futebol", "name_en": "Football", "emoji": "⚽"},
    "festival": {"name_pt": "Festivais", "name_en": "Festivals", "emoji": "🎉"},
    "music": {"name_pt": "Música", "name_en": "Music", "emoji": "🎵"},
    "culture": {"name_pt": "Cultura", "name_en": "Culture", "emoji": "🎭"},
}

_MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
_MONTHS_EN = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]

_last_fixture_refresh: datetime | None = None
_fixture_source_ok: bool = False
_refresh_task: "asyncio.Task | None" = None


# ---------------------------------------------------------------------------
# Time helpers — always Europe/Lisbon
# ---------------------------------------------------------------------------

def today_in_porto() -> date:
    """Today's date in Europe/Lisbon, regardless of the host's timezone."""
    return datetime.now(PORTO_TZ).date()


def now_in_porto() -> datetime:
    """Current time in Europe/Lisbon."""
    return datetime.now(PORTO_TZ)


def _resolve_today(today: date | None) -> date:
    return today if today is not None else today_in_porto()


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def dataset_end_date() -> date | None:
    """Latest ``end_date`` in the dataset, or None when it is empty."""
    if not EVENTS:
        return None
    return max(e.end_date for e in EVENTS)


def is_dataset_stale(today: date | None = None) -> bool:
    """True when every known event has already finished.

    In that state the dataset can no longer answer questions about the current
    period, and callers must say "no event data available for this period"
    rather than "there are no events".
    """
    today = _resolve_today(today)
    end = dataset_end_date()
    return end is None or end < today


def get_events_status(today: date | None = None, limit: int = 5) -> dict:
    """Describe the event data situation in a machine-checkable way.

    Returns a dict with:
        ``state``     — :data:`STATE_OK` (something is on today),
                        :data:`STATE_NONE_TODAY` (nothing today but upcoming
                        events are known), or :data:`STATE_NO_DATA` (the
                        dataset does not cover this period at all).
        ``today``     — events happening today.
        ``upcoming``  — the next events after today.
        ``stale``     — True when the dataset has run out.
        ``fixtures_live`` — whether the live FC Porto feed was loaded.
        ``message_pt`` / ``message_en`` — human wording for the state.
    """
    today = _resolve_today(today)
    todays = get_todays_events(today)
    upcoming = get_upcoming_events(today, limit=limit)
    stale = is_dataset_stale(today)

    if todays:
        state = STATE_OK
        message_pt = f"{len(todays)} evento(s) hoje no Porto."
        message_en = f"{len(todays)} event(s) in Porto today."
    elif upcoming:
        state = STATE_NONE_TODAY
        message_pt = "Sem eventos hoje. Próximos eventos abaixo."
        message_en = "No events today. Upcoming events below."
    else:
        state = STATE_NO_DATA
        message_pt = ("Sem dados de eventos para este período. "
                      "Consulta porto.pt/agenda ou fcporto.pt.")
        message_en = ("No event data available for this period. "
                      "See porto.pt/agenda or fcporto.pt.")

    return {
        "state": state,
        "today": todays,
        "upcoming": upcoming,
        "stale": stale,
        "fixtures_live": _fixture_source_ok,
        "dataset_end_date": dataset_end_date(),
        "dataset_reviewed": DATASET_REVIEWED,
        "message_pt": message_pt,
        "message_en": message_en,
    }


def _warn_if_stale(today: date) -> None:
    if is_dataset_stale(today):
        logger.warning(
            "Porto event dataset is stale: latest end_date is %s but today is "
            "%s — reporting 'no event data for this period' instead of 'no "
            "events'. Refresh the curated list in bot/services/events.py.",
            dataset_end_date(), today,
        )


# ---------------------------------------------------------------------------
# Live FC Porto fixtures
# ---------------------------------------------------------------------------

def _format_match_date(dt: datetime, has_hour: bool) -> tuple[str, str]:
    day = dt.day
    month_pt = _MONTHS_PT[dt.month - 1]
    month_en = _MONTHS_EN[dt.month - 1]
    if not has_hour:
        return f"{day} de {month_pt}", f"{month_en} {day}"
    pt = f"{day} de {month_pt}, {dt.strftime('%Hh%M')}"
    hour12 = dt.strftime("%I:%M %p").lstrip("0")
    return pt, f"{month_en} {day}, {hour12}"


def _parse_fixture(item: dict) -> Event | None:
    """Convert one FC Porto API match into an :class:`Event` at the Dragão."""
    place = (item.get("place") or {}).get("name") or ""
    if DRAGAO_VENUE.lower() not in place.lower():
        return None  # not a Porto-transport-relevant match

    raw_date = item.get("date") or ""
    try:
        dt = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        logger.debug("Unparseable FC Porto fixture date: %r", raw_date)
        return None

    home = (item.get("home_team") or {}).get("short_name") or "FC Porto"
    away = (item.get("away_team") or {}).get("short_name") or "?"
    competition = item.get("competition") or {}
    top_level = (competition.get("top_level") or {}).get("name") or ""
    has_hour = str(item.get("has_hour", "1")) not in ("0", "False", "")

    date_pt, date_en = _format_match_date(dt, has_hour)
    name = f"{home} vs {away}"
    if top_level:
        name_pt = f"{name} ({top_level})"
        name_en = f"{name} ({top_level})"
    else:
        name_pt = name_en = name

    return Event(
        name_pt=name_pt,
        name_en=name_en,
        venue_pt=DRAGAO_VENUE,
        venue_en=DRAGAO_VENUE,
        date_info_pt=date_pt,
        date_info_en=date_en,
        nearest_station=DRAGAO_VENUE,
        transport_tip_pt=_DRAGAO_TIP_PT,
        transport_tip_en=_DRAGAO_TIP_EN,
        category="football",
        emoji="⚽",
        start_date=dt.date(),
        end_date=dt.date(),
        source=SOURCE_FCPORTO,
    )


async def fetch_fcporto_fixtures() -> list[Event]:
    """Fetch upcoming FC Porto home fixtures. Raises on transport failure."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(
            FCPORTO_FIXTURES_URL, params=FCPORTO_QUERY,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            headers={"User-Agent": "PortoTransportBot/1.0"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            payload = await resp.json(content_type=None)

    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RuntimeError("unexpected payload shape")

    fixtures = [ev for ev in (_parse_fixture(i) for i in items) if ev]
    return fixtures


def _rebuild(fixtures: list[Event]) -> None:
    """Replace the live part of EVENTS in place, keeping curated entries."""
    merged = list(_CURATED_EVENTS) + list(fixtures)
    merged.sort(key=lambda e: (e.start_date, e.name_pt))
    EVENTS[:] = merged


async def refresh_events(force: bool = False) -> bool:
    """Refresh live fixtures into :data:`EVENTS`.

    Returns True when the live feed was loaded.  On failure the curated dataset
    is left untouched and ``False`` is returned — no invented fixtures are ever
    substituted.
    """
    global _last_fixture_refresh, _fixture_source_ok

    if not force and _last_fixture_refresh is not None:
        age = (now_in_porto() - _last_fixture_refresh).total_seconds()
        if age < FIXTURES_REFRESH_SECONDS:
            return _fixture_source_ok

    _last_fixture_refresh = now_in_porto()
    try:
        fixtures = await fetch_fcporto_fixtures()
    except Exception as exc:
        _fixture_source_ok = False
        logger.warning("Could not fetch FC Porto fixtures (%s) — no football "
                       "events will be shown rather than stale ones", exc)
        return False

    _rebuild(fixtures)
    _fixture_source_ok = True
    logger.info("Loaded %d FC Porto home fixtures at %s",
                len(fixtures), DRAGAO_VENUE)
    return True


#: Set to False to stop the synchronous getters from kicking off background
#: refreshes (e.g. in a worker that refreshes on its own schedule).
AUTO_REFRESH = True


def _auto_refresh_enabled() -> bool:
    # Never start background network tasks inside a test run: they outlive the
    # test's event loop and turn into "Task was destroyed" noise.
    return AUTO_REFRESH and "PYTEST_CURRENT_TEST" not in os.environ


def _maybe_schedule_refresh() -> None:
    """Kick off a background fixture refresh when an event loop is running.

    The public getters are synchronous (the handlers call them directly), so the
    live feed is refreshed opportunistically instead of blocking a request.
    """
    global _refresh_task
    if not _auto_refresh_enabled():
        return
    if _last_fixture_refresh is not None:
        age = (now_in_porto() - _last_fixture_refresh).total_seconds()
        if age < FIXTURES_REFRESH_SECONDS:
            return
    if _refresh_task is not None and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop (e.g. sync tests) — nothing to schedule
    _refresh_task = loop.create_task(refresh_events())


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_todays_events(today: date | None = None) -> list[Event]:
    """Return events happening today (Europe/Lisbon unless ``today`` given)."""
    _maybe_schedule_refresh()
    today = _resolve_today(today)
    _warn_if_stale(today)
    return [e for e in EVENTS if e.start_date <= today <= e.end_date]


def get_upcoming_events(today: date | None = None, limit: int = 5) -> list[Event]:
    """Return the next upcoming events (starting after today)."""
    _maybe_schedule_refresh()
    today = _resolve_today(today)
    _warn_if_stale(today)
    future = [e for e in EVENTS if e.start_date > today]
    future.sort(key=lambda e: e.start_date)
    return future[:limit]


def get_events(category: str | None = None,
               include_past: bool = True,
               today: date | None = None) -> list[Event]:
    """Return events, optionally filtered by category.

    Args:
        category: Category key, or None for all categories.
        include_past: Keep events that have already finished. Defaults to True
            for backward compatibility; pass ``False`` to browse only events
            that are still current or upcoming.
        today: Reference date for ``include_past`` (defaults to Porto's today).
    """
    _maybe_schedule_refresh()
    events = list(EVENTS)
    if category is not None:
        events = [e for e in events if e.category == category]
    if not include_past:
        reference = _resolve_today(today)
        events = [e for e in events if e.end_date >= reference]
    return events


def get_current_events(category: str | None = None,
                       today: date | None = None) -> list[Event]:
    """Events that have not finished yet, optionally filtered by category."""
    return get_events(category, include_past=False, today=today)


def get_event(index: int) -> Event | None:
    """Return a single event by its index in the global EVENTS list."""
    if 0 <= index < len(EVENTS):
        return EVENTS[index]
    return None


def get_event_categories() -> list[str]:
    """Return the list of event category keys."""
    return list(EVENT_CATEGORIES.keys())


def get_events_near_station(station_name: str) -> list[Event]:
    """Return events whose nearest_station matches (case-insensitive)."""
    normalised = station_name.lower()
    return [e for e in EVENTS if e.nearest_station.lower() == normalised]
